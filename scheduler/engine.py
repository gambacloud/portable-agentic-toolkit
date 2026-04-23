"""
Scheduled task engine — runs agent tasks on a cron schedule.
HITL is auto-approved for scheduled tasks (no user present).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import db.queries as q
from utils.logger import get_logger

log = get_logger(__name__)

_MCP_SERVERS_DIR = Path(__file__).parent.parent / "bin" / "mcp_servers"


class SchedulerEngine:
    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self):
        schedules = q.list_schedules()
        for s in schedules:
            if s["enabled"]:
                self._add_job(s)
        self._scheduler.start()
        log.info("Scheduler started — %d job(s) registered", len([s for s in schedules if s["enabled"]]))

    def add_or_replace(self, schedule: dict):
        self._remove_job(schedule["id"])
        if schedule.get("enabled", True):
            self._add_job(schedule)

    def remove(self, sid: str):
        self._remove_job(sid)

    def run_now(self, sid: str):
        schedule = q.get_schedule(sid)
        if not schedule:
            raise ValueError(f"Schedule {sid} not found")
        self._execute(sid)

    def shutdown(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _add_job(self, schedule: dict):
        try:
            trigger = CronTrigger.from_crontab(schedule["cron"], timezone="UTC")
            self._scheduler.add_job(
                self._execute,
                trigger=trigger,
                id=schedule["id"],
                args=[schedule["id"]],
                replace_existing=True,
            )
            log.info("Scheduled job '%s' (%s) cron=%s", schedule["name"], schedule["id"][:8], schedule["cron"])
        except Exception as exc:
            log.error("Failed to add job '%s': %s", schedule["name"], exc)

    def _remove_job(self, sid: str):
        try:
            self._scheduler.remove_job(sid)
        except Exception:
            pass

    def _execute(self, sid: str):
        schedule = q.get_schedule(sid)
        if not schedule:
            log.warning("Schedule %s not found at execution time", sid)
            return

        log.info("Running scheduled task '%s' — model=%s", schedule["name"], schedule["model"])
        try:
            result = _run_task(
                task=schedule["task"],
                model=schedule["model"],
                active_mcps=schedule["active_mcps"] or None,
            )
            q.record_schedule_run(sid, result)
            q.create_schedule_run(sid, schedule["name"], result)
            log.info("Scheduled task '%s' done — result_len=%d", schedule["name"], len(result))

            # Dispatch to outputs
            active_outputs = schedule.get("active_outputs", [])
            for oid in active_outputs:
                output = q.get_output(oid)
                if output:
                    success, msg = send_to_output(output, f"✅ Scheduled task '{schedule['name']}' completed:\n\n{result}")
                    if not success:
                        log.error("Failed to send output '%s': %s", output['name'], msg)

        except Exception as exc:
            error_msg = f"Error: {exc}"
            q.record_schedule_run(sid, error_msg)
            q.create_schedule_run(sid, schedule["name"], error_msg)
            log.error("Scheduled task '%s' failed: %s", schedule["name"], exc, exc_info=True)

            # Dispatch to outputs
            active_outputs = schedule.get("active_outputs", [])
            for oid in active_outputs:
                output = q.get_output(oid)
                if output:
                    send_to_output(output, f"❌ Scheduled task '{schedule['name']}' failed:\n\n{exc}")


def send_to_output(output: dict, message: str) -> tuple[bool, str]:
    import urllib.request
    import json
    
    otype = output.get("type")
    config = output.get("config", {})
    
    if otype == "telegram":
        token = config.get("token")
        chat_id = config.get("chat_id")
        if not token or not chat_id:
            return False, "Missing token or chat_id"
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 200:
                    return True, "OK"
                else:
                    return False, f"HTTP {resp.status}"
        except Exception as e:
            return False, str(e)
            
    # other types later
    return False, f"Unsupported output type: {otype}"


def _run_task(task: str, model: str, active_mcps: Optional[list]) -> str:
    from agents.runner import build_crew
    from mcp_tools.registry import MCPRegistry

    async def _do_task():
        registry = MCPRegistry(_MCP_SERVERS_DIR)
        await registry.discover()

        def _auto_allow(prompt: str, choices: list[str]) -> str:
            log.info("Scheduled task auto-approved: %s", choices[0])
            return choices[0]

        t_defs, t_map = registry.get_runner_tools(_auto_allow, only_servers=active_mcps)

        from mcp_tools.installer import make_runner_installer_tool
        inst_def, inst_fn = make_runner_installer_tool(_auto_allow)
        t_defs.append(inst_def)
        t_map["install_mcp_server"] = inst_fn

        runner = build_crew(model=model, tool_defs=t_defs, tool_map=t_map)

        # Run synchronous kickoff in a thread to keep async loop responsive for tools
        result = await asyncio.to_thread(runner.kickoff, {"task": task})

        await registry.close()
        return result

    return asyncio.run(_do_task())


# Module-level singleton
_engine: Optional[SchedulerEngine] = None


def get_engine() -> SchedulerEngine:
    global _engine
    if _engine is None:
        _engine = SchedulerEngine()
    return _engine
