"""CRUD helpers — one function per operation, no ORM."""
import json
import uuid
from datetime import datetime, timezone

from db.database import get_conn, _gen_short_id


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


def create_conversation(user_id: str, model: str, title: str | None = None) -> tuple[str, str]:
    conv_id = str(uuid.uuid4())
    short_id = _gen_short_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, short_id, user_id, model, title) VALUES (?, ?, ?, ?, ?)",
            (conv_id, short_id, user_id, model, title),
        )
    return conv_id, short_id


def get_conversation_by_short_id(short_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE short_id = ?", (short_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["messages"] = json.loads(data["messages"])
    return data


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


def update_conversation_title(conv_id: str, title: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id)
        )


def delete_conversation(conv_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    return cur.rowcount > 0


def list_conversations(user_id: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, short_id, title, model, created_at, updated_at "
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


# ── Scheduled Tasks ───────────────────────────────────────────────────────────


def create_schedule(name: str, task: str, cron: str, model: str, active_mcps: list) -> dict:
    sid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scheduled_tasks (id, name, task, cron, model, active_mcps) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, name, task, cron, model, json.dumps(active_mcps)),
        )
    return get_schedule(sid)


def list_schedules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["active_mcps"] = json.loads(d["active_mcps"])
        result.append(d)
    return result


def get_schedule(sid: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["active_mcps"] = json.loads(d["active_mcps"])
    return d


def update_schedule(sid: str, **kwargs) -> dict | None:
    allowed = {"name", "task", "cron", "model", "active_mcps", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_schedule(sid)
    if "active_mcps" in fields:
        fields["active_mcps"] = json.dumps(fields["active_mcps"])
    with get_conn() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE scheduled_tasks SET {set_clause} WHERE id = ?",
            [*fields.values(), sid],
        )
    return get_schedule(sid)


def record_schedule_run(sid: str, result: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET last_run = datetime('now'), last_result = ? WHERE id = ?",
            (result[:2000], sid),
        )


def delete_schedule(sid: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (sid,))
    return cur.rowcount > 0
