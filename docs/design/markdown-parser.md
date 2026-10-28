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
      .render(_preprocess(normalize_line_endings(md)))
```

| Piece | Why |
|---|---|
| markdown-it-py, `commonmark` preset | CommonMark-conformant, already in the lock as a transitive dependency (now a direct one). `html=True` keeps raw HTML passing through to `html_to_ast`, as before. |
| `table`, `strikethrough` rules | GFM's two block/inline extensions. Task lists are left as literal `[ ] `/`[x] ` text, which `html_to_ast` already turns into checkbox items, so no plugin is needed. |
| `_gfm_autolink_rule` (core rule) | GFM extended autolinks: `www.`, `http(s)://`, email. See below. |
| `normalizeLink` = identity | markdown-it percent-encodes destinations; a local image path like `café.png` would no longer open. `validateLink` still refuses `javascript:` and friends. |
| `_spaced_image_rule`, `_spaced_link_rule` (inline rules) | `![alt](/path/Screen Shot.png)`, `[notes](./My Notes.md "t")`: Python-Markdown accepted a space in a link or image destination, CommonMark doesn't, and existing `.md` files rely on it. Only that shape is taken: two or more space-separated pieces with no quotes, parens or angle brackets, then an optional quoted title. Anything CommonMark itself parses as a link or image never reaches them. The destination is unescaped like any other (`\_`, `&amp;`) and refused if that yields a quote; the match stops at `posMax` (a link label's end, inside one); a label naming a reference definition stays that reference; and no link opens inside another's label. |
| `maxNesting` = 100 | The commonmark preset's 20 silently dropped everything deeper, and each list level costs two (`ul` + `li`), so an item's text vanished from about level 10. Python-Markdown kept it. 100 keeps 50 list levels and still parses `">" * 1200`. |
| `_preprocess` (one line-based pre-pass) | Plan rules D1 and D2. See below. |
| `asyncio.to_thread` in `_apply_doc_content` | The parse is pure CPU, about 2× Python-Markdown's time on realistic input (0.2 s for 50 KB) and up to 5× on emphasis-heavy input, all linear. It ran on the event loop before too; now the Markdown step doesn't. |
| Ruler caches built at import | Both renderers and the block scanner are shared by every `to_thread` worker, and markdown-it builds a ruler's rule cache lazily on first use. Every ruler's cache is built at import, so concurrent first conversions never see a half-built one. |

Each conversion block-parses the document twice: once in `_preprocess` (`_verbatim_lines`, inline
pass off) and once to render.

`markdown` (Python-Markdown) stays a dependency: `anchors.py` uses its `toc` slugify for the
GitLab heading-anchor scheme, and `upload_file(source_format='markdown')` (EP-8) still renders
with it until #1101 routes that entry point through this converter.

### Autolinks: a GFM rule, not linkify-it

markdown-it's own `linkify` needs `linkify-it-py` and doesn't follow GFM. Measured:
with fuzzy links on, it links `README.md`, `file.py` and `example.com` (any TLD-looking token);
with them off, it stops linking `www.` too; it also links `ftp://`. The GFM rule is short, so it's
a core rule over text tokens instead:

- `www.` or `http(s)://` plus a domain, or an email address, after whitespace, `*`, `_`, `~` or
  `(`. A text token's own start counts only at the start of the inline content, after a line
  break, or after an emphasis or strikethrough delimiter (`_AUTOLINK_BOUNDARY_TOKENS`). So, as in
  GFM, a URL right after a code span, a link, an inline tag (`<b>https://x.com</b>`) or a
  character like `:` (`URL:https://x.com`) isn't linked. The Python-Markdown-era bare-URL
  extension linked those last two; `CHANGELOG.md` says so.
- No `_` in the last two domain segments, and no empty segment. A scheme-ful link may have a
  one-segment domain (`http://localhost:8000`), as in cmark-gfm.
- Trailing `?!.,:*_~'"`, an unbalanced `)`, and a trailing `&entity;` are left outside the link.
  The domain is checked after that trim, since it can eat the domain (`http://__`, `www.__`
  aren't links), and a link is scheme-ful only if it starts with `http://` or `https://` (so
  `www.x.com/a://b` still gets `http://`).
- Runs after inline parsing, so a code span, an `<autolink>` or raw HTML is never re-matched; text
  inside a Markdown link or a raw-HTML `<a>` is skipped, since links can't nest.
- Linear in the text: emails are found outwards from each `@` (`_gfm_email_matches`), and
  `_trim_autolink` works back from the end with running paren counts. See "Review history".

`autolink_urls=False` drops the rule, so `www.`, email and `https://` are all plain text.

### `_preprocess`: plan rules D1 and D2

One pass over the lines, keeping a stack of open list items (`_ListItemColumns`: original and
rewritten marker and content columns). It keeps the line count, except for D2's inserted blank
lines, which `_rewrite` returns as lines with no source index so a quote run can put its
prefixes back.

**Code and raw HTML are never read as Markdown.** `_verbatim_lines` runs markdown-it's own block
parser (inline pass off) once, and returns every line of an indented code block or raw HTML block
and the body and closing fence of a fenced block, mapped to the block's first line. A fence
opened on a marker line (`` - ``` ``) or inside a quote is found the way the renderer finds it.
Those lines are only moved with the item they belong to (a fence body by its opening line's
shift), and only their item's own indentation is rewritten (`_shift_verbatim`): whitespace past
the item's content column is the code's, tabs included, so a Makefile recipe keeps its tab.

**D1: nesting width (#1071).** Plan rule D1 (`docs/qa/tests/docs_markdown.md`): a marker indented
at least 2 columns past the previous item's marker nests under it, whatever the parent marker's
width. CommonMark nests only at the parent's content column, so `1. A` / `  - a` (column 2 < 3)
doesn't nest, and under markdown-it the grandchildren of a 2-space numbered outline became
literal `1. Grandchild` text. For each marker line:

- pop items until the top's marker is at least 2 columns left of this one; an item within 0–1
  columns is a sibling, and the line moves as far as that sibling moved, not onto its column;
- under a parent, the marker moves to the parent's rewritten content column, plus however far
  past the original content column it already was, so 4-space and tab indents are unchanged;
- continuation lines move by their owning item's shift.

Right under paragraph text (a list item's own text counts), a marker opens a new list only if
CommonMark lets it interrupt a paragraph: a bullet or `1.`/`1)` with text after it. Otherwise
(`Some text` / `2019. A great year`) it is paragraph text. One exception: a child candidate short
of its parent's content column isn't inside the parent's paragraph at all, so CommonMark reads it
at the parent's own level (`1. A` / `  2. b` is two items), and so does the pass.

A tab after a moved marker is written as the spaces it spanned (`_moved_marker_line`): moved, the
same tab would reach a different tab stop and change the item's content column. Tab widths
after a marker count from the marker's column (`_space_after_marker`), and leading columns count
tabs to the next multiple of 4, as CommonMark does.

A run of quoted lines not indented into a list ends any open list and gets the same rules one
level in: each line's `>` prefix is stripped, the inner lines go through `_rewrite` with the
verbatim map sliced to them by bisect (no second parse, no scan of the whole map), and the
prefixes are put back, so `> 1. A` / `>   - a` nests. Past `_MAX_QUOTE_DEPTH` (markdown-it's
`maxNesting`, 100) quotes are left as written. A quote inside a list item isn't rewritten, and
neither is anything after a list ends (a blank line then unindented text, or a heading, quote,
fence or thematic break). A lazy line starting with `|` that isn't a table is paragraph text and
doesn't end the list.

**D2: a table starts its own block.** GFM lets a table interrupt a paragraph, but not a list
item's or a quote's lazy continuation, so `- B` / `| K | V |` / `|---|---|` made the rows more
item text. A blank line goes in before a table header only where it would be read that way:
right under a list item's text (or lazy text continuing it) or a quote run, and not indented into
the item. A table indented into an item already renders inside it, and one under a plain
paragraph already renders as a table; a blank line there would only make a list loose (and
`html_to_ast` then drops its bullets, #1111). A header needs a delimiter row with a `|` and the
same number of cells, so a setext underline (`a | b` / `---`) isn't split from its heading text.
Inside a quote, the inserted line is a bare `>`, so the table stays in the quote. A table indented
into an item right after a quote in that item (`- a` / `  > q` / `  | x |`) would be the quote's
lazy text, and a blank line would make the list loose; an HTML comment line (`_LAZY_BREAK`, which
`html_to_ast` ignores) ends the quote instead and keeps the table in the item. Two tables with
no blank line between stay one table (AJ-078: GFM ends a table only at a blank line or another
block).

**Where this departs from CommonMark.** Running all 652 CommonMark spec examples through
`_md_to_html` and plain markdown-it (same rules, raw destinations) differs in exactly four, all
by design: example 297 (`10) foo` / `   - bar`: the bullet nests), 311 and 313 (`1. a`, blank,
`  2. b`: `2.` nests under `1.`, where CommonMark has siblings or, in 313, a code block), and 488
(`[link](/my uri)` is a link, `_spaced_link_rule`).

## The HTML `html_to_ast` sees

Inventory of where markdown-it's HTML differs from Python-Markdown's, and what handles it:

| Shape | Python-Markdown | markdown-it | Handling |
|---|---|---|---|
| Tight item with a nested block | `<li>a<ul>` | `<li>a\n<ul>` (also before `<pre>`, `<table>`, `<blockquote>`) | **Changed:** `_interrupt_open_block` drops trailing whitespace holding a line break from the raw text before the block. It was reaching the Docs API as an empty paragraph under every parent item. A `<br>`'s own break is kept. |
| Rule inside an item | (never produced) | `<li>item\n<hr />\n</li>` | **Changed:** an `<hr>` after text in an open block, or in a resumed segment (after a nested list or quote in the item), ends that segment, emits the rule's empty paragraph, and resumes the block. `<li><hr>` with no text keeps #401's dropped-construct boundary. |
| Text after a block in an item | (never produced) | `<hr />\nmore</li>` | **Changed:** a resumed segment drops the line break at its start, as the break before a block is dropped. An authored `&nbsp;` there isn't ASCII whitespace and stays (#444). |
| Loose item | `<li>\n<p>a</p>\n</li>` | same | Unchanged here: handled by community PR #1164 (#1111), merged into `develop` before this PR. markdown-it produces it more often, since it attaches an indented paragraph or code block to the item instead of dropping it out of the list. |
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
  match their expectation on screen; r16's agenda is one list numbered 1–4 in the HTML and the AST,
  but on screen Docs still restarts it at 1 after each sub-list, which is the emitter's #1072,
  live in TC-MD016); blocks inside list items (TC-MD201); fenced
  code inside items renders as code without the info string as text; strikethrough; www/email
  autolinks; `\` escapes; adjacent quotes; a bare `-` no longer becomes a setext heading.
- **Loose lists, with #1164 in:** in CommonMark one blank line anywhere in a list (`- a`, `- b`,
  blank, `- c`) makes the whole list loose (`<li><p>`), and so does an item with an indented
  paragraph or code block under it (r06's numbered steps, TC-MD107, TC-MD108 LX-08, TC-MD203's
  list-after-list pairs, which CommonMark merges into one loose list). Without #1164 every such
  item lost its bullet (#1111); with it, which this branch merged before approval, every one keeps
  its bullet. Python-Markdown kept some of those items bulleted, or dropped the blocks out of the
  list and restarted the numbering. A block inside a numbered item now stays inside one `<ol>`, so
  the AST keeps every item ordered, but the emitter still splits the list around the block and
  Docs restarts the numbering on screen (#1094).
- **A setext underline under an item's text** (`- a` / `  ---`) makes that text a Heading 2 inside
  the item, as CommonMark reads it; Python-Markdown kept the item and a rule. The heading then
  loses its bullet in the AST (#1094's open question). `***` is a rule in either parser.
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

- Strip front matter (#1173), keep an empty list item (#1075), keep a loose item's bullet (#1164, already in `develop`),
  or fix hard and soft breaks (#1117, #1093). Each is in the HTML → AST step or its own ticket.
- Change EP-8 (`upload_file`), which keeps Python-Markdown until #1101.
- Read table column alignment.

## Review history

PR #1228's QA rounds, and what each changed. The invariants they produced are in `CLAUDE.md`'s
`docs/md_to_html.py` entry.

- **Round 1 (8 findings).** The two pre-passes tracked fences by hand, so they missed a fence
  opened on a list-marker line and every raw HTML block, and rewrote code inside them. Replaced
  by `_verbatim_lines`, from markdown-it's own block parser. Also: the pass ignored CommonMark's
  paragraph-interrupt rule (`2019. A great year` opened a list); a bare `---` counted as a
  delimiter row, splitting a setext heading; the email regex was quadratic on `_`-heavy text
  (`"a_" * 20000` took about a second), replaced by the scan out from each `@`; text after a code
  span or link was autolinked; the spaced-image rule didn't unescape or respect `posMax`; tab
  widths after a marker counted from column 0. A run of the CommonMark spec examples then found
  siblings snapping onto their sibling's rewritten column (example 310).
- **Round 2 (9 findings).** D2's blank line went in before a table already indented into an
  item, which made the list loose and lost its bullets: D2 moved into the D1 pass, which knows
  which item a line belongs to, and the separate table pass (and its second block parse) went
  away. Also: `_trim_autolink` was quadratic on a run of entities or parens; the quote recursion
  had no depth cap (`">" * 1200` raised `RecursionError`) and parsed again per quote run; the
  shared parsers' ruler caches were built lazily, racing across `to_thread` workers;
  `_md_to_html(x, None)` raised `KeyError`; and the `html_parser` trim before a block removed a
  `<br>`'s break, now marked `_LineBreak` so only source text is trimmed. The stricter GFM link
  boundary (`URL:https://x.com`, `<b>https://x.com</b>` not linked) was kept and documented.
- **Round 3 (10 findings, plus the live matrix).** The branch had fallen behind `develop`, so CI
  hadn't run; merged. In `html_parser`, a rule after a nested list in an item took the
  dropped-construct path and left the resumed segment's `\n`s as empty bullets, and text after a
  rule kept a leading break: a resumed segment now takes the `<hr>` interrupt path and drops a
  leading line break. In the pre-pass: each quote run scanned the whole verbatim map (now a bisect
  slice); moving an item rebuilt a fence body's whole indentation, turning a recipe tab into
  spaces (`_shift_verbatim` keeps the code's own whitespace); `maxNesting` 20 dropped deep list
  text (now 100, with `_MAX_QUOTE_DEPTH` matching); a lazy `|` line ended the list; and a table
  after a quote inside an item stayed the quote's lazy text (`_LAZY_BREAK`). Spaced destinations
  now take a title, and links get the same rule as images, since existing `.md` files lose
  `[notes](./My Notes.md)` otherwise; the CommonMark spec run caught two edges of that rule
  (examples 41 and 568). The "r16 keeps 1–4" claim was the HTML's, not the screen's.
- **Round 4 (6 findings).** The loose-list regression is wider than round 1's wording said: one
  blank line anywhere makes a CommonMark list loose, and every item then loses its bullet until
  #1164; the PR now waits for #1164 (QA won't approve without it). The autolink domain was checked
  before trimming (`http://__` linked an empty host) and the scheme by `"://" in label`; the
  resumed-segment trim lacked the `<pre>` guard its counterpart has; a setext underline under item
  text is documented as a behavior change; and a stale dev-group `markdown-it-py` pin was removed.
- **Round 5 (the `develop` merge).** #1164 merged, and `develop` was merged in: loose lists keep
  their bullets, and a code block or paragraph inside a numbered item keeps one `<ol>`
  (`TestLooseListsAfter1164`).
