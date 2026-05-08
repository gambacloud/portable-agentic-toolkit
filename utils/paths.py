"""Runtime path resolution — works both as script and as PyInstaller EXE."""
import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory for persistent user data (DB, ChromaDB, uploads).

    PyInstaller --onefile: parent of the EXE (not the temp _MEIPASS dir).
    Normal script:        project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def bundle_dir() -> Path:
    """Directory where read-only bundled assets live (frontend/dist, config).

    PyInstaller --onefile: sys._MEIPASS (temp extraction dir).
    Normal script:        project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.parent
