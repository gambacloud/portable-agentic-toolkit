# Portable Agentic Toolkit

A fully **local**, privacy-first AI agent workspace.
All computation — model inference, tool calls, data — stays on your machine.
No cloud. No telemetry. No API keys required to get started.

---

## Features

- **Zero-cloud privacy** — Ollama runs models locally; nothing leaves your machine
- **One-command setup** — `bootstrap.bat` / `bootstrap.sh` installs everything from scratch
- **Self-extending tools** — drop a `config.json` into `bin/mcp_servers/` and new tools are auto-loaded on next start
- **Live agent thinking** — toggle "Show agent thinking" to watch every ReAct step in real time
- **Human-in-the-loop** — tools marked `requires_confirmation: true` pause and ask before executing
- **Model switcher** — change the LLM mid-session from the settings panel without restarting
- **Git exporter** — `scripts/git_export.py` cleans `.venv`, caches, and logs before committing

---

## Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| [Ollama](https://ollama.com/download) | Latest | Must be installed before bootstrap |
| Python | 3.11+ | Managed automatically by `uv` |
| RAM | 16 GB+ | 8 GB works for small models (phi3) |
| Disk | ~10 GB | For models + dependencies |

---

## Quick start

### Windows
```bat
bootstrap.bat
```

### macOS / Linux
```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

The script will:
1. Install `uv` (Python env manager) if missing
2. Verify Ollama is installed and start it if needed
3. Create an isolated `.venv` and install all dependencies
4. Pull the default model (`llama3.2`)
5. Find a free port (starting at 8000) and open the UI

---

## Project layout

```
├── app.py                  Chainlit UI entry point
├── agents/
│   └── crew.py             CrewAI agent builder (reads config/agents.yaml)
├── mcp_tools/
│   └── registry.py         MCP auto-discovery + CrewAI tool wrappers
├── utils/
│   └── ollama_utils.py     Ollama helpers (list models, health check)
├── bin/
│   └── mcp_servers/        ← drop MCP server configs here
│       └── README.md       Schema + examples for config.json
├── config/
│   └── agents.yaml         Agent role / goal / backstory + default models
├── scripts/
│   ├── git_export.py       Clean project for Git distribution
│   └── pull_models.py      Pull / list Ollama models
├── bootstrap.bat           Windows setup + launch
├── bootstrap.sh            macOS/Linux setup + launch
├── pyproject.toml          Python dependencies (managed by uv)
└── .env.example            API key template (copy to .env)
```

---

## Adding MCP tools

Create a directory under `bin/mcp_servers/` with a `config.json`:

```json
{
  "name": "filesystem",
  "description": "Read and write local files",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/you/Documents"],
  "enabled": true,
  "requires_confirmation": false
}
```

Restart the app — tools are discovered automatically at startup.

### Popular servers

```bash
# File system access
npx -y @modelcontextprotocol/server-filesystem <directory>

# Web search (needs BRAVE_API_KEY in .env)
npx -y @modelcontextprotocol/server-brave-search

# SQLite database
npx -y @modelcontextprotocol/server-sqlite path/to/db.sqlite

# GitHub (needs GITHUB_TOKEN in .env)
npx -y @modelcontextprotocol/server-github
```

More at [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers).

---

## Customising the agent

Edit `config/agents.yaml` to change the agent's personality, goal, or default models — no Python changes needed:

```yaml
agents:
  - name: assistant
    role: "Senior Data Engineer"
    goal: "Help build and debug data pipelines"
    backstory: "You specialise in Fivetran, dbt, and SQL..."

default_models:
  - llama3.2
  - phi3
```

---

## Useful commands

```bash
# Start the UI manually
uv run chainlit run app.py

# Pull additional models
uv run python scripts/pull_models.py --model phi3
uv run python scripts/pull_models.py --list

# Clean before committing
uv run python scripts/git_export.py --dry-run
uv run python scripts/git_export.py
```

---

## Architecture

```
User browser
    │
    ▼
Chainlit UI (app.py)          ← async event loop
    │  asyncio.to_thread()
    ▼
CrewAI Agent (agents/crew.py) ← sync, runs in worker thread
    │  BaseTool._run()
    ▼
MCP Registry (mcp_tools/)     ← asyncio.run() per tool call
    │  stdio transport
    ▼
MCP Server processes          ← spawned on demand from bin/mcp_servers/
    │
    ▼
Ollama API (localhost:11434)  ← local model inference
```

Human-in-the-loop confirmations are bridged back from the worker thread to the Chainlit event loop via `asyncio.run_coroutine_threadsafe`.

---

## License

MIT
