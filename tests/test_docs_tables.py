"""Tests for docs table tools and nested table emitter."""

import asyncio
from unittest.mock import MagicMock

import pytest

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs.ast import (
    Cell,
    Image,
    RGBColor,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.content import _html_to_doc_requests, _to_doc_requests
from mcp_gee_sweet.tools.docs.emitter import (
    CellImages,
    _apply_merges,
    _ast_cell_to_doc_cell,
    _build_fill_requests,
    _cell_para_start_for_cursor,
    _fill_nested_cell_content,
    _find_nth_table_in_cell,
    _text_offset_since_last_table,
    ast_to_requests,
    fill_tables,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


def _make_ctx(**services):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    for k, v in services.items():
        setattr(lc, k, v)
    return ctx


_docs_tool, _docs_tools = _make_tool_registry()
docs_module.register(_docs_tool)


# ---------------------------------------------------------------------------
# AST construction helpers
# ---------------------------------------------------------------------------


def _cell(text: str, colspan: int = 1, rowspan: int = 1) -> Cell:
    return Cell(children=[Run(text)], colspan=colspan, rowspan=rowspan)


def _row(*cells: Cell) -> Row:
    return Row(cells=list(cells))


def _table(*rows: Row) -> Table:
    return Table(rows=list(rows))


def _tables_in(cell: Cell) -> list[Table]:
    return [child for child in cell.children if isinstance(child, Table)]


def _runs_in(cell: Cell) -> list[Run]:
    return [child for child in cell.children if isinstance(child, Run)]


def _plain_images(svc, doc_id: str = "doc1") -> CellImages:
    """A fill with no cell images, sending each batch through `svc` as-is."""

    async def run_batch(requests: list[dict]) -> None:
        svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    return CellImages({}, run_batch, lambda _e: None, lambda *_: None)


# ---------------------------------------------------------------------------
# Table structural ops (#146)
# ---------------------------------------------------------------------------


class TestInsertTableRow:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_insert_below_default(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_table_row"](
            doc_id="doc1", table_start_index=5, row_index=1, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "row_index": 1}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertTableRow"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["rowIndex"] == 1
        assert req["tableCellLocation"]["columnIndex"] == 0
        assert req["insertBelow"] is True

    async def test_insert_above(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_table_row"](
            doc_id="doc1", table_start_index=5, row_index=0, insert_below=False, ctx=ctx
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["insertTableRow"]["insertBelow"] is False

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_table_row"](
            doc_id="doc1", table_start_index=5, row_index=0, ctx=ctx
        )
        assert "error" in result


class TestDeleteTableRow:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["delete_table_row"](
            doc_id="doc1", table_start_index=5, row_index=2, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "row_index": 2}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["deleteTableRow"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["rowIndex"] == 2
        assert req["tableCellLocation"]["columnIndex"] == 0

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["delete_table_row"](
            doc_id="doc1", table_start_index=5, row_index=0, ctx=ctx
        )
        assert "error" in result


class TestInsertTableColumn:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_insert_right_default(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_table_column"](
            doc_id="doc1", table_start_index=5, column_index=1, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "column_index": 1}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertTableColumn"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["columnIndex"] == 1
        assert req["tableCellLocation"]["rowIndex"] == 0
        assert req["insertRight"] is True

    async def test_insert_left(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_table_column"](
            doc_id="doc1", table_start_index=5, column_index=0, insert_right=False, ctx=ctx
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["insertTableColumn"]["insertRight"] is False

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_table_column"](
            doc_id="doc1", table_start_index=5, column_index=0, ctx=ctx
        )
        assert "error" in result


class TestMergeTableCells:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_sends_correct_request_defaults(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["merge_table_cells"](
            doc_id="doc1", table_start_index=5, row_index=0, column_index=1, ctx=ctx
        )
        assert result == {
            "docId": "doc1",
            "table_start_index": 5,
            "row_index": 0,
            "column_index": 1,
            "row_span": 1,
            "column_span": 1,
        }
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        tr = body["requests"][0]["mergeTableCells"]["tableRange"]
        assert tr["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert tr["tableCellLocation"]["rowIndex"] == 0
        assert tr["tableCellLocation"]["columnIndex"] == 1
        assert tr["rowSpan"] == 1
        assert tr["columnSpan"] == 1

    async def test_sends_correct_request_with_spans(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["merge_table_cells"](
            doc_id="doc1",
            table_start_index=5,
            row_index=1,
            column_index=2,
            row_span=2,
            column_span=3,
            ctx=ctx,
        )
        assert result == {
            "docId": "doc1",
            "table_start_index": 5,
            "row_index": 1,
            "column_index": 2,
            "row_span": 2,
            "column_span": 3,
        }
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        tr = body["requests"][0]["mergeTableCells"]["tableRange"]
        assert tr["rowSpan"] == 2
        assert tr["columnSpan"] == 3

    async def test_marks_doc_cache_dirty(self):
        docs_svc = MagicMock()
        doc_cache = MagicMock()
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=doc_cache)
        await _docs_tools["merge_table_cells"](
            doc_id="doc1", table_start_index=5, row_index=0, column_index=0, ctx=ctx
        )
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["merge_table_cells"](
            doc_id="doc1", table_start_index=5, row_index=0, column_index=0, ctx=ctx
        )
        assert "error" in result


class TestDeleteTableColumn:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["delete_table_column"](
            doc_id="doc1", table_start_index=5, column_index=2, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "column_index": 2}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["deleteTableColumn"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["columnIndex"] == 2
        assert req["tableCellLocation"]["rowIndex"] == 0

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["delete_table_column"](
            doc_id="doc1", table_start_index=5, column_index=0, ctx=ctx
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# Nested table — parser
# ---------------------------------------------------------------------------


def _nested_html(inner_rows: str = "<tr><td>inner</td></tr>") -> str:
    return f"<table><tr><td><table>{inner_rows}</table></td></tr></table>"


class TestNestedTableParser:
    async def test_simple_nested_table_parsed(self):
        nodes = html_to_ast(_nested_html())
        assert len(nodes) == 1
        outer = nodes[0]
        assert isinstance(outer, Table)
        cell = outer.rows[0].cells[0]
        tables = _tables_in(cell)
        assert len(tables) == 1

    async def test_nested_cell_text_correct(self):
        nodes = html_to_ast(_nested_html())
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert _runs_in(inner.rows[0].cells[0])[0].text == "inner"

    async def test_outer_cell_has_only_the_nested_table_when_no_surrounding_text(self):
        nodes = html_to_ast(_nested_html())
        cell = nodes[0].rows[0].cells[0]
        assert _runs_in(cell) == []
        assert len(cell.children) == 1

    async def test_nested_table_multiple_rows(self):
        nodes = html_to_ast(_nested_html("<tr><td>R0</td></tr><tr><td>R1</td></tr>"))
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert len(inner.rows) == 2
        assert _runs_in(inner.rows[0].cells[0])[0].text == "R0"
        assert _runs_in(inner.rows[1].cells[0])[0].text == "R1"

    async def test_nested_table_multiple_cols(self):
        nodes = html_to_ast(_nested_html("<tr><td>A</td><td>B</td></tr>"))
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert len(inner.rows[0].cells) == 2
        assert _runs_in(inner.rows[0].cells[1])[0].text == "B"

    async def test_non_nested_cell_has_no_table_child(self):
        nodes = html_to_ast("<table><tr><td>plain</td></tr></table>")
        assert _tables_in(nodes[0].rows[0].cells[0]) == []

    async def test_sibling_cell_text_preserved(self):
        # Col 0 has nested table; col 1 has plain text
        nodes = html_to_ast(
            "<table><tr><td><table><tr><td>inner</td></tr></table></td><td>plain</td></tr></table>"
        )
        outer = nodes[0]
        assert _tables_in(outer.rows[0].cells[0]) != []
        assert _runs_in(outer.rows[0].cells[1])[0].text == "plain"

    async def test_table_depth_resets_to_zero(self):
        from mcp_gee_sweet.tools.docs.html_parser import _AstParser

        parser = _AstParser()
        parser.feed(_nested_html())
        assert parser._table_depth == 0
        assert parser._table_stack == []

    # -- issue #108/#275: text sharing a cell with a nested table must not be
    # dropped, and must stay in true source order relative to the table(s) --

    async def test_leading_text_stays_with_outer_cell(self):
        # Exact reproduction from #108: text before the nested <table> used to
        # bleed into the nested table's own first cell instead of staying put.
        nodes = html_to_ast(
            "<table><tr><td>Some label <table><tr><td>inner</td></tr></table></td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        assert outer.children[0].text == "Some label "
        assert isinstance(outer.children[1], Table)
        assert _runs_in(outer.children[1].rows[0].cells[0])[0].text == "inner"

    async def test_trailing_text_stays_with_outer_cell(self):
        # Text after the nested table already worked before the fix — guard
        # against a regression while touching this code path.
        nodes = html_to_ast(
            "<table><tr><td><table><tr><td>inner</td></tr></table>After</td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        assert isinstance(outer.children[0], Table)
        assert outer.children[1].text == "After"

    async def test_leading_text_formatting_preserved(self):
        nodes = html_to_ast(
            "<table><tr><td>Some <b>bold</b> label "
            "<table><tr><td>inner</td></tr></table></td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        leading_runs = _runs_in(outer)
        texts_and_bold = [(r.text, r.bold) for r in leading_runs]
        assert texts_and_bold == [("Some ", None), ("bold", True), (" label ", None)]

    async def test_leading_and_trailing_text_in_true_order(self):
        # Issue #275: text before AND after a nested table, in the same cell,
        # must preserve true source order — not collapse into one block.
        nodes = html_to_ast(
            "<table><tr><td>Before <table><tr><td>inner</td></tr></table> After</td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        kinds = [type(c).__name__ for c in outer.children]
        assert kinds == ["Run", "Table", "Run"]
        assert outer.children[0].text == "Before "
        assert outer.children[2].text == " After"

    async def test_multiple_nested_tables_with_text_between(self):
        # A cell may contain more than one nested table, with text interleaved
        # between them, in true order (not supported before #275).
        nodes = html_to_ast(
            "<table><tr><td>A<table><tr><td>1</td></tr></table>B"
            "<table><tr><td>2</td></tr></table>C</td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        kinds = [type(c).__name__ for c in outer.children]
        assert kinds == ["Run", "Table", "Run", "Table", "Run"]
        assert outer.children[0].text == "A"
        assert _runs_in(outer.children[1].rows[0].cells[0])[0].text == "1"
        assert outer.children[2].text == "B"
        assert _runs_in(outer.children[3].rows[0].cells[0])[0].text == "2"
        assert outer.children[4].text == "C"


# ---------------------------------------------------------------------------
# Nested table — emitter phase-1 (ast_to_requests)
# ---------------------------------------------------------------------------


class TestNestedTableEmitter:
    async def test_outer_table_emits_insert_table(self):
        requests, _tables = _html_to_doc_requests(
            "<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
        )
        table_inserts = [r for r in requests if "insertTable" in r]
        # Only the OUTER table is inserted in phase 1; nested table is handled by fill_tables
        assert len(table_inserts) == 1
        assert table_inserts[0]["insertTable"]["rows"] == 1
        assert table_inserts[0]["insertTable"]["columns"] == 1

    async def test_tables_list_contains_outer_with_nested_cell(self):
        _, tables = _html_to_doc_requests(
            "<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
        )
        assert len(tables) == 1
        assert _tables_in(tables[0].rows[0].cells[0]) != []


# ---------------------------------------------------------------------------
# Nested table — pure helpers (_ast_cell_to_doc_cell, _cell_para_start_for_cursor,
# _text_offset_since_last_table, _find_nth_table_in_cell)
# ---------------------------------------------------------------------------


def _para_elem(start_index: int, end_index: int | None = None) -> dict:
    return {"paragraph": {}, "startIndex": start_index, "endIndex": end_index or start_index + 1}


def _table_content_elem(inner_doc_table: dict) -> dict:
    return {"table": inner_doc_table}


class TestAstCellToDocCell:
    async def test_single_cell_matches(self):
        ast_table = _table(_row(_cell("x")))
        doc_cell = {"startIndex": 9, "content": [_para_elem(10)]}
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        assert _ast_cell_to_doc_cell(doc_table, ast_table, r=0, ast_col=0) is doc_cell

    async def test_second_column_matches_by_position(self):
        ast_table = _table(_row(_cell("a"), _cell("b")))
        doc_cell_a = {"startIndex": 9, "content": [_para_elem(10)]}
        doc_cell_b = {"startIndex": 19, "content": [_para_elem(20)]}
        doc_table = {"tableRows": [{"tableCells": [doc_cell_a, doc_cell_b]}]}
        assert _ast_cell_to_doc_cell(doc_table, ast_table, r=0, ast_col=1) is doc_cell_b

    async def test_row_out_of_range_returns_none(self):
        ast_table = _table(_row(_cell("x")))
        doc_table = {"tableRows": []}
        assert _ast_cell_to_doc_cell(doc_table, ast_table, r=0, ast_col=0) is None


class TestCellParaStartForCursor:
    async def test_cursor_zero_returns_first_paragraph(self):
        ast_cell = Cell(children=[Run("x")])
        doc_cell = {"content": [_para_elem(10)]}
        assert _cell_para_start_for_cursor(doc_cell, ast_cell, cursor=0) == 10

    async def test_after_one_table_returns_second_paragraph(self):
        inner = _table(_row(_cell("x")))
        ast_cell = Cell(children=[inner, Run("After")])
        doc_cell = {
            "content": [_para_elem(10), _table_content_elem({"tableRows": []}), _para_elem(20)]
        }
        assert _cell_para_start_for_cursor(doc_cell, ast_cell, cursor=1) == 20

    async def test_missing_paragraph_returns_none(self):
        inner = _table(_row(_cell("x")))
        ast_cell = Cell(children=[inner, Run("After")])
        doc_cell = {"content": [_para_elem(10)]}  # no paragraph after the table yet
        assert _cell_para_start_for_cursor(doc_cell, ast_cell, cursor=1) is None


class TestTextOffsetSinceLastTable:
    async def test_no_preceding_children_is_zero(self):
        assert _text_offset_since_last_table([Run("x")], cursor=0) == 0

    async def test_sums_runs_since_start(self):
        children = [Run("AB"), Run("CDE")]
        assert _text_offset_since_last_table(children, cursor=2) == 5

    async def test_stops_at_nearest_preceding_table(self):
        inner = _table(_row(_cell("x")))
        children = [Run("AB"), inner, Run("CDE")]
        assert _text_offset_since_last_table(children, cursor=3) == 3

    async def test_zero_for_a_table_immediately_after_another_table(self):
        t1 = _table(_row(_cell("x")))
        t2 = _table(_row(_cell("y")))
        children = [t1, t2]
        assert _text_offset_since_last_table(children, cursor=1) == 0


class TestFindNthTableInCell:
    async def test_finds_only_table(self):
        ast_table = _table(_row(_cell("x")))
        nested_doc_table = {"tableRows": [{"tableCells": [{"content": [_para_elem(30)]}]}]}
        doc_cell = {
            "startIndex": 9,
            "content": [_para_elem(10), _table_content_elem(nested_doc_table)],
        }
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        result = _find_nth_table_in_cell(doc_table, ast_table, r=0, c=0, occurrence=0)
        assert result is nested_doc_table

    async def test_second_occurrence_found(self):
        ast_table = _table(_row(_cell("x")))
        first_nested = {"tableRows": [{"tableCells": [{"content": [_para_elem(30)]}]}]}
        second_nested = {"tableRows": [{"tableCells": [{"content": [_para_elem(50)]}]}]}
        doc_cell = {
            "startIndex": 9,
            "content": [
                _para_elem(10),
                _table_content_elem(first_nested),
                _para_elem(40),
                _table_content_elem(second_nested),
            ],
        }
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        result = _find_nth_table_in_cell(doc_table, ast_table, r=0, c=0, occurrence=1)
        assert result is second_nested

    async def test_occurrence_not_found_returns_none(self):
        ast_table = _table(_row(_cell("x")))
        doc_cell = {"startIndex": 9, "content": [_para_elem(10)]}
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        assert _find_nth_table_in_cell(doc_table, ast_table, r=0, c=0, occurrence=0) is None


# ---------------------------------------------------------------------------
# Nested table — _fill_nested_cell_content (end-to-end round/re-fetch behavior)
#
# FakeDoc/Para/TableNode are a minimal Google-Docs-like simulator: they
# actually apply insertText/insertTable mutations and re-derive indices on
# every get(), instead of relying on hand-computed index fixtures — this
# nested re-fetch/recursion logic is easy to get subtly wrong, and a hand-
# computed fixture can't catch that the way an executable model can.
# ---------------------------------------------------------------------------


IMG = "▣"  # how FakeDoc shows an inline image in a paragraph's text


class Para:
    def __init__(self, text: str = ""):
        self.text = text

    def size(self) -> int:
        return len(self.text) + 1  # implicit trailing newline

    def to_elem(self, start: int) -> dict:
        return {"paragraph": {}, "startIndex": start, "endIndex": start + self.size()}


class FakeCell:
    def __init__(self):
        self.content: list = [Para("")]

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.content) + 1  # cell start/end markers

    def to_elem(self, start: int) -> dict:
        idx = start + 1
        elems = []
        for c in self.content:
            elems.append(c.to_elem(idx))
            idx += c.size()
        return {"startIndex": start, "endIndex": start + self.size(), "content": elems}


class TableNode:
    def __init__(self, rows: int, cols: int):
        self.rows: list[list[FakeCell]] = [[FakeCell() for _ in range(cols)] for _ in range(rows)]

    def size(self) -> int:
        return 1 + sum(1 + sum(c.size() for c in row) for row in self.rows) + 1

    def to_elem(self, start: int) -> dict:
        idx = start + 1
        row_dicts = []
        for row in self.rows:
            row_start = idx
            idx += 1
            cell_dicts = []
            for cell in row:
                cell_dicts.append(cell.to_elem(idx))
                idx += cell.size()
            row_dicts.append({"tableCells": cell_dicts, "startIndex": row_start})
        return {
            "table": {"tableRows": row_dicts},
            "startIndex": start,
            "endIndex": start + self.size(),
        }


class FakeDoc:
    """A tiny in-memory stand-in for the Docs API's document tree — only
    supports what the nested-table fill path needs: insertText and
    insertTable, applied against a mutable tree, with indices re-derived
    fresh on every get()."""

    def __init__(self):
        self.content: list = [Para("")]

    def _find_para(self, index: int):
        # Walk the object tree and the freshly computed get() dict in lockstep,
        # so index math is never duplicated — only to_elem() computes indices.
        doc_dict = self.get()

        def walk(objs, dict_elems):
            for i, (obj, dict_elem) in enumerate(zip(objs, dict_elems, strict=True)):
                if isinstance(obj, Para):
                    if dict_elem["startIndex"] <= index <= dict_elem["endIndex"]:
                        return obj, dict_elem["startIndex"], objs, i
                else:
                    for row_obj, row_elem in zip(
                        obj.rows, dict_elem["table"]["tableRows"], strict=True
                    ):
                        for cell_obj, cell_elem in zip(
                            row_obj, row_elem["tableCells"], strict=True
                        ):
                            result = walk(cell_obj.content, cell_elem["content"])
                            if result:
                                return result
            return None

        result = walk(self.content, doc_dict["body"]["content"])
        if result is None:
            raise ValueError(f"no paragraph found for index {index}")
        return result

    def insert_text(self, index: int, text: str):
        para, start, _, _ = self._find_para(index)
        offset = index - start
        para.text = para.text[:offset] + text + para.text[offset:]

    def insert_table(self, index: int, rows: int, cols: int):
        para, start, elems, pos = self._find_para(index)
        offset = index - start
        before, after = para.text[:offset], para.text[offset:]
        para.text = before
        elems.insert(pos + 1, TableNode(rows, cols))
        elems.insert(pos + 2, Para(after))

    def batch_update(self, requests: list[dict]):
        for req in requests:
            if "insertText" in req:
                self.insert_text(req["insertText"]["location"]["index"], req["insertText"]["text"])
            elif "insertInlineImage" in req:
                # An inline object takes one index, like a character (#1073).
                self.insert_text(req["insertInlineImage"]["location"]["index"], IMG)
            elif "insertTable" in req:
                it = req["insertTable"]
                self.insert_table(it["location"]["index"], it["rows"], it["columns"])
            elif "mergeTableCells" in req:
                # Real mergeTableCells doesn't delete content or shift indices —
                # covered cells remain physical entries (see _physical_to_ast_indices) —
                # so this simulator has nothing to mutate; the fill step already knows
                # to skip covered cells based on the AST's own colspan/rowspan.
                pass
            elif "updateTableColumnProperties" in req:
                utcp = req["updateTableColumnProperties"]
                table = self._check_table_start(utcp["tableStartLocation"])
                # Mirrors the real API's 400 "Invalid column index N."
                for col_idx in utcp["columnIndices"]:
                    if col_idx >= len(table.rows[0]):
                        raise ValueError(f"invalid column index {col_idx}")
            elif "updateTableCellStyle" in req:
                loc = req["updateTableCellStyle"]["tableRange"]["tableCellLocation"]
                self._check_table_start(loc["tableStartLocation"])

    def _check_table_start(self, location: dict) -> "TableNode":
        # Mirrors the real API's 400 "The provided table start location is
        # invalid." for an index that isn't a top-level table's current start (#1053).
        for obj, elem in zip(self.content, self.get()["body"]["content"], strict=True):
            if isinstance(obj, TableNode) and elem["startIndex"] == location["index"]:
                return obj
        raise ValueError(f"invalid table start location {location['index']}")

    def get(self) -> dict:
        idx = 0
        out = []
        for e in self.content:
            out.append(e.to_elem(idx))
            idx += e.size()
        return {"body": {"content": out}}

    def describe_cell(self, table_index: int, row: int, col: int) -> list[str]:
        cell = self.content[table_index].rows[row][col]
        out = []
        for c in cell.content:
            if isinstance(c, Para):
                if c.text:
                    out.append(f"Para:{c.text}")
            else:
                out.append("Table")
        return out


class TestFillNestedCellContent:
    """Drive the real multi-round fill algorithm against the FakeDoc simulator
    above — far more trustworthy
    than hand-computed index fixtures for this much re-fetch/recursion logic
    (issues #108, #275)."""

    async def _run(self, outer_cell: Cell) -> FakeDoc:
        doc = FakeDoc()
        doc.content = [TableNode(1, 1)]
        ast_table = Table(rows=[Row(cells=[outer_cell])])

        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = lambda **_kwargs: (
            doc.get()
        )

        def do_batch(documentId, body):
            doc.batch_update(body["requests"])
            m = MagicMock()
            m.execute.return_value = {}
            return m

        svc.documents.return_value.batchUpdate.side_effect = do_batch
        await _fill_nested_cell_content(svc, "doc1", [ast_table], _plain_images(svc))
        return doc

    async def test_leading_text_only(self):
        # children = [Run("Some label "), Table(inner)] — issue #108's exact repro.
        inner = _table(_row(_cell("inner")))
        doc = await self._run(Cell(children=[Run("Some label "), inner]))
        assert doc.describe_cell(0, 0, 0) == ["Para:Some label ", "Table"]

    async def test_trailing_text_only_regression_guard(self):
        inner = _table(_row(_cell("inner")))
        doc = await self._run(Cell(children=[inner, Run("After")]))
        assert doc.describe_cell(0, 0, 0) == ["Table", "Para:After"]

    async def test_leading_and_trailing_text_around_one_table(self):
        # Issue #275's exact repro: text before AND after one nested table must
        # land on the correct side of it, not both merge before the table.
        inner = _table(_row(_cell("Inner")))
        doc = await self._run(Cell(children=[Run("Before "), inner, Run(" After")]))
        assert doc.describe_cell(0, 0, 0) == ["Para:Before ", "Table", "Para: After"]

    async def test_two_nested_tables_with_text_between(self):
        # General case: multiple nested tables in one cell, with text
        # interleaved — validates the fully general children ordering.
        t1 = _table(_row(_cell("1")))
        t2 = _table(_row(_cell("2")))
        doc = await self._run(Cell(children=[Run("A"), t1, Run("B"), t2, Run("C")]))
        assert doc.describe_cell(0, 0, 0) == [
            "Para:A",
            "Table",
            "Para:B",
            "Table",
            "Para:C",
        ]

    async def test_nested_tables_own_text_is_filled(self):
        # A nested table's own plain cells must be filled too — not just its
        # shell inserted (a regression this exact test class caught once).
        inner = _table(_row(_cell("Inner")))
        doc = await self._run(Cell(children=[Run("Before "), inner, Run(" After")]))
        outer_table = doc.content[0]
        outer_cell = outer_table.rows[0][0]
        nested_table = next(c for c in outer_cell.content if isinstance(c, TableNode))
        nested_cell = nested_table.rows[0][0]
        assert [
            f"Para:{c.text}" if isinstance(c, Para) else "Table" for c in nested_cell.content
        ] == ["Para:Inner"]

    async def test_deeply_nested_mixed_content_at_every_level(self):
        # A nested table's own cell may itself contain a further nested table,
        # with text on both sides, at any depth.
        deep = _table(_row(_cell("deep")))
        mid = _table(_row(Cell(children=[Run("mid-before "), deep, Run(" mid-after")])))
        doc = await self._run(Cell(children=[Run("outer-before "), mid, Run(" outer-after")]))
        assert doc.describe_cell(0, 0, 0) == [
            "Para:outer-before ",
            "Table",
            "Para: outer-after",
        ]

        outer_cell = doc.content[0].rows[0][0]
        mid_table = next(c for c in outer_cell.content if isinstance(c, TableNode))
        mid_cell = mid_table.rows[0][0]
        assert [f"Para:{c.text}" if isinstance(c, Para) else "Table" for c in mid_cell.content] == [
            "Para:mid-before ",
            "Table",
            "Para: mid-after",
        ]

        deep_table = next(c for c in mid_cell.content if isinstance(c, TableNode))
        deep_cell = deep_table.rows[0][0]
        assert [c.text for c in deep_cell.content if isinstance(c, Para) and c.text] == ["deep"]

    async def test_plain_cells_produce_no_calls(self):
        ast_table = _table(_row(_cell("plain")))
        svc = MagicMock()
        await _fill_nested_cell_content(svc, "doc1", [ast_table], _plain_images(svc))
        svc.documents.return_value.get.assert_not_called()
        svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_degenerate_zero_column_table_does_not_abandon_trailing_content(self):
        # A table with a row but no cells has num_cols == 0, so the
        # `num_rows > 0 and num_cols > 0` guard skips its insertTable request —
        # that round then has no requests at all. The loop must not treat an
        # empty round as "done": trailing content after the skipped table still
        # needs to be processed, not silently abandoned.
        degenerate = Table(rows=[Row(cells=[])])
        doc = await self._run(Cell(children=[degenerate, Run("After")]))
        assert doc.describe_cell(0, 0, 0) == ["Para:After"]

    async def test_image_child_is_skipped_not_looped_on(self):
        # #509: a cell with a nested table and an Image used to stay pending
        # forever, since the run-group loop stopped at the Image without advancing.
        # The Image never resolved here, so it's written as its fallback text (#1099),
        # as _build_fill_requests writes it in a plain cell: "image", since a drive:
        # source with no alt has no name to show.
        inner = _table(_row(_cell("inner")))
        img = Image(src="drive:abc")
        doc = await asyncio.wait_for(
            self._run(Cell(children=[img, Run("A"), img, Run("B"), inner, img])), timeout=5
        )
        assert doc.describe_cell(0, 0, 0) == ["Para:imageAimageB", "Table", "Para:image"]


# ---------------------------------------------------------------------------
# #109 — colspan/rowspan on cells inside a nested table
# ---------------------------------------------------------------------------


class TestNestedTableMerges:
    """A nested table's own cells may have colspan/rowspan > 1 — _fill_table_fully
    must emit mergeTableCells for them, mirroring the outer-table merge phase in
    fill_tables(), instead of silently leaving an unmerged shell (#109)."""

    async def _run(self, outer_cell: Cell) -> tuple[FakeDoc, list[list[dict]]]:
        doc = FakeDoc()
        doc.content = [TableNode(1, 1)]
        ast_table = Table(rows=[Row(cells=[outer_cell])])

        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = lambda **_kwargs: (
            doc.get()
        )

        batches: list[list[dict]] = []

        def do_batch(documentId, body):
            batches.append(body["requests"])
            doc.batch_update(body["requests"])
            m = MagicMock()
            m.execute.return_value = {}
            return m

        svc.documents.return_value.batchUpdate.side_effect = do_batch
        await _fill_nested_cell_content(svc, "doc1", [ast_table], _plain_images(svc))
        return doc, batches

    async def test_colspan_merge_emitted_and_only_anchor_cell_filled(self):
        inner = _table(_row(_cell("Header", colspan=2)))
        doc, batches = await self._run(Cell(children=[inner]))

        merge_reqs = [r for batch in batches for r in batch if "mergeTableCells" in r]
        assert len(merge_reqs) == 1
        tr = merge_reqs[0]["mergeTableCells"]["tableRange"]
        assert tr["rowSpan"] == 1
        assert tr["columnSpan"] == 2

        nested_table = next(
            c for c in doc.content[0].rows[0][0].content if isinstance(c, TableNode)
        )
        assert nested_table.rows[0][0].content[0].text == "Header"
        assert nested_table.rows[0][1].content[0].text == ""  # colspan phantom — untouched

    async def test_rowspan_merge_emitted_and_only_anchor_cell_filled(self):
        inner = _table(_row(_cell("A", rowspan=2), _cell("B")), _row(_cell("C")))
        doc, batches = await self._run(Cell(children=[inner]))

        merge_reqs = [r for batch in batches for r in batch if "mergeTableCells" in r]
        assert len(merge_reqs) == 1
        tr = merge_reqs[0]["mergeTableCells"]["tableRange"]
        assert tr["rowSpan"] == 2
        assert tr["columnSpan"] == 1

        nested_table = next(
            c for c in doc.content[0].rows[0][0].content if isinstance(c, TableNode)
        )
        assert nested_table.rows[0][0].content[0].text == "A"
        assert nested_table.rows[0][1].content[0].text == "B"
        assert nested_table.rows[1][0].content[0].text == ""  # rowspan phantom — untouched
        assert nested_table.rows[1][1].content[0].text == "C"

    async def test_no_merge_call_when_nested_table_has_no_spans(self):
        inner = _table(_row(_cell("A"), _cell("B")))
        _doc, batches = await self._run(Cell(children=[inner]))
        assert not any("mergeTableCells" in r for batch in batches for r in batch)

    async def test_merge_precedes_fill_in_batch_order(self):
        # Pin the documented phase order in _fill_table_fully — merge runs (and
        # is re-fetched) before the bulk text fill, mirroring fill_tables()'s own
        # outer-table phase order. (The batch preceding both is the round
        # algorithm's own insertTable for the nested table's shell.)
        inner = _table(_row(_cell("Header", colspan=2)))
        _doc, batches = await self._run(Cell(children=[inner]))

        merge_idx = next(
            i for i, batch in enumerate(batches) if any("mergeTableCells" in r for r in batch)
        )
        fill_idx = next(
            i for i, batch in enumerate(batches) if any("insertText" in r for r in batch)
        )
        assert merge_idx < fill_idx

    async def test_raises_when_table_vanishes_from_resolve_after_merge(self):
        # mergeTableCells doesn't shift indices or delete content, so a resolve
        # failure right after one is an anomaly, not a normal "not there yet"
        # case — it must surface loudly rather than silently drop the fill and
        # leave the just-merged table empty with no operator-visible signal.
        ast_table = _table(_row(_cell("Header", colspan=2)))
        doc_table = {
            "tableRows": [
                {
                    "tableCells": [
                        {"startIndex": 3, "content": [{"startIndex": 4}]},
                        {"startIndex": 6, "content": [{"startIndex": 7}]},
                    ]
                }
            ]
        }

        svc = MagicMock()
        svc.documents.return_value.batchUpdate.return_value.execute.return_value = {}
        svc.documents.return_value.get.return_value.execute.return_value = {"body": {"content": []}}

        with pytest.raises(RuntimeError, match="vanished"):
            await _apply_merges(svc, "doc1", [doc_table], [ast_table], lambda _live_doc: [])


# ---------------------------------------------------------------------------
# #1053 — column widths on a table after the first must use post-fill indices
# ---------------------------------------------------------------------------


class TestFillTablesColumnWidths:
    """Drive the real fill_tables() against FakeDoc, which rejects a
    tableStartLocation that isn't a table's current start index, and a
    column index past the table's last column."""

    async def _run(self, ast_tables: list[Table]) -> tuple[FakeDoc, list[list[dict]], int]:
        doc = FakeDoc()
        content: list = [Para("")]
        for t in ast_tables:
            content += [TableNode(len(t.rows), len(t.rows[0].cells)), Para("sep")]
        doc.content = content

        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = lambda **_kwargs: (
            doc.get()
        )
        batches: list[list[dict]] = []

        def do_batch(documentId, body):
            batches.append(body["requests"])
            doc.batch_update(body["requests"])
            m = MagicMock()
            m.execute.return_value = {}
            return m

        svc.documents.return_value.batchUpdate.side_effect = do_batch
        await fill_tables(svc, "doc1", ast_tables, _plain_images(svc))
        fetches = svc.documents.return_value.get.return_value.execute.call_count
        return doc, batches, fetches

    async def _baseline_fetches(self) -> int:
        _doc, _batches, fetches = await self._run([_table(_row(_cell("A")), _row(_cell("B")))])
        return fetches

    @staticmethod
    def _width_starts(batches: list[list[dict]]) -> list[int]:
        return [
            r["updateTableColumnProperties"]["tableStartLocation"]["index"]
            for batch in batches
            for r in batch
            if "updateTableColumnProperties" in r
        ]

    async def test_widths_on_second_table_use_post_fill_start(self):
        first = _table(_row(_cell("A")))
        second = _table(_row(_cell("Narrow"), _cell("Wide")))
        second.col_widths = [108.0, 216.0]
        doc, batches, _fetches = await self._run([first, second])

        table_starts = [e["startIndex"] for e in doc.get()["body"]["content"] if "table" in e]
        assert self._width_starts(batches) == [table_starts[1], table_starts[1]]

    async def test_widths_on_every_table_after_text_filled_tables(self):
        tables = [_table(_row(_cell(f"cell {i}"), _cell("x"))) for i in range(3)]
        for t in tables:
            t.col_widths = [72.0, None]
        doc, batches, _fetches = await self._run(tables)

        table_starts = [e["startIndex"] for e in doc.get()["body"]["content"] if "table" in e]
        assert self._width_starts(batches) == table_starts

    async def test_more_col_widths_than_columns_are_skipped(self):
        # <col> x3 over a 2-cell row: a columnIndices entry of 2 is a 400 that
        # clears the doc and keeps the backup.
        table = _table(_row(_cell("a"), _cell("b")))
        table.col_widths = [75.0, 75.0, 75.0]
        _doc, batches, _fetches = await self._run([table])

        indices = [
            r["updateTableColumnProperties"]["columnIndices"]
            for batch in batches
            for r in batch
            if "updateTableColumnProperties" in r
        ]
        assert indices == [[0], [1]]

    async def test_cell_styles_after_widths_share_one_post_fill_fetch(self):
        baseline = await self._baseline_fetches()
        first = _table(_row(_cell("A")))
        second = _table(_row(_cell("B")))
        second.col_widths = [144.0]
        second.rows[0].cells[0].background_color = RGBColor(1.0, 0.0, 0.0)
        # FakeDoc raises on a stale start
        _doc, batches, fetches = await self._run([first, second])

        assert any("updateTableCellStyle" in r for batch in batches for r in batch)
        assert fetches == baseline + 1

    async def test_cell_styles_alone_fetch_after_fill(self):
        baseline = await self._baseline_fetches()
        first = _table(_row(_cell("A")))
        second = _table(_row(_cell("B")))
        second.rows[0].cells[0].background_color = RGBColor(1.0, 0.0, 0.0)
        _doc, batches, fetches = await self._run([first, second])

        assert any("updateTableCellStyle" in r for batch in batches for r in batch)
        assert fetches == baseline + 1

    async def test_no_extra_fetch_without_col_widths(self):
        baseline = await self._baseline_fetches()
        first = _table(_row(_cell("A")))
        second = _table(_row(_cell("B")))
        _doc, batches, fetches = await self._run([first, second])
        assert self._width_starts(batches) == []
        assert fetches == baseline

    async def test_no_extra_fetch_when_every_col_width_is_none(self):
        # <col> with a percentage or no width parses to None
        baseline = await self._baseline_fetches()
        first = _table(_row(_cell("A")))
        second = _table(_row(_cell("B"), _cell("C")))
        second.col_widths = [None, None]
        _doc, batches, fetches = await self._run([first, second])
        assert self._width_starts(batches) == []
        assert fetches == baseline


# ---------------------------------------------------------------------------
# #277 — a skipped degenerate table must not desync doc_tables/ast_tables
# ---------------------------------------------------------------------------


class TestSkippedTableDoesNotDesyncTablePairing:
    async def test_empty_row_table_excluded_from_ast_to_requests_tables(self):
        # A top-level <table><tr></tr></table> has a row but zero cells, so num_cols == 0
        # and no insertTable request is emitted for it. It must not appear in the returned
        # `tables` list either, or the table after it desyncs from doc_tables in fill_tables().
        empty_table = _table(_row())
        normal_table = _table(_row(_cell("hello")))
        requests, tables = ast_to_requests([empty_table, normal_table])

        table_inserts = [r for r in requests if "insertTable" in r]
        assert len(table_inserts) == 1
        assert tables == [normal_table]

    async def test_fill_requests_land_on_correct_table_after_a_skip(self):
        # Simulates fill_tables(): doc_tables comes from the live doc, which only ever
        # contains tables that actually got an insertTable request — i.e. never the
        # skipped empty-row table. ast_tables must be the same (already-filtered) list
        # returned by ast_to_requests, so the zip() stays 1:1.
        empty_table = _table(_row())
        normal_table = _table(_row(_cell("hello")))
        _, tables = ast_to_requests([empty_table, normal_table])

        doc_table = {
            "tableRows": [{"tableCells": [{"startIndex": 9, "content": [{"startIndex": 10}]}]}]
        }
        fill_requests = _build_fill_requests([doc_table], tables, _plain_images(MagicMock()))

        insert_texts = [r["insertText"] for r in fill_requests if "insertText" in r]
        assert len(insert_texts) == 1
        assert insert_texts[0]["text"] == "hello"
        assert insert_texts[0]["location"]["index"] == 10


# ---------------------------------------------------------------------------
# #1073 — images inside table cells
# ---------------------------------------------------------------------------


class TestCellImageParser:
    async def test_img_in_cell_becomes_image_child(self):
        nodes = html_to_ast(
            '<table><tr><td>Before</td><td><img src="https://a/b.png" width="40"></td>'
            "<td>After</td></tr></table>"
        )
        cells = nodes[0].rows[0].cells
        assert cells[1].children == [Image(src="https://a/b.png", width=30.0)]
        assert _runs_in(cells[0])[0].text == "Before"
        assert _runs_in(cells[2])[0].text == "After"

    async def test_image_keeps_source_order_and_link(self):
        nodes = html_to_ast(
            '<table><tr><td>A <a href="https://x.com"><img src="https://a/b.png"></a> B'
            "</td></tr></table>"
        )
        children = nodes[0].rows[0].cells[0].children
        assert [type(c).__name__ for c in children] == ["Run", "Image", "Run"]
        assert children[1].link_url == "https://x.com"

    async def test_markdown_table_cell_image(self):
        _, tables = _to_doc_requests(
            "| a | b |\n|---|---|\n| Logo | ![cell logo](https://a/b.png) |\n", "markdown"
        )
        assert tables[0].rows[1].cells[1].children == [
            Image(src="https://a/b.png", alt="cell logo")
        ]

    async def test_image_in_nested_table_cell(self):
        nodes = html_to_ast(
            '<table><tr><td>outer<table><tr><td><img src="https://a/b.png"></td></tr></table>'
            "</td></tr></table>"
        )
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert inner.rows[0].cells[0].children == [Image(src="https://a/b.png")]

    async def test_img_without_src_in_cell_is_dropped(self):
        nodes = html_to_ast("<table><tr><td>x<img></td></tr></table>")
        assert [type(c).__name__ for c in nodes[0].rows[0].cells[0].children] == ["Run"]

    @staticmethod
    def _shape(cell: Cell) -> list:
        return [c.text if isinstance(c, Run) else type(c).__name__ for c in cell.children]

    async def test_indentation_around_a_nested_table_is_dropped(self):
        # PR #1215 QA round 1: TC-DOC102 Case 7's indented fixture gave the cell a
        # Run("\n      ") before the nested table, written as empty paragraphs.
        nodes = html_to_ast(
            "<table><tr><td>\n      <table><tr><td>x</td></tr></table>\n    </td></tr></table>"
        )
        assert self._shape(nodes[0].rows[0].cells[0]) == ["Table"]

    @staticmethod
    def _linked_text(cell: Cell) -> list[tuple[str, str | None]]:
        """A cell's text as (text, link) spans, adjacent same-link runs joined: they
        render alike, and where runs split depends only on where tags flushed."""
        spans: list[tuple[str, str | None]] = []
        for child in cell.children:
            if isinstance(child, Run) and spans and spans[-1][1] == child.link_url:
                spans[-1] = (spans[-1][0] + child.text, child.link_url)
            elif isinstance(child, Run):
                spans.append((child.text, child.link_url))
            else:
                spans.append((type(child).__name__, "-"))  # never joins a run
        return spans

    async def test_line_break_edges_are_trimmed(self):
        # Whitespace holding a line break goes at a segment's edges, mixed text
        # included; the whitespace between two pieces of content parses as before.
        nodes = html_to_ast('<table><tr><td>\n  A\n  <img src="u">\n  <b>B</b>\n</td></tr></table>')
        assert self._linked_text(nodes[0].rows[0].cells[0]) == [
            ("A\n  ", None),
            ("Image", "-"),
            ("\n  B", None),
        ]

    async def test_text_before_a_nested_table_loses_its_indentation_edges(self):
        # PR #1215 QA round 3: a mixed chunk's newline-led edges, next to a nested
        # table, still became empty paragraphs.
        nodes = html_to_ast(
            "<table><tr><td>\n  Intro text\n  <table><tr><td>i</td></tr></table>\n"
            "</td></tr></table>"
        )
        assert self._shape(nodes[0].rows[0].cells[0]) == ["Intro text", "Table"]

    async def test_cell_block_content_and_pre_keep_their_line_breaks(self):
        # PR #1215 QA round 2: collapsing every line break merged these. A <pre>'s
        # whitespace is never trimmed, even at an edge.
        nodes = html_to_ast(
            "<table><tr><td><p>a</p>\n<p>b</p></td><td><pre>x\n  y</pre></td>"
            "<td><a href='http://u'>x\n</a>y</td><td><pre>\n  code\n</pre></td></tr></table>"
        )
        cells = nodes[0].rows[0].cells
        assert self._linked_text(cells[0]) == [("a\nb", None)]
        assert self._linked_text(cells[1]) == [("x\n  y", None)]
        assert self._linked_text(cells[2]) == [("x\n", "http://u"), ("y", None)]
        assert self._linked_text(cells[3]) == [("\n  code\n", None)]

    async def test_held_whitespace_keeps_its_link_and_style(self):
        # PR #1215 QA round 3: released held whitespace had lost the link it was
        # typed in.
        nodes = html_to_ast(
            '<table><tr><td><a href="u"><b>X</b>\n  </a><a href="v">Y</a></td></tr></table>'
        )
        runs = _runs_in(nodes[0].rows[0].cells[0])
        assert [(r.text, r.link_url, r.bold) for r in runs] == [
            ("X", "u", True),
            ("\n  ", "u", None),
            ("Y", "v", None),
        ]

    async def test_held_whitespace_does_not_leak_past_an_unclosed_cell(self):
        # The row never closes, so the table has no rows and emits no node.
        nodes = html_to_ast("<table><tr><td>a\n</table><p>x<b>y</b></p>")
        assert [r.text for r in nodes[-1].runs] == ["x", "y"]

    async def test_br_and_plain_spaces_in_a_cell_are_kept(self):
        nodes = html_to_ast(
            "<table><tr><td>a<br>b</td><td>Some label <table><tr><td>i</td></tr></table>"
            "</td></tr></table>"
        )
        cells = nodes[0].rows[0].cells
        assert "".join(r.text for r in _runs_in(cells[0])) == "a\nb"
        assert self._shape(cells[1]) == ["Some label ", "Table"]


class _ImageFetchError(Exception):
    """Stands in for the Docs API's 400 naming requests[index].insertInlineImage."""

    def __init__(self, index: int):
        super().__init__(f"requests[{index}].insertInlineImage")
        self.index = index


class TestCellImageFill:
    """Drive fill_tables against FakeDoc, which shows an inserted image as IMG. Each
    batch's first insertInlineImage whose uri is in `bad` fails it, as the live API
    names only one failing image per error."""

    async def _run(
        self,
        ast_tables: list[Table],
        uris: dict[int, str],
        bad: frozenset[str] = frozenset(),
        doc: FakeDoc | None = None,
    ) -> tuple[FakeDoc, list[list[dict]], CellImages, list[Image]]:
        if doc is None:
            doc = FakeDoc()
            content: list = [Para("")]
            for t in ast_tables:
                content += [TableNode(len(t.rows), len(t.rows[0].cells)), Para("")]
            doc.content = content

        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = lambda **_kwargs: (
            doc.get()
        )

        def do_batch(documentId, body):
            doc.batch_update(body["requests"])
            m = MagicMock()
            m.execute.return_value = {}
            return m

        svc.documents.return_value.batchUpdate.side_effect = do_batch
        batches: list[list[dict]] = []
        dropped: list[Image] = []

        async def run_batch(requests: list[dict]) -> None:
            batches.append(list(requests))
            for i, r in enumerate(requests):
                if r.get("insertInlineImage", {}).get("uri") in bad:
                    raise _ImageFetchError(i)
            doc.batch_update(requests)

        images = CellImages(
            uris,
            run_batch,
            lambda e: e.index if isinstance(e, _ImageFetchError) else None,
            lambda image, _e: dropped.append(image),
        )
        await asyncio.wait_for(fill_tables(svc, "doc1", ast_tables, images), timeout=5)
        return doc, batches, images, dropped

    @staticmethod
    def _cell_texts(doc: FakeDoc, table_index: int, row: int, col: int) -> list[str]:
        cell = doc.content[table_index].rows[row][col]
        return [c.text if isinstance(c, Para) else "Table" for c in cell.content]

    async def test_image_only_cell_is_filled(self):
        img = Image(src="https://a/b.png")
        table = _table(_row(_cell("Before"), Cell(children=[img]), _cell("After")))
        doc, _batches, images, _ = await self._run([table], {id(img): "https://a/b.png"})
        assert self._cell_texts(doc, 1, 0, 0) == ["Before"]
        assert self._cell_texts(doc, 1, 0, 1) == [IMG]
        assert self._cell_texts(doc, 1, 0, 2) == ["After"]
        assert images.embedded == {id(img)}

    async def test_image_between_text_and_adjacent_images_keep_order(self):
        a, b, c = Image(src="a"), Image(src="b"), Image(src="c")
        cell = Cell(children=[Run("x"), a, Run("yy"), b, c, Run("z")])
        doc, batches, images, _ = await self._run(
            [_table(_row(cell))], {id(a): "uri-a", id(b): "uri-b", id(c): "uri-c"}
        )
        assert self._cell_texts(doc, 1, 0, 0) == [f"x{IMG}yy{IMG}{IMG}z"]
        inserts = [r for batch in batches for r in batch if "insertInlineImage" in r]
        # Latest first: c and b share an offset, so c goes in before b.
        assert [r["insertInlineImage"]["uri"] for r in inserts] == ["uri-c", "uri-b", "uri-a"]
        assert images.embedded == {id(a), id(b), id(c)}

    async def test_unresolved_image_written_as_fallback_text(self):
        # #1099: an image that never resolved shows its alt text (here, with no alt,
        # its source's name) instead of leaving no trace.
        img = Image(src="a")
        doc, batches, images, _ = await self._run(
            [_table(_row(Cell(children=[Run("t"), img])))], {}
        )
        assert self._cell_texts(doc, 1, 0, 0) == ["ta"]
        assert not any("insertInlineImage" in r for batch in batches for r in batch)
        assert images.embedded == set()
        assert images.fallbacks.shown == {id(img)}

    async def test_linked_image_link_follows_its_insert(self):
        img = Image(src="a", link_url="https://x.com")
        _doc, batches, _, _ = await self._run(
            [_table(_row(Cell(children=[img])))], {id(img): "uri-a"}
        )
        [batch] = batches
        i = next(i for i, r in enumerate(batch) if "insertInlineImage" in r)
        position = batch[i]["insertInlineImage"]["location"]["index"]
        assert batch[i + 1]["updateTextStyle"] == {
            "range": {"startIndex": position, "endIndex": position + 1},
            "textStyle": {"link": {"url": "https://x.com"}},
            "fields": "link",
        }

    async def test_unfetchable_linked_image_replaced_by_linked_fallback_text(self):
        # #1099: the image's insert and its one-character link go; its fallback text
        # takes its place, linked over the text's whole range.
        good, bad = Image(src="g"), Image(src="b", link_url="https://x.com")
        cell = Cell(children=[Run("t"), bad, good])
        doc, batches, images, dropped = await self._run(
            [_table(_row(cell))],
            {id(good): "uri-g", id(bad): "uri-bad"},
            bad=frozenset({"uri-bad"}),
        )
        assert self._cell_texts(doc, 1, 0, 0) == [f"tb{IMG}"]
        assert dropped == [bad]
        assert images.embedded == {id(good)}
        assert images.fallbacks.shown == {id(bad)}
        assert id(bad) not in images.uris
        retry = batches[-1]
        i = next(i for i, r in enumerate(retry) if r.get("insertText", {}).get("text") == "b")
        position = retry[i]["insertText"]["location"]["index"]
        assert retry[i + 1]["updateTextStyle"] == {
            "range": {"startIndex": position, "endIndex": position + 1},
            "textStyle": {"link": {"url": "https://x.com"}},
            "fields": "link",
        }
        assert not any("insertInlineImage" in r and "uri-bad" in str(r) for r in retry)
        links = [r for r in retry if "link" in r.get("updateTextStyle", {}).get("textStyle", {})]
        assert links == [retry[i + 1]]

    async def test_second_bad_image_splits_the_batch_at_that_image(self):
        # #510's split, for the cell batch: from the second failure on, the requests
        # ahead of the failed image go on their own and only the rest is retried. The
        # batch runs latest cell first, so the split keeps each cell's text ahead of
        # every earlier cell's.
        a, b, c = Image(src="a"), Image(src="b"), Image(src="c")
        table = _table(
            _row(Cell(children=[Run("one"), a]), Cell(children=[Run("two"), b])),
            _row(Cell(children=[Run("three"), c]), _cell("four")),
        )
        doc, batches, images, dropped = await self._run(
            [table],
            {id(a): "uri-a", id(b): "uri-b", id(c): "uri-c"},
            bad=frozenset({"uri-b", "uri-c"}),
        )
        full, retry, head, tail = batches

        def fallback_at(batch: list[dict], text: str) -> int:
            return next(
                i for i, r in enumerate(batch) if r.get("insertText", {}).get("text") == text
            )

        # Each failed image's insert is replaced in place by its fallback text and
        # that text's link-clearing request (#1099).
        c_index = next(
            i for i, r in enumerate(full) if r.get("insertInlineImage", {}).get("uri") == "uri-c"
        )
        assert fallback_at(retry, "c") == c_index
        assert retry[:c_index] + retry[c_index + 2 :] == full[:c_index] + full[c_index + 1 :]
        b_index = next(
            i for i, r in enumerate(retry) if r.get("insertInlineImage", {}).get("uri") == "uri-b"
        )
        # The split is at b, the second failure: its fallback text heads the tail.
        assert head == retry[:b_index]
        assert tail[0] == {
            "insertText": {"location": retry[b_index]["insertInlineImage"]["location"], "text": "b"}
        }
        assert tail[2:] == retry[b_index + 1 :]
        assert not any("insertInlineImage" in r for r in head)
        assert dropped == [c, b]
        assert images.embedded == {id(a)}
        assert images.fallbacks.shown == {id(b), id(c)}
        assert self._cell_texts(doc, 1, 0, 0) == [f"one{IMG}"]
        assert self._cell_texts(doc, 1, 0, 1) == ["twob"]
        assert self._cell_texts(doc, 1, 1, 0) == ["threec"]
        assert self._cell_texts(doc, 1, 1, 1) == ["four"]

    async def test_error_naming_a_non_image_request_raises(self):
        img = Image(src="a")
        table = _table(_row(Cell(children=[Run("t"), img])))
        doc = FakeDoc()
        doc.content = [Para(""), TableNode(1, 1), Para("")]

        async def run_batch(requests: list[dict]) -> None:
            raise _ImageFetchError(0)  # requests[0] is the insertText

        images = CellImages({id(img): "uri-a"}, run_batch, lambda e: e.index, lambda *_: None)
        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = lambda **_kwargs: (
            doc.get()
        )
        with pytest.raises(_ImageFetchError):
            await fill_tables(svc, "doc1", [table], images)

    async def test_retry_bookkeeping_is_per_batch(self):
        # PR #1215 QA round 1: an insert dict freed after its batch could have its id()
        # reused by a later batch's insert, so a stale map entry (a link from the
        # earlier batch) was found for it. The maps now hold their requests and are
        # cleared once each batch settles.
        linked, later = Image(src="l", link_url="https://x.com"), Image(src="u")
        inner = _table(_row(Cell(children=[later])))
        cell = Cell(children=[linked, inner])
        _doc, _batches, images, dropped = await self._run(
            [_table(_row(cell))],
            {id(linked): "uri-l", id(later): "uri-bad"},
            bad=frozenset({"uri-bad"}),
        )
        assert images._pending == {}
        assert dropped == [later]
        assert images.embedded == {id(linked)}

    async def test_image_before_nested_table_shifts_the_table(self):
        # The nested table lands after the text *and* the image in its paragraph.
        img = Image(src="a")
        img2 = Image(src="a")
        inner = _table(_row(_cell("inner")))
        cell = Cell(children=[Run("Lead "), img, inner, Run("tail"), img2])
        doc, _batches, _, _ = await self._run(
            [_table(_row(cell))], {id(img): "uri-a", id(img2): "uri-a"}
        )
        assert self._cell_texts(doc, 1, 0, 0) == [f"Lead {IMG}", "Table", f"tail{IMG}"]

    async def test_dropped_image_counted_as_its_fallback_text_before_nested_table(self):
        # A dropped image isn't in the doc, but its fallback text is (#1099), so the
        # nested table after it lands past that text, not one index past "Lead".
        img = Image(src="a", alt="alt text")
        inner = _table(_row(_cell("inner")))
        cell = Cell(children=[Run("Lead"), img, inner])
        doc, _batches, _images, dropped = await self._run(
            [_table(_row(cell))], {id(img): "uri-bad"}, bad=frozenset({"uri-bad"})
        )
        assert dropped == [img]
        assert self._cell_texts(doc, 1, 0, 0) == ["Leadalt text", "Table", ""]
        nested = doc.content[1].rows[0][0].content[1]
        assert nested.rows[0][0].content[0].text == "inner"

    async def test_image_in_nested_table_cell(self):
        img = Image(src="a")
        inner = _table(_row(Cell(children=[img, Run(" logo")])))
        doc, _batches, images, _ = await self._run(
            [_table(_row(Cell(children=[inner])))], {id(img): "uri-a"}
        )
        outer_cell = doc.content[1].rows[0][0]
        nested = next(c for c in outer_cell.content if isinstance(c, TableNode))
        assert nested.rows[0][0].content[0].text == f"{IMG} logo"
        assert images.embedded == {id(img)}

    async def test_image_in_a_cell_the_fill_skips_is_not_embedded(self):
        # A cell missing from the live doc gets no insert; the caller reports it.
        img = Image(src="a")
        table = _table(_row(Cell(children=[img])))
        doc = FakeDoc()
        doc.content = [Para(""), TableNode(1, 1), Para("")]
        doc.content[1].rows[0][0].content = []
        _doc, batches, images, _ = await self._run([table], {id(img): "uri-a"}, doc=doc)
        assert batches == []
        assert images.embedded == set()
