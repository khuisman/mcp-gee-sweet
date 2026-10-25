"""Tests for the Docs -> Markdown export path (issue #300): doc_to_ast.py's Docs
API -> AST walker, ast_to_markdown.py's AST -> Markdown serializer, and the
get_doc_as_markdown tool wiring them together."""

from html import escape
from unittest.mock import MagicMock
from xml.etree import ElementTree

import markdown
import pytest
from markdown_it import MarkdownIt

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Cell,
    Heading,
    Image,
    NamedBlock,
    Paragraph,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.ast_to_markdown import ast_to_markdown
from mcp_gee_sweet.tools.docs.doc_to_ast import document_to_ast

# Strict CommonMark, plus GFM pipe tables. Python-Markdown (used by some older
# tests below) strips whitespace inside code spans and closes a fence only on an
# exact-length match, so it can't catch padding or fence-length regressions
# (#938).
_COMMONMARK = MarkdownIt("commonmark").enable("table")


def _code(text, **kwargs):
    return Run(text=text, font_family="Courier New", **kwargs)


@pytest.mark.parametrize("ticks", [3, 4, 6])
@pytest.mark.parametrize("interleaved_image", [False, True])
def test_code_block_preserves_literal_backtick_fences(ticks, interleaved_image):
    content = f"before\n{'`' * ticks}\nafter"
    runs = [Run(text=content, font_family="Courier New")]
    if interleaved_image:
        runs += [Image(src="https://example.com/image.png"), *runs]
    rendered = ast_to_markdown([Paragraph(runs=runs)])
    assert rendered.startswith("`" * (ticks + 1) + "\nbefore\n")
    tokens = _COMMONMARK.parse(rendered)
    blocks = [t.content for t in tokens if t.type == "fence"]
    expected = [content + "\n"] * (2 if interleaved_image else 1)
    assert blocks == expected
    assert sum(t.type == "image" for t in tokens for t in (t.children or [])) == int(
        interleaved_image
    )


def _para(text, style=None, bullet=None, para_style=None):
    elem = {"paragraph": {"elements": [{"textRun": {"content": text, "textStyle": style or {}}}]}}
    if bullet:
        elem["paragraph"]["bullet"] = bullet
    if para_style:
        elem["paragraph"]["paragraphStyle"] = para_style
    return elem


def _make_tool_registry():
    captured = {}
    captured_annotations = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            captured_annotations[func.__name__] = annotations
            return func

        return decorator

    return tool, captured, captured_annotations


def _make_ctx(**services):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    for k, v in services.items():
        setattr(lc, k, v)
    return ctx


_docs_tool, _docs_tools, _docs_annotations = _make_tool_registry()
docs_module.register(_docs_tool)


class TestDocToAstParagraphs:
    def test_heading_level_from_named_style(self):
        doc = {"body": {"content": [_para("Title\n", para_style={"namedStyleType": "HEADING_2"})]}}
        nodes = document_to_ast(doc)
        assert len(nodes) == 1
        assert isinstance(nodes[0], Heading)
        assert nodes[0].level == 2
        assert nodes[0].runs[0].text == "Title"

    def test_trailing_paragraph_newline_is_stripped(self):
        doc = {"body": {"content": [_para("Hello\n")]}}
        nodes = document_to_ast(doc)
        assert nodes[0].runs[0].text == "Hello"

    def test_paragraph_that_is_only_a_newline_becomes_empty_runs(self):
        doc = {"body": {"content": [_para("\n")]}}
        nodes = document_to_ast(doc)
        assert isinstance(nodes[0], Paragraph)
        assert nodes[0].runs == []

    def test_title_and_subtitle_become_named_block(self):
        doc = {
            "body": {
                "content": [
                    _para("My Doc\n", para_style={"namedStyleType": "TITLE"}),
                    _para("A subtitle\n", para_style={"namedStyleType": "SUBTITLE"}),
                ]
            }
        }
        nodes = document_to_ast(doc)
        assert isinstance(nodes[0], NamedBlock) and nodes[0].style_type == "TITLE"
        assert isinstance(nodes[1], NamedBlock) and nodes[1].style_type == "SUBTITLE"

    def test_text_style_fields_map_onto_run(self):
        style = {
            "bold": True,
            "italic": True,
            "strikethrough": True,
            "link": {"url": "https://example.com"},
            "weightedFontFamily": {"fontFamily": "Courier New"},
            "foregroundColor": {"color": {"rgbColor": {"red": 1.0}}},
        }
        doc = {"body": {"content": [_para("styled\n", style=style)]}}
        run = document_to_ast(doc)[0].runs[0]
        assert run.bold and run.italic and run.strikethrough
        assert run.link_url == "https://example.com"
        assert run.font_family == "Courier New"
        assert run.foreground_color.red == 1.0
        assert run.foreground_color.green == 0.0

    def test_courier_new_run_converts_soft_break_to_newline(self):
        # #719: emitter.py writes a multi-line fenced code block's internal
        # line breaks as "\v" (soft break) rather than "\n", so the whole
        # block stays one Docs paragraph instead of fragmenting into one
        # paragraph per line. This is the read-side reversal.
        style = {"weightedFontFamily": {"fontFamily": "Courier New"}}
        doc = {"body": {"content": [_para("line1\vline2\vline3\n", style=style)]}}
        run = document_to_ast(doc)[0].runs[0]
        assert run.text == "line1\nline2\nline3"

    def test_non_code_run_converts_soft_break_to_newline(self):
        # #1057: a soft break in prose (insert_softbreak_paragraph) is a line
        # break too, not a raw "\v" in the exported text.
        doc = {"body": {"content": [_para("line1\vline2\v\n")]}}
        run = document_to_ast(doc)[0].runs[0]
        assert run.text == "line1\nline2\n"


class TestDocToAstBullets:
    def test_ordered_detected_from_glyph_type(self):
        doc = {
            "body": {"content": [_para("one\n", bullet={"listId": "l1", "nestingLevel": 0})]},
            "lists": {"l1": {"listProperties": {"nestingLevels": [{"glyphType": "DECIMAL"}]}}},
        }
        node = document_to_ast(doc)[0]
        assert isinstance(node, BulletItem)
        assert node.ordered is True

    def test_unordered_detected_from_glyph_symbol(self):
        doc = {
            "body": {"content": [_para("one\n", bullet={"listId": "l1", "nestingLevel": 0})]},
            "lists": {"l1": {"listProperties": {"nestingLevels": [{"glyphSymbol": "●"}]}}},
        }
        node = document_to_ast(doc)[0]
        assert node.ordered is False

    def test_nesting_level_maps_to_depth(self):
        doc = {
            "body": {"content": [_para("deep\n", bullet={"listId": "l1", "nestingLevel": 2})]},
            "lists": {"l1": {"listProperties": {"nestingLevels": [{}, {}, {"glyphSymbol": "●"}]}}},
        }
        node = document_to_ast(doc)[0]
        assert node.depth == 2

    def test_checked_glyph_prefix_sets_checked_and_is_stripped(self):
        doc = {
            "body": {"content": [_para("☑ Done\n", bullet={"listId": "l1", "nestingLevel": 0})]},
            "lists": {"l1": {"listProperties": {"nestingLevels": [{"glyphSymbol": "●"}]}}},
        }
        node = document_to_ast(doc)[0]
        assert node.checked is True
        assert node.runs[0].text == "Done"

    def test_unchecked_glyph_prefix_sets_checked_false(self):
        doc = {
            "body": {"content": [_para("☐ Todo\n", bullet={"listId": "l1", "nestingLevel": 0})]},
            "lists": {"l1": {"listProperties": {"nestingLevels": [{"glyphSymbol": "●"}]}}},
        }
        node = document_to_ast(doc)[0]
        assert node.checked is False
        assert node.runs[0].text == "Todo"

    def test_no_checkbox_prefix_leaves_checked_none(self):
        doc = {
            "body": {"content": [_para("plain\n", bullet={"listId": "l1", "nestingLevel": 0})]},
            "lists": {"l1": {"listProperties": {"nestingLevels": [{"glyphSymbol": "●"}]}}},
        }
        node = document_to_ast(doc)[0]
        assert node.checked is None


class TestDocToAstBlockquote:
    def test_indent_and_border_left_infer_depth_one(self):
        doc = {
            "body": {
                "content": [
                    _para(
                        "quoted\n",
                        para_style={"indentStart": {"magnitude": 36}, "borderLeft": {"color": {}}},
                    )
                ]
            }
        }
        node = document_to_ast(doc)[0]
        assert node.blockquote_depth == 1

    def test_indent_without_border_left_is_not_a_blockquote(self):
        doc = {
            "body": {
                "content": [_para("indented\n", para_style={"indentStart": {"magnitude": 36}})]
            }
        }
        node = document_to_ast(doc)[0]
        assert node.blockquote_depth == 0

    def test_deeper_indent_infers_higher_depth(self):
        doc = {
            "body": {
                "content": [
                    _para(
                        "double quoted\n",
                        para_style={"indentStart": {"magnitude": 72}, "borderLeft": {"color": {}}},
                    )
                ]
            }
        }
        node = document_to_ast(doc)[0]
        assert node.blockquote_depth == 2

    def _quoted_bullet_doc(self, indent_start, level=0, level_indent=None):
        nesting = [{"glyphSymbol": "●"} for _ in range(level + 1)]
        if level_indent is not None:
            nesting[level]["indentStart"] = {"magnitude": level_indent}
        return {
            "body": {
                "content": [
                    _para(
                        "item\n",
                        bullet={"listId": "l1", "nestingLevel": level},
                        para_style={
                            "indentStart": {"magnitude": indent_start},
                            "borderLeft": {"color": {}},
                        },
                    )
                ]
            },
            "lists": {"l1": {"listProperties": {"nestingLevels": nesting}}},
        }

    def test_quoted_bullet_depth_excludes_list_level_indent(self):
        """#1056: a quoted list item's indentStart is its list level's own plus the
        quote's, so the level's share isn't quote depth."""
        doc = self._quoted_bullet_doc(108, level=1, level_indent=72)
        node = document_to_ast(doc)[0]
        assert node.depth == 1
        assert node.blockquote_depth == 1

    def test_quoted_bullet_level_indent_falls_back_to_preset(self):
        doc = self._quoted_bullet_doc(144)
        assert document_to_ast(doc)[0].blockquote_depth == 3

    def test_pre_1056_quoted_bullet_still_reads_as_quoted(self):
        """Written before #1056, the bullets call left the level's own indent only."""
        doc = self._quoted_bullet_doc(36, level_indent=36)
        assert document_to_ast(doc)[0].blockquote_depth == 1


class TestDocToAstLinks:
    """PR #976 QA round 1: Docs reports a same-document link by ID, with no
    url (live shape: `{"headingId": "h.x"}`), on text runs and images alike."""

    _BASE = "https://docs.google.com/document/d/DOC/edit"

    def _doc(self, link):
        return {
            "documentId": "DOC",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "jump", "textStyle": {"link": link}}},
                                {
                                    "inlineObjectElement": {
                                        "inlineObjectId": "img1",
                                        "textStyle": {"link": link},
                                    }
                                },
                                {"textRun": {"content": "\n", "textStyle": {}}},
                            ]
                        }
                    }
                ]
            },
            "inlineObjects": {
                "img1": {
                    "inlineObjectProperties": {
                        "embeddedObject": {"imageProperties": {"contentUri": "https://i/p.png"}}
                    }
                }
            },
        }

    @pytest.mark.parametrize(
        "link, expected",
        [
            ({"url": "https://example.com"}, "https://example.com"),
            ({"headingId": "h.abc"}, f"{_BASE}?tab=t.0#heading=h.abc"),
            ({"heading": {"id": "h.abc", "tabId": "t.7"}}, f"{_BASE}?tab=t.7#heading=h.abc"),
            ({"bookmarkId": "id.xyz"}, f"{_BASE}?tab=t.0#bookmark=id.xyz"),
            ({"bookmark": {"id": "id.xyz", "tabId": "t.2"}}, f"{_BASE}?tab=t.2#bookmark=id.xyz"),
            ({"headingId": "h.abc", "tabId": "t.3"}, f"{_BASE}?tab=t.3#heading=h.abc"),
        ],
    )
    def test_link_url_on_run_and_image(self, link, expected):
        run, image = document_to_ast(self._doc(link))[0].runs
        assert run.link_url == expected
        assert isinstance(image, Image)
        assert image.link_url == expected

    def test_internal_link_without_document_id_is_dropped(self):
        doc = self._doc({"headingId": "h.abc"})
        del doc["documentId"]
        run, image = document_to_ast(doc)[0].runs
        assert run.link_url is None
        assert image.link_url is None

    def test_heading_link_exports_as_markdown_link(self):
        md = ast_to_markdown(document_to_ast(self._doc({"headingId": "h.abc"})))
        url = f"{self._BASE}?tab=t.0#heading=h.abc"
        assert md == f"[jump]({url})[![](https://i/p.png)]({url})\n"


class TestDocToAstImages:
    def test_inline_object_resolves_to_image(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"inlineObjectElement": {"inlineObjectId": "img1"}},
                                {"textRun": {"content": "\n", "textStyle": {}}},
                            ]
                        }
                    }
                ]
            },
            "inlineObjects": {
                "img1": {
                    "inlineObjectProperties": {
                        "embeddedObject": {
                            "title": "A photo",
                            "imageProperties": {"contentUri": "https://example.com/img.png"},
                            "size": {
                                "width": {"magnitude": 100.0},
                                "height": {"magnitude": 50.0},
                            },
                        }
                    }
                }
            },
        }
        node = document_to_ast(doc)[0]
        image = node.runs[0]
        assert isinstance(image, Image)
        assert image.src == "https://example.com/img.png"
        assert image.alt == "A photo"
        assert image.width == 100.0
        assert image.link_url is None

    def test_linked_inline_object_carries_link_url(self):
        # #951: shape confirmed live, the link sits on the element's own textStyle.
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {
                                    "inlineObjectElement": {
                                        "inlineObjectId": "img1",
                                        "textStyle": {"link": {"url": "https://x.com/t"}},
                                    }
                                },
                                {"textRun": {"content": "\n", "textStyle": {}}},
                            ]
                        }
                    }
                ]
            },
            "inlineObjects": {
                "img1": {
                    "inlineObjectProperties": {
                        "embeddedObject": {
                            "imageProperties": {"contentUri": "https://example.com/img.png"},
                        }
                    }
                }
            },
        }
        image = document_to_ast(doc)[0].runs[0]
        assert isinstance(image, Image)
        assert image.link_url == "https://x.com/t"
        assert ast_to_markdown(document_to_ast(doc)) == (
            "[![](https://example.com/img.png)](https://x.com/t)\n"
        )

    def test_inline_object_with_no_content_uri_is_dropped(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"inlineObjectElement": {"inlineObjectId": "img1"}},
                                {"textRun": {"content": "\n", "textStyle": {}}},
                            ]
                        }
                    }
                ]
            },
            "inlineObjects": {
                "img1": {"inlineObjectProperties": {"embeddedObject": {"imageProperties": {}}}}
            },
        }
        node = document_to_ast(doc)[0]
        assert node.runs == []


class TestDocToAstTables:
    def test_simple_table_round_trips_rows_and_cells(self):
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"tableCellStyle": {}, "content": [_para("a\n")]},
                                        {"tableCellStyle": {}, "content": [_para("b\n")]},
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        assert isinstance(table, Table)
        assert len(table.rows) == 1
        assert len(table.rows[0].cells) == 2
        assert table.rows[0].cells[0].children[0].text == "a"
        assert table.rows[0].cells[1].children[0].text == "b"

    def test_colspan_and_rowspan_read_from_cell_style(self):
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {"columnSpan": 2, "rowSpan": 3},
                                            "content": [_para("merged\n")],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        cell = table.rows[0].cells[0]
        assert cell.colspan == 2
        assert cell.rowspan == 3

    def test_colspan_phantom_cell_in_same_row_is_skipped_not_treated_as_real(self):
        # Google's Docs API leaves a real (empty) physical tableCells[] entry
        # for the position a colspan absorbs — confirmed live (#591 QA round
        # 1): a colspan=2 header row actually has TWO physical cell entries,
        # not one. Treating the phantom as a real cell produced an extra
        # blank column.
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {"columnSpan": 2},
                                            "content": [_para("Merged\n")],
                                        },
                                        {
                                            "tableCellStyle": {"columnSpan": 1},
                                            "content": [_para("\n")],
                                        },
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"tableCellStyle": {}, "content": [_para("a\n")]},
                                        {"tableCellStyle": {}, "content": [_para("b\n")]},
                                    ]
                                },
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        assert len(table.rows[0].cells) == 1
        assert table.rows[0].cells[0].colspan == 2
        assert table.rows[0].cells[0].children[0].text == "Merged"
        assert len(table.rows[1].cells) == 2

    def test_rowspan_phantom_cell_in_later_row_is_skipped_and_sibling_survives(self):
        # The rowspan mirror of the colspan case above: the row a rowspan
        # reaches into has its own empty phantom physical cell at the covered
        # position — confirmed live to otherwise silently drop that row's own
        # real trailing cell (e.g. "b2" in a 2-column table).
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {"rowSpan": 2},
                                            "content": [_para("Tall\n")],
                                        },
                                        {"tableCellStyle": {}, "content": [_para("b1\n")]},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"tableCellStyle": {}, "content": [_para("\n")]},
                                        {"tableCellStyle": {}, "content": [_para("b2\n")]},
                                    ]
                                },
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        assert len(table.rows[0].cells) == 2
        assert table.rows[0].cells[0].rowspan == 2
        # The phantom is consumed silently; only the real trailing cell survives.
        assert len(table.rows[1].cells) == 1
        assert table.rows[1].cells[0].children[0].text == "b2"

    def test_nested_table_is_a_table_child_in_cell_children(self):
        inner_table_elem = {
            "table": {
                "tableRows": [
                    {"tableCells": [{"tableCellStyle": {}, "content": [_para("inner\n")]}]}
                ]
            }
        }
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {},
                                            "content": [_para("outer\n"), inner_table_elem],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        outer = document_to_ast(doc)[0]
        children = outer.rows[0].cells[0].children
        assert isinstance(children[0], Run) and children[0].text == "outer"
        assert isinstance(children[1], Table)

    def test_multiple_paragraphs_in_a_cell_are_newline_joined(self):
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {},
                                            "content": [_para("line1\n"), _para("line2\n")],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        text = "".join(r.text for r in table.rows[0].cells[0].children)
        assert text == "line1\nline2"

    def test_blank_spacer_paragraph_in_a_cell_is_preserved_not_dropped(self):
        # A blank spacer paragraph between two lines of real text (#594) used
        # to be `continue`d past entirely in _cell_content_to_children,
        # silently collapsing "Line 1", blank, "Line 2" into a single
        # "\n"-joined "Line 1\nLine 2" — indistinguishable from a cell with no
        # spacer at all. The spacer must still show up as a second newline.
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {},
                                            "content": [
                                                _para("Line 1\n"),
                                                _para("\n"),
                                                _para("Line 2\n"),
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        text = "".join(r.text for r in table.rows[0].cells[0].children)
        assert text == "Line 1\n\nLine 2"

    def test_trailing_spacer_paragraph_in_a_cell_leaves_a_trailing_newline(self):
        # QA round 2 (#594): a spacer at the very end of a cell — as opposed
        # to one sandwiched between two real lines (the case above) — is a
        # distinct shape doc_to_ast.py must also represent correctly, since
        # the bug that reached this far (ast_to_markdown.py's _render_cell
        # stripping it away) is downstream of this function producing the
        # right AST in the first place.
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {},
                                            "content": [_para("Trailing test\n"), _para("\n")],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        text = "".join(r.text for r in table.rows[0].cells[0].children)
        assert text == "Trailing test\n"

    def test_leading_spacer_paragraph_in_a_cell_leaves_a_leading_newline(self):
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "tableCellStyle": {},
                                            "content": [_para("\n"), _para("Leading test\n")],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        table = document_to_ast(doc)[0]
        text = "".join(r.text for r in table.rows[0].cells[0].children)
        assert text == "\nLeading test"


class TestAstToMarkdownInline:
    def test_bold_and_link_render_correctly(self):
        nodes = [Paragraph(runs=[Run(text="hello", bold=True, link_url="https://x.com")])]
        assert ast_to_markdown(nodes) == "[**hello**](https://x.com)\n"

    def test_trailing_whitespace_in_bold_run_does_not_break_commonmark(self):
        # "**Bold **" would fail to close per CommonMark's flanking rules —
        # the trailing space must land outside the delimiters.
        nodes = [
            Paragraph(
                runs=[
                    Run(text="Bold ", bold=True),
                    Run(text="and "),
                    Run(text="link", link_url="https://example.com"),
                ]
            )
        ]
        md = ast_to_markdown(nodes)
        assert md == "**Bold** and [link](https://example.com)\n"

    def test_paragraph_entirely_code_styled_renders_as_fenced_block(self):
        nodes = [Paragraph(runs=[Run(text="x = 1", font_family="Courier New")])]
        assert ast_to_markdown(nodes) == "```\nx = 1\n```\n"

    def test_multiline_code_paragraph_renders_as_one_fenced_block(self):
        # #719: a multi-line fenced code block round-trips as one Paragraph
        # node (its internal line breaks already restored to "\n" by
        # doc_to_ast.py's _text_run_to_run) and must render as a single
        # fence, not one fence per line.
        nodes = [Paragraph(runs=[Run(text="line1\nline2\nline3", font_family="Courier New")])]
        assert ast_to_markdown(nodes) == "```\nline1\nline2\nline3\n```\n"

    def test_image_mixed_into_code_styled_paragraph_is_not_dropped(self):
        # An Image sitting alongside Courier-New-styled Runs in the same
        # paragraph used to vanish entirely (#594) — `_is_code_block` filtered
        # to Run-only children before checking font_family, so the paragraph
        # was still correctly classified as a code block, but the fenced-block
        # render path then built its text from Run items only, dropping the
        # Image with no trace it was ever there.
        nodes = [
            Paragraph(
                runs=[
                    Image(src="https://x.com/i.png", alt="pic"),
                    Run(text="x = 1", font_family="Courier New"),
                ]
            )
        ]
        assert ast_to_markdown(nodes) == "![pic](https://x.com/i.png)\n\n```\nx = 1\n```\n"

    def test_code_run_mixed_with_plain_text_stays_inline_backtick_span(self):
        nodes = [
            Paragraph(
                runs=[Run(text="see "), Run(text="x", font_family="Courier New"), Run(text=" here")]
            )
        ]
        assert ast_to_markdown(nodes) == "see `x` here\n"

    def test_special_markdown_characters_are_escaped(self):
        nodes = [Paragraph(runs=[Run(text="a*b_c[d]")])]
        assert ast_to_markdown(nodes) == "a\\*b\\_c\\[d\\]\n"

    def test_image_renders_as_markdown_image_syntax(self):
        nodes = [Paragraph(runs=[Image(src="https://x.com/i.png", alt="pic")])]
        assert ast_to_markdown(nodes) == "![pic](https://x.com/i.png)\n"

    def test_link_url_with_unbalanced_parens_is_angle_bracket_wrapped(self):
        # A bare "(...)" link destination requires balanced parens per
        # CommonMark — "Foo_(bar)" has an unmatched ")" that would otherwise
        # terminate the destination early (#591 QA round 1, live-confirmed).
        url = "https://en.wikipedia.org/wiki/Foo_(bar)"
        nodes = [Paragraph(runs=[Run(text="link", link_url=url)])]
        assert ast_to_markdown(nodes) == f"[link](<{url}>)\n"

    def test_link_url_without_special_chars_is_not_wrapped(self):
        nodes = [Paragraph(runs=[Run(text="link", link_url="https://example.com/plain")])]
        assert ast_to_markdown(nodes) == "[link](https://example.com/plain)\n"

    def test_code_run_link_url_also_gets_escaped(self):
        # Mixed with plain text so the paragraph isn't entirely code-styled
        # (which would instead render as a fenced block — see
        # TestAstToMarkdownInline.test_paragraph_entirely_code_styled_renders_as_fenced_block).
        url = "https://x.com/(code)"
        nodes = [
            Paragraph(
                runs=[Run(text="see "), Run(text="x", font_family="Courier New", link_url=url)]
            )
        ]
        assert ast_to_markdown(nodes) == f"see [`x`](<{url}>)\n"

    def test_image_src_with_unbalanced_parens_is_angle_bracket_wrapped(self):
        url = "https://x.com/i(1).png"
        nodes = [Paragraph(runs=[Image(src=url, alt="pic")])]
        assert ast_to_markdown(nodes) == f"![pic](<{url}>)\n"


def _links(markdown_text):
    """Every (href, child token types) pair CommonMark parses out of `markdown_text`."""
    found = []
    for block in _COMMONMARK.parse(markdown_text):
        children = block.children or []
        for i, tok in enumerate(children):
            if tok.type == "link_open":
                inner = []
                for t in children[i + 1 :]:
                    if t.type == "link_close":
                        break
                    inner.append(t.type)
                found.append((tok.attrs["href"], inner))
    return found


class TestCodeBlockLinks:
    """#951: a fenced block's content is literal, so a link inside one was lost."""

    def test_linked_code_only_paragraph_keeps_link_as_inline_code(self):
        nodes = [Paragraph(runs=[_code("pkg", link_url="https://pypi.org/p/pkg")])]
        md = ast_to_markdown(nodes)
        assert md == "[`pkg`](https://pypi.org/p/pkg)\n"
        assert _links(md) == [("https://pypi.org/p/pkg", ["code_inline"])]

    def test_partly_linked_code_paragraph_keeps_every_run(self):
        nodes = [
            Paragraph(
                runs=[
                    _code("pip install "),
                    _code("pkg", link_url="https://pypi.org/p/pkg"),
                ]
            )
        ]
        md = ast_to_markdown(nodes)
        assert md == "`pip install `[`pkg`](https://pypi.org/p/pkg)\n"
        assert not any(t.type == "fence" for t in _COMMONMARK.parse(md))
        assert _links(md) == [("https://pypi.org/p/pkg", ["code_inline"])]

    def test_multiline_linked_code_paragraph_stays_one_paragraph(self):
        # Each line becomes its own span joined by <br>; a raw newline could
        # start a new block ("# x" as a heading).
        nodes = [Paragraph(runs=[_code("a\n# b", link_url="https://x.com")])]
        md = ast_to_markdown(nodes)
        assert md == "[`a`<br>`# b`](https://x.com)\n"
        tokens = _COMMONMARK.parse(md)
        assert [t.type for t in tokens] == ["paragraph_open", "inline", "paragraph_close"]

    def test_link_on_only_a_line_break_keeps_the_fence(self):
        # PR #976 QA round 1: a link covering just the soft break renders as
        # bare <br> with no link, so it must not cost the paragraph its fence.
        nodes = [Paragraph(runs=[_code("a"), _code("\n", link_url="https://x.com"), _code("b")])]
        assert ast_to_markdown(nodes) == "```\na\nb\n```\n"

    def test_unlinked_code_paragraph_still_fenced(self):
        nodes = [Paragraph(runs=[_code("x = 1")])]
        assert ast_to_markdown(nodes) == "```\nx = 1\n```\n"

    def test_linked_image_in_code_paragraph_keeps_link_and_fence(self):
        nodes = [
            Paragraph(
                runs=[
                    _code("x = 1"),
                    Image(src="https://x.com/i.png", alt="pic", link_url="https://x.com/target"),
                ]
            )
        ]
        md = ast_to_markdown(nodes)
        assert md == "```\nx = 1\n```\n\n[![pic](https://x.com/i.png)](https://x.com/target)\n"
        assert _links(md) == [("https://x.com/target", ["image"])]

    def test_linked_image_in_plain_paragraph_keeps_link(self):
        url = "https://x.com/Foo_(bar)"
        nodes = [Paragraph(runs=[Image(src="https://x.com/i.png", alt="pic", link_url=url)])]
        md = ast_to_markdown(nodes)
        assert md == f"[![pic](https://x.com/i.png)](<{url}>)\n"
        assert _links(md) == [(url, ["image"])]

    def test_linked_image_in_table_cell_keeps_link(self):
        nodes = [
            Table(
                rows=[
                    Row(
                        cells=[
                            Cell(
                                children=[
                                    Image(
                                        src="https://x.com/i.png",
                                        alt="pic",
                                        link_url="https://x.com/t",
                                    )
                                ]
                            )
                        ]
                    )
                ]
            )
        ]
        md = ast_to_markdown(nodes)
        assert "[![pic](https://x.com/i.png)](https://x.com/t)" in md
        assert _links(md) == [("https://x.com/t", ["image"])]

    def test_blockquoted_linked_code_paragraph(self):
        nodes = [Paragraph(runs=[_code("pkg", link_url="https://x.com")], blockquote_depth=1)]
        assert ast_to_markdown(nodes) == "> [`pkg`](https://x.com)\n"


class TestAstToMarkdownBlocks:
    def test_heading_level_renders_hashes(self):
        nodes = [Heading(level=3, runs=[Run(text="Sub")])]
        assert ast_to_markdown(nodes) == "### Sub\n"

    def test_title_and_subtitle_map_to_h1_h2(self):
        nodes = [
            NamedBlock(style_type="TITLE", runs=[Run(text="T")]),
            NamedBlock(style_type="SUBTITLE", runs=[Run(text="S")]),
        ]
        assert ast_to_markdown(nodes) == "# T\n\n## S\n"

    def test_bullet_item_unordered(self):
        nodes = [BulletItem(runs=[Run(text="item")], depth=0, ordered=False)]
        assert ast_to_markdown(nodes) == "- item\n"

    def test_bullet_item_nested_indents_by_depth(self):
        nodes = [BulletItem(runs=[Run(text="item")], depth=2, ordered=False)]
        assert ast_to_markdown(nodes) == "    - item\n"

    def test_bullet_item_ordered_uses_numeral_marker(self):
        nodes = [BulletItem(runs=[Run(text="item")], depth=0, ordered=True)]
        assert ast_to_markdown(nodes) == "1. item\n"

    def test_checked_task_item(self):
        nodes = [BulletItem(runs=[Run(text="done")], depth=0, ordered=False, checked=True)]
        assert ast_to_markdown(nodes) == "- [x] done\n"

    def test_unchecked_task_item(self):
        nodes = [BulletItem(runs=[Run(text="todo")], depth=0, ordered=False, checked=False)]
        assert ast_to_markdown(nodes) == "- [ ] todo\n"

    def test_blockquote_depth_prefixes_each_line(self):
        nodes = [Paragraph(runs=[Run(text="quoted")], blockquote_depth=2)]
        assert ast_to_markdown(nodes) == "> > quoted\n"

    def test_paragraph_starting_with_ordered_marker_is_escaped(self):
        # Live-confirmed (#591 QA round 1): unescaped, this reparses as a
        # real ordered-list item under any CommonMark parser.
        nodes = [Paragraph(runs=[Run(text="1. Not actually a list item")])]
        assert ast_to_markdown(nodes) == "1\\. Not actually a list item\n"

    def test_paragraph_starting_with_hash_is_escaped(self):
        nodes = [Paragraph(runs=[Run(text="# Not a heading either")])]
        assert ast_to_markdown(nodes) == "\\# Not a heading either\n"

    def test_paragraph_starting_with_blockquote_marker_is_escaped(self):
        nodes = [Paragraph(runs=[Run(text="> not a quote")])]
        assert ast_to_markdown(nodes) == "\\> not a quote\n"

    def test_paragraph_starting_with_bullet_marker_is_escaped(self):
        nodes = [Paragraph(runs=[Run(text="- not a bullet")])]
        assert ast_to_markdown(nodes) == "\\- not a bullet\n"

    @pytest.mark.parametrize(
        "text",
        [
            " - a",
            "  - a",
            "   - a",
            "  # h",
            "## h",
            "###### h",
            "  ### h",
            "   > q",
            " 1. x",
            "---",
            "- - -",
            "--",
            "===",
            "===  ",
            "* * *",
            "___",
            "    four-space indent",
            "\ttab indent",
        ],
    )
    def test_paragraph_never_renders_as_another_block(self, text):
        # Leading spaces before a marker, rule lines, and 4+ space or tab
        # indents (an indented code block) all stay a plain paragraph (#993).
        html = _COMMONMARK.render(ast_to_markdown([Paragraph(runs=[Run(text=text)])]))
        assert html == f"<p>{escape(text.strip(), quote=False)}</p>\n"

    def test_paragraph_starting_with_digit_but_no_marker_punctuation_is_untouched(self):
        # "123 apples" isn't an ordered-list marker (no "." or ")" after the
        # digits) — must not be escaped.
        nodes = [Paragraph(runs=[Run(text="123 apples")])]
        assert ast_to_markdown(nodes) == "123 apples\n"

    def test_heading_starting_with_hash_text_is_not_double_escaped(self):
        # A real Heading node's own "# " prefix is legitimate — the escape
        # only applies to plain Paragraph rendering, not Heading/BulletItem/
        # NamedBlock, which already have their own distinguishing prefix.
        nodes = [Heading(level=1, runs=[Run(text="# looks like a heading")])]
        assert ast_to_markdown(nodes) == "# # looks like a heading\n"

    def test_leading_marker_inside_blockquote_is_still_escaped(self):
        # A "> #" line is parsed as a heading *inside* the blockquote by
        # CommonMark — the escape must happen before the "> " prefix is
        # applied, not after.
        nodes = [Paragraph(runs=[Run(text="# fake heading")], blockquote_depth=1)]
        assert ast_to_markdown(nodes) == "> \\# fake heading\n"

    def test_consecutive_bullet_items_form_a_tight_list_no_blank_line(self):
        nodes = [
            BulletItem(runs=[Run(text="one")], depth=0),
            BulletItem(runs=[Run(text="two")], depth=1),
            BulletItem(runs=[Run(text="three")], depth=0),
        ]
        assert ast_to_markdown(nodes) == "- one\n  - two\n- three\n"

    def test_bullet_list_still_blank_line_separated_from_surrounding_paragraphs(self):
        nodes = [
            Paragraph(runs=[Run(text="before")]),
            BulletItem(runs=[Run(text="item")], depth=0),
            Paragraph(runs=[Run(text="after")]),
        ]
        assert ast_to_markdown(nodes) == "before\n\n- item\n\nafter\n"


class TestAstToMarkdownTables:
    def _table(self, rows):
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        return Table(rows=[Row(cells=[Cell(children=[Run(text=t)]) for t in row]) for row in rows])

    def test_first_row_renders_as_header(self):
        table = self._table([["H1", "H2"], ["a", "b"]])
        md = ast_to_markdown([table])
        assert md.splitlines()[:3] == ["| H1 | H2 |", "| --- | --- |", "| a | b |"]

    def test_colspan_leaves_blank_trailing_cell(self):
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        table = Table(rows=[Row(cells=[Cell(children=[Run(text="merged")], colspan=2)])])
        md = ast_to_markdown([table])
        assert md.splitlines()[0] == "| merged |  |"

    def test_pipe_character_in_cell_is_escaped(self):
        table = self._table([["a|b"]])
        assert "a\\|b" in ast_to_markdown([table])

    def test_multiline_cell_with_blank_spacer_renders_as_double_br(self):
        # Mirrors test_blank_spacer_paragraph_in_a_cell_is_preserved_not_dropped
        # one layer up, at the actual Markdown-rendering level: the cell's
        # internal "\n\n" (real line, spacer, real line) must survive
        # _render_cell's newline->"<br>" conversion as two consecutive <br>
        # tags, not collapse into a single one indistinguishable from a cell
        # with no spacer at all.
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        table = Table(rows=[Row(cells=[Cell(children=[Run(text="Line 1\n\nLine 2")])])])
        md = ast_to_markdown([table])
        assert "Line 1<br><br>Line 2" in md

    def test_trailing_spacer_in_a_cell_renders_a_trailing_br(self):
        # #594 QA round 2: _render_cell's `.strip()` used to run BEFORE the
        # "\n" -> "<br>" conversion, silently eating a spacer newline sitting
        # at the very edge of the cell's text — indistinguishable from a
        # cell with no spacer at all. Only the mid-cell case (the test above)
        # was covered by round 1's own new tests, which is exactly why this
        # slipped through code review and unit tests and only surfaced in
        # live QA. strip() must now run AFTER the <br> conversion.
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        table = Table(rows=[Row(cells=[Cell(children=[Run(text="Trailing test\n")])])])
        md = ast_to_markdown([table])
        assert "Trailing test<br>" in md
        assert "Trailing test |" not in md

    def test_leading_spacer_in_a_cell_renders_a_leading_br(self):
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        table = Table(rows=[Row(cells=[Cell(children=[Run(text="\nLeading test")])])])
        md = ast_to_markdown([table])
        assert "<br>Leading test" in md
        assert "| Leading test" not in md

    def test_nested_table_in_cell_renders_placeholder(self):
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        inner = Table(rows=[Row(cells=[Cell(children=[Run(text="inner")])])])
        outer = Table(rows=[Row(cells=[Cell(children=[inner])])])
        md = ast_to_markdown([outer])
        assert "nested table omitted" in md


class TestAstToMarkdownComments:
    def test_comments_section_appended_with_author_and_quote(self):
        nodes = [Paragraph(runs=[Run(text="body")])]
        comments = [
            {
                "author": {"display_name": "Alice"},
                "quoted_text": "the sentence",
                "content": "please fix",
                "replies": [{"author": {"display_name": "Bob"}, "content": "done"}],
            }
        ]
        md = ast_to_markdown(nodes, comments=comments)
        assert "## Comments" in md
        assert "**Alice**" in md
        assert "> the sentence" in md
        assert "please fix" in md
        assert "**Bob**: done" in md

    def _quote_md(self, quoted_text):
        comments = [{"author": {"display_name": "A"}, "quoted_text": quoted_text, "content": "fix"}]
        md = ast_to_markdown([Paragraph(runs=[Run(text="body")])], comments=comments)
        return md.split("## Comments\n\n", 1)[1]

    def test_quote_keeps_plain_text_and_escapes_only_markdown_syntax(self):
        # "&" before a non-entity and "<" before a space stay as-is; "*" and
        # a "<" that could open a tag are escaped (#984).
        section = self._quote_md('Café & Tom, a < b, <x> "hi" *two*')
        assert section == '**A**\n> Café & Tom, a < b, \\<x> "hi" \\*two\\*\n\nfix\n'

    def test_multiline_quote_prefixes_every_line_and_escapes_block_markers(self):
        section = self._quote_md("one\n\n# head\n- item\n1. num")
        assert section == "**A**\n> one\n>\n> \\# head\\\n> \\- item\\\n> 1\\. num\n\nfix\n"

    def test_quote_is_closed_before_the_comment_text(self):
        # Without the blank line, "fix" would be a lazy continuation of the quote.
        assert "> the sentence\n\nfix" in self._quote_md("the sentence")

    def test_author_content_and_replies_are_escaped_as_plain_text(self):
        comments = [
            {
                "author": {"display_name": "A_b*"},
                "content": "use <b> and *x*\n# not a heading",
                "replies": [{"author": {"display_name": "C"}, "content": "ok *y*\n- not an item"}],
            }
        ]
        md = ast_to_markdown([Paragraph(runs=[Run(text="body")])], comments=comments)
        section = md.split("## Comments\n\n", 1)[1]
        assert section == (
            "**A\\_b\\***\\\n"
            "use \\<b> and \\*x\\*\\\n"
            "\\# not a heading\n"
            "  - **C**: ok \\*y\\*\\\n"
            "    \\- not an item\n"
        )

    def _render(self, content=None, quoted_text=None, reply=None):
        comment = {"author": {"display_name": "A"}, "content": content or "c", "replies": []}
        if quoted_text is not None:
            comment["quoted_text"] = quoted_text
        if reply is not None:
            comment["replies"].append({"author": {"display_name": "B"}, "content": reply})
        md = ast_to_markdown([Paragraph(runs=[Run(text="body")])], comments=[comment])
        return _COMMONMARK.render(md.split("## Comments\n\n", 1)[1])

    @pytest.mark.parametrize(
        "content, lines",
        [
            # setext underline / thematic break (PR #991 QA round 1)
            ("Summary\n---\nmore", ["Summary", "---", "more"]),
            ("Title\n===\n--", ["Title", "===", "--"]),
            # multi-"#" ATX headings (PR #991 QA round 2)
            ("Probe heading\n## Notes\n###### six", ["Probe heading", "## Notes", "###### six"]),
            # leading spaces before a marker
            ("Points:\n - a\n   - b\n  # c", ["Points:", "- a", "- b", "# c"]),
            # GFM table
            ("a | b\n-|-\nc | d", ["a | b", "-|-", "c | d"]),
            # every line keeps its own line, not one soft-wrapped line
            ("step 1\nstep 2\nstep 3", ["step 1", "step 2", "step 3"]),
            # a literal trailing backslash stays literal before the hard break
            ("path C:\\\nnext", ["path C:\\", "next"]),
        ],
    )
    def test_content_lines_render_as_plain_text_lines(self, content, lines):
        html = self._render(content=content)
        assert html == "<p><strong>A</strong><br />\n" + "<br />\n".join(lines) + "</p>\n"

    def test_indented_content_after_blank_line_is_not_a_code_block(self):
        html = self._render(content="intro\n\n    indented *x*")
        assert "<pre>" not in html
        assert "<p>indented *x*</p>" in html

    def test_quote_ending_in_equals_with_trailing_spaces_is_not_a_setext_heading(self):
        # Drive keeps trailing whitespace in quoted_text (PR #991 QA round 2, live).
        html = self._render(quoted_text="Summary\n===  ")
        assert "<h1>" not in html
        assert "<blockquote>\n<p>Summary<br />\n===</p>\n</blockquote>" in html

    def test_indented_quote_line_is_not_a_list(self):
        html = self._render(quoted_text="   - indented quote")
        assert "<blockquote>\n<p>- indented quote</p>\n</blockquote>" in html

    @pytest.mark.parametrize(
        "reply, expected",
        [
            ("r\n\n---", "<p><strong>B</strong>: r</p>\n<p>---</p>"),
            ("r\n\n        deep *x*", "<p><strong>B</strong>: r</p>\n<p>deep *x*</p>"),
            ("r\n- not an item", "<strong>B</strong>: r<br />\n- not an item"),
        ],
    )
    def test_reply_continuation_stays_plain_text_in_the_item(self, reply, expected):
        html = self._render(reply=reply)
        assert "<pre>" not in html and "<hr" not in html
        assert expected in html
        assert html.count("<li>") == 1

    def test_reply_first_line_is_not_block_escaped(self):
        # It follows "**B**: " on the same line, so "1." can't start a list.
        comments = [
            {
                "author": {"display_name": "A"},
                "content": "c",
                "replies": [{"author": {"display_name": "B"}, "content": "1. agreed"}],
            }
        ]
        md = ast_to_markdown([Paragraph(runs=[Run(text="body")])], comments=comments)
        assert "  - **B**: 1. agreed\n" in md

    def test_no_comments_section_when_comments_is_none(self):
        nodes = [Paragraph(runs=[Run(text="body")])]
        assert "## Comments" not in ast_to_markdown(nodes, comments=None)


class TestGetDocAsMarkdownTool:
    def test_is_read_only(self):
        assert _docs_annotations["get_doc_as_markdown"].read_only_hint is True

    async def test_returns_markdown_for_simple_doc(self):
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "My Doc",
            "body": {"content": [_para("Hello\n", para_style={"namedStyleType": "HEADING_1"})]},
        }
        ctx = _make_ctx(docs_service=docs_service, drive_service=MagicMock())
        result = await _docs_tools["get_doc_as_markdown"](doc_id="doc1", ctx=ctx)
        assert result["doc_id"] == "doc1"
        assert result["title"] == "My Doc"
        assert result["markdown"] == "# Hello\n"

    async def test_include_comments_fetches_and_appends_open_comments_only(self):
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "My Doc",
            "body": {"content": [_para("Hello\n")]},
        }
        drive_service = MagicMock()
        drive_service.comments.return_value.list.return_value.execute.return_value = {
            "comments": [
                {
                    "id": "c1",
                    "content": "open one",
                    "author": {"displayName": "Alice"},
                    "resolved": False,
                    "deleted": False,
                    "replies": [],
                },
                {
                    "id": "c2",
                    "content": "resolved one",
                    "author": {"displayName": "Bob"},
                    "resolved": True,
                    "deleted": False,
                    "replies": [],
                },
            ]
        }
        ctx = _make_ctx(docs_service=docs_service, drive_service=drive_service)
        result = await _docs_tools["get_doc_as_markdown"](
            doc_id="doc1", include_comments=True, ctx=ctx
        )
        assert "open one" in result["markdown"]
        assert "resolved one" not in result["markdown"]

    async def test_no_comments_section_when_include_comments_false(self):
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "My Doc",
            "body": {"content": [_para("Hello\n")]},
        }
        drive_service = MagicMock()
        ctx = _make_ctx(docs_service=docs_service, drive_service=drive_service)
        result = await _docs_tools["get_doc_as_markdown"](doc_id="doc1", ctx=ctx)
        assert "## Comments" not in result["markdown"]
        drive_service.comments.assert_not_called()

    async def test_api_error_returns_error_dict(self):
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.side_effect = RuntimeError(
            "boom"
        )
        ctx = _make_ctx(docs_service=docs_service, drive_service=MagicMock())
        result = await _docs_tools["get_doc_as_markdown"](doc_id="doc1", ctx=ctx)
        assert "error" in result

    async def test_local_path_writes_to_disk_and_returns_manifest(self, tmp_path):
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "My Doc",
            "body": {"content": [_para("Hello\n")]},
        }
        ctx = _make_ctx(docs_service=docs_service, drive_service=MagicMock())
        dest = tmp_path / "out.md"
        result = await _docs_tools["get_doc_as_markdown"](
            doc_id="doc1", local_path=str(dest), ctx=ctx
        )
        assert result == {
            "local_path": str(dest),
            "bytes_written": dest.stat().st_size,
            "doc_id": "doc1",
            "title": "My Doc",
        }

    async def test_local_path_file_is_byte_identical_to_inline_markdown(self, tmp_path):
        """#958: the file holds the raw Markdown (comments included), not the JSON envelope."""
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "My Doc",
            "body": {"content": [_para('Héllo 😀 "quoted"\n'), _para("Second\n")]},
        }
        drive_service = MagicMock()
        drive_service.comments.return_value.list.return_value.execute.return_value = {
            "comments": [
                {
                    "id": "c1",
                    "content": "open one",
                    "author": {"displayName": "Alice"},
                    "resolved": False,
                    "deleted": False,
                    "replies": [],
                }
            ]
        }
        ctx = _make_ctx(docs_service=docs_service, drive_service=drive_service)
        inline = await _docs_tools["get_doc_as_markdown"](
            doc_id="doc1", include_comments=True, ctx=ctx
        )
        dest = tmp_path / "out.md"
        result = await _docs_tools["get_doc_as_markdown"](
            doc_id="doc1", include_comments=True, local_path=str(dest), ctx=ctx
        )
        assert "## Comments" in inline["markdown"]
        assert dest.read_bytes() == inline["markdown"].encode("utf-8")
        assert result["bytes_written"] == len(inline["markdown"].encode("utf-8"))

    async def test_local_path_directory_writes_doc_id_md(self, tmp_path):
        docs_service = MagicMock()
        docs_service.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "title": "My Doc",
            "body": {"content": [_para("Hello\n")]},
        }
        ctx = _make_ctx(docs_service=docs_service, drive_service=MagicMock())
        result = await _docs_tools["get_doc_as_markdown"](
            doc_id="doc1", local_path=str(tmp_path), ctx=ctx
        )
        assert result["local_path"] == str(tmp_path / "doc1.md")
        assert (tmp_path / "doc1.md").read_text(encoding="utf-8").startswith("Hello")


@pytest.mark.parametrize("text", ["call(`value`)", "`leading", "trailing`", "``nested``"])
@pytest.mark.parametrize("link_url", [None, "https://example.com/code"])
def test_inline_code_backticks_survive_markdown_rendering(text, link_url):
    nodes = [
        Paragraph(
            runs=[Run(text="see "), Run(text=text, font_family="Courier New", link_url=link_url)]
        )
    ]
    rendered = ElementTree.fromstring(markdown.markdown(ast_to_markdown(nodes)))
    code = rendered.find(".//code")
    assert code is not None
    assert code.text == text
    if link_url:
        assert rendered.find("a").attrib["href"] == link_url


def _inline_code(markdown_text):
    """Each code span's content in the first paragraph, as strict CommonMark parses it."""
    inline = next(t for t in _COMMONMARK.parse(markdown_text) if t.type == "inline")
    return [t.content for t in inline.children if t.type == "code_inline"]


class TestInlineCodeCommonMark:
    """#938: code-span edge cases checked against a strict CommonMark parser."""

    @pytest.mark.parametrize(
        "text",
        [
            "call(`value`)",
            "`leading",
            "trailing`",
            "``nested``",
            " both ends ",
            " leading only",
            "trailing only ",
            "  ",
            " `x` ",
            "  double  ",
        ],
    )
    @pytest.mark.parametrize("link_url", [None, "https://example.com/code"])
    def test_code_span_content_survives_exactly(self, text, link_url):
        nodes = [Paragraph(runs=[Run(text="see "), _code(text, link_url=link_url), Run(text=".")])]
        assert _inline_code(ast_to_markdown(nodes)) == [text]

    def test_adjacent_code_runs_merge_into_one_span(self):
        # Docs splits a run at a style change; Markdown can't show bold code.
        nodes = [Paragraph(runs=[Run(text="a "), _code("x`"), _code("`y", bold=True)])]
        assert _inline_code(ast_to_markdown(nodes)) == ["x``y"]

    def test_adjacent_code_runs_with_same_link_merge(self):
        url = "https://example.com"
        nodes = [
            Paragraph(runs=[Run(text="a "), _code("x", link_url=url), _code("y", link_url=url)])
        ]
        assert ast_to_markdown(nodes) == f"a [`xy`]({url})\n"

    def test_adjacent_code_runs_with_different_links_stay_separate(self):
        nodes = [
            Paragraph(
                runs=[
                    Run(text="a "),
                    _code("x", link_url="https://a.example"),
                    _code("y", link_url="https://b.example"),
                    _code("z"),
                ]
            )
        ]
        assert _inline_code(ast_to_markdown(nodes)) == ["x", "y", "z"]

    def test_code_run_merge_does_not_mutate_input(self):
        first, second = _code("x"), _code("y")
        ast_to_markdown([Paragraph(runs=[Run(text="a "), first, second])])
        assert (first.text, second.text) == ("x", "y")

    def test_newline_in_inline_code_does_not_start_a_new_block(self):
        nodes = [Paragraph(runs=[Run(text="a "), _code("x\n# y\n- z\n\nw"), Run(text=" b")])]
        rendered = ast_to_markdown(nodes)
        tokens = _COMMONMARK.parse(rendered)
        assert [t.type for t in tokens] == ["paragraph_open", "inline", "paragraph_close"]
        assert _inline_code(rendered) == ["x", "# y", "- z", "w"]
        assert rendered == "a `x`<br>`# y`<br>`- z`<br><br>`w` b\n"

    def test_newline_in_inline_code_inside_blockquote_stays_one_line(self):
        nodes = [Paragraph(runs=[Run(text="a "), _code("x\ny")], blockquote_depth=1)]
        assert ast_to_markdown(nodes) == "> a `x`<br>`y`\n"


class TestTableCellCodeCommonMark:
    """#938: inline code inside a GFM pipe-table cell."""

    def _render_cell(self, children):
        from mcp_gee_sweet.tools.docs.ast import Cell, Row

        table = Table(
            rows=[
                Row(cells=[Cell(children=[Run(text="h")])]),
                Row(cells=[Cell(children=children)]),
            ]
        )
        rendered = ast_to_markdown([table])
        html = _COMMONMARK.render(rendered)
        return rendered, html[html.index("<td>") + 4 : html.index("</td>")]

    def test_pipe_in_code_has_no_backslash(self):
        rendered, cell = self._render_cell([_code("a|b")])
        assert "\\" not in rendered
        assert cell == "<code>a|b</code>"

    def test_pipe_code_escapes_html_special_characters(self):
        _, cell = self._render_cell([_code("<a> & b|c")])
        assert cell == "<code>&lt;a&gt; &amp; b|c</code>"

    def test_code_without_pipe_stays_a_code_span(self):
        rendered, cell = self._render_cell([_code(" `x` ")])
        assert "| ``  `x`  `` |" in rendered
        assert cell == "<code> `x` </code>"

    def test_newline_in_code_becomes_br_outside_the_code(self):
        _, cell = self._render_cell([Run(text="t "), _code("x\ny")])
        assert cell == "t <code>x</code><br><code>y</code>"

    def test_code_paragraphs_in_one_cell_join_with_br(self):
        # doc_to_ast prefixes the second paragraph's first run with "\n".
        _, cell = self._render_cell([_code("x"), _code("\ny|z")])
        assert cell == "<code>x</code><br><code>y|z</code>"

    def test_plain_pipe_next_to_code_is_still_escaped(self):
        _, cell = self._render_cell([Run(text="a|b "), _code("c")])
        assert cell == "a|b <code>c</code>"

    def test_linked_code_with_pipe_in_url_stays_in_one_cell(self):
        rendered, cell = self._render_cell([_code("c", link_url="https://e.example/a|b")])
        assert rendered.splitlines()[2].count("|") - rendered.splitlines()[2].count("\\|") == 2
        assert cell == '<a href="https://e.example/a%7Cb"><code>c</code></a>'

    def test_pipe_code_keeps_markdown_punctuation_literal(self):
        # Text inside raw <code> is still parsed as Markdown (PR #968 QA round 1).
        text = "a|*b* _c_ [x](y) ~~d~~ `e` <i> &amp;"
        _, cell = self._render_cell([_code(text)])
        assert cell == "<code>a|*b* _c_ [x](y) ~~d~~ `e` &lt;i&gt; &amp;amp;</code>"

    def test_backslash_before_pipe_in_code_survives(self):
        _, cell = self._render_cell([_code("C:\\|x")])
        assert cell == "<code>C:\\|x</code>"

    def test_linked_code_paragraph_break_lands_outside_the_link(self):
        url = "https://e.example"
        _, cell = self._render_cell([_code("x"), _code("\nb", link_url=url)])
        assert cell == f'<code>x</code><br><a href="{url}"><code>b</code></a>'

    def test_plain_run_rendered_in_table_is_table_safe(self):
        from mcp_gee_sweet.tools.docs.ast_to_markdown import _render_run

        assert _render_run(Run(text="a|b\nc"), in_table=True) == "a\\|b<br>c"


class TestPlainTextEscapingCommonMark:
    """PR #968 QA round 1: plain text that looks like HTML, an entity, or GFM
    strikethrough must export as literal text."""

    def test_html_entity_and_tilde_render_literally(self):
        text = "Use <br> or &#124; and &amp; and ~~old~~ </p> <!-- x -->"
        rendered = ast_to_markdown([Paragraph(runs=[Run(text=text)])])
        inline = next(t for t in _COMMONMARK.parse(rendered) if t.type == "inline")
        assert [t.type for t in inline.children] == ["text"]
        assert inline.children[0].content == text

    def test_prose_ampersand_and_less_than_stay_unescaped(self):
        rendered = ast_to_markdown([Paragraph(runs=[Run(text="AT&T: a < b & c")])])
        assert rendered == "AT&T: a < b & c\n"

    def test_linked_code_trailing_soft_break_lands_outside_the_link(self):
        url = "https://e.example"
        nodes = [Paragraph(runs=[Run(text="a "), _code("x\n", link_url=url), Run(text="b")])]
        rendered = ast_to_markdown(nodes)
        assert rendered == f"a [`x`]({url})<br>b\n"
        assert _COMMONMARK.render(rendered) == (
            f'<p>a <a href="{url}"><code>x</code></a><br>b</p>\n'
        )


class TestSoftBreakCommonMark:
    """#1057: a soft break in non-code text exports as a <br> hard break, in
    every block type, never as a raw "\\v" or a newline that joins the lines."""

    def _html(self, nodes):
        rendered = ast_to_markdown(nodes)
        assert "\v" not in rendered
        return _COMMONMARK.render(rendered)

    def test_paragraph_from_live_doc_shape(self):
        doc = {"body": {"content": [_para("first\vsecond\vthird\n")]}}
        rendered = ast_to_markdown(document_to_ast(doc))
        assert rendered == "first<br>second<br>third\n"
        assert _COMMONMARK.render(rendered) == "<p>first<br>second<br>third</p>\n"

    def test_line_that_looks_like_a_block_stays_in_the_paragraph(self):
        html = self._html([Paragraph(runs=[Run(text="intro\n# not a heading\n- not a list")])])
        assert html == "<p>intro<br># not a heading<br>- not a list</p>\n"

    def test_heading_and_bullet_keep_their_line(self):
        nodes = [
            Heading(level=2, runs=[Run(text="Title\nsubtitle")]),
            BulletItem(runs=[Run(text="item\nmore")], ordered=False, depth=0),
        ]
        assert self._html(nodes) == (
            "<h2>Title<br>subtitle</h2>\n<ul>\n<li>item<br>more</li>\n</ul>\n"
        )

    def test_blockquote(self):
        html = self._html([Paragraph(runs=[Run(text="a\nb")], blockquote_depth=1)])
        assert html == "<blockquote>\n<p>a<br>b</p>\n</blockquote>\n"

    def test_emphasis_closes_around_edge_breaks(self):
        nodes = [Paragraph(runs=[Run(text="\nbold\n", bold=True), Run(text="x")])]
        assert self._html(nodes) == "<p><br><strong>bold</strong><br>x</p>\n"

    def test_emphasis_spans_an_inner_break(self):
        nodes = [Paragraph(runs=[Run(text="one\ntwo", italic=True)])]
        assert self._html(nodes) == "<p><em>one<br>two</em></p>\n"

    def test_edge_breaks_land_outside_the_link(self):
        url = "https://e.example"
        nodes = [Paragraph(runs=[Run(text="a"), Run(text="\nlink\n", link_url=url), Run(text="b")])]
        rendered = ast_to_markdown(nodes)
        assert rendered == f"a<br>[link]({url})<br>b\n"
        assert _COMMONMARK.render(rendered) == f'<p>a<br><a href="{url}">link</a><br>b</p>\n'

    # PR #1088 QA round 1: a space between the edge break and the run's own
    # edge kept the break inside the link, on both the plain and code paths.
    @pytest.mark.parametrize("code", [False, True])
    def test_space_beside_edge_break_stays_outside_the_link(self, code):
        url = "https://e.example"
        run = (_code if code else Run)(text=" \nlink\n ", link_url=url)
        rendered = ast_to_markdown([Paragraph(runs=[Run(text="a"), run, Run(text="b")])])
        inner = "`link`" if code else "link"
        assert rendered == f"a <br>[{inner}]({url})<br> b\n"
        html = _COMMONMARK.render(rendered)
        inner_html = "<code>link</code>" if code else "link"
        assert html == f'<p>a <br><a href="{url}">{inner_html}</a><br> b</p>\n'

    def test_space_beside_edge_break_in_table_cell(self):
        url = "https://e.example"
        cell = Cell(children=[Run(text="x"), Run(text=" \nlink", link_url=url)])
        rendered = ast_to_markdown([Table(rows=[Row(cells=[cell])])])
        assert rendered == f"| x <br>[link]({url}) |\n| --- |\n"

    def test_code_run_of_whitespace_and_breaks_keeps_the_fence(self):
        # Its link can't render, so it doesn't give up the fenced block.
        nodes = [Paragraph(runs=[_code("x"), _code(" \n ", link_url="https://e.example")])]
        assert ast_to_markdown(nodes).startswith("```\nx")

    def test_break_only_run(self):
        nodes = [Paragraph(runs=[Run(text="a"), Run(text="\n", bold=True), Run(text="b")])]
        assert self._html(nodes) == "<p>a<br>b</p>\n"

    def test_table_cell(self):
        doc_cell = {"content": [_para("x\vy\n")]}
        doc = {"body": {"content": [{"table": {"tableRows": [{"tableCells": [doc_cell]}]}}]}}
        rendered = ast_to_markdown(document_to_ast(doc))
        assert rendered == "| x<br>y |\n| --- |\n"

    def test_markup_next_to_a_break_stays_literal(self):
        text = "a <\nb> &\namp; c"
        html = self._html([Paragraph(runs=[Run(text=text)])])
        assert html == "<p>a &lt;<br>b&gt; &amp;<br>amp; c</p>\n"


class TestBangBeforeLinkCommonMark:
    """#969: a run ending in "!" followed by a linked run exported as
    "wow![x](url)", which CommonMark reads as an image."""

    URL = "https://e.example"

    def _html(self, runs):
        return _COMMONMARK.render(ast_to_markdown([Paragraph(runs=runs)]))

    def test_plain_bang_before_link_stays_text(self):
        runs = [Run(text="wow!"), Run(text="x", link_url=self.URL)]
        assert ast_to_markdown([Paragraph(runs=runs)]) == f"wow\\![x]({self.URL})\n"
        assert self._html(runs) == f'<p>wow!<a href="{self.URL}">x</a></p>\n'

    def test_plain_bang_before_linked_code(self):
        runs = [Run(text="wow!"), _code("x", link_url=self.URL)]
        assert self._html(runs) == f'<p>wow!<a href="{self.URL}"><code>x</code></a></p>\n'

    def test_plain_bang_before_linked_image(self):
        runs = [Run(text="wow!"), Image(src="https://i.example/p.png", alt="p", link_url=self.URL)]
        assert self._html(runs) == (
            f'<p>wow!<a href="{self.URL}"><img src="https://i.example/p.png" alt="p" /></a></p>\n'
        )

    def test_empty_run_between_does_not_hide_the_boundary(self):
        runs = [Run(text="wow!"), Run(text=""), Run(text="x", link_url=self.URL)]
        assert self._html(runs) == f'<p>wow!<a href="{self.URL}">x</a></p>\n'

    def test_literal_backslash_before_bang(self):
        # "a\" escapes to "a\\", which leaves the "!" live, so it still needs one.
        runs = [Run(text="a\\!"), Run(text="x", link_url=self.URL)]
        assert self._html(runs) == f'<p>a\\!<a href="{self.URL}">x</a></p>\n'

    def test_bang_not_before_link_is_left_alone(self):
        assert ast_to_markdown([Paragraph(runs=[Run(text="wow! "), Run(text="ok!")])]) == (
            "wow! ok!\n"
        )
        runs = [Run(text="wow!"), Image(src="https://i.example/p.png", alt="p")]
        assert ast_to_markdown([Paragraph(runs=runs)]) == "wow!![p](https://i.example/p.png)\n"
        assert self._html(runs) == '<p>wow!<img src="https://i.example/p.png" alt="p" /></p>\n'

    def test_table_cell(self):
        cell = Cell(children=[Run(text="wow!"), Run(text="x", link_url=self.URL)])
        table = Table(rows=[Row(cells=[cell]), Row(cells=[Cell(children=[Run(text="b")])])])
        html = _COMMONMARK.render(ast_to_markdown([table]))
        assert f'<th>wow!<a href="{self.URL}">x</a></th>' in html


class TestLookaheadEscapeAcrossRunsCommonMark:
    """PR #981 QA round 1: "<" and "&" are escaped only when the text after
    them would make a tag, autolink, or entity. A run boundary (e.g. a color
    change mid-word, which Markdown doesn't render) hid that text."""

    def _render(self, *texts):
        rendered = ast_to_markdown([Paragraph(runs=[Run(text=t) for t in texts])])
        inline = next(t for t in _COMMONMARK.parse(rendered) if t.type == "inline")
        return rendered, inline

    @pytest.mark.parametrize(
        "texts",
        [
            ("a <", "b> text"),
            ("AT&", "amp;T"),
            ("see <", "https://x.io>"),
            ("x &", "#124; y"),
            ("&", "am", "p; split three ways"),
            ("a <", "", "b> empty run between"),
        ],
    )
    def test_split_syntax_renders_literally(self, texts):
        _, inline = self._render(*texts)
        assert [t.type for t in inline.children] == ["text"]
        assert inline.children[0].content == "".join(texts)

    @pytest.mark.parametrize(
        "texts",
        [("a <", " b"), ("AT&", "T"), ("a &", " b"), ("1 <", "2")],
    )
    def test_prose_stays_unescaped(self, texts):
        rendered, _ = self._render(*texts)
        assert rendered == "".join(texts) + "\n"

    def test_less_than_before_inline_code_is_left_alone(self):
        rendered = ast_to_markdown([Paragraph(runs=[Run(text="a <"), _code("b")])])
        assert rendered == "a <`b`\n"

    def test_table_cell(self):
        cell = Cell(children=[Run(text="a <"), Run(text="b> text")])
        table = Table(rows=[Row(cells=[cell]), Row(cells=[Cell(children=[Run(text="c")])])])
        html = _COMMONMARK.render(ast_to_markdown([table]))
        assert "<th>a &lt;b&gt; text</th>" in html


_DECIMAL_LEVEL = {"glyphType": "DECIMAL"}


class TestOrderedListNumbering:
    """#1208: every ordered item rendered as "1.", so an item continuing a Docs
    list after an interrupting block read back as the start of a second list.
    doc_to_ast numbers items per listId and nesting level; ast_to_markdown
    writes that number."""

    @staticmethod
    def _item(text, list_id="l1", level=0):
        return _para(f"{text}\n", bullet={"listId": list_id, "nestingLevel": level})

    @staticmethod
    def _table():
        return {
            "table": {
                "tableRows": [{"tableCells": [{"tableCellStyle": {}, "content": [_para("c\n")]}]}]
            }
        }

    def _doc(self, content, lists=None):
        return {
            "body": {"content": content},
            "lists": lists or {"l1": {"listProperties": {"nestingLevels": [_DECIMAL_LEVEL] * 3}}},
        }

    def _numbers(self, doc):
        return [n.number for n in document_to_ast(doc) if isinstance(n, BulletItem)]

    def test_table_between_items_continues_the_count(self):
        doc = self._doc([self._item("step one"), self._table(), self._item("step two")])
        assert self._numbers(doc) == [1, 2]

    def test_paragraph_between_items_continues_the_count(self):
        doc = self._doc([self._item("a"), _para("aside\n"), self._item("b"), self._item("c")])
        assert self._numbers(doc) == [1, 2, 3]

    def test_each_list_id_counts_separately(self):
        lists = {
            lid: {"listProperties": {"nestingLevels": [_DECIMAL_LEVEL]}} for lid in ("l1", "l2")
        }
        doc = self._doc(
            [self._item("a"), self._item("x", "l2"), self._item("b"), self._item("y", "l2")],
            lists,
        )
        assert self._numbers(doc) == [1, 1, 2, 2]

    def test_sublevel_restarts_under_each_parent_item(self):
        doc = self._doc(
            [
                self._item("a"),
                self._item("a1", level=1),
                self._item("a2", level=1),
                self._item("b"),
                self._item("b1", level=1),
            ]
        )
        assert self._numbers(doc) == [1, 1, 2, 2, 1]

    def test_unordered_parent_still_restarts_an_ordered_sublevel(self):
        lists = {
            "l1": {"listProperties": {"nestingLevels": [{"glyphSymbol": "●"}, _DECIMAL_LEVEL]}}
        }
        doc = self._doc(
            [
                self._item("a"),
                self._item("a1", level=1),
                self._item("a2", level=1),
                self._item("b"),
                self._item("b1", level=1),
            ],
            lists,
        )
        assert self._numbers(doc) == [None, 1, 2, None, 1]

    @pytest.mark.parametrize(("start", "expected"), [(None, [1, 2]), (0, [1, 2]), (5, [5, 6])])
    def test_start_number_offsets_the_count(self, start, expected):
        level = dict(_DECIMAL_LEVEL)
        if start is not None:
            level["startNumber"] = start
        doc = self._doc(
            [self._item("a"), self._item("b")],
            {"l1": {"listProperties": {"nestingLevels": [level]}}},
        )
        assert self._numbers(doc) == expected

    def test_renderer_writes_the_number(self):
        nodes = [
            BulletItem(runs=[Run(text="a")], ordered=True, number=1),
            BulletItem(runs=[Run(text="b")], ordered=True, number=2),
        ]
        assert ast_to_markdown(nodes) == "1. a\n2. b\n"

    def test_renderer_without_a_number_keeps_one(self):
        nodes = [BulletItem(runs=[Run(text="a")], ordered=True)]
        assert ast_to_markdown(nodes) == "1. a\n"

    def test_interrupted_list_resumes_at_its_ordinal_in_commonmark(self):
        """The ticket's observed case (PR #1201 QA, TC-DOC233 step 5): one Docs
        list with a table between its two items."""
        doc = self._doc([self._item("step one"), self._table(), self._item("step two")])
        md = ast_to_markdown(document_to_ast(doc))
        assert "\n2. step two\n" in md
        assert '<ol start="2">\n<li>step two</li>' in _COMMONMARK.render(md)
