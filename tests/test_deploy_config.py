"""Deployment-shaped checks.

These are cheap guards against the failure that wastes an afternoon: the
container starts, the platform's health check hits the wrong port, and the
logs say nothing useful.
"""

from dossier import api


def test_the_platform_port_wins(monkeypatch):
    monkeypatch.setenv("PORT", "4321")
    monkeypatch.setenv("DOSSIER_PORT", "8500")
    assert api.port() == 4321


def test_falls_back_to_the_project_variable(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("DOSSIER_PORT", "8600")
    assert api.port() == 8600


def test_and_finally_to_the_default(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("DOSSIER_PORT", raising=False)
    assert api.port() == 8500


def test_health_reports_what_is_running(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from dossier import db, fakes
    from dossier.graph import build_graph

    monkeypatch.setenv("RENDER_GIT_COMMIT", "ac26977ffffffffffffffffffffffffffffffff")
    engine = db.engine(f"sqlite:///{tmp_path}/t.db")
    with TestClient(api.create_app(database=engine, graph=build_graph(**fakes.FAKE_NODES))) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["commit"] == "ac26977"  # short sha, so a deploy can be identified at a glance
    assert body["version"]


def test_health_works_without_a_host_that_sets_a_commit(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from dossier import db, fakes
    from dossier.graph import build_graph

    for name in ("RENDER_GIT_COMMIT", "RAILWAY_GIT_COMMIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT"):
        monkeypatch.delenv(name, raising=False)
    engine = db.engine(f"sqlite:///{tmp_path}/t.db")
    with TestClient(api.create_app(database=engine, graph=build_graph(**fakes.FAKE_NODES))) as client:
        assert client.get("/health").json()["commit"] is None  # unknown, not a crash
