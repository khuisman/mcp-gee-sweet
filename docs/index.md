# mcp-gee-sweet

An MCP server that gives AI clients reliable, direct access to Google Workspace — Sheets, Drive, Docs, and Calendar.

## What it does

- **Read and write Google Sheets** — cell values, formulas, sheet structure, batch updates
- **Manage Google Drive** — list, search, upload, download, move, copy, and sync files and folders
- **Work with Google Docs** — create documents, read content, write formatted content from HTML
- **Access Google Calendar** — list calendars and events, create and update events, find free slots

## Why it exists

Google does not provide an official MCP server for Sheets or Drive (as of mid-2026). This project fills that gap, forked from [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) and expanded substantially. See [Project Fork](decisions/decision-fork.md) for the full history and alternatives evaluated.

## Key design decisions

**Tool count is a cost.** Every registered tool is a name the AI must reason about on every call. This server applies a strict inclusion test — see [Design Principles](design.md) — and defers borderline cases to the `batch_update` passthrough rather than adding named tools speculatively.

**Composite tools only when it matters.** Multi-step workflows are left to the AI client unless they involve binary data, pagination loops, or encoding decisions that Claude handles inconsistently in practice. See [Design Principles](design.md#when-to-build-a-composite) for the policy.

**Caching by default.** Sheet structure, sheet data, Drive folder listings, doc content, and calendar metadata are all cached in a local SQLite database with TTL + dirty invalidation. See [Configuration](configuration.md#caching) for details.

## Quickstart

```bash
# Run locally
uv run mcp-gee-sweet

# Docker
docker run --rm -p 8000:8000 \
  -e CREDENTIALS_CONFIG=<base64-service-account> \
  -e DRIVE_FOLDER_ID=<folder-id> \
  mcp-gee-sweet
```

## Reference

- [Tools](tools.md) — all 84 tools, grouped by domain
- [Authentication](auth.md) — four auth methods and when to use each
- [Configuration](configuration.md) — env vars, tool filtering, caching
- [Client Setup](client-setup.md) — Claude Desktop and Claude Code config examples
- [Known Limitations](known-limitations.md) — API constraints and workarounds
