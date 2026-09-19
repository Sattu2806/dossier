"""Unit tests for the researcher node, with a fake search function.

The failure paths are the point of this node: a research agent that crashes
because one search timed out is useless, and one that silently drops a
sub-question is worse — the Writer would then invent an answer for it.
"""

import pytest
from tavily.errors import InvalidAPIKeyError, UsageLimitExceededError

from dossier import nodes
from dossier.fakes import FAKE_NODES
from dossier.graph import build_graph
from dossier.state import ResearcherTask

RESULTS = [
    {"title": "Solid-state basics", "url": "https://a.example/1", "content": "Ceramic electrolytes ..."},
    {"title": "Scaling up", "url": "https://b.example/2", "content": "Manufacturing is hard ..."},
]


@pytest.fixture
def fake_search(monkeypatch):
    """Replace the web entry in the SOURCES registry.

    The registry is the seam now: the node resolves a source by name, so
    patching `nodes.web_search` would no longer be seen.
    """

    def install(result=None, error=None):
        calls = []

        def _search(query):
            calls.append(query)
            if error is not None:
                raise error
            return result if result is not None else []

        monkeypatch.setitem(nodes.SOURCES, "web", _search)
        return calls

    return install


def test_one_note_per_search_result_keeping_the_source(fake_search):
    calls = fake_search(result=RESULTS)

    task = ResearcherTask(origin="web", question="What are solid-state batteries?")
    notes = nodes.researcher(task)["research_notes"]

    assert calls == ["What are solid-state batteries?"]
    assert [note["source_url"] for note in notes] == ["https://a.example/1", "https://b.example/2"]
    assert all(note["status"] == "ok" for note in notes)
    assert all(note["sub_question"] == "What are solid-state batteries?" for note in notes)
    assert all(note["origin"] == "web" for note in notes)


def test_long_content_is_capped(fake_search):
    fake_search(result=[{"title": "t", "url": "u", "content": "x" * 5000}])
    note = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"][0]
    assert len(note["content"]) == nodes.MAX_NOTE_CHARS


def test_missing_fields_in_a_result_do_not_crash(fake_search):
    fake_search(result=[{"url": "https://a.example/1", "content": None}])
    note = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"][0]
    assert note["title"] == "" and note["content"] == ""


def test_empty_results_are_recorded_as_a_visible_gap(fake_search):
    fake_search(result=[])
    note = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"][0]
    assert note["status"] == "no_results"
    assert note["source_url"] == ""


@pytest.mark.parametrize(
    "error",
    [UsageLimitExceededError("out of credits"), InvalidAPIKeyError("bad key"), TimeoutError("too slow")],
)
def test_search_errors_become_notes_instead_of_crashing(fake_search, error):
    fake_search(error=error)
    note = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"][0]
    assert note["status"] == "error"
    assert type(error).__name__ in note["content"]


def test_an_empty_document_search_is_silence_not_a_gap(monkeypatch):
    # Your documents having nothing to say about a topic is normal. Recording
    # it as a gap made every run report missing evidence.
    monkeypatch.setitem(nodes.SOURCES, "docs", lambda query: [])
    assert nodes.researcher(ResearcherTask(origin="docs", question="q"))["research_notes"] == []


def test_an_empty_web_search_is_still_a_gap(fake_search):
    fake_search(result=[])
    note = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"][0]
    assert note["status"] == "no_results"


def test_a_document_source_error_is_still_recorded(monkeypatch):
    def broken(query):
        raise RuntimeError("chroma is down")

    monkeypatch.setitem(nodes.SOURCES, "docs", broken)
    monkeypatch.setattr(nodes, "SEARCH_RETRY_DELAY", 0)
    note = nodes.researcher(ResearcherTask(origin="docs", question="q"))["research_notes"][0]
    assert note["status"] == "error"  # a broken source is not the same as a quiet one


def test_documents_are_searched_only_when_some_have_been_ingested(monkeypatch):
    monkeypatch.setattr(nodes, "document_count", lambda: 0)
    assert nodes.available_origins() == ["web"]

    monkeypatch.setattr(nodes, "document_count", lambda: 42)
    assert nodes.available_origins() == ["web", "docs"]


def test_fan_out_covers_every_question_and_every_available_source(monkeypatch):
    monkeypatch.setattr(nodes, "document_count", lambda: 42)
    sends = nodes.fan_out_to_researchers({"topic": "t", "sub_questions": ["Q1?", "Q2?"]})

    assert len(sends) == 4  # 2 questions x 2 sources, still one super-step
    assert {(send.arg["question"], send.arg["origin"]) for send in sends} == {
        ("Q1?", "web"),
        ("Q1?", "docs"),
        ("Q2?", "web"),
        ("Q2?", "docs"),
    }


def test_a_document_search_failure_degrades_like_a_web_one(monkeypatch):
    def broken_doc_search(query):
        raise RuntimeError("chroma is down")

    monkeypatch.setitem(nodes.SOURCES, "docs", broken_doc_search)
    note = nodes.researcher(ResearcherTask(origin="docs", question="q"))["research_notes"][0]

    assert note["status"] == "error" and note["origin"] == "docs"


def test_one_failing_researcher_does_not_stop_the_others(monkeypatch):
    def flaky_search(query):
        if "2" in query:
            raise TimeoutError("too slow")
        return RESULTS

    monkeypatch.setitem(nodes.SOURCES, "web", flaky_search)

    def planner_with_three(state):
        return {"sub_questions": ["Question 1?", "Question 2?", "Question 3?"]}

    graph = build_graph(**(FAKE_NODES | {"planner": planner_with_three, "researcher": nodes.researcher}))
    result = graph.invoke({"topic": "test topic"})

    statuses = sorted(note["status"] for note in result["research_notes"])
    assert statuses == ["error", "ok", "ok", "ok", "ok"]  # 1 failure + 2 questions x 2 results
    assert result["final_report"]  # the run still finished


def test_a_timed_out_search_is_retried_once_before_degrading(monkeypatch):
    # Observed for real: four concurrent searches timed out at once and the
    # report came back empty. One retry recovers from that.
    attempts = []

    def flaky(query):
        attempts.append(query)
        if len(attempts) == 1:
            raise TimeoutError("Request timed out after 20 seconds.")
        return RESULTS

    monkeypatch.setitem(nodes.SOURCES, "web", flaky)
    monkeypatch.setattr(nodes, "SEARCH_RETRY_DELAY", 0)

    notes = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"]

    assert len(attempts) == 2
    assert all(note["status"] == "ok" for note in notes)


def test_a_search_that_keeps_failing_still_degrades(monkeypatch):
    attempts = []

    def always_failing(query):
        attempts.append(query)
        raise TimeoutError("Request timed out after 20 seconds.")

    monkeypatch.setitem(nodes.SOURCES, "web", always_failing)
    monkeypatch.setattr(nodes, "SEARCH_RETRY_DELAY", 0)

    note = nodes.researcher(ResearcherTask(origin="web", question="q"))["research_notes"][0]

    assert len(attempts) == nodes.SEARCH_ATTEMPTS
    assert note["status"] == "error"
