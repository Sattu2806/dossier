"""The eval harness: run the whole graph over a set of topics and score it.

Tests (tests/) ask "does the machinery work?" and are deterministic. Evals ask
"is the output any good?" and are not — you run them over many topics and
compare averages before and after a change.

Three rules this harness follows:

1. **Never lose a run.** One topic blowing up must not discard the other 26.
2. **Never pay twice.** Results are cached per topic and keyed by a hash of the
   prompts and model names, so re-running only pays for what actually changed.
3. **Judge with a different model than the writer.** Models rate their own
   style generously.
"""

import csv
import hashlib
import json
import logging
import statistics
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from dossier import nodes, prompts
from dossier.llm import chat_model, model_name

logger = logging.getLogger(__name__)

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"
TOPICS_FILE = EVALS_DIR / "topics.json"
RESULTS_DIR = EVALS_DIR / "results"

JUDGE_RUBRIC = ("groundedness", "completeness", "coherence", "usefulness")


# Model-facing text only. Field order is the reasoning order: the model fills
# the schema top to bottom, so it names flaws and reasons BEFORE it commits to
# numbers. Asked for scores first, it rated everything 5/5 — including a report
# that answered none of its sub-questions.
class JudgeScores(BaseModel):
    """Scores for one research report."""

    weaknesses: list[str] = Field(description="Concrete flaws, naming the passage; empty only if there are none")
    rationale: str = Field(description="Two sentences explaining the scores")
    groundedness: int = Field(description="1 to 5: is every claim supported by the supplied evidence?")
    completeness: int = Field(description="1 to 5: is every sub-question addressed, honest gaps included?")
    coherence: int = Field(description="1 to 5: structure, readability, no repetition or contradiction")
    usefulness: int = Field(description="1 to 5: would a well-informed reader come away better informed?")


def _hash(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


# Bumped when the GRAPH changes shape — a new node, a new edge, a new source.
# Prompts and models are hashed below, but "the pipeline gained a fact-checker"
# is invisible to a prompt hash, and stale results would silently be credited
# to a system that no longer exists.
PIPELINE_VERSION = "3-optional-sources"


def run_fingerprint() -> str:
    """Identifies the system that PRODUCED a report. Changing a node prompt, a
    node model, the pass threshold or the pipeline shape invalidates cached
    runs: a cached score must never be attributed to a system that is gone."""
    return _hash(
        [
            PIPELINE_VERSION,
            prompts.PLANNER_SYSTEM,
            prompts.WRITER_SYSTEM,
            prompts.FACT_CHECKER_SYSTEM,
            prompts.CRITIC_SYSTEM,
            str(nodes.PASS_THRESHOLD),
            *(model_name(role) for role in ("planner", "writer", "factchecker", "critic")),
        ]
    )


def judge_fingerprint() -> str:
    """Identifies the system that SCORED a report. Kept separate on purpose:
    tuning the judge should re-score the reports you already have, not re-run
    every graph — that is the difference between a few cheap calls and paying
    for 27 full pipelines again."""
    return _hash([prompts.JUDGE_SYSTEM, model_name("judge")])


def judge_report(topic: str, sub_questions: list[str], notes: list[dict], report: str) -> dict:
    """LLM-as-judge, run independently of the Critic that was in the loop."""
    evidence, _ = nodes._prepare_evidence(notes)
    request = [
        f"Topic: {topic}",
        "",
        "Sub-questions:",
        *[f"- {question}" for question in sub_questions],
        "",
        "Evidence available to the writer:",
        evidence,
        "",
        "Report:",
        report,
    ]
    scores = (
        chat_model("judge")
        .with_structured_output(JudgeScores)
        .invoke(
            [
                SystemMessage(prompts.JUDGE_SYSTEM),
                HumanMessage("\n".join(request)),
            ]
        )
    )
    result = {dimension: max(1, min(5, getattr(scores, dimension))) for dimension in JUDGE_RUBRIC}
    result["rationale"] = scores.rationale
    result["weaknesses"] = scores.weaknesses
    return result


def _slug(topic: str) -> str:
    keep = "".join(character if character.isalnum() else "-" for character in topic.lower())
    return "-".join(part for part in keep.split("-") if part)[:60]


def run_topic(topic: str, graph, *, judge=judge_report, judge_first_draft: bool = False) -> dict:
    """Run the graph once and collect every metric we can measure cheaply."""
    started = time.time()
    drafts: list[str] = []
    state: dict = {}
    error = None

    try:
        # stream_mode="values" yields the FULL state after each step, already
        # merged by the reducers. Rebuilding it from per-task updates instead
        # would silently overwrite the parallel researchers' notes, leaving 1
        # note where there were 12 — and every note-based metric would be wrong.
        for snapshot in graph.stream({"topic": topic}, stream_mode="values"):
            state = snapshot
            draft = snapshot.get("draft")
            if draft and (not drafts or draft != drafts[-1]):
                drafts.append(draft)
    except Exception as exc:  # one bad topic must not end the eval
        logger.warning("run failed for %r: %s: %s", topic, type(exc).__name__, exc)
        error = f"{type(exc).__name__}: {exc}"

    notes = state.get("research_notes", [])
    report = state.get("final_report", "")
    sources = nodes._prepare_evidence(notes)[1] if notes else {}
    cited = nodes.cited_numbers(report)

    result = {
        "topic": topic,
        "error": error,
        "duration_s": round(time.time() - started, 1),
        "sub_questions": state.get("sub_questions", []),
        "notes_ok": sum(1 for note in notes if note["status"] == "ok"),
        "notes_missing": sum(1 for note in notes if note["status"] != "ok"),
        "sources_available": len(sources),
        "sources_cited": len(cited & sources.keys()),
        "citations_invented": len(cited - sources.keys()),
        "word_count": len(report.split()),
        "revision_count": state.get("revision_count", 0),
        "critique_passed": state.get("critique_passed"),
        "critique_scores": state.get("critique_scores", {}),
        "report": report,
        "first_draft": drafts[0] if drafts else "",
        # Kept so a failed judging pass can be retried later without paying to
        # run the whole graph again.
        "research_notes": notes,
    }

    return ensure_judged(result, judge=judge, judge_first_draft=judge_first_draft)


def ensure_judged(result: dict, *, judge=judge_report, judge_first_draft: bool = False) -> dict:
    """Add judge scores if they are missing. Safe to call on a cached result.

    The judge is a network call like any other, and a 503 from it must not
    destroy a run that already cost a planner, four searches and two drafts.
    """
    if result["error"] or not result["report"] or result.get("judge"):
        return result

    notes = result.get("research_notes", [])
    if not notes and result.get("notes_ok", 0) + result.get("notes_missing", 0) > 0:
        # The run had notes but this cached copy didn't keep them. Judging
        # anyway would score the report against NO evidence and call it
        # ungrounded — a made-up number that looks like a real one.
        result["judge_error"] = "cached result has no research_notes; re-run this topic"
        return result

    try:
        result["judge"] = judge(result["topic"], result["sub_questions"], notes, result["report"])
        if judge_first_draft and result.get("first_draft"):
            # Answers the question Lesson 4 raised: is the revision loop worth
            # what it costs? Same judge, same evidence, first draft vs final.
            result["judge_first_draft"] = judge(result["topic"], result["sub_questions"], notes, result["first_draft"])
        result.pop("judge_error", None)
    except Exception as exc:
        logger.warning("judging failed for %r: %s: %s", result["topic"], type(exc).__name__, exc)
        result["judge_error"] = f"{type(exc).__name__}: {exc}"
    return result


def load_topics(path: Path = TOPICS_FILE) -> list[dict]:
    return json.loads(path.read_text())


def evaluate(
    topics: list[dict],
    graph,
    *,
    results_dir: Path = RESULTS_DIR,
    limit: int | None = None,
    force: bool = False,
    judge=judge_report,
    judge_first_draft: bool = False,
) -> list[dict]:
    """Run every topic, caching each result on disk."""
    results_dir.mkdir(parents=True, exist_ok=True)
    run_config, judge_config = run_fingerprint(), judge_fingerprint()
    selected = topics[:limit] if limit else topics
    results = []

    for index, entry in enumerate(selected, start=1):
        topic = entry["topic"]
        cache_file = results_dir / f"{_slug(topic)}.json"

        if cache_file.exists() and not force:
            cached = json.loads(cache_file.read_text())
            if cached.get("run_config") == run_config:
                # The expensive part is still valid. Re-judge only if the judge
                # changed or its last attempt failed — a few cheap calls
                # instead of running the whole graph again.
                if cached.get("judge_config") != judge_config or cached.get("judge_error"):
                    print(f"[{index}/{len(selected)}] re-judging: {topic}")
                    cached.pop("judge", None)
                    cached.pop("judge_first_draft", None)
                    ensure_judged(cached, judge=judge, judge_first_draft=judge_first_draft)
                    cached["judge_config"] = judge_config
                    cache_file.write_text(json.dumps(cached, indent=2))
                else:
                    print(f"[{index}/{len(selected)}] cached: {topic}")
                results.append(cached)
                continue

        print(f"[{index}/{len(selected)}] running: {topic}")
        result = run_topic(topic, graph, judge=judge, judge_first_draft=judge_first_draft)
        result["category"] = entry.get("category", "")
        result["run_config"] = run_config
        result["judge_config"] = judge_config
        # Failed runs are not cached: a 503 or a quota wall is a fact about
        # today, not about the system, and the next pass should retry it.
        if not result["error"]:
            cache_file.write_text(json.dumps(result, indent=2))
        results.append(result)

        status = result["error"] or f"judge={result.get('judge', {}).get('usefulness', '-')}/5"
        print(f"    {result['duration_s']}s  drafts={result['revision_count']}  {status}")

    return results


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def summarize(results: list[dict]) -> dict:
    """Aggregate — the numbers that go in the README."""
    ok = [result for result in results if not result["error"] and result.get("judge")]
    judged = [result["judge"] for result in ok]

    summary = {
        "topics": len(results),
        "failed_runs": sum(1 for result in results if result["error"]),
        # Scored averages below cover `judged` runs only. This number must sit
        # next to them: an average over 7 of 27 topics is not a benchmark.
        "judged": len(ok),
        "unjudged_runs": sum(1 for result in results if not result["error"] and not result.get("judge")),
        "avg_revisions": _mean([result["revision_count"] for result in ok]),
        "passed_first_draft_pct": round(100 * sum(1 for result in ok if result["revision_count"] == 1) / len(ok), 1)
        if ok
        else None,
        "critic_passed_pct": round(100 * sum(1 for result in ok if result["critique_passed"]) / len(ok), 1)
        if ok
        else None,
        "avg_word_count": _mean([result["word_count"] for result in ok]),
        "avg_sources_cited": _mean([result["sources_cited"] for result in ok]),
        "runs_with_missing_evidence": sum(1 for result in ok if result["notes_missing"]),
        "invented_citations": sum(result["citations_invented"] for result in ok),
        "avg_duration_s": _mean([result["duration_s"] for result in ok]),
    }
    for dimension in JUDGE_RUBRIC:
        summary[f"judge_{dimension}"] = _mean([judge[dimension] for judge in judged])

    first = [result for result in ok if result.get("judge_first_draft")]
    if first:
        summary["first_draft_judge_avg"] = _mean(
            [statistics.mean([result["judge_first_draft"][d] for d in JUDGE_RUBRIC]) for result in first]
        )
        summary["final_draft_judge_avg"] = _mean(
            [statistics.mean([result["judge"][d] for d in JUDGE_RUBRIC]) for result in first]
        )
    return summary


CSV_COLUMNS = [
    "topic",
    "category",
    "revision_count",
    "critique_passed",
    "word_count",
    "sources_cited",
    "citations_invented",
    "notes_missing",
    "duration_s",
    "error",
]


def write_outputs(results: list[dict], summary: dict, results_dir: Path = RESULTS_DIR) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    with (results_dir / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS + list(JUDGE_RUBRIC))
        writer.writeheader()
        for result in results:
            row = {column: result.get(column) for column in CSV_COLUMNS}
            row.update({dimension: result.get("judge", {}).get(dimension) for dimension in JUDGE_RUBRIC})
            writer.writerow(row)
