<div align="center">
  <img src="https://raw.githubusercontent.com/khuisman/mcp-gee-sweet/main/docs/assets/logo.png" alt="mcp-gee-sweet logo" width="160">

  <b>mcp-gee-sweet</b>
  <p align="center"><i>A Google Workspace MCP server built for depth.</i></p>

![GitHub License](https://img.shields.io/github/license/khuisman/mcp-gee-sweet)
</div>

<!-- mcp-name: io.github.khuisman/mcp-gee-sweet -->

mcp-gee-sweet gives AI clients deep, direct access to Google Sheets, Docs, Drive, Calendar, and Gmail. It reads raw formulas like `=VLOOKUP()`, builds Docs structurally (colspan/rowspan tables, themes, named styles, an HTML/Markdown→AST→Docs pipeline), and covers Drive files, sharing, and sync alongside Calendar events and Gmail messages, threads, and drafts.

A few highlights:
- **Caching** — repeated reads return in ~2ms from a local cache instead of a round-trip API call every time.
- **Formula access** — reads raw `=VLOOKUP()`, `=SUM()`, and `=IF()` expressions, not just the values they produce.
- **Local sync** — two-way sync between a local folder and Google Drive.

**Install (stable):**
```bash
uvx mcp-gee-sweet
```

**Install (bleeding edge — every code change on `develop`):**
```bash
uvx --prerelease=allow mcp-gee-sweet
```

**[Full documentation →](https://khuisman.github.io/mcp-gee-sweet/)**

---

## What's covered

| Service | Tools | Highlights |
|---|---|---|
| **Google Sheets** | 36 | Formula access, batch read/write, 8 chart types, structural ops |
| **Google Drive** | 38 | File ops, sharing/permissions, local sync, revision history |
| **Google Docs** | 34 | Full HTML→Doc pipeline, tables, range styling, themes, Markdown export |
| **Google Calendar** | 17 | Event CRUD, free-slot finder across multiple calendars |
| **Gmail** | 11 | Search and read messages and threads, send and reply, drafts, labels (OAuth only) |

---

## Quick start

### Option A: `uv` — local use and development

If you cloned the repo or just want to use the server from your machine, `uv` is all you need. No Docker required.

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet
uv sync
```

Then point your MCP client at it using **stdio transport** (see [MCP client config](#mcp-client-config) below). The client spawns the server as a subprocess on demand — each session gets its own isolated process, so restarting the server for a code change or config update doesn't affect other open sessions.

### Option B: Docker — persistent shared server (SSE)

Use Docker when you want a single long-running server that multiple clients connect to over SSE — for example, Claude Desktop talking to the same instance as Claude Code.

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet
echo "MCP_SERVER_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
make build   # build the container image
make start   # start the server (SSE on port 47000)
make logs    # tail logs
```

Point your MCP client at `http://localhost:47000/sse`, sending the token from `.env` as an `Authorization: Bearer <token>` header (see the SSE config below). The server rejects any request without it. Without Docker, `--transport sse` and `--transport streamable-http` listen on `127.0.0.1` only, and need `MCP_SERVER_TOKEN` to serve on any other address; see [HTTP transport authentication](https://khuisman.github.io/mcp-gee-sweet/latest/configuration/#http-transport-authentication).

> **Note:** when using SSE, all clients share one server process. After a code change or restart (`make restart`), you must also restart each MCP client to reconnect.

---

## Configuration

The server tries auth methods in a waterfall by default, OAuth first — it authenticates as you and has full personal Drive access, which is what local/dev use (Option A above) needs. For OAuth, download an OAuth Client ID JSON from GCP Console and point the server at it:

```bash
export CREDENTIALS_PATH="/path/to/credentials.json"
export TOKEN_PATH="/path/to/token.json"
mcp-gee-sweet auth   # one-time browser login; `uvx mcp-gee-sweet auth` for a PyPI install
```

Pass the same `CREDENTIALS_PATH` and `TOKEN_PATH` in your MCP client's `env`. A stdio server with no token doesn't open a browser itself. Instead its first tool call offers you the Google consent link (or you run `mcp-gee-sweet auth`), and you retry the call. A token revoked mid-session is handled the same way, with no restart.

Service accounts (recommended for headless server deployments, see Option B above), base64 credential injection, and Application Default Credentials are also supported. Gmail tools need OAuth. See [Authentication](https://khuisman.github.io/mcp-gee-sweet/latest/auth/) for all options.

---

## MCP client config

**Claude Desktop — stdio (cloned repo):**
```json
{
  "mcpServers": {
    "mcp-gee-sweet": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-gee-sweet", "mcp-gee-sweet"],
      "env": {
        "CREDENTIALS_PATH": "/path/to/credentials.json",
        "TOKEN_PATH": "/path/to/token.json"
      }
    }
  }
}
```

**Claude Desktop — SSE (Docker):**
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

See [Client Setup](https://khuisman.github.io/mcp-gee-sweet/latest/client-setup/) for more options including tool filtering.

---

## Docs

- [Tools](https://khuisman.github.io/mcp-gee-sweet/latest/tools/) — full tool reference, grouped by domain
- [Authentication](https://khuisman.github.io/mcp-gee-sweet/latest/auth/) — all four auth methods
- [Configuration](https://khuisman.github.io/mcp-gee-sweet/latest/configuration/) — env vars, caching, tool filtering
- [Client Setup](https://khuisman.github.io/mcp-gee-sweet/latest/client-setup/) — MCP client config examples
- [Design Principles](https://khuisman.github.io/mcp-gee-sweet/latest/design/) — tool inclusion policy, composite tool decisions
- [Roadmap](https://khuisman.github.io/mcp-gee-sweet/latest/roadmap/) — planned features and known gaps

---

## Contributing

See [CONTRIBUTING.md](https://github.com/khuisman/mcp-gee-sweet/blob/main/CONTRIBUTING.md) for setup, QA workflows, and PR guidelines. A signed-off [`docs/qa/runs/vX.Y.Z.md`](https://github.com/khuisman/mcp-gee-sweet/tree/main/docs/qa/runs) record is required before any stable PyPI release — see [`docs/qa/README.md`](https://github.com/khuisman/mcp-gee-sweet/blob/main/docs/qa/README.md) for the QA workflow.

## License

MIT — see [LICENSE](https://github.com/khuisman/mcp-gee-sweet/blob/main/LICENSE).

## Credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — upstream this project was forked from
- [FastMCP](https://github.com/cognitiveapis/fastmcp)
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) and [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — roadmap inspiration
