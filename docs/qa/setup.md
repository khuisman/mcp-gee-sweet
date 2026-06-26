# Fixture Setup

## Overview

QA fixtures are a spreadsheet and a doc that all test cases reference. Their IDs live in `.env` (gitignored) alongside your other server config.

Setup has two steps: create the files in Drive, then run the seed prompt to populate them.

---

## Step 1 — Create the files in Drive

How you create the fixture files depends on your auth method.

### OAuth / Application Default Credentials

The AI can create the folder structure for you. In a Claude session with the MCP server connected, run the `setup_fixtures` operation (see `operations.yaml`) and it will create the spreadsheet and doc, write their IDs to `.env`, and populate the fixture data — all in one go. Skip to Step 3 when done.

### Service account (`SERVICE_ACCOUNT_PATH` / `CREDENTIALS_CONFIG`)

Service accounts cannot create files in your personal Drive. You must create them manually:

1. Create an empty spreadsheet and an empty Google Doc in any Drive folder.
2. Share the folder (or both files) with the service account email. Find it in `service_account.json` → `client_email`.
3. Continue to Step 2.

---

## Step 2 — Add IDs to `.env`

Add the following to your `.env` file (create it at the repo root if it doesn't exist):

```
# QA test fixtures
TEST_SPREADSHEET_ID=<your spreadsheet ID>
TEST_DOC_ID=<your doc ID>
TEST_FOLDER_ID=<the folder ID that contains both files>
TEST_LARGE_DOC_ID=         # large-content doc for TC-D48; create via setup_fixtures or manually
TEST_CALENDAR_ID=          # leave blank until calendar fixtures are set up
TEST_EVENT_ID=             # leave blank until calendar fixtures are set up
TEST_PERMISSION_EMAIL=     # a second Google account email for permission add/remove tests (TC-D130)
```

File and folder IDs are in the URL when you open them in Drive:
- Spreadsheet: `docs.google.com/spreadsheets/d/<ID>/edit`
- Doc: `docs.google.com/document/d/<ID>/edit`
- Folder: `drive.google.com/drive/folders/<ID>`

---

## Step 3 — Run the seed prompt

Paste the seed prompt below into a Claude session with the MCP server connected. Claude will populate the spreadsheet and doc with the known fixture data.

```
Set up my QA fixtures for mcp-gee-sweet using these IDs from my .env:
- Spreadsheet: <TEST_SPREADSHEET_ID>
- Doc: <TEST_DOC_ID>

Please do all of the following in order:

1. Rename the spreadsheet to "mcp-gee-sweet-qa-fixtures".
2. Rename the first sheet to "Sales" and populate it with:
   - Row 1 (headers): Product, Q1, Q2, Q3
   - Row 2: Widget, 100, 120, 140
   - Row 3: Gadget, 200, 180, 220
   - Row 4: Donut, 50, 60, 55
   - Row 5: Gizmo, 300, 310, 290
   - Row 6: Totals, =SUM(B2:B5), =SUM(C2:C5), =SUM(D2:D5)
3. Add a second sheet called "Empty" — leave it completely blank.
4. Add a third sheet called "Notes & Misc" with:
   - Row 1 (headers): Date, Note
   - Row 2: =TODAY(), Setup complete
5. Rename the doc to "mcp-gee-sweet-qa-fixtures-doc" and write this content:
   <h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>

Confirm when done.
```

---

## Known fixture state (after seed)

| Sheet | Row | A | B | C | D |
|---|---|---|---|---|---|
| Sales | 1 | Product | Q1 | Q2 | Q3 |
| Sales | 2 | Widget | 100 | 120 | 140 |
| Sales | 3 | Gadget | 200 | 180 | 220 |
| Sales | 4 | Donut | 50 | 60 | 55 |
| Sales | 5 | Gizmo | 300 | 310 | 290 |
| Sales | 6 | Totals | =SUM(B2:B5) | =SUM(C2:C5) | =SUM(D2:D5) |
| Empty | — | _(blank)_ | | | |
| Notes & Misc | 1 | Date | Note | | |
| Notes & Misc | 2 | =TODAY() | Setup complete | | |

Doc content: `<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>`

---

## Calendar fixture setup

Calendar tests require a calendar the service account can access.

> **Service account note:** The service account cannot see calendars shared only with your personal Google account. You must subscribe the service account to the calendar via `calendarList().insert()`. See the `Calendar API setup` memory entry for the workaround, or skip calendar tests if you don't need them.

Seed prompt (paste with MCP server connected):

```
Set up my calendar QA fixtures for mcp-gee-sweet:

1. Call list_calendars — if a calendar called "mcp-gee-sweet-qa" already appears, skip to step 3.
2. I will share my primary Google Calendar with the service account email manually in Google Calendar settings (Settings → Share with specific people). Tell me to proceed when ready.
3. Create a test event in that calendar: title "QA Test Event", tomorrow at 10:00–11:00 AM in my local timezone.
4. Return the calendar ID and the event ID.
```

Add the returned IDs to `.env` as `TEST_CALENDAR_ID` and `TEST_EVENT_ID`.

---

## Resetting fixtures

Re-run the Step 3 seed prompt against your existing IDs to restore known state. No need to create new files.
