"""Tests for docs layout tools — create_header, create_footer, insert_doc_text segment_id."""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

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
# create_header / create_footer (#147)
# ---------------------------------------------------------------------------


class TestCreateHeader:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _make_docs_svc(self, header_id="hdr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createHeader": {"headerId": header_id}}]
        }
        return docs_svc

    async def test_returns_header_id(self):
        docs_svc = self._make_docs_svc("hdr-abc")
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "headerId": "hdr-abc"}

    async def test_default_type_sent(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createHeader"]["type"] == "DEFAULT"
        assert "sectionBreakLocation" not in body["requests"][0]["createHeader"]

    async def test_first_page_header_type_is_refused_before_any_call(self):
        # The Docs API's HeaderFooterType has only DEFAULT: FIRST_PAGE_HEADER was
        # a 400 (checked live, #1527).
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_header"](
            doc_id="doc1", header_type="FIRST_PAGE_HEADER", ctx=ctx
        )
        assert "first-page header can't be created" in result["error"]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_reply_header_id_is_used_without_a_document_read(self):
        docs_svc = self._make_docs_svc("hdr-abc")
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        docs_svc.documents.return_value.get.assert_not_called()

    async def test_invalid_type_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["create_header"](doc_id="doc1", header_type="BOGUS", ctx=ctx)
        assert "error" in result

    async def test_content_inserted_when_provided(self):
        docs_svc = self._make_docs_svc("hdr1")
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_header"](doc_id="doc1", content="My Header", ctx=ctx)
        # Two batchUpdate calls: one to create, one to insert text
        assert docs_svc.documents.return_value.batchUpdate.call_count == 2
        second_body = docs_svc.documents.return_value.batchUpdate.call_args_list[1].kwargs["body"]
        insert_req = second_body["requests"][0]["insertText"]
        assert insert_req["text"] == "My Header"
        assert insert_req["location"]["segmentId"] == "hdr1"
        assert insert_req["location"]["index"] == 0

    async def test_no_content_single_api_call(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 1

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert "error" in result

    async def test_empty_replies_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultHeaderId": "hdr-fallback"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "headerId": "hdr-fallback"}

    async def test_already_exists_error_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=400), content=b"Default header already exists."
        )
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultHeaderId": "hdr-existing"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_header"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "headerId": "hdr-existing"}


class TestCreateFooter:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _make_docs_svc(self, footer_id="ftr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createFooter": {"footerId": footer_id}}]
        }
        return docs_svc

    async def test_returns_footer_id(self):
        docs_svc = self._make_docs_svc("ftr-xyz")
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "footerId": "ftr-xyz"}

    async def test_default_type_sent(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createFooter"]["type"] == "DEFAULT"
        assert "sectionBreakLocation" not in body["requests"][0]["createFooter"]

    async def test_first_page_footer_type_is_refused_before_any_call(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_footer"](
            doc_id="doc1", footer_type="FIRST_PAGE_FOOTER", ctx=ctx
        )
        assert "first-page footer can't be created" in result["error"]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_invalid_type_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["create_footer"](doc_id="doc1", footer_type="BOGUS", ctx=ctx)
        assert "error" in result

    async def test_content_inserted_when_provided(self):
        docs_svc = self._make_docs_svc("ftr1")
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_footer"](doc_id="doc1", content="Page 1", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 2
        second_body = docs_svc.documents.return_value.batchUpdate.call_args_list[1].kwargs["body"]
        insert_req = second_body["requests"][0]["insertText"]
        assert insert_req["text"] == "Page 1"
        assert insert_req["location"]["segmentId"] == "ftr1"
        assert insert_req["location"]["index"] == 0

    async def test_no_content_single_api_call(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 1

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert "error" in result

    async def test_empty_replies_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultFooterId": "ftr-fallback"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "footerId": "ftr-fallback"}

    async def test_already_exists_error_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=400), content=b"Default footer already exists."
        )
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultFooterId": "ftr-existing"}
        }
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_footer"](doc_id="doc1", ctx=ctx)
        assert result == {"docId": "doc1", "footerId": "ftr-existing"}


class TestCreateHeaderOrFooter:
    """create_header_or_footer (#1527) sends what create_header/create_footer send."""

    def _docs_svc(self, kind):
        docs_svc = MagicMock()
        name = "createHeader" if kind == "header" else "createFooter"
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{name: {f"{kind}Id": f"{kind}-1"}}]
        }
        return docs_svc

    def _bodies(self, docs_svc):
        return [
            c.kwargs["body"] for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]

    @pytest.mark.parametrize("kind", ["header", "footer"])
    async def test_returns_the_id_keyed_by_kind(self, kind):
        ctx = _make_ctx(docs_service=self._docs_svc(kind), doc_cache=MagicMock())
        result = await _docs_tools["create_header_or_footer"](doc_id="doc1", kind=kind, ctx=ctx)
        assert result == {"docId": "doc1", "kind": kind, f"{kind}Id": f"{kind}-1"}

    @pytest.mark.parametrize("kind", ["header", "footer"])
    async def test_sends_the_same_requests_as_the_deprecated_tool(self, kind):
        merged_svc = self._docs_svc(kind)
        await _docs_tools["create_header_or_footer"](
            doc_id="doc1",
            kind=kind,
            content="Text",
            ctx=_make_ctx(docs_service=merged_svc, doc_cache=MagicMock()),
        )
        old_svc = self._docs_svc(kind)
        await _docs_tools[f"create_{kind}"](
            doc_id="doc1",
            content="Text",
            ctx=_make_ctx(docs_service=old_svc, doc_cache=MagicMock()),
        )
        assert self._bodies(merged_svc) == self._bodies(old_svc)
        assert len(self._bodies(merged_svc)) == 2

    async def test_existing_footer_falls_back_to_document_style(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=400), content=b"Default footer already exists."
        )
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {"defaultHeaderId": "hdr", "defaultFooterId": "ftr-existing"}
        }
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["create_header_or_footer"](doc_id="doc1", kind="footer", ctx=ctx)
        assert result["footerId"] == "ftr-existing"

    async def test_content_insert_failure_is_a_warning(self):
        docs_svc = self._docs_svc("header")
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = [
            {"replies": [{"createHeader": {"headerId": "header-1"}}]},
            RuntimeError("insert failed"),
        ]
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["create_header_or_footer"](
            doc_id="doc1", kind="header", content="Text", ctx=ctx
        )
        assert result["headerId"] == "header-1"
        assert "insert failed" in result["warning"]

    @pytest.mark.parametrize("content", ["Text", None])
    async def test_a_failed_id_lookup_is_a_warning_not_a_silent_none(self, content):
        # PR #1548 QA round 1: the doc already has a header, so the create fails,
        # and the documentStyle lookup that would name it fails too.
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=400), content=b"Default header already exists."
        )
        docs_svc.documents.return_value.get.return_value.execute.side_effect = RuntimeError(
            "lookup failed"
        )
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["create_header_or_footer"](
            doc_id="doc1", kind="header", content=content, ctx=ctx
        )
        assert result["headerId"] is None
        assert "lookup failed" in result["warning"]
        assert ("not inserted" in result["warning"]) is (content is not None)
        assert docs_svc.documents.return_value.batchUpdate.call_count == 1

    async def test_no_default_id_in_document_style_is_a_warning(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentStyle": {}
        }
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["create_footer"](doc_id="doc1", content="x", ctx=ctx)
        assert result["footerId"] is None
        assert "no default footer" in result["warning"]

    async def test_invalid_kind_returns_error_without_a_call(self):
        docs_svc = MagicMock()
        ctx = _make_ctx(docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["create_header_or_footer"](
            doc_id="doc1", kind="sidebar", ctx=ctx
        )
        assert "error" in result
        docs_svc.documents.return_value.batchUpdate.assert_not_called()


# ---------------------------------------------------------------------------
# insert_doc_text — segment_id support for headers/footers
# ---------------------------------------------------------------------------


class TestInsertDocTextSegmentId:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_segment_id_included_in_location(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_doc_text"](
            doc_id="doc1",
            insertions=[{"index": 1, "text": "Header text", "segment_id": "hdr1"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        loc = body["requests"][0]["insertText"]["location"]
        assert loc["index"] == 1
        assert loc["segmentId"] == "hdr1"

    async def test_no_segment_id_omits_field(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_doc_text"](
            doc_id="doc1",
            insertions=[{"index": 5, "text": "Body text"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        loc = body["requests"][0]["insertText"]["location"]
        assert "segmentId" not in loc

    async def test_mixed_body_and_segment_insertions(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_doc_text"](
            doc_id="doc1",
            insertions=[
                {"index": 10, "text": "Body"},
                {"index": 1, "text": "Header", "segment_id": "hdr1"},
            ],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        reqs = body["requests"]
        assert len(reqs) == 2
        # Sorted high-index-first: index=10 before index=1
        assert reqs[0]["insertText"]["location"]["index"] == 10
        assert "segmentId" not in reqs[0]["insertText"]["location"]
        assert reqs[1]["insertText"]["location"]["index"] == 1
        assert reqs[1]["insertText"]["location"]["segmentId"] == "hdr1"
