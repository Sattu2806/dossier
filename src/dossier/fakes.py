"""Deterministic fake nodes: no LLM, no network, no API key.

Two uses:
- tests run the whole graph with these, so they are fast, free and repeatable
- `dossier run --offline` runs the graph mechanics without any keys

Each real node in nodes.py keeps its fake here. Until a real node is built,
graph.py uses the fake as the default.
"""

from dossier.state import Note, ResearcherTask, ResearchState


def planner(state: ResearchState) -> dict:
    topic = state["topic"]
    return {
        "sub_questions": [
            f"What is {topic}?",
            f"What is the current state of {topic}?",
            f"What are the open problems in {topic}?",
        ]
    }


def researcher(task: ResearcherTask) -> dict:
    # One researcher handles ONE sub-question (see nodes.fan_out_to_researchers).
    question = task["question"]
    note: Note = {
        "sub_question": question,
        "origin": task.get("origin", "web"),
        "status": "ok",
        "title": "Example source",
        "source_url": "https://example.com/stub",
        "content": f"(stub) Findings for: {question}",
    }
    return {"research_notes": [note]}


def writer(state: ResearchState) -> dict:
    # .get() because on the first pass none of these exist yet. Mirrors the
    # real writer: both reviewers' feedback reaches the draft.
    draft_number = state.get("revision_count", 0) + 1
    feedback = "\n".join(part for part in (state.get("fact_feedback"), state.get("critique_feedback")) if part)

    # " [1]" because the real writer cites sources, and finalize only lists
    # sources the draft actually cited. All fake notes share one URL = [1].
    sections = [f"## {note['sub_question']}\n{note['content']} [1]" for note in state["research_notes"]]
    draft = f"# Report: {state['topic']} (draft {draft_number})\n\n" + "\n\n".join(sections)
    if feedback:
        draft += f"\n\n_(Revised to address: {feedback})_"

    return {"draft": draft, "revision_count": draft_number}


def fact_checker(state: ResearchState) -> dict:
    return {"grounded": True, "unsupported_claims": [], "fact_feedback": ""}


def critic(state: ResearchState) -> dict:
    # Reject the first draft, accept the second, so a run goes around the
    # Writer -> Critic loop exactly once.
    if state["revision_count"] < 2:
        return {
            "critique_passed": False,
            "critique_feedback": "- Add a conclusion section.",
            "critique_scores": {"groundedness": 4, "completeness": 3, "coherence": 4},
        }
    return {
        "critique_passed": True,
        "critique_feedback": "",
        "critique_scores": {"groundedness": 5, "completeness": 4, "coherence": 4},
    }


FAKE_NODES = {
    "planner": planner,
    "researcher": researcher,
    "writer": writer,
    "fact_checker": fact_checker,
    "critic": critic,
}


def judge(topic: str, sub_questions: list[str], notes: list, report: str) -> dict:
    """Deterministic stand-in for the LLM judge, for `dossier eval --offline`."""
    return {
        "groundedness": 4,
        "completeness": 4,
        "coherence": 4,
        "usefulness": 3,
        "rationale": "(fake judge) Scores are fixed; only the harness is being exercised.",
    }
