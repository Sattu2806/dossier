# Lesson 2 — The Planner: your first real LLM node

**Goal:** make one node call a real model safely. That means structured
output instead of text parsing, a clear way to handle every failure, and tests
that still run with no API key.

Only the Planner is real. Researcher, Writer and Critic are still fakes, so
when something goes wrong there's only one place to look.

## What changed

```
src/dossier/
├── llm.py       NEW  the only file that knows we use Gemini
├── prompts.py   NEW  every prompt in one place (easy to diff and eval)
├── fakes.py     NEW  the Step 1 stubs moved here + FAKE_NODES
├── nodes.py          real planner (+ finalize)
├── graph.py          retry policy on planner; unbuilt nodes default to fakes
└── cli.py            --offline flag
tests/
├── test_graph.py     now runs on fakes + retry tests
└── test_planner.py   NEW  planner logic with a fake model
playground/           your prototype (gitignored, not linted)
```

---

## 1. Keep the provider behind one function (`llm.py`)

```python
@cache
def chat_model() -> BaseChatModel:
    return ChatGoogleGenerativeAI(model=os.getenv("DOSSIER_MODEL", DEFAULT_MODEL))
```

Three decisions are packed in here:

- **One file knows the provider.** Nodes call `chat_model()`, never
  `ChatGoogleGenerativeAI(...)`. Moving to Claude or GPT means changing one file.
  The return type is `BaseChatModel`, LangChain's common interface, so nodes only
  use methods every provider has (`invoke`, `with_structured_output`).
- **Created lazily, not at import time.** The prototype did
  `llm = ChatGoogleGenerativeAI(...)` at module level, so merely *importing*
  it needed a key, and tests couldn't import it without one.
  `test_building_the_real_graph_needs_no_api_key` guards this.
- **`@cache`** creates the client once and reuses it (one connection pool,
  one config) instead of building a new client on every node call.

**Why not `init_chat_model("google_genai:...")`?** It's LangChain's
"any provider from a string" helper, and it needs the extra `langchain` package.
We have one provider today. The moment we need a second one, probably a judge
model from a *different* family in Step 8 (so the model doesn't grade its own
style favourably), it's worth adding. Until then `llm.py` gives us the same
flexibility with no new dependency.

**The model is chosen by an environment variable** (`DOSSIER_MODEL`). You saw why this
matters today: `gemini-3.5-flash` hit its quota and we switched to
`gemini-3.5-flash-lite` without touching any code.

## 2. How structured output actually works

```python
class Plan(BaseModel):
    """A research plan for the given topic."""

    sub_questions: list[str] = Field(description="3 to 5 self-contained research sub-questions")


model = chat_model().with_structured_output(Plan)
plan = model.invoke([...])  # plan is a Plan object, not text
```

Under the hood (`method="json_schema"`, the default in langchain-google-genai 4.4):

1. Pydantic turns `Plan` into a **JSON Schema** (`Plan.model_json_schema()`).
2. That schema is sent with the request. Gemini uses **constrained decoding**:
   while generating, it can only produce tokens that keep the JSON valid for the schema.
3. The reply is parsed by `PydanticOutputParser` into a `Plan`.
4. If parsing fails, you get `OutputParserException`.

Compare with the alternative, "reply with a numbered list" plus
`text.split("\n")`. That breaks on the first "Sure! Here are your questions:".
With structured output the model *cannot* reply in the wrong format.

### The bug I caught today

Step 1 in that list turns **the class docstring and every `Field` description**
into schema text, and the schema goes to the model. The first version of
`Plan` had a developer note in its docstring ("a sixth question is not worth
crashing a run over…"), which meant **that note was prompt text sent on every call.**

Fix: developer notes go in `#` comments; the docstring and descriptions are
written *for the model*. A test now guards it. Check any schema with
`Plan.model_json_schema()`.

## 3. Strict schema or forgiving code?

A schema could enforce "3 to 5" with `Field(min_length=3, max_length=5)`. We
deliberately don't:

| Model returns | Strict schema | What we do |
|---|---|---|
| 6 questions | Validation error → retry → maybe crash | Keep the first 5 |
| `"  What is X? "` | Fine | Strip it |
| The same question twice | Fine | Remove duplicates |
| No questions | Validation error | Raise `OutputParserException` → retry |

**Validate what matters, normalize what doesn't.** An empty plan makes the run
meaningless, so it's an error. A sixth question isn't worth a failed run.

## 4. Prompt design (`prompts.py`)

**The system message holds instructions; the user message holds the topic.** The topic comes from a user,
so treat it as **untrusted input**. Keeping it apart from our instructions is the first,
cheapest defence against prompt injection. Phase 6 builds on this.

**"Self-contained" is the most important rule, and it comes from the architecture.**
In Step 3 each sub-question goes to a researcher **on its own**. If the
Planner writes *"What are its main drawbacks?"*, that researcher has no idea
what "it" is. The prompt is written for the node that *consumes* the output:

```
Each sub-question is sent on its own to a web search engine by a separate
researcher who never sees the topic or the other sub-questions.
```

Telling the model *why* ("a separate researcher who never sees the topic")
works better than a bare rule ("be self-contained"), because it can apply the reason
to cases the rule doesn't cover.

**What the live run showed:**

```
solid-state batteries
  - How do solid-state batteries compare to traditional lithium-ion batteries in
    terms of energy density, safety, and charging speed?
```

Self-contained ✓, doesn't overlap ✓, but "ask exactly one thing" ✗ (three things).
**A prompt makes an outcome more likely, not guaranteed.** Should we tighten it?
Don't guess: a single example is an anecdote. Step 8 turns this into a measurable
question ("what % of sub-questions ask one thing?").

## 5. Two ways an LLM call fails, and a retry layer for each

| Failure | Example | Who retries | How |
|---|---|---|---|
| **Transport** | Network drop, 429 rate limit, 5xx | Gemini client | `max_retries=6` built in |
| **Content** | Invalid JSON, empty plan | LangGraph | `RetryPolicy(max_attempts=3, retry_on=OutputParserException)` |
| **Bug** | `KeyError` in our code | Nobody | Fail immediately |

The subtle part, found in `langgraph/_internal/_retry.py`: LangGraph's
default `retry_on` **never retries `ValueError`** (or `TypeError`,
`KeyError`…), because those usually mean a bug, and retrying a bug only wastes
time. But `OutputParserException` **is a subclass of `ValueError`**:

```python
>>> OutputParserException.__mro__
(OutputParserException, ValueError, LangChainException, Exception, ...)
```

So with a plain `RetryPolicy()`, bad model output would **never be retried.**
We name the exception explicitly. Two tests pin this down: bad output is
retried, a `KeyError` is not.

**Retries aren't free.** Each retry is another paid call. Three attempts of a
failing planner took 3.1 seconds with backoff. With the real model, that's three
charges for nothing if the prompt itself is broken.

**A daily quota isn't a transient error.** The 429 you hit today was
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`. No amount of retrying helps
until tomorrow.

## 6. Three levels of fakes

| Level | What's faked | Tests | Needs key |
|---|---|---|---|
| Graph tests (`test_graph.py`) | Whole nodes (`FAKE_NODES`) | Routing, loop cap, retries | No |
| Node tests (`test_planner.py`) | Only the model (`FakeModel`) | Messages sent, output cleaning | No |
| Manual runs / evals | Nothing | Quality of the output | Yes |

`FakeModel` is 12 lines. It records the messages it receives and returns a
canned `Plan`. **Patch where the name is used, not where it's defined:**

```python
monkeypatch.setattr(nodes, "chat_model", lambda: model)  # ✓ nodes.py looks up its own name
monkeypatch.setattr(llm, "chat_model", lambda: model)  # ✗ nodes.py already imported the original
```

`from dossier.llm import chat_model` copies the reference into `nodes`'
namespace. Patching `llm` afterwards changes a name that `nodes` no longer reads.

## 7. Free-tier budget: plan for it now

What we learned today, from the API's own error:

- `gemini-3.5-flash` free tier: **20 requests/day**, per model, per project.
- One full run (planner + writer/critic loop + fact-check) is **about 10 calls**.
- An eval pass over 25 topics is **about 250 calls**. Model a budget before Step 8.

Options when we get there: lite models (separate quota), enabling billing (flash-lite
costs fractions of a cent per call), caching planner/researcher outputs so eval
reruns only pay for the node whose prompt changed. We'll pick then, using numbers.

---

## Exercises

1. **Read real plans.** Run `uv run dossier run "<topic>"` on 4 topics: something broad
   ("artificial intelligence"), a comparison, something very narrow, and a fictional
   topic ("migration of the Zorblex fish"). For each, check the four prompt rules.
   Which rule breaks most often? (Each run is 1 call.)
2. **Prove the prompt matters.** Delete the "self-contained" bullet *and* the
   sentence explaining why, then run a comparison topic. Do pronouns or vague
   references appear? Revert. Notice you can't be sure from one run; that's evals.
3. **See what structured output hides.** Use `with_structured_output(Plan, include_raw=True)`
   in a scratch script. You get `{"raw", "parsed", "parsing_error"}`. Find
   `raw.usage_metadata`: input/output tokens. That's the basis of the per-user
   cost cap in Phase 6.
4. **Strict vs forgiving.** Add `min_length=3, max_length=5` to the Field and
   print `Plan.model_json_schema()`. Where did `minItems`/`maxItems` go? Argue
   both sides, then revert.
5. **Exhaust the retries.** In a scratch script, give the offline graph a planner that
   always raises `OutputParserException`. Predict the number of attempts and the final error. Then
   make it raise `ValueError` instead and predict again.
6. **Trace it.** With LangSmith enabled, open a run and find the planner's LLM
   span: the system prompt, the JSON schema sent, and token counts.

## Interview check

1. Why use structured output instead of asking for a list and parsing it?
2. What exactly gets sent to the model when you call `with_structured_output(Plan)`?
3. Why does LangGraph's default retry policy not retry `OutputParserException`,
   and what did we do about it?
4. Transport failure vs content failure: who retries each, and why keep them apart?
5. Why is the topic in the user message and not formatted into the system prompt?
6. Why must sub-questions be self-contained, and what in the *architecture* forces it?
7. Why is the LLM client created lazily?

---

## Next: Step 3 — the Researcher

→ [Lesson 3](03-researcher-parallel-fanout.md)
