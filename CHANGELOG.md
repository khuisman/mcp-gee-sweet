# Changelog

All notable changes to this project are documented in this file.

---

## [Unreleased]

### New tools

- Gmail drafts can now be reviewed, edited, and discarded before sending: `list_drafts` (query and pagination; each draft's recipients, subject, and snippet), `get_draft` (same shape as `get_message`), `update_draft` (replaces the content and keeps the draft ID, the thread of a reply draft, and its send-as From; `keep_attachments=True` keeps the existing attachments), and `delete_draft`. None of them sends mail; `send_draft` is still the only way a draft goes out — #1205

### Changed

- **Behavior change: Gmail no longer sends on the agent's call alone.** With the new default `GMAIL_SEND=confirm`, `send_message` and `reply_to_message` save the email as a draft (a reply in its thread) and send it only after the user confirms it in a form the MCP client shows; `send_draft` asks the same way. Declining, cancelling, no answer, or a client that can't show the form leaves the draft unsent and returns `sent: false` with its `draft_id`. Confirmation needs a client on the 2025-11-25 handshake with form elicitation; on 2026-07-28 connections mail stays a draft. The confirmation and the result flag recipients outside a Workspace organization, more than `GMAIL_SEND_WARN_RECIPIENTS` (default 10) recipients, and any Bcc. A client hook that auto-accepts elicitations makes this the same as `direct`. Set `GMAIL_SEND=direct` for the old immediate delivery. Every send result now has a `sent` field — #1081
- **Claude Code users: sends are held as drafts.** Claude Code currently connects on MCP 2026-07-28, where the server can't ask for confirmation, so under the new default every `send_message` and `reply_to_message` from Claude Code returns `sent: false` with the email saved in Gmail's Drafts folder, and `send_draft` refuses. Send from Drafts, or set `GMAIL_SEND=direct` to keep sending at once. Confirmation on 2026-07-28 connections is tracked in #1235 — #1081

---

## [0.9.5] — 2026-10-24

Security hotfix on top of v0.9.4. No new tools.

### Security

- Requires `certifi>=2026.10.19`. Older certifi bundles still trust the eight eMudhra/emSign intermediate CAs, whose weak EC keys let a TLS chain through them be forged ([PSF notice](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)). certifi backs the TLS connection on every Google API call. v0.9.4's lock pinned certifi `2026.5.20`, and no earlier version set a minimum, so `pip install -U mcp-gee-sweet` kept whatever certifi an environment already had — #1217

**What you need to do yourself.** A library can't upgrade your tooling for you:

- Upgrade pip to 26.2.2 or later, and uv to 0.13.4 or later. Both shipped fixes for the same incident.
- Rebuild any Docker image without the cache (`docker build --no-cache ...`), so a cached layer doesn't keep the old certifi.

---

## [0.8.1] — 2026-07-05

Defects and documentation cleanup. No new tools.

### Bug fixes

- `get_sheet_data`: `include_grid_data=True` without a range now auto-detects the actual used range and enforces a response-size safety cap, instead of fetching/returning the sheet's full padded grid — #235
- Response-size safety net generalized to `export_file`, `get_doc_content`, `get_multiple_sheet_data`, `find_in_spreadsheet`, and `list_file_activity` — #242
- `create_doc_from_file`: `\$` markdown escape now renders as a literal `$` instead of passing through untouched — #213
- Unrecognized tool keyword arguments now raise a validation error instead of being silently dropped — #239
- Cache: graceful recovery from read-only or corrupted DB files instead of failing to start — #212
- `get_multiple_spreadsheet_summary`: `rows_to_fetch=0` now consistently returns no data rows regardless of prior cache state (previously returned different results on a cold vs. warm cache) — #254
- `write_doc_content`: fixed a bug where an explicit font size/family override left on a document's trailing paragraph mark by prior content (e.g. a table or fenced code block) could leak into newly-written plain-paragraph content — #255

### Documentation

- `docs/tools.md` and the tool-filtering section of `docs/configuration.md` are now regenerated from tool docstrings via a pre-commit hook (`scripts/gen_tool_docs.py`) — #94
- `CONTRIBUTING.md` rewritten for the full contributor experience: PR scope rules, best-effort review turnaround, Code of Conduct, and the current label table — #95, #237
- Fixed tool-count drift, known-limitations entries, and auth-method ordering across the docs; removed stale `TODO.md` — #236
- Release gate scoping policy: a stable release can substitute Smoke + targeted Domain QA runs for Full Regression when a source-diff audit shows the change is narrow — see `docs/decisions/decision-testing.md`

### QA

- Scoped release gate: 148 PASS / 2 FAIL / 16 SKIP across 166 test cases. Both FAILs were real bugs found during this pass (`rows_to_fetch=0` cache-clamp inconsistency, `write_doc_content` font contamination) — fixed and re-verified live before release, not deferred. See `docs/qa/runs/v0.8.1.md`.

---

## [0.8.0] — 2026-06-29

### New tools

**Google Sheets**
- `delete_sheet` — remove a sheet tab from a spreadsheet
- `delete_rows` / `delete_columns` — remove rows or columns by index
- `clear_values` — erase cell values while preserving formatting
- `format_cells` — apply number formats, alignment, and text styles
- `merge_cells` / `unmerge_cells` — merge or split cell ranges
- `freeze` — freeze rows and/or columns
- `sort_range` — sort a range by one or more columns

**Google Drive**
- `list_shared_with_me` — list files shared with the authenticated user
- `list_recent_files` — list recently modified files, optionally filtered by type and recency window
- `get_storage_quota` — return Drive storage usage and limit
- `list_file_activity` — fetch file activity history via the Drive Activity API v2

**Google Docs**
- `insert_inline_image` — insert an image into a document at a specified location
- `insert_table_row` / `delete_table_row` — add or remove rows in a Docs table
- `insert_table_column` / `delete_table_column` — add or remove columns in a Docs table
- `create_header` / `create_footer` — add a header or footer section to a document

**Google Calendar**
- RRULE recurrence rules for `create_event` and `update_event` — supports weekly, daily, monthly, and custom patterns
- `expand_recurring` parameter on `list_events` — expand recurring events into individual instances (default) or return the master event

### New features

- `.env` file support — `src/mcp_gee_sweet/.env` is loaded at startup; template at `.env.template`
- Structured access logging — `DEBUG_LEVEL`, `LOG_FILE`, and `ACCESS_LOG_FILE` env vars write per-request timing logs in `"IP" "UA" "TOOL name" status elapsed` format

### Bug fixes

- `list_folders`: trashed folders now excluded from results (`trashed=false` filter added to Drive query) — #216
- `get_file_metadata`: `size` field suppressed for Google Workspace files (Docs, Sheets, Slides etc.) which do not consume storage quota — #217
- `list_events`: `time_min` now defaults to the current UTC time when omitted, so only upcoming events are returned by default — #218
- Docs: blank paragraph before a table no longer adds extra height — #190
- Docs: inherited heading `fontSize` cleared when filling table cells to prevent style bleed — #189
- Docs: `headerId` / `footerId` retrieval made robust against missing segment metadata — #145–#147
- Security: bumped `pydantic-settings` to 2.7.1+ (CVE symlink traversal fix)

### Infrastructure

- MCP SDK floor pin raised to `>=1.27.0`
- GitHub security scaffolding: `SECURITY.md`, `CONTRIBUTING.md`, branch protection, Dependabot
- `known-limitations.md` added to docs
- Full QA regression suite (383 PASS / 8 FAIL / 44 SKIP on 2026-06-28; all 8 failures resolved or filed)

---

## [0.7.0] — 2026-06-02

Initial stable release. See README for the full tool list.
