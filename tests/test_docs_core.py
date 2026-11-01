"""Tests for docs core — HTML/AST pipeline and emitter internals."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Cell,
    Heading,
    Image,
    NamedBlock,
    Paragraph,
    RGBColor,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.content import (
    _html_to_doc_requests,
    _md_to_html,
    _to_doc_requests,
)
from mcp_gee_sweet.tools.docs.emitter import (
    CellImages,
    _build_blank_para_before_table_collapses,
    _build_fill_requests,
    _build_merge_requests,
    _build_phantom_set,
    _inserted_table_length,
    _physical_to_ast_indices,
    _run_group_fill_requests,
    _text_offset_since_last_table,
    ast_to_requests,
    extract_images,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast

# ---------------------------------------------------------------------------
# AST construction helpers
# ---------------------------------------------------------------------------


def _cell(text: str, colspan: int = 1, rowspan: int = 1) -> Cell:
    return Cell(children=[Run(text)], colspan=colspan, rowspan=rowspan)


def _row(*cells: Cell) -> Row:
    return Row(cells=list(cells))


def _no_images() -> CellImages:
    """A fill with no cell images, for the builders that only read `uris`."""
    return CellImages({}, AsyncMock(), lambda _e: None, lambda *_: None)


def _table(*rows: Row) -> Table:
    return Table(rows=list(rows))


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
        # Both items are the same preset and contiguous, so they're grouped into one
        # createParagraphBullets call spanning both paragraphs (#336) rather than one
        # call per item.
        requests, _ = _html_to_doc_requests("<ul><li>Item one</li><li>Item two</li></ul>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_whitespace_only_paragraph_preserves_boundary(self):
        # #402: a whitespace-only paragraph (e.g. spaces, or a lone &nbsp; used
        # as a deliberate markdown blank-line spacer) must not be dropped —
        # dropping it fuses its neighbors together with no gap.
        requests, _ = _html_to_doc_requests("<p>Real content</p><p>   </p><p>More content</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Real content\n   \nMore content\n"

    def test_nbsp_only_paragraph_preserves_boundary(self):
        requests, _ = _html_to_doc_requests("<p>A</p><p>&nbsp;</p><p>B</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "A\n\xa0\nB\n"

    def test_img_and_hr_preserve_paragraph_boundary(self):
        # #401: an unsupported construct (<img>, <hr>) must not fuse its
        # neighbors together — each still gets its own blank line in the
        # final insertText rather than A's endIndex landing on B's startIndex.
        requests, _ = _html_to_doc_requests('<p>A</p><p><img src="x.png"></p><hr><p>B</p>')
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "A\n\n\nB\n"

    def test_table_produces_insert_table_request(self):
        requests, _tables = _html_to_doc_requests(
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
        requests, _tables = _html_to_doc_requests(html)
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

    def test_astral_characters_use_utf16_indices(self):
        requests, _ = _html_to_doc_requests(
            "<p>😀</p><p><b>X</b></p><table><tr><td>T</td></tr></table>"
        )

        styled_x = next(r["updateTextStyle"]["range"] for r in requests if "updateTextStyle" in r)
        table_index = next(
            r["insertTable"]["location"]["index"] for r in requests if "insertTable" in r
        )

        assert styled_x == {"startIndex": 4, "endIndex": 5}
        assert table_index == 6

    def test_astral_characters_use_utf16_indices_inside_table_cells(self):
        runs = [Run("😀"), Run("X", bold=True)]

        requests = _run_group_fill_requests(runs, para_start=10, images=_no_images())
        clear_range = requests[1]["updateTextStyle"]["range"]
        styled_x = requests[2]["updateTextStyle"]["range"]

        assert clear_range == {"startIndex": 10, "endIndex": 13}
        assert styled_x == {"startIndex": 12, "endIndex": 13}
        assert _text_offset_since_last_table(runs, cursor=2) == 3

    def test_astral_characters_use_utf16_indices_for_table_cell_images(self):
        # #1073: a cell image's offset counts UTF-16 units, and the image counts as one.
        img = Image(src="a")
        children = [Run("😀"), img, Run("X")]
        images = CellImages({id(img): "uri-a"}, AsyncMock(), lambda _e: None, lambda *_: None)

        requests = _run_group_fill_requests(children, para_start=10, images=images)
        insert = next(r["insertInlineImage"] for r in requests if "insertInlineImage" in r)

        assert insert["location"]["index"] == 12
        assert _text_offset_since_last_table(children, cursor=3, images=images) == 4
        assert _text_offset_since_last_table(children, cursor=3) == 3

    def test_astral_fallback_text_counts_utf16_indices(self):
        # #1099: an unresolved cell image is written as its fallback text, which a
        # nested table after it must count in UTF-16 units, not code points.
        img = Image(src="a", alt="😀😀")
        children = [Run("X"), img]
        images = CellImages({}, AsyncMock(), lambda _e: None, lambda *_: None)

        requests = _run_group_fill_requests(children, para_start=10, images=images)
        fallback = next(r for r in requests if r.get("insertText", {}).get("text") == "😀😀")
        assert fallback["insertText"]["location"]["index"] == 11
        link = requests[requests.index(fallback) + 1]["updateTextStyle"]
        assert link == {
            "range": {"startIndex": 11, "endIndex": 15},
            "textStyle": {},
            "fields": "link",
        }
        assert _text_offset_since_last_table(children, cursor=2, images=images) == 5

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


def _styled(runs: list, text: str) -> Run:
    """The one run whose text is `text`."""
    (run,) = [r for r in runs if isinstance(r, Run) and r.text == text]
    return run


class TestInlineStrikeBaselineHighlight:
    """#1231: `<del>`/`~~x~~` strike, `<sub>`/`<sup>` baseline, `<mark>` highlight."""

    @pytest.mark.parametrize("tag", ["s", "strike", "del"])
    def test_strike_tags(self, tag):
        nodes = html_to_ast(f"<p>a <{tag}>x</{tag}> b</p>")
        assert _styled(nodes[0].runs, "x").strikethrough is True
        assert _styled(nodes[0].runs, " b").strikethrough is None

    def test_markdown_tildes_strike(self):
        nodes = html_to_ast(_md_to_html("a ~~x~~ b\n"))
        assert _styled(nodes[0].runs, "x").strikethrough is True

    def test_strike_combines_with_other_styles(self):
        nodes = html_to_ast(_md_to_html("***~~x~~***\n"))
        run = _styled(nodes[0].runs, "x")
        assert (run.bold, run.italic, run.strikethrough) == (True, True, True)

    def test_sub_and_sup(self):
        nodes = html_to_ast("<p>H<sub>2</sub>O mc<sup>2</sup>.</p>")
        assert [(r.text, r.baseline_offset) for r in nodes[0].runs] == [
            ("H", None),
            ("2", "SUBSCRIPT"),
            ("O mc", None),
            ("2", "SUPERSCRIPT"),
            (".", None),
        ]

    def test_innermost_baseline_wins(self):
        nodes = html_to_ast("<p><sup>a<sub>b</sub>c</sup>d</p>")
        assert [(r.text, r.baseline_offset) for r in nodes[0].runs] == [
            ("a", "SUPERSCRIPT"),
            ("b", "SUBSCRIPT"),
            ("c", "SUPERSCRIPT"),
            ("d", None),
        ]

    def test_mark_highlights(self):
        nodes = html_to_ast("<p>a <mark><b>hi</b></mark> b</p>")
        run = _styled(nodes[0].runs, "hi")
        assert run.bold is True
        bg = run.background_color
        assert (bg.red, bg.green, bg.blue) == (1.0, 1.0, 0.0)
        assert _styled(nodes[0].runs, " b").background_color is None

    def test_mark_runs_do_not_share_a_color_object(self):
        nodes = html_to_ast("<p><mark>a<b>b</b></mark></p>")
        a, b = nodes[0].runs
        assert a.background_color == b.background_color
        assert a.background_color is not b.background_color

    def test_del_inside_s_keeps_strike_after_del_closes(self):
        nodes = html_to_ast("<p><s>a<del>b</del>c</s>d</p>")
        assert [(r.text, r.strikethrough) for r in nodes[0].runs] == [
            ("a", True),
            ("b", True),
            ("c", True),
            ("d", None),
        ]

    def test_in_table_cell(self):
        nodes = html_to_ast(_md_to_html("| h |\n|---|\n| <sup>x</sup> ~~y~~ <mark>z</mark> |\n"))
        children = nodes[0].rows[1].cells[0].children
        assert _styled(children, "x").baseline_offset == "SUPERSCRIPT"
        assert _styled(children, "y").strikethrough is True
        assert _styled(children, "z").background_color is not None

    def test_requests_carry_the_styles(self):
        requests, _ = _to_doc_requests(
            "~~s~~ H<sub>2</sub>O x<sup>2</sup> <mark>m</mark>", "markdown"
        )
        styles = [r["updateTextStyle"]["textStyle"] for r in requests if "updateTextStyle" in r]
        assert {"strikethrough": True} in styles
        assert {"baselineOffset": "SUBSCRIPT"} in styles
        assert {"baselineOffset": "SUPERSCRIPT"} in styles
        assert {
            "backgroundColor": {"color": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 0.0}}}
        } in styles


# The Run field and value each inline tag sets (#1231).
_INLINE_TAG_FIELDS = {
    "s": ("strikethrough", True),
    "del": ("strikethrough", True),
    "mark": ("background_color", RGBColor(1.0, 1.0, 0.0)),
    "sub": ("baseline_offset", "SUBSCRIPT"),
    "sup": ("baseline_offset", "SUPERSCRIPT"),
}


class TestNewInlineTagsMatchStrikeOnMalformedInput:
    """#1231's review bar: on malformed input each new tag carries its style exactly
    where `<s>` carries strikethrough. Making either match a browser is #1329."""

    _INPUTS = (
        "<p><T>a</p><p>b</p>",
        "<h2><T>a</h2><p>b</p>",
        "<ul><li><T>a</li><li>b</li></ul>",
        "<ul><li><T><p>a</p>b</T></li></ul><p>c</p>",
        "<table><tr><td><T>a</td><td>b</td></tr></table><p>c</p>",
        "<table><tr><td><T>a<table><tr><td>x</td></tr></table>b</T></td></tr></table>",
        "<p><T>a</p></T><p>b</p>",
        "<p><T>a</b>b</T>c</p>",
        "<pre><T>a</pre><p>b</p>",
    )

    @classmethod
    def _texts(cls, nodes) -> list[Run]:
        """Every Run in document order, table cells included."""
        out = []
        for node in nodes:
            if isinstance(node, Run):
                out.append(node)
            elif isinstance(node, Table):
                for row in node.rows:
                    for cell in row.cells:
                        out.extend(cls._texts(cell.children))
            elif hasattr(node, "runs"):
                out.extend(cls._texts(node.runs))
        return out

    def _styled_texts(self, html: str, tag: str) -> list[tuple[str, bool]]:
        field, value = _INLINE_TAG_FIELDS[tag]
        runs = self._texts(html_to_ast(html.replace("T>", f"{tag}>")))
        return [(r.text, getattr(r, field) == value) for r in runs]

    @pytest.mark.parametrize("tag", ["del", "mark", "sub", "sup"])
    @pytest.mark.parametrize("html", _INPUTS)
    def test_same_carry_as_s(self, html, tag):
        assert self._styled_texts(html, tag) == self._styled_texts(html, "s")


class TestLooseListItemKeepsItsBullet:
    """#1111: python-markdown wraps a *loose* list item's text in its own `<p>`
    (so any list with a blank line between items), and the parser treated that
    `<p>` as a sibling block — the `<li>` flushed empty, which emits no bullet at
    all, and the text landed in a plain Paragraph. Every Markdown list with a
    blank line between its items therefore arrived unbulleted."""

    def test_p_directly_inside_li_becomes_the_item(self):
        nodes = html_to_ast("<ul><li><p>Item</p></li></ul>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], BulletItem)
        assert nodes[0].runs[0].text == "Item"

    def test_tight_item_is_unchanged(self):
        nodes = html_to_ast("<ul><li>Item</li></ul>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], BulletItem)
        assert nodes[0].runs[0].text == "Item"

    def test_ordered_loose_item_keeps_its_numbering(self):
        nodes = html_to_ast("<ol><li><p>Item</p></li></ol>")
        assert isinstance(nodes[0], BulletItem)
        assert nodes[0].ordered is True

    def test_loose_item_in_a_blockquote_keeps_both_carried_inwards(self):
        # The issue asks for depth, ordered flag *and* blockquote depth to
        # survive. Neither is a new property of this fix — the transparent `<p>`
        # simply stops discarding the item that already carries them.
        nodes = html_to_ast("<blockquote><ul><li><p>q</p></li></ul></blockquote>")
        assert isinstance(nodes[0], BulletItem)
        assert nodes[0].blockquote_depth == 1

    def test_markdown_loose_list(self):
        nodes = html_to_ast(_md_to_html("- a\n\n- b\n"))
        assert all(isinstance(n, BulletItem) for n in nodes)
        assert [n.runs[0].text for n in nodes] == ["a", "b"]
        assert [n.depth for n in nodes] == [0, 0]
        # One blank line anywhere makes python-markdown wrap *every* item, so the
        # first two — written tight — take the same path (#1115's mixed list).
        mixed = html_to_ast(_md_to_html("- a\n- b\n\n- c\n"))
        assert [n.runs[0].text for n in mixed] == ["a", "b", "c"]
        assert all(isinstance(n, BulletItem) for n in mixed)

    def test_nested_loose_list_keeps_both_depths(self):
        # The issue's own case: the top-level items lost their bullets while the
        # tight nested item kept its depth, so the list arrived half-converted.
        nodes = html_to_ast(_md_to_html("- a\n    - a1\n\n- b\n"))
        assert all(isinstance(n, BulletItem) for n in nodes)
        assert [n.depth for n in nodes] == [0, 1, 0]

    def test_inline_formatting_survives_the_item(self):
        nodes = html_to_ast("<ul><li><p><b>bold</b> plain</p></li></ul>")
        assert isinstance(nodes[0], BulletItem)
        assert next(r for r in nodes[0].runs if r.bold).text == "bold"

    def test_task_marker_in_a_loose_item(self):
        # [x]/[ ] is read off the item's first run, so a lost bullet also lost
        # the checkbox.
        nodes = html_to_ast(_md_to_html("- [x] done\n\n- [ ] todo\n"))
        assert [n.checked for n in nodes] == [True, False]

    def test_tag_padding_stays_out_of_the_item_runs(self):
        # What markdown actually emits: newlines between <li>, <p> and </li>.
        # They are HTML padding, not item text — the tight form never sees them.
        nodes = html_to_ast("<ul>\n<li>\n<p>a</p>\n</li>\n</ul>")
        assert "".join(r.text for r in nodes[0].runs) == "a"

    def test_whitespace_only_loose_item_is_an_empty_bullet_like_the_tight_one(self):
        # A loose item's `<p>` is the item itself, so the item rule applies: an
        # item holding only whitespace is an empty bullet (#1075), loose or tight.
        for html in ("<ul><li><p>&nbsp;</p></li></ul>", "<ul><li>&nbsp;</li></ul>"):
            nodes = html_to_ast(html)
            assert [type(n) for n in nodes] == [BulletItem]
            assert nodes[0].runs == []

    def test_whitespace_only_loose_item_does_not_swallow_its_neighbours(self):
        nodes = html_to_ast("<ul><li><p>Real</p></li><li><p>&nbsp;</p></li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, BulletItem]
        assert ["".join(r.text for r in n.runs) for n in nodes] == ["Real", ""]

    def test_empty_paragraph_item_is_an_empty_bullet(self):
        nodes = html_to_ast("<ul><li><p></p></li><li>Real</li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, BulletItem]
        assert nodes[0].runs == []
        assert nodes[1].runs[0].text == "Real"

    def test_second_paragraph_in_an_item_is_still_a_separate_block(self):
        # Only the item's first paragraph is transparent. A later one is a block
        # inside the item, marked with the item's depth (#1094).
        nodes = html_to_ast("<ul><li><p>a</p><p>b</p></li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, Paragraph]
        assert nodes[1].list_depth == 0
        assert nodes[1].list_path == nodes[0].list_path

    # Once the `<li>` resumes after a nested block, its first paragraph is
    # already used, so the next `<p>` must not join the item again: that would
    # emit it as a new bullet (or a new number in an ordered list).

    def test_paragraph_after_a_nested_list_is_not_a_new_item(self):
        nodes = html_to_ast(_md_to_html("- a\n    - b\n\n    c\n"))
        assert [type(n) for n in nodes] == [BulletItem, BulletItem, Paragraph]
        assert [n.depth for n in nodes[:2]] == [0, 1]
        assert nodes[2].runs[0].text == "c"
        # Under a: column 4 is short of b's content column (6).
        assert nodes[2].list_depth == 0

    def test_third_paragraph_in_an_item_is_not_a_new_item(self):
        nodes = html_to_ast(_md_to_html("- a\n\n    b\n\n    c\n"))
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, Paragraph]
        assert [n.runs[0].text for n in nodes] == ["a", "b", "c"]

    def test_paragraph_after_a_quote_in_an_ordered_item_is_not_a_new_number(self):
        nodes = html_to_ast(_md_to_html("1. a\n\n    > q\n\n    c\n"))
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, Paragraph]
        assert nodes[0].ordered is True
        assert [n.blockquote_depth for n in nodes] == [0, 1, 0]
        assert nodes[2].runs[0].text == "c"
        assert [n.list_depth for n in nodes[1:]] == [0, 0]

    def test_paragraph_after_a_code_block_in_an_ordered_item_is_not_a_new_number(self):
        # An indented code block: python-markdown doesn't parse a fence inside a
        # list item.
        nodes = html_to_ast(_md_to_html("1. a\n\n        x\n\n    c\n"))
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, Paragraph]
        assert nodes[0].ordered is True
        assert nodes[2].runs[0].text == "c"

    def test_loose_list_after_a_resumed_item_keeps_its_bullets(self):
        # The guard only stops a resumed item's `<p>`; the next item's first
        # paragraph is still transparent.
        nodes = html_to_ast(_md_to_html("- a\n    - b\n\n    c\n\n- d\n\n- e\n"))
        assert [type(n) for n in nodes] == [
            BulletItem,
            BulletItem,
            Paragraph,
            BulletItem,
            BulletItem,
        ]
        assert [n.runs[0].text for n in nodes] == ["a", "b", "c", "d", "e"]

    def test_named_style_paragraph_inside_an_item_keeps_its_style(self):
        # A styled paragraph isn't the item's transparent `<p>`: it's a block inside
        # the item, which has no text of its own and so is an empty bullet (#1075).
        nodes = html_to_ast('<ul><li><p data-style="title">T</p></li></ul>')
        assert [type(n) for n in nodes] == [BulletItem, NamedBlock]
        assert nodes[0].runs == []
        assert nodes[1].style_type == "TITLE"
        assert nodes[1].list_depth == 0

    def test_emitter_bullets_the_loose_list(self):
        # End to end: the requests actually sent to Docs must carry the bullets,
        # and the inserted text must not have gained the HTML padding.
        requests, _ = _html_to_doc_requests(_md_to_html("- a\n\n- b\n"))
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 1
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "a\nb\n"


class TestBlockInsideListItemAst:
    """#1094: a block inside a list item is its own node, marked with the item's
    list_depth and list_path, and never a new BulletItem."""

    def test_each_block_kind_names_its_item(self):
        for block in ("> q", "#### H", "***", "```\n   x\n   ```", "![i](http://e.com/i.png)"):
            nodes = html_to_ast(_md_to_html(f"1. a\n\n   {block}\n\n2. b\n"))
            inner = [n for n in nodes if not isinstance(n, BulletItem)]
            assert len(inner) == 1, block
            assert inner[0].list_depth == 0, block
            assert inner[0].list_path == nodes[0].list_path, block
            assert [type(n) for n in (nodes[0], nodes[-1])] == [BulletItem, BulletItem]

    def test_table_names_its_item(self):
        nodes = html_to_ast(_md_to_html("- a\n\n  | K | V |\n  |---|---|\n  | k | v |\n- b\n"))
        assert isinstance(nodes[1], Table)
        assert nodes[1].list_depth == 0
        assert nodes[1].list_path == nodes[0].list_path

    def test_block_under_a_nested_item_names_the_nested_item(self):
        nodes = html_to_ast(_md_to_html("1. a\n   - b\n\n     > q\n\n   - c\n"))
        assert [type(n) for n in nodes] == [BulletItem, BulletItem, Paragraph, BulletItem]
        assert nodes[2].list_depth == 1
        assert nodes[2].list_path == nodes[1].list_path

    def test_text_after_a_rule_in_an_item_is_not_a_new_bullet(self):
        # Raw <li>a<hr>b</li> gave two bullets (PR #1228 QA round 4).
        nodes = html_to_ast("<ul><li>a<hr>b</li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, Paragraph]
        assert [n.list_depth for n in nodes[1:]] == [0, 0]

    def test_text_after_a_nested_list_in_a_transparent_paragraph_is_not_a_bullet(self):
        # #1266 edge case 2: "tail" came out as a third bullet at depth 0.
        nodes = html_to_ast("<ul><li><p>a<ul><li>x</li></ul>tail</p></li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, BulletItem, Paragraph]
        assert nodes[2].runs[0].text == "tail"
        assert nodes[2].list_depth == 0

    def test_block_left_open_until_its_list_closes_keeps_its_item(self):
        # PR #1301 QA round 1: flushed after </ul> popped the list, so the live stack
        # no longer matched the item and b fell to the margin.
        nodes = html_to_ast("<ul><li>a<p>b</ul>")
        assert [type(n) for n in nodes] == [BulletItem, Paragraph]
        assert nodes[1].list_depth == 0

    def test_text_after_a_list_with_an_unclosed_item_keeps_the_outer_item(self):
        # PR #1301 QA round 2: x's unclosed <li> left a frame on the stack after
        # </ul>, which stopped the walk, so z fell to the margin.
        nodes = html_to_ast("<ul><li>a<ul><li>x<p>y</ul>z</li></ul>")
        assert [(type(n), n.runs[0].text) for n in nodes] == [
            (BulletItem, "a"),
            (BulletItem, "x"),
            (Paragraph, "y"),
            (Paragraph, "z"),
        ]
        assert [(n.list_depth, n.list_path) for n in nodes[2:]] == [
            (1, nodes[1].list_path),
            (0, nodes[0].list_path),
        ]

    def test_stale_frame_from_a_closed_list_is_not_matched(self):
        # PR #1301 QA round 3: matching frames by list depth let "loose", a block
        # loose in q's nested list, take item x's stale frame from the first list.
        nodes = html_to_ast(
            "<ul><li>a<ul><li>x<p>y</ul></li></ul>"
            "<ul><li>q<ul><li>r</li><p>loose</p></ul></li></ul>"
        )
        loose = nodes[-1]
        assert loose.runs[0].text == "loose"
        assert loose.list_depth is None
        assert loose.list_path == ()

    def test_heading_item_interrupted_before_its_close_tag(self):
        # PR #1301 QA round 1: </h1> after the nested list fell through to the inline
        # end-tag path and decremented _tag_depth, so the later bare "z" and <hr>
        # became paragraphs inside the <span>.
        interrupted = html_to_ast(
            "<span><ul><li><h1>T<ul><li>x</li></ul></h1>a</li></ul>z<hr></span>"
        )
        plain = html_to_ast("<span><ul><li><h1>T</h1>a</li></ul>z<hr></span>")
        assert [(type(n), n.runs[0].text) for n in interrupted] == [
            (BulletItem, "T"),
            (BulletItem, "x"),
            (Paragraph, "a"),
        ]
        assert interrupted[0].heading_level == 1
        assert [type(n) for n in plain] == [BulletItem, Paragraph]

    def test_block_loose_in_a_nested_list_belongs_to_no_item(self):
        # Not inside the outer item's own content: a list opened since.
        nodes = html_to_ast("<ul><li>a<ul><li>b</li><p>stray</p></ul></li></ul>")
        assert nodes[2].list_depth is None

    def test_block_outside_every_list_has_no_list_depth(self):
        nodes = html_to_ast(_md_to_html("- a\n\n> q\n\npara\n"))
        assert [n.list_depth for n in nodes[1:]] == [None, None]

    def test_heading_that_opens_an_item_is_the_item(self):
        nodes = html_to_ast(_md_to_html("- # Title\n  more\n- b\n"))
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, BulletItem]
        assert nodes[0].heading_level == 1
        assert nodes[0].runs[0].text == "Title"
        assert nodes[1].list_depth == 0
        assert nodes[2].heading_level is None

    def test_setext_heading_under_an_item_is_the_item(self):
        nodes = html_to_ast(_md_to_html("- a\n  ---\n- b\n"))
        assert [(type(n), n.heading_level) for n in nodes] == [(BulletItem, 2), (BulletItem, None)]

    def test_heading_after_item_text_is_a_block_inside_it(self):
        nodes = html_to_ast(_md_to_html("- a\n  #### H\n- b\n"))
        assert [type(n) for n in nodes] == [BulletItem, Heading, BulletItem]
        assert nodes[0].heading_level is None
        assert nodes[1].list_depth == 0

    def test_second_heading_in_an_item_is_a_block_inside_it(self):
        nodes = html_to_ast("<ul><li><h2>a</h2><h2>b</h2></li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, Heading]
        assert nodes[0].heading_level == 2
        assert nodes[1].list_depth == 0

    def test_heading_item_keeps_its_inline_formatting(self):
        nodes = html_to_ast("<ul><li><h3>a <b>bold</b></h3></li></ul>")
        assert len(nodes) == 1
        assert [(r.text, r.bold) for r in nodes[0].runs] == [("a ", None), ("bold", True)]


class TestUnsupportedConstructPreservesParagraphBoundary:
    """#401: a construct the converter can't represent (<hr>) must leave
    behind an empty block rather than deleting the paragraph boundary
    itself, so adjacent content doesn't fuse together. <img> used to be in
    this category too, but #333 makes it a genuinely supported construct —
    see TestImageParsing below for its own coverage — so this class now
    documents that its paragraph boundary is preserved by carrying the real
    Image node forward, not by leaving an empty placeholder."""

    def test_img_wrapped_in_paragraph_preserves_boundary_with_real_content(self):
        nodes = html_to_ast('<p>A</p><p><img src="x.png"></p><p>B</p>')
        assert len(nodes) == 3
        assert [isinstance(n, Paragraph) for n in nodes] == [True, True, True]
        assert nodes[0].runs[0].text == "A"
        assert len(nodes[1].runs) == 1
        assert isinstance(nodes[1].runs[0], Image)
        assert nodes[1].runs[0].src == "x.png"
        assert nodes[2].runs[0].text == "B"

    def test_bare_hr_between_paragraphs_leaves_empty_paragraph(self):
        nodes = html_to_ast("<p>A</p><hr><p>B</p>")
        assert len(nodes) == 3
        assert [isinstance(n, Paragraph) for n in nodes] == [True, True, True]
        assert nodes[0].runs[0].text == "A"
        assert nodes[1].runs == []
        assert nodes[2].runs[0].text == "B"

    def test_underscore_hr_between_paragraphs_leaves_empty_paragraph(self):
        # python-markdown renders both "---" and "___" thematic breaks the
        # same way (<hr />) — confirmed in issue #401's own follow-up comment.
        nodes = html_to_ast("<p>A</p><hr /><p>B</p>")
        assert len(nodes) == 3
        assert nodes[1].runs == []

    def test_hr_wrapped_in_inline_tag_with_no_block_ancestor_still_dropped(self):
        # PR #406 QA pass 2: the bare-<hr> check omitted the _tag_depth == 0
        # condition that handle_data's sibling bare-text check uses (#343),
        # so an <hr> wrapped only in an inline tag with no block ancestor
        # (e.g. "<span><hr></span>") spuriously injected a paragraph
        # boundary — contradicting the existing, tested policy that
        # inline-only content with no block ancestor is a deliberate no-op
        # (see test_span_wrapped_text_still_dropped in test_docs_content.py).
        assert html_to_ast("<span><hr></span>") == []

    def test_whitespace_only_paragraph_preserved(self):
        # #402: unlike the runs=[] case above (gated on preserve_if_empty),
        # a paragraph with actual (whitespace) runs is always kept — there's
        # real, if invisible, content to lose, not just a boundary.
        nodes = html_to_ast("<p>A</p><p>   </p><p>B</p>")
        assert len(nodes) == 3
        assert nodes[0].runs[0].text == "A"
        assert nodes[1].runs[0].text == "   "
        assert nodes[2].runs[0].text == "B"

    def test_nbsp_only_paragraph_preserved(self):
        nodes = html_to_ast("<p>A</p><p>&nbsp;</p><p>B</p>")
        assert len(nodes) == 3
        assert nodes[1].runs[0].text == "\xa0"

    def test_nbsp_only_list_item_is_an_empty_bullet(self):
        # PR #441 dropped this item, since #402's whitespace-preserve fix is a
        # <p>-specific blank-line-spacer convention. #1075 made every item a
        # bullet, so it's an empty one: the item keeps its marker, not the nbsp.
        nodes = html_to_ast("<ul><li>Real</li><li>&nbsp;</li><li>More</li></ul>")
        assert ["".join(r.text for r in n.runs) for n in nodes] == ["Real", "", "More"]
        assert all(isinstance(n, BulletItem) for n in nodes)

    def test_nbsp_only_heading_still_dropped(self):
        nodes = html_to_ast("<h1>Title</h1><h1>&nbsp;</h1><h1>Next</h1>")
        assert len(nodes) == 2
        assert nodes[0].runs[0].text == "Title"
        assert nodes[1].runs[0].text == "Next"

    def test_resumed_list_item_trailing_nbsp_preserved(self):
        # #444: a resumed block's whitespace-only trailing flush is normally
        # dropped as markup-formatting noise (test_nested_list_via_markdown_
        # preserves_parent_text in test_docs_content.py covers that case with
        # a plain "\n"), but an actual "&nbsp;" placed right after a nested
        # list, still inside the same <li>, decodes to "\xa0" — a character
        # no pretty-printer emits as indentation — and must survive instead
        # of vanishing with no trace, unlike the fresh-<li> case just above.
        nodes = html_to_ast("<ul><li>Item<ul><li>x</li></ul>&nbsp;</li></ul>")
        assert len(nodes) == 3
        assert nodes[0].runs[0].text == "Item"
        assert nodes[1].runs[0].text == "x"
        assert nodes[2].runs[0].text == "\xa0"

    def test_resumed_list_item_trailing_nbsp_with_leading_newline_not_split(self):
        # PR #772 QA round 1, finding 1: a literal newline commonly sits
        # between a nested list's "</ul>" and the following "&nbsp;" (real
        # markdown/pretty-printed HTML rarely puts them adjacent with no
        # whitespace at all, unlike the test above's minimal repro) — the
        # unstripped "\n\xa0" run text would reach the Docs API as literal
        # inserted text, which splits on any "\n" into a spurious extra
        # paragraph (#719) regardless of styling. The preserved run must
        # carry only the authored "\xa0", with the formatting-noise
        # newline stripped out before it ever reaches that point.
        html = "<ul><li>Item<ul><li>x</li></ul>\n&nbsp;</li></ul>"
        nodes = html_to_ast(html)
        assert len(nodes) == 3
        assert nodes[2].runs[0].text == "\xa0"

    def test_resumed_list_item_trailing_plain_whitespace_still_dropped(self):
        # Control for the test above: plain ASCII whitespace (not an entity)
        # after the same nested-list interruption is still markup-formatting
        # noise and must still be dropped — the #444 fix is scoped to a
        # character _is_formatting_whitespace doesn't recognize, not to
        # "resumed block has any trailing text at all".
        nodes = html_to_ast("<ul><li>Item<ul><li>x</li></ul>\n</li></ul>")
        assert len(nodes) == 2
        assert nodes[0].runs[0].text == "Item"
        assert nodes[1].runs[0].text == "x"

    def test_resumed_paragraph_trailing_nbsp_preserved(self):
        # Same #444 fix, <p> instead of <li> — a resumed <p>'s trailing
        # "&nbsp;" after a nested table must survive the same way a fresh
        # <p>&nbsp;</p> already does (test_nbsp_only_paragraph_preserved).
        html = "<p>Before<table><tr><td>cell</td></tr></table>&nbsp;</p>"
        nodes = html_to_ast(html)
        assert nodes[0].runs[0].text == "Before"
        assert isinstance(nodes[-1], Paragraph)
        assert nodes[-1].runs[0].text == "\xa0"

    def test_resumed_pre_trailing_nbsp_preserved(self):
        # Same #444 fix applied to the <pre> close-tag handler's own
        # independent fresh-vs-resumed whitespace check (#443).
        html = "<pre>before<table><tr><td>cell</td></tr></table>&nbsp;</pre>"
        nodes = html_to_ast(html)
        assert nodes[0].runs[0].text == "before"
        assert nodes[-1].runs[0].text == "\xa0"

    def test_resumed_pre_trailing_nbsp_with_leading_newline_not_split(self):
        # PR #772 QA round 1, finding 1's <pre> sibling case.
        html = "<pre>before<table><tr><td>cell</td></tr></table>\n&nbsp;</pre>"
        nodes = html_to_ast(html)
        assert nodes[-1].runs[0].text == "\xa0"

    def test_resumed_pre_real_multiline_content_not_stripped(self):
        # Control for the fix above: a resumed <pre> can also carry genuine
        # multi-line content of its own (not just whitespace-plus-entity) —
        # its newlines are real, significant <pre> text and must NOT be
        # stripped just because is_resumed_authored_whitespace is also true
        # for non-whitespace text (it only checks "not all-formatting-
        # whitespace", which is trivially true for real content too).
        html = "<pre>before<table><tr><td>cell</td></tr></table>line1\nline2</pre>"
        nodes = html_to_ast(html)
        assert nodes[-1].runs[0].text == "line1\nline2"

    def test_resumed_list_item_trailing_vertical_tab_preserved(self):
        # PR #772 QA round 1, finding 2: "\v"/"\f" were originally included
        # in the ASCII-formatting-whitespace whitelist despite qualifying
        # for the exact same authored-content reasoning as "\xa0" — no
        # pretty-printer emits either as structural indentation, so a
        # genuinely-typed one (e.g. pasted from a terminal) must survive
        # instead of being silently dropped as if it were noise.
        nodes = html_to_ast("<ul><li>Item<ul><li>x</li></ul>\x0b</li></ul>")
        assert len(nodes) == 3
        assert nodes[2].runs[0].text == "\x0b"

    def test_resumed_pre_trailing_plain_whitespace_still_dropped(self):
        # Control for the <pre> case: plain ASCII whitespace noise between
        # the nested table's close and </pre> is still dropped — only the
        # "before" paragraph and the table itself remain, no trailing node
        # for the resumed <pre>'s own whitespace-only flush.
        html = "<pre>before<table><tr><td>cell</td></tr></table>\n</pre>"
        nodes = html_to_ast(html)
        assert len(nodes) == 2
        assert nodes[0].runs[0].text == "before"
        assert isinstance(nodes[1], Table)

    def test_dropped_construct_survives_interruption_by_nested_list(self):
        # #401 follow-up (PR #406, TC-DOC136): _interrupt_open_block flushed
        # the currently-open block before descending into a nested construct
        # with preserve_if_empty always False, so a bullet whose only content
        # was an unsupported construct vanished entirely — not just that
        # construct's own content — whenever it was interrupted by its own
        # nested list instead of closing directly. TC-DOC135's own review
        # round live-reproduced this exact gap using <img> as the dropped
        # construct; #333 makes <img> itself supported (see
        # test_image_survives_interruption_by_nested_list below for that same
        # shape with a real Image node preserved instead of an empty runs
        # list). A bare <hr> stood in here until #1075, which made a fresh <li>
        # always emit its bullet and the rule a block inside the item (PR #1322
        # QA round 1): the bullet survives the interruption, now with its rule.
        html = "<ul><li><hr><ul><li>nested</li></ul></li></ul>"
        nodes = html_to_ast(html)
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, BulletItem]
        assert nodes[0].runs == []
        assert nodes[1].list_depth == 0
        assert (nodes[2].runs[0].text, nodes[2].depth) == ("nested", 1)

    def test_image_survives_interruption_by_nested_list(self):
        # #333 companion to the dropped-construct test above: a bullet whose
        # only content is an <img> must carry the real Image node forward
        # through the same interrupt/resume path, not an empty runs list.
        html = '<ul><li><img src="x.png"><ul><li>nested</li></ul></li></ul>'
        nodes = html_to_ast(html)
        assert [isinstance(n, BulletItem) for n in nodes] == [True, True]
        assert len(nodes[0].runs) == 1
        assert isinstance(nodes[0].runs[0], Image)
        assert nodes[0].runs[0].src == "x.png"
        assert nodes[1].runs[0].text == "nested"

    def test_parent_with_no_own_text_is_an_empty_bullet(self):
        # An <li> that wraps only a nested list, with no text and no dropped
        # construct of its own, is an empty bullet (#1075), with the child one
        # level under it.
        html = "<ul><li><ul><li>child</li></ul></li></ul>"
        nodes = html_to_ast(html)
        assert [(type(n), n.depth) for n in nodes] == [(BulletItem, 0), (BulletItem, 1)]
        assert nodes[0].runs == []
        assert nodes[1].runs[0].text == "child"


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


class TestBlockquoteEmitter:
    """Blockquote paragraphs get a left border + scaled indent (#476) — the closest
    visual equivalent to a real blockquote style the Docs API's ParagraphStyle
    exposes, since Google Docs has no native blockquote namedStyleType."""

    def _blockquote_style_requests(self, requests):
        return [
            r["updateParagraphStyle"]
            for r in requests
            if "updateParagraphStyle" in r
            and "borderLeft" in r["updateParagraphStyle"]["paragraphStyle"]
        ]

    def test_blockquote_paragraph_gets_border_and_indent(self):
        requests, _ = _html_to_doc_requests("<blockquote><p>Quoted</p></blockquote>")
        bq_requests = self._blockquote_style_requests(requests)
        assert len(bq_requests) == 1
        style = bq_requests[0]["paragraphStyle"]
        assert style["borderLeft"]["dashStyle"] == "SOLID"
        assert style["indentStart"]["magnitude"] == 36
        assert bq_requests[0]["fields"] == "indentStart,indentFirstLine,borderLeft"

    def test_blockquote_first_line_indented_like_the_rest(self):
        """indentFirstLine is absolute: unset, a single-line quote's only line sat at
        the margin (#1056)."""
        requests, _ = _html_to_doc_requests("<blockquote><p>Quoted</p></blockquote>")
        style = self._blockquote_style_requests(requests)[0]["paragraphStyle"]
        assert style["indentFirstLine"]["magnitude"] == 36

    def test_plain_paragraph_gets_no_border(self):
        requests, _ = _html_to_doc_requests("<p>Not quoted</p>")
        assert self._blockquote_style_requests(requests) == []

    def test_nested_blockquote_doubles_indent(self):
        html = "<blockquote><p>outer</p><blockquote><p>inner</p></blockquote></blockquote>"
        requests, _ = _html_to_doc_requests(html)
        bq_requests = self._blockquote_style_requests(requests)
        for key in ("indentStart", "indentFirstLine"):
            magnitudes = sorted(r["paragraphStyle"][key]["magnitude"] for r in bq_requests)
            assert magnitudes == [36, 72]

    def test_blockquote_wrapping_bullet_item_gets_border(self):
        html = "<blockquote><ul><li>a</li></ul></blockquote>"
        requests, _ = _html_to_doc_requests(html)
        assert len(self._blockquote_style_requests(requests)) == 1

    @staticmethod
    def _is_bq(r):
        return (
            "updateParagraphStyle" in r
            and "borderLeft" in (r["updateParagraphStyle"]["paragraphStyle"])
        )

    def _bullet_quote_requests(self, requests):
        """Each quoted bullet's style request, checked to come after the whole bullet
        pass (createParagraphBullets overwrites both indents, #1056) and before any
        table/image insert, whose positions the ranges are not adjusted for."""
        bullet_pass = [
            i
            for i, r in enumerate(requests)
            if "createParagraphBullets" in r
            # an isolated run's anchor delete, not a table's placeholder delete (#1097)
            or ("deleteContentRange" in r and "insertTable" not in requests[i - 1])
        ]
        inserts = [
            i for i, r in enumerate(requests) if "insertTable" in r or "insertInlineImage" in r
        ]
        bq = [(i, r["updateParagraphStyle"]) for i, r in enumerate(requests) if self._is_bq(r)]
        for i, _ in bq:
            assert all(i > b for b in bullet_pass)
            assert all(i < k for k in inserts)
        return [r for _, r in bq]

    def _html_bullet_quote_requests(self, html):
        requests, _ = _html_to_doc_requests(html)
        return self._bullet_quote_requests(requests)

    def test_quoted_bullet_indent_adds_to_list_level_indent(self):
        """Level-0 list item: the preset's 36/18 plus the 36pt quote indent."""
        (req,) = self._html_bullet_quote_requests("<blockquote><ul><li>a</li></ul></blockquote>")
        style = req["paragraphStyle"]
        assert style["indentStart"]["magnitude"] == 72
        assert style["indentFirstLine"]["magnitude"] == 54
        assert req["range"] == {"startIndex": 1, "endIndex": 3}

    def test_quoted_nested_bullets_ranges_follow_tab_consumption(self):
        """Ranges are post-bullets: each item has lost its own leading tabs and every
        earlier item's."""
        html = (
            "<blockquote><ul><li>a<ul><li>bb<ul><li>ccc</li></ul></li></ul></li>"
            "<li>d</li></ul></blockquote>"
        )
        reqs = self._html_bullet_quote_requests(html)
        # Final text: "a\n" [1,3), "bb\n" [3,6), "ccc\n" [6,10), "d\n" [10,12).
        assert [r["range"] for r in reqs] == [
            {"startIndex": 1, "endIndex": 3},
            {"startIndex": 3, "endIndex": 6},
            {"startIndex": 6, "endIndex": 10},
            {"startIndex": 10, "endIndex": 12},
        ]
        assert [r["paragraphStyle"]["indentStart"]["magnitude"] for r in reqs] == [72, 108, 144, 72]
        assert [r["paragraphStyle"]["indentFirstLine"]["magnitude"] for r in reqs] == [
            54,
            90,
            126,
            54,
        ]

    def test_quoted_bullet_after_earlier_nested_run(self):
        """An earlier run's consumed tab shifts a later quoted item's range too."""
        html = (
            "<ul><li>x<ul><li>y</li></ul></li></ul><p>mid</p>"
            "<blockquote><ol><li>q</li></ol></blockquote>"
        )
        (req,) = self._html_bullet_quote_requests(html)
        # Pre-bullets text: "x\n\ty\nmid\nq\n", "q\n" at [10,12); the "\t" goes.
        assert req["range"] == {"startIndex": 9, "endIndex": 11}

    def test_quoted_bullet_styled_before_table_insert(self):
        """A table after a quoted list: the quote request uses post-bullets text
        positions, so it must run before the insertTable that shifts them again."""
        html = (
            "<blockquote><ul><li>a<ul><li>b</li></ul></li></ul></blockquote>"
            "<table><tr><td>t</td></tr></table>"
        )
        reqs = self._html_bullet_quote_requests(html)
        assert [r["range"] for r in reqs] == [
            {"startIndex": 1, "endIndex": 3},
            {"startIndex": 3, "endIndex": 5},
        ]

    def test_quoted_isolated_bullet_run(self):
        """An isolated (no depth-0 item) quoted run: the anchor insert/delete nets to
        zero, so the range is the item minus its own tab."""
        from mcp_gee_sweet.tools.docs.ast import BulletItem, Run
        from mcp_gee_sweet.tools.docs.emitter import ast_to_requests

        nodes = [BulletItem(runs=[Run(text="deep")], depth=1, blockquote_depth=2)]
        requests, _ = ast_to_requests(nodes)
        (req,) = self._bullet_quote_requests(requests)
        assert req["range"] == {"startIndex": 1, "endIndex": 6}
        assert req["paragraphStyle"]["indentStart"]["magnitude"] == 72 + 72
        assert req["paragraphStyle"]["indentFirstLine"]["magnitude"] == 54 + 72

    def test_quoted_bullet_list_level_capped_at_8(self):
        """Docs caps nestingLevel at 8, so an item deeper than that sits at level 8 and
        its quote indent adds to level 8's indents, not a level that doesn't exist
        (PR #1089 QA round 1)."""
        from mcp_gee_sweet.tools.docs.ast import BulletItem, Run
        from mcp_gee_sweet.tools.docs.emitter import ast_to_requests

        nodes = [
            BulletItem(runs=[Run(text=f"l{d}")], depth=d, blockquote_depth=1) for d in range(11)
        ]
        requests, _ = ast_to_requests(nodes)
        reqs = self._bullet_quote_requests(requests)
        starts = [r["paragraphStyle"]["indentStart"]["magnitude"] for r in reqs]
        first_lines = [r["paragraphStyle"]["indentFirstLine"]["magnitude"] for r in reqs]
        assert starts[8:] == [36 + 36 * 8 + 36] * 3
        assert first_lines[8:] == [18 + 36 * 8 + 36] * 3
        assert starts[7] == 36 + 36 * 7 + 36


class TestBlockquotePath:
    """html_parser gives each <blockquote> its own id, so adjacent quotes stay
    distinguishable once flattened to blockquote_depth (#1098)."""

    def test_separate_quotes_get_different_paths(self):
        a, b = html_to_ast("<blockquote><p>a</p></blockquote><blockquote><p>b</p></blockquote>")
        assert len(a.blockquote_path) == len(b.blockquote_path) == 1
        assert a.blockquote_path != b.blockquote_path

    def test_paragraphs_of_one_quote_share_a_path(self):
        a, b = html_to_ast("<blockquote><p>a</p><p>b</p></blockquote>")
        assert a.blockquote_path == b.blockquote_path

    def test_nested_quote_path_extends_the_outer(self):
        outer, inner, tail = html_to_ast(
            "<blockquote><p>o</p><blockquote><p>i</p></blockquote><p>t</p></blockquote>"
        )
        assert inner.blockquote_path[:1] == outer.blockquote_path
        assert inner.blockquote_depth == len(inner.blockquote_path) == 2
        assert tail.blockquote_path == outer.blockquote_path

    def test_every_quoted_node_type_gets_a_path(self):
        nodes = html_to_ast(
            "<blockquote><h2>h</h2><ul><li>l</li></ul><pre><code>c</code></pre>"
            "<p>i<hr></p></blockquote>"
        )
        assert nodes
        assert all(len(n.blockquote_path) == n.blockquote_depth == 1 for n in nodes)

    def test_unquoted_node_has_empty_path(self):
        (node,) = html_to_ast("<p>plain</p>")
        assert node.blockquote_path == ()

    def test_path_ignored_by_equality(self):
        """The ids are arbitrary counters, so they don't make otherwise equal nodes
        differ."""
        a = Paragraph(runs=[Run("x")], blockquote_depth=1, blockquote_path=(1,))
        b = Paragraph(runs=[Run("x")], blockquote_depth=1, blockquote_path=(7,))
        assert a == b


class TestBlockSeparation:
    """Adjacent blocks stay apart (#1098): Docs joins the borders of adjacent paragraphs
    styled alike, so separate quotes get an unbordered, collapsed separator paragraph;
    quotes get space where they meet other content; code blocks get space around
    them."""

    @staticmethod
    def _inserted_text(requests):
        return requests[0]["insertText"]["text"]

    @staticmethod
    def _spacing(requests):
        """{startIndex: {field: magnitude}} for every spaceAbove/spaceBelow > 0."""
        found: dict[int, dict[str, int]] = {}
        for r in requests:
            ps = r.get("updateParagraphStyle")
            if not ps:
                continue
            for field in ("spaceAbove", "spaceBelow"):
                magnitude = ps["paragraphStyle"].get(field, {}).get("magnitude")
                if magnitude:
                    found.setdefault(ps["range"]["startIndex"], {})[field] = magnitude
        return found

    @staticmethod
    def _collapsed_ranges(requests):
        return [
            r["updateTextStyle"]["range"]
            for r in requests
            if "updateTextStyle" in r
            and r["updateTextStyle"]["textStyle"].get("fontSize", {}).get("magnitude") == 1
        ]

    def test_separate_quotes_get_a_collapsed_separator(self):
        requests, _ = _html_to_doc_requests(
            "<blockquote><p>a</p></blockquote><blockquote><p>b</p></blockquote>"
        )
        # "a\n" [1,3), separator "\n" [3,4), "b\n" [4,6).
        assert self._inserted_text(requests) == "a\n\nb\n"
        assert self._collapsed_ranges(requests) == [{"startIndex": 3, "endIndex": 4}]
        bordered = [
            r["updateParagraphStyle"]["range"]
            for r in requests
            if "borderLeft" in r.get("updateParagraphStyle", {}).get("paragraphStyle", {})
        ]
        assert {"startIndex": 3, "endIndex": 4} not in bordered
        # spaceBelow targets each node's last character, its "\n". The separator is
        # spaced on one side only: spaced on both, two quotes sat twice as far apart as
        # a quote and a paragraph (PR #1199 QA round 1).
        assert self._spacing(requests) == {
            1: {"spaceAbove": 8},
            2: {"spaceBelow": 8},
            5: {"spaceBelow": 8},
        }

    def test_one_quote_gets_no_separator_and_no_inner_spacing(self):
        requests, _ = _html_to_doc_requests(
            "<p>x</p><blockquote><p>a</p><p>b</p></blockquote><p>y</p>"
        )
        assert self._inserted_text(requests) == "x\na\nb\ny\n"
        assert self._collapsed_ranges(requests) == []
        # "a\n" starts at 3, "b\n" at 5: space above the quote and below it only.
        assert self._spacing(requests) == {3: {"spaceAbove": 8}, 6: {"spaceBelow": 8}}

    def test_nested_quote_continuing_its_outer_quote_not_separated(self):
        requests, _ = _html_to_doc_requests(
            "<blockquote><p>o</p><blockquote><p>i</p></blockquote><p>t</p></blockquote>"
        )
        assert self._inserted_text(requests) == "o\ni\nt\n"

    def test_separate_nested_quotes_inside_one_outer_quote_separated(self):
        requests, _ = _html_to_doc_requests(
            "<blockquote><blockquote><p>i</p></blockquote>"
            "<blockquote><p>j</p></blockquote></blockquote>"
        )
        assert self._inserted_text(requests) == "i\n\nj\n"
        assert self._collapsed_ranges(requests) == [{"startIndex": 3, "endIndex": 4}]

    def test_unknown_paths_never_separated(self):
        """doc_to_ast.py leaves blockquote_path empty: nothing to tell quotes apart by,
        so the nodes render as before."""
        nodes = [
            Paragraph(runs=[Run("a")], blockquote_depth=1),
            Paragraph(runs=[Run("b")], blockquote_depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        assert self._inserted_text(requests) == "a\nb\n"

    def test_separate_quoted_lists_are_separate_lists(self):
        requests, _ = _html_to_doc_requests(
            "<blockquote><ul><li>a</li></ul></blockquote>"
            "<blockquote><ul><li>b</li></ul></blockquote>"
        )
        assert self._inserted_text(requests) == "a\n\nb\n"
        bullets = [
            r["createParagraphBullets"]["range"] for r in requests if "createParagraphBullets" in r
        ]
        assert sorted(b["startIndex"] for b in bullets) == [1, 4]

    def test_quoted_bullet_spacing_follows_the_bullet_pass(self):
        """Like its quote styling, a quoted bullet's spacing is emitted after the bullet
        pass, on post-bullet positions."""
        requests, _ = _html_to_doc_requests(
            "<blockquote><ul><li>a<ul><li>b</li></ul></li></ul></blockquote>"
        )
        last_bullet = max(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        spacing = [
            (i, r["updateParagraphStyle"]["range"])
            for i, r in enumerate(requests)
            if "updateParagraphStyle" in r
            and {"spaceAbove", "spaceBelow"} & set(r["updateParagraphStyle"]["paragraphStyle"])
        ]
        assert all(i > last_bullet for i, _ in spacing)
        # Post-bullets: "a\n" [1,3), "b\n" [3,5) (its tab consumed).
        assert self._spacing(requests) == {1: {"spaceAbove": 8}, 4: {"spaceBelow": 8}}

    def test_spacing_lands_on_a_multi_paragraph_nodes_edges(self):
        """A node whose text holds "\\n" becomes several Docs paragraphs (#1093); the
        quote's space goes on the first and last of them, not between."""
        nodes = [Paragraph(runs=[Run("one\ntwo")], blockquote_depth=1, blockquote_path=(1,))]
        requests, _ = ast_to_requests(nodes)
        # "one\n" [1,5), "two\n" [5,9).
        assert self._spacing(requests) == {1: {"spaceAbove": 8}, 8: {"spaceBelow": 8}}

    def test_code_blocks_get_space_around_them(self):
        requests, _ = _html_to_doc_requests(
            "<pre><code>c1</code></pre><pre><code>c2</code></pre><p>p</p>"
        )
        # "c1\n" [1,4), "c2\n" [4,7), "p\n" [7,9).
        assert self._spacing(requests) == {
            1: {"spaceAbove": 8},
            3: {"spaceBelow": 8},
            4: {"spaceAbove": 8},
            6: {"spaceBelow": 8},
        }

    @pytest.mark.parametrize(
        "html",
        [
            "<p>x</p><blockquote><h1>H</h1><p>q</p></blockquote>",
            '<p>x</p><blockquote><p data-style="title">H</p><p>q</p></blockquote>',
        ],
    )
    def test_quoted_named_style_keeps_its_own_spacing(self, html):
        """An explicit quote-edge value would replace HEADING_1's or TITLE's own spacing
        (PR #1199 QA round 1); the quote's other edge is still spaced."""
        requests, _ = _html_to_doc_requests(html)
        # "x\n" [1,3), "H\n" [3,5), "q\n" [5,7).
        assert self._spacing(requests) == {6: {"spaceBelow": 8}}

    def test_plain_paragraphs_and_lists_get_no_spacing(self):
        requests, _ = _html_to_doc_requests("<h2>h</h2><p>p</p><ul><li>l</li></ul>")
        assert self._spacing(requests) == {}


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
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())
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
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 31 not in insert_indices  # phantom — must not be filled even when listed last
        assert 41 in insert_indices  # real cell must be filled

    def test_empty_cell_text_skipped(self):
        ast_t = _table(_row(_cell(""), _cell("B")))
        doc_t = {"tableRows": [self._doc_row(10, 20)]}
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 11 not in insert_indices  # para_start = startIndex + 1
        assert 21 in insert_indices

    def test_colspan_phantom_not_filled(self):
        # After a colspan=2 merge, col 1 (phantom) remains as a physical cell.
        # Fill must skip it and write to col 2 (the real cell).
        ast_t = _table(_row(_cell("Wide", colspan=2), _cell("C2")))
        # Row 0 post-merge: [merged_col0 at 10, colspan_phantom_col1 at 20, real_col2 at 30]
        doc_t = {"tableRows": [self._doc_row(10, 20, 30)]}
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        assert 21 not in insert_indices  # colspan phantom — must not be filled
        assert 11 in insert_indices  # merged cell gets "Wide"
        assert 31 in insert_indices  # real col 2 gets "C2"

    def test_requests_sorted_high_to_low(self):
        ast_t = _table(_row(_cell("A"), _cell("B")))
        doc_t = {"tableRows": [self._doc_row(10, 50)]}
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())
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
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())
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
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())

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
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())

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
        reqs = _build_fill_requests([doc_t], [ast_t], _no_images())

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


class TestNestedBulletDepthEmitsIndentation:
    """#336: BulletItem.depth must reach the live doc as nesting level via leading tabs —
    the only mechanism createParagraphBullets exposes for setting it (it infers and
    consumes leading tab characters from each paragraph's text). PR #432 QA round 1
    found that issuing one createParagraphBullets call per paragraph let call
    order/adjacency to an already-bulleted neighbor override the tab-encoded depth live
    (same-depth siblings landed at different indentation levels, ordered lists lost
    continuous numbering) even though each call's own range/tabs were individually
    correct — so contiguous same-preset BulletItems must be grouped into one call."""

    def _bullet_ranges(self, requests):
        return [
            r["createParagraphBullets"]["range"] for r in requests if "createParagraphBullets" in r
        ]

    def test_depth_zero_item_gets_no_leading_tabs(self):
        nodes = [BulletItem(runs=[Run("Item")], depth=0)]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Item\n"

    def test_nested_item_gets_leading_tabs_matching_depth(self):
        nodes = [
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
            BulletItem(runs=[Run("Grandchild")], depth=2),
        ]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Parent\n\tChild\n\t\tGrandchild\n"

    def test_contiguous_same_preset_bullets_grouped_into_one_call(self):
        # A parent + nested child of the same preset must get exactly ONE
        # createParagraphBullets call spanning both paragraphs (including the child's
        # leading tab), not one call per paragraph — see class docstring.
        nodes = [
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        ranges = self._bullet_ranges(requests)
        assert len(ranges) == 1
        # "Parent\n" (7 chars) + "\tChild\n" (7 chars) = one combined range, 1-15
        assert ranges[0] == {"startIndex": 1, "endIndex": 15}

    def test_three_level_nesting_still_one_call(self):
        nodes = [
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
            BulletItem(runs=[Run("Grandchild")], depth=2),
        ]
        requests, _ = ast_to_requests(nodes)
        ranges = self._bullet_ranges(requests)
        assert len(ranges) == 1
        insert = next(r for r in requests if "insertText" in r)
        full_text = insert["insertText"]["text"]
        assert ranges[0] == {"startIndex": 1, "endIndex": 1 + len(full_text)}

    def test_run_style_offset_skips_leading_tabs(self):
        # A styled run inside a nested item must not have the leading tab(s) folded
        # into its style range.
        requests, _ = ast_to_requests([BulletItem(runs=[Run("bold", bold=True)], depth=2)])
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "\t\tbold\n"
        bold_req = next(
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        )
        rng = bold_req["updateTextStyle"]["range"]
        assert rng == {"startIndex": 3, "endIndex": 7}  # skips the 2 leading tabs

    def test_bullet_run_request_applied_after_sibling_requests(self):
        # A grouped bullet-run's createParagraphBullets call consumes characters
        # (shifting everything after it), so it must be ordered after every other
        # request that assumes positions haven't shifted yet — including a later
        # heading's own style request, which must appear earlier in the array.
        nodes = [
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
            Heading(level=1, runs=[Run("Next")]),
        ]
        requests, _ = ast_to_requests(nodes)
        heading_idx = next(i for i, r in enumerate(requests) if "updateParagraphStyle" in r)
        bullet_run_idx = next(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        assert heading_idx < bullet_run_idx

    def test_separate_bullet_runs_applied_latest_position_first(self):
        # Two lists separated by a paragraph are two independent runs, each getting
        # its own createParagraphBullets call. Processing must go latest-in-document-
        # first so an earlier, not-yet-processed run's precomputed range is never
        # invalidated by a later run's own tab consumption.
        nodes = [
            BulletItem(runs=[Run("A")], depth=1),
            Paragraph(runs=[Run("Interrupter")]),
            BulletItem(runs=[Run("B")], depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        ranges = self._bullet_ranges(requests)
        assert len(ranges) == 2
        starts = [r["startIndex"] for r in ranges]
        assert starts == sorted(starts, reverse=True)

    def test_ordered_and_unordered_runs_split_at_preset_boundary(self):
        # A preset change mid-list must end the current run and start a new one — one
        # createParagraphBullets call takes exactly one bulletPreset.
        nodes = [
            BulletItem(runs=[Run("Bullet A")], depth=0, ordered=False),
            BulletItem(runs=[Run("Bullet B")], depth=0, ordered=False),
            BulletItem(runs=[Run("Num 1")], depth=0, ordered=True),
            BulletItem(runs=[Run("Num 2")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        bullet_reqs = [
            r["createParagraphBullets"] for r in requests if "createParagraphBullets" in r
        ]
        assert len(bullet_reqs) == 2
        presets = {req["bulletPreset"] for req in bullet_reqs}
        assert presets == {"BULLET_DISC_CIRCLE_SQUARE", "NUMBERED_DECIMAL_ALPHA_ROMAN"}

    def test_table_position_adjusted_for_preceding_nested_bullet_tabs(self):
        # A table positioned after a nested bullet must have its insertTable index
        # adjusted for the tab character(s) that bullet's own createParagraphBullets
        # call removes ahead of it.
        nodes = [
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
            Table(rows=[Row(cells=[Cell(children=[Run("X")])])]),
        ]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        table_req = next(r for r in requests if "insertTable" in r)
        # As-inserted text is "Parent\n\tChild\n" (14 chars) plus the table's placeholder
        # (#1097); table's raw position would be 1 + 14 = 15, but the 1 leading tab gets
        # consumed ahead of it, so the real position is 14.
        assert insert["insertText"]["text"] == "Parent\n\tChild\n\n"
        assert table_req["insertTable"]["location"]["index"] == 14

    def test_table_before_nested_bullet_unaffected(self):
        # No nested-bullet tabs precede this table, so its position needs no adjustment.
        nodes = [
            Table(rows=[Row(cells=[Cell(children=[Run("X")])])]),
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        table_req = next(r for r in requests if "insertTable" in r)
        assert table_req["insertTable"]["location"]["index"] == 1

    def test_ordered_nested_list_uses_numbered_preset(self):
        nodes = [BulletItem(runs=[Run("Item")], depth=1, ordered=True)]
        requests, _ = ast_to_requests(nodes)
        bullet_req = next(r for r in requests if "createParagraphBullets" in r)
        assert (
            bullet_req["createParagraphBullets"]["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"
        )

    def test_end_to_end_html_nested_list_produces_leading_tabs(self):
        # Integration check through the real HTML parser, matching the shape of the
        # live #336 repro (a parent item followed by a nested sub-list).
        html = "<ul><li>Parent<ul><li>Child</li></ul></li></ul>"
        requests, _ = _to_doc_requests(html)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Parent\n\tChild\n"


class TestBulletDepthEdgeCases:
    """#434: non-blocking cleanup findings surfaced by PR #432's own code review,
    covering two BulletItem edge cases the original nested-bullet fix didn't
    account for."""

    def test_literal_leading_tab_in_item_text_does_not_double_the_depth_tabs(self):
        # Finding 1: a literal leading tab in the item's own source text (e.g.
        # hand-formatted HTML/markdown) is indistinguishable, once concatenated,
        # from the synthesized depth-tabs above it — createParagraphBullets reads
        # every leading tab character in the paragraph to infer nesting level, not
        # just the ones this function intended as depth markers. Left un-stripped,
        # a depth=1 item with its own literal leading tab would read as 2 leading
        # tabs (nested one level too deep) instead of the 1 its depth actually
        # calls for.
        nodes = [BulletItem(runs=[Run("\tHello")], depth=1)]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "\tHello\n"

    def test_literal_leading_tab_does_not_desync_following_table_position(self):
        # Same finding, checked from the other side: the extra un-stripped literal
        # tab would also get silently consumed by createParagraphBullets without
        # being counted in cumulative_tabs, desyncing a later table's insertTable
        # position by exactly the extra tab's own length.
        nodes = [
            BulletItem(runs=[Run("\tChild")], depth=1),
            Table(rows=[Row(cells=[Cell(children=[Run("X")])])]),
        ]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        table_req = next(r for r in requests if "insertTable" in r)
        # "\tChild\n" is 7 chars (then the table's placeholder, #1097); table's raw
        # position 1+7=8, minus the 1 synthetic tab consumed ahead of it by
        # createParagraphBullets = 7.
        assert insert["insertText"]["text"] == "\tChild\n\n"
        assert table_req["insertTable"]["location"]["index"] == 7

    def test_literal_leading_tab_still_strips_at_depth_zero(self):
        # Finding 5: the strip is unconditional on depth, not just depth>0 — a
        # depth=0 item's own literal leading tab is still misread as a nesting
        # signal by createParagraphBullets (relative to the rest of its call),
        # even with no synthetic tabs of emitter.py's own to merge with. No prior
        # test covered depth=0 specifically (QA round 2 finding).
        nodes = [BulletItem(runs=[Run("\tHello")], depth=0)]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Hello\n"

    def test_literal_leading_tab_stripped_run_does_not_overrun_its_own_style_range(self):
        # QA round 2 finding 1+2: the leading-tab strip originally only touched
        # the local `run_text` string used to build the inserted text, not the
        # actual Run object the style-request loop iterates afterward — so a
        # styled run's own updateTextStyle range still counted the stripped tab
        # character(s), overrunning by however many were removed. The correct
        # range for "Hello" (5 chars, right after the paragraph's skip_len=0 at
        # depth=0) is [1, 6), not [1, 7).
        nodes = [BulletItem(runs=[Run("\tHello", bold=True)], depth=0)]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Hello\n"
        bold_req = next(
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        )
        assert bold_req["updateTextStyle"]["range"] == {"startIndex": 1, "endIndex": 6}

    def test_literal_leading_tab_stripped_run_does_not_shift_following_image(self):
        # Same root cause as the style-range case above, checked against the
        # image-position math instead: an Image following a tab-stripped Run must
        # land right after "Hello" (index 6), not one past it (index 7) purely
        # because the stale, unstripped Run.text was used to compute the offset.
        img = Image(src="x.png")
        nodes = [BulletItem(runs=[Run("\tHello"), img], depth=0)]
        requests, _ = ast_to_requests(nodes, image_uris={id(img): "https://example.com/x.png"})
        insert = next(r for r in requests if "insertText" in r)
        image_req = next(r for r in requests if "insertInlineImage" in r)
        assert insert["insertText"]["text"] == "Hello\n"
        assert image_req["insertInlineImage"]["location"]["index"] == 6

    def test_negative_depth_orphan_li_does_not_take_isolated_wrap_path(self):
        # Finding 3 (as fixed after QA round 2's finding 3+4 fold): an orphan <li>
        # outside any <ul>/<ol> used to reach ast_to_requests with depth=-1 from
        # html_parser.py's _make_bullet_item (len(_list_ordered) - 1 with an empty
        # stack), needing 3 separate emitter.py call sites to each independently
        # clamp it. Now clamped once at the source in _make_bullet_item itself, so
        # a real BulletItem can never carry a negative depth in the first place —
        # this test goes through html_to_ast (not a hand-built BulletItem(depth=-1),
        # which is no longer a shape emitter.py needs to defend against) to exercise
        # the actual production path. Takes the single-call min_depth==0 path a
        # normal depth-0 item does, not the 3-request isolated-run wrap path.
        nodes = html_to_ast("<li>Orphan</li>")
        requests, _ = ast_to_requests(nodes)
        bullet_reqs = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_reqs) == 1
        assert not any("deleteContentRange" in r for r in requests)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "Orphan\n"

    def test_negative_depth_orphan_li_groups_with_depth_zero_sibling(self):
        # An orphan <li> immediately followed by a normal depth-0 <li> (inside its
        # own <ul>) of the same preset must still be treated as one contiguous run.
        nodes = html_to_ast("<li>Orphan</li><ul><li>Normal</li></ul>")
        requests, _ = ast_to_requests(nodes)
        bullet_reqs = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_reqs) == 1
        assert not any("deleteContentRange" in r for r in requests)

    def test_orphan_li_depth_is_clamped_at_the_ast_level(self):
        # Finding 3's actual fix site: html_parser.py's _make_bullet_item clamps
        # len(_list_ordered) - 1 to a minimum of 0, so an orphan <li>'s own
        # BulletItem.depth is 0, not -1, before it ever reaches emitter.py — the
        # invariant the two tests above rely on holding at the source.
        nodes = html_to_ast("<li>Orphan</li>")
        (bullet,) = nodes
        assert isinstance(bullet, BulletItem)
        assert bullet.depth == 0


def _render_bullet_levels(requests: list[dict]) -> list[tuple[str, int | None]]:
    """Each paragraph's (text, nestingLevel) after `requests`, nestingLevel None for a
    non-bullet. See _render_lists."""
    return [(text, level) for text, level, _, _ in _render_lists(requests)]


def _render_lists(requests: list[dict]) -> list[tuple[str, int | None, str | None, int | None]]:
    """Apply the text and bullet requests in `requests` to an empty doc and return
    each paragraph's (text, nestingLevel, list, ordinal), all but text None for a
    non-bullet. `list` names the paragraph's Docs list by its preset's first letter
    ("N" numbered, "B" bulleted) and its order of creation ("N1", "B2"); `ordinal` is
    the number Docs shows it at, counted per list and level, a level restarting after
    an item at a shallower level of the same list.

    Models the API behaviors the bullet pass depends on, confirmed live (TC-DOC190,
    #1072): createParagraphBullets sets each paragraph's nestingLevel to its
    leading-tab count minus the minimum across the call's range, then removes those
    tabs, and puts every paragraph in its range into one new list, including one
    already in a list; a paragraph's properties live on its trailing newline, so
    deleting an empty anchor paragraph leaves the next one's level intact; and
    deleteParagraphBullets leaves the level's indent, which a later
    createParagraphBullets reads as extra depth (#1069), so bulleting such a paragraph
    before an updateParagraphStyle zeroes its indent is unmodeled and fails here.
    And when the paragraph just before the range is in a list with the same preset,
    the range joins that list, its levels counted from that paragraph's level instead
    of 0 (#1241). Other request types don't change text or lists and are ignored."""
    # One entry per character from index 1; a "\n" entry carries its paragraph's
    # properties: level, list, and whether it holds a stale list indent.
    chars: list[list] = [["\n", None]]  # an empty doc is one empty paragraph
    lists: list[str] = []

    def paragraphs() -> list[tuple[int, int]]:
        """(start, end) list positions of each paragraph, end inclusive of its newline."""
        out, start = [], 0
        for i, (ch, _) in enumerate(chars):
            if ch == "\n":
                out.append((start, i))
                start = i + 1
        return out

    def covered(rng: dict) -> list[tuple[int, int]]:
        lo, hi = rng["startIndex"] - 1, rng["endIndex"] - 1
        return [(a, b) for a, b in paragraphs() if a < hi and b >= lo]

    for req in requests:
        if "insertText" in req:
            pos = req["insertText"]["location"]["index"] - 1
            chars[pos:pos] = [[ch, None] for ch in req["insertText"]["text"]]
        elif "deleteContentRange" in req:
            rng = req["deleteContentRange"]["range"]
            del chars[rng["startIndex"] - 1 : rng["endIndex"] - 1]
        elif "deleteParagraphBullets" in req:
            for _, b in covered(req["deleteParagraphBullets"]["range"]):
                if chars[b][1] is not None:
                    chars[b][1] = {"stale_indent": True}
        elif "updateParagraphStyle" in req:
            update = req["updateParagraphStyle"]
            if "indentStart" in update["paragraphStyle"]:
                for _, b in covered(update["range"]):
                    if chars[b][1] is not None and chars[b][1].get("stale_indent"):
                        chars[b][1] = None
        elif "createParagraphBullets" in req:
            create = req["createParagraphBullets"]
            paras = covered(create["range"])
            tabs = []
            for a, b in paras:
                assert not (chars[b][1] or {}).get("stale_indent"), "unmodeled stale indent"
                n = 0
                while a + n < b and chars[a + n][0] == "\t":
                    n += 1
                tabs.append(n)
            base = min(tabs)
            letter = create.get("bulletPreset", "B")[0]
            before = chars[paras[0][0] - 1][1] if paras[0][0] > 0 else None
            if before and "level" in before and before["list"][0] == letter:
                list_name, offset = before["list"], before["level"]
            else:
                lists.append(f"{letter}{len(lists) + 1}")
                list_name, offset = lists[-1], 0
            # Latest-first, so stripping one paragraph's tabs doesn't shift the next.
            for (a, b), n in reversed(list(zip(paras, tabs, strict=True))):
                chars[b][1] = {"level": n - base + offset, "list": list_name}
                del chars[a : a + n]

    rendered = []
    counters: dict[str, list[int]] = {}
    for a, b in paragraphs()[:-1]:
        text, props = "".join(ch for ch, _ in chars[a:b]), chars[b][1]
        if props is None or "level" not in props:
            rendered.append((text, None, None, None))
            continue
        level, list_name = props["level"], props["list"]
        counts = counters.setdefault(list_name, [])
        del counts[level + 1 :]
        counts.extend([0] * (level + 1 - len(counts)))
        counts[level] += 1
        rendered.append((text, level, list_name, counts[level]))
    return rendered


class TestRenderBulletLevelsModel:
    """Pins the fake above to the API behavior that caused #439, so the outcome
    tests below can't pass against a model that never had the bug."""

    def test_run_with_no_zero_tab_paragraph_collapses_to_level_0(self):
        requests = [
            {"insertText": {"location": {"index": 1}, "text": "\tC1\n\tC2\n"}},
            {"createParagraphBullets": {"range": {"startIndex": 1, "endIndex": 9}}},
        ]
        assert _render_bullet_levels(requests) == [("C1", 0), ("C2", 0)]

    def test_range_after_same_preset_list_joins_it(self):
        # #1241, confirmed live: the range joins the list just before it, its levels
        # counted from that paragraph's level, so this fails without the barrier.
        preset = "NUMBERED_DECIMAL_ALPHA_ROMAN"
        requests = [
            {"insertText": {"location": {"index": 1}, "text": "P\n\ta\n\n\tb\n"}},
            {
                "createParagraphBullets": {
                    "range": {"startIndex": 1, "endIndex": 6},
                    "bulletPreset": preset,
                }
            },
            # The first call consumed a's tab: the empty paragraph and \tb are at 5..9.
            {
                "createParagraphBullets": {
                    "range": {"startIndex": 5, "endIndex": 9},
                    "bulletPreset": preset,
                }
            },
        ]
        assert _render_lists(requests) == [
            ("P", 0, "N1", 1),
            ("a", 1, "N1", 1),
            ("", 1, "N1", 2),
            ("b", 2, "N1", 1),
        ]


class TestIsolatedDepthRunGlyph:
    """#439: a contiguous createParagraphBullets run whose every item is at depth > 0
    (no depth-0 sibling in the same call) rendered the depth-0 glyph (disc) instead of
    the correct nested glyph — createParagraphBullets assigns nestingLevel relative to
    the *minimum* leading-tab count in the range, so a run with no 0-tab paragraph
    collapses to level 0. Fixed by wrapping such a run with a throwaway 0-tab anchor
    paragraph (insert -> bullet extended range -> delete) so the real items land at
    their true nesting level and glyph. The anchor insert (+1) and delete (-1) cancel.

    These assert the rendered levels through _render_bullet_levels rather than the
    request literals (#715), so a refactor of the request sequence that keeps the
    outcome doesn't have to touch them. TC-DOC190 covers the glyph itself live."""

    def test_isolated_depth1_run_renders_at_level_1(self):
        nodes = [
            BulletItem(runs=[Run("C1")], depth=1),
            BulletItem(runs=[Run("C2")], depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_bullet_levels(requests) == [("C1", 1), ("C2", 1)]

    def test_single_isolated_item_renders_at_its_depth(self):
        requests, _ = ast_to_requests([BulletItem(runs=[Run("only")], depth=2)])
        assert _render_bullet_levels(requests) == [("only", 2)]

    def test_run_with_depth0_item_renders_levels_without_anchor(self):
        nodes = [
            BulletItem(runs=[Run("Parent")], depth=0),
            BulletItem(runs=[Run("Child")], depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_bullet_levels(requests) == [("Parent", 0), ("Child", 1)]
        # A run that already has a level-0 item needs no anchor.
        assert not any("deleteContentRange" in r for r in requests)

    def test_anchor_wrap_is_position_neutral_for_a_following_table(self):
        # The anchor insert/delete cancel, so a table after an isolated run sits exactly
        # where it would if the run's tabs alone were consumed — same index the
        # equivalent depth-0-anchored run would produce.
        isolated = [
            BulletItem(runs=[Run("C1")], depth=1),
            BulletItem(runs=[Run("C2")], depth=1),
            Table(rows=[Row(cells=[Cell(children=[Run("X")])])]),
        ]
        requests, _ = ast_to_requests(isolated)
        table_req = next(r for r in requests if "insertTable" in r)
        # as-inserted text "\tC1\n\tC2\n" is 8 chars -> raw table pos 1 + 8 = 9;
        # the 2 leading tabs are consumed ahead of it -> real pos 7.
        assert table_req["insertTable"]["location"]["index"] == 7

    def test_two_isolated_runs_both_render_at_level_1(self):
        nodes = [
            BulletItem(runs=[Run("A")], depth=1),
            Paragraph(runs=[Run("Interrupter")]),
            BulletItem(runs=[Run("B")], depth=1),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_bullet_levels(requests) == [("A", 1), ("Interrupter", None), ("B", 1)]

    def test_end_to_end_list_nested_with_no_parent_item_renders_at_level_1(self):
        # A nested list with no parent item (a <ul> directly in a <ul>) is an
        # isolated depth-1 run. #439's original shape, a bare <li> wrapping the
        # nested list, is now an empty bullet at level 0 (#1075).
        html = "<ul><ul><li>C1</li><li>C2</li></ul></ul>"
        requests, _ = _to_doc_requests(html)
        assert _render_bullet_levels(requests) == [("C1", 1), ("C2", 1)]
        bare = "<ul><li><ul><li>C1</li><li>C2</li></ul></li></ul>"
        requests, _ = _to_doc_requests(bare)
        assert _render_bullet_levels(requests) == [("", 0), ("C1", 1), ("C2", 1)]


class TestMixedTypeNestedListKeepsNumbering:
    """#1072: a list nested in one of the other type ended the outer list's
    createParagraphBullets run, so the outer list became separate Docs lists and its
    numbering restarted after the nested one (1, ○, ○, 1, 2). Now each top-level list
    is one call and each nested list of the other type is taken back out of it, so
    every list in the source is one Docs list. Asserted through _render_lists, which
    models list identity and per-list numbering."""

    def test_issue_repro_numbering_continues_after_nested_bullets(self):
        html = "<ol><li>A<ul><li>a1</li><li>a2</li></ul></li><li>B</li><li>C</li></ol>"
        requests, _ = _to_doc_requests(html)
        assert _render_lists(requests) == [
            ("A", 0, "N1", 1),
            ("a1", 1, "B2", 1),
            ("a2", 1, "B2", 2),
            ("B", 0, "N1", 2),
            ("C", 0, "N1", 3),
        ]

    def test_issue_repro_through_markdown(self):
        html = _md_to_html("1. A\n    - a1\n    - a2\n2. B\n3. C\n")
        requests, _ = _to_doc_requests(html)
        assert [(text, ordinal) for text, _, _, ordinal in _render_lists(requests)] == [
            ("A", 1),
            ("a1", 1),
            ("a2", 2),
            ("B", 2),
            ("C", 3),
        ]

    def test_nested_numbered_level_continues_after_deeper_bullets(self):
        # Every level keeps counting, not just the top one.
        nodes = [
            BulletItem(runs=[Run("A")], depth=0, ordered=True),
            BulletItem(runs=[Run("a1")], depth=1, ordered=True),
            BulletItem(runs=[Run("x")], depth=2, ordered=False),
            BulletItem(runs=[Run("a2")], depth=1, ordered=True),
            BulletItem(runs=[Run("B")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_lists(requests) == [
            ("A", 0, "N1", 1),
            ("a1", 1, "N1", 1),
            ("x", 2, "B2", 1),
            ("a2", 1, "N1", 2),
            ("B", 0, "N1", 2),
        ]

    def test_three_alternating_levels(self):
        # A nested list's range holds the list nested in it, which is taken out in turn.
        nodes = [
            BulletItem(runs=[Run("A")], depth=0),
            BulletItem(runs=[Run("n1")], depth=1, ordered=True),
            BulletItem(runs=[Run("b1")], depth=2),
            BulletItem(runs=[Run("n2")], depth=1, ordered=True),
            BulletItem(runs=[Run("B")], depth=0),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_lists(requests) == [
            ("A", 0, "B1", 1),
            ("n1", 1, "N2", 1),
            ("b1", 2, "B3", 1),
            ("n2", 1, "N2", 2),
            ("B", 0, "B1", 2),
        ]

    def test_second_nested_list_under_one_item_restarts(self):
        # `1. a` / `- b` / `1. c` under one item are three Markdown lists, so c
        # restarts rather than continuing a's numbering.
        nodes = [
            BulletItem(runs=[Run("A")], depth=0, ordered=True),
            BulletItem(runs=[Run("a")], depth=1, ordered=True),
            BulletItem(runs=[Run("b")], depth=1),
            BulletItem(runs=[Run("c")], depth=1, ordered=True),
            BulletItem(runs=[Run("B")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        rendered = _render_lists(requests)
        assert [(text, ordinal) for text, _, _, ordinal in rendered] == [
            ("A", 1),
            ("a", 1),
            ("b", 1),
            ("c", 1),
            ("B", 2),
        ]
        lists = {text: list_name for text, _, list_name, _ in rendered}
        assert lists["A"] == lists["a"] == lists["B"]
        assert len({lists["a"], lists["b"], lists["c"]}) == 3

    def test_sibling_lists_of_different_type_stay_separate(self):
        # A same-depth type change is a new Markdown list, so the next numbered list
        # restarts.
        nodes = [
            BulletItem(runs=[Run("n1")], depth=0, ordered=True),
            BulletItem(runs=[Run("b")], depth=0),
            BulletItem(runs=[Run("m1")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_lists(requests) == [
            ("n1", 0, "N3", 1),
            ("b", 0, "B2", 1),
            ("m1", 0, "N1", 1),
        ]

    def test_isolated_fragment_with_nested_other_type(self):
        # A top-level list with no depth-0 item still takes the anchor wrap, and its
        # nested list comes out of it at its own depth.
        nodes = [
            BulletItem(runs=[Run("A")], depth=1, ordered=True),
            BulletItem(runs=[Run("x")], depth=2),
            BulletItem(runs=[Run("B")], depth=1, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        assert _render_lists(requests) == [
            ("A", 1, "N1", 1),
            ("x", 2, "B2", 1),
            ("B", 1, "N1", 2),
        ]

    def test_following_table_position_unchanged(self):
        # Taking a nested list out inserts its tabs again and consumes them again, so a
        # later table sits where a single call would leave it: "A\n\ta1\nB\n" is 8
        # characters, then the placeholder at 9, less the one consumed tab.
        nodes = [
            BulletItem(runs=[Run("A")], depth=0, ordered=True),
            BulletItem(runs=[Run("a1")], depth=1),
            BulletItem(runs=[Run("B")], depth=0, ordered=True),
            Table(rows=[Row(cells=[Cell(children=[Run("X")])])]),
        ]
        requests, _ = ast_to_requests(nodes)
        table_req = next(r for r in requests if "insertTable" in r)
        assert table_req["insertTable"]["location"]["index"] == 8

    def test_later_list_unaffected_by_earlier_mixed_list(self):
        # Lists are applied latest-first, so a mixed list after a paragraph doesn't
        # disturb an earlier one, and vice versa.
        nodes = [
            BulletItem(runs=[Run("A")], depth=0, ordered=True),
            BulletItem(runs=[Run("a1")], depth=1),
            BulletItem(runs=[Run("B")], depth=0, ordered=True),
            Paragraph(runs=[Run("P")]),
            BulletItem(runs=[Run("C")], depth=0, ordered=True),
            BulletItem(runs=[Run("c1")], depth=1),
            BulletItem(runs=[Run("D")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        assert [(text, level, ordinal) for text, level, _, ordinal in _render_lists(requests)] == [
            ("A", 0, 1),
            ("a1", 1, 1),
            ("B", 0, 2),
            ("P", None, None),
            ("C", 0, 1),
            ("c1", 1, 1),
            ("D", 0, 2),
        ]


class TestAdjacentSameTypeListsStaySeparate:
    """#1241: two adjacent source lists of one type at one depth (a marker change,
    `-` then `*` or `1.` then `1)`) rendered as one Docs list, since the AST carried no
    list boundary. Each BulletItem now carries its source lists' ids, and the emitter
    starts a new Docs list where they change."""

    def test_parser_gives_each_list_its_own_id(self):
        nodes = html_to_ast("<ul><li>a</li><li>b</li></ul><ul><li>c</li></ul>")
        assert nodes[0].list_path == nodes[1].list_path == (1,)
        assert nodes[2].list_path == (2,)

    def test_item_after_nested_list_keeps_its_list_path(self):
        nodes = html_to_ast("<ol><li>A<ul><li>x</li></ul></li><li>B</li></ol>")
        paths = {item.runs[0].text: item.list_path for item in nodes}
        assert paths == {"A": (1,), "x": (1, 2), "B": (1,)}

    def test_unclosed_li_keeps_the_list_it_opened_in(self):
        # PR #1295 QA round 1: an <li> left open until </ul> is flushed after the
        # pop, and used to read the next list's ids (or none) and the wrong depth.
        nodes = html_to_ast("<ul><li>a</li><li>b</ul><ul><li>c</ul>")
        assert [n.list_path for n in nodes] == [(1,), (1,), (2,)]
        nodes = html_to_ast("<ol><li>P<ol><li>a</li><li>b</ol></li></ol>")
        assert [(n.runs[0].text, n.depth, n.list_path) for n in nodes] == [
            ("P", 0, (1,)),
            ("a", 1, (1, 2)),
            ("b", 1, (1, 2)),
        ]

    def test_unclosed_li_lists_render_separately(self):
        requests, _ = _to_doc_requests("<ul><li>a</li><li>b</ul><ul><li>c</ul>")
        lists = {text: list_name for text, _, list_name, _ in _render_lists(requests)}
        assert lists["a"] == lists["b"] != lists["c"]

    def test_list_after_deeper_fragment_starts_its_own(self):
        # PR #1295 QA round 1: y's list follows a list whose only item x sits at depth
        # 1 (its parent item dropped, #714). y isn't from a list enclosing x's, so it
        # doesn't rejoin x's Docs list.
        nodes = html_to_ast("<ol><li><ol><li>x</li></ol></li></ol><ol><li>y</li></ol>")
        requests, _ = ast_to_requests(nodes)
        creates = [r for r in requests if "createParagraphBullets" in r]
        assert len(creates) == 2
        lists = {text: list_name for text, _, list_name, _ in _render_lists(requests)}
        assert lists["x"] != lists["y"]

    def test_list_after_earlier_list_isnt_nested_in_it(self):
        # A fragment of a separate list (no parent item) after a shallower list's
        # item isn't nested under that item: its list doesn't enclose the fragment.
        nodes = html_to_ast("<ol><li>P</li></ol><ol><ol><li>z</li></ol></ol>")
        rendered = _render_lists(ast_to_requests(nodes)[0])
        lists = {text: list_name for text, _, list_name, _ in rendered}
        assert lists["P"] != lists["z"]
        assert [(text, level, ordinal) for text, level, _, ordinal in rendered] == [
            ("P", 0, 1),
            ("z", 1, 1),
        ]

    def test_trailing_nested_list_of_other_type(self):
        # PR #1295 QA round 1 (a #1072 regression): a nested list of the other type
        # that ends its top-level list left its tabs unconsumed, so a rendered one
        # level too deep. The top list's range now spans its nested items.
        html = _md_to_html("- P\n  - x\n- R\n  1. a\n  2. b\n")
        requests, _ = _to_doc_requests(html)
        rendered = _render_lists(requests)
        assert [(text, level, ordinal) for text, level, _, ordinal in rendered] == [
            ("P", 0, 1),
            ("x", 1, 1),
            ("R", 0, 2),
            ("a", 1, 1),
            ("b", 1, 2),
        ]
        lists = {text: list_name for text, _, list_name, _ in rendered}
        assert lists["P"] == lists["x"] == lists["R"] != lists["a"] == lists["b"]

    def test_trailing_nested_list_keeps_a_following_table_in_place(self):
        # "A\n\ta\nP\nB\n\tb\n" is 12 characters, so the placeholder sits at 13, less
        # the 2 consumed tabs: the trailing list's tab counts too.
        nodes = [
            BulletItem(runs=[Run("A")], depth=0),
            BulletItem(runs=[Run("a")], depth=1, ordered=True),
            Paragraph(runs=[Run("P")]),
            BulletItem(runs=[Run("B")], depth=0),
            BulletItem(runs=[Run("b")], depth=1, ordered=True),
            Table(rows=[Row(cells=[Cell(children=[Run("X")])])]),
        ]
        requests, _ = ast_to_requests(nodes)
        # The last entry is the table's placeholder paragraph (insertTable isn't modeled).
        assert [(text, level) for text, level, _, _ in _render_lists(requests)][:-1] == [
            ("A", 0),
            ("a", 1),
            ("P", None),
            ("B", 0),
            ("b", 1),
        ]
        table_req = next(r for r in requests if "insertTable" in r)
        assert table_req["insertTable"]["location"]["index"] == 11

    def test_issue_repro_bullets(self):
        html = _md_to_html("- a\n- b\n\n* c\n* d\n")
        requests, _ = _to_doc_requests(html)
        rendered = _render_lists(requests)
        lists = {text: list_name for text, _, list_name, _ in rendered}
        assert lists["a"] == lists["b"] != lists["c"] == lists["d"]

    def test_top_level_numbered_restarts(self):
        html = _md_to_html("1. x\n2. y\n\n1) z\n")
        requests, _ = _to_doc_requests(html)
        assert [(text, ordinal) for text, _, _, ordinal in _render_lists(requests)] == [
            ("x", 1),
            ("y", 2),
            ("z", 1),
        ]

    def test_sublist_marker_change_under_one_item_restarts(self):
        # PR #1286 QA round 1: two sublists under P, the second a new list.
        html = _md_to_html("1. P\n    1. a\n    1) b\n2. Q\n")
        requests, _ = _to_doc_requests(html)
        rendered = _render_lists(requests)
        assert [(text, level, ordinal) for text, level, _, ordinal in rendered] == [
            ("P", 0, 1),
            ("a", 1, 1),
            ("b", 1, 1),
            ("Q", 0, 2),
        ]
        lists = {text: list_name for text, _, list_name, _ in rendered}
        assert lists["P"] == lists["a"] == lists["Q"] != lists["b"]

    def test_nested_list_after_deeper_same_type_list_stays_separate(self):
        # The restarted sublist D under A follows c, the last item of an ordered list
        # nested one level deeper; without the barrier, D would join c's list.
        html = _md_to_html("1. A\n   - b\n     1. c\n   1. d\n2. B\n")
        nodes = html_to_ast(html)
        assert [(n.runs[0].text, n.depth) for n in nodes] == [
            ("A", 0),
            ("b", 1),
            ("c", 2),
            ("d", 1),
            ("B", 0),
        ]
        rendered = _render_lists(_to_doc_requests(html)[0])
        lists = {text: list_name for text, _, list_name, _ in rendered}
        assert len({lists["A"], lists["b"], lists["c"], lists["d"]}) == 4
        assert lists["A"] == lists["B"]
        assert [(text, level, ordinal) for text, level, _, ordinal in rendered] == [
            ("A", 0, 1),
            ("b", 1, 1),
            ("c", 2, 1),
            ("d", 1, 1),
            ("B", 0, 2),
        ]

    def test_first_same_type_sublist_still_joins_parent(self):
        html = _md_to_html("1. A\n    1. a1\n    2. a2\n2. B\n")
        requests, _ = _to_doc_requests(html)
        rendered = _render_lists(requests)
        assert len({list_name for _, _, list_name, _ in rendered}) == 1
        assert [(text, ordinal) for text, _, _, ordinal in rendered] == [
            ("A", 1),
            ("a1", 1),
            ("a2", 2),
            ("B", 2),
        ]

    def test_dropped_parent_fragment_still_joins_outer_list(self):
        # #714: the empty outer item is dropped, so the inner list's item comes first
        # at depth 1. The outer list's next item joins it, as before, despite the ids.
        nodes = html_to_ast("<ol><li><ol><li>a</li></ol></li><li>B</li><li>C</li></ol>")
        requests, _ = ast_to_requests(nodes)
        rendered = _render_lists(requests)
        assert len({list_name for _, _, list_name, _ in rendered}) == 1

    def test_items_without_ids_group_by_type(self):
        # An AST not built by html_parser has no ids: adjacent same-type items merge.
        nodes = [
            BulletItem(runs=[Run("a")], depth=0, ordered=True),
            BulletItem(runs=[Run("b")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        assert [ordinal for _, _, _, ordinal in _render_lists(requests)] == [1, 2]

    def test_explicit_ids_split_adjacent_lists(self):
        nodes = [
            BulletItem(runs=[Run("a")], depth=0, ordered=True, list_path=(1,)),
            BulletItem(runs=[Run("b")], depth=0, ordered=True, list_path=(2,)),
        ]
        requests, _ = ast_to_requests(nodes)
        assert [ordinal for _, _, _, ordinal in _render_lists(requests)] == [1, 1]


def _md_lists(md: str) -> list[tuple[str, int | None, str | None, int | None]]:
    requests, _ = _to_doc_requests(_md_to_html(md))
    return _render_lists(requests)


def _final_range(requests: list[dict], text: str) -> dict:
    """The range of the paragraph whose text is `text` once `requests` have run."""
    position = 1
    for paragraph_text, *_ in _render_lists(requests):
        end = position + len(paragraph_text) + 1
        if paragraph_text == text:
            return {"startIndex": position, "endIndex": end}
        position = end
    raise AssertionError(f"no paragraph {text!r}")


def _final_indent_request(requests: list[dict], text: str) -> dict:
    """The paragraph style the last indent-setting request gives `text`'s paragraph,
    which must come after every bullet request (a later one would overwrite it)."""
    rng = _final_range(requests, text)
    index, style = max(
        (i, r["updateParagraphStyle"]["paragraphStyle"])
        for i, r in enumerate(requests)
        if "updateParagraphStyle" in r
        and r["updateParagraphStyle"]["range"] == rng
        and "indentStart" in r["updateParagraphStyle"]["paragraphStyle"]
    )
    last_bullet = max(
        i
        for i, r in enumerate(requests)
        if "createParagraphBullets" in r or "deleteParagraphBullets" in r
    )
    assert index > last_bullet
    return style


_TC_DOC104_FIXTURE = Path(__file__).parent / "../docs/qa/fixtures/tc-doc104-nested-lists.html"


class TestPrettyPrintedListWhitespace:
    """#1074: formatting whitespace between list tags (indented, pretty-printed HTML)
    became whitespace-only bullet paragraphs, so a numbered list skipped a number
    ("Top ordered 2" shown as "3."). #1116's line-break trims in html_parser
    (`_interrupt_open_block`, and a resumed segment's leading break in `handle_data`)
    fixed it. These pin the result: whitespace between list tags produces no
    paragraph, and the list renders as it does when written without the whitespace."""

    def test_tc_doc104_fixture_has_no_stray_bullets(self):
        requests, _ = _to_doc_requests(_TC_DOC104_FIXTURE.read_text())
        # Every paragraph, headings included, so a stray non-bullet paragraph fails
        # too. List names count creation order; the bullet pass runs latest list first.
        assert _render_lists(requests) == [
            ("Nested List Structure Test (direct HTML)", None, None, None),
            ("Case 1: parent item has its own text AND a nested sub-list", None, None, None),
            ("Parent A has text", 0, "B6", 1),
            ("Child A1", 1, "B6", 1),
            ("Child A2", 1, "B6", 2),
            ("Grandchild A2a", 2, "B6", 1),
            ("Parent B has text", 0, "B6", 2),
            ("Ordered child B1", 1, "N7", 1),
            ("Ordered child B2", 1, "N7", 2),
            ("Case 2: parent item has NO text of its own, just a nested list", None, None, None),
            # An empty item is an empty bullet (#1075).
            ("", 0, "B5", 1),
            ("Bare-nested child C1", 1, "B5", 1),
            ("Bare-nested child C2", 1, "B5", 2),
            ("Case 3: ordered list nested inside ordered list", None, None, None),
            ("Top ordered 1", 0, "N4", 1),
            ("Nested ordered 1.1", 1, "N4", 1),
            ("Nested ordered 1.2", 1, "N4", 2),
            ("Top ordered 2", 0, "N4", 2),
            ("Case 4: two levels of empty parent li", None, None, None),
            ("", 0, "B3", 1),
            ("", 1, "B3", 1),
            ("Doubly-bare child D2a", 2, "B3", 1),
            ("Doubly-bare child D2b", 2, "B3", 2),
            ("Case 5: nested list with no parent item, isolated min_depth=1 run", None, None, None),
            ("Parentless child E1", 1, "B2", 1),
            ("Parentless child E2", 1, "B2", 2),
            (
                "Case 6: two levels of nested list with no parent item, isolated min_depth=2 run",
                None,
                None,
                None,
            ),
            ("Parentless child F2a", 2, "B1", 1),
            ("Parentless child F2b", 2, "B1", 2),
        ]

    @pytest.mark.parametrize(
        "pretty, compact",
        [
            pytest.param(
                "<ol>\n  <li>One\n    <ol>\n      <li>1.1</li>\n      <li>1.2</li>\n"
                "    </ol>\n  </li>\n  <li>Two</li>\n</ol>\n",
                "<ol><li>One<ol><li>1.1</li><li>1.2</li></ol></li><li>Two</li></ol>",
                id="nested-ol-in-li",
            ),
            pytest.param(
                # The issue's literal shape: a nested list after "</li>", a sibling
                # of the items rather than inside one.
                "<ol>\n  <li>One</li>\n  <ol>\n    <li>1.1</li>\n  </ol>\n  <li>Two</li>\n</ol>\n",
                "<ol><li>One</li><ol><li>1.1</li></ol><li>Two</li></ol>",
                id="nested-ol-after-li-close",
            ),
            pytest.param(
                "<ul>\r\n\t<li>A\r\n\t\t<ol>\r\n\t\t\t<li>a1</li>\r\n\t\t</ol>\r\n"
                "\t</li>\r\n\t<li>B</li>\r\n</ul>\r\n",
                "<ul><li>A<ol><li>a1</li></ol></li><li>B</li></ul>",
                id="tabs-and-crlf",
            ),
            pytest.param(
                "<ul>\n  <li>\n    <ul>\n      <li>C1</li>\n    </ul>\n  </li>\n"
                "  <li>D</li>\n</ul>\n",
                "<ul><li><ul><li>C1</li></ul></li><li>D</li></ul>",
                id="bare-parent-li",
            ),
            pytest.param(
                "<ul>\n  <li><b>A</b>\n    <ul>\n      <li>a1</li>\n    </ul>\n  </li>\n"
                "  <li>B</li>\n</ul>\n",
                "<ul><li><b>A</b><ul><li>a1</li></ul></li><li>B</li></ul>",
                id="inline-wrapped-parent-text",
            ),
            pytest.param(
                "<ol>\n  <li>\n    <p>One</p>\n    <ol>\n      <li>1.1</li>\n    </ol>\n"
                "  </li>\n  <li>Two</li>\n</ol>\n",
                "<ol><li><p>One</p><ol><li>1.1</li></ol></li><li>Two</li></ol>",
                id="p-wrapped-parent-text",
            ),
        ],
    )
    def test_pretty_printed_renders_like_compact(self, pretty, compact):
        pretty_requests, _ = _to_doc_requests(pretty)
        compact_requests, _ = _to_doc_requests(compact)
        rendered = _render_lists(pretty_requests)
        assert rendered == _render_lists(compact_requests)
        # No whitespace-only paragraph. An empty bullet (a bare parent <li>, #1075)
        # is in the compact form too.
        assert all(text.strip() or not text for text, *_ in rendered)


class TestBlockInsideListItem:
    """#1094: a block inside a list item (a second paragraph, code, a quote, a heading,
    a table, a rule) ended the item's list, so the next item restarted at 1. The block
    now carries the item's list_depth: the list continues past it, and it's indented
    to the item's text with no bullet. Numbering asserted through _render_lists."""

    def test_fenced_code_in_an_ordered_item(self):
        # The issue's repro (LB-05).
        md = "1. Clone the repo:\n\n   ```bash\n   git clone x\n   ```\n\n2. Install.\n"
        assert _md_lists(md) == [
            ("Clone the repo:", 0, "N1", 1),
            ("git clone x", None, None, None),
            ("Install.", 0, "N1", 2),
        ]

    def test_tight_fence_lines_are_not_items(self):
        # The tight variant (r04/r09): no blank lines around the fence.
        md = "1. a\n2. b\n   ```python\n   x\n   y\n   ```\n3. c\n"
        assert [(t, o) for t, _, _, o in _md_lists(md)] == [
            ("a", 1),
            ("b", 2),
            ("x\x0by", None),
            ("c", 3),
        ]

    def test_second_paragraph_in_an_item(self):
        md = "1. First.\n\n   Second.\n\n2. Two.\n"
        assert [(t, o) for t, _, _, o in _md_lists(md)] == [
            ("First.", 1),
            ("Second.", None),
            ("Two.", 2),
        ]

    def test_every_block_kind_keeps_the_list(self):
        for block in (
            "> quoted",
            "#### Inner heading",
            "***",
            "| K | V |\n   |---|---|\n   | k | v |",
        ):
            md = f"1. a\n\n   {block}\n\n2. b\n"
            rendered = _md_lists(md)
            items = [(t, lst, o) for t, _, lst, o in rendered if o is not None]
            assert items == [("a", "N1", 1), ("b", "N1", 2)], block

    def test_paragraph_under_a_nested_item_keeps_both_levels(self):
        md = "1. a\n   - b1\n\n     para\n\n   - b2\n2. c\n"
        assert _md_lists(md) == [
            ("a", 0, "N1", 1),
            ("b1", 1, "B2", 1),
            ("para", None, None, None),
            ("b2", 1, "B2", 2),
            ("c", 0, "N1", 2),
        ]

    def test_code_under_a_nested_numbered_item(self):
        md = "- a\n  1. x\n     ```\n     y\n     ```\n  2. z\n- b\n"
        assert _md_lists(md) == [
            ("a", 0, "B1", 1),
            ("x", 1, "N2", 1),
            ("y", None, None, None),
            ("z", 1, "N2", 2),
            ("b", 0, "B1", 2),
        ]

    def test_block_under_the_outer_item_closes_the_sublist(self):
        # para is a's content, after a's sublist: c starts a new sublist under a.
        md = "1. a\n   - b\n\n   para\n\n   - c\n2. d\n"
        assert _md_lists(md) == [
            ("a", 0, "N1", 1),
            ("b", 1, "B2", 1),
            ("para", None, None, None),
            ("c", 1, "B3", 1),
            ("d", 0, "N1", 2),
        ]

    def test_trailing_block_does_not_join_the_next_list(self):
        md = "1. a\n\n   more\n\nOutside\n\n1. b\n"
        rendered = _md_lists(md)
        assert [(t, o) for t, _, _, o in rendered] == [
            ("a", 1),
            ("more", None),
            ("Outside", None),
            ("b", 1),
        ]
        assert rendered[0][2] != rendered[3][2]

    def test_block_is_indented_to_its_item_text(self):
        requests, _ = _to_doc_requests(_md_to_html("1. a\n\n   more\n\n2. b\n"))
        style = _final_indent_request(requests, "more")
        assert style["indentStart"] == {"magnitude": 36, "unit": "PT"}
        assert style["indentFirstLine"] == {"magnitude": 36, "unit": "PT"}
        assert "borderLeft" not in style

    def test_block_under_a_nested_item_is_indented_one_level_further(self):
        requests, _ = _to_doc_requests(_md_to_html("- a\n  - b\n\n    more\n\n  - c\n"))
        style = _final_indent_request(requests, "more")
        assert style["indentStart"] == {"magnitude": 72, "unit": "PT"}

    def test_quote_in_an_item_gets_its_border_past_the_item_text(self):
        requests, _ = _to_doc_requests(_md_to_html("- a\n\n  > q\n\n- b\n"))
        style = _final_indent_request(requests, "q")
        assert style["indentStart"] == {"magnitude": 72, "unit": "PT"}
        assert style["indentFirstLine"] == {"magnitude": 72, "unit": "PT"}
        assert "borderLeft" in style

    def test_two_quotes_in_one_item_keep_the_list(self):
        # The separator between the two quotes belongs to the item too.
        rendered = _md_lists("1. a\n\n   > q1\n\n   > q2\n\n2. b\n")
        items = [(t, lst, o) for t, _, lst, o in rendered if o is not None]
        assert items == [("a", "N1", 1), ("b", "N1", 2)]

    def test_table_in_an_item_is_inserted_at_the_item_text_indent(self):
        md = "1. a\n\n   | K | V |\n   |---|---|\n   | k | v |\n\n2. b\n"
        requests, tables = _to_doc_requests(_md_to_html(md))
        assert len(tables) == 1
        resets = [
            r["updateParagraphStyle"]["paragraphStyle"]
            for r in requests
            if "updateParagraphStyle" in r and r["updateParagraphStyle"]["fields"] == "*"
        ]
        assert resets[0]["indentStart"] == {"magnitude": 36, "unit": "PT"}
        assert resets[0]["indentFirstLine"] == {"magnitude": 36, "unit": "PT"}

    def test_heading_as_an_item_is_a_bulleted_heading(self):
        # LB-08.
        requests, _ = _to_doc_requests(_md_to_html("- # Heading inside an item\n- Plain\n"))
        assert _render_lists(requests) == [
            ("Heading inside an item", 0, "B1", 1),
            ("Plain", 0, "B1", 2),
        ]
        rng = _final_range(requests, "Heading inside an item")
        assert {
            "updateParagraphStyle": {
                "range": rng,
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        } in requests

    def test_item_with_only_a_block_does_not_break_the_next_items(self):
        # The item has no text of its own, so it's an empty bullet (#1075) with its
        # code indented under it, and the next items continue its list.
        md = "- ```\n  x\n  ```\n- b\n- c\n"
        assert _md_lists(md) == [
            ("", 0, "B1", 1),
            ("x", None, None, None),
            ("b", 0, "B1", 2),
            ("c", 0, "B1", 3),
        ]


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
        # 4 requests: delete bullets, reset style, collapse paragraph, 1pt font
        assert len(result) == 4
        rng = {"startIndex": 1, "endIndex": 2}
        assert result[0] == {"deleteParagraphBullets": {"range": rng}}
        reset = result[1]["updateParagraphStyle"]
        assert reset["range"] == rng
        assert reset["paragraphStyle"] == {"namedStyleType": "NORMAL_TEXT"}
        assert reset["fields"] == "namedStyleType,indentStart,indentFirstLine,borderLeft"
        ps = result[2]["updateParagraphStyle"]
        assert ps["range"] == rng
        assert ps["paragraphStyle"]["spaceAbove"] == {"magnitude": 0, "unit": "PT"}
        assert ps["paragraphStyle"]["spaceBelow"] == {"magnitude": 0, "unit": "PT"}
        assert ps["paragraphStyle"]["lineSpacing"] == 1
        assert ps["fields"] == "spaceAbove,spaceBelow,lineSpacing"
        ts = result[3]["updateTextStyle"]
        assert ts["range"] == rng
        assert ts["textStyle"]["fontSize"] == {"magnitude": 1, "unit": "PT"}
        assert ts["fields"] == "fontSize"

    def test_style_inherited_from_following_block_reset(self):
        """insertTable gives the paragraph before a table the following block's style
        (#1097): a following list's bullet showed as an empty item and pushed the list's
        numbering on; a following quote's indent and border came along too (PR #1199 QA
        round 1). Bullets go first: deleteParagraphBullets adds indent, which the reset
        must then clear."""
        doc = self._doc([self._blank_para(1, 2), self._table_elem(2)])
        result = _build_blank_para_before_table_collapses(doc)
        assert "deleteParagraphBullets" in result[0]
        fields = result[1]["updateParagraphStyle"]["fields"].split(",")
        assert {"indentStart", "indentFirstLine", "borderLeft"} <= set(fields)
        style = result[1]["updateParagraphStyle"]["paragraphStyle"]
        assert not {"indentStart", "indentFirstLine", "borderLeft"} & set(style)

    def test_heading_blank_para_before_table_reset_to_normal_text(self):
        # #1092: the displaced initial paragraph inherits the preceding heading's style,
        # so a "## Decisions" + table doc left an empty HEADING_2 paragraph behind.
        heading = {
            "startIndex": 1,
            "endIndex": 12,
            "paragraph": {
                "elements": [{"textRun": {"content": "Decisions\n"}}],
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
            },
        }
        doc = self._doc([heading, self._blank_para(12, 13), self._table_elem(13)])
        result = _build_blank_para_before_table_collapses(doc)
        ps = result[1]["updateParagraphStyle"]
        assert ps["range"] == {"startIndex": 12, "endIndex": 13}
        assert ps["paragraphStyle"]["namedStyleType"] == "NORMAL_TEXT"
        assert "namedStyleType" in ps["fields"].split(",")

    def test_non_blank_para_before_table_not_collapsed(self):
        doc = self._doc([self._text_para(1, 8, "Hello\n\n"), self._table_elem(8)])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_table_first_element_not_touched(self):
        doc = self._doc([self._table_elem(1)])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_multiple_blank_paras_before_tables_four_requests_each(self):
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
        # 4 requests per blank para = 8 total
        assert len(result) == 8
        starts = [next(iter(r.values()))["range"]["startIndex"] for r in result]
        assert starts == [1] * 4 + [15] * 4

    def test_para_before_non_table_not_collapsed(self):
        doc = self._doc([self._blank_para(1, 2), self._text_para(2, 5, "Hi\n")])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_table_preceded_by_table_not_touched(self):
        doc = self._doc([self._table_elem(1), self._table_elem(10)])
        assert _build_blank_para_before_table_collapses(doc) == []

    def test_blank_para_between_two_tables_keeps_its_height(self):
        """Collapsed, it let two tables touch and read as one (#1098). It is still reset:
        left at full height, a following list's bullet showed as an empty item between
        the tables (PR #1199 QA round 1)."""
        doc = self._doc([self._table_elem(1), self._blank_para(9, 10), self._table_elem(10)])
        result = _build_blank_para_before_table_collapses(doc)
        rng = {"startIndex": 9, "endIndex": 10}
        assert result == [
            {"deleteParagraphBullets": {"range": rng}},
            {
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType,indentStart,indentFirstLine,borderLeft",
                }
            },
        ]


class TestImagePositionalInserts:
    """#333: extract_images + ast_to_requests's image_uris handling — the combined
    descending-position pass that lets images and tables shift each other's
    positions correctly, exactly like the table-only pass it generalizes."""

    def test_extract_images_collects_in_document_order(self):
        img1 = Image(src="a.png")
        img2 = Image(src="b.png")
        nodes = [
            Paragraph(runs=[Run("before "), img1, Run(" after")]),
            BulletItem(runs=[img2]),
        ]
        assert extract_images(nodes) == [img1, img2]

    def test_extract_images_includes_table_cells_in_document_order(self):
        # #1073: cell images, nested tables included, are resolved like body ones.
        body1, cell1, nested, cell2, body2 = (Image(src=s) for s in "abcde")
        inner = Table(rows=[Row(cells=[Cell(children=[nested])])])
        table = Table(
            rows=[
                Row(cells=[Cell(children=[Run("x"), cell1]), Cell(children=[inner])]),
                Row(cells=[Cell(children=[cell2])]),
            ]
        )
        nodes = [Paragraph(runs=[body1]), table, Paragraph(runs=[body2])]
        assert extract_images(nodes) == [body1, cell1, nested, cell2, body2]

    def test_unresolved_image_dropped_no_crash(self):
        nodes = [Paragraph(runs=[Run("before "), Image(src="a.png"), Run(" after")])]
        requests, _ = ast_to_requests(nodes)  # no image_uris
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "before  after\n"
        assert not any("insertInlineImage" in r for r in requests)

    def test_resolved_image_positioned_correctly_with_size(self):
        img = Image(src="a.png", width=100.0, height=50.0)
        nodes = [Paragraph(runs=[Run("Before")]), Paragraph(runs=[img])]
        requests, _ = ast_to_requests(nodes, image_uris={id(img): "https://example.com/a.png"})
        image_reqs = [r for r in requests if "insertInlineImage" in r]
        assert len(image_reqs) == 1
        req = image_reqs[0]["insertInlineImage"]
        assert req["uri"] == "https://example.com/a.png"
        assert req["location"]["index"] == 8  # "Before\n" = 7 chars, start_index 1
        assert req["objectSize"]["width"] == {"magnitude": 100.0, "unit": "PT"}
        assert req["objectSize"]["height"] == {"magnitude": 50.0, "unit": "PT"}

    def test_image_position_accounts_for_preceding_bullet_tab_consumption(self):
        # A nested bullet's leading tabs are consumed by createParagraphBullets
        # before the image-insertion pass runs — the image's own final position
        # must already reflect that shrinkage (tabs_through in ast_to_requests).
        img = Image(src="a.png")
        nodes = [
            BulletItem(runs=[Run("outer")], depth=0),
            BulletItem(runs=[Run("nested")], depth=1),
            Paragraph(runs=[img]),
        ]
        requests, _ = ast_to_requests(nodes, image_uris={id(img): "https://example.com/a.png"})
        insert = next(r for r in requests if "insertText" in r)
        # Raw text (pre-tab-removal): "outer\n" (6) + "\tnested\n" (8) = 14 chars from
        # start_index 1, so the image's own paragraph starts at raw position 15 — one
        # tab (1 char) gets removed by createParagraphBullets, so its final position
        # must be 15 - 1 = 14, not the raw 15.
        assert insert["insertText"]["text"] == "outer\n\tnested\n\n"
        image_req = next(r for r in requests if "insertInlineImage" in r)
        assert image_req["insertInlineImage"]["location"]["index"] == 14

    def test_image_after_table_lands_correctly_not_shifted_by_table_insertion(self):
        # The core ordering fix (#333): an image positioned after a table in the
        # document must not have its target position invalidated by the table's
        # own insertTable request running first — both are applied together in
        # one descending-position pass, not as two separate blocks.
        img = Image(src="a.png")
        table = Table(rows=[Row(cells=[Cell(children=[Run("cell")])])])
        nodes = [
            Paragraph(runs=[Run("Before")]),
            table,
            Paragraph(runs=[img]),
        ]
        requests, tables = ast_to_requests(nodes, image_uris={id(img): "https://example.com/a.png"})
        assert tables == [table]
        insert = next(r for r in requests if "insertText" in r)
        # "Before\n" (7 chars), the table's placeholder paragraph (#1097), then "\n"
        # for the image's own now-empty paragraph.
        assert insert["insertText"]["text"] == "Before\n\n\n"
        table_req = next(r for r in requests if "insertTable" in r)
        image_req = next(r for r in requests if "insertInlineImage" in r)
        # Table lands at its placeholder right after "Before\n" (position 8); the
        # image's own paragraph starts at 9. The image request is processed first in
        # the combined descending pass, so it isn't shifted by the table insertion
        # despite appearing later in the document.
        assert table_req["insertTable"]["location"]["index"] == 8
        assert image_req["insertInlineImage"]["location"]["index"] == 9
        # Descending-position ordering means the higher-position insertion (here,
        # a tie — image is emitted after its own node walk, so it appears after
        # the table in requests) must still not corrupt either target index.
        idx_table = requests.index(table_req)
        idx_image = requests.index(image_req)
        assert {idx_table, idx_image}.issubset(range(len(requests)))


class TestImageLinks:
    """#977: an <img> inside <a href> (markdown "[![alt](src)](url)") keeps its
    link through the parser and the emitter."""

    def _image(self, nodes):
        return next(item for item in nodes[0].runs if isinstance(item, Image))

    def test_parser_carries_enclosing_href_onto_image(self):
        nodes = html_to_ast('<p><a href="https://t"><img src="https://x/i.png"></a></p>')
        assert self._image(nodes).link_url == "https://t"

    def test_parser_markdown_linked_image(self):
        nodes = html_to_ast(_md_to_html("[![alt](https://x/i.png)](https://t)"))
        image = self._image(nodes)
        assert (image.alt, image.link_url) == ("alt", "https://t")

    def test_parser_image_outside_link_has_no_link(self):
        nodes = html_to_ast('<p><a href="https://t">text</a><img src="https://x/i.png"></p>')
        assert self._image(nodes).link_url is None

    def test_parser_top_level_linked_image_gets_implicit_paragraph(self):
        # PR #992 QA round 1: raw HTML with no enclosing block dropped the image.
        nodes = html_to_ast('<a href="https://t"><img src="https://x/i.png"></a>')
        assert len(nodes) == 1
        assert self._image(nodes).link_url == "https://t"

    def test_parser_top_level_link_does_not_reach_later_text_or_images(self):
        nodes = html_to_ast(
            '<a href="https://t">dropped</a><img src="https://x/a.png"><p>text</p>'
            '<a href="https://u"><p>in block</p></a>'
        )
        assert self._image(nodes).link_url is None
        assert [r.link_url for node in nodes[1:] for r in node.runs] == [None, None]

    def test_parser_hrefless_nested_anchor_keeps_outer_link_bare(self):
        # PR #992 QA round 2: an href-less </a> popped the outer bare link.
        nodes = html_to_ast('<a href="https://u"><a name="n"></a><img src="https://x/a.png"></a>')
        assert self._image(nodes).link_url == "https://u"

    def test_parser_hrefless_nested_anchor_keeps_outer_link_in_block(self):
        # #994: the same defect in the block-level stack, for text and images.
        nodes = html_to_ast(
            '<p><a href="https://u"><a name="n"></a>tail<img src="https://x/a.png"></a> after</p>'
        )
        runs = nodes[0].runs
        assert [r.link_url for r in runs] == ["https://u", "https://u", None]

    def test_parser_outer_close_after_nested_anchor_ends_the_link(self):
        nodes = html_to_ast(
            '<a href="https://u"><a name="n"></a></a><img src="https://x/a.png">'
            '<p><a href="https://v"><a name="n"></a></a>plain</p>'
        )
        assert self._image(nodes).link_url is None
        assert [r.link_url for r in nodes[1].runs] == [None]

    def test_parser_image_between_linked_text_shares_the_link(self):
        nodes = html_to_ast('<p><a href="https://t">a<img src="https://x/i.png">b</a></p>')
        runs = nodes[0].runs
        assert [r.link_url for r in runs] == ["https://t", "https://t", "https://t"]

    def test_emitter_links_image_right_after_its_insert(self):
        img = Image(src="a.png", link_url="https://t")
        nodes = [Paragraph(runs=[Run("Before")]), Paragraph(runs=[img])]
        requests, _ = ast_to_requests(nodes, image_uris={id(img): "https://example.com/a.png"})
        i = next(i for i, r in enumerate(requests) if "insertInlineImage" in r)
        assert requests[i]["insertInlineImage"]["location"]["index"] == 8
        assert requests[i + 1] == {
            "updateTextStyle": {
                "range": {"startIndex": 8, "endIndex": 9},
                "textStyle": {"link": {"url": "https://t"}},
                "fields": "link",
            }
        }

    def test_emitter_unlinked_image_gets_no_link_request(self):
        # An inserted image doesn't inherit a neighboring run's link (confirmed
        # live), so there's nothing to clear.
        img = Image(src="a.png")
        nodes = [Paragraph(runs=[Run("text", link_url="https://t"), img])]
        requests, _ = ast_to_requests(nodes, image_uris={id(img): "https://example.com/a.png"})
        links = [r for r in requests if "link" in r.get("updateTextStyle", {}).get("textStyle", {})]
        assert [r["updateTextStyle"]["range"] for r in links] == [{"startIndex": 1, "endIndex": 5}]

    def test_emitter_adjacent_images_keep_source_order(self):
        # PR #992 QA round 1: images with nothing between them share a position,
        # and each insert lands in front of what's already there, so the later
        # one must be inserted first.
        img1 = Image(src="a.png", link_url="https://one")
        img2 = Image(src="b.png", link_url="https://two")
        img3 = Image(src="c.png")
        nodes = [Paragraph(runs=[Run("x"), img1, img2, img3])]
        uris = {id(i): i.src for i in (img1, img2, img3)}
        requests, _ = ast_to_requests(nodes, image_uris=uris)
        tail = [r for r in requests if "insertInlineImage" in r or "link" in str(r)]
        assert [r["insertInlineImage"]["uri"] for r in tail if "insertInlineImage" in r] == [
            "c.png",
            "b.png",
            "a.png",
        ]
        # Simulate the inserts in order: each lands at index 2, in front of the rest.
        doc: list[str] = []
        for r in tail:
            if "insertInlineImage" in r:
                doc.insert(0, r["insertInlineImage"]["uri"])
        assert doc == ["a.png", "b.png", "c.png"]
        # Each link still directly follows its own image's insert.
        for i, r in enumerate(tail):
            if r.get("insertInlineImage", {}).get("uri") == "a.png":
                assert tail[i + 1]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://one"

    def test_emitter_table_still_precedes_image_at_same_position(self):
        img = Image(src="a.png")
        table = Table(rows=[Row(cells=[Cell(children=[Run("cell")])])])
        nodes = [Paragraph(runs=[Run("Before")]), table, Paragraph(runs=[img])]
        requests, _ = ast_to_requests(nodes, image_uris={id(img): "a.png"})
        kinds = [next(iter(r)) for r in requests if "insertTable" in r or "insertInlineImage" in r]
        # Both target index 8: the image (later in the doc) goes first, then the
        # table is inserted in front of it.
        assert kinds == ["insertInlineImage", "insertTable"]

    def test_emitter_each_link_follows_its_own_image_across_tables(self):
        # The descending pass interleaves images and tables; every link request
        # must stay paired with (directly after) its own image's insert.
        img1 = Image(src="a.png", link_url="https://one")
        img2 = Image(src="b.png")
        img3 = Image(src="c.png", link_url="https://three")
        table = Table(rows=[Row(cells=[Cell(children=[Run("cell")])])])
        nodes = [
            Paragraph(runs=[Run("x"), img1]),
            table,
            Paragraph(runs=[img2, Run("y"), img3]),
        ]
        uris = {id(i): f"https://example.com/{i.src}" for i in (img1, img2, img3)}
        requests, _ = ast_to_requests(nodes, image_uris=uris)
        for img in (img1, img2, img3):
            i = next(
                i
                for i, r in enumerate(requests)
                if r.get("insertInlineImage", {}).get("uri") == uris[id(img)]
            )
            index = requests[i]["insertInlineImage"]["location"]["index"]
            following = requests[i + 1] if i + 1 < len(requests) else {}
            if img.link_url is None:
                assert "updateTextStyle" not in following
            else:
                assert following["updateTextStyle"]["range"] == {
                    "startIndex": index,
                    "endIndex": index + 1,
                }
                assert following["updateTextStyle"]["textStyle"] == {"link": {"url": img.link_url}}


class TestTablePlaceholder:
    """Each table is inserted at a placeholder paragraph of its own, deleted right after
    (#1097). Inserted at the next block instead, the table took that block's indent and
    every empty cell its first character's text style."""

    @staticmethod
    def _table(rows: int = 1, cols: int = 1) -> Table:
        return Table(
            rows=[Row(cells=[Cell(children=[Run("x")]) for _ in range(cols)]) for _ in range(rows)]
        )

    def test_inserted_table_length_matches_live_counts(self):
        # Confirmed live: 2x2 adds 13 indices, 2x3 adds 17.
        assert _inserted_table_length(2, 2) == 13
        assert _inserted_table_length(2, 3) == 17

    def test_table_inserted_at_its_placeholder_then_placeholder_deleted(self):
        nodes = [
            Paragraph(runs=[Run("Before")]),
            self._table(2, 3),
            Paragraph(runs=[Run("Hotel:", bold=True), Run(" Casa")]),
        ]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        # "Before\n" (7), the placeholder at 8, then the following paragraph at 9.
        assert insert["insertText"]["text"] == "Before\n\nHotel: Casa\n"
        i = next(i for i, r in enumerate(requests) if "insertTable" in r)
        assert requests[i]["insertTable"]["location"]["index"] == 8
        # insertTable pushes the placeholder to 8 + 17; the next request deletes it.
        assert requests[i + 1] == {
            "deleteContentRange": {"range": {"startIndex": 25, "endIndex": 26}}
        }
        # The following paragraph's bold run starts after the placeholder.
        bold = next(r for r in requests if "updateTextStyle" in r)
        assert bold["updateTextStyle"]["range"] == {"startIndex": 9, "endIndex": 15}

    @staticmethod
    def _touching(requests: list[dict], rng: dict) -> list[int]:
        return [
            i
            for i, r in enumerate(requests)
            for v in r.values()
            if isinstance(v, dict) and v.get("range") == rng
        ]

    @staticmethod
    def _plain(rng: dict, paragraph_style: dict | None = None) -> list[dict]:
        return [
            {"deleteParagraphBullets": {"range": rng}},
            {
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": paragraph_style or {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "*",
                }
            },
            {"updateTextStyle": {"range": rng, "textStyle": {}, "fields": "*"}},
        ]

    def test_placeholder_reset_to_plain_after_bullets_before_insert(self):
        nodes = [self._table(), BulletItem(runs=[Run("one")], depth=0, ordered=True)]
        requests, _ = ast_to_requests(nodes)
        placeholder = {"startIndex": 1, "endIndex": 2}
        touching = self._touching(requests, placeholder)
        assert [requests[i] for i in touching] == self._plain(placeholder)
        bullets = next(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        assert requests[bullets]["createParagraphBullets"]["range"]["startIndex"] == 2
        insert = next(i for i, r in enumerate(requests) if "insertTable" in r)
        assert all(bullets < i < insert for i in touching)

    def test_table_between_list_items_keeps_one_list_and_a_plain_placeholder(self):
        # PR #1201 QA round 1: the bullet run skips Table nodes, so "1. a" / table /
        # "2. b" is one createParagraphBullets range, placeholder included. Both items
        # stay one list (one call), and the placeholder loses its bullet afterward.
        nodes = [
            BulletItem(runs=[Run("a")], depth=0, ordered=True),
            BulletItem(runs=[Run("b")], depth=1, ordered=True),
            self._table(),
            BulletItem(runs=[Run("c")], depth=0, ordered=True),
        ]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "a\n\tb\n\nc\n"
        bullet_calls = [i for i, r in enumerate(requests) if "createParagraphBullets" in r]
        assert len(bullet_calls) == 1
        assert requests[bullet_calls[0]]["createParagraphBullets"]["range"] == {
            "startIndex": 1,
            "endIndex": 9,
        }
        # The placeholder sits at 6 in the inserted text, 5 once b's tab is consumed.
        placeholder = {"startIndex": 5, "endIndex": 6}
        touching = self._touching(requests, placeholder)
        assert [requests[i] for i in touching] == self._plain(placeholder)
        table = next(i for i, r in enumerate(requests) if "insertTable" in r)
        assert requests[table]["insertTable"]["location"]["index"] == 5
        assert all(bullet_calls[0] < i < table for i in touching)

    def test_consecutive_tables_each_get_a_placeholder(self):
        nodes = [self._table(), self._table(1, 2)]
        requests, _ = ast_to_requests(nodes)
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "\n\n"
        pairs = [
            (r["insertTable"]["location"]["index"], requests[i + 1]["deleteContentRange"])
            for i, r in enumerate(requests)
            if "insertTable" in r
        ]
        # Latest first: the 1x2 table at its placeholder (2), then the 1x1 at 1.
        assert pairs == [
            (2, {"range": {"startIndex": 2 + 8, "endIndex": 2 + 9}}),
            (1, {"range": {"startIndex": 1 + 6, "endIndex": 1 + 7}}),
        ]

    def test_degenerate_table_gets_no_placeholder(self):
        nodes = [Paragraph(runs=[Run("a")]), Table(rows=[]), Paragraph(runs=[Run("b")])]
        requests, tables = ast_to_requests(nodes)
        assert tables == []
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "a\nb\n"
        assert not any("deleteContentRange" in r for r in requests)


class TestQuotedTable:
    """A table inside a blockquote is indented like the quote (#1097, PR #1201 QA round
    1): inserted at the following quote paragraph it took that indent by accident, and at
    a plain placeholder it lost it. No border: the table doesn't take one."""

    def test_parser_records_quote_depth_on_a_top_level_table(self):
        nodes = html_to_ast(
            "<blockquote><p>a</p><table><tr><td>x</td></tr></table><p>b</p></blockquote>"
            "<table><tr><td>y</td></tr></table>"
        )
        tables = [n for n in nodes if isinstance(n, Table)]
        assert [t.blockquote_depth for t in tables] == [1, 0]

    def test_markdown_quoted_table_gets_quote_depth(self):
        md = "> quote a\n>\n> | Q | R |\n> |---|---|\n> | 1 | 2 |\n>\n> quote b\n"
        nodes = html_to_ast(_md_to_html(md))
        (table,) = [n for n in nodes if isinstance(n, Table)]
        assert table.blockquote_depth == 1

    def test_quoted_table_placeholder_indented_without_border(self):
        table = Table(rows=[Row(cells=[Cell(children=[Run("x")])])], blockquote_depth=2)
        requests, _ = ast_to_requests([Paragraph(runs=[Run("a")]), table])
        rng = {"startIndex": 3, "endIndex": 4}
        style = next(
            r["updateParagraphStyle"]
            for r in requests
            if r.get("updateParagraphStyle", {}).get("range") == rng
        )
        assert style["paragraphStyle"] == {
            "namedStyleType": "NORMAL_TEXT",
            "indentStart": {"magnitude": 72, "unit": "PT"},
            "indentFirstLine": {"magnitude": 72, "unit": "PT"},
        }
        assert style["fields"] == "*"

    def test_quoted_table_is_not_quoted_for_separators_or_spacing(self):
        # Table.blockquote_depth is indent only: two quotes around a table still get
        # quote-edge spacing against it, and no separator is added next to it.
        nodes = html_to_ast(
            "<blockquote><p>a</p><table><tr><td>x</td></tr></table><p>b</p></blockquote>"
        )
        requests, _ = ast_to_requests(nodes)
        spacing = [
            r["updateParagraphStyle"]["paragraphStyle"]
            for r in requests
            if "updateParagraphStyle" in r
            and set(r["updateParagraphStyle"]["paragraphStyle"]) & {"spaceAbove", "spaceBelow"}
        ]
        assert spacing == [
            {"spaceAbove": {"magnitude": 8, "unit": "PT"}},
            {"spaceBelow": {"magnitude": 8, "unit": "PT"}},
            {"spaceAbove": {"magnitude": 8, "unit": "PT"}},
            {"spaceBelow": {"magnitude": 8, "unit": "PT"}},
        ]


class TestEmptyListItemIsABullet:
    """#1075: a list item with no text (a Markdown bare `-`, an HTML `<li></li>`) was
    dropped, so the list lost an item and an ordered list a number. Every item is now a
    bullet, an empty one when it has no text, with a list nested under it one level
    deeper."""

    def test_bare_dash_between_items(self):
        assert _md_lists("- a\n-\n- c\n") == [
            ("a", 0, "B1", 1),
            ("", 0, "B1", 2),
            ("c", 0, "B1", 3),
        ]

    def test_bare_dash_as_the_first_item(self):
        assert _md_lists("-\n- b\n") == [("", 0, "B1", 1), ("b", 0, "B1", 2)]

    def test_empty_ordered_item_keeps_its_number(self):
        assert _md_lists("1. a\n2.\n3. c\n") == [
            ("a", 0, "N1", 1),
            ("", 0, "N1", 2),
            ("c", 0, "N1", 3),
        ]

    def test_nested_list_under_an_empty_item_is_one_level_deeper(self):
        # TC-DOC105/106 Case 2.
        assert _md_lists("-\n  - C1\n  - C2\n- d\n") == [
            ("", 0, "B1", 1),
            ("C1", 1, "B1", 1),
            ("C2", 1, "B1", 2),
            ("d", 0, "B1", 2),
        ]

    def test_item_whose_only_content_is_a_nested_list(self):
        assert _md_lists("- - x\n") == [("", 0, "B1", 1), ("x", 1, "B1", 1)]

    def test_empty_item_in_a_loose_list(self):
        assert _md_lists("- a\n\n-\n\n- c\n") == [
            ("a", 0, "B1", 1),
            ("", 0, "B1", 2),
            ("c", 0, "B1", 3),
        ]

    def test_empty_item_in_a_quote_keeps_the_quote(self):
        nodes = html_to_ast(_md_to_html("> - a\n> -\n"))
        assert [(type(n), n.runs, n.blockquote_depth) for n in nodes][1] == (BulletItem, [], 1)

    def test_empty_html_item(self):
        nodes = html_to_ast("<ol><li>a</li><li></li><li> </li><li>d</li></ol>")
        assert all(isinstance(n, BulletItem) and n.ordered for n in nodes)
        assert [n.runs for n in nodes][1:3] == [[], []]

    def test_empty_item_inserts_an_empty_paragraph(self):
        requests, _ = _to_doc_requests(_md_to_html("- a\n-\n- c\n"))
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "a\n\nc\n"

    def test_item_whose_only_content_is_a_rule(self):
        # PR #1322 QA round 1: like a code block or quote there, the rule is a block
        # inside the empty item, and the list continues past it.
        assert _md_lists("- a\n-\n  ---\n- c\n") == [
            ("a", 0, "B1", 1),
            ("", 0, "B1", 2),
            ("", None, None, None),
            ("c", 0, "B1", 3),
        ]
        nodes = html_to_ast("<ol><li><hr></li><li>b</li></ol>")
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, BulletItem]
        assert nodes[0].runs == [] and nodes[1].runs == []
        assert nodes[1].list_depth == 0
        assert nodes[1].list_path == nodes[0].list_path

    def test_text_after_a_rule_in_an_empty_item_stays_in_the_item(self):
        nodes = html_to_ast("<ul><li><hr>after</li></ul>")
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, Paragraph]
        assert nodes[2].runs[0].text == "after"
        assert [n.list_depth for n in nodes[1:]] == [0, 0]

    def test_rule_in_an_empty_paragraph_keeps_its_boundary(self):
        # Only a fresh <li> changed: a fresh <p> with no text before its rule keeps
        # #401's dropped-construct boundary.
        assert html_to_ast("<p><hr></p>") == [Paragraph(runs=[])]

    def test_dash_under_text_is_still_a_heading_underline(self):
        # CommonMark (and GitHub): a "-" line right under paragraph text underlines
        # it as a setext heading. That's the spec, not this issue's defect.
        nodes = html_to_ast(_md_to_html("text\n-\n"))
        assert [type(n) for n in nodes] == [Heading]

    def test_tc_doc106_fixture(self):
        # TC-DOC106's live fixture: Case 2 is the issue's repro, Case 4 an empty item
        # between items in a bulleted and a numbered list.
        md = (
            Path(__file__).parent / "../docs/qa/fixtures/tc-doc106-nested-lists-4space.md"
        ).read_text()
        rendered = _md_lists(md)
        case2 = rendered.index(
            ("Case 2: parent item has NO text of its own, just a nested list", None, None, None)
        )
        assert [row[:2] for row in rendered[case2 + 1 : case2 + 4]] == [
            ("", 0),
            ("Bare-nested child C1", 1),
            ("Bare-nested child C2", 1),
        ]
        case4 = rendered.index(("Case 4: empty items between items", None, None, None))
        assert [(text, level, ordinal) for text, level, _, ordinal in rendered[case4 + 1 :]] == [
            ("Bullet before", 0, 1),
            ("", 0, 2),
            ("Bullet after", 0, 3),
            ("Number one", 0, 1),
            ("", 0, 2),
            ("Number three", 0, 3),
            # An item whose only content is a rule (PR #1322 QA round 1).
            ("Rule item before", 0, 1),
            ("", 0, 2),
            ("", None, None),
            ("Rule item after", 0, 3),
        ]
