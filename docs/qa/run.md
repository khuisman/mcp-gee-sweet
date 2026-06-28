# Running QA

This file contains the conductor prompt. Paste it into a Claude session that has **both the mcp-gee-sweet MCP server and the Playwright MCP connected**. Claude will read your fixtures, execute every test case against the live server, visually verify results in the browser via Playwright, and save a results report.

## Prerequisites

1. mcp-gee-sweet server running and connected to this Claude session
2. Playwright MCP connected to this Claude session (used for visual verification)
3. `docs/qa/.env` exists and is filled in (see `setup.md` if not)
4. A valid `token.json` present (OAuth auth, so Playwright can open Google pages as your account — see `docs/qa/playwright_oauth.md`)
5. For calendar tests: the calendar in `.env` is accessible to the authenticated account

## How Playwright verification works

After each MCP tool call, the conductor navigates to the affected resource in Playwright and visually confirms the change appears in the Google UI:

- **Sheets tests** — open the spreadsheet URL, snapshot the relevant cells
- **Docs tests** — open the doc URL, snapshot the affected section
- **Drive tests** — open Drive or the folder URL, confirm files/folders appear
- **Calendar tests** — open Google Calendar, confirm events appear or are gone

This catches discrepancies between what the API reports and what is actually stored — a response of `{"updatedCells": 4}` is not the same as seeing the cells updated in the browser.

For **read-only tests** (checks that the API returns the right data), Playwright verification is optional — the API response is the ground truth. Use Playwright for a spot-check on read tests if something looks suspicious.

For **write/mutation tests** (create, update, delete, format, share, etc.), Playwright verification is **required** before recording PASS.

## How to start

Copy everything in the **Conductor prompt** section below and paste it into the Claude chat.

To run a single category instead of the full suite, add after the prompt: "Only run the `tests/drive.md` file" (or whichever category you want).

To resume an interrupted run: paste the prompt and add "Resume from `docs/qa/results/<date>-partial.md`".

---

## Conductor prompt

```
You are the QA conductor for mcp-gee-sweet. Your job is to execute the full test suite against the live MCP server, visually verify results in the browser via the Playwright MCP, record outcomes, and save a results report.

You have two MCPs connected:
- mcp-gee-sweet (the server under test — use its tools to call the Google APIs)
- Playwright (use browser_navigate + browser_snapshot to visually verify results in Google Sheets / Docs / Drive / Calendar)

## Step 0 — Fixture setup

Before running any tests, verify fixture state:

1. Read `.env` from the repo root. If the file does not exist or the TEST_* keys are missing, stop and say: ".env not found or TEST_* keys missing — follow docs/qa/setup.md to create your fixtures first."
2. Extract TEST_SPREADSHEET_ID, TEST_DOC_ID, TEST_FOLDER_ID, TEST_CALENDAR_ID, TEST_EVENT_ID, TEST_LARGE_DOC_ID, TEST_PERMISSION_EMAIL.
3. Open the fixture spreadsheet in Playwright: navigate to https://docs.google.com/spreadsheets/d/{TEST_SPREADSHEET_ID}/edit and take a snapshot. Confirm:
   - Sheet tabs: Sales, Empty, Notes & Misc
   - Sales data: 6 rows (header + Widget/Gadget/Donut/Gizmo/Totals), columns A–D
   - If data is missing or in wrong order, use update_cells to restore known seed state (see docs/qa/setup.md §Known fixture state)
4. Open the fixture doc in Playwright: navigate to https://docs.google.com/document/d/{TEST_DOC_ID}/edit and confirm:
   - Title: "mcp-gee-sweet-qa-fixtures-doc"
   - Body: heading "Test Document", paragraph, bullet list (Item one / Item two)
   - If content is wrong, use write_doc_content to restore it
5. Tell me the fixture IDs and whether the visual state looks correct, then wait for me to confirm before proceeding.

## Step 1 — Run tests

Work through the test files in this order:
1. `docs/qa/tests/infra.md`
2. `docs/qa/tests/sheets_read.md`
3. `docs/qa/tests/sheets_write.md`
4. `docs/qa/tests/sheets_mgmt.md`
5. `docs/qa/tests/sheets_charts.md`
6. `docs/qa/tests/drive.md`
7. `docs/qa/tests/docs.md`
8. `docs/qa/tests/calendar.md`

For each test case:

1. Announce the TC number and title.
2. Substitute fixture IDs into the prompt (replace {SPREADSHEET_ID}, {DOC_ID}, etc. with the values from `.env`).
3. Execute the prompt using the mcp-gee-sweet tools available in this session.
4. **For write/mutation tests:** navigate to the affected resource in Playwright and take a snapshot to visually confirm the change appears in the Google UI. Include what you saw in your notes.
5. Evaluate each item in the **Checks** list against the actual result (API response + Playwright snapshot where applicable).
6. Record one of:
   - **PASS** — every check met (including Playwright visual confirmation for mutations)
   - **FAIL** — one or more checks failed; note exactly what was wrong and include what Playwright showed
   - **SKIP** — with reason (e.g. "requires server restart", "skipped by user", "prerequisite TC failed")
7. For tests marked ⚠️ destructive: ask me before running. If I say skip, record SKIP(destructive-skipped).
8. For tests marked 🔍 product decision: always record PASS and note the observed behavior.
9. Track intermediate IDs as you go — some tests produce IDs (permissionId, eventId, fileId) needed by later tests. Record them in your working notes and substitute them when referenced.

## Step 2 — Save progress

After completing each test file, write current results to `docs/qa/results/<YYYY-MM-DD>.md` (use today's date). If a file already exists for today, overwrite it with the fully updated version.

If I say "pause" or "stop" at any point, save immediately to `docs/qa/results/<YYYY-MM-DD>-partial.md` before stopping.

## Step 3 — Final report

After all test files are complete, write the final report to `docs/qa/results/<YYYY-MM-DD>.md` using this format:

---
# QA Run — <YYYY-MM-DD>

**Auth:** OAuth  
**Fixtures:** SPREADSHEET_ID=`<id>` · DOC_ID=`<id>` · FOLDER_ID=`<id>`

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
Playwright: <what the browser showed>

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

## Resuming an interrupted run

If resuming: read the partial results file I specify, identify the last completed TC, and continue from the next one. Re-confirm fixture IDs from `.env` and re-verify fixture visual state in Playwright before continuing.
```

---

## Results location

Reports are saved to `docs/qa/results/`. Files named `YYYY-MM-DD.md` are completed runs; files named `YYYY-MM-DD-partial.md` are interrupted runs.
