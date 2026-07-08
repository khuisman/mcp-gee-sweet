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
    _ast_cell_to_doc_cell,
    _cell_para_start_for_cursor,
    _fill_nested_cell_content,
    _find_nth_table_in_cell,
    _text_offset_since_last_table,
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
    return Cell(children=[Run(text)], colspan=colspan, rowspan=rowspan)


def _row(*cells: Cell) -> Row:
    return Row(cells=list(cells))


def _table(*rows: Row) -> Table:
    return Table(rows=list(rows))


def _tables_in(cell: Cell) -> list[Table]:
    return [child for child in cell.children if isinstance(child, Table)]


def _runs_in(cell: Cell) -> list[Run]:
    return [child for child in cell.children if isinstance(child, Run)]


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
        tables = _tables_in(cell)
        assert len(tables) == 1

    def test_nested_cell_text_correct(self):
        nodes = html_to_ast(_nested_html())
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert _runs_in(inner.rows[0].cells[0])[0].text == "inner"

    def test_outer_cell_has_only_the_nested_table_when_no_surrounding_text(self):
        nodes = html_to_ast(_nested_html())
        cell = nodes[0].rows[0].cells[0]
        assert _runs_in(cell) == []
        assert len(cell.children) == 1

    def test_nested_table_multiple_rows(self):
        nodes = html_to_ast(_nested_html("<tr><td>R0</td></tr><tr><td>R1</td></tr>"))
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert len(inner.rows) == 2
        assert _runs_in(inner.rows[0].cells[0])[0].text == "R0"
        assert _runs_in(inner.rows[1].cells[0])[0].text == "R1"

    def test_nested_table_multiple_cols(self):
        nodes = html_to_ast(_nested_html("<tr><td>A</td><td>B</td></tr>"))
        inner = _tables_in(nodes[0].rows[0].cells[0])[0]
        assert len(inner.rows[0].cells) == 2
        assert _runs_in(inner.rows[0].cells[1])[0].text == "B"

    def test_non_nested_cell_has_no_table_child(self):
        nodes = html_to_ast("<table><tr><td>plain</td></tr></table>")
        assert _tables_in(nodes[0].rows[0].cells[0]) == []

    def test_sibling_cell_text_preserved(self):
        # Col 0 has nested table; col 1 has plain text
        nodes = html_to_ast(
            "<table><tr><td><table><tr><td>inner</td></tr></table></td><td>plain</td></tr></table>"
        )
        outer = nodes[0]
        assert _tables_in(outer.rows[0].cells[0]) != []
        assert _runs_in(outer.rows[0].cells[1])[0].text == "plain"

    def test_table_depth_resets_to_zero(self):
        from mcp_gee_sweet.tools.docs.html_parser import _AstParser

        parser = _AstParser()
        parser.feed(_nested_html())
        assert parser._table_depth == 0
        assert parser._table_stack == []

    # -- issue #108/#275: text sharing a cell with a nested table must not be
    # dropped, and must stay in true source order relative to the table(s) --

    def test_leading_text_stays_with_outer_cell(self):
        # Exact reproduction from #108: text before the nested <table> used to
        # bleed into the nested table's own first cell instead of staying put.
        nodes = html_to_ast(
            "<table><tr><td>Some label <table><tr><td>inner</td></tr></table></td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        assert outer.children[0].text == "Some label "
        assert isinstance(outer.children[1], Table)
        assert _runs_in(outer.children[1].rows[0].cells[0])[0].text == "inner"

    def test_trailing_text_stays_with_outer_cell(self):
        # Text after the nested table already worked before the fix — guard
        # against a regression while touching this code path.
        nodes = html_to_ast(
            "<table><tr><td><table><tr><td>inner</td></tr></table>After</td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        assert isinstance(outer.children[0], Table)
        assert outer.children[1].text == "After"

    def test_leading_text_formatting_preserved(self):
        nodes = html_to_ast(
            "<table><tr><td>Some <b>bold</b> label "
            "<table><tr><td>inner</td></tr></table></td></tr></table>"
        )
        outer = nodes[0].rows[0].cells[0]
        leading_runs = _runs_in(outer)
        texts_and_bold = [(r.text, r.bold) for r in leading_runs]
        assert texts_and_bold == [("Some ", None), ("bold", True), (" label ", None)]

    def test_leading_and_trailing_text_in_true_order(self):
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

    def test_multiple_nested_tables_with_text_between(self):
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
    def test_single_cell_matches(self):
        ast_table = _table(_row(_cell("x")))
        doc_cell = {"startIndex": 9, "content": [_para_elem(10)]}
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        assert _ast_cell_to_doc_cell(doc_table, ast_table, r=0, ast_col=0) is doc_cell

    def test_second_column_matches_by_position(self):
        ast_table = _table(_row(_cell("a"), _cell("b")))
        doc_cell_a = {"startIndex": 9, "content": [_para_elem(10)]}
        doc_cell_b = {"startIndex": 19, "content": [_para_elem(20)]}
        doc_table = {"tableRows": [{"tableCells": [doc_cell_a, doc_cell_b]}]}
        assert _ast_cell_to_doc_cell(doc_table, ast_table, r=0, ast_col=1) is doc_cell_b

    def test_row_out_of_range_returns_none(self):
        ast_table = _table(_row(_cell("x")))
        doc_table = {"tableRows": []}
        assert _ast_cell_to_doc_cell(doc_table, ast_table, r=0, ast_col=0) is None


class TestCellParaStartForCursor:
    def test_cursor_zero_returns_first_paragraph(self):
        ast_cell = Cell(children=[Run("x")])
        doc_cell = {"content": [_para_elem(10)]}
        assert _cell_para_start_for_cursor(doc_cell, ast_cell, cursor=0) == 10

    def test_after_one_table_returns_second_paragraph(self):
        inner = _table(_row(_cell("x")))
        ast_cell = Cell(children=[inner, Run("After")])
        doc_cell = {
            "content": [_para_elem(10), _table_content_elem({"tableRows": []}), _para_elem(20)]
        }
        assert _cell_para_start_for_cursor(doc_cell, ast_cell, cursor=1) == 20

    def test_missing_paragraph_returns_none(self):
        inner = _table(_row(_cell("x")))
        ast_cell = Cell(children=[inner, Run("After")])
        doc_cell = {"content": [_para_elem(10)]}  # no paragraph after the table yet
        assert _cell_para_start_for_cursor(doc_cell, ast_cell, cursor=1) is None


class TestTextOffsetSinceLastTable:
    def test_no_preceding_children_is_zero(self):
        assert _text_offset_since_last_table([Run("x")], cursor=0) == 0

    def test_sums_runs_since_start(self):
        children = [Run("AB"), Run("CDE")]
        assert _text_offset_since_last_table(children, cursor=2) == 5

    def test_stops_at_nearest_preceding_table(self):
        inner = _table(_row(_cell("x")))
        children = [Run("AB"), inner, Run("CDE")]
        assert _text_offset_since_last_table(children, cursor=3) == 3

    def test_zero_for_a_table_immediately_after_another_table(self):
        t1 = _table(_row(_cell("x")))
        t2 = _table(_row(_cell("y")))
        children = [t1, t2]
        assert _text_offset_since_last_table(children, cursor=1) == 0


class TestFindNthTableInCell:
    def test_finds_only_table(self):
        ast_table = _table(_row(_cell("x")))
        nested_doc_table = {"tableRows": [{"tableCells": [{"content": [_para_elem(30)]}]}]}
        doc_cell = {
            "startIndex": 9,
            "content": [_para_elem(10), _table_content_elem(nested_doc_table)],
        }
        doc_table = {"tableRows": [{"tableCells": [doc_cell]}]}
        result = _find_nth_table_in_cell(doc_table, ast_table, r=0, c=0, occurrence=0)
        assert result is nested_doc_table

    def test_second_occurrence_found(self):
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

    def test_occurrence_not_found_returns_none(self):
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
            for i, (obj, dict_elem) in enumerate(zip(objs, dict_elems)):
                if isinstance(obj, Para):
                    if dict_elem["startIndex"] <= index <= dict_elem["endIndex"]:
                        return obj, dict_elem["startIndex"], objs, i
                else:
                    for row_obj, row_elem in zip(obj.rows, dict_elem["table"]["tableRows"]):
                        for cell_obj, cell_elem in zip(row_obj, row_elem["tableCells"]):
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
            elif "insertTable" in req:
                it = req["insertTable"]
                self.insert_table(it["location"]["index"], it["rows"], it["columns"])

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

    def _run(self, outer_cell: Cell) -> FakeDoc:
        doc = FakeDoc()
        doc.content = [TableNode(1, 1)]
        ast_table = Table(rows=[Row(cells=[outer_cell])])

        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = lambda: doc.get()

        def do_batch(documentId, body):
            doc.batch_update(body["requests"])
            m = MagicMock()
            m.execute.return_value = {}
            return m

        svc.documents.return_value.batchUpdate.side_effect = do_batch
        _fill_nested_cell_content(svc, "doc1", [ast_table])
        return doc

    def test_leading_text_only(self):
        # children = [Run("Some label "), Table(inner)] — issue #108's exact repro.
        inner = _table(_row(_cell("inner")))
        doc = self._run(Cell(children=[Run("Some label "), inner]))
        assert doc.describe_cell(0, 0, 0) == ["Para:Some label ", "Table"]

    def test_trailing_text_only_regression_guard(self):
        inner = _table(_row(_cell("inner")))
        doc = self._run(Cell(children=[inner, Run("After")]))
        assert doc.describe_cell(0, 0, 0) == ["Table", "Para:After"]

    def test_leading_and_trailing_text_around_one_table(self):
        # Issue #275's exact repro: text before AND after one nested table must
        # land on the correct side of it, not both merge before the table.
        inner = _table(_row(_cell("Inner")))
        doc = self._run(Cell(children=[Run("Before "), inner, Run(" After")]))
        assert doc.describe_cell(0, 0, 0) == ["Para:Before ", "Table", "Para: After"]

    def test_two_nested_tables_with_text_between(self):
        # General case: multiple nested tables in one cell, with text
        # interleaved — validates the fully general children ordering.
        t1 = _table(_row(_cell("1")))
        t2 = _table(_row(_cell("2")))
        doc = self._run(Cell(children=[Run("A"), t1, Run("B"), t2, Run("C")]))
        assert doc.describe_cell(0, 0, 0) == [
            "Para:A",
            "Table",
            "Para:B",
            "Table",
            "Para:C",
        ]

    def test_nested_tables_own_text_is_filled(self):
        # A nested table's own plain cells must be filled too — not just its
        # shell inserted (a regression this exact test class caught once).
        inner = _table(_row(_cell("Inner")))
        doc = self._run(Cell(children=[Run("Before "), inner, Run(" After")]))
        outer_table = doc.content[0]
        outer_cell = outer_table.rows[0][0]
        nested_table = next(c for c in outer_cell.content if isinstance(c, TableNode))
        nested_cell = nested_table.rows[0][0]
        assert [
            f"Para:{c.text}" if isinstance(c, Para) else "Table" for c in nested_cell.content
        ] == ["Para:Inner"]

    def test_deeply_nested_mixed_content_at_every_level(self):
        # A nested table's own cell may itself contain a further nested table,
        # with text on both sides, at any depth.
        deep = _table(_row(_cell("deep")))
        mid = _table(_row(Cell(children=[Run("mid-before "), deep, Run(" mid-after")])))
        doc = self._run(Cell(children=[Run("outer-before "), mid, Run(" outer-after")]))
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

    def test_plain_cells_produce_no_calls(self):
        ast_table = _table(_row(_cell("plain")))
        svc = MagicMock()
        _fill_nested_cell_content(svc, "doc1", [ast_table])
        svc.documents.return_value.get.assert_not_called()
        svc.documents.return_value.batchUpdate.assert_not_called()

    def test_degenerate_zero_column_table_does_not_abandon_trailing_content(self):
        # A table with a row but no cells has num_cols == 0, so the
        # `num_rows > 0 and num_cols > 0` guard skips its insertTable request —
        # that round then has no requests at all. The loop must not treat an
        # empty round as "done": trailing content after the skipped table still
        # needs to be processed, not silently abandoned.
        degenerate = Table(rows=[Row(cells=[])])
        doc = self._run(Cell(children=[degenerate, Run("After")]))
        assert doc.describe_cell(0, 0, 0) == ["Para:After"]
