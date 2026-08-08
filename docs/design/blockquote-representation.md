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

**Interaction with list nesting (not a bug, documented for the next person surprised by
it):** a blockquote-wrapped list item can end up with a visually deeper indent than
`36pt × blockquote_depth` alone would suggest, when Markdown's `sane_lists` extension
parses the quoted item as also being one level deeper in list nesting (lazy continuation of
a preceding list, e.g. `- Item\n> - Quoted item` with no blank line between). In that case
the item's `BulletItem.depth` (list nesting) and `blockquote_depth` (quote nesting) are both
> 0, and their two indent contributions — the list preset's own per-level indent (applied
via `createParagraphBullets`, a separate mechanism) and this feature's explicit
`indentStart` — are genuinely orthogonal API properties that both apply. Confirmed live;
not something this feature should try to compensate for, since the extra depth accurately
reflects two real, independent kinds of nesting.

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

- No reverse conversion (Doc → Markdown/HTML `blockquote` output) — this project has no
  Doc-to-source export path at all currently, matching the existing precedent for other
  one-way conversions (e.g. `anchors.py`'s heading-anchor resolution).
- Does not attempt to detect an *existing* Google Doc's manually-applied indent+border as
  "this was a blockquote" on any round-trip read — there is no such round-trip path in this
  codebase (AST flows one direction, HTML/Markdown → Docs), so this concern doesn't arise.
- No comprehensive multi-construct fixture — tracked separately as
  [#477](https://github.com/khuisman/mcp-gee-sweet/issues/477), which explicitly depended on
  this issue landing first.
