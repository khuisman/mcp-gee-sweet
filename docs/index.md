# mcp-gee-sweet

An MCP server that gives AI clients reliable, direct access to Google Workspace — Sheets, Drive, Docs, Calendar, and Gmail.

## What it does

- **Read and write Google Sheets** — cell values, formulas, sheet structure, batch updates
- **Manage Google Drive** — list, search, upload, download, move, copy, and sync files and folders
- **Work with Google Docs** — create documents, read content, write formatted content from HTML
- **Access Google Calendar** — list calendars and events, create and update events, find free slots
- **Use Gmail** — search and read messages and threads, send and reply, manage drafts and labels (OAuth only)

## Why it exists

This project started as a fork of [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) and has since diverged substantially — full Sheets read/write/formulas/structure/formatting/charts plus a raw `batch_update` passthrough for anything a named tool doesn't cover, an AST-based Docs pipeline (HTML and Markdown input, theming, structural table editing), Drive file/sharing/sync operations, Calendar, and Gmail. See [Project Fork](decisions/decision-fork.md) for the original fork history.

This project deliberately keeps its named-tool surface small. Related operations consolidate into fewer, more parameterized tools, with `batch_update` as the escape hatch for whatever doesn't fit a named tool — see [Design Principles](design.md) for the reasoning ("tool count is a cost").

Known gaps (comments, conditional formatting, protected ranges, multi-tab Docs, and more) are tracked as candidates in the [roadmap](roadmap.md), not silently ignored.

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

- [Tools](tools.md) — the full tool reference, grouped by domain
- [Authentication](auth.md) — four auth methods and when to use each
- [Configuration](configuration.md) — env vars, tool filtering, caching
- [Client Setup](client-setup.md) — Claude Desktop and Claude Code config examples
- [Known Limitations](known-limitations.md) — API constraints and workarounds
- [Style Guide](style-guide.md) — module size, test structure, linting conventions
