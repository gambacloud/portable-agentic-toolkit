"""RAG tool factory — registers search_knowledge_base when the collection has documents."""
from __future__ import annotations

from utils.logger import get_logger

log = get_logger(__name__)


def make_rag_tool() -> tuple[dict, callable] | None:
    try:
        from rag.retriever import get_collection
        # Always re-check count so mid-session uploads are visible
        count = get_collection().count()
        if count == 0:
            log.debug("RAG collection empty — tool not registered")
            return None
        log.info("RAG tool active — %d chunks available", count)
    except Exception as exc:
        log.debug("RAG unavailable: %s", exc)
        return None

    tool_def = {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search the local knowledge base for information relevant to the query. "
                "Use this before answering questions that may be covered in uploaded documents."
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
        results = search(query, top_k=top_k)
        if not results:
            return "No relevant documents found in the knowledge base."
        parts = [f"[Source: {r['source']}]\n{r['text']}" for r in results]
        return "\n\n---\n\n".join(parts)

    return tool_def, tool_fn
