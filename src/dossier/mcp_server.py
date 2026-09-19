"""An MCP server exposing dossier's research tools.

Why this exists: the Researcher's abilities are useful outside this project's
own front end. Wrapping them in the Model Context Protocol means Claude
Desktop — or any MCP client — can search the web, search your ingested
documents, or commission a full report, without knowing anything about
LangGraph.

Run it:  uv run dossier mcp        (stdio, the transport MCP clients expect)

Design notes:
- Tool docstrings and argument names ARE the interface. A client model picks
  a tool by reading them, so they are written for that reader.
- Every tool degrades instead of raising: an MCP client handles "no results"
  far better than a stack trace.
- `research` runs the whole graph, which takes ~10-60 seconds and costs
  several LLM calls, and its docstring says so — an agent choosing between
  `search_web` and `research` should know which one is expensive.
"""

import logging

from mcp.server.mcpserver import MCPServer

from dossier import docstore, search
from dossier.graph import build_graph
from dossier.guardrails import InvalidTopic, TokenBudget

logger = logging.getLogger(__name__)

server = MCPServer(
    name="dossier",
    title="Dossier research tools",
    instructions=(
        "Web and document research. Use search_web for a quick lookup, "
        "search_documents for the user's own ingested files, and research "
        "only when a full cited report is wanted — it is slow and costly."
    ),
)


@server.tool()
def search_web(query: str, max_results: int = 3) -> list[dict]:
    """Search the web and return sources with their text.

    Use for a specific factual question. Returns a list of
    {title, url, content}; an empty list means nothing was found.

    Args:
        query: A self-contained question or phrase. It is sent verbatim to the
            search engine, so include the subject rather than "it".
        max_results: How many sources to return (1-10).
    """
    try:
        results = search.web_search(query, max_results=max(1, min(10, max_results)))
    except Exception as exc:
        logger.warning("search_web failed: %s: %s", type(exc).__name__, exc)
        return []
    return [
        {"title": result.get("title", ""), "url": result.get("url", ""), "content": result.get("content", "")}
        for result in results
    ]


@server.tool()
def search_documents(query: str, max_results: int = 3) -> list[dict]:
    """Search the user's own ingested documents (PDFs, notes, Markdown).

    Use when the answer is likely to be in the user's files rather than on the
    web. Returns {title, url, content}; an empty list means either nothing
    matched or no documents have been ingested yet.

    Args:
        query: What to look for, in plain words.
        max_results: How many passages to return (1-10).
    """
    if not docstore.document_count():
        return []
    try:
        return docstore.doc_search(query, k=max(1, min(10, max_results)))
    except Exception as exc:
        logger.warning("search_documents failed: %s: %s", type(exc).__name__, exc)
        return []


@server.tool()
def document_library() -> dict:
    """How many document chunks are available to search_documents."""
    return {"chunks": docstore.document_count()}


@server.tool()
def research(topic: str) -> dict:
    """Produce a cited research report on a topic. SLOW AND EXPENSIVE.

    Runs the full pipeline: plans sub-questions, searches the web and the
    user's documents in parallel, drafts a report, fact-checks it against the
    sources, and revises it if needed. Takes roughly 10-60 seconds and makes
    several LLM calls. For a single fact, use search_web instead.

    Returns the report in Markdown with a numbered source list, plus how many
    drafts it took and what it cost in tokens.

    Args:
        topic: The subject to research, in plain words (3-200 characters).
    """
    budget = TokenBudget()
    try:
        state = build_graph().invoke({"topic": topic}, config={"callbacks": [budget]})
    except InvalidTopic as exc:
        return {"error": str(exc), "report": ""}
    except Exception as exc:
        logger.warning("research failed for %r: %s: %s", topic, type(exc).__name__, exc)
        return {"error": f"{type(exc).__name__}: {exc}", "report": ""}

    return {
        "report": state.get("final_report", ""),
        "drafts": state.get("revision_count", 0),
        "grounded": state.get("grounded"),
        "passed_review": state.get("critique_passed"),
        "usage": budget.summary(),
    }


def main() -> None:
    server.run(transport="stdio")
