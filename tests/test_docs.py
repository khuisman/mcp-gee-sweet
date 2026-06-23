"""Tests for docs package — HTML pipeline and tool registration."""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs import (
    _build_named_style_requests,
    _html_to_doc_requests,
    _html_to_text,
    _md_to_html,
    _read_body_styles,
    _read_named_styles,
    _to_doc_requests,
)
from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Cell,
    Heading,
    NamedBlock,
    Paragraph,
    RGBColor,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.emitter import (
    _build_cell_style_requests,
    _build_fill_requests,
    _build_merge_requests,
    _build_nested_table_inserts,
    _build_phantom_set,
    _collect_nested_table_pairs,
    _physical_to_ast_indices,
    _run_style_requests,
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


class TestHtmlToText:
    def test_plain_paragraph(self):
        assert _html_to_text("<p>Hello world</p>") == "Hello world"

    def test_multiple_paragraphs(self):
        result = _html_to_text("<p>First</p><p>Second</p>")
        assert "First" in result
        assert "Second" in result
        assert result.index("First") < result.index("Second")

    def test_line_break(self):
        result = _html_to_text("Line one<br>Line two")
        assert "\n" in result

    def test_strips_tags(self):
        result = _html_to_text("<h1>Title</h1><p>Body</p>")
        assert "<h1>" not in result
        assert "Title" in result
        assert "Body" in result

    def test_html_entities(self):
        assert "&amp;" not in _html_to_text("<p>fish &amp; chips</p>")
        assert "fish & chips" in _html_to_text("<p>fish &amp; chips</p>")

    def test_numeric_html_entity(self):
        result = _html_to_text("<p>&#169;</p>")
        assert "©" in result

    def test_empty_input(self):
        assert _html_to_text("") == ""

    def test_plain_text_passthrough(self):
        assert _html_to_text("just text") == "just text"


class TestHtmlToDocRequests:
    def test_empty_input_returns_empty(self):
        requests, tables = _html_to_doc_requests("")
        assert requests == []
        assert tables == []

    def test_paragraph_produces_insert_text(self):
        requests, _ = _html_to_doc_requests("<p>Hello</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert "Hello" in insert["insertText"]["text"]

    def test_h1_produces_heading_1(self):
        requests, _ = _html_to_doc_requests("<h1>Title</h1>")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in styles

    def test_h2_produces_heading_2(self):
        requests, _ = _html_to_doc_requests("<h2>Subtitle</h2>")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_2" in styles

    def test_list_item_produces_bullet(self):
        requests, _ = _html_to_doc_requests("<li>Item</li>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_anchor_produces_link_style(self):
        requests, _ = _html_to_doc_requests('<p><a href="https://example.com">click</a></p>')
        links = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"].get("textStyle", {})
        ]
        assert len(links) == 1
        assert links[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://example.com"

    def test_start_index_offset(self):
        requests_default, _ = _html_to_doc_requests("<p>Hi</p>", start_index=1)
        requests_offset, _ = _html_to_doc_requests("<p>Hi</p>", start_index=10)
        default_insert = next(r for r in requests_default if "insertText" in r)
        offset_insert = next(r for r in requests_offset if "insertText" in r)
        assert offset_insert["insertText"]["location"]["index"] == 10
        assert default_insert["insertText"]["location"]["index"] == 1

    def test_indices_are_contiguous(self):
        requests, _ = _html_to_doc_requests("<p>First</p><p>Second</p>")
        insert = next(r for r in requests if "insertText" in r)
        full_text = insert["insertText"]["text"]
        assert full_text == "First\nSecond\n"

    def test_list_item_inside_ul(self):
        requests, _ = _html_to_doc_requests("<ul><li>Item one</li><li>Item two</li></ul>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 2

    def test_whitespace_only_paragraph_skipped(self):
        requests, _ = _html_to_doc_requests("<p>   </p><p>Real content</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert "Real content" in insert["insertText"]["text"]
        assert insert["insertText"]["text"].strip() == "Real content"

    def test_table_produces_insert_table_request(self):
        requests, tables = _html_to_doc_requests(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
        table_reqs = [r for r in requests if "insertTable" in r]
        assert len(table_reqs) == 1
        assert table_reqs[0]["insertTable"]["rows"] == 2
        assert table_reqs[0]["insertTable"]["columns"] == 2

    def test_table_data_returned_in_tables(self):
        _, tables = _html_to_doc_requests(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
        assert len(tables) == 1
        # tables are now Table AST nodes
        assert len(tables[0].rows) == 2
        assert tables[0].rows[0].cells[0].runs[0].text == "A"
        assert tables[0].rows[0].cells[1].runs[0].text == "B"
        assert tables[0].rows[1].cells[0].runs[0].text == "1"
        assert tables[0].rows[1].cells[1].runs[0].text == "2"

    def test_table_interleaved_with_text(self):
        html = "<h2>Before</h2><table><tr><td>X</td></tr></table><h2>After</h2>"
        requests, tables = _html_to_doc_requests(html)
        insert_texts = [r for r in requests if "insertText" in r]
        insert_tables = [r for r in requests if "insertTable" in r]
        # All text ("Before\nAfter\n") in one insertText; table inserted between them
        assert len(insert_texts) == 1
        assert len(insert_tables) == 1
        all_text = insert_texts[0]["insertText"]["text"]
        assert "Before" in all_text and "After" in all_text
        # Table position is between the two text segments (after "Before\n" = 7 chars)
        text_start = insert_texts[0]["insertText"]["location"]["index"]
        table_idx = insert_tables[0]["insertTable"]["location"]["index"]
        assert text_start <= table_idx <= text_start + len("Before\n")

    def test_heading_gets_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<h1>Title</h1>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert has_delete

    def test_paragraph_gets_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<p>Body</p>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert has_delete

    def test_li_does_not_get_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<li>Item</li>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert not has_delete

    def test_table_no_cell_inserttext_in_requests(self):
        requests, _ = _html_to_doc_requests("<table><tr><td>hello</td></tr></table>")
        # Cell content must NOT appear in this batch — it goes in a second phase
        cell_inserts = [
            r for r in requests if "insertText" in r and "hello" in r["insertText"].get("text", "")
        ]
        assert cell_inserts == []

    def test_adjacent_tables_order_preserved(self):
        html = "<table><tr><td>T1</td></tr></table><table><tr><td>T2</td></tr></table>"
        requests, tables = _html_to_doc_requests(html)
        insert_tables = [r for r in requests if "insertTable" in r]
        assert len(insert_tables) == 2
        assert len(tables) == 2
        assert tables[0].rows[0].cells[0].runs[0].text == "T1"
        assert tables[1].rows[0].cells[0].runs[0].text == "T2"
        # Both tables share the same insert position (no text between them).
        # Reverse-order insertion means T1 ends up at a lower index than T2 in the doc,
        # so T1's position must be <= T2's position in the request list (last request = T1).
        t1_req = insert_tables[-1]  # inserted last → lands first in doc
        t2_req = insert_tables[-2]  # inserted first → lands second in doc
        assert (
            t1_req["insertTable"]["location"]["index"] <= t2_req["insertTable"]["location"]["index"]
        )


class TestHtmlToAst:
    """Tests for the AST layer — html_to_ast and the nodes it produces."""

    def test_h1_to_h6_correct_levels(self):
        for level in range(1, 7):
            nodes = html_to_ast(f"<h{level}>Title</h{level}>")
            assert len(nodes) == 1
            assert isinstance(nodes[0], Heading)
            assert nodes[0].level == level

    def test_paragraph_node(self):
        nodes = html_to_ast("<p>Hello</p>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)
        assert nodes[0].runs[0].text == "Hello"

    def test_bullet_item_from_ul(self):
        nodes = html_to_ast("<ul><li>Item</li></ul>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert len(bullets) == 1
        assert bullets[0].ordered is False

    def test_bullet_item_from_ol(self):
        nodes = html_to_ast("<ol><li>Item</li></ol>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert len(bullets) == 1
        assert bullets[0].ordered is True

    def test_inline_bold_in_paragraph(self):
        nodes = html_to_ast("<p><b>bold</b> plain</p>")
        assert isinstance(nodes[0], Paragraph)
        runs = nodes[0].runs
        bold_run = next(r for r in runs if r.bold)
        assert bold_run.text == "bold"
        plain_run = next(r for r in runs if not r.bold)
        assert "plain" in plain_run.text

    def test_inline_italic_in_paragraph(self):
        nodes = html_to_ast("<p><i>italic</i></p>")
        assert nodes[0].runs[0].italic is True

    def test_inline_link_in_paragraph(self):
        nodes = html_to_ast('<p><a href="https://example.com">click</a></p>')
        link_run = next(r for r in nodes[0].runs if r.link_url)
        assert link_run.link_url == "https://example.com"

    def test_th_cell_has_bold_run(self):
        nodes = html_to_ast("<table><tr><th>Header</th></tr></table>")
        table = nodes[0]
        assert isinstance(table, Table)
        cell = table.rows[0].cells[0]
        assert cell.is_header is True
        assert cell.runs[0].bold is True

    def test_td_cell_text(self):
        nodes = html_to_ast("<table><tr><td>Data</td></tr></table>")
        table = nodes[0]
        cell = table.rows[0].cells[0]
        assert cell.is_header is False
        assert cell.runs[0].text == "Data"

    def test_inline_bold_in_td(self):
        nodes = html_to_ast("<table><tr><td><b>bold cell</b></td></tr></table>")
        cell = nodes[0].rows[0].cells[0]
        assert cell.runs[0].bold is True
        assert cell.runs[0].text == "bold cell"

    def test_inline_link_in_td(self):
        nodes = html_to_ast('<table><tr><td><a href="https://x.com">link</a></td></tr></table>')
        cell = nodes[0].rows[0].cells[0]
        link_run = next(r for r in cell.runs if r.link_url)
        assert link_run.link_url == "https://x.com"

    def test_colspan_on_td(self):
        nodes = html_to_ast('<table><tr><td colspan="2">wide</td></tr></table>')
        cell = nodes[0].rows[0].cells[0]
        assert cell.colspan == 2

    def test_default_colspan_is_1(self):
        nodes = html_to_ast("<table><tr><td>x</td></tr></table>")
        assert nodes[0].rows[0].cells[0].colspan == 1

    def test_col_width_parsed_from_col_tag(self):
        # 96px → 72pt (96 * 72 / 96 = 72)
        nodes = html_to_ast('<table><col width="96"><tr><td>x</td></tr></table>')
        assert isinstance(nodes[0], Table)
        widths = nodes[0].col_widths
        assert len(widths) == 1
        assert widths[0] == pytest.approx(72.0)

    def test_col_width_parsed_from_td_first_row(self):
        nodes = html_to_ast('<table><tr><td width="96">x</td></tr></table>')
        assert isinstance(nodes[0], Table)
        widths = nodes[0].col_widths
        assert len(widths) == 1
        assert widths[0] == pytest.approx(72.0)

    def test_h3_to_h6_correct_heading_levels_in_requests(self):
        for level in range(3, 7):
            requests, _ = _html_to_doc_requests(f"<h{level}>Title</h{level}>")
            styles = [
                r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
                for r in requests
                if "updateParagraphStyle" in r
            ]
            assert f"HEADING_{level}" in styles

    def test_rowspan_on_td(self):
        nodes = html_to_ast(
            '<table><tr><td rowspan="2">x</td><td>y</td></tr><tr><td>z</td></tr></table>'
        )
        cell = nodes[0].rows[0].cells[0]
        assert cell.rowspan == 2

    def test_default_rowspan_is_1(self):
        nodes = html_to_ast("<table><tr><td>x</td></tr></table>")
        assert nodes[0].rows[0].cells[0].rowspan == 1

    def test_data_style_title(self):
        nodes = html_to_ast('<p data-style="title">My Title</p>')
        assert len(nodes) == 1
        assert isinstance(nodes[0], NamedBlock)
        assert nodes[0].style_type == "TITLE"
        assert nodes[0].runs[0].text == "My Title"

    def test_data_style_subtitle(self):
        nodes = html_to_ast('<p data-style="subtitle">Sub</p>')
        assert isinstance(nodes[0], NamedBlock)
        assert nodes[0].style_type == "SUBTITLE"

    def test_p_no_data_style_is_paragraph(self):
        nodes = html_to_ast("<p>Normal</p>")
        assert isinstance(nodes[0], Paragraph)

    def test_data_style_unknown_is_paragraph(self):
        nodes = html_to_ast('<p data-style="bogus">X</p>')
        assert isinstance(nodes[0], Paragraph)

    def test_data_style_case_insensitive(self):
        nodes = html_to_ast('<p data-style="TITLE">T</p>')
        assert isinstance(nodes[0], NamedBlock)
        assert nodes[0].style_type == "TITLE"


class TestNamedBlockEmitter:
    def test_title_emits_named_style_type(self):
        requests, _ = _html_to_doc_requests('<p data-style="title">My Title</p>')
        para_styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "TITLE" in para_styles

    def test_subtitle_emits_named_style_type(self):
        requests, _ = _html_to_doc_requests('<p data-style="subtitle">Sub</p>')
        para_styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "SUBTITLE" in para_styles

    def test_named_block_does_not_produce_bullet(self):
        requests, _ = _html_to_doc_requests('<p data-style="title">T</p>')
        assert not any("createParagraphBullets" in r for r in requests)

    def test_named_block_produces_delete_bullets(self):
        requests, _ = _html_to_doc_requests('<p data-style="title">T</p>')
        assert any("deleteParagraphBullets" in r for r in requests)


class TestColspanNumCols:
    """num_cols must count colspan, not just cells, for insertTable requests."""

    def test_single_colspan3_row_inserts_3_columns(self):
        requests, _ = _html_to_doc_requests('<table><tr><td colspan="3">wide</td></tr></table>')
        table_reqs = [r for r in requests if "insertTable" in r]
        assert table_reqs[0]["insertTable"]["columns"] == 3

    def test_mixed_rows_uses_max_logical_width(self):
        # Row 0: [colspan=3]. Row 1: [1, 1, 1]. Max logical cols = 3.
        html = (
            "<table>"
            '<tr><td colspan="3">header</td></tr>'
            "<tr><td>a</td><td>b</td><td>c</td></tr>"
            "</table>"
        )
        requests, _ = _html_to_doc_requests(html)
        table_reqs = [r for r in requests if "insertTable" in r]
        assert table_reqs[0]["insertTable"]["columns"] == 3


class TestPhantomSet:
    def test_no_merges_empty(self):
        t = _table(_row(_cell("A"), _cell("B")), _row(_cell("C"), _cell("D")))
        assert _build_phantom_set(t) == set()

    def test_rowspan2_marks_phantom_below(self):
        # A(rowspan=2) in row 0 col 0 → (1,0) is phantom
        t = _table(_row(_cell("A", rowspan=2), _cell("B")), _row(_cell("C")))
        assert _build_phantom_set(t) == {(1, 0)}

    def test_rowspan3_marks_two_phantoms(self):
        t = _table(
            _row(_cell("A", rowspan=3), _cell("B")),
            _row(_cell("C")),
            _row(_cell("D")),
        )
        assert _build_phantom_set(t) == {(1, 0), (2, 0)}

    def test_colspan_marks_same_row_phantom(self):
        # colspan=2: (0,1) is covered by the spanning cell
        t = _table(_row(_cell("A", colspan=2), _cell("B")))
        assert _build_phantom_set(t) == {(0, 1)}

    def test_combined_rowspan_colspan(self):
        # A(rowspan=2, colspan=2) at (0,0) → phantoms at (0,1), (1,0), (1,1)
        t = _table(_row(_cell("A", colspan=2, rowspan=2), _cell("B")), _row(_cell("C")))
        assert _build_phantom_set(t) == {(0, 1), (1, 0), (1, 1)}

    def test_rowspan_in_second_column(self):
        # Row 0: [A, B(rowspan=2)], Row 1: [C] → phantom at (1,1)
        t = _table(_row(_cell("A"), _cell("B", rowspan=2)), _row(_cell("C")))
        assert _build_phantom_set(t) == {(1, 1)}


class TestPhysicalToAstIndices:
    def test_no_phantoms_no_colspan(self):
        row = _row(_cell("A"), _cell("B"), _cell("C"))
        assert _physical_to_ast_indices(0, row, set(), 3) == [0, 1, 2]

    def test_phantom_at_col0_maps_none(self):
        # Row 1: [C] at logical col 1; col 0 is phantom
        row = _row(_cell("C"))
        assert _physical_to_ast_indices(1, row, {(1, 0)}, 2) == [None, 0]

    def test_colspan_absorbed_gets_none(self):
        # Col 1 is absorbed by colspan=2 on col 0 but still physical in the doc after merge;
        # mapping must include None for it so fill skips the right cell.
        row = _row(_cell("A", colspan=2), _cell("B"))
        assert _physical_to_ast_indices(0, row, set(), 3) == [0, None, 1]

    def test_phantom_and_real_mixed(self):
        # Row 1 with phantom at col 0, two real cells at cols 1 and 2
        row = _row(_cell("X"), _cell("Y"))
        assert _physical_to_ast_indices(1, row, {(1, 0)}, 3) == [None, 0, 1]


class TestBuildMergeRequests:
    def _doc_table(self, num_rows=2, num_cols=2, first_cell_start=7):
        """Minimal doc table dict. _table_start_index returns first_cell_start - 2."""
        rows = []
        idx = first_cell_start
        for _ in range(num_rows):
            cells = [{"startIndex": idx + c * 3} for c in range(num_cols)]
            rows.append({"tableCells": cells})
            idx += num_cols * 3
        return {"tableRows": rows}

    def test_no_merges_empty(self):
        t = _table(_row(_cell("A"), _cell("B")), _row(_cell("C"), _cell("D")))
        assert _build_merge_requests([self._doc_table()], [t]) == []

    def test_rowspan2_emits_merge(self):
        t = _table(_row(_cell("A", rowspan=2), _cell("B")), _row(_cell("C")))
        reqs = _build_merge_requests([self._doc_table()], [t])
        assert len(reqs) == 1
        tr = reqs[0]["mergeTableCells"]["tableRange"]
        assert tr["rowSpan"] == 2
        assert tr["columnSpan"] == 1
        loc = tr["tableCellLocation"]
        assert loc["rowIndex"] == 0
        assert loc["columnIndex"] == 0

    def test_colspan2_emits_merge(self):
        t = _table(_row(_cell("A", colspan=2), _cell("B")))
        reqs = _build_merge_requests([self._doc_table(num_rows=1, num_cols=3)], [t])
        assert len(reqs) == 1
        tr = reqs[0]["mergeTableCells"]["tableRange"]
        assert tr["rowSpan"] == 1
        assert tr["columnSpan"] == 2

    def test_combined_rowspan_colspan_single_request(self):
        t = _table(_row(_cell("A", colspan=2, rowspan=2), _cell("B")), _row(_cell("C")))
        reqs = _build_merge_requests([self._doc_table(num_rows=2, num_cols=3)], [t])
        assert len(reqs) == 1
        tr = reqs[0]["mergeTableCells"]["tableRange"]
        assert tr["rowSpan"] == 2
        assert tr["columnSpan"] == 2

    def test_colspan_removed_tracks_physical_col(self):
        # Row: [A(colspan=2), B(colspan=2)] → A at physical 0, B at physical 1 (not logical 2)
        t = _table(_row(_cell("A", colspan=2), _cell("B", colspan=2)))
        reqs = _build_merge_requests([self._doc_table(num_rows=1, num_cols=4)], [t])
        assert len(reqs) == 2
        cols = [
            r["mergeTableCells"]["tableRange"]["tableCellLocation"]["columnIndex"] for r in reqs
        ]
        assert cols[0] == 0
        assert cols[1] == 1

    def test_empty_doc_table_skipped(self):
        t = _table(_row(_cell("A", colspan=2)))
        assert _build_merge_requests([{"tableRows": []}], [t]) == []


class TestRowspanFill:
    def _doc_cell(self, start_index):
        # startIndex at top level mirrors the real Docs API tableCells entry;
        # content[0].startIndex is what fill uses as para_start.
        return {"startIndex": start_index, "content": [{"startIndex": start_index + 1}]}

    def _doc_row(self, *start_indices):
        return {"tableCells": [self._doc_cell(i) for i in start_indices]}

    def test_phantom_cell_not_filled(self):
        # 2x2 table; A(rowspan=2) in col 0 → doc row 1 has 2 physical cells but col 0 is phantom
        ast_t = _table(_row(_cell("A", rowspan=2), _cell("B")), _row(_cell("C")))
        doc_t = {"tableRows": [self._doc_row(10, 20), self._doc_row(30, 40)]}
        reqs = _build_fill_requests([doc_t], [ast_t])
        # para_start = startIndex + 1; check on those values
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 31 not in insert_indices  # phantom cell — must not be filled
        assert 11 in insert_indices
        assert 21 in insert_indices
        assert 41 in insert_indices

    def test_phantom_comes_last_in_api_response(self):
        # After mergeTableCells, the Docs API returns covered (phantom) cells at the END
        # of tableCells, not in column order. Sort by startIndex must fix this.
        ast_t = _table(_row(_cell("A", rowspan=2), _cell("B")), _row(_cell("C")))
        # Row 1: API returns [real_col1 at si=40, phantom_col0 at si=30] — reversed order
        doc_t = {
            "tableRows": [
                {"tableCells": [self._doc_cell(10), self._doc_cell(20)]},
                {"tableCells": [self._doc_cell(40), self._doc_cell(30)]},  # real first
            ]
        }
        reqs = _build_fill_requests([doc_t], [ast_t])
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 31 not in insert_indices  # phantom — must not be filled even when listed last
        assert 41 in insert_indices  # real cell must be filled

    def test_empty_cell_text_skipped(self):
        ast_t = _table(_row(_cell(""), _cell("B")))
        doc_t = {"tableRows": [self._doc_row(10, 20)]}
        reqs = _build_fill_requests([doc_t], [ast_t])
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 11 not in insert_indices  # para_start = startIndex + 1
        assert 21 in insert_indices

    def test_colspan_phantom_not_filled(self):
        # After a colspan=2 merge, col 1 (phantom) remains as a physical cell.
        # Fill must skip it and write to col 2 (the real cell).
        ast_t = _table(_row(_cell("Wide", colspan=2), _cell("C2")))
        # Row 0 post-merge: [merged_col0 at 10, colspan_phantom_col1 at 20, real_col2 at 30]
        doc_t = {"tableRows": [self._doc_row(10, 20, 30)]}
        reqs = _build_fill_requests([doc_t], [ast_t])
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 21 not in insert_indices  # colspan phantom — must not be filled
        assert 11 in insert_indices  # merged cell gets "Wide"
        assert 31 in insert_indices  # real col 2 gets "C2"

    def test_requests_sorted_high_to_low(self):
        ast_t = _table(_row(_cell("A"), _cell("B")))
        doc_t = {"tableRows": [self._doc_row(10, 50)]}
        reqs = _build_fill_requests([doc_t], [ast_t])
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert insert_indices == sorted(insert_indices, reverse=True)


def _quota_http_error():
    resp = MagicMock()
    resp.status = 403
    return HttpError(
        resp=resp,
        content=b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}',
    )


def _other_403_error():
    resp = MagicMock()
    resp.status = 403
    return HttpError(resp=resp, content=b'{"error": {"reason": "forbidden"}}')


class TestCreateDoc:
    """Bug: create_doc used _html_to_text (plain text) instead of _html_to_doc_requests."""

    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "Test",
            "parents": ["folder1"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_h1_produces_heading_style(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_list_item_produces_bullet(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<li>Item</li>", ctx=ctx)
        bullets = [r for r in self._batchupdate_requests(docs_svc) if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_no_content_skips_batchupdate(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content=None, ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    def test_inline_only_html_skips_batchupdate(self):
        """Tags with no block-level elements produce no requests; batchUpdate should not fire."""
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<span>no blocks</span>", ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    def test_quota_exceeded_returns_error_dict(self):
        """create_doc must return {"error": ...} on storageQuotaExceeded, not raise."""
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    def test_non_quota_403_still_raises(self):
        """A 403 that is NOT storageQuotaExceeded must propagate — not be swallowed."""
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        with pytest.raises(HttpError):
            _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)


# ---------------------------------------------------------------------------
# Markdown / code block / task list — html_parser
# ---------------------------------------------------------------------------


class TestInlineCode:
    def test_inline_code_sets_font_family(self):
        nodes = html_to_ast("<p>Use <code>x = 1</code> here</p>")
        assert isinstance(nodes[0], Paragraph)
        code_run = next(r for r in nodes[0].runs if r.font_family)
        assert code_run.font_family == "Courier New"
        assert code_run.text == "x = 1"

    def test_inline_code_plain_text_no_font_family(self):
        nodes = html_to_ast("<p>plain text</p>")
        for run in nodes[0].runs:
            assert run.font_family is None

    def test_inline_code_preserves_surrounding_text(self):
        nodes = html_to_ast("<p>before <code>fn()</code> after</p>")
        texts = [r.text for r in nodes[0].runs]
        assert "before " in texts
        assert "fn()" in texts
        assert " after" in texts


class TestPreBlock:
    def test_pre_code_creates_paragraph(self):
        nodes = html_to_ast("<pre><code>hello</code></pre>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)

    def test_pre_code_sets_font_family_on_runs(self):
        nodes = html_to_ast("<pre><code>def foo(): pass</code></pre>")
        para = nodes[0]
        assert isinstance(para, Paragraph)
        assert all(r.font_family == "Courier New" for r in para.runs)

    def test_pre_multiline_preserved_in_run_text(self):
        nodes = html_to_ast("<pre><code>line1\nline2</code></pre>")
        para = nodes[0]
        full = "".join(r.text for r in para.runs)
        assert "line1" in full
        assert "line2" in full
        assert "\n" in full

    def test_pre_trailing_newline_stripped(self):
        # The markdown library appends a trailing \n inside <pre>; we strip it
        # so the emitter doesn't produce a spurious extra empty paragraph.
        nodes = html_to_ast("<pre><code>code\n</code></pre>")
        para = nodes[0]
        full = "".join(r.text for r in para.runs)
        assert not full.endswith("\n")

    def test_pre_followed_by_paragraph(self):
        nodes = html_to_ast("<pre><code>code</code></pre><p>text</p>")
        assert len(nodes) == 2
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Paragraph)


class TestTaskList:
    def test_checked_item_sets_checked_true(self):
        nodes = html_to_ast("<ul><li>[x] Done</li></ul>")
        bullet = next(n for n in nodes if isinstance(n, BulletItem))
        assert bullet.checked is True

    def test_unchecked_item_sets_checked_false(self):
        nodes = html_to_ast("<ul><li>[ ] Todo</li></ul>")
        bullet = next(n for n in nodes if isinstance(n, BulletItem))
        assert bullet.checked is False

    def test_checked_prefix_stripped_from_runs(self):
        nodes = html_to_ast("<ul><li>[x] Done</li></ul>")
        bullet = nodes[0]
        full_text = "".join(r.text for r in bullet.runs)
        assert "[x]" not in full_text
        assert "Done" in full_text

    def test_unchecked_prefix_stripped_from_runs(self):
        nodes = html_to_ast("<ul><li>[ ] Todo</li></ul>")
        bullet = nodes[0]
        full_text = "".join(r.text for r in bullet.runs)
        assert "[ ]" not in full_text
        assert "Todo" in full_text

    def test_uppercase_X_also_recognised(self):
        nodes = html_to_ast("<ul><li>[X] Done</li></ul>")
        bullet = nodes[0]
        assert bullet.checked is True

    def test_normal_item_checked_is_none(self):
        nodes = html_to_ast("<ul><li>Regular item</li></ul>")
        bullet = nodes[0]
        assert bullet.checked is None

    def test_checked_with_bold_text(self):
        nodes = html_to_ast("<ul><li>[x] <b>Important</b></li></ul>")
        bullet = nodes[0]
        assert bullet.checked is True
        # The bold run should survive
        bold_run = next((r for r in bullet.runs if r.bold), None)
        assert bold_run is not None
        assert bold_run.text == "Important"

    def test_mixed_task_and_normal_items(self):
        nodes = html_to_ast("<ul><li>[x] Done</li><li>[ ] Todo</li><li>Plain</li></ul>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert bullets[0].checked is True
        assert bullets[1].checked is False
        assert bullets[2].checked is None


# ---------------------------------------------------------------------------
# Emitter — inline run styles, font_family, task list glyphs
# ---------------------------------------------------------------------------


class TestRunStylesInParagraphs:
    def test_bold_run_emits_update_text_style(self):
        requests, _ = _to_doc_requests("<p><b>bold</b></p>")
        bold_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        ]
        assert len(bold_reqs) == 1

    def test_italic_run_emits_update_text_style(self):
        requests, _ = _to_doc_requests("<p><i>italic</i></p>")
        italic_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("italic") is True
        ]
        assert len(italic_reqs) == 1

    def test_bold_italic_combined(self):
        requests, _ = _to_doc_requests("<p><b><i>both</i></b></p>")
        styled = [r for r in requests if "updateTextStyle" in r]
        ts = styled[0]["updateTextStyle"]["textStyle"]
        assert ts.get("bold") is True
        assert ts.get("italic") is True

    def test_font_family_emits_weighted_font(self):
        requests, _ = _to_doc_requests("<p><code>fn()</code></p>")
        font_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "weightedFontFamily" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(font_reqs) == 1
        assert (
            font_reqs[0]["updateTextStyle"]["textStyle"]["weightedFontFamily"]["fontFamily"]
            == "Courier New"
        )

    def test_pre_block_font_family_emitted(self):
        requests, _ = _to_doc_requests("<pre><code>x = 1</code></pre>")
        font_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "weightedFontFamily" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(font_reqs) == 1

    def test_link_still_emitted(self):
        requests, _ = _to_doc_requests('<p><a href="https://x.com">link</a></p>')
        link_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(link_reqs) == 1


class TestTaskListEmitter:
    def test_checked_item_inserts_check_glyph(self):
        requests, _ = _to_doc_requests("<ul><li>[x] Done</li></ul>")
        insert = next(r for r in requests if "insertText" in r)
        assert "☑" in insert["insertText"]["text"]

    def test_unchecked_item_inserts_ballot_glyph(self):
        requests, _ = _to_doc_requests("<ul><li>[ ] Todo</li></ul>")
        insert = next(r for r in requests if "insertText" in r)
        assert "☐" in insert["insertText"]["text"]

    def test_normal_item_no_glyph(self):
        requests, _ = _to_doc_requests("<ul><li>Plain</li></ul>")
        insert = next(r for r in requests if "insertText" in r)
        assert "☑" not in insert["insertText"]["text"]
        assert "☐" not in insert["insertText"]["text"]

    def test_run_style_offset_skips_glyph(self):
        # Bold run inside a checked item — its updateTextStyle range must NOT overlap the glyph.
        # The glyph is 2 chars (☑ + space) at doc_start; the bold run starts at doc_start + 2.
        requests, _ = _to_doc_requests("<ul><li>[x] <b>task</b></li></ul>")
        insert = next(r for r in requests if "insertText" in r)
        insert_idx = insert["insertText"]["location"]["index"]  # typically 1
        bold_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        ]
        assert len(bold_reqs) == 1
        bold_start = bold_reqs[0]["updateTextStyle"]["range"]["startIndex"]
        # glyph "☑ " is 2 chars; bold run must start at least 2 chars after insert_idx
        assert bold_start >= insert_idx + 2


# ---------------------------------------------------------------------------
# Markdown pipeline — _md_to_html and _to_doc_requests
# ---------------------------------------------------------------------------


class TestMdToHtml:
    def test_heading_converts(self):
        html = _md_to_html("# Title")
        assert "<h1>" in html

    def test_bold_converts(self):
        html = _md_to_html("**bold**")
        assert "<strong>" in html

    def test_italic_converts(self):
        html = _md_to_html("*italic*")
        assert "<em>" in html

    def test_unordered_list(self):
        html = _md_to_html("- item one\n- item two\n")
        assert "<ul>" in html
        assert "<li>" in html

    def test_ordered_list(self):
        html = _md_to_html("1. first\n2. second\n")
        assert "<ol>" in html

    def test_link(self):
        html = _md_to_html("[click](https://example.com)")
        assert 'href="https://example.com"' in html

    def test_pipe_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        html = _md_to_html(md)
        assert "<table>" in html

    def test_fenced_code_block(self):
        md = "```python\nx = 1\n```\n"
        html = _md_to_html(md)
        assert "<pre>" in html
        assert "<code" in html  # may include class="language-python"


class TestToDocRequestsMarkdown:
    def test_h1_in_markdown_produces_heading_1(self):
        requests, _ = _to_doc_requests("# Title", "markdown")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in styles

    def test_markdown_matches_html_for_heading(self):
        md_reqs, _ = _to_doc_requests("# Title", "markdown")
        html_reqs, _ = _to_doc_requests("<h1>Title</h1>", "html")
        md_styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in md_reqs
            if "updateParagraphStyle" in r
        ]
        html_styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in html_reqs
            if "updateParagraphStyle" in r
        ]
        assert md_styles == html_styles

    def test_markdown_list_produces_bullet(self):
        requests, _ = _to_doc_requests("- item\n", "markdown")
        assert any("createParagraphBullets" in r for r in requests)

    def test_markdown_ordered_list_produces_numbered_bullet(self):
        requests, _ = _to_doc_requests("1. first\n", "markdown")
        bullet_reqs = [r for r in requests if "createParagraphBullets" in r]
        assert any("NUMBERED" in r["createParagraphBullets"]["bulletPreset"] for r in bullet_reqs)

    def test_markdown_bold_emits_text_style(self):
        requests, _ = _to_doc_requests("**bold**\n", "markdown")
        bold_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        ]
        assert len(bold_reqs) >= 1

    def test_markdown_task_list_checked(self):
        requests, _ = _to_doc_requests("- [x] Done\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert "☑" in insert["insertText"]["text"]

    def test_markdown_task_list_unchecked(self):
        requests, _ = _to_doc_requests("- [ ] Todo\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert "☐" in insert["insertText"]["text"]

    def test_markdown_fenced_code_emits_font_family(self):
        requests, _ = _to_doc_requests("```\nx = 1\n```\n", "markdown")
        font_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "weightedFontFamily" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(font_reqs) >= 1

    def test_html_format_still_works(self):
        requests, _ = _to_doc_requests("<h2>Sub</h2>", "html")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_2" in styles


# ---------------------------------------------------------------------------
# create_doc content_format and create_doc_from_file
# ---------------------------------------------------------------------------


class TestCreateDocMarkdown:
    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "Test",
            "parents": ["folder1"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_markdown_heading_in_create_doc(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](
            title="Doc", content="# Title", content_format="markdown", ctx=ctx
        )
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_html_format_default_unchanged(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types


class TestCreateDocFromFile:
    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "myfile",
            "parents": ["root"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_md_file_creates_doc(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Hello\n\nParagraph text.\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        assert "docId" in result
        assert "error" not in result

    def test_md_file_title_defaults_to_stem(self, tmp_path):
        md_file = tmp_path / "my-notes.md"
        md_file.write_text("# Content\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        create_body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert create_body["name"] == "my-notes"

    def test_md_file_explicit_title_used(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Content\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc_from_file"](local_path=str(md_file), title="My Doc", ctx=ctx)
        create_body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert create_body["name"] == "My Doc"

    def test_md_file_heading_emitted(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Section\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_html_file_accepted(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<h2>Hello</h2>")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](local_path=str(html_file), ctx=ctx)
        assert "docId" in result
        assert "error" not in result

    def test_file_not_found_returns_error(self, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](
            local_path=str(tmp_path / "missing.md"), ctx=ctx
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_unsupported_extension_returns_error(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("plain text")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](local_path=str(txt_file), ctx=ctx)
        assert "error" in result
        assert ".txt" in result["error"]


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


# ---------------------------------------------------------------------------
# Phase 3 — Run style fields
# ---------------------------------------------------------------------------


class TestRunStylePhase3:
    def _run_req(self, run: Run) -> dict | None:
        reqs = _run_style_requests(run, 10, 15)
        return reqs[0]["updateTextStyle"] if reqs else None

    def test_font_size_emits_fontSize(self):
        req = self._run_req(Run("hello", font_size=14.0))
        assert req is not None
        assert req["textStyle"]["fontSize"] == {"magnitude": 14.0, "unit": "PT"}
        assert "fontSize" in req["fields"]

    def test_foreground_color_emits_foregroundColor(self):
        color = RGBColor(red=1.0, green=0.0, blue=0.0)
        req = self._run_req(Run("hello", foreground_color=color))
        assert req is not None
        rgb = req["textStyle"]["foregroundColor"]["color"]["rgbColor"]
        assert rgb == {"red": 1.0, "green": 0.0, "blue": 0.0}
        assert "foregroundColor" in req["fields"]

    def test_background_color_emits_backgroundColor(self):
        color = RGBColor(red=0.0, green=1.0, blue=0.0)
        req = self._run_req(Run("hello", background_color=color))
        assert req is not None
        rgb = req["textStyle"]["backgroundColor"]["color"]["rgbColor"]
        assert rgb == {"red": 0.0, "green": 1.0, "blue": 0.0}
        assert "backgroundColor" in req["fields"]

    def test_baseline_offset_emits_baselineOffset(self):
        req = self._run_req(Run("hello", baseline_offset="SUPERSCRIPT"))
        assert req is not None
        assert req["textStyle"]["baselineOffset"] == "SUPERSCRIPT"
        assert "baselineOffset" in req["fields"]

    def test_small_caps_emits_smallCaps(self):
        req = self._run_req(Run("hello", small_caps=True))
        assert req is not None
        assert req["textStyle"]["smallCaps"] is True
        assert "smallCaps" in req["fields"]

    def test_none_phase3_fields_not_emitted(self):
        req = self._run_req(Run("hello", bold=True))
        assert req is not None
        assert "fontSize" not in req["textStyle"]
        assert "foregroundColor" not in req["textStyle"]
        assert "backgroundColor" not in req["textStyle"]
        assert "baselineOffset" not in req["textStyle"]
        assert "smallCaps" not in req["textStyle"]

    def test_combined_phase2_and_phase3(self):
        run = Run("hello", bold=True, font_size=12.0, foreground_color=RGBColor(0.5, 0.5, 0.5))
        req = self._run_req(run)
        assert req is not None
        assert "bold" in req["fields"]
        assert "fontSize" in req["fields"]
        assert "foregroundColor" in req["fields"]


# ---------------------------------------------------------------------------
# Phase 3 — Cell style requests
# ---------------------------------------------------------------------------


class TestBuildCellStyleRequests:
    def _doc_table(self, table_start: int = 5, num_rows: int = 1, num_cols: int = 2) -> dict:
        rows = []
        idx = table_start + 2
        for _ in range(num_rows):
            cells = []
            for _ in range(num_cols):
                cells.append({"startIndex": idx, "endIndex": idx + 3})
                idx += 3
            rows.append({"tableCells": cells})
        return {"tableRows": rows}

    def test_background_color_emitted(self):
        color = RGBColor(red=0.9, green=0.9, blue=0.9)
        ast_table = Table(rows=[Row(cells=[Cell(runs=[], background_color=color), _cell("b")])])
        doc_table = self._doc_table()
        reqs = _build_cell_style_requests([doc_table], [ast_table])
        assert len(reqs) == 1
        style = reqs[0]["updateTableCellStyle"]["tableCellStyle"]
        assert "backgroundColor" in style
        assert style["backgroundColor"]["color"]["rgbColor"] == {
            "red": 0.9,
            "green": 0.9,
            "blue": 0.9,
        }

    def test_padding_emitted(self):
        ast_table = Table(
            rows=[
                Row(
                    cells=[
                        Cell(
                            runs=[],
                            padding_top=3.6,
                            padding_right=3.6,
                            padding_bottom=3.6,
                            padding_left=3.6,
                        ),
                    ]
                )
            ]
        )
        doc_table = self._doc_table(num_cols=1)
        reqs = _build_cell_style_requests([doc_table], [ast_table])
        assert len(reqs) == 1
        style = reqs[0]["updateTableCellStyle"]["tableCellStyle"]
        for side in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft"):
            assert style[side] == {"magnitude": 3.6, "unit": "PT"}

    def test_border_emitted_all_sides(self):
        color = RGBColor(0.0, 0.0, 0.0)
        ast_table = Table(
            rows=[
                Row(
                    cells=[
                        Cell(
                            runs=[], border_color=color, border_width=0.5, border_dash_style="SOLID"
                        ),
                    ]
                )
            ]
        )
        doc_table = self._doc_table(num_cols=1)
        reqs = _build_cell_style_requests([doc_table], [ast_table])
        assert len(reqs) == 1
        style = reqs[0]["updateTableCellStyle"]["tableCellStyle"]
        for side in ("borderTop", "borderRight", "borderBottom", "borderLeft"):
            assert side in style
            assert style[side]["dashStyle"] == "SOLID"

    def test_no_style_fields_skipped(self):
        ast_table = Table(rows=[Row(cells=[_cell("plain")])])
        doc_table = self._doc_table(num_cols=1)
        reqs = _build_cell_style_requests([doc_table], [ast_table])
        assert reqs == []


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------


def _make_body_doc(paragraphs: list[dict]) -> dict:
    """Build a minimal Docs API body dict from a list of paragraph specs."""
    content = []
    idx = 1
    for p in paragraphs:
        style_type = p["style_type"]
        text = p.get("text", "Hello")
        ts = p.get("text_style", {})
        ps = p.get("para_style", {})
        end = idx + len(text) + 1
        content.append(
            {
                "startIndex": idx,
                "endIndex": end,
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": style_type, **ps},
                    "elements": [
                        {
                            "startIndex": idx,
                            "endIndex": end - 1,
                            "textRun": {"content": text, "textStyle": ts},
                        }
                    ],
                },
            }
        )
        idx = end
    return {"body": {"content": content}}


class TestThemeHelpers:
    def test_read_body_styles_extracts_fields(self):
        doc = _make_body_doc(
            [
                {
                    "style_type": "HEADING_1",
                    "text": "My Heading",
                    "text_style": {
                        "weightedFontFamily": {"fontFamily": "Arial"},
                        "fontSize": {"magnitude": 20.0, "unit": "PT"},
                        "bold": True,
                    },
                    "para_style": {
                        "lineSpacing": 115,
                        "spaceAbove": {"magnitude": 12.0, "unit": "PT"},
                    },
                }
            ]
        )
        theme = _read_body_styles(doc)
        assert "HEADING_1" in theme
        h1 = theme["HEADING_1"]
        assert h1["font_family"] == "Arial"
        assert h1["font_size"] == 20.0
        assert h1["bold"] is True
        assert h1["line_spacing"] == 115
        assert h1["space_above"] == 12.0

    def test_first_paragraph_per_type_wins(self):
        doc = _make_body_doc(
            [
                {
                    "style_type": "NORMAL_TEXT",
                    "text": "First",
                    "text_style": {"weightedFontFamily": {"fontFamily": "Roboto"}},
                },
                {
                    "style_type": "NORMAL_TEXT",
                    "text": "Second",
                    "text_style": {"weightedFontFamily": {"fontFamily": "Arial"}},
                },
            ]
        )
        theme = _read_body_styles(doc)
        assert theme["NORMAL_TEXT"]["font_family"] == "Roboto"

    def test_unknown_style_type_ignored(self):
        doc = _make_body_doc(
            [{"style_type": "DEFAULT_PARAGRAPH_STYLE", "text": "x", "text_style": {"bold": True}}]
        )
        theme = _read_body_styles(doc)
        assert "DEFAULT_PARAGRAPH_STYLE" not in theme

    def test_build_named_style_requests_text_fields(self):
        reqs = _build_named_style_requests(
            "HEADING_1", {"font_family": "Georgia", "font_size": 18.0, "bold": True}
        )
        assert len(reqs) == 1
        req = reqs[0]["updateNamedStyle"]
        assert req["namedStyle"]["namedStyleType"] == "HEADING_1"
        assert req["namedStyle"]["textStyle"]["weightedFontFamily"]["fontFamily"] == "Georgia"
        assert "named_style_type" in req["fields"]
        assert "text_style.weighted_font_family" in req["fields"]
        assert "text_style.font_size" in req["fields"]
        assert "text_style.bold" in req["fields"]

    def test_build_named_style_requests_para_fields(self):
        reqs = _build_named_style_requests("NORMAL_TEXT", {"line_spacing": 115, "space_above": 6.0})
        req = reqs[0]["updateNamedStyle"]
        assert "named_style_type" in req["fields"]
        assert "paragraph_style.line_spacing" in req["fields"]
        assert "paragraph_style.space_above" in req["fields"]
        assert req["namedStyle"]["paragraphStyle"]["lineSpacing"] == 115

    def test_build_named_style_requests_empty_entry_returns_empty(self):
        assert _build_named_style_requests("NORMAL_TEXT", {}) == []

    def test_read_named_styles_extracts_fields(self):
        doc = {
            "namedStyles": {
                "styles": [
                    {
                        "namedStyleType": "HEADING_1",
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Arial"},
                            "fontSize": {"magnitude": 20.0, "unit": "PT"},
                            "bold": True,
                        },
                        "paragraphStyle": {
                            "lineSpacing": 115,
                            "spaceAbove": {"magnitude": 12.0, "unit": "PT"},
                        },
                    }
                ]
            }
        }
        theme = _read_named_styles(doc)
        assert "HEADING_1" in theme
        h1 = theme["HEADING_1"]
        assert h1["font_family"] == "Arial"
        assert h1["font_size"] == 20.0
        assert h1["bold"] is True
        assert h1["line_spacing"] == 115
        assert h1["space_above"] == 12.0

    def test_read_named_styles_unknown_type_ignored(self):
        doc = {
            "namedStyles": {
                "styles": [
                    {"namedStyleType": "DEFAULT_PARAGRAPH_STYLE", "textStyle": {"bold": True}}
                ]
            }
        }
        theme = _read_named_styles(doc)
        assert "DEFAULT_PARAGRAPH_STYLE" not in theme

    def test_read_named_styles_empty_entry_omitted(self):
        doc = {
            "namedStyles": {
                "styles": [{"namedStyleType": "HEADING_1", "textStyle": {}, "paragraphStyle": {}}]
            }
        }
        theme = _read_named_styles(doc)
        assert "HEADING_1" not in theme


# ---------------------------------------------------------------------------
# apply_theme / get_doc_theme tools
# ---------------------------------------------------------------------------


class TestApplyThemeTool:
    def _setup(self):
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        return tools

    def _mock_doc_with_para(self, style_type="HEADING_1", font_family="Georgia"):
        return _make_body_doc(
            [
                {
                    "style_type": style_type,
                    "text": "Sample text",
                    "text_style": {
                        "weightedFontFamily": {"fontFamily": font_family},
                    },
                }
            ]
        )

    def test_apply_theme_emits_update_named_style(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = tools["apply_theme"](
            doc_id="doc123",
            theme={"HEADING_1": {"font_family": "Georgia"}},
            ctx=ctx,
        )
        assert result["docId"] == "doc123"
        assert result["requests"] >= 1
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        assert any("updateNamedStyle" in r for r in reqs)
        # Default mode must NOT fetch the doc (no paragraph scan)
        mock_docs.documents().get.assert_not_called()

    def test_apply_theme_empty_theme_returns_error(self):
        tools = self._setup()
        mock_docs = MagicMock()
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        result = tools["apply_theme"](doc_id="doc123", theme={}, ctx=ctx)
        assert "error" in result

    def test_apply_theme_table_style(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "body": {"content": [{"table": {"rows": 2, "columns": 3}, "startIndex": 5}]}
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = tools["apply_theme"](
            doc_id="doc123",
            theme={"table": {"border_width": 0.5, "cell_padding": 3.6}},
            ctx=ctx,
        )
        mock_docs.documents().get.assert_called_with(documentId="doc123")
        assert result["requests"] > 0

    def test_apply_theme_default_succeeds_without_matching_paragraphs(self):
        # Default mode (overwrite=False) updates named style definitions regardless of
        # which paragraphs currently exist in the doc.
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = tools["apply_theme"](
            doc_id="doc123",
            theme={"HEADING_1": {"font_size": 20.0}},
            ctx=ctx,
        )
        assert "error" not in result
        assert result["requests"] == 1

    def test_apply_theme_overwrite_also_updates_paragraphs(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = self._mock_doc_with_para("HEADING_1")
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = tools["apply_theme"](
            doc_id="doc123",
            theme={"HEADING_1": {"font_family": "Georgia"}},
            overwrite=True,
            ctx=ctx,
        )
        assert result["docId"] == "doc123"
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        assert any("updateNamedStyle" in r for r in reqs)
        assert any("updateTextStyle" in r for r in reqs)

    def test_get_doc_theme_returns_theme_dict(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = _make_body_doc(
            [
                {
                    "style_type": "HEADING_1",
                    "text": "My Title",
                    "text_style": {"weightedFontFamily": {"fontFamily": "Arial"}},
                }
            ]
        )
        ctx = _make_ctx(docs_service=mock_docs)
        result = tools["get_doc_theme"](doc_id="doc123", ctx=ctx)
        assert "HEADING_1" in result
        assert result["HEADING_1"]["font_family"] == "Arial"

    def test_get_doc_named_styles_returns_named_style_dict(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "namedStyles": {
                "styles": [
                    {
                        "namedStyleType": "HEADING_1",
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Georgia"},
                            "fontSize": {"magnitude": 20.0, "unit": "PT"},
                        },
                        "paragraphStyle": {},
                    }
                ]
            }
        }
        ctx = _make_ctx(docs_service=mock_docs)
        result = tools["get_doc_named_styles"](doc_id="doc123", ctx=ctx)
        assert "HEADING_1" in result
        assert result["HEADING_1"]["font_family"] == "Georgia"
        assert result["HEADING_1"]["font_size"] == 20.0


# ---------------------------------------------------------------------------
# insert_inline_image (#145)
# ---------------------------------------------------------------------------


class TestInsertInlineImage:
    def _ctx(self, docs_svc=None, drive_svc=None):
        return _make_ctx(
            docs_service=docs_svc or MagicMock(),
            drive_service=drive_svc or MagicMock(),
            doc_cache=MagicMock(),
        )

    def test_uri_only_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=5, uri="https://example.com/img.png", ctx=ctx
        )
        assert result == {"docId": "doc1", "index": 5}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["location"]["index"] == 5
        assert req["uri"] == "https://example.com/img.png"
        assert "objectSize" not in req

    def test_width_and_height_included(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            width=200.0,
            height=100.0,
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["objectSize"]["width"] == {"magnitude": 200.0, "unit": "PT"}
        assert req["objectSize"]["height"] == {"magnitude": 100.0, "unit": "PT"}

    def test_drive_file_id_fetches_web_content_link(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=3, drive_file_id="file1", ctx=ctx
        )
        assert "error" not in result
        drive_svc.files.return_value.get.assert_called_with(
            fileId="file1", fields="webContentLink", supportsAllDrives=True
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["uri"] == "https://drive.google.com/uc?id=file1"

    def test_missing_both_returns_error(self):
        ctx = self._ctx()
        result = _docs_tools["insert_inline_image"](doc_id="doc1", index=1, ctx=ctx)
        assert "error" in result

    def test_both_provided_returns_error(self):
        ctx = self._ctx()
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            drive_file_id="file1",
            ctx=ctx,
        )
        assert "error" in result

    def test_drive_file_no_web_content_link_returns_error(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {}
        ctx = self._ctx(drive_svc=drive_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, drive_file_id="file1", ctx=ctx
        )
        assert "error" in result

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, uri="https://example.com/img.png", ctx=ctx
        )
        assert "error" in result


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
# create_header / create_footer (#147)
# ---------------------------------------------------------------------------


class TestCreateHeader:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _make_docs_svc(self, header_id="hdr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createHeaderResponse": {"headerId": header_id}}]
        }
        return docs_svc

    def test_returns_header_id(self):
        docs_svc = self._make_docs_svc("hdr-abc")
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "headerId": "hdr-abc"}

    def test_default_type_sent(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createHeader"]["type"] == "DEFAULT"
        assert "sectionBreakLocation" not in body["requests"][0]["createHeader"]

    def test_first_page_header_type(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_header"](doc_id="doc1", header_type="FIRST_PAGE_HEADER", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createHeader"]["type"] == "FIRST_PAGE_HEADER"

    def test_invalid_type_returns_error(self):
        ctx = self._ctx()
        result = _docs_tools["create_header"](doc_id="doc1", header_type="BOGUS", ctx=ctx)
        assert "error" in result

    def test_content_inserted_when_provided(self):
        docs_svc = self._make_docs_svc("hdr1")
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_header"](doc_id="doc1", content="My Header", ctx=ctx)
        # Two batchUpdate calls: one to create, one to insert text
        assert docs_svc.documents.return_value.batchUpdate.call_count == 2
        second_body = docs_svc.documents.return_value.batchUpdate.call_args_list[1].kwargs["body"]
        insert_req = second_body["requests"][0]["insertText"]
        assert insert_req["text"] == "My Header"
        assert insert_req["location"]["segmentId"] == "hdr1"
        assert insert_req["location"]["index"] == 0

    def test_no_content_single_api_call(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 1

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert "error" in result

    def test_empty_replies_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultHeaderId": "hdr-fallback"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "headerId": "hdr-fallback"}

    def test_already_exists_error_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=400), content=b"Default header already exists."
        )
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultHeaderId": "hdr-existing"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "headerId": "hdr-existing"}


class TestCreateFooter:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _make_docs_svc(self, footer_id="ftr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createFooterResponse": {"footerId": footer_id}}]
        }
        return docs_svc

    def test_returns_footer_id(self):
        docs_svc = self._make_docs_svc("ftr-xyz")
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "footerId": "ftr-xyz"}

    def test_default_type_sent(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createFooter"]["type"] == "DEFAULT"
        assert "sectionBreakLocation" not in body["requests"][0]["createFooter"]

    def test_first_page_footer_type(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_footer"](doc_id="doc1", footer_type="FIRST_PAGE_FOOTER", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createFooter"]["type"] == "FIRST_PAGE_FOOTER"

    def test_invalid_type_returns_error(self):
        ctx = self._ctx()
        result = _docs_tools["create_footer"](doc_id="doc1", footer_type="BOGUS", ctx=ctx)
        assert "error" in result

    def test_content_inserted_when_provided(self):
        docs_svc = self._make_docs_svc("ftr1")
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_footer"](doc_id="doc1", content="Page 1", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 2
        second_body = docs_svc.documents.return_value.batchUpdate.call_args_list[1].kwargs["body"]
        insert_req = second_body["requests"][0]["insertText"]
        assert insert_req["text"] == "Page 1"
        assert insert_req["location"]["segmentId"] == "ftr1"
        assert insert_req["location"]["index"] == 0

    def test_no_content_single_api_call(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 1

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert "error" in result

    def test_empty_replies_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultFooterId": "ftr-fallback"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "footerId": "ftr-fallback"}

    def test_already_exists_error_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=400), content=b"Default footer already exists."
        )
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultFooterId": "ftr-existing"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "footerId": "ftr-existing"}


# ---------------------------------------------------------------------------
# insert_doc_text — segment_id support for headers/footers
# ---------------------------------------------------------------------------


class TestInsertDocTextSegmentId:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def test_segment_id_included_in_location(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_doc_text"](
            doc_id="doc1",
            insertions=[{"index": 1, "text": "Header text", "segment_id": "hdr1"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        loc = body["requests"][0]["insertText"]["location"]
        assert loc["index"] == 1
        assert loc["segmentId"] == "hdr1"

    def test_no_segment_id_omits_field(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_doc_text"](
            doc_id="doc1",
            insertions=[{"index": 5, "text": "Body text"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        loc = body["requests"][0]["insertText"]["location"]
        assert "segmentId" not in loc

    def test_mixed_body_and_segment_insertions(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_doc_text"](
            doc_id="doc1",
            insertions=[
                {"index": 10, "text": "Body"},
                {"index": 1, "text": "Header", "segment_id": "hdr1"},
            ],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        reqs = body["requests"]
        assert len(reqs) == 2
        # Sorted high-index-first: index=10 before index=1
        assert reqs[0]["insertText"]["location"]["index"] == 10
        assert "segmentId" not in reqs[0]["insertText"]["location"]
        assert reqs[1]["insertText"]["location"]["index"] == 1
        assert reqs[1]["insertText"]["location"]["segmentId"] == "hdr1"
