"""The local-file policy (#796) at each tool's choke point: a refused path gets the
policy's error, and nothing on disk or in Drive is touched.

The policy itself is tested in test_local_files.py."""

import base64
import inspect
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_gee_sweet import auth, cache, local_files
from mcp_gee_sweet.local_files import LocalFileAccessError
from mcp_gee_sweet.tools import gmail, response_limits
from mcp_gee_sweet.tools.docs import content, images
from mcp_gee_sweet.tools.drive import files as files_module
from mcp_gee_sweet.tools.drive.transfer import _upload_local_file

from .drive.test_transfer import _drive_file, _drive_folder, _FakeDriveFS, _transfer_tools
from .fakes import use_local_file_policy

_OFF = "local file access is disabled on this server (LOCAL_FILE_ACCESS=off)"


@pytest.fixture(autouse=True)
def _isolated_deny_list(monkeypatch, tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setattr(auth, "TOKEN_PATH", str(secrets / "token.json"))
    monkeypatch.setattr(auth, "CREDENTIALS_PATH", str(secrets / "credentials.json"))
    monkeypatch.setattr(auth, "SERVICE_ACCOUNT_PATH", str(secrets / "service_account.json"))
    monkeypatch.setattr(cache, "CACHE_DB_PATH", str(secrets / "cache.db"))
    return secrets


@pytest.fixture
def off(monkeypatch):
    use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="off")


@pytest.fixture
def root(monkeypatch, tmp_path):
    """roots mode with tmp_path/root as the one root, and an outside file beside it."""
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("secret")
    use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="roots", LOCAL_FILE_ROOTS=str(root))
    return root


def _ctx(svc, **extra):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.drive_service = svc
    lc.drive_folder_cache = MagicMock()
    for k, v in extra.items():
        setattr(lc, k, v)
    ctx.report_progress = AsyncMock()
    return ctx


def _tree(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


class TestUploads:
    async def test_upload_local_file_off_refuses_before_any_stat_or_call(self, off, tmp_path):
        svc = MagicMock()
        for path in (tmp_path / "missing.txt", tmp_path / "exists.txt"):
            if path.name == "exists.txt":
                path.write_text("x")
            with pytest.raises(LocalFileAccessError, match="LOCAL_FILE_ACCESS=off"):
                await _upload_local_file(svc, str(path), "parent")
        svc.files.assert_not_called()

    async def test_upload_local_file_refuses_the_token(self, monkeypatch, _isolated_deny_list):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        (_isolated_deny_list / "token.json").write_text("{}")
        svc = MagicMock()
        with pytest.raises(LocalFileAccessError, match="own credential"):
            await _upload_local_file(svc, str(_isolated_deny_list / "token.json"), "parent")
        svc.files.assert_not_called()

    async def test_upload_local_folder_outside_root_refused(self, root, tmp_path):
        svc = MagicMock()
        with pytest.raises(LocalFileAccessError, match="outside this server's LOCAL_FILE_ROOTS"):
            await _transfer_tools["upload_local_folder"](
                local_path=str(tmp_path), parent_folder_id="parent", ctx=_ctx(svc)
            )
        svc.files.assert_not_called()

    async def test_upload_local_folder_symlink_escaping_root_lands_in_failed(self, root, tmp_path):
        (root / "ok.txt").write_text("fine")
        (root / "escape.txt").symlink_to(tmp_path / "outside.txt")
        fs = _FakeDriveFS({"parent": []})

        result = await _transfer_tools["upload_local_folder"](
            local_path=str(root), parent_folder_id="parent", skip_if_exists=False, ctx=_ctx(fs.svc)
        )

        assert result["uploaded"] == ["ok.txt"]
        assert [f["name"] for f in result["failed"]] == ["escape.txt"]
        assert "outside this server's LOCAL_FILE_ROOTS" in result["failed"][0]["error"]
        assert [b["name"] for b in fs.created_files] == ["ok.txt"]


class TestDownloads:
    async def test_download_file_off_touches_nothing(self, off, tmp_path):
        svc = MagicMock()
        dest = tmp_path / "new" / "dir/"
        with pytest.raises(LocalFileAccessError, match="LOCAL_FILE_ACCESS=off"):
            await _transfer_tools["download_file"](
                file_id="f1", local_path=str(dest) + "/", ctx=_ctx(svc)
            )
        assert not (tmp_path / "new").exists()
        svc.files.assert_not_called()

    async def test_download_file_into_a_directory_holding_the_token(
        self, monkeypatch, _isolated_deny_list
    ):
        # The joined target is checked, not only the directory the caller named.
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "name": "token.json",
            "mimeType": "application/json",
        }
        with pytest.raises(LocalFileAccessError, match="own credential"):
            await _transfer_tools["download_file"](
                file_id="f1", local_path=str(_isolated_deny_list), ctx=_ctx(svc)
            )
        assert not (_isolated_deny_list / "token.json").exists()
        svc.files.return_value.get_media.assert_not_called()

    async def test_download_folder_outside_root_creates_nothing(self, root, tmp_path):
        svc = MagicMock()
        with pytest.raises(LocalFileAccessError):
            await _transfer_tools["download_folder"](
                folder_id="root", local_path=str(tmp_path / "elsewhere"), ctx=_ctx(svc)
            )
        assert not (tmp_path / "elsewhere").exists()
        svc.files.assert_not_called()

    async def test_download_folder_symlink_in_destination_lands_in_failed(self, root, tmp_path):
        (root / "Escape.pdf").symlink_to(tmp_path / "outside.txt")
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                _drive_file("Escape", "d1", mime="application/vnd.google-apps.document"),
                _drive_file("Fine", "d2", mime="application/vnd.google-apps.document"),
            ]
        }
        svc.files.return_value.export.return_value.execute.return_value = b"pdf"

        result = await _transfer_tools["download_folder"](
            folder_id="root",
            local_path=str(root),
            export_format="pdf",
            skip_if_exists=False,
            ctx=_ctx(svc),
        )

        assert result["downloaded"] == ["Fine.pdf"]
        assert [f["name"] for f in result["failed"]] == ["Escape"]
        assert (tmp_path / "outside.txt").read_text() == "secret"


class TestSyncFolder:
    async def test_off_refuses_before_any_call(self, off, tmp_path):
        fs = _FakeDriveFS({"root": []})
        with pytest.raises(LocalFileAccessError):
            await _transfer_tools["sync_folder"](
                folder_id="root", local_path=str(tmp_path / "new"), ctx=_ctx(fs.svc)
            )
        assert fs.list_calls == []
        assert not (tmp_path / "new").exists()

    async def test_result_local_path_outside_root_refused_before_any_transfer(self, root, tmp_path):
        fs = _FakeDriveFS({"root": []})
        with pytest.raises(LocalFileAccessError):
            await _transfer_tools["sync_folder"](
                folder_id="root",
                local_path=str(root),
                result_local_path=str(tmp_path / "manifest.json"),
                ctx=_ctx(fs.svc),
            )
        assert fs.list_calls == []

    @pytest.mark.parametrize("dry_run", [False, True])
    async def test_symlink_escaping_root_is_reported_not_uploaded(self, root, tmp_path, dry_run):
        (root / "ok.txt").write_text("fine")
        (root / "escape.txt").symlink_to(tmp_path / "outside.txt")
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(root),
            direction="upload",
            dry_run=dry_run,
            ctx=_ctx(fs.svc),
        )

        if dry_run:
            by_name = {a["name"]: a for a in result["actions"]}
            assert by_name["ok.txt"]["action"] == "upload"
            assert by_name["escape.txt"]["action"] == "local_read_fail"
            assert "outside this server's LOCAL_FILE_ROOTS" in by_name["escape.txt"]["reason"]
            assert fs.created_files == []
        else:
            assert result["uploaded"] == ["ok.txt"]
            assert [f["name"] for f in result["failed"]] == ["escape.txt"]
            assert [b["name"] for b in fs.created_files] == ["ok.txt"]

    async def test_download_never_writes_through_an_escaping_symlink(self, root, tmp_path):
        (root / "a.pdf").symlink_to(tmp_path / "outside.txt")
        fs = _FakeDriveFS(
            {
                "root": [
                    _drive_file(
                        "a",
                        "fa",
                        mime="application/vnd.google-apps.document",
                        mtime="2099-01-01T00:00:00.000Z",
                    )
                ]
            }
        )
        fs.svc.files.return_value.export.return_value.execute.return_value = b"overwrite"

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(root),
            direction="download",
            export_format="pdf",
            ctx=_ctx(fs.svc),
        )

        assert [f["name"] for f in result["failed"]] == ["a.pdf"]
        assert (tmp_path / "outside.txt").read_text() == "secret"
        fs.svc.files.return_value.export.assert_not_called()

    async def test_drive_file_named_like_the_token_is_never_downloaded(
        self, monkeypatch, _isolated_deny_list
    ):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        fs = _FakeDriveFS({"root": [_drive_file("token.json", "ft")]})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(_isolated_deny_list),
            direction="download",
            ctx=_ctx(fs.svc),
        )

        assert [f["name"] for f in result["failed"]] == ["token.json"]
        assert "own credential" in result["failed"][0]["error"]
        assert not (_isolated_deny_list / "token.json").exists()

    async def test_local_only_refused_file_is_a_plain_skip_for_download(self, root, tmp_path):
        # Never touched by a download-only sync, so not reported as a failure.
        (root / "escape.txt").symlink_to(tmp_path / "outside.txt")
        fs = _FakeDriveFS({"root": []})

        result = await _transfer_tools["sync_folder"](
            folder_id="root", local_path=str(root), direction="download", ctx=_ctx(fs.svc)
        )

        assert result["failed"] == []
        assert result["skipped"] == ["escape.txt"]

    @pytest.mark.parametrize("dry_run", [False, True])
    async def test_recursion_never_descends_through_an_escaping_symlink(
        self, root, tmp_path, dry_run
    ):
        outside = tmp_path / "outside_dir"
        outside.mkdir()
        (outside / "loot.txt").write_text("secret")
        (root / "escape").symlink_to(outside, target_is_directory=True)
        (root / "real").mkdir()
        (root / "real" / "ok.txt").write_text("fine")
        fs = _FakeDriveFS({"root": [_drive_folder("escape", "fe"), _drive_folder("real", "fr")]})

        result = await _transfer_tools["sync_folder"](
            folder_id="root",
            local_path=str(root),
            direction="upload",
            recursive=True,
            dry_run=dry_run,
            ctx=_ctx(fs.svc),
        )

        assert "fe" not in fs.list_calls
        if dry_run:
            by_name = {a["name"]: a["action"] for a in result["actions"]}
            assert by_name["escape/"] == "local_read_fail"
            assert by_name["real/ok.txt"] == "upload"
        else:
            assert result["uploaded"] == ["real/ok.txt"]
            assert [f["name"] for f in result["failed"]] == ["escape/"]


class TestCappedResultWrites:
    async def test_off_refuses_and_writes_nothing(self, off, tmp_path):
        with pytest.raises(LocalFileAccessError, match="LOCAL_FILE_ACCESS=off"):
            await response_limits.write_capped_result_to_disk(
                {"a": 1}, str(tmp_path / "out/"), default_filename="x.json", manifest_extra={}
            )
        assert _tree(tmp_path) == ["secrets"]

    async def test_joined_default_filename_is_checked(self, root, tmp_path):
        # A directory inside the root, but the joined file is a symlink leading out.
        (root / "x.json").symlink_to(tmp_path / "outside.txt")
        with pytest.raises(LocalFileAccessError):
            await response_limits.write_capped_result_to_disk(
                {"a": 1}, str(root), default_filename="x.json", manifest_extra={}
            )
        assert (tmp_path / "outside.txt").read_text() == "secret"

    async def test_inside_root_writes(self, root):
        manifest = await response_limits.write_capped_result_to_disk(
            {"a": 1}, str(root / "r.json"), default_filename="x.json", manifest_extra={}
        )
        assert json.loads((root / "r.json").read_text()) == {"a": 1}
        assert manifest["local_path"] == str(root / "r.json")

    @pytest.mark.parametrize("policy", ["off", "full"])
    def test_cap_hint_offers_local_path_only_when_usable(self, monkeypatch, policy):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS=policy)
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError) as exc:
            response_limits.enforce_response_size_cap({"big": "x" * 20}, tool_name="t")
        assert ("Pass local_path" in str(exc.value)) is (policy == "full")


class TestOtherReaders:
    async def test_import_csv_to_sheet_off(self, off, tmp_path):
        (tmp_path / "a.csv").write_text("a,b\n")
        tools = {}

        def tool(annotations=None, local_only=False):
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

        files_module.register(tool)
        svc = MagicMock()
        result = await tools["import_csv_to_sheet"](
            local_path=str(tmp_path / "a.csv"), title="t", ctx=_ctx(svc, sheets_service=svc)
        )
        assert result == {"error": _OFF}
        svc.files.assert_not_called()

    def test_doc_source_file_outside_root(self, root, tmp_path):
        (tmp_path / "notes.md").write_text("# hi")
        result = content._read_doc_source_file(
            str(tmp_path / "notes.md"), None, format_overridable=False
        )
        assert "outside this server's LOCAL_FILE_ROOTS" in result["error"]

    def test_doc_source_file_symlink_keeps_its_own_suffix(self, root, tmp_path):
        (root / "notes.txt").write_text("# hi")
        (root / "notes.md").symlink_to(root / "notes.txt")
        assert content._read_doc_source_file(
            str(root / "notes.md"), None, format_overridable=False
        ) == ("# hi", "markdown")

    def test_gmail_attachment_refused(self, off, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"x")
        with pytest.raises(LocalFileAccessError, match="LOCAL_FILE_ACCESS=off"):
            gmail._read_attachment_bytes({"local_path": str(tmp_path / "a.pdf")})

    def test_gmail_base64_attachment_still_works_when_off(self, off):
        assert gmail._read_attachment_bytes(
            {"content_base64": base64.b64encode(b"hi").decode(), "filename": "a.txt"}
        ) == ("a.txt", None, b"hi")

    async def test_markdown_local_image_refused_per_image(self, off, tmp_path):
        (tmp_path / "a.png").write_bytes(b"x")
        svc = MagicMock()
        result = await content._resolve_image_source(svc, str(tmp_path / "a.png"), "folder")
        assert result == {"error": _OFF}
        svc.files.assert_not_called()

    async def test_local_image_upload_refused_before_size_check(self, root, tmp_path):
        svc = MagicMock()
        result = await images.upload_and_share_local_image(
            svc, str(tmp_path / "outside.txt"), "folder", auto_downscale=False
        )
        assert "outside this server's LOCAL_FILE_ROOTS" in result["error"]
        svc.files.assert_not_called()


def test_policy_fixture_is_scoped_to_the_test():
    # The process default (stdio, unset) is back after the fixtures above.
    assert local_files.POLICY.mode is local_files.LocalFileAccess.FULL
    assert local_files.POLICY.explicit is False


def _all_tools():
    from mcp_gee_sweet.tools import register_all

    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    register_all(tool)
    return captured


_OPTIONAL_LOCAL_PATH_TOOLS = [
    "export_revision",
    "find_in_doc",
    "find_in_spreadsheet",
    "get_doc_as_markdown",
    "get_doc_content",
    "get_message",
    "get_multiple_sheet_data",
    "get_multiple_spreadsheet_summary",
    "get_sheet_data",
    "get_thread",
]


@pytest.mark.parametrize("name", _OPTIONAL_LOCAL_PATH_TOOLS)
async def test_optional_local_path_refused_before_any_api_call(off, tmp_path, name):
    """A refused local_path costs no fetch: it's checked at the tool's entry, not
    only when the capped result is written."""
    func = _all_tools()[name]
    kwargs = {}
    for param in inspect.signature(func).parameters.values():
        if param.default is not inspect.Parameter.empty or param.name == "ctx":
            continue
        kwargs[param.name] = [] if "list" in str(param.annotation) else "x"
    ctx = MagicMock()
    with pytest.raises(LocalFileAccessError, match="LOCAL_FILE_ACCESS=off"):
        await func(**kwargs, local_path=str(tmp_path / "out.json"), ctx=ctx)
    assert ctx.request_context.lifespan_context.mock_calls == []
    assert _tree(tmp_path) == ["secrets"]
