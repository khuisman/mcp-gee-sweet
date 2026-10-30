# Changelog

All notable changes to this project are documented in this file.

---

## [Unreleased]

### New tools

- Gmail drafts can now be reviewed, edited, and discarded before sending: `list_drafts` (query and pagination; each draft's recipients, subject, and snippet), `get_draft` (same shape as `get_message`), `update_draft` (replaces the content and keeps the draft ID, the thread of a reply draft, and its send-as From; `keep_attachments=True` keeps the existing attachments), and `delete_draft`. None of them sends mail; `send_draft` is still the only way a draft goes out — #1205

### New features

- Each GitHub Release now carries an MCP Bundle, `mcp-gee-sweet-<version>.mcpb`, which installs the server in Claude Desktop in one click: the install dialog asks for the OAuth client file, and nothing goes into `claude_desktop_config.json` by hand. The bundle uses OAuth only and keeps its token at `~/.mcp-gee-sweet-token.json`. See [Install as a bundle](docs/client-setup.md#install-as-a-bundle) — #1036

### Changed

- **Behavior change: Gmail no longer sends on the agent's call alone.** With the new default `GMAIL_SEND=confirm`, `send_message` and `reply_to_message` save the email as a draft (a reply in its thread) and send it only after the user confirms it in a form the MCP client shows; `send_draft` asks the same way. Declining, cancelling, no answer, or a client that can't show the form leaves the draft unsent and returns `sent: false` with its `draft_id`. Confirmation needs a client on the 2025-11-25 handshake with form elicitation; on 2026-07-28 connections mail stays a draft. The confirmation and the result flag recipients outside a Workspace organization, more than `GMAIL_SEND_WARN_RECIPIENTS` (default 10) recipients, and any Bcc. A client hook that auto-accepts elicitations makes this the same as `direct`. Set `GMAIL_SEND=direct` for the old immediate delivery. Every send result now has a `sent` field — #1081
- **Claude Code users: sends are held as drafts.** Claude Code currently connects on MCP 2026-07-28, where the server can't ask for confirmation, so under the new default every `send_message` and `reply_to_message` from Claude Code returns `sent: false` with the email saved in Gmail's Drafts folder, and `send_draft` refuses. Send from Drafts, or set `GMAIL_SEND=direct` to keep sending at once. Confirmation on 2026-07-28 connections is tracked in #1235 — #1081
- Markdown input (`create_doc`/`write_doc_content` with `content_format='markdown'`, `create_doc_from_file`, `update_doc_from_file`) is now parsed as CommonMark plus GitHub-flavored Markdown (markdown-it-py), the dialect models and most tools write, instead of Python-Markdown. Markdown that renders differently — #1116:
  - A list, task list, quote, table or code block written directly under a paragraph, list item or quote line, with no blank line, now starts its own block instead of being joined to the text above. A pipe table under a list item or quote line also starts its own block (plan rule D2).
  - Sub-lists nest at 2 or 3 spaces of indent, under bullets and numbered items alike, and numbering continues after them (plan rule D1) — #1071.
  - A paragraph, code block or quote indented under a list item belongs to that item. A fenced code block inside a list item renders as code instead of literal text.
  - `~~text~~` is struck through. `1)` starts a numbered list. `\` at the end of a line is a line break. A backslash before any ASCII punctuation character escapes it.
  - `www.example.com` and `me@example.com` are linked, like bare `https://` URLs already were (`autolink_urls=False` turns all three off). `README.md`, `file.py` and `ftp://` URLs are not. A bare URL is now linked only where GitHub links one: at the start of a line or after a space, `*`, `_`, `~` or `(`. So `URL:https://example.com`, `<b>https://example.com</b>` and a URL right after a code span or link stay plain text, where they used to be linked; put a space before the URL, or write `<https://example.com>`.
  - Bold inside italic (`*a **b** c*`) keeps both styles. `#hashtag` and `####### seven` stay paragraphs instead of becoming headings.
  - A link or image whose path contains spaces (`![shot](./Screen Shot.png)`, `[notes](./My Notes.md "Notes")`) still works, as it did before, although CommonMark itself would leave it as text.
  - Two quotes separated by a blank line render as two quotes.
  - A line of only `-` is an empty list item instead of a setext heading underline or literal text. The empty item itself is still dropped (#1075).
  - YAML front matter (`---` … `---` at the top) now renders as a rule and then a Heading 2 of its text, where it used to render as a rule, a paragraph and a rule. It's still shown either way (#1173).
  - A list with a blank line between items, or with a paragraph or code block indented under an item, stays one list with every bullet and number, where Python-Markdown dropped some of those items out of the list (#1111, fixed by #1164). On screen, Docs still restarts the numbering after a block inside a numbered item, as it did before (#1094).
  - A line of `---` (or `===`) right under a list item's text makes that text a heading inside the item, as CommonMark reads a setext underline: `- a` then `  ---` is a Heading 2 "a", not an item followed by a rule. Write the rule as `***` to keep the item and the rule.

### Bug fixes

- A numbered list keeps its numbering after a bulleted list nested in one of its items (`1. A`, `   - a`, `2. B` shows 2, not 1), at every level; a sublist nested in one of the other type used to split the outer list into separate lists. A sublist that follows another sublist of a different type under the same item starts its own numbering. Two adjacent lists of the same type still merge into one (`1.` then `1)` markers, #1241). Applies to `create_doc`, `write_doc_content`, `create_doc_from_file` and `update_doc_from_file` — #1072

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
