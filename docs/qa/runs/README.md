# QA Runs

One file per stable release, named `vX.Y.Z.md`. Each file is the sign-off record confirming the test suite passed before the release tag was cut. Run files are checked into the repo alongside the code they cover.

---

## Suite tiers

| Tier | ~Cases | When to run |
|---|---|---|
| **Smoke** | ~20 happy-path cases, one per tool group | Before every release (stable or dev) |
| **Domain** | Full test file for one domain | When a specific domain has changes |
| **Full regression** | All domain suites | Before every stable release |

**Stable releases require Full regression.** Dev releases (`0.x.0.devN`) require Smoke at minimum.

---

## Smoke suite

One happy-path case per tool group — fast, no destructive operations where avoidable.

| TC | Tool | Source |
|---|---|---|
| TC-R01 | `get_sheet_data` | `tests/sheets_read.md` |
| TC-R08 | `get_sheet_formulas` | `tests/sheets_read.md` |
| TC-R16 | `get_multiple_spreadsheet_summary` | `tests/sheets_read.md` |
| TC-R23 | `find_in_spreadsheet` | `tests/sheets_read.md` |
| TC-W01 | `update_cells` | `tests/sheets_write.md` |
| TC-W06 | `batch_update_cells` | `tests/sheets_write.md` |
| TC-S01 | `list_sheets` | `tests/sheets_mgmt.md` |
| TC-S15 | `create_sheet` | `tests/sheets_mgmt.md` |
| TC-S20 | `refresh_cache` | `tests/sheets_mgmt.md` |
| TC-C01 | `add_chart` | `tests/sheets_charts.md` |
| TC-D13 | `list_spreadsheets` | `tests/drive.md` |
| TC-D36 | `list_files` | `tests/drive.md` |
| TC-D44 | `get_doc_content` | `tests/drive.md` |
| TC-D79 | `get_file_metadata` | `tests/drive.md` |
| TC-D152 | `list_shared_with_me` | `tests/drive.md` |
| TC-D160 | `get_storage_quota` | `tests/drive.md` |
| TC-D152 | `get_doc_structure` | `tests/docs.md` |
| TC-CAL01 | `list_calendars` | `tests/calendar.md` |
| TC-CAL09 | `list_events` | `tests/calendar.md` |
| TC-CAL20 | `create_event` | `tests/calendar.md` |

> **Note:** TC-D152 appears in both `drive.md` (`list_shared_with_me`) and `docs.md` (`get_doc_structure`) due to a numbering conflict — see #201. Run both; they cover different tools.

---

## How to start a run

1. Start the mcp-gee-sweet server and connect a Claude session to it.
2. Check that `docs/qa/.env` exists with `TEST_*` fixture IDs (see `setup.md`).
3. Paste the conductor prompt from `docs/qa/run.md` into the session.
   - For a smoke run: add "Only run the smoke suite cases listed in `docs/qa/runs/README.md`."
   - For a domain run: add "Only run `tests/<domain>.md`."
   - For full regression: paste the prompt as-is.
4. Save results to `docs/qa/results/<YYYY-MM-DD>.md`.
5. Fill in the run file for this release and check off each suite when it passes.

---

## Release gate

A completed `docs/qa/runs/vX.Y.Z.md` — with all required suites checked off and a results file linked — is required before tagging a stable release.
