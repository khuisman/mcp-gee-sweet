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
# When enabled, a cache hit for sheet structure/data or doc content is validated
# against the source file's Drive modifiedTime before being served, so edits from
# other users/tabs are picked up without waiting out the TTL. Costs one extra
# Drive API call per cache lookup — disable if that overhead outweighs the benefit.
CACHE_VALIDATE_MODIFIED_TIME = os.environ.get(
    "CACHE_VALIDATE_MODIFIED_TIME", "true"
).lower() not in (
    "false",
    "0",
    "no",
)

_DDL = """
CREATE TABLE IF NOT EXISTS cache (
    namespace    TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    fetched_at   REAL NOT NULL,
    dirty        INTEGER NOT NULL DEFAULT 0,
    rows_fetched INTEGER,
    PRIMARY KEY (namespace, key)
)
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Concurrent Claude sessions share this DB file by default; without a busy_timeout
    # a write from another session hits SQLITE_BUSY immediately instead of waiting.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(_DDL)
    conn.commit()
    return conn


def _open(db_path: str) -> sqlite3.Connection:
    # Each cache class holds its own connection to the same DB file. WAL mode lets
    # them read concurrently without blocking each other. All cache I/O is synchronous
    # on the asyncio event loop — acceptable at this scale; wrap in asyncio.to_thread()
    # if it ever shows up in profiling.
    try:
        return _connect(db_path)
    except sqlite3.OperationalError as exc:
        # Stale/read-only/corrupted files (e.g. left by Docker with wrong perms).
        # Try deleting and recreating; if that also fails, fall back to :memory:.
        if db_path != ":memory:":
            for suffix in ("", "-shm", "-wal"):
                path = db_path + suffix
                try:
                    os.remove(path)
                except OSError:
                    pass
            logger.warning("Cache file unusable (%s), deleted and retrying: %s", exc, db_path)
            try:
                return _connect(db_path)
            except sqlite3.OperationalError as exc2:
                logger.warning("Cache file still unusable (%s), falling back to :memory:", exc2)
        else:
            logger.warning("In-memory cache failed to initialise (%s)", exc)
        return _connect(":memory:")


def _safe_fetchone(conn: sqlite3.Connection, sql: str, params: tuple) -> sqlite3.Row | None:
    """Run a SELECT and fetchone(), treating any sqlite error as a cache miss.

    Another session's crash can leave a locked/corrupted WAL behind; a cache read
    should never take down a tool call over it (fail open, same as the API-fetch
    fallback in fetch_sheets()).
    """
    try:
        return conn.execute(sql, params).fetchone()
    except sqlite3.Error as exc:
        logger.warning("Cache read failed (%s), treating as cache miss", exc)
        return None


def _safe_write(conn: sqlite3.Connection, sql: str, params: tuple) -> None:
    """Run a write statement + commit, swallowing sqlite errors (fail-open cache write).

    A failed cache write must not fail the tool call that already succeeded against
    the underlying Google API — it just means that result won't be cached this time.
    """
    try:
        conn.execute(sql, params)
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("Cache write failed (%s), continuing without caching", exc)


def get_modified_time(drive_service: Any, file_id: str) -> str | None:
    """Fetch a Drive file's modifiedTime, or None if unavailable/on any failure.

    Used to validate a cache hit against the live source before serving it —
    a lightweight `fields=modifiedTime`-only call, distinct from the full
    metadata fetch a cache miss triggers.
    """
    if drive_service is None:
        return None
    try:
        meta = (
            drive_service.files()
            .get(fileId=file_id, fields="modifiedTime", supportsAllDrives=True)
            .execute()
        )
        return meta.get("modifiedTime")
    except Exception as e:
        logger.debug("Could not fetch modifiedTime for %s: %s", file_id, e)
        return None


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

    def _get_valid(
        self, spreadsheet_id: str, current_modified_time: str | None = None
    ) -> sqlite3.Row | None:
        row = _safe_fetchone(
            self._conn,
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, spreadsheet_id),
        )
        if row is None or row["dirty"]:
            return None
        if current_modified_time is not None:
            cached_mtime = json.loads(row["value"]).get("modified_time")
            if cached_mtime is not None and cached_mtime != current_modified_time:
                logger.debug("Source modified since cache for %s, marking dirty", spreadsheet_id)
                _safe_write(
                    self._conn,
                    "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                    (self._NS, spreadsheet_id),
                )
                return None
        if time.time() - row["fetched_at"] > self._ttl:
            logger.debug("Cache TTL expired for %s, marking dirty", spreadsheet_id)
            _safe_write(
                self._conn,
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                (self._NS, spreadsheet_id),
            )
            return None
        return row

    def get_sheets(
        self, spreadsheet_id: str, current_modified_time: str | None = None
    ) -> list[SheetInfo] | None:
        """Returns cached sheet list, or None on cache miss/dirty/expired/stale-vs-source."""
        row = self._get_valid(spreadsheet_id, current_modified_time)
        if row is None:
            return None
        return [SheetInfo(**s) for s in json.loads(row["value"])["sheets"]]

    def get_title(
        self, spreadsheet_id: str, current_modified_time: str | None = None
    ) -> str | None:
        """Returns cached spreadsheet title, or None on cache miss/dirty/expired/stale-vs-source."""
        row = self._get_valid(spreadsheet_id, current_modified_time)
        if row is None:
            return None
        return json.loads(row["value"]).get("title")

    def store(
        self,
        spreadsheet_id: str,
        sheets: list[SheetInfo],
        title: str | None = None,
        modified_time: str | None = None,
    ):
        value: dict = {"sheets": [{"title": s.title, "sheet_id": s.sheet_id} for s in sheets]}
        if title is not None:
            value["title"] = title
        if modified_time is not None:
            value["modified_time"] = modified_time
        _safe_write(
            self._conn,
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, spreadsheet_id, json.dumps(value), time.time()),
        )
        logger.debug("Cached %d sheets for %s", len(sheets), spreadsheet_id)

    def set_ttl(self, ttl: int) -> None:
        self._ttl = ttl

    def mark_dirty(self, spreadsheet_id: str):
        _safe_write(
            self._conn,
            "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
            (self._NS, spreadsheet_id),
        )
        logger.debug("Marked cache dirty for %s", spreadsheet_id)

    def mark_all_dirty(self):
        _safe_write(self._conn, "UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        logger.debug("Invalidated all sheet structure cache entries")

    def get_stale_sheets(self, spreadsheet_id: str) -> list[SheetInfo] | None:
        """Returns cached sheet list regardless of dirty/TTL state; None only on complete miss."""
        row = _safe_fetchone(
            self._conn,
            "SELECT value FROM cache WHERE namespace=? AND key=?",
            (self._NS, spreadsheet_id),
        )
        if row is None:
            return None
        return [SheetInfo(**s) for s in json.loads(row["value"])["sheets"]]

    def close(self):
        self._conn.close()


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
        self,
        spreadsheet_id: str,
        sheet_id: int,
        rows_to_fetch: int,
        current_modified_time: str | None = None,
    ) -> sqlite3.Row | None:
        key = self._key(spreadsheet_id, sheet_id)
        row = _safe_fetchone(
            self._conn,
            "SELECT value, fetched_at, dirty, rows_fetched FROM cache WHERE namespace=? AND key=?",
            (self._NS, key),
        )
        if row is None or row["dirty"]:
            return None
        if current_modified_time is not None:
            cached_mtime = json.loads(row["value"]).get("modified_time")
            if cached_mtime is not None and cached_mtime != current_modified_time:
                logger.debug("Source modified since cache for %s, marking dirty", key)
                _safe_write(
                    self._conn,
                    "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                    (self._NS, key),
                )
                return None
        if time.time() - row["fetched_at"] > self._ttl:
            _safe_write(
                self._conn, "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, key)
            )
            return None
        if (row["rows_fetched"] or 0) < rows_to_fetch:
            return None
        return row

    def get(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        rows_to_fetch: int,
        current_modified_time: str | None = None,
    ) -> dict | None:
        """Returns cached {headers, first_rows}, or None on miss/dirty/expired/insufficient rows/stale-vs-source."""
        row = self._get_valid(spreadsheet_id, sheet_id, rows_to_fetch, current_modified_time)
        if row is None:
            return None
        data = json.loads(row["value"])
        logger.debug("Sheet data cache hit: %s/%s", spreadsheet_id, sheet_id)
        return {
            "headers": data["headers"],
            "first_rows": data["first_rows"][: max(1, rows_to_fetch) - 1],
        }

    def store(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        headers: list,
        first_rows: list,
        rows_to_fetch: int,
        modified_time: str | None = None,
    ):
        value: dict = {"headers": headers, "first_rows": first_rows}
        if modified_time is not None:
            value["modified_time"] = modified_time
        _safe_write(
            self._conn,
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty, rows_fetched)"
            " VALUES (?,?,?,?,0,?)",
            (
                self._NS,
                self._key(spreadsheet_id, sheet_id),
                json.dumps(value),
                time.time(),
                rows_to_fetch,
            ),
        )
        logger.debug("Cached sheet data for %s/%s", spreadsheet_id, sheet_id)

    def set_ttl(self, ttl: int) -> None:
        self._ttl = ttl

    def mark_dirty(self, spreadsheet_id: str, sheet_id: int | None = None):
        if sheet_id is not None:
            _safe_write(
                self._conn,
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                (self._NS, self._key(spreadsheet_id, sheet_id)),
            )
            logger.debug("Marked sheet data dirty for %s/%s", spreadsheet_id, sheet_id)
        else:
            _safe_write(
                self._conn,
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key LIKE ?",
                (self._NS, f"{spreadsheet_id}:%"),
            )
            logger.debug("Marked all sheet data dirty for %s", spreadsheet_id)

    def mark_all_dirty(self):
        _safe_write(self._conn, "UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        logger.debug("Invalidated all sheet data cache entries")

    def close(self):
        self._conn.close()


class DriveFolderCache:
    """Caches Drive folder listings keyed by (folder_id, mime_type).

    No modifiedTime-based validation: a folder's own modifiedTime does not
    change when children are added/removed, so it can't detect staleness here.
    """

    _NS = "drive_folder"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Drive folder cache opened: %s", db_path)

    def _key(self, folder_id: str, mime_type: str | None) -> str:
        return f"{folder_id}:{mime_type or ''}"

    def _get_valid(self, folder_id: str, mime_type: str | None) -> sqlite3.Row | None:
        key = self._key(folder_id, mime_type)
        row = _safe_fetchone(
            self._conn,
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, key),
        )
        if row is None or row["dirty"]:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            _safe_write(
                self._conn, "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, key)
            )
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
        _safe_write(
            self._conn,
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, self._key(folder_id, mime_type), json.dumps(files), time.time()),
        )
        logger.debug("Cached %d files for folder %s (mime=%s)", len(files), folder_id, mime_type)

    def mark_dirty(self, folder_id: str):
        _safe_write(
            self._conn,
            "UPDATE cache SET dirty=1 WHERE namespace=? AND key LIKE ?",
            (self._NS, f"{folder_id}:%"),
        )
        logger.debug("Marked drive folder cache dirty for %s", folder_id)

    def mark_all_dirty(self):
        _safe_write(self._conn, "UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        logger.debug("Invalidated all drive folder cache entries")

    def set_ttl(self, ttl: int) -> None:
        self._ttl = ttl

    def close(self):
        self._conn.close()


class DocContentCache:
    """Caches Google Doc content keyed by file_id."""

    _NS = "doc_content"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Doc cache opened: %s", db_path)

    def _get_valid(
        self, file_id: str, current_modified_time: str | None = None
    ) -> sqlite3.Row | None:
        row = _safe_fetchone(
            self._conn,
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, file_id),
        )
        if row is None or row["dirty"]:
            return None
        if current_modified_time is not None:
            # get_doc_content already stores the source's modifiedTime as part of
            # the cached doc dict — no separate column needed.
            cached_mtime = json.loads(row["value"]).get("modified_time")
            if cached_mtime is not None and cached_mtime != current_modified_time:
                logger.debug("Source modified since cache for %s, marking dirty", file_id)
                _safe_write(
                    self._conn,
                    "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                    (self._NS, file_id),
                )
                return None
        if time.time() - row["fetched_at"] > self._ttl:
            _safe_write(
                self._conn,
                "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
                (self._NS, file_id),
            )
            return None
        return row

    def get(self, file_id: str, current_modified_time: str | None = None) -> dict | None:
        """Returns cached doc response dict, or None on miss/dirty/expired/stale-vs-source."""
        row = self._get_valid(file_id, current_modified_time)
        if row is None:
            return None
        logger.debug("Doc cache hit: %s", file_id)
        return json.loads(row["value"])

    def store(self, file_id: str, doc: dict):
        _safe_write(
            self._conn,
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, file_id, json.dumps(doc), time.time()),
        )
        logger.debug("Cached doc %s", file_id)

    def mark_dirty(self, file_id: str):
        _safe_write(
            self._conn,
            "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?",
            (self._NS, file_id),
        )
        logger.debug("Marked doc cache dirty for %s", file_id)

    def mark_all_dirty(self):
        _safe_write(self._conn, "UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        logger.debug("Invalidated all doc cache entries")

    def set_ttl(self, ttl: int) -> None:
        self._ttl = ttl

    def close(self):
        self._conn.close()


class CalendarCache:
    """Caches calendar list and per-calendar metadata keyed by calendar_id.

    No modifiedTime-based validation: calendars aren't Drive files and don't
    expose a comparable field via the Calendar API; TTL/dirty invalidation only.
    """

    _NS = "calendar"
    _LIST_KEY = "__list__"

    def __init__(self, db_path: str = CACHE_DB_PATH, ttl: int = CACHE_TTL):
        self._ttl = ttl
        self._conn = _open(db_path)
        logger.debug("Calendar cache opened: %s", db_path)

    def _get_valid(self, key: str) -> sqlite3.Row | None:
        row = _safe_fetchone(
            self._conn,
            "SELECT value, fetched_at, dirty FROM cache WHERE namespace=? AND key=?",
            (self._NS, key),
        )
        if row is None or row["dirty"]:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            _safe_write(
                self._conn, "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, key)
            )
            return None
        return row

    def get_list(self) -> list | None:
        """Returns cached calendar list, or None on miss/dirty/expired."""
        row = self._get_valid(self._LIST_KEY)
        if row is None:
            return None
        logger.debug("Calendar list cache hit")
        return json.loads(row["value"])

    def store_list(self, calendars: list):
        _safe_write(
            self._conn,
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, self._LIST_KEY, json.dumps(calendars), time.time()),
        )
        logger.debug("Cached calendar list (%d entries)", len(calendars))

    def get(self, calendar_id: str) -> dict | None:
        """Returns cached calendar metadata, or None on miss/dirty/expired."""
        row = self._get_valid(calendar_id)
        if row is None:
            return None
        logger.debug("Calendar cache hit: %s", calendar_id)
        return json.loads(row["value"])

    def store(self, calendar_id: str, calendar: dict):
        _safe_write(
            self._conn,
            "INSERT OR REPLACE INTO cache (namespace, key, value, fetched_at, dirty)"
            " VALUES (?,?,?,?,0)",
            (self._NS, calendar_id, json.dumps(calendar), time.time()),
        )
        logger.debug("Cached calendar %s", calendar_id)

    def mark_dirty(self, calendar_id: str):
        for key in (calendar_id, self._LIST_KEY):
            _safe_write(
                self._conn, "UPDATE cache SET dirty=1 WHERE namespace=? AND key=?", (self._NS, key)
            )
        logger.debug("Marked calendar cache dirty for %s", calendar_id)

    def mark_all_dirty(self):
        _safe_write(self._conn, "UPDATE cache SET dirty=1 WHERE namespace=?", (self._NS,))
        logger.debug("Invalidated all calendar cache entries")

    def set_ttl(self, ttl: int) -> None:
        self._ttl = ttl

    def close(self):
        self._conn.close()


def fetch_sheets(
    sheets_service: Any,
    spreadsheet_id: str,
    cache: SheetStructureCache,
    drive_service: Any = None,
) -> list[SheetInfo]:
    """Fetch sheet list with caching. Falls back to stale cache if API call fails.

    If drive_service is given and CACHE_VALIDATE_MODIFIED_TIME is enabled, a
    cache hit is validated against the spreadsheet's live Drive modifiedTime
    first — an edit from another session invalidates the cache immediately
    instead of waiting out the TTL.
    """
    current_mtime = (
        get_modified_time(drive_service, spreadsheet_id) if CACHE_VALIDATE_MODIFIED_TIME else None
    )
    cached = cache.get_sheets(spreadsheet_id, current_modified_time=current_mtime)
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
        cache.store(spreadsheet_id, sheets, title=title, modified_time=current_mtime)
        return sheets
    except Exception as e:
        # Fall back to stale cache rather than hard-failing
        stale = cache.get_stale_sheets(spreadsheet_id)
        if stale is not None:
            logger.warning("API call failed for %s, serving stale cache: %s", spreadsheet_id, e)
            return stale
        raise
