"""
Direct Ollama agent runner for fast, reliable tool-calling.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Optional

import ollama
import yaml

from utils.logger import get_logger
from utils.settings import get_system_prompt_extra, get_user_prompt_prefix

log = get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "agents.yaml"


# ── Public API ───────────────────────────────────────────────────────────────


def build_crew(
    model: str,
    tool_defs: list,
    tool_map: dict,
    on_step: Optional[Callable] = None,
    profile_id: Optional[str] = None,
    on_token_usage: Optional[Callable[[int, int], None]] = None,
) -> "_Runner":
    cfg = _agent_config(profile_id=profile_id)
    dna = _load_company_dna()
    extra = get_system_prompt_extra()
    backstory = f"{dna}\n\n{cfg['backstory']}" if dna else cfg["backstory"]
    if extra:
        backstory = f"{backstory}\n\n{extra}"
    log.info("Building single agent — model=%s tools=%d profile=%s", model, len(tool_defs), profile_id)

    agent = _OllamaAgent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=backstory,
        model=model,
        tool_defs=tool_defs,
        tool_map=tool_map,
        on_step=on_step,
        on_token_usage=on_token_usage,
    )
    return _Runner([agent], on_step=on_step, model=model, on_token_usage=on_token_usage)


def build_hierarchical_crew(
    model: str,
    tool_defs: list,
    tool_map: dict,
    on_step: Optional[Callable] = None,
    profile_id: Optional[str] = None,
    on_token_usage: Optional[Callable[[int, int], None]] = None,
) -> "_Runner":
    cfg = _agent_config(profile_id=profile_id)
    dna = _load_company_dna()
    extra = get_system_prompt_extra()
    crew_cfgs = _load_crew_agent_configs()

    if not crew_cfgs:
        log.warning("No crew_agents in agents.yaml — falling back to single agent")
        return build_crew(model=model, tool_defs=tool_defs, tool_map=tool_map, on_step=on_step, profile_id=profile_id, on_token_usage=on_token_usage)

    log.info(
        "Building team — default_model=%s workers=%d tools=%d models=%s",
        model, len(crew_cfgs), len(tool_defs), [c.get("model") or model for c in crew_cfgs],
    )

    def _backstory(text: str) -> str:
        b = f"{dna}\n\n{text}" if dna else text
        return f"{b}\n\n{extra}" if extra else b

    workers = [
        _OllamaAgent(
            role=c["role"],
            goal=c["goal"],
            backstory=_backstory(c["backstory"]),
            model=c.get("model") or model,
            tool_defs=tool_defs,
            tool_map=tool_map,
            on_step=on_step,
            on_token_usage=on_token_usage,
        )
        for c in crew_cfgs
    ]

    manager_cfg = {
        "role": "Team Manager — " + cfg["role"],
        "goal": cfg["goal"],
        "backstory": _backstory(cfg["backstory"]),
    }
    return _Runner(workers, manager_cfg=manager_cfg, on_step=on_step, model=model, on_token_usage=on_token_usage)


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
        on_token_usage: Optional[Callable[[int, int], None]] = None,
        max_iter: int = 6,
    ):
        self.role = role
        self.goal = goal
        self.model = model
        self.tool_defs = tool_defs
        self.tool_map = tool_map
        self.on_step = on_step
        self.on_token_usage = on_token_usage
        self.max_iter = max_iter
        self.failed = False  # set when the model call itself errors out (not a tool error)
        self.tokens_used = 0  # running total for this agent, across all calls in run()
        self._system = (
            f"You are {role}.\nGoal: {goal}\n\n{backstory}"
        )

    _LITELLM_PREFIXES = ("groq/", "claude/", "gemini/")
    _OLLAMA_CLOUD_PREFIX = "ollama_cloud/"

    def _record_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.tokens_used += prompt_tokens + completion_tokens
        if self.on_token_usage:
            self.on_token_usage(prompt_tokens, completion_tokens)

    def run(self, task: str) -> str:
        prefix = get_user_prompt_prefix()
        if prefix:
            task = f"{prefix}\n\n{task}"
        if self.model.startswith(self._OLLAMA_CLOUD_PREFIX):
            return self._run_ollama_cloud(task)
        if any(self.model.startswith(p) for p in self._LITELLM_PREFIXES):
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
                self._record_tokens(getattr(resp, "prompt_eval_count", 0) or 0, getattr(resp, "eval_count", 0) or 0)
            except Exception as exc:
                log.error("Ollama chat error: %s", exc)
                self.failed = True
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
            self._record_tokens(getattr(resp, "prompt_eval_count", 0) or 0, getattr(resp, "eval_count", 0) or 0)
            return resp.message.content or "Unable to complete task within iteration limit."
        except Exception as exc:
            self.failed = True
            return f"Error: {exc}"

    def _run_ollama_cloud(self, task: str) -> str:
        from utils.ollama_utils import ollama_cloud_client
        client = ollama_cloud_client()
        model = self.model.removeprefix(self._OLLAMA_CLOUD_PREFIX)
        messages: list = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": task},
        ]

        for _ in range(self.max_iter):
            try:
                resp = client.chat(
                    model=model,
                    messages=messages,
                    tools=self.tool_defs if self.tool_defs else None,
                )
                self._record_tokens(getattr(resp, "prompt_eval_count", 0) or 0, getattr(resp, "eval_count", 0) or 0)
            except Exception as exc:
                log.error("Ollama Cloud chat error: %s", exc)
                self.failed = True
                return f"Error communicating with Ollama Cloud: {exc}"

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
                log.debug("Tool call — %s(%s)", fn_name, str(parsed)[:80])
                if self.on_step:
                    self.on_step(f"🔧 {fn_name}", str(parsed)[:120])
                result = self._call_tool(fn_name, parsed)
                messages.append({"role": "tool", "content": str(result)})

        log.warning("Max iterations reached — requesting final answer")
        messages.append({"role": "user", "content": "Please provide your final answer now."})
        try:
            resp = client.chat(model=model, messages=messages)
            self._record_tokens(getattr(resp, "prompt_eval_count", 0) or 0, getattr(resp, "eval_count", 0) or 0)
            return resp.message.content or "Unable to complete task within iteration limit."
        except Exception as exc:
            self.failed = True
            return f"Error: {exc}"

    def _litellm_chat(self, messages: list, tools: list | None):
        import litellm
        # claude/ prefix → anthropic/ for LiteLLM
        model = self.model.replace("claude/", "anthropic/", 1) if self.model.startswith("claude/") else self.model
        for attempt in range(4):
            try:
                return litellm.completion(
                    model=model,
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
                if hasattr(resp, "usage") and resp.usage:
                    self._record_tokens(getattr(resp.usage, "prompt_tokens", 0) or 0, getattr(resp.usage, "completion_tokens", 0) or 0)
            except Exception as exc:
                log.error("LiteLLM error: %s", exc)
                self.failed = True
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
            if hasattr(resp, "usage") and resp.usage:
                self._record_tokens(getattr(resp.usage, "prompt_tokens", 0) or 0, getattr(resp.usage, "completion_tokens", 0) or 0)
            return resp.choices[0].message.content or "Unable to complete."
        except Exception as exc:
            self.failed = True
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
        on_token_usage: Optional[Callable[[int, int], None]] = None,
    ):
        self._agents = agents
        self._manager_cfg = manager_cfg
        self._on_step = on_step
        self._model = model
        self._on_token_usage = on_token_usage

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

    def _select_relevant_agents(self, task: str) -> list:
        """Ask a cheap routing call which team members this task actually
        needs, instead of always fanning out to every crew member. Falls
        back to the full team whenever the router is unavailable, fails, or
        gives an answer we can't parse — under-selecting silently would be
        worse than the old always-run-everyone behaviour."""
        if len(self._agents) <= 1:
            return self._agents

        on_step = self._on_step
        roster = "\n".join(f"- {a.role}: {a.goal}" for a in self._agents)
        router = _OllamaAgent(
            role="Team Router",
            goal="Decide which team members are needed for a given task.",
            backstory="You triage work for a team and assign only the members who are actually needed.",
            model=self._model,
            tool_defs=[],
            tool_map={},
        )
        routing_prompt = (
            f"Team members available:\n{roster}\n\n"
            f"Task: {task}\n\n"
            "Which of the team members above are actually needed to complete this task well? "
            "Reply with nothing but a comma-separated list of their exact role names from the "
            "list above. Include only the ones genuinely needed — if just one suffices, name "
            "only that one. If unsure, list all of them."
        )
        try:
            reply = router.run(routing_prompt)
        except Exception as exc:
            log.warning("Routing call failed, using full team: %s", exc)
            return self._agents

        if router.failed:
            log.warning("Routing call failed, using full team: %s", reply[:200])
            return self._agents

        chosen = [a for a in self._agents if a.role.lower() in reply.lower()]
        if not chosen:
            log.warning("Routing reply matched no known role, using full team: %r", reply[:200])
            return self._agents

        if on_step:
            skipped = [a.role for a in self._agents if a not in chosen]
            on_step(
                "🧭 Routing",
                f"selected: {', '.join(a.role for a in chosen)}"
                + (f" — skipped: {', '.join(skipped)}" if skipped else ""),
            )
        return chosen

    def _select_relevant_tools(self, task: str, tool_defs: list) -> list:
        """Ask a cheap routing call which tools this task actually needs,
        once for the whole team, instead of handing every worker the entire
        tool surface (every MCP server's tools). A large tool list measurably
        confuses a small local model into looping on a trivial task instead
        of answering — see the QA note from testing dynamic agent selection.
        Falls back to the full tool set on any failure or unparseable reply."""
        if len(tool_defs) <= 1:
            return tool_defs

        on_step = self._on_step
        roster = "\n".join(
            f"- {t['function']['name']}: {t['function'].get('description', '')[:100]}"
            for t in tool_defs
        )
        router = _OllamaAgent(
            role="Tool Router",
            goal="Decide which tools a team needs for a given task.",
            backstory="You triage available tools and grant only the ones actually needed.",
            model=self._model,
            tool_defs=[],
            tool_map={},
        )
        routing_prompt = (
            f"Tools available:\n{roster}\n\n"
            f"Task: {task}\n\n"
            "Which of the tools above are actually needed to complete this task? Reply with "
            "nothing but a comma-separated list of their exact names from the list above. "
            "If none are needed, reply with the single word NONE. If unsure, list all of them."
        )
        try:
            reply = router.run(routing_prompt)
        except Exception as exc:
            log.warning("Tool routing call failed, using full tool set: %s", exc)
            return tool_defs

        if router.failed:
            log.warning("Tool routing call failed, using full tool set: %s", reply[:200])
            return tool_defs

        if reply.strip().strip(".").upper() == "NONE":
            if on_step:
                on_step("🧰 Tools", "0 tool(s) selected — none needed for this task")
            return []

        reply_lower = reply.lower()
        chosen = [t for t in tool_defs if t["function"]["name"].lower() in reply_lower]
        if not chosen:
            log.warning("Tool routing reply matched no known tool, using full tool set: %r", reply[:200])
            return tool_defs

        if on_step:
            on_step("🧰 Tools", f"{len(chosen)}/{len(tool_defs)} tool(s) selected for this task")
        return chosen

    def _coarse_plan(self, task: str) -> list[dict]:
        """The old select-agents + select-tools behaviour: every selected
        worker gets the exact same raw task text, with one team-wide tool
        filter. Used when real planning (_plan) fails or is unparseable —
        strictly safer than under-selecting, since it still runs every
        agent that plausibly matters."""
        agents = self._select_relevant_agents(task)
        if agents and agents[0].tool_defs:
            allowed_defs = self._select_relevant_tools(task, agents[0].tool_defs)
            allowed_names = {t["function"]["name"] for t in allowed_defs}
            for agent in agents:
                agent.tool_defs = allowed_defs
                agent.tool_map = {n: fn for n, fn in agent.tool_map.items() if n in allowed_names}
        return [{"agent": a, "instruction": task} for a in agents]

    def _plan(self, task: str) -> list[dict]:
        """Ask a planner call to break the task into a specific instruction
        and tool list per team member, instead of broadcasting the same raw
        task and the same team-wide tool filter to everyone selected.
        Returns [{"agent": _OllamaAgent, "instruction": str}, ...]. Falls
        back to _coarse_plan on any router failure or unparseable reply."""
        if len(self._agents) <= 1:
            return [{"agent": a, "instruction": task} for a in self._agents]

        on_step = self._on_step
        agent_roster = "\n".join(f"- {a.role}: {a.goal}" for a in self._agents)
        all_tool_defs = self._agents[0].tool_defs or []
        tool_roster = "\n".join(
            f"- {t['function']['name']}: {t['function'].get('description', '')[:100]}"
            for t in all_tool_defs
        ) or "(none)"

        planner = _OllamaAgent(
            role="Planner",
            goal="Break a task into per-agent instructions and tool assignments.",
            backstory=(
                "You plan work for a team: decide who is genuinely needed, write a "
                "specific instruction for exactly what each of them should do, and "
                "list only the tools each one personally needs."
            ),
            model=self._model,
            tool_defs=[],
            tool_map={},
        )
        plan_prompt = (
            f"Team members available:\n{agent_roster}\n\n"
            f"Tools available:\n{tool_roster}\n\n"
            f"Task: {task}\n\n"
            "Break this into a plan. Include only members genuinely needed — skip anyone "
            "who wouldn't add anything. For each one, write a specific instruction covering "
            "exactly what they personally should do (not just the raw task restated), and "
            "list only the tool names they personally need (exact names from the list above, "
            "empty list if none).\n\n"
            "IMPORTANT: every member works independently and in parallel — none of them can "
            "see any other member's output, and there is no second round. Never write an "
            "instruction that depends on another member's result (e.g. 'summarize what the "
            "researcher found') — if a step truly needs another step's output first, give both "
            "the same self-contained instruction instead so each can complete the task alone.\n\n"
            'Reply with nothing but JSON, no prose, no code fence: {"steps": [{"role": '
            '"<exact role name>", "instruction": "<specific instruction>", "tools": '
            '["<tool name>", ...]}]}'
        )
        try:
            reply = planner.run(plan_prompt)
        except Exception as exc:
            log.warning("Planning call failed, using coarse fallback: %s", exc)
            return self._coarse_plan(task)

        if planner.failed:
            log.warning("Planning call failed, using coarse fallback: %s", reply[:200])
            return self._coarse_plan(task)

        parsed = _parse_tool_args(reply)
        if isinstance(parsed, str) or not isinstance(parsed.get("steps"), list) or not parsed["steps"]:
            log.warning("Planning reply unparseable, using coarse fallback: %r", reply[:200])
            return self._coarse_plan(task)

        by_role = {a.role.lower(): a for a in self._agents}
        tool_defs_by_name = {t["function"]["name"]: t for t in all_tool_defs}

        steps = []
        for raw_step in parsed["steps"]:
            if not isinstance(raw_step, dict):
                continue
            role = str(raw_step.get("role", "")).strip()
            agent = by_role.get(role.lower()) or next(
                (a for a in self._agents if role and (role.lower() in a.role.lower() or a.role.lower() in role.lower())),
                None,
            )
            if not agent or any(s["agent"] is agent for s in steps):
                continue

            instruction = str(raw_step.get("instruction") or task).strip()
            tool_names = raw_step.get("tools")
            tool_names = tool_names if isinstance(tool_names, list) else []
            selected_defs = [tool_defs_by_name[n] for n in tool_names if n in tool_defs_by_name]

            agent.tool_defs = selected_defs
            allowed = {t["function"]["name"] for t in selected_defs}
            agent.tool_map = {n: fn for n, fn in agent.tool_map.items() if n in allowed}

            steps.append({"agent": agent, "instruction": instruction})

        if not steps:
            log.warning("Planning reply named no known agents, using coarse fallback: %r", reply[:200])
            return self._coarse_plan(task)

        if on_step:
            summary = "; ".join(
                f"{s['agent'].role} ({len(s['agent'].tool_defs)} tools): {s['instruction'][:60]}"
                for s in steps
            )
            on_step("🗺️ Plan", summary)

        return steps

    def _run_team(self, task: str) -> str:
        on_step = self._on_step
        import concurrent.futures

        steps = self._plan(task)

        def _run_worker(step: dict) -> str:
            agent, instruction = step["agent"], step["instruction"]
            log.debug("Delegating to: %s (model=%s)", agent.role, agent.model)
            if on_step:
                on_step("🤝 Delegating", f"→ **{agent.role}** ({agent.model}): {instruction[:80]}")

            result = agent.run(instruction)

            if agent.failed:
                log.warning("Worker '%s' (model=%s) failed: %s", agent.role, agent.model, result[:200])
                if on_step:
                    on_step(f"⚠️ {agent.role[:40]}", f"failed on {agent.model} — {result[:150]}")
                return f"**{agent.role}** [FAILED — do not treat this as a real answer]:\n{result}"

            if on_step:
                on_step(f"✅ {agent.role[:40]}", f"done — {agent.tokens_used} tokens")

            return f"**{agent.role}**:\n{result}"

        # Run the planned workers concurrently
        context_parts: list[str] = []
        if steps:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(steps)) as executor:
                context_parts = list(executor.map(_run_worker, steps))

        agents = [s["agent"] for s in steps]

        failed_count = sum(1 for a in agents if a.failed)
        if failed_count and on_step:
            on_step("⚠️ Team status", f"{failed_count}/{len(agents)} worker(s) failed — see steps above")

        # Manager synthesizes all worker outputs
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
            on_token_usage=self._on_token_usage,
        )

        synthesis_prompt = (
            "Here are the outputs from your team:\n\n"
            + "\n\n---\n\n".join(context_parts)
            + f"\n\nOriginal task: {task}\n\n"
            "Any output marked [FAILED] came from a team member whose model call errored out — "
            "ignore its content entirely and rely on the other members' outputs instead. "
            "If every member failed, say so plainly instead of guessing an answer.\n\n"
            "Synthesize a final, clear, and complete answer."
        )
        result = manager.run(synthesis_prompt)

        if on_step:
            parts = [f"{a.role} ({a.model}): {a.tokens_used}" for a in agents]
            parts.append(f"{manager.role} ({manager.model}): {manager.tokens_used}")
            on_step("📊 Token usage", ", ".join(parts))

        self._judge(task, result)
        return result

    def _judge(self, task: str, answer: str) -> None:
        """Verification only, not a retry loop: ask whether the delivered
        answer actually satisfies the original task, and surface the
        verdict as a step. Deliberately doesn't loop back and re-run the
        team on INCOMPLETE — that risks the team failing to converge and
        looping forever on a genuinely hard or ambiguous task."""
        on_step = self._on_step
        if not on_step:
            return

        judge = _OllamaAgent(
            role="Judge",
            goal="Verify whether a delivered answer satisfies the task it was meant to answer.",
            backstory="You check delivered work against what was actually asked, and say so plainly.",
            model=self._model,
            tool_defs=[],
            tool_map={},
        )
        judge_prompt = (
            f"Original task: {task}\n\nDelivered answer:\n{answer}\n\n"
            "Does this answer fully satisfy the task? Reply with nothing but one line: "
            "either the single word PASS, or INCOMPLETE followed by a colon and one short "
            "sentence naming what's missing."
        )
        try:
            verdict = judge.run(judge_prompt)
        except Exception as exc:
            log.debug("Judge call failed, skipping: %s", exc)
            return
        if judge.failed:
            log.debug("Judge call failed, skipping: %s", verdict[:200])
            return

        verdict = verdict.strip()
        icon = "✅" if verdict.upper().startswith("PASS") else "⚠️"
        on_step(f"{icon} Judge", verdict[:200])


def _load_company_dna() -> str:
    if not _CONFIG_PATH.exists():
        return ""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        dna = data.get("company_dna", "").strip()
        if dna:
            log.debug("Company DNA loaded (%d chars)", len(dna))
        return dna
    except Exception as exc:
        log.warning("Failed to load company_dna: %s", exc)
        return ""


def _load_crew_agent_configs() -> list[dict]:
    """crew_agents from config/agents.yaml (factory defaults, git-tracked)
    plus any DB Profile the user flagged is_crew_member — same shape either
    way, so a Profile created in /profiles shows up in the team with no YAML
    edit needed. YAML entries come first; a name clash between the two
    sources is a user configuration mistake, not something resolved here."""
    yaml_cfgs: list[dict] = []
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            yaml_cfgs = [
                {
                    "role": c.get("role", "Specialist"),
                    "goal": c.get("goal", ""),
                    "backstory": c.get("backstory", ""),
                    "model": c.get("model"),
                }
                for c in data.get("crew_agents", [])
            ]
        except Exception as exc:
            log.warning("Failed to load crew_agents from agents.yaml: %s", exc)

    db_cfgs: list[dict] = []
    try:
        from db.queries import list_crew_profiles
        db_cfgs = [
            {
                "role": p.get("role") or p.get("name") or "Specialist",
                "goal": p.get("goal") or "",
                "backstory": p.get("backstory") or "",
                "model": p.get("model"),
            }
            for p in list_crew_profiles()
        ]
    except Exception as exc:
        log.debug("No DB crew profiles loaded: %s", exc)

    return yaml_cfgs + db_cfgs


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

    try:
        from db.queries import get_default_profile
        profile = get_default_profile()
        if profile:
            log.debug("Using system profile from DB: %s", profile.get("name"))
            return {
                "role": profile.get("role") or defaults["role"],
                "goal": profile.get("goal") or defaults["goal"],
                "backstory": profile.get("backstory") or defaults["backstory"],
            }
    except Exception as exc:
        log.debug("DB profile lookup skipped: %s", exc)

    if not _CONFIG_PATH.exists():
        log.debug("No agents.yaml found — using defaults")
        return defaults

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
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
    except json.JSONDecodeError:
        pass

    # A small model sometimes stops generating before closing every bracket —
    # close whatever is still open (tracking string state so brackets inside
    # a quoted value aren't counted) and try once more before giving up.
    repaired = _close_unbalanced_json(s_clean)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(s_clean)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON arguments provided: {exc}. Please fix your JSON formatting and try again."


def _close_unbalanced_json(s: str) -> Optional[str]:
    """Append whatever closing braces/brackets a truncated JSON string is
    missing, in the right order. Returns None if nothing looks unbalanced
    (so the caller doesn't retry an identical parse for no reason)."""
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in s:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    if not stack or in_string:
        return None
    closers = {"{": "}", "[": "]"}
    return s + "".join(closers[c] for c in reversed(stack))
