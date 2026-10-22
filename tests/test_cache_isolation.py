"""GHSA-8jqx-w7j8-6xwm: the cache keeps each Google identity's entries apart, lives in
an owner-only per-user directory, and serves a stale entry only when Google couldn't
answer."""

import contextlib
import os
import sqlite3
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from mcp_gee_sweet import auth, cache, local_files, reauth
from mcp_gee_sweet.auth import SpreadsheetContext
from mcp_gee_sweet.cache import (
    CalendarCache,
    DocContentCache,
    DriveFolderCache,
    SheetDataCache,
    SheetInfo,
    SheetStructureCache,
    fetch_sheets,
)
from mcp_gee_sweet.local_files import LocalFileAccessError

from .fakes import FakeSheetsService

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX owner and mode bits")


def _http_error(status: int) -> HttpError:
    return HttpError(MagicMock(status=status, reason="x"), b'{"error": {}}')


def _denied_service(status: int = 403) -> MagicMock:
    """Drive and Sheets both refusing every call, as for an identity with no access."""
    err = _http_error(status)
    svc = MagicMock()
    svc._http = SimpleNamespace(credentials=None)
    svc.files.return_value.get.return_value.execute.side_effect = err
    svc.spreadsheets.return_value.get.return_value.execute.side_effect = err
    return svc


def _pair(cls, db):
    return cls(db_path=db, ttl=60, principal="drive:A"), cls(
        db_path=db, ttl=60, principal="drive:B"
    )


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "shared.db")


@pytest.fixture(autouse=True)
def _close_opened_connections(monkeypatch):
    """Tests here call _open/_connect directly; close what they open, so a real
    connection leak isn't hidden among the tests' own ResourceWarnings."""
    opened = []
    real_connect = cache._connect

    def tracking_connect(path):
        conn = real_connect(path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(cache, "_connect", tracking_connect)
    yield
    for conn in opened:
        conn.close()


class TestPrincipalIsolation:
    def test_sheet_structure(self, db):
        a, b = _pair(SheetStructureCache, db)
        a.store("sid", [SheetInfo("Salaries", 0)], title="A's plan")
        assert b.get_sheets("sid") is None
        assert b.get_title("sid") is None
        assert b.get_stale_sheets("sid") is None
        assert a.get_sheets("sid")[0].title == "Salaries"

    def test_sheet_data(self, db):
        a, b = _pair(SheetDataCache, db)
        a.store("sid", 0, ["H"], [["r"]], 5)
        assert b.get("sid", 0, 5) is None
        assert a.get("sid", 0, 5) is not None

    def test_drive_folder(self, db):
        a, b = _pair(DriveFolderCache, db)
        a.store("folder", None, [{"id": "f"}], 10)
        assert b.get("folder", None, 10) is None
        assert a.get("folder", None, 10) == [{"id": "f"}]

    def test_doc_content(self, db):
        a, b = _pair(DocContentCache, db)
        a.store("doc", {"title": "A's doc"})
        assert b.get("doc") is None
        assert a.get("doc") == {"title": "A's doc"}

    def test_calendar_and_calendar_list(self, db):
        a, b = _pair(CalendarCache, db)
        a.store("cal", {"id": "cal"})
        a.store_list([{"id": "cal"}])
        assert b.get("cal") is None
        assert b.get_list() is None
        assert a.get_list() == [{"id": "cal"}]

    def test_both_principals_keep_their_own_entry_for_one_key(self, db):
        a, b = _pair(SheetStructureCache, db)
        a.store("sid", [SheetInfo("A", 0)])
        b.store("sid", [SheetInfo("B", 0)])
        assert a.get_sheets("sid")[0].title == "A"
        assert b.get_sheets("sid")[0].title == "B"

    def test_ttl_expiry_marks_only_the_expired_principals_row(self, db):
        a = SheetStructureCache(db_path=db, ttl=0, principal="drive:A")
        b = SheetStructureCache(db_path=db, ttl=60, principal="drive:B")
        a.store("sid", [SheetInfo("A", 0)])
        b.store("sid", [SheetInfo("B", 0)])
        assert a.get_sheets("sid") is None  # expired for A
        assert b.get_sheets("sid")[0].title == "B"


class TestDeniedIdentityGetsNothing:
    """Joy's probe: B can't reach the spreadsheet (every call 403s) but shares the DB
    file with A, who cached it."""

    @pytest.mark.parametrize("validate", [True, False])
    async def test_denied_principal_gets_the_403(self, db, monkeypatch, validate):
        monkeypatch.setattr(cache, "CACHE_VALIDATE_MODIFIED_TIME", validate)
        a, b = _pair(SheetStructureCache, db)
        a.store("sid", [SheetInfo("Salaries", 0)], modified_time="t1")
        denied = _denied_service()
        with pytest.raises(HttpError):
            await fetch_sheets(denied, "sid", b, drive_service=denied)
        b.mark_dirty("sid")
        with pytest.raises(HttpError):
            await fetch_sheets(denied, "sid", b, drive_service=denied)

    async def test_owner_gets_the_403_too_rather_than_its_stale_entry(self, db):
        # Losing access is an answer; a stale entry mustn't outlive it.
        a, _ = _pair(SheetStructureCache, db)
        a.store("sid", [SheetInfo("Salaries", 0)])
        a.mark_dirty("sid")
        with pytest.raises(HttpError):
            await fetch_sheets(_denied_service(), "sid", a)


class TestStaleFallbackOnlyWhenTransient:
    def _stale_cache(self, db):
        c = SheetStructureCache(db_path=db, ttl=60, principal="drive:A")
        c.store("sid", [SheetInfo("Stale", 0)])
        c.mark_dirty("sid")
        return c

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    async def test_client_errors_raise_even_with_a_stale_row(self, db, status):
        c = self._stale_cache(db)
        with pytest.raises(HttpError):
            await fetch_sheets(FakeSheetsService(exception=_http_error(status)), "sid", c)

    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_server_errors_serve_stale(self, db, status):
        c = self._stale_cache(db)
        got = await fetch_sheets(FakeSheetsService(exception=_http_error(status)), "sid", c)
        assert got[0].title == "Stale"

    @pytest.mark.parametrize(
        "error",
        [
            httplib2.error.ServerNotFoundError("dns"),
            TransportError("reset"),
            TimeoutError("slow"),
            ConnectionResetError("reset"),
        ],
    )
    async def test_transport_errors_serve_stale(self, db, error):
        c = self._stale_cache(db)
        got = await fetch_sheets(FakeSheetsService(exception=error), "sid", c)
        assert got[0].title == "Stale"

    @pytest.mark.parametrize("error", [RefreshError("invalid_grant"), KeyError("sheets")])
    async def test_refresh_and_other_errors_raise(self, db, error):
        c = self._stale_cache(db)
        with pytest.raises(type(error)):
            await fetch_sheets(FakeSheetsService(exception=error), "sid", c)

    async def test_transient_error_with_no_stale_row_propagates(self, db):
        c = SheetStructureCache(db_path=db, ttl=60, principal="drive:A")
        error = _http_error(503)
        with pytest.raises(HttpError) as raised:
            await fetch_sheets(FakeSheetsService(exception=error), "sid", c)
        assert raised.value is error


class TestCrossPrincipalInvalidation:
    def test_mark_dirty_reaches_every_principal(self, db):
        a, b = _pair(SheetStructureCache, db)
        a.store("sid", [SheetInfo("A", 0)])
        b.mark_dirty("sid")
        assert a.get_sheets("sid") is None

    def test_prefix_and_all_reach_every_principal(self, db):
        a, b = _pair(SheetDataCache, db)
        a.store("sid", 0, ["H"], [], 5)
        b.mark_dirty("sid")
        assert a.get("sid", 0, 5) is None
        fa, fb = _pair(DriveFolderCache, db)
        fa.store("folder", None, [{"id": "f"}], 10)
        fb.mark_all_dirty()
        assert fa.get("folder", None, 10) is None

    def test_unbound_instance_still_invalidates(self, db):
        a = SheetStructureCache(db_path=db, ttl=60, principal="drive:A")
        unbound = SheetStructureCache(db_path=db, ttl=60)
        a.store("sid", [SheetInfo("A", 0)])
        unbound.mark_dirty("sid")
        assert a.get_sheets("sid") is None

    @pytest.mark.parametrize("scoped", [True, False])
    async def test_refresh_cache_reaches_every_principal(self, db, scoped):
        from mcp_gee_sweet.tools import cache as cache_tools

        registry = {}

        def tool(annotations=None, local_only=False):
            def decorator(func):
                registry[func.__name__] = func
                return func

            return decorator

        cache_tools.register(tool)
        a_ctx = _context(principal="drive:A", db=db)
        b_ctx = _context(principal="drive:B", db=db)
        a_ctx.cache.store("sid", [SheetInfo("A", 0)])
        a_ctx.doc_cache.store("doc", {"title": "A"})
        kwargs = {"spreadsheet_id": "sid", "doc_id": "doc"} if scoped else {}
        await registry["refresh_cache"](ctx=_ctx(b_ctx), **kwargs)
        assert a_ctx.cache.get_sheets("sid") is None
        assert a_ctx.doc_cache.get("doc") is None


class TestUnbound:
    def test_reads_miss_and_writes_do_nothing(self, db):
        unbound = SheetStructureCache(db_path=db, ttl=60)
        unbound.store("sid", [SheetInfo("X", 0)])
        assert unbound.get_sheets("sid") is None
        assert unbound.get_stale_sheets("sid") is None
        for cls, write in [
            (DocContentCache, lambda c: c.store("doc", {})),
            (CalendarCache, lambda c: c.store_list([])),
            (DriveFolderCache, lambda c: c.store("f", None, [], 10)),
        ]:
            write(cls(db_path=db, ttl=60))
        # An unbound write doesn't even open the DB; a bound instance creates the table.
        SheetStructureCache(db_path=db, ttl=60, principal="drive:A").mark_all_dirty()
        with contextlib.closing(sqlite3.connect(db)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0

    def test_default_context_is_unbound(self):
        context = _context(principal=None)
        assert context.cache_principal is None
        assert context.cache.principal is None


def _context(principal=None, db=None, credentials=None, drive=None) -> SpreadsheetContext:
    context = SpreadsheetContext(
        sheets_service=MagicMock(),
        drive_service=drive if drive is not None else MagicMock(),
        docs_service=MagicMock(),
        calendar_service=MagicMock(),
        activity_service=MagicMock(),
        gmail_service=MagicMock(),
        credentials=credentials,
    )
    if principal is not None or db is not None:
        for name, cls in auth._CACHE_FIELDS.items():
            setattr(context, name, cls(db_path=db, ttl=60, principal=principal))
        context.cache_principal = principal
    return context


def _ctx(context):
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=context))


def _drive_reporting(permission_id=None, error=None) -> MagicMock:
    drive = MagicMock()
    drive._http = SimpleNamespace(credentials=None)
    execute = drive.about.return_value.get.return_value.execute
    if error is not None:
        execute.side_effect = error
    else:
        execute.return_value = {"user": {"permissionId": permission_id}}
    return drive


def _service_account_creds(email="bot@proj.iam.gserviceaccount.com"):
    return SimpleNamespace(service_account_email=email)


class TestPrincipalResolution:
    @pytest.mark.parametrize(
        "credentials", [SimpleNamespace(refresh_token="rt"), _service_account_creds(), None]
    )
    async def test_drive_identity_for_every_auth_method(self, credentials):
        context = _context(drive=_drive_reporting("123"), credentials=credentials)
        await auth.ensure_cache_principal(context)
        assert context.cache_principal == "drive:123"
        assert context.cache.principal == "drive:123"
        assert context.calendar_cache.principal == "drive:123"

    async def test_drive_failure_with_a_service_account_uses_its_email(self):
        context = _context(
            drive=_drive_reporting(error=_http_error(403)), credentials=_service_account_creds()
        )
        await auth.ensure_cache_principal(context)
        assert context.cache_principal == "sa:bot@proj.iam.gserviceaccount.com"

    async def test_drive_failure_with_user_credentials_stays_unbound_and_retries(self):
        drive = _drive_reporting(error=_http_error(403))
        context = _context(drive=drive, credentials=SimpleNamespace(refresh_token="rt"))
        await auth.ensure_cache_principal(context)
        assert context.cache_principal is None
        drive.about.return_value.get.return_value.execute.side_effect = None
        drive.about.return_value.get.return_value.execute.return_value = {
            "user": {"permissionId": "123"}
        }
        await auth.ensure_cache_principal(context)
        assert context.cache_principal == "drive:123"

    async def test_compute_engine_default_email_is_ignored(self):
        context = _context(
            drive=_drive_reporting(error=_http_error(403)),
            credentials=_service_account_creds("default"),
        )
        await auth.ensure_cache_principal(context)
        assert context.cache_principal is None

    async def test_calendar_only_scopes_stay_unbound(self):
        # No Drive scope: about() is refused; a user identity has no other ID to use.
        context = _context(
            drive=_drive_reporting(error=_http_error(403)),
            credentials=SimpleNamespace(refresh_token="rt"),
        )
        await auth.ensure_cache_principal(context)
        assert context.cache_principal is None
        context.cache.store("sid", [SheetInfo("X", 0)])
        assert context.cache.get_sheets("sid") is None

    async def test_never_raises(self):
        drive = MagicMock()
        drive.about.side_effect = RuntimeError("boom")
        context = _context(drive=drive)
        await auth.ensure_cache_principal(context)
        assert context.cache_principal is None

    async def test_degraded_context_isnt_bound(self):
        context = auth._degraded_context("no token")
        await auth.ensure_cache_principal(context)
        assert context.cache_principal is None

    async def test_bound_context_isnt_looked_up_again(self):
        drive = _drive_reporting("123")
        context = _context(drive=drive)
        await auth.ensure_cache_principal(context)
        await auth.ensure_cache_principal(context)
        assert drive.about.return_value.get.return_value.execute.call_count == 1

    async def test_rebinding_keeps_the_ttl(self):
        context = _context(drive=_drive_reporting("123"))
        for name in auth._CACHE_FIELDS:
            getattr(context, name).set_ttl(7)
        await auth.ensure_cache_principal(context)
        assert all(getattr(context, n).get_ttl() == 7 for n in auth._CACHE_FIELDS)

    async def test_token_swapped_during_the_lookup_isnt_bound_to_the_old_identity(self):
        context = _context(credentials=SimpleNamespace(refresh_token="old"))
        drive = context.drive_service

        def lookup(**kwargs):
            # A re-authorization to another account lands mid-lookup.
            context.credentials = SimpleNamespace(refresh_token="new")
            return {"user": {"permissionId": "old-account"}}

        drive._http = SimpleNamespace(credentials=None)
        drive.about.return_value.get.return_value.execute.side_effect = lookup
        await auth.ensure_cache_principal(context)
        assert context.cache_principal is None

    async def test_lifespan_binds_the_new_context(self, monkeypatch):
        monkeypatch.setattr(auth, "AUTH_METHOD", "service_account")
        drive = _drive_reporting("sa-perm")
        services = {name: MagicMock() for name in auth._SERVICE_VERSIONS}
        services["drive"] = drive
        with (
            patch.object(auth, "_service_account_creds", return_value=_service_account_creds()),
            patch.object(auth, "_build_services", return_value=services),
        ):
            context = await auth._build_context()
        assert context.cache_principal == "drive:sa-perm"

    async def test_lifespan_lookup_failure_leaves_it_unbound(self, monkeypatch):
        monkeypatch.setattr(auth, "AUTH_METHOD", "oauth")
        services = {name: MagicMock() for name in auth._SERVICE_VERSIONS}
        services["drive"] = _drive_reporting(error=_http_error(500))
        with (
            patch.object(auth, "_oauth_creds", return_value=SimpleNamespace(refresh_token="rt")),
            patch.object(auth, "_build_services", return_value=services),
        ):
            context = await auth._build_context()
        assert context.cache_principal is None
        assert context.unauthorized_message is None

    async def test_before_call_binds_a_service_account_context(self):
        context = _context(drive=_drive_reporting("123"), credentials=_service_account_creds())
        await reauth.before_call(_ctx(context))
        assert context.cache_principal == "drive:123"


class TestRebinding:
    async def test_in_flight_fetch_stores_under_its_own_principal(self, db):
        context = _context(principal="drive:A", db=db)
        held = context.cache

        class Sheets(FakeSheetsService):
            def execute(self, **kwargs):
                auth._bind_caches(context, "drive:B")  # rebinding mid-fetch
                return {"sheets": [{"properties": {"title": "A's", "sheetId": 0}}]}

        await fetch_sheets(Sheets(), "sid", held)
        assert context.cache.principal == "drive:B"
        assert context.cache.get_sheets("sid") is None
        fresh_a = SheetStructureCache(db_path=db, ttl=60, principal="drive:A")
        assert fresh_a.get_sheets("sid")[0].title == "A's"

    async def test_reauthorizing_unbinds_and_the_same_account_gets_its_entries_back(self):
        # The default CACHE_DB_PATH (conftest's), which rebinding reopens.
        context = _context(principal="drive:A", drive=_drive_reporting("A"))
        context.oauth_reauthorizable = True
        context.cache.store("sid", [SheetInfo("A", 0)])
        services = {name: MagicMock() for name in auth._SERVICE_VERSIONS}
        services["drive"] = _drive_reporting("A")
        with patch.object(auth, "_build_services", return_value=services):
            auth.apply_oauth_credentials(context, SimpleNamespace(refresh_token="rt2"), 1)
        assert context.cache_principal is None
        assert context.cache.get_sheets("sid") is None
        await auth.ensure_cache_principal(context)
        assert context.cache_principal == "drive:A"
        assert context.cache.get_sheets("sid")[0].title == "A"

    async def test_reauthorizing_to_another_account_misses(self):
        context = _context(principal="drive:A")
        context.cache.store("sid", [SheetInfo("A", 0)])
        services = {name: MagicMock() for name in auth._SERVICE_VERSIONS}
        services["drive"] = _drive_reporting("B")
        with patch.object(auth, "_build_services", return_value=services):
            auth.apply_oauth_credentials(context, SimpleNamespace(refresh_token="rt2"), 1)
        await auth.ensure_cache_principal(context)
        assert context.cache_principal == "drive:B"
        assert context.cache.get_sheets("sid") is None


def _v1_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cache (namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
        " fetched_at REAL NOT NULL, dirty INTEGER NOT NULL DEFAULT 0, rows_fetched INTEGER,"
        " PRIMARY KEY (namespace, key))"
    )
    conn.execute("INSERT INTO cache VALUES ('sheet_structure', 'sid', '{}', 0, 0, NULL)")
    conn.commit()
    conn.close()


class TestSchemaUpgrade:
    def test_old_table_is_dropped_and_recreated(self, db):
        _v1_db(db)
        conn = cache._open(db)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == cache._SCHEMA_VERSION
        columns = [r[1] for r in conn.execute("PRAGMA table_info(cache)")]
        assert columns[0] == "principal"
        assert conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0

    def test_current_db_is_kept(self, db):
        SheetStructureCache(db_path=db, ttl=60, principal="drive:A").store("sid", [])
        assert SheetStructureCache(db_path=db, ttl=60, principal="drive:A").get_sheets("sid") == []

    def test_concurrent_openers_both_succeed(self, db):
        _v1_db(db)
        barrier = threading.Barrier(4)
        conns, errors = [], []

        def opener():
            barrier.wait()
            try:
                conns.append(cache._connect(db))
            except Exception as e:  # pragma: no cover - the failure being tested for
                errors.append(e)

        threads = [threading.Thread(target=opener) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert all(
            c.execute("PRAGMA user_version").fetchone()[0] == cache._SCHEMA_VERSION for c in conns
        )


class TestPathResolution:
    def test_linux_default(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/u")
        assert cache.default_db_path({}, "linux") == "/home/u/.cache/mcp-gee-sweet/cache.db"

    def test_absolute_xdg_cache_home(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/u")
        env = {"XDG_CACHE_HOME": "/xdg"}
        assert cache.default_db_path(env, "linux") == "/xdg/mcp-gee-sweet/cache.db"

    def test_relative_xdg_cache_home_is_ignored(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/u")
        env = {"XDG_CACHE_HOME": "rel"}
        assert cache.default_db_path(env, "linux") == "/home/u/.cache/mcp-gee-sweet/cache.db"

    def test_macos_default(self, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/u")
        assert (
            cache.default_db_path({}, "darwin") == "/Users/u/Library/Caches/mcp-gee-sweet/cache.db"
        )

    def test_windows_default(self):
        env = {"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local"}
        path = cache.default_db_path(env, "win32")
        assert path.startswith("C:\\Users\\u\\AppData\\Local")
        assert path.endswith(os.path.join("mcp-gee-sweet", "cache.db"))

    def test_explicit_path_and_memory_are_honored(self):
        assert cache.db_path({"CACHE_DB_PATH": "/x/c.db"}, "linux") == "/x/c.db"
        assert cache.db_path({"CACHE_DB_PATH": ":memory:"}, "linux") == ":memory:"

    def test_empty_explicit_path_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/u")
        assert cache.db_path({"CACHE_DB_PATH": ""}, "linux") == cache.default_db_path({}, "linux")

    def test_importing_the_server_creates_nothing(self, tmp_path):
        env = {k: v for k, v in os.environ.items() if k not in ("CACHE_DB_PATH", "XDG_CACHE_HOME")}
        env["HOME"] = str(tmp_path)
        subprocess.run(
            [sys.executable, "-c", "import mcp_gee_sweet.server"],
            env=env,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=120,
        )
        assert list(tmp_path.iterdir()) == []


def _mode(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture
def default_location(tmp_path, monkeypatch):
    """Point the default cache location into tmp_path, as if CACHE_DB_PATH were unset."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CACHE_DB_PATH")
    path = cache.default_db_path()
    monkeypatch.setattr(cache, "CACHE_DB_PATH", path)
    return path


@posix_only
class TestPermissions:
    @pytest.mark.parametrize("umask", [0o022, 0o000])
    def test_default_directory_and_files_are_owner_only(self, default_location, umask):
        old = os.umask(umask)
        try:
            c = SheetStructureCache(ttl=60, principal="drive:A")
            c.store("sid", [SheetInfo("X", 0)])
        finally:
            os.umask(old)
        assert _mode(os.path.dirname(default_location)) == 0o700
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(default_location + suffix):
                assert _mode(default_location + suffix) == 0o600, suffix
        assert c.get_sheets("sid")[0].title == "X"

    def test_existing_loose_directory_is_tightened(self, default_location):
        directory = os.path.dirname(default_location)
        os.makedirs(directory, mode=0o755)
        os.chmod(directory, 0o755)
        cache._open(default_location).close()
        assert _mode(directory) == 0o700

    def test_another_users_directory_falls_back_to_memory(
        self, default_location, monkeypatch, caplog
    ):
        os.makedirs(os.path.dirname(default_location))
        monkeypatch.setattr(cache.os, "getuid", lambda: os.geteuid() + 1)
        conn = cache._open(default_location)
        assert conn.execute("PRAGMA database_list").fetchone()[2] == ""  # in-memory
        assert not os.path.exists(default_location)
        assert "owned by another user" in caplog.text

    def test_another_users_file_falls_back_to_memory_and_is_kept(self, tmp_path, monkeypatch):
        path = str(tmp_path / "theirs.db")
        open(path, "w").close()
        monkeypatch.setattr(cache.os, "getuid", lambda: os.geteuid() + 1)
        conn = cache._open(path)
        assert conn.execute("PRAGMA database_list").fetchone()[2] == ""
        assert os.path.exists(path)

    def test_symlinked_directory_is_refused(self, default_location, tmp_path):
        target = tmp_path / "elsewhere"
        target.mkdir()
        os.makedirs(os.path.dirname(os.path.dirname(default_location)), exist_ok=True)
        os.symlink(target, os.path.dirname(default_location))
        conn = cache._open(default_location)
        assert conn.execute("PRAGMA database_list").fetchone()[2] == ""
        assert list(target.iterdir()) == []

    @pytest.mark.parametrize("suffix", ["", "-wal"])
    def test_symlinked_file_is_refused(self, tmp_path, suffix):
        target = tmp_path / "target"
        target.write_text("")
        path = str(tmp_path / "c.db")
        os.symlink(target, path + suffix)
        conn = cache._open(path)
        assert conn.execute("PRAGMA database_list").fetchone()[2] == ""
        assert target.read_text() == ""

    def test_explicit_path_is_tightened_and_its_directory_left_alone(self, tmp_path):
        directory = tmp_path / "shared"
        directory.mkdir()
        os.chmod(directory, 0o755)
        path = str(directory / "c.db")
        open(path, "w").close()
        os.chmod(path, 0o644)
        cache._open(path).close()
        assert _mode(path) == 0o600
        assert _mode(directory) == 0o755

    def test_no_home_directory_falls_back_to_memory(self, monkeypatch):
        monkeypatch.delenv("CACHE_DB_PATH")
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setattr(cache.os.path, "expanduser", lambda p: p)
        path = cache.default_db_path()
        assert not os.path.isabs(path)
        conn = cache._open(path)
        assert conn.execute("PRAGMA database_list").fetchone()[2] == ""
        assert not os.path.exists(path)

    def test_legacy_tmp_db_is_tightened_not_deleted(self, default_location, tmp_path, monkeypatch):
        legacy = str(tmp_path / "legacy.db")
        for suffix in ("", "-wal"):
            open(legacy + suffix, "w").close()
            os.chmod(legacy + suffix, 0o644)
        monkeypatch.setattr(cache, "_LEGACY_DB_PATH", legacy)
        monkeypatch.setattr(cache, "_legacy_db_checked", False)
        cache._open(default_location).close()
        assert _mode(legacy) == 0o600
        assert _mode(legacy + "-wal") == 0o600

    def test_legacy_db_is_left_alone_under_an_explicit_path(self, tmp_path, monkeypatch):
        legacy = str(tmp_path / "legacy.db")
        open(legacy, "w").close()
        os.chmod(legacy, 0o644)
        monkeypatch.setattr(cache, "_LEGACY_DB_PATH", legacy)
        monkeypatch.setattr(cache, "_legacy_db_checked", False)
        cache._open(str(tmp_path / "explicit.db")).close()
        assert _mode(legacy) == 0o644


class TestDenyList:
    def test_default_cache_directory_is_denied_whole(self, default_location, monkeypatch):
        policy = local_files.resolve_policy(
            {**os.environ, "LOCAL_FILE_ACCESS": "full"}, ["mcp-gee-sweet"]
        )
        monkeypatch.setattr(local_files, "POLICY", policy)
        directory = os.path.dirname(default_location)
        for path in (directory, os.path.join(directory, "other.db"), default_location + "-shm"):
            with pytest.raises(LocalFileAccessError):
                local_files.check_write(path)
        local_files.check_write(os.path.join(os.path.dirname(directory), "next-door.txt"))

    def test_explicit_path_denies_its_files_not_its_directory(self, tmp_path, monkeypatch):
        path = str(tmp_path / "explicit.db")
        monkeypatch.setattr(cache, "CACHE_DB_PATH", path)
        policy = local_files.resolve_policy(
            {**os.environ, "LOCAL_FILE_ACCESS": "full"}, ["mcp-gee-sweet"]
        )
        monkeypatch.setattr(local_files, "POLICY", policy)
        with pytest.raises(LocalFileAccessError):
            local_files.check_read(path + "-wal")
        local_files.check_read(str(tmp_path / "neighbor.txt"))


class TestRoundOneFindings:
    """PR #1 (fork) QA round 1."""

    @posix_only
    def test_no_follow_symlinks_chmod_on_old_glibc(self, tmp_path, monkeypatch):
        # glibc < 2.32: chmod(follow_symlinks=False) raises NotImplementedError.
        real_chmod = os.chmod

        def old_glibc_chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
            if not follow_symlinks:
                raise NotImplementedError("chmod: follow_symlinks unavailable on this platform")
            return real_chmod(path, mode, dir_fd=dir_fd)

        monkeypatch.setattr(cache.os, "chmod", old_glibc_chmod)
        path = str(tmp_path / "c.db")
        open(path, "w").close()
        os.chmod(path, 0o644)
        c = SheetStructureCache(db_path=path, ttl=60, principal="drive:A")
        c.store("sid", [SheetInfo("X", 0)])
        assert c.get_sheets("sid")[0].title == "X"
        assert _mode(path) == 0o600

    @posix_only
    def test_legacy_tightening_survives_old_glibc(self, default_location, tmp_path, monkeypatch):
        legacy = str(tmp_path / "legacy.db")
        open(legacy, "w").close()
        os.chmod(legacy, 0o644)
        real_chmod = os.chmod

        def old_glibc_chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
            if not follow_symlinks:
                raise NotImplementedError
            return real_chmod(path, mode, dir_fd=dir_fd)

        monkeypatch.setattr(cache.os, "chmod", old_glibc_chmod)
        monkeypatch.setattr(cache, "_LEGACY_DB_PATH", legacy)
        monkeypatch.setattr(cache, "_legacy_db_checked", False)
        cache._open(default_location).close()
        assert _mode(legacy) == 0o600

    def test_legacy_db_is_deny_listed(self, monkeypatch):
        policy = local_files.resolve_policy(
            {**os.environ, "LOCAL_FILE_ACCESS": "full"}, ["mcp-gee-sweet"]
        )
        monkeypatch.setattr(local_files, "POLICY", policy)
        for suffix in ("", "-wal", "-shm"):
            with pytest.raises(LocalFileAccessError):
                local_files.check_read(cache._LEGACY_DB_PATH + suffix)

    async def test_invalidation_during_a_rebind_still_stops_the_in_flight_store(self):
        # The default CACHE_DB_PATH, which rebinding reopens.
        context = _context(principal="drive:A")
        held = context.cache

        class Sheets(FakeSheetsService):
            def execute(self, **kwargs):
                # A re-authorization to the same account, then a write tool's
                # invalidation on the new instance, both while this fetch is in flight.
                auth._bind_caches(context, "drive:A")
                context.cache.mark_dirty("sid")
                return {"sheets": [{"properties": {"title": "pre-write", "sheetId": 0}}]}

        await fetch_sheets(Sheets(), "sid", held)
        assert context.cache.get_sheets("sid") is None
        assert context.cache.invalidations is held.invalidations

    async def test_a_lifespan_context_opens_each_cache_once(self, monkeypatch):
        opened = []
        real_open = cache._open
        monkeypatch.setattr(cache, "_open", lambda path: opened.append(path) or real_open(path))
        monkeypatch.setattr(auth, "AUTH_METHOD", "service_account")
        services = {name: MagicMock() for name in auth._SERVICE_VERSIONS}
        services["drive"] = _drive_reporting("sa-perm")
        with (
            patch.object(auth, "_service_account_creds", return_value=_service_account_creds()),
            patch.object(auth, "_build_services", return_value=services),
        ):
            context = await auth._build_context()
        assert opened == []  # nothing until a cache is used
        for name in auth._CACHE_FIELDS:
            getattr(context, name).mark_all_dirty()
        assert len(opened) == 5

    def test_close_before_use_and_use_after_close(self, db):
        c = SheetStructureCache(db_path=db, ttl=60, principal="drive:A")
        c.close()
        c.store("sid", [SheetInfo("X", 0)])  # dropped, not raised
        assert c.get_sheets("sid") is None

    @posix_only
    def test_opened_log_names_the_memory_fallback(self, tmp_path, caplog):
        target = tmp_path / "target"
        target.write_text("")
        path = str(tmp_path / "c.db")
        os.symlink(target, path)
        caplog.set_level("DEBUG", logger="mcp_gee_sweet.cache")
        SheetStructureCache(db_path=path, ttl=60, principal="drive:A").mark_all_dirty()
        assert "sheet_structure cache opened: :memory:" in caplog.text
        assert f"cache opened: {path}" not in caplog.text
