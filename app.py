"""
Portable Agentic Toolkit — Chainlit UI entry point.
Run with: uv run chainlit run app.py
"""
import asyncio
import time
from pathlib import Path

import chainlit as cl
import ollama as ol

from agents.crew import build_crew
from mcp_tools.registry import MCPRegistry
from utils.logger import get_logger

log = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent
MCP_SERVERS_DIR = PROJECT_ROOT / "bin" / "mcp_servers"

# ── Lifecycle ───────────────────────────────────────────────────────────────


@cl.on_chat_start
async def on_start():
    log.info("New session started")

    model_names = _get_ollama_models()
    if not model_names:
        log.warning("Ollama unreachable or no models installed")
        await cl.Message(
            content=(
                "**Ollama is not running or has no models.**\n\n"
                "Start Ollama and pull a model:\n"
                "```\nollama pull llama3.2\n```\n"
                "Then refresh this page."
            )
        ).send()
        model_names = ["llama3.2"]
    else:
        log.info("Available models: %s", ", ".join(model_names))

    registry = MCPRegistry(MCP_SERVERS_DIR)
    await registry.discover()
    cl.user_session.set("registry", registry)
    log.info("MCP discovery complete — %d tool(s) loaded", registry.tool_count())

    settings = await cl.ChatSettings(
        [
            cl.input_widget.Select(
                id="model",
                label="LLM Model",
                values=model_names,
                initial_value=model_names[0],
            ),
            cl.input_widget.Switch(
                id="verbose",
                label="Show agent thinking",
                initial=True,
            ),
        ]
    ).send()

    selected_model = settings.get("model", model_names[0])
    cl.user_session.set("model", selected_model)
    cl.user_session.set("verbose", settings.get("verbose", True))
    log.info("Session initialised — model=%s tools=%d", selected_model, registry.tool_count())

    tool_count = registry.tool_count()
    tool_msg = f"**{tool_count} MCP tool(s) loaded**" if tool_count else (
        "_No MCP tools found — add servers to `bin/mcp_servers/` to extend capabilities._"
    )
    await cl.Message(
        content=f"Ready. {tool_msg}\n\nSelect a model above and start chatting."
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    new_model = settings.get("model")
    cl.user_session.set("model", new_model)
    cl.user_session.set("verbose", settings.get("verbose", True))
    log.info("Settings updated — model=%s verbose=%s", new_model, settings.get("verbose"))


# ── Message handler ─────────────────────────────────────────────────────────


@cl.on_message
async def on_message(message: cl.Message):
    model: str = cl.user_session.get("model") or "llama3.2"
    verbose: bool = cl.user_session.get("verbose", True)
    registry: MCPRegistry = cl.user_session.get("registry")

    log.info("Message received (model=%s, len=%d)", model, len(message.content))
    log.debug("Message content: %s", message.content[:200])

    loop = asyncio.get_event_loop()

    # ── Human-in-the-loop: synchronous bridge from agent thread → Chainlit ──
    def ask_user_sync(prompt: str, choices: list[str]) -> str:
        log.info("HITL prompt shown to user (choices=%s)", choices)
        future = asyncio.run_coroutine_threadsafe(
            _ask_user_async(prompt, choices), loop
        )
        try:
            decision = future.result(timeout=120)
            log.info("HITL decision: %s", decision)
            return decision
        except Exception as exc:
            log.warning("HITL timed out or failed (%s) — defaulting to '%s'", exc, choices[-1])
            return choices[-1]

    # ── Agent step callback: stream thinking to Chainlit Steps ──────────────
    def on_agent_step(step_name: str, content: str):
        log.debug("Agent step — %s: %s", step_name, content[:120])
        if verbose:
            asyncio.run_coroutine_threadsafe(
                _emit_step(step_name, content), loop
            )

    # ── Run crew and return response ─────────────────────────────────────────
    response_msg = cl.Message(content="")
    await response_msg.send()

    t_start = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            _run_crew_sync,
            message.content,
            model,
            registry,
            ask_user_sync,
            on_agent_step,
        )
        elapsed = time.perf_counter() - t_start
        log.info("Crew finished in %.2fs (model=%s)", elapsed, model)
        log.debug("Crew result: %s", str(result)[:200])
        response_msg.content = str(result)
        await response_msg.update()
    except Exception as exc:
        elapsed = time.perf_counter() - t_start
        log.error("Crew failed after %.2fs — %s", elapsed, exc, exc_info=True)
        response_msg.content = f"**Error:** {exc}"
        await response_msg.update()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_ollama_models() -> list[str]:
    try:
        resp = ol.list()
        return [m.model for m in (resp.models or [])]
    except Exception as exc:
        log.debug("Ollama list() failed: %s", exc)
        return []


async def _ask_user_async(prompt: str, choices: list[str]) -> str:
    actions = [cl.Action(name=c, label=c, value=c) for c in choices]
    response = await cl.AskActionMessage(content=prompt, actions=actions, timeout=120).send()
    if response:
        return response.get("value", choices[-1])
    return choices[-1]


async def _emit_step(name: str, content: str):
    async with cl.Step(name=name) as step:
        step.output = content


def _run_crew_sync(
    user_message: str,
    model: str,
    registry: MCPRegistry,
    ask_user_fn,
    on_step_fn,
) -> str:
    """Runs CrewAI synchronously inside asyncio.to_thread."""
    tools = registry.get_crewai_tools(ask_user_fn) if registry else []
    log.debug("Building crew — model=%s tools=%d", model, len(tools))
    crew = build_crew(model=model, tools=tools, on_step=on_step_fn)
    return crew.kickoff(inputs={"task": user_message})
