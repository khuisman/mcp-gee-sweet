"""Tests for docs layout tools — create_header, create_footer, insert_doc_text segment_id."""

from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

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
# create_header / create_footer (#147)
# ---------------------------------------------------------------------------


class TestCreateHeader:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _make_docs_svc(self, header_id="hdr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createHeaderResponse": {"headerId": header_id}}]
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

    async def test_first_page_header_type(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_header"](doc_id="doc1", header_type="FIRST_PAGE_HEADER", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createHeader"]["type"] == "FIRST_PAGE_HEADER"

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
            "replies": [{"createFooterResponse": {"footerId": footer_id}}]
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

    async def test_first_page_footer_type(self):
        docs_svc = self._make_docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["create_footer"](doc_id="doc1", footer_type="FIRST_PAGE_FOOTER", ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0]["createFooter"]["type"] == "FIRST_PAGE_FOOTER"

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
