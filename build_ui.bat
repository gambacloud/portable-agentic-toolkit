@echo off
setlocal enabledelayedexpansion
title Build GAMBABOT UI

echo.
echo ================================================
echo   Build GAMBABOT UI (React Frontend)
echo ================================================
echo.

:: ── Check Node.js ─────────────────────────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Please install Node.js first.
    pause & exit /b 1
)

:: ── Build React frontend ──────────────────────────────────────────────────────
echo [1/2] Installing npm dependencies...
cd frontend
call npm install --silent
if errorlevel 1 ( echo ERROR: npm install failed & cd .. & pause & exit /b 1 )

echo [2/2] Building production bundle...
call npm run build
if errorlevel 1 ( echo ERROR: npm build failed & cd .. & pause & exit /b 1 )

cd ..
echo.
echo   UI Build successful!
echo   The built files are located in frontend\dist
echo.
pause
