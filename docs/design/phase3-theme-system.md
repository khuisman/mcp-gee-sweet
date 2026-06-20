# Design: Phase 3 — Theme System (`get_doc_theme` / `apply_theme`)

**Date:** 2026-06-20  
**Issue:** [#88](https://github.com/khuisman/mcp-gee-sweet/issues/88)  
**Status:** complete

> Point-in-time implementation design — captures the key discovery, data model, and approach decisions. See [docs-ast-pipeline.md](docs-ast-pipeline.md) for Phase 2 context.

---

## What Phase 3 adds

1. **Emitter Phase 3 Run fields** — activates the `Run.font_size`, `Run.foreground_color`, `Run.background_color`, `Run.baseline_offset`, `Run.small_caps` AST stubs in `_run_style_requests` (previously silently ignored).

2. **Emitter Cell styling (Step 7)** — new `_build_cell_style_requests` helper; `fill_tables` now emits `updateTableCellStyle` for cells with `background_color`, `padding_*`, or `border_*` fields set.

3. **`get_doc_theme` tool** — reads `doc.namedStyles.styles` from the Docs API and returns a theme dict keyed by named style type.

4. **`apply_theme` tool** — applies a theme dict to a doc by scanning existing paragraphs and emitting `updateParagraphStyle` / `updateTextStyle` for each matching paragraph. Also handles a `"table"` key via `updateTableCellStyle`.

---

## Key API discovery: `updateNamedStyles` does not exist

The original design intended `apply_theme` to call `updateNamedStyles` in a `batchUpdate` to set the document's default named style templates (HEADING_1, NORMAL_TEXT, etc.). This would have changed the defaults for all future new paragraphs.

**This does not work.** The Google Docs batchUpdate API has no `updateNamedStyles` request type. Sending such a request returns:

```
HTTP 400 — Invalid JSON payload received. Unknown name "updateNamedStyles"
at 'requests[0]': Cannot find field.
```

The `namedStyles` field is readable from `documents.get()` but is not writable via `batchUpdate`. There is no other Docs API method that exposes named style writes.

## Chosen approach: paragraph scanning

`apply_theme` instead:

1. Fetches the full doc via `documents.get()`
2. Iterates `body.content` looking for paragraph elements
3. Reads each paragraph's `paragraphStyle.namedStyleType`
4. For any named style type that appears as a key in the theme, emits:
   - `updateParagraphStyle` — for `line_spacing`, `space_above`, `space_below`
   - `updateTextStyle` — for `font_family`, `font_size`, `bold`, `italic`, `color`
5. For the optional `"table"` key, emits `updateTableCellStyle` rows per table

**Trade-off:** This applies styles to *existing* paragraphs only — it does not change the doc's named style defaults, so new paragraphs typed after the fact will not inherit the theme. For AI-generated docs (where all content is written programmatically), this is not a meaningful limitation: `apply_theme` can be called after writing content to enforce consistent styling.

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
