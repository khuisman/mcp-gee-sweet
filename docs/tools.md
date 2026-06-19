# Tool Reference

60 tools across six domains. All tool names are lowercase with underscores — use these exact strings with `ENABLED_TOOLS` or `--include-tools`.

## Sheets — data

| Tool | Description | Key parameters |
|---|---|---|
| `get_sheet_data` | Read cell values from a range | `spreadsheet_id`, `sheet`, `range?`, `include_grid_data?` |
| `get_sheet_formulas` | Read formulas from a range | `spreadsheet_id`, `sheet`, `range?` |
| `get_multiple_sheet_data` | Batch read across multiple spreadsheets | `queries` (list of `{spreadsheet_id, sheet, range}`) |
| `get_multiple_spreadsheet_summary` | Title, tab names, headers, and preview rows for multiple spreadsheets | `spreadsheet_ids`, `rows_to_fetch?` |
| `find_in_spreadsheet` | Full-text search across all cells | `spreadsheet_id`, `query` |
| `update_cells` | Write a 2D array to a range | `spreadsheet_id`, `sheet`, `range`, `data` |
| `batch_update_cells` | Write multiple ranges in one API call | `spreadsheet_id`, `sheet`, `ranges` (dict of range → 2D array) |
| `batch_update` | Raw `spreadsheets.batchUpdate` passthrough | `spreadsheet_id`, `requests` |

`batch_update` is the escape hatch for anything not covered by a named tool (formatting, conditional formatting, dimension properties, etc.).

## Sheets — structure

| Tool | Description | Key parameters |
|---|---|---|
| `list_sheets` | List tab names in a spreadsheet | `spreadsheet_id` |
| `create_sheet` | Add a new tab | `spreadsheet_id`, `title` |
| `rename_sheet` | Rename a tab | `spreadsheet`, `sheet`, `new_name` |
| `copy_sheet` | Duplicate a tab to another spreadsheet | `src_spreadsheet`, `src_sheet`, `dst_spreadsheet`, `dst_sheet` |
| `add_rows` | Insert empty rows | `spreadsheet_id`, `sheet`, `count`, `start_row?` |
| `add_columns` | Insert empty columns | `spreadsheet_id`, `sheet`, `count`, `start_column?` |
| `add_chart` | Create a chart from a data range | `spreadsheet_id`, `sheet`, `chart_type`, `data_range`, `title?`, ... |

`add_chart` supports types: `COLUMN`, `BAR`, `LINE`, `AREA`, `PIE`, `SCATTER`, `COMBO`, `HISTOGRAM`.

## Spreadsheets (Drive-level)

| Tool | Description | Key parameters |
|---|---|---|
| `create_spreadsheet` | Create a new spreadsheet | `title`, `folder_id?` |
| `list_spreadsheets` | List spreadsheets in a folder | `folder_id?` |
| `search_spreadsheets` | Search Drive for spreadsheets by name | `query`, `folder_id?` |

`create_spreadsheet` cannot create files in a personal Drive when using service account auth — use OAuth or a Shared Drive.

## Drive — files

| Tool | Description | Key parameters |
|---|---|---|
| `list_files` | List files in a folder | `folder_id?` |
| `search_files` | Search Drive by name (any file type) | `query`, `folder_id?` |
| `list_folders` | List folders | `parent_id?` |
| `list_drives` | List shared drives | — |
| `get_file_metadata` | Get file properties (name, size, mimeType, etc.) | `file_id` |
| `create_folder` | Create a Drive folder | `name`, `parent_id?` |
| `copy_file` | Duplicate a file | `file_id`, `name?`, `folder_id?` |
| `move_file` | Move a file to another folder | `file_id`, `folder_id` |
| `rename_file` | Rename a file | `file_id`, `new_name` |
| `delete_file` | Trash or permanently delete a file | `file_id`, `permanent?` |

## Drive — transfer

| Tool | Description | Key parameters |
|---|---|---|
| `upload_file` | Upload a file to Drive from a URL | `url`, `name`, `folder_id?`, `mime_type?` |
| `upload_local_file` | Upload a file from the local filesystem | `path`, `name?`, `folder_id?`, `mime_type?` |
| `upload_local_folder` | Upload an entire local folder to Drive | `path`, `folder_id?` |
| `download_file` | Download a Drive file to the local filesystem | `file_id`, `path` |
| `download_folder` | Download an entire Drive folder | `folder_id`, `path` |
| `sync_folder` | Two-way sync between local and Drive folder | `folder_id`, `path`, `direction?` |
| `export_file` | Export a Workspace file (e.g. Sheets → XLSX) | `file_id`, `mime_type`, `path` |
| `list_revisions` | List revision history for a file | `file_id` |
| `export_revision` | Download a specific revision | `file_id`, `revision_id`, `path` |

## Drive — sharing

| Tool | Description | Key parameters |
|---|---|---|
| `share_spreadsheet` | Share a spreadsheet with users | `spreadsheet_id`, `recipients`, `send_notification?` |
| `share_file` | Share any Drive file with users | `file_id`, `recipients`, `send_notification?` |
| `list_permissions` | List who has access to a file | `file_id` |
| `update_permission` | Change a user's role | `file_id`, `permission_id`, `role` |
| `remove_permission` | Revoke a user's access | `file_id`, `permission_id` |

`recipients` is a list of `{email_address, role}` objects. Valid roles: `reader`, `commenter`, `writer`, `owner`.

## Docs

| Tool | Description | Key parameters |
|---|---|---|
| `create_doc` | Create a new Google Doc | `title`, `content?` (HTML), `folder_id?` |
| `get_doc_content` | Read doc content as an AST | `file_id` |
| `get_doc_structure` | Read doc structure — headings, sections, table layout | `doc_id` |
| `write_doc_content` | Replace doc content from HTML | `file_id`, `content` (HTML) |
| `insert_doc_text` | Insert text at an index | `doc_id`, `text`, `index`, `style?` |
| `insert_doc_table` | Insert a table | `doc_id`, `rows`, `columns`, `index?` |
| `delete_doc_range` | Delete a range of content | `doc_id`, `start_index`, `end_index` |
| `style_doc_range` | Apply text or paragraph formatting to a range | `doc_id`, `start_index`, `end_index`, `text_style?`, `paragraph_style?` |
| `style_doc_table_cells` | Apply formatting to table cells | `doc_id`, `table_start_index`, `requests` |

`write_doc_content` accepts HTML and converts it to Docs API requests via the HTML→AST→emitter pipeline. See [Docs AST Pipeline](design/docs-ast-pipeline.md) for the design.

`create_doc` cannot create files in a personal Drive when using service account auth — see [Authentication](auth.md#method-a-service-account-recommended-for-servers).

## Calendar

| Tool | Description | Key parameters |
|---|---|---|
| `list_calendars` | List all calendars | — |
| `get_calendar` | Get calendar metadata | `calendar_id` |
| `list_events` | List events with optional filters | `calendar_id`, `start?`, `end?`, `query?`, `max_results?` |
| `get_event` | Fetch a single event | `calendar_id`, `event_id` |
| `create_event` | Create a new event | `calendar_id`, `summary`, `start`, `end`, `description?`, `attendees?`, ... |
| `update_event` | Modify an existing event | `calendar_id`, `event_id`, + any fields to change |
| `delete_event` | Delete an event | `calendar_id`, `event_id` |
| `find_free_slots` | Find available time slots across calendars | `calendar_ids`, `start`, `end`, `duration_minutes`, `timezone?` |

**Note:** when using service account auth, calendars must be explicitly shared with the service account. The service account must also subscribe to shared calendars via `calendarList().insert()` before they appear in `list_calendars`.

## Cache

| Tool | Description | Key parameters |
|---|---|---|
| `refresh_cache` | Invalidate cached data for a resource or everything | `spreadsheet_id?`, `doc_id?`, `folder_id?`, `calendar_id?` |

Omit all parameters to flush the entire cache. See [Configuration](configuration.md#caching) for TTL and path settings.

## MCP resources

Two resources are available (read-only, not tools):

| Resource | Description |
|---|---|
| `server://auth-status` | Active auth method and Drive capability limits |
| `spreadsheet://{spreadsheet_id}/info` | Sheet list and grid properties for a spreadsheet |
