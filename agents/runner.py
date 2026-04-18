"""
Direct Ollama agent runner — replaces CrewAI for fast, reliable tool-calling.

Exposes the same build_crew / build_hierarchical_crew interface as crew.py
so app.py needs minimal changes.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import ollama

from utils.logger import get_logger

log = get_logger(__name__)


# ── Public API (same interface as crew.py) ────────────────────────────────────


def build_crew(
    model: str,
    tool_defs: list,
    tool_map: dict,
    on_step: Optional[Callable] = None,
    profile_id: Optional[str] = None,
) -> "_Runner":
    from agents.crew import _agent_config, _load_company_dna

    cfg = _agent_config(profile_id=profile_id)
    dna = _load_company_dna()
    backstory = f"{dna}\n\n{cfg['backstory']}" if dna else cfg["backstory"]
    log.info("Building single agent — model=%s tools=%d profile=%s", model, len(tool_defs), profile_id)

    agent = _OllamaAgent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=backstory,
        model=model,
        tool_defs=tool_defs,
        tool_map=tool_map,
        on_step=on_step,
    )
    return _Runner([agent], on_step=on_step, model=model)


def build_hierarchical_crew(
    model: str,
    tool_defs: list,
    tool_map: dict,
    on_step: Optional[Callable] = None,
    profile_id: Optional[str] = None,
) -> "_Runner":
    from agents.crew import _agent_config, _load_company_dna, _load_crew_agent_configs

    cfg = _agent_config(profile_id=profile_id)
    dna = _load_company_dna()
    crew_cfgs = _load_crew_agent_configs()

    if not crew_cfgs:
        log.warning("No crew_agents in agents.yaml — falling back to single agent")
        return build_crew(model=model, tool_defs=tool_defs, tool_map=tool_map, on_step=on_step, profile_id=profile_id)

    log.info("Building team — model=%s workers=%d tools=%d", model, len(crew_cfgs), len(tool_defs))

    workers = [
        _OllamaAgent(
            role=c["role"],
            goal=c["goal"],
            backstory=f"{dna}\n\n{c['backstory']}" if dna else c["backstory"],
            model=model,
            tool_defs=tool_defs,
            tool_map=tool_map,
            on_step=on_step,
        )
        for c in crew_cfgs
    ]

    manager_cfg = {
        "role": "Team Manager — " + cfg["role"],
        "goal": cfg["goal"],
        "backstory": (f"{dna}\n\n" if dna else "") + cfg["backstory"],
    }
    return _Runner(workers, manager_cfg=manager_cfg, on_step=on_step, model=model)


# ── Agent ─────────────────────────────────────────────────────────────────────


class _OllamaAgent:
    def __init__(
        self,
        role: str,
        goal: str,
        backstory: str,
        model: str,
        tool_defs: list,
        tool_map: dict,
        on_step: Optional[Callable] = None,
        max_iter: int = 6,
    ):
        self.role = role
        self.model = model
        self.tool_defs = tool_defs
        self.tool_map = tool_map
        self.on_step = on_step
        self.max_iter = max_iter
        self._system = (
            f"You are {role}.\nGoal: {goal}\n\n{backstory}"
        )

    def run(self, task: str) -> str:
        messages: list = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": task},
        ]

        for iteration in range(self.max_iter):
            try:
                resp = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=self.tool_defs if self.tool_defs else None,
                )
            except Exception as exc:
                log.error("Ollama chat error: %s", exc)
                return f"Error communicating with model: {exc}"

            msg = resp.message
            messages.append(msg)

            if not msg.tool_calls:
                return msg.content or ""

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                log.debug("Tool call — %s(%s)", fn_name, str(fn_args)[:80])

                if self.on_step:
                    self.on_step(f"🔧 {fn_name}", str(fn_args)[:120])

                if fn_name in self.tool_map:
                    try:
                        result = self.tool_map[fn_name](**fn_args)
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                        log.warning("Tool '%s' raised: %s", fn_name, exc)
                else:
                    result = f"Unknown tool: {fn_name}"
                    log.warning("Unknown tool requested: %s", fn_name)

                log.debug("Tool result: %s", str(result)[:200])
                messages.append({"role": "tool", "content": str(result)})

        # Max iterations reached — ask for final answer
        log.warning("Max iterations reached for agent '%s' — requesting final answer", self.role)
        messages.append({"role": "user", "content": "Please provide your final answer now based on what you have so far."})
        try:
            resp = ollama.chat(model=self.model, messages=messages)
            return resp.message.content or "Unable to complete task within iteration limit."
        except Exception as exc:
            return f"Error: {exc}"


# ── Runner (orchestrator) ──────────────────────────────────────────────────────


class _Runner:
    def __init__(
        self,
        agents: list[_OllamaAgent],
        manager_cfg: Optional[dict] = None,
        on_step: Optional[Callable] = None,
        model: Optional[str] = None,
    ):
        self._agents = agents
        self._manager_cfg = manager_cfg
        self._on_step = on_step
        self._model = model

    def kickoff(self, inputs: dict) -> str:
        task = inputs.get("task", "")
        on_step = self._on_step
        hierarchical = self._manager_cfg is not None and len(self._agents) > 1

        log.info(
            "Runner kickoff — model=%s agents=%d hierarchical=%s task_len=%d",
            self._model, len(self._agents), hierarchical, len(task),
        )

        if on_step:
            mode = "multi-agent" if hierarchical else "single agent"
            on_step(f"🚀 Starting ({mode})", f"model: {self._model}")

        t_start = time.perf_counter()
        try:
            result = self._run_team(task) if hierarchical else self._agents[0].run(task)
            elapsed = time.perf_counter() - t_start
            log.info("Runner completed in %.2fs — result_len=%d", elapsed, len(result))
            if on_step:
                on_step("✅ Done", f"completed in {elapsed:.1f}s")
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - t_start
            log.error("Runner failed after %.2fs — %s", elapsed, exc, exc_info=True)
            raise

    def _run_team(self, task: str) -> str:
        on_step = self._on_step
        context_parts: list[str] = []

        for agent in self._agents:
            log.debug("Delegating to: %s", agent.role)
            if on_step:
                on_step("🤝 Delegating", f"→ **{agent.role}**: {task[:80]}")

            # Each worker sees the task + all previous results
            if context_parts:
                prompt = (
                    f"Previous team work:\n"
                    + "\n\n".join(context_parts)
                    + f"\n\nYour task (as {agent.role}): {task}"
                )
            else:
                prompt = task

            result = agent.run(prompt)
            context_parts.append(f"**{agent.role}**:\n{result}")

            if on_step:
                on_step(f"✅ {agent.role[:40]}", "done")

        # Manager synthesizes all worker outputs
        from agents.crew import _agent_config, _load_company_dna
        cfg = _agent_config()
        dna = _load_company_dna()
        mcfg = self._manager_cfg

        if on_step:
            on_step("🧠 Synthesizing", "manager combining results")

        manager = _OllamaAgent(
            role=mcfg["role"],
            goal=mcfg["goal"],
            backstory=(f"{dna}\n\n" if dna else "") + mcfg["backstory"],
            model=self._model,
            tool_defs=[],
            tool_map={},
            on_step=on_step,
        )

        synthesis_prompt = (
            "Here are the outputs from your team:\n\n"
            + "\n\n---\n\n".join(context_parts)
            + f"\n\nOriginal task: {task}\n\n"
            "Synthesize a final, clear, and complete answer."
        )
        return manager.run(synthesis_prompt)
