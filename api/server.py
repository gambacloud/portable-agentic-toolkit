"""
FastAPI REST + WebSocket API.

Identity: a signed session cookie (set at /login) or an "Authorization: Bearer
pat_..." personal access token — see current_user() and AuthGuardMiddleware.
Docs: http://localhost:8002/docs
"""
import asyncio
import concurrent.futures
import os
import threading
import uuid
from pathlib import Path

import db.queries as q
from db.database import DB_PATH
from fastapi import Depends, FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from utils.auth import get_or_create_session_secret
from utils.logger import get_logger

log = get_logger(__name__)

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")

api = FastAPI(
    title=f"{BOT_NAME} API",
    version="1.2.0",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth gate ─────────────────────────────────────────────────────────────────
# Per-user accounts (username/password, hashed in db/database.py's users table)
# gate the app behind a session cookie set at /login, or a personal access
# token (Authorization: Bearer pat_...) for non-interactive callers. Browser
# fetch() calls need no changes: same-origin requests send cookies automatically.

_AUTH_ALLOWLIST = {"/login", "/auth/login", "/health", "/favicon.ico"}


class AuthGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _AUTH_ALLOWLIST or path.startswith("/settings-assets/"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:].startswith("pat_"):
            from utils.auth import hash_token
            user_id = q.get_user_id_for_token_hash(hash_token(auth_header[7:]))
            if user_id:
                request.state.user_id = user_id
                return await call_next(request)
            return JSONResponse({"detail": "Invalid API token"}, status_code=401)

        if request.session.get("authed") and request.session.get("user_id"):
            request.state.user_id = request.session["user_id"]
            return await call_next(request)
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/login")
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)


# Added in this order so SessionMiddleware (added last) wraps AuthGuardMiddleware
# and runs first, populating request.session before the guard reads it.
api.add_middleware(AuthGuardMiddleware)
api.add_middleware(
    SessionMiddleware,
    secret_key=get_or_create_session_secret(),
    session_cookie="pat_session",
    same_site="lax",
    max_age=60 * 60 * 24 * 30,  # 30 days
)

from api.reminders import router as reminders_router
api.include_router(reminders_router)


_LOGIN_PAGE = """\
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Sign in</title>
<style>
  body {{ background:#0f172a; color:#f8fafc; font-family:-apple-system,'Segoe UI',sans-serif;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  form {{ background:rgba(30,41,59,0.85); border:1px solid rgba(255,255,255,0.1); border-radius:16px;
          padding:2rem; width:320px; box-shadow:0 4px 6px -1px rgba(0,0,0,0.3); }}
  h1 {{ font-size:1.3rem; margin:0 0 1.2rem; }}
  input {{ width:100%; box-sizing:border-box; background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.1);
           color:white; padding:0.65rem 0.9rem; border-radius:8px; font-size:0.9rem; margin-bottom:1rem; }}
  button {{ width:100%; background:#3b82f6; color:white; border:none; padding:0.65rem; border-radius:8px;
            font-weight:600; cursor:pointer; }}
  button:hover {{ background:#2563eb; }}
  .err {{ color:#ef4444; font-size:0.85rem; margin:-0.5rem 0 1rem; }}
  .hint {{ color:#94a3b8; font-size:0.75rem; margin-top:1rem; }}
</style></head><body>
<form method="post" action="/auth/login">
  <h1>🔒 Sign in</h1>
  {error_html}
  <input type="text" name="username" placeholder="Username" autofocus required>
  <input type="password" name="password" placeholder="Password" required>
  <input type="hidden" name="next" value="{next_url}">
  <button type="submit">Continue</button>
  <p class="hint">First run? Username <code>local</code>, password printed to the app's log / console on startup (also saved to <code>.auth_token</code> next to the app).</p>
</form>
</body></html>
"""


@api.get("/login", response_class=HTMLResponse, tags=["auth"])
def login_page(next: str = "/", error: str = ""):
    error_html = f'<p class="err">{error}</p>' if error else ""
    return _LOGIN_PAGE.format(error_html=error_html, next_url=next.replace('"', "&quot;"))


@api.post("/auth/login", tags=["auth"])
async def do_login(request: Request):
    from utils.auth import verify_password
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    next_url = str(form.get("next", "/")) or "/"
    if not next_url.startswith("/"):
        next_url = "/"

    user = q.get_user_by_username(username)
    if user and user.get("password_hash") and verify_password(password, user["password_hash"]):
        request.session.clear()
        request.session["authed"] = True
        request.session["user_id"] = user["id"]
        return RedirectResponse(url=next_url, status_code=303)
    return RedirectResponse(url=f"/login?error=Invalid+username+or+password&next={next_url}", status_code=303)


@api.post("/auth/logout", tags=["auth"])
def do_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@api.on_event("startup")
def init_db_budget():
    from db.database import get_conn
    with get_conn() as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN token_usage INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN token_limit INTEGER DEFAULT 1000000") # Default 1M limit
        except Exception:
            pass


@api.on_event("startup")
def init_db_hierarchy():
    from db.database import get_conn
    with get_conn() as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'employee'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN department TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN manager_id TEXT REFERENCES users(id)")
        except Exception:
            pass

        # Bootstrap: with no admin yet, promote the default single-user identity
        # ("local", used by the WS default) so someone can grant roles via the API.
        has_admin = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        if not has_admin:
            conn.execute(
                """INSERT INTO users (id, role) VALUES ('local', 'admin')
                   ON CONFLICT(id) DO UPDATE SET role = 'admin'"""
            )


@api.on_event("startup")
def init_db_accounts():
    from db.database import get_conn
    from utils.auth import get_or_create_bootstrap_password, hash_password

    with get_conn() as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        except Exception:
            pass
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL REFERENCES users(id),
                name       TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # First run (or upgrading from the old shared-token gate): give the
        # bootstrap admin a real username/password so per-user login works.
        row = conn.execute("SELECT password_hash FROM users WHERE id = 'local'").fetchone()
        if row and not row[0]:
            conn.execute(
                "UPDATE users SET username = 'local', password_hash = ? WHERE id = 'local'",
                (hash_password(get_or_create_bootstrap_password()),),
            )


@api.on_event("startup")
def backfill_titles():
    updated = q.backfill_conversation_titles()
    if updated:
        log.info("Backfilled titles for %d conversation(s)", updated)

# ── Settings endpoints ────────────────────────────────────────────────────────

@api.get("/api/settings")
def get_settings_info():
    from utils.settings import (
        get_document_instructions,
        get_logo_filename,
        get_system_prompt_extra,
        get_user_prompt_prefix,
        SETTINGS_DIR,
    )
    logo = get_logo_filename()
    document_instructions = get_document_instructions()
    return {
        "settings_dir": str(SETTINGS_DIR),
        "logo_url": f"/settings-assets/{logo}" if logo else None,
        "has_system_prompt": bool(get_system_prompt_extra()),
        "has_user_prompt": bool(get_user_prompt_prefix()),
        "has_document_instructions": bool(document_instructions),
        "document_instructions": document_instructions,
    }


class DocumentInstructionsUpdate(BaseModel):
    text: str


@api.post("/api/settings/document-instructions")
def set_document_instructions(body: DocumentInstructionsUpdate):
    from utils.settings import save_document_instructions
    save_document_instructions(body.text)
    return {"ok": True}


_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp"}


@api.post("/api/settings/logo")
async def upload_logo(file: UploadFile):
    from utils.settings import save_logo

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _LOGO_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type: '{suffix}'. Supported: {', '.join(sorted(_LOGO_SUFFIXES))}")

    data = await file.read()
    save_logo(data, suffix)

    from utils.settings import get_logo_filename
    logo = get_logo_filename()
    return {"logo_url": f"/settings-assets/{logo}" if logo else None}


def _provider_status_payload() -> dict:
    from utils.env_config import KNOWN_KEYS, read_env_status
    from utils.ollama_utils import is_ollama_running, list_model_names

    ollama_up = is_ollama_running()
    status = read_env_status()
    return {
        "providers": {
            key: {"label": label, "configured": status[key]}
            for key, label in KNOWN_KEYS.items()
        },
        "ollama": {"running": ollama_up, "models": list_model_names() if ollama_up else []},
    }


@api.get("/api/settings/env-keys")
def get_env_keys_status():
    return _provider_status_payload()


class EnvKeysUpdate(BaseModel):
    keys: dict[str, str]


@api.post("/api/settings/env-keys")
def set_env_keys(body: EnvKeysUpdate):
    from utils.env_config import KNOWN_KEYS, write_env_keys
    from api.chat import get_all_models

    unknown = [k for k in body.keys if k not in KNOWN_KEYS]
    if unknown:
        raise HTTPException(400, f"Unknown key(s): {', '.join(unknown)}")

    write_env_keys(body.keys)
    payload = _provider_status_payload()
    payload["models"] = get_all_models()
    return payload


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


def current_user(request: Request) -> str:
    """Real identity, set by AuthGuardMiddleware from the session cookie or a
    Bearer PAT — never trusted from a client-supplied header."""
    return getattr(request.state, "user_id", "anonymous")


def _public_user(user: dict) -> dict:
    """Strips password_hash before a user row leaves the API — it's only ever
    needed internally (login verification, password-change checks)."""
    return {k: v for k, v in user.items() if k != "password_hash"}


ROLE_RANK = {"employee": 0, "manager": 1, "admin": 2}


def require_role(min_role: str):
    """Dependency factory: 403s unless current_user's stored role meets min_role
    (admin > manager > employee). The role lives on the users row, not the
    X-User-Id header, so it can't be spoofed by just changing the header."""
    def _dep(user_id: str = Depends(current_user)) -> str:
        user = q.get_user(user_id) or q.upsert_user(user_id)
        if ROLE_RANK.get(user.get("role", "employee"), 0) < ROLE_RANK[min_role]:
            raise HTTPException(403, f"Requires role '{min_role}' or higher")
        return user_id
    return _dep


# ── Per-model budgets (config/model_limits.yaml — set via settings/model_limits.yaml) ─


def _period_key(period: str, conv_id: str | None) -> str:
    if period == "session":
        return conv_id or "no-conversation"
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _check_model_budget(user_id: str, model: str, conv_id: str | None) -> str | None:
    """Returns an error message if the configured per-model budget is exceeded, else None."""
    from utils.settings import resolve_model_limit
    cfg = resolve_model_limit(model)
    if not cfg:
        return None
    usage = q.get_model_usage(user_id, model, _period_key(cfg["period"], conv_id))
    if usage >= cfg["limit"]:
        return f"Budget exceeded for '{model}' ({cfg['period']}): used {usage} of {cfg['limit']} tokens."
    return None


def _track_model_usage(user_id: str, model: str, conv_id: str | None, tokens: int) -> None:
    from utils.settings import resolve_model_limit
    cfg = resolve_model_limit(model)
    if not cfg or tokens <= 0:
        return
    q.add_model_usage(user_id, model, _period_key(cfg["period"], conv_id), tokens)


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
    return _public_user(q.upsert_user(user_id))


@api.get("/users/me/budget", tags=["users"])
def get_budget(user_id: str = Depends(current_user)):
    from db.database import get_conn
    with get_conn() as conn:
        res = conn.execute("SELECT token_usage, token_limit FROM users WHERE id = ?", (user_id,)).fetchone()
        if res:
            return {"token_usage": res[0] or 0, "token_limit": res[1] or 0}
    return {"token_usage": 0, "token_limit": 1000000}


@api.get("/users/me/budget/models", tags=["users"])
def get_model_budgets(user_id: str = Depends(current_user)):
    """Per-model usage vs. the limits configured in settings/model_limits.yaml."""
    from utils.settings import get_model_limits
    rows = []
    for pattern, cfg in get_model_limits().items():
        period_key = _period_key(cfg["period"], conv_id=None) if cfg["period"] == "month" else None
        if period_key is not None:
            usage = q.get_model_usage(user_id, pattern, period_key)
        else:
            # session-scoped limits are per-conversation; sum every session on record for this pattern
            usage = q.sum_model_usage(user_id, pattern)
        rows.append({
            "model": pattern,
            "period": cfg["period"],
            "period_key": period_key,
            "usage": usage,
            "limit": cfg["limit"],
        })
    return rows


@api.get("/users/me/conversations", tags=["users"])
def my_conversations(limit: int = 20, user_id: str = Depends(current_user)):
    return q.list_conversations(user_id, limit)


class ModelLimitEntry(BaseModel):
    limit: int
    period: str = "month"  # "month" | "session"


@api.get("/settings/model-limits", tags=["settings"])
def get_model_limits_config(user_id: str = Depends(require_role("admin"))):
    from utils.settings import get_model_limits
    return get_model_limits()


@api.put("/settings/model-limits", tags=["settings"])
def put_model_limits_config(body: dict[str, ModelLimitEntry], user_id: str = Depends(require_role("admin"))):
    for pattern, entry in body.items():
        if entry.period not in ("month", "session"):
            raise HTTPException(400, f"period must be 'month' or 'session' for '{pattern}'")
        if entry.limit <= 0:
            raise HTTPException(400, f"limit must be positive for '{pattern}'")
    from utils.settings import save_model_limits
    save_model_limits({k: v.model_dump() for k, v in body.items()})
    return {"ok": True}


# ── Hierarchy: roles / managers / departments ────────────────────────────────


@api.get("/users", tags=["users"])
def list_all_users(user_id: str = Depends(require_role("admin"))):
    return [_public_user(u) for u in q.list_users()]


class UserHierarchyUpdate(BaseModel):
    role: str | None = None          # "employee" | "manager" | "admin"
    department: str | None = None
    manager_id: str | None = None    # "" clears the manager


@api.patch("/users/{target_user_id}", tags=["users"])
def update_user_hierarchy(target_user_id: str, body: UserHierarchyUpdate, user_id: str = Depends(require_role("admin"))):
    if body.role is not None and body.role not in ROLE_RANK:
        raise HTTPException(400, f"role must be one of {list(ROLE_RANK)}")
    if not q.get_user(target_user_id):
        raise HTTPException(404, "User not found")
    updated = q.update_user_hierarchy(target_user_id, role=body.role, department=body.department, manager_id=body.manager_id)
    return _public_user(updated)


@api.get("/users/me/reports", tags=["users"])
def my_direct_reports(user_id: str = Depends(require_role("manager"))):
    return [_public_user(u) for u in q.list_direct_reports(user_id)]


@api.get("/departments/{department}/members", tags=["users"])
def department_members(department: str, user_id: str = Depends(current_user)):
    return [_public_user(u) for u in q.list_department_members(department)]


# ── Accounts (per-user login) ────────────────────────────────────────────────


class AccountCreate(BaseModel):
    username: str
    password: str
    role: str = "employee"
    department: str | None = None
    manager_id: str | None = None


@api.post("/users", status_code=201, tags=["users"])
def create_account(body: AccountCreate, user_id: str = Depends(require_role("admin"))):
    from utils.auth import hash_password
    if body.role not in ROLE_RANK:
        raise HTTPException(400, f"role must be one of {list(ROLE_RANK)}")
    if len(body.password) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    if q.get_user_by_username(body.username):
        raise HTTPException(409, f"Username '{body.username}' is already taken")
    new_id = body.username  # ids are free-text already (e.g. "local") — reuse the username
    if q.get_user(new_id):
        raise HTTPException(409, f"User id '{new_id}' already exists")
    return _public_user(q.create_account(new_id, body.username, hash_password(body.password), body.role, body.department, body.manager_id))


class PasswordReset(BaseModel):
    new_password: str


@api.post("/users/{target_user_id}/reset-password", tags=["users"])
def reset_password(target_user_id: str, body: PasswordReset, user_id: str = Depends(require_role("admin"))):
    from utils.auth import hash_password
    if len(body.new_password) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    if not q.get_user(target_user_id):
        raise HTTPException(404, "User not found")
    q.set_password(target_user_id, hash_password(body.new_password))
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@api.post("/users/me/password", tags=["users"])
def change_own_password(body: PasswordChange, user_id: str = Depends(current_user)):
    from utils.auth import hash_password, verify_password
    user = q.get_user(user_id)
    if not user or not user.get("password_hash") or not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(403, "Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    q.set_password(user_id, hash_password(body.new_password))
    return {"ok": True}


# ── Personal access tokens (for scripts / the /conversations/{id}/ask API) ──


class TokenCreate(BaseModel):
    name: str


@api.post("/users/me/tokens", status_code=201, tags=["users"])
def create_my_token(body: TokenCreate, user_id: str = Depends(current_user)):
    from utils.auth import generate_pat, hash_token
    plaintext = generate_pat()
    meta = q.create_api_token(str(uuid.uuid4()), user_id, body.name, hash_token(plaintext))
    meta["token"] = plaintext  # shown once — only the hash is stored
    return meta


@api.get("/users/me/tokens", tags=["users"])
def list_my_tokens(user_id: str = Depends(current_user)):
    return q.list_api_tokens(user_id)


@api.delete("/users/me/tokens/{token_id}", status_code=204, tags=["users"])
def delete_my_token(token_id: str, user_id: str = Depends(current_user)):
    if not q.delete_api_token(token_id, user_id):
        raise HTTPException(404, "Token not found")


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


class ConversationAsk(BaseModel):
    content: str
    active_mcps: list[str] | None = None


@api.post("/conversations/{conv_id}/ask", tags=["conversations"])
def ask_conversation(conv_id: str, body: ConversationAsk):
    """Synchronous invoke: run the agent on this conversation and return its reply
    in the response — for external systems that can't hold a WebSocket open.
    Discovering MCP servers + the LLM call can take several seconds; callers
    should set a generous timeout (no streaming/progress here, unlike the WS chat)."""
    conv = q.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if not body.content.strip():
        raise HTTPException(400, "content must not be empty")

    user_id = conv["user_id"]
    model = conv["model"]

    from db.database import get_conn
    with get_conn() as conn:
        usage_row = conn.execute("SELECT token_usage, token_limit FROM users WHERE id = ?", (user_id,)).fetchone()
    if usage_row:
        usage, limit = usage_row[0] or 0, usage_row[1] or 0
        if limit > 0 and usage >= limit:
            raise HTTPException(402, f"Budget exceeded. You have used {usage} out of your {limit} tokens limit.")

    model_budget_error = _check_model_budget(user_id, model, conv_id)
    if model_budget_error:
        raise HTTPException(402, model_budget_error)

    import asyncio
    from mcp_tools.registry import MCPRegistry

    mcp_servers_dir = Path(__file__).parent.parent / "bin" / "mcp_servers"

    def _auto_allow(prompt: str, choices: list[str]) -> str:
        return choices[0]

    usage_totals = {"tokens": 0}

    def _on_token_usage(prompt_tokens: int, completion_tokens: int):
        usage_totals["tokens"] += prompt_tokens + completion_tokens

    async def _do():
        registry = MCPRegistry(mcp_servers_dir)
        await registry.discover()
        try:
            from api.chat import run_crew_sync
            return await asyncio.to_thread(
                run_crew_sync,
                body.content, model, registry,
                _auto_allow, lambda *a: None, lambda *a: None,
                None, False, body.active_mcps, _on_token_usage,
            )
        finally:
            await registry.close()

    q.append_message(conv_id, "user", body.content)
    try:
        reply = asyncio.run(_do())
    except Exception as exc:
        raise HTTPException(500, f"Agent run failed: {exc}")
    q.append_message(conv_id, "assistant", reply)

    if usage_totals["tokens"] > 0:
        with get_conn() as conn:
            conn.execute("UPDATE users SET token_usage = COALESCE(token_usage, 0) + ? WHERE id = ?", (usage_totals["tokens"], user_id))
        _track_model_usage(user_id, model, conv_id, usage_totals["tokens"])

    return {"reply": reply}


@api.delete("/conversations/{conv_id}", status_code=204, tags=["conversations"])
def remove_conversation(conv_id: str):
    if not q.delete_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")


@api.post("/conversations/cleanup-empty", tags=["conversations"])
def cleanup_empty_conversations(user_id: str = Depends(current_user)):
    return {"deleted": q.delete_empty_conversations(user_id)}


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
def create_schedule(body: ScheduleCreate, user_id: str = Depends(require_role("manager"))):
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
def update_schedule(sid: str, body: ScheduleUpdate, user_id: str = Depends(require_role("manager"))):
    if not q.get_schedule(sid):
        raise HTTPException(404, "Schedule not found")
    updated = q.update_schedule(sid, **body.model_dump(exclude_none=True))
    from scheduler.engine import get_engine
    get_engine().add_or_replace(updated)
    return updated


@api.delete("/schedules/{sid}", status_code=204, tags=["schedules"])
def delete_schedule(sid: str, user_id: str = Depends(require_role("manager"))):
    if not q.delete_schedule(sid):
        raise HTTPException(404, "Schedule not found")
    from scheduler.engine import get_engine
    get_engine().remove(sid)


@api.post("/schedules/{sid}/run", tags=["schedules"])
def run_schedule_now(sid: str, user_id: str = Depends(require_role("manager"))):
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
def create_output(body: OutputCreate, user_id: str = Depends(require_role("manager"))):
    return q.create_output(body.name, body.type, body.config)


@api.patch("/outputs/{oid}", tags=["outputs"])
def update_output(oid: str, body: OutputUpdate, user_id: str = Depends(require_role("manager"))):
    if not q.get_output(oid):
        raise HTTPException(404, "Output not found")
    updated = q.update_output(oid, **body.model_dump(exclude_none=True))
    return updated


@api.delete("/outputs/{oid}", status_code=204, tags=["outputs"])
def delete_output(oid: str, user_id: str = Depends(require_role("manager"))):
    if not q.delete_output(oid):
        raise HTTPException(404, "Output not found")


@api.post("/outputs/{oid}/test", tags=["outputs"])
def test_output(oid: str, user_id: str = Depends(require_role("manager"))):
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
    enabled: bool | None = None
    env: dict[str, str] | None = None
    arg_values: dict[str, str] | None = None
    config_file_content: str | None = None
    url_values: dict[str, str] | None = None


class MCPInstall(BaseModel):
    name: str
    env: dict[str, str] | None = None
    config_file_content: str | None = None
    url_values: dict[str, str] | None = None


def _redact_env(env: dict) -> dict:
    """Never ship real secret values to the browser — just whether each is set."""
    return {key: not str(value).startswith("<your ") for key, value in (env or {}).items()}


@api.get("/mcp-catalog", tags=["mcps"])
def get_mcp_catalog():
    from mcp_tools.installer import _load_catalog
    return _load_catalog()


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
                    safe_cfg = {**cfg, "env": _redact_env(cfg.get("env", {}))}
                    results.append({"name": d.name, "enabled": cfg.get("enabled", True), "config": safe_cfg})
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
    if body.enabled is not None:
        cfg["enabled"] = body.enabled
    if body.env:
        cfg.setdefault("env", {}).update({k: v for k, v in body.env.items() if v and v.strip()})
    if body.arg_values:
        from mcp_tools.installer import _load_catalog
        entry = _load_catalog().get(name, {})
        args = cfg.setdefault("args", [])
        for var in entry.get("arg_vars", []):
            key = var["key"]
            value = body.arg_values.get(key, "").strip()
            if not value:
                continue
            flag = var["flag"]
            if flag in args:
                idx = args.index(flag)
                if idx + 1 < len(args):
                    args[idx + 1] = value
                else:
                    args.append(value)
            else:
                args += [flag, value]
    if body.config_file_content is not None:
        from mcp_tools.installer import _load_catalog
        entry = _load_catalog().get(name, {})
        config_file_spec = entry.get("config_file")
        if config_file_spec:
            (mcp_dir / config_file_spec["filename"]).write_text(body.config_file_content, encoding="utf-8")
    if body.url_values and body.url_values.get("url", "").strip():
        cfg["url"] = body.url_values["url"].strip()
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return {**cfg, "env": _redact_env(cfg.get("env", {}))}


@api.post("/mcps", tags=["mcps"])
def install_mcp(body: MCPInstall):
    from mcp_tools.installer import _install, _load_catalog
    catalog = _load_catalog()
    def fake_ask(prompt, choices):
        return choices[0] # Auto-approve for UI
    result = _install(body.name.strip().lower(), catalog, fake_ask, body.env, body.config_file_content, body.url_values)
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


@api.get("/kb-ui", response_class=HTMLResponse, tags=["ui"])
def kb_ui():
    html_path = Path(__file__).parent.parent / "public" / "kb_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/wizard-ui", response_class=HTMLResponse, tags=["ui"])
def wizard_ui():
    html_path = Path(__file__).parent.parent / "public" / "wizard_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/branding-ui", response_class=HTMLResponse, tags=["ui"])
def branding_ui():
    html_path = Path(__file__).parent.parent / "public" / "branding_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/usage-ui", response_class=HTMLResponse, tags=["ui"])
def usage_ui():
    html_path = Path(__file__).parent.parent / "public" / "usage_ui.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "UI File Not Found"


@api.get("/generated/{file_id}", tags=["meta"])
def download_generated_file(file_id: str):
    import uuid as _uuid

    from utils.pdf_export import GENERATED_DIR

    try:
        _uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(404, "File not found")

    folder = GENERATED_DIR / file_id
    if not folder.is_dir():
        raise HTTPException(404, "File not found")
    files = list(folder.iterdir())
    if not files:
        raise HTTPException(404, "File not found")
    return FileResponse(files[0], filename=files[0].name)


@api.get("/schedule-runs", tags=["schedules"])
def list_schedule_runs(sid: str | None = None, limit: int = 50):
    return q.list_schedule_runs(sid, limit)


# ── RAG ───────────────────────────────────────────────────────────────────────


@api.post("/rag/extract", tags=["rag"])
async def rag_extract(file: UploadFile):
    import shutil
    import tempfile
    from rag.indexer import SUPPORTED_SUFFIXES, parse_file

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type: '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        named_path = tmp_path.parent / (file.filename or tmp_path.name)
        tmp_path = tmp_path.rename(named_path)
        text = await asyncio.to_thread(parse_file, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not text.strip():
        raise HTTPException(422, "No text could be extracted from this file.")

    return {"source": file.filename, "content": text}


@api.post("/rag/upload", tags=["rag"])
async def rag_upload(file: UploadFile):
    import shutil
    import tempfile
    from rag.indexer import SUPPORTED_SUFFIXES, index_file
    from rag.retriever import get_collection

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type: '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        collection = get_collection()
        named_path = tmp_path.parent / file.filename
        tmp_path = tmp_path.rename(named_path)
        chunks = await asyncio.to_thread(index_file, tmp_path, collection)
    finally:
        tmp_path.unlink(missing_ok=True)

    if chunks == 0:
        raise HTTPException(422, "No text could be extracted from this file.")

    return {"source": file.filename, "chunks": chunks}


@api.get("/rag/documents", tags=["rag"])
def rag_list_documents():
    from rag.retriever import list_sources
    return list_sources()


@api.delete("/rag/documents/{source}", status_code=204, tags=["rag"])
def rag_delete_document(source: str):
    from rag.retriever import delete_source
    deleted = delete_source(source)
    if deleted == 0:
        raise HTTPException(404, "Document not found in knowledge base")


# ── Models ────────────────────────────────────────────────────────────────────


@api.get("/models", tags=["meta"])
def list_models():
    from api.chat import get_all_models
    return get_all_models()


# ── WebSocket chat ─────────────────────────────────────────────────────────────


MCP_SERVERS_DIR = Path(__file__).parent.parent / "bin" / "mcp_servers"


@api.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, resume_conv_id: str | None = None):
    # AuthGuardMiddleware only wraps HTTP scope — WebSocket needs its own check.
    # Identity comes from the session (real login), never the old ?user_id= query
    # param — the frontend still sends it, but it's ignored now.
    if not websocket.session.get("authed") or not websocket.session.get("user_id"):
        await websocket.close(code=4401)
        return
    user_id = websocket.session["user_id"]
    await websocket.accept()
    loop = asyncio.get_event_loop()

    # ── Session defaults ──────────────────────────────────────────────────────
    persist = user_id != "guest"
    model = "llama3.2"
    profile_id: str | None = None
    verbose = True
    multi_agent = False
    active_mcps: list[str] | None = None
    kb_sources: list[str] = []
    conv_id: str | None = None

    # Pending HITL responses keyed by request id
    hitl_futures: dict[str, concurrent.futures.Future] = {}

    # ── MCP discovery ─────────────────────────────────────────────────────────
    from mcp_tools.registry import MCPRegistry
    registry = MCPRegistry(MCP_SERVERS_DIR)
    try:
        await registry.discover()

        # ── Bootstrap session data ────────────────────────────────────────────────
        from api.chat import get_all_models
        models = get_all_models()
        profiles = q.list_profiles()
        mcp_servers = registry.all_server_names()
        active_mcps = registry.server_names()[:]

        model = models[0] if models else "llama3.2"

        history: list[dict] = []
        short_id: str | None = None
        if persist:
            q.upsert_user(user_id)
            if resume_conv_id:
                existing = q.get_conversation(resume_conv_id)
                if existing:
                    conv_id = existing["id"]
                    short_id = existing["short_id"]
                    history = existing["messages"]
                    model = existing.get("model") or model
            # No resume_conv_id (or it no longer exists): don't create a row yet —
            # wait until the user actually sends a message (see msg_type == "message"
            # below). Otherwise every page load/reconnect leaves an empty conversation.

        # Notify about scheduled task runs since last session
        notifications: list[dict] = []
        if persist:
            unnotified = q.list_unnotified_runs()
            if unnotified:
                q.mark_runs_notified([r["id"] for r in unnotified])
                notifications = [
                    {
                        "schedule_name": r["schedule_name"],
                        "ran_at": r["ran_at"],
                        "result": (r["result"] or "")[:500],
                    }
                    for r in unnotified
                ]

        await websocket.send_json({
            "type": "ready",
            "conv_id": conv_id,
            "short_id": short_id,
            "models": models,
            "profiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
            "mcp_servers": mcp_servers,
            "active_mcps": active_mcps,
            "model": model,
            "notifications": notifications,
            "history": history,
        })

        # ── Thread-safe helpers ───────────────────────────────────────────────────

        _stop_requested = threading.Event()
        agent_task: asyncio.Task | None = None

        def send_sync(msg: dict) -> None:
            """Call from any thread to send a WS message."""
            if not _stop_requested.is_set():
                asyncio.run_coroutine_threadsafe(websocket.send_json(msg), loop)

        def ask_user_sync(prompt: str, choices: list[str]) -> str:
            hit_id = str(uuid.uuid4())
            cf_fut: concurrent.futures.Future = concurrent.futures.Future()

            async def _register_and_send():
                hitl_futures[hit_id] = cf_fut
                await websocket.send_json({
                    "type": "hitl_request",
                    "id": hit_id,
                    "prompt": prompt,
                    "choices": choices,
                })

            asyncio.run_coroutine_threadsafe(_register_and_send(), loop).result()
            try:
                return cf_fut.result(timeout=120)
            except Exception:
                return choices[-1]
            finally:
                hitl_futures.pop(hit_id, None)

        _ALWAYS_SHOW = {"🚀", "✅"}

        def on_agent_step(step_name: str, content: str) -> None:
            always = any(step_name.startswith(p) for p in _ALWAYS_SHOW)
            if verbose or always:
                send_sync({"type": "step", "name": step_name, "content": content})

        # ── Message loop ──────────────────────────────────────────────────────────
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "settings":
                    model = data.get("model", model)
                    profile_id = data.get("profile_id", profile_id)
                    verbose = data.get("verbose", verbose)
                    multi_agent = data.get("multi_agent", multi_agent)
                    if "active_mcps" in data:
                        active_mcps = data["active_mcps"]
                    if "kb_sources" in data:
                        kb_sources = data["kb_sources"]
                    log.info(
                        "WS settings updated — user=%s model=%s profile=%s verbose=%s mcps=%s",
                        user_id, model, profile_id, verbose, active_mcps,
                    )

                elif msg_type == "hitl_response":
                    hit_id = data.get("id", "")
                    value = data.get("value", "")
                    cf_fut = hitl_futures.get(hit_id)
                    if cf_fut is not None and not cf_fut.done():
                        cf_fut.set_result(value)

                elif msg_type == "stop":
                    if agent_task and not agent_task.done():
                        agent_task.cancel()

                elif msg_type == "message":
                    if agent_task and not agent_task.done():
                        continue

                    content = data.get("content", "").strip()
                    if not content:
                        continue

                    if persist and not conv_id:
                        conv_id, short_id = q.create_conversation(user_id, model, title=q.derive_title(content))
                        await websocket.send_json({"type": "conv_created", "conv_id": conv_id, "short_id": short_id})

                    # Inject the current canvas state into the context if the frontend provides it
                    canvas_state = data.get("canvas_state")
                    if canvas_state:
                        content = f"{content}\n\n[Current Canvas Context]:\n```\n{canvas_state}\n```"

                    log.info("WS message — user=%s model=%s len=%d", user_id, model, len(content))
                    if persist and conv_id:
                        q.append_message(conv_id, "user", content)

                    if persist:
                        from db.database import get_conn
                        with get_conn() as conn:
                            usage_row = conn.execute("SELECT token_usage, token_limit FROM users WHERE id = ?", (user_id,)).fetchone()
                            if usage_row:
                                usage, limit = usage_row[0] or 0, usage_row[1] or 0
                                if limit > 0 and usage >= limit:
                                    await websocket.send_json({"type": "error", "content": f"Budget exceeded. You have used {usage} out of your {limit} tokens limit."})
                                    continue

                        model_budget_error = _check_model_budget(user_id, model, conv_id)
                        if model_budget_error:
                            await websocket.send_json({"type": "error", "content": model_budget_error})
                            continue

                    def on_token_usage(prompt_tokens: int, completion_tokens: int, _conv_id=conv_id):
                        total = prompt_tokens + completion_tokens
                        if total > 0 and persist:
                            from db.database import get_conn
                            with get_conn() as conn:
                                conn.execute("UPDATE users SET token_usage = COALESCE(token_usage, 0) + ? WHERE id = ?", (total, user_id))
                            _track_model_usage(user_id, model, _conv_id, total)
                            send_sync({"type": "token_update", "added": total})

                    from api.chat import run_crew_sync

                    async def run_agent(
                        _content=content, _model=model, _profile_id=profile_id,
                        _multi_agent=multi_agent, _active_mcps=active_mcps,
                        _on_token_usage=on_token_usage, _kb_sources=kb_sources,
                    ):
                        nonlocal agent_task
                        try:
                            _stop_requested.clear()
                            result = await asyncio.to_thread(
                                run_crew_sync,
                                _content, _model, registry,
                                ask_user_sync, on_agent_step, send_sync,
                                _profile_id, _multi_agent, _active_mcps, _on_token_usage,
                                _kb_sources,
                            )
                            if persist and conv_id:
                                q.append_message(conv_id, "assistant", str(result))
                            await websocket.send_json({"type": "response", "content": str(result)})
                        except asyncio.CancelledError:
                            _stop_requested.set()
                            for fut in list(hitl_futures.values()):
                                if not fut.done():
                                    fut.cancel()
                            hitl_futures.clear()
                            await websocket.send_json({"type": "stopped"})
                        except Exception as exc:
                            log.error("WS chat error — %s", exc, exc_info=True)
                            await websocket.send_json({"type": "error", "content": str(exc)})
                        finally:
                            agent_task = None

                    agent_task = asyncio.create_task(run_agent())

        except WebSocketDisconnect:
            log.info("WS disconnected — user=%s conv=%s", user_id, conv_id)
            if agent_task and not agent_task.done():
                agent_task.cancel()
    finally:
        await registry.close()
