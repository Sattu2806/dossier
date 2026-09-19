"""The shared state that flows through every node of the graph.

Think of this as the contract between agents. A node never calls another
node — it reads what it needs from the state and returns the fields it wants
to change. LangGraph merges that partial update back into the state and
hands the result to whichever node runs next.
"""

import operator
from typing import Annotated, Literal, Required, TypedDict


class Note(TypedDict):
    """One piece of evidence. Keeping the source next to the content is what
    lets the Critic and the Fact-Checker trace a claim back to where it came
    from."""

    sub_question: str
    # "web" or "docs": the same note shape carries both, so every later node
    # treats an uploaded PDF and a web page identically.
    origin: str
    # A failed or empty search is recorded as a note too, so the Writer and
    # Critic can SEE the gap instead of silently inventing an answer for it.
    # A typed field beats hunting for "[no results]" inside content.
    status: Literal["ok", "no_results", "error"]
    title: str
    source_url: str
    content: str


class ResearcherTask(TypedDict):
    """What one researcher receives. Not the full state: each researcher is
    sent exactly one sub-question via Send(), for exactly one source."""

    question: str
    origin: str


# total=False: every key is optional unless marked Required. Only `topic`
# exists when a run starts; the rest appear as nodes write them.
class ResearchState(TypedDict, total=False):
    # Input — the only thing the caller provides.
    topic: Required[str]

    # Written by Planner.
    sub_questions: list[str]

    # Written by Researcher — by SEVERAL researchers, in the same step.
    # operator.add is the reducer: concurrent updates are appended instead of
    # overwriting each other. Without it LangGraph raises InvalidUpdateError
    # ("can receive only one value per step").
    research_notes: Annotated[list[Note], operator.add]

    # Written by Writer. revision_count = how many drafts have been written,
    # so it is 1 after the first draft.
    draft: str
    revision_count: int

    # Written by Fact-Checker — a separate node from the Critic because
    # "is this claim supported?" is a different question from "is this report
    # any good?", and mixing them makes both answers worse.
    grounded: bool
    unsupported_claims: list[str]
    fact_feedback: str

    # Written by Critic. `critique_passed` is a separate boolean on purpose:
    # the router branches on it, and routing on a bool is reliable where
    # parsing "does the feedback text sound positive?" is not.
    critique_passed: bool
    critique_feedback: str
    # Kept because evals report them: "average groundedness" is only possible
    # if the numbers survive the run.
    critique_scores: dict[str, int]

    # Written by Finalize.
    final_report: str
