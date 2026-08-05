# Design: Borderless-Table Pattern for Form-Style Column Alignment (issue #473)

## Problem

Issue #404 asked for a way to set custom paragraph tab stops, to align independent lines of
text (a label on one line, a value on another) to a shared horizontal position without a
visible table — form-style layouts like signature lines or label/value pairs. That issue is
closed as infeasible: the Docs API's `ParagraphStyle.tabStops` field is documented read-only,
and no request type in the API can set it (see `decisions/` for prior tab-stop findings).

The underlying need — columnar alignment without a table's visual footprint — is still real.

## The recipe

A table gives exact column positions for free; the only missing piece is hiding its visible
structure so it reads as plain aligned text rather than a table:

1. `insert_doc_table` to create a single-row table with the needed number of columns.
2. `insert_doc_text` (using the cell indices `insert_doc_table` returns) to fill each cell.
3. `style_doc_table_cells` with `padding_top`/`padding_right`/`padding_bottom`/`padding_left: 0`
   on every cell, to remove the table's default cell padding so column content sits flush.

Content written into each cell lands at a precise, guaranteed column position — the same
alignment guarantee `tabStops` would have provided.

## Open question: suppressing the default visible border

A freshly inserted table renders visible default borders in the Docs UI even though a fresh
cell's `tableCellStyle` has no `borderTop`/`borderRight`/`borderBottom`/`borderLeft` keys at
all (confirmed via TC-DOC146's live `documents().get()` read, `docs/qa/tests/docs.md`). That
means the visible default grid isn't controlled by the absence/presence of those cell-level
fields the way you'd expect — "just don't call `style_doc_table_cells` with any `border_*`
keys" does **not** hide it, since the default is visible whether or not those keys are set.

**Unverified:** whether an explicit `border_width: 0` override (with no `border_color`, since
the API only requires a color when width is non-zero — see `style_doc_table_cells`'s
per-edge-override docstring note) on every cell actually suppresses the default rendering, as
opposed to being a no-op against whatever mechanism draws that default border. This needs a
live check via `documents().get()` plus a Playwright/visual snapshot before being treated as
confirmed — same class of check as TC-DOC146 itself. Until confirmed, treat step 4 below as a
hypothesis, not a working step:

4. *(unconfirmed)* `style_doc_table_cells` with `border_width: 0` on every cell, to suppress
   the default visible grid.

If width:0 turns out not to suppress the default border, the fallback worth testing next is an
explicit white/background-matching `border_color` at a small nonzero width, so the border still
"exists" for API purposes but is visually indistinguishable from the page background.

## Convenience wrapper (lower priority)

Once the recipe above is confirmed end-to-end, it's worth evaluating whether a small
`align_columns`-style helper — create a borderless table and fill it in one call — is worth
adding on top of the documented recipe, rather than requiring three separate tool calls every
time. Not pursued here; the documented recipe is the near-term deliverable issue #473 asked for.
