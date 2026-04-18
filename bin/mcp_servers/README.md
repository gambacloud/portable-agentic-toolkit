# MCP Servers

Each subdirectory here is one MCP server.  
The toolkit scans for `*/config.json` at startup and loads tools automatically.

## Directory layout

```
bin/mcp_servers/
├── filesystem/
│   └── config.json
├── brave_search/
│   └── config.json
└── my_custom_tool/
    ├── config.json
    └── server.py        ← optional: server binary lives here too
```

## config.json schema

```json
{
  "name": "filesystem",
  "description": "Read and write local files",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
  "env": {},
  "enabled": true,
  "requires_confirmation": false
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | string | *(dir name)* | Display name |
| `description` | string | `""` | Shown in UI |
| `command` | string | **required** | Executable to spawn |
| `args` | list | `[]` | Command arguments |
| `env` | object | `{}` | Extra env vars (merged with current env) |
| `enabled` | bool | `true` | Set `false` to skip without deleting |
| `requires_confirmation` | bool | `false` | Show HITL dialog before each call |

## Popular MCP servers

```bash
# Official servers (Node.js required)
npx -y @modelcontextprotocol/server-filesystem <dir>
npx -y @modelcontextprotocol/server-brave-search     # needs BRAVE_API_KEY env
npx -y @modelcontextprotocol/server-sqlite <db.sqlite>
npx -y @modelcontextprotocol/server-github           # needs GITHUB_TOKEN env

# More: https://github.com/modelcontextprotocol/servers
```
