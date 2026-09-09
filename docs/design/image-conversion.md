# Design: Native Markdown/HTML Image Support (issue #333)

## Problem

`create_doc`/`create_doc_from_file`/`write_doc_content` silently dropped every `<img>` /
`![alt](src)` during conversion (confirmed via TC-DOC102/103, filed as the original #333 bug
report). The only path to an embedded image was the pre-existing `insert_local_images` (#332),
which requires a manual placeholder-marker workaround per image — a multi-step, multi-tool-call
dance the issue's own reporter described in detail.

## Image as a first-class AST node, not a marker

The tempting shortcut was to reuse `insert_local_images`'s already-proven marker mechanism
under the hood: substitute each `![]()` with a unique placeholder token during markdown→HTML
conversion, let the existing (unmodified) AST/emitter pipeline treat it as ordinary text, then
run a second pass after the main content batch to locate each marker and swap in the image —
exactly what `insert_local_images` already does. This would have meant zero changes to
`ast.py`/`html_parser.py`/`emitter.py`'s position math.

Rejected in favor of a true `Image` AST node (`ast.py`) because the marker approach requires a
*second* round-trip after the main `insertText`/table batch — a real robustness cost (a doc left
with literal marker text visible if the second pass fails) for no benefit once the atomic
single-batch approach turned out to be achievable. An `Image` node contributes **zero characters**
to `ast_to_requests`'s text-building pass (unlike a marker) — it's purely a positional marker
within a node's `runs` list, resolved into its own `insertInlineImage` request. This lets it
piggyback on the exact "process positional insertions in descending-document-order" pattern this
codebase already uses for tables (`ast_to_requests`'s trailing loop), generalized here into
`positional_inserts`: a single combined list of `(final_position, request)` covering **both**
tables and images, sorted descending and applied together. Interleaving them in one list (not two
separate blocks, "all tables then all images") matters — a table inserted before a lower-position
image within the same document would otherwise physically shift that image's precomputed
position before it gets a chance to run.

`ast_to_requests` stays fully synchronous (no network I/O) by accepting an already-resolved
`image_uris: dict[id(image), str]` map rather than doing any resolution itself.
`extract_images(nodes)` is the paired helper the caller (`content.py`, async) uses to collect
every `Image` in a parsed tree *before* calling `ast_to_requests`, resolve each one to a URI, and
pass the map in. An `Image` with no entry in that map (resolution failed, or the caller never
passed one at all) is silently omitted — the same graceful-degradation behavior any other
unsupported construct already gets from this parser.

## Three source kinds, one shared resolver

`src` may be a local filesystem path (uploaded to Drive, then shared), a `drive:<file_id>`
reference to an already-uploaded file (shared, not uploaded), or a public `http(s)://` URL (used
directly — no upload, no share, nothing to revoke). `_resolve_image_source` (`content.py`)
implements all three; `insert_local_images`'s own upload+share logic was left as its existing
inline code rather than refactored to share this helper, since its local-path-only case doesn't
need the source-kind dispatch.

Local-path and `drive:` sources are shared `anyone:reader` regardless of source, since the Docs
backend fetches an inline image as an anonymous HTTP request at insertion time — confirmed live
in #332, reconfirmed here for the `drive:` case specifically. Per explicit product decision
(2026-08-02), that temporary share is revoked again by default once the image is actually
embedded (`revoke_sharing=True`) — a **behavior change** from #332's `insert_local_images`, which
always left images shared with no flag at all; both surfaces now share the same default and the
same opt-out flag, since a caller has no principled reason to want different defaults from two
tools performing the same upload→share→embed→[revoke] lifecycle.

## Live-discovered bug: one bad image URI fails the entire batch

The atomic single-batch design (image + table insertions bundled with all other content
requests) has a real failure mode the position-math design alone doesn't cover: the Docs API
rejects an entire `batchUpdate` if *any one* `insertInlineImage` request in it can't be fetched
by Google's own (unauthenticated, separate-network-path) image-fetching service — confirmed live
via TC-DOC102's own Case 8 (a deliberately unreachable URL), which was silently killing Cases
1–5's otherwise-valid image requests in the same call. This is not a position-math bug — a
rejected `batchUpdate` executes nothing at all, successful or not.

Fixed by treating this as a retryable, not fatal, failure: Google's own error message names the
failing request's index directly (`"Invalid requests[N].insertInlineImage: ..."`), so
`_apply_doc_content` catches the `HttpError`, parses that index out via regex
(`_failed_insert_image_request_index`), strips exactly that request from the list, and retries
with everything else unchanged. Safe without any position recomputation specifically *because* a
rejected batch never partially applies — every other request's absolute position is exactly as
valid on retry as it was on the first attempt. The removed image's outcome entry gets an
`error` field; every other image/table/text request in the same call is unaffected.

## Known, deliberate gap: table-cell images

`html_parser.py`'s img-handling only fires when a block context is open at the body level
(`self._block_tag` truthy) — explicitly excluded when inside a table cell, where it falls through
to the existing silent-no-op path any other unsupported construct already gets there. This is not
an oversight: `Cell.children`'s type (`list[Run | Image | Table]`) already allows an `Image` for
forward-compatibility, but the cell-fill machinery (`emitter.py`'s `_fill_children_recursive`)
would infinite-loop on one if it ever appeared — its cursor-advance logic assumes every non-Table
child is a `Run` with a `.text` to consume, and would stall forever on an `Image` (`isinstance(child,
Run)` false, so the run-group loop never advances `cursor`). Supporting table-cell images
requires extending that cursor logic (and the live-index re-fetch cycle it depends on) to a third
child type — a meaningfully larger increment of complexity than body-level support, and not
something the original issue's own ask required. Tracked as a follow-up rather than folded into
this change.
