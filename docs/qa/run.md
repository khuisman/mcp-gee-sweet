# Running QA

This file contains the conductor prompt. Paste it into a Claude session that has the mcp-gee-sweet MCP server connected. Claude will read your fixtures, execute every test case against the live server, evaluate the checks, and save a results report.

## Prerequisites

1. mcp-gee-sweet server running and connected to this Claude session
2. `docs/qa/`.env`` exists and is filled in (see `setup.md` if not)
3. For calendar tests: the service account has been subscribed to the calendar in ``.env``

## How to start

Copy everything in the **Conductor prompt** section below and paste it into the Claude chat.

To run a single category instead of the full suite, add after the prompt: "Only run the `tests/drive.md` file" (or whichever category you want).

To resume an interrupted run: paste the prompt and add "Resume from `docs/qa/results/<date>-partial.md`".

---

## Conductor prompt

```
You are the QA conductor for mcp-gee-sweet. Your job is to execute the full test suite against the live MCP server, record outcomes, and save a results report.

## Step 1 — Load fixtures

Read `.env` from the repo root. If the file does not exist or the TEST_* keys are missing, stop immediately and say: ".env not found or TEST_* keys missing — follow docs/qa/setup.md to create your fixtures first."

Extract TEST_SPREADSHEET_ID, TEST_DOC_ID, TEST_FOLDER_ID, TEST_CALENDAR_ID, TEST_EVENT_ID. Tell me the values you found, then wait for me to confirm before proceeding.

## Step 2 — Run tests

Work through the test files in this order:
1. `docs/qa/tests/infra.md`
2. `docs/qa/tests/read.md`
3. `docs/qa/tests/write.md`
4. `docs/qa/tests/sheets.md`
5. `docs/qa/tests/drive.md`
6. `docs/qa/tests/charts.md`
7. `docs/qa/tests/calendar.md`

For each test case:

1. Announce the TC number and title.
2. Substitute fixture IDs into the prompt (replace {SPREADSHEET_ID}, {DOC_ID}, etc. with the values from `.env`).
3. Execute the prompt using the MCP tools available in this session.
4. Evaluate each item in the **Checks** list against the actual result.
5. Record one of:
   - **PASS** — every check met
   - **FAIL** — one or more checks failed; note exactly what was wrong
   - **SKIP** — with reason (e.g. "requires server restart", "skipped by user", "prerequisite TC failed")
6. For tests marked ⚠️ destructive: ask me before running. If I say skip, record SKIP(destructive-skipped).
7. For tests marked 🔍 product decision: always record PASS and note the observed behavior.
8. Track intermediate IDs as you go — some tests produce IDs (permissionId, eventId, fileId) needed by later tests. Record them in your working notes and substitute them when referenced.

## Step 3 — Save progress

After completing each test file, write current results to `docs/qa/results/<YYYY-MM-DD>.md` (use today's date). If a file already exists for today, overwrite it with the fully updated version.

If I say "pause" or "stop" at any point, save immediately to `docs/qa/results/<YYYY-MM-DD>-partial.md` before stopping.

## Step 4 — Final report

After all test files are complete, write the final report to `docs/qa/results/<YYYY-MM-DD>.md` using this format:

---
# QA Run — <YYYY-MM-DD>

**Fixtures:** SPREADSHEET_ID=`<id>` · DOC_ID=`<id>` · FOLDER_ID=`<id>`

## Summary

| Category | PASS | FAIL | SKIP | Total |
|---|---|---|---|---|
| Infrastructure | | | | |
| Read | | | | |
| Write | | | | |
| Sheets | | | | |
| Drive | | | | |
| Charts | | | | |
| Calendar | | | | |
| **Total** | | | | |

## Failures

For each FAIL, one entry:
**TC-XXX — <title>**
Expected: <what the check said>
Observed: <what actually happened>

*(none)* if all tests passed.

## Full results

| TC | Title | Outcome | Notes |
|---|---|---|---|
| TC-I01 | ... | PASS | |
| ... | | | |
---

## Resuming an interrupted run

If resuming: read the partial results file I specify, identify the last completed TC, and continue from the next one. Re-confirm fixture IDs from `.env` before continuing.
```

---

## Results location

Reports are saved to `docs/qa/results/`. Files named `YYYY-MM-DD.md` are completed runs; files named `YYYY-MM-DD-partial.md` are interrupted runs.
