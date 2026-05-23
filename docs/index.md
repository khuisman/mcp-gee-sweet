# mcp-gee-sweet

An MCP server that gives AI clients reliable, direct access to Google Workspace — Sheets, Drive, Docs, and Calendar.

## What it does

- **Read and write Google Sheets** — cell values, formulas, sheet structure, batch updates
- **Manage Google Drive** — list, search, upload, download, move, copy, and sync files and folders
- **Work with Google Docs** — create documents, read content, write formatted content from HTML
- **Access Google Calendar** — list calendars and events, create and update events, find free slots

## Why it exists

Google does not provide an official MCP server for Sheets or Drive (as of mid-2026). This project fills that gap, forked from [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) and expanded substantially. See [Project Fork](decision-fork.md) for the full history and alternatives evaluated.

## Key design decisions

**Tool count is a cost.** Every registered tool is a name the AI must reason about on every call. This server applies a strict inclusion test — see [Tool Philosophy](tool-philosophy.md) — and defers borderline cases to the `batch_update` passthrough rather than adding named tools speculatively.

**Composite tools only when it matters.** Multi-step workflows are left to the AI client unless they involve binary data, pagination loops, or encoding decisions that Claude handles inconsistently in practice. See [Composite Tools](decision-composite-tools.md) for the full policy and the specific failure modes that justified server-side wrappers.

**Caching by default.** Sheet structure, sheet data, Drive folder listings, doc content, and calendar metadata are all cached in a local SQLite database with TTL + dirty invalidation. This keeps repeated reads fast without hitting the Google API quota on every call.

**Tool access presets.** The `ENABLED_TOOLS` environment variable restricts which tools are registered. Named presets (`readonly`, `standard`, `full`) let deployments scope their access level without enumerating individual tools. See the [Roadmap](roadmap.md) for the planned implementation.

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

See the [README](https://github.com/khuisman/mcp-gee-sweet#readme) for full auth setup and configuration options.
