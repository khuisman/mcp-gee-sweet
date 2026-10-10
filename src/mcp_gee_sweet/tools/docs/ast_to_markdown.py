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

import html
import re

from .ast import BulletItem, Cell, DocNode, Heading, Image, NamedBlock, Paragraph, Run, Table
from .emitter import _build_phantom_set

_MD_ESCAPE = re.compile(r"([\\`*_\[\]])")
_BACKTICK_RUN = re.compile(r"`+")

# A paragraph whose rendered text starts with one of these (unescaped) would be
# misread by any CommonMark parser as a different block type entirely — an ATX
# heading, a blockquote, a bullet item, or an ordered-list item — rather than
# the plain paragraph text it actually is (#591 QA round 1, live-confirmed for
# "1. Not actually a list item" and "# Not a heading either"). Scoped to plain
# Paragraph rendering only: Heading/NamedBlock/BulletItem already have their
# own legitimate prefix on the same line, so content following it is never
# re-parsed as a new block starting mid-line.
_LEADING_SIMPLE_MARKER = re.compile(r"^([#>]|[-*+])(?=[ \t]|$)")
_LEADING_ORDERED_MARKER = re.compile(r"^(\d{1,9})([.)])(?=[ \t]|$)")

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
    signal available (see markdown-support.md's write-side mapping table)."""
    runs = [r for r in node.runs if isinstance(r, Run)]
    return bool(runs) and all(r.font_family == "Courier New" for r in runs)


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
            segments.append(f"![{_escape(item.alt or '')}]({_md_link_dest(item.src)})")
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
        prefix = "> " * depth
        body = "\n".join(
            f"{prefix}{line}" if line else prefix.rstrip() for line in body.split("\n")
        )
    return body


def _escape_leading_block_marker(text: str) -> str:
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
            parts.append(f"![{_escape(item.alt or '')}]({_md_link_dest(item.src)})")
        else:
            parts.append(_render_run(item))
    return "".join(parts)


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
    if run.text == "":
        return ""
    if run.font_family == "Courier New":
        body = _render_code_run_text(run.text, in_table)
        if not run.link_url:
            return body
        dest = _md_link_dest(run.link_url)
        return f"[{body}]({_table_safe(dest) if in_table else dest})"

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
    return _MD_ESCAPE.sub(r"\\\1", text)


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
    HTML <code> with the pipe as an entity instead, which no table parser
    splits on."""
    spans: list[str] = []
    for line in text.split("\n"):
        if not line:
            spans.append("")
        elif in_table and "|" in line:
            escaped = html.escape(line, quote=False).replace("|", "&#124;")
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
            parts.append(_table_safe(f"![{_escape(child.alt or '')}]({_md_link_dest(child.src)})"))
        elif _is_code_run(child):
            # Already table-safe: _render_code_run_text handles its own
            # newlines and pipes, and escaping its output again would put a
            # literal backslash inside the code (#938).
            parts.append(_render_run(child, in_table=True))
        else:
            parts.append(_table_safe(_render_run(child)))
    # Pipe-table cells are single-line: a literal newline (from a multi-
    # paragraph cell, see doc_to_ast.py's _cell_content_to_children) would
    # break the table's row structure, so it becomes a <br> instead. "|" is
    # escaped for the same structural reason.
    #
    # \n -> <br> conversion must happen BEFORE strip(), not after (#594 QA
    # round 2): a spacer paragraph at the very start or end of a cell (as
    # opposed to one sandwiched between two real lines) shows up here as a
    # leading/trailing "\n" on the joined text — stripping first, as an
    # earlier version of this function did, silently ate exactly that
    # newline, making an edge spacer indistinguishable from a cell with no
    # spacer at all. "<br>" is not whitespace, so converting first means
    # strip() only removes genuine incidental whitespace, never a spacer
    # that's already been turned into a <br> marker.
    return "".join(parts).strip()


def _table_safe(text: str) -> str:
    return text.replace("\n", "<br>").replace("|", "\\|")


def _render_comment(comment: dict) -> str:
    author = (comment.get("author") or {}).get("display_name") or "Unknown"
    lines = [f"**{author}**"]
    if comment.get("quoted_text"):
        lines.append(f"> {comment['quoted_text']}")
    lines.append(comment.get("content") or "")
    for reply in comment.get("replies", []):
        r_author = (reply.get("author") or {}).get("display_name") or "Unknown"
        lines.append(f"  - **{r_author}**: {reply.get('content') or ''}")
    return "\n".join(lines) + "\n"
