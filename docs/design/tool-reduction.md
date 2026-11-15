# Tool Reduction

**Date:** 2026-11-14
**Snapshot commit:** [`7c887e29`](https://github.com/khuisman/mcp-gee-sweet/commit/7c887e29)
**Issue:** [#1514](https://github.com/khuisman/mcp-gee-sweet/issues/1514)
**Status:** proposed. Nothing here is implemented, and no implementation ticket is filed until the maintainer approves the candidate list.

> A point-in-time design. Counts are as of the snapshot commit, under `ENABLED_TOOLS=all`. The approaches already ruled out (dynamic disclosure, an executor tool, a groups setting, composites the client can chain) are recorded in [`decision-tool-surface.md`](../decisions/decision-tool-surface.md) and aren't reopened here.

## Summary

Tool groups (#1364) cut what a client sees by default. This proposal cuts the total, by merging sibling tools that do one operation along different axes, and removing tools that a more general tool already covers.

| | Tools | Change |
|---|---|---|
| Today | 143 | |
| After tier A (merges with no loss) | 128 | −15, two of them already planned |
| After tier B (removals with a behavior difference to settle) | 122 | −6 |
| After tier C (maintainer call: a discoverability cost) | 117 | −5 |

`default` loses one tool (`get_sheet_formulas`, folded into `get_sheet_data`), so it drops to 39 once PR #1510 lands. `search_files`, already in `default`, gains what five Drive listing tools do today, so `default` clients can do more, not less.

One planned addition pulls the other way: the comments CRUD in #664 adds eight tools as specified. A six-tool shape for the whole comments surface is proposed below; it conflicts with a decided table, so it's the maintainer's call.

## The rule

Two tools become one tool with a parameter when all of these hold:

1. **Same operation, different axis.** They call the same API request, or the same one with a different enum value (`ROWS`/`COLUMNS`, `hidden: true/false`, a render option). Two operations that only share a noun stay separate.
2. **Same annotations.** Both are read-only, or both are writes with the same `destructiveHint`. A merge that would put a read and a write in one tool would mislabel one of them (ChatGPT drops a write on read-only plans, #1358).
3. **Same permission decision.** A user would allow or deny both together. Claude Code permission rules and other clients' approvals work by tool name, so an operation a user might want to allow while denying its sibling stays a separate tool: add vs delete, delete vs restore, share vs transfer ownership. This is the rule that keeps most pairs below.
4. **No union in the schema.** The merged input doesn't need mutually exclusive parameters, and the output keeps one shape. A merge that needs `oneOf`/`anyOf` at the root also breaks clients (#1342).
5. **Still findable.** The merged tool's name still contains the words a model searches for. `hide_rows_or_columns` is found by "hide rows"; folding `freeze` into `update_sheet_properties` is not, which is why that one is tier C.
6. **Local-file access is its own boundary.** A tool that reads or writes local files stays separate from its remote twin, so `LOCAL_FILE_ACCESS=off` can drop it and keep the other (#796).

A tool is removed outright when another tool already does the same thing with a parameter, which `docs/design.md`'s inclusion test already forbids ("Convenience aliases").

## Tier A: merges with no loss

| Today | After | Notes |
|---|---|---|
| `add_rows`, `add_columns` | `add_rows_or_columns(dimension, count, start)` | Same `insertDimension` request. |
| `delete_rows`, `delete_columns` | `delete_rows_or_columns(dimension, start, end)` | Same `deleteDimension`. Stays separate from add (rule 3). |
| `resize_rows`, `resize_columns` | `resize_rows_or_columns(dimension, start, end, pixel_size, auto_resize)` | Same `updateDimensionProperties`/`autoResizeDimensions`. |
| `hide_rows`, `unhide_rows`, `hide_columns`, `unhide_columns` | `hide_rows_or_columns(dimension, start, end, hidden=True)` | Same `updateDimensionProperties` on `hiddenByUser`. Hiding is reversible, so one permission decision covers both directions. |
| `insert_table_row`, `insert_table_column` | `insert_table_row_or_column(dimension, table_start_index, index, after)` | `after` replaces `insert_below`/`insert_right`. |
| `delete_table_row`, `delete_table_column` | `delete_table_row_or_column(dimension, table_start_index, index)` | |
| `star_file`, `unstar_file` | `star_file(file_id, starred=True)` | Not breaking for `star_file`. |
| `create_header`, `create_footer` | `create_header_or_footer(kind, type, content)` | Identical parameters apart from the name of the type field. |
| `get_doc_theme`, `get_doc_named_styles` | `get_doc_theme(doc_id, source="body")`, with `source` one of `body`, `named_styles`, `both` | Same input and the same theme-dict output; `get_doc_theme`'s docstring already tells the model to call both and compare, which `both` does in one call. Lands with #1358's `readOnlyHint` for it. |
| `get_sheet_data`, `get_sheet_formulas` | `get_sheet_data(..., value_render="formatted")`, with `value_render` one of `formatted`, `unformatted`, `formula` | `get_sheet_formulas` is `values().get(valueRenderOption="FORMULA")`. It returns a bare list today; through `get_sheet_data` it returns the usual dict. `value_render` applies to the values path; with `include_grid_data=True` the grid already carries each cell's formula. |
| `copy_sheet`, `duplicate_sheet` | `copy_sheet(spreadsheet_id, sheet, destination_spreadsheet_id=None, new_name=None, insert_index=None)` | No destination means a `duplicateSheet` in place; a destination means `copyTo` plus the rename `copy_sheet` already does. `copy_sheet`'s parameters change (`src_spreadsheet` → `spreadsheet_id`, `src_sheet` → `sheet`, `dst_spreadsheet` → `destination_spreadsheet_id`, `dst_sheet` → `new_name`), through `deprecation.renamed_params`. `insert_index` across spreadsheets needs an extra `updateSheetProperties`, since `copyTo` appends. |
| `share_spreadsheet` | `share_file` | Already decided (#665). |
| `create_bookmark` | `create_named_range` | Already planned (#1364's "then" step, #1076). |

Net −15. `get_sheet_formulas` is the only `default` tool here.

## Tier B: removals with a behavior difference to settle

### B1. One Drive finder: `search_files`

`search_files` becomes the tool for finding files anywhere. `query` becomes optional, and it gains `order_by` (`modified` or `name`), `shared_with_me` and `modified_within_days`. It absorbs five tools:

| Removed | Becomes | Difference to settle |
|---|---|---|
| `search_spreadsheets` | `search_files(query, mime_type=<spreadsheet>)` | None: the same query, corpus and sort. Its own docstring calls it a "narrower convenience wrapper". |
| `list_spreadsheets` | `search_files(mime_type=<spreadsheet>)`, optionally with `folder_id` | It returns `{id, title}` and isn't cached; `search_files` returns richer fields. |
| `list_folders` | `search_files(mime_type=<folder>, folder_id=...)` | `list_folders` defaults its parent to `DRIVE_FOLDER_ID` and sorts by name; `search_files` doesn't default the folder. The removal either documents that or gives `search_files` the same default for folders. |
| `list_recent_files` | `search_files(modified_within_days=N)` | Default sort `modified`. |
| `list_shared_with_me` | `search_files(shared_with_me=True)` | Must keep the `user` corpus for this case, as `list_shared_with_me` does today (CLAUDE.md, `tools/drive/files.py`). |

`list_files` stays: it's cached, folder-scoped, sorted by name, and reports `exhaustive`, which makes it the right tool for "what's in this folder".

Net −5. This bundle also changes how two decided tickets land:
- **#1202** (decided 2026-11-01, option A) wraps the output of these same five unscoped listings in `{"files": [...], "exhaustive": bool}`. Done together, that breaking output change hits one tool, `search_files`, instead of five. **Recommendation:** fold #1202 into this bundle.
- **#39** (decided 2026-10-18) makes an empty `search_spreadsheets` query an error pointing to `list_spreadsheets`. Both tools go away here, and an empty `query` becomes valid on `search_files`. This supersedes #39, so it's flagged for the maintainer rather than overridden.
- **#1483** (PR #1496 open) rewrites the `list_spreadsheets`/`list_files` docstrings. It's still useful for the deprecation release, when both tools exist.

### B2. `get_doc_content`

Removed in favor of `get_doc_as_markdown` for a Doc's content, or `export_file(export_format="txt")` for plain text. **Difference:** `get_doc_content` is served from the doc cache; neither replacement is. Either accept that, or add the cache to `get_doc_as_markdown` first.

Net −1.

## Tier C: maintainer call (a discoverability cost)

Each saves a tool, but the tool that remains doesn't have the word a model would search for in its name. The docstring would have to carry it.

| Today | After | Cost |
|---|---|---|
| `rename_sheet`, `freeze` | `update_sheet_properties(..., title=, frozen_rows=, frozen_columns=)` | "rename" and "freeze" leave the tool names. `rename_sheet`'s `spreadsheet` parameter, unlike every other Sheets tool's `spreadsheet_id`, goes with it. |
| `unmerge_cells` | `merge_cells(..., merge_type="NONE")` | "unmerge" leaves the tool names. |
| `clear_data_validation` | `set_data_validation` (renamed from `add_data_validation`), where no `condition_type` clears the rule | Both send `setDataValidation`; the rename also fixes "add" for a call that replaces the range's rule. |
| `insert_page_break` | an `insert_doc_text` insertion with `"page_break": true` | "page break" leaves the tool names. |

Net −5 if all are taken.

## Investigate before deciding

- **`import_csv_to_sheet` vs `upload_local_file(convert=True)`.** Both make a spreadsheet from a local CSV. The first parses the file and writes rows with `valueInputOption="USER_ENTERED"` (so it takes `sheet_name` and reports exactly which row ranges failed); the second hands the file to Drive's import. Whether Drive's import parses numbers, dates and leading zeros the same way, and where its size limit sits, needs a live comparison before `import_csv_to_sheet` can go. Not counted above.

## Comments: a smaller shape for #663 and #664

[`decision-comments-first-class.md`](../decisions/decision-comments-first-class.md) (2026-08-28) renames the three comment tools (#663) and specifies eight more (#664): `get_file_comment`, `update_file_comment`, `delete_file_comment`, `reply_to_comment`, `reopen_comment`, `update_reply`, `delete_reply`, `list_replies`. That's 11 comment tools. Its table also names `add_note`/`update_note` for cell notes.

Applying the rule above gives the same API coverage in six:

| Tool | Covers | Annotation |
|---|---|---|
| `list_file_comments` | `comments.list` | read-only |
| `get_file_comment` | `comments.get`, with its replies (covers `list_replies`) | read-only |
| `add_file_comment` | `comments.create` | write |
| `reply_to_comment(action=None)`, with `action` one of `resolve`, `reopen` | `replies.create`, with or without an action (covers `resolve_comment` and `reopen_comment`) | write |
| `update_comment(comment_id, reply_id=None, content)` | `comments.update`, `replies.update` | write |
| `delete_comment(comment_id, reply_id=None)` | `comments.delete`, `replies.delete` | destructive, kept apart from update (rule 3) |

Cell notes would likewise be one `set_note` where empty text clears.

**This reverses part of a decided table**, so it's flagged, not adopted. If the maintainer takes it, it has to be decided before #663 starts, since #663 renames `resolve_doc_comment` to `resolve_comment`, a name this shape folds into `reply_to_comment`. The comments total is 11 under the decided plan and 6 under this one.

## Pairs considered and kept

| Tools | Rule that keeps them apart |
|---|---|
| `add_*`/`delete_*` row and column tools; `insert_table_*`/`delete_table_*`; `add_calendar_acl`/`remove_calendar_acl`; `add_calendar_to_list`/`remove_calendar_from_list`; `share_file`/`remove_permission` | 3: adding and removing are separate permission decisions |
| `delete_file`, `restore_file`, `empty_trash` | 3 |
| `transfer_ownership`, `update_permission` | 3: transferring ownership is the highest-risk sharing action and keeps its own name |
| `get_cache_ttl`, `set_cache_ttl` | 2: a read and a write |
| `list_messages`, `list_threads` | 4: different result types |
| `get_message`, `get_thread`, `get_draft` | 1: different resources |
| `send_message`, `reply_to_message`, `create_draft`, `update_draft`, `send_draft`, `delete_draft`, `list_drafts` | 3, and the send-confirmation design (#1081, `docs/design/gmail-send-confirmation.md`): every send goes through a held draft |
| `create_paragraph_bullets`, `delete_paragraph_bullets` | 4: different item schemas; the create side carries the list logic |
| `upload_file`/`upload_local_file`, `create_doc`/`create_doc_from_file`, `write_doc_content`/`update_doc_from_file`, `insert_inline_image`/`insert_local_images`, `export_file`/`download_file` | 6: local-file access |
| `get_sheet_data`/`get_multiple_sheet_data`, `update_cells`/`batch_update_cells` | 4: merging needs mutually exclusive inputs and two output shapes |
| `list_events`, `list_all_events` | 4: one calendar's events vs several calendars', optionally grouped by calendar |
| `rename_file`, `move_file` | 5: both are `default` tools whose names are the words users say; an `update_file` would hide both |
| `list_files`, `search_files` | See B1: `list_files` is the cached, exhaustive folder listing |

Kept with no overlapping sibling:

- **Sheets:** `add_chart`, `batch_update`, `clear_values`, `create_sheet`, `delete_sheet`, `find_in_spreadsheet`, `format_cells`, `get_multiple_spreadsheet_summary`, `list_sheets`, `sort_range`, `update_borders`, plus `get_data_validation` (the read side of C3) and `update_cells`
- **Drive:** `copy_file`, `create_folder`, `create_shortcut`, `create_spreadsheet`, `download_folder`, `export_revision`, `get_file_metadata`, `get_storage_quota`, `list_drives`, `list_file_activity`, `list_permissions`, `list_revisions`, `sync_folder`, `upload_local_folder`
- **Docs:** `apply_theme`, `delete_doc_range`, `find_in_doc`, `get_doc_structure`, `insert_doc_table`, `insert_softbreak_paragraph` (it writes one paragraph with soft breaks and a named style, which `insert_doc_text` doesn't), `merge_table_cells`, `style_doc_range`, `style_doc_table_cells`, `get_doc_as_markdown`
- **Calendar:** `create_calendar`, `get_calendar`, `update_calendar`, `delete_calendar`, `list_calendars`, `list_calendar_acl`, `create_event`, `get_event`, `update_event`, `delete_event`, `find_free_slots`
- **Gmail:** `list_labels`, `modify_labels`, `trash_message`
- **Cache:** `refresh_cache`

## Counts by group

| Group | Today | After A + B | After A + B + C |
|---|---|---|---|
| `sheets` | 36 | 28 | 24 |
| `drive` | 38 | 31 | 31 |
| `docs` | 34 | 28 | 27 |
| `calendar` | 17 | 17 | 17 |
| `gmail` | 15 | 15 | 15 |
| `cache` | 3 | 3 | 3 |
| **all** | **143** | **122** | **117** |
| `default` | 38 (40 with PR #1510) | 39 | 39 |

The comments tools are in `docs` today and move to `drive` with #663; neither the decided +8 nor the alternative +3 is in this table.

## Deprecation

Every merge goes through `docs/design.md`'s "Renaming or Removing a Tool":

- **A removed tool** whose job moves to a tool with different parameters is deprecated with `deprecation.deprecated_tool(use=...)` for one release, naming the call that replaces it (`` use="`hide_rows_or_columns` with `dimension='rows', hidden=False`" ``). A `RENAMED_TOOLS` alias doesn't fit: an alias passes the old arguments through unchanged, and none of these merges keeps them.
- **A surviving tool** that only gains optional parameters (`star_file`, `get_doc_theme`, `get_sheet_data`, `search_files`, `update_sheet_properties`, `merge_cells`, `insert_doc_text`) doesn't break.
- **`copy_sheet`'s renamed parameters** use `deprecation.renamed_params`. `dst_sheet` was required and `new_name` is optional, so a call naming neither changes meaning: it now duplicates under Google's default name instead of failing validation.
- **During the deprecation release the total rises**, since the merged tools ship while the old ones are still registered: tier A adds seven new names (four Sheets, two Docs tables, `create_header_or_footer`), eight with C3's `set_data_validation`. No group reaches its cap (100 per service group; `default` gains no new tool). The cut lands the release after.
- **Each removal is filed as a ticket when its deprecation merges**, per the policy.

## Order

1. PR #1510 (groups docs) merges first.
2. The maintainer decides the comments shape before #663 starts.
3. B1 lands with #1202 folded in. It supersedes #39.
4. The tier A bundles are independent of each other and of B1.
5. Tier C items join whichever bundle covers their service, once approved.

## Implementation tickets, to file after approval

1. Sheets rows and columns: the four `*_rows_or_columns` tools (A).
2. Sheets reads and copies: `get_sheet_data(value_render=)`, `copy_sheet` absorbing `duplicate_sheet` (A), and any approved C items for Sheets.
3. Docs: the table row/column tools, `create_header_or_footer`, `get_doc_theme(source=)` (A), `get_doc_content` (B2), and `insert_page_break` if C4 is approved.
4. Drive finder: `search_files` absorbing five tools, `star_file(starred=)`, with #1202 (B1, A).
5. Investigation: `import_csv_to_sheet` against Drive's CSV import, live.
6. If the comments shape is approved: amend `decision-comments-first-class.md`, then re-scope #663 and #664.

## Open questions for the maintainer

1. Approve tiers A and B as listed?
2. Which tier C items, if any?
3. The comments shape: the decided 11 tools or the proposed 6?
4. B2: accept losing the doc cache for plain-text reads, or add it to `get_doc_as_markdown` first?
5. The names. `*_rows_or_columns` favors being found by search over brevity; the alternative is the API's own word, `*_dimension`.
