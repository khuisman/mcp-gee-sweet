"""Plan rule D3 (#1173): a .md handed to Drive's Markdown import (EP-5 to EP-7) is sent
without its YAML front matter, which Drive would show as a rule and a heading. Every
other upload sends the file's bytes as they are."""

import os
from unittest.mock import MagicMock

import pytest

from mcp_gee_sweet.tools.drive import transfer as transfer_module
from mcp_gee_sweet.tools.drive.transfer import _upload_local_file

from . import test_transfer
from .test_transfer import _FakeDriveFS, _make_ctx, _transfer_tools

# Imported through the module, so pytest doesn't collect its tests here a second time.
_resolve_helpers = test_transfer.TestSyncFolderResolve

FRONT_MATTER = b"---\ntitle: Front matter\nauthor: QA\n---\n\n# Body heading\n\nBody text.\n"
BODY = b"# Body heading\n\nBody text.\n"


def _media_bytes(media) -> bytes:
    return media.getbytes(0, media.size())


def _drive_svc():
    drive_svc = MagicMock()
    drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
    drive_svc.files.return_value.create.return_value.execute.return_value = {
        "id": "fid1",
        "name": "notes.md",
        "webViewLink": "https://example.com",
    }
    return drive_svc


async def _uploaded(tmp_path, content: bytes, name="notes.md", convert=True):
    local_file = tmp_path / name
    local_file.write_bytes(content)
    drive_svc = _drive_svc()
    result = await _upload_local_file(
        drive_svc, str(local_file), "folder1", skip_if_exists=False, convert=convert
    )
    assert "error" not in result
    return drive_svc.files.return_value.create.call_args.kwargs["media_body"]


class TestUploadLocalFile:
    async def test_convert_strips_front_matter(self, tmp_path):
        media = await _uploaded(tmp_path, FRONT_MATTER)
        assert _media_bytes(media) == BODY
        assert media.mimetype() == "text/markdown"
        assert media.resumable()

    @pytest.mark.parametrize(
        "content",
        [
            b"# Body heading\n\nBody text.\n",
            b"---\nSome text\n---\n",
            # Not UTF-8: uploaded unchanged rather than guessed at.
            b"---\ntitle: caf\xe9\n---\nBody\n",
        ],
        ids=["no-front-matter", "rule-and-setext-heading", "not-utf8"],
    )
    async def test_convert_without_front_matter_sends_the_file(self, tmp_path, content):
        media = await _uploaded(tmp_path, content)
        assert isinstance(media, transfer_module.MediaFileUpload)
        assert _media_bytes(media) == content

    async def test_byte_order_mark_is_dropped_with_front_matter(self, tmp_path):
        media = await _uploaded(tmp_path, b"\xef\xbb\xbf" + FRONT_MATTER)
        assert _media_bytes(media) == BODY

    async def test_unconverted_md_keeps_front_matter(self, tmp_path):
        media = await _uploaded(tmp_path, FRONT_MATTER, convert=False)
        assert _media_bytes(media) == FRONT_MATTER

    async def test_other_converted_types_keep_their_bytes(self, tmp_path):
        content = b"---\ntitle: x\n---\n<p>Body</p>\n"
        media = await _uploaded(tmp_path, content, name="page.html")
        assert _media_bytes(media) == content


async def test_upload_local_folder_convert_strips_front_matter(tmp_path):
    (tmp_path / "notes.md").write_bytes(FRONT_MATTER)
    drive_svc = _drive_svc()
    ctx = _make_ctx(drive_service=drive_svc, drive_folder_cache=MagicMock())

    result = await _transfer_tools["upload_local_folder"](
        str(tmp_path), "folder1", convert=True, ctx=ctx
    )

    assert result["uploaded"] == ["notes.md"]
    media = drive_svc.files.return_value.create.call_args.kwargs["media_body"]
    assert _media_bytes(media) == BODY


class TestSyncFolder:
    async def test_new_doc_strips_front_matter(self, tmp_path):
        (tmp_path / "notes.md").write_bytes(FRONT_MATTER)
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            direction="upload",
            convert_markdown=True,
            ctx=_resolve_helpers()._ctx(fs),
        )

        assert result["uploaded"] == ["notes.md"]
        media = fs.svc.files.return_value.create.call_args_list[-1].kwargs["media_body"]
        assert _media_bytes(media) == BODY

    async def test_reupload_strips_front_matter(self, tmp_path):
        resolve = _resolve_helpers()
        fs = resolve._drive_edited(tmp_path, local_offset=600)
        local = tmp_path / "notes.md"
        st = local.stat()
        local.write_bytes(FRONT_MATTER)
        os.utime(local, (st.st_atime, st.st_mtime))

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(tmp_path),
            resolve={"notes.md": "keep_local"},
            ctx=resolve._ctx(fs),
        )

        assert result["uploaded"] == ["notes.md"]
        (update,) = fs.updated_files
        assert _media_bytes(update["media_body"]) == BODY
