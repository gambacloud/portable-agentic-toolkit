#!/usr/bin/env bash
# Portable Agentic Toolkit — Bootstrap (macOS / Linux)
set -euo pipefail

echo ""
echo "================================================"
echo "  Portable Agentic Toolkit - Bootstrap"
echo "================================================"
echo ""

# ── Step 1: Check / install uv ─────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "[1/6] Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo ""
        echo "ERROR: uv installation failed."
        echo "Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    echo "[1/6] uv installed."
else
    echo "[1/6] uv found."
fi

# ── Step 2: Check Node.js ──────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    echo ""
    echo "ERROR: Node.js not found."
    echo "Install from: https://nodejs.org (LTS version)"
    exit 1
fi
echo "[2/6] Node.js found."

# ── Step 3: Check Ollama ────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo ""
    echo "ERROR: Ollama not found."
    echo "Install from: https://ollama.com/download"
    echo "Then re-run this script."
    exit 1
fi
echo "[3/6] Ollama found."

# Start Ollama if not running
if ! ollama list &>/dev/null; then
    echo "  Starting Ollama service in background..."
    ollama serve &>/dev/null &
    sleep 3
    if ! ollama list &>/dev/null; then
        echo "  WARNING: Could not start Ollama. Start it manually and re-run."
    fi
fi

# ── Step 3b: Ensure .env exists ────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "  Created .env from .env.example."
    else
        touch .env
    fi
fi

# ── Step 4: Install Python dependencies ────────────────────────────────────
echo "[4/6] Installing Python dependencies (this may take a minute)..."
uv sync --no-dev
echo "  Dependencies installed."

# ── Step 5: Build React frontend ───────────────────────────────────────────
echo "[5/6] Building React frontend..."
cd frontend
npm install --silent
npm run build
cd ..
echo "  Frontend built."

# ── Step 6: Pull default model and launch ──────────────────────────────────
echo "[6/6] Pulling default model (llama3.2)..."
ollama pull llama3.2 || {
    echo "  WARNING: Could not pull llama3.2."
    echo "  Pull manually with:  ollama pull llama3.2"
}

echo ""
echo "  Access the toolkit at:  http://localhost:8002"
echo "  API docs at:            http://localhost:8002/docs"
echo "  Press Ctrl+C to stop."
echo ""
uv run python main.py
