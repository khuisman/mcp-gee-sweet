# MCP Client Setup

## Claude Desktop

Install the MCP Bundle, or add a block under `mcpServers` in `claude_desktop_config.json` yourself: stdio (cloned repo) or SSE (Docker).

### Install as a bundle

A [GitHub Release](https://github.com/khuisman/mcp-gee-sweet/releases) carries an MCP Bundle, `mcp-gee-sweet-<version>.mcpb`, under its assets. Open it in Claude Desktop on macOS to install the server, without editing any config file. The bundle declares macOS and Linux; Windows isn't tested yet, so it's left out.

The install dialog asks for:

- **OAuth client file** (required): the OAuth Client ID JSON for a Desktop app, downloaded from Google Cloud Console. See [Authentication](auth.md#method-b-oauth-20-personal-use--local-dev) for how to create one.
- **Enabled tools** (optional): a comma-separated list of tool names. Leave it empty to enable every tool (see [Tool filtering](#tool-filtering-in-client-config)).

The bundle ships the source and `uv.lock`, not the dependencies: the first start runs `uv run --frozen`, which installs Python and the locked dependencies, so it takes longer than later ones. It uses OAuth only (`AUTH_METHOD=oauth`) and keeps the token at `~/.mcp-gee-sweet-token.json`, outside the extension directory, so the token survives an update. For a service account or Application Default Credentials, use the manual config below instead.

There's no token on the first start. The server starts without Google access, and its first tool call returns a Google consent link. Approve it in a browser, then retry the call. To authorize from a terminal instead, run `CREDENTIALS_PATH=/path/to/credentials.json TOKEN_PATH=~/.mcp-gee-sweet-token.json ENABLED_TOOLS=<your Enabled tools value> uvx mcp-gee-sweet auth`, then retry. Give `ENABLED_TOOLS` the same value as the install dialog's **Enabled tools**, or leave it out if that was empty: the consent asks for mailbox access only when a Gmail tool is enabled, so leaving it out after excluding Gmail grants a scope the server doesn't use.

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
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json"
      }
    }
  }
}
```

Replace `/path/to/mcp-gee-sweet` with your clone path. This uses OAuth (the default waterfall's first method, full personal Drive access) — swap the `env` block for a different auth method — see [Authentication](auth.md).

Before the first connection, log in once from a terminal with the same paths: `CREDENTIALS_PATH=... TOKEN_PATH=... uv run --directory /path/to/mcp-gee-sweet mcp-gee-sweet auth`. A stdio server with no token doesn't open a browser itself. It starts without Google access, and its first tool call offers you the Google consent link, or you can run this command and retry (see [Re-authorizing from the client](auth.md#method-b-oauth-20-personal-use--local-dev)).

### SSE — Docker

The container serves over the network interface, so it needs a bearer token (see [HTTP transport authentication](configuration.md#http-transport-authentication)). Put `MCP_SERVER_TOKEN=<token>` in a `.env` file next to `docker-compose.yml`, start the server (`make start`), then point Claude Desktop at the SSE endpoint with the same token:

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "transport": "sse",
      "url": "http://localhost:47000/sse",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

For Claude Code: `claude mcp add --transport sse mcp-gee-sweet http://localhost:47000/sse --header "Authorization: Bearer <token>"`.

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
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json"
      }
    }
  }
}
```

See [Configuration](configuration.md#tool-filtering) for suggested subsets.

## Clients with a tool limit

Several MCP clients cap how many tools they accept, and with every tool registered the server is over each of these caps:

| Client | Limit | What happens over it |
|---|---|---|
| VS Code + GitHub Copilot (agent mode) | 128 tools per request, VS Code's built-in tools included ([docs](https://code.visualstudio.com/docs/agents/run/tools)) | The request fails with "Cannot have more than 128 tools per request" |
| Windsurf | 100 tools in total, across every server ([docs](https://docs.devin.ai/desktop/cascade/mcp)) | Not documented |
| Cursor | Depends on the model (older builds capped it at 40) | "Too many MCP tools are enabled for this mode", or only part of the tool list is used |
| Google Antigravity | 100 tools per server (user report) | The server is rejected |

The fix is the same everywhere: set `ENABLED_TOOLS` to one of the [suggested subsets](configuration.md#suggested-subsets), each of which is under 100 tools, or to your own list. You can join two subsets with a comma, like the Docs + Drive example there, as long as the total stays under your client's limit. On Windsurf, leave room for your other servers' tools too.

The snippets below use the **Read-only Sheets** subset with the PyPI install (`uvx`); swap in the list you want. For a cloned repo, use the `uv run --directory` command from [Claude Desktop](#stdio-cloned-repo) instead. `--include-tools <list>` at the end of `args` works too, in place of the `ENABLED_TOOLS` entry.

### VS Code + GitHub Copilot

In `.vscode/mcp.json` (workspace) or your user-profile `mcp.json`. VS Code's format uses a top-level `servers` key ([reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)):

```json
{
  "servers": {
    "mcp-gee-sweet": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-gee-sweet"],
      "env": {
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json",
        "ENABLED_TOOLS": "get_sheet_data,get_sheet_formulas,get_multiple_sheet_data,get_multiple_spreadsheet_summary,find_in_spreadsheet,list_sheets,list_spreadsheets"
      }
    }
  }
}
```

The 128 includes VS Code's own tools and every other server's, so a subset near 100 can still go over it with other servers enabled. You can also deselect tools or whole servers in the chat view's tools picker. That choice is saved in your VS Code profile, while `ENABLED_TOOLS` travels with the server config.

### Cursor

In `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "command": "uvx",
      "args": ["mcp-gee-sweet"],
      "env": {
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json",
        "ENABLED_TOOLS": "get_sheet_data,get_sheet_formulas,get_multiple_sheet_data,get_multiple_spreadsheet_summary,find_in_spreadsheet,list_sheets,list_spreadsheets"
      }
    }
  }
}
```

Cursor doesn't publish its per-model caps. If you still see "Too many MCP tools", use a smaller subset or switch to a model that allows more tools.

### Windsurf

In Windsurf's `mcp_config.json` (its location per platform is in Windsurf's [MCP docs](https://docs.devin.ai/desktop/cascade/mcp)):

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "command": "uvx",
      "args": ["mcp-gee-sweet"],
      "env": {
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json",
        "ENABLED_TOOLS": "get_sheet_data,get_sheet_formulas,get_multiple_sheet_data,get_multiple_spreadsheet_summary,find_in_spreadsheet,list_sheets,list_spreadsheets"
      }
    }
  }
}
```

Windsurf's 100 counts the tools from every server you have enabled. Windsurf also has a per-server `disabledTools` array, but it lists the tools to hide, so with this server you'd be naming most of them. `ENABLED_TOOLS` names the ones to keep.

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
