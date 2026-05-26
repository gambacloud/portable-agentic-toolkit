"""ChromaDB retrieval helpers."""
from __future__ import annotations

from pathlib import Path

from utils.logger import get_logger
from utils.paths import app_dir

log = get_logger(__name__)

_CHROMA_PATH = app_dir() / "data" / "chroma"
_collection = None


def get_collection():
    global _collection
    if _collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        _collection = client.get_or_create_collection("knowledge_base")
        log.debug("ChromaDB collection loaded — %d chunks", _collection.count())
    return _collection


def search(query: str, top_k: int = 5, sources: list[str] | None = None) -> list[dict]:
    from rag.embedder import embed

    collection = get_collection()
    if collection.count() == 0:
        return []

    where = {"source": {"$in": sources}} if sources else None

    # Cap n_results to actual matching chunk count to avoid ChromaDB errors
    if where:
        matching = collection.get(where=where)
        count = len(matching["ids"])
    else:
        count = collection.count()

    if count == 0:
        return []

    query_emb = embed([query])
    results = collection.query(
        query_embeddings=query_emb,
        n_results=min(top_k, count),
        where=where,
    )
    out = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        out.append({"text": doc, "source": meta.get("source", "unknown")})
    return out


def list_sources() -> list[dict]:
    collection = get_collection()
    if collection.count() == 0:
        return []
    all_items = collection.get()
    sources: dict[str, int] = {}
    for meta in all_items["metadatas"]:
        src = meta.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
    return [{"source": s, "chunks": c} for s, c in sorted(sources.items())]


def delete_source(source: str) -> int:
    collection = get_collection()
    existing = collection.get(where={"source": source})
    if not existing["ids"]:
        return 0
    collection.delete(ids=existing["ids"])
    log.info("Deleted %d chunks for source: %s", len(existing["ids"]), source)
    return len(existing["ids"])
