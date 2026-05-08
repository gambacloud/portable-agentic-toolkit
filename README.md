# Portable Agentic Toolkit

A **local-first, privacy-forward** AI agent workspace.
Runs entirely on your machine (Ollama) or connects to cloud LLMs (Claude, Groq) via API keys.

---

## Features

- **Local or cloud LLMs** — Ollama for local inference; Claude (Anthropic) and Groq via API key
- **One-command setup** — `bootstrap.bat` / `bootstrap.sh` installs everything from scratch
- **Self-extending tools** — drop a `config.json` into `bin/mcp_servers/` and new tools auto-load on restart
- **Live agent thinking** — toggle "Show agent thinking" to watch every ReAct step in real time
- **Human-in-the-loop** — tools marked `requires_confirmation: true` pause and ask before executing
- **Multi-agent mode** — hierarchical manager + specialist team, toggled per session
- **Model switcher** — change the LLM mid-session from the settings panel
- **Expert profiles** — system-prompt personas stored in DB, selectable per conversation
- **Agent scheduling** — cron-based scheduled tasks with run history
- **Send behaviour** — toggle Enter-to-send vs Ctrl+Enter in settings
- **React UI** — WebSocket-based chat with sidebar history and settings drawer

---

## Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| [Ollama](https://ollama.com/download) | Latest | Optional if using Claude/Groq only |
| Python | 3.11+ | Managed automatically by `uv` |
| Node.js | 18+ | For building the React frontend |
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

The script:
1. Installs `uv` (Python env manager) if missing
2. Checks for Node.js and Ollama
3. Creates an isolated `.venv` and installs all dependencies
4. Builds the React frontend
5. Pulls the default model (`llama3.2`)
6. Starts the server at `http://localhost:8002`

---

## Project layout

```
├── main.py                 Server entry point (FastAPI + React static files)
├── api/
│   ├── server.py           REST API + WebSocket chat endpoint
│   └── chat.py             Agent runner logic (shared with scheduler)
├── agents/
│   └── runner.py           Ollama / LiteLLM agent + hierarchical crew
├── mcp_tools/
│   └── registry.py         MCP auto-discovery + tool wrappers
├── scheduler/
│   └── engine.py           APScheduler-based cron runner
├── db/
│   ├── database.py         SQLite init + connection helper
│   └── queries.py          CRUD operations
├── utils/
│   └── logger.py           Structured logger
├── frontend/               React/Vite UI
│   └── src/
│       ├── App.tsx
│       ├── hooks/useChat.ts  WebSocket state management
│       └── components/
├── config/
│   └── agents.yaml         Agent role / goal / backstory + default models
├── bin/
│   └── mcp_servers/        ← drop MCP server configs here
├── bootstrap.bat           Windows setup + launch
├── bootstrap.sh            macOS/Linux setup + launch
└── .env.example            API key template (copy to .env)
```

---

## Cloud LLMs

Add keys to your `.env` file (copy `.env.example` first):

```env
ANTHROPIC_API_KEY=sk-ant-...   # enables Claude models
GROQ_API_KEY=gsk_...           # enables Groq models
```

Claude and Groq models appear automatically in the model selector when their key is present.

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
# Web search (needs BRAVE_API_KEY in .env)
npx -y @modelcontextprotocol/server-brave-search

# SQLite database
npx -y @modelcontextprotocol/server-sqlite path/to/db.sqlite

# GitHub (needs GITHUB_TOKEN in .env)
npx -y @modelcontextprotocol/server-github
```

More at [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers).

---

## Useful commands

```bash
# Start manually (after bootstrap)
uv run python main.py

# Dev mode (hot-reload React)
cd frontend && npm run dev   # → http://localhost:5173 (proxied to :8002)

# Pull additional models
uv run python scripts/pull_models.py --model phi3
uv run python scripts/pull_models.py --list
```

---

## Architecture

```
User browser
    │
    ▼
React UI (frontend/dist)      ← served as static files by FastAPI
    │  WebSocket /ws/chat
    ▼
FastAPI (api/server.py)       ← port 8002
    │  asyncio.to_thread()
    ▼
Agent Runner (agents/runner.py) ← sync, worker thread
    │  ollama / litellm
    ▼
LLM (Ollama local / Claude / Groq)
    │
    ▼
MCP tools (bin/mcp_servers/)  ← spawned stdio processes
```

---

## License

MIT
