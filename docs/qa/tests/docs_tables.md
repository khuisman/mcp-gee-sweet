# Docs Tools — Tables — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs/tables.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` from `fixtures.local.md`.

These tools operate on document body indices. Use `get_doc_structure` first in any session to obtain current indices before calling insert/delete/style operations.

---

## `insert_doc_table`

### TC-DOC16: Insert a 2×3 table ⚠️ destructive
**Setup:** fetch structure; note a suitable insertion index (e.g. endIndex of a paragraph)

**Prompt**
**Playwright: required**
> "Insert a 2-row, 3-column table at index {N} in doc {DOC_ID}"

**Checks**
- Response includes `precedingParagraphIndex`, `tableStartIndex`, `tableEndIndex`, `rows: 2`, `columns: 3`
- `cells` list has 6 entries (rows × columns)
- Each cell has `row`, `col`, `startIndex`, `endIndex`, `paragraphStartIndex`
- `precedingParagraphIndex` = N, `tableStartIndex` = N + 1 (Docs API always inserts a required empty paragraph before the table; it cannot be deleted while the table exists)
- Re-fetch structure shows an empty paragraph at N, then the table at N + 1

**Cleanup:** delete `[precedingParagraphIndex, tableEndIndex]` in one range — this removes both the required preceding paragraph and the table body together

**Result (2026-06-20) ✅ PASS**
- Inserted 2×3 table at N=88. Response: `precedingParagraphIndex=88`, `tableStartIndex=89` (=N+1), `tableEndIndex=105`, `rows: 2`, `columns: 3`, 6 cells. All `paragraphStartIndex = startIndex + 1`. Re-fetch confirmed table at index 89.

---

### TC-DOC17: Cell indices usable for insert_doc_text ⚠️ destructive
**Setup:** insert a table (TC-DOC16); use the returned `cells[0].paragraphStartIndex`

**Prompt**
> "Insert text 'Cell content' at the paragraphStartIndex of cell [0,0] returned by the table insertion"

**Checks**
- Re-fetch shows 'Cell content' in row 0, col 0
- No index errors

**Cleanup:** delete table

**Result (2026-06-20) ✅ PASS**
- Used `cells[0].paragraphStartIndex = 92` from TC-DOC16. Inserted "Cell content" at index 92. Re-fetch: cell [0,0] `text: "Cell content"`. No index errors.

---

## `insert_table_row` / `delete_table_row` / `insert_table_column` / `delete_table_column` (#146)

### TC-DOC61: Insert a row below an existing row ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Insert a row below row 0 in the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `row_index: 0`
- Re-fetch `get_doc_structure` shows the table now has 3 rows

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_row(row_index=0, insert_below=True)`. Response: `{docId, table_start_index, row_index: 0}`. Re-fetched structure showed 3 rows.

---

### TC-DOC62: Insert a row above an existing row ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Insert a row above row 1 in the table at index {tableStartIndex} in doc {DOC_ID} (insert_below=False)"

**Checks**
- Call succeeds with no API error
- Re-fetch shows the table has 3 rows
- New row appears at row 1 (between original rows 0 and 1)

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_row(row_index=1, insert_below=False)`. Re-fetched structure showed 3 rows.

---

### TC-DOC63: Delete a row ⚠️ destructive
**Setup:** insert a 3-row table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Delete row 1 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `row_index: 1`
- Re-fetch shows the table has 2 rows

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 3-row table; called `delete_table_row(row_index=1)`. Response: `{docId, table_start_index, row_index: 1}`. Re-fetched structure showed 2 rows.

---

### TC-DOC64: Insert a column to the right ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Insert a column to the right of column 0 in the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `column_index: 0`
- Re-fetch shows the table has 3 columns

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_column(column_index=0, insert_right=True)`. Response: `{docId, table_start_index, column_index: 0}`. Re-fetched structure showed 3 columns.

---

### TC-DOC65: Insert a column to the left ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Insert a column to the left of column 1 in the table at index {tableStartIndex} in doc {DOC_ID} (insert_right=False)"

**Checks**
- Call succeeds with no API error
- Re-fetch shows the table has 3 columns

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_column(column_index=1, insert_right=False)`. Re-fetched structure showed 3 columns.

---

### TC-DOC66: Delete a column ⚠️ destructive
**Setup:** insert a 2×3 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Delete column 1 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `column_index: 1`
- Re-fetch shows the table has 2 columns

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×3 table; called `delete_table_column(column_index=1)`. Response: `{docId, table_start_index, column_index: 1}`. Re-fetched structure showed 2 columns.

---

### TC-DOC67: API error returned gracefully (out of bounds row)
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Delete row 99 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure

**Result (2026-06-22) ✅ PASS** Called `delete_table_row(row_index=99)` on a 2×2 table. Returned `{"error": "..."}` with an API error message referencing an invalid row index. No exception raised.

---

## `merge_table_cells` (#150)

### TC-DOC91: Merge a horizontal range of cells (colspan) ⚠️ destructive
**Setup:** insert a 2×3 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Merge cells in the table at index {tableStartIndex} in doc {DOC_ID} starting at row 0, column 0, spanning 1 row and 2 columns"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `row_index: 0`, `column_index: 0`, `row_span: 1`, `column_span: 2`
- 🔍 Visual check in Google Docs: row 0's first two columns render as one wide cell; row 1 is unaffected
- Re-fetch `get_doc_structure` still reports 3 physical columns in row 0 (merge doesn't delete the covered cell, it only changes rendering)

**Cleanup:** delete the table

**Result (2026-07-14) ✅ PASS** Inserted a 2×3 table, called `merge_table_cells(table_start_index, row_index=0, column_index=0, row_span=1, column_span=2)`. Response matched exactly: `{"docId", "table_start_index", "row_index": 0, "column_index": 0, "row_span": 1, "column_span": 2}`. Playwright screenshot confirmed row 0's first two columns render as one wide cell while row 1 kept three separate cells. Re-fetched `get_doc_structure`: table still reported 3 physical columns in row 0 (cells at col 0, 1, 2 all present with distinct indices). Table deleted via `delete_doc_range`.

### TC-DOC92: Merge a vertical range of cells (rowspan) ⚠️ destructive
**Setup:** insert a 3×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Merge cells in the table at index {tableStartIndex} in doc {DOC_ID} starting at row 0, column 0, spanning 2 rows and 1 column"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `row_index: 0`, `column_index: 0`, `row_span: 2`, `column_span: 1`
- 🔍 Visual check in Google Docs: column 0's first two rows render as one tall cell; column 1 is unaffected in both rows

**Cleanup:** delete the table

**Result (2026-07-14) ✅ PASS** Inserted a 3×2 table, called `merge_table_cells(table_start_index, row_index=0, column_index=0, row_span=2, column_span=1)`. Response matched exactly: `{"docId", "table_start_index", "row_index": 0, "column_index": 0, "row_span": 2, "column_span": 1}`. Playwright screenshot confirmed column 0's first two rows render as one tall cell while column 1 kept two separate cells across the same rows; row 2 unaffected. Table deleted via `delete_doc_range`.

### TC-DOC93: API error returned gracefully (merge range exceeds table bounds)
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Merge cells in the table at index {tableStartIndex} in doc {DOC_ID} starting at row 0, column 0, spanning 1 row and 99 columns"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure

**Cleanup:** delete the table

**Result (2026-07-14) ✅ PASS** Inserted a 2×2 table, called `merge_table_cells(row_index=0, column_index=0, row_span=1, column_span=99)`. Returned `{"error": "<HttpError 400 ... Invalid requests[0].mergeTableCells: The table range extends outside the bounds of the table.>"}`. No exception raised. Table deleted via `delete_doc_range`.

---
