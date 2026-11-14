"""HTML string → Document AST."""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser

from .ast import (
    BulletItem,
    Cell,
    DocNode,
    Heading,
    Image,
    NamedBlock,
    Paragraph,
    RGBColor,
    Row,
    Run,
    Table,
)

_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}
_NAMED_BLOCK_STYLES = {"title": "TITLE", "subtitle": "SUBTITLE"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# What a browser draws as a block but this parser has no node for (#1391): the HTML
# spec's display:block elements (Rendering, "Flow content" and "Sections and headings",
# plus details, summary and fieldset), less those handled by name (p, pre, headings,
# lists, blockquote, table). Text directly inside one is its own paragraph. An allowlist
# rather than "any unknown tag": an inline tag with no block around it stays a no-op.
_CONTAINER_TAGS = {
    "address",
    "article",
    "aside",
    "body",
    "center",
    "dd",
    "details",
    "dialog",
    "dir",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "header",
    "hgroup",
    "html",
    "legend",
    "main",
    "menu",
    "nav",
    "search",
    "section",
    "summary",
}
# Obsolete elements a browser draws exactly as <pre>: parsed as one (PR #1400 QA round 1).
# Newer stdlib HTMLParser versions read <xmp>'s and <plaintext>'s content as raw text,
# which suits code: there it's one text run either way.
_PRE_ALIASES = {"listing": "pre", "xmp": "pre", "plaintext": "pre"}
# The block tag of a paragraph opened for text directly inside a container. Never a
# _BLOCK_TAGS entry: only _end_anonymous_block closes it.
_ANONYMOUS_BLOCK = "div"
# Elements a browser doesn't draw: a stylesheet, a script, the page title, or fallback
# for a script, frame or plugin. <head> isn't one: its end tag is optional, so it could
# hide the whole document, and everything in it that has text is listed here anyway. Any
# element with the hidden attribute or display:none, and a <dialog> that isn't open, is
# hidden too (_is_hidden). <video>, <audio>, <canvas> and <object> aren't: a Doc can't
# play or draw one, so its fallback content is what a reader can get, and one left
# unclosed in Markdown would otherwise hide the rest of the document (PR #1400 QA
# round 2).
_HIDDEN_TAGS = {
    "datalist",
    "iframe",
    "noembed",
    "noframes",
    "noscript",
    "script",
    "style",
    "template",
    "title",
}
# An end tag outside the table structure never closes past an open table or cell, as in
# a browser: a </div> inside a cell can't close a <div> around the table.
_TABLE_SCOPE_TAGS = {"table", "td", "th"}
_TABLE_STRUCTURE_TAGS = {
    "table",
    "caption",
    "colgroup",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
}


def _end_key(tag: str) -> str:
    """What an end tag matches in the open-element stack. </ol> and </ul> close either
    list type: HTML copied from elsewhere mismatches them in practice, and the list
    handling resolves a mismatch by depth (#382, #450)."""
    return "list" if tag in ("ol", "ul") else tag


def _is_hidden(tag: str, attr_dict: dict) -> bool:
    """True for an element a browser doesn't draw, nothing in which reaches the Doc: a
    _HIDDEN_TAGS element, an unopened <dialog>, or one with the hidden attribute or a
    display:none style. Email HTML keeps preheader text in display:none elements, and a
    tracking pixel is a hidden <img> (PR #1400 QA round 1)."""
    if tag in _HIDDEN_TAGS or "hidden" in attr_dict:
        return True
    if tag == "dialog" and "open" not in attr_dict:
        return True
    return _css_value(attr_dict, "display", _display_value) == "none"


# CSS display keywords, any combination of which _display_value accepts as a valid value.
_DISPLAY_KEYWORDS = {
    "block",
    "contents",
    "flex",
    "flow",
    "flow-root",
    "grid",
    "inline",
    "inline-block",
    "inline-flex",
    "inline-grid",
    "inline-table",
    "list-item",
    "none",
    "ruby",
    "ruby-base",
    "ruby-base-container",
    "ruby-text",
    "ruby-text-container",
    "run-in",
    "table",
    "table-caption",
    "table-cell",
    "table-column",
    "table-column-group",
    "table-footer-group",
    "table-header-group",
    "table-row",
    "table-row-group",
    "-webkit-box",
    "-webkit-inline-box",
    "-moz-box",
    "-moz-inline-box",
    "-ms-flexbox",
    "-ms-inline-flexbox",
    "-ms-grid",
    "-ms-inline-grid",
    "inherit",
    "initial",
    "revert",
    "revert-layer",
    "unset",
}


def _display_value(value: str) -> str | None:
    """A display value as CSS keeps it, or None for one it drops as invalid."""
    words = value.split()
    return value if words and all(w in _DISPLAY_KEYWORDS for w in words) else None


def _css_value(attr_dict: dict, prop: str, parse):
    """The value of `prop` in an element's style attribute, as CSS resolves it, parsed by
    `parse` (None for a value CSS would drop as invalid), or None. An !important
    declaration beats a normal one, and the last valid declaration of the same
    importance wins: CSS drops an invalid one, so `display:none; display:bogus` is none
    (PR #1400 QA round 2)."""
    result, result_important = None, False
    for declaration in (attr_dict.get("style") or "").split(";"):
        name, sep, value = declaration.partition(":")
        if not sep or name.strip().lower() != prop:
            continue
        value = value.strip().lower()
        important = _IMPORTANT.search(value) is not None
        parsed = parse(_IMPORTANT.sub("", value).strip())
        if parsed is not None and (important or not result_important):
            result, result_important = parsed, important
    return result


@dataclass
class _OpenElement:
    """An element in _AstParser's open-element stack."""

    tag: str
    # Pushed inside a hidden element, or hidden itself: its start tag did nothing, so
    # its end tag does nothing either.
    inert: bool = False
    hidden: bool = False
    # Counted in _tag_depth: it took the generic inline-element path.
    counted: bool = False
    # A container that holds its own text, counted in _container_depth.
    container_text: bool = False
    # The formatting this element contributes to runs flushed while it is open, for
    # an inline tag opened with no block around it (#1404); None on every other
    # element. See _AstParser._bare_formatting.
    formatting: _ElementFormatting | None = None


@dataclass(frozen=True)
class _ElementFormatting:
    """The formatting one open inline element contributes to the runs flushed while
    it is open (#1404): recorded on the element itself instead of the live depth
    counters, which every block boundary resets, so a document opening blocks
    inside the tag can no longer end the style at the first boundary. The
    open-element stack ends it instead — at the tag's own close, or an outer
    element's close (#1391) — and `_bare_formatting` keeps it out of table cells."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    mark: bool = False
    code: bool = False
    # "SUBSCRIPT"/"SUPERSCRIPT" for <sub>/<sup>; the innermost open one wins.
    baseline: str | None = None


# What _bare_formatting returns when nothing contributes (#1404).
_NO_FORMATTING = _ElementFormatting()

_INLINE_BOLD = {"b", "strong"}
_INLINE_ITALIC = {"i", "em"}
_INLINE_UNDERLINE = {"u"}
_INLINE_STRIKE = {"s", "strike", "del"}  # <del> strikes too (#1077)
# <sub>/<sup> set the run's baselineOffset; the innermost open one wins (#1119).
_INLINE_BASELINE = {"sub": "SUBSCRIPT", "sup": "SUPERSCRIPT"}
# <mark> highlights its text in yellow, a browser's default <mark> color (#1119).
_INLINE_MARK = "mark"

# The inline formatting tags that can open with no block around them and so record
# their contribution on their open element (#1404) instead of the live counters.
_INLINE_FORMATTING_TAGS = (
    _INLINE_BOLD
    | _INLINE_ITALIC
    | _INLINE_UNDERLINE
    | _INLINE_STRIKE
    | set(_INLINE_BASELINE)
    | {_INLINE_MARK, "code"}
)


def _formatting_of(tag: str) -> _ElementFormatting:
    """The one formatting contribution `tag`'s open element records (#1404). Only
    called for tags in _INLINE_FORMATTING_TAGS."""
    if tag in _INLINE_BOLD:
        return _ElementFormatting(bold=True)
    if tag in _INLINE_ITALIC:
        return _ElementFormatting(italic=True)
    if tag in _INLINE_UNDERLINE:
        return _ElementFormatting(underline=True)
    if tag in _INLINE_STRIKE:
        return _ElementFormatting(strike=True)
    if tag in _INLINE_BASELINE:
        return _ElementFormatting(baseline=_INLINE_BASELINE[tag])
    if tag == _INLINE_MARK:
        return _ElementFormatting(mark=True)
    return _ElementFormatting(code=True)


_MARK_RGB = (1.0, 1.0, 0.0)
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

# The literal whitespace characters a markup pretty-printer/renderer can
# actually emit as structural formatting noise: source indentation (a run of
# spaces/tabs) or a newline between two tags, plus the "\r" half of a "\r\n"
# line ending. Used by _is_formatting_whitespace below (#444) to tell that
# apart from a non-ASCII space character like "\xa0" (the result of decoding
# "&nbsp;"/"&#160;" — HTMLParser's default convert_charrefs=True resolves
# these into plain str.isspace()-true characters before handle_data ever
# sees them, so handle_entityref/handle_charref never fire for ordinary body
# text and can't be used as the signal instead): no renderer or
# hand-formatter has a reason to emit a non-breaking space as indentation,
# so its presence means a human actually typed it. Deliberately excludes
# "\v"/"\f" (vertical tab / form feed) despite both being ASCII and
# str.isspace()-true: no pretty-printer emits either as structural
# whitespace either — the same "nothing legitimate produces this" reasoning
# that justifies treating "\xa0" as authored applies to these too (PR #772
# QA round 1, finding 2), so a resumed segment whose only trailing content
# is a genuinely-typed "\v"/"\f" (e.g. pasted from a terminal) must also
# survive rather than being silently dropped as if it were noise.
_ASCII_FORMATTING_WHITESPACE = " \t\n\r"


def _is_formatting_whitespace(text: str) -> bool:
    """True for a non-empty string made up only of the plain ASCII
    whitespace characters a pretty-printer/renderer would emit as
    structural noise — False for text.strip() == "" text that still
    contains something else (e.g. "&nbsp;"'s decoded "\\xa0", or a stray
    "\\v"/"\\f"), which is real, if invisible, authored content instead
    (#444)."""
    return text != "" and all(c in _ASCII_FORMATTING_WHITESPACE for c in text)


def _without_line_break_edge(text: str, *, leading: bool) -> str:
    """`text` without its leading (or trailing) run of ASCII formatting whitespace, when
    that run holds a line break; unchanged otherwise."""
    stripped = (
        text.lstrip(_ASCII_FORMATTING_WHITESPACE)
        if leading
        else text.rstrip(_ASCII_FORMATTING_WHITESPACE)
    )
    edge = text[: len(text) - len(stripped)] if leading else text[len(stripped) :]
    return stripped if "\n" in edge else text


def _without_trailing_line_break(runs: list[Run | Image]) -> list[Run | Image]:
    """`runs` without whitespace holding a line break at their end, a run left empty
    dropped. For text already flushed into runs by an inline end tag, which
    _AstParser._trim_source_line_break can't reach: `<a href>\\n  link\\n</a>\\n</div>`
    ends in "link\\n" (PR #1400 QA round 1). Returns new Run objects."""
    runs = list(runs)
    while runs and isinstance(runs[-1], Run):
        text = runs[-1].text
        trimmed = _without_line_break_edge(text, leading=False)
        if trimmed == text:
            break
        if trimmed:
            runs[-1] = replace(runs[-1], text=trimmed)
            break
        runs.pop()
    return runs


def _is_resumed_authored_whitespace(resumed: bool, runs: list[Run | Image], raw_text: str) -> bool:
    """True when a resumed block's segment is non-empty and its full,
    unstripped text is whitespace-only per str.strip() but not made up
    solely of _ASCII_FORMATTING_WHITESPACE characters — i.e. it contains
    something like the decoded "\\xa0" from an authored "&nbsp;" that no
    markup pretty-printer/renderer would emit as indentation noise (#444).
    Shared by _emit_block_node and the <pre> close-tag handler's own
    parallel fresh/resumed whitespace check so the two definitions can't
    drift out of sync the way #417 was filed to prevent for block-open
    state (PR #772 QA round 1, finding 3)."""
    return resumed and bool(runs) and not _is_formatting_whitespace(raw_text)


def _strip_formatting_whitespace(runs: list[Run | Image]) -> list[Run | Image]:
    """Remove _ASCII_FORMATTING_WHITESPACE characters from each Run's text
    in a resumed segment being preserved for its genuinely-authored content
    (#444's _is_resumed_authored_whitespace case). Without this, an
    incidental newline sitting next to the authored content — e.g. the
    indentation between a nested list's closing tag and the "&nbsp;" that
    follows it — would still reach the Docs API as literal inserted text:
    the API splits on any "\\n" into a new paragraph regardless of styling
    (#719), producing a spurious extra paragraph for exactly the segment
    this fix was meant to preserve cleanly (PR #772 QA round 1, finding 1).
    Only ever called on a segment already confirmed non-empty and
    whitespace-only-but-authored, so it can never strip a run down to
    nothing without also having something authored left in a sibling run —
    a Run that does strip down to empty is dropped outright, mirroring
    _flush_run's own refusal to create an empty Run. Image entries pass
    through untouched."""
    result: list[Run | Image] = []
    for r in runs:
        if isinstance(r, Image):
            result.append(r)
            continue
        stripped = "".join(c for c in r.text if c not in _ASCII_FORMATTING_WHITESPACE)
        if stripped:
            result.append(replace(r, text=stripped))
    return result


class _LineBreak(str):
    """The break a <br> puts in the run buffer, told apart from source text so trimming
    source whitespace before a block (_interrupt_open_block) never removes it. It's
    "\\v" (#1117, #1091), the line break the Docs API keeps inside one paragraph, like
    Shift+Enter; a "\\n" would start a new paragraph. Inside <pre> it's "\\n", the
    code's own line break, which the emitter turns into "\\v" for the whole block."""


# What an Image stands for in _collapse_soft_breaks' joined text: content, never
# whitespace and never a line break.
_IMAGE_PLACEHOLDER = "￼"


def _soft_break_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each stretch of _ASCII_FORMATTING_WHITESPACE holding a "\\n" in
    `text` (#1093), in order. Each "\\n" is widened over the whitespace on both sides;
    the next search starts where a stretch ends, and a stretch's left edge never moves
    past the content ending the one before, so every character is read a bounded number
    of times (a regex here backtracked quadratically on a long run of spaces, PR #1356
    QA round 1)."""
    spans = []
    pos = text.find("\n")
    while pos != -1:
        start = pos
        while start > 0 and text[start - 1] in _ASCII_FORMATTING_WHITESPACE:
            start -= 1
        end = pos + 1
        while end < len(text) and text[end] in _ASCII_FORMATTING_WHITESPACE:
            end += 1
        spans.append((start, end))
        pos = text.find("\n", end)
    return spans


def _collapse_soft_breaks(runs: list[Run | Image]) -> list[Run | Image]:
    """`runs` with each source line break inside the text written as a browser shows it
    (#1093): the whitespace around it becomes one space, or nothing next to a <br>'s
    "\\v", which already breaks the line. Only ASCII formatting whitespace collapses, so
    an authored "&nbsp;" stays. The stretch's space goes in the run where it starts.

    A stretch at either end of the text is left as it is: whitespace at a block's edges
    is #1229's question, and the trimming rules for a segment's edges (#402, #444,
    #1116) already decide what reaches here. So is <pre> text, whose line breaks are
    the code's, and a table cell's, which is #1221's. Returns new Run objects; the
    caller's are never changed."""
    texts = [r.text if isinstance(r, Run) else _IMAGE_PLACEHOLDER for r in runs]
    joined = "".join(texts)
    if "\n" not in joined:
        return runs
    edits: list[tuple[int, int, str]] = []
    for start, end in _soft_break_spans(joined):
        if start == 0 or end == len(joined):
            continue
        at_line_break = joined[start - 1] == "\v" or joined[end] == "\v"
        edits.append((start, end, "" if at_line_break else " "))
    if not edits:
        return runs
    result: list[Run | Image] = []
    run_start = 0
    # The edits are sorted and don't overlap, so their ends are sorted too: `first` only
    # moves forward, and each run reads only the edits overlapping it (PR #1356 QA round 1).
    first = 0
    for run, text in zip(runs, texts, strict=True):
        run_end = run_start + len(text)
        if isinstance(run, Image):
            result.append(run)
            run_start = run_end
            continue
        while first < len(edits) and edits[first][1] <= run_start:
            first += 1
        pieces = []
        pos = run_start
        i = first
        while i < len(edits) and edits[i][0] < run_end:
            start, end, replacement = edits[i]
            pieces.append(joined[pos : max(start, run_start)])
            if start >= run_start:
                pieces.append(replacement)
            pos = min(end, run_end)
            i += 1
        pieces.append(joined[pos:run_end])
        new_text = "".join(pieces)
        if new_text:
            result.append(replace(run, text=new_text))
        run_start = run_end
    return result


def _has_content(runs: list[Run | Image]) -> bool:
    """True when `runs` hold something a reader sees: an image, text that isn't
    whitespace, or a line break "\\v", which draws a line though str.strip() strips it
    (PR #1356 QA rounds 2 and 3). The one emptiness test every branch of
    _emit_block_node uses. Whitespace-only text, an "&nbsp;" included, isn't content
    here: #402's and #444's rules decide whether such a segment is kept."""
    return any(isinstance(r, Image) or r.text.strip() or "\v" in r.text for r in runs)


def _drop_final_line_break(runs: list[Run | Image]) -> tuple[list[Run | Image], bool]:
    """`runs` without a "\\v" that ends them, ignoring formatting whitespace after it,
    and whether one was dropped. A browser draws no line for a <br> that ends a
    segment's text (at a block's end or right before a nested block), but Docs draws an
    empty line for a paragraph's final "\\v" (PR #1356 QA round 1). A segment left with
    nothing is still a line: _emit_block_node keeps it (round 3). Only one goes: `a<br><br>` keeps one empty line,
    as a browser shows. The whitespace after it is left for #1229. Returns new Run
    objects; the caller's are never changed."""
    for i in range(len(runs) - 1, -1, -1):
        run = runs[i]
        if isinstance(run, Image):
            return runs, False
        content = run.text.rstrip(_ASCII_FORMATTING_WHITESPACE)
        if not content:
            continue
        if not content.endswith("\v"):
            return runs, False
        new_text = content[:-1] + run.text[len(content) :]
        kept = [replace(run, text=new_text)] if new_text else []
        return [*runs[:i], *kept, *runs[i + 1 :]], True
    return runs, False


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
    # The interrupted block's _block_lists: for an <li>, the lists enclosing that item,
    # which a block nested in the item reads through _list_item_fields (#1094).
    lists: tuple[tuple[bool, ...], tuple[int, ...]] = ((), ())
    # The interrupted block's _block_implicit, so a resumed implicit paragraph keeps
    # its source line breaks too.
    implicit: bool = False


def _px_to_pt(value: str) -> float | None:
    """Parse a width attribute value to points. Skips percentages."""
    v = value.strip().lower().rstrip("px")
    try:
        return float(v) * 72 / 96
    except ValueError:
        return None


_CELL_ALIGNMENTS = {
    "left": "START",
    "start": "START",
    "center": "CENTER",
    "right": "END",
    "end": "END",
    "justify": "JUSTIFIED",
    # Vendor values that HTML copied from Chrome, Safari or Firefox (or an email) carries.
    "-webkit-left": "START",
    "-webkit-center": "CENTER",
    "-webkit-right": "END",
    "-moz-left": "START",
    "-moz-center": "CENTER",
    "-moz-right": "END",
}

_IMPORTANT = re.compile(r"!\s*important\s*$")

# How a browser reads an integer attribute (the HTML spec's rules for parsing integers):
# ASCII whitespace, an optional sign, then digits, ignoring what follows them.
_HTML_INTEGER = re.compile(r"[ \t\n\f\r]*([+-]?)([0-9]+)")
# Past int32 a browser ignores the attribute.
_HTML_INTEGER_MAX = 2**31 - 1


def _html_integer(value: str | None) -> int | None:
    """An <ol start> or <li value> as a browser reads it, or None when absent or invalid
    (#1118). Leading zeros don't count toward the size, and the length check keeps
    int() from raising on a number past Python's digit limit."""
    match = _HTML_INTEGER.match(value or "")
    if match is None:
        return None
    digits = match.group(2).lstrip("0") or "0"
    if len(digits) > len(str(_HTML_INTEGER_MAX)):
        return None
    number = int(match.group(1) + digits)
    return number if abs(number) <= _HTML_INTEGER_MAX else None


@dataclass
class _OrderedList:
    """What numbers an <ol>'s items (#1118): its attributes, and each item built so
    far with its <li value>."""

    start: int | None
    reversed: bool
    items: list[tuple[BulletItem, int | None]] = field(default_factory=list)

    def assign_numbers(self) -> None:
        """Give each item the number a browser shows, unless that's 1, 2, 3."""
        step = -1 if self.reversed else 1
        number = self.start
        if number is None:
            number = len(self.items) if self.reversed else 1
        numbers = []
        for _, value in self.items:
            number = number if value is None else value
            numbers.append(number)
            number += step
        if numbers == list(range(1, len(numbers) + 1)):
            return
        for (item, _), item_number in zip(self.items, numbers, strict=True):
            item.number = item_number


_TABLE_SECTIONS = ("thead", "tbody", "tfoot")


def _text_align(attr_dict: dict) -> str | None:
    """An element's own style text-align as a Docs paragraph alignment, or None, resolved
    as CSS does (_css_value): `text-align:right; text-align:bogus` is right, since we
    can only map a valid value."""
    return _css_value(attr_dict, "text-align", _CELL_ALIGNMENTS.get)


def _cell_alignment(attr_dict: dict, *, align_attribute: bool = True) -> str | None:
    """The horizontal alignment an element gives its cells, as a Docs paragraph
    alignment (#1095), or None. Used for a <td>/<th> and for what a cell inherits
    from its <tr>, <thead>/<tbody>/<tfoot> or <table> (_TableBuilder.inherited_alignment).

    Read from its style's text-align (what markdown-it writes for a GFM :--/:-:/--:
    column), else from the legacy align attribute, since CSS overrides a presentational
    attribute. A value we can't map sets nothing and falls through. align_attribute is
    False for <table>, whose align positions the table rather than its text."""
    alignment = _text_align(attr_dict)
    if alignment is None and align_attribute:
        alignment = _CELL_ALIGNMENTS.get((attr_dict.get("align") or "").strip().lower())
    return alignment


def _image_src(attr_dict: dict) -> str:
    """An <img>'s src with surrounding whitespace stripped, as a browser strips a
    URL attribute, or "" when it has none. Stripped here, once, so every consumer
    (ast.image_source_kind, the resolver, the fallback text) sees the same value:
    `src=" https://..."` was classified as a local path (PR #1310 QA round 2)."""
    return (attr_dict.get("src") or "").strip()


def _make_image(attr_dict: dict, src: str, link_url: str | None = None) -> Image:
    """Build an Image node from an <img> tag's attributes. width/height are
    only ever present on raw HTML <img> tags (content_format="html") — plain
    markdown "![alt](src)" has no syntax for them, so they're None there.
    link_url is the enclosing <a href>, if any (markdown "[![alt](src)](url)",
    #977)."""
    return Image(
        src=src,
        alt=attr_dict.get("alt") or None,
        width=_px_to_pt(attr_dict.get("width") or ""),
        height=_px_to_pt(attr_dict.get("height") or ""),
        link_url=link_url,
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
        self._block_implicit = False  # see _open_block
        # True while the last content of the current segment is a <br>: only then does
        # _emit_block_node drop a final "\v", so an authored "\v" character stays
        # (PR #772). Per-segment, reset by _open_block.
        self._ends_with_line_break = False
        # True once the current segment has held a <br>: a segment that did is never
        # discarded, since a browser draws a line for it (PR #1356 QA round 3).
        # Per-segment, reset by _open_block.
        self._segment_had_line_break = False
        # True while the segment about to be flushed is a list item whose text
        # came through its own transparent `<p>` (#1111); makes
        # _flush_pending_runs trim the HTML padding that follows that `</p>`.
        # Per-segment state, so _open_block resets it along with the rest.
        self._li_trailing_padding = False
        # True once some construct inside the current block's current segment
        # (since it was last freshly opened or resumed) was silently dropped
        # instead of contributing a run — an unsupported void element like
        # <img>, an <hr> inside <pre>, or any other unrecognized tag with no text of
        # its own (see the generic inline-element fallthrough below). Reset
        # every time a new segment begins (fresh open or resume) so it always
        # reflects only the segment about to be flushed. This is the signal
        # _emit_block_node's preserve_if_empty is keyed on: an empty flush is
        # worth preserving (#401) exactly when something was actually dropped
        # to produce it, not merely because the segment never had any content
        # to begin with. A fresh <li> doesn't consult it: an item is a bullet
        # even with no content (#1075).
        self._block_had_unsupported_content = False
        self._list_ordered: list[bool] = []  # stack: True=ol, False=ul
        # Each <ol> by list id, numbered once every item is known (#1118).
        self._ordered_lists: dict[int, _OrderedList] = {}
        # The open <li>'s value attribute.
        self._li_value: int | None = None
        # Ids of the open lists, pushed and popped with _list_ordered: each <ol>/<ul>
        # gets a fresh one, so two adjacent lists stay distinguishable (#1241).
        self._list_ids: list[int] = []
        self._list_count = 0
        # The open lists as the current block segment began (_open_block): an <li>
        # left unclosed until </ul> is flushed after the pop, so _make_bullet_item
        # reads this instead of the live stack (#1241).
        self._block_lists: tuple[tuple[bool, ...], tuple[int, ...]] = ((), ())
        # The level of a heading that is a list item's own content ("<li><h1>"), which
        # makes the item a bulleted heading (#1094). Per-segment, like the fields
        # _open_block resets.
        self._li_heading_level: int | None = None
        # The tags of the open item headings, which outlive their segment: a nested
        # block can interrupt the item before the heading's </hN>, which must still be
        # consumed here rather than reach the inline end-tag path and decrement
        # _tag_depth, which its start tag never incremented (PR #1301 QA round 1).
        self._li_heading_tags: list[str] = []
        self._in_pre = False  # inside <pre>; text is literal, runs get font_family

        # Ids of the open <blockquote> tags, outermost first (#476, #1098); its
        # length is the nesting depth. Read directly (via _blockquote_fields) at
        # the moment each leaf node is built, the same way _make_bullet_item
        # reads len(self._list_ordered) fresh rather than threading depth
        # through as a parameter — correct as long as this is only mutated in
        # handle_starttag/handle_endtag's own "blockquote" branches, which
        # bracket exactly the content that's actually inside the tag via the
        # existing _interrupt_open_block/_resume_interrupted_block machinery
        # (the same mechanism table/pre/ol/ul already use). Each <blockquote>
        # gets a fresh id, so two adjacent quotes stay distinguishable.
        self._blockquote_ids: list[int] = []
        self._blockquote_count = 0

        # Depth of open non-block tags (span, b, a, unrecognized tags, ...)
        # that reach the generic inline-element fallthrough below. Lets
        # handle_data tell genuinely bare top-level text (depth 0, e.g. plain
        # "hello world" with no wrapping tag at all — #343) apart from text
        # that's merely wrapped in an inline tag with no block ancestor (e.g.
        # "<span>no blocks</span>", depth 1) — the latter is intentionally
        # dropped (see test_inline_only_html_skips_batchupdate). Counts the open
        # elements with `counted` set, so it falls when an ancestor's end tag
        # closes one left open.
        self._tag_depth = 0

        # The open elements, outermost first (#1391), so an end tag closes the element
        # it names and everything opened inside it, as a browser's does, and an end tag
        # naming nothing open is ignored. _tag_depth, _container_depth and
        # _hidden_depth count flags on these entries. _open_index holds each end-tag
        # key's positions in the stack, and _scope_boundaries the positions of open
        # tables and cells, which an end tag outside the table structure can't close
        # past; both keep a lookup O(1), and every element is pushed and popped once.
        # An inline formatting tag opened with no block around it carries its
        # formatting on its own element (#1404), so the stack ends that style
        # exactly where the element ends.
        self._open_elements: list[_OpenElement] = []
        self._open_index: dict[str, list[int]] = {}
        self._scope_boundaries: list[int] = []
        # Open containers that hold their own text (_OpenElement.container_text).
        self._container_depth = 0
        # Open elements carrying element-recorded formatting (#1404): the count of
        # _open_elements entries with formatting set, so the run flush and the
        # end-tag pre-flush can skip the element walk when none is open (the
        # common case).
        self._bare_formatting_open = 0
        # Open hidden elements (_is_hidden): nothing inside one reaches the Doc.
        self._hidden_depth = 0

        # --- inline formatting stacks ---
        # The block-side state (#1404): what a formatting tag opened inside an open
        # block or table cell bumps, reset at every block boundary by
        # _close_dangling_inline_formatting — the leak guard for a tag left unclosed
        # at a boundary, where a browser would auto-close it. A tag opened with no
        # block around it records on its open element instead (see
        # _ElementFormatting) and is untouched by that reset.
        self._bold_depth = 0
        self._italic_depth = 0
        self._underline_depth = 0
        self._strike_depth = 0
        self._mark_depth = 0
        # One entry per open <sub>/<sup>, innermost last (#1119).
        self._baseline_stack: list[str] = []
        self._code_depth = 0  # inline <code> nesting; ignored inside <pre>
        self._link_url: list[str] = []  # stack of href values
        # href values of <a> tags opened with no block or table cell around them.
        # Read wherever content such an <a> wraps keeps its link (#1404): the bare
        # top-level <img> branch (#977, "<a href><img></a>"), the in-block <img>
        # fallback, and every run _flush_run commits while the anchor is open — a
        # container's paragraph, a <p> of its own, a list item. Kept apart from
        # _link_url, the block-side stack that _close_dangling_inline_formatting
        # clears at block boundaries; bare links stop at table cells, which read
        # _link_url alone (see _bare_formatting).
        self._bare_link_url: list[str] = []
        # One entry per open <a>: which of the two stacks above its start tag
        # pushed an href onto ("block" or "bare"), or None if it pushed nothing
        # (no href, e.g. <a name>). </a> pops only what its own start tag pushed,
        # so an href-less anchor nested in a linked one can't pop the outer
        # link (#994).
        self._anchor_pushes: list[str | None] = []

        # --- current run buffer ---
        self._run_buf: list[str] = []
        self._pending_runs: list[Run | Image] = []

        # --- table context ---
        self._table_depth = 0
        self._table_stack: list[_TableBuilder] = []
        # Line-break whitespace at the end of a table cell's text so far (#1073 QA):
        # see handle_data. Held as runs with the style and link it was typed under,
        # written once more content follows in the same segment of the cell, and
        # dropped if the segment ends first.
        self._cell_held_runs: list[Run] = []
        # Open <pre> tags inside a table cell, whose whitespace is never trimmed.
        self._cell_pre_depth = 0

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

    def _record_bare_formatting(self, formatting: _ElementFormatting) -> None:
        """Record `formatting` on the inline element just opened (#1404): the element
        carries it for as long as it stays open, so the block boundaries a document
        opens inside the tag — each of which flushes runs and resets the live
        per-segment counters — can no longer end the style at the first one. The
        open-element stack ends it instead: the tag's own close pops the element,
        an outer element's close pops everything inside it (#1391), and
        _bare_formatting keeps it out of table cells."""
        self._open_elements[-1].formatting = formatting
        self._bare_formatting_open += 1

    def _bare_formatting(self) -> _ElementFormatting:
        """The union of the formatting recorded on open elements (#1404), for a run
        flushed now: every inline element opened with no block around it that is
        still on the open-element stack contributes. None of it reaches inside a
        table — an element opened outside a cell sits below the cell on the stack,
        and a browser's active formatting stops at the table's structure the same
        way (`<table><tr><b><td>x</td></b></tr></table>` leaves the cell plain, as
        develop's parser does too) — so a table's runs keep reading only what its
        own cells opened, which takes the live counters."""
        if not self._bare_formatting_open or self._table_depth:
            return _NO_FORMATTING
        bold = italic = underline = strike = mark = code = False
        baseline = None
        for element in reversed(self._open_elements):
            formatting = element.formatting
            if formatting is None:
                continue
            bold = bold or formatting.bold
            italic = italic or formatting.italic
            underline = underline or formatting.underline
            strike = strike or formatting.strike
            mark = mark or formatting.mark
            code = code or formatting.code
            if baseline is None:
                baseline = formatting.baseline
        return _ElementFormatting(
            bold=bold,
            italic=italic,
            underline=underline,
            strike=strike,
            mark=mark,
            code=code,
            baseline=baseline,
        )

    def _flush_run(self):
        """Commit buffered text as a Run (if non-empty) to pending_runs."""
        text = "".join(self._run_buf)
        if not text:
            return
        self._run_buf = []
        bare = self._bare_formatting()
        run = Run(
            text=text,
            bold=True if self._bold_depth > 0 or bare.bold else None,
            italic=True if self._italic_depth > 0 or bare.italic else None,
            underline=True if self._underline_depth > 0 or bare.underline else None,
            strikethrough=True if self._strike_depth > 0 or bare.strike else None,
            background_color=RGBColor(*_MARK_RGB) if self._mark_depth > 0 or bare.mark else None,
            baseline_offset=self._baseline_stack[-1] if self._baseline_stack else bare.baseline,
            # An <a> opened with no block or cell around it pushed its href as a
            # bare link (#977); a run flushed while it is still open — the
            # paragraph of a block container it wraps, a <p> of its own, a list
            # item — keeps that link, the way the bare top-level <img> branch and
            # the in-block <img> fallback already do (#1404). Never inside a
            # table: like the element-recorded styles, a bare link stops at table
            # cells (see _bare_formatting).
            link_url=(
                self._link_url[-1]
                if self._link_url
                else self._bare_link_url[-1]
                if self._bare_link_url and self._table_depth == 0
                else None
            ),
            font_family="Courier New"
            if (self._in_pre or self._code_depth > 0 or bare.code)
            else None,
        )
        self._pending_runs.append(run)

    def _flush_pending_runs(self) -> list[Run | Image]:
        self._flush_run()
        runs, self._pending_runs = self._pending_runs, []
        if self._li_trailing_padding:
            # A list item whose text arrived through its own transparent `<p>`
            # (#1111) is followed in the source by the padding between `</p>`
            # and the next tag, which handle_data buffers as the item's own
            # text. Tight items never see it, so trim it here rather than
            # handing `['a', '\n']` to the emitter. _is_formatting_whitespace,
            # not str.strip(): an authored "&nbsp;" is a deliberate spacer and
            # stays (#402's fresh-`<p>` rule, which this item's text still
            # arrives through).
            while runs and isinstance(runs[-1], Run) and _is_formatting_whitespace(runs[-1].text):
                runs.pop()
            # One shot: it describes the padding right after that `</p>`, not
            # every flush for the rest of the document.
            self._li_trailing_padding = False
        return runs

    def _open_block(
        self, tag: str, *, resumed: bool, named_style: str | None, implicit: bool = False
    ):
        """Reset every piece of per-segment block-open state together, in the
        one place all four sites that begin buffering a block's content route
        through: a fresh `_BLOCK_TAGS`/`pre` start tag, `_resume_interrupted_
        block`, and the implicit top-level paragraph opened for bare text
        (#343). Each of these fields used to be hand-duplicated at every
        call site — the actual root cause behind #417: `_block_had_
        unsupported_content` was forgotten at the implicit-paragraph site in
        round 1, then `_block_resumed` was forgotten at the very same site in
        round 2, because nothing forced the two sites' lists to stay in sync.
        Routing every site through this one setter makes omitting a field
        here structurally impossible instead of relying on each call site's
        own manual list matching the others going forward.
        """
        self._block_tag = tag
        self._block_resumed = resumed
        # True for the paragraph opened for bare top-level text (#343). Its source line
        # breaks stay paragraph breaks: text sent with no tags at all is plain lines,
        # not HTML to reflow, and a caller's line structure would vanish silently
        # (PR #1356 QA round 1).
        self._block_implicit = implicit
        self._ends_with_line_break = False
        self._segment_had_line_break = False
        self._block_had_unsupported_content = False
        self._block_named_style = named_style
        self._li_trailing_padding = False
        self._li_heading_level = None
        self._block_lists = (tuple(self._list_ordered), tuple(self._list_ids))
        self._run_buf = []
        self._pending_runs = []

    def _push_element(self, element: _OpenElement) -> None:
        position = len(self._open_elements)
        self._open_elements.append(element)
        self._open_index.setdefault(_end_key(element.tag), []).append(position)
        if element.tag in _TABLE_SCOPE_TAGS:
            self._scope_boundaries.append(position)
        if element.hidden:
            self._hidden_depth += 1

    def _pop_elements(self, tag: str) -> list[_OpenElement] | None:
        """Pop the innermost open element an end tag for `tag` closes, and every element
        opened inside it, innermost first; None, popping nothing, when nothing that tag
        could close is open."""
        positions = self._open_index.get(_end_key(tag))
        if not positions:
            return None
        target = positions[-1]
        if (
            tag not in _TABLE_STRUCTURE_TAGS
            and self._scope_boundaries
            and self._scope_boundaries[-1] > target
        ):
            return None
        popped = []
        while len(self._open_elements) > target:
            element = self._open_elements.pop()
            self._open_index[_end_key(element.tag)].pop()
            if self._scope_boundaries and self._scope_boundaries[-1] == len(self._open_elements):
                self._scope_boundaries.pop()
            if element.hidden:
                self._hidden_depth -= 1
            if element.counted:
                self._tag_depth -= 1
            if element.container_text:
                self._container_depth -= 1
            if element.formatting is not None:
                self._bare_formatting_open -= 1
            popped.append(element)
        return popped

    def _close_implied_table_parts(self, tag: str) -> None:
        """Close the cell (for a <td>/<th>) or row (for a <tr> or table section) open in
        the innermost open table, if any, through the ordinary end-tag path."""
        table = next(
            (
                position
                for position in reversed(self._scope_boundaries)
                if self._open_elements[position].tag == "table"
            ),
            None,
        )
        if table is None:
            return
        for part in ("td", "th") if tag in ("td", "th") else ("tr",):
            positions = self._open_index.get(part)
            if positions and positions[-1] > table:
                self.handle_endtag(part)
                return

    def _can_open_anonymous_block(self) -> bool:
        """True where content with no block of its own gets a paragraph (#1391): directly
        inside a container or a <blockquote>. Unlike the implicit paragraph for bare
        top-level text (#343), its source line breaks are soft breaks: this is HTML, not
        plain lines, and it opens for an inline tag too, not just for text."""
        return (
            self._block_tag is None
            and self._table_depth == 0
            and not self._hidden_depth
            and bool(self._container_depth or self._blockquote_ids)
        )

    def _end_anonymous_block(self, *, implicit_too: bool = False):
        """Emit the paragraph a container's own text opened, if one is open: a container
        boundary ends it, as a block's end tag ends that block (#1391). With
        implicit_too, the paragraph opened for bare top-level text (#343) ends too: a
        container's start tag is a block boundary for it as well."""
        tag = self._block_tag
        if tag is None or (tag != _ANONYMOUS_BLOCK and not (implicit_too and self._block_implicit)):
            return
        self._trim_source_line_break()
        runs = _without_trailing_line_break(self._flush_pending_runs())
        self._emit_block_node(tag, runs)
        self._block_tag = None
        self._block_named_style = None
        self._close_dangling_inline_formatting()

    def _trim_source_line_break(self):
        """Drop whitespace holding a line break from the end of the text not yet flushed,
        since at a block's edge it's source formatting, not content: markdown-it writes
        "<li>a\\n<ul>" for every nested list (#1116), and the "\\n" would reach the Docs
        API as an empty paragraph. Only raw text is trimmed, so a <br>'s own break stays."""
        last_br = max(
            (i for i, piece in enumerate(self._run_buf) if isinstance(piece, _LineBreak)),
            default=-1,
        )
        kept, text = self._run_buf[: last_br + 1], "".join(self._run_buf[last_br + 1 :])
        tail = _without_line_break_edge(text, leading=False)
        self._run_buf = [*kept, tail] if tail else kept

    def _make_bullet_item(self, runs: list[Run | Image]) -> BulletItem:
        # The lists open when this segment began, not now: see _block_lists.
        list_ordered, list_path = self._block_lists
        ordered = list_ordered[-1] if list_ordered else False
        # max(..., 0): an orphan <li> outside any <ul>/<ol> (reachable — "li" is an
        # ordinary _BLOCK_TAGS entry, not gated on an enclosing list) would otherwise
        # compute depth -1 here. Clamped at the source rather than left for every
        # downstream consumer (emitter.py's tab/min_depth math, ast_to_markdown.py's
        # indent math) to independently remember to clamp — #434 QA round 2 found the
        # un-clamped value already needed patching at 3 separate emitter.py call
        # sites, which is exactly the kind of duplication-invites-a-missed-site
        # pattern #417 was filed to close for block-open state.
        depth = max(len(list_ordered) - 1, 0)
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
        item = BulletItem(
            runs=runs,
            depth=depth,
            ordered=ordered,
            checked=checked,
            list_path=list_path,
            heading_level=self._li_heading_level,
            **self._blockquote_fields(),
        )
        ordered_list = self._ordered_lists.get(list_path[-1]) if list_path else None
        if ordered_list is not None:
            ordered_list.items.append((item, self._li_value))
        return item

    def _push_list(self, ordered: bool) -> None:
        self._list_count += 1
        self._list_ordered.append(ordered)
        self._list_ids.append(self._list_count)

    def _blockquote_fields(self) -> dict:
        """blockquote_depth and blockquote_path for a node built now. Every leaf-node
        construction passes these, so a node can't record its depth without the quote
        it's in (#1098)."""
        return {
            "blockquote_depth": len(self._blockquote_ids),
            "blockquote_path": tuple(self._blockquote_ids),
        }

    def _rule_paragraph(self) -> Paragraph:
        """A thematic break built now (#1096), in whatever quote and list item is open."""
        return Paragraph(
            runs=[], rule=True, **self._blockquote_fields(), **self._list_item_fields()
        )

    def _list_item_fields(self) -> dict:
        """list_depth and list_path for a non-item block built now (#1094): the list
        item it sits in, if any. That's the item whose later segment is open (text
        after a nested block, which belongs to the item), else the innermost item a
        nested block interrupted whose lists are the ones open now. An item counts only
        while no list has opened inside it since, so a block in a nested list's own
        items, or loose in that list, isn't taken for content of the outer item. Every
        non-item leaf construction passes these, like _blockquote_fields.

        "Open now" is the ids of the lists open when the block's own segment began
        (_block_lists), not the live stack: a block left open until its list's </ul>
        is flushed after the pop, the same case _make_bullet_item reads _block_lists
        for (#1241). A node built with no block open uses the live stack.

        The walk skips any <li> frame whose lists aren't exactly the open ones rather
        than stopping at it: an item left unclosed inside a nested list
        (`<li>x<p>y</ul>`) leaves its frame on _block_stack after the </ul>, and text
        after that list still belongs to the outer item (PR #1301 QA round 2). Frames
        match by list ids, not depth, so a stale frame from a list that has closed
        never matches a later list at the same depth (PR #1301 QA round 3)."""
        open_ids = self._block_lists[1] if self._block_tag is not None else tuple(self._list_ids)
        if self._block_tag == "li" and self._block_resumed:
            lists = self._block_lists
        else:
            frame = next(
                (
                    f
                    for f in reversed(self._block_stack)
                    if f.outer_tag == "li" and f.lists[1] == open_ids
                ),
                None,
            )
            if frame is None:
                return {}
            lists = frame.lists
        ordered, path = lists
        if not ordered or path != open_ids:
            return {}
        return {"list_depth": len(ordered) - 1, "list_path": path}

    def _close_dangling_inline_formatting(self):
        """A block boundary is starting while inline formatting tags may still
        be open (e.g. an unclosed <b> before a nested list/table/pre/etc). Real
        HTML doesn't allow block content inside a true inline element — a
        browser would auto-close it here — so treat the boundary as an implicit
        close for all inline state. Otherwise formatting silently leaks into
        every node for the rest of the document, since the tag that would have
        decremented these depths never arrives.

        Only the block-side counters and the block-side link stack end here
        (#1404). The formatting a tag opened with no block around it records on
        its open element deliberately survives this reset: that tag wraps the
        boundary rather than sitting inside it, and the element ends it — at its
        own close, or an outer element's close — instead of the boundary ending
        it. That is what keeps a tag wrapping several blocks working.
        """
        self._bold_depth = 0
        self._italic_depth = 0
        self._underline_depth = 0
        self._strike_depth = 0
        self._mark_depth = 0
        self._baseline_stack = []
        self._code_depth = 0
        self._link_url = []
        # The cleared hrefs' anchors no longer own an entry to pop.
        self._anchor_pushes = [
            None if pushed == "block" else pushed for pushed in self._anchor_pushes
        ]

    def _close_baseline(self, offset: str):
        """Pop the innermost open <sub>/<sup> of this kind (#1119).

        A close with no open tag of its kind pops nothing, as `<s>`'s depth never
        goes below 0, so `<sup>a</sub>b` keeps "b" superscript.
        """
        for i in range(len(self._baseline_stack) - 1, -1, -1):
            if self._baseline_stack[i] == offset:
                del self._baseline_stack[i]
                return

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
        void element like <img>, or an <hr> inside <pre>), emitting it as an empty
        node (runs=[]) so its paragraph boundary survives (#401), instead of
        vanishing outright. An empty result that *isn't* due to dropped
        content — e.g. a resumed segment's formatting newline — leaves this
        False and emits nothing, since there's no boundary to lose.

        A fresh `<li>` takes none of the rules below: it always emits its
        BulletItem, first and on its own, with runs=[] when it has no text
        (#1075), since an item shows a marker however little it holds
        (`<li></li>`, a Markdown bare `-`; `<li>&nbsp;</li>`; an `<li>` whose
        content starts with a nested list or block). preserve_if_empty and the
        whitespace rules apply only to every other block, and to a resumed
        `<li>` segment, which is a Paragraph inside the item (#1094).

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
        invisible) content here to lose, not just a boundary. A heading
        keeps the pre-#402 behavior of always dropping whitespace-only text —
        PR #441's own QA round live-caught a first version of this fix that
        wasn't scoped to `<p>` at all, producing a stray heading with only
        invisible content for `<h1>&nbsp;</h1>` between two real siblings,
        which isn't the blank-line-spacer convention this fix is for. (It
        dropped `<li>&nbsp;</li>` the same way until #1075 made every fresh
        `<li>` a bullet; the item keeps its marker but not the `&nbsp;`.) A *resumed* `<p>`'s whitespace-only trailing flush is a
        different animal too, and must NOT get the fresh-`<p>` treatment
        either: it's markup-formatting noise (e.g. the indentation newline
        between a nested list's `</ul>` and the outer `<li>`'s own `</li>`),
        not authored content — confirmed live via
        test_nested_list_via_markdown_preserves_parent_text, where treating
        it as #402 content injected a spurious extra list item for that
        stray "\n". Both the non-`<p>` and resumed-`<p>` cases fall back to
        the same preserve_if_empty gate the runs=[] case already uses (a
        real drop elsewhere in the same segment still earns a boundary
        node; an ordinary formatting artifact doesn't) — *unless* the
        resumed segment's whitespace-only text contains a character
        `_is_formatting_whitespace` doesn't recognize as ordinary ASCII
        formatting whitespace (#444) — e.g. the "\xa0" a decoded "&nbsp;"
        becomes (HTMLParser's default convert_charrefs=True resolves
        "&nbsp;"/"&#160;" into that plain character before handle_data ever
        sees it, so handle_entityref/handle_charref never fire for this and
        can't be used as the signal instead). A markup-formatting artifact
        (like the stray "\n" above) is always plain ASCII whitespace
        produced by a parser/pretty-printer — a non-breaking space or other
        non-ASCII space character has no reason to appear there, so a
        resumed segment that's whitespace-only *because of* one (e.g. an
        explicit "&nbsp;" placed right after a nested list/table/pre, still
        inside the same tag) can only be something a human actually typed —
        real, if invisible, content to lose, the same rationale the
        fresh-`<p>` case above already rests on. This deliberately does NOT
        extend to a *fresh* heading whose only content is such a character
        (e.g. `<h1>&nbsp;</h1>` between two real siblings): that's the PR #441
        regression above, and the signal doesn't rescue it, since the problem
        there isn't ambiguity about who produced the character — it's that
        headings have no blank-line-spacer convention to begin with. Emitter.py's
        ast_to_requests() no longer special-cases this text at all — it
        emits whatever text a kept node carries, whitespace or not.

        An Image (#333) counts as real content the same way non-whitespace
        text does: a node whose runs are e.g. just [Image(...)], with no
        Run at all, must never hit the empty-drop path below just because
        joining its (nonexistent) Run text yields "".
        """
        # Something dropped in a container's own text is no paragraph to keep: the
        # container's boundary is there without it (<div><span></span></div>).
        if tag == _ANONYMOUS_BLOCK:
            preserve_if_empty = False
        # Line breaks (#1230). A <pre> interrupted by a nested block lands here too; its
        # text is literal. Bare top-level text keeps its source line breaks (_open_block).
        if tag != "pre":
            if not self._block_implicit:
                runs = _collapse_soft_breaks(runs)
            if self._ends_with_line_break:
                runs, _ = _drop_final_line_break(runs)
        raw_text = "".join(r.text for r in runs if isinstance(r, Run))
        has_image = any(isinstance(r, Image) for r in runs)
        if tag != "pre" and self._segment_had_line_break and not has_image:
            if all(c in _ASCII_FORMATTING_WHITESPACE for c in raw_text):
                # A segment that held only a <br> (its final "\v" dropped above) is one
                # empty line in a browser, whatever its tag and whether it's fresh or
                # resumed: `<p><br></p>`, `<li>a<ul>…</ul><br></li>`, `<h2><br></h2>`.
                # Its whitespace goes with it (PR #1356 QA rounds 2 and 3).
                runs = []
                preserve_if_empty = True
            elif all(c in _ASCII_FORMATTING_WHITESPACE or c == "\v" for c in raw_text):
                # Only line breaks left (`<br><br>`): the formatting whitespace around
                # them is source layout, not text.
                runs = _strip_formatting_whitespace(runs)
        if tag == "li" and not self._block_resumed:
            # A list item is a bullet whatever it holds (#1075): `<li></li>` (a
            # Markdown bare `-`), an item holding only whitespace or `&nbsp;`, and an
            # item whose content starts with a nested list or block, all of which
            # show a marker in a browser. Its whitespace is padding, not text.
            if not _has_content(runs):
                runs = []
            self._nodes.append(self._make_bullet_item(runs))
            return
        if not _has_content(runs):
            is_fresh_paragraph_whitespace = tag == "p" and bool(runs) and not self._block_resumed
            # A container's "&nbsp;" draws a line and its source indentation doesn't,
            # the same test a resumed segment needs (<div>&nbsp;</div>, #1391).
            is_resumed_authored_whitespace = _is_resumed_authored_whitespace(
                self._block_resumed or tag == _ANONYMOUS_BLOCK, runs, raw_text
            )
            if is_resumed_authored_whitespace:
                runs = _strip_formatting_whitespace(runs)
            if (
                not is_fresh_paragraph_whitespace
                and not is_resumed_authored_whitespace
                and not preserve_if_empty
            ):
                return
        if tag in _HEADING_TAGS:
            level = int(tag[1])
            self._nodes.append(
                Heading(
                    level=level,
                    runs=runs,
                    **self._blockquote_fields(),
                    **self._list_item_fields(),
                )
            )
        elif tag == "p" and self._block_named_style:
            self._nodes.append(
                NamedBlock(
                    style_type=self._block_named_style,
                    runs=runs,
                    **self._blockquote_fields(),
                    **self._list_item_fields(),
                )
            )
        else:
            # A resumed <li> segment lands here too: text after a block nested in the
            # item is more of that item's content, not a new item (#1094).
            self._nodes.append(
                Paragraph(runs=runs, **self._blockquote_fields(), **self._list_item_fields())
            )

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
        if self._run_buf and not self._in_pre:
            self._trim_source_line_break()
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
                lists=self._block_lists,
                implicit=self._block_implicit,
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
        # A container's or quote's own paragraph ends with its line-break trim and
        # inline state reset, whichever end tag closes it (PR #1400 QA round 1).
        self._end_anonymous_block()
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
        self._open_block(
            frame.outer_tag, resumed=True, named_style=frame.named_style, implicit=frame.implicit
        )

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        tag = _PRE_ALIASES.get(tag, tag)
        attr_dict = dict(attrs)

        # --- open-element stack (#1391) ---
        # A hidden element, and everything inside one, is tracked and nothing else: no
        # node, no image, no empty block or table, and no #401 boundary.
        hidden = _is_hidden(tag, attr_dict)
        if self._hidden_depth or hidden:
            if tag not in _VOID_TAGS:
                self._push_element(_OpenElement(tag, inert=True, hidden=hidden))
            return
        # A cell or row start tag closes the cell or row open in the same table first,
        # as a browser's implied end tags do: <td>a<td>b is two cells, and
        # <tr><td>a<tr><td>b two rows (PR #1400 QA round 2).
        if tag in ("td", "th", "tr", "thead", "tbody", "tfoot"):
            self._close_implied_table_parts(tag)
        if tag not in _VOID_TAGS:
            self._push_element(_OpenElement(tag))

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
                self._cell_held_runs = []
            self._table_depth += 1
            self._table_stack.append(
                _TableBuilder(alignment=_cell_alignment(attr_dict, align_attribute=False))
            )
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
                tb.start_row(alignment=_cell_alignment(attr_dict))
                return
            if tag in _TABLE_SECTIONS:
                # Recorded for its cells only; the tag still takes the generic
                # unrecognized-tag path below, as it did before #1095.
                tb.section_alignment = _cell_alignment(attr_dict)
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
                    colspan=colspan,
                    rowspan=rowspan,
                    is_header=is_header,
                    width_pt=width_pt,
                    alignment=_cell_alignment(attr_dict) or tb.inherited_alignment(),
                )
                self._cell_held_runs = []
                self._cell_pre_depth = 0
                # If it's a header cell, pre-activate bold
                if is_header:
                    self._bold_depth += 1
                return

        # --- list context ---
        if tag == "ol":
            self._interrupt_open_block("ol")
            self._push_list(True)
            self._ordered_lists[self._list_count] = _OrderedList(
                _html_integer(attr_dict.get("start")), "reversed" in attr_dict
            )
            return
        if tag == "ul":
            self._interrupt_open_block("ul")
            self._push_list(False)
            return

        # --- blockquote (#476) ---
        # Interrupts any open block the same way ol/ul/table/pre already do,
        # flushing the outer block's own buffered text (at the pre-increment
        # depth — that text is not inside this blockquote) before entering.
        # Depth increments after the interrupt so nested content — including a
        # further nested <blockquote> — reads the correct depth via
        # _emit_block_node's _blockquote_fields lookup.
        if tag == "blockquote":
            self._interrupt_open_block("blockquote")
            self._blockquote_count += 1
            self._blockquote_ids.append(self._blockquote_count)
            return

        # --- pre / code block ---
        if tag == "pre" and self._table_depth == 0:
            self._interrupt_open_block("pre")
            self._open_block("pre", resumed=False, named_style=None)
            self._in_pre = True
            return

        # --- block elements ---
        if tag in _BLOCK_TAGS and self._table_depth == 0:
            named_style = None
            if tag == "p":
                style = (attr_dict.get("data-style") or "").lower()
                named_style = _NAMED_BLOCK_STYLES.get(style)
            # A `<p>` opening as a list item's own wrapper *is* that item's
            # content, not a sibling block (#1111). Interrupting would flush the
            # still-empty `<li>` — no runs, so no bullet emitted at all — and
            # then emit the text as a plain Paragraph, which is how every
            # *loose* Markdown list lost its bullets: python-markdown wraps each
            # loose item's text in `<p>`, so any blank line between items hits
            # this. Only the item's first paragraph stays transparent; a second
            # one interrupts, and becomes a block inside the item (#1094). So does
            # any `<p>` once the `<li>` has resumed after a nested list, quote,
            # code block or paragraph: joining the resumed item would emit it as
            # a new bullet, or a new number in an ordered list. A
            # `data-style` paragraph owns a NamedBlock identity, so it keeps
            # interrupting too.
            li_padding = "".join(self._run_buf)
            if (
                tag == "p"
                and named_style is None
                and self._block_tag == "li"
                and not self._block_resumed
                and not self._pending_runs
                and (li_padding == "" or _is_formatting_whitespace(li_padding))
            ):
                # Drops the `<li>`-to-`<p>` padding that would otherwise be
                # buffered as the item's own leading text.
                self._run_buf = []
                return
            # A heading that opens a list item ("- # Title") is the item's own text,
            # in that heading's style (#1094): the item becomes a bulleted heading
            # rather than an empty item followed by an unlisted Heading. Same
            # conditions as the transparent `<p>` above; a heading after the item's
            # text stays a block inside the item.
            if (
                tag in _HEADING_TAGS
                and self._block_tag == "li"
                and not self._block_resumed
                and not self._pending_runs
                and self._li_heading_level is None
                and (li_padding == "" or _is_formatting_whitespace(li_padding))
            ):
                self._run_buf = []
                self._li_heading_level = int(tag[1])
                self._li_heading_tags.append(tag)
                return
            self._interrupt_open_block(tag)
            self._open_block(tag, resumed=False, named_style=named_style)
            if tag == "li":
                self._li_value = _html_integer(attr_dict.get("value"))
            return

        # --- block container with no node of its own (#1391) ---
        # One inside an open block stays an unrecognized tag there, whose text the
        # block already keeps.
        if tag in _CONTAINER_TAGS and self._table_depth == 0:
            self._end_anonymous_block(implicit_too=True)
            if self._block_tag is None:
                self._open_elements[-1].container_text = True
                self._container_depth += 1
                return

        # --- thematic break (<hr>) with no open block ---
        # Unlike <img>, which markdown always wraps in a <p> (so an unsupported
        # image already reaches _emit_block_node's runs=[] handling above),
        # the Markdown parser emits "---"/"___" thematic breaks as a bare <hr />
        # sibling with no wrapping tag at all — it never opens a block, so it
        # would otherwise vanish with zero trace, collapsing the paragraph
        # boundary between the surrounding content (#401). It's a rule paragraph,
        # which the emitter draws as a horizontal line (#1096). Scoped to <hr>
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
            self._nodes.append(self._rule_paragraph())
            return
        # An <hr> in an open block is a block of its own, as a browser shows it: end
        # the outer block's segment, emit the rule, then resume the outer block. That
        # covers a rule after text (markdown-it's "<li>item\n<hr />\n</li>" for a rule
        # in a list item, #1116; without this the rule vanished and the newlines around
        # it became empty paragraphs), in a resumed segment after a nested list, quote
        # or paragraph in the item ("- a\n  - b\n  ---"), and in a fresh <li> with no
        # text ("<li><hr>", Markdown "-" then "  ---"): the item is an empty bullet
        # either way (#1075), so the rule is a block inside it, like a <pre> or
        # <blockquote> there. A fresh block with no text before the rule ("<p><hr>")
        # emits nothing for its empty first segment, so it's the rule alone (#1096);
        # before rules were drawn, it was a dropped construct keeping a boundary (#401).
        if (
            tag == "hr"
            and self._block_tag is not None
            and self._table_depth == 0
            and self._tag_depth == 0
            and not self._in_pre
        ):
            self._interrupt_open_block("hr")
            self._nodes.append(self._rule_paragraph())
            self._resume_interrupted_block("hr")
            return

        # --- bare top-level <img> with no open block (#333) ---
        # Same rationale as <hr> just above: markdown's own "![]()" syntax
        # always renders wrapped in a <p>, so this only matters for raw HTML
        # (content_format="html") supplying a top-level <img> with no
        # wrapping block at all. Unlike <hr> and bare text, an <img> wrapped
        # only in inline tags still gets its implicit paragraph: a raw-HTML
        # "<a href><img></a>" (a linked badge, say) is real content, and
        # dropping it loses the image along with its link (PR #992 QA round 1).
        # Directly in a container it opens the container's own paragraph instead, so
        # text after it joins it, as text before it would (PR #1400 QA round 1).
        if tag == "img" and _image_src(attr_dict) and self._can_open_anonymous_block():
            self._open_block(_ANONYMOUS_BLOCK, resumed=False, named_style=None)
        if tag == "img" and self._block_tag is None and self._table_depth == 0:
            src = _image_src(attr_dict)
            if src:
                link_url = self._bare_link_url[-1] if self._bare_link_url else None
                self._nodes.append(
                    Paragraph(
                        runs=[_make_image(attr_dict, src, link_url)],
                        **self._blockquote_fields(),
                        **self._list_item_fields(),
                    )
                )
                return
            # No src — nothing to embed; fall through to the generic
            # unrecognized-tag handling below (a no-op at depth 0).

        # --- inline elements / unrecognized tags ---
        if tag not in _VOID_TAGS:
            self._tag_depth += 1
            self._open_elements[-1].counted = True
        if (tag not in _VOID_TAGS or tag == "br") and self._can_open_anonymous_block():
            # Opened before the tag's own handling below, so <div><b>x</b></div> is bold.
            self._open_block(_ANONYMOUS_BLOCK, resumed=False, named_style=None)
        in_cell = (
            self._table_depth >= 1 and bool(self._table_stack) and self._table_stack[-1].in_cell
        )
        # A formatting tag or <a> opened with no block of its own around it records
        # its formatting on its open element (#1404) instead of the live depth
        # counters: those are per-segment state that every block boundary resets
        # (_close_dangling_inline_formatting), which ended the style at the first
        # block inside the tag — <b><div>l1</div><div>l2</div></b> styled only l1.
        # On the element, the style ends where the element does: at its own close,
        # at an outer element's close (#1391), and — like a browser's active
        # formatting markers, and like develop — never inside table cells, which
        # _bare_formatting keeps the element-recorded style out of entirely. "No
        # block of its own" is the top level and a table's non-cell structure,
        # plus the implicit paragraph bare top-level text opens (#343): that
        # paragraph is the parser's own construct, so in the source HTML
        # "Intro <b><div>x</div></b>" has the <b> with no block around it. A real
        # block or a cell around the tag keeps the counters, whose boundary reset
        # stays the leak guard for a tag left unclosed inside a block, where a
        # browser would auto-close it
        # (test_unclosed_bold_does_not_leak_past_nested_list).
        bare_side = not in_cell and (self._block_tag is None or self._block_implicit)
        if self._block_tag or in_cell:
            self._release_cell_whitespace()
            self._flush_run()
            if bare_side and tag in _INLINE_FORMATTING_TAGS:
                self._record_bare_formatting(_formatting_of(tag))
            elif tag in _INLINE_BOLD:
                self._bold_depth += 1
            elif tag in _INLINE_ITALIC:
                self._italic_depth += 1
            elif tag in _INLINE_UNDERLINE:
                self._underline_depth += 1
            elif tag in _INLINE_STRIKE:
                self._strike_depth += 1
            elif tag in _INLINE_BASELINE:
                self._baseline_stack.append(_INLINE_BASELINE[tag])
            elif tag == _INLINE_MARK:
                self._mark_depth += 1
            elif tag == "a":
                href = attr_dict.get("href", "")
                if href:
                    (self._bare_link_url if bare_side else self._link_url).append(href)
                self._anchor_pushes.append(("bare" if bare_side else "block") if href else None)
            elif tag == "code" and not self._in_pre:
                self._code_depth += 1
            elif tag == "pre":
                # Only reachable in a table cell: a body <pre> is handled above.
                self._cell_pre_depth += 1
            elif tag == "br":
                in_pre = self._in_pre or self._cell_pre_depth > 0
                self._run_buf.append(_LineBreak("\n" if in_pre else "\v"))
                self._ends_with_line_break = True
                self._segment_had_line_break = True
            elif tag == "img" and not self._in_pre:
                # In an open block (#333) or a table cell (#1073), where it joins the
                # cell's children in source order; never inside <pre>, where an
                # embedded image makes no sense.
                src = _image_src(attr_dict)
                if src:
                    link_url = self._link_url[-1] if self._link_url else None
                    if link_url is None and self._block_tag is not None and self._table_depth == 0:
                        # An <a> around the block, which opened with no block around
                        # it, pushed its href as a bare link (#977), which a bare
                        # top-level <img> reads; an image in any block it wraps keeps
                        # it the same way — the container's own paragraph (PR #1400 QA
                        # round 2), a <p> of its own (#1404 review), a list item.
                        # Never inside a table: bare links stop at table cells, like
                        # the element-recorded styles (see _bare_formatting).
                        link_url = self._bare_link_url[-1] if self._bare_link_url else None
                    self._pending_runs.append(_make_image(attr_dict, src, link_url))
                    self._ends_with_line_break = False
                elif self._block_tag:
                    self._block_had_unsupported_content = True
            elif self._block_tag:
                # Anything else reaching this fallthrough (an <hr> inside <pre>
                # or an inline tag, an <img> inside <pre>, or any
                # other tag this parser doesn't specially recognize) is
                # silently dropped rather than contributing a run — see
                # self._block_had_unsupported_content.
                self._block_had_unsupported_content = True
        elif tag == "a":
            href = attr_dict.get("href", "") if self._table_depth == 0 else ""
            if href:
                self._bare_link_url.append(href)
            self._anchor_pushes.append("bare" if href else None)
        elif tag in _INLINE_FORMATTING_TAGS:
            # The true-bare counterpart of the branch above: nothing records on the
            # live counters here, since the block boundaries inside the tag would
            # reset them (#1404). The element does the scoping instead: a stray
            # close names nothing open and is ignored, and an unclosed tag ends
            # with the outer element that contains it (#1391), so nothing leaks
            # past the element's own scope. Text with no block of its own at all
            # still stays dropped (#343), since nothing flushes outside a block.
            self._record_bare_formatting(_formatting_of(tag))

    def handle_endtag(self, tag):
        tag = _PRE_ALIASES.get(tag, tag)
        # Text still buffered when a close tag arrives was typed inside the elements
        # that close is about to pop, so it must keep the formatting they record
        # (#1404): flush it while they are all still on the stack, before
        # _pop_elements removes them — the flushes the close paths run below happen
        # after the pop. Only the element-recorded side needs this; the live counters
        # a guarded inline tag bumps don't change at pop time, so with no bare
        # formatting element open the buffer keeps flushing exactly where it does
        # today.
        if self._run_buf and self._bare_formatting_open:
            self._flush_run()
        # An end tag closes the element it names and everything still open inside it,
        # innermost first, as a browser's does (#1391): an unclosed <b>, hidden <video>,
        # <p> or list ends with its container or cell. One naming nothing open is
        # ignored. The element it names closes under the end tag's own name, so a
        # </ul> closing an <ol> still reaches the list handling as </ul>.
        popped = self._pop_elements(tag)
        if popped is None:
            return
        for element in popped[:-1]:
            if not element.inert:
                self._close_element(element.tag, element)
        if not popped[-1].inert:
            self._close_element(tag, popped[-1])

    def _close_element(self, tag: str, element: _OpenElement):
        """Everything an element's end tag does once the stack has popped it."""
        # --- block container with no node of its own (#1391) ---
        if element.container_text:
            self._end_anonymous_block()
            return
        # --- table structure ---
        if tag == "table":
            # A cell left open has no </td> to drop what it held.
            self._cell_held_runs = []
            if self._table_stack:
                tb = self._table_stack.pop()
                node = tb.build()
                if node is not None:
                    if self._table_depth == 1:
                        for name, value in {
                            **self._blockquote_fields(),
                            **self._list_item_fields(),
                        }.items():
                            setattr(node, name, value)
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
            if tag in _TABLE_SECTIONS:
                tb.section_alignment = None  # then the generic path, as at the start tag
            if tag in ("td", "th"):
                is_header = tag == "th"
                runs = self._flush_pending_runs()
                self._cell_held_runs = []
                self._cell_pre_depth = 0
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
        if tag in ("ol", "ul"):
            if self._list_ordered:
                self._list_ordered.pop()
                self._list_ids.pop()
            self._resume_interrupted_block(tag)
            return

        # --- blockquote (#476) ---
        # Resume before decrementing depth: if a block was left open right up
        # to this close tag (e.g. malformed HTML missing its own inner close
        # tag), _resume_interrupted_block's own pre-resume flush must still
        # see this content as inside the blockquote (depth not yet
        # decremented) — mirroring how _emit_block_node reads
        # the open blockquotes fresh at flush time everywhere else.
        if tag == "blockquote":
            self._resume_interrupted_block("blockquote")
            if self._blockquote_ids:
                self._blockquote_ids.pop()
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
            # all in the resulting doc (QA round 1, PR #515). And, mirroring
            # _emit_block_node's own #444 fix: a resumed <pre> whose trailing
            # flush is whitespace-only but contains a character
            # _is_formatting_whitespace doesn't recognize as ordinary ASCII
            # formatting whitespace (e.g. the "\xa0" a decoded "&nbsp;"
            # becomes) is still genuinely-authored content, not the
            # markup-formatting noise this whole check exists to filter out
            # of the resumed case — an indentation artifact between a
            # nested table's close tag and this <pre>'s own close tag is
            # always plain ASCII whitespace. As in _emit_block_node, the
            # preserved runs are then stripped of that formatting whitespace
            # (PR #772 QA round 1, finding 1) — but only when this segment
            # is whitespace-only to begin with (`not text.strip()`): a
            # resumed <pre> can also carry genuine multi-line content of its
            # own (is_resumed_authored_whitespace is True there too, since
            # real text isn't all-formatting-whitespace either), and that
            # content's own newlines are real, significant <pre> text, not
            # noise to strip — they're handled separately at write time via
            # the Courier-New "\n"→"\v" substitution (#719), same as any
            # other code paragraph.
            text = "".join(r.text for r in runs if isinstance(r, Run))
            is_fresh_pre_whitespace = not self._block_resumed and bool(runs)
            is_resumed_authored_whitespace = _is_resumed_authored_whitespace(
                self._block_resumed, runs, text
            )
            if not text.strip() and is_resumed_authored_whitespace:
                runs = _strip_formatting_whitespace(runs)
            if (
                text.strip()
                or is_fresh_pre_whitespace
                or is_resumed_authored_whitespace
                or self._block_had_unsupported_content
            ):
                self._nodes.append(
                    Paragraph(runs=runs, **self._blockquote_fields(), **self._list_item_fields())
                )
            self._block_tag = None
            self._in_pre = False
            self._resume_interrupted_block("pre")
            return

        # --- heading that is a list item's own text (#1094) ---
        # The item ends with its heading: anything after it in the <li> is a block
        # inside the item, so the item is emitted here and its later segment resumed.
        # If a nested block interrupted the item first, the item was emitted then, and
        # this end tag only closes the heading. A heading opened as a block of its own
        # (self._block_tag == tag) closes through the block-element branch below.
        if (
            tag in _HEADING_TAGS
            and self._table_depth == 0
            and self._li_heading_tags
            and self._li_heading_tags[-1] == tag
            and self._block_tag != tag
        ):
            self._li_heading_tags.pop()
            if self._block_tag == "li" and self._li_heading_level == int(tag[1]):
                runs = self._flush_pending_runs()
                self._emit_block_node(
                    "li", runs, preserve_if_empty=self._block_had_unsupported_content
                )
                self._open_block("li", resumed=True, named_style=None)
            return

        # --- transparent paragraph inside a list item (#1111) ---
        # Its start tag opened no block of its own, so there is nothing here to
        # emit: the item's `</li>` builds the BulletItem from the runs collected
        # in the meantime. Flushing at this boundary keeps the paragraph's text,
        # and arming the trim makes the `</p>`-to-next-tag padding that
        # handle_data buffers next land outside the item's runs.
        if tag == "p" and self._block_tag == "li" and self._table_depth == 0:
            self._flush_run()
            self._li_trailing_padding = True
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
        # _pop_elements already took a counted element out of _tag_depth.
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
            elif tag in _INLINE_BASELINE:
                self._close_baseline(_INLINE_BASELINE[tag])
            elif tag == _INLINE_MARK:
                self._mark_depth = max(0, self._mark_depth - 1)
            elif tag == "a":
                self._close_anchor()
            elif tag == "code" and not self._in_pre:
                self._code_depth = max(0, self._code_depth - 1)
            elif tag == "pre":
                self._cell_pre_depth = max(0, self._cell_pre_depth - 1)
        elif tag == "a":
            self._close_anchor()
        # A formatting tag's bare-side close needs no branch of its own (#1404):
        # _pop_elements already took its element — with its recorded formatting —
        # off the stack, and any text it still held flushed before the pop, in
        # handle_endtag. A stray close naming nothing open never reaches here.

    def _release_cell_whitespace(self):
        """Write held cell whitespace (see handle_data) ahead of the content about to
        be added, as the runs it was held as."""
        if self._cell_held_runs:
            self._flush_run()
            self._pending_runs.extend(self._cell_held_runs)
            self._cell_held_runs = []

    def _hold_cell_whitespace(self, text: str):
        """Hold `text` as a run with the current style and link (see handle_data)."""
        self._flush_run()
        self._run_buf.append(text)
        self._flush_run()
        held = self._pending_runs.pop()
        assert isinstance(held, Run)  # _flush_run just made it from non-empty text
        self._cell_held_runs.append(held)

    def _close_anchor(self):
        """Pop whatever href the matching <a> start tag pushed, and nothing
        else (#994)."""
        if not self._anchor_pushes:
            return
        pushed = self._anchor_pushes.pop()
        if pushed == "block" and self._link_url:
            self._link_url.pop()
        elif pushed == "bare" and self._bare_link_url:
            self._bare_link_url.pop()

    def handle_data(self, data):
        if self._hidden_depth:
            return
        # An "&nbsp;" draws a line in a container, as source indentation doesn't.
        if data and not _is_formatting_whitespace(data) and self._can_open_anonymous_block():
            self._open_block(_ANONYMOUS_BLOCK, resumed=False, named_style=None)
        # Table-cell text and open-block text are independent triggers that happen
        # to be buffered the same way today; kept as separate branches so either
        # can diverge without first untangling a merged condition (#638).
        if self._table_depth >= 1 and self._table_stack and self._table_stack[-1].in_cell:
            if self._cell_pre_depth:
                self._release_cell_whitespace()
                self._run_buf.append(data)
                return
            # Whitespace holding a line break at a segment's edge (the cell's start or
            # end, or either side of a nested table, as in "<td>\n  Intro\n  <table>")
            # became empty paragraphs in the cell (#1073 QA). At the segment's start it
            # is dropped. At the end of the text so far it is held, and written as-is,
            # with its own style and link, only if more content follows; so everything
            # else in a cell parses as before (#1221 is the general question).
            if not (self._run_buf or self._pending_runs):
                data = _without_line_break_edge(data, leading=True)
            text = _without_line_break_edge(data, leading=False)
            if text:
                self._release_cell_whitespace()
                self._run_buf.append(text)
            if len(text) < len(data):
                self._hold_cell_whitespace(data[len(text) :])
        elif self._block_tag:
            # Never in <pre>, where the line break and indentation are the code's.
            if (
                (self._block_resumed or self._block_tag == _ANONYMOUS_BLOCK)
                and not self._in_pre
                and not (self._run_buf or self._pending_runs)
            ):
                # A resumed segment starts right after the block that interrupted it,
                # and markdown-it writes a line break there ("<hr />\nmore"), as a
                # container's source does before its text ("<div>\n  text"). Source
                # formatting, like the break before the block (_interrupt_open_block);
                # an authored "&nbsp;" is not ASCII whitespace and stays (#444).
                data = _without_line_break_edge(data, leading=True)
                if not data:
                    return
            if self._block_implicit and self._ends_with_line_break:
                head, newline, _ = data.partition("\n")
                if newline and all(c in _ASCII_FORMATTING_WHITESPACE for c in head):
                    # Bare text keeps its source line breaks as paragraph breaks, so a
                    # <br> right before one ends a paragraph, where it draws no line
                    # (_drop_final_line_break; PR #1356 QA round 2).
                    self._flush_run()
                    self._pending_runs, _ = _drop_final_line_break(self._pending_runs)
                    self._ends_with_line_break = False
            if not all(c in _ASCII_FORMATTING_WHITESPACE for c in data):
                self._ends_with_line_break = False
            self._run_buf.append(data)
        elif self._table_depth == 0 and self._tag_depth == 0 and data.strip():
            # Genuinely bare text — no wrapping block tag, no enclosing tag of
            # any kind (#343). Implicitly open a paragraph so it isn't
            # silently dropped the way inline-only content
            # (e.g. "<span>no blocks</span>") intentionally is.
            self._open_block("p", resumed=False, named_style=None, implicit=True)
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
        self._end_anonymous_block()
        if self._block_tag is not None:
            runs = self._flush_pending_runs()
            self._emit_block_node(
                self._block_tag, runs, preserve_if_empty=self._block_had_unsupported_content
            )
            self._block_tag = None
            self._block_named_style = None
        for ordered_list in self._ordered_lists.values():
            ordered_list.assign_numbers()


class _TableBuilder:
    """Accumulates rows/cells while parsing a <table>."""

    def __init__(self, alignment: str | None = None):
        self.rows: list[Row] = []
        # What a cell with no alignment of its own inherits (#1095), nearest first:
        # its <tr>, its <thead>/<tbody>/<tfoot>, then the <table>'s style.
        self.table_alignment = alignment
        self.section_alignment: str | None = None
        self.row_alignment: str | None = None
        self.col_widths_from_col: list[float | None] = []
        self._current_row_cells: list[Cell] = []
        self._current_cell: dict | None = None  # metadata for current open cell
        self._cell_col_widths: list[float | None] = []  # widths from <td width>
        self.in_cell = False
        # ordered content of the open cell
        self._current_children: list[Run | Image | Table] = []

    def start_row(self, alignment: str | None = None):
        self._current_row_cells = []
        self.row_alignment = alignment

    def end_row(self):
        if self._current_row_cells:
            self.rows.append(Row(cells=self._current_row_cells))
        self._current_row_cells = []
        self.row_alignment = None

    def inherited_alignment(self) -> str | None:
        return self.row_alignment or self.section_alignment or self.table_alignment

    def start_cell(
        self,
        colspan: int,
        rowspan: int,
        is_header: bool,
        width_pt: float | None,
        alignment: str | None = None,
    ):
        self._current_cell = {
            "colspan": colspan,
            "rowspan": rowspan,
            "is_header": is_header,
            "width_pt": width_pt,
            "alignment": alignment,
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
            alignment=meta["alignment"],
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
