# One Temporary-Image-Share Lifecycle

**Date:** 2026-10-13
**Issues:** #909 (bundle of #904, #907, #908, #666)

## Problem

Every image a doc edit embeds from a local path or a `drive:` source is shared `anyone:reader` before the edit, because the Docs backend fetches inline images anonymously, and that share is revoked once the edit is over. `_apply_doc_content` (PR #877) and `insert_local_images` (PR #903) each implemented that sequence themselves, and the copies had drifted. The gaps PR #903's QA found were in exactly the places they differed:

- **#904.** `_apply_doc_content` had no checkpoint between its shielded image gather and its first doc edit. A cancellation held off by the shield was re-delivered at the content `batchUpdate`'s `execute_in_thread`, which by then had already handed the request to a worker thread. `asyncio.to_thread` can't stop a running thread, so a call the client had cancelled still edited the doc.
- **#908.** Its success-path revoke was shielded with no checkpoint afterward. A cancellation that arrived during the revoke was absorbed: no warning was logged, and the response that would have reported a revoke failure was discarded.
- **#907.** When the in-flight edit landed after the cancellation had unwound, the doc cache could hold the pre-edit state. `insert_local_images` marked the doc dirty on its cancel path, before the orphaned edit committed, so a read in between re-cached the old content. `_apply_doc_content`'s cancel path didn't invalidate at all.
- **#666 (2).** `write_doc_content` uploads a local image into the server's default folder without marking that folder's listing dirty. A resized `drive:` copy lands next to its original, which no tool marked dirty either. `insert_inline_image` had the same gap for its resized `drive_file_id` copy.

## Design

### `images.ImageShareLifecycle`

One object per doc edit, holding what the cleanup needs: `shares` (each `(outcome_entry, file_id, permission_id)` to revoke), `outcomes` (every image's entry, for the log), and `created_file_ids` (files the call made, which the log lists separately from the caller's own `drive:` files).

- `resolve(coros)` runs the upload/share coroutines as a gather shielded from cancellation (`return_exceptions=True`, as before), then marks dirty every folder a result names in `created_in`.
- `async with edit():` wraps the doc edit:
  1. A checkpoint (#904), inside the `try` whose handler revokes, so a cancellation landing here still revokes and logs.
  2. The body runs inside `after_abandoned_calls(mark the doc dirty)` (#907, below).
  3. A `finally` around the body marks the doc dirty on every exit, success included. Callers no longer do this themselves.
  4. A shielded revoke, then a checkpoint (#908), so a cancellation held off by the revoke's shield is raised here and the handler logs it.
  5. On any `BaseException` the handler revokes (at most once) and logs through `log_images_after_failed_edit`, then re-raises.

`_apply_doc_content` converts an `Exception` leaving the `async with` into `DocEditError` with the outcome list (#789), after the lifecycle has already revoked and logged. `insert_local_images` catches its own `batchUpdate` failure inside the body, as before. The body also runs when there's nothing to embed, so an all-failed call still checkpoints and logs its orphans (PR #903 QA finding 1).

### `http_transport.after_abandoned_calls` (#907)

#907 suggested exposing `execute_in_thread`'s future so the cancel path could attach a done-callback. That would mean threading the future out of every request an edit makes, including `fill_tables` and anchor resolution, which issue their own requests several calls deep. Instead, a context-scoped hook: inside `with after_abandoned_calls(callback):`, `execute_in_thread` wraps the worker function so that, if the awaiting task gave up on the call while its thread was running, the thread schedules `callback` on the loop (`call_soon_threadsafe`) once it returns or raises. Nested requests are covered because the hook travels in a `ContextVar`, which gathered tasks and worker threads both copy.

The "gave up while running" check is a lock-guarded pair of flags. The worker sets `finished` in its `finally`, and the cancel path sets `abandoned` only if `finished` isn't set yet. Either the thread finished first, so the cancel path's own invalidation already runs after the commit, or the call was marked abandoned first, so the callback runs after the commit. A completed call, or a cancelled one whose thread never started, never triggers the callback, so the hook adds no cache writes on the normal path.

The same hook covers `_replace_doc_content`'s clear `batchUpdate` and `insert_inline_image`'s `batchUpdate`, which have the same orphaned-edit window but no images to share.

### `created_in` (#666)

Only the call that creates a file knows its folder (`downscale_drive_file` picks the original's parent, falling back to the default folder). So `upload_and_share_image` and `upload_and_share_local_image` tag any result that carries a `file_id` they created, an orphan included, with `created_in` (`_with_created_in`). The caller never has to work out the folder. `record_image_outcome` doesn't copy the key into the caller-facing outcome. A `drive:` source's own `file_id` never gets one, since nothing was created.

### `insert_inline_image`'s resized copy

`insert_inline_image` shares nothing temporarily (a `drive_file_id` must already be public), so it doesn't use the lifecycle. Its `auto_downscale` copy, though, is created and link-shared for good, and two exits used to lose its ID: a cancellation during the downscale or the edit, and a failed `batchUpdate`, whose `{"error"}` result omitted `resized_file_id`. The downscale is now shielded and followed by a checkpoint. A failed edit's result carries `resized_file_id`, and a cancelled call logs it as a WARNING, the same treatment PR #877 gave temporary shares.

### #666 (1): already fixed by #511

#666's first item, a `files().get()` failing after a successful `permissions().create()` and losing the permission ID, can't happen any more. Since #511, `share_image_file` takes `webContentLink` from the `create()`/`get()` call that preceded the share and makes no request after it (`test_local_path_uploaded_shared_and_resolved` asserts no `files().get()`). There's nothing left to fix.

### A cancellation after the edit finished (PR #1029 QA round 1)

The post-revoke checkpoint raises a cancellation that the revoke's shield held off, even though the edit itself completed. For `_replace_doc_content` that used to read as a partial write: `_failed` kept the backup copy of a doc whose new content had fully landed (reproduced live). The lifecycle now sets `edit_completed` once the edit body exits cleanly. `_replace_doc_content` builds the lifecycle itself, passes it to `_apply_doc_content(lifecycle=...)`, and on a cancellation with `edit_completed` set it discards the backup (shielded) and re-raises.

`create_doc`/`create_doc_from_file` now mark the target folder dirty right after the Drive `create()`. They used to do it only after the content step, which a cancellation skipped. The doc is in the folder from the create on, and images uploaded later are marked dirty by `resolve()`.

## Trade-offs

- A failed or cancelled `write_doc_content` now marks the doc dirty twice: once in the lifecycle and once in `_replace_doc_content`'s `_failed`. `_failed` has to keep its own call, because a doc that was cleared and whose `_apply_doc_content` raised before the edit phase (during image resolution, say) still changed. A redundant `mark_dirty` costs one SQLite write.
- `_apply_doc_content` now takes the lifespan context (`lc`) instead of the two services, since the lifecycle needs the doc and folder caches too.
