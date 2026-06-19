"""HTML string → Document AST."""

from __future__ import annotations

import html as html_module
from html.parser import HTMLParser

from .ast import BulletItem, Cell, DocNode, Heading, NamedBlock, Paragraph, Row, Run, Table

_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}
_NAMED_BLOCK_STYLES = {"title": "TITLE", "subtitle": "SUBTITLE"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_INLINE_BOLD = {"b", "strong"}
_INLINE_ITALIC = {"i", "em"}
_INLINE_UNDERLINE = {"u"}
_INLINE_STRIKE = {"s", "strike"}


def _px_to_pt(value: str) -> float | None:
    """Parse a width attribute value to points. Skips percentages."""
    v = value.strip().lower().rstrip("px")
    try:
        return float(v) * 72 / 96
    except ValueError:
        return None


class _AstParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._nodes: list[DocNode] = []

        # --- block context ---
        self._block_tag: str | None = None  # current block tag (h1–h6, p, li, pre)
        self._list_ordered: list[bool] = []  # stack: True=ol, False=ul
        self._in_pre = False  # inside <pre>; text is literal, runs get font_family

        # --- inline formatting stacks ---
        self._bold_depth = 0
        self._italic_depth = 0
        self._underline_depth = 0
        self._strike_depth = 0
        self._code_depth = 0  # inline <code> nesting; ignored inside <pre>
        self._link_url: list[str] = []  # stack of href values

        # --- current run buffer ---
        self._run_buf: list[str] = []
        self._pending_runs: list[Run] = []

        # --- table context ---
        self._table_depth = 0
        self._table_stack: list[_TableBuilder] = []

        # --- named block style (data-style on <p>) ---
        self._block_named_style: str | None = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _flush_run(self):
        """Commit buffered text as a Run (if non-empty) to pending_runs."""
        text = "".join(self._run_buf)
        if not text:
            return
        self._run_buf = []
        run = Run(
            text=text,
            bold=True if self._bold_depth > 0 else None,
            italic=True if self._italic_depth > 0 else None,
            underline=True if self._underline_depth > 0 else None,
            strikethrough=True if self._strike_depth > 0 else None,
            link_url=self._link_url[-1] if self._link_url else None,
            font_family="Courier New" if (self._in_pre or self._code_depth > 0) else None,
        )
        self._pending_runs.append(run)

    def _flush_pending_runs(self) -> list[Run]:
        self._flush_run()
        runs, self._pending_runs = self._pending_runs, []
        return runs

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)

        # --- table structure ---
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                # Collect col widths from the first row of <td width> or <col width>
                self._table_stack.append(_TableBuilder())
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
                tb.start_row()
                return
            if tag in ("td", "th"):
                colspan = int(attr_dict.get("colspan") or 1)
                rowspan = int(attr_dict.get("rowspan") or 1)
                is_header = tag == "th"
                width_str = attr_dict.get("width", "")
                width_pt = _px_to_pt(width_str) if width_str else None
                tb.start_cell(
                    colspan=colspan, rowspan=rowspan, is_header=is_header, width_pt=width_pt
                )
                # If it's a header cell, pre-activate bold
                if is_header:
                    self._bold_depth += 1
                return

        # --- list context ---
        if tag == "ol":
            self._list_ordered.append(True)
            return
        if tag == "ul":
            self._list_ordered.append(False)
            return

        # --- pre / code block ---
        if tag == "pre" and self._table_depth == 0:
            self._block_tag = "pre"
            self._in_pre = True
            self._run_buf = []
            self._pending_runs = []
            return

        # --- block elements ---
        if tag in _BLOCK_TAGS and self._table_depth == 0:
            self._block_tag = tag
            self._run_buf = []
            self._pending_runs = []
            if tag == "p":
                style = (attr_dict.get("data-style") or "").lower()
                self._block_named_style = _NAMED_BLOCK_STYLES.get(style)
            else:
                self._block_named_style = None
            return

        # --- inline elements ---
        if self._block_tag or (
            self._table_depth >= 1 and self._table_stack and self._table_stack[-1].in_cell
        ):
            self._flush_run()
            if tag in _INLINE_BOLD:
                self._bold_depth += 1
            elif tag in _INLINE_ITALIC:
                self._italic_depth += 1
            elif tag in _INLINE_UNDERLINE:
                self._underline_depth += 1
            elif tag in _INLINE_STRIKE:
                self._strike_depth += 1
            elif tag == "a":
                href = attr_dict.get("href", "")
                if href:
                    self._link_url.append(href)
            elif tag == "code" and not self._in_pre:
                self._code_depth += 1
            elif tag == "br":
                self._run_buf.append("\n")

    def handle_endtag(self, tag):
        # --- table structure ---
        if tag == "table":
            if self._table_depth == 1 and self._table_stack:
                tb = self._table_stack.pop()
                node = tb.build()
                if node is not None:
                    self._nodes.append(node)
            self._table_depth -= 1
            return

        if self._table_depth >= 1 and self._table_stack:
            tb = self._table_stack[-1]
            if tag == "tr":
                tb.end_row()
                return
            if tag in ("td", "th"):
                is_header = tag == "th"
                runs = self._flush_pending_runs()
                if is_header:
                    self._bold_depth -= 1
                tb.end_cell(runs)
                return

        # --- list context ---
        if tag == "ol" and self._list_ordered:
            if self._list_ordered[-1]:
                self._list_ordered.pop()
            return
        if tag == "ul" and self._list_ordered:
            if not self._list_ordered[-1]:
                self._list_ordered.pop()
            return

        # --- pre / code block ---
        if tag == "pre" and self._table_depth == 0 and self._block_tag == "pre":
            runs = self._flush_pending_runs()
            # Strip trailing newline that markdown adds inside <pre> content
            if runs and runs[-1].text.endswith("\n"):
                runs[-1].text = runs[-1].text.rstrip("\n")
                if not runs[-1].text:
                    runs.pop()
            if runs:
                self._nodes.append(Paragraph(runs=runs))
            self._block_tag = None
            self._in_pre = False
            return

        # --- block elements ---
        if tag in _BLOCK_TAGS and self._table_depth == 0 and self._block_tag == tag:
            runs = self._flush_pending_runs()
            text = "".join(r.text for r in runs).strip()
            if text:
                if tag in _HEADING_TAGS:
                    level = int(tag[1])
                    self._nodes.append(Heading(level=level, runs=runs))
                elif tag == "li":
                    ordered = self._list_ordered[-1] if self._list_ordered else False
                    depth = len(self._list_ordered) - 1
                    # Detect task list markers written as literal [x] / [ ] by the markdown library
                    checked = None
                    if runs:
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
                    self._nodes.append(
                        BulletItem(runs=runs, depth=depth, ordered=ordered, checked=checked)
                    )
                elif tag == "p" and self._block_named_style:
                    self._nodes.append(NamedBlock(style_type=self._block_named_style, runs=runs))
                else:
                    self._nodes.append(Paragraph(runs=runs))
            self._block_named_style = None
            self._block_tag = None
            return

        # --- inline elements ---
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
            elif tag == "a" and self._link_url:
                self._link_url.pop()
            elif tag == "code" and not self._in_pre:
                self._code_depth = max(0, self._code_depth - 1)

    def handle_data(self, data):
        if self._table_depth >= 1 and self._table_stack and self._table_stack[-1].in_cell:
            self._run_buf.append(data)
        elif self._block_tag:
            self._run_buf.append(data)

    def handle_entityref(self, name):
        text = html_module.unescape(f"&{name};")
        self.handle_data(text)

    def handle_charref(self, name):
        text = html_module.unescape(f"&#{name};")
        self.handle_data(text)


class _TableBuilder:
    """Accumulates rows/cells while parsing a <table>."""

    def __init__(self):
        self.rows: list[Row] = []
        self.col_widths_from_col: list[float | None] = []
        self._current_row_cells: list[Cell] = []
        self._current_cell: dict | None = None  # metadata for current open cell
        self._cell_col_widths: list[float | None] = []  # widths from <td width>
        self.in_cell = False

    def start_row(self):
        self._current_row_cells = []

    def end_row(self):
        if self._current_row_cells:
            self.rows.append(Row(cells=self._current_row_cells))
        self._current_row_cells = []

    def start_cell(self, colspan: int, rowspan: int, is_header: bool, width_pt: float | None):
        self._current_cell = {
            "colspan": colspan,
            "rowspan": rowspan,
            "is_header": is_header,
            "width_pt": width_pt,
        }
        self.in_cell = True

    def end_cell(self, runs: list[Run]):
        if self._current_cell is None:
            return
        meta = self._current_cell
        # Record td width for col_widths (first row only)
        if meta["width_pt"] is not None and len(self.rows) == 0:
            self._cell_col_widths.append(meta["width_pt"])
        cell = Cell(
            runs=runs,
            colspan=meta["colspan"],
            rowspan=meta["rowspan"],
            is_header=meta["is_header"],
        )
        self._current_row_cells.append(cell)
        self._current_cell = None
        self.in_cell = False

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
    return parser._nodes
