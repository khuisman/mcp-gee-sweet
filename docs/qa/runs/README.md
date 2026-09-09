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
| TC-D13 | `list_spreadsheets` | `tests/drive_files.md` |
| TC-D36 | `list_files` | `tests/drive_files.md` |
| TC-D44 | `get_doc_content` | `tests/docs_content.md` |
| TC-D79 | `get_file_metadata` | `tests/drive_files.md` |
| TC-D152 | `list_shared_with_me` | `tests/drive_files.md` |
| TC-D160 | `get_storage_quota` | `tests/drive_files.md` |
| TC-D152 | `get_doc_structure` | `tests/docs_content.md` |
| TC-CAL01 | `list_calendars` | `tests/calendar.md` |
| TC-CAL09 | `list_events` | `tests/calendar.md` |
| TC-CAL20 | `create_event` | `tests/calendar.md` |

> **Note:** TC-D152 appears in both `tests/drive_files.md` (`list_shared_with_me`) and `tests/docs_content.md` (`get_doc_structure`) due to a numbering conflict — see #201. Run both; they cover different tools. `get_doc_structure`'s own current numbering is actually `TC-DOC01` (renumbered per #201's resolution) — this row's `TC-D152` label appears to predate that renumbering and was already stale before this file split; not fixed here as it's a numbering-content question, not a file-organization one.

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

## Pre-approved SKIPs (master list)

Disposition of every SKIP from the v0.8.0 Full Regression run (44 total, `docs/qa/results/2026-06-28.md`), reviewed case-by-case against the actual test suite rather than trusting each case's original SKIP note (issue #227). Each new run-gate file's own "Pre-approved SKIPs" table should be copied forward from this list, trimmed to whatever's actually in scope for that run.

**Categories:**
- **Pre-approved** — no action; already covered or a documented non-testable limitation
- **Unit-tested** — verified live against `tests/` to actually cover the case; safe to pre-approve
- **Environmental** — needs a fixture/account change to un-skip; low-risk by inspection in the meantime
- **Procedure exists** — was manual-only for lack of a way to run it; now has a documented procedure and **must be executed during the pass**, not skipped
- **Genuine gap** — verified *not* covered anywhere; tracked as a follow-up issue, still counts as a live-run SKIP until closed

| TC | Reason | Category | Coverage / Action |
|---|---|---|---|
| TC-I01, I03 | Cache TTL / `CACHE_DB_PATH` — requires restart | Unit-tested | ✅ `tests/test_cache.py` |
| TC-I02, TC-I24 | Cross-session concurrency — needs two simultaneous requests to one server, which a single client session can't produce | Procedure exists | Run via `run.md` §"Running true-concurrency test cases" (two-subagent `mkdir`-barrier procedure) during the release pass — no longer a standing SKIP (#673) |
| TC-I04 | Cache persists across restart | Pre-approved | SQLite file persistence, trivially true by design |
| TC-I13 | stdio transport — requires client config change | Pre-approved | Manual / verify once per environment |
| TC-I15 | Hot reload with SSE | Pre-approved | Manual — known uvicorn + SSE limitation |
| TC-D04 | Service account Drive quota-limit message | Unit-tested | ✅ `tests/drive/test_files.py::TestQuotaErrors` |
| TC-D35 | `search_spreadsheets` forced API error | Genuine gap | No test mocks a failing `.execute()` for this tool's `except Exception → {"error": ...}` path — #490 |
| TC-D93, D94, D96, D97 | `upload_local_file` (binary, skip_if_exists, non-existent, name override) | Unit-tested | ✅ `tests/drive/test_transfer.py::TestUploadLocalFileCore`/`TestUploadLocalFileConvert` |
| TC-D95 | `upload_local_file` skip_if_exists=False creates duplicate | Genuine gap | Every non-skip test mocks `list → {"files": []}` — no test ever has a colliding file present to actually observe the duplicate-creation behavior — #495 |
| TC-D98–D102 | `upload_local_folder` (basic, skip_if_exists, recursive, ignore patterns, non-existent) | Genuine gap | Zero unit test coverage for this tool at all — #485 |
| TC-D103–D107 | `download_file` (Doc export, Sheet as xlsx, export_format, binary, non-existent) | Genuine gap | Zero unit test coverage for this tool at all — #486 |
| TC-D108 | `download_folder` basic | Unit-tested | ✅ `tests/drive/test_transfer.py::TestDownloadFolder` |
| TC-D109, D110 | `download_folder` `skip_if_exists` / `mime_type_filter` | Genuine gap | Neither param exercised by any test — #487 |
| TC-D111–D118 | `sync_folder` (dry_run, drive-only, local-only, newer-wins, mtime, direction=upload/download, Workspace excluded) | Unit-tested | ✅ ~38 tests across `TestSyncFolder*` classes |
| TC-D119 | `sync_folder` invalid `direction` value | Genuine gap | No validation exists in the code for an unrecognized `direction` — silent no-op, not just untested — #488 |
| TC-D123 | `list_drives` pagination | Genuine gap | Pagination loop has no mocked-multi-page test — #489 |
| TC-D155 | `list_shared_with_me` `mime_type` single-quote escaping | Genuine gap | `TestListSharedWithMe` has no quote-escaping test — the table originally miscited `test_single_quote_is_escaped`, which covers an unrelated tool (`search_spreadsheets`'s `query` param) — #494 |
| TC-D159 | `list_recent_files` max_results cap | Unit-tested | ✅ `test_max_results_capped_at_200`/`_100` |
| TC-D161, D162 | `get_storage_quota` SA `limit_bytes=0` / integer types | Unit-tested | ✅ `tests/drive/test_files.py::TestGetStorageQuota` |
| TC-D166 | `list_file_activity` invalid file ID returns error | Unit-tested | ✅ `tests/drive/test_activity.py::test_http_error_returns_error_dict` |
| TC-DOC51 | Nested tables not supported in markdown | Pre-approved | Documented limitation — no code path exists to test |
| TC-CAL04 | `list_calendars` empty subscription list | Environmental | Needs a fresh account with zero subscriptions; trivially correct by code inspection (list comprehension over `[]`) in the meantime |
| TC-CAL32 | `find_free_slots` multi-calendar merge | Genuine gap | `TestFindFreeSlots`'s mock only ever configures one `cal_id`; no test merges busy periods across calendars — #491 |

**Follow-up issues filed for genuine gaps:** #485 (`upload_local_folder`), #486 (`download_file`), #487 (`download_folder` params), #488 (`sync_folder` invalid direction — also a possible validation gap, `decision-needed`), #489 (`list_drives` pagination), #490 (`search_spreadsheets` error path), #491 (`find_free_slots` multi-calendar), #494 (`list_shared_with_me` mime_type escaping), #495 (`upload_local_file` no-skip duplicate path).

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
6. **Required suites:** Smoke (always) + a Domain run for every domain identified in steps 3–4, scoped by how the change touched that domain's file:
   - **Structural** — a refactor that reorganizes files/modules (like the `docs/__init__.py` submodule split), or a change whose diff spans most of the domain's tool sections. Run the **full** domain test file. "No intended behavior change" is a claim, not evidence; only full live coverage of that file counts as evidence, especially for a domain that's never had a live pass since the reorg.
   - **Non-structural** — one or a handful of isolated tool sections changed within a larger per-submodule test file (e.g. `drive_files.md` covers 20+ tools, but a fix touched only `list_recent_files`), with no reorganization. Running just the changed tools' TC sections is sufficient — identify the exact functions touched **in the diff itself**, not just what the originating issue claims to have scoped, since a fix can touch more than its issue describes.
   - **When in doubt, treat it as structural.** Over-testing a domain file costs time; under-testing a refactor costs a shipped regression.
7. **Fall back to Full Regression** if the audit can't be done cleanly (history too messy or rebased to enumerate reliably) or if more than roughly half the domains would need a Domain run anyway — at that point scoping isn't saving meaningful time.
8. **Document the audit** in the release's `docs/qa/runs/vX.Y.Z.md`: list the commits reviewed, the classification of each (including structural vs. non-structural for domains that got a tool-scoped run), and which domains/tools were included or excluded and why. This is what makes the scoping decision auditable rather than a one-off judgment call.
