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
rendered output. Related: #190.

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
   block either way.

**Why:** (1) and (3) are Docs-representation-level ambiguities, not gaps in this tool's
traversal; (2) is inherent to how Drive serves inline image bytes.

**Workaround:** For full fidelity on any of these three cases, use `get_doc_structure` (or the
raw Docs API via `batch_update` passthrough) instead. Related: docs/design/doc-to-markdown.md.

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
