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

## Testing

- [x] Add `pytest` and `pytest-cov` as dev dependencies
- [x] Unit tests for cache logic — TTL expiry, dirty flag, partial invalidation for all four cache classes; uses in-memory SQLite (`:memory:`)
- [x] Unit tests for A1 notation helpers — `_parse_a1_notation`, `_column_index_to_letter`, `_letter_to_column_index`
- [x] Unit tests for HTML↔Doc conversion (`_html_to_text`, `_html_to_doc_requests`)
- [x] Unit tests for tool filtering — tools excluded when not in `ENABLED_TOOLS`
- [ ] Formatting integration spike — explore `effectiveFormat` API response shape; determine fixture strategy; assess whether API-level assertions cover formatting without a browser
- [ ] Integration tests — API-level smoke tests against a dedicated test Drive folder (service account)
- [ ] OAuth integration tests — verify auth fallback chain and tool behavior under user credentials; needed for `create_doc`/`create_spreadsheet` in personal Drive

## Infrastructure / internal

- [x] Migrate cache persistence — replaced four `/tmp/*.json` files with a single SQLite DB (`/tmp/mcp_gee_sweet.db`, configurable via `CACHE_DB_PATH`); one table, four namespaces; WAL mode
- [ ] PyPI publish — set up trusted publishing (OIDC), create package on PyPI, do a test release; CI workflow already written
- [x] Open PR to xing5 from `upstream-observability` branch (structured logging, per-tool timing, `cache_discovery=False`) — [PR #79](https://github.com/xing5/mcp-google-sheets/pull/79)
- [x] Fork repo and rename to `mcp-gee-sweet`; README credits xing5, freema, and piotr-agier

## Potential / under consideration

- **SQLite cache encryption at rest** — the cache DB (`/tmp/mcp_gee_sweet.db`) stores Google Sheets data in plaintext. For deployments that handle sensitive data, consider [SQLCipher](https://www.zetetic.net/sqlcipher/) (open-source, AES-256, mostly API-compatible with standard SQLite) or rely on filesystem-level encryption (FileVault, LUKS, BitLocker). The official SQLite Encryption Extension (SEE) is an alternative but is commercial/proprietary. Not needed for typical local-dev use.

## Inspiration and credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — original upstream this project was forked from
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) — most comprehensive Sheets-specific MCP server; primary source for formatting, validation, and sheet property roadmap items
- [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — full Workspace suite; primary source for Drive file operations, permissions, and named/protected range roadmap items
