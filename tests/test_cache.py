import os
import sqlite3
import time
from types import SimpleNamespace

from mcp_gee_sweet.cache import (
    CalendarCache,
    DocContentCache,
    DriveFolderCache,
    SheetDataCache,
    SheetInfo,
    SheetStructureCache,
    _env_flag,
    _open,
    _safe_fetchone,
    _safe_write,
    fetch_sheets,
    get_modified_time,
)
from mcp_gee_sweet.tools.sheets.helpers import _get_sheet_id

# All tests use an in-memory SQLite database.
DB = ":memory:"


class TestSheetStructureCache:
    def setup_method(self):
        self.cache = SheetStructureCache(db_path=DB, ttl=60)
        self.sheets = [SheetInfo(title="Sheet1", sheet_id=0), SheetInfo(title="Sheet2", sheet_id=1)]

    def test_miss_returns_none(self):
        assert self.cache.get_sheets("nonexistent") is None

    def test_store_and_hit(self):
        self.cache.store("sid", self.sheets)
        result = self.cache.get_sheets("sid")
        assert result is not None
        assert len(result) == 2
        assert result[0].title == "Sheet1"

    def test_title_stored_and_retrieved(self):
        self.cache.store("sid", self.sheets, title="My Sheet")
        assert self.cache.get_title("sid") == "My Sheet"

    def test_title_none_when_not_stored(self):
        self.cache.store("sid", self.sheets)
        assert self.cache.get_title("sid") is None

    def test_dirty_flag_causes_miss(self):
        self.cache.store("sid", self.sheets)
        self.cache.mark_dirty("sid")
        assert self.cache.get_sheets("sid") is None

    def test_mark_all_dirty(self):
        self.cache.store("a", self.sheets)
        self.cache.store("b", self.sheets)
        self.cache.mark_all_dirty()
        assert self.cache.get_sheets("a") is None
        assert self.cache.get_sheets("b") is None

    def test_ttl_expiry(self):
        cache = SheetStructureCache(db_path=DB, ttl=0)  # TTL of 0 expires immediately
        cache.store("sid", self.sheets)
        time.sleep(0.01)
        assert cache.get_sheets("sid") is None

    def test_restore_after_dirty(self):
        self.cache.store("sid", self.sheets)
        self.cache.mark_dirty("sid")
        new_sheets = [SheetInfo(title="NewSheet", sheet_id=99)]
        self.cache.store("sid", new_sheets)
        result = self.cache.get_sheets("sid")
        assert result is not None
        assert result[0].title == "NewSheet"

    def test_get_stale_sheets_ignores_dirty(self):
        self.cache.store("sid", self.sheets)
        self.cache.mark_dirty("sid")
        result = self.cache.get_stale_sheets("sid")
        assert result is not None
        assert result[0].title == "Sheet1"

    def test_get_stale_sheets_miss_returns_none(self):
        assert self.cache.get_stale_sheets("nonexistent") is None

    def test_store_with_stale_epoch_is_skipped(self):
        """Regression test (QA finding, #183): a concurrent mark_dirty() (e.g. from
        refresh_cache()) landing while a fetch is in flight must not be silently
        undone by that fetch's store() call once it completes — this couldn't
        happen before tool calls were async (no await point existed for another
        call to interleave), so it's a race newly possible under concurrency."""
        epoch = self.cache.snapshot_epoch()
        self.cache.mark_dirty("sid")  # simulates a concurrent invalidation mid-fetch
        self.cache.store("sid", self.sheets, epoch=epoch)
        assert self.cache.get_sheets("sid") is None

    def test_store_with_current_epoch_succeeds(self):
        """Sanity check: an unstale epoch (no invalidation happened) still writes."""
        epoch = self.cache.snapshot_epoch()
        self.cache.store("sid", self.sheets, epoch=epoch)
        assert self.cache.get_sheets("sid") is not None

    def test_close(self):
        self.cache.close()

    def test_set_ttl_shortens_window_for_existing_entry(self):
        self.cache.store("sid", self.sheets)
        self.cache.set_ttl(0)
        time.sleep(0.01)
        assert self.cache.get_sheets("sid") is None

    def test_set_ttl_lengthens_window(self):
        # ttl=0 would expire on the first lookup, but expiry is only evaluated
        # (and the row marked dirty) inside a read — raising the TTL before any
        # read happens keeps the entry alive.
        cache = SheetStructureCache(db_path=DB, ttl=0)
        cache.store("sid", self.sheets)
        cache.set_ttl(60)
        assert cache.get_sheets("sid") is not None

    def test_modified_time_mismatch_causes_miss(self):
        self.cache.store("sid", self.sheets, modified_time="2026-01-01T00:00:00Z")
        result = self.cache.get_sheets("sid", current_modified_time="2026-02-01T00:00:00Z")
        assert result is None

    def test_modified_time_match_hits(self):
        self.cache.store("sid", self.sheets, modified_time="2026-01-01T00:00:00Z")
        result = self.cache.get_sheets("sid", current_modified_time="2026-01-01T00:00:00Z")
        assert result is not None

    def test_no_stored_modified_time_skips_check(self):
        # Entries stored before this feature (or without a drive_service) have no
        # modified_time recorded — comparison must not spuriously invalidate them.
        self.cache.store("sid", self.sheets)
        result = self.cache.get_sheets("sid", current_modified_time="2026-01-01T00:00:00Z")
        assert result is not None

    def test_modified_time_mismatch_marks_dirty(self):
        self.cache.store("sid", self.sheets, modified_time="2026-01-01T00:00:00Z")
        self.cache.get_sheets("sid", current_modified_time="2026-02-01T00:00:00Z")
        # Even a plain lookup (no current_modified_time) now misses, since the
        # stale-detection path marks the row dirty rather than just skipping it.
        assert self.cache.get_sheets("sid") is None

    def test_title_modified_time_check(self):
        self.cache.store("sid", self.sheets, title="T1", modified_time="2026-01-01T00:00:00Z")
        assert self.cache.get_title("sid", current_modified_time="2026-01-01T00:00:00Z") == "T1"
        assert self.cache.get_title("sid", current_modified_time="2026-02-01T00:00:00Z") is None


class TestSheetDataCache:
    def setup_method(self):
        self.cache = SheetDataCache(db_path=DB, ttl=60)

    def test_miss_returns_none(self):
        assert self.cache.get("sid", 0, 10) is None

    def test_store_and_hit(self):
        self.cache.store("sid", 0, headers=["A", "B"], first_rows=[["1", "2"]], rows_to_fetch=5)
        result = self.cache.get("sid", 0, 5)
        assert result is not None
        assert result["headers"] == ["A", "B"]

    def test_insufficient_rows_causes_miss(self):
        self.cache.store("sid", 0, headers=["A"], first_rows=[["x"]], rows_to_fetch=3)
        assert self.cache.get("sid", 0, 10) is None

    def test_sufficient_rows_hits(self):
        self.cache.store("sid", 0, headers=["A"], first_rows=[["x"] * 9], rows_to_fetch=10)
        assert self.cache.get("sid", 0, 5) is not None

    def test_rows_to_fetch_zero_clamps_on_warm_cache(self):
        # issue #254: rows_to_fetch=0 must return no rows on a warm cache too,
        # matching the max(1, rows_to_fetch) clamp the cold-cache fetch path applies.
        self.cache.store("sid", 0, headers=["A"], first_rows=[["x"], ["y"], ["z"]], rows_to_fetch=5)
        result = self.cache.get("sid", 0, 0)
        assert result is not None
        assert result["first_rows"] == []

    def test_dirty_flag_causes_miss(self):
        self.cache.store("sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1)
        self.cache.mark_dirty("sid", sheet_id=0)
        assert self.cache.get("sid", 0, 1) is None

    def test_mark_dirty_all_sheets_for_spreadsheet(self):
        self.cache.store("sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1)
        self.cache.store("sid", 1, headers=["B"], first_rows=[], rows_to_fetch=1)
        self.cache.mark_dirty("sid")  # no sheet_id → mark all for that spreadsheet
        assert self.cache.get("sid", 0, 1) is None
        assert self.cache.get("sid", 1, 1) is None

    def test_mark_dirty_one_sheet_leaves_other_intact(self):
        self.cache.store("sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1)
        self.cache.store("sid", 1, headers=["B"], first_rows=[], rows_to_fetch=1)
        self.cache.mark_dirty("sid", sheet_id=0)
        assert self.cache.get("sid", 0, 1) is None
        assert self.cache.get("sid", 1, 1) is not None

    def test_mark_all_dirty(self):
        self.cache.store("a", 0, headers=[], first_rows=[], rows_to_fetch=1)
        self.cache.store("b", 0, headers=[], first_rows=[], rows_to_fetch=1)
        self.cache.mark_all_dirty()
        assert self.cache.get("a", 0, 1) is None
        assert self.cache.get("b", 0, 1) is None

    def test_ttl_expiry(self):
        cache = SheetDataCache(db_path=DB, ttl=0)
        cache.store("sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1)
        time.sleep(0.01)
        assert cache.get("sid", 0, 1) is None

    def test_partial_invalidation_leaves_other_spreadsheet_intact(self):
        self.cache.store("sid1", 0, headers=["A"], first_rows=[], rows_to_fetch=1)
        self.cache.store("sid2", 0, headers=["B"], first_rows=[], rows_to_fetch=1)
        self.cache.mark_dirty("sid1")
        assert self.cache.get("sid1", 0, 1) is None
        assert self.cache.get("sid2", 0, 1) is not None

    def test_set_ttl_shortens_window_for_existing_entry(self):
        self.cache.store("sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1)
        self.cache.set_ttl(0)
        time.sleep(0.01)
        assert self.cache.get("sid", 0, 1) is None

    def test_modified_time_mismatch_causes_miss(self):
        self.cache.store(
            "sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1, modified_time="v1"
        )
        assert self.cache.get("sid", 0, 1, current_modified_time="v2") is None

    def test_modified_time_match_hits(self):
        self.cache.store(
            "sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1, modified_time="v1"
        )
        result = self.cache.get("sid", 0, 1, current_modified_time="v1")
        assert result is not None
        assert result["headers"] == ["A"]

    def test_store_with_stale_epoch_is_skipped(self):
        """Same epoch-guard mechanism as SheetStructureCache — see that class's
        test_store_with_stale_epoch_is_skipped for the full rationale."""
        epoch = self.cache.snapshot_epoch()
        self.cache.mark_dirty("sid", sheet_id=0)
        self.cache.store("sid", 0, headers=["A"], first_rows=[], rows_to_fetch=1, epoch=epoch)
        assert self.cache.get("sid", 0, 1) is None

    def test_close(self):
        self.cache.close()


class TestDriveFolderCache:
    def setup_method(self):
        self.cache = DriveFolderCache(db_path=DB, ttl=60)
        self.files = [{"id": "f1", "name": "doc.docx"}]

    def test_miss_returns_none(self):
        assert self.cache.get("folder", None, 100) is None

    def test_store_and_hit(self):
        self.cache.store("folder", None, self.files, 100)
        result = self.cache.get("folder", None, 100)
        assert result == self.files

    def test_mime_type_differentiates_keys(self):
        self.cache.store("folder", "application/pdf", [{"id": "pdf"}], 100)
        self.cache.store("folder", None, [{"id": "all"}], 100)
        assert self.cache.get("folder", "application/pdf", 100) == [{"id": "pdf"}]
        assert self.cache.get("folder", None, 100) == [{"id": "all"}]

    def test_dirty_flag_causes_miss(self):
        self.cache.store("folder", None, self.files, 100)
        self.cache.mark_dirty("folder")
        assert self.cache.get("folder", None, 100) is None

    def test_mark_dirty_invalidates_all_mime_types_for_folder(self):
        self.cache.store("folder", None, self.files, 100)
        self.cache.store("folder", "image/png", [{"id": "img"}], 100)
        self.cache.mark_dirty("folder")
        assert self.cache.get("folder", None, 100) is None
        assert self.cache.get("folder", "image/png", 100) is None

    def test_mark_dirty_leaves_other_folder_intact(self):
        self.cache.store("f1", None, self.files, 100)
        self.cache.store("f2", None, [{"id": "other"}], 100)
        self.cache.mark_dirty("f1")
        assert self.cache.get("f1", None, 100) is None
        assert self.cache.get("f2", None, 100) is not None

    def test_mark_all_dirty(self):
        self.cache.store("f1", None, self.files, 100)
        self.cache.store("f2", None, self.files, 100)
        self.cache.mark_all_dirty()
        assert self.cache.get("f1", None, 100) is None
        assert self.cache.get("f2", None, 100) is None

    def test_ttl_expiry(self):
        cache = DriveFolderCache(db_path=DB, ttl=0)
        cache.store("folder", None, self.files, 100)
        time.sleep(0.01)
        assert cache.get("folder", None, 100) is None

    def test_set_ttl_shortens_window_for_existing_entry(self):
        self.cache.store("folder", None, self.files, 100)
        self.cache.set_ttl(0)
        time.sleep(0.01)
        assert self.cache.get("folder", None, 100) is None

    def test_close(self):
        self.cache.close()

    def test_smaller_max_results_request_does_not_ignore_its_own_limit(self):
        # issue #688 bug 1: a cached larger fetch must be sliced down, not
        # returned unsliced and over the caller's own requested limit.
        five_files = [{"id": f"f{i}"} for i in range(5)]
        self.cache.store("folder", None, five_files, 100)
        result = self.cache.get("folder", None, 2)
        assert result == five_files[:2]

    def test_larger_max_results_request_after_smaller_cached_fetch_is_a_miss(self):
        # issue #688 bug 2: a small-max_results fetch must not poison the
        # cache for a later, larger request — that's a miss, not a truncated hit.
        self.cache.store("folder", None, [{"id": "f0"}, {"id": "f1"}], 2)
        assert self.cache.get("folder", None, 100) is None

    def test_sufficient_prior_fetch_size_hits_and_slices(self):
        five_files = [{"id": f"f{i}"} for i in range(5)]
        self.cache.store("folder", None, five_files, 10)
        assert self.cache.get("folder", None, 5) == five_files


class TestDocContentCache:
    def setup_method(self):
        self.cache = DocContentCache(db_path=DB, ttl=60)
        self.doc = {"title": "My Doc", "body": {"content": []}}

    def test_miss_returns_none(self):
        assert self.cache.get("file_id") is None

    def test_store_and_hit(self):
        self.cache.store("fid", self.doc)
        assert self.cache.get("fid") == self.doc

    def test_dirty_flag_causes_miss(self):
        self.cache.store("fid", self.doc)
        self.cache.mark_dirty("fid")
        assert self.cache.get("fid") is None

    def test_mark_all_dirty(self):
        self.cache.store("a", self.doc)
        self.cache.store("b", self.doc)
        self.cache.mark_all_dirty()
        assert self.cache.get("a") is None
        assert self.cache.get("b") is None

    def test_ttl_expiry(self):
        cache = DocContentCache(db_path=DB, ttl=0)
        cache.store("fid", self.doc)
        time.sleep(0.01)
        assert cache.get("fid") is None

    def test_restore_overwrites_stale(self):
        self.cache.store("fid", self.doc)
        self.cache.mark_dirty("fid")
        new_doc = {"title": "Updated"}
        self.cache.store("fid", new_doc)
        assert self.cache.get("fid") == new_doc

    def test_set_ttl_shortens_window_for_existing_entry(self):
        self.cache.store("fid", self.doc)
        self.cache.set_ttl(0)
        time.sleep(0.01)
        assert self.cache.get("fid") is None

    def test_modified_time_mismatch_causes_miss(self):
        # get_doc_content stores modified_time as part of the cached doc dict
        # itself — no separate column needed.
        doc = {"title": "My Doc", "modified_time": "v1"}
        self.cache.store("fid", doc)
        assert self.cache.get("fid", current_modified_time="v2") is None

    def test_modified_time_match_hits(self):
        doc = {"title": "My Doc", "modified_time": "v1"}
        self.cache.store("fid", doc)
        assert self.cache.get("fid", current_modified_time="v1") == doc

    def test_close(self):
        self.cache.close()


class TestGetModifiedTime:
    async def test_none_drive_service_returns_none(self):
        assert await get_modified_time(None, "fid") is None

    async def test_returns_modified_time_on_success(self):
        class FakeFiles:
            def get(self, fileId, fields, supportsAllDrives):
                class FakeRequest:
                    def execute(self, **kwargs):
                        return {"modifiedTime": "2026-01-01T00:00:00Z"}

                return FakeRequest()

        class FakeDriveService:
            _http = SimpleNamespace(credentials=None)

            def files(self):
                return FakeFiles()

        assert await get_modified_time(FakeDriveService(), "fid") == "2026-01-01T00:00:00Z"

    async def test_returns_none_on_api_error(self):
        class FakeFiles:
            def get(self, fileId, fields, supportsAllDrives):
                raise Exception("API error")

        class FakeDriveService:
            _http = SimpleNamespace(credentials=None)

            def files(self):
                return FakeFiles()

        assert await get_modified_time(FakeDriveService(), "fid") is None


class TestEnvFlag:
    """CACHE_VALIDATE_MODIFIED_TIME uses an allowlist of truthy values, not a
    denylist of falsy ones — an unrecognized/misspelled value like "off" or
    "disabled" must fall back to disabled, not silently stay enabled."""

    def test_recognized_truthy_values(self, monkeypatch):
        for value in ("true", "TRUE", "1", "yes", "y", "on", " True "):
            monkeypatch.setenv("TEST_FLAG", value)
            assert _env_flag("TEST_FLAG", "false") is True, value

    def test_recognized_falsy_and_unrecognized_values(self, monkeypatch):
        for value in ("false", "0", "no", "off", "disabled", "banana"):
            monkeypatch.setenv("TEST_FLAG", value)
            assert _env_flag("TEST_FLAG", "true") is False, value

    def test_uses_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_FLAG", raising=False)
        assert _env_flag("TEST_FLAG", "true") is True
        assert _env_flag("TEST_FLAG", "false") is False


class TestCalendarCacheSetTtl:
    def test_set_ttl_shortens_window_for_existing_entry(self):
        cache = CalendarCache(db_path=DB, ttl=60)
        cache.store_list([{"id": "cal1"}])
        cache.set_ttl(0)
        time.sleep(0.01)
        assert cache.get_list() is None

    def test_get_ttl_returns_current_value(self):
        cache = CalendarCache(db_path=DB, ttl=60)
        assert cache.get_ttl() == 60
        cache.set_ttl(5)
        assert cache.get_ttl() == 5


class _FakeSheetsService:
    """Returns a spreadsheet with a single sheet named 'New', id 1."""

    _http = SimpleNamespace(credentials=None)

    class _Spreadsheets:
        class _Request:
            def execute(self, **kwargs):
                return {
                    "properties": {"title": "New Title"},
                    "sheets": [{"properties": {"title": "New", "sheetId": 1}}],
                }

        def get(self, spreadsheetId, fields):
            return self._Request()

    def spreadsheets(self):
        return self._Spreadsheets()


class _FakeDriveService:
    """Reports modifiedTime='v2' for any file."""

    _http = SimpleNamespace(credentials=None)

    class _Files:
        class _Request:
            def execute(self, **kwargs):
                return {"modifiedTime": "v2"}

        def get(self, fileId, fields, supportsAllDrives):
            return self._Request()

    def files(self):
        return self._Files()


class TestFetchSheetsModifiedTimeValidation:
    async def test_stale_cache_triggers_refetch_when_drive_service_given(self):
        cache = SheetStructureCache(db_path=DB, ttl=1000)
        cache.store("sid", [SheetInfo(title="Old", sheet_id=0)], modified_time="v1")

        result = await fetch_sheets(_FakeSheetsService(), "sid", cache, _FakeDriveService())

        assert len(result) == 1
        assert result[0].title == "New"

    async def test_fresh_cache_skipped_refetch_without_drive_service(self):
        cache = SheetStructureCache(db_path=DB, ttl=1000)
        cache.store("sid", [SheetInfo(title="Old", sheet_id=0)], modified_time="v1")

        # No drive_service passed → no modifiedTime check → TTL-valid cache hit,
        # even though _FakeSheetsService would return a different sheet.
        result = await fetch_sheets(_FakeSheetsService(), "sid", cache)

        assert result[0].title == "Old"


class TestGetSheetIdModifiedTimePropagation:
    """Regression test (issue #99 review): _get_sheet_id is the sheet-name-to-ID
    resolver used by ~11 write-path tools (add_rows, format_cells, rename_sheet,
    etc.), all sharing the same SheetStructureCache row per spreadsheet_id as the
    read-path tools (list_sheets, find_in_spreadsheet). It originally called
    fetch_sheets() without drive_service, so any write-path lookup that missed
    the cache re-stored the row with modified_time absent from the JSON value —
    silently disabling staleness detection for every subsequent reader of that
    spreadsheet, since a None-vs-anything comparison always skips the check.
    """

    async def test_write_path_lookup_refreshes_modified_time_tag_on_miss(self):
        cache = SheetStructureCache(db_path=DB, ttl=1000)
        cache.store("sid", [SheetInfo(title="Old", sheet_id=0)], modified_time="v1")
        cache.mark_dirty("sid")  # force the next lookup to be a genuine miss

        sheet_id = await _get_sheet_id(
            _FakeSheetsService(), "sid", "New", cache, _FakeDriveService()
        )

        assert sheet_id == 1
        # The row was re-stored with a real modified_time ("v2", from
        # _FakeDriveService) rather than silently omitting the key.
        assert cache.get_sheets("sid", current_modified_time="v2") is not None
        # A later genuine edit (v3) is still detected — the exact capability this
        # bug defeated when drive_service wasn't threaded through.
        assert cache.get_sheets("sid", current_modified_time="v3") is None


class TestSharedDb:
    """Verify that multiple cache instances pointing to the same DB file share state.

    Each cache class opens its own connection; WAL mode must allow cross-connection
    visibility of writes within the same process.
    """

    def test_two_connections_share_writes(self, tmp_path):
        db = str(tmp_path / "shared.db")
        writer = SheetStructureCache(db_path=db, ttl=60)
        reader = SheetStructureCache(db_path=db, ttl=60)
        sheets = [SheetInfo(title="S1", sheet_id=0)]
        writer.store("sid", sheets)
        result = reader.get_sheets("sid")
        assert result is not None
        assert result[0].title == "S1"

    def test_dirty_from_one_connection_seen_by_other(self, tmp_path):
        db = str(tmp_path / "shared.db")
        a = SheetStructureCache(db_path=db, ttl=60)
        b = SheetStructureCache(db_path=db, ttl=60)
        a.store("sid", [SheetInfo(title="X", sheet_id=0)])
        b.mark_dirty("sid")
        assert a.get_sheets("sid") is None

    def test_different_namespaces_coexist(self, tmp_path):
        db = str(tmp_path / "shared.db")
        struct = SheetStructureCache(db_path=db, ttl=60)
        doc = DocContentCache(db_path=db, ttl=60)
        struct.store("sid", [SheetInfo(title="T", sheet_id=0)])
        doc.store("fid", {"title": "Doc"})
        struct.mark_all_dirty()
        assert struct.get_sheets("sid") is None
        assert doc.get("fid") is not None  # different namespace, unaffected


class TestBusyTimeout:
    """issue #234: a busy_timeout must be set so a concurrent writer from another
    session waits instead of raising SQLITE_BUSY immediately."""

    def test_busy_timeout_is_set(self, tmp_path):
        db = str(tmp_path / "test.db")
        conn = _open(db)
        try:
            (value,) = conn.execute("PRAGMA busy_timeout").fetchone()
            assert value == 5000
        finally:
            conn.close()


class TestFailOpenOnSqliteError:
    """issue #234: a cache read/write must never crash a tool call — any sqlite
    error (locked/corrupted DB from another session) is treated as a cache miss
    on reads and silently dropped on writes."""

    def test_safe_fetchone_returns_none_on_error(self):
        conn = sqlite3.connect(":memory:")
        conn.close()  # any operation on a closed connection raises sqlite3.ProgrammingError
        assert _safe_fetchone(conn, "SELECT 1", ()) is None

    def test_safe_write_swallows_error(self):
        conn = sqlite3.connect(":memory:")
        conn.close()
        _safe_write(conn, "SELECT 1", ())  # must not raise

    def test_cache_get_survives_closed_connection(self):
        cache = SheetStructureCache(db_path=":memory:", ttl=60)
        cache.store("sid", [SheetInfo(title="S1", sheet_id=0)])
        cache._conn.close()
        assert cache.get_sheets("sid") is None

    def test_cache_store_survives_closed_connection(self):
        cache = SheetStructureCache(db_path=":memory:", ttl=60)
        cache._conn.close()
        cache.store("sid", [SheetInfo(title="S1", sheet_id=0)])  # must not raise

    def test_mark_dirty_survives_closed_connection(self):
        cache = SheetStructureCache(db_path=":memory:", ttl=60)
        cache._conn.close()
        cache.mark_dirty("sid")  # must not raise

    def test_mark_all_dirty_survives_closed_connection(self):
        cache = SheetStructureCache(db_path=":memory:", ttl=60)
        cache._conn.close()
        cache.mark_all_dirty()  # must not raise

    def test_doc_cache_get_survives_closed_connection(self):
        cache = DocContentCache(db_path=":memory:", ttl=60)
        cache.store("fid", {"title": "Doc"})
        cache._conn.close()
        assert cache.get("fid") is None


class TestOpenFallback:
    """_open() must survive a read-only or corrupted DB file without crashing."""

    def test_readonly_file_deleted_and_retried(self, tmp_path):
        # chmod 444 on the file — WAL pragma can't write, triggers OperationalError.
        # Directory is still writable, so deletion succeeds and retry creates a fresh DB.
        db = str(tmp_path / "test.db")
        open(db, "w").close()
        os.chmod(db, 0o444)
        try:
            conn = _open(db)
            conn.execute("SELECT 1").fetchone()
            conn.close()
            # Retry succeeded — fresh file was created (not memory fallback)
            assert os.path.exists(db)
        finally:
            os.chmod(db, 0o644)

    def test_readonly_dir_falls_back_to_memory(self, tmp_path):
        # chmod 444 on the directory — both the initial open and the retry fail,
        # so _open must return a working :memory: connection without raising.
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        db = str(ro_dir / "test.db")
        os.chmod(str(ro_dir), 0o444)
        try:
            conn = _open(db)
            conn.execute("SELECT 1").fetchone()
            conn.close()
        finally:
            os.chmod(str(ro_dir), 0o755)

    def test_memory_fallback_cache_is_functional(self, tmp_path):
        # Full end-to-end: cache object backed by :memory: must store and retrieve.
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        db = str(ro_dir / "test.db")
        os.chmod(str(ro_dir), 0o444)
        try:
            cache = SheetStructureCache(db_path=db, ttl=60)
            sheets = [SheetInfo(title="S1", sheet_id=0)]
            cache.store("sid", sheets)
            result = cache.get_sheets("sid")
            assert result is not None
            assert result[0].title == "S1"
        finally:
            os.chmod(str(ro_dir), 0o755)
