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


def read_pages(path: Path) -> list[str]:
    """Text per page, because a study guide has to be able to say where a
    claim came from, and "page 148" is the only reference a reader can act on."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return [page.extract_text() or "" for page in PdfReader(str(path)).pages]
    return path.read_text(errors="replace").split("\f")  # form feed, if any


def read_document(path: Path) -> str:
    return "\n\n".join(read_pages(path))


def chunk_pages(pages: list[str]) -> list[tuple[str, int]]:
    """Chunks paired with the page they started on."""
    chunked: list[tuple[str, int]] = []
    for number, text in enumerate(pages, start=1):
        if not text.strip():
            continue
        chunked += [(chunk, number) for chunk in split_text(text)]
    return chunked


def ingest(
    paths: list[Path],
    *,
    store: Chroma | None = None,
    document_id: str | None = None,
    user_id: int | None = None,
    title: str | None = None,
) -> dict:
    """Read, split and embed documents. Returns what was added.

    `document_id` and `user_id` end up on every chunk so retrieval can be
    scoped to one book and one person. Without them a study guide for your
    book would happily quote somebody else's.
    """
    store = store or vector_store()
    documents: list[Document] = []
    ingested = []

    for path in paths:
        pages = read_pages(path)
        chunks = chunk_pages(pages)
        if not chunks:
            logger.warning("no extractable text in %s", path)
            continue

        documents += [
            Document(
                page_content=chunk,
                metadata={
                    "title": title or path.stem,
                    "source": str(path),
                    "chunk": index,
                    "page": page,
                    # Chroma rejects None in metadata, so absent means "shared".
                    **({"document_id": document_id} if document_id else {}),
                    **({"user_id": user_id} if user_id is not None else {}),
                },
            )
            for index, (chunk, page) in enumerate(chunks)
        ]
        ingested.append({"path": str(path), "chunks": len(chunks), "pages": len(pages)})

    if documents:
        store.add_documents(documents)
    return {
        "files": ingested,
        "chunks": sum(entry["chunks"] for entry in ingested),
        "pages": sum(entry["pages"] for entry in ingested),
    }


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


def scoped_search(
    query: str,
    *,
    document_id: str,
    k: int = 6,
    store: Chroma | None = None,
    min_relevance: float | None = None,
) -> list[dict]:
    """Search inside ONE document. Used by the study-guide pipeline, where
    every lesson must come from the book in front of you."""
    threshold = MIN_RELEVANCE if min_relevance is None else min_relevance
    hits = (store or vector_store()).similarity_search_with_relevance_scores(
        query, k=k, filter={"document_id": document_id}
    )
    return [
        {
            "title": hit.metadata.get("title", "document"),
            "page": hit.metadata.get("page"),
            "chunk": hit.metadata.get("chunk"),
            "content": hit.page_content,
            "score": round(score, 3),
        }
        for hit, score in hits
        if score >= threshold
    ]


def document_overview(document_id: str, *, limit: int = 40, store: Chroma | None = None) -> list[dict]:
    """The start of the book, in order.

    An outline needs the shape of the whole thing, and similarity search
    cannot give you that — "what is this book about" matches nothing in
    particular. So this reads the opening chunks directly, where a preface
    and a table of contents live.
    """
    try:
        found = (store or vector_store()).get(where={"document_id": document_id}, limit=limit * 3)
    except Exception as exc:
        logger.warning("could not read document %s: %s", document_id, exc)
        return []

    pieces = [
        {"chunk": metadata.get("chunk", 0), "page": metadata.get("page"), "content": text}
        for text, metadata in zip(found.get("documents", []), found.get("metadatas", []), strict=False)
    ]
    return sorted(pieces, key=lambda piece: piece["chunk"])[:limit]


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
