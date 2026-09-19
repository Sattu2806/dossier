# Lesson 9 — An MCP server for the research tools

**Goal:** let Claude Desktop, or any MCP client, use the web search, the
document search and the whole pipeline — without knowing that LangGraph exists.

```bash
uv run dossier mcp     # stdio, the transport MCP clients launch
```

## What MCP actually is

A protocol for handing tools to a model that isn't yours. The client launches
your server as a subprocess, asks it what tools it has, and calls them on the
model's behalf. Three consequences shape the code:

1. **Docstrings and argument names are the API.** A model picks a tool by
   reading them; there is no documentation site.
2. **The caller is a model**, so errors should be data ("no results") rather
   than exceptions.
3. **stdout is the protocol.** Logs go to stderr — a stray `print()` corrupts
   the stream.

## Descriptions are written for the model that must choose

```python
@server.tool()
def research(topic: str) -> dict:
    """Produce a cited research report on a topic. SLOW AND EXPENSIVE.

    Runs the full pipeline ... Takes roughly 10-60 seconds and makes several
    LLM calls. For a single fact, use search_web instead.
    """
```

An agent deciding between `search_web` and `research` has only this text to go
on. If it doesn't know one costs a hundred times the other, it will pick
wrongly — and you pay for it. A test enforces that:

```python
def test_the_expensive_tool_says_so():
    description = tools()["research"].description.lower()
    assert "slow" in description and "expensive" in description
```

and another one fails any tool whose description is too thin to choose by.

## Every tool degrades

```python
try:
    results = search.web_search(query, max_results=...)
except Exception as exc:
    logger.warning(...)
    return []
```

A stack trace crossing the protocol tells the model nothing it can act on. An
empty list does. `research` goes further and returns `{"error": ..., "report":
""}`, so an invalid topic is a fact the agent can relay rather than a crash.

Arguments are clamped rather than validated into an error: `max_results=99`
becomes 10. Models guess numbers; a clamp is friendlier than a 400.

## Testing through the protocol, not around it

The tests call `server.call_tool(...)` and `server.list_tools()` rather than
the Python functions, because the registry is what a client sees. That caught
two things a direct call would have missed:

- **`CallToolResult`, not a tuple.** The SDK returns an object with content
  blocks and optional structured content.
- **A list return is wrapped**: `{"result": [...]}`, because structured content
  must be a JSON object at the top level.

Both are protocol facts, and a test that bypasses the protocol would have
passed while a real client failed.

It was also worth driving the server the way Claude Desktop does — spawn it,
handshake, list, call:

```python
async with stdio_client(StdioServerParameters(command="uv", args=["run", "dossier", "mcp"])) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        await session.call_tool("search_documents", {"query": "..."})
```

## A version note worth internalising

The SDK is at 2.x, where `FastMCP` was renamed `MCPServer`. Every tutorial
online still imports `mcp.server.fastmcp`. The installed package said so
plainly in its error message — which is a reminder that for a fast-moving
library, `inspect.signature` on what you actually installed beats any blog
post, including a recent one.

## Using it from a client

```json
{
  "mcpServers": {
    "dossier": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/dossier", "dossier", "mcp"],
      "env": { "GEMINI_API_KEY": "...", "TAVILY_API_KEY": "..." }
    }
  }
}
```

---

## Exercises

1. **Connect it.** Add the config above to Claude Desktop, restart it, and ask
   it to search your ingested documents.
2. **Read your own descriptions as a model would.** Strip everything but the
   tool names and first lines. Could you choose correctly?
3. **Break a tool on purpose.** Make `search_web` raise, then call it from a
   client. Does the client get something useful?
4. **Add a tool.** Expose `ingest` — then decide whether handing a remote model
   the ability to read arbitrary file paths is a good idea, and what you would
   restrict.

## Interview check

1. Why are tool docstrings part of the interface rather than documentation?
2. Why must an MCP tool avoid raising, and avoid printing to stdout?
3. Why test through `call_tool` instead of calling the function?
4. How does an agent know which of your tools is expensive?
