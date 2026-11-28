"""Tests for docs style tools and theme helpers."""

from typing import ClassVar
from unittest.mock import MagicMock

import pytest

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
    _STYLED_ELEMENT_KINDS,
    _add_or_clear_field,
    _bold_runs_in_range,
    _build_named_style_requests,
    _clear_paragraph_gap_requests,
    _own_paragraph_spacing_fields,
    _read_body_styles,
    _read_named_styles,
    _text_style_and_fields,
)


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False, **_):
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

    def test_font_family_sets_weighted_font_family(self):
        # #720: font_family sets weightedFontFamily with fontFamily
        text_style, fields = _text_style_and_fields({"font_family": "Courier New"})
        assert text_style == {"weightedFontFamily": {"fontFamily": "Courier New"}}
        assert fields == ["weightedFontFamily"]


class TestAddOrClearField:
    """#448: the general "omit key but keep field mask" helper factored out
    of _text_style_and_fields's link_url case, now also used directly by
    content.py's heading-anchor link resolve/strip code — tested on its own
    generic contract (an arbitrary api_field/value), not just "link", since
    a future nullable field (e.g. foreground_color) is expected to reuse it
    without ever touching links at all."""

    def test_truthy_value_sets_field_and_masks_it(self):
        text_style: dict = {}
        fields: list[str] = []
        _add_or_clear_field(text_style, fields, "foregroundColor", {"color": "red"})
        assert text_style == {"foregroundColor": {"color": "red"}}
        assert fields == ["foregroundColor"]

    def test_none_value_omits_key_but_still_masks_it(self):
        text_style: dict = {}
        fields: list[str] = []
        _add_or_clear_field(text_style, fields, "foregroundColor", None)
        assert text_style == {}
        assert fields == ["foregroundColor"]

    def test_empty_dict_value_is_written_as_is_not_treated_as_clear(self):
        # PR #778 QA round 1, finding 1: gating on "is not None" rather than
        # truthiness is deliberate — an explicitly passed empty dict ({}) is
        # a real value, not a clear request, and must be written into
        # text_style verbatim rather than silently treated the same as
        # None. (Whether {} is itself a *valid* Docs API value is the
        # caller's problem, same as any other value this helper is handed —
        # not something this generic helper can or should judge.)
        text_style: dict = {}
        fields: list[str] = []
        _add_or_clear_field(text_style, fields, "foregroundColor", {})
        assert text_style == {"foregroundColor": {}}
        assert fields == ["foregroundColor"]

    def test_accumulates_onto_existing_text_style_and_fields(self):
        # Callers (e.g. content.py's heading-anchor code) reuse one
        # text_style/fields pair across a single request's fields — a second
        # call must not clobber what the first one already added.
        text_style: dict = {"bold": True}
        fields: list[str] = ["bold"]
        _add_or_clear_field(text_style, fields, "link", {"url": "https://x.com"})
        assert text_style == {"bold": True, "link": {"url": "https://x.com"}}
        assert fields == ["bold", "link"]


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


class TestBoldRunsInRangeElementKinds:
    """#1635: every ParagraphElement kind that carries a textStyle counts as a
    run for the bold read, not only textRun."""

    def test_kinds_match_the_discovery_document(self):
        # Pins _STYLED_ELEMENT_KINDS to the Docs API's own schema, so a kind
        # Google adds with a textStyle fails here instead of reading as plain.
        import json
        from pathlib import Path

        import googleapiclient

        path = Path(googleapiclient.__file__).parent / "discovery_cache/documents/docs.v1.json"
        schemas = json.loads(path.read_text())["schemas"]
        styled = {
            name
            for name, prop in schemas["ParagraphElement"]["properties"].items()
            if "$ref" in prop and "textStyle" in schemas[prop["$ref"]]["properties"]
        }
        assert set(_STYLED_ELEMENT_KINDS) == styled
        assert len(_STYLED_ELEMENT_KINDS) == len(styled)

    @staticmethod
    def _doc(elements: list[dict]) -> dict:
        return {"body": {"content": [{"startIndex": 1, "paragraph": {"elements": elements}}]}}

    def test_bold_image_and_text_merge_into_one_span(self):
        doc = self._doc(
            [
                {
                    "startIndex": 1,
                    "endIndex": 2,
                    "inlineObjectElement": {"inlineObjectId": "i", "textStyle": {"bold": True}},
                },
                {
                    "startIndex": 2,
                    "endIndex": 4,
                    "textRun": {"content": "ab", "textStyle": {"bold": True}},
                },
            ]
        )
        assert _bold_runs_in_range(doc, 1, 4) == [{"startIndex": 1, "endIndex": 4}]

    def test_element_without_text_style_is_skipped_but_advances_offset(self):
        # An equation has no textStyle: never bold, but it still takes its
        # index, so the bold run after it is read at the right position.
        doc = self._doc(
            [
                {"equation": {}, "endIndex": 2},
                {"textRun": {"content": "B", "textStyle": {"bold": True}}},
            ]
        )
        assert _bold_runs_in_range(doc, 1, 3) == [{"startIndex": 2, "endIndex": 3}]


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

    async def test_font_family_sets_weighted_font_family(self):
        # #720: font_family sets textStyle.weightedFontFamily.fontFamily and fields="weightedFontFamily"
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5, "font_family": "Courier New"}],
            ctx=ctx,
        )
        assert "error" not in result
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        update = next(r["updateTextStyle"] for r in reqs if "updateTextStyle" in r)
        assert update["fields"] == "weightedFontFamily"
        assert update["textStyle"]["weightedFontFamily"] == {"fontFamily": "Courier New"}

    async def test_font_family_only_restores_bold_over_bold_runs(self):
        """#1273: a weightedFontFamily request with no bold in the same call clears
        the range's direct bold, so the bold runs read before the batchUpdate are
        restored in the same batch, after the font request."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 22,
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 6,
                                    "textRun": {"content": "Alpha ", "textStyle": {}},
                                },
                                {
                                    "startIndex": 6,
                                    "endIndex": 10,
                                    "textRun": {
                                        "content": "Beta",
                                        "textStyle": {"bold": True},
                                    },
                                },
                                {
                                    "startIndex": 10,
                                    "endIndex": 22,
                                    "textRun": {"content": " Gamma Delta\n", "textStyle": {}},
                                },
                            ]
                        },
                    }
                ]
            },
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 7, "end_index": 11, "font_family": "Georgia"}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert len(reqs) == 2
        font_update = reqs[0]["updateTextStyle"]
        assert font_update["fields"] == "weightedFontFamily"
        bold_update = reqs[1]["updateTextStyle"]
        assert bold_update["fields"] == "bold"
        assert bold_update["textStyle"] == {"bold": True}
        # only the bold part of the requested range [7, 11) is restored: [7, 10)
        assert bold_update["range"] == {"startIndex": 7, "endIndex": 10}

    async def test_font_family_only_restores_bold_over_bold_inline_image(self):
        """#1635: a directly bold inline image in the range is restored with the
        text around it, so text typed after it later still inherits bold."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 7,
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 2,
                                    "inlineObjectElement": {
                                        "inlineObjectId": "kix.img",
                                        "textStyle": {"bold": True},
                                    },
                                },
                                {
                                    "startIndex": 2,
                                    "endIndex": 7,
                                    "textRun": {"content": "text\n", "textStyle": {}},
                                },
                            ]
                        },
                    }
                ]
            },
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 6, "font_family": "Georgia"}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert [r["updateTextStyle"]["fields"] for r in reqs] == ["weightedFontFamily", "bold"]
        assert reqs[1]["updateTextStyle"]["range"] == {"startIndex": 1, "endIndex": 2}

    async def test_adjacent_bold_runs_merge_into_one_restore_request(self):
        """#1273: two adjacent bold runs inside the range restore as one span."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 4,
                                    "textRun": {"content": "abc", "textStyle": {"bold": True}},
                                },
                                {
                                    "startIndex": 4,
                                    "endIndex": 7,
                                    "textRun": {"content": "def", "textStyle": {"bold": True}},
                                },
                                {
                                    "startIndex": 7,
                                    "endIndex": 10,
                                    "textRun": {"content": "ghi", "textStyle": {}},
                                },
                            ]
                        },
                    }
                ]
            },
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 10, "font_family": "Georgia"}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        bold_updates = [
            r["updateTextStyle"] for r in reqs if r["updateTextStyle"]["fields"] == "bold"
        ]
        assert len(bold_updates) == 1
        assert bold_updates[0]["range"] == {"startIndex": 1, "endIndex": 7}

    async def test_font_family_with_bold_true_reads_nothing_and_restores_nothing(self):
        """#1273's not-affected case: bold in the same range dict keeps the bold,
        so no document read and no restore request."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5, "font_family": "Courier New", "bold": True}],
            ctx=ctx,
        )
        assert "error" not in result
        mock_docs.documents().get.assert_not_called()
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert len(reqs) == 1

    async def test_font_family_read_failure_returns_error_dict(self):
        """#1273: a failed document read before styling returns the error dict,
        with no batchUpdate sent."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.side_effect = Exception("boom")
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5, "font_family": "Courier New"}],
            ctx=ctx,
        )
        assert "boom" in result["error"]
        mock_docs.documents().batchUpdate.assert_not_called()

    async def test_font_only_restore_handles_element_without_start_index(self):
        """The Docs API sometimes omits startIndex on an element, usually a
        document's first one (indices._collect_doc_paragraphs guards this).
        The restore must carry the offset forward from the paragraph's start
        instead of raising a KeyError (#1273 review)."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "elements": [
                                {
                                    # no startIndex, as on a first element;
                                    # its bold run starts at the paragraph's own start
                                    "endIndex": 10,
                                    "textRun": {
                                        "content": "boldtext",
                                        "textStyle": {"bold": True},
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 10, "font_family": "Georgia"}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        bold_updates = [
            r["updateTextStyle"]
            for r in reqs
            if r["updateTextStyle"]["fields"] == "bold"
            and r["updateTextStyle"]["textStyle"] == {"bold": True}
        ]
        assert bold_updates[0]["range"] == {"startIndex": 1, "endIndex": 10}

    async def test_font_only_after_bold_false_range_stays_unbold(self):
        """An earlier range in the same call that sets bold=False over the same
        text must win over the pre-batch read: on bold text, bold=False then
        font_family ends unbolded — no restore request re-bolds the overlap
        (#1273 review)."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 10,
                                    "textRun": {
                                        "content": "boldtext",
                                        "textStyle": {"bold": True},
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 10, "bold": False},
                {"start_index": 1, "end_index": 10, "font_family": "Georgia"},
            ],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        bold_updates = [
            r["updateTextStyle"] for r in reqs if r["updateTextStyle"]["fields"] == "bold"
        ]
        # the earlier range set bold=False over the whole overlap, so the
        # restore must not re-bold any of it
        assert [u for u in bold_updates if u["textStyle"] == {"bold": True}] == []
        assert reqs[0]["updateTextStyle"]["textStyle"] == {"bold": False}
        assert reqs[1]["updateTextStyle"]["fields"] == "weightedFontFamily"

    async def test_font_only_after_bold_true_range_restores_bold(self):
        """The reverse direction: bold=True then font_family on plain text must
        end bolded — the restore accounts for the earlier range instead of
        trusting the pre-batch read (#1273 review)."""
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "documentId": "doc123",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 10,
                                    "textRun": {"content": "plaintext", "textStyle": {}},
                                }
                            ]
                        },
                    }
                ]
            },
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["style_doc_range"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 10, "bold": True},
                {"start_index": 1, "end_index": 10, "font_family": "Georgia"},
            ],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        bold_updates = [
            r["updateTextStyle"] for r in reqs if r["updateTextStyle"]["fields"] == "bold"
        ]
        assert bold_updates[0]["textStyle"] == {"bold": True}
        assert bold_updates[1]["textStyle"] == {"bold": True}
        assert bold_updates[1]["range"] == {"startIndex": 1, "endIndex": 10}


class TestStyleDocRangeParagraphSpacing:
    """#1439: style_doc_range sets and clears line_spacing, space_above, space_below."""

    async def _call(self, *ranges):
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        mock_docs.documents().batchUpdate.reset_mock()
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        result = await tools["style_doc_range"](doc_id="doc1", ranges=list(ranges), ctx=ctx)
        call = mock_docs.documents().batchUpdate.call_args
        reqs = call[1]["body"]["requests"] if call else None
        return result, reqs

    async def test_sets_all_three_in_one_paragraph_request(self):
        result, reqs = await self._call(
            {
                "start_index": 3,
                "end_index": 9,
                "line_spacing": 115,
                "space_above": 0,
                "space_below": 6.5,
            }
        )
        assert result == {"docId": "doc1", "requests": 1}
        assert reqs == [
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 3, "endIndex": 9},
                    "paragraphStyle": {
                        "lineSpacing": 115,
                        "spaceAbove": {"magnitude": 0, "unit": "PT"},
                        "spaceBelow": {"magnitude": 6.5, "unit": "PT"},
                    },
                    "fields": "lineSpacing,spaceAbove,spaceBelow",
                }
            }
        ]

    async def test_null_clears_the_field(self):
        _, reqs = await self._call(
            {"start_index": 1, "end_index": 4, "line_spacing": None, "space_below": None}
        )
        update = reqs[0]["updateParagraphStyle"]
        assert update["paragraphStyle"] == {}
        assert update["fields"] == "lineSpacing,spaceBelow"

    async def test_shares_the_request_with_named_style_type(self):
        _, reqs = await self._call(
            {"start_index": 1, "end_index": 4, "named_style_type": "HEADING_2", "line_spacing": 200}
        )
        assert reqs == [
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": 4},
                    "paragraphStyle": {"namedStyleType": "HEADING_2", "lineSpacing": 200},
                    "fields": "namedStyleType,lineSpacing",
                }
            }
        ]

    async def test_paragraph_request_comes_before_text_request(self):
        _, reqs = await self._call(
            {"start_index": 1, "end_index": 4, "space_above": 4, "bold": True}
        )
        assert [next(iter(r)) for r in reqs] == ["updateParagraphStyle", "updateTextStyle"]

    async def test_named_style_alone_is_unchanged(self):
        _, reqs = await self._call({"start_index": 1, "end_index": 4, "named_style_type": "TITLE"})
        assert reqs[0]["updateParagraphStyle"]["fields"] == "namedStyleType"
        assert reqs[0]["updateParagraphStyle"]["paragraphStyle"] == {"namedStyleType": "TITLE"}

    @pytest.mark.parametrize(
        ("key", "value", "message"),
        [
            ("line_spacing", 0, "line_spacing must be greater than zero"),
            ("line_spacing", -50, "line_spacing must be greater than zero"),
            ("space_above", -1, "space_above must be zero or more"),
            ("space_below", "12", "space_below must be a number or null"),
            ("line_spacing", True, "line_spacing must be a number or null"),
            # PR #1631 QA round 1: NaN passes `< 0` and `== 0`, and none is valid JSON.
            ("line_spacing", float("nan"), "line_spacing must be a number or null"),
            ("space_above", float("inf"), "space_above must be a number or null"),
            ("space_below", float("-inf"), "space_below must be a number or null"),
        ],
    )
    async def test_invalid_values_refused_before_any_call(self, key, value, message):
        result, reqs = await self._call(
            {"start_index": 1, "end_index": 4, "bold": True},
            {"start_index": 5, "end_index": 8, key: value},
        )
        assert reqs is None
        assert result["error"].startswith(f"ranges[1]: {message}")

    async def test_invalid_value_refused_before_the_font_family_read(self):
        # PR #1631 QA round 1: a font_family range makes style_doc_range read the doc
        # for #1273's bold restore; a bad spacing value must not cost that read, nor
        # be hidden by its error.
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        mock_docs = MagicMock()
        mock_docs.documents.return_value.get.return_value.execute.side_effect = Exception("429")
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        result = await tools["style_doc_range"](
            doc_id="doc1",
            ranges=[
                {"start_index": 1, "end_index": 4, "font_family": "Georgia"},
                {"start_index": 5, "end_index": 8, "space_below": -2},
            ],
            ctx=ctx,
        )
        assert result == {"error": "ranges[1]: space_below must be zero or more, got -2"}
        mock_docs.documents.return_value.get.assert_not_called()
        mock_docs.documents.return_value.batchUpdate.assert_not_called()


# ---------------------------------------------------------------------------
# create_paragraph_bullets / delete_paragraph_bullets tools (#334)
# ---------------------------------------------------------------------------


def _zero_indent(start, end):
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentStart": {"magnitude": 0, "unit": "PT"},
                "indentFirstLine": {"magnitude": 0, "unit": "PT"},
            },
            "fields": "indentStart,indentFirstLine",
        }
    }


class TestCreateParagraphBulletsTool:
    """#334 round 2: createParagraphBullets is a no-op on an already-listed
    paragraph, and infers nesting only relative to whatever else is in the
    same call — confirmed live against the real Docs API (see PR #524
    review). The tool now fetches the doc, expands each already-listed
    target to its full contiguous same-listId neighbor run (preserving each
    neighbor's own nesting level), and issues one createParagraphBullets
    call per contiguous run, always preceded by deleteParagraphBullets.
    """

    def _setup(self):
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        return tools

    def _doc(self, paragraphs, lists=None):
        # paragraphs: list of (start, end, text, bullet_or_None[, paragraphStyle])
        content = []
        for start, end, text, bullet, *style in paragraphs:
            para = {"elements": [{"textRun": {"content": text}}]}
            if bullet is not None:
                para["bullet"] = bullet
            if style:
                para["paragraphStyle"] = style[0]
            content.append({"startIndex": start, "endIndex": end, "paragraph": para})
        doc = {"documentId": "doc123", "body": {"content": content}}
        if lists is not None:
            doc["lists"] = lists
        return doc

    def _numbered_list_entry(self, num_levels=1):
        # Mirrors a live NUMBERED_DECIMAL_ALPHA_ROMAN list's own `lists` map
        # shape (confirmed live, #334 round 2): level 0 uses glyphType.
        return {
            "listProperties": {
                "nestingLevels": [{"glyphType": "DECIMAL"} for _ in range(num_levels)]
            }
        }

    def _bullet_list_entry(self, num_levels=1):
        return {
            "listProperties": {"nestingLevels": [{"glyphSymbol": "●"} for _ in range(num_levels)]}
        }

    def _mocks(self, doc):
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = doc
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        return mock_docs, ctx

    async def test_empty_ranges_returns_error(self):
        tools = self._setup()
        ctx = _make_ctx(docs_service=MagicMock(), doc_cache=MagicMock())
        result = await tools["create_paragraph_bullets"](doc_id="doc123", ranges=[], ctx=ctx)
        assert "error" in result

    async def test_negative_nesting_level_returns_error(self):
        tools = self._setup()
        ctx = _make_ctx(docs_service=MagicMock(), doc_cache=MagicMock())
        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5, "nesting_level": -1}],
            ctx=ctx,
        )
        assert "error" in result

    async def test_range_not_overlapping_any_paragraph_returns_error(self):
        tools = self._setup()
        doc = self._doc([(1, 10, "Item\n", None)])
        _mock_docs, ctx = self._mocks(doc)
        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 50, "end_index": 60}],
            ctx=ctx,
        )
        assert "error" in result

    async def test_fresh_paragraph_top_level_sends_delete_then_create(self):
        # No pre-existing bullet, nesting_level 0 (default): a lone
        # deleteParagraphBullets (harmless no-op), the indent reset, then
        # createParagraphBullets, no insertText needed.
        tools = self._setup()
        doc = self._doc([(1, 10, "Item\n", None)])
        mock_docs, ctx = self._mocks(doc)

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 10}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert len(reqs) == 3
        assert reqs[0]["deleteParagraphBullets"]["range"] == {"startIndex": 1, "endIndex": 10}
        assert reqs[1]["updateParagraphStyle"]["range"] == {"startIndex": 1, "endIndex": 10}
        bullet_req = reqs[2]["createParagraphBullets"]
        assert bullet_req["range"] == {"startIndex": 1, "endIndex": 10}
        assert bullet_req["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"

    async def test_ordered_preset_passthrough(self):
        tools = self._setup()
        doc = self._doc([(1, 10, "Item\n", None)])
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {
                    "start_index": 1,
                    "end_index": 10,
                    "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                }
            ],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        create_req = next(
            r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r
        )
        assert create_req["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"

    async def test_nesting_level_on_isolated_paragraph_inserts_tabs(self):
        # A single paragraph with no same-list neighbors in the doc at all —
        # nothing to expand, tabs inserted directly for the target itself.
        # Every unit in the run sits at nesting_level > 0, so a throwaway
        # 0-tab anchor paragraph is prepended and then deleted (#713) to
        # stop the API collapsing the run to nestingLevel 0.
        tools = self._setup()
        doc = self._doc([(5, 15, "Item\n", {"listId": "L1"})])
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 5, "end_index": 15, "nesting_level": 2}],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert reqs[0]["deleteParagraphBullets"]["range"] == {"startIndex": 5, "endIndex": 15}
        assert "updateParagraphStyle" in reqs[1]
        assert reqs[2]["insertText"] == {"location": {"index": 5}, "text": "\t\t"}
        assert reqs[3]["insertText"] == {"location": {"index": 5}, "text": "\n"}
        # endIndex = run_end (15) + total_tabs (2) + anchor newline (1)
        assert reqs[4]["createParagraphBullets"]["range"] == {"startIndex": 5, "endIndex": 18}
        assert reqs[5]["deleteContentRange"]["range"] == {"startIndex": 5, "endIndex": 6}

    async def test_isolated_all_nonzero_run_wraps_zero_tab_anchor(self):
        # #713: repairing part of an existing list whose contiguous
        # same-listId run has NO level-0 member (every neighbour pulled in
        # by the expansion pass is itself at nestingLevel >= 1). Without a
        # 0-tab anchor, createParagraphBullets assigns every paragraph
        # nestingLevel = (its tabs) - (min tabs in range) = 0 and renders
        # the depth-0 disc glyph despite the bumped indent — the same shape
        # #439 fixed for emitter.py in PR #711.
        tools = self._setup()
        bullet = {"listId": "L1", "nestingLevel": 1}
        doc = self._doc(
            [
                (1, 6, "One\n", bullet),
                (6, 11, "Two\n", bullet),
                (11, 17, "Three\n", bullet),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 6, "end_index": 11, "nesting_level": 1}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        kinds = [next(iter(r)) for r in reqs]
        # the indent reset, tabs for all three items, then the anchor
        # newline, then one createParagraphBullets, then the anchor delete.
        assert kinds == [
            "deleteParagraphBullets",
            "updateParagraphStyle",
            "insertText",
            "insertText",
            "insertText",
            "insertText",
            "createParagraphBullets",
            "deleteContentRange",
        ]
        # Tabs are inserted in descending-start order (Three, Two, One), each
        # unit's own single tab at its own start index — the load-bearing
        # invariant is that these three land in the request array *before*
        # the anchor insert below, since both the last of these (index 1) and
        # the anchor target the identical run_start index (1) and Docs API
        # requests at the same location apply in array order.
        assert reqs[2]["insertText"] == {"location": {"index": 11}, "text": "\t"}
        assert reqs[3]["insertText"] == {"location": {"index": 6}, "text": "\t"}
        assert reqs[4]["insertText"] == {"location": {"index": 1}, "text": "\t"}
        anchor_insert = reqs[5]["insertText"]
        assert anchor_insert == {"location": {"index": 1}, "text": "\n"}
        create = reqs[6]["createParagraphBullets"]
        # run_end (17) + total_tabs (1 per item * 3) + anchor newline (1)
        assert create["range"] == {"startIndex": 1, "endIndex": 21}
        assert reqs[7]["deleteContentRange"]["range"] == {"startIndex": 1, "endIndex": 2}

    async def test_expands_to_include_same_list_neighbors(self):
        # #334 round 2's core fix: nesting the middle paragraph of an
        # existing 3-item list must pull in both same-listId neighbors
        # (preserving their own nesting_level unchanged) into ONE run,
        # rather than only touching the requested paragraph in isolation —
        # confirmed live that an isolated single-paragraph call gets
        # silently overridden back to level 0 by untouched neighbors.
        tools = self._setup()
        bullet = {"listId": "L1"}
        doc = self._doc(
            [
                (1, 6, "One\n", bullet),
                (6, 11, "Two\n", bullet),
                (11, 17, "Three\n", bullet),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 6, "end_index": 11, "nesting_level": 1}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        # One run spanning all three paragraphs: delete over the whole span,
        # exactly one insertText (only "Two" gets a tab), one create call.
        delete_reqs = [r for r in reqs if "deleteParagraphBullets" in r]
        insert_reqs = [r for r in reqs if "insertText" in r]
        create_reqs = [r for r in reqs if "createParagraphBullets" in r]
        assert len(delete_reqs) == 1
        assert delete_reqs[0]["deleteParagraphBullets"]["range"] == {
            "startIndex": 1,
            "endIndex": 17,
        }
        assert len(insert_reqs) == 1
        assert insert_reqs[0]["insertText"] == {"location": {"index": 6}, "text": "\t"}
        assert len(create_reqs) == 1
        assert create_reqs[0]["createParagraphBullets"]["range"] == {
            "startIndex": 1,
            "endIndex": 18,
        }

    async def test_indent_reset_between_delete_and_tabs(self):
        # #1069: deleteParagraphBullets leaves a level-N item indented 36pt * N,
        # and createParagraphBullets counts that indent as depth on top of the
        # inserted tabs (confirmed live: re-running a 0/1/2 call gave 0/2/4).
        # Both indents are zeroed over the whole run after the delete and
        # before any tab insert, so the tabs alone set the level.
        tools = self._setup()
        doc = self._doc(
            [
                (1, 6, "One\n", {"listId": "L1"}),
                (6, 11, "Two\n", {"listId": "L1", "nestingLevel": 1}),
                (11, 17, "Three\n", {"listId": "L1", "nestingLevel": 2}),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 6, "end_index": 11, "nesting_level": 1}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert next(iter(reqs[0])) == "deleteParagraphBullets"
        assert reqs[1] == {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": 17},
                "paragraphStyle": {
                    "indentStart": {"magnitude": 0, "unit": "PT"},
                    "indentFirstLine": {"magnitude": 0, "unit": "PT"},
                },
                "fields": "indentStart,indentFirstLine",
            }
        }
        assert all("insertText" in r for r in reqs[2:4])

    async def test_rerunning_same_call_inserts_only_requested_tabs(self):
        # #1069 repro step 2: the same explicit 0/1/2 call on a list already at
        # 0/1/2. Each paragraph gets exactly its requested tab count (none for
        # level 0), never its current level added on top, and the reset runs
        # first, so the result is 0/1/2 again.
        tools = self._setup()
        doc = self._doc(
            [
                (1, 6, "One\n", {"listId": "L1"}),
                (6, 11, "Two\n", {"listId": "L1", "nestingLevel": 1}),
                (11, 17, "Three\n", {"listId": "L1", "nestingLevel": 2}),
            ],
            lists={"L1": self._numbered_list_entry(3)},
        )
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 6, "nesting_level": 0},
                {"start_index": 6, "end_index": 11, "nesting_level": 1},
                {"start_index": 11, "end_index": 17, "nesting_level": 2},
            ],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        kinds = [next(iter(r)) for r in reqs]
        assert kinds == [
            "deleteParagraphBullets",
            "updateParagraphStyle",
            "insertText",
            "insertText",
            "createParagraphBullets",
        ]
        assert reqs[2]["insertText"] == {"location": {"index": 11}, "text": "\t\t"}
        assert reqs[3]["insertText"] == {"location": {"index": 6}, "text": "\t"}
        create = reqs[4]["createParagraphBullets"]
        assert create["range"] == {"startIndex": 1, "endIndex": 20}
        assert create["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"

    async def test_each_run_gets_its_own_indent_reset(self):
        # Two separate runs: each one's reset covers exactly its own span and
        # comes right after its own delete, before that run's tab inserts.
        tools = self._setup()
        doc = self._doc(
            [
                (1, 6, "First\n", None),
                (20, 26, "Second\n", None),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 6, "nesting_level": 1},
                {"start_index": 20, "end_index": 26, "nesting_level": 1},
            ],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        resets = [i for i, r in enumerate(reqs) if "updateParagraphStyle" in r]
        assert len(resets) == 2
        for i, (start, end) in zip(resets, [(20, 26), (1, 6)], strict=True):
            assert reqs[i - 1]["deleteParagraphBullets"]["range"] == {
                "startIndex": start,
                "endIndex": end,
            }
            assert reqs[i]["updateParagraphStyle"]["range"] == {
                "startIndex": start,
                "endIndex": end,
            }
            assert "insertText" in reqs[i + 1]

    async def test_does_not_expand_across_different_list_id(self):
        # A directly-adjacent paragraph belonging to a DIFFERENT list must
        # not be pulled into the run.
        tools = self._setup()
        doc = self._doc(
            [
                (1, 6, "Target\n", {"listId": "L1"}),
                (6, 12, "Other\n", {"listId": "L2"}),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 6, "nesting_level": 1}],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        delete_req = next(
            r["deleteParagraphBullets"] for r in reqs if "deleteParagraphBullets" in r
        )
        assert delete_req["range"] == {"startIndex": 1, "endIndex": 6}

    async def test_multiple_runs_applied_in_descending_position_order(self):
        # Two non-adjacent single-paragraph targets become two separate
        # runs; higher-position run's requests must be emitted first so an
        # earlier tab insertion never shifts a not-yet-processed run's
        # indices.
        tools = self._setup()
        doc = self._doc(
            [
                (1, 6, "First\n", None),
                (20, 26, "Second\n", None),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 6, "nesting_level": 1},
                {"start_index": 20, "end_index": 26, "nesting_level": 1},
            ],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        insert_indices = [r["insertText"]["location"]["index"] for r in reqs if "insertText" in r]
        # Each run is all-nesting_level>0, so each emits a tab insert plus a
        # 0-tab anchor newline insert (#713), both at the run start. The
        # higher-position run (20) is still fully emitted before the lower
        # one (1) so an earlier tab/anchor insert never shifts a
        # not-yet-processed run's indices.
        assert insert_indices == [20, 20, 1, 1]

    async def test_omitted_preset_preserves_existing_numbered_list(self):
        # #334 round 2's core fix: repairing part of an existing NUMBERED
        # list without passing bullet_preset must NOT silently convert the
        # whole (expanded) run to the tool's own default bullet preset —
        # confirmed live this happened before the fix (Playwright-caught).
        tools = self._setup()
        bullet = {"listId": "L1"}
        doc = self._doc(
            [
                (1, 6, "One\n", bullet),
                (6, 11, "Two\n", bullet),
                (11, 17, "Three\n", bullet),
            ],
            lists={"L1": self._numbered_list_entry()},
        )
        mock_docs, ctx = self._mocks(doc)

        # Matches TC-DOC156's own documented call: no bullet_preset passed.
        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 6, "end_index": 11, "nesting_level": 1}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        create_req = next(
            r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r
        )
        assert create_req["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"

    async def test_omitted_preset_on_fresh_paragraph_defaults_to_bullet(self):
        # No existing list to infer from — falls back to the original default.
        tools = self._setup()
        doc = self._doc([(1, 6, "Item\n", None)])
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 6}],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        create_req = next(
            r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r
        )
        assert create_req["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"

    async def test_explicit_preset_overrides_inferred_one(self):
        # Explicit caller intent always wins over inference.
        tools = self._setup()
        bullet = {"listId": "L1"}
        doc = self._doc(
            [(1, 6, "One\n", bullet)],
            lists={"L1": self._numbered_list_entry()},
        )
        mock_docs, ctx = self._mocks(doc)

        await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {
                    "start_index": 1,
                    "end_index": 6,
                    "bullet_preset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            ],
            ctx=ctx,
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        create_req = next(
            r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r
        )
        assert create_req["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"

    async def test_adjacent_conflicting_explicit_presets_split_into_two_lists(self):
        # Two touching paragraphs with different explicit presets is a
        # legitimate request (two distinct lists side by side) — not an
        # error. A preset conflict only naturally breaks the run here since
        # both units are explicit and adjacent.
        tools = self._setup()
        doc = self._doc(
            [
                (1, 6, "One\n", None),
                (6, 11, "Two\n", None),
            ]
        )
        mock_docs, ctx = self._mocks(doc)

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 6, "bullet_preset": "BULLET_DISC_CIRCLE_SQUARE"},
                {
                    "start_index": 6,
                    "end_index": 11,
                    "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                },
            ],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        create_reqs = [r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r]
        assert len(create_reqs) == 2
        presets = {c["bulletPreset"] for c in create_reqs}
        assert presets == {"BULLET_DISC_CIRCLE_SQUARE", "NUMBERED_DECIMAL_ALPHA_ROMAN"}

    async def test_conflicting_presets_bridged_by_context_returns_error(self):
        # Two explicitly-conflicting requests that both expand (via a shared
        # same-listId neighbor) into ONE contiguous run — since the bridging
        # neighbor isn't itself explicit, the run-break check alone can't
        # separate them; the run-level conflict check must catch it.
        tools = self._setup()
        bullet = {"listId": "L1"}
        doc = self._doc(
            [
                (1, 6, "One\n", bullet),
                (6, 11, "Two\n", bullet),
                (11, 17, "Three\n", bullet),
            ]
        )
        _mock_docs, ctx = self._mocks(doc)

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123",
            ranges=[
                {"start_index": 1, "end_index": 6, "bullet_preset": "BULLET_DISC_CIRCLE_SQUARE"},
                {
                    "start_index": 11,
                    "end_index": 17,
                    "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                },
            ],
            ctx=ctx,
        )
        assert "error" in result

    async def _requests(self, doc, ranges):
        tools = self._setup()
        mock_docs, ctx = self._mocks(doc)
        result = await tools["create_paragraph_bullets"](doc_id="doc123", ranges=ranges, ctx=ctx)
        assert "error" not in result
        return mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]

    @staticmethod
    def _indents(first_line, start, border=False):
        style = {
            "indentFirstLine": {"magnitude": first_line, "unit": "PT"},
            "indentStart": {"magnitude": start, "unit": "PT"},
        }
        if border:
            style["borderLeft"] = {"width": {"magnitude": 3, "unit": "PT"}}
        return style

    def _nested_other_type_doc(self):
        # #1288's repro as the converter writes it (confirmed live): `1. A` /
        # `- a1` / `2. B` / `3. C` is one numbered list (L1) with a bullet list
        # (L2) inside A.
        return self._doc(
            [
                (1, 3, "A\n", {"listId": "L1"}),
                (3, 6, "a1\n", {"listId": "L2", "nestingLevel": 1}),
                (6, 8, "B\n", {"listId": "L1"}),
                (8, 10, "C\n", {"listId": "L1"}),
            ],
            lists={"L1": self._numbered_list_entry(2), "L2": self._bullet_list_entry(2)},
        )

    @pytest.mark.parametrize("target", [(6, 8), (1, 3), (8, 10)])
    async def test_run_continues_past_a_nested_list_of_the_other_type(self, target):
        # #1288: re-bulleting any item of L1 covers the whole list, a1 included,
        # in one numbered call (so B and C keep counting from A), then takes a1
        # back out with its own bullet preset behind a barrier.
        reqs = await self._requests(
            self._nested_other_type_doc(),
            [{"start_index": target[0], "end_index": target[1]}],
        )
        creates = [r["createParagraphBullets"] for r in reqs if "createParagraphBullets" in r]
        # A's list: 1..10 plus a1's one tab; then a1's: the anchor (after the
        # barrier, at 4) through a1 (3..6 plus its tab, two places on).
        assert creates == [
            {
                "range": {"startIndex": 1, "endIndex": 11},
                "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
            },
            {
                "range": {"startIndex": 4, "endIndex": 9},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            },
        ]
        main = reqs.index({"createParagraphBullets": creates[0]})
        assert reqs[main + 1 :] == [
            {"deleteParagraphBullets": {"range": {"startIndex": 3, "endIndex": 6}}},
            _zero_indent(3, 6),
            {"insertText": {"location": {"index": 3}, "text": "\t"}},
            {"insertText": {"location": {"index": 3}, "text": "\n\n"}},
            {"createParagraphBullets": creates[1]},
            {"deleteContentRange": {"range": {"startIndex": 3, "endIndex": 5}}},
        ]

    async def test_nested_list_inside_a_nested_list_goes_out_after_its_parent(self):
        # A sublist (L3) inside a1's list (L2) inside A: L2's span covers L3's
        # item too, then L3's own span takes it back out.
        doc = self._doc(
            [
                (1, 3, "A\n", {"listId": "L1"}),
                (3, 6, "a1\n", {"listId": "L2", "nestingLevel": 1}),
                (6, 9, "x1\n", {"listId": "L3", "nestingLevel": 2}),
                (9, 12, "a2\n", {"listId": "L2", "nestingLevel": 1}),
                (12, 14, "B\n", {"listId": "L1"}),
            ],
            lists={
                "L1": self._numbered_list_entry(3),
                "L2": self._bullet_list_entry(3),
                "L3": self._numbered_list_entry(3),
            },
        )
        reqs = await self._requests(doc, [{"start_index": 12, "end_index": 14}])
        deletes = [
            r["deleteParagraphBullets"]["range"] for r in reqs if "deleteParagraphBullets" in r
        ]
        assert deletes == [
            {"startIndex": 1, "endIndex": 14},
            {"startIndex": 3, "endIndex": 12},
            {"startIndex": 6, "endIndex": 9},
        ]
        presets = [
            r["createParagraphBullets"]["bulletPreset"]
            for r in reqs
            if "createParagraphBullets" in r
        ]
        assert presets == [
            "NUMBERED_DECIMAL_ALPHA_ROMAN",
            "BULLET_DISC_CIRCLE_SQUARE",
            "NUMBERED_DECIMAL_ALPHA_ROMAN",
        ]

    @pytest.mark.parametrize(
        "between",
        [
            # Another list at the item's own level isn't inside it.
            (3, 6, "o1\n", {"listId": "L2"}),
            # Nor is an unlisted paragraph at the margin.
            (3, 6, "p1\n", None),
            # Nor one indented past the item's text.
            (3, 6, "p1\n", None, {"indentStart": {"magnitude": 72, "unit": "PT"}}),
        ],
    )
    async def test_run_stops_at_a_paragraph_not_inside_the_item(self, between):
        doc = self._doc(
            [
                (1, 3, "A\n", {"listId": "L1"}),
                between,
                (6, 8, "B\n", {"listId": "L1"}),
            ]
        )
        reqs = await self._requests(doc, [{"start_index": 6, "end_index": 8}])
        assert reqs[0] == {"deleteParagraphBullets": {"range": {"startIndex": 6, "endIndex": 8}}}

    def _block_doc(self, block_text="inside A\n"):
        # A block inside item A (#1094): unlisted, both lines at A's text indent.
        return self._doc(
            [
                (1, 3, "A\n", {"listId": "L1"}),
                (3, 12, block_text, None, self._indents(36, 36)),
                (12, 14, "B\n", {"listId": "L1"}),
            ],
            lists={"L1": self._numbered_list_entry()},
        )

    async def test_run_continues_past_a_block_inside_an_item(self):
        # Docs numbers B past the block, so the run takes it in and gives it
        # back: its bullet removed and its own indents restored, last.
        reqs = await self._requests(self._block_doc(), [{"start_index": 12, "end_index": 14}])
        assert reqs[0] == {"deleteParagraphBullets": {"range": {"startIndex": 1, "endIndex": 14}}}
        assert reqs[-2:] == [
            {"deleteParagraphBullets": {"range": {"startIndex": 3, "endIndex": 12}}},
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 3, "endIndex": 12},
                    "paragraphStyle": self._indents(36, 36),
                    "fields": "indentStart,indentFirstLine",
                }
            },
        ]

    async def test_block_opening_with_a_tab_stops_the_run(self):
        # createParagraphBullets would consume its tab as depth.
        reqs = await self._requests(
            self._block_doc("\tinside A\n"), [{"start_index": 12, "end_index": 14}]
        )
        assert reqs[0] == {"deleteParagraphBullets": {"range": {"startIndex": 12, "endIndex": 14}}}

    async def test_run_after_a_list_item_gets_a_barrier_at_level_zero(self):
        # #1297 (option B, maintainer 2026-11-01): createParagraphBullets joins a
        # range to the same-preset list just before it, so a level-0 span after
        # a list item goes through the anchor wrap with a barrier and starts
        # its own list.
        doc = self._doc(
            [
                (1, 9, "Dot one\n", {"listId": "L1"}),
                (9, 19, "Paren one\n", {"listId": "L2"}),
            ],
            lists={"L1": self._numbered_list_entry(), "L2": self._numbered_list_entry()},
        )
        reqs = await self._requests(doc, [{"start_index": 9, "end_index": 19}])
        assert reqs[2:] == [
            {"insertText": {"location": {"index": 9}, "text": "\n\n"}},
            {
                "createParagraphBullets": {
                    "range": {"startIndex": 10, "endIndex": 21},
                    "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                }
            },
            {"deleteContentRange": {"range": {"startIndex": 9, "endIndex": 11}}},
        ]

    async def test_nested_run_after_a_list_item_gets_a_barrier(self):
        # #1297's repro: Z bulleted at level 1 right after P's list.
        doc = self._doc(
            [
                (1, 3, "P\n", {"listId": "L1"}),
                (3, 5, "a\n", {"listId": "L1", "nestingLevel": 1}),
                (5, 7, "Z\n", None),
            ],
            lists={"L1": self._numbered_list_entry(2)},
        )
        reqs = await self._requests(
            doc,
            [
                {
                    "start_index": 5,
                    "end_index": 7,
                    "nesting_level": 1,
                    "bullet_preset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                }
            ],
        )
        assert reqs[2:] == [
            {"insertText": {"location": {"index": 5}, "text": "\t"}},
            {"insertText": {"location": {"index": 5}, "text": "\n\n"}},
            {
                "createParagraphBullets": {
                    "range": {"startIndex": 6, "endIndex": 10},
                    "bulletPreset": "NUMBERED_DECIMAL_ALPHA_ROMAN",
                }
            },
            {"deleteContentRange": {"range": {"startIndex": 5, "endIndex": 7}}},
        ]

    async def test_quoted_items_keep_their_quote_indent(self):
        # #1090's repro: a quoted level-0/1/0 list re-bulleted from its first
        # item. Each item gets its level's indents plus 36pt for the quote,
        # after the bullet call, leaving its border alone.
        quoted = {"listId": "L1"}
        doc = self._doc(
            [
                (1, 17, "Quoted item one\n", quoted, self._indents(54, 72, border=True)),
                (
                    17,
                    31,
                    "Quoted nested\n",
                    {"listId": "L1", "nestingLevel": 1},
                    self._indents(90, 108, border=True),
                ),
                (31, 47, "Quoted item two\n", quoted, self._indents(54, 72, border=True)),
            ]
        )
        reqs = await self._requests(doc, [{"start_index": 1, "end_index": 17}])
        create = next(i for i, r in enumerate(reqs) if "createParagraphBullets" in r)
        restores = reqs[create + 1 :]
        assert [r["updateParagraphStyle"]["range"] for r in restores] == [
            {"startIndex": 1, "endIndex": 17},
            {"startIndex": 17, "endIndex": 31},
            {"startIndex": 31, "endIndex": 47},
        ]
        assert [r["updateParagraphStyle"]["paragraphStyle"] for r in restores] == [
            self._indents(54, 72),
            self._indents(90, 108),
            self._indents(54, 72),
        ]
        assert all(
            r["updateParagraphStyle"]["fields"] == "indentStart,indentFirstLine" for r in restores
        )

    async def test_quoted_plain_paragraph_keeps_its_quote_indent(self):
        doc = self._doc([(1, 14, "Quoted plain\n", None, self._indents(36, 36, border=True))])
        reqs = await self._requests(doc, [{"start_index": 1, "end_index": 14}])
        assert reqs[-1]["updateParagraphStyle"]["paragraphStyle"] == self._indents(54, 72)

    async def test_unquoted_item_gets_no_indent_restore(self):
        doc = self._doc([(1, 6, "Item\n", {"listId": "L1"}, self._indents(18, 36))])
        reqs = await self._requests(doc, [{"start_index": 1, "end_index": 6}])
        assert "createParagraphBullets" in reqs[-1]

    async def test_get_doc_error_returns_error_dict(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.side_effect = Exception("boom")
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123", ranges=[{"start_index": 1, "end_index": 5}], ctx=ctx
        )
        assert result == {"error": "boom"}

    async def test_docs_api_error_returns_error_dict(self):
        tools = self._setup()
        doc = self._doc([(1, 6, "Item\n", None)])
        mock_docs, ctx = self._mocks(doc)
        mock_docs.documents().batchUpdate().execute.side_effect = Exception("boom")

        result = await tools["create_paragraph_bullets"](
            doc_id="doc123", ranges=[{"start_index": 1, "end_index": 6}], ctx=ctx
        )
        assert result == {"error": "boom"}


class TestDeleteParagraphBulletsTool:
    def _setup(self):
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        return tools

    async def test_empty_ranges_returns_error(self):
        tools = self._setup()
        ctx = _make_ctx(docs_service=MagicMock(), doc_cache=MagicMock())
        result = await tools["delete_paragraph_bullets"](doc_id="doc123", ranges=[], ctx=ctx)
        assert "error" in result

    async def test_quoted_item_keeps_its_quote_indent(self):
        # #1090 (Kit's evidence): deleteParagraphBullets sets both indents to
        # 36pt per level whatever the quote added (confirmed live), so each
        # quoted item in range gets its quote's 36pt back on top. An unquoted
        # one, and a quoted one outside the range, get nothing.
        def para(start, end, level, border):
            style = {"indentStart": {"magnitude": 72, "unit": "PT"}}
            if border:
                style["borderLeft"] = {"width": {"magnitude": 3, "unit": "PT"}}
            return {
                "startIndex": start,
                "endIndex": end,
                "paragraph": {
                    "elements": [{"textRun": {"content": "x\n"}}],
                    "bullet": {"listId": "L1", "nestingLevel": level},
                    "paragraphStyle": style,
                },
            }

        doc = {
            "body": {
                "content": [
                    para(1, 5, 0, True),
                    para(5, 9, 1, True),
                    para(9, 13, 0, False),
                    para(13, 17, 0, True),
                ]
            }
        }
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = doc
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["delete_paragraph_bullets"](
            doc_id="doc123", ranges=[{"start_index": 1, "end_index": 13}], ctx=ctx
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert reqs[1:] == [
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {
                        "indentStart": {"magnitude": indent, "unit": "PT"},
                        "indentFirstLine": {"magnitude": indent, "unit": "PT"},
                    },
                    "fields": "indentStart,indentFirstLine",
                }
            }
            for start, end, indent in [(1, 5, 36), (5, 9, 72)]
        ]

    async def test_sends_one_request_per_range(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {"body": {"content": []}}
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["delete_paragraph_bullets"](
            doc_id="doc123",
            ranges=[{"start_index": 1, "end_index": 5}, {"start_index": 10, "end_index": 15}],
            ctx=ctx,
        )
        assert "error" not in result
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        assert len(reqs) == 2
        assert reqs[0]["deleteParagraphBullets"]["range"] == {"startIndex": 1, "endIndex": 5}
        assert reqs[1]["deleteParagraphBullets"]["range"] == {"startIndex": 10, "endIndex": 15}

    async def test_docs_api_error_returns_error_dict(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.side_effect = Exception("boom")
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["delete_paragraph_bullets"](
            doc_id="doc123", ranges=[{"start_index": 1, "end_index": 5}], ctx=ctx
        )
        assert result == {"error": "boom"}


class TestStyleDocTableCellsTool:
    def _setup(self):
        tool, tools = _make_tool_registry()
        docs_module.register(tool)
        return tools

    async def _call(self, cells):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        result = await tools["style_doc_table_cells"](
            doc_id="doc123",
            table_start_index=5,
            cells=cells,
            ctx=ctx,
        )
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        style = reqs[0]["updateTableCellStyle"]["tableCellStyle"]
        fields = reqs[0]["updateTableCellStyle"]["fields"].split(",")
        return result, style, fields

    async def test_uniform_border_still_applies_to_all_sides(self):
        # Backward compatibility: border_color/width/dash_style alone, no per-edge keys.
        result, style, fields = await self._call(
            [
                {
                    "row_index": 0,
                    "column_index": 0,
                    "border_color": {"red": 0, "green": 0, "blue": 0},
                    "border_width": 0.5,
                }
            ]
        )
        assert "error" not in result
        for side in ("borderTop", "borderRight", "borderBottom", "borderLeft"):
            assert side in fields
            assert style[side]["color"]["color"]["rgbColor"] == {
                "red": 0,
                "green": 0,
                "blue": 0,
            }
            assert style[side]["width"] == {"magnitude": 0.5, "unit": "PT"}

    async def test_border_bottom_only_sets_single_edge(self):
        # The signature-line use case from #403: only one edge should be touched.
        result, style, fields = await self._call(
            [
                {
                    "row_index": 0,
                    "column_index": 0,
                    "border_bottom": {"color": {"red": 0, "green": 0, "blue": 0}, "width": 1.0},
                }
            ]
        )
        assert "error" not in result
        assert fields == ["borderBottom"]
        assert "borderTop" not in style
        assert "borderRight" not in style
        assert "borderLeft" not in style
        assert style["borderBottom"]["color"]["color"]["rgbColor"] == {
            "red": 0,
            "green": 0,
            "blue": 0,
        }
        assert style["borderBottom"]["width"] == {"magnitude": 1.0, "unit": "PT"}

    async def test_per_edge_overrides_uniform_other_edges_keep_uniform(self):
        result, style, fields = await self._call(
            [
                {
                    "row_index": 0,
                    "column_index": 0,
                    "border_color": {"red": 0, "green": 0, "blue": 0},
                    "border_width": 0.5,
                    "border_bottom": {
                        "color": {"red": 1, "green": 0, "blue": 0},
                        "width": 2.0,
                    },
                }
            ]
        )
        assert "error" not in result
        assert set(fields) == {"borderTop", "borderRight", "borderBottom", "borderLeft"}
        assert style["borderBottom"]["color"]["color"]["rgbColor"] == {
            "red": 1,
            "green": 0,
            "blue": 0,
        }
        assert style["borderBottom"]["width"] == {"magnitude": 2.0, "unit": "PT"}
        for side in ("borderTop", "borderRight", "borderLeft"):
            assert style[side]["color"]["color"]["rgbColor"] == {
                "red": 0,
                "green": 0,
                "blue": 0,
            }
            assert style[side]["width"] == {"magnitude": 0.5, "unit": "PT"}

    async def test_edge_override_width_only_inherits_uniform_color(self):
        # #403 QA follow-up: confirmed live that the Docs API rejects a border
        # request with non-zero width and no color as "transparent" (400 error).
        # A width-only per-edge override must inherit color from the uniform spec.
        result, style, _fields = await self._call(
            [
                {
                    "row_index": 0,
                    "column_index": 0,
                    "border_color": {"red": 0, "green": 0, "blue": 0},
                    "border_width": 0.5,
                    "border_bottom": {"width": 2.0},
                }
            ]
        )
        assert "error" not in result
        assert style["borderBottom"]["color"]["color"]["rgbColor"] == {
            "red": 0,
            "green": 0,
            "blue": 0,
        }
        assert style["borderBottom"]["width"] == {"magnitude": 2.0, "unit": "PT"}

    async def test_empty_cells_list_returns_error(self):
        tools = self._setup()
        ctx = _make_ctx(docs_service=MagicMock(), doc_cache=MagicMock())
        result = await tools["style_doc_table_cells"](
            doc_id="doc123", table_start_index=5, cells=[], ctx=ctx
        )
        assert "error" in result

    async def test_non_dict_border_edge_returns_clean_error(self):
        # #462 QA send-back: a non-dict border_bottom (e.g. None) must not raise
        # an uncaught TypeError from the "color" in edge_spec membership check.
        tools = self._setup()
        ctx = _make_ctx(docs_service=MagicMock(), doc_cache=MagicMock())
        result = await tools["style_doc_table_cells"](
            doc_id="doc123",
            table_start_index=5,
            cells=[{"row_index": 0, "column_index": 0, "border_bottom": None}],
            ctx=ctx,
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# apply_theme / get_doc_theme tools
# ---------------------------------------------------------------------------


class TestGetDocThemeSource:
    """get_doc_theme(source=) replaces get_doc_named_styles (#1527)."""

    _DOC: ClassVar[dict] = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "elements": [
                            {
                                "textRun": {
                                    "content": "Title\n",
                                    "textStyle": {"weightedFontFamily": {"fontFamily": "Georgia"}},
                                }
                            }
                        ],
                    }
                }
            ]
        },
        "namedStyles": {
            "styles": [
                {
                    "namedStyleType": "HEADING_1",
                    "textStyle": {"weightedFontFamily": {"fontFamily": "Lora"}},
                }
            ]
        },
    }

    def _tools(self):
        tool, captured = _make_tool_registry()
        annotations = {}

        def recording_tool(**kwargs):
            def decorator(func):
                annotations[func.__name__] = kwargs.get("annotations")
                return tool(**kwargs)(func)

            return decorator

        docs_module.register(recording_tool)
        return captured, annotations

    async def _theme(self, name, **kwargs):
        captured, _ = self._tools()
        docs = MagicMock()
        docs.documents.return_value.get.return_value.execute.return_value = self._DOC
        ctx = _make_ctx(docs_service=docs, doc_cache=MagicMock())
        return await captured[name](doc_id="doc1", ctx=ctx, **kwargs)

    async def test_body_is_the_default(self):
        assert await self._theme("get_doc_theme") == _read_body_styles(self._DOC)

    async def test_named_styles_matches_the_deprecated_tool(self):
        result = await self._theme("get_doc_theme", source="named_styles")
        assert result == await self._theme("get_doc_named_styles")
        assert result == {"HEADING_1": {"font_family": "Lora"}}

    async def test_both_returns_the_two_side_by_side(self):
        result = await self._theme("get_doc_theme", source="both")
        assert result == {
            "body": _read_body_styles(self._DOC),
            "named_styles": _read_named_styles(self._DOC),
        }
        assert result["body"]["HEADING_1"]["font_family"] == "Georgia"

    async def test_unknown_source_is_an_error(self):
        result = await self._theme("get_doc_theme", source="theme")
        assert "source must be" in result["error"]

    def test_both_are_read_only(self):
        _, annotations = self._tools()
        assert annotations["get_doc_theme"].read_only_hint is True
        assert annotations["get_doc_named_styles"].read_only_hint is True


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

    async def test_apply_theme_table_border_bottom_only(self):
        # #403: per-edge border override on the table theme's border styling.
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "body": {"content": [{"table": {"rows": 1, "columns": 2}, "startIndex": 5}]}
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
            doc_id="doc123",
            theme={
                "table": {
                    "border_bottom": {"color": {"red": 0, "green": 0, "blue": 0}, "width": 1.0}
                }
            },
            ctx=ctx,
        )
        assert "error" not in result
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        cell_reqs = [r["updateTableCellStyle"] for r in reqs if "updateTableCellStyle" in r]
        assert len(cell_reqs) == 1
        style = cell_reqs[0]["tableCellStyle"]
        fields = cell_reqs[0]["fields"].split(",")
        assert fields == ["borderBottom"]
        assert "borderTop" not in style
        assert style["borderBottom"]["width"] == {"magnitude": 1.0, "unit": "PT"}

    async def test_apply_theme_table_border_per_edge_overrides_uniform(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "body": {"content": [{"table": {"rows": 1, "columns": 2}, "startIndex": 5}]}
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
            doc_id="doc123",
            theme={
                "table": {
                    "border_width": 0.5,
                    "border_bottom": {"width": 2.0},
                }
            },
            ctx=ctx,
        )
        assert "error" not in result
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        style = next(
            r["updateTableCellStyle"]["tableCellStyle"] for r in reqs if "updateTableCellStyle" in r
        )
        assert style["borderBottom"]["width"] == {"magnitude": 2.0, "unit": "PT"}
        assert style["borderTop"]["width"] == {"magnitude": 0.5, "unit": "PT"}

    async def test_apply_theme_table_edge_width_only_inherits_uniform_color(self):
        # #403 QA follow-up: confirmed live that the Docs API rejects a border
        # request with non-zero width and no color as "transparent" (400 error).
        # A width-only per-edge override must inherit color from the uniform spec.
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "body": {"content": [{"table": {"rows": 1, "columns": 2}, "startIndex": 5}]}
        }
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
            doc_id="doc123",
            theme={
                "table": {
                    "border_color": {"red": 0, "green": 0, "blue": 0},
                    "border_width": 0.5,
                    "border_bottom": {"width": 2.0},
                }
            },
            ctx=ctx,
        )
        assert "error" not in result
        call_kwargs = mock_docs.documents().batchUpdate.call_args[1]
        reqs = call_kwargs["body"]["requests"]
        style = next(
            r["updateTableCellStyle"]["tableCellStyle"] for r in reqs if "updateTableCellStyle" in r
        )
        assert style["borderBottom"]["color"]["color"]["rgbColor"] == {
            "red": 0,
            "green": 0,
            "blue": 0,
        }
        assert style["borderBottom"]["width"] == {"magnitude": 2.0, "unit": "PT"}

    async def test_apply_theme_table_non_dict_border_edge_returns_clean_error(self):
        # #462 QA send-back: same non-dict-edge gap as style_doc_table_cells, here
        # in apply_theme's table styling per-edge override.
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = {
            "body": {"content": [{"table": {"rows": 1, "columns": 2}, "startIndex": 5}]}
        }
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())

        result = await tools["apply_theme"](
            doc_id="doc123",
            theme={"table": {"border_bottom": None}},
            ctx=ctx,
        )
        assert "error" in result

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

    @pytest.mark.parametrize(
        "paragraph_style, own",
        [
            ({"spaceAbove": {"unit": "PT"}, "spaceBelow": {"unit": "PT"}}, set()),
            ({"spaceBelow": {"magnitude": 6, "unit": "PT"}}, {"spaceBelow"}),
            ({"spaceAbove": {"magnitude": 12, "unit": "PT"}}, {"spaceAbove"}),
        ],
    )
    def test_own_paragraph_spacing_fields_reads_normal_text(self, paragraph_style, own):
        doc = {
            "namedStyles": {
                "styles": [
                    {
                        "namedStyleType": "HEADING_1",
                        "paragraphStyle": {"spaceAbove": {"magnitude": 20, "unit": "PT"}},
                    },
                    {"namedStyleType": "NORMAL_TEXT", "paragraphStyle": paragraph_style},
                ]
            }
        }
        assert _own_paragraph_spacing_fields(doc) == own

    @staticmethod
    def _body_paragraph(style, text, font=None):
        text_style = {"weightedFontFamily": {"fontFamily": font}} if font else {}
        return {
            "paragraph": {
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT", **style},
                "elements": [{"textRun": {"content": text, "textStyle": text_style}}],
            }
        }

    def test_unstyled_first_paragraph_decides_over_a_later_bold_lead_in(self):
        """One run's bold isn't the doc's body text (PR #1388 QA round 3)."""
        lead_in = self._body_paragraph({}, "Lead-in.")
        lead_in["paragraph"]["elements"] = [
            {"textRun": {"content": "Lead-in.", "textStyle": {"bold": True}}},
            {"textRun": {"content": " The rest.\n", "textStyle": {}}},
        ]
        doc = {"body": {"content": [self._body_paragraph({}, "plain\n"), lead_in]}}
        assert _read_body_styles(doc) == {}

    def test_opening_bold_or_code_run_is_not_the_paragraphs_style(self):
        para = self._body_paragraph({}, "x")
        para["paragraph"]["elements"] = [
            {
                "textRun": {
                    "content": "pip",
                    "textStyle": {
                        "bold": True,
                        "weightedFontFamily": {"fontFamily": "Courier New"},
                        "fontSize": {"magnitude": 12, "unit": "PT"},
                    },
                }
            },
            {
                "textRun": {
                    "content": " fails\n",
                    "textStyle": {"fontSize": {"magnitude": 12, "unit": "PT"}},
                }
            },
        ]
        assert _read_body_styles({"body": {"content": [para]}})["NORMAL_TEXT"] == {"font_size": 12}

    def test_first_heading_decides_for_its_style_too(self):
        def heading(text_style):
            return {
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "elements": [{"textRun": {"content": "h\n", "textStyle": text_style}}],
                }
            }

        doc = {"body": {"content": [heading({}), heading({"italic": True})]}}
        assert _read_body_styles(doc) == {}

    def test_body_theme_reads_a_doc_set_in_courier(self):
        """Courier New alone isn't a code block (PR #1388 QA round 2)."""
        doc = {
            "body": {
                "content": [
                    self._body_paragraph({}, "one\n", font="Courier New"),
                    self._body_paragraph({}, "two\n", font="Courier New"),
                ]
            }
        }
        assert _read_body_styles(doc)["NORMAL_TEXT"] == {"font_family": "Courier New"}

    def test_body_theme_skips_a_code_block_for_body_text(self):
        spacing = {
            "spaceAbove": {"magnitude": 8, "unit": "PT"},
            "spaceBelow": {"magnitude": 8, "unit": "PT"},
        }
        doc = {
            "body": {
                "content": [
                    self._body_paragraph(spacing, "code\n", font="Courier New"),
                    self._body_paragraph({}, "body\n", font="Georgia"),
                ]
            }
        }
        assert _read_body_styles(doc)["NORMAL_TEXT"] == {"font_family": "Georgia"}

    def test_unstyled_body_text_keeps_a_block_out_of_the_theme(self):
        spacing = {
            "spaceAbove": {"magnitude": 8, "unit": "PT"},
            "spaceBelow": {"magnitude": 8, "unit": "PT"},
        }
        doc = {
            "body": {
                "content": [
                    self._body_paragraph({}, "body\n"),
                    self._body_paragraph(spacing, "code\n", font="Courier New"),
                ]
            }
        }
        assert "NORMAL_TEXT" not in _read_body_styles(doc)

    def test_doc_of_blocks_only_keeps_the_font_but_not_their_spacing(self):
        doc = {
            "body": {
                "content": [
                    self._body_paragraph(
                        {
                            "borderLeft": {"width": {"magnitude": 3, "unit": "PT"}},
                            "spaceAbove": {"magnitude": 8, "unit": "PT"},
                        },
                        "quote\n",
                        font="Georgia",
                    )
                ]
            }
        }
        assert _read_body_styles(doc)["NORMAL_TEXT"] == {"font_family": "Georgia"}

    @pytest.mark.parametrize("key", ["spaceAbove", "spaceBelow"])
    def test_body_theme_leaves_out_spacing_beside_a_quoted_table(self, key):
        """That paragraph has the quote's 8pt and no border (PR #1388 QA round 2)."""
        doc = {
            "body": {
                "content": [self._body_paragraph({key: {"magnitude": 8, "unit": "PT"}}, "next\n")]
            }
        }
        assert "NORMAL_TEXT" not in _read_body_styles(doc)

    def test_body_theme_keeps_a_heading_at_the_block_spacing(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "paragraphStyle": {
                                "namedStyleType": "HEADING_2",
                                "spaceAbove": {"magnitude": 8, "unit": "PT"},
                            },
                            "elements": [],
                        }
                    }
                ]
            }
        }
        assert _read_body_styles(doc)["HEADING_2"] == {"space_above": 8}

    def test_body_theme_leaves_out_the_paragraph_gap_and_block_spacing(self):
        """A theme carrying them would space a whole doc (PR #1388 QA round 1)."""
        theme = _read_body_styles(self._paragraph_gap_doc())
        assert "NORMAL_TEXT" not in theme
        # A heading at the same value is that heading's own style.
        assert theme["HEADING_1"]["space_below"] == 10

    @pytest.mark.parametrize(
        "block_style, runs",
        [
            ({"borderLeft": {"width": {"magnitude": 3, "unit": "PT"}}}, ["quote\n"]),
            ({"borderBottom": {"width": {"magnitude": 1, "unit": "PT"}}}, ["\n"]),
            ({}, ["\n"]),
        ],
        ids=["quote", "rule", "empty"],
    )
    def test_body_theme_skips_a_block_for_the_first_body_text(self, block_style, runs):
        def paragraph(style, text):
            return {
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT", **style},
                    "elements": [{"textRun": {"content": text, "textStyle": {}}}],
                }
            }

        spacing = {"spaceAbove": {"magnitude": 8, "unit": "PT"}}
        doc = {
            "body": {
                "content": [
                    paragraph({**spacing, **block_style}, runs[0]),
                    paragraph({"spaceBelow": {"magnitude": 4, "unit": "PT"}}, "body\n"),
                ]
            }
        }
        assert _read_body_styles(doc)["NORMAL_TEXT"] == {"space_below": 4}

    def _collapsed_after_table_doc(self, *, body_before=None, font_size=None):
        """A heading, a final table, and text later added in the collapsed paragraph:
        the style _build_trailing_para_after_table_collapse leaves there, as the API
        returns it (a zero magnitude is omitted)."""
        collapsed = {"lineSpacing": 1, "spaceAbove": {"unit": "PT"}, "spaceBelow": {"unit": "PT"}}
        added = self._body_paragraph(collapsed, "added later\n", font="Georgia")
        if font_size is not None:
            text_style = added["paragraph"]["elements"][0]["textRun"]["textStyle"]
            text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
        heading = {
            "paragraph": {
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "elements": [{"textRun": {"content": "Title\n", "textStyle": {}}}],
            }
        }
        content = [heading, *([body_before] if body_before else []), {"table": {}}, added]
        return {"body": {"content": content}}

    def test_text_added_after_a_collapsed_final_table_gives_no_collapse_spacing(self):
        """Its 1% line spacing as a theme overprints every body line (#1440). With no
        other body text, it still gives its font."""
        theme = _read_body_styles(self._collapsed_after_table_doc())
        assert theme["NORMAL_TEXT"] == {"font_family": "Georgia"}

    def test_a_block_before_the_table_decides_over_collapsed_text(self):
        """Both are blocks; the first with text gives the fallback, as before."""
        quote = self._body_paragraph(
            {"borderLeft": {"width": {"magnitude": 3, "unit": "PT"}}}, "q\n", font="Arial"
        )
        theme = _read_body_styles(self._collapsed_after_table_doc(body_before=quote))
        assert theme["NORMAL_TEXT"] == {"font_family": "Arial"}

    def test_collapsed_paragraph_gives_no_one_point_font(self):
        """The collapse sets 1pt on a quote separator and the line before a table."""
        theme = _read_body_styles(self._collapsed_after_table_doc(font_size=1))
        assert theme["NORMAL_TEXT"] == {"font_family": "Georgia"}

    def test_collapsed_paragraph_keeps_a_real_font_size(self):
        theme = _read_body_styles(self._collapsed_after_table_doc(font_size=12))
        assert theme["NORMAL_TEXT"] == {"font_family": "Georgia", "font_size": 12}

    def test_heading_made_from_collapsed_text_gives_no_collapse_spacing(self):
        doc = self._collapsed_after_table_doc()
        doc["body"]["content"] = doc["body"]["content"][1:]  # drop the earlier heading
        doc["body"]["content"][-1]["paragraph"]["paragraphStyle"]["namedStyleType"] = "HEADING_2"
        assert _read_body_styles(doc) == {"HEADING_2": {"font_family": "Georgia"}}

    def test_collapsed_heading_doesnt_hide_a_later_real_heading(self):
        """Text after table A made a HEADING_2 keeps the collapse; the real HEADING_2
        after table B decides (PR #1647 QA round 1)."""
        doc = self._collapsed_after_table_doc()
        collapsed_heading = doc["body"]["content"][-1]
        collapsed_heading["paragraph"]["paragraphStyle"]["namedStyleType"] = "HEADING_2"
        real_heading = {
            "paragraph": {
                "paragraphStyle": {
                    "namedStyleType": "HEADING_2",
                    "spaceAbove": {"magnitude": 18, "unit": "PT"},
                },
                "elements": [{"textRun": {"content": "Real\n", "textStyle": {}}}],
            }
        }
        doc["body"]["content"] += [{"table": {}}, real_heading]
        assert _read_body_styles(doc)["HEADING_2"] == {"space_above": 18}

    def test_one_percent_line_spacing_with_real_spacing_is_still_read(self):
        """Only the whole collapse signature is the emitter's."""
        style = {"lineSpacing": 1, "spaceBelow": {"magnitude": 4, "unit": "PT"}}
        doc = {"body": {"content": [self._body_paragraph(style, "body\n")]}}
        assert _read_body_styles(doc)["NORMAL_TEXT"] == {"line_spacing": 1, "space_below": 4}

    @staticmethod
    def _paragraph_gap_doc():
        """A gap paragraph, one with a quote edge's 8pt, and a heading at the gap's value."""

        def paragraph(start, end, named_style, space_below):
            return {
                "startIndex": start,
                "endIndex": end,
                "paragraph": {
                    "paragraphStyle": {
                        "namedStyleType": named_style,
                        "spaceBelow": {"magnitude": space_below, "unit": "PT"},
                    },
                    "elements": [{"textRun": {"content": "x\n", "textStyle": {}}}],
                },
            }

        return {
            "body": {
                "content": [
                    {"endIndex": 1, "sectionBreak": {}},
                    paragraph(1, 3, "NORMAL_TEXT", 10),
                    paragraph(3, 5, "NORMAL_TEXT", 8),
                    paragraph(5, 7, "HEADING_1", 10),
                ]
            }
        }

    async def _run_theme(self, theme, **kwargs):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = self._paragraph_gap_doc()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        await tools["apply_theme"](doc_id="doc123", theme=theme, ctx=ctx, **kwargs)
        return mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]

    @pytest.mark.parametrize("key", ["space_above", "space_below"])
    async def test_theme_spacing_replaces_the_paragraph_gap(self, key):
        """#1382: a value on the paragraph would beat the theme's NORMAL_TEXT."""
        reqs = await self._run_theme({"NORMAL_TEXT": {key: 20}})
        assert [r for r in reqs if "updateParagraphStyle" in r] == [
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": 3},
                    "paragraphStyle": {},
                    "fields": "spaceBelow",
                }
            }
        ]

    @pytest.mark.parametrize(
        "theme",
        [{"NORMAL_TEXT": {"font_family": "Georgia"}}, {"HEADING_1": {"space_below": 20}}],
    )
    async def test_theme_without_body_spacing_leaves_the_doc_alone(self, theme):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        await tools["apply_theme"](doc_id="doc123", theme=theme, ctx=ctx)
        mock_docs.documents().get.assert_not_called()

    @staticmethod
    def _table_gap_doc():
        """As the emitter writes "a", "b", a table, "c", then "d" with a 10pt
        spaceAbove set by hand: a [1,3) and c [16,18) carry plain paragraph gaps below,
        b [3,5) the gap before the table's empty paragraph [5,6), c the gap after it."""

        def paragraph(start, text, **spacing):
            style: dict = {"namedStyleType": "NORMAL_TEXT"}
            style.update({k: {"magnitude": v, "unit": "PT"} for k, v in spacing.items()})
            return {
                "startIndex": start,
                "endIndex": start + len(text),
                "paragraph": {
                    "paragraphStyle": style,
                    "elements": [{"textRun": {"content": text}}],
                },
            }

        return {
            "body": {
                "content": [
                    paragraph(1, "a\n", spaceBelow=10),
                    paragraph(3, "b\n", spaceBelow=10),
                    paragraph(5, "\n", spaceAbove=0, spaceBelow=0),
                    {"startIndex": 6, "endIndex": 16, "table": {}},
                    paragraph(16, "c\n", spaceAbove=10, spaceBelow=10),
                    paragraph(18, "d\n", spaceAbove=10),
                ]
            }
        }

    @pytest.mark.parametrize(
        ("theme_fields", "cleared"),
        [
            # PR #1434 QA round 1: a theme spaced only below leaves the gap after the
            # table, or "c" would sit on it.
            ({"spaceBelow"}, {1: "spaceBelow", 3: "spaceBelow", 16: "spaceBelow"}),
            ({"spaceAbove"}, {1: "spaceBelow", 16: "spaceAbove,spaceBelow"}),
            (
                {"spaceAbove", "spaceBelow"},
                {1: "spaceBelow", 3: "spaceBelow", 16: "spaceAbove,spaceBelow"},
            ),
        ],
        ids=["below", "above", "both"],
    )
    def test_a_table_gap_is_cleared_only_for_the_themes_own_field(self, theme_fields, cleared):
        """#1427. The plain paragraph gaps go whatever the theme sets, as before, and
        "d"'s 10pt spaceAbove, which doesn't follow a table, is never the emitter's
        (PR #1434 QA round 1)."""
        requests = _clear_paragraph_gap_requests(self._table_gap_doc(), theme_fields)
        assert {
            r["updateParagraphStyle"]["range"]["startIndex"]: r["updateParagraphStyle"]["fields"]
            for r in requests
        } == cleared
        assert all(r["updateParagraphStyle"]["paragraphStyle"] == {} for r in requests)

    async def test_apply_theme_keeps_the_gap_after_a_table_for_a_below_only_theme(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = self._table_gap_doc()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        await tools["apply_theme"](
            doc_id="doc123", theme={"NORMAL_TEXT": {"space_below": 20}}, ctx=ctx
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        cleared = {
            r["updateParagraphStyle"]["range"]["startIndex"]: r["updateParagraphStyle"]["fields"]
            for r in reqs
            if "updateParagraphStyle" in r
        }
        assert cleared == {1: "spaceBelow", 3: "spaceBelow", 16: "spaceBelow"}

    async def test_an_explicit_zero_in_the_theme_counts_as_setting_the_field(self):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = self._table_gap_doc()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        await tools["apply_theme"](
            doc_id="doc123", theme={"NORMAL_TEXT": {"space_above": 0}}, ctx=ctx
        )
        reqs = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        fields = [
            r["updateParagraphStyle"]["fields"]
            for r in reqs
            if r.get("updateParagraphStyle", {}).get("range", {}).get("startIndex") == 16
        ]
        assert fields == ["spaceAbove,spaceBelow"]

    async def test_overwrite_spacing_lands_after_the_gap_is_cleared(self):
        reqs = await self._run_theme({"NORMAL_TEXT": {"space_below": 20}}, overwrite=True)
        styles = [
            r["updateParagraphStyle"]
            for r in reqs
            if r.get("updateParagraphStyle", {}).get("range", {}).get("startIndex") == 1
        ]
        assert styles[0]["paragraphStyle"] == {}
        assert styles[-1]["paragraphStyle"]["spaceBelow"]["magnitude"] == 20

    @staticmethod
    def _collapse_doc():
        """Body text; the 1pt collapsed line before a table; the table; the collapsed line
        after it (no font set); then, still collapsed, text a user typed there later, an
        image inserted there, and a line holding only a space."""
        collapsed = {"lineSpacing": 1, "spaceAbove": {"unit": "PT"}, "spaceBelow": {"unit": "PT"}}
        one_point = {"fontSize": {"magnitude": 1, "unit": "PT"}}

        def paragraph(start, end, text, style=None, text_style=None):
            return {
                "startIndex": start,
                "endIndex": end,
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT", **(style or {})},
                    "elements": [{"textRun": {"content": text, "textStyle": text_style or {}}}],
                },
            }

        image = paragraph(27, 29, "\n", collapsed)
        image["paragraph"]["elements"].insert(0, {"inlineObjectElement": {"inlineObjectId": "i"}})
        return {
            "body": {
                "content": [
                    paragraph(1, 6, "body\n"),
                    paragraph(6, 7, "\n", collapsed, one_point),
                    {"startIndex": 7, "endIndex": 20, "table": {}},
                    paragraph(20, 21, "\n", collapsed),
                    paragraph(21, 27, "typed\n", collapsed),
                    image,
                    paragraph(29, 31, " \n", collapsed),
                ]
            }
        }

    async def _overwrite_requests(self, theme):
        tools = self._setup()
        mock_docs = MagicMock()
        mock_docs.documents().get().execute.return_value = self._collapse_doc()
        mock_docs.documents().batchUpdate().execute.return_value = {}
        ctx = _make_ctx(docs_service=mock_docs, doc_cache=MagicMock())
        await tools["apply_theme"](doc_id="doc123", theme=theme, ctx=ctx, overwrite=True)
        requests = mock_docs.documents().batchUpdate.call_args[1]["body"]["requests"]
        by_start: dict[int, list[dict]] = {}
        for request in requests:
            for kind in ("updateParagraphStyle", "updateTextStyle"):
                if kind in request:
                    start = request[kind]["range"]["startIndex"]
                    by_start.setdefault(start, []).append({kind: request[kind]["fields"]})
        return by_start

    async def test_overwrite_keeps_an_empty_collapsed_paragraphs_collapse(self):
        """The theme's spacing would undo the collapse (PR #1647 QA round 1)."""
        theme = {
            "NORMAL_TEXT": {
                "line_spacing": 115,
                "space_above": 4,
                "space_below": 6,
                "font_family": "Georgia",
                "font_size": 11,
            }
        }
        by_start = await self._overwrite_requests(theme)
        both = [
            {"updateParagraphStyle": "lineSpacing,spaceAbove,spaceBelow"},
            {"updateTextStyle": "weightedFontFamily,fontSize"},
        ]
        assert by_start[1] == both
        # The 1pt line before the table keeps its spacing and its 1pt font.
        assert by_start[6] == [{"updateTextStyle": "weightedFontFamily"}]
        # The line after the final table keeps its spacing; it has the doc's font size.
        assert by_start[20] == [{"updateTextStyle": "weightedFontFamily,fontSize"}]
        # Text typed into it gets the theme's spacing back, as insert_doc_text does, and so
        # do an image and a line of whitespace: at 1% they overlap the table (PR #1647
        # QA round 2).
        assert by_start[21] == both
        assert by_start[27] == both
        assert by_start[29] == both

    async def test_overwrite_with_only_spacing_sends_nothing_for_a_collapsed_line(self):
        by_start = await self._overwrite_requests({"NORMAL_TEXT": {"line_spacing": 115}})
        assert set(by_start) == {1, 21, 27, 29}

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
