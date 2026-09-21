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
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from dossier import auth, db, docstore
from dossier.graph import build_graph
from dossier.guardrails import BudgetExceeded, InvalidTopic, TokenBudget
from dossier.learn import build_learn_graph

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


# Uploads are bounded in three directions, because each one costs differently:
# bytes (bandwidth and memory), pages (embedding calls), documents (storage).
MAX_UPLOAD_BYTES = int(os.getenv("DOSSIER_MAX_UPLOAD_MB", "12")) * 1024 * 1024
MAX_PAGES = int(os.getenv("DOSSIER_MAX_PAGES", "400"))
MAX_DOCUMENTS_PER_USER = int(os.getenv("DOSSIER_MAX_DOCUMENTS", "20"))

# Human-readable labels: the UI should not have to know node names.
NODE_LABELS = {
    "validate": "Checking the topic",
    "planner": "Planning sub-questions",
    "researcher": "Researching",
    "writer": "Writing the draft",
    "fact_checker": "Fact-checking against sources",
    "critic": "Reviewing quality",
    "finalize": "Adding citations",
    # the study-guide graph
    "outline": "Reading the book and planning lessons",
    "lesson": "Writing a lesson",
    "assemble": "Putting the guide together",
}


class ResearchRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)


class GuideRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=64)


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


def create_app(database=None, graph=None, learn_graph=None) -> FastAPI:
    """Both dependencies are injectable, so tests run against a temporary
    database and a graph of fakes — no keys, no network, no cost."""
    app = FastAPI(title="dossier", version="0.1.0", lifespan=lifespan)
    app.state.db = database or db.engine()
    app.state.graph = graph or build_graph()
    app.state.learn_graph = learn_graph or build_learn_graph()

    def current_user(authorization: str = Header(default="")) -> dict:
        """Accept either credential and return the same user row.

        An API key identifies a machine; a Clerk session identifies a person.
        Everything downstream — budgets, history, ownership — works off the
        row, so nothing else in the app has to know which was used.
        """
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Send a bearer token: Authorization: Bearer <key or session>")
        token = authorization.removeprefix("Bearer ").strip()

        # API keys are ours and recognisable, so check them first and avoid a
        # pointless signature verification on every CLI request.
        if token.startswith("dsr_"):
            user = db.user_for_key(app.state.db, token)
            if not user:
                raise HTTPException(401, "Unknown API key")
            return user

        if not auth.clerk_is_configured():
            raise HTTPException(401, "Unknown API key")

        try:
            claims = auth.verify_clerk_token(token)
        except auth.InvalidToken as exc:
            raise HTTPException(401, f"Session rejected: {exc}") from None

        user = db.user_for_clerk_id(app.state.db, claims["sub"])
        if user:
            return user
        # First request from a new account: create it now rather than relying
        # on a signup webhook arriving first.
        return db.create_clerk_user(app.state.db, claims["sub"], auth.email_from_claims(claims))

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
            # Tells the UI whether to offer sign-in or ask for a key.
            "auth": "clerk" if user.get("clerk_user_id") else "api_key",
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

        # Per-user limits bound one person. This bounds a bad day: open signup
        # spends the operator's provider quota, not the visitor's.
        if db.GLOBAL_DAILY_TOKEN_LIMIT:
            spent = db.tokens_used_today_globally(app.state.db)
            if spent >= db.GLOBAL_DAILY_TOKEN_LIMIT:
                raise HTTPException(429, "This instance has spent its daily budget. Try again tomorrow.")

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

        return EventSourceResponse(_events(run_id, record, request))

    # --- documents ------------------------------------------------------

    @app.post("/api/documents", status_code=201)
    async def upload(file: UploadFile = File(...), user: dict = Depends(current_user)) -> dict:
        """Take a PDF (or text) and make it searchable.

        Read into memory deliberately: the size cap is small, and streaming to
        disk to then read it back buys nothing at this scale.
        """
        if db.document_count_for(app.state.db, user["id"]) >= MAX_DOCUMENTS_PER_USER:
            raise HTTPException(429, f"You can keep {MAX_DOCUMENTS_PER_USER} documents. Delete one first.")

        name = Path(file.filename or "document").name
        if Path(name).suffix.lower() not in {".pdf", ".txt", ".md"}:
            raise HTTPException(415, "Upload a PDF, a text file or Markdown.")

        contents = await file.read()
        if not contents:
            raise HTTPException(400, "That file is empty.")
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"That file is {len(contents) / 1e6:.1f} MB; the limit is {MAX_UPLOAD_BYTES // 1024 // 1024} MB."
            )

        document_id = secrets.token_hex(8)
        # A real temporary file, because pypdf wants a path and the file is
        # gone as soon as the chunks are embedded.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / name
            path.write_bytes(contents)

            try:
                pages = docstore.read_pages(path)
            except Exception as exc:
                logger.warning("could not read %s: %s", name, exc)
                raise HTTPException(
                    422, "That file could not be read. Is it a scanned image rather than text?"
                ) from None

            if len(pages) > MAX_PAGES:
                raise HTTPException(413, f"That document has {len(pages)} pages; the limit is {MAX_PAGES}.")
            if not any(page.strip() for page in pages):
                raise HTTPException(
                    422,
                    "No text could be extracted. A scanned PDF needs to be run through OCR first.",
                )

            title = Path(name).stem.replace("_", " ").replace("-", " ").strip() or name
            result = await asyncio.to_thread(
                docstore.ingest, [path], document_id=document_id, user_id=user["id"], title=title
            )

        db.add_document(app.state.db, document_id, user["id"], title, name, result.get("pages", 0), result["chunks"])
        logger.info("ingested %s (%s pages, %s chunks)", name, result.get("pages"), result["chunks"])
        return db.get_document(app.state.db, document_id, user["id"])

    @app.get("/api/documents")
    def documents(user: dict = Depends(current_user)) -> dict:
        return {"documents": db.list_documents(app.state.db, user["id"])}

    # --- study guides ---------------------------------------------------

    @app.post("/api/guides", status_code=202)
    async def start_guide(request: GuideRequest, user: dict = Depends(current_user)) -> dict:
        document = db.get_document(app.state.db, request.document_id, user["id"])
        if not document:
            raise HTTPException(404, "No such document")

        used = db.tokens_used_today(app.state.db, user["id"])
        if used >= user["daily_token_limit"]:
            raise HTTPException(429, f"Daily token budget spent ({used:,}/{user['daily_token_limit']:,}).")

        guide_id = secrets.token_hex(8)
        db.start_guide(app.state.db, guide_id, user["id"], document["id"], document["title"])
        _channel(guide_id)
        asyncio.create_task(_build_guide(app, guide_id, document, user))
        return {"guide_id": guide_id, "stream_url": f"/api/guides/{guide_id}/stream"}

    @app.get("/api/guides")
    def guide_list(user: dict = Depends(current_user)) -> dict:
        return {"guides": db.list_guides(app.state.db, user["id"])}

    @app.get("/api/guides/{guide_id}")
    def one_guide(guide_id: str, user: dict = Depends(current_user)) -> dict:
        record = db.get_guide(app.state.db, guide_id, user["id"])
        if not record:
            raise HTTPException(404, "No such guide")
        return record

    @app.get("/api/guides/{guide_id}/stream")
    async def guide_stream(guide_id: str, request: Request, user: dict = Depends(current_user)):
        record = db.get_guide(app.state.db, guide_id, user["id"])
        if not record:
            raise HTTPException(404, "No such guide")
        return EventSourceResponse(_events(guide_id, record, request))

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


async def _events(stream_id: str, record: dict, request: Request) -> AsyncIterator[dict]:
    """Replay what has happened, then follow along. Shared by runs and guides:
    the streaming problem is identical, and two copies would drift."""
    channel = _channels.get(stream_id)
    if channel is None:
        # Older than the in-memory history: replay the stored result.
        yield {"event": "done", "data": _json(record)}
        return

    queue = channel.subscribe()
    try:
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


async def _build_guide(app: FastAPI, guide_id: str, document: dict, user: dict) -> None:
    """Run the study-guide graph off the event loop, streaming its progress.

    Same shape as _execute: the graph is synchronous, so it goes to a worker
    thread and progress crosses back through the loop.
    """
    loop = asyncio.get_running_loop()
    budget = TokenBudget(max_tokens=user["daily_token_limit"] - db.tokens_used_today(app.state.db, user["id"]))

    def emit(event: str, data) -> None:
        asyncio.run_coroutine_threadsafe(_publish(guide_id, event, data), loop)

    def run_graph() -> dict:
        final: dict = {}
        config = {
            "callbacks": [budget],
            "run_name": f"guide: {document['title'][:60]}",
            "tags": ["dossier", "guide"],
            "metadata": {"guide_id": guide_id, "user_id": user["id"], "document_id": document["id"]},
        }
        stream = app.state.learn_graph.stream(
            {"document_id": document["id"], "title": document["title"]}, stream_mode="debug", config=config
        )
        for event in stream:
            if event["type"] == "task":
                name = event["payload"]["name"]
                emit("progress", {"step": event["step"], "node": name, "label": NODE_LABELS.get(name, name)})
            elif event["type"] == "task_result":
                final.update(event["payload"]["result"])
        return final

    try:
        state = await asyncio.to_thread(run_graph)
    except Exception as exc:
        logger.exception("guide %s failed", guide_id)
        db.finish_guide(app.state.db, guide_id, status="failed", error=str(exc), tokens=budget.total_tokens)
        await _publish(guide_id, "error", {"error": f"{type(exc).__name__}: {exc}", "kind": "failed"})
        return

    db.finish_guide(app.state.db, guide_id, status="done", guide=state.get("guide", {}), tokens=budget.total_tokens)
    await _publish(guide_id, "done", db.get_guide(app.state.db, guide_id, user["id"]))


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
