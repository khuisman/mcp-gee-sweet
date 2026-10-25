# Design: CommonMark/GFM Markdown Parser

**Status:** Implemented in #1116 (closes #1071 too). Replaces the Python-Markdown call in
[`markdown-support.md`](markdown-support.md); the MD → HTML → AST → Docs pipeline that doc
describes is unchanged. Also answers #1112's open questions (Joy's spike, closed into #1116).

## Problem

`_md_to_html` parsed with Python-Markdown, which departs from CommonMark/GFM, the dialect
models and most tools write: a list or table directly under a paragraph stayed text, `1)` wasn't
a list, `\`-escapes kept their backslash, bold inside italic was lost, sub-lists needed 4 spaces,
fenced code inside a list item was literal text, `~~` did nothing. The #1044 Phase 2 baseline
(`docs/qa/results/2026-10-18-markdown-phase2.md`) found each one live. The maintainer decision
(2026-10-18) was to replace the parser rather than patch Python-Markdown's grammar case by case.

## Solution

`src/mcp_gee_sweet/tools/docs/md_to_html.py`, imported by `content.py`:

```
_md_to_html(md, autolink_urls)
  = markdown-it("commonmark", html=True) + table + strikethrough
      .render(_separate_tables(_nest_lists(normalize_line_endings(md))))
```

| Piece | Why |
|---|---|
| markdown-it-py, `commonmark` preset | CommonMark-conformant, already in the lock as a transitive dependency (now a direct one). `html=True` keeps raw HTML passing through to `html_to_ast`, as before. |
| `table`, `strikethrough` rules | GFM's two block/inline extensions. Task lists are left as literal `[ ] `/`[x] ` text, which `html_to_ast` already turns into checkbox items, so no plugin is needed. |
| `_gfm_autolink_rule` (core rule) | GFM extended autolinks: `www.`, `http(s)://`, email. See below. |
| `normalizeLink` = identity | markdown-it percent-encodes destinations; a local image path like `café.png` would no longer open. `validateLink` still refuses `javascript:` and friends. |
| `_spaced_image_rule` (inline rule) | `![alt](/path/Screen Shot.png)`: Python-Markdown accepted a space in an image path, CommonMark doesn't. Only that shape (whitespace, no title, quotes, parens or angle brackets) is taken; anything CommonMark itself parses as an image never reaches it. Links stay strict: a URL can't hold a space. |
| `_nest_lists` (pre-pass) | Plan rule D1. See below. |
| `_separate_tables` (pre-pass) | Plan rule D2. See below. |

`markdown` (Python-Markdown) stays a dependency: `anchors.py` uses its `toc` slugify for the
GitLab heading-anchor scheme, and `upload_file(source_format='markdown')` (EP-8) still renders
with it until #1101 routes that entry point through this converter.

### Autolinks: a GFM rule, not linkify-it

markdown-it's own `linkify` needs `linkify-it-py` and doesn't follow GFM. Measured:
with fuzzy links on, it links `README.md`, `file.py` and `example.com` (any TLD-looking token);
with them off, it stops linking `www.` too; it also links `ftp://`. The GFM rule is short, so it's
a core rule over text tokens instead (`_GFM_AUTOLINK_RE`, `_trim_autolink`):

- `www.` or `http(s)://` plus a domain, or an email address, at the start of text or after
  whitespace, `*`, `_`, `~` or `(`.
- No `_` in the last two domain segments. A scheme-ful link may have a one-segment domain
  (`http://localhost:8000`), as in cmark-gfm.
- Trailing `?!.,:*_~'"`, an unbalanced `)`, and a trailing `&entity;` are left outside the link.
- Runs after inline parsing, so a code span, an `<autolink>` or raw HTML is never re-matched; text
  inside a Markdown link or a raw-HTML `<a>` is skipped, since links can't nest.

`autolink_urls=False` drops the rule, so `www.`, email and `https://` are all plain text.

### D1: nesting width (#1071)

Plan rule D1 (`docs/qa/tests/docs_markdown.md`): a marker indented at least 2 columns past the
previous item's marker nests under it, whatever the parent marker's width. CommonMark nests only
at the parent's content column, so `1. A` / `  - a` (column 2 < 3) doesn't nest, and under
markdown-it the grandchildren of a 2-space numbered outline became literal `1. Grandchild` text.

`_nest_lists` keeps a stack of open items (`_ListItemColumns`: original and rewritten marker and
content columns). For each marker line:

- pop items until the top's marker is at least 2 columns left of this one; an item within 0–1
  columns is a sibling, and the line takes the sibling's rewritten column;
- under a parent, the marker moves to the parent's rewritten content column, plus however far
  past the original content column it already was, so 4-space and tab indents are unchanged;
- continuation lines (a fenced block's body included) move by their owning item's shift.

It leaves alone: lines in a top-level fence; everything after the list ends (a blank line then
unindented text, or a heading, quote, fence, table row or thematic break); a thematic break
like `* * *`, which looks like a marker. Columns count tabs to the next multiple of 4, as
CommonMark does. A run of quoted lines not indented into a list ends any open list, and gets
the same rule one level in: each line's `>` prefix is stripped, the inner text goes through
`_nest_lists`, and the prefixes are put back (so `> 1. A` / `>   - a` nests, at any quote
depth). A quote inside a list item is left alone.

### D2: a table starts its own block

GFM lets a table interrupt a paragraph, but not a list item's or a quote's lazy continuation, so
`- B` / `| K | V |` / `|---|---|` made the rows more item text. `_separate_tables` inserts a
blank line before a header row whose next line is a delimiter row, when the line above is
non-blank and not itself in a table. A table written inside a quote (`> | K |`) or indented
inside an item stays there. Two tables with no blank line between stay one table (AJ-078: GFM
ends a table only at a blank line or another block).

## The HTML `html_to_ast` sees

Inventory of where markdown-it's HTML differs from Python-Markdown's, and what handles it:

| Shape | Python-Markdown | markdown-it | Handling |
|---|---|---|---|
| Tight item with a nested block | `<li>a<ul>` | `<li>a\n<ul>` (also before `<pre>`, `<table>`, `<blockquote>`) | **Changed:** `_interrupt_open_block` drops trailing whitespace holding a line break from the raw text before the block. It was reaching the Docs API as an empty paragraph under every parent item. A `<br>`'s own break is kept. |
| Rule inside an item | (never produced) | `<li>item\n<hr />\n</li>` | **Changed:** an `<hr>` after text in an open block ends that segment, emits the rule's empty paragraph, and resumes the block. `<li><hr>` with no text keeps #401's dropped-construct boundary. |
| Loose item | `<li>\n<p>a</p>\n</li>` | same | Unchanged here: owned by community PR #1164 (#1111). markdown-it produces it more often, since it attaches an indented paragraph or code block to the item instead of dropping it out of the list, so **#1164 must land first or in the same release.** |
| Strikethrough | (none) | `<s>` | Already handled (`_INLINE_STRIKE`). |
| Table alignment | `align="left"` | `style="text-align:left"` | Neither is read; no AST field for column alignment. No regression. |
| Code block language | `class="language-x"` | same | Unchanged. |
| Hard break | `<br />\n` | same | Unchanged; the double break it produces is #1117. Now reachable from a trailing `\` too. |
| Two quotes | one `<blockquote>`, two `<p>` | two `<blockquote>` | Renders as two quotes (#1098's emitter work). |
| Empty item | (not produced) | `<li></li>` | Dropped by `_emit_block_node`'s no-content rule; #1075. |
| Output | no trailing newline | ends in `\n` | Harmless; one exact-match test updated. |

## Behavior changes for existing callers

Measured by rendering every fixture under `docs/qa/fixtures/md/` through both parsers into the
AST and diffing (32 of 52 fixtures changed). Each change is one of the fixes in #1116's table,
D1, D2, or listed here; `CHANGELOG.md` has the user-facing version.

- **Fixed:** everything in #1116's table; 2-, 3- and 4-space nesting (TC-MD106 LN-01 to LN-16 all
  match their expectation, r16's agenda keeps 1–4); blocks inside list items (TC-MD201); fenced
  code inside items renders as code without the info string as text; strikethrough; www/email
  autolinks; `\` escapes; adjacent quotes; a bare `-` no longer becomes a setext heading.
- **Worse until #1164:** an item followed by an indented paragraph or code block loses its bullet
  (r06's numbered steps, TC-MD107, TC-MD108 LX-08, TC-MD203's list-after-list pairs, which
  CommonMark merges into one loose list). Python-Markdown dropped those blocks out of the list,
  restarting the numbering at 1 after each; neither is right.
- **Different, still wrong:** front matter (DS-14) renders as a rule plus a Heading 2 instead of
  a rule, a paragraph and a rule (#1173). A block inside a list item renders after the item, not
  indented inside it: the AST has no blocks inside list items.
- **Unchanged:** r03, r07, code blocks, inline code, inline HTML, images, unicode, and DS-01 to
  DS-13 (CRLF included).

## Re-run scope

Every Markdown entry point that uses `_md_to_html` (EP-1 to EP-4). EP-5 to EP-7 (Drive's native
import) and EP-8 don't use it.

- **The #1116 table:** TC-MD202, TC-MD108 (LX-01, LX-02), TC-MD113 (TB-04, TB-08), TC-MD105
  (LM-03), TC-MD114 (BR-03), TC-MD101 (HD-02, HD-04), TC-MD115 (ES-01), TC-MD102 (EM-04),
  TC-MD204 (IN-05), TC-MD111 (LK-06, LK-07).
- **D1 (#1071):** TC-MD106, TC-MD109 (TK-02), TC-MD016, TC-MD001, TC-MD002, TC-MD012.
- **Changed fixtures, for regressions:** TC-MD004–TC-MD006, TC-MD008–TC-MD011, TC-MD013–TC-MD015,
  TC-MD107, TC-MD110, TC-MD201, TC-MD203, TC-MD301 (DS-14), TC-MD302.
- The rest of `docs_markdown.md` produced the same AST and needs no re-run for this change.

## What this does NOT do

- Strip front matter (#1173), keep an empty list item (#1075), keep a loose item's bullet (#1164),
  or fix hard and soft breaks (#1117, #1093). Each is in the HTML → AST step or its own ticket.
- Change EP-8 (`upload_file`), which keeps Python-Markdown until #1101.
- Read table column alignment.
