"""This project's own AST (docs/ast.py) -> GitHub-flavored Markdown text.

The read-side inverse of markdown-support.md's MD -> HTML -> AST -> Docs pipeline,
run backwards from an AST built by doc_to_ast.py's Docs API walker. See that file's
mapping table for the per-construct correspondence this mirrors.

Known, deliberate gaps (documented rather than silently dropped):
  - A table nested inside another table's cell has no Markdown table syntax to
    express it (the write side has the identical limitation in reverse — see
    markdown-support.md's "What this does NOT do") — rendered as a placeholder
    note in that cell instead of being ast_to_markdown-ed inline.
  - Markdown pipe tables have no merged-cell concept: a colspan>1 cell's text
    goes in the first spanned column, the rest render blank; a rowspan phantom
    renders as a blank cell in every row it covers. This is the closest GFM
    tables can represent a merge, not a lossless round-trip.
  - The first row of every table is always rendered as the header row (GFM
    pipe-table syntax requires exactly one header + separator row; Docs has no
    per-row "is this the header" signal to read back).
"""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import replace

from .ast import BulletItem, Cell, DocNode, Heading, Image, NamedBlock, Paragraph, Run, Table
from .emitter import _build_phantom_set

# Characters in plain text that Markdown would otherwise read as syntax. "~" is
# GFM strikethrough. "<" only when it could open an HTML tag or autolink, and
# "&" only when it starts an entity reference, so ordinary prose ("a < b",
# "AT&T") stays readable. Exported text must not be mistaken for the <br> and
# <code> HTML the exporter writes itself (#938).
_LT_OPENS_SYNTAX = r"[A-Za-z/!?]"
_AMP_OPENS_SYNTAX = r"#[0-9]{1,7};|#[xX][0-9a-fA-F]{1,6};|[A-Za-z][A-Za-z0-9]*;"
_MD_ESCAPE = re.compile(
    r"[\\`*_\[\]~]"
    rf"|<(?={_LT_OPENS_SYNTAX})"
    rf"|&(?={_AMP_OPENS_SYNTAX})"
)
# Characters that are syntax only when certain text follows them, and that
# text. Each run is escaped on its own, so when the following text comes from
# the next part, _join_inline has to make the call (#969). "!" is left
# unescaped in plain text and is syntax only right before a "[" (an image).
_BOUNDARY_SYNTAX = {
    "!": re.compile(r"\["),
    "<": re.compile(_LT_OPENS_SYNTAX),
    "&": re.compile(_AMP_OPENS_SYNTAX),
}
_BACKTICK_RUN = re.compile(r"`+")

# A paragraph whose rendered text starts with one of these (unescaped) would be
# misread by any CommonMark parser as a different block type entirely — an ATX
# heading, a blockquote, a bullet item, or an ordered-list item — rather than
# the plain paragraph text it actually is (#591 QA round 1, live-confirmed for
# "1. Not actually a list item" and "# Not a heading either"). Applied to a
# plain Paragraph and to a list item's text, which starts the item's first
# block, so "- # a" is a heading inside the item (#1302). Heading/NamedBlock
# text follows its own "#" prefix, where it's never re-parsed as a new block.
_LEADING_SIMPLE_MARKER = re.compile(r"^(#{1,6}|[*+-])(?=[ \t]|$)")
_LEADING_ORDERED_MARKER = re.compile(r"^(\d{1,9})([.)])(?=[ \t]|$)")
# A line of only "-" (spaces allowed) is a thematic break, or a setext
# underline under a preceding line, and so is a line of only "=". "*" and "_"
# rules can't occur: _escape has already escaped both (#993).
_LEADING_RULE_LINE = re.compile(r"^(?:=+[ \t]*|-[- \t]*)$")
# CommonMark's blockquote marker is the one simple marker that needs no
# whitespace after it: ">word" opens a quote where "#word" and "-word" stay
# paragraphs. So ">" gets its own check, which never looks past the marker.
_LEADING_BLOCKQUOTE_MARKER = re.compile(r"^>")

# A thematic break (#1096). Every block is separated by a blank line, so "---"
# never sits under a paragraph line, where it would be a setext underline. As the
# document's first line it would open YAML front matter, which the Markdown import
# drops (D3, #1173) when what follows reads as a mapping, so there it's "***".
_RULE = "---"
_FIRST_LINE_RULE = "***"

_NESTED_TABLE_PLACEHOLDER = (
    "*(nested table omitted — Markdown tables can't contain a table; "
    "use get_doc_structure for full fidelity)*"
)


def ast_to_markdown(nodes: list[DocNode], comments: list[dict] | None = None) -> str:
    """Serialize a list of DocNode into a single Markdown document string."""
    parts: list[str] = []
    prev_node: DocNode | None = None
    open_items = _OpenItems()
    for node in nodes:
        rendered = open_items.render(node, prev_node)
        if prev_node is None and rendered == _RULE:
            rendered = _FIRST_LINE_RULE
        if prev_node is not None:
            parts.append(open_items.separator)
        parts.append(rendered)
        prev_node = node

    markdown = "".join(parts)
    if not markdown.endswith("\n"):
        markdown += "\n"

    if comments:
        markdown += "\n---\n\n## Comments\n\n"
        markdown += "\n".join(_render_comment(c) for c in comments)

    return markdown


class _OpenItems:
    """Renders each node, writing a block inside a list item (its `list_depth`,
    #1302) under that item instead of at the margin, and picks the separator before it.

    CommonMark keeps a block in an item when it's indented to the item's content
    column, the width of the item's own indent and marker. So every list item
    records that column for its depth, and a block with a `list_depth` is indented
    by the column of the last item at that depth. The block ends the deeper items.
    A node with no `list_depth` ends them all.

    A quoted item's quote markers come before its indent ("> - a"). A block inside
    it is inside that quote too, whatever depth it reads with (an unquoted table
    reads none), so the item's quote levels go outside the block's indent and only
    its own extra levels inside ("> - a" then ">   > b"). Two blocks in one item
    whose own levels overlap share that quote, so the blank line between them
    carries it (#1122).

    After `render`, `separator` is what goes between the node and the one before it:
    a newline between two items at the same quote depth, so a list stays tight (items at
    different depths are different lists, "- b" then "> - qa"); a newline between an
    empty item and its first block, since CommonMark ends an item that starts with a
    blank line there (PR #1326 QA round 1); otherwise a blank line carrying the quote
    levels both nodes write at the margin, so it doesn't end a quote they share. Two
    adjacent quoted blocks in Docs are one quote: Docs draws their left borders as one
    bar, and emitter.py puts an unquoted separator paragraph between two separate
    quotes (#1098), which reads back as a node of its own with no quote."""

    def __init__(self) -> None:
        # Per open item depth: (content column, blockquote_depth).
        self._items: list[tuple[int, int]] = []
        # Quote levels the last node wrote at the margin, before any indent.
        self._margin_quote = 0
        # For a block inside an item: (list_depth, content column, the quote levels it
        # writes inside the item's indent). None for anything else.
        self._inner_quote: tuple[int, int, int] | None = None
        self.separator = "\n\n"

    def render(self, node: DocNode, prev_node: DocNode | None) -> str:
        prev_quote = self._margin_quote
        prev_inner = self._inner_quote
        rendered = self._render(node, prev_node)
        same_list = (
            isinstance(node, BulletItem)
            and isinstance(prev_node, BulletItem)
            and node.blockquote_depth == prev_node.blockquote_depth
        )
        shared = min(prev_quote, self._margin_quote)
        if same_list or _starts_empty_item(prev_node, node):
            self.separator = "\n"
        elif (
            prev_inner is not None
            and self._inner_quote is not None
            and prev_inner[:2] == self._inner_quote[:2]
            and min(prev_inner[2], self._inner_quote[2])
        ):
            # Two blocks in one item that share a quote inside its indent: the blank
            # line between them carries that quote too, or it would end it (#1122).
            column = self._inner_quote[1]
            inner = min(prev_inner[2], self._inner_quote[2])
            self.separator = f"\n{_blockquote(' ' * column + '>' * inner, shared)}\n"
        else:
            self.separator = f"\n{'>' * shared}\n" if shared else "\n\n"
        return rendered

    def _nesting_column(self, depth: int, quote: int) -> int:
        """The column an item at `depth` starts at: the content column of the open
        item above it (#1128), when Markdown can hold it inside that item.

        It can't when their quote depths differ: the item's quote markers go at the
        margin, outside any indent, so a quoted child of an unquoted item, or the
        reverse, would sit 4+ columns past its quote's margin, an indented code
        block. A skipped depth has no column of its own either, and a step past the
        item above would put the child 4+ columns past it, lazy text of that item.
        So the item nests in the deepest open item when the quotes match, and
        otherwise starts at the margin. That ends every list above it in Markdown,
        so those depths close (column 0, no quote): a block that names one is
        written at the margin, where it then is."""
        if not self._items or depth == 0:
            return 0
        column, above_quote = self._items[-1]
        if above_quote == quote:
            return column
        self._items[:] = [(0, 0)] * len(self._items)
        return 0

    def _render(self, node: DocNode, prev_node: DocNode | None) -> str:
        if isinstance(node, BulletItem):
            opens_sublist = _opens_sublist(node, prev_node)
            quote = node.blockquote_depth
            del self._items[node.depth :]
            indent = self._nesting_column(node.depth, quote)
            # A depth with no item of its own (a skipped level, or a fragment whose
            # parent wasn't exported) sits at the column this item nests under, so a
            # block that names it lands inside the same item, or at the margin.
            self._items.extend([(indent, quote)] * (node.depth - len(self._items)))
            prefix = _item_prefix(node, opens_sublist, indent)
            self._items.append((len(prefix), quote))
            self._margin_quote = quote
            self._inner_quote = None
            return _render_block(node, item_prefix=prefix)
        list_depth = node.list_depth
        if list_depth is None or list_depth >= len(self._items):
            self._items.clear()
            self._margin_quote = node.blockquote_depth
            self._inner_quote = None
            if isinstance(node, Table):
                # A quoted table (#1122) gets its quote markers like any block.
                body = _render_table(node)
                return _blockquote(body, node.blockquote_depth) if node.blockquote_depth else body
            return _render_block(node)
        del self._items[list_depth + 1 :]
        column, item_quote = self._items[list_depth]
        # A block inside a quoted list's item is inside that list's quote too. Its
        # own depth can read lower: an unquoted table has no indent in the API, and
        # Docs puts an unindented empty paragraph before a table in an item.
        quote = max(node.blockquote_depth, item_quote)
        outer = item_quote
        self._margin_quote = outer
        self._inner_quote = (list_depth, column, quote - outer)
        if isinstance(node, Table):
            body = _render_table(node)
            if quote > outer:
                body = _blockquote(body, quote - outer)
        else:
            body = _render_block(node, blockquote_depth=quote - outer)
        body = _indent_lines(body, column)
        return _blockquote(body, outer) if outer else body


def _starts_empty_item(prev_node: DocNode | None, node: DocNode) -> bool:
    """Whether `node` is the first block inside `prev_node`, a list item with no text.
    CommonMark lets an item start with at most one blank line, its marker's own, so
    "-", a blank line, then "  ---" is an empty item ended by a rule at the margin."""
    return (
        isinstance(prev_node, BulletItem)
        and not isinstance(node, BulletItem)
        and not prev_node.runs
        and prev_node.checked is None
        and prev_node.heading_level is None
        and node.list_depth == prev_node.depth
    )


def _indent_lines(body: str, column: int) -> str:
    # Blank lines stay empty: CommonMark keeps them in the item either way.
    pad = " " * column
    return "\n".join(f"{pad}{line}" if line else line for line in body.split("\n"))


def _is_code_block(node: Paragraph) -> bool:
    """A Paragraph whose every run is code-styled (font_family='Courier New')
    is the read-back signal for a fenced ```code block``` (#103) — the Docs
    representation has no other marker distinguishing a full code-block
    paragraph from a Paragraph that merely contains one inline `code` span
    among ordinary text, so "every run in this paragraph is code" is the only
    signal available (see markdown-support.md's write-side mapping table).

    A fenced block's content is literal, so it can't carry a link. A paragraph
    with any linked run renders as inline code spans instead, which can (#951).
    Only a link `_render_run` would actually write counts: a linked run that
    is only whitespace and line breaks renders as bare <br>, so giving up the
    fence for it would lose the block and still export no link (PR #976 QA
    round 1). A linked Image doesn't count either: images render outside the
    fence."""
    runs = [r for r in node.runs if isinstance(r, Run)]
    return (
        bool(runs)
        and all(r.font_family == "Courier New" for r in runs)
        and not any(r.link_url and _split_edge_breaks(r.text)[1] for r in runs)
    )


def _render_code_block(node: Paragraph) -> str:
    """Every Run in `node` is code-styled (see `_is_code_block`), but a non-Run
    child (an Image, #594) can still be interleaved among them — Markdown has
    no way to embed an image inside a fenced code block, so a contiguous run
    of code text becomes one fence and each Image renders on its own line
    outside any fence, preserving both the content and its original order
    rather than silently dropping the image the way naively joining only the
    Run text did."""
    segments: list[str] = []
    buffer = ""
    for item in node.runs:
        if isinstance(item, Run):
            buffer += item.text
        else:
            if buffer:
                segments.append(_fenced_code_block(buffer))
                buffer = ""
            segments.append(_render_image(item))
    if buffer:
        segments.append(_fenced_code_block(buffer))
    return "\n\n".join(segments)


def _opens_sublist(node: DocNode, prev_node: DocNode | None) -> bool:
    """Whether `node` is a list item nested under the item just before it, so its
    line follows that item's text with only a newline between them. An item whose
    quote depth differs from that item's can't nest in it (`_OpenItems._nesting_column`),
    and a blank line comes between them."""
    return (
        isinstance(node, BulletItem)
        and isinstance(prev_node, BulletItem)
        and node.depth > prev_node.depth
        and node.blockquote_depth == prev_node.blockquote_depth
    )


def _ordered_marker(node: BulletItem, opens_sublist: bool) -> str:
    """The item's real number, from doc_to_ast, so an item resuming a list after an
    interrupting block starts its Markdown list there (#1208); "1." when unknown.

    CommonMark lets an ordered list interrupt a paragraph only when it starts at 1.
    A sublist's first line follows its parent item's text, so "- a\\n  5. a1" reads
    "5. a1" as more of the parent's text. That item writes "1." instead, keeping the
    sublist and losing only its start number (PR #1234 QA round 1). A blank line
    before it would keep the number but make the parent list loose."""
    if node.number is None or (opens_sublist and node.number != 1):
        return "1. "
    return f"{node.number}. "


def _item_prefix(node: BulletItem, opens_sublist: bool, indent: int) -> str:
    """A list item's indent and list marker, before its text; its length is the
    item's content column.

    `indent` is the content column of the item it's nested in (0 at the top level).
    CommonMark nests an item only when it starts at or past that column, which
    depends on the parent's marker: 2 under "- ", 3 under "1. ", 4 under "10. ". A
    fixed two spaces per depth read a numbered child as a sibling (#1128).

    A checkbox's "[ ] " isn't part of the marker: CommonMark reads it as the
    item's text (GFM's task list is an extension of that paragraph), so a task
    item's content column is 2 like any "- " item's, and `_render_block` writes
    the box after this prefix. Counting it put a block 4 columns past the column,
    an indented code block, and a child item in the parent's text."""
    if node.ordered and node.checked is None:
        return " " * indent + _ordered_marker(node, opens_sublist)
    return " " * indent + "- "


def _checkbox(node: BulletItem) -> str:
    if node.checked is None:
        return ""
    return "[x] " if node.checked else "[ ] "


def _render_block(
    node: Heading | Paragraph | BulletItem | NamedBlock,
    blockquote_depth: int | None = None,
    item_prefix: str = "",
) -> str:
    """`blockquote_depth` overrides the node's own, for a block whose outer quote
    levels its caller writes (see `_OpenItems`). `item_prefix` is a list item's
    indent and marker, from `_item_prefix`, whose length `_OpenItems` records as
    the column the item's children nest under."""
    if isinstance(node, Paragraph) and node.rule:
        body = _RULE
    elif isinstance(node, Paragraph) and _is_code_block(node):
        body = _render_code_block(node)
    elif isinstance(node, Heading):
        body = f"{'#' * node.level} {_render_inline(node.runs)}".rstrip()
    elif isinstance(node, NamedBlock):
        # No Markdown equivalent to Docs' distinct TITLE/SUBTITLE styles — the
        # closest visual match is H1/H2 (see get_doc_as_markdown's docstring).
        level = 1 if node.style_type == "TITLE" else 2
        body = f"{'#' * level} {_render_inline(node.runs)}".rstrip()
    elif isinstance(node, BulletItem):
        text = _render_inline(node.runs)
        if node.heading_level:
            # An item whose text is a heading (#1302): "- # Title".
            text = f"{'#' * node.heading_level} {text}".rstrip()
        else:
            # Text after the marker starts the item's first block, so "# a" or
            # "> a" there would read as a heading or quote inside the item.
            text = _escape_leading_block_marker(text)
        body = f"{item_prefix}{_checkbox(node)}{text}"
    else:
        body = _escape_leading_block_marker(_render_inline(node.runs))

    depth = node.blockquote_depth if blockquote_depth is None else blockquote_depth
    if depth:
        body = _blockquote(body, depth)
    return body


def _blockquote(body: str, depth: int) -> str:
    prefix = "> " * depth
    return "\n".join(f"{prefix}{line}" if line else prefix.rstrip() for line in body.split("\n"))


def _escape_leading_block_marker(text: str) -> str:
    """Make one line that starts a block read as paragraph text. Leading
    spaces and tabs are dropped first: CommonMark strips a paragraph's
    leading whitespace anyway, so the rendered text is unchanged, while
    keeping them lets " - a" parse as a list and four spaces or a tab as an
    indented code block (#993)."""
    text = text.lstrip(" \t")
    if _LEADING_RULE_LINE.match(text):
        return "\\" + text
    if _LEADING_BLOCKQUOTE_MARKER.match(text):
        return "\\" + text
    m = _LEADING_SIMPLE_MARKER.match(text)
    if m:
        return "\\" + text
    m = _LEADING_ORDERED_MARKER.match(text)
    if m:
        digits, punct = m.group(1), m.group(2)
        return f"{digits}\\{punct}{text[m.end() :]}"
    return text


def _md_link_dest(url: str) -> str:
    """A bare (non-angle-bracket) CommonMark link destination can't contain
    whitespace or unbalanced parentheses — confirmed live (#591 QA round 1):
    a link to a URL like ".../wiki/Foo_(bar)" broke link-destination parsing
    at the unmatched ")". Wrapping the destination in `<...>` sidesteps the
    bare-destination rules entirely (CommonMark's angle-bracket destination
    form) — the only characters that still need escaping inside are a literal
    "<", ">", or backslash."""
    if not any(c in url for c in "() \t\n"):
        return url
    escaped = url.replace("\\", "\\\\").replace("<", "\\<").replace(">", "\\>")
    return f"<{escaped}>"


def _render_inline(items: list[Run | Image]) -> str:
    parts = _render_inline_parts(_coalesce_plain_runs(_coalesce_code_runs(items)), in_table=False)
    return _join_inline(parts)


def _render_inline_parts(items: list, in_table: bool, cell: bool = False) -> list[str]:
    """Render coalesced inline items to Markdown parts, keeping an emphasis
    span open across an image that shares it (#1509): a Doc whose paragraph is
    bold \"bold", image, bold "image" renders "**bold ![alt](src) image**" —
    one span — instead of "**bold** ![alt](src) **image**", which a round trip
    through the write pipeline then reads back with a plain image. An image
    whose own style no neighbor shares keeps its markers alone. Anything
    outside such a span renders exactly as it did before.

    A group never forms across a line break at an image's boundary, the same
    edge `_coalesce_plain_runs keeps apart for runs, so a break never lands
    inside markers it didn't before. A group whose markers would flank an
    image edge beside a character that is neither whitespace nor punctuation
    — a letter, a digit, an emoji or symbol included (#1583) — or beside a
    neighboring styled run's own emphasis marker never forms either: the
    markers wouldn't read as emphasis there, so the members fall back to the split rendering, the
    image bare. Code runs never join a group: their
    backticks aren't emphasis markers."""
    parts: list[str] = []
    i = 0
    n = len(items)
    while i < n:
        item = items[i]
        if cell and isinstance(item, Table):
            parts.append(_NESTED_TABLE_PLACEHOLDER)
            i += 1
            continue
        if _is_code_run(item):
            parts.append(_render_run(item, in_table))
            i += 1
            continue
        style = _markdown_style(item)
        group = [item]
        i += 1
        if style[:3] != (False, False, False):
            while i < n:
                nxt = items[i]
                if (
                    (cell and isinstance(nxt, Table))
                    or _is_code_run(nxt)
                    or _markdown_style(nxt) != style
                ):
                    break
                # An edge break between two group members would render inside
                # the markers, where a soft break would split the span; keep
                # the members apart, as _coalesce_plain_runs does for runs.
                prev = group[-1]
                edge_break = (isinstance(prev, Run) and _split_edge_breaks(prev.text)[2]) or (
                    isinstance(nxt, Run) and _split_edge_breaks(nxt.text)[0]
                )
                if edge_break:
                    break
                group.append(nxt)
                i += 1
        if any(isinstance(m, Image) for m in group) and not _markers_flank_image_edge(
            group, parts, items, i, style
        ):
            parts.append(_render_span(group, style, in_table))
        else:
            # No image, nothing a marker could span, or markers that would
            # flank an image edge beside a non-whitespace, non-punctuation
            # character, or a styled neighbor's own marker: one item at a
            # time, the image bare.
            parts.extend(_render_ungrouped(group, in_table))
    return parts


def _breaks_flanking(ch: str) -> bool:
    """Whether a character beside an emphasis marker stops CommonMark reading
    the marker as flanking: a letter, a digit, or anything else that is
    neither whitespace nor punctuation — an emoji or a symbol included,
    which GitHub's cmark-gfm also breaks on where an isalnum() test saw no
    break (#1583). Whitespace and Unicode punctuation leave the flanking
    rule satisfied, so a marker beside them still reads as emphasis."""
    if not ch or ch.isspace():
        return False
    if ch.isascii():
        # Every ASCII character that is neither whitespace nor alphanumeric
        # is ASCII punctuation to CommonMark.
        return ch.isalnum()
    return not unicodedata.category(ch).startswith("P")


def _markers_flank_image_edge(
    group: list, parts: list[str], items: list, next_i: int, style: tuple
) -> bool:
    """True when the span's markers would sit beside a character that breaks
    CommonMark's flanking rule, with an image edge between them (#1509
    review): `see**![logo](u)**` keeps its literal asterisks (an
    opening `**` after an alphanumeric is not left-flanking when `!`
    follows), and `**a ![logo](u)**b` loses its bold (a closing `**` before an
    alphanumeric is not right-flanking when `)` precedes). The breaking
    character is anything that is neither whitespace nor punctuation — the
    `_breaks_flanking` character-class test, not isalnum, since an emoji or
    a symbol beside the image edge breaks the span the same way on GitHub's
    cmark-gfm (#1583). A neighboring styled run's own marker is just as bad
    (#1530 review): its `*` merges with an asterisk marker into a single
    `***` run the parser reads as neither span, so a previous rendered part
    ending in a live `*` — a styled neighbor's own marker, where a literal
    one is escaped, and an escaped backslash before the marker leaves it
    live too (#1583) — and a next run carrying bold or italic and starting
    with no whitespace fall back as well — `*it***![logo](u) bold**` would
    lose its bold, and `**bold ![logo](u)***it*` its markers. Only an image
    at the span's edge puts a marker there — a run's edge whitespace already
    renders outside the markers.

    A span that takes its own link wrap — `style[3]` set with a run in the
    group, so `_render_span` writes `[**…**](url)` — puts its markers inside
    the brackets: neither the character outside nor a styled neighbour's
    own marker can touch them, so both neighbour checks are skipped (#1610
    review). The caller falls back to the split rendering, the image bare,
    as before."""
    if style[3] and any(isinstance(m, Run) for m in group):
        # The span's own link wrap puts its markers inside the brackets —
        # `[…](url)` — so the character outside never touches them, and a
        # styled neighbour's own marker cannot merge with one either.
        return False
    if isinstance(group[0], Image) and parts:
        prev = parts[-1]
        # A `*` the previous part ends in is a styled neighbor's own marker
        # when it's live — backslash parity decides (_ends_with_unescaped), so
        # an escaped backslash followed by a real marker counts too: an
        # italic run "a\\" renders `*a\\*`, where endswith("\\*") misread
        # the marker as escaped. Beside an opening asterisk marker the two
        # merge into one `***` run.
        if _breaks_flanking(prev[-1:]) or (
            (style[0] or style[1]) and _ends_with_unescaped(prev, "*")
        ):
            return True
    nxt = items[next_i] if next_i < len(items) else None
    if isinstance(group[-1], Image) and isinstance(nxt, Run):
        if _breaks_flanking(nxt.text[:1]):
            return True
        # A next run carrying bold or italic writes its own marker directly
        # after the span's closing one when it starts with no whitespace,
        # and the two merge into a single `***` run.
        if (
            (style[0] or style[1])
            and (nxt.bold or nxt.italic)
            and nxt.text[:1]
            and not nxt.text[0].isspace()
        ):
            return True
    return False


def _render_ungrouped(group: list, in_table: bool) -> list[str]:
    parts: list[str] = []
    for member in group:
        if isinstance(member, Image):
            image = _render_image(member)
            parts.append(_table_safe(image) if in_table else image)
        else:
            parts.append(_render_run(member, in_table))
    return parts


def _render_span(group: list[Run | Image], style: tuple, in_table: bool) -> str:
    """One emphasis span around `group`, its markers kept open across the
    images inside it (#1509) — the shape doc_to_ast reads from a Doc whose
    image sits inside a styled span, and the only Markdown form that round
    trips through the write pipeline back to the same styled span.

    Whitespace at the span's outer edges stays outside the markers, with its
    line breaks rendered as <br> outside the markers and the span's link, the
    way _render_plain_run keeps a run's edges from breaking CommonMark's
    flanking rule and _render_run keeps a break out of the <a>;
    whitespace beside an image is inside the span, never at a marker edge.
    A break inside a run renders as <br> inside the markers, as _render_run
    does.

    The span's own link wraps the whole body when a run joins it, and the
    images then render bare: their link is the span's (their style matched),
    so wrapping again would nest a link in a link. An images-only span keeps
    _render_image's own link wrap instead."""
    bold, italic, strike, link_url = style
    has_run = any(isinstance(m, Run) for m in group)
    inner: list[str] = []
    lead = trail = ""
    last = len(group) - 1
    for pos, member in enumerate(group):
        if isinstance(member, Image):
            inner.append(_image_body(member) if has_run else _render_image(member))
            continue
        core = member.text
        if pos == 0:
            lead = core[: len(core) - len(core.lstrip())]
            core = core[len(lead) :]
        if pos == last:
            trail = core[len(core.rstrip()) :]
            core = core[: len(core) - len(trail)]
        inner.append(_escape(core))
    # The span's outer edges follow _render_run's _split_edge_breaks rule:
    # the breaks themselves render outside the link too, so a span starting
    # or ending with a line break (a table cell's second paragraph, an edge
    # soft break) keeps its <br> out of the <a> (#1509 review). Whitespace on
    # the inner side of a break stays with the span, inside the link but
    # outside the markers.
    lead_breaks = lead[: lead.rfind("\n") + 1] if "\n" in lead else ""
    lead = lead[len(lead_breaks) :]
    trail_cut = trail.find("\n")
    trail_breaks = trail[trail_cut:] if trail_cut != -1 else ""
    trail = trail[:trail_cut] if trail_cut != -1 else trail
    body = _join_inline(inner).replace("\n", "<br>")
    if strike:
        body = f"~~{body}~~"
    if italic:
        body = f"*{body}*"
    if bold:
        body = f"**{body}**"
    body = f"{_render_breaks(lead, in_table)}{body}{_render_breaks(trail, in_table)}"
    if link_url and has_run:
        # The destination isn't table-safed here: the whole span is, once,
        # at return, and a pre-escaped "\\|" would come out "\\\\|" — an
        # escaped backslash and a live pipe that splits the row (#1583).
        dest = _md_link_dest(link_url)
        body = f"[{body}]({dest})"
    body = f"{_render_breaks(lead_breaks, in_table)}{body}{_render_breaks(trail_breaks, in_table)}"
    return _table_safe(body) if in_table else body


def _join_inline(parts: list[str]) -> str:
    """Join rendered inline parts, escaping a character that the next part
    turns into syntax. Each part is rendered on its own, so a part ending in
    "!" followed by a link exported as "wow![x](url)", an image (#969). "<"
    and "&" have the same problem: `_escape` checks what follows them, and at
    the end of a run nothing does, so "a <" then "b> text" exported a raw
    <b> tag and "AT&" then "amp;T" an entity (PR #981 QA round 1). The check
    runs against the text joined so far and everything after it, so an empty
    part, or an entity split across several runs, can't hide the boundary."""
    out = ""
    for i, part in enumerate(parts):
        if (
            part
            and _ends_with_unescaped(out, _BOUNDARY_SYNTAX)
            and _BOUNDARY_SYNTAX[out[-1]].match(_text_ahead(parts, i))
        ):
            out = out[:-1] + "\\" + out[-1]
        out += part
    return out


# Longer than the longest match any _BOUNDARY_SYNTAX pattern needs (a named
# entity is the longest; HTML's longest name is 31 characters plus ";").
_LOOKAHEAD_CHARS = 64


def _text_ahead(parts: list[str], start: int) -> str:
    # Enough of parts[start:] for a _BOUNDARY_SYNTAX match, without joining
    # the whole rest of the paragraph at every boundary.
    ahead = ""
    for part in parts[start:]:
        ahead += part
        if len(ahead) >= _LOOKAHEAD_CHARS:
            break
    return ahead


def _ends_with_unescaped(text: str, chars) -> bool:
    # An odd number of backslashes right before the character escapes it; an
    # even number is escaped backslashes, leaving the character itself live.
    if not text or text[-1] not in chars:
        return False
    backslashes = len(text[:-1]) - len(text[:-1].rstrip("\\"))
    return backslashes % 2 == 0


def _image_body(image: Image) -> str:
    """An image's own Markdown, with no link or span around it."""
    return f"![{_escape(image.alt or '')}]({_md_link_dest(image.src)})"


def _render_image(image: Image) -> str:
    """Markdown for one image, wrapped in a link when the image is linked.
    Every image goes through here, so a linked image keeps its link in a
    code paragraph, a table cell, and ordinary text alike (#951)."""
    body = _image_body(image)
    if image.link_url:
        body = f"[{body}]({_md_link_dest(image.link_url)})"
    return body


def _is_code_run(item: Run | Image | Table) -> bool:
    return isinstance(item, Run) and item.font_family == "Courier New"


def _coalesce_code_runs(items: list) -> list:
    """Merge adjacent code runs that share a link. Docs splits a run at any
    style change (bold, color), but rendered side by side two code spans
    would read as one: `` `a``b` `` parses as the single span "a``b", since
    the first span's closing delimiter and the second's opening one form one
    backtick run. A code span can't carry those styles anyway, so the merge
    loses nothing. Runs with different links stay apart; the link brackets
    already separate them."""
    merged: list = []
    for item in items:
        prev = merged[-1] if merged else None
        if (
            _is_code_run(item)
            and prev is not None
            and _is_code_run(prev)
            and prev.link_url == item.link_url
        ):
            merged[-1] = Run(
                text=prev.text + item.text, font_family="Courier New", link_url=prev.link_url
            )
        else:
            merged.append(item)
    return merged


def _markdown_style(item: Run | Image) -> tuple:
    # The styles _render_plain_run writes. Everything else on a Run (color,
    # size, underline, highlight, ...) has no Markdown syntax. An Image carries
    # the same fields (#1475), so the same test tells whether it sits in the
    # same span as a run (#1509).
    return (bool(item.bold), bool(item.italic), bool(item.strikethrough), item.link_url)


def _coalesce_plain_runs(items: list) -> list:
    """Merge adjacent non-code runs whose Markdown styles match (#1462).

    Docs splits a run at any style change, including ones Markdown can't
    write (a color). Rendered apart, two such runs put their markers side by
    side: struck runs wrote "~~a~~~~b~~", which GFM's single-tilde
    strikethrough reads as literal tildes, and bold struck ones
    "**~~a~~****~~b~~**". Merged first, they render as one span ("~~ab~~"),
    and the text is escaped as a whole, so an entity or tag split across runs
    is still seen. Like _coalesce_code_runs, the merge loses nothing Markdown
    could have kept. Runs are collected in a list and joined once, so a long
    paragraph of alternating colors stays linear.

    Two runs that meet at a line break stay apart: a run's edge breaks render
    outside its link and markers (_split_edge_breaks), and merged they'd be
    inside, a cell's paragraph break included (PR #1088 QA round 1). Apart,
    a <br> separates the markers, so they never touch."""
    merged: list = []
    pending: list[Run] = []

    def flush() -> None:
        if len(pending) == 1:
            merged.append(pending[0])
        elif pending:
            merged.append(replace(pending[0], text="".join(r.text for r in pending)))
        pending.clear()

    for item in items:
        if not isinstance(item, Run) or _is_code_run(item):
            flush()
            merged.append(item)
        elif pending and (
            _markdown_style(pending[0]) != _markdown_style(item)
            or _split_edge_breaks(pending[-1].text)[2]
            or _split_edge_breaks(item.text)[0]
        ):
            flush()
            pending.append(item)
        else:
            pending.append(item)
    flush()
    return merged


def _render_run(run: Run, in_table: bool = False) -> str:
    """Markdown for one run. `in_table` makes the result safe inside a
    pipe-table cell (see `_table_safe`).

    A line break inside a run (a Docs soft break, #1057) renders as <br>, as
    in a code run or a table cell. A raw newline would be a Markdown soft
    break, which joins the lines, and could start a new block mid-paragraph;
    a trailing backslash would end an ATX heading or a list item's line.
    The run's edges, up to its outermost line break, render outside its link,
    emphasis, and code span (see `_split_edge_breaks`)."""
    if run.text == "":
        return ""
    lead, inner, trail = _split_edge_breaks(run.text)
    if not inner:
        return _render_breaks(run.text, in_table)
    if run.font_family == "Courier New":
        body = _render_code_run(replace(run, text=inner), in_table)
    else:
        body = _render_breaks(_render_plain_run(replace(run, text=inner)), in_table)
    return f"{_render_breaks(lead, in_table)}{body}{_render_breaks(trail, in_table)}"


def _split_edge_breaks(text: str) -> tuple[str, str, str]:
    """Split `text` into (lead, inner, trail), where lead runs through the
    last line break in the leading whitespace and trail starts at the first
    line break in the trailing whitespace. Those edges render outside the
    run's link, so a cell's paragraph break (a leading "\n" from doc_to_ast)
    or an edge soft break never becomes a <br> inside the <a>, even with a
    space beside it (PR #1088 QA round 1). Whitespace on the inner side of a
    break stays with the run, as before. A run that is only whitespace with a
    break in it is all lead, with an empty inner."""
    if "\n" in text and not text.strip():
        return text, "", ""
    leading_ws = text[: len(text) - len(text.lstrip())]
    lead = leading_ws[: leading_ws.rfind("\n") + 1]
    rest = text[len(lead) :]
    trailing_ws = rest[len(rest.rstrip()) :]
    cut = trailing_ws.find("\n")
    trail = trailing_ws[cut:] if cut != -1 else ""
    return lead, rest[: len(rest) - len(trail)], trail


def _render_breaks(text: str, in_table: bool) -> str:
    # Rendered non-code Markdown with each "\n" as a <br>.
    return _table_safe(text) if in_table else text.replace("\n", "<br>")


def _render_code_run(run: Run, in_table: bool) -> str:
    # `run` has no line break at either edge; _render_run renders those.
    body = _render_code_run_text(run.text, in_table)
    if run.link_url:
        dest = _md_link_dest(run.link_url)
        body = f"[{body}]({_table_safe(dest) if in_table else dest})"
    return body


def _render_plain_run(run: Run) -> str:
    # CommonMark emphasis delimiters can't have whitespace on the inner side
    # (e.g. "**Bold **" doesn't close — the space right before "**" means it
    # renders as literal asterisks, not bold). Keep leading/trailing
    # whitespace outside the style markers so a run ending mid-sentence with
    # a trailing space still renders as intended.
    core = run.text.strip()
    if core == "":
        return run.text
    leading_ws = run.text[: len(run.text) - len(run.text.lstrip())]
    trailing_ws = run.text[len(run.text.rstrip()) :]

    body = _escape(core)
    if run.strikethrough:
        body = f"~~{body}~~"
    if run.italic:
        body = f"*{body}*"
    if run.bold:
        body = f"**{body}**"
    body = f"{leading_ws}{body}{trailing_ws}"
    if run.link_url:
        body = f"[{body}]({_md_link_dest(run.link_url)})"
    return body


def _escape(text: str) -> str:
    return _MD_ESCAPE.sub(lambda m: "\\" + m.group(), text)


def _longest_backtick_run(text: str) -> int:
    return max((len(match.group()) for match in _BACKTICK_RUN.finditer(text)), default=0)


def _fenced_code_block(text: str) -> str:
    # A fence must be longer than any backtick run in the content, or a
    # literal ``` line inside the block would close it early.
    fence = "`" * max(3, _longest_backtick_run(text) + 1)
    return f"{fence}\n{text}\n{fence}"


def _code_span(text: str) -> str:
    """One CommonMark code span for `text` (which has no newline).

    A code span's content is literal: backslash escapes don't work inside
    it, so the only tools are the delimiter length and padding. The
    delimiter is one backtick longer than the longest run in the content, so
    no literal run can close the span. Padding is exactly one space a side
    because CommonMark strips exactly one space from each end when both ends
    have one (and the content isn't all spaces). That stripping is what
    separates an edge backtick from the delimiter, and it would also eat a
    real leading and trailing space, so both cases get padded."""
    fence = "`" * (_longest_backtick_run(text) + 1)
    pad = text.startswith("`") or text.endswith("`")
    pad = pad or (text.startswith(" ") and text.endswith(" ") and text.strip(" ") != "")
    if pad:
        text = f" {text} "
    return f"{fence}{text}{fence}"


def _render_code_run_text(text: str, in_table: bool) -> str:
    """Inline code for `text`, which may span lines.

    A code span can't hold a line break: CommonMark turns one into a space,
    and in a paragraph a raw newline can start a new block (a "# " heading,
    a "- " item) before the span is parsed. So each line becomes its own
    span, joined by <br> the same way a table cell joins its lines.

    In a table cell, a "|" splits the cell before inline parsing, and the
    GFM `\\|` escape inside a code span shows its backslash in renderers
    that don't implement that rule. A line holding a "|" is written as raw
    HTML <code> instead, which no table parser splits on. Text inside raw
    HTML is still parsed as Markdown, so every ASCII punctuation character
    becomes a numeric entity: an entity is never Markdown syntax, and a
    backslash can't escape the "&" that starts one."""
    spans: list[str] = []
    for line in text.split("\n"):
        if not line:
            spans.append("")
        elif in_table and "|" in line:
            escaped = "".join(f"&#{ord(c)};" if c in string.punctuation else c for c in line)
            spans.append(f"<code>{escaped}</code>")
        else:
            spans.append(_code_span(line))
    return "<br>".join(spans)


# A GFM delimiter row can only carry what Markdown can express (#1337): a
# JUSTIFIED cell has no GFM form and stays `---`. START reaches it only from a
# table where it isn't Docs' default, such as a Drive `.docx` import
# (`doc_to_ast._start_is_default`, #1503).
_GFM_COLUMN_DELIMITERS = {"START": ":--", "CENTER": ":-:", "END": "--:"}


def _render_table(table: Table) -> str:
    if not table.rows:
        return ""
    ncols = max((sum(c.colspan for c in row.cells) for row in table.rows), default=0)
    if ncols == 0:
        return ""

    phantom = _build_phantom_set(table)
    grid: list[list[str]] = [["" for _ in range(ncols)] for _ in range(len(table.rows))]
    # A column only carries an alignment when every cell in it that has text
    # agrees on one (#1337): Docs aligns per cell and Markdown per column, so
    # a mixed or unaligned column stays `---`. Cells without text never vote.
    votes: list[set[str]] = [set() for _ in range(ncols)]
    unaligned_text: list[bool] = [False] * ncols
    for r, row in enumerate(table.rows):
        col = 0
        for cell in row.cells:
            while (r, col) in phantom:
                col += 1
            if col < ncols:
                text = _render_cell(cell)
                grid[r][col] = text
                if text:
                    span = min(cell.colspan, ncols - col)
                    for c in range(col, col + span):
                        if cell.alignment:
                            votes[c].add(cell.alignment)
                        else:
                            unaligned_text[c] = True
            col += cell.colspan

    delimiters = [
        # JUSTIFIED has no GFM form, so .get falls back to --- (#1337).
        _GFM_COLUMN_DELIMITERS.get(next(iter(votes[c])), "---")
        if len(votes[c]) == 1 and not unaligned_text[c]
        else "---"
        for c in range(ncols)
    ]

    lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(delimiters) + " |"]
    for row_cells in grid[1:]:
        lines.append("| " + " | ".join(row_cells) + " |")
    return "\n".join(lines)


def _render_cell(cell: Cell) -> str:
    parts = _render_inline_parts(
        _coalesce_plain_runs(_coalesce_code_runs(cell.children)), in_table=True, cell=True
    )
    # Every part is already table-safe, with its newlines turned into <br>,
    # so strip() here only removes incidental whitespace, never an edge
    # spacer paragraph (#594 QA round 2; see _table_safe).
    return _join_inline(parts).strip()


def _table_safe(text: str) -> str:
    """Make rendered non-code Markdown safe inside a pipe-table cell.

    Pipe-table cells are single-line: a literal newline (from a multi-
    paragraph cell, see doc_to_ast.py's _cell_content_to_children) would
    break the table's row structure, so it becomes a <br> instead. "|" is
    escaped for the same structural reason.

    This runs per part, before _render_cell's strip(), not on the joined
    cell text after it (#594 QA round 2): a spacer paragraph at the very
    start or end of a cell shows up as a leading/trailing "\\n", and
    stripping first silently ate exactly that newline. "<br>" is not
    whitespace, so converting first keeps the spacer.

    Code runs never go through this: _render_code_run_text writes its own
    <br> and table-safe <code>, and escaping its output again would put a
    literal backslash inside the code (#938). Only a code link's
    destination is passed through here."""
    return text.replace("\n", "<br>").replace("|", "\\|")


def _render_comment(comment: dict) -> str:
    """Comment authors, anchors, and text are all plain text (Drive's
    `content`, not `htmlContent`), so none of it may render as Markdown
    structure (#984). See _comment_text for how each line is kept literal.

    The quote is a blockquote ended by a blank line, since the comment text
    after it would otherwise be a lazy continuation of the quote. Without a
    quote, the author line ends in a hard break so the text starts on its own
    line. A reply's continuation lines are indented to the list item's
    content column, so they stay in the item instead of ending the list."""
    author = _comment_inline((comment.get("author") or {}).get("display_name") or "Unknown")
    content = _comment_text(comment.get("content") or "")
    lines = [f"**{author}**"]
    if comment.get("quoted_text"):
        lines.append(_blockquote(_comment_text(comment["quoted_text"]), 1) + "\n")
    elif content.split("\n", 1)[0]:
        lines[0] += "\\"
    lines.append(content)
    for reply in comment.get("replies", []):
        r_author = _comment_inline((reply.get("author") or {}).get("display_name") or "Unknown")
        first, *rest = _comment_text(reply.get("content") or "", starts_block=False).split("\n")
        lines.append(
            "\n".join(
                [f"  - **{r_author}**: {first}"] + [f"    {line}" if line else "" for line in rest]
            )
        )
    return "\n".join(lines) + "\n"


def _comment_inline(text: str) -> str:
    # "|" too: consecutive comment lines like "a | b" and "-|-" form a table.
    return _escape(text).replace("|", "\\|")


def _comment_text(text: str, starts_block: bool = True) -> str:
    """Multi-line plain text as Markdown that renders as the same lines. Each
    line is escaped inline, and block markers are escaped on every line that
    can start a block: all of them, except a first line that follows other
    text on its own line (a reply's, after "**author**: "). Every line
    followed by a non-empty one ends in a hard break ("\\"); a soft break
    would join them into one line. An empty line stays a paragraph break."""
    lines = [_comment_inline(line) for line in text.split("\n")]
    for i in range(len(lines)):
        if i or starts_block:
            lines[i] = _escape_leading_block_marker(lines[i])
    for i in range(len(lines) - 1):
        if lines[i] and lines[i + 1]:
            lines[i] += "\\"
    return "\n".join(lines)
