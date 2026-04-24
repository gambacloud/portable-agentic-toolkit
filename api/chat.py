"""
Chat logic shared between the WebSocket handler and the scheduler.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import ollama as ol

from agents.runner import build_crew, build_hierarchical_crew
from mcp_tools.installer import make_runner_installer_tool
from mcp_tools.scheduler_tools import make_scheduler_tools
from utils.logger import get_logger

log = get_logger(__name__)

_GROQ_MODELS = [
    "groq/llama-3.3-70b-versatile",
    "groq/llama3-groq-70b-8192-tool-use-preview",
    "groq/llama-3.1-8b-instant",
]


def get_ollama_models() -> list[str]:
    try:
        resp = ol.list()
        return [m.model for m in (resp.models or [])]
    except Exception as exc:
        log.debug("Ollama list() failed: %s", exc)
        return []


def get_all_models() -> list[str]:
    groq = _GROQ_MODELS if os.getenv("GROQ_API_KEY") else []
    return groq + get_ollama_models()


def make_draft_tool(send_fn: Callable[[dict], None]):
    """
    send_fn: thread-safe callable that sends a WS message dict to the client.
    In WS context this calls asyncio.run_coroutine_threadsafe under the hood.
    """
    tool_def = {
        "type": "function",
        "function": {
            "name": "display_draft_in_ui",
            "description": (
                "Displays a formatted text draft or piece of code in the UI "
                "for the user to read and copy. Use this whenever the user asks "
                "to generate a draft, document, or piece of code."
            ),
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
) -> str:
    tool_defs: list = []
    tool_map: dict = {}

    if registry:
        t_defs, t_map = registry.get_runner_tools(ask_user_fn, only_servers=active_mcps or None)
        tool_defs += t_defs
        tool_map.update(t_map)

    inst_def, inst_fn = make_runner_installer_tool(ask_user_fn)
    tool_defs.append(inst_def)
    tool_map["install_mcp_server"] = inst_fn

    sched_defs, sched_map = make_scheduler_tools(model, active_mcps or [])
    tool_defs += sched_defs
    tool_map.update(sched_map)

    draft_def, draft_fn = make_draft_tool(send_fn)
    tool_defs.append(draft_def)
    tool_map["display_draft_in_ui"] = draft_fn

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
    )
    return runner.kickoff(inputs={"task": user_message})
