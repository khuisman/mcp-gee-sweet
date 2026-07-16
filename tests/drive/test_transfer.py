"""Tests for tools/drive/transfer.py (upload_file, _xlsx_range_values, etc.)."""

import io
from unittest.mock import MagicMock

import openpyxl
import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.drive import transfer as transfer_module
from mcp_gee_sweet.tools.drive.transfer import _xlsx_range_values


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


_transfer_tool, _transfer_tools = _make_tool_registry()
transfer_module.register(_transfer_tool)


def _make_wb(data: list[list]) -> openpyxl.Workbook:
    """Build an in-memory workbook with data written to Sheet1."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in data:
        ws.append(row)
    return wb


def _roundtrip(wb: openpyxl.Workbook) -> openpyxl.Workbook:
    """Save to bytes and reload read-only (mirrors what export_revision does)."""
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return openpyxl.load_workbook(buf, read_only=True, data_only=True)


class TestUploadFile:
    """upload_file returns a friendly error on quota exceeded and invalidates the folder cache."""

    def _quota_err(self):
        resp = MagicMock()
        resp.status = 403
        return HttpError(resp=resp, content=b'{"error": {"reason": "storageQuotaExceeded"}}')

    def _drive_file_response(self):
        return {
            "id": "fid1",
            "name": "file.txt",
            "parents": ["parent1"],
            "mimeType": "text/plain",
            "webViewLink": "https://example.com",
        }

    async def test_quota_exceeded_returns_friendly_error_dict(self):
        """upload_file must return {"error": ...} on storageQuotaExceeded, not raise."""
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = self._quota_err()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        result = await _transfer_tools["upload_file"](name="test.txt", content="hello", ctx=ctx)
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]  # raw message replaced
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    async def test_with_folder_marks_folder_cache_dirty(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = (
            self._drive_file_response()
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(
            drive_service=mock, drive_folder_cache=folder_cache, folder_id="default_folder"
        )
        await _transfer_tools["upload_file"](
            name="doc.txt", content="hello", folder_id="target_folder", ctx=ctx
        )
        folder_cache.mark_dirty.assert_called_once_with("target_folder")


class TestXlsxRangeValues:
    async def test_no_range_returns_all_rows(self):
        wb = _roundtrip(_make_wb([["A", "B"], ["C", "D"]]))
        result = _xlsx_range_values(wb.active, None)
        assert result == [["A", "B"], ["C", "D"]]

    async def test_multi_cell_range(self):
        wb = _roundtrip(_make_wb([["A", "B", "C"], ["D", "E", "F"], ["G", "H", "I"]]))
        result = _xlsx_range_values(wb.active, "A1:B2")
        assert result == [["A", "B"], ["D", "E"]]

    async def test_single_row_range(self):
        wb = _roundtrip(_make_wb([["X", "Y", "Z"]]))
        result = _xlsx_range_values(wb.active, "A1:C1")
        assert result == [["X", "Y", "Z"]]

    async def test_single_cell_range(self):
        wb = _roundtrip(_make_wb([["Hello", "World"]]))
        result = _xlsx_range_values(wb.active, "A1")
        assert result == [["Hello"]]

    async def test_empty_cells_return_none(self):
        wb = _roundtrip(_make_wb([["A", None, "C"]]))
        result = _xlsx_range_values(wb.active, "A1:C1")
        assert result == [["A", None, "C"]]

    async def test_numeric_values(self):
        wb = _roundtrip(_make_wb([[1, 2.5, 3]]))
        result = _xlsx_range_values(wb.active, "A1:C1")
        assert result == [[1, 2.5, 3]]

    async def test_second_sheet(self):
        wb = openpyxl.Workbook()
        wb.active.title = "Sheet1"
        ws2 = wb.create_sheet("Sheet2")
        ws2.append(["only", "here"])
        rb = _roundtrip(wb)
        result = _xlsx_range_values(rb["Sheet2"], "A1:B1")
        assert result == [["only", "here"]]


class TestExportFile:
    """export_file's base64 encoding inflates raw size ~33%, so it needs the response-size
    safety net too (issue #242) — but points to download_file instead of a local_path
    bypass, since download_file already writes raw bytes with no base64/JSON overhead."""

    def _ctx(self, drive_svc):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = drive_svc
        return ctx

    def _workspace_svc(self, content_bytes, mime_type="application/vnd.google-apps.document"):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "id": "doc1",
            "name": "Test Doc",
            "mimeType": mime_type,
        }
        svc.files.return_value.export.return_value.execute.return_value = content_bytes
        return svc

    async def test_small_export_succeeds(self):
        ctx = self._ctx(self._workspace_svc(b"small pdf content"))
        result = await _transfer_tools["export_file"](file_id="doc1", export_format="pdf", ctx=ctx)
        assert result["encoding"] == "base64"

    async def test_oversized_base64_content_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        ctx = self._ctx(self._workspace_svc(b"x" * 1000))
        with pytest.raises(ValueError, match="safety cap"):
            await _transfer_tools["export_file"](file_id="doc1", export_format="pdf", ctx=ctx)

    async def test_error_points_to_download_file_not_local_path(self, monkeypatch):
        # export_file has no local_path param — download_file is the correct bypass
        # (raw bytes to disk, no base64/JSON overhead), so the error must say so and
        # must not reference a param this tool doesn't have.
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        ctx = self._ctx(self._workspace_svc(b"x" * 1000))
        with pytest.raises(ValueError) as exc_info:
            await _transfer_tools["export_file"](file_id="doc1", export_format="pdf", ctx=ctx)
        msg = str(exc_info.value)
        assert "download_file" in msg
        assert "local_path" not in msg


class _FakeDriveFS:
    """Fakes the slice of the Drive API sync_folder needs: per-folder `files().list`,
    plus `files().create`/`files().update` that record what would have been written."""

    def __init__(self, children: dict[str, list[dict]]):
        self.children = children  # folder_id -> Drive API file/folder dicts
        self.list_calls: list[str] = []  # folder ids queried, in order
        self.created_folders: list[dict] = []
        self.created_files: list[dict] = []
        self.updated_files: list[dict] = []

        self.svc = MagicMock()
        self.svc.files.return_value.list.side_effect = self._list
        self.svc.files.return_value.create.side_effect = self._create
        self.svc.files.return_value.update.side_effect = self._update

    def _list(self, **kwargs):
        folder_id = kwargs["q"].split("'")[1]
        self.list_calls.append(folder_id)
        resp = MagicMock()
        resp.execute.return_value = {"files": self.children.get(folder_id, [])}
        return resp

    def _create(self, **kwargs):
        body = kwargs["body"]
        resp = MagicMock()
        if body.get("mimeType") == "application/vnd.google-apps.folder":
            new_id = f"new-folder-{len(self.created_folders)}"
            self.created_folders.append(body)
            resp.execute.return_value = {"id": new_id}
        else:
            self.created_files.append(body)
            resp.execute.return_value = {"id": f"new-file-{len(self.created_files)}"}
        return resp

    def _update(self, **kwargs):
        self.updated_files.append(kwargs)
        resp = MagicMock()
        resp.execute.return_value = {"id": kwargs.get("fileId")}
        return resp


def _drive_file(name, file_id, mtime="2024-01-01T00:00:00.000Z", mime="text/plain"):
    return {"id": file_id, "name": name, "mimeType": mime, "modifiedTime": mtime}


def _drive_folder(name, folder_id):
    return {"id": folder_id, "name": name, "mimeType": "application/vnd.google-apps.folder"}


class TestSyncFolderRecursive:
    """Issue #315: sync_folder silently ignored every subfolder, one level deep,
    reporting a clean 'in sync' result instead of surfacing the gap. `recursive=True`
    now walks matching subfolders to any depth; subfolders left alone because the
    sync direction wouldn't create them on the missing side are reported under
    'folders_skipped' instead of vanishing silently."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        return ctx

    async def test_default_is_non_recursive_and_ignores_subfolders(self, tmp_path):
        # A subfolder plus export_format set together used to hit the pre-existing bug
        # where a folder's mimeType (starts with "application/vnd.google-apps.", same
        # prefix as real Workspace docs) got treated as an exportable file and failed.
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file("readme.txt", "f1"),
                    _drive_folder("sub", "subid"),
                ]
            }
        )
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            dry_run=True,
            ctx=self._ctx(fs),
        )
        names = [a["name"] for a in result["actions"]]
        assert names == ["readme.txt"]
        assert result["failed"] == []
        assert result["folders_skipped"] == []
        assert fs.list_calls == ["root"]  # subfolder never queried

    async def test_recursive_both_sides_descends_into_matching_subfolder(self, tmp_path):
        (tmp_path / "sub").mkdir()
        fs = _FakeDriveFS(
            {
                "root": [_drive_folder("sub", "subid")],
                "subid": [_drive_file("nested.txt", "f1")],
            }
        )
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            dry_run=True,
            recursive=True,
            ctx=self._ctx(fs),
        )
        actions_by_name = {a["name"]: a for a in result["actions"]}
        assert actions_by_name["sub/nested.txt"]["action"] == "download"
        assert result["folders_skipped"] == []
        assert set(fs.list_calls) == {"root", "subid"}

    async def test_recursive_drive_only_subfolder_downloaded_when_direction_allows(self, tmp_path):
        fs = _FakeDriveFS(
            {
                "root": [_drive_folder("sub", "subid")],
                "subid": [_drive_file("nested.txt", "f1")],
            }
        )
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            dry_run=True,
            recursive=True,
            ctx=self._ctx(fs),
        )
        actions_by_name = {a["name"]: a for a in result["actions"]}
        assert actions_by_name["sub/nested.txt"]["action"] == "download"
        assert result["folders_skipped"] == []
        # dry_run never touches the filesystem, even to descend
        assert not (tmp_path / "sub").exists()

    async def test_recursive_drive_only_subfolder_skipped_under_upload_direction(self, tmp_path):
        fs = _FakeDriveFS(
            {
                "root": [_drive_folder("sub", "subid")],
                "subid": [_drive_file("nested.txt", "f1")],
            }
        )
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            dry_run=True,
            recursive=True,
            ctx=self._ctx(fs),
        )
        assert result["folders_skipped"] == ["sub/"]
        assert result["actions"] == []
        assert fs.list_calls == ["root"]  # subfolder's children never fetched

    async def test_recursive_local_only_subfolder_skipped_under_download_direction(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "local.txt").write_text("hi")
        fs = _FakeDriveFS({"root": []})
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="download",
            dry_run=True,
            recursive=True,
            ctx=self._ctx(fs),
        )
        assert result["folders_skipped"] == ["sub/"]
        assert fs.created_folders == []

    async def test_recursive_local_only_subfolder_uploaded_creates_drive_folder(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "local.txt").write_text("hi")
        fs = _FakeDriveFS({"root": []})
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            recursive=True,
            ctx=self._ctx(fs),
        )
        assert fs.created_folders == [
            {"name": "sub", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]}
        ]
        assert result["uploaded"] == ["sub/local.txt"]
        assert fs.created_files[0]["name"] == "local.txt"
        assert fs.created_files[0]["parents"] == ["new-folder-0"]
        assert result["folders_skipped"] == []
