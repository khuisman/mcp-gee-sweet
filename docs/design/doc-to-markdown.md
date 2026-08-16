# Design: Docs → Markdown Export (`get_doc_as_markdown`)

**Status:** Shipped. Issue #300, PR #591. Live-verified against real Docs/Drive API calls
(headings, styled runs, nested/ordered/checked bullets, blockquotes, inline code, fenced code
blocks, a colspan table, and open/resolved comment filtering) via scratch scripts per
`CLAUDE.md`'s "Verify a ticket's API premise live" convention. PR #591's QA round 1
(`/code-review high` + live QA against TC-DOC173–182) found three blocking correctness bugs the
initial version's own live round trip hadn't exercised — merged-cell table corruption, an
unescaped link URL, and unescaped leading block-marker text — detailed in "Merged
(colspan/rowspan) table cells" and the escaping bullets below, fixed in the same PR, with
TC-DOC183–185 added as permanent regression coverage. See `docs/qa/tests/docs_content.md` for
the full QA checklist and results.

## Problem

The Docs write side has full Markdown support (`content_format='markdown'` on
`create_doc`/`write_doc_content`, `create_doc_from_file`) via a Markdown → HTML → AST → Docs API
pipeline (see [Markdown Support](markdown-support.md)). Nothing mirrors this on the read side:
`get_doc_content` returns plain text only, and `export_file` has no Markdown output format. A
competitor server (taylorwilsdon/google_workspace_mcp) has a `get_doc_as_markdown` tool; without
an equivalent this project's Markdown story is write-only — a concrete, checkable gap flagged
during v0.9 competitive positioning work (see issue #300's comment thread).

## Approach: Docs API → AST → Markdown (not HTML export + a conversion library)

Two approaches were considered:

1. **Docs API → this project's own AST (`docs/ast.py`) → Markdown.** Walk `documents().get()`
   into the same node types the write pipeline already produces, then serialize that AST to
   Markdown — the read-side mirror of `html_to_ast` → `ast_to_requests`.
2. **`export_file(export_format='html')` → an HTML-to-Markdown library** (e.g. `markdownify`,
   `html2text`). Reuse Docs' own HTML export.

**Chosen: (1).** Google's raw Docs HTML export is heavily styled — redundant inline `<span
style="...">` wrappers rather than semantic tags — and converting that cleanly to Markdown
needs fragile cleanup heuristics. Building on the project's own AST instead means:

- Reusing exactly the node types and mapping `markdown-support.md` already documents for the
  write direction, just inverted — no new intermediate representation to design or trust.
- No new dependency (an HTML→Markdown library would have been one).
- Symmetric code structure: `doc_to_ast.py` (Docs API → AST) sits next to `html_parser.py`
  (HTML → AST); `ast_to_markdown.py` (AST → Markdown) sits next to `emitter.py` (AST → Docs API
  requests).

## Scope

Full fidelity was chosen over an MVP subset, given issue #300's own elevated-priority framing
(a competitive gap worth closing properly, not partially): headings, styled runs (bold, italic,
strikethrough, links, inline code), nested/ordered/checked bullet lists, blockquotes (including
nesting), inline code and fenced code blocks, images, tables (including nested tables,
best-effort — see below), and an opt-in comments section.

Three gaps were kept **as documented limitations, not implementation shortcuts** — see
`docs/known-limitations.md`'s `get_doc_as_markdown` entry for the full writeup:

- A table nested inside another table's cell — GFM pipe-table syntax has no way to express this
  at all, the read-side mirror of markdown-support.md's identical write-side gap.
- Inline images resolve to Drive's temporary `contentUri` (expires ~30 min) — inherent to how
  Drive serves embedded image bytes, not something this tool controls.
- Inline code vs. a fenced code block are represented identically in the Docs API (a run, or
  every run in a paragraph, styled `font_family="Courier New"` — see markdown-support.md's own
  write-side table). There's no other signal to tell them apart on read; see the heuristic below.

## Key implementation decisions

### `doc_to_ast.py` — walking `documents().get()` into the AST

- **Bullet ordered/unordered and nesting depth**: `paragraph.bullet` carries `listId` and
  `nestingLevel` but no preset field of its own — the same gap `style.py`'s
  `create_paragraph_bullets` already solved by reading `document["lists"][listId]
  ["listProperties"]["nestingLevels"][level]` (`glyphType` present → ordered, `glyphSymbol`
  present → unordered). Reused verbatim here rather than re-deriving it.
- **Checkbox state**: the write side has no `BULLET_CHECKBOX` preset — it prepends a literal
  `"☑ "`/`"☐ "` glyph to the item's own text (see emitter.py's comment on this). Read-back
  detects that exact prefix on the item's first run and strips it back off, setting
  `BulletItem.checked` — a direct inverse, not a new convention.
- **Blockquote depth**: emitter.py's `_blockquote_style_request` writes a specific
  `indentStart` (36pt × depth) + `borderLeft`. Read-back requires *both* to be present
  (`borderLeft` alone signals "this was our blockquote styling"; `indentStart` alone is
  ambiguous — plenty of ordinary paragraphs use indentation for unrelated reasons) and infers
  depth from `round(indentStart / 36)`.
- **Trailing paragraph newline**: every paragraph's content ends with a `"\n"` in the Docs API's
  own representation. Stripped from the last Run once, dropping the Run entirely if that empties
  it — mirrors `html_parser.py`'s own `<pre>`-close trailing-newline handling.
- **Table cells are flat, not per-paragraph**: `Cell.children` (`ast.py`) has no paragraph
  structure of its own — the write side never produces one (`html_parser.py`'s table-cell
  handling treats a `<td>` as flat inline content). Multiple paragraphs within one live Docs
  table cell are read back joined by a literal `"\n"`, the same character an explicit `<br>`
  would have produced on write.
- **Merged (colspan/rowspan) table cells — phantom physical cells (PR #591 QA round 1)**: the
  first version built one `Cell` per raw `tableCells[]` JSON entry unconditionally. Live-confirmed
  this is wrong: a merged cell does NOT remove the physical entries it covers — the Docs API
  leaves an empty, ordinary-looking (`columnSpan: 1, rowSpan: 1`) phantom cell at every absorbed
  position, both within a colspan's own row and in every later row a rowspan reaches into (a
  colspan=2 header row actually has *two* physical `tableCells[]` entries, not one). There is no
  field marking a cell as "this is a phantom" — `emitter.py`'s write-side `_build_phantom_set`/
  `_physical_to_ast_indices` already established this same fact for the opposite direction
  (mapping a known AST onto live physical cells), but that logic can't be reused directly here
  since there's no target AST yet — building one *is* the job. The fix (`_table_elem_to_ast`)
  walks each row's physical cells in `startIndex` order, tracking which `(row, col)` positions an
  earlier real cell's own `colspan`/`rowspan` already claims; a physical cell landing on a
  claimed position is consumed (advances past it) but not added to the AST, exactly mirroring the
  write side's phantom-set concept computed forward instead of backward. Before this fix, a
  colspan=2 header exported as a 3-column table (TC-DOC177, confirmed live); a rowspan=2 cell's
  covered row silently lost its own real trailing cell entirely (no test coverage existed for
  this case at all — added as TC-DOC183).

### `ast_to_markdown.py` — serializing the AST

- **CommonMark emphasis-delimiter whitespace rule**: a naive `f"**{text}**"` wrapper breaks when
  `text` has trailing whitespace (`"**Bold **"` doesn't close per CommonMark's flanking-delimiter
  rule — it renders as literal asterisks). Caught live during round-trip verification, not by
  the initial hand-written test fixtures. Fixed by moving leading/trailing whitespace outside
  the style markers before wrapping.
- **Fenced code block vs. inline code**: since the Docs representation can't distinguish them
  (see Scope above), the heuristic is: a `Paragraph` node renders as a fenced block only when
  *every* run in it is code-styled; a paragraph mixing code-styled and plain runs renders each
  code-styled run as an inline `` `span` `` instead. Confirmed live that this correctly
  distinguishes a genuine ```` ```code block``` ```` paragraph from `` `inline code` `` sitting
  next to ordinary text in the same paragraph — the one case it can't resolve (a paragraph
  containing *only* a single inline code span, nothing else) is the genuinely ambiguous case
  documented above, not a bug in the heuristic.
- **Tight vs. loose lists**: consecutive `BulletItem` nodes are joined with a single `"\n"`
  rather than the `"\n\n"` used between other block types — CommonMark still parses a
  blank-line-separated run of list items as one list either way (just "loose", wrapped in `<p>`
  tags), so this is a readability polish on the output, not a correctness fix. Caught during
  live round-trip verification (the initial version produced a blank line between every single
  list item, nested or not).
- **Tables**: the first row is always rendered as the header row — GFM pipe-table syntax
  structurally requires exactly one header + separator row, and the Docs API has no per-row
  "is this the header" signal to read back (unlike the AST's own `is_header_row`, which only
  ever gets set on the write side from an HTML `<thead>`/`<th>`). A merged cell (`colspan`/
  `rowspan` > 1) renders its text in the first spanned column and blank cells for the rest,
  reusing `emitter.py`'s own `_build_phantom_set` to find which (row, col) positions a rowspan
  covers — the closest a pipe table (no native merge concept) can represent one.
- **Comments**: `include_comments=True` fetches every comment via the same Drive `comments`
  resource `list_doc_comments` uses (paginated, unlike `list_doc_comments`' single-page default),
  filters to non-resolved ones (a resolved comment's discussion is already settled — not scoped
  as diff-worthy content in an export), and appends a `## Comments` section with each comment's
  author, quoted anchor text, content, and replies.
- **Link/image URL escaping (PR #591 QA round 1)**: `run.link_url`/`image.src` were interpolated
  directly into `[text](url)`/`![alt](url)` with no escaping. Live-confirmed a real-world URL
  containing an unmatched `)` (e.g. `.../wiki/Foo_(bar)`) breaks CommonMark's bare-link-destination
  parsing, which requires balanced parentheses. Fixed via `_md_link_dest`: a destination
  containing whitespace or any parenthesis is wrapped in CommonMark's `<...>` angle-bracket
  destination form instead, which has no such restriction (only a literal `<`, `>`, or backslash
  inside still needs escaping). A plain URL with none of those characters is left bare, unchanged.
- **Leading block-marker escaping (PR #591 QA round 1)**: `_MD_ESCAPE` only escaped
  `` \ ` * _ [ ] `` — not a line-leading `#`, `>`, `-`/`*`/`+`, or an ordered-list `N.`/`N)`.
  Live-confirmed a plain paragraph reading literally "1. Not actually a list item" or "# Not a
  heading either" round-tripped unescaped and any CommonMark parser reinterprets it as a real
  ordered-list item or ATX heading. Fixed via `_escape_leading_block_marker`, applied only to
  plain `Paragraph` rendering (not `Heading`/`NamedBlock`/`BulletItem`, which already have their
  own legitimate same-line prefix, so content following it is never re-parsed as a new block
  starting mid-line) and applied *before* any blockquote `"> "` wrapping (a `"> #"` line is parsed
  as a heading nested inside the blockquote by CommonMark, so the escape has to happen first, not
  after). One CommonMark subtlety this surfaced: digits are not in CommonMark's escapable
  ASCII-punctuation set, so `\1` is not a valid escape and renders as a literal backslash — the
  fix escapes the trailing `.`/`)` punctuation after the digit run instead (`1\.`), which is the
  actual mechanism that neutralizes ordered-list-marker detection.

## Verification

1. `uv run python -m pytest tests/` — full suite passes, plus `tests/test_docs_markdown_export.py`
   (unit coverage for `doc_to_ast.py`, `ast_to_markdown.py`, and the tool itself).
2. Live round-trip via a scratch script (`mcp_gee_sweet.auth._oauth_creds()` +
   `googleapiclient.discovery.build`, per `CLAUDE.md`'s documented same-session verification
   method — the `jay` MCP server only serves the main checkout's installed code, not an
   in-progress worktree change): built a real Doc through the *existing* write pipeline from a
   Markdown source covering every construct in scope, then read it back through
   `get_doc_as_markdown` and diffed the output against the original source. Caught and fixed two
   real bugs (the emphasis-whitespace CommonMark violation and the tight-list join) this way —
   neither was caught by the hand-written unit tests, which had no way to independently verify
   what the live Docs API actually returns for `bullet.nestingLevel`, `lists[...].glyphType`, or
   `tableCellStyle.columnSpan`/`rowSpan` shapes.
3. Live-verified comment export separately: created open and resolved comments (with a reply) on
   a real Doc, confirmed only the open one appears in the rendered `## Comments` section.
4. See `docs/qa/tests/docs_content.md` for the QA checklist test cases covering this tool
   (TC-DOC173–185).
5. **PR #591 QA round 1** (`/code-review high` + live QA against TC-DOC173–182) caught three
   blocking bugs the round above's own live round trip hadn't exercised — a single Markdown
   source covering every construct doesn't guarantee coverage of every edge case within a
   construct (a *merged* table cell specifically, a URL with parens, plain text that happens to
   look like a block marker). Fixed and re-verified live via the same scratch-script method
   against the exact reported repros (a colspan header, a rowspan second row, a parenthesized
   Wikipedia-style URL, and both flagged plain-paragraph texts) — all four now round-trip
   correctly. TC-DOC183–185 added so this bug class has permanent regression coverage rather than
   living only in a PR comment thread.
