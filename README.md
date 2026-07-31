# Portable Agentic Toolkit

A fully **local**, privacy-first AI agent workspace powered by a custom FastAPI + React stack.  
All computation — including model inference — runs on your machine. No cloud, no telemetry.

---

## Quick start

1. Run the app (`uv run python main.py` or use `bootstrap.bat`)
2. Follow the **Quick Start Wizard** to set up your environment, select a model, and create your agent identity.
3. Manage tasks, chats, and connectors from the new sidebar (DO / SEE / CONFIGURE).

## Adding MCP Tools

Open **`/wizard-ui`** (or the **API Keys & Connectors** link in the sidebar settings) and paste the credentials for Slack, Microsoft Teams, Jira, GitHub, or Gmail directly into the connector card — no config files to edit. Already-installed connectors can have their credentials added or rotated the same way from `/mcp-ui`.

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

## Using Cloud Models (Claude, Gemini, Groq, OpenAI, Ollama Cloud)

Open **`/wizard-ui`**, go to the **AI Model** step, and paste an API key into the provider card you want (get a free Groq key at https://console.groq.com/keys, for example). It's saved and picked up immediately — no restart, no manual `.env` editing.

## Key files

| Path | Purpose |
|------|---------|
| `config/agents.yaml` | Agent role / goal / backstory |
| `bin/mcp_servers/` | MCP server configs |
| `scripts/git_export.py` | Clean & package for Git |
| `bootstrap.bat` / `.sh` | One-click setup |