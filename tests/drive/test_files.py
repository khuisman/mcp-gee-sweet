"""Tests for tools/drive/files.py (search_spreadsheets, create_folder, move_file, delete_file, etc.)."""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools.drive import files as drive_files_module


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


_drive_tool, _drive_tools = _make_tool_registry()
drive_files_module.register(_drive_tool)


class TestSearchSpreadsheets:
    """Bug: single quotes in query were interpolated raw into the Drive query string."""

    def _drive_service(self):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": []}
        return mock

    def _captured_q(self, drive_svc):
        return drive_svc.files.return_value.list.call_args.kwargs["q"]

    async def test_single_quote_is_escaped(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="it's a test", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    async def test_escaped_form_used_not_raw(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="O'Brien", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "O\\'Brien" in q
        # The apostrophe in 'O'Brien' must be preceded by a backslash
        idx = q.index("'Brien")
        assert q[idx - 1] == "\\"

    async def test_query_without_quotes_passes_through(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="budget 2024", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "budget 2024" in q


class TestFileMutations:
    """Mutating file ops (create_folder, move_file, delete_file) must invalidate the folder cache."""

    def _drive_file_response(self, **kwargs):
        defaults = {
            "id": "fid1",
            "name": "file.txt",
            "parents": ["parent1"],
            "mimeType": "text/plain",
            "webViewLink": "https://example.com",
        }
        return {**defaults, **kwargs}

    async def test_create_folder_with_parent_marks_dirty(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder",
            "name": "MyFolder",
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        await _drive_tools["create_folder"](name="MyFolder", parent_folder_id="par1", ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_create_folder_without_parent_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder",
            "name": "MyFolder",
            "parents": [],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        await _drive_tools["create_folder"](name="MyFolder", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()

    async def test_move_file_marks_old_and_new_parent_dirty(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["old_par"]}
        mock.files.return_value.update.return_value.execute.return_value = (
            self._drive_file_response(parents=["dest_par"])
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["move_file"](file_id="fid1", destination_folder_id="dest_par", ctx=ctx)
        calls = [c.args[0] for c in folder_cache.mark_dirty.call_args_list]
        assert "old_par" in calls
        assert "dest_par" in calls

    async def test_delete_file_trash_marks_parent_dirty_before_trash(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        mock.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["delete_file"](file_id="fid1", permanent=False, ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_delete_file_permanent_marks_parent_dirty_before_delete(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        mock.files.return_value.delete.return_value.execute.return_value = None
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_restore_file_marks_parent_dirty(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        result = await _drive_tools["restore_file"](file_id="fid1", ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"trashed": False},
            supportsAllDrives=True,
            fields="id,parents",
        )
        folder_cache.mark_dirty.assert_called_once_with("par1")
        assert result == {"fileId": "fid1", "action": "restored"}

    async def test_restore_file_no_parents_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["restore_file"](file_id="fid1", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()

    async def test_empty_trash_defaults_to_my_drive_no_drive_id(self):
        mock = MagicMock()
        mock.files.return_value.emptyTrash.return_value.execute.return_value = {}
        ctx = _make_ctx(drive_service=mock)
        result = await _drive_tools["empty_trash"](ctx=ctx)
        mock.files.return_value.emptyTrash.assert_called_once_with()
        assert result == {"action": "trash_emptied", "drive_id": None}

    async def test_empty_trash_with_drive_id_scopes_to_shared_drive(self):
        mock = MagicMock()
        mock.files.return_value.emptyTrash.return_value.execute.return_value = {}
        ctx = _make_ctx(drive_service=mock)
        result = await _drive_tools["empty_trash"](drive_id="shared1", ctx=ctx)
        mock.files.return_value.emptyTrash.assert_called_once_with(driveId="shared1")
        assert result == {"action": "trash_emptied", "drive_id": "shared1"}

    async def test_restore_file_nonexistent_id_propagates_error(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        with pytest.raises(HttpError):
            await _drive_tools["restore_file"](file_id="invalidid123xyz", ctx=ctx)

    async def test_empty_trash_api_error_propagates(self):
        mock = MagicMock()
        mock.files.return_value.emptyTrash.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock)
        with pytest.raises(HttpError):
            await _drive_tools["empty_trash"](ctx=ctx)


class TestStarFile:
    """star_file/unstar_file (#139) set starred via files().update, no folder-cache impact."""

    async def test_star_file_sets_starred_true(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": True,
        }
        ctx = _make_ctx(drive_service=mock)
        result = await _drive_tools["star_file"](file_id="fid1", ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"starred": True},
            supportsAllDrives=True,
            fields="id, name, starred",
        )
        assert result == {"fileId": "fid1", "name": "file.txt", "starred": True}

    async def test_unstar_file_sets_starred_false(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": False,
        }
        ctx = _make_ctx(drive_service=mock)
        result = await _drive_tools["unstar_file"](file_id="fid1", ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"starred": False},
            supportsAllDrives=True,
            fields="id, name, starred",
        )
        assert result == {"fileId": "fid1", "name": "file.txt", "starred": False}


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


class TestQuotaErrors:
    """create_spreadsheet and copy_file return a helpful error dict on storageQuotaExceeded.

    The raw Google 403 is replaced with an actionable message pointing the caller
    at server://auth-status and suggesting OAuth/ADC.  Non-quota 403s must still
    propagate so callers can distinguish permission errors from quota errors.
    """

    def _assert_helpful_error(self, result):
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    async def test_create_spreadsheet_quota_returns_error_dict(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        result = await _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)
        self._assert_helpful_error(result)

    async def test_copy_file_quota_returns_error_dict(self):
        mock = MagicMock()
        mock.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        result = await _drive_tools["copy_file"](file_id="fid", ctx=ctx)
        self._assert_helpful_error(result)

    async def test_create_spreadsheet_non_quota_403_still_raises(self):
        """A 403 that is not storageQuotaExceeded must propagate — not be swallowed."""
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        with pytest.raises(HttpError):
            await _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)


class TestListSharedWithMe:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _list_call_kwargs(self, svc):
        return svc.files.return_value.list.call_args.kwargs

    async def test_query_includes_shared_with_me(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](ctx=ctx)
        kw = self._list_call_kwargs(svc)
        assert "sharedWithMe=true" in kw["q"]
        assert "trashed=false" in kw["q"]

    async def test_mime_type_filter_added_to_query(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](
            mime_type="application/vnd.google-apps.spreadsheet", ctx=ctx
        )
        kw = self._list_call_kwargs(svc)
        assert "application/vnd.google-apps.spreadsheet" in kw["q"]

    async def test_max_results_capped_at_200(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](max_results=999, ctx=ctx)
        assert self._list_call_kwargs(svc)["pageSize"] == 200

    async def test_result_shape(self):
        svc = self._drive_service(
            files=[
                {
                    "id": "fid1",
                    "name": "Shared Doc",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "owners": [{"emailAddress": "owner@example.com"}],
                    "webViewLink": "https://docs.google.com/fid1",
                }
            ]
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["list_shared_with_me"](ctx=ctx)
        assert len(result) == 1
        assert result[0]["id"] == "fid1"
        assert result[0]["owners"] == ["owner@example.com"]


class TestListRecentFiles:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _list_call_kwargs(self, svc):
        return svc.files.return_value.list.call_args.kwargs

    async def test_orders_by_modified_time_desc(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](ctx=ctx)
        assert self._list_call_kwargs(svc)["orderBy"] == "modifiedTime desc"

    async def test_days_filter_adds_modified_time_constraint(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](days=7, ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "modifiedTime >" in q

    async def test_no_days_filter_omits_time_constraint(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "modifiedTime >" not in q

    async def test_max_results_capped_at_100(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](max_results=500, ctx=ctx)
        assert self._list_call_kwargs(svc)["pageSize"] == 100

    async def test_mime_type_filter_applied(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](mime_type="application/pdf", ctx=ctx)
        assert "application/pdf" in self._list_call_kwargs(svc)["q"]


class TestGetStorageQuota:
    def _drive_service(self, quota=None, user=None):
        mock = MagicMock()
        mock.about.return_value.get.return_value.execute.return_value = {
            "storageQuota": quota
            or {
                "limit": "16106127360",
                "usage": "1073741824",
                "usageInDrive": "1000000000",
                "usageInDriveTrash": "73741824",
            },
            "user": user
            or {
                "emailAddress": "test@example.com",
                "displayName": "Test User",
            },
        }
        return mock

    async def test_returns_byte_values_as_integers(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert isinstance(result["limit_bytes"], int)
        assert isinstance(result["usage_bytes"], int)
        assert result["limit_bytes"] == 16106127360

    async def test_no_limit_key_returns_none(self):
        svc = self._drive_service(
            quota={"usage": "0", "usageInDrive": "0", "usageInDriveTrash": "0"}
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["limit_bytes"] is None

    async def test_limit_zero_string_returns_zero(self):
        # SA accounts: Drive API returns "0" (not absent), which casts to int 0
        svc = self._drive_service(
            quota={"limit": "0", "usage": "0", "usageInDrive": "0", "usageInDriveTrash": "0"}
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["limit_bytes"] == 0

    async def test_includes_user_info(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["email"] == "test@example.com"
        assert result["display_name"] == "Test User"

    async def test_requests_correct_fields(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["get_storage_quota"](ctx=ctx)
        fields_arg = svc.about.return_value.get.call_args.kwargs["fields"]
        assert "storageQuota" in fields_arg
        assert "user" in fields_arg


class TestImportCsvToSheet:
    """import_csv_to_sheet: create a spreadsheet from a local CSV file."""

    def _drive_service(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "sheet123",
            "name": "Imported",
            "parents": ["folder1"],
            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123",
        }
        return mock

    def _sheets_service(self, sheet_title="Sheet1", row_count=1000, column_count=26):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [
                {
                    "properties": {
                        "sheetId": 0,
                        "title": sheet_title,
                        "gridProperties": {
                            "rowCount": row_count,
                            "columnCount": column_count,
                        },
                    }
                }
            ]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        mock.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}
        return mock

    def _write_csv(self, tmp_path, rows, name="data.csv"):
        path = tmp_path / name
        path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        return path

    async def test_file_not_found_returns_error(self):
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](
            local_path="/no/such/file.csv", title="X", ctx=ctx
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_unsupported_extension_returns_error(self, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" in result
        assert ".csv" in result["error"]

    async def test_empty_csv_returns_error(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" in result
        assert "empty" in result["error"].lower()

    async def test_creates_spreadsheet_and_writes_rows(self, tmp_path):
        path = self._write_csv(tmp_path, [["name", "age"], ["Alice", "30"], ["Bob", "25"]])
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        folder_cache = MagicMock()
        sheet_data_cache = MagicMock()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=folder_cache,
            sheet_data_cache=sheet_data_cache,
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="Imported", folder_id="folder1", ctx=ctx
        )

        assert result["spreadsheetId"] == "sheet123"
        assert result["title"] == "Imported"
        assert result["web_link"] == "https://docs.google.com/spreadsheets/d/sheet123"
        assert result["rows_written"] == 3

        update_call = sheets_svc.spreadsheets.return_value.values.return_value.update
        assert update_call.call_count == 1
        kwargs = update_call.call_args.kwargs
        assert kwargs["spreadsheetId"] == "sheet123"
        assert kwargs["range"] == "Sheet1!A1"
        assert kwargs["valueInputOption"] == "USER_ENTERED"
        assert kwargs["body"]["values"] == [
            ["name", "age"],
            ["Alice", "30"],
            ["Bob", "25"],
        ]
        folder_cache.mark_dirty.assert_called_once_with("folder1")
        sheet_data_cache.mark_dirty.assert_called_once_with("sheet123")
        # No resize/rename needed — default title matches, data fits default grid.
        sheets_svc.spreadsheets.return_value.batchUpdate.assert_not_called()

    async def test_pads_ragged_rows_to_common_width(self, tmp_path):
        path = tmp_path / "ragged.csv"
        path.write_text("a,b,c\n1,2\n", encoding="utf-8")
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        kwargs = sheets_svc.spreadsheets.return_value.values.return_value.update.call_args.kwargs
        assert kwargs["body"]["values"] == [["a", "b", "c"], ["1", "2", ""]]

    async def test_renames_default_sheet_when_sheet_name_differs(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service(sheet_title="Sheet1")
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="X", sheet_name="Imported Data", ctx=ctx
        )
        requests = sheets_svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"][
            "requests"
        ]
        assert requests[0]["updateSheetProperties"]["properties"]["title"] == "Imported Data"
        assert requests[0]["updateSheetProperties"]["properties"]["sheetId"] == 0
        assert requests[0]["updateSheetProperties"]["fields"] == "title"
        update_range = (
            sheets_svc.spreadsheets.return_value.values.return_value.update.call_args.kwargs[
                "range"
            ]
        )
        assert update_range == "'Imported Data'!A1"

    async def test_resizes_grid_when_data_exceeds_default(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"], ["2"], ["3"]])
        drive_svc = self._drive_service()
        # Force a resize by mocking a grid smaller than our 4-row CSV.
        sheets_svc = self._sheets_service(row_count=1, column_count=1)
        cache = MagicMock()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=cache,
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        requests = sheets_svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"][
            "requests"
        ]
        resize_req = next(
            r for r in requests if "gridProperties" in r["updateSheetProperties"]["properties"]
        )
        grid = resize_req["updateSheetProperties"]["properties"]["gridProperties"]
        assert grid["rowCount"] == 4
        assert grid["columnCount"] == 1
        cache.mark_dirty.assert_called_once_with("sheet123")

    async def test_no_resize_when_data_fits_default_grid(self, tmp_path):
        path = self._write_csv(tmp_path, [["a", "b"], ["1", "2"]])
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service(row_count=1000, column_count=26)
        cache = MagicMock()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=cache,
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        sheets_svc.spreadsheets.return_value.batchUpdate.assert_not_called()
        cache.mark_dirty.assert_not_called()

    async def test_chunks_large_row_counts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 2)
        rows = [["a"]] + [[str(i)] for i in range(5)]
        path = self._write_csv(tmp_path, rows)
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert result["rows_written"] == 6
        update_call = sheets_svc.spreadsheets.return_value.values.return_value.update
        assert update_call.call_count == 3
        # Chunks now write concurrently via asyncio.gather(), so completion order
        # (and thus call_args_list order) isn't guaranteed to match submission order —
        # compare as a set instead of an ordered list.
        ranges = {c.kwargs["range"] for c in update_call.call_args_list}
        assert ranges == {"Sheet1!A1", "Sheet1!A3", "Sheet1!A5"}

    async def test_partial_chunk_failure_reports_failed_and_written_ranges(
        self, tmp_path, monkeypatch
    ):
        """One chunk failing among several concurrent writes must not raise a bare
        exception — it must report exactly which row ranges failed vs. wrote
        successfully, since a concurrent partial failure can leave a hole mid-sheet
        rather than a clean truncated prefix (QA finding, #183)."""
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 2)
        rows = [["h"]] + [[str(i)] for i in range(6)]
        path = self._write_csv(tmp_path, rows)
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()

        def _make_update_mock(**update_kwargs):
            m = MagicMock()
            if update_kwargs.get("range") == "Sheet1!A3":
                m.execute.side_effect = RuntimeError("simulated API failure")
            else:
                m.execute.return_value = {}
            return m

        sheets_svc.spreadsheets.return_value.values.return_value.update.side_effect = (
            _make_update_mock
        )

        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)

        assert "error" in result
        assert result["spreadsheetId"] == "sheet123"
        assert result["failed_ranges"] == [
            {"start_row": 3, "end_row": 4, "error": "simulated API failure"}
        ]
        written_starts = {w["start_row"] for w in result["written_ranges"]}
        assert written_starts == {1, 5, 7}

    async def test_storage_quota_error_returns_helpful_message(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=drive_svc, sheets_service=MagicMock(), folder_id=None)
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert result["error"] == drive_files_module._SA_QUOTA_ERROR

    async def test_other_403_error_reraises(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(drive_service=drive_svc, sheets_service=MagicMock(), folder_id=None)
        with pytest.raises(HttpError):
            await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
