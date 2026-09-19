"""Unit tests for the writer node and the citation machinery.

These check what the Writer is *given* and what we do with what it returns.
Whether the prose is any good is an eval question (Step 8).
"""

import pytest
from langchain_core.exceptions import OutputParserException

from dossier import nodes
from dossier.state import Note


def note(question: str, *, status="ok", title="T", url="https://a.example/1", content="Evidence text") -> Note:
    return {"sub_question": question, "status": status, "title": title, "source_url": url, "content": content}


NOTES = [
    note("What is X?", title="Basics", url="https://a.example/1", content="X is a thing."),
    note("What is X?", title="More basics", url="https://b.example/2", content="X has parts."),
    note("Who builds X?", title="Makers", url="https://c.example/3", content="Acme builds X."),
]


# --- The evidence block and source numbering ---------------------------------


def test_each_unique_url_gets_one_citation_number():
    evidence, sources = nodes._prepare_evidence(NOTES)

    assert "[1] Basics\nX is a thing." in evidence
    assert sources == {
        1: "Basics — https://a.example/1",
        2: "More basics — https://b.example/2",
        3: "Makers — https://c.example/3",
    }


def test_the_same_url_found_twice_keeps_one_number():
    duplicated = [
        note("What is X?", title="Basics", url="https://a.example/1"),
        note("Who builds X?", title="Basics", url="https://a.example/1"),
    ]
    _, sources = nodes._prepare_evidence(duplicated)
    assert len(sources) == 1


def test_gaps_are_marked_and_get_no_source_number():
    notes = [
        note("What is X?"),
        note("Is X safe?", status="error", title="", url="", content="Search failed (TimeoutError)."),
        note("Who builds X?", status="no_results", title="", url="", content="No search results found."),
    ]
    evidence, sources = nodes._prepare_evidence(notes)

    assert evidence.count(nodes.NO_EVIDENCE_MARKER) == 2
    assert "Search failed (TimeoutError)." in evidence
    assert len(sources) == 1


# --- The node ----------------------------------------------------------------


def test_first_draft_prompt_has_evidence_but_no_previous_draft(fake_model):
    model = fake_model("# Report\nX is a thing [1].")

    result = nodes.writer({"topic": "X", "research_notes": NOTES})

    assert result == {"draft": "# Report\nX is a thing [1].", "revision_count": 1}
    assert "Topic: X" in model.prompt
    assert "X is a thing." in model.prompt
    # Check the user message only: the system prompt mentions a previous draft
    # in its revision instructions, which is not the same thing.
    _, human = model.messages
    assert "Your previous draft:" not in human.text


def test_revision_prompt_includes_the_previous_draft_and_the_feedback(fake_model):
    model = fake_model("# Report (revised)\nX is a thing [1].")

    result = nodes.writer(
        {
            "topic": "X",
            "research_notes": NOTES,
            "draft": "# Report\nX is a thing [1].",
            "critique_feedback": "Section 2 is vague.",
            "revision_count": 1,
        }
    )

    assert "Your previous draft:" in model.prompt
    assert "# Report\nX is a thing [1]." in model.prompt
    assert "Section 2 is vague." in model.prompt
    assert result["revision_count"] == 2


def test_instructions_and_data_stay_in_separate_messages(fake_model):
    model = fake_model("draft")
    nodes.writer({"topic": "X", "research_notes": NOTES})

    system, human = model.messages
    assert system.text == nodes.WRITER_SYSTEM
    assert "Topic: X" in human.text


def test_empty_reply_raises_a_retryable_error(fake_model):
    fake_model("   \n  ")
    with pytest.raises(OutputParserException):
        nodes.writer({"topic": "X", "research_notes": NOTES})


# --- Finalize ----------------------------------------------------------------


def test_finalize_lists_only_the_sources_the_draft_cited():
    draft = "# Report\nX is a thing [1]. Acme builds it [3]."
    report = nodes.finalize({"draft": draft, "research_notes": NOTES})["final_report"]

    assert report.startswith(draft)
    assert "[1] Basics — https://a.example/1" in report
    assert "[3] Makers — https://c.example/3" in report
    assert "More basics" not in report  # source 2 was never cited


def test_finalize_ignores_invented_citation_numbers(caplog):
    report = nodes.finalize({"draft": "Claim [1]. Invented [99].", "research_notes": NOTES})["final_report"]

    assert "[99]" not in report.split("## Sources")[1]
    assert "do not exist: [99]" in caplog.text


def test_finalize_without_usable_notes_adds_no_source_section():
    notes = [note("What is X?", status="error", title="", url="", content="Search failed.")]
    report = nodes.finalize({"draft": "# Report", "research_notes": notes})["final_report"]
    assert report == "# Report"


def test_cited_numbers_finds_every_citation_form():
    assert nodes.cited_numbers("a [1] b [2][3] c [2].") == {1, 2, 3}
