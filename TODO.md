# TODO

Prioritized work queue. See [docs/roadmap.md](docs/roadmap.md) for full context and credits.

## Up next

1. ~~**Fix A1 notation bugs**~~ ✓ — fixed open-ended range `endRowIndex` and empty-string raising. [Issue #11](https://github.com/khuisman/mcp-gee-sweet/issues/11)
2. ~~**SQLite cache migration**~~ ✓ — single DB at `/tmp/mcp_gee_sweet.db`, four namespaces, WAL mode
3. ~~**Cache unit tests**~~ ✓ — 32 tests covering TTL, dirty flag, partial invalidation, all four caches
4. **PyPI publish** — set up trusted publishing (OIDC) on PyPI, do a test release; CI workflow already written

## Tier 1 features

5. `clear_values` — clear cell content in a range without touching formatting
6. `delete_sheet` — delete a tab by name or sheetId
7. `delete_rows` / `delete_columns` — remove rows or columns by index range
8. `update_sheet_properties` — set tab color, freeze rows/cols, hide/show gridlines

## Drive

Items already done: `create_folder`, `move_file`, `rename_file`, `copy_file`, `delete_file`, `search_files`, `get_file_metadata`.

9. ~~`rename_file`~~ ✓ — rename any file or folder (`files().update()` with new `name`)
10. ~~`copy_file`~~ ✓ — duplicate a file (`files().copy()`); useful for template workflows
11. ~~`trash_file` / `delete_file`~~ ✓ — `permanent=False` trashes, `permanent=True` permanently deletes
12. ~~`search_files`~~ ✓ — general Drive search across all MIME types, optional mime_type + folder_id filter
13. ~~`get_file_metadata`~~ ✓ — fetch name, MIME type, parents, modified time, size, owners, trashed status
14. `list_permissions` — who has access to a file (`permissions().list()`)
15. `update_permission` — change a user's role (`permissions().update()`)
16. `remove_permission` — revoke access (`permissions().delete()`)
17. `share_file` — generalize `share_spreadsheet` to work on any file/folder, not just spreadsheets
18. `list_drives` — enumerate shared / Team Drives (`drives().list()`)
19. ~~`export_file`~~ ✓ — download non-Google files and export Google files to PDF/DOCX/HTML (`files().export()` / `files().get_media()`)

## Docs

Items already done: `create_doc`, `get_doc_content`, `write_doc_content`.

20. `append_doc_content` — append HTML to the end of an existing doc without replacing it
21. `find_replace_in_doc` — find and replace text across a doc (`replaceAllText` Docs API request)
22. ~~`export_doc`~~ ✓ — covered by `export_file` (item 19)
23. `get_doc_structure` — return headings, paragraphs, and lists as structured data instead of a flat string
24. `rename_file` _(shared with Drive item 9)_ — rename a doc via `files().update()`
25. `insert_image_in_doc` — insert an inline image (`insertInlineImage` Docs API request)
26. Table operations — `insert_table`, `delete_table`, `update_table_cell`
27. Headers / footers — `create_header`, `create_footer`, `update_header_footer`

### Markdown → Google Doc flow

~~`upload_file`~~ ✓ — `source_format='markdown'`, `convert_to_doc=True`; converts via `markdown[extra]` → HTML → Drive HTML import. Handles headings, lists, bold/italic, tables, fenced code, links.

## Tier 2 features

28. Cell formatting — `format_cells`, `update_borders`, `merge_cells` / `unmerge_cells`
29. Data validation — `add_data_validation`, `get_data_validation`
30. Row/column sizing — `resize_rows` / `resize_columns`, `hide_rows` / `hide_columns`

## Tier 3+ features

31. Conditional formatting, named/protected ranges, permissions, filters _(see roadmap for details)_

## Testing

14. **Formatting integration spike** — explore what `get_sheet_data(include_grid_data=True)` returns for formatted cells; determine fixture strategy (dedicated test sheet vs. ephemeral); assess whether API-level assertions cover formatting without a browser
15. **Integration tests** — API-level smoke tests against a dedicated test Drive folder using service account credentials; one test per tool
16. **OAuth integration tests** — verify auth fallback chain and tool behavior under user credentials; required for `create_doc`/`create_spreadsheet` in personal Drive
