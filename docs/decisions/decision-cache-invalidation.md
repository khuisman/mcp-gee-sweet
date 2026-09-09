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

### 5. `drive_service` threaded through every `fetch_sheets()` call site, including `_get_sheet_id`

**Reversed from the original PR.** The first version deliberately left `_get_sheet_id()` (`tools/sheets/helpers.py`) — the internal sheet-name→ID resolver used by ~11 write-path tools in `structure.py` (`add_rows`, `format_cells`, etc.) — calling `fetch_sheets()` without `drive_service`, reasoning that write-path correctness was a separate concern from read-path freshness (decision 3's cost/scope framing).

Code review caught that this was a correctness bug, not a scoping choice: `SheetStructureCache` rows are keyed only by `spreadsheet_id` and shared across every call path. `_get_sheet_id`'s 3-arg `fetch_sheets()` call computed `current_mtime=None` (no `drive_service`), and on a cache miss `store()` only writes the `modified_time` key when it's not `None` — so the row got re-stored *without* a `modified_time` key at all. The next reader's `_check_modified_time` sees `cached_mtime is None` and skips the comparison entirely (there's nothing to compare against), silently disabling staleness detection for that spreadsheet for every subsequent caller — including the correctly-updated `list_sheets`/`find_in_spreadsheet`/`get_multiple_spreadsheet_summary` paths. Since almost every mutating sheet tool routes through `_get_sheet_id`, this defeated a large fraction of the feature in practice. Fixed by threading `drive_service` through `_get_sheet_id` and all 11 call sites; regression-tested in `tests/test_cache.py::TestGetSheetIdModifiedTimePropagation`.

### 6. `get_cache_ttl` tool added alongside `set_cache_ttl`

`set_cache_ttl` mutates 5 process-wide singleton cache instances shared by every concurrent SSE client session, with no prior way to inspect the current value before overwriting it — one session calling `set_cache_ttl(0)` silently changed behavior for everyone else with no way to know what to restore. Added a read-only `get_cache_ttl` tool (backed by a new `_BaseCache.get_ttl()`) and a docstring/log line on `set_cache_ttl` making the process-wide, multi-session blast radius explicit. The underlying single-process-wide-cache design itself is unchanged (decision 1 still applies) — this only closes the "can't see or restore the previous value" gap.

### 7. Shared `_BaseCache` for the TTL/modifiedTime-check plumbing

The modifiedTime-comparison-and-mark-dirty block was duplicated near-verbatim across three cache classes, and `set_ttl`/`close`/`mark_all_dirty` were duplicated across all five, with no single source of truth — exactly the shape of bug that produced decision 5's regression (one call site missed a signature update, and nothing forced the other four to be checked). Extracted a `_BaseCache` with `_check_modified_time`/`_check_ttl` helpers and the shared connection/TTL/dirty-marking methods; each cache class now only owns its own key shape and payload shape. `_get_valid` methods also now parse the cached JSON value once and return it directly instead of returning the raw `sqlite3.Row` for callers to re-parse.

## When to Re-evaluate

- If Calendar API staleness turns out to matter in practice, investigate what field (if any) the Calendar API exposes that's comparable to Drive's `modifiedTime` before assuming this pattern extends there directly.
- No live benchmark of the extra `files.get` call's latency impact has been run (decision 4) — if `CACHE_VALIDATE_MODIFIED_TIME` overhead is reported as a real problem, that's the first thing to measure. `get_multiple_spreadsheet_summary` now makes one such call per sheet (not per spreadsheet) to keep each sheet's cached `modified_time` tag accurate against its own, separately-timed fetch — if that tool's Drive-call volume becomes a problem for spreadsheets with many sheets, this is the place to revisit first.
- `get_cache_ttl`/`set_cache_ttl` still have no per-session scoping (decision 6) — if that becomes a real operational problem in multi-session SSE deployments, the fix is per-session cache instances, not another env var.
