"""MCP self-installer — lets the agent add new tool servers at runtime."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import yaml

from utils.logger import get_logger

log = get_logger(__name__)

_CATALOG_PATH = Path(__file__).parent.parent / "config" / "mcp_catalog.yaml"
_SERVERS_DIR = Path(__file__).parent.parent / "bin" / "mcp_servers"


def make_runner_installer_tool(ask_user_fn: Callable[[str, list[str]], str]) -> tuple[dict, Callable]:
    """Return (ollama_tool_def, callable) for the direct Ollama runner."""
    catalog = _load_catalog()
    available = ", ".join(catalog) if catalog else "none"
    _blocked = [False]

    def install_mcp_server(server_name: str) -> str:
        if _blocked[0]:
            return "Installation already declined this turn. Provide your final answer now."
        result = _install(server_name.strip().lower(), catalog, ask_user_fn)
        if "declined" in result:
            _blocked[0] = True
        return result

    tool_def = {
        "type": "function",
        "function": {
            "name": "install_mcp_server",
            "description": (
                "Install a new MCP server to connect to an external service. "
                f"Known servers: {available}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "Name of the MCP server to install",
                    }
                },
                "required": ["server_name"],
            },
        },
    }
    return tool_def, install_mcp_server


# ── Internal ──────────────────────────────────────────────────────────────────


def _install(server_name: str, catalog: dict, ask_user_fn: Callable) -> str:
    if server_name not in catalog:
        available = ", ".join(catalog)
        return f"Unknown server '{server_name}'. Available: {available}"

    entry = catalog[server_name]
    config_path = _SERVERS_DIR / server_name / "config.json"

    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        if cfg.get("enabled", True):
            return f"'{server_name}' is already installed and enabled."
        cfg["enabled"] = True
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        log.info("Re-enabled MCP server: %s", server_name)
        return f"'{server_name}' was disabled — re-enabled. Restart the server to load it."

    decision = ask_user_fn(
        f"I'll install the **{server_name}** MCP server ({entry['description']}).\n"
        f"This creates `bin/mcp_servers/{server_name}/config.json`. Proceed?",
        ["Install", "Cancel"],
    )
    if decision == "Cancel":
        return f"The user declined to install '{server_name}'. Do not retry — report this outcome as your final answer."

    env_section = {}
    instructions = []
    for var in entry.get("env_vars", []):
        env_section[var["key"]] = f"<your {var['description']}>"
        if var.get("required"):
            instructions.append(f"  • **{var['key']}** — {var['description']}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    command = entry.get("command", "npx")
    args = [entry["package"]] if command != "npx" else ["-y", entry["package"]]
    config = {
        "name": server_name,
        "command": command,
        "args": args,
        "env": env_section,
        "requires_confirmation": entry.get("requires_confirmation", True),
        "enabled": True,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log.info("Installed MCP server: %s → %s", server_name, config_path)

    if instructions:
        steps = "\n".join(instructions)
        return (
            f"✅ **{server_name}** config created.\n\n"
            f"Add these to your `.env` file, then restart:\n{steps}"
        )
    return f"✅ **{server_name}** installed. Restart the server to activate it."


def _load_catalog() -> dict:
    if not _CATALOG_PATH.exists():
        log.warning("mcp_catalog.yaml not found")
        return {}
    try:
        with open(_CATALOG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("servers", {})
    except Exception as exc:
        log.warning("Failed to load mcp_catalog.yaml: %s", exc)
        return {}
