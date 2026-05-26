"""RAG tool factory — registers search_knowledge_base when sources are selected."""
from __future__ import annotations

from utils.logger import get_logger

log = get_logger(__name__)


def make_rag_tool(kb_sources: list[str] | None = None) -> tuple[dict, callable] | None:
    # Empty list = user explicitly selected nothing — don't register
    if kb_sources is not None and len(kb_sources) == 0:
        log.debug("No KB sources selected — RAG tool not registered")
        return None

    try:
        from rag.retriever import get_collection
        count = get_collection().count()
        if count == 0:
            log.debug("RAG collection empty — tool not registered")
            return None
        log.info("RAG tool active — %d chunks, sources=%s", count, kb_sources)
    except Exception as exc:
        log.debug("RAG unavailable: %s", exc)
        return None

    source_hint = (
        f" Restrict search to these documents: {', '.join(kb_sources)}."
        if kb_sources else ""
    )

    tool_def = {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search the local knowledge base for information relevant to the query. "
                "Use this before answering questions that may be covered in uploaded documents."
                + source_hint
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    }

    def tool_fn(query: str, top_k: int = 5) -> str:
        from rag.retriever import search
        results = search(query, top_k=top_k, sources=kb_sources)
        if not results:
            return "No relevant documents found in the knowledge base."
        parts = [f"[Source: {r['source']}]\n{r['text']}" for r in results]
        return "\n\n---\n\n".join(parts)

    return tool_def, tool_fn
