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

### `write_doc_content` — HTML table tests
- [ ] TC-D140: Simple 2×2 table created from HTML
- [ ] TC-D141: Table after paragraph content
- [ ] TC-D142: Table with empty cells
- [ ] TC-D143: Table-only HTML (no paragraphs)
- [ ] TC-D144: Multiple tables in one write
- [ ] TC-D145: HTML with `<th>` header cells treated as data

### `list_revisions`
- [ ] TC-D146: List revisions for a spreadsheet
- [ ] TC-D147: List revisions for a non-existent file

### `export_revision`
- [ ] TC-D148: Export a revision and read a cell range
- [ ] TC-D149: Export revision with explicit sheet name
- [ ] TC-D150: Export revision — no range returns all data
- [ ] TC-D151: Export revision of a non-Sheets file

### `list_shared_with_me`
- [ ] TC-D152: List all files shared with me
- [ ] TC-D153: Filter shared files by MIME type
- [ ] TC-D154: Limit shared files with max_results
- [ ] TC-D155: Single-quote in MIME type is escaped

### `list_recent_files`
- [ ] TC-D156: List recently modified files
- [ ] TC-D157: Filter by days
- [ ] TC-D158: Filter by MIME type
- [ ] TC-D159: max_results capped at 100

### `get_storage_quota`
- [ ] TC-D160: Get storage quota
- [ ] TC-D161: Fields requested include storageQuota and user
- [ ] TC-D162: Byte values are integers not strings

### `list_file_activity`
- [ ] TC-D163: Basic activity fetch returns timeline entries
- [ ] TC-D164: Known-user actor structure
- [ ] TC-D165: Pagination — next_page_token present when results exceed page_size
- [ ] TC-D166: Invalid file ID returns error (unit test)

---

## Docs Tools (`tools/docs/`)

### `get_doc_structure`
- [ ] TC-DOC01: Structure of a non-empty doc
- [ ] TC-DOC02: Paragraph runs include style data
- [ ] TC-DOC03: Structure of a doc containing a table
- [ ] TC-DOC04: Structure of an empty doc
- [ ] TC-DOC05: Invalid doc ID returns error

### `insert_doc_text`
- [ ] TC-DOC06: Insert a single paragraph ⚠️ destructive
- [ ] TC-DOC07: Insert at multiple indices — high→low ordering verified ⚠️ destructive
- [ ] TC-DOC08: Empty insertions list returns error

### `delete_doc_range`
- [ ] TC-DOC09: Delete a paragraph ⚠️ destructive
- [ ] TC-DOC10: Cannot delete final segment newline
- [ ] TC-DOC11: Empty deletions list returns error

### `style_doc_range`
- [ ] TC-DOC12: Apply named style type ⚠️ destructive
- [ ] TC-DOC13: Apply text styles (bold, italic, foreground color) ⚠️ destructive
- [ ] TC-DOC14: Apply both paragraph and text style in one range ⚠️ destructive
- [ ] TC-DOC15: No recognised style fields returns error

### `insert_doc_table`
- [ ] TC-DOC16: Insert a 2×3 table ⚠️ destructive
- [ ] TC-DOC17: Cell indices usable for insert_doc_text ⚠️ destructive

### `style_doc_table_cells`
- [ ] TC-DOC18: Apply grey header row background ⚠️ destructive
- [ ] TC-DOC19: Apply borders and padding ⚠️ destructive
- [ ] TC-DOC20: Empty cells list returns error
- [ ] TC-DOC21: Cell with no style fields is skipped

### Integration / ordering
- [ ] TC-DOC22: Multi-delete high→low ordering verified ⚠️ destructive
- [ ] TC-DOC23: style_doc_range round-trip — heading confirmed in get_doc_structure ⚠️ destructive
- [ ] TC-DOC24: style_doc_range text styles round-trip ⚠️ destructive
- [ ] TC-DOC25: style_doc_table_cells post-fix live verification ⚠️ destructive
- [ ] TC-DOC26: Full end-to-end sequence — insert table then style cells ⚠️ destructive
- [ ] TC-DOC27: Insert text then insert table — index chaining ⚠️ destructive
- [ ] TC-DOC28: Apply strikethrough ⚠️ destructive
- [ ] TC-DOC29: Apply font_size ⚠️ destructive
- [ ] TC-DOC30: Apply link_url ⚠️ destructive

### `write_doc_content` — HTML emitter
- [ ] TC-DOC31: `<h2>` maps to HEADING_2 (not HEADING_3) ⚠️ destructive
- [ ] TC-DOC32: `<th>` cells produce bold runs ⚠️ destructive
- [ ] TC-DOC33: Inline formatting inside `<td>` cells ⚠️ destructive
- [ ] TC-DOC34: `colspan` produces merged cells ⚠️ destructive
- [ ] TC-DOC35: Column widths from HTML ⚠️ destructive
- [ ] TC-DOC36: `rowspan` produces vertically merged cells ⚠️ destructive
- [ ] TC-DOC37: Combined `rowspan` and `colspan` in the same table ⚠️ destructive
- [ ] TC-DOC38: `rowspan` with header row — phantom not filled, real cells in correct columns ⚠️ destructive
- [ ] TC-DOC39: Markdown headings via `write_doc_content` ⚠️ destructive
- [ ] TC-DOC40: Markdown bold and italic via `write_doc_content` ⚠️ destructive
- [ ] TC-DOC41: Markdown task list ⚠️ destructive
- [ ] TC-DOC42: Markdown fenced code block ⚠️ destructive
- [ ] TC-DOC43: Markdown table via `write_doc_content` ⚠️ destructive
- [ ] TC-DOC47: `write_doc_content` inline code monospace ⚠️ destructive
- [ ] TC-DOC78: `data-style="title"` produces TITLE named style ⚠️ destructive
- [ ] TC-DOC79: `data-style="subtitle"` produces SUBTITLE named style ⚠️ destructive

### `create_doc_from_file`
- [ ] TC-DOC44: `create_doc_from_file` with a local .md file ⚠️ requires-oauth ⚠️ destructive
- [ ] TC-DOC45: `create_doc_from_file` with a local .html file ⚠️ requires-oauth ⚠️ destructive
- [ ] TC-DOC46: `create_doc_from_file` file not found

### Nested tables
- [ ] TC-DOC48: Simple nested table ⚠️ destructive
- [ ] TC-DOC49: Nested table alongside regular cells ⚠️ destructive
- [ ] TC-DOC50: Nested table with multiple rows and columns ⚠️ destructive
- [ ] TC-DOC51: Nested tables not supported in markdown (documented limitation)

### `get_doc_theme` / `apply_theme`
- [ ] TC-DOC52: `get_doc_theme` scans body paragraph styles
- [ ] TC-DOC53: `apply_theme` updates named style definitions ⚠️ destructive
- [ ] TC-DOC54: `apply_theme` with `overwrite=True` also patches existing paragraphs ⚠️ destructive
- [ ] TC-DOC55: `apply_theme` with table styling ⚠️ destructive
- [ ] TC-DOC56: `get_doc_theme` → `apply_theme` round-trip on an AI-generated doc ⚠️ destructive

### `insert_inline_image`
- [ ] TC-DOC57: Insert an image by public URI ⚠️ destructive
- [ ] TC-DOC58: Insert an image with explicit size ⚠️ destructive
- [ ] TC-DOC59: No source provided returns error
- [ ] TC-DOC60: Both URI and drive_file_id provided returns error

### Table row/column operations
- [ ] TC-DOC61: Insert a row below an existing row ⚠️ destructive
- [ ] TC-DOC62: Insert a row above an existing row ⚠️ destructive
- [ ] TC-DOC63: Delete a row ⚠️ destructive
- [ ] TC-DOC64: Insert a column to the right ⚠️ destructive
- [ ] TC-DOC65: Insert a column to the left ⚠️ destructive
- [ ] TC-DOC66: Delete a column ⚠️ destructive
- [ ] TC-DOC67: API error returned gracefully (out of bounds row)

### `create_header` / `create_footer`
- [ ] TC-DOC68: Create a default page header ⚠️ destructive
- [ ] TC-DOC69: Create a header with content ⚠️ destructive
- [ ] TC-DOC70: Create a default page footer ⚠️ destructive
- [ ] TC-DOC71: Create a footer with content ⚠️ destructive
- [ ] TC-DOC72: Invalid header_type returns error
- [ ] TC-DOC73: Invalid footer_type returns error
- [ ] TC-DOC74: insert_doc_text with segment_id writes into header ⚠️ destructive

### `get_doc_named_styles`
- [ ] TC-DOC75: `get_doc_named_styles` reads named style defaults set via the Docs UI

### Integration / two-phase table fill
- [ ] TC-DOC76: Table immediately after heading renders at Normal Text size ⚠️ requires-oauth ⚠️ destructive
- [ ] TC-DOC77: No visible blank line between heading and table in `create_doc_from_file` ⚠️ requires-oauth ⚠️ destructive

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

### `create_event` / `update_event` — recurrence (RRULE)
- [ ] TC-CAL36: Create a weekly recurring event ⚠️ destructive
- [ ] TC-CAL37: Create a daily recurring event with COUNT limit ⚠️ destructive
- [ ] TC-CAL38: Recurrence absent when not provided

### `list_events` — expand_recurring
- [ ] TC-CAL39: expand_recurring=False returns master events
- [ ] TC-CAL40: expand_recurring=True (default) expands instances

### `update_event` — recurrence support
- [ ] TC-CAL41: Update RRULE on a master event ⚠️ destructive
- [ ] TC-CAL42: Remove recurrence by passing an empty list ⚠️ destructive
- [ ] TC-CAL43: Update a single instance without affecting the series ⚠️ destructive

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
