# Feature Roadmap

Features are grouped by category and ordered by practical priority within each tier. Items marked with a source were identified by auditing competing projects — see [decision-fork.md](decision-fork.md) for full credits.

## Tier 1 — High value, frequently needed

### Sheet management
- [ ] `delete_sheet` — delete a tab by name or sheetId _(freema/mcp-gsheets)_
- [ ] `delete_rows` / `delete_columns` — remove rows or columns by index range _(freema/mcp-gsheets)_
- [ ] `clear_values` — clear cell content in a range without touching formatting _(freema/mcp-gsheets)_
- [ ] `update_sheet_properties` — set tab color, freeze rows/cols, hide/show gridlines _(freema/mcp-gsheets)_

### Drive file operations
- [ ] `move_file` — move a file to a different folder _(piotr-agier/google-drive-mcp)_
- [ ] `rename_file` — rename any Drive file _(piotr-agier/google-drive-mcp)_
- [ ] `copy_file` — duplicate a file into a folder _(piotr-agier/google-drive-mcp)_
- [ ] `delete_file` — move a file to trash _(piotr-agier/google-drive-mcp)_

## Tier 2 — Useful for structured data work

### Cell formatting
- [ ] `format_cells` — set background color, font, alignment, number format on a range _(freema/mcp-gsheets)_
- [ ] `update_borders` — set border style, width, and color on a range _(freema/mcp-gsheets)_
- [ ] `merge_cells` / `unmerge_cells` — merge a range into one cell _(freema/mcp-gsheets)_

### Data validation
- [ ] `add_data_validation` — add a dropdown list, checkbox, or value constraint to a range _(freema/mcp-gsheets)_
- [ ] `get_data_validation` — read existing validation rules from a range _(freema/mcp-gsheets)_

### Row/column sizing and visibility
- [ ] `resize_rows` / `resize_columns` — set pixel height/width, or auto-fit to content _(freema/mcp-gsheets)_
- [ ] `hide_rows` / `hide_columns` / unhide variants — toggle row or column visibility _(freema/mcp-gsheets)_

## Tier 3 — Advanced / occasionally needed

### Conditional formatting
- [ ] `add_conditional_formatting` — add a highlight or color-scale rule to a range _(freema/mcp-gsheets)_
- [ ] `delete_conditional_formatting` — remove a rule by index _(freema/mcp-gsheets)_

### Named and protected ranges
- [ ] `add_named_range` / `delete_named_range` — create or remove a named range _(piotr-agier/google-drive-mcp)_
- [ ] `add_protected_range` — lock a range against edits _(piotr-agier/google-drive-mcp)_

### Permissions
- [ ] `list_permissions` — list who has access to a file and their roles _(piotr-agier/google-drive-mcp)_
- [ ] `remove_permission` — revoke a specific user's access _(piotr-agier/google-drive-mcp)_
- [ ] `update_permission` — change a user's role (e.g. reader → writer) _(piotr-agier/google-drive-mcp)_

### Filters
- [ ] `set_basic_filter` — apply an AutoFilter to a range _(freema/mcp-gsheets)_
- [ ] `clear_basic_filter` — remove the AutoFilter from a sheet _(freema/mcp-gsheets)_

## Tier 4 — Nice to have

- [ ] `get_sheet_dimensions` — read column widths, row heights, and frozen row/col counts _(freema/mcp-gsheets)_
- [ ] `add_note` / `clear_note` — attach or remove a cell note (distinct from a comment) _(freema/mcp-gsheets)_
- [ ] `get_revisions` — list Drive revision history for a file _(piotr-agier/google-drive-mcp)_

## Infrastructure / internal

- [ ] Revisit cache persistence — all caches write JSON to `/tmp/*.json`; evaluate whether SQLite would be more appropriate as the number of cached entries grows
- [ ] Open PR to xing5 from `upstream-observability` branch (structured logging, per-tool timing, `cache_discovery=False`) before fully cutting loose
- [ ] Fork repo and rename (e.g., `mcp-google-workspace`); update README to credit xing5, freema, and piotr-agier

## Inspiration and credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — original upstream this project was forked from
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) — most comprehensive Sheets-specific MCP server; primary source for formatting, validation, and sheet property roadmap items
- [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — full Workspace suite; primary source for Drive file operations, permissions, and named/protected range roadmap items
