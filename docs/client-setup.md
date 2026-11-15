# MCP Client Setup

## Claude Desktop

Install the MCP Bundle, or add a block under `mcpServers` in `claude_desktop_config.json` yourself: stdio (cloned repo) or SSE (Docker).

### Install as a bundle

**New in v0.9.6;** on 0.9.5, see [its docs](https://khuisman.github.io/mcp-gee-sweet/0.9.5/client-setup/). A [GitHub Release](https://github.com/khuisman/mcp-gee-sweet/releases) carries an MCP Bundle, `mcp-gee-sweet-<version>.mcpb`, under its assets. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) first: the bundle runs the server with it. Then download the `.mcpb` file and double-click it, or install it from Claude Desktop's **Settings → Extensions**, to install the server on macOS without editing any config file. The bundle declares macOS and Linux; Windows isn't tested yet, so it's left out.

The install dialog asks for:

- **OAuth client file** (required): the OAuth Client ID JSON for a Desktop app, downloaded from Google Cloud Console. See [Authentication](auth.md#method-b-oauth-20-personal-use-local-dev) for how to create one.
- **Enabled tools** (optional): a comma-separated list of tool names and [tool groups](configuration.md#tool-groups), or `all` for every tool (see [Choosing tools for your client](#choosing-tools-for-your-client)). Empty loads the `default` group. To create Docs from local Markdown files, upload, download or sync local folders, enter `default,local-files`.

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

Replace `/path/to/mcp-gee-sweet` with your clone path. This uses OAuth (the default waterfall's first method, full personal Drive access) — swap the `env` block for a different auth method — see [Authentication](auth.md). With no `ENABLED_TOOLS`, it loads the `default` tool group; add `"ENABLED_TOOLS": "default,local-files"` to `env` for the local Markdown file tools and local upload, download and sync (see [Choosing tools for your client](#choosing-tools-for-your-client)).

Before the first connection, log in once from a terminal with the same paths: `CREDENTIALS_PATH=... TOKEN_PATH=... uv run --directory /path/to/mcp-gee-sweet mcp-gee-sweet auth`. A stdio server with no token doesn't open a browser itself. It starts without Google access, and its first tool call offers you the Google consent link, or you can run this command and retry (see [Re-authorizing from the client](auth.md#method-b-oauth-20-personal-use-local-dev)).

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

## Claude Code — stdio

```bash
claude mcp add mcp-gee-sweet \
  -e ENABLED_TOOLS=all \
  -e CREDENTIALS_PATH=/path/to/credentials.json \
  -e TOKEN_PATH=/path/to/token.json \
  -- uv run --directory /path/to/mcp-gee-sweet mcp-gee-sweet
```

`ENABLED_TOOLS=all` loads every tool. Claude Code's tool search loads a tool's full definition only when the model picks it, so the full set costs little context; without `ENABLED_TOOLS`, the server loads only the `default` group. For a PyPI install, replace everything after `--` with `uvx mcp-gee-sweet`.

Before the first connection, log in once from a terminal with the same paths and the same `ENABLED_TOOLS`, which decides the scopes: `CREDENTIALS_PATH=... TOKEN_PATH=... ENABLED_TOOLS=all uv run --directory /path/to/mcp-gee-sweet mcp-gee-sweet auth`, or `... uvx mcp-gee-sweet auth` for a PyPI install.

## Claude Code (this project's own MCP config)

The project runs two instances — one OAuth, one service account — defined in `.mcp.json` at the repo root. Claude Code picks these up automatically when you open the project.

## Choosing tools for your client

With `ENABLED_TOOLS` unset, the server loads the `default` [tool group](configuration.md#tool-groups): everyday reading and writing across Sheets, Docs, Drive, Calendar and Gmail, and under every client's tool cap. Set `ENABLED_TOOLS` (or `--include-tools`) to change it:

| Client | Setting |
|---|---|
| Claude Code | `all` (tool search loads each tool's definition only when it's used) |
| Codex | `default`; `all` if your Codex build has tool search |
| Claude Desktop | `default`, plus `local-files` for local work: `default,local-files` |
| Cursor, VS Code + Copilot, Windsurf, Antigravity | `default` (see [Clients with a tool limit](#clients-with-a-tool-limit)) |
| claude.ai, ChatGPT, API connectors | `default` |

`default` leaves out the tools that only work on files on the server's machine, so the Markdown file tools (`create_doc_from_file`, `update_doc_from_file`) and local upload, download and sync (`upload_local_folder`, `sync_folder`, ...) need `local-files` in the list. Under SSE or streamable HTTP they also need [`LOCAL_FILE_ACCESS`](configuration.md#local-file-access) set, since it defaults to `off` there. To add more, join a service group or tool names on: `default,comments`, `default,docs`, `default,insert_doc_table`. The full list of groups and what `default` holds is in [Tool filtering](configuration.md#tool-filtering).

To set it as a CLI argument instead of an environment variable, pass `--include-tools`:

```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/mcp-gee-sweet",
        "mcp-gee-sweet",
        "--include-tools", "default,local-files"
      ],
      "env": {
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json"
      }
    }
  }
}
```

## Clients with a tool limit

Several MCP clients cap how many tools they accept. The `default` group, and every group but `all`, is under each of these caps; with every tool registered (`all`), the server is over all of them:

| Client | Limit | What happens over it |
|---|---|---|
| VS Code + GitHub Copilot (agent mode) | 128 tools per request, VS Code's built-in tools included ([docs](https://code.visualstudio.com/docs/agents/run/tools)) | Depends on the build: see the note below the table |
| Windsurf | 100 tools in total, across every server ([docs](https://docs.devin.ai/desktop/cascade/mcp)) | Not documented |
| Cursor | Depends on the model (older builds capped it at 40) | "Too many MCP tools are enabled for this mode", or only part of the tool list is used |
| Google Antigravity | 100 tools per server (user report) | The server is rejected |

On these clients, leave `ENABLED_TOOLS` unset or set it to `default`, or to any combination of [tool groups](configuration.md#tool-groups) and names whose total stays under your client's cap. The group counts are in [Tool filtering](configuration.md#tool-groups). On Windsurf, leave room for your other servers' tools too.

**VS Code may handle every tool.** In our November 2026 test, with every tool registered, VS Code + Copilot looked tools up on demand: Copilot's first step in the chat was **Search Tools**, and it sent only the tools it picked, so the request carried far fewer than 128 and worked. A build that sends every tool with each request instead fails with "Cannot have more than 128 tools per request". `all` is worth trying there; if you see that error, go back to `default`.

The snippets below set `default` explicitly, with the PyPI install (`uvx`); swap in the list you want. For a cloned repo, use the `uv run --directory` command from [Claude Desktop](#stdio-cloned-repo) instead. `--include-tools <list>` at the end of `args` works too, in place of the `ENABLED_TOOLS` entry.

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
        "ENABLED_TOOLS": "default"
      }
    }
  }
}
```

The 128 includes VS Code's own tools and every other server's, so a combination near 100 can still go over it with other servers enabled. You can also deselect tools or whole servers in the chat view's tools picker. That choice is saved in your VS Code profile, while `ENABLED_TOOLS` travels with the server config.

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
        "ENABLED_TOOLS": "default"
      }
    }
  }
}
```

Cursor doesn't publish its per-model caps. If you still see "Too many MCP tools", name fewer tools (a single service group, or your own list) or switch to a model that allows more tools.

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
        "ENABLED_TOOLS": "default"
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
