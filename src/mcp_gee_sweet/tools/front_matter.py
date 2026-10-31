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


def strip_front_matter(text: str) -> str:
    """text without its leading YAML front matter, and the blank lines right after it.

    Front matter is a first line of "---" and a later closing line of "---" or "...",
    each allowing trailing spaces or tabs, after an optional byte-order mark. The lines
    between must read as a YAML mapping: every line at column 0 that isn't blank or a
    "#" comment is a "key:" line, and there's at least one. Indented lines (nested
    values, folded text) are kept as part of the block unread.

    Anything else is returned unchanged: an unclosed block, an empty one ("---" then
    "---", two thematic breaks), or one holding a line that isn't a key, so "---",
    "Some text", "---" stays a rule and a setext heading. A block that is a mapping is
    always front matter, as on GitHub, even if the author meant a rule and a heading
    whose text reads "key: value". Line endings are kept as written."""
    lines = _LINE_RE.findall(text)
    if not lines:
        return text
    first = lines[0].removeprefix(_BOM)
    if not _OPEN_RE.fullmatch(first.rstrip("\r\n")):
        return text
    has_key = False
    for i in range(1, len(lines)):
        line = lines[i].rstrip("\r\n")
        if _CLOSE_RE.fullmatch(line):
            if not has_key:
                return text
            rest = i + 1
            while rest < len(lines) and not lines[rest].strip():
                rest += 1
            return "".join(lines[rest:])
        if not line.strip() or line[0] in " \t#":
            continue
        if not _KEY_RE.match(line):
            return text
        has_key = True
    return text
