"""Unit tests for the critic node.

The critic decides whether the loop runs again, so what it is *shown* and how
its scores become a verdict are worth pinning down. Whether its judgement is
any good is an eval question (Step 8).
"""

from dossier import nodes
from dossier.state import Note


def note(question: str, *, status="ok", content="Evidence text") -> Note:
    return {
        "sub_question": question,
        "status": status,
        "title": "T",
        "source_url": "https://a.example/1",
        "content": content,
    }


STATE = {
    "topic": "X",
    "sub_questions": ["What is X?", "Who builds X?"],
    "research_notes": [note("What is X?"), note("Who builds X?")],
    "draft": "# Report\nX is a thing [1].",
    "revision_count": 1,
}


def review(**scores):
    return {
        "uncovered_sub_questions": [],
        "groundedness": 5,
        "completeness": 5,
        "coherence": 5,
        "issues": [],
        **scores,
    }


def test_critic_sees_the_evidence_not_just_the_draft(fake_model):
    model = fake_model(review())
    nodes.critic(STATE)

    assert "Evidence text" in model.prompt  # the notes themselves
    assert "What is X?" in model.prompt  # the sub-questions
    assert "X is a thing [1]." in model.prompt  # the draft
    assert model.schema is nodes.Critique


def test_all_dimensions_at_threshold_passes(fake_model):
    fake_model(review(groundedness=4, completeness=4, coherence=4))
    result = nodes.critic(STATE)

    assert result["critique_passed"] is True
    assert result["critique_scores"] == {"groundedness": 4, "completeness": 4, "coherence": 4}


def test_one_weak_dimension_fails_even_with_perfect_others(fake_model):
    fake_model(review(groundedness=2, issues=["Claim about cost is not in [1]."]))
    result = nodes.critic(STATE)

    assert result["critique_passed"] is False
    assert result["critique_feedback"] == "- Claim about cost is not in [1]."


def test_scores_outside_the_scale_are_clamped_not_fatal(fake_model):
    fake_model(review(groundedness=9, completeness=0, coherence=5))
    scores = nodes.critic(STATE)["critique_scores"]
    assert scores["groundedness"] == 5 and scores["completeness"] == 1


def test_a_rejection_always_carries_feedback(fake_model):
    # A fail with no issues would reach the writer as empty feedback, which it
    # would read as "first draft" and rewrite from scratch.
    fake_model(review(coherence=1, issues=[]))
    result = nodes.critic(STATE)

    assert result["critique_passed"] is False
    assert "coherence" in result["critique_feedback"]


def test_blank_issues_are_dropped(fake_model):
    fake_model(review(completeness=3, issues=["  ", "Section 2 omits the second sub-question."]))
    assert nodes.critic(STATE)["critique_feedback"] == "- Section 2 omits the second sub-question."


def test_an_unaddressed_sub_question_caps_completeness_whatever_the_model_scored(fake_model):
    # The model once rated a draft that skipped a whole sub-question 5/5 for
    # completeness. Enumerating the gaps is its job; the penalty is ours.
    fake_model(review(completeness=5, uncovered_sub_questions=["Who builds X?"]))
    result = nodes.critic(STATE)

    assert result["critique_scores"]["completeness"] == nodes.UNCOVERED_COMPLETENESS_CAP
    assert result["critique_passed"] is False
    assert "does not address the sub-question: Who builds X?" in result["critique_feedback"]


def test_coverage_gaps_are_listed_before_the_models_own_issues(fake_model):
    fake_model(review(uncovered_sub_questions=["Who builds X?"], issues=["Tighten the intro."]))
    lines = nodes.critic(STATE)["critique_feedback"].splitlines()

    assert lines[0].startswith("- The report does not address")
    assert lines[1] == "- Tighten the intro."


def test_pass_threshold_is_policy_in_code_not_in_the_prompt():
    # The prompt asks for scores; it never mentions passing. Moving the bar is
    # a one-number change plus an eval run, not a prompt rewrite.
    assert "pass" not in nodes.CRITIC_SYSTEM.lower()
    assert nodes.PASS_THRESHOLD == 4
