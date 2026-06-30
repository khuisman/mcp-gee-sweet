"""Tests for docs table tools and nested table emitter."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs.ast import (
    Cell,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.content import _html_to_doc_requests
from mcp_gee_sweet.tools.docs.emitter import (
    _build_nested_table_inserts,
    _collect_nested_table_pairs,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast


def _make_tool_registry():
    captured = {}

    def tool(annotations=None):
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
    return Cell(runs=[Run(text)], colspan=colspan, rowspan=rowspan)


def _row(*cells: Cell) -> Row:
    return Row(cells=list(cells))


def _table(*rows: Row) -> Table:
    return Table(rows=list(rows))


# ---------------------------------------------------------------------------
# Table structural ops (#146)
# ---------------------------------------------------------------------------


class TestInsertTableRow:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def test_insert_below_default(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_table_row"](
            doc_id="doc1", table_start_index=5, row_index=1, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "row_index": 1}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertTableRow"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["rowIndex"] == 1
        assert req["tableCellLocation"]["columnIndex"] == 0
        assert req["insertBelow"] is True

    def test_insert_above(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_table_row"](
            doc_id="doc1", table_start_index=5, row_index=0, insert_below=False, ctx=ctx
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["insertTableRow"]["insertBelow"] is False

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_table_row"](
            doc_id="doc1", table_start_index=5, row_index=0, ctx=ctx
        )
        assert "error" in result


class TestDeleteTableRow:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def test_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["delete_table_row"](
            doc_id="doc1", table_start_index=5, row_index=2, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "row_index": 2}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["deleteTableRow"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["rowIndex"] == 2
        assert req["tableCellLocation"]["columnIndex"] == 0

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["delete_table_row"](
            doc_id="doc1", table_start_index=5, row_index=0, ctx=ctx
        )
        assert "error" in result


class TestInsertTableColumn:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def test_insert_right_default(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_table_column"](
            doc_id="doc1", table_start_index=5, column_index=1, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "column_index": 1}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertTableColumn"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["columnIndex"] == 1
        assert req["tableCellLocation"]["rowIndex"] == 0
        assert req["insertRight"] is True

    def test_insert_left(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_table_column"](
            doc_id="doc1", table_start_index=5, column_index=0, insert_right=False, ctx=ctx
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["insertTableColumn"]["insertRight"] is False

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_table_column"](
            doc_id="doc1", table_start_index=5, column_index=0, ctx=ctx
        )
        assert "error" in result


class TestDeleteTableColumn:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def test_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["delete_table_column"](
            doc_id="doc1", table_start_index=5, column_index=2, ctx=ctx
        )
        assert result == {"docId": "doc1", "table_start_index": 5, "column_index": 2}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["deleteTableColumn"]
        assert req["tableCellLocation"]["tableStartLocation"]["index"] == 5
        assert req["tableCellLocation"]["columnIndex"] == 2
        assert req["tableCellLocation"]["rowIndex"] == 0

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["delete_table_column"](
            doc_id="doc1", table_start_index=5, column_index=0, ctx=ctx
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# Nested table — parser
# ---------------------------------------------------------------------------


def _nested_html(inner_rows: str = "<tr><td>inner</td></tr>") -> str:
    return f"<table><tr><td><table>{inner_rows}</table></td></tr></table>"


class TestNestedTableParser:
    def test_simple_nested_table_parsed(self):
        nodes = html_to_ast(_nested_html())
        assert len(nodes) == 1
        outer = nodes[0]
        assert isinstance(outer, Table)
        cell = outer.rows[0].cells[0]
        assert cell.nested_table is not None
        assert isinstance(cell.nested_table, Table)

    def test_nested_cell_text_correct(self):
        nodes = html_to_ast(_nested_html())
        inner = nodes[0].rows[0].cells[0].nested_table
        assert inner.rows[0].cells[0].runs[0].text == "inner"

    def test_outer_cell_runs_empty_when_only_nested(self):
        nodes = html_to_ast(_nested_html())
        cell = nodes[0].rows[0].cells[0]
        assert cell.runs == []

    def test_nested_table_multiple_rows(self):
        nodes = html_to_ast(_nested_html("<tr><td>R0</td></tr><tr><td>R1</td></tr>"))
        inner = nodes[0].rows[0].cells[0].nested_table
        assert len(inner.rows) == 2
        assert inner.rows[0].cells[0].runs[0].text == "R0"
        assert inner.rows[1].cells[0].runs[0].text == "R1"

    def test_nested_table_multiple_cols(self):
        nodes = html_to_ast(_nested_html("<tr><td>A</td><td>B</td></tr>"))
        inner = nodes[0].rows[0].cells[0].nested_table
        assert len(inner.rows[0].cells) == 2
        assert inner.rows[0].cells[1].runs[0].text == "B"

    def test_non_nested_cell_has_none(self):
        nodes = html_to_ast("<table><tr><td>plain</td></tr></table>")
        assert nodes[0].rows[0].cells[0].nested_table is None

    def test_sibling_cell_text_preserved(self):
        # Col 0 has nested table; col 1 has plain text
        nodes = html_to_ast(
            "<table><tr><td><table><tr><td>inner</td></tr></table></td><td>plain</td></tr></table>"
        )
        outer = nodes[0]
        assert outer.rows[0].cells[0].nested_table is not None
        assert outer.rows[0].cells[1].runs[0].text == "plain"

    def test_table_depth_resets_to_zero(self):
        from mcp_gee_sweet.tools.docs.html_parser import _AstParser

        parser = _AstParser()
        parser.feed(_nested_html())
        assert parser._table_depth == 0
        assert parser._table_stack == []


# ---------------------------------------------------------------------------
# Nested table — emitter phase-1 (ast_to_requests)
# ---------------------------------------------------------------------------


class TestNestedTableEmitter:
    def test_outer_table_emits_insert_table(self):
        requests, tables = _html_to_doc_requests(
            "<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
        )
        table_inserts = [r for r in requests if "insertTable" in r]
        # Only the OUTER table is inserted in phase 1; nested table is handled by fill_tables
        assert len(table_inserts) == 1
        assert table_inserts[0]["insertTable"]["rows"] == 1
        assert table_inserts[0]["insertTable"]["columns"] == 1

    def test_tables_list_contains_outer_with_nested_cell(self):
        _, tables = _html_to_doc_requests(
            "<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
        )
        assert len(tables) == 1
        assert tables[0].rows[0].cells[0].nested_table is not None


# ---------------------------------------------------------------------------
# Nested table — _build_nested_table_inserts
# ---------------------------------------------------------------------------


class TestBuildNestedTableInserts:
    def _doc_cell(self, para_start: int) -> dict:
        return {
            "startIndex": para_start - 1,
            "content": [{"startIndex": para_start}],
        }

    def _doc_table_with_cell(self, para_start: int) -> dict:
        return {"tableRows": [{"tableCells": [self._doc_cell(para_start)]}]}

    def test_single_nested_table_request(self):
        inner = _table(_row(_cell("x")))
        outer_cell = Cell(runs=[], nested_table=inner)
        ast_table = Table(rows=[Row(cells=[outer_cell])])
        doc_table = self._doc_table_with_cell(para_start=10)
        reqs = _build_nested_table_inserts([doc_table], [ast_table])
        assert len(reqs) == 1
        it = reqs[0]["insertTable"]
        assert it["rows"] == 1
        assert it["columns"] == 1
        assert it["location"]["index"] == 10

    def test_two_cells_sorted_high_to_low(self):
        inner = _table(_row(_cell("x")))
        ast_table = Table(
            rows=[
                Row(
                    cells=[
                        Cell(runs=[], nested_table=inner),
                        Cell(runs=[], nested_table=inner),
                    ]
                )
            ]
        )
        doc_table = {
            "tableRows": [
                {
                    "tableCells": [
                        self._doc_cell(para_start=5),
                        self._doc_cell(para_start=20),
                    ]
                }
            ]
        }
        reqs = _build_nested_table_inserts([doc_table], [ast_table])
        assert len(reqs) == 2
        # HIGH first
        assert reqs[0]["insertTable"]["location"]["index"] == 20
        assert reqs[1]["insertTable"]["location"]["index"] == 5

    def test_cell_without_nested_table_skipped(self):
        ast_table = Table(rows=[Row(cells=[_cell("plain")])])
        doc_table = self._doc_table_with_cell(para_start=10)
        reqs = _build_nested_table_inserts([doc_table], [ast_table])
        assert reqs == []

    def test_nested_table_dimensions_correct(self):
        inner = _table(_row(_cell("A"), _cell("B")), _row(_cell("C"), _cell("D")))
        ast_table = Table(rows=[Row(cells=[Cell(runs=[], nested_table=inner)])])
        doc_table = self._doc_table_with_cell(para_start=10)
        reqs = _build_nested_table_inserts([doc_table], [ast_table])
        it = reqs[0]["insertTable"]
        assert it["rows"] == 2
        assert it["columns"] == 2


# ---------------------------------------------------------------------------
# Nested table — _collect_nested_table_pairs
# ---------------------------------------------------------------------------


class TestCollectNestedTablePairs:
    def _doc_cell_with_nested(self, para_start: int, nested_table_start: int) -> dict:
        return {
            "startIndex": para_start - 1,
            "content": [
                {"startIndex": para_start},
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {
                                        "startIndex": nested_table_start,
                                        "content": [{"startIndex": nested_table_start + 1}],
                                    }
                                ]
                            }
                        ]
                    }
                },
            ],
        }

    def test_finds_nested_table_in_cell(self):
        inner_ast = _table(_row(_cell("x")))
        outer_cell = Cell(runs=[], nested_table=inner_ast)
        ast_table = Table(rows=[Row(cells=[outer_cell])])
        doc_cell = self._doc_cell_with_nested(para_start=5, nested_table_start=10)
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        n_doc, n_ast = _collect_nested_table_pairs([doc_table], [ast_table])
        assert len(n_doc) == 1
        assert len(n_ast) == 1
        assert n_ast[0] is inner_ast

    def test_cell_without_nested_returns_empty(self):
        ast_table = Table(rows=[Row(cells=[_cell("plain")])])
        doc_cell = {"startIndex": 5, "content": [{"startIndex": 6}]}
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        n_doc, n_ast = _collect_nested_table_pairs([doc_table], [ast_table])
        assert n_doc == []
        assert n_ast == []

    def test_multiple_cells_only_nested_ones_collected(self):
        inner_ast = _table(_row(_cell("x")))
        ast_table = Table(
            rows=[
                Row(
                    cells=[
                        _cell("plain"),
                        Cell(runs=[], nested_table=inner_ast),
                    ]
                )
            ]
        )
        doc_table = {
            "tableRows": [
                {
                    "tableCells": [
                        {"startIndex": 5, "content": [{"startIndex": 6}]},
                        self._doc_cell_with_nested(para_start=15, nested_table_start=20),
                    ]
                }
            ]
        }
        n_doc, n_ast = _collect_nested_table_pairs([doc_table], [ast_table])
        assert len(n_ast) == 1
        assert n_ast[0] is inner_ast
