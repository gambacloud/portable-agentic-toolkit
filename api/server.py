"""
FastAPI persistence API — mounted at /api on the Chainlit server.

Identity: pass X-User-ID header on every request.
Docs:     http://localhost:8000/api/docs
"""
import os
from pathlib import Path

import db.queries as q
from db.database import DB_PATH
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")

api = FastAPI(
    title=f"{BOT_NAME} API",
    version="1.2.0",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    model: str = "llama3.2"
    title: str | None = None


class MessageAppend(BaseModel):
    role: str
    content: str


class ProfileCreate(BaseModel):
    name: str
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    is_default: bool = False


class ProfileUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    is_default: bool | None = None


# ── Identity dependency ───────────────────────────────────────────────────────


def current_user(x_user_id: str = Header(default="anonymous")) -> str:
    return x_user_id


# ── Health ────────────────────────────────────────────────────────────────────


@api.get("/health", tags=["meta"])
def health():
    from db.database import get_conn

    db_size_mb = round(DB_PATH.stat().st_size / 1_048_576, 2) if DB_PATH.exists() else 0

    with get_conn() as conn:
        users      = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        convs      = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        messages   = conn.execute("SELECT SUM(json_array_length(messages)) FROM conversations").fetchone()[0] or 0
        profiles   = conn.execute("SELECT COUNT(*) FROM system_profiles").fetchone()[0]

    try:
        import ollama as ol
        models = [m.model for m in (ol.list().models or [])]
        ollama_status = "ok"
    except Exception:
        models = []
        ollama_status = "unreachable"

    mcp_dir = Path(__file__).parent.parent / "bin" / "mcp_servers"
    mcp_servers = [d.name for d in mcp_dir.iterdir() if d.is_dir()] if mcp_dir.exists() else []

    return {
        "status": "ok",
        "bot": BOT_NAME,
        "app_mode": os.getenv("APP_MODE", "SINGLE"),
        "db": {
            "path": str(DB_PATH),
            "size_mb": db_size_mb,
            "users": users,
            "conversations": convs,
            "messages": messages,
            "profiles": profiles,
        },
        "ollama": {
            "status": ollama_status,
            "models": models,
        },
        "mcp_servers": mcp_servers,
    }


# ── Users ─────────────────────────────────────────────────────────────────────


@api.get("/users/me", tags=["users"])
def get_me(user_id: str = Depends(current_user)):
    return q.upsert_user(user_id)


@api.get("/users/me/conversations", tags=["users"])
def my_conversations(limit: int = 20, user_id: str = Depends(current_user)):
    return q.list_conversations(user_id, limit)


# ── Conversations ─────────────────────────────────────────────────────────────


@api.post("/conversations", status_code=201, tags=["conversations"])
def start_conversation(body: ConversationCreate, user_id: str = Depends(current_user)):
    q.upsert_user(user_id)
    conv_id, short_id = q.create_conversation(user_id, body.model, body.title)
    return {"id": conv_id, "short_id": short_id}


@api.get("/conversations/s/{short_id}", tags=["conversations"])
def get_conversation_by_short(short_id: str):
    conv = q.get_conversation_by_short_id(short_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@api.get("/conversations/{conv_id}", tags=["conversations"])
def get_conversation(conv_id: str):
    conv = q.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@api.post("/conversations/{conv_id}/messages", status_code=201, tags=["conversations"])
def add_message(conv_id: str, body: MessageAppend):
    if not q.get_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    q.append_message(conv_id, body.role, body.content)
    return {"ok": True}


# ── System Profiles ───────────────────────────────────────────────────────────


@api.get("/profiles", tags=["profiles"])
def list_profiles():
    return q.list_profiles()


@api.post("/profiles", status_code=201, tags=["profiles"])
def create_profile(body: ProfileCreate):
    return q.create_profile(
        body.name, body.role, body.goal, body.backstory, body.is_default
    )


@api.put("/profiles/{profile_id}", tags=["profiles"])
def update_profile(profile_id: str, body: ProfileUpdate):
    updated = q.update_profile(profile_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(404, "Profile not found")
    return updated


@api.delete("/profiles/{profile_id}", status_code=204, tags=["profiles"])
def delete_profile(profile_id: str):
    if not q.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")


# ── Scheduled Tasks ───────────────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    name: str
    task: str
    cron: str
    model: str = "groq/llama-3.3-70b-versatile"
    active_mcps: list[str] = []
    active_outputs: list[str] = []


class ScheduleUpdate(BaseModel):
    name: str | None = None
    task: str | None = None
    cron: str | None = None
    model: str | None = None
    active_mcps: list[str] | None = None
    active_outputs: list[str] | None = None
    enabled: bool | None = None


@api.get("/schedules", tags=["schedules"])
def list_schedules():
    return q.list_schedules()


@api.post("/schedules", status_code=201, tags=["schedules"])
def create_schedule(body: ScheduleCreate):
    from apscheduler.triggers.cron import CronTrigger
    try:
        CronTrigger.from_crontab(body.cron)
    except Exception:
        raise HTTPException(400, f"Invalid cron expression: '{body.cron}'")
    schedule = q.create_schedule(body.name, body.task, body.cron, body.model, body.active_mcps, body.active_outputs)
    from scheduler.engine import get_engine
    get_engine().add_or_replace(schedule)
    return schedule


@api.patch("/schedules/{sid}", tags=["schedules"])
def update_schedule(sid: str, body: ScheduleUpdate):
    if not q.get_schedule(sid):
        raise HTTPException(404, "Schedule not found")
    updated = q.update_schedule(sid, **body.model_dump(exclude_none=True))
    from scheduler.engine import get_engine
    get_engine().add_or_replace(updated)
    return updated


@api.delete("/schedules/{sid}", status_code=204, tags=["schedules"])
def delete_schedule(sid: str):
    if not q.delete_schedule(sid):
        raise HTTPException(404, "Schedule not found")
    from scheduler.engine import get_engine
    get_engine().remove(sid)


@api.post("/schedules/{sid}/run", tags=["schedules"])
def run_schedule_now(sid: str):
    if not q.get_schedule(sid):
        raise HTTPException(404, "Schedule not found")
    import threading
    threading.Thread(
        target=lambda: __import__("scheduler.engine", fromlist=["get_engine"]).get_engine().run_now(sid),
        daemon=True,
        name=f"schedule-{sid[:8]}",
    ).start()
    return {"ok": True, "message": "Task started in background"}


# ── Outputs ───────────────────────────────────────────────────────────────────


class OutputCreate(BaseModel):
    name: str
    type: str
    config: dict


class OutputUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    config: dict | None = None


@api.get("/outputs", tags=["outputs"])
def list_outputs():
    return q.list_outputs()


@api.post("/outputs", status_code=201, tags=["outputs"])
def create_output(body: OutputCreate):
    return q.create_output(body.name, body.type, body.config)


@api.patch("/outputs/{oid}", tags=["outputs"])
def update_output(oid: str, body: OutputUpdate):
    if not q.get_output(oid):
        raise HTTPException(404, "Output not found")
    updated = q.update_output(oid, **body.model_dump(exclude_none=True))
    return updated


@api.delete("/outputs/{oid}", status_code=204, tags=["outputs"])
def delete_output(oid: str):
    if not q.delete_output(oid):
        raise HTTPException(404, "Output not found")


@api.post("/outputs/{oid}/test", tags=["outputs"])
def test_output(oid: str):
    output = q.get_output(oid)
    if not output:
        raise HTTPException(404, "Output not found")
    
    from scheduler.engine import send_to_output
    success, msg = send_to_output(output, "This is a test message from Portable Agentic Toolkit!")
    if not success:
        raise HTTPException(400, f"Test failed: {msg}")
    return {"ok": True, "message": "Test successful"}


# ── MCP Management ────────────────────────────────────────────────────────────


class MCPUpdate(BaseModel):
    enabled: bool


class MCPInstall(BaseModel):
    name: str


@api.get("/mcps", tags=["mcps"])
def list_mcps():
    mcp_dir = Path(__file__).parent.parent / "bin" / "mcp_servers"
    if not mcp_dir.exists():
        return []
    results = []
    for d in mcp_dir.iterdir():
        if d.is_dir():
            config_path = d / "config.json"
            if config_path.exists():
                import json
                try:
                    cfg = json.loads(config_path.read_text(encoding="utf-8"))
                    results.append({"name": d.name, "enabled": cfg.get("enabled", True), "config": cfg})
                except Exception:
                    pass
    return results


@api.patch("/mcps/{name}", tags=["mcps"])
def update_mcp(name: str, body: MCPUpdate):
    mcp_dir = Path(__file__).parent.parent / "bin" / "mcp_servers" / name
    config_path = mcp_dir / "config.json"
    if not config_path.exists():
        raise HTTPException(404, "MCP server not found")
    import json
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg["enabled"] = body.enabled
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


@api.post("/mcps", tags=["mcps"])
def install_mcp(body: MCPInstall):
    from mcp_tools.installer import _install, _load_catalog
    catalog = _load_catalog()
    def fake_ask(prompt, choices):
        return choices[0] # Auto-approve for UI
    result = _install(body.name.strip().lower(), catalog, fake_ask)
    return {"result": result}


@api.get("/mcp-ui", response_class=HTMLResponse, tags=["ui"])
def mcp_ui():
    html_path = Path(__file__).parent.parent / "public" / "mcp_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/schedules-ui", response_class=HTMLResponse, tags=["ui"])
def schedules_ui():
    html_path = Path(__file__).parent.parent / "public" / "schedules_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/outputs-ui", response_class=HTMLResponse, tags=["ui"])
def outputs_ui():
    html_path = Path(__file__).parent.parent / "public" / "outputs_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/wizard-ui", response_class=HTMLResponse, tags=["ui"])
def wizard_ui():
    html_path = Path(__file__).parent.parent / "public" / "wizard_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/schedule-runs", tags=["schedules"])
def list_schedule_runs(sid: str | None = None, limit: int = 50):
    return q.list_schedule_runs(sid, limit)
