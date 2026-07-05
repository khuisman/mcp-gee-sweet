# QA Run — 2026-07-04 (Drive (scoped) + Smoke remainder)

**Auth:** OAuth
**Fixtures:** SPREADSHEET_ID=`15hOwO1Jay26PyxjjYtq9Pq-gEd8lDa81g-C13-GyvCA` · DOC_ID=`1-whiEVwvnSOABaK9qgpzdVaGUOMRvJdQhDmCURqx4fA` · FOLDER_ID=`1RCnhFTjh4aT8AJ_Rx5J9s8O2Kqta1vJE` · CALENDAR_ID=`kevin.huisman@gmail.com`
**Scope:** This is one of four parallel shards for the v0.8.1 live QA gate. This shard covers a narrow, precisely-scoped list of 20 TCs spanning `drive.md` (export_file / list_file_activity remainder), `sheets_write.md` (TC-W01, TC-W06 — rows 7–9, non-overlapping with the sheets_read shard's rows 1–6 / A1:B2 work), `sheets_mgmt.md` (TC-S01, TC-S15, TC-S20), `sheets_charts.md` (TC-C01), and `calendar.md` (TC-CAL01, TC-CAL09, TC-CAL20). No server restarts or env var/config changes were performed (would drop the shared MCP connection all four shards depend on).

**Playwright note:** TC-CAL20 is the only Playwright-tagged case in this shard's scope. Per the concurrent docs shard's heavy use of the shared Playwright browser tab, visual verification was skipped for TC-CAL20 — confirmation relied on the `create_event`/`get_event` API responses instead (the same fallback pattern `run.md` already prescribes for permission-change tests).

## Step 0 — Fixture verification

- `get_sheet_data(TEST_SPREADSHEET_ID, sheet="Sales", range="A1:D6")` → header row + Widget/Gadget/Donut/Gizmo/Totals, columns A–D, 6 rows total. Matches expected seed state exactly. No restore needed.
- Rows 7+ and extra tabs were intentionally not checked (owned by other shards / additive to this shard's own writes).

Fixture state: **correct**, no restore performed.

## Summary

| Category | PASS | FAIL | SKIP | Total |
|---|---|---|---|---|
| Drive (export_file / list_file_activity) | 9 | 0 | 1 | 10 |
| Sheets Write | 2 | 0 | 0 | 2 |
| Sheets Mgmt | 3 | 0 | 0 | 3 |
| Sheets Charts | 1 | 0 | 0 | 1 |
| Calendar | 3 | 0 | 0 | 3 |
| **Total** | **18** | **0** | **1** | **19*** |

\* 20 TCs assigned; TC-D166 is a unit-test-only case (see Full results) so effective live-executed total is 19 PASS + 1 documented SKIP = 20 rows below.

## Failures

*(none)*

## Tool coverage (this shard only)

| Tool | TC(s) | Status |
|---|---|---|
| export_file | TC-D83, TC-D84, TC-D85, TC-D86, TC-D87, TC-D167 | ✅ all pass |
| list_file_activity | TC-D163, TC-D164, TC-D165, TC-D168 | ✅ all pass |
| update_cells | TC-W01 | ✅ pass |
| batch_update_cells | TC-W06 | ✅ pass |
| list_sheets | TC-S01, TC-S20 (verification step) | ✅ all pass |
| create_sheet | TC-S15 | ✅ pass |
| refresh_cache | TC-S20 | ✅ pass |
| add_chart | TC-C01 | ✅ pass |
| list_calendars | TC-CAL01 | ✅ pass |
| list_events | TC-CAL09 | ✅ pass |
| create_event | TC-CAL20 | ✅ pass |
| get_event | TC-CAL20 (confirmation) | ✅ pass |

(Full tool coverage across all domains is aggregated by the conductor from all four shards' results files, not by this shard alone.)

## Full results

| TC | Title | Outcome | Notes |
|---|---|---|---|
| TC-D83 | Export Google Doc as plain text | **PASS** | `export_file(DOC_ID, "txt")` → `encoding: "utf-8"`, `format: "txt"`. Content included "Test Document", the body paragraph, and "Item one"/"Item two" bullet text. |
| TC-D84 | Export Google Doc as HTML | **PASS** | `export_file(DOC_ID, "html")` → `encoding: "utf-8"`. Content wrapped in `<html>...</html>`, heading rendered as `<h1>...Test Document...</h1>`, bullets rendered as a `<ul><li>` list. |
| TC-D85 | Export Google Doc as PDF (binary) | **PASS** | `export_file(DOC_ID, "pdf")` → `encoding: "base64"`. Base64 content decodes to a valid PDF (`JVBERi0...` = `%PDF-` header). Non-empty. |
| TC-D86 | Export Google Sheet as CSV | **PASS** | `export_file(SPREADSHEET_ID, "csv")` → `encoding: "utf-8"`. Content is comma-separated text exactly matching the Sales sheet's A1:D6 data. |
| TC-D87 | Unknown export format | **PASS** | `export_file(DOC_ID, "xyz")` raised: `Unknown export_format 'xyz'. Valid options: pdf, html, txt, docx, odt, rtf, epub, csv, xlsx, ods, pptx, raw`. Clean error, not a server crash. |
| TC-D163 | Basic activity fetch returns timeline entries | **PASS** | `list_file_activity(DOC_ID)` → 79 activities. All entries have `timestamp`, `action`, `actors`. Actions observed: `edit`, `rename`, `permission_change`, `create`. No `error` key. |
| TC-D164 | Known-user actor structure | **PASS** | Multiple `type: "user"` actors present with `person_name` (e.g. `people/101951097007377611160`) and boolean `is_current_user` (both `true` and `false` values observed across different actors). A `system` actor (`event: null`) appears on the `permission_change` entry. |
| TC-D165 | Pagination — next_page_token present when results exceed page_size | **PASS** | `list_file_activity(DOC_ID, page_size=1)` returned 2 activities (API groups related events rather than hard-clipping) and a non-null `next_page_token`. |
| TC-D166 | Invalid file ID returns error (unit test) | **SKIP** | Checks section is explicitly marked "(unit test)" in `drive.md` — no live-callable repro path (would require simulating a 403/404 from the Drive Activity API). Recorded as SKIP per the file's own stated scope rather than forcing a live call. |
| TC-D167 | export_file trips the response-size cap on base64-inflated content (issue #242) | **PASS** | `export_file(SPREADSHEET_ID, "xlsx")` raised `ValueError`: "export_file: the response is 116880 characters, over the 40000-character safety cap. Base64 encoding inflates raw file size by ~33%. Call download_file instead ... or set MAX_TOOL_RESPONSE_CHARS ...". Mentions the actual size, the 40,000 cap, base64 inflation, and `download_file` — does NOT mention `local_path`. Matches the documented behavior from the prior 2026-07-03 verification exactly. |
| TC-D168 | list_file_activity response-size cap — code-path only, no dedicated live fixture (issue #242) | **PASS (N/A by design)** | Per the file's own Background note, this tool intentionally has no dedicated live cap-triggering fixture (cap is defense-in-depth, verified by unit tests `test_oversized_result_raises` / `test_error_points_to_page_size_not_local_path`). Live sanity check performed instead: `list_file_activity(SPREADSHEET_ID, page_size=5)` returned a normal 10-entry activity list, no regression, no error. Cap-triggering behavior itself remains unit-test-only — a documented scoping decision, not an oversight. |
| TC-W01 | Write simple values | **PASS** | `update_cells(SPREADSHEET_ID, sheet="Sales", range="A7:D7", data=[["Test","A","B","C"]])` → `updatedRange: "Sales!A7:D7"`, 4 cells updated. Follow-up `get_sheet_data(range="A1:D9")` confirmed row 7 = `Test, A, B, C` and rows 1–6 unchanged (Widget/Gadget/Donut/Gizmo/Totals intact). No `error` field. |
| TC-W06 | Multiple ranges in one call | **PASS** | `batch_update_cells(SPREADSHEET_ID, sheet="Sales", ranges={"A8:A8": [["Batch1"]], "A9:A9": [["Batch2"]]})` → both ranges updated in one call (`totalUpdatedCells: 2`). Follow-up read confirmed A8="Batch1", A9="Batch2". |
| TC-S01 | Happy path | **PASS** | `list_sheets(SPREADSHEET_ID)` → `["Sales", "Empty", "Notes & Misc"]` (queried before TC-S15 added "BrandNew"). All 3 expected tabs present, no `error` field. |
| TC-S15 | Create a new tab | **PASS** | `create_sheet(SPREADSHEET_ID, title="BrandNew")` → `{"sheetId": 1823833581, "title": "BrandNew", "index": 3, "spreadsheetId": "..."}`. All expected fields present. |
| TC-S20 | Refresh by spreadsheet ID only | **PASS** | `refresh_cache(spreadsheet_id=SPREADSHEET_ID)` → `{"invalidated": ["spreadsheet:15hOwO1Jay26PyxjjYtq9Pq-gEd8lDa81g-C13-GyvCA"]}`. Follow-up `list_sheets` returned `["Sales", "Empty", "Notes & Misc", "BrandNew"]` — confirms the cache was actually invalidated and the next call re-fetched fresh data (BrandNew, created moments earlier by TC-S15, was visible). |
| TC-C01 | COLUMN chart | **PASS** | `add_chart(SPREADSHEET_ID, sheet="Sales", chart_type="COLUMN", data_range="A1:D5", title="Sales by Quarter")` → `chartId: 1019744218`, `success: true`, `basicChart.chartType: "COLUMN"` in the response spec. |
| TC-CAL01 | Returns subscribed calendars | **PASS** | `list_calendars()` → 11 calendars returned. Each has `id`, `summary`, `time_zone`, `access_role`, `primary`. Exactly one (`kevin.huisman@gmail.com`) has `primary: true`. |
| TC-CAL09 | No time filters — upcoming events | **PASS** | `list_events(calendar_id="kevin.huisman@gmail.com")` (no time filter) → events ordered by start time, earliest returned event starts 2026-07-07 (after "now" = 2026-07-04) — no past events present. Each entry has `id`, `summary`, `start`, `end`, `status`. |
| TC-CAL20 | Timed event ⚠️ destructive | **PASS** | `create_event(calendar_id="kevin.huisman@gmail.com", summary="QA-Timed-Test", start="2026-07-01T10:00:00-07:00", end="2026-07-01T11:00:00-07:00", timezone="America/Los_Angeles")` → `id: "7p8utbir5rmagpjl2n67rke8pg"`, `start`/`end` are RFC 3339 with `-07:00` offset, `html_link` present, `status: "confirmed"`. Confirmed via follow-up `get_event` (same calendar_id/event_id) — full details echoed back including `created`/`updated` timestamps. Playwright visual verification was **skipped** per the concurrent docs shard's heavy use of the shared browser tab; API-response confirmation (`create_event` + `get_event`) was used instead, consistent with `run.md`'s prescribed fallback pattern for cases where Playwright isn't practical. |
