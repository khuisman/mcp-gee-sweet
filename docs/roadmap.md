# Feature Roadmap

Features are grouped by category and ordered by practical priority within each tier. Items marked with a source were identified by auditing competing projects — see [decision-fork.md](decisions/decision-fork.md) for full credits.

## Tier 1 — High value, frequently needed

### Sheet management
- [ ] `delete_sheet` — delete a tab by name or sheetId _(freema/mcp-gsheets)_
- [ ] `delete_rows` / `delete_columns` — remove rows or columns by index range _(freema/mcp-gsheets)_
- [ ] `clear_values` — clear cell content in a range without touching formatting _(freema/mcp-gsheets)_
- [ ] `update_sheet_properties` — set tab color, freeze rows/cols, hide/show gridlines _(freema/mcp-gsheets)_

### Drive file operations
- [x] `move_file` — move a file to a different folder _(piotr-agier/google-drive-mcp)_
- [x] `rename_file` — rename any Drive file _(piotr-agier/google-drive-mcp)_
- [x] `copy_file` — duplicate a file into a folder _(piotr-agier/google-drive-mcp)_
- [x] `delete_file` — move a file to trash _(piotr-agier/google-drive-mcp)_

## Tier 2 — Useful for structured data work

### Cell formatting
- [ ] `format_cells` — set background color, font, alignment, number format on a range _(freema/mcp-gsheets)_
- [ ] `update_borders` — set border style, width, and color on a range _(freema/mcp-gsheets)_
- [ ] `merge_cells` / `unmerge_cells` — merge a range into one cell _(freema/mcp-gsheets)_

### Data validation
- [ ] `add_data_validation` — add a dropdown list, checkbox, or value constraint to a range _(freema/mcp-gsheets)_
- [ ] `get_data_validation` — read existing validation rules from a range _(freema/mcp-gsheets)_

### Row/column sizing and visibility
- [ ] `resize_rows` / `resize_columns` — set pixel height/width, or auto-fit to content _(freema/mcp-gsheets)_
- [ ] `hide_rows` / `hide_columns` / unhide variants — toggle row or column visibility _(freema/mcp-gsheets)_

## Tier 3 — Advanced / occasionally needed

### Conditional formatting
- [ ] `add_conditional_formatting` — add a highlight or color-scale rule to a range _(freema/mcp-gsheets)_
- [ ] `delete_conditional_formatting` — remove a rule by index _(freema/mcp-gsheets)_

### Named and protected ranges
- [ ] `add_named_range` / `delete_named_range` — create or remove a named range _(piotr-agier/google-drive-mcp)_
- [ ] `add_protected_range` — lock a range against edits _(piotr-agier/google-drive-mcp)_

### Permissions
- [x] `list_permissions` — list who has access to a file and their roles _(piotr-agier/google-drive-mcp)_
- [x] `remove_permission` — revoke a specific user's access _(piotr-agier/google-drive-mcp)_
- [x] `update_permission` — change a user's role (e.g. reader → writer) _(piotr-agier/google-drive-mcp)_

### Filters
- [ ] `set_basic_filter` — apply an AutoFilter to a range _(freema/mcp-gsheets)_
- [ ] `clear_basic_filter` — remove the AutoFilter from a sheet _(freema/mcp-gsheets)_

## Tier 4 — Nice to have

- [ ] `get_sheet_dimensions` — read column widths, row heights, and frozen row/col counts _(freema/mcp-gsheets)_
- [ ] `add_note` / `clear_note` — attach or remove a cell note (distinct from a comment) _(freema/mcp-gsheets)_
- [ ] `get_revisions` — list Drive revision history for a file _(piotr-agier/google-drive-mcp)_

## Bugs found in Phase 1 QA run (2026-06-02)

### `add_chart` — multi-column range fails (BUG-1)
**Severity:** High — affects all practical chart use cases.
The tool passes the full data range (e.g. `A1:D5`) as a single `ChartSourceRange`. The Sheets API requires separate source range objects per column — one for the domain (X axis / categories) and one per series. Fix: parse the A1 range, split into domain (first column) and series (remaining columns), pass as separate entries in `sources`.

### `add_chart` HISTOGRAM — wrong API spec (BUG-2)
**Severity:** Medium — HISTOGRAM specifically broken even after BUG-1 fixed.
`HISTOGRAM` is not a valid `BasicChartType` enum value. The Sheets API uses a `histogramChart` spec field rather than `basicChart.chartType`. Fix: detect `chart_type == "HISTOGRAM"` and build a `histogramChart` spec instead.

### TC-W03 — test case assumption wrong
The test expected the API to silently truncate a 2D array that's wider than the target range. The API actually rejects it with a 400 error. The test case needs to be updated to reflect correct API behaviour.

---

## Product decisions needed (from Phase 1 QA run)

These observations were noted during the QA run. Each needs a deliberate decision — see `docs/decisions/` for the ADR process.

- **TC-R04**: `get_sheet_data` with a non-existent sheet surfaces as a tool exception, not a structured `{"error": ...}` field. Inconsistent with other tools that return error objects. Decide: standardise all errors as structured returns, or document the exception pattern?
- **TC-W08**: `batch_update_cells` with an empty ranges dict succeeds silently (no-op). Decide: should empty input be a validation error or an accepted no-op?
- **TC-W16**: `add_rows` with `count=1000` succeeds with no cap. Decide: should the tool cap large counts to prevent accidental bloat, and if so, what limit?
- **TC-S12**: Same-name `rename_sheet` round-trips to the API rather than short-circuiting. Decide: add a client-side guard to skip the API call if names are identical?
- **TC-S16**: `create_sheet` with a duplicate tab title returns an API error — no auto-suffix. Decide: is that the right UX, or should we auto-suffix (e.g. "Sales 2")?
- **TC-D04**: Confirmed: service accounts cannot create files in personal Drive. Decide: should the tool return a clear structured error (already done) or also be omitted from the registered toolset when service account auth is detected?
- **TC-D15**: `list_spreadsheets` with no folder returns all accessible spreadsheets, not Drive root. Decide: is this the right behaviour or should it be scoped to root?
- **TC-D25 / TC-D132**: No ownership validation before sharing — any accessible file ID can be shared. Decide: add a check that the caller owns or has share permission before attempting, or document as-is?
- **TC-D34**: Empty/whitespace `search_spreadsheets` query returns all accessible spreadsheets. Decide: validate non-empty input or keep the wildcard behaviour?
- **TC-D79**: `get_file_metadata` returns `size: "1024"` for Workspace files (Docs, Sheets), not `null`. Decide: normalise to `null` for Workspace files to match Drive API docs, or document the quirk?
- **TC-D84**: `write_doc_content` with `<h2>` input produces `<h3>` in the rendered doc (heading level shift). Decide: fix the heading mapping in `_html_to_doc_requests`, or document as a known limitation?
- **TC-C05/TC-C08**: PIE and HISTOGRAM charts need separate code paths. Decide scope of BUG-1/BUG-2 fix: fix all types together or incrementally?

---

## Testing

- [x] Add `pytest` and `pytest-cov` as dev dependencies
- [x] Unit tests for cache logic — TTL expiry, dirty flag, partial invalidation for all four cache classes; uses in-memory SQLite (`:memory:`)
- [x] Unit tests for A1 notation helpers — `_parse_a1_notation`, `_column_index_to_letter`, `_letter_to_column_index`
- [x] Unit tests for HTML↔Doc conversion (`_html_to_text`, `_html_to_doc_requests`)
- [x] Unit tests for tool filtering — tools excluded when not in `ENABLED_TOOLS`
- [x] Unit tests for service account quota error handling — `create_spreadsheet`, `create_doc`, `copy_file`, `upload_file` return structured error on 403 quota exceeded; non-quota 403s still raise
- [x] Unit tests for `server://auth-status` resource — correct capabilities returned for service_account, oauth, and adc
- [ ] Fix BUG-1: `add_chart` multi-column range — split into per-column source ranges for domain and series
- [ ] Fix BUG-2: `add_chart` HISTOGRAM — implement `histogramChart` spec path
- [ ] Update TC-W03 test case — API rejects oversized 2D arrays, does not silently truncate
- [ ] Formatting integration spike — explore `effectiveFormat` API response shape; determine fixture strategy; assess whether API-level assertions cover formatting without a browser

### Missing QA fixtures (from Phase 1 run)

Tests skipped because a required fixture file, folder, or state didn't exist — not an auth or quota issue.

| TC | What's needed |
|---|---|
| TC-D48 | A second, large-content doc fixture |
| TC-D61 | A disposable file to move (moving the main fixture would break subsequent tests) |
| TC-D62 | A second QA Drive folder |
| TC-D64 | A disposable file to rename |
| TC-D72 | A disposable file to permanently delete |
| TC-D130 | A pre-shared permission on the fixture spreadsheet to remove |
| Calendar (all) | TEST_CALENDAR_ID and TEST_EVENT_ID not configured — a shared calendar and a seed event |

#### Under consideration — may not be worth creating fixtures

| TC | Why it was skipped | Question |
|---|---|---|
| TC-D50 | No empty doc (quota blocked creation at the time) | Should reset_fixtures maintain a second empty doc, or write then clear the existing one? |
| TC-D53 | Parallel execution order uncertainty | Test design issue — no fixture would fix it; needs explicit ordering or isolation |
| TC-D56 | Not attempted | Is very long content worth a dedicated fixture, or generate inline? |
| TC-D121 | No shared drives available | Worth setting up a shared drive for QA, or accept as environment-constrained? |
| TC-D122 | No shared drives available | Same as above |
| TC-D123 | Requires 100+ shared drives | Probably not feasible; mark as permanently skipped? |
| TC-D135/137/138/139 | example.com blocked by Google for sharing without notify | Needs a real test Google account email; assess if worth the setup cost |
| TC-D136 | Not attempted — public access risk | Decide whether to gate behind an explicit flag or skip permanently |

### 91 skipped tests from Phase 1 run

Of the 91 tests skipped in the 2026-06-02 run, the breakdown by root cause is:

| Bucket | Count | Root cause | Path to coverage |
|---|---|---|---|
| OAuth/ADC required | ~22 | Service account quota blocks `create_spreadsheet`, `create_doc`, `copy_file`, `upload_file`, and cascade failures | Re-run with `QA_AUTH_METHOD=oauth` set in `.env` and server started with OAuth credentials |
| Local filesystem | ~27 | `upload_local_file/folder`, `download_file/folder`, `sync_folder` — require file paths accessible to the MCP server process | Needs a non-AI test runner with filesystem access; could use a headless Python script or a dedicated CI job with a temp directory |
| Server restart / reconfig | ~13 | All infra tests (cache TTL, tool filtering, auth variants, transport) — each needs a server restart with different config | Needs a test harness that can start/stop the server between cases; could be a pytest fixture with subprocess control |
| Environment constraints | ~29 | No shared drives, Google blocks example.com addresses without notify, no second test Google account, no concurrent session support in AI runs | Needs a dedicated test Google account, shared Drive setup, or mocked transport layer for the email/sharing tests |

- [ ] **Plan how to cover local-filesystem tests** — investigate whether a pytest-subprocess harness (start `uv run mcp-gee-sweet`, issue HTTP calls, check results) can cover upload/download/sync without manual intervention
- [ ] **Plan how to cover infra restart tests** — same subprocess harness could start the server with different env vars per test; assess whether this is worth the setup cost at current scale
- [ ] **Plan how to cover OAuth-gated tests** — decide whether to maintain a second set of `.env` credentials for OAuth QA, or gate these behind a CI environment variable
- [ ] **Plan how to cover environment-constraint tests** — some (example.com sharing) need a real test Google account with known email; others (shared drives, concurrent sessions) may not be worth the setup cost; document which to invest in vs accept as permanently skipped

## Infrastructure / internal

- [x] Migrate cache persistence — replaced four `/tmp/*.json` files with a single SQLite DB (`/tmp/mcp_gee_sweet.db`, configurable via `CACHE_DB_PATH`); one table, four namespaces; WAL mode
- [ ] PyPI publish — set up trusted publishing (OIDC), create package on PyPI, do a test release; CI workflow already written
- [x] Open PR to xing5 from `upstream-observability` branch (structured logging, per-tool timing, `cache_discovery=False`) — [PR #79](https://github.com/xing5/mcp-google-sheets/pull/79)
- [x] Fork repo and rename to `mcp-gee-sweet`; README credits xing5, freema, and piotr-agier

## Tasks

Requires `tasks/v1` client and `https://www.googleapis.com/auth/tasks` scope. Add `tasks_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan alongside the existing clients.

### Task lists
- [ ] `list_task_lists` — list all task lists for the authenticated user
- [ ] `get_task_list` — fetch metadata for a single task list
- [ ] `create_task_list` — create a new task list
- [ ] `delete_task_list` — delete a task list and all its tasks

### Tasks
- [ ] `list_tasks` — list tasks in a task list with optional due date filter and completed/hidden flags
- [ ] `get_task` — fetch a single task by task list ID + task ID
- [ ] `create_task` — create a task (title, notes, due date, parent for subtasks)
- [ ] `update_task` — update fields on an existing task (`tasks().patch()`)
- [ ] `delete_task` — delete a task
- [ ] `complete_task` — mark a task as completed (shortcut for `update_task` with `status='completed'`)
- [ ] `clear_completed` — delete all completed tasks from a list (`tasks().clear()`)

## Gmail

Requires `gmail/v1` client and `https://www.googleapis.com/auth/gmail.modify` scope (or narrower `gmail.readonly` / `gmail.send` scopes where appropriate). Add `gmail_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan.

### Reading
- [ ] `list_messages` — list messages with optional query string (same syntax as Gmail search), label filter, and pagination
- [ ] `get_message` — fetch a single message by ID; return headers, body (plain text + HTML), and attachment metadata
- [ ] `list_threads` — list conversation threads with optional query and label filter
- [ ] `get_thread` — fetch all messages in a thread
- [ ] `list_labels` — list all labels (system and user-defined)

### Sending and drafts
- [ ] `send_message` — send an email (to, cc, bcc, subject, body, optional attachments)
- [ ] `create_draft` — create a draft without sending
- [ ] `send_draft` — send an existing draft by ID
- [ ] `reply_to_message` — send a reply in an existing thread

### Organization
- [ ] `modify_labels` — add or remove labels from a message or thread (covers archive, mark read/unread, star, etc.)
- [ ] `trash_message` — move a message to trash
- [ ] `delete_message` — permanently delete a message

## Potential / under consideration

- **Google Keep** — philosophically in scope (Workspace productivity tool) but the Keep API v1 is read-only for most operations and was historically restricted to Workspace Business/Enterprise accounts. Creating and editing notes via an officially supported third-party API is not currently possible. Revisit if Google opens the API further.

- **SQLite cache encryption at rest** — the cache DB (`/tmp/mcp_gee_sweet.db`) stores Google Sheets data in plaintext. For deployments that handle sensitive data, consider [SQLCipher](https://www.zetetic.net/sqlcipher/) (open-source, AES-256, mostly API-compatible with standard SQLite) or rely on filesystem-level encryption (FileVault, LUKS, BitLocker). The official SQLite Encryption Extension (SEE) is an alternative but is commercial/proprietary. Not needed for typical local-dev use.

## Inspiration and credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — original upstream this project was forked from
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) — most comprehensive Sheets-specific MCP server; primary source for formatting, validation, and sheet property roadmap items
- [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — full Workspace suite; primary source for Drive file operations, permissions, and named/protected range roadmap items
