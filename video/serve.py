"""The API, pointed at a throwaway copy of your database, for recording.

Why a copy: the recording needs a known API key, and keys are stored hashed,
one per user — so seeding one means replacing yours. Doing it on a copy leaves
your real history and your real key alone, and the video's own run never lands
in your history.

    uv run python video/serve.py              # the real graph: real searches, real quota
    VIDEO_FAKE=1 uv run python video/serve.py # slow fakes: rehearse the choreography for free

Each start copies the database afresh, so every take begins from the same state.
"""

import os
import random
import shutil
import sqlite3
import time
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from dossier import api, db, fakes
from dossier.graph import build_graph

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "video" / ".work"
PORT = int(os.getenv("VIDEO_API_PORT", "8511"))

# Local-only, and only ever written into the copy.
KEY = "dsr_video_local_recording_only"


def slow(node, seconds):
    """A fake that takes about as long as the real thing, so the progress
    timeline moves at the pace it will on camera."""

    def run(state):
        time.sleep(seconds() if callable(seconds) else seconds)
        return node(state)

    return run


def rehearsal_graph():
    return build_graph(
        **{
            **fakes.FAKE_NODES,
            "planner": slow(fakes.planner, 2.0),
            "researcher": slow(fakes.researcher, lambda: random.uniform(1.5, 3.5)),
            "writer": slow(fakes.writer, 3.5),
            "fact_checker": slow(fakes.fact_checker, 1.5),
            "critic": slow(fakes.critic, 1.5),
        }
    )


def main():
    # The CLI loads .env for `dossier serve`; this bypasses the CLI, so it
    # has to do the same or the first model call fails for want of a key.
    load_dotenv(ROOT / ".env")
    WORK.mkdir(parents=True, exist_ok=True)
    copy = WORK / "video.db"
    shutil.copyfile(ROOT / "data" / "dossier.db", copy)

    # A book guided twice shows up twice in the library. Keep the newest one —
    # in the copy only — so the video shows the guide from the current code.
    with sqlite3.connect(copy) as connection:
        connection.execute(
            """delete from guides where created_at < (
                   select max(created_at) from guides newer where newer.document_id = guides.document_id)"""
        )

    os.environ["DOSSIER_BOOTSTRAP_EMAIL"] = "demo@dossier.local"
    os.environ["DOSSIER_BOOTSTRAP_KEY"] = KEY

    api.configure_logging()
    graph = rehearsal_graph() if os.getenv("VIDEO_FAKE") else None
    app = api.create_app(database=db.engine(f"sqlite:///{copy}"), graph=graph)
    uvicorn.run(app, host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
