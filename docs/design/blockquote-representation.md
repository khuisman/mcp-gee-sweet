# Design: Blockquote Representation in the Docs AST

**Date:** 2026-08-06
**Issue:** [#476](https://github.com/khuisman/mcp-gee-sweet/issues/476)
**Status:** shipped, fixed in PR #546's own QA round 1 (see below)

## Problem

Neither the AST schema (`ast.py`) nor the HTML parser (`html_parser.py`) had any concept
of a blockquote. A `<blockquote>` (HTML) or `> quoted text` (Markdown, core syntax — no
extension needed) converted to a plain, visually indistinguishable `Paragraph`/`BulletItem`/
etc. Text content survived; the semantic distinction did not.

## Decision: a flat `blockquote_depth` field, not a wrapper node

The issue's own text flagged two options: a new `Blockquote` node wrapping child content,
or a flag on the existing leaf node types. This follows the flag approach, for the same
reason `BulletItem.depth` encodes list nesting as an integer on each leaf node rather than
a wrapping `List` node, and `BulletItem.checked` encodes task-list state as a field rather
than a new node type (see `docs-ast-pipeline.md`'s Nested Table Rewrite section for the
one case where this project *did* choose a wrapper — nested tables — and why: table cells
need genuine structural nesting to express colspan/rowspan/multi-child ordering, which a
flat depth counter can't). A blockquote can wrap arbitrary block content (paragraphs,
headings, lists, even a further nested blockquote), but nothing about *rendering* one
requires a wrapper — each contained leaf just needs to know how deep inside a blockquote
it is, exactly the same shape of problem list nesting already solved.

`blockquote_depth: int = 0` was added to `Heading`, `Paragraph`, `BulletItem`, and
`NamedBlock` — the four `DocNode` variants that already share `paragraph_style`. `0` means
"not in a blockquote"; `N ≥ 1` is the nesting depth, supporting `> > nested` /
`<blockquote><blockquote>`.

**Rejected: reusing `paragraph_style.indent_start` directly instead of a new field.**
`ParagraphStyle.indent_start` already exists in the schema, and the issue floated reusing
it. Rejected because it conflates two independent concerns: "this paragraph happens to be
indented" (a Phase 3 styling input, settable by a caller for unrelated reasons) and "this
paragraph is semantically a blockquote" (a parser-derived fact used to decide *what to
render*, including the left border, which is not just an indent value). A dedicated field
keeps the semantic marker independent of Phase 3's styling knobs, matching how
`BulletItem.checked` is a dedicated field rather than reusing an existing Run flag.

## Parser: reusing the interrupt/resume machinery

`html_parser.py` already has a generic mechanism for a block-ish construct (`<ol>`, `<ul>`,
`<table>`, `<pre>`) interrupting whatever leaf block is currently open, flushing it, and
resuming it afterward (`_interrupt_open_block` / `_resume_interrupted_block`). `<blockquote>`
plugs into this unchanged: on open, `_interrupt_open_block("blockquote")` runs (flushing
any outer text at the pre-increment depth, since that text is not inside the quote) and
`self._blockquote_depth` increments; on close, `_resume_interrupted_block("blockquote")`
runs before decrementing (so a malformed trailing flush during resume — content left open
right up to the close tag — still reads the correct "still inside" depth).

`_emit_block_node` reads `self._blockquote_depth` directly at the moment it builds each
node, the same way `_make_bullet_item` reads `len(self._list_ordered)` fresh rather than
threading depth through as a parameter. No new state machine, no `_BlockFrame` changes —
blockquote's interruption is always a single matching open/close pair (unlike `<ol>`/`<ul>`,
which the existing frame design tolerates being mismatched); the plain
`frame.interrupted_by != closing_tag` equality check in `_resume_interrupted_block` already
handles it correctly.

## Emitter: left border + scaled indent

Google Docs has no native blockquote `namedStyleType` — `ParagraphStyle` in the Docs API
schema has no direct blockquote-style field either. Two options were live-tested against a
scratch document before committing to either (per this project's rule to verify an API
premise live before implementing — see CLAUDE.md's `tabStops`/#404 cautionary tale):

- `paragraphStyle.indentStart` — already used elsewhere in this codebase's schema, known
  writable.
- `paragraphStyle.borderLeft` — never previously used in this codebase. Its discovery-schema
  description carries no "read-only" note, but that alone wasn't trusted (#404's `tabStops`
  looked identical and turned out unsettable). Confirmed live via a scratch doc:
  `updateParagraphStyle` with `borderLeft` set succeeds, and a re-fetch shows it persisted.

Both are applied together via one `updateParagraphStyle` request per blockquote-tagged node
(`_blockquote_style_request` in `emitter.py`):

- `indentStart`: `36pt × blockquote_depth` — scales with nesting.
- `indentFirstLine`: the same value as `indentStart` (#1056). The Docs API's
  `indentFirstLine` is absolute, measured from the margin like `indentStart`, not an
  offset from it. Left unset, it stays 0, so a single-line quote's only line sat at the
  margin and only wrapped continuation lines were indented: the quote showed nothing but
  its border, and a nested quote looked no deeper than its parent.
- `borderLeft`: a constant gray (`0.6, 0.6, 0.6`), 3pt solid line, 8pt padding — a visual
  "quote bar," independent of depth.

Applied uniformly regardless of node type (`Heading`/`Paragraph`/`NamedBlock`/`BulletItem`
can all be blockquote content) rather than special-cased per type, since the condition is
just `node.blockquote_depth > 0`.

**Rejected: forcing `italic=True` on contained runs.** The issue's own text floated this
("e.g. indent + optional italic") as a common blockquote convention. Rejected because it
would override or conflict with a run's own explicit formatting decisions (e.g. bold text
quoted verbatim should stay bold, not be silently forced italic too) — the border + indent
already give a strong, unambiguous "this is a quote" visual without touching text styling
at all.

**Quoted list items (#1056).** `createParagraphBullets` writes the list preset's own
`indentStart`/`indentFirstLine` onto every paragraph it bullets, overwriting whatever was
there. The bullet pass runs after the per-node styling pass, so a quoted list item's quote
indent was silently replaced and a quoted list sat at exactly an unquoted list's indent,
with only the border to tell them apart. (This section used to say the two indents "both
apply"; live reads show they didn't. The deeper indent it described came from list
nesting alone.)

So a `BulletItem`'s blockquote request is emitted after the whole bullet pass, not in
the per-node pass, and before the combined table/image insert pass. By then every
synthetic depth-tab in the doc has been consumed, so its range maps through
`_after_bullet_pass` exactly like the table and image positions do: the start moves back
by the tabs ahead of the item, the end also by the item's own. Paragraph styling doesn't
shift anything, so the inserts that follow are unaffected. (PR #1089 round 1 first put
each request inside its own run's bullet requests, with a third hand-built copy of the
tab-shift arithmetic; QA asked for one mapping, and the whole-pass placement allows it.)

Its indents are the list level's own plus the quote's: `indentStart = 36 + 36n + 36d` and
`indentFirstLine = 18 + 36n + 36d` for nesting level `n` and quote depth `d`, keeping the
glyph's hanging indent (`emitter.list_level_indents`). The level geometry (18/36 at level
0, +36 per level) is the same for both presets the emitter uses,
`BULLET_DISC_CIRCLE_SQUARE` and `NUMBERED_DECIMAL_ALPHA_ROMAN`, confirmed live. Docs caps
`nestingLevel` at 8: an item with more leading tabs lands at level 8, so `n` is capped at
8 too. Uncapped, items nested 9 and 10 deep got indents for levels that don't exist and
read back as quoted two and three times (PR #1089 QA round 1, live).

`doc_to_ast.py`'s `_infer_blockquote_depth` subtracts the list level's own `indentStart`
(read from the doc's `lists` map, falling back to the preset value) before dividing by
36, so a level-1 item quoted once reads back as quote depth 1, not 2. A bordered list item
written before #1056, with only the level's own indent, still reads as depth 1.

## Adjacent quotes and spacing (#1098)

Docs joins the left borders of adjacent paragraphs with the same border and indents into
one continuous bar. Two separate quotes in a row therefore rendered as one, and nothing
put space between a quote and the paragraphs around it. Checked live on a scratch doc
(PDF export), each pair styled as a depth-1 quote:

| Between the two paragraphs | Result |
|---|---|
| nothing | one bar |
| `spaceBelow`/`spaceAbove` 12pt | one bar, with the gap inside it |
| zero-width `borderTop`/`borderBottom` | one bar |
| border color 0.6 vs 0.61 (stored as 0.6117647), width 3 vs 3.01 | one bar |
| border padding 8 vs 9 | two bars, visibly offset by 1pt |
| an empty unbordered paragraph | two bars |
| an empty unbordered paragraph collapsed to 1pt (as before a table), quotes spaced 8pt | two bars, a clean gap |

The last row is what the emitter does. A flat `blockquote_depth` can't tell "the second
paragraph of one quote" from "the first paragraph of the next quote", so the parser
also records `blockquote_path` on every leaf node: the ids of the `<blockquote>`
elements it sits in, outermost first, a fresh id per element. Two quoted nodes are in
one quote when one path is a prefix of the other. The ids are arbitrary, so the field is
excluded from node equality; `doc_to_ast.py` leaves it empty, and empty paths are never
separated.

`emitter._with_quote_separators` inserts an empty `Paragraph` between two adjacent quoted
nodes that aren't in one quote, and `_collapse_paragraph_requests` shrinks it (the same
styling the blank paragraph before a table gets). The separator is unquoted even between
two quotes nested in one outer quote: carrying the outer quote's border, its 1pt height
left a stray dash of that bar. The outer bar already breaks around the deeper-indented
nested quotes, so nothing is lost. A separator between two quoted lists also splits them
into two Docs lists, as the source has.

`_block_spacing` gives a quoted node 8pt above where its quote meets content outside it
(an unquoted node, a table, or the start) and 8pt below likewise, and nothing between
the paragraphs of one quote. A code block gets 8pt above and below, which is what tells
two consecutive code blocks apart.

Two exceptions, both from PR #1199's QA round 1:

- A separator is spaced on one side only, below the quote before it. Spaced on both
  sides, two separate quotes sat about 41px apart, baseline to baseline, against 31px
  between a quote and a plain paragraph.
- A `Heading`, or a `NamedBlock` with a TITLE/SUBTITLE style, gets no quote-edge space.
  An explicit `spaceAbove` replaces the named style's own, so a quoted H1 lost HEADING_1's
  20pt above.

The paragraphs `insertTable` leaves before a table take the style of the block after the
table (#1097). At full height, the one between two tables showed a following list's
bullet as an empty numbered item, and collapsed or not, they pushed that list's numbering
on and carried a following quote's indent and border. `_build_blank_para_before_table_collapses`
now deletes their bullets and clears `indentStart`, `indentFirstLine`, and `borderLeft`,
in that order, since `deleteParagraphBullets` adds indent to keep a paragraph's visual
level. The table cells themselves still take the following block's style, including its
indent; that part is #1097.

**Markdown input is still affected by the parser.** Python-Markdown parses `> a`, a blank
line, `> b` as one `<blockquote>` with two paragraphs, where CommonMark has two quotes. That
reaches the AST as one quote, so it renders as one. Switching the parser (#1116) fixes it
with no change here. HTML input with two `<blockquote>` elements already renders as two.

## QA round 1 (PR #546): two gaps in the interrupt/resume integration

Reproduced directly against parser output (`html_to_ast`), no live Google API calls
needed — both were pure AST-construction bugs.

**1. Three `Paragraph`-construction sites bypassed `_emit_block_node` entirely.** The
initial implementation's single point of truth — "`_emit_block_node` reads
`self._blockquote_depth` directly at the moment it builds each node" — was true for
`_emit_block_node` itself, but `html_parser.py` has three other call sites that construct
a `Paragraph` node directly without going through it: a bare `<hr>` with no open block, a
bare `<img>` with no open block, and `<pre>`'s own close-tag handler (which builds its
`Paragraph` directly rather than dispatching through `_emit_block_node`, for reasons
unrelated to blockquotes — see the `<pre>`/#443 history in `CLAUDE.md`). All three
silently defaulted to `blockquote_depth=0` when they were the sole content of a
`<blockquote>`. Fixed by passing `blockquote_depth=self._blockquote_depth` explicitly at
each of the three sites — the "single point of truth" claim was correct in spirit but
incomplete in coverage; the fix doesn't introduce a fourth code path, it just closes the
three gaps in the existing rule.

**2. Malformed HTML with `<blockquote>` opening at top level lost the split entirely** —
`<blockquote><p>text</blockquote>after` merged into one `Paragraph(text="textafter",
blockquote_depth=0)` instead of two nodes. Root cause traced deeper than the blockquote
code itself: `_interrupt_open_block` correctly pushes no frame when nothing is open to
interrupt (there's nothing to resume), but `_resume_interrupted_block`'s own
flush-whatever's-open step (the PR #478 fix, see that function's docstring) was only
reachable from *inside* the "a frame exists and will be resumed" branch — so a wrapper
construct that opened frameless (nothing outer to interrupt) with its own inner content
left open at close time skipped the flush entirely, regardless of whether that content
was blockquote's or anyone else's. Confirmed this is not blockquote-specific: plain
`<ul>text</ul>after` (no blockquote involved, verified against `develop` before this
PR's own changes) reproduces the identical merge. Fixed by moving the flush to run
unconditionally at the top of `_resume_interrupted_block`, before the
`if not self._block_stack: return` check — closing the gap for every wrapper construct
(`<ol>`/`<ul>`/`<table>`/`<pre>`/`<blockquote>`) at once, per this project's "take the
generalized fix, not just the reported case" rule (see `.claude/team-roles/dev.md`'s
Retro section), rather than a blockquote-specific patch that would have left the
identical defect reachable through `<ul>`/`<ol>` at top level.

## What this does NOT do

- At the time of #476 there was no Doc → Markdown read path. One exists now
  (`get_doc_as_markdown`, `docs/design/doc-to-markdown.md`): `doc_to_ast.py`'s
  `_infer_blockquote_depth` reads a paragraph as quoted only when it carries both a
  `borderLeft` and an `indentStart` beyond its list level's own (see "Quoted list items"
  above), so a hand-indented paragraph without a border isn't mistaken for a quote.
- No comprehensive multi-construct fixture — tracked separately as
  [#477](https://github.com/khuisman/mcp-gee-sweet/issues/477), which explicitly depended on
  this issue landing first.
