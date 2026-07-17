# Decision: `sync_folder` recursion into subfolders

**Date:** 2026-07-15
**Snapshot commit:** branch `fix/ash/issue-315` — see `src/mcp_gee_sweet/tools/drive/transfer.py` (`_sync_level`, `_list_drive_children`)

## Background

Issue #315: `sync_folder(folder_id, local_path, ...)` only ever compared files living directly inside `folder_id`. It never walked into subfolders on either side, and the failure mode was silent — a folder with subfolders on both Drive and local sides reported a clean "in sync", zero-actions result while having ignored everything nested one level down. Confirmed live against a 22-subfolder / ~225-file tree: `sync_folder` on the root reported only the one loose top-level file and said nothing about the rest.

The issue's own workaround (`list_folders` + one `sync_folder` call per subfolder) works but pushes the recursion-shaped problem onto every caller.

## Options Considered

### Option A: Surface the gap, don't fix it

Detect subfolders present on either side and list them in the response (`subfolders_skipped`) without ever descending into them, leaving the one-call-per-subfolder workaround in place.

**Cons:** doesn't remove the actual pain point (the caller still has to loop); the issue explicitly marked this the fallback, not the preferred fix.

### Option B: Recurse unconditionally, mirroring the full Drive tree onto disk (and vice versa) regardless of `direction` (chosen, with one constraint)

Add `recursive: bool = False`. When true, walk matching subfolders to any depth, reusing the same per-level plan/execute logic already used for files at the top level.

The one constraint carried over from the file-level logic: a subfolder present on **only one side** is only created on the missing side (and descended into) when `direction` would actually put something there:
- Drive-only subfolder → downloaded (local dir created) only if `direction` includes download; otherwise left alone.
- Local-only subfolder → uploaded (Drive folder created) only if `direction` includes upload; otherwise left alone.

Both-sides subfolders always recurse (nothing needs creating). Subfolders left alone this way go into a new `folders_skipped` list — this incorporates Option A's visibility win as a strict subset of Option B's behavior, at no extra cost, since determining "should this recurse" already requires knowing which side each subfolder is on.

**Why the constraint instead of mirroring unconditionally:** a `direction='download'`-only sync must not write to Drive at all, and a `direction='upload'`-only sync must not create empty placeholder directories on disk for content it isn't touching. Recursing into (and creating) the "wrong side" of an asymmetric subfolder would violate that expectation for no sync benefit — the subtree would only ever produce more `skip` entries anyway once inside.

## Implementation notes

- The single-level plan/execute logic (build Drive map, build local map, decide per-name action, execute or dry-run-report) was extracted into a module-level `_sync_level` helper so the exact same logic runs at every depth — this was necessary to reuse rather than duplicate, not an unrelated refactor.
- **Pre-existing bug found and fixed as part of this extraction:** the original single Drive `files().list()` call had no `mimeType` filter, so subfolders came back mixed in with files. Because a folder's mimeType (`application/vnd.google-apps.folder`) shares the same `application/vnd.google-apps.` prefix the code used to detect Workspace docs, a subfolder was treated as an exportable Workspace file whenever `export_format` was set — attempting to `export()` a folder, which fails, and silently landing in `failed` with a confusing error. `_list_drive_children` now splits Drive children into `(files, folders)` by an exact mimeType match, so this can no longer happen in `sync_folder`'s own traversal, regardless of `recursive`. `download_folder` had the identical conflation bug in its own separate listing code and needed its own fix (folders are now always skipped there, since it's non-recursive and never descends into them) — the two tools don't share `_list_drive_children`. TC-D192 guards `sync_folder`; TC-D195 guards `download_folder`.
- Nested results use `rel_prefix` + name (e.g. `sub/nested.txt`) in every list (`uploaded`, `downloaded`, `skipped`, `conflicts`, `failed`, `actions`) — at the top level this is identical to the pre-recursion behavior (empty prefix), so `recursive=False` (the default) is byte-for-byte unchanged.
- Dry-run planning of a not-yet-existing subfolder simulates "nothing there yet" by passing `drive_folder_id=None` (skips the Drive API call, empty Drive-side map) without ever touching the filesystem — this lets `actions` show what *would* happen without creating the folder just to plan against it.

## Decision

**Use Option B.** `recursive` defaults to `False` (no behavior change for existing callers). When `True`, subfolders are walked to any depth; an asymmetric subfolder is only created/entered on the side `direction` would actually populate, and is reported under `folders_skipped` otherwise instead of being silently dropped.

## Follow-up

None currently tracked. If a future caller needs partial-tree sync (e.g. depth limit, subfolder name filter), that's a new, separate ask — not implied by this fix.

## When to Re-evaluate

If `sync_folder` gains a `max_depth` or subfolder-name-filter parameter, the `folders_skipped` semantics here (currently meaning only "direction wouldn't create this side") would need to also cover "excluded by depth/filter" — worth revisiting the field's meaning at that point rather than overloading it silently.
