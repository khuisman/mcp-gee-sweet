"""tests/drive/test_transfer_pagination.py

Issue #1165: the `files().list()` calls in `tools/drive/transfer.py` read only
the first page and never followed `nextPageToken`, so a folder with more than
one page of children was silently cut off: `download_folder` skipped the rest,
and `sync_folder`/`upload_local_folder`/`_upload_local_file` treated files past
the first page as missing and uploaded duplicates. Each site now pages through
`_list_all_files`; every test here serves a two-page listing and puts the entry
that matters on the second page.
"""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_gee_sweet.tools.drive import transfer as transfer_module
from mcp_gee_sweet.tools.drive.transfer import _list_drive_children, _upload_local_file
from mcp_gee_sweet.tools.pagination import PageLimitExceeded

_FOLDER_MIME = "application/vnd.google-apps.folder"


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


_transfer_tool, _transfer_tools = _make_tool_registry()
transfer_module.register(_transfer_tool)


def _paged_svc(*pages):
    """A Drive service whose files().list() serves `pages` in order, keyed by
    pageToken: page i carries nextPageToken "t<i+1>" unless it's the last. An
    Exception in `pages` is raised by that page's execute()."""
    by_token = {}
    for i, page in enumerate(pages):
        if not isinstance(page, Exception) and i < len(pages) - 1:
            page = {**page, "nextPageToken": f"t{i + 1}"}
        by_token[None if i == 0 else f"t{i}"] = page

    def _list(**kwargs):
        page = by_token[kwargs.get("pageToken")]
        req = MagicMock()
        if isinstance(page, Exception):
            req.execute.side_effect = page
        else:
            req.execute.return_value = page
        return req

    svc = MagicMock()
    svc.files.return_value.list.side_effect = _list
    return svc


def _list_calls(svc):
    return svc.files.return_value.list.call_args_list


def _ctx(svc):
    ctx = MagicMock()
    ctx.request_context.lifespan_context.drive_service = svc
    ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
    ctx.report_progress = AsyncMock()
    return ctx


def _assert_paged(svc, pages):
    calls = _list_calls(svc)
    assert [c.kwargs.get("pageToken") for c in calls] == [None, *[f"t{i}" for i in range(1, pages)]]
    for c in calls:
        assert c.kwargs["fields"].startswith("nextPageToken, files(")


class TestListDriveChildren:
    async def test_children_on_every_page_are_returned(self):
        svc = _paged_svc(
            {"files": [{"id": "f1", "name": "a.txt", "mimeType": "text/plain"}]},
            {
                "files": [
                    {"id": "f2", "name": "b.txt", "mimeType": "text/plain"},
                    {"id": "d1", "name": "sub", "mimeType": _FOLDER_MIME},
                ]
            },
        )

        files, folders = await _list_drive_children(svc, "root")

        assert [f["id"] for f in files] == ["f1", "f2"]
        assert [f["id"] for f in folders] == ["d1"]
        _assert_paged(svc, 2)

    async def test_error_on_a_later_page_propagates(self):
        # Acting on the pages already read would be the truncation bug again.
        svc = _paged_svc(
            {"files": [{"id": "f1", "name": "a.txt", "mimeType": "text/plain"}]},
            RuntimeError("page 2 failed"),
        )

        with pytest.raises(RuntimeError, match="page 2 failed"):
            await _list_drive_children(svc, "root")

    async def test_endless_token_stops_at_the_page_bound(self, monkeypatch):
        monkeypatch.setattr(transfer_module, "_FILES_LIST_MAX_PAGES", 3)
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [],
            "nextPageToken": "again",
        }

        with pytest.raises(PageLimitExceeded):
            await _list_drive_children(svc, "root")
        assert len(_list_calls(svc)) == 3


class TestUploadLocalFileExistenceCheck:
    async def test_existing_match_on_second_page_is_skipped(self, tmp_path):
        local_file = tmp_path / "report.csv"
        local_file.write_text("a,b\n1,2")
        svc = _paged_svc(
            {"files": [{"id": "other", "name": "other.csv", "mimeType": "text/csv"}]},
            {"files": [{"id": "dup", "name": "report.csv", "mimeType": "text/csv"}]},
        )

        result = await _upload_local_file(svc, str(local_file), "parent")

        assert result["skipped"] is True
        assert result["fileId"] == "dup"
        svc.files.return_value.create.assert_not_called()
        _assert_paged(svc, 2)


class TestUploadLocalFolderBulkCheck:
    async def test_existing_files_on_second_page_are_skipped(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        svc = _paged_svc(
            {"files": [{"name": "a.txt", "mimeType": "text/plain"}]},
            {"files": [{"name": "b.txt", "mimeType": "text/plain"}]},
        )

        result = await _transfer_tools["upload_local_folder"](
            local_path=str(tmp_path), parent_folder_id="parent", ctx=_ctx(svc)
        )

        assert result["uploaded"] == []
        assert sorted(result["skipped"]) == ["a.txt", "b.txt"]
        svc.files.return_value.create.assert_not_called()
        _assert_paged(svc, 2)


class TestDownloadFolder:
    async def test_files_on_second_page_are_downloaded(self, tmp_path, monkeypatch):
        svc = _paged_svc(
            {"files": [{"id": "bin1", "name": "a.bin", "mimeType": "application/octet-stream"}]},
            {"files": [{"id": "bin2", "name": "b.bin", "mimeType": "application/octet-stream"}]},
        )
        svc.files.return_value.get_media.side_effect = lambda fileId, supportsAllDrives: MagicMock(
            fileId=fileId
        )

        class _FakeDownloader:
            def __init__(self, fh, request):
                self._fh = fh
                self._data = request.fileId.encode()

            def next_chunk(self):
                self._fh.write(self._data)
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)

        result = await _transfer_tools["download_folder"](
            folder_id="root", local_path=str(tmp_path), ctx=_ctx(svc)
        )

        assert result["failed"] == []
        assert sorted(result["downloaded"]) == ["a.bin", "b.bin"]
        assert (tmp_path / "b.bin").read_bytes() == b"bin2"
        _assert_paged(svc, 2)


class TestSyncFolderUpload:
    async def test_drive_file_on_second_page_is_not_reuploaded(self, tmp_path):
        mtime = datetime(2026, 1, 1, tzinfo=UTC)
        for name in ("a.txt", "b.txt"):
            p = tmp_path / name
            p.write_text("same")
            os.utime(p, (mtime.timestamp(), mtime.timestamp()))
        stamp = mtime.isoformat().replace("+00:00", "Z")

        def _entry(fid, name):
            return {
                "id": fid,
                "name": name,
                "mimeType": "text/plain",
                "modifiedTime": stamp,
                "size": "4",
            }

        svc = _paged_svc({"files": [_entry("f1", "a.txt")]}, {"files": [_entry("f2", "b.txt")]})

        result = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(tmp_path), direction="upload", ctx=_ctx(svc)
        )

        assert result["uploaded"] == []
        assert result["failed"] == []
        svc.files.return_value.create.assert_not_called()
        _assert_paged(svc, 2)
