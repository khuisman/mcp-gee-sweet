# TODO

Prioritized work queue. See [docs/roadmap.md](docs/roadmap.md) for full context and credits.

## Up next

1. ~~**Fix A1 notation bugs**~~ ✓ — fixed open-ended range `endRowIndex` and empty-string raising. [Issue #11](https://github.com/khuisman/mcp-gee-sweet/issues/11)
2. ~~**SQLite cache migration**~~ ✓ — single DB at `/tmp/mcp_gee_sweet.db`, four namespaces, WAL mode
3. ~~**Cache unit tests**~~ ✓ — 32 tests covering TTL, dirty flag, partial invalidation, all four caches
4. **PyPI publish** — set up trusted publishing (OIDC) on PyPI, do a test release; CI workflow already written
5. ~~**Bug: sheet names with spaces break range strings**~~ ✓ — added `_quote_sheet_name()` helper in `helpers.py`; applied to all seven range-construction sites across `read.py` and `write.py` (`get_sheet_data`, `get_sheet_formulas`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `find_in_spreadsheet`, `update_cells`, `batch_update_cells`).

## Post-PR cleanup

Flagged in code reviews on PR #18, #20, and #22 — tackle after open PRs are merged.

- ~~**Move local imports to top of file**~~ ✓ — `MediaFileUpload`, `MediaInMemoryUpload`, `MediaIoBaseDownload`, and `markdown` moved to top-level imports in `drive.py`.
- ~~**Extract `_EXPORT_MIME` into a module-level constant**~~ ✓ — hoisted to module level as `dict[str, tuple[str, str]]`; `export_file` updated to use `[0]` for mime type. Four local definitions removed.
- ~~**Unit tests for cache invalidation**~~ ✓ — 6 new tests in `TestDriveFolderCacheInvalidation` covering `create_folder`, `move_file`, `delete_file` (trash + permanent), and `upload_file`.
- **Link `qa-checklist.md` to TC numbers** — the checklist items in `docs/qa-checklist.md` and the ai-guided test cases in `docs/qa/tests/` cover the same ground but don't reference each other. Each checklist item should cite its TC number(s) so the checklist can serve as attestation that specific test cases were run and passed.
- **Pin GitHub Actions to commit SHAs** — `actions/checkout@v4`, `astral-sh/setup-uv@v5`, `actions/upload-artifact@v4`, `actions/download-artifact@v4`, `pypa/gh-action-pypi-publish` use mutable tags; a compromised upstream repo can move the tag to malicious code. As part of this work: (1) research the latest versions of each action that support Node.js 24 (Node 20 deprecated June 2 2026, removed Sept 16 2026 — currently papered over with `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`), (2) pin each to a specific commit SHA, (3) enable Dependabot for `github-actions` to keep SHAs updated automatically.
- **Update `decision-fork.md` — "What This Project Has That Alternatives Don't"** — section is out of date; the project has grown substantially (Calendar tools, Drive permissions, sync, upload/download, etc.) since this was written. Review and rewrite to reflect current state; also reassess the alternatives — they may have shipped new features since May 2026.
- **Investigate Calendar settings API** — the Calendar API has a `settings()` endpoint that exposes user preferences: working hours, timezone, locale, default reminders, etc. Assess whether a `get_calendar_settings` (or `update_calendar_settings`) tool would be useful; check what the API actually returns for a service account vs. a user account.
- ~~**Wire up MkDocs build and publish**~~ ✓ — `docs.yml` deploys to GitHub Pages via `mkdocs gh-deploy` on merge to main; `ci.yml` runs lint + tests on every push/PR; `release.yml` now gates on tests before building.
- ~~**Remove `site/` from git tracking**~~ ✓ — `git rm -r --cached site/` done; `.gitignore` entry already present.

## Tier 1 features

5. `clear_values` — clear cell content in a range without touching formatting
6. `delete_sheet` — delete a tab by name or sheetId
7. `delete_rows` / `delete_columns` — remove rows or columns by index range
8. `update_sheet_properties` — set tab color, freeze rows/cols, hide/show gridlines

## Drive

Items already done: `create_folder`, `move_file`, `rename_file`, `copy_file`, `delete_file`, `search_files`, `get_file_metadata`.

9. ~~`rename_file`~~ ✓ — rename any file or folder (`files().update()` with new `name`)
10. ~~`copy_file`~~ ✓ — duplicate a file (`files().copy()`); useful for template workflows
11. ~~`trash_file` / `delete_file`~~ ✓ — `permanent=False` trashes, `permanent=True` permanently deletes
12. ~~`search_files`~~ ✓ — general Drive search across all MIME types, optional mime_type + folder_id filter
13. ~~`get_file_metadata`~~ ✓ — fetch name, MIME type, parents, modified time, size, owners, trashed status
14. ~~`list_permissions`~~ ✓ — list all permissions on any file/folder (`permissions().list()`)
15. ~~`update_permission`~~ ✓ — change role on an existing permission (`permissions().update()`)
16. ~~`remove_permission`~~ ✓ — revoke a permission by ID (`permissions().delete()`)
17. ~~`share_file`~~ ✓ — generalized `share_spreadsheet`; supports type=user/group/domain/anyone

### QA — Drive permissions tools

- [ ] `list_permissions(file_id)` — returns at least the owner entry; owner role is `owner`, type is `user`
- [ ] `list_permissions(file_id)` on a shared file — shared user's email appears with correct role
- [ ] `share_file` type=user — share with a test address as `reader`; `list_permissions` confirms new entry
- [ ] `share_file` type=user — share with bad role `'admin'` — returns failure, not exception
- [ ] `share_file` type=user — omit `email_address` — returns failure entry, not exception
- [ ] `share_file` type=domain — share with a domain; `list_permissions` shows domain entry
- [ ] `share_file` type=anyone role=reader — makes file public; `list_permissions` shows `anyone` entry
- [ ] `update_permission` — downgrade a `writer` to `reader`; `list_permissions` reflects new role
- [ ] `update_permission` — invalid role `'owner'` — returns `{"error": ...}`, not exception
- [ ] `remove_permission` — removes a previously-added permission; `list_permissions` no longer shows it
- [ ] `remove_permission` — invalid permission_id — Drive API raises; verify error surfaces cleanly
- [ ] `share_file` on a folder — verify permissions propagate to children (manual check in Drive UI)
18. ~~`list_drives`~~ ✓ — enumerate shared / Team Drives (`drives().list()`), with optional query filter and pagination
19. ~~`export_file`~~ ✓ — download non-Google files and export Google files to PDF/DOCX/HTML (`files().export()` / `files().get_media()`)

## Docs

Items already done: `create_doc`, `get_doc_content`, `write_doc_content`.

20. `append_doc_content` — append HTML to the end of an existing doc without replacing it
21. `find_replace_in_doc` — find and replace text across a doc (`replaceAllText` Docs API request)
22. ~~`export_doc`~~ ✓ — covered by `export_file` (item 19)
23. `get_doc_structure` — return headings, paragraphs, and lists as structured data instead of a flat string
24. `rename_file` _(shared with Drive item 9)_ — rename a doc via `files().update()`
25. `insert_image_in_doc` — insert an inline image (`insertInlineImage` Docs API request)
26. Table operations — `insert_table`, `delete_table`, `update_table_cell`
27. Headers / footers — `create_header`, `create_footer`, `update_header_footer`

### Markdown → Google Doc flow

~~`upload_file`~~ ✓ — `source_format='markdown'`, `convert_to_doc=True`; converts via `markdown[extra]` → HTML → Drive HTML import. Handles headings, lists, bold/italic, tables, fenced code, links.

## Calendar

Requires `google-api-python-client` Calendar client (`calendar/v3`) and `https://www.googleapis.com/auth/calendar` scope. Add `calendar_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan alongside the existing Sheets and Drive clients.

32. ~~`list_calendars`~~ ✓ — list all calendars accessible to the authenticated user (`calendarList().list()`)
33. ~~`get_calendar`~~ ✓ — fetch metadata for a single calendar by ID (name, timezone, access role)
34. ~~`list_events`~~ ✓ — list events in a calendar with optional `time_min`/`time_max`, `query`, and `max_results` (`events().list()`)
35. ~~`get_event`~~ ✓ — fetch a single event by calendar ID + event ID
36. ~~`create_event`~~ ✓ — create a new event (summary, start/end datetime, description, location, attendees, timezone)
37. ~~`update_event`~~ ✓ — update fields on an existing event (`events().patch()`)
38. ~~`delete_event`~~ ✓ — delete or cancel an event (`events().delete()`)
39. ~~`find_free_slots`~~ ✓ — given a list of calendars + a time window, return free slots (`freebusy().query()`)

## Tasks

Requires `tasks/v1` client and `tasks` scope. Add `tasks_service` to `SpreadsheetContext`, wire up in `auth.py` lifespan.

48. `list_task_lists` — list all task lists
49. `get_task_list` — fetch metadata for a single task list
50. `create_task_list` — create a new task list
51. `delete_task_list` — delete a task list and all its tasks
52. `list_tasks` — list tasks in a list with optional due date filter and completed/hidden flags
53. `get_task` — fetch a single task by task list ID + task ID
54. `create_task` — create a task (title, notes, due date, parent for subtasks)
55. `update_task` — update fields on an existing task
56. `delete_task` — delete a task
57. `complete_task` — mark a task completed (shortcut for `update_task` with `status='completed'`)
58. `clear_completed` — delete all completed tasks from a list

## Tool access presets

Preset names for `ENABLED_TOOLS` derived automatically from tool annotations (no hardcoded lists):

- `readonly` — all tools where `readOnlyHint=True`
- `standard` — readonly + create/update, excluding `destructiveHint=True` tools
- `full` — all registered tools (current default when `ENABLED_TOOLS` is unset)

Presets are resolved in the `ENABLED_TOOLS` parser in `server.py` before tool registration. Support mixing: `ENABLED_TOOLS=readonly,create_event` takes a preset and adds individual tools.

## Tier 2 features

28. Cell formatting — `format_cells`, `update_borders`, `merge_cells` / `unmerge_cells`
29. Data validation — `add_data_validation`, `get_data_validation`
30. Row/column sizing — `resize_rows` / `resize_columns`, `hide_rows` / `hide_columns`

## Tier 3+ features

31. Conditional formatting, named/protected ranges, permissions, filters _(see roadmap for details)_

## Composite workflows

Server-side tools that wrap multi-step chains worth implementing for reliability, not just convenience. See [docs/decision-composite-tools.md](docs/decision-composite-tools.md) for the full rationale.

40. `sheet_to_doc` — pull data from a sheet range and render it as a formatted report doc; server-side to handle table/cell encoding decisions that Claude gets inconsistently (`get_sheet_data` → `create_doc` + `write_doc_content`)
43. `bulk_export_folder` — export every doc/file in a folder to a target format (PDF, DOCX, etc.); server-side because the loop involves base64 binary decode on each file and pagination (`list_files` → loop `export_file`)
46. `drive_inventory_doc` — generate a structured index of a folder's contents as a Google Doc; server-side to handle pagination and large result sets reliably (`list_files` + `get_file_metadata` → `create_doc` + `write_doc_content`)

### Won't do — simple alias workflows

These are straightforward two-call chains that Claude handles correctly without a dedicated tool. Adding a wrapper would add surface area with no reliability benefit. See [docs/decision-composite-tools.md](docs/decision-composite-tools.md).

- ~~41. `create_from_template`~~ — `copy_file` → `write_doc_content`; two sequential calls Claude gets right
- ~~42. `log_calendar_to_sheet`~~ — `list_events` → `add_rows`; two sequential calls Claude gets right
- ~~44. `book_next_free_slot`~~ — `find_free_slots` → `create_event`; two sequential calls Claude gets right
- ~~45. `find_and_update_row`~~ — `find_in_spreadsheet` → `update_cells`; two sequential calls Claude gets right
- ~~47. `markdown_to_doc`~~ — already works via `upload_file` with `source_format='markdown'`; a named alias adds nothing

## Testing

14. **Formatting integration spike** — explore what `get_sheet_data(include_grid_data=True)` returns for formatted cells; determine fixture strategy (dedicated test sheet vs. ephemeral); assess whether API-level assertions cover formatting without a browser
15. **Integration tests** — API-level smoke tests against a dedicated test Drive folder using service account credentials; one test per tool
16. **OAuth integration tests** — verify auth fallback chain and tool behavior under user credentials; required for `create_doc`/`create_spreadsheet` in personal Drive
