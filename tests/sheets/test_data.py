"""Tests for tools/sheets/data.py."""

import json
from unittest.mock import MagicMock

import pytest

from mcp_gee_sweet.tools import response_limits
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

    async def test_include_grid_data_without_range_auto_detects_used_range(self):
        svc = self._service(values=[["a", "b", "c"], ["1", "2", "3"]])
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", include_grid_data=True, ctx=ctx
        )
        probe_kwargs = svc.spreadsheets.return_value.values.return_value.get.call_args.kwargs
        assert probe_kwargs["range"] == "Sheet1"
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1:C2"]
        assert grid_kwargs["includeGridData"] is True

    async def test_ragged_rows_use_max_column_count(self):
        svc = self._service(values=[["a"], ["1", "2", "3"]])
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", include_grid_data=True, ctx=ctx
        )
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1:C2"]

    async def test_empty_sheet_falls_back_to_a1(self):
        svc = self._service(values=[])
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", include_grid_data=True, ctx=ctx
        )
        grid_kwargs = svc.spreadsheets.return_value.get.call_args.kwargs
        assert grid_kwargs["ranges"] == ["Sheet1!A1"]

    async def test_oversized_grid_result_raises_after_fetch(self):
        # Cell count doesn't predict size (issue #235) — a live test found a 26,000-cell
        # blank range costs almost nothing, while a 1,300-cell formatted one hit ~984K
        # chars. So the check has to run on the real serialized result, which means the
        # fetch itself already happened by the time we raise.
        big_grid_result = {"filler": "x" * 300_000}
        svc = self._service(grid_result=big_grid_result)
        ctx = _make_ctx(sheets_service=svc)
        with pytest.raises(ValueError, match="safety cap"):
            await _data_tools["get_sheet_data"](
                spreadsheet_id="ss1",
                sheet="Sheet1",
                range="A1:C10",
                include_grid_data=True,
                ctx=ctx,
            )
        svc.spreadsheets.return_value.get.assert_called_once()

    async def test_small_grid_result_under_cap_succeeds(self):
        grid_result = {"sheets": [{"data": [{"rowData": []}]}]}
        svc = self._service(grid_result=grid_result)
        ctx = _make_ctx(sheets_service=svc)
        result = await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:C10",
            include_grid_data=True,
            ctx=ctx,
        )
        assert result == grid_result

    async def test_cap_is_configurable(self, monkeypatch):
        # A result that fits under the default cap should be rejected once the cap is
        # lowered below its size — the config knob has to actually change the behavior.
        grid_result = {"filler": "x" * 1000}
        svc = self._service(grid_result=grid_result)
        ctx = _make_ctx(sheets_service=svc)
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 500)
        with pytest.raises(ValueError, match="safety cap"):
            await _data_tools["get_sheet_data"](
                spreadsheet_id="ss1",
                sheet="Sheet1",
                range="A1:C10",
                include_grid_data=True,
                ctx=ctx,
            )

    async def test_explicit_range_skips_auto_detection(self):
        grid_result = {"sheets": [{"data": [{"rowData": []}]}]}
        svc = self._service(grid_result=grid_result)
        ctx = _make_ctx(sheets_service=svc)
        result = await _data_tools["get_sheet_data"](
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

    async def test_local_path_bypasses_cap_and_writes_grid_result(self, tmp_path):
        # Actually over the size cap — local_path should bypass the check entirely,
        # not just happen to be under it.
        grid_result = {"filler": "x" * 300_000}
        svc = self._service(grid_result=grid_result)
        ctx = _make_ctx(sheets_service=svc)
        dest = tmp_path / "out.json"
        result = await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:C10",
            include_grid_data=True,
            local_path=str(dest),
            ctx=ctx,
        )
        assert result["local_path"] == str(dest)
        assert result["bytes_written"] == dest.stat().st_size
        assert json.loads(dest.read_text()) == grid_result

    async def test_local_path_as_directory_synthesizes_filename(self, tmp_path):
        svc = self._service(grid_result={"ok": True})
        ctx = _make_ctx(sheets_service=svc)
        result = await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:B2",
            include_grid_data=True,
            local_path=str(tmp_path),
            ctx=ctx,
        )
        dest = tmp_path / "Sheet1_data.json"
        assert result["local_path"] == str(dest)
        assert json.loads(dest.read_text()) == {"ok": True}

    async def test_local_path_creates_missing_parent_dirs(self, tmp_path):
        svc = self._service(grid_result={"ok": True})
        ctx = _make_ctx(sheets_service=svc)
        dest = tmp_path / "nested" / "sub" / "out.json"
        result = await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:B2",
            include_grid_data=True,
            local_path=str(dest),
            ctx=ctx,
        )
        assert result["local_path"] == str(dest)
        assert dest.exists()

    async def test_local_path_without_grid_data_writes_values_result(self, tmp_path):
        svc = self._service(values=[["a", "b"]])
        ctx = _make_ctx(sheets_service=svc)
        dest = tmp_path / "values.json"
        result = await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", local_path=str(dest), ctx=ctx
        )
        assert result["local_path"] == str(dest)
        written = json.loads(dest.read_text())
        assert written["valueRanges"][0]["values"] == [["a", "b"]]

    async def test_without_grid_data_and_without_range_uses_sheet_name_only(self):
        svc = self._service(values=[["a"]])
        ctx = _make_ctx(sheets_service=svc)
        result = await _data_tools["get_sheet_data"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        call_kwargs = svc.spreadsheets.return_value.values.return_value.get.call_args.kwargs
        assert call_kwargs["range"] == "Sheet1"
        assert result["valueRanges"][0]["values"] == [["a"]]

    async def test_without_grid_data_range_is_optional_and_scoped_when_given(self):
        svc = self._service(values=[["a", "b"]])
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["get_sheet_data"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:B1", ctx=ctx
        )
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

    async def test_range_optional_fetches_full_sheet(self):
        ctx = self._ctx([["A", "B"], ["1", "2"]])
        result = await _data_tools["get_multiple_sheet_data"](
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

    async def test_range_provided_appended_to_sheet(self):
        ctx = self._ctx([["A"]])
        result = await _data_tools["get_multiple_sheet_data"](
            queries=[{"spreadsheet_id": "abc", "sheet": "Sheet1", "range": "A1:B5"}],
            ctx=ctx,
        )
        assert "error" not in result[0]

    async def test_missing_spreadsheet_id_returns_error(self):
        ctx = self._ctx([])
        result = await _data_tools["get_multiple_sheet_data"](
            queries=[{"sheet": "Sheet1"}],
            ctx=ctx,
        )
        assert result[0]["error"] == "Missing required keys (spreadsheet_id, sheet)"

    async def test_missing_sheet_returns_error(self):
        ctx = self._ctx([])
        result = await _data_tools["get_multiple_sheet_data"](
            queries=[{"spreadsheet_id": "abc"}],
            ctx=ctx,
        )
        assert result[0]["error"] == "Missing required keys (spreadsheet_id, sheet)"

    async def test_valid_query_not_blocked_by_invalid_sibling(self):
        ctx = self._ctx([["ok"]])
        result = await _data_tools["get_multiple_sheet_data"](
            queries=[
                {"spreadsheet_id": "abc", "sheet": "Sheet1"},
                {"sheet": "NoId"},
            ],
            ctx=ctx,
        )
        assert "error" not in result[0]
        assert "error" in result[1]

    async def test_empty_queries_returns_empty_list(self):
        ctx = self._ctx([])
        result = await _data_tools["get_multiple_sheet_data"](queries=[], ctx=ctx)
        assert result == []

    async def test_oversized_result_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx([["x" * 1000]])
        with pytest.raises(ValueError, match="safety cap"):
            await _data_tools["get_multiple_sheet_data"](
                queries=[{"spreadsheet_id": "abc", "sheet": "Sheet1"}], ctx=ctx
            )

    async def test_local_path_bypasses_cap_and_writes_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx([["x" * 1000]])
        dest = tmp_path / "out.json"
        result = await _data_tools["get_multiple_sheet_data"](
            queries=[{"spreadsheet_id": "abc", "sheet": "Sheet1"}],
            local_path=str(dest),
            ctx=ctx,
        )
        assert result["local_path"] == str(dest)
        assert result["query_count"] == 1
        written = json.loads(dest.read_text())
        assert written[0]["data"] == [["x" * 1000]]


class TestGetMultipleSpreadsheetSummary:
    """Response-size cap and local_path parity with get_multiple_sheet_data (QA finding, #183)."""

    def _ctx(self, spreadsheet_meta, values):
        sheets_service = MagicMock()
        sheets_service.spreadsheets.return_value.get.return_value.execute.return_value = (
            spreadsheet_meta
        )
        sheets_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": values
        }
        ctx = _make_ctx(sheets_service=sheets_service, drive_service=MagicMock())
        lc = ctx.request_context.lifespan_context
        lc.cache.get_sheets.return_value = None
        lc.cache.get_title.return_value = None
        lc.sheet_data_cache.get.return_value = None
        return ctx

    def _spreadsheet_meta(self, title="Big"):
        return {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": 0}}],
        }

    async def test_oversized_result_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(self._spreadsheet_meta(), [["x" * 1000]])
        with pytest.raises(ValueError, match="safety cap"):
            await _data_tools["get_multiple_spreadsheet_summary"](spreadsheet_ids=["abc"], ctx=ctx)

    async def test_local_path_bypasses_cap_and_writes_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(self._spreadsheet_meta(), [["x" * 1000]])
        dest = tmp_path / "out.json"
        result = await _data_tools["get_multiple_spreadsheet_summary"](
            spreadsheet_ids=["abc"], local_path=str(dest), ctx=ctx
        )
        assert result["local_path"] == str(dest)
        assert result["spreadsheet_count"] == 1
        written = json.loads(dest.read_text())
        assert written[0]["title"] == "Big"


class TestFindInSpreadsheet:
    def _service(self, sheet_titles, values):
        svc = MagicMock()
        svc.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [
                {"properties": {"title": t, "sheetId": i}} for i, t in enumerate(sheet_titles)
            ]
        }
        svc.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": values
        }
        return svc

    def _ctx(self, sheet_titles, values):
        return _make_ctx(
            sheets_service=self._service(sheet_titles, values),
            cache=MagicMock(
                get_sheets=MagicMock(return_value=None), get_title=MagicMock(return_value=None)
            ),
        )

    async def test_finds_matching_cell(self):
        ctx = self._ctx(["Sheet1"], [["foo", "bar"], ["baz", "foobar"]])
        result = await _data_tools["find_in_spreadsheet"](
            spreadsheet_id="ss1", query="foo", ctx=ctx
        )
        assert {r["cell"] for r in result} == {"A1", "B2"}

    async def test_max_results_caps_match_count_not_size(self):
        # max_results bounds how many matches are returned, not how large each matched
        # value is — a handful of huge matching cells can still blow the size cap.
        ctx = self._ctx(["Sheet1"], [["foo" + "x" * 1000]])
        result = await _data_tools["find_in_spreadsheet"](
            spreadsheet_id="ss1", query="foo", max_results=1, ctx=ctx
        )
        assert len(result) == 1

    async def test_oversized_result_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(["Sheet1"], [["foo" + "x" * 1000]])
        with pytest.raises(ValueError, match="safety cap"):
            await _data_tools["find_in_spreadsheet"](spreadsheet_id="ss1", query="foo", ctx=ctx)

    async def test_local_path_bypasses_cap_and_writes_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(["Sheet1"], [["foo" + "x" * 1000]])
        dest = tmp_path / "out.json"
        result = await _data_tools["find_in_spreadsheet"](
            spreadsheet_id="ss1", query="foo", local_path=str(dest), ctx=ctx
        )
        assert result["local_path"] == str(dest)
        assert result["match_count"] == 1
        written = json.loads(dest.read_text())
        assert len(written) == 1


class TestBatchUpdate:
    """Bug: batch_update only invalidated sheet_data_cache, leaving structure cache stale."""

    def _mock_sheets(self):
        mock = MagicMock()
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        return mock

    async def test_structure_cache_marked_dirty(self):
        mock_cache = MagicMock()
        ctx = _make_ctx(
            sheets_service=self._mock_sheets(),
            cache=mock_cache,
            sheet_data_cache=MagicMock(),
        )
        await _data_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"addSheet": {"properties": {"title": "New Sheet"}}}],
            ctx=ctx,
        )
        mock_cache.mark_dirty.assert_called_once_with("abc123")

    async def test_both_caches_marked_dirty_together(self):
        mock_data_cache = MagicMock()
        ctx = _make_ctx(
            sheets_service=self._mock_sheets(),
            cache=MagicMock(),
            sheet_data_cache=mock_data_cache,
        )
        await _data_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"updateCells": {}}],
            ctx=ctx,
        )
        mock_data_cache.mark_dirty.assert_called_once_with("abc123")


class TestUpdateCells:
    """Rich-text cells (issue #89): a cell value that's a list of
    {"text", "hyperlink"} run dicts builds a textFormatRuns updateCells request
    instead of a plain values().update() write."""

    def _service(self, sheet_id=0, batch_replies=None):
        mock = MagicMock()
        mock.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {
            "updatedRange": "Sheet1!A1:A1",
            "updatedCells": 1,
        }
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = (
            batch_replies or {"replies": [{}]}
        )
        return mock

    async def test_plain_values_use_values_update_unchanged(self):
        svc = self._service()
        ctx = _make_ctx(sheets_service=svc, cache=None, sheet_data_cache=MagicMock())
        result = await _data_tools["update_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:B1", data=[["a", "b"]], ctx=ctx
        )
        svc.spreadsheets.return_value.values.return_value.update.assert_called_once()
        svc.spreadsheets.return_value.batchUpdate.assert_not_called()
        assert result == {"updatedRange": "Sheet1!A1:A1", "updatedCells": 1}

    async def test_rich_text_cell_builds_text_format_runs(self):
        svc = self._service(sheet_id=42)
        ctx = _make_ctx(sheets_service=svc, cache=None, sheet_data_cache=MagicMock())
        runs = [{"text": "See "}, {"text": "docs", "hyperlink": "https://example.com"}]
        await _data_tools["update_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", data=[[runs]], ctx=ctx
        )
        # Pure rich-text write — no plain values().update() call needed.
        svc.spreadsheets.return_value.values.return_value.update.assert_not_called()
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        request = body["requests"][0]["updateCells"]
        assert request["range"] == {
            "sheetId": 42,
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        }
        cell = request["rows"][0]["values"][0]
        assert cell["userEnteredValue"] == {"stringValue": "See docs"}
        assert cell["userEnteredFormat"] == {"hyperlinkDisplayType": "LINKED"}
        assert cell["textFormatRuns"] == [
            {"format": {}},
            {"startIndex": 4, "format": {"link": {"uri": "https://example.com"}}},
        ]

    async def test_astral_character_run_offset_uses_utf16_units(self):
        # An astral-plane emoji is 1 Python char but 2 UTF-16 units — the second
        # run's startIndex must account for that surrogate pair, not len().
        svc = self._service()
        ctx = _make_ctx(sheets_service=svc, cache=None, sheet_data_cache=MagicMock())
        runs = [{"text": "🚀"}, {"text": "link", "hyperlink": "https://example.com"}]
        await _data_tools["update_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", data=[[runs]], ctx=ctx
        )
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        cell = body["requests"][0]["updateCells"]["rows"][0]["values"][0]
        assert cell["textFormatRuns"][1]["startIndex"] == 2

    async def test_mixed_plain_and_rich_text_cells_writes_both(self):
        svc = self._service()
        ctx = _make_ctx(sheets_service=svc, cache=None, sheet_data_cache=MagicMock())
        runs = [{"text": "link", "hyperlink": "https://example.com"}]
        await _data_tools["update_cells"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:B1",
            data=[["plain", runs]],
            ctx=ctx,
        )
        svc.spreadsheets.return_value.values.return_value.update.assert_called_once()
        plain_body = svc.spreadsheets.return_value.values.return_value.update.call_args.kwargs[
            "body"
        ]
        assert plain_body["values"] == [["plain", ""]]
        svc.spreadsheets.return_value.batchUpdate.assert_called_once()
        req_range = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]["requests"][
            0
        ]["updateCells"]["range"]
        assert req_range["startColumnIndex"] == 1

    async def test_malformed_run_missing_text_key_returns_error(self):
        svc = self._service()
        ctx = _make_ctx(sheets_service=svc, cache=None, sheet_data_cache=MagicMock())
        result = await _data_tools["update_cells"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1",
            data=[[[{"hyperlink": "https://example.com"}]]],
            ctx=ctx,
        )
        assert "error" in result
        svc.spreadsheets.return_value.batchUpdate.assert_not_called()
        svc.spreadsheets.return_value.values.return_value.update.assert_not_called()

    async def test_sheet_not_found_returns_error(self):
        svc = self._service()
        svc.spreadsheets.return_value.get.return_value.execute.return_value = {"sheets": []}
        ctx = _make_ctx(sheets_service=svc, cache=None, sheet_data_cache=MagicMock())
        result = await _data_tools["update_cells"](
            spreadsheet_id="ss1",
            sheet="Missing",
            range="A1",
            data=[[[{"text": "x"}]]],
            ctx=ctx,
        )
        assert result == {"error": "Sheet 'Missing' not found"}


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

    async def test_with_range_builds_full_range(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["clear_values"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:D10", ctx=ctx
        )
        kw = self._clear_call_kwargs(svc)
        assert kw["range"] == "Sheet1!A1:D10"
        assert kw["spreadsheetId"] == "ss1"

    async def test_without_range_uses_sheet_name_only(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["clear_values"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        kw = self._clear_call_kwargs(svc)
        assert kw["range"] == "Sheet1"
        assert "!" not in kw["range"]

    async def test_sheet_name_with_spaces_is_quoted(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc)
        await _data_tools["clear_values"](
            spreadsheet_id="ss1", sheet="My Data", range="A1:B5", ctx=ctx
        )
        kw = self._clear_call_kwargs(svc)
        assert kw["range"].startswith("'My Data'!")
