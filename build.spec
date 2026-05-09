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
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(".").resolve()

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[
        (str(ROOT / ".venv" / "Lib" / "site-packages" / "chromadb_rust_bindings" / "chromadb_rust_bindings.pyd"), "chromadb_rust_bindings"),
    ],
    datas=[
        (str(ROOT / "frontend" / "dist"), "frontend/dist"),
        (str(ROOT / "config"), "config"),
        (str(ROOT / "bin" / "mcp_servers"), "bin/mcp_servers"),
        *collect_data_files("litellm"),
        *collect_data_files("tiktoken"),
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
        "chromadb.api.rust",           # default chroma_api_impl in 1.x (RustBindingsAPI)
        "chromadb.api.segment",
        "chromadb.config",
        "chromadb.db.impl.sqlite",
        "chromadb.db.impl.sqlite_pool",
        "chromadb.db.mixins.embeddings_queue",
        "chromadb.db.mixins.sysdb",
        "chromadb.segment.impl.manager.local",
        "chromadb.segment.impl.vector.local_hnsw",
        "chromadb.segment.impl.metadata.sqlite",
        "chromadb.execution.executor.local",
        "chromadb.quota.simple_quota_enforcer",
        "chromadb.rate_limit.simple_rate_limit",
        "chromadb.telemetry",
        "chromadb.telemetry.product",
        "chromadb.telemetry.product.posthog",
        "chromadb_rust_bindings",      # compiled Rust extension required by chromadb.api.rust
        # starlette / fastapi
        "starlette.routing",
        "starlette.websockets",
        "fastapi.middleware.cors",
        # scheduling
        "apscheduler.triggers.cron",
        "apscheduler.schedulers.background",
        # project modules — many are lazy-imported inside functions at runtime
        "agents",
        "agents.runner",
        "api.chat",
        "db.database",
        "db.queries",
        "mcp_tools.installer",
        "mcp_tools.registry",
        "mcp_tools.scheduler_tools",
        "rag.embedder",
        "rag.indexer",
        "rag.retriever",
        "rag.tool",
        "scheduler.engine",
        "utils.logger",
        "utils.ollama_utils",
        "utils.paths",
        "utils.settings",
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
        # tiktoken — encoding registry is discovered via importlib.metadata plugins
        "tiktoken",
        "tiktoken.core",
        "tiktoken.load",
        "tiktoken.model",
        "tiktoken.registry",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
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
