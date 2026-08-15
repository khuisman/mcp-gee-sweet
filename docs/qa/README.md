# QA Workflow

Prompt-driven integration tests for mcp-gee-sweet. Each test case is a natural language prompt you issue to Claude via the MCP server, paired with a list of things to verify in the response.

## Prerequisites

- A running mcp-gee-sweet server (Docker or `uv run mcp-gee-sweet`)
- Auth configured (service account or OAuth) with access to your Google Drive
- Claude Desktop or Claude Code connected to the server

## Steps

1. **Set up fixtures** — follow [`setup.md`](setup.md) to create your test spreadsheet, doc, and calendar fixtures. Takes about 5 minutes.
2. **Record your IDs** — copy `fixtures.template.md` → `fixtures.local.md` (gitignored) and fill in the IDs from step 1.
3. **Run tests** — paste the conductor prompt from [`run.md`](run.md) into a Claude session that has **both the mcp-gee-sweet MCP server and the Playwright MCP connected**. Claude will execute the tests, visually verify mutations in the browser via Playwright, and save a report to `results/`.
4. **Review the report** — check `results/<date>.md` for failures and the tool coverage checklist (lists every tool, which TCs exercise it, and which tools have no coverage at all).
5. **Report failures** — open a GitHub issue with the TC number, the exact prompt used, what was observed, and what Playwright showed.

## Release runs

`runs/` contains one file per stable release (`vX.Y.Z.md`). Each file is the sign-off record for that release — a checklist of required suites, links to result files, and a final sign-off. A completed run file is required before tagging any stable release. See [`runs/README.md`](runs/README.md) for suite tier definitions (smoke / domain / full regression).

## Test files

| File | Category | TC prefix |
|---|---|---|
| [tests/sheets_read.md](tests/sheets_read.md) | Sheets read tools | TC-R## |
| [tests/sheets_write.md](tests/sheets_write.md) | Sheets write tools | TC-W## |
| [tests/sheets_mgmt.md](tests/sheets_mgmt.md) | Sheets management tools | TC-S## |
| [tests/sheets_charts.md](tests/sheets_charts.md) | Sheets chart tools | TC-C## |
| [tests/drive_files.md](tests/drive_files.md) | Drive files & folders | TC-D## |
| [tests/drive_sharing.md](tests/drive_sharing.md) | Drive sharing & permissions | TC-D## |
| [tests/drive_transfer.md](tests/drive_transfer.md) | Drive upload/download/sync/export/revisions | TC-D## |
| [tests/drive_activity.md](tests/drive_activity.md) | Drive activity | TC-D## |
| [tests/docs_content.md](tests/docs_content.md) | Docs content — `content.py` plus the catch-all for `editing.py`/`images.py`/`comments.py`/`named_ranges.py` and the markdown/HTML conversion pipeline (unlike the other 7 files, not a 1:1 submodule mapping — see the file's own Source line) | TC-DOC## (plus TC-D## carried over from `create_doc`/`get_doc_content`/`write_doc_content` cases originally numbered under `drive.md`) |
| [tests/docs_tables.md](tests/docs_tables.md) | Docs tables | TC-DOC## |
| [tests/docs_style.md](tests/docs_style.md) | Docs style & theming | TC-DOC## |
| [tests/docs_layout.md](tests/docs_layout.md) | Docs layout (headers/footers) | TC-DOC## |
| [tests/infra.md](tests/infra.md) | Infrastructure | TC-I## |
| [tests/calendar.md](tests/calendar.md) | Calendar tools | TC-CAL## |

## Notes

- Tests marked **⚠️ destructive** mutate the fixture spreadsheet. Run these last within their section or reset fixtures afterward using the seed prompt in `setup.md`.
- Tests marked **⚠️ requires-oauth** need OAuth or ADC auth — service accounts cannot create or copy files in Drive (no storage quota). These tests are automatically skipped with a warning when `QA_AUTH_METHOD=service_account` in `.env`.
- Tests marked **⚠️ local-filesystem** need file paths accessible to the MCP server process. These cannot run in an AI-session QA run and are always skipped.
- Tests marked **🔍 product decision** have no single correct answer — note what you observed and open an issue if the behavior seems wrong.
- Cache hit tests (TC-R17, TC-S02, etc.) require checking server logs: `make logs` or `docker compose logs mcp-gee-sweet`.

## Contributing

If you find a bug or surprising behavior, open a GitHub issue. To add a new test case, submit a PR adding it to the relevant file in `tests/` with the next sequential TC number.

## Test case format

Each test case follows this structure:

```markdown
### TC-XNN: Short description [tags]

**Setup:** <precondition — fixture file path or live doc state to establish>

**Prompt**
> "Natural language instruction to Claude"

**Checks**
- Specific key or value to verify in the response (e.g. "`docId` returned with no `error`")
- Structural assertion (e.g. "`get_doc_structure` shows HEADING_1 "Foo" and a table")
- 🔍 Visual check: anything that requires opening the doc/sheet in a browser

**Cleanup:** what to delete or tear down

**Result:** ⏳ pending  ← replaced with date + PASS/FAIL after live run
```

### Fixture files

If a test needs a local file (e.g. a `.md` or `.html` to upload), **commit it to `docs/qa/fixtures/`** and reference it by repo path — don't ask the tester to write content by hand. Name fixtures after their TC number: `tc-d195-create-doc.md`. Note: several `docs.md` fixtures (`tc-d195-*`, `tc-d196-*`, `tc-d213-*`, `tc-d226-*`) still carry `TC-D##`-prefixed filenames from before `docs.md` was split onto its own `TC-DOC##` sequence — their current headers are `TC-DOC44`, `TC-DOC45`, etc., not the number in the filename. Don't assume a `TC-D<N>`-shaped filename means that number is claimed in `drive.md`'s own sequence, and don't assume a fixture's filename number matches its test case's current number.

### Checks quality bar

- Name specific keys, values, or text strings — not vague descriptions like "the response looks right"
- Visual checks (`🔍`) are fine for things the API doesn't surface (e.g. rendered font size in Google Docs)
- Error-path tests should name the exact error key or message fragment expected
