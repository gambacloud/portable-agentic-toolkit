"""
Central logging configuration for the Portable Agentic Toolkit.

Usage:
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Something happened")

Outputs to both console (INFO+) and logs/app.log (DEBUG+).
Log level can be overridden with the LOG_LEVEL env var.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"
LOG_LEVEL_CONSOLE = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL_FILE = "DEBUG"

_CONSOLE_FMT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
_FILE_FMT = "%(asctime)s [%(levelname)-8s] %(name)s (%(filename)s:%(lineno)d) — %(message)s"
_DATE_FMT = "%H:%M:%S"

_configured = False


def _configure():
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger("pat")  # "portable agentic toolkit" namespace
    root.setLevel(logging.DEBUG)
    root.propagate = False

    # ── Console handler ──────────────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, LOG_LEVEL_CONSOLE, logging.INFO))
    ch.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
    root.addHandler(ch)

    # ── Rotating file handler (10 MB × 3 files) ──────────────────────────────
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
    root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'pat' namespace."""
    _configure()
    # Strip leading package path so names stay short: "agents.crew" not "pat.agents.crew"
    short = name.removeprefix("pat.") if name.startswith("pat.") else name
    return logging.getLogger(f"pat.{short}")
