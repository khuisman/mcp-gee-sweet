# Decision: Change Detection for convert_markdown Docs (issue #814)

**Date:** 2026-09-26
**Snapshot commit:** `435a99e` on `develop`. See `_sync_level` and `_upload_local_file` in `src/mcp_gee_sweet/tools/drive/transfer.py`.

## Background

`sync_folder(convert_markdown=True)` uploads a local `.md` file as a Google Doc and matches it back to that file on every later sync. Until now, both directions of change detection compared the local mtime with Drive's `modifiedTime`. To make that comparison hold, both upload paths stamp `modifiedTime` from the local mtime. They do it with a follow-up metadata-only `update()` after `create()`, because Drive's import conversion overwrites the value stamped at create time (#414, TC-D218). #421 finding #5 considered polling until conversion settles and rejected it in favor of this single restamp.

#814 reported that the restamp sometimes loses: in TC-D266 (PR #812), 2 of 5 converted Docs drifted up to 29s past their local mtime. A drifted Doc reads as "Drive newer", and there is no reverse conversion. So the Doc sits in `conflicts` on every bidirectional sync and never settles.

The maintainer set one hard requirement for the fix: `sync_folder` must keep detecting that a converted Doc was changed in Drive rather than locally.

## What was measured

Live, against the global OAuth `mcp-gee-sweet` server, on a scratch Shared Drive folder. Six `.md` files were uploaded with `sync_folder(direction="upload", convert_markdown=True)`, some were then edited through the Docs API (`insert_doc_text`), and one was re-uploaded after a local edit. Revisions were read with `list_revisions`, and `modifiedTime` with `get_file_metadata`, which is uncached.

| Question | Observed |
|---|---|
| Does the restamp race reproduce? | Yes, on 1 of 6 in the first upload. The Doc's `modifiedTime` landed about 1s after its only revision's timestamp. |
| Does the conversion's late overwrite add a revision? | No. The drifted Doc still had exactly one revision. |
| Does an edit made soon after an import merge into the import's revision? | No. An edit about 20s after a create, and one 11s after a re-upload, each got their own revision. |
| Do consecutive edits merge with each other? | Yes. On one Doc, revision 2 was replaced by revision 3 after a second edit. |
| Does a re-upload of an existing converted Doc add revisions? | Exactly one. |
| Does `modifiedTime` reflect a Docs edit promptly? | **No.** Two edited Docs still reported the upload-time `modifiedTime` 70–100s after their edits. It caught up somewhere between 1.5 and 5 minutes later. `list_revisions` showed each edit within seconds. |

The last row is the root cause. Drive's `modifiedTime` for a Google Doc is updated from the Docs backend asynchronously, minutes behind. A late update of the import's own timestamp overwrites our restamp, which is the #814 race. The same lag also hides real edits. In the probe, a `sync_folder` run about a minute after the edits reported both edited Docs as `skipped` (in sync), and the unedited, drifted Doc as a `conflict`. The current signal flagged the wrong Doc and missed the two that were really edited. That run used `direction='upload'`, which still reports a Drive-newer pair as a conflict, so the edits weren't hidden by the direction.

**What this does not establish:**
- The upper bound of the `modifiedTime` lag.
- Whether edits made in the Docs UI (as opposed to the Docs API) merge into an import revision differently.
- Revision behavior for edits by a *different* user. Those can only produce more separate revisions, not fewer.
- Whether other conversion targets (CSV → Sheet, PPTX → Slides) behave the same way. See "Out of scope" below.

## Options considered

1. **Widen the mtime tolerance for converted Docs.** Rejected. The drift isn't bounded, and a wider window also hides real Drive edits for longer.
2. **Poll until conversion settles, then restamp.** Rejected, for the reason #421 already recorded, now made stronger: Drive exposes no "conversion finished" signal, and the lag observed here runs to minutes.
3. **Re-read `modifiedTime` after the restamp and retry a bounded number of times.** Rejected. A re-read immediately after the restamp returns our own value; the overwrite arrives later. To catch it, the re-read has to wait out the lag, which makes this option 2 with a retry cap.
4. **Treat converted Docs as a one-way mirror with no Drive-side edit detection.** Race-free, but it drops the capability the maintainer required to keep. Rejected.
5. **Record our own baseline in `properties`, and detect Drive-side edits through revision history.** Chosen.

This doesn't reverse #421's decision against polling. It makes the question moot: nothing waits on conversion, and converted Docs no longer rely on `modifiedTime` for correctness.

## Decision

For a Doc recognized as converted (`_is_converted_md_entry`), `_sync_level` decides whether each side changed without consulting Drive's `modifiedTime`.

**Local side: compare against a stamped source mtime.** Every converted-`.md` upload stamps the local file's mtime string into a new `properties` key. That covers a new Doc from `_sync_level`'s create path, a re-upload through its `update()` path, and `_upload_local_file(convert=True)` for a `.md` source. Properties survive import conversion; TC-D266 confirmed this for the existing source markers. The key and its roughly 24-byte value sit well under Drive's 124-byte cap (#805). A local mtime within `_SYNC_MTIME_TOLERANCE` of the property means the local file hasn't changed. A local mtime newer than the property means the local file changed. An older one means it was rolled back; recency is then unknown, so the result is a conflict.

**Drive side: detect edits through revision history.** For every converted Doc present on both sides, call `revisions.list`. This isn't gated on `modifiedTime`, because the lag above would hide exactly the edits the check exists for. The cost is one call per converted Doc per sync, run concurrently with the existing per-item work. Only converted Docs pay it.

- *Knowing which revision is ours.* On a re-upload, read the current latest revision ID and stamp it as a baseline property before the `update()`. That read happens before conversion starts, so it can't race. For a new Doc there is no baseline, and the import is the Doc's first revision.
- *Recording the import revision.* On the first sync after an upload, the first revision after the baseline is the import. Record its ID in a property once. If no revision exists after the baseline yet, the sync ran within seconds of the upload. In that case, treat the Doc as unchanged and try again next sync.
- *Detecting an edit.* After that, the Doc was edited in Drive exactly when the latest revision's ID differs from the recorded import revision ID. Edits never merge into the import revision (measured above), so any edit moves the latest revision. Drive trimming or merging *older* revisions doesn't affect this, because only the latest revision is compared.

**Outcome table:**

| Local changed | Drive changed | Result |
|---|---|---|
| no | no | skip (in sync) |
| yes | no | upload, or `conflict` under `direction='download'` |
| no | yes | `conflict`. There is no reverse conversion, so it can't be downloaded. |
| yes | yes | `conflict`. Today this silently overwrites the Drive edit, because local reads as newer. |

**Legacy Docs.** A converted Doc without the new properties (anything converted before this change) stays on the current `modifiedTime` path. It gains the properties on its next re-upload, so no migration pass is needed.

**The restamp stays.** For converted Docs it's now purely cosmetic: it keeps Drive's displayed "last modified" near the source mtime, and correctness no longer depends on it. The shared `_restamp_modified_time` helper from #435 / PR #817 is where the new property stamping goes. That helper's docstring currently says the restamp "makes the stamp stick", which this measurement contradicts, so #814 corrects it.

## Out of scope

- **Other conversion types.** CSV → Sheet (and likely PPTX → Slides) matched back through `export_format` compare `modifiedTime` the same way, and probably share both the race and the edit-lag. There, the race's failure mode is a spurious download of the export over the local source. This wasn't measured here and is tracked in #818 rather than widening #814.
- **Surfacing *who* edited in Drive.** `revisions.list` returns the last modifying user, which could enrich the conflict reason. That's a nice-to-have, not part of this fix.

## When to re-evaluate

If Drive starts exposing a reliable "last content change" for Google Docs, or if a measurement shows Docs-UI edits merging into an import revision, the Drive-side signal needs revisiting.
