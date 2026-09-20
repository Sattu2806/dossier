"""Tests for sign-in with Clerk, alongside API keys.

Tokens are signed with a locally generated RSA key and verified against a fake
JWKS, so the real verification path runs — signature, expiry, required claims —
without a Clerk account or a network call. Stubbing `verify_clerk_token`
instead would test nothing: that function *is* the security boundary.
"""

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from dossier import api, auth, db, fakes
from dossier.graph import build_graph

KEY_ID = "test-key-1"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def clerk(monkeypatch, signing_key):
    """Serve a JWKS containing our public key, over HTTP on localhost.

    A file:// URL would be simpler, but PyJWKClient refuses any scheme other
    than http/https — a deliberate guard against pointing key discovery at the
    local filesystem. Serving it properly keeps the fetch in the tested path.
    """
    numbers = signing_key.public_key().public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    body = json.dumps(
        {
            "keys": [
                {"kty": "RSA", "kid": KEY_ID, "use": "sig", "alg": "RS256", "n": b64(numbers.n), "e": b64(numbers.e)}
            ]
        }
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # keep pytest output clean

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    auth._jwk_client.cache_clear()
    monkeypatch.setattr(auth, "CLERK_JWKS_URL", f"http://127.0.0.1:{server.server_port}/.well-known/jwks.json")
    yield
    auth._jwk_client.cache_clear()
    server.shutdown()


def token_for(signing_key, **claims) -> str:
    payload = {"sub": "user_abc123", "exp": int(time.time()) + 600, **claims}
    return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": KEY_ID})


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


# --- verification ------------------------------------------------------------


def test_a_valid_session_is_accepted(clerk, signing_key):
    claims = auth.verify_clerk_token(token_for(signing_key, email="satender@example.com"))
    assert claims["sub"] == "user_abc123"


def test_an_expired_session_is_rejected(clerk, signing_key):
    expired = token_for(signing_key, exp=int(time.time()) - 60)
    with pytest.raises(auth.InvalidToken):
        auth.verify_clerk_token(expired)


def test_a_token_signed_by_someone_else_is_rejected(clerk):
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"sub": "user_abc123", "exp": int(time.time()) + 600}, impostor, "RS256", headers={"kid": KEY_ID}
    )

    with pytest.raises(auth.InvalidToken):
        auth.verify_clerk_token(forged)


def test_an_unsigned_token_is_rejected(clerk):
    # The "alg: none" attack, which is why algorithms are pinned to RS256.
    unsigned = jwt.encode({"sub": "user_abc123", "exp": int(time.time()) + 600}, key="", algorithm="none")
    with pytest.raises(auth.InvalidToken):
        auth.verify_clerk_token(unsigned)


# --- configuration -----------------------------------------------------------


def test_the_jwks_url_is_derived_from_the_publishable_key(monkeypatch):
    encoded = base64.b64encode(b"cheerful-moth-42.clerk.accounts.dev$").decode()
    monkeypatch.setattr(auth, "CLERK_JWKS_URL", "")
    monkeypatch.setattr(auth, "CLERK_PUBLISHABLE_KEY", f"pk_test_{encoded}")

    assert auth.jwks_url() == "https://cheerful-moth-42.clerk.accounts.dev/.well-known/jwks.json"


def test_without_clerk_the_app_still_runs_on_api_keys(monkeypatch):
    monkeypatch.setattr(auth, "CLERK_JWKS_URL", "")
    monkeypatch.setattr(auth, "CLERK_PUBLISHABLE_KEY", "")
    assert auth.clerk_is_configured() is False


# --- through the API ---------------------------------------------------------


def test_a_first_request_creates_the_account(clerk, client, database, signing_key):
    headers = {"Authorization": f"Bearer {token_for(signing_key, email='satender@example.com')}"}

    body = client.get("/api/me", headers=headers).json()

    assert body["email"] == "satender@example.com"
    assert body["auth"] == "clerk"
    assert body["daily_token_limit"] == db.SIGNUP_TOKEN_LIMIT  # not the operator's own limit
    assert db.user_for_clerk_id(database, "user_abc123") is not None


def test_a_second_request_reuses_the_same_account(clerk, client, database, signing_key):
    headers = {"Authorization": f"Bearer {token_for(signing_key, email='satender@example.com')}"}
    client.get("/api/me", headers=headers)
    client.get("/api/me", headers=headers)

    with database.connect() as connection:
        count = connection.exec_driver_sql("SELECT COUNT(*) FROM users").scalar_one()
    assert count == 1


def test_each_account_sees_only_its_own_runs(clerk, client, signing_key):
    mine = {"Authorization": f"Bearer {token_for(signing_key, sub='user_mine', email='me@example.com')}"}
    yours = {"Authorization": f"Bearer {token_for(signing_key, sub='user_yours', email='you@example.com')}"}

    run_id = client.post("/api/research", json={"topic": "solid-state batteries"}, headers=mine).json()["run_id"]
    client.get(f"/api/runs/{run_id}/stream", headers=mine)

    assert [run["id"] for run in client.get("/api/runs", headers=mine).json()["runs"]] == [run_id]
    assert client.get("/api/runs", headers=yours).json()["runs"] == []
    assert client.get(f"/api/runs/{run_id}", headers=yours).status_code == 404


def test_a_signed_in_user_also_gets_an_api_key_for_the_cli(clerk, client, database, signing_key):
    headers = {"Authorization": f"Bearer {token_for(signing_key, email='satender@example.com')}"}
    client.get("/api/me", headers=headers)

    user = db.user_for_clerk_id(database, "user_abc123")
    assert user["api_key_hash"]  # so the CLI and MCP server work for them too


def test_api_keys_still_work(client, database):
    _, key = db.create_user(database, "machine@example.com")
    body = client.get("/api/me", headers={"Authorization": f"Bearer {key}"}).json()
    assert body["auth"] == "api_key"


def test_a_random_string_is_not_a_session(clerk, client):
    assert client.get("/api/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


# --- the operator's own budget ------------------------------------------------


def test_the_instance_wide_ceiling_stops_everyone(clerk, client, database, monkeypatch, signing_key):
    monkeypatch.setattr(db, "GLOBAL_DAILY_TOKEN_LIMIT", 1000)
    user_id, _ = db.create_user(database, "someone@example.com")
    db.start_run(database, "expensive", user_id, "a topic")
    db.finish_run(database, "expensive", tokens=5000)

    headers = {"Authorization": f"Bearer {token_for(signing_key, email='new@example.com')}"}
    response = client.post("/api/research", json={"topic": "solid-state batteries"}, headers=headers)

    assert response.status_code == 429
    assert "daily budget" in response.json()["detail"]
