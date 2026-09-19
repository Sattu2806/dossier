"""Tests for the HTTP API — auth, ownership, budgets and streaming.

Everything runs against a temporary SQLite file and a graph of fakes, so the
suite still needs no API key and costs nothing.
"""

import json

import pytest
from fastapi.testclient import TestClient

from dossier import api, db, fakes
from dossier.graph import build_graph


@pytest.fixture
def database(tmp_path):
    engine = db.engine(f"sqlite:///{tmp_path}/test.db")
    db.init(engine)
    return engine


@pytest.fixture
def client(database):
    app = api.create_app(database=database, graph=build_graph(**fakes.FAKE_NODES))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(database):
    _, key = db.create_user(database, "satender@example.com")
    return {"Authorization": f"Bearer {key}"}


# --- auth ---------------------------------------------------------------------


def test_health_needs_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "nonsense"}])
def test_protected_endpoints_reject_bad_credentials(client, headers):
    assert client.get("/api/me", headers=headers).status_code == 401


def test_the_api_key_itself_is_never_stored(database):
    _, key = db.create_user(database, "a@example.com")
    with database.connect() as connection:
        stored = connection.exec_driver_sql("SELECT api_key_hash FROM users").scalar_one()

    assert key not in stored
    assert stored == db.hash_key(key)


def test_me_reports_the_budget(client, auth):
    body = client.get("/api/me", headers=auth).json()
    assert body["email"] == "satender@example.com"
    assert body["tokens_remaining"] == body["daily_token_limit"] == db.DAILY_TOKEN_LIMIT


# --- running ------------------------------------------------------------------


def start(client, auth, topic="solid-state batteries"):
    response = client.post("/api/research", json={"topic": topic}, headers=auth)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_a_run_streams_progress_then_the_report(client, auth):
    run_id = start(client, auth)

    events = []
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=auth) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            elif line.startswith("data:") and events and events[-1] == "done":
                payload = json.loads(line.split(":", 1)[1])
                break

    assert events[0] == "progress"
    assert events[-1] == "done"
    assert payload["status"] == "done"
    assert payload["report"].startswith("# Report: solid-state batteries")
    assert payload["drafts"] == 2


def test_progress_events_carry_readable_labels(client, auth):
    run_id = start(client, auth)
    labels = []
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=auth) as response:
        for line in response.iter_lines():
            if line.startswith("data:") and '"label"' in line:
                labels.append(json.loads(line.split(":", 1)[1])["label"])
            if line.strip() == "event: done":
                break

    assert "Planning sub-questions" in labels
    assert "Fact-checking against sources" in labels


def test_an_invalid_topic_fails_the_run_with_a_reason(client, auth):
    run_id = start(client, auth, topic="asdkjhqwe zxcvbnm qqq")

    kinds = []
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=auth) as response:
        for line in response.iter_lines():
            if line.startswith("data:") and '"kind"' in line:
                kinds.append(json.loads(line.split(":", 1)[1])["kind"])
                break

    assert kinds == ["invalid_topic"]
    assert client.get(f"/api/runs/{run_id}", headers=auth).json()["status"] == "failed"


def test_history_is_scoped_to_the_owner(client, database, auth):
    run_id = start(client, auth)
    client.get(f"/api/runs/{run_id}/stream", headers=auth)  # let it finish

    _, other_key = db.create_user(database, "someone-else@example.com")
    other = {"Authorization": f"Bearer {other_key}"}

    assert [run["id"] for run in client.get("/api/runs", headers=auth).json()["runs"]] == [run_id]
    assert client.get("/api/runs", headers=other).json()["runs"] == []
    assert client.get(f"/api/runs/{run_id}", headers=other).status_code == 404


def test_a_finished_run_can_still_be_streamed(client, auth):
    run_id = start(client, auth)
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=auth) as first:
        list(first.iter_lines())

    # Reconnecting after the queue is gone replays the result instead of hanging.
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=auth) as second:
        body = "\n".join(second.iter_lines())

    assert "event: done" in body


# --- budget -------------------------------------------------------------------


def test_a_user_over_budget_is_refused_before_anything_runs(client, database, auth):
    run_id = start(client, auth)
    client.get(f"/api/runs/{run_id}/stream", headers=auth)
    db.finish_run(database, run_id, tokens=db.DAILY_TOKEN_LIMIT + 1)

    response = client.post("/api/research", json={"topic": "anything at all"}, headers=auth)

    assert response.status_code == 429
    assert "budget" in response.json()["detail"].lower()
    assert len(client.get("/api/runs", headers=auth).json()["runs"]) == 1  # nothing new started


def test_usage_is_recorded_against_the_user(client, database, auth):
    run_id = start(client, auth)
    client.get(f"/api/runs/{run_id}/stream", headers=auth)
    db.finish_run(database, run_id, tokens=1234)

    assert client.get("/api/me", headers=auth).json()["tokens_used_today"] == 1234
