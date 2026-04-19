"""SQLite connection and schema initialisation."""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", "gambabot.db"))

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
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,
    last_result TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
            # Backfill existing rows
            rows = conn.execute("SELECT id FROM conversations WHERE short_id IS NULL").fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE conversations SET short_id = ? WHERE id = ?",
                    (_gen_short_id(), row[0]),
                )


def _gen_short_id(length: int = 8) -> str:
    import random
    import string
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))
