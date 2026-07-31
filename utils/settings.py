"""User-editable settings directory next to the EXE (or project root in dev)."""
from __future__ import annotations

import re
from pathlib import Path

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
    "README.md": """\
# Settings Directory

Place files here to customise the Portable Agentic Toolkit:

| File | Purpose |
|------|---------|
| `system_prompt.md` | Extra instructions appended to every agent's system prompt |
| `user_prompt.md`   | Text prepended to every user message |
| `document_instructions.md` | Guidelines applied only when generating a draft/document/summary |
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
