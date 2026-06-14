"""Tests for tools/sheets/data.py (batch_update and related)."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools.sheets import data as sheets_data_module


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


_data_tool, _data_tools = _make_tool_registry()
sheets_data_module.register(_data_tool)


class TestBatchUpdateCacheInvalidation:
    """Bug: batch_update only invalidated sheet_data_cache, leaving structure cache stale."""

    def _mock_sheets(self):
        mock = MagicMock()
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        return mock

    def test_structure_cache_marked_dirty(self):
        mock_cache = MagicMock()
        ctx = _make_ctx(
            sheets_service=self._mock_sheets(),
            cache=mock_cache,
            sheet_data_cache=MagicMock(),
        )
        _data_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"addSheet": {"properties": {"title": "New Sheet"}}}],
            ctx=ctx,
        )
        mock_cache.mark_dirty.assert_called_once_with("abc123")

    def test_both_caches_marked_dirty_together(self):
        mock_data_cache = MagicMock()
        ctx = _make_ctx(
            sheets_service=self._mock_sheets(),
            cache=MagicMock(),
            sheet_data_cache=mock_data_cache,
        )
        _data_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"updateCells": {}}],
            ctx=ctx,
        )
        mock_data_cache.mark_dirty.assert_called_once_with("abc123")
