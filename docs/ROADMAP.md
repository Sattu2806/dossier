# Roadmap

Built slowly, one step at a time, with a lesson in `docs/learn/` for each.

## Phase 1 — Core graph

- [x] **1. Skeleton, no LLM**: State, stub nodes, wiring, conditional loop, mechanics tests → [lesson](learn/01-setup-and-graph-skeleton.md)
- [x] **2. Planner**: Gemini via structured output, retry on bad output, fakes for offline tests → [lesson](learn/02-planner-structured-output.md)
- [x] **3. Researcher**: Tavily per sub-question, parallel fan-out with `Send` + `operator.add` reducer, failures degrade to typed gap notes → [lesson](learn/03-researcher-parallel-fanout.md)
  - later, once evals can judge it: dedupe repeated URLs, filter by Tavily score, consider `include_raw_content`
- [x] **4. Writer**: grounded drafting with `[n]` citations, gaps admitted, revisions that edit the previous draft; finalize lists only cited sources and flags invented numbers → [lesson](learn/04-writer-citations-revisions.md)
  - measure in Step 8: does a revision actually improve the score? (a wrong critique still got complied with)
  - measure in Step 8: LaTeX math leaking into Markdown output; 400–700 word target
- [x] **5. Critic**: rubric scores from the model, pass/fail policy in code, coverage enumerated before scoring → [lesson](learn/05-critic-rubric-and-policy.md)
- [x] **6. Conditional edge with real critic**: fail → writer, cap → finalize anyway (wired in Step 1, now driven by real scores)
- [x] **7. Manual runs + probes**: read real reports, then probed critic and judge with known-good/bad drafts
- [x] **8. Eval set**: 27 topics (incl. adversarial), LLM-as-judge with a different model, cached + resumable, CSV/JSON out → [lesson](learn/06-evals-and-judging-the-judge.md)
- [x] **9. README with numbers**: see the results table in [README](../README.md)

Known gaps to fix in later phases, found by the evals:
- no input validation: a gibberish topic is researched straight-faced (Phase 6)
- the model sometimes emits LaTeX in Markdown output
- source quality is unfiltered: a YouTube podcast and an SEO market-report page carry the same weight as a peer-reviewed page

## Later phases

- [x] **2. Doc RAG + Fact-Checker**: ingest PDFs/Markdown, Chroma + Gemini embeddings, hybrid fan-out over web *and* documents, relevance floor, separate fact-checking node → [lesson](learn/08-rag-and-fact-checking.md)
- [x] **3. MCP server**: `dossier mcp` exposes search_web / search_documents / document_library / research over stdio → [lesson](learn/09-mcp-server.md)
- [x] **4. FastAPI + SSE + persistence + auth**: 202 + event stream with replay, hashed API keys, per-user history, SQLAlchemy Core (SQLite locally, Postgres by URL) → [lesson](learn/10-api-ui-and-shipping.md)
- [x] **5. Tracing + CI**: LangSmith run names/tags/metadata on every run; GitHub Actions runs lint + 133 keyless tests on push, evals nightly with a quality floor
- [x] **6. Guardrails + cost caps**: topic validation as the first node, token budget callback, per-user daily limit enforced before work starts → [lesson](learn/07-guardrails-and-budgets.md)
- [x] **7. Next.js frontend**: live progress over SSE, cited report, history; API key in an httpOnly cookie behind a proxy route
- [x] **8. Docker + deploy**: two-stage Dockerfile, compose with Postgres, CI workflow

## Still open

- **Docker images are unbuilt**: no Docker daemon on the machine they were written on. `docker compose up --build` is the first thing to try.
- **Deployment target undecided** (Render / Fly.io / Railway) — needs a host, a managed Postgres and the two API keys as secrets.
- **The revision loop is inert**: the critic passes ~100% of first drafts even at `PASS_THRESHOLD=5`. Next experiment: a stronger critic model, or a rubric that forces at least one issue.
- **Judge self-preference**: judge and writer are both Gemini. A different provider would make the benchmark more credible.
- **LaTeX leaks into Markdown output** occasionally (`$r = 0.88$`).
- **Source quality is unweighted**: a YouTube page and a peer-reviewed paper carry equal weight.
- **One box only**: SSE channels are in-process. Two workers means Redis pub/sub for progress and a real job queue.
