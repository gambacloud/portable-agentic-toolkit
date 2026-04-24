"""
Portable Agentic Toolkit — React UI entry point.
Run with: uv run python main.py
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass

import uvicorn

from db.database import init_db
from utils.logger import get_logger

log = get_logger(__name__)

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")
API_PORT = int(os.getenv("API_PORT", "8002"))
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

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
    log.info("%s ready — http://localhost:%d  (docs: http://localhost:%d/docs)", BOT_NAME, API_PORT, API_PORT)
    uvicorn.run(api, host="0.0.0.0", port=API_PORT, log_level="info")
