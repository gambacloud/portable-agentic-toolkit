"""
MCP Tool Registry — auto-discovers MCP servers from bin/mcp_servers/
and wraps their tools as CrewAI BaseTool instances.

Discovery flow:
  1. Scan bin/mcp_servers/*/config.json at startup (async).
  2. Connect to each server via stdio, call list_tools(), cache results.
  3. On crew build, wrap each tool as a CrewAI BaseTool.
  4. On tool execution (sync, inside a thread), call the server via asyncio.run().
  5. If requires_confirmation=true, gate execution behind HITL ask_user_fn.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Callable, Optional

from crewai.tools import BaseTool
from pydantic import Field

from utils.logger import get_logger

log = get_logger(__name__)


# ── Registry ─────────────────────────────────────────────────────────────────


class MCPRegistry:
    def __init__(self, servers_dir: Path):
        self.servers_dir = servers_dir
        self._servers: dict[str, dict] = {}

    async def discover(self):
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
                tools = await _list_tools(config)
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

    def tool_count(self) -> int:
        return sum(len(s["tools"]) for s in self._servers.values())

    def get_crewai_tools(self, ask_user_fn: Optional[Callable] = None) -> list[BaseTool]:
        tools: list[BaseTool] = []
        for server_name, server_data in self._servers.items():
            config = server_data["config"]
            needs_confirm = config.get("requires_confirmation", False)
            for tool_def in server_data["tools"]:
                tools.append(
                    _make_mcp_tool(
                        server_name=server_name,
                        tool_def=tool_def,
                        server_config=config,
                        requires_confirmation=needs_confirm,
                        ask_user_fn=ask_user_fn,
                    )
                )
        log.debug("Returning %d CrewAI tool wrapper(s)", len(tools))
        return tools

    def tool_descriptions(self) -> str:
        if not self._servers:
            return "No MCP tools available."
        lines = ["Available MCP tools:"]
        for srv_name, srv_data in self._servers.items():
            for t in srv_data["tools"]:
                lines.append(f"  [{srv_name}] {t['name']}: {t['description']}")
        return "\n".join(lines)


# ── MCP tool factory ─────────────────────────────────────────────────────────


def _make_mcp_tool(
    server_name: str,
    tool_def: dict,
    server_config: dict,
    requires_confirmation: bool,
    ask_user_fn: Optional[Callable],
) -> BaseTool:
    safe_name = f"{server_name}__{tool_def['name']}".replace("-", "_")
    description = (
        f"[MCP:{server_name}] {tool_def.get('description', tool_def['name'])}. "
        "Input: a JSON object with the tool arguments."
    )
    _server_config = server_config
    _tool_name = tool_def["name"]
    _requires_confirm = requires_confirmation
    _ask_user = ask_user_fn
    _log = get_logger(f"mcp.{server_name}.{_tool_name}")

    class _MCPTool(BaseTool):
        name: str = Field(default=safe_name)
        description: str = Field(default=description)

        def _run(self, tool_input: str = "") -> str:
            args: dict = {}
            stripped = (tool_input or "").strip()
            if stripped.startswith("{"):
                try:
                    args = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    _log.warning("Could not parse tool input as JSON (%s) — using {}", exc)

            _log.info("Tool call — server=%s tool=%s args=%s", server_name, _tool_name, args)

            if _requires_confirm and _ask_user:
                preview = json.dumps(args, indent=2, ensure_ascii=False)
                decision = _ask_user(
                    f"**Tool `{_tool_name}` wants to run** with:\n```json\n{preview}\n```\nAllow?",
                    ["Allow", "Deny"],
                )
                if decision != "Allow":
                    _log.warning("Tool '%s' denied by user", _tool_name)
                    return "Action denied by user."
                _log.info("Tool '%s' allowed by user", _tool_name)

            t_start = time.perf_counter()
            try:
                result = asyncio.run(_call_tool(_server_config, _tool_name, args))
                elapsed = time.perf_counter() - t_start
                _log.info(
                    "Tool '%s' completed in %.2fs — output_len=%d",
                    _tool_name, elapsed, len(result),
                )
                _log.debug("Tool output: %s", result[:300])
                return result
            except Exception as exc:
                elapsed = time.perf_counter() - t_start
                _log.error(
                    "Tool '%s' failed after %.2fs — %s",
                    _tool_name, elapsed, exc, exc_info=True,
                )
                return f"Tool error: {exc}"

    _MCPTool.__name__ = safe_name
    return _MCPTool()


# ── Async MCP helpers ────────────────────────────────────────────────────────


async def _list_tools(config: dict) -> list[dict]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=config["command"],
        args=config.get("args", []),
        env=config.get("env") or None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema or {},
                }
                for t in result.tools
            ]


async def _call_tool(config: dict, tool_name: str, args: dict) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=config["command"],
        args=config.get("args", []),
        env=config.get("env") or None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)

    if result.content:
        return "\n".join(getattr(c, "text", str(c)) for c in result.content)
    return "(Tool completed — no text output)"
