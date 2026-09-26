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

# Gmail QA fixtures (written by scripts/qa_gmail_fixtures.py; see setup.md)
TEST_GMAIL_ADDRESS=        # QA mailbox (the OAuth fixture account)
TEST_GMAIL_SENDER_ADDRESS= # sender mailbox that delivers the sent fixtures
TEST_GMAIL_LABEL_ID=       # mcp-qa-fixture user label
TEST_MESSAGE_ID=           # plain
TEST_THREAD_ID=            # thread (3-message, two-party)
TEST_GMAIL_UNICODE_ID=     # alt-unicode
TEST_GMAIL_ATTACH_ID=      # attachments (PDF + CSV)
TEST_GMAIL_INLINE_ID=      # inline (multipart/related PNG, no filename)
TEST_GMAIL_REPLYTO_ID=     # reply-to (TC-GM23)
TEST_GMAIL_FWD_ID=         # forwarded (message/rfc822)
TEST_GMAIL_LARGE_ID=       # large-body (~3 MB, #803 item 2)
TEST_GMAIL_BIG_THREAD_ID=  # over-cap-thread
TEST_GMAIL_LATIN1_ID=      # latin1 (#792)
```

See `setup.md` for how to create the fixtures and which auth options require extra sharing steps.
