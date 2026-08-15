"""Tests for the Docs -> Markdown export path (issue #300): doc_to_ast.py's Docs
API -> AST walker, ast_to_markdown.py's AST -> Markdown serializer, and the
get_doc_as_markdown tool wiring them together."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Heading,
    Image,
    NamedBlock,
    Paragraph,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.ast_to_markdown import ast_to_markdown
from mcp_gee_sweet.tools.docs.doc_to_ast import document_to_ast


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

    def tool(annotations=None):
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

    def test_no_comments_section_when_comments_is_none(self):
        nodes = [Paragraph(runs=[Run(text="body")])]
        assert "## Comments" not in ast_to_markdown(nodes, comments=None)


class TestGetDocAsMarkdownTool:
    def test_is_read_only(self):
        assert _docs_annotations["get_doc_as_markdown"].readOnlyHint is True

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
        dest = tmp_path / "out.json"
        result = await _docs_tools["get_doc_as_markdown"](
            doc_id="doc1", local_path=str(dest), ctx=ctx
        )
        assert result["local_path"] == str(dest)
        assert dest.exists()
