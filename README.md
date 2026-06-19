<div align="center">
  <b>mcp-gee-sweet</b>
  <p align="center"><i>Your AI Assistant's Gateway to Google Workspace!</i></p>

![GitHub License](https://img.shields.io/github/license/khuisman/mcp-gee-sweet)
</div>

> **Not published to PyPI** — source install only. Do not attempt `pip install mcp-gee-sweet` or `uvx mcp-gee-sweet`.

An MCP server that gives AI clients reliable, direct access to Google Workspace — Sheets, Drive, Docs, and Calendar. 60 tools across six domains. Forked from [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) and expanded substantially.

**[Full documentation →](https://khuisman.github.io/mcp-gee-sweet/)**

---

## Quick start

### Docker (recommended)

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet
make build   # build the container image
make start   # start the server (SSE on port 47000)
make logs    # tail logs
```

Point your MCP client at `http://localhost:47000/sse`.

### Local with `uv`

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet
uv sync
uv run mcp-gee-sweet                 # stdio transport
uv run mcp-gee-sweet --transport sse # SSE on port 8000
```

---

## Configuration

Set credentials via environment variable before starting the server. The recommended method for servers is a service account:

```bash
export SERVICE_ACCOUNT_PATH="/path/to/service_account.json"
export DRIVE_FOLDER_ID="your_drive_folder_id"
```

The server also supports OAuth, base64 credential injection, and Application Default Credentials. See [Authentication](https://khuisman.github.io/mcp-gee-sweet/auth/) for all options.

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
        "SERVICE_ACCOUNT_PATH": "/path/to/service_account.json",
        "DRIVE_FOLDER_ID": "your_drive_folder_id"
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
      "url": "http://localhost:47000/sse"
    }
  }
}
```

See [Client Setup](https://khuisman.github.io/mcp-gee-sweet/client-setup/) for more options including tool filtering.

---

## Docs

- [Tools](https://khuisman.github.io/mcp-gee-sweet/tools/) — full tool reference (60 tools)
- [Authentication](https://khuisman.github.io/mcp-gee-sweet/auth/) — all four auth methods
- [Configuration](https://khuisman.github.io/mcp-gee-sweet/configuration/) — env vars, caching, tool filtering
- [Client Setup](https://khuisman.github.io/mcp-gee-sweet/client-setup/) — MCP client config examples
- [Design Principles](https://khuisman.github.io/mcp-gee-sweet/design/) — tool inclusion policy, composite tool decisions
- [Roadmap](https://khuisman.github.io/mcp-gee-sweet/roadmap/) — planned features and known gaps

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, QA workflows, and PR guidelines. All items in [`docs/qa-checklist.md`](docs/qa-checklist.md) must be verified before any PyPI release.

## License

MIT — see [LICENSE](LICENSE).

## Credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — upstream this project was forked from
- [FastMCP](https://github.com/cognitiveapis/fastmcp)
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) and [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — roadmap inspiration
