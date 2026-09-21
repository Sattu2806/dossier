"""Tests for measuring a study guide without a judge.

These metrics are meant to sit in CI, so the thing that matters most is that
they do not fire on good input — a floor that cries wolf gets deleted.
"""

import pytest

from dossier.guide_evals import (
    diagram_problem,
    invented_citations,
    jargon_leaks,
    passes,
    reading_grade,
    score_guide,
    syllables,
)

SIMPLE = (
    "A queue is like a line at a shop. You take a ticket and wait. "
    "The shop helps one person at a time. Nobody is lost. Everyone gets a turn. "
    "The line can be long or short. It does not matter. You still get help."
)
COMPLEX = (
    "Asynchronous message-oriented middleware decouples producers from consumers by "
    "interposing a durable intermediary, thereby permitting independent scalability "
    "characteristics and accommodating transient unavailability of downstream "
    "subscribers without compromising delivery guarantees or transactional integrity."
)


# --- readability --------------------------------------------------------------


@pytest.mark.parametrize(
    "word,count",
    [("cat", 1), ("water", 2), ("table", 2), ("queue", 1), ("people", 2), ("fire", 1), ("the", 1), ("", 0)],
)
def test_the_syllable_heuristic_is_roughly_right(word, count):
    assert syllables(word) == count


@pytest.mark.parametrize("word,got,truth", [("idea", 2, 3), ("business", 3, 2)])
def test_the_words_it_gets_wrong_are_written_down(word, got, truth):
    """Pinning the known errors beats implying there are none.

    It stays usable because it errs the same way on both texts being
    compared, and the comparison is the metric.
    """
    assert syllables(word) == got != truth


def test_simple_prose_scores_below_dense_prose():
    assert reading_grade(SIMPLE) < reading_grade(COMPLEX)


def test_a_snippet_too_short_to_measure_returns_none():
    # Better than a confident number derived from four words.
    assert reading_grade("A queue is a line.") is None


def test_citation_markers_and_code_are_not_counted_as_prose():
    with_marks = reading_grade(SIMPLE + " [1] [2] ```python\nx = 1\n```")
    assert with_marks == pytest.approx(reading_grade(SIMPLE), abs=0.6)


# --- the ELI5 promise ---------------------------------------------------------

GLOSSARY = [{"term": "Broker", "plain": "..."}, {"term": "dead letter queue", "plain": "..."}]


def test_a_technical_word_in_the_simple_version_is_reported():
    lesson = {"eli5": "The broker keeps the note safe."}
    assert jargon_leaks(lesson, GLOSSARY) == ["broker"]


def test_multi_word_terms_and_plurals_are_caught():
    lesson = {"eli5": "Bad notes go to dead letter queues."}
    assert jargon_leaks(lesson, GLOSSARY) == ["dead letter queue"]


def test_a_clean_simple_version_leaks_nothing():
    lesson = {"eli5": "The helper keeps the note safe until the worker says it is done."}
    assert jargon_leaks(lesson, GLOSSARY) == []


def test_everyday_words_in_the_glossary_are_not_treated_as_jargon():
    # "line" is in the glossary because the book defines it; a child owns it.
    lesson = {"eli5": "You wait in the line."}
    assert jargon_leaks(lesson, [{"term": "line", "plain": "..."}]) == []


def test_a_lessons_own_key_terms_count_even_if_the_glossary_missed_them():
    lesson = {"eli5": "The partition keeps order.", "key_terms": [{"term": "partition", "plain": "..."}]}
    assert jargon_leaks(lesson, []) == ["partition"]


# --- diagrams -----------------------------------------------------------------


def test_the_bare_quoted_node_form_is_caught():
    # Exactly what the model produced before the prompt was fixed: reads
    # perfectly, renders as nothing.
    assert diagram_problem('flowchart TD\n"Producer" --> "Message Queue"') == "quoted node without an identifier"


def test_the_repaired_form_is_accepted():
    assert diagram_problem('flowchart TD\nA["Producer"] --> B["Queue"]') is None


def test_a_sequence_diagram_is_accepted():
    assert diagram_problem("sequenceDiagram\n  Producer->>Queue: send") is None


@pytest.mark.parametrize(
    "source,expected",
    [("", "empty"), ("   ", "empty"), ("flowchart TD", "header with no body")],
)
def test_empty_and_headerless_diagrams_are_reported(source, expected):
    assert diagram_problem(source) == expected


def test_prose_mistaken_for_a_diagram_is_reported():
    assert "no header" in diagram_problem("The producer sends to the queue.\nThen the consumer reads.")


# --- citations ----------------------------------------------------------------


def test_a_number_no_passage_carries_is_reported():
    lesson = {"detail": "Queues decouple services [1] and absorb spikes [9].", "passages": [{"number": 1, "page": 3}]}
    assert invented_citations(lesson) == [9]


def test_citing_only_real_passages_is_clean():
    lesson = {"detail": "Queues decouple services [1].", "passages": [{"number": 1, "page": 3}]}
    assert invented_citations(lesson) == []


# --- the whole guide ----------------------------------------------------------


def guide(**overrides):
    lesson = {
        "number": 1,
        "title": "Queues",
        "status": "ok",
        "eli5": SIMPLE,
        "detail": COMPLEX + " It is described in the book [1].",
        "diagram": 'flowchart TD\nA["Producer"] --> B["Queue"]',
        "example_valid": True,
        "passages": [{"number": 1, "page": 3}],
        **overrides,
    }
    return {"title": "A Book", "lessons": [lesson], "glossary": GLOSSARY}


def test_a_sound_guide_has_nothing_to_report():
    scored = score_guide(guide(), pages=6)
    assert passes(scored) == []
    assert scored["examples_parsed"] == "1/1"
    assert scored["page_coverage"] == round(1 / 6, 2)
    assert scored["grade_gap"] > 0  # the simple version really is simpler


def test_every_kind_of_failure_is_named_in_words_you_could_act_on():
    scored = score_guide(guide(eli5="The broker holds it. " * 12, diagram="flowchart TD", detail="Claimed [7]."))
    reported = " ".join(passes(scored))
    assert "broker" in reported and "diagram" in reported and "invented" in reported


def test_a_lesson_with_no_passages_is_a_failure_not_a_low_score():
    scored = score_guide({"lessons": [{"number": 1, "status": "no_passages"}], "glossary": []})
    assert "no passages" in " ".join(passes(scored))


def test_an_unmeasurable_guide_does_not_crash_or_pretend():
    scored = score_guide({"lessons": [], "glossary": []})
    assert scored["eli5_grade"] is None and scored["grade_gap"] is None and scored["examples_parsed"] is None
