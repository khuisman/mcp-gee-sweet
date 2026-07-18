"""Tests for tools/drive/transfer.py (upload_file, _xlsx_range_values, etc.)."""

import io
import threading
from unittest.mock import AsyncMock, MagicMock

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
        ctx.report_progress = AsyncMock()
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

    async def test_reports_progress_for_each_transfer_not_after_the_whole_batch(self, tmp_path):
        """#316: sync_folder's per-level transfers already run concurrently (#293),
        but nothing reported progress, so a large single-level sync was still silent
        for its whole duration. Progress must be reported inside each transfer's own
        coroutine as it completes — not after the level's asyncio.gather resolves,
        which would only ever deliver one final burst instead of live updates."""
        (tmp_path / "a.txt").write_text("hi")
        (tmp_path / "b.txt").write_text("bye")
        fs = _FakeDriveFS({"root": []})
        ctx = self._ctx(fs)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=ctx,
        )
        assert set(result["uploaded"]) == {"a.txt", "b.txt"}
        assert ctx.report_progress.await_count == 2
        completed_values = sorted(c.args[0] for c in ctx.report_progress.await_args_list)
        assert completed_values == [1, 2]
        messages = [c.args[2] for c in ctx.report_progress.await_args_list]
        assert any("a.txt" in m for m in messages)
        assert any("b.txt" in m for m in messages)

    async def test_dry_run_reports_no_progress(self, tmp_path):
        """dry_run transfers nothing, so no progress update should fire either."""
        (tmp_path / "a.txt").write_text("hi")
        fs = _FakeDriveFS({"root": []})
        ctx = self._ctx(fs)

        await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            dry_run=True,
            ctx=ctx,
        )
        ctx.report_progress.assert_not_awaited()

    async def test_file_folder_name_collision_recorded_as_failed_not_crashed(self, tmp_path):
        """PR #328 review: a Drive file and a Drive folder can share a name (keyed by
        ID, not name). A local file already occupying the subfolder's target path
        (e.g. downloaded moments earlier at the file level) used to crash the whole
        sync via an uncaught FileExistsError from mkdir(exist_ok=True) — exist_ok only
        tolerates an existing *directory*, not an existing file at the same path."""
        (tmp_path / "collide").write_text("existing local file, not a directory")
        fs = _FakeDriveFS(
            {
                "root": [_drive_folder("collide", "collide-folder-id")],
                "collide-folder-id": [],
            }
        )
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="download",
            recursive=True,
            ctx=self._ctx(fs),
        )
        assert result["failed"] == [
            {
                "name": "collide/",
                "error": (
                    "cannot create local folder 'collide': a file with the same name "
                    "already exists at this path"
                ),
            }
        ]
        # the pre-existing local file itself must survive untouched
        assert (tmp_path / "collide").read_text() == "existing local file, not a directory"

    async def test_drive_folder_create_failure_recorded_as_failed_not_crashed(self, tmp_path):
        """PR #328 review: unlike every file-level transfer, the Drive folder-create
        call for a local-only subfolder being uploaded had no try/except — a
        transient API error there used to propagate uncaught and abort the entire
        multi-level sync instead of recording one failed item."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "local.txt").write_text("hi")

        def _create(**kwargs):
            if kwargs["body"].get("mimeType") == "application/vnd.google-apps.folder":
                resp = MagicMock(status=500)
                raise HttpError(resp=resp, content=b'{"error": {"message": "boom"}}')
            resp = MagicMock()
            resp.execute.return_value = {"id": "new-file"}
            return resp

        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        svc.files.return_value.create.side_effect = _create
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            recursive=True,
            ctx=ctx,
        )
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "sub/"
        assert "boom" in result["failed"][0]["error"]
        # the call itself must not raise — proven by reaching this line at all

    async def test_recursive_sibling_subfolders_descend_concurrently(self, tmp_path):
        """PR #328 review: sibling subfolder recursion was awaited one at a time
        instead of gathered, so wall-clock time scaled with the sum of subfolder
        round-trips instead of the max. A synchronization barrier proves both
        siblings' Drive list calls are genuinely in flight together at the same
        time, in real OS threads via execute_in_thread — if recursion regresses to
        sequential awaits, only one call is ever in flight and the barrier times
        out. The barrier must live inside `.execute()`, not `.list()`: `.list()` is
        evaluated eagerly on the event-loop thread while building the call chain,
        before execute_in_thread ever hands off to a worker thread — blocking there
        would freeze the single-threaded event loop itself rather than proving
        cross-thread concurrency."""
        barrier = threading.Barrier(2, timeout=2)

        class _ConcurrentFakeDriveFS(_FakeDriveFS):
            def _list(self, **kwargs):
                folder_id = kwargs["q"].split("'")[1]
                self.list_calls.append(folder_id)
                resp = MagicMock()
                if folder_id in ("alpha-id", "beta-id"):

                    def _execute(*args, folder_id=folder_id, **kwargs):
                        barrier.wait()
                        return {"files": self.children.get(folder_id, [])}

                    resp.execute.side_effect = _execute
                else:
                    resp.execute.return_value = {"files": self.children.get(folder_id, [])}
                return resp

        fs = _ConcurrentFakeDriveFS(
            {
                "root": [_drive_folder("alpha", "alpha-id"), _drive_folder("beta", "beta-id")],
                "alpha-id": [_drive_file("a.txt", "fa")],
                "beta-id": [_drive_file("b.txt", "fb")],
            }
        )
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            dry_run=True,
            recursive=True,
            ctx=self._ctx(fs),
        )
        names = {a["name"] for a in result["actions"]}
        assert names == {"alpha/a.txt", "beta/b.txt"}
        assert result["failed"] == []


class TestDownloadFolder:
    """PR #328 review: download_folder's own Drive listing had the same folder/
    Workspace-file mimeType conflation bug sync_folder's _list_drive_children was
    fixed for — the two tools don't share that helper, so download_folder needed
    its own fix. Subfolders must always be skipped (this tool never descends into
    them), never handed to export()."""

    def _ctx(self, drive_svc):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = drive_svc
        ctx.report_progress = AsyncMock()
        return ctx

    async def test_subfolders_always_skipped_not_exported(self, tmp_path):
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "sub1", "name": "subdir", "mimeType": "application/vnd.google-apps.folder"},
            ]
        }
        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            ctx=self._ctx(svc),
        )
        assert result["skipped"] == ["subdir"]
        assert result["downloaded"] == []
        assert result["failed"] == []
        svc.files.return_value.export.assert_not_called()

    async def test_files_download_concurrently(self, tmp_path):
        """#316: download_folder used to loop sequentially, awaiting one transfer at
        a time — 1.04s/file on a real 217-file folder. A synchronization barrier
        proves two exports are genuinely in flight together, in real OS threads via
        execute_in_thread — a regression back to a sequential loop would only ever
        have one call in flight and the barrier would time out."""
        barrier = threading.Barrier(2, timeout=2)

        def _export(**kwargs):
            resp = MagicMock()

            def _execute(*args, **kwargs):
                barrier.wait()
                return b"content"

            resp.execute.side_effect = _execute
            return resp

        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "doc1",
                    "name": "Doc One",
                    "mimeType": "application/vnd.google-apps.document",
                },
                {
                    "id": "doc2",
                    "name": "Doc Two",
                    "mimeType": "application/vnd.google-apps.document",
                },
            ]
        }
        svc.files.return_value.export.side_effect = _export

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            ctx=self._ctx(svc),
        )
        assert set(result["downloaded"]) == {"Doc One.pdf", "Doc Two.pdf"}
        assert result["failed"] == []

    async def test_reports_progress_as_files_complete(self, tmp_path):
        """#316: the 226s call was silent for its entire duration. Each completed
        transfer must fire a notifications/progress update via ctx.report_progress,
        counted against the known total, instead of arriving all at once (or not
        at all) after every download finishes."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "doc1",
                    "name": "Doc One",
                    "mimeType": "application/vnd.google-apps.document",
                },
                {
                    "id": "doc2",
                    "name": "Doc Two",
                    "mimeType": "application/vnd.google-apps.document",
                },
            ]
        }
        svc.files.return_value.export.return_value.execute.return_value = b"content"
        ctx = self._ctx(svc)

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            ctx=ctx,
        )
        assert result["failed"] == []
        assert ctx.report_progress.await_count == 2
        completed_values = sorted(c.args[0] for c in ctx.report_progress.await_args_list)
        assert completed_values == [1, 2]
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 2  # total


class TestSyncFolderResponseSizeCap:
    """PR #328 review: recursive=True removes the previous implicit bound (one
    folder's direct children) on every result list, especially 'actions' during a
    dry run — nothing enforced the shared response-size safety net other capped
    tools use (issue #235/#242)."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    async def test_oversized_result_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        with pytest.raises(ValueError, match="safety cap"):
            await _transfer_tools["sync_folder"](
                folder_id="root",
                local_path=str(tmp_path),
                dry_run=True,
                ctx=self._ctx(fs),
            )

    async def test_error_does_not_offer_local_path_bypass(self, tmp_path, monkeypatch):
        # sync_folder's local_path param already means the sync destination — it
        # can't double as a place to dump the oversized response, so the error must
        # not suggest passing it for that (unlike get_sheet_data's local_path, which
        # exists specifically for this purpose).
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        with pytest.raises(ValueError) as exc_info:
            await _transfer_tools["sync_folder"](
                folder_id="root",
                local_path=str(tmp_path),
                dry_run=True,
                ctx=self._ctx(fs),
            )
        assert "local_path" not in str(exc_info.value)
