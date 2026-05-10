import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CACHE_DB_PATH = os.environ.get("CACHE_DB_PATH", "/tmp/mcp_gee_sweet.db")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "1800"))  # 30 minutes

_DDL = """
CREATE TABLE IF NOT EXISTS cache (
    namespace  TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    dirty      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (namespace, key)
)
"""


def _open(db_path: str) -> sqlite3.Connection:
    # Each cache class holds its own connection to the same DB file. WAL mode lets
    # them read concurrently without blocking each other. All cache I/O is synchronous
    # on the asyncio event loop — acceptable at this scale; wrap in asyncio.to_thread()
    # if it ever shows up in profiling.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL)
    conn.commit()
    return conn


@dataclass
class SheetInfo:
    title: str
    sheet_id: int


class SheetStructureCache:
    _NS = "sheet_structure"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Sheet structure cache opened: %s", db_path)

    def _get_valid(self, spreadsheet_id: str) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, spreadsheet_id),
        ).fetchone()
        if row is None or row["dirty"]:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            logger.debug("Cache TTL expired for %s, marking dirty", spreadsheet_id)
            self._conn.execute(
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                (self._NS, spreadsheet_id),
            )
            self._conn.commit()
            return None
        return row

    def get_sheets(self, spreadsheet_id: str) -> list[SheetInfo] | None:
        """Returns cached sheet list, or None on cache miss/dirty/expired."""
        row = self._get_valid(spreadsheet_id)
        if row is None:
            return None
        return [SheetInfo(**s) for s in json.loads(row["value"])["sheets"]]

    def get_title(self, spreadsheet_id: str) -> str | None:
        """Returns cached spreadsheet title, or None on cache miss/dirty/expired."""
        row = self._get_valid(spreadsheet_id)
        if row is None:
            return None
        return json.loads(row["value"]).get("title")

    def store(self, spreadsheet_id: str, sheets: list[SheetInfo], title: str | None = None):
        value: dict = {"sheets": [{"title": s.title, "sheet_id": s.sheet_id} for s in sheets]}
        if title is not None:
            value["title"] = title
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, spreadsheet_id, json.dumps(value), time.time()),
        )
        self._conn.commit()
        logger.debug("Cached %d sheets for %s", len(sheets), spreadsheet_id)

    def mark_dirty(self, spreadsheet_id: str):
        self._conn.execute(
            "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
            (self._NS, spreadsheet_id),
        )
        self._conn.commit()
        logger.debug("Marked cache dirty for %s", spreadsheet_id)

    def mark_all_dirty(self):
        self._conn.execute("UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        self._conn.commit()
        logger.debug("Invalidated all sheet structure cache entries")


class SheetDataCache:
    """Caches per-sheet summary data (headers + first N rows) keyed by (spreadsheet_id, sheet_id)."""

    _NS = "sheet_data"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Sheet data cache opened: %s", db_path)

    def _key(self, spreadsheet_id: str, sheet_id: int) -> str:
        return f"{spreadsheet_id}:{sheet_id}"

    def _get_valid(
        self, spreadsheet_id: str, sheet_id: int, rows_to_fetch: int
    ) -> sqlite3.Row | None:
        key = self._key(spreadsheet_id, sheet_id)
        row = self._conn.execute(
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, key),
        ).fetchone()
        if row is None or row["dirty"]:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            self._conn.execute(
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, key)
            )
            self._conn.commit()
            return None
        if json.loads(row["value"]).get("rows_fetched", 0) < rows_to_fetch:
            return None
        return row

    def get(self, spreadsheet_id: str, sheet_id: int, rows_to_fetch: int) -> dict | None:
        """Returns cached {headers, first_rows}, or None on miss/dirty/expired/insufficient rows."""
        row = self._get_valid(spreadsheet_id, sheet_id, rows_to_fetch)
        if row is None:
            return None
        data = json.loads(row["value"])
        logger.debug("Sheet data cache hit: %s/%s", spreadsheet_id, sheet_id)
        return {
            "headers": data["headers"],
            "first_rows": data["first_rows"][: rows_to_fetch - 1],
        }

    def store(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        headers: list,
        first_rows: list,
        rows_to_fetch: int,
    ):
        value = {"headers": headers, "first_rows": first_rows, "rows_fetched": rows_to_fetch}
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, self._key(spreadsheet_id, sheet_id), json.dumps(value), time.time()),
        )
        self._conn.commit()
        logger.debug("Cached sheet data for %s/%s", spreadsheet_id, sheet_id)

    def mark_dirty(self, spreadsheet_id: str, sheet_id: int | None = None):
        if sheet_id is not None:
            self._conn.execute(
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                (self._NS, self._key(spreadsheet_id, sheet_id)),
            )
            logger.debug("Marked sheet data dirty for %s/%s", spreadsheet_id, sheet_id)
        else:
            self._conn.execute(
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key LIKE ?",
                (self._NS, f"{spreadsheet_id}:%"),
            )
            logger.debug("Marked all sheet data dirty for %s", spreadsheet_id)
        self._conn.commit()

    def mark_all_dirty(self):
        self._conn.execute("UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        self._conn.commit()
        logger.debug("Invalidated all sheet data cache entries")


class DriveFolderCache:
    """Caches Drive folder listings keyed by (folder_id, mime_type)."""

    _NS = "drive_folder"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Drive folder cache opened: %s", db_path)

    def _key(self, folder_id: str, mime_type: str | None) -> str:
        return f"{folder_id}:{mime_type or ''}"

    def _get_valid(self, folder_id: str, mime_type: str | None) -> sqlite3.Row | None:
        key = self._key(folder_id, mime_type)
        row = self._conn.execute(
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, key),
        ).fetchone()
        if row is None or row["dirty"]:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            self._conn.execute(
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, key)
            )
            self._conn.commit()
            return None
        return row

    def get(self, folder_id: str, mime_type: str | None) -> list | None:
        """Returns cached file list, or None on miss/dirty/expired."""
        row = self._get_valid(folder_id, mime_type)
        if row is None:
            return None
        logger.debug("Drive folder cache hit: %s (mime=%s)", folder_id, mime_type)
        return json.loads(row["value"])

    def store(self, folder_id: str, mime_type: str | None, files: list):
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, self._key(folder_id, mime_type), json.dumps(files), time.time()),
        )
        self._conn.commit()
        logger.debug("Cached %d files for folder %s (mime=%s)", len(files), folder_id, mime_type)

    def mark_dirty(self, folder_id: str):
        self._conn.execute(
            "UPDATE cache SET dirty=1 WHERE namespace=? AND key LIKE ?",
            (self._NS, f"{folder_id}:%"),
        )
        self._conn.commit()
        logger.debug("Marked drive folder cache dirty for %s", folder_id)

    def mark_all_dirty(self):
        self._conn.execute("UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        self._conn.commit()
        logger.debug("Invalidated all drive folder cache entries")


class DocContentCache:
    """Caches Google Doc content keyed by file_id."""

    _NS = "doc_content"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Doc cache opened: %s", db_path)

    def _get_valid(self, file_id: str) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, file_id),
        ).fetchone()
        if row is None or row["dirty"]:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            self._conn.execute(
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, file_id)
            )
            self._conn.commit()
            return None
        return row

    def get(self, file_id: str) -> dict | None:
        """Returns cached doc response dict, or None on miss/dirty/expired."""
        row = self._get_valid(file_id)
        if row is None:
            return None
        logger.debug("Doc cache hit: %s", file_id)
        return json.loads(row["value"])

    def store(self, file_id: str, doc: dict):
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, file_id, json.dumps(doc), time.time()),
        )
        self._conn.commit()
        logger.debug("Cached doc %s", file_id)

    def mark_dirty(self, file_id: str):
        self._conn.execute(
            "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
            (self._NS, file_id),
        )
        self._conn.commit()
        logger.debug("Marked doc cache dirty for %s", file_id)

    def mark_all_dirty(self):
        self._conn.execute("UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        self._conn.commit()
        logger.debug("Invalidated all doc cache entries")


def fetch_sheets(
    sheets_service: Any, spreadsheet_id: str, cache: SheetStructureCache
) -> list[SheetInfo]:
    """Fetch sheet list with caching. Falls back to stale cache if API call fails."""
    cached = cache.get_sheets(spreadsheet_id)
    if cached is not None:
        logger.debug("Cache hit: %d sheets for %s", len(cached), spreadsheet_id)
        return cached

    try:
        spreadsheet = (
            sheets_service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="properties.title,sheets(properties(title,sheetId))",
            )
            .execute()
        )
        sheets = [
            SheetInfo(title=s["properties"]["title"], sheet_id=s["properties"]["sheetId"])
            for s in spreadsheet.get("sheets", [])
        ]
        title = spreadsheet.get("properties", {}).get("title")
        cache.store(spreadsheet_id, sheets, title=title)
        return sheets
    except Exception as e:
        # Fall back to stale cache rather than hard-failing
        stale = cache._conn.execute(
            "SELECT value FROM cache WHERE namespace=? AND key=?",
            (SheetStructureCache._NS, spreadsheet_id),
        ).fetchone()
        if stale:
            logger.warning("API call failed for %s, serving stale cache: %s", spreadsheet_id, e)
            return [SheetInfo(**s) for s in json.loads(stale["value"])["sheets"]]
        raise
