# Sheet Management Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/sheets.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}` from `fixtures.local.md`.

Tests marked **⚠️ destructive** rename or delete sheets — reset fixtures afterward.

---

## `list_sheets`

### TC-S01: Happy path

**Prompt**
> "List all the sheets in {SPREADSHEET_ID}"

**Checks**
- Returns 3 tabs: Sales, Empty, Notes & Misc
- Each entry includes the sheet name
- No `error` field

---

### TC-S02: Cache hit on second call

**Prompt** (run twice in the same session)
> "List the sheets in {SPREADSHEET_ID} again"

**Checks**
- Second call returns the same list
- Server logs show `cache hit` for the second call (`make logs`)

---

### TC-S03: Cache invalidated after rename

**Prompt**
> "Rename the 'Empty' sheet in {SPREADSHEET_ID} to 'WasEmpty', then immediately list all sheets"

**Checks**
- `list_sheets` response includes 'WasEmpty', not 'Empty'
- Confirms `cache.mark_dirty` fires after rename and the next list re-fetches

---

## `copy_sheet`

### TC-S04: Copy within same spreadsheet

**Prompt**
> "Copy the Sales sheet within {SPREADSHEET_ID} and name the copy 'Sales Copy'"

**Checks**
- New sheet 'Sales Copy' appears in {SPREADSHEET_ID}
- Data in 'Sales Copy' matches Sales (6 rows, 4 columns)
- Original Sales sheet unchanged

---

### TC-S05: Copy to a different spreadsheet

**Prompt**
> "Copy the Sales sheet from {SPREADSHEET_ID} into a different spreadsheet — use {SPREADSHEET_ID} as both source and destination for this test, but note the tool supports different IDs"

**Checks**
- Tool accepts `src_spreadsheet` and `dst_spreadsheet` as separate params
- Copy operation completes without error
- 🔍 **Note:** requires a second spreadsheet ID to fully verify cross-spreadsheet copy

---

### TC-S06: Name differs from Google's auto-assigned name — rename triggered

**Prompt**
> "Copy the Sales sheet in {SPREADSHEET_ID} and name the copy 'My Custom Name'"

**Checks**
- Sheet is named 'My Custom Name', not Google's default 'Copy of Sales'
- Rename was triggered automatically after the copy

---

### TC-S07: Name matches Google's auto-assigned name — rename skipped

**Prompt**
> "Copy the Sales sheet in {SPREADSHEET_ID} and name the copy 'Copy of Sales'"

**Checks**
- Sheet is named 'Copy of Sales'
- No unnecessary rename API call (names already match)

---

### TC-S08: Source sheet not found

**Prompt**
> "Copy a sheet called 'DoesNotExist' from {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` before calling the copy API
- Error references the missing sheet name

---

### TC-S09: Destination spreadsheet not writable

**Prompt**
> "Copy the Sales sheet from {SPREADSHEET_ID} to spreadsheet 'invalidid123xyz'"

**Checks**
- Returns a clear API error — destination not accessible
- Source spreadsheet unaffected

---

### TC-S10: Cache invalidated after copy ⚠️ destructive

**Prompt**
> "Copy the Sales sheet in {SPREADSHEET_ID} as 'PostCopyCache', then immediately list all sheets"

**Checks**
- `list_sheets` includes 'PostCopyCache'
- Confirms `cache.mark_dirty(dst_spreadsheet)` fires after copy

---

## `duplicate_sheet`

### TC-S51: Duplicate within the same spreadsheet, default name ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- New tab appears, named by Google's default (e.g. "Copy of Sales")
- Data in the new tab matches Sales (6 rows, 4 columns)
- Original Sales sheet unchanged
- Response includes `sheetId`, `title`, `index`, `spreadsheetId`

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales")` → `{"sheetId":1766233601,"title":"Copy of Sales","index":1,...}`. `get_sheet_data` on "Copy of Sales" returned matching headers/rows. Deleted after verification.

---

### TC-S52: Duplicate with a custom name ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID} and name the copy 'Sales Duplicate'"

**Checks**
- New tab is named 'Sales Duplicate', not Google's default
- `newSheetName` was passed on the same `duplicateSheet` request (single API call, no follow-up rename)

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales", new_name="Sales Duplicate")` → title `"Sales Duplicate"`, confirmed via code that `newSheetName` is set on the same request body as `sourceSheetId`. Deleted after verification.

---

### TC-S53: Default position lands immediately after the source tab ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID} without specifying a position, then list all sheets"

**Checks**
- The new tab appears immediately after 'Sales' in the `list_sheets` response order
- 🔍 **Regression:** the Sheets API's own default for `duplicateSheet` places the copy at tab position 0 regardless of source position (confirmed via live QA on this tool) — the tool must compute and pass `insertSheetIndex` explicitly to land the copy after the source, matching Sheets UI's native "Duplicate" behavior

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales")` → index 1. `list_sheets` → `["Sales","Copy of Sales","Empty","Notes & Misc","BrandNew"]` — lands immediately after Sales, confirming the regression fix (`_get_sheet_index` + explicit `insertSheetIndex`). Deleted after verification.

---

### TC-S54: Explicit insert_index is honored ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID}, placing the copy at tab position 0"

**Checks**
- The new tab is the first tab in the `list_sheets` response order
- Confirms an explicit `insert_index` overrides the "after source" default

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales", insert_index=0)` → index 0. `list_sheets` → `["Copy of Sales","Sales",...]` — explicit index correctly overrides the default. Deleted after verification.

---

### TC-S55: Source sheet not found

**Prompt**
> "Duplicate a sheet called 'DoesNotExist' in {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` before calling the duplicate API
- Error references the missing sheet name

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="DoesNotExist")` → `{"error": "Sheet 'DoesNotExist' not found"}`. No mutation, non-destructive.

---

### TC-S56: Cache invalidated after duplicate ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID} as 'PostDuplicateCache', then immediately list all sheets"

**Checks**
- `list_sheets` includes 'PostDuplicateCache'
- Confirms `cache.mark_dirty(spreadsheet_id)` fires after duplicate

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales", new_name="PostDuplicateCache")` succeeded; immediate `list_sheets` (no explicit `refresh_cache`) included `"PostDuplicateCache"`, confirming `mark_dirty` fired. Deleted after verification; fixture restored to `["Sales","Empty","Notes & Misc","BrandNew"]`.

---

## `rename_sheet`

### TC-S11: Rename to a new name ⚠️ destructive

**Prompt**
> "Rename the 'Empty' sheet in {SPREADSHEET_ID} to 'Renamed'"

**Checks**
- Sheet formerly called 'Empty' is now 'Renamed'
- `list_sheets` reflects the new name
- No `error` field

---

### TC-S12: Rename to the same name

**Prompt**
> "Rename the 'Sales' sheet in {SPREADSHEET_ID} to 'Sales' (same name)"

**Checks**
- API succeeds or no-ops — no error
- Sheet still exists with the same name
- 🔍 **Product decision:** is a same-name rename a no-op or does it round-trip to the API?

---

### TC-S13: Sheet not found

**Prompt**
> "Rename a sheet called 'NoSuchSheet' in {SPREADSHEET_ID} to 'Anything'"

**Checks**
- Returns `{"error": ...}` — sheet not found
- Does not call the Sheets API

---

### TC-S14: Cache invalidated after rename

**Prompt**
> "Rename 'Notes & Misc' to 'Notes' in {SPREADSHEET_ID}, then list all sheets"

**Checks**
- `list_sheets` shows 'Notes', not 'Notes & Misc'
- Confirms `cache.mark_dirty` fires; next list re-fetches from API

---

## `create_sheet`

### TC-S15: Create a new tab

**Prompt**
> "Add a new sheet called 'BrandNew' to {SPREADSHEET_ID}"

**Checks**
- New tab 'BrandNew' appears
- Response includes `sheetId`, `title`, `index`, `spreadsheetId`
- `cache.mark_dirty` called — `list_sheets` reflects the new tab

---

### TC-S16: Duplicate tab title

**Prompt**
> "Add another sheet called 'Sales' to {SPREADSHEET_ID} — a tab with that name already exists"

**Checks**
- 🔍 **Product decision:** does the API error, auto-suffix (e.g. "Sales2"), or succeed with a duplicate?
- Note observed behavior

---

### TC-S17: Long title

**Prompt**
> "Add a sheet with a 150-character title to {SPREADSHEET_ID}"

**Checks**
- API error with a clear message about title length limits, or succeeds if no limit enforced
- Note the actual limit if an error is returned

---

### TC-S18: Response shape

**Prompt**
> "Create a sheet called 'ShapeTest' in {SPREADSHEET_ID} and show me the full response"

**Checks**
- Response includes: `sheetId` (integer), `title` (string), `index` (integer), `spreadsheetId` (string)
- No unexpected missing fields

---

### TC-S19: Cache updated after create

**Prompt**
> "Create a sheet called 'CacheNewSheet' in {SPREADSHEET_ID}, then list all sheets"

**Checks**
- `list_sheets` includes 'CacheNewSheet' immediately
- Confirms `cache.mark_dirty` fires after creation

---

## `refresh_cache`

### TC-S20: Refresh by spreadsheet ID only

**Prompt**
> "Refresh the cache for {SPREADSHEET_ID}"

**Checks**
- Returns success
- Next `list_sheets` or summary call hits the API (visible in logs as a cache miss)

---

### TC-S21: Refresh by doc ID only

**Prompt**
> "Refresh the cache for doc {DOC_ID}"

**Checks**
- Returns success
- Next `get_doc_content` call re-fetches from API

---

### TC-S22: Refresh both spreadsheet and doc

**Prompt**
> "Refresh the cache for both {SPREADSHEET_ID} and doc {DOC_ID}"

**Checks**
- Both caches marked dirty
- Subsequent calls for both re-fetch from API

---

### TC-S23: Refresh with no arguments — clears all caches

**Prompt**
> "Clear all caches in mcp-gee-sweet"

**Checks**
- All four caches marked dirty (structure, data, Drive folder, doc)
- Next calls for any resource re-fetch from API

---

### TC-S24: Cache re-populated after refresh

**Prompt**
> "Refresh the cache for {SPREADSHEET_ID}, then immediately summarize it"

**Checks**
- Summary returns correct data (re-fetched, not stale)
- Logs show a cache miss followed by a cache store

---

## `delete_sheet`

### TC-S25: Delete an existing sheet tab ⚠️ destructive

**Prompt**
> "Delete the sheet called 'TempTab' from {SPREADSHEET_ID}"

**Setup:** Create a throwaway tab called 'TempTab' first.

**Checks**
- 'TempTab' no longer appears in `list_sheets`
- No `error` field in response

**Result (2026-06-21) ✅** TempTab created via `create_sheet`, then deleted. `list_sheets` returned `["Sales","Empty","Notes & Misc"]` — TempTab absent. No error field.

---

### TC-S26: Delete a non-existent sheet returns error

**Prompt**
> "Delete a sheet called 'DoesNotExist' from {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field mentioning the sheet name
- No API call made (no batchUpdate)

**Result (2026-06-21) ✅** Response: `{"error":"Sheet 'DoesNotExist' not found"}`. No batchUpdate issued.

---

## `delete_rows`

### TC-S27: Delete a single row ⚠️ destructive

**Prompt**
> "Delete row 5 (0-based index 4) from the Sales sheet in {SPREADSHEET_ID}"

**Setup:** Confirm rows 4 and 5 (0-based) have known values before deleting.

**Checks**
- Former row 5 content is gone; row 5 now contains what was row 6
- Other rows unchanged

**Result (2026-06-21) ✅** Row 4 (Gizmo/300/310/290) deleted. Former row 5 (Totals) shifted up. Totals recalculated to 350/360/415 reflecting the reduced data set.

---

### TC-S28: Delete a range of rows ⚠️ destructive

**Prompt**
> "Delete rows 3 through 5 (0-based indices 2–4) from the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Three rows removed; subsequent rows shift up correctly
- `startIndex: 2`, `endIndex: 5` in the deleteDimension request

**Result (2026-06-21) ✅** Rows 2–4 (Gadget/Donut/Gizmo) removed. Widget and Totals remain; Totals recalculated to 100/120/140 (Widget only).

---

### TC-S29: Delete rows — sheet not found returns error

**Prompt**
> "Delete row 0 from a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-06-21) ✅** Response: `{"error":"Sheet 'NoSuchSheet' not found"}`.

---

## `delete_columns`

### TC-S30: Delete a single column ⚠️ destructive

**Prompt**
> "Delete column B (0-based index 1) from the Sales sheet in {SPREADSHEET_ID}"

**Setup:** Confirm column B has known content before deleting.

**Checks**
- Column B content removed; former column C shifts left to become B
- `dimension: COLUMNS`, `startIndex: 1`, `endIndex: 2`

**Result (2026-06-21) ✅** Column index 1 (Q1) deleted. Q2 and Q3 shifted left. Totals recalculated to 670/705 (Q2+Q3 only).

---

### TC-S31: Delete a range of columns ⚠️ destructive

**Prompt**
> "Delete columns C through E (0-based indices 2–4) from the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Three columns removed; columns to the right shift left
- `startIndex: 2`, `endIndex: 5`

**Result (2026-06-21) ✅** Column indices 2–3 (Q2 and Q3) deleted (only 4 cols exist so effective range was 2–3). Only Product and Q1 remained. Inclusive end index correctly translated to exclusive endIndex in API call.

---

### TC-S32: Delete columns — sheet not found returns error

**Prompt**
> "Delete column 0 from a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-06-21) ✅** Response: `{"error":"Sheet 'NoSuchSheet' not found"}`.

---

## `format_cells`

### TC-S33: Apply bold and background color to a range ⚠️ destructive

**Prompt**
**Playwright: required**
> "Make cells A1:D1 on the Sales sheet bold with a light blue background"

**Checks**
- `repeatCell` request sent with `textFormat.bold=true`
- `backgroundColor` set to the specified color
- `fields` mask includes both `userEnteredFormat.textFormat` and `userEnteredFormat.backgroundColor`
- No error in response

**Result (2026-06-21) ✅** A1:D1 on Sales formatted bold with light blue background. `replies: [{}]` — no error.

---

### TC-S34: Apply number format to a column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Format column B (B2:B100) on Sales as currency with 2 decimal places"

**Checks**
- `numberFormat.type` is `"CURRENCY"` (or `"NUMBER"` with pattern)
- `numberFormat.pattern` applied
- `fields` includes `userEnteredFormat.numberFormat`

**Result (2026-06-21) ✅** B2:B6 on Sales formatted NUMBER with pattern `#,##0.00`. `replies: [{}]` — no error.

---

### TC-S35: Set horizontal alignment ⚠️ destructive

**Prompt**
**Playwright: required**
> "Center-align cells A1:F1 on the Sales sheet"

**Checks**
- `horizontalAlignment` is `"CENTER"`
- `fields` includes `userEnteredFormat.horizontalAlignment`

**Result (2026-06-21) ✅** A1:D1 on Sales center-aligned. `replies: [{}]` — no error.

---

### TC-S36: No formatting params returns error

**Checks (unit test)**
- Calling `format_cells` with no formatting params returns `{"error": ...}`
- No batchUpdate API call made

**Result (2026-06-21) ✅** Unit test confirms error returned and batchUpdate not called.

---

### TC-S37: format_cells — sheet not found returns error

**Checks (unit test)**
- Sheet name not in spreadsheet → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

---

## `merge_cells` / `unmerge_cells`

### TC-S38: Merge a header row range ⚠️ destructive

**Prompt**
**Playwright: required**
> "Merge cells A1:D1 on the Sales sheet to make a single header cell"

**Checks**
- `mergeCells` request with `mergeType=MERGE_ALL`
- Range covers A1:D1
- No error in response

**Result (2026-06-21) ✅** E1:G2 on Empty merged with MERGE_ALL. `replies: [{}]` — no error.

---

### TC-S39: Merge rows independently ⚠️ destructive

**Prompt**
**Playwright: required**
> "Merge each row independently in A1:C3 on Sales (merge_type=MERGE_ROWS)"

**Checks**
- `mergeCells` request with `mergeType=MERGE_ROWS`

**Result (2026-06-21) ✅** H1:J3 on Empty merged with MERGE_ROWS. `replies: [{}]` — no error.

---

### TC-S40: Unmerge a previously merged range ⚠️ destructive

**Prompt**
**Playwright: required**
> "Unmerge cells A1:D1 on the Sales sheet"

**Checks**
- `unmergeCells` request sent
- No error in response

**Result (2026-06-21) ✅** E1:G2 on Empty unmerged. `replies: [{}]` — no error.

---

### TC-S41: merge_cells — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

---

## `freeze`

### TC-S42: Freeze the header row ⚠️ destructive

**Prompt**
**Playwright: required**
> "Freeze the first row on the Sales sheet"

**Checks**
- `updateSheetProperties` with `frozenRowCount=1`, `frozenColumnCount=0`
- `fields` covers both `frozenRowCount` and `frozenColumnCount`
- No error in response

**Result (2026-06-21) ✅** Row 1 frozen on Sales. `replies: [{}]` — no error.

---

### TC-S43: Freeze first row and first column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Freeze the first row and first column on Sales"

**Checks**
- `frozenRowCount=1`, `frozenColumnCount=1`

**Result (2026-06-21) ✅** Row 1 and column 1 frozen on Sales. `replies: [{}]` — no error.

---

### TC-S44: Unfreeze all (rows=0, columns=0) ⚠️ destructive

**Prompt**
> "Unfreeze all rows and columns on the Sales sheet"

**Checks**
- `frozenRowCount=0`, `frozenColumnCount=0`

**Result (2026-06-21) ✅** All rows and columns unfrozen on Sales. `replies: [{}]` — no error.

---

### TC-S45: freeze — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

---

## `update_sheet_properties`

### TC-S57: Set tab color ⚠️ destructive

**Prompt**
**Playwright: required**
> "Set the tab color of the Sales sheet in {SPREADSHEET_ID} to red (red=1.0, green=0.0, blue=0.0)"

**Checks**
- `updateSheetProperties` request has `properties.tabColor == {"red": 1.0, "green": 0.0, "blue": 0.0}`
- `fields` includes `tabColor`
- No error in response
- Sales tab visibly shows a red color in the Sheets UI

**Result (2026-07-13) ✅ PASS** API call succeeded, no error field. Visually confirmed via Playwright: DOM element `.docs-sheet-tab-color` on the Sales tab has `style="background: rgb(255, 0, 0)"` — matches the requested red.

---

### TC-S57b: Clear tab color with `{}` ⚠️ destructive

**Prompt**
**Playwright: required**
> "Clear the tab color of the Sales sheet in {SPREADSHEET_ID}" (tool called with `tab_color={}`)

**Checks**
- `updateSheetProperties` request has `properties.tabColorStyle == {}`
- `fields` includes `tabColorStyle`, and does not include `tabColor`
- No error in response
- Sales tab visibly returns to the default (no color) state in the Sheets UI, not black

---

### TC-S58: Hide gridlines ⚠️ destructive

**Prompt**
**Playwright: required**
> "Hide the gridlines on the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- `updateSheetProperties` request has `properties.gridProperties.hideGridlines == True`
- `fields` includes `gridProperties.hideGridlines`
- No error in response
- Gridlines are visibly absent from the Sales sheet in the Sheets UI

**Result (2026-07-13) ✅ PASS** API call succeeded, no error field. Visually confirmed via Playwright screenshot: no gridlines visible between cells on the Sales sheet after the call.

---

### TC-S59: Set right-to-left layout ⚠️ destructive

**Prompt**
**Playwright: required**
> "Set the Sales sheet in {SPREADSHEET_ID} to right-to-left layout"

**Checks**
- `updateSheetProperties` request has `properties.rightToLeft == True`
- `fields` includes `rightToLeft`
- No error in response
- Sheet layout visibly mirrors to right-to-left in the Sheets UI (row headers on the right)

**Result (2026-07-13) ✅ PASS** API call succeeded, no error field. Visually confirmed via Playwright screenshot: column headers ran right-to-left (A on the far right, K on the far left) after the call.

---

### TC-S60: Combine tab color, gridlines, and right-to-left in one call ⚠️ destructive

**Prompt**
> "On the Sales sheet in {SPREADSHEET_ID}, set the tab color to blue (red=0.0, green=0.0, blue=1.0), show gridlines, and turn off right-to-left layout — all in one call"

**Checks**
- Single `updateSheetProperties` request in the batchUpdate body
- `properties` includes `tabColor`, `gridProperties.hideGridlines == False`, and `rightToLeft == False`
- `fields` lists all three: `tabColor`, `gridProperties.hideGridlines`, `rightToLeft`
- No error in response

**Result (2026-07-13) ✅ PASS** Single `update_sheet_properties` call with `tab_color`, `show_gridlines=true`, `right_to_left=false` all set returned `{"spreadsheetId":"...","replies":[{}]}`, no error field — confirming the tool folds all three into one `updateSheetProperties` request (per code: one `properties`/`fields` dict shared across all provided args). Unit test `test_multiple_properties_produce_multiple_fields` independently confirms the request-body shape (all three keys present in both `properties` and `fields`).

---

### TC-S61: No properties provided returns error

**Checks (unit test)**
- Calling with no `tab_color`, `show_gridlines`, or `right_to_left` → `{"error": "No properties provided to update"}`
- No `batchUpdate` call is made

**Result (2026-07-13) ✅ PASS** `tests/sheets/test_structure.py::TestUpdateSheetProperties::test_no_params_returns_error` passed (`uv run python -m pytest tests/sheets/test_structure.py -k UpdateSheetProperties`, 9/9 passed).

---

### TC-S62: update_sheet_properties — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`
- No `batchUpdate` call is made

**Result (2026-07-13) ✅ PASS** Unit test `test_returns_error_when_sheet_not_found` passed. Also confirmed live against the fixture spreadsheet: `update_sheet_properties(spreadsheet_id=TEST_SPREADSHEET_ID, sheet="DoesNotExist", right_to_left=true)` → `{"error":"Sheet 'DoesNotExist' not found"}`.

---

## `sort_range`

### TC-S46: Sort a data range ascending by first column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Sort the range A2:D50 on Sales by the first column ascending"

**Checks**
- `sortRange` request with `sortSpecs[0].dimensionIndex=0`, `sortOrder=ASCENDING`
- Range covers A2:D50

**Result (2026-06-21) ✅** A2:D5 on Sales sorted by Product ascending (Donut, Gadget, Gizmo, Widget). `replies: [{}]` — no error.

---

### TC-S47: Sort descending by a non-first column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Sort A2:D50 on Sales by column C (index 2) descending"

**Checks**
- `sortSpecs[0].dimensionIndex=2`, `sortOrder=DESCENDING`

**Result (2026-06-21) ✅** A2:D5 sorted by Q2 descending (Gizmo 310, Widget 120, Gadget 180... descending). `replies: [{}]` — no error.

---

### TC-S48: Multi-column sort ⚠️ destructive

**Prompt**
**Playwright: required**
> "Sort A2:D50 on Sales: primary key column A ascending, secondary key column C descending"

**Checks**
- Two sort specs in `sortSpecs`
- First spec: `dimensionIndex=0`, `ASCENDING`
- Second spec: `dimensionIndex=2`, `DESCENDING`

**Result (2026-06-21) ✅** A2:D5 sorted by Product ASC then Q2 DESC. Two sortSpecs emitted. `replies: [{}]` — no error.

---

### TC-S49: column_index offset by range start column

**Checks (unit test)**
- Range starting at column B (index 1) with `column_index=0` → `dimensionIndex=1`

**Result (2026-06-21) ✅** Unit test confirms offset applied correctly.

---

### TC-S50: sort_range — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.
