# Decision: Comments as a First-Class, Cross-Suite Capability

**Date:** 2026-08-28
**Snapshot commit:** branch `doc/joy/comments-first-class`

## Background

The user asked whether comments had been missed entirely as a class of interaction, starting from the (incorrect) premise that Google Docs had no comment tooling at all. Investigation found the opposite problem: comments exist, but the codebase's own bookkeeping about them has drifted, and the underlying capability was never built out to match what the Drive API actually offers.

**What's actually shipped today:** `src/mcp_gee_sweet/tools/docs/comments.py` ships `list_doc_comments`, `add_doc_comment`, `resolve_doc_comment` (issue #151, PR #324, Tier 2, closed). All three call the generic Drive v3 `comments()`/`replies()` resource against `fileId` — there is nothing Docs-specific in the implementation. Confirmed live: the exact same code, pointed at a real Spreadsheet's file ID, returns real comment data today with zero modification.

**Two roadmap/issue inaccuracies found and corrected by this doc:**
- `docs/roadmap.md` Tier 4 still carries `Doc comments (add/get/list/reply/resolve/delete) — we have zero comment tooling on Docs today`, untouched since #151 shipped a subset of exactly that scope. Stale.
- Issue #142 ("File comments — list and add comments on Drive files," Tier 3, v1.0) was filed on the premise that "comments are separate from Google Docs comment threads." They are not — same Drive resource. #142 asks for something #151 already built, under different naming.

**A parallel, unreviewed instance of the same pattern exists elsewhere in this codebase:** `share_spreadsheet` (`tools/drive/sharing.py`) is literally the project's original tool (PR #1, from before Drive had its own domain). `share_file`, added later, is a strict superset of its capability (generic `type`/`role` permission entries vs. `share_spreadsheet`'s narrower always-`user` email+role shape), over the identical Drive `permissions()` resource. Nobody ever revisited `share_spreadsheet` once `share_file` existed — no decision doc discusses it, and the one open roadmap item touching both (#38, ownership validation) is unrelated to consolidation. This doc treats it as corroborating evidence for the design principle below, but scopes the actual fix to a separate follow-up issue (see Decision 6) rather than bundling it into comments work.

## Google's own permission model is unified — not split by product

Checked `auth.py`'s `SCOPES`: `spreadsheets`, `drive`, `calendar`, `drive.activity.readonly`. There is no Docs-specific or Sheets-specific comment (or sharing) scope. The Drive `comments`/`replies` resource (`files/{fileId}/comments`) is the *only* API surface for comments on any file type, gated entirely by the one broad `drive` scope. Google does not distinguish "comment on a Doc" from "comment on a Sheet" at any level — not the API surface, not the OAuth scope. Any Docs/Sheets split we might invent in our own tool surface would be modeling a distinction that doesn't exist upstream.

Confirmed live, full method surface (neither used anywhere in this codebase today beyond the three Tier-2 tools):

| Resource | Methods |
|---|---|
| `comments` | `create`, `get`, `list`, `update`, `delete` |
| `replies` | `create`, `get`, `list`, `update`, `delete` |

`replies().create()` with `body.action` of `resolve` or `reopen` is how resolve/reopen work (confirmed via the live discovery schema); a plain reply is `create()` with `content` and no `action`.

## Decisions

### 1. One generic tool set, not domain-duplicated wrappers

Considered three shapes: (a) one generic set operating on any `file_id`, (b) generic implementation plus real per-domain wrapper tools that verify `mimeType` before delegating, (c) generic implementation plus unenforced per-domain naming sugar. Chose (a).

Reasoning: `ENABLED_TOOLS`/`--include-tools` (confirmed in `server.py`) matches by **exact function name only** — no wildcards, no module-awareness. Splitting into `list_sheet_comments`/`list_doc_comments` doesn't give an operator anything beyond "twice as many on/off switches for identical underlying behavior," and doing it in an *enforced* way (b) costs a real extra `files().get(fileId, fields="mimeType")` round-trip on every call. Doing it unenforced (c) is naming sugar that risks being mistaken for a security boundary. Given Google's own model is unified (see above), (a) is also the option that doesn't invent a distinction the platform itself doesn't have.

### 2. Module home: `tools/drive/comments.py`

Comments are a generic Drive-resource capability, not owned by Docs or Sheets — this matches how `tools/drive/files.py` and `tools/drive/sharing.py` already own generic file-level operations (`share_file`, `copy_file`, `move_file`) that work against any file type. `tools/docs/comments.py` is retired; its logic moves to `tools/drive/comments.py` unchanged in substance.

### 3. Rename to generic tool names — an explicit breaking change

`list_doc_comments` → `list_file_comments`, `add_doc_comment` → `add_file_comment`, `resolve_doc_comment` → `resolve_comment`, param `doc_id` → `file_id`.

Confirmed live: this codebase has **no alias or deprecation mechanism** — `tool()`'s decorator either registers a function under its exact name or doesn't; a caller pinning `ENABLED_TOOLS=list_doc_comments` would see the tool silently vanish (not error) once renamed. This is a real breaking change and should be called out explicitly in the CHANGELOG/release notes for whichever version ships it. Chosen anyway over a permanent-alias approach, consistent with this project's stated anti-shim style (`CLAUDE.md`: "avoid backwards-compatibility hacks... just change the code") and because the affected surface is small and recently shipped (Tier 2, not original/entrenched like `share_spreadsheet` — see Decision 6 for why that one is treated more cautiously).

### 4. Cell notes are a separate capability, not part of "comments"

Sheets' `CellData.note` field (Sheets API v4, set via `batchUpdate` `updateCells`/`repeatCell` with `fields=note`) is a completely different mechanism from Drive comments: plain text, no author, no thread, no resolve state, no Drive API involvement at all. Confirmed via repo-wide grep: entirely unbuilt today (issue #131, Tier 4, no code touches `note` anywhere). Ships as its own module, `tools/sheets/notes.py` (`add_note`/`get_note`/`clear_note`), not folded into the comments work — conflating the two is exactly the confusion the current stale Tier 4 roadmap line already has ("Sheet comments **and cell notes**... zero tooling") and is worth untangling explicitly rather than perpetuating.

### 5. Cell-anchored Sheets comments — confirmed infeasible via the public API; cell notes are the documented answer instead

Google's own docs (`developers.google.com/workspace/drive/api/v3/manage-comments`) state plainly that Workspace editors treat a custom `anchor` value as unanchored, and that anchors are best suited to "documents where the position doesn't change" — not an encouraging signal for arbitrary cell-pinning.

Three live experiments confirmed this outright, no spike ticket needed:
1. Reading real, human-created comments on an actual spreadsheet (via `comments().list()`) shows Sheets' own client uses `anchor` shaped as `{"type":"workbook-range","uid":<sheetId>,"range":"<opaque numeric id>"}`. This schema is **not documented anywhere in Google's public API docs** — it was recovered empirically. The `range` value doesn't match any sheetId, protected-range ID, or chart ID on the sheet it came from (checked via `spreadsheets().get()`); it looks like an internal ID assigned by Sheets' own client, not something constructible from an A1 string via the public API.
2. Creating comments on a scratch spreadsheet with three candidate `anchor` payloads (the observed shape with a guessed `range`, a community-sourced `{"a1Range": "..."}` format, and Google's own documented generic `drive#commentRegion` example) — **all three were accepted and echoed back verbatim by `comments().create()`/`.get()`, with zero validation.** Proves the API stores literally any string as `anchor`; write-side success is not evidence of anything rendering.
3. **Visual confirmation** (live, human-checked): a control comment (no anchor) plus both candidate formats were created on three cells of a scratch spreadsheet and viewed directly in the Sheets UI. None of the three — including the format that mimics real Sheets-anchored comments structurally — rendered with a cell-pinned indicator, before or after a page refresh. All three appeared identically unanchored.

**Conclusion: closed as infeasible via the public API**, matching this project's existing precedent for the `tabStops` case (issue #404) — a capability that looks plausible from the discovery schema but has no real write path. Not filed as a roadmap item pending future re-investigation; the `range` field is almost certainly an internal Sheets identifier with no public construction path, and there's no signal Google intends to expose one.

**Cell notes were verified as the working alternative** for "point at a specific cell": set live via `batchUpdate`'s `updateCells` with `fields="note"`, read back correctly via the API, and confirmed visually in the Sheets UI — the black corner-triangle indicator and hover popup rendered exactly as expected, with the exact text set through the API. This is a real, fully-functional, already-designed mechanism (Decision 4) — it's the answer to "I want to point a comment at cell B2," just not via the `comments` resource.

### 6. `share_spreadsheet`/`share_file` overlap — flagged, not fixed here

Same shape of problem as #151/#142, and a cleaner case of it (`share_file` is a strict superset, not just similarly-scoped). Not bundled into this work: `share_spreadsheet` is the project's original tool with a much longer usage/compatibility tail than the 3-tool comments surface, so deprecating it deserves its own review rather than riding along with an unrelated piece of work. Filed separately (Ticket 6 below).

## Proposed tool surface (target end-state)

All in `tools/drive/comments.py` unless noted; all operate on any `file_id`.

| Tool | Drive call | Status |
|---|---|---|
| `list_file_comments` | `comments().list()` | Rename of `list_doc_comments` |
| `get_file_comment` | `comments().get()` | New |
| `add_file_comment` | `comments().create()` | Rename of `add_doc_comment`; gains an optional passthrough `anchor: str \| None` param for non-Workspace Drive files (images, PDFs) where Google's documented generic `drive#commentRegion` format may actually be honored — confirmed inert for Docs/Sheets/Slides (Decision 5), so the docstring must say so explicitly rather than implying it can pin a comment to a cell |
| `update_file_comment` | `comments().update()` | New — edit a comment's content |
| `delete_file_comment` | `comments().delete()` | New — explicitly out of scope for #151 per its own QA docs; closes that gap |
| `reply_to_comment` | `replies().create()` (no `action`) | New — plain reply; today only a resolve-flavored reply exists |
| `resolve_comment` | `replies().create(action="resolve")` | Rename of `resolve_doc_comment` |
| `reopen_comment` | `replies().create(action="reopen")` | New |
| `update_reply` | `replies().update()` | New — edit a reply's content |
| `delete_reply` | `replies().delete()` | New |
| `list_replies` | `replies().list()` | New — pagination beyond what `list_file_comments` embeds inline; low priority |

Cell notes, in `tools/sheets/notes.py` (Sheets API v4, unrelated resource):

| Tool | Mechanism |
|---|---|
| `get_note` | `spreadsheets().get(fields=".../note")` |
| `add_note` / `update_note` | `batchUpdate` `updateCells`/`repeatCell`, `fields="note"` |
| `clear_note` | same, empty string |

## Wiring and doc-gen impact

- `tools/sheets/__init__.py` is currently empty (0 bytes); `tools/__init__.py::register_all` imports `sheets.data`/`sheets.structure` directly. Adding `sheets/notes.py` is the moment to mirror the `docs` package's own pattern: give `sheets/__init__.py` a `register(tool)` that fans out to `data`, `structure`, `notes`, and have `tools/__init__.py` call `sheets.register(tool)` once — consistent with how `docs.register(tool)` already works, instead of growing `register_all` linearly forever.
- `scripts/gen_tool_docs.py`'s `SECTIONS` list needs two new predicate entries (`"Drive — comments"` matching `mcp_gee_sweet.tools.drive.comments`, `"Sheets — notes"` matching `mcp_gee_sweet.tools.sheets.notes`) or the pre-commit hook fails the commit outright (confirmed: `render_tools_md` raises `RuntimeError` for any unmatched module).
- `tests/test_docs_comments.py` relocates to `tests/drive/test_comments.py`, extended for the new tools; existing coverage (confirmed by reading it in full) asserts request/response field mapping well but has **no error-path unit tests** (404s etc. are QA-only today) — worth closing that gap while the module moves, not just carrying it forward.
- QA test cases `TC-DOC96–101` (`docs/qa/tests/docs_content.md`) relocate to a new `docs/qa/tests/drive_comments.md`, following the same prescriptive Setup/Prompt/Checks/Cleanup template, extended with: a Sheets-file-id case (proving the generalization live), and one case per new tool. The anchor-feasibility spike itself becomes its own QA-style test case with an explicit Playwright visual-check line.
- `docs/roadmap.md`: fix the stale Tier 4 Docs line, close or re-scope #142, add a new Tier-appropriate entry for cell notes (#131 already exists) and for this rename/generalization work with real issue numbers once filed.

## Ticket plan

1. **Roadmap/issue cleanup** (no code) — fix the stale Tier 4 Docs comments line; close #142 as superseded by #151, or re-scope it to whatever's still missing.
2. **Generalize existing three tools** — move to `tools/drive/comments.py`, rename per Decision 3, update tests/QA/docs-gen config. Mechanical, low risk, highest value (this is the part that's actually "missing" today: discoverability, not capability).
3. **Fill CRUD gaps** — `delete_file_comment`, `reply_to_comment`, `reopen_comment`, `get_file_comment`, `update_file_comment`, `update_reply`, `delete_reply`, `list_replies`.
4. **Cell notes** — `tools/sheets/notes.py`, closes #131. Feasibility already confirmed live (Decision 5) — this is a straight implementation ticket, no spike needed.
5. **`share_spreadsheet`/`share_file` consolidation review** — separate from comments work; evaluate deprecation path given its longer compatibility tail.

Cell-anchored Sheets comments are **not** a ticket — Decision 5 closes that line of work outright, confirmed infeasible via three live experiments (empirical schema recovery, write-side validation-bypass proof, and direct visual confirmation in the Sheets UI). No further investigation recommended barring a future change in what Google's API exposes.

## When to Re-evaluate

- **Decision 1** (no domain-duplicated tools): revisit if an operator actually asks for per-domain comment restriction as a real deployment need — the enforcement cost (extra `mimeType` round-trip) was judged not worth paying speculatively, not judged impossible.
- **Decision 3** (breaking rename): if this ships in a version where deprecation tooling has since been added generally to the project, prefer that mechanism over a bare rename.
- **Decision 5** (anchor infeasibility): revisit only if Google documents and exposes a real, public write path for Workspace-editor comment anchoring — nothing in this investigation suggests that's planned. Not worth re-checking speculatively.
- **Decision 6**: if `share_spreadsheet` usage data (QA fixtures, README references, any telemetry) shows it's rarely used standalone, the deprecation case gets stronger; if it's heavily referenced, consider keeping both permanently instead and documenting *why*, rather than leaving the question open indefinitely.
