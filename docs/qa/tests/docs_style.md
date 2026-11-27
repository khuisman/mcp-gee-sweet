# Docs Tools — Style & Theming — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs/style.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` from `fixtures.local.md`.

These tools operate on document body indices. Use `get_doc_structure` first in any session to obtain current indices before calling insert/delete/style operations.

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

**Result (2026-09-04) ⚠️ PARTIAL**
Styled [1,23] HEADING_2; re-fetch namedStyleType HEADING_2; requests:1. Visual not verified (browser unauth). Restyled NORMAL_TEXT.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run (browser not signed in).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — "P12 style test" [88,103] styled HEADING_2 → `requests: 1`; re-fetch `namedStyleType: HEADING_2` with a headingId. Playwright: renders as a Heading 2 and appears in the outline (shot tc-doc12).

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

**Result (2026-09-04) ✅ PASS**
bold+italic+red on [1,23]; run bold:true italic:true; requests:1 (updateTextStyle only).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [103,116] bold+italic+red → `requests: 1`; run `bold: true, italic: true`, paragraph still NORMAL_TEXT. Playwright: "P13 bold test" renders bold italic red (shot tc-doc12).

---

### TC-DOC14: Apply both paragraph and text style in one range ⚠️ destructive
**Prompt**
> "Style range {start}–{end} in doc {DOC_ID} as HEADING_3 and bold"

**Checks**
- `requests: 2` (one updateParagraphStyle + one updateTextStyle)
- Both applied correctly on re-fetch

**Result (2026-06-20) ✅ PASS**
- Applied HEADING_3 + bold to same paragraph. `requests: 2` (one updateParagraphStyle + one updateTextStyle).

**Result (2026-09-04) ✅ PASS**
HEADING_3 + bold on [1,24]; requests:2; both applied on re-fetch.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [117,128] HEADING_3 + bold → `requests: 2`; re-fetch HEADING_3 and run `bold: true`.

---

### TC-DOC15: No recognised style fields returns error
**Prompt**
> "Call style_doc_range on doc {DOC_ID} with a range that has no style fields"

**Checks**
- Returns `{"error": "no recognised style fields in any range"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "no recognised style fields in any range"}`.

**Result (2026-09-04) ✅ PASS**
Range with no style fields -> {"error":"no recognised style fields in any range"}.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — range [117,128] with no style fields → `{"error":"no recognised style fields in any range"}`.

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

**Result (2026-09-04) ✅ PASS**
grey background visible

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — 2×2 table, row 0 background 0.953 with column_span 2 → `requests: 1`. Playwright: header row grey across both cells; raw read shows both row-0 cells backgroundColor 0.953.

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

**Result (2026-09-04) ✅ PASS**
borders visible on all 4 cells; padding not independently visible (empty cells) but no rendering issue

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — all 4 cells black 0.5pt SOLID + 3.6pt padding → `requests: 4`, no error. Raw read: every cell has all four borders at 0.5pt SOLID and 3.6pt padding (untouched tables show 5pt). Playwright: thin black borders visible.

---

### TC-DOC20: Empty cells list returns error
**Prompt**
> "Call style_doc_table_cells on doc {DOC_ID} with table_start_index {N} and an empty cells list"

**Checks**
- Returns `{"error": "cells list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "cells list is empty"}`.

**Result (2026-09-04) ✅ PASS**
Empty cells list -> {"error":"cells list is empty"}.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — `cells=[]` → `{"error":"cells list is empty"}`.

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

**Result (2026-09-04) ✅ PASS**
One styled cell + one no-style cell; requests:1 (no-style cell skipped).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [0,0] background red + [0,1] with no fields → `requests: 1`. Raw read: only [0,0] has a background; Playwright shows one red cell.

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

**Result (2026-09-04) ✅ PASS**
light blue background visible, distinct from TC-DOC18's grey

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [0,0] background 0.8/0.9/1.0 → `requests: 1`, no oneof 400. Playwright: cell [0,0] light blue, clearly distinct from TC-DOC18's grey.

---

## `get_doc_theme` / `get_doc_named_styles` / `apply_theme`

### TC-DOC75: `get_doc_named_styles` reads named style defaults set via the Docs UI
**Note:** Named styles are only populated when the user explicitly goes to Format > Paragraph styles > Update X to match. Most docs leave named styles at Google's defaults — this tool returns empty or near-empty for those docs. Use `get_doc_theme` to read actual paragraph appearance instead.

**Prompt**
> "Call `get_doc_named_styles` on doc {DOC_ID} and show me the result."

**Checks**
- No `error` key in result
- For a doc where named styles were explicitly set: returns a non-empty dict with named style type keys
- For a standard doc: may return `{}` or only Google's default entries (expected, not an error)

**Result (2026-06-20) ✅ PASS** Called on a doc that had `apply_theme` previously applied (Georgia HEADING_1/H2, Roboto NORMAL_TEXT). Returned 9 entries: NORMAL_TEXT (Roboto 11pt, line_spacing 115), HEADING_1 (Georgia 24pt bold, space_above 20), HEADING_2 (Georgia 18pt, space_above 18), HEADING_3–6 (Google defaults with font sizes and colors), TITLE, SUBTITLE. Confirms `apply_theme` default mode successfully writes to named styles, and `get_doc_named_styles` reads them back correctly. No error.

**Result (2026-09-04) ✅ PASS**
get_doc_named_styles returned Google default entries (9 keys), no error key — expected for standard doc.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Read-only on the fixture doc: returned 9 entries (NORMAL_TEXT Arial 11, HEADING_1–6, TITLE, SUBTITLE at Google defaults), no `error` key.

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

**Result (2026-09-04) ✅ PASS**
get_doc_theme on inherited-style doc returned {} — expected, no error.

**Result (2026-11-07, PR #1388 QA round 4 @ e6dabe3e, Sky) ✅ PASS** Inherited-style Markdown Doc returned `{}`, no error. After `apply_theme overwrite=True` (Georgia HEADING_1, Roboto NORMAL_TEXT) it returned both entries. The first paragraph of a style now decides, so a Doc with an unstyled first paragraph reports nothing for that style even if later ones are hand-styled.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Fixture doc (inherited styles) → `{}`, no error. On a doc after `apply_theme overwrite=True` (TC-DOC56's doc) it returned `{"HEADING_1":{"font_family":"Georgia"},"NORMAL_TEXT":{"font_family":"Verdana"}}`.

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

**Result (2026-09-04) ✅ PASS**
apply_theme HEADING_1+NORMAL_TEXT -> {docId, requests:2} = key count; no error.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc "QA-orn-D theme53" (h1 + p); theme HEADING_1 + NORMAL_TEXT → `{"docId", "requests": 2}` = key count, no error.

**Result (2026-11-10) ✅ PASS — v0.9.6 re-run, shard R4 on `kai-sa`** — On a fixture copy, the HEADING_1 + NORMAL_TEXT theme returned `requests: 2`, equal to the key count, with no error; a raw read shows NORMAL_TEXT Verdana/11 and HEADING_1 Georgia/22.

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

**Result (2026-09-04) ✅ PASS**
Georgia 22pt heading / Verdana body confirmed both visually and via toolbar readout

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc "QA-orn-D theme54": wrote `<h1>Heading One</h1><p>Normal body text.</p>`, applied the theme with overwrite=True → `requests: 5` (> 2 keys), no error. Raw read: heading run Georgia, body runs Verdana. Playwright: heading shows Georgia/22 in the toolbar; body renders in Verdana (shot tc-doc54).

**Result (2026-11-10) ✅ PASS — v0.9.6 re-run, shard R4 on `kai-sa`** — With `overwrite=True` the theme returned `requests: 5`, no error. The heading run reads Georgia and the body run Verdana; on screen the toolbar shows Georgia/22 and the body renders in Verdana.

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

**Result (2026-09-04) ✅ PASS**
grey header row, black borders, visible padding

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc with a 2-row table; table theme → `requests: 2`, no error. Raw read: all cells 0.5pt SOLID black borders and 3.6pt padding, row 0 background 0.953. Playwright: thin black borders, grey header row (shot tc-doc55).

**Result (2026-11-10) ✅ PASS — v0.9.6 re-run, shard R4 on `kai-sa`** — `requests: 2`, no error; every cell has 0.5pt solid black borders and 3.6pt padding, and the header row is grey, in the raw read and on screen. Extra #1427 check: a table-only theme kept the paragraph gaps on both sides of the table; a later `apply_theme({"NORMAL_TEXT": {"space_below": 4}})` cleared the gap below the paragraph before the table and kept the gap above the paragraph after it.

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

**Result (2026-09-04) ✅ PASS**
round-tripped Georgia/Roboto fonts render distinctly

**Result (2026-11-07, PR #1388 QA round 4 @ e6dabe3e, Sky) ✅ PASS** `get_doc_theme` returned `{"HEADING_1": {"font_family": "Georgia"}, "NORMAL_TEXT": {"font_family": "Roboto"}}`; applying it back with `overwrite=True` returned `requests > 0` and no error. Not checked on screen.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — On TC-DOC54's doc (explicit Georgia/Verdana run fonts): `get_doc_theme` → `{"HEADING_1":{"font_family":"Georgia"},"NORMAL_TEXT":{"font_family":"Verdana"}}`; applying it back with overwrite=True → `requests: 5`, no error in either.

**Result (2026-11-10) ✅ PASS — v0.9.6 re-run, shard R4 on `kai-sa`** — `get_doc_theme` returned Georgia/Verdana; applying it back with `overwrite=True` returned `requests: 5`; neither call errored.

---

## `style_doc_table_cells` / `apply_theme` — per-edge table border override (issue #403)

### TC-DOC146: `style_doc_table_cells` per-edge border override — signature-line (bottom-only border) ⚠️ destructive

**Purpose:** #403 — `style_doc_table_cells` previously only supported a single uniform border applied to all four cell edges. This confirms the new `border_top`/`border_right`/`border_bottom`/`border_left` per-edge overrides, using the signature-line use case from the issue (bottom border only, no other edges touched).

**Setup:** insert a 2×1 table; record its `tableStartIndex` from the response

**Prompt**
**Playwright: required**
> "Style cell [0,0] of the table at index {tableStartIndex} in doc {DOC_ID} with only a bottom border: color red, width 1.5"

Tool call: `style_doc_table_cells(doc_id=DOC_ID, table_start_index=<tableStartIndex>, cells=[{"row_index": 0, "column_index": 0, "border_bottom": {"color": {"red": 1, "green": 0, "blue": 0}, "width": 1.5}}])`

Use a non-default color and width. A black 1pt border equals the table's default border, so the API omits it from the cell's `tableCellStyle` and the check below can't see it.

**Checks**
- Response succeeds, no `error` key, `requests: 1`
- Docs tables render onto a canvas with no accessible `<table>` DOM, and a brand-new table already shows default borders on every cell — a screenshot can't distinguish "our applied border" from "the table's own default," so the visual check below is unreliable (see `run.md`'s "Docs table cell borders" limitation). Verify instead via a raw `documents().get()` read: cell [0,0]'s `tableCellStyle.borderBottom` should be present with the requested red color and 1.5pt width; `borderTop`/`borderLeft`/`borderRight` should be absent (or default) since they were never targeted

**Result:** PASS (2026-07-30, PR #462 re-verification round). Verified live via raw `documents().get()` read against the QA fixture doc rather than a screenshot (see note above) — a fresh table's untouched cell showed no `tableCellStyle` border keys at all; after `style_doc_table_cells` with only `border_bottom` set, the cell showed a `borderBottom` entry with the requested color/width and no `borderTop`/`borderLeft`/`borderRight` keys. Confirmed with two distinct rows/widths for reproducibility.

**Cleanup:** delete the table

**Result (2026-09-04) ⚠️ PARTIAL**
style_doc_table_cells cell[0,0] border_bottom only (black, 1.0) on 2x1 table; no error, requests:1. Per-edge border struct not independently verifiable via MCP tools (no raw documents().get() access; browser unauth) — response-level checks pass.
**Corrected (2026-10-17, #1044 audit):** the per-edge border wasn't checked by any means.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Black 1pt equals the default border, so the API omits it; verified with a non-default red 1.5pt border. TC wording stale.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — 2×1 table, [0,0] `border_bottom` red 1.5 → `requests: 1`, no error. Raw read: [0,0] has `borderBottom` red, 1.5pt SOLID, with no borderTop/Left/Right ([1,0] reports the same shared edge as its `borderTop`). Playwright: red line between the two rows.

---

### TC-DOC147: `apply_theme` table styling with per-edge border override ⚠️ destructive

**Purpose:** #403 — `apply_theme`'s `table` key had the same uniform-border-only limitation as `style_doc_table_cells`. Confirms `border_top`/`border_right`/`border_bottom`/`border_left` overrides on the theme's table styling, combined with the existing uniform `border_width` for the untouched edges.

**Prerequisite:** doc must contain at least one table (write one with `write_doc_content` first if needed)

**Prompt**
**Playwright: required**
> "Apply this theme to doc {DOC_ID}: `{"table": {"border_color": {"red": 0, "green": 0, "blue": 0}, "border_width": 0.5, "border_bottom": {"width": 2.0}}}`"

**Checks**
- Result contains `docId` and `requests > 0`
- No `error` key
- Same canvas-rendering limitation as TC-DOC146 — screenshot verification is unreliable here. Verify instead via a raw `documents().get()` read: interior rows' cells should show `borderTop`/`borderRight`/`borderBottom`/`borderLeft` all at the uniform width/color, and the *last* row's `borderBottom` should show the overridden width while still inheriting the uniform color (this is the core #403-follow-up fix: a width-only per-edge override must inherit color from the uniform spec, since the Docs API rejects a non-zero-width border with no color as "transparent")

**Result:** PASS (2026-07-30, PR #462 re-verification round). Verified live via raw `documents().get()` read: applying `{"border_color": <uniform>, "border_width": 0.5, "border_bottom": {"width": <override>}}` produced a `borderBottom` on the outer edge with the overridden width and the *uniform* color correctly inherited (confirmed unambiguously using a non-default color, since the Docs API omits zero-valued RGB components from its response — a pure-black test color would round-trip as `{}` and couldn't distinguish "inherited" from "absent"). Also confirmed `{"border_bottom": null}` returns a clean `{"error": ...}` instead of raising.

**Cleanup:** write fixture content back

**Result (2026-09-04) ✅ PASS**
apply_theme table {border_color, border_width:0.5, border_bottom:{width:2}} -> {docId, requests:3}; no error. Also verified {"border_bottom":null} -> clean {"error":...}, no raise. Raw struct read unavailable via MCP.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc with a 2×2 table; the exact theme → `requests: 2`, no error. Raw read: row 0 all edges 0.5pt; row 1 top/left/right 0.5pt and borderBottom 2pt. Black reads back as `{}`, so I repeated it with uniform color blue: every edge, including the 2pt last-row bottom, carried blue (inherited). Playwright shows the thick blue bottom edge (shot tc-doc147, blue probe state).

**Result (2026-11-10) ✅ PASS — v0.9.6 re-run, shard R4 on `kai-sa`** — `requests: 2`, no error; the last row's bottom border is 2pt and every other edge 0.5pt, inheriting the uniform colour (confirmed with a blue probe, since black reads back as `{}`).

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

**Result (2026-09-04) ✅ PASS**
strikethrough on [1,20]; requests:1; run strikethrough:true on re-fetch.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [129,144] strikethrough → `requests: 1`; run `strikethrough: true` (also visibly struck through in shot tc-doc12).

---

### TC-DOC29: Apply font_size ⚠️ destructive
**Setup:** insert a paragraph; note its range

**Prompt**
**Playwright: required**
> "Set font size to 18pt for range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- 🔍 Visual check: text is visibly larger

**Result (2026-06-20) ✅ PASS**
- Applied `font_size: 18` to [88, 104]. `requests: 1`. (Visual check only — `get_doc_structure` does not expose `font_size` from effectiveFormat.)

**Result (2026-09-04) ✅ PASS**
font_size 18 on [1,15]; requests:1; re-fetch run shows font_size:18.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [145,158] font_size 18 → `requests: 1`; run `font_size: 18`. Playwright: "P29 size test" is visibly larger than the body text (shot tc-doc12).

---

### TC-DOC30: Apply link_url ⚠️ destructive
**Setup:** insert a paragraph 'Visit example\n'; note the range covering 'example'

**Prompt**
**Playwright: required**
> "Apply link_url 'https://example.com' to range {start}–{end} in doc {DOC_ID}"

**Checks**
- Response `requests: 1`
- `get_doc_structure` shows run split at the link boundary: linked run has `link_url: "https://example.com"`, non-linked run has `link_url: null`
- 🔍 **Note:** Google Docs automatically adds `underline: true` to the linked run — expected API behaviour, not a tool bug
- 🔍 Visual check: text appears as a hyperlink

**Result (2026-06-20) ✅ PASS**
- Inserted "Visit example\n"; applied `link_url: "https://example.com"` to "example" (indices 94–101). `requests: 1`. Re-fetch: run split into "Visit " (`link_url: null`), "example" (`link_url: "https://example.com"`, `underline: true`), "\n" (`link_url: null`). Auto-underline is expected API behaviour.

**Result (2026-09-04) ✅ PASS**
link_url https://example.com on "example" [7,14]; requests:1; run split — "Visit "(null), "example"(link_url set, underline:true auto), "\n"(null).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — "example" [165,172] linked → `requests: 1`; runs split "Visit "(null) / "example"(https://example.com, underline auto-added) / "\n"(null). Playwright: blue underlined hyperlink (shot tc-doc12).

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

**Result (2026-09-04) ✅ PASS**
style [1,19] HEADING_1; requests:1; namedStyleType HEADING_1; text "Style-test heading\n" unchanged. Restyled NORMAL_TEXT + deleted.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-sa`: On the fresh doc: inserted "Style-test heading\n" at [1,20], then `style_doc_range` HEADING_1 returned `requests: 1`. `get_doc_structure`: HEADING_1 (headingId set), text unchanged. Cleanup done (restyled NORMAL_TEXT, deleted).

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — "Style-test heading" [187,206] HEADING_1 → `requests: 1`; re-fetch HEADING_1 with headingId, text unchanged.

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

**Result (2026-09-04) ✅ PASS**
style [1,17] bold+italic; requests:1; run bold:true italic:true; namedStyleType NORMAL_TEXT unchanged.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-sa`: Inserted "Bold-italic test\n" at [1,18], then `style_doc_range([1,17], bold, italic)` returned `requests: 1`. The run reads `bold: true, italic: true`, and namedStyleType stayed NORMAL_TEXT. Paragraph deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — [206,222] bold+italic → `requests: 1`; run `bold: true, italic: true`; namedStyleType stayed NORMAL_TEXT.

---

### TC-DOC230: `font_family` sets the font through `style_doc_range` and `insert_softbreak_paragraph` (#720) ⚠️ destructive
**Purpose:** the first live check of `font_family` (#720, PR #1026). Both tools build run styles through the shared `_text_style_and_fields`, so both take the field. `get_doc_structure` doesn't report a run's font, so the font box in the Docs toolbar is the check.

**Prompt**
**Playwright: required**

**Setup:** `create_doc(title="QA-TC-DOC230", folder_id={FOLDER_ID})`, then `insert_doc_text(doc_id=<it>, index=1, text="Alpha Beta Gamma\n")`. "Alpha" is [1, 6), "Beta" [7, 11), "Gamma" [12, 17).

1. `style_doc_range(doc_id=<it>, ranges=[{"start_index": 1, "end_index": 6, "font_family": "Georgia"}, {"start_index": 7, "end_index": 11, "font_family": "Courier New", "bold": true}, {"start_index": 12, "end_index": 17, "italic": true}])`
2. `insert_softbreak_paragraph(doc_id=<it>, index=18, lines=[{"text": "Line one", "font_family": "Georgia"}, {"text": "Line two"}])`

**Checks**
- Step 1 returns no `error` and `requests: 3`.
- Playwright, clicking into each word and reading the toolbar's font box: "Alpha" is Georgia; "Beta" is Courier New and bold; "Gamma" is italic in the document's default font (Arial), not Georgia or Courier New.
- `get_doc_as_markdown`: "Beta" exports as inline code (a Courier New run); "Alpha" and "Gamma" don't.
- Step 2 returns no `error`. Playwright: "Line one" is Georgia and "Line two" is the default font, and the two lines are one paragraph (no paragraph spacing between them).

**Cleanup:** `delete_file` the doc.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-sa`: Step 1 returned `requests: 3`, no error. Step 2 returned line_ranges [18,26] and [27,35], no error. Playwright, reading the toolbar after clicking into each word: Alpha=Georgia; Beta=Courier New + bold; Gamma=Arial + italic; Line one=Georgia; Line two=Arial. `get_doc_as_markdown` gives "Alpha \`Beta\` *Gamma*\n\nLine one<br>Line two", so only Beta is inline code. Structure shows "Line one\vLine two" as one paragraph [18,36]. Screenshot `2026-10-19-tc-doc230.png`. Doc trashed. Side note: `insert_softbreak_paragraph`'s docstring still doesn't list `font_family` (tracked, #1037).

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Setup as written (doc in run folder). Step 1 → `requests: 3`, no error; step 2 → line_ranges [18,26] and [27,35], no error. Playwright, mouse-clicking into each word and reading the toolbar: Alpha=Georgia; Beta=Courier New + bold; Gamma=Arial + italic; Line one=Georgia; Line two=Arial, shown on adjacent lines with no paragraph gap (shot tc-doc230). Raw read: "Line one\vLine two" is one paragraph. `get_doc_as_markdown` gives "Alpha \`Beta\` *Gamma*\n\nLine one<br>Line two", so only Beta is inline code. (Keyboard ArrowRight didn't move the Docs cursor in the shared browser; mouse clicks did.)

### TC-DOC238: `font_family` keeps the range's other text styles, and a call without it keeps the font (#720) ⚠️ destructive
**Purpose:** TC-DOC230 checks that the font lands. This case checks what a `font_family` call leaves alone: bold already on the range, the other fields in the same call, and an existing font when a later call omits `font_family`. `get_doc_structure` doesn't report a run's font, so the checks read the raw `documents().get()` `textStyle`.

**Setup:** `create_doc(title="QA-TC-DOC238", folder_id={FOLDER_ID})`, then `insert_doc_text(doc_id=<it>, insertions=[{"index": 1, "text": "Alpha Beta Gamma Delta\n"}])`. "Alpha" is [1, 6), "Beta" [7, 11), "Gamma" [12, 17), "Delta" [18, 23).

1. `style_doc_range(doc_id=<it>, ranges=[{"start_index": 7, "end_index": 11, "bold": true}, {"start_index": 18, "end_index": 23, "font_family": "Courier New"}])`
2. `style_doc_range(doc_id=<it>, ranges=[{"start_index": 1, "end_index": 6, "font_family": "Roboto Mono"}, {"start_index": 7, "end_index": 11, "font_family": "Georgia"}, {"start_index": 12, "end_index": 17, "font_family": "Georgia", "bold": true, "font_size": 18}, {"start_index": 18, "end_index": 23, "italic": true}])`

**Checks**
- Steps 1 and 2 return no `error`, with `requests: 2` and `requests: 4`.
- Raw read after step 2: "Alpha" has `weightedFontFamily.fontFamily` "Roboto Mono", and the spaces on either side have no `weightedFontFamily`.
- "Beta" is Georgia and still `bold: true`. The `font_family`-only call must not clear the bold step 1 set.
- "Gamma" has `bold: true`, `fontSize` 18pt and Georgia.
- "Delta" is `italic: true` and still Courier New.

**Cleanup:** `delete_file` the doc.

**Result (2026-10-27) ❌ FAIL — Beta loses its bold (#1273)**
Run against PR #1026's merge in an isolated service-account sandbox on a Shared Drive. Steps 1 and 2 returned `requests: 2` and `requests: 4`, no error. Raw read: Alpha `{"weightedFontFamily": {"fontFamily": "Roboto Mono", "weight": 400}}`, with plain spaces around it. Gamma `bold: true`, `fontSize` 18pt, Georgia. Delta `italic: true`, Courier New. **Beta** is `{"weightedFontFamily": {"fontFamily": "Georgia", "weight": 400}}` with no `bold`. Re-bolding Beta and then sending `font_family: "Courier New"` alone cleared it again. The request's field mask is only `weightedFontFamily`, so the Docs API clears `bold` on its own. Docs UI rendering wasn't checked here (TC-DOC230 covers the font on screen). Doc trashed.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Step 1 → `requests: 2`; step 2 → **`requests: 5`** (the case says 4). The fifth is the #1273 fix's bold-restore `updateTextStyle` on Beta (`style.py` ~L541, PR #1279), so the case's count is stale wording, not a defect. Raw read: Alpha Roboto Mono, with plain spaces on each side; Beta Georgia **and `bold: true`** (the 2026-10-27 FAIL is fixed; #1273 closed 2026-10-31); Gamma bold + 18pt + Georgia; Delta italic + Courier New.

---

## `style_doc_range`: `link_url: null` now actually clears a link (issue #408)

**Background:** TC-DOC30 above covers *setting* a link. Clearing one (`link_url: null`, documented in the tool's own docstring as the way to do it) always failed with `HttpError 400 ... "Invalid requests[0].updateTextStyle: Links must include at least one type."` instead. `_text_style_and_fields` (`style.py`, shared with `insert_softbreak_paragraph` in `editing.py`) built the clearing request as `textStyle.link = {}` — the Docs API rejects an empty `Link` object outright, confirmed live via a direct API call reproducing the exact reported error. Fixed by omitting the `link` key from `textStyle` entirely while still naming `"link"` in the `fields` mask — the correct way to reset a nested message field to its Docs API default (no link) — confirmed live this actually clears an existing link without error. Both call sites' own `if text_style: requests.append(...)` guard also had to change to `if fields:`: a link-clear-only call now legitimately produces an empty `text_style` dict alongside a non-empty `fields` list (`["link"]`), and the old guard would have silently dropped the request rather than sending it.

### TC-DOC139: Clearing a link via `link_url: null` removes it instead of erroring ⚠️ destructive

**Setup:** insert a paragraph "Visit example\n" in `{DOC_ID}`; apply `link_url: "https://example.com"` to the range covering "example" (same setup as TC-DOC30); note that range.

**Prompt**
**Playwright: required**
> "Clear the hyperlink on range {start}–{end} in doc {DOC_ID} by setting link_url to null."

**Checks**
- Tool completes without error (no `HttpError 400` / "Links must include at least one type")
- Response `requests: 1`
- `get_doc_structure` shows the run over that range now has `link_url: null` (not still `"https://example.com"`)
- 🔍 Visual check: the text no longer renders as a hyperlink (no blue/underline hyperlink styling). The request names only the `link` field, but Docs removes the underline it auto-added with the link (TC-DOC30) when the link is cleared, so `get_doc_structure` shows the run without `underline: true` as well (observed in the v0.9.2 pass)

**Cleanup:** delete the test paragraph

**Result:** ⚠️ PARTIAL (2026-07-27, live via `mcp-gee-sweet-kit`, `mcp-gee-sweet-qa-fixtures-doc` `{DOC_ID}`). Inserted "Visit example\n", linked "example" (indices 94–101) to `https://example.com`, then cleared it via `style_doc_range(..., link_url=null)` — no `HttpError 400`, `requests: 1`. `get_doc_structure` confirmed "example" split into its own run with `link_url: null` (previously carried the link). Visual/Playwright check not performed (no browser session in this pass); cleared status confirmed via the API's own structural response instead. Test paragraph deleted after.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run.

**Result (2026-09-04) ⚠️ PARTIAL**
link_url:null clear on [7,14]; no HttpError 400; requests:1; "example" run link_url:null on re-fetch. Visual not verified.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Clearing the link also cleared the auto-added underline; TC wording stale.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Second "Visit example": linked [179,186], then `link_url: null` → `requests: 1`, no HttpError. Re-fetch: "example" run `link_url: null`, `underline: null`. Playwright: second line renders as plain black text, not a link (shot tc-doc12).

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

**Result (2026-09-04) ✅ PASS**
insert_softbreak_paragraph index 1, line link_url:null; no error; line_ranges 1 entry; inserted run link_url:null.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — index 1, one line, link_url null → no error, `line_ranges: [{1,20}]`; the run's `link_url: null`. As in the 2026-07-27 note, the text joined the "Test Document" paragraph and the default NORMAL_TEXT restyled it (documented behaviour, throwaway copy).

Table cases DOC18/19/20/21/25/146 ran on one fresh doc "QA-orn-D tables" (1wN9rY...), one table per case, top-to-bottom 18, 19, 21, 25, 146; shared screenshot `shardD-2026-11-08-tc-doc18.png`, plus a raw `documents().get()` read (scratch script `tmp/D/rawget.py`, run from Aziz's worktree with its own token, read-only).

---

## Paragraph bullet inspection and repair — `get_doc_structure`'s `bullet` field, `create_paragraph_bullets`/`delete_paragraph_bullets` (issue #334)

### TC-DOC155: `get_doc_structure` surfaces `bullet.listId`/`bullet.nestingLevel` for list paragraphs ⚠️ destructive

**Setup:** none — list created fresh by the call under test.

**Prompt**
> "Write this Markdown to doc {DOC_ID}: '- Top level item\n    - Nested item\n', then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="- Top level item\n    - Nested item\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})`.

**Checks**
- Both list-item elements have a non-null `bullet` field, and both share the SAME `listId`
- "Top level item"'s `bullet.nestingLevel` is `0`
- "Nested item"'s `bullet.nestingLevel` is `1`

**Cleanup:** write fixture content back

**Result (2026-08-06) ❌ FAIL as originally written, ✅ PASS after test-case fix — run live against PR #524 (issue #334).** The prompt originally used a 2-space indent (`"- Top level item\n  - Nested item\n"`), which this codebase's `_md_to_html` (`sane_lists` extension, same as plain `python-markdown`) does not recognize as nested — both items render as a single flat `<ul>` with no nesting, so "Nested item" correctly reported `nestingLevel: 0` given that input; not a product bug, a test-case bug (`sane_lists`/`markdown` requires 4-space indent to nest a list). Fixed the prompt above to 4-space indent and re-ran: both items share one `listId`, "Top level item" is `nestingLevel: 0`, "Nested item" is `nestingLevel: 1` — PASS.
**Corrected (2026-10-17, #1044 audit):** the original FAIL was a product defect, not a test-case bug: 2-space nested Markdown should nest (TC-DOC105, TC-MD106). The PASS stands only for the rewritten 4-space prompt. Tracked in #1071.

**Result (2026-09-04) ✅ PASS**
write md (4-space nested); both list items bullet non-null, share listId kix.io6il1p3p40e; "Top level" nestingLevel 0, "Nested" nestingLevel 1.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc, `write_doc_content` with the 4-space Markdown: both items share listId `kix.m8npadf4rly`; "Top level item" nestingLevel 0, "Nested item" nestingLevel 1.

---

### TC-DOC156: `create_paragraph_bullets` repairs a flat list by promoting specific paragraphs to a deeper nesting level (#334) ⚠️ destructive

**Background:** issue #334: `create_doc`'s Markdown conversion used to flatten an indented sub-list under a numbered item into the same single-level list, and there was no way to fix that after the fact short of delete-and-retype. Since #1228 (markdown-it, plan rule D1) that sub-list nests correctly, so #334's own repro no longer produces a flat list. This case builds the flat list directly instead, writing the three settings as top-level numbered items, and exercises the repair: `get_doc_structure`'s `bullet` field to see the flat list, then `create_paragraph_bullets` to nest the settings.

**Prompt**
**Playwright: required**
> "Write this Markdown to doc {DOC_ID}: '1. Select the snapshot\n2. Configure the instance:\n3. Instance identifier\n4. Instance class\n5. Storage encryption\n6. Click Restore\n', then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="1. Select the snapshot\n2. Configure the instance:\n3. Instance identifier\n4. Instance class\n5. Storage encryption\n6. Click Restore\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})` — note the `start_index`/`end_index` of the "Instance identifier" and "Storage encryption" paragraphs from this call's output.

Then: "Now nest the three settings paragraphs (Instance identifier through Storage encryption) one level deeper under item 2, and show me the structure again."

Tool calls: `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Instance identifier para start_index>, "end_index": <Storage encryption para end_index>, "nesting_level": 1}])` (one range spanning all three contiguous settings paragraphs), then `get_doc_structure(doc_id={DOC_ID})` again.

**Checks**
- First `get_doc_structure` call: all 6 items ("Select the snapshot" through "Click Restore") share one `listId`, all at `nestingLevel: 0`: the flat list #334 describes, with the three settings numbered 3–5 like their siblings
- `create_paragraph_bullets` call succeeds with no API error
- Second `get_doc_structure` call: "Select the snapshot", "Configure the instance", and "Click Restore" are still `nestingLevel: 0`; "Instance identifier", "Instance class", "Storage encryption" are now `nestingLevel: 1`, still sharing the same `listId` as their siblings
- The three promoted paragraphs' own text is unchanged (`"Instance identifier\n"` and so on) — no tab character leaked into `text` (confirms the Docs API fully consumes the leading tab characters used to signal nesting depth)
- 🔍 Visual check: the three settings render as a visually indented `a.`/`b.`/`c.` sub-list under "Configure the instance", and "Click Restore" now numbers as item 3 (not item 6)

**Cleanup:** write fixture content back

**Result (2026-08-06) ❌ FAIL — run live against PR #524 (issue #334).** First `get_doc_structure` call matches expectations (all 6 items share one `listId` at `nestingLevel: 0`, confirming the flattening). The repair step fails: after `create_paragraph_bullets(ranges=[{"start_index": 45, "end_index": 114, "nesting_level": 1}])` (single range spanning all three contiguous settings paragraphs — the tool's own documented "safe" pattern), a second `get_doc_structure` shows **all three settings paragraphs still at `nestingLevel: 0`** — the promotion had no effect. Worse, the leading tab character the tool inserts to signal depth was never consumed by the Docs API: "Instance identifier"'s own `text` field literally reads `"\t   - Instance identifier\n"`, tab included — contradicting this test's own third check ("no visible tab character leaked into text") and the tool's docstring claim that the API "consumes (removing)" the tab once applied. This is the PR's own flagship, headline use case (#334's original repro) and it does not work at all as implemented. Sent back to Dev (PR #524 comment) rather than approved.

**Result (2026-08-06, round 2) ❌ FAIL — re-verified live against fix commit `a36f1c7`.** The `nestingLevel`/tab-leak failure from round 1 is fixed: the second `get_doc_structure` call now shows "Instance identifier"/"Instance class"/"Storage encryption" correctly at `nestingLevel: 1` sharing the sibling `listId`, with no leaked tab in `text`. However, this test's own 🔍 visual check now fails for a new reason: a Playwright screenshot of the result shows the **entire list rendered as unordered bullets (●/○) instead of numbers** — "Click Restore" is a bullet, not "3.". Confirmed via a control doc (identical markdown, no `create_paragraph_bullets` call) that the pre-repair list renders correctly numbered 1–6, so the repair call itself is what strips the numbering. Root cause: the fix's fixed algorithm applies one `bullet_preset` to the entire merged run (the requested paragraphs plus every already-listed neighbor it sweeps in as context) — since this test's own documented tool call doesn't pass `bullet_preset` (defaults to `BULLET_DISC_CIRCLE_SQUARE`), it silently overwrites the numbering of "Select the snapshot"/"Configure the instance"/"Click Restore" even though the caller never asked to touch those paragraphs' preset. The round 1 code-review's two non-blocking findings (uncaught `KeyError` on a malformed range, unvalidated negative `nesting_level`) are both fixed and confirmed live; the original multi-range-fragmentation finding is also fixed and confirmed live (3 single-paragraph ranges at depths 0/1/0 now correctly share one `listId`). Sent back to Dev (PR #524 comment) rather than approved.

**Result (2026-08-06, round 3) ✅ PASS — re-verified live against fix commit `9ae16ee`.** Round 2's numbering regression is fixed: `create_paragraph_bullets` now reads the existing list's own glyph info from the document's `lists` map (`infer_preset`) when the caller doesn't pass `bullet_preset` explicitly, instead of defaulting to unordered bullets. Re-ran this test's exact documented call (no `bullet_preset`) — a Playwright screenshot confirms the list renders correctly: "1./2./3." for the top-level items, "a./b./c." for the promoted settings paragraphs, "Click Restore" still "3." All of this test's own checks pass. Also spot-checked the fix's new conflicting-preset validation: two directly-adjacent ranges with different explicit `bullet_preset`s split cleanly into two separate lists (no error, reasonable default); a mediated 3-paragraph case (two explicit, conflicting presets bridged by an already-listed paragraph with no explicit preset) correctly returns `{"error": "conflicting bullet_preset values among contiguous paragraphs..."}` as the docstring describes — the docstring's phrasing ("two explicitly-requested contiguous paragraphs") is a little imprecise about requiring same-run membership rather than literal adjacency in the caller's `ranges` list, but the behavior itself is correct and safe; noted as a non-blocking documentation nit, not filed as a ticket. Re-confirmed no regression on the original multi-range-fragmentation repro (3 single-paragraph ranges at depths 0/1/0 still land in one shared `listId` with correct depths). `qa-approved` applied.

**Result (2026-09-04) ✅ PASS**
1./2./3. + nested a./b./c., "Click Restore" still "3." — #334 fix holds

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc. First structure: all 6 items share one listId at level 0. `create_paragraph_bullets([45,99] nesting 1)` → `requests: 6`, no error. Second structure: Select/Configure/Click Restore at 0; the three settings at 1; one shared listId; text unchanged, no tab leaked. Playwright: 1./2. with a./b./c. nested under Configure, and "Click Restore" is 3. (shot tc-doc156).

---

### TC-DOC157: `delete_paragraph_bullets` removes list membership from a range, leaving paragraph text untouched ⚠️ destructive

**Setup:** none — list created fresh by the call under test.

**Prompt**
> "Write this Markdown to doc {DOC_ID}: '- First item\n- Second item\n- Third item\n', then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="- First item\n- Second item\n- Third item\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})` — note "Second item"'s `start_index`/`end_index`.

Then: "Remove the bullet from just the second item, and show me the structure again."

Tool calls: `delete_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Second item start_index>, "end_index": <Second item end_index>}])`, then `get_doc_structure(doc_id={DOC_ID})` again.

**Checks**
- After the call: "First item" and "Third item" still have non-null `bullet` fields (unaffected)
- "Second item"'s `bullet` field is now `null`
- "Second item"'s `text` is still exactly "Second item\n" (unchanged)

**Cleanup:** write fixture content back

**Result (2026-08-06) ✅ PASS — run live against PR #524 (issue #334).** All three checks confirmed exactly as specified: "First item"/"Third item" kept their `bullet` field and shared `listId`, "Second item"'s `bullet` became `null`, and its `text` was unchanged.

**Result (2026-09-04) ✅ PASS**
3-item list; delete_paragraph_bullets "Second item" [12,24] -> requests:1; First/Third keep bullet, Second bullet:null, Second text "Second item\n" unchanged.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc. Deleting [12,24] → `requests: 1`. First/Third keep listId `kix.f9edw1oie4w`; Second `bullet: null`, text "Second item\n" unchanged.

---

### TC-DOC191: `create_paragraph_bullets` — an all-`nesting_level>=1` run renders the correct nested glyph, not the disc (#713) ⚠️ destructive

**Background:** issue #713 — `create_paragraph_bullets` (`style.py`) has the same collapse-to-`nestingLevel 0` bug that `emitter.py` had under #439 (fixed in PR #711, covered by `docs_content.md` TC-DOC190). `createParagraphBullets` assigns each covered paragraph `nestingLevel = (its leading-tab count) − (the minimum leading-tab count across the whole call's range)`, so a formed run in which every paragraph sits at `nesting_level >= 1` — no level-0 member to anchor the inference — collapsed entirely to `nestingLevel 0`: the per-level indent was bumped so it *looked* nested, but the rendered glyph was the depth-0 disc (●) instead of the depth-1 circle (○). Reachable either by passing only `nesting_level >= 1` ranges, or when the same-`listId` contiguous-neighbour expansion pulls in only paragraphs already at level >= 1. Fixed by wrapping such a run with a throwaway 0-tab anchor paragraph (`insertText "\n"` at `run_start` → `createParagraphBullets` over the range extended by 1 → `deleteContentRange` the anchor), mirroring `emitter.py`'s #439 fix — the insert (+1) and delete (−1) cancel, so positions outside the run are unaffected.

**Prompt**
**Playwright: required**
> "Write this Markdown to doc {DOC_ID}: '- Alpha\n- Beta\n- Gamma\n', then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="- Alpha\n- Beta\n- Gamma\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})` — note the `start_index` of "Alpha" and the `end_index` of "Gamma".

Then: "Now indent all three items one level deeper, and show me the structure again."

Tool calls: `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Alpha start_index>, "end_index": <Gamma end_index>, "nesting_level": 1}])` (one range covering all three items — the formed run has no level-0 member), then `get_doc_structure(doc_id={DOC_ID})` again.

**Checks**
- First `get_doc_structure`: "Alpha"/"Beta"/"Gamma" share one `listId`, all at `nestingLevel: 0`.
- `create_paragraph_bullets` call succeeds with no API error.
- Second `get_doc_structure`: all three paragraphs' `bullet.nestingLevel` is now `1` (not `0`), still sharing the same `listId`; no leaked tab or stray anchor `"\n"` in any `text` field; no extra empty list paragraph left behind.
- Precise structural confirmation (`get_doc_structure` doesn't expose the glyph): a script-driven `documents().get()` shows each of the three paragraphs with `bullet.nestingLevel == 1`, and that list's `listProperties.nestingLevels[1].glyphSymbol` is the circle (○), not `nestingLevels[0]`'s disc (●).
- 🔍 Visual check: a Playwright screenshot shows all three items rendered with the depth-1 circle glyph (○) at a single indented level — not the depth-0 disc (●).

**Result (2026-09-11) ✅ PASS** — run live against PR #723 (commit `9bd4ca1`), script-driven `documents().get()` + Playwright visual check.
First `get_doc_structure`: "Alpha"(1-7)/"Beta"(7-12)/"Gamma"(12-18) share one `listId`, all `nestingLevel: 0`. `create_paragraph_bullets(ranges=[{start_index:1, end_index:18, nesting_level:1}])` → no error, 7 requests (delete + 3 tab inserts + anchor insert + create + anchor delete — the isolated-run anchor-wrap shape). Second `get_doc_structure`: all three still share one `listId` (new list, as expected — delete+recreate always spawns a fresh one), now `nestingLevel: 1`, indices and text unchanged ("Alpha\n"/"Beta\n"/"Gamma\n", no leaked tab or stray anchor `\n`), trailing empty paragraph still `bullet: null`. Raw `documents().get()` on that `listId`: `nestingLevels[1].glyphSymbol == '○'` vs. `nestingLevels[0] == '●'` — the fix confirmed structurally, matching TC-DOC190's own `emitter.py` result. Playwright screenshot: Alpha/Beta/Gamma render the hollow-circle (○) glyph at one indented level, not the disc (●).

Note: sharing the fixture doc to the Playwright browser's own Google identity (TC-DOC190's mechanism) was blocked by the Claude Code auto-mode classifier this round; navigated directly instead once the human logged the Playwright browser into an account that already has access to the fixture — no share/revoke needed. Record which approach worked for the next run rather than assuming TC-DOC190's share-based one still does.

**Result (2026-09-12) ✅ PASS (regression check, PR #735/#727)** — PR #727 extracted this fix's insert/createParagraphBullets/deleteContentRange triple into a shared `isolated_bullet_run_wrap_requests` helper (`indices.py`), reused by both `style.py` (here) and `emitter.py`. Re-ran the tool-call steps above (not the full Playwright/glyph pass, since the underlying mechanism is unchanged from the 2026-09-11 PASS — only its call site moved): `create_paragraph_bullets(ranges=[{start_index:1, end_index:18, nesting_level:1}])` → no error, 7 requests. Second `get_doc_structure`: all three share one new `listId`, `nestingLevel: 1`, text/indices unchanged, no leaked tab or anchor artifact, trailing paragraph still `bullet: null` — confirms the extraction is behavior-preserving. `tests/test_docs_indices.py`/`tests/test_docs_style.py` (79 tests) pass. Fixture restored to baseline.

**Result (2026-09-12) ✅ PASS (re-verification, fix `31d5dd2`, PR #735)** — Ash's fix drops the redundant `min_nesting` seed, computing it once via `min(u["nesting_level"] for u in run)`. Re-ran the tool-call steps: `create_paragraph_bullets` → 7 requests, no error; second `get_doc_structure` shows all three items sharing one new `listId`, `nestingLevel: 1`, text/indices unchanged, no leaked artifacts — identical outcome to the pre-fix run. `tests/test_docs_style.py`/`tests/test_docs_indices.py` (79 tests) pass. Fixture restored.

**Cleanup:** write fixture content back to the documented baseline (`docs/qa/setup.md`), NOT the Alpha/Beta/Gamma test content used above — an earlier version of this line told the next run to restore Alpha/Beta/Gamma itself, which would have permanently overwritten the real fixture baseline: `write_doc_content(doc_id={DOC_ID}, content='<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>')`.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc. Alpha/Beta/Gamma started on one listId at level 0. `create_paragraph_bullets([1,18] nesting 1)` → `requests: 8`, no error (one more than the 7 recorded earlier, consistent with #1069's indent reset). After: all three on one new listId at nestingLevel 1, text/indices unchanged, no anchor left behind, trailing paragraph `bullet: null`. Raw read: nestingLevels[1] glyph ○ vs [0] ●, and indents 72/54. Playwright: three ○ items at one indented level (shot tc-doc191).

---

### TC-DOC234: `create_paragraph_bullets` sets `nesting_level` absolutely on already-listed paragraphs (#1069) ⚠️ destructive

**Background:** issue #1069. `deleteParagraphBullets` leaves a level-N item indented 36pt × N, and `createParagraphBullets` counts that leftover indent as depth on top of the tabs the tool inserts. So on a paragraph that was already a list item, the tool added the requested level to the current one: re-running the same 0/1/2 call gave 0/2/4, and a call naming one paragraph moved its untouched expanded neighbours too. Fixed by zeroing `indentStart`/`indentFirstLine` over each run after its `deleteParagraphBullets` and before the tab inserts, so the tabs alone set the level.

**Prompt**
> "Write three plain paragraphs Alpha, Beta, Gamma to doc {DOC_ID}, then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="Alpha\n\nBeta\n\nGamma\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})`. Note each paragraph's `start_index`/`end_index`.

Then: "Make them a numbered list at levels 0, 1 and 2."

Tool calls: `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Alpha start>, "end_index": <Alpha end>, "nesting_level": 0, "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN"}, {"start_index": <Beta start>, "end_index": <Beta end>, "nesting_level": 1, "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN"}, {"start_index": <Gamma start>, "end_index": <Gamma end>, "nesting_level": 2, "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN"}])`, then `get_doc_structure(doc_id={DOC_ID})`.

Then: "Run exactly the same call again." Repeat the same `create_paragraph_bullets` call with the indices from the latest `get_doc_structure`, then `get_doc_structure(doc_id={DOC_ID})`.

Then: "Set only Beta to level 1." Tool calls: `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Beta start>, "end_index": <Beta end>, "nesting_level": 1}])`, then `get_doc_structure(doc_id={DOC_ID})`.

Then: "Flatten Gamma to level 1, then put it back at level 2." Tool calls: `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Gamma start>, "end_index": <Gamma end>, "nesting_level": 1}])`, `get_doc_structure(doc_id={DOC_ID})`, `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Gamma start>, "end_index": <Gamma end>, "nesting_level": 2}])`, `get_doc_structure(doc_id={DOC_ID})`.

**Checks**
- After the first bullet call: Alpha/Beta/Gamma share one `listId` at `nestingLevel` 0/1/2.
- After the repeated call: still 0/1/2, not 0/2/4.
- After the Beta-only call: still 0/1/2; Gamma, pulled in as a neighbour, keeps level 2.
- After flattening Gamma: 0/1/1. After putting it back: 0/1/2, not 3.
- Every `create_paragraph_bullets` call returns no error, and after each one all three paragraphs share one `listId`, with no leaked tab in any `text` field and no extra empty paragraph.

**Cleanup:** write fixture content back to the documented baseline (`docs/qa/setup.md`): `write_doc_content(doc_id={DOC_ID}, content='<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>')`.

**Result (2026-10-24) ✅ PASS (PR #1216 round 1, head `5de64c4`, Sky)** — Run on a throwaway doc (created via `create_doc`, trashed afterward) instead of the shared fixture, so no fixture cleanup was needed. All steps as written: the first numbered call gave 0/1/2 on one `listId`; the repeated call gave 0/1/2 (not 0/2/4); the Beta-only call gave 0/1/2 with Gamma kept at 2; flattening Gamma gave 0/1/1, and putting it back gave 0/1/2 (not 3). Every call returned 5 requests and no error. No tab leaked into any `text`, and no paragraph was added: the trailing empty paragraph came from the markdown write and was there before the first call. Extra probes: (a) an emitter-written 0/1/2 list (`- pa` / 4-space `- pb` / 8-space `- pc`), re-bulleting only `pb` at level 1, gave 0/1/2, and a raw `documents().get()` showed the preset indents 36/18, 72/54, 108/90, so the explicit 0pt reset doesn't survive the bullet. (b) `delete_paragraph_bullets` over the three left `pa` with no indent and `pb`/`pc` at 36/36 and 72/72, as the new docstring says. Then `create_paragraph_bullets` on `pb`@1 + `pc`@2 (the #713 anchor path, starting from leftover indent) gave 1/2, with the anchor removed (7 requests), and the same result again on a repeat. (c) A quoted list item (72/54 + `borderLeft`) came out at 36/18 with the border kept; that's the pre-existing #1090, not this PR. `get_doc_as_markdown` still printed the `>`. Note for the next run: this markdown parser needs 4-space list nesting, and a 2-space nested item is written flat at level 0, quoted or not.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard D on `mcp-gee-sweet-ash`** — Throwaway doc. First numbered call → 0/1/2 on one listId; the repeat stays 0/1/2 (indents 36/72/108, not doubled); Beta-only → 0/1/2 with Gamma kept at 2; flattening Gamma → 0/1/1, back to 2 → 0/1/2. Every call returned `requests: 5` and no error, with one shared listId each time, no leaked tab and no extra paragraph. Intermediate states read through a raw `documents().get()`, the last two through `get_doc_structure`.

---
Cleanup: run folder QA-orn-D-2026-11-08 trashed (not permanent), along with every doc in it. No case failed, so nothing was kept. The fixture doc was only read. Totals: 31 PASS, 0 FAIL, 0 PARTIAL, 0 SKIP.

---

## `get_doc_theme(source=)` (#1527)

### TC-DOC264: `get_doc_theme` reads the body, the named styles, or both ⚠️ destructive

**Purpose:** `get_doc_named_styles` folds into `get_doc_theme(source="named_styles")`; `source="both"` returns the two side by side. `get_doc_theme` is now marked read-only.

**Steps**
1. `create_doc(title="TC-DOC264", folder_id={FOLDER_ID}, content_format="markdown", content="# Heading\n\nBody text\n")` → `{DOC}`
2. `apply_theme(doc_id={DOC}, theme={"HEADING_1": {"font_family": "Georgia"}})` (named styles only, so the body's heading keeps its own style)
3. `get_doc_theme(doc_id={DOC})`, `get_doc_theme(doc_id={DOC}, source="named_styles")`, `get_doc_theme(doc_id={DOC}, source="both")`, and `get_doc_named_styles(doc_id={DOC})`
4. `get_doc_theme(doc_id={DOC}, source="theme")`
5. In the client's tool list, read `get_doc_theme`'s annotations and `get_doc_named_styles`' description

**Checks**
- Step 3: the default call returns the same dict as `source="body"` would (keyed by named style type, no `body`/`named_styles` keys). `source="named_styles"` returns exactly what `get_doc_named_styles` returns, with `HEADING_1.font_family` `Georgia`. `source="both"` is `{"body": <the default call's dict>, "named_styles": <the named_styles call's dict>}`
- Step 4: the call is refused with an input validation error naming `source` (`Input should be 'body', 'named_styles' or 'both'`): `source` is a `Literal`, so the MCP argument check rejects it before the tool's own check runs
- Step 5: `get_doc_theme` has `readOnlyHint: true`; `get_doc_named_styles`' description starts with `Deprecated: use` and names `get_doc_theme` with `source='named_styles'`

**Cleanup:** `delete_file` the doc

**Result (2026-11-19) ✅ PASS — Kit, PR #1548 round 1 @ 1f5fd10b**
`mcp-gee-sweet-kit`, reconnected after the reset. Step 2: `{requests: 1}`. Step 3: the default call returned `{}` (the Markdown write sets no explicit body styles), and `source="both"` returned `{"body": {}, "named_styles": …}`; `source="named_styles"` and `get_doc_named_styles` returned identical dicts with `HEADING_1.font_family` `Georgia`. Step 4: refused with `Input should be 'body', 'named_styles' or 'both'` from the argument check (check corrected this round: it expected the tool's own `{"error"}`, which a `Literal` parameter never reaches). Step 5: `readOnlyHint=True` on `get_doc_theme`'s decorator; `get_doc_named_styles`' description starts `Deprecated: use \`get_doc_theme\` with \`source='named_styles'\``. Doc trashed.

---

## Paragraph spacing after a doc's final table (#1439)

### TC-DOC274: `insert_doc_text` after a final table doesn't overprint it, and `style_doc_range` sets and clears paragraph spacing ⚠️ destructive

**Purpose:** a doc written from content that ends in a table has its last, empty paragraph collapsed to 1% line spacing (#1100). Text `insert_doc_text` writes there gets the doc's normal spacing back, so it no longer overprints the table, while the collapsed blank paragraph before the table stays collapsed. `style_doc_range` takes `line_spacing`, `space_above` and `space_below`, and `null` clears each one.

`get_doc_structure` doesn't report paragraph spacing. Read each paragraph's `paragraphStyle` (`lineSpacing`, `spaceAbove`, `spaceBelow`) from a fresh-interpreter `documents().get()`, as `CLAUDE.md`'s "MCP restart" section describes. The API omits a zero `magnitude`, so `{"unit": "PT"}` is 0pt.

**Playwright: required** (step 4: the inserted lines sit clear of the table's last row in the editor, as well as in the PDF)

**Steps**
1. `create_doc(title="TC-DOC274", folder_id={FOLDER_ID}, content_format="markdown", content="Intro **bold** text\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")` → `{DOC}`
2. `get_doc_structure(doc_id={DOC})`: note the last paragraph's `startIndex` as `{END}` (the empty paragraph after the table)
3. `insert_doc_text(doc_id={DOC}, insertions=[{"index": {END}, "text": "After 🙂 one\nAfter two"}, {"index": 1, "text": "Lead "}])`
4. Read the paragraph styles; `download_file(file_id={DOC}, local_path=<scratch dir>, export_format="pdf")` and open the PDF
5. `insert_doc_text(doc_id={DOC}, insertions=[{"index": <last paragraph's endIndex − 1>, "text": " more"}])`
6. `get_doc_structure`, then `style_doc_range(doc_id={DOC}, ranges=[{"start_index": <Intro paragraph's start>, "end_index": <its end − 1>, "line_spacing": 150, "space_above": 0, "space_below": 12}])`; read the paragraph styles and the Intro paragraph's text runs
7. Same range: `style_doc_range(..., ranges=[{..., "named_style_type": "HEADING_2", "line_spacing": 200, "space_below": 3}])`; read the paragraph styles
8. Same range: `style_doc_range(..., ranges=[{..., "line_spacing": null, "space_above": null, "space_below": null}])`; read the paragraph styles
9. Same range: `style_doc_range(..., ranges=[{..., "line_spacing": 0}])`, then `style_doc_range(..., ranges=[{..., "space_above": -1}])`

**Checks**
- Step 2: the paragraph after the table, and the empty one before it, have `lineSpacing` 1 and 0pt above and below
- Step 3: the result is `{"docId": {DOC}, "insertions": 2, "trailingParagraphReset": true}`
- Step 4: "After 🙂 one" and "After two" are two paragraphs after the table with no `lineSpacing`, `spaceAbove` or `spaceBelow` of their own. The empty paragraph before the table still has `lineSpacing` 1. "Lead " starts the first paragraph. In the PDF, both lines sit below the table on their own lines, overlapping neither the table nor each other
- Step 5: the result has no `trailingParagraphReset` key (that paragraph is no longer collapsed)
- Step 6: the result is `{"requests": 1}`; the Intro paragraph has `lineSpacing` 150, 0pt above and `spaceBelow` 12, and "bold" is still bold
- Step 7: the result is `{"requests": 1}`; the paragraph is `HEADING_2` with `lineSpacing` 200 and `spaceBelow` 3
- Step 8: the paragraph has no `lineSpacing`, `spaceAbove` or `spaceBelow` of its own and is still `HEADING_2`
- Step 9: both are refused with `{"error"}` before any write: `ranges[0]: line_spacing must be greater than zero, got 0` and `ranges[0]: space_above must be zero or more, got -1`

**Cleanup:** `delete_file` the doc and the scratch PDF

**Result (2026-11-26) ✅ PASS — Sky, PR #1631 round 1 @ 7e85ab8e**
`mcp-gee-sweet-sky`, reconnected after the reset; doc created in the server's default Shared Drive folder. Step 2: `{END}` = 34; the paragraph after the table (34–35) and the empty one before it (17–18) both had `lineSpacing` 1 and `{"unit": "PT"}` above and below. Step 3: `{"docId", "insertions": 2, "trailingParagraphReset": true}`. Step 4: "After 🙂 one" (39–52) and "After two" (52–62) had an empty `paragraphStyle` spacing; 22–23 kept `lineSpacing` 1; "Lead Intro bold text" was the first paragraph. The PDF and the editor (Playwright, URL-verified, title "TC-DOC274") both show the two lines below the table on their own lines, with no overlap. Step 5: `{"insertions": 1}` with no `trailingParagraphReset`. Step 6: `{requests: 1}`; `lineSpacing` 150, `spaceAbove` 0pt, `spaceBelow` 12pt, "bold" still bold. Step 7: `HEADING_2`, `lineSpacing` 200, `spaceBelow` 3pt (step 6's `spaceAbove` was cleared, as the docstring says). Step 8: `HEADING_2` with no spacing of its own. Step 9: both refused with the exact messages. Extra probes, both failed and sent back: (a) two lines raw-inserted after the table (as Enter in the editor makes them), then `insert_doc_text` into the second, got no reset; the text kept `lineSpacing` 1. (b) `insert_doc_text` at the collapsed paragraph with `segment_id: ""` landed in the body with no reset and `lineSpacing` 1.

### TC-DOC275: The reset covers several collapsed paragraphs after the table, an empty `segment_id`, and refuses NaN (PR #1631 QA round 1) ⚠️ destructive

**Purpose:** text added after a final table with a `"\n"` before #1439 (or by Enter in the editor) leaves several paragraphs, each with the collapse, and an insert into any of them resets them all. An empty or null `segment_id` is the body, as Docs reads it. A non-finite spacing value gets the tool's own error, not Google's 400.

Read paragraph styles as in TC-DOC274.

**Steps**
1. `create_doc(title="TC-DOC275", folder_id={FOLDER_ID}, content_format="markdown", content="Intro text\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")` → `{DOC}`; `get_doc_structure`: the last paragraph's `startIndex` is `{END}`
2. From a fresh interpreter, one raw `batchUpdate` with `insertText` of `"old one\nold two"` at `{END}` (this reproduces a pre-#1439 insert); read the paragraph styles
3. `get_doc_structure`; `insert_doc_text(doc_id={DOC}, insertions=[{"index": <"old two" paragraph's endIndex − 1>, "text": " more"}])`; read the paragraph styles
4. `create_doc` a second doc `{DOC2}` from the same content; `insert_doc_text(doc_id={DOC2}, insertions=[{"index": <its {END}>, "text": "tail", "segment_id": ""}])`; read the paragraph styles
5. `style_doc_range(doc_id={DOC}, ranges=[{"start_index": 1, "end_index": 3, "font_family": "Georgia"}, {"start_index": 1, "end_index": 3, "line_spacing": NaN}])`, sending NaN as the JSON token if the client allows it, else as `float("nan")` from a fresh interpreter calling the tool function

**Checks**
- Step 2: "old one" and "old two" both have `lineSpacing` 1
- Step 3: the result has `trailingParagraphReset: true`; "old one" and "old two more" have no `lineSpacing`, `spaceAbove` or `spaceBelow` of their own; the empty paragraph before the table still has `lineSpacing` 1. In the editor neither line overlaps the table or the other
- Step 4: the result has `trailingParagraphReset: true`; "tail" is in the body after the table with no `lineSpacing` of its own
- Step 5: `{"error": "ranges[1]: line_spacing must be a number or null, got nan"}`, and no write landed

**Playwright: required** (step 3: the lines sit clear of the table and of each other)

**Cleanup:** `delete_file` both docs

**Result (2026-11-26) ✅ PASS — Sky, PR #1631 round 2 @ 6701d30f**
`mcp-gee-sweet-sky`, reconnected after the reset. Step 1: `{END}` = 29. Step 2: "old one" (29–37) and "old two" (37–45) both `lineSpacing` 1 with 0pt above and below. Step 3: `{"insertions": 1, "trailingParagraphReset": true}`; "old one" and "old two more" have no spacing of their own, and the empty paragraph before the table (12–13) kept `lineSpacing` 1. Editor (Playwright, URL-verified, title "TC-DOC275"): both lines sit below the table on their own lines, no overlap. Step 4: `{"insertions": 1, "trailingParagraphReset": true}`; "tail" (29–34) in the body with no spacing of its own. Step 5: run from a fresh interpreter calling the registered `style_doc_range` with a docs service that raises on any attribute access: NaN gave `{"error": "ranges[1]: line_spacing must be a number or null, got nan"}` and inf `... got inf`, with no API touched, so the check now runs before the `font_family` bold-restore read. Also re-ran TC-DOC274 step 3 on a fresh doc against the `targetRevisionId` change: same result as round 1 (`trailingParagraphReset: true`, both lines with no spacing of their own, "Lead " in the first paragraph).

---

## `get_doc_theme` after a doc's final table (#1440)

### TC-DOC276: `get_doc_theme` doesn't read collapsed text after a final table as the body style ⚠️ destructive

**Purpose:** text added after a final table in the Docs editor keeps the collapse #1100 leaves there (`lineSpacing` 1, 0pt above and below). In a doc whose only body text before the table is a heading, `get_doc_theme` read that text as NORMAL_TEXT and reported `line_spacing: 1`, which `apply_theme` would set on every body paragraph, so their lines overprint. It's now a block: its font is still read, but not its line spacing or spacing.

`insert_doc_text` resets the collapse on what it writes (#1439), so step 2 adds the text with a raw `insertText` from a fresh interpreter, as typing in the editor does. Read paragraph styles as in TC-DOC274.

**Steps**
1. `create_doc(title="TC-DOC276", folder_id={FOLDER_ID}, content_format="markdown", content="# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")` → `{DOC}`; `get_doc_structure`: the last paragraph's `startIndex` is `{END}`
2. From a fresh interpreter, one raw `batchUpdate` with `insertText` of `"added later"` at `{END}`; read the last paragraph's style
3. `get_doc_theme(doc_id={DOC})`
4. `style_doc_range(doc_id={DOC}, ranges=[{"start_index": {END}, "end_index": <{END} + 11>, "font_family": "Georgia"}])`, then `get_doc_theme(doc_id={DOC})`

**Checks**
- Step 2: "added later" has `lineSpacing` 1 and 0pt above and below
- Step 3: the result has no `NORMAL_TEXT` key and no `line_spacing` of 1 anywhere (before #1440: `{"NORMAL_TEXT": {"line_spacing": 1}}`)
- Step 4: `NORMAL_TEXT` is exactly `{"font_family": "Georgia"}`: the font of the doc's only body text, with no `line_spacing`, `space_above` or `space_below`

**Cleanup:** `delete_file` the doc

**Result (2026-11-27) ✅ PASS — Kit, PR #1647 round 1 @ 73fad873**
`mcp-gee-sweet-kit`, reconnected after the reset. Step 1: `{END}` = 24; the empty paragraph before the table (7–8) is collapsed (`lineSpacing` 1, 0pt above and below). Step 2: "added later" (24–36) has `lineSpacing` 1 with 0pt above and below. Step 3: `{}`, no `NORMAL_TEXT` and no `line_spacing` anywhere. Step 4: `{"NORMAL_TEXT": {"font_family": "Georgia"}}`. Extra probe, not part of the case: `apply_theme(theme={"NORMAL_TEXT": {"line_spacing": 115, "space_below": 6}}, overwrite=True)` then gave the collapsed empty paragraph before the table `lineSpacing` 115 and 6pt below (send-back on the PR).

---
