# Fixtures

Fixture IDs now live in `.env` at the repo root (gitignored), not in this file.

Copy the block below into your `.env` and fill in your IDs after running the seed prompt in `setup.md`.

```
# Server default create-location — the mcp-gee-sweet-shared Shared Drive ID
DRIVE_FOLDER_ID=          # same value as SHARED_DRIVE_ID below

# QA test fixtures (provisioned inside the mcp-gee-sweet-shared Shared Drive)
TEST_SPREADSHEET_ID=       # mcp-gee-sweet-qa-fixtures spreadsheet
TEST_DOC_ID=               # mcp-gee-sweet-qa-fixtures-doc
TEST_FOLDER_ID=            # the Shared Drive folder containing the fixture files
TEST_LARGE_DOC_ID=         # mcp-gee-sweet-qa-large-doc (TC-D48 large-content test)
TEST_CALENDAR_ID=          # a calendar the authenticated account can access
TEST_EVENT_ID=             # a pre-existing event in that calendar
TEST_PERMISSION_EMAIL=     # a second account to use for permission add/remove tests (TC-D130)
SHARED_DRIVE_ID=           # mcp-gee-sweet-shared Shared Drive (TC-D121/D122/D205); = DRIVE_FOLDER_ID
```

See `setup.md` for how to create the fixtures and which auth options require extra sharing steps.
