"""
CrewAI crew builder.
Wraps a single versatile agent whose role/goal/backstory comes from
config/agents.yaml, so you can tune behaviour without touching code.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Callable, Optional

from crewai import Agent, Crew, LLM, Process, Task

CONFIG_PATH = Path(__file__).parent.parent / "config" / "agents.yaml"


# ── Public API ───────────────────────────────────────────────────────────────


def build_crew(
    model: str,
    tools: list,
    on_step: Optional[Callable[[str, str], None]] = None,
) -> "_DeferredCrew":
    """
    Returns a crew-like object whose .kickoff(inputs) accepts a single
    'task' key, constructs a CrewAI Task dynamically, and returns the
    raw result string.
    """
    llm = LLM(
        model=f"ollama/{model}",
        base_url="http://localhost:11434",
        temperature=0.1,
    )

    cfg = _agent_config()

    def step_callback(agent_output):
        """Forward each ReAct step to the Chainlit UI as a Step."""
        if on_step and hasattr(agent_output, "tool") and agent_output.tool:
            tool_input = getattr(agent_output, "tool_input", "")
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

    return _DeferredCrew(agent)


# ── Internal ─────────────────────────────────────────────────────────────────


class _DeferredCrew:
    """Creates a fresh Crew per kickoff() call — safe for multi-turn chat."""

    def __init__(self, agent: Agent):
        self._agent = agent

    def kickoff(self, inputs: dict) -> str:
        task_description = inputs.get("task", "")
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
        result = crew.kickoff()
        return result.raw if hasattr(result, "raw") else str(result)


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

    if not CONFIG_PATH.exists():
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
    except Exception:
        pass

    return defaults
