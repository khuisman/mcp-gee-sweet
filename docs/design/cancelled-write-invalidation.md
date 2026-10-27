# Invalidating Caches for Cancelled and Failed Writes

**Date:** 2026-10-27
**Issues:** #1030 (with #1032 folded in)

## Problem

PR #1029 (#909) fixed one race for the image-embedding doc edits: a write whose call is cancelled while its worker thread runs still lands after the cancellation unwinds, because `asyncio.to_thread` can't stop a started thread. Every other write tool still marked its cache dirty only after a successful response:

- **Docs edit tools** in `editing.py`, `tables.py`, `style.py`, `layout.py`, and `named_ranges.py` (`doc_cache`).
- **Drive tools that change a folder's contents** in `tools/drive/files.py` and `tools/drive/transfer.py` (`drive_folder_cache`): the creates, uploads, copy, move, rename, star/unstar, trash/delete, restore, and `sync_folder`'s per-level writes.

A cancelled call left the cache serving the pre-write state until the TTL or a `refresh_cache`. A failed call did too, although a request that times out may still have been applied. Some sites had narrower versions of the same gap: `insert_doc_table` marked the doc dirty only once its re-fetch found the table, `import_csv_to_sheet` marked the folder only after every chunk write, and `delete_file` marked the folder before the delete, so a read between the mark and an abandoned delete landing re-cached the file.

#1032 is the same stale read from the other side. `DocContentCache.store` had no epoch guard, so a `get_doc_content` fetch that started before an edit could store its pre-edit result after the edit's `mark_dirty`, and `store` writes `dirty=0`.

## Design

### `http_transport.invalidating(callback, *, on_success=True)`

A context manager around a tool's write requests. It enters `after_abandoned_calls(callback)` (#907), so an abandoned request reruns the callback once its thread finishes, and runs the callback once more on every exit from the block. Every exit includes a failure: the request may have landed. Each tool's old post-success `mark_dirty` is removed, since the block's own exit replaces it.

`on_success=False` skips the normal exit and leaves it to the caller. Three sites need that because they decide on a normal exit whether anything changed: `upload_local_file` and `upload_local_folder` (a skip must not invalidate, PR #645 QA round 1) and `sync_folder`'s levels (`level_changed`). Each of those now also counts a failed upload, a failed resolve, and an unexpected exception from a step as a change.

### `tools/drive._FolderInvalidation`

The callback for a Drive write. It's built with the folders known before the write (a create's target, a move's old and new parents, a delete's parents from its pre-read), and `found(parents)` takes the response's parents when nothing was known up front. A rename, star/unstar, restore, or a copy with no destination only learns its folder from the response. If that write fails or is abandoned there is no response, so the callback marks every folder listing dirty (`mark_all_dirty()`). That fallback runs only on those rare paths, so a normal rename still invalidates just its own folder. Fetching the parents up front instead would add a `files.get` to every call to cover a rare case.

### `sync_folder`

`_sync_level` runs about 1,100 lines of planning and gathered writes, so each call site (the top level in `sync_folder._run`, each child in `_descend`) is wrapped by `_sync_level_invalidation(lc, drive_folder_id, dry_run)` instead of reindenting the body. A level's own wrapper replaces its parent's hook for that level's requests, because the hook is a `ContextVar`. A subfolder's `create()` runs in the parent level, so it marks the parent. A dry run writes nothing and gets a `nullcontext()`.

### #1032: the epoch guard

`DocContentCache.store` takes `epoch=` like the sheet and folder caches, and `get_doc_content` snapshots it before its first Drive read, the metadata `files.get` when modifiedTime validation is on. `mark_dirty` already bumped the key's epoch, so only the snapshot and the conditional store were missing.

### In the same files

Two more gaps sat in files this PR already changes, so they're fixed here. `_replace_doc_content`'s backup copy (`content.py`) never marked its folder dirty, either after the copy or after removing it, so a listing read in between kept showing a deleted backup. `import_csv_to_sheet` (`files.py`) now wraps its sheet rename/resize in `invalidating` for `cache`, and its chunk writes for `sheet_data_cache`.

## Not covered

- The Sheets tools under `tools/sheets/` and the Calendar write tools in `calendar.py` still invalidate only after a successful response, and `calendar.py`'s calendar-list fetch stores without an epoch guard. The Calendar tests assert that a failed write doesn't invalidate, so changing that is a policy change of its own.
- A create into My Drive's root with no folder named: an abandoned one can't be placed, and the root's listing is keyed by whatever ID the caller passed to `list_files`. `_FolderInvalidation` falls back to `mark_all_dirty()` there.
