"""Tests for tools/sheets/data.py."""

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


class TestGetMultipleSheetData:
    """range is optional — omitting it fetches the full sheet (issue #75)."""

    def _mock_sheets(self, values):
        mock = MagicMock()
        mock.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": values
        }
        return mock

    def _ctx(self, values):
        return _make_ctx(sheets_service=self._mock_sheets(values))

    def test_range_optional_fetches_full_sheet(self):
        ctx = self._ctx([["A", "B"], ["1", "2"]])
        result = _data_tools["get_multiple_sheet_data"](
            queries=[{"spreadsheet_id": "abc", "sheet": "Sheet1"}],
            ctx=ctx,
        )
        assert len(result) == 1
        assert "error" not in result[0]
        assert result[0]["data"] == [["A", "B"], ["1", "2"]]
        # Confirm no range appended — call arg should be just the quoted sheet name
        call_kwargs = ctx.request_context.lifespan_context.sheets_service.spreadsheets.return_value.values.return_value.get.call_args
        assert "!" not in call_kwargs.kwargs.get(
            "range", call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
        )

    def test_range_provided_appended_to_sheet(self):
        ctx = self._ctx([["A"]])
        result = _data_tools["get_multiple_sheet_data"](
            queries=[{"spreadsheet_id": "abc", "sheet": "Sheet1", "range": "A1:B5"}],
            ctx=ctx,
        )
        assert "error" not in result[0]

    def test_missing_spreadsheet_id_returns_error(self):
        ctx = self._ctx([])
        result = _data_tools["get_multiple_sheet_data"](
            queries=[{"sheet": "Sheet1"}],
            ctx=ctx,
        )
        assert result[0]["error"] == "Missing required keys (spreadsheet_id, sheet)"

    def test_missing_sheet_returns_error(self):
        ctx = self._ctx([])
        result = _data_tools["get_multiple_sheet_data"](
            queries=[{"spreadsheet_id": "abc"}],
            ctx=ctx,
        )
        assert result[0]["error"] == "Missing required keys (spreadsheet_id, sheet)"

    def test_valid_query_not_blocked_by_invalid_sibling(self):
        ctx = self._ctx([["ok"]])
        result = _data_tools["get_multiple_sheet_data"](
            queries=[
                {"spreadsheet_id": "abc", "sheet": "Sheet1"},
                {"sheet": "NoId"},
            ],
            ctx=ctx,
        )
        assert "error" not in result[0]
        assert "error" in result[1]

    def test_empty_queries_returns_empty_list(self):
        ctx = self._ctx([])
        result = _data_tools["get_multiple_sheet_data"](queries=[], ctx=ctx)
        assert result == []


class TestBatchUpdate:
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
