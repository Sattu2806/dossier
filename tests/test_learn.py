"""Tests for the study-guide pipeline.

The rules that matter here are the same ones the research graph has: one
failure must not cost the reader everything else, parallel results must come
back in order, and nothing may be cited that was not supplied.
"""

import pytest
from langchain_core.exceptions import OutputParserException

from dossier import learn
from dossier.learn import LessonTask, assemble, build_learn_graph, clean_diagram, fan_out_to_lessons

PASSAGES = [
    {"page": 12, "chunk": 3, "content": "A queue holds work until a worker is free.", "score": 0.7},
    {"page": 13, "chunk": 4, "content": "Workers pull from the front of the queue.", "score": 0.66},
]

LESSON = {"number": 1, "title": "What a queue is", "covers": "Explain queues", "query": "queue worker"}


def written(**overrides):
    return {
        "eli5": "It is like waiting your turn for the slide.",
        "analogy": "A line at the slide in a playground.",
        "detail": "A queue holds work until a worker is free [1]. Workers take from the front [2].",
        "diagram": 'flowchart TD\n  A["Job"] --> B["Queue"]',
        "example": "print('hello')",
        "example_language": "Python",
        "example_walkthrough": "It prints a word.",
        "key_terms": [{"term": "Queue", "plain": "A line of work waiting its turn."}],
        "questions": [{"question": "Why queue?", "answer": "So work is not lost."}],
        **overrides,
    }


# --- diagrams -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("flowchart TD\n A --> B", "flowchart TD\n A --> B"),
        ("```mermaid\nflowchart TD\n A --> B\n```", "flowchart TD\n A --> B"),
        ("```\nsequenceDiagram\n A->>B: hi\n```", "sequenceDiagram\n A->>B: hi"),
        # Prose instead of a diagram renders as a red error box mid-lesson,
        # so it is dropped rather than shown.
        ("Here is a diagram of the system", ""),
        ("", ""),
    ],
)
def test_diagrams_are_cleaned_or_dropped(given, expected):
    assert clean_diagram(given) == expected


# --- one lesson ---------------------------------------------------------------


def test_a_lesson_is_written_from_the_books_own_passages(fake_model, monkeypatch):
    model = fake_model(written())
    monkeypatch.setattr(learn, "scoped_search", lambda query, **kwargs: PASSAGES)

    result = learn.write_lesson(LessonTask(document_id="doc1", lesson=LESSON))["lessons"][0]

    assert result["status"] == "ok"
    assert result["eli5"].startswith("It is like")
    assert result["example_language"] == "python"  # normalised
    assert [passage["page"] for passage in result["passages"]] == [12, 13]
    # The passages, numbered, are what the model was given to cite.
    assert "[1] (page 12)" in model.prompt


def test_a_lesson_with_nothing_to_cite_says_so_instead_of_inventing(fake_model, monkeypatch):
    fake_model(written())
    monkeypatch.setattr(learn, "scoped_search", lambda query, **kwargs: [])

    result = learn.write_lesson(LessonTask(document_id="doc1", lesson=LESSON))["lessons"][0]

    assert result["status"] == "no_passages"
    assert result["passages"] == []


def test_invented_citations_are_recorded(fake_model, monkeypatch, caplog):
    fake_model(written(detail="A claim [1]. Another [9]."))
    monkeypatch.setattr(learn, "scoped_search", lambda query, **kwargs: PASSAGES)

    result = learn.write_lesson(LessonTask(document_id="doc1", lesson=LESSON))["lessons"][0]

    assert result["invented_citations"] == [9]  # only two passages were given
    assert "do not exist" in caplog.text


def test_one_failed_lesson_does_not_raise(monkeypatch):
    monkeypatch.setattr(learn, "scoped_search", lambda query, **kwargs: PASSAGES)

    class Exploding:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(learn, "chat_model", lambda role="default": Exploding())
    result = learn.write_lesson(LessonTask(document_id="doc1", lesson=LESSON))["lessons"][0]

    assert result["status"] == "failed"


# --- outline and assembly -----------------------------------------------------


def test_the_outline_becomes_one_task_per_lesson():
    outline = [
        {"number": 1, "title": "One", "covers": "", "query": "a"},
        {"number": 2, "title": "Two", "covers": "", "query": "b"},
    ]
    sends = fan_out_to_lessons({"document_id": "doc1", "outline": outline})

    assert len(sends) == 2
    assert {send.arg["lesson"]["title"] for send in sends} == {"One", "Two"}


def test_an_empty_document_fails_loudly(fake_model, monkeypatch):
    fake_model({"subject": "x", "lessons": []})
    monkeypatch.setattr(learn, "document_overview", lambda document_id, **kwargs: [])

    with pytest.raises(OutputParserException):
        learn.outline_book({"document_id": "doc1", "title": "Empty"})


def test_lessons_are_reordered_after_parallel_writing():
    # Writers finish in whatever order they finish; without sorting, lesson 6
    # can arrive before lesson 2.
    lessons = [
        {"number": 3, "title": "Third", "status": "ok", "key_terms": [{"term": "B", "plain": "b"}], "questions": []},
        {"number": 1, "title": "First", "status": "ok", "key_terms": [{"term": "A", "plain": "a"}], "questions": []},
        {"number": 2, "title": "Second", "status": "failed", "key_terms": [], "questions": []},
    ]
    guide = assemble({"title": "Book", "lessons": lessons})["guide"]

    assert [lesson["number"] for lesson in guide["lessons"]] == [1, 2, 3]
    assert [term["term"] for term in guide["glossary"]] == ["a", "b"] or [
        term["term"] for term in guide["glossary"]
    ] == ["a", "b"]
    assert guide["stats"]["lessons"] == 3
    assert guide["stats"]["written"] == 2  # the failed one is counted separately


def test_the_whole_graph_runs_on_fakes():
    def outline(state):
        return {
            "outline": [
                {"number": number, "title": f"Lesson {number}", "covers": "", "query": "q"} for number in (1, 2, 3)
            ],
            "title": "A Book",
        }

    def lesson(task):
        return {
            "lessons": [
                {**task["lesson"], "status": "ok", "key_terms": [], "questions": [], "diagram": "flowchart TD\n A-->B"}
            ]
        }

    result = build_learn_graph(outline=outline, lesson=lesson).invoke({"document_id": "doc1"})

    assert result["guide"]["stats"] == {"lessons": 3, "written": 3, "diagrams": 3, "questions": 0, "terms": 0}
    assert [lesson["number"] for lesson in result["guide"]["lessons"]] == [1, 2, 3]


# --- worked examples ----------------------------------------------------------


def test_python_examples_are_syntax_checked():
    assert learn.check_example("x = 1\nprint(x)", "python") is True
    assert learn.check_example("def broken(:\n  pass", "python") is False


def test_examples_in_other_languages_are_not_judged():
    # None, not True: "we cannot check this" is different from "this is fine".
    assert learn.check_example("SELECT 1;", "sql") is None
    assert learn.check_example("", "python") is None


def test_the_example_check_never_runs_the_code(tmp_path):
    # If this parsed *and ran*, the file would exist. It must only parse.
    marker = tmp_path / "executed.txt"
    assert learn.check_example(f"open({str(marker)!r}, 'w').write('x')", "python") is True
    assert not marker.exists()


# --- diagram repair -----------------------------------------------------------


def test_quoted_nodes_are_given_the_identifiers_mermaid_requires():
    # What the model writes: readable, and renders as nothing.
    given = 'flowchart TD\n"Producer" --> "Queue"\n"Queue" --> "Consumer"'
    fixed = learn.clean_diagram(given)

    assert 'n1["Producer"] --> n2["Queue"]' in fixed
    # The same label keeps the same identifier, or the arrow points nowhere.
    assert 'n2["Queue"] --> n3["Consumer"]' in fixed


def test_edge_labels_are_not_turned_into_nodes():
    given = 'flowchart TD\n"Consumer" -->|"acknowledges"| "Broker"'
    fixed = learn.clean_diagram(given)

    assert '-->|"acknowledges"|' in fixed  # still an edge label
    assert 'n1["Consumer"]' in fixed and 'n2["Broker"]' in fixed


def test_already_correct_diagrams_are_left_alone():
    given = 'flowchart TD\n  A["Producer"] --> B["Queue"]'
    assert learn.clean_diagram(given) == given


def test_sequence_diagrams_are_not_rewritten():
    given = "sequenceDiagram\n  Producer->>Queue: publish"
    assert learn.clean_diagram(given) == given
