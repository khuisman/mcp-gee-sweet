# Manual QA + Code Review Checklist

Strategic post-merge verification of every registered tool. Work through each section after a clean server start. Check off items as verified. Each TC-XXX item links to the corresponding test case in `docs/qa/tests/`.

---

## Bugs / Issues (fix before live testing)

- [x] **`search_spreadsheets` query injection** (`drive.py`): User input interpolated raw into Drive API query string — a single quote breaks syntax. Fix: escape `'` → `\'` before embedding. → TC-D32
- [x] **`create_doc` strips formatting, `write_doc_content` preserves it** (`drive.py`): `create_doc` used `_html_to_text` (plain text); `write_doc_content` uses `_html_to_doc_requests` (headings, bullets, links). Fixed to use `_html_to_doc_requests` in both. → TC-D08
- [x] **`copy_sheet` rename silently skipped if API omits `title`** (`sheets.py`): Guarded with `if "title" in copy_result` — if API response omits the key, sheet is left with wrong name and no error. Fixed to use `.get()` and always attempt rename when names differ. → TC-S06, TC-S07
- [x] **`batch_update` does not invalidate structure cache** (`write.py`): Only called `sheet_data_cache.mark_dirty`; raw batchUpdate ops that add/rename/delete sheets left structure cache stale. Fixed to also call `cache.mark_dirty`. → TC-W24, TC-W28
- [ ] **`get_multiple_spreadsheet_summary` range format** (`read.py:207`): `f"{sheet_info.title}!A1:{max_row}"` produces e.g. `Sheet1!A1:5` — valid A1 notation (rows 1–5, all columns), but verify this is intentional for sheets with many columns. → TC-R22

---

## Read Tools (`read.py`)

### `get_sheet_data`
- [ ] TC-R01: Happy path — fetch all data
- [ ] TC-R02: Explicit range
- [ ] TC-R03: Grid data with formatting
- [ ] TC-R04: Non-existent sheet name
- [ ] TC-R05: Non-existent spreadsheet ID
- [ ] TC-R06: Range beyond data bounds
- [ ] TC-R07: Sheet name with spaces and special characters

### `get_sheet_formulas`
- [ ] TC-R08: Sheet with formulas — returns formula strings
- [ ] TC-R09: Sheet with no formulas
- [ ] TC-R10: Mixed cells — formulas and literals
- [ ] TC-R11: No range provided — fetches entire sheet

### `get_multiple_sheet_data`
- [ ] TC-R12: Multiple valid queries
- [ ] TC-R13: One query with missing required keys
- [ ] TC-R14: All queries fail
- [ ] TC-R15: Empty queries list

### `get_multiple_spreadsheet_summary`
- [ ] TC-R16: Happy path — multiple spreadsheet IDs
- [ ] TC-R17: Cache hit — second call skips API
- [ ] TC-R18: rows_to_fetch=1 — only header returned
- [ ] TC-R19: rows_to_fetch=0 — clamped to 1
- [ ] TC-R20: Spreadsheet with empty sheet
- [ ] TC-R21: Invalid spreadsheet ID in list
- [ ] TC-R22: Range format verification

### `find_in_spreadsheet`
- [ ] TC-R23: Match found in specific sheet
- [ ] TC-R24: Match across all sheets
- [ ] TC-R25: Case-insensitive match (default)
- [ ] TC-R26: Case-sensitive match
- [ ] TC-R27: max_results respected
- [ ] TC-R28: No matches
- [ ] TC-R29: Sheet name not found
- [ ] TC-R30: Multiple column matches in same row

---

## Write Tools (`write.py`)

### `update_cells`
- [ ] TC-W01: Write simple values
- [ ] TC-W02: Write a formula via USER_ENTERED ⚠️ destructive
- [ ] TC-W03: Range smaller than data provided
- [ ] TC-W04: Cache invalidated after write
- [ ] TC-W05: Non-existent sheet name

### `batch_update_cells`
- [ ] TC-W06: Multiple ranges in one call
- [ ] TC-W07: Ranges on the same sheet
- [ ] TC-W08: Empty ranges dict
- [ ] TC-W09: Cache invalidated after batch write

### `add_rows`
- [ ] TC-W10: Add row at beginning (no position specified)
- [ ] TC-W11: Add row at explicit position ⚠️ destructive
- [ ] TC-W12: start_row=0 — inheritFromBefore=False
- [ ] TC-W13: start_row=1 — inheritFromBefore=True
- [ ] TC-W14: Add multiple rows at once
- [ ] TC-W15: Invalid sheet name
- [ ] TC-W16: Large count value

### `add_columns`
- [ ] TC-W17: Add column at beginning (no position specified)
- [ ] TC-W18: start_column=0 — inheritFromBefore=False
- [ ] TC-W19: start_column=1 — inheritFromBefore=True
- [ ] TC-W20: Add multiple columns

### `batch_update` _(raw passthrough)_
- [ ] TC-W21: Add a sheet via raw request
- [ ] TC-W22: Rename a sheet via raw request
- [ ] TC-W23: Insert dimension via raw request
- [ ] TC-W24: Delete dimension — structure cache invalidated ⚠️ destructive
- [ ] TC-W25: Empty requests list
- [ ] TC-W26: Non-dict item in requests
- [ ] TC-W27: Invalid request structure
- [ ] TC-W28: Both caches marked dirty

---

## Sheet Management Tools (`sheets.py`)

### `list_sheets`
- [ ] TC-S01: Happy path
- [ ] TC-S02: Cache hit on second call
- [ ] TC-S03: Cache invalidated after rename

### `copy_sheet`
- [ ] TC-S04: Copy within same spreadsheet
- [ ] TC-S05: Copy to a different spreadsheet
- [ ] TC-S06: Name differs from Google's auto-assigned name — rename triggered
- [ ] TC-S07: Name matches Google's auto-assigned name — rename skipped
- [ ] TC-S08: Source sheet not found
- [ ] TC-S09: Destination spreadsheet not writable
- [ ] TC-S10: Cache invalidated after copy ⚠️ destructive

### `rename_sheet`
- [ ] TC-S11: Rename to a new name ⚠️ destructive
- [ ] TC-S12: Rename to the same name
- [ ] TC-S13: Sheet not found
- [ ] TC-S14: Cache invalidated after rename

### `create_sheet`
- [ ] TC-S15: Create a new tab
- [ ] TC-S16: Duplicate tab title
- [ ] TC-S17: Long title
- [ ] TC-S18: Response shape
- [ ] TC-S19: Cache updated after create

### `refresh_cache`
- [ ] TC-S20: Refresh by spreadsheet ID only
- [ ] TC-S21: Refresh by doc ID only
- [ ] TC-S22: Refresh both spreadsheet and doc
- [ ] TC-S23: Refresh with no arguments — clears all caches
- [ ] TC-S24: Cache re-populated after refresh

---

## Drive Tools (`drive.py`)

### `create_spreadsheet`
- [ ] TC-D01: Create in default folder
- [ ] TC-D02: Create with explicit folder ID
- [ ] TC-D03: Create without a folder (root of Drive)
- [ ] TC-D04: Service account Drive limitation
- [ ] TC-D05: Drive folder cache invalidated
- [ ] TC-D06: Resulting spreadsheet has expected title

### `create_doc`
- [ ] TC-D07: Create with no content
- [ ] TC-D08: Create with HTML content — formatting preserved
- [ ] TC-D09: Create with a link
- [ ] TC-D10: Content with no block-level elements — batchUpdate skipped
- [ ] TC-D11: Drive folder cache invalidated
- [ ] TC-D12: Long content

### `list_spreadsheets`
- [ ] TC-D13: List from configured folder
- [ ] TC-D14: List from explicit folder ID
- [ ] TC-D15: List from root (no folder)
- [ ] TC-D16: Empty folder
- [ ] TC-D17: Pagination not implemented

### `share_spreadsheet`
- [ ] TC-D18: Share as writer
- [ ] TC-D19: Share as reader
- [ ] TC-D20: Share as commenter
- [ ] TC-D21: Invalid role
- [ ] TC-D22: Missing email address key
- [ ] TC-D23: Mixed success and failure
- [ ] TC-D24: send_notification=False
- [ ] TC-D25: Non-existent spreadsheet ID

### `list_folders`
- [ ] TC-D26: List folders in a specific parent
- [ ] TC-D27: List from root
- [ ] TC-D28: Empty folder

### `search_spreadsheets`
- [ ] TC-D29: Basic name search
- [ ] TC-D30: Content search
- [ ] TC-D31: max_results respected
- [ ] TC-D32: Query with a single quote — injection fix
- [ ] TC-D33: No results
- [ ] TC-D34: Empty query string
- [ ] TC-D35: API error

### `list_files`
- [ ] TC-D36: List all files in a folder (no MIME type filter)
- [ ] TC-D37: Filter by MIME type
- [ ] TC-D38: Cache hit on second call
- [ ] TC-D39: mime_type=None cache key
- [ ] TC-D40: max_results clamped
- [ ] TC-D41: Pagination limit
- [ ] TC-D42: Trashed files excluded
- [ ] TC-D43: Cache invalidated after create

### `get_doc_content`
- [ ] TC-D44: Happy path
- [ ] TC-D45: Cache hit on second call
- [ ] TC-D46: Non-Google-Doc file ID
- [ ] TC-D47: Non-existent file ID
- [ ] TC-D48: Large document
- [ ] TC-D49: Content decode branch

### `write_doc_content`
- [ ] TC-D50: Write to an empty doc
- [ ] TC-D51: Write to a doc with existing content ⚠️ destructive
- [ ] TC-D52: HTML with headings and bullets
- [ ] TC-D53: HTML with a link
- [ ] TC-D54: HTML with no recognizable tags
- [ ] TC-D55: Empty string content
- [ ] TC-D56: Very long content
- [ ] TC-D57: Cache invalidated after write

### `create_folder`
- [ ] TC-D58: Create in default folder
- [ ] TC-D59: Create at root (no parent)
- [ ] TC-D60: Cache invalidated after create

### `move_file`
- [ ] TC-D61: Move a file to another folder ⚠️ destructive
- [ ] TC-D62: Move a folder
- [ ] TC-D63: Non-existent file ID

### `rename_file`
- [ ] TC-D64: Rename a file ⚠️ destructive
- [ ] TC-D65: Rename a folder
- [ ] TC-D66: Non-existent file ID

### `copy_file`
- [ ] TC-D67: Copy with auto-assigned name
- [ ] TC-D68: Copy with explicit name and destination folder
- [ ] TC-D69: Copy a Google Doc
- [ ] TC-D70: Attempt to copy a folder

### `delete_file`
- [ ] TC-D71: Trash a file (default — recoverable) ⚠️ destructive
- [ ] TC-D72: Permanently delete a file ⚠️ destructive
- [ ] TC-D73: Trash a folder ⚠️ destructive
- [ ] TC-D74: Non-existent file ID

### `search_files`
- [ ] TC-D75: Search by name across all MIME types
- [ ] TC-D76: Search with MIME type filter
- [ ] TC-D77: Search with folder filter
- [ ] TC-D78: Query with single quote

### `get_file_metadata`
- [ ] TC-D79: Metadata for a Google Spreadsheet
- [ ] TC-D80: Metadata for a Google Doc
- [ ] TC-D81: Metadata for a folder
- [ ] TC-D82: Non-existent file ID

### `export_file`
- [ ] TC-D83: Export Google Doc as plain text
- [ ] TC-D84: Export Google Doc as HTML
- [ ] TC-D85: Export Google Doc as PDF (binary)
- [ ] TC-D86: Export Google Sheet as CSV
- [ ] TC-D87: Unknown export format

### `upload_file`
- [ ] TC-D88: Upload plain text file
- [ ] TC-D89: Upload Markdown as raw file (no conversion)
- [ ] TC-D90: Upload Markdown and convert to Google Doc ⚠️ destructive
- [ ] TC-D91: Upload HTML and convert to Google Doc
- [ ] TC-D92: Upload Markdown with table

### `upload_local_file`
- [ ] TC-D93: Upload a binary file
- [ ] TC-D94: skip_if_exists prevents re-upload
- [ ] TC-D95: skip_if_exists=False creates duplicate
- [ ] TC-D96: Non-existent local path
- [ ] TC-D97: Name override

### `upload_local_folder`
- [ ] TC-D98: Bulk upload of a mixed directory ⚠️ destructive
- [ ] TC-D99: .DS_Store excluded by default
- [ ] TC-D100: skip_if_exists batches the existence check

### `download_file`
- [ ] TC-D101: Download a non-Google file
- [ ] TC-D102: Export Google Doc as plain text
- [ ] TC-D103: Export Google Doc as PDF
- [ ] TC-D104: Export Google Sheet as CSV
- [ ] TC-D105: Workspace file without export_format
- [ ] TC-D106: local_path as exact file path

### `download_folder`
- [ ] TC-D107: Download folder with mixed content
- [ ] TC-D108: Download folder with export_format
- [ ] TC-D109: skip_if_exists=True skips existing local files
- [ ] TC-D110: mime_type_filter

### `sync_folder`
- [ ] TC-D111: dry_run shows full action plan
- [ ] TC-D112: Bidirectional — Drive-only file downloaded ⚠️ destructive
- [ ] TC-D113: Bidirectional — local-only file uploaded ⚠️ destructive
- [ ] TC-D114: Local newer → uploaded; Drive newer → downloaded
- [ ] TC-D115: Upload preserves mtime for future sync accuracy
- [ ] TC-D116: direction='upload' — Drive-only file not downloaded
- [ ] TC-D117: direction='download' — local-only file not uploaded
- [ ] TC-D118: Workspace files excluded without export_format
- [ ] TC-D119: Invalid direction raises error

### `list_drives`
- [ ] TC-D120: List all shared drives
- [ ] TC-D121: Filter by name
- [ ] TC-D122: max_results clamping
- [ ] TC-D123: Pagination across multiple pages

### `list_permissions`
- [ ] TC-D124: List permissions on a file — owner entry present
- [ ] TC-D125: List permissions after sharing — new entry visible
- [ ] TC-D126: Non-existent file ID

### `update_permission`
- [ ] TC-D127: Downgrade writer → reader ⚠️ destructive
- [ ] TC-D128: Invalid role value
- [ ] TC-D129: Non-existent permission ID

### `remove_permission`
- [ ] TC-D130: Remove a permission ⚠️ destructive
- [ ] TC-D131: Non-existent permission ID

### `share_file`
- [ ] TC-D132: Share with type=user as reader
- [ ] TC-D133: Missing email_address for type=user
- [ ] TC-D134: Invalid role
- [ ] TC-D135: Share with type=domain
- [ ] TC-D136: Share with type=anyone (public link)
- [ ] TC-D137: Share a folder
- [ ] TC-D138: Mixed success and failure in one call
- [ ] TC-D139: send_notification=False for user share

---

## Calendar Tools (`calendar.py`)

### `list_calendars`
- [ ] TC-CAL01: Returns subscribed calendars
- [ ] TC-CAL02: primary flag
- [ ] TC-CAL03: Cache hit on second call
- [ ] TC-CAL04: Empty subscription list

### `get_calendar`
- [ ] TC-CAL05: Valid calendar ID
- [ ] TC-CAL06: calendar_id='primary'
- [ ] TC-CAL07: Cache hit on second call
- [ ] TC-CAL08: Non-existent calendar ID

### `list_events`
- [ ] TC-CAL09: No time filters — upcoming events
- [ ] TC-CAL10: time_min + time_max window
- [ ] TC-CAL11: query string search
- [ ] TC-CAL12: All-day event format
- [ ] TC-CAL13: Timed event format
- [ ] TC-CAL14: max_results clamped
- [ ] TC-CAL15: Non-existent calendar ID

### `get_event`
- [ ] TC-CAL16: Valid event — full details
- [ ] TC-CAL17: Attendees populated
- [ ] TC-CAL18: Recurring event instance
- [ ] TC-CAL19: Non-existent event ID

### `create_event`
- [ ] TC-CAL20: Timed event ⚠️ destructive
- [ ] TC-CAL21: All-day event ⚠️ destructive
- [ ] TC-CAL22: With description, location, and attendees ⚠️ destructive
- [ ] TC-CAL23: Invalid calendar ID

### `update_event`
- [ ] TC-CAL24: Update summary only ⚠️ destructive
- [ ] TC-CAL25: Update start and end ⚠️ destructive
- [ ] TC-CAL26: Update description and location ⚠️ destructive
- [ ] TC-CAL27: Non-existent event ID

### `delete_event`
- [ ] TC-CAL28: Delete an existing event ⚠️ destructive
- [ ] TC-CAL29: Non-existent event ID

### `find_free_slots`
- [ ] TC-CAL30: Single calendar — no events in window
- [ ] TC-CAL31: Single calendar — events in window
- [ ] TC-CAL32: Multiple calendar IDs
- [ ] TC-CAL33: Invalid calendar ID in list
- [ ] TC-CAL34: free_slots covers full window when no busy times
- [ ] TC-CAL35: Contiguous busy periods merged in free_slots

---

## Chart Tools (`charts.py`)

### `add_chart`
- [ ] TC-C01: COLUMN chart
- [ ] TC-C02: BAR chart
- [ ] TC-C03: LINE chart
- [ ] TC-C04: AREA chart
- [ ] TC-C05: PIE chart
- [ ] TC-C06: SCATTER chart
- [ ] TC-C07: COMBO chart
- [ ] TC-C08: HISTOGRAM chart
- [ ] TC-C09: Invalid chart type
- [ ] TC-C10: Lowercase chart type input
- [ ] TC-C11: Sheet not found
- [ ] TC-C12: Custom position and size

---

## MCP Resource (`server.py`)

### `spreadsheet://{spreadsheet_id}/info`
- [ ] Happy path — returns JSON with title and sheet list
- [ ] Each sheet entry has `title`, `sheetId`, `gridProperties`
- [ ] Non-existent spreadsheet ID — API error (resource doesn't catch exceptions)
- [ ] Uses `mcp.get_lifespan_context()` not `ctx` — verify this works correctly in resource context
- [ ] No cache — always hits the API (intentional)

---

## Infrastructure

### Cache behavior
- [ ] TC-I01: Structure cache TTL — stale entry causes re-fetch
- [ ] TC-I02: SQLite WAL mode — concurrent reads during a write
- [ ] TC-I03: CACHE_DB_PATH env var respected
- [ ] TC-I04: Cache persists across server restarts

### Tool filtering (`ENABLED_TOOLS`)
- [ ] TC-I05: CLI flag — only specified tools registered
- [ ] TC-I06: ENABLED_TOOLS env var — same behavior as CLI flag
- [ ] TC-I07: Unlisted tool called by name

### Auth fallback chain
- [ ] TC-I08: CREDENTIALS_CONFIG (base64 service account)
- [ ] TC-I09: SERVICE_ACCOUNT_PATH
- [ ] TC-I10: OAuth flow (CREDENTIALS_PATH / TOKEN_PATH)
- [ ] TC-I11: Application Default Credentials (ADC)
- [ ] TC-I12: No credentials — server fails to start with clear error

### Transport
- [ ] TC-I13: stdio transport
- [ ] TC-I14: SSE transport
- [ ] TC-I15: Hot reload with SSE
