"""
CrewAI crew builder.
Wraps a single versatile agent whose role/goal/backstory comes from
config/agents.yaml, so you can tune behaviour without touching code.
"""
from __future__ import annotations

import json
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
    profile_id: Optional[str] = None,
) -> "_DeferredCrew":
    log.info("Building crew — model=%s tools=%d profile=%s", model, len(tools), profile_id)

    llm = LLM(
        model=f"ollama/{model}",
        base_url="http://localhost:11434",
        temperature=0.1,
        max_tokens=4096,
    )

    company_dna = _load_company_dna()
    cfg = _agent_config(profile_id=profile_id)
    log.debug("Agent role: %s", cfg["role"])

    backstory = cfg["backstory"]
    if company_dna:
        backstory = f"{company_dna}\n\n{backstory}"

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
        backstory=backstory,
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        step_callback=step_callback,
    )

    return _DeferredCrew(agent, model, on_step=on_step)


def build_hierarchical_crew(
    model: str,
    tools: list,
    on_step: Optional[Callable[[str, str], None]] = None,
    profile_id: Optional[str] = None,
) -> "_DeferredCrew":
    log.info("Building hierarchical crew — model=%s tools=%d profile=%s", model, len(tools), profile_id)

    llm = LLM(
        model=f"ollama/{model}",
        base_url="http://localhost:11434",
        temperature=0.1,
        max_tokens=4096,
    )

    company_dna = _load_company_dna()
    cfg = _agent_config(profile_id=profile_id)

    def step_callback(agent_output):
        if not (hasattr(agent_output, "tool") and agent_output.tool and on_step):
            return
        tool = agent_output.tool
        raw = getattr(agent_output, "tool_input", "")
        try:
            inp = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            inp = {}
        if tool == "delegate_work_to_coworker":
            coworker = inp.get("coworker", "?")
            task = (inp.get("task", "") or str(raw))[:80]
            on_step("🤝 Delegating", f"→ **{coworker}**: {task}")
        elif tool == "ask_question_to_coworker":
            coworker = inp.get("coworker", "?")
            question = (inp.get("question", "") or str(raw))[:80]
            on_step("❓ Asking", f"→ **{coworker}**: {question}")
        else:
            on_step(f"🔧 {tool}", str(raw)[:120])

    def _make_agent(role: str, goal: str, backstory: str, agent_tools: list) -> Agent:
        full_backstory = f"{company_dna}\n\n{backstory}" if company_dna else backstory
        return Agent(
            role=role,
            goal=goal,
            backstory=full_backstory,
            llm=llm,
            tools=agent_tools,
            verbose=True,
            allow_delegation=False,
            max_iter=5,
            step_callback=step_callback,
        )

    crew_cfgs = _load_crew_agent_configs()
    if not crew_cfgs:
        log.warning("No crew_agents in agents.yaml — falling back to single agent")
        return build_crew(model=model, tools=tools, on_step=on_step, profile_id=profile_id)

    worker_agents = [
        _make_agent(c["role"], c["goal"], c["backstory"], tools)
        for c in crew_cfgs
    ]

    manager_backstory = (
        f"{company_dna}\n\n" if company_dna else ""
    ) + (
        cfg["backstory"] + "\n\nAs manager, break complex tasks into subtasks and "
        "delegate to the right specialist. Synthesise their outputs into a final answer."
    )
    manager = Agent(
        role="Team Manager — " + cfg["role"],
        goal=cfg["goal"],
        backstory=manager_backstory,
        llm=llm,
        tools=[],
        verbose=True,
        allow_delegation=True,
        step_callback=step_callback,
    )

    return _DeferredCrew(worker_agents, model, manager=manager, on_step=on_step)


# ── Internal ─────────────────────────────────────────────────────────────────


class _DeferredCrew:
    def __init__(self, agent, model: str, manager: Optional[Agent] = None, on_step: Optional[Callable] = None):
        self._agent = agent
        self._model = model
        self._manager = manager
        self._on_step = on_step

    def kickoff(self, inputs: dict) -> str:
        task_description = inputs.get("task", "")
        on_step = self._on_step
        hierarchical = self._manager is not None
        log.info("Kickoff — model=%s task_len=%d hierarchical=%s", self._model, len(task_description), hierarchical)
        log.debug("Task: %s", task_description[:200])

        if on_step:
            mode = "multi-agent" if hierarchical else "single agent"
            on_step(f"🚀 Starting ({mode})", f"model: {self._model}")

        def task_done(task_output):
            if not on_step:
                return
            agent_name = (getattr(task_output, "agent", None) or "Agent")
            if hasattr(agent_name, "role"):
                agent_name = agent_name.role
            on_step(f"✅ {str(agent_name)[:50]}", "task complete")

        if hierarchical:
            agents = self._agent  # list of workers
            task = Task(
                description=task_description,
                expected_output=(
                    "A clear, accurate, and helpful response. "
                    "If you used tools, summarise what you found."
                ),
            )
            crew = Crew(
                agents=agents,
                tasks=[task],
                process=Process.hierarchical,
                manager_agent=self._manager,
                verbose=True,
                task_callback=task_done,
            )
        else:
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
                task_callback=task_done,
            )

        t_start = time.perf_counter()
        try:
            result = crew.kickoff()
            elapsed = time.perf_counter() - t_start
            raw = result.raw if hasattr(result, "raw") else str(result)
            raw = _sanitize_output(raw)
            log.info("Crew completed in %.2fs — result_len=%d", elapsed, len(raw))
            return raw
        except Exception as exc:
            elapsed = time.perf_counter() - t_start
            log.error("Crew failed after %.2fs — %s", elapsed, exc, exc_info=True)
            raise


def _sanitize_output(raw: str) -> str:
    """Replace JSON tool-call hallucinations with a plain error message."""
    stripped = raw.strip()
    if stripped.startswith("{") and '"parameters"' in stripped:
        log.warning("LLM returned raw JSON as final answer — replacing with error message")
        return "I was unable to complete the task. The model returned an invalid response."
    return raw


def _load_crew_agent_configs() -> list[dict]:
    if not CONFIG_PATH.exists():
        return []
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return [
            {
                "role": c.get("role", "Specialist"),
                "goal": c.get("goal", ""),
                "backstory": c.get("backstory", ""),
            }
            for c in data.get("crew_agents", [])
        ]
    except Exception as exc:
        log.warning("Failed to load crew_agents: %s", exc)
        return []


def _load_company_dna() -> str:
    if not CONFIG_PATH.exists():
        return ""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        dna = data.get("company_dna", "").strip()
        if dna:
            log.debug("Company DNA loaded (%d chars)", len(dna))
        return dna
    except Exception as exc:
        log.warning("Failed to load company_dna: %s", exc)
        return ""


def _agent_config(profile_id: Optional[str] = None) -> dict:
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

    # Priority 1: explicitly selected profile
    if profile_id:
        try:
            from db.queries import get_profile
            profile = get_profile(profile_id)
            if profile:
                log.debug("Using selected profile: %s", profile.get("name"))
                return {
                    "role": profile.get("role") or defaults["role"],
                    "goal": profile.get("goal") or defaults["goal"],
                    "backstory": profile.get("backstory") or defaults["backstory"],
                }
        except Exception as exc:
            log.debug("Selected profile lookup failed: %s", exc)

    # Priority 2: default system_profile from DB
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
