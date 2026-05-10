# TODO

Prioritized work queue. See [docs/roadmap.md](docs/roadmap.md) for full context and credits.

## Up next

1. **Fix A1 notation bugs** — `_parse_a1_notation` returns wrong `endRowIndex` for open-ended ranges (e.g. `B2:D`) and silently returns `{}` for empty string instead of raising. [Issue #11](https://github.com/khuisman/mcp-gee-sweet/issues/11)
2. **SQLite cache migration** — replace `/tmp/*.json` file-backed caches with SQLite; unblocks cache unit tests
3. **Cache unit tests** — after SQLite migration
4. **PyPI publish** — set up trusted publishing (OIDC) on PyPI, do a test release; CI workflow already written

## Tier 1 features

5. `clear_values` — clear cell content in a range without touching formatting
6. `delete_sheet` — delete a tab by name or sheetId
7. `delete_rows` / `delete_columns` — remove rows or columns by index range
8. `update_sheet_properties` — set tab color, freeze rows/cols, hide/show gridlines
9. Drive file ops — `rename_file`, `move_file`, `copy_file`, `delete_file`

## Tier 2 features

10. Cell formatting — `format_cells`, `update_borders`, `merge_cells` / `unmerge_cells`
11. Data validation — `add_data_validation`, `get_data_validation`
12. Row/column sizing — `resize_rows` / `resize_columns`, `hide_rows` / `hide_columns`

## Tier 3+ features

13. Conditional formatting, named/protected ranges, permissions, filters _(see roadmap for details)_

## Testing

14. **Formatting integration spike** — explore what `get_sheet_data(include_grid_data=True)` returns for formatted cells; determine fixture strategy (dedicated test sheet vs. ephemeral); assess whether API-level assertions cover formatting without a browser
15. **Integration tests** — API-level smoke tests against a dedicated test Drive folder using service account credentials; one test per tool
16. **OAuth integration tests** — verify auth fallback chain and tool behavior under user credentials; required for `create_doc`/`create_spreadsheet` in personal Drive
