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


def create_schedule(name: str, task: str, cron: str, model: str, active_mcps: list, active_outputs: list = None) -> dict:
    if active_outputs is None: active_outputs = []
    sid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scheduled_tasks (id, name, task, cron, model, active_mcps, active_outputs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, name, task, cron, model, json.dumps(active_mcps), json.dumps(active_outputs)),
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
        d["active_outputs"] = json.loads(d.get("active_outputs", "[]"))
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
    d["active_outputs"] = json.loads(d.get("active_outputs", "[]"))
    return d


def update_schedule(sid: str, **kwargs) -> dict | None:
    allowed = {"name", "task", "cron", "model", "active_mcps", "active_outputs", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_schedule(sid)
    if "active_mcps" in fields:
        fields["active_mcps"] = json.dumps(fields["active_mcps"])
    if "active_outputs" in fields:
        fields["active_outputs"] = json.dumps(fields["active_outputs"])
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


# ── Outputs ───────────────────────────────────────────────────────────────────


def list_outputs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM outputs ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d["config"])
        result.append(d)
    return result


def get_output(output_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM outputs WHERE id = ?", (output_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config"])
    return d


def create_output(name: str, type: str, config: dict) -> dict:
    oid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO outputs (id, name, type, config) VALUES (?, ?, ?, ?)",
            (oid, name, type, json.dumps(config)),
        )
    return get_output(oid)


def update_output(output_id: str, **kwargs) -> dict | None:
    allowed = {"name", "type", "config"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_output(output_id)
    if "config" in fields:
        fields["config"] = json.dumps(fields["config"])
    with get_conn() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE outputs SET {set_clause} WHERE id = ?", [*fields.values(), output_id])
    return get_output(output_id)


def delete_output(output_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM outputs WHERE id = ?", (output_id,))
    return cur.rowcount > 0


# ── Schedule Runs ─────────────────────────────────────────────────────────────


def create_schedule_run(schedule_id: str, schedule_name: str, result: str) -> None:
    run_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO schedule_runs (id, schedule_id, schedule_name, result) VALUES (?, ?, ?, ?)",
            (run_id, schedule_id, schedule_name, result[:4000]),
        )


def list_unnotified_runs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_runs WHERE notified = 0 ORDER BY ran_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def mark_runs_notified(run_ids: list[str]) -> None:
    if not run_ids:
        return
    placeholders = ",".join("?" * len(run_ids))
    with get_conn() as conn:
        conn.execute(
            f"UPDATE schedule_runs SET notified = 1 WHERE id IN ({placeholders})",
            run_ids,
        )


def list_schedule_runs(sid: str | None = None, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        if sid:
            rows = conn.execute(
                "SELECT * FROM schedule_runs WHERE schedule_id = ? ORDER BY ran_at DESC LIMIT ?",
                (sid, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM schedule_runs ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]
