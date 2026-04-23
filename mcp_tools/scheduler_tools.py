"""Agent tools for creating and managing scheduled tasks from chat."""
from __future__ import annotations

import db.queries as q
from utils.logger import get_logger

log = get_logger(__name__)


def make_scheduler_tools(model: str, active_mcps: list) -> tuple[list[dict], dict]:
    """Return (tool_defs, tool_map) for scheduler management tools."""

    tool_defs = [
        {
            "type": "function",
            "function": {
                "name": "create_schedule",
                "description": (
                    "Create a new scheduled task that runs automatically on a cron schedule. "
                    "Convert natural language like 'every day at 9am' to a cron expression (UTC). "
                    "Examples: '0 9 * * *' = daily at 9am, '0 9 * * 1' = every Monday at 9am, "
                    "'0 */6 * * *' = every 6 hours, '30 8 * * 1-5' = weekdays at 8:30am."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short descriptive name for this schedule (e.g. 'Daily email summary')",
                        },
                        "task": {
                            "type": "string",
                            "description": "Full description of what the agent should do when this schedule fires",
                        },
                        "cron": {
                            "type": "string",
                            "description": "Cron expression with 5 fields: minute hour day month weekday",
                        },
                    },
                    "required": ["name", "task", "cron"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_schedules",
                "description": "List all scheduled tasks and their current status.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_schedule",
                "description": "Delete a scheduled task by its ID (full or 8-char prefix).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "schedule_id": {
                            "type": "string",
                            "description": "The ID of the schedule to delete (full UUID or 8-char prefix)",
                        },
                    },
                    "required": ["schedule_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "toggle_schedule",
                "description": "Enable or disable a scheduled task without deleting it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "schedule_id": {
                            "type": "string",
                            "description": "The ID of the schedule (full UUID or 8-char prefix)",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "True to enable, False to disable/pause",
                        },
                    },
                    "required": ["schedule_id", "enabled"],
                },
            },
        },
    ]

    def _resolve(schedule_id: str) -> dict | None:
        schedules = q.list_schedules()
        return next(
            (s for s in schedules if s["id"] == schedule_id or s["id"].startswith(schedule_id)),
            None,
        )

    def _create_schedule(name: str, task: str, cron: str) -> str:
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(cron)
        except Exception as exc:
            return f"Invalid cron expression '{cron}': {exc}. Please fix and try again."
        try:
            schedule = q.create_schedule(name, task, cron, model, active_mcps)
            from scheduler.engine import get_engine
            get_engine().add_or_replace(schedule)
            log.info("Schedule created from chat: '%s' cron=%s model=%s", name, cron, model)
            mcps_note = f", MCPs: {', '.join(active_mcps)}" if active_mcps else ", no MCP servers"
            return (
                f"✅ Schedule **{name}** created (ID: `{schedule['id'][:8]}…`).\n"
                f"Cron: `{cron}` (UTC) · Model: `{model}`{mcps_note}.\n"
                f"Task: _{task}_"
            )
        except Exception as exc:
            log.error("Failed to create schedule: %s", exc)
            return f"Failed to create schedule: {exc}"

    def _list_schedules() -> str:
        try:
            schedules = q.list_schedules()
            if not schedules:
                return "No scheduled tasks found. Create one with create_schedule."
            lines = []
            for s in schedules:
                status = "✅ enabled" if s["enabled"] else "⏸ paused"
                last = s["last_run"] or "never"
                lines.append(
                    f"- **{s['name']}** ({status})\n"
                    f"  ID: `{s['id'][:8]}…` · Cron: `{s['cron']}` · Last run: {last}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"Failed to list schedules: {exc}"

    def _delete_schedule(schedule_id: str) -> str:
        match = _resolve(schedule_id)
        if not match:
            return f"No schedule found with ID '{schedule_id}'."
        try:
            from scheduler.engine import get_engine
            get_engine().remove(match["id"])
            q.delete_schedule(match["id"])
            return f"Schedule **{match['name']}** deleted."
        except Exception as exc:
            return f"Failed to delete schedule: {exc}"

    def _toggle_schedule(schedule_id: str, enabled: bool) -> str:
        match = _resolve(schedule_id)
        if not match:
            return f"No schedule found with ID '{schedule_id}'."
        try:
            updated = q.update_schedule(match["id"], enabled=enabled)
            from scheduler.engine import get_engine
            get_engine().add_or_replace(updated)
            state = "enabled" if enabled else "paused"
            return f"Schedule **{match['name']}** {state}."
        except Exception as exc:
            return f"Failed to toggle schedule: {exc}"

    tool_map = {
        "create_schedule": _create_schedule,
        "list_schedules": lambda: _list_schedules(),
        "delete_schedule": _delete_schedule,
        "toggle_schedule": _toggle_schedule,
    }

    return tool_defs, tool_map
