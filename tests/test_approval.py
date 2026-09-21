"""Pausing a run so a human can edit the plan before money is spent.

The point of interrupting after the Planner is that everything expensive is
still ahead, so the tests that matter are the ones that count researcher
calls — not the ones that check a flag.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from dossier import checkpoints, fakes
from dossier.graph import build_graph


@pytest.fixture
def searched():
    """Every sub-question a researcher was actually asked to look up."""
    return []


@pytest.fixture
def graph(searched):
    def counting_researcher(task):
        searched.append(task["question"])
        return fakes.researcher(task)

    return build_graph(**{**fakes.FAKE_NODES, "researcher": counting_researcher}, approval=True)


def thread(name="t1"):
    return {"configurable": {"thread_id": name}}


def start(graph, topic="solid-state batteries", name="t1"):
    return graph.invoke({"topic": topic}, thread(name))


def paused_plan(result):
    return result["__interrupt__"][0].value


# --- the pause ----------------------------------------------------------------


def test_the_run_stops_before_a_single_search_is_paid_for(graph, searched):
    start(graph)
    assert searched == []


def test_the_pause_hands_back_the_plan_to_look_at(graph):
    plan = paused_plan(start(graph))
    assert plan["topic"] == "solid-state batteries"
    assert len(plan["sub_questions"]) == 3


def test_the_graph_knows_it_is_waiting_at_the_approve_node(graph):
    start(graph)
    assert graph.get_state(thread()).next == ("approve",)


# --- resuming -----------------------------------------------------------------


def test_approving_researches_the_plan_as_written(graph, searched):
    start(graph)
    result = graph.invoke(Command(resume=True), thread())

    assert len(searched) == 3
    assert result["final_report"]


def test_editing_the_plan_changes_what_is_searched(graph, searched):
    start(graph)
    graph.invoke(Command(resume=["Only this one"]), thread())

    # The saving is the whole point: three searches became one.
    assert searched == ["Only this one"]


def test_a_client_may_send_a_dict_instead_of_a_bare_list(graph, searched):
    start(graph)
    graph.invoke(Command(resume={"sub_questions": ["A", "B"]}), thread())
    assert searched == ["A", "B"]


def test_deleting_every_question_keeps_the_plan_rather_than_failing(graph, searched):
    start(graph)
    graph.invoke(Command(resume=[]), thread())

    # To cancel, never resume. An unanswered interrupt costs nothing.
    assert len(searched) == 3


def test_edited_questions_are_cleaned_like_the_planners_own(graph, searched):
    start(graph)
    graph.invoke(Command(resume=["  spacing  ", "", "Dup", "dup"]), thread())
    assert searched == ["spacing", "Dup"]


def test_two_runs_pause_independently(graph, searched):
    start(graph, topic="batteries", name="a")
    start(graph, topic="fusion", name="b")

    graph.invoke(Command(resume=["only for b"]), thread("b"))
    assert searched == ["only for b"]
    assert graph.get_state(thread("a")).next == ("approve",)


# --- durability ---------------------------------------------------------------


def test_a_run_can_be_resumed_by_a_different_graph_object(searched):
    """The proof that the checkpoint carries the run, not the process.

    A new graph, built from scratch, resumes a run the first one paused —
    which is what surviving a restart means when the saver is durable.
    """
    saver = InMemorySaver()
    calls = []

    def counting(task):
        calls.append(task["question"])
        return fakes.researcher(task)

    first = build_graph(**{**fakes.FAKE_NODES, "researcher": counting}, approval=True, saver=saver)
    first.invoke({"topic": "batteries"}, thread("shared"))
    assert calls == []

    second = build_graph(**{**fakes.FAKE_NODES, "researcher": counting}, approval=True, saver=saver)
    result = second.invoke(Command(resume=True), thread("shared"))

    assert len(calls) == 3
    assert result["final_report"]


# --- the default path ---------------------------------------------------------


def test_without_approval_nothing_pauses_and_no_thread_is_needed(searched):
    def counting(task):
        searched.append(task["question"])
        return fakes.researcher(task)

    plain = build_graph(**{**fakes.FAKE_NODES, "researcher": counting})
    result = plain.invoke({"topic": "batteries"})

    assert "__interrupt__" not in result
    assert len(searched) == 3


# --- choosing a saver ---------------------------------------------------------


def test_no_url_means_memory():
    assert isinstance(checkpoints.checkpointer(), InMemorySaver)


def test_an_unrecognised_url_degrades_instead_of_refusing_to_start(caplog):
    # A checkpoint backend that cannot be reached should not take the API down.
    assert isinstance(checkpoints.checkpointer("mysql://host/db"), InMemorySaver)
    assert "unrecognised" in caplog.text


def test_a_sqlite_url_gives_a_saver_that_outlives_the_process(tmp_path):
    saver = checkpoints.checkpointer(f"sqlite:///{tmp_path}/cp.db")
    assert not isinstance(saver, InMemorySaver)
    assert (tmp_path / "cp.db").exists()
