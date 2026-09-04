"""Per-user auth: password hashing, the session-signing secret, and
Personal Access Tokens (PATs) for non-interactive/API callers.

Login flow: a user's password is checked here, then api/server.py stores
their real user_id in a signed session cookie (Starlette SessionMiddleware).
Everything downstream (current_user, require_role, ...) trusts the session,
never a client-supplied header — that's what makes this "real accounts"
instead of the old shared-token gate.

This module deliberately avoids adding a hashing dependency (bcrypt/passlib)
— PBKDF2-HMAC-SHA256 from the stdlib is enough for a locally-run app and
keeps the PyInstaller build simple.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from utils.paths import app_dir

_BOOTSTRAP_PW_PATH = app_dir() / ".auth_token"  # first-run admin password (same file as the old shared-token gate)
_SESSION_SECRET_PATH = app_dir() / ".session_secret"

_PBKDF2_ITERATIONS = 260_000


def get_or_create_bootstrap_password() -> str:
    """The local admin account's first-run password. Generated once, persisted,
    and only meaningful until an admin changes it via the API."""
    if _BOOTSTRAP_PW_PATH.exists():
        pw = _BOOTSTRAP_PW_PATH.read_text(encoding="utf-8").strip()
        if pw:
            return pw
    pw = secrets.token_urlsafe(18)
    _BOOTSTRAP_PW_PATH.write_text(pw, encoding="utf-8")
    return pw


def get_or_create_session_secret() -> str:
    if _SESSION_SECRET_PATH.exists():
        secret = _SESSION_SECRET_PATH.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    secret = secrets.token_urlsafe(32)
    _SESSION_SECRET_PATH.write_text(secret, encoding="utf-8")
    return secret


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations, salt, hash_hex = (stored_hash or "").split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def generate_pat() -> str:
    """A personal access token shown to the caller exactly once at creation time."""
    return "pat_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """One-way hash for storing PATs (only the hash is kept in the DB). No salt needed —
    unlike passwords, PATs are already high-entropy random strings, not human-chosen."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
