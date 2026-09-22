# Decision: Static Lint Check for `supportsAllDrives` (issue #696)

**Date:** 2026-09-22
**Snapshot commit:** branch `chore/ash/issue-696` — see `scripts/check_supports_all_drives.py`

## Background

Issue #687 fixed `share_spreadsheet`'s `permissions().create()` call missing `supportsAllDrives=True`, which silently produced "File not found" against any Shared Drive item. Issue #696 flagged that this same literal (`supportsAllDrives=True`) is manually inlined at 58 call sites across 6 files, with nothing stopping a new call site from omitting it the same way #687's did — the ticket left the fix direction open, naming two options.

## Options considered

1. **Runtime wrapper around the service object.** Wrap `drive_service` at construction (`auth.py`) so every `.files()`/`.permissions()` resource-builder call defaults `supportsAllDrives=True` automatically, letting the 58 existing literals be removed entirely. This is the more complete fix — it protects a call site even if a future lint check is bypassed or disabled — but it changes real runtime behavior of every Drive API call in the codebase, and every existing test that mocks `drive_service` directly (asserting `supportsAllDrives=True` appears in the call kwargs) would need to either go through the same wrapper or be rewritten, since a bare `MagicMock()` substituted for the real service never passes through the wrapper. Rejected as disproportionate to the actual defect class (a missing kwarg at write-time, not a runtime correctness gap in existing code — all 58 current sites are already correct).
2. **Static lint/grep-based pre-commit check.** Chosen — see below.

## Decision

**Added `scripts/check_supports_all_drives.py`, an AST-based checker wired into `.pre-commit-config.yaml`** (mirroring the existing `gen-tool-docs` local hook) that walks every `.py` file under `src/mcp_gee_sweet/` and flags a `.files()`/`.permissions()` method call that accepts `supportsAllDrives` but omits the keyword.

- **AST-based, not string/regex.** This codebase's actual call style chains the resource builder and method across multiple lines (`drive_service.files()\n.get(...)`), which a naive text match could miss depending on formatting. Parsing the AST and checking the `Call` node's keyword list directly is immune to that.
- **Method set confirmed live, not assumed from the schema.** Per `CLAUDE.md`'s "Verify a ticket's API premise live before implementing, not after" rule, the exact set of resources/methods that accept `supportsAllDrives` was checked against the live Drive v3 discovery document (`https://www.googleapis.com/discovery/v1/apis/drive/v3/rest`) rather than guessed: only `files` (`get`/`list`/`create`/`update`/`delete`/`copy`/`watch`), `permissions` (`get`/`list`/`create`/`update`/`delete`), and `changes` (unused in this codebase, so left out of the checked set) accept it. `comments`/`replies`/`revisions`/`drives`/`about` do not, confirmed by their absence from the discovery doc's parameter lists — the checker never flags calls on those resources.
- **A `**kwargs` spread is skipped, not flagged.** Two existing call sites (`files().emptyTrash(**kwargs)`, `drives().list(**kwargs)`) build their call kwargs dynamically; a static AST check can't verify what's inside the dict at parse time. Guessing either way risks a false positive, so any call with a `**`-spread keyword is left unchecked rather than reported — this matches neither existing site anyway, since neither calls a checked method (`emptyTrash`/`drives.list` aren't in the checked set), but the guard is defensive against a future one that does.

## Not addressed here

- **Existing 58 call sites are unchanged.** All were already correct; this is purely a regression guard for future code, not a fix to present code.
- **The runtime-wrapper approach** remains a valid, more complete fix if this lint check turns out to be insufficient in practice (e.g. someone routinely bypasses pre-commit). Not pursued now given the scope/risk tradeoff above.

## When to Re-evaluate

- If a call site is added that legitimately needs a `**kwargs`-built call to one of the checked methods, the checker will silently pass it without verifying `supportsAllDrives` — that's an accepted gap (see above), but if it starts happening in practice, revisit whether the skip is still the right tradeoff.
- If the Drive API's discovery document changes which methods accept `supportsAllDrives`, re-verify `CHECKED_METHODS` against the live document rather than assuming it's still accurate.
