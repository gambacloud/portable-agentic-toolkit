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
    echo [1/5] Installing uv package manager...
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
    echo [1/5] uv installed successfully.
) else (
    echo [1/5] uv found.
)

:: ── Step 2: Check Ollama ─────────────────────────────────────────────────────
where ollama >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Ollama not found.
    echo Download and install from: https://ollama.com/download/windows
    echo Then re-run this script.
    pause
    exit /b 1
)
echo [2/5] Ollama found.

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

:: ── Step 2b: Ensure .env exists with a JWT secret ───────────────────────────
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo   Created .env from .env.example.
    ) else (
        type nul > .env
    )
)
findstr /R /C:"^CHAINLIT_AUTH_SECRET=" .env >nul 2>&1
if errorlevel 1 (
    for /f "delims=" %%i in ('powershell -Command "[guid]::NewGuid().ToString(\"N\") + [guid]::NewGuid().ToString(\"N\")"') do set JWT=%%i
    echo CHAINLIT_AUTH_SECRET=!JWT!>> .env
    echo   JWT secret generated and saved to .env.
)

:: ── Step 3: Create venv and install dependencies ─────────────────────────────
echo [3/5] Installing Python dependencies (this may take a minute)...
uv sync --no-dev
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    echo Check the error above, then re-run.
    pause
    exit /b 1
)
echo   Dependencies installed.

:: ── Step 4: Pull default LLM model ──────────────────────────────────────────
echo [4/5] Pulling default model (llama3.2)...
ollama pull llama3.2
if errorlevel 1 (
    echo   WARNING: Could not pull llama3.2.
    echo   Pull a model manually with:  ollama pull llama3.2
    echo   Then re-run bootstrap or just use: uv run chainlit run app.py
)

:: ── Step 5: Find free port and launch Chainlit UI ────────────────────────────
echo [5/5] Launching UI...

set PORT=8000
:find_port
powershell -Command "if (Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>&1
if errorlevel 1 (
    set /a PORT=%PORT%+1
    goto find_port
)

echo.
echo   Access the toolkit at:  http://localhost:%PORT%
echo   Press Ctrl+C to stop.
echo.
uv run chainlit run app.py --port %PORT% --host localhost --no-cache

pause
