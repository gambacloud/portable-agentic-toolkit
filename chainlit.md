# Portable Agentic Toolkit

A fully **local**, privacy-first AI agent workspace.  
All computation — including model inference — runs on your machine. No cloud, no telemetry.

---

## Quick start

1. **Select a model** from the settings panel (⚙️ top right)
2. Type your request and press **Enter**
3. Watch the agent reason and call tools in real-time

## Adding MCP Tools

Drop a server config into `bin/mcp_servers/<name>/config.json`:

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
