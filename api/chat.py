"""
Chat logic shared between the WebSocket handler and the scheduler.
"""
from __future__ import annotations

import os
import re
from typing import Callable, Optional

import ollama as ol

from agents.runner import build_crew, build_hierarchical_crew
from mcp_tools.installer import make_runner_installer_tool
from mcp_tools.scheduler_tools import make_scheduler_tools
from utils.logger import get_logger

log = get_logger(__name__)

# Static fallbacks — used only if the live provider lookup below fails (no
# network, bad key, provider outage). Keeping these small and rarely touched
# is fine precisely because they're a fallback, not the primary source.
_GROQ_MODELS = [
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-8b-instant",
]

_CLAUDE_MODELS = [
    "claude/claude-sonnet-5",
    "claude/claude-opus-5",
    "claude/claude-haiku-4-5-20251001",
]

_GEMINI_MODELS = [
    # Rolling aliases (auto-track Google's current release) instead of pinned
    # dated versions — a pinned model (e.g. gemini-2.0-flash) gets retired and
    # 404s with no warning; see https://ai.google.dev/gemini-api/docs/models.
    "gemini/gemini-pro-latest",
    "gemini/gemini-flash-latest",
    "gemini/gemini-flash-lite-latest",
]

# Gemini's models.list() also returns image/speech/embedding/etc. models,
# none of which can hold a text chat — offering them just invites a
# confusing failure several seconds later.
_GEMINI_NOT_TEXT = (
    "embedding", "image", "tts", "-live", "lyria", "veo", "imagen",
    "nano-banana", "aqa", "learnlm", "robotics", "computer-use", "transcribe",
)

_VERSION = re.compile(r"(\d+(?:\.\d+)?)")


def _descending(name: str):
    """Sort key that puts later-looking version numbers first (gemini-3.6
    before gemini-3.5, without burying gemini-3.6 under gemma-4)."""
    parts = _VERSION.split(name)
    return [(-float(p), "") if _VERSION.fullmatch(p) else (0.0, p) for p in parts]


def get_ollama_models() -> list[str]:
    try:
        resp = ol.list()
        return [m.model for m in (resp.models or [])]
    except Exception as exc:
        log.debug("Ollama list() failed: %s", exc)
        return []


def get_ollama_cloud_models() -> list[str]:
    try:
        from utils.ollama_utils import ollama_cloud_client
        client = ollama_cloud_client()
        resp = client.list()
        return [f"ollama_cloud/{m.model}" for m in (resp.models or [])]
    except Exception as exc:
        log.debug("Ollama Cloud list() failed: %s", exc)
        return []


def get_claude_models() -> list[str]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return [f"claude/{m.id}" for m in client.models.list(limit=100)]
    except Exception as exc:
        log.debug("Anthropic models.list() failed — using static fallback: %s", exc)
        return _CLAUDE_MODELS


def get_gemini_models() -> list[str]:
    try:
        import httpx
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key}, timeout=5,
        )
        resp.raise_for_status()
        names = []
        for m in resp.json().get("models", []):
            name = m.get("name", "").removeprefix("models/")
            if not name or "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if any(word in name for word in _GEMINI_NOT_TEXT):
                continue
            names.append(name)
        names.sort(key=lambda n: (not n.startswith("gemini-"), _descending(n)))
        return [f"gemini/{n}" for n in names] or _GEMINI_MODELS
    except Exception as exc:
        log.debug("Gemini models.list() failed — using static fallback: %s", exc)
        return _GEMINI_MODELS


def get_groq_models() -> list[str]:
    try:
        import httpx
        resp = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"}, timeout=5,
        )
        resp.raise_for_status()
        return sorted(f"groq/{m['id']}" for m in resp.json().get("data", [])) or _GROQ_MODELS
    except Exception as exc:
        log.debug("Groq models.list() failed — using static fallback: %s", exc)
        return _GROQ_MODELS


def get_all_models() -> list[str]:
    claude = get_claude_models() if os.getenv("ANTHROPIC_API_KEY") else []
    gemini = get_gemini_models() if (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")) else []
    groq = get_groq_models() if os.getenv("GROQ_API_KEY") else []
    ollama_cloud = get_ollama_cloud_models() if os.getenv("OLLAMA_API_KEY") else []
    return claude + gemini + groq + ollama_cloud + get_ollama_models()


def make_draft_tool(send_fn: Callable[[dict], None]):
    """
    send_fn: thread-safe callable that sends a WS message dict to the client.
    In WS context this calls asyncio.run_coroutine_threadsafe under the hood.
    """
    from utils.settings import get_document_instructions

    description = (
        "Displays a formatted text draft or piece of code in the UI "
        "for the user to read and copy. Use this whenever the user asks "
        "to generate a draft, document, or piece of code."
    )
    branding = get_document_instructions()
    if branding:
        description += f" When writing the content, follow these brand/content guidelines: {branding}"

    tool_def = {
        "type": "function",
        "function": {
            "name": "display_draft_in_ui",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the draft (e.g. 'Marketing Email', 'Python Script').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text content of the draft.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language for syntax highlighting (e.g. 'python'). Empty for plain text.",
                    },
                },
                "required": ["title", "content"],
            },
        },
    }

    def tool_fn(title: str, content: str, language: str = "") -> str:
        send_fn({"type": "draft", "title": title, "content": content, "language": language or ""})
        return "Draft displayed successfully."

    return tool_def, tool_fn


def make_pdf_tool(send_fn: Callable[[dict], None]):
    """
    send_fn: thread-safe callable that sends a WS message dict to the client.
    In WS context this calls asyncio.run_coroutine_threadsafe under the hood.
    """
    from utils.settings import get_document_instructions

    description = (
        "Generates a downloadable PDF file and shows a download link in the UI. "
        "Use this when the user explicitly asks for a PDF file (not just a draft "
        "to read or copy — use display_draft_in_ui for that). "
        "Currently only supports English/Latin-script content — if the user's "
        "content is in Hebrew or another non-Latin script, tell them PDF export "
        "doesn't support it yet and offer a regular draft instead."
    )
    branding = get_document_instructions()
    if branding:
        description += f" When writing the content, follow these brand/content guidelines: {branding}"

    tool_def = {
        "type": "function",
        "function": {
            "name": "generate_pdf_document",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the document (e.g. 'Marketing Plan').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full English/Latin-script text content, paragraphs separated by blank lines.",
                    },
                },
                "required": ["title", "content"],
            },
        },
    }

    def tool_fn(title: str, content: str) -> str:
        from utils.pdf_export import generate_pdf

        try:
            file_id, filename = generate_pdf(title, content)
        except ValueError as exc:
            return str(exc)

        send_fn({"type": "file", "title": title, "url": f"/generated/{file_id}", "filename": filename})
        return f"PDF generated and shown to the user for download: {filename}"

    return tool_def, tool_fn


def run_crew_sync(
    user_message: str,
    model: str,
    registry,
    ask_user_fn: Callable,
    on_step_fn: Callable,
    send_fn: Callable[[dict], None],
    profile_id: Optional[str] = None,
    multi_agent: bool = False,
    active_mcps: Optional[list[str]] = None,
    on_token_usage: Optional[Callable[[int, int], None]] = None,
    kb_sources: Optional[list[str]] = None,
    is_privileged: bool = False,
) -> str:
    tool_defs: list = []
    tool_map: dict = {}

    if registry:
        t_defs, t_map = registry.get_runner_tools(ask_user_fn, only_servers=active_mcps or None, is_privileged=is_privileged)
        tool_defs += t_defs
        tool_map.update(t_map)

    inst_def, inst_fn = make_runner_installer_tool(ask_user_fn)
    tool_defs.append(inst_def)
    tool_map["install_mcp_server"] = inst_fn

    sched_defs, sched_map = make_scheduler_tools(model, active_mcps or [])
    tool_defs += sched_defs
    tool_map.update(sched_map)

    # Auto-inject KB context when sources are selected — don't rely on agent calling the tool
    if kb_sources:
        try:
            from rag.retriever import search
            rag_hits = search(user_message, top_k=5, sources=kb_sources)
            if rag_hits:
                rag_block = "\n\n---\n\n".join(
                    f"[Source: {r['source']}]\n{r['text']}" for r in rag_hits
                )
                user_message = (
                    f"[Knowledge Base — selected sources: {', '.join(kb_sources)}]\n"
                    f"{rag_block}\n\n---\n\n{user_message}"
                )
                log.debug("Injected %d KB chunks from %s", len(rag_hits), kb_sources)
        except Exception as exc:
            log.debug("KB auto-inject failed: %s", exc)

    try:
        from rag.tool import make_rag_tool
        rag = make_rag_tool(kb_sources=kb_sources)
        if rag:
            rag_def, rag_fn = rag
            tool_defs.append(rag_def)
            tool_map["search_knowledge_base"] = rag_fn
    except Exception as exc:
        log.debug("RAG tool skipped: %s", exc)

    draft_def, draft_fn = make_draft_tool(send_fn)
    tool_defs.append(draft_def)
    tool_map["display_draft_in_ui"] = draft_fn

    pdf_def, pdf_fn = make_pdf_tool(send_fn)
    tool_defs.append(pdf_def)
    tool_map["generate_pdf_document"] = pdf_fn

    log.debug(
        "Building runner — model=%s tools=%d profile=%s multi=%s",
        model, len(tool_defs), profile_id, multi_agent,
    )
    builder = build_hierarchical_crew if multi_agent else build_crew
    runner = builder(
        model=model,
        tool_defs=tool_defs,
        tool_map=tool_map,
        on_step=on_step_fn,
        profile_id=profile_id,
        on_token_usage=on_token_usage,
    )
    return runner.kickoff(inputs={"task": user_message})
