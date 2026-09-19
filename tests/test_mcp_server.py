"""Tests for the MCP server.

These go through the server's own tool registry rather than calling the
functions directly, because the registry is what an MCP client sees: the
names, the argument schemas and the descriptions are the contract.
"""

import asyncio
import json

from dossier import docstore, mcp_server, search


def call(name: str, **arguments):
    """Invoke a tool the way a client would, and return its payload.

    A client receives a CallToolResult: text content blocks plus optional
    structured content. Unwrapping it here is the point — it proves the tools
    are reachable through the protocol, not merely importable as Python.
    """
    result = asyncio.run(mcp_server.server.call_tool(name, arguments))
    assert result.is_error is False, result.content
    payload = result.structured_content
    if payload is None:
        payload = json.loads(result.content[0].text)
    # A tool that returns a list is wrapped as {"result": [...]}, because
    # structured content must be a JSON object at the top level.
    if isinstance(payload, dict) and set(payload) == {"result"}:
        return payload["result"]
    return payload


def tools() -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}


def test_every_tool_is_described_for_the_model_that_must_choose_one():
    for name, tool in tools().items():
        assert tool.description, f"{name} has no description"
        # A client model picks tools by reading these; one line is not enough
        # for anything with arguments.
        if tool.input_schema.get("properties"):
            assert len(tool.description) > 80, f"{name}'s description is too thin"


def test_the_expensive_tool_says_so():
    # An agent choosing between a search and a full pipeline must be able to
    # tell which one costs money.
    description = tools()["research"].description.lower()
    assert "slow" in description and "expensive" in description


def test_search_web_returns_the_documented_shape(monkeypatch):
    monkeypatch.setattr(
        search,
        "web_search",
        lambda query, max_results=3: [{"title": "T", "url": "https://a.example/1", "content": "C", "score": 0.9}],
    )
    results = call("search_web", query="solid-state batteries")

    assert results == [{"title": "T", "url": "https://a.example/1", "content": "C"}]


def test_search_web_degrades_to_empty_instead_of_raising(monkeypatch):
    def broken(query, max_results=3):
        raise RuntimeError("tavily down")

    monkeypatch.setattr(search, "web_search", broken)
    assert call("search_web", query="anything") == []


def test_max_results_is_clamped(monkeypatch):
    seen = {}

    def record(query, max_results=3):
        seen["max_results"] = max_results
        return []

    monkeypatch.setattr(search, "web_search", record)
    call("search_web", query="q", max_results=99)
    assert seen["max_results"] == 10


def test_document_search_is_empty_when_nothing_is_ingested(monkeypatch):
    monkeypatch.setattr(docstore, "document_count", lambda: 0)
    assert call("search_documents", query="anything") == []


def test_document_search_returns_passages(monkeypatch):
    monkeypatch.setattr(docstore, "document_count", lambda: 12)
    monkeypatch.setattr(
        docstore,
        "doc_search",
        lambda query, k=3: [{"title": "notes", "url": "/tmp/notes.md", "content": "text"}],
    )
    assert call("search_documents", query="q")[0]["title"] == "notes"


def test_document_library_reports_the_collection_size(monkeypatch):
    monkeypatch.setattr(docstore, "document_count", lambda: 42)
    assert call("document_library") == {"chunks": 42}


def test_research_rejects_a_bad_topic_without_running_anything():
    result = call("research", topic="asdkjhqwe zxcvbnm qqq")

    assert result["report"] == ""
    assert "research topic" in result["error"]


def test_research_returns_the_report_and_what_it_cost(monkeypatch):
    from dossier import fakes
    from dossier.graph import build_graph

    monkeypatch.setattr(mcp_server, "build_graph", lambda: build_graph(**fakes.FAKE_NODES))
    result = call("research", topic="solid-state batteries")

    assert result["report"].startswith("# Report: solid-state batteries")
    assert result["drafts"] == 2
    assert result["grounded"] is True
    assert result["usage"]["calls"] == 0  # fakes make no LLM calls


def test_a_failing_run_is_reported_not_raised(monkeypatch):
    from dossier import fakes
    from dossier.graph import build_graph

    def exploding_writer(state):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(
        mcp_server,
        "build_graph",
        lambda: build_graph(**(fakes.FAKE_NODES | {"writer": exploding_writer})),
    )
    result = call("research", topic="solid-state batteries")

    assert result["report"] == ""
    assert "model exploded" in result["error"]
