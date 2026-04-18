"""
Git Exporter — clean the project for a pristine Git commit / distribution.

Usage:
    uv run python scripts/git_export.py [--dry-run]

What it removes:
  - .venv/
  - __pycache__/ and *.pyc / *.pyo
  - .chainlit/translations/ (auto-generated, bulky)
  - .files/ (Chainlit uploads)
  - chainlit.db (Chainlit session data)
  - *.log files
  - .DS_Store, Thumbs.db
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Directories to delete entirely
DIRS_TO_REMOVE = [
    ".venv",
    ".files",
    ".chainlit/translations",
]

# File patterns to delete recursively
FILE_PATTERNS = [
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.log",
    "chainlit.db",
    "**/.DS_Store",
    "**/Thumbs.db",
]


def main():
    parser = argparse.ArgumentParser(description="Clean project for Git export")
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would be removed without deleting"
    )
    args = parser.parse_args()
    dry = args.dry_run

    removed: list[Path] = []

    # ── Named directories ────────────────────────────────────────────────────
    for rel in DIRS_TO_REMOVE:
        path = ROOT / rel
        if path.exists():
            removed.append(path)
            if not dry:
                shutil.rmtree(path, ignore_errors=True)

    # ── Glob patterns ────────────────────────────────────────────────────────
    for pattern in FILE_PATTERNS:
        for match in ROOT.glob(pattern):
            if match.exists():
                removed.append(match)
                if not dry:
                    if match.is_dir():
                        shutil.rmtree(match, ignore_errors=True)
                    else:
                        match.unlink(missing_ok=True)

    # ── Report ───────────────────────────────────────────────────────────────
    if not removed:
        print("Nothing to clean — project is already tidy.")
        return

    label = "[DRY RUN] Would remove" if dry else "Removed"
    print(f"{label} {len(removed)} item(s):")
    for p in removed:
        print(f"  {p.relative_to(ROOT)}")

    if dry:
        print("\nRun without --dry-run to actually delete these.")
    else:
        print("\nDone. Ready to commit or zip.")


if __name__ == "__main__":
    main()
