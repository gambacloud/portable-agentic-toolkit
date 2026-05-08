# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Portable Agentic Toolkit.
Produces a single PortableAgenticToolkit.exe (~150-250 MB).

Build:
  Windows:       build_exe.bat
  macOS/Linux:   ./build_exe.sh
  GitHub CI:     triggered automatically on version tags.
"""
from pathlib import Path

ROOT = Path(".").resolve()

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "frontend" / "dist"), "frontend/dist"),
        (str(ROOT / "config"), "config"),
        (str(ROOT / "bin" / "mcp_servers"), "bin/mcp_servers"),
    ],
    hiddenimports=[
        # uvicorn
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # chromadb — include all dynamically-loaded classes (config.get_class)
        "chromadb",
        "chromadb.api",
        "chromadb.api.client",
        "chromadb.api.segment",
        "chromadb.config",
        "chromadb.db.impl",
        "chromadb.db.impl.sqlite",
        "chromadb.db.mixins.embeddings_queue",
        "chromadb.db.mixins.sysdb",
        "chromadb.db.mixins.embeddings",
        "chromadb.segment",
        "chromadb.segment.impl",
        "chromadb.segment.impl.vector",
        "chromadb.segment.impl.vector.local_hnsw",
        "chromadb.segment.impl.metadata",
        "chromadb.segment.impl.metadata.sqlite",
        "chromadb.execution",
        "chromadb.execution.executor",
        "chromadb.execution.executor.local",
        "chromadb.quota",
        "chromadb.quota.noop",
        "chromadb.rate_limiting",
        "chromadb.rate_limiting.noop",
        "chromadb.telemetry",
        "chromadb.telemetry.product",
        "chromadb.telemetry.product.posthog",
        # starlette / fastapi
        "starlette.routing",
        "starlette.websockets",
        "fastapi.middleware.cors",
        # scheduling
        "apscheduler.triggers.cron",
        "apscheduler.schedulers.background",
        # misc
        "ollama",
        "mcp",
        "yaml",
        "dotenv",
        "litellm",
        "anthropic",
        "openai",
        "pypdf",
        "docx",
        "openpyxl",
        "sqlite3",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "cv2", "jupyter", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PortableAgenticToolkit",
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=None,
)
