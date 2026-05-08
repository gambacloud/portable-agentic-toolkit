@echo off
setlocal enabledelayedexpansion
title Build PortableAgenticToolkit.exe

echo.
echo ================================================
echo   Build PortableAgenticToolkit.exe
echo ================================================
echo.

:: ── Check uv ─────────────────────────────────────────────────────────────────
where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv not found. Run bootstrap.bat first.
    pause & exit /b 1
)

:: ── Check Node.js ─────────────────────────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Run bootstrap.bat first.
    pause & exit /b 1
)

:: ── Build React frontend ──────────────────────────────────────────────────────
echo [1/3] Building React frontend...
cd frontend
call npm install --silent
if errorlevel 1 ( echo ERROR: npm install failed & cd .. & pause & exit /b 1 )
call npm run build
if errorlevel 1 ( echo ERROR: npm build failed & cd .. & pause & exit /b 1 )
cd ..
echo   Frontend built.

:: ── Install PyInstaller ───────────────────────────────────────────────────────
echo [2/3] Installing PyInstaller...
uv run pip install pyinstaller --quiet
if errorlevel 1 ( echo ERROR: PyInstaller install failed & pause & exit /b 1 )

:: ── Run PyInstaller ───────────────────────────────────────────────────────────
echo [3/3] Bundling EXE (this takes 2-5 minutes)...
uv run pyinstaller build.spec --clean --noconfirm
if errorlevel 1 ( echo ERROR: PyInstaller failed & pause & exit /b 1 )

echo.
if exist "dist\PortableAgenticToolkit.exe" (
    for %%F in ("dist\PortableAgenticToolkit.exe") do (
        set /a SIZE=%%~zF / 1048576
        echo   Build successful^^!
        echo   Output: dist\PortableAgenticToolkit.exe  (!SIZE! MB^)
        echo.
        echo   Run with:  dist\PortableAgenticToolkit.exe
    )
) else (
    echo   Build failed. Check output above.
)
echo.
pause
