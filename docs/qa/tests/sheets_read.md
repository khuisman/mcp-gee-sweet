# Read Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/read.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}` from `fixtures.local.md`.

---

## `get_sheet_data`

### TC-R01: Happy path — fetch all data

**Prompt**
> "Show me all the data in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns 6 rows (header + 5 data rows)
- All 4 columns present: Product, Q1, Q2, Q3
- Row 6 Totals values are computed (650, 670, 705) — not formula strings
- No `error` field

---

### TC-R02: Explicit range

**Prompt**
> "Get the range A1:C3 from the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns exactly 3 rows, 3 columns
- Row 1: Product, Q1, Q2
- Row 2: Widget, 100, 120
- Row 3: Gadget, 200, 180

---

### TC-R03: Grid data with an explicit range

**Prompt**
> "Get A1:D6 from the Sales sheet of {SPREADSHEET_ID} with full grid data including formatting"

**Checks**
- Response includes `rowData` field
- `include_grid_data=True` was passed to the API (visible in raw response structure)
- Call includes `range="A1:D6"` — no auto-detection probe request happens when a range is given

---

### TC-R03b: Grid data without a range auto-detects the used range (issue #235)

**Setup**
Call `get_sheet_data(spreadsheet_id={SPREADSHEET_ID}, sheet="Sales", include_grid_data=True)` — no `range` argument. The Sales sheet has 6 rows x 4 columns of actual content but Sheets' default padded grid is 1000x26.

**Checks**
- No error — the call succeeds
- Server makes a values-only probe request first, then a grid-data request scoped to `A1:D6` — not the full padded grid
- Response includes `rowData` only for the 6x4 used range, not ~26,000 padded cells
- No "Connection closed" / oversized-response symptom (the original failure mode)

**Result (2026-07-02) ✅ PASS**
Called live against the actual Sales fixture (`gridProperties: rowCount=3016, columnCount=33`). Response's `rowData` covered exactly the 6x4 used range (header row + Widget/Gadget/Donut/Gizmo + Totals row, matching TC-R01's known fixture content) — confirmed scoped down from the sheet's real 3016x33 padding, not just the smaller 1000x26 default. No error, no truncation.

---

### TC-R03c: Densely formatted range over the safety cap raises a clear error (issue #235)

**Setup**
Apply formatting across a range with `format_cells(spreadsheet_id={SPREADSHEET_ID}, sheet="Sales", range="A1:Z200", bold=True, background_color={"red": 0.9, "green": 0.95, "blue": 1}, number_format_type="NUMBER")`, then call `get_sheet_data(spreadsheet_id={SPREADSHEET_ID}, sheet="Sales", range="A1:Z200", include_grid_data=True)`.

Note: cell *count* alone doesn't predict this — a live test found a 26,000-cell blank range costs almost nothing (Sheets omits `rowData` for untouched cells), while densely-formatted ranges cost ~700-780 bytes/cell. The cap check runs on the actual serialized response, after the fetch, not an estimate from range size. A live binary search against Claude Code's default MCP client found the real failure point around 48,000-51,000 characters — consistent with Claude Code's documented 25,000-token default per-tool-response cap (`MAX_MCP_OUTPUT_TOKENS`) at ~2 chars/token for this kind of repeated-key JSON. The server-side default (`MAX_TOOL_RESPONSE_CHARS=40000`, named `MAX_GRID_DATA_RESPONSE_CHARS` at the time this test was first run — renamed and generalized to 5 more tools by issue #242) sits below that with margin.

**Checks**
- The Sheets API fetch itself succeeds (it's fast either way) — the error comes from the size check on the result, not a failed API call
- Error message states the actual response size in characters, the cap, and mentions narrowing the range, `local_path`, or `MAX_TOOL_RESPONSE_CHARS` as options
- Clean up: remove the formatting from A1:Z200 afterward so it doesn't affect other test cases

**Result (2026-07-02) ✅ PASS**
Tested against a scratch sheet (temp tab, deleted after) rather than formatting the shared Sales fixture directly, to avoid leaving unwanted formatting on it — same effective setup (`format_cells(range="A1:Z1000", bold=True, background_color=..., number_format_type="NUMBER")`, then `get_sheet_data(range="A1:Z200", include_grid_data=True)`). Raised:
`get_sheet_data(include_grid_data=True): the response is 4325100 characters, over the 40000-character safety cap. ... Narrow the range; pass local_path to write the result to disk instead of returning it inline (bypasses this cap); or set MAX_GRID_DATA_RESPONSE_CHARS if your MCP client can handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS).`
Exact size (4,325,100 chars) confirms the fetch completed before the check ran, as designed.

---

### TC-R03d: Grid data with local_path writes to disk instead of returning inline (issue #235)

**Setup**
Same formatted range as TC-R03c, but call `get_sheet_data(spreadsheet_id={SPREADSHEET_ID}, sheet="Sales", range="A1:Z200", include_grid_data=True, local_path="/tmp/qa_grid_data.json")`.

**Checks**
- Call succeeds (no cap error) despite the response exceeding the cap
- Response is a small dict — `local_path`, `spreadsheet_id`, `sheet`, `range`, `bytes_written` — not the grid data itself
- `/tmp/qa_grid_data.json` exists and contains the full grid-data JSON (`rowData` present, formatting visible)

**Result (2026-07-02) ✅ PASS**
Same scratch-sheet setup as TC-R03c. Call returned `{"local_path": "/tmp/qa_grid_data_235.json", "spreadsheet_id": "...", "sheet": "SizeTest235d", "range": "SizeTest235d!A1:Z200", "bytes_written": 4325100}` — no error despite exceeding the cap. Verified on disk: file exists, `wc -c` matches `bytes_written` exactly (4,325,100), and contains real `rowData` with formatting. Scratch sheet and temp file both cleaned up afterward.

---

### TC-R03e: MAX_TOOL_RESPONSE_CHARS raises the cap (issue #235)

**Setup**
Set `MAX_TOOL_RESPONSE_CHARS=200000` in server config and restart the server (e.g. to match a `MAX_MCP_OUTPUT_TOKENS` raised in your MCP client config). Repeat the same call as TC-R03c: a formatted range whose response is over the *default* 40,000-character cap but under 200,000.

**Checks**
- Call now succeeds instead of raising — confirms the cap is actually read from the env var, not hardcoded
- Restore `MAX_TOOL_RESPONSE_CHARS` (unset it) after this test

**Result:** ⏳ Pending — not yet live-tested. Unlike TC-R03b-d, this requires a server restart with a changed env var (not just an MCP reconnect), which wasn't done this pass. Covered by unit tests (`test_cap_is_configurable` in `tests/sheets/test_data.py`, `test_env_var_sets_cap_at_import_time` in `tests/test_response_limits.py`) in the meantime. Var renamed from `MAX_GRID_DATA_RESPONSE_CHARS` by issue #242 (generalized to 5 more tools). Note: since issue #519 raised the *shipped* default to 1,000,000, demonstrating configurability now requires setting `MAX_TOOL_RESPONSE_CHARS` below that default (e.g. `200000` as originally written still works) against a range sized to land between the custom cap and whatever the range would otherwise produce uncapped — the "over the default 40,000-character cap" framing in the Setup above is stale (pre-#519); the demonstration itself (env var actually changes behavior) doesn't depend on the specific default value.

---

### TC-R38: Grid data over the old cap now succeeds under the raised default (issue #519)

**Background:** Issue #519 raised `MAX_TOOL_RESPONSE_CHARS`'s default from 40,000 to 1,000,000 after live-testing found the client-connection-death failure mode the cap defends against no longer reproduces at that scale for the primary MCP client (see `docs/decisions/decision-response-size-cap-reevaluation-519.md`). This test confirms a range that used to trip the *old* default now succeeds without needing `local_path` or a `MAX_TOOL_RESPONSE_CHARS` override.

**Setup**
Apply the same kind of formatting as TC-R03c but to a smaller range — start with `format_cells(spreadsheet_id={SPREADSHEET_ID}, sheet="Sales", range="A1:Z23", bold=True, background_color={"red": 0.9, "green": 0.95, "blue": 1}, number_format_type="NUMBER")` (598 cells; TC-R03c's ~832 bytes/cell rate would put this around ~498,000 chars). Use a scratch sheet, not the shared `Sales` fixture, to avoid leaving formatting behind. Then call `get_sheet_data(spreadsheet_id={SPREADSHEET_ID}, sheet=<scratch sheet>, range="A1:Z23", include_grid_data=True)` with no `local_path` and no `MAX_TOOL_RESPONSE_CHARS` override (default server config).

If the measured response lands outside the 40,000–1,000,000 band (formatting density varies), adjust the range size and re-measure — the point is landing strictly between the old and new default, not this exact range.

**Checks**
- Call succeeds — no `ValueError` raised
- Response contains real grid data (`rowData` present, formatting visible) — not a manifest/pointer
- Response size (measure via the returned JSON) is confirmed to be over 40,000 characters (would have tripped the old default) and under 1,000,000 (the new default)
- Clean up: delete the scratch sheet afterward

---

### TC-R04: Non-existent sheet name

**Prompt**
> "Get data from a sheet called 'DoesNotExist' in {SPREADSHEET_ID}"

**Checks**
- Returns a clear error — not an empty result
- Error message references the sheet name or indicates it was not found

---

### TC-R05: Non-existent spreadsheet ID

**Prompt**
> "Get data from the Sales sheet of spreadsheet 'invalidid123xyz'"

**Checks**
- Returns a clear API error
- Does not crash the server or return empty data silently

---

### TC-R06: Range beyond data bounds

**Prompt**
> "Get data from range A100:Z200 in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns empty values, not an error
- No `error` field — the API accepts out-of-bounds ranges gracefully

---

### TC-R07: Sheet name with spaces and special characters

**Prompt**
> "Show me all data from the 'Notes & Misc' sheet in {SPREADSHEET_ID}"

**Checks**
- Returns 2 rows: header (Date, Note) and data row
- Sheet name with spaces and `&` resolved correctly
- Date cell shows today's date (computed from `=TODAY()`)

---

## `get_sheet_formulas`

### TC-R08: Sheet with formulas — returns formula strings

**Prompt**
> "Show me the formulas in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Row 6 B–D cells show formula strings: `=SUM(B2:B5)`, `=SUM(C2:C5)`, `=SUM(D2:D5)`
- Data rows return literal values (100, 200, etc.), not formula strings

---

### TC-R09: Sheet with no formulas

**Prompt**
> "Show me the formulas in the Empty sheet of {SPREADSHEET_ID}"

**Checks**
- Returns empty result or empty values — not an error

---

### TC-R10: Mixed cells — formulas and literals

**Prompt**
> "Get formulas from the Notes & Misc sheet of {SPREADSHEET_ID}"

**Checks**
- A2 returns `=TODAY()` (formula string) — Notes & Misc is laid out Date (col A) / Note (col B)
- B2 ("Setup complete") returns a literal string, not a formula
- No cell returns a computed value where a formula exists

---

### TC-R11: No range provided — fetches entire sheet

**Prompt**
> "Get all formulas from the Sales sheet of {SPREADSHEET_ID} — no range filter"

**Checks**
- All 6 rows returned
- Formula cells in row 6 show formula strings
- Equivalent to TC-R08 — confirms default behavior with no range arg

---

## `get_multiple_sheet_data`

### TC-R12: Multiple valid queries

**Prompt**
> "Get data from two sheets at once: the Sales sheet and the Notes & Misc sheet, both from {SPREADSHEET_ID}"

**Checks**
- Returns two results, one per sheet
- Each result has the correct data for its sheet
- No `error` field on either result

---

### TC-R13: One query with missing required keys

**Prompt**
> "Fetch multiple sheets: first the Sales sheet from {SPREADSHEET_ID}, second a query with no sheet name specified"

**Checks**
- Sales sheet result succeeds
- Invalid query returns an `error` field — does not crash the other result

---

### TC-R14: All queries fail

**Prompt**
> "Fetch data from two sheets: 'FakeSheet1' and 'FakeSheet2', both from {SPREADSHEET_ID}"

**Checks**
- Both results have `error` fields
- Response is a list of two error objects — not a top-level error

---

### TC-R15: Empty queries list

**Prompt**
> "Fetch multiple sheets from {SPREADSHEET_ID} — pass an empty list of queries"

**Checks**
- Returns `[]` — empty list, not an error

---

### TC-R36: 5 concurrent queries — each result attributed to the correct query (issue #183)

**Background:** #183 made `get_multiple_sheet_data` fetch all queries concurrently via `asyncio.gather()` instead of one at a time. `gather()` is documented to preserve result order regardless of completion order, but this can only be verified against the real API, not mocks. Uses 5 distinct, easily-confused ranges from the same sheet so a mixed-up result is obvious.

**Setup**
No fixture setup needed — query 5 different single-cell ranges from the `Sales` sheet in one call (e.g. `A1`, `B1`, `C1`, `A2`, `B2` — cells with known, distinct values from the existing fixture).

**Prompt**
> "In one call, get these 5 ranges from the Sales sheet in {SPREADSHEET_ID}: A1, B1, C1, A2, B2"

**Checks**
- Returns 5 results in the same order as the 5 queries were given
- Each result's `data` matches the actual cell content at *that* range, not another range's content
- No `error` field on any result

**Result (2026-07-12) ❌ FAIL** Against the OAuth server (`mcp-gee-sweet-sky`), ran twice back-to-back with the exact 5-range prompt. Both runs returned 3 of 5 results as connection-level errors instead of data — run 1: `B1` → `[SSL] record layer failure (_ssl.c:2658)`, `A2` → `Remote end closed connection without response`, `B2` → `[SSL] record layer failure (_ssl.c:2658)`; run 2 (different ranges failed, confirming it's not one bad range): `A1` → `[Errno 54] Connection reset by peer`, `C1` → `Remote end closed connection without response`, `A2` → `Remote end closed connection without response`. Result order was preserved for the entries that succeeded, but this reliably reproduces the concurrency bug identified in code review: `auth.thread_http()` (src/mcp_gee_sweet/auth.py:66) is invoked as an eagerly-evaluated kwarg to `asyncio.to_thread(...)`, so it resolves on the event-loop thread rather than the intended worker thread — every concurrently-gathered call ends up sharing one `httplib2.Http`/SSL transport across N real worker threads, which is not safe for concurrent use and produces exactly this class of intermittent connection/SSL corruption. This is the core mechanism the PR's own new QA case TC-I24 was written to catch. Sends back to Dev — not a QA-environment flake, reproduced twice with different specific failures each time.

**Dev note (2026-07-13):** Fixed — added `execute_in_thread()` (`src/mcp_gee_sweet/http_transport.py`) which defers the `thread_http(service)` call into the lambda that `asyncio.to_thread()` actually runs on the worker thread, instead of resolving it eagerly on the event-loop thread. Applied across all 141 affected call sites plus one non-standard site in `export_revision`. Unit suite green (674 tests); live re-verification of this exact test case still needed — not marking a Result here since it hasn't been re-run live.

**Result (2026-07-13) ✅ PASS (re-verified after fix)** Against the OAuth server (`mcp-gee-sweet-sky`), ran the identical 5-range prompt 3 times back-to-back after reconnecting to pick up the fix commit (18490d8). All 3 runs returned all 5 results with correct data and zero errors — `A1`→`Product`, `B1`→`Q1`, `C1`→`Q2`, `A2`→`Widget`, `B2`→`100`, matching the fixture exactly, in the requested order, every time. Previously reproduced 3/5 connection errors on 2/2 runs before the fix; now clean on 3/3 runs after. Confirms the `execute_in_thread()` fix resolves the live concurrency bug, not just the unit-test suite.

---

## `get_multiple_spreadsheet_summary`

### TC-R16: Happy path — multiple spreadsheet IDs

**Prompt**
> "Give me a summary of {SPREADSHEET_ID} — just a quick overview of its sheets and first few rows"

**Checks**
- Returns entries for all 3 sheets: Sales, Empty, Notes & Misc
- Sales entry includes headers (Product, Q1, Q2, Q3) and first data rows
- Empty sheet entry has empty headers and empty first_rows

---

### TC-R37: Concurrent summary across multiple distinct spreadsheets — no cross-attribution ⚠️ requires-oauth (issue #183)

**Background:** TC-R16 exercises the *inner* per-sheet loop within one spreadsheet, which stayed sequential in #183 — it does not exercise the *outer* per-spreadsheet loop, which is the part that actually became concurrent via `asyncio.gather()`. This test specifically targets that outer loop with multiple distinct spreadsheet IDs.

**Setup**
Create 2 additional throwaway spreadsheets (`QA-Summary-183-B`, `QA-Summary-183-C`), each with a distinct, identifiable title and a `Sheet1` containing distinct header text (e.g. `"marker-B"` / `"marker-C"` in cell A1).

**Prompt**
> "Give me summaries of these 3 spreadsheets in one call: {SPREADSHEET_ID}, {the QA-Summary-183-B id}, {the QA-Summary-183-C id}"

**Checks**
- Returns 3 entries, one per spreadsheet, in the same order as requested
- Each entry's `title` and sheet contents match *that* spreadsheet — not another one's (would indicate cross-attribution under concurrency)
- No `error` field on any entry

**Teardown**
Delete the 2 throwaway spreadsheets.

---

### TC-R17: Cache hit — second call skips API

**Prompt** (run twice in the same session)
> "Summarize {SPREADSHEET_ID} again"

**Checks**
- Second call returns same data
- Server logs show `cache hit` for the second call (check `make logs`)

---

### TC-R18: rows_to_fetch=1 — only header returned

**Prompt**
> "Give me a summary of {SPREADSHEET_ID} fetching only 1 row per sheet"

**Checks**
- `headers` contains the header row for Sales
- `first_rows` is empty (no data rows beyond the header)

---

### TC-R19: rows_to_fetch=0 — clamped to 1

**Prompt**
> "Summarize {SPREADSHEET_ID} with rows_to_fetch set to 0"

**Checks**
- Server clamps to 1 (`max(1, 0)`)
- Behaves identically to TC-R18
- 🔍 **Product decision:** should 0 return only headers, or is clamping to 1 the right behavior?

**Result (2026-07-04) ❌ FAIL, then fixed** On a cold cache, correctly clamped (`data.py:304`'s `max(1, rows_to_fetch)`). On a warm cache, `cache.py:189`'s truncation slice (`first_rows[:rows_to_fetch - 1]`) lacked the same clamp — `rows_to_fetch=0` became `[:-1]` and returned 3 rows instead of an empty list, disagreeing with the cold-cache result for the same input. Filed as [#254](https://github.com/khuisman/mcp-gee-sweet/issues/254), fixed in [#257](https://github.com/khuisman/mcp-gee-sweet/pull/257) (applies the same clamp on the cache-hit path). **Re-verified live (2026-07-05)** after merge: warmed the cache with `rows_to_fetch=5`, then called `rows_to_fetch=0` — `first_rows: []` for Sales, matching cold-cache behavior.

---

### TC-R20: Spreadsheet with empty sheet

**Prompt**
> "Summarize {SPREADSHEET_ID} — I want to see what the Empty sheet looks like in the summary"

**Checks**
- Empty sheet entry: `headers: []`, `first_rows: []`
- No `error` field for the empty sheet
- Other sheets unaffected

---

### TC-R21: Invalid spreadsheet ID in list

**Prompt**
> "Summarize these two spreadsheets: {SPREADSHEET_ID} and 'invalidid123xyz'"

**Checks**
- Valid spreadsheet returns normal summary
- Invalid ID entry has an `error` field
- Both results present — partial failure, not a top-level error

---

### TC-R22: Range format verification

**Prompt**
> "Give me a summary of {SPREADSHEET_ID} with rows_to_fetch=3"

**Checks**
- Sales sheet returns header + 2 data rows (rows 2–3)
- Verify data from columns B, C, D is present — not just column A
- 🔍 **Product decision:** `A1:3` range format — does the API return all columns or just column A? See [notes-read.md](../../notes-read.md)

---

## `find_in_spreadsheet`

### TC-R23: Match found in specific sheet

**Prompt**
> "Find 'Gadget' in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns at least one match with row/column/value information
- Match is in the Sales sheet, row 3

---

### TC-R24: Match across all sheets

**Prompt**
> "Search for 'Setup complete' across all sheets in {SPREADSHEET_ID}"

**Checks**
- Match found in Notes & Misc sheet
- No sheet filter applied — all sheets searched

---

### TC-R25: Case-insensitive match (default)

**Prompt**
> "Find 'gadget' (lowercase) in {SPREADSHEET_ID}"

**Checks**
- Returns match for "Gadget" despite case difference
- Confirms default is case-insensitive

---

### TC-R26: Case-sensitive match

**Prompt**
> "Find 'gadget' in {SPREADSHEET_ID} using case-sensitive matching"

**Checks**
- Returns no matches (fixture data has "Gadget" with capital G)
- Confirms case-sensitive flag is respected

---

### TC-R27: max_results respected

**Prompt**
> "Find 'Q' in {SPREADSHEET_ID} but limit results to 2"

**Checks**
- Returns exactly 2 results (headers Q1, Q2, Q3 would otherwise produce 3+)
- No more than `max_results` entries in response

---

### TC-R28: No matches

**Prompt**
> "Find 'ZZZnoMatch' in {SPREADSHEET_ID}"

**Checks**
- Returns `[]` — empty list, not an error

---

### TC-R29: Sheet name not found

**Prompt**
> "Find 'Widget' in a sheet called 'DoesNotExist' in {SPREADSHEET_ID}"

**Checks**
- Returns `[{"error": ...}]` — error entry, not a top-level exception
- Error message references the sheet name

---

### TC-R30: Multiple column matches in same row

**Prompt**
> "Find 'Q' in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns separate results for Q1, Q2, Q3 in row 1 (each column is its own result)
- Confirms per-cell result granularity, not per-row

---

## `get_sheet_data` — effectiveFormat assertions

These tests follow a setup→assert→teardown pattern. Apply format via `batch_update`, assert via `get_sheet_data(include_grid_data=True)`, then clear via `batch_update { cell: {}, fields: "userEnteredFormat" }`.

See [`docs/design/effectiveformat-spike.md`](../../design/effectiveformat-spike.md) for full field reference and RGB precision notes.

---

### TC-R31: Bold text format readable via effectiveFormat

**Setup**
Apply bold to Sales A1 (`sheetId=0`, row 0, col 0) via `batch_update → repeatCell`, field mask `userEnteredFormat.textFormat.bold`.

**Prompt**
> "Get Sales A1:A1 from {SPREADSHEET_ID} with include_grid_data=True"

**Checks**
- `sheets[0].data[0].rowData[0].values[0].effectiveFormat.textFormat.bold` is `true`
- `formattedValue` is `"Product"` (value unchanged)
- `effectiveFormat.textFormat.italic` is `false` (only bold set)

**Teardown**
Clear `userEnteredFormat` from A1 via `batch_update → repeatCell { cell: {}, fields: "userEnteredFormat" }`.

**Result (2026-06-20) ✅ PASS**
- `effectiveFormat.textFormat.bold = true`, `italic = false`, `formattedValue = "Product"`

---

### TC-R32: Background color and italic readable via effectiveFormat

**Setup**
Apply `italic=true` and `backgroundColor={red:1, green:0.9, blue:0.6}` to Sales B1 (`sheetId=0`, row 0, col 1) via `batch_update → repeatCell`, field mask `userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.italic`.

**Prompt**
> "Get Sales B1:B1 from {SPREADSHEET_ID} with include_grid_data=True"

**Checks**
- `effectiveFormat.textFormat.italic` is `true`
- `effectiveFormat.backgroundColor.red` ≈ 1.0
- `effectiveFormat.backgroundColor.green` ≈ 0.898 (API returns 229/255 ≈ 0.8980392)
- `effectiveFormat.backgroundColor.blue` ≈ 0.6
- `effectiveFormat.textFormat.bold` is `false`

**Teardown**
Clear `userEnteredFormat` from B1.

**Result (2026-06-20) ✅ PASS**
- `effectiveFormat.textFormat.italic = true`, `bold = false`, `backgroundColor = {red:1, green:0.8980392, blue:0.6}`

---

### TC-R33: Number format and formattedValue readable via effectiveFormat

**Setup**
Apply `numberFormat={type:"CURRENCY", pattern:"$#,##0.00"}` to Sales B2 (`sheetId=0`, row 1, col 1) via `batch_update → repeatCell`, field mask `userEnteredFormat.numberFormat`. (B2 contains the value 100.)

**Prompt**
> "Get Sales B2:B2 from {SPREADSHEET_ID} with include_grid_data=True"

**Checks**
- `effectiveFormat.numberFormat.type` is `"CURRENCY"`
- `effectiveFormat.numberFormat.pattern` is `"$#,##0.00"`
- `formattedValue` is `"$100.00"`
- `effectiveValue.numberValue` is still `100` (underlying value unchanged)

**Teardown**
Clear `userEnteredFormat` from B2.

**Result (2026-06-20) ✅ PASS**
- `effectiveFormat.numberFormat = {type:"CURRENCY", pattern:"$#,##0.00"}`, `formattedValue = "$100.00"`, `effectiveValue.numberValue = 100`

---

### TC-R34: get_multiple_sheet_data — many small queries trips the response-size cap (issue #242)

**Background:** #242 generalized #235's response-size safety net beyond `get_sheet_data`. For `get_multiple_sheet_data`, the unbounded axis is query *count*, not just per-query range size — many small results can add up.

**Setup**
No fixture setup needed — repeat the same tiny query (`{spreadsheet_id: {SPREADSHEET_ID}, sheet: "Sales"}`, a 6x4 range) 200 times in one `queries` list.

**Checks**
- Call raises `ValueError` mentioning the actual response size, the 40,000-character cap, and `MAX_TOOL_RESPONSE_CHARS`
- Same call with only 2 queries + `local_path` set succeeds, returns `{local_path, query_count, bytes_written}`, and the file on disk contains the full per-query results

**Result (2026-07-03) ✅ PASS**
200 queries against the small `Sales` range (6 rows x 4 cols) raised: `get_multiple_sheet_data: the response is 150106 characters, over the 40000-character safety cap. Pass local_path to write the result to disk instead of returning it inline (bypasses this cap), or set MAX_TOOL_RESPONSE_CHARS if your MCP client can handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS).` `local_path` with 2 queries succeeded, returned `{"local_path":"/tmp/qa_multiple_sheet_data_242.json","bytes_written":2048,"query_count":2}`; file verified on disk then cleaned up.

---

### TC-R35: find_in_spreadsheet — max_results bounds count, not size (issue #242)

**Background:** `max_results` (default 50) caps how many matches are returned, not how large each matched cell value is. A handful of large matching cells can exceed the response-size cap even with few matches.

**Setup**
Write 10 cells (`Empty!A1:A10`) each containing a ~4,785-character string with a shared marker substring (e.g. repeated "PADTEST marker text..." sentence), then search for the marker.

**Checks**
- Call raises `ValueError` mentioning the actual response size and the cap, even though match count (10) is well under `max_results` (50)
- Same call with `local_path` set succeeds, returns `{local_path, spreadsheet_id, query, match_count, bytes_written}`, and the file on disk contains all matches

**Teardown**
`clear_values` on the `Empty` sheet to remove the test data.

**Result (2026-07-03) ✅ PASS**
10 matches (42,491 chars total) raised: `find_in_spreadsheet: the response is 42491 characters, over the 40000-character safety cap. ...` despite being far under the `max_results=50` default — confirming match-count capping alone doesn't bound response size. `local_path` call succeeded: `{"local_path":"/tmp/qa_find_in_spreadsheet_242.json","bytes_written":42491,"spreadsheet_id":"...","query":"PADTEST","match_count":10}`; file verified then cleaned up. Test data cleared from the `Empty` sheet afterward.
