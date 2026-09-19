# Lesson 1 — Project setup & the graph skeleton

**Goal:** understand how LangGraph works *before* any LLM is involved. When
the Planner starts calling a model in Step 2, anything that breaks should be
a prompt problem, never a wiring problem.

---

## Part A — The project setup

### Commands that created this repo

```bash
brew install uv
uv init --package --python 3.13 dossier   # src layout, pyproject, git init, .python-version
uv add langgraph python-dotenv             # runtime deps → pyproject + uv.lock
uv add --dev pytest ruff                   # dev-only deps (not shipped to prod)
```

Day to day you only need:

```bash
uv sync              # make .venv match uv.lock exactly (after a git pull, in CI, in Docker)
uv run <cmd>         # run inside the venv without "activating" it
uv add <pkg>         # add a dependency (updates pyproject + lock + venv in one go)
```

### Why each choice

| Choice | Why |
|---|---|
| **uv** instead of pip + venv | One tool manages the Python version, venv, deps and lockfile, and it's roughly 10–100× faster. `uv.lock` pins *every* transitive version, so your laptop, CI and Docker install the same packages. That matters in Phase 8. |
| **Python 3.13**, not 3.14 | A big dependency tree is coming: vector DBs, Postgres drivers, PDF parsers. Those packages sometimes ship wheels for a new Python version months late. For a project like this, the version one behind the newest is the safe choice. |
| **`src/` layout** | Code lives in `src/dossier/`, so tests import the *installed* package rather than whatever happens to be in the current directory. This catches packaging bugs early. |
| **`[dependency-groups] dev`** | pytest and ruff are for you, not for the production image. |
| **`[project.scripts]`** | That's why `uv run dossier ...` works as a command. |
| **`.env` + `.env.example`** | Secrets live in `.env` (gitignored). `.env.example` is the committed record of which keys exist. |
| **Deps added only when needed** | No OpenAI/Anthropic/Tavily yet. Every dependency is a thing to learn, update and secure, so add it in the step that uses it. |

### Files

```
dossier/
├── pyproject.toml          project metadata, deps, tool config (pytest, ruff)
├── uv.lock                 exact pinned versions — commit this
├── .python-version         "3.13" — uv reads it
├── .env.example            which secrets exist (copy to .env)
├── src/dossier/
│   ├── state.py            the State contract
│   ├── nodes.py            the 5 node functions (stubs)
│   ├── graph.py            wiring + router + loop limits
│   └── cli.py              `dossier run` / `dossier diagram`
├── tests/test_graph.py     mechanics tests (routing, cap, data flow)
└── docs/learn/             these lessons
```

---

## Part B — LangGraph, concept by concept

Open `state.py`, `nodes.py` and `graph.py` side by side while you read this.

### 1. State: the only thing agents share

`ResearchState` is a `TypedDict`: a dict with declared keys. Nodes never call
each other or pass arguments. They read state and write state, so this file is
the full contract between your agents.

Two design decisions to notice:

- **`critique_passed: bool` exists even though the original spec didn't
  list it.** The router needs something it can branch on reliably. Parsing
  the critic's feedback text ("does it sound like a pass?") is fragile.
  *Rule: if a decision depends on some data, that data gets its own typed field.*
- **`research_notes` is a list of `Note` objects `{sub_question, source_url, content}`,
  not a list of strings.** In Step 5 the Critic must check "is every claim traceable to a
  source?" That's impossible if the source URL was never stored. Design the state
  for the node that *reads* it, not only the node that writes it.

`total=False` + `Required[str]` on `topic` says the caller only provides `topic`;
every other key appears as the run goes on. That's why the writer uses
`state.get("critique_feedback")`: on the first pass that key doesn't exist.

### 2. Nodes: `(state) -> partial update`

```python
def critic(state: ResearchState) -> dict:
    return {"critique_passed": False, "critique_feedback": "Add a conclusion section."}
```

A node returns **only the keys it owns**. LangGraph merges that dict into the
state. Don't return the whole state, and don't mutate `state` in place.

### 3. Reducers: *how* updates are merged

By default, writing a key **overwrites** it. That's why `draft` holds only the
latest draft after the loop.

You can attach a **reducer** to a key to change the merge rule:

```python
from typing import Annotated
import operator


class S(TypedDict):
    history: Annotated[list[str], operator.add]  # new values are appended


# node a returns {"history": ["A"]}, then node b returns {"history": ["B"]}
# final state: {"history": ["A", "B"]}
```

This matters a lot in Phase 1. When several Researchers run **in parallel**
and all write `research_notes` in the same step, a key with no reducer raises:

```
InvalidUpdateError: At key 'x': Can receive only one value per step.
Use an Annotated key to handle multiple values.
```

(Both behaviours above were checked against LangGraph 1.2.11.) Parallel
fan-out only works once you've decided how concurrent writes merge.

### 4. Edges: fixed and conditional

```python
builder.add_edge("planner", "researcher")  # always
builder.add_conditional_edges("critic", route_after_critic)  # decided at runtime
```

A **router** is a plain function that reads state and returns the *name* of
the next node:

```python
def route_after_critic(state) -> Literal["writer", "finalize"]:
    if state["critique_passed"]:
        return "finalize"
    if state["revision_count"] >= MAX_REVISIONS:
        return "finalize"
    return "writer"
```

- **Routers cannot update state.** Their return value is a destination, not data.
  So "increment `revision_count` when looping back" can't happen in the router;
  the Writer does it. This is the most common beginner bug in LangGraph.
- **The `Literal[...]` return type** tells LangGraph every possible
  destination. That's how `dossier diagram` can draw the dashed edges without
  running anything.

This loop back from Critic to Writer is what makes the system *agentic*
rather than a pipeline: the path through the graph depends on what the model
produced.

### 5. compile, invoke, stream

- `builder.compile()` validates the structure (dangling edges, unknown node
  names) and returns a runnable graph.
- `graph.invoke({"topic": ...})` runs to the end and returns the final state.
- `graph.stream(..., stream_mode="updates")` yields `{node_name: what_it_returned}`
  after every step. The CLI uses it, and later the FastAPI SSE endpoint in
  Phase 4 will too. `stream_mode="values"` yields the *full* state after each step instead.

### 6. Two layers of loop protection

| Layer | Where | What it protects |
|---|---|---|
| `MAX_REVISIONS = 3` | router | **Business rule.** After 3 drafts, finalize anyway. Expected, handled, not an error. |
| `recursion_limit = 25` | `.with_config()` | **Safety net.** If the business rule is ever broken, raise `GraphRecursionError` instead of looping forever. |

Two things surprised me when checking this against the installed version:

- **LangGraph 1.2's default recursion limit is 10,007**, not the 25 that
  older tutorials quote (`langgraph/_internal/_config.py`). With real LLM calls
  and a broken cap, that's thousands of paid requests. Always set your own limit.
- **A run that executes N nodes needs `recursion_limit ≥ N + 1`.** Writing the
  input into state counts as a step too. Our default run executes 7 nodes and
  fails with a limit of 7. The worst case (3 rejected drafts) executes 9 nodes and needs 10.

### 7. Dependency injection for testability

```python
def build_graph(*, planner=nodes.planner, ..., critic=nodes.critic, ...):
```

Tests pass in `critic=approve` or `critic=reject` to force each path
through the router. Later the same hook lets us run the whole graph with
fake LLM nodes, which means fast tests in CI with no API key.

### 8. Tests vs evals

`tests/test_graph.py` checks **mechanics**: which nodes run, in what order,
where the loop stops, and that feedback reaches the writer. These results are
deterministic, so they either pass or fail.

**Evals** (Step 8) measure **quality**: is the report grounded, complete and
coherent? LLM output isn't deterministic, so you measure scores across 20–30
topics and watch averages. You need both kinds of check, and tests always come first.

---

## Part C — Exercises (do these yourself)

Run each one, predict the output *before* you look, then undo your change.

1. **Trace a run.** `uv run dossier run "solid-state batteries"`. Match every
   `[n]` step to an edge in `graph.py`.
2. **See the graph.** `uv run dossier diagram`. Paste the output into
   <https://mermaid.live>. Solid edges are fixed and dashed edges come from the router.
3. **Hit the cap.** In `nodes.critic`, make it always return
   `critique_passed: False`. How many drafts are written? What's in the final report?
4. **Break the cap.** Keep exercise 3 and set `MAX_REVISIONS = 1000`. Which
   error do you get, and after how many steps? Now read `RECURSION_LIMIT` again.
5. **The router can't write.** Make `route_after_critic` return a dict
   like `{"revision_count": 99}` instead of a name. You'll get a cryptic
   `TypeError: unhashable type: 'dict'`. Work out why: what is LangGraph trying
   to *look up* with your return value? Real LangGraph bugs often surface as
   errors this indirect.
6. **Your first reducer.** Step 9 needs a "before vs after critique"
   example, so the run must keep *every* draft, not just the last one. Add
   `draft_history: Annotated[list[str], operator.add]` to the state, have the writer
   return `{"draft_history": [draft], ...}`, and print it in the CLI.
   (Keep this one if you like it; it's a real feature.)
7. **Turn on tracing.** Create a free LangSmith account, put the key in
   `.env` (`cp .env.example .env`, set `LANGSMITH_TRACING=true`), and run exercise 1
   again. Open the trace. Even with stubs you'll see every node as a span with its
   inputs and outputs. When LLM calls arrive, token counts and latency show up in the same place.

---

## Part D — Can you answer these? (interview check)

1. How is LangGraph different from a LangChain chain, in one sentence?
2. Why do nodes return partial dicts instead of the full state?
3. What happens when two parallel nodes write the same key with no reducer?
4. Why can't a routing function increment a counter?
5. What's the difference between `MAX_REVISIONS` and `recursion_limit`?
   Why keep both?
6. Why is `critique_passed` a separate boolean from `critique_feedback`?
7. What does `stream_mode="updates"` give you that `invoke` doesn't, and
   where will you need it?

---

## Next: Step 2 — the Planner

→ [Lesson 2](02-planner-structured-output.md)
