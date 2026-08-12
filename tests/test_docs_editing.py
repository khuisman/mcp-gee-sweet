"""Tests for docs editing tools — insert_page_break, insert_softbreak_paragraph."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module


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
# insert_page_break (#148)
# ---------------------------------------------------------------------------


class TestInsertPageBreak:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_page_break"](doc_id="doc1", index=5, ctx=ctx)
        assert result == {"docId": "doc1", "index": 5}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertPageBreak"]
        assert req["location"]["index"] == 5

    async def test_marks_doc_cache_dirty(self):
        docs_svc = MagicMock()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["insert_page_break"](doc_id="doc1", index=1, ctx=ctx)
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_page_break"](doc_id="doc1", index=1, ctx=ctx)
        assert "error" in result


# ---------------------------------------------------------------------------
# insert_softbreak_paragraph (#332)
# ---------------------------------------------------------------------------


class TestInsertSoftbreakParagraph:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_lines_joined_with_soft_break(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "Line one"}, {"text": "Line two"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        insert_req = body["requests"][0]["insertText"]
        assert insert_req["location"]["index"] == 10
        assert insert_req["text"] == "Line one\vLine two"

    async def test_paragraph_style_set_explicitly_over_whole_span(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "abc"}, {"text": "de"}],
            named_style_type="HEADING_2",
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_req = body["requests"][1]["updateParagraphStyle"]
        assert style_req["paragraphStyle"]["namedStyleType"] == "HEADING_2"
        assert style_req["fields"] == "namedStyleType"
        # "abc" (3) + soft break (1) + "de" (2) = 6 units
        assert style_req["range"] == {"startIndex": 10, "endIndex": 16}
        assert result["start_index"] == 10
        assert result["end_index"] == 16

    async def test_line_ranges_and_per_line_bold_style(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "Document ID: X", "bold": True}, {"text": "Category: Y"}],
            ctx=ctx,
        )
        # Line 0: [1, 15); soft break at 15; line 1: [16, 27)
        assert result["line_ranges"] == [
            {"start_index": 1, "end_index": 15},
            {"start_index": 16, "end_index": 27},
        ]
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_requests = [r["updateTextStyle"] for r in body["requests"] if "updateTextStyle" in r]
        assert len(style_requests) == 1
        assert style_requests[0]["range"] == {"startIndex": 1, "endIndex": 15}
        assert style_requests[0]["textStyle"] == {"bold": True}
        assert style_requests[0]["fields"] == "bold"

    async def test_link_url_null_clears_link(self):
        # #408: shares _text_style_and_fields with style_doc_range, so a
        # link_url=None line must still send its clearing updateTextStyle
        # request rather than being skipped for having an empty textStyle.
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "no longer linked", "link_url": None}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_requests = [r["updateTextStyle"] for r in body["requests"] if "updateTextStyle" in r]
        assert len(style_requests) == 1
        assert style_requests[0]["fields"] == "link"
        assert "link" not in style_requests[0]["textStyle"]

    async def test_astral_character_advances_offset_by_two_utf16_units(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "hi 😀"}, {"text": "next"}],
            ctx=ctx,
        )
        # "hi 😀" is 4 Python chars but 5 UTF-16 units (the emoji is a surrogate
        # pair) -> line 0 spans [1, 6), soft break at 6, line 1 starts at 7.
        assert result["line_ranges"][0] == {"start_index": 1, "end_index": 6}
        assert result["line_ranges"][1]["start_index"] == 7

    async def test_empty_lines_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[], ctx=ctx
        )
        assert "error" in result

    async def test_line_missing_text_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[{"bold": True}], ctx=ctx
        )
        assert "error" in result

    async def test_invalid_named_style_type_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "x"}],
            named_style_type="NOT_A_STYLE",
            ctx=ctx,
        )
        assert "error" in result

    async def test_marks_doc_cache_dirty(self):
        docs_svc = MagicMock()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[{"text": "x"}], ctx=ctx
        )
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[{"text": "x"}], ctx=ctx
        )
        assert "error" in result
