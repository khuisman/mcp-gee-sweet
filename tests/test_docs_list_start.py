"""An ordered list that doesn't start at 1 (#1118).

No Docs API request sets a list's start number. A top-level list that picks up where the
last list stopped joins it, and any other such list is written as literal numbers."""

import copy

import pytest

from mcp_gee_sweet.tools.docs.ast import BulletItem, Heading, Paragraph
from mcp_gee_sweet.tools.docs.ast_to_markdown import ast_to_markdown
from mcp_gee_sweet.tools.docs.content import _md_to_html, _walk_headings_and_anchor_runs
from mcp_gee_sweet.tools.docs.doc_to_ast import document_to_ast
from mcp_gee_sweet.tools.docs.emitter import (
    _resolve_list_starts,
    ast_to_requests,
    literal_list_marker,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast


def _ast(markdown_text: str):
    return html_to_ast(_md_to_html(markdown_text))


def _requests(markdown_text: str) -> list[dict]:
    return ast_to_requests(_ast(markdown_text))[0]


def _inserted(requests: list[dict]) -> str:
    return requests[0]["insertText"]["text"]


def _of(requests: list[dict], kind: str) -> list[dict]:
    return [r[kind] for r in requests if kind in r]


class TestParserReadsStart:
    def test_items_carry_their_numbers(self):
        nodes = _ast("3. a\n4. b\n")
        assert [n.number for n in nodes] == [3, 4]

    def test_a_list_starting_at_1_has_no_numbers(self):
        assert [n.number for n in _ast("1. a\n2. b\n")] == [None, None]

    def test_an_interrupted_item_counts_once(self):
        nodes = _ast("3. a\n\n   para\n\n4. b\n")
        assert [n.number for n in nodes if isinstance(n, BulletItem)] == [3, 4]

    def test_a_nested_list_counts_on_its_own(self):
        nodes = html_to_ast('<ol start="5"><li>a<ol start="2"><li>b</li></ol></li><li>c</li></ol>')
        assert [n.number for n in nodes] == [5, 2, 6]

    @pytest.mark.parametrize(
        ("value", "number"),
        [
            ("0", 0),
            ("-2", -2),
            ("+4", 4),
            (" 4", 4),
            ("4abc", 4),
            ("1", None),
            ("abc", None),
            ("", None),
            ("9" * 5000, None),
            ("99999999999", None),
        ],
    )
    def test_start_is_read_as_a_browser_reads_it(self, value, number):
        assert html_to_ast(f'<ol start="{value}"><li>a</li></ol>')[0].number == number

    def test_a_ul_start_means_nothing(self):
        assert html_to_ast('<ul start="3"><li>a</li></ul>')[0].number is None


class TestLiteralNumbers:
    def test_a_list_starting_at_3_is_written_with_its_numbers(self):
        requests = _requests("3. Three\n4. Four\n5. Five\n")
        assert _inserted(requests) == "3.\tThree\n4.\tFour\n5.\tFive\n"
        assert not _of(requests, "createParagraphBullets")

    def test_each_item_takes_the_list_levels_hanging_indent(self):
        styles = [
            s
            for s in _of(_requests("3. a\n"), "updateParagraphStyle")
            if "indentStart" in s["paragraphStyle"]
        ]
        assert len(styles) == 1
        assert styles[0]["paragraphStyle"]["indentStart"]["magnitude"] == 36
        assert styles[0]["paragraphStyle"]["indentFirstLine"]["magnitude"] == 18
        assert "borderLeft" not in styles[0]["paragraphStyle"]

    def test_a_quoted_item_keeps_the_quote(self):
        styles = [
            s
            for s in _of(_requests("> 3. a\n"), "updateParagraphStyle")
            if "indentStart" in s["paragraphStyle"]
        ]
        assert styles[-1]["paragraphStyle"]["indentStart"]["magnitude"] == 72
        assert styles[-1]["paragraphStyle"]["indentFirstLine"]["magnitude"] == 54
        assert "borderLeft" in styles[-1]["paragraphStyle"]

    def test_run_styles_land_past_the_marker(self):
        requests = _requests("3. **bold**\n")
        bold = next(s for s in _of(requests, "updateTextStyle") if s["textStyle"].get("bold"))
        assert (bold["range"]["startIndex"], bold["range"]["endIndex"]) == (4, 8)

    def test_a_task_item_keeps_its_checkbox(self):
        assert _inserted(_requests("3. [x] done\n")) == "3.\t☑ done\n"

    def test_a_heading_item_stays_a_heading(self):
        nodes, _ = _resolve_list_starts(_ast("3. # Title\n"))
        assert isinstance(nodes[0], Heading)
        assert nodes[0].level == 1
        assert nodes[0].literal_item_level == 0

    def test_a_sublist_under_a_literal_item_is_a_real_list_at_its_depth(self):
        requests = _requests("3. a\n   - b\n4. c\n")
        assert _inserted(requests) == "3.\ta\n\tb\n4.\tc\n"
        assert any(
            s["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"
            for s in _of(requests, "createParagraphBullets")
        )

    def test_a_nested_list_writes_its_levels_glyph_and_the_outer_list_keeps_counting(self):
        nodes = html_to_ast('<ol><li>a<ol start="3"><li>b</li></ol></li><li>c</li></ol>')
        resolved, _ = _resolve_list_starts(nodes)
        assert [type(n) for n in resolved] == [BulletItem, Paragraph, BulletItem]
        assert resolved[1].runs[0].text == "c.\t"
        assert resolved[1].list_depth == 0
        requests = ast_to_requests(nodes)[0]
        bullets = _of(requests, "createParagraphBullets")
        assert len(bullets) == 1
        assert bullets[0]["range"] == {"startIndex": 1, "endIndex": 1 + len("a\nc.\tb\nc\n")}
        assert {"startIndex": 3, "endIndex": 8} in [
            d["range"] for d in _of(requests, "deleteParagraphBullets")
        ]

    def test_the_callers_nodes_are_left_alone(self):
        nodes = _ast("3. [ ] a\n")
        before = copy.deepcopy(nodes)
        ast_to_requests(nodes)
        assert nodes == before
        assert isinstance(nodes[0], BulletItem)


class TestHeadingAnchor:
    def test_a_literal_heading_item_matches_by_its_own_text(self):
        body = [
            {
                "startIndex": 1,
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "HEADING_1", "headingId": "h.1"},
                    "elements": [{"startIndex": 1, "textRun": {"content": "3.\tTitle\n"}}],
                },
            }
        ]
        assert _walk_headings_and_anchor_runs(body)[0] == [("Title", "h.1")]


class TestListMarker:
    @pytest.mark.parametrize(
        ("number", "depth", "marker"),
        [
            (3, 0, "3."),
            (0, 0, "0."),
            (-2, 0, "-2."),
            (3, 1, "c."),
            (26, 1, "z."),
            (27, 1, "aa."),
            (0, 1, "0."),
            (4, 2, "iv."),
            (3999, 2, "mmmcmxcix."),
            (4000, 2, "4000."),
            (3, 3, "3."),
            (3, 4, "c."),
        ],
    )
    def test_marker(self, number, depth, marker):
        assert literal_list_marker(number, depth) == marker


class TestContinuation:
    LX_09 = "1. Step one\n\n```\ncode\n```\n\n2. Step two\n"

    def test_a_list_picking_up_the_count_joins_the_last_list(self):
        requests = _requests(self.LX_09)
        assert _inserted(requests) == "Step one\ncode\nStep two\n"
        bullets = _of(requests, "createParagraphBullets")
        assert len(bullets) == 1
        assert bullets[0]["range"] == {"startIndex": 1, "endIndex": 24}

    def test_the_block_between_is_taken_back_out(self):
        requests = _requests(self.LX_09)
        bullets_at = next(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        after = requests[bullets_at + 1 :]
        code = {"startIndex": 10, "endIndex": 15}
        assert {"deleteParagraphBullets": {"range": code}} in after
        reset = next(
            r["updateParagraphStyle"]
            for r in after
            if "updateParagraphStyle" in r and r["updateParagraphStyle"]["range"] == code
        )
        assert reset["paragraphStyle"] == {}
        assert reset["fields"] == "indentStart,indentFirstLine"

    def test_the_block_between_keeps_its_spacing(self):
        requests = _requests(self.LX_09)
        bullets_at = next(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        assert any(
            "spaceAbove" in r.get("updateParagraphStyle", {}).get("paragraphStyle", {})
            for r in requests[bullets_at:]
        )

    def test_a_quote_between_gets_its_indent_back(self):
        requests = _requests("1. a\n\n> quoted\n\n2. b\n")
        bullets_at = next(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]
            for r in requests[bullets_at:]
            if "updateParagraphStyle" in r
        ]
        assert any(s.get("indentStart", {}).get("magnitude") == 36 for s in styles)

    def test_a_table_between_stays_in_the_one_list(self):
        requests = _requests("1. a\n\n| x |\n|---|\n| y |\n\n2. b\n")
        assert len(_of(requests, "createParagraphBullets")) == 1
        assert len(_of(requests, "insertTable")) == 1

    def test_several_continuations_keep_counting(self):
        requests = _requests("1. a\n\ntext\n\n2. b\n\nmore\n\n3. c\n")
        assert _inserted(requests) == "a\ntext\nb\nmore\nc\n"
        assert len(_of(requests, "createParagraphBullets")) == 1

    def test_adjacent_lists_with_different_markers_continue(self):
        requests = _requests("1. a\n2) b\n")
        assert _inserted(requests) == "a\nb\n"
        assert len(_of(requests, "createParagraphBullets")) == 1

    def test_a_block_in_the_last_item_is_recorded_once(self):
        requests = _requests("1. a\n\n   in item\n\nout\n\n2. b\n")
        ranges = [d["range"]["startIndex"] for d in _of(requests, "deleteParagraphBullets")[-2:]]
        assert len(set(ranges)) == 2

    def test_a_wrong_number_is_literal(self):
        requests = _requests("1. a\n\ntext\n\n5. b\n")
        assert _inserted(requests) == "a\ntext\n5.\tb\n"

    def test_another_list_between_is_literal(self):
        requests = _requests("1. a\n\n- x\n\n2. b\n")
        assert _inserted(requests) == "a\nx\n2.\tb\n"
        assert len(_of(requests, "createParagraphBullets")) == 2

    def test_a_different_quote_is_literal(self):
        requests = _requests("1. a\n\ntext\n\n> 2. b\n")
        assert _inserted(requests) == "a\ntext\n2.\tb\n"

    def test_a_literal_list_is_not_continued(self):
        requests = _requests("3. a\n\ntext\n\n4. b\n")
        assert _inserted(requests) == "3.\ta\ntext\n4.\tb\n"

    def test_a_bullet_list_is_not_continued(self):
        assert _inserted(_requests("- a\n\ntext\n\n2. b\n")) == "a\ntext\n2.\tb\n"

    def test_lists_starting_at_1_are_untouched(self):
        nodes = _ast("1. a\n\ntext\n\n1. b\n")
        resolved, continuing = _resolve_list_starts(nodes)
        assert resolved is nodes
        assert not continuing
        assert len(_of(ast_to_requests(nodes)[0], "createParagraphBullets")) == 2

    def test_an_ast_with_no_list_ids_is_left_alone(self):
        nodes = [BulletItem(runs=[], ordered=True, number=3)]
        assert _resolve_list_starts(nodes)[0][0] is nodes[0]


def _para(text: str, *, start: float | None = None, first: float | None = None, border=False):
    pstyle: dict = {"namedStyleType": "NORMAL_TEXT"}
    if start is not None:
        pstyle["indentStart"] = {"magnitude": start, "unit": "PT"}
        pstyle["indentFirstLine"] = {"magnitude": first, "unit": "PT"}
    if border:
        pstyle["borderLeft"] = {"width": {"magnitude": 1, "unit": "PT"}}
    return {
        "paragraph": {
            "elements": [{"textRun": {"content": text + "\n", "textStyle": {}}}],
            "paragraphStyle": pstyle,
        }
    }


def _doc(*paragraphs):
    return {"body": {"content": list(paragraphs)}, "lists": {}}


class TestReadBack:
    def test_a_literal_item_reads_as_an_item_of_its_number(self):
        nodes = document_to_ast(_doc(_para("3.\tThree", start=36, first=18)))
        assert isinstance(nodes[0], BulletItem)
        assert nodes[0].number == 3
        assert nodes[0].ordered
        assert nodes[0].runs[0].text == "Three"

    def test_literal_items_export_as_a_list(self):
        document = _doc(
            _para("3.\tThree", start=36, first=18),
            _para("4.\tFour", start=36, first=18),
        )
        assert ast_to_markdown(document_to_ast(document)).strip() == "3. Three\n4. Four"

    def test_a_block_inside_a_literal_item_stays_inside_it(self):
        document = _doc(_para("3.\ta", start=36, first=18), _para("b", start=36, first=36))
        nodes = document_to_ast(document)
        assert nodes[1].list_depth == 0

    def test_an_unindented_rule_after_an_item_is_outside_it(self):
        rule_style = {
            "namedStyleType": "NORMAL_TEXT",
            "borderBottom": {"width": {"magnitude": 1, "unit": "PT"}},
            "borderBetween": {"width": {"magnitude": 1, "unit": "PT"}},
        }
        rule = {
            "paragraph": {
                "elements": [{"textRun": {"content": "\n"}}],
                "paragraphStyle": rule_style,
            }
        }
        nodes = document_to_ast(_doc(_para("3.\ta", start=36, first=18), rule))
        assert nodes[1].rule
        assert nodes[1].list_depth is None

    def test_a_nested_item_reads_its_levels_glyph(self):
        nodes = document_to_ast(_doc(_para("c.\tb", start=72, first=54)))
        assert (nodes[0].depth, nodes[0].number) == (1, 3)

    def test_a_quoted_item_reads_in_the_quote(self):
        nodes = document_to_ast(_doc(_para("3.\ta", start=72, first=54, border=True)))
        assert (nodes[0].depth, nodes[0].blockquote_depth, nodes[0].number) == (0, 1, 3)

    def test_a_task_item_keeps_its_state(self):
        nodes = document_to_ast(_doc(_para("3.\t☑ done", start=36, first=18)))
        assert nodes[0].checked is True
        assert nodes[0].runs[0].text == "done"

    @pytest.mark.parametrize(
        "para",
        [
            _para("3.\tThree"),  # no indent
            _para("3.\tThree", start=36, first=36),  # no hanging indent
            _para("3. Three", start=36, first=18),  # no tab
            _para("c.\tThree", start=36, first=18),  # level 0 writes digits
            _para("3.\tThree", start=40, first=22),  # not a list level
        ],
    )
    def test_any_other_paragraph_stays_a_paragraph(self, para):
        assert isinstance(document_to_ast(_doc(para))[0], Paragraph)

    def test_round_trip_of_the_written_requests(self):
        text = _inserted(_requests("3. Three\n4. **Four**\n"))
        document = _doc(*[_para(line, start=36, first=18) for line in text.split("\n")[:-1]])
        assert ast_to_markdown(document_to_ast(document)).strip() == "3. Three\n4. Four"
