"""YAML front matter at the start of a Markdown file, which no Markdown entry point shows.

Plan rule D3 (docs/qa/tests/docs_markdown.md, #1173): a leading "---"-delimited YAML
block is omitted from the Doc. Shared by _md_to_html (our converter) and the uploads
that hand a .md to Drive's own Markdown import, so the two engines agree on what
counts as front matter.
"""

import re

_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
_OPEN_RE = re.compile(r"---[ \t]*")
_CLOSE_RE = re.compile(r"(?:---|\.\.\.)[ \t]*")
# A top-level YAML mapping key: a quoted scalar, or a plain one that doesn't start with
# a YAML indicator character, then ":" and whitespace or the end of the line.
_KEY_RE = re.compile(
    r"""(?:"[^"]*"[ \t]*|'[^']*'[ \t]*|[^\s#\-?:,\[\]{}&*!|>'"%@`][^:]*):(?:[ \t]|$)"""
)
# One line with its ending. Only CR, LF and CRLF end a line, as in CommonMark;
# str.splitlines would also split on \v, \f and U+2028.
_LINE_RE = re.compile(r".*?(?:\r\n|\r|\n)|.+", re.DOTALL)
# Where a quoted scalar can start inside a flow collection: after one of these, or
# at the start of a line.
_FLOW_TOKEN_START = "[{,:"


def _is_blank(line: str) -> bool:
    # Spaces and tabs only, as CommonMark counts a blank line: a line holding a
    # no-break space is an authored spacer, not blank.
    return not line.strip(" \t\r\n")


def _scan(s: str, quote: str | None, depth: int) -> tuple[str | None, int]:
    """The open quoted scalar and flow-collection depth after reading s, given those
    open before it. Stops once both are closed; the rest of the line is a comment or
    trailing text the caller doesn't need. One pass over s."""
    last = None  # the last non-blank character outside a quoted scalar
    i = 0
    while i < len(s):
        c = s[i]
        if quote == '"':
            if c == "\\":
                i += 2
                continue
            if c == '"':
                quote = None
        elif quote == "'":
            if c == "'":
                if s.startswith("''", i):
                    i += 2
                    continue
                quote = None
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c in "\"'" and (last is None or last in _FLOW_TOKEN_START):
            quote = c
        if quote is None and depth <= 0:
            return None, 0
        if quote is None and c not in " \t":
            last = c
        i += 1
    return quote, depth


def strip_front_matter(text: str) -> str:
    """text without its leading YAML front matter, and the blank lines right after it.

    Front matter is a first line of "---" and a later closing line of "---" or "...",
    each allowing trailing spaces or tabs, after an optional byte-order mark. The lines
    between must read as a YAML mapping: every line at column 0 that isn't blank or a
    "#" comment is a "key:" line, or a "- " item of a key whose value is on the lines
    below it, and there's at least one key. A value that is a quoted scalar or a flow
    collection ("[...]", "{...}") is followed to its close, across lines at any
    indentation. Other indented lines (nested values, block scalars) are kept as part
    of the block unread. Explicit "? " keys aren't recognized.

    Anything else is returned unchanged: an unclosed block or value, an empty block
    ("---" then "---", two thematic breaks), or one holding a line that isn't a key,
    so "---", "Some text", "---" stays a rule and a setext heading. A block that is a
    mapping is always front matter, as on GitHub, even if the author meant a rule and
    a heading whose text reads "key: value". Line endings are kept as written, and only
    lines of spaces and tabs count as blank. A text that doesn't start with "---" is
    returned without being split into lines."""
    start = 1 if text.startswith(_BOM) else 0
    if not text.startswith("---", start):
        return text
    lines = _LINE_RE.finditer(text, start)
    if not _OPEN_RE.fullmatch(next(lines).group().rstrip("\r\n")):
        return text
    has_key = False
    # Whether a column-0 "- " item may follow: the last key had no value on its line.
    sequence_ok = False
    quote: str | None = None
    depth = 0
    for m in lines:
        line = m.group().rstrip("\r\n")
        if _CLOSE_RE.fullmatch(line):
            if quote is not None or depth > 0 or not has_key:
                return text
            rest = m.end()
            for after in _LINE_RE.finditer(text, rest):
                if not _is_blank(after.group()):
                    break
                rest = after.end()
            return text[rest:]
        if quote is not None or depth > 0:
            quote, depth = _scan(line, quote, depth)
            continue
        if _is_blank(line) or line[0] in " \t#":
            continue
        if line[0] == "-" and line[1:2] in ("", " ", "\t"):
            if not sequence_ok:
                return text
            continue
        key = _KEY_RE.match(line)
        if key is None:
            return text
        has_key = True
        value = line[key.end() :].lstrip(" \t")
        sequence_ok = not value or value[0] == "#"
        if value and value[0] in "\"'":
            quote, depth = _scan(value[1:], value[0], 0)
        elif value and value[0] in "[{":
            quote, depth = _scan(value, None, 0)
    return text
