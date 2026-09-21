"""The real nodes.

Every node has the same shape:  (state) -> dict of fields to update.
Nodes that are not built yet still use their fake from fakes.py.
"""

import logging
import os
import re
import time

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Send, interrupt
from pydantic import BaseModel, Field

from dossier.docstore import doc_search, document_count
from dossier.guardrails import validate_topic
from dossier.llm import chat_model
from dossier.prompts import CRITIC_SYSTEM, FACT_CHECKER_SYSTEM, PLANNER_SYSTEM, WRITER_SYSTEM
from dossier.search import web_search
from dossier.state import Note, ResearcherTask, ResearchState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate(state: ResearchState) -> dict:
    """First node in the graph, so no caller can skip it — CLI, API and MCP
    all get the same check. Returns the cleaned topic; raises InvalidTopic."""
    return {"topic": validate_topic(state["topic"])}


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

MAX_SUB_QUESTIONS = 5


# The shape we force the LLM's reply into.
#
# Careful: this class's docstring and every Field description end up in the
# JSON schema sent to the model, so they are PROMPT TEXT. Notes meant for
# developers go in comments like this one, never in the docstring.
#
# There is deliberately no hard min/max length: a sixth question isn't worth
# crashing a run over, so the node trims instead.
class Plan(BaseModel):
    """A research plan for the given topic."""

    sub_questions: list[str] = Field(description="3 to 5 self-contained research sub-questions")


def _clean(questions: list[str]) -> list[str]:
    """Strip whitespace, drop blanks and case-insensitive duplicates, keep order."""
    seen: set[str] = set()
    cleaned = []
    for question in questions:
        question = question.strip()
        if question and question.lower() not in seen:
            seen.add(question.lower())
            cleaned.append(question)
    return cleaned


def planner(state: ResearchState) -> dict:
    # with_structured_output makes Gemini reply in JSON matching Plan's schema
    # and parses it into a Plan object. We never parse free text ourselves.
    model = chat_model("planner").with_structured_output(Plan)

    # Instructions go in the system message and the topic in the user
    # message. The topic is untrusted user input and should never be able to
    # rewrite our instructions.
    plan = model.invoke([SystemMessage(PLANNER_SYSTEM), HumanMessage(f"Topic: {state['topic']}")])

    questions = _clean(plan.sub_questions)
    if not questions:
        # Same exception as unparseable output: the model's reply is unusable,
        # so the graph's retry policy should try again.
        raise OutputParserException("Planner returned no sub-questions")
    return {"sub_questions": questions[:MAX_SUB_QUESTIONS]}


# ---------------------------------------------------------------------------
# Approve the plan
# ---------------------------------------------------------------------------


def approve_plan(state: ResearchState) -> dict:
    """Stop and show the plan before anyone pays for searches.

    This is the cheapest possible place to interrupt: the Planner has cost one
    call, and everything expensive — N parallel searches, three drafts, two
    reviewers — is still ahead. Dropping two sub-questions here is a real
    saving, not a gesture.

    `interrupt()` raises on the way out and re-runs this node from the top on
    resume, so nothing above it in this function may have side effects. It
    needs a checkpointer; without one the pause has nowhere to live.
    """
    decision = interrupt({"topic": state["topic"], "sub_questions": state["sub_questions"]})

    edited = _edited_questions(decision)
    if edited is None:
        return {}

    # An empty edit means "I deleted everything", which cannot be researched.
    # Keeping the plan is friendlier than failing: to cancel, simply never
    # resume — an interrupt nobody answers costs nothing and expires with its
    # checkpoint.
    if not edited:
        logger.warning("plan edited to nothing; keeping the planner's questions")
        return {}

    logger.info("plan edited: %d questions -> %d", len(state["sub_questions"]), len(edited))
    return {"sub_questions": edited}


def _edited_questions(decision) -> list[str] | None:
    """The sub-questions a client sent back, or None for plain approval.

    Accepts the shapes a client naturally sends: a bare list, a dict carrying
    one, or anything else meaning "approved as planned".
    """
    if isinstance(decision, dict):
        decision = decision.get("sub_questions")
    if not isinstance(decision, list):
        return None
    return _clean([str(question) for question in decision])[:MAX_SUB_QUESTIONS]


# ---------------------------------------------------------------------------
# Researcher
# ---------------------------------------------------------------------------

# Tavily snippets are usually a few hundred characters, but a long one would
# quietly inflate every later prompt. Cap it here, where the note is created.
MAX_NOTE_CHARS = 1000

# One retry, then degrade. Observed in a real run: four concurrent Tavily
# searches all timed out at once and the report came back empty but honest.
# A single retry recovers from that without the "retry until the run dies"
# failure mode of a node-level RetryPolicy.
SEARCH_ATTEMPTS = 2
SEARCH_RETRY_DELAY = 1.0


# Where evidence can come from. Each entry is a function with the same
# signature: query -> [{title, url, content}]. Adding an internal wiki or a
# ticket system means adding one line here.
SOURCES = {"web": web_search, "docs": doc_search}

# Sources that are expected to be silent most of the time. The web finding
# nothing for a sub-question is a gap the Writer must be told about; your
# documents having nothing to say about Rust is just Tuesday, and recording it
# as a gap made every run look like it had missing evidence.
OPTIONAL_SOURCES = {"docs"}


def available_origins() -> list[str]:
    """Routing: only search documents when documents have been ingested.

    Without this, every run would fan out to a doc researcher that can only
    return "no results" — paying for a step that cannot succeed.
    """
    return ["web", "docs"] if document_count() else ["web"]


def fan_out_to_researchers(state: ResearchState) -> list[Send]:
    """Start one researcher per sub-question per source, all in one step.

    This is a router like route_after_critic, but instead of one destination
    it returns a list of Send objects, each carrying the input for ONE run of
    the node. 4 sub-questions across 2 sources is 8 researchers in parallel —
    and still a single super-step.
    """
    origins = available_origins()
    return [
        Send("researcher", ResearcherTask(question=question, origin=origin))
        for question in state["sub_questions"]
        for origin in origins
    ]


def _gap_note(question: str, origin: str, status: str, reason: str) -> Note:
    """A note that records the absence of evidence, so later nodes can see it."""
    return {
        "sub_question": question,
        "origin": origin,
        "status": status,
        "title": "",
        "source_url": "",
        "content": reason,
    }


def _search_with_retry(search, question: str, origin: str) -> list[dict]:
    for attempt in range(1, SEARCH_ATTEMPTS + 1):
        try:
            return search(question)
        except Exception as exc:
            if attempt == SEARCH_ATTEMPTS:
                raise
            logger.info("%s search attempt %d failed (%s), retrying", origin, attempt, type(exc).__name__)
            time.sleep(SEARCH_RETRY_DELAY)
    return []


def researcher(task: ResearcherTask) -> dict:
    """Search one sub-question in one source. Never raises: a dead search must
    not kill the other researchers running beside it, or the whole run."""
    question = task["question"]
    origin = task.get("origin", "web")
    search = SOURCES[origin]

    try:
        results = _search_with_retry(search, question, origin)
    except Exception as exc:
        # Tavily's exceptions (timeout, bad key, usage limit) share no common
        # base class, and an embedding call can fail just as many ways, so we
        # catch broadly — but ONLY around the search call, never around our own
        # code, where a bug should still surface.
        logger.warning("%s search failed for %r: %s: %s", origin, question, type(exc).__name__, exc)
        return {"research_notes": [_gap_note(question, origin, "error", f"Search failed ({type(exc).__name__}).")]}

    if not results:
        if origin in OPTIONAL_SOURCES:
            logger.info("no relevant %s results for %r", origin, question)
            return {"research_notes": []}
        logger.warning("no %s results for %r", origin, question)
        return {"research_notes": [_gap_note(question, origin, "no_results", "No search results found.")]}

    notes: list[Note] = [
        {
            "sub_question": question,
            "origin": origin,
            "status": "ok",
            "title": result.get("title", ""),
            "source_url": result.get("url", ""),
            "content": (result.get("content") or "")[:MAX_NOTE_CHARS],
        }
        for result in results
    ]
    return {"research_notes": notes}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

NO_EVIDENCE_MARKER = "NO EVIDENCE AVAILABLE"


def _prepare_evidence(notes: list[Note]) -> tuple[str, dict[int, str]]:
    """Turn notes into (evidence block for the prompt, numbered source list).

    Citation numbers are assigned per unique URL, so the same page found by two
    sub-questions keeps one number. The model cites [2]; it never writes URLs,
    because models mangle them — we render the source list ourselves from the
    same numbering. Pure function: same notes in, same numbers out, which is
    why the Writer and Finalize can both call it instead of storing the result.
    """
    numbers: dict[str, int] = {}
    sources: dict[int, str] = {}
    blocks: list[str] = []

    # dict.fromkeys keeps first-seen order while removing duplicates.
    for question in dict.fromkeys(note["sub_question"] for note in notes):
        group = [note for note in notes if note["sub_question"] == question]
        usable = [note for note in group if note["status"] == "ok"]

        blocks.append(f"### Sub-question: {question}")
        if not usable:
            blocks.append(f"{NO_EVIDENCE_MARKER} — {group[0]['content']}")
            continue

        for note in usable:
            key = note["source_url"] or note["title"] or f"unnamed-{len(numbers)}"
            if key not in numbers:
                numbers[key] = len(numbers) + 1
                sources[numbers[key]] = f"{note['title'] or 'Untitled'} — {note['source_url']}"
            blocks.append(f"[{numbers[key]}] {note['title']}\n{note['content']}")

    return "\n".join(blocks), sources


def writer(state: ResearchState) -> dict:
    evidence, _ = _prepare_evidence(state["research_notes"])
    draft_number = state.get("revision_count", 0) + 1

    request = [f"Topic: {state['topic']}", "", "Evidence:", evidence]

    # On a revision, the feedback refers to specific parts of the previous
    # draft, so the model must see that draft as well. Without it, "section 2
    # is vague" is unactionable and the model rewrites blind.
    previous_draft = state.get("draft")
    # Both reviewers' findings reach the Writer: the Fact-Checker's list of
    # unsupported statements and the Critic's quality issues.
    feedback = "\n".join(part for part in (state.get("fact_feedback"), state.get("critique_feedback")) if part)
    if previous_draft and feedback:
        request += ["", "Your previous draft:", previous_draft, "", "Reviewer feedback to address:", feedback]

    # No structured output here: the result is prose, not fields. `.text`
    # flattens whatever the provider returns (a plain string, or a list of
    # content blocks for a thinking model) into text.
    reply = chat_model("writer").invoke([SystemMessage(WRITER_SYSTEM), HumanMessage("\n".join(request))])
    draft = reply.text.strip()
    if not draft:
        raise OutputParserException("Writer returned an empty draft")

    return {"draft": draft, "revision_count": draft_number}


# ---------------------------------------------------------------------------
# Fact-checker
# ---------------------------------------------------------------------------


# Claims first, verdict second: the model lists what it found before it is
# asked to conclude anything, and the conclusion itself is computed in code.
class FactCheck(BaseModel):
    """Statements in a report that the evidence does not support."""

    unsupported_claims: list[str] = Field(
        description="Quoted statements the evidence does not support; empty if every statement checks out"
    )


def fact_checker(state: ResearchState) -> dict:
    """Separate from the Critic on purpose: catching a fabricated number and
    grading a report's quality are different jobs, and a node asked to do both
    does neither well. This one only asks "does the evidence say this?"."""
    evidence, _ = _prepare_evidence(state["research_notes"])
    request = [
        "Evidence:",
        evidence,
        "",
        "Report to check:",
        state["draft"],
    ]

    check = (
        chat_model("factchecker")
        .with_structured_output(FactCheck)
        .invoke([SystemMessage(FACT_CHECKER_SYSTEM), HumanMessage("\n".join(request))])
    )

    claims = [claim.strip() for claim in check.unsupported_claims if claim.strip()]
    feedback = "\n".join(f"- Unsupported: {claim}" for claim in claims)
    logger.info("fact check: %d unsupported claims", len(claims))

    return {
        "grounded": not claims,  # the verdict is ours, not the model's
        "unsupported_claims": claims,
        "fact_feedback": feedback,
    }


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------

RUBRIC = ("groundedness", "completeness", "coherence")

# Every dimension must reach this for the draft to pass. This lives in code,
# not in the prompt: the model's job is to judge each dimension, and the
# policy ("what counts as good enough") is ours. Changing the bar then means
# changing one number and re-running the evals, not rewriting a prompt.
# Overridable so an experiment is one environment variable, not a code edit —
# and it is part of the eval fingerprint, so results can't be confused.
PASS_THRESHOLD = int(os.getenv("DOSSIER_PASS_THRESHOLD", "4"))

# A sub-question the report never addresses caps completeness here.
UNCOVERED_COMPLETENESS_CAP = 2


# Model-facing text only (see the note on Plan above).
class Critique(BaseModel):
    """A review of a research report."""

    # First field on purpose: the model fills the schema in order, so listing
    # the uncovered sub-questions makes it check them one by one BEFORE it
    # scores completeness. Asked only for a score, it rated a draft that
    # skipped a whole sub-question 5/5.
    uncovered_sub_questions: list[str] = Field(
        description="Sub-questions the report does not address at all; empty if every one is addressed"
    )
    groundedness: int = Field(description="1 to 5: is every claim supported by the evidence and cited correctly?")
    completeness: int = Field(description="1 to 5: is every sub-question addressed, counting honest gaps as covered?")
    coherence: int = Field(description="1 to 5: structure, readability, no repetition or contradiction")
    issues: list[str] = Field(description="Specific, actionable issues; empty if the report is sound")


def _clamp_score(value: int) -> int:
    """Scores outside 1-5 are meaningless, but not worth failing a run over."""
    return max(1, min(5, value))


def critic(state: ResearchState) -> dict:
    evidence, _ = _prepare_evidence(state["research_notes"])
    request = [
        f"Topic: {state['topic']}",
        "",
        "Sub-questions the report must cover:",
        *[f"- {question}" for question in state["sub_questions"]],
        "",
        # Without the evidence, "is every claim traceable to a source?" is
        # unanswerable and the critic just grades prose style.
        "Evidence the writer was given:",
        evidence,
        "",
        "Report to review:",
        state["draft"],
    ]

    review = (
        chat_model("critic")
        .with_structured_output(Critique)
        .invoke([SystemMessage(CRITIC_SYSTEM), HumanMessage("\n".join(request))])
    )

    scores = {dimension: _clamp_score(getattr(review, dimension)) for dimension in RUBRIC}

    # Policy in code again: a missing sub-question is a completeness failure by
    # definition, whatever the model scored it.
    uncovered = [question for question in review.uncovered_sub_questions if question.strip()]
    if uncovered:
        scores["completeness"] = min(scores["completeness"], UNCOVERED_COMPLETENESS_CAP)

    passed = all(score >= PASS_THRESHOLD for score in scores.values())

    issues = [f"The report does not address the sub-question: {question}" for question in uncovered]
    issues += [issue for issue in review.issues if issue.strip()]
    feedback = "\n".join(f"- {issue}" for issue in issues)
    if not passed and not feedback:
        # A rejection with no issues would reach the Writer as empty feedback,
        # which it would read as "first draft" and rewrite from scratch.
        worst = min(scores, key=scores.get)
        feedback = f"- Improve {worst} (scored {scores[worst]}/5)."

    logger.info("critique scores=%s passed=%s issues=%d", scores, passed, len(review.issues))
    return {"critique_passed": passed, "critique_feedback": feedback, "critique_scores": scores}


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


def cited_numbers(draft: str) -> set[int]:
    """Every [n] the draft actually cites."""
    return {int(number) for number in re.findall(r"\[(\d+)\]", draft)}


def finalize(state: ResearchState) -> dict:
    """Attach the source list. It is derived from the notes, not written by the
    LLM, so a citation can never point at a URL the model invented.

    Only cited sources are listed: the Writer is given more evidence than it
    ends up using, and a "Sources" section should say what the report used.
    """
    draft = state["draft"]
    _, sources = _prepare_evidence(state["research_notes"])
    cited = cited_numbers(draft)

    # A citation number we never handed out means the model made one up. Cheap
    # check now; Phase 2's Fact-Checker judges whether cited claims hold up.
    invented = cited - sources.keys()
    if invented:
        logger.warning("draft cites source numbers that do not exist: %s", sorted(invented))

    used = [f"[{number}] {sources[number]}" for number in sorted(cited & sources.keys())]
    report = draft
    if used:
        report += "\n\n## Sources\n" + "\n".join(used)
    return {"final_report": report}
