# QA Run — 2026-07-04 (Sheets Read shard)

**Auth:** OAuth
**Fixtures:** SPREADSHEET_ID=`15hOwO1Jay26PyxjjYtq9Pq-gEd8lDa81g-C13-GyvCA`
**Scope:** This is one of four parallel shards for the v0.8.1 live QA gate. This shard covers ONLY `docs/qa/tests/sheets_read.md` (39 TCs) — a full run, since `get_sheet_data` changed for issue #235 in this release. No server restarts or env var/config changes were performed (would drop the shared MCP connection all four shards depend on).
**Start:** ~20:11 · **End:** ~20:57 (run cut short at the very last step — TC-R35 teardown — by a shared-server auth outage; see "Known issues" below)

## Step 0 — Fixture verification and cleanup

- `list_sheets` → `["Sales", "Empty", "Notes & Misc"]` — all three expected tabs present (a `BrandNew` tab appeared later from a concurrent shard — expected, out of scope).
- `get_sheet_data(sheet="Sales", range="A1:D6")` (values-only) initially returned **`$100.00`, `$200.00`, `$50.00`, `$300.00`, `$650.00`** for column B instead of plain numbers — column B (rows 2-6) carried stray `CURRENCY` `userEnteredFormat.numberFormat`, left over from a previous, incompletely-torn-down run of TC-R33. This directly conflicts with TC-R01/TC-R02's checks ("Totals values are computed 650/670/705 — not formula/formatted strings"). **Cleaned via `batch_update → repeatCell` clearing `userEnteredFormat.numberFormat` on Sales!B2:B6** before starting. Re-verified: `100, 120, 200, ..., 650, 670, 705` — clean.
- `get_sheet_data(sheet="Notes & Misc")` → `Date, Note` header + `7/4/2026, Setup complete` — matches known fixture state.
- Also found (while running TC-R31/32): the header row Sales!A1:D1 carried leftover `bold=true` + light-blue background + center alignment, same stale-leftover class as above. Cleaned incrementally as each TC's own prescribed teardown ran over A1 and B1 (see notes on TC-R31/R32 below).

Fixture state: **corrected then correct.** (Rows/tabs beyond row 6 or extra tabs belong to concurrent shards — not treated as corruption, per scope instructions.)

## Summary

| Category | PASS | FAIL | SKIP | Total |
|---|---|---|---|---|
| Sheets Read | 36 | 2 | 1 | 39 |

## Failures

**TC-R10 — Mixed cells — formulas and literals**
Expected: "B2 returns `=TODAY()` (formula string)".
Observed: The test case's cell reference does not match the actual fixture layout. Per `setup.md`'s seed data, Notes & Misc is `Date` (column A), `Note` (column B) — so **A2** contains `=TODAY()` and **B2** contains the literal `"Setup complete"`. Live call to `get_sheet_formulas(sheet="Notes & Misc")` returned `[["Date","Note"],["=TODAY()","Setup complete"]]` — i.e., the tool correctly differentiates formula vs. literal cells (no computed value where a formula exists, header row is literal), but strictly by the check as written, B2 does not return `=TODAY()`. This reads as a test-file documentation defect (swapped A2/B2 reference) rather than a product bug — recording FAIL rather than silently "fixing" the interpretation, per the checks-as-written. Recommend the test file be corrected to reference A2.

**TC-R19 — rows_to_fetch=0 — clamped to 1 (🔍 product decision)**
Expected: "Server clamps to 1 (`max(1, 0)`)" and "Behaves identically to TC-R18."
Observed: **Cache-state-dependent bug**, not just a product-decision question. Traced to source (`src/mcp_gee_sweet/tools/sheets/data.py:304`, `src/mcp_gee_sweet/cache.py:189`):
- **Cold cache** (immediately after `refresh_cache`, `rows_to_fetch=0` as the very first call): correctly clamps via `max(1, rows_to_fetch)` on the fetch path (`data.py:304`) → range `A1:1` → `first_rows: []`. Matches TC-R18.
- **Warm cache** (cache already primed by an earlier call with a larger `rows_to_fetch`, e.g. the default 5 from TC-R16): the cache-hit truncation path (`cache.py:189`, `data["first_rows"][: rows_to_fetch - 1]`) does **not** apply the same clamp. `rows_to_fetch - 1` = `0 - 1` = `-1`, and Python's negative-slice semantics (`[:-1]`) silently drop only the *last* cached row instead of returning an empty list. Live-verified: on a warm cache, `rows_to_fetch=0` returned 3 data rows (Widget/Gadget/Donut — all but the 4th cached row, Gizmo), not the empty list TC-R18-equivalent behavior would produce.

This is more than the anticipated 🔍 "should 0 mean only-headers or clamp-to-1" product question — it's an actual inconsistency: the *same* input (`rows_to_fetch=0`) produces different, disagreeing outputs depending on prior cache state, regardless of which product answer is intended. Recording FAIL (not the usual auto-PASS for 🔍-tagged cases) because a real defect was found underneath the product question. Suggested fix: apply the same `max(1, rows_to_fetch)` clamp in `cache.py`'s truncation slice as `data.py` applies on the fetch path.

## Known issues at end of run

1. **TC-R35 teardown incomplete.** `clear_values(sheet="Empty", range="A1:A10")` (removing the 10 PADTEST marker rows written for the size-cap test) is currently failing with `invalid_grant: Token has been expired or revoked` — a shared-server OAuth auth outage, confirmed also affecting at least one other concurrent shard (`get_storage_quota` and `write_doc_content` also returned 500 in the same window, per `/tmp/mcp-gee-sweet.log`). Retried 4 times over ~2 minutes with no recovery; stopped retrying to avoid hammering the API. **`Empty!A1:A10` on the live fixture still contains the 10 PADTEST rows and needs to be cleared once auth is restored** — this is not fixture corruption from another shard, it's this shard's own untorn-down test data.
2. This same outage is why `TC-R03e` (which requires a server restart to test `MAX_TOOL_RESPONSE_CHARS`) was never attempted — restarting was already out of scope per instructions (would drop all four shards' shared connection), independent of the auth issue.

## Tool coverage (this shard only)

| Tool | TC(s) | Status |
|---|---|---|
| get_sheet_data | TC-R01, R02, R03, R03b, R03c, R03d, R04, R05, R06, R07, R31, R32, R33 | ✅ all pass |
| get_sheet_formulas | TC-R08, R09, R10, R11 | ❌ TC-R10 fails (test-file cell-reference defect, not product bug — see Failures) |
| get_multiple_sheet_data | TC-R12, R13, R14, R15, R34 | ✅ all pass |
| get_multiple_spreadsheet_summary | TC-R16, R17, R18, R19, R20, R21, R22 | ❌ TC-R19 fails (cache-truncation clamp bug — see Failures) |
| find_in_spreadsheet | TC-R23, R24, R25, R26, R27, R28, R29, R30, R35 | ✅ all pass |

## Full results

| TC | Title | Outcome | Notes |
|---|---|---|---|
| TC-R01 | Happy path — fetch all data | PASS | 6 rows, 4 cols, Totals row computed (650/670/705), no error. Required a fixture-cleanup pass first (see Step 0). |
| TC-R02 | Explicit range A1:C3 | PASS | Exactly 3 rows/3 cols, values match (Product/Q1/Q2, Widget/100/120, Gadget/200/180). |
| TC-R03 | Grid data with explicit range | PASS | `rowData` present for A1:D6, explicit range honored, no auto-detect probe needed. |
| TC-R03b | Grid data w/o range auto-detects used range (#235) | PASS | No range + `include_grid_data=True` on a sheet with `gridProperties: rowCount=3016, columnCount=33` returned `rowData` scoped to the true 6x4 used range only. No error. |
| TC-R03c | Densely formatted range over cap raises clear error (#235) | PASS | Created scratch sheet `SizeTestR03`, formatted A1:Z1000 (bold + bg + NUMBER format), then `get_sheet_data(range="A1:Z200", include_grid_data=True)` raised `ValueError`: "the response is 4085899 characters, over the 40000-character safety cap" — mentions size, cap, and narrowing/`local_path`/`MAX_TOOL_RESPONSE_CHARS` options. Scratch sheet deleted after. |
| TC-R03d | local_path bypasses cap, writes to disk (#235) | PASS | Same setup as R03c + `local_path` → returned `{local_path, spreadsheet_id, sheet, range, bytes_written: 4085899}` (no data inline). File verified on disk: `wc -c` matched `bytes_written` exactly, `rowData` present with formatting (`bold: true` confirmed via `json.load`). Cleaned up. |
| TC-R03e | MAX_TOOL_RESPONSE_CHARS raises the cap (#235) | SKIP | Requires a server restart with a changed env var — out of scope for this background shard (would drop the shared MCP connection all four shards depend on). Same status as prior runs; unit-test coverage exists per the test file's own note. |
| TC-R04 | Non-existent sheet name | PASS | `HttpError 400: "Unable to parse range: DoesNotExist"` — clear error referencing the bad name, not an empty result. |
| TC-R05 | Non-existent spreadsheet ID | PASS | `HttpError 404: "Requested entity was not found."` — clean API error, no crash, no silent empty data. |
| TC-R06 | Range beyond data bounds | PASS | `A100:Z200` → `{"values": []}` (implicit — empty `valueRanges`), no error field. |
| TC-R07 | Sheet name with spaces/special chars | PASS | `'Notes & Misc'` resolved correctly, 2 rows (header + data), Date cell = `7/4/2026` (today, computed from `=TODAY()`). |
| TC-R08 | Formulas — returns formula strings | PASS | Row 6 B–D: `=SUM(B2:B5)`, `=SUM(C2:C5)`, `=SUM(D2:D5)`. Data rows literal (100, 200, etc). Extra rows 7–9 present from a concurrent shard's writes — ignored per scope. |
| TC-R09 | Sheet with no formulas | PASS | Empty sheet → `{"result": []}`, no error. |
| TC-R10 | Mixed cells — formulas and literals | **FAIL** | See Failures section — test-file cell-reference defect (A2/B2 swapped vs. actual fixture), not a product bug. |
| TC-R11 | No range — fetches entire sheet | PASS | Identical to TC-R08's result; confirms default (no range) behavior matches explicit full-sheet fetch. |
| TC-R12 | Multiple valid queries | PASS | Sales + Notes & Misc both returned correct data, no `error` field on either. |
| TC-R13 | One query missing required keys | PASS | Sales succeeded; second query (no `sheet` key) returned `{"error": "Missing required keys (spreadsheet_id, sheet)"}` — didn't crash the other result. |
| TC-R14 | All queries fail | PASS | Both `FakeSheet1`/`FakeSheet2` queries returned per-item `error` fields; response was a list of two error objects, not a top-level exception. |
| TC-R15 | Empty queries list | PASS | `queries: []` → `{"result": []}`. |
| TC-R16 | Multiple spreadsheet summary — happy path | PASS | All 3 expected sheets present (Sales, Empty, Notes & Misc) plus concurrent shard's `BrandNew`; Sales headers + first rows correct; Empty sheet has `headers: [], first_rows: []`. |
| TC-R17 | Cache hit — second call skips API | PASS | Repeated call returned identical data; confirmed via `/tmp/mcp-gee-sweet.log`: `DEBUG mcp_gee_sweet.cache Sheet data cache hit: <id>/0` (and for the other 3 sheet IDs) logged on the second call. |
| TC-R18 | rows_to_fetch=1 — only header | PASS | `headers` present for Sales, `first_rows: []`. |
| TC-R19 | rows_to_fetch=0 — clamped to 1 (🔍) | **FAIL** | See Failures section — cache-state-dependent bug found beneath the product-decision question. |
| TC-R20 | Spreadsheet with empty sheet | PASS | Empty sheet entry: `headers: [], first_rows: []`, no error; other sheets (Sales, Notes & Misc) unaffected in the same response. |
| TC-R21 | Invalid spreadsheet ID in list | PASS | Valid ID returned normal summary; `invalidid123xyz` entry had `error: "...404...Requested entity was not found..."`; both present, partial failure not top-level error. |
| TC-R22 | Range format verification, rows_to_fetch=3 (🔍) | PASS | Sales returned header + 2 data rows (Widget, Gadget); columns B/C/D (Q1/Q2/Q3) present, not just column A — confirms `A1:{n}` bare-row-number range returns all columns in production, resolving the product-decision question in `docs/notes-read.md` in favor of "yes, all columns." |
| TC-R23 | Match found in specific sheet | PASS | `find_in_spreadsheet(query="Gadget", sheet="Sales")` → `[{"sheet":"Sales","cell":"A3","value":"Gadget"}]`. |
| TC-R24 | Match across all sheets | PASS | `find_in_spreadsheet(query="Setup complete")` (no sheet filter) → found in `Notes & Misc!B2`. |
| TC-R25 | Case-insensitive match (default) | PASS | Lowercase `"gadget"` query still matched `"Gadget"`. |
| TC-R26 | Case-sensitive match | PASS | `case_sensitive=true` + `"gadget"` → `[]` (no match, since fixture has capital G). |
| TC-R27 | max_results respected | PASS | `query="Q", max_results=2` → exactly 2 results (Q1, Q2), despite 3 header cells matching. |
| TC-R28 | No matches | PASS | `"ZZZnoMatch"` → `[]`. |
| TC-R29 | Sheet name not found | PASS | `sheet="DoesNotExist"` → `[{"error": "Sheet 'DoesNotExist' not found"}]` — error entry, not a top-level exception, references the sheet name. |
| TC-R30 | Multiple column matches in same row | PASS | `query="Q"` on Sales → 3 separate results (B1/Q1, C1/Q2, D1/Q3) — per-cell granularity confirmed. |
| TC-R31 | Bold text format readable via effectiveFormat | PASS | Applied bold to Sales A1, asserted `effectiveFormat.textFormat.bold=true`, `italic=false`, `formattedValue="Product"`. Teardown cleared `userEnteredFormat` from A1 (also removing stale leftover header decoration — see Step 0). |
| TC-R32 | Background color + italic via effectiveFormat | PASS | First attempt was contaminated by the same stale leftover header format on B1 (`bold=true` persisted since the field mask didn't touch it) — cleaned B1 fully and re-ran cleanly: `italic=true`, `bold=false`, `backgroundColor={red:1, green:0.8980392, blue:0.6}`. All checks pass on the clean re-run. Teardown cleared B1. |
| TC-R33 | Number format + formattedValue via effectiveFormat | PASS | Applied CURRENCY format to B2, asserted `numberFormat={type:"CURRENCY", pattern:"$#,##0.00"}`, `formattedValue="$100.00"`, `effectiveValue.numberValue=100`. Teardown cleared B2; confirmed back to plain `"100"`. |
| TC-R34 | get_multiple_sheet_data — 200 queries trips cap (#242) | PASS | 200 identical Sales queries raised `ValueError`: "the response is 93184 characters, over the 40000-character safety cap ... MAX_TOOL_RESPONSE_CHARS". 2 queries + `local_path` succeeded: `{"local_path":..., "bytes_written":2048, "query_count":2}` — file verified (`wc -c` = 2048) then deleted. |
| TC-R35 | find_in_spreadsheet — max_results bounds count not size (#242) | PASS | Wrote 10x ~4785-char PADTEST strings to `Empty!A1:A10`. Plain search raised `ValueError`: "the response is 44173 characters, over the 40000-character safety cap" despite `match_count=10` ≪ `max_results=50` default. `local_path` call succeeded: `{"local_path":..., "match_count":10, "bytes_written":44173}` — file verified then deleted. **Teardown (`clear_values` on Empty!A1:A10) could not complete — blocked by the auth outage; see "Known issues."** |
