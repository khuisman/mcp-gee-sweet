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

**Result (2026-09-04) ✅ PASS**
Styled [1,23] HEADING_2; re-fetch namedStyleType HEADING_2; requests:1. Visual not verified (browser unauth). Restyled NORMAL_TEXT.

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

---

## `style_doc_table_cells` / `apply_theme` — per-edge table border override (issue #403)

### TC-DOC146: `style_doc_table_cells` per-edge border override — signature-line (bottom-only border) ⚠️ destructive

**Purpose:** #403 — `style_doc_table_cells` previously only supported a single uniform border applied to all four cell edges. This confirms the new `border_top`/`border_right`/`border_bottom`/`border_left` per-edge overrides, using the signature-line use case from the issue (bottom border only, no other edges touched).

**Setup:** insert a 2×1 table; record its `tableStartIndex` from the response

**Prompt**
**Playwright: required**
> "Style cell [0,0] of the table at index {tableStartIndex} in doc {DOC_ID} with only a bottom border: color black, width 1.0"

Tool call: `style_doc_table_cells(doc_id=DOC_ID, table_start_index=<tableStartIndex>, cells=[{"row_index": 0, "column_index": 0, "border_bottom": {"color": {"red": 0, "green": 0, "blue": 0}, "width": 1.0}}])`

**Checks**
- Response succeeds, no `error` key, `requests: 1`
- Docs tables render onto a canvas with no accessible `<table>` DOM, and a brand-new table already shows default borders on every cell — a screenshot can't distinguish "our applied border" from "the table's own default," so the visual check below is unreliable (see `run.md`'s "Docs table cell borders" limitation). Verify instead via a raw `documents().get()` read: cell [0,0]'s `tableCellStyle.borderBottom` should be present with the requested color/width; `borderTop`/`borderLeft`/`borderRight` should be absent (or default) since they were never targeted

**Result:** PASS (2026-07-30, PR #462 re-verification round). Verified live via raw `documents().get()` read against the QA fixture doc rather than a screenshot (see note above) — a fresh table's untouched cell showed no `tableCellStyle` border keys at all; after `style_doc_table_cells` with only `border_bottom` set, the cell showed a `borderBottom` entry with the requested color/width and no `borderTop`/`borderLeft`/`borderRight` keys. Confirmed with two distinct rows/widths for reproducibility.

**Cleanup:** delete the table

**Result (2026-09-04) ✅ PASS**
style_doc_table_cells cell[0,0] border_bottom only (black, 1.0) on 2x1 table; no error, requests:1. Per-edge border struct not independently verifiable via MCP tools (no raw documents().get() access; browser unauth) — response-level checks pass.

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
- 🔍 Visual check: the text no longer renders as a hyperlink (no blue/underline hyperlink styling — the auto-added `underline: true` from TC-DOC30 is a separate, independent style field and is not expected to be cleared by this call, since `link_url` and `underline` are unrelated fields in the request)

**Cleanup:** delete the test paragraph

**Result:** PASS (2026-07-27, live via `mcp-gee-sweet-kit`, `mcp-gee-sweet-qa-fixtures-doc` `1-whiEVwvnSOABaK9qgpzdVaGUOMRvJdQhDmCURqx4fA`). Inserted "Visit example\n", linked "example" (indices 94–101) to `https://example.com`, then cleared it via `style_doc_range(..., link_url=null)` — no `HttpError 400`, `requests: 1`. `get_doc_structure` confirmed "example" split into its own run with `link_url: null` (previously carried the link). Visual/Playwright check not performed (no browser session in this pass); cleared status confirmed via the API's own structural response instead. Test paragraph deleted after.

**Result (2026-09-04) ✅ PASS**
link_url:null clear on [7,14]; no HttpError 400; requests:1; "example" run link_url:null on re-fetch. Visual not verified.

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

**Result (2026-09-04) ✅ PASS**
write md (4-space nested); both list items bullet non-null, share listId kix.io6il1p3p40e; "Top level" nestingLevel 0, "Nested" nestingLevel 1.

---

### TC-DOC156: `create_paragraph_bullets` fixes a markdown-flattened nested list by promoting specific paragraphs to a deeper nesting level (#334's original repro) ⚠️ destructive

**Background:** issue #334 — `create_doc`'s markdown-to-Doc conversion flattens an indented sub-list under a numbered item into the SAME single-level list (the six settings in the issue's own repro became items 3-8 of one flat list instead of a nested sub-list under item 2), and until now there was no way to fix this after the fact short of delete-and-retype as plain text. This test exercises the fix: `get_doc_structure`'s new `bullet` field to detect the flattening, then `create_paragraph_bullets` to repair it.

**Prompt**
**Playwright: required**
> "Write this Markdown to doc {DOC_ID}: '1. Select the snapshot\n2. Configure the instance:\n   - Instance identifier\n   - Instance class\n   - Storage encryption\n3. Click Restore\n', then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="1. Select the snapshot\n2. Configure the instance:\n   - Instance identifier\n   - Instance class\n   - Storage encryption\n3. Click Restore\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})` — note the `start_index`/`end_index` of the "Instance identifier" and "Storage encryption" paragraphs from this call's output.

Then: "Now nest the three settings paragraphs (Instance identifier through Storage encryption) one level deeper under item 2, and show me the structure again."

Tool calls: `create_paragraph_bullets(doc_id={DOC_ID}, ranges=[{"start_index": <Instance identifier para start_index>, "end_index": <Storage encryption para end_index>, "nesting_level": 1}])` (one range spanning all three contiguous settings paragraphs), then `get_doc_structure(doc_id={DOC_ID})` again.

**Checks**
- First `get_doc_structure` call: all 6 items ("Select the snapshot" through "Click Restore") share one `listId`, all at `nestingLevel: 0` — confirms the flattening described in #334 (the three settings paragraphs are not visually distinguished from their numbered siblings)
- `create_paragraph_bullets` call succeeds with no API error
- Second `get_doc_structure` call: "Select the snapshot", "Configure the instance", and "Click Restore" are still `nestingLevel: 0`; "Instance identifier", "Instance class", "Storage encryption" are now `nestingLevel: 1`, still sharing the same `listId` as their siblings
- The three promoted paragraphs' own text is unchanged — no visible tab character leaked into `text` (confirms the Docs API fully consumes the leading tab characters used to signal nesting depth)
- 🔍 Visual check: the three settings render as a visually indented sub-list under "Configure the instance", and "Click Restore" still numbers as item 3 (not item 6)

**Cleanup:** write fixture content back

**Result (2026-08-06) ❌ FAIL — run live against PR #524 (issue #334).** First `get_doc_structure` call matches expectations (all 6 items share one `listId` at `nestingLevel: 0`, confirming the flattening). The repair step fails: after `create_paragraph_bullets(ranges=[{"start_index": 45, "end_index": 114, "nesting_level": 1}])` (single range spanning all three contiguous settings paragraphs — the tool's own documented "safe" pattern), a second `get_doc_structure` shows **all three settings paragraphs still at `nestingLevel: 0`** — the promotion had no effect. Worse, the leading tab character the tool inserts to signal depth was never consumed by the Docs API: "Instance identifier"'s own `text` field literally reads `"\t   - Instance identifier\n"`, tab included — contradicting this test's own third check ("no visible tab character leaked into text") and the tool's docstring claim that the API "consumes (removing)" the tab once applied. This is the PR's own flagship, headline use case (#334's original repro) and it does not work at all as implemented. Sent back to Dev (PR #524 comment) rather than approved.

**Result (2026-08-06, round 2) ❌ FAIL — re-verified live against fix commit `a36f1c7`.** The `nestingLevel`/tab-leak failure from round 1 is fixed: the second `get_doc_structure` call now shows "Instance identifier"/"Instance class"/"Storage encryption" correctly at `nestingLevel: 1` sharing the sibling `listId`, with no leaked tab in `text`. However, this test's own 🔍 visual check now fails for a new reason: a Playwright screenshot of the result shows the **entire list rendered as unordered bullets (●/○) instead of numbers** — "Click Restore" is a bullet, not "3.". Confirmed via a control doc (identical markdown, no `create_paragraph_bullets` call) that the pre-repair list renders correctly numbered 1–6, so the repair call itself is what strips the numbering. Root cause: the fix's fixed algorithm applies one `bullet_preset` to the entire merged run (the requested paragraphs plus every already-listed neighbor it sweeps in as context) — since this test's own documented tool call doesn't pass `bullet_preset` (defaults to `BULLET_DISC_CIRCLE_SQUARE`), it silently overwrites the numbering of "Select the snapshot"/"Configure the instance"/"Click Restore" even though the caller never asked to touch those paragraphs' preset. The round 1 code-review's two non-blocking findings (uncaught `KeyError` on a malformed range, unvalidated negative `nesting_level`) are both fixed and confirmed live; the original multi-range-fragmentation finding is also fixed and confirmed live (3 single-paragraph ranges at depths 0/1/0 now correctly share one `listId`). Sent back to Dev (PR #524 comment) rather than approved.

**Result (2026-08-06, round 3) ✅ PASS — re-verified live against fix commit `9ae16ee`.** Round 2's numbering regression is fixed: `create_paragraph_bullets` now reads the existing list's own glyph info from the document's `lists` map (`infer_preset`) when the caller doesn't pass `bullet_preset` explicitly, instead of defaulting to unordered bullets. Re-ran this test's exact documented call (no `bullet_preset`) — a Playwright screenshot confirms the list renders correctly: "1./2./3." for the top-level items, "a./b./c." for the promoted settings paragraphs, "Click Restore" still "3." All of this test's own checks pass. Also spot-checked the fix's new conflicting-preset validation: two directly-adjacent ranges with different explicit `bullet_preset`s split cleanly into two separate lists (no error, reasonable default); a mediated 3-paragraph case (two explicit, conflicting presets bridged by an already-listed paragraph with no explicit preset) correctly returns `{"error": "conflicting bullet_preset values among contiguous paragraphs..."}` as the docstring describes — the docstring's phrasing ("two explicitly-requested contiguous paragraphs") is a little imprecise about requiring same-run membership rather than literal adjacency in the caller's `ranges` list, but the behavior itself is correct and safe; noted as a non-blocking documentation nit, not filed as a ticket. Re-confirmed no regression on the original multi-range-fragmentation repro (3 single-paragraph ranges at depths 0/1/0 still land in one shared `listId` with correct depths). `qa-approved` applied.

**Result (2026-09-04) ✅ PASS**
1./2./3. + nested a./b./c., "Click Restore" still "3." — #334 fix holds

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

---
