# QA Runs

One file per stable release, named `vX.Y.Z.md`. Each file is the sign-off record confirming the test suite passed before the release tag was cut. Run files are checked into the repo alongside the code they cover.

---

## Suite tiers

| Tier | ~Cases | When to run |
|---|---|---|
| **Smoke** | ~20 happy-path cases, one per tool group | Before every release (stable or dev) |
| **Domain** | Full test file for one domain | When a specific domain has changes |
| **Full regression** | All domain suites | Before every stable release, unless the release qualifies for scoped gating (see below) |

**Stable releases require Full regression by default.** Dev releases (`0.x.0.devN`) require Smoke at minimum. See [Release gate](#release-gate) for when a stable release can substitute Smoke + targeted Domain runs instead.

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

### Scoped gating

Full Regression is the default, but a release can substitute **Smoke + targeted Domain runs** if a source-diff audit shows the change is narrow. Rationale in [`docs/decisions/decision-testing.md`](../../decisions/decision-testing.md#release-gate-scoping-2026-07-04); this section is the mechanical process.

1. **Enumerate.** `git log v<last-stable>..HEAD -- src/` — list every commit touching source since the last stable tag.
2. **Classify each one:**
   - **Behavior change** — a tool's inputs, outputs, or side effects changed.
   - **Pure refactor** — organization only; existing tests were re-targeted at the same assertions, no intended behavior change.
3. **Map behavior changes to domains** using the tool→test-file table in `docs/qa/README.md`.
4. **Include a refactor's domain too** if that refactor has never had a live QA pass — i.e. it landed after the last stable release's run file. Unit tests mock the Google API; they can't catch integration drift a refactor might introduce (wrong re-export, changed call order, etc.), so a live Domain run is the only thing that actually checks it.
5. **A cross-cutting change** — touches shared infrastructure used by every tool (the `tool()` decorator, auth, server startup) — does not by itself force Full Regression. Smoke already samples one call per tool group, which is enough to catch a generic regression from a shared-layer change.
6. **Required suites:** Smoke (always) + a Domain run for every domain identified in steps 3–4.
7. **Fall back to Full Regression** if the audit can't be done cleanly (history too messy or rebased to enumerate reliably) or if more than roughly half the domains would need a Domain run anyway — at that point scoping isn't saving meaningful time.
8. **Document the audit** in the release's `docs/qa/runs/vX.Y.Z.md`: list the commits reviewed, the classification of each, and which domains were included/excluded and why. This is what makes the scoping decision auditable rather than a one-off judgment call.
