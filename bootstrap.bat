@echo off
setlocal enabledelayedexpansion
title Portable Agentic Toolkit - Bootstrap

echo.
echo ================================================
echo   Portable Agentic Toolkit - Bootstrap
echo ================================================
echo.

:: ── Step 1: Check / install uv ──────────────────────────────────────────────
where uv >nul 2>&1
if errorlevel 1 (
    echo [1/6] Installing uv package manager...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ERROR: uv installation failed.
        echo Install manually from: https://docs.astral.sh/uv/getting-started/installation/
        pause
        exit /b 1
    )
    echo [1/6] uv installed successfully.
) else (
    echo [1/6] uv found.
)

:: ── Step 2: Check Node.js ─────────────────────────────────────────────────────
node --version >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramFiles%\nodejs\node.exe" (
        set "PATH=%ProgramFiles%\nodejs;%PATH%"
    ) else if exist "%ProgramFiles(x86)%\nodejs\node.exe" (
        set "PATH=%ProgramFiles(x86)%\nodejs;%PATH%"
    ) else (
        echo.
        echo ERROR: Node.js not found.
        echo Download and install from: https://nodejs.org (LTS version)
        echo Then re-run this script.
        pause
        exit /b 1
    )
)
node --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Node.js found but could not run. Try restarting your PC.
    pause
    exit /b 1
)
echo [2/6] Node.js found.

:: ── Step 3: Check Ollama ─────────────────────────────────────────────────────
where ollama >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Ollama not found.
    echo Download and install from: https://ollama.com/download/windows
    echo Then re-run this script.
    pause
    exit /b 1
)
echo [3/6] Ollama found.

:: Start Ollama service if not already running
ollama list >nul 2>&1
if errorlevel 1 (
    echo   Starting Ollama service in background...
    start "" /b ollama serve
    timeout /t 4 /nobreak >nul
    ollama list >nul 2>&1
    if errorlevel 1 (
        echo   WARNING: Could not start Ollama automatically.
        echo   Please start Ollama manually and re-run.
    )
)

:: ── Step 3b: Ensure .env exists ───────────────────────────────────────────────
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo   Created .env from .env.example.
    ) else (
        type nul > .env
    )
)

:: ── Step 4: Install Python dependencies ──────────────────────────────────────
echo [4/6] Installing Python dependencies (this may take a minute)...
uv sync --no-dev
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    echo Check the error above, then re-run.
    pause
    exit /b 1
)
echo   Python dependencies installed.

:: ── Step 5: Build React frontend ─────────────────────────────────────────────
echo [5/6] Building React frontend...
cd frontend
call npm install --silent
if errorlevel 1 (
    echo.
    echo ERROR: npm install failed.
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo.
    echo ERROR: React build failed.
    pause
    exit /b 1
)
cd ..
echo   Frontend built successfully.

:: ── Step 6: Pull default LLM model and launch ────────────────────────────────
echo [6/6] Pulling default model (llama3.2)...
ollama pull llama3.2
if errorlevel 1 (
    echo   WARNING: Could not pull llama3.2.
    echo   Pull a model manually with:  ollama pull llama3.2
)

echo.
echo   Access the toolkit at:  http://localhost:8002
echo   API docs at:            http://localhost:8002/docs
echo   Press Ctrl+C to stop.
echo.
uv run python main.py

pause
