"""Read/write cloud-LLM API keys in the app's .env file — no manual editing required.

Values are never returned to callers, only presence/absence, since this backs
a REST endpoint the frontend polls to render setup status.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from utils.paths import app_dir

KNOWN_KEYS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "Claude (Anthropic)",
    "GOOGLE_API_KEY": "Gemini (Google)",
    "GROQ_API_KEY": "Groq",
    "OPENAI_API_KEY": "OpenAI",
    "OLLAMA_API_KEY": "Ollama Cloud",
}

_ENV_PATH = app_dir() / ".env"
_LINE_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=")


def read_env_status() -> dict[str, bool]:
    """Return {KEY: is_set} for every known key, checking the live process env."""
    return {key: bool(os.getenv(key)) for key in KNOWN_KEYS}


def write_env_keys(values: dict[str, str]) -> None:
    """Update or append KEY=value lines in .env, then hot-reload into os.environ.

    Silently ignores keys not in KNOWN_KEYS and blank/whitespace-only values.
    """
    updates = {
        key: value.strip()
        for key, value in values.items()
        if key in KNOWN_KEYS and value and value.strip()
    }
    if not updates:
        return

    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() if _ENV_PATH.exists() else []
    remaining = dict(updates)

    for i, line in enumerate(lines):
        m = _LINE_RE.match(line)
        if m and m.group(1) in remaining:
            lines[i] = f"{m.group(1)}={remaining.pop(m.group(1))}"

    for key, value in remaining.items():
        lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=True)
