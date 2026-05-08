"""OpenAI-compatible embedding wrapper (works with Ollama, OpenAI, or any /v1/embeddings endpoint)."""
from __future__ import annotations

import os

from utils.logger import get_logger

log = get_logger(__name__)

_EMBED_BASE = os.getenv("EMBEDDING_API_BASE", "http://localhost:11434/v1")
_EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
_EMBED_KEY = os.getenv("EMBEDDING_API_KEY", "ollama")

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=_EMBED_BASE, api_key=_EMBED_KEY)
    return _client


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    log.debug("Embedding %d text(s) via %s model=%s", len(texts), _EMBED_BASE, _EMBED_MODEL)
    resp = _get_client().embeddings.create(model=_EMBED_MODEL, input=texts)
    return [e.embedding for e in resp.data]
