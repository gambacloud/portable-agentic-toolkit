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


def get_user_by_username(username: str) -> dict | None:
    if not username:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def create_account(user_id: str, username: str, password_hash: str, role: str = "employee",
                    department: str | None = None, manager_id: str | None = None) -> dict:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (id, name, username, password_hash, role, department, manager_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, username, password_hash, role, department, manager_id),
        )
    return get_user(user_id)


def set_password(user_id: str, password_hash: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


# ── Hierarchy: role / department / manager ──────────────────────────────────


def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def update_user_hierarchy(
    user_id: str,
    role: str | None = None,
    department: str | None = None,
    manager_id: str | None = None,
) -> dict | None:
    fields, params = [], []
    if role is not None:
        fields.append("role = ?")
        params.append(role)
    if department is not None:
        fields.append("department = ?")
        params.append(department)
    if manager_id is not None:
        fields.append("manager_id = ?")
        params.append(None if manager_id == "" else manager_id)
    if not fields:
        return get_user(user_id)
    params.append(user_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
    return get_user(user_id)


def list_direct_reports(manager_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE manager_id = ? ORDER BY name", (manager_id,)).fetchall()
    return [dict(r) for r in rows]


def list_department_members(department: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE department = ? ORDER BY name", (department,)).fetchall()
    return [dict(r) for r in rows]


# ── Personal access tokens (for non-interactive/API callers) ────────────────


def create_api_token(token_id: str, user_id: str, name: str, token_hash: str) -> dict:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_tokens (id, user_id, name, token_hash) VALUES (?, ?, ?, ?)",
            (token_id, user_id, name, token_hash),
        )
        row = conn.execute("SELECT id, user_id, name, created_at FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
    return dict(row)


def get_user_id_for_token_hash(token_hash: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT user_id FROM api_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
    return row[0] if row else None


def list_api_tokens(user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_api_token(token_id: str, user_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user_id))
    return cur.rowcount > 0


# ── Per-model usage ───────────────────────────────────────────────────────────


def get_model_usage(user_id: str, model: str, period_key: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT token_usage FROM model_usage WHERE user_id = ? AND model = ? AND period_key = ?",
            (user_id, model, period_key),
        ).fetchone()
    return row[0] if row else 0


def add_model_usage(user_id: str, model: str, period_key: str, tokens: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO model_usage (user_id, model, period_key, token_usage) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, model, period_key) DO UPDATE SET
                 token_usage = token_usage + excluded.token_usage""",
            (user_id, model, period_key, tokens),
        )


def sum_model_usage(user_id: str, model: str) -> int:
    """Total usage recorded for a model across every period_key (used for session-scoped limits)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(token_usage), 0) FROM model_usage WHERE user_id = ? AND model = ?",
            (user_id, model),
        ).fetchone()
    return row[0] if row else 0


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


def delete_empty_conversations(user_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE user_id = ? AND json_array_length(messages) = 0",
            (user_id,),
        )
    return cur.rowcount


def derive_title(content: str) -> str:
    content = " ".join(content.split())
    if len(content) <= 50:
        return content
    truncated = content[:50].rsplit(" ", 1)[0]
    return f"{truncated}…"


def backfill_conversation_titles() -> int:
    """One-time fixup: give untitled-but-non-empty conversations a real title
    derived from their first user message, instead of the generic date fallback."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, messages FROM conversations "
            "WHERE title IS NULL AND json_array_length(messages) > 0"
        ).fetchall()
        updated = 0
        for row in rows:
            msgs = json.loads(row["messages"])
            first_user = next((m for m in msgs if m.get("role") == "user"), None)
            if not first_user or not first_user.get("content", "").strip():
                continue
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (derive_title(first_user["content"]), row["id"]),
            )
            updated += 1
    return updated


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
    if active_outputs is None:
        active_outputs = []
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
