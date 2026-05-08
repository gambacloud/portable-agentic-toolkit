"""
Portable Agentic Toolkit — React UI entry point.
Run with: uv run python main.py
"""
import os
from pathlib import Path

import uvicorn

from utils.paths import app_dir, bundle_dir

try:
    from dotenv import load_dotenv
    load_dotenv(app_dir() / ".env", override=False)
except ImportError:
    pass

from db.database import init_db
from utils.logger import get_logger

log = get_logger(__name__)

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")
API_PORT = int(os.getenv("API_PORT", "8002"))
FRONTEND_DIST = bundle_dir() / "frontend" / "dist"

init_db()
log.info("%s starting — DB initialised", BOT_NAME)

from scheduler.engine import get_engine as _get_scheduler  # noqa: E402
_get_scheduler().start()
log.info("Scheduler started")

from api.server import api  # noqa: E402

# Serve the React production build if it exists
if FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles
    api.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    log.info("Serving React frontend from %s", FRONTEND_DIST)
else:
    log.warning(
        "Frontend dist not found — run 'cd frontend && npm install && npm run build' first.\n"
        "For development, run the React dev server separately: cd frontend && npm run dev"
    )

if __name__ == "__main__":
    import threading
    import webbrowser

    url = f"http://localhost:{API_PORT}"
    log.info("%s ready — %s  (docs: %s/docs)", BOT_NAME, url, url)

    # Open browser after server is up (0.5 s delay)
    threading.Timer(0.5, webbrowser.open, args=[url]).start()

    uvicorn.run(api, host="127.0.0.1", port=API_PORT, log_level="warning")
