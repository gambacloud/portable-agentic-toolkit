"""
CrewAI crew builder.
Wraps a single versatile agent whose role/goal/backstory comes from
config/agents.yaml, so you can tune behaviour without touching code.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import yaml
from crewai import Agent, Crew, LLM, Process, Task

from utils.logger import get_logger

log = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "agents.yaml"


# ── Public API ───────────────────────────────────────────────────────────────


def build_crew(
    model: str,
    tools: list,
    on_step: Optional[Callable[[str, str], None]] = None,
) -> "_DeferredCrew":
    log.info("Building crew — model=%s tools=%d", model, len(tools))

    llm = LLM(
        model=f"ollama/{model}",
        base_url="http://localhost:11434",
        temperature=0.1,
    )

    cfg = _agent_config()
    log.debug("Agent role: %s", cfg["role"])

    def step_callback(agent_output):
        if hasattr(agent_output, "tool") and agent_output.tool:
            tool_input = getattr(agent_output, "tool_input", "")
            log.debug(
                "Agent step — tool=%s input=%s",
                agent_output.tool,
                str(tool_input)[:120],
            )
            if on_step:
                on_step(f"Tool: {agent_output.tool}", str(tool_input))

    agent = Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
        step_callback=step_callback,
    )

    return _DeferredCrew(agent, model)


# ── Internal ─────────────────────────────────────────────────────────────────


class _DeferredCrew:
    def __init__(self, agent: Agent, model: str):
        self._agent = agent
        self._model = model

    def kickoff(self, inputs: dict) -> str:
        task_description = inputs.get("task", "")
        log.info("Kickoff — model=%s task_len=%d", self._model, len(task_description))
        log.debug("Task: %s", task_description[:200])

        task = Task(
            description=task_description,
            expected_output=(
                "A clear, accurate, and helpful response. "
                "If you used tools, summarise what you found."
            ),
            agent=self._agent,
        )
        crew = Crew(
            agents=[self._agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
        )

        t_start = time.perf_counter()
        try:
            result = crew.kickoff()
            elapsed = time.perf_counter() - t_start
            raw = result.raw if hasattr(result, "raw") else str(result)
            log.info("Crew completed in %.2fs — result_len=%d", elapsed, len(raw))
            return raw
        except Exception as exc:
            elapsed = time.perf_counter() - t_start
            log.error("Crew failed after %.2fs — %s", elapsed, exc, exc_info=True)
            raise


def _agent_config() -> dict:
    defaults = {
        "role": "General Purpose AI Assistant",
        "goal": (
            "Help the user accomplish their tasks efficiently and accurately, "
            "using available tools when appropriate."
        ),
        "backstory": (
            "You are a thoughtful AI assistant running entirely on the user's local machine. "
            "You have access to various tools via the Model Context Protocol (MCP). "
            "You reason step by step, use tools when they help, and always ask for "
            "confirmation before taking irreversible actions."
        ),
    }

    # Priority 1: default system_profile from DB
    try:
        from db.queries import get_default_profile
        profile = get_default_profile()
        if profile:
            cfg = {
                "role": profile.get("role") or defaults["role"],
                "goal": profile.get("goal") or defaults["goal"],
                "backstory": profile.get("backstory") or defaults["backstory"],
            }
            log.debug("Using system profile from DB: %s", profile.get("name"))
            return cfg
    except Exception as exc:
        log.debug("DB profile lookup skipped: %s", exc)

    # Priority 2: config/agents.yaml
    if not CONFIG_PATH.exists():
        log.debug("No agents.yaml found — using defaults")
        return defaults

    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        agents = data.get("agents", [])
        if agents:
            cfg = agents[0]
            return {
                "role": cfg.get("role", defaults["role"]),
                "goal": cfg.get("goal", defaults["goal"]),
                "backstory": cfg.get("backstory", defaults["backstory"]),
            }
    except Exception as exc:
        log.warning("Failed to load agents.yaml (%s) — using defaults", exc)

    return defaults
