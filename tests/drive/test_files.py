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

    def test_create_spreadsheet_quota_returns_error_dict(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        result = _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)
        self._assert_helpful_error(result)

    def test_copy_file_quota_returns_error_dict(self):
        mock = MagicMock()
        mock.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        result = _drive_tools["copy_file"](file_id="fid", ctx=ctx)
        self._assert_helpful_error(result)

    def test_create_spreadsheet_non_quota_403_still_raises(self):
        """A 403 that is not storageQuotaExceeded must propagate — not be swallowed."""
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        with pytest.raises(HttpError):
            _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)


class TestListSharedWithMe:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _list_call_kwargs(self, svc):
        return svc.files.return_value.list.call_args.kwargs

    def test_query_includes_shared_with_me(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_shared_with_me"](ctx=ctx)
        kw = self._list_call_kwargs(svc)
        assert "sharedWithMe=true" in kw["q"]
        assert "trashed=false" in kw["q"]

    def test_mime_type_filter_added_to_query(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_shared_with_me"](
            mime_type="application/vnd.google-apps.spreadsheet", ctx=ctx
        )
        kw = self._list_call_kwargs(svc)
        assert "application/vnd.google-apps.spreadsheet" in kw["q"]

    def test_max_results_capped_at_200(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_shared_with_me"](max_results=999, ctx=ctx)
        assert self._list_call_kwargs(svc)["pageSize"] == 200

    def test_result_shape(self):
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
        result = _drive_tools["list_shared_with_me"](ctx=ctx)
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

    def test_orders_by_modified_time_desc(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_recent_files"](ctx=ctx)
        assert self._list_call_kwargs(svc)["orderBy"] == "modifiedTime desc"

    def test_days_filter_adds_modified_time_constraint(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_recent_files"](days=7, ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "modifiedTime >" in q

    def test_no_days_filter_omits_time_constraint(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_recent_files"](ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "modifiedTime >" not in q

    def test_max_results_capped_at_100(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_recent_files"](max_results=500, ctx=ctx)
        assert self._list_call_kwargs(svc)["pageSize"] == 100

    def test_mime_type_filter_applied(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["list_recent_files"](mime_type="application/pdf", ctx=ctx)
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

    def test_returns_byte_values_as_integers(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = _drive_tools["get_storage_quota"](ctx=ctx)
        assert isinstance(result["limit_bytes"], int)
        assert isinstance(result["usage_bytes"], int)
        assert result["limit_bytes"] == 16106127360

    def test_no_limit_key_returns_none(self):
        svc = self._drive_service(
            quota={"usage": "0", "usageInDrive": "0", "usageInDriveTrash": "0"}
        )
        ctx = _make_ctx(drive_service=svc)
        result = _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["limit_bytes"] is None

    def test_limit_zero_string_returns_zero(self):
        # SA accounts: Drive API returns "0" (not absent), which casts to int 0
        svc = self._drive_service(
            quota={"limit": "0", "usage": "0", "usageInDrive": "0", "usageInDriveTrash": "0"}
        )
        ctx = _make_ctx(drive_service=svc)
        result = _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["limit_bytes"] == 0

    def test_includes_user_info(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["email"] == "test@example.com"
        assert result["display_name"] == "Test User"

    def test_requests_correct_fields(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        _drive_tools["get_storage_quota"](ctx=ctx)
        fields_arg = svc.about.return_value.get.call_args.kwargs["fields"]
        assert "storageQuota" in fields_arg
        assert "user" in fields_arg
