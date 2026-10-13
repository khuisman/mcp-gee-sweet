# Design: Google Doc Revisions as Markdown (`export_revision`)

**Status:** Implemented. Issue #959. Live-verified against real Drive/Docs API calls via scratch
scripts per `CLAUDE.md`'s "Verify a ticket's API premise live" convention (2026-10-11).

## Problem

`export_revision` handled only Sheets (XLSX export → cell values). `list_revisions` already
listed Doc revisions, but nothing could read one, so "what changed in this Doc since revision N"
couldn't be answered through the server. The issue asked for a Doc revision as Markdown "through
the same converter `get_doc_as_markdown` uses", so that diffing two revisions' exports shows only
the edit.

## The constraint

`get_doc_as_markdown` walks `documents().get()` into the AST (`doc-to-markdown.md`). The Docs API
reads only a document's **current** state; it has no revision parameter. Drive is the only source
of an old revision, and only as a file from the revision's `exportLinks`. Measured on a Doc
revision: `text/markdown`, `text/x-markdown`, `text/html`, `text/plain`, DOCX, ODT, RTF, PDF, EPUB,
and a zipped HTML.

## Options measured

Each option was run against the same Doc, written through `write_doc_content` with headings, bold
and italic, inline code, a fenced code block, a blockquote, nested ordered/bulleted lists, task
items, a table, an image, and heading links.

1. **Drive's own `text/markdown` export.** Lossy: inline code became plain text, the fenced code
   block became soft-broken plain lines, the blockquote became a plain paragraph, a nested bullet
   inside a numbered list became a separate numbered item with a literal `\-`, and the image was
   inlined as a base64 `data:` URI (10KB for one small logo). It's a different dialect from
   `get_doc_as_markdown`, and a much less faithful one.
2. **`text/html` export → this project's `html_parser` → AST.** Google's export carries styling in
   CSS classes (`.c3{font-weight:700}`), which `html_parser` doesn't read, so bold, italic and code
   fonts would be lost without a CSS resolver. Importing that HTML back into a Doc (to reuse the
   Docs-side converter) was also measured: it split the code block into one fence per line and
   turned every list item after the blockquote into a quote.
3. **DOCX export → import as a temporary Google Doc → `document_to_ast` → `ast_to_markdown`.**
   The output was **identical** to `get_doc_as_markdown` on the live Doc, except for the two
   import-specific values below. The zipped-HTML export can't be imported (400).

**Chosen: (3).** It is the same converter, not an equivalent one, so everything
`get_doc_as_markdown` supports and documents carries over unchanged.

## What differs on every import, and how it's made stable

Measured across two imports of the same DOCX:

- **Inline image `contentUri`.** A new URL each import; the image bytes are identical (same
  SHA-256). `_stabilize_images` fetches each image (concurrency 8) while the temporary Doc still
  exists and replaces its `contentUri` with `image:sha256-<first 16 hex digits>`, so an unchanged
  image doesn't show in a diff and a changed one does. A failed fetch renders
  `image:unavailable`. No viewable URL is returned: PR #988's QA round found the temporary Doc's
  image URLs 404 (anonymously and authenticated) once it's deleted, so a returned URL would be
  dead on arrival. (One earlier probe got a 200 right after deletion; it doesn't hold.)
- **Heading IDs and the document ID.** Every heading gets a new `headingId`, and
  `doc_to_ast._link_url` rebuilds an ID-only heading link (the kind the Docs UI creates) as a URL
  containing the temporary Doc's ID. That changes on every export and points at a deleted Doc.
  `_stabilize_internal_links` rewrites a heading link to `#<slug>`, using anchors.py's GitHub-style
  slug with `-1`/`-2` duplicate suffixes, so the link survives a round trip through the write
  side's anchor resolver. The slug list holds only paragraphs that render as Markdown headings,
  classified by `doc_to_ast._paragraph_to_node` itself (`Heading`, or a TITLE/SUBTITLE
  `NamedBlock`): a bulleted heading renders as a list item and a heading in a table cell as cell
  text, and counting them shifted every later duplicate's suffix onto the wrong heading (PR #988
  QA round 1). A link to a heading that doesn't render as one is dropped, following the project's
  rule that a wrong link is worse than none.
- **Bookmark links are dropped.** A bookmark has no text to name it, and any `#fragment` made up
  for one can be fuzzy-matched by `anchors.py` to a heading when the Markdown is written back
  (`#bookmark-1` → the second heading titled "Bookmark"; PR #988 QA round 1).
- URL links written by this project's own write side are already absolute URLs and pass through
  unchanged.

## The temporary Doc

- Where it's created depends on the identity (#989), because the copy holds the revision's full
  content and the default folder's audience can differ from the source Doc's:
  - A user identity (OAuth, or ADC with user credentials) creates it in My Drive root, not the
    default folder, so only the user can see it.
  - A service account identity (`lc.is_service_account_identity`) creates it in the default
    folder (`lc.folder_id`). A service account has no My Drive storage, so only a configured
    Shared Drive works. The remaining exposure is documented in `docs/known-limitations.md`: the
    Shared Drive's members can open the copy while the export runs, a Content manager's copy sits
    in the trash for 30 days, and a failed cleanup leaves it live.

  Rejected alternatives: the source Doc's parent folder matches the source's audience more
  closely, but the identity may not be able to write there. Restricting the copy's permissions
  after creation can't work on a Shared Drive, where member access is inherited. A
  storageQuotaExceeded error renders with the shared `_SA_QUOTA_ERROR` text.
- Uploaded resumable: Drive takes a multipart upload only up to 5 MB, and a revision with
  embedded images can exceed it.
- Named `export_revision temp (<file_id> r<revision_id>)`, so an orphan is identifiable.
- Created inside `anyio.CancelScope(shield=True)`, per `CLAUDE.md`'s cancellation rule: a
  cancellation can't land after Drive created the Doc but before its ID is recorded.
- Removed in a shielded `finally`: deleted when `capabilities.canDelete` allows it, else trashed
  (a Content manager on a Shared Drive can only trash, #876). The removal retries a 5xx or 429
  (`num_retries=3`), since a failed removal leaves a copy of the revision in Drive. A failed removal
  never hides the export: the result gets a `warning` naming the Doc's ID.
- Because it writes to Drive, `export_revision` is no longer annotated `readOnlyHint`; it's
  `destructiveHint=False`, since it changes nothing of the caller's.
- About 5–6 seconds per call, measured, on top of the image fetches.

## Errors found while measuring

- The export endpoint answers rapid calls with HTTP 429 and an HTML page, without raising. The
  Sheets path handed that page straight to openpyxl. `_fetch_revision_export` checks the status
  for both paths.
- Docs folds the latest revision into the next one while editing continues: revision 18 was
  listed, an edit 90 seconds later produced 19, and 18 then returned 404. A second run with a
  5-minute gap merged 19 into 20 the same way. `export_revision` turns a "Revision not found" 404
  into an error telling the caller to call `list_revisions` again. Any other 404, such as a bad
  file ID ("File not found"), is re-raised unchanged. A Doc created by Drive import keeps its
  import revision separate (as #814 measured).
- `revisions.list` returns at most 200 revisions per page by default (discovery document), and
  `list_revisions` read only the first page. It now pages through every revision via the same
  `_list_revisions` helper `sync_folder` uses.
- A Doc `local_path` is checked with `response_limits.validate_local_destination` before the export, so a bad
  destination fails before the temporary Doc round trip.

## Live verification

Against a Doc imported through `upload_file(convert_to_doc=True)`, then edited by inserting one
word: exporting revision 1 (the import) and revision 2 and diffing the two `markdown` values gave
exactly one changed line, the edited paragraph. On a `write_doc_content` Doc with every construct
above plus two `Setup` headings linked by ID, the export matched `get_doc_as_markdown` except the
image line and the two links (`#setup`, `#setup-1`). With the first `Setup` bulleted, it rendered
as `- Setup`, the link to it was dropped, and the link to the second rendered as `#setup`.

## What this does NOT do

- **Comments.** They aren't part of a revision, so there's no `include_comments`.
- **Match `get_doc_as_markdown` byte for byte.** Heading links and images differ by design (above).
  Diff a revision against another revision's export, not against the live Doc's
  `get_doc_as_markdown`.
- **Show an old revision's images.** Only their hashes; see above.
- **Multi-tab documents: not measured.** How Drive's DOCX export handles a Doc's extra tabs
  wasn't checked; `document_to_ast` reads only the imported Doc's body.
