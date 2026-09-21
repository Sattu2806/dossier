"""Where a paused run is kept.

A graph without a checkpointer has no memory between steps: it runs to the
end or it dies, and a crash at the Writer throws away every search you paid
for. A checkpointer writes the state after each step, which buys two
different things that are easy to confuse:

  * **resume after a crash** — needs storage that outlives the process
  * **pause for a human** — needs only storage that outlives the request

`interrupt()` requires one either way, which is why this module exists at all.

The backend is chosen by the same URL `db.py` already switches on, so there is
one database setting rather than two. The durable savers are optional imports:
missing packages degrade to memory with a warning rather than refusing to
start, because a missing checkpoint backend should not take the API down.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)

# Savers that own a connection pool need their context manager entered and
# kept open for the life of the process. One stack, closed at shutdown.
_stack = ExitStack()


def checkpointer(url: str | None = None) -> BaseCheckpointSaver:
    """A saver for this database URL, or an in-memory one.

    In-memory is the right default for tests, the CLI and `--offline`: a
    single process, one run, nothing to resume into.
    """
    if not url:
        return InMemorySaver()

    try:
        if url.startswith("sqlite"):
            return _sqlite(url)
        if "postgres" in url:
            return _postgres(url)
    except ImportError as exc:
        logger.warning("no durable checkpointer (%s); paused runs will not survive a restart", exc)
        return InMemorySaver()

    logger.warning("unrecognised checkpoint URL %r; using memory", url.split("://")[0])
    return InMemorySaver()


def _sqlite(url: str) -> BaseCheckpointSaver:
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    path = url.split("///", 1)[-1] if "///" in url else ":memory:"
    # check_same_thread=False because the API runs the graph on a worker
    # thread while the request that started it has already returned.
    saver = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    saver.setup()
    return saver


def _postgres(url: str) -> BaseCheckpointSaver:
    from langgraph.checkpoint.postgres import PostgresSaver

    # The saver speaks psycopg directly, so it wants a plain libpq URL — not
    # the SQLAlchemy "postgresql+psycopg://" form db.py normalises to.
    plain = url.replace("postgresql+psycopg://", "postgresql://").replace("postgres://", "postgresql://")
    saver = _stack.enter_context(PostgresSaver.from_conn_string(plain))
    saver.setup()
    return saver


def close() -> None:
    """Release any pooled connections. Called from the API's shutdown hook."""
    _stack.close()
