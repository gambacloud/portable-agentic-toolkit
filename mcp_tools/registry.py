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
from pathlib import Path
from typing import Callable, Optional

from crewai.tools import BaseTool
from pydantic import Field


# ── Registry ─────────────────────────────────────────────────────────────────


class MCPRegistry:
    """
    Discovers and caches MCP server tool definitions.
    Must be instantiated and awaited (discover()) before crew creation.
    """

    def __init__(self, servers_dir: Path):
        self.servers_dir = servers_dir
        # { server_name: { "config": dict, "tools": list[dict] } }
        self._servers: dict[str, dict] = {}

    async def discover(self):
        """Scan servers_dir, connect to each enabled server, cache tool lists."""
        if not self.servers_dir.exists():
            return

        for config_path in sorted(self.servers_dir.glob("*/config.json")):
            server_name = config_path.parent.name
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[MCP] Skipping '{server_name}': bad config.json — {exc}")
                continue

            if not config.get("enabled", True):
                continue

            try:
                tools = await _list_tools(config)
                self._servers[server_name] = {"config": config, "tools": tools}
                print(f"[MCP] Loaded '{server_name}' — {len(tools)} tool(s)")
            except Exception as exc:
                print(f"[MCP] Failed to load '{server_name}': {exc}")

    def tool_count(self) -> int:
        return sum(len(s["tools"]) for s in self._servers.values())

    def get_crewai_tools(self, ask_user_fn: Optional[Callable] = None) -> list[BaseTool]:
        """Return one CrewAI BaseTool per discovered MCP tool."""
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
        return tools

    def tool_descriptions(self) -> str:
        """Human-readable tool list — useful for injecting into system prompts."""
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
    """
    Dynamically creates a CrewAI BaseTool subclass that calls an MCP server tool.
    We use a closure over the config so each instance is self-contained.
    """
    # CrewAI expects tool names to be valid Python identifiers
    safe_name = f"{server_name}__{tool_def['name']}".replace("-", "_")
    description = (
        f"[MCP:{server_name}] {tool_def.get('description', tool_def['name'])}. "
        "Input: a JSON object with the tool arguments."
    )
    _server_config = server_config
    _tool_name = tool_def["name"]
    _requires_confirm = requires_confirmation
    _ask_user = ask_user_fn

    class _MCPTool(BaseTool):
        name: str = Field(default=safe_name)
        description: str = Field(default=description)

        def _run(self, tool_input: str = "") -> str:
            # Parse JSON arguments supplied by the agent
            args: dict = {}
            stripped = (tool_input or "").strip()
            if stripped.startswith("{"):
                try:
                    args = json.loads(stripped)
                except json.JSONDecodeError:
                    pass

            # HITL gate for destructive / API-touching tools
            if _requires_confirm and _ask_user:
                preview = json.dumps(args, indent=2, ensure_ascii=False)
                decision = _ask_user(
                    f"**Tool `{_tool_name}` wants to run** with:\n```json\n{preview}\n```\nAllow?",
                    ["Allow", "Deny"],
                )
                if decision != "Allow":
                    return "Action denied by user."

            # asyncio.run() is safe here: we're inside asyncio.to_thread(),
            # so there is no running event loop in this thread.
            return asyncio.run(_call_tool(_server_config, _tool_name, args))

    # Rename the class so CrewAI logs show something meaningful
    _MCPTool.__name__ = safe_name
    return _MCPTool()


# ── Async MCP helpers ────────────────────────────────────────────────────────


async def _list_tools(config: dict) -> list[dict]:
    """Connect to an MCP server and return its tool definitions."""
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
    """Connect to an MCP server, call one tool, return text output."""
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
        return "\n".join(
            getattr(c, "text", str(c)) for c in result.content
        )
    return "(Tool completed — no text output)"
