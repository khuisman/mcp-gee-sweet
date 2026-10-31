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


# blockquote_path (#1098): the ids of the <blockquote> elements a node sits in, outermost
# first, one per level of blockquote_depth. Two quoted nodes belong to one quote exactly
# when one path is a prefix of the other; otherwise they are separate quotes, which the
# emitter must keep apart because Docs joins the borders of adjacent paragraphs styled
# alike. The ids are parser-assigned counters with no meaning beyond identity, so they
# don't take part in node equality. Empty when unknown (doc_to_ast.py): no separation.


@dataclass
class Heading:
    level: int  # 1-6
    runs: list[Run | Image]
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading


@dataclass
class Paragraph:
    runs: list[Run | Image]
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading


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


@dataclass
class NamedBlock:
    style_type: str  # TITLE, SUBTITLE, NORMAL_TEXT
    runs: list[Run | Image]
    paragraph_style: ParagraphStyle | None = None
    blockquote_depth: int = 0  # 0 = not in a blockquote; N = nesting depth (#476)
    blockquote_path: tuple[int, ...] = field(default=(), compare=False)  # #1098, see above Heading


DocNode = Heading | Paragraph | BulletItem | Table | NamedBlock
