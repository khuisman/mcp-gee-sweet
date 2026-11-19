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

**Result (2026-09-04) ✅ PASS**
insert 2x3 table at N=1: precedingParagraphIndex=1, tableStartIndex=2 (=N+1), tableEndIndex=18, rows:2, columns:3, 6 cells each with row/col/startIndex/endIndex/paragraphStartIndex. Re-fetch: empty para at 1, table at 2.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — On my fixture copy, `insert_doc_table(index=1, rows=2, columns=3)` returned precedingParagraphIndex=1, tableStartIndex=2, tableEndIndex=18, rows 2, columns 3, 6 cells each with row/col/startIndex/endIndex/paragraphStartIndex. Re-fetch: empty paragraph at 1 (inherits HEADING_1 from the paragraph it was split from, expected Docs behavior), table at 2. Screenshot `.playwright-mcp/S3/2026-11-08-tc-doc16.png` (URL-checked) shows a 2×3 table above "Test Document".

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

**Result (2026-09-04) ✅ PASS**
insert "Cell content" at cells[0].paragraphStartIndex=5; re-fetch cell[0,0] text "Cell content"; no index errors.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — `insert_doc_text` at cells[0].paragraphStartIndex=5 → insertions 1; re-fetch cell [0,0] text "Cell content", other cells empty, no index error. Cleanup delete [1,30] succeeded.

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

**Result (2026-09-04) ✅ PASS**
insert_table_row row_index=0 insert_below=True on 2x2 -> {docId, table_start_index:2, row_index:0}; re-fetch 3 rows.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 2×2 table at tableStartIndex 2; `insert_table_row(row_index=0)` → `{docId, table_start_index: 2, row_index: 0}`, no error. Re-fetch: rows 3. Screenshot `2026-11-08-tc-doc61.png` (URL-checked) shows a 3-row × 2-col table.

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

**Result (2026-09-04) ✅ PASS**
insert_table_row row_index=1 insert_below=False on 2x2; re-fetch 3 rows.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — Fresh 2×2 with "orig0"/"orig1" in col 0; `insert_table_row(row_index=1, insert_below=False)` → no error. Re-fetch: 3 rows, row 0 "orig0", row 1 empty (new), row 2 "orig1". Screenshot `2026-11-08-tc-doc62.png` shows the empty row between orig0 and orig1.

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

**Result (2026-09-04) ✅ PASS**
delete_table_row row_index=1 on 3-row -> {docId, table_start_index:2, row_index:1}; re-fetch 2 rows.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 3×2 table labeled r0/r1/r2; `delete_table_row(row_index=1)` → `{docId, table_start_index: 2, row_index: 1}`. Re-fetch: 2 rows, "r0" and "r2". Screenshot `2026-11-08-tc-doc63.png` shows r0/r2 only.

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

**Result (2026-09-04) ✅ PASS**
insert_table_column column_index=0 insert_right=True on 2x2 -> {docId, table_start_index:2, column_index:0}; re-fetch 3 columns.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 2×2 labeled c0/c1 in row 0; `insert_table_column(column_index=0)` → `{docId, table_start_index: 2, column_index: 0}`. Re-fetch: 3 columns, row 0 = c0, (new empty), c1. Screenshot `2026-11-08-tc-doc64.png` matches.

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

**Result (2026-09-04) ✅ PASS**
insert_table_column column_index=1 insert_right=False on 2x2; re-fetch 3 columns.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 2×2 labeled c0/c1; `insert_table_column(column_index=1, insert_right=False)` → no error. Re-fetch: 3 columns, row 0 = c0, (new empty), c1. Screenshot `2026-11-08-tc-doc65.png` matches.

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

**Result (2026-09-04) ✅ PASS**
delete_table_column column_index=1 on 2x3 -> {docId, table_start_index:2, column_index:1}; re-fetch 2 columns.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 2×3 labeled c0/c1/c2; `delete_table_column(column_index=1)` → `{docId, table_start_index: 2, column_index: 1}`. Re-fetch: 2 columns, row 0 = c0, c2. Screenshot `2026-11-08-tc-doc66.png` matches.

---

### TC-DOC67: API error returned gracefully (out of bounds row)
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Delete row 99 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure

**Result (2026-06-22) ✅ PASS** Called `delete_table_row(row_index=99)` on a 2×2 table. Returned `{"error": "..."}` with an API error message referencing an invalid row index. No exception raised.

**Result (2026-09-04) ✅ PASS**
delete_table_row row_index=99 -> {"error":"<HttpError 400 ... row index 99 should be less than the total number of rows 2>"}; no exception.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — On a 2×2 table, `delete_table_row(row_index=99)` returned `{"error": "<HttpError 400 ... deleteTableRow: The row index 99 should be less than the total number of rows 2.>"}`; no exception.

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


**Result (2026-09-04) ⚠️ PARTIAL**
merge_table_cells row0/col0 span 1x2 on 2x3 -> response matches exactly; re-fetch row 0 still 3 physical cells (distinct indices). Visual 🔍 not verified (browser unauth).
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run (browser not signed in).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 2×3 table; `merge_table_cells(0,0,row_span=1,column_span=2)` → exactly `{docId, table_start_index: 2, row_index: 0, column_index: 0, row_span: 1, column_span: 2}`. Screenshot `2026-11-08-tc-doc91.png`: row 0's first two columns render as one wide cell, row 1 keeps three cells. Re-fetch still reports 3 physical cells in row 0 (indices 4/6/8).

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


**Result (2026-09-04) ⚠️ PARTIAL**
merge_table_cells row0/col0 span 2x1 on 3x2 -> response matches exactly. Visual 🔍 not verified.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — 3×2 table; `merge_table_cells(0,0,row_span=2,column_span=1)` → exactly `{..., row_span: 2, column_span: 1}`. Screenshot `2026-11-08-tc-doc92.png`: column 0 rows 0–1 render as one tall cell, column 1 keeps two separate cells, row 2 unaffected. Table deleted after.

Layout cases ran on "S3 layout copy" (<copy doc id>: DOC68/70/74) and a second fixture copy "S3 layout content copy" (<copy doc id>: DOC69/71/72/73), so the content variants exercise the fresh-create path, not the "already exists" fallback.

### TC-DOC93: API error returned gracefully (merge range exceeds table bounds)
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Merge cells in the table at index {tableStartIndex} in doc {DOC_ID} starting at row 0, column 0, spanning 1 row and 99 columns"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure

**Cleanup:** delete the table

**Result (2026-07-14) ✅ PASS** Inserted a 2×2 table, called `merge_table_cells(row_index=0, column_index=0, row_span=1, column_span=99)`. Returned `{"error": "<HttpError 400 ... Invalid requests[0].mergeTableCells: The table range extends outside the bounds of the table.>"}`. No exception raised. Table deleted via `delete_doc_range`.

**Result (2026-09-04) ✅ PASS**
merge_table_cells span 1x99 -> {"error":"<HttpError 400 ... table range extends outside the bounds of the table>"}; no exception.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S3 on `ash`** — Same 2×2 table, `merge_table_cells(0,0,row_span=1,column_span=99)` returned `{"error": "<HttpError 400 ... mergeTableCells: The table range extends outside the bounds of the table.>"}`; no exception. Table deleted afterwards. (Run before DOC91/92 to reuse the 2×2.)

---

## `insert_table_row_or_column` / `delete_table_row_or_column` (#1527)

### TC-DOC262: Insert and delete a row and a column with the merged tools; the deprecated names still work ⚠️ destructive

**Purpose:** The four row-only and column-only table tools merge into `insert_table_row_or_column` and `delete_table_row_or_column`, where `dimension` picks a row or a column. The old names stay registered for one release, marked deprecated, and send the same requests.

**Steps**
1. `create_doc(title="TC-DOC262", folder_id={FOLDER_ID}, content_format="markdown", content="| a | b |\n|---|---|\n| 1 | 2 |\n")` → `{DOC}`; `get_doc_structure(doc_id={DOC})` → the table's `startIndex` `{T}`
2. `insert_table_row_or_column(doc_id={DOC}, dimension="row", table_start_index={T}, index=0)`, then `get_doc_structure`
3. `insert_table_row_or_column(doc_id={DOC}, dimension="column", table_start_index={T}, index=0, after=False)`, then `get_doc_structure`
4. `delete_table_row_or_column(doc_id={DOC}, dimension="row", table_start_index={T}, index=1)`, then `get_doc_structure`
5. `delete_table_row_or_column(doc_id={DOC}, dimension="column", table_start_index={T}, index=0)`, then `get_doc_structure`
6. `insert_table_row(doc_id={DOC}, table_start_index={T}, row_index=0)` and `delete_table_column(doc_id={DOC}, table_start_index={T}, column_index=1)`, then `get_doc_structure`
7. `insert_table_row_or_column(doc_id={DOC}, dimension="cell", table_start_index={T}, index=0)`
8. In the client's tool list, read the descriptions of `insert_table_row`, `insert_table_column`, `delete_table_row` and `delete_table_column`

**Checks**
- Step 2: `{docId, table_start_index: {T}, dimension: "row", index: 0}`; the table has 3 rows, and row 1 is the new empty one (cells `a`, `b` stay in row 0)
- Step 3: the table has 3 columns, and column 0 is the new empty one (`a` is now in column 1)
- Step 4: back to 2 rows: `a`/`b` and `1`/`2`, with the empty column still first
- Step 5: back to 2 columns, `a | b` over `1 | 2`
- Step 6: both return the pre-merge shape (`row_index` and `column_index`, no `dimension`), and the table ends 3 rows × 1 column, holding `a`, an empty cell, `1`
- Step 7: `{"error": "dimension must be 'row' or 'column', got 'cell'"}`, and the table is unchanged
- Step 8: each description starts with `Deprecated: use` and names `insert_table_row_or_column` or `delete_table_row_or_column` with the matching `dimension`

**Cleanup:** `delete_file` the doc

---
