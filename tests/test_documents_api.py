"""Tests for uploading a book and turning it into a study guide.

Uploads are the first place a stranger's file meets this system, so the
refusals matter as much as the happy path: a scanned PDF, an oversized file,
somebody else's document.
"""

import json

import pytest
from fastapi.testclient import TestClient

from dossier import api, db, docstore, fakes
from dossier.graph import build_graph
from dossier.learn import build_learn_graph


@pytest.fixture
def database(tmp_path):
    engine = db.engine(f"sqlite:///{tmp_path}/test.db")
    db.init(engine)
    return engine


@pytest.fixture
def ingested(monkeypatch):
    """Record what would have been embedded, without embedding anything."""
    calls = []

    def fake_ingest(paths, *, document_id=None, user_id=None, title=None, **kwargs):
        calls.append({"paths": [str(path) for path in paths], "document_id": document_id, "user_id": user_id})
        return {"files": [], "chunks": 12, "pages": 3}

    monkeypatch.setattr(docstore, "ingest", fake_ingest)
    monkeypatch.setattr(docstore, "read_pages", lambda path: ["Chapter one text", "More text", "Even more"])
    return calls


@pytest.fixture
def client(database):
    app = api.create_app(
        database=database,
        graph=build_graph(**fakes.FAKE_NODES),
        learn_graph=build_learn_graph(outline=fake_outline, lesson=fake_lesson),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(database):
    _, key = db.create_user(database, "reader@example.com")
    return {"Authorization": f"Bearer {key}"}


def fake_outline(state):
    return {
        "title": "A Book",
        "outline": [{"number": n, "title": f"Lesson {n}", "covers": "", "query": "q"} for n in (1, 2)],
    }


def fake_lesson(task):
    return {
        "lessons": [
            {
                **task["lesson"],
                "status": "ok",
                "eli5": "Like waiting your turn.",
                "diagram": "flowchart TD\n A-->B",
                "key_terms": [{"term": "Queue", "plain": "A line."}],
                "questions": [{"question": "Why?", "answer": "Because."}],
            }
        ]
    }


def upload(client, auth, name="book.pdf", contents=b"%PDF-1.4 fake"):
    return client.post("/api/documents", files={"file": (name, contents, "application/pdf")}, headers=auth)


# --- uploading ----------------------------------------------------------------


def test_a_pdf_becomes_a_searchable_document(client, auth, ingested):
    response = upload(client, auth)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "book"  # from the filename, tidied
    assert body["pages"] == 3 and body["chunks"] == 12
    # Chunks are tagged with both ids, which is what scopes retrieval later.
    assert ingested[0]["document_id"] == body["id"]
    assert ingested[0]["user_id"] is not None


def test_uploads_need_auth(client, ingested):
    response = client.post("/api/documents", files={"file": ("b.pdf", b"x", "application/pdf")})
    assert response.status_code == 401


@pytest.mark.parametrize("name", ["notes.docx", "photo.png", "archive.zip"])
def test_unsupported_types_are_refused(client, auth, ingested, name):
    response = upload(client, auth, name=name)
    assert response.status_code == 415


def test_an_empty_file_is_refused(client, auth, ingested):
    assert upload(client, auth, contents=b"").status_code == 400


def test_an_oversized_file_is_refused_with_its_size(client, auth, ingested, monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 1000)
    response = upload(client, auth, contents=b"x" * 2000)

    assert response.status_code == 413
    assert "MB" in response.json()["detail"]


def test_too_many_pages_is_refused(client, auth, ingested, monkeypatch):
    monkeypatch.setattr(api, "MAX_PAGES", 2)
    response = upload(client, auth)

    assert response.status_code == 413
    assert "pages" in response.json()["detail"]


def test_a_scanned_pdf_is_refused_with_a_reason_someone_can_act_on(client, auth, monkeypatch):
    # A scan extracts as empty strings, not as an error — the most common
    # "why doesn't this work" upload there is.
    monkeypatch.setattr(docstore, "read_pages", lambda path: ["", "   ", ""])
    response = upload(client, auth)

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


def test_a_document_quota_applies(client, auth, ingested, monkeypatch):
    monkeypatch.setattr(api, "MAX_DOCUMENTS_PER_USER", 1)
    assert upload(client, auth).status_code == 201
    assert upload(client, auth).status_code == 429


def test_documents_are_listed_per_owner(client, database, auth, ingested):
    upload(client, auth)
    _, other_key = db.create_user(database, "someone-else@example.com")

    assert len(client.get("/api/documents", headers=auth).json()["documents"]) == 1
    assert client.get("/api/documents", headers={"Authorization": f"Bearer {other_key}"}).json()["documents"] == []


# --- study guides -------------------------------------------------------------


def start_guide(client, auth, document_id):
    return client.post("/api/guides", json={"document_id": document_id}, headers=auth)


def test_a_guide_streams_progress_then_the_lessons(client, auth, ingested):
    document_id = upload(client, auth).json()["id"]
    guide_id = start_guide(client, auth, document_id).json()["guide_id"]

    events, payload = [], None
    with client.stream("GET", f"/api/guides/{guide_id}/stream", headers=auth) as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            elif line.startswith("data:") and events and events[-1] == "done":
                payload = json.loads(line.split(":", 1)[1])
                break

    assert events[0] == "progress"
    assert payload["status"] == "done"
    assert payload["guide"]["stats"]["lessons"] == 2
    assert payload["guide"]["glossary"][0]["term"] == "queue"


def test_a_guide_cannot_be_built_from_someone_elses_document(client, database, auth, ingested):
    document_id = upload(client, auth).json()["id"]
    _, other_key = db.create_user(database, "someone-else@example.com")

    response = start_guide(client, {"Authorization": f"Bearer {other_key}"}, document_id)
    assert response.status_code == 404


def test_a_missing_document_is_a_404(client, auth):
    assert start_guide(client, auth, "does-not-exist").status_code == 404


def test_guides_are_listed_and_readable(client, auth, ingested):
    document_id = upload(client, auth).json()["id"]
    guide_id = start_guide(client, auth, document_id).json()["guide_id"]
    client.get(f"/api/guides/{guide_id}/stream", headers=auth)  # let it finish

    listed = client.get("/api/guides", headers=auth).json()["guides"]
    assert [guide["id"] for guide in listed] == [guide_id]
    assert client.get(f"/api/guides/{guide_id}", headers=auth).json()["guide"]["stats"]["written"] == 2


def test_a_user_over_budget_cannot_start_a_guide(client, database, auth, ingested):
    document_id = upload(client, auth).json()["id"]
    user = db.user_for_key(database, auth["Authorization"].removeprefix("Bearer "))
    db.start_run(database, "spent", user["id"], "something")
    db.finish_run(database, "spent", tokens=db.DAILY_TOKEN_LIMIT + 1)

    assert start_guide(client, auth, document_id).status_code == 429
