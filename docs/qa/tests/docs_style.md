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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa) on a throwaway doc; Playwright visual checks plus raw documents().get() reads.

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

**Result:** ⚠️ PARTIAL (2026-07-27, live via `mcp-gee-sweet-kit`, `mcp-gee-sweet-qa-fixtures-doc` `1-whiEVwvnSOABaK9qgpzdVaGUOMRvJdQhDmCURqx4fA`). Inserted "Visit example\n", linked "example" (indices 94–101) to `https://example.com`, then cleared it via `style_doc_range(..., link_url=null)` — no `HttpError 400`, `requests: 1`. `get_doc_structure` confirmed "example" split into its own run with `link_url: null` (previously carried the link). Visual/Playwright check not performed (no browser session in this pass); cleared status confirmed via the API's own structural response instead. Test paragraph deleted after.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run.

**Result (2026-09-04) ⚠️ PARTIAL**
link_url:null clear on [7,14]; no HttpError 400; requests:1; "example" run link_url:null on re-fetch. Visual not verified.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't run.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Clearing the link also cleared the auto-added underline; TC wording stale.

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

---
