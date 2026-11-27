# Converted Uploads: Restamping After the Import's Own Write (#1415)

**Date:** 2026-11-27
**Code:** `_await_import_write` and `_restamp_modified_time` in `src/mcp_gee_sweet/tools/drive/transfer.py`.

## Problem

A converted upload (`upload_local_file(convert=True)`, `upload_local_folder(convert=True)`, `sync_folder(convert_markdown=True)`) restamps the new file's `modifiedTime` with a metadata-only `update()` after `create()`, because the import conversion doesn't keep the value `create()` was sent (#421, TC-D218). In the ornithomimus release pass, 3 of 16 CSV → Sheet uploads under a service account still carried their upload time an hour later (#1415). A `sync_folder(export_format="csv")` dry run then planned to download two of them over their local CSVs.

#818 had probed the Sheets restamp race on 2026-11-01 and not seen it, one sample per case. It shows up only in larger samples.

## What was measured

All live, 2026-11-27, on a scratch folder in the team's Shared Drive. The uploads ran concurrently, 8 at a time, from a fresh interpreter (`googleapiclient` directly, or the branch's `_upload_local_file`), plus one `upload_local_folder(convert=True)` call through the lane server.

| Question | Observed |
|---|---|
| Does it reproduce? | Yes. 1 of 16 through `upload_local_folder`; with an immediate restamp, 3 of 24 under OAuth and 6 of 24 under a service account. Slides (1 of 16) and Markdown Docs (1 of 16) too. |
| Does the restamp land? | Yes. Its `update()` response carries the stamped `modifiedTime`. |
| What overwrites it? | The import. Each drifted file has one revision, and its `modifiedTime` is 0.6–1 s after that revision's timestamp. Nothing moved it later (checked at +5 s, +30 s, +90 s). |
| Which restamps lose? | Fast ones. In one OAuth run of 24, the three drifted restamps took 0.65–0.73 s; most that held took 1.4–1.9 s, though four fast ones held too. The restamp has to land after the import's write to survive. |
| Does the file show the import's progress? | Through `version`. `create()` returns version 4 (sometimes 5). The import writes version 5, which is the write that moves `modifiedTime` (32 of 32 CSV uploads, no restamp), then versions 6 and sometimes 7, which never moved it. Revision 1 appears before version 5. |
| Does the import always move `modifiedTime`? | No. With a `modifiedTime` in the create body, some imports reached version 6 without moving it. So "wait until `modifiedTime` changes" can wait forever (it hit a 15 s cap on 1–3 of every 24); "wait until `version` passes `create()`'s" doesn't. |
| Does restamping after the version moves hold? | Yes: 0 of 72 Sheets under OAuth, 0 of 72 under a service account, 0 of 16 each for Slides, Markdown Docs and HTML Docs (checked at +60 s or +90 s). Through the branch's `_upload_local_file`, 0 of 144 (3 runs × 24 per identity). |
| How long is the wait? | At most 2.3 s under OAuth and 5.2 s under a service account, usually about 0.9 s (one or two polls). |

## Decision

Before the restamp, `_await_import_write` polls `files().get(fields="version")` every `_IMPORT_WRITE_POLL_SECONDS` (0.5 s) until the version is past the one `create()` returned, for at most `_IMPORT_WRITE_WAIT_SECONDS` (15 s). Both `create()` calls that convert ask for `version` in their fields.

If the version never moves within the bound, if a poll fails, or if `create()` returned no version, the restamp goes out at once, as it did before. The wait can make an upload slower but never leaves it worse stamped than before.

The restamp now waits for the import's own write, which #814's [decision](../decisions/decision-converted-doc-change-detection.md) (option 2) and #421 rejected as having "no conversion finished signal". For a Doc that's still true of what #814 measured: the Docs backend moves `modifiedTime` minutes after an *edit*, and no wait at upload time helps there. A convert_markdown Doc's change detection runs off properties and revision history, and stays that way. What this measures is narrower: the import's own write, the one that overwrote the restamp, is visible through `version`, on every conversion type.

## Not covered

- `sync_folder`'s re-upload of an existing converted `.md` Doc (`update()` with media) re-imports in place and sends `modifiedTime` in the same call, so the import can overwrite it the same way. It isn't restamped afterwards. That Doc's change detection doesn't read `modifiedTime` (#814), so only Drive's displayed "last modified" is affected.
- A Sheet or Slides deck edited in Drive is still detected by `modifiedTime`, which #818 measured tracking an edit within a second.
