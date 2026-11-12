"""tests/drive/test_transfer_query_escaping.py

Issue #1084: four Drive `files().list()` queries in `tools/drive/transfer.py`
interpolated a caller-supplied folder ID without escaping, so an ID containing a
single quote closed the quoted value and OR'd in arbitrary terms —
`x' in parents or trashed=true or 'y` becomes a filter that can pull in trashed
files and children of other folders, and any ID with a quote gets an opaque
Drive 400. PR #1083 (#1054) added `_escape_drive_query_value` and applied it in
`files.py`; these tests pin it at the four transfer.py sites:

  * `_upload_local_file`'s skip_if_exists existence check
  * `_list_drive_children` (shared by `sync_folder`)
  * `upload_local_folder`'s bulk skip_if_exists pre-check
  * `download_folder`'s child listing

Each asserts the *exact* escaped form rather than merely "no bare quote", so
dropping the backslash escape (Drive's grammar escapes a literal `'` as `\\'`,
not SQL-style doubling — see #494) fails the test too.
"""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools.drive import transfer as transfer_module
from mcp_gee_sweet.tools.drive.transfer import _list_drive_children, _upload_local_file

# A Drive folder ID that is malformed on purpose: unescaped, the leading quote
# closes the `'…' in parents` value and `trashed=true` becomes its own term.
PROBE_ID = "x' in parents or trashed=true or 'y"
# What Drive must actually receive: both quotes backslash-escaped.
ESCAPED_PROBE = "x\\' in parents or trashed=true or \\'y"


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False):
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


def _drive_svc(files=None):
    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.return_value = {"files": files or []}
    return svc


def _q(svc, index=0):
    return svc.files.return_value.list.call_args_list[index].kwargs["q"]


class TestListDriveChildren:
    async def test_folder_id_is_escaped(self):
        svc = _drive_svc()
        await _list_drive_children(svc, PROBE_ID)
        assert _q(svc) == f"'{ESCAPED_PROBE}' in parents and trashed=false"

    async def test_backslash_in_folder_id_is_escaped_first(self):
        # `_escape_drive_query_value` escapes backslashes before quotes, so a
        # trailing backslash cannot turn the closing quote into an escape.
        svc = _drive_svc()
        await _list_drive_children(svc, "a\\b")
        assert _q(svc) == "'a\\\\b' in parents and trashed=false"

    async def test_ordinary_id_is_unchanged(self):
        svc = _drive_svc()
        await _list_drive_children(svc, "1AbCdEfGhIjKlMnOpQrStUv")
        assert _q(svc) == "'1AbCdEfGhIjKlMnOpQrStUv' in parents and trashed=false"


class TestUploadLocalFileExistenceCheck:
    async def test_parent_folder_id_is_escaped(self, tmp_path):
        local_file = tmp_path / "report.csv"
        local_file.write_text("a,b\n1,2")
        svc = _drive_svc()

        await _upload_local_file(svc, str(local_file), PROBE_ID)

        assert f"'{ESCAPED_PROBE}' in parents and trashed=false" in _q(svc)

    async def test_name_and_parent_are_escaped_independently(self, tmp_path):
        # Both halves of the query carry caller text; escaping must not stop at
        # the name clause that PR #800 already escaped by hand. Without
        # convert=True the lookup is the full name only (PR #800's stem clause
        # is a convert-path detail), which is all this test needs.
        local_file = tmp_path / "it's.csv"
        local_file.write_text("a,b\n1,2")
        svc = _drive_svc()

        await _upload_local_file(svc, str(local_file), PROBE_ID)

        q = _q(svc)
        assert "name='it\\'s.csv'" in q
        assert f"'{ESCAPED_PROBE}' in parents" in q


class TestUploadLocalFolderBulkCheck:
    async def test_parent_folder_id_is_escaped(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        svc = _drive_svc()
        ctx = _make_ctx(drive_service=svc, drive_folder_cache=MagicMock())

        await _transfer_tools["upload_local_folder"](
            local_path=str(tmp_path), parent_folder_id=PROBE_ID, ctx=ctx
        )

        assert f"'{ESCAPED_PROBE}' in parents and trashed=false" in _q(svc)


class TestDownloadFolderQuery:
    async def test_folder_id_is_escaped(self, tmp_path):
        svc = _drive_svc()
        ctx = _make_ctx(drive_service=svc, drive_folder_cache=MagicMock())

        await _transfer_tools["download_folder"](
            folder_id=PROBE_ID, local_path=str(tmp_path), ctx=ctx
        )

        assert _q(svc) == f"'{ESCAPED_PROBE}' in parents and trashed=false"

    async def test_escaped_id_and_mime_filter_coexist(self, tmp_path):
        # The mime filter was already escaped (#1054 review); the folder ID now
        # is too, and neither escape may leak into the other value.
        svc = _drive_svc()
        ctx = _make_ctx(drive_service=svc, drive_folder_cache=MagicMock())

        await _transfer_tools["download_folder"](
            folder_id=PROBE_ID,
            local_path=str(tmp_path),
            mime_type_filter="weird/type'value",
            ctx=ctx,
        )

        assert _q(svc) == (
            f"'{ESCAPED_PROBE}' in parents and trashed=false and mimeType='weird/type\\'value'"
        )
