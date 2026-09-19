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
