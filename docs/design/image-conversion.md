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
`_apply_doc_content` catches the `HttpError`, parses that index out of the structured response
(`_failed_insert_image_request_index` — status 400 plus `HttpError.reason`, which the client
library fills from the JSON body's `error.message`, not `HttpError`'s own display string, #510),
and strips exactly that request. The dropped image's outcome `error` is built from that same
field, minus its `Invalid requests[N].` lead-in (`N` indexes an internal retry batch). Safe without any
position recomputation specifically *because* a rejected batch never partially applies — every
other request's absolute position is exactly as valid on retry as it was on the first attempt.
The removed image's outcome entry gets an `error` field; every other image/table/text request in
the same call is unaffected.

Google names only the *first* failing image per error (confirmed live), so K unreachable images
need K retries. Resending the whole document each time would be K+1 full-size round trips, so
(#510):

- **K=0 and K=1 stay all-or-nothing.** The happy path is one atomic call; the first retry is
  still one atomic call of the whole remaining list. K=1, the common case, costs 2 calls, the
  same as before #510.
- **From the second bad image on, the list splits** at the start of `ast_to_requests`'s trailing
  descending-position `insertTable`/`insertInlineImage` pass (`_positional_insert_tail_start`).
  The prefix (text, styles, bullets) is committed once on its own, and only the small tail is
  retried per further bad image. That boundary is the only safe split point: every prefix
  request must run before any positional insert, while within the tail each insert lands at or
  before every insert already applied, so dropping one never shifts the rest.
- **Residual partial-write window (K≥2 only):** once the prefix has committed, a tail retry that
  fails for a *non*-image reason raises with the text already in the doc but no tables or
  images, and `fill_tables` never runs.
- **Fail-safe:** the tail boundary is inferred from request kinds, so it silently depends on
  `ast_to_requests` emitting nothing after its positional-insert pass (pinned by a unit test).
  If any image request is found outside the inferred tail, the retry never splits and falls
  back to whole-list retries.

Confirmed live that the split produces a document structurally identical to the old
whole-list retry (text, bullets, table, and the surviving image all in place).

## Linked images (#977)

An `<img>` inside `<a href>` (markdown `[![alt](src)](url)`) keeps its link: `html_parser.py`
copies the open `<a>`'s href onto `Image.link_url`. That includes raw HTML with no enclosing
block: a top-level `<img>` gets an implicit paragraph even when it's wrapped in inline tags (unlike
bare text or `<hr>` in that position), and reads its link from `_bare_link_url`, a stack separate
from `_link_url` so text handling and an unclosed top-level `<a>` are unaffected. Each open `<a>`
records which of the two stacks it pushed onto, or that it pushed nothing (`_anchor_pushes`), and
its `</a>` pops only that: an href-less `<a name>` nested in a linked anchor used to pop the outer
link (#994, PR #992 QA round 2). Docs stores an image's link on its
`inlineObjectElement`'s own `textStyle.link`, so `emitter.py` follows the image's
`insertInlineImage` with an `updateTextStyle` over its one-character range
`[position, position + 1)`. The link has to come right after its own insert, inside the
descending-position tail: at that point nothing before `position` has shifted yet. An inserted
image never inherits a neighboring run's link (confirmed live, both directions), so an unlinked
image gets no clearing request.

Inserts that share a position, such as adjacent images with nothing between them, each land in
front of whatever is already there, so the later one in the document has to be inserted first.
The descending pass sorts on `(position, node order, item order)`, all descending; sorting by
position alone kept source order within a tie and wrote adjacent images reversed (PR #992 QA
round 1). A table and the image right after it share a position the same way, and still come out
table first.

The retry treats the pair as one unit. `ast_to_requests(image_links=...)` records each
`id(insert request) -> link request` as it builds them, and `_apply_doc_content` uses that record
rather than matching request shapes. `_drop_failed_image` pops the link request with its failed
insert, since a stranded link would land on whatever character now sits at that position.
`_positional_insert_tail_start` counts a recorded link request as part of the tail, so the K≥2
split still applies. A `#slug` image link goes
through the heading-anchor pass like a text link: `_walk_headings_and_anchor_runs` reads the
`inlineObjectElement`'s link too, so it's resolved or stripped.

## Table-cell images (#1073)

#333 shipped body-level images only: the parser dropped an `<img>` in a cell, with no error and
no `images` entry. Table cells aren't written in phase 1. `fill_tables` fills them afterwards
from live indices, so a cell image goes in during that fill, not in `ast_to_requests`'s
positional pass.

- **Parser.** An `<img>` in a cell joins `Cell.children` in source order, with its `<a>` link,
  the same as in a block. A nested `<table>` already flushed the open cell's pending runs into
  the outer cell before it started, so an image keeps its place on either side of a nested table.
  A source line break and the indentation around it (`<td>\n  <table>`) is held rather than
  written, and becomes one space only if content follows it in the cell, as a browser renders
  it; kept as text, it became empty paragraphs before a nested table (PR #1215 QA round 1). A
  `<br>` still breaks the line.
- **Resolution.** `extract_images` walks cells too, nested tables included, in document order.
  Cell images are uploaded, shared and revoked with the body's, through the same
  `ImageShareLifecycle`, and get the same `images` entries.
- **Placement.** The fill gets the resolved URIs as an `emitter.CellImages`. Each contiguous
  run of a cell's text and images (`_run_group_fill_requests`) inserts its text and styles as if
  no image were there, then each image at the offset of the text before it, latest first, like
  the body's descending pass. Images that share an offset (no text between them) therefore come
  out in source order, and none shifts another. A linked image's `updateTextStyle` follows its
  insert, as in the body.
- **Nested tables.** A nested table goes in at its paragraph's start plus everything already
  inserted before it in that paragraph, so `_text_offset_since_last_table` counts each image as
  one index. It counts only an image still in `CellImages.uris`: one that never resolved, or
  whose insert failed, isn't in the doc.
- **Unfetchable images.** When there are cell images, each fill `batchUpdate` goes through
  `CellImages.execute`. On an image-fetch error it drops that image and its link, removes it from
  the URIs, tells `_apply_doc_content` (which records the error on the image's entry), and
  resends. Dropping one never moves another request: within a cell the images go last, latest
  first, and cells run latest first. As in the body (#510), the first retry resends the whole
  batch; from the second failure on, the batch splits at the failed image, the requests ahead of
  it are sent on their own, and only the rest is retried. A `batchUpdate` applies its requests in
  order, so sending `L[:i]` and then `L[i:]` does what sending `L` would. A split anywhere else
  is wrong: sending every cell's text first and the images after (the body's prefix/tail split)
  moves each later cell's image by the length of every earlier cell's text.
- **Retry bookkeeping.** `CellImages` maps each insert it built to its image and link, holding
  the request dicts themselves, and clears the map once that batch settles. Keyed on `id()`
  alone, a freed insert's key outlived it, and a later batch's insert could be allocated at the
  same address and pick up the stale link (PR #1215 QA round 1). The body's maps don't need this:
  `content_requests` keeps their requests alive.
- **Images the fill never placed.** A cell the fill can't locate in the live doc gets no insert.
  `CellImages.embedded` records every image whose insert went out in a batch that succeeded, and
  `_apply_doc_content` gives any other resolved cell image an `error`, since it was uploaded and
  shared and would otherwise read as embedded.

Confirmed live (2026-10-24, two runs): text around an image, an image-only cell, a linked image,
an unreachable URL (dropped and reported, rest of the table intact), a local upload (share
revoked afterwards), an image on each side of a nested table and one inside it, and Markdown
pipe-table cells with one and two images. `get_doc_as_markdown` reads them back.
