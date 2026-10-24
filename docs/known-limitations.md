# Known Limitations

Constraints imposed by the Google Docs/Drive/Sheets APIs or by current implementation scope.
Each entry describes what the limitation is, why it exists, and the available workaround (if any).

---

## Google Docs

### Setting a named style clears the paragraph's inline text styles

**What:** Writing a `namedStyleType` onto a paragraph that already has inline text
styles removes those styles - reproduced with `strikethrough`, and it happens even when
the named style being written is the one the paragraph already had.

**Why:** The Docs API's `updateParagraphStyle` with a `namedStyleType` re-applies the
named style's own text properties to the paragraph's runs, so per-run formatting is not
preserved. It is API behaviour rather than a quirk of this server's request building.

**Where it bites:** `style_doc_range(named_style_type=...)`, and
`insert_softbreak_paragraph`, which sets the style explicitly for the whole block. The
v0.9.2 release QA pass reproduced it three times, including a control that set no other
style fields.

**Workaround:** Set the named style first, then apply the text styles in a second
`style_doc_range` call carrying only text-style fields. Setting text styles alone never
takes the `namedStyleType` path.


**What:** A blank paragraph always appears in the document structure immediately before each
table, even when none was written in the source HTML/Markdown.

**Why:** `insertTable` is a structural Docs API operation that requires at least one paragraph
before the table. When phase-1 `insertText` is used to write document content, it displaces the
document's initial empty paragraph to the position just before the table. Attempting to remove
this paragraph via `deleteContentRange` is rejected by the API ("Invalid deletion range") because
the paragraph is a required structural element — even though the Google Docs UI allows the
equivalent manual deletion.

**Workaround:** The emitter collapses the blank paragraph to zero visual height using
`updateParagraphStyle` (`spaceAbove/spaceBelow = 0`, `lineSpacing = 1`) and `updateTextStyle`
(`fontSize = 1pt`). The paragraph remains in the document structure but is invisible in the
rendered output. The one exception is a paragraph between two tables: it keeps its height, as
the blank line that keeps the tables from touching and reading as one (#1098). Every such
paragraph also loses any bullet, indent, or border it took from the block after the table
(#1097). Related: #190.

---

### `get_doc_structure` — top-level body elements only

**What:** `get_doc_structure` reports elements in the document body at the top level only.
Content inside nested table cells (tables within table cells) is not exposed.

**Why:** The tool walks the body content array one level deep. Deeply nested structures require
recursive traversal that is not currently implemented.

**Workaround:** For inspecting nested cell content, fetch the raw document via the Docs API
`documents.get` endpoint (accessible via `batch_update` passthrough or by reading the raw API
response). Related: #133.

---

### Nested tables not supported via Markdown input

**What:** Markdown content passed to `create_doc`/`write_doc_content` (`content_format='markdown'`)
or `create_doc_from_file` (`.md` files) cannot produce a nested table — a table inside a table
cell.

**Why:** The Python `markdown` library's `tables` extension has no syntax for a table nested
inside another table's cell.

**Workaround:** Supply raw HTML instead — the HTML→AST pipeline fully supports nested tables
(see #109). Related: `docs/qa/tests/docs_content.md` TC-DOC51.

---

### A bare `-` line is never recognized as an empty list item

**What:** In Markdown input, a line containing only `-` (optionally with trailing whitespace) is
never recognized as an empty list item, regardless of indentation. What happens instead depends
on what precedes it:

1. **As the first line of a would-be list** (e.g. right after a heading, as in the
   `tc-doc106-nested-lists-4space.md` fixture's Case 2 — a bare `-` meant to hold only a nested
   sub-list): the whole block, including the following well-formed list-item lines, collapses
   into a single plain paragraph of literal text. No list is produced at all.
   `"-\n- item two\n- item three\n"` → `<p>-\n- item two\n- item three</p>`.
2. **Immediately following a text line** (e.g. `"- item one\n-\n- item three\n"`): it's instead
   consumed together with the preceding line as a Setext-style H2 heading, since a line of only
   `-` characters is also CommonMark/Setext heading-underline syntax. Renders
   `<h2>- item one</h2>` followed by a list containing only `"item three"` — the first item's
   bullet and the empty second item are both silently lost.

**Why:** This is a Python `markdown` library parsing-priority issue, not something this
project's own HTML→AST pipeline controls. The list-item regex (`sane_lists` and core alike)
requires a marker *and* a space *and* content (`"- "` + text) to recognize a line as a list item
— a bare `-` with nothing after it never matches, so it falls through to whatever else can claim
the line: ordinary paragraph continuation (case 1) or the core block processor's Setext-heading
check, which runs before list-continuation logic gets a chance to treat the line as a (would-be
empty) list item (case 2). This fires regardless of indentation and is distinct from the
`sane_lists` indentation-threshold defect (2- and 3-space nested lists don't nest; see
`docs/qa/tests/docs_content.md`'s TC-DOC105 and `docs/qa/tests/docs_markdown.md`'s TC-MD106,
tracked in #1071) — that bug is about sub-list nesting depth, not this marker-recognition
gap. Working around this by changing how bare markers or Setext headings are
parsed would change behavior for every other document using either construct, a much larger and
riskier change than this narrow, low-frequency edge case (an intentionally empty list item)
warrants.

**Workaround:** Give the list item a non-breaking space instead of a bare `-` (i.e. `- ` followed
by U+00A0) — python-markdown parses this as an ordinary, genuinely empty list item (`<li></li>`)
in both contexts above. Confirmed via direct execution of `_md_to_html` — a local, offline
markdown→HTML conversion, not a live Google API round trip. CommonMark does allow an empty list
item, so this stays open as #1075 (#692, closed, is the earlier triage). Related:
`docs/qa/tests/docs_markdown.md` TC-MD301.

---

### Images inside table cells are dropped

**What:** An image in a table cell (Markdown `| ![alt](src) |` or HTML `<td><img …></td>`) is
dropped: the cell renders empty, and the call reports no error and no per-image entry under
`images`.

**Why:** Image support (#333) covers body-level images only. The table fill
(`emitter.py`'s `_fill_children_recursive`) has no handling for an `Image` among a cell's
children, so the parser drops it before it gets there.

**Workaround:** Insert the image into the cell afterwards with `insert_inline_image`, at the
cell's `paragraphStartIndex` from `get_doc_structure`. Tracked in #1073;
`docs/qa/tests/docs_markdown.md` IM-09 and `docs/qa/tests/docs_content.md` TC-DOC102/TC-DOC153
cover it.

---

### `create_bookmark` doesn't create a bookmark Docs lists

**What:** `create_bookmark` creates a one-character named range. It doesn't appear under
Insert > Link > "Headings, bookmarks, and tabs", and no link can point to it.

**Why:** The Docs API has no request that creates a bookmark; only the Docs UI can.

**Workaround:** Link to a heading instead: every heading has a `headingId` (`get_doc_structure`)
that a link can target. Tracked in #1076.

---

### `get_doc_as_markdown` — nested tables, temporary image URLs, and inline-vs-block code ambiguity

**What:** `get_doc_as_markdown` (#300) has three read-side gaps, each rooted in a genuine
Markdown-format or Docs-API constraint rather than missing implementation:

1. A table nested inside another table's cell has no Markdown table syntax to express — the
   mirror image of the write-side limitation above. That cell renders a placeholder note
   (`*(nested table omitted...)*`) instead.
2. An inline image resolves to Drive's temporary `contentUri`, which expires (roughly 30
   minutes). The exported Markdown's `![alt](url)` links go stale if consumed well after
   generation.
3. Both inline code (`` `x` ``) and a fenced code block (` ```...``` `) are written to the Docs
   API identically — a run (or every run in a paragraph) with `font_family="Courier New"` — see
   `docs/design/markdown-support.md`'s mapping table. There is no other marker to tell them
   apart on read. `get_doc_as_markdown` treats a paragraph as a fenced block only when *every*
   run in it is code-styled; a paragraph containing nothing but a single inline code span (no
   surrounding text) is indistinguishable from a one-line code block and renders as a fenced
   block either way. An all-code paragraph with a linked run renders as inline code spans
   instead, since a fenced block can't carry a link.

**Why:** (1) and (3) are Docs-representation-level ambiguities, not gaps in this tool's
traversal; (2) is inherent to how Drive serves inline image bytes.

**Workaround:** For full fidelity on any of these three cases, use `get_doc_structure` (or the
raw Docs API via `batch_update` passthrough) instead. Related: docs/design/doc-to-markdown.md.

---

### `export_revision` on a Google Doc — links, images, and vanishing revision IDs

**What:** `export_revision` (#959) returns a Doc revision as Markdown through the same converter
as `get_doc_as_markdown`, with these differences and gaps:

1. A link to a heading renders as a GitHub-style `#slug` anchor, not as a docs.google.com URL.
   A link to a bookmark, or to a heading that doesn't render as one (a bulleted heading, or one
   in a table cell), is dropped and leaves its text. An image renders as
   `image:sha256-<hash>`, with no viewable URL: the temporary Doc's image URLs stop working
   once it's deleted, so an old revision's images can't be viewed this way.
2. The export doesn't include comments, which aren't part of a revision.
3. A revision ID from `list_revisions` can stop existing: Docs folds a recent revision into the
   next one while editing continues (measured: edits 90 seconds and 5 minutes later both merged it).
   The export then fails with an error saying to list revisions again.
4. Each call creates and removes a temporary Google Doc holding the revision's full content,
   which takes several seconds. A user identity (OAuth, or ADC with user credentials) creates it
   in My Drive root, not shared with anyone. That needs room in My Drive and permission to
   create files there, even when `DRIVE_FOLDER_ID` is a Shared Drive with room: a full My Drive,
   or a Workspace policy that blocks creating files in My Drive, makes the export fail. A service
   account has no My Drive storage, so it uses the default folder, which must be a Shared Drive.
   The source Doc's own sharing doesn't limit who can see that copy:
   - Every member of the Shared Drive can open it while the export runs, including the image
     downloads.
   - A Content manager can only trash it, not delete it, so it stays in the Shared Drive's
     trash for 30 days, where the drive's managers can see it.
   - If removal fails, the copy stays live, and the result's `warning` names the Doc to delete
     by hand.

**Why:** The Docs API reads only a document's current state, so the revision is exported as DOCX
and imported into a temporary Doc to be read. That Doc's ID, heading IDs, and image URLs are new
on every import, so (1) replaces them with values that stay the same between exports and keep
diffs clean. A bookmark has no text to make a stable anchor from, and an invented one could be
matched to the wrong heading if the Markdown is written back. (3) is how Drive keeps Docs
revision history. (4) follows from that import: a service account can create files only in a
Shared Drive, and member access there is inherited, so the copy's permissions can't be narrowed.

**Workaround:** For (1), diff one revision's export against another's, not against
`get_doc_as_markdown` output. For (3), export a revision only after editing has settled. For
(4), when a revision's content shouldn't reach the Shared Drive's members, export it with a user
identity (OAuth), or point `DRIVE_FOLDER_ID` at a Shared Drive whose membership matches the
source Doc's audience.
Related: docs/design/doc-revision-export.md.

---

## Google Drive

### Service account cannot create files in personal Drive

**What:** When authenticated as a service account (`AUTH_METHOD=service_account`), tools that
create new files (`create_doc`, `create_doc_from_file`, `create_spreadsheet`) will fail with a
permission error if the target folder is in a personal Google Drive.

**Why:** Service accounts have their own Drive storage quota separate from any user's personal
Drive. They can only create files in shared drives or in folders explicitly shared with the
service account.

**Workaround:** Manually create the file in Drive and share it with the service account, then
use `write_doc_content` or `update_cells` to populate it. Alternatively, use OAuth authentication
(`AUTH_METHOD=oauth`) which authenticates as the user and has full personal Drive access.
Related: project memory `service_account_limit`.

### `sync_folder` — renaming a long-named `convert_markdown` Doc in Drive unlinks it

**What:** `sync_folder(convert_markdown=True)` normally keeps matching a converted Doc to its
local `.md` file even after the Doc is renamed in Drive. That doesn't hold for a `.md` filename
longer than 103 UTF-8 bytes, `.md` included: 101+ ASCII characters, or 34+ CJK characters,
before the `.md`. (Drive's 124-byte cap, minus the 21-byte `geeSweetConvertSource` key.)
Names of 103 bytes or less still survive a rename. If a Doc converted from a longer name
is renamed in Drive, the next sync no longer recognizes it. The local file then reads as "local
only" and is uploaded again as a new Doc, and the renamed one is left as an ordinary,
unrelated Doc.

**Why:** `sync_folder` records the source filename in a Drive custom property, and Drive caps
each property's key + value at 124 bytes. A name too long to fit is stored as a `sha256:`
digest, which can't be read back. The source name is then taken from the Doc's own display
name, which keeps its `.md` suffix, and checked against the digest. After a rename, the two no
longer agree (#805).

**Workaround:** Don't rename these Docs in Drive. To change the name, rename the local file and
delete the old Doc in Drive; the next sync converts the file again under its new name. Renaming
both sides to the same new name doesn't restore the link, because the digest still records the
old name.

### `sync_folder` — a `convert_markdown` Doc edited in Drive needs a manual resolve

**What:** Once a converted Doc is edited in Drive, every `sync_folder` run reports it under
`conflicts`, including after the local `.md` is edited too. Editing or touching the local file
doesn't clear the conflict. Clearing it takes a call that names the Doc in `resolve`.

**Why:** There's no reverse conversion (Doc → Markdown), so the Drive edit can't be downloaded,
and uploading the local file would overwrite it. `sync_folder` used to do that silently and now
refuses (#814), so which side wins is the caller's choice.

**Workaround:** Name the Doc in `resolve`. The right choice depends on whether the local file has
edits of its own:

- **Only the Doc was edited:** copy the Drive edits into the local `.md` by hand, so the two
  match, then sync with `resolve={"<name>": "keep_drive"}`. Nothing in Drive changes.
- **Both were edited:** merge the Drive edits into the local `.md`, then sync with
  `resolve={"<name>": "keep_local"}`, which uploads the merged file in place. Don't use
  `keep_drive` here. It records the local file as matching the Doc, so its own edits would never
  reach Drive.
- **To discard the Drive edit:** sync with `"keep_local"` without merging. The edit stays in
  the Doc's version history.

Either way the Doc keeps its file ID, sharing, comments, and links. Preview the call with
`dry_run=True` first.

### `sync_folder` — a `convert_markdown` Doc from before #814 can stay stuck in `conflicts`

**What:** A converted Doc created before #814 has none of the properties #814's change
detection uses, so it stays on the old `modifiedTime` comparison until it's next re-uploaded. If
Drive's late `modifiedTime` update overwrote its restamp (the bug #814 fixed), it reads as
"Drive newer" and is reported under `conflicts` on every sync. A conflict never uploads, so it
never picks up the properties that would fix it.

**Why:** Migrating such a Doc means choosing a baseline revision for it. While it reads as Drive
newer, `sync_folder` can't tell a lagging timestamp from a real Drive edit, so it doesn't guess.

**Workaround:** Sync once with `resolve={"<name>": "keep_drive"}`. That stamps the properties
without changing the Doc's content, and from then on the Doc uses the new detection. Use it only
when the local file matches the Doc: if the Doc *was* edited in Drive, copy those edits into the
local file first. If the local file has edits of its own, merge and use `"keep_local"` instead,
which re-uploads in place and stamps the same properties.

### Downloads and `sync_folder` skip names that aren't a single filename

**What:** Drive allows `/` in a file or folder name, and a name of `.` or `..`. `download_file`
(with a directory as `local_path`), `download_folder`, and `sync_folder` refuse such a name
instead of writing it, and report it under `failed` (`download_file` raises an error). A name
containing `\` is refused too, on every OS. That includes a local file or folder whose name
contains `\`, which macOS and Linux allow: `sync_folder` won't upload it.

**Why:** A Drive name is used as the local filename. One that isn't a single ordinary filename
would land somewhere other than the requested folder. `\` is a separator on Windows, so it's
refused everywhere, which means the same names are refused as path separators on every OS.
(Other Windows filename rules, such as `:` or reserved names like `CON`, aren't checked here.)

**Workaround:** Rename the file or folder in Drive (or locally). For a single file,
`download_file` with a full file path as `local_path` downloads it under that name.

### Downloads replace the local file rather than rewriting it

**What:** `download_file`, `download_folder`, and `sync_folder` write a download to a temporary
`.gee-sweet-partial-*` file next to the destination, then rename it over the old file. The
replacement is a new file, so:

- It keeps the old file's permission bits, and its owner and group only when the server may set
  them (running as root, as the Docker image does). Running as a regular user, a file owned by
  someone else becomes owned by the server's user; its group is kept if the server's user
  belongs to that group. ACLs, extended attributes (macOS Finder tags,
  the quarantine flag), and the creation time aren't carried over.
- Another hard link to the old file keeps the old content.
- The server needs write permission on the destination's *folder*, not just on the file. A
  writable file inside a read-only folder can't be downloaded over.
- A FIFO or socket at the destination is refused instead of written to. A device such as
  `/dev/null` is still written directly.

A download the server is killed partway through leaves its `.gee-sweet-partial-*` file behind.
`sync_folder` and `upload_local_folder` never upload one and list it under `skipped`; they
don't delete it, since it may belong to a download that's still running.

**Why:** Writing into the existing file left a truncated file behind when a download failed
partway, with a fresh mtime that made `sync_folder` upload it over the intact Drive copy (#844).
A rename means the destination only ever holds the old content or the complete new content.

**Workaround:** Re-apply ACLs, tags, or ownership after downloading, if they matter. Delete a
leftover `.gee-sweet-partial-*` file once no download into that folder is running.

## Local file access

### `LOCAL_FILE_ACCESS=roots` checks a path before it's used, not as it's used

**What:** A path is resolved, symlinks included, and checked against `LOCAL_FILE_ROOTS` just
before the tool opens it. If a symlink inside a root is swapped to point outside it between
that check and the open, the tool follows the new link.

**Why:** Closing the gap fully means descriptor-relative I/O (`openat`) through every local
read and write, which is out of proportion here. No tool can create a symlink (downloads write
regular files and `sync_folder` never creates links), so a remote caller can't stage the swap.
It takes a local user with write access inside a root.

**Workaround:** Don't give untrusted local users write access to a directory listed in
`LOCAL_FILE_ROOTS`.

### `roots` mode can refuse a path spelled in a different case on macOS

**What:** On a case-insensitive filesystem (macOS's default), a path whose directories are
spelled with a different case than the configured root, such as `/Data/x.csv` under the root
`/data`, can be refused even though it names a file inside the root.

**Why:** Containment is a test on the resolved path's text, and resolving keeps the caller's
spelling of existing directories. A case mismatch can therefore refuse a path inside a root,
but never allows one outside it. The always-refused credential files are matched by file
identity instead, so a case variant of one of them is still refused.

**Workaround:** Spell paths with the same case as the `LOCAL_FILE_ROOTS` entry.

### Only the server's own files are protected

**What:** In every mode, tools can't read or write the server's own credential, config, cache,
and log files. Any other secret is readable in `full` mode, or in `roots` mode when it's
inside a root.

**Why:** The server can't know which other files are sensitive. `roots` mode is how an
operator limits tools to directories meant for them.

**Workaround:** Use `LOCAL_FILE_ACCESS=roots` with roots that hold only files meant for the
server.

## Google API requests

### A write that times out may still have been applied

**What:** A Google API request fails with `Google API request timed out:` once Google sends
nothing for `HTTP_TIMEOUT_SECONDS` (default 60). A read is retried once on a new connection;
a write (create, update, delete, a `batchUpdate`) is not. A timed-out write may still have been
applied, since Google can finish it after the connection stops answering.

**Why:** The client can't tell a dead connection from a request Google is still working on.
Without the timeout, a silently dead connection hung a call for up to 30 minutes (#1129).
Retrying a write automatically could apply it twice, such as a duplicate file or a repeated
append.

**Workaround:** After a timed-out write, check its result (e.g. `list_files`, `get_sheet_data`)
before repeating it. If a request legitimately takes Google longer than the timeout to start
answering, such as a very large export or `batchUpdate`, raise `HTTP_TIMEOUT_SECONDS`. See
`docs/decisions/decision-http-socket-timeout.md`.
