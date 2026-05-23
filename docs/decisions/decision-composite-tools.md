# Decision: Composite Tool Policy

**Date:** 2026-05-22
**Snapshot commit:** [`d90ca0c`](https://github.com/khuisman/mcp-gee-sweet/commit/d90ca0c8517a44ad3222d4d35063a9877f7f3afc) — codebase as it existed when this decision was made

> This is a point-in-time record. It captures context, alternatives, and reasoning as they were understood on the date above — not the current state of the project.

## Background

As the tool count grew past 40, a question arose about whether to add server-side composite tools — single MCP tools that wrap common multi-step chains — or rely on the AI client (Claude) to orchestrate the primitives.

## Default Position

The MCP server exposes atomic tools. The AI client can chain them. In principle, composite tools are unnecessary because Claude can call `list_events` then `add_rows` in sequence without a dedicated `log_calendar_to_sheet` tool.

## When Server-Side Composites Are Worth It

After observing real usage, three failure modes justify a server-side wrapper:

1. **Binary data handling** — tools that return base64-encoded content (XLSX exports, PDF exports, image downloads) require a decode step that Claude handles inconsistently. In practice, downloading a sheet as XLSX took multiple attempts to correctly decode. A server-side tool that handles decode + local write once is more reliable than Claude doing it on every call.

2. **Pagination loops** — bulk operations over a folder or large file list require correctly following `nextPageToken`. Claude can do this but will occasionally stop at the first page or loop incorrectly under load.

3. **Data encoding decisions in transformation chains** — `sheet_to_doc` involves decisions about how to encode tables, merge cells, and handle formatting that benefit from a consistent, predictable server-side implementation.

## Decision

**Implement server-side composites only when the intermediate steps are fiddly enough that Claude will fail or require retries in normal use.** The test: would a developer write a helper script to avoid doing this by hand? If yes, it's worth wrapping.

### Approved for implementation

| Tool | Reason |
|------|--------|
| `sheet_to_doc` | Data transformation + encoding decisions |
| `bulk_export_folder` | Binary data (base64) in a loop + pagination |
| `drive_inventory_doc` | Pagination + large result sets |

### Won't do

| Tool | Reason |
|------|--------|
| `create_from_template` | Two sequential calls (`copy_file` → `write_doc_content`); Claude gets this right |
| `log_calendar_to_sheet` | Two sequential calls (`list_events` → `add_rows`); Claude gets this right |
| `book_next_free_slot` | Two sequential calls (`find_free_slots` → `create_event`); Claude gets this right |
| `find_and_update_row` | Two sequential calls (`find_in_spreadsheet` → `update_cells`); Claude gets this right |
| `markdown_to_doc` | Already works via `upload_file` with `source_format='markdown'`; a named alias adds surface area with no benefit |

## Corollary: Docstrings Over Wrappers

For the "won't do" workflows, the right investment is clear docstrings that describe when and how to combine the primitives — not a new tool. This keeps the tool count down and avoids confusing the AI with overlapping capabilities.
