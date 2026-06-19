# MCP Client Setup

## Claude Desktop

Add a block under `mcpServers` in `claude_desktop_config.json`. Choose stdio (cloned repo) or SSE (Docker).

### stdio — cloned repo

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-gee-sweet",
        "mcp-gee-sweet"
      ],
      "env": {
        "SERVICE_ACCOUNT_PATH": "/path/to/service_account.json",
        "DRIVE_FOLDER_ID": "your_drive_folder_id"
      }
    }
  }
}
```

Replace `/path/to/mcp-gee-sweet` with your clone path. Swap the `env` block for your auth method — see [Authentication](auth.md).

### SSE — Docker

Start the server first (`make start`), then point Claude Desktop at the SSE endpoint:

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "transport": "sse",
      "url": "http://localhost:47000/sse"
    }
  }
}
```

## Claude Code (this project's own MCP config)

The project runs two instances — one OAuth, one service account — defined in `.mcp.json` at the repo root. Claude Code picks these up automatically when you open the project.

## Tool filtering in client config

To restrict tools at the client level, pass `--include-tools` as a CLI arg:

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/mcp-gee-sweet",
        "mcp-gee-sweet",
        "--include-tools", "get_sheet_data,update_cells,list_sheets,list_spreadsheets"
      ],
      "env": {
        "SERVICE_ACCOUNT_PATH": "/path/to/service_account.json"
      }
    }
  }
}
```

See [Configuration](configuration.md#tool-filtering) for suggested subsets.

## Finding Google IDs

```
Google Drive Folder:
  https://drive.google.com/drive/folders/1xcRQCU9xrNVBPTeNzHqx4hrG7yR91WIa
                                         └────────── Folder ID ──────────┘

Google Sheets Spreadsheet:
  https://docs.google.com/spreadsheets/d/25_-_raTaKjaVxu9nJzA7-FCrNhnkd3cXC54BPAOXemI/edit
                                         └───────────── Spreadsheet ID ─────────────┘

Google Docs Document:
  https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
                                     └─────────────── Document ID ──────────────┘

Google Calendar:
  Settings → [Calendar name] → Calendar ID (e.g. abc@group.calendar.google.com)
```
