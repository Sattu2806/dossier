# Lesson 3 — The Researcher: parallel fan-out and failing well

**Goal:** run one researcher per sub-question, all at the same time, and make
a failed search a recorded gap instead of a crashed run.

This is the step where the graph stops being a line. Two new ideas carry it:
**`Send`** (start N copies of a node) and **reducers** (merge what they all write).

## What changed

```
src/dossier/
├── search.py    NEW  the only file that knows we search with Tavily
├── state.py          Note gains status/title; research_notes gets a reducer; ResearcherTask
├── nodes.py          real researcher + fan_out_to_researchers
├── graph.py          planner → researcher is now a fan-out edge
├── fakes.py          fake researcher now takes one question
└── cli.py            stream_mode="debug" so parallel steps are visible
tests/test_researcher.py  NEW  failure paths, mostly
```

---

## 1. `Send`: one node, N runs

```python
def fan_out_to_researchers(state: ResearchState) -> list[Send]:
    return [Send("researcher", ResearcherTask(question=q)) for q in state["sub_questions"]]


builder.add_conditional_edges("planner", nodes.fan_out_to_researchers, ["researcher"])
```

It's still a router: a function that returns destinations. The difference is
that it returns **a list**, and each `Send` carries **its own input**.

- `Send(node_name, payload)` means "run this node once, with this input".
- The **payload replaces the state for that run**. `researcher` receives
  `{"question": "..."}`, not the full `ResearchState`. That's deliberate: a
  researcher shouldn't see the draft or the critique, and a smaller input is a
  smaller prompt.
- **The width is decided at runtime.** 3 sub-questions start 3 researchers,
  7 start 7. A fixed edge can't do that.
- The `["researcher"]` third argument lists where Sends may land, so
  `dossier diagram` still draws the edge.

Checked against LangGraph 1.2.11: the payload arrives **unchanged**, without
declaring an input schema. (`add_node(..., input_schema=ResearcherTask)` exists
if you want it enforced and documented; the type annotation on the function
does the documenting for us.)

**Return type note:** `route_after_critic` returns `Literal["writer", "finalize"]`
while this one returns `list[Send]`. Same mechanism, different shape.

## 2. Reducers: what happens when 4 nodes write the same key at once

```python
research_notes: Annotated[list[Note], operator.add]
```

Without the `Annotated[...]` part, LangGraph refuses the parallel write:

```
InvalidUpdateError: At key 'research_notes': Can receive only one value per step.
```

That error is LangGraph protecting you. Four researchers each returning
`{"research_notes": [...]}` in one step is four values for one key, and the
default rule (overwrite) has no sane answer for that, so you must state the
merge rule. `operator.add` on lists means concatenate.

Two things to remember:

- **The reducer belongs to the state key, not the node.** It's declared once in
  `state.py` and applies to every write of that key.
- **Don't rely on the order of merged results.** Notes arrive in whatever order
  the parallel tasks finish. Group by `sub_question` when you need structure.

## 3. The parallelism is real (measured)

Three searches through the graph, timed:

| query | start | end | thread |
|---|---|---|---|
| What is solid-state batteries? | 0.01s | 4.60s | ThreadPoolExecutor-1_0 |
| What is the current state…? | 0.01s | 8.22s | ThreadPoolExecutor-1_1 |
| What are the open problems…? | 0.01s | 8.66s | ThreadPoolExecutor-1_2 |

**Wall clock 8.65s. Added together: 21.45s.** All three started at the same
moment on different threads. LangGraph runs the tasks of one super-step in a
thread pool (for `async def` nodes it uses the event loop instead).

A second measured consequence: **a fan-out is ONE super-step no matter how wide it is.**
20 researchers cost the same one step as 3, so `RECURSION_LIMIT` doesn't need
to change (there's a test with 12).

This is the architectural argument for agent graphs over a `for` loop: the
parallelism comes from the shape of the graph, and you don't manage threads.

## 4. Failing well — the heart of this node

A research agent that dies because one search timed out is useless. One that
silently skips a sub-question is *worse*: the Writer will fill the hole with
invention, and a plausible-sounding invented paragraph is a hallucination.

```python
try:
    results = web_search(question)
except Exception as exc:
    logger.warning(...)
    return {"research_notes": [_gap_note(question, "error", ...)]}

if not results:
    return {"research_notes": [_gap_note(question, "no_results", ...)]}
```

Four decisions in that small block:

1. **Catch broadly, but narrowly scoped.** Tavily's errors
   (`TimeoutError`, `InvalidAPIKeyError`, `UsageLimitExceededError`…) share no
   common base class, so `except Exception` is the honest option. But only the
   `web_search(...)` line is inside the `try`. A `KeyError` in *our* code below
   still crashes, as it should. A `try` wrapped around a whole function body is
   how bugs get hidden for months.
2. **Degrade, don't crash.** The other researchers in the same step keep going,
   and the run still produces a report. A test proves it:
   `test_one_failing_researcher_does_not_stop_the_others`.
3. **Record the gap as data.** `status: "error" | "no_results" | "ok"` is a
   typed field, not a magic string inside the content. In Step 5 the Critic can
   ask "did the draft make claims for a sub-question whose status wasn't ok?",
   and evals can count failed searches per run.
4. **Log it.** `logger.warning` gives you the operational view; the state gives
   you the model-visible view. They serve different readers.

**Why no `RetryPolicy` here, when the Planner has one?** Because there's a
better option than failing. A retry policy that runs out of attempts kills the
run, whereas degrading returns a report with 3 of 4 questions answered, with
the gap marked. Partial results beat no results. (Retrying once *then*
degrading is a reasonable upgrade; do it inside the node, not with a policy.)

## 5. Seeing parallel work: `debug` vs `updates`

The CLI used to number steps itself, and fan-out exposed the lie: three
researchers looked like steps 2, 3 and 4.

`stream_mode="updates"` yields **one chunk per task** with no step boundaries.
`stream_mode="debug"` yields `task` and `task_result` events that carry the
**real super-step number**, plus an `error` field per task:

```
[step 2] researcher     ← same number = ran together
[step 2] researcher
[step 2] researcher
[step 3] writer
```

Use `updates` when you want "what changed"; use `debug` when the timing and
structure of the run matter. Phase 4's live UI will stream exactly this.

## 6. Cost control lives where data is created

```python
MAX_RESULTS = 3  # search.py
MAX_NOTE_CHARS = 1000  # nodes.py
```

4 sub-questions × 3 results × ~1000 chars ≈ 12,000 characters ≈ 3,000 tokens
in the Writer's prompt — **and the Writer runs up to 3 times**, so every extra
character is paid for repeatedly. Capping at the point where notes are created
is much easier than trimming a prompt later.

## 7. What this node deliberately does *not* do yet

- No deduplication when two sub-questions return the same URL.
- No relevance filtering (Tavily returns a score we ignore).
- No fetching of full page content (`include_raw_content`): more evidence, far more tokens.

Each is a real improvement, and each should be justified by an eval number
rather than a hunch.

---

## Exercises

1. **Watch it fan out.** `uv run dossier run "<topic>"`. How many researchers
   in step 2? Why that number? (1 Gemini call + N searches.)
2. **Break the search on purpose.** Predict the outcome first, then run:
   ```bash
   TAVILY_API_KEY=not-a-real-key uv run dossier run "solid-state batteries"
   ```
   Does the run finish? What's in the notes? What did the log say?
3. **Remove the reducer.** Change `research_notes` to plain `list[Note]` in
   `state.py` and run `--offline`. Read the error, then put it back.
4. **Width is free.** Give the offline graph a fake planner returning 30
   sub-questions. Does `RECURSION_LIMIT` complain? Explain why not.
5. **Feel the token cost.** Set `MAX_RESULTS = 1`, run offline and compare the
   number of notes. Work out the character count that reaches the Writer at 1
   vs 3, then multiply by 3 revisions.
6. **Prove parallelism yourself.** Wrap `web_search` with a function that prints
   a timestamp and thread name at entry and exit.
7. **Trace it.** With LangSmith on, open the run and look at the timeline: the
   researcher spans overlap.

## Interview check

1. What does `Send` do that a conditional edge returning one node name can't?
2. What exactly does a researcher receive as its input, and why not the full state?
3. Why does `research_notes` need a reducer when `draft` doesn't?
4. Two searches fail out of five. What does the run produce, and why is that
   better than raising?
5. Why is a failed search recorded as a note rather than skipped?
6. Why is `except Exception` acceptable here but a `try` around the whole
   function body isn't?
7. How many super-steps does a fan-out of 20 researchers take? What does that
   mean for the recursion limit?

---

## Next: Step 4 — the Writer

→ [Lesson 4](04-writer-citations-revisions.md)
