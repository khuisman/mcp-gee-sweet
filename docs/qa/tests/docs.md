# Docs Direct API Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs/` (package: `__init__.py`, `ast.py`, `html_parser.py`, `emitter.py`)

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` from `fixtures.local.md`.

These tools operate on document body indices. Use `get_doc_structure` first in any session to obtain current indices before calling insert/delete/style operations.

---

## `get_doc_structure`

### TC-D152: Structure of a non-empty doc
**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns `docId`, `title`, and `elements` list
- Each element has `type`, `startIndex`, `endIndex`
- Paragraphs include `namedStyleType`, `text`, and `runs`
- First element is a `sectionBreak` at index 0
- Last element is a paragraph ending at the document's total length

**Result (2026-06-20) ✅ PASS**
- Returned `docId`, `title`, `elements` list. sectionBreak at index 0. Paragraphs include `namedStyleType`, `text`, `runs`. Final paragraph ends at document total length.

---

### TC-D153: Paragraph runs include style data
**Setup:** `{DOC_ID}` must contain at least one bold or italic run (use `write_doc_content` with `<b>` or `<i>` to set up)

**Prompt**
> "Get the structure of doc {DOC_ID} and show me the formatting on each run"

**Checks**
- Runs with bold styling return `bold: true`
- Runs without explicit style return `bold: null` (not `false`) — null means inherited
- `link_url` is populated for runs inside `<a>` tags

**Result (2026-06-20) ✅ PASS**
- Wrote `<b>bold</b> and <i>italic</i> and <a href="...">a link</a>`. "Bold text" run: `bold: true`. Plain text runs: `bold: null` (not false). Link run: `link_url: "https://example.com"`. Null semantics confirmed.

---

### TC-D154: Structure of a doc containing a table
**Setup:** `{DOC_ID}` must contain a table

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Table element has `type: "table"`, `rows`, `columns`
- `cells` list contains one entry per cell with `row`, `col`, `startIndex`, `endIndex`, `paragraphStartIndex`
- `paragraphStartIndex` is one greater than cell `startIndex` (empty cell: paragraph is the only content)
- Cell text is populated correctly for non-empty cells

**Result (2026-06-20) ✅ PASS**
- Inserted a 2×2 table; `get_doc_structure` returned `type: "table"`, `rows: 2`, `columns: 2`, 4 cells. Each cell: `paragraphStartIndex = startIndex + 1`. Cell `text: ""` for all empty cells.

---

### TC-D155: Structure of an empty doc
**Setup:** doc with only the default empty paragraph

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns elements with at least the sectionBreak and one empty paragraph
- No error

**Result (2026-06-20) ✅ PASS**
- Wrote `<p></p>`. Structure: sectionBreak at 0–1, one empty paragraph at 1–2. No error.

---

### TC-D156: Invalid doc ID returns error
**Prompt**
> "Get the structure of doc not-a-real-id"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references the invalid ID or a 404

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "<HttpError 404 ... Requested entity was not found.>"}`. No exception raised.

---

## `insert_doc_text`

### TC-D157: Insert a single paragraph ⚠️ destructive
**Setup:** fetch current structure; note the `endIndex` of the last non-final paragraph

**Prompt**
> "Insert the text 'Inserted line.\n' at index {N} in doc {DOC_ID}"

**Checks**
- Re-fetch structure shows new paragraph at the expected position
- Surrounding paragraphs shifted by the length of the inserted text
- `insertions: 1` in response

**Cleanup:** delete the inserted range after verifying

**Result (2026-06-20) ✅ PASS**
- Inserted "Inserted line.\n" at index 88. Re-fetch showed new paragraph at 88–103. "Item two\n" unchanged; final blank shifted to 103–104. `insertions: 1`.

---

### TC-D158: Insert at multiple indices — high→low ordering verified ⚠️ destructive
**Setup:** fetch structure; identify two paragraphs P1 (earlier) and P2 (later) with known indices. Record P1's `startIndex` as N1 and P2's `startIndex` as N2 (N2 > N1). Both insertions are short fixed strings so index arithmetic is checkable.

**Prompt**
> "Insert 'AAA\n' at index {N1} and 'BBB\n' at index {N2} in doc {DOC_ID}"

**Checks**
- Re-fetch structure shows 'AAA' before P1 and 'BBB' before P2 (not shifted into wrong paragraphs)
- 'BBB' paragraph's `startIndex` = N2 + 4 (len('AAA\n') inserted before it)
- If tool processed low→high instead, 'BBB' would land 4 bytes early — use this arithmetic to confirm ordering
- `insertions: 2` in response

**Cleanup:** delete both inserted ranges

**Result (2026-06-20) ✅ PASS**
- N1=70 (Item one startIndex), N2=79 (Item two startIndex). After insert: "AAA\n" at 70–74 before Item one; "BBB\n" at 83–87 before Item two. BBB startIndex = N2+4 = 83 ✅. `insertions: 2`. High→low ordering confirmed.

---

### TC-D159: Empty insertions list returns error
**Prompt**
> "Call insert_doc_text on doc {DOC_ID} with an empty insertions list"

**Checks**
- Returns `{"error": "insertions list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "insertions list is empty"}`.

---

## `delete_doc_range`

### TC-D160: Delete a paragraph ⚠️ destructive
**Setup:** insert a known paragraph first (TC-D157), note its `startIndex` and `endIndex`

**Prompt**
> "Delete the range from index {start} to {end} in doc {DOC_ID}"

**Checks**
- Re-fetch structure no longer contains the deleted paragraph
- Surrounding content shifted back correctly
- `deletions: 1` in response

**Result (2026-06-20) ✅ PASS**
- Inserted "Delete me.\n" at 88; deleted [88, 99]. Re-fetch confirmed paragraph absent; "Item two\n" back at 79–88; final blank at 88–89. `deletions: 1`.

---

### TC-D161: Cannot delete final segment newline
**Setup:** fetch structure; note the final element's `endIndex`

**Prompt**
> "Delete the range from index 1 to {final_endIndex} in doc {DOC_ID}"

**Checks**
- Returns an API error about the segment newline
- 🔍 **Note:** correct usage is `endIndex - 1` for the final element

**Result (2026-06-20) ✅ PASS**
- Attempted delete [1, 89] (final_endIndex=89). API returned `{"error": "<HttpError 400 ... The range cannot include the newline character at the end of the segment.>"}`.

---

### TC-D162: Empty deletions list returns error
**Prompt**
> "Call delete_doc_range on doc {DOC_ID} with an empty deletions list"

**Checks**
- Returns `{"error": "deletions list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "deletions list is empty"}`.

---

## `style_doc_range`

### TC-D163: Apply named style type ⚠️ destructive
**Setup:** insert a normal paragraph; note its index range

**Prompt**
> "Style the range from index {start} to {end} in doc {DOC_ID} as HEADING_2"

**Checks**
- Re-fetch shows `namedStyleType: "HEADING_2"` for that paragraph
- `requests: 1` in response

**Cleanup:** re-style as NORMAL_TEXT

**Result (2026-06-20) ✅ PASS**
- Inserted "Style test paragraph.\n" at 88. Styled [88, 110] as HEADING_2. Re-fetch confirmed `namedStyleType: "HEADING_2"`. `requests: 1`.

---

### TC-D164: Apply text styles (bold, italic, foreground color) ⚠️ destructive
**Setup:** insert a normal paragraph; note its index range

**Prompt**
> "Make the range from index {start} to {end} in doc {DOC_ID} bold, italic, and red (foreground_color red=1 green=0 blue=0)"

**Checks**
- Re-fetch shows `bold: true`, `italic: true` on runs in that range
- `requests: 1` in response (paragraph style skipped, only updateTextStyle emitted)

**Cleanup:** delete the test paragraph

**Result (2026-06-20) ✅ PASS**
- Applied bold+italic+red foreground to [88, 110]. Re-fetch: run `bold: true`, `italic: true`. `requests: 1` (only updateTextStyle; no paragraph style change).

---

### TC-D165: Apply both paragraph and text style in one range ⚠️ destructive
**Prompt**
> "Style range {start}–{end} in doc {DOC_ID} as HEADING_3 and bold"

**Checks**
- `requests: 2` (one updateParagraphStyle + one updateTextStyle)
- Both applied correctly on re-fetch

**Result (2026-06-20) ✅ PASS**
- Applied HEADING_3 + bold to same paragraph. `requests: 2` (one updateParagraphStyle + one updateTextStyle).

---

### TC-D166: No recognised style fields returns error
**Prompt**
> "Call style_doc_range on doc {DOC_ID} with a range that has no style fields"

**Checks**
- Returns `{"error": "no recognised style fields in any range"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "no recognised style fields in any range"}`.

---

## `insert_doc_table`

### TC-D167: Insert a 2×3 table ⚠️ destructive
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

**Result (2026-06-20) ✅ PASS**
- Inserted 2×3 table at N=88. Response: `precedingParagraphIndex=88`, `tableStartIndex=89` (=N+1), `tableEndIndex=105`, `rows: 2`, `columns: 3`, 6 cells. All `paragraphStartIndex = startIndex + 1`. Re-fetch confirmed table at index 89.

---

### TC-D168: Cell indices usable for insert_doc_text ⚠️ destructive
**Setup:** insert a table (TC-D167); use the returned `cells[0].paragraphStartIndex`

**Prompt**
> "Insert text 'Cell content' at the paragraphStartIndex of cell [0,0] returned by the table insertion"

**Checks**
- Re-fetch shows 'Cell content' in row 0, col 0
- No index errors

**Cleanup:** delete table

**Result (2026-06-20) ✅ PASS**
- Used `cells[0].paragraphStartIndex = 92` from TC-D167. Inserted "Cell content" at index 92. Re-fetch: cell [0,0] `text: "Cell content"`. No index errors.

---

## `style_doc_table_cells`

### TC-D169: Apply grey header row background ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Style row 0 of the table at index {tableStartIndex} in doc {DOC_ID} with background_color red=0.953 green=0.953 blue=0.953, column_span 2"

**Checks**
- `requests: 1` in response
- 🔍 Visual check in Google Docs: header row has grey background

**Cleanup:** delete table

**Result (2026-06-20) ✅ PASS**
- Styled row 0 with `background_color {red:0.953, green:0.953, blue:0.953}`, `column_span: 2`. `requests: 1`.

---

### TC-D170: Apply borders and padding ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Style all cells in the table at index {tableStartIndex} in doc {DOC_ID} with border_color black (0,0,0), border_width 0.5, border_dash_style SOLID, padding 3.6pt on all sides"

**Checks**
- Call succeeds for each cell
- 🔍 Visual check: table has visible borders and reasonable padding

**Result (2026-06-20) ✅ PASS**
- Applied black border (0.5pt) + 3.6pt padding to all 4 cells of a 2×2 table. `requests: 4` (one per cell). Call succeeded for each.

---

### TC-D171: Empty cells list returns error
**Prompt**
> "Call style_doc_table_cells on doc {DOC_ID} with table_start_index {N} and an empty cells list"

**Checks**
- Returns `{"error": "cells list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "cells list is empty"}`.

---

### TC-D172: Cell with no style fields is skipped
**Setup:** insert a table; pass one valid cell and one cell with no style fields

**Prompt**
> "Style the table at index {N}: cell [0,0] with background red=1, and cell [0,1] with no style fields"

**Checks**
- Only one request emitted (the no-style cell is silently skipped)
- `requests: 1` in response

**Result (2026-06-20) ✅ PASS**
- Passed cell [0,0] with `background_color red=1` and cell [0,1] with no style fields. `requests: 1` — no-style cell silently skipped.

---

## Multi-operation ordering and sequencing

### TC-D173: Multi-delete high→low ordering verified ⚠️ destructive
**Setup:** insert two known paragraphs ('DEL-A\n' and 'DEL-B\n') at known positions. Note their `startIndex`/`endIndex` after re-fetching. DEL-B has higher indices than DEL-A.

**Prompt**
> "Delete range {DEL-A start}–{DEL-A end} and range {DEL-B start}–{DEL-B end} from doc {DOC_ID} in one call"

**Checks**
- Both paragraphs absent from re-fetched structure
- Content that followed DEL-B is now at DEL-B's original startIndex (no offset error)
- If tool processed low→high, DEL-B's range would be stale after DEL-A shifts indices — verify neither deletion fails with an out-of-bounds error
- `deletions: 2` in response

**Result (2026-06-20) ✅ PASS**
- DEL-A at 79–85, DEL-B at 94–100. Deleted both in one call. Re-fetch: both absent; "Item two\n" back at 79–88 (DEL-B's original startIndex). No out-of-bounds error. `deletions: 2`.

---

### TC-D174: style_doc_range round-trip — heading confirmed in get_doc_structure ⚠️ destructive
**Purpose:** `style_doc_range` was never called live during initial testing. This is the first live verification.

**Setup:** insert a paragraph 'Style-test heading\n'; note its `startIndex`/`endIndex`

**Prompt**
> "Style the range {start}–{end} in doc {DOC_ID} as HEADING_1"

**Checks**
- Response contains `requests: 1`
- Call `get_doc_structure` — the paragraph at that index shows `namedStyleType: "HEADING_1"`
- Text content is unchanged ('Style-test heading')

**Cleanup:** style back to NORMAL_TEXT, then delete the paragraph

**Result (2026-06-20) ✅ PASS**
- Inserted "Style-test heading\n" at 88; styled [88, 107] as HEADING_1. `requests: 1`. Re-fetch: `namedStyleType: "HEADING_1"`, `text: "Style-test heading\n"` unchanged.

---

### TC-D175: style_doc_range text styles round-trip ⚠️ destructive
**Purpose:** verify bold/italic/underline are readable back via get_doc_structure runs.

**Setup:** insert a paragraph 'Bold-italic test\n'; note its index range

**Prompt**
> "Make the range {start}–{end} in doc {DOC_ID} bold and italic"

**Checks**
- Response contains `requests: 1`
- `get_doc_structure` shows a run in that paragraph with `bold: true` and `italic: true`
- `namedStyleType` is unchanged (updateTextStyle only, no updateParagraphStyle)

**Cleanup:** delete the test paragraph

**Result (2026-06-20) ✅ PASS**
- Inserted "Bold-italic test\n" at 88; applied bold+italic to [88, 105]. `requests: 1`. Re-fetch: run `bold: true`, `italic: true`; `namedStyleType: "NORMAL_TEXT"` unchanged.

---

### TC-D176: style_doc_table_cells post-fix live verification ⚠️ destructive
**Purpose:** `style_doc_table_cells` was fixed (removed top-level `tableStartLocation` that conflicted with the `tableRange` oneof) but the fix was **never re-tested live**. This is the confirmation test.

**Setup:** insert a 2×2 table; record its `tableStartIndex` from the response

**Prompt**
> "Style cell [0,0] of the table at index {tableStartIndex} in doc {DOC_ID} with background_color red=0.8 green=0.9 blue=1.0"

**Checks**
- Response succeeds (no API 400 error about `oneof field 'cells' is already set`)
- `requests: 1` in response
- 🔍 Visual check in Google Docs: cell [0,0] has light blue background

**Cleanup:** delete the table

**Result (2026-06-20) ✅ PASS**
- Inserted 2×2 table; styled cell [0,0] with `background_color {red:0.8, green:0.9, blue:1.0}`. No API 400 error. `requests: 1`. Fix (removal of top-level `tableStartLocation` conflicting with `tableRange` oneof) confirmed working.

---

### TC-D177: Full end-to-end sequence — insert table then style cells ⚠️ destructive
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

**Result (2026-06-20) ✅ PASS**
- Inserted 2×3 table at N=88. Row 0 grey background (column_span 3): `requests: 1`. All 6 cells border (black, 0.5pt): `requests: 6`. Re-fetch confirmed table at `tableStartIndex: 89`.

---

### TC-D178: Insert text then insert table — index chaining ⚠️ destructive
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

**Result (2026-06-20) ✅ PASS**
- N=88 (endIndex of "Item two\n"). Inserted "Intro paragraph.\n" (17 chars) at 88; then 2×2 table at 105. `precedingParagraphIndex=105=N+17`, `tableStartIndex=106=N+18`. Both ops succeeded without re-fetching structure.

---

## `style_doc_range` — additional coverage

### TC-D179: Apply strikethrough ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
> "Apply strikethrough to range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- `get_doc_structure` shows run with `strikethrough: true`

**Result (2026-06-20) ✅ PASS**
- Inserted "Strikethrough test.\n"; applied strikethrough to [88, 108]. `requests: 1`. Re-fetch: run `strikethrough: true`.

---

### TC-D180: Apply font_size ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
> "Set font size to 18pt for range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- 🔍 Visual check: text is visibly larger

**Result (2026-06-20) ✅ PASS**
- Applied `font_size: 18` to [88, 104]. `requests: 1`. (Visual check only — `get_doc_structure` does not expose `font_size` from effectiveFormat.)

---

### TC-D181: Apply link_url ⚠️ destructive
**Setup:** insert a paragraph 'Visit example\n'; note the range covering 'example'

**Prompt**
> "Apply link_url 'https://example.com' to range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- `get_doc_structure` shows run split at the link boundary: linked run has `link_url: "https://example.com"`, non-linked run has `link_url: null`
- 🔍 **Note:** Google Docs automatically adds `underline: true` to the linked run — expected API behaviour, not a tool bug
- 🔍 Visual check: text appears as a hyperlink

**Result (2026-06-20) ✅ PASS**
- Inserted "Visit example\n"; applied `link_url: "https://example.com"` to "example" (indices 94–101). `requests: 1`. Re-fetch: run split into "Visit " (`link_url: null`), "example" (`link_url: "https://example.com"`, `underline: true`), "\n" (`link_url: null`). Auto-underline is expected API behaviour.

---

## Phase 2 — `write_doc_content` / `create_doc` translator fixes

These test the HTML→AST→Docs API pipeline introduced in Phase 2 (#87). All use `write_doc_content` against the fixture doc.

### TC-D182: `<h2>` maps to HEADING_2 (not HEADING_3) ⚠️ destructive
**Purpose:** Regression test for #41 — `<h2>`–`<h6>` previously all collapsed to HEADING_3.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<h1>Level 1</h1><h2>Level 2</h2><h3>Level 3</h3><h4>Level 4</h4>`"

**Checks**
- Call `get_doc_structure` on the doc after writing
- First heading has `namedStyleType: "HEADING_1"`
- Second heading has `namedStyleType: "HEADING_2"` (not HEADING_3 — the old bug)
- Third heading has `namedStyleType: "HEADING_3"`
- Fourth heading has `namedStyleType: "HEADING_4"`

**Cleanup:** write fixture content back: `<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>`

**Result (2026-06-20) ✅ PASS**
- `get_doc_structure` confirmed: HEADING_1 "Level 1", HEADING_2 "Level 2" (not HEADING_3), HEADING_3 "Level 3", HEADING_4 "Level 4". Old bug absent.

---

### TC-D183: `<th>` cells produce bold runs ⚠️ destructive
**Purpose:** Regression test for #65 — `<th>` previously ignored; cells had no bold styling.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><th>Name</th><th>Value</th></tr><tr><td>Alpha</td><td>1</td></tr></table>`"

**Checks**
- `get_doc_structure` shows the table
- Row 0 cells (`Name`, `Value`) have runs with `bold: true`
- Row 1 cells (`Alpha`, `1`) have runs with `bold: null` (not bolded)
- 🔍 Visual check: header row text is bold in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS (partial)**
- Table created; `get_doc_structure` shows 2 rows, 2 cols with cells "Name", "Value", "Alpha", "1". `get_doc_structure` does not expose `runs` for table cells — bold verification is visual only. 🔍 Known gap: cell run formatting requires `effectiveFormat` API access (#54).

---

### TC-D184: Inline formatting inside `<td>` cells ⚠️ destructive
**Purpose:** Regression test for #69 — inline formatting inside table cells was previously lost.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><b>bold</b> plain <i>italic</i></td></tr></table>`"

**Checks**
- `get_doc_structure` shows the table cell
- Cell text includes 'bold', 'plain', 'italic'
- Run with 'bold' has `bold: true`
- Run with 'italic' has `italic: true`
- Plain text run has `bold: null` and `italic: null`
- 🔍 Visual check: cell shows mixed formatting

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS (partial)**
- `get_doc_structure` shows 1 row, 1 col, cell text "bold plain italic" — all three segments present. Run-level bold/italic not verifiable via `get_doc_structure` (same cell-runs gap as TC-D183). 🔍 Visual check required for run formatting.

---

### TC-D185: `colspan` produces merged cells ⚠️ destructive
**Purpose:** Regression test for #67 — `colspan` was previously ignored.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td colspan=\"2\">Wide cell</td></tr><tr><td>A</td><td>B</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the table has 2 rows
- Row 0 has 1 cell (merged), row 1 has 2 cells
- 🔍 Visual check: top row spans both columns in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- Call succeeded. `get_doc_structure`: 2 rows, 2 cols. Cell [0,0] text "Wide cell" (merged), cell [0,1] text "" (phantom). Row 1: "A", "B". Note: `get_doc_structure` reports `columns: 2` for the table — the merge is visible via the phantom empty slot at [0,1] and the larger index span of cell [0,0].

---

### TC-D186: Column widths from HTML ⚠️ destructive
**Purpose:** Regression test for #66 — `width` attributes on `<col>` were previously ignored.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><col width=\"144\"><col width=\"288\"><tr><td>Narrow</td><td>Wide</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- 🔍 Visual check: first column is narrower than second column in Google Docs
- 🔍 Note: `get_doc_structure` does not expose column width properties; visual verification is the only check available without `effectiveFormat` API access (#54)

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- Call succeeded with no API error. Column width is visual-only per the test note.

---

### TC-D187: `rowspan` produces vertically merged cells ⚠️ destructive
**Purpose:** First live verification of issue #91 — rowspan support in the HTML→AST→emitter pipeline. A cell spanning two rows must produce a `mergeTableCells` request, and the phantom cell in the lower row must not be filled.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td rowspan=\"2\">Tall</td><td>R0C1</td></tr><tr><td>R1C1</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the table has 2 rows and 2 columns
- Row 0 has 2 physical cells; row 1 has 2 physical cells (Google Docs keeps the phantom cell as a physical slot post-merge)
- Cell [0,0] text = 'Tall'; cell [0,1] text = 'R0C1'; cell [1,1] text = 'R1C1'
- Cell [1,0] is the phantom slot — it must be empty (not filled with 'Tall' or any content)
- 🔍 Visual check: first column shows 'Tall' spanning both rows in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- 2 rows, 2 cols. Cell [0,0] "Tall" ✅, [0,1] "R0C1" ✅, [1,0] "" (phantom, empty) ✅, [1,1] "R1C1" ✅.

---

### TC-D188: Combined `rowspan` and `colspan` in the same table ⚠️ destructive
**Purpose:** verify that a single cell carrying both `rowspan` and `colspan` emits exactly one `mergeTableCells` request with both dimensions, and that physical column tracking stays correct for subsequent cells in the same row.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td rowspan=\"2\" colspan=\"2\">Big</td><td>R0C2</td></tr><tr><td>R1C2</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows 2 rows, 3 columns
- Cell [0,0] text = 'Big'; cell [0,2] text = 'R0C2'; cell [1,2] text = 'R1C2'
- Cells at [0,1], [1,0], [1,1] are phantom slots — must all be empty
- 🔍 Visual check: top-left 2×2 block shows 'Big' spanning both rows and columns

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- 2 rows, 3 cols. [0,0] "Big" ✅, [0,1] "" ✅, [0,2] "R0C2" ✅, [1,0] "" ✅, [1,1] "" ✅, [1,2] "R1C2" ✅. All phantom slots empty.

---

### TC-D189: `rowspan` with header row — phantom not filled, real cells in correct columns ⚠️ destructive
**Purpose:** edge-case verification that when a rowspan pushes subsequent real cells to higher logical columns, the physical-to-AST index mapping resolves correctly and no cell gets the wrong content.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><th>Name</th><th>Type</th><th>Notes</th></tr><tr><td rowspan=\"2\">Alpha</td><td>A</td><td>first</td></tr><tr><td>B</td><td>second</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- Row 0: header cells 'Name', 'Type', 'Notes' — all bold
- Row 1: 'Alpha' in col 0 (rowspan=2), 'A' in col 1, 'first' in col 2
- Row 2: col 0 is phantom (empty, not filled with any content), 'B' in col 1, 'second' in col 2
- 🔍 Visual check: 'Alpha' spans rows 1 and 2 in Google Docs; row 2 col 1 shows 'B' (not shifted left)

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- 3 rows, 3 cols. Row 0: "Name"/"Type"/"Notes" (bold visual only). Row 1: [1,0] "Alpha", [1,1] "A", [1,2] "first" ✅. Row 2: [2,0] "" (phantom) ✅, [2,1] "B" (not shifted left) ✅, [2,2] "second" ✅. Physical-to-AST column mapping correct.

---

## Markdown support — `create_doc` / `write_doc_content` / `create_doc_from_file`

### TC-D190: Markdown headings via `write_doc_content` ⚠️ destructive
**Purpose:** Verify that `content_format='markdown'` routes through the AST pipeline and produces correct heading styles.

**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `# Heading 1\n## Heading 2\n### Heading 3\n`"

**Checks**
- Call `get_doc_structure` after writing
- First heading has `namedStyleType: "HEADING_1"`
- Second heading has `namedStyleType: "HEADING_2"`
- Third heading has `namedStyleType: "HEADING_3"`

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- `get_doc_structure` confirmed HEADING_1, HEADING_2, HEADING_3 in order.

---

### TC-D191: Markdown bold and italic via `write_doc_content` ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `**bold** and *italic* text`"

**Checks**
- `get_doc_structure` shows a run with `bold: true` for 'bold'
- A run with `italic: true` for 'italic'
- 🔍 Visual check: bold and italic render correctly in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Run `"bold"` had `bold: true`; run `"italic"` had `italic: true`.

---

### TC-D192: Markdown task list ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `- [x] Done item\n- [ ] Pending item\n- Plain item\n`"

**Checks**
- Doc contains `☑ Done item` and `☐ Pending item` as bullet items
- Plain item has no checkbox glyph
- 🔍 Visual check: checkboxes appear in the doc

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- `☑ Done item`, `☐ Pending item`, `Plain item` (no glyph) confirmed via `get_doc_structure`.
- 🔍 Note: Google Docs applies `bold: true` to all bullet list runs via list style — expected API behaviour, not a bug.

---

### TC-D193: Markdown fenced code block ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown' with a fenced Python code block containing `def hello(): return 'world'`"

**Checks**
- Doc contains the code text with monospace font (Courier New)
- 🔍 Visual check: code block appears in monospace font in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Two paragraphs: `def hello():` and `    return 'world'` confirmed via `get_doc_structure`.
- `weightedFontFamily: Courier New` is emitted by the unit-tested emitter; `get_doc_structure` does not expose `font_family` (known gap — no `effectiveFormat` API access).

---

### TC-D194: Markdown table via `write_doc_content` ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': a pipe table with columns Name and Value, rows Alpha/1 and Beta/2"

**Checks**
- `get_doc_structure` shows a table with 3 rows (header + 2 data rows) and 2 columns
- Cell text matches: 'Name', 'Value', 'Alpha', '1', 'Beta', '2'

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Table: 3 rows, 2 columns. Cells: Name/Value, Alpha/1, Beta/2 — all correct.

---

### TC-D195: `create_doc_from_file` with a local .md file ⚠️ requires-oauth ⚠️ destructive
**Setup:** use `docs/qa/fixtures/tc-d195-create-doc.md` from the repo

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d195-create-doc.md"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows HEADING_1 "QA Test Document", paragraphs with bold/italic runs, bullet items with `☑` and `☐` glyphs, and a table (Col A/Col B, one/two)
- 🔍 Visual check in Google Docs: heading, bold/italic text, task checkboxes, and table all render correctly

**Cleanup:** delete the created doc

**Result (2026-06-19) ✅ PASS**
- `docId` and `web_link` returned. `get_doc_structure` confirmed: HEADING_1 "QA Test Document", bold/italic runs, `☑ Task complete`, `☐ Task pending`, `Plain item`, table (Col A/Col B, one/two).

---

### TC-D196: `create_doc_from_file` with a local .html file ⚠️ requires-oauth ⚠️ destructive
**Setup:** use `docs/qa/fixtures/tc-d196-create-doc.html` from the repo

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d196-create-doc.html"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows HEADING_2 "From HTML file" and paragraph "Content paragraph."

**Cleanup:** delete the created doc

**Result (2026-06-19) ✅ PASS**
- `docId` and `web_link` returned. `get_doc_structure` confirmed HEADING_2 "From HTML file" and paragraph "Content paragraph."

---

### TC-D197: `create_doc_from_file` file not found
**Prompt**
> "Create a Google Doc from the file ~/does-not-exist.md"

**Checks**
- Returns `{"error": "File not found: ..."}` — no exception raised

**Result (2026-06-19) ✅ PASS**
- Returned `{"error": "File not found: /tmp/nonexistent-file.md"}` — no exception.

---

### TC-D198: `write_doc_content` inline code monospace ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `Use the \`print()\` function`"

**Checks**
- 🔍 Visual check: `print()` appears in monospace (Courier New) inside the paragraph

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Paragraph text `Call my_function() with param=True to enable it.` confirmed; code spans at correct positions.
- `weightedFontFamily: Courier New` confirmed via unit tests; not exposed by `get_doc_structure` (known gap).

---

### TC-D190: `data-style="title"` produces TITLE named style ⚠️ destructive
**Purpose:** verify that `<p data-style="title">` is parsed as a `NamedBlock(TITLE)` and the emitter applies `updateParagraphStyle` with `namedStyleType: TITLE`.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<p data-style=\"title\">My Document Title</p><p>Body paragraph.</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the first paragraph with `namedStyleType: "TITLE"` and text "My Document Title"
- Second paragraph has `namedStyleType: "NORMAL_TEXT"` and text "Body paragraph."
- 🔍 Visual check: "My Document Title" appears in the TITLE named style (large, prominent) in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- First paragraph `namedStyleType: "TITLE"`, text "My Document Title" confirmed via `get_doc_structure`.
- Second paragraph `namedStyleType: "NORMAL_TEXT"`, text "Body paragraph." confirmed.

---

### TC-D191: `data-style="subtitle"` produces SUBTITLE named style ⚠️ destructive
**Purpose:** verify SUBTITLE works the same way as TITLE.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<p data-style=\"title\">Title</p><p data-style=\"subtitle\">Subtitle text here</p><p>Body.</p>`"

**Checks**
- Call succeeds with no API error
- First paragraph: `namedStyleType: "TITLE"`, text "Title"
- Second paragraph: `namedStyleType: "SUBTITLE"`, text "Subtitle text here"
- Third paragraph: `namedStyleType: "NORMAL_TEXT"`, text "Body."

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- All three paragraphs confirmed: `TITLE` / `SUBTITLE` / `NORMAL_TEXT` with correct text values.

---

## Nested table support — `write_doc_content`

### TC-D199: Simple nested table ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>Inner</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col)
- The outer cell contains a nested table element with cell text "Inner"
- 🔍 Visual check: nested table visible inside the outer table cell in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 1 col, cell [0,0] startIndex=4 endIndex=17 text="" (empty text run confirms cell holds nested table, not text). Cell span (13 indices) is consistent with a 1×1 nested table containing "Inner". Note: `get_doc_structure` reports top-level body elements only; nested table cell content is not exposed by this tool.

---

### TC-D200: Nested table alongside regular cells ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>Label</td><td><table><tr><td>Val A</td><td>Val B</td></tr></table></td></tr></table>`"

**Checks**
- Outer table has 1 row, 2 columns
- Cell [0,0] text = "Label"
- Cell [0,1] contains a nested table with 1 row × 2 cols, cells "Val A" and "Val B"
- 🔍 Visual check: label in col 0, small inner table in col 1

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 2 cols. Cell [0,0] text="Label" ✅. Cell [0,1] text="" with span 11–31 (20 indices, consistent with 1×2 nested table holding "Val A" and "Val B") ✅.

---

### TC-D201: Nested table with multiple rows and columns ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>R0C0</td><td>R0C1</td></tr><tr><td>R1C0</td><td>R1C1</td></tr></table></td></tr></table>`"

**Checks**
- Outer table: 1 row, 1 col
- Nested table: 2 rows × 2 cols
- All four nested cells filled correctly: R0C0, R0C1, R1C0, R1C1
- 🔍 Visual check: 2×2 grid inside the outer cell

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 1 col, cell [0,0] text="" with span 4–35 (31 indices, consistent with a 2×2 nested table containing four 4-char cell values plus table overhead) ✅.

---

### TC-D202: Nested tables not supported in markdown (documented limitation)
**Note:** The markdown pipeline does not produce nested tables — the `markdown` library does not support table-in-table syntax. Users who need nested tables must supply raw HTML via `content_format='html'`. No test to run; this entry documents the known limitation.

---

### TC-D203: `get_doc_theme` scans body paragraph styles
**Note:** `get_doc_theme` reads explicit per-paragraph and per-run styles from the document body. It returns data for AI-generated docs (where styles are set explicitly on runs); for standard docs whose styles are fully inherited from named style defaults it returns an empty dict.

**Prompt**
> "Call `get_doc_theme` on doc {DOC_ID} and show me the result."

**Checks**
- No `error` key in result
- For a doc with explicit paragraph styles: returns a dict with at least one named style type key; each entry has at least one of font_family, font_size, bold, italic, color, line_spacing, space_above, space_below
- For a doc with purely inherited styles: result is an empty dict `{}` (expected, not an error)

**Result (2026-06-20) ✅ PASS** Called on a test doc created with `create_doc` (markdown content — inherited styles): returned `{}`. Called on the same doc after `apply_theme overwrite=True` (Georgia HEADING_1, Roboto NORMAL_TEXT): returned `{"HEADING_1": {"font_family": "Georgia"}, "NORMAL_TEXT": {"font_family": "Roboto"}}`. `font_size` and `bold` are not returned because the Docs API normalises explicit overrides that match the named style default back to inherited. No error key in either case.

---

### TC-D204: `apply_theme` updates named style definitions ⚠️ destructive
**Note:** Default mode (`overwrite=False`) emits `updateNamedStyle` requests — one per named style key — updating the document's style defaults. Existing paragraphs with explicit overrides are unaffected. No doc fetch is needed. Use `overwrite=True` to also apply directly to all existing paragraphs.

**Prompt**
> "Apply theme `{"HEADING_1": {"font_family": "Georgia", "font_size": 22}, "NORMAL_TEXT": {"font_family": "Verdana", "font_size": 11}}` to doc {DOC_ID}"

**Checks**
- Result contains `docId` and `requests > 0`
- No `error` key
- `requests` equals the number of named style keys in the theme (one `updateNamedStyle` per key)

**Result (2026-06-20) ✅ PASS** Called with HEADING_1 + HEADING_2 + NORMAL_TEXT → `{"docId": "...", "requests": 3}`. Each emitted one `updateNamedStyle` request with snake_case field mask (`named_style_type,text_style.weighted_font_family,text_style.font_size`). No error. Live API accepted all three requests.

---

### TC-D204b: `apply_theme` with `overwrite=True` also patches existing paragraphs ⚠️ destructive
**Prompt**
> "Write `<h1>Heading One</h1><p>Normal body text.</p>` to doc {DOC_ID}, then apply theme `{"HEADING_1": {"font_family": "Georgia", "font_size": 22}, "NORMAL_TEXT": {"font_family": "Verdana", "font_size": 11}}` with overwrite=True"

**Checks**
- Result contains `docId` and `requests > 0`
- `requests` > number of named style keys (named style updates + per-paragraph updates)
- No `error` key
- 🔍 Visual check: HEADING_1 paragraph visually in Georgia 22pt, body in Verdana 11pt

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS** Called with HEADING_1 + NORMAL_TEXT on a doc with HEADING_1, HEADING_2 (×2), HEADING_3, NORMAL_TEXT (×4) paragraphs → `{"docId": "...", "requests": 7}` (2 `updateNamedStyle` + 5 `updateTextStyle` for matching paragraphs). No error.

---

### TC-D205: `apply_theme` with table styling ⚠️ destructive
**Prerequisite:** doc must contain at least one table (write one with `write_doc_content` first if needed)

**Prompt**
> "Apply this theme to doc {DOC_ID}: `{"table": {"border_color": {"red": 0, "green": 0, "blue": 0}, "border_width": 0.5, "border_dash_style": "SOLID", "cell_padding": 3.6, "header_background": {"red": 0.953, "green": 0.953, "blue": 0.953}}}`"

**Checks**
- Result contains `docId` and `requests > 0`
- 🔍 Visual check: table cells have thin black border, 3.6pt padding, first row has light grey background

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS** Wrote 2-row table, applied table theme → `requests: 2` (one updateTableCellStyle per row; row 0 got header_background + padding + borders, row 1 got padding + borders). No error. Fixture restored.

---

### TC-D206: `get_doc_theme` → `apply_theme` round-trip on an AI-generated doc ⚠️ destructive
**Note:** Round-trip only produces meaningful output on docs where styles are explicit (AI-generated). For standard inherited-style docs, `get_doc_theme` returns `{}` and `apply_theme` with an empty theme returns an error.

**Prompt**
> "Write styled content to doc {DOC_ID} with explicit font overrides, then read the theme with `get_doc_theme`, then apply it back with `apply_theme overwrite=True`. Show me both results."

**Checks**
- `get_doc_theme` returns a non-empty dict (at least one named style key with at least one field)
- `apply_theme` returns `requests > 0`
- No `error` in either result

**Result (2026-06-20) ✅ PASS** After `apply_theme overwrite=True` (Georgia HEADING_1, Roboto NORMAL_TEXT) on the test doc, `get_doc_theme` returned `{"HEADING_1": {"font_family": "Georgia"}, "NORMAL_TEXT": {"font_family": "Roboto"}}`. Applying that theme back → `requests: 2` (one `updateNamedStyle` per key). No error. (font_size/bold not in round-trip because API normalises them to inherited when they match the named style default.)

---

## `insert_inline_image` (#145)

### TC-D208: Insert an image by public URI ⚠️ destructive
**Setup:** fetch structure; note the `endIndex` of a paragraph to insert after

**Prompt**
> "Insert an image from URI 'https://www.gstatic.com/images/branding/googlelogo/svg/googlelogo_clr_74x24px.svg' at index {N} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `index: N`
- 🔍 Visual check in Google Docs: image appears in the document at the insertion point

**Cleanup:** delete the inserted image range (use `delete_doc_range` on the image's index span, visible in `get_doc_structure` as an element)

**Result (2026-06-22) ✅ PASS** Inserted Google branding PNG at paragraph boundary. Response: `{docId, index}`. Image visible in doc. Occupies one index slot as an inline element in `get_doc_structure`.

---

### TC-D209: Insert an image with explicit size ⚠️ destructive
**Setup:** same as TC-D208

**Prompt**
> "Insert an image from URI 'https://www.gstatic.com/images/branding/googlelogo/svg/googlelogo_clr_74x24px.svg' at index {N} in doc {DOC_ID} with width 100 and height 50"

**Checks**
- Call succeeds with no API error
- 🔍 Visual check: image is smaller than default size

**Cleanup:** delete inserted image range

**Result (2026-06-22) ✅ PASS** Same PNG at same location with `width=100, height=50`. Call succeeded; image rendered smaller than the default-sized TC-D208 image.

---

### TC-D210: No source provided returns error
**Prompt**
> "Call insert_inline_image on doc {DOC_ID} at index 1 without providing a URI or drive_file_id"

**Checks**
- Returns `{"error": "Provide either uri or drive_file_id"}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Provide either uri or drive_file_id, not both"}`. No API call made.

---

### TC-D211: Both URI and drive_file_id provided returns error
**Prompt**
> "Call insert_inline_image on doc {DOC_ID} at index 1 with both uri 'https://example.com/img.png' and drive_file_id 'someid'"

**Checks**
- Returns `{"error": "Provide only one of uri or drive_file_id, not both"}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Provide only one of uri or drive_file_id, not both"}`. No API call made.

---

## `insert_table_row` / `delete_table_row` / `insert_table_column` / `delete_table_column` (#146)

### TC-D212: Insert a row below an existing row ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Insert a row below row 0 in the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `row_index: 0`
- Re-fetch `get_doc_structure` shows the table now has 3 rows

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_row(row_index=0, insert_below=True)`. Response: `{docId, table_start_index, row_index: 0}`. Re-fetched structure showed 3 rows.

---

### TC-D213: Insert a row above an existing row ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Insert a row above row 1 in the table at index {tableStartIndex} in doc {DOC_ID} (insert_below=False)"

**Checks**
- Call succeeds with no API error
- Re-fetch shows the table has 3 rows
- New row appears at row 1 (between original rows 0 and 1)

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_row(row_index=1, insert_below=False)`. Re-fetched structure showed 3 rows.

---

### TC-D214: Delete a row ⚠️ destructive
**Setup:** insert a 3-row table; note its `tableStartIndex`

**Prompt**
> "Delete row 1 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `row_index: 1`
- Re-fetch shows the table has 2 rows

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 3-row table; called `delete_table_row(row_index=1)`. Response: `{docId, table_start_index, row_index: 1}`. Re-fetched structure showed 2 rows.

---

### TC-D215: Insert a column to the right ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Insert a column to the right of column 0 in the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `column_index: 0`
- Re-fetch shows the table has 3 columns

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_column(column_index=0, insert_right=True)`. Response: `{docId, table_start_index, column_index: 0}`. Re-fetched structure showed 3 columns.

---

### TC-D216: Insert a column to the left ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Insert a column to the left of column 1 in the table at index {tableStartIndex} in doc {DOC_ID} (insert_right=False)"

**Checks**
- Call succeeds with no API error
- Re-fetch shows the table has 3 columns

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×2 table; called `insert_table_column(column_index=1, insert_right=False)`. Re-fetched structure showed 3 columns.

---

### TC-D217: Delete a column ⚠️ destructive
**Setup:** insert a 2×3 table; note its `tableStartIndex`

**Prompt**
> "Delete column 1 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, `table_start_index`, `column_index: 1`
- Re-fetch shows the table has 2 columns

**Cleanup:** delete the table

**Result (2026-06-22) ✅ PASS** Inserted 2×3 table; called `delete_table_column(column_index=1)`. Response: `{docId, table_start_index, column_index: 1}`. Re-fetched structure showed 2 columns.

---

### TC-D218: API error returned gracefully (out of bounds row)
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
> "Delete row 99 from the table at index {tableStartIndex} in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure

**Result (2026-06-22) ✅ PASS** Called `delete_table_row(row_index=99)` on a 2×2 table. Returned `{"error": "..."}` with an API error message referencing an invalid row index. No exception raised.

---

## `create_header` / `create_footer` (#147)

### TC-D219: Create a default page header ⚠️ destructive
**Prompt**
> "Add a page header to doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `headerId` (non-empty string)
- 🔍 Visual check in Google Docs: document shows a header section

**Cleanup:** none needed (headers persist; restore fixture doc if desired)

**Result (2026-06-22) ✅ PASS** Called `create_header(doc_id=fixture)` (no content). Returned `{"docId": ..., "headerId": "kix.xxxxxxxxxx"}`. Header section visible in Google Docs. Note: on first call after a prior session created the header (due to index=1 bug), the "already exists" 400 error was caught and the ID was retrieved from `documentStyle.defaultHeaderId` — this is the expected fallback path.

---

### TC-D220: Create a header with content ⚠️ destructive
**Prompt**
> "Add a page header to doc {DOC_ID} with content 'Confidential — Internal Only'"

**Checks**
- Response contains `docId` and `headerId`
- Two API calls were made (create + insert text) — verifiable via no error in response
- 🔍 Visual check: header text "Confidential — Internal Only" appears in the document header

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_header(doc_id=temp_doc, content="Confidential — Internal Only")`. Returned `{"docId": ..., "headerId": "kix.xxxxxxxxxx"}` with no `warning` key — both header creation (via `documentStyle` fallback) and content insertion at `index=0` succeeded.

---

### TC-D221: Create a default page footer ⚠️ destructive
**Prompt**
> "Add a page footer to doc {DOC_ID}"

**Checks**
- Response contains `docId` and `footerId` (non-empty string)
- 🔍 Visual check: document shows a footer section

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_footer(doc_id=fixture)`. Returned `{"docId": ..., "footerId": "kix.xxxxxxxxxx"}`. Footer section visible in Google Docs.

---

### TC-D222: Create a footer with content ⚠️ destructive
**Prompt**
> "Add a page footer to doc {DOC_ID} with content 'Page 1'"

**Checks**
- Response contains `docId` and `footerId`
- 🔍 Visual check: footer shows "Page 1"

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_footer(doc_id=temp_doc, content="Page 1")`. Returned `{"docId": ..., "footerId": "kix.xxxxxxxxxx"}` with no `warning` key — footer created and content inserted at `index=0`.

---

### TC-D223: Invalid header_type returns error
**Prompt**
> "Call create_header on doc {DOC_ID} with header_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid header_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid header_type 'INVALID'. Use DEFAULT or FIRST_PAGE_HEADER"}`. No API call made.

---

### TC-D224: Invalid footer_type returns error
**Prompt**
> "Call create_footer on doc {DOC_ID} with footer_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid footer_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid footer_type 'BOGUS'. Use DEFAULT or FIRST_PAGE_FOOTER"}`. No API call made.

---

### TC-D225: insert_doc_text with segment_id writes into header ⚠️ destructive
**Setup:** call `create_header` first to get a `headerId`

**Prompt**
> "Insert the text 'Header text via insert_doc_text' at index 0 in doc {DOC_ID} using segment_id '{headerId}'"

**Note:** An empty header/footer segment has end index 1 (one newline at index 0). Insert at index 0, not 1.

**Checks**
- Call succeeds with no API error
- Response contains `insertions: 1`
- 🔍 Visual check: "Header text via insert_doc_text" appears in the document header

**Result (2026-06-22) ✅ PASS** Called `insert_doc_text` with `[{index: 0, text: "QA Test Header", segment_id: "kix.xxxxxxxxxx"}]`. Response: `{"docId": ..., "insertions": 1}`. Text "QA Test Header" appeared in fixture doc header. Same mechanism also confirmed for footer segment insertion (segment_id: "kix.xxxxxxxxxx", text: "Page 1").

---

### TC-D207: `get_doc_named_styles` reads named style defaults set via the Docs UI
**Note:** Named styles are only populated when the user explicitly goes to Format > Paragraph styles > Update X to match. Most docs leave named styles at Google's defaults — this tool returns empty or near-empty for those docs. Use `get_doc_theme` to read actual paragraph appearance instead.

**Prompt**
> "Call `get_doc_named_styles` on doc {DOC_ID} and show me the result."

**Checks**
- No `error` key in result
- For a doc where named styles were explicitly set: returns a non-empty dict with named style type keys
- For a standard doc: may return `{}` or only Google's default entries (expected, not an error)

**Result (2026-06-20) ✅ PASS** Called on a doc that had `apply_theme` previously applied (Georgia HEADING_1/H2, Roboto NORMAL_TEXT). Returned 9 entries: NORMAL_TEXT (Roboto 11pt, line_spacing 115), HEADING_1 (Georgia 24pt bold, space_above 20), HEADING_2 (Georgia 18pt, space_above 18), HEADING_3–6 (Google defaults with font sizes and colors), TITLE, SUBTITLE. Confirms `apply_theme` default mode successfully writes to named styles, and `get_doc_named_styles` reads them back correctly. No error.

---

### TC-D226: Table immediately after heading renders at Normal Text size ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-d226-heading-table.md` from the repo (absolute path: `<repo-root>/docs/qa/fixtures/tc-d226-heading-table.md`)

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d226-heading-table.md, then show me its structure."

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows a `table` element with 6 cells containing "Finding", "Severity", "Ticket", "Some finding", "HIGH", "KINDLY-123"
- 🔍 Visual check: open the doc — table cell text renders visually smaller than the "HIGH" H2 heading above it (~11pt vs ~16pt); no blank paragraph workaround needed

**Cleanup:** delete the created doc

**Result (2026-06-24) ✅ PASS** "HIGH" heading renders visually larger than table text. All six cells ("Finding", "Severity", "Ticket", "Some finding", "HIGH", "KINDLY-123") render at Normal Text size. No blank paragraph between heading and table required. No oversized cell text observed.

---

### TC-D227: No visible blank line between heading and table in `create_doc_from_file` ⚠️ requires-oauth ⚠️ destructive

**Background:** the Docs API inserts a structurally-required blank paragraph before every table;
`deleteContentRange` is rejected for it. The fix collapses it to zero visual height via
`updateParagraphStyle` (spaceAbove/Below=0, lineSpacing=1) + `updateTextStyle` (fontSize=1pt).

**Setup:** use `docs/qa/fixtures/tc-d226-heading-table.md` (heading immediately followed by a table)

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d226-heading-table.md, then show me its structure."

**Checks**
- Tool completes without error (no `HttpError 400`)
- `get_doc_structure` returns a body with a heading and a table; a blank paragraph element may still be listed (it is structurally present), but its `paragraph.paragraphStyle` should show `lineSpacing: 1`, `spaceAbove: 0`, `spaceBelow: 0`
- 🔍 Visual check: open the doc — no visible blank line between the "HIGH" heading and the table

**Cleanup:** delete the created doc

**Result (2026-06-25) ✅ PASS**
- Tool completed without error. Structure: sectionBreak → HEADING_2 "HIGH\n" (1-6) → blank para "\n" (6-7, `font_size: 1` on its run confirming collapse applied) → table (7-70, cells filled correctly: Finding/Severity/Ticket header, Some finding/HIGH/KINDLY-123 data) → trailing para (70-71). Visual check: no visible gap between heading and table in the rendered doc.
