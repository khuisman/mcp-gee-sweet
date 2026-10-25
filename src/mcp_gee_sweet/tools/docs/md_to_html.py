"""Markdown -> HTML for the Docs write tools: CommonMark plus GFM, via markdown-it-py.

The HTML goes on through html_to_ast and the emitter, the same pipeline as HTML input.
Design and the behavior changes from Python-Markdown: docs/design/markdown-parser.md.
"""

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

# GFM extended autolinks (https://github.github.com/gfm/#autolinks-extension-): a
# www. or http(s):// link, or an email address, at the start of the text or after
# whitespace, "*", "_", "~" or "(". A domain is dot-separated segments of
# alphanumerics, "_" and "-", with no "_" in the last two (checked in
# _gfm_autolink_matches). Like cmark-gfm, a scheme-ful link may have a single-segment
# domain (http://localhost); a www. one already has its dot. Trailing punctuation and
# an unbalanced ")" are trimmed afterwards (_trim_autolink).
_GFM_AUTOLINK_RE = re.compile(
    r"(?:^|(?<=[\s*_~(]))"
    r"(?:"
    r"(?P<url>(?:https?://|www\.)[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*[^\s<]*)"
    r"|(?P<email>[A-Za-z0-9._+-]+@[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)"
    r")"
)
_AUTOLINK_TRAILING_PUNCT = "?!.,:*_~'\""
_AUTOLINK_TRAILING_ENTITY_RE = re.compile(r"&[A-Za-z0-9]+;$")
_HTML_A_OPEN_RE = re.compile(r"<a[\s>]", re.IGNORECASE)
_HTML_A_CLOSE_RE = re.compile(r"</a\s*>", re.IGNORECASE)


def _trim_autolink(url: str) -> str:
    """Drop what GFM leaves outside an extended autolink: trailing punctuation, an
    unbalanced closing paren, and a trailing entity reference like "&hl;"."""
    while url:
        entity = _AUTOLINK_TRAILING_ENTITY_RE.search(url)
        if entity:
            url = url[: entity.start()]
        elif url[-1] in _AUTOLINK_TRAILING_PUNCT or (
            url[-1] == ")" and url.count("(") < url.count(")")
        ):
            url = url[:-1]
        else:
            break
    return url


def _gfm_autolink_matches(text: str):
    """Yield (start, end, href) for each GFM extended autolink in text."""
    for m in _GFM_AUTOLINK_RE.finditer(text):
        if m.group("url"):
            label = _trim_autolink(m.group("url"))
            # The last two domain segments may not hold "_" (GFM's "valid domain").
            host = re.split(r"[/?#]", label.split("://", 1)[-1], maxsplit=1)[0]
            if "_" in ".".join(host.split(".")[-2:]):
                continue
            href = label if "://" in label else "http://" + label
        else:
            label = m.group("email")
            # An email may not end in "-" or "_"; a trailing "." is punctuation.
            label = label.rstrip(".")
            if label[-1] in "-_":
                continue
            href = "mailto:" + label
        yield m.start(), m.start() + len(label), href


def _gfm_autolink_rule(state) -> None:
    """markdown-it core rule: turn GFM extended autolinks in plain text into links.

    Runs after inline parsing, so it only sees text tokens: an <autolink>, a code span
    or a raw HTML tag is a different token and never re-matched. Text inside a link,
    Markdown or a raw HTML <a>, is skipped too, since a link can't nest."""
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        children = []
        link_depth = 0
        for tok in block.children:
            if tok.type == "link_open" or (
                tok.type == "html_inline" and _HTML_A_OPEN_RE.match(tok.content)
            ):
                link_depth += 1
            elif tok.type == "link_close" or (
                tok.type == "html_inline" and _HTML_A_CLOSE_RE.match(tok.content)
            ):
                link_depth = max(0, link_depth - 1)
            if tok.type != "text" or link_depth or not tok.content:
                children.append(tok)
                continue
            pos = 0
            for start, end, href in _gfm_autolink_matches(tok.content):
                if start > pos:
                    children.append(_text_token(tok.content[pos:start], tok.level))
                children.append(
                    Token(
                        "link_open",
                        "a",
                        1,
                        attrs={"href": href},
                        markup="linkify",
                        info="auto",
                        level=tok.level,
                    )
                )
                children.append(_text_token(tok.content[start:end], tok.level + 1))
                children.append(
                    Token("link_close", "a", -1, markup="linkify", info="auto", level=tok.level)
                )
                pos = end
            if pos == 0:
                children.append(tok)
            elif pos < len(tok.content):
                children.append(_text_token(tok.content[pos:], tok.level))
        block.children = children


def _text_token(content: str, level: int) -> Token:
    return Token("text", "", 0, content=content, level=level)


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _closes_fence(line: str, fence: str) -> bool:
    """True when line closes the code block that fence opened: the same character, at
    least as long, and nothing after it but whitespace."""
    m = re.match(r"^\s*(`{3,}|~{3,})\s*$", line)
    return m is not None and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)


_LIST_MARKER_RE = re.compile(r"(?P<marker>[-+*]|\d{1,9}[.)])(?P<space>[ \t]+|$)")
_THEMATIC_BREAK_RE = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*$")
# A line that starts a block of its own, so it ends any list it isn't indented into.
# One quote level: up to 3 spaces, ">", and the one optional space CommonMark absorbs.
_QUOTE_PREFIX_RE = re.compile(r" {0,3}> ?")
_LIST_ENDING_BLOCK_RE = re.compile(r"#{1,6}(?:[ \t]|$)|>|`{3,}|~{3,}|\|")


@dataclass
class _ListItemColumns:
    orig_marker: int
    new_marker: int
    orig_content: int
    new_content: int


def _leading_columns(line: str) -> tuple[int, str]:
    """The column the line's text starts at, with tabs stopping every 4 columns as
    CommonMark counts them, and the text itself."""
    col = 0
    for i, ch in enumerate(line):
        if ch == " ":
            col += 1
        elif ch == "\t":
            col += 4 - col % 4
        else:
            return col, line[i:]
    return col, ""


def _nest_lists(md_text: str) -> str:
    """Plan rule D1 (#1071): a list marker indented at least 2 columns further than
    the previous item's marker nests under that item, whatever the parent marker's
    width.

    CommonMark nests a marker only once it reaches the parent's content column, so
    "1. A" followed by "  - a" (2 spaces, short of column 3) doesn't nest, and the
    2-space sub-lists models write under numbered items stay flat or turn into text.
    This rewrites each such marker to start at its parent's content column, and moves
    the item's continuation lines (fenced code included) by the same amount, so
    markdown-it nests what D1 says should nest. A marker that already reaches the
    content column keeps its offset past it, so 4-space and tab indents are unchanged.
    A run of quoted lines outside any list gets the same rule one quote level in.
    Lines inside a top-level fenced code block, and anything once a list has ended,
    are left as written."""
    out: list[str] = []
    stack: list[_ListItemColumns] = []
    fence: str | None = None
    fence_delta = 0
    prev_blank = False

    def shifted(line: str, col: int, body: str, delta: int) -> str:
        return line if delta == 0 else " " * max(0, col + delta) + body

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        col, body = _leading_columns(line)
        quote = _QUOTE_PREFIX_RE.match(line) if fence is None else None
        if quote and (not stack or col < stack[0].orig_content):
            # A quote not indented into a list ends it. Strip one quote level from
            # each line of the run, apply D1 inside it, and put each prefix back.
            stack = []
            run = [line]
            prefixes = [quote.group(0)]
            while i < len(lines) and (next_quote := _QUOTE_PREFIX_RE.match(lines[i])):
                run.append(lines[i])
                prefixes.append(next_quote.group(0))
                i += 1
            # _nest_lists keeps the line count, so the prefixes line up again.
            inner = _nest_lists("\n".join(q[len(p) :] for q, p in zip(run, prefixes, strict=True)))
            out.extend(p + q for p, q in zip(prefixes, inner.split("\n"), strict=True))
            prev_blank = False
            continue
        if fence is not None:
            if _closes_fence(line, fence):
                fence = None
            out.append(shifted(line, col, body, fence_delta) if body else line)
            continue
        if not body:
            out.append(line)
            prev_blank = True
            continue

        marker = _LIST_MARKER_RE.match(body)
        if marker and _THEMATIC_BREAK_RE.match(body):
            marker = None
        if marker and (stack or col <= 3):
            width = len(marker.group("marker"))
            space = marker.group("space")
            # The content column: up to 4 spaces after the marker count; 5 or more
            # mean an indented code block starts one space in.
            gap = len(space.expandtabs(4)) if space else 1
            content_offset = width + (gap if 1 <= gap <= 4 else 1)
            sibling = None
            while stack:
                top = stack[-1]
                if col >= top.orig_marker + 2:
                    break
                stack.pop()
                if col >= top.orig_marker:
                    sibling = top
                    break
            if sibling is not None:
                new_marker = sibling.new_marker
            elif stack:
                parent = stack[-1]
                new_marker = parent.new_content + max(0, col - parent.orig_content)
            else:
                new_marker = col
            stack.append(
                _ListItemColumns(col, new_marker, col + content_offset, new_marker + content_offset)
            )
            out.append(shifted(line, col, body, new_marker - col))
            prev_blank = False
            continue

        owner = next((item for item in reversed(stack) if col >= item.orig_content), None)
        if owner is not None:
            delta = owner.new_content - owner.orig_content
        else:
            if stack and (
                prev_blank or _LIST_ENDING_BLOCK_RE.match(body) or _THEMATIC_BREAK_RE.match(body)
            ):
                stack = []
            delta = 0
        opening = _FENCE_RE.match(line)
        if opening:
            fence = opening.group(1)
            fence_delta = delta
        out.append(shifted(line, col, body, delta))
        prev_blank = False
    return "\n".join(out)


# A pipe-table header row and the delimiter row under it (GFM "tables" extension).
_TABLE_ROW_RE = re.compile(r"^ {0,3}(?!>)\S.*\|.*$|^ {0,3}\|")
_TABLE_DELIM_RE = re.compile(r"^ {0,3}\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _separate_tables(md_text: str) -> str:
    """Plan rule D2: a pipe table directly under a paragraph, list item or quote line
    starts its own block, after that one.

    GFM lets a table interrupt a paragraph but not a list item's or a quote's lazy
    continuation, so there the header and delimiter rows read as more text. Inserting a
    blank line before the header makes them a table at the top level in every case.
    Skipped inside a fenced code block, and when the line above is already a table row
    (GFM makes those lines more body rows of the table above)."""
    lines = md_text.split("\n")
    out: list[str] = []
    fence: str | None = None
    in_table = False
    for i, line in enumerate(lines):
        if fence is not None:
            if _closes_fence(line, fence):
                fence = None
            out.append(line)
            continue
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            fence = fence_match.group(1)
            in_table = False
            out.append(line)
            continue
        if not line.strip():
            in_table = False
            out.append(line)
            continue
        starts_table = (
            i + 1 < len(lines)
            and _TABLE_ROW_RE.match(line) is not None
            and _TABLE_DELIM_RE.match(lines[i + 1]) is not None
        )
        if starts_table and not in_table and out and out[-1].strip():
            out.append("")
        if starts_table:
            in_table = True
        out.append(line)
    return "\n".join(out)


# An image whose destination holds whitespace and no title: "![alt](./Screen Shot.png)".
# CommonMark requires "<...>" around such a destination and otherwise leaves the
# whole thing as text, but Python-Markdown accepted it, and a local path with a space
# (every macOS screenshot) is what people write. Quotes, parens and angle brackets
# are excluded, so a destination with a title, or any image CommonMark itself
# accepts, still goes through markdown-it's own image rule.
_SPACED_IMAGE_RE = re.compile(r"!\[([^\[\]\n]*)\]\(\s*([^\s()<>\"']+(?:[ \t]+[^\s()<>\"']+)+)\s*\)")


def _spaced_image_rule(state, silent: bool) -> bool:
    if not state.src.startswith("![", state.pos):
        return False
    m = _SPACED_IMAGE_RE.match(state.src, state.pos)
    if not m or not state.md.validateLink(m.group(2)):
        return False
    if not silent:
        token = state.push("image", "img", 0)
        token.attrs = {"src": m.group(2), "alt": ""}
        token.content = m.group(1)
        children: list[Token] = []
        state.md.inline.parse(m.group(1), state.md, state.env, children)
        token.children = children
    state.pos = m.end()
    return True


def _build_markdown_parser(autolink_urls: bool) -> MarkdownIt:
    # CommonMark plus GFM's table and strikethrough extensions. Raw HTML passes through
    # to html_to_ast, as it did under Python-Markdown. Task-list items stay literal
    # "[ ] "/"[x] " text, which html_to_ast turns into checkbox items.
    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    # Keep link and image destinations as written. markdown-it percent-encodes them
    # by default, which breaks a local image path ("café.png" becomes "caf%C3%A9.png")
    # that _resolve_image_source opens as-is. validateLink still screens schemes.
    md.normalizeLink = lambda url: url
    md.inline.ruler.before("image", "spaced_image", _spaced_image_rule)
    if autolink_urls:
        md.core.ruler.push("gfm_autolink", _gfm_autolink_rule)
    return md


_MARKDOWN_PARSERS = {flag: _build_markdown_parser(flag) for flag in (True, False)}


def _md_to_html(md_text: str, autolink_urls: bool = True) -> str:
    """Convert CommonMark/GFM Markdown to HTML with markdown-it-py: tables,
    strikethrough and GFM extended autolinks (bare http(s)://, www. and email
    addresses), plus plan rules D1 (_nest_lists) and D2 (_separate_tables).

    autolink_urls=False skips the extended autolinks for callers who want a URL to
    render as plain text — e.g. a placeholder or example. Per-URL suppression (rather
    than disabling it for the whole call) is available by wrapping just that URL in
    backticks, which already protects it as an inline code span."""
    # The pre-passes work line by line, so normalize line endings first, as markdown-it
    # itself does: in a CRLF file a blank line would otherwise read as "\r", not blank.
    md_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    return _MARKDOWN_PARSERS[autolink_urls].render(_separate_tables(_nest_lists(md_text)))
