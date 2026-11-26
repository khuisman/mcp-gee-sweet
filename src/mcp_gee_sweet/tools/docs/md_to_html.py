"""Markdown -> HTML for the Docs write tools: CommonMark plus GFM, via markdown-it-py.

The HTML goes on through html_to_ast and the emitter, the same pipeline as HTML input.
Design and the behavior changes from Python-Markdown: docs/design/markdown-parser.md.
"""

import bisect
import functools
import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.common.utils import normalizeReference, unescapeAll
from markdown_it.token import Token

from ..front_matter import strip_front_matter

# GFM extended autolinks (https://github.github.com/gfm/#autolinks-extension-): a
# www. or http(s):// link, or an email address, at the start of the text or after
# whitespace, "*", "_", "~" or "(". A domain is dot-separated segments of
# alphanumerics, "_" and "-", with no "_" in the last two (checked in
# _gfm_autolink_matches). Like cmark-gfm, a scheme-ful link may have a single-segment
# domain (http://localhost); a www. one already has its dot. Trailing punctuation and
# an unbalanced ")" are trimmed afterwards (_trim_autolink).
_GFM_URL_RE = re.compile(
    r"(?:^|(?<=[\s*_~(]))(?:https?://|www\.)[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*[^\s<]*"
)
# An email is found from its "@" outwards (_gfm_email_matches), not by a regex that
# tries every start position: "_" is both a valid left boundary and a local-part
# character, so that regex rescans to the end of the text from each "_" in a long
# token with no "@" (quadratic; "a_" * 20000 took about a second).
_EMAIL_LOCAL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-")
_EMAIL_DOMAIN_RE = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+")
_AUTOLINK_LEFT_BOUNDARY = "*_~("
_AUTOLINK_TRAILING_PUNCT = "?!.,:*_~'\""
_ENTITY_NAME_RE = re.compile(r"[A-Za-z0-9]+")
_HTML_A_OPEN_RE = re.compile(r"<a[\s>]", re.IGNORECASE)
_HTML_A_CLOSE_RE = re.compile(r"</a\s*>", re.IGNORECASE)
# Inline tokens after which the next text token starts at a valid autolink boundary:
# a line break, or an emphasis or strikethrough delimiter ("*", "_", "~"). After a
# code span, a link or an inline HTML tag, it doesn't ("`x`www.a.com" isn't linked).
_AUTOLINK_BOUNDARY_TOKENS = frozenset(
    {
        "softbreak",
        "hardbreak",
        "em_open",
        "em_close",
        "strong_open",
        "strong_close",
        "s_open",
        "s_close",
    }
)


def _trim_autolink(url: str) -> str:
    """Drop what GFM leaves outside an extended autolink: trailing punctuation, an
    unbalanced closing paren, and a trailing entity reference like "&hl;".

    Works back from the end with running paren counts, never re-searching or slicing
    the whole URL per character: that was quadratic on a long run of entities or
    parens ("&a;" * 10000 took over a second, PR #1228 QA round 2)."""
    end = len(url)
    opens, closes = url.count("("), url.count(")")
    while end:
        ch = url[end - 1]
        if ch == ";":
            amp = url.rfind("&", 0, end - 1)
            if amp == -1 or not _ENTITY_NAME_RE.fullmatch(url, amp + 1, end - 1):
                break
            end = amp
        elif ch in _AUTOLINK_TRAILING_PUNCT:
            end -= 1
        elif ch == ")" and opens < closes:
            closes -= 1
            end -= 1
        else:
            break
    return url[:end]


def _at_boundary(text: str, pos: int, start_ok: bool) -> bool:
    if pos == 0:
        return start_ok
    before = text[pos - 1]
    return before.isspace() or before in _AUTOLINK_LEFT_BOUNDARY


def valid_gfm_domain(host: str) -> bool:
    """GFM's "valid domain" segment test: non-empty dot-separated segments, with no
    "_" in the last two. Which characters a host may hold is the caller's. Shared with
    emitter._storable_link_url's www. rewrite (#1180), so an autolink and a written
    www. link agree on what a host is."""
    segments = host.split(".")
    return all(segments) and "_" not in "".join(segments[-2:])


def _gfm_url_matches(text: str, start_ok: bool):
    for m in _GFM_URL_RE.finditer(text):
        if m.start() == 0 and not start_ok:
            continue
        label = _trim_autolink(m.group(0))
        # The domain is checked on the trimmed label, since trimming can eat it
        # ("http://__", "www.__"). It must be non-empty dot-separated segments, with
        # no "_" in the last two (GFM's "valid domain"), and a www. link keeps its dot.
        scheme = label.startswith(("http://", "https://"))
        if not scheme and not label.startswith("www."):
            continue
        host = re.split(r"[/?#]", label.split("://", 1)[1] if scheme else label, maxsplit=1)[0]
        if not valid_gfm_domain(host):
            continue
        # https://, not GFM's http://, matching emitter._storable_link_url's www.
        # rewrite of a written link (#1281).
        href = label if scheme else "https://" + label
        yield m.start(), m.start() + len(label), href


def _gfm_email_matches(text: str, start_ok: bool):
    at = text.find("@")
    while at != -1:
        start = at
        while start > 0 and text[start - 1] in _EMAIL_LOCAL_CHARS:
            start -= 1
        domain = _EMAIL_DOMAIN_RE.match(text, at + 1)
        end = at + 1
        if start < at and domain and _at_boundary(text, start, start_ok):
            # An email may not end in "-" or "_"; a trailing "." is punctuation.
            label = text[start : domain.end()].rstrip(".")
            if label[-1] not in "-_":
                yield start, start + len(label), "mailto:" + label
                end = start + len(label)
        at = text.find("@", end)


def _gfm_autolink_matches(text: str, start_ok: bool = True):
    """Yield (start, end, href) for each GFM extended autolink in text, in order.
    start_ok says whether position 0 is a valid left boundary (see
    _AUTOLINK_BOUNDARY_TOKENS)."""
    matches = sorted([*_gfm_url_matches(text, start_ok), *_gfm_email_matches(text, start_ok)])
    pos = 0
    for start, end, href in matches:
        if start >= pos:
            yield start, end, href
            pos = end


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
        prev: Token | None = None
        for tok in block.children:
            if tok.type == "link_open" or (
                tok.type == "html_inline" and _HTML_A_OPEN_RE.match(tok.content)
            ):
                link_depth += 1
            elif tok.type == "link_close" or (
                tok.type == "html_inline" and _HTML_A_CLOSE_RE.match(tok.content)
            ):
                link_depth = max(0, link_depth - 1)
            start_ok = prev is None or prev.type in _AUTOLINK_BOUNDARY_TOKENS
            prev = tok
            if tok.type != "text" or link_depth or not tok.content:
                children.append(tok)
                continue
            pos = 0
            for start, end, href in _gfm_autolink_matches(tok.content, start_ok):
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


# Block structure only, for _verbatim_lines: the same block grammar as the renderer
# (raw HTML on, GFM tables), with no inline pass.
# markdown-it drops anything nested deeper than maxNesting, silently, and each list
# level costs two (ul + li): the commonmark preset's 20 lost an item's text from
# about level 10, which Python-Markdown kept. 100 keeps a 50-level list and still
# parses ">" * 1200 without RecursionError.
_MAX_NESTING = 100
_BLOCK_SCANNER = (
    MarkdownIt("commonmark", {"html": True, "maxNesting": _MAX_NESTING})
    .enable(["table"])
    .disable(["inline"])
)


def _verbatim_lines(md_text: str) -> dict[int, int]:
    """The lines whose text a pre-pass must not read as Markdown, each mapped to the
    first line of its block: a fenced code block's body and closing fence, and every
    line of an indented code block or a raw HTML block. Found by markdown-it's own
    block parser, so a fence opened on a list-marker line ("- ```") or nested in a
    quote is found the same way the renderer finds it."""
    lines: dict[int, int] = {}
    for tok in _BLOCK_SCANNER.parse(md_text):
        if tok.type in ("fence", "code_block", "html_block") and tok.map:
            start, end = tok.map
            for line in range(start + 1 if tok.type == "fence" else start, end):
                lines[line] = start
    return lines


_LIST_MARKER_RE = re.compile(r"(?P<marker>[-+*]|(?P<number>\d{1,9})[.)])(?P<space>[ \t]+|$)")
_THEMATIC_BREAK_RE = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*$")
# One quote level: up to 3 spaces, ">", and the one optional space CommonMark absorbs.
_QUOTE_PREFIX_RE = re.compile(r" {0,3}> ?")
# A line that starts a block of its own, so it ends any list it isn't indented into.
# Not a "|" line: one that isn't a table is lazy paragraph text (a table start is
# handled on its own, by D2).
_LIST_ENDING_BLOCK_RE = re.compile(r"#{1,6}(?:[ \t]|$)|>|`{3,}|~{3,}")
# The pre-pass's quote recursion stops at markdown-it's own nesting cap, past which
# it nests nothing anyway; without a cap ">" * 1200 raised RecursionError.
_MAX_QUOTE_DEPTH = _MAX_NESTING
# The line D2 puts before a table that would otherwise be lazy text of a quote inside
# a list item. An HTML comment ends the quote's paragraph without a blank line, which
# would make the list loose; html_to_ast ignores comments.
_LAZY_BREAK = "<!-- -->"

# A pipe-table header row and the delimiter row under it (GFM "tables" extension).
_TABLE_ROW_RE = re.compile(r"^ {0,3}(?!>)\S.*\|.*$|^ {0,3}\|")
_TABLE_DELIM_RE = re.compile(r"^ {0,3}\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


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


def _space_after_marker(col: int, marker: re.Match) -> int:
    """How many columns the whitespace after a marker at col spans, with tabs stopping
    every 4 columns from where they sit, not from column 0."""
    end = col + len(marker.group("marker"))
    start = end
    for ch in marker.group("space"):
        end += 1 if ch == " " else 4 - end % 4
    return end - start


def _content_offset(col: int, marker: re.Match) -> int:
    """How far past the marker's own column an item's content starts: the marker's
    width plus up to 4 columns of space after it. Five or more columns, or nothing
    after the marker, means content starts one column past the marker."""
    gap = _space_after_marker(col, marker)
    return len(marker.group("marker")) + (gap if 1 <= gap <= 4 and marker.group("space") else 1)


def _moved_marker_line(col: int, body: str, marker: re.Match, new_marker: int) -> str:
    """A marker line moved to start at new_marker. A tab after the marker is written
    as the spaces it spanned where it was: moved, the same tab would reach a different
    tab stop and change where the item's content starts."""
    space = marker.group("space")
    if "\t" in space:
        space = " " * _space_after_marker(col, marker)
    return " " * new_marker + marker.group("marker") + space + body[marker.end() :]


def _shift_verbatim(line: str, container_col: int, delta: int) -> str:
    """A code or raw HTML line moved by delta with its list item. Only the item's own
    indentation (up to container_col) is rewritten; whitespace past it is the code's
    content and stays as written, tabs included (a Makefile recipe needs its tab)."""
    if delta == 0 or not line.strip():
        return line
    col = idx = 0
    while idx < len(line) and col < container_col and line[idx] in " \t":
        col += 1 if line[idx] == " " else 4 - col % 4
        idx += 1
    # A tab that ran past container_col spanned some content columns too.
    overshoot = max(0, col - container_col)
    return " " * (min(col, container_col) + delta) + " " * overshoot + line[idx:]


def _owner(stack: list[_ListItemColumns], col: int) -> _ListItemColumns | None:
    """The innermost open item a line indented to col continues, if any."""
    return next((item for item in reversed(stack) if col >= item.orig_content), None)


def _table_cell_count(row: str) -> int:
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return len(_UNESCAPED_PIPE_RE.split(row))


def _starts_table(header: str, delimiter: str) -> bool:
    """True when header and delimiter open a GFM table: a row with a pipe, then a
    delimiter row with a pipe and the same number of cells. A bare "---" under a line
    holding "|" is a setext heading underline, not a delimiter row."""
    return (
        _TABLE_ROW_RE.match(header) is not None
        and _TABLE_DELIM_RE.match(delimiter) is not None
        and "|" in delimiter
        and _table_cell_count(header) == _table_cell_count(delimiter)
    )


# _rewrite's output: (the input line it came from, or None for an inserted line, and
# the text).
_Rewritten = list[tuple[int | None, str]]


def _rewrite(
    lines: list[str],
    verbatim: dict[int, int],
    depth: int = 0,
    keys: list[int] | None = None,
) -> _Rewritten:
    """Apply plan rules D1 and D2 to lines (see _preprocess). verbatim is
    _verbatim_lines for exactly these lines, and keys its sorted line numbers, so a
    quoted run's lines map into it by offset (a bisect, not a scan of the whole map)
    and the recursion never parses again."""
    if keys is None:
        keys = sorted(verbatim)
    out: _Rewritten = []
    stack: list[_ListItemColumns] = []
    # Per line: how far it moved, and the column its item's content starts at, which
    # a code block opened on that line moves with (_shift_verbatim).
    anchors: dict[int, tuple[int, int]] = {}
    prev_blank = False
    # Whether the line above is paragraph text, which a list may only interrupt with
    # a bullet or "1." (CommonMark's rule; a list item's own text counts).
    prev_text = False
    # Whether the line above ends a quote run or is a list item's text that a table
    # line not indented into the item would continue lazily (D2).
    prev_lazy_target = False
    # The item whose text holds a quote the line above belongs to, which a table
    # indented into that item would continue lazily (D2).
    quote_in: _ListItemColumns | None = None
    in_table = False

    def shifted(line: str, col: int, body: str, delta: int) -> str:
        return line if delta == 0 or not body else " " * max(0, col + delta) + body

    i = 0
    while i < len(lines):
        idx, line = i, lines[i]
        i += 1
        col, body = _leading_columns(line)

        if idx in verbatim:
            first = verbatim[idx]
            if first in anchors:
                # A fence body moves with the line that opened it.
                delta, container = anchors[first]
            else:
                owner = _owner(stack, col)
                if owner is None:
                    stack = []
                delta = owner.new_content - owner.orig_content if owner else 0
                container = owner.orig_content if owner else 0
            anchors[idx] = (delta, container)
            out.append((idx, _shift_verbatim(line, container, delta)))
            prev_blank = prev_text = prev_lazy_target = in_table = False
            quote_in = None
            continue

        quote = _QUOTE_PREFIX_RE.match(line)
        if quote and (not stack or col < stack[0].orig_content):
            # A quote not indented into a list ends it. Strip one quote level from
            # each line of the run, apply the rules inside it, and put each prefix back.
            stack = []
            start = idx
            prefixes = [quote.group(0)]
            while i < len(lines) and (next_quote := _QUOTE_PREFIX_RE.match(lines[i])):
                prefixes.append(next_quote.group(0))
                i += 1
            run = [q[len(p) :] for q, p in zip(lines[start:i], prefixes, strict=True)]
            if depth >= _MAX_QUOTE_DEPTH:
                out.extend((start + k, q) for k, q in enumerate(lines[start:i]))
            else:
                run_keys = keys[bisect.bisect_left(keys, start) : bisect.bisect_left(keys, i)]
                inner_verbatim = {k - start: verbatim[k] - start for k in run_keys}
                inner_keys = [k - start for k in run_keys]
                for source, text in _rewrite(run, inner_verbatim, depth + 1, inner_keys):
                    if source is None:
                        # An inserted line, inside the same quote.
                        out.append((None, (prefixes[0] + text) if text else prefixes[0].rstrip()))
                    else:
                        out.append((start + source, prefixes[source] + text))
            prev_blank = prev_text = in_table = False
            prev_lazy_target = True
            quote_in = None
            continue

        if not body:
            out.append((idx, line))
            prev_blank, prev_text, prev_lazy_target, in_table = True, False, False, False
            quote_in = None
            continue

        marker = _LIST_MARKER_RE.match(body)
        if marker and _THEMATIC_BREAK_RE.match(body):
            marker = None
        if marker and (stack or col <= 3):
            has_content = bool(body[marker.end() :].strip())
            keep = len(stack)
            sibling = None
            while keep:
                top = stack[keep - 1]
                if col >= top.orig_marker + 2:
                    break
                keep -= 1
                if col >= top.orig_marker:
                    sibling = top
                    break
            number = marker.group("number")
            may_start_list = has_content and (number is None or int(number) == 1)
            if sibling is None and prev_text and not may_start_list and keep:
                # It can't open a sub-list inside the item's text. Short of the item's
                # content column it isn't inside the item at all, so CommonMark reads it
                # at the item's own level (the list's next item, or a new list there);
                # moving it in, as D1 would, would make it the item's paragraph text.
                top = stack[keep - 1]
                if col < top.orig_content:
                    keep -= 1
                    sibling = top
            if sibling is not None or not prev_text or may_start_list:
                stack = stack[:keep]
                if sibling is not None:
                    # Moved as far as the sibling was, not onto its column: snapping a
                    # staircase ("- a", " - b", "  - c") to one column would push the
                    # unmoved lines after it deeper than CommonMark puts them.
                    new_marker = col + sibling.new_marker - sibling.orig_marker
                elif stack:
                    parent = stack[-1]
                    new_marker = parent.new_content + max(0, col - parent.orig_content)
                else:
                    new_marker = col
                offset = _content_offset(col, marker)
                stack.append(_ListItemColumns(col, new_marker, col + offset, new_marker + offset))
                anchors[idx] = (new_marker - col, col + offset)
                quote_in = None
                out.append(
                    (
                        idx,
                        line
                        if new_marker == col
                        else _moved_marker_line(col, body, marker, new_marker),
                    )
                )
                prev_blank, prev_text, prev_lazy_target, in_table = False, has_content, True, False
                continue

        owner = _owner(stack, col)
        starts_table = (
            not in_table and i < len(lines) and i not in verbatim and _starts_table(line, lines[i])
        )
        if starts_table and owner is None and prev_lazy_target:
            # D2: a table under a list item's or a quote's text, not indented into
            # the item, would be read as that text's lazy continuation. A blank line
            # ends the list or quote so the table starts its own block. A table
            # indented into an item, or under a plain paragraph, is a table already:
            # a blank line there would only make the list loose.
            out.append((None, ""))
        elif starts_table and owner is not None and owner is quote_in:
            # The same, for a quote inside the item: the table, indented into the
            # item, would be the quote's lazy text. _LAZY_BREAK ends the quote and
            # keeps the table in the item without making the list loose.
            out.append((None, " " * owner.new_content + _LAZY_BREAK))
        if owner is not None:
            delta = owner.new_content - owner.orig_content
            container = owner.orig_content
        else:
            if stack and (
                prev_blank
                or starts_table
                or _LIST_ENDING_BLOCK_RE.match(body)
                or _THEMATIC_BREAK_RE.match(body)
            ):
                stack = []
            delta = container = 0
        anchors[idx] = (delta, container)
        out.append((idx, shifted(line, col, body, delta)))
        if starts_table:
            in_table = True
        ends_paragraph = _LIST_ENDING_BLOCK_RE.match(body) or _THEMATIC_BREAK_RE.match(body)
        if body.startswith(">") and owner is not None:
            quote_in = owner
        elif ends_paragraph or starts_table:
            quote_in = None
        prev_blank = False
        prev_text = not ends_paragraph
        # Lazy text continues the item above, so a table under it is lazy too; once a
        # table or another block takes over, there's nothing left to continue.
        prev_lazy_target = prev_lazy_target and not in_table and not ends_paragraph
    return out


def _preprocess(md_text: str) -> str:
    """Plan rules D1 and D2, applied line by line before markdown-it renders.

    D1 (#1071): a list marker indented at least 2 columns further than the previous
    item's marker nests under that item, whatever the parent marker's width. CommonMark
    nests a marker only once it reaches the parent's content column, so "1. A" followed
    by "  - a" (2 spaces, short of column 3) doesn't nest, and the 2-space sub-lists
    models write under numbered items stay flat or turn into text. Each such marker is
    rewritten to start at its parent's content column, and the item's continuation
    lines move by the same amount. A marker that already reaches the content column
    keeps its offset past it, so 4-space and tab indents are unchanged.

    A marker that would start a new list right under paragraph text counts only if
    CommonMark lets it interrupt a paragraph: a bullet, or an ordered marker numbered
    1, with text after it. Anything else there ("2019. A great year") is paragraph
    text, as markdown-it will read it.

    D2: a pipe table directly under a list item's or a quote's text, not indented into
    the item, starts its own block: GFM would read its rows as that text's lazy
    continuation, so a blank line goes in before it.

    Code and raw HTML (_verbatim_lines, from one block parse of md_text) are never read
    as Markdown; they only move with the item they belong to. A run of quoted lines not
    inside a list gets the same rules one quote level in. Anything once a list has
    ended is left as written."""
    lines = md_text.split("\n")
    return "\n".join(text for _, text in _rewrite(lines, _verbatim_lines(md_text)))


# A link or image whose destination holds whitespace: "![alt](./Screen Shot.png)",
# "[notes](./My Notes.md "t")". CommonMark requires "<...>" around such a destination
# and otherwise leaves the whole thing as text, but Python-Markdown accepted it, and a
# local path with a space (every macOS screenshot) is what people write. The
# destination is two or more space-separated pieces with no quotes, parens or angle
# brackets, then an optional quoted title, so anything CommonMark itself accepts (one
# piece, or "<...>") still goes through markdown-it's own link and image rules.
_SPACED_DESTINATION = (
    r"\(\s*([^\s()<>\"']+(?:[ \t]+[^\s()<>\"']+)+)"
    r"(?:[ \t]+(\"[^\"\n]*\"|'[^'\n]*'))?\s*\)"
)
_SPACED_IMAGE_RE = re.compile(r"!\[([^\[\]\n]*)\]" + _SPACED_DESTINATION)
_SPACED_LINK_RE = re.compile(r"\[([^\[\]\n]*)\]" + _SPACED_DESTINATION)


def _spaced_destination(state, pattern: re.Pattern) -> tuple[re.Match, str, str | None] | None:
    # posMax bounds the match to the text being parsed: inside a link's label it is
    # the label's end, not the end of the line.
    m = pattern.match(state.src, state.pos, state.posMax)
    if not m:
        return None
    # Backslash escapes and entities resolve as in any other destination or title. One
    # that resolves to a quote ("url &quot;tit&quot;") was a title written as entities,
    # not a path; leave it to CommonMark, which reads it as text.
    href = unescapeAll(m.group(2))
    if '"' in href or "'" in href or not state.md.validateLink(href):
        return None
    # A label that names a reference definition is that reference, followed by text,
    # as CommonMark reads it ("[foo](not a link)" with "[foo]: /url" defined).
    if normalizeReference(m.group(1)) in state.env.get("references", {}):
        return None
    title = unescapeAll(m.group(3)[1:-1]) if m.group(3) else None
    return m, href, title


def _spaced_image_rule(state, silent: bool) -> bool:
    if not state.src.startswith("![", state.pos):
        return False
    found = _spaced_destination(state, _SPACED_IMAGE_RE)
    if found is None:
        return False
    m, src, title = found
    if not silent:
        token = state.push("image", "img", 0)
        token.attrs = {"src": src, "alt": ""}
        if title is not None:
            token.attrs["title"] = title
        token.content = m.group(1)
        children: list[Token] = []
        state.md.inline.parse(m.group(1), state.md, state.env, children)
        token.children = children
    state.pos = m.end()
    return True


def _spaced_link_rule(state, silent: bool) -> bool:
    # Links can't nest, so none inside another link's label.
    if state.src[state.pos] != "[" or state.linkLevel > 0:
        return False
    found = _spaced_destination(state, _SPACED_LINK_RE)
    if found is None:
        return False
    m, href, title = found
    if not silent:
        token = state.push("link_open", "a", 1)
        token.attrs = {"href": href}
        if title is not None:
            token.attrs["title"] = title
        # The label is inline content: tokenize it in place, as markdown-it's own link
        # rule does, so its emphasis and code reach the same token stream.
        end, old_max = m.end(), state.posMax
        state.pos, state.posMax = m.start(1), m.end(1)
        state.linkLevel += 1
        state.md.inline.tokenize(state)
        state.linkLevel -= 1
        state.posMax = old_max
        state.push("link_close", "a", -1)
        state.pos = end
        return True
    state.pos = m.end()
    return True


# Single-tilde delimiters carry their own marker, so balance_pairs' same-marker
# pairing matches them by width and never mixes a `~` run with a `~~` one. Any
# other value works as the distinct marker; balance_pairs only ever compares
# markers for equality.
_SINGLE_TILDE_MARKER = 0x7E7E


def _autolink_span_windows(state) -> dict:
    """For every text token index, the GFM extended-autolink spans of its text
    run and the token's offset in it, from one linear pass (#1436 review).

    The window is each maximal run of adjacent text tokens — a `text_special`
    one (a `\\_` escape, an `&amp;` entity) reads as text here, so a URL that
    holds one stays whole, exactly the token text_join later hands the
    autolink core rule — with a dropped `~` delimiter, fragments_join merges
    the run back into exactly that token — and `start_ok` mirrors that rule's
    boundary check, so a `~` a reader sees as part of a URL never strikes:
    GitHub links the whole URL, and so did develop. The spans are what
    `_gfm_autolink_matches` actually links — a URL that an overlapping email
    match drops never suppresses a tilde, since the core rule renders no
    link there (#1612) — so the suppression and the link the reader sees can't
    disagree. The spans are in order, so a delimiter's lookup bisects them
    instead of scanning (#1436 review). A window without a scheme or a `www.`
    holds no URL span, so it skips the URL pass entirely (#1612)."""
    result: dict[int, tuple[list, int]] = {}
    tokens = state.tokens
    i = 0
    total = len(tokens)
    while i < total:
        if tokens[i].type not in ("text", "text_special"):
            i += 1
            continue
        first = i
        pieces: list[str] = []
        offsets: list[int] = []
        length_so_far = 0
        while i < total and tokens[i].type in ("text", "text_special"):
            offsets.append(length_so_far)
            length_so_far += len(tokens[i].content)
            pieces.append(tokens[i].content)
            i += 1
        window = "".join(pieces)
        prev = tokens[first - 1] if first > 0 else None
        start_ok = prev is None or prev.type in _AUTOLINK_BOUNDARY_TOKENS
        spans = (
            [(start, end) for start, end, _ in _gfm_autolink_matches(window, start_ok)]
            if "://" in window or "www." in window
            else []
        )
        for token_index, offset in zip(range(first, i), offsets, strict=True):
            result[token_index] = (spans, offset)
    return result


def _cull_tildes_inside_autolinks(state, delimiters, windows) -> None:
    """Drop every tilde delimiter that sits inside a GFM autolink span, so the
    URL text stays whole for the autolink core rule, as on develop.

    A `~` run counts when it starts inside a span; a `~~` run when it lies
    entirely inside one, which keeps `see https://x.com/~~a~~/b` a single
    link the way GitHub renders it (#1612). The spans are in order, so the one
    that could cover a delimiter is the last that starts at or before it: one
    bisect, not a scan of every span, which was quadratic on a paragraph of
    many URLs and many tildes ("www.a.com ~ " * 20000, #1436 review)."""
    kept = []
    for delimiter in delimiters:
        if delimiter.marker == 0x7E:
            spans, offset = windows[delimiter.token]
            idx = bisect.bisect_right(spans, offset, key=lambda span: span[0]) - 1
            content = state.tokens[delimiter.token].content
            if content == "~":
                if idx >= 0 and spans[idx][1] > offset:
                    continue
            elif idx >= 0 and spans[idx][0] <= offset and spans[idx][1] >= offset + 2:
                continue
        kept.append(delimiter)
    delimiters[:] = kept


def _balance_pairs(state) -> None:
    """Pair the emphasis and tilde delimiters of one inline run together, the
    way cmark's ``process_emphasis`` does: every closer in document order,
    over all delimiter kinds at once."""
    _process_delimiters(state, state.delimiters)
    for meta in state.tokens_meta:
        if meta and "delimiters" in meta:
            _process_delimiters(state, meta["delimiters"])


def _process_delimiters(state, delimiters) -> None:
    """markdown-it's ``balance_pairs`` walk, with cmark-gfm's tilde pairing
    folded in where the two disagree.

    Upstream already walks every delimiter kind in one closer-order pass, and
    its ``jumps`` stand in for cmark's ``remove_delimiter``; but it pairs any
    two tilde runs whatever their widths, which is not what cmark-gfm does
    (#1612, #1436). Here a tilde closer runs cmark-gfm's pairing instead: the
    nearest live tilde opener wins under the emphasis arithmetic whatever its
    width, and the attempt consumes the opener, the closer and everything
    between them whether the widths match or not, so a mixed-width row renders
    as the literal text GitHub renders (#1612). Emphasis pairing is upstream's
    own, untouched.

    Folding the pairing into the walk is what lets a strike wrap an emphasis
    span (#1617 review): in ``~x *a ~b* c~`` the ``*`` closer pairs first and
    its match consumes ``~b``, so ``c~`` reaches back to ``~x`` and strikes
    ``x <em>a ~b</em> c``, as on develop and GitHub. A tilde pass that ran
    before the emphasis had paired saw ``~b`` still live, paired it with
    ``c~`` and culled ``~x``, so nothing struck. The consumption cuts both
    ways: a matched tilde pair consumes the unmatched emphasis delimiters
    inside it, so ``~x *a b~ c*`` strikes with no emphasis, and a tilde
    closer that can't open and finds no opener is consumed itself, as on
    cmark.

    Everything consumed is unlinked from a previous-pointer chain over the
    delimiters of its kind (``find`` below — cmark's ``remove_delimiter`` with
    path compression), so an opener search or a consumption walk only hops
    over live delimiters and each is consumed at most once. Without it every
    closer rescanned the tildes an earlier pair consumed: ``"~a " * 8000 +
    "b~ " * 8000`` walked back over them one at a time, about 64M search
    steps for 48 KB of input (#1617 review). A closer that finds no opener
    still sets the lower bound for later closers of its width, which keeps
    the failed searches linear too (#1502, #1612).

    Surviving 1-tilde pairs are recorded the way upstream records its own —
    ``end``, the same jump bookkeeping, and the pair's own marker — so nothing
    pairs or converts them as a ``~~`` run and ``_single_tilde_pairs``
    converts them; ``~~`` pairs keep the upstream marker and convert as they
    always have. Everything else — consumed by a mismatched attempt, or never
    paired — keeps ``end == -1`` and stays literal text.
    """
    maximum = len(delimiters)
    if not maximum:
        return

    tildes = [i for i, d in enumerate(delimiters) if d.marker == 0x7E]
    tilde_index = {segment_index: k for k, segment_index in enumerate(tildes)}
    widths = [1 if state.tokens[delimiters[i].token].content == "~" else 2 for i in tildes]
    others = [i for i, d in enumerate(delimiters) if d.marker != 0x7E]
    # cmark's remove_delimiter, as a previous-pointer chain per kind: find()
    # returns the nearest chain position at or before k that is still live,
    # compressing the pointers it walked so the hop is paid once. Consuming a
    # delimiter only marks it dead in place (#1617 review).
    tilde_prev = list(range(-1, len(tildes)))
    tilde_dead = [False] * len(tildes)
    other_prev = list(range(-1, len(others)))
    other_dead = [False] * len(others)

    def find(prev: list[int], dead: list[bool], k: int) -> int:
        root = k
        while root >= 0 and dead[root]:
            root = prev[root]
        while k >= 0 and dead[k] and prev[k] != root:
            prev[k], k = root, prev[k]
        return root

    def consume_tildes_between(opener_idx: int, closer_idx: int) -> None:
        # Everything strictly between a matched emphasis pair is consumed with
        # it, so the tilde runs inside can no longer pair (#1617 review).
        k = find(tilde_prev, tilde_dead, bisect.bisect_left(tildes, closer_idx) - 1)
        while k >= 0 and tildes[k] > opener_idx:
            tilde_dead[k] = True
            k = find(tilde_prev, tilde_dead, k)

    def consume_others_between(opener_idx: int, closer_idx: int) -> None:
        # The emphasis delimiters a tilde attempt steps over are consumed with
        # it, as cmark's remove_delimiter would. A pair another closer already
        # matched is gone from cmark's stack by itself — its conversion reads
        # only `end`, so its flags can stay.
        k = find(other_prev, other_dead, bisect.bisect_left(others, closer_idx) - 1)
        while k >= 0 and others[k] > opener_idx:
            other = delimiters[others[k]]
            if other.end == -1:
                other.open = other.close = False
            other_dead[k] = True
            k = find(other_prev, other_dead, k)

    openers_bottom: dict[int, list[int]] = {}
    tilde_bottom = {1: 0, 2: 0}
    header_idx = 0
    last_token_idx = -2
    jumps: list[int] = []
    closer_idx = 0
    while closer_idx < maximum:
        closer = delimiters[closer_idx]
        jumps.append(0)

        if (
            delimiters[header_idx].marker != closer.marker
            or last_token_idx != closer.token - 1
        ):
            header_idx = closer_idx
        last_token_idx = closer.token

        closer.length = closer.length or 0

        if closer.marker == 0x7E:
            # cmark-gfm's tilde pairing, at this closer's turn in the shared
            # walk (#1612, #1617 review).
            k = tilde_index[closer_idx]
            if closer.close and not tilde_dead[k]:
                width = widths[k]
                cand = find(tilde_prev, tilde_dead, k - 1)
                opener_pos = -1
                while cand >= tilde_bottom[width]:
                    candidate = delimiters[tildes[cand]]
                    if candidate.open and (
                        not (closer.open or candidate.close)
                        or width % 3 == 0
                        or (widths[cand] + width) % 3 != 0
                    ):
                        opener_pos = cand
                        break
                    cand = find(tilde_prev, tilde_dead, cand - 1)
                if opener_pos == -1:
                    tilde_bottom[width] = k
                    if not closer.open:
                        tilde_dead[k] = True
                else:
                    opener_idx = tildes[opener_pos]
                    tilde_dead[opener_pos] = True
                    j = find(tilde_prev, tilde_dead, k - 1)
                    while j > opener_pos:
                        tilde_dead[j] = True
                        j = find(tilde_prev, tilde_dead, j)
                    tilde_dead[k] = True
                    consume_others_between(opener_idx, closer_idx)
                    if widths[opener_pos] == width:
                        opener = delimiters[opener_idx]
                        if opener_idx > 0 and not delimiters[opener_idx - 1].open:
                            last_jump = jumps[opener_idx - 1] + 1
                        else:
                            last_jump = 0
                        jumps[closer_idx] = closer_idx - opener_idx + last_jump
                        jumps[opener_idx] = last_jump
                        closer.open = False
                        opener.end = closer_idx
                        opener.close = False
                        last_token_idx = -2
                        if width == 1:
                            opener.marker = _SINGLE_TILDE_MARKER
                            closer.marker = _SINGLE_TILDE_MARKER
            closer_idx += 1
            continue

        if not closer.close:
            closer_idx += 1
            continue

        # From here on this is markdown-it's own balance_pairs, verbatim.
        if closer.marker not in openers_bottom:
            openers_bottom[closer.marker] = [-1, -1, -1, -1, -1, -1]

        min_opener_idx = openers_bottom[closer.marker][(3 if closer.open else 0) + (closer.length % 3)]

        opener_idx = header_idx - jumps[header_idx] - 1

        new_min_opener_idx = opener_idx

        while opener_idx > min_opener_idx:
            opener = delimiters[opener_idx]

            if opener.marker != closer.marker:
                opener_idx -= jumps[opener_idx] + 1
                continue

            if opener.open and opener.end < 0:
                is_odd_match = (
                    (opener.close or closer.open)
                    and (opener.length + closer.length) % 3 == 0
                    and (opener.length % 3 != 0 or closer.length % 3 != 0)
                )

                if not is_odd_match:
                    if opener_idx > 0 and not delimiters[opener_idx - 1].open:
                        last_jump = jumps[opener_idx - 1] + 1
                    else:
                        last_jump = 0

                    jumps[closer_idx] = closer_idx - opener_idx + last_jump
                    jumps[opener_idx] = last_jump

                    closer.open = False
                    opener.end = closer_idx
                    opener.close = False
                    new_min_opener_idx = -1
                    last_token_idx = -2
                    consume_tildes_between(opener_idx, closer_idx)
                    break

            opener_idx -= jumps[opener_idx] + 1

        if new_min_opener_idx != -1:
            openers_bottom[closer.marker][(3 if closer.open else 0) + (closer.length % 3)] = (
                new_min_opener_idx
            )

        closer_idx += 1


def _tilde_autolink_cull(state, autolink_urls: bool) -> None:
    """Drop every tilde delimiter that sits inside a GFM autolink span, before
    ``balance_pairs`` runs.

    The upstream ``strikethrough_single_tilde`` tokenizer accepts runs of one
    or two tildes (three or more are consumed as plain text). This rule drops
    the runs a GFM extended autolink swallows first (#1612), keeping the URL
    text whole for the autolink core rule, as on develop — but only when this
    parser autolinks: with ``autolink_urls=False`` there is no link to keep
    whole, so ``www.a.com/~x~`` strikes instead of rendering neither linked
    nor struck (#1612). A paragraph with no tilde delimiter skips the URL
    pass entirely (#1612). Pairing itself is ``_balance_pairs``'s, where the
    emphasis delimiters and the surviving tildes meet in closer order.
    """
    segments = [state.delimiters]
    for meta in state.tokens_meta:
        if meta and "delimiters" in meta:
            segments.append(meta["delimiters"])
    tilde_segments = [segment for segment in segments if any(d.marker == 0x7E for d in segment)]
    if not tilde_segments:
        return
    if autolink_urls:
        windows = _autolink_span_windows(state)
        for segment in tilde_segments:
            _cull_tildes_inside_autolinks(state, segment, windows)


def _single_tilde_pairs(state) -> None:
    """Convert the single-tilde pairs ``balance_pairs`` matched into ``s`` tags,
    the conversion the upstream strikethrough post-process only performs for
    the ``~~`` marker."""

    def convert_one(delimiters) -> None:
        for delimiter in delimiters:
            if delimiter.marker != _SINGLE_TILDE_MARKER or delimiter.end == -1:
                continue
            end = delimiters[delimiter.end]
            token = state.tokens[delimiter.token]
            token.type = "s_open"
            token.tag = "s"
            token.nesting = 1
            token.markup = "~"
            token.content = ""
            token = state.tokens[end.token]
            token.type = "s_close"
            token.tag = "s"
            token.nesting = -1
            token.markup = "~"
            token.content = ""

    convert_one(state.delimiters)
    for meta in state.tokens_meta:
        if meta and "delimiters" in meta:
            convert_one(meta["delimiters"])


def _build_markdown_parser(autolink_urls: bool) -> MarkdownIt:
    # CommonMark plus GFM's table and strikethrough extensions. Raw HTML passes through
    # to html_to_ast, as it did under Python-Markdown. Task-list items stay literal
    # "[ ] "/"[x] " text, which html_to_ast turns into checkbox items.
    # strikethrough_single_tilde widens the strikethrough tokenizer to GFM's full
    # form: `~x~` strikes like `~~x~~`, and a run of three or more tildes stays
    # literal text (#1335). The upstream option only tokenizes the runs: pairing
    # is cmark-gfm's algorithm, folded into balance_pairs itself, which walks
    # every delimiter kind in closer order the way cmark's process_emphasis
    # does — so a mixed-width row renders like GitHub (#1612), a strike that
    # wraps an emphasis span strikes around it (#1617 review), and the pass
    # stays linear on the tildes an earlier pair consumed (#1617 review).
    # _single_tilde_pairs converts the 1-tilde pairs.
    md = MarkdownIt(
        "commonmark",
        {
            "html": True,
            "maxNesting": _MAX_NESTING,
            "strikethrough_single_tilde": True,
        },
    ).enable(["table", "strikethrough"])
    # The autolink cull only protects URLs when this parser links them
    # (#1612): with autolinks off there is no link to keep whole.
    md.inline.ruler2.before(
        "balance_pairs",
        "tilde_autolink_cull",
        functools.partial(_tilde_autolink_cull, autolink_urls=autolink_urls),
    )
    md.inline.ruler2.at("balance_pairs", _balance_pairs)
    md.inline.ruler2.after("strikethrough", "single_tilde_pairs", _single_tilde_pairs)
    # Keep link and image destinations as written. markdown-it percent-encodes them
    # by default, which breaks a local image path ("café.png" becomes "caf%C3%A9.png")
    # that _resolve_image_source opens as-is. validateLink still screens schemes.
    md.normalizeLink = lambda url: url
    md.inline.ruler.before("image", "spaced_image", _spaced_image_rule)
    md.inline.ruler.before("link", "spaced_link", _spaced_link_rule)
    if autolink_urls:
        md.core.ruler.push("gfm_autolink", _gfm_autolink_rule)
    return md


_MARKDOWN_PARSERS = {flag: _build_markdown_parser(flag) for flag in (True, False)}

# The parsers are shared by every asyncio.to_thread worker (content._convert_doc_content), and
# markdown-it builds each ruler's rule cache lazily on first use. Build every one
# here, at import, so concurrent first conversions never see a half-built cache.
for _parser in (*_MARKDOWN_PARSERS.values(), _BLOCK_SCANNER):
    for _ruler in (
        _parser.core.ruler,
        _parser.block.ruler,
        _parser.inline.ruler,
        _parser.inline.ruler2,
    ):
        _ruler.getRules("")


def _md_to_html(md_text: str, autolink_urls: bool = True) -> str:
    """Convert CommonMark/GFM Markdown to HTML with markdown-it-py: tables,
    strikethrough and GFM extended autolinks (bare http(s)://, www. and email
    addresses), plus plan rules D1 and D2 (_preprocess) and D3, leading YAML front
    matter left out (strip_front_matter).

    autolink_urls=False skips the extended autolinks for callers who want a URL to
    render as plain text — e.g. a placeholder or example. Per-URL suppression (rather
    than disabling it for the whole call) is available by wrapping just that URL in
    backticks, which already protects it as an inline code span."""
    # The pre-pass works line by line, so normalize line endings first, as markdown-it
    # itself does: in a CRLF file a blank line would otherwise read as "\r", not blank.
    md_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    md_text = strip_front_matter(md_text)
    return _MARKDOWN_PARSERS[bool(autolink_urls)].render(_preprocess(md_text))
