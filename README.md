# dossier

Give it a topic and it produces a researched report whose every claim is cited,
after the system has criticised and revised its own draft. A multi-agent system
built with **LangGraph**.

```
                             ┌─ web ──┐  one researcher per sub-question
topic → validate → planner ──┼─ web ──┼── PER SOURCE, all in one parallel step
                             ├─ docs ─┤
                             └─ docs ─┘
                                      │
     writer → fact-checker → critic ──┬── grounded AND passed ──► finalize
        ▲                             │
        └──── either one rejects, ────┘
              up to 3 drafts
```

Every claim cites a numbered source; the model never writes a URL. Sub-questions
whose searches fail are reported as gaps rather than filled in from memory.

**Or upload a book and be taught it.** A second graph turns a PDF into a
course: lessons in the order the ideas have to be learned, each explained as
if to a five-year-old and then properly, with a diagram, a worked example and
the passages it came from.

```
outline → lesson × N (in parallel) → assemble
```

**Four ways in:** a CLI, an HTTP API with live progress, an MCP server for
Claude Desktop, and a Next.js front end.

## Results

27 topics, judged 1–5 by an LLM judge running on a *different* model from the
one that wrote the reports. Reproduce with `uv run dossier eval`; raw data in
[`evals/results/`](evals/results).

| | |
|---|---|
| topics evaluated | **27** (0 failed runs, 0 unjudged) |
| groundedness | **4.85** / 5 |
| completeness | **4.74** / 5 |
| coherence | **5.00** / 5 |
| usefulness | **4.74** / 5 |
| invented citations | **0** across all 27 reports |
| drafts that passed review first time | **100%** |
| average report | 683 words, 10.1 cited sources |
| average run | 10.9s (1 planner call, N parallel searches, 1 writer call, 1 critic call) |

### What those numbers actually say

**The revision loop never ran**, so `avg_revisions` is 1.0 and the loop-back
edge — the whole point of using a graph — did no work in this run.

I ran the obvious experiment: raise `PASS_THRESHOLD` from 4 to 5 over six
topics (`evals/results-threshold5/`). **The loop still never fired**, because
the Critic scored 5/5/5 on every real draft. That is not the same as a lenient
critic in general: probed with deliberately flawed drafts it gives groundedness
1 to invented figures and completeness 2 to a report that skips a sub-question.
It simply finds no fault in drafts produced by a writer that is already
constrained to cite supplied evidence — and the independent judge broadly
agrees, at 4.74–5.00.

So the honest conclusion is that **the loop is insurance, not a routine
improvement path**: it costs one critic call per run (~3k input tokens) and
earns its place only when a draft is genuinely bad. Making it fire more often
would mean a stricter critic (a stronger model, or a rubric that forces at
least one issue), and that change has to be justified by scores, not by taste.

**A measured noise floor.** Since no revision occurred, "first draft" and
"final report" are the same text scored twice. The judge returned an average
0.04 apart over six topics, and moved a single topic by 0.25. **Any future
"improvement" smaller than that is noise**, which is exactly the number you
need before trusting a prompt tweak.

**Zero invented citations** is a real result, and it isn't the model's doing:
citation numbers are assigned by code, the model is never shown a URL, and
`finalize` drops any number that was never issued.

**The adversarial topics were the most useful.** Asked about a fictional fish,
the system reported `NO EVIDENCE AVAILABLE` for every sub-question instead of
inventing marine biology. Given a prompt-injection string as a topic, it did not
follow the instruction — but it also didn't refuse; it researched cats. Given
gibberish, it produced a straight-faced report about the QWERTY layout and the
QQQ ETF. Those two findings became the guardrails in
[lesson 7](docs/learn/07-guardrails-and-budgets.md): both topics are now refused
before a single paid call, and the eval set keeps them so the refusal stays tested.

**These numbers describe the pipeline as it was measured**, before the
fact-checker and document search were added. `run_fingerprint()` includes a
`PIPELINE_VERSION`, so those cached results are already invalidated and a
re-run over all 27 topics is the next thing to do with a day's quota.

### Since then: the loop woke up

A 6-topic run on the newer pipeline (`evals/results-v2/`) changed the
conclusion above:

| | Phase 1 (27 topics) | with fact-checker (6 topics) |
|---|---|---|
| average drafts | 1.00 | **1.50** |
| passed on the first draft | 100% | **67%** |
| judge groundedness | 4.85 | **5.00** |
| judge usefulness | 4.74 | 4.50 |
| seconds per run | 10.9 | 16.8 |

**Adding a second, narrower reviewer is what made the revision loop do
work.** The Critic, asked to judge a report as a whole, found nothing wrong;
the Fact-Checker, asked only "does the evidence support this sentence?", sent
a third of the drafts back — and groundedness reached 5.00. One topic went to
the full three drafts because the Critic scored its completeness 2.

Six topics is not 27, and the subsets differ, so this is a signal rather than
a verdict — but it is the kind of signal the harness exists to produce.

## Quick start

```bash
uv sync
cp .env.example .env          # GEMINI_API_KEY + TAVILY_API_KEY
uv run dossier run "solid-state batteries"
```

```bash
uv run dossier run --offline "anything"   # fake nodes, no API keys, no cost
uv run dossier ingest paper.pdf notes.md  # search your own documents too
uv run dossier diagram                     # Mermaid diagram of the graph
uv run pytest                              # 200 tests, none need a key
```

### The API and the web app

```bash
uv run dossier user you@example.com   # prints an API key, once
uv run dossier serve                  # http://127.0.0.1:8500
npm --prefix web run dev              # http://localhost:3600
```

Sign in (Clerk, if keys are set) or paste an API key, then either ask a
question or drop a PDF on **Learn a book** and watch the outline and lessons
arrive over the same SSE channel.

The browser watches a run happen over SSE — including "Researching ×8 in
parallel" — then renders the cited report. The API key is held in an httpOnly
cookie and attached by a Next.js proxy route, so it is never readable from the
page.

### From Claude Desktop (MCP)

```bash
uv run dossier mcp
```

```json
{ "mcpServers": { "dossier": {
  "command": "uv",
  "args": ["run", "--directory", "/path/to/dossier", "dossier", "mcp"],
  "env": { "GEMINI_API_KEY": "...", "TAVILY_API_KEY": "..." }
} } }
```

Tools: `search_web`, `search_documents`, `document_library`, `research`.

### Docker and deployment

```bash
docker compose up --build     # API on Postgres instead of SQLite
```

Deployment notes are in [docs/DEPLOY.md](docs/DEPLOY.md), including a
no-card free path (Hugging Face Space + Neon + Vercel). The short version:
the API runs the graph *after* returning `202` and keeps its vector index on
disk, so it needs a long-lived container with a volume — not a serverless
function. The web app has no such constraint.

Evals:

```bash
uv run dossier eval --offline --limit 5    # exercise the harness for free
uv run dossier eval --limit 5              # the real thing, quota permitting
```

Results are cached per topic and keyed by a fingerprint of the prompts and
models, split into a **run** fingerprint and a **judge** fingerprint: changing
a node prompt re-runs the graph, while changing the judge only re-scores the
reports you already paid for.

## Design decisions worth defending

| decision | why |
|---|---|
| Scores from the model, pass/fail in code | the bar is a number you can move and measure, not a mood |
| Citation numbers assigned by code | models mangle URLs; integers they handle, and invented ones are detectable for free |
| Failed searches become typed `status` gaps | a gap the Writer can see is a gap it won't invent over |
| Fan-out with `Send` + `operator.add` reducer | 3 searches in 8.7s wall clock vs 21.5s serially; width decided at runtime |
| Every node injectable (`build_graph(critic=...)`) | the whole suite runs with no API key and no network |
| Retry only `OutputParserException` | bad model output deserves a retry; a `KeyError` in our code does not |
| Two loop limits | `MAX_REVISIONS` is the product rule, `recursion_limit` is the bug net |
| Judge on a different model, validated first | an uncalibrated judge made everything look like 5/5 |
| `web_search` and `doc_search` share a signature | the Researcher never learns there are two kinds of source; a third is one dict entry |
| A measured relevance floor on document search | a vector store always returns its nearest chunk — mine cited a fish survey for a question about rent control |
| Fact-Checker separate from Critic | "does the evidence say this?" and "is this good?" need different attention |
| A second graph for study guides, not a mode flag | different state, no review loop, one source instead of many — the shared part is retrieval, not the pipeline |
| The outline reads opening pages, not search results | "what is this book about" matches no passage in particular |
| Generated examples are parsed, never executed | running model-written code for whoever uploaded a PDF is RCE with a friendly name |
| Mermaid repaired in code *and* fixed in the prompt | a prompt makes an outcome likelier, never certain — and the repair is pattern-bounded so it cannot damage valid input |
| Validation as the first graph node | CLI, API and MCP cannot forget it |
| Token budget as a LangChain callback | it sees calls made inside `with_structured_output`, which node-level counting cannot |
| Hashed API keys, not JWTs | one service that already hits the database per request; instant revocation beats stateless verification here |
| SSE events kept and replayed | a run that finishes before the browser connects would otherwise show nothing |
| The human-approval pause sits right after the Planner | one call spent, every search still ahead — the cheapest point at which stopping saves real money |
| Approval is opt-in, not the default | the CLI and MCP server must not hang waiting for a human who isn't there |
| Cancelling means never resuming | an unanswered interrupt costs nothing and expires with its checkpoint; a cancel endpoint would be a second way to do the same thing |

## Learning notes

Written as this was built, one step at a time:

- [1 — Project setup & the graph skeleton](docs/learn/01-setup-and-graph-skeleton.md)
- [2 — The Planner: your first real LLM node](docs/learn/02-planner-structured-output.md)
- [3 — The Researcher: parallel fan-out and failing well](docs/learn/03-researcher-parallel-fanout.md)
- [4 — The Writer: grounding, citations, revisions](docs/learn/04-writer-citations-revisions.md)
- [5 — The Critic: rubric, verdict, and who decides](docs/learn/05-critic-rubric-and-policy.md)
- [6 — Evals, and judging the judge](docs/learn/06-evals-and-judging-the-judge.md)
- [7 — Guardrails and budgets](docs/learn/07-guardrails-and-budgets.md)
- [8 — Your own documents, and a separate fact-checker](docs/learn/08-rag-and-fact-checking.md)
- [9 — An MCP server for the research tools](docs/learn/09-mcp-server.md)
- [10 — API, live UI, and shipping](docs/learn/10-api-ui-and-shipping.md)
- [11 — Teaching a book](docs/learn/11-study-guides.md)

[Roadmap](docs/ROADMAP.md) — every phase is built; what remains open is listed
there honestly, including the images that have never been built and the
revision loop that does not currently fire.

## Configuration

| variable | default | purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | required for real runs |
| `TAVILY_API_KEY` | — | required for real searches |
| `DOSSIER_MODEL` | `gemini-3.5-flash-lite` | model for every node |
| `DOSSIER_<ROLE>_MODEL` | — | per-role override (`PLANNER`, `WRITER`, `CRITIC`, `JUDGE`) |
| `DOSSIER_PASS_THRESHOLD` | `4` | the score every rubric dimension must reach |
| `LANGSMITH_TRACING` | `false` | set to `true` with a key for traces |
| `DOSSIER_MIN_RELEVANCE` | `0.5` | document matches below this are discarded (measured, not guessed) |
| `DOSSIER_APPROVE_PLAN` | `false` | pause after the Planner so a human can edit the sub-questions |
| `DOSSIER_MAX_UPLOAD_MB` | `12` | largest book you can upload |
| `DOSSIER_MAX_PAGES` | `400` | pages per upload — each one costs embedding calls |
| `DOSSIER_MAX_DOCUMENTS` | `20` | books kept per user |
| `DOSSIER_MAX_TOKENS` | `120000` | per-run token budget |
| `DOSSIER_DAILY_TOKEN_LIMIT` | `500000` | per-user, per-day budget |
| `DOSSIER_DATABASE_URL` | `sqlite:///data/dossier.db` | `postgresql+psycopg://…` in production |
| `DOSSIER_PRICE_PER_M_INPUT` / `_OUTPUT` | `0` | set from your provider's pricing for cost estimates |
