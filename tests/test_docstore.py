"""Tests for document ingestion and retrieval.

Embeddings are faked with a deterministic bag-of-words vector: the point here
is the plumbing (splitting, metadata, the result shape the Researcher relies
on), not whether a real embedding model ranks well — that is an eval question.
"""

import math
from pathlib import Path

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from dossier import docstore

VOCAB = ["battery", "electrolyte", "toyota", "pasta", "sauce", "garlic"]


class FakeEmbeddings(Embeddings):
    """A unit-length word-count vector. Same words in, similar vectors out.

    Normalised on purpose: relevance scores are only meaningful — and only
    land in 0..1, which the threshold assumes — for unit vectors.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        lowered = text.lower()
        counts = [float(lowered.count(word)) for word in VOCAB] + [0.2]
        length = math.sqrt(sum(value * value for value in counts)) or 1.0
        return [value / length for value in counts]


@pytest.fixture
def store(tmp_path) -> Chroma:
    return Chroma(
        collection_name="test-docs",
        embedding_function=FakeEmbeddings(),
        persist_directory=str(tmp_path / "chroma"),
    )


# --- splitting ---------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert docstore.split_text("One short paragraph.") == ["One short paragraph."]


def test_paragraphs_are_kept_together_until_the_limit():
    text = "\n\n".join(["A" * 400, "B" * 400, "C" * 400])
    chunks = docstore.split_text(text, chunk_chars=900, overlap=0)

    assert len(chunks) == 2
    assert chunks[0].startswith("A") and "B" in chunks[0]


def test_a_paragraph_longer_than_the_limit_is_cut():
    chunks = docstore.split_text("X" * 3000, chunk_chars=1000, overlap=0)
    assert len(chunks) == 3
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_chunks_overlap_so_a_split_sentence_is_still_findable():
    text = "\n\n".join(["A" * 400, "B" * 400])
    chunks = docstore.split_text(text, chunk_chars=500, overlap=50)
    assert chunks[1].startswith("A" * 50)


# --- ingest and search -------------------------------------------------------


def test_ingest_reports_what_it_stored(tmp_path, store):
    path = tmp_path / "notes.md"
    path.write_text("Battery chemistry.\n\n" + "electrolyte " * 300)

    result = docstore.ingest([path], store=store)

    assert result["files"][0]["path"] == str(path)
    assert result["chunks"] == result["files"][0]["chunks"] > 1
    assert docstore.document_count(store) == result["chunks"]


def test_a_file_with_no_text_is_skipped_not_fatal(tmp_path, store):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n  ")
    good = tmp_path / "good.txt"
    good.write_text("Toyota announced a pilot line.")

    result = docstore.ingest([empty, good], store=store)

    assert [entry["path"] for entry in result["files"]] == [str(good)]


def test_search_returns_the_same_shape_as_web_search(tmp_path, store):
    path = tmp_path / "batteries.md"
    path.write_text("Toyota and electrolyte research.\n\nPasta sauce with garlic.")
    docstore.ingest([path], store=store)

    hits = docstore.doc_search("electrolyte", k=1, store=store, min_relevance=0)

    assert list(hits[0]) == ["title", "url", "content"]  # exactly web_search's keys
    assert hits[0]["title"] == "batteries"
    assert hits[0]["url"] == str(path)
    assert "electrolyte" in hits[0]["content"]


def test_retrieval_prefers_the_relevant_chunk(tmp_path, store):
    (tmp_path / "a.md").write_text("Toyota electrolyte battery research programme.")
    (tmp_path / "b.md").write_text("Pasta sauce with garlic and more garlic.")
    docstore.ingest([tmp_path / "a.md", tmp_path / "b.md"], store=store)

    assert docstore.doc_search("garlic pasta", k=1, store=store, min_relevance=0)[0]["title"] == "b"
    assert docstore.doc_search("battery electrolyte", k=1, store=store, min_relevance=0)[0]["title"] == "a"


def test_an_irrelevant_match_is_dropped_rather_than_returned(tmp_path, store):
    # A vector store always has a nearest neighbour. With one document
    # ingested, every query matches it — which is how a report on rent control
    # ended up citing a survey about fish.
    (tmp_path / "fish.md").write_text("Toyota electrolyte battery research programme.")
    docstore.ingest([tmp_path / "fish.md"], store=store)

    assert docstore.doc_search("pasta sauce garlic", store=store, min_relevance=0.5) == []
    assert docstore.doc_search("battery electrolyte", store=store, min_relevance=0.5) != []


def test_no_documents_means_no_client_and_no_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(docstore, "DATA_DIR", tmp_path / "does-not-exist")

    def explode():
        raise AssertionError("embeddings must not be built just to count documents")

    monkeypatch.setattr(docstore, "embeddings", explode)
    assert docstore.document_count() == 0


def test_reading_a_text_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello")
    assert docstore.read_document(Path(path)) == "hello"
