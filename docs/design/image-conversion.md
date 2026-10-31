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

`ast_to_requests` stays fully synchronous (no network I/O) by taking an
`image_uris: dict[id(image), str]` map rather than doing any resolution itself. An `Image` with
no entry in that map is silently omitted — the same graceful-degradation behavior any other
unsupported construct already gets from this parser.

Since #1240, `content._convert_doc_content` builds the requests *before* any image resolves, so
a conversion that fails or is cancelled never reaches the doc. It collects every `Image` with
`extract_images(nodes)` and passes a unique placeholder URI for each one. `_apply_doc_content`
then resolves the images and swaps each resolved image's placeholder for its real URI. An
unresolved image's `insertInlineImage` request is replaced by its fallback text (below), and its
link request goes, since the fallback carries the link. Its insert sits in the descending-position
tail, so text at that position shifts none of the requests still to come
(`test_unresolved_images_requests_match_their_fallback_text` pins this).

## Fallback text for an image that isn't embedded (#1099)

An image Docs can't embed used to disappear: an SVG badge (`img.shields.io` serves SVG, which
Docs doesn't take), an unreachable URL, a missing local file, a failed share. A README's badge
line became an empty paragraph, its link gone too. Now `emitter.image_fallback_requests` writes
`image_fallback_text(image)` where the image would have gone: its alt text with whitespace
collapsed, else the last segment of its source (a URL's path segment, percent-decoded; a local
path's file name, never the whole path, so a server path doesn't land in the doc; nothing for a
`drive:` ID), else `image`. Alt text that's empty wouldn't help a reader find what's missing.

- **One request pair, either way.** An `insertText` at the image's position, then an
  `updateTextStyle` with `fields: "link"`: the image's link (through `_storable_link_url`, the
  text-link rule), or, for an unlinked image, cleared. Inserted text takes the style of the
  character before it, a link included, which an inserted image never does (#977). Its other
  inherited styles stay, so it reads like the text around it.
- **Where it applies.** An image that didn't resolve (`_apply_doc_content`, before the first
  batch), and one Docs couldn't fetch at the embed step (`_drop_failed_image` in the body,
  `CellImages._drop` in cells), which now replace the failed insert in place instead of popping
  it. Either way the text goes at the image's own position in the descending tail, so no request
  after it moves, the same argument that made dropping safe.
- **The K≥2 split.** `_positional_insert_tail_start` takes the fallback requests' ids
  (`fallback_ids`), so a fallback inside the tail doesn't cut the scan short and fall back to
  whole-list retries.
- **Reporting.** The image's `images` entry keeps its `error` and gains `fallback_text` once
  the batch carrying the text has landed: `send_dropping_failed_images`'s `on_applied` for the
  body, and `CellImages.shown_as_text` for cells. A batch that fails for another reason leaves
  it out.
- **Not in a heading (PR #1310 QA round 1).** The anchor pass reads a heading's text from its
  runs, so fallback text there joins the heading's own: `# MyProj ![build](svg)` became
  "MyProj build", and `[Go](#myproj)` lost its link (`no_matching_heading`). GitHub leaves image
  alt text out of a slug, so a README's TOC is written against the heading without it. An image
  in any paragraph the anchor pass reads as a heading (any named style but `NORMAL_TEXT`:
  `Heading`, a `BulletItem` with `heading_level`, a TITLE/SUBTITLE `NamedBlock`;
  `emitter.heading_image_ids`, recorded on `ConvertedContent.heading_image_ids`) is dropped as
  before #1099, with its link request, and reported by its `error` alone.
- **One tracker.** `emitter.ImageFallbacks` builds every fallback (computing each image's text
  once), records its request ids for the tail scan, and moves an image into `shown` from the
  `on_applied` of the batch that carried it. The body's retry and `CellImages` share the one
  instance `_apply_doc_content` makes, so both report `fallback_text` the same way.
- **Source kinds.** `ast.image_source_kind` is the one classification (URL, `drive:`, `data:`,
  local path), used by `_resolve_image_source`, the replace's folder check, and the fallback
  text. A `data:` URI (markdown-it lets `data:image/...` through) is an error, since Docs takes
  an image only by URL, and its fallback is its alt or "image", never its base64.
- **What it doesn't cover.** `insert_inline_image` and `insert_local_images` insert one image
  the caller named at an index, and still fail outright: there's no source text to stand in for.

## Where a local image comes from and goes (#1121, #1139)

- **Relative paths.** `create_doc_from_file` and `update_doc_from_file` pass the file's folder
  as `source_dir`, and `_local_image_path` joins a relative `src` to it, as a README's images
  are relative to the README. It's the caller's spelling of the folder (`Path(local_path).parent`),
  not the resolved one, so a symlinked file's images are found next to the link. The joined path
  goes through `check_read` like any other (#796). Content passed as a string (`create_doc`,
  `write_doc_content`, `upload_file`) has no file, so a relative path there stays relative to the
  server's working directory.
- **Upload folder.** A local image goes to `folder_id` (the tool's, else the server's default),
  else the doc's own folder (`_image_folder`). For the create tools that's the new doc's parent,
  which Drive reports even for My Drive's root. For the replace tools (`write_doc_content`,
  `update_doc_from_file`, which now take `folder_id` too), `_replace_doc_content` looks the doc's
  parents up only when the content has a local image this server would upload and no folder was
  given (`_uploadable_local_image`: the access policy allows reading it and it's a file). A doc
  shared from a folder the account can't see has no parents, and a failed lookup (a 403, a 5xx)
  has none to offer: either way the call refuses with `{"error", "docId"}` before the backup copy
  and the clear, since replacing would drop every such image (the #1139 report: a successful call
  that left the doc without its images). A local image that can't be read anyway (missing, or
  refused by `LOCAL_FILE_ACCESS`) doesn't cause the refusal: a folder wouldn't help it, and it's
  written as its alt text (PR #1310 QA round 1).
- **One body for the create tools.** `create_doc_from_file` calls `_create_doc_with_content`
  with `source_dir`, like `create_doc` and `upload_file`, so the image-folder fallback lives in
  one place.

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
and strips exactly that request (since #1099, replaces it with the image's fallback text; see
below). The dropped image's outcome `error` is built from that same
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
  A run of whitespace holding a line break at a segment's edge (the cell's start or end, or
  either side of a nested table, as in `<td>\n  Intro\n  <table>`) is dropped, whether its text
  chunk is whitespace-only or not; kept, it became empty paragraphs around a nested table (PR
  #1215 QA rounds 1 and 3). At the segment's start it's dropped as it arrives. At the end of
  the text so far it's held, as a run with the style and link it was typed under, and written
  only if more content follows, so everything else in a cell parses as before. Nothing inside a
  cell's `<pre>` is trimmed. Collapsing every source line break instead (round 1's fix) merged a
  cell's `<p>`s and a `<pre>`'s lines, which Docs keeps as separate lines (round 2). Whether a
  newline inside cell text should collapse as a browser renders it is #1221.
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
  inserted before it in that paragraph, so `_text_offset_since_last_table` counts what each
  image took (`CellImages.doc_length`): one index for an embedded image, its fallback text's
  UTF-16 length for one written as text (#1099).
- **Unfetchable images.** Every fill `batchUpdate` goes through `CellImages.execute`, which
  `fill_tables` requires, so there's one send path. On
  an image-fetch error it replaces that image's insert with its fallback text and drops its
  link, removes it from the URIs, tells `_apply_doc_content` (which records the error on the
  image's entry), and resends. An image that never resolved gets its fallback text from the
  start. The replacement never moves another request: within a cell the images go last, latest
  first, and cells run latest first. The loop is `batch_retry.send_dropping_failed_images`, which the body's retry
  uses too; the two differ only in where they split. As in the body (#510), the first retry
  resends the whole batch; from the second failure on, the batch splits at the failed image, the
  requests ahead of it are sent on their own, and only the rest is retried. A `batchUpdate`
  applies its requests in order, so sending `L[:i]` and then `L[i:]` does what sending `L` would.
  A split anywhere else is wrong: sending every cell's text first and the images after (the
  body's prefix/tail split) moves each later cell's image by the length of every earlier cell's
  text.
- **Retry bookkeeping.** `CellImages` maps each insert it built to its image and link, holding
  the request dicts themselves, and clears the map once that batch settles. Keyed on `id()`
  alone, a freed insert's key outlived it, and a later batch's insert could be allocated at the
  same address and pick up the stale link (PR #1215 QA round 1). The body's maps don't need this:
  `content_requests` keeps their requests alive.
- **Images the fill never placed.** A cell the fill can't locate in the live doc gets no insert,
  and after a split, the head of a batch lands before the rest can fail for another reason (a
  5xx, say). `CellImages.embedded` grows as each batch lands, the head of a split included, and
  `_apply_doc_content` gives every other resolved cell image an `error`, since it was uploaded
  and shared and would otherwise read as embedded: after the fill, and on any `Exception` out of
  the edit, including a phase-1 failure before the fill starts. A cancellation is left alone: a
  cancelled `execute_in_thread` batch still runs to completion, so its images may yet land.

Confirmed live (2026-10-24, two runs): text around an image, an image-only cell, a linked image,
an unreachable URL (dropped and reported, rest of the table intact), a local upload (share
revoked afterwards), an image on each side of a nested table and one inside it, and Markdown
pipe-table cells with one and two images. `get_doc_as_markdown` reads them back.
