"""MCP self-installer — lets the agent add new tool servers at runtime."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
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
                f"Known servers in catalog: {available}. "
                "For unlisted services, searches npm and PyPI automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "Name of the service to connect (e.g. 'hubspot', 'slack', 'notion')",
                    }
                },
                "required": ["server_name"],
            },
        },
    }
    return tool_def, install_mcp_server


# ── Internal ──────────────────────────────────────────────────────────────────


def _install(
    server_name: str,
    catalog: dict,
    ask_user_fn: Callable,
    env_values: dict | None = None,
    config_file_content: str | None = None,
) -> str:
    config_path = _SERVERS_DIR / server_name / "config.json"

    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        if cfg.get("enabled", True):
            return f"'{server_name}' is already installed and enabled."
        cfg["enabled"] = True
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        log.info("Re-enabled MCP server: %s", server_name)
        return f"'{server_name}' was disabled — re-enabled. Restart the server to load it."

    if server_name in catalog:
        return _install_from_catalog(server_name, catalog[server_name], config_path, ask_user_fn, env_values, config_file_content)

    # Not in catalog — search registries
    log.info("'%s' not in catalog, searching npm/PyPI...", server_name)
    found = _search_registries(server_name)
    if not found:
        return (
            f"No MCP package found for '{server_name}' on npm or PyPI.\n"
            f"Catalog servers available: {', '.join(catalog)}"
        )

    package = found["package"]
    command = found["command"]
    description = found.get("description", "")

    decision = ask_user_fn(
        f"Found **{package}** (`{command}`) for '{server_name}'.\n"
        + (f"{description}\n\n" if description else "\n")
        + "Install? (If it needs API keys you'll configure them afterwards.)",
        ["Install", "Cancel"],
    )
    if decision == "Cancel":
        return f"The user declined to install '{server_name}'. Do not retry — report this outcome as your final answer."

    args = ["-y", package] if command == "npx" else [package]
    config = {
        "name": server_name,
        "command": command,
        "args": args,
        "env": {},
        "requires_confirmation": True,
        "enabled": True,
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log.info("Installed MCP server from registry search: %s (%s)", server_name, package)
    return (
        f"✅ **{server_name}** installed ({package}).\n\n"
        f"If this server requires API keys, add them to your `.env` and restart."
    )


def _install_from_catalog(
    server_name: str,
    entry: dict,
    config_path: Path,
    ask_user_fn: Callable,
    env_values: dict | None = None,
    config_file_content: str | None = None,
) -> str:
    decision = ask_user_fn(
        f"I'll install the **{server_name}** MCP server ({entry['description']}).\n"
        f"This creates `bin/mcp_servers/{server_name}/config.json`. Proceed?",
        ["Install", "Cancel"],
    )
    if decision == "Cancel":
        return f"The user declined to install '{server_name}'. Do not retry — report this outcome as your final answer."

    env_values = env_values or {}
    env_section = {}
    instructions = []
    for var in entry.get("env_vars", []):
        key = var["key"]
        supplied = env_values.get(key, "").strip()
        env_section[key] = supplied if supplied else f"<your {var['description']}>"
        if var.get("required") and not supplied:
            instructions.append(f"  • **{key}** — {var['description']}")

    command = entry.get("command", "npx")
    args = [entry["package"]] if command != "npx" else ["-y", entry["package"]]

    config_path.parent.mkdir(parents=True, exist_ok=True)

    config_file_spec = entry.get("config_file")
    if config_file_spec:
        file_path = config_path.parent / config_file_spec["filename"]
        file_path.write_text(
            config_file_content or config_file_spec.get("default_content", ""),
            encoding="utf-8",
        )
        args += [config_file_spec.get("cli_flag", "--config-file"), str(file_path)]

    config = {
        "name": server_name,
        "command": command,
        "args": args,
        "env": env_section,
        "requires_confirmation": entry.get("requires_confirmation", True),
        "enabled": True,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log.info("Installed MCP server from catalog: %s", server_name)

    setup_note = entry.get("setup_note", "")
    note_suffix = f"\n\n{setup_note}" if setup_note else ""

    if instructions:
        steps = "\n".join(instructions)
        return (
            f"✅ **{server_name}** config created.\n\n"
            f"Add these to your `.env` file, then restart:\n{steps}{note_suffix}"
        )
    return f"✅ **{server_name}** installed. Restart the server to activate it.{note_suffix}"


# ── Registry search ────────────────────────────────────────────────────────────


def _search_registries(name: str) -> dict | None:
    return _search_npm(name) or _search_pypi(name)


def _search_npm(name: str) -> dict | None:
    # Try common naming patterns directly first
    candidates = [
        f"@modelcontextprotocol/server-{name}",
        f"mcp-server-{name}",
        f"{name}-mcp-server",
        f"@{name}/mcp-server",
    ]
    for package in candidates:
        encoded = urllib.parse.quote(package, safe="")
        try:
            req = urllib.request.Request(
                f"https://registry.npmjs.org/{encoded}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=6) as r:
                if r.status == 200:
                    data = json.loads(r.read())
                    log.info("Found npm package: %s", package)
                    return {"package": package, "command": "npx", "description": data.get("description", "")}
        except Exception:
            pass

    # Fall back to npm search API
    query = urllib.parse.quote(f"mcp {name}")
    try:
        with urllib.request.urlopen(
            f"https://registry.npmjs.org/-/v1/search?text={query}&size=5", timeout=6
        ) as r:
            data = json.loads(r.read())
            for obj in data.get("objects", []):
                pkg = obj["package"]
                pkg_name = pkg["name"]
                if "mcp" in pkg_name.lower() and name.lower() in pkg_name.lower():
                    log.info("Found npm package via search: %s", pkg_name)
                    return {"package": pkg_name, "command": "npx", "description": pkg.get("description", "")}
    except Exception:
        pass

    return None


def _search_pypi(name: str) -> dict | None:
    candidates = [
        f"mcp-{name}",
        f"mcp-server-{name}",
        f"{name}-mcp",
    ]
    for package in candidates:
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=6) as r:
                if r.status == 200:
                    data = json.loads(r.read())
                    desc = data.get("info", {}).get("summary", "")
                    log.info("Found PyPI package: %s", package)
                    return {"package": package, "command": "uvx", "description": desc}
        except Exception:
            pass

    return None


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
