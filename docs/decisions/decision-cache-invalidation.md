# Decision: Runtime Cache TTL and modifiedTime-Based Invalidation (issue #99)

**Date:** 2026-07-07
**Snapshot commit:** branch `feat/issue-99` — see `src/mcp_gee_sweet/cache.py`

## Background

The cache's only staleness defenses were a fixed `CACHE_TTL` (set at process start, unchangeable without a restart) and `mark_dirty` calls from this server's own write tools. Neither catches an edit that happens outside this MCP session — another Claude session, or a person editing the spreadsheet/doc directly — until the TTL window closes. Issue #99 asked for two independent improvements: a way to change the TTL without restarting, and a way to detect out-of-band edits sooner.

## Decisions

### 1. `set_cache_ttl` tool, not a per-call TTL parameter

The issue suggested either a `set_cache_ttl` tool or a per-resource TTL parameter added to every read tool. Chose the tool: it's one new surface instead of a parameter threaded through a dozen existing signatures, and TTL is a deployment-wide tuning knob in practice (this codebase already treats `CACHE_TTL` as global, not per-call). The tool updates `_ttl` on all five in-memory cache instances immediately; it doesn't touch the `CACHE_TTL` env var, so it only affects the running process, not the startup default.

### 2. `modified_time` stored inside the cached JSON value, not a new DB column

Considered adding a `source_modified_time` column to the `cache` table. Rejected — it would need a migration path for every already-deployed SQLite file (`ALTER TABLE ... ADD COLUMN` guarded against pre-existing installs), for a value that's only ever read back by the same process that wrote it. Storing `modified_time` as a key inside the existing JSON `value` blob avoids the migration entirely and, for `DocContentCache`, turned out to already be present — `get_doc_content` was already fetching and storing `modifiedTime` as part of the cached doc dict, so that cache needed no `store()` signature change at all, only a comparison added to `_get_valid`.

### 3. Applied to sheet structure/data and doc content only — not Drive folder listings or calendar metadata

The issue's own framing ("a spreadsheet or doc is being edited by others") pointed at file-keyed caches. Checked whether the other two namespaces could reuse the same mechanism and concluded no for structural reasons, not just scope-trimming:

- **`DriveFolderCache`**: a folder's own `modifiedTime` does not change when a child file is added, removed, or renamed — Drive doesn't propagate child mutations to the parent's metadata. The signal this feature depends on doesn't exist for folder listings.
- **`CalendarCache`**: calendars aren't Drive files and the Calendar API doesn't expose a directly comparable field via the endpoints already in use (`calendarList().list()` / `calendars().get()`). Out of scope without a separate investigation into what Calendar API field, if any, would serve the same purpose.

Both classes still got `set_ttl` (decision 1 applies uniformly); only the modifiedTime check is scoped down.

### 4. Validation is opt-out (`CACHE_VALIDATE_MODIFIED_TIME`, default `true`), not opt-in

The issue's own "Notes" section flagged the cost explicitly: one extra Drive `files.get(fields=modifiedTime)` call per cache lookup, and asked whether that overhead is worth it relative to the cost of a stale read. Without a production benchmark available, defaulted to correctness (matching the problem the issue opened with — staleness that fails silently) and exposed the env var as the escape hatch for deployments where the extra round-trip matters more than immediate freshness.

### 5. `drive_service` threaded through selectively, not to every cache read path

`fetch_sheets()` (used by `list_sheets`, `find_in_spreadsheet`) and `get_multiple_spreadsheet_summary`'s inline cache logic gained the check, since these are the read-oriented tools the issue is about. Deliberately *not* threaded into `_get_sheet_id()` (`tools/sheets/helpers.py`), the internal sheet-name→ID resolver used by ~11 write-path tools in `structure.py` (`add_rows`, `format_cells`, etc.) — those already re-resolve and `mark_dirty` on a lookup miss, and adding a Drive round-trip to every mutating tool call for a staleness class this issue wasn't about (write-path correctness, not read-path freshness) wasn't justified without a separate look at that call path's own trade-offs.

## When to Re-evaluate

- If Calendar API staleness turns out to matter in practice, investigate what field (if any) the Calendar API exposes that's comparable to Drive's `modifiedTime` before assuming this pattern extends there directly.
- If write-path tools (`_get_sheet_id` callers) show evidence of stale-`sheet_id` bugs from concurrent structural edits, revisit decision 5 — it was scoped out for cost reasons, not because the risk is zero.
- No live benchmark of the extra `files.get` call's latency impact has been run (decision 4) — if `CACHE_VALIDATE_MODIFIED_TIME` overhead is reported as a real problem, that's the first thing to measure.
