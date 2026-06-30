# Feature Roadmap

This doc is a high-level orientation — feature ideas, architectural direction, and historical context. **Active work is tracked in [GitHub Issues](https://github.com/khuisman/mcp-gee-sweet/issues).** When a roadmap item is scheduled, an issue is opened; the checkbox here stays as a reference.

Features are ordered by practical priority within each tier, cross-domain. Items marked with a source were identified by auditing competing projects — see [decision-fork.md](decisions/decision-fork.md) for full credits.

## What's implemented

### Google Sheets — 19 tools
- **Read:** `get_sheet_data`, `get_sheet_formulas`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `find_in_spreadsheet`
- **Write:** `update_cells`, `batch_update_cells`, `batch_update` _(raw batchUpdate passthrough — escape hatch for anything not covered by named tools)_
- **Structure:** `list_sheets`, `create_sheet`, `rename_sheet`, `copy_sheet`, `delete_sheet`, `add_rows`, `add_columns`, `delete_rows`, `delete_columns`, `add_chart`
- **Data ops:** `clear_values`

### Google Drive — 28 tools
- **Files:** `list_files`, `list_spreadsheets`, `search_files`, `search_spreadsheets`, `list_folders`, `list_drives`, `get_file_metadata`, `create_spreadsheet`, `create_folder`, `copy_file`, `move_file`, `rename_file`, `delete_file`
- **Sharing:** `share_spreadsheet`, `share_file`, `list_permissions`, `update_permission`, `remove_permission`
- **Transfer:** `upload_file`, `upload_local_file`, `upload_local_folder`, `download_file`, `download_folder`, `sync_folder`, `export_file`, `export_revision`, `list_revisions`

### Google Docs — 20 tools
- **Content:** `create_doc`, `create_doc_from_file`, `get_doc_content`, `write_doc_content`, `insert_doc_text`, `delete_doc_range`, `get_doc_structure`, `insert_doc_table`, `insert_inline_image`, `create_header`, `create_footer`
- **Styling:** `style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `get_doc_named_styles`, `apply_theme`
- **Table structure:** `insert_table_row`, `delete_table_row`, `insert_table_column`, `delete_table_column`

### Google Calendar — 8 tools
`list_calendars`, `get_calendar`, `list_events`, `get_event`, `create_event`, `update_event`, `delete_event`, `find_free_slots`

---

## Release cadence

| Version | Scope | Signal |
|---------|-------|--------|
| **v0.7.0** | ✅ First stable PyPI release — 63 tools across Sheets, Drive, Docs, Calendar | Published 2026-06-21 |
| **v0.8.0** | Tier 1 complete — all "frequently needed" items across all domains (~14 tools) | "Complete for everyday use" |
| **v0.9.0** | Tier 2 complete — power-user and structured-work layer (~20 tools) | Covers most real workflows |
| **v1.0.0** | API stability declaration — Tier 3 items that make the cut + any breaking cleanups from v0.8–0.9 | Backwards-compatibility commitment |
| **v1.1.0+** | Future domains — Tasks, Gmail (separate minor releases, each needs a new API client) | Expanded scope |

Tier 4 items remain backlog with no assigned version.

---

## Roadmap

### Tier 1 — High value, frequently needed _(target: v0.8.0)_

**Infrastructure**
- [x] PyPI publish — OIDC trusted publishing ([#55](https://github.com/khuisman/mcp-gee-sweet/issues/55)) — v0.7.0 stable live; `uvx mcp-gee-sweet` works

**Sheets**
- [x] `delete_sheet` — delete a tab by name or sheetId ([#115](https://github.com/khuisman/mcp-gee-sweet/issues/115)) _(freema/mcp-gsheets)_
- [x] `clear_values` — clear cell content in a range without touching formatting ([#116](https://github.com/khuisman/mcp-gee-sweet/issues/116)) _(freema/mcp-gsheets)_
- [x] `delete_rows` / `delete_columns` — remove rows or columns by index ([#117](https://github.com/khuisman/mcp-gee-sweet/issues/117)) _(freema/mcp-gsheets)_
- [x] `format_cells` — background color, font, alignment, number format on a range ([#118](https://github.com/khuisman/mcp-gee-sweet/issues/118)) _(freema/mcp-gsheets)_
- [x] `merge_cells` / `unmerge_cells` — merge a range into one cell ([#119](https://github.com/khuisman/mcp-gee-sweet/issues/119)) _(freema/mcp-gsheets)_
- [x] `freeze` — freeze rows and/or columns ([#120](https://github.com/khuisman/mcp-gee-sweet/issues/120))
- [x] `sort_range` — sort a range by one or more columns ([#121](https://github.com/khuisman/mcp-gee-sweet/issues/121))

**Calendar**
- [x] Recurring events — RRULE support in `create_event` and `update_event`; `expand_recurring` in `list_events`; instance vs master scope documented ([#155](https://github.com/khuisman/mcp-gee-sweet/issues/155))

**Docs**
- [x] `insert_inline_image` — insert an image at a document index ([#145](https://github.com/khuisman/mcp-gee-sweet/issues/145))
- [x] Table structural ops — `insert_table_row`, `delete_table_row`, `insert_table_column`, `delete_table_column` ([#146](https://github.com/khuisman/mcp-gee-sweet/issues/146))
- [x] `create_header` / `create_footer` — page headers and footers ([#147](https://github.com/khuisman/mcp-gee-sweet/issues/147))

**Drive**
- [x] `list_shared_with_me` — files explicitly shared with the authenticated user ([#135](https://github.com/khuisman/mcp-gee-sweet/issues/135))
- [x] `list_recent_files` — files recently accessed or modified ([#136](https://github.com/khuisman/mcp-gee-sweet/issues/136))
- [x] `get_storage_quota` — Drive storage usage and limits ([#137](https://github.com/khuisman/mcp-gee-sweet/issues/137))

### Tier 2 — Useful for structured work _(target: v0.9.0)_

**Sheets**
- [ ] `update_borders` — border style, width, color on a range ([#122](https://github.com/khuisman/mcp-gee-sweet/issues/122)) _(freema/mcp-gsheets)_
- [ ] `hide_rows` / `hide_columns` / unhide — toggle row or column visibility ([#123](https://github.com/khuisman/mcp-gee-sweet/issues/123)) _(freema/mcp-gsheets)_
- [ ] `resize_rows` / `resize_columns` — set pixel height/width, or auto-fit to content ([#124](https://github.com/khuisman/mcp-gee-sweet/issues/124)) _(freema/mcp-gsheets)_
- [ ] `add_data_validation` / `get_data_validation` — dropdowns, checkboxes, value constraints ([#125](https://github.com/khuisman/mcp-gee-sweet/issues/125)) _(freema/mcp-gsheets)_
- [ ] `update_sheet_properties` — tab color, hide/show gridlines ([#126](https://github.com/khuisman/mcp-gee-sweet/issues/126)) _(freema/mcp-gsheets)_
- [ ] `duplicate_sheet` — copy a sheet within the same spreadsheet ([#127](https://github.com/khuisman/mcp-gee-sweet/issues/127))

**Calendar**
- [ ] `create_calendar` / `update_calendar` / `delete_calendar` — calendar lifecycle ([#156](https://github.com/khuisman/mcp-gee-sweet/issues/156))
- [ ] `add_calendar_to_list` / `remove_calendar_from_list` — subscribe/unsubscribe ([#157](https://github.com/khuisman/mcp-gee-sweet/issues/157))
- [ ] Calendar ACL — share a calendar with users or groups ([#158](https://github.com/khuisman/mcp-gee-sweet/issues/158))

**Docs**
- [ ] `insert_page_break` — explicit page break at an index ([#148](https://github.com/khuisman/mcp-gee-sweet/issues/148))
- [ ] `merge_table_cells` — merge cells in an existing table (distinct from write-time colspan) ([#150](https://github.com/khuisman/mcp-gee-sweet/issues/150))
- [ ] Comments API — list, add, resolve doc comments ([#151](https://github.com/khuisman/mcp-gee-sweet/issues/151))
- [ ] `create_named_range` / `create_bookmark` — anchor points for internal links ([#152](https://github.com/khuisman/mcp-gee-sweet/issues/152))
- [ ] Rowspan emitter — AST `Cell.rowspan` field exists but emitter does not yet merge rows
- [ ] Warn/error on mixed text + nested table in same cell ([#108](https://github.com/khuisman/mcp-gee-sweet/issues/108))
- [ ] colspan/rowspan inside nested tables ([#109](https://github.com/khuisman/mcp-gee-sweet/issues/109))

**Drive**
- [ ] `restore_file` / `empty_trash` — undelete or permanently purge trashed files ([#138](https://github.com/khuisman/mcp-gee-sweet/issues/138))
- [ ] `star_file` / `unstar_file` — mark files with a star for easy retrieval ([#139](https://github.com/khuisman/mcp-gee-sweet/issues/139))
- [ ] `transfer_ownership` — transfer a file to another user ([#140](https://github.com/khuisman/mcp-gee-sweet/issues/140))
- [ ] `create_shortcut` — create a Drive shortcut to a file ([#141](https://github.com/khuisman/mcp-gee-sweet/issues/141))
- [x] Drive Activity API — file change history ([#72](https://github.com/khuisman/mcp-gee-sweet/issues/72))

### Tier 3 — Advanced / occasionally needed _(target: v1.0.0)_

**Sheets**
- [ ] `add_conditional_formatting` / `delete_conditional_formatting` ([#129](https://github.com/khuisman/mcp-gee-sweet/issues/129)) _(freema/mcp-gsheets)_
- [ ] `add_named_range` / `delete_named_range` ([#130](https://github.com/khuisman/mcp-gee-sweet/issues/130)) _(piotr-agier/google-drive-mcp)_
- [ ] `protect_sheet` / `protect_range` — lock a sheet or range against edits ([#128](https://github.com/khuisman/mcp-gee-sweet/issues/128)) _(piotr-agier/google-drive-mcp)_
- [ ] `set_basic_filter` / `clear_basic_filter` _(freema/mcp-gsheets)_

**Calendar**
- [ ] `quick_add` — create an event from a natural language string ([#159](https://github.com/khuisman/mcp-gee-sweet/issues/159))
- [ ] Event color coding — `colorId` on create/update ([#160](https://github.com/khuisman/mcp-gee-sweet/issues/160))
- [ ] Conference data — auto-create Google Meet link ([#161](https://github.com/khuisman/mcp-gee-sweet/issues/161))
- [ ] Event attachments — link Drive files to events ([#162](https://github.com/khuisman/mcp-gee-sweet/issues/162))
- [ ] Reminders — per-event override reminders (email, popup, minutes before) ([#163](https://github.com/khuisman/mcp-gee-sweet/issues/163))

**Docs**
- [ ] `create_footnote` — footnote at a run index ([#149](https://github.com/khuisman/mcp-gee-sweet/issues/149))
- [ ] `create_table_of_contents` ([#153](https://github.com/khuisman/mcp-gee-sweet/issues/153))
- [ ] `insert_section_break` — section breaks for per-section column/margin layout ([#154](https://github.com/khuisman/mcp-gee-sweet/issues/154))

**Drive**
- [ ] File comments — list and add comments on Drive files ([#142](https://github.com/khuisman/mcp-gee-sweet/issues/142))
- [ ] Watch notifications — webhook push on file changes ([#143](https://github.com/khuisman/mcp-gee-sweet/issues/143))
- [ ] Labels API — custom metadata labels on Drive files ([#144](https://github.com/khuisman/mcp-gee-sweet/issues/144))

### Tier 4 — Nice to have / niche _(no assigned version)_

**Sheets**
- [ ] `get_sheet_dimensions` — read column widths, row heights, frozen counts ([#132](https://github.com/khuisman/mcp-gee-sweet/issues/132)) _(freema/mcp-gsheets)_
- [ ] `add_note` / `clear_note` — cell notes (distinct from comments) ([#131](https://github.com/khuisman/mcp-gee-sweet/issues/131)) _(freema/mcp-gsheets)_
- [ ] Pivot tables — create and update pivot table specs via batchUpdate ([#133](https://github.com/khuisman/mcp-gee-sweet/issues/133))
- [ ] Developer metadata — key-value metadata attached to rows, columns, or ranges ([#134](https://github.com/khuisman/mcp-gee-sweet/issues/134))

**Calendar**
- [ ] Working location / OOO / Focus time events ([#164](https://github.com/khuisman/mcp-gee-sweet/issues/164))
- [ ] Watch notifications — webhook push on calendar or event changes ([#165](https://github.com/khuisman/mcp-gee-sweet/issues/165))

---

## Bugs found in Phase 1 QA run (2026-06-02)

### `add_chart` — multi-column range fails (BUG-1)
**Severity:** High — affects all practical chart use cases.
The tool passes the full data range (e.g. `A1:D5`) as a single `ChartSourceRange`. The Sheets API requires separate source range objects per column — one for the domain (X axis / categories) and one per series. Fix: parse the A1 range, split into domain (first column) and series (remaining columns), pass as separate entries in `sources`. ✅ Fixed.

### `add_chart` HISTOGRAM — wrong API spec (BUG-2)
**Severity:** Medium — HISTOGRAM specifically broken even after BUG-1 fixed.
`HISTOGRAM` is not a valid `BasicChartType` enum value. The Sheets API uses a `histogramChart` spec field rather than `basicChart.chartType`. Fix: detect `chart_type == "HISTOGRAM"` and build a `histogramChart` spec instead. ✅ Fixed.

### `add_chart` BAR — wrong series target axis (BUG-3)
**Severity:** Medium — BAR charts fail with "series may only target the BOTTOM_AXIS".
BAR charts (horizontal) have a horizontal value axis. Series must target `BOTTOM_AXIS`, not `LEFT_AXIS`. Fix: detect `chart_type == "BAR"` and set `targetAxis` accordingly. ✅ Fixed.

### `add_chart` COMBO — no per-series type specified (BUG-4)
**Severity:** Medium — COMBO charts fail with "No basic chart type specified".
The Sheets API requires each series in a COMBO chart to declare its own `type`. Fix: when `chart_type == "COMBO"`, add `type: COLUMN` to all series except the last, which gets `type: LINE`. ✅ Fixed.

### TC-W03 — test case assumption wrong
The test expected the API to silently truncate a 2D array that's wider than the target range. The API actually rejects it with a 400 error. The test case needs to be updated to reflect correct API behaviour. ✅ Fixed.

---

## Testing

### Unit tests (456 passing as of 2026-06-24)
- [x] Add `pytest` and `pytest-cov` as dev dependencies
- [x] Cache logic — TTL expiry, dirty flag, partial invalidation for all five cache classes; in-memory SQLite
- [x] A1 notation helpers — `_parse_a1_notation`, `_column_index_to_letter`, `_letter_to_column_index`
- [x] Tool filtering — tools excluded when not in `ENABLED_TOOLS`
- [x] Service account quota error handling — structured error on 403 quota exceeded; non-quota 403s raise
- [x] `server://auth-status` resource — correct capabilities for service_account, oauth, and adc
- [x] Docs AST pipeline — `html_to_ast`, `ast_to_requests`, `fill_tables`, nested table emitter, cell style emitter, run style Phase 3 fields
- [x] Docs tools — `write_doc_content`, `style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `get_doc_named_styles`, `apply_theme`
- [x] Fix BUG-1–4: `add_chart` multi-column ranges, HISTOGRAM spec, BAR axis, COMBO per-series types
- [x] Update TC-W03 test case — API rejects oversized 2D arrays, does not silently truncate

### Live QA (AI-driven test cases in `docs/qa/tests/`)
- [x] Sheets read, write, management, charts — `sheets_read.md`, `sheets_write.md`, `sheets_mgmt.md`, `sheets_charts.md`
- [x] Drive files and sharing — `drive.md`
- [x] Google Docs tools (all 13) — `docs.md`
- [x] Calendar tools — `calendar.md`
- [x] Infrastructure — `infra.md`
- See [GitHub Issues (label: qa)](https://github.com/khuisman/mcp-gee-sweet/issues?q=label%3Aqa) for open QA gaps and fixture issues

---

## Infrastructure / internal

- [x] Migrate cache persistence — replaced four `/tmp/*.json` files with a single SQLite DB (`/tmp/mcp_gee_sweet.db`, configurable via `CACHE_DB_PATH`); one table, four namespaces; WAL mode
- [x] Open PR to xing5 from `upstream-observability` branch (structured logging, per-tool timing, `cache_discovery=False`) — [PR #79](https://github.com/xing5/mcp-google-sheets/pull/79)
- [x] Fork repo and rename to `mcp-gee-sweet`; README credits xing5, freema, and piotr-agier
- [x] PyPI publish — v0.7.0 stable on PyPI; dev track publishes `0.7.0.devN` on every push to `develop`
- [ ] Live QA system — fixture setup, per-release run files (`docs/qa/runs/vX.Y.Z.md`), Playwright OAuth automation ([#173](https://github.com/khuisman/mcp-gee-sweet/issues/173)) _(gate for v0.8.0)_
- See [GitHub Issues (label: infrastructure)](https://github.com/khuisman/mcp-gee-sweet/issues?q=label%3Ainfrastructure) for open infrastructure work

---

## Future domains

### Tasks

Requires `tasks/v1` client and `https://www.googleapis.com/auth/tasks` scope. Add `tasks_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan alongside the existing clients.

**Task lists**
- [ ] `list_task_lists` — list all task lists for the authenticated user
- [ ] `get_task_list` — fetch metadata for a single task list
- [ ] `create_task_list` — create a new task list
- [ ] `delete_task_list` — delete a task list and all its tasks

**Tasks**
- [ ] `list_tasks` — list tasks in a task list with optional due date filter and completed/hidden flags
- [ ] `get_task` — fetch a single task by task list ID + task ID
- [ ] `create_task` — create a task (title, notes, due date, parent for subtasks)
- [ ] `update_task` — update fields on an existing task (`tasks().patch()`)
- [ ] `delete_task` — delete a task
- [ ] `complete_task` — mark a task as completed (shortcut for `update_task` with `status='completed'`)
- [ ] `clear_completed` — delete all completed tasks from a list (`tasks().clear()`)

### Gmail

Requires `gmail/v1` client and `https://www.googleapis.com/auth/gmail.modify` scope (or narrower `gmail.readonly` / `gmail.send` scopes where appropriate). Add `gmail_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan.

**Reading**
- [ ] `list_messages` — list messages with optional query string (same syntax as Gmail search), label filter, and pagination
- [ ] `get_message` — fetch a single message by ID; return headers, body (plain text + HTML), and attachment metadata
- [ ] `list_threads` — list conversation threads with optional query and label filter
- [ ] `get_thread` — fetch all messages in a thread
- [ ] `list_labels` — list all labels (system and user-defined)

**Sending and drafts**
- [ ] `send_message` — send an email (to, cc, bcc, subject, body, optional attachments)
- [ ] `create_draft` — create a draft without sending
- [ ] `send_draft` — send an existing draft by ID
- [ ] `reply_to_message` — send a reply in an existing thread

**Organization**
- [ ] `modify_labels` — add or remove labels from a message or thread (covers archive, mark read/unread, star, etc.)
- [ ] `trash_message` — move a message to trash
- [ ] `delete_message` — permanently delete a message

---

## Potential / under consideration

- **Google Keep** — philosophically in scope (Workspace productivity tool) but the Keep API v1 is read-only for most operations and was historically restricted to Workspace Business/Enterprise accounts. Creating and editing notes via an officially supported third-party API is not currently possible. Revisit if Google opens the API further.

- **SQLite cache encryption at rest** — the cache DB (`/tmp/mcp_gee_sweet.db`) stores Google Sheets data in plaintext. For deployments that handle sensitive data, consider [SQLCipher](https://www.zetetic.net/sqlcipher/) (open-source, AES-256, mostly API-compatible with standard SQLite) or rely on filesystem-level encryption (FileVault, LUKS, BitLocker). The official SQLite Encryption Extension (SEE) is an alternative but is commercial/proprietary. Not needed for typical local-dev use.

---

## Inspiration and credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — original upstream this project was forked from
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) — most comprehensive Sheets-specific MCP server; primary source for formatting, validation, and sheet property roadmap items
- [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — full Workspace suite; primary source for Drive file operations, permissions, and named/protected range roadmap items
