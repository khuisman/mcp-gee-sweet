# QA Retro — v0.8.0 Full Regression

**Run date:** 2026-06-28  
**Auth:** OAuth  
**Results:** [docs/qa/results/2026-06-28.md](results/2026-06-28.md)  
**Scope:** First full regression run with Playwright visual verification on every mutation

---

## What went well

**The Playwright + API + cache three-way comparison found a real bug.**  
TC-D73 (`delete_file` on a folder): API returned `"action: trashed"`, cache still listed the folder, Playwright showed it gone from Drive. Three different answers made the cache bug immediately obvious and unambiguous. This is exactly the scenario the visual verification was designed to catch, and it worked.

**Unit test coverage carried the infra suite.**  
TC-I05–I12 (tool filtering, all auth variants) are fully covered by 476 unit tests. Having those green meant the infra live QA reduced to three manual checks (OAuth in-session, SSE in-session, logging from a prior run) instead of twelve server-restart cycles. The test suite and live QA complemented each other rather than duplicating.

**Pre-approved SKIPs in the gate file reduced decision fatigue.**  
`docs/qa/runs/v0.8.0.md` listing which SKIPs were pre-approved (local-filesystem, WAL concurrency, hot reload) meant we didn't have to adjudicate them mid-run. The run moved faster because there were no judgment calls about whether to stop and set up a special environment.

**435 test cases run in a single session.**  
Sheets, Drive, Docs, Calendar, and Infra in one continuous session with no fixture rot between suites. The fixture spreadsheet and doc held their state well across ~8 hours of parallel test activity.

---

## What didn't work well

### 1. "Visual whenever visual is possible" was too broad

The rule caused Playwright snapshots on tests where the browser added no information:
- **Read-only tests** (`get_sheet_data`, `list_events`, `get_doc_content`): the API response is the ground truth; the browser shows the same data.
- **Error path tests**: nothing changes in the UI when a tool returns `{"error": "..."}`.
- **Count/pagination tests**: whether a list contains 2 or 100 items isn't visible at a glance.
- **"Confirmation" shots for trivial Drive mutations**: by TC-D60+ each `create_folder` → navigate → "folder is there" snapshot was confirming that the Google Drive API works, not the tool.

**Cost:** significant extra time per test for near-zero extra signal.

### 2. Footer/header Playwright limitation was undocumented

Google Docs renders the footer in the document canvas at the bottom of the page, below the browser's viewport. `window.scrollTo` does not reach it for short documents. TC-DOC70/71 required a fallback to API response confirmation. This will happen on every run — it needs to be documented in `run.md` so future QA conductors don't spend time debugging why the footer isn't scrolling into view.

### 3. Test fixture email addresses were not real Google accounts

`test-recipient@example.com` and `test-recipient@example.com` are placeholder addresses. Three test cases (TC-D135, TC-D137, TC-D139) failed because Drive rejects sharing with non-Google accounts in certain modes. Each failure required investigation to distinguish "tool bug" from "test design problem." They're marked FAIL in the results but are not tool bugs.

The `.env` already has `TEST_PERMISSION_EMAIL` for one test — this pattern needs to extend to the share_file suite so all sharing tests use a real secondary account.

### 4. Drive revision grouping produced an unexplained FAIL

TC-D148 expected to read an earlier revision after two rapid sequential writes. Drive's revision API coalesced both writes into a single revision, so `QA-BEFORE` was never a separately exportable state. The test FAIL required investigation to understand. The test design assumption (rapid writes produce distinct revisions) doesn't hold.

### 5. `list_events` time_min bug discovered late

TC-CAL09 (all historical events returned when `time_min` omitted) was a significant behavioral discrepancy, but it was only discovered during the calendar suite, near the end of the run. A smoke test that exercises `list_events` with no arguments earlier in the run would have surfaced this sooner.

---

## Action items

### Run.md / process improvements
- [x] **Refine Playwright guidance** — define three explicit tiers in `run.md`: *Required* (mutations with a visual component), *Spot-check* (optional — only if something looks suspicious), *Skip* (read-only, error paths, count/pagination). Replace "visual whenever visual is possible" with the tier table. Tier definition formalized in #264 (PR #593). The same PR's audit against the new tiers covers `docs_content.md`/`docs_style.md`/`docs_tables.md`/`sheets_charts.md` (PR #592) — `drive_files.md`/`drive_transfer.md`/`drive_sharing.md` (209 test cases, zero Playwright tags) audited in #597: `drive_sharing.md`/`drive_files.md` turned out fully Skip-tier already (permission/metadata changes are all API-confirmable); `drive_transfer.md` had three genuine gaps (TC-D90/91/92, `upload_file`'s markdown/HTML→Doc conversion, whose Checks required opening the doc in a browser with no API alternative) now tagged `**Playwright: required**`.
- [x] **Document footer/header Playwright limitation** — add a note in `run.md` that Google Docs footer/header content is not reachable via browser scroll for short documents; use API response as confirmation for those tests. Already present in `run.md`'s "Known limitations" section.

### Test suite improvements
- [ ] **Fix share_file test fixtures** — update `docs/qa/tests/drive.md` TC-D135/D137/D139 to require a real Google account in `TEST_PERMISSION_EMAIL` (or add a second env var). Note the drive.md setup section accordingly.
- [ ] **Fix TC-D148 test design** — add a `time.sleep(2)` or a forced flush between the two writes, or change the test to verify the revision mechanism works without relying on separate revisions being created.
- [ ] **Add a list_events smoke check to the infra suite or session warmup** — call `list_events(time_min=now)` as a fixture verification step so time_min filtering is exercised early.

### Bugs to fix
- [ ] **#216** — `delete_file`: invalidate `drive_folder_cache` for parent folder on trash/delete
- [ ] **#217** — `get_file_metadata`: suppress or rename `size` for Workspace files
- [ ] **#218** — `list_events`: either default `time_min` to now, or update docstring to match actual behaviour
- [ ] **#215** — `create_event`: update timezone docstring to cover recurring datetime events

### For next retro
- Track: did the refined Playwright tiers reduce time-per-test without missing bugs?
- Track: did the share_file fixture fix eliminate the environmental FAILs?
- Consider: should multi-table write_doc_content (#144 gap) be promoted to a blocking issue for v0.9.0?

---

## Playwright tier proposal (for run.md)

| Tier | When to use | Examples |
|---|---|---|
| **Required** | Mutations with a visual component — formatting, layout, create/delete/move confirmed in UI, cache invalidation checks | format_cells, freeze, merge, add_chart, delete_file, write_doc_content tables, create_event |
| **Spot-check** | When an API response looks unexpected or a cache discrepancy is suspected | Any time API says success but behavior seems wrong |
| **Skip** | Read-only, error paths, count/pagination, cache-hit-only, unit-tested paths | get_sheet_data, list_events, error returns, rows_to_fetch counts |
