"""Document search: your own PDFs and notes, alongside the web.

The point of this module is the shape of one function. `doc_search(query)`
returns exactly what `search.web_search(query)` returns — a list of
`{title, url, content}` — so the Researcher never learns there are two kinds
of source. Adding a third (an internal wiki, a ticket system) means writing
one more function with that signature.
"""

import logging
import os
import re
from functools import cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DOSSIER_DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "chroma"))
COLLECTION = "dossier-documents"
EMBEDDING_MODEL = "gemini-embedding-001"

# Chunks are what the model actually reads, so they are sized like evidence,
# not like documents: big enough to carry an argument, small enough that ten
# of them fit in a prompt. The overlap stops a sentence being cut in half.
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
DEFAULT_K = 3

# A vector store always returns its k nearest chunks, however far away they
# are: with one document ingested, every query matches it. Measured against
# the real embedding model, on-topic queries scored 0.61-0.64 and off-topic
# ones 0.32-0.41, so 0.5 separates them. Re-measure if the model changes.
MIN_RELEVANCE = float(os.getenv("DOSSIER_MIN_RELEVANCE", "0.5"))


@cache
def embeddings():
    """Lazy, like every other client here: importing must not need a key."""
    return GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)


@cache
def vector_store(embedding_function=None) -> Chroma:
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embedding_function or embeddings(),
        persist_directory=str(DATA_DIR),
    )


def split_text(text: str, *, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split on paragraph boundaries, falling back to a hard cut.

    Deliberately hand-written rather than a dependency: the rule ("keep
    paragraphs together, overlap a little") is the whole idea, and it is
    easier to reason about a bad retrieval when you can read the splitter.
    """
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= chunk_chars:
            current = f"{current}\n\n{paragraph}" if current else paragraph
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > chunk_chars:
            chunks.append(paragraph[:chunk_chars])
            paragraph = paragraph[chunk_chars - overlap :]
        current = paragraph

    if current:
        chunks.append(current)

    # Carry the tail of each chunk into the next, so a claim split across a
    # boundary is still retrievable from one side of it.
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    overlapped = [chunks[0]]
    for previous, chunk in zip(chunks, chunks[1:], strict=False):
        overlapped.append(f"{previous[-overlap:]}\n\n{chunk}")
    return overlapped


def read_document(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return path.read_text(errors="replace")


def ingest(paths: list[Path], *, store: Chroma | None = None) -> dict:
    """Read, split and embed documents. Returns what was added."""
    store = store or vector_store()
    documents: list[Document] = []
    ingested = []

    for path in paths:
        text = read_document(path)
        if not text.strip():
            logger.warning("no extractable text in %s", path)
            continue
        chunks = split_text(text)
        documents += [
            Document(
                page_content=chunk,
                metadata={"title": path.stem, "source": str(path), "chunk": index},
            )
            for index, chunk in enumerate(chunks)
        ]
        ingested.append({"path": str(path), "chunks": len(chunks)})

    if documents:
        store.add_documents(documents)
    return {"files": ingested, "chunks": sum(entry["chunks"] for entry in ingested)}


def document_count(store: Chroma | None = None) -> int:
    """How many chunks are stored. Must be cheap and must not need an API key:
    it is called on every run to decide whether to search documents at all,
    and "no documents yet" is the common case."""
    if store is None and not DATA_DIR.exists():
        return 0
    try:
        return (store or vector_store())._collection.count()
    except Exception as exc:  # a missing or unreadable store is "no documents"
        logger.warning("document store unavailable: %s: %s", type(exc).__name__, exc)
        return 0


def doc_search(
    query: str,
    *,
    k: int = DEFAULT_K,
    store: Chroma | None = None,
    min_relevance: float | None = None,
) -> list[dict]:
    """Same return shape as web_search, on purpose.

    Returns nothing rather than the nearest irrelevant chunk: evidence that
    has nothing to do with the question is worse than no evidence, because it
    fills the Writer's prompt and invites a stretched connection.
    """
    threshold = MIN_RELEVANCE if min_relevance is None else min_relevance
    hits = (store or vector_store()).similarity_search_with_relevance_scores(query, k=k)
    return [
        {
            "title": hit.metadata.get("title", "document"),
            "url": hit.metadata.get("source", ""),
            "content": hit.page_content,
        }
        for hit, score in hits
        if score >= threshold
    ]
