"""HTTP API: start a run, watch it happen, read the history.

Three things make this more than a wrapper around the CLI:

- **Runs are slow** (10-60s), so the request that starts one returns
  immediately and progress arrives over Server-Sent Events. A user watching
  "researching question 3 of 4" tolerates a wait that a blank spinner doesn't.
- **Runs cost money**, so a per-user daily token budget is checked *before*
  anything starts and recorded after it finishes.
- **Runs belong to someone**, so every query is scoped to the caller's user id.
"""

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from dossier import db
from dossier.graph import build_graph
from dossier.guardrails import BudgetExceeded, InvalidTopic, TokenBudget

logger = logging.getLogger(__name__)

# How many finished runs keep their event history in memory, so a client that
# connects late — or a second browser tab — still sees the whole run.
CHANNEL_HISTORY = 50


class RunChannel:
    """Fan-out of one run's events, with replay.

    Without the replay, a run that finishes before the browser opens the
    stream would emit its progress into nothing and the UI would show an empty
    list. Keeping the history also means a second viewer sees the same run.
    """

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self.closed = False

    async def publish(self, event: str, data) -> None:
        message = {"event": event, "data": _json(data)}
        self.events.append(message)
        for queue in self.subscribers:
            await queue.put(message)
        if event in {"done", "error"}:
            self.closed = True

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)


# In-process on purpose: one box, one worker. The moment there are two workers
# this becomes Redis pub/sub, which is why publishing goes through one class.
_channels: dict[str, RunChannel] = {}


def _channel(run_id: str) -> RunChannel:
    _channels[run_id] = _channels.get(run_id) or RunChannel()
    # Bounded memory: drop the oldest finished runs.
    while len(_channels) > CHANNEL_HISTORY:
        oldest = next(iter(_channels))
        if oldest == run_id:
            break
        _channels.pop(oldest)
    return _channels[run_id]


# Human-readable labels: the UI should not have to know node names.
NODE_LABELS = {
    "validate": "Checking the topic",
    "planner": "Planning sub-questions",
    "researcher": "Researching",
    "writer": "Writing the draft",
    "fact_checker": "Fact-checking against sources",
    "critic": "Reviewing quality",
    "finalize": "Adding citations",
}


class ResearchRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init(app.state.db)

    # Seed the first user from secrets, for hosts with no shell.
    email = os.getenv("DOSSIER_BOOTSTRAP_EMAIL")
    key = os.getenv("DOSSIER_BOOTSTRAP_KEY")
    if email and key:
        created = db.ensure_user(
            app.state.db,
            email,
            key,
            daily_token_limit=int(os.getenv("DOSSIER_BOOTSTRAP_TOKEN_LIMIT", str(db.DAILY_TOKEN_LIMIT))),
        )
        logger.info("bootstrap user %s: %s", email, "created" if created else "already present")

    yield


def create_app(database=None, graph=None) -> FastAPI:
    """Both dependencies are injectable, so tests run against a temporary
    database and a graph of fakes — no keys, no network, no cost."""
    app = FastAPI(title="dossier", version="0.1.0", lifespan=lifespan)
    app.state.db = database or db.engine()
    app.state.graph = graph or build_graph()

    def current_user(authorization: str = Header(default="")) -> dict:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Send your API key as: Authorization: Bearer <key>")
        user = db.user_for_key(app.state.db, authorization.removeprefix("Bearer ").strip())
        if not user:
            raise HTTPException(401, "Unknown API key")
        return user

    @app.get("/health")
    def health() -> dict:
        """Also reports what is running.

        "Which commit is live?" is the first question when a deploy
        misbehaves, and without this the only way to answer it is to trust the
        dashboard. Hosts expose the deployed SHA in their own variable.
        """
        commit = (
            os.getenv("RENDER_GIT_COMMIT")
            or os.getenv("RAILWAY_GIT_COMMIT_SHA")
            or os.getenv("SOURCE_COMMIT")
            or os.getenv("GIT_COMMIT")
        )
        return {
            "status": "ok",
            "version": version("dossier"),
            "commit": commit[:7] if commit else None,
        }

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)) -> dict:
        used = db.tokens_used_today(app.state.db, user["id"])
        return {
            "email": user["email"],
            "tokens_used_today": used,
            "daily_token_limit": user["daily_token_limit"],
            "tokens_remaining": max(0, user["daily_token_limit"] - used),
        }

    @app.post("/api/research", status_code=202)
    async def start_research(request: ResearchRequest, user: dict = Depends(current_user)) -> dict:
        used = db.tokens_used_today(app.state.db, user["id"])
        if used >= user["daily_token_limit"]:
            # 429 before any work: the cheapest possible way to enforce a budget.
            raise HTTPException(
                429,
                f"Daily token budget spent ({used:,}/{user['daily_token_limit']:,}). Try again tomorrow.",
            )

        run_id = secrets.token_hex(8)
        db.start_run(app.state.db, run_id, user["id"], request.topic)
        _channel(run_id)
        asyncio.create_task(_execute(app, run_id, request.topic, user))
        return {"run_id": run_id, "stream_url": f"/api/runs/{run_id}/stream"}

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str, request: Request, user: dict = Depends(current_user)):
        record = db.get_run(app.state.db, run_id, user["id"])
        if not record:
            raise HTTPException(404, "No such run")

        async def events() -> AsyncIterator[dict]:
            channel = _channels.get(run_id)
            if channel is None:
                # Older than the in-memory history: replay the stored result.
                yield {"event": "done", "data": _json(record)}
                return

            queue = channel.subscribe()
            try:
                # Everything that already happened, in order, before anything new.
                for message in list(channel.events):
                    yield message
                    if message["event"] in {"done", "error"}:
                        return
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=30)
                    except TimeoutError:
                        yield {"event": "ping", "data": "{}"}  # stop proxies closing the connection
                        continue
                    yield message
                    if message["event"] in {"done", "error"}:
                        return
            finally:
                channel.unsubscribe(queue)

        return EventSourceResponse(events())

    @app.get("/api/runs")
    def history(user: dict = Depends(current_user), limit: int = 20) -> dict:
        return {"runs": db.list_runs(app.state.db, user["id"], limit=min(limit, 100))}

    @app.get("/api/runs/{run_id}")
    def one_run(run_id: str, user: dict = Depends(current_user)) -> dict:
        record = db.get_run(app.state.db, run_id, user["id"])
        if not record:
            raise HTTPException(404, "No such run")
        return record

    return app


def _json(payload) -> str:
    import json

    return json.dumps(payload, default=str)


async def _publish(run_id: str, event: str, data) -> None:
    channel = _channels.get(run_id)
    if channel is not None:
        await channel.publish(event, data)


async def _execute(app: FastAPI, run_id: str, topic: str, user: dict) -> None:
    """Run the graph off the event loop and stream what happens.

    The graph is synchronous, so it goes to a worker thread; progress crosses
    back through the loop with run_coroutine_threadsafe. Without the thread,
    one research run would block every other request on the server.
    """
    loop = asyncio.get_running_loop()
    budget = TokenBudget(max_tokens=user["daily_token_limit"] - db.tokens_used_today(app.state.db, user["id"]))
    state: dict = {}

    def emit(event: str, data) -> None:
        asyncio.run_coroutine_threadsafe(_publish(run_id, event, data), loop)

    def run_graph() -> dict:
        final: dict = {}
        # Metadata and tags make a trace findable later: LangSmith can then
        # answer "show me runs for this user that were sent back by the
        # fact-checker", which a wall of anonymous traces cannot.
        config = {
            "callbacks": [budget],
            "run_name": f"research: {topic[:60]}",
            "tags": ["dossier", "api"],
            "metadata": {"run_id": run_id, "user_id": user["id"], "topic": topic},
        }
        stream = app.state.graph.stream({"topic": topic}, stream_mode="debug", config=config)
        for event in stream:
            if event["type"] == "task":
                name = event["payload"]["name"]
                emit("progress", {"step": event["step"], "node": name, "label": NODE_LABELS.get(name, name)})
            elif event["type"] == "task_result":
                final.update(event["payload"]["result"])
        return final

    try:
        state = await asyncio.to_thread(run_graph)
    except InvalidTopic as exc:
        db.finish_run(app.state.db, run_id, status="failed", error=str(exc), tokens=budget.total_tokens)
        await _publish(run_id, "error", {"error": str(exc), "kind": "invalid_topic"})
        return
    except BudgetExceeded as exc:
        db.finish_run(app.state.db, run_id, status="failed", error=str(exc), tokens=budget.total_tokens)
        await _publish(run_id, "error", {"error": str(exc), "kind": "budget_exceeded"})
        return
    except Exception as exc:
        logger.exception("run %s failed", run_id)
        db.finish_run(app.state.db, run_id, status="failed", error=str(exc), tokens=budget.total_tokens)
        await _publish(run_id, "error", {"error": f"{type(exc).__name__}: {exc}", "kind": "failed"})
        return

    db.finish_run(
        app.state.db,
        run_id,
        status="done",
        report=state.get("final_report", ""),
        drafts=state.get("revision_count", 0),
        grounded=state.get("grounded"),
        passed_review=state.get("critique_passed"),
        tokens=budget.total_tokens,
        sub_questions=state.get("sub_questions", []),
        critique_scores=state.get("critique_scores", {}),
    )
    await _publish(run_id, "done", db.get_run(app.state.db, run_id, user["id"]))


app = None  # built by serve(), so importing this module never touches a database


def port() -> int:
    """PORT is injected by most hosts (Railway, Render, Heroku, Cloud Run) and
    must win: binding to the wrong port is the classic "deploy succeeds, health
    check fails" afternoon."""
    return int(os.getenv("PORT") or os.getenv("DOSSIER_PORT", "8500"))


def configure_logging() -> None:
    """Without this, our logger.info calls go nowhere: nothing configures the
    root logger, so only WARNING and above reach stderr via the last-resort
    handler. On a hosted box the logs are all you get, and "which searches
    failed, what the critic scored" is exactly what you need at 2am."""
    logging.basicConfig(
        level=os.getenv("DOSSIER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def serve() -> None:
    import uvicorn

    configure_logging()
    uvicorn.run(create_app(), host=os.getenv("DOSSIER_HOST", "127.0.0.1"), port=port())
