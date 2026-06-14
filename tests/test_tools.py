"""Regression tests for four bugs fixed in the post-merge code review."""

import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.drive import files as drive_files_module
from mcp_gee_sweet.tools.drive import transfer as drive_transfer_module
from mcp_gee_sweet.tools.sheets import data as sheets_data_module
from mcp_gee_sweet.tools.sheets import structure as sheets_structure_module


def _make_tool_registry():
    """Capture tool functions by name without going through FastMCP."""
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


# add_chart is now in sheets.structure
_charts_tool, _charts_tools = _make_tool_registry()
sheets_structure_module.register(_charts_tool)

# drive tools split across files, transfer, and docs
_drive_tool, _drive_tools = _make_tool_registry()
drive_files_module.register(_drive_tool)
drive_transfer_module.register(_drive_tool)
docs_module.register(_drive_tool)

# copy_sheet is now in sheets.structure
_sheets_tool, _sheets_tools = _make_tool_registry()
sheets_structure_module.register(_sheets_tool)

# batch_update is now in sheets.data
_write_tool, _write_tools = _make_tool_registry()
sheets_data_module.register(_write_tool)


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
        return _charts_tools["add_chart"](
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


class TestSearchSpreadsheetsQueryEscape:
    """Bug: single quotes in query were interpolated raw into the Drive query string."""

    def _drive_service(self):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": []}
        return mock

    def _captured_q(self, drive_svc):
        return drive_svc.files.return_value.list.call_args.kwargs["q"]

    def test_single_quote_is_escaped(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        _drive_tools["search_spreadsheets"](query="it's a test", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    def test_escaped_form_used_not_raw(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        _drive_tools["search_spreadsheets"](query="O'Brien", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "O\\'Brien" in q
        # The apostrophe in 'O'Brien' must be preceded by a backslash
        idx = q.index("'Brien")
        assert q[idx - 1] == "\\"

    def test_query_without_quotes_passes_through(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        _drive_tools["search_spreadsheets"](query="budget 2024", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "budget 2024" in q


class TestCreateDocHtmlFormatting:
    """Bug: create_doc used _html_to_text (plain text) instead of _html_to_doc_requests."""

    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "Test",
            "parents": ["folder1"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _make_ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_h1_produces_heading_style(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_list_item_produces_bullet(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content="<li>Item</li>", ctx=ctx)
        bullets = [r for r in self._batchupdate_requests(docs_svc) if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_no_content_skips_batchupdate(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content=None, ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    def test_inline_only_html_skips_batchupdate(self):
        """Tags with no block-level elements produce no requests; batchUpdate should not fire."""
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content="<span>no blocks</span>", ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called


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
        _sheets_tools["copy_sheet"](
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
        _sheets_tools["copy_sheet"](
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
        _sheets_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Target Name",
            ctx=ctx,
        )
        assert not mock_sheets.spreadsheets.return_value.batchUpdate.called


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
        _write_tools["batch_update"](
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
        _write_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"updateCells": {}}],
            ctx=ctx,
        )
        mock_data_cache.mark_dirty.assert_called_once_with("abc123")


class TestDriveFolderCacheInvalidation:
    """Verify that mutating Drive tools call drive_folder_cache.mark_dirty."""

    def _drive_file_response(self, **kwargs):
        defaults = {
            "id": "fid1",
            "name": "file.txt",
            "parents": ["parent1"],
            "mimeType": "text/plain",
            "webViewLink": "https://example.com",
        }
        return {**defaults, **kwargs}

    def test_create_folder_with_parent_marks_dirty(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder",
            "name": "MyFolder",
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        _drive_tools["create_folder"](name="MyFolder", parent_folder_id="par1", ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    def test_create_folder_without_parent_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder",
            "name": "MyFolder",
            "parents": [],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        _drive_tools["create_folder"](name="MyFolder", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()

    def test_move_file_marks_old_and_new_parent_dirty(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["old_par"]}
        mock.files.return_value.update.return_value.execute.return_value = (
            self._drive_file_response(parents=["dest_par"])
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        _drive_tools["move_file"](file_id="fid1", destination_folder_id="dest_par", ctx=ctx)
        calls = [c.args[0] for c in folder_cache.mark_dirty.call_args_list]
        assert "old_par" in calls
        assert "dest_par" in calls

    def test_delete_file_trash_marks_parent_dirty_before_trash(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        mock.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        _drive_tools["delete_file"](file_id="fid1", permanent=False, ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    def test_delete_file_permanent_marks_parent_dirty_before_delete(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        mock.files.return_value.delete.return_value.execute.return_value = None
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    def test_upload_file_quota_exceeded_returns_error_dict(self):
        """upload_file should return {"error": ...} on storageQuotaExceeded, not raise."""
        resp = MagicMock()
        resp.status = 403
        quota_err = HttpError(resp=resp, content=b'{"error": {"reason": "storageQuotaExceeded"}}')
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = quota_err
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        result = _drive_tools["upload_file"](name="test.txt", content="hello", ctx=ctx)
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]  # raw message replaced
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    def test_upload_file_with_folder_marks_dirty(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = (
            self._drive_file_response()
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(
            drive_service=mock, drive_folder_cache=folder_cache, folder_id="default_folder"
        )
        _drive_tools["upload_file"](
            name="doc.txt", content="hello", folder_id="target_folder", ctx=ctx
        )
        folder_cache.mark_dirty.assert_called_once_with("target_folder")


def _quota_http_error():
    """Build a 403 storageQuotaExceeded HttpError as returned by the Drive API."""
    resp = MagicMock()
    resp.status = 403
    return HttpError(
        resp=resp,
        content=b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}',
    )


def _other_403_error():
    """Build a generic 403 that is NOT quota-related."""
    resp = MagicMock()
    resp.status = 403
    return HttpError(resp=resp, content=b'{"error": {"reason": "forbidden"}}')


class TestServiceAccountQuotaErrors:
    """Tools that create Drive files return a helpful error dict on storageQuotaExceeded.

    The raw Google 403 is replaced with an actionable message pointing the caller
    at server://auth-status and suggesting OAuth/ADC.  Non-quota 403s must still
    propagate so callers can distinguish permission errors from quota errors.
    """

    def _quota_create_drive(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        return mock

    def _quota_copy_drive(self):
        mock = MagicMock()
        mock.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        return mock

    def _assert_helpful_error(self, result):
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    def test_create_spreadsheet_quota_returns_error_dict(self):
        ctx = _make_ctx(
            drive_service=self._quota_create_drive(),
            drive_folder_cache=MagicMock(),
            folder_id=None,
        )
        result = _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)
        self._assert_helpful_error(result)

    def test_create_doc_quota_returns_error_dict(self):
        ctx = _make_ctx(
            drive_service=self._quota_create_drive(),
            docs_service=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id=None,
        )
        result = _drive_tools["create_doc"](title="Test", ctx=ctx)
        self._assert_helpful_error(result)

    def test_copy_file_quota_returns_error_dict(self):
        ctx = _make_ctx(
            drive_service=self._quota_copy_drive(),
            drive_folder_cache=MagicMock(),
        )
        result = _drive_tools["copy_file"](file_id="fid", ctx=ctx)
        self._assert_helpful_error(result)

    def test_create_spreadsheet_non_quota_403_still_raises(self):
        """A 403 that is not storageQuotaExceeded must propagate — not be swallowed."""
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(
            drive_service=mock,
            drive_folder_cache=MagicMock(),
            folder_id=None,
        )
        with pytest.raises(HttpError):
            _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)

    def test_create_doc_non_quota_403_still_raises(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(
            drive_service=mock,
            docs_service=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id=None,
        )
        with pytest.raises(HttpError):
            _drive_tools["create_doc"](title="Test", ctx=ctx)


class TestAuthStatusResource:
    """server://auth-status resource returns correct capabilities per auth method."""

    def _get_status(self, auth_method):
        from mcp_gee_sweet.server import _auth_status_json

        return json.loads(_auth_status_json(auth_method))

    def test_service_account_cannot_create_in_personal_drive(self):
        status = self._get_status("service_account")
        assert status["auth_method"] == "service_account"
        assert status["can_create_in_personal_drive"] is False

    def test_service_account_lists_limited_tools(self):
        status = self._get_status("service_account")
        assert len(status["limited_tools"]) > 0
        assert "create_spreadsheet" in status["limited_tools"]
        assert "create_doc" in status["limited_tools"]
        assert "copy_file" in status["limited_tools"]
        assert "upload_file" in status["limited_tools"]

    def test_service_account_includes_reason_and_alternative(self):
        status = self._get_status("service_account")
        assert status["reason"] is not None
        assert "storage quota" in status["reason"].lower()
        assert status["alternatives"] is not None

    def test_oauth_can_create_in_personal_drive(self):
        status = self._get_status("oauth")
        assert status["auth_method"] == "oauth"
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
        assert status["reason"] is None

    def test_adc_can_create_in_personal_drive(self):
        status = self._get_status("adc")
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
