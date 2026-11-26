"""Tests for docs editing tools — insert_page_break, insert_softbreak_paragraph."""

from unittest.mock import MagicMock

import pytest

from mcp_gee_sweet.tools import docs as docs_module


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

    async def test_default_sends_no_paragraph_style_request(self):
        # #1489: the tool used to always send updateParagraphStyle, defaulting
        # to NORMAL_TEXT, so a plain insert wiped the paragraph's existing
        # inline text styles with no named_style_type asked for. The default
        # now sends no paragraph-style request at all.
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "abc"}, {"text": "de"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        kinds = [next(iter(r)) for r in body["requests"]]
        assert kinds == ["insertText"]

    async def test_font_family_line_sends_weighted_font_family(self):
        # #1489 item 4: font_family is part of the line-dict vocabulary
        # (_text_style_and_fields supports it), and must reach the batchUpdate
        # as a weightedFontFamily updateTextStyle request.
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "code line", "font_family": "Courier New"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_requests = [r["updateTextStyle"] for r in body["requests"] if "updateTextStyle" in r]
        assert style_requests == [
            {
                "range": {"startIndex": 1, "endIndex": 10},
                "textStyle": {"weightedFontFamily": {"fontFamily": "Courier New"}},
                "fields": "weightedFontFamily",
            }
        ]

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


class TestInsertSoftbreakParagraphBoldRestore:
    """#1499 item 4: a font_family line that sends no bold of its own keeps the
    bold the insert inherits from the character before index — the same
    weightedFontFamily request would otherwise clear it (#1273), so it is
    restored in the same batchUpdate, after the font request, as
    style_doc_range does."""

    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    @staticmethod
    def _doc_with_bold_run():
        # A directly bold run covering [1, 15), plain text around it: an insert
        # at index 10 inherits its bold from the character at 9.
        return {
            "documentId": "doc1",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 25,
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 15,
                                    "textRun": {
                                        "content": "Bold text here",
                                        "textStyle": {"bold": True},
                                    },
                                },
                                {
                                    "startIndex": 15,
                                    "endIndex": 25,
                                    "textRun": {"content": " plain tail", "textStyle": {}},
                                },
                            ]
                        },
                    }
                ]
            },
        }

    async def test_font_only_line_after_bold_char_restores_bold(self):
        docs_svc = MagicMock()
        docs_svc.documents().get().execute.return_value = self._doc_with_bold_run()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "code line", "font_family": "Courier New"}],
            ctx=ctx,
        )
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == ["insertText", "updateTextStyle", "updateTextStyle"]
        font_update = reqs[1]["updateTextStyle"]
        assert font_update["fields"] == "weightedFontFamily"
        bold_restore = reqs[2]["updateTextStyle"]
        assert bold_restore["range"] == {"startIndex": 10, "endIndex": 19}
        assert bold_restore["textStyle"] == {"bold": True}
        assert bold_restore["fields"] == "bold"

    async def test_plain_preceding_char_sends_no_restore(self):
        docs_svc = MagicMock()
        # Insert at index 20: the character at 19 sits in the plain run.
        docs_svc.documents().get().execute.return_value = self._doc_with_bold_run()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=20,
            lines=[{"text": "code line", "font_family": "Courier New"}],
            ctx=ctx,
        )
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == ["insertText", "updateTextStyle"]
        assert reqs[1]["updateTextStyle"]["fields"] == "weightedFontFamily"

    async def test_line_with_own_bold_is_left_alone(self):
        # A line that sends bold in the same request is not in the restore set,
        # and no document read happens at all (#1273: same-request bold keeps).
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "both", "font_family": "Courier New", "bold": True}],
            ctx=ctx,
        )
        docs_svc.documents().get.assert_not_called()
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == ["insertText", "updateTextStyle"]

    async def test_restore_covers_only_the_font_only_line(self):
        docs_svc = MagicMock()
        docs_svc.documents().get().execute.return_value = self._doc_with_bold_run()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[
                {"text": "plain line"},
                {"text": "font line", "font_family": "Consolas"},
                {"text": "bold line", "bold": True},
            ],
            ctx=ctx,
        )
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        bold_requests = [
            r["updateTextStyle"]
            for r in reqs
            if "updateTextStyle" in r and r["updateTextStyle"]["fields"] == "bold"
        ]
        # The bold-restore belongs to the font-only line, not the bold line
        # (whose own bold=True request is [31, 40), sent either way):
        # [10,20) "plain line", [21,30) "font line", [31,40) "bold line".
        assert [b["range"] for b in bold_requests] == [
            {"startIndex": 21, "endIndex": 30},
            {"startIndex": 31, "endIndex": 40},
        ]
        assert result["line_ranges"][1] == {"start_index": 21, "end_index": 30}
        # The restore for [21, 30) follows that line's font request.
        font_idx = next(
            i
            for i, r in enumerate(reqs)
            if "updateTextStyle" in r and r["updateTextStyle"]["fields"] == "weightedFontFamily"
        )
        restore_idx = next(
            i
            for i, r in enumerate(reqs)
            if "updateTextStyle" in r
            and r["updateTextStyle"]["fields"] == "bold"
            and r["updateTextStyle"]["range"]["startIndex"] == 21
        )
        assert font_idx < restore_idx

    async def test_failed_document_read_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents().get().execute.side_effect = Exception("boom")
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "code line", "font_family": "Courier New"}],
            ctx=ctx,
        )
        assert "error" in result
        docs_svc.documents().batchUpdate.assert_not_called()

    async def test_named_style_type_sends_no_bold_restore(self):
        # updateParagraphStyle goes out before the line styles and clears the
        # inherited bold across the whole paragraph, so reading it to restore
        # would re-bold the font-only lines alone (bold code line next to plain
        # ones). Nothing is read, no bold request goes out.
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "code line", "font_family": "Courier New"}],
            named_style_type="NORMAL_TEXT",
            ctx=ctx,
        )
        docs_svc.documents().get.assert_not_called()
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == [
            "insertText",
            "updateParagraphStyle",
            "updateTextStyle",
        ]
        assert reqs[2]["updateTextStyle"]["fields"] == "weightedFontFamily"
        assert not any(
            "updateTextStyle" in r and r["updateTextStyle"]["fields"] == "bold" for r in reqs
        )

    async def test_no_font_line_reads_no_document(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "a"}, {"text": "b", "bold": True}],
            ctx=ctx,
        )
        docs_svc.documents().get.assert_not_called()


class TestBoldRestoreAtParagraphStart:
    """#1584: at a paragraph's first index, Docs styles the inserted text from
    the character after index — the paragraph's own first character — not from
    the previous paragraph's newline, so the bold restore must probe there,
    in both directions (live-verified in the issue via raw documents().get())."""

    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    @staticmethod
    def _two_paragraph_doc(first: dict, second: dict) -> dict:
        # Two one-run paragraphs: <p>{first}</p><p>{second}</p>, the trailing
        # newline inside each paragraph's run (the Docs API shape).
        content = []
        start = 1
        for text, style in (first, second):
            end = start + len(text) + 1  # +1 for the paragraph's newline
            element = {
                "startIndex": start,
                "endIndex": end,
                "textRun": {"content": text + "\n", "textStyle": style},
            }
            content.append(
                {"startIndex": start, "endIndex": end, "paragraph": {"elements": [element]}}
            )
            start = end
        return {"documentId": "doc1", "body": {"content": content}}

    async def test_plain_paragraph_start_after_bold_sends_no_restore(self):
        # <p><b>Header</b></p><p>tail</p>, insert at the start of `tail`
        # (index 8): Docs renders the insert plain — it follows `tail` — so a
        # restore reading the previous paragraph's bold newline would bold a
        # line that should stay plain.
        docs_svc = MagicMock()
        docs_svc.documents().get().execute.return_value = self._two_paragraph_doc(
            ("Header", {"bold": True}), ("tail", {})
        )
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=8,
            lines=[{"text": "code", "font_family": "Courier New"}],
            ctx=ctx,
        )
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == ["insertText", "updateTextStyle"]
        assert reqs[1]["updateTextStyle"]["fields"] == "weightedFontFamily"

    async def test_bold_paragraph_start_after_plain_restores_bold(self):
        # <p>plain</p><p><b>Bold</b></p>, insert at the start of `Bold`
        # (index 7): Docs renders the insert bold — it follows `Bold` — so the
        # font request clears the inherited bold and the restore must bring it
        # back (the original #1499 symptom).
        docs_svc = MagicMock()
        docs_svc.documents().get().execute.return_value = self._two_paragraph_doc(
            ("plain", {}), ("Bold", {"bold": True})
        )
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=7,
            lines=[{"text": "code", "font_family": "Courier New"}],
            ctx=ctx,
        )
        assert result["line_ranges"][0] == {"start_index": 7, "end_index": 11}
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == ["insertText", "updateTextStyle", "updateTextStyle"]
        bold_restore = reqs[2]["updateTextStyle"]
        assert bold_restore["range"] == {"startIndex": 7, "endIndex": 11}
        assert bold_restore["textStyle"] == {"bold": True}
        assert bold_restore["fields"] == "bold"

    async def test_empty_paragraph_read_pins_its_lone_newline(self):
        # <p><b>Header</b></p><p></p>, insert at the empty paragraph's start
        # (index 8, its lone newline): the neighbour read is the character at
        # index — the empty paragraph's own plain newline — not the previous
        # paragraph's bold one, so nothing restores.
        docs_svc = MagicMock()
        docs_svc.documents().get().execute.return_value = self._two_paragraph_doc(
            ("Header", {"bold": True}), ("", {})
        )
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=8,
            lines=[{"text": "code", "font_family": "Courier New"}],
            ctx=ctx,
        )
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        assert [next(iter(r)) for r in reqs] == ["insertText", "updateTextStyle"]
        assert reqs[1]["updateTextStyle"]["fields"] == "weightedFontFamily"


class TestInsertSoftbreakParagraphExplicitNormalText:
    """#1499 item 5: the fix depends on telling None apart from an explicit
    NORMAL_TEXT — pin that the explicit one still sends updateParagraphStyle."""

    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_explicit_normal_text_still_sends_paragraph_style(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "abc"}],
            named_style_type="NORMAL_TEXT",
            ctx=ctx,
        )
        reqs = docs_svc.documents().batchUpdate.call_args.kwargs["body"]["requests"]
        style_req = reqs[1]["updateParagraphStyle"]
        assert style_req["paragraphStyle"]["namedStyleType"] == "NORMAL_TEXT"
        assert style_req["fields"] == "namedStyleType"


# ---------------------------------------------------------------------------
# insert_doc_text: the collapsed paragraph after a doc's final table (#1439)
# ---------------------------------------------------------------------------

_COLLAPSED = {
    "lineSpacing": 1,
    "spaceAbove": {"unit": "PT"},  # the API omits a zero magnitude (checked live)
    "spaceBelow": {"unit": "PT"},
}


def _doc_ending_in_table(trailing_style=None, *, last_is_table_neighbor=True):
    content = [
        {"startIndex": 1, "endIndex": 17, "paragraph": {"paragraphStyle": {}}},
        {"startIndex": 17, "endIndex": 18, "paragraph": {"paragraphStyle": dict(_COLLAPSED)}},
        {"startIndex": 18, "endIndex": 34, "table": {"rows": 2}},
        {
            "startIndex": 34,
            "endIndex": 35,
            "paragraph": {
                "paragraphStyle": _COLLAPSED if trailing_style is None else trailing_style
            },
        },
    ]
    if not last_is_table_neighbor:
        content.insert(3, {"startIndex": 34, "endIndex": 35, "paragraph": {"paragraphStyle": {}}})
        content[-1] = {**content[-1], "startIndex": 35, "endIndex": 36}
    return {"body": {"content": content}}


class TestInsertDocTextTrailingParagraphReset:
    async def _call(self, insertions, doc=None):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = (
            doc if doc is not None else _doc_ending_in_table()
        )
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["insert_doc_text"](doc_id="doc1", insertions=insertions, ctx=ctx)
        call = docs_svc.documents.return_value.batchUpdate.call_args
        return result, (call.kwargs["body"]["requests"] if call else None), docs_svc

    async def test_insert_into_collapsed_paragraph_resets_its_spacing(self):
        result, reqs, _ = await self._call([{"index": 34, "text": "After"}])
        assert result == {"docId": "doc1", "insertions": 1, "trailingParagraphReset": True}
        assert reqs == [
            {"insertText": {"location": {"index": 34}, "text": "After"}},
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 34, "endIndex": 40},
                    "paragraphStyle": {},
                    "fields": "lineSpacing,spaceAbove,spaceBelow",
                }
            },
        ]

    async def test_range_counts_earlier_inserts_and_utf16_length(self):
        # An insert before the paragraph moves its start; every insert moves the end.
        # "🙂" is two UTF-16 code units.
        _, reqs, _ = await self._call(
            [{"index": 1, "text": "Lead 🙂"}, {"index": 34, "text": "a\nb🙂"}]
        )
        assert [next(iter(r)) for r in reqs] == ["insertText", "insertText", "updateParagraphStyle"]
        assert reqs[-1]["updateParagraphStyle"]["range"] == {
            "startIndex": 34 + 7,
            "endIndex": 35 + 7 + 5,
        }

    async def test_insert_elsewhere_sends_no_reset(self):
        result, reqs, _ = await self._call([{"index": 5, "text": "x"}])
        assert result == {"docId": "doc1", "insertions": 1}
        assert len(reqs) == 1

    async def test_header_insert_at_same_index_neither_reads_nor_resets(self):
        result, reqs, docs_svc = await self._call(
            [{"index": 34, "text": "x", "segment_id": "kix.h"}]
        )
        assert result == {"docId": "doc1", "insertions": 1}
        assert len(reqs) == 1
        docs_svc.documents.return_value.get.assert_not_called()

    async def test_header_insert_does_not_shift_the_range(self):
        _, reqs, _ = await self._call(
            [{"index": 1, "text": "hdr", "segment_id": "kix.h"}, {"index": 34, "text": "ab"}]
        )
        assert reqs[-1]["updateParagraphStyle"]["range"] == {"startIndex": 34, "endIndex": 37}

    @pytest.mark.parametrize(
        "style",
        [
            {},
            {"lineSpacing": 100, "spaceAbove": {"unit": "PT"}, "spaceBelow": {"unit": "PT"}},
            {"lineSpacing": 1, "spaceAbove": {"magnitude": 6, "unit": "PT"}},
            {"lineSpacing": 1, "spaceBelow": {"magnitude": 10, "unit": "PT"}},
        ],
    )
    async def test_paragraph_without_the_full_signature_is_left_alone(self, style):
        result, reqs, _ = await self._call(
            [{"index": 34, "text": "x"}], _doc_ending_in_table(style)
        )
        assert "trailingParagraphReset" not in result
        assert len(reqs) == 1

    async def test_collapsed_paragraph_not_after_a_table_is_left_alone(self):
        doc = _doc_ending_in_table(last_is_table_neighbor=False)
        result, reqs, _ = await self._call([{"index": 35, "text": "x"}], doc)
        assert "trailingParagraphReset" not in result
        assert len(reqs) == 1

    async def test_text_already_in_the_paragraph_is_reset_too(self):
        # Text written there before #1439 still has the 1% spacing; inserting
        # anywhere in that paragraph resets all of it.
        doc = _doc_ending_in_table()
        doc["body"]["content"][-1]["endIndex"] = 40
        _, reqs, _ = await self._call([{"index": 38, "text": "z"}], doc)
        assert reqs[-1]["updateParagraphStyle"]["range"] == {"startIndex": 34, "endIndex": 41}

    async def test_read_failure_returns_error_without_writing(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = Exception("boom")
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["insert_doc_text"](
            doc_id="doc1", insertions=[{"index": 34, "text": "x"}], ctx=ctx
        )
        assert result == {"error": "boom"}
        docs_svc.documents.return_value.batchUpdate.assert_not_called()
