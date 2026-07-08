"""Tests for docs core — HTML/AST pipeline and emitter internals."""

import pytest

from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Cell,
    Heading,
    NamedBlock,
    Paragraph,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.content import (
    _html_to_doc_requests,
    _html_to_text,
    _to_doc_requests,
)
from mcp_gee_sweet.tools.docs.emitter import (
    _build_blank_para_before_table_collapses,
    _build_fill_requests,
    _build_merge_requests,
    _build_phantom_set,
    _physical_to_ast_indices,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast

# ---------------------------------------------------------------------------
# AST construction helpers
# ---------------------------------------------------------------------------


def _cell(text: str, colspan: int = 1, rowspan: int = 1) -> Cell:
    return Cell(children=[Run(text)], colspan=colspan, rowspan=rowspan)


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
        assert tables[0].rows[0].cells[0].children[0].text == "A"
        assert tables[0].rows[0].cells[1].children[0].text == "B"
        assert tables[0].rows[1].cells[0].children[0].text == "1"
        assert tables[0].rows[1].cells[1].children[0].text == "2"

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
        assert tables[0].rows[0].cells[0].children[0].text == "T1"
        assert tables[1].rows[0].cells[0].children[0].text == "T2"
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
        assert cell.children[0].bold is True

    def test_td_cell_text(self):
        nodes = html_to_ast("<table><tr><td>Data</td></tr></table>")
        table = nodes[0]
        cell = table.rows[0].cells[0]
        assert cell.is_header is False
        assert cell.children[0].text == "Data"

    def test_inline_bold_in_td(self):
        nodes = html_to_ast("<table><tr><td><b>bold cell</b></td></tr></table>")
        cell = nodes[0].rows[0].cells[0]
        assert cell.children[0].bold is True
        assert cell.children[0].text == "bold cell"

    def test_inline_link_in_td(self):
        nodes = html_to_ast('<table><tr><td><a href="https://x.com">link</a></td></tr></table>')
        cell = nodes[0].rows[0].cells[0]
        link_run = next(r for r in cell.children if r.link_url)
        assert link_run.link_url == "https://x.com"

    def test_colspan_on_td(self):
        nodes = html_to_ast('<table><tr><td colspan="2">wide</td></tr></table>')
        cell = nodes[0].rows[0].cells[0]
        assert cell.colspan == 2

    def test_default_colspan_is_1(self):
        nodes = html_to_ast("<table><tr><td>x</td></tr></table>")
        assert nodes[0].rows[0].cells[0].colspan == 1

    def test_explicit_colspan_zero_clamped_to_1(self):
        # colspan="0" is invalid HTML but must not survive as a literal 0 — a
        # zero-column cell breaks downstream `num_cols` calculations. The old
        # `int(attr_dict.get("colspan") or 1)` didn't catch this: "0" is a
        # non-empty (truthy) string, so `or 1` never kicks in.
        nodes = html_to_ast('<table><tr><td colspan="0">x</td></tr></table>')
        assert nodes[0].rows[0].cells[0].colspan == 1

    def test_explicit_rowspan_zero_clamped_to_1(self):
        nodes = html_to_ast('<table><tr><td rowspan="0">x</td></tr></table>')
        assert nodes[0].rows[0].cells[0].rowspan == 1

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

    def test_cell_with_nested_table_skipped_here(self):
        # Cells containing a nested table are handled by _fill_nested_cell_content
        # instead (see tests/test_docs_tables.py) — _build_fill_requests must skip
        # them entirely rather than filling only the leading text and ignoring
        # the table, which would silently drop content again.
        inner = _table(_row(_cell("inner")))
        ast_t = Table(rows=[Row(cells=[Cell(children=[Run("Some label "), inner])])])
        doc_t = {"tableRows": [self._doc_row(10)]}
        reqs = _build_fill_requests([doc_t], [ast_t])
        assert reqs == []


class TestFillRequestsFontSizeClear:
    """Table cell text must not inherit font size from a preceding heading (issue #189)."""

    def _doc_cell(self, start_index):
        return {"startIndex": start_index, "content": [{"startIndex": start_index + 1}]}

    def _doc_row(self, *start_indices):
        return {"tableCells": [self._doc_cell(i) for i in start_indices]}

    def test_fontSize_clear_emitted_after_insertText(self):
        # A plain text cell must emit an updateTextStyle clearing fontSize immediately
        # after its insertText so any heading-inherited fontSize is wiped out.
        ast_t = _table(_row(_cell("Hello")))
        doc_t = {"tableRows": [self._doc_row(10)]}
        reqs = _build_fill_requests([doc_t], [ast_t])

        insert_idx = next(i for i, r in enumerate(reqs) if "insertText" in r)
        clear_idx = next(
            i
            for i, r in enumerate(reqs)
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("fields") == "fontSize"
            and r["updateTextStyle"].get("textStyle") == {}
        )
        # Clear must come after insertText in the request list
        assert clear_idx > insert_idx

    def test_fontSize_clear_covers_full_cell_text(self):
        ast_t = _table(_row(_cell("Hello")))
        doc_t = {"tableRows": [self._doc_row(10)]}
        reqs = _build_fill_requests([doc_t], [ast_t])

        clear = next(
            r
            for r in reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("fields") == "fontSize"
            and r["updateTextStyle"].get("textStyle") == {}
        )
        rng = clear["updateTextStyle"]["range"]
        # para_start = 10+1 = 11; text "Hello" = 5 chars → endIndex = 16
        assert rng["startIndex"] == 11
        assert rng["endIndex"] == 16

    def test_explicit_run_font_size_applied_after_clear(self):
        # If a run has an explicit font_size, it must appear AFTER the clear request.
        sized_run = Run("Big", font_size=18.0)
        cell = Cell(children=[sized_run])
        ast_t = _table(_row(cell))
        doc_t = {"tableRows": [self._doc_row(10)]}
        reqs = _build_fill_requests([doc_t], [ast_t])

        clear_idx = next(
            i
            for i, r in enumerate(reqs)
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("fields") == "fontSize"
            and r["updateTextStyle"].get("textStyle") == {}
        )
        explicit_idx = next(
            i
            for i, r in enumerate(reqs)
            if "updateTextStyle" in r and "fontSize" in r["updateTextStyle"].get("textStyle", {})
        )
        assert explicit_idx > clear_idx


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


class TestBuildBlankParaBeforeTableCollapses:
    """_build_blank_para_before_table_collapses shrinks empty paragraphs before tables to
    zero visual height (deleteContentRange is rejected by the API for these paragraphs)."""

    def _doc(self, content):
        return {"body": {"content": content}}

    def _blank_para(self, start, end):
        return {
            "startIndex": start,
            "endIndex": end,
            "paragraph": {"elements": [{"textRun": {"content": "\n"}}]},
        }

    def _text_para(self, start, end, text):
        return {
            "startIndex": start,
            "endIndex": end,
            "paragraph": {"elements": [{"textRun": {"content": text}}]},
        }

    def _table_elem(self, start):
        return {"startIndex": start, "table": {}}

    def test_no_tables_returns_empty(self):
        doc = self._doc([self._blank_para(1, 2), self._text_para(2, 5, "Hi\n")])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_blank_para_before_table_collapsed(self):
        doc = self._doc([self._blank_para(1, 2), self._table_elem(2)])
        result = _build_blank_para_before_table_collapses(doc)
        # 2 requests: updateParagraphStyle + updateTextStyle
        assert len(result) == 2
        rng = {"startIndex": 1, "endIndex": 2}
        ps = result[0]["updateParagraphStyle"]
        assert ps["range"] == rng
        assert ps["paragraphStyle"]["spaceAbove"] == {"magnitude": 0, "unit": "PT"}
        assert ps["paragraphStyle"]["spaceBelow"] == {"magnitude": 0, "unit": "PT"}
        assert ps["paragraphStyle"]["lineSpacing"] == 1
        assert ps["fields"] == "spaceAbove,spaceBelow,lineSpacing"
        ts = result[1]["updateTextStyle"]
        assert ts["range"] == rng
        assert ts["textStyle"]["fontSize"] == {"magnitude": 1, "unit": "PT"}
        assert ts["fields"] == "fontSize"

    def test_non_blank_para_before_table_not_collapsed(self):
        doc = self._doc([self._text_para(1, 8, "Hello\n\n"), self._table_elem(8)])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_table_first_element_not_touched(self):
        doc = self._doc([self._table_elem(1)])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_multiple_blank_paras_before_tables_two_requests_each(self):
        doc = self._doc(
            [
                self._blank_para(1, 2),
                self._table_elem(2),
                self._text_para(10, 15, "Text\n"),
                self._blank_para(15, 16),
                self._table_elem(16),
            ]
        )
        result = _build_blank_para_before_table_collapses(doc)
        # 2 requests per blank para = 4 total
        assert len(result) == 4
        # First pair: blank para at 1
        assert result[0]["updateParagraphStyle"]["range"]["startIndex"] == 1
        assert result[1]["updateTextStyle"]["range"]["startIndex"] == 1
        # Second pair: blank para at 15
        assert result[2]["updateParagraphStyle"]["range"]["startIndex"] == 15
        assert result[3]["updateTextStyle"]["range"]["startIndex"] == 15

    def test_para_before_non_table_not_collapsed(self):
        doc = self._doc([self._blank_para(1, 2), self._text_para(2, 5, "Hi\n")])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_table_preceded_by_table_not_touched(self):
        doc = self._doc([self._table_elem(1), self._table_elem(10)])
        assert _build_blank_para_before_table_collapses(doc) == []
