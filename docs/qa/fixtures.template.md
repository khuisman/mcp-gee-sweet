# Fixtures

Copy this file to `fixtures.local.md` (gitignored) and fill in your IDs after running the seed prompt in `setup.md`.

```
# Core fixtures — created by the setup seed prompt
SPREADSHEET_ID=   # mcp-gee-sweet-qa-fixtures spreadsheet
DOC_ID=           # mcp-gee-sweet-qa-fixtures-doc
FOLDER_ID=        # the Drive folder the spreadsheet was created in

# Calendar fixtures — required for calendar tests
# The service account must be subscribed to this calendar first (see docs/qa/setup.md)
CALENDAR_ID=      # a calendar the service account has access to
EVENT_ID=         # a pre-existing event in that calendar
```

Substitute these values for `{PLACEHOLDER}` names in the test prompts.

The conductor prompt (`docs/qa/run.md`) reads this file automatically — you do not need to substitute manually when using it.
