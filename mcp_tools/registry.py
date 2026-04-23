"""
MCP Tool Registry — auto-discovers MCP servers from bin/mcp_servers/.

Discovery flow:
  1. Scan bin/mcp_servers/*/config.json at startup (async).
  2. Connect to each server via stdio, call list_tools(), cache results, KEEP ALIVE.
  3. On runner build, expose tools as (tool_defs, tool_map) for direct Ollama calls.
  4. On tool execution (sync, inside a thread), dispatch to main loop via run_coroutine_threadsafe.
  5. If requires_confirmation=true, gate execution behind HITL ask_user_fn.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Callable, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from utils.logger import get_logger

log = get_logger(__name__)


# ── Registry ─────────────────────────────────────────────────────────────────


class MCPRegistry:
    def __init__(self, servers_dir: Path):
        self.servers_dir = servers_dir
        self._servers: dict[str, dict] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._stack = AsyncExitStack()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    async def discover(self):
        if not self._loop:
            self._loop = asyncio.get_running_loop()

        if not self.servers_dir.exists():
            log.debug("MCP servers dir not found: %s", self.servers_dir)
            return

        configs = sorted(self.servers_dir.glob("*/config.json"))
        log.info("Scanning %d MCP server config(s) in %s", len(configs), self.servers_dir)

        for config_path in configs:
            server_name = config_path.parent.name
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("Skipping '%s': bad config.json — %s", server_name, exc)
                continue

            if not config.get("enabled", True):
                log.debug("Skipping '%s': disabled in config", server_name)
                continue

            t_start = time.perf_counter()
            try:
                tools = await self._connect_and_list_tools(server_name, config)
                elapsed = time.perf_counter() - t_start
                self._servers[server_name] = {"config": config, "tools": tools}
                log.info(
                    "Loaded MCP server '%s' — %d tool(s) in %.2fs",
                    server_name, len(tools), elapsed,
                )
                for t in tools:
                    log.debug("  tool: %s — %s", t["name"], t["description"][:80])
            except Exception as exc:
                elapsed = time.perf_counter() - t_start
                log.error(
                    "Failed to load MCP server '%s' after %.2fs — %s",
                    server_name, elapsed, exc, exc_info=True,
                )

    async def _connect_and_list_tools(self, server_name: str, config: dict) -> list[dict]:
        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env") or None,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        self._sessions[server_name] = session

        result = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {},
            }
            for t in result.tools
        ]

    async def close(self):
        log.info("Closing MCP Registry and killing server processes")
        await self._stack.aclose()
        self._sessions.clear()

    def call_tool_sync(self, server_name: str, tool_name: str, args: dict) -> str:
        """Call an MCP tool synchronously by dispatching it to the main event loop."""
        session = self._sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' is not connected."

        async def _do_call():
            result = await session.call_tool(tool_name, args)
            if result.content:
                return "\n".join(getattr(c, "text", str(c)) for c in result.content)
            return "(Tool completed — no text output)"

        if not self._loop:
            return "Error: No event loop available for MCP tool call."

        future = asyncio.run_coroutine_threadsafe(_do_call(), self._loop)
        try:
            return future.result(timeout=120)
        except Exception as exc:
            return f"Tool execution failed: {exc}"

    def tool_count(self) -> int:
        return sum(len(s["tools"]) for s in self._servers.values())

    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    def get_runner_tools(self, ask_user_fn: Optional[Callable] = None, only_servers: Optional[list] = None) -> tuple[list[dict], dict]:
        tool_defs: list[dict] = []
        tool_map: dict[str, Callable] = {}

        for server_name, server_data in self._servers.items():
            if only_servers is not None and server_name not in only_servers:
                continue
            config = server_data["config"]
            needs_confirm = config.get("requires_confirmation", False)

            for t in server_data["tools"]:
                safe_name = f"{server_name}__{t['name']}".replace("-", "_")
                schema = dict(t.get("input_schema") or {})
                schema.setdefault("type", "object")
                schema.setdefault("properties", {})

                tool_defs.append({
                    "type": "function",
                    "function": {
                        "name": safe_name,
                        "description": f"[MCP:{server_name}] {t.get('description', t['name'])}",
                        "parameters": schema,
                    },
                })
                tool_map[safe_name] = _make_runner_callable(
                    self, server_name, t["name"], needs_confirm, ask_user_fn,
                    get_logger(f"mcp.{server_name}.{t['name']}"),
                )

        log.debug("Runner tools prepared: %d", len(tool_defs))
        return tool_defs, tool_map

    def tool_descriptions(self) -> str:
        if not self._servers:
            return "No MCP tools available."
        lines = ["Available MCP tools:"]
        for srv_name, srv_data in self._servers.items():
            for t in srv_data["tools"]:
                lines.append(f"  [{srv_name}] {t['name']}: {t['description']}")
        return "\n".join(lines)


def _make_runner_callable(registry: MCPRegistry, server_name: str, tool_name: str, needs_confirm: bool, ask_user_fn: Optional[Callable], logger):
    def fn(**kwargs):
        if needs_confirm and ask_user_fn:
            import json as _json
            preview = _json.dumps(kwargs, indent=2)
            decision = ask_user_fn(
                f"**Tool `{tool_name}` wants to run** with:\n```json\n{preview}\n```\nAllow?",
                ["Allow", "Deny"],
            )
            if decision != "Allow":
                logger.warning("Tool '%s' denied", tool_name)
                return "Action denied by user."
        try:
            return registry.call_tool_sync(server_name, tool_name, kwargs)
        except Exception as exc:
            logger.error("Tool error: %s", exc)
            return f"Tool error: {exc}"
    return fn
