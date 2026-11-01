"""A thematic break (`---`, `***`, `___`, `<hr>`) is drawn as a horizontal line (#1096).

The Docs API has no request that inserts a horizontalRule element, so the write side
draws a rule as an empty paragraph with a bottom border, and the read side takes both
that stand-in and a native horizontal line back to a Markdown rule."""

import pytest
from markdown_it import MarkdownIt

from mcp_gee_sweet.tools.docs.ast import BulletItem, Heading, Paragraph, Run
from mcp_gee_sweet.tools.docs.ast_to_markdown import ast_to_markdown
from mcp_gee_sweet.tools.docs.content import _md_to_html
from mcp_gee_sweet.tools.docs.doc_to_ast import document_to_ast
from mcp_gee_sweet.tools.docs.emitter import (
    _RULE_BORDER,
    _build_blank_para_before_table_collapses,
    ast_to_requests,
    is_rule_style,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast

_COMMONMARK = MarkdownIt("commonmark").enable("table")


def _md(markdown_text):
    return html_to_ast(_md_to_html(markdown_text))


def _rule_styles(requests):
    """(range, paragraphStyle) of every request that draws a rule's line."""
    return [
        (r["updateParagraphStyle"]["range"], r["updateParagraphStyle"]["paragraphStyle"])
        for r in requests
        if "borderBottom" in r.get("updateParagraphStyle", {}).get("paragraphStyle", {})
    ]


def _index(requests, predicate):
    return next(i for i, r in enumerate(requests) if predicate(r))


class TestParser:
    @pytest.mark.parametrize("marker", ["---", "***", "___", "- - -", "<hr>"])
    def test_every_rule_spelling_is_a_rule_paragraph(self, marker):
        nodes = _md(f"Para\n\n{marker}\n\nNext\n")
        assert [(type(n), n.rule) for n in nodes] == [
            (Paragraph, False),
            (Paragraph, True),
            (Paragraph, False),
        ]
        assert nodes[1].runs == []

    def test_rule_in_a_quote_keeps_the_quote(self):
        # TC-MD201 CT-70/80: a rule in a quote rendered as nothing.
        nodes = _md("> a\n>\n> ***\n>\n> b\n")
        assert [(n.rule, n.blockquote_depth) for n in nodes] == [(False, 1), (True, 1), (False, 1)]
        assert len({n.blockquote_path for n in nodes}) == 1

    def test_rule_in_a_list_item_is_a_block_in_the_item(self):
        nodes = _md("- a\n\n  ---\n- b\n")
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, BulletItem]
        assert nodes[1].rule and nodes[1].list_depth == 0
        assert nodes[1].list_path == nodes[0].list_path

    def test_hr_in_pre_is_not_a_rule(self):
        assert not any(
            n.rule for n in html_to_ast("<pre>code<hr></pre>") if isinstance(n, Paragraph)
        )

    def test_hr_in_a_heading_splits_it(self):
        nodes = html_to_ast("<h2>a<hr>b</h2>")
        assert [getattr(n, "rule", False) for n in nodes] == [False, True, False]


class TestEmitter:
    def test_rule_paragraph_gets_bottom_and_between_borders(self):
        requests, _ = ast_to_requests(
            [Paragraph(runs=[Run("A")]), Paragraph(runs=[], rule=True), Paragraph(runs=[Run("B")])]
        )
        ((rng, style),) = _rule_styles(requests)
        # "A\n" is 1-3, the rule's "\n" 3-4.
        assert rng == {"startIndex": 3, "endIndex": 4}
        assert style["borderBottom"] == style["borderBetween"] == _RULE_BORDER
        assert style["spaceAbove"]["magnitude"] == 0
        assert style["spaceBelow"]["magnitude"] > 0
        assert style["lineSpacing"] == 100
        font = [
            r["updateTextStyle"]
            for r in requests
            if r.get("updateTextStyle", {}).get("range") == rng
        ]
        assert font == [
            {
                "range": rng,
                "textStyle": {"fontSize": {"magnitude": 6, "unit": "PT"}},
                "fields": "fontSize",
            }
        ]

    def test_two_rules_in_a_row_each_get_their_line(self):
        # Docs joins adjacent paragraphs with the same borders, drawing borderBottom
        # only under the last; borderBetween draws the one between (confirmed live).
        requests, _ = ast_to_requests(
            [Paragraph(runs=[], rule=True), Paragraph(runs=[], rule=True)]
        )
        assert [rng for rng, _ in _rule_styles(requests)] == [
            {"startIndex": 1, "endIndex": 2},
            {"startIndex": 2, "endIndex": 3},
        ]

    def test_plain_empty_paragraph_gets_no_rule(self):
        requests, _ = ast_to_requests([Paragraph(runs=[])])
        assert _rule_styles(requests) == []

    def test_quoted_rule_keeps_quote_border_and_edge_spacing(self):
        nodes = [Paragraph(runs=[], rule=True, blockquote_depth=1, blockquote_path=(1,))]
        requests, _ = ast_to_requests(nodes)
        rule_at = _index(
            requests,
            lambda r: "borderBottom" in r.get("updateParagraphStyle", {}).get("paragraphStyle", {}),
        )
        quote_at = _index(
            requests,
            lambda r: "borderLeft" in r.get("updateParagraphStyle", {}).get("paragraphStyle", {}),
        )
        spacing_at = [
            i
            for i, r in enumerate(requests)
            if r.get("updateParagraphStyle", {}).get("fields") in ("spaceAbove", "spaceBelow")
        ]
        # The quote's edge spacing replaces the rule's own, so it must come after.
        assert spacing_at and all(i > rule_at for i in spacing_at)
        assert quote_at != rule_at

    def test_rule_in_a_list_item_is_drawn_after_the_bullet_pass(self):
        nodes = _md("1. a\n\n   ---\n2. b\n")
        requests, _ = ast_to_requests(nodes)
        bullets_at = max(i for i, r in enumerate(requests) if "createParagraphBullets" in r)
        ((rng, _style),) = _rule_styles(requests)
        rule_at = _index(
            requests,
            lambda r: "borderBottom" in r.get("updateParagraphStyle", {}).get("paragraphStyle", {}),
        )
        assert rule_at > bullets_at
        # Indented to the item's text, like any block inside an item (#1094).
        indent = [
            r["updateParagraphStyle"]["paragraphStyle"]
            for r in requests
            if r.get("updateParagraphStyle", {}).get("range") == rng
            and "indentStart" in r["updateParagraphStyle"]["paragraphStyle"]
        ]
        assert indent and indent[-1]["indentStart"]["magnitude"] == 36

    def test_table_collapse_backstop_leaves_a_rule_alone(self):
        live_doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 2,
                        "paragraph": {
                            "elements": [{"textRun": {"content": "\n"}}],
                            "paragraphStyle": _RULE_STYLE,
                        },
                    },
                    {"startIndex": 2, "endIndex": 10, "table": {}},
                ]
            }
        }
        assert _build_blank_para_before_table_collapses(live_doc) == []


_RULE_STYLE = {"borderBottom": _RULE_BORDER, "borderBetween": _RULE_BORDER}
_BOX = dict.fromkeys(
    ("borderTop", "borderBottom", "borderLeft", "borderRight", "borderBetween"), _RULE_BORDER
)


def _doc(*paragraphs):
    return {"body": {"content": [{"paragraph": p} for p in paragraphs]}}


def _text(text, **style):
    return {"elements": [{"textRun": {"content": text, "textStyle": {}}}], "paragraphStyle": style}


class TestReadSide:
    def test_native_horizontal_line_is_a_rule(self):
        # What Drive's Markdown import and the Docs UI write (checked live).
        native = {
            "elements": [{"horizontalRule": {"textStyle": {}}}, {"textRun": {"content": "\n"}}],
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
        }
        nodes = document_to_ast(_doc(_text("a\n"), native, _text("b\n")))
        assert [n.rule for n in nodes] == [False, True, False]

    def test_bordered_empty_paragraph_is_a_rule(self):
        nodes = document_to_ast(_doc(_text("\n", **_RULE_STYLE)))
        assert nodes == [Paragraph(runs=[], rule=True)]

    @pytest.mark.parametrize(
        "paragraph",
        [
            _text("\n"),
            _text("text\n", **_RULE_STYLE),
            _text("\n", borderBottom={"width": {"unit": "PT"}}),
            # An empty line in a user's bordered box (PR #1326 QA round 1).
            _text("\n", **_BOX),
            # A bottom border alone, with no matching between-border.
            _text("\n", borderBottom=_RULE_BORDER),
        ],
        ids=["no border", "has text", "zero-width border", "boxed", "bottom only"],
    )
    def test_other_paragraphs_are_not_rules(self, paragraph):
        assert not document_to_ast(_doc(paragraph))[0].rule

    def test_is_rule_style(self):
        assert is_rule_style(_RULE_STYLE)
        # A quoted rule has the quote's left border too.
        assert is_rule_style({**_RULE_STYLE, "borderLeft": _RULE_BORDER})
        assert not is_rule_style(_BOX)
        assert not is_rule_style({"borderLeft": _RULE_BORDER})
        assert not is_rule_style({})

    def test_native_line_after_text_in_one_paragraph(self):
        # Drive's HTML import: "<p>text before<hr>text after</p>" gives the line and
        # "text after" in one paragraph (checked live).
        para = {
            "elements": [
                {"horizontalRule": {"textStyle": {}}},
                {"textRun": {"content": "text after\n", "textStyle": {}}},
            ],
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
        }
        nodes = document_to_ast(_doc(para))
        assert [(n.rule, [r.text for r in n.runs]) for n in nodes] == [
            (True, []),
            (False, ["text after"]),
        ]

    def test_native_line_in_a_list_item_is_inside_the_item(self):
        # Drive's import: "<li>item one<hr></li>" (checked live).
        item = {
            "elements": [
                {"textRun": {"content": "item one", "textStyle": {}}},
                {"horizontalRule": {"textStyle": {}}},
                {"textRun": {"content": "\n", "textStyle": {}}},
            ],
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "bullet": {"listId": "l1"},
        }
        two = {**_text("item two\n"), "bullet": {"listId": "l1"}}
        nodes = document_to_ast(_doc(item, two))
        assert [type(n) for n in nodes] == [BulletItem, Paragraph, BulletItem]
        assert nodes[1].rule and nodes[1].list_depth == 0
        assert ast_to_markdown(nodes) == "- item one\n\n  ---\n\n- item two\n"

    def test_native_line_in_a_heading_keeps_the_heading(self):
        para = {
            "elements": [
                {"textRun": {"content": "Title", "textStyle": {}}},
                {"horizontalRule": {"textStyle": {}}},
                {"textRun": {"content": "\n", "textStyle": {}}},
            ],
            "paragraphStyle": {"namedStyleType": "HEADING_2"},
        }
        nodes = document_to_ast(_doc(para))
        assert [type(n) for n in nodes] == [Heading, Paragraph]
        assert nodes[1].rule

    def test_list_item_with_only_a_native_line(self):
        item = {
            "elements": [
                {"horizontalRule": {"textStyle": {}}},
                {"textRun": {"content": "\n", "textStyle": {}}},
            ],
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "bullet": {"listId": "l1"},
        }
        nodes = document_to_ast(_doc(item))
        assert [type(n) for n in nodes] == [BulletItem, Paragraph]
        assert nodes[0].runs == [] and nodes[1].rule and nodes[1].list_depth == 0


class TestMarkdownExport:
    def test_rule_between_paragraphs(self):
        markdown = ast_to_markdown(
            [Paragraph(runs=[Run("a")]), Paragraph(runs=[], rule=True), Paragraph(runs=[Run("b")])]
        )
        assert markdown == "a\n\n---\n\nb\n"
        assert [t.type for t in _COMMONMARK.parse(markdown) if t.type == "hr"] == ["hr"]

    def test_first_line_rule_is_not_front_matter(self):
        # "---" as the first line opens YAML front matter, which the import drops when
        # what follows reads as a mapping (#1173).
        markdown = ast_to_markdown(
            [
                Paragraph(runs=[], rule=True),
                Paragraph(runs=[Run("title: x")]),
                Paragraph(runs=[], rule=True),
            ]
        )
        assert markdown == "***\n\ntitle: x\n\n---\n"
        assert _md(markdown)[1].runs[0].text == "title: x"

    def test_quoted_rule(self):
        markdown = ast_to_markdown(
            [
                Paragraph(runs=[Run("a")], blockquote_depth=1),
                Paragraph(runs=[], rule=True, blockquote_depth=1),
            ]
        )
        assert markdown == "> a\n>\n> ---\n"
        tokens = [t.type for t in _COMMONMARK.parse(markdown)]
        assert tokens.count("blockquote_open") == 1 and "hr" in tokens

    @pytest.mark.parametrize(
        "source",
        [
            "Para\n\n---\n\nNext\n",
            "> a\n>\n> ***\n>\n> b\n",
            "1. a\n\n   ---\n2. b\n",
            "- a\n\n---\n\n- b\n",
            "***\n\nAfter a leading rule\n",
            "---\n\n---\n",
        ],
    )
    def test_round_trip_keeps_every_rule(self, source):
        # Markdown -> AST -> Markdown keeps each rule where it was.
        nodes = _md(source)
        exported = ast_to_markdown(nodes)
        assert [(type(n), n.rule if isinstance(n, Paragraph) else None) for n in _md(exported)] == [
            (type(n), n.rule if isinstance(n, Paragraph) else None) for n in nodes
        ]
        hr_count = sum(t.type == "hr" for t in _COMMONMARK.parse(source))
        assert sum(t.type == "hr" for t in _COMMONMARK.parse(exported)) == hr_count


class TestRoundOneFindings:
    """PR #1326 QA round 1."""

    def test_rule_mid_quote_has_no_spacing_that_breaks_the_bar(self):
        # Spacing isn't covered by the quote bar, so a gap split one quote into two.
        nodes = _md("> a\n>\n> ---\n>\n> b\n")
        requests, _ = ast_to_requests(nodes)
        ((rng, style),) = _rule_styles(requests)
        assert style["spaceBelow"]["magnitude"] == 0
        assert style["spaceAbove"]["magnitude"] == 0
        assert not [
            r
            for r in requests
            if r.get("updateParagraphStyle", {}).get("range") == rng
            and r["updateParagraphStyle"]["fields"] in ("spaceAbove", "spaceBelow")
        ]
        font = [
            r["updateTextStyle"]["textStyle"]["fontSize"]["magnitude"]
            for r in requests
            if r.get("updateTextStyle", {}).get("range") == rng
        ]
        assert font == [4]

    def test_rule_in_an_empty_item_stays_in_the_item_on_export(self):
        # "- a\n-\n  ---\n- b" exported a blank line after the empty item's marker,
        # which CommonMark reads as the end of the item: two lists, rule at the margin.
        source = "- a\n-\n  ---\n- b\n"
        exported = ast_to_markdown(_md(source))
        assert exported == "- a\n- \n  ---\n\n- b\n"
        tokens = [t.type for t in _COMMONMARK.parse(exported)]
        assert tokens.count("bullet_list_open") == 1
        assert [(type(n), getattr(n, "list_depth", None)) for n in _md(exported)] == [
            (type(n), getattr(n, "list_depth", None)) for n in _md(source)
        ]

    def test_rule_in_an_empty_quoted_item(self):
        exported = ast_to_markdown(_md("> - a\n> -\n>   ---\n> - b\n"))
        tokens = [t.type for t in _COMMONMARK.parse(exported)]
        assert tokens.count("blockquote_open") == tokens.count("bullet_list_open") == 1

    def test_quoted_list_with_a_block_then_a_quoted_paragraph_is_one_quote(self):
        # "> - a\n>\n>   b\n>\n> c" is one Docs quote; it exported as two.
        nodes = [
            BulletItem(runs=[Run("a")], blockquote_depth=1),
            Paragraph(runs=[Run("b")], blockquote_depth=1, list_depth=0),
            Paragraph(runs=[Run("c")], blockquote_depth=1),
        ]
        exported = ast_to_markdown(nodes)
        assert exported == "> - a\n>\n>   b\n>\n> c\n"
        assert [t.type for t in _COMMONMARK.parse(exported)].count("blockquote_open") == 1

    def test_quoted_paragraph_then_quoted_list_is_one_quote(self):
        exported = ast_to_markdown(
            [
                Paragraph(runs=[Run("a")], blockquote_depth=1),
                BulletItem(runs=[Run("x")], blockquote_depth=1),
            ]
        )
        assert exported == "> a\n>\n> - x\n"

    def test_list_then_quoted_list_gets_a_blank_line(self):
        exported = ast_to_markdown(
            [BulletItem(runs=[Run("b")]), BulletItem(runs=[Run("qa")], blockquote_depth=1)]
        )
        assert exported == "- b\n\n> - qa\n"
