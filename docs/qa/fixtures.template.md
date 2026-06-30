# Fixtures

Fixture IDs now live in `.env` at the repo root (gitignored), not in this file.

Copy the block below into your `.env` and fill in your IDs after running the seed prompt in `setup.md`.

```
# QA test fixtures
TEST_SPREADSHEET_ID=       # mcp-gee-sweet-qa-fixtures spreadsheet
TEST_DOC_ID=               # mcp-gee-sweet-qa-fixtures-doc
TEST_FOLDER_ID=            # the Drive folder containing both files
TEST_LARGE_DOC_ID=         # mcp-gee-sweet-qa-large-doc (TC-D48 large-content test)
TEST_CALENDAR_ID=          # a calendar the authenticated account can access
TEST_EVENT_ID=             # a pre-existing event in that calendar
TEST_PERMISSION_EMAIL=     # a second account to use for permission add/remove tests (TC-D130)
```

See `setup.md` for how to create the fixtures and which auth options require extra sharing steps.
