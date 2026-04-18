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
    echo "[1/5] Installing uv package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo ""
        echo "ERROR: uv installation failed."
        echo "Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    echo "[1/5] uv installed."
else
    echo "[1/5] uv found."
fi

# ── Step 2: Check Ollama ────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo ""
    echo "ERROR: Ollama not found."
    echo "Install from: https://ollama.com/download"
    echo "Then re-run this script."
    exit 1
fi
echo "[2/5] Ollama found."

# Start Ollama if not running
if ! ollama list &>/dev/null; then
    echo "  Starting Ollama service in background..."
    ollama serve &>/dev/null &
    OLLAMA_PID=$!
    sleep 3
    if ! ollama list &>/dev/null; then
        echo "  WARNING: Could not start Ollama. Start it manually and re-run."
    fi
fi

# ── Step 3: Install dependencies ────────────────────────────────────────────
echo "[3/5] Installing Python dependencies (this may take a minute)..."
uv sync --no-dev
echo "  Dependencies installed."

# ── Step 4: Pull default model ──────────────────────────────────────────────
echo "[4/5] Pulling default model (llama3.2)..."
ollama pull llama3.2 || {
    echo "  WARNING: Could not pull llama3.2."
    echo "  Pull manually with:  ollama pull llama3.2"
}

# ── Step 5: Find free port and launch Chainlit UI ──────────────────────────
echo "[5/5] Launching UI..."

PORT=8000
while lsof -iTCP:"$PORT" -sTCP:LISTEN &>/dev/null 2>&1 || \
      nc -z localhost "$PORT" &>/dev/null 2>&1; do
    PORT=$((PORT + 1))
done

echo ""
echo "  Access the toolkit at:  http://localhost:$PORT"
echo "  Press Ctrl+C to stop."
echo ""
uv run chainlit run app.py --port "$PORT" --host localhost --no-cache
