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

### TC-R03: Grid data with formatting

**Prompt**
> "Get A1:D6 from the Sales sheet of {SPREADSHEET_ID} with full grid data including formatting"

**Checks**
- Response includes `rowData` field
- `include_grid_data=True` was passed to the API (visible in raw response structure)
- Call includes `range="A1:D6"` — as of issue #235, `include_grid_data=True` requires a range

---

### TC-R03b: Grid data without a range raises a validation error (issue #235)

**Setup**
Call `get_sheet_data(spreadsheet_id={SPREADSHEET_ID}, sheet="Sales", include_grid_data=True)` — no `range` argument.

**Checks**
- Call raises/returns an error before any Sheets API request is made — not a silent full-grid fetch
- Error message mentions that `range` is required when `include_grid_data=True`
- No "Connection closed" / oversized-response symptom (the original failure mode)

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
- B2 returns `=TODAY()` (formula string)
- B1 ("Note") returns literal string
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

## `get_multiple_spreadsheet_summary`

### TC-R16: Happy path — multiple spreadsheet IDs

**Prompt**
> "Give me a summary of {SPREADSHEET_ID} — just a quick overview of its sheets and first few rows"

**Checks**
- Returns entries for all 3 sheets: Sales, Empty, Notes & Misc
- Sales entry includes headers (Product, Q1, Q2, Q3) and first data rows
- Empty sheet entry has empty headers and empty first_rows

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
