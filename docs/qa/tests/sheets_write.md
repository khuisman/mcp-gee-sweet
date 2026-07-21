# Write Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/write.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}` from `fixtures.local.md`.

Many write tests mutate the fixture spreadsheet. Tests marked **⚠️ destructive** should be run last or followed by a fixture reset.

---

## `update_cells`

### TC-W01: Write simple values

**Prompt**
> "Write the values 'Test', 'A', 'B', 'C' into row 7 of the Sales sheet in {SPREADSHEET_ID}, starting at column A"

**Checks**
- Row 7 in Sales now contains: Test, A, B, C
- Existing rows 1–6 unchanged
- No `error` field

---

### TC-W02: Write a formula via USER_ENTERED ⚠️ destructive

**Prompt**
> "Write the formula =A2&' '&A3 into cell E2 of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- E2 shows computed value "Widget Gadget" (formula evaluated, not stored as string)
- Confirms `USER_ENTERED` input mode

---

### TC-W03: Range smaller than data provided

**Prompt**
> "Write these four values — Alpha, Beta, Gamma, Delta — into just cells A8:A9 of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Returns an error — the API rejects an oversized array with a 400 "tried writing to row [N]" error
- No values are written
- 🔍 **Product decision:** should the tool pre-truncate the data to fit the range instead of letting the API error?

---

### TC-W04: Cache invalidated after write

**Prompt** (run TC-R16 or TC-R17 first to warm the cache, then run this)
> "Update cell A7 in the Sales sheet of {SPREADSHEET_ID} to 'CacheTest', then immediately summarize that spreadsheet"

**Checks**
- Summary reflects the new value in A7 — not stale cached data
- Confirms `sheet_data_cache.mark_dirty` fired after the write

---

### TC-W05: Non-existent sheet name

**Prompt**
> "Write 'Hello' into cell A1 of a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Returns a clear API error
- Does not silently succeed or create the sheet

---

### TC-W33: Partial (rich-text) hyperlink in a single cell ⚠️ destructive

**Prompt**
**Playwright: required**
> "In the Sales sheet of {SPREADSHEET_ID}, write cell F2 using `update_cells` so it reads 'See the docs' where only the 'the docs' part is a hyperlink to https://example.com — pass F2's value as a two-run list: {\"text\": \"See \"} then {\"text\": \"the docs\", \"hyperlink\": \"https://example.com\"}"

**Checks**
- `get_sheet_data` with `include_grid_data=True` on F2 shows `userEnteredValue.stringValue` = "See the docs"
- `textFormatRuns` has two entries: first with no `startIndex` (implicit 0) and an empty `format`, second with `startIndex: 4` and `format.link.uri` = "https://example.com"
- `userEnteredFormat.hyperlinkDisplayType` = "LINKED"
- 🔍 Visual check: only "the docs" renders underlined/blue and is clickable; "See " renders as plain text

**Result (2026-07-19) ✅** — `get_sheet_data(include_grid_data=True)` on F2 confirmed `userEnteredValue.stringValue` = "See the docs", `textFormatRuns` = `[{"format":{}}, {"startIndex":4,"format":{"link":{"uri":"https://example.com"},...}}]`, `userEnteredFormat.hyperlinkDisplayType` = "LINKED". 🔍 Visual check blocked by the documented "Chart-covered grid (Sales sheet)" limitation (`docs/qa/run.md`) — a floating chart from earlier `add_chart` runs covers rows 1–22 including F2; API response used as the confirmation source per that doc's guidance instead.

---

### TC-W34: Mixed plain and rich-text cells in the same call ⚠️ destructive

**Prompt**
**Playwright: required**
> "In the Sales sheet of {SPREADSHEET_ID}, use `update_cells` on range F3:G3 to write 'PlainValue' into F3 and, into G3, a hyperlinked cell reading 'Link' that links to https://example.com/g3"

**Checks**
- F3 = "PlainValue" (written via a per-cell `values.batchUpdate` scoped to just F3, not a whole-range `values.update` — the whole-range write was retired because it required blanking G3 to "" first and relying on the rich-text pass to overwrite it back, losing G3's content for good if that second call failed)
- G3 shows "Link" with `userEnteredFormat.hyperlinkDisplayType` = "LINKED" and a `textFormatRuns` entry linking to https://example.com/g3
- Both cells are correct in a single tool call — confirms the plain-cell pass and the rich-text `batchUpdate` pass compose correctly over the same range
- The tool's own return value is `{"values_update": {...}, "rich_text_update": {...}}` — both results present, not just the plain-cell one (previously the rich-text result was silently dropped whenever plain cells were also present in the same call)
- 🔍 Visual check: G3 renders underlined/blue and clickable; F3 renders as plain text

**Result (2026-07-19) ✅ (write) / ⚠️ tool-response gap** — `get_sheet_data(include_grid_data=True)` on F3:G3 confirmed both cells correct: F3 `userEnteredValue.stringValue` = "PlainValue" (`hyperlinkDisplayType: PLAIN_TEXT`); G3 `userEnteredValue.stringValue` = "Link", `hyperlinkDisplayType: LINKED`, `textFormatRuns[0].format.link.uri` = "https://example.com/g3" — the two passes do compose correctly on the sheet. However the tool's own return value was `{"updatedRange":"Sales!F3:G3","updatedRows":1,"updatedColumns":2,"updatedCells":2}` — only the plain `values().update()` response; the `batchUpdate` reply for G3's rich-text write is silently dropped from what the caller sees, even though the write itself succeeded. Matches code-review finding (data.py:687, `result = batch_result` only fires `if not has_plain_cells`) — real, live-confirmed, not just a code-reading inference. 🔍 Visual check blocked by the same chart-pollution limitation as TC-W33.

---

### TC-W35: Rich-text run missing "text" key returns an error

**Prompt**
> "Call `update_cells` on {SPREADSHEET_ID}'s Sales sheet, range F4, with a malformed rich-text cell: a run list containing only `{\"hyperlink\": \"https://example.com\"}` with no `text` key"

**Checks**
- Returns `{"error": ...}` naming the missing `text` key
- No write occurs — F4 is unchanged (neither the plain-value pass nor the batchUpdate pass fires)

**Result (2026-07-19) ✅** — Returned `{"error": "Rich-text cell runs must be dicts with a 'text' key, e.g. {'text': ..., 'hyperlink': ...}"}`. Follow-up `get_sheet_data` on F4 confirmed no write occurred (empty). Note: this test only covers a *missing* `text` key — it does not cover a *present-but-wrong-type* `text` value (e.g. `{"text": None, ...}` or `{"text": 123, ...}`), which code review found crashes with an unhandled `TypeError` instead of returning this same graceful error (see PR comment).

---

### TC-W36: Rich-text run offsets after an astral-plane character (emoji) ⚠️ destructive

**Background:** Sheets API `TextFormatRun.startIndex` counts UTF-16 code units, not Python characters — an emoji outside the Basic Multilingual Plane is 2 units. A run offset computed with plain `len()` would land the hyperlink one character early.

**Prompt**
**Playwright: required**
> "In the Sales sheet of {SPREADSHEET_ID}, write cell F5 using `update_cells` with a two-run rich-text cell: first run text is a single 🚀 emoji with no hyperlink, second run text is 'link' hyperlinked to https://example.com"

**Checks**
- `textFormatRuns`'s second entry has `startIndex: 2` (the emoji occupies 2 UTF-16 units), not `1`
- 🔍 Visual check: the hyperlink underline/color starts exactly at "link", not one character into the emoji

**Result (2026-07-19) ✅** — `get_sheet_data(include_grid_data=True)` on F5 confirmed `userEnteredValue.stringValue` = "🚀link", `textFormatRuns[1].startIndex` = 2 (not 1) with `format.link.uri` = "https://example.com". `_utf16_len` correctly accounts for the emoji's UTF-16 surrogate pair. 🔍 Visual check blocked by the same chart-pollution limitation as TC-W33.

---

### TC-W37: Rich-text run with a wrong-typed "text" value returns an error, not a crash

**Prompt**
> "Call `update_cells` on {SPREADSHEET_ID}'s Sales sheet, range F6, with a malformed rich-text cell: a run list containing `{\"text\": null, \"hyperlink\": \"https://example.com\"}`"

**Checks**
- Returns `{"error": ...}` — does not raise/crash (a prior version only checked `"text"` was present, not that it was a string, and crashed with an unhandled `TypeError` on a non-string value)
- No write occurs — F6 is unchanged

---

### TC-W38: Empty rich-text run list returns an error, not a silent blank

**Prompt**
> "Call `update_cells` on {SPREADSHEET_ID}'s Sales sheet, range F7, passing `[]` (an empty list) as F7's cell value"

**Checks**
- Returns `{"error": ...}` — an empty run list is rejected up front
- No write occurs — F7 is unchanged (a prior version treated `[]` as a valid zero-run rich-text cell and silently blanked it)

---

### TC-W39: Empty `data` returns an error, not a silent no-op

**Prompt**
> "Call `update_cells` on {SPREADSHEET_ID}'s Sales sheet, range F8, with `data` set to an empty list `[]`"

**Checks**
- Returns `{"error": "data cannot be empty"}`
- No API call is made and the spreadsheet is unchanged

---

## `batch_update_cells`

### TC-W06: Multiple ranges in one call

**Prompt**
> "In {SPREADSHEET_ID}, update two ranges at once: write 'Batch1' into Sales!A8 and 'Batch2' into Sales!A9"

**Checks**
- Both cells updated in a single operation
- A8 = Batch1, A9 = Batch2

---

### TC-W07: Ranges on the same sheet

**Prompt**
> "Update Sales!B8 to 999 and Sales!C8 to 888 in {SPREADSHEET_ID} in one batch call"

**Checks**
- Both cells updated correctly
- No conflict from writing multiple ranges to the same sheet

---

### TC-W08: Empty ranges dict

**Prompt**
> "Do a batch cell update on {SPREADSHEET_ID} with an empty set of ranges — no ranges to update"

**Checks**
- Returns success or a clear no-op response — not a server error
- 🔍 **Product decision:** should an empty ranges dict be an error or a no-op?

---

### TC-W09: Cache invalidated after batch write

**Prompt**
> "Batch update Sales!A8 to 'dirty' in {SPREADSHEET_ID}, then immediately summarize the spreadsheet"

**Checks**
- Summary reflects A8 = 'dirty'
- Confirms `sheet_data_cache.mark_dirty` is called for `batch_update_cells`

### TC-W10: Trailing empty-array rows are normalized

**Prompt**
> "In {SPREADSHEET_ID}, batch update Sales!A8:B10 with these values: row 1 is ['hello', 'world'], rows 2 and 3 are empty (no data). Check that updatedRange in the response covers all three rows (A8:B10), not just the first."

**Checks**
- `updatedRange` in the response is `Sales!A8:B10`, not `Sales!A8:B8`
- Rows A9 and A10 are cleared (blank) in the sheet
- No duplicate row appended after the write

---

## `add_rows`

### TC-W10: Add row at beginning (no position specified)

**Prompt**
> "Add 1 row at the very beginning of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- New blank row appears above the current row 1 (headers pushed to row 2)
- `inheritFromBefore=False` (inserting at index 0 — no row above to inherit from)

---

### TC-W11: Add row at explicit position ⚠️ destructive

**Prompt**
> "Add 1 row after row 3 of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- New blank row at position 4
- Existing rows 4–6 shifted down

---

### TC-W12: start_row=0 — inheritFromBefore=False

**Prompt**
> "Add 1 row at position 0 (the very first row) of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Row inserted at the top
- `inheritFromBefore` is False (0 is not > 0)
- 🔍 **Product decision:** is `start_row=0` meaningfully different from `start_row=None`?

---

### TC-W13: start_row=1 — inheritFromBefore=True

**Prompt**
> "Add 1 row at position 1 in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Row inserted at index 1 (after the first row)
- `inheritFromBefore=True` — new row inherits formatting from row above

---

### TC-W14: Add multiple rows at once

**Prompt**
> "Add 5 blank rows at the end of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- 5 new rows appear
- Existing data unchanged

---

### TC-W15: Invalid sheet name

**Prompt**
> "Add 1 row to a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` without calling the Sheets API
- Does not throw an unhandled exception

---

### TC-W16: Large count value

**Prompt**
> "Add 1000 rows to the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Succeeds or returns a clear API limit error
- 🔍 **Product decision:** should the tool cap `count` to prevent accidental large inserts?

---

## `add_columns`

### TC-W17: Add column at beginning (no position specified)

**Prompt**
> "Add 1 column at the very beginning of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- New blank column A; existing columns shift right (Product moves to B)
- `inheritFromBefore=False`

---

### TC-W18: start_column=0 — inheritFromBefore=False

**Prompt**
> "Add 1 column at position 0 of the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- Column inserted at the leftmost position
- `inheritFromBefore` is False

---

### TC-W19: start_column=1 — inheritFromBefore=True

**Prompt**
> "Add 1 column at position 1 in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Column inserted after column A
- `inheritFromBefore=True`

---

### TC-W20: Add multiple columns

**Prompt**
> "Add 3 columns at position 2 in the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- 3 new blank columns inserted at the correct position
- Existing columns shifted right

---

## `batch_update` (raw passthrough)

### TC-W21: Add a sheet via raw request

**Prompt**
> "Use a raw batch update on {SPREADSHEET_ID} to add a new sheet called 'RawAdded'"

**Checks**
- New sheet 'RawAdded' appears in the spreadsheet
- Response includes the new sheet's properties

---

### TC-W22: Rename a sheet via raw request

**Prompt**
> "Use a raw batch update to rename the 'Empty' sheet to 'RawRenamed' in {SPREADSHEET_ID}"

**Checks**
- Sheet formerly called 'Empty' is now 'RawRenamed'
- `list_sheets` reflects the new name

---

### TC-W23: Insert dimension via raw request

**Prompt**
> "Use a raw batch update on {SPREADSHEET_ID} to insert 2 rows at index 1 in the Sales sheet"

**Checks**
- 2 new rows appear at index 1
- Existing data shifts down

---

### TC-W24: Delete dimension — structure cache invalidated ⚠️ destructive

**Prompt**
> "Use a raw batch update to delete row 7 from the Sales sheet in {SPREADSHEET_ID}, then list the sheets"

**Checks**
- Row 7 deleted
- `list_sheets` call after reflects current state — not stale cache
- Confirms the structure cache bug fix: both `cache.mark_dirty` and `sheet_data_cache.mark_dirty` are called

---

### TC-W25: Empty requests list

**Prompt**
> "Send a raw batch update to {SPREADSHEET_ID} with an empty requests list"

**Checks**
- Returns `{"error": "requests list cannot be empty"}` or similar
- Does not call the Sheets API

---

### TC-W26: Non-dict item in requests

**Prompt**
> "Send a raw batch update to {SPREADSHEET_ID} with a requests list containing the string 'notadict'"

**Checks**
- Returns an `error` field
- Does not forward the malformed request to the API

---

### TC-W27: Invalid request structure

**Prompt**
> "Send a raw batch update to {SPREADSHEET_ID} with requests: [{\"unknownKey\": {}}]"

**Checks**
- API error propagates back — not a server crash
- Error message is from the Sheets API (unknown request type)

---

### TC-W28: Both caches marked dirty

**Prompt**
> "Use a raw batch update to add a sheet called 'CacheCheck' to {SPREADSHEET_ID}, then immediately list all sheets and summarize the spreadsheet"

**Checks**
- `list_sheets` includes 'CacheCheck' — structure cache was invalidated
- Summary reflects the new sheet — data cache was invalidated
- Confirms both `cache.mark_dirty` and `sheet_data_cache.mark_dirty` are called

---

## `clear_values`

### TC-W29: Clear a specific range ⚠️ destructive

**Prompt**
> "Clear the values in cells A1:C5 of the Sales sheet in {SPREADSHEET_ID}, leaving formatting intact"

**Setup:** Confirm A1:C5 has values and formatting before clearing.

**Checks**
- Cells A1:C5 are empty (no values)
- Cell formatting (background color, borders, number format) is unchanged
- No `error` field

**Result (2026-06-21) ✅** A1:C5 cleared. `get_sheet_data` confirmed columns A–C rows 1–5 empty; column D (Q3) and row 6 (Totals) untouched. SUM formulas recalculated to 0 for cleared columns.

---

### TC-W30: Clear entire sheet ⚠️ destructive

**Prompt**
> "Clear all values from the Notes sheet in {SPREADSHEET_ID}"

**Checks**
- Sheet is empty (all cells blank)
- No `error` field
- Formatting preserved (not a full delete)

**Result (2026-06-21) ✅** `clear_values` called with no range on Notes & Misc. `get_sheet_data` returned `values: []`. No error field. `clearedRange: "'Notes & Misc'!A1:Z1000"`.

---

### TC-W31: Clear values — sheet name with spaces

**Prompt**
> "Clear cells B2:D4 from the 'Notes & Misc' sheet in {SPREADSHEET_ID}"

**Checks**
- Range string sent to API is `'Notes & Misc'!B2:D4` (sheet name single-quoted)
- Values cleared successfully

**Result (2026-06-21) ✅** `clearedRange` in response was `'Notes & Misc'!B2:D4` — single-quoting applied correctly. No error.

---

### TC-W32: Clear non-existent range — API behaviour

**Prompt**
> "Clear cells Z100:Z200 from the Sales sheet in {SPREADSHEET_ID}"

**Checks**
- API returns a `clearedRange` with an adjusted or empty range (no error — the API accepts out-of-bounds ranges)

**Result (2026-06-21) ✅** Response: `{"clearedRange":"Sales!Z100:Z200"}` — API accepted the out-of-bounds range and returned it as-is with no error.
