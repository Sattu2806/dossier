"""Storage: users, their API keys, and every run.

SQLAlchemy Core (not the ORM) against a URL, so the default is a local SQLite
file and production is `DOSSIER_DATABASE_URL=postgresql+psycopg://...` with no
code change. Core rather than ORM because this schema is two tables and a
handful of queries — an ORM would add indirection without removing any.
"""

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    select,
)

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "dossier.db"
DATABASE_URL = os.getenv("DOSSIER_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

# What one user may spend per day. The check happens before a run starts, so
# a user who is over budget costs nothing at all.
DAILY_TOKEN_LIMIT = int(os.getenv("DOSSIER_DAILY_TOKEN_LIMIT", "500000"))

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), unique=True, nullable=False),
    # Only the hash is stored: a leaked database must not hand over working
    # credentials. The key itself is shown once, when it is created.
    Column("api_key_hash", String(64), unique=True, nullable=False),
    Column("daily_token_limit", Integer, nullable=False, default=DAILY_TOKEN_LIMIT),
    Column("created_at", DateTime, nullable=False),
)

runs = Table(
    "runs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("topic", Text, nullable=False),
    Column("status", String(16), nullable=False),  # running | done | failed
    Column("report", Text),
    Column("error", Text),
    Column("drafts", Integer, default=0),
    Column("grounded", Integer),  # SQLite has no bool; 0/1/NULL
    Column("passed_review", Integer),
    Column("tokens", Integer, default=0),
    Column("sub_questions", JSON),
    Column("critique_scores", JSON),
    Column("created_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
)


def engine(url: str | None = None):
    url = url or DATABASE_URL
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def init(db) -> None:
    metadata.create_all(db)


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def create_user(db, email: str, *, daily_token_limit: int = DAILY_TOKEN_LIMIT) -> tuple[int, str]:
    """Return (user_id, api_key). The key is returned once and never stored."""
    api_key = f"dsr_{secrets.token_urlsafe(32)}"
    with db.begin() as connection:
        result = connection.execute(
            users.insert().values(
                email=email,
                api_key_hash=hash_key(api_key),
                daily_token_limit=daily_token_limit,
                created_at=datetime.now(UTC),
            )
        )
    return int(result.inserted_primary_key[0]), api_key


def ensure_user(db, email: str, api_key: str, *, daily_token_limit: int = DAILY_TOKEN_LIMIT) -> bool:
    """Create a user with a known key if they do not already exist.

    Free hosts (Hugging Face Spaces, Render free) give you no shell, so
    `dossier user` cannot be run after deploying. This lets the first user be
    seeded from a secret at startup instead. Idempotent: restarting a container
    must not fail, and must not rotate a working key.
    """
    if user_for_key(db, api_key):
        return False
    with db.begin() as connection:
        existing = connection.execute(select(users.c.id).where(users.c.email == email)).first()
        if existing:
            # Same person, new key: replace the hash rather than refusing to start.
            connection.execute(users.update().where(users.c.email == email).values(api_key_hash=hash_key(api_key)))
            return False
        connection.execute(
            users.insert().values(
                email=email,
                api_key_hash=hash_key(api_key),
                daily_token_limit=daily_token_limit,
                created_at=datetime.now(UTC),
            )
        )
    return True


def user_for_key(db, api_key: str) -> dict | None:
    with db.connect() as connection:
        row = connection.execute(select(users).where(users.c.api_key_hash == hash_key(api_key))).mappings().first()
    return dict(row) if row else None


def tokens_used_today(db, user_id: int) -> int:
    """Usage since UTC midnight.

    Deliberately UTC and not local time: `created_at` is stored in UTC, so a
    local-midnight boundary makes the two disagree for as many hours as you
    are offset from UTC. Found by tests failing at 01:30 IST, when local
    "today" had started but UTC was still on yesterday — every run vanished
    from the count and the daily budget silently reset.
    """
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with db.connect() as connection:
        total = connection.execute(
            select(func.coalesce(func.sum(runs.c.tokens), 0)).where(
                runs.c.user_id == user_id, runs.c.created_at >= start
            )
        ).scalar_one()
    return int(total)


def start_run(db, run_id: str, user_id: int, topic: str) -> None:
    with db.begin() as connection:
        connection.execute(
            runs.insert().values(
                id=run_id,
                user_id=user_id,
                topic=topic,
                status="running",
                created_at=datetime.now(UTC),
            )
        )


def finish_run(db, run_id: str, **values) -> None:
    values["finished_at"] = datetime.now(UTC)
    with db.begin() as connection:
        connection.execute(runs.update().where(runs.c.id == run_id).values(**values))


def get_run(db, run_id: str, user_id: int) -> dict | None:
    with db.connect() as connection:
        row = connection.execute(select(runs).where(runs.c.id == run_id, runs.c.user_id == user_id)).mappings().first()
    return _clean(row) if row else None


def list_runs(db, user_id: int, limit: int = 20) -> list[dict]:
    with db.connect() as connection:
        rows = (
            connection.execute(
                select(
                    runs.c.id,
                    runs.c.topic,
                    runs.c.status,
                    runs.c.drafts,
                    runs.c.tokens,
                    runs.c.grounded,
                    runs.c.passed_review,
                    runs.c.created_at,
                )
                .where(runs.c.user_id == user_id)
                .order_by(runs.c.created_at.desc())
                .limit(limit)
            )
            .mappings()
            .all()
        )
    return [_clean(row) for row in rows]


def _clean(row) -> dict:
    """SQLite stores booleans as 0/1 and JSON as text depending on the driver;
    normalise both so the API's shape doesn't depend on the database."""
    record = dict(row)
    for key in ("grounded", "passed_review"):
        if key in record and record[key] is not None:
            record[key] = bool(record[key])
    for key in ("sub_questions", "critique_scores"):
        if isinstance(record.get(key), str):
            record[key] = json.loads(record[key])
    for key in ("created_at", "finished_at"):
        if isinstance(record.get(key), datetime):
            record[key] = record[key].isoformat()
    return record
