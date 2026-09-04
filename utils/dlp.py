"""Local, non-LLM text/technical scanner for outbound data.

Runs at the actual egress boundary (mcp_tools/registry.py, right before an
MCP tool call reaches an external service like Slack/Gmail/GitHub) rather
than on chat replies — that's where organizational data actually leaves the
app. Two pattern sources feed it:

  1. A small built-in set of technical secret patterns (API keys, private
     keys, JWTs, ...) — always active, always classified "secret".
  2. Org-defined patterns from settings/org_policy.yaml (utils.settings.
     get_dlp_policy) — keywords or regexes an admin maps to a level.

This is pattern matching, not semantic understanding: it catches literal
strings/formats, not a paraphrased description of the same secret. Treat it
as one layer, not a guarantee.
"""
from __future__ import annotations

import re

LEVELS = ("public", "internal", "confidential", "secret")
_RANK = {level: i for i, level in enumerate(LEVELS)}


def level_rank(level: str) -> int:
    return _RANK.get(level, 0)


def highest_level(findings: list[dict]) -> str:
    if not findings:
        return "public"
    return max(findings, key=lambda f: level_rank(f["level"]))["level"]


# Always-on technical patterns. Every one is "secret" — these are formats
# that are inherently sensitive (credentials), not organization-specific.
_BUILTIN_PATTERNS: list[tuple[str, str, "re.Pattern"]] = [
    ("aws_access_key_id", "secret", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", "secret", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("slack_token", "secret", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("jwt", "secret", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    (
        "generic_api_key_assignment",
        "secret",
        re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-/]{16,}"),
    ),
    ("github_token", "secret", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _find_credit_cards(text: str) -> list[dict]:
    findings = []
    for m in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            findings.append({"name": "credit_card_number", "level": "secret", "match": _redact(digits)})
    return findings


def _redact(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}{'*' * (len(s) - 8)}{s[-4:]}"


def _compile_custom(patterns: list[dict]) -> list[tuple[str, str, str, "re.Pattern"]]:
    """Returns (name, level, action, compiled_regex). action is "block" or "redact" —
    only meaningful for custom org patterns; builtin technical patterns are always
    "block" (masking a credential breaks the destination call anyway)."""
    compiled = []
    for p in patterns:
        name, level = p["name"], p["level"]
        action = p.get("action", "block")
        if action not in ("block", "redact"):
            action = "block"
        if p.get("regex"):
            try:
                compiled.append((name, level, action, re.compile(p["regex"], re.IGNORECASE)))
            except re.error:
                continue
        elif p.get("keywords"):
            escaped = "|".join(re.escape(k) for k in p["keywords"] if k)
            if escaped:
                compiled.append((name, level, action, re.compile(escaped, re.IGNORECASE)))
    return compiled


def scan_text(text: str, custom_patterns: list[dict] | None = None) -> list[dict]:
    """Returns findings: [{"name", "level", "action", "match"}, ...] — one entry
    per matching pattern (not per occurrence), match text redacted/truncated."""
    if not text:
        return []
    findings: list[dict] = []

    for name, level, rx in _BUILTIN_PATTERNS:
        m = rx.search(text)
        if m:
            findings.append({"name": name, "level": level, "action": "block", "match": _redact(m.group(0))})

    for f in _find_credit_cards(text):
        f["action"] = "block"
        findings.append(f)

    for name, level, action, rx in _compile_custom(custom_patterns or []):
        m = rx.search(text)
        if m:
            snippet = m.group(0)
            findings.append({"name": name, "level": level, "action": action, "match": snippet[:40]})

    return findings


def redact_text(text: str, findings: list[dict], custom_patterns: list[dict] | None = None) -> str:
    """Replaces matches from "redact"-action findings with [REDACTED:name]. Any
    "block"-action finding among `findings` means the caller should have blocked
    already — this is only meant to run on the surviving redact-only findings."""
    redact_names = {f["name"] for f in findings if f.get("action") == "redact"}
    if not redact_names:
        return text
    for name, _level, action, rx in _compile_custom(custom_patterns or []):
        if name in redact_names and action == "redact":
            text = rx.sub(f"[REDACTED:{name}]", text)
    return text
