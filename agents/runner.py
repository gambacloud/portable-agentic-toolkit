"""
Direct Ollama agent runner — replaces CrewAI for fast, reliable tool-calling.

Exposes the same build_crew / build_hierarchical_crew interface as crew.py
so app.py needs minimal changes.
"""
from __future__ import annotations

import json
import re
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
        if self.model.startswith("groq/"):
            return self._run_litellm(task)
        return self._run_ollama(task)

    def _run_ollama(self, task: str) -> str:
        messages: list = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": task},
        ]

        for _ in range(self.max_iter):
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
                raw_args = tc.function.arguments or {}

                parsed = _parse_tool_args(raw_args)
                if isinstance(parsed, str):
                    log.warning("Tool call JSON parse failed for %s", fn_name)
                    if self.on_step:
                        self.on_step(f"⚠️ {fn_name}", "JSON format error — asking model to retry")
                    messages.append({"role": "tool", "content": parsed})
                    continue

                fn_args = parsed
                log.debug("Tool call — %s(%s)", fn_name, str(fn_args)[:80])
                if self.on_step:
                    self.on_step(f"🔧 {fn_name}", str(fn_args)[:120])
                result = self._call_tool(fn_name, fn_args)
                messages.append({"role": "tool", "content": str(result)})

        log.warning("Max iterations reached — requesting final answer")
        messages.append({"role": "user", "content": "Please provide your final answer now."})
        try:
            resp = ollama.chat(model=self.model, messages=messages)
            return resp.message.content or "Unable to complete task within iteration limit."
        except Exception as exc:
            return f"Error: {exc}"

    def _litellm_chat(self, messages: list, tools: list | None):
        import litellm
        for attempt in range(4):
            try:
                return litellm.completion(
                    model=self.model,
                    messages=messages,
                    tools=tools or None,
                )
            except Exception as exc:
                err = str(exc).lower()
                if "rate_limit" in err or "rate limit" in err or "429" in err:
                    wait = 15 * (attempt + 1)
                    log.warning("Rate limit — waiting %ds (attempt %d)", wait, attempt + 1)
                    if self.on_step:
                        self.on_step("⏳ Rate limit", f"waiting {wait}s…")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("Rate limit persists after retries — try again in a minute.")

    def _run_litellm(self, task: str) -> str:
        messages: list = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": task},
        ]

        for _ in range(self.max_iter):
            try:
                resp = self._litellm_chat(messages, self.tool_defs)
            except Exception as exc:
                log.error("LiteLLM error: %s", exc)
                return f"Error communicating with model: {exc}"

            msg = resp.choices[0].message
            assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_entry)

            if not msg.tool_calls:
                return msg.content or ""

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                raw_args = tc.function.arguments or "{}"

                parsed = _parse_tool_args(raw_args)
                if isinstance(parsed, str):
                    log.warning("Tool call JSON parse failed for %s", fn_name)
                    if self.on_step:
                        self.on_step(f"⚠️ {fn_name}", "JSON format error — asking model to retry")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": parsed})
                    continue

                fn_args = parsed
                log.debug("Tool call — %s(%s)", fn_name, str(fn_args)[:80])
                if self.on_step:
                    self.on_step(f"🔧 {fn_name}", str(fn_args)[:120])
                result = self._call_tool(fn_name, fn_args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

        log.warning("Max iterations reached — requesting final answer")
        messages.append({"role": "user", "content": "Please provide your final answer now."})
        try:
            resp = self._litellm_chat(messages, None)
            return resp.choices[0].message.content or "Unable to complete."
        except Exception as exc:
            return f"Error: {exc}"

    def _call_tool(self, fn_name: str, fn_args: dict) -> str:
        if fn_name in self.tool_map:
            try:
                return str(self.tool_map[fn_name](**fn_args))
            except Exception as exc:
                log.warning("Tool '%s' raised: %s", fn_name, exc)
                return f"Tool error: {exc}"
        log.warning("Unknown tool requested: %s", fn_name)
        return f"Unknown tool: {fn_name}"


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
        import concurrent.futures

        def _run_worker(agent) -> str:
            log.debug("Delegating to: %s", agent.role)
            if on_step:
                on_step("🤝 Delegating", f"→ **{agent.role}**: {task[:80]}")

            prompt = task
            result = agent.run(prompt)

            if on_step:
                on_step(f"✅ {agent.role[:40]}", "done")

            return f"**{agent.role}**:\n{result}"

        # Run workers concurrently
        context_parts: list[str] = []
        if self._agents:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._agents)) as executor:
                context_parts = list(executor.map(_run_worker, self._agents))

        # Manager synthesizes all worker outputs
        from agents.crew import _load_company_dna
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


def _parse_tool_args(raw_args) -> dict | str:
    if isinstance(raw_args, dict):
        return raw_args
    if not isinstance(raw_args, str):
        return {}

    s = raw_args.strip()
    if not s:
        return {}

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Attempt to strip markdown blocks if model hallucinated them
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Generic cleanup (e.g., trailing commas before braces)
    s_clean = re.sub(r",(\s*[}\]])", r"\1", s)
    try:
        return json.loads(s_clean)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON arguments provided: {exc}. Please fix your JSON formatting and try again."
