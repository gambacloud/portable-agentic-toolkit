"""
Portable Agentic Toolkit — Chainlit UI entry point.
Run with: uv run chainlit run app.py
"""
import asyncio
import os
import secrets
import threading
import time
from pathlib import Path

# Auto-generate CHAINLIT_AUTH_SECRET if missing (needed for header_auth_callback)
if not os.getenv("CHAINLIT_AUTH_SECRET"):
    _secret = secrets.token_hex(32)
    os.environ["CHAINLIT_AUTH_SECRET"] = _secret
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        _env_content = _env_path.read_text(encoding="utf-8")
        if "CHAINLIT_AUTH_SECRET" not in _env_content:
            with open(_env_path, "a", encoding="utf-8") as _f:
                _f.write(f"\nCHAINLIT_AUTH_SECRET={_secret}\n")

import chainlit as cl
import ollama as ol
import uvicorn

import db.queries as q
from agents.runner import build_crew, build_hierarchical_crew
from api.server import api as rest_api
from db.chainlit_data import SQLiteDataLayer
from db.database import init_db
from mcp_tools.installer import make_runner_installer_tool
from mcp_tools.registry import MCPRegistry
from utils.logger import get_logger

log = get_logger(__name__)

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")
APP_MODE = os.getenv("APP_MODE", "SINGLE").upper()
API_PORT = int(os.getenv("API_PORT", "8002"))
PROJECT_ROOT = Path(__file__).parent
MCP_SERVERS_DIR = PROJECT_ROOT / "bin" / "mcp_servers"

# ── Initialise DB and start REST API on its own port ─────────────────────────

init_db()
log.info("%s starting — DB initialised  mode=%s", BOT_NAME, APP_MODE)

def _run_api():
    uvicorn.run(rest_api, host="localhost", port=API_PORT, log_level="warning")

threading.Thread(target=_run_api, daemon=True, name="api-server").start()
log.info("REST API started — http://localhost:%d  (docs: http://localhost:%d/docs)", API_PORT, API_PORT)

# ── Register Chainlit data layer (conversation history sidebar) ───────────────

if SQLiteDataLayer is not None:
    try:
        import chainlit.data as cl_data
        cl_data.data_layer = SQLiteDataLayer()
        log.info("Chainlit data layer registered — history sidebar enabled")
    except Exception as _e:
        log.warning("Could not register data layer: %s", _e)

# ── Write public assets and patch Chainlit config ────────────────────────────

def _setup_ui_assets():
    public_dir = PROJECT_ROOT / "public"
    public_dir.mkdir(exist_ok=True)
    (public_dir / "config.js").write_text(
        f"window.__PAT_API_PORT__ = {API_PORT};\n", encoding="utf-8"
    )

    config_toml = PROJECT_ROOT / ".chainlit" / "config.toml"
    if not config_toml.exists():
        return  # Chainlit hasn't generated it yet; will patch on next run

    import re
    content = config_toml.read_text(encoding="utf-8")
    original = content

    for key, val in [
        ("custom_css", '"/public/sidebar.css"'),
        ("custom_js", '"/public/sidebar.js"'),
        ("default_sidebar_state", '"open"'),
    ]:
        if re.search(rf'^{key}\s*=', content, re.MULTILINE):
            continue  # already set (uncommented)
        # Replace commented line if present, else append under [UI]
        commented = re.sub(
            rf'^#\s*{key}\s*=.*$', f'{key} = {val}', content, flags=re.MULTILINE
        )
        if commented != content:
            content = commented
        else:
            content = re.sub(r'(\[UI\])', rf'\1\n{key} = {val}', content)

    if content != original:
        config_toml.write_text(content, encoding="utf-8")
        log.info("Chainlit config patched with sidebar assets — restart to activate")

_setup_ui_assets()


# ── Header-based identity ────────────────────────────────────────────────────


@cl.header_auth_callback
def header_auth(headers: dict) -> cl.User | None:
    if APP_MODE == "MULTI":
        email = (headers.get("x-user-email") or headers.get("X-User-Email", "")).strip()
        if email:
            log.debug("MULTI auth — email=%s", email)
            return cl.User(identifier=email, metadata={"is_guest": False})
        log.debug("MULTI auth — no email header, guest session")
        return cl.User(identifier="guest", metadata={"is_guest": True})
    # SINGLE mode — fixed local identity, optional X-User-ID override
    user_id = (headers.get("x-user-id") or headers.get("X-User-ID", "local")).strip()
    return cl.User(identifier=user_id, metadata={"is_guest": False})


# ── Lifecycle ────────────────────────────────────────────────────────────────


@cl.on_chat_start
async def on_start():
    cl_user = cl.user_session.get("user")
    is_guest = (cl_user.metadata or {}).get("is_guest", False) if cl_user else False
    user_id = cl_user.identifier if cl_user else "guest"
    cl.user_session.set("persist", not is_guest)
    log.info("Session started — user=%s mode=%s guest=%s", user_id, APP_MODE, is_guest)

    if is_guest:
        await cl.Message(
            content=(
                "**Guest Mode** — History and save features are disabled.\n\n"
                "Ask your administrator to pass an `X-User-Email` header to enable persistence."
            ),
            author="System",
        ).send()
    else:
        q.upsert_user(user_id)

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

    profiles = q.list_profiles()
    profile_names = ["(none)"] + [p["name"] for p in profiles]
    profile_id_map: dict[str, str | None] = {"(none)": None}
    profile_id_map.update({p["name"]: p["id"] for p in profiles})
    cl.user_session.set("profile_id_map", profile_id_map)
    log.info("Profiles loaded — %d available", len(profiles))

    settings = await cl.ChatSettings(
        [
            cl.input_widget.Select(
                id="model",
                label="LLM Model",
                values=model_names,
                initial_value=model_names[0],
            ),
            cl.input_widget.Select(
                id="profile",
                label="Expert Profile (Level 2)",
                values=profile_names,
                initial_value=profile_names[0],
            ),
            cl.input_widget.Switch(
                id="verbose",
                label="Show agent thinking",
                initial=True,
            ),
            cl.input_widget.Switch(
                id="multi_agent",
                label="Multi-agent mode (needs a capable model)",
                initial=False,
            ),
        ]
    ).send()

    selected_model = settings.get("model", model_names[0])
    selected_profile_name = settings.get("profile", "(none)")
    cl.user_session.set("model", selected_model)
    cl.user_session.set("profile_id", profile_id_map.get(selected_profile_name))
    cl.user_session.set("verbose", settings.get("verbose", True))
    cl.user_session.set("multi_agent", settings.get("multi_agent", False))
    cl.user_session.set("user_id", user_id)

    # Create a conversation record (skipped in guest mode)
    conv_id = None
    short_id = None
    if not is_guest:
        conv_id, short_id = q.create_conversation(user_id, selected_model)
        log.info("Conversation created — id=%s short_id=%s model=%s", conv_id, short_id, selected_model)
    cl.user_session.set("conv_id", conv_id)
    cl.user_session.set("short_id", short_id)

    tool_count = registry.tool_count()
    tool_msg = (
        f"**{tool_count} MCP tool(s) loaded**"
        if tool_count
        else "_No MCP tools — add servers to `bin/mcp_servers/`._"
    )
    chat_ref = f"🔖 `{short_id}`" if short_id else ""
    await cl.Message(
        content=(
            f"**{BOT_NAME}** ready. {tool_msg}\n\n"
            f"Select a model and expert profile above, then start chatting.\n\n"
            f"---\n"
            f"🔧 [API Docs](http://localhost:{API_PORT}/docs) · "
            f"[Profiles](http://localhost:{API_PORT}/profiles) · "
            f"[Health](http://localhost:{API_PORT}/health)"
            + (f"\n\n{chat_ref}" if chat_ref else "")
        )
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    new_model = settings.get("model")
    profile_name = settings.get("profile", "(none)")
    profile_id_map = cl.user_session.get("profile_id_map", {})
    profile_id = profile_id_map.get(profile_name)
    cl.user_session.set("model", new_model)
    cl.user_session.set("profile_id", profile_id)
    cl.user_session.set("verbose", settings.get("verbose", True))
    cl.user_session.set("multi_agent", settings.get("multi_agent", False))
    log.info(
        "Settings updated — model=%s profile=%s verbose=%s",
        new_model, profile_name, settings.get("verbose"),
    )


# ── Message handler ──────────────────────────────────────────────────────────


@cl.on_message
async def on_message(message: cl.Message):
    model: str = cl.user_session.get("model") or "llama3.2"
    verbose: bool = cl.user_session.get("verbose", True)
    persist: bool = cl.user_session.get("persist", True)
    profile_id: str | None = cl.user_session.get("profile_id")
    registry: MCPRegistry = cl.user_session.get("registry")
    user_id: str = cl.user_session.get("user_id", "local")
    conv_id: str = cl.user_session.get("conv_id")

    log.info("Message received — user=%s model=%s len=%d", user_id, model, len(message.content))
    log.debug("Message content: %s", message.content[:200])

    # Persist user message
    if persist and conv_id:
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

    _ALWAYS_SHOW = {"🚀", "✅"}

    def on_agent_step(step_name: str, content: str):
        log.debug("Agent step — %s: %s", step_name, content[:120])
        always = any(step_name.startswith(p) for p in _ALWAYS_SHOW)
        if verbose or always:
            asyncio.run_coroutine_threadsafe(_emit_step(step_name, content), loop)

    response_msg = cl.Message(content="")
    await response_msg.send()

    t_start = time.perf_counter()
    try:
        multi_agent: bool = cl.user_session.get("multi_agent", False)
        result = await asyncio.to_thread(
            _run_crew_sync, message.content, model, registry, ask_user_sync, on_agent_step, profile_id, multi_agent
        )
        elapsed = time.perf_counter() - t_start
        log.info("Crew finished in %.2fs", elapsed)

        # Persist assistant response
        if persist and conv_id:
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
    actions = [cl.Action(name=c, label=c, value=c, payload={"value": c}) for c in choices]
    response = await cl.AskActionMessage(content=prompt, actions=actions, timeout=120).send()
    if not response:
        return choices[-1]
    log.debug("HITL raw response: %s", response)
    return (
        response.get("value")
        or response.get("payload", {}).get("value")
        or response.get("name")
        or choices[-1]
    )


async def _emit_step(name: str, content: str):
    async with cl.Step(name=name) as step:
        step.output = content


def _run_crew_sync(user_message, model, registry, ask_user_fn, on_step_fn, profile_id=None, multi_agent=False) -> str:
    tool_defs: list = []
    tool_map: dict = {}

    if registry:
        t_defs, t_map = registry.get_runner_tools(ask_user_fn)
        tool_defs += t_defs
        tool_map.update(t_map)

    inst_def, inst_fn = make_runner_installer_tool(ask_user_fn)
    tool_defs.append(inst_def)
    tool_map["install_mcp_server"] = inst_fn

    log.debug("Building runner — model=%s tools=%d profile=%s multi=%s", model, len(tool_defs), profile_id, multi_agent)
    builder = build_hierarchical_crew if multi_agent else build_crew
    runner = builder(model=model, tool_defs=tool_defs, tool_map=tool_map, on_step=on_step_fn, profile_id=profile_id)
    return runner.kickoff(inputs={"task": user_message})
