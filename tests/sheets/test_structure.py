"""Tests for tools/sheets/structure.py (add_chart, copy_sheet, and related)."""

from unittest.mock import AsyncMock, MagicMock

from mcp_gee_sweet.cache import SheetInfo
from mcp_gee_sweet.tools.sheets import structure as sheets_structure_module


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


_structure_tool, _structure_tools = _make_tool_registry()
sheets_structure_module.register(_structure_tool)


class TestAddChart:
    """BUG-1: multi-column ranges must be split per-column; BUG-2: HISTOGRAM uses histogramChart spec."""

    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sales", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"addChart": {"chart": {"chartId": 1}}}]
        }
        return mock

    def _chart_spec(self, sheets_svc):
        body = sheets_svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["addChart"]["chart"]["spec"]

    async def _call(self, sheets_svc, chart_type="COLUMN", data_range="A1:D5"):
        ctx = _make_ctx(sheets_service=sheets_svc, cache=None)
        return await _structure_tools["add_chart"](
            spreadsheet_id="ss1",
            sheet="Sales",
            chart_type=chart_type,
            data_range=data_range,
            ctx=ctx,
        )

    # BUG-1 — per-column source ranges

    async def test_domain_is_single_column(self):
        """BUG-1: domain source must span exactly one column, not the full range rectangle."""
        svc = self._sheets_service()
        await self._call(svc, "COLUMN", "A1:D5")
        spec = self._chart_spec(svc)
        domain_src = spec["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]
        assert domain_src["endColumnIndex"] - domain_src["startColumnIndex"] == 1

    async def test_domain_is_first_column(self):
        svc = self._sheets_service()
        await self._call(svc, "LINE", "A1:C10")
        spec = self._chart_spec(svc)
        domain_src = spec["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]
        assert domain_src["startColumnIndex"] == 0
        assert domain_src["endColumnIndex"] == 1

    async def test_series_count_matches_remaining_columns(self):
        """A1:D5 has 4 columns → 1 domain + 3 series."""
        svc = self._sheets_service()
        await self._call(svc, "COLUMN", "A1:D5")
        spec = self._chart_spec(svc)
        assert len(spec["basicChart"]["series"]) == 3

    async def test_each_series_is_single_column(self):
        svc = self._sheets_service()
        await self._call(svc, "BAR", "A1:C5")
        spec = self._chart_spec(svc)
        for s in spec["basicChart"]["series"]:
            src = s["series"]["sourceRange"]["sources"][0]
            assert src["endColumnIndex"] - src["startColumnIndex"] == 1

    async def test_series_columns_are_sequential(self):
        svc = self._sheets_service()
        await self._call(svc, "AREA", "A1:C5")
        spec = self._chart_spec(svc)
        col_starts = [
            s["series"]["sourceRange"]["sources"][0]["startColumnIndex"]
            for s in spec["basicChart"]["series"]
        ]
        assert col_starts == [1, 2]

    async def test_single_column_range_succeeds(self):
        """A single-column range (no separate series) must not error."""
        svc = self._sheets_service()
        result = await self._call(svc, "LINE", "B1:B10")
        assert "error" not in result

    # BUG-2 — HISTOGRAM spec

    async def test_histogram_uses_histogram_chart_spec(self):
        """BUG-2: HISTOGRAM must emit histogramChart, not basicChart."""
        svc = self._sheets_service()
        await self._call(svc, "HISTOGRAM", "A1:A10")
        spec = self._chart_spec(svc)
        assert "histogramChart" in spec
        assert "basicChart" not in spec

    async def test_histogram_series_one_per_column(self):
        svc = self._sheets_service()
        await self._call(svc, "HISTOGRAM", "A1:B10")
        spec = self._chart_spec(svc)
        assert len(spec["histogramChart"]["series"]) == 2

    # PIE chart column splitting

    async def test_pie_domain_is_first_column(self):
        svc = self._sheets_service()
        await self._call(svc, "PIE", "A1:B5")
        spec = self._chart_spec(svc)
        src = spec["pieChart"]["domain"]["sourceRange"]["sources"][0]
        assert src["startColumnIndex"] == 0
        assert src["endColumnIndex"] == 1

    async def test_pie_series_is_second_column(self):
        svc = self._sheets_service()
        await self._call(svc, "PIE", "A1:B5")
        spec = self._chart_spec(svc)
        src = spec["pieChart"]["series"]["sourceRange"]["sources"][0]
        assert src["startColumnIndex"] == 1
        assert src["endColumnIndex"] == 2

    # BUG-3 — BAR targetAxis

    async def test_bar_series_target_bottom_axis(self):
        """BUG-3: BAR charts have a horizontal value axis — series must target BOTTOM_AXIS."""
        svc = self._sheets_service()
        await self._call(svc, "BAR", "A1:C5")
        spec = self._chart_spec(svc)
        axes = [s["targetAxis"] for s in spec["basicChart"]["series"]]
        assert all(a == "BOTTOM_AXIS" for a in axes)

    async def test_non_bar_series_target_left_axis(self):
        svc = self._sheets_service()
        await self._call(svc, "COLUMN", "A1:C5")
        spec = self._chart_spec(svc)
        axes = [s["targetAxis"] for s in spec["basicChart"]["series"]]
        assert all(a == "LEFT_AXIS" for a in axes)

    # BUG-4 — COMBO per-series type

    async def test_combo_series_have_explicit_type(self):
        """BUG-4: COMBO requires a type on each series or the API returns 'No basic chart type specified'."""
        svc = self._sheets_service()
        await self._call(svc, "COMBO", "A1:D5")
        spec = self._chart_spec(svc)
        for s in spec["basicChart"]["series"]:
            assert "type" in s

    async def test_combo_last_series_is_line(self):
        svc = self._sheets_service()
        await self._call(svc, "COMBO", "A1:D5")
        spec = self._chart_spec(svc)
        series = spec["basicChart"]["series"]
        assert series[-1]["type"] == "LINE"
        assert all(s["type"] == "COLUMN" for s in series[:-1])


class TestCopySheet:
    """Bug: rename was silently skipped when API response omitted the 'title' key."""

    def _mock_sheets(self, copy_result):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": 0}}]
        }
        (
            mock.spreadsheets.return_value.sheets.return_value.copyTo.return_value.execute.return_value
        ) = copy_result
        return mock

    def _rename_titles(self, mock_sheets):
        body = mock_sheets.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return [
            r["updateSheetProperties"]["properties"]["title"]
            for r in body["requests"]
            if "updateSheetProperties" in r
        ]

    async def test_rename_triggered_when_title_absent_from_response(self):
        """The old guard `if 'title' in copy_result` would silently skip this case."""
        mock_sheets = self._mock_sheets({"sheetId": 42})  # no "title" key
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        await _structure_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="My Sheet",
            ctx=ctx,
        )
        assert mock_sheets.spreadsheets.return_value.batchUpdate.called
        assert "My Sheet" in self._rename_titles(mock_sheets)

    async def test_rename_triggered_when_title_differs(self):
        mock_sheets = self._mock_sheets({"sheetId": 42, "title": "Copy of Sheet1"})
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        await _structure_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Renamed",
            ctx=ctx,
        )
        assert mock_sheets.spreadsheets.return_value.batchUpdate.called

    async def test_rename_skipped_when_title_already_matches(self):
        mock_sheets = self._mock_sheets({"sheetId": 42, "title": "Target Name"})
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        await _structure_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Target Name",
            ctx=ctx,
        )
        assert not mock_sheets.spreadsheets.return_value.batchUpdate.called


class TestDuplicateSheet:
    def _sheets_service(self, sheet_id=0, source_index=0, reply_props=None):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [
                {"properties": {"title": "Sheet1", "sheetId": sheet_id, "index": source_index}}
            ]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [
                {
                    "duplicateSheet": {
                        "properties": reply_props
                        or {"sheetId": 99, "title": "Copy of Sheet1", "index": 1}
                    }
                }
            ]
        }
        return mock

    def _cache_with_sheet(self, title="Sheet1", sheet_id=0):
        cache = MagicMock()
        cache.get_sheets.return_value = [SheetInfo(title=title, sheet_id=sheet_id)]
        return cache

    def _request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["duplicateSheet"]

    async def test_sends_duplicate_sheet_request_with_source_id(self):
        svc = self._sheets_service(sheet_id=7, source_index=0)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        assert self._request(svc)["sourceSheetId"] == 7

    async def test_new_name_included_when_given(self):
        svc = self._sheets_service(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](
            spreadsheet_id="ss1", sheet="Sheet1", new_name="My Copy", ctx=ctx
        )
        assert self._request(svc)["newSheetName"] == "My Copy"

    async def test_insert_index_included_when_given(self):
        svc = self._sheets_service(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](
            spreadsheet_id="ss1", sheet="Sheet1", insert_index=3, ctx=ctx
        )
        assert self._request(svc)["insertSheetIndex"] == 3

    async def test_explicit_insert_index_skips_source_index_lookup(self):
        """When the caller supplies insert_index, no extra API call is needed to
        compute a default — the direct spreadsheets().get() (used only for that
        lookup) must not be invoked."""
        svc = self._sheets_service(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](
            spreadsheet_id="ss1", sheet="Sheet1", insert_index=3, ctx=ctx
        )
        assert not svc.spreadsheets.return_value.get.called

    async def test_new_name_omitted_when_not_given(self):
        svc = self._sheets_service(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        assert "newSheetName" not in self._request(svc)

    async def test_insert_index_defaults_to_immediately_after_source(self):
        """Matches Sheets' native UI 'Duplicate' behavior: the copy lands right
        after the source tab. The Sheets API's own default (observed via live
        QA) is index 0 regardless of source position, so this must be computed
        and passed explicitly rather than relying on the API's default."""
        svc = self._sheets_service(sheet_id=7, source_index=2)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        assert self._request(svc)["insertSheetIndex"] == 3

    async def test_insert_index_omitted_when_source_index_lookup_fails(self):
        svc = self._sheets_service(sheet_id=7)
        svc.spreadsheets.return_value.get.return_value.execute.return_value = {"sheets": []}
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["duplicate_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        assert "insertSheetIndex" not in self._request(svc)

    async def test_returns_new_sheet_info(self):
        svc = self._sheets_service(
            sheet_id=7, reply_props={"sheetId": 99, "title": "Copy of Sheet1", "index": 2}
        )
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        result = await _structure_tools["duplicate_sheet"](
            spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx
        )
        assert result == {
            "sheetId": 99,
            "title": "Copy of Sheet1",
            "index": 2,
            "spreadsheetId": "ss1",
        }

    async def test_returns_error_when_source_sheet_not_found(self):
        svc = self._sheets_service(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(title="Other", sheet_id=7))
        result = await _structure_tools["duplicate_sheet"](
            spreadsheet_id="ss1", sheet="Missing", ctx=ctx
        )
        assert result == {"error": "Sheet 'Missing' not found"}
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_marks_cache_dirty_on_success(self):
        svc = self._sheets_service(sheet_id=7)
        cache = self._cache_with_sheet(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=cache)
        await _structure_tools["duplicate_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        cache.mark_dirty.assert_called_with("ss1")

    async def test_forwards_drive_service_to_get_sheet_id(self, monkeypatch):
        """Regression: this call site omitted drive_service, reintroducing the
        cache-poisoning bug fixed in #284 (modified_time silently disabled for
        all subsequent readers of the spreadsheet)."""
        svc = self._sheets_service(sheet_id=7)
        cache = self._cache_with_sheet(sheet_id=7)
        drive_svc = MagicMock()
        ctx = _make_ctx(sheets_service=svc, cache=cache, drive_service=drive_svc)
        mock_get_sheet_id = AsyncMock(return_value=7)
        monkeypatch.setattr(sheets_structure_module, "_get_sheet_id", mock_get_sheet_id)
        await _structure_tools["duplicate_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        mock_get_sheet_id.assert_called_once_with(svc, "ss1", "Sheet1", cache, drive_svc)


class TestGetSheetIdCallSitesForwardDriveService:
    """Static regression guard: every _get_sheet_id() call in structure.py must
    forward drive_service as its 5th argument.

    PR #284 fixed cache poisoning caused by a missing drive_service (it silently
    disables modifiedTime staleness checks for all readers of that spreadsheet).
    duplicate_sheet reintroduced the bug by omitting the argument (caught in
    review of PR #286) — this scans all call sites so a future tool can't drop
    it again without a test failing.
    """

    async def test_all_call_sites_pass_drive_service(self):
        import inspect
        import re

        source = inspect.getsource(sheets_structure_module)
        calls = re.findall(r"_get_sheet_id\(([^)]*)\)", source)
        assert len(calls) >= 12, (
            f"expected at least 12 _get_sheet_id call sites, found {len(calls)}"
        )
        for call_args in calls:
            assert "drive_service" in call_args, (
                f"_get_sheet_id call missing drive_service: {call_args}"
            )


class TestDeleteSheet:
    def _sheets_service(self, sheet_id=7):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _cache_with_sheet(self, title="Sheet1", sheet_id=7):
        cache = MagicMock()
        cache.get_sheets.return_value = [SheetInfo(title=title, sheet_id=sheet_id)]
        return cache

    async def test_sends_delete_sheet_request(self):
        svc = self._sheets_service(sheet_id=7)
        ctx = _make_ctx(sheets_service=svc, cache=self._cache_with_sheet(sheet_id=7))
        await _structure_tools["delete_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        assert body["requests"][0] == {"deleteSheet": {"sheetId": 7}}

    async def test_marks_cache_dirty_on_success(self):
        svc = self._sheets_service()
        cache = self._cache_with_sheet()
        ctx = _make_ctx(sheets_service=svc, cache=cache)
        await _structure_tools["delete_sheet"](spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx)
        cache.mark_dirty.assert_called_with("ss1")

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["delete_sheet"](
            spreadsheet_id="ss1", sheet="Missing", ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called


class TestDeleteRows:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _dimension_range(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["deleteDimension"]["range"]

    async def test_single_row_end_index_is_start_plus_one(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["delete_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=3, ctx=ctx
        )
        r = self._dimension_range(svc)
        assert r["startIndex"] == 3
        assert r["endIndex"] == 4
        assert r["dimension"] == "ROWS"

    async def test_range_of_rows_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["delete_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=2, end_row=5, ctx=ctx
        )
        r = self._dimension_range(svc)
        assert r["startIndex"] == 2
        assert r["endIndex"] == 6  # end_row=5 inclusive → exclusive index 6

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["delete_rows"](
            spreadsheet_id="ss1", sheet="Missing", start_row=0, ctx=ctx
        )
        assert "error" in result


class TestDeleteColumns:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _dimension_range(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["deleteDimension"]["range"]

    async def test_single_column_end_index_is_start_plus_one(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["delete_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=0, ctx=ctx
        )
        r = self._dimension_range(svc)
        assert r["startIndex"] == 0
        assert r["endIndex"] == 1
        assert r["dimension"] == "COLUMNS"

    async def test_range_of_columns_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["delete_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=1, end_column=3, ctx=ctx
        )
        r = self._dimension_range(svc)
        assert r["startIndex"] == 1
        assert r["endIndex"] == 4  # end_column=3 inclusive → exclusive index 4

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["delete_columns"](
            spreadsheet_id="ss1", sheet="Missing", start_column=0, ctx=ctx
        )
        assert "error" in result


class TestHideRows:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _dimension_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateDimensionProperties"]

    async def test_single_row_end_index_is_start_plus_one(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["hide_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=3, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 3
        assert req["range"]["endIndex"] == 4
        assert req["range"]["dimension"] == "ROWS"
        assert req["properties"] == {"hiddenByUser": True}
        assert req["fields"] == "hiddenByUser"

    async def test_range_of_rows_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["hide_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=2, end_row=5, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 2
        assert req["range"]["endIndex"] == 6  # end_row=5 inclusive → exclusive index 6

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["hide_rows"](
            spreadsheet_id="ss1", sheet="Missing", start_row=0, ctx=ctx
        )
        assert "error" in result


class TestUnhideRows:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _dimension_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateDimensionProperties"]

    async def test_single_row_sets_hidden_false(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["unhide_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=3, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 3
        assert req["range"]["endIndex"] == 4
        assert req["range"]["dimension"] == "ROWS"
        assert req["properties"] == {"hiddenByUser": False}

    async def test_range_of_rows_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["unhide_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=2, end_row=5, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 2
        assert req["range"]["endIndex"] == 6

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["unhide_rows"](
            spreadsheet_id="ss1", sheet="Missing", start_row=0, ctx=ctx
        )
        assert "error" in result


class TestHideColumns:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _dimension_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateDimensionProperties"]

    async def test_single_column_end_index_is_start_plus_one(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["hide_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=0, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 0
        assert req["range"]["endIndex"] == 1
        assert req["range"]["dimension"] == "COLUMNS"
        assert req["properties"] == {"hiddenByUser": True}

    async def test_range_of_columns_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["hide_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=1, end_column=3, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 1
        assert req["range"]["endIndex"] == 4  # end_column=3 inclusive → exclusive index 4

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["hide_columns"](
            spreadsheet_id="ss1", sheet="Missing", start_column=0, ctx=ctx
        )
        assert "error" in result


class TestUnhideColumns:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _dimension_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateDimensionProperties"]

    async def test_single_column_sets_hidden_false(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["unhide_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=0, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 0
        assert req["range"]["endIndex"] == 1
        assert req["range"]["dimension"] == "COLUMNS"
        assert req["properties"] == {"hiddenByUser": False}

    async def test_range_of_columns_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["unhide_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=1, end_column=3, ctx=ctx
        )
        req = self._dimension_request(svc)
        assert req["range"]["startIndex"] == 1
        assert req["range"]["endIndex"] == 4

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["unhide_columns"](
            spreadsheet_id="ss1", sheet="Missing", start_column=0, ctx=ctx
        )
        assert "error" in result


class TestResizeRows:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]

    async def test_pixel_size_sets_updateDimensionProperties(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["resize_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=3, pixel_size=50, ctx=ctx
        )
        req = self._request(svc)["updateDimensionProperties"]
        assert req["range"]["startIndex"] == 3
        assert req["range"]["endIndex"] == 4
        assert req["range"]["dimension"] == "ROWS"
        assert req["properties"] == {"pixelSize": 50}
        assert req["fields"] == "pixelSize"

    async def test_range_of_rows_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["resize_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=2, end_row=5, pixel_size=30, ctx=ctx
        )
        req = self._request(svc)["updateDimensionProperties"]
        assert req["range"]["startIndex"] == 2
        assert req["range"]["endIndex"] == 6  # end_row=5 inclusive → exclusive index 6

    async def test_auto_resize_sets_autoResizeDimensions(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["resize_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=3, auto_resize=True, ctx=ctx
        )
        req = self._request(svc)["autoResizeDimensions"]
        assert req["dimensions"]["startIndex"] == 3
        assert req["dimensions"]["endIndex"] == 4
        assert req["dimensions"]["dimension"] == "ROWS"

    async def test_returns_error_when_neither_option_given(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["resize_rows"](
            spreadsheet_id="ss1", sheet="Sheet1", start_row=0, ctx=ctx
        )
        assert "error" in result

    async def test_returns_error_when_both_options_given(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["resize_rows"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            start_row=0,
            pixel_size=50,
            auto_resize=True,
            ctx=ctx,
        )
        assert "error" in result

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["resize_rows"](
            spreadsheet_id="ss1", sheet="Missing", start_row=0, pixel_size=50, ctx=ctx
        )
        assert "error" in result


class TestResizeColumns:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]

    async def test_pixel_size_sets_updateDimensionProperties(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["resize_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=0, pixel_size=120, ctx=ctx
        )
        req = self._request(svc)["updateDimensionProperties"]
        assert req["range"]["startIndex"] == 0
        assert req["range"]["endIndex"] == 1
        assert req["range"]["dimension"] == "COLUMNS"
        assert req["properties"] == {"pixelSize": 120}
        assert req["fields"] == "pixelSize"

    async def test_range_of_columns_end_index_is_inclusive(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["resize_columns"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            start_column=1,
            end_column=3,
            pixel_size=80,
            ctx=ctx,
        )
        req = self._request(svc)["updateDimensionProperties"]
        assert req["range"]["startIndex"] == 1
        assert req["range"]["endIndex"] == 4  # end_column=3 inclusive → exclusive index 4

    async def test_auto_resize_sets_autoResizeDimensions(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["resize_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=0, auto_resize=True, ctx=ctx
        )
        req = self._request(svc)["autoResizeDimensions"]
        assert req["dimensions"]["startIndex"] == 0
        assert req["dimensions"]["endIndex"] == 1
        assert req["dimensions"]["dimension"] == "COLUMNS"

    async def test_returns_error_when_neither_option_given(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["resize_columns"](
            spreadsheet_id="ss1", sheet="Sheet1", start_column=0, ctx=ctx
        )
        assert "error" in result

    async def test_returns_error_when_both_options_given(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["resize_columns"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            start_column=0,
            pixel_size=80,
            auto_resize=True,
            ctx=ctx,
        )
        assert "error" in result

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["resize_columns"](
            spreadsheet_id="ss1", sheet="Missing", start_column=0, pixel_size=80, ctx=ctx
        )
        assert "error" in result


class TestFormatCells:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _repeat_cell_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["repeatCell"]

    async def test_bold_sets_text_format_and_field(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["format_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:B2", bold=True, ctx=ctx
        )
        rc = self._repeat_cell_request(svc)
        assert rc["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True
        assert "userEnteredFormat.textFormat" in rc["fields"]

    async def test_background_color_sets_field(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        color = {"red": 1.0, "green": 0.0, "blue": 0.0}
        await _structure_tools["format_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", background_color=color, ctx=ctx
        )
        rc = self._repeat_cell_request(svc)
        assert rc["cell"]["userEnteredFormat"]["backgroundColor"] == color
        assert "userEnteredFormat.backgroundColor" in rc["fields"]

    async def test_horizontal_alignment_uppercased(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["format_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", horizontal_alignment="center", ctx=ctx
        )
        rc = self._repeat_cell_request(svc)
        assert rc["cell"]["userEnteredFormat"]["horizontalAlignment"] == "CENTER"

    async def test_number_format_type_and_pattern(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["format_cells"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:A10",
            number_format_type="number",
            number_format_pattern="#,##0.00",
            ctx=ctx,
        )
        rc = self._repeat_cell_request(svc)
        nf = rc["cell"]["userEnteredFormat"]["numberFormat"]
        assert nf["type"] == "NUMBER"
        assert nf["pattern"] == "#,##0.00"

    async def test_no_params_returns_error(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["format_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["format_cells"](
            spreadsheet_id="ss1", sheet="Missing", range="A1", bold=True, ctx=ctx
        )
        assert "error" in result

    async def test_multiple_format_params_produce_multiple_fields(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["format_cells"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1",
            bold=True,
            background_color={"red": 0.5},
            horizontal_alignment="LEFT",
            ctx=ctx,
        )
        rc = self._repeat_cell_request(svc)
        fields = rc["fields"]
        assert "userEnteredFormat.textFormat" in fields
        assert "userEnteredFormat.backgroundColor" in fields
        assert "userEnteredFormat.horizontalAlignment" in fields


class TestUpdateBorders:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _update_borders_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateBorders"]

    async def test_top_border_sets_style_and_range(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_borders"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:D5",
            top={"style": "SOLID"},
            ctx=ctx,
        )
        req = self._update_borders_request(svc)
        assert req["top"]["style"] == "SOLID"
        assert req["range"] == {
            "sheetId": 0,
            "startRowIndex": 0,
            "startColumnIndex": 0,
            "endRowIndex": 5,
            "endColumnIndex": 4,
        }

    async def test_color_and_width_included_when_present(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        color = {"red": 1.0, "green": 0.0, "blue": 0.0}
        await _structure_tools["update_borders"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1",
            bottom={"style": "DASHED", "color": color, "width": 2},
            ctx=ctx,
        )
        req = self._update_borders_request(svc)
        assert req["bottom"] == {"style": "DASHED", "color": color, "width": 2}

    async def test_style_is_uppercased(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_borders"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", left={"style": "solid"}, ctx=ctx
        )
        req = self._update_borders_request(svc)
        assert req["left"]["style"] == "SOLID"

    async def test_multiple_edges_produce_multiple_keys(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_borders"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:C3",
            top={"style": "SOLID"},
            bottom={"style": "SOLID"},
            inner_horizontal={"style": "DOTTED"},
            inner_vertical={"style": "DOTTED"},
            ctx=ctx,
        )
        req = self._update_borders_request(svc)
        assert "top" in req
        assert "bottom" in req
        assert "innerHorizontal" in req
        assert "innerVertical" in req
        assert "left" not in req
        assert "right" not in req

    async def test_none_style_clears_border(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_borders"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", right={"style": "NONE"}, ctx=ctx
        )
        req = self._update_borders_request(svc)
        assert req["right"]["style"] == "NONE"

    async def test_no_params_returns_error(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["update_borders"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_missing_style_returns_error(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["update_borders"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", top={"color": {"red": 1.0}}, ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_invalid_style_returns_error(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["update_borders"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", top={"style": "SQUIGGLY"}, ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_non_string_style_returns_error(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        for bad_style in (5, None):
            result = await _structure_tools["update_borders"](
                spreadsheet_id="ss1", sheet="Sheet1", range="A1", top={"style": bad_style}, ctx=ctx
            )
            assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["update_borders"](
            spreadsheet_id="ss1", sheet="Missing", range="A1", top={"style": "SOLID"}, ctx=ctx
        )
        assert "error" in result


class TestAddDataValidation:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _set_data_validation_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["setDataValidation"]

    async def test_one_of_list_sets_condition_and_values(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A2:A100",
            condition_type="one_of_list",
            values=["Yes", "No", "Maybe"],
            ctx=ctx,
        )
        req = self._set_data_validation_request(svc)
        rule = req["rule"]
        assert rule["condition"]["type"] == "ONE_OF_LIST"
        assert rule["condition"]["values"] == [
            {"userEnteredValue": "Yes"},
            {"userEnteredValue": "No"},
            {"userEnteredValue": "Maybe"},
        ]
        assert rule["strict"] is True
        assert rule["showCustomUi"] is True

    async def test_boolean_without_values_omits_condition_values(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="B2:B10",
            condition_type="boolean",
            ctx=ctx,
        )
        req = self._set_data_validation_request(svc)
        assert req["rule"]["condition"] == {"type": "BOOLEAN"}

    async def test_custom_formula_passes_formula_string_through(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="C2:C10",
            condition_type="custom_formula",
            values=["=C2>0"],
            ctx=ctx,
        )
        req = self._set_data_validation_request(svc)
        assert req["rule"]["condition"]["values"] == [{"userEnteredValue": "=C2>0"}]

    async def test_strict_false_and_show_custom_ui_false_pass_through(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1",
            condition_type="NUMBER_GREATER",
            values=["0"],
            strict=False,
            show_custom_ui=False,
            ctx=ctx,
        )
        req = self._set_data_validation_request(svc)
        assert req["rule"]["strict"] is False
        assert req["rule"]["showCustomUi"] is False

    async def test_input_message_included_when_provided(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1",
            condition_type="NOT_BLANK",
            input_message="This field is required",
            ctx=ctx,
        )
        req = self._set_data_validation_request(svc)
        assert req["rule"]["inputMessage"] == "This field is required"

    async def test_range_maps_to_grid_range_indices(self):
        svc = self._sheets_service(sheet_id=42)
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="B2:C5",
            condition_type="NOT_BLANK",
            ctx=ctx,
        )
        req = self._set_data_validation_request(svc)
        assert req["range"] == {
            "sheetId": 42,
            "startRowIndex": 1,
            "startColumnIndex": 1,
            "endRowIndex": 5,
            "endColumnIndex": 3,
        }

    async def test_invalid_condition_type_returns_error_without_api_call(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1",
            condition_type="NOT_A_REAL_TYPE",
            ctx=ctx,
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["add_data_validation"](
            spreadsheet_id="ss1",
            sheet="Missing",
            range="A1",
            condition_type="NOT_BLANK",
            ctx=ctx,
        )
        assert "error" in result


class TestGetDataValidation:
    def _sheets_service(self, grid_data):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"data": [grid_data]}]
        }
        return mock

    async def test_returns_cells_that_have_a_rule_skips_ones_that_dont(self):
        rule = {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
        grid_data = {
            "startRow": 0,
            "startColumn": 0,
            "rowData": [
                {"values": [{"dataValidation": rule}, {}]},
                {"values": [{}, {"dataValidation": rule}]},
            ],
        }
        svc = self._sheets_service(grid_data)
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["get_data_validation"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:B2", ctx=ctx
        )
        assert result == [
            {"cell": "A1", "rule": rule},
            {"cell": "B2", "rule": rule},
        ]

    async def test_offsets_use_start_row_and_start_column(self):
        rule = {"condition": {"type": "NOT_BLANK"}, "strict": True, "showCustomUi": True}
        grid_data = {
            "startRow": 4,
            "startColumn": 2,
            "rowData": [{"values": [{"dataValidation": rule}]}],
        }
        svc = self._sheets_service(grid_data)
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["get_data_validation"](
            spreadsheet_id="ss1", sheet="Sheet1", range="C5", ctx=ctx
        )
        assert result == [{"cell": "C5", "rule": rule}]

    async def test_no_validation_in_range_returns_empty_list(self):
        grid_data = {
            "startRow": 0,
            "startColumn": 0,
            "rowData": [{"values": [{}, {}]}],
        }
        svc = self._sheets_service(grid_data)
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["get_data_validation"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:B1", ctx=ctx
        )
        assert result == []

    async def test_no_sheets_in_response_returns_empty_list(self):
        svc = MagicMock()
        svc.spreadsheets.return_value.get.return_value.execute.return_value = {"sheets": []}
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["get_data_validation"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1", ctx=ctx
        )
        assert result == []


class TestMergeCells:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _merge_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["mergeCells"]

    async def test_default_merge_type_is_merge_all(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["merge_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:C3", ctx=ctx
        )
        assert self._merge_request(svc)["mergeType"] == "MERGE_ALL"

    async def test_merge_type_uppercased(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["merge_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:C3", merge_type="merge_rows", ctx=ctx
        )
        assert self._merge_request(svc)["mergeType"] == "MERGE_ROWS"

    async def test_range_translated_to_grid_range(self):
        svc = self._sheets_service(sheet_id=5)
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["merge_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="B2:D4", ctx=ctx
        )
        r = self._merge_request(svc)["range"]
        assert r["sheetId"] == 5
        assert r["startRowIndex"] == 1
        assert r["startColumnIndex"] == 1

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["merge_cells"](
            spreadsheet_id="ss1", sheet="Missing", range="A1:B2", ctx=ctx
        )
        assert "error" in result


class TestUnmergeCells:
    def _sheets_service(self):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": 0}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    async def test_sends_unmerge_request(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["unmerge_cells"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:C3", ctx=ctx
        )
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        assert "unmergeCells" in body["requests"][0]

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["unmerge_cells"](
            spreadsheet_id="ss1", sheet="Missing", range="A1:B2", ctx=ctx
        )
        assert "error" in result


class TestFreeze:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _update_props_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateSheetProperties"]

    async def test_freeze_rows_sets_frozen_row_count(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["freeze"](spreadsheet_id="ss1", sheet="Sheet1", rows=1, ctx=ctx)
        props = self._update_props_request(svc)
        assert props["properties"]["gridProperties"]["frozenRowCount"] == 1

    async def test_freeze_columns_sets_frozen_column_count(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["freeze"](spreadsheet_id="ss1", sheet="Sheet1", columns=2, ctx=ctx)
        props = self._update_props_request(svc)
        assert props["properties"]["gridProperties"]["frozenColumnCount"] == 2

    async def test_freeze_both_rows_and_columns(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["freeze"](
            spreadsheet_id="ss1", sheet="Sheet1", rows=1, columns=1, ctx=ctx
        )
        grid = self._update_props_request(svc)["properties"]["gridProperties"]
        assert grid["frozenRowCount"] == 1
        assert grid["frozenColumnCount"] == 1

    async def test_fields_mask_covers_both_frozen_counts(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["freeze"](spreadsheet_id="ss1", sheet="Sheet1", rows=1, ctx=ctx)
        fields = self._update_props_request(svc)["fields"]
        assert "frozenRowCount" in fields
        assert "frozenColumnCount" in fields

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["freeze"](spreadsheet_id="ss1", sheet="Missing", ctx=ctx)
        assert "error" in result


class TestUpdateSheetProperties:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _update_props_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["updateSheetProperties"]

    async def test_tab_color_sets_property_and_field(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        color = {"red": 1.0, "green": 0.0, "blue": 0.0}
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", tab_color=color, ctx=ctx
        )
        req = self._update_props_request(svc)
        assert req["properties"]["tabColor"] == color
        assert req["properties"]["sheetId"] == 0
        assert "tabColor" in req["fields"]

    async def test_empty_tab_color_dict_clears_color(self):
        """Passing {} should be treated as 'clear tab_color to default' via
        tabColorStyle, not tabColor — tabColor has no explicit-presence
        tracking on the wire, so an empty dict there is indistinguishable
        from black rather than "unset" (see docs/qa/tests/sheets_mgmt.md
        TC-S57b)."""
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", tab_color={}, ctx=ctx
        )
        req = self._update_props_request(svc)
        assert req["properties"]["tabColorStyle"] == {}
        assert "tabColor" not in req["properties"]
        field_list = req["fields"].split(",")
        assert "tabColorStyle" in field_list
        assert "tabColor" not in field_list

    async def test_show_gridlines_false_sets_hide_gridlines_true(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", show_gridlines=False, ctx=ctx
        )
        req = self._update_props_request(svc)
        assert req["properties"]["gridProperties"]["hideGridlines"] is True
        assert "gridProperties.hideGridlines" in req["fields"]

    async def test_show_gridlines_true_sets_hide_gridlines_false(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", show_gridlines=True, ctx=ctx
        )
        req = self._update_props_request(svc)
        assert req["properties"]["gridProperties"]["hideGridlines"] is False

    async def test_right_to_left_sets_property_and_field(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", right_to_left=True, ctx=ctx
        )
        req = self._update_props_request(svc)
        assert req["properties"]["rightToLeft"] is True
        assert "rightToLeft" in req["fields"]

    async def test_multiple_properties_produce_multiple_fields(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        color = {"red": 0.2, "green": 0.4, "blue": 0.6}
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            tab_color=color,
            show_gridlines=False,
            right_to_left=True,
            ctx=ctx,
        )
        req = self._update_props_request(svc)
        assert "tabColor" in req["fields"]
        assert "gridProperties.hideGridlines" in req["fields"]
        assert "rightToLeft" in req["fields"]
        assert req["properties"]["tabColor"] == color
        assert req["properties"]["gridProperties"]["hideGridlines"] is True
        assert req["properties"]["rightToLeft"] is True

    async def test_no_params_returns_error(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Missing", right_to_left=True, ctx=ctx
        )
        assert "error" in result
        assert not svc.spreadsheets.return_value.batchUpdate.called

    async def test_sheet_id_included_in_properties(self):
        svc = self._sheets_service(sheet_id=42)
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["update_sheet_properties"](
            spreadsheet_id="ss1", sheet="Sheet1", show_gridlines=False, ctx=ctx
        )
        req = self._update_props_request(svc)
        assert req["properties"]["sheetId"] == 42


class TestSortRange:
    def _sheets_service(self, sheet_id=0):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": sheet_id}}]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        return mock

    def _sort_request(self, svc):
        body = svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return body["requests"][0]["sortRange"]

    async def test_default_sort_is_first_column_ascending(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["sort_range"](
            spreadsheet_id="ss1", sheet="Sheet1", range="A1:D10", ctx=ctx
        )
        specs = self._sort_request(svc)["sortSpecs"]
        assert len(specs) == 1
        assert specs[0]["sortOrder"] == "ASCENDING"
        assert specs[0]["dimensionIndex"] == 0  # column A

    async def test_sort_order_uppercased(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["sort_range"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:D10",
            sort_order=[{"column_index": 1, "order": "descending"}],
            ctx=ctx,
        )
        specs = self._sort_request(svc)["sortSpecs"]
        assert specs[0]["sortOrder"] == "DESCENDING"

    async def test_column_index_offset_by_range_start(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        # range starts at column B (index 1); sort_order column_index 0 → dimensionIndex 1
        await _structure_tools["sort_range"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="B1:D10",
            sort_order=[{"column_index": 0, "order": "ASCENDING"}],
            ctx=ctx,
        )
        specs = self._sort_request(svc)["sortSpecs"]
        assert specs[0]["dimensionIndex"] == 1

    async def test_multiple_sort_specs(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        await _structure_tools["sort_range"](
            spreadsheet_id="ss1",
            sheet="Sheet1",
            range="A1:C10",
            sort_order=[
                {"column_index": 0, "order": "ASCENDING"},
                {"column_index": 2, "order": "DESCENDING"},
            ],
            ctx=ctx,
        )
        specs = self._sort_request(svc)["sortSpecs"]
        assert len(specs) == 2
        assert specs[1]["dimensionIndex"] == 2
        assert specs[1]["sortOrder"] == "DESCENDING"

    async def test_returns_error_when_sheet_not_found(self):
        svc = self._sheets_service()
        ctx = _make_ctx(sheets_service=svc, cache=None)
        result = await _structure_tools["sort_range"](
            spreadsheet_id="ss1", sheet="Missing", range="A1:D10", ctx=ctx
        )
        assert "error" in result
