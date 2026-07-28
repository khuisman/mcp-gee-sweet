"""Tests for docs style tools and theme helpers."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs.ast import (
    Cell,
    RGBColor,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.content import _to_doc_requests
from mcp_gee_sweet.tools.docs.emitter import (
    _build_cell_style_requests,
    _run_style_requests,
)
from mcp_gee_sweet.tools.docs.style import (
    _build_named_style_requests,
    _read_body_styles,
    _read_named_styles,
    _text_style_and_fields,
)


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


# ---------------------------------------------------------------------------
# AST construction helpers
# ---------------------------------------------------------------------------


def _cell(text: str, colspan: int = 1, rowspan: int = 1) -> Cell:
    return Cell(children=[Run(text)], colspan=colspan, rowspan=rowspan)


def _row(*cells: Cell) -> Row:
    return Row(cells=list(cells))


def _table(*rows: Row) -> Table:
    return Table(rows=list(rows))


# ---------------------------------------------------------------------------
# Phase 3 — Run style fields
# ---------------------------------------------------------------------------


class TestRunStylesInParagraphs:
    async def test_bold_run_emits_update_text_style(self):
        requests, _ = _to_doc_requests("<p><b>bold</b></p>")
        bold_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        ]
        assert len(bold_reqs) == 1

    async def test_italic_run_emits_update_text_style(self):
        requests, _ = _to_doc_requests("<p><i>italic</i></p>")
        italic_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("italic") is True
        ]
        assert len(italic_reqs) == 1

    async def test_bold_italic_combined(self):
        requests, _ = _to_doc_requests("<p><b><i>both</i></b></p>")
        styled = [r for r in requests if "updateTextStyle" in r]
        ts = styled[0]["updateTextStyle"]["textStyle"]
        assert ts.get("bold") is True
        assert ts.get("italic") is True

    async def test_font_family_emits_weighted_font(self):
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

    async def test_pre_block_font_family_emitted(self):
        requests, _ = _to_doc_requests("<pre><code>x = 1</code></pre>")
        font_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "weightedFontFamily" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(font_reqs) == 1

    async def test_link_still_emitted(self):
        requests, _ = _to_doc_requests('<p><a href="https://x.com">link</a></p>')
        link_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(link_reqs) == 1


class TestTextStyleAndFieldsLinkClearing:
    """#408: link_url=None must clear a link, not send an invalid empty Link{}."""

    def test_link_url_set_emits_link_object(self):
        text_style, fields = _text_style_and_fields({"link_url": "https://x.com"})
        assert text_style == {"link": {"url": "https://x.com"}}
        assert fields == ["link"]

    def test_link_url_none_omits_link_key_but_keeps_field_mask(self):
        # The Docs API rejects an empty Link{} object ("must include at least
        # one type") — clearing a link means naming "link" in the field mask
        # while omitting the "link" key from textStyle entirely, so the API
        # resets it to its default (no link).
        text_style, fields = _text_style_and_fields({"link_url": None})
        assert text_style == {}
        assert fields == ["link"]

    def test_link_url_absent_does_not_touch_link(self):
        text_style, fields = _text_style_and_fields({"bold": True})
        assert "link" not in text_style
        assert "link" not in fields


class TestRunStylePhase3:
    def _run_req(self, run: Run) -> dict | None:
        reqs = _run_style_requests(run, 10, 15)
        return reqs[0]["updateTextStyle"] if reqs else None

    async def test_font_size_emits_fontSize(self):
        req = self._run_req(Run("hello", font_size=14.0))
        assert req is not None
        assert req["textStyle"]["fontSize"] == {"magnitude": 14.0, "unit": "PT"}
        assert "fontSize" in req["fields"]

    async def test_foreground_color_emits_foregroundColor(self):
        color = RGBColor(red=1.0, green=0.0, blue=0.0)
        req = self._run_req(Run("hello", foreground_color=color))
        assert req is not None
        rgb = req["textStyle"]["foregroundColor"]["color"]["rgbColor"]
        assert rgb == {"red": 1.0, "green": 0.0, "blue": 0.0}
        assert "foregroundColor" in req["fields"]

    async def test_background_color_emits_backgroundColor(self):
        color = RGBColor(red=0.0, green=1.0, blue=0.0)
        req = self._run_req(Run("hello", background_color=color))
        assert req is not None
        rgb = req["textStyle"]["backgroundColor"]["color"]["rgbColor"]
        assert rgb == {"red": 0.0, "green": 1.0, "blue": 0.0}
        assert "backgroundColor" in req["fields"]

    async def test_baseline_offset_emits_baselineOffset(self):
        req = self._run_req(Run("hello", baseline_offset="SUPERSCRIPT"))
        assert req is not None
        assert req["textStyle"]["baselineOffset"] == "SUPERSCRIPT"
        assert "baselineOffset" in req["fields"]

    async def test_small_caps_emits_smallCaps(self):
        req = self._run_req(Run("hello", small_caps=True))
        assert req is not None
        assert req["textStyle"]["smallCaps"] is True
        assert "smallCaps" in req["fields"]

    async def test_none_phase3_fields_not_emitted(self):
        req = self._run_req(Run("hello", bold=True))
        assert req is not None
        assert "fontSize" not in req["textStyle"]
        assert "foregroundColor" not in req["textStyle"]
        assert "backgroundColor" not in req["textStyle"]
        assert "baselineOffset" not in req["textStyle"]
        assert "smallCaps" not in req["textStyle"]

    async def test_combined_phase2_and_phase3(self):
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

    async def test_background_color_emitted(self):
        color = RGBColor(red=0.9, green=0.9, blue=0.9)
        ast_table = Table(rows=[Row(cells=[Cell(children=[], background_color=color), _cell("b")])])
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

    async def test_padding_emitted(self):
        ast_table = Table(
            rows=[
                Row(
                    cells=[
                        Cell(
                            children=[],
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

    async def test_border_emitted_all_sides(self):
        color = RGBColor(0.0, 0.0, 0.0)
        ast_table = Table(
            rows=[
                Row(
                    cells=[
                        Cell(
                            children=[],
                            border_color=color,
                            border_width=0.5,
                            border_dash_style="SOLID",
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

    async def test_no_style_fields_skipped(self):
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
    async def test_read_body_styles_extracts_fields(self):
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

    async def test_first_paragraph_per_type_wins(self):
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

    async def test_unknown_style_type_ignored(self):
        doc = _make_body_doc(
            [{"style_type": "DEFAULT_PARAGRAPH_STYLE", "text": "x", "text_style": {"bold": True}}]
        )
        theme = _read_body_styles(doc)
        assert "DEFAULT_PARAGRAPH_STYLE" not in theme

    async def test_build_named_style_requests_text_fields(self):
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

    async def test_build_named_style_requests_para_fields(self):
        reqs = _build_named_style_requests("NORMAL_TEXT", {"line_spacing": 115, "space_above": 6.0})
        req = reqs[0]["updateNamedStyle"]
        assert "named_style_type" in req["fields"]
        assert "paragraph_style.line_spacing" in req["fields"]
        assert "paragraph_style.space_above" in req["fields"]
        assert req["namedStyle"]["paragraphStyle"]["lineSpacing"] == 115

    async def test_build_named_style_requests_empty_entry_returns_empty(self):
        assert _build_named_style_requests("NORMAL_TEXT", {}) == []

    async def test_read_named_styles_extracts_fields(self):
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

    async def test_read_named_styles_unknown_type_ignored(self):
        doc = {
            "namedStyles": {
                "styles": [
                    {"namedStyleType": "DEFAULT_PARAGRAPH_STYLE", "textStyle": {"bold": True}}
                ]
            }
        }
        theme = _read_named_styles(doc)
        assert "DEFAULT_PARAGRAPH_STYLE" not in theme

    async def test_read_named_styles_empty_entry_omitted(self):
        doc = {
            "namedStyles": {
                "styles": [{"namedStyleType": "HEADING_1", "textStyle": {}, "paragraphStyle": {}}]
            }
        }
        theme = _read_named_styles(doc)
        assert "HEADING_1" not in theme


# ---------------------------------------------------------------------------
# style_doc_range tool
# ---------------------------------------------------------------------------


class TestStyleDocRangeTool:
    def _setup(self):
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        return tools

    async def test_link_url_null_clears_link(self):
        # #408: link_url=None must actually send a clearing request, not get
        # silently skipped because the resulting textStyle dict is empty.
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5, "link_url": None}],
            ctx=ctx,
        )
        assert "error" not in result
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        link_reqs = [r for r in reqs if "updateTextStyle" in r]
        assert len(link_reqs) == 1
        update = link_reqs[0]["updateTextStyle"]
        assert update["fields"] == "link"
        assert "link" not in update["textStyle"]

    async def test_link_url_set_sends_link_object(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5, "link_url": "https://x.com"}],
            ctx=ctx,
        )
        assert "error" not in result
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        update = next(r["updateTextStyle"] for r in reqs if "updateTextStyle" in r)
        assert update["textStyle"]["link"] == {"url": "https://x.com"}


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

    async def test_apply_theme_emits_update_named_style(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
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

    async def test_apply_theme_empty_theme_returns_error(self):
        tools = self._setup()
        mock_docs = MagicMock()
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        result = await tools["apply_theme"](doc_id="doc123", theme={}, ctx=ctx)
        assert "error" in result

    async def test_apply_theme_table_style(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "body": {"content": [{"table": {"rows": 2, "columns": 3}, "startIndex": 5}]}
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
            doc_id="doc123",
            theme={"table": {"border_width": 0.5, "cell_padding": 3.6}},
            ctx=ctx,
        )
        mock_docs.documents().get.assert_called_with(documentId="doc123")
        assert result["requests"] > 0

    async def test_apply_theme_default_succeeds_without_matching_paragraphs(self):
        # Default mode (overwrite=False) updates named style definitions regardless of
        # which paragraphs currently exist in the doc.
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
            doc_id="doc123",
            theme={"HEADING_1": {"font_size": 20.0}},
            ctx=ctx,
        )
        assert "error" not in result
        assert result["requests"] == 1

    async def test_apply_theme_overwrite_also_updates_paragraphs(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = self._mock_doc_with_para("HEADING_1")
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
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

    async def test_get_doc_theme_returns_theme_dict(self):
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
        result = await tools["get_doc_theme"](doc_id="doc123", ctx=ctx)
        assert "HEADING_1" in result
        assert result["HEADING_1"]["font_family"] == "Arial"

    async def test_get_doc_named_styles_returns_named_style_dict(self):
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
        result = await tools["get_doc_named_styles"](doc_id="doc123", ctx=ctx)
        assert "HEADING_1" in result
        assert result["HEADING_1"]["font_family"] == "Georgia"
        assert result["HEADING_1"]["font_size"] == 20.0
