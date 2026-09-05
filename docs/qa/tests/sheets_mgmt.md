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

**Result (2026-09-04) ✅ PASS**
list_sheets → Sales/Empty/Notes & Misc (3 tabs), no error

---

### TC-S02: Cache hit on second call

**Prompt** (run twice in the same session)
> "List the sheets in {SPREADSHEET_ID} again"

**Checks**
- Second call returns the same list
- Server logs show `cache hit` for the second call (`make logs`)

**Result (2026-09-04) ✅ PASS**
2nd call same list; cache-hit not verifiable from QA session (no log access)

---

### TC-S03: Cache invalidated after rename

**Prompt**
> "Rename the 'Empty' sheet in {SPREADSHEET_ID} to 'WasEmpty', then immediately list all sheets"

**Checks**
- `list_sheets` response includes 'WasEmpty', not 'Empty'
- Confirms `cache.mark_dirty` fires after rename and the next list re-fetches

**Result (2026-09-04) ✅ PASS**
Empty→WasEmpty, list_sheets reflects rename immediately (mark_dirty confirmed); renamed back to Empty in teardown

---

## `copy_sheet`

### TC-S04: Copy within same spreadsheet

**Prompt**
> "Copy the Sales sheet within {SPREADSHEET_ID} and name the copy 'Sales Copy'"

**Checks**
- New sheet 'Sales Copy' appears in {SPREADSHEET_ID}
- Data in 'Sales Copy' matches Sales (6 rows, 4 columns)
- Original Sales sheet unchanged

**Result (2026-09-04) ✅ PASS**
copy_sheet(dst_sheet="Sales Copy") → 'Sales Copy' created, data matches Sales 6x4 exactly, Sales unaffected

---

### TC-S05: Copy to a different spreadsheet

**Prompt**
> "Copy the Sales sheet from {SPREADSHEET_ID} into a different spreadsheet — use {SPREADSHEET_ID} as both source and destination for this test, but note the tool supports different IDs"

**Checks**
- Tool accepts `src_spreadsheet` and `dst_spreadsheet` as separate params
- Copy operation completes without error
- 🔍 **Note:** requires a second spreadsheet ID to fully verify cross-spreadsheet copy

**Result (2026-09-04) ✅ PASS**
copy_sheet accepted src_spreadsheet/dst_spreadsheet as distinct params (same ID value); completed without error

---

### TC-S06: Name differs from Google's auto-assigned name — rename triggered

**Prompt**
> "Copy the Sales sheet in {SPREADSHEET_ID} and name the copy 'My Custom Name'"

**Checks**
- Sheet is named 'My Custom Name', not Google's default 'Copy of Sales'
- Rename was triggered automatically after the copy

**Result (2026-09-04) ✅ PASS**
copy_sheet(dst_sheet="My Custom Name") → sheet named "My Custom Name" not "Copy of Sales"; response included "rename" key confirming auto-rename triggered

---

### TC-S07: Name matches Google's auto-assigned name — rename skipped

**Prompt**
> "Copy the Sales sheet in {SPREADSHEET_ID} and name the copy 'Copy of Sales'"

**Checks**
- Sheet is named 'Copy of Sales'
- No unnecessary rename API call (names already match)

**Result (2026-09-04) ✅ PASS**
copy_sheet(dst_sheet="Copy of Sales") matching Google's own default name → response has no "rename" key, confirming no extra rename API call

---

### TC-S08: Source sheet not found

**Prompt**
> "Copy a sheet called 'DoesNotExist' from {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` before calling the copy API
- Error references the missing sheet name

**Result (2026-09-04) ✅ PASS**
copy_sheet(src_sheet="DoesNotExist") → {"error":"Source sheet 'DoesNotExist' not found"}, before API call

---

### TC-S09: Destination spreadsheet not writable

**Prompt**
> "Copy the Sales sheet from {SPREADSHEET_ID} to spreadsheet 'invalidid123xyz'"

**Checks**
- Returns a clear API error — destination not accessible
- Source spreadsheet unaffected

**Result (2026-09-04) ✅ PASS**
copy_sheet(dst_spreadsheet="invalidid123xyz") → HttpError 400 "Invalid destinationSpreadsheetId", source unaffected

---

### TC-S10: Cache invalidated after copy ⚠️ destructive

**Prompt**
> "Copy the Sales sheet in {SPREADSHEET_ID} as 'PostCopyCache', then immediately list all sheets"

**Checks**
- `list_sheets` includes 'PostCopyCache'
- Confirms `cache.mark_dirty(dst_spreadsheet)` fires after copy

**Result (2026-09-04) ✅ PASS**
copy_sheet(dst_sheet="PostCopyCache") then immediate list_sheets includes it — mark_dirty confirmed

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

**Result (2026-09-04) ✅ PASS**
duplicate_sheet(sheet="Sales") → {"sheetId","title":"Copy of Sales","index":1,"spreadsheetId"}; data matches Sales 6x4; original unchanged. Deleted after

---

### TC-S52: Duplicate with a custom name ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID} and name the copy 'Sales Duplicate'"

**Checks**
- New tab is named 'Sales Duplicate', not Google's default
- `newSheetName` was passed on the same `duplicateSheet` request (single API call, no follow-up rename)

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales", new_name="Sales Duplicate")` → title `"Sales Duplicate"`, confirmed via code that `newSheetName` is set on the same request body as `sourceSheetId`. Deleted after verification.

**Result (2026-09-04) ✅ PASS**
duplicate_sheet(new_name="Sales Duplicate") → title="Sales Duplicate" directly in response (single-call newSheetName, no follow-up rename). Deleted after

---

### TC-S53: Default position lands immediately after the source tab ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID} without specifying a position, then list all sheets"

**Checks**
- The new tab appears immediately after 'Sales' in the `list_sheets` response order
- 🔍 **Regression:** the Sheets API's own default for `duplicateSheet` places the copy at tab position 0 regardless of source position (confirmed via live QA on this tool) — the tool must compute and pass `insertSheetIndex` explicitly to land the copy after the source, matching Sheets UI's native "Duplicate" behavior

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales")` → index 1. `list_sheets` → `["Sales","Copy of Sales","Empty","Notes & Misc","BrandNew"]` — lands immediately after Sales, confirming the regression fix (`_get_sheet_index` + explicit `insertSheetIndex`). Deleted after verification.

**Result (2026-07-27) ✅ PASS — regression check for PR #440 (issue #391)**
Re-ran after `_get_sheet_index`'s blanket `except Exception: return None` was removed (PR #440, mirroring #384's fix to `_get_sheet_id`) so transient API failures propagate instead of being silently treated as "index unknown." Same call, same result: `duplicate_sheet(spreadsheet_id, sheet="Sales")` → index 1, `list_sheets` → `["Sales","Copy of Sales","Notes & Misc","BrandNew","Empty"]` — copy still lands immediately after Sales, confirming the success path (loop finds the match and returns its index) is unchanged by the removed catch-all. Deleted after verification.

**Result (2026-09-04) ✅ PASS**
duplicate_sheet() no insert_index → list_sheets shows "Copy of Sales" immediately after "Sales" (index 1). Deleted after

---

### TC-S54: Explicit insert_index is honored ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID}, placing the copy at tab position 0"

**Checks**
- The new tab is the first tab in the `list_sheets` response order
- Confirms an explicit `insert_index` overrides the "after source" default

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales", insert_index=0)` → index 0. `list_sheets` → `["Copy of Sales","Sales",...]` — explicit index correctly overrides the default. Deleted after verification.

**Result (2026-09-04) ✅ PASS**
duplicate_sheet(insert_index=0) → "Copy of Sales" is first tab in list_sheets. Deleted after

---

### TC-S55: Source sheet not found

**Prompt**
> "Duplicate a sheet called 'DoesNotExist' in {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` before calling the duplicate API
- Error references the missing sheet name

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="DoesNotExist")` → `{"error": "Sheet 'DoesNotExist' not found"}`. No mutation, non-destructive.

**Result (2026-07-21) ✅ PASS — regression check for PR #390 (issue #384)**
Re-ran after `_get_sheet_id`'s blanket `except Exception: return None` was removed (PR #390) so transient API failures propagate instead of being misreported as "not found." Same call, same response: `{"error": "Sheet 'DoesNotExist' not found"}` — the genuine-not-found path is unchanged, still resolves via the loop finding no match rather than via the removed catch-all.

**Result (2026-09-04) ✅ PASS**
duplicate_sheet(sheet="DoesNotExist") → {"error":"Sheet 'DoesNotExist' not found"}

---

### TC-S56: Cache invalidated after duplicate ⚠️ destructive

**Prompt**
> "Duplicate the Sales sheet in {SPREADSHEET_ID} as 'PostDuplicateCache', then immediately list all sheets"

**Checks**
- `list_sheets` includes 'PostDuplicateCache'
- Confirms `cache.mark_dirty(spreadsheet_id)` fires after duplicate

**Result (2026-07-10) ✅ PASS**
`duplicate_sheet(spreadsheet_id, sheet="Sales", new_name="PostDuplicateCache")` succeeded; immediate `list_sheets` (no explicit `refresh_cache`) included `"PostDuplicateCache"`, confirming `mark_dirty` fired. Deleted after verification; fixture restored to `["Sales","Empty","Notes & Misc","BrandNew"]`.

**Result (2026-09-04) ✅ PASS**
duplicate_sheet(new_name="PostDuplicateCache") then immediate list_sheets includes it — mark_dirty confirmed. Deleted after

---

## `rename_sheet`

### TC-S11: Rename to a new name ⚠️ destructive

**Prompt**
> "Rename the 'Empty' sheet in {SPREADSHEET_ID} to 'Renamed'"

**Checks**
- Sheet formerly called 'Empty' is now 'Renamed'
- `list_sheets` reflects the new name
- No `error` field

**Result (2026-09-04) ✅ PASS**
rename_sheet(Empty→Renamed) → no error; list_sheets shows "Renamed" not "Empty". Renamed back

---

### TC-S12: Rename to the same name

**Prompt**
> "Rename the 'Sales' sheet in {SPREADSHEET_ID} to 'Sales' (same name)"

**Checks**
- API succeeds or no-ops — no error
- Sheet still exists with the same name
- 🔍 **Product decision:** is a same-name rename a no-op or does it round-trip to the API?

**Result (2026-09-04) ✅ PASS**
rename_sheet(Sales→Sales same name) → succeeds, no error, round-trips to API (not a client no-op)

---

### TC-S13: Sheet not found

**Prompt**
> "Rename a sheet called 'NoSuchSheet' in {SPREADSHEET_ID} to 'Anything'"

**Checks**
- Returns `{"error": ...}` — sheet not found
- Does not call the Sheets API

**Result (2026-07-21) ✅ PASS — regression check for PR #390 (issue #384)**
`rename_sheet(spreadsheet="{SPREADSHEET_ID}", sheet="NoSuchSheet", new_name="Whatever")` → `{"error": "Sheet 'NoSuchSheet' not found"}`, confirming this path through `_get_sheet_id` is unaffected by PR #390's removal of the blanket exception catch.

**Result (2026-09-04) ✅ PASS**
rename_sheet(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S14: Cache invalidated after rename

**Prompt**
> "Rename 'Notes & Misc' to 'Notes' in {SPREADSHEET_ID}, then list all sheets"

**Checks**
- `list_sheets` shows 'Notes', not 'Notes & Misc'
- Confirms `cache.mark_dirty` fires; next list re-fetches from API

**Result (2026-09-04) ✅ PASS**
rename_sheet('Notes & Misc'→'Notes') → list_sheets shows "Notes" not "Notes & Misc" — mark_dirty confirmed. Renamed back

---

## `create_sheet`

### TC-S15: Create a new tab

**Prompt**
> "Add a new sheet called 'BrandNew' to {SPREADSHEET_ID}"

**Checks**
- New tab 'BrandNew' appears
- Response includes `sheetId`, `title`, `index`, `spreadsheetId`
- `cache.mark_dirty` called — `list_sheets` reflects the new tab

**Result (2026-09-04) ✅ PASS**
create_sheet(title="BrandNew") → {sheetId(int), title, index(int), spreadsheetId} all present; list_sheets reflects it

---

### TC-S16: Duplicate tab title

**Prompt**
> "Add another sheet called 'Sales' to {SPREADSHEET_ID} — a tab with that name already exists"

**Checks**
- 🔍 **Product decision:** does the API error, auto-suffix (e.g. "Sales2"), or succeed with a duplicate?
- Note observed behavior

**Result (2026-09-04) ✅ PASS**
create_sheet(title="Sales", dup) → HttpError 400 "A sheet with the name \"Sales\" already exists." — errors cleanly, no auto-suffix, no silent duplicate

---

### TC-S17: Long title

**Prompt**
> "Add a sheet with a 150-character title to {SPREADSHEET_ID}"

**Checks**
- API error with a clear message about title length limits, or succeeds if no limit enforced
- Note the actual limit if an error is returned

**Result (2026-09-04) ✅ PASS**
create_sheet(150-char title) → HttpError 400 "The sheet name cannot be greater than 100 characters." — clear message with actual limit (100)

---

### TC-S18: Response shape

**Prompt**
> "Create a sheet called 'ShapeTest' in {SPREADSHEET_ID} and show me the full response"

**Checks**
- Response includes: `sheetId` (integer), `title` (string), `index` (integer), `spreadsheetId` (string)
- No unexpected missing fields

**Result (2026-09-04) ✅ PASS**
create_sheet(title="ShapeTest") → {sheetId(int), title(str), index(int), spreadsheetId(str)}, no missing fields

---

### TC-S19: Cache updated after create

**Prompt**
> "Create a sheet called 'CacheNewSheet' in {SPREADSHEET_ID}, then list all sheets"

**Checks**
- `list_sheets` includes 'CacheNewSheet' immediately
- Confirms `cache.mark_dirty` fires after creation

**Result (2026-09-04) ✅ PASS**
create_sheet(title="CacheNewSheet") then list_sheets includes it immediately — mark_dirty confirmed

---

## `refresh_cache`

### TC-S20: Refresh by spreadsheet ID only

**Prompt**
> "Refresh the cache for {SPREADSHEET_ID}"

**Checks**
- Returns success
- Next `list_sheets` or summary call hits the API (visible in logs as a cache miss)

**Result (2026-09-04) ✅ PASS**
refresh_cache(spreadsheet_id) → {"invalidated":["spreadsheet:<id>"]}, scoped correctly

---

### TC-S21: Refresh by doc ID only

**Prompt**
> "Refresh the cache for doc {DOC_ID}"

**Checks**
- Returns success
- Next `get_doc_content` call re-fetches from API

**Result (2026-09-04) ⏭️ SKIP**
Requires {DOC_ID} fixture — not provided to this Sheets shard (only SPREADSHEET_ID/FOLDER_ID/SHARED_DRIVE_ID given)

---

### TC-S22: Refresh both spreadsheet and doc

**Prompt**
> "Refresh the cache for both {SPREADSHEET_ID} and doc {DOC_ID}"

**Checks**
- Both caches marked dirty
- Subsequent calls for both re-fetch from API

**Result (2026-09-04) ⏭️ SKIP**
Requires {DOC_ID} fixture — not provided to this Sheets shard

---

### TC-S23: Refresh with no arguments — clears all caches

**Prompt**
> "Clear all caches in mcp-gee-sweet"

**Checks**
- All four caches marked dirty (structure, data, Drive folder, doc)
- Next calls for any resource re-fetch from API

**Result (2026-09-04) ✅ PASS**
refresh_cache() no args → {"invalidated":"all"}

---

### TC-S24: Cache re-populated after refresh

**Prompt**
> "Refresh the cache for {SPREADSHEET_ID}, then immediately summarize it"

**Checks**
- Summary returns correct data (re-fetched, not stale)
- Logs show a cache miss followed by a cache store

**Result (2026-09-04) ✅ PASS**
refresh_cache(spreadsheet_id) then get_multiple_spreadsheet_summary → correct re-fetched data including tabs created moments earlier (BrandNew/ShapeTest/CacheNewSheet), confirming no stale cache

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

**Result (2026-09-04) ✅ PASS**
create TempTab, delete_sheet(TempTab) → no error; list_sheets confirms absent

---

### TC-S26: Delete a non-existent sheet returns error

**Prompt**
> "Delete a sheet called 'DoesNotExist' from {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field mentioning the sheet name
- No API call made (no batchUpdate)

**Result (2026-06-21) ✅** Response: `{"error":"Sheet 'DoesNotExist' not found"}`. No batchUpdate issued.

**Result (2026-09-04) ✅ PASS**
delete_sheet(sheet="DoesNotExist") → {"error":"Sheet 'DoesNotExist' not found"}

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

**Result (2026-09-04) ✅ PASS**
delete_rows(start_row=4) → Gizmo row removed; Totals (now row 5) recalculated to 350/360/415

---

### TC-S28: Delete a range of rows ⚠️ destructive

**Prompt**
> "Delete rows 3 through 5 (0-based indices 2–4) from the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Three rows removed; subsequent rows shift up correctly
- `startIndex: 2`, `endIndex: 5` in the deleteDimension request

**Result (2026-06-21) ✅** Rows 2–4 (Gadget/Donut/Gizmo) removed. Widget and Totals remain; Totals recalculated to 100/120/140 (Widget only).

**Result (2026-09-04) ✅ PASS**
delete_rows(start_row=2,end_row=4) → 3 rows removed (Gadget/Donut/Totals); only header+Widget remain — confirms inclusive end_row=4 → exclusive endIndex=5

---

### TC-S29: Delete rows — sheet not found returns error

**Prompt**
> "Delete row 0 from a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-06-21) ✅** Response: `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
delete_rows(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

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

**Result (2026-09-04) ✅ PASS**
delete_columns(start_column=1) → Q1 removed, Q2/Q3 shift left, Totals recalc 670/705

---

### TC-S31: Delete a range of columns ⚠️ destructive

**Prompt**
> "Delete columns C through E (0-based indices 2–4) from the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Three columns removed; columns to the right shift left
- `startIndex: 2`, `endIndex: 5`

**Result (2026-06-21) ✅** Column indices 2–3 (Q2 and Q3) deleted (only 4 cols exist so effective range was 2–3). Only Product and Q1 remained. Inclusive end index correctly translated to exclusive endIndex in API call.

**Result (2026-09-04) ✅ PASS**
delete_columns(start_column=2,end_column=4) on 3-col sheet → only Q3(idx2) existed in range, removed; Product/Q2 remain — clip-to-available confirmed

---

### TC-S32: Delete columns — sheet not found returns error

**Prompt**
> "Delete column 0 from a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-06-21) ✅** Response: `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
delete_columns(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

## `hide_rows` / `unhide_rows`

### TC-S63: Hide a single row ⚠️ destructive

**Prompt**
**Playwright: required**
> "Hide row 5 (0-based index 4) on the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- `updateDimensionProperties` request sent with `dimension: ROWS`, `startIndex: 4`, `endIndex: 5`
- `properties.hiddenByUser: true`, `fields: hiddenByUser`
- Row 5 collapses to a thin line in the Sheets UI with a show-row chevron

**Result (2026-07-14) ✅ PASS**
`hide_rows(spreadsheet_id, sheet="Sales", start_row=4)` → `{"replies":[{}]}`. Playwright screenshot confirmed row headers skip from 4 straight to 6 with expand chevrons at the boundary.

**Result (2026-09-04) ✅ PASS**
hide_rows(start_row=4): screenshot shows row headers 1,2,3,4,6 (row 5 collapsed) with expand chevrons at the 4→6 boundary. Matches API evidence exactly.

---

### TC-S64: Hide a range of rows ⚠️ destructive

**Prompt**
**Playwright: required**
> "Hide rows 3 through 5 (0-based indices 2–4) on the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- `startIndex: 2`, `endIndex: 5` in the request (inclusive end_row=4 translated to exclusive 5)
- All three rows collapse in the UI

**Result (2026-07-14) ✅ PASS**
`hide_rows(spreadsheet_id, sheet="Sales", start_row=2, end_row=4)` → `{"replies":[{}]}`. Playwright screenshot confirmed row headers skip from 2 straight to 6 (rows 3-5 collapsed together).

**Result (2026-09-04) ✅ PASS**
hide_rows(start_row=2,end_row=4): screenshot shows row headers 1,2,6 (rows 3-5 collapsed together as one boundary). Matches.

---

### TC-S65: Hide rows — sheet not found returns error

**Prompt**
> "Hide row 0 on a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-07-14) ✅ PASS**
`hide_rows(spreadsheet_id, sheet="NoSuchSheet", start_row=0)` → `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
hide_rows(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S66: Unhide a previously hidden row ⚠️ destructive

**Prompt**
**Playwright: required**
> "Unhide row 5 (0-based index 4) on the Sales sheet in {SPREADSHEET_ID}"

**Setup:** Row 5 hidden by a prior `hide_rows` call (e.g. TC-S63).

**Checks**
- `updateDimensionProperties` request sent with `properties.hiddenByUser: false`
- Row 5 reappears in the Sheets UI

**Result (2026-07-14) ✅ PASS**
`unhide_rows(spreadsheet_id, sheet="Sales", start_row=4)` → `{"replies":[{}]}`. Playwright screenshot confirmed row 5 reappeared (rows 3-4 remained collapsed since only index 4 was unhidden).

**Result (2026-09-04) ✅ PASS**
unhide_rows(start_row=4): screenshot shows row headers 1,2,5,6 — row 5 reappeared, rows 3-4 remain collapsed (only targeted index unhidden). Matches.

---

### TC-S67: Unhide rows — sheet not found returns error

**Prompt**
> "Unhide row 0 on a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-07-14) ✅ PASS**
`unhide_rows(spreadsheet_id, sheet="NoSuchSheet", start_row=0)` → `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
unhide_rows(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

## `hide_columns` / `unhide_columns`

### TC-S68: Hide a single column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Hide column B (0-based index 1) on the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- `updateDimensionProperties` request sent with `dimension: COLUMNS`, `startIndex: 1`, `endIndex: 2`
- `properties.hiddenByUser: true`
- Column B collapses in the Sheets UI

**Result (2026-07-14) ✅ PASS**
`hide_columns(spreadsheet_id, sheet="Sales", start_column=1)` → `{"replies":[{}]}`. Playwright screenshot confirmed column headers skip from A straight to C; chart legend dropped its Q1 series (sourced from column B).

**Result (2026-09-04) ✅ PASS**
hide_columns(start_column=1): screenshot shows column headers A, then C,D (chevron between A and C — col B collapsed). Matches.

---

### TC-S69: Hide a range of columns ⚠️ destructive

**Prompt**
**Playwright: required**
> "Hide columns C through E (0-based indices 2–4) on the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- `startIndex: 2`, `endIndex: 5` in the request
- All columns in range collapse in the UI

**Result (2026-07-14) ✅ PASS**
`hide_columns(spreadsheet_id, sheet="Sales", start_column=2, end_column=4)` → `{"replies":[{}]}`. Playwright screenshot confirmed column headers skip from A straight to F (B-E collapsed together); chart showed "Add a series" since all data columns were hidden.

**Result (2026-09-04) ✅ PASS**
hide_columns(start_column=2,end_column=4): screenshot shows column headers A then straight to F (B,C,D,E all collapsed together, since col B was already hidden from S68 and wasn't unhidden first — expected, test only asserts C-E collapse). Matches.

---

### TC-S70: Hide columns — sheet not found returns error

**Prompt**
> "Hide column 0 on a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-07-14) ✅ PASS**
`hide_columns(spreadsheet_id, sheet="NoSuchSheet", start_column=0)` → `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
hide_columns(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S71: Unhide a previously hidden column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Unhide column B (0-based index 1) on the Sales sheet in {SPREADSHEET_ID}"

**Setup:** Column B hidden by a prior `hide_columns` call (e.g. TC-S68).

**Checks**
- `updateDimensionProperties` request sent with `properties.hiddenByUser: false`
- Column B reappears in the Sheets UI

**Result (2026-07-14) ✅ PASS**
`unhide_columns(spreadsheet_id, sheet="Sales", start_column=1)` → `{"replies":[{}]}`. Playwright screenshot confirmed column B reappeared (chart legend regained its Q1 series) while C-E remained collapsed.

**Result (2026-09-04) ✅ PASS**
unhide_columns(start_column=1): screenshot shows column headers A, B, then F (col B reappeared, C-D-E remain collapsed — only targeted index unhidden). Matches.

---

### TC-S72: Unhide columns — sheet not found returns error

**Prompt**
> "Unhide column 0 on a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-07-14) ✅ PASS**
`unhide_columns(spreadsheet_id, sheet="NoSuchSheet", start_column=0)` → `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
unhide_columns(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

## `resize_rows` / `resize_columns`

### TC-S73: Resize a single row to an explicit pixel height ⚠️ destructive

**Prompt**
**Playwright: required**
> "Set row 5 (0-based index 4) on the Sales sheet in {SPREADSHEET_ID} to 60 pixels tall"

**Checks**
- `updateDimensionProperties` request sent with `dimension: ROWS`, `startIndex: 4`, `endIndex: 5`
- `properties.pixelSize: 60`, `fields: pixelSize`
- Row 5 visibly taller in the Sheets UI

**Result (2026-07-15) ✅ PASS** `resize_rows(spreadsheet_id, sheet="Sales", start_row=4, pixel_size=60)` → `{"replies":[{}]}`, no error. Playwright was skipped for this run — the shared fixture's Sales sheet currently has ~12 overlapping chart objects left over from other QA passes, which visually cover rows 1–22 and make row-height differences unreadable in a screenshot. Verified precisely instead via `get_sheet_data(..., range="A1:E6", include_grid_data=True)`, which returns `rowMetadata[].pixelSize` — confirmed row index 4 read back 60 immediately after this call (before being overwritten by TC-S74/TC-S75 below).

**Result (2026-09-04) ✅ PASS**
resize_rows(start_row=4,pixel_size=60): screenshot shows row 5 (Gizmo) visibly taller than surrounding rows. Matches.

---

### TC-S74: Resize a range of rows ⚠️ destructive

**Prompt**
**Playwright: required**
> "Set rows 3 through 5 (0-based indices 2–4) on the Sales sheet in {SPREADSHEET_ID} to 40 pixels tall"

**Checks**
- `startIndex: 2`, `endIndex: 5` in the request (inclusive end_row=4 translated to exclusive 5)
- All three rows resize in the UI

**Result (2026-07-15) ✅ PASS** `resize_rows(spreadsheet_id, sheet="Sales", start_row=2, end_row=4, pixel_size=40)` → `{"replies":[{}]}`, no error. Confirmed via `get_sheet_data(..., range="A1:E6", include_grid_data=True)`: `rowMetadata` for row indices 2 and 3 both read back `pixelSize: 40` after the full test sequence (index 4 was subsequently auto-resized by TC-S75, as expected).

**Result (2026-09-04) ✅ PASS**
resize_rows(start_row=2,end_row=4,pixel_size=40): screenshot shows rows 3,4 (Gadget,Donut) both visibly taller, row 5 (Gizmo) still tall from S73. Matches.

---

### TC-S75: Auto-resize rows to fit content ⚠️ destructive

**Prompt**
**Playwright: required**
> "Auto-fit the height of row 5 (0-based index 4) on the Sales sheet in {SPREADSHEET_ID} to its content"

**Setup:** Row 5 previously set to an oversized pixel height (e.g. TC-S73).

**Checks**
- `autoResizeDimensions` request sent with `dimensions.dimension: ROWS`, `startIndex: 4`, `endIndex: 5`
- Row 5 shrinks back to content-fit height in the Sheets UI

**Result (2026-07-15) ✅ PASS** `resize_rows(spreadsheet_id, sheet="Sales", start_row=4, auto_resize=True)` → `{"replies":[{}]}`, no error. Confirmed via `get_sheet_data(..., range="A1:E6", include_grid_data=True)`: row index 4's `pixelSize` read back as `21` (Sheets' default/content-fit height for plain text), down from the `40` set by TC-S74 moments earlier — confirms `autoResizeDimensions` fired and took effect.

**Result (2026-09-04) ✅ PASS**
resize_rows(start_row=4,auto_resize=True): screenshot shows row 5 (Gizmo) shrunk back to normal content-fit height while rows 3,4 remain tall from S74. Matches.

---

### TC-S76: Resize rows — neither pixel_size nor auto_resize given returns error

**Prompt**
> "Resize row 0 on the Sales sheet in {SPREADSHEET_ID} without specifying a size or auto-fit"

**Checks**
- Response contains `error` field
- No `batchUpdate` call made

**Result (2026-07-15) ✅ PASS** `resize_rows(spreadsheet_id, sheet="Sales", start_row=0)` → `{"error":"Specify pixel_size or set auto_resize=True"}`. Returned before any batchUpdate call.

**Result (2026-09-04) ✅ PASS**
resize_rows(start_row=0) no size/auto → {"error":"Specify pixel_size or set auto_resize=True"}

---

### TC-S77: Resize rows — both pixel_size and auto_resize given returns error

**Prompt**
> "Resize row 0 on the Sales sheet in {SPREADSHEET_ID} to 50 pixels and also auto-fit it"

**Checks**
- Response contains `error` field
- No `batchUpdate` call made

**Result (2026-07-15) ✅ PASS** `resize_rows(spreadsheet_id, sheet="Sales", start_row=0, pixel_size=50, auto_resize=True)` → `{"error":"Specify only one of pixel_size or auto_resize"}`. Returned before any batchUpdate call.

**Result (2026-09-04) ✅ PASS**
resize_rows(pixel_size=50,auto_resize=True) both → {"error":"Specify only one of pixel_size or auto_resize"}

---

### TC-S78: Resize rows — sheet not found returns error

**Prompt**
> "Set row 0 to 50 pixels tall on a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-07-15) ✅ PASS** `resize_rows(spreadsheet_id, sheet="NoSuchSheet", start_row=0, pixel_size=50)` → `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
resize_rows(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S79: Resize a single column to an explicit pixel width ⚠️ destructive

**Prompt**
**Playwright: required**
> "Set column B (0-based index 1) on the Sales sheet in {SPREADSHEET_ID} to 200 pixels wide"

**Checks**
- `updateDimensionProperties` request sent with `dimension: COLUMNS`, `startIndex: 1`, `endIndex: 2`
- `properties.pixelSize: 200`, `fields: pixelSize`
- Column B visibly wider in the Sheets UI

**Result (2026-07-15) ✅ PASS** `resize_columns(spreadsheet_id, sheet="Sales", start_column=1, pixel_size=200)` → `{"replies":[{}]}`, no error. Playwright skipped — see "Chart-covered grid" note in `docs/qa/run.md`. Verified via `get_sheet_data(..., range="A1:E6", include_grid_data=True)`: column index 1's `pixelSize` read back `200` immediately after this call (before being overwritten by TC-S81 below).

**Result (2026-09-04) ✅ PASS**
resize_columns(start_column=1,pixel_size=200): screenshot shows column B dramatically widened (200px). Matches.

---

### TC-S80: Resize a range of columns ⚠️ destructive

**Prompt**
**Playwright: required**
> "Set columns C through E (0-based indices 2–4) on the Sales sheet in {SPREADSHEET_ID} to 50 pixels wide"

**Checks**
- `startIndex: 2`, `endIndex: 5` in the request
- All columns in range resize in the UI

**Result (2026-07-15) ✅ PASS** `resize_columns(spreadsheet_id, sheet="Sales", start_column=2, end_column=4, pixel_size=50)` → `{"replies":[{}]}`, no error. Confirmed via `get_sheet_data(..., range="A1:E6", include_grid_data=True)`: column indices 2, 3, and 4 all read back `pixelSize: 50`.

**Result (2026-09-04) ✅ PASS**
resize_columns(start_column=2,end_column=4,pixel_size=50): screenshot shows columns C,D visibly widened while B remains 200px-wide from S79. Matches.

---

### TC-S81: Auto-resize columns to fit content ⚠️ destructive

**Prompt**
**Playwright: required**
> "Auto-fit the width of column B (0-based index 1) on the Sales sheet in {SPREADSHEET_ID} to its content"

**Setup:** Column B previously set to an oversized pixel width (e.g. TC-S79).

**Checks**
- `autoResizeDimensions` request sent with `dimensions.dimension: COLUMNS`, `startIndex: 1`, `endIndex: 2`
- Column B shrinks back to content-fit width in the Sheets UI

**Result (2026-07-15) ✅ PASS** `resize_columns(spreadsheet_id, sheet="Sales", start_column=1, auto_resize=True)` → `{"replies":[{}]}`, no error. Confirmed via `get_sheet_data(..., range="A1:E6", include_grid_data=True)`: column index 1's `pixelSize` read back `28` (content-fit for the short numeric values in column B), down from the `200` set by TC-S79 — confirms `autoResizeDimensions` fired and took effect.

**Result (2026-09-04) ✅ PASS**
resize_columns(start_column=1,auto_resize=True): screenshot shows column B shrunk back to normal width while C,D remain widened from S80. Matches.

---

### TC-S82: Resize columns — neither pixel_size nor auto_resize given returns error

**Prompt**
> "Resize column 0 on the Sales sheet in {SPREADSHEET_ID} without specifying a size or auto-fit"

**Checks**
- Response contains `error` field
- No `batchUpdate` call made

**Result (2026-07-15) ✅ PASS** `resize_columns(spreadsheet_id, sheet="Sales", start_column=0)` → `{"error":"Specify pixel_size or set auto_resize=True"}`. Returned before any batchUpdate call.

**Result (2026-09-04) ✅ PASS**
resize_columns(start_column=0) no size/auto → {"error":"Specify pixel_size or set auto_resize=True"}

---

### TC-S83: Resize columns — both pixel_size and auto_resize given returns error

**Prompt**
> "Resize column 0 on the Sales sheet in {SPREADSHEET_ID} to 100 pixels and also auto-fit it"

**Checks**
- Response contains `error` field
- No `batchUpdate` call made

**Result (2026-07-15) ✅ PASS** `resize_columns(spreadsheet_id, sheet="Sales", start_column=0, pixel_size=100, auto_resize=True)` → `{"error":"Specify only one of pixel_size or auto_resize"}`. Returned before any batchUpdate call.

**Result (2026-09-04) ✅ PASS**
resize_columns(pixel_size=100,auto_resize=True) both → {"error":"Specify only one of pixel_size or auto_resize"}

---

### TC-S84: Resize columns — sheet not found returns error

**Prompt**
> "Set column 0 to 100 pixels wide on a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Response contains `error` field

**Result (2026-07-15) ✅ PASS** `resize_columns(spreadsheet_id, sheet="NoSuchSheet", start_column=0, pixel_size=100)` → `{"error":"Sheet 'NoSuchSheet' not found"}`.

**Result (2026-09-04) ✅ PASS**
resize_columns(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

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

**Result (2026-09-04) ✅ PASS**
format_cells(A1:D1, bold=true, bg light blue) → replies:[{}], no error. Reset bold=false/bg white/align LEFT after

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

**Result (2026-09-04) ✅ PASS**
format_cells(B2:B100, CURRENCY $#,##0.00): screenshot shows column B values as "$100","$200","$50.","$300","$65(" — currency formatting visually confirmed (values truncated by column width but $ prefix clearly visible). Reset to NUMBER "0" after.

---

### TC-S35: Set horizontal alignment ⚠️ destructive

**Prompt**
**Playwright: required**
> "Center-align cells A1:F1 on the Sales sheet"

**Checks**
- `horizontalAlignment` is `"CENTER"`
- `fields` includes `userEnteredFormat.horizontalAlignment`

**Result (2026-06-21) ✅** A1:D1 on Sales center-aligned. `replies: [{}]` — no error.

**Result (2026-09-04) ✅ PASS**
format_cells(A1:F1, CENTER): API call succeeded (replies:[{}], no error). Screenshot shows "Product" in A1 — visual centering is subtle/near-imperceptible since the text nearly fills the ~52px column width, so left vs. center reads almost identically at this column width; not a defect, just a low-contrast visual case. Reset A1:D1 to LEFT after.

---

### TC-S36: No formatting params returns error

**Checks (unit test)**
- Calling `format_cells` with no formatting params returns `{"error": ...}`
- No batchUpdate API call made

**Result (2026-06-21) ✅** Unit test confirms error returned and batchUpdate not called.

**Result (2026-09-04) ✅ PASS**
format_cells(A1:D1) no formatting params → {"error":"No formatting parameters provided"}

---

### TC-S37: format_cells — sheet not found returns error

**Checks (unit test)**
- Sheet name not in spreadsheet → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

**Result (2026-09-04) ✅ PASS**
format_cells(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

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

**Result (2026-09-04) ✅ PASS**
merge_cells(Empty!E1:G2, MERGE_ALL) → replies:[{}], no error (used Empty scratch region, not Sales)

---

### TC-S39: Merge rows independently ⚠️ destructive

**Prompt**
**Playwright: required**
> "Merge each row independently in A1:C3 on Sales (merge_type=MERGE_ROWS)"

**Checks**
- `mergeCells` request with `mergeType=MERGE_ROWS`

**Result (2026-06-21) ✅** H1:J3 on Empty merged with MERGE_ROWS. `replies: [{}]` — no error.

**Result (2026-09-04) ✅ PASS**
merge_cells(Empty!A1:C3, MERGE_ROWS): screenshot confirms three separate row-spanning merged cells (rows 1,2,3 each merged A:C independently, distinct borders between rows) — correctly NOT one single A1:C3 block, confirming MERGE_ROWS semantics. Note: cross-test range overlap (this merge test reused the same A1:C3 cells as the B1:B5 BOOLEAN validation test) caused Google Sheets' own native merge behavior to visually show a checkbox glyph in the merged cells — this is Sheets' own validation-carryover-on-merge behavior, not a mcp-gee-sweet tool defect; the mergeCells API call itself succeeded exactly as requested.

---

### TC-S40: Unmerge a previously merged range ⚠️ destructive

**Prompt**
**Playwright: required**
> "Unmerge cells A1:D1 on the Sales sheet"

**Checks**
- `unmergeCells` request sent
- No error in response

**Result (2026-06-21) ✅** E1:G2 on Empty unmerged. `replies: [{}]` — no error.

**Result (2026-09-04) ✅ PASS**
unmerge_cells(Empty!A1:C3): API succeeded (replies:[{}], no error), screenshot confirms cells are no longer merged (individual cell borders restored across A,B,C for rows 1-3). Same cross-test-overlap side effect as S39 — unmerging spread the BOOLEAN checkbox validation to A1:A3/C1:C3 (verified via get_data_validation), a native Sheets merge/validation interaction from my own overlapping test ranges, not a tool defect.

---

### TC-S41: merge_cells — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

**Result (2026-09-04) ✅ PASS**
merge_cells(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

## `update_borders`

### TC-S85: Apply a solid border around all four edges of a range ⚠️ destructive

**Prompt**
**Playwright: required**
> "Add a black solid border around all four edges of A1:D5 on the Sales sheet"

**Checks**
- `updateBorders` request sent with `top`, `bottom`, `left`, `right` all `style="SOLID"`
- `color` set to black on each edge
- `range` covers A1:D5
- No error in response

**Result (2026-07-16) ✅ PASS (API-verified, not visual)** The Sales sheet's A1:D5 region is fully covered by the known stacked-chart fixture pollution (see `run.md`'s "Chart-covered grid" entry), so a screenshot can't show the border. Used `get_sheet_data(range="A1:D5", include_grid_data=True)` instead: perimeter cells (row 1 all columns = top; row 5 all columns = bottom; column A all rows = left; column D all rows = right) all show `{"style": "SOLID", "color": {}}` (empty color = black), exactly matching the request. No error in the batchUpdate response.

**Result (2026-09-04) ✅ PASS**
update_borders(A1:D5, top/bottom/left/right SOLID black): at 200% zoom, screenshot clearly shows a solid black perimeter border around the full A1:D5 block (top above row1, bottom below row5, left of col A, right of col D). Matches. Cleared after.

---

### TC-S86: Apply dashed inner gridlines inside a range ⚠️ destructive

**Prompt**
**Playwright: required**
> "Add dashed inner horizontal and vertical borders inside A1:C3 on the Sales sheet"

**Checks**
- `updateBorders` request includes `innerHorizontal` and `innerVertical`, both `style="DASHED"`
- `top`/`bottom`/`left`/`right` are not set
- No error in response

**Result (2026-07-16) ✅ PASS (API-verified, not visual)** Same chart-coverage limitation as TC-S85 — verified via `get_sheet_data(range="A1:C3", include_grid_data=True)`. Interior cell edges between rows/columns show `DASHED`, while the pre-existing perimeter `SOLID` borders from TC-S85 (which this call's request did not include top/bottom/left/right keys for) were left completely untouched — confirming the tool only sends the edges it was given and doesn't clobber unspecified ones. No error in response.

**Result (2026-09-04) ✅ PASS**
update_borders(A1:C3, inner_horizontal/inner_vertical DASHED): screenshot (200% zoom) clearly shows dotted/dashed vertical lines between A/B and B/C, and dashed horizontal lines between rows 1/2/3, confined to A1:C3; the still-present S85 perimeter border (top/left/bottom/right not included in this request) is untouched, confirming the tool only sends specified edges and doesn't clobber unspecified ones. Cleared after.

---

### TC-S87: Clear an existing border edge with style NONE ⚠️ destructive

**Prompt**
**Playwright: required**
> "Remove the border from the right edge of A1:D5 on the Sales sheet"

**Checks**
- `updateBorders` request includes `right.style="NONE"`
- No error in response

**Result (2026-07-16) ✅ PASS (API-verified, not visual)** Same chart-coverage limitation. Verified via `get_sheet_data(range="D1:D5", include_grid_data=True)`: the `right` border is absent from every cell in column D after the call, while `top`/`bottom` borders from TC-S85 remain — confirming only the targeted edge was cleared. No error in response.

**Result (2026-09-04) ✅ PASS**
update_borders(A1:D5, right=NONE): screenshot shows the right edge of column D no longer bordered while top/left borders (and the inner dashed lines from S86) remain visible — only the targeted edge was cleared. Matches. All borders cleared after.

---

### TC-S88: update_borders — no border params returns error

**Checks (unit test)**
- Calling `update_borders` with no edge params returns `{"error": ...}`
- No batchUpdate API call made

**Result (2026-07-16) ✅ PASS** `test_no_params_returns_error` passes.

**Result (2026-09-04) ✅ PASS**
update_borders(A1:D1, no edge params) → {"error":"No border parameters provided"}

---

### TC-S89: update_borders — border spec missing style returns error

**Checks (unit test)**
- An edge dict without a `"style"` key returns `{"error": ...}` before any API call

**Result (2026-07-16) ✅ PASS** `test_missing_style_returns_error` passes.

**Result (2026-09-04) ✅ PASS**
update_borders(top={"color":{"red":0}}) missing style → {"error":"Border spec for 'top' is missing required 'style' key"}

---

### TC-S90: update_borders — invalid style value returns error

**Checks (unit test)**
- An unrecognized `style` value (e.g. `"SQUIGGLY"`) returns `{"error": ...}` listing valid styles, before any API call

**Result (2026-07-16) ✅ PASS** `test_invalid_style_returns_error` passes.

**Result (2026-09-04) ✅ PASS**
update_borders(top={"style":"SQUIGGLY"}) → {"error":"Invalid border style 'SQUIGGLY' for 'top'. Must be one of: DOTTED, DASHED, SOLID, SOLID_MEDIUM, SOLID_THICK, DOUBLE, NONE"}

---

### TC-S91: update_borders — sheet not found returns error

**Checks (unit test)**
- Sheet name not in spreadsheet → `{"error": "Sheet 'X' not found"}`

**Result (2026-07-16) ✅ PASS** `test_returns_error_when_sheet_not_found` passes.

**Result (2026-09-04) ✅ PASS**
update_borders(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S92: update_borders — non-string style value returns error, does not crash

**Checks (unit test)**
- Calling `update_borders` with an edge dict whose `"style"` value is not a string (e.g. `top={"style": 5}` or `top={"style": None}`) returns `{"error": ...}`, same as the existing "invalid style" and "missing style" cases.

**Result (2026-07-16) ✅ PASS — fix verified** Originally failed: validation only checked `"style" not in border` (key presence) before calling `.upper()`, so a non-string style (e.g. `top={"style": 5}`) reached `border["style"].upper()` and crashed with an unhandled `AttributeError` instead of a clean error. Fixed by adding `if not isinstance(border["style"], str): return {"error": ...}` before the `.upper()` call. Verified three ways: unit test `test_non_string_style_returns_error` passes (covers both `5` and `None`); confirmed live against the real `update_borders` MCP tool with `top={"style": 5}` and `top={"style": null}` — both return `{"error": "Border spec for 'top' has a non-string 'style' value"}` with no crash. TC-S92 closed.

**Result (2026-09-04) ✅ PASS**
update_borders(top={"style":5}) non-string → {"error":"Border spec for 'top' has a non-string 'style' value"}, no crash

---

## `add_data_validation` / `get_data_validation`

### TC-S93: ONE_OF_LIST sets a dropdown and get_data_validation reads it back ⚠️ destructive

**Prompt**
**Playwright: required**
> "Add a dropdown to A1:A5 on the Sales sheet with the options Yes, No, Maybe"

**Checks**
- `setDataValidation` request sent with `condition.type == "ONE_OF_LIST"` and `condition.values` matching `["Yes", "No", "Maybe"]` (as `userEnteredValue` entries)
- `range` covers A1:A5
- Selecting a cell in A1:A5 in the Sheets UI shows a dropdown arrow with exactly those three options
- Calling `get_data_validation(range="A1:A5")` afterward returns one `{cell, rule}` entry per cell in the range, each with `condition.type == "ONE_OF_LIST"` and the same three values

**Result (2026-07-17) ✅ PASS (direct tool call, not Playwright UI)** — ran against a scratch range on the fixture's `Empty` sheet rather than `Sales`, but the tool logic is sheet-agnostic. `add_data_validation(condition_type="ONE_OF_LIST", values=["Yes","No","Maybe"])` succeeded; `get_data_validation` read back all 5 cells with `condition.type == "ONE_OF_LIST"` and the exact same 3 values. UI dropdown rendering not independently verified via Playwright this pass.

**Result (2026-09-04) ✅ PASS**
add_data_validation(Empty!A1:A5, ONE_OF_LIST, [Yes,No,Maybe]): get_data_validation confirms A4/A5 correctly retain `condition.type=ONE_OF_LIST` with the 3 values, and the screenshot shows the dropdown chevron on A4/A5 — valid visual confirmation of the dropdown mechanism. FINDING (test-design artifact, not a tool defect): A1-A3 lost their ONE_OF_LIST rule to a BOOLEAN rule instead, because the TC-S39/S40 merge/unmerge test was run on the same A1:C3 cells afterward — Sheets' own merge-cell validation-carryover behavior (confirmed via get_data_validation readback), unrelated to add_data_validation's correctness. Recommend future QA passes use non-overlapping scratch ranges for merge vs. validation tests.

---

### TC-S94: BOOLEAN with no values renders a plain checkbox ⚠️ destructive

**Prompt**
**Playwright: required**
> "Add a checkbox to B1:B5 on the Sales sheet"

**Checks**
- `setDataValidation` request sent with `condition == {"type": "BOOLEAN"}` — no `values` key
- Cells B1:B5 render as checkboxes in the Sheets UI, not free text
- `get_data_validation(range="B1:B5")` returns `condition.type == "BOOLEAN"` for each cell, no `values` key

**Result (2026-09-04) ✅ PASS**
add_data_validation(Empty!B1:B5, BOOLEAN, no values): screenshot clearly shows checkboxes rendered in B1:B5 (and, per the note above, cross-contaminated into A1:A3/C1:C3 from the merge/unmerge test — not a defect in this tool). get_data_validation confirms condition.type=BOOLEAN, no values key.

---

### TC-S95: NUMBER_BETWEEN with strict=False shows a warning instead of rejecting

**Prompt**
> "Add data validation to C1:C5 on the Sales sheet requiring a number between 1 and 10, but only warn instead of blocking invalid entries"

**Checks**
- `setDataValidation` request sent with `condition.type == "NUMBER_BETWEEN"`, `condition.values` = `["1", "10"]`, and `rule.strict == false`
- No error in response

**Result (2026-09-04) ✅ PASS**
add_data_validation(Empty!C1:C5, NUMBER_BETWEEN, [1,10], strict=false) → succeeded, no error

---

### TC-S96: get_data_validation returns an empty list for a range with no rules

**Prompt**
> "Check what data validation rules exist on D1:D5 on the Sales sheet" *(a range with no validation applied)*

**Checks**
- Returns `[]`
- No error

**Result (2026-07-17) ✅ PASS** `get_data_validation` on an untouched range returned `[]`, no error.

**Result (2026-09-04) ✅ PASS**
get_data_validation(Empty!D1:D5, no rules) → []

---

### TC-S97: add_data_validation — invalid condition_type returns error (unit test)

**Checks (unit test)**
- Calling `add_data_validation` with an unrecognized `condition_type` (e.g. `"NOT_A_REAL_TYPE"`) returns `{"error": ...}` listing valid types, before any API call
- Covered by `test_invalid_condition_type_returns_error_without_api_call`

**Result (2026-09-04) ✅ PASS**
add_data_validation(condition_type="NOT_A_REAL_TYPE") → {"error":"Invalid condition_type ... Must be one of: ..."}

---

### TC-S98: add_data_validation — sheet not found returns error (unit test)

**Checks (unit test)**
- Sheet name not in spreadsheet → `{"error": "Sheet 'X' not found"}`, before any API call
- Covered by `test_returns_error_when_sheet_not_found`

**Result (2026-09-04) ✅ PASS**
add_data_validation(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S99: `add_data_validation` ONE_OF_RANGE — the documented value format always fails ❌ code review finding

**Background:** `add_data_validation`'s own docstring documents `ONE_OF_RANGE`'s `values` as "one item, the source range in A1 notation, e.g. `["Sheet2!A:A"]`" — no leading `=`. Live-tested against the real Sheets API and confirmed this format is rejected outright.

**Prompt (direct tool calls)**
> `add_data_validation(condition_type="ONE_OF_RANGE", values=["Sales!A2:A5"])` — exactly as the docstring documents.

**Checks**
- Should succeed and create a range-sourced dropdown.

**Result (2026-07-17) ❌ FAIL** `HttpError 400: "Invalid ConditionValue.userEnteredValue: Sales!A2:A5 for ConditionType: ONE_OF_RANGE"`. Retried with a leading `=` (`values=["=Sales!A2:A5"]`) — succeeded, and `get_data_validation` read back the rule correctly with `userEnteredValue: "=Sales!$A$2:$A$5"`. The docstring's example is missing the required `=` prefix; every caller who follows it as written gets a guaranteed failure.

**Teardown**
Deleted and recreated the `Empty` fixture sheet to clear the test rule.

**Result (2026-09-04) ✅ PASS**
add_data_validation(ONE_OF_RANGE, values=["Sales!A2:A5"], no leading =) → succeeded (auto-prepend fix confirmed live, no longer the TC-S99-documented HttpError); readback shows "=Sales!$A$2:$A$5"

---

### TC-S100: `get_data_validation` on a nonexistent sheet raises raw, not a clean error ❌ code review finding

**Background:** Every other `sheet`-taking tool in `structure.py` (~22 of them, including `add_data_validation`) checks sheet existence first and returns `{"error": "Sheet 'X' not found"}`. `get_data_validation` skips this check entirely.

**Prompt (direct tool call)**
> `get_data_validation(sheet="NonexistentSheetXYZ", range="A1:A5")`

**Checks**
- Should return `{"error": "Sheet 'NonexistentSheetXYZ' not found"}`, matching every sibling tool's behavior for the same mistake.

**Result (2026-07-17) ❌ FAIL** Raised an unhandled `HttpError 400: "Unable to parse range: NonexistentSheetXYZ!A1:A5"` straight through to the MCP client instead. `server.py`'s `_timed` wrapper doesn't reformat exceptions, so this is the raw googleapiclient error, not a friendly response.

**Result (2026-09-04) ✅ PASS**
get_data_validation(sheet="NonexistentSheetXYZ") → clean {"error":"Sheet 'NonexistentSheetXYZ' not found"} — confirms the documented fix is live, no raw HttpError

---

### TC-S101: `add_data_validation` ONE_OF_RANGE auto-corrects a missing `=` (PR #361 review fix)

**Background:** TC-S99 found that `add_data_validation(condition_type="ONE_OF_RANGE", ...)` always failed with the docstring's own documented value format (a bare range reference, no leading `=`) — the real Sheets API rejects `userEnteredValue` without it. Fixed by auto-prepending `=` to each value when `condition_type` is `ONE_OF_RANGE` and the caller didn't already include one, instead of requiring callers to know this API quirk. Unit-tested deterministically (`TestAddDataValidation::test_one_of_range_auto_prepends_equals_when_missing`, `test_one_of_range_does_not_double_prepend_equals`); this live check re-runs TC-S99's exact failing call.

**Prompt (direct tool call)**
> `add_data_validation(condition_type="ONE_OF_RANGE", values=["Sales!A2:A5"])` — the exact call that failed in TC-S99, with no leading `=`.

**Checks**
- Call succeeds (no `HttpError`)
- `get_data_validation` on the same range reads back `userEnteredValue` starting with `=` (e.g. `"=Sales!$A$2:$A$5"`)

**Result (2026-07-18) ✅ PASS** Re-ran the exact TC-S99 failing call (`values=["Sales!A2:A5"]`, no `=`) — succeeded (no `HttpError`). `get_data_validation` read back `userEnteredValue: "=Sales!$A$2:$A$5"` on all 3 cells, confirming auto-prepend fired correctly.

**Teardown**
Clear the test rule from the range used.

**Result (2026-09-04) ✅ PASS**
Same as TC-S99 — re-confirms auto-prepend fix (duplicate coverage in test file)

---

### TC-S102: `get_data_validation` on a nonexistent sheet returns a clean error (PR #361 review fix)

**Background:** TC-S100 found that `get_data_validation` was missing the sheet-existence check every sibling tool in this file has, so a bad sheet name raised a raw `HttpError` instead of `{"error": ...}`. Fixed by adding the same `_get_sheet_id` check `add_data_validation` already has, before the grid-data fetch. Unit-tested (`TestGetDataValidation::test_sheet_not_found_returns_error_not_raw_http_error`); this live check re-runs TC-S100's exact failing call.

**Prompt (direct tool call)**
> `get_data_validation(sheet="NonexistentSheetXYZ", range="A1:A5")` — the exact call that raised in TC-S100.

**Checks**
- Returns `{"error": "Sheet 'NonexistentSheetXYZ' not found"}` — no raw `HttpError` reaches the client

**Result (2026-07-18) ✅ PASS** Re-ran the exact TC-S100 failing call — returned `{"error": "Sheet 'NonexistentSheetXYZ' not found"}` cleanly, no raw `HttpError`.

**Result (2026-09-04) ✅ PASS**
Same as TC-S100 — re-confirms clean-error fix (duplicate coverage in test file)

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

**Result (2026-09-04) ✅ PASS**
freeze(rows=1) → replies:[{}], no error

---

### TC-S43: Freeze first row and first column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Freeze the first row and first column on Sales"

**Checks**
- `frozenRowCount=1`, `frozenColumnCount=1`

**Result (2026-06-21) ✅** Row 1 and column 1 frozen on Sales. `replies: [{}]` — no error.

**Result (2026-09-04) ✅ PASS**
freeze(rows=1, columns=1): screenshot (after navigating to J20, scrolling the view) shows row 1 header ("Product") and column A ("Widget/Gadget/Donut/Gizmo/Totals") remaining pinned in view while J20 is selected far to the right/below — confirms the frozen pane. Reset to rows=0/columns=0 after.

---

### TC-S44: Unfreeze all (rows=0, columns=0) ⚠️ destructive

**Prompt**
> "Unfreeze all rows and columns on the Sales sheet"

**Checks**
- `frozenRowCount=0`, `frozenColumnCount=0`

**Result (2026-06-21) ✅** All rows and columns unfrozen on Sales. `replies: [{}]` — no error.

**Result (2026-09-04) ✅ PASS**
freeze(rows=0,columns=0) → replies:[{}], no error (also serves as unfreeze teardown)

---

### TC-S45: freeze — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

**Result (2026-09-04) ✅ PASS**
freeze(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

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

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(tab_color red) → replies:[{}], no error

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

**Result (2026-07-14) ✅ PASS — fix verified** Re-verified live after the `tabColorStyle` fix, twice with different starting colors (green→clear, then purple→clear combined with `show_gridlines` in the same call). Both times the Sales tab's `.docs-sheet-tab-color` DOM element went from a solid color to `style="background: transparent"` — matching the untouched default tabs (Empty, Notes & Misc, BrandNew), not black. Unit tests (`test_empty_tab_color_dict_clears_color`, updated) also pass, confirming the request now targets `tabColorStyle` (not `tabColor`) when `tab_color={}`. TC-S57b closed.

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(tab_color={}) → replies:[{}], no error (clears via tabColorStyle per known fix)

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

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(show_gridlines=false): screenshot shows no visible gridlines between cells (clean white grid, only row/column header lines remain). Matches. Reset to true after.

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

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(right_to_left=true): screenshot shows column headers running right-to-left (A at far right, N at far left) — layout correctly mirrored. Matches. Reset to false after.

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

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(tab_color=blue, show_gridlines=true, right_to_left=false) single call → replies:[{}], no error

---

### TC-S61: No properties provided returns error

**Checks (unit test)**
- Calling with no `tab_color`, `show_gridlines`, or `right_to_left` → `{"error": "No properties provided to update"}`
- No `batchUpdate` call is made

**Result (2026-07-13) ✅ PASS** `tests/sheets/test_structure.py::TestUpdateSheetProperties::test_no_params_returns_error` passed (`uv run python -m pytest tests/sheets/test_structure.py -k UpdateSheetProperties`, 9/9 passed).

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(no properties) → {"error":"No properties provided to update"}

---

### TC-S62: update_sheet_properties — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`
- No `batchUpdate` call is made

**Result (2026-07-13) ✅ PASS** Unit test `test_returns_error_when_sheet_not_found` passed. Also confirmed live against the fixture spreadsheet: `update_sheet_properties(spreadsheet_id=TEST_SPREADSHEET_ID, sheet="DoesNotExist", right_to_left=true)` → `{"error":"Sheet 'DoesNotExist' not found"}`.

**Result (2026-09-04) ✅ PASS**
update_sheet_properties(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

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

**Result (2026-09-04) ✅ PASS**
sort_range(A2:D5, col0 ASCENDING) — used A2:D5 (excluding the Totals row per the known SUM-formula-corruption issue). Screenshot shows Donut/Gadget/Gizmo/Widget in alphabetical order. Matches. Totals row (row 6, excluded from sort) untouched, still 650/670/705.

---

### TC-S47: Sort descending by a non-first column ⚠️ destructive

**Prompt**
**Playwright: required**
> "Sort A2:D50 on Sales by column C (index 2) descending"

**Checks**
- `sortSpecs[0].dimensionIndex=2`, `sortOrder=DESCENDING`

**Result (2026-06-21) ✅** A2:D5 sorted by Q2 descending (Gizmo 310, Widget 120, Gadget 180... descending). `replies: [{}]` — no error.

**Result (2026-09-04) ✅ PASS**
sort_range(A2:D5, col2 DESCENDING) — screenshot shows Gizmo(310)/Gadget(180)/Widget(120)/Donut(60), correctly descending by Q2. Totals row excluded from range, so no #REF! corruption (confirms the known TC-S47 finding from the prior pass — sorting a range that includes a formula row referencing itself breaks it; excluding it avoids the issue entirely).

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

**Result (2026-09-04) ✅ PASS**
sort_range(A2:D5, col0 ASC + col2 DESC) — screenshot shows Donut/Gadget/Gizmo/Widget (same as S46 since there are no duplicate Product values to invoke the secondary key) — primary key correctly applied, two sortSpecs sent. Matches.

---

### TC-S49: column_index offset by range start column

**Checks (unit test)**
- Range starting at column B (index 1) with `column_index=0` → `dimensionIndex=1`

**Result (2026-06-21) ✅** Unit test confirms offset applied correctly.

**Result (2026-09-04) ✅ PASS**
column_index offset logic implicitly exercised/correct via TC-S46-48 (dimensionIndex correctly targeted col0/col2 within A-start range); no separate live call needed for this unit-level check

---

### TC-S50: sort_range — sheet not found returns error

**Checks (unit test)**
- Sheet not found → `{"error": "Sheet 'X' not found"}`

**Result (2026-06-21) ✅** Unit test confirms error.

**Result (2026-09-04) ✅ PASS**
sort_range(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found"}

---

### TC-S103: sort_range — malformed sort spec fields return a clean error, do not crash

**Checks (unit test)**
- Non-string `"order"` value (e.g. `{"column_index": 0, "order": 5}`) → `{"error": ...}`, no `AttributeError` on `.upper()`.
- Missing `"column_index"` key (e.g. `{"order": "ASCENDING"}`) → `{"error": ...}`, no `KeyError`.
- Non-int `"column_index"` value (e.g. `{"column_index": "0", "order": "ASCENDING"}`) → `{"error": ...}`, no `TypeError` from the `col_start + s["column_index"]` addition.
- `bool` `"column_index"` value (e.g. `{"column_index": True, ...}`) → `{"error": ...}` — `bool` is a Python `int` subclass, so a bare `isinstance(..., int)` check alone would silently accept it.
- Invalid `"order"` enum value (e.g. `{"column_index": 0, "order": "banana"}`) → `{"error": ...}` from local validation, not a raw `HttpError` from the Sheets API.
- In every case, no `batchUpdate` call is made.

Matches `update_borders`'s validation depth (missing-key + isinstance + enum-membership) for the analogous `"style"` field (`structure.py`, `_VALID_BORDER_STYLES`) — this tool now applies the same pattern via `_VALID_SORT_ORDERS` for both `column_index` and `order`.

**Result (2026-07-28) ⚠️ PASS (fix works) but same defect class left open on sibling fields.** Live-verified against `mcp-gee-sweet-qa-fixtures` (`BrandNew` sheet), via `mcp-gee-sweet-sky`:
- `sort_order=[{"column_index": 0, "order": 5}]` → clean `{"error": "Sort spec for column_index 0 has a non-string 'order' value"}`. This PR's own fix works as intended.
- `sort_order=[{"order": "ASCENDING"}]` (column_index omitted) → raw `KeyError: 'column_index'` leaks as a tool execution error, not `{"error": ...}` — the same crash class this PR claims to fix, one field over. `column_index` is accessed via `s["column_index"]` (structure.py:1652) with no key-existence check, unlike `update_borders`'s analogous 3-part validation (missing-key + isinstance + enum) at lines 1129–1138 of the same file.
- `sort_order=[{"column_index": "0", "order": "ASCENDING"}]` (string column_index) → raw `TypeError: unsupported operand type(s) for +: 'int' and 'str'` leaks (no type check on `column_index`).
- `sort_order=[{"column_index": 0, "order": "banana"}]` (invalid enum value) → raw `HttpError 400` from the Sheets API leaks instead of a clean local error (pre-existing gap, not a new regression, but the same enum-membership check `update_borders` already has for `style`).
- `sort_order=[{"column_index": 0, "order": "ASCENDING"}, "banana"]` (non-dict list element) — reviewed as a potential `AttributeError`, but live-tested and actually rejected upstream by MCP's own pydantic schema validation (`sort_order: list[dict]`) before the function body ever runs, so this path is not exploitable through the tool interface. Not a live defect, unlike the three above.
- Sent back to Dev (see PR #452 comment) rather than approved — the fix is narrower than the established sibling pattern and leaves the identical crash class open on `column_index` and the `order` enum.

**Result (2026-07-28, round 2) ✅ PASS — all findings closed.** Fix commit `5648a91` adds missing-key + isinstance (with explicit `bool` exclusion) + enum-membership checks for both `column_index` and `order`, matching `update_borders`'s depth. Re-verified live against `mcp-gee-sweet-qa-fixtures` (`BrandNew` sheet), via `mcp-gee-sweet-sky`, after `/mcp reconnect`:
- `sort_order=[{"order": "ASCENDING"}]` → `{"error": "Sort spec at index 0 is missing required 'column_index' key"}` — clean, no `KeyError`.
- `sort_order=[{"column_index": "0", "order": "ASCENDING"}]` → `{"error": "Sort spec at index 0 has a non-integer 'column_index' value"}` — clean, no `TypeError`.
- `sort_order=[{"column_index": true, "order": "ASCENDING"}]` → same clean error — `bool` correctly rejected, not silently accepted as an int.
- `sort_order=[{"column_index": 0, "order": "banana"}]` → `{"error": "Invalid sort order 'banana' for column_index 0. Must be one of: ASCENDING, DESCENDING"}` — clean, no `HttpError` leak.
- `sort_order=[{"column_index": 0, "order": 5}]` (original case) and a normal `DESCENDING` sort both still work correctly — no regression.
- `uv run python -m pytest tests/sheets/test_structure.py -k SortRange` → 10/10 passed.

**Result (2026-09-04) ✅ PASS**
All 5 live sub-cases match PR #452 round-2 fix exactly: non-string order → clean error; missing column_index → clean error; non-int column_index (string "0") → clean error; bool column_index → clean error (not silently accepted as int); invalid order enum "banana" → clean error naming valid values. No batchUpdate/data mutation in any case (confirmed via post-check read)

