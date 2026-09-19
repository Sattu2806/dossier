"""Tests for the fact-checker node.

It answers one question — "does the evidence say this?" — and the verdict is
computed from its answer rather than asked for.
"""

from dossier import nodes

NOTES = [
    {
        "sub_question": "What is X?",
        "origin": "web",
        "status": "ok",
        "title": "Primer",
        "source_url": "https://a.example/1",
        "content": "X uses a solid electrolyte.",
    }
]
STATE = {
    "topic": "X",
    "sub_questions": ["What is X?"],
    "research_notes": NOTES,
    "draft": "# X\nX uses a solid electrolyte [1]. The market reached $4.2bn [1].",
}


def test_it_sees_the_evidence_and_the_draft(fake_model):
    model = fake_model({"unsupported_claims": []})
    nodes.fact_checker(STATE)

    assert "X uses a solid electrolyte." in model.prompt  # the note
    assert "The market reached $4.2bn [1]." in model.prompt  # the draft
    assert model.schema is nodes.FactCheck


def test_no_findings_means_grounded(fake_model):
    fake_model({"unsupported_claims": []})
    result = nodes.fact_checker(STATE)

    assert result == {"grounded": True, "unsupported_claims": [], "fact_feedback": ""}


def test_findings_make_it_ungrounded_with_quotable_feedback(fake_model):
    fake_model({"unsupported_claims": ["The market reached $4.2bn"]})
    result = nodes.fact_checker(STATE)

    assert result["grounded"] is False
    assert result["fact_feedback"] == "- Unsupported: The market reached $4.2bn"


def test_blank_findings_are_ignored(fake_model):
    # An empty string is not a finding; treating it as one would send a clean
    # draft back to the writer and pay for a revision that fixes nothing.
    fake_model({"unsupported_claims": ["   ", ""]})
    assert nodes.fact_checker(STATE)["grounded"] is True


def test_the_verdict_is_computed_not_asked_for():
    # The schema has no "grounded" field: the model reports what it found, and
    # the code decides what that means.
    assert set(nodes.FactCheck.model_fields) == {"unsupported_claims"}
