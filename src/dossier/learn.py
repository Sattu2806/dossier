"""Turning a book into a course.

A different job from the research pipeline, so a different graph:

    outline → lesson × N (in parallel) → assemble

The research graph answers a question from many sources. This one teaches one
source, in an order a beginner can follow, and every lesson has to survive the
same rule as a report: if the book does not say it, it does not go in.

Each lesson is written twice on purpose — once for a five-year-old and once
properly. The simple version is not a summary of the detailed one; it is the
test of whether the thing was understood at all, which is why the prompt bans
technical words outright rather than asking for "simple language".
"""

import ast
import logging
import operator
import re
from typing import Annotated, Required, TypedDict

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send
from pydantic import BaseModel, Field

from dossier.docstore import document_overview, scoped_search
from dossier.llm import chat_model
from dossier.prompts import LESSON_SYSTEM, OUTLINE_SYSTEM

logger = logging.getLogger(__name__)

MAX_LESSONS = 8
PASSAGES_PER_LESSON = 6
# Mermaid has many diagram types; these two cover "how parts relate" and "what
# happens in what order", which is nearly every explanation in a textbook.
ALLOWED_DIAGRAMS = ("flowchart", "sequenceDiagram", "graph")


class PlannedLesson(TypedDict):
    number: int
    title: str
    covers: str
    query: str


class LessonTask(TypedDict):
    document_id: str
    lesson: PlannedLesson


class LearnState(TypedDict, total=False):
    document_id: Required[str]
    title: str
    outline: list[PlannedLesson]
    lessons: Annotated[list[dict], operator.add]
    guide: dict


# --- outline -----------------------------------------------------------------


class Outline(BaseModel):
    """A course plan for one book."""

    subject: str = Field(description="What this book is about, in one plain sentence")
    lessons: list[dict] = Field(description="Lessons in learning order, each with title, covers and query")


def outline_book(state: LearnState) -> dict:
    opening = document_overview(state["document_id"])
    if not opening:
        raise OutputParserException("The document has no readable text to plan from")

    passages = "\n\n".join(f"[page {piece['page']}] {piece['content']}" for piece in opening[:20])
    reply = (
        chat_model("planner")
        .with_structured_output(Outline)
        .invoke(
            [
                SystemMessage(OUTLINE_SYSTEM),
                HumanMessage(f"Book: {state.get('title', 'Untitled')}\n\nOpening pages:\n{passages}"),
            ]
        )
    )

    lessons: list[PlannedLesson] = []
    for index, raw in enumerate(reply.lessons[:MAX_LESSONS], start=1):
        title = str(raw.get("title", "")).strip()
        if not title:
            continue
        lessons.append(
            {
                "number": index,
                "title": title,
                "covers": str(raw.get("covers", "")).strip(),
                # Falling back to the title keeps a lesson searchable even when
                # the model forgets the field.
                "query": str(raw.get("query") or title).strip(),
            }
        )

    if not lessons:
        raise OutputParserException("The outline came back with no lessons")

    logger.info("outlined %d lessons for %s", len(lessons), state["document_id"])
    return {"outline": lessons, "title": state.get("title") or reply.subject}


def fan_out_to_lessons(state: LearnState) -> list[Send]:
    """One writer per lesson, all in the same step — the same trick the
    researchers use, and the reason a whole guide takes seconds rather than
    minutes."""
    return [Send("lesson", LessonTask(document_id=state["document_id"], lesson=lesson)) for lesson in state["outline"]]


# --- one lesson ---------------------------------------------------------------


class KeyTerm(BaseModel):
    term: str = Field(description="The technical word")
    plain: str = Field(description="What it means, in one plain sentence")


class Question(BaseModel):
    question: str = Field(description="A question that checks understanding, not recall")
    answer: str = Field(description="The answer, in two or three sentences")


class WrittenLesson(BaseModel):
    """One lesson of a study guide."""

    eli5: str = Field(description="The explanation for a five-year-old. Everyday words only, no jargon.")
    analogy: str = Field(description="One concrete physical comparison a child would recognise")
    detail: str = Field(description="The real explanation for an adult, citing passages like [2]")
    diagram: str = Field(description="Mermaid source: flowchart TD or sequenceDiagram, 4-8 nodes, no code fence")
    example: str = Field(description="A worked example that can be run or followed by hand")
    example_language: str = Field(description="Language of the example: python, sql, text, …")
    example_walkthrough: str = Field(description="What the example does, step by step, in plain words")
    key_terms: list[KeyTerm] = Field(description="Technical words used here, each explained plainly")
    questions: list[Question] = Field(description="Three questions with answers")


def check_example(code: str, language: str) -> bool | None:
    """Does the example at least parse?

    Parsed, never executed: running code a model wrote, on the server, on
    behalf of whoever uploaded a PDF, is a remote code execution hole with a
    friendly name. `ast.parse` reads it without running a line of it.

    Returns None for languages we cannot check, which is not the same as True.
    """
    if language != "python" or not code.strip():
        return None
    try:
        ast.parse(code)
        return True
    except SyntaxError as exc:
        logger.warning("example does not parse: %s", exc)
        return False


def repair_flowchart(text: str) -> str:
    """Give quoted nodes the identifiers Mermaid requires.

    Models reliably write `"Producer" --> "Queue"`, which reads perfectly and
    renders as nothing: Mermaid needs `A["Producer"] --> B["Queue"]`. The
    mistake is predictable enough to fix in code rather than lose the diagram
    over — and a prompt cannot be relied on to prevent it every time.

    Edge labels (`-->|"acknowledges"|`) are deliberately left alone; they are
    quoted too, but they are not nodes.
    """
    identifiers: dict[str, str] = {}

    def identifier(label: str) -> str:
        if label not in identifiers:
            identifiers[label] = f"n{len(identifiers) + 1}"
        return identifiers[label]

    lines = []
    for line in text.splitlines():
        # Split so that |...| segments can be skipped wholesale.
        parts = re.split(r"(\|[^|]*\|)", line)
        for index, part in enumerate(parts):
            if part.startswith("|"):
                continue
            parts[index] = re.sub(
                # A node label contains no brackets or arrows. Without that,
                # the pattern happily spans two nodes — `"] --> B["` matches
                # as "a label" and corrupts a diagram that was already valid.
                r'(?<![\[\(\{])"([^"\[\]<>|]+)"(?![\]\)\}])',
                lambda match: f'{identifier(match.group(1))}["{match.group(1)}"]',
                part,
            )
        lines.append("".join(parts))
    return "\n".join(lines)


def clean_diagram(source: str) -> str:
    """Make the model's Mermaid safe to render, or drop it.

    A broken diagram is worse than none: it renders as a red error box in the
    middle of a lesson. Fences and stray prose are stripped, node syntax is
    repaired, and anything still unrecognisable is dropped.
    """
    text = source.strip()
    text = re.sub(r"^```(?:mermaid)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith(ALLOWED_DIAGRAMS):
        return ""
    return repair_flowchart(text) if text.startswith(("flowchart", "graph")) else text


def write_lesson(task: LessonTask) -> dict:
    """Retrieve this lesson's passages, then write it. Never raises: one
    lesson that fails must not cost the reader the other seven."""
    lesson = task["lesson"]

    try:
        passages = scoped_search(lesson["query"], document_id=task["document_id"], k=PASSAGES_PER_LESSON)
    except Exception as exc:
        logger.warning("retrieval failed for lesson %s: %s", lesson["title"], exc)
        passages = []

    if not passages:
        return {
            "lessons": [
                {
                    **lesson,
                    "status": "no_passages",
                    "eli5": "",
                    "detail": "This part of the book could not be found in the uploaded text.",
                    "passages": [],
                }
            ]
        }

    evidence = "\n\n".join(
        f"[{index}] (page {passage['page']}) {passage['content']}" for index, passage in enumerate(passages, start=1)
    )

    try:
        written = (
            chat_model("writer")
            .with_structured_output(WrittenLesson)
            .invoke(
                [
                    SystemMessage(LESSON_SYSTEM),
                    HumanMessage(
                        f"Lesson {lesson['number']}: {lesson['title']}\n"
                        f"It should teach: {lesson['covers']}\n\n"
                        f"Passages from the book:\n{evidence}"
                    ),
                ]
            )
        )
    except Exception as exc:
        logger.warning("lesson %s failed: %s: %s", lesson["title"], type(exc).__name__, exc)
        return {"lessons": [{**lesson, "status": "failed", "error": f"{type(exc).__name__}", "passages": []}]}

    # Citations are checked the same way the report's are: we know which
    # numbers were handed out, so anything else was invented.
    cited = {int(number) for number in re.findall(r"\[(\d+)\]", written.detail)}
    invented = sorted(number for number in cited if number > len(passages))
    if invented:
        logger.warning("lesson %r cited passages that do not exist: %s", lesson["title"], invented)

    return {
        "lessons": [
            {
                **lesson,
                "status": "ok",
                "eli5": written.eli5.strip(),
                "analogy": written.analogy.strip(),
                "detail": written.detail.strip(),
                "diagram": clean_diagram(written.diagram),
                "example": written.example.strip(),
                "example_language": (language := (written.example_language or "text").strip().lower()),
                "example_valid": check_example(written.example, language),
                "example_walkthrough": written.example_walkthrough.strip(),
                "key_terms": [term.model_dump() for term in written.key_terms],
                "questions": [question.model_dump() for question in written.questions],
                "invented_citations": invented,
                "passages": [
                    {"number": index, "page": passage["page"], "quote": passage["content"][:400]}
                    for index, passage in enumerate(passages, start=1)
                ],
            }
        ]
    }


# --- assemble -----------------------------------------------------------------


def assemble(state: LearnState) -> dict:
    """Put the lessons back in order and collect the glossary.

    Parallel writers finish in whatever order they finish, so ordering here is
    not a nicety — without it lesson 6 can arrive before lesson 2.
    """
    lessons = sorted(state.get("lessons", []), key=lambda lesson: lesson["number"])

    glossary: dict[str, str] = {}
    for lesson in lessons:
        for term in lesson.get("key_terms", []):
            glossary.setdefault(term["term"].strip().lower(), term["plain"])

    written = [lesson for lesson in lessons if lesson.get("status") == "ok"]
    return {
        "guide": {
            "title": state.get("title", "Study guide"),
            "lessons": lessons,
            "glossary": [{"term": term, "plain": plain} for term, plain in sorted(glossary.items())],
            "stats": {
                "lessons": len(lessons),
                "written": len(written),
                "diagrams": sum(1 for lesson in written if lesson.get("diagram")),
                "questions": sum(len(lesson.get("questions", [])) for lesson in written),
                "terms": len(glossary),
            },
        }
    }


# --- the graph ----------------------------------------------------------------

LESSON_RETRY = RetryPolicy(max_attempts=2, retry_on=OutputParserException)


def build_learn_graph(*, outline=outline_book, lesson=write_lesson, assembler=assemble):
    """Injectable like the research graph, so the tests run on fakes."""
    builder = StateGraph(LearnState)

    builder.add_node("outline", outline, retry_policy=LESSON_RETRY)
    builder.add_node("lesson", lesson)
    builder.add_node("assemble", assembler)

    builder.add_edge(START, "outline")
    builder.add_conditional_edges("outline", fan_out_to_lessons, ["lesson"])
    builder.add_edge("lesson", "assemble")
    builder.add_edge("assemble", END)

    # 1 input + outline + (up to 8 lessons in one step) + assemble = 4.
    return builder.compile().with_config(recursion_limit=12)
