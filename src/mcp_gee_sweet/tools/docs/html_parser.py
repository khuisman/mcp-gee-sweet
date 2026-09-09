"""HTML string → Document AST."""

from __future__ import annotations

import html as html_module
from dataclasses import dataclass
from html.parser import HTMLParser

from .ast import BulletItem, Cell, DocNode, Heading, Image, NamedBlock, Paragraph, Row, Run, Table

_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}
_NAMED_BLOCK_STYLES = {"title": "TITLE", "subtitle": "SUBTITLE"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_INLINE_BOLD = {"b", "strong"}
_INLINE_ITALIC = {"i", "em"}
_INLINE_UNDERLINE = {"u"}
_INLINE_STRIKE = {"s", "strike"}
# HTML void elements: never get a matching close tag from Python's stdlib
# HTMLParser unless the source text itself self-closes them ("<img ... />"),
# since HTMLParser has no built-in HTML5 void-element awareness. Excluded from
# _tag_depth tracking below — otherwise one of these written without a
# trailing slash (e.g. "<img src=\"x\">", plain "<hr>") would increment the
# depth counter with nothing to ever decrement it, permanently breaking the
# depth-0 "genuinely bare text" check in handle_data for the rest of the
# document (#343 follow-up).
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


@dataclass
class _BlockFrame:
    outer_tag: str  # the interrupted block's own tag (li, p, h1-6)
    interrupted_by: str  # the tag whose matching close should restore this frame
    named_style: str | None  # the interrupted block's _block_named_style, if any
    # For a list interruption (interrupted_by in {"ol", "ul"}) only: the
    # depth of self._list_ordered *before* the interrupting list's own push
    # — the depth this frame should resume at once the interrupting list
    # (and anything nested inside it) has closed. ol/ul are the one category
    # HTML lets mismatch in practice (an <ol> closed by a stray </ul> or vice
    # versa, both closing the same visual construct), so _resume_interrupted_
    # block matches list interruptions by returning to this depth rather
    # than requiring the closing tag to equal interrupted_by exactly (#450).
    # None for every other interrupted_by category (table/pre/block-tag),
    # each of which has exactly one possible closing tag and so can't be
    # mismatched the same way.
    list_depth: int | None


def _px_to_pt(value: str) -> float | None:
    """Parse a width attribute value to points. Skips percentages."""
    v = value.strip().lower().rstrip("px")
    try:
        return float(v) * 72 / 96
    except ValueError:
        return None


def _make_image(attr_dict: dict, src: str) -> Image:
    """Build an Image node from an <img> tag's attributes. width/height are
    only ever present on raw HTML <img> tags (content_format="html") — plain
    markdown "![alt](src)" has no syntax for them, so they're None there."""
    return Image(
        src=src,
        alt=attr_dict.get("alt") or None,
        width=_px_to_pt(attr_dict.get("width") or ""),
        height=_px_to_pt(attr_dict.get("height") or ""),
    )


class _AstParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._nodes: list[DocNode] = []

        # --- block context ---
        self._block_tag: str | None = None  # current block tag (h1-h6, p, li, pre)
        # True once the current self._block_tag was restored by
        # _resume_interrupted_block rather than freshly opened. A resumed
        # block's own flush is only meant to capture optional *trailing*
        # content after the nested construct that interrupted it — the
        # block's real content, if any, was already emitted at interrupt
        # time. See self._block_had_unsupported_content for how an empty
        # flush's preserve-or-drop decision (#401) is actually made.
        self._block_resumed = False
        # True once some construct inside the current block's current segment
        # (since it was last freshly opened or resumed) was silently dropped
        # instead of contributing a run — an unsupported void element like
        # <img>, a bare <hr>, or any other unrecognized tag with no text of
        # its own (see the generic inline-element fallthrough below). Reset
        # every time a new segment begins (fresh open or resume) so it always
        # reflects only the segment about to be flushed. This is the signal
        # _emit_block_node's preserve_if_empty is keyed on: an empty flush is
        # worth preserving (#401) exactly when something was actually dropped
        # to produce it, not merely because the segment never had any content
        # to begin with — e.g. an <li> that wraps only a nested <ul> with no
        # text of its own is empty for a completely unrelated, common reason
        # and must NOT be preserved as a spurious empty bullet.
        self._block_had_unsupported_content = False
        self._list_ordered: list[bool] = []  # stack: True=ol, False=ul
        self._in_pre = False  # inside <pre>; text is literal, runs get font_family

        # Nesting depth of open <blockquote> tags (#476). Read directly by
        # _emit_block_node at the moment each leaf node is built, the same way
        # _make_bullet_item reads len(self._list_ordered) fresh rather than
        # threading depth through as a parameter — correct as long as this is
        # only mutated in handle_starttag/handle_endtag's own "blockquote"
        # branches, which bracket exactly the content that's actually inside
        # the tag via the existing _interrupt_open_block/_resume_interrupted_
        # block machinery (the same mechanism table/pre/ol/ul already use).
        self._blockquote_depth = 0

        # Depth of open non-block tags (span, b, a, unrecognized tags, ...)
        # that reach the generic inline-element fallthrough below. Lets
        # handle_data tell genuinely bare top-level text (depth 0, e.g. plain
        # "hello world" with no wrapping tag at all — #343) apart from text
        # that's merely wrapped in an inline tag with no block ancestor (e.g.
        # "<span>no blocks</span>", depth 1) — the latter is intentionally
        # dropped (see test_inline_only_html_skips_batchupdate). _VOID_TAGS
        # are excluded since they never get a matching close tag.
        self._tag_depth = 0

        # --- inline formatting stacks ---
        self._bold_depth = 0
        self._italic_depth = 0
        self._underline_depth = 0
        self._strike_depth = 0
        self._code_depth = 0  # inline <code> nesting; ignored inside <pre>
        self._link_url: list[str] = []  # stack of href values

        # --- current run buffer ---
        self._run_buf: list[str] = []
        self._pending_runs: list[Run | Image] = []

        # --- table context ---
        self._table_depth = 0
        self._table_stack: list[_TableBuilder] = []

        # --- named block style (data-style on <p>) ---
        self._block_named_style: str | None = None

        # --- block-interruption stack ---
        # One entry per open block (of any kind — li, p, h1-6, pre) that a
        # nested construct (ul/ol, the outermost table, pre, another
        # _BLOCK_TAGS tag) interrupted mid-buffer. See _interrupt_open_block /
        # _resume_interrupted_block. Each entry records which tag would
        # legitimately end the interruption, so a close tag only ever pops
        # the frame it actually owns — malformed/mismatched HTML degrades
        # locally instead of a later, unrelated close tag popping (and
        # corrupting) a frame that isn't its own.
        self._block_stack: list[_BlockFrame] = []

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _flush_run(self):
        """Commit buffered text as a Run (if non-empty) to pending_runs."""
        text = "".join(self._run_buf)
        if not text:
            return
        self._run_buf = []
        run = Run(
            text=text,
            bold=True if self._bold_depth > 0 else None,
            italic=True if self._italic_depth > 0 else None,
            underline=True if self._underline_depth > 0 else None,
            strikethrough=True if self._strike_depth > 0 else None,
            link_url=self._link_url[-1] if self._link_url else None,
            font_family="Courier New" if (self._in_pre or self._code_depth > 0) else None,
        )
        self._pending_runs.append(run)

    def _flush_pending_runs(self) -> list[Run | Image]:
        self._flush_run()
        runs, self._pending_runs = self._pending_runs, []
        return runs

    def _make_bullet_item(self, runs: list[Run | Image]) -> BulletItem:
        ordered = self._list_ordered[-1] if self._list_ordered else False
        depth = len(self._list_ordered) - 1
        # Detect task list markers written as literal [x] / [ ] by the markdown library.
        # An image can never be the first child here in practice (markdown always wraps
        # a bare "![]()" in its own <p>, never mixes it as literal leading text before a
        # checkbox marker) but the isinstance guard keeps this robust regardless.
        checked = None
        if runs and isinstance(runs[0], Run):
            first_text = runs[0].text
            if first_text.startswith(("[x] ", "[X] ")):
                checked = True
                runs[0].text = first_text[4:]
                if not runs[0].text:
                    runs.pop(0)
            elif first_text.startswith("[ ] "):
                checked = False
                runs[0].text = first_text[4:]
                if not runs[0].text:
                    runs.pop(0)
        return BulletItem(runs=runs, depth=depth, ordered=ordered, checked=checked)

    def _close_dangling_inline_formatting(self):
        """A block boundary is starting while inline formatting tags may still
        be open (e.g. an unclosed <b> before a nested list/table/pre/etc). Real
        HTML doesn't allow block content inside a true inline element — a
        browser would auto-close it here — so treat the boundary as an implicit
        close for all inline state. Otherwise formatting silently leaks into
        every node for the rest of the document, since the tag that would have
        decremented these depths never arrives.
        """
        self._bold_depth = 0
        self._italic_depth = 0
        self._underline_depth = 0
        self._strike_depth = 0
        self._code_depth = 0
        self._link_url = []

    def _emit_block_node(
        self, tag: str, runs: list[Run | Image], *, preserve_if_empty: bool = False
    ):
        """Turn a closed block's buffered runs into the node type its own tag
        implies (Heading / BulletItem / NamedBlock / Paragraph) — shared by
        the normal close-tag path and by _interrupt_open_block, so both stay
        in sync with exactly one dispatch rule.

        preserve_if_empty=True (both callers pass
        self._block_had_unsupported_content) additionally keeps a node whose
        runs came back completely empty because something inside this
        segment was silently dropped (e.g. its only child was an unsupported
        void element like <img>, or a bare <hr>), emitting it as an empty
        node (runs=[]) so its paragraph boundary survives (#401), instead of
        vanishing outright. An empty result that *isn't* due to dropped
        content — e.g. an <li> that wraps only a nested <ul> with no text of
        its own — leaves this False and emits nothing, since there's no
        boundary to lose: that segment was never going to have its own node
        either way.

        Whitespace-only text (runs non-empty but strips to nothing, e.g. a
        lone space or `&nbsp;`) is a separate case from the runs=[] one
        above (#402): markdown authors commonly write a standalone `&nbsp;`
        line as a deliberate blank-line spacer, since a literal blank line
        collapses in markdown — but that's specifically a `<p>` convention
        (blank lines only collapse *between paragraphs*; it doesn't apply to
        list items or headings the same way). A *freshly*-closed `<p>`
        (self._block_resumed False — opened and closed with nothing in
        between, e.g. `<p>&nbsp;</p>`) always keeps that whitespace text,
        unconditional on preserve_if_empty, since there's real (if
        invisible) content here to lose, not just a boundary. Every other
        tag (`<li>`, `<h1>`-`<h6>`) keeps the pre-#402 behavior of always
        dropping whitespace-only text — PR #441's own QA round live-caught a
        first version of this fix that wasn't scoped to `<p>` at all,
        producing a stray bullet glyph / stray heading with only invisible
        content for `<li>&nbsp;</li>` or `<h1>&nbsp;</h1>` between two real
        siblings, which isn't the blank-line-spacer convention this fix is
        for. A *resumed* `<p>`'s whitespace-only trailing flush is a
        different animal too, and must NOT get the fresh-`<p>` treatment
        either: it's markup-formatting noise (e.g. the indentation newline
        between a nested list's `</ul>` and the outer `<li>`'s own `</li>`),
        not authored content — confirmed live via
        test_nested_list_via_markdown_preserves_parent_text, where treating
        it as #402 content injected a spurious extra list item for that
        stray "\n". Both the non-`<p>` and resumed-`<p>` cases fall back to
        the same preserve_if_empty gate the runs=[] case already uses (a
        real drop elsewhere in the same segment still earns a boundary
        node; an ordinary formatting artifact doesn't). Emitter.py's
        ast_to_requests() no longer special-cases this text at all — it
        emits whatever text a kept node carries, whitespace or not.

        An Image (#333) counts as real content the same way non-whitespace
        text does: a node whose runs are e.g. just [Image(...)], with no
        Run at all, must never hit the empty-drop path below just because
        joining its (nonexistent) Run text yields "".
        """
        text = "".join(r.text for r in runs if isinstance(r, Run)).strip()
        has_image = any(isinstance(r, Image) for r in runs)
        if not text and not has_image:
            is_fresh_paragraph_whitespace = tag == "p" and bool(runs) and not self._block_resumed
            if not is_fresh_paragraph_whitespace and not preserve_if_empty:
                return
        if tag in _HEADING_TAGS:
            level = int(tag[1])
            self._nodes.append(
                Heading(level=level, runs=runs, blockquote_depth=self._blockquote_depth)
            )
        elif tag == "li":
            bullet = self._make_bullet_item(runs)
            bullet.blockquote_depth = self._blockquote_depth
            self._nodes.append(bullet)
        elif tag == "p" and self._block_named_style:
            self._nodes.append(
                NamedBlock(
                    style_type=self._block_named_style,
                    runs=runs,
                    blockquote_depth=self._blockquote_depth,
                )
            )
        else:
            self._nodes.append(Paragraph(runs=runs, blockquote_depth=self._blockquote_depth))

    def _interrupt_open_block(self, new_construct_tag: str):
        """A block-ish construct (new_construct_tag: 'ul', 'ol', 'table',
        'pre', or a _BLOCK_TAGS tag) is opening. If a block is currently
        open — of *any* kind, not just <li> — its buffered text must be
        flushed and emitted using its own real node type *now*, before
        descending into the nested construct. Waiting until the outer
        block's own close tag would both let the nested construct's start
        tag clobber the shared buffer (#335, and — one level up — headings/
        paragraphs interrupted the same way) and emit the outer block after
        its children, since a streaming parser closes children before their
        parent.

        Pushes a frame recording exactly which tag closing would legitimately
        end this interruption, so _resume_interrupted_block can restore it —
        recovering trailing text after the nested construct instead of
        dropping it. No-ops (pushes nothing) if nothing was open.
        """
        if self._block_tag is None:
            return
        outer_tag = self._block_tag
        outer_named_style = self._block_named_style
        runs = self._flush_pending_runs()
        self._emit_block_node(
            outer_tag, runs, preserve_if_empty=self._block_had_unsupported_content
        )
        self._block_stack.append(
            _BlockFrame(
                outer_tag=outer_tag,
                interrupted_by=new_construct_tag,
                named_style=outer_named_style,
                list_depth=(len(self._list_ordered) if new_construct_tag in ("ol", "ul") else None),
            )
        )
        self._block_tag = None
        self._block_named_style = None
        self._close_dangling_inline_formatting()

    def _resume_interrupted_block(self, closing_tag: str):
        """The matching close for a construct that may have interrupted an
        open block (see _interrupt_open_block) has been reached.

        For every interrupted_by category except lists, only restores a
        block if the top of the stack was genuinely interrupted *by this
        exact tag* — an unrelated or mismatched close tag leaves the stack
        untouched rather than popping a frame it doesn't own, so malformed
        HTML degrades locally instead of a stray close corrupting unrelated
        later content with the wrong reopened block.

        Lists are the one category HTML lets mismatch in practice (<ol>
        closed by </ul> or vice versa — both close the same visual
        construct). For those, match by returning to the list-nesting depth
        recorded at interrupt time (frame.list_depth) instead of requiring
        the closing tag to equal interrupted_by exactly (#450): depth is the
        real signal that the interrupting list has closed, tag identity
        isn't. The frame is always popped once that depth is reached, even
        on a mismatch, so it can never be left stuck for some later,
        unrelated list to pop by tag-name coincidence — but the outer block
        is only actually *resumed* (self._block_tag restored) on an exact
        tag match; a mismatched close proves the interrupting list ended but
        never proves the outer block's own close tag was seen, so restoring
        it would be guessing. Requires self._list_ordered to already reflect
        this closing tag's own pop (see handle_endtag's list-context
        section) — the depth check needs the post-pop count.

        Before checking for a frame to resume at all, flushes whatever block
        is currently open (self._block_tag), if any — unconditional on
        whether a frame exists on self._block_stack, not just when one is
        about to be resumed. Normally nothing is open at this point — every
        other path that closes a block routes through _interrupt_open_block
        or a block-tag's own close handler, both of which already flush
        before touching self._block_tag. But two cases reach here with
        self._block_tag still set and no frame to explain it:

        1. Bare top-level text directly inside a still-open <ol>/<ul> (not
           wrapped in its own <li>) opens an *implicit* paragraph via
           handle_data's bare-text path (#343) without ever going through
           _interrupt_open_block, so it has no frame of its own on
           self._block_stack. Resuming an outer frame while that implicit
           paragraph was still open used to silently overwrite
           self._block_tag and clear self._run_buf out from under it, losing
           its text entirely — caught live against
           `<h1>Start<ol><li>B<ul><li>C</li></ol>D</ol>E`, where 'D' vanished
           and 'E' was mistyped as a new heading instead of resuming the
           paragraph implicitly opened by 'D' (PR #478 review round).
        2. A wrapper construct (<ol>/<ul>/<table>/<pre>/<blockquote>) that
           opened with *nothing* outer to interrupt (so _interrupt_open_block
           pushed no frame at all — self._block_stack has nothing to say
           about this construct) whose own inner content is left open when
           this closing tag arrives — either malformed HTML missing its own
           close tag (`<blockquote><p>text</blockquote>after`) or the same
           implicit-paragraph case as (1) but with no outer frame at all
           (`<ul>text</ul>after`). The original #478 fix only reached its
           flush from inside the "a frame exists and will be resumed" branch
           below, so this frameless case fell through the earlier
           `if not self._block_stack: return` guard without ever flushing —
           self._block_tag stayed open and silently absorbed whatever text
           came after this closing tag (#476 QA round 1, confirmed to also
           reproduce for plain `<ul>text</ul>after` with no blockquote
           involved — a pre-existing gap this generalizes the fix for,
           not something new to blockquote).

        After this unconditional flush, self._block_tag is cleared — correct
        for case 2, where there is nothing to resume into; case 1's frame
        (when one exists) still overwrites self._block_tag below via
        frame.outer_tag once resuming is confirmed.
        """
        if self._block_tag is not None:
            runs = self._flush_pending_runs()
            self._emit_block_node(
                self._block_tag, runs, preserve_if_empty=self._block_had_unsupported_content
            )
            self._block_tag = None
            self._block_named_style = None

        if not self._block_stack:
            return
        frame = self._block_stack[-1]
        if closing_tag in ("ol", "ul") and frame.interrupted_by in ("ol", "ul"):
            if len(self._list_ordered) != frame.list_depth:
                return
            resumes = closing_tag == frame.interrupted_by
        else:
            if frame.interrupted_by != closing_tag:
                return
            resumes = True
        self._block_stack.pop()
        if not resumes:
            return
        self._block_tag = frame.outer_tag
        self._block_resumed = True
        self._block_had_unsupported_content = False
        self._run_buf = []
        self._pending_runs = []
        self._block_named_style = frame.named_style

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)

        # --- table structure ---
        if tag == "table":
            if self._table_depth == 0:
                self._interrupt_open_block("table")
            elif self._table_stack and self._table_stack[-1].in_cell:
                # A nested table is opening inside an already-open cell. The run
                # buffer is shared across nesting levels, so any text typed before
                # this point must be flushed now and attached to the outer cell —
                # otherwise it bleeds into the nested table's own first cell (#108).
                self._table_stack[-1].append_runs(self._flush_pending_runs())
            self._table_depth += 1
            self._table_stack.append(_TableBuilder())
            return

        if self._table_depth >= 1:
            tb = self._table_stack[-1]
            if tag == "col":
                w = _px_to_pt(attr_dict.get("width") or "")
                if w is not None:
                    tb.col_widths_from_col.append(w)
                else:
                    tb.col_widths_from_col.append(None)
                return
            if tag == "tr":
                tb.start_row()
                return
            if tag in ("td", "th"):
                # `or 1` only covers a missing attribute — an explicit colspan="0"/
                # rowspan="0" is falsy-looking HTML but a truthy non-empty string,
                # so it survives the `or` and must be clamped separately. A cell
                # can't span zero columns/rows.
                colspan = max(1, int(attr_dict.get("colspan") or 1))
                rowspan = max(1, int(attr_dict.get("rowspan") or 1))
                is_header = tag == "th"
                width_str = attr_dict.get("width", "")
                width_pt = _px_to_pt(width_str) if width_str else None
                tb.start_cell(
                    colspan=colspan, rowspan=rowspan, is_header=is_header, width_pt=width_pt
                )
                # If it's a header cell, pre-activate bold
                if is_header:
                    self._bold_depth += 1
                return

        # --- list context ---
        if tag == "ol":
            self._interrupt_open_block("ol")
            self._list_ordered.append(True)
            return
        if tag == "ul":
            self._interrupt_open_block("ul")
            self._list_ordered.append(False)
            return

        # --- blockquote (#476) ---
        # Interrupts any open block the same way ol/ul/table/pre already do,
        # flushing the outer block's own buffered text (at the pre-increment
        # depth — that text is not inside this blockquote) before entering.
        # Depth increments after the interrupt so nested content — including a
        # further nested <blockquote> — reads the correct depth via
        # _emit_block_node's self._blockquote_depth lookup.
        if tag == "blockquote":
            self._interrupt_open_block("blockquote")
            self._blockquote_depth += 1
            return

        # --- pre / code block ---
        if tag == "pre" and self._table_depth == 0:
            self._interrupt_open_block("pre")
            self._block_tag = "pre"
            self._block_resumed = False
            self._block_had_unsupported_content = False
            self._in_pre = True
            self._run_buf = []
            self._pending_runs = []
            return

        # --- block elements ---
        if tag in _BLOCK_TAGS and self._table_depth == 0:
            self._interrupt_open_block(tag)
            self._block_tag = tag
            self._block_resumed = False
            self._block_had_unsupported_content = False
            self._run_buf = []
            self._pending_runs = []
            if tag == "p":
                style = (attr_dict.get("data-style") or "").lower()
                self._block_named_style = _NAMED_BLOCK_STYLES.get(style)
            else:
                self._block_named_style = None
            return

        # --- thematic break (<hr>) with no open block ---
        # Unlike <img>, which markdown always wraps in a <p> (so an unsupported
        # image already reaches _emit_block_node's runs=[] handling above),
        # python-markdown emits "---"/"___" thematic breaks as a bare <hr />
        # sibling with no wrapping tag at all — it never opens a block, so it
        # would otherwise vanish with zero trace, collapsing the paragraph
        # boundary between the surrounding content (#401). Scoped to <hr>
        # specifically rather than every void tag: it's the only one that's a
        # genuine block-level CommonMark construct in its own right. Also
        # requires _tag_depth == 0, matching handle_data's sibling bare-text
        # check below (#343): an <hr> wrapped only in an inline tag with no
        # block ancestor (e.g. "<span><hr></span>") is inline-only content
        # with no block ancestor, same as bare text in that position, and
        # must stay a no-op rather than injecting a spurious paragraph
        # boundary — see test_span_wrapped_text_still_dropped.
        if (
            tag == "hr"
            and self._block_tag is None
            and self._table_depth == 0
            and self._tag_depth == 0
        ):
            self._nodes.append(Paragraph(runs=[], blockquote_depth=self._blockquote_depth))
            return

        # --- bare top-level <img> with no open block (#333) ---
        # Same rationale as <hr> just above: markdown's own "![]()" syntax
        # always renders wrapped in a <p>, so this only matters for raw HTML
        # (content_format="html") supplying a top-level <img> with no
        # wrapping tag at all.
        if (
            tag == "img"
            and self._block_tag is None
            and self._table_depth == 0
            and self._tag_depth == 0
        ):
            src = attr_dict.get("src")
            if src:
                self._nodes.append(
                    Paragraph(
                        runs=[_make_image(attr_dict, src)],
                        blockquote_depth=self._blockquote_depth,
                    )
                )
                return
            # No src — nothing to embed; fall through to the generic
            # unrecognized-tag handling below (a no-op at depth 0).

        # --- inline elements / unrecognized tags ---
        if tag not in _VOID_TAGS:
            self._tag_depth += 1
        if self._block_tag or (
            self._table_depth >= 1 and self._table_stack and self._table_stack[-1].in_cell
        ):
            self._flush_run()
            if tag in _INLINE_BOLD:
                self._bold_depth += 1
            elif tag in _INLINE_ITALIC:
                self._italic_depth += 1
            elif tag in _INLINE_UNDERLINE:
                self._underline_depth += 1
            elif tag in _INLINE_STRIKE:
                self._strike_depth += 1
            elif tag == "a":
                href = attr_dict.get("href", "")
                if href:
                    self._link_url.append(href)
            elif tag == "code" and not self._in_pre:
                self._code_depth += 1
            elif tag == "br":
                self._run_buf.append("\n")
            elif tag == "img" and self._block_tag and not self._in_pre:
                # Supported (#333) only at body level (self._block_tag truthy) —
                # NOT inside a table cell (self._block_tag is always None there,
                # so this branch can't fire for cell content) and not inside
                # <pre>, where an embedded image makes no sense. Table-cell
                # images remain a documented, deliberately out-of-scope gap
                # (tracked as a follow-up) and fall through unchanged to the
                # existing silent-no-op behavior any other unsupported tag
                # already gets in a cell.
                src = attr_dict.get("src")
                if src:
                    self._pending_runs.append(_make_image(attr_dict, src))
                else:
                    self._block_had_unsupported_content = True
            elif self._block_tag:
                # Anything else reaching this fallthrough (a bare <hr> inside
                # a block, an <img> inside a table cell or <pre>, or any
                # other tag this parser doesn't specially recognize) is
                # silently dropped rather than contributing a run — see
                # self._block_had_unsupported_content.
                self._block_had_unsupported_content = True

    def handle_endtag(self, tag):
        # --- table structure ---
        if tag == "table":
            if self._table_stack:
                tb = self._table_stack.pop()
                node = tb.build()
                if node is not None:
                    if self._table_depth == 1:
                        self._nodes.append(node)
                    elif self._table_stack:
                        self._table_stack[-1].append_nested_table(node)
            self._table_depth -= 1
            if self._table_depth == 0:
                self._resume_interrupted_block("table")
            return

        if self._table_depth >= 1 and self._table_stack:
            tb = self._table_stack[-1]
            if tag == "tr":
                tb.end_row()
                return
            if tag in ("td", "th"):
                is_header = tag == "th"
                runs = self._flush_pending_runs()
                if is_header:
                    self._bold_depth -= 1
                tb.end_cell(runs)
                return

        # --- list context ---
        # _list_ordered pops unconditionally (#382) — not gated on the popped
        # entry's own type matching this closing tag, the way an earlier
        # version of this code did. That gate meant a mismatched close (e.g.
        # an <ol> closed by a stray </ul>) silently skipped the pop instead
        # of performing it, permanently leaving _list_ordered one level too
        # deep for the rest of the document — every subsequent
        # BulletItem.depth (len(self._list_ordered) - 1) came out off by one,
        # confirmed live to bleed into completely unrelated, later, correctly
        # well-formed lists. A closing </ol> or </ul> always means "one fewer
        # list is open" regardless of which of the two opened it, so this
        # pops by count, matching every open tag's own unconditional push
        # above.
        #
        # The pop happens *before* _resume_interrupted_block runs (#450):
        # resuming a list-interrupted block frame is itself matched by depth
        # now (see _resume_interrupted_block), which needs the already-popped
        # count to tell whether the interrupting list construct — however its
        # own open/close tags were paired — has actually closed.
        if tag == "ol":
            if self._list_ordered:
                self._list_ordered.pop()
            self._resume_interrupted_block("ol")
            return
        if tag == "ul":
            if self._list_ordered:
                self._list_ordered.pop()
            self._resume_interrupted_block("ul")
            return

        # --- blockquote (#476) ---
        # Resume before decrementing depth: if a block was left open right up
        # to this close tag (e.g. malformed HTML missing its own inner close
        # tag), _resume_interrupted_block's own pre-resume flush must still
        # see this content as inside the blockquote (depth not yet
        # decremented) — mirroring how _emit_block_node reads
        # self._blockquote_depth fresh at flush time everywhere else.
        if tag == "blockquote":
            self._resume_interrupted_block("blockquote")
            self._blockquote_depth = max(0, self._blockquote_depth - 1)
            return

        # --- pre / code block ---
        if tag == "pre" and self._table_depth == 0 and self._block_tag == "pre":
            # Images are never appended to _pending_runs while self._in_pre is
            # True (see the img handling in handle_starttag) — this filter is
            # a type-narrowing no-op, not a behavior change. list[Run | Image]
            # is kept (rather than list[Run]) because handle_endtag reuses
            # `runs` as one function-scoped variable across several branches
            # (table cells, generic block tags) that do need list[Run |
            # Image] — Python's list invariance means a genuinely list[Run]
            # local here still couldn't be passed to Paragraph(runs=...)'s
            # list[Run | Image] parameter below without the same cast, so the
            # isinstance filter in the join just below stays for the same
            # reason.
            runs: list[Run | Image] = [r for r in self._flush_pending_runs() if isinstance(r, Run)]
            # Strip trailing newline that markdown adds inside <pre> content
            last = runs[-1] if runs else None
            if isinstance(last, Run) and last.text.endswith("\n"):
                last.text = last.text.rstrip("\n")
                if not last.text:
                    runs.pop()
            # A *resumed* <pre> (interrupted by a nested table/etc, then
            # reopened via _resume_interrupted_block) whose trailing flush is
            # whitespace-only is markup-formatting noise, not authored <pre>
            # content — the same fresh-vs-resumed distinction _emit_block_node
            # already draws for <p>/<li>/headings (#401/#402), #443. A
            # *fresh* <pre> keeps its whitespace unconditionally, since every
            # character inside <pre> is normally significant. But a resumed
            # segment that dropped genuinely unsupported content (e.g. a
            # <hr> inside <pre>) must still get a boundary node even when its
            # remaining flush is whitespace-only or empty — the same
            # preserve_if_empty guarantee _emit_block_node gives every other
            # block type — otherwise the dropped content leaves no trace at
            # all in the resulting doc (QA round 1, PR #515).
            text = "".join(r.text for r in runs if isinstance(r, Run))
            is_fresh_pre_whitespace = not self._block_resumed and bool(runs)
            if text.strip() or is_fresh_pre_whitespace or self._block_had_unsupported_content:
                self._nodes.append(Paragraph(runs=runs, blockquote_depth=self._blockquote_depth))
            self._block_tag = None
            self._in_pre = False
            self._resume_interrupted_block("pre")
            return

        # --- block elements ---
        if tag in _BLOCK_TAGS and self._table_depth == 0 and self._block_tag == tag:
            runs = self._flush_pending_runs()
            self._emit_block_node(tag, runs, preserve_if_empty=self._block_had_unsupported_content)
            self._block_named_style = None
            self._block_tag = None
            self._resume_interrupted_block(tag)
            return

        # --- inline elements / unrecognized tags ---
        if tag not in _VOID_TAGS and self._tag_depth > 0:
            self._tag_depth -= 1
        if self._block_tag or (
            self._table_depth >= 1 and self._table_stack and self._table_stack[-1].in_cell
        ):
            self._flush_run()
            if tag in _INLINE_BOLD:
                self._bold_depth = max(0, self._bold_depth - 1)
            elif tag in _INLINE_ITALIC:
                self._italic_depth = max(0, self._italic_depth - 1)
            elif tag in _INLINE_UNDERLINE:
                self._underline_depth = max(0, self._underline_depth - 1)
            elif tag in _INLINE_STRIKE:
                self._strike_depth = max(0, self._strike_depth - 1)
            elif tag == "a" and self._link_url:
                self._link_url.pop()
            elif tag == "code" and not self._in_pre:
                self._code_depth = max(0, self._code_depth - 1)

    def handle_data(self, data):
        if (
            self._table_depth >= 1 and self._table_stack and self._table_stack[-1].in_cell
        ) or self._block_tag:
            self._run_buf.append(data)
        elif self._table_depth == 0 and self._tag_depth == 0 and data.strip():
            # Genuinely bare text — no wrapping block tag, no enclosing tag of
            # any kind (#343). Implicitly open a paragraph so it isn't
            # silently dropped the way inline-only content
            # (e.g. "<span>no blocks</span>") intentionally is.
            self._block_tag = "p"
            self._block_named_style = None
            self._run_buf.append(data)

    def handle_entityref(self, name):
        text = html_module.unescape(f"&{name};")
        self.handle_data(text)

    def handle_charref(self, name):
        text = html_module.unescape(f"&#{name};")
        self.handle_data(text)

    def _finalize(self):
        """Flush a block left open at end-of-input — the implicit paragraph
        opened for bare top-level text (no closing tag ever arrives for it),
        or malformed HTML missing a final close tag — so trailing content
        isn't silently dropped."""
        if self._block_tag is not None:
            runs = self._flush_pending_runs()
            self._emit_block_node(
                self._block_tag, runs, preserve_if_empty=self._block_had_unsupported_content
            )
            self._block_tag = None
            self._block_named_style = None


class _TableBuilder:
    """Accumulates rows/cells while parsing a <table>."""

    def __init__(self):
        self.rows: list[Row] = []
        self.col_widths_from_col: list[float | None] = []
        self._current_row_cells: list[Cell] = []
        self._current_cell: dict | None = None  # metadata for current open cell
        self._cell_col_widths: list[float | None] = []  # widths from <td width>
        self.in_cell = False
        # ordered content of the open cell
        self._current_children: list[Run | Image | Table] = []

    def start_row(self):
        self._current_row_cells = []

    def end_row(self):
        if self._current_row_cells:
            self.rows.append(Row(cells=self._current_row_cells))
        self._current_row_cells = []

    def start_cell(self, colspan: int, rowspan: int, is_header: bool, width_pt: float | None):
        self._current_cell = {
            "colspan": colspan,
            "rowspan": rowspan,
            "is_header": is_header,
            "width_pt": width_pt,
        }
        self.in_cell = True
        self._current_children = []

    def append_runs(self, runs: list[Run | Image]):
        """Add flushed text runs to this still-open cell's ordered content."""
        self._current_children.extend(runs)

    def append_nested_table(self, table: Table):
        """Add a completed nested <table> to this still-open cell's ordered content."""
        self._current_children.append(table)

    def end_cell(self, runs: list[Run | Image]):
        if self._current_cell is None:
            return
        meta = self._current_cell
        # Record td width for col_widths (first row only)
        if meta["width_pt"] is not None and len(self.rows) == 0:
            self._cell_col_widths.append(meta["width_pt"])
        cell = Cell(
            children=self._current_children + runs,
            colspan=meta["colspan"],
            rowspan=meta["rowspan"],
            is_header=meta["is_header"],
        )
        self._current_row_cells.append(cell)
        self._current_cell = None
        self.in_cell = False
        self._current_children = []

    def build(self) -> Table | None:
        if not self.rows:
            return None
        # Prefer <col width> widths; fall back to first-row <td width>
        widths = self.col_widths_from_col or self._cell_col_widths
        return Table(rows=self.rows, col_widths=widths)


def html_to_ast(html: str) -> list[DocNode]:
    """Parse an HTML string into a list of DocNode objects."""
    parser = _AstParser()
    parser.feed(html)
    parser._finalize()
    return parser._nodes
