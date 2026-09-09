# Fixture Setup

## Overview

QA fixtures are a spreadsheet, a doc, a large-content doc, a folder, and a calendar +
event that test cases reference. Their IDs live in `.env` (gitignored) alongside your
other server config.

Fixtures are provisioned in the **`mcp-gee-sweet-shared` Shared Drive** — common ground
that both the OAuth QA identity and the service account can read and write. (The Shared
Drive's own ID doubles as a fixture, `SHARED_DRIVE_ID`, for the `list_drives` /
`empty_trash --drive_id` test cases.)

Setup has four steps: make sure the required Google APIs are enabled, create the files
in the Shared Drive, add the resulting IDs to `.env`, then run the seed prompt to
populate them.

---

## Step 0 — Enable the required Google APIs

The OAuth client's GCP project must have every API these tools call **enabled**, or the
tool fails at call time with `HttpError 403 ... "<API> has not been used in project
<n> before or it is disabled"` (`reason: SERVICE_DISABLED`). File creation still
partly succeeds in that state (the file shell is made via the Drive API) while every
content read/write fails — a confusing half-broken state, so enable all of these up
front:

| API | Service name | Used by |
|---|---|---|
| Google Drive | `drive.googleapis.com` | every Drive tool, and file creation for Sheets/Docs |
| Google Sheets | `sheets.googleapis.com` | all sheet read/write tools |
| Google Docs | `docs.googleapis.com` | all doc content tools |
| Google Calendar | `calendar-json.googleapis.com` | all calendar tools |
| Google Drive Activity | `driveactivity.googleapis.com` | `list_file_activity` |

```
gcloud services enable drive.googleapis.com sheets.googleapis.com docs.googleapis.com \
  calendar-json.googleapis.com driveactivity.googleapis.com --project=<your-project>
```

or enable each from the API Library in the Cloud Console. Changes take ~1–3 minutes to
propagate.

---

## Step 1 — Create the files in the Shared Drive

How you create the fixture files depends on your auth method. Either way the target is a
folder **inside the `mcp-gee-sweet-shared` Shared Drive** (not personal My Drive) so the
service account can reach them too.

### OAuth / Application Default Credentials

The AI can create the fixture set for you. In a Claude session with the MCP server
connected, run the `setup_fixtures` operation (see `operations.yaml`) and it will create
the folder, spreadsheet, doc, and large-content doc in the Shared Drive, write their IDs
to `.env`, and populate the fixture data. Skip to Step 3 when done.

### Service account (`SERVICE_ACCOUNT_PATH` / `CREDENTIALS_CONFIG`)

A service account has no personal-Drive storage quota, but it **can** create files in a
Shared Drive it's a member of. Add the service account (`service_account.json` →
`client_email`) to the `mcp-gee-sweet-shared` Shared Drive as **Content manager**, then
either run `setup_fixtures` or create an empty spreadsheet, Google Doc, and large-content
Doc in a folder inside that Shared Drive by hand. Continue to Step 2.

---

## Step 2 — Add IDs to `.env`

Add the following to your `.env` file (create it at the repo root if it doesn't exist):

```
# Server default create-location — set to the Shared Drive's ID
DRIVE_FOLDER_ID=<mcp-gee-sweet-shared Shared Drive ID>

# QA test fixtures
TEST_SPREADSHEET_ID=<spreadsheet ID>
TEST_DOC_ID=<doc ID>
TEST_FOLDER_ID=<the folder inside the Shared Drive that contains the fixture files>
TEST_LARGE_DOC_ID=<large-content doc ID for TC-D48; create via setup_fixtures or manually>
TEST_CALENDAR_ID=<see Calendar fixture setup below>
TEST_EVENT_ID=<see Calendar fixture setup below>
TEST_PERMISSION_EMAIL=<a second Google account email for permission add/remove tests (TC-D130)>
SHARED_DRIVE_ID=<mcp-gee-sweet-shared Shared Drive ID — same value as DRIVE_FOLDER_ID>
```

`SHARED_DRIVE_ID` and `DRIVE_FOLDER_ID` are the same value: a Shared Drive's ID is also
its root folder ID. Get it from `list_drives`, or from the URL when the drive is open
(`drive.google.com/drive/folders/<ID>`).

File and folder IDs are in the URL when you open them in Drive:
- Spreadsheet: `docs.google.com/spreadsheets/d/<ID>/edit`
- Doc: `docs.google.com/document/d/<ID>/edit`
- Folder / Shared Drive: `drive.google.com/drive/folders/<ID>`

---

## Step 3 — Run the seed prompt

Paste the seed prompt below into a Claude session that has **both the mcp-gee-sweet MCP server and the Playwright MCP connected**. Claude will populate the spreadsheet and doc with the known fixture data, then open each file in Playwright to visually confirm the result.

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

Then open https://docs.google.com/spreadsheets/d/<TEST_SPREADSHEET_ID>/edit in Playwright and take a snapshot to visually confirm the sheet names and data are correct. Do the same for the doc at https://docs.google.com/document/d/<TEST_DOC_ID>/edit.
```

The **large-content doc** (`TEST_LARGE_DOC_ID`, "mcp-gee-sweet-qa-large-doc") is padded
past ~50,000 characters of filler text so `get_doc_content` returns a large response
without timeout or truncation (TC-D48). `setup_fixtures` creates it; to build it by hand,
`create_doc_from_file` a `.md` file of repeated lorem-ipsum paragraphs into the fixture
folder.

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

Calendar tests need a dedicated calendar plus one pre-existing event.

### OAuth / ADC

`create_calendar` makes a secondary calendar owned by the authenticated account — no
personal-calendar sharing needed. Seed prompt (paste with MCP server connected):

```
Set up my calendar QA fixtures for mcp-gee-sweet:

1. Call list_calendars — if a calendar called "mcp-gee-sweet-qa" already appears, use it and skip to step 3.
2. Call create_calendar with summary "mcp-gee-sweet-qa".
3. Create an event in that calendar: title "QA Test Event", tomorrow at 10:00–11:00 in the calendar's timezone.
4. Return the calendar ID and the event ID.
```

### Service account

The service account cannot see a calendar shared only with a personal account — you must
subscribe it via `calendarList().insert()`. See the `Calendar API setup` memory entry for
the workaround, or skip calendar tests if you don't need them.

Add the returned IDs to `.env` as `TEST_CALENDAR_ID` and `TEST_EVENT_ID`.

---

## OAuth token setup (for `⚠️ requires-oauth` tests)

Tests tagged `⚠️ requires-oauth` need a valid OAuth token (`token.json`). If you're running with a service account or ADC, these tests will be skipped or will fail — they require personal Drive access.

To acquire or refresh a token without manually clicking through Google's consent screen, see **[`docs/qa/playwright_oauth.md`](playwright_oauth.md)**. Two paths are documented:

- **Playwright-assisted**: run `scripts/oauth_setup.py`, let Claude Code + Playwright MCP complete the browser flow
- **Refresh token injection**: one-time manual flow, then store the refresh token as an env secret for all future runs (CI-friendly)

---

## Resetting fixtures

Re-run the Step 3 seed prompt against your existing IDs to restore known state. No need to create new files.
