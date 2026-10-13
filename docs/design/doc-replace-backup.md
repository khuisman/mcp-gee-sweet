# Design: Backup Copy Before Replacing a Doc's Content

**Status:** Implemented. Issue #878. Live-verified against real Drive/Docs API calls via scratch
scripts per `CLAUDE.md`'s "Verify a ticket's API premise live" convention (2026-10-12).

## Problem

`write_doc_content` and `update_doc_from_file` share `_replace_doc_content`
(`tools/docs/content.py`). It clears the doc in its own `batchUpdate` and then writes the new
content in later calls. The clear has to be separate because of the same-batch `insertText`
style-inheritance quirk. If anything after the clear fails (the content `batchUpdate`, a non-image
retry failure, `fill_tables`, anchor resolution), the original content is already gone, and the
error didn't say so.

## The decision that didn't survive measurement

The issue was triaged on 2026-10-04 to record the doc's current Drive revision ID before the clear,
and to name it in the error for recovery with `export_revision`. Restoring the old content by
re-inserting a snapshot was ruled out, because formatting, images, and tables don't round-trip.

Measured live before implementing:

| Case | Revisions before the clear | Right after the clear | `revisions.get` on the recorded ID |
|---|---|---|---|
| Doc written 5 s before the clear | `1, 3` (3 exported the original text) | `1, 4` | 404 at +0 s, +30 s, +2, +5, +8 min |
| Doc idle for 7 min before the clear | `1, 3` (same) | `1, 4` | 404 at +0 s, +30 s, +2, +5, +8 min |

Docs merges the revision that was current before the clear into the clear's own new revision
straight away, however old it is. The pre-clear content is no longer reachable through the
revisions API, so an error naming that revision would point at a 404. This matches the merge
behavior `doc-revision-export.md` recorded, except that here it happened immediately rather than
after a later edit.

## Decision (maintainer, 2026-10-12)

Copy the doc with Drive (`files.copy`) before the clear. A copy is the real document, so formatting,
images, and tables survive, which a re-inserted snapshot wouldn't.

- **Only a doc with content is copied.** An empty doc (`endIndex <= 2`) has nothing to lose and
  isn't cleared.
- **Name and location.** `"<title> (backup before replace)"`. With no `parents` in the request, the
  copy inherits the source's parents, so it sits next to the doc.
- **Success:** the copy is removed with `markdown_export._discard_temp_doc`, the same helper
  `export_revision`'s temporary Doc uses. It deletes the copy, or trashes it when `canDelete` is
  false (a Content manager on a Shared Drive, #876), and retries on a 5xx or 429. A failed removal
  doesn't fail the call. The result gets a `warning` naming the copy.
- **Failure after the clear:** the copy is kept. The result is `{"error", "docId", "backupId"}`
  (plus `images` when there are any), and the error names the copy.
- **The clear answered with a 4xx (429 included):** the API ran nothing, so the doc is unchanged.
  The copy is removed and the error says so. Anything else from the clear (a 5xx, a timeout, a
  transport error) doesn't say whether it landed, so the copy is kept and the error says the
  content *may have been* cleared. QA reproduced a 503 returned after a clear that had run (PR
  #1017 round 1), which an earlier version treated as rejected, deleting the only copy.
- **The doc is re-read after the copy.** The copy takes seconds, and a concurrent edit meanwhile
  would otherwise survive the clear (the doc grew) or make it fail (it shrank). A failed re-read
  stops before the clear: the doc is unchanged and the copy is removed. A doc emptied meanwhile
  isn't cleared, and a later failure still names the copy.
- **The copy fails:** nothing is changed, and an error is returned. A 429 is retried (up to 3 times,
  with backoff), since Drive ran nothing. A 5xx isn't, since the copy may already exist and a
  retry would make a second one. For a failure other than a 4xx, the error names the copy that
  may have been created, so the caller can find and remove it. The exception is
  `storageQuotaExceeded`. A service account can't own a copy of a user-owned doc, and
  `write_doc_content` is the documented way for a service account to write into such a doc
  (`known-limitations.md`'s quota section). That case replaces without a backup and logs a
  warning. If the replace then fails, the error says no backup could be made. Whether other
  permission or limit failures should also fall back to no backup is #1018.
- **Cancellation:** the copy is created inside a shielded scope, so its ID is always recorded (the
  PR #877 rule). The scope is bounded by `_BACKUP_COPY_TIMEOUT` (60 s, all attempts together), per
  `CLAUDE.md`'s rule that a cancel waits for shielded work; a timeout is reported like a 5xx.
  Once the copy exists, a cancellation keeps it and logs a warning with its ID, since the doc may
  already be cleared and the call has no result left to report it in.
- **On success,** the copy's removal and the `webViewLink` lookup run together.

## Cost

Measured on a 20 KB doc: `files.copy` 2.5–4.0 s, delete 0.8–1.3 s, so about 3.5–5 s added to every
replace of a non-empty doc. The maintainer accepted this over options with no recovery path.

## Options rejected

- **Name the pre-clear revision in the error.** The revision is gone at once (table above).
- **Snapshot and re-insert on failure.** Formatting, images, and tables don't round-trip (2026-10-04
  triage).
- **Error message only, no recovery.** A silently emptied doc is real data loss (2026-10-04 triage).
- **Backup behind an opt-out parameter.** Considered on 2026-10-12. Not chosen: the default would
  have been on anyway, and the latency cost is accepted.
