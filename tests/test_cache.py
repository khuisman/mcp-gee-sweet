import time

from mcp_gee_sweet.cache import (
    DocContentCache,
    DriveFolderCache,
    SheetDataCache,
    SheetInfo,
    SheetStructureCache,
)

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


class TestDriveFolderCache:
    def setup_method(self):
        self.cache = DriveFolderCache(db_path=DB, ttl=60)
        self.files = [{"id": "f1", "name": "doc.docx"}]

    def test_miss_returns_none(self):
        assert self.cache.get("folder", None) is None

    def test_store_and_hit(self):
        self.cache.store("folder", None, self.files)
        result = self.cache.get("folder", None)
        assert result == self.files

    def test_mime_type_differentiates_keys(self):
        self.cache.store("folder", "application/pdf", [{"id": "pdf"}])
        self.cache.store("folder", None, [{"id": "all"}])
        assert self.cache.get("folder", "application/pdf") == [{"id": "pdf"}]
        assert self.cache.get("folder", None) == [{"id": "all"}]

    def test_dirty_flag_causes_miss(self):
        self.cache.store("folder", None, self.files)
        self.cache.mark_dirty("folder")
        assert self.cache.get("folder", None) is None

    def test_mark_dirty_invalidates_all_mime_types_for_folder(self):
        self.cache.store("folder", None, self.files)
        self.cache.store("folder", "image/png", [{"id": "img"}])
        self.cache.mark_dirty("folder")
        assert self.cache.get("folder", None) is None
        assert self.cache.get("folder", "image/png") is None

    def test_mark_dirty_leaves_other_folder_intact(self):
        self.cache.store("f1", None, self.files)
        self.cache.store("f2", None, [{"id": "other"}])
        self.cache.mark_dirty("f1")
        assert self.cache.get("f1", None) is None
        assert self.cache.get("f2", None) is not None

    def test_mark_all_dirty(self):
        self.cache.store("f1", None, self.files)
        self.cache.store("f2", None, self.files)
        self.cache.mark_all_dirty()
        assert self.cache.get("f1", None) is None
        assert self.cache.get("f2", None) is None

    def test_ttl_expiry(self):
        cache = DriveFolderCache(db_path=DB, ttl=0)
        cache.store("folder", None, self.files)
        time.sleep(0.01)
        assert cache.get("folder", None) is None


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
