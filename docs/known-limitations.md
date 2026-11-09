# Known Limitations

Constraints imposed by the Google Docs/Drive/Sheets APIs or by current implementation scope.
Each entry describes what the limitation is, why it exists, and the available workaround (if any).

---

## Google Docs

### Blank paragraph before every table

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
paragraph is also reset to plain `NORMAL_TEXT`, with no bullet, indent, or border (#1097),
except that one between two quoted tables in the same quote takes the quote's indent and
bar (#1122).
Related: #190.

---

### A quoted table is a table inside a 1x1 wrapper table

**What:** A table inside a blockquote (Markdown `> | a | b |`, or HTML `<blockquote><table>`)
is written into the one cell of a 1x1 wrapper table, whose left border is the quote's
gray bar (#1122). `get_doc_structure` reports the wrapper as the top-level table, with the
quoted table nested in its cell, so table tools that take a table's position
(`insert_table_row`, `merge_table_cells`, and so on) reach the wrapper, not the table you
see. Removing the wrapper in the Docs editor removes the bar but leaves the table.

**Why:** The Docs API can't give a table a paragraph border, so a bar beside a table has to
come from a table cell's border. Without the wrapper, a quoted table sat at the quote's
indent with a gap in the bar beside it.

**Workaround:** To edit a quoted table's rows or columns with the table tools, pass the
quoted table's own `table_start_index`: one more than the wrapper cell's
`paragraphStartIndex` in `get_doc_structure`, since the cell's first paragraph is an empty
line before the table. Or rewrite the content with `write_doc_content`. `get_doc_as_markdown` reads the wrapper back
as the quoted table (`> | a | b |`).

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

**Why:** GFM's pipe-table syntax has no way to write a table inside another table's cell.

**Workaround:** Supply raw HTML instead — the HTML→AST pipeline fully supports nested tables
(see #109). Related: `docs/qa/tests/docs_content.md` TC-DOC51.

---

### Markdown input doesn't read footnotes, definition lists, or other Python-Markdown `extra` syntax

**What:** Markdown passed to `create_doc`/`write_doc_content` (`content_format='markdown'`),
`create_doc_from_file`/`update_doc_from_file`, or `upload_file(source_format='markdown')` is read
as CommonMark plus GitHub-flavored Markdown (tables, strikethrough, task lists, autolinks). These
constructs from Python-Markdown's `extra` extension aren't part of that:

- Footnotes: `Text[^1]` and `[^1]: …`. A note written as prose (`[^1]: This is the note.`)
  stays literal text, both the `[^1]` marker and the note line. A note of a single word or URL
  (`[^1]: note`) is a valid CommonMark link reference definition instead, so the note line
  disappears and the marker shows as `^1`. It's linked when the note is a URL; otherwise the
  link is dropped (no scheme, #1120) and reported in `dropped_links`.

These come out as literal text:

- Definition lists: `Term` followed by `: definition`.
- Abbreviations: `*[HTML]: Hyper Text Markup Language`.
- Attribute lists: `{#id}` or `{.class}` after a heading or paragraph.
- Markdown inside an HTML block marked `markdown="1"`; the block's contents stay as written.

**Why:** `upload_file` converted with Python-Markdown `extra` until #1102 moved it onto this
server's CommonMark/GFM converter, which the Docs tools already used. They never read these
constructs.

**Workaround:** Write a footnote as an inline parenthetical or a "Notes" list at the end (creating
real Docs footnotes is #149), a definition list as `**Term**: definition` lines, and put HTML that
needs Markdown inside it as HTML instead.

---

### `get_doc_as_markdown` exports a table or quote that ends a list's last item outside the list

**What:** A table inside a list's last item (`1. a\n\n   | x |\n   |---|\n`) is written to the
Doc indented under the item, but `get_doc_as_markdown` exports it at the margin, after the list.
A quote that ends a list's last item (`- a\n\n  > q\n`) exports as a deeper quote at the margin
(`> > q`). So does a paragraph, code block, heading, or rule inside the last item of a *quoted*
list (`> - a\n>\n>   b\n` exports `b` as `> > b`). Any of these exports inside its item when the
list goes on after it: a later item of the list, a sublist nested under the item (of either
type), or a paragraph indented in the item. A paragraph, code block, or heading inside an item of
an unquoted list always exports inside it.

**Why:** The export finds a block inside an item from its indent (#1302). A table's indent isn't
reported anywhere in the Docs API: the JSON of a table inside an item matches one at the margin
(checked live). A quote's is, but a quote inside an item sits exactly where a deeper quote at the
margin would (a quote in a top-level item is at 72pt, like a margin `> >`), so the indent can't
tell them apart. A block inside a quoted list's item is written the same way, at the item's text
indent plus the quote's and with the quote's border, which is exactly where a deeper quote at the
margin goes. Such a block counts as inside an item only when the list goes on after it, which
it never does after a list's last item. Reading an ambiguous quote as the margin quote keeps every
quote level; reading it into the item would drop one.

**Workaround:** None in the export. Indent the table or quote under its item by hand in the
exported Markdown. Related: `docs/qa/tests/docs_content.md` TC-DOC244.

---

### A list inside a blockquote draws its own quote bar, offset from the quote's

**What:** In Markdown or HTML content written to a Doc, a list inside a blockquote shows its gray
left bar at the list item's indent, not at the quote's. A quote that mixes paragraphs and list
items therefore shows two bars, the items' sitting to the right of the paragraphs'. For example,
`create_doc(content="> quote text\n>\n> - item\n", content_format="markdown")` gives "quote text"
a bar at the quote indent and "item" a second bar further right. The same mechanism puts a nested
item's bar at its own, deeper indent. Reading the Doc back with `get_doc_as_markdown` is
unaffected: every item comes back at its correct quote depth.

**Why:** Docs has no blockquote style, so a quoted paragraph gets a left border and an indent.
Docs draws a paragraph's `borderLeft` at its `indentStart`, and there's no separate setting for
where the border goes. A list item needs its own `indentStart` too, past the quote's: it's where
the item's wrapped lines start, under the text rather than under the bullet. Setting a quoted
item's `indentStart` to the quote indent does join the two bars, but then every wrapped line lands
left of the item's bullet and nested items lose their indent after the first line. One paragraph
can't have both the quote's bar position and a list's hanging indent, so the offset bar is the
lesser problem.

**Workaround:** None that keeps a real list. To get one continuous bar, keep the list outside the
quote, or write each item as its own quoted paragraph starting with a bullet character, which isn't
a Markdown list marker: `> • one\n>\n> • two\n`. Keep the blank `>` line between items, or the
lines join into one paragraph. Decided in #1242.

---

### A list that doesn't start at 1 can be literal numbers, not a Docs list

**What:** In Markdown or HTML content written to a Doc, `3. a` or `<ol start="3">` shows the
right numbers, but unless it continues the list before it, its items are plain paragraphs
holding the number, a tab and the text, at a list's hanging indent. Docs doesn't treat them
as a list: pressing Enter in one doesn't add an item, and adding or removing one doesn't
renumber the rest. `get_doc_as_markdown` reads them back as list items.

A top-level list that starts where the last top-level list stopped (`1. a`, a code block,
`2. b`) stays a real list: it joins that list. It's literal instead when another list comes
between them, or a table, an empty paragraph or a quote two levels deep (each would read back
from the Doc as inside the first list's last item), or when it's in a different blockquote or
has a different number. A nested list that doesn't start at 1 is always literal, written in its
level's glyph (`c.`, `iv.`). So are `<ol reversed>` and a list with an `<li value>`.

A literal item that's both quoted and nested in a list reads back through `get_doc_as_markdown`
as a plain paragraph: its marker and tab as text, at the quote depth its indent gives. The Doc
itself shows it correctly. An indent adds the item's list level to its quote depth, and nothing
in the Doc separates the two. A quoted literal item at the top of a list, with a digit marker,
reads back as a list item.

A marker too wide for a list's 18pt gap (`100.`, or `10.` in a heading) starts further left, so
its text stays lined up with the other items. A marker wider than the level's whole text indent
moves the item's text right, leaving the blocks and sublists under it behind. The width is
estimated from Arial at the default sizes, so a much wider font can still overrun it.

**Why:** `NestingLevel.startNumber` is read-only: no `batchUpdate` request writes it, and
deleting a list's first items renumbers the rest from 1 (confirmed live). Only Drive's HTML
import sets it, and importing over an existing Doc removes its headers, named styles and
margins. See `docs/design/list-start-numbers.md`.

**Workaround:** To get a real list, start it at 1, or write it through Drive's import
(`upload_local_file(convert=True)`), which creates a new Doc.

---

### The gap between paragraphs is set on each paragraph

**What:** `create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file`, and
`upload_file` (Markdown source) put 10pt below a paragraph that another paragraph follows, in the
paragraph's own style rather than in NORMAL_TEXT, so a change to NORMAL_TEXT in the Docs UI doesn't
reach those paragraphs. `apply_theme` with a NORMAL_TEXT `space_above` or `space_below` does: it
removes the 10pt from every NORMAL_TEXT body paragraph that has exactly that value, including one
a person set by hand. A doc whose NORMAL_TEXT has nonzero spacing gets no gaps when it's written,
but a NORMAL_TEXT set to 0 can't be told from the default, so that doc gets them.

The same 10pt goes on each side of a list (#1389), but not on a list inside a quote: the list's
indent differs from the paragraphs beside it, so Docs wouldn't draw the quote bar across the gap,
and a quoted list sits tight against the quoted paragraphs around it.

`get_doc_theme` leaves 8pt and 10pt out of NORMAL_TEXT's `space_above` and `space_below`, since
that's what those values are on a server-written doc, so it also misses them on a paragraph set
to one by hand.

---

### A horizontal rule is a bordered paragraph, not a Docs horizontal line

**What:** A Markdown thematic break (`---`, `***`, `___`) or an HTML `<hr>` written by `create_doc`,
`write_doc_content`, `create_doc_from_file`, `update_doc_from_file`, or `upload_file` (Markdown
source) appears as a thin gray line, but in Docs it's an empty paragraph with a bottom border
(6pt, or 4pt inside a quote), not the element Insert > Horizontal line adds, so editing it in Docs
behaves like editing a paragraph. Inside a quote the line sits closer to the text below it than
to the text above: space below it would break the quote bar. `get_doc_as_markdown` reads both
kinds of line back as `---` (`***` when it's the document's first line, where `---` would open
front matter). A native line that shares a list item's paragraph but comes before its text
exports at the margin, ending the list there. An `<hr>` inside a table cell is dropped: a cell
holds no paragraph styling the converter writes (#1327).

**Why:** The Docs API has no request that inserts a horizontal line (#1096).

**Workaround:** For a native line, use Insert > Horizontal line in the Docs UI, or convert the
file with `upload_local_file(convert=True)`, whose Drive import draws native lines (with the other
differences listed under Google Drive below).

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

### Converting `.md` on upload uses Drive's Markdown import, which renders differently

**What:** `upload_local_file(convert=True)`, `upload_local_folder(convert=True)`, and
`sync_folder(convert_markdown=True)` hand a `.md` file to Drive's own Markdown importer. The
Docs tools (`create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file`)
use this server's converter instead. The same Markdown comes out differently:

- **Bullets** show the source's own marker: a `-` list shows `-` at every level, a top-level
  `+` list `+`, and a top-level `*` list ●. This server's converter uses ● / ○ / ■ by level,
  whatever the marker.
- **Numbered lists** use `1.` numbering at every level, not `a.` / `i.` for nested levels. A
  `1)` list keeps the `)`. A top-level item after a nested numbered sub-list can repeat the
  previous number (1, 2, 2). A numbered list can also join the numbered sub-list before it,
  even across a heading, so it continues that sub-list's count (2., 3., 4.) instead of starting
  at 1.
- **Numbers of 100 or more** don't line up: an item's wrapped line starts left of its first
  line's text, and a paragraph under the item doesn't line up with the item's text.
- **Fenced code blocks** become a gray rounded monospace box with syntax colors and a language
  label, with each source line as its own 9pt paragraph. A fence with no language, or one Drive
  doesn't recognize, is labeled "None", a word that isn't in the source.
- **A fenced code block in a list item or a blockquote** sits at the page margin at full width,
  outside the item or the quote (seen one and two quotes deep). A list continues correctly after
  it.
- **Indented code blocks** render as the same gray box as a fence with no language, labeled
  "None".
- **Inline code** is green monospace rather than Courier New, so `get_doc_as_markdown` reads it
  back as plain text, without backticks.
- **Blockquotes** are indented but have no left border.
- **Task lists** become native Docs checklists rather than `☐` / `☑` text. A numbered task list
  loses its numbers, and a plain item after its task items restarts at 1. A task list two quotes
  deep isn't a checklist at all: it shows dash bullets with the literal `[ ]` / `[x]` text (one
  quote deep it's a checklist).
- **Sub-lists indented by 2 spaces** under a numbered item don't nest; 3 or more spaces do. A
  list nested under such a sub-list is joined onto its parent item's text as literal text ("Child
  one 1. Grandchild one 2. Grandchild two"), and the items after it are renumbered.
- **A pipe table right under a list item or a quote line**, with no blank line between them,
  becomes literal text on the end of that line. After a paragraph or a heading, the table is
  built.
- **A paragraph between two items of an HTML list** (`<ol><li>…</li><p>…</p><li>…</li></ol>`)
  is joined onto the start of the next item's text, with no space ("Loose in the listLoose two").
- **Extra empty paragraphs** appear around paragraphs, rules, lists, and tables. A table gets a
  visible empty line above it when it starts the document, and between it and a paragraph
  directly before it.
- **Inline HTML:** `<del>` and `<mark>` aren't rendered as strikethrough or highlight, and a
  `<br>` splits its paragraph in two, with an empty paragraph between, instead of starting a new
  line in the same paragraph.
- **Images** with a local path or `drive:` source aren't embedded. Only this server's converter
  uploads and shares those. A local path with a space in it shows as the literal
  `![alt](path)` text.
- **An image Docs can't display**, such as an SVG badge from shields.io, leaves an empty line or
  a gap in the sentence, with no alt text, linked or not. This server's converter writes its alt
  text in its place (#1099), except in a heading, where it leaves the image out so the heading's
  text and its link target stay as written.
- **A protocol-relative image** (`//host/image.png`) shows nothing. This server's converter
  fetches it over `https://` (#1180).
- **Relative and `#anchor` links** don't work. A relative link such as `./guide.md` points to
  `http://./guide.md`, and a link to a heading (`#section`) opens nothing. This server's
  converter drops a relative link's target, keeping its text, and points an anchor link at its
  heading, or drops it when no heading matches.
- **`www.` links**, bare (`www.example.com`) or written (`[x](www.example.com)`), point to
  `http://`. This server's converter gives both `https://` (#1180, #1281).

**Why:** The rendering is Drive's, not this server's. These tools upload the file and set a Google
Doc as the target type, and Drive's importer converts it. QA recorded the differences above in
the #1044 Markdown baselines (`docs/qa/results/2026-10-18-markdown.md`,
`2026-10-18-markdown-phase2.md`, `2026-10-22-markdown-boundaries-state.md`,
`2026-11-05-markdown.md`, `2026-11-08-markdown.md`, #1429); the `www.` scheme in PR #1298's QA
round 1. Drive can change this rendering without a release of this server: fenced code blocks
looked different in the 2026-10-18 and 2026-11-05 baselines, and the bullet-glyph and
indented-code entries above were corrected from the 2026-11-08 pass. Routing these tools through
this server's converter is a design question (#1113).

**Workaround:** For a single file, use `create_doc_from_file`, and `update_doc_from_file` to
refresh it. They render `.md` the same way as the other Docs tools. There's no equivalent for a
whole folder or for `sync_folder`'s change tracking yet. Related: `get_doc_as_markdown` exports a
Drive-imported list as blockquoted numbered items (#1104).

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

---

## MCP clients

### Some clients refuse the full tool set

**What:** With every tool registered (the default), the server is over the tool cap of several
MCP clients. VS Code with GitHub Copilot fails every agent request with "Cannot have more than
128 tools per request". Windsurf allows 100 tools across all servers. Cursor's cap depends on the
model and reports "Too many MCP tools are enabled for this mode", or uses only part of the list.
Google Antigravity is reported to reject a server with more than 100 tools.

**Why:** The caps are the clients' own, and the server registers every tool unless told
otherwise, so it works out of the box on clients without a cap. An upcoming release loads a smaller
default tool set; `ENABLED_TOOLS=all` keeps every tool.

**Workaround:** Set `ENABLED_TOOLS` (or `--include-tools`) to one of the
[suggested subsets](configuration.md#suggested-subsets), each under 100 tools. Per-client
config is in [Clients with a tool limit](client-setup.md#clients-with-a-tool-limit).

---

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

## Gmail

### A send confirmation can't ask on a 2026-07-28 connection

**What:** Under the default `GMAIL_SEND=confirm`, a client connected on MCP 2026-07-28 never
sees a confirmation: `send_message` and `reply_to_message` save the email as a draft and return
`sent: false`, and `send_draft` refuses. This happens even when the client declares form
elicitation. **Claude Code currently connects on 2026-07-28** (2.1.310, checked 2026-10-26),
so every send from Claude Code is held as a draft.

**Claude Desktop holds sends too.** On the Chat tab, Claude Desktop 4.23118.0 with the bundle
installed (checked 2026-11-07) never showed this server's confirmation form: `send_message`
returned `reason: no_elicitation` and left the email as a draft. Claude Desktop's own permission
prompt may appear first, showing To, Subject and Body. Allowing it only saves the draft; nothing
is sent. Which protocol version it connects on hasn't been checked, so this may have a different
cause from the one below, and #1235 may not change it.

**Why:** Revision 2026-07-28 removed server-initiated requests. Asking there takes an
`InputRequiredResult` round trip, which isn't implemented yet (#1235).

**Workaround:** Send the draft from Gmail's Drafts folder, connect with a client on the
2025-11-25 `initialize` handshake, or set `GMAIL_SEND=direct`. The bundle install has no setting
for `GMAIL_SEND`.

### The changed-draft check has a short window before the send

**What:** After the user confirms, the server reads the draft again and sends it only if its
message ID is unchanged. An edit that lands between that read and Gmail's `drafts.send` would
still be sent.

**Why:** `drafts.send` takes no precondition, so the check has to be a separate request. The
window is the time between two back-to-back API calls.

**Workaround:** Don't edit a draft while its send confirmation is open.
