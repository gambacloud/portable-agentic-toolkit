"""CRUD helpers — one function per operation, no ORM."""
import json
import uuid
from datetime import datetime, timezone

from db.database import get_conn


# ── Users ────────────────────────────────────────────────────────────────────


def upsert_user(user_id: str, name: str = "Anonymous") -> dict:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (id, name) VALUES (?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name      = excluded.name,
                 last_seen = datetime('now')""",
            (user_id, name),
        )
    return get_user(user_id)


def get_user(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ── Conversations ─────────────────────────────────────────────────────────────


def create_conversation(user_id: str, model: str, title: str | None = None) -> str:
    conv_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, model, title) VALUES (?, ?, ?, ?)",
            (conv_id, user_id, model, title),
        )
    return conv_id


def append_message(conv_id: str, role: str, content: str) -> None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT messages FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        if not row:
            return
        msgs = json.loads(row["messages"])
        msgs.append({
            "role": role,
            "content": content,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        conn.execute(
            "UPDATE conversations SET messages = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(msgs), conv_id),
        )


def get_conversation(conv_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["messages"] = json.loads(data["messages"])
    return data


def list_conversations(user_id: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, model, created_at, updated_at "
            "FROM conversations WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── System Profiles ───────────────────────────────────────────────────────────


def list_profiles() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM system_profiles ORDER BY is_default DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_profile(profile_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM system_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    return dict(row) if row else None


def get_default_profile() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM system_profiles WHERE is_default = 1 LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def create_profile(
    name: str,
    role: str | None,
    goal: str | None,
    backstory: str | None,
    is_default: bool,
) -> dict:
    profile_id = str(uuid.uuid4())
    with get_conn() as conn:
        if is_default:
            conn.execute("UPDATE system_profiles SET is_default = 0")
        conn.execute(
            "INSERT INTO system_profiles (id, name, role, goal, backstory, is_default) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profile_id, name, role, goal, backstory, int(is_default)),
        )
    return get_profile(profile_id)


def update_profile(profile_id: str, **kwargs) -> dict | None:
    allowed = {"name", "role", "goal", "backstory", "is_default"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_profile(profile_id)
    with get_conn() as conn:
        if fields.get("is_default"):
            conn.execute("UPDATE system_profiles SET is_default = 0")
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE system_profiles SET {set_clause} WHERE id = ?",
            [*fields.values(), profile_id],
        )
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM system_profiles WHERE id = ?", (profile_id,)
        )
    return cur.rowcount > 0
