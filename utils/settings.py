"""User-editable settings directory next to the EXE (or project root in dev)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from utils.paths import app_dir

SETTINGS_DIR = app_dir() / "settings"

_LOGO_EXTENSIONS = ("png", "jpg", "jpeg", "svg", "webp")

_TEMPLATES: dict[str, str] = {
    "system_prompt.md": """\
# Additional System Instructions

Add any custom instructions here. They are appended to every agent's system
prompt. Useful for company context, tone guidelines, or domain knowledge.

Examples:
- "Always reply in Hebrew."
- "We are an e-commerce company called Acme. Prices are in USD."
- "Never reveal internal tool names to the user."
""",
    "user_prompt.md": """\
# User Prompt Prefix

Text here is prepended to every user message before it reaches the AI.
Leave this empty (or only comments) to disable.

Examples:
- "Context: today is {date}. The user is an expert developer."
- "Always respond concisely, max 3 sentences unless asked for more."
""",
    "document_instructions.md": """\
# Document / Summary Branding

Instructions here are only used when the agent generates a draft, document,
or summary (not regular chat replies). Describe tone, required structure,
a footer/disclaimer to include, or how to describe your brand colors in
words (output is plain text, not styled).

Examples:
- "Sign off every document with: Acme Inc. — Confidential."
- "Use a formal, concise tone. Always include a one-line TL;DR at the top."
- "Our brand colors are navy blue and gold — mention them only if the user
   asks about visual styling, not in the document body."
""",
    "model_limits.yaml": """\
# Per-model token budgets (optional). Nothing here means no model-specific
# limit — only the global per-user budget (see /users/me/budget) applies.
#
# Key = exact model id (e.g. "claude/claude-sonnet-4-6") or a provider
# prefix ending in "*" (e.g. "claude/*") to cover every model from that
# provider. The most specific matching key wins.
#
# period: "month" (resets every calendar month, default) or "session"
# (resets per conversation).
#
# Example:
# limits:
#   "claude/*":
#     limit: 500000
#     period: month
#   "claude/claude-opus-4-7":
#     limit: 100000
#     period: session

limits: {}
""",
    "README.md": """\
# Settings Directory

Place files here to customise the Portable Agentic Toolkit:

| File | Purpose |
|------|---------|
| `system_prompt.md` | Extra instructions appended to every agent's system prompt |
| `user_prompt.md`   | Text prepended to every user message |
| `document_instructions.md` | Guidelines applied only when generating a draft/document/summary |
| `model_limits.yaml` | Per-model token budgets (e.g. cap "claude/*" usage) |
| `logo.png`         | Custom logo shown in the UI (also: .jpg, .jpeg, .svg, .webp) |

Restart the app after editing these files, or use `/branding-ui` to edit
the logo and document instructions live without restarting.
""",
}


def ensure_settings_dir() -> None:
    SETTINGS_DIR.mkdir(exist_ok=True)
    for name, content in _TEMPLATES.items():
        p = SETTINGS_DIR / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")


def _load_md(name: str) -> str:
    p = SETTINGS_DIR / name
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
        # Strip markdown comments (<!-- ... -->)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        # Strip level-1 headings (template headers)
        text = re.sub(r"^#\s+.+\n?", "", text, flags=re.MULTILINE)
        return text.strip()
    except Exception:
        return ""


def get_system_prompt_extra() -> str:
    return _load_md("system_prompt.md")


def get_user_prompt_prefix() -> str:
    return _load_md("user_prompt.md")


def get_document_instructions() -> str:
    return _load_md("document_instructions.md")


def save_document_instructions(text: str) -> None:
    ensure_settings_dir()
    header = _TEMPLATES["document_instructions.md"].split("\n\n", 1)[0]
    (SETTINGS_DIR / "document_instructions.md").write_text(f"{header}\n\n{text.strip()}\n", encoding="utf-8")


def get_logo_path() -> Path | None:
    for ext in _LOGO_EXTENSIONS:
        p = SETTINGS_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None


def get_logo_filename() -> str | None:
    p = get_logo_path()
    return p.name if p else None


def save_logo(data: bytes, ext: str) -> None:
    ext = ext.lower().lstrip(".")
    if ext not in _LOGO_EXTENSIONS:
        raise ValueError(f"Unsupported logo extension: '{ext}'. Use one of {_LOGO_EXTENSIONS}.")
    ensure_settings_dir()
    for existing in _LOGO_EXTENSIONS:
        stale = SETTINGS_DIR / f"logo.{existing}"
        if stale.exists():
            stale.unlink()
    (SETTINGS_DIR / f"logo.{ext}").write_bytes(data)


def get_model_limits() -> dict[str, dict]:
    """Parses settings/model_limits.yaml into {pattern: {"limit": int, "period": "month"|"session"}}."""
    p = SETTINGS_DIR / "model_limits.yaml"
    if not p.exists():
        return {}
    try:
        raw = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("limits") or {}
    except Exception:
        return {}

    out: dict[str, dict] = {}
    for pattern, cfg in raw.items():
        if not isinstance(cfg, dict) or not cfg.get("limit"):
            continue
        period = cfg.get("period", "month")
        out[pattern] = {
            "limit": int(cfg["limit"]),
            "period": period if period in ("month", "session") else "month",
        }
    return out


def save_model_limits(limits: dict[str, dict]) -> None:
    """Overwrites settings/model_limits.yaml's `limits` map. Each value needs
    {"limit": int, "period": "month"|"session"}."""
    ensure_settings_dir()
    header = _TEMPLATES["model_limits.yaml"].rsplit("limits: {}", 1)[0]
    body = yaml.safe_dump({"limits": limits}, default_flow_style=False, allow_unicode=True, sort_keys=True)
    (SETTINGS_DIR / "model_limits.yaml").write_text(f"{header}{body}", encoding="utf-8")


def resolve_model_limit(model: str) -> dict | None:
    """Finds the most specific configured limit for a model id (exact match, then longest '*' prefix)."""
    limits = get_model_limits()
    if model in limits:
        return limits[model]
    best_pattern, best_cfg = None, None
    for pattern, cfg in limits.items():
        if pattern.endswith("*") and model.startswith(pattern[:-1]):
            if best_pattern is None or len(pattern) > len(best_pattern):
                best_pattern, best_cfg = pattern, cfg
    return best_cfg
