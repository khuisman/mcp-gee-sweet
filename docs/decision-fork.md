# Decision: Fork and Continue as Independent Project

## Background

This project began as a fork of [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets), a community MCP server for interacting with Google Sheets. The original repo was chosen specifically because it included `get_sheet_formulas` — access to raw cell formulas via the Sheets API — which most alternatives lacked. As of May 2026, Google has not released an official MCP server for Sheets or Drive (official servers exist for Maps, BigQuery, GCE, and GKE), so community solutions are the only option.

Over time the codebase diverged substantially. It now includes a caching architecture, Google Drive file listing, Google Docs support, tool filtering, and observability improvements that put it well outside the original scope. This document records the research done to decide whether to continue building on this base or switch to a different foundation.

## Alternatives Evaluated (May 2026)

### [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — current upstream
- **Language:** Python
- **Tools:** ~19 tools covering core Sheets read/write, formulas, batch operations, Drive spreadsheet management
- **Strengths:** Deep Sheets API coverage, `get_sheet_formulas`, raw `batch_update` passthrough, active maintenance (last commit March 2026)
- **Weaknesses:** No cell formatting, no Drive file management beyond spreadsheets, no Docs support

### [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets)
- **Language:** TypeScript
- **Tools:** 40+ tools — the most comprehensive Sheets-specific server found
- **Strengths:** Cell formatting (colors, fonts, borders, number formats), conditional formatting, data validation, sheet dimension metadata, freeze rows/columns, compact formatting snapshots
- **Weaknesses:** No `get_sheet_formulas`, no Docs API support, TypeScript (harder to extend for this use case), no caching layer
- **Notable:** Primary inspiration for the feature roadmap

### [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp)
- **Language:** TypeScript
- **Tools:** Cross-service Workspace suite (Sheets, Docs, Slides, Calendar)
- **Strengths:** Named ranges, protected ranges, Drive file operations (move, copy, delete, rename), permission management, revision history
- **Weaknesses:** Shallower Sheets depth than xing5 or freema, no formula access, TypeScript
- **Notable:** Primary inspiration for Drive file operations and permissions roadmap items

### [isaacphi/mcp-gdrive](https://github.com/isaacphi/mcp-gdrive)
- **Language:** TypeScript
- **Tools:** 4 tools (search, read_file, gsheets_read, gsheets_update_cell)
- **Verdict:** Too minimal to consider as a base

## Decision: Continue and Fork

**Continue building on the xing5 base.** No alternative offers a clearly superior starting point:

- `freema/mcp-gsheets` has broader formatting coverage but lacks formula access (the original selection criterion) and is TypeScript
- `piotr-agier/google-drive-mcp` has better Drive operations but shallower Sheets depth
- Neither has a caching layer
- No official Google-provided alternative exists

The gap analysis (see [roadmap.md](roadmap.md)) shows that most missing features can be added incrementally using the existing architecture. The `batch_update` passthrough already provides an escape hatch for any Sheets API operation not yet wrapped as a named tool.

**Fork from upstream.** The codebase has grown well past the original scope. Continuing as a silent fork accumulates invisible divergence and makes it harder to credit the work appropriately. The plan:

1. Open a PR upstream from the `upstream-observability` branch — structured logging, per-tool timing, and `cache_discovery=False` fix — changes that fit cleanly within xing5's scope before cutting loose
2. Fork to a new repo under an appropriate name (e.g., `mcp-google-workspace`)
3. Update README to credit xing5 as the original base and freema/piotr-agier for roadmap inspiration

## What This Project Has That Alternatives Don't

- **Caching architecture** — sheet structure, sheet data, Drive folder listings, and doc content all cached with TTL + dirty invalidation, file-backed across restarts
- **Google Docs support** — `get_doc_content`, `create_doc`, `write_doc_content` with HTML→Docs API formatting
- **`get_sheet_formulas`** — raw formula access (inherited from xing5, absent in freema and piotr-agier)
- **Tool filtering** — `ENABLED_TOOLS` env var / `--include-tools` CLI flag to restrict which tools are registered
- **`batch_update` passthrough** — direct access to the raw Sheets batchUpdate API as an escape hatch
