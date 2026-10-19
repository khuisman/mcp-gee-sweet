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
# "1. Not actually a list item" and "# Not a heading either"). Scoped to plain
# Paragraph rendering only: Heading/NamedBlock/BulletItem already have their
# own legitimate prefix on the same line, so content following it is never
# re-parsed as a new block starting mid-line.
_LEADING_SIMPLE_MARKER = re.compile(r"^(#{1,6}|[>*+-])(?=[ \t]|$)")
_LEADING_ORDERED_MARKER = re.compile(r"^(\d{1,9})([.)])(?=[ \t]|$)")
# A line of only "-" (spaces allowed) is a thematic break, or a setext
# underline under a preceding line, and so is a line of only "=". "*" and "_"
# rules can't occur: _escape has already escaped both (#993).
_LEADING_RULE_LINE = re.compile(r"^(?:=+[ \t]*|-[- \t]*)$")

_NESTED_TABLE_PLACEHOLDER = (
    "*(nested table omitted — Markdown tables can't contain a table; "
    "use get_doc_structure for full fidelity)*"
)


def ast_to_markdown(nodes: list[DocNode], comments: list[dict] | None = None) -> str:
    """Serialize a list of DocNode into a single Markdown document string."""
    parts: list[str] = []
    prev_node: DocNode | None = None
    for node in nodes:
        rendered = _render_table(node) if isinstance(node, Table) else _render_block(node)
        if prev_node is not None:
            # Consecutive list items get a single newline, not a blank line, so
            # they render as one "tight" list (CommonMark still parses a blank-
            # line-separated run as the same list, just needlessly "loose" —
            # no correctness difference, only readability of the output).
            same_list_run = isinstance(node, BulletItem) and isinstance(prev_node, BulletItem)
            parts.append("\n" if same_list_run else "\n\n")
        parts.append(rendered)
        prev_node = node

    markdown = "".join(parts)
    if not markdown.endswith("\n"):
        markdown += "\n"

    if comments:
        markdown += "\n---\n\n## Comments\n\n"
        markdown += "\n".join(_render_comment(c) for c in comments)

    return markdown


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


def _render_block(node: Heading | Paragraph | BulletItem | NamedBlock) -> str:
    if isinstance(node, Paragraph) and _is_code_block(node):
        body = _render_code_block(node)
    elif isinstance(node, Heading):
        body = f"{'#' * node.level} {_render_inline(node.runs)}".rstrip()
    elif isinstance(node, NamedBlock):
        # No Markdown equivalent to Docs' distinct TITLE/SUBTITLE styles — the
        # closest visual match is H1/H2 (see get_doc_as_markdown's docstring).
        level = 1 if node.style_type == "TITLE" else 2
        body = f"{'#' * level} {_render_inline(node.runs)}".rstrip()
    elif isinstance(node, BulletItem):
        indent = "  " * node.depth
        if node.checked is not None:
            marker = "- [x] " if node.checked else "- [ ] "
        elif node.ordered:
            marker = "1. "
        else:
            marker = "- "
        body = f"{indent}{marker}{_render_inline(node.runs)}"
    else:
        body = _escape_leading_block_marker(_render_inline(node.runs))

    depth = getattr(node, "blockquote_depth", 0)
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
    parts: list[str] = []
    for item in _coalesce_code_runs(items):
        if isinstance(item, Image):
            parts.append(_render_image(item))
        else:
            parts.append(_render_run(item))
    return _join_inline(parts)


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


def _render_image(image: Image) -> str:
    """Markdown for one image, wrapped in a link when the image is linked.
    Every image goes through here, so a linked image keeps its link in a
    code paragraph, a table cell, and ordinary text alike (#951)."""
    body = f"![{_escape(image.alt or '')}]({_md_link_dest(image.src)})"
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


def _render_table(table: Table) -> str:
    if not table.rows:
        return ""
    ncols = max((sum(c.colspan for c in row.cells) for row in table.rows), default=0)
    if ncols == 0:
        return ""

    phantom = _build_phantom_set(table)
    grid: list[list[str]] = [["" for _ in range(ncols)] for _ in range(len(table.rows))]
    for r, row in enumerate(table.rows):
        col = 0
        for cell in row.cells:
            while (r, col) in phantom:
                col += 1
            if col < ncols:
                grid[r][col] = _render_cell(cell)
            col += cell.colspan

    lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(["---"] * ncols) + " |"]
    for row_cells in grid[1:]:
        lines.append("| " + " | ".join(row_cells) + " |")
    return "\n".join(lines)


def _render_cell(cell: Cell) -> str:
    parts: list[str] = []
    for child in _coalesce_code_runs(cell.children):
        if isinstance(child, Table):
            parts.append(_NESTED_TABLE_PLACEHOLDER)
        elif isinstance(child, Image):
            parts.append(_table_safe(_render_image(child)))
        else:
            parts.append(_render_run(child, in_table=True))
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
