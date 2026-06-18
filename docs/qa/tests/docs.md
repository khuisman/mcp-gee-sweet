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

### TC-D158: Insert at multiple indices — high→low ordering verified ⚠️ requires-oauth ⚠️ destructive
**Setup:** fetch structure; identify two paragraphs P1 (earlier) and P2 (later) with known indices. Record P1's `startIndex` as N1 and P2's `startIndex` as N2 (N2 > N1). Both insertions are short fixed strings so index arithmetic is checkable.

**Prompt**
> "Insert 'AAA\n' at index {N1} and 'BBB\n' at index {N2} in doc {DOC_ID}"

**Checks**
- Re-fetch structure shows 'AAA' before P1 and 'BBB' before P2 (not shifted into wrong paragraphs)
- 'BBB' paragraph's `startIndex` = N2 + 4 (len('AAA\n') inserted before it)
- If tool processed low→high instead, 'BBB' would land 4 bytes early — use this arithmetic to confirm ordering
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
- Response includes `precedingParagraphIndex`, `tableStartIndex`, `tableEndIndex`, `rows: 2`, `columns: 3`
- `cells` list has 6 entries (rows × columns)
- Each cell has `row`, `col`, `startIndex`, `endIndex`, `paragraphStartIndex`
- `precedingParagraphIndex` = N, `tableStartIndex` = N + 1 (Docs API always inserts a required empty paragraph before the table; it cannot be deleted while the table exists)
- Re-fetch structure shows an empty paragraph at N, then the table at N + 1

**Cleanup:** delete `[precedingParagraphIndex, tableEndIndex]` in one range — this removes both the required preceding paragraph and the table body together

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

---

## Multi-operation ordering and sequencing

### TC-D173: Multi-delete high→low ordering verified ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert two known paragraphs ('DEL-A\n' and 'DEL-B\n') at known positions. Note their `startIndex`/`endIndex` after re-fetching. DEL-B has higher indices than DEL-A.

**Prompt**
> "Delete range {DEL-A start}–{DEL-A end} and range {DEL-B start}–{DEL-B end} from doc {DOC_ID} in one call"

**Checks**
- Both paragraphs absent from re-fetched structure
- Content that followed DEL-B is now at DEL-B's original startIndex (no offset error)
- If tool processed low→high, DEL-B's range would be stale after DEL-A shifts indices — verify neither deletion fails with an out-of-bounds error
- `deletions: 2` in response

---

### TC-D174: style_doc_range round-trip — heading confirmed in get_doc_structure ⚠️ requires-oauth ⚠️ destructive
**Purpose:** `style_doc_range` was never called live during initial testing. This is the first live verification.

**Setup:** insert a paragraph 'Style-test heading\n'; note its `startIndex`/`endIndex`

**Prompt**
> "Style the range {start}–{end} in doc {DOC_ID} as HEADING_1"

**Checks**
- Response contains `requests: 1`
- Call `get_doc_structure` — the paragraph at that index shows `namedStyleType: "HEADING_1"`
- Text content is unchanged ('Style-test heading')

**Cleanup:** style back to NORMAL_TEXT, then delete the paragraph

---

### TC-D175: style_doc_range text styles round-trip ⚠️ requires-oauth ⚠️ destructive
**Purpose:** verify bold/italic/underline are readable back via get_doc_structure runs.

**Setup:** insert a paragraph 'Bold-italic test\n'; note its index range

**Prompt**
> "Make the range {start}–{end} in doc {DOC_ID} bold and italic"

**Checks**
- Response contains `requests: 1`
- `get_doc_structure` shows a run in that paragraph with `bold: true` and `italic: true`
- `namedStyleType` is unchanged (updateTextStyle only, no updateParagraphStyle)

**Cleanup:** delete the test paragraph

---

### TC-D176: style_doc_table_cells post-fix live verification ⚠️ requires-oauth ⚠️ destructive
**Purpose:** `style_doc_table_cells` was fixed (removed top-level `tableStartLocation` that conflicted with the `tableRange` oneof) but the fix was **never re-tested live**. This is the confirmation test.

**Setup:** insert a 2×2 table; record its `tableStartIndex` from the response

**Prompt**
> "Style cell [0,0] of the table at index {tableStartIndex} in doc {DOC_ID} with background_color red=0.8 green=0.9 blue=1.0"

**Checks**
- Response succeeds (no API 400 error about `oneof field 'cells' is already set`)
- `requests: 1` in response
- 🔍 Visual check in Google Docs: cell [0,0] has light blue background

**Cleanup:** delete the table

---

### TC-D177: Full end-to-end sequence — insert table then style cells ⚠️ requires-oauth ⚠️ destructive
**Purpose:** the complete `insert_doc_table` → `style_doc_table_cells` sequence was never run end-to-end in live testing. Covers both tools and the index handoff between them.

**Setup:** fetch structure; note a suitable insertion index N

**Prompt**
> "Insert a 2×3 table at index {N} in doc {DOC_ID}, then style row 0 with grey background (red=0.85 green=0.85 blue=0.85) spanning all 3 columns, and add a solid black border (width 0.5) to every cell"

**Checks**
- `insert_doc_table` succeeds: `rows: 2`, `columns: 3`, 6 cells returned
- `style_doc_table_cells` for row 0 grey background succeeds (`requests: 1`)
- `style_doc_table_cells` for all 6 cells border succeeds (`requests: 6`)
- Re-fetch `get_doc_structure` shows the table at `tableStartIndex`
- 🔍 Visual check in Google Docs: styled header row and visible borders

**Cleanup:** delete table range

---

### TC-D178: Insert text then insert table — index chaining ⚠️ requires-oauth ⚠️ destructive
**Purpose:** verify that indices returned by one operation are usable as input to a subsequent operation without re-fetching the full structure each time.

**Setup:** start with a known doc structure; note `endIndex` of a paragraph as N

**Step 1 prompt**
> "Insert 'Intro paragraph.\n' at index {N} in doc {DOC_ID}"

**Step 2 prompt** (using `N + len('Intro paragraph.\n')` as the new insertion point)
> "Insert a 2×2 table at index {N + 17} in doc {DOC_ID}"

**Checks**
- Both operations succeed without error
- Re-fetch structure shows the paragraph immediately followed by the table
- `precedingParagraphIndex` = N + 17, `tableStartIndex` = N + 18

**Cleanup:** for each table, delete `[precedingParagraphIndex, tableEndIndex]` in one range (high→low for the two tables).

---

## `style_doc_range` — additional coverage

### TC-D179: Apply strikethrough ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
> "Apply strikethrough to range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- `get_doc_structure` shows run with `strikethrough: true`

---

### TC-D180: Apply font_size ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
> "Set font size to 18pt for range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- 🔍 Visual check: text is visibly larger

---

### TC-D181: Apply link_url ⚠️ requires-oauth ⚠️ destructive
**Setup:** insert a paragraph 'Visit example\n'; note the range covering 'example'

**Prompt**
> "Apply link_url 'https://example.com' to range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- `get_doc_structure` shows run split at the link boundary: linked run has `link_url: "https://example.com"`, non-linked run has `link_url: null`
- 🔍 **Note:** Google Docs automatically adds `underline: true` to the linked run — expected API behaviour, not a tool bug
- 🔍 Visual check: text appears as a hyperlink
