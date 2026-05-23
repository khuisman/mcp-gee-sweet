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
