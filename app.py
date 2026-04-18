"""
Portable Agentic Toolkit — Chainlit UI entry point.
Run with: uv run chainlit run app.py
"""
import asyncio
import os
import time
from pathlib import Path

import chainlit as cl
import ollama as ol

import db.queries as q
from agents.crew import build_crew
from api.server import api as rest_api
from db.database import init_db
from mcp_tools.registry import MCPRegistry
from utils.logger import get_logger

log = get_logger(__name__)

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")
PROJECT_ROOT = Path(__file__).parent
MCP_SERVERS_DIR = PROJECT_ROOT / "bin" / "mcp_servers"

# ── Initialise DB and mount REST API on Chainlit's server ────────────────────

init_db()
log.info("%s starting — DB initialised", BOT_NAME)

from chainlit.server import app as cl_server  # noqa: E402 — must come after cl import
cl_server.mount("/api", rest_api)
log.info("REST API mounted at /api  (docs: /api/docs)")


# ── Header-based identity ────────────────────────────────────────────────────


@cl.header_auth_callback
def header_auth(headers: dict) -> cl.User | None:
    user_id = headers.get("x-user-id") or headers.get("X-User-ID", "anonymous")
    return cl.User(identifier=user_id)


# ── Lifecycle ────────────────────────────────────────────────────────────────


@cl.on_chat_start
async def on_start():
    cl_user = cl.user_session.get("user")
    user_id = cl_user.identifier if cl_user else "anonymous"
    q.upsert_user(user_id)
    log.info("Session started — user=%s bot=%s", user_id, BOT_NAME)

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
    cl.user_session.set("user_id", user_id)

    # Create a conversation record for this session
    conv_id = q.create_conversation(user_id, selected_model)
    cl.user_session.set("conv_id", conv_id)
    log.info("Conversation created — id=%s model=%s", conv_id, selected_model)

    tool_count = registry.tool_count()
    tool_msg = (
        f"**{tool_count} MCP tool(s) loaded**"
        if tool_count
        else "_No MCP tools — add servers to `bin/mcp_servers/`._"
    )
    await cl.Message(
        content=f"**{BOT_NAME}** ready. {tool_msg}\n\nSelect a model above and start chatting."
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    new_model = settings.get("model")
    cl.user_session.set("model", new_model)
    cl.user_session.set("verbose", settings.get("verbose", True))
    log.info("Settings updated — model=%s verbose=%s", new_model, settings.get("verbose"))


# ── Message handler ──────────────────────────────────────────────────────────


@cl.on_message
async def on_message(message: cl.Message):
    model: str = cl.user_session.get("model") or "llama3.2"
    verbose: bool = cl.user_session.get("verbose", True)
    registry: MCPRegistry = cl.user_session.get("registry")
    user_id: str = cl.user_session.get("user_id", "anonymous")
    conv_id: str = cl.user_session.get("conv_id")

    log.info("Message received — user=%s model=%s len=%d", user_id, model, len(message.content))
    log.debug("Message content: %s", message.content[:200])

    # Persist user message
    if conv_id:
        q.append_message(conv_id, "user", message.content)

    loop = asyncio.get_event_loop()

    def ask_user_sync(prompt: str, choices: list[str]) -> str:
        log.info("HITL prompt shown — choices=%s", choices)
        future = asyncio.run_coroutine_threadsafe(
            _ask_user_async(prompt, choices), loop
        )
        try:
            decision = future.result(timeout=120)
            log.info("HITL decision: %s", decision)
            return decision
        except Exception as exc:
            log.warning("HITL timed out (%s) — defaulting to '%s'", exc, choices[-1])
            return choices[-1]

    def on_agent_step(step_name: str, content: str):
        log.debug("Agent step — %s: %s", step_name, content[:120])
        if verbose:
            asyncio.run_coroutine_threadsafe(_emit_step(step_name, content), loop)

    response_msg = cl.Message(content="")
    await response_msg.send()

    t_start = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            _run_crew_sync, message.content, model, registry, ask_user_sync, on_agent_step
        )
        elapsed = time.perf_counter() - t_start
        log.info("Crew finished in %.2fs", elapsed)

        # Persist assistant response
        if conv_id:
            q.append_message(conv_id, "assistant", str(result))

        response_msg.content = str(result)
        await response_msg.update()
    except Exception as exc:
        elapsed = time.perf_counter() - t_start
        log.error("Crew failed after %.2fs — %s", elapsed, exc, exc_info=True)
        response_msg.content = f"**Error:** {exc}"
        await response_msg.update()


# ── Helpers ──────────────────────────────────────────────────────────────────


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
    return response.get("value", choices[-1]) if response else choices[-1]


async def _emit_step(name: str, content: str):
    async with cl.Step(name=name) as step:
        step.output = content


def _run_crew_sync(user_message, model, registry, ask_user_fn, on_step_fn) -> str:
    tools = registry.get_crewai_tools(ask_user_fn) if registry else []
    log.debug("Building crew — model=%s tools=%d", model, len(tools))
    crew = build_crew(model=model, tools=tools, on_step=on_step_fn)
    return crew.kickoff(inputs={"task": user_message})
