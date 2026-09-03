# Running QA

This file contains the conductor prompt. Paste it into a Claude session that has the mcp-gee-sweet MCP server connected. Claude will read your fixtures, execute every test case against the live server, record outcomes, and save a results report.

## Prerequisites

1. mcp-gee-sweet server running and connected to this Claude session
2. `docs/qa/.env` exists and is filled in (see `setup.md` if not)
3. For calendar tests: the calendar in `.env` is accessible to the authenticated account
4. **If using Playwright for visual verification:** Playwright MCP connected and a valid `token.json` present (see `docs/qa/playwright_oauth.md`)

## How to start

Copy everything in the **Conductor prompt** section below and paste it into the Claude chat.

To run a single category instead of the full suite, add after the prompt: "Only run the `tests/drive_files.md` file" (or whichever category you want).

To resume an interrupted run: paste the prompt and add "Resume from `docs/qa/results/<date>-partial.md`".

---

## Playwright verification

Playwright is optional at the run level. Whether a test requires visual verification is a **per-test-case decision**, marked in the test file itself with `**Playwright: required**`. The conductor follows those tags — it does not decide at runtime which tests get visual verification.

### Tiers (authoring reference)

Three tiers replace the earlier "visual whenever visual is possible" guidance (which produced near-zero-signal screenshots on read-only/error-path/count tests — see the v0.8.0 retro's finding #1). Only **Required** corresponds to an actual tag on the test case; **Spot-check** and **Skip** are authoring/runtime guidance, not tags.

| Tier | When to use | Tag the test case? | Examples |
|---|---|---|---|
| **Required** | The check verifies a mutation with a visual signature the API-level response can't fully confirm — formatting, hyperlinks, images, charts, layout, table-cell run formatting, create/delete/move confirmed in UI, cache invalidation checks | Yes — `**Playwright: required**` on the Prompt line | `format_cells`, `freeze`, `merge`, `add_chart`, `delete_file`, `write_doc_content` tables, `create_event`, `style_doc_range` (font size, hyperlinks) |
| **Spot-check** | An API response looks unexpected, or a cache discrepancy is suspected — a runtime judgment call during the run, not a fixed property of the test case | No | Any time the API says success but behavior seems wrong |
| **Skip** | Read-only, error paths, count/pagination, cache-hit-only, unit-tested paths, or a mutation whose visual signature the API response already fully confirms (e.g. plain-paragraph bold/italic runs, checkbox glyphs as literal text, `namedStyleType`, Drive file metadata) | No | `get_sheet_data`, `list_events`, error returns, `create_folder`/`rename_file` (confirmed via `list_files`/`get_file_metadata` instead — see Drive fixture note below), row/column counts |

A test case's Checks list is the source of truth: if every listed check is answerable from the tool's own response (or a follow-up read-only call), it's Skip even if the mutation *sounds* visual. If at least one check can only be answered by looking at the rendered result, it's Required. When in doubt, prefer Required — the cost of an unnecessary screenshot is lower than a silently-unverified regression.

**Drive mutations are Skip by default policy, not by oversight.** Drive's UI mostly just reflects API-returned metadata directly (file name, mimeType, trashed state, parent), so `list_files`/`get_file_metadata` is the confirmation source rather than a screenshot — this is documented per-case in `docs/qa/tests/drive_*.md` Result entries (e.g. TC-D at drive_files.md's `create_shortcut` test, which uses the shortcut mimeType instead of a screenshot). Permission/sharing changes follow the same policy — see "Known limitations" below.

### How it works (authoring reference)

When a test case is tagged `**Playwright: required**`, after the tool call the conductor:

- **Sheets** — navigates to `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit` and snapshots the affected cells
- **Docs** — navigates to `https://docs.google.com/document/d/{DOC_ID}/edit` and snapshots the affected section
- **Drive** — navigates to `https://drive.google.com/drive/folders/{FOLDER_ID}` (or the file's `web_link`) and confirms the change
- **Calendar** — navigates to `https://calendar.google.com` and confirms the event appears or is gone

### Known limitations

- **Footer / header content** — Google Docs renders headers and footers outside the main document canvas. For short documents `window.scrollTo` does not bring the footer into the viewport. When a test involves `create_footer` or `create_header`, use the API response as confirmation; a Playwright snapshot of the body is still useful but will not show the footer content.
- **Permission changes** — sharing confirmations are not visible in the Drive UI without navigating to the file's "Share" dialog. Use `list_permissions` API response as the confirmation source for share tests.
- **Chart-covered grid (Sales sheet)** — repeated `add_chart` test runs leave floating chart objects on the Sales sheet (they're never cleaned up between runs), and as of 2026-07-15 there were ~12 stacked overlapping charts covering roughly rows 1–22. This blocks visual verification of anything in that region — row-height/column-width changes (`resize_rows`/`resize_columns`), cell formatting, etc. are not visible in a screenshot, and Playwright's accessibility snapshot doesn't expose per-cell grid geometry either (only the charts' own accessible text). When a test in that area needs precise confirmation, use `get_sheet_data(..., range=<affected range>, include_grid_data=True)` instead — the raw response includes `rowMetadata`/`columnMetadata` with each row/column's actual `pixelSize`, which is more precise than a screenshot anyway. The same call also works for border verification (`update_borders` QA, TC-S85–S87 on 2026-07-16): each cell's `userEnteredFormat.borders`/`effectiveFormat.borders` reports `top`/`bottom`/`left`/`right` style and color directly, so a border-covering-range test doesn't need the screenshot at all — check the per-cell `borders` dict instead of `rowMetadata`/`columnMetadata`. Longer term, `add_chart` QA test cases should delete the chart they create at the end of each run (see `docs/qa/tests/sheets_charts.md`) so the fixture doesn't accumulate; that cleanup is not yet in place.

### Coordinating Playwright across parallel shards

A single Playwright MCP instance is one browser tab. If a QA run is split across multiple agents (e.g. one per domain), any two shards that both hit `**Playwright: required**` cases at the same time will fight over that tab — one shard's navigation clobbers the snapshot the other was about to take. Spinning up a second authenticated Playwright instance to get true parallelism is possible but costly: the browser profile needs its own logged-in Google session (see `playwright_oauth.md`), so a second instance means cloning that profile rather than just adding a server entry.

Cheaper fix: a filesystem mutex around Playwright usage, since only one shard needs the tab at a time and each hold is brief (one navigate + snapshot, not the whole run).

- **Lock path:** `/tmp/mcp-gee-sweet-playwright.lock` (a directory, not a file — `mkdir` is atomic on POSIX, so no separate locking library is needed).
- **Acquire:** before a Playwright tool call, attempt `mkdir /tmp/mcp-gee-sweet-playwright.lock`. Success means the lock is held — proceed. Failure (already exists) means another shard holds it — back off (a few seconds) and retry.
- **Release:** immediately after the snapshot for that one test case, `rmdir /tmp/mcp-gee-sweet-playwright.lock`. Don't hold the lock across an entire test file — only around the actual Playwright step.
- **Stale-lock recovery:** if the lock directory's mtime is older than ~120s, treat it as abandoned (the shard that created it likely crashed or was killed) — remove it and re-acquire rather than waiting forever.
- **When it's not needed:** a single-shard full run (no parallel agents) never contends with itself — skip the lock entirely in that case.

Give each parallel shard's conductor prompt this protocol explicitly (path, acquire/release commands, backoff, staleness threshold) rather than assuming priority ordering or hoping timing works out.

---

## Drive fixture-folder pollution

`TEST_FOLDER_ID` accumulates stray items across many creation/copy test categories that don't tear down after themselves (tracked in [#304](https://github.com/khuisman/mcp-gee-sweet/issues/304) — dedicated QA account/cleanup sweep). As of 2026-07-17 it held ~15 duplicate leftovers (`Copy of mcp-gee-sweet-qa-fixtures` ×2, `QA-Cache-Check` ×2, `QA-Copy-Explicit`, `QA-Create-Explicit`, `QA-Doc-Copy`, `QA-DocCache`, `QA-HTML-Doc` ×2, `QA-Markdown-Doc` ×2, `QA-Table-Doc` ×2, loose `qa-notes.md`/`qa-upload.txt`, two leftover folders).

This matters for any test that syncs, lists, or downloads the whole folder (`sync_folder`, `download_folder`, `list_files` against `TEST_FOLDER_ID` directly) — the pollution items show up in results alongside whatever the test actually cares about, and a `recursive`/whole-folder operation will process all of it. Until #304 lands: for a test that needs a clean or isolated Drive tree (rather than "does this tool correctly handle files that happen to be in `TEST_FOLDER_ID`"), create a throwaway child folder under `TEST_FOLDER_ID` for that test's own fixtures instead of working at the shared top level, and delete it in teardown. Same tool behavior either way — this only reduces noise and avoids accidentally sweeping up items you don't own.

---

## Clearing sheet-level state with no direct tool (e.g. data validation)

Some sheet-level state has a tool to *set* it but none to *clear* it, and no tool exposes a sheet's numeric `sheetId` by name to fall back to the raw `batch_update` escape hatch (`list_sheets` returns names only; the `spreadsheet://{id}/info` resource that's supposed to cover this was broken until [#363](https://github.com/khuisman/mcp-gee-sweet/issues/363) fixed it — reading it now works, but it's still no substitute for a tool that returns `sheetId` by name, tracked as a product gap in [#365](https://github.com/khuisman/mcp-gee-sweet/issues/365)). Hit live testing `add_data_validation`/`get_data_validation` (PR #361, 2026-07-18): no way to clear a validation rule from the fixture's `Empty` sheet between test cases.

Workaround for a *scratch* fixture sheet (never do this to a sheet with real data — it destroys everything on the tab, not just the state you're trying to clear): `delete_sheet(sheet="Empty")` then `create_sheet(title="Empty")`. Fully resets the tab to blank, including any validation/formatting/merges, and is safe here because every QA tool call references the sheet by name, never by the ID that changes on recreate.

---

## Missing `docs/qa/.env` in a role worktree

`docs/qa/.env` is gitignored, so it doesn't exist by default in a freshly-provisioned `.claude/worktrees/<name>` slot — confirmed empty/absent across every role worktree and the main checkout, 2026-07-19, while doing a scoped QA pass from Kit's own role process (`.claude/team-roles/qa.md` step 4), not the full conductor-prompt flow this file otherwise documents. That flow's own fixture-check step (below) would just stop and ask the user to run `setup.md`, but a scoped single-PR QA pass doesn't need the whole `.env` — only the one fixture ID relevant to the PR under review.

Workaround: the fixture files have fixed, documented names (`setup.md`'s seed prompt: "Rename the doc to `mcp-gee-sweet-qa-fixtures-doc`" / "Rename the spreadsheet to `mcp-gee-sweet-qa-fixtures`"). Find the ID directly instead of blocking: `search_files(query="mcp-gee-sweet-qa-fixtures-doc", mime_type="application/vnd.google-apps.document")` (swap the doc mime type/name for the spreadsheet as needed). Only reach for this fallback in a scoped pass that needs one or two fixture IDs — a full multi-category run still needs the real `.env` for `TEST_FOLDER_ID`/`TEST_CALENDAR_ID`/etc., which don't have as fixed a name to search by.

---

## Conductor prompt

```
You are the QA conductor for mcp-gee-sweet. Your job is to execute the full test suite against the live MCP server, record outcomes, and save a results report.

You have the mcp-gee-sweet MCP connected. Before starting, check whether Playwright MCP is also connected. If it is not, tell me: "Playwright MCP is not connected — tests marked **Playwright: required** will run without visual verification. Confirm to proceed, or connect Playwright first and restart." Wait for my confirmation before continuing.

## Step 0 — Fixture setup

Before running any tests:

1. Record the start time (current timestamp).
2. Read `.env` from the repo root. If the file does not exist or the TEST_* keys are missing, stop and say: ".env not found or TEST_* keys missing — follow docs/qa/setup.md to create your fixtures first."
3. Extract TEST_SPREADSHEET_ID, TEST_DOC_ID, TEST_FOLDER_ID, TEST_CALENDAR_ID, TEST_EVENT_ID, TEST_LARGE_DOC_ID, TEST_PERMISSION_EMAIL, SHARED_DRIVE_ID.
4. Verify the fixture spreadsheet with get_sheet_data: confirm sheet tabs Sales, Empty, Notes & Misc exist and Sales data has 6 rows (header + Widget/Gadget/Donut/Gizmo/Totals), columns A–D. If data is missing or in wrong order, use update_cells to restore known seed state (see docs/qa/setup.md §Known fixture state).
5. Verify the fixture doc with get_doc_structure: confirm title "mcp-gee-sweet-qa-fixtures-doc" and body contains heading "Test Document", a paragraph, and a bullet list (Item one / Item two). If content is wrong, use write_doc_content to restore it.
6. Tell me the fixture IDs, start time, and whether the fixture state looks correct, then wait for me to confirm before proceeding.

## Step 1 — Run tests

Work through the test files in this order:
1. `docs/qa/tests/infra.md`
2. `docs/qa/tests/sheets_read.md`
3. `docs/qa/tests/sheets_write.md`
4. `docs/qa/tests/sheets_mgmt.md`
5. `docs/qa/tests/sheets_charts.md`
6. `docs/qa/tests/drive_files.md`
7. `docs/qa/tests/drive_sharing.md`
8. `docs/qa/tests/drive_transfer.md`
9. `docs/qa/tests/drive_activity.md`
10. `docs/qa/tests/docs_content.md`
11. `docs/qa/tests/docs_tables.md`
12. `docs/qa/tests/docs_style.md`
13. `docs/qa/tests/docs_layout.md`
14. `docs/qa/tests/calendar.md`

For each test case:

1. Announce the TC number and title.
2. Substitute fixture IDs into the prompt (replace {SPREADSHEET_ID}, {DOC_ID}, etc. with the values from `.env`).
3. Execute the prompt using the mcp-gee-sweet tools available in this session.
4. If the test case is marked **Playwright: required** and Playwright MCP is connected: navigate to the affected resource and take a snapshot before recording the outcome. Also save a screenshot via `browser_take_screenshot`, with `filename` set to `docs/qa/screenshots/<YYYY-MM-DD>-<tc-id>.png` (today's date, lowercase TC number — e.g. `tc-doc12.png`). The date prefix keeps each run's screenshots separate without overwriting a prior run's evidence, and avoids depending on a subfolder that `browser_take_screenshot` won't auto-create.
5. Evaluate each item in the **Checks** list against the actual result.
6. Record one of:
   - **PASS** — every check met
   - **FAIL** — one or more checks failed; note exactly what was wrong
   - **SKIP** — with reason (e.g. "requires server restart", "skipped by user", "prerequisite TC failed")
7. For tests marked ⚠️ destructive: ask me before running. If I say skip, record SKIP(destructive-skipped).
8. For tests marked 🔍 product decision: always record PASS and note the observed behavior.
9. Track intermediate IDs as you go — some tests produce IDs (permissionId, eventId, fileId) needed by later tests. Record them in your working notes and substitute them when referenced.

## Step 2 — Save progress

After completing each test file, write current results to `docs/qa/results/<YYYY-MM-DD>.md` (use today's date). If a file already exists for today, overwrite it with the fully updated version.

If I say "pause" or "stop" at any point, save immediately to `docs/qa/results/<YYYY-MM-DD>-partial.md` before stopping.

## Step 3 — Final report

After all test files are complete, record the end time and write the final report to `docs/qa/results/<YYYY-MM-DD>.md` using this format:

---
# QA Run — <YYYY-MM-DD>

**Auth:** OAuth  
**Fixtures:** SPREADSHEET_ID=`<id>` · DOC_ID=`<id>` · FOLDER_ID=`<id>`  
**Start:** <timestamp> · **End:** <timestamp> · **Duration:** <HH:MM>

## Summary

| Category | PASS | FAIL | SKIP | Total |
|---|---|---|---|---|
| Infrastructure | | | | |
| Sheets Read | | | | |
| Sheets Write | | | | |
| Sheets Mgmt | | | | |
| Sheets Charts | | | | |
| Drive + Docs | | | | |
| Docs Tools | | | | |
| Calendar | | | | |
| **Total** | | | | |

## Failures

For each FAIL, one entry:
**TC-XXX — <title>**
Expected: <what the check said>
Observed: <what actually happened>
Playwright: <what the browser showed, if applicable>

*(none)* if all tests passed.

## Tool coverage

For every tool registered by the server, list which TCs exercise it and whether those TCs passed. Derive this by scanning the test files you ran.

| Tool | TC(s) | Status |
|---|---|---|
| get_sheet_data | TC-R01, TC-R02, … | ✅ all pass |
| create_spreadsheet | TC-D01 | ✅ pass |
| create_calendar | (none) | ⚠️ no coverage |
| … | | |

Use ✅ if all covering TCs passed, ❌ if any failed, ⚠️ no coverage if no TC exercises the tool, and SKIP if all covering TCs were skipped.

## Full results

| TC | Title | Outcome | Notes |
|---|---|---|---|
| TC-I01 | ... | PASS | |
| ... | | | |
---

If any test case this run was marked **Playwright: required**, tell me: "Screenshots saved to `docs/qa/screenshots/` (prefixed `<YYYY-MM-DD>-`) — delete when no longer needed."

## Resuming an interrupted run

If resuming: read the partial results file I specify, identify the last completed TC, and continue from the next one. Re-confirm fixture IDs from `.env` and re-verify fixture state before continuing.
```

---

## Results location

Reports are saved to `docs/qa/results/`. Files named `YYYY-MM-DD.md` are completed runs; files named `YYYY-MM-DD-partial.md` are interrupted runs.
