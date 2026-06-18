# Docs Direct API Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` from `fixtures.local.md`.

These tools operate on document body indices. Use `get_doc_structure` first in any session to obtain current indices before calling insert/delete/style operations.

---

## `get_doc_structure`

### TC-D152: Structure of a non-empty doc ⚠️ requires-oauth
**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns `docId`, `title`, and `elements` list
- Each element has `type`, `startIndex`, `endIndex`
- Paragraphs include `namedStyleType`, `text`, and `runs`
- First element is a `sectionBreak` at index 0
- Last element is a paragraph ending at the document's total length

---

### TC-D153: Paragraph runs include style data ⚠️ requires-oauth
**Setup:** `{DOC_ID}` must contain at least one bold or italic run (use `write_doc_content` with `<b>` or `<i>` to set up)

**Prompt**
> "Get the structure of doc {DOC_ID} and show me the formatting on each run"

**Checks**
- Runs with bold styling return `bold: true`
- Runs without explicit style return `bold: null` (not `false`) — null means inherited
- `link_url` is populated for runs inside `<a>` tags

---

### TC-D154: Structure of a doc containing a table ⚠️ requires-oauth
**Setup:** `{DOC_ID}` must contain a table

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Table element has `type: "table"`, `rows`, `columns`
- `cells` list contains one entry per cell with `row`, `col`, `startIndex`, `endIndex`, `paragraphStartIndex`
- `paragraphStartIndex` is one greater than cell `startIndex` (empty cell: paragraph is the only content)
- Cell text is populated correctly for non-empty cells

---

### TC-D155: Structure of an empty doc ⚠️ requires-oauth
**Setup:** doc with only the default empty paragraph

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns elements with at least the sectionBreak and one empty paragraph
- No error

---

### TC-D156: Invalid doc ID returns error ⚠️ requires-oauth
**Prompt**
> "Get the structure of doc not-a-real-id"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references the invalid ID or a 404

---

## `insert_doc_text`

### TC-D157: Insert a single paragraph ⚠️ requires-oauth ⚠️ destructive
**Setup:** fetch current structure; note the `endIndex` of the last non-final paragraph

**Prompt**
> "Insert the text 'Inserted line.\n' at index {N} in doc {DOC_ID}"

**Checks**
- Re-fetch structure shows new paragraph at the expected position
- Surrounding paragraphs shifted by the length of the inserted text
- `insertions: 1` in response

**Cleanup:** delete the inserted range after verifying

---

### TC-D158: Insert at multiple indices in one call ⚠️ requires-oauth ⚠️ destructive
**Prompt**
> "Insert 'First addition.\n' at index {N1} and 'Second addition.\n' at index {N2} in doc {DOC_ID} (N2 > N1)"

**Checks**
- Both insertions land at the correct positions
- Lower-index insertion is not shifted by the higher-index one (high→low ordering confirmed)
- `insertions: 2` in response

**Cleanup:** delete both inserted ranges

---

### TC-D159: Empty insertions list returns error ⚠️ requires-oauth
**Prompt**
> "Call insert_doc_text on doc {DOC_ID} with an empty insertions list"

**Checks**
- Returns `{"error": "insertions list is empty"}`

---

## `delete_doc_range`

### TC-D160: Delete a paragraph ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a known paragraph first (TC-D157), note its `startIndex` and `endIndex`

**Prompt**
> "Delete the range from index {start} to {end} in doc {DOC_ID}"

**Checks**
- Re-fetch structure no longer contains the deleted paragraph
- Surrounding content shifted back correctly
- `deletions: 1` in response

---

### TC-D161: Cannot delete final segment newline ⚠️ requires-oauth
**Setup:** fetch structure; note the final element's `endIndex`

**Prompt**
> "Delete the range from index 1 to {final_endIndex} in doc {DOC_ID}"

**Checks**
- Returns an API error about the segment newline
- 🔍 **Note:** correct usage is `endIndex - 1` for the final element

---

### TC-D162: Empty deletions list returns error ⚠️ requires-oauth
**Prompt**
> "Call delete_doc_range on doc {DOC_ID} with an empty deletions list"

**Checks**
- Returns `{"error": "deletions list is empty"}`

---

## `style_doc_range`

### TC-D163: Apply named style type ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a normal paragraph; note its index range

**Prompt**
> "Style the range from index {start} to {end} in doc {DOC_ID} as HEADING_2"

**Checks**
- Re-fetch shows `namedStyleType: "HEADING_2"` for that paragraph
- `requests: 1` in response

**Cleanup:** re-style as NORMAL_TEXT

---

### TC-D164: Apply text styles (bold, italic, foreground color) ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a normal paragraph; note its index range

**Prompt**
> "Make the range from index {start} to {end} in doc {DOC_ID} bold, italic, and red (foreground_color red=1 green=0 blue=0)"

**Checks**
- Re-fetch shows `bold: true`, `italic: true` on runs in that range
- `requests: 1` in response (paragraph style skipped, only updateTextStyle emitted)

**Cleanup:** delete the test paragraph

---

### TC-D165: Apply both paragraph and text style in one range ⚠️ requires-oauth ⚠️ destructive
**Prompt**
> "Style range {start}–{end} in doc {DOC_ID} as HEADING_3 and bold"

**Checks**
- `requests: 2` (one updateParagraphStyle + one updateTextStyle)
- Both applied correctly on re-fetch

---

### TC-D166: No recognised style fields returns error ⚠️ requires-oauth
**Prompt**
> "Call style_doc_range on doc {DOC_ID} with a range that has no style fields"

**Checks**
- Returns `{"error": "no recognised style fields in any range"}`

---

## `insert_doc_table`

### TC-D167: Insert a 2×3 table ⚠️ requires-oauth ⚠️ destructive
**Setup:** fetch structure; note a suitable insertion index (e.g. endIndex of a paragraph)

**Prompt**
> "Insert a 2-row, 3-column table at index {N} in doc {DOC_ID}"

**Checks**
- Response includes `tableStartIndex`, `tableEndIndex`, `rows: 2`, `columns: 3`
- `cells` list has 6 entries (rows × columns)
- Each cell has `row`, `col`, `startIndex`, `endIndex`, `paragraphStartIndex`
- `tableStartIndex` is `N + 1` (Docs API inserts a paragraph boundary before the table)
- Re-fetch structure shows the table at the returned `tableStartIndex`

**Cleanup:** delete table range after verifying

---

### TC-D168: Cell indices usable for insert_doc_text ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a table (TC-D167); use the returned `cells[0].paragraphStartIndex`

**Prompt**
> "Insert text 'Cell content' at the paragraphStartIndex of cell [0,0] returned by the table insertion"

**Checks**
- Re-fetch shows 'Cell content' in row 0, col 0
- No index errors

**Cleanup:** delete table

---

## `style_doc_table_cells`

### TC-D169: Apply grey header row background ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Style row 0 of the table at index {tableStartIndex} in doc {DOC_ID} with background_color red=0.953 green=0.953 blue=0.953, column_span 2"

**Checks**
- `requests: 1` in response
- 🔍 Visual check in Google Docs: header row has grey background

**Cleanup:** delete table

---

### TC-D170: Apply borders and padding ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Style all cells in the table at index {tableStartIndex} in doc {DOC_ID} with border_color black (0,0,0), border_width 0.5, border_dash_style SOLID, padding 3.6pt on all sides"

**Checks**
- Call succeeds for each cell
- 🔍 Visual check: table has visible borders and reasonable padding

---

### TC-D171: Empty cells list returns error ⚠️ requires-oauth
**Prompt**
> "Call style_doc_table_cells on doc {DOC_ID} with table_start_index {N} and an empty cells list"

**Checks**
- Returns `{"error": "cells list is empty"}`

---

### TC-D172: Cell with no style fields is skipped ⚠️ requires-oauth
**Setup:** insert a table; pass one valid cell and one cell with no style fields

**Prompt**
> "Style the table at index {N}: cell [0,0] with background red=1, and cell [0,1] with no style fields"

**Checks**
- Only one request emitted (the no-style cell is silently skipped)
- `requests: 1` in response
