# Feature Roadmap

This doc is a high-level orientation — feature ideas, architectural direction, and historical context. **Active work is tracked in [GitHub Issues](https://github.com/khuisman/mcp-gee-sweet/issues).** When a roadmap item is scheduled, an issue is opened; the checkbox here stays as a reference.

Features are ordered by practical priority within each tier, cross-domain. Items marked with a source were identified by auditing competing projects — see [decision-fork.md](decisions/decision-fork.md) for full credits.

## What's implemented

### Google Sheets — 25 tools
- **Read:** `get_sheet_data`, `get_sheet_formulas`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `find_in_spreadsheet`
- **Write:** `update_cells`, `batch_update_cells`, `batch_update` _(raw batchUpdate passthrough — escape hatch for anything not covered by named tools)_
- **Structure:** `list_sheets`, `create_sheet`, `rename_sheet`, `copy_sheet`, `duplicate_sheet`, `delete_sheet`, `add_rows`, `add_columns`, `delete_rows`, `delete_columns`, `format_cells`, `merge_cells`, `unmerge_cells`, `freeze`, `sort_range`, `add_chart`
- **Data ops:** `clear_values`

### Google Drive — 32 tools
- **Files:** `list_files`, `list_spreadsheets`, `search_files`, `search_spreadsheets`, `list_folders`, `list_drives`, `get_file_metadata`, `create_spreadsheet`, `import_csv_to_sheet`, `create_folder`, `copy_file`, `move_file`, `rename_file`, `delete_file`, `list_shared_with_me`, `list_recent_files`, `get_storage_quota`
- **Sharing:** `share_spreadsheet`, `share_file`, `list_permissions`, `update_permission`, `remove_permission`
- **Transfer:** `upload_file`, `upload_local_file`, `upload_local_folder`, `download_file`, `download_folder`, `sync_folder`, `export_file`, `export_revision`, `list_revisions`
- **Activity:** `list_file_activity` _(Drive Activity API v2; requires `drive.activity.readonly` scope)_

### Google Docs — 20 tools
- **Content:** `create_doc`, `create_doc_from_file`, `get_doc_content`, `write_doc_content`, `insert_doc_text`, `delete_doc_range`, `get_doc_structure`, `insert_doc_table`, `insert_inline_image`, `create_header`, `create_footer`
- **Styling:** `style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `get_doc_named_styles`, `apply_theme`
- **Table structure:** `insert_table_row`, `delete_table_row`, `insert_table_column`, `delete_table_column`

### Google Calendar — 13 tools
- **Calendars:** `list_calendars`, `get_calendar`, `create_calendar`, `update_calendar`, `delete_calendar`, `add_calendar_to_list`, `remove_calendar_from_list`
- **Events:** `list_events`, `get_event`, `create_event`, `update_event`, `delete_event`, `find_free_slots`

---

## Release cadence

| Version | Scope | Signal |
|---------|-------|--------|
| [**v0.7.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.7) | ✅ First stable PyPI release — 63 tools across Sheets, Drive, Docs, Calendar | Published 2026-06-21 |
| [**v0.8.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8) | ✅ Tier 1 complete — all "frequently needed" items across all domains (84 tools) | Published 2026-06-29 |
| [**v0.8.1**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8.1) | Defect & documentation cleanup — no new tools, ships the QA/refactor work already on `develop` plus fixes for #235, #242, #213, #239, #236 | Stabilizes before Tier 2 feature work begins |
| [**v0.9.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9) | Tier 2 complete — power-user and structured-work layer (~20 tools), plus defects that surfaced after v0.8.1 shipped ([#248](https://github.com/khuisman/mcp-gee-sweet/issues/248)) | Covers most real workflows |
| [**v1.0.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av1.0) | API stability declaration — Tier 3 items that make the cut + any breaking cleanups from v0.8–0.9 | Backwards-compatibility commitment |
| [**v1.1.0+**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22v1.1%2B%22) | Future domains — Tasks, Gmail (separate minor releases, each needs a new API client) | Expanded scope |

Tier 4 items remain backlog with no assigned version.

---

## Roadmap

### Tier 1 — High value, frequently needed _(target: [v0.8.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8))_

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

### v0.8.1 — Defect & documentation cleanup _(target: [v0.8.1](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8.1), before Tier 2 begins)_

No new tools. Stabilize on what Tier 1 shipped before starting Tier 2 feature work.

**Already on `develop`, awaiting release**
- [x] Playwright per-test tagging policy, conductor prompt improvements (PR #228)
- [x] QA test case fixes — `share_file` fixtures, TC-D148 setup, Playwright tags (PR #229)
- [x] SQLite cache defensive recovery from read-only/corrupted DB files at connect time (PR #230)
- [x] `tools/docs/__init__.py` split into `content.py`/`tables.py`/`style.py`/`layout.py` (PR #232)

**Remaining defects to fix before cutting the release**
- [x] `get_sheet_data(include_grid_data=True)` without a range fetches the full padded grid instead of the used range ([#235](https://github.com/khuisman/mcp-gee-sweet/issues/235))
- [x] Generalize the #235 response-size safety net (post-fetch size check + configurable cap + `local_path` bypass) to other tools that can return large responses — `export_file`, `get_doc_content`, `get_multiple_sheet_data`, `find_in_spreadsheet`, `list_file_activity`. Oversized responses silently kill the MCP session today (client-side output cap, e.g. Claude Code's `MAX_MCP_OUTPUT_TOKENS`), requiring a server restart to recover — confirmed live, not hypothetical. Renamed `MAX_GRID_DATA_RESPONSE_CHARS` to `MAX_TOOL_RESPONSE_CHARS` (single global cap); live-verified thresholds per tool ([#242](https://github.com/khuisman/mcp-gee-sweet/issues/242))
- [x] `create_doc_from_file` markdown `$` escape renders as literal backslash+dollar in the doc — Python-Markdown's default `ESCAPED_CHARS` omitted `$` (unlike CommonMark); fixed via a small extension adding it, respecting code-span/fenced-code protection ([#213](https://github.com/khuisman/mcp-gee-sweet/issues/213))
- [x] Unknown tool parameters are silently dropped instead of raising a validation error — FastMCP's generated pydantic arg models default to ignoring extra fields, so a typo'd kwarg (e.g. `parent_id` instead of `parent_folder_id`) silently falls back to default behavior instead of erroring. Fixed centrally in the `tool()` decorator (applies to all ~84 tools uniformly) ([#239](https://github.com/khuisman/mcp-gee-sweet/issues/239))
- [x] Auto-generate `docs/tools.md` from tool source as a pre-commit hook — makes the manual tools.md backfill in #236 unnecessary (PR #240) ([#94](https://github.com/khuisman/mcp-gee-sweet/issues/94))
- [x] Correct `docs/roadmap.md`'s own tool catalog counts, `known-limitations.md`'s `list_all_events` entry, and rework README's/`docs/client-setup.md`'s Configuration examples to lead with OAuth (not service account) for local/dev quick-start — currently mismatches the project's own auth priority order and PyPI's page inherits it verbatim ([#236](https://github.com/khuisman/mcp-gee-sweet/issues/236))
- [x] Rewrite `CONTRIBUTING.md` — fix broken links to removed README anchors, fix stale "Available Tool Names" and `bug`-label references, add better local-dev setup examples including observability (`DEBUG_LEVEL`/`LOG_FILE`/`ACCESS_LOG_FILE`) ([#95](https://github.com/khuisman/mcp-gee-sweet/issues/95))
- [ ] Define and document community PR expectations — template, testing bar for non-tool PRs, scope/size convention, CLA/DCO/code-of-conduct decision, review turnaround ([#237](https://github.com/khuisman/mcp-gee-sweet/issues/237))

### Tier 2 — Useful for structured work, plus defects surfaced since v0.8.1 _(target: [v0.9.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9))_

**Defects** _(found after v0.8.1 shipped; too late for that release, don't warrant a standalone patch)_
- [x] Dev prereleases become unreachable once the base version's stable release ships — `format-jinja` never bumps past the last tag, so `X.Y.Z.devN` is a PEP 440 pre-release of the already-published `X.Y.Z` and always loses precedence to it; fix is `bump = true` in `[tool.uv-dynamic-versioning]` (PR #318) ([#317](https://github.com/khuisman/mcp-gee-sweet/issues/317))
- [ ] `sync_folder` doesn't recurse into subfolders — one-level-only Drive query silently reports a clean "in sync" result while ignoring every nested file (confirmed live: 225 files across 22 subfolders ignored, only the root-level file seen) ([#315](https://github.com/khuisman/mcp-gee-sweet/issues/315))
- [ ] `download_folder`'s file loop is genuinely sequential (`for f in ...: await asyncio.to_thread(...)`) — the one multi-file transfer path missed when the `asyncio.gather` pattern was established (#183); `sync_folder`'s own transfer step already uses it correctly ([#316](https://github.com/khuisman/mcp-gee-sweet/issues/316))
- [x] Bare URLs in markdown content aren't autolinked — Python-Markdown's built-in autolink only fires on `<https://...>` or `[text](url)`, not a bare URL (PR #265) ([#248](https://github.com/khuisman/mcp-gee-sweet/issues/248))
- [x] `zip(doc_tables, ast_tables)` in `emitter.py` silently cross-pairs tables when one is skipped (zero-row/zero-col table), misapplying fill/merge/style requests to the wrong table — surfaced during #276's review (PR #282) ([#277](https://github.com/khuisman/mcp-gee-sweet/issues/277))

**Sheets**
- [x] `update_borders` — border style, width, color on a range (PR #325) ([#122](https://github.com/khuisman/mcp-gee-sweet/issues/122)) _(freema/mcp-gsheets)_
- [x] `hide_rows` / `hide_columns` / unhide — toggle row or column visibility ([#123](https://github.com/khuisman/mcp-gee-sweet/issues/123)) _(freema/mcp-gsheets)_ (PR #311)
- [x] `resize_rows` / `resize_columns` — set pixel height/width, or auto-fit to content (PR #321) ([#124](https://github.com/khuisman/mcp-gee-sweet/issues/124)) _(freema/mcp-gsheets)_
- [ ] `add_data_validation` / `get_data_validation` — dropdowns, checkboxes, value constraints ([#125](https://github.com/khuisman/mcp-gee-sweet/issues/125)) _(freema/mcp-gsheets)_
- [x] `update_sheet_properties` — tab color, hide/show gridlines (PR #301) ([#126](https://github.com/khuisman/mcp-gee-sweet/issues/126)) _(freema/mcp-gsheets)_
- [x] `duplicate_sheet` — copy a sheet within the same spreadsheet (PR #286) ([#127](https://github.com/khuisman/mcp-gee-sweet/issues/127))
- [ ] Partial (rich-text) hyperlinks in `update_cells` ([#89](https://github.com/khuisman/mcp-gee-sweet/issues/89))
- [x] `import_csv_to_sheet` — populate a spreadsheet from a local CSV file (PR #272) ([#187](https://github.com/khuisman/mcp-gee-sweet/issues/187))

**Calendar**
- [x] `create_calendar` / `update_calendar` / `delete_calendar` — calendar lifecycle (PR #266) ([#156](https://github.com/khuisman/mcp-gee-sweet/issues/156))
- [x] `add_calendar_to_list` / `remove_calendar_from_list` — subscribe/unsubscribe (PR #269) ([#157](https://github.com/khuisman/mcp-gee-sweet/issues/157))
- [ ] Calendar ACL — share a calendar with users or groups ([#158](https://github.com/khuisman/mcp-gee-sweet/issues/158))
- [ ] `list_all_events` — query all subscribed calendars in parallel _(decision needed — also tracked in Decisions Needed)_ ([#194](https://github.com/khuisman/mcp-gee-sweet/issues/194))

**Docs**
- [x] `insert_page_break` — explicit page break at an index ([#148](https://github.com/khuisman/mcp-gee-sweet/issues/148)) (PR #314)
- [x] `merge_table_cells` — merge cells in an existing table (distinct from write-time colspan) ([#150](https://github.com/khuisman/mcp-gee-sweet/issues/150)) (PR #310)
- [x] Comments API — list, add, resolve doc comments (PR #324) ([#151](https://github.com/khuisman/mcp-gee-sweet/issues/151))
- [ ] `create_named_range` / `create_bookmark` — anchor points for internal links ([#152](https://github.com/khuisman/mcp-gee-sweet/issues/152))
- [x] Rowspan emitter — closed as duplicate, already implemented via #100 (rowspan support) and PR #287 (nested-table colspan/rowspan) ([#195](https://github.com/khuisman/mcp-gee-sweet/issues/195))
- [x] Warn/error on mixed text + nested table in same cell — shipped as the fuller `Cell.children: list[Run | Table]` ordered model, also fixing trailing-text-after-nested-table ordering ([#275](https://github.com/khuisman/mcp-gee-sweet/issues/275)) in the same PR (PR #276) ([#108](https://github.com/khuisman/mcp-gee-sweet/issues/108))
- [x] colspan/rowspan inside nested tables (PR #287) ([#109](https://github.com/khuisman/mcp-gee-sweet/issues/109))
- [ ] `find_in_doc` — search doc text and return match locations, parallel to `find_in_spreadsheet`; removes the manual index math currently needed to retrofit links (or any style) onto text already in a doc, raised while fixing #248 ([#262](https://github.com/khuisman/mcp-gee-sweet/issues/262))

**Drive**
- [ ] `restore_file` / `empty_trash` — undelete or permanently purge trashed files ([#138](https://github.com/khuisman/mcp-gee-sweet/issues/138))
- [ ] `star_file` / `unstar_file` — mark files with a star for easy retrieval ([#139](https://github.com/khuisman/mcp-gee-sweet/issues/139))
- [ ] `transfer_ownership` — transfer a file to another user ([#140](https://github.com/khuisman/mcp-gee-sweet/issues/140))
- [ ] `create_shortcut` — create a Drive shortcut to a file ([#141](https://github.com/khuisman/mcp-gee-sweet/issues/141))
- [ ] `sync_folder` — option to convert markdown files to Google Docs on upload ([#211](https://github.com/khuisman/mcp-gee-sweet/issues/211))
- [ ] `upload_local_file` with Drive format conversion (CSV→Sheets, MD→Docs) ([#188](https://github.com/khuisman/mcp-gee-sweet/issues/188))
- [ ] Expose `md5Checksum` in `list_files`/`get_file_metadata` for real content-diffing, and let `sync_folder` diff by checksum instead of/in addition to `modifiedTime` — mtime is unreliable across in-place overwrites, `upload_local_file`'s "now" stamp, and content-preserving regenerations; related to #239 ([#274](https://github.com/khuisman/mcp-gee-sweet/issues/274))
- [x] Drive Activity API — file change history ([#72](https://github.com/khuisman/mcp-gee-sweet/issues/72))

**Infrastructure**
- [x] Harden concurrent-session access — fail-open on cache read/write errors, `busy_timeout` (PR #280) ([#234](https://github.com/khuisman/mcp-gee-sweet/issues/234))
- [x] Cache reliability & configurability — runtime-configurable TTL, smarter invalidation for shared files (PR #284) ([#99](https://github.com/khuisman/mcp-gee-sweet/issues/99))
- [ ] Async tool execution — `asyncio.gather()` for parallel Google API calls; establishes the project's parallel-call pattern, which [#194](https://github.com/khuisman/mcp-gee-sweet/issues/194) should reuse rather than introducing its own `ThreadPoolExecutor` ([#183](https://github.com/khuisman/mcp-gee-sweet/issues/183))

**Documentation**
- [x] Rewrite positioning/differentiation in README and `docs/index.md` — official Google MCP servers are now in developer preview, which undercuts the current "no official alternative exists" framing; lead with concrete differentiators (tool breadth, stability/QA gate, design philosophy) instead, checked against what the official servers actually cover (PR #306) ([#263](https://github.com/khuisman/mcp-gee-sweet/issues/263))

### Tier 3 — Advanced / occasionally needed _(target: [v1.0.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av1.0))_

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
- [ ] Sheet comments and cell notes (add/get/list/reply/resolve/delete) — we have zero comment tooling on Sheets today _(a-bonus/google-docs-mcp)_
- [ ] Conditional formatting rules — add/get/delete _(a-bonus/google-docs-mcp)_
- [ ] Protected ranges — protect/unprotect a range _(a-bonus/google-docs-mcp)_
- [ ] Dropdown / data validation on a range _(a-bonus/google-docs-mcp)_
- [ ] Row grouping (outline/collapse) — group/ungroup rows _(a-bonus/google-docs-mcp)_
- [ ] Auto-resize columns/rows to fit content _(a-bonus/google-docs-mcp)_
- [ ] Write-side column widths / row heights — companion to the read-only `get_sheet_dimensions` above ([#132](https://github.com/khuisman/mcp-gee-sweet/issues/132)) _(a-bonus/google-docs-mcp)_
- [ ] Native Sheets "Tables" object support (create/list/get/delete/update a structured Table, distinct from a plain range) — a newer Sheets API feature we don't touch at all _(a-bonus/google-docs-mcp)_
- [ ] Copy formatting only, without values (paste-special-style) _(a-bonus/google-docs-mcp)_

**Docs**
- [ ] Doc comments (add/get/list/reply/resolve/delete) — we have zero comment tooling on Docs today _(a-bonus/google-docs-mcp)_
- [ ] Multi-tab document support (list/add/rename tabs) — Google Docs' newer per-document tabs feature _(a-bonus/google-docs-mcp)_
- [ ] Smart chips — date chips, person chips, rich links; `list_smart_chips` to enumerate existing ones _(a-bonus/google-docs-mcp)_
- [ ] Section breaks and per-section page styling _(a-bonus/google-docs-mcp)_
- [ ] Page breaks _(a-bonus/google-docs-mcp)_
- [ ] Table structure discovery and cloning (read a table's row/column structure; clone an existing table) _(a-bonus/google-docs-mcp)_
- [ ] Finer-grained table styling — per-border, per-column-width, per-row-height table styling beyond what `style_doc_table_cells` currently exposes _(a-bonus/google-docs-mcp)_
- [ ] Footnote management _(piotr-agier/google-drive-mcp)_

**Calendar**
- [ ] Working location / OOO / Focus time events ([#164](https://github.com/khuisman/mcp-gee-sweet/issues/164))
- [ ] Watch notifications — webhook push on calendar or event changes ([#165](https://github.com/khuisman/mcp-gee-sweet/issues/165))

**Infrastructure**
- [ ] `notifications/progress` feedback for long-running transfer calls (`download_folder`, `sync_folder`) — no tool uses MCP progress reporting today, would establish a new pattern; split from #316 ([#319](https://github.com/khuisman/mcp-gee-sweet/issues/319))

### Decisions Needed — blocking backlog _(no assigned version)_

Design questions raised during Phase 1 QA that need a deliberate product/API decision rather than just code. Each blocks whichever tool it names until resolved — pick these up opportunistically alongside the tool they affect, or dedicate a pass to clear the backlog.

- [ ] `get_sheet_data` on an unknown sheet — exception vs structured error ([#31](https://github.com/khuisman/mcp-gee-sweet/issues/31))
- [ ] `batch_update_cells` empty input — validation error vs silent no-op ([#32](https://github.com/khuisman/mcp-gee-sweet/issues/32))
- [ ] `add_rows` count cap — accept unlimited or enforce a maximum ([#33](https://github.com/khuisman/mcp-gee-sweet/issues/33))
- [ ] `rename_sheet` same-name — skip the API call or always round-trip ([#34](https://github.com/khuisman/mcp-gee-sweet/issues/34))
- [ ] `create_sheet` duplicate title — API error or auto-suffix ([#35](https://github.com/khuisman/mcp-gee-sweet/issues/35))
- [ ] Hide Drive-create tools from the toolset when service account auth is detected ([#36](https://github.com/khuisman/mcp-gee-sweet/issues/36))
- [ ] `list_spreadsheets` with no folder — all accessible or Drive root ([#37](https://github.com/khuisman/mcp-gee-sweet/issues/37))
- [ ] Validate ownership before `share_spreadsheet` / `share_file` ([#38](https://github.com/khuisman/mcp-gee-sweet/issues/38))
- [ ] `search_spreadsheets` empty query — return all or require non-empty input ([#39](https://github.com/khuisman/mcp-gee-sweet/issues/39))
- [ ] `get_file_metadata` size field for Workspace files — normalize or document ([#40](https://github.com/khuisman/mcp-gee-sweet/issues/40))
- [ ] `rows_to_fetch=0` — clamp to 1 or return all rows ([#78](https://github.com/khuisman/mcp-gee-sweet/issues/78))
- [ ] `list_all_events` — how to handle per-calendar failures when querying in parallel (partial results vs fail-fast); also blocked on [#183](https://github.com/khuisman/mcp-gee-sweet/issues/183) landing first so it reuses that pattern instead of its own `ThreadPoolExecutor` ([#194](https://github.com/khuisman/mcp-gee-sweet/issues/194))

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
- [ ] QA gaps targeted for v0.9 — disposition of v0.8.0 SKIP entries, do first since it triages the rest ([#227](https://github.com/khuisman/mcp-gee-sweet/issues/227)); dedicated QA Google account + calendar + pollution root-cause fixes, consolidates #225/#226/#249 ([#304](https://github.com/khuisman/mcp-gee-sweet/issues/304)); second Drive folder + shared drive fixtures, consolidates #44/#48 ([#305](https://github.com/khuisman/mcp-gee-sweet/issues/305)); domain/public sharing coverage ([#49](https://github.com/khuisman/mcp-gee-sweet/issues/49)); local-filesystem coverage ([#50](https://github.com/khuisman/mcp-gee-sweet/issues/50)); environment-constraint coverage, likely closes as duplicate once #227/#48/#49 are disposed — not yet closed, pending #227 ([#53](https://github.com/khuisman/mcp-gee-sweet/issues/53)); split `drive.md`/`docs.md` test files by submodule, do before #264/#224 to avoid a file-rename conflict ([#233](https://github.com/khuisman/mcp-gee-sweet/issues/233)); Playwright tag consistency audit + formalize the required/spot-check/skip tiers, raised while fixing #248, sequenced after #233 ([#264](https://github.com/khuisman/mcp-gee-sweet/issues/264)); image fixtures for `insert_inline_image`, sequenced after #233 ([#224](https://github.com/khuisman/mcp-gee-sweet/issues/224)); dedicated screenshots folder, independent of the rest ([#231](https://github.com/khuisman/mcp-gee-sweet/issues/231))
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
- [a-bonus/google-docs-mcp](https://github.com/a-bonus/google-docs-mcp) — source-verified ~44 Sheets tools / ~39 Docs tools (one-file-per-operation style, exceeds its own README's claimed counts); primary source for the Sheets comments/conditional-formatting/protected-ranges/validation/grouping cluster and the Docs comments/tabs/smart-chips/section-breaks cluster added 2026-07-14
- [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp) — 12-service, source-verified 115-tool server; only project reviewed with a confirmed Markdown *export* tool (`get_doc_as_markdown`, see [#300](https://github.com/khuisman/mcp-gee-sweet/issues/300)) — our Markdown support is currently input-only
