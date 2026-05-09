# Portable Agentic Toolkit

A fully **local**, privacy-first AI agent workspace powered by a custom FastAPI + React stack.  
All computation — including model inference — runs on your machine. No cloud, no telemetry.

---

## Quick start

1. Run the app (`uv run python main.py` or use `bootstrap.bat`)
2. Follow the **Quick Start Wizard** to set up your environment, select a model, and create your agent identity.
3. Manage tasks, chats, and connectors from the new sidebar (DO / SEE / CONFIGURE).

## Adding MCP Tools

You can easily install and manage MCP tools directly from the **Connectors** page in the UI.

Alternatively, for custom servers, drop a config into `bin/mcp_servers/<name>/config.json`:

```json
{
  "name": "filesystem",
  "description": "Read and write local files",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/you/Documents"],
  "enabled": true,
  "requires_confirmation": true
}
```

**Restart** the app — tools are auto-discovered on startup.

## System requirements

| Component | Minimum |
|-----------|---------|
| RAM | 16 GB |
| Storage | 10 GB (for models) |
| Ollama | Running locally |

## Using Groq Models (Cloud)

If you'd like to use ultra-fast cloud models via Groq instead of running them locally:
1. Open the `.env` file in the project root.
2. Add your Groq API key: `GROQ_API_KEY=gsk_...`
3. Restart the app. The Groq models will now appear in the model selection dropdown!

## Key files

| Path | Purpose |
|------|---------|
| `config/agents.yaml` | Agent role / goal / backstory |
| `bin/mcp_servers/` | MCP server configs |
| `scripts/git_export.py` | Clean & package for Git |
| `bootstrap.bat` / `.sh` | One-click setup |