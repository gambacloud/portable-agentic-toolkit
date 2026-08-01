"""
MCP Tool Registry — auto-discovers MCP servers from bin/mcp_servers/.

Discovery flow:
  1. Scan bin/mcp_servers/*/config.json at startup (async).
  2. Launch one supervisor task per server; each opens its own connection
     (stdio/http/sse), calls list_tools(), then blocks until told to close —
     this keeps anyio's cancel scopes correctly task-scoped (open and close
     must happen in the same task; a shared AsyncExitStack entered from
     concurrent gather()'d tasks and closed from the caller's task breaks
     that invariant and crashes on close).
  3. On runner build, expose tools as (tool_defs, tool_map) for direct Ollama calls.
  4. On tool execution (sync, inside a thread), dispatch to main loop via run_coroutine_threadsafe.
  5. If requires_confirmation=true, gate execution behind HITL ask_user_fn.
"""
from __future__ import annotations

import asyncio
import json
import time
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
        self._discovered_names: list[str] = []
        self._server_tasks: dict[str, asyncio.Task] = {}
        self._close_events: dict[str, asyncio.Event] = {}
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

        to_load: list[tuple[str, dict]] = []
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

            self._discovered_names.append(server_name)
            to_load.append((server_name, config))

        # Each server gets its own long-lived task that owns its connection's
        # full lifetime (open -> stay alive -> close), started concurrently —
        # this turns an 8-10s sequential connect delay (every page load /
        # conversation switch re-discovers all of them) into roughly the
        # slowest single server's time, without the cross-task cancel-scope
        # crash a shared exit stack would hit.
        ready_events = []
        for name, cfg in to_load:
            ready = asyncio.Event()
            close_event = asyncio.Event()
            self._close_events[name] = close_event
            self._server_tasks[name] = asyncio.create_task(
                self._run_server(name, cfg, ready, close_event)
            )
            ready_events.append(ready)

        await asyncio.gather(*(e.wait() for e in ready_events))

    async def _run_server(self, server_name: str, config: dict, ready_event: asyncio.Event, close_event: asyncio.Event) -> None:
        t_start = time.perf_counter()
        try:
            async with self._connect(server_name, config) as session:
                self._sessions[server_name] = session
                result = await session.list_tools()
                tools = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema or {},
                    }
                    for t in result.tools
                ]
                elapsed = time.perf_counter() - t_start
                self._servers[server_name] = {"config": config, "tools": tools}
                log.info(
                    "Loaded MCP server '%s' — %d tool(s) in %.2fs",
                    server_name, len(tools), elapsed,
                )
                for t in tools:
                    log.debug("  tool: %s — %s", t["name"], t["description"][:80])

                ready_event.set()
                await close_event.wait()
        except Exception as exc:
            elapsed = time.perf_counter() - t_start
            log.error(
                "Failed to load MCP server '%s' after %.2fs — %s",
                server_name, elapsed, exc, exc_info=True,
            )
            ready_event.set()
        finally:
            self._sessions.pop(server_name, None)

    @staticmethod
    def _connect(server_name: str, config: dict):
        """Async context manager yielding an initialized ClientSession for any transport."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm():
            transport = config.get("transport", "stdio")

            if transport == "stdio":
                params = StdioServerParameters(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env") or None,
                )
                stream_cm = stdio_client(params)
            elif transport == "http":
                from mcp.client.streamable_http import streamablehttp_client
                stream_cm = streamablehttp_client(config["url"], headers=config.get("headers") or None)
            elif transport == "sse":
                from mcp.client.sse import sse_client
                stream_cm = sse_client(config["url"], headers=config.get("headers") or None)
            else:
                raise ValueError(f"Unknown transport '{transport}'")

            async with stream_cm as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

        return _cm()

    async def close(self):
        log.info("Closing MCP Registry and killing server processes")
        for event in self._close_events.values():
            event.set()
        if self._server_tasks:
            await asyncio.gather(*self._server_tasks.values(), return_exceptions=True)
        self._server_tasks.clear()
        self._close_events.clear()
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
        """Returns names of servers that successfully connected."""
        return list(self._servers.keys())

    def all_server_names(self) -> list[str]:
        """Returns all discovered server names, including those that failed to connect."""
        return list(self._discovered_names)

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
