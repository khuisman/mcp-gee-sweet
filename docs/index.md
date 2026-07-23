# mcp-gee-sweet

An MCP server that gives AI clients reliable, direct access to Google Workspace — Sheets, Drive, Docs, and Calendar.

## What it does

- **Read and write Google Sheets** — cell values, formulas, sheet structure, batch updates
- **Manage Google Drive** — list, search, upload, download, move, copy, and sync files and folders
- **Work with Google Docs** — create documents, read content, write formatted content from HTML
- **Access Google Calendar** — list calendars and events, create and update events, find free slots

## Why it exists

This project started as a fork of [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) and has since diverged substantially — full Sheets read/write/formulas/structure/formatting/charts plus a raw `batch_update` passthrough for anything a named tool doesn't cover, an AST-based Docs pipeline (HTML and Markdown input, theming, structural table editing), Drive file/sharing/sync operations, and Calendar. See [Project Fork](decisions/decision-fork.md) for the original fork history.

The MCP landscape for Google Workspace has grown since then — Google now runs an official Developer Preview program, and several community projects cover similar ground. Rather than claim to be the only option, here's how the coverage actually breaks down as of mid-2026 (full sourcing in [Repositioning](decisions/decision-repositioning.md)):

| | mcp-gee-sweet | Official Google Workspace MCP (Developer Preview) | Notable community alternatives |
|---|---|---|---|
| Sheets | 25 tools — read/write, formulas, structure, formatting, charts, raw `batch_update` passthrough | **No dedicated server** | [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp) (12), [a-bonus/google-docs-mcp](https://github.com/a-bonus/google-docs-mcp) (~44, incl. comments/conditional formatting/protected ranges we don't have yet) |
| Docs | 20 tools — HTML + Markdown input, AST-based theming (`apply_theme`, named styles), structural table editing | **No dedicated server** | taylorwilsdon (18, plus a Markdown *export* tool we don't have — see [#300](https://github.com/khuisman/mcp-gee-sweet/issues/300)), [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) (~17, incl. footnotes/multi-tab we don't have) |
| Drive | 32 tools | 8 tools | Several — piotr-agier and others cover a similar range |
| Calendar | 13 tools | 9 tools | Several |
| Release channel | Stable PyPI releases behind a QA regression gate | Developer Preview | Varies by project |

This project deliberately keeps its named-tool surface smaller than some alternatives — a-bonus/google-docs-mcp, for example, registers more raw tools by giving nearly every Sheets/Docs operation its own dedicated tool. Here, related operations consolidate into fewer, more parameterized tools, with `batch_update` as the escape hatch for whatever doesn't fit a named tool — see [Design Principles](design.md) for the reasoning ("tool count is a cost"). Neither approach is strictly better; it's a different tradeoff, and it's why raw tool counts alone don't tell the whole story in the table above.

Known gaps found while researching this comparison (comments, conditional formatting, protected ranges, multi-tab Docs, Markdown export, and more) are tracked as candidates in the [roadmap](roadmap.md), not silently ignored.

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

- [Tools](tools.md) — all 90 tools, grouped by domain
- [Authentication](auth.md) — four auth methods and when to use each
- [Configuration](configuration.md) — env vars, tool filtering, caching
- [Client Setup](client-setup.md) — Claude Desktop and Claude Code config examples
- [Known Limitations](known-limitations.md) — API constraints and workarounds
- [Style Guide](style-guide.md) — module size, test structure, linting conventions
