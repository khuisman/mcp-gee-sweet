# Manual QA + Code Review Checklist

Strategic post-merge verification of every registered tool. Work through each section after a clean server start. Check off items as verified.

---

## Bugs / Issues (fix before live testing)

- [x] **`search_spreadsheets` query injection** (`drive.py`): User input interpolated raw into Drive API query string — a single quote breaks syntax. Fix: escape `'` → `\'` before embedding.
- [x] **`create_doc` strips formatting, `write_doc_content` preserves it** (`drive.py`): `create_doc` used `_html_to_text` (plain text); `write_doc_content` uses `_html_to_doc_requests` (headings, bullets, links). Fixed to use `_html_to_doc_requests` in both.
- [x] **`copy_sheet` rename silently skipped if API omits `title`** (`sheets.py`): Guarded with `if "title" in copy_result` — if API response omits the key, sheet is left with wrong name and no error. Fixed to use `.get()` and always attempt rename when names differ.
- [x] **`batch_update` does not invalidate structure cache** (`write.py`): Only called `sheet_data_cache.mark_dirty`; raw batchUpdate ops that add/rename/delete sheets left structure cache stale. Fixed to also call `cache.mark_dirty`.
- [ ] **`get_multiple_spreadsheet_summary` range format** (`read.py:207`): `f"{sheet_info.title}!A1:{max_row}"` produces e.g. `Sheet1!A1:5` — valid A1 notation (rows 1–5, all columns), but verify this is intentional for sheets with many columns.

---

## Read Tools (`read.py`)

### `get_sheet_data`
- [ ] Happy path: fetch all data from a sheet (no range)
- [ ] With explicit range: `A1:C5`
- [ ] With `include_grid_data=True`: verify response includes `rowData` / formatting fields
- [ ] Non-existent sheet name — does the Sheets API return a clear error?
- [ ] Non-existent spreadsheet ID — error propagates up?
- [ ] Range beyond data bounds (e.g., `A100:Z200` on a small sheet) — returns empty values, not error?
- [ ] Sheet name with spaces or special characters

### `get_sheet_formulas`
- [ ] Happy path: sheet with formulas — returns formula strings, not computed values
- [ ] Sheet with no formulas — returns empty or literal values?
- [ ] Mixed cells (some formulas, some literals) — literals returned as-is?
- [ ] No range provided — fetches entire sheet

### `get_multiple_sheet_data`
- [ ] Multiple valid queries across different spreadsheets
- [ ] One query missing required keys — that entry returns error, others succeed
- [ ] All queries fail — full list of errors returned
- [ ] Empty `queries` list — returns `[]`

### `get_multiple_spreadsheet_summary`
- [ ] Happy path with multiple spreadsheet IDs
- [ ] Cache hit path: call twice, confirm second call skips API
- [ ] `rows_to_fetch=1` — only header returned, `first_rows` is empty
- [ ] `rows_to_fetch=0` — `max(1, 0)` clamps to 1; verify behavior
- [ ] Spreadsheet with empty sheet — headers and first_rows both empty
- [ ] Invalid spreadsheet ID in list — that entry has error, others succeed
- [ ] Verify `range_to_get = f"{sheet_info.title}!A1:{max_row}"` works correctly for sheets with header-only data

### `find_in_spreadsheet`
- [ ] Match found in a specific sheet
- [ ] Match found across all sheets (no `sheet` param)
- [ ] Case-insensitive match (default)
- [ ] Case-sensitive match
- [ ] `max_results` respected — stops at limit
- [ ] No matches — returns `[]`
- [ ] Sheet name not found — returns `[{"error": ...}]`
- [ ] Query matching multiple columns in same row — each cell is a separate result

---

## Write Tools (`write.py`)

### `update_cells`
- [ ] Write simple values to a range
- [ ] Write formulas (`=SUM(A1:A5)`) via `USER_ENTERED` — formula is evaluated
- [ ] Range smaller than data (data truncated to range)
- [ ] After write: `sheet_data_cache.mark_dirty` called — verify next `get_multiple_spreadsheet_summary` re-fetches
- [ ] Non-existent sheet — Sheets API error propagates

### `batch_update_cells`
- [ ] Multiple ranges updated in one call
- [ ] Ranges on the same sheet
- [ ] Empty `ranges` dict — what does the API return? (probably succeeds with no changes)
- [ ] Cache invalidation: `sheet_data_cache.mark_dirty` called

### `add_rows`
- [ ] Add rows at beginning (`start_row=None` → index 0, `inheritFromBefore=False`)
- [ ] Add rows at explicit position (e.g., `start_row=5`)
- [ ] `start_row=0` explicitly — `inheritFromBefore` is `False` (0 > 0), correct?
- [ ] `start_row=1` — `inheritFromBefore=True`, new row inherits formatting from row above
- [ ] Add multiple rows at once (`count=5`)
- [ ] Invalid sheet name — returns `{"error": ...}` without calling API
- [ ] Large `count` value — API limit behavior

### `add_columns`
- [ ] Same cases as `add_rows` but for COLUMNS dimension
- [ ] `start_column=None` → adds at column A
- [ ] `start_column=0` explicitly — `inheritFromBefore=False`
- [ ] `start_column=1` — `inheritFromBefore=True`

### `batch_update` _(raw passthrough)_
- [ ] Valid request: add a sheet (`addSheet`)
- [ ] Valid request: rename a sheet (`updateSheetProperties`)
- [ ] Valid request: insert dimension
- [ ] Valid request: delete dimension — verify structure cache is now invalidated (was a bug, now fixed)
- [ ] Empty `requests` list — returns `{"error": "requests list cannot be empty"}`
- [ ] Non-dict item in `requests` — returns error
- [ ] Invalid request structure — API error propagates
- [ ] Verify both `sheet_data_cache.mark_dirty` and `cache.mark_dirty` are called

---

## Sheet Management Tools (`sheets.py`)

### `list_sheets`
- [ ] Happy path — returns tab names
- [ ] Cache hit: call twice, second is served from cache
- [ ] After `rename_sheet`: `cache.mark_dirty` is called; next `list_sheets` re-fetches

### `copy_sheet`
- [ ] Copy within same spreadsheet (src == dst spreadsheet)
- [ ] Copy to different spreadsheet
- [ ] `dst_sheet` name that differs from Google's auto-assigned "Copy of X" — rename triggered
- [ ] `dst_sheet` name that matches Google's auto-assigned name — rename skipped, correct behavior
- [ ] Source sheet not found — returns `{"error": ...}`
- [ ] Destination spreadsheet not writable — API error
- [ ] Verify `cache.mark_dirty(dst_spreadsheet)` called after copy

### `rename_sheet`
- [ ] Rename to a new name
- [ ] Rename to same name — API may succeed or no-op
- [ ] Sheet not found — returns `{"error": ...}`
- [ ] After rename: `cache.mark_dirty` called; subsequent `list_sheets` reflects new name

### `create_sheet`
- [ ] Create a new tab with a unique title
- [ ] Create a tab with a duplicate title — API behavior (error or auto-suffix?)
- [ ] Long title (>100 chars) — API limit behavior
- [ ] Verify response includes `sheetId`, `title`, `index`, `spreadsheetId`
- [ ] Verify `cache.mark_dirty` called

### `refresh_cache`
- [ ] With `spreadsheet_id` only — marks structure + data cache dirty
- [ ] With `doc_id` only — marks doc cache dirty
- [ ] With both — marks both
- [ ] With neither — marks all four caches dirty
- [ ] After `mark_all_dirty`: next summary call triggers fresh API fetch

---

## Drive Tools (`drive.py`)

### `create_spreadsheet`
- [ ] Create in configured default folder (`lc.folder_id`)
- [ ] Create with explicit `folder_id`
- [ ] Create without any folder (root of Drive) — `target_folder_id` is None
- [ ] Service account: can it create in shared Drive? (known limitation — may fail for personal Drive)
- [ ] Verify `drive_folder_cache.mark_dirty` called for the target folder
- [ ] Resulting spreadsheet has expected title

### `create_doc`
- [ ] Create with no content — doc created, empty body
- [ ] Create with `<p>`, `<h1>`, `<li>` content — headings and bullets preserved (now uses `_html_to_doc_requests`)
- [ ] Create with `<a href="...">` — link formatting preserved
- [ ] Content that results in empty requests — no `batchUpdate` call, no error
- [ ] Verify `drive_folder_cache.mark_dirty` called
- [ ] Long content — API limit behavior

### `list_spreadsheets`
- [ ] List from configured folder
- [ ] List from explicit `folder_id`
- [ ] List from root (no folder — omits folder filter in query)
- [ ] Empty folder — returns `[]`
- [ ] Folder with many spreadsheets — pagination not implemented, may silently truncate

### `share_spreadsheet`
- [ ] Share with valid email as `writer`
- [ ] Share with valid email as `reader`
- [ ] Share with valid email as `commenter`
- [ ] Invalid role — goes to `failures` list
- [ ] Missing `email_address` key — goes to `failures` list with `None` email
- [ ] Multiple recipients, some succeed, some fail — mixed result
- [ ] `send_notification=False` — no email sent
- [ ] Non-existent spreadsheet ID — API error goes to `failures`
- [ ] **Danger check**: no validation that caller owns the spreadsheet before sharing

### `list_folders`
- [ ] List folders in a specific parent folder
- [ ] List from root (no `parent_folder_id`) — adds `'root' in parents` filter
- [ ] Empty folder — returns `[]`
- [ ] Note: pagination not implemented

### `search_spreadsheets`
- [ ] Basic name search
- [ ] Content search (fullText)
- [ ] `max_results` clamped to 1–100
- [ ] Query containing a single quote — now safely escaped (was a bug, now fixed)
- [ ] No results — returns `[]`
- [ ] Empty query string — behavior?
- [ ] API error — returns `[{"error": ...}]`

### `list_files`
- [ ] List all files in a folder (no `mime_type`)
- [ ] Filter by MIME type
- [ ] Cache hit: second call with same `(folder_id, mime_type)` returns cached result
- [ ] `mime_type=None` cache key — verify `folder_cache.get(folder_id, None)` works correctly
- [ ] `max_results` clamped to 1–1000
- [ ] Pagination: >1000 files silently truncated
- [ ] Trashed files excluded (query includes `trashed=false`)
- [ ] After `create_spreadsheet`/`create_doc`: `drive_folder_cache.mark_dirty` ensures next `list_files` re-fetches

### `get_doc_content`
- [ ] Happy path — returns text, metadata, web link
- [ ] Cache hit: second call returns cached result
- [ ] Non-Google-Doc file ID — Drive `export` API error
- [ ] Non-existent file ID — API error
- [ ] Large document — response handling
- [ ] Binary content edge case: `content.decode("utf-8")` vs already-string branch

### `write_doc_content`
- [ ] Write to empty doc — `end_index=2`, no `deleteContentRange`, only insert
- [ ] Write to doc with existing content — existing content cleared, new content written
- [ ] HTML with `<h1>`, `<h2>`, `<li>`, `<p>` — headings and bullets preserved
- [ ] HTML with `<a href="...">` — link formatting preserved
- [ ] HTML with no recognizable tags — existing content cleared, nothing new written
- [ ] Empty string content — existing content cleared, nothing inserted
- [ ] Very long content — Docs API batchUpdate size limits (~2MB per request)
- [ ] Verify `doc_cache.mark_dirty` called

---

## Chart Tools (`charts.py`)

### `add_chart`
- [ ] Each of the 8 chart types: COLUMN, BAR, LINE, AREA, PIE, SCATTER, COMBO, HISTOGRAM
- [ ] Invalid chart type — returns `{"error": ...}` before API call
- [ ] Chart type lowercase input — `.upper()` normalizes correctly
- [ ] Sheet not found — returns `{"error": ...}`
- [ ] Invalid A1 notation in `data_range` — returns `{"error": ...}` from `_parse_a1_notation`
- [ ] PIE chart: verify separate code path (no axis/domain/series splitting)
- [ ] Non-PIE chart with `x_axis_label` and `y_axis_label` — included in `axis` list
- [ ] Non-PIE chart without axis labels — axis entries have no `title` key
- [ ] Custom `position_x`, `position_y`, `width`, `height` — values passed to `overlayPosition`
- [ ] Chart created on a sheet with data — appears in spreadsheet
- [ ] `chartId` extracted from response and returned
- [ ] API error during chart creation — returns `{"error": "Failed to add chart: ..."}` (catches all exceptions — intentional?)

---

## MCP Resource (`server.py`)

### `spreadsheet://{spreadsheet_id}/info`
- [ ] Happy path — returns JSON with title and sheet list
- [ ] Each sheet entry has `title`, `sheetId`, `gridProperties`
- [ ] Non-existent spreadsheet ID — API error (resource doesn't catch exceptions)
- [ ] Uses `mcp.get_lifespan_context()` not `ctx` — verify this works correctly in resource context
- [ ] No cache — always hits the API (intentional)

---

## Cross-Cutting / Infrastructure

### Cache behavior
- [ ] Structure cache TTL: verify stale entries cause a re-fetch after expiry (not just after `mark_dirty`)
- [ ] SQLite WAL mode: verify concurrent reads during a write don't block
- [ ] `CACHE_DB_PATH` env var respected — verify file is created at custom path
- [ ] Server restart: cache persists across restarts (SQLite file survives), stale data possible

### Tool filtering (`ENABLED_TOOLS`)
- [ ] With `--include-tools get_sheet_data,list_sheets`: only those two registered
- [ ] With `ENABLED_TOOLS` env var: same behavior
- [ ] Tool not in allowlist is called by name — MCP returns "tool not found"

### Auth fallback chain
- [ ] `CREDENTIALS_CONFIG` (base64 service account) — works
- [ ] `SERVICE_ACCOUNT_PATH` — works
- [ ] OAuth flow (`CREDENTIALS_PATH`/`TOKEN_PATH`) — works; `create_doc`/`create_spreadsheet` land in personal Drive
- [ ] Application Default Credentials — works (e.g., `gcloud auth application-default login`)
- [ ] No credentials at all — server fails to start with a clear error

### Transport
- [ ] stdio transport: `uv run mcp-gee-sweet` — connects from a MCP client
- [ ] SSE transport: `uv run mcp-gee-sweet --transport sse` — accessible at `http://localhost:8000`
- [ ] `--reload` flag with SSE — uvicorn hot-reload works
