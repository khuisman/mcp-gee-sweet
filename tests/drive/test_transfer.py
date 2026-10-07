"""Tests for tools/drive/transfer.py (upload_file, _xlsx_range_values, etc.)."""

import io
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.drive import transfer as transfer_module
from mcp_gee_sweet.tools.drive.transfer import (
    _should_skip_existing_upload,
    _upload_local_file,
    _xlsx_range_values,
)


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


class TestShouldSkipExistingUpload:
    """Direct tests for _should_skip_existing_upload — the skip-decision helper
    shared by _upload_local_file's own skip_if_exists check and
    upload_local_folder's bulk one (#514, extracted after PR #505's review of
    #411 found the two independently duplicating this same comparison)."""

    def test_no_existing_entries_never_skips(self):
        assert _should_skip_existing_upload(None, []) is False
        assert (
            _should_skip_existing_upload(
                ("text/csv", "application/vnd.google-apps.spreadsheet"), []
            )
            is False
        )

    def test_no_convert_skips_on_any_existing_entry(self):
        assert _should_skip_existing_upload(None, ["text/plain"]) is True

    def test_convert_skips_only_when_target_mimetype_present(self):
        convert_mime = ("text/csv", "application/vnd.google-apps.spreadsheet")
        assert _should_skip_existing_upload(convert_mime, ["text/csv"]) is False
        assert (
            _should_skip_existing_upload(convert_mime, ["application/vnd.google-apps.spreadsheet"])
            is True
        )

    def test_convert_skips_when_target_mimetype_present_among_several(self):
        """Multiple existing entries (e.g. two Drive files sharing a name) —
        skip as soon as any one of them is already in the target format,
        regardless of position."""
        convert_mime = ("text/csv", "application/vnd.google-apps.spreadsheet")
        assert (
            _should_skip_existing_upload(
                convert_mime, ["text/csv", "application/vnd.google-apps.spreadsheet"]
            )
            is True
        )


class TestUploadLocalFileCore:
    """Direct tests for _upload_local_file — the module-level helper factored out
    of the upload_local_file tool so docs/images.py's insert_local_images can
    call it directly."""

    def _quota_err(self):
        resp = MagicMock()
        resp.status = 403
        return HttpError(resp=resp, content=b'{"error": {"reason": "storageQuotaExceeded"}}')

    async def test_missing_local_file_raises(self, tmp_path):
        drive_svc = MagicMock()
        with pytest.raises(ValueError, match="No file found"):
            await _upload_local_file(drive_svc, str(tmp_path / "missing.txt"), "folder1")

    async def test_uploads_and_returns_file_metadata(self, tmp_path):
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "pic.png",
            "webViewLink": "https://example.com/pic",
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1")

        assert result == {
            "fileId": "fid1",
            "name": "pic.png",
            "web_link": "https://example.com/pic",
            "skipped": False,
        }
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        body = create_kwargs["body"]
        assert body["name"] == "pic.png"
        assert body["parents"] == ["folder1"]
        # #274 PR #472 review, finding #2: a plain (non-convert) upload now stamps
        # modifiedTime from the local file's mtime too, not just the convert branch.
        assert "modifiedTime" in body
        assert "webContentLink" in create_kwargs["fields"]

    async def test_returns_web_content_link_when_drive_provides_it(self, tmp_path):
        # #511: an image-embedding caller uses this link directly instead of a
        # follow-up files().get().
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "pic.png",
            "webViewLink": "https://example.com/pic",
            "webContentLink": "https://drive.google.com/uc?id=fid1",
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1")

        assert result["web_content_link"] == "https://drive.google.com/uc?id=fid1"

    async def test_skip_if_exists_returns_existing_file_without_uploading(self, tmp_path):
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "existing1", "name": "pic.png", "webViewLink": "https://x/existing"}]
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=True
        )

        assert result == {
            "fileId": "existing1",
            "name": "pic.png",
            "web_link": "https://x/existing",
            "skipped": True,
        }
        drive_svc.files.return_value.create.assert_not_called()

    async def test_no_skip_creates_duplicate_when_file_already_exists(self, tmp_path):
        """skip_if_exists=False must never even check for a same-named file — TC-D95
        (issue #495): the existence list() call is gated behind `if skip_if_exists:`
        (transfer.py:126), so this pins that it's genuinely bypassed (not just
        untriggered by coincidence) rather than "checked but ignored". The list()
        mock is configured with a colliding file precisely so a regression that
        started calling list() and honoring it would fail this test's own
        assert_not_called(), not just silently produce the same result."""
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "existing1", "name": "pic.png", "webViewLink": "https://x/existing"}]
        }
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid_new",
            "name": "pic.png",
            "webViewLink": "https://example.com/pic",
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False
        )

        assert result == {
            "fileId": "fid_new",
            "name": "pic.png",
            "web_link": "https://example.com/pic",
            "skipped": False,
        }
        drive_svc.files.return_value.list.assert_not_called()
        drive_svc.files.return_value.create.assert_called_once()

    async def test_quota_exceeded_returns_friendly_error_dict(self, tmp_path):
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.side_effect = self._quota_err()

        result = await _upload_local_file(drive_svc, str(local_file), "folder1")

        assert "error" in result
        assert "Service accounts" in result["error"]

    async def test_custom_name_used_instead_of_filename(self, tmp_path):
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "renamed.png",
            "webViewLink": "https://example.com/pic",
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", name="renamed.png")

        assert result["name"] == "renamed.png"
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["name"] == "renamed.png"


class TestUploadLocalFileConvert:
    """convert=True requests Drive's native import conversion (issue #188)."""

    def _quota_err(self):
        resp = MagicMock()
        resp.status = 403
        return HttpError(resp=resp, content=b'{"error": {"reason": "storageQuotaExceeded"}}')

    @pytest.mark.parametrize(
        "filename,expected_target_mime",
        [
            ("data.csv", "application/vnd.google-apps.spreadsheet"),
            ("data.xlsx", "application/vnd.google-apps.spreadsheet"),
            ("doc.docx", "application/vnd.google-apps.document"),
            ("notes.md", "application/vnd.google-apps.document"),
            ("page.html", "application/vnd.google-apps.document"),
            ("page.htm", "application/vnd.google-apps.document"),
            ("deck.pptx", "application/vnd.google-apps.presentation"),
        ],
    )
    async def test_convert_sets_target_mimetype_for_supported_extensions(
        self, tmp_path, filename, expected_target_mime
    ):
        local_file = tmp_path / filename
        local_file.write_text("content")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": filename,
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["mimeType"] == expected_target_mime

    async def test_convert_md_stamps_source_property_for_sync_folder_matching(self, tmp_path):
        """#414 QA review round 3, finding #2: upload_local_file(convert=True) never
        stamped the marker sync_folder's own convert_markdown matching relies on,
        so a Doc created here was invisible to that matching and got silently
        duplicated on the next sync_folder run. Only .md needs this — it's the only
        extension sync_folder's convert_markdown has an equivalent matching path
        for."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "notes.md",
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        props = dict(create_kwargs["body"]["properties"])
        _pop_uploaded_at(props)
        assert props == {
            transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md",
            transfer_module._CONVERT_SOURCE_PROP: "notes.md",
            # #814: sync_folder's local-side reference for this Doc, exact to
            # the microsecond (PR #854 QA round 1).
            transfer_module._CONVERTED_MD_SOURCE_MTIME_PROP: _precise_mtime(local_file),
        }

    async def test_convert_non_md_does_not_stamp_source_mtime(self, tmp_path):
        """#814's source-mtime property is only for .md → Doc, the one
        conversion sync_folder tracks through properties; other types (#818)
        stay on the modifiedTime comparison."""
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2\n")
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "fid1"}

        await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert transfer_module._CONVERTED_MD_SOURCE_MTIME_PROP not in body["properties"]

    @pytest.mark.parametrize(
        ("file_name", "target_mime"),
        [
            ("notes.md", "application/vnd.google-apps.document"),
            ("data.csv", "application/vnd.google-apps.spreadsheet"),
        ],
    )
    async def test_convert_stamps_modified_time_from_local_mtime_and_restamps_after_create(
        self, tmp_path, file_name, target_mime
    ):
        """#422 finding #2: _upload_local_file never set modifiedTime on a converted
        Doc, so it got Drive's own creation timestamp instead of the local file's
        mtime — landing in sync_folder's 'conflicts' rather than 'skipped' on
        nearly every first sync_folder call afterward, since nothing tied the two
        timestamps together. A metadata-only follow-up update() re-stamps it after
        Drive's native import overwrites the create() request, the same way
        _sync_level's own convert_markdown upload path already does (TC-D218).

        The .csv case guards #435's declined .md-only gate: sync_folder matches a
        converted Sheet back to its local .csv via export_format's suffix scheme
        and compares mtimes, so every conversion type must restamp."""
        local_file = tmp_path / file_name
        local_file.write_text("a,b\n1,2\n")
        expected_mtime = datetime.fromtimestamp(
            local_file.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "notes.md",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["modifiedTime"] == expected_mtime
        assert create_kwargs["body"]["mimeType"] == target_mime

        update_kwargs = drive_svc.files.return_value.update.call_args.kwargs
        assert update_kwargs["fileId"] == "fid1"
        assert update_kwargs["body"] == {"modifiedTime": expected_mtime}
        assert "media_body" not in update_kwargs

    async def test_unreadable_mtime_returns_error_instead_of_raising(self, tmp_path, monkeypatch):
        """PR #817 QA round 1: the local mtime used to be read before the create()
        try, so a file that vanished or became unreadable after the is_file()
        check raised out of the upload_local_file tool instead of returning
        {"error": ...}. Nothing is created in Drive."""
        local_file = tmp_path / "notes.txt"
        local_file.write_text("x")

        def _boom(_path, _st=None):
            raise FileNotFoundError("gone")

        monkeypatch.setattr(transfer_module, "_local_mtime_dt", _boom)
        drive_svc = MagicMock()

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False
        )

        assert result == {"error": "gone"}
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_modified_time_restamp_failure_returns_clean_error_not_raise(
        self, tmp_path
    ):
        """#422 finding #1: a failure in the follow-up modifiedTime-restamp update()
        call — after create() already succeeded — used to propagate as an
        uncaught exception, even though a Doc now genuinely exists in Drive. The
        caller (the upload_local_file tool) has no try/except of its own, so this
        would otherwise surface as an unhandled tool error with no fileId
        returned at all. Mirrors _sync_level._run_one's create()+update() pair,
        which already wraps both calls in one broad except and returns a clean
        failure rather than letting a partial success propagate raw.

        #420: the clean error alone wasn't enough — a bare {"error": ...} still
        lost the ID of the Doc that genuinely got created in Drive, leaving an
        untracked orphan with no way to find it. The result must also carry
        'fileId' in this specific case."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "notes.md",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.side_effect = RuntimeError(
            "transient network error"
        )

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" in result
        assert "transient network error" in result["error"]
        assert result["fileId"] == "fid1"

    async def test_convert_restamp_quota_error_uses_friendly_message(self, tmp_path):
        """#650: a storageQuotaExceeded HttpError raised by the metadata-only
        restamp update() (after create() already succeeded) went through a bare
        `except Exception` that leaked the raw error string, unlike every other
        quota-error site in transfer.py. It must now surface the shared
        _SA_QUOTA_ERROR text while still carrying the created file's fileId."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "notes.md",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.side_effect = self._quota_err()

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert result["fileId"] == "fid1"
        assert "storageQuotaExceeded" not in result["error"]  # raw message replaced
        assert transfer_module._SA_QUOTA_ERROR in result["error"]

    async def test_create_failure_returns_error_with_no_fileId(self, tmp_path):
        """#420: distinct from the restamp-failure case above — when create()
        itself fails, nothing was created in Drive, so the error must NOT carry
        a fileId (there's no orphan to report)."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.side_effect = RuntimeError(
            "create failed"
        )

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" in result
        assert "create failed" in result["error"]
        assert "fileId" not in result

    async def test_convert_non_md_extension_stamps_only_generic_source_property(self, tmp_path):
        """A non-.md conversion gets the generic _CONVERT_SOURCE_PROP marker
        (#769) but never _CONVERT_MARKDOWN_SOURCE_PROP — sync_folder reads the
        latter on any Doc as "converted from a local .md", which this isn't."""
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "data.csv",
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["properties"] == {
            transfer_module._CONVERT_SOURCE_PROP: "data.csv"
        }

    async def test_non_convert_upload_stamps_no_properties(self, tmp_path):
        """The marker records a conversion's source; a plain upload has none."""
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "data.csv",
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False
        )

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert "properties" not in create_kwargs["body"]

    async def test_convert_unsupported_extension_returns_error_without_uploading(self, tmp_path):
        local_file = tmp_path / "archive.zip"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=True
        )

        assert "error" in result
        assert ".zip" in result["error"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_false_default_does_not_set_target_mimetype(self, tmp_path):
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "data.csv",
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1")

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert "mimeType" not in create_kwargs["body"]
        # modifiedTime is stamped on every upload now, not just the convert branch
        # (#274 PR #472 review, finding #2) — but only via the create() body itself;
        # no follow-up restamp is needed (or performed) for a plain upload, since
        # Drive has no import-conversion here to overwrite the value.
        assert "modifiedTime" in create_kwargs["body"]
        drive_svc.files.return_value.update.assert_not_called()

    async def test_convert_extension_comes_from_name_override_not_local_path(self, tmp_path):
        """A no-extension local_path with a .csv name= override should still convert
        (PR #410 QA review: the lookup used local_path's suffix, not the effective
        destination name, so this previously errored as "unsupported extension")."""
        local_file = tmp_path / "scratch_tmpfile"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "report.csv",
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(
            drive_svc,
            str(local_file),
            "folder1",
            name="report.csv",
            skip_if_exists=False,
            convert=True,
        )

        assert "error" not in result
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["mimeType"] == "application/vnd.google-apps.spreadsheet"

    async def test_convert_extension_mismatch_between_local_path_and_name_override_errors(
        self, tmp_path
    ):
        """Inverse of the above: a .csv local_path with a name= override that has no
        supported extension should error on the destination extension, not silently
        succeed using local_path's .csv (PR #410 QA review)."""
        local_file = tmp_path / "upload.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()

        result = await _upload_local_file(
            drive_svc,
            str(local_file),
            "folder1",
            name="archive.zip",
            skip_if_exists=False,
            convert=True,
        )

        assert "error" in result
        assert ".zip" in result["error"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_skip_if_exists_does_not_skip_when_existing_file_is_unconverted(self, tmp_path):
        """skip_if_exists must not treat a same-named raw (unconverted) file as the
        skip-worthy duplicate when convert=True — a name-only match previously
        returned the raw file with no conversion and no error (PR #410 QA review)."""
        local_file = tmp_path / "a.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "existing-raw",
                    "name": "a.csv",
                    "webViewLink": "https://x/existing",
                    "mimeType": "text/csv",
                }
            ]
        }
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid-converted",
            "name": "a.csv",
            "webViewLink": "https://example.com/converted",
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        assert result["skipped"] is False
        assert result["fileId"] == "fid-converted"
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["mimeType"] == "application/vnd.google-apps.spreadsheet"

    async def test_skip_if_exists_still_skips_when_existing_file_already_converted(self, tmp_path):
        """The converted case that skip_if_exists is actually meant to catch: an
        existing file already in the target Workspace mimeType should still skip."""
        local_file = tmp_path / "a.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "existing-converted",
                    "name": "a.csv",
                    "webViewLink": "https://x/existing",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
            ]
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        assert result == {
            "fileId": "existing-converted",
            "name": "a.csv",
            "web_link": "https://x/existing",
            "skipped": True,
        }
        drive_svc.files.return_value.create.assert_not_called()

    async def test_skip_if_exists_picks_the_converted_hit_among_several_same_named(self, tmp_path):
        """#514 QA round 1 (PR #767): _upload_local_file's own existence check
        used to query with pageSize=1, so it could never see more than one
        Drive entry sharing the destination name even though Drive allows
        it — the multi-hit case _should_skip_existing_upload exists to
        handle was only actually reachable via upload_local_folder's bulk
        path. Here the raw duplicate is listed *first* and the
        already-converted one *second* — the ordering under which the old
        hits[0]-only code would have picked the raw file, seen no mimeType
        match, and re-converted a duplicate instead of skipping."""
        local_file = tmp_path / "a.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "existing-raw",
                    "name": "a.csv",
                    "webViewLink": "https://x/raw",
                    "mimeType": "text/csv",
                },
                {
                    "id": "existing-converted",
                    "name": "a.csv",
                    "webViewLink": "https://x/converted",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                },
            ]
        }

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        assert result == {
            "fileId": "existing-converted",
            "name": "a.csv",
            "web_link": "https://x/converted",
            "skipped": True,
        }
        drive_svc.files.return_value.create.assert_not_called()
        list_kwargs = drive_svc.files.return_value.list.call_args.kwargs
        assert "pageSize" not in list_kwargs


class TestConvertSourceMarker:
    """#769 marker encoding + PR #800 QA round 1: Drive caps a custom
    property's key + value at 124 UTF-8 bytes, and a create() over the cap
    fails with 403 propertyLengthLimitExceeded while still creating the file
    (an orphan). Every stamped property must stay within the cap."""

    def test_property_fits_at_exact_byte_boundary(self):
        key = "k" * 24
        assert transfer_module._property_fits(key, "v" * 100)  # 124 bytes
        assert not transfer_module._property_fits(key, "v" * 101)  # 125 bytes

    def test_property_fits_counts_utf8_bytes_not_characters(self):
        key = "k" * 4
        # 40 CJK characters = 120 UTF-8 bytes; + 4-byte key = 124 fits, one more doesn't.
        assert transfer_module._property_fits(key, "報" * 40)
        assert not transfer_module._property_fits(key, "報" * 41)

    def test_short_name_marker_is_the_raw_name(self):
        assert transfer_module._convert_source_marker("report.csv") == "report.csv"

    def test_marker_at_cap_stays_raw_one_byte_over_is_digested(self):
        key_len = len(transfer_module._CONVERT_SOURCE_PROP.encode("utf-8"))
        room = transfer_module._DRIVE_PROPERTY_MAX_BYTES - key_len
        at_cap = "a" * (room - 4) + ".csv"
        over = "a" * (room - 3) + ".csv"
        assert transfer_module._convert_source_marker(at_cap) == at_cap
        assert transfer_module._convert_source_marker(over).startswith("sha256:")

    @pytest.mark.parametrize(
        "file_name",
        ["q" * 114 + ".csv", "四半期売上レポート" * 5 + ".csv", "長い" * 30 + ".md"],
    )
    def test_every_stamped_property_fits_the_cap(self, file_name):
        props = transfer_module._convert_properties(file_name)
        assert transfer_module._CONVERT_SOURCE_PROP in props
        for key, value in props.items():
            assert transfer_module._property_fits(key, value), (key, value)

    def test_long_md_name_omits_markdown_key_rather_than_digesting_it(self):
        """sync_folder reads _CONVERT_MARKDOWN_SOURCE_PROP back verbatim as the
        local filename, so a digest there would match nothing; the key is
        dropped instead, and the generic marker (digested) still verifies."""
        name = "n" * 120 + ".md"
        props = transfer_module._convert_properties(name)
        assert transfer_module._CONVERT_MARKDOWN_SOURCE_PROP not in props
        assert transfer_module._marker_names_source({"properties": props}, name)

    def test_short_md_name_gets_both_keys(self):
        props = transfer_module._convert_properties("notes.md")
        assert props == {
            transfer_module._CONVERT_SOURCE_PROP: "notes.md",
            transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md",
        }

    def test_digested_marker_verifies_only_its_own_source(self):
        name = "x" * 120 + ".csv"
        f = {"properties": transfer_module._convert_properties(name)}
        assert transfer_module._marker_names_source(f, name)
        assert not transfer_module._marker_names_source(f, "y" * 120 + ".csv")

    def test_empty_string_marker_does_not_fall_through_to_the_other_key(self):
        """An empty generic marker is still a marker (so not "unmarked"), and
        must not be skipped over in favor of the markdown key — each key is
        checked explicitly with `is not None` (PR #800 QA round 1, item 5)."""
        f = {
            "properties": {
                transfer_module._CONVERT_SOURCE_PROP: "",
                transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "",
            }
        }
        assert transfer_module._has_convert_marker(f)
        assert not transfer_module._marker_names_source(f, "notes.md")

    async def test_long_name_upload_stamps_within_cap(self, tmp_path):
        """The live repro: a 118-byte .csv name used to send a 139-byte
        property and fail with 403 after Drive had already created the Sheet."""
        name = "r" * 114 + ".csv"
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": name[:-4],
            "webViewLink": "https://example.com",
        }

        result = await _upload_local_file(
            drive_svc, str(local_file), "folder1", name=name, skip_if_exists=False, convert=True
        )

        assert "error" not in result
        props = drive_svc.files.return_value.create.call_args.kwargs["body"]["properties"]
        for key, value in props.items():
            assert transfer_module._property_fits(key, value)


class TestConvertedMdSourceName:
    """#805: sync_folder recognizes a convert_markdown Doc through either
    marker key — the legacy markdown key (every pre-#805 Doc) or the generic
    one, whose digest form is resolved against the Doc's own display name."""

    _DOC = "application/vnd.google-apps.document"

    def _doc(self, name, props):
        return {"name": name, "mimeType": self._DOC, "properties": props}

    def test_legacy_markdown_key_alone_is_recognized(self):
        f = self._doc(
            "renamed in drive", {transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"}
        )
        assert transfer_module._converted_md_source_name(f) == "notes.md"

    def test_raw_generic_marker_names_the_source_even_after_rename(self):
        f = self._doc("renamed in drive", {transfer_module._CONVERT_SOURCE_PROP: "notes.md"})
        assert transfer_module._converted_md_source_name(f) == "notes.md"

    def test_digest_marker_resolves_to_the_docs_own_name(self):
        name = "n" * 120 + ".md"
        f = self._doc(name, transfer_module._convert_properties(name))
        assert transfer_module._CONVERT_MARKDOWN_SOURCE_PROP not in f["properties"]
        assert transfer_module._converted_md_source_name(f) == name

    def test_digest_marker_on_a_renamed_doc_is_not_recognized(self):
        name = "n" * 120 + ".md"
        f = self._doc("m" * 120 + ".md", transfer_module._convert_properties(name))
        assert transfer_module._converted_md_source_name(f) is None

    @pytest.mark.parametrize("source", ["report.docx", "page.html", "x" * 120 + ".html"])
    def test_non_md_conversion_is_not_a_convert_markdown_doc(self, source):
        f = self._doc(source, transfer_module._convert_properties(source))
        assert transfer_module._converted_md_source_name(f) is None

    def test_non_doc_mimetype_is_never_recognized(self):
        f = {
            "name": "notes.md",
            "mimeType": "text/markdown",
            "properties": {transfer_module._CONVERT_SOURCE_PROP: "notes.md"},
        }
        assert transfer_module._converted_md_source_name(f) is None

    def test_unmarked_doc_is_not_recognized(self):
        assert transfer_module._converted_md_source_name(self._doc("notes.md", {})) is None
        f = {"name": "notes.md", "mimeType": self._DOC}
        assert transfer_module._converted_md_source_name(f) is None


class TestUploadLocalFileStemMatch:
    """PR #800 QA round 1, item 2: _upload_local_file's own skip_if_exists
    check only queried the full name, so upload_local_file(convert=True)
    re-converted a duplicate of a file whose converted copy Drive had
    extension-stripped — even when that copy carried the marker naming it.
    It now shares _find_existing_upload with upload_local_folder."""

    SHEET = "application/vnd.google-apps.spreadsheet"

    def _svc(self, files):
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": files}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid-new",
            "name": "fresh",
            "webViewLink": "https://example.com/new",
        }
        return drive_svc

    async def test_marked_stem_match_is_a_verified_skip(self, tmp_path):
        local_file = tmp_path / "fresh.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = self._svc(
            [
                {
                    "id": "existing",
                    "name": "fresh",
                    "webViewLink": "https://x/existing",
                    "mimeType": self.SHEET,
                    "properties": {transfer_module._CONVERT_SOURCE_PROP: "fresh.csv"},
                }
            ]
        )

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        assert result == {
            "fileId": "existing",
            "name": "fresh",
            "web_link": "https://x/existing",
            "skipped": True,
        }
        drive_svc.files.return_value.create.assert_not_called()
        list_kwargs = drive_svc.files.return_value.list.call_args.kwargs
        assert "name='fresh.csv' or name='fresh'" in list_kwargs["q"]
        assert "properties" in list_kwargs["fields"]

    async def test_unmarked_stem_match_is_an_unverified_skip(self, tmp_path):
        local_file = tmp_path / "report.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = self._svc(
            [
                {
                    "id": "unrelated",
                    "name": "report",
                    "webViewLink": "https://x/unrelated",
                    "mimeType": self.SHEET,
                }
            ]
        )

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        assert result["skipped"] is True
        assert result["skipped_unverified"] is True
        assert result["fileId"] == "unrelated"
        assert "unverified" in result["reason"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_stem_match_marked_with_other_source_uploads(self, tmp_path):
        local_file = tmp_path / "report.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = self._svc(
            [
                {
                    "id": "other",
                    "name": "report",
                    "webViewLink": "https://x/other",
                    "mimeType": self.SHEET,
                    "properties": {transfer_module._CONVERT_SOURCE_PROP: "report.xlsx"},
                }
            ]
        )

        result = await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        assert result["skipped"] is False
        assert result["fileId"] == "fid-new"

    async def test_stem_query_escapes_quotes_in_both_names(self, tmp_path):
        local_file = tmp_path / "it's.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = self._svc([])

        await _upload_local_file(drive_svc, str(local_file), "folder1", convert=True)

        q = drive_svc.files.return_value.list.call_args.kwargs["q"]
        assert "name='it\\'s.csv' or name='it\\'s'" in q

    async def test_non_convert_check_queries_full_name_only_without_properties(self, tmp_path):
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = self._svc([])

        await _upload_local_file(drive_svc, str(local_file), "folder1")

        list_kwargs = drive_svc.files.return_value.list.call_args.kwargs
        assert "name='data.csv')" in list_kwargs["q"]
        assert " or " not in list_kwargs["q"]
        assert "properties" not in list_kwargs["fields"]

    async def test_non_convert_ignores_a_same_stem_entry(self, tmp_path):
        """Without convert there's no extension stripping, so a "data" entry
        is just a different name — no skip."""
        local_file = tmp_path / "data.csv"
        local_file.write_text("a,b\n1,2")
        drive_svc = self._svc(
            [{"id": "d", "name": "data", "webViewLink": "https://x/d", "mimeType": self.SHEET}]
        )

        result = await _upload_local_file(drive_svc, str(local_file), "folder1")

        assert result["skipped"] is False


class TestUploadLocalFileToolCacheInvalidation:
    """upload_local_file tool wrapper: drive_folder_cache.mark_dirty gate.

    #420 QA round 1 (PR #645): the gate was `"error" not in result and not
    skipped`, so the new orphan case — create() genuinely succeeded but the
    convert restamp then failed, returning {"error": ..., "fileId": ...} —
    fell through as a false negative even though the folder's contents
    really did change."""

    async def test_restamp_failure_orphan_still_marks_folder_cache_dirty(self, tmp_path):
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "notes.md",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.side_effect = RuntimeError(
            "transient network error"
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=drive_svc, drive_folder_cache=folder_cache)

        result = await _transfer_tools["upload_local_file"](
            local_path=str(local_file),
            parent_folder_id="folder1",
            skip_if_exists=False,
            convert=True,
            ctx=ctx,
        )

        assert "error" in result
        assert result["fileId"] == "fid1"
        folder_cache.mark_dirty.assert_called_once_with("folder1")

    async def test_skip_does_not_mark_folder_cache_dirty(self, tmp_path):
        """Regression guard for the fix above: a skip result also carries a
        'fileId' (the pre-existing file's), but nothing changed — it must NOT
        be conflated with the orphan case and must not mark the cache dirty."""
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "existing1", "name": "pic.png", "webViewLink": "https://x/existing"}]
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=drive_svc, drive_folder_cache=folder_cache)

        result = await _transfer_tools["upload_local_file"](
            local_path=str(local_file), parent_folder_id="folder1", ctx=ctx
        )

        assert result["skipped"] is True
        folder_cache.mark_dirty.assert_not_called()

    async def test_create_failure_does_not_mark_folder_cache_dirty(self, tmp_path):
        """Distinct from the orphan case: create() itself failing means nothing
        was created, so the cache must stay untouched."""
        local_file = tmp_path / "pic.png"
        local_file.write_bytes(b"fake-bytes")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.side_effect = RuntimeError(
            "create failed"
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=drive_svc, drive_folder_cache=folder_cache)

        result = await _transfer_tools["upload_local_file"](
            local_path=str(local_file), parent_folder_id="folder1", ctx=ctx
        )

        assert "error" in result
        assert "fileId" not in result
        folder_cache.mark_dirty.assert_not_called()


class TestUploadLocalFolder:
    """upload_local_folder now routes each file through the shared
    _upload_local_file helper (issue #411) instead of its own independent
    inline create() call, so it can offer the same convert param
    upload_local_file already has. The bulk skip_if_exists pre-check (one
    list() call for the whole folder, TC-D100) is preserved rather than
    delegated per-file, since _upload_local_file's own skip_if_exists check
    would cost one list() call per candidate instead."""

    def _tool(self):
        return _transfer_tools["upload_local_folder"]

    def _ctx(self, drive_svc):
        return _make_ctx(drive_service=drive_svc, drive_folder_cache=MagicMock())

    async def test_bulk_upload_of_mixed_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.png").write_bytes(b"fake")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid",
            "name": "x",
            "webViewLink": "https://example.com",
        }
        ctx = self._ctx(drive_svc)

        result = await self._tool()(str(tmp_path), "folder1", ctx=ctx)

        assert result["uploaded"] == ["a.txt", "b.png"]
        assert result["skipped"] == []
        assert result["failed"] == []
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "folder1"
        )

    async def test_restamp_failure_orphan_still_marks_folder_cache_dirty(self, tmp_path):
        """#420 QA round 1 (PR #645): a single-item folder where create()
        succeeds but the convert restamp then fails never lands in `uploaded`
        (it's reported under `failed` instead) — the old `if uploaded:` gate
        missed this, even though create() genuinely changed the folder."""
        (tmp_path / "notes.md").write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "notes.md",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.side_effect = RuntimeError(
            "transient network error"
        )
        ctx = self._ctx(drive_svc)

        result = await self._tool()(str(tmp_path), "folder1", convert=True, ctx=ctx)

        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["fileId"] == "fid1"
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "folder1"
        )

    async def test_ds_store_excluded_by_default(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / ".DS_Store").write_bytes(b"junk")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid",
            "name": "a.txt",
            "webViewLink": "https://example.com",
        }

        result = await self._tool()(str(tmp_path), "folder1", ctx=self._ctx(drive_svc))

        assert result["uploaded"] == ["a.txt"]
        assert ".DS_Store" not in result["uploaded"]

    async def test_skip_if_exists_makes_exactly_one_list_call_for_the_whole_folder(self, tmp_path):
        """TC-D100: the existence check must stay a single batched list() call
        across the whole folder, not one per file — this is why the bulk
        pre-check result is passed down as skip_if_exists=False into
        _upload_local_file rather than letting each call do its own check."""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.txt").write_text("c")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "a.txt", "mimeType": "text/plain"}]
        }
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid",
            "name": "x",
            "webViewLink": "https://example.com",
        }

        result = await self._tool()(str(tmp_path), "folder1", ctx=self._ctx(drive_svc))

        assert result["skipped"] == ["a.txt"]
        assert sorted(result["uploaded"]) == ["b.txt", "c.txt"]
        assert drive_svc.files.return_value.list.call_count == 1

    async def test_convert_routes_through_shared_helper_and_sets_target_mimetype(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid",
            "name": "data.csv",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.return_value = {"id": "fid"}

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["uploaded"] == ["data.csv"]
        assert result["failed"] == []
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["mimeType"] == "application/vnd.google-apps.spreadsheet"

    async def test_convert_unsupported_extension_reported_as_failed_not_uploaded(self, tmp_path):
        (tmp_path / "archive.zip").write_bytes(b"fake")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "archive.zip"
        assert ".zip" in result["failed"][0]["error"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_unsupported_extension_still_reported_failed_despite_name_collision(
        self, tmp_path
    ):
        """#514 QA round 1 (PR #767): unifying both skip branches through
        _should_skip_existing_upload must not treat convert=True's
        unsupported-extension case (target_mime is None) the same as the
        not-converting case (convert_mime is None means "any existing entry
        matches") — that would silently skip an unsupported file merely
        because Drive happens to already have some unrelated entry sharing
        its name, instead of surfacing the "not supported" error the way
        test_convert_unsupported_extension_reported_as_failed_not_uploaded
        above confirms for the no-collision case."""
        (tmp_path / "archive.zip").write_bytes(b"fake")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "archive.zip", "mimeType": "application/zip"}]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == []
        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "archive.zip"
        assert ".zip" in result["failed"][0]["error"]

    async def test_convert_skips_when_existing_file_already_in_target_mimetype(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "data.csv", "mimeType": "application/vnd.google-apps.spreadsheet"}]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["data.csv"]
        assert result["uploaded"] == []
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_does_not_skip_when_existing_file_is_still_unconverted(self, tmp_path):
        """A same-named file that exists but hasn't been converted yet (still its
        raw mimeType) is not the duplicate convert=True's skip check is meant to
        catch — mirrors _upload_local_file's own convert-aware skip logic."""
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "data.csv", "mimeType": "text/csv"}]
        }
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid-converted",
            "name": "data.csv",
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.update.return_value.execute.return_value = {
            "id": "fid-converted"
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["uploaded"] == ["data.csv"]
        assert result["skipped"] == []

    async def test_convert_skips_when_existing_converted_file_has_stripped_extension(
        self, tmp_path
    ):
        """TC-D243 (PR #505 review): Drive's native import-conversion strips the
        source extension from some converted types' display name (confirmed
        live for CSV) — a second convert=True run must still recognize the
        already-converted file even though its Drive name ("data") no longer
        matches the local file's name ("data.csv"), or it re-converts and
        duplicates it on every run."""
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "name": "data",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "properties": {transfer_module._CONVERT_SOURCE_PROP: "data.csv"},
                }
            ]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["data.csv"]
        assert result["skipped_unverified"] == []
        assert result["uploaded"] == []
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_unrelated_stem_match_is_reported_unverified(self, tmp_path):
        """#769's repro: an unrelated Sheet literally named "report" (no
        conversion marker) must not be passed off as report.csv's converted
        duplicate. Per the maintainer decision it's still skipped — it could
        equally be a conversion from before the marker existed, and uploading
        would duplicate those — but reported under skipped_unverified, not
        skipped, so the ambiguity is visible."""
        (tmp_path / "report.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "report", "mimeType": "application/vnd.google-apps.spreadsheet"}]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == []
        assert result["uploaded"] == []
        assert len(result["skipped_unverified"]) == 1
        entry = result["skipped_unverified"][0]
        assert entry["name"] == "report.csv"
        assert entry["matched_name"] == "report"
        assert "unverified" in entry["reason"]
        drive_svc.files.return_value.create.assert_not_called()
        # The marker can only be read back if the bulk list() asks for it.
        list_kwargs = drive_svc.files.return_value.list.call_args.kwargs
        assert "properties" in list_kwargs["fields"]

    async def test_convert_stem_match_marked_with_other_source_uploads(self, tmp_path):
        """A stem match whose marker names a *different* source file (here a
        "report" Sheet this tool converted from report.xlsx) is provably not
        report.csv's duplicate, so report.csv uploads rather than being
        skipped either way (#769)."""
        (tmp_path / "report.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "name": "report",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "properties": {transfer_module._CONVERT_SOURCE_PROP: "report.xlsx"},
                }
            ]
        }
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "report",
            "webViewLink": "https://example.com",
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["uploaded"] == ["report.csv"]
        assert result["skipped"] == []
        assert result["skipped_unverified"] == []

    async def test_convert_marked_match_wins_over_unmarked_same_stem_entry(self, tmp_path):
        """With both an unrelated unmarked "data" Sheet and this tool's own
        marked conversion present, the file is provably already converted —
        a plain skip, not an unverified one, regardless of listing order."""
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"name": "data", "mimeType": "application/vnd.google-apps.spreadsheet"},
                {
                    "name": "data",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "properties": {transfer_module._CONVERT_SOURCE_PROP: "data.csv"},
                },
            ]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["data.csv"]
        assert result["skipped_unverified"] == []

    async def test_convert_stem_match_recognizes_markdown_only_marker(self, tmp_path):
        """A Doc converted by sync_folder's convert_markdown path carries only
        _CONVERT_MARKDOWN_SOURCE_PROP, never the generic marker — it's still
        this tool's own conversion and must count as verified (#769)."""
        (tmp_path / "notes.md").write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "name": "notes",
                    "mimeType": "application/vnd.google-apps.document",
                    "properties": {transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                }
            ]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["notes.md"]
        assert result["skipped_unverified"] == []

    async def test_full_name_match_stays_unconditional_without_marker(self, tmp_path):
        """Only the stem lookup needs the marker (#769) — an unmarked entry
        matching the full local name in the target format is still a plain skip."""
        (tmp_path / "notes.md").write_text("# Heading")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "notes.md", "mimeType": "application/vnd.google-apps.document"}]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["notes.md"]
        assert result["skipped_unverified"] == []

    async def test_non_convert_bulk_list_does_not_fetch_properties(self, tmp_path):
        """Only the convert stem check reads the marker (PR #800 QA round 1, item 4)."""
        (tmp_path / "a.txt").write_text("a")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "a.txt", "mimeType": "text/plain"}]
        }

        result = await self._tool()(str(tmp_path), "folder1", ctx=self._ctx(drive_svc))

        assert result["skipped"] == ["a.txt"]
        list_kwargs = drive_svc.files.return_value.list.call_args.kwargs
        assert "properties" not in list_kwargs["fields"]

    async def test_convert_long_name_digested_marker_is_recognized(self, tmp_path):
        """A name too long for a raw marker gets a digest; the rerun must still
        read it back as verified (PR #800 QA round 1, item 1)."""
        name = "L" * 114 + ".csv"
        (tmp_path / name).write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "name": name[:-4],
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "properties": transfer_module._convert_properties(name),
                }
            ]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == [name]
        assert result["skipped_unverified"] == []
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_skips_when_both_raw_and_converted_duplicates_exist(self, tmp_path):
        """A third convert=True run against a folder that already has both the
        raw pre-convert duplicate (TC-D242's scenario, matched by full name) and
        the already-converted file (TC-D243's scenario, matched by stem) must
        still recognize the converted one and skip, not create a third file —
        the two lookups must be independent, not short-circuit on the first
        (unrelated) match."""
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"name": "data.csv", "mimeType": "text/csv"},
                {
                    "name": "data",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "properties": {transfer_module._CONVERT_SOURCE_PROP: "data.csv"},
                },
            ]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["data.csv"]
        assert result["uploaded"] == []
        drive_svc.files.return_value.create.assert_not_called()

    async def test_convert_recognizes_already_converted_when_two_drive_files_share_a_name(
        self, tmp_path
    ):
        """#514 (surfaced during PR #505's review of #411): Drive allows more
        than one file to share a literal name. The old existing_by_name dict
        comprehension kept only the *last*-iterated entry for a given name,
        so whichever of the raw/converted duplicates Drive happened to list
        last decided the (wrong, order-dependent) skip outcome. Here both
        entries are literally named "data.csv" — the raw one listed *after*
        the already-converted one, the ordering under which the old
        last-write-wins dict would have silently lost the converted
        classification and reconverted a duplicate."""
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"name": "data.csv", "mimeType": "application/vnd.google-apps.spreadsheet"},
                {"name": "data.csv", "mimeType": "text/csv"},
            ]
        }

        result = await self._tool()(
            str(tmp_path), "folder1", convert=True, ctx=self._ctx(drive_svc)
        )

        assert result["skipped"] == ["data.csv"]
        assert result["uploaded"] == []
        drive_svc.files.return_value.create.assert_not_called()

    async def test_skip_if_exists_false_uploads_despite_colliding_existing_files(self, tmp_path):
        """#514: the per-candidate skip check is gated explicitly on
        skip_if_exists rather than relying on existing_by_name being empty
        when it's False, so a future change that populates existing_by_name
        for an unrelated reason can't silently reintroduce skip behavior a
        caller explicitly opted out of."""
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid1",
            "name": "data.csv",
            "webViewLink": "https://example.com",
        }

        result = await self._tool()(
            str(tmp_path), "folder1", skip_if_exists=False, ctx=self._ctx(drive_svc)
        )

        assert result["uploaded"] == ["data.csv"]
        assert result["skipped"] == []
        drive_svc.files.return_value.list.assert_not_called()

    async def test_file_deleted_mid_loop_reported_as_failed_not_raised(self, tmp_path, monkeypatch):
        """_upload_local_file raises ValueError uncaught if the local file is
        gone by the time it's actually called (its own path.is_file() check
        runs before its try/except) — e.g. deleted between the directory scan
        and this file's turn in the loop. The old inline upload code caught
        this per-file; the refactor to _upload_local_file needs its own
        try/except to keep that isolation (PR #505 review, issue #411).
        Simulated via monkeypatch since a real race on disk isn't reliably
        reproducible in a unit test."""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}

        real_upload = transfer_module._upload_local_file

        async def _flaky(drive_service, local_path, *args, **kwargs):
            if local_path.endswith("b.txt"):
                raise ValueError(f"No file found at {local_path!r}")
            return await real_upload(drive_service, local_path, *args, **kwargs)

        monkeypatch.setattr(transfer_module, "_upload_local_file", _flaky)
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid",
            "name": "a.txt",
            "webViewLink": "https://example.com",
        }

        result = await self._tool()(str(tmp_path), "folder1", ctx=self._ctx(drive_svc))

        assert result["uploaded"] == ["a.txt"]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "b.txt"
        assert "No file found" in result["failed"][0]["error"]

    async def test_create_failure_reported_as_failed_not_raised(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.side_effect = RuntimeError("boom")

        result = await self._tool()(str(tmp_path), "folder1", ctx=self._ctx(drive_svc))

        assert result["uploaded"] == []
        assert result["failed"] == [{"name": "a.txt", "error": "boom"}]

    async def test_no_upload_does_not_mark_folder_cache_dirty(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"name": "a.txt", "mimeType": "text/plain"}]
        }
        ctx = self._ctx(drive_svc)

        result = await self._tool()(str(tmp_path), "folder1", ctx=ctx)

        assert result["uploaded"] == []
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_not_called()

    async def test_missing_local_directory_raises(self, tmp_path):
        drive_svc = MagicMock()
        with pytest.raises(ValueError, match="No directory found"):
            await self._tool()(str(tmp_path / "missing"), "folder1", ctx=self._ctx(drive_svc))


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
    plus `files().create`/`files().update` that record what would have been written,
    and `revisions().list` (#814) serving `revisions[file_id]` (default ["1"]) as
    a single page, or raising `revision_errors[file_id]` if set."""

    def __init__(self, children: dict[str, list[dict]]):
        self.children = children  # folder_id -> Drive API file/folder dicts
        self.list_calls: list[str] = []  # folder ids queried, in order
        self.created_folders: list[dict] = []
        self.created_files: list[dict] = []
        self.updated_files: list[dict] = []
        self.revisions: dict[str, list[str]] = {}
        self.revision_errors: dict[str, Exception] = {}
        self.revision_list_calls: list[str] = []

        self.svc = MagicMock()
        self.svc.files.return_value.list.side_effect = self._list
        self.svc.files.return_value.create.side_effect = self._create
        self.svc.files.return_value.update.side_effect = self._update
        self.svc.revisions.return_value.list.side_effect = self._list_revisions

    def _list_revisions(self, **kwargs):
        file_id = kwargs["fileId"]
        self.revision_list_calls.append(file_id)
        resp = MagicMock()
        if file_id in self.revision_errors:
            resp.execute.side_effect = self.revision_errors[file_id]
        else:
            ids = self.revisions.get(file_id, ["1"])
            resp.execute.return_value = {"revisions": [{"id": i} for i in ids]}
        return resp

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


class _RestampFailsFakeDriveFS(_FakeDriveFS):
    """_FakeDriveFS variant that fails only the metadata-only modifiedTime
    restamp update() that follows a successful create() on a convert_markdown
    upload (#420). It tells that call apart from the media-carrying update()
    used to re-import an *existing* converted Doc purely by the absence of
    `media_body` in the kwargs — so any test relying on this fixture also has
    to prove that discriminator against the case it's meant to distinguish
    from, i.e. a real re-upload of an existing file must still pass straight
    through to the parent's _update (#650)."""

    def _update(self, **kwargs):
        if "media_body" not in kwargs:
            raise RuntimeError("transient network error")
        return super()._update(**kwargs)


def _drive_file(
    name,
    file_id,
    mtime="2024-01-01T00:00:00.000Z",
    mime="text/plain",
    properties=None,
    md5=None,
    size=None,
):
    f = {"id": file_id, "name": name, "mimeType": mime, "modifiedTime": mtime}
    if properties is not None:
        f["properties"] = properties
    if md5 is not None:
        f["md5Checksum"] = md5
    if size is not None:
        f["size"] = str(size)  # Drive returns size as a string
    return f


def _precise_mtime(path: Path) -> str:
    """The microsecond-precision source-mtime stamp #814 writes for `path`."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _pop_uploaded_at(props: dict) -> str:
    """Remove and sanity-check the upload-time stamp (#814), which is "now"."""
    value = props.pop(transfer_module._CONVERTED_MD_UPLOADED_AT_PROP)
    stamped = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    assert abs(stamped - time.time()) < 60
    return value


def _drive_folder(name, folder_id):
    return {"id": folder_id, "name": name, "mimeType": "application/vnd.google-apps.folder"}


class TestSyncFolderValidation:
    """Issue #488: `sync_folder` already rejected an unrecognized `direction`
    up front (a `raise ValueError`, present since the domain-based refactor)
    — `_sync_level` itself has no such check, but it's only ever reached
    through this validated wrapper, so a bad value could never actually reach
    it. The real gap was the error's shape: a raised exception rather than
    the `{"error": ...}` dict every other bad-enum-like-param case in this
    codebase returns (e.g. `add_data_validation`'s `condition_type`), and
    there was no test coverage of either behavior. Fixed by returning the
    dict instead of raising, per the maintainer's decision on the issue.

    PR #563 review round: the adjacent `export_format` check three lines
    below `direction`'s had the identical bug (raise instead of return),
    caught live by QA and confirmed as in-scope for the same fix — this
    tool's own `export_format`, not `download_file`'s separate check of the
    same name (see `TestDownloadFile`'s own raise-based tests, untouched)."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    async def test_invalid_direction_returns_error_dict(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="mirror",
            ctx=self._ctx(fs),
        )
        assert result == {
            "error": "Invalid direction 'mirror'. Use 'upload', 'download', or 'bidirectional'."
        }
        assert fs.list_calls == []  # rejected before any Drive API call

    async def test_invalid_export_format_returns_error_dict(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="bogus",
            ctx=self._ctx(fs),
        )
        assert result["error"].startswith("Unknown export_format 'bogus'. Valid: ")
        assert fs.list_calls == []  # rejected before any Drive API call


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

    async def test_progress_message_includes_running_bytes_transferred(self, tmp_path):
        """#352: sync_folder's progress/total stay file-count-based with no total
        (recursive descent means the overall count isn't known upfront) — the
        message text adds a running total of bytes transferred so far as
        supplementary context."""
        (tmp_path / "a.txt").write_text("hi")  # 2 bytes
        (tmp_path / "b.txt").write_text("bye!")  # 4 bytes
        fs = _FakeDriveFS({"root": []})
        ctx = self._ctx(fs)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=ctx,
        )
        assert set(result["uploaded"]) == {"a.txt", "b.txt"}
        messages = [c.args[2] for c in ctx.report_progress.await_args_list]
        assert all(m.endswith("bytes so far") for m in messages)
        # progress/total (args[0]/args[1]) are unaffected — still file-count-based
        # with no total, per the docstring's own documented Progress behavior.
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] is None
        # Running total accumulates across both uploads (2 then 6, in whichever
        # order the concurrent gather completes them).
        assert any("6 bytes so far" in m for m in messages)

    async def test_upload_stat_failure_after_successful_write_reports_orphan_fileId(
        self, tmp_path, monkeypatch
    ):
        """#352 QA review, finding #1: the new bytes-reporting `p.stat()` call
        used to sit inside the same try/except that covers the Drive create()/
        update() calls above it. If the local file is deleted/moved in the
        window between the Drive write succeeding and this stat() call, the
        exception fell into the enclosing except and reported upload_fail with
        no fileId — unlike the restamp-failure branch a few lines above
        (#420/#650), which deliberately reports fileId so a genuinely-created
        Drive object isn't left untracked. The stat() call now has its own
        try/except mirroring that pattern."""
        local_file = tmp_path / "a.txt"
        local_file.write_text("hi")
        fs = _FakeDriveFS({"root": []})
        ctx = self._ctx(fs)

        real_stat = Path.stat

        def _flaky_stat(self, *args, **kwargs):
            # Raise only once the fake Drive write has actually landed —
            # simulates the local file vanishing in the window between the
            # Drive write succeeding and the post-write size stat(), without
            # having to guess how many earlier stat() calls (e.g. the
            # pre-upload mtime read) happen first.
            if self == local_file and fs.created_files:
                raise OSError("No such file or directory")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", _flaky_stat)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=ctx,
        )

        # The Drive write genuinely succeeded before the stat() failed.
        assert len(fs.created_files) == 1
        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        entry = result["failed"][0]
        assert entry["name"] == "a.txt"
        assert "failed to stat the local file afterward" in entry["error"]
        assert entry["fileId"] == "new-file-1"
        # A genuine Drive-side change still earns a cache invalidation, the same
        # as a real upload_ok (mirrors the restamp-failure case above).
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "root"
        )

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

    async def test_report_progress_failure_does_not_demote_a_successful_upload(self, tmp_path):
        """PR #351 review: ctx.report_progress raising (e.g. a dropped session)
        must not overwrite an already-successful upload's result, and must not
        skip the drive_folder_cache invalidation that a real mutation earns."""
        (tmp_path / "a.txt").write_text("hi")
        fs = _FakeDriveFS({"root": []})
        ctx = self._ctx(fs)
        ctx.report_progress.side_effect = RuntimeError("connection dropped")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=ctx,
        )
        assert result["uploaded"] == ["a.txt"]
        assert result["failed"] == []
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "root"
        )

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


class TestSyncFolderConvertMarkdown:
    """Issue #211: sync_folder's convert_markdown param uploads local .md files via
    Drive's native import conversion (same mechanism as upload_local_file's convert
    param, #188), landing as Google Docs that keep their '.md' name so later syncs
    match them back to their local counterpart instead of re-uploading a duplicate
    every run."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    async def test_local_only_md_file_converts_to_google_doc(self, tmp_path):
        (tmp_path / "notes.md").write_text("# Heading\n\nBody text.")
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == ["notes.md"]
        assert fs.created_files[0]["name"] == "notes.md"
        assert fs.created_files[0]["mimeType"] == "application/vnd.google-apps.document"
        props = dict(fs.created_files[0]["properties"])
        _pop_uploaded_at(props)
        assert props == {
            transfer_module._CONVERT_SOURCE_PROP: "notes.md",
            transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md",
            # #814: the local-side reference; a new Doc has no baseline.
            transfer_module._CONVERTED_MD_SOURCE_MTIME_PROP: _precise_mtime(tmp_path / "notes.md"),
        }
        create_kwargs = fs.svc.files.return_value.create.call_args_list[-1].kwargs
        assert create_kwargs["media_body"].mimetype() == "text/markdown"
        # TC-D218 root cause: Drive's native import-conversion overwrites the
        # modifiedTime requested on create() with its own "now" — a metadata-only
        # follow-up update() re-stamps it correctly.
        assert len(fs.updated_files) == 1
        assert fs.updated_files[0]["fileId"] == "new-file-1"
        assert "modifiedTime" in fs.updated_files[0]["body"]
        assert "media_body" not in fs.updated_files[0]

    @pytest.mark.parametrize(
        ("name", "digested"),
        [
            # Too long for the markdown key, still fits the generic key raw.
            ("n" * 100 + ".md", False),
            # Too long for either: the generic marker falls back to a digest.
            ("n" * 110 + ".md", True),
        ],
    )
    async def test_long_md_name_upload_stamps_every_property_within_cap(
        self, tmp_path, name, digested
    ):
        """#805: a .md name over ~95 bytes used to be stamped raw into the
        markdown key, failing create() with 403 propertyLengthLimitExceeded
        after Drive had already made the Doc — one more orphan per run."""
        (tmp_path / name).write_text("# Heading")
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == [name]
        assert result["failed"] == []
        props = fs.created_files[0]["properties"]
        assert transfer_module._CONVERT_MARKDOWN_SOURCE_PROP not in props
        assert props[transfer_module._CONVERT_SOURCE_PROP].startswith("sha256:") == digested
        for key, value in props.items():
            assert transfer_module._property_fits(key, value), (key, value)

    @pytest.mark.parametrize("name", ["n" * 100 + ".md", "n" * 110 + ".md", "長い" * 30 + ".md"])
    async def test_resync_matches_long_name_doc_via_digest_marker(self, tmp_path, name):
        """A Doc stamped with only the digested generic marker (a long name,
        from either sync_folder or upload_local_file's convert path) must
        still match its local file on resync, not re-upload as a duplicate."""
        local_file = tmp_path / name
        local_file.write_text("# Heading")
        drive_mtime = "2024-06-01T12:00:00.000Z"
        ts = datetime.fromisoformat(drive_mtime.replace("Z", "+00:00")).timestamp()
        os.utime(local_file, (ts, ts))
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        name,
                        "fa",
                        mtime=drive_mtime,
                        mime="application/vnd.google-apps.document",
                        properties=transfer_module._convert_properties(name),
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            ctx=self._ctx(fs),
        )

        assert result["skipped"] == [name]
        assert result["uploaded"] == []
        assert fs.created_files == []

    async def test_convert_markdown_false_default_uploads_md_as_plain_text(self, tmp_path):
        (tmp_path / "notes.md").write_text("# Heading")
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == ["notes.md"]
        assert "mimeType" not in fs.created_files[0]

    async def test_resync_matches_existing_converted_doc_by_name_not_reuploaded(self, tmp_path):
        """The converted Doc keeps the '.md' name in Drive, so a resync must match
        it directly against the local file (bypassing the export_format-suffix
        scheme used for other Workspace files) — otherwise it looks 'local only'
        again and gets re-uploaded as a duplicate on every sync."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_mtime = "2024-06-01T12:00:00.000Z"
        os.utime(
            local_file,
            (
                datetime.fromisoformat(drive_mtime.replace("Z", "+00:00")).timestamp(),
                datetime.fromisoformat(drive_mtime.replace("Z", "+00:00")).timestamp(),
            ),
        )
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime=drive_mtime,
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["skipped"] == ["notes.md"]
        assert result["uploaded"] == []
        assert fs.created_files == []

    async def test_local_edit_after_conversion_updates_in_place_not_recreated(self, tmp_path):
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Updated heading")
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime="2020-01-01T00:00:00.000Z",  # far older than local
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == ["notes.md"]
        assert fs.created_files == []
        assert len(fs.updated_files) == 1
        assert fs.updated_files[0]["fileId"] == "fa"
        assert fs.updated_files[0]["media_body"].mimetype() == "text/markdown"
        # #814: a legacy Doc (no source-mtime stamp) gains the properties on
        # re-upload, with the pre-update latest revision as its baseline and
        # any stale import revision cleared.
        props = dict(fs.updated_files[0]["body"]["properties"])
        _pop_uploaded_at(props)
        assert props == {
            transfer_module._CONVERTED_MD_SOURCE_MTIME_PROP: _precise_mtime(local_file),
            transfer_module._CONVERTED_MD_BASELINE_REV_PROP: "1",
            transfer_module._CONVERTED_MD_IMPORT_REV_PROP: None,
        }
        assert fs.revision_list_calls == ["fa"]

    async def test_drive_only_converted_doc_reported_as_conflict_not_downloaded(self, tmp_path):
        """No reverse conversion exists (Google Doc -> markdown). A converted Doc
        with no local counterpart yet ('drive only') would normally trigger a
        download — matching it into drive_map without requiring export_format (so
        resyncs of already-converted files work) means this path must be guarded
        explicitly. #414 QA review (finding #4): this must be caught at plan-
        building time and reported as a clean 'conflict', not queued as a doomed
        'download' that only fails at runtime."""
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime="2030-01-01T00:00:00.000Z",
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["downloaded"] == []
        assert result["failed"] == []
        assert result["conflicts"] == ["notes.md"]

    async def test_plain_file_and_converted_doc_sharing_name_reported_as_failed(self, tmp_path):
        """#422 finding #1: Drive allows a plain file and a convert_markdown Doc to
        share the same display name, and both compute the same drive_map key —
        whichever was enumerated last used to silently win the slot, making the
        other completely invisible to sync (never uploaded, downloaded, or
        reported anywhere). Now reported as a clean failure instead, with neither
        entry touched."""
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file("notes.md", "plain-id", mime="text/markdown"),
                    _drive_file(
                        "notes.md",
                        "doc-id",
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    ),
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "notes.md"
        assert "notes.md" in result["failed"][0]["error"]
        assert result["uploaded"] == []
        assert result["downloaded"] == []
        assert result["skipped"] == []
        assert result["conflicts"] == []
        assert fs.created_files == []
        assert fs.updated_files == []

    async def test_two_plain_files_sharing_name_reported_as_failed(self, tmp_path):
        """#422 finding #2: the collision guard originally only fired when
        _is_converted_md differed between the two colliding entries (a plain
        file vs. a convert_markdown Doc) — leaving a same-type collision (e.g.
        two plain files sharing a display name) silently overwritten, the exact
        same bug class in a case the original fix didn't close."""
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file("notes.md", "plain-id-1", mime="text/markdown"),
                    _drive_file("notes.md", "plain-id-2", mime="text/plain"),
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            ctx=self._ctx(fs),
        )

        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "notes.md"
        assert "notes.md" in result["failed"][0]["error"]
        assert result["uploaded"] == []
        assert result["downloaded"] == []
        assert result["skipped"] == []
        assert result["conflicts"] == []

    async def test_collision_with_local_counterpart_reported_not_silently_dropped(self, tmp_path):
        """#422 finding #3: a *local* file whose name collides with a Drive-side
        plain-file/converted-Doc pair used to vanish from every output list
        (uploaded/downloaded/skipped/conflicts/actions) with zero acknowledgment
        — the plan loop's bare `continue` skipped it entirely whenever a local
        file happened to share the colliding name. It must now still be reported
        (as a real 'failed' entry for a non-dry-run call), the same as when
        there's no local counterpart at all."""
        (tmp_path / "notes.md").write_text("local content")
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file("notes.md", "plain-id", mime="text/markdown"),
                    _drive_file(
                        "notes.md",
                        "doc-id",
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    ),
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "notes.md"
        assert result["uploaded"] == []
        assert result["skipped"] == []
        assert result["conflicts"] == []
        assert fs.created_files == []
        assert fs.updated_files == []

    async def test_collision_dry_run_reports_conflict_not_failed(self, tmp_path):
        """#422 finding #4: dry_run must never report a 'failed' entry — only a
        preview. A name collision used to be written straight to `failed`
        unconditionally, even during dry_run where nothing is materialized,
        breaking that expectation (the pre-existing folder-collision failure
        path in this same function is explicitly guarded against this)."""
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file("notes.md", "plain-id", mime="text/markdown"),
                    _drive_file(
                        "notes.md",
                        "doc-id",
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    ),
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            dry_run=True,
            ctx=self._ctx(fs),
        )

        # #512: dry_run leaves the flat lists empty — 'actions' (asserted below) is
        # the sole, non-redundant source of truth for a dry_run preview.
        assert result["failed"] == []
        assert result["conflicts"] == []
        assert len(result["actions"]) == 1
        assert result["actions"][0]["name"] == "notes.md"
        assert result["actions"][0]["action"] == "collision"

    async def test_drive_only_converted_doc_skipped_not_conflict_under_upload_direction(
        self, tmp_path
    ):
        """#422 finding #3: the drive-only branch checked _is_converted_md before
        checking direction, so a convert_markdown Doc with no local counterpart
        always reported 'conflict' even under direction='upload' — where an
        ordinary (non-converted) drive-only file correctly reports a plain 'skip',
        since an upload-only caller doesn't care about drive-only content at all."""
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["skipped"] == ["notes.md"]
        assert result["conflicts"] == []
        assert result["downloaded"] == []
        assert result["failed"] == []

    async def test_unrelated_doc_with_matching_md_name_is_not_treated_as_converted(self, tmp_path):
        """#414 QA review (finding #2): a human-created Google Doc that happens to
        be named 'notes.md' but wasn't produced by convert_markdown (no source-name
        property) must not be matched as this tool's converted twin — that would
        let a same-named newer local file silently overwrite its real content."""
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime="2020-01-01T00:00:00.000Z",
                        mime="application/vnd.google-apps.document",
                        # No properties — an unrelated pre-existing Doc, not one
                        # this tool created.
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            dry_run=True,
            ctx=self._ctx(fs),
        )

        # No export_format and not a recognized converted twin -> excluded from the
        # plan entirely, same as any other Workspace file with no export_format.
        assert result["actions"] == []

    async def test_promoting_a_previously_plain_upload_fails_cleanly(self, tmp_path):
        """#414 QA review (finding #3): a .md file previously synced with
        convert_markdown=False landed as a plain Drive file (not a Doc). Drive's
        API has no supported way to convert an existing file's type via update() —
        only create() honors import conversion — so flipping convert_markdown=True
        later must not silently leave it unpromoted; it should fail with an
        actionable message instead."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Updated heading")
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime="2020-01-01T00:00:00.000Z",  # far older than local
                        mime="text/markdown",  # plain file, never converted
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "notes.md"
        assert "plain file" in result["failed"][0]["error"]
        assert fs.updated_files == []

    async def test_unreadable_mtime_at_upload_lands_in_failed(self, tmp_path, monkeypatch):
        """PR #817 QA round 1: _run_one read the local mtime before its try, so a
        file that vanished or became unreadable between the scan and the upload
        escaped upload_fail handling. The final failed entry looked the same
        (the gather's return_exceptions caught it), but the raw exception skipped
        _run_one_with_progress, so no progress notification went out for it. It
        must be a real upload_fail: reported as progress, nothing created."""
        (tmp_path / "notes.txt").write_text("x")
        fs = _FakeDriveFS({"root": []})

        def _boom(_path, _st=None):
            raise PermissionError("denied")

        monkeypatch.setattr(transfer_module, "_local_mtime_dt", _boom)
        ctx = self._ctx(fs)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=ctx,
        )

        assert result["uploaded"] == []
        assert result["failed"] == [{"name": "notes.txt", "error": "denied"}]
        assert fs.created_files == []
        ctx.report_progress.assert_awaited_once()
        assert ctx.report_progress.await_args.args[2] == "notes.txt: upload_fail"

    async def test_restamp_failure_after_successful_create_reports_orphan_fileId(self, tmp_path):
        """#420: sync_folder's convert_markdown upload path wraps the create() call
        and its metadata-only restamp update() in the same step. If create()
        succeeds but the follow-up restamp fails (transient error), the Doc still
        genuinely exists in Drive — reporting a bare 'upload_fail' with no fileId
        would leave it an untracked orphan with no way to find it. The failed
        entry must carry the created file's own ID alongside the error."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")

        fs = _RestampFailsFakeDriveFS({"root": []})
        ctx = self._ctx(fs)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=ctx,
        )

        # The Doc was genuinely created in Drive before the restamp failed.
        assert len(fs.created_files) == 1
        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        entry = result["failed"][0]
        assert entry["name"] == "notes.md"
        assert "transient network error" in entry["error"]
        assert entry["fileId"] == "new-file-1"
        # #420 QA round 1 (PR #645): create() genuinely changed the folder even
        # though the overall step reports upload_fail — the cache must still be
        # invalidated, not just for a real upload_ok/download_ok.
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "root"
        )

    async def test_restamp_fixture_lets_existing_file_reimport_through(self, tmp_path):
        """#650: _RestampFailsFakeDriveFS tells the metadata-only restamp update()
        apart from a real re-import update() purely by the absence of `media_body`.
        The restamp-failure test above only ever exercises the create() path
        (empty Drive folder), so nothing verified that discriminator against the
        case it's meant to distinguish from. Here a converted Doc already exists
        and the newer local file re-imports in place: that update() carries
        `media_body`, so it must pass straight through to the parent _update and
        the sync must succeed — not be misfired as the restamp failure."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Updated heading")
        fs = _RestampFailsFakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime="2020-01-01T00:00:00.000Z",  # far older than local
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["failed"] == []
        assert result["uploaded"] == ["notes.md"]
        assert fs.created_files == []
        assert len(fs.updated_files) == 1
        assert fs.updated_files[0]["fileId"] == "fa"
        assert "media_body" in fs.updated_files[0]

    async def test_restamp_quota_failure_uses_friendly_message(self, tmp_path):
        """#650: _sync_level._run_one's restamp except mirrors _upload_local_file's
        and had the same gap — a storageQuotaExceeded HttpError there leaked its
        raw text instead of the shared _SA_QUOTA_ERROR message. The upload_fail
        entry must carry the friendly message and still report the orphan fileId."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")

        class _RestampQuotaFailsFakeDriveFS(_FakeDriveFS):
            def _update(self, **kwargs):
                if "media_body" not in kwargs:
                    resp = MagicMock()
                    resp.status = 403
                    raise HttpError(
                        resp=resp,
                        content=b'{"error": {"reason": "storageQuotaExceeded"}}',
                    )
                return super()._update(**kwargs)

        fs = _RestampQuotaFailsFakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        entry = result["failed"][0]
        assert entry["name"] == "notes.md"
        assert entry["fileId"] == "new-file-1"
        assert "storageQuotaExceeded" not in entry["error"]
        assert transfer_module._SA_QUOTA_ERROR in entry["error"]

    async def test_upload_create_quota_failure_uses_friendly_message(self, tmp_path):
        """#670: _sync_level._run_one's *outer* catch-all `except Exception` (the
        one wrapping the whole create()/update() block, not the restamp except
        fixed in #650) returned a bare str(e). A storageQuotaExceeded HttpError
        raised by files().create() lands there and previously leaked Drive's raw
        error blob instead of the shared _SA_QUOTA_ERROR text. Exercised via a
        plain (non-convert) upload so the failure is create() itself, not the
        convert_markdown restamp."""
        (tmp_path / "readme.txt").write_text("hello")

        class _CreateQuotaFailsFakeDriveFS(_FakeDriveFS):
            def _create(self, **kwargs):
                resp = MagicMock()
                resp.status = 403
                raise HttpError(
                    resp=resp,
                    content=b'{"error": {"reason": "storageQuotaExceeded"}}',
                )

        fs = _CreateQuotaFailsFakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == []
        assert len(result["failed"]) == 1
        entry = result["failed"][0]
        assert entry["name"] == "readme.txt"
        assert "storageQuotaExceeded" not in entry["error"]
        assert transfer_module._SA_QUOTA_ERROR in entry["error"]

    async def test_bidirectional_resync_after_initial_convert_stays_in_sync(self, tmp_path):
        """TC-D218 (#414 QA review): Drive's native import-conversion on create()
        overwrites the modifiedTime we request with its own 'now' once conversion
        finishes, unlike update() which honors it correctly. Without a follow-up
        metadata-only update() re-stamping the correct modifiedTime after create(),
        a bidirectional resync with no local changes reads Drive as newer, tries to
        download the (unconvertible) Doc, and the file gets stuck 'failed' forever."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        local_mtime_str = datetime.fromtimestamp(
            local_file.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        fs = _FakeDriveFS({"root": []})
        ctx = self._ctx(fs)

        first = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=ctx,
        )
        assert first["uploaded"] == ["notes.md"]

        # The create() call requested the local mtime, but Drive's conversion
        # would normally overwrite it with its own "now" — simulate that by NOT
        # trusting fs.created_files[0]["modifiedTime"] and instead asserting the
        # follow-up update() call is what actually carries the correct value.
        assert len(fs.updated_files) == 1
        assert fs.updated_files[0]["fileId"] == "new-file-1"
        assert fs.updated_files[0]["body"] == {"modifiedTime": local_mtime_str}

        # Simulate Drive's real behavior: the created entry now shows Drive's own
        # (later) modifiedTime rather than what create() was asked to set, exactly
        # as if the metadata-only update() above had never landed — proving the
        # resync only stays clean because that follow-up call fixed it.
        fs.children["root"] = [
            _drive_file(
                "notes.md",
                "new-file-1",
                mtime=local_mtime_str,
                mime="application/vnd.google-apps.document",
                properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
            )
        ]

        second = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=ctx,
        )
        assert second["skipped"] == ["notes.md"]
        assert second["downloaded"] == []
        assert second["failed"] == []
        assert second["conflicts"] == []

    async def test_resync_without_flag_still_matches_and_does_not_duplicate(self, tmp_path):
        """#414 QA review round 3, finding #1: matching used to be gated on this
        call's own convert_markdown flag, not just the Doc's stamped property. A
        resync that simply omitted convert_markdown=True on a folder containing an
        already-converted Doc saw the local .md as 'local only' and silently
        created a second, plain-text duplicate. Matching must recognize the Doc by
        its property regardless of this call's flag."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_mtime_str = datetime.fromtimestamp(
            local_file.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime=drive_mtime_str,
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            # convert_markdown intentionally omitted (defaults False) — the Doc was
            # converted on a prior call, this one just forgot the flag.
            ctx=self._ctx(fs),
        )

        assert result["skipped"] == ["notes.md"]
        assert result["uploaded"] == []
        assert fs.created_files == []

    async def test_local_edit_without_flag_reimports_in_place_not_duplicated(self, tmp_path):
        """Companion to the above: a local edit to an already-converted Doc must
        still update() in place (correct reimport mimetype) even when this call
        omits convert_markdown, rather than either duplicating or corrupting the
        Doc with a plain-text/octet-stream re-upload."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Updated heading")
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime="2020-01-01T00:00:00.000Z",  # far older than local
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == ["notes.md"]
        assert fs.created_files == []
        assert len(fs.updated_files) == 1
        assert fs.updated_files[0]["fileId"] == "fa"
        assert fs.updated_files[0]["media_body"].mimetype() == "text/markdown"

    async def test_upload_local_file_conversion_recognized_by_sync_folder(self, tmp_path):
        """#414 QA review round 3, finding #2: a Doc converted via
        upload_local_file(convert=True) must be recognized by sync_folder's
        convert_markdown matching too — before the fix, only sync_folder's own
        create() call stamped the marker property, so upload_local_file's converted
        Docs were invisible to it and got silently duplicated on the next
        sync_folder run."""
        local_file = tmp_path / "notes.md"
        local_file.write_text("# Heading")
        drive_mtime_str = datetime.fromtimestamp(
            local_file.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # Simulates the Doc upload_local_file(convert=True) would have created —
        # same marker property, same mechanism, different call site.
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime=drive_mtime_str,
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            convert_markdown=True,
            ctx=self._ctx(fs),
        )

        # Recognized as an in-sync match, not a "local only" file to be uploaded as
        # a second, unconverted duplicate.
        assert result["skipped"] == ["notes.md"]
        assert result["uploaded"] == []
        assert fs.created_files == []


class TestConvertedMdDriveState:
    """#814: the Drive side of a convert_markdown Doc is judged from revision
    history, not modifiedTime."""

    @staticmethod
    def _revs(*ids, times=None):
        times = times or {}
        return [{"id": i, **({"modifiedTime": times[i]} if i in times else {})} for i in ids]

    @pytest.mark.parametrize(
        ("props", "ids", "expected"),
        [
            # New Doc, first sync: its first revision is the import.
            ({}, ["1"], ("unchanged", "1")),
            ({}, ["1", "2"], ("changed", "1")),
            # Import already recorded.
            ({"geeSweetImportRevision": "1"}, ["1"], ("unchanged", None)),
            ({"geeSweetImportRevision": "1"}, ["1", "2"], ("changed", None)),
            # Recorded import trimmed away, latest is something else: an edit.
            ({"geeSweetImportRevision": "1"}, ["5"], ("changed", None)),
            # Re-upload: the import is the first revision after the baseline.
            ({"geeSweetBaselineRevision": "2"}, ["1", "2", "3"], ("unchanged", "3")),
            ({"geeSweetBaselineRevision": "2"}, ["1", "2", "3", "4"], ("changed", "3")),
            # Import not listed yet.
            ({"geeSweetBaselineRevision": "2"}, ["1", "2"], ("pending", None)),
            # Baseline gone and no upload time to fall back on.
            ({"geeSweetBaselineRevision": "2"}, ["1", "3"], ("baseline_missing", None)),
        ],
    )
    def test_states(self, props, ids, expected):
        assert transfer_module._converted_md_drive_state(props, self._revs(*ids)) == expected

    _UPLOADED = "2026-01-01T00:00:00.000Z"

    def test_import_merged_into_later_edit_is_changed(self):
        """PR #854 QA round 1: a Doc edited in Drive and first synced long after,
        once Drive compacted its history to just the edit. Taking that edit as
        the import would let the next local change overwrite it."""
        props = {"geeSweetUploadedAt": self._UPLOADED}
        revs = self._revs("7", times={"7": "2026-01-20T00:00:00.000Z"})

        assert transfer_module._converted_md_drive_state(props, revs) == ("changed", None)

    def test_import_within_window_is_accepted(self):
        props = {"geeSweetUploadedAt": self._UPLOADED}
        revs = self._revs("1", times={"1": "2026-01-01T00:00:04.000Z"})

        assert transfer_module._converted_md_drive_state(props, revs) == ("unchanged", "1")

    def test_pruned_baseline_falls_back_to_upload_time(self):
        """PR #854 QA round 1: a pruned baseline used to leave an unedited Doc
        in 'baseline_missing' for good."""
        props = {"geeSweetBaselineRevision": "2", "geeSweetUploadedAt": self._UPLOADED}
        revs = self._revs(
            "1",
            "3",
            times={"1": "2025-12-01T00:00:00.000Z", "3": "2026-01-01T00:00:05.000Z"},
        )

        assert transfer_module._converted_md_drive_state(props, revs) == ("unchanged", "3")

    def test_pruned_baseline_with_no_revision_since_upload_is_pending(self):
        props = {"geeSweetBaselineRevision": "2", "geeSweetUploadedAt": self._UPLOADED}
        revs = self._revs("1", times={"1": "2025-12-01T00:00:00.000Z"})

        assert transfer_module._converted_md_drive_state(props, revs) == ("pending", None)


class TestSyncFolderConvertedDocChangeDetection:
    """#814: a convert_markdown Doc carrying the source-mtime stamp is synced
    without consulting Drive's modifiedTime, which the Docs backend updates
    minutes behind an edit (so it both overwrote the restamp and hid real Drive
    edits). The local side compares against the stamped mtime, the Drive side
    against revision history."""

    _LOCAL_MTIME = datetime(2025, 6, 1, tzinfo=timezone.utc)
    _STAMP = "2025-06-01T00:00:00.000Z"

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _setup(self, tmp_path, *, local_offset=0.0, drive_mtime=None, props=None):
        """A local notes.md whose mtime is `local_offset` seconds after the
        stamped source mtime, and a matching converted Doc `fa`. The Doc's
        modifiedTime defaults to far in the future, which the modifiedTime
        comparison would read as "Drive newer": every test here therefore also
        shows that value isn't consulted."""
        local = tmp_path / "notes.md"
        local.write_text("# Notes")
        ts = self._LOCAL_MTIME.timestamp() + local_offset
        os.utime(local, (ts, ts))
        all_props = {
            transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md",
            transfer_module._CONVERTED_MD_SOURCE_MTIME_PROP: self._STAMP,
            **(props or {}),
        }
        return _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime=drive_mtime or "2030-01-01T00:00:00.000Z",
                        mime="application/vnd.google-apps.document",
                        properties=all_props,
                    )
                ]
            }
        )

    async def _sync(self, fs, tmp_path, direction="bidirectional", dry_run=False):
        return await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction=direction,
            dry_run=dry_run,
            ctx=self._ctx(fs),
        )

    async def test_unchanged_doc_skipped_despite_drifted_modified_time(self, tmp_path):
        """The original report: a restamp overwritten by the late async
        modifiedTime update read as "Drive newer" and sat in conflicts."""
        fs = self._setup(tmp_path, props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"})

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]
        assert result["conflicts"] == []
        assert fs.revision_list_calls == ["fa"]
        assert fs.updated_files == []  # nothing new to record

    async def test_first_sync_records_import_revision(self, tmp_path):
        fs = self._setup(tmp_path)
        fs.revisions["fa"] = ["1"]

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]
        assert fs.updated_files == [
            {
                "fileId": "fa",
                # modifiedTime too: a property write would otherwise bump it
                # to "now", undoing the cosmetic restamp.
                "body": {
                    "properties": {transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
                    "modifiedTime": self._STAMP,
                },
                "supportsAllDrives": True,
                "fields": "id",
            }
        ]

    async def test_first_sync_after_reupload_records_revision_after_baseline(self, tmp_path):
        fs = self._setup(tmp_path, props={transfer_module._CONVERTED_MD_BASELINE_REV_PROP: "2"})
        fs.revisions["fa"] = ["1", "2", "3"]

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]
        assert fs.updated_files[0]["body"] == {
            "properties": {transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "3"},
            "modifiedTime": self._STAMP,
        }

    async def test_failed_import_revision_record_does_not_fail_sync(self, tmp_path):
        fs = self._setup(tmp_path)

        def _fail(**kwargs):
            raise RuntimeError("transient")

        fs.svc.files.return_value.update.side_effect = _fail

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]
        assert result["failed"] == []

    async def test_drive_edit_detected_while_modified_time_still_lags(self, tmp_path):
        """The missed-edit half of #814: Drive's modifiedTime still matches the
        local file minutes after a Docs edit, which the modifiedTime comparison
        reported as in sync. The new revision shows it immediately."""
        fs = self._setup(
            tmp_path,
            drive_mtime=self._STAMP,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )
        fs.revisions["fa"] = ["1", "2"]

        result = await self._sync(fs, tmp_path, direction="upload")

        assert result["conflicts"] == ["notes.md"]
        assert result["skipped"] == []
        assert fs.updated_files == []

    async def test_both_sides_changed_is_conflict_not_overwrite(self, tmp_path):
        """Local newer used to upload straight over a Drive edit."""
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )
        fs.revisions["fa"] = ["1", "2"]

        result = await self._sync(fs, tmp_path, dry_run=True)

        assert result["actions"][0]["action"] == "conflict"
        assert "edited both locally and in Drive" in result["actions"][0]["reason"]

        result = await self._sync(fs, tmp_path)
        assert result["conflicts"] == ["notes.md"]
        assert result["uploaded"] == []
        assert fs.updated_files == []

    async def test_local_change_uploads_with_fresh_baseline(self, tmp_path):
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )
        fs.revisions["fa"] = ["1"]

        result = await self._sync(fs, tmp_path)

        assert result["uploaded"] == ["notes.md"]
        (update,) = fs.updated_files
        assert update["fileId"] == "fa"
        props = dict(update["body"]["properties"])
        _pop_uploaded_at(props)
        assert props == {
            transfer_module._CONVERTED_MD_SOURCE_MTIME_PROP: _precise_mtime(tmp_path / "notes.md"),
            transfer_module._CONVERTED_MD_BASELINE_REV_PROP: "1",
            transfer_module._CONVERTED_MD_IMPORT_REV_PROP: None,
        }
        assert update["body"]["modifiedTime"] != self._STAMP
        # One read to plan, one fresh read for the baseline just before update().
        assert fs.revision_list_calls == ["fa", "fa"]

    async def test_local_change_under_download_direction_is_conflict(self, tmp_path):
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )

        result = await self._sync(fs, tmp_path, direction="download")

        assert result["conflicts"] == ["notes.md"]
        assert fs.updated_files == []

    async def test_local_rollback_is_conflict(self, tmp_path):
        fs = self._setup(
            tmp_path,
            local_offset=-600,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )

        result = await self._sync(fs, tmp_path, dry_run=True)

        assert result["actions"][0]["action"] == "conflict"
        assert "older than the version last uploaded" in result["actions"][0]["reason"]

    async def test_local_change_waits_while_import_revision_pending(self, tmp_path):
        """Uploading again before the previous import is listed would stamp a
        baseline that predates it, so that import would later read as a Drive
        edit."""
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_BASELINE_REV_PROP: "2"},
        )
        fs.revisions["fa"] = ["1", "2"]

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]
        assert result["uploaded"] == []
        assert fs.updated_files == []

    async def test_missing_baseline_is_conflict(self, tmp_path):
        fs = self._setup(tmp_path, props={transfer_module._CONVERTED_MD_BASELINE_REV_PROP: "2"})
        fs.revisions["fa"] = ["1", "3"]

        result = await self._sync(fs, tmp_path, dry_run=True)

        assert result["actions"][0]["action"] == "conflict"
        assert (
            "revision recorded before its last upload is gone" in (result["actions"][0]["reason"])
        )

    async def test_revision_read_failure_reported_as_failed(self, tmp_path):
        fs = self._setup(tmp_path)
        fs.revision_errors["fa"] = RuntimeError("revisions unavailable")

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == []
        assert result["failed"] == [
            {
                "name": "notes.md",
                "error": (
                    "couldn't read the Doc's revision history to check for Drive edits: "
                    "revisions unavailable"
                ),
            }
        ]

    async def test_dry_run_checks_revisions_but_records_nothing(self, tmp_path):
        fs = self._setup(tmp_path)

        result = await self._sync(fs, tmp_path, dry_run=True)

        assert result["actions"] == [{"name": "notes.md", "action": "skip", "reason": "in sync"}]
        assert fs.revision_list_calls == ["fa"]
        assert fs.updated_files == []

    async def test_baseline_read_failure_fails_upload_before_update(self, tmp_path):
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )
        calls = []
        real = fs._list_revisions

        def _second_fails(**kwargs):
            calls.append(kwargs["fileId"])
            if len(calls) == 2:
                raise RuntimeError("revisions unavailable")
            return real(**kwargs)

        fs.svc.revisions.return_value.list.side_effect = _second_fails

        result = await self._sync(fs, tmp_path)

        assert result["uploaded"] == []
        assert result["failed"] == [{"name": "notes.md", "error": "revisions unavailable"}]
        assert fs.updated_files == []

    async def test_legacy_doc_without_stamp_keeps_modified_time_path(self, tmp_path):
        """No migration: a Doc converted before #814 isn't revision-checked."""
        local = tmp_path / "notes.md"
        local.write_text("# Notes")
        ts = self._LOCAL_MTIME.timestamp()
        os.utime(local, (ts, ts))
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "notes.md",
                        "fa",
                        mtime=self._STAMP,
                        mime="application/vnd.google-apps.document",
                        properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "notes.md"},
                    )
                ]
            }
        )

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]
        assert fs.revision_list_calls == []

    async def test_recording_on_drive_edited_doc_keeps_its_modified_time(self, tmp_path):
        """PR #854 QA round 1, item 1 (reproduced live): re-sending the stamped
        mtime on a Doc edited in Drive reset its modifiedTime, so the Drive UI
        and every other client saw it as unedited."""
        fs = self._setup(tmp_path)
        fs.revisions["fa"] = ["1", "2"]

        result = await self._sync(fs, tmp_path)

        assert result["conflicts"] == ["notes.md"]
        (update,) = fs.updated_files
        # Drive's own modifiedTime from the listing (_setup's default), not the
        # stamped source mtime, and never left out (which stamps "now").
        assert update["body"] == {
            "properties": {transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
            "modifiedTime": "2030-01-01T00:00:00.000Z",
        }

    async def test_local_save_within_seconds_of_upload_is_detected(self, tmp_path):
        """PR #854 QA round 1, item 2 (reproduced live): the 5s Drive clock-skew
        tolerance hid a local save made within 5s of the stamped mtime, and it
        never uploaded."""
        fs = self._setup(
            tmp_path,
            local_offset=3,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )

        result = await self._sync(fs, tmp_path)

        assert result["uploaded"] == ["notes.md"]

    async def test_sub_millisecond_difference_is_in_sync(self, tmp_path):
        fs = self._setup(
            tmp_path,
            local_offset=0.0002,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )

        result = await self._sync(fs, tmp_path)

        assert result["skipped"] == ["notes.md"]

    async def test_pending_local_change_under_download_is_conflict(self, tmp_path):
        """PR #854 QA round 1, item 3: 'pending' used to win over the
        direction check and promise an upload that download never makes."""
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_BASELINE_REV_PROP: "2"},
        )
        fs.revisions["fa"] = ["1", "2"]

        result = await self._sync(fs, tmp_path, direction="download", dry_run=True)

        assert result["actions"][0]["action"] == "conflict"
        assert "direction is download" in result["actions"][0]["reason"]

    async def test_recording_import_revision_marks_folder_dirty(self, tmp_path):
        """PR #854 QA round 1, item 4: the import-revision write changes the
        Doc's metadata, like every other write here that invalidates the cache."""
        fs = self._setup(tmp_path)
        ctx = self._ctx(fs)

        await _transfer_tools["sync_folder"](folder_id="root", local_path=str(tmp_path), ctx=ctx)

        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_with(
            "root"
        )

    async def test_empty_revision_history_is_drive_read_fail(self, tmp_path):
        """PR #854 QA round 1, item 5: an empty list read as 'changed', a false
        Drive-edit conflict whose advice changes the Doc's file ID."""
        fs = self._setup(tmp_path, props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"})
        fs.revisions["fa"] = []

        result = await self._sync(fs, tmp_path)

        assert result["conflicts"] == []
        assert result["failed"] == [
            {
                "name": "notes.md",
                "error": (
                    "couldn't read the Doc's revision history to check for Drive edits: "
                    "Drive returned an empty revision history"
                ),
            }
        ]

    async def test_drive_edit_between_plan_and_upload_is_conflict(self, tmp_path):
        """PR #854 QA round 1, item 6: the upload's fresh revision read now
        checks the plan's view still holds; an edit landing in between used to
        be absorbed into the baseline and overwritten."""
        fs = self._setup(
            tmp_path,
            local_offset=600,
            props={transfer_module._CONVERTED_MD_IMPORT_REV_PROP: "1"},
        )
        reads = iter([["1"], ["1", "2"]])

        def _moving(**kwargs):
            resp = MagicMock()
            resp.execute.return_value = {"revisions": [{"id": i} for i in next(reads)]}
            return resp

        fs.svc.revisions.return_value.list.side_effect = _moving

        result = await self._sync(fs, tmp_path)

        assert result["conflicts"] == ["notes.md"]
        assert result["uploaded"] == []
        assert fs.updated_files == []

    async def test_revision_list_follows_pagination(self):
        svc = MagicMock()
        pages = [
            {"revisions": [{"id": "1"}, {"id": "2"}], "nextPageToken": "t"},
            {"revisions": [{"id": "3"}]},
        ]
        svc.revisions.return_value.list.return_value.execute.side_effect = pages

        revisions = await transfer_module._list_revisions(svc, "fa")
        assert [r["id"] for r in revisions] == ["1", "2", "3"]
        tokens = [c.kwargs["pageToken"] for c in svc.revisions.return_value.list.call_args_list]
        assert tokens == [None, "t"]


class TestSyncFolderDownloadMtimeRoundTrip:
    """Issue #346: a downloaded file's local mtime defaulted to write time ('now'),
    not Drive's modifiedTime — since 'now' is always later than Drive's original
    timestamp, the next sync saw the file as locally newer and re-uploaded it
    (harmless to content, but wasteful, and repeats on every subsequent sync).
    Fixed by setting the local file's mtime to Drive's modifiedTime after a
    successful download, mirroring what the upload branch already does in
    reverse for the Drive side."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _workspace_fs(self, drive_mtime: str) -> _FakeDriveFS:
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "a",
                        "fa",
                        mtime=drive_mtime,
                        mime="application/vnd.google-apps.document",
                    )
                ]
            }
        )
        fs.svc.files.return_value.export.return_value.execute.return_value = b"content"
        return fs

    async def test_downloaded_file_mtime_matches_drive_modifiedtime(self, tmp_path):
        drive_mtime = "2024-06-01T12:00:00.000Z"
        fs = self._workspace_fs(drive_mtime)

        await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            export_format="pdf",
            ctx=self._ctx(fs),
        )

        local_mtime = datetime.fromtimestamp((tmp_path / "a.pdf").stat().st_mtime, tz=timezone.utc)
        expected = datetime.fromisoformat(drive_mtime.replace("Z", "+00:00"))
        assert abs((local_mtime - expected).total_seconds()) < 1

    async def test_resync_after_download_reports_skipped_not_reuploaded(self, tmp_path):
        drive_mtime = "2024-06-01T12:00:00.000Z"
        fs = self._workspace_fs(drive_mtime)
        ctx = self._ctx(fs)

        first = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            export_format="pdf",
            ctx=ctx,
        )
        assert first["downloaded"] == ["a.pdf"]

        second = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            export_format="pdf",
            ctx=ctx,
        )
        assert second["skipped"] == ["a.pdf"]
        assert second["downloaded"] == []
        assert second["uploaded"] == []


def _partial_files(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir() if transfer_module._is_partial_download(p.name)]


class _FailingDownloader:
    """Writes `written` bytes, then raises from the next chunk, like a dropped
    connection partway through a large download."""

    written = b"truncated"

    def __init__(self, fh, request):
        self._fh = fh
        self._calls = 0

    def next_chunk(self):
        self._calls += 1
        if self._calls == 1:
            self._fh.write(self.written)
            return None, False
        raise ConnectionError("connection reset mid-download")


class TestSyncFolderFailedDownloadLeavesNoPartial:
    """#844: a download that failed partway left a truncated file at the
    destination with a current mtime, which the next bidirectional sync read
    as locally newer and uploaded over the intact Drive copy."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _fs(self) -> _FakeDriveFS:
        return _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "big.bin",
                        "fbig",
                        mtime="2024-06-01T12:00:00.000Z",
                        mime="application/octet-stream",
                        size=50,
                    )
                ]
            }
        )

    async def test_failed_download_keeps_existing_local_file_intact(self, tmp_path, monkeypatch):
        local = tmp_path / "big.bin"
        local.write_bytes(b"old local content")
        old_mtime = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(local, (old_mtime, old_mtime))
        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FailingDownloader)
        fs = self._fs()

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="bidirectional",
            ctx=self._ctx(fs),
        )

        assert [f["name"] for f in result["failed"]] == ["big.bin"]
        assert local.read_bytes() == b"old local content"
        assert local.stat().st_mtime == old_mtime
        assert _partial_files(tmp_path) == []

    async def test_failed_download_then_resync_does_not_upload(self, tmp_path, monkeypatch):
        """The issue's scenario end to end: Drive-only file, download fails,
        the next sync must not upload anything over the Drive copy."""
        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FailingDownloader)
        fs = self._fs()
        ctx = self._ctx(fs)

        first = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(tmp_path), direction="bidirectional", ctx=ctx
        )
        assert [f["name"] for f in first["failed"]] == ["big.bin"]
        assert not (tmp_path / "big.bin").exists()
        assert _partial_files(tmp_path) == []

        second = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(tmp_path), direction="bidirectional", ctx=ctx
        )
        assert second["uploaded"] == []
        assert fs.created_files == []
        assert [u for u in fs.updated_files if "media_body" in u] == []

    async def test_failed_mtime_restamp_leaves_destination_untouched(self, tmp_path, monkeypatch):
        """The restamp runs before the rename, so a failure there can't leave a
        complete file with a 'now' mtime either."""

        class _OkDownloader:
            def __init__(self, fh, request):
                self._fh = fh

            def next_chunk(self):
                self._fh.write(b"complete")
                return None, True

        def _utime_fails(*args, **kwargs):
            raise PermissionError("utime denied")

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _OkDownloader)
        monkeypatch.setattr(transfer_module.os, "utime", _utime_fails)
        fs = self._fs()

        result = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(tmp_path), direction="bidirectional", ctx=self._ctx(fs)
        )

        assert [f["name"] for f in result["failed"]] == ["big.bin"]
        assert not (tmp_path / "big.bin").exists()
        assert _partial_files(tmp_path) == []

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0o444 file")
    async def test_read_only_local_file_is_a_download_fail_not_replaced(
        self, tmp_path, monkeypatch
    ):
        """PR #884 QA round 1: sync_folder's download branch must refuse a
        read-only local file the way the old in-place write did."""
        local = tmp_path / "big.bin"
        local.write_bytes(b"protected")
        old_mtime = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(local, (old_mtime, old_mtime))
        local.chmod(0o444)

        class _OkDownloader:
            def __init__(self, fh, request):
                self._fh = fh

            def next_chunk(self):
                self._fh.write(b"drive content")
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _OkDownloader)
        fs = self._fs()

        result = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(tmp_path), direction="download", ctx=self._ctx(fs)
        )

        assert [f["name"] for f in result["failed"]] == ["big.bin"]
        assert result["downloaded"] == []
        assert local.read_bytes() == b"protected"
        assert _partial_files(tmp_path) == []

    async def test_leftover_partial_is_never_uploaded(self, tmp_path):
        """A temp file only survives a hard kill mid-download. sync_folder must
        not treat it as a local-only file to upload."""
        leftover = tmp_path / (transfer_module._PARTIAL_DOWNLOAD_PREFIX + "0123456789abcdef")
        leftover.write_bytes(b"half a file")
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(tmp_path), direction="bidirectional", ctx=self._ctx(fs)
        )

        assert result["uploaded"] == []
        assert fs.created_files == []


class TestWriteAtomically:
    """#844: _write_atomically, the shared write path behind every download."""

    def test_failure_leaves_existing_file_and_no_temp(self, tmp_path):
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"original")

        def _write(fh):
            fh.write(b"partial")
            raise OSError("disk full")

        with pytest.raises(OSError, match="disk full"):
            transfer_module._write_atomically(dest, _write)
        assert dest.read_bytes() == b"original"
        assert _partial_files(tmp_path) == []

    def test_success_replaces_content_and_stamps_mtime(self, tmp_path):
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"original")
        stamp = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()

        transfer_module._write_atomically(dest, lambda fh: fh.write(b"new"), stamp)

        assert dest.read_bytes() == b"new"
        assert dest.stat().st_mtime == stamp
        assert _partial_files(tmp_path) == []

    def test_existing_file_mode_is_kept(self, tmp_path):
        dest = tmp_path / "f.sh"
        dest.write_bytes(b"old")
        dest.chmod(0o750)

        transfer_module._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.stat().st_mode & 0o777 == 0o750

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0o444 file")
    def test_read_only_destination_is_refused_not_replaced(self, tmp_path):
        """PR #884 QA round 1: a rename only needs directory write permission,
        so a file the user made read-only was silently replaced. The old
        open('wb') raised PermissionError; that refusal is kept."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"protected")
        dest.chmod(0o444)

        with pytest.raises(PermissionError):
            transfer_module._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.read_bytes() == b"protected"
        assert dest.stat().st_mode & 0o777 == 0o444
        assert _partial_files(tmp_path) == []

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0o444 file")
    def test_read_only_symlink_target_is_refused(self, tmp_path):
        real = tmp_path / "real.bin"
        real.write_bytes(b"protected")
        real.chmod(0o444)
        link = tmp_path / "link.bin"
        link.symlink_to(real)

        with pytest.raises(PermissionError):
            transfer_module._write_atomically(link, lambda fh: fh.write(b"new"))

        assert real.read_bytes() == b"protected"

    def test_setuid_setgid_sticky_bits_are_not_carried_over(self, tmp_path):
        """PR #884 QA round 1: an in-place write by a non-root process has the
        kernel clear setuid/setgid, so the replacement mustn't copy them."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"old")
        dest.chmod(0o4755)

        transfer_module._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.stat().st_mode & 0o7777 == 0o755

    def test_new_file_gets_umask_default_mode(self, tmp_path):
        """Same mode a plain open('wb') would give, not mkstemp's 0o600."""
        reference = tmp_path / "reference"
        reference.write_bytes(b"")
        dest = tmp_path / "f.bin"

        transfer_module._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.stat().st_mode & 0o777 == reference.stat().st_mode & 0o777

    def test_symlink_destination_is_written_through(self, tmp_path):
        """_safe_local_dest keeps a user's symlink inside the target directory
        working; the rename must replace the link's target, not the link."""
        real = tmp_path / "elsewhere" / "real.bin"
        real.parent.mkdir()
        real.write_bytes(b"old")
        link = tmp_path / "link.bin"
        link.symlink_to(real)

        transfer_module._write_atomically(link, lambda fh: fh.write(b"new"))

        assert link.is_symlink()
        assert real.read_bytes() == b"new"
        assert _partial_files(real.parent) == []

    def test_partial_name_matcher_is_exact(self):
        assert transfer_module._is_partial_download(".gee-sweet-partial-0123456789abcdef")
        assert not transfer_module._is_partial_download("gee-sweet-partial-0123456789abcdef")
        assert not transfer_module._is_partial_download(".gee-sweet-partial-0123456789abcdef.txt")
        assert not transfer_module._is_partial_download("notes.txt")


class TestDownloadToolsFailedDownloadLeavesNoPartial:
    """#844's sibling sites: download_file and download_folder shared the same
    write-straight-to-destination pattern as sync_folder."""

    def _ctx(self, drive_svc):
        ctx = _make_ctx(drive_service=drive_svc, drive_folder_cache=MagicMock())
        ctx.report_progress = AsyncMock()
        return ctx

    async def test_download_file_failure_keeps_existing_file(self, tmp_path, monkeypatch):
        dest = tmp_path / "big.bin"
        dest.write_bytes(b"previous download")
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.bin",
            "mimeType": "application/octet-stream",
        }
        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FailingDownloader)

        with pytest.raises(ConnectionError):
            await _transfer_tools["download_file"](
                file_id="fbig", local_path=str(dest), ctx=self._ctx(svc)
            )

        assert dest.read_bytes() == b"previous download"
        assert _partial_files(tmp_path) == []

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0o444 file")
    async def test_download_file_refuses_read_only_destination(self, tmp_path, monkeypatch):
        """PR #884 QA round 1, the live repro: a read-only file was replaced by
        the Drive content and the call reported success."""
        dest = tmp_path / "big.bin"
        dest.write_bytes(b"protected")
        dest.chmod(0o444)
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.bin",
            "mimeType": "application/octet-stream",
        }

        class _OkDownloader:
            def __init__(self, fh, request):
                self._fh = fh

            def next_chunk(self):
                self._fh.write(b"drive content")
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _OkDownloader)

        with pytest.raises(PermissionError):
            await _transfer_tools["download_file"](
                file_id="fbig", local_path=str(dest), ctx=self._ctx(svc)
            )

        assert dest.read_bytes() == b"protected"
        assert _partial_files(tmp_path) == []

    async def test_download_folder_failure_leaves_no_file_for_skip_if_exists(
        self, tmp_path, monkeypatch
    ):
        """With skip_if_exists=True (the default), a truncated file left by a
        failed run would be skipped by every later run, so it never healed."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "fbig", "name": "big.bin", "mimeType": "application/octet-stream"},
            ]
        }
        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FailingDownloader)

        result = await _transfer_tools["download_folder"](
            folder_id="root", local_path=str(tmp_path), ctx=self._ctx(svc)
        )

        assert [f["name"] for f in result["failed"]] == ["big.bin"]
        assert not (tmp_path / "big.bin").exists()
        assert _partial_files(tmp_path) == []

    async def test_upload_local_folder_skips_leftover_partial(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / (transfer_module._PARTIAL_DOWNLOAD_PREFIX + "0123456789abcdef")).write_bytes(
            b"half a file"
        )
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "fid",
            "name": "a.txt",
            "webViewLink": "https://example.com",
        }

        result = await _transfer_tools["upload_local_folder"](
            str(tmp_path), "folder1", ctx=self._ctx(drive_svc)
        )

        assert result["uploaded"] == ["a.txt"]
        assert result["failed"] == []


class TestSyncFolderUseChecksum:
    """Issue #274: mtime alone can't distinguish real content drift from a
    non-content-changing mtime bump (or vice versa) — upload_local_file in
    particular doesn't stamp modifiedTime the way sync_folder's own upload does,
    so identical content re-downloads forever under mtime-only comparison.
    use_checksum=True adds a content check ahead of the mtime comparison for
    names present on both sides."""

    _CONTENT = b"hello world"
    _MD5 = "5eb63bbbe01eeed093cb22bb8f5acdc3"  # md5(_CONTENT)
    _OTHER_MD5 = "0949f7eb1f66dad39d488d5d22531166"  # md5 of different content

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _write_local(self, tmp_path, name, content, mtime_str):
        p = tmp_path / name
        p.write_bytes(content)
        dt = datetime.fromisoformat(mtime_str.replace("Z", "+00:00"))
        os.utime(p, (dt.timestamp(), dt.timestamp()))
        return p

    async def test_checksum_match_skips_despite_mtime_far_apart(self, tmp_path):
        # Drive's modifiedTime is far outside the 5s tolerance of the local file's
        # mtime (mirrors upload_local_file's non-stamped modifiedTime), but the
        # content is identical.
        fs = _FakeDriveFS(
            {"root": [_drive_file("a.txt", "fa", mtime="2024-06-01T00:00:00.000Z", md5=self._MD5)]}
        )
        self._write_local(tmp_path, "a.txt", self._CONTENT, "2020-01-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == ["a.txt"]
        assert result["uploaded"] == []
        assert result["downloaded"] == []
        assert result["conflicts"] == []

    async def test_without_use_checksum_same_mtime_gap_is_not_skipped(self, tmp_path):
        # Control: the exact same mismatched-mtime/matching-content setup as above,
        # but use_checksum defaults to False — mtime alone can't tell these apart,
        # so it's treated as a real conflict (drive newer, bidirectional download
        # would apply but let's use upload direction to force a conflict instead).
        fs = _FakeDriveFS(
            {"root": [_drive_file("a.txt", "fa", mtime="2024-06-01T00:00:00.000Z", md5=self._MD5)]}
        )
        self._write_local(tmp_path, "a.txt", self._CONTENT, "2020-01-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == []
        assert result["conflicts"] == ["a.txt"]

    async def test_checksum_mismatch_falls_back_to_mtime_decision(self, tmp_path):
        # Content genuinely differs and mtimes disagree beyond tolerance (so the
        # checksum comparison actually runs — see the gating tests below). A
        # mismatch doesn't force any outcome by itself — it just falls through to
        # the same mtime-based decision used when use_checksum=False: local is 20s
        # newer here, so 'upload' under the default bidirectional direction.
        fs = _FakeDriveFS(
            {"root": [_drive_file("a.txt", "fa", mtime="2024-06-01T00:00:00.000Z", md5=self._MD5)]}
        )
        self._write_local(tmp_path, "a.txt", b"different content", "2024-06-01T00:00:20.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["uploaded"] == ["a.txt"]
        assert result["skipped"] == []
        assert result["conflicts"] == []

    async def test_checksum_verifies_within_tolerance_pair_when_opted_in(
        self, tmp_path, monkeypatch
    ):
        # #716: an explicit use_checksum=True is an accuracy opt-in, so it hashes
        # a within-tolerance pair too instead of trusting mtime alone (#274 PR
        # #472 originally gated this off). Identical content still settles as a
        # skip.
        spy = MagicMock(side_effect=transfer_module._local_md5)
        monkeypatch.setattr(transfer_module, "_local_md5", spy)
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "a.txt",
                        "fa",
                        mtime="2024-06-01T00:00:00.000Z",
                        md5=self._MD5,
                        size=len(self._CONTENT),
                    )
                ]
            }
        )
        self._write_local(tmp_path, "a.txt", self._CONTENT, "2024-06-01T00:00:02.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == ["a.txt"]
        assert result["conflicts"] == []
        spy.assert_called_once()

    async def test_checksum_not_computed_during_dry_run(self, tmp_path, monkeypatch):
        # Same finding #3: dry_run is documented as a cheap, no-transfer preview —
        # it must not read every file's full content to hash it.
        spy = MagicMock(side_effect=transfer_module._local_md5)
        monkeypatch.setattr(transfer_module, "_local_md5", spy)
        fs = _FakeDriveFS(
            {"root": [_drive_file("a.txt", "fa", mtime="2024-06-01T00:00:00.000Z", md5=self._MD5)]}
        )
        self._write_local(tmp_path, "a.txt", self._CONTENT, "2020-01-01T00:00:00.000Z")

        await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            dry_run=True,
            ctx=self._ctx(fs),
        )
        spy.assert_not_called()

    async def test_local_read_failure_reported_as_failed_not_raised(self, tmp_path, monkeypatch):
        # #274 PR #472 review, finding #1: every other per-item operation in
        # _sync_level degrades to a 'failed' entry instead of raising — a file
        # that becomes unreadable between the directory scan and the hash read
        # (deleted, permission-denied, etc.) must behave the same way, not take
        # down the whole sync_folder call.
        def _boom(path):
            raise OSError("permission denied")

        monkeypatch.setattr(transfer_module, "_local_md5", _boom)
        fs = _FakeDriveFS(
            {"root": [_drive_file("a.txt", "fa", mtime="2024-06-01T00:00:00.000Z", md5=self._MD5)]}
        )
        self._write_local(tmp_path, "a.txt", self._CONTENT, "2020-01-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["failed"] == [{"name": "a.txt", "error": "permission denied"}]
        assert result["skipped"] == []
        assert result["uploaded"] == []
        assert result["downloaded"] == []

    async def test_workspace_file_with_no_checksum_falls_back_to_mtime(self, tmp_path):
        # Google Workspace files have no md5Checksum — use_checksum=True must not
        # crash and must behave exactly as use_checksum=False for these.
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "Notes",
                        "fa",
                        mtime="2024-06-01T00:00:00.000Z",
                        mime="application/vnd.google-apps.document",
                    )
                ]
            }
        )
        fs.svc.files.return_value.export.return_value.execute.return_value = b"content"
        self._write_local(tmp_path, "Notes.pdf", b"stale local copy", "2020-01-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["downloaded"] == ["Notes.pdf"]

    async def test_local_md5_matches_known_content_hash(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_bytes(self._CONTENT)
        assert transfer_module._local_md5(p) == self._MD5


class TestSyncFolderChecksumWithinTolerance:
    """Issue #716: #659's byte-size check catches a within-tolerance pair whose
    content diverged *and* changed length, but a same-size edit that also
    preserves mtime still read as "in sync" — use_checksum's hash was gated on
    the mtimes already disagreeing, so even an explicit use_checksum=True never
    verified it. An explicit opt-in now hashes that pair too; a mismatch is a
    `conflict` for every direction (mtimes agree, so recency is unknown — same
    reasoning as the size-mismatch conflict)."""

    _CONTENT = b"hello world"  # 11 bytes
    _MD5 = "5eb63bbbe01eeed093cb22bb8f5acdc3"
    _SAME_SIZE_EDIT = b"HELLO WORLD"  # 11 bytes, different md5

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _write_local(self, tmp_path, content, mtime_str="2024-06-01T00:00:02.000Z"):
        p = tmp_path / "a.txt"
        p.write_bytes(content)
        dt = datetime.fromisoformat(mtime_str.replace("Z", "+00:00"))
        os.utime(p, (dt.timestamp(), dt.timestamp()))
        return p

    def _write_local_named(self, tmp_path, name, content):
        p = tmp_path / name
        p.write_bytes(content)
        dt = datetime.fromisoformat("2024-06-01T00:00:02.000+00:00")
        os.utime(p, (dt.timestamp(), dt.timestamp()))

    def _fs(self, md5=_MD5):
        return _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "a.txt",
                        "fa",
                        mtime="2024-06-01T00:00:00.000Z",
                        md5=md5,
                        size=len(self._CONTENT),
                    )
                ]
            }
        )

    @pytest.mark.parametrize("direction", ["bidirectional", "upload", "download"])
    async def test_same_size_checksum_mismatch_is_conflict_for_every_direction(
        self, tmp_path, direction
    ):
        fs = self._fs()
        self._write_local(tmp_path, self._SAME_SIZE_EDIT)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction=direction,
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["conflicts"] == ["a.txt"]
        assert result["skipped"] == []
        assert result["uploaded"] == []
        assert result["downloaded"] == []
        # Local file untouched — a conflict never auto-transfers.
        assert (tmp_path / "a.txt").read_bytes() == self._SAME_SIZE_EDIT

    async def test_without_use_checksum_same_size_edit_still_skips_without_reading(
        self, tmp_path, monkeypatch
    ):
        # The default (use_checksum=False) keeps the cheap mtime+size behavior:
        # no hash read, and the same-size edit is still the documented gap.
        spy = MagicMock(side_effect=transfer_module._local_md5)
        monkeypatch.setattr(transfer_module, "_local_md5", spy)
        fs = self._fs()
        self._write_local(tmp_path, self._SAME_SIZE_EDIT)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == ["a.txt"]
        assert result["conflicts"] == []
        spy.assert_not_called()

    async def test_size_mismatch_resolves_without_reading(self, tmp_path, monkeypatch):
        # A within-tolerance pair whose sizes already differ is a conflict from
        # the stat alone — the hash block must not pay for a read it can't
        # change the outcome of.
        spy = MagicMock(side_effect=transfer_module._local_md5)
        monkeypatch.setattr(transfer_module, "_local_md5", spy)
        fs = self._fs()
        self._write_local(tmp_path, b"a different length entirely")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["conflicts"] == ["a.txt"]
        spy.assert_not_called()

    async def test_dry_run_does_not_hash_within_tolerance_pair(self, tmp_path, monkeypatch):
        # dry_run stays a cheap preview: the same-size edit previews as a skip
        # (no read) — but says the checksum wasn't verified, since the real run
        # reports a conflict for this same state (PR #841 QA).
        spy = MagicMock(side_effect=transfer_module._local_md5)
        monkeypatch.setattr(transfer_module, "_local_md5", spy)
        fs = self._fs()
        self._write_local(tmp_path, self._SAME_SIZE_EDIT)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            dry_run=True,
            ctx=self._ctx(fs),
        )
        spy.assert_not_called()
        a_txt = [a for a in result["actions"] if a["name"] == "a.txt"]
        assert a_txt[0]["action"] == "skip"
        assert a_txt[0]["reason"] == "in sync (checksum not verified in dry_run)"

    async def test_dry_run_without_use_checksum_reason_is_unannotated(self, tmp_path):
        fs = self._fs()
        self._write_local(tmp_path, self._SAME_SIZE_EDIT)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            dry_run=True,
            ctx=self._ctx(fs),
        )
        assert result["actions"][0]["reason"] == "in sync"

    async def test_local_file_vanishing_before_stat_reported_as_failed(self, tmp_path, monkeypatch):
        # PR #841 QA: the plan loop's stat was unguarded, so a file deleted
        # between the directory scan and the plan raised FileNotFoundError out
        # of the whole call. Simulate the race by having the scan report a name
        # that is gone by the time it's statted.
        ghost = tmp_path / "a.txt"
        real_iterdir = Path.iterdir
        real_is_file = Path.is_file
        monkeypatch.setattr(
            Path,
            "iterdir",
            lambda self: (
                iter([*real_iterdir(self), ghost]) if self == tmp_path else real_iterdir(self)
            ),
        )
        monkeypatch.setattr(
            Path, "is_file", lambda self: True if self == ghost else real_is_file(self)
        )
        fs = self._fs()

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            ctx=self._ctx(fs),
        )
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "a.txt"
        assert result["skipped"] == []
        assert result["downloaded"] == []

    async def test_hashes_run_concurrently_bounded_and_keep_name_order(self, tmp_path, monkeypatch):
        # PR #841 QA: with every both-sides pair now hashed, hashing them one at
        # a time put a full serial read of the folder ahead of any transfer.
        # They now run concurrently, capped at _SYNC_HASH_CONCURRENCY, and each
        # result still lands on its own name.
        lock = threading.Lock()
        state = {"now": 0, "peak": 0}
        real_md5 = transfer_module._local_md5

        def _slow_md5(path):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return real_md5(path)

        monkeypatch.setattr(transfer_module, "_local_md5", _slow_md5)
        names = [f"f{i:02d}.txt" for i in range(20)]
        files = []
        for i, name in enumerate(names):
            # Odd-numbered files carry a same-size edit locally.
            self._write_local_named(
                tmp_path, name, self._SAME_SIZE_EDIT if i % 2 else self._CONTENT
            )
            files.append(
                _drive_file(
                    name,
                    f"id{i}",
                    mtime="2024-06-01T00:00:00.000Z",
                    md5=self._MD5,
                    size=len(self._CONTENT),
                )
            )
        fs = _FakeDriveFS({"root": files})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert 1 < state["peak"] <= transfer_module._SYNC_HASH_CONCURRENCY
        assert result["skipped"] == names[0::2]
        assert result["conflicts"] == names[1::2]

    async def test_within_tolerance_read_failure_reported_as_failed(self, tmp_path, monkeypatch):
        # The newly-reachable hash read degrades to one 'failed' entry like the
        # out-of-tolerance one does (#274 PR #472 review, finding #1).
        def _boom(path):
            raise OSError("permission denied")

        monkeypatch.setattr(transfer_module, "_local_md5", _boom)
        fs = self._fs()
        self._write_local(tmp_path, self._CONTENT)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["failed"] == [{"name": "a.txt", "error": "permission denied"}]
        assert result["skipped"] == []

    async def test_no_drive_md5_falls_back_to_in_sync(self, tmp_path):
        # A file Drive reports no md5Checksum for can't be verified — it settles
        # on the mtime+size decision, as before.
        fs = self._fs(md5=None)
        self._write_local(tmp_path, self._SAME_SIZE_EDIT)

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == ["a.txt"]


class TestSyncFolderSizeDivergence:
    """Issue #659: `sync_folder` reports "in sync" for a name whose content
    differs on the two sides whenever the mtimes happen to agree. The classic
    trigger is a rename-in-place — `mv` preserves mtime, so a name ends up
    pointing at different bytes with an unchanged timestamp and the equal-mtime
    skip hides it forever. use_checksum can't catch it (its hash check is guarded
    on the mtimes already disagreeing). Fixed with a near-free byte-size check:
    Drive's `size` is already in the folder listing, so a within-tolerance mtime
    pair whose sizes disagree is not skipped — it is reported as a `conflict`,
    for every direction (PR #712 QA round 1): the mtimes agree, so recency is
    unknown, and a directional sync already reports `conflict` rather than
    overwrite a target it *can* tell is newer, so this branch (which knows less)
    must be at least as cautious."""

    _CONTENT = b"hello world"  # 11 bytes
    _MD5 = "5eb63bbbe01eeed093cb22bb8f5acdc3"
    _OTHER = b"totally different content, longer"  # 33 bytes — different size

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _write_local(self, tmp_path, name, content, mtime_str):
        p = tmp_path / name
        p.write_bytes(content)
        dt = datetime.fromisoformat(mtime_str.replace("Z", "+00:00"))
        os.utime(p, (dt.timestamp(), dt.timestamp()))
        return p

    def _fs_with_stale_drive_file(self):
        # Drive still holds the 11-byte _CONTENT under 'a.txt' (size + md5 match
        # it); the local 'a.txt' will be overwritten with different, differently
        # sized bytes at the same mtime.
        return _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "a.txt",
                        "fa",
                        mtime="2024-06-01T00:00:00.000Z",
                        md5=self._MD5,
                        size=len(self._CONTENT),
                    )
                ]
            }
        )

    async def test_bidirectional_equal_mtime_size_differs_is_conflict(self, tmp_path):
        fs = self._fs_with_stale_drive_file()
        self._write_local(tmp_path, "a.txt", self._OTHER, "2024-06-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == []
        assert result["conflicts"] == ["a.txt"]
        assert result["uploaded"] == []
        assert result["downloaded"] == []

    async def test_upload_direction_equal_mtime_size_differs_is_conflict(self, tmp_path):
        # direction='upload' must NOT auto-upload here: the local file could be the
        # stale side (a collaborator's newer, differently-sized Drive copy whose
        # mtime landed within tolerance) — same caution the drive-newer +
        # direction='upload' branch already applies (PR #712 QA round 1).
        fs = self._fs_with_stale_drive_file()
        self._write_local(tmp_path, "a.txt", self._OTHER, "2024-06-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=self._ctx(fs),
        )
        assert result["conflicts"] == ["a.txt"]
        assert result["uploaded"] == []
        assert result["skipped"] == []

    async def test_download_direction_equal_mtime_size_differs_is_conflict(self, tmp_path):
        # Symmetric to the upload case: direction='download' must not silently
        # overwrite a freshly-renamed local file (no local revision history to
        # recover from) with Drive's stale bytes.
        fs = self._fs_with_stale_drive_file()
        self._write_local(tmp_path, "a.txt", self._OTHER, "2024-06-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="download",
            ctx=self._ctx(fs),
        )
        assert result["conflicts"] == ["a.txt"]
        assert result["downloaded"] == []
        assert result["skipped"] == []

    async def test_signal_is_independent_of_use_checksum_and_md5(self, tmp_path):
        # Drive reports `size` but no md5Checksum, and use_checksum is left at its
        # default False — the divergence is still caught purely from size.
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "a.txt",
                        "fa",
                        mtime="2024-06-01T00:00:00.000Z",
                        size=len(self._CONTENT),
                    )
                ]
            }
        )
        self._write_local(tmp_path, "a.txt", self._OTHER, "2024-06-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            ctx=self._ctx(fs),
        )
        assert result["conflicts"] == ["a.txt"]
        assert result["skipped"] == []

    async def test_equal_mtime_equal_size_still_reads_as_in_sync(self, tmp_path):
        # Documented remaining gap under the default use_checksum=False: a
        # same-size edit that also preserves mtime is indistinguishable without a
        # hash (opt in with use_checksum=True — see
        # TestSyncFolderChecksumWithinTolerance, #716).
        fs = self._fs_with_stale_drive_file()
        self._write_local(tmp_path, "a.txt", b"11 bytes!!!", "2024-06-01T00:00:02.000Z")  # 11 bytes

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            ctx=self._ctx(fs),
        )
        assert result["skipped"] == ["a.txt"]
        assert result["conflicts"] == []

    async def test_dry_run_flags_size_divergence_without_reading_files(self, tmp_path, monkeypatch):
        # The other half of the bug report: a dry-run preview must give a signal.
        # Size comes from the listing, so this costs no file read — the hash path
        # stays dry_run-gated.
        spy = MagicMock(side_effect=transfer_module._local_md5)
        monkeypatch.setattr(transfer_module, "_local_md5", spy)
        fs = self._fs_with_stale_drive_file()
        self._write_local(tmp_path, "a.txt", self._OTHER, "2024-06-01T00:00:00.000Z")

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            use_checksum=True,
            dry_run=True,
            ctx=self._ctx(fs),
        )
        spy.assert_not_called()
        # dry_run leaves the flat lists empty (#512) — the signal is in `actions`.
        assert result["skipped"] == []
        assert result["conflicts"] == []
        a_txt = [a for a in result["actions"] if a["name"] == "a.txt"]
        assert len(a_txt) == 1
        assert a_txt[0]["action"] == "conflict"
        assert "size" in a_txt[0]["reason"]


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

    async def test_progress_message_falls_back_to_running_bytes_when_sizes_unknown(self, tmp_path):
        """#352: Drive doesn't report a `size` for Workspace files, so an upfront
        byte total isn't knowable when export_format is exporting them — the
        message falls back to a running byte count with no '/total' denominator
        rather than fabricating one. progress/total (the primary metric) stay
        file-count-based either way."""
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
        messages = [c.args[2] for c in ctx.report_progress.await_args_list]
        assert all("bytes so far:" in m for m in messages)
        assert not any(" bytes:" in m for m in messages)
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 2  # total stays file-count-based

    async def test_progress_message_includes_byte_total_when_sizes_known(
        self, tmp_path, monkeypatch
    ):
        """#352: non-Workspace candidates report `size` in the same Drive listing
        call, so an accurate upfront byte total is known — the message shows it
        as 'transferred/total bytes' instead of a denominator-less running count.
        The fake downloader writes each candidate's own listed size (5 and 7,
        not a fixed amount for both) so the numerator is checked against the
        real accumulated total, not just the denominator's presence (#352 QA
        review, finding #4 — the original version's fixed 5-byte-per-file fake
        would have passed even if bytes_completed accumulation regressed)."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "bin1",
                    "name": "a.bin",
                    "mimeType": "application/octet-stream",
                    "size": "5",
                },
                {
                    "id": "bin2",
                    "name": "b.bin",
                    "mimeType": "application/octet-stream",
                    "size": "7",
                },
            ]
        }
        sizes = {"bin1": 5, "bin2": 7}
        svc.files.return_value.get_media.side_effect = lambda fileId, supportsAllDrives: MagicMock(
            fileId=fileId
        )

        class _FakeDownloader:
            def __init__(self, fh, request):
                self._fh = fh
                self._size = sizes[request.fileId]

            def next_chunk(self):
                self._fh.write(b"x" * self._size)
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)
        ctx = self._ctx(svc)

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            ctx=ctx,
        )
        assert result["failed"] == []
        assert result["size_bytes"] == 12
        by_completed = {c.args[0]: c.args[2] for c in ctx.report_progress.await_args_list}
        assert set(by_completed) == {1, 2}
        # First completion (whichever file finishes first) reports its own real
        # size against the fixed total; second (final) completion reports the
        # real accumulated total, not a fixed/guessed value.
        assert by_completed[1] in ("1/2, 5/12 bytes: a.bin: ok", "1/2, 7/12 bytes: b.bin: ok")
        assert by_completed[2].startswith("2/2, 12/12 bytes:")

    async def test_progress_unit_bytes_reports_byte_totals_when_sizes_known(
        self, tmp_path, monkeypatch
    ):
        """#741: progress_unit='bytes' feeds the structured progress/total fields
        from bytes_completed/total_bytes_expected instead of file counts, for a
        client that renders a progress bar from those fields alone rather than
        parsing the message text. The message text itself is unaffected — still
        file-count-first with a supplementary bytes note (#352)."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "bin1",
                    "name": "a.bin",
                    "mimeType": "application/octet-stream",
                    "size": "5",
                },
                {
                    "id": "bin2",
                    "name": "b.bin",
                    "mimeType": "application/octet-stream",
                    "size": "7",
                },
            ]
        }
        sizes = {"bin1": 5, "bin2": 7}
        svc.files.return_value.get_media.side_effect = lambda fileId, supportsAllDrives: MagicMock(
            fileId=fileId
        )

        class _FakeDownloader:
            def __init__(self, fh, request):
                self._fh = fh
                self._size = sizes[request.fileId]

            def next_chunk(self):
                self._fh.write(b"x" * self._size)
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)
        ctx = self._ctx(svc)

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            progress_unit="bytes",
            ctx=ctx,
        )
        assert result["failed"] == []
        calls = [(c.args[0], c.args[1], c.args[2]) for c in ctx.report_progress.await_args_list]
        progress_totals = {(progress, total) for progress, total, _ in calls}
        # Whichever file finishes first reports its own byte size (5 or 7)
        # against the full total (12); the second (final) completion reports
        # the accumulated 12/12 — the message text stays file-count-first
        # regardless of progress_unit.
        assert progress_totals in ({(5, 12), (12, 12)}, {(7, 12), (12, 12)})
        final_message = next(msg for progress, _, msg in calls if progress == 12)
        assert final_message.startswith("2/2, 12/12 bytes:")

    async def test_progress_unit_bytes_falls_back_to_files_when_sizes_unknown(self, tmp_path):
        """#741: progress_unit='bytes' has no reliable total to report against
        when a Workspace export's size isn't known upfront — falls back to
        file-count for the structured fields rather than reporting a byte
        'total' with no real denominator."""
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
            progress_unit="bytes",
            ctx=ctx,
        )
        assert result["failed"] == []
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 2  # falls back to file-count total, not bytes

    async def test_progress_unit_bytes_reaches_full_total_even_when_a_candidate_fails(
        self, tmp_path, monkeypatch
    ):
        """#741 QA review, finding #1: bytes_completed only advanced on success,
        while total_bytes_expected sums every candidate's declared size regardless
        of outcome — a failed candidate's size stayed baked into the denominator
        while never counted toward the numerator, so the final report_progress
        call reported less than 100% even though the whole batch had finished.
        bytes_accounted (distinct from bytes_completed, which stays success-only
        for the message text) now advances by each candidate's own declared size
        on every outcome, matching file-count mode's "final call always reports
        full completion" guarantee."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "bin1",
                    "name": "a.bin",
                    "mimeType": "application/octet-stream",
                    "size": "5",
                },
                {
                    "id": "bin2",
                    "name": "b.bin",
                    "mimeType": "application/octet-stream",
                    "size": "7",
                },
            ]
        }
        svc.files.return_value.get_media.side_effect = lambda fileId, supportsAllDrives: MagicMock(
            fileId=fileId
        )

        class _FakeDownloader:
            def __init__(self, fh, request):
                self._fh = fh
                self._fid = request.fileId

            def next_chunk(self):
                if self._fid == "bin2":
                    raise RuntimeError("simulated download failure")
                self._fh.write(b"x" * 5)
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)
        ctx = self._ctx(svc)

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            progress_unit="bytes",
            ctx=ctx,
        )
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "b.bin"
        # Both candidates' declared sizes (5 + 7 = 12) are accounted for by the
        # final call, matching total_bytes_expected exactly — never stuck below it.
        progress_values = [c.args[0] for c in ctx.report_progress.await_args_list]
        assert 12 in progress_values
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 12  # total stays fixed regardless of outcome

    async def test_duplicate_drive_filenames_do_not_race_or_double_count(self, tmp_path):
        """PR #351 review, live-reproduced: Drive allows two files with the same
        name (distinct IDs) in one folder; the local filesystem doesn't. The old
        sequential loop was accidentally safe here (each existence check ran only
        after the previous file had fully written) — the concurrent rewrite must
        dedupe by destination path instead of letting two writers race onto the
        same file and double-count size_bytes."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "doc1",
                    "name": "Report",
                    "mimeType": "application/vnd.google-apps.document",
                },
                {
                    "id": "doc2",
                    "name": "Report",
                    "mimeType": "application/vnd.google-apps.document",
                },
            ]
        }
        svc.files.return_value.export.return_value.execute.return_value = b"content"

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            ctx=self._ctx(svc),
        )
        assert result["downloaded"] == ["Report.pdf"]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["name"] == "Report"
        assert "duplicate filename" in result["failed"][0]["error"]
        assert result["size_bytes"] == len(b"content")
        assert (tmp_path / "Report.pdf").read_bytes() == b"content"

    async def test_report_progress_failure_does_not_demote_a_successful_download(self, tmp_path):
        """PR #351 review: ctx.report_progress raising (e.g. a dropped session)
        must not overwrite an already-successful download's result."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "doc1",
                    "name": "Doc One",
                    "mimeType": "application/vnd.google-apps.document",
                },
            ]
        }
        svc.files.return_value.export.return_value.execute.return_value = b"content"
        ctx = self._ctx(svc)
        ctx.report_progress.side_effect = RuntimeError("connection dropped")

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            ctx=ctx,
        )
        assert result["downloaded"] == ["Doc One.pdf"]
        assert result["failed"] == []

    @pytest.mark.parametrize(
        ("skip_if_exists", "skipped", "downloaded", "export_calls", "final_bytes"),
        [
            (True, ["Doc One.pdf"], [], 0, b"already here"),
            (False, [], ["Doc One.pdf"], 1, b"new content"),
        ],
        ids=["skip", "redownload"],
    )
    async def test_skip_if_exists_with_existing_destination(
        self, tmp_path, skip_if_exists, skipped, downloaded, export_calls, final_bytes
    ):
        """TC-D109 (v0.8.0 QA run, #227): skip_if_exists was live-SKIPped as
        local-filesystem-dependent and had no unit coverage. With the flag on, an
        existing destination file is left untouched and the candidate never
        reaches export(); with it off, the file is overwritten by a fresh export.
        One parametrized test so the shared mock can't drift between cases (#561)."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "doc1",
                    "name": "Doc One",
                    "mimeType": "application/vnd.google-apps.document",
                },
            ]
        }
        svc.files.return_value.export.return_value.execute.return_value = b"new content"
        dest = tmp_path / "Doc One.pdf"
        dest.write_bytes(b"already here")

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            skip_if_exists=skip_if_exists,
            ctx=self._ctx(svc),
        )
        assert result["skipped"] == skipped
        assert result["downloaded"] == downloaded
        assert result["failed"] == []
        assert svc.files.return_value.export.call_count == export_calls
        assert dest.read_bytes() == final_bytes

    async def test_mime_type_filter_appended_to_drive_query(self, tmp_path):
        """TC-D110 (v0.8.0 QA run, #227): mime_type_filter is delegated entirely to
        Drive's own query string, not filtered client-side — the only thing a unit
        test can verify is that it's appended to `q` correctly."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}

        await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            mime_type_filter="application/pdf",
            ctx=self._ctx(svc),
        )

        svc.files.return_value.list.assert_called_once()
        query = svc.files.return_value.list.call_args.kwargs["q"]
        assert query == ("'root' in parents and trashed=false and mimeType='application/pdf'")

    async def test_mime_type_filter_escapes_embedded_single_quote(self, tmp_path):
        """The filter value is interpolated directly into the query string — an
        embedded single quote must be escaped rather than breaking the query
        syntax."""
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        mime_filter = "weird/type'value"

        await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            mime_type_filter=mime_filter,
            ctx=self._ctx(svc),
        )

        query = svc.files.return_value.list.call_args.kwargs["q"]
        assert query == ("'root' in parents and trashed=false and mimeType='weird/type\\'value'")


class TestDownloadFile:
    """#486: download_file had zero unit test coverage — download_folder (its
    sibling) has TestDownloadFolder above, but the single-file tool itself was
    only ever exercised indirectly, via error-message strings mentioning it by
    name in other tests."""

    def _ctx(self, drive_svc):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = drive_svc
        return ctx

    def _metadata(self, name, mime_type):
        return {"name": name, "mimeType": mime_type}

    def _assert_metadata_call(self, svc, file_id):
        """#551: supportsAllDrives=True is what lets a shared-drive file
        resolve, and `fields` must include both keys download_file reads."""
        svc.files.return_value.get.assert_called_once_with(
            fileId=file_id, fields="name, mimeType", supportsAllDrives=True
        )

    async def test_google_doc_export(self, tmp_path):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "My Doc", "application/vnd.google-apps.document"
        )
        svc.files.return_value.export.return_value.execute.return_value = b"pdf bytes"

        result = await _transfer_tools["download_file"](
            file_id="doc1",
            local_path=str(tmp_path),
            export_format="pdf",
            ctx=self._ctx(svc),
        )

        svc.files.return_value.export.assert_called_once_with(
            fileId="doc1", mimeType="application/pdf"
        )
        self._assert_metadata_call(svc, "doc1")
        dest = tmp_path / "My Doc.pdf"
        assert result == {
            "local_path": str(dest),
            "name": "My Doc",
            "size_bytes": len(b"pdf bytes"),
        }
        assert dest.read_bytes() == b"pdf bytes"

    async def test_google_sheet_export_as_xlsx(self, tmp_path):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "My Sheet", "application/vnd.google-apps.spreadsheet"
        )
        svc.files.return_value.export.return_value.execute.return_value = b"xlsx bytes"

        result = await _transfer_tools["download_file"](
            file_id="sheet1",
            local_path=str(tmp_path),
            export_format="xlsx",
            ctx=self._ctx(svc),
        )

        svc.files.return_value.export.assert_called_once_with(
            fileId="sheet1",
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        dest = tmp_path / "My Sheet.xlsx"
        assert result["local_path"] == str(dest)
        assert dest.read_bytes() == b"xlsx bytes"

    async def test_str_export_content_is_utf8_encoded(self, tmp_path):
        """#551: googleapiclient can hand back a text export (csv/html/txt) as
        str rather than bytes; download_file encodes it as UTF-8 before writing."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "My Sheet", "application/vnd.google-apps.spreadsheet"
        )
        text = "name,city\nZoë,Zürich\n"
        svc.files.return_value.export.return_value.execute.return_value = text

        result = await _transfer_tools["download_file"](
            file_id="sheet1",
            local_path=str(tmp_path),
            export_format="csv",
            ctx=self._ctx(svc),
        )

        svc.files.return_value.export.assert_called_once_with(fileId="sheet1", mimeType="text/csv")
        self._assert_metadata_call(svc, "sheet1")
        dest = tmp_path / "My Sheet.csv"
        expected = text.encode("utf-8")
        assert dest.read_bytes() == expected
        assert result["size_bytes"] == len(expected)

    async def test_explicit_local_path_overrides_drive_filename(self, tmp_path):
        """When local_path names an exact file (not a directory), that name is
        used as-is rather than Drive's own name + a guessed extension — the
        dest.is_dir() branch in download_file is only taken for directories."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "My Slides", "application/vnd.google-apps.presentation"
        )
        svc.files.return_value.export.return_value.execute.return_value = b"pptx bytes"
        dest = tmp_path / "custom_name.pptx"
        dest.write_bytes(b"previous download")

        result = await _transfer_tools["download_file"](
            file_id="slides1",
            local_path=str(dest),
            export_format="pptx",
            ctx=self._ctx(svc),
        )

        svc.files.return_value.export.assert_called_once_with(
            fileId="slides1",
            mimeType="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        assert result["local_path"] == str(dest)
        assert dest.read_bytes() == b"pptx bytes"

    async def test_binary_file_download(self, tmp_path, monkeypatch):
        """Non-Google files skip export() entirely and stream via get_media()/
        MediaIoBaseDownload instead — fake the downloader since it otherwise
        drives a real HTTP range-request loop against request.http."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "photo.png", "image/png"
        )
        content = b"\x89PNG raw bytes"

        class _FakeDownloader:
            def __init__(self, fh, request):
                self._fh = fh

            def next_chunk(self):
                self._fh.write(content)
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)

        result = await _transfer_tools["download_file"](
            file_id="bin1",
            local_path=str(tmp_path),
            ctx=self._ctx(svc),
        )

        svc.files.return_value.export.assert_not_called()
        svc.files.return_value.get_media.assert_called_once_with(
            fileId="bin1", supportsAllDrives=True
        )
        self._assert_metadata_call(svc, "bin1")
        dest = tmp_path / "photo.png"
        assert result == {"local_path": str(dest), "name": "photo.png", "size_bytes": len(content)}
        assert dest.read_bytes() == content

    async def test_nonexistent_file_id_propagates_error(self, tmp_path):
        resp = MagicMock()
        resp.status = 404
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.side_effect = HttpError(
            resp=resp, content=b'{"error": {"message": "File not found: invalidid123xyz"}}'
        )

        with pytest.raises(HttpError):
            await _transfer_tools["download_file"](
                file_id="invalidid123xyz",
                local_path=str(tmp_path),
                ctx=self._ctx(svc),
            )

    async def test_workspace_file_without_export_format_raises_valueerror(self, tmp_path):
        """PR #547 QA round 1: the only place this can ever be verified — the
        matching live case (TC-D105) is a standing SKIP (⚠️ local-filesystem)."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "My Doc", "application/vnd.google-apps.document"
        )

        with pytest.raises(ValueError, match="export_format is required"):
            await _transfer_tools["download_file"](
                file_id="doc1",
                local_path=str(tmp_path),
                ctx=self._ctx(svc),
            )
        svc.files.return_value.export.assert_not_called()

    async def test_invalid_export_format_raises_valueerror(self, tmp_path):
        """PR #547 QA round 1: same untested-and-unreachable-live rationale as
        the missing-export_format case above."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "My Doc", "application/vnd.google-apps.document"
        )

        with pytest.raises(ValueError, match="Unknown export_format 'bogus'"):
            await _transfer_tools["download_file"](
                file_id="doc1",
                local_path=str(tmp_path),
                export_format="bogus",
                ctx=self._ctx(svc),
            )
        svc.files.return_value.export.assert_not_called()

    async def test_trailing_slash_nonexistent_dir_is_created_and_file_saved_inside(
        self, tmp_path, monkeypatch
    ):
        """#690: a local_path ending in a separator whose directory doesn't exist
        yet was writing a plain file literally named after the last segment
        (Path() strips the trailing slash before the .is_dir() check). It must
        instead create the directory and save the Drive file inside it."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "photo.png", "image/png"
        )

        class _FakeDownloader:
            def __init__(self, fh, request):
                self._fh = fh

            def next_chunk(self):
                self._fh.write(b"png bytes")
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)
        new_dir = tmp_path / "new" / "sub"  # neither level exists yet
        result = await _transfer_tools["download_file"](
            file_id="bin1",
            local_path=str(new_dir) + os.sep,  # trailing separator
            ctx=self._ctx(svc),
        )

        assert new_dir.is_dir()
        saved = new_dir / "photo.png"
        assert saved.is_file()
        assert saved.read_bytes() == b"png bytes"
        assert result["local_path"] == str(saved)
        # The bug's signature: NO plain file literally named "sub" alongside.
        assert not (tmp_path / "new" / "sub").is_file()

    async def test_trailing_slash_dir_second_download_does_not_clobber(self, tmp_path, monkeypatch):
        """#690's clobber symptom: two different Drive files downloaded to the
        same trailing-slash local_path must land as two separate files inside the
        directory, not overwrite one file named after the directory."""
        svc = MagicMock()
        target = str(tmp_path / "out") + os.sep

        class _FakeDownloader:
            payload = b""

            def __init__(self, fh, request):
                self._fh = fh

            def next_chunk(self):
                self._fh.write(_FakeDownloader.payload)
                return None, True

        monkeypatch.setattr(transfer_module, "MediaIoBaseDownload", _FakeDownloader)

        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "first.bin", "application/octet-stream"
        )
        _FakeDownloader.payload = b"first"
        await _transfer_tools["download_file"](file_id="a", local_path=target, ctx=self._ctx(svc))

        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "second.bin", "application/octet-stream"
        )
        _FakeDownloader.payload = b"second"
        await _transfer_tools["download_file"](file_id="b", local_path=target, ctx=self._ctx(svc))

        out = tmp_path / "out"
        assert (out / "first.bin").read_bytes() == b"first"
        assert (out / "second.bin").read_bytes() == b"second"
        assert not out.is_file()

    async def test_trailing_slash_over_existing_non_directory_raises(self, tmp_path):
        """If a plain file already sits where the trailing-slash local_path points,
        the directory intent can't be honored — raise rather than silently write
        past it."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "x.bin", "application/octet-stream"
        )
        clash = tmp_path / "clash"
        clash.write_bytes(b"i am a file")

        with pytest.raises(ValueError, match=r"non-directory path component at.*clash"):
            await _transfer_tools["download_file"](
                file_id="bin1",
                local_path=str(clash) + os.sep,
                ctx=self._ctx(svc),
            )
        assert clash.read_bytes() == b"i am a file"  # untouched
        # #724: reject the local collision before spending a Drive metadata call.
        svc.files.return_value.get.assert_not_called()

    async def test_trailing_slash_with_file_in_parent_path_raises_valueerror(self, tmp_path):
        """#724: an intermediate regular file must produce the same friendly
        ValueError surface rather than leaking a pathlib/OSError exception."""
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = self._metadata(
            "x.bin", "application/octet-stream"
        )
        clash = tmp_path / "clash"
        clash.write_bytes(b"i am a file")
        target = clash / "sub"

        with pytest.raises(ValueError, match=r"non-directory path component at.*clash"):
            await _transfer_tools["download_file"](
                file_id="bin1",
                local_path=str(target) + os.sep,
                ctx=self._ctx(svc),
            )

        assert clash.read_bytes() == b"i am a file"
        svc.files.return_value.get.assert_not_called()

    async def test_file_destination_with_file_parent_fails_before_drive_call(self, tmp_path):
        """#836: a regular file in an intermediate parent must not leak
        NotADirectoryError or spend a Drive metadata request."""
        svc = MagicMock()
        clash = tmp_path / "clash"
        clash.write_bytes(b"i am a file")
        target = clash / "sub" / "out.bin"

        with pytest.raises(ValueError, match=r"non-directory path component at.*clash"):
            await _transfer_tools["download_file"](
                file_id="bin1", local_path=str(target), ctx=self._ctx(svc)
            )

        svc.files.return_value.get.assert_not_called()
        assert clash.read_bytes() == b"i am a file"

    async def test_trailing_slash_with_dangling_symlink_names_blocker(self, tmp_path):
        """#836: exists() is false for a dangling symlink, but mkdir sees it."""
        svc = MagicMock()
        blocker = tmp_path / "dangling"
        blocker.symlink_to(tmp_path / "missing-target")

        with pytest.raises(ValueError, match=r"non-directory path component at.*dangling"):
            await _transfer_tools["download_file"](
                file_id="bin1", local_path=str(blocker) + os.sep, ctx=self._ctx(svc)
            )

        svc.files.return_value.get.assert_not_called()


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

    async def test_error_points_to_result_local_path_not_local_path(self, tmp_path, monkeypatch):
        # sync_folder's local_path param already means the sync destination — it
        # can't double as a place to dump the oversized response (#512), so the
        # error must point at the dedicated result_local_path param instead.
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        with pytest.raises(ValueError) as exc_info:
            await _transfer_tools["sync_folder"](
                folder_id="root",
                local_path=str(tmp_path),
                dry_run=True,
                ctx=self._ctx(fs),
            )
        assert "result_local_path" in str(exc_info.value)

    async def test_result_local_path_bypasses_cap_and_writes_to_disk(self, tmp_path, monkeypatch):
        # #512: unlike the sync destination local_path, result_local_path is the
        # offramp for the *response* — passing it must skip the cap entirely and
        # write the full result to disk instead of raising.
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        manifest = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path / "sync"),
            dry_run=True,
            result_local_path=str(out_dir),
            ctx=self._ctx(fs),
        )
        assert manifest["folder_id"] == "root"
        assert manifest["dry_run"] is True
        written = json.loads(Path(manifest["local_path"]).read_text())
        assert written["actions"][0]["name"] == "readme.txt"

    async def test_result_local_path_equal_to_local_path_raises(self, tmp_path):
        # QA finding, PR #518 review: local_path is scanned as sync input on every
        # call — writing the result manifest there would show up as a new
        # local-only file on the very next sync (and get uploaded on a real run).
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        sync_dir = tmp_path / "sync"
        with pytest.raises(ValueError, match="result_local_path"):
            await _transfer_tools["sync_folder"](
                folder_id="root",
                local_path=str(sync_dir),
                dry_run=True,
                result_local_path=str(sync_dir),
                ctx=self._ctx(fs),
            )

    async def test_result_local_path_inside_local_path_raises(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        sync_dir = tmp_path / "sync"
        with pytest.raises(ValueError, match="result_local_path"):
            await _transfer_tools["sync_folder"](
                folder_id="root",
                local_path=str(sync_dir),
                dry_run=True,
                result_local_path=str(sync_dir / "nested" / "out.json"),
                ctx=self._ctx(fs),
            )

    async def test_result_local_path_outside_local_path_succeeds(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_file("readme.txt", "f1")]})
        sync_dir = tmp_path / "sync"
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        manifest = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(sync_dir),
            dry_run=True,
            result_local_path=str(out_dir),
            ctx=self._ctx(fs),
        )
        assert manifest["folder_id"] == "root"


def _tree(root: Path) -> set[str]:
    """Every path under `root`, relative to it — used to prove nothing was
    written anywhere a test didn't expect."""
    return {str(p.relative_to(root)) for p in root.rglob("*")}


_DOC_MIME = "application/vnd.google-apps.document"


class TestDriveNameUnsafeReason:
    """A Drive name is joined onto a local directory only if it's one ordinary
    path component (_unsafe_name_reason / _safe_local_dest)."""

    @pytest.mark.parametrize(
        "name",
        [
            "",
            ".",
            "..",
            "../x",
            "../../escaped-probe.txt",
            "a/b",
            "a/../../b",
            "/etc/passwd",
            "a\\b",
            "..\\..\\x",
            "C:\\x",
            "a\x00b",
        ],
    )
    def test_refuses(self, name):
        assert transfer_module._unsafe_name_reason(name) is not None
        with pytest.raises(ValueError) as exc:
            transfer_module._safe_local_dest(Path("/tmp/base"), name)
        # The reason alone; each caller names the file itself.
        assert str(exc.value) == transfer_module._unsafe_name_reason(name)

    @pytest.mark.parametrize(
        "name",
        ["notes.txt", ".hidden", "...", "..x", "x..", "...pdf", "Meeting 10:30.txt", "ü 日本.md"],
    )
    def test_allows(self, name, tmp_path):
        assert transfer_module._unsafe_name_reason(name) is None
        assert transfer_module._safe_local_dest(tmp_path, name) == tmp_path / name

    def test_uses_given_resolved_base_without_resolving(self, tmp_path, monkeypatch):
        """A caller joining many names passes the resolved base once."""

        def _no_resolve(self, *args, **kwargs):
            raise AssertionError("resolve() called despite resolved_base")

        resolved = tmp_path.resolve()
        monkeypatch.setattr(Path, "resolve", _no_resolve)
        assert transfer_module._safe_local_dest(tmp_path, "x", resolved) == tmp_path / "x"

    def test_symlink_inside_base_is_not_followed(self, tmp_path):
        """A symlink the user placed inside the target keeps working: only the
        base is resolved, not the final component."""
        outside = tmp_path / "outside"
        outside.mkdir()
        base = tmp_path / "base"
        base.mkdir()
        (base / "linked").symlink_to(outside)
        assert transfer_module._safe_local_dest(base, "linked") == base / "linked"


class TestDownloadFileUnsafeName:
    def _ctx(self, drive_svc):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = drive_svc
        return ctx

    def _svc(self, name, mime="text/plain"):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "name": name,
            "mimeType": mime,
        }
        return svc

    async def test_traversal_name_raises_before_any_write(self, tmp_path):
        # The advisory's reproduction: '../../escaped-probe.txt' into <dir>/a/b/.
        target = tmp_path / "a" / "b"
        target.mkdir(parents=True)
        before = _tree(tmp_path)
        svc = self._svc("../../escaped-probe.txt")

        with pytest.raises(ValueError, match="can't be used as a local filename"):
            await _transfer_tools["download_file"](
                file_id="f1", local_path=str(target), ctx=self._ctx(svc)
            )

        assert _tree(tmp_path) == before
        svc.files.return_value.get_media.assert_not_called()
        svc.files.return_value.export.assert_not_called()

    async def test_trailing_separator_dir_not_created_for_refused_name(self, tmp_path):
        target = tmp_path / "new"
        svc = self._svc("..")

        with pytest.raises(ValueError):
            await _transfer_tools["download_file"](
                file_id="f1", local_path=str(target) + "/", ctx=self._ctx(svc)
            )

        assert not target.exists()

    async def test_exported_workspace_name_checked_with_extension(self, tmp_path):
        svc = self._svc("../escaped", mime=_DOC_MIME)

        with pytest.raises(ValueError):
            await _transfer_tools["download_file"](
                file_id="d1", local_path=str(tmp_path), export_format="pdf", ctx=self._ctx(svc)
            )

        assert _tree(tmp_path) == set()
        svc.files.return_value.export.assert_not_called()

    async def test_explicit_file_path_ignores_drive_name(self, tmp_path):
        """With an explicit file destination the Drive name is never used as a
        path, so an odd name doesn't block the download."""
        svc = self._svc("../../escaped", mime=_DOC_MIME)
        svc.files.return_value.export.return_value.execute.return_value = b"pdf"
        dest = tmp_path / "chosen.pdf"

        result = await _transfer_tools["download_file"](
            file_id="d1", local_path=str(dest), export_format="pdf", ctx=self._ctx(svc)
        )

        assert result["local_path"] == str(dest)
        assert _tree(tmp_path) == {"chosen.pdf"}


class TestDownloadFolderUnsafeName:
    def _ctx(self, drive_svc):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = drive_svc
        ctx.report_progress = AsyncMock()
        return ctx

    async def test_refused_name_is_failed_entry_and_others_download(self, tmp_path):
        target = tmp_path / "a" / "b"
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "bad", "name": "../../escaped-probe", "mimeType": _DOC_MIME},
                {"id": "ok", "name": "fine", "mimeType": _DOC_MIME},
            ]
        }
        svc.files.return_value.export.return_value.execute.return_value = b"pdf"

        result = await _transfer_tools["download_folder"](
            folder_id="root", local_path=str(target), export_format="pdf", ctx=self._ctx(svc)
        )

        assert result["downloaded"] == ["fine.pdf"]
        assert result["failed"] == [
            {
                "name": "../../escaped-probe",
                # Quotes the Drive name the user sees, not the '.pdf' local name.
                "error": (
                    "'../../escaped-probe' can't be used as a local filename: "
                    "name contains a path separator"
                ),
            }
        ]
        assert _tree(tmp_path) == {"a", "a/b", "a/b/fine.pdf"}
        svc.files.return_value.export.assert_called_once_with(
            fileId="ok", mimeType="application/pdf"
        )


class TestSyncFolderUnsafeName:
    """sync_folder never joins a name that isn't one ordinary path component:
    it's an 'unsafe_name' plan action (a 'failed' entry on a real run), except
    a one-sided name this direction wouldn't touch, which stays a plain skip."""

    def _ctx(self, fs: _FakeDriveFS):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.drive_service = fs.svc
        ctx.request_context.lifespan_context.drive_folder_cache = MagicMock()
        ctx.report_progress = AsyncMock()
        return ctx

    def _fs(self, *entries) -> _FakeDriveFS:
        fs = _FakeDriveFS({"root": list(entries)})
        fs.svc.files.return_value.export.return_value.execute.return_value = b"pdf"
        return fs

    @pytest.mark.parametrize("direction", ["download", "bidirectional"])
    async def test_download_direction_refuses_and_writes_nothing_outside(self, tmp_path, direction):
        local = tmp_path / "a" / "b"
        local.mkdir(parents=True)
        fs = self._fs(
            _drive_file("../../escaped", "bad", mime=_DOC_MIME),
            _drive_file("fine", "ok", mime=_DOC_MIME),
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(local),
            direction=direction,
            export_format="pdf",
            ctx=self._ctx(fs),
        )

        assert result["downloaded"] == ["fine.pdf"]
        assert [f["name"] for f in result["failed"]] == ["../../escaped.pdf"]
        assert "path separator" in result["failed"][0]["error"]
        assert _tree(tmp_path) == {"a", "a/b", "a/b/fine.pdf"}

    async def test_duplicate_unsafe_drive_names_are_counted(self, tmp_path):
        """Two Drive files under one unsafe name are both accounted for, the
        way a collision is, rather than the second vanishing."""
        fs = self._fs(
            _drive_file("../../escaped-probe.txt", "bad1"),
            _drive_file("../../escaped-probe.txt", "bad2"),
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="download",
            ctx=self._ctx(fs),
        )

        assert result["failed"] == [
            {
                "name": "../../escaped-probe.txt",
                "error": (
                    "name contains a path separator (2 Drive entries have this name); not synced"
                ),
            }
        ]
        assert _tree(tmp_path) == set()

    async def test_duplicate_unsafe_drive_folders_are_counted(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_folder("..", "d1"), _drive_folder("..", "d2")]})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="download",
            recursive=True,
            ctx=self._ctx(fs),
        )

        assert result["failed"] == [
            {
                "name": "../",
                "error": (
                    "name is the special path segment '..' "
                    "(2 Drive entries have this name); not synced"
                ),
            }
        ]
        assert fs.list_calls == ["root"]

    async def test_dry_run_reports_unsafe_name_action(self, tmp_path):
        fs = self._fs(_drive_file("../escaped", "bad", mime=_DOC_MIME))

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            export_format="pdf",
            dry_run=True,
            ctx=self._ctx(fs),
        )

        assert result["failed"] == []
        assert [(a["name"], a["action"]) for a in result["actions"]] == [
            ("../escaped.pdf", "unsafe_name")
        ]

    async def test_upload_direction_drive_only_refused_name_is_plain_skip(self, tmp_path):
        (tmp_path / "local.txt").write_text("x")
        fs = self._fs(_drive_file("../escaped", "bad", mime=_DOC_MIME))

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            export_format="pdf",
            ctx=self._ctx(fs),
        )

        assert result["failed"] == []
        assert result["skipped"] == ["../escaped.pdf"]
        assert result["uploaded"] == ["local.txt"]
        assert [b["name"] for b in fs.created_files] == ["local.txt"]
        assert _tree(tmp_path) == {"local.txt"}

    @pytest.mark.skipif(os.name == "nt", reason="'\\' is a separator on Windows")
    async def test_upload_direction_refuses_local_backslash_name(self, tmp_path):
        """A POSIX file named 'a\\b' would upload under a name the Drive side
        then refuses, so it would never match again; it's refused up front."""
        (tmp_path / "a\\b").write_text("x")
        fs = self._fs()

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            ctx=self._ctx(fs),
        )

        assert result["uploaded"] == []
        assert [f["name"] for f in result["failed"]] == ["a\\b"]
        assert fs.created_files == []

    @pytest.mark.skipif(os.name == "nt", reason="'\\' is a separator on Windows")
    async def test_download_direction_local_only_backslash_name_is_plain_skip(self, tmp_path):
        (tmp_path / "a\\b").write_text("x")
        fs = self._fs()

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="download",
            ctx=self._ctx(fs),
        )

        assert result["failed"] == []
        assert result["skipped"] == ["a\\b"]

    async def test_converted_md_source_property_is_checked(self, tmp_path):
        """A converted Doc's local name comes from its Drive properties, which
        whoever shared it can set; that name is checked, not the display name."""
        local = tmp_path / "a" / "b"
        local.mkdir(parents=True)
        fs = self._fs(
            _drive_file(
                "innocent.md",
                "doc",
                mime=_DOC_MIME,
                properties={transfer_module._CONVERT_MARKDOWN_SOURCE_PROP: "../../evil.md"},
            )
        )

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(local),
            dry_run=True,
            ctx=self._ctx(fs),
        )

        assert [(a["name"], a["action"]) for a in result["actions"]] == [
            ("../../evil.md", "unsafe_name")
        ]
        assert fs.revision_list_calls == []

    @pytest.mark.parametrize("direction", ["download", "bidirectional"])
    async def test_recursive_refuses_dotdot_subfolder(self, tmp_path, direction):
        """A Drive folder named '..' would otherwise be downloaded into (and,
        bidirectionally, uploaded from) the parent of local_path."""
        parent = tmp_path / "parent"
        local = parent / "sync"
        local.mkdir(parents=True)
        (parent / "secret.txt").write_text("not for Drive")
        fs = _FakeDriveFS(
            {
                "root": [_drive_folder("..", "dotdot")],
                "dotdot": [_drive_file("payload", "p", mime=_DOC_MIME)],
            }
        )
        fs.svc.files.return_value.export.return_value.execute.return_value = b"pdf"

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(local),
            direction=direction,
            export_format="pdf",
            recursive=True,
            ctx=self._ctx(fs),
        )

        assert result["failed"] == [
            {"name": "../", "error": "name is the special path segment '..'; not synced"}
        ]
        assert "dotdot" not in fs.list_calls
        assert fs.created_files == []
        assert _tree(tmp_path) == {"parent", "parent/sync", "parent/secret.txt"}

    async def test_recursive_dry_run_reports_unsafe_subfolder(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_folder("a/..", "bad")]})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            recursive=True,
            dry_run=True,
            ctx=self._ctx(fs),
        )

        assert result["failed"] == []
        assert [(a["name"], a["action"]) for a in result["actions"]] == [("a/../", "unsafe_name")]
        assert fs.list_calls == ["root"]

    async def test_recursive_upload_direction_drive_only_unsafe_folder_skipped(self, tmp_path):
        fs = _FakeDriveFS({"root": [_drive_folder("..", "dotdot")]})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            recursive=True,
            ctx=self._ctx(fs),
        )

        assert result["failed"] == []
        assert result["folders_skipped"] == ["../"]
        assert fs.list_calls == ["root"]


@pytest.mark.parametrize("reason", ["storageQuotaExceededLater", "otherstorageQuotaExceeded"])
def test_quota_error_rejects_other_reason_names(reason):
    from mcp_gee_sweet.tools.drive.transfer import _is_quota_error

    response = MagicMock()
    response.status = 403
    error = HttpError(
        resp=response, content=json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    )
    assert not _is_quota_error(error)
