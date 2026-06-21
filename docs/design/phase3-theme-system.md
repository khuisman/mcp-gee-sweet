# Design: Phase 3 — Theme System (`get_doc_theme` / `apply_theme`)

**Date:** 2026-06-20  
**Issue:** [#88](https://github.com/khuisman/mcp-gee-sweet/issues/88)  
**Status:** complete

> Point-in-time implementation design — captures the key discovery, data model, and approach decisions. See [docs-ast-pipeline.md](docs-ast-pipeline.md) for Phase 2 context.

---

## What Phase 3 adds

1. **Emitter Phase 3 Run fields** — activates the `Run.font_size`, `Run.foreground_color`, `Run.background_color`, `Run.baseline_offset`, `Run.small_caps` AST stubs in `_run_style_requests` (previously silently ignored).

2. **Emitter Cell styling (Step 7)** — new `_build_cell_style_requests` helper; `fill_tables` now emits `updateTableCellStyle` for cells with `background_color`, `padding_*`, or `border_*` fields set.

3. **`get_doc_theme` tool** — scans `body.content` paragraphs and returns a theme dict keyed by named style type, reading the first paragraph per type as representative. Text-level fields come from the first non-empty text run; paragraph-level fields come from `paragraphStyle`. Only works for docs with *explicit* per-paragraph styles (AI-generated content); returns empty for docs whose styles are purely inherited from named style defaults.

4. **`apply_theme` tool** — applies a theme dict by emitting `updateNamedStyle` requests (one per named style key) to update the document's named style definitions. An `overwrite=True` param additionally applies styles directly to all existing paragraphs via `updateParagraphStyle` / `updateTextStyle`. Also handles a `"table"` key via `updateTableCellStyle`.

---

## Key API discovery: `updateNamedStyle` (singular) works

The original implementation tried `updateNamedStyles` (plural), which returned HTTP 400 ("Unknown name"). The correct batchUpdate request type is `updateNamedStyle` (singular, camelCase). Confirmed via the Docs API discovery doc (`UpdateNamedStyleRequest` schema).

**Field mask requirements (discovered during live QA):**
- Paths are **snake_case** (`text_style.bold`, `paragraph_style.line_spacing`) — not camelCase
- `named_style_type` **must always be included** in the field mask, or the API returns HTTP 400 "Named style type is required"
- The root `named_style` prefix is implied and must not appear in the mask

`get_doc_theme` originally read from `doc.namedStyles.styles` (the document's named style template defaults). This works for standard Google Docs but returns empty for AI-generated docs, which store styles as explicit per-paragraph and per-run overrides and leave `namedStyles` at Google's blank defaults. The implementation was replaced with a body paragraph scan.

## Chosen approach: `updateNamedStyle` + optional paragraph overwrite

`apply_theme` (default mode):

1. For each named style key in the theme, emits one `updateNamedStyle` request
2. Updates the document's named style definitions — affects all future paragraphs that inherit from those named styles
3. Does **not** fetch the doc or touch existing paragraphs; existing explicit overrides are unaffected
4. For the optional `"table"` key, fetches the doc and emits `updateTableCellStyle` rows per table

`apply_theme` with `overwrite=True`:

1. Same `updateNamedStyle` requests as above
2. Additionally fetches the full doc and scans `body.content`
3. For each paragraph matching a named style key, emits `updateParagraphStyle` / `updateTextStyle`
4. This overwrites any existing per-paragraph style overrides

**Trade-off (default mode):** Named style updates affect new paragraphs but may not visually change existing content if those paragraphs have explicit overrides (the override wins). Use `overwrite=True` to force-apply to all existing paragraphs.

**Trade-off (`get_doc_theme` body scan):** Only returns data for docs where styles are stored as explicit paragraph/run overrides. For standard docs with inherited styles, returns empty. Combine with `overwrite=True` in an AI-generated-doc workflow where you know styles are explicit.

## Theme dict schema

```python
{
  # Named style type key → style entry (all fields optional)
  "HEADING_1": {
    "font_family": "Georgia",      # str
    "font_size": 20.0,             # float, points
    "bold": True,                  # bool
    "italic": False,               # bool
    "color": {"red": 0, "green": 0, "blue": 0},  # RGB 0-1
    "line_spacing": 115,           # float, 100=single
    "space_above": 12.0,           # float, points
    "space_below": 6.0,            # float, points
  },
  "NORMAL_TEXT": { ... },

  # Optional: apply default cell styling to all tables in the doc
  "table": {
    "border_color": {"red": 0, "green": 0, "blue": 0},
    "border_width": 0.5,           # float, points
    "border_dash_style": "SOLID",  # str
    "cell_padding": 3.6,           # float, points (all four sides)
    "header_background": {"red": 0.953, "green": 0.953, "blue": 0.953},  # first row only
  }
}
```

Valid named style type keys: `NORMAL_TEXT`, `HEADING_1`–`HEADING_6`, `TITLE`, `SUBTITLE`.

## Named theme management (deferred)

Storing and re-using named themes (e.g. "corporate", "report") was explicitly deferred. The current design is **inline-only**: the caller passes the theme dict directly. A future spike (#TBD) should design the storage layer, covering all server config variants (Docker volume, local process, service account without persistent filesystem, ADC).
