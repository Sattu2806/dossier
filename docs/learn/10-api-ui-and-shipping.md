# Lesson 10 — API, live UI, and shipping

**Goal:** turn the pipeline into something a person can use from a browser,
with progress they can watch, history they can return to, and limits that
protect the bill.

```
Next.js (3600) ──► /api/proxy/* ──► FastAPI (8500) ──► LangGraph
   httpOnly cookie      adds bearer       SSE + SQLite/Postgres
```

## 1. A slow run needs a different request shape

A research run takes 10–60 seconds. That rules out "POST and wait":

```
POST /api/research      → 202 {run_id, stream_url}      (starts a background task)
GET  /api/runs/{id}/stream → text/event-stream            (progress, then the report)
GET  /api/runs             → history
```

The graph is **synchronous**, so it runs in a worker thread
(`asyncio.to_thread`) and pushes progress back through the event loop with
`run_coroutine_threadsafe`. Without the thread, one research run would block
every other request on the server — the classic way an async framework ends up
slower than a sync one.

The events are the `stream_mode="debug"` events from Lesson 3, relabelled for
humans: `planner` → "Planning sub-questions". The UI should not have to know
node names.

## 2. The race that only appears in a real browser

The first version lost every progress event when a run finished before the
browser connected — a queue with no subscriber, and a UI showing nothing. In
tests it passed, because the timing happened to work.

The fix is a channel that keeps its history:

```python
class RunChannel:
    events: list[dict]  # everything that happened, replayed to new subscribers
    subscribers: list[Queue]  # everyone currently watching
```

A subscriber replays the history first, then follows live. This also gives two
browser tabs the same run for free, and a reconnect after a dropped connection.
Memory is bounded to the last 50 runs; older ones fall back to the stored
result in the database.

A 30-second `ping` event keeps proxies from closing an idle stream.

## 3. The key never reaches the browser

`EventSource` cannot send an `Authorization` header. The usual workarounds are
a key in the query string (which lands in logs) or a key in `localStorage`
(readable by any script that gets onto the page).

Instead the Next.js app holds the key in an **httpOnly cookie** and proxies:

```
browser → /api/proxy/api/runs/x/stream   (same origin, cookie sent automatically)
         → route handler adds Authorization: Bearer …
         → FastAPI
```

The proxy passes the SSE body straight through rather than awaiting it —
`await response.text()` would buffer every progress event until the run
finished, which is a subtle way to break streaming while all the tests pass.

The key is verified against `/api/me` **before** the cookie is set, so a typo
fails at the connect screen instead of on every later request.

## 4. Why API keys rather than JWTs

A hashed key in a table, `Authorization: Bearer dsr_…`, and only the hash is
stored — the key is shown once, at creation.

JWTs buy stateless verification, which matters when many services must
validate a token without a shared database. This is one service that already
queries its database on every request to check the user's budget, so a key
lookup costs nothing extra and buys **instant revocation** — deleting the row
ends access immediately, where a JWT stays valid until it expires. If a second
service appears, that trade-off flips.

## 5. Budgets belong before the work

```python
if used >= user["daily_token_limit"]:
    raise HTTPException(429, ...)
```

Checked before anything starts, recorded when the run ends, and the run's own
`TokenBudget` is sized to what the user has left — so a single run cannot blow
through a budget that a check-afterwards design would only notice too late.

## 6. What the browser found that tests didn't

Two real bugs surfaced in the first UI run, and neither could have:

- **Every search timed out at once** (four concurrent Tavily calls, 20s). The
  system degraded exactly as designed — an honest "no sources found" report
  rather than a crash or invention — but the right response was a **single
  retry before degrading**, which is now in the Researcher.
- **The report cited a fish survey for a question about rent control.** The
  vector store returned its nearest chunk regardless of distance. That became
  the relevance floor in Lesson 8.

**Running the thing end to end is a different test from running the tests.**

## 7. Shipping

- **Dockerfile**: two stages, dependencies installed once with uv into a
  virtualenv that the runtime image copies, so uv itself never ships. Non-root
  user, `/data` volume for the vector index, and a healthcheck written in
  Python because a slim image has no curl.
- **compose**: the same image against Postgres instead of SQLite. Only
  `DOSSIER_DATABASE_URL` changes — the reason `db.py` uses SQLAlchemy Core
  against a URL instead of the `sqlite3` module.
- **CI**: lint, the full test suite and an offline pipeline smoke test on every
  push — possible only because nothing in the suite needs a key. Evals run
  nightly or on demand, with a **quality floor** that fails the job if
  groundedness or completeness drops below 4.0, and the results uploaded as an
  artifact so a regression is visible in the run history.

Those last two are the point of Phase 1: because the eval harness exists and
prints numbers, CI can refuse a prompt change that makes the reports worse.

---

## Exercises

1. **Watch the stream with curl**, not the UI:
   `curl -N localhost:8500/api/runs/<id>/stream -H "Authorization: Bearer <key>"`.
2. **Break the replay.** Remove the history loop in the SSE generator, start a
   run, and open the stream a few seconds late.
3. **Set a tiny budget.** `dossier user test@x.com --daily-token-limit 3000`,
   then run two topics and read the 429.
4. **Switch to Postgres** with compose, run a topic, and confirm the history
   survives `docker compose restart api`.
5. **Make CI fail.** Lower the quality floor in the workflow below the current
   scores, then push — and watch the gate work.

## Interview check

1. Why does starting a run return 202 rather than the report?
2. Why does the graph run in a thread?
3. What breaks if a client connects to the stream late, and how is it fixed?
4. Why can't the browser hold the API key, and where does it live instead?
5. When would you choose JWTs over hashed API keys here?
6. Why is the daily budget checked before the run rather than after?
