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


class TestGetSheetData:
    """include_grid_data=True without a range auto-detects the used range instead of
    fetching formatting for the sheet's full padded grid (issue #235)."""

    def _service(self, values=None, grid_result=None):
        mock = MagicMock()
        mock.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": values or []
        }
        mock.spreadsheets.return_value.get.return_value.execute.return_value = grid_result or {}
        return mock

    def test_include_grid_data_without_range_auto_detects_used_range(self):
        svc = self._service(values=[["a", "b", "c"], ["1", "2", "3"]])
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", include_grid_data=True, ctx=ctx
        )
        probe_kwargs = svc.spreadsheets.return_value.values.return_value.get.call_args.kwargs
        assert probe_kwargs["range"] == "Sheet1"
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1:C2"]
        assert grid_kwargs["includeGridData"] is True

    def test_ragged_rows_use_max_column_count(self):
        svc = self._service(values=[["a"], ["1", "2", "3"]])
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", include_grid_data=True, ctx=ctx
        )
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1:C2"]

    def test_empty_sheet_falls_back_to_a1(self):
        svc = self._service(values=[])
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", include_grid_data=True, ctx=ctx
        )
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1"]

    def test_explicit_range_skips_auto_detection(self):
        grid_result = {"sheets": [{"data": [{"rowData": []}]}]}
        svc = self._service(grid_result=grid_result)
        ctx = _make_ctx(sheets_service=svc)
        result = _data_tools["get_sheet_data"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:C10",
            include_grid_data=True,
            ctx=ctx,
        )
        svc.spreadsheets.return_value.values.return_value.get.assert_not_called()
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1:C10"]
        assert grid_kwargs["includeGridData"] is True
        assert result == grid_result

    def test_without_grid_data_and_without_range_uses_sheet_name_only(self):
        svc = self._service(values=[["a"]])
        ctx = _make_ctx(sheets_service=svc)
        result = _data_tools["get_sheet_data"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        call_kwargs = svc.spreadsheets.return_value.values.return_value.get.call_args.kwargs
        assert call_kwargs["range"] == "Sheet1"
        assert result["valueRanges"][0]["values"] == [["a"]]

    def test_without_grid_data_range_is_optional_and_scoped_when_given(self):
        svc = self._service(values=[["a", "b"]])
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["get_sheet_data"](spreadsheet_id="ss1", sheet="Sheet1", range="A1:B1", ctx=ctx)
        call_kwargs = svc.spreadsheets.return_value.values.return_value.get.call_args.kwargs
        assert call_kwargs["range"] == "Sheet1!A1:B1"


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


class TestClearValues:
    def _sheets_service(self):
        mock = MagicMock()
        mock.spreadsheets.return_value.values.return_value.clear.return_value.execute.return_value = {
            "spreadsheetId": "ss1",
            "clearedRange": "Sheet1!A1:Z1000",
        }
        return mock

    def _clear_call_kwargs(self, svc):
        return svc.spreadsheets.return_value.values.return_value.clear.call_args.kwargs

    def test_with_range_builds_full_range(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["clear_values"](spreadsheet_id="ss1", sheet="Sheet1", range="A1:D10", ctx=ctx)
        kw = self._clear_call_kwargs(svc)
        assert kw["range"] == "Sheet1!A1:D10"
        assert kw["spreadsheetId"] == "ss1"

    def test_without_range_uses_sheet_name_only(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["clear_values"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        kw = self._clear_call_kwargs(svc)
        assert kw["range"] == "Sheet1"
        assert "!" not in kw["range"]

    def test_sheet_name_with_spaces_is_quoted(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc)
        _data_tools["clear_values"](spreadsheet_id="ss1", sheet="My Data", range="A1:B5", ctx=ctx)
        kw = self._clear_call_kwargs(svc)
        assert kw["range"].startswith("'My Data'!")
