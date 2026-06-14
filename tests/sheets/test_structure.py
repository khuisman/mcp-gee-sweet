"""Tests for tools/sheets/structure.py (add_chart, copy_sheet, and related)."""

from unittest.mock import MagicMock

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


class TestChartBugs:
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

    def _call(self, sheets_svc, chart_type="COLUMN", data_range="A1:D5"):
        ctx = _make_ctx(sheets_service=sheets_svc, cache=None)
        return _structure_tools["add_chart"](
            spreadsheet_id="ss1",
            sheet="Sales",
            chart_type=chart_type,
            data_range=data_range,
            ctx=ctx,
        )

    # BUG-1 — per-column source ranges

    def test_domain_is_single_column(self):
        """BUG-1: domain source must span exactly one column, not the full range rectangle."""
        svc = self._sheets_service()
        self._call(svc, "COLUMN", "A1:D5")
        spec = self._chart_spec(svc)
        domain_src = spec["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]
        assert domain_src["endColumnIndex"] - domain_src["startColumnIndex"] == 1

    def test_domain_is_first_column(self):
        svc = self._sheets_service()
        self._call(svc, "LINE", "A1:C10")
        spec = self._chart_spec(svc)
        domain_src = spec["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]
        assert domain_src["startColumnIndex"] == 0
        assert domain_src["endColumnIndex"] == 1

    def test_series_count_matches_remaining_columns(self):
        """A1:D5 has 4 columns → 1 domain + 3 series."""
        svc = self._sheets_service()
        self._call(svc, "COLUMN", "A1:D5")
        spec = self._chart_spec(svc)
        assert len(spec["basicChart"]["series"]) == 3

    def test_each_series_is_single_column(self):
        svc = self._sheets_service()
        self._call(svc, "BAR", "A1:C5")
        spec = self._chart_spec(svc)
        for s in spec["basicChart"]["series"]:
            src = s["series"]["sourceRange"]["sources"][0]
            assert src["endColumnIndex"] - src["startColumnIndex"] == 1

    def test_series_columns_are_sequential(self):
        svc = self._sheets_service()
        self._call(svc, "AREA", "A1:C5")
        spec = self._chart_spec(svc)
        col_starts = [
            s["series"]["sourceRange"]["sources"][0]["startColumnIndex"]
            for s in spec["basicChart"]["series"]
        ]
        assert col_starts == [1, 2]

    def test_single_column_range_succeeds(self):
        """A single-column range (no separate series) must not error."""
        svc = self._sheets_service()
        result = self._call(svc, "LINE", "B1:B10")
        assert "error" not in result

    # BUG-2 — HISTOGRAM spec

    def test_histogram_uses_histogram_chart_spec(self):
        """BUG-2: HISTOGRAM must emit histogramChart, not basicChart."""
        svc = self._sheets_service()
        self._call(svc, "HISTOGRAM", "A1:A10")
        spec = self._chart_spec(svc)
        assert "histogramChart" in spec
        assert "basicChart" not in spec

    def test_histogram_series_one_per_column(self):
        svc = self._sheets_service()
        self._call(svc, "HISTOGRAM", "A1:B10")
        spec = self._chart_spec(svc)
        assert len(spec["histogramChart"]["series"]) == 2

    # PIE chart column splitting

    def test_pie_domain_is_first_column(self):
        svc = self._sheets_service()
        self._call(svc, "PIE", "A1:B5")
        spec = self._chart_spec(svc)
        src = spec["pieChart"]["domain"]["sourceRange"]["sources"][0]
        assert src["startColumnIndex"] == 0
        assert src["endColumnIndex"] == 1

    def test_pie_series_is_second_column(self):
        svc = self._sheets_service()
        self._call(svc, "PIE", "A1:B5")
        spec = self._chart_spec(svc)
        src = spec["pieChart"]["series"]["sourceRange"]["sources"][0]
        assert src["startColumnIndex"] == 1
        assert src["endColumnIndex"] == 2

    # BUG-3 — BAR targetAxis

    def test_bar_series_target_bottom_axis(self):
        """BUG-3: BAR charts have a horizontal value axis — series must target BOTTOM_AXIS."""
        svc = self._sheets_service()
        self._call(svc, "BAR", "A1:C5")
        spec = self._chart_spec(svc)
        axes = [s["targetAxis"] for s in spec["basicChart"]["series"]]
        assert all(a == "BOTTOM_AXIS" for a in axes)

    def test_non_bar_series_target_left_axis(self):
        svc = self._sheets_service()
        self._call(svc, "COLUMN", "A1:C5")
        spec = self._chart_spec(svc)
        axes = [s["targetAxis"] for s in spec["basicChart"]["series"]]
        assert all(a == "LEFT_AXIS" for a in axes)

    # BUG-4 — COMBO per-series type

    def test_combo_series_have_explicit_type(self):
        """BUG-4: COMBO requires a type on each series or the API returns 'No basic chart type specified'."""
        svc = self._sheets_service()
        self._call(svc, "COMBO", "A1:D5")
        spec = self._chart_spec(svc)
        for s in spec["basicChart"]["series"]:
            assert "type" in s

    def test_combo_last_series_is_line(self):
        svc = self._sheets_service()
        self._call(svc, "COMBO", "A1:D5")
        spec = self._chart_spec(svc)
        series = spec["basicChart"]["series"]
        assert series[-1]["type"] == "LINE"
        assert all(s["type"] == "COLUMN" for s in series[:-1])


class TestCopySheetRename:
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

    def test_rename_triggered_when_title_absent_from_response(self):
        """The old guard `if 'title' in copy_result` would silently skip this case."""
        mock_sheets = self._mock_sheets({"sheetId": 42})  # no "title" key
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        _structure_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="My Sheet",
            ctx=ctx,
        )
        assert mock_sheets.spreadsheets.return_value.batchUpdate.called
        assert "My Sheet" in self._rename_titles(mock_sheets)

    def test_rename_triggered_when_title_differs(self):
        mock_sheets = self._mock_sheets({"sheetId": 42, "title": "Copy of Sheet1"})
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        _structure_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Renamed",
            ctx=ctx,
        )
        assert mock_sheets.spreadsheets.return_value.batchUpdate.called

    def test_rename_skipped_when_title_already_matches(self):
        mock_sheets = self._mock_sheets({"sheetId": 42, "title": "Target Name"})
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        _structure_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Target Name",
            ctx=ctx,
        )
        assert not mock_sheets.spreadsheets.return_value.batchUpdate.called
