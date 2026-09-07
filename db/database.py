"""SQLite connection and schema initialisation."""
import os
import sqlite3
import uuid
from pathlib import Path

from utils.logger import get_logger
from utils.paths import app_dir

log = get_logger(__name__)

_default_db = str(app_dir() / "gambabot.db")
DB_PATH = Path(os.getenv("DB_PATH", _default_db))

_EXPERT_PROFILES_PATH = Path(__file__).parent.parent / "config" / "expert_profiles.yaml"

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT 'Anonymous',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    title      TEXT,
    model      TEXT,
    messages   TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_profiles (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    role       TEXT,
    goal       TEXT,
    backstory  TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    task        TEXT NOT NULL,
    cron        TEXT NOT NULL,
    model       TEXT NOT NULL,
    active_mcps TEXT NOT NULL DEFAULT '[]',
    active_outputs TEXT NOT NULL DEFAULT '[]',
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,
    last_result TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outputs (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,
    config     TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schedule_runs (
    id            TEXT PRIMARY KEY,
    schedule_id   TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    schedule_name TEXT NOT NULL,
    ran_at        TEXT NOT NULL DEFAULT (datetime('now')),
    result        TEXT,
    notified      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS model_usage (
    user_id     TEXT NOT NULL,
    model       TEXT NOT NULL,
    period_key  TEXT NOT NULL,
    token_usage INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, model, period_key)
);

CREATE TABLE IF NOT EXISTS reminders (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    remind_at  TEXT NOT NULL,
    note       TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_conn() -> sqlite3.Connection:
    """Open a connection with Row factory and FK enforcement."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # Migration: add short_id column if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "short_id" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN short_id TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_short_id ON conversations(short_id)")
            rows = conn.execute("SELECT id FROM conversations WHERE short_id IS NULL").fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE conversations SET short_id = ? WHERE id = ?",
                    (_gen_short_id(), row[0]),
                )
        # Migration: create schedule_runs if missing
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "schedule_runs" not in tables:
            conn.execute("""
                CREATE TABLE schedule_runs (
                    id            TEXT PRIMARY KEY,
                    schedule_id   TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
                    schedule_name TEXT NOT NULL,
                    ran_at        TEXT NOT NULL DEFAULT (datetime('now')),
                    result        TEXT,
                    notified      INTEGER NOT NULL DEFAULT 0
                )
            """)
        # Migration: add active_outputs to scheduled_tasks if missing
        st_cols = [r[1] for r in conn.execute("PRAGMA table_info(scheduled_tasks)").fetchall()]
        if "active_outputs" not in st_cols:
            conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN active_outputs TEXT NOT NULL DEFAULT '[]'")
        # Migration: let a Profile also serve as a multi-agent crew member,
        # with its own model override — same shape as a crew_agents entry in
        # config/agents.yaml, so the two sources can merge (see
        # agents.runner._load_crew_agent_configs).
        profile_cols = [r[1] for r in conn.execute("PRAGMA table_info(system_profiles)").fetchall()]
        if "is_crew_member" not in profile_cols:
            conn.execute("ALTER TABLE system_profiles ADD COLUMN is_crew_member INTEGER NOT NULL DEFAULT 0")
        if "model" not in profile_cols:
            conn.execute("ALTER TABLE system_profiles ADD COLUMN model TEXT")
        # Migration: create outputs if missing
        if "outputs" not in tables:
            conn.execute("""
                CREATE TABLE outputs (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    type       TEXT NOT NULL,
                    config     TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
        # Migration: create reminders if missing
        if "reminders" not in tables:
            conn.execute("""
                CREATE TABLE reminders (
                    id         TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    remind_at  TEXT NOT NULL,
                    note       TEXT,
                    status     TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
        _seed_expert_profiles(conn)


def _seed_expert_profiles(conn) -> None:
    """Insert any config/expert_profiles.yaml entry not already present by
    name. Git-tracked defaults, unlike ordinary Profiles which only live in
    this (gitignored) DB — delete one here and it will re-seed on the next
    restart; remove it from the YAML file instead if you don't want it."""
    if not _EXPERT_PROFILES_PATH.exists():
        return
    try:
        import yaml
        with open(_EXPERT_PROFILES_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        existing = {r[0] for r in conn.execute("SELECT name FROM system_profiles").fetchall()}
        for p in data.get("profiles", []):
            name = p.get("name")
            if not name or name in existing:
                continue
            conn.execute(
                "INSERT INTO system_profiles "
                "(id, name, role, goal, backstory, is_default, is_crew_member, model) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    str(uuid.uuid4()), name, p.get("role"), p.get("goal"), p.get("backstory"),
                    int(bool(p.get("is_crew_member"))), p.get("model"),
                ),
            )
    except Exception as exc:
        log.warning("Failed to seed expert profiles from %s: %s", _EXPERT_PROFILES_PATH, exc)


def _gen_short_id(length: int = 8) -> str:
    import random
    import string
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))
