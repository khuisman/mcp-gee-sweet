from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


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
    line_spacing: float | None = None  # 100=single, 150=1.5×, 200=double
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
class Cell:
    runs: list[Run]
    nested_table: Table | None = None  # one nested table rendered inside this cell
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


@dataclass
class Heading:
    level: int  # 1–6
    runs: list[Run]
    paragraph_style: ParagraphStyle | None = None


@dataclass
class Paragraph:
    runs: list[Run]
    paragraph_style: ParagraphStyle | None = None


@dataclass
class BulletItem:
    runs: list[Run]
    depth: int = 0
    ordered: bool = False
    checked: bool | None = None  # None = not a task item; True/False = ☑/☐
    paragraph_style: ParagraphStyle | None = None


@dataclass
class NamedBlock:
    style_type: str  # TITLE, SUBTITLE, NORMAL_TEXT
    runs: list[Run]
    paragraph_style: ParagraphStyle | None = None


DocNode = Union[Heading, Paragraph, BulletItem, Table, NamedBlock]
