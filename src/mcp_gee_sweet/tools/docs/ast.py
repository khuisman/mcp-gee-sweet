from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RGBColor:
    red: float
    green: float
    blue: float


@dataclass
class ParagraphStyle:
    alignment: str | None = None  # LEFT, CENTER, RIGHT, JUSTIFIED
    indent_start: float | None = None  # pt
    indent_end: float | None = None  # pt
    indent_first_line: float | None = None  # pt
    space_above: float | None = None  # pt
    space_below: float | None = None  # pt
    line_spacing: float | None = None  # 100=single, 150=1.5x, 200=double
    page_break_before: bool | None = None
    keep_lines_together: bool | None = None
    keep_with_next: bool | None = None


@dataclass
class Run:
    text: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strikethrough: bool | None = None
    link_url: str | None = None
    font_size: float | None = None  # Phase 3
    foreground_color: RGBColor | None = None  # Phase 3
    font_family: str | None = None  # Phase 3
    background_color: RGBColor | None = None  # Phase 3; text highlight
    baseline_offset: str | None = None  # Phase 3; SUPERSCRIPT, SUBSCRIPT
    small_caps: bool | None = None  # Phase 3


@dataclass
class Image:
    # Local filesystem path, "drive:<file_id>", or a public http(s) URL — resolved to a
    # fetchable URI by the caller (docs/content.py) before any insertInlineImage request
    # is built, since the Docs API only accepts a URI, never a Drive file ID (#333).
    src: str
    alt: str | None = None
    width: float | None = None  # pt
    height: float | None = None  # pt
    # The image element's own textStyle.link: read by doc_to_ast.py, and written
    # by emitter.py as an updateTextStyle over the image's one-character range (#977).
    link_url: str | None = None


# image_source_kind's values.
IMAGE_SOURCE_URL = "url"
IMAGE_SOURCE_DRIVE = "drive"
IMAGE_SOURCE_DATA = "data"
IMAGE_SOURCE_LOCAL = "local"


def _is_host_relative(src: str) -> bool:
    """A protocol-relative "//host/..." whose host starts with a letter or digit,
    the same test emitter._storable_link_url applies to a link (#1180)."""
    return src.startswith("//") and len(src) > 2 and src[2].isascii() and src[2].isalnum()


def image_source_kind(src: str) -> str:
    """What an Image.src names: an http(s) URL (a protocol-relative "//host/..."
    included, fetched over https by image_url), a "drive:<file_id>", a "data:" URI
    (inline bytes, which markdown-it's validateLink lets through for images), or,
    for anything else, a local path. The one classification every image path uses
    (#1232 QA round 1): resolving it, deciding whether a doc edit needs an upload
    folder, and naming it in fallback text. Schemes are case-insensitive (RFC 3986).
    html_parser strips the src when it builds the Image, so it's never padded here."""
    lowered = src[:8].lower()
    if lowered.startswith(("http://", "https://")) or _is_host_relative(src):
        return IMAGE_SOURCE_URL
    if lowered.startswith("drive:"):
        return IMAGE_SOURCE_DRIVE
    if lowered.startswith("data:"):
        return IMAGE_SOURCE_DATA
    return IMAGE_SOURCE_LOCAL


def image_url(src: str) -> str:
    """The URL Docs fetches for a URL-kind src: the src itself, or, for a
    protocol-relative "//host/...", https: plus it. Always https, never http, as
    for a link (#1180)."""
    return "https:" + src if _is_host_relative(src) else src


@dataclass
class Cell:
    # Ordered text runs, inline images, and nested tables, in source order
    children: list[Run | Image | Table]
    colspan: int = 1
    rowspan: int = 1
    is_header: bool = False
    content_alignment: str | None = None  # TOP, MIDDLE, BOTTOM
    background_color: RGBColor | None = None  # Phase 3
    padding_top: float | None = None  # Phase 3
    padding_right: float | None = None  # Phase 3
    padding_bottom: float | None = None  # Phase 3
    padding_left: float | None = None  # Phase 3
    border_color: RGBColor | None = None  # Phase 3
    border_width: float | None = None  # Phase 3
    border_dash_style: str | None = None  # Phase 3


@dataclass
class Row:
    cells: list[Cell]
    minimum_height: float | None = None  # pt
    is_header_row: bool = False


@dataclass
class Table:
    rows: list[Row]
    col_widths: list[float | None] = field(default_factory=list)
    table_alignment: str | None = None  # ALIGNED_START, CENTER, ALIGNED_END
    # Indent only (#1097): the emitter indents a quoted table like its quote, but gives
    # it no border or quote spacing, and doesn't count it as quoted for separators.
    blockquote_depth: int = 0
    list_depth: int | None = None  # #1094, see below
    list_path: tuple[int, ...] = field(default=(), compare=False)  # #1094, see below


# blockquote_path (#1098): the ids of the <blockquote> elements a node sits in, outermost
# first, one per level of blockquote_depth. Two quoted nodes belong to one quote exactly
# when one path is a prefix of the other; otherwise they are separate quotes, which the
# emitter must keep apart because Docs joins the borders of adjacent paragraphs styled
# alike. The ids are parser-assigned counters with no meaning beyond identity, so they
# don't take part in node equality. Empty when unknown (doc_to_ast.py): no separation.

# list_depth (#1094): set on a block inside a list item (a second paragraph, a code
# block, a quote, a heading, a table, a rule): the depth of that item. The emitter
# indents the block to the item's text and keeps the list going past it, so the next
# item continues its numbering. None for a block outside every list item. list_path is
# the item's BulletItem.list_path (write side only, identity only, like
# blockquote_path), so the emitter can tell which list the block belongs to.


@dataclass
class Heading:
    level: int  # 1-6
    runs: list[Run | Image]
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading
    list_depth: int | None = None  # #1094, see above Heading
    list_path: tuple[int, ...] = field(default=(), compare=False)  # #1094, see above Heading


@dataclass
class Paragraph:
    runs: list[Run | Image]
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading
    list_depth: int | None = None  # #1094, see above Heading
    list_path: tuple[int, ...] = field(default=(), compare=False)  # #1094, see above Heading
    # A thematic break (`---`, `<hr>`, #1096): an empty paragraph (runs=[]) the emitter
    # draws as a horizontal line, since the Docs API can't insert a horizontalRule
    # element. doc_to_ast.py reads both that stand-in and a native horizontal line back
    # as one, and ast_to_markdown.py writes it as a rule.
    rule: bool = False


@dataclass
class BulletItem:
    runs: list[Run | Image]
    depth: int = 0
    ordered: bool = False
    checked: bool | None = None  # None = not a task item; True/False = ☑/☐
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading
    # Read side only (#1208): an ordered item's ordinal in its Docs list, counted across
    # any blocks that interrupt the list. None when unknown; ast_to_markdown writes "1.".
    # Read-side metadata like blockquote_path, so it doesn't take part in equality.
    number: int | None = field(default=None, compare=False)
    # Write side only (#1241): ids of the source <ul>/<ol> lists enclosing the item,
    # outermost first, its own list last; parser-assigned counters like
    # blockquote_path's. Two adjacent lists of one type at one depth differ only
    # here. Empty when unknown: the emitter then groups by type alone. Identity
    # only, so it doesn't take part in equality.
    list_path: tuple[int, ...] = field(default=(), compare=False)
    # #1094: a list item whose own content is a heading ("- # Title"): the item is a
    # bulleted paragraph in that HEADING_N style. None for an ordinary item.
    heading_level: int | None = None


@dataclass
class NamedBlock:
    style_type: str  # TITLE, SUBTITLE, NORMAL_TEXT
    runs: list[Run | Image]
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading
    list_depth: int | None = None  # #1094, see above Heading
    list_path: tuple[int, ...] = field(default=(), compare=False)  # #1094, see above Heading


DocNode = Heading | Paragraph | BulletItem | Table | NamedBlock
