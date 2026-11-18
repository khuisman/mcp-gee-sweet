# Invalidating Caches for Cancelled and Failed Writes

**Date:** 2026-10-27
**Issues:** #1030 (with #1032 folded in); Sheets and Calendar added for #1265 (2026-11-14)

## Problem

PR #1029 (#909) fixed one race for the image-embedding doc edits: a write whose call is cancelled while its worker thread runs still lands after the cancellation unwinds, because `asyncio.to_thread` can't stop a started thread. Every other write tool still marked its cache dirty only after a successful response:

- **Docs edit tools** in `editing.py`, `tables.py`, `style.py`, `layout.py`, and `named_ranges.py` (`doc_cache`).
- **Drive tools that change a folder's contents** in `tools/drive/files.py` and `tools/drive/transfer.py` (`drive_folder_cache`): the creates, uploads, copy, move, rename, star/unstar, trash/delete, restore, and `sync_folder`'s per-level writes.

A cancelled call left the cache serving the pre-write state until the TTL or a `refresh_cache`. A failed call did too, although a request that times out may still have been applied. Some sites had narrower versions of the same gap: `insert_doc_table` marked the doc dirty only once its re-fetch found the table, `import_csv_to_sheet` marked the folder only after every chunk write, and `delete_file` marked the folder before the delete, so a read between the mark and an abandoned delete landing re-cached the file.

#1032 is the same stale read from the other side. `DocContentCache.store` had no epoch guard, so a `get_doc_content` fetch that started before an edit could store its pre-edit result after the edit's `mark_dirty`, and `store` writes `dirty=0`.

## Design

### `http_transport.invalidating(callback, *, on_success=True)`

A context manager around a tool's write requests. It enters `after_abandoned_calls(callback)` (#907), so an abandoned request reruns the callback once its thread finishes, and runs the callback once more on every exit from the block. Every exit includes a failure, since the request may have landed, except a 4xx (`is_rejection`): that's the API's answer that it ran nothing, so the callback is skipped (PR #1264 QA round 1). Each tool's old post-success `mark_dirty` is removed, since the block's own exit replaces it. Docs edits go through `tools/docs/invalidation.doc_invalidating`, so the rules live in `invalidating` alone.

`on_success=False` skips the normal exit and leaves it to the caller. Three sites need that because they decide on a normal exit whether anything changed: `upload_local_file` and `upload_local_folder` (a skip must not invalidate, PR #645 QA round 1) and `sync_folder`'s levels (`level_changed`). Each of those now also counts a failed upload, a failed resolve, and an unexpected exception from a step as a change. `_upload_local_file` catches its own errors and returns `{"error": ...}`, which doesn't say whether it was a 4xx, so a rejected upload still marks its one known folder. That costs one listing refetch, never the whole cache.

### `tools/drive._FolderInvalidation`

The callback for a Drive write. It's built with the folders known before the write (a create's target, a move's old and new parents, a delete's parents from its pre-read), and `found(parents)` takes the response's parents when nothing was known up front. A rename, star/unstar, restore, or a copy with no destination only learns its folder from the response. If that write fails without a 4xx, or is abandoned, there is no response, so the callback marks every folder listing dirty (`mark_all_dirty()`). That fallback needs both: no folder known and no response (`found()` never called). A response that names no parents, such as a non-owner's rename of a file shared with them, marks nothing, since there's no listing of the caller's to mark (PR #1264 QA round 1). So a normal rename still invalidates just its own folder. Fetching the parents up front instead would add a `files.get` to every call to cover a rare case.

### `sync_folder`

`_sync_level` runs about 1,100 lines of planning and gathered writes, so each call site (the top level in `sync_folder._run`, each child in `_descend`) is wrapped by `_sync_level_invalidation(lc, drive_folder_id, dry_run)` instead of reindenting the body. A level's own wrapper replaces its parent's hook for that level's requests, because the hook is a `ContextVar`. A subfolder's `create()` runs in the parent level, so it marks the parent. A dry run writes nothing and gets a `nullcontext()`.

### #1032: the epoch guard

`DocContentCache.store` takes `epoch=` like the sheet and folder caches. `get_doc_content` snapshots it after its cache lookup misses and before the export, the order `list_files` and `fetch_sheets` already use. `mark_dirty` already bumped the key's epoch, so only the snapshot and the conditional store were missing. Round 1 snapshotted before the lookup, and that broke caching: with modifiedTime validation on, a lookup that finds a stale row marks it dirty itself (`_check_modified_time`), which bumps the epoch past the snapshot, so every refetch of an edited doc skipped its store and re-exported on the next call (PR #1264 QA round 1).

### In the same files

Three more gaps sat in files this PR already changes, so they're fixed here. `create_doc`/`create_doc_from_file` (`_create_doc_file`) hooked only an abandoned create, and only when a folder was named, so a create that failed after Drive applied it left the listing stale; it now goes through `invalidating` and `_FolderInvalidation` like the other creates. `_replace_doc_content`'s backup copy (`content.py`) never marked its folder dirty, either after the copy or after removing it, so a listing read in between kept showing a deleted backup. `import_csv_to_sheet` (`files.py`) now wraps its sheet rename/resize in `invalidating` for `cache`, and its chunk writes for `sheet_data_cache`.

## Sheets and Calendar (#1265)

The Sheets and Calendar write tools now follow the same rule. Each write runs inside `invalidating`, and its post-success `mark_dirty` is gone.

- **Sheets.** `data.py`'s `_execute_or_error` takes `invalidate=`, the write's callback, and catches the `HttpError` outside the `invalidating` block, so the block sees a 4xx before it becomes an error dict. `clear_values`, `update_cells` (each of its up to two writes), and `batch_update_cells` go through it; `batch_update` marks both caches. In `structure.py`, the tab-list writes (`copy_sheet`'s copy and rename, `duplicate_sheet`, `rename_sheet`, `create_sheet`, `delete_sheet`) invalidate `cache`. Five writes that change values or their positions, `add_rows`, `add_columns`, `delete_rows`, `delete_columns`, and `sort_range`, never invalidated `sheet_data_cache` at all, and `clear_values` didn't either; they now do. The default modifiedTime check usually caught those, but not with `CACHE_VALIDATE_MODIFIED_TIME=false`. Two more change what `sheet_data_cache` holds and now invalidate it (PR #1492 QA round 1): `merge_cells` clears the value of every merged cell but the top-left one, and `format_cells` with a number format changes the `FORMATTED_VALUE` strings `get_multiple_spreadsheet_summary` caches (other formatting doesn't, so only that path invalidates). Resizing, hiding, validation, unmerging, and charts change nothing either cache holds.
- **Calendar.** Every calendar write invalidates through `invalidating`, and the existing Calendar tests that asserted a failed write leaves the cache alone now use a 4xx, the one failure that still does. Each one marks every calendar entry (`_invalidate_calendars`, `mark_all_dirty`), not just the ID it was given: `get_calendar` caches under the caller's spelling, so `primary` and the primary calendar's address are two entries for one calendar, and a write may name only one of them; `create_calendar` and an ACL write's responses don't name the calendar at all. The entries are small and calendar writes are rare. Event writes (`create_event`, `update_event`, `delete_event`) no longer invalidate anything: `CalendarCache` holds no event data, and doing it on every outcome made a bulk event workflow refetch the calendar list after each write. `_get_cached_calendar_list` and `get_calendar` snapshot the epoch after the lookup and pass it to `store_list`/`store`, which now take `epoch=` (#1032's guard).
- **A 4xx after a landed write.** `copy_sheet` (copy, then rename) and `update_calendar` (`calendars().patch`, then `calendarList().patch` for the color) send two writes in one `invalidating` block. Before, a 4xx on the second skipped the callback although the first had landed. `invalidating` now records, through a context variable `execute_in_thread` reads, whether any write in the block may have landed (it returned, failed other than with a 4xx, or was cancelled), and a 4xx skips the callback only when none did. A GET or HEAD doesn't count; a request it can't classify does. A nested block's writes count for the blocks around it. The fix is in the mechanism, so it covers every multi-write block in Docs and Drive too.

`scripts/qa_cancel_inflight_write.py` gained `update_cells`, `create_sheet`, and `update_calendar` (TC-W45, TC-CAL85).

## Not covered

- A create into My Drive's root with no folder named: an abandoned one can't be placed, and the root's listing is keyed by whatever ID the caller passed to `list_files`. `_FolderInvalidation` falls back to `mark_all_dirty()` there.
