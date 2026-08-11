"""Tests for docs named-range tools — create_named_range, create_bookmark."""

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


class TestCreateNamedRange:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _docs_svc(self, named_range_id="nr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createNamedRange": {"namedRangeId": named_range_id}}]
        }
        return docs_svc

    async def test_sends_correct_request(self):
        docs_svc = self._docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["createNamedRange"]
        assert req["name"] == "section-a"
        assert req["range"] == {"startIndex": 5, "endIndex": 10}
        assert result == {
            "docId": "doc1",
            "namedRangeId": "nr1",
            "name": "section-a",
            "startIndex": 5,
            "endIndex": 10,
        }

    async def test_marks_doc_cache_dirty(self):
        docs_svc = self._docs_svc()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        assert "error" in result

    async def test_success_response_with_empty_replies_returns_error_not_crash(self):
        """Regression (PR #337 review): a success response with no/empty replies must
        not raise IndexError/KeyError — every sibling tool in this file guarantees
        {"error": ...} instead."""
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        result = await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        assert "error" in result
        doc_cache.mark_dirty.assert_not_called()


class TestCreateBookmark:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _docs_svc(self, named_range_id="nr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createNamedRange": {"namedRangeId": named_range_id}}]
        }
        return docs_svc

    async def test_sends_single_character_named_range(self):
        docs_svc = self._docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["createNamedRange"]
        assert req["name"] == "intro"
        assert req["range"] == {"startIndex": 7, "endIndex": 8}
        assert result == {
            "docId": "doc1",
            "namedRangeId": "nr1",
            "name": "intro",
            "index": 7,
        }

    async def test_marks_doc_cache_dirty(self):
        docs_svc = self._docs_svc()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        assert "error" in result

    async def test_success_response_with_empty_replies_returns_error_not_crash(self):
        """Regression (PR #337 review): a success response with no/empty replies must
        not raise IndexError/KeyError — every sibling tool in this file guarantees
        {"error": ...} instead."""
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        result = await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        assert "error" in result
        doc_cache.mark_dirty.assert_not_called()
