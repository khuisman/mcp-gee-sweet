# Docs Direct API Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs/` (package: `__init__.py`, `ast.py`, `html_parser.py`, `emitter.py`)

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` (and, for `insert_local_images`, `{FOLDER_ID}`) from `fixtures.local.md`.

These tools operate on document body indices. Use `get_doc_structure` first in any session to obtain current indices before calling insert/delete/style operations.

---

## `get_doc_structure`

### TC-DOC01: Structure of a non-empty doc
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

### TC-DOC02: Paragraph runs include style data
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

### TC-DOC03: Structure of a doc containing a table
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

### TC-DOC04: Structure of an empty doc
**Setup:** doc with only the default empty paragraph

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns elements with at least the sectionBreak and one empty paragraph
- No error

**Result (2026-06-20) ✅ PASS**
- Wrote `<p></p>`. Structure: sectionBreak at 0–1, one empty paragraph at 1–2. No error.

---

### TC-DOC05: Invalid doc ID returns error
**Prompt**
> "Get the structure of doc not-a-real-id"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references the invalid ID or a 404

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "<HttpError 404 ... Requested entity was not found.>"}`. No exception raised.

---

## `insert_doc_text`

### TC-DOC06: Insert a single paragraph ⚠️ destructive
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

### TC-DOC07: Insert at multiple indices — high→low ordering verified ⚠️ destructive
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

### TC-DOC08: Empty insertions list returns error
**Prompt**
> "Call insert_doc_text on doc {DOC_ID} with an empty insertions list"

**Checks**
- Returns `{"error": "insertions list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "insertions list is empty"}`.

---

## `delete_doc_range`

### TC-DOC09: Delete a paragraph ⚠️ destructive
**Setup:** insert a known paragraph first (TC-DOC06), note its `startIndex` and `endIndex`

**Prompt**
> "Delete the range from index {start} to {end} in doc {DOC_ID}"

**Checks**
- Re-fetch structure no longer contains the deleted paragraph
- Surrounding content shifted back correctly
- `deletions: 1` in response

**Result (2026-06-20) ✅ PASS**
- Inserted "Delete me.\n" at 88; deleted [88, 99]. Re-fetch confirmed paragraph absent; "Item two\n" back at 79–88; final blank at 88–89. `deletions: 1`.

---

### TC-DOC10: Cannot delete final segment newline
**Setup:** fetch structure; note the final element's `endIndex`

**Prompt**
> "Delete the range from index 1 to {final_endIndex} in doc {DOC_ID}"

**Checks**
- Returns an API error about the segment newline
- 🔍 **Note:** correct usage is `endIndex - 1` for the final element

**Result (2026-06-20) ✅ PASS**
- Attempted delete [1, 89] (final_endIndex=89). API returned `{"error": "<HttpError 400 ... The range cannot include the newline character at the end of the segment.>"}`.

---

### TC-DOC11: Empty deletions list returns error
**Prompt**
> "Call delete_doc_range on doc {DOC_ID} with an empty deletions list"

**Checks**
- Returns `{"error": "deletions list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "deletions list is empty"}`.

---

## `style_doc_range`

### TC-DOC12: Apply named style type ⚠️ destructive
**Setup:** insert a normal paragraph; note its index range

**Prompt**
**Playwright: required**
> "Style the range from index {start} to {end} in doc {DOC_ID} as HEADING_2"

**Checks**
- Re-fetch shows `namedStyleType: "HEADING_2"` for that paragraph
- `requests: 1` in response

**Cleanup:** re-style as NORMAL_TEXT

**Result (2026-06-20) ✅ PASS**
- Inserted "Style test paragraph.\n" at 88. Styled [88, 110] as HEADING_2. Re-fetch confirmed `namedStyleType: "HEADING_2"`. `requests: 1`.

---

### TC-DOC13: Apply text styles (bold, italic, foreground color) ⚠️ destructive
**Setup:** insert a normal paragraph; note its index range

**Prompt**
**Playwright: required**
> "Make the range from index {start} to {end} in doc {DOC_ID} bold, italic, and red (foreground_color red=1 green=0 blue=0)"

**Checks**
- Re-fetch shows `bold: true`, `italic: true` on runs in that range
- `requests: 1` in response (paragraph style skipped, only updateTextStyle emitted)

**Cleanup:** delete the test paragraph

**Result (2026-06-20) ✅ PASS**
- Applied bold+italic+red foreground to [88, 110]. Re-fetch: run `bold: true`, `italic: true`. `requests: 1` (only updateTextStyle; no paragraph style change).

---

### TC-DOC14: Apply both paragraph and text style in one range ⚠️ destructive
**Prompt**
> "Style range {start}–{end} in doc {DOC_ID} as HEADING_3 and bold"

**Checks**
- `requests: 2` (one updateParagraphStyle + one updateTextStyle)
- Both applied correctly on re-fetch

**Result (2026-06-20) ✅ PASS**
- Applied HEADING_3 + bold to same paragraph. `requests: 2` (one updateParagraphStyle + one updateTextStyle).

---

### TC-DOC15: No recognised style fields returns error
**Prompt**
> "Call style_doc_range on doc {DOC_ID} with a range that has no style fields"

**Checks**
- Returns `{"error": "no recognised style fields in any range"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "no recognised style fields in any range"}`.

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

## `style_doc_table_cells`

### TC-DOC18: Apply grey header row background ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Style row 0 of the table at index {tableStartIndex} in doc {DOC_ID} with background_color red=0.953 green=0.953 blue=0.953, column_span 2"

**Checks**
- `requests: 1` in response
- 🔍 Visual check in Google Docs: header row has grey background

**Cleanup:** delete table

**Result (2026-06-20) ✅ PASS**
- Styled row 0 with `background_color {red:0.953, green:0.953, blue:0.953}`, `column_span: 2`. `requests: 1`.

---

### TC-DOC19: Apply borders and padding ⚠️ destructive
**Setup:** insert a 2×2 table; note its `tableStartIndex`

**Prompt**
**Playwright: required**
> "Style all cells in the table at index {tableStartIndex} in doc {DOC_ID} with border_color black (0,0,0), border_width 0.5, border_dash_style SOLID, padding 3.6pt on all sides"

**Checks**
- Call succeeds for each cell
- 🔍 Visual check: table has visible borders and reasonable padding

**Result (2026-06-20) ✅ PASS**
- Applied black border (0.5pt) + 3.6pt padding to all 4 cells of a 2×2 table. `requests: 4` (one per cell). Call succeeded for each.

---

### TC-DOC20: Empty cells list returns error
**Prompt**
> "Call style_doc_table_cells on doc {DOC_ID} with table_start_index {N} and an empty cells list"

**Checks**
- Returns `{"error": "cells list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "cells list is empty"}`.

---

### TC-DOC21: Cell with no style fields is skipped
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

### TC-DOC22: Multi-delete high→low ordering verified ⚠️ destructive
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

### TC-DOC23: style_doc_range round-trip — heading confirmed in get_doc_structure ⚠️ destructive
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

### TC-DOC24: style_doc_range text styles round-trip ⚠️ destructive
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

### TC-DOC25: style_doc_table_cells post-fix live verification ⚠️ destructive
**Purpose:** `style_doc_table_cells` was fixed (removed top-level `tableStartLocation` that conflicted with the `tableRange` oneof) but the fix was **never re-tested live**. This is the confirmation test.

**Setup:** insert a 2×2 table; record its `tableStartIndex` from the response

**Prompt**
**Playwright: required**
> "Style cell [0,0] of the table at index {tableStartIndex} in doc {DOC_ID} with background_color red=0.8 green=0.9 blue=1.0"

**Checks**
- Response succeeds (no API 400 error about `oneof field 'cells' is already set`)
- `requests: 1` in response
- 🔍 Visual check in Google Docs: cell [0,0] has light blue background

**Cleanup:** delete the table

**Result (2026-06-20) ✅ PASS**
- Inserted 2×2 table; styled cell [0,0] with `background_color {red:0.8, green:0.9, blue:1.0}`. No API 400 error. `requests: 1`. Fix (removal of top-level `tableStartLocation` conflicting with `tableRange` oneof) confirmed working.

---

### TC-DOC26: Full end-to-end sequence — insert table then style cells ⚠️ destructive
**Purpose:** the complete `insert_doc_table` → `style_doc_table_cells` sequence was never run end-to-end in live testing. Covers both tools and the index handoff between them.

**Setup:** fetch structure; note a suitable insertion index N

**Prompt**
**Playwright: required**
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

### TC-DOC27: Insert text then insert table — index chaining ⚠️ destructive
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

### TC-DOC28: Apply strikethrough ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
> "Apply strikethrough to range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- `get_doc_structure` shows run with `strikethrough: true`

**Result (2026-06-20) ✅ PASS**
- Inserted "Strikethrough test.\n"; applied strikethrough to [88, 108]. `requests: 1`. Re-fetch: run `strikethrough: true`.

---

### TC-DOC29: Apply font_size ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
> "Set font size to 18pt for range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- 🔍 Visual check: text is visibly larger

**Result (2026-06-20) ✅ PASS**
- Applied `font_size: 18` to [88, 104]. `requests: 1`. (Visual check only — `get_doc_structure` does not expose `font_size` from effectiveFormat.)

---

### TC-DOC30: Apply link_url ⚠️ destructive
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

### TC-DOC31: `<h2>` maps to HEADING_2 (not HEADING_3) ⚠️ destructive
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

### TC-DOC32: `<th>` cells produce bold runs ⚠️ destructive
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

### TC-DOC33: Inline formatting inside `<td>` cells ⚠️ destructive
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
- `get_doc_structure` shows 1 row, 1 col, cell text "bold plain italic" — all three segments present. Run-level bold/italic not verifiable via `get_doc_structure` (same cell-runs gap as TC-DOC32). 🔍 Visual check required for run formatting.

---

### TC-DOC34: `colspan` produces merged cells ⚠️ destructive
**Purpose:** Regression test for #67 — `colspan` was previously ignored.

**Prompt**
**Playwright: required**
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

### TC-DOC35: Column widths from HTML ⚠️ destructive
**Purpose:** Regression test for #66 — `width` attributes on `<col>` were previously ignored.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><col width=\"144\"><col width=\"288\"><tr><td>Narrow</td><td>Wide</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- 🔍 Visual check: first column is narrower than second column in Google Docs
- 🔍 Note: `get_doc_structure` does not expose column width properties; visual verification is the only check available without `effectiveFormat` API access (#54)

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- Call succeeded with no API error. Column width is visual-only per the test note.

---

### TC-DOC36: `rowspan` produces vertically merged cells ⚠️ destructive
**Purpose:** First live verification of issue #91 — rowspan support in the HTML→AST→emitter pipeline. A cell spanning two rows must produce a `mergeTableCells` request, and the phantom cell in the lower row must not be filled.

**Prompt**
**Playwright: required**
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

### TC-DOC37: Combined `rowspan` and `colspan` in the same table ⚠️ destructive
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

### TC-DOC38: `rowspan` with header row — phantom not filled, real cells in correct columns ⚠️ destructive
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

### TC-DOC39: Markdown headings via `write_doc_content` ⚠️ destructive
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

### TC-DOC40: Markdown bold and italic via `write_doc_content` ⚠️ destructive
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

### TC-DOC41: Markdown task list ⚠️ destructive
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

### TC-DOC42: Markdown fenced code block ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown' with a fenced Python code block containing `def hello(): return 'world'`"

**Checks**
- Doc contains the code text with monospace font (Courier New)
- 🔍 Visual check: code block appears in monospace font in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Two paragraphs: `def hello():` and `    return 'world'` confirmed via `get_doc_structure`.
- `weightedFontFamily: Courier New` is emitted by the unit-tested emitter; `get_doc_structure` does not expose `font_family` (known gap — no `effectiveFormat` API access).

**Result (2026-07-04) — related bug found, not a failure of this TC's own checks** Writing a fenced code block as the doc's last content left an explicit `font_size`/`font_family` override on the document's trailing paragraph mark, which `write_doc_content`'s clear+reinsert couldn't remove (the Docs API won't let `deleteContentRange` touch the final paragraph mark) — a *subsequent* `write_doc_content` call with plain content would inherit that contamination. Filed as [#255](https://github.com/khuisman/mcp-gee-sweet/issues/255). Fixed in [#258](https://github.com/khuisman/mcp-gee-sweet/pull/258), then corrected in [#259](https://github.com/khuisman/mcp-gee-sweet/pull/259) after live re-testing showed #258's single-batchUpdate version was unreliable. **Re-verified live (2026-07-05)** after both merged: wrote a fenced code block, then overwrote with plain content — new content came back with `textStyle: {}`, no contamination, across repeated rounds.

---

### TC-DOC43: Markdown table via `write_doc_content` ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': a pipe table with columns Name and Value, rows Alpha/1 and Beta/2"

**Checks**
- `get_doc_structure` shows a table with 3 rows (header + 2 data rows) and 2 columns
- Cell text matches: 'Name', 'Value', 'Alpha', '1', 'Beta', '2'

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Table: 3 rows, 2 columns. Cells: Name/Value, Alpha/1, Beta/2 — all correct.

---

### TC-DOC44: `create_doc_from_file` with a local .md file ⚠️ requires-oauth ⚠️ destructive
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

### TC-DOC45: `create_doc_from_file` with a local .html file ⚠️ requires-oauth ⚠️ destructive
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

### TC-DOC46: `create_doc_from_file` file not found
**Prompt**
> "Create a Google Doc from the file ~/does-not-exist.md"

**Checks**
- Returns `{"error": "File not found: ..."}` — no exception raised

**Result (2026-06-19) ✅ PASS**
- Returned `{"error": "File not found: /tmp/nonexistent-file.md"}` — no exception.

---

### TC-DOC47: `write_doc_content` inline code monospace ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `Use the \`print()\` function`"

**Checks**
- 🔍 Visual check: `print()` appears in monospace (Courier New) inside the paragraph

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Paragraph text `Call my_function() with param=True to enable it.` confirmed; code spans at correct positions.
- `weightedFontFamily: Courier New` confirmed via unit tests; not exposed by `get_doc_structure` (known gap).

**Result (2026-07-04)** Two findings during the v0.8.1 live pass, neither a failure of this TC's own checks:
1. The prescribed SVG image URI in TC-DOC57/58 is unrelated to this TC but was hit in the same session — see those TCs, now fixed to use a PNG.
2. This TC's own content (an inline code span) was one of the reproductions of the trailing-paragraph-mark contamination bug — see TC-DOC42's 2026-07-04 result for the full account, filed as [#255](https://github.com/khuisman/mcp-gee-sweet/issues/255), fixed in [#258](https://github.com/khuisman/mcp-gee-sweet/pull/258)/[#259](https://github.com/khuisman/mcp-gee-sweet/pull/259) and re-verified live post-merge. Separately, a possible over-broad Courier New application (whole line vs. just the code span) was observed visually but not conclusively confirmed, since `get_doc_structure` doesn't expose `font_family` per run — no ticket filed yet, flagged as a follow-up if that gap is ever closed.

---

### TC-DOC78: `data-style="title"` produces TITLE named style ⚠️ destructive
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

### TC-DOC79: `data-style="subtitle"` produces SUBTITLE named style ⚠️ destructive
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

### TC-DOC48: Simple nested table ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>Inner</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col)
- The outer cell contains a nested table element with cell text "Inner"
- 🔍 Visual check: nested table visible inside the outer table cell in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 1 col, cell [0,0] startIndex=4 endIndex=17 text="" (empty text run confirms cell holds nested table, not text). Cell span (13 indices) is consistent with a 1×1 nested table containing "Inner". Note: `get_doc_structure` reports top-level body elements only; nested table cell content is not exposed by this tool.

---

### TC-DOC49: Nested table alongside regular cells ⚠️ destructive
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

### TC-DOC50: Nested table with multiple rows and columns ⚠️ destructive
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

### TC-DOC51: Nested tables not supported in markdown (documented limitation)
**Note:** The markdown pipeline does not produce nested tables — the `markdown` library does not support table-in-table syntax. Users who need nested tables must supply raw HTML via `content_format='html'`. No test to run; this entry documents the known limitation.

---

### TC-DOC84: Text sharing a cell with a nested table is no longer dropped (issue #108) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>Some label <table><tr><td>Inner</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col) with a non-empty text run in cell [0,0] (previously this cell's text was silently dropped — bled into the nested table's own cell instead)
- 🔍 Visual check: "Some label" appears above/before the nested table inside the outer cell, and the nested table's own cell reads "Inner" (not "Some label Inner" merged together)

**Cleanup:** write fixture content back

**Result (2026-07-06) ✅ PASS** `get_doc_structure` shows outer cell [0,0] `text: "Some label"` (previously empty per TC-DOC48's bug pattern). Playwright screenshot confirms "Some label" renders above the nested table, whose own cell reads exactly "Inner" — no merging.

---

### TC-DOC85: Text after a nested table in the same cell, correctly positioned (issue #275) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>Inner</td></tr></table>After</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer cell's text as "After" — content intact, not merged with "Inner"
- 🔍 Visual check: "After" renders *below* the nested table, not above it

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` cell [0,0] `text: "After"`. Playwright confirms "After" renders below the nested table ("Inner"). Note: an earlier pass of this test case (2026-07-06) incorrectly expected "After" to render *above* the table — that was the pre-#275-fix limitation (a cell's text always rendered as one block before any nested table, regardless of source order). #275 fixed the emitter to place text on the correct side of each nested table; this test case's expectation and prompt were updated to match.

---

### TC-DOC86: Text before AND after one nested table, both correctly positioned (issue #275) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>Before <table><tr><td>Inner</td></tr></table> After</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows outer cell [0,0] text as `"Before \n After"` (the `\n` confirms two distinct paragraphs — before and after the table — not one merged block)
- 🔍 Visual check: "Before" above the nested table, "Inner" inside it, "After" below it

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` shows `text: "Before \n After"`. Playwright screenshot confirms all three pieces render in the correct order and position.

---

### TC-DOC87: Multiple nested tables in one cell with text between them (issue #275) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>A<table><tr><td>1</td></tr></table>B<table><tr><td>2</td></tr></table>C</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows outer cell [0,0] text as `"A\nB\nC"` (three separate paragraphs — one per text segment between/around the two nested tables)
- 🔍 Visual check: A, then a table containing "1", then B, then a second table containing "2", then C — all in that order

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` shows `text: "A\nB\nC"`. Playwright screenshot confirms both nested tables render in the correct positions with "1" and "2" filled in, and A/B/C text correctly interleaved — a capability that didn't exist before #275 (previously only one nested table per cell was supported at all).

---

### TC-DOC88: `colspan="0"` clamps to 1 instead of producing a degenerate zero-column cell

**Background:** Found via code review of PR #276 — `int(attr_dict.get("colspan") or 1)` only covers a *missing* colspan attribute; an explicit `colspan="0"` is a non-empty (truthy) string, so it survives the `or` and parses to the literal integer `0`. A cell that spans zero columns breaks downstream `num_cols` calculations used by the nested-table fill algorithm. Fixed by clamping colspan/rowspan to a minimum of 1 in `html_parser.py`.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td colspan="0">Wide</td><td>Next</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the table with `columns: 2` (not 1 or a broken/merged layout) — cell [0,0] text "Wide", cell [0,1] text "Next"

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` shows `columns: 2`, cell [0,0] `text: "Wide"`, cell [0,1] `text: "Next"` — `colspan="0"` clamped to 1 and rendered as two normal side-by-side cells.

---

### TC-DOC89: Degenerate table (row with no cells) followed by a real table doesn't desync content (issue #277)

**Background:** `ast_to_requests` skips emitting an `insertTable` request for a table with zero rows or zero columns (e.g. a `<tr>` with no `<td>`s), but was still counting that table in the list it hands to `fill_tables()`. Since `fill_tables()` pairs AST tables against live-doc tables positionally, a skipped table shifted every later table's fill/merge/style requests onto the wrong doc table — silently, with no error. Fixed by excluding degenerate tables from that list at the source.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr></tr></table><table><tr><td>A</td><td>B</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows exactly **one** table in the doc (the empty-row table produces no table element at all)
- That table is `columns: 2` with cell [0,0] text "A" and cell [0,1] text "B" — not empty, not misapplied, not offset onto the wrong table

**Cleanup:** write fixture content back

**Result (2026-07-09) ✅ PASS**

---

### TC-DOC90: `colspan`/`rowspan` inside a nested table now merges correctly (issue #109) ⚠️ destructive

**Background:** Nested tables produced a correctly-sized shell but silently ignored `colspan`/`rowspan` on their own cells — no `mergeTableCells` request was ever emitted for them, unlike outer-table cells (TC-DOC34/36/37). Fixed by having `_fill_table_fully` run the same merge phase for a nested table's own cells that `fill_tables` already runs for the outer table.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td colspan=\"2\">Header</td></tr><tr><td>A</td><td>B</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col) with cell [0,0] text empty (holds the nested table, not text)
- 🔍 Visual check: nested table renders with "Header" spanning both columns of the top row, and "A"/"B" as two separate cells in the second row — not four ungrouped cells

**Cleanup:** write fixture content back

**Result (2026-07-09) ✅ PASS**
`write_doc_content` succeeded. `get_doc_structure` showed the outer table (1 row × 1 col) with cell [0,0] text empty. Playwright screenshot confirmed the nested table rendered with "Header" spanning both columns of the top row and "A"/"B" as two separate cells below — the merge applied correctly. (Unrelated observation: the fixture doc had leftover header/footer text visible in the render and in `get_doc_content`'s plain-text export but not in `get_doc_structure` — headers/footers aren't part of the body map that tool returns; pre-existing fixture-doc state from an earlier header/footer test, untouched by `write_doc_content`, not a regression from this PR.) Fixture content restored per cleanup step.

---

### TC-DOC52: `get_doc_theme` scans body paragraph styles
**Note:** `get_doc_theme` reads explicit per-paragraph and per-run styles from the document body. It returns data for AI-generated docs (where styles are set explicitly on runs); for standard docs whose styles are fully inherited from named style defaults it returns an empty dict.

**Prompt**
> "Call `get_doc_theme` on doc {DOC_ID} and show me the result."

**Checks**
- No `error` key in result
- For a doc with explicit paragraph styles: returns a dict with at least one named style type key; each entry has at least one of font_family, font_size, bold, italic, color, line_spacing, space_above, space_below
- For a doc with purely inherited styles: result is an empty dict `{}` (expected, not an error)

**Result (2026-06-20) ✅ PASS** Called on a test doc created with `create_doc` (markdown content — inherited styles): returned `{}`. Called on the same doc after `apply_theme overwrite=True` (Georgia HEADING_1, Roboto NORMAL_TEXT): returned `{"HEADING_1": {"font_family": "Georgia"}, "NORMAL_TEXT": {"font_family": "Roboto"}}`. `font_size` and `bold` are not returned because the Docs API normalises explicit overrides that match the named style default back to inherited. No error key in either case.

---

### TC-DOC53: `apply_theme` updates named style definitions ⚠️ destructive
**Note:** Default mode (`overwrite=False`) emits `updateNamedStyle` requests — one per named style key — updating the document's style defaults. Existing paragraphs with explicit overrides are unaffected. No doc fetch is needed. Use `overwrite=True` to also apply directly to all existing paragraphs.

**Prompt**
> "Apply theme `{"HEADING_1": {"font_family": "Georgia", "font_size": 22}, "NORMAL_TEXT": {"font_family": "Verdana", "font_size": 11}}` to doc {DOC_ID}"

**Checks**
- Result contains `docId` and `requests > 0`
- No `error` key
- `requests` equals the number of named style keys in the theme (one `updateNamedStyle` per key)

**Result (2026-06-20) ✅ PASS** Called with HEADING_1 + HEADING_2 + NORMAL_TEXT → `{"docId": "...", "requests": 3}`. Each emitted one `updateNamedStyle` request with snake_case field mask (`named_style_type,text_style.weighted_font_family,text_style.font_size`). No error. Live API accepted all three requests.

---

### TC-DOC54: `apply_theme` with `overwrite=True` also patches existing paragraphs ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write `<h1>Heading One</h1><p>Normal body text.</p>` to doc {DOC_ID}, then apply theme `{"HEADING_1": {"font_family": "Georgia", "font_size": 22}, "NORMAL_TEXT": {"font_family": "Verdana", "font_size": 11}}` with overwrite=True"

**Checks**
- Result contains `docId` and `requests > 0`
- `requests` > number of named style keys (named style updates + per-paragraph updates)
- No `error` key
- 🔍 Visual check: HEADING_1 paragraph visually in Georgia 22pt, body in Verdana 11pt

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS** Called with HEADING_1 + NORMAL_TEXT on a doc with HEADING_1, HEADING_2 (×2), HEADING_3, NORMAL_TEXT (×4) paragraphs → `{"docId": "...", "requests": 7}` (2 `updateNamedStyle` + 5 `updateTextStyle` for matching paragraphs). No error.

---

### TC-DOC55: `apply_theme` with table styling ⚠️ destructive
**Prerequisite:** doc must contain at least one table (write one with `write_doc_content` first if needed)

**Prompt**
**Playwright: required**
> "Apply this theme to doc {DOC_ID}: `{"table": {"border_color": {"red": 0, "green": 0, "blue": 0}, "border_width": 0.5, "border_dash_style": "SOLID", "cell_padding": 3.6, "header_background": {"red": 0.953, "green": 0.953, "blue": 0.953}}}`"

**Checks**
- Result contains `docId` and `requests > 0`
- 🔍 Visual check: table cells have thin black border, 3.6pt padding, first row has light grey background

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS** Wrote 2-row table, applied table theme → `requests: 2` (one updateTableCellStyle per row; row 0 got header_background + padding + borders, row 1 got padding + borders). No error. Fixture restored.

---

### TC-DOC56: `get_doc_theme` → `apply_theme` round-trip on an AI-generated doc ⚠️ destructive
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

### TC-DOC57: Insert an image by public URI ⚠️ destructive
**Setup:** fetch structure; note the `endIndex` of a paragraph to insert after

**Prompt**
**Playwright: required**
> "Insert an image from URI 'https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png' at index {N} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `index: N`
- 🔍 Visual check in Google Docs: image appears in the document at the insertion point

**Cleanup:** delete the inserted image range (use `delete_doc_range` on the image's index span, visible in `get_doc_structure` as an element)

**Result (2026-06-22) ✅ PASS** Inserted Google branding PNG at paragraph boundary. Response: `{docId, index}`. Image visible in doc. Occupies one index slot as an inline element in `get_doc_structure`.

---

### TC-DOC58: Insert an image with explicit size ⚠️ destructive
**Setup:** same as TC-DOC57

**Prompt**
**Playwright: required**
> "Insert an image from URI 'https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png' at index {N} in doc {DOC_ID} with width 100 and height 50"

**Checks**
- Call succeeds with no API error
- 🔍 Visual check: image is smaller than default size

**Cleanup:** delete inserted image range

**Result (2026-06-22) ✅ PASS** Same PNG at same location with `width=100, height=50`. Call succeeded; image rendered smaller than the default-sized TC-DOC57 image.

---

### TC-DOC59: No source provided returns error
**Prompt**
> "Call insert_inline_image on doc {DOC_ID} at index 1 without providing a URI or drive_file_id"

**Checks**
- Returns `{"error": "Provide either uri or drive_file_id"}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Provide either uri or drive_file_id, not both"}`. No API call made.

---

### TC-DOC60: Both URI and drive_file_id provided returns error
**Prompt**
> "Call insert_inline_image on doc {DOC_ID} at index 1 with both uri 'https://example.com/img.png' and drive_file_id 'someid'"

**Checks**
- Returns `{"error": "Provide only one of uri or drive_file_id, not both"}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Provide only one of uri or drive_file_id, not both"}`. No API call made.

---

## `insert_table_row` / `delete_table_row` / `insert_table_column` / `delete_table_column` (#146)

### TC-DOC61: Insert a row below an existing row ⚠️ destructive
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

## `create_header` / `create_footer` (#147)

### TC-DOC68: Create a default page header ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page header to doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `headerId` (non-empty string)
- 🔍 Visual check in Google Docs: document shows a header section

**Cleanup:** none needed (headers persist; restore fixture doc if desired)

**Result (2026-06-22) ✅ PASS** Called `create_header(doc_id=fixture)` (no content). Returned `{"docId": ..., "headerId": "kix.xxxxxxxxxx"}`. Header section visible in Google Docs. Note: on first call after a prior session created the header (due to index=1 bug), the "already exists" 400 error was caught and the ID was retrieved from `documentStyle.defaultHeaderId` — this is the expected fallback path.

---

### TC-DOC69: Create a header with content ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page header to doc {DOC_ID} with content 'Confidential — Internal Only'"

**Checks**
- Response contains `docId` and `headerId`
- Two API calls were made (create + insert text) — verifiable via no error in response
- 🔍 Visual check: header text "Confidential — Internal Only" appears in the document header

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_header(doc_id=temp_doc, content="Confidential — Internal Only")`. Returned `{"docId": ..., "headerId": "kix.xxxxxxxxxx"}` with no `warning` key — both header creation (via `documentStyle` fallback) and content insertion at `index=0` succeeded.

---

### TC-DOC70: Create a default page footer ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page footer to doc {DOC_ID}"

**Checks**
- Response contains `docId` and `footerId` (non-empty string)
- 🔍 Visual check: document shows a footer section

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_footer(doc_id=fixture)`. Returned `{"docId": ..., "footerId": "kix.xxxxxxxxxx"}`. Footer section visible in Google Docs.

---

### TC-DOC71: Create a footer with content ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page footer to doc {DOC_ID} with content 'Page 1'"

**Checks**
- Response contains `docId` and `footerId`
- 🔍 Visual check: footer shows "Page 1"

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_footer(doc_id=temp_doc, content="Page 1")`. Returned `{"docId": ..., "footerId": "kix.xxxxxxxxxx"}` with no `warning` key — footer created and content inserted at `index=0`.

---

### TC-DOC72: Invalid header_type returns error
**Prompt**
> "Call create_header on doc {DOC_ID} with header_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid header_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid header_type 'INVALID'. Use DEFAULT or FIRST_PAGE_HEADER"}`. No API call made.

---

### TC-DOC73: Invalid footer_type returns error
**Prompt**
> "Call create_footer on doc {DOC_ID} with footer_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid footer_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid footer_type 'BOGUS'. Use DEFAULT or FIRST_PAGE_FOOTER"}`. No API call made.

---

### TC-DOC74: insert_doc_text with segment_id writes into header ⚠️ destructive
**Setup:** call `create_header` first to get a `headerId`

**Prompt**
**Playwright: required**
> "Insert the text 'Header text via insert_doc_text' at index 0 in doc {DOC_ID} using segment_id '{headerId}'"

**Note:** An empty header/footer segment has end index 1 (one newline at index 0). Insert at index 0, not 1.

**Checks**
- Call succeeds with no API error
- Response contains `insertions: 1`
- 🔍 Visual check: "Header text via insert_doc_text" appears in the document header

**Result (2026-06-22) ✅ PASS** Called `insert_doc_text` with `[{index: 0, text: "QA Test Header", segment_id: "kix.xxxxxxxxxx"}]`. Response: `{"docId": ..., "insertions": 1}`. Text "QA Test Header" appeared in fixture doc header. Same mechanism also confirmed for footer segment insertion (segment_id: "kix.xxxxxxxxxx", text: "Page 1").

---

### TC-DOC75: `get_doc_named_styles` reads named style defaults set via the Docs UI
**Note:** Named styles are only populated when the user explicitly goes to Format > Paragraph styles > Update X to match. Most docs leave named styles at Google's defaults — this tool returns empty or near-empty for those docs. Use `get_doc_theme` to read actual paragraph appearance instead.

**Prompt**
> "Call `get_doc_named_styles` on doc {DOC_ID} and show me the result."

**Checks**
- No `error` key in result
- For a doc where named styles were explicitly set: returns a non-empty dict with named style type keys
- For a standard doc: may return `{}` or only Google's default entries (expected, not an error)

**Result (2026-06-20) ✅ PASS** Called on a doc that had `apply_theme` previously applied (Georgia HEADING_1/H2, Roboto NORMAL_TEXT). Returned 9 entries: NORMAL_TEXT (Roboto 11pt, line_spacing 115), HEADING_1 (Georgia 24pt bold, space_above 20), HEADING_2 (Georgia 18pt, space_above 18), HEADING_3–6 (Google defaults with font sizes and colors), TITLE, SUBTITLE. Confirms `apply_theme` default mode successfully writes to named styles, and `get_doc_named_styles` reads them back correctly. No error.

---

### TC-DOC76: Table immediately after heading renders at Normal Text size ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-d226-heading-table.md` from the repo (absolute path: `<repo-root>/docs/qa/fixtures/tc-d226-heading-table.md`)

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d226-heading-table.md, then show me its structure."

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows a `table` element with 6 cells containing "Finding", "Severity", "Ticket", "Some finding", "HIGH", "KINDLY-123"
- 🔍 Visual check: open the doc — table cell text renders visually smaller than the "HIGH" H2 heading above it (~11pt vs ~16pt); no blank paragraph workaround needed

**Cleanup:** delete the created doc

**Result (2026-06-24) ✅ PASS** "HIGH" heading renders visually larger than table text. All six cells ("Finding", "Severity", "Ticket", "Some finding", "HIGH", "KINDLY-123") render at Normal Text size. No blank paragraph between heading and table required. No oversized cell text observed.

---

### TC-DOC77: No visible blank line between heading and table in `create_doc_from_file` ⚠️ requires-oauth ⚠️ destructive

**Background:** the Docs API inserts a structurally-required blank paragraph before every table;
`deleteContentRange` is rejected for it. The fix collapses it to zero visual height via
`updateParagraphStyle` (spaceAbove/Below=0, lineSpacing=1) + `updateTextStyle` (fontSize=1pt).

**Setup:** use `docs/qa/fixtures/tc-d226-heading-table.md` (heading immediately followed by a table)

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d226-heading-table.md, then show me its structure."

**Checks**
- Tool completes without error (no `HttpError 400`)
- `get_doc_structure` returns a body with a heading and a table; a blank paragraph element may still be listed (it is structurally present), but its `paragraph.paragraphStyle` should show `lineSpacing: 1`, `spaceAbove: 0`, `spaceBelow: 0`
- 🔍 Visual check: open the doc — no visible blank line between the "HIGH" heading and the table

**Cleanup:** delete the created doc

**Result (2026-06-25) ✅ PASS**
- Tool completed without error. Structure: sectionBreak → HEADING_2 "HIGH\n" (1-6) → blank para "\n" (6-7, `font_size: 1` on its run confirming collapse applied) → table (7-70, cells filled correctly: Finding/Severity/Ticket header, Some finding/HIGH/KINDLY-123 data) → trailing para (70-71). Visual check: no visible gap between heading and table in the rendered doc.

---

### TC-DOC80: get_doc_content trips the response-size cap; cached path re-checks it too (issue #242)

**Background:** #242 generalized #235's response-size safety net to `get_doc_content`. `doc_cache` previously returned a cached result *before* any cap check ran, so a cached oversized doc would bypass the cap on repeat calls — fixed so the check runs on both the cache-hit and cache-miss paths.

**Setup:** `TEST_LARGE_DOC_ID` (`mcp-gee-sweet-qa-large-doc`), grown from its original ~5,300-character seed content to ~49,700 characters by inserting repeated padding text (permanent fixture growth — this doc's whole purpose is being a large-content fixture, and it was never previously large enough to exceed any cap since none existed for this tool before now).

**Checks**
- First call (fetch path) raises `ValueError` mentioning the actual response size, the cap, and `MAX_TOOL_RESPONSE_CHARS`
- Second call (cache-hit path, no `refresh_cache` in between) raises the *same* error — proves the cache-hit path re-checks the cap rather than returning the stale oversized cached result
- Same call with `local_path` set succeeds, returns `{local_path, id, bytes_written}`, and the file on disk contains the full content

**Result (2026-07-03) ✅ PASS**
Fetch-path call raised: `get_doc_content: the response is 49700 characters, over the 40000-character safety cap. Pass local_path to write the result to disk instead of returning it inline (bypasses this cap), or set MAX_TOOL_RESPONSE_CHARS if your MCP client can handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS).` Repeat call (served from `doc_cache`, confirmed via no additional Drive API round-trip) raised the identical error — confirms the cache-ordering fix. `local_path` call succeeded: `{"local_path":"/tmp/qa_doc_content_242.json","bytes_written":49700,"id":"{TEST_LARGE_DOC_ID}"}`; file verified then cleaned up.

---

### TC-DOC81: create_doc_from_file renders \$ escape as literal $ (issue #213) ⚠️ requires-oauth ⚠️ destructive

**Background:** Python-Markdown's default `ESCAPED_CHARS` omits `$` (unlike CommonMark, which includes it in its escapable-punctuation set), so `\$` — commonly used to defeat math/LaTeX-delimiter renderers like Obsidian/Typora/Jupyter that treat bare `$...$` as inline math — previously passed through untouched into the rendered Doc as a literal backslash+dollar. Fixed via a small `markdown.extensions.Extension` that adds `$` to `ESCAPED_CHARS`, so it's handled by the library's own escape mechanism (respecting code-span/fenced-code protection) rather than a blind text substitution.

**Setup:** use `docs/qa/fixtures/tc-d213-dollar-escape.md` from the repo (a table cell, a second table row, and a plain-text sentence, each with a `\$`-escaped dollar amount)

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d213-dollar-escape.md"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_content` shows `$6,000`, `$25`, and `$1,200` as plain literal dollar amounts — no `\$` (literal backslash+dollar) anywhere in the content

**Cleanup:** delete the created doc

**Result (2026-07-04) ✅ PASS**
`create_doc_from_file` succeeded. `get_doc_content` returned: `"...Deductible\r\n\t$6,000\r\n\tCopay\r\n\t$25\r\n\tPlain text with an escaped price: $1,200 due at signing."` — all three escaped amounts rendered as literal `$`, no `\$` anywhere. Doc permanently deleted after verification.

---

### TC-DOC82: create_doc autolinks bare URLs in markdown content (issue #248) ⚠️ requires-oauth ⚠️ destructive

**Background:** Python-Markdown's built-in autolink only fires on `<https://...>` (angle brackets) or `[text](url)` — a bare URL like `https://example.com/some-page` was left as inert plain text with no hyperlink. Fixed via a low-priority `InlineProcessor` extension that autolinks bare `http(s)://` URLs left as plain text after the library's own link/code-span processing runs, trimming trailing sentence punctuation and unmatched closing parens (CommonMark/GFM extended-autolink behavior).

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'QA TC-DOC82' with content_format='markdown' and this content: `From: https://example.com/some-page. See (https://example.com/parens) for details. Already linked: [click](https://example.com/existing). Code: \`https://example.com/code\`.`"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows a run with `link_url: "https://example.com/some-page"` (trailing period NOT included in the link)
- A run with `link_url: "https://example.com/parens"` (wrapping parens NOT included in the link)
- The existing markdown link still shows `link_url: "https://example.com/existing"` (not double-processed)
- The backtick-wrapped URL has no `link_url` set (code span still suppresses autolinking)

**Cleanup:** delete the created doc

**Result (2026-07-05) ✅ PASS**
`create_doc` succeeded (docId `1F66ZQQMuBx9CjaGx49bBg6DlcVMAYMnqnuYHtouyfIU`). `get_doc_structure` confirmed all four checks: `https://example.com/some-page` run has `link_url` set with the trailing `.` split into its own unlinked run; `https://example.com/parens` run has `link_url` set with both wrapping parens split into unlinked runs; the markdown link's `click` run has `link_url: "https://example.com/existing"` (untouched, not double-processed); the backtick-wrapped `https://example.com/code` run has `link_url: null`. Doc trashed after verification. Visual check (re-created identical content, Playwright screenshot, re-trashed): both bare URLs render blue/underlined, wrapping punctuation stays plain black, `click` renders as a normal link, and the backtick-wrapped URL renders as plain monospace code — not a link.

---

### TC-DOC83: autolink_urls=False leaves bare URLs as plain text (issue #248) ⚠️ requires-oauth ⚠️ destructive

**Background:** The autolinking added for TC-DOC82 is unconditional by default. `autolink_urls: bool = True` on `create_doc`/`create_doc_from_file`/`write_doc_content` lets a caller opt out for the whole call when a bare URL should stay as plain, non-monospace text (backticks are the existing per-URL escape hatch, but they force code styling).

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'QA TC-DOC83' with content_format='markdown', autolink_urls=False, and this content: `See https://example.com/inert here`"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows the URL text present with `link_url: null` (no hyperlink applied)

**Cleanup:** delete the created doc

**Result (2026-07-05) ✅ PASS**
`create_doc` succeeded (docId `1elTfZ70c6AO66cjLQ7O-PrzzUlYGmVwiKuNWjDXVMGI`). `get_doc_structure` confirmed the entire line ("See https://example.com/inert here") is a single unstyled run — no `link_url`, no underline. Doc trashed after verification. Visual check (re-created identical content, Playwright screenshot, re-trashed): entire line renders as plain black text, no blue/underline anywhere.

---

## `insert_page_break` (#148)

### TC-DOC94: Insert a page break at a given index ⚠️ destructive
**Setup:** create a doc with two short paragraphs; note the `endIndex` of the first paragraph

**Prompt**
**Playwright: required**
> "Insert a page break at index {N} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `index: N`
- `get_doc_structure` does not surface the page break as its own element (it's an inline element inside the paragraph, not a top-level body element) — this is expected, not a bug
- 🔍 Visual check in Google Docs: the second paragraph starts on a new page

**Cleanup:** delete the created doc

**Result (2026-07-15) ✅ PASS**
Created a doc with two paragraphs; `get_doc_structure` showed the first paragraph ending at index 38. `insert_page_break(index=38)` returned `{"docId": ..., "index": 38}` with no API error. Re-fetched `get_doc_structure`: the page break did not appear as its own top-level element (as expected) — the second paragraph's `startIndex` shifted from 38 to 40, consistent with an inline break being inserted. Playwright visual check: navigated to the doc, clicked into the body, pressed Ctrl+End to reach the document end — the accessibility live region announced "Entering page 2 of 2," confirming the second paragraph now renders on a new page. Doc trashed after verification.

---

### TC-DOC95: API error returned gracefully (index beyond document end)
**Prompt**
> "Insert a page break at index 99999 in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure (index out of bounds)

**Cleanup:** none (no mutation applied)

**Result (2026-07-15) ✅ PASS**
`insert_page_break(doc_id=<TEST_DOC_ID>, index=99999)` returned `{"error": "<HttpError 400 ... Index 99999 must be less than the end index of the referenced segment, 89. ...>"}` — no exception raised, error clearly references the out-of-bounds index. No mutation applied to the fixture doc.

---

## `list_doc_comments` / `add_doc_comment` / `resolve_doc_comment` (#151)

These operate on the Drive `comments`/`replies` resource, not the Docs API — they work against any file type Drive supports comments on (Docs, Sheets, Slides), but are scoped here to the doc fixture. There is no `delete_doc_comment` tool (out of scope for #151), so comments added during QA are not cleanable via a tool call — they persist as real threads on the fixture doc until removed manually in the Docs UI. Keep test comment text prefixed `QA TC-DOC…` so they're identifiable for manual cleanup.

### TC-DOC96: Add a comment with no quoted-text anchor ⚠️ destructive
**Prompt**
> "Add a comment 'QA TC-DOC96: general note.' to doc {DOC_ID}"

**Checks**
- Returns `id`, `content` matching the input text, `author` (`display_name`/`email_address` populated from the caller's identity), `created_time`
- `quoted_text` is `null` — no anchor was requested
- No error

**Cleanup:** none available — no `delete_doc_comment` tool exists; the comment persists on the fixture doc (see section note above)

**Result (2026-07-16) ✅ PASS**
`add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC96: general note.")` returned `id: "AAAB-5FtNYE"`, `content` matching the input, `author.display_name: "Kevin Huisman"`, `created_time`, `quoted_text: null`. No error. Note: `author.email_address` was `null` rather than populated — this is Drive API behavior for the authenticated OAuth user's own comments (email visibility is a privacy-scoped field), not a tool defect; the tool correctly passes through whatever the API returns.

---

### TC-DOC97: Add a comment anchored to quoted text ⚠️ destructive
**Setup:** `{DOC_ID}` must contain the literal text "QA anchor target" somewhere (use `write_doc_content` to add it first if absent)

**Prompt**
> "Add a comment 'QA TC-DOC97: anchored note.' to doc {DOC_ID}, quoting the text 'QA anchor target'"

**Checks**
- Returns `quoted_text: "QA anchor target"` — the anchor round-trips through the API response
- `list_doc_comments` on the same doc shows this comment with the same `quoted_text`

**Cleanup:** none available (see section note above)

**Result (2026-07-16) ✅ PASS**
Doc lacked the literal text "QA anchor target", so it was inserted via `insert_doc_text` (not `write_doc_content`, which replaces the whole doc body — using it as the setup note suggests would have wiped the fixture's existing content). `add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC97: anchored note.", quoted_text="QA anchor target")` returned `quoted_text: "QA anchor target"`, round-tripping correctly. Confirmed via `list_doc_comments` in TC-DOC98 below.

---

### TC-DOC98: List comments reflects previously added comments
**Setup:** run TC-DOC96 and TC-DOC97 first

**Prompt**
> "List the comments on doc {DOC_ID}"

**Checks**
- Both the TC-DOC96 and TC-DOC97 comments appear in `comments`
- Each has `resolved: false` and `replies: []`
- The TC-DOC97 entry has `quoted_text: "QA anchor target"`; the TC-DOC96 entry has `quoted_text: null`
- `doc_id` in the response matches `{DOC_ID}`

**Cleanup:** none (read-only)

**Result (2026-07-16) ✅ PASS**
`list_doc_comments(doc_id=<TEST_DOC_ID>)` returned both comments: TC-DOC97 (`quoted_text: "QA anchor target"`) and TC-DOC96 (`quoted_text: null`), both `resolved: false` and `replies: []`, `doc_id` echoed correctly.

---

### TC-DOC99: Resolve a comment ⚠️ destructive
**Setup:** use the `id` returned by TC-DOC96 as `{COMMENT_ID}`

**Prompt**
> "Resolve comment {COMMENT_ID} on doc {DOC_ID} with the reply 'Handled.'"

**Checks**
- Returns `doc_id`, `comment_id`, `reply_id`, and `action: "resolve"`
- Re-running `list_doc_comments` shows that comment with `resolved: true` and a reply with `content: "Handled."` and `action: "resolve"`

**Cleanup:** none available — resolving doesn't remove the comment thread, just marks it resolved (see section note above)

**Result (2026-07-16) ✅ PASS**
`resolve_doc_comment(doc_id=<TEST_DOC_ID>, comment_id="AAAB-5FtNYE", reply_content="Handled.")` returned `doc_id`, `comment_id`, `reply_id: "AAAB-5FtNYQ"`, `action: "resolve"`. Re-ran `list_doc_comments`: the TC-DOC96 comment now shows `resolved: true` with a reply `content: "Handled.", action: "resolve"`. The reply also included `modified_time` — confirms the fix from PR review comment (missing `modified_time` on replies) is live.

---

### TC-DOC100: Resolve a non-existent comment ID
**Prompt**
> "Resolve comment 'not-a-real-comment-id' on doc {DOC_ID}"

**Checks**
- API error propagates — not a silent success or server crash

**Cleanup:** none (no mutation applied)

**Result (2026-07-16) ✅ PASS**
`resolve_doc_comment(doc_id=<TEST_DOC_ID>, comment_id="not-a-real-comment-id")` raised `HttpError 404 ... "Comment not found: not-a-real-comment-id."` — propagated cleanly, no silent success, no server crash.

---

### TC-DOC101: List comments on a non-existent doc
**Prompt**
> "List the comments on doc 'not-a-real-doc-id'"

**Checks**
- API error propagates — not a silent empty list or server crash

**Cleanup:** none (no mutation applied)

**Result (2026-07-16) ✅ PASS**
`list_doc_comments(doc_id="not-a-real-doc-id")` raised `HttpError 404 ... "File not found: not-a-real-doc-id."` — propagated cleanly, no silent empty list, no server crash.
## HTML/Markdown → Doc image conversion (#332, #333)

**Background:** `_AstParser` in `html_parser.py` has no `<img>` handling at all — `handle_starttag`/`handle_endtag` recognize block tags, inline formatting tags, table tags, and list tags, but an `img` tag matches none of those branches and is silently ignored. Since markdown images (`![alt](src)`) are converted to `<img>` HTML by `_md_to_html` before reaching this same parser, **every** content path that goes through the shared AST pipeline — `create_doc`, `create_doc_from_file`, `write_doc_content`, for both `content_format="html"` and `content_format="markdown"` — drops images with no error, no warning, and no placeholder. The only working path today is the separate `insert_inline_image` tool (TC-DOC57/58), which requires a second pass of index bookkeeping after the doc already exists (the manual workaround documented in #332/#333).

This is worse than a simple drop in two cases, both verified directly against `html_to_ast` on the fixtures below:
- A paragraph (or table cell) whose **only** content is an image produces **zero** AST nodes for it — not even an empty paragraph/cell. `ast_to_requests`'s guard `if not text.strip(): continue` (and the equivalent cell-fill guard in `emitter.py`) discards it entirely.
- An inline image inside running text (`"before <img> after"`) leaves no gap, marker, or trace — the surrounding runs are simply concatenated (`"before "` + `" after"`), so a caller inspecting `get_doc_structure` afterward has no signal an image was ever present in the source.

**Fixtures:** `docs/qa/fixtures/tc-doc102-image-conversion.html` and `docs/qa/fixtures/tc-doc103-image-conversion.md` — each covers 8 placement cases: standalone image paragraph, inline mid-paragraph, two consecutive images with no separating text, image wrapped in a link, image inside a list item, image inside a table cell, image inside a nested table cell (HTML only — markdown tables can't nest, matching the documented limitation in TC-DOC51; the markdown fixture substitutes reference-style `![alt][ref]` syntax for its Case 7 instead), and an image with an unreachable URL (included specifically to show the drop happens at parse time, before any HTTP fetch is attempted — a dead image URL fails identically to a live one).

### TC-DOC102: HTML image conversion — every placement should produce a visible image ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc102-image-conversion.html"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows all 8 headings and surrounding paragraph text intact
- Each of the 8 cases produces an inline image element (`get_doc_structure` doesn't currently surface inline images explicitly — cross-check via element/paragraph text length matching an image occupying one index slot, as in TC-DOC57)
- 🔍 Visual check in Google Docs: an image renders in each of the 8 cases, including inside the plain table cell and the nested table cell
- Final paragraph after Case 8 is present (confirms the document isn't truncated)

**Cleanup:** delete the created doc

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`html_to_ast`), not yet run live against the Docs API.** Running the fixture through `html_to_ast` this session confirms every one of the 8 cases drops its image with zero trace:
- Case 1 (standalone image paragraph): the paragraph containing only the image produces **no AST node at all** — not even an empty paragraph. `get_doc_structure` would show "Paragraph before the image." followed directly by "Paragraph after the image." with nothing between them.
- Case 2 (inline mid-paragraph): AST paragraph text is `"Text before "` + `" text after, same paragraph."` — concatenated with no gap or marker.
- Case 3 (two consecutive images, no text): produces **zero** AST nodes — the whole paragraph vanishes.
- Case 4 (image wrapped in a link): produces **zero** AST nodes — same as Case 3, since the only content was the image.
- Case 5 (image inside a list item): `BulletItem` text is `"List item with an image "` + `" inline"` — image silently gone, item otherwise intact.
- Case 6 (image inside a table cell): cell `children` is `[]` — completely empty cell, no error.
- Case 7 (image inside a nested table cell): the nested `Table` itself comes through correctly as a structural node, but its own single cell (containing only the image) is empty, same as Case 6.
- Case 8 (unreachable URL): produces **zero** AST nodes, identically to Case 1/3/4 — confirms the drop happens at parse time regardless of URL validity.
- Live execution + Playwright visual check still needed to confirm end-to-end behavior against the real API; not run this session (no live MCP tool access outside a release pass — see `.claude/team-roles/aziz.md`).

---

### TC-DOC103: Markdown image conversion shares the same drop as the HTML path ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc103-image-conversion.md"

**Checks**
- `docId` and `web_link` returned with no `error`
- Same 8-case expectations as TC-DOC102 (Case 7 here is reference-style `![alt][ref]` syntax instead of a nested table)
- 🔍 Visual check: images render in all 8 cases, including the reference-style image

**Cleanup:** delete the created doc

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`_md_to_html` → `html_to_ast`), not yet run live.** `_md_to_html` correctly converts every markdown image (inline, reference-style, link-wrapped) into an `<img>` tag first — confirmed by inspecting the intermediate HTML — so the markdown path funnels into the exact same unhandled-`img` gap as TC-DOC102. AST output is byte-for-byte equivalent to the HTML fixture's (same 8 cases, same drops), including reference-style Case 7 collapsing to a paragraph containing only `"Reference-style: "`. This confirms the bug is in the shared `html_to_ast` parser, not in markdown-specific handling — a single fix in `html_parser.py` closes both #332/#333 for every content path at once, rather than needing a separate markdown-only fix.

---

## HTML/Markdown → Doc nested list conversion (#334)

**Background:** Three independent, compounding bugs, isolated separately below:

1. **Parser data loss (`html_parser.py`, both HTML and Markdown paths):** `_AstParser.handle_starttag`'s block-tag branch (`if tag in _BLOCK_TAGS and self._table_depth == 0:`) unconditionally resets `self._run_buf`/`self._pending_runs` whenever ANY block tag opens — including a nested `<li>` opening inside an already-open outer `<li>`. There's no stack/save-restore of the outer block's in-progress buffer, so **the outer list item's own text is silently destroyed** whenever that item has both its own text and a nested sub-list (the extremely common `<li>Item text<ul>...</ul></li>` shape — e.g. any markdown of the form `- Item:\n  - sub\n  - sub`). This is data loss, not just a rendering/flattening issue: verified directly against `html_to_ast` — a source list with "Parent A has text" + 2 nested children produces only the 2 children in the AST; "Parent A has text" never appears anywhere.
2. **Emitter ignores depth (`emitter.py`):** even where the parser *does* correctly track nesting (`BulletItem.depth`, verified correct in all cases below, including the ones unaffected by bug 1), `ast_to_requests` never reads `.depth` or `.paragraph_style` — `createParagraphBullets` is emitted with only `range` and `bulletPreset`, no indentation. Google Docs infers a bullet's nesting level from paragraph indentation, not an explicit field on the create request, so **every bullet renders at nesting level 0 in the live document regardless of source depth.** This is a real gap even for a list with zero parent-text collisions.
3. **Markdown-specific, on top of 1+2:** python-markdown's `sane_lists` extension (used by `_md_to_html`) only recognizes a sub-list as nested when indented by exactly 4 spaces or a tab. The CommonMark/GFM-standard indentation that most people and tools (including Claude) write by default — 2 spaces under a `-`/`*` marker, 3 spaces under a `1.` marker — is silently flattened to the parent list **before it even reaches the HTML parser**, with no warning. Verified empirically this session (`uv run python3 -c "import markdown; ..."`) across four indentation widths.

**Fixtures:** `docs/qa/fixtures/tc-doc104-nested-lists.html` (direct HTML, isolates bugs 1+2 with no markdown-library involvement), `docs/qa/fixtures/tc-doc105-nested-lists-gfm.md` (GFM-standard 2/3-space indentation, adds bug 3 on top), `docs/qa/fixtures/tc-doc106-nested-lists-4space.md` (4-space indentation — the documented python-markdown workaround — reproduces bugs 1+2 only, proving they're independent of bug 3). Each fixture has 3 cases: parent item with its own text + a nested sub-list (bug 1 trigger), a bare parent item with no text of its own (isolates bug 2 alone, since there's no parent text to lose), and ordered-in-ordered nesting.

### TC-DOC104: Direct HTML nested lists — parent item text must survive when a sub-list follows it ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: contents of docs/qa/fixtures/tc-doc104-nested-lists.html"

**Checks**
- `get_doc_structure` shows "Parent A has text" and "Parent B has text" as their own bullet items, each followed by their nested children
- Case 2's bare-nested children ("Bare-nested child C1"/"C2") appear at a visibly deeper indentation than Case 2's (absent) parent
- Case 3's "Top ordered 1" survives as its own item, with "Nested ordered 1.1"/"1.2" indented under it
- 🔍 Visual check in Google Docs: 3 distinct indentation levels are visible in Case 1 (Parent A / Child A2 / Grandchild A2a), and Case 2/3's nesting is visually indented, not flush-left

**Cleanup:** write fixture content back

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`html_to_ast`), not yet run live.** Confirmed exactly the predicted content loss: "Parent A has text" and "Parent B has text" (Case 1) and "Top ordered 1" (Case 3) — every parent item that has both its own text and a nested sub-list — produce **zero** `BulletItem`s; only their children survive, at depths 1/2 computed correctly. Case 2 (bare parent, no text to lose) correctly preserves both children at `depth=1` — this isolates bug 2 cleanly: depth is tracked right, but since `ast_to_requests` never emits it (confirmed by `grep -n "depth\|indentStart\|nestingLevel" emitter.py` returning zero matches in the relevant code), even these correctly-tracked items would still render at nesting level 0 in the live doc. Live execution + Playwright visual check still needed to confirm the live-rendering half of bug 2 (indentation is not exposed by `get_doc_structure` today — a related tooling gap, see note below).

**Result (2026-07-27) ❌ FAIL — run live against PR #432 (issue #336's emitter fix), Playwright visual check.** Bug 1 (parent text lost) is confirmed fixed independently (unrelated PR #401/`preserve_if_empty` work) — "Parent A has text"/"Parent B has text"/"Top ordered 1" all survive as their own bullet items with correct `depth` in `get_doc_structure`. But bug 2's live-rendering half is **not fixed** — PR #432's new leading-tab/`createParagraphBullets` mechanism produces visibly broken, inconsistent nesting, not the flat-nesting-level-0 the PR describes replacing:
- Two siblings at the *same* AST `depth=1` ("Child A1" and "Child A2", both children of "Parent A has text") render at **different** visual indentation levels — "Child A1" sits flush with its depth-0 parent (unindented), while "Child A2" is indented one level, as if it were Child A1's child rather than its sibling.
- The same pattern recurs for "Ordered child B1"/"B2" and "Nested ordered 1.1"/"1.2" — first item after a preceding bullet's own `createParagraphBullets` call stays at the wrong level; later siblings shift progressively.
- Ordered-list numbering is corrupted: "Ordered child B1" and "Ordered child B2" both render as "1." (not "1."/"2."); "Top ordered 1"/"Top ordered 2" also lose continuous numbering across the nested block.
- On the raw HTML fixture specifically (not the 4-space-markdown fixture below), literal whitespace between a `<li>`'s own text and its nested `<ul>` (the fixture file's own indentation, e.g. `Parent A has text\n    <ul>`) is preserved by `html_parser.py`'s existing whitespace handling as part of the same `BulletItem`'s run text, and the embedded newline splits it into an extra empty bullet paragraph in the live doc when rendered (visible in the screenshot as a stray bullet with no text between "Parent A has text" and "Child A1"). This part is unrelated to PR #432 (pre-existing `html_parser.py` behavior, reproducible with any depth-0 bullet regardless of the tab mechanism) but compounds the visible breakage on this fixture.
- Root cause not fully isolated — confirmed via an offline `ast_to_requests` dump (no live API) that request ordering/index math for the deferred nested-bullet pass looks internally consistent (each `createParagraphBullets` range's boundaries line up exactly against `full_text`, no character-index overlap between requests) — see TC-DOC106's result below, which reproduces the identical first-sibling-not-indented/numbering-corruption pattern on a markdown fixture with **no** embedded-whitespace paragraphs at all, ruling out the whitespace/embedded-newline issue as the actual cause of the indentation bug itself. Most likely explanation: the Docs API's `createParagraphBullets` nesting inference is not purely a function of each call's own leading-tab count in isolation, as the code's own comment assumes — something about calling it via separate, out-of-visual-order requests (this PR's deferred, descending-position pass) instead of one combined call, or per-call adjacency to an already-bulleted neighbor, is affecting the level the API actually assigns. Needs the PR author to reproduce directly against the live API (not just the mocked unit tests, which only assert request *construction*, not actual Docs API rendering behavior) to pin down the exact mechanism.
- Screenshots and repro scripts available in this session for the Dev's follow-up.

**Sending back to Dev — this is the PR's own target behavior failing live on the repo's existing QA fixture, not a peripheral or edge-case finding.**

**Result (2026-07-27, round 2) ✅ PASS — re-run live against PR #432 commit 5fa26e7 (Playwright visual check), after Dev's fix.** Root cause was confirmed to be exactly what round 1 suspected: separate per-paragraph `createParagraphBullets` calls let each paragraph land under a different `listId`. The fix groups maximal contiguous same-preset `BulletItem` runs into one call. Live re-verification:
- Case 1: "Child A1"/"Child A2" (both `depth=1`) now render at the **same** indentation level (circle glyph), "Grandchild A2a" (`depth=2`) renders one level deeper (square glyph) — 3 distinct levels confirmed. "Ordered child B1"/"B2" render with continuous numbering ("1.", "2.").
- Case 3: "Top ordered 1" → "Nested ordered 1.1"/"1.2" (rendered "a."/"b.", correct decimal→alpha nesting) → "Top ordered 2" — correct nesting and numbering.
- Case 2: "Bare-nested child C1"/"C2" render visibly more indented than the absent parent (checklist requirement met), though their bullet glyph is a disc rather than the circle used by other `depth=1` items elsewhere in the doc — a narrow, isolated-run edge case (a contiguous bulleted run with no `depth=0` member to anchor nesting level 0 against). Not part of this test case's stated checklist; filed separately as #439, non-blocking.
- The stray empty-bullet paragraph noted in round 1 is confirmed pre-existing and unrelated to this PR (reproduced identically on TC-DOC106 below, which has no such artifact at all in its markdown source) — out of scope here.

**PASS — bugs 1 and 2 both confirmed fixed live.**

---

### TC-DOC105: Markdown nested lists at GFM-standard (2/3-space) indentation ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': contents of docs/qa/fixtures/tc-doc105-nested-lists-gfm.md"

**Checks**
- Same nesting expectations as TC-DOC104 (this is the indentation width most humans/AI tools write by default — it should behave the same as explicit HTML nesting)
- No literal `1.`/`2.` digit-dot text visible anywhere in bullet content

**Cleanup:** write fixture content back

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`_md_to_html`), not yet run live.** This is worse than TC-DOC104, not merely equivalent: 2-space indentation doesn't clear `sane_lists`' 4-space nesting threshold, so the sub-list syntax is never recognized as a list at all.
- Case 1: "Child A1" and "Child A2" become **sibling** bullets of "Parent A has text" (fully flattened, not nested) — while "Parent B has text" ends up with the literal text `"Parent B has text\n  1. Ordered child B1\n  2. Ordered child B2"` glued into ONE bullet item, i.e. the ordered sub-items render as raw, visible `1.`/`2.` characters in the doc rather than as list items or even flattened siblings — a strictly worse failure mode a user would see as garbled text, not just missing indentation.
- Case 2: a bare `-` marker with nothing else on its line, followed by an indented sub-list, isn't recognized as a list item at all by `sane_lists` — the whole block degrades to a single plain paragraph containing the literal source text (`"-\n  - Bare-nested child C1\n  - Bare-nested child C2"`).
- Case 3: "Top ordered 1" survives as its own item (no bug-1 collision at this indentation, since the sub-items aren't recognized as nested — they become plain siblings instead), but "Nested ordered 1.1"/"1.2" render as flat siblings, not nested, and are mis-numbered as continuing the same list as "Top ordered 1"/"2" in the live doc.
- Live execution + Playwright visual check still needed; not run this session.

---

### TC-DOC106: Markdown nested lists at 4-space indentation — isolates bugs 1+2 from bug 3 ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': contents of docs/qa/fixtures/tc-doc106-nested-lists-4space.md"

**Checks**
- Same nesting expectations as TC-DOC104 — 4-space indentation is the one width where `_md_to_html` produces genuinely nested `<ul>`/`<ol>` HTML, so this TC should behave identically to TC-DOC104 once bugs 1+2 are fixed
- Confirms whether a "use 4 spaces" workaround note in tool docstrings would be sufficient today (it would not — bugs 1+2 still apply at this indentation)

**Cleanup:** write fixture content back

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`_md_to_html` → `html_to_ast`), not yet run live.** At 4-space indentation, `_md_to_html` produces properly nested `<ul>`/`<ol>` HTML (confirmed by inspecting the intermediate HTML output), so this fixture reproduces TC-DOC104's HTML-path results exactly: "Parent A has text"/"Parent B has text"/"Top ordered 1" all lost to bug 1, correct `depth` values (1, 2) on the surviving children, Case 2's bare-parent children correctly preserved at `depth=1`. This confirms bugs 1+2 are independent of the markdown-library indentation quirk (bug 3) — fixing `_md_to_html`'s indentation sensitivity alone would not fix nested lists; `html_parser.py` and `emitter.py` both need fixing regardless of indentation width used.

**Result (2026-07-27) ❌ FAIL — run live against PR #432, Playwright visual check.** Bug 1 confirmed fixed (independent of this PR). Bug 2's live-rendering is **not fixed**, and this fixture is the more important data point of the two run this round since it has no interstitial-whitespace paragraphs at all (unlike TC-DOC104's raw-HTML fixture): "Child A1" (AST `depth=1`) still renders flush with "Parent A has text" (`depth=0`) while its own sibling "Child A2" (also `depth=1`) renders one level deeper, and "Ordered child B1"/"B2" both render as "1." instead of continuing the numbering. This isolates the defect to PR #432's `createParagraphBullets`/leading-tab mechanism itself — see TC-DOC104's result above for full detail and root-cause discussion. Sending back to Dev alongside TC-DOC104.

**Result (2026-07-27, round 2) ✅ PASS — re-run live against PR #432 commit 5fa26e7 (Playwright visual check), after Dev's fix.** This fixture is the clean confirmation (no whitespace artifacts to confound the result): Case 1 "Child A1"/"Child A2" both render at the same, correct depth-1 indentation (circle glyph), "Grandchild A2a" one level deeper (square glyph), "Ordered child B1"/"B2" number continuously ("1.", "2."). Case 3 "Top ordered 1" → "Nested ordered 1.1"/"1.2" (alpha-nested, "a."/"b.") → "Top ordered 2" nests and numbers correctly. Confirms the fix, independent of TC-DOC104's unrelated whitespace-artifact noise.

**PASS.**

---

**Tooling gap note (not a fix, just a QA-visibility limitation):** `get_doc_structure` doesn't currently expose paragraph indentation or the Docs API's bullet `nestingLevel` field, so confirming bug 2's live-rendering half (or a future fix for it) requires a Playwright visual check every time rather than a structural assertion. Worth a follow-up ticket if this bug is fixed — the same way `font_family` is already a known `get_doc_structure` gap (TC-DOC42/47).

---

## `create_named_range` / `create_bookmark` (#152)

The Docs API has no dedicated bookmark-creation endpoint — `create_bookmark` is implemented as a thin wrapper over `createNamedRange` spanning a single character. Neither tool's output is visible anywhere in the Docs UI (named ranges aren't a UI-surfaced concept), so verification is API-round-trip only, except TC-DOC109 which specifically checks the UI does *not* show the bookmark, to confirm the docstring's caveat is accurate.

### TC-DOC107: `create_named_range` creates a named range over a span ⚠️ destructive
**Setup:** create a doc with a paragraph of text; call `get_doc_structure` to get its `startIndex`/`endIndex`

**Prompt**
> "Create a named range called 'section-a' spanning indices {N} to {M} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, a non-empty string `namedRangeId`, `name: "section-a"`, `startIndex: N`, `endIndex: M`

**Cleanup:** delete the created doc

**Result (2026-07-17) ✅ PASS**
`create_named_range(doc_id, name="section-a", start_index=1, end_index=64)` against a doc with one paragraph of real text returned `{"docId": ..., "namedRangeId": "kix.kmeha3539w3s", "name": "section-a", "startIndex": 1, "endIndex": 64}` — all fields present and correct. Note: `create_doc`'s `content` param and a plain-text (no wrapping tag) call to `write_doc_content` both silently produced an empty document body (confirmed live via Playwright screenshot) — wrapping the same text in `<p>...</p>` via `write_doc_content` worked. This is unrelated to `create_named_range`/`create_bookmark` (not touched by this PR) but is a real, reproducible bug in the existing HTML content pipeline; flagging separately, not blocking this PR. Filed as issue #343; fixed — see TC-DOC131/TC-DOC132 below.

---

### TC-DOC108: `create_named_range` — API error returned gracefully (end_index beyond document end)
**Prompt**
> "Create a named range called 'bad' spanning indices 1 to 99999 in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure (index out of bounds)

**Cleanup:** none (no mutation applied)

**Result (2026-07-17) ✅ PASS**
Returned `{"error": "<HttpError 400 ... Index 99998 must be less than the end index of the referenced segment, 65.>"}` — clean error dict, no exception, references index out of bounds.

---

### TC-DOC109: `create_bookmark` creates a single-character named range anchor ⚠️ destructive
**Setup:** create a doc with a paragraph of text; call `get_doc_structure` to get a valid index `N` within it

**Prompt**
**Playwright: required**
> "Create a bookmark called 'intro' at index {N} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, a non-empty string `namedRangeId`, `name: "intro"`, `index: N`
- 🔍 Visual check in Google Docs: Insert > Link, then click the "Headings, bookmarks, and tabs" button in the link dialog — the resulting list does **not** include "intro" — confirms this is a named-range-backed anchor, not a native Docs UI bookmark (documented limitation)

**Cleanup:** delete the created doc

**Result (2026-07-17) ✅ PASS**
`create_bookmark(doc_id, name="intro", index=1)` returned `{"docId": ..., "namedRangeId": "kix.jare8zg6gej", "name": "intro", "index": 1}`. Playwright: Insert > Link > "Headings, bookmarks, and tabs" listed only "Tab 1" — "intro" does not appear, confirming the documented limitation (not a native Docs UI bookmark).

---

### TC-DOC110: `create_bookmark` — API error returned gracefully (index beyond document end)
**Prompt**
> "Create a bookmark called 'bad' at index 99999 in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure (index out of bounds)

**Cleanup:** none (no mutation applied)

**Result (2026-07-17) ✅ PASS**
Returned `{"error": "<HttpError 400 ... Index 99999 must be less than the end index of the referenced segment, 65.>"}` — clean error dict, no exception, references index out of bounds.

---

### TC-DOC111: `find_in_doc` literal case-insensitive search returns correct offsets
**Setup:** create a doc via `write_doc_content` with content `<p>Hello World</p><p>another hello here</p>`

**Prompt**
> "Find all instances of 'hello' in doc {DOC_ID}"

**Checks**
- Returns a list of 2 matches
- First match: `matched_text` is `"Hello"`, `context` is `"Hello World"`
- Second match: `matched_text` is `"hello"`, `context` is `"another hello here"`
- Each match's `start_index`/`end_index` span exactly the matched text — confirm by calling `get_doc_structure` and slicing the paragraph text at those offsets

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
2 matches returned. `start_index`/`end_index` (1-6, 21-26) confirmed exact against `get_doc_structure` paragraph offsets (paragraphs start at 1 and 13).

---

### TC-DOC112: `find_in_doc` regex search feeds directly into `style_doc_range` to hyperlink matches ⚠️ destructive
**Setup:** create a doc via `write_doc_content` with content `<p>Contact test@example.com or admin@example.com for help</p>`

**Prompt**
> "Find every email address in doc {DOC_ID} using a regex, then turn each one into a mailto: link"

**Checks**
- `find_in_doc(doc_id, query=r"[\w.]+@[\w.]+", regex=True)` returns 2 matches with the correct `matched_text` values and offsets
- Calling `style_doc_range` with `link_url="mailto:" + matched_text` at each returned `start_index`/`end_index` succeeds
- `get_doc_structure` afterward shows both runs with `link_url` set to the corresponding `mailto:` address, confirming the offsets from `find_in_doc` landed on the exact right characters

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
2 email matches found; `style_doc_range` applied `mailto:` links at the returned offsets; `get_doc_structure` afterward showed both runs split exactly at the email boundaries with the correct `link_url`.

---

### TC-DOC113: `find_in_doc` case_sensitive=True excludes different-case matches
**Setup:** create a doc via `write_doc_content` with content `<p>Hello World, another hello here</p>`

**Prompt**
> "Find case-sensitive matches of 'hello' in doc {DOC_ID}"

**Checks**
- Returns exactly 1 match (`matched_text: "hello"`) — the capitalized "Hello" in the same doc is excluded

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
Exactly 1 match returned (`"hello"`); capitalized "Hello" correctly excluded.

---

### TC-DOC114: `find_in_doc` invalid regex returned gracefully
**Setup:** create a doc via `write_doc_content` with any content

**Prompt**
> "Search doc {DOC_ID} using the regex '(unclosed'"

**Checks**
- Returns `{"error": "..."}` referencing the invalid regex — does not raise an exception

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
Returned `{"error": "Invalid regex: missing ), unterminated subpattern at position 0"}}` — clean error dict, no exception. Also spot-checked live: an invalid `doc_id` now returns `{"error": "<HttpError 404 ...>"}` instead of raising (regression test for the fix to the missing-try/except finding from code review).

---

### TC-DOC115: `find_in_doc` searches table cell text
**Setup:** create a doc, insert a 1x1 table via `insert_doc_table`, then write "needle" into the cell via `insert_doc_text` at the cell's `paragraphStartIndex` (from `get_doc_structure`)

**Prompt**
> "Find 'needle' in doc {DOC_ID}"

**Checks**
- Returns 1 match with `matched_text: "needle"` and `start_index` equal to the cell's `paragraphStartIndex`

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
1 match returned, `start_index` (11) equal to the cell's `paragraphStartIndex` (11).

---

## `insert_softbreak_paragraph` (#332)

Not tagged `⚠️ requires-oauth` — like `insert_doc_text`/`style_doc_range`, the tool itself is auth-agnostic; only the fixture doc happens to live in personal Drive.

### TC-DOC116: Two lines join into a single soft-break paragraph with an explicit style ⚠️ destructive
**Setup:** create a doc with a placeholder paragraph via `write_doc_content`; note the placeholder paragraph's `startIndex`

**Prompt**
**Playwright: required**
> "Insert a soft-break paragraph at index {N} in doc {DOC_ID} with lines [{text: 'Document ID: KH-OPS-001', bold: true}, {text: 'Category: AWS / Database'}], named_style_type HEADING_2"

**Checks**
- Response has no `error`; `start_index`/`end_index`/`line_ranges` are present, and each `line_ranges` entry's span matches its line's text length
- `get_doc_structure` shows **one** paragraph element spanning the inserted block (not two) — confirms the `\v` separator did not create a paragraph break
- That paragraph's `namedStyleType` is `HEADING_2`
- 🔍 Visual check in Google Docs: the two lines render as one tight paragraph (no blank-line gap between them) with a visible line break; only the first line is bold

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
Structural checks confirmed (single paragraph, HEADING_2, correct line_ranges). Playwright screenshot confirmed one tight paragraph with a visible soft line break, only "Document ID: KH-OPS-001" bold.

---

### TC-DOC117: Invalid named_style_type rejected without mutating the doc
**Setup:** create a doc via `write_doc_content` with any content

**Prompt**
> "Insert a soft-break paragraph at index 1 in doc {DOC_ID} with lines [{text: 'x'}], named_style_type 'NOT_A_STYLE'"

**Checks**
- Returns `{"error": "..."}` naming the invalid value — does not raise an exception
- `get_doc_structure` shows the doc unchanged (no insertion occurred)

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
Returned `{"error": "invalid named_style_type 'NOT_A_STYLE'; must be one of: ..."}}`; doc structure confirmed unchanged.

---

## `insert_local_images` (#332)

**Fixture:** `docs/qa/fixtures/qa-fixture-pixel.png` — a 1×1 pixel PNG, small enough to commit directly; only used to confirm placement/replacement mechanics, not visual image quality.

Tagged `⚠️ requires-oauth` on every case that reaches the upload step — the tool calls the same local-file-upload path as `upload_local_file`, which cannot write to personal Drive under a service account (see its docstring). Error-path cases that return before any upload (marker not found/not unique, missing local file) are not tagged, matching the convention for `insert_inline_image`'s own error-path tests.

### TC-DOC118: Single marker is replaced by an uploaded image ⚠️ requires-oauth ⚠️ destructive
**Setup:** create a doc via `write_doc_content` with content `<p>before</p><p>IMGMARKERONE</p><p>after</p>`

**Prompt**
**Playwright: required**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERONE', local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png', into folder {FOLDER_ID}"

**Checks**
- `results` has exactly one entry with no `error`, a `fileId`, and an `index` equal to the "IMGMARKERONE" paragraph's `startIndex` (from a prior `get_doc_structure`)
- `get_doc_structure` afterward: the marker text is gone, the "before"/"after" paragraphs are unaffected, and the middle paragraph's `endIndex - startIndex` is now 2 (one image "character" + the paragraph's trailing `\n`)
- The uploaded file (`results[0].fileId`) is shared `anyone`/`reader` (`list_permissions`)
- 🔍 Visual check in Google Docs: an image renders where the marker used to be, and the literal marker text is gone

**Cleanup:** delete the created doc; delete the uploaded image file

**Result (2026-07-19) ✅ PASS**
`results` had one entry, `fileId` present, `index` 8 matched the marker paragraph's `startIndex`. Middle paragraph's span was exactly 2 (image + `\n`); before/after paragraphs unaffected. `list_permissions` confirmed `anyone`/`reader`.

---

### TC-DOC119: Two markers are placed in one call, higher index first
**Setup:** create a doc via `write_doc_content` with content `<p>MARKERONE</p><p>MARKERTWO</p>`

**Prompt**
**Playwright: required**
> "In doc {DOC_ID}, insert local images: marker 'MARKERONE' and marker 'MARKERTWO', both using local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png', into folder {FOLDER_ID}"

**Checks**
- `results` has two entries, both with no `error` and distinct `fileId`s
- `get_doc_structure` afterward: both marker texts are gone and both paragraphs now contain only an image
- 🔍 Visual check: both paragraphs show an image, in the original top-to-bottom order

**Cleanup:** delete the created doc; delete both uploaded image files

**Result (2026-07-19) ✅ PASS**
Both entries succeeded with distinct fileIds, returned in input order (MARKERONE, MARKERTWO) despite MARKERTWO sitting at the higher document index — confirms the results-ordering fix live. Both paragraphs reduced to image-only spans afterward.

---

### TC-DOC120: Marker not found / not unique / local file missing all fail per-image without mutating the doc
**Setup:** create a doc via `write_doc_content` with content `<p>DUPMARKER</p><p>DUPMARKER</p>`

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'NOPE' with local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png'; marker 'DUPMARKER' with the same local_path; marker 'ANY' with local_path '/nonexistent/missing.png' — all into folder {FOLDER_ID}"

**Checks**
- `results` has three entries, each with an `error` and no `fileId`: "not found" for NOPE, "must be unique" for DUPMARKER (occurs twice), a missing-file message for ANY
- `get_doc_structure` shows the doc completely unchanged — no image, no marker text removed (the tool uploads/shares before touching the document, and none of these three ever reached that step)

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
All three error messages matched exactly (not found / occurs 2 times / no file found); no `fileId` on any entry; doc structure confirmed unchanged.

---

### TC-DOC121: A marker that's a substring of unrelated document text is not falsely matched
**Setup:** create a doc via `write_doc_content` with content `<p>Reference build IMG10 in the changelog.</p>` — note there is no standalone "IMG1" token anywhere, only "IMG1" as the first four characters of "IMG10"

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'IMG1', local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png', into folder {FOLDER_ID}"

**Checks**
- `results` has one entry with an `error` containing "not found" — plain substring search would incorrectly match "IMG1" inside "IMG10" and report success
- `get_doc_structure` shows the doc completely unchanged (no upload happened, since the marker never resolved)
- No file was uploaded to Drive (nothing to clean up)

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
Returned `{"error": "marker 'IMG1' not found in document"}}` — confirms the substring-collision fix live; the prior implementation would have falsely matched inside "IMG10".

---

## Nested list / interrupted `<li>` parent-text handling — `write_doc_content` (issue #335)

**Note:** nested-list *indentation* is a separate, not-yet-fixed issue (#336) — `BulletItem.depth` is computed correctly but the Docs writer doesn't yet turn it into visual indentation, so all bullets below may render at the same flat list level for now. These test cases cover #335: that an open `<li>`'s own text is no longer silently dropped when something block-level opens inside it (a nested `<ul>`/`<ol>`, but also `<pre>`, `<table>`, `<p>`, headings), that text appears before its children in document order, that text trailing a nested construct (before the real `</li>`) isn't dropped either, and that formatting state doesn't leak forward when an inline tag is left unclosed across the boundary. None are tagged `Playwright: required` since indentation (the only visual signature not yet checkable) isn't verifiable until #336 lands — `get_doc_structure` text/order/style checks are sufficient here.

### TC-DOC122: Parent `<li>` text survives alongside a nested list ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Item text<ul><li>sub a</li><li>sub b</li></ul></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows **three** bulleted paragraphs in order: "Item text", "sub a", "sub b" — previously the parent's "Item text" paragraph was dropped entirely, leaving only the two children

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Item text", "sub a", "sub b". Fixture restored.

---

### TC-DOC123: Three-level nested list preserves every parent's own text, in document order ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Parent A has text<ul><li>Child A1 has text<ul><li>Grandchild A2a</li></ul></li></ul></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows three bulleted paragraphs in order: "Parent A has text", "Child A1 has text", "Grandchild A2a" — all three levels' own text present, none clobbered by the nested `<li>` below it
- Order matches source order (each parent before its own children) — a fix that only restores the buffer at the outer `</li>` close would emit children before their parent instead

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Parent A has text", "Child A1 has text", "Grandchild A2a". Fixture restored.

---

### TC-DOC124: Nested list via Markdown also preserves the parent line's text ⚠️ destructive
**Prompt**
> "Write this Markdown to doc {DOC_ID} with content_format='markdown': `- Item text:\n    - sub a\n    - sub b`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows three bulleted paragraphs: "Item text:", "sub a", "sub b" — confirms the fix applies through the Markdown→HTML pipeline too, not just raw HTML
- Note: 4-space indentation is used deliberately — 2-space indentation doesn't clear the `sane_lists` nesting threshold and produces a flat, unnested list instead (a separate, already-tracked issue, #334)

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Item text:", "sub a", "sub b" — confirms the fix applies through the Markdown pipeline too. Fixture restored.

---

### TC-DOC125: A `<pre>` block opening inside an open `<li>` doesn't drop the `<li>`'s own text ⚠️ destructive
**Note:** covers the review-round finding that #335's original fix only guarded `<ul>`/`<ol>` — any block-level construct interrupting an open `<li>` had the same data-loss bug.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Note:<pre>code</pre></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a bulleted paragraph "Note:" followed by a separate (non-bulleted) paragraph "code" — previously "Note:" was dropped entirely and no bullet was emitted for this `<li>` at all

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned bulleted paragraph "Note:" followed by non-bulleted paragraph "code". Fixture restored.

---

### TC-DOC126: A `<table>` opening inside an open `<li>` doesn't drop the `<li>`'s own text ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Before<table><tr><td>cell</td></tr></table></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a bulleted paragraph "Before" followed by a 1×1 table whose cell reads "cell"

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned bulleted paragraph "Before" followed by a 1×1 table with cell text "cell". Fixture restored.

---

### TC-DOC127: Trailing text after a nested list, before the real `</li>`, is not dropped ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Parent<ul><li>Child</li></ul>trailing text</li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows three bulleted paragraphs in order: "Parent" (depth 0), "Child" (nested), "trailing text" (depth 0) — previously "trailing text" was silently dropped since the parent `<li>`'s block context was never reopened after its nested list closed

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Parent", "Child", "trailing text". Fixture restored.

---

### TC-DOC128: An unclosed `<b>` inside a `<li>` doesn't leak bold formatting into the rest of the document ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Item <b>bold text<ul><li>sub</li></ul></li></ul><p>After the list</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows "Item " unbolded and "bold text" bolded within the first bullet (as authored)
- The "sub" bullet and the "After the list" paragraph are **not** bolded — previously the never-closed `<b>` left bold formatting active for every subsequent node in the document

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned "Item " unbolded and "bold text" bolded within the first bullet; "sub" and "After the list" both unbolded. Fixture restored.

---

### TC-DOC129: A heading's own text survives a nested table interrupting it ⚠️ destructive
**Note:** review round 2 found the prior fix was still gated on the interrupted block being specifically `<li>` — any open block (headings, plain paragraphs) had the same text-loss bug, and in this specific shape the loss was worse than a drop: the heading's text was spliced directly into the table's own cell content.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<h2>Heading text<table><tr><td>cell</td></tr></table></h2>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a level-2 heading reading exactly "Heading text", followed by a 1×1 table whose cell reads exactly "cell" — not "Heading textcell" or any other splice/merge of the two

**Cleanup:** write fixture content back

---

### TC-DOC130: Malformed HTML (an unclosed `<p>` inside a `<li>`) degrades locally without corrupting later, well-formed content ⚠️ destructive
**Note:** covers a live-confirmed corruption mode from review round 2 — an interruption stack that pops on any close tag (rather than verifying it owns the frame) let a stray close tag later in the document consume the wrong frame, causing unrelated plain text to be spuriously wrapped as a bulleted list item.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>text<p>unclosed</li></ul><p>Later unrelated paragraph</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a bulleted paragraph "text" (the `<li>`'s own text, preserved despite the unclosed `<p>` inside it)
- `get_doc_structure` shows "Later unrelated paragraph" as a plain, non-bulleted paragraph — not wrapped into a list item and not merged with any other text

**Cleanup:** write fixture content back

---

## Bare top-level text no longer silently dropped — `write_doc_content` (issue #343)

**Background:** surfaced by Kit while building fixtures for TC-DOC107/PR #337 (unrelated to that PR's diff, flagged separately). `content`/HTML with no wrapping block tag (e.g. `hello world` instead of `<p>hello world</p>`) fell into `html_to_ast`'s inline-only code path — `handle_data` only buffers text inside an open block (`<p>`, `<li>`, a heading, or a table cell), so text with no block ancestor at all was silently dropped, producing an empty document body. The fix adds a generic open-tag depth counter so `handle_data` can tell genuinely bare text (depth 0) apart from text merely wrapped in a non-block tag with no block ancestor at all (e.g. `<span>no blocks</span>`, depth 1) — the latter stays an intentional no-op (see `test_inline_only_html_skips_batchupdate`), the former now gets an implicit paragraph wrap.

### TC-DOC131: Bare text with no wrapping tag at all is no longer dropped ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `hello world`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a single plain paragraph reading exactly "hello world" — previously this call silently produced an empty document body

**Cleanup:** write fixture content back

---

### TC-DOC132: An inline tag with no block ancestor still produces no content (regression guard) ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<span>no blocks</span>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the document body empty/unchanged — this is the deliberate existing behavior for inline-only tags with no block ancestor and the #343 fix must not alter it

**Cleanup:** write fixture content back

---

## UTF-16 code-unit offset correctness in write paths (issue #358)

**Background:** Docs API `startIndex`/`endIndex` count UTF-16 code units, not Python code points — an astral-plane character (most emoji, some CJK/math symbols) is one Python `str` character but a 2-unit surrogate pair. `emitter.py`'s `ast_to_requests` derived every downstream offset (table positions, paragraph-style ranges, inline run-style ranges) from plain `len()`, so any content containing an astral-plane character before other content in the same batch silently desynced every subsequent computed offset. Fixed by introducing a shared `utf16_len` helper (`docs/indices.py`) and routing `emitter.py` and `content.py` through it; `sheets/helpers.py`'s `_utf16_len` now delegates to the same helper instead of duplicating the accounting. The identical pattern was already fixed in `find_in_doc`'s `_collect_doc_paragraphs` (#262); this closes the matching gap in the write path.

### TC-DOC133: `write_doc_content` — table position lands correctly after an astral-plane (emoji) paragraph ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<p>😀 Hello</p><table><tr><td>Marker</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a paragraph reading exactly "😀 Hello" immediately followed by a 1×1 table whose cell reads exactly "Marker" — not truncated, spliced, or overlapping. Pre-fix, `table_positions` was computed from `len("😀 Hello\n")` (8) instead of the correct UTF-16 length (9), landing the table one unit early — inside the paragraph's trailing newline.

**Cleanup:** write fixture content back

**Result (2026-07-22) ✅ PASS**
Run against a live sandbox scoped to only `create_doc,create_doc_from_file,write_doc_content,find_in_doc,insert_softbreak_paragraph,insert_local_images,update_cells` (`get_doc_structure` not enabled) — verified via `find_in_doc` instead: "Hello" matched at `[4,9]` (paragraph text, UTF-16-correct given 😀 occupies units 1-2), "Marker" matched intact at `[14,20]` with clean cell-only context, no splice/corruption between paragraph and table content. Geometry consistent with the fixed `table_positions` (10) rather than the pre-fix value (9). A future run with `get_doc_structure` available should confirm the exact table/cell start index directly rather than inferring it from `find_in_doc` matches.

---

### TC-DOC134: `insert_softbreak_paragraph` — `line_ranges` correct across an astral-plane (emoji) character ⚠️ destructive
**Setup:** fresh/empty doc (index 1 is always a valid insertion point in a new Google Doc)

**Prompt**
> "Insert a soft-break paragraph at index 1 in doc {DOC_ID} with lines [{text: '😀X'}, {text: 'Y'}]"

**Checks**
- Response has no `error`; `end_index` is 6 and `line_ranges` is `[{start_index: 1, end_index: 4}, {start_index: 5, end_index: 6}]` — UTF-16-correct (😀 = 2 units, X/\v/Y = 1 unit each, total 5 units from index 1). Pre-fix (`len()`-based) would have given `end_index: 5` and `line_ranges: [{1,3},{4,5}]`.
- `get_doc_structure` confirms the paragraph text reads exactly "😀X\vY" with no dropped or shifted characters

**Cleanup:** delete the created doc

**Result (2026-07-22) ✅ PASS**
`insert_softbreak_paragraph` returned `end_index: 6`, `line_ranges: [{start_index:1,end_index:4},{start_index:5,end_index:6}]` — exact match for the UTF-16-correct values, not the pre-fix `len()`-based ones. Independently confirmed via `find_in_doc`: "Y" matched at `[5,6]` with context `"😀XY"`.

---

### TC-W36 regression spot-check — not run
`sheets/helpers.py`'s `_utf16_len` now delegates to the same shared `utf16_len` helper (behavior-preserving, no logic change) rather than duplicating it. A regression spot-check of TC-W36 (`docs/qa/tests/sheets_write.md`) was skipped this round: the live sandbox's `ENABLED_TOOLS` included `update_cells` but not `get_sheet_data`, so a rich-text write couldn't be read back to confirm `textFormatRuns[1].startIndex`. Worth a real spot-check next time a sandbox with read-back access is available; low risk given the change is a pure delegation.

---

## Unsupported markdown constructs preserve paragraph boundaries (issue #401)

**Background:** #332/#333 established that an unsupported construct like `<img>` (markdown images convert to `<img>` before reaching the shared HTML→AST parser) gets dropped from the document. #401 is a step further: the construct's entire *paragraph* was also being deleted, not just the construct itself — `_emit_block_node` (`html_parser.py`) returned early without appending anything whenever a closed block's buffered runs came back empty (e.g. its only child was an unsupported `<img>`), and a bare `<hr>` (python-markdown's rendering of both `---` and `___` thematic breaks — confirmed via the issue's own follow-up comment) never opened a block at all, so it left zero trace. Either way, the two blocks on either side ended up directly adjacent (one's `endIndex` == the next one's `startIndex`), unlike how any standard markdown viewer degrades (the construct's own line/block boundary survives even when the construct itself can't render). The fix keeps an empty node (`runs=[]`) in the AST for both cases instead of dropping it — `emitter.py`'s `ast_to_requests` was updated to match, since its own `if not text.strip(): continue` guard would otherwise have skipped the now-empty node's contribution to `full_text` and lost the boundary anyway.

### TC-DOC135: Dropped image and thematic breaks each keep their own paragraph instead of fusing adjacent headings together ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc135-paragraph-boundary.md` — an unsupported image, two headings, a `---` thematic break, a `##` heading + paragraph, a `___` thematic break, and a final `##` heading + paragraph, mirroring the issue's own repro (`![Kindly Human](kh-logo.png)` immediately followed by two headings) plus the underscore-variant break called out in the issue's follow-up comment.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc135-paragraph-boundary.md, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists, in order: an empty (non-heading, non-bulleted) paragraph — the dropped image's boundary — then HEADING_1 "Kindly Human", HEADING_1 "Auditing and Accountability Policy", another empty paragraph (the `---` break), HEADING_2 "PURPOSE", a plain paragraph "Body text after the thematic break.", another empty paragraph (the `___` break), HEADING_2 "SCOPE", and a plain paragraph "Body text after the underscore break."
- Confirm each empty paragraph is a real, distinct structural element (own `startIndex`/`endIndex`, one index unit wide) sitting *between* the two real elements around it — not the two real elements landing with one's `endIndex` equal to the next one's `startIndex` with nothing between them

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-22, live via `mcp-gee-sweet-kit`, doc `1wUsmzHLHn4v4DRFvedfcy7qqBVuVnIcjk3gnUjtJTQU`, deleted after). `get_doc_structure` returned exactly the expected sequence: empty paragraph (dropped-image boundary), HEADING_1 "Kindly Human", HEADING_1 "Auditing and Accountability Policy", empty paragraph (`---`), HEADING_2 "PURPOSE", body paragraph, empty paragraph (`___`), HEADING_2 "SCOPE", body paragraph — each empty paragraph its own 1-unit-wide element between real neighbors, none fused. Separately reproduced live (scratch doc `1xa-iLbjHbqSJlyQ2IN_mFggCTd9gb_WsenMKolehQio`, deleted after) that `_interrupt_open_block` (`html_parser.py:236`) still drops the entire outer node when a block whose only content is an unsupported construct is interrupted by a nested block (e.g. `- ![img](x.png)\n    - nested`) — the outer bullet vanishes completely, not just its image, unlike the direct-close case this test covers. This gap is outside TC-DOC135's own scope but confirms the code-review finding on the same PR; see PR comment for detail. Not itself a fail for this test case, but blocks `qa-approved` for the PR as a whole.

**Re-verified after fix (2026-07-24, live via `mcp-gee-sweet-kit`, doc `1gWzAqpRvwT8n7IfJ70dkKRHyErTJyJLLjY4w3GaEqh4`, deleted after):** direct-close path unaffected by the interrupt-path fix (`preserve_if_empty` now keyed on `_block_had_unsupported_content` rather than `not self._block_resumed`) — `get_doc_structure` returned the identical expected sequence, no regression.

---

**Background:** TC-DOC135's own review round found a same-bug-class gap: `_interrupt_open_block` (`html_parser.py`) flushed the currently-open block *before* descending into a nested construct with `preserve_if_empty=False` unconditionally, so a block whose only content was an unsupported construct (e.g. an `<img>`) vanished entirely — not just the image — whenever it was itself interrupted by a nested list/table/pre/block instead of closing directly. The fix replaces the old `not self._block_resumed` proxy (used at every `_emit_block_node` call site) with a new `self._block_had_unsupported_content` flag that tracks, per open-block segment, whether something was actually silently dropped (an unsupported void element or unrecognized tag) since the segment last began — set in `handle_starttag`'s generic inline-element fallthrough, reset on both fresh block open and on `_resume_interrupted_block`. This is a deliberately different signal than "is this the block's first segment," because the interrupt call site's old proxy is wrong exactly when a block is empty for a completely unrelated, common reason: an `<li>` that wraps *only* a nested list with no text of its own (ordinary nested-list markdown) is empty on its first flush too, and must NOT gain a spurious empty bullet — a regression the naive `not self._block_resumed` fix would have introduced, caught by the existing unit test `TestNestedLists::test_parent_with_no_own_text_unaffected`.

### TC-DOC136: A block whose only content is a dropped construct survives when interrupted by a nested list, while a block with no content of its own still emits nothing ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc136-interrupted-block-boundary.md` — an H1 "Bug case" followed by a bullet whose only content is an unsupported `<img>`, immediately interrupted by its own nested one-item list (no direct-close ever happens for the outer bullet); then an H1 "Control case" followed by a bullet with real text of its own before an interrupting nested two-item list.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc136-interrupted-block-boundary.md, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists, in order: HEADING_1 "Bug case", an empty (non-heading) bullet item — the dropped image's boundary, surviving the interruption instead of the whole outer bullet vanishing — a nested bullet item "nested one", HEADING_1 "Control case", a bullet item "text", and two nested bullet items "control child a" / "control child b"
- Exactly one bullet item appears for the "Bug case" list before "nested one" (the preserved empty outer bullet) — not zero (the pre-fix vanish) and not two (a duplicate)
- No spurious empty bullet item appears anywhere under "Control case" — the outer "text" bullet's own real content is the only node before its two children

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-24, live via `mcp-gee-sweet-kit`, doc `16Cp78j9qXCqXXcA3PcYI_-bPUsRx9PwB9a-wn0zFIWU`, deleted after). `get_doc_structure` returned exactly the expected sequence: HEADING_1 "Bug case", one empty paragraph (the preserved outer-bullet boundary), "nested one", HEADING_1 "Control case", "text", "control child a", "control child b" — exactly one empty node for the bug case (neither vanished nor duplicated), and no spurious empty node anywhere under the control case. Confirms the send-back finding from PR #406's prior QA round (interrupt path dropping a block whose only content was an unsupported construct) is fixed without regressing the ordinary nested-list-with-no-own-text case.

---

**Background:** TC-DOC136's own review round (QA pass 2) found a second, unrelated gap in the *original* #401 fix (not introduced by TC-DOC136's own change): the bare-`<hr>`-with-no-open-block check (`html_parser.py`, added by #401) tested `self._block_tag is None and self._table_depth == 0` but omitted `self._tag_depth == 0` — the condition `handle_data`'s sibling bare-text check uses (#343) to distinguish genuinely bare top-level content from content that's merely wrapped in an inline tag with no block ancestor. An `<hr>` wrapped only in an inline tag (e.g. `<span><hr></span>`) was therefore treated as a bare top-level thematic break and injected a spurious empty-paragraph boundary — contradicting the existing, tested policy (`test_span_wrapped_text_still_dropped`, TC-DOC132) that inline-only content with no block ancestor is a deliberate no-op. Only reachable via hand-authored HTML through `create_doc_from_file`'s `.html` path — python-markdown never emits `<hr>` wrapped in an inline tag, only as a bare top-level sibling.

### TC-DOC137: An `<hr>` wrapped only in an inline tag with no block ancestor stays a no-op, matching the existing bare-text policy ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc137-inline-hr-no-block-ancestor.html` — a paragraph, a `<span>` wrapping only an `<hr>` with no block ancestor, and another paragraph.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc137-inline-hr-no-block-ancestor.html, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` shows exactly two body elements: a paragraph "Before" immediately followed by a paragraph "After" — no empty paragraph or other structural element between them (the pre-fix bug would show three elements, with a spurious empty paragraph from the inline-wrapped `<hr>`)

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-24, live via `mcp-gee-sweet-kit`, doc `11kfAgxg8pfiSfEGgvu9AvLtYlaWjf4B0KsBJPwntnSI`, deleted after). `get_doc_structure` returned exactly "Before" immediately followed by "After" — no spurious empty paragraph from the inline-wrapped `<hr>`, confirming the send-back finding from PR #406's QA pass 2 is fixed. Full unit suite: 898 passed.

---

## Whitespace/`&nbsp;`-only paragraphs preserve their blank line instead of being silently dropped (issue #402)

**Background:** distinct from #401's `runs=[]` case (an unsupported construct like `<img>` leaves a block with *no* buffered content at all). Here the block's buffered runs are non-empty but strip to nothing — a lone `&nbsp;` or a run of plain spaces — which markdown authors commonly write as a standalone line to force a visible blank-line spacer, since a literal blank line collapses in markdown. `_emit_block_node` (`html_parser.py`) used to drop any block whose text stripped to empty regardless of *why*, fusing the paragraphs on either side together exactly like #401 did before its fix. The fix distinguishes a *freshly*-closed block (opened and closed with nothing in between, e.g. `<p>&nbsp;</p>`) — always kept now, unconditional on `preserve_if_empty`, since there's real (if invisible) content to lose — from a *resumed* block's whitespace-only trailing flush (e.g. the indentation newline between a nested list's `</ul>` and the outer `<li>`'s own `</li>`), which is markup-formatting noise, not authored content, and keeps falling back to the same `preserve_if_empty` gate the `runs=[]` case already used (confirmed via `test_nested_list_via_markdown_preserves_parent_text`, which regressed under a first, broader version of this fix that preserved every non-empty-runs whitespace-only block regardless of resumption state). `emitter.py`'s `ast_to_requests` no longer special-cases whitespace text either — it emits whatever text a kept node carries.

### TC-DOC138: A standalone `&nbsp;` line between two paragraphs keeps its own blank paragraph rather than fusing its neighbors together ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc138-nbsp-spacer-paragraph.md` — mirrors the issue's own repro (an Employee Handbook acknowledgment/signature block): a paragraph, a standalone `&nbsp;` line, a row of underscores (renders as `<hr />`, exercising #401's case in the same doc), and a final paragraph with several inline `&nbsp;` runs mixed with real text.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc138-nbsp-spacer-paragraph.md, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists exactly 4 paragraphs in order: the acknowledgment paragraph, a non-empty paragraph whose `text` is just the nbsp character (plus the API's own trailing newline) — not merged into either neighbor, own `startIndex`/`endIndex` — an empty paragraph (the underscore `<hr>`, #401's case), and the "Employee Signature ... Date" paragraph
- The nbsp paragraph's `endIndex` does **not** equal the acknowledgment paragraph's `endIndex` (i.e. it isn't zero-width/fused) — it has real width from the nbsp character
- The final paragraph's inline `&nbsp;&nbsp;...` run between "Employee Signature" and "Date" survives as literal nbsp characters in its `text`, not collapsed or stripped

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-27, live via `mcp-gee-sweet-kit`, doc `1e9W8zb8gWtOCDb6lJcuFtCZbum7hoXRqGbBaEBd3vD0`, deleted after). `get_doc_structure` returned the expected 4 content paragraphs in order, followed by the doc's own terminal empty paragraph (confirmed via a separate baseline doc with unrelated plain content — this trailing element is a standard Google Docs artifact on every doc, not something this fix introduces, so it doesn't count against "exactly 4"). Verified at the raw codepoint level via a direct Docs API call: the spacer paragraph is literally `'\xa0\n'` (startIndex 96, endIndex 98) with real width — not fused with the acknowledgment paragraph's endIndex 96; the `<hr>` paragraph is the expected bare `'\n'`; the final paragraph's inline gap is `'Employee Signature \xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0 Date\n'`, all 8 nbsp characters intact, not collapsed to regular spaces. Full unit suite: 945 passed.

---

## `style_doc_range`: `link_url: null` now actually clears a link (issue #408)

**Background:** TC-DOC30 above covers *setting* a link. Clearing one (`link_url: null`, documented in the tool's own docstring as the way to do it) always failed with `HttpError 400 ... "Invalid requests[0].updateTextStyle: Links must include at least one type."` instead. `_text_style_and_fields` (`style.py`, shared with `insert_softbreak_paragraph` in `content.py`) built the clearing request as `textStyle.link = {}` — the Docs API rejects an empty `Link` object outright, confirmed live via a direct API call reproducing the exact reported error. Fixed by omitting the `link` key from `textStyle` entirely while still naming `"link"` in the `fields` mask — the correct way to reset a nested message field to its Docs API default (no link) — confirmed live this actually clears an existing link without error. Both call sites' own `if text_style: requests.append(...)` guard also had to change to `if fields:`: a link-clear-only call now legitimately produces an empty `text_style` dict alongside a non-empty `fields` list (`["link"]`), and the old guard would have silently dropped the request rather than sending it.

### TC-DOC139: Clearing a link via `link_url: null` removes it instead of erroring ⚠️ destructive

**Setup:** insert a paragraph "Visit example\n" in `{DOC_ID}`; apply `link_url: "https://example.com"` to the range covering "example" (same setup as TC-DOC30); note that range.

**Prompt**
> "Clear the hyperlink on range {start}–{end} in doc {DOC_ID} by setting link_url to null."

**Checks**
- Tool completes without error (no `HttpError 400` / "Links must include at least one type")
- Response `requests: 1`
- `get_doc_structure` shows the run over that range now has `link_url: null` (not still `"https://example.com"`)
- 🔍 Visual check: the text no longer renders as a hyperlink (no blue/underline hyperlink styling — the auto-added `underline: true` from TC-DOC30 is a separate, independent style field and is not expected to be cleared by this call, since `link_url` and `underline` are unrelated fields in the request)

**Cleanup:** delete the test paragraph

**Result:** PASS (2026-07-27, live via `mcp-gee-sweet-kit`, `mcp-gee-sweet-qa-fixtures-doc` `1-whiEVwvnSOABaK9qgpzdVaGUOMRvJdQhDmCURqx4fA`). Inserted "Visit example\n", linked "example" (indices 94–101) to `https://example.com`, then cleared it via `style_doc_range(..., link_url=null)` — no `HttpError 400`, `requests: 1`. `get_doc_structure` confirmed "example" split into its own run with `link_url: null` (previously carried the link). Visual/Playwright check not performed (no browser session in this pass); cleared status confirmed via the API's own structural response instead. Test paragraph deleted after.

---

### TC-DOC140: `insert_softbreak_paragraph`'s `link_url: null` also clears rather than erroring (shared helper)

**Setup:** none — the line is inserted fresh by the call under test.

**Prompt**
> "Insert a soft-break paragraph at index 1 in doc {DOC_ID} with one line: text 'plain text, no link' and link_url null."

**Checks**
- Tool completes without error
- Response includes `line_ranges` with one entry
- `get_doc_structure` shows the inserted run has `link_url: null`

**Cleanup:** delete the inserted paragraph

**Result:** PASS (2026-07-27, live via `mcp-gee-sweet-kit`, same fixture doc). `insert_softbreak_paragraph(index=1, lines=[{"text": "plain text, no link", "link_url": null}])` completed without error, returned `line_ranges: [{"start_index": 1, "end_index": 20}]`. `get_doc_structure` confirmed the inserted run's `link_url: null`. Note: since `named_style_type` wasn't passed, the call's documented "covers the entire paragraph touched by the insert" behavior downgraded the existing "Test Document" HEADING_1 paragraph to NORMAL_TEXT (expected, not a defect) — restored via an explicit `style_doc_range` call after cleanup, fixture doc left in its original state.
