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
    "org_policy.yaml": """\
# Organizational policy — one file for the admin-controlled rules that used
# to live in separate configs. Edit via the API (admin-only) or by hand.

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
# model_limits:
#   "claude/*":
#     limit: 500000
#     period: month
model_limits: {}

# DLP (data-leak prevention): a local, non-LLM text scan run against outbound
# MCP tool-call arguments (the boundary where data actually leaves the app —
# Slack, Gmail, GitHub, etc). A generic set of technical patterns (API keys,
# private keys, JWTs, ...) is always active and always classified "secret";
# `patterns` below adds organization-specific terms on top of that.
#
# levels, low to high: public < internal < confidential < secret
# block_at_level: findings at or above this level are blocked unless the
# requesting user's role is manager or admin.
#
# Example:
# dlp:
#   block_at_level: secret
#   patterns:
#     - name: project_codename
#       level: confidential
#       keywords: ["Project Chimera"]
#     - name: customer_export_marker
#       level: secret
#       regex: "BEGIN CUSTOMER EXPORT"
dlp:
  block_at_level: secret
  patterns: []
""",
    "README.md": """\
# Settings Directory

Place files here to customise the Portable Agentic Toolkit:

| File | Purpose |
|------|---------|
| `system_prompt.md` | Extra instructions appended to every agent's system prompt |
| `user_prompt.md`   | Text prepended to every user message |
| `document_instructions.md` | Guidelines applied only when generating a draft/document/summary |
| `org_policy.yaml`  | Org-wide policy: per-model token budgets + DLP (data-leak) patterns |
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


# ── Org policy (settings/org_policy.yaml): model budgets + DLP ──────────────


def _load_org_policy() -> dict:
    p = SETTINGS_DIR / "org_policy.yaml"
    if p.exists():
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    # One-time migration from the old standalone model_limits.yaml, if present.
    legacy = SETTINGS_DIR / "model_limits.yaml"
    if legacy.exists():
        try:
            legacy_limits = (yaml.safe_load(legacy.read_text(encoding="utf-8")) or {}).get("limits") or {}
        except Exception:
            legacy_limits = {}
        merged = {"model_limits": legacy_limits, "dlp": {"block_at_level": "secret", "patterns": []}}
        _save_org_policy(merged)
        return merged
    return {}


def _save_org_policy(policy: dict) -> None:
    ensure_settings_dir()
    header = _TEMPLATES["org_policy.yaml"].split("\nmodel_limits:", 1)[0]
    body = yaml.safe_dump(policy, default_flow_style=False, allow_unicode=True, sort_keys=False)
    (SETTINGS_DIR / "org_policy.yaml").write_text(f"{header}\n{body}", encoding="utf-8")


def get_model_limits() -> dict[str, dict]:
    """{pattern: {"limit": int, "period": "month"|"session"}} from org_policy.yaml's model_limits section."""
    raw = _load_org_policy().get("model_limits") or {}
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
    """Overwrites the model_limits section. Each value needs {"limit": int, "period": "month"|"session"}."""
    policy = _load_org_policy()
    policy["model_limits"] = limits
    _save_org_policy(policy)


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


# ── DLP policy (also in org_policy.yaml) ─────────────────────────────────────

_DLP_LEVELS = ("public", "internal", "confidential", "secret")


def get_dlp_policy() -> dict:
    """{"block_at_level": str, "patterns": [{"name","level","keywords"?,"regex"?}, ...]}."""
    raw = _load_org_policy().get("dlp") or {}
    block_at = raw.get("block_at_level", "secret")
    patterns = []
    for p in raw.get("patterns") or []:
        if not isinstance(p, dict) or not p.get("name") or p.get("level") not in _DLP_LEVELS:
            continue
        if not p.get("keywords") and not p.get("regex"):
            continue
        patterns.append(p)
    return {
        "block_at_level": block_at if block_at in _DLP_LEVELS else "secret",
        "patterns": patterns,
    }


def save_dlp_policy(block_at_level: str, patterns: list[dict]) -> None:
    policy = _load_org_policy()
    policy["dlp"] = {"block_at_level": block_at_level, "patterns": patterns}
    _save_org_policy(policy)
