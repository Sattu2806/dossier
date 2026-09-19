"""Tests for graph *mechanics* — routing, loop cap, data flow.

These say nothing about report quality (that is what evals are for in
Step 8). They pin down the plumbing so that when LLM nodes arrive, a broken
run is a prompt problem, not a wiring problem.

Every graph here is built from fakes: no LLM, no network, no API key.
"""

import pytest
from langchain_core.exceptions import OutputParserException
from langgraph.errors import GraphRecursionError
from langgraph.types import RetryPolicy

import dossier.graph
from dossier.fakes import FAKE_NODES
from dossier.graph import MAX_REVISIONS, build_graph, route_after_critic


def offline_graph(**overrides):
    """The graph with every LLM node faked; override individual nodes by name."""
    return build_graph(**(FAKE_NODES | overrides))


def approve(state):
    return {"critique_passed": True, "critique_feedback": ""}


def reject(state):
    return {"critique_passed": False, "critique_feedback": "Not good enough."}


def visited_nodes(graph, topic="test topic"):
    return [node for update in graph.stream({"topic": topic}, stream_mode="updates") for node in update]


# --- The router on its own: a plain function, no graph needed -----------------


def test_router_finalizes_when_critique_passes():
    assert route_after_critic({"topic": "t", "critique_passed": True, "revision_count": 1}) == "finalize"


def test_router_loops_back_when_critique_fails_under_cap():
    assert route_after_critic({"topic": "t", "critique_passed": False, "revision_count": 1}) == "writer"


def test_router_gives_up_at_cap():
    state = {"topic": "t", "critique_passed": False, "revision_count": MAX_REVISIONS}
    assert route_after_critic(state) == "finalize"


# --- The whole graph ---------------------------------------------------------


def test_fake_run_fans_out_then_loops_exactly_once():
    graph = offline_graph()
    visited = visited_nodes(graph)
    # The fake planner returns 3 sub-questions, so 3 researchers run. They all
    # run inside ONE super-step, but the stream reports each update separately.
    assert visited[:5] == ["validate", "planner", "researcher", "researcher", "researcher"]
    assert visited[5:] == [
        "writer",
        "fact_checker",
        "critic",
        "writer",
        "fact_checker",
        "critic",
        "finalize",
    ]

    result = graph.invoke({"topic": "solid-state batteries"})
    assert result["revision_count"] == 2
    assert result["critique_passed"] is True
    # finalize appends a source list built from the notes, not from the LLM.
    assert result["final_report"].startswith(result["draft"])
    assert "## Sources\n[1] Example source — https://example.com/stub" in result["final_report"]


def test_critic_that_approves_skips_the_loop():
    graph = offline_graph(critic=approve)
    assert visited_nodes(graph)[5:] == ["writer", "fact_checker", "critic", "finalize"]


def test_critic_that_never_approves_stops_at_max_revisions():
    result = offline_graph(critic=reject).invoke({"topic": "test topic"})
    assert result["revision_count"] == MAX_REVISIONS
    assert result["critique_passed"] is False
    assert result["final_report"]  # finalized anyway, not stuck


def test_writer_sees_critic_feedback_on_revision():
    result = offline_graph(critic=reject).invoke({"topic": "test topic"})
    assert "Not good enough." in result["final_report"]


def test_recursion_limit_catches_a_missing_cap(monkeypatch):
    # Simulate the bug "someone removed the revision cap".
    monkeypatch.setattr(dossier.graph, "MAX_REVISIONS", 10**9)
    with pytest.raises(GraphRecursionError):
        offline_graph(critic=reject).invoke({"topic": "test topic"})


def test_fan_out_runs_one_researcher_per_sub_question_and_appends_notes():
    def planner_with_five(state):
        return {"sub_questions": [f"Question {i}?" for i in range(5)]}

    result = offline_graph(planner=planner_with_five).invoke({"topic": "test topic"})

    # 5 researchers each returned 1 note, and the operator.add reducer appended
    # all of them instead of letting the last writer win.
    assert len(result["research_notes"]) == 5
    assert {note["sub_question"] for note in result["research_notes"]} == {f"Question {i}?" for i in range(5)}


def test_parallel_researchers_cost_only_one_super_step():
    # 12 sub-questions still fit inside RECURSION_LIMIT, because fan-out is one
    # step no matter how wide it is.
    def planner_with_twelve(state):
        return {"sub_questions": [f"Question {i}?" for i in range(12)]}

    result = offline_graph(planner=planner_with_twelve).invoke({"topic": "test topic"})
    assert len(result["research_notes"]) == 12


def test_an_ungrounded_draft_is_sent_back_even_when_the_critic_passes():
    # The two reviewers are independent gates: the Critic can love a report
    # that the Fact-Checker has just caught inventing figures.
    def unsupported(state):
        return {
            "grounded": False,
            "unsupported_claims": ["Market reached $4.2bn"],
            "fact_feedback": "- Unsupported: Market reached $4.2bn",
        }

    result = offline_graph(fact_checker=unsupported, critic=approve).invoke({"topic": "test topic"})

    assert result["revision_count"] == MAX_REVISIONS  # kept trying, then gave up
    assert result["critique_passed"] is True
    assert result["grounded"] is False
    assert result["final_report"]  # still finalised rather than looping forever


def test_fact_check_feedback_reaches_the_writer():
    def unsupported(state):
        return {
            "grounded": False,
            "unsupported_claims": ["X"],
            "fact_feedback": "- Unsupported: invented figure",
        }

    result = offline_graph(fact_checker=unsupported, critic=approve).invoke({"topic": "test topic"})
    assert "invented figure" in result["final_report"]


def test_building_the_real_graph_needs_no_api_key(monkeypatch):
    # LLM clients are created lazily, on first call, not at import or build time.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    build_graph()


# --- Retries ------------------------------------------------------------------


@pytest.fixture
def instant_retries(monkeypatch):
    """Same retry rule as production, without the backoff sleeps."""
    policy = RetryPolicy(max_attempts=3, initial_interval=0, jitter=False, retry_on=OutputParserException)
    monkeypatch.setattr(dossier.graph, "LLM_OUTPUT_RETRY", policy)


def test_planner_is_retried_when_llm_output_is_unusable(instant_retries):
    calls = []

    def flaky_planner(state):
        calls.append(1)
        if len(calls) == 1:
            raise OutputParserException("model returned invalid JSON")
        return FAKE_NODES["planner"](state)

    result = offline_graph(planner=flaky_planner).invoke({"topic": "test topic"})
    assert len(calls) == 2
    assert result["final_report"]


def test_planner_bugs_are_not_retried(instant_retries):
    calls = []

    def buggy_planner(state):
        calls.append(1)
        return {"sub_questions": state["typo_in_key"]}  # KeyError: a bug, not bad model output

    with pytest.raises(KeyError):
        offline_graph(planner=buggy_planner).invoke({"topic": "test topic"})
    assert len(calls) == 1
