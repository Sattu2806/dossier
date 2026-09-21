"""Measuring a study guide without asking a model.

Reports are judged by an LLM because "is this a good report?" has no closed
form. A study guide is different in one important way: its central promise —
that the simple version is *actually simple* — is checkable by code, because
the guide hands you its own list of jargon. Every technical word it uses
appears in `key_terms`, so any of those words turning up in the `eli5` is the
guide breaking its own rule, and no judge is needed to see it.

So this module measures what can be measured, and leaves opinion to the judge
that comes next. Everything here runs offline, costs nothing, and is
deterministic — which means it can sit in CI as a floor rather than a report.
"""

from __future__ import annotations

import re
import statistics

# Words a term-match should not fire on: they are in the glossary because the
# book defines them, but a five-year-old already owns them.
EVERYDAY = {"line", "job", "work", "worker", "note", "helper", "order", "list", "copy"}

# A lesson's simple version should read this far below its detailed one before
# the "Explain simply" toggle is doing real work rather than changing font.
GRADE_GAP = 2.0


# --- readability --------------------------------------------------------------


def syllables(word: str) -> int:
    """A heuristic, not a dictionary: vowel groups, minus a silent final 'e'.

    Probed against real words it is right on cat, water, table, queue,
    people, simple and fire, and wrong on 'idea' (says 2, is 3) and
    'business' (says 3, is 2). That is tolerable because it is wrong the
    *same way* on both texts being compared, and the comparison — eli5
    against detail — is what the metric is for. The absolute grade is a
    rough number; the gap between two grades is the finding.
    """
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    groups = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and groups > 1:
        groups -= 1
    return max(1, groups)


def _plain(text: str) -> str:
    """Strip what is not prose: code fences, citation markers, markdown marks."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", " ", text)
    return re.sub(r"[*_#`>|-]", " ", text)


def reading_grade(text: str) -> float | None:
    """Flesch–Kincaid grade level: roughly the US school year needed to read it."""
    text = _plain(text)
    sentences = [part for part in re.split(r"[.!?]+", text) if part.strip()]
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if not sentences or len(words) < 20:
        return None
    per_sentence = len(words) / len(sentences)
    per_word = sum(syllables(word) for word in words) / len(words)
    return round(0.39 * per_sentence + 11.8 * per_word - 15.59, 1)


# --- the ELI5 promise ---------------------------------------------------------


def _mentions(text: str, term: str) -> bool:
    words = [re.escape(word) for word in term.split() if word]
    if not words:
        return False
    pattern = r"\b" + r"\s+".join(words) + r"(?:s|es)?\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def jargon_leaks(lesson: dict, glossary: list[dict]) -> list[str]:
    """Which of the guide's own technical terms turned up in its simple version.

    The guide supplies the word list, so this cannot be gamed by writing a
    lesson about a topic whose jargon we forgot to enumerate.
    """
    eli5 = lesson.get("eli5") or ""
    terms = {entry["term"].strip().lower() for entry in glossary}
    terms |= {entry["term"].strip().lower() for entry in lesson.get("key_terms", [])}
    return sorted(term for term in terms - EVERYDAY if _mentions(eli5, term))


# --- diagrams -----------------------------------------------------------------

DIAGRAM_HEADERS = ("flowchart", "graph", "sequencediagram")
BARE_QUOTED_NODE = re.compile(r'(?<![\[\(\{])"[^"\[\]<>|]+"(?![\]\)\}])\s*(?:-->|---|->>)')


def diagram_problem(source: str) -> str | None:
    """Why this Mermaid would not render, or None if it looks sound.

    Not a Mermaid parser — a check for the two failures actually observed:
    a missing header, and the bare-quoted-node form (`"A" --> "B"`) that reads
    perfectly and renders as nothing.
    """
    if not (source or "").strip():
        return "empty"
    lines = [line.strip() for line in source.strip().splitlines() if line.strip()]
    if not lines[0].lower().startswith(DIAGRAM_HEADERS):
        return f"no header: {lines[0][:40]!r}"
    if BARE_QUOTED_NODE.search(source):
        return "quoted node without an identifier"
    if len(lines) < 2:
        return "header with no body"
    return None


# --- citations ----------------------------------------------------------------


def invented_citations(lesson: dict) -> list[int]:
    """Numbers cited in the detail text that no retrieved passage carries."""
    issued = {passage["number"] for passage in lesson.get("passages", [])}
    cited = {int(number) for number in re.findall(r"\[(\d{1,2})\]", lesson.get("detail") or "")}
    return sorted(cited - issued)


# --- the whole guide ----------------------------------------------------------


def score_guide(guide: dict, *, pages: int | None = None) -> dict:
    """Every deterministic thing worth knowing about one guide."""
    lessons = guide.get("lessons", [])
    written = [lesson for lesson in lessons if lesson.get("status") == "ok"]
    glossary = guide.get("glossary", [])

    per_lesson, grades, gaps = [], [], []
    for lesson in written:
        simple = reading_grade(lesson.get("eli5") or "")
        full = reading_grade(lesson.get("detail") or "")
        leaks = jargon_leaks(lesson, glossary)
        problem = diagram_problem(lesson.get("diagram") or "")
        invented = invented_citations(lesson)

        if simple is not None and full is not None:
            gaps.append(full - simple)
        if simple is not None:
            grades.append(simple)

        per_lesson.append(
            {
                "number": lesson.get("number"),
                "title": lesson.get("title"),
                "eli5_grade": simple,
                "detail_grade": full,
                "jargon_leaks": leaks,
                "diagram_problem": problem,
                "invented_citations": invented,
                "example_valid": lesson.get("example_valid"),
                "pages_cited": sorted({p["page"] for p in lesson.get("passages", []) if p.get("page")}),
            }
        )

    cited_pages = {page for entry in per_lesson for page in entry["pages_cited"]}
    examples = [lesson.get("example_valid") for lesson in written if lesson.get("example_valid") is not None]

    return {
        "title": guide.get("title"),
        "lessons": len(lessons),
        "written": len(written),
        "eli5_grade": round(statistics.mean(grades), 1) if grades else None,
        "grade_gap": round(statistics.mean(gaps), 1) if gaps else None,
        "lessons_with_jargon_leaks": sum(1 for entry in per_lesson if entry["jargon_leaks"]),
        "leaked_terms": sorted({term for entry in per_lesson for term in entry["jargon_leaks"]}),
        "broken_diagrams": sum(1 for entry in per_lesson if entry["diagram_problem"]),
        "invented_citations": sum(len(entry["invented_citations"]) for entry in per_lesson),
        "examples_parsed": f"{sum(1 for ok in examples if ok)}/{len(examples)}" if examples else None,
        "pages_cited": len(cited_pages),
        "page_coverage": round(len(cited_pages) / pages, 2) if pages else None,
        "per_lesson": per_lesson,
    }


def passes(scored: dict) -> list[str]:
    """The failures that should stop a build, in the words you would use.

    A floor, not a grade: these are all things that are simply wrong, not
    things that are merely mediocre.
    """
    failures = []
    if scored["written"] < scored["lessons"]:
        failures.append(f"{scored['lessons'] - scored['written']} lesson(s) had no passages")
    if scored["invented_citations"]:
        failures.append(f"{scored['invented_citations']} invented citation(s)")
    if scored["broken_diagrams"]:
        failures.append(f"{scored['broken_diagrams']} diagram(s) would not render")
    if scored["lessons_with_jargon_leaks"]:
        failures.append(f"jargon in the simple version: {', '.join(scored['leaked_terms'])}")
    if scored["grade_gap"] is not None and scored["grade_gap"] < GRADE_GAP:
        failures.append(f"simple version only {scored['grade_gap']} grades easier than the detailed one")
    return failures
