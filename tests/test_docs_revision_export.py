"""Tests for export_revision on Google Docs and list_revisions (#959): the
DOCX -> temporary Doc -> Markdown path in docs/markdown_export.py, its
diff-stabilizing link and image rewrites, the temporary Doc's cleanup, and
export_revision's Sheets/Docs dispatch in drive/transfer.py."""

import threading
from functools import partial
from unittest.mock import MagicMock, patch

import anyio
import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.docs import markdown_export
from mcp_gee_sweet.tools.drive import _SA_QUOTA_ERROR
from mcp_gee_sweet.tools.drive import transfer as transfer_module

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_tools: dict = {}


def _tool(annotations=None):
    def decorator(func):
        _tools[func.__name__] = func
        return func

    return decorator


transfer_module.register(_tool)


def _resp(status):
    resp = MagicMock()
    resp.status = status
    return resp


class _FakeHttp:
    """Stands in for thread_http(service): serves url -> (status, bytes)."""

    def __init__(self, routes: dict[str, tuple[int, bytes]]):
        self.routes = routes
        self.requested: list[str] = []

    def request(self, url):
        self.requested.append(url)
        status, body = self.routes.get(url, (404, b"not found"))
        return _resp(status), body


def _para(text, link=None, heading_id=None):
    style = {"link": link} if link else {}
    para: dict = {"elements": [{"textRun": {"content": text, "textStyle": style}}]}
    if heading_id:
        para["paragraphStyle"] = {"namedStyleType": "HEADING_2", "headingId": heading_id}
    return {"paragraph": para}


def _image_para(object_id):
    return {"paragraph": {"elements": [{"inlineObjectElement": {"inlineObjectId": object_id}}]}}


def _inline_object(uri):
    return {
        "inlineObjectProperties": {
            "embeddedObject": {"imageProperties": {"contentUri": uri}, "size": {}}
        }
    }


def _document(content, inline_objects=None, doc_id="tmp1"):
    return {
        "documentId": doc_id,
        "body": {"content": content},
        "inlineObjects": inline_objects or {},
    }


def _services(document, can_delete=True):
    drive = MagicMock()
    drive.revisions.return_value.get.return_value.execute.return_value = {
        "exportLinks": {_DOCX: "https://export/docx"},
        "modifiedTime": "2026-10-11T00:00:00Z",
    }
    drive.files.return_value.create.return_value.execute.return_value = {
        "id": "tmp1",
        "capabilities": {"canDelete": can_delete},
    }
    docs = MagicMock()
    docs.documents.return_value.get.return_value.execute.return_value = document
    return drive, docs


def _ctx(drive, docs, folder_id: str | None = "folder1"):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.drive_service, lc.docs_service, lc.folder_id = drive, docs, folder_id
    return ctx


@pytest.fixture
def fake_http():
    http = _FakeHttp({"https://export/docx": (200, b"docx-bytes")})
    with (
        patch.object(transfer_module, "thread_http", return_value=http),
        patch.object(markdown_export, "thread_http", return_value=http),
    ):
        yield http


async def _export(ctx, **kwargs):
    return await _tools["export_revision"](file_id="doc1", revision_id="7", ctx=ctx, **kwargs)


class TestDocRevisionExport:
    async def test_returns_markdown_via_temp_doc_and_deletes_it(self, fake_http):
        drive, docs = _services(_document([_para("Hello world\n")]))
        result = await _export(_ctx(drive, docs))

        assert result == {
            "revisionId": "7",
            "modifiedTime": "2026-10-11T00:00:00Z",
            "markdown": "Hello world\n",
            "images": [],
        }
        create = drive.files.return_value.create.call_args.kwargs
        assert create["body"]["mimeType"] == "application/vnd.google-apps.document"
        assert create["body"]["parents"] == ["folder1"]
        assert create["media_body"].mimetype() == _DOCX
        assert create["media_body"].getbytes(0, 100) == b"docx-bytes"
        docs.documents.return_value.get.assert_called_with(documentId="tmp1")
        drive.files.return_value.delete.assert_called_once_with(
            fileId="tmp1", supportsAllDrives=True
        )
        assert fake_http.requested[0] == "https://export/docx"

    async def test_no_default_folder_omits_parents(self, fake_http):
        drive, docs = _services(_document([_para("x\n")]))
        await _export(_ctx(drive, docs, folder_id=None))
        assert "parents" not in drive.files.return_value.create.call_args.kwargs["body"]

    async def test_trashes_when_identity_cannot_delete(self, fake_http):
        # A Content manager on a Shared Drive can trash but not delete (#876).
        drive, docs = _services(_document([_para("x\n")]), can_delete=False)
        await _export(_ctx(drive, docs))
        drive.files.return_value.delete.assert_not_called()
        drive.files.return_value.update.assert_called_once_with(
            fileId="tmp1", body={"trashed": True}, fields="id", supportsAllDrives=True
        )

    async def test_failed_cleanup_is_a_warning_naming_the_doc(self, fake_http):
        drive, docs = _services(_document([_para("x\n")]))
        drive.files.return_value.delete.return_value.execute.side_effect = RuntimeError("boom")
        result = await _export(_ctx(drive, docs))
        assert result["markdown"] == "x\n"
        assert "tmp1" in result["warning"] and "boom" in result["warning"]

    async def test_temp_doc_deleted_when_read_fails(self, fake_http):
        drive, docs = _services(_document([]))
        docs.documents.return_value.get.return_value.execute.side_effect = RuntimeError("read")
        with pytest.raises(RuntimeError, match="read"):
            await _export(_ctx(drive, docs))
        drive.files.return_value.delete.assert_called_once()

    async def test_quota_error_on_import_uses_shared_text(self, fake_http):
        drive, docs = _services(_document([]))
        err = HttpError(_resp(403), b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}')
        drive.files.return_value.create.return_value.execute.side_effect = err
        with pytest.raises(ValueError) as exc_info:
            await _export(_ctx(drive, docs))
        assert _SA_QUOTA_ERROR in str(exc_info.value)
        drive.files.return_value.delete.assert_not_called()

    async def test_export_http_error_raises_before_import(self, fake_http):
        fake_http.routes["https://export/docx"] = (429, b"<html>rate limited</html>")
        drive, docs = _services(_document([]))
        with pytest.raises(ValueError, match=r"HTTP 429.*retry"):
            await _export(_ctx(drive, docs))
        drive.files.return_value.create.assert_not_called()

    async def test_temp_doc_deleted_when_cancelled_mid_read(self, fake_http):
        # mcp cancels a request through an anyio cancel scope; the cleanup in
        # the finally still runs.
        drive, docs = _services(_document([]))
        started, release = threading.Event(), threading.Event()

        def blocking_get(**kwargs):
            started.set()
            release.wait(5)
            return _document([])

        docs.documents.return_value.get.return_value.execute.side_effect = blocking_get
        async with anyio.create_task_group() as tg:
            tg.start_soon(partial(_export, _ctx(drive, docs)))
            await anyio.to_thread.run_sync(started.wait, 5)
            tg.cancel_scope.cancel()
            release.set()
        drive.files.return_value.delete.assert_called_once_with(
            fileId="tmp1", supportsAllDrives=True
        )

    async def test_temp_doc_deleted_when_cancelled_mid_create(self, fake_http):
        # Cancelled while Drive is creating the Doc, the create still finishes
        # (shielded), so its ID is recorded and the Doc removed, not orphaned.
        drive, docs = _services(_document([]))
        started, release = threading.Event(), threading.Event()

        def blocking_create(**kwargs):
            started.set()
            release.wait(5)
            return {"id": "tmp1", "capabilities": {"canDelete": True}}

        drive.files.return_value.create.return_value.execute.side_effect = blocking_create
        async with anyio.create_task_group() as tg:
            tg.start_soon(partial(_export, _ctx(drive, docs)))
            await anyio.to_thread.run_sync(started.wait, 5)
            tg.cancel_scope.cancel()
            release.set()
        drive.files.return_value.delete.assert_called_once_with(
            fileId="tmp1", supportsAllDrives=True
        )
        docs.documents.return_value.get.assert_not_called()

    async def test_local_path_writes_raw_markdown(self, fake_http, tmp_path):
        drive, docs = _services(_document([_para("Saved\n")]))
        result = await _export(_ctx(drive, docs), local_path=str(tmp_path))
        dest = tmp_path / "doc1-r7.md"
        assert dest.read_text() == "Saved\n"
        assert result["local_path"] == str(dest)
        assert result["revisionId"] == "7"
        assert "markdown" not in result

    async def test_oversized_response_raises_without_local_path(self, fake_http, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        drive, docs = _services(_document([_para("x" * 100 + "\n")]))
        with pytest.raises(ValueError, match="safety cap"):
            await _export(_ctx(drive, docs))

    @pytest.mark.parametrize("kwargs", [{"range": "A1:B2"}, {"sheet": "Sheet1"}])
    async def test_sheets_only_args_rejected_for_doc(self, fake_http, kwargs):
        drive, docs = _services(_document([]))
        with pytest.raises(ValueError, match="apply only to Google Sheets"):
            await _export(_ctx(drive, docs), **kwargs)
        drive.files.return_value.create.assert_not_called()


class TestInternalLinks:
    async def _markdown(self, content, fake_http):
        drive, docs = _services(_document(content))
        return (await _export(_ctx(drive, docs)))["markdown"]

    async def test_heading_links_become_deduplicated_slugs(self, fake_http):
        md = await self._markdown(
            [
                _para("Setup\n", heading_id="h.a"),
                _para("Setup\n", heading_id="h.b"),
                _para("first", link={"headingId": "h.a"}),
                _para("second", link={"heading": {"id": "h.b", "tabId": "t.0"}}),
            ],
            fake_http,
        )
        assert "[first](#setup)" in md
        assert "[second](#setup-1)" in md
        assert "docs.google.com" not in md

    async def test_bookmark_links_numbered_by_first_reference(self, fake_http):
        md = await self._markdown(
            [
                _para("one", link={"bookmarkId": "id.x"}),
                _para("two", link={"bookmark": {"id": "id.y"}}),
                _para("again", link={"bookmarkId": "id.x"}),
            ],
            fake_http,
        )
        assert "[one](#bookmark-1)" in md
        assert "[two](#bookmark-2)" in md
        assert "[again](#bookmark-1)" in md

    async def test_link_to_missing_heading_dropped(self, fake_http):
        md = await self._markdown([_para("orphan", link={"headingId": "h.gone"})], fake_http)
        assert md.strip() == "orphan"

    async def test_heading_inside_table_cell_counts(self, fake_http):
        table = {
            "table": {
                "tableRows": [
                    {"tableCells": [{"content": [_para("Cell Head\n", heading_id="h.t")]}]}
                ]
            }
        }
        md = await self._markdown([table, _para("go", link={"headingId": "h.t"})], fake_http)
        assert "[go](#cell-head)" in md

    async def test_url_links_untouched(self, fake_http):
        md = await self._markdown([_para("ext", link={"url": "https://example.com"})], fake_http)
        assert "[ext](https://example.com)" in md


class TestImages:
    async def test_image_src_is_content_hash_stable_across_temp_uris(self, fake_http):
        fake_http.routes["https://img/a"] = (200, b"png-bytes")
        fake_http.routes["https://img/b"] = (200, b"png-bytes")
        results = []
        for uri in ("https://img/a", "https://img/b"):
            drive, docs = _services(_document([_image_para("o1")], {"o1": _inline_object(uri)}))
            results.append(await _export(_ctx(drive, docs)))
        assert results[0]["markdown"] == results[1]["markdown"]
        assert "](image:sha256-" in results[0]["markdown"]
        assert results[0]["images"][0]["url"] == "https://img/a"
        assert results[0]["images"][0]["src"] == results[1]["images"][0]["src"]

    async def test_changed_image_changes_src(self, fake_http):
        fake_http.routes["https://img/a"] = (200, b"one")
        fake_http.routes["https://img/b"] = (200, b"two")
        drive, docs = _services(
            _document(
                [_image_para("o1"), _image_para("o2")],
                {"o1": _inline_object("https://img/a"), "o2": _inline_object("https://img/b")},
            )
        )
        result = await _export(_ctx(drive, docs))
        assert len({i["src"] for i in result["images"]}) == 2

    async def test_duplicate_image_listed_once(self, fake_http):
        fake_http.routes["https://img/a"] = (200, b"same")
        fake_http.routes["https://img/b"] = (200, b"same")
        drive, docs = _services(
            _document(
                [_image_para("o1"), _image_para("o2")],
                {"o1": _inline_object("https://img/a"), "o2": _inline_object("https://img/b")},
            )
        )
        result = await _export(_ctx(drive, docs))
        assert len(result["images"]) == 1

    async def test_unfetchable_image_marked_unavailable(self, fake_http):
        drive, docs = _services(
            _document([_image_para("o1")], {"o1": _inline_object("https://img/missing")})
        )
        result = await _export(_ctx(drive, docs))
        assert "](image:unavailable)" in result["markdown"]
        assert result["images"] == []


class TestExportRevisionDispatch:
    async def test_sheet_revision_unchanged(self, fake_http):
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        wb.active.title = "Sheet1"
        wb.active.append(["a", "b"])
        buf = io.BytesIO()
        wb.save(buf)
        fake_http.routes["https://export/xlsx"] = (200, buf.getvalue())
        drive = MagicMock()
        drive.revisions.return_value.get.return_value.execute.return_value = {
            "exportLinks": {_XLSX: "https://export/xlsx"},
            "modifiedTime": "T",
        }
        result = await _export(_ctx(drive, MagicMock()))
        assert result == {
            "revisionId": "7",
            "modifiedTime": "T",
            "sheet": "Sheet1",
            "range": None,
            "values": [["a", "b"]],
        }
        drive.files.assert_not_called()

    async def test_sheet_rejects_local_path(self, fake_http, tmp_path):
        drive = MagicMock()
        drive.revisions.return_value.get.return_value.execute.return_value = {
            "exportLinks": {_XLSX: "https://export/xlsx"}
        }
        with pytest.raises(ValueError, match="local_path applies only to Google Docs"):
            await _export(_ctx(drive, MagicMock()), local_path=str(tmp_path))

    async def test_sheet_export_http_error_is_clear(self, fake_http):
        # Before #959 the error page went straight to openpyxl (BadZipFile).
        fake_http.routes["https://export/xlsx"] = (500, b"<html>")
        drive = MagicMock()
        drive.revisions.return_value.get.return_value.execute.return_value = {
            "exportLinks": {_XLSX: "https://export/xlsx"}
        }
        with pytest.raises(ValueError, match="HTTP 500 exporting revision 7"):
            await _export(_ctx(drive, MagicMock()))

    async def test_other_file_type_rejected(self, fake_http):
        drive = MagicMock()
        drive.revisions.return_value.get.return_value.execute.return_value = {"exportLinks": {}}
        with pytest.raises(ValueError, match="Google Sheets and Google Docs files only"):
            await _export(_ctx(drive, MagicMock()))

    async def test_missing_revision_explains_merging(self, fake_http):
        drive = MagicMock()
        drive.revisions.return_value.get.return_value.execute.side_effect = HttpError(
            _resp(404), b"Revision not found"
        )
        with pytest.raises(ValueError, match="call list_revisions again"):
            await _export(_ctx(drive, MagicMock()))


class TestListRevisions:
    async def test_follows_every_page(self):
        # revisions.list returns at most 200 per page by default; the tool used
        # to read only the first page.
        drive = MagicMock()
        pages = [
            {"revisions": [{"id": "1"}], "nextPageToken": "p2"},
            {"revisions": [{"id": "2", "keepForever": True}]},
        ]
        drive.revisions.return_value.list.return_value.execute.side_effect = pages
        result = await _tools["list_revisions"](file_id="f", ctx=_ctx(drive, MagicMock()))
        assert [r["revisionId"] for r in result] == ["1", "2"]
        assert result[1]["keepForever"] is True
        tokens = [c.kwargs["pageToken"] for c in drive.revisions.return_value.list.call_args_list]
        assert tokens == [None, "p2"]
