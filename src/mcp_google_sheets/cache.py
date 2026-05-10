import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CACHE_PATH = os.environ.get("CACHE_PATH", "/tmp/mcp_sheet_cache.json")
SHEET_DATA_CACHE_PATH = os.environ.get("SHEET_DATA_CACHE_PATH", "/tmp/mcp_sheet_data_cache.json")
DRIVE_FOLDER_CACHE_PATH = os.environ.get(
    "DRIVE_FOLDER_CACHE_PATH", "/tmp/mcp_drive_folder_cache.json"
)
DOC_CACHE_PATH = os.environ.get("DOC_CACHE_PATH", "/tmp/mcp_doc_cache.json")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "1800"))  # 30 minutes


@dataclass
class SheetInfo:
    title: str
    sheet_id: int


class SheetStructureCache:
    def __init__(self, path: str = CACHE_PATH, ttl: int = CACHE_TTL):
        self._path = path
        self._ttl = ttl
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self._path) as f:
                self._data = json.load(f)
            logger.debug("Loaded sheet cache from %s (%d entries)", self._path, len(self._data))
        except FileNotFoundError:
            self._data = {}
        except Exception as e:
            logger.warning("Failed to load sheet cache: %s", e)
            self._data = {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f)
        except Exception as e:
            logger.warning("Failed to save sheet cache: %s", e)  # best-effort, don't crash

    def _is_valid(self, spreadsheet_id: str) -> bool:
        entry = self._data.get(spreadsheet_id)
        if entry is None:
            return False
        if entry.get("dirty", False):
            return False
        if time.time() - entry.get("fetched_at", 0) > self._ttl:
            logger.debug("Cache TTL expired for %s, marking dirty", spreadsheet_id)
            entry["dirty"] = True
            self._save()
            return False
        return True

    def get_sheets(self, spreadsheet_id: str) -> list[SheetInfo] | None:
        """Returns cached sheet list, or None on cache miss/dirty/expired."""
        if not self._is_valid(spreadsheet_id):
            return None
        return [SheetInfo(**s) for s in self._data[spreadsheet_id]["sheets"]]

    def get_title(self, spreadsheet_id: str) -> str | None:
        """Returns cached spreadsheet title, or None on cache miss/dirty/expired."""
        if not self._is_valid(spreadsheet_id):
            return None
        return self._data[spreadsheet_id].get("title")

    def store(self, spreadsheet_id: str, sheets: list[SheetInfo], title: str | None = None):
        self._data[spreadsheet_id] = {
            "sheets": [{"title": s.title, "sheet_id": s.sheet_id} for s in sheets],
            "fetched_at": time.time(),
            "dirty": False,
        }
        if title is not None:
            self._data[spreadsheet_id]["title"] = title
        self._save()
        logger.debug("Cached %d sheets for %s", len(sheets), spreadsheet_id)

    def mark_dirty(self, spreadsheet_id: str):
        if spreadsheet_id in self._data:
            self._data[spreadsheet_id]["dirty"] = True
            self._save()
            logger.debug("Marked cache dirty for %s", spreadsheet_id)

    def mark_all_dirty(self):
        for entry in self._data.values():
            entry["dirty"] = True
        self._save()
        logger.debug("Invalidated all %d cache entries", len(self._data))


class SheetDataCache:
    """Caches per-sheet summary data (headers + first N rows) keyed by (spreadsheet_id, sheet_id)."""

    def __init__(self, path: str = SHEET_DATA_CACHE_PATH, ttl: int = CACHE_TTL):
        self._path = path
        self._ttl = ttl
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self._path) as f:
                self._data = json.load(f)
            logger.debug(
                "Loaded sheet data cache from %s (%d spreadsheets)", self._path, len(self._data)
            )
        except FileNotFoundError:
            self._data = {}
        except Exception as e:
            logger.warning("Failed to load sheet data cache: %s", e)
            self._data = {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f)
        except Exception as e:
            logger.warning("Failed to save sheet data cache: %s", e)  # best-effort, don't crash

    def _is_valid(self, spreadsheet_id: str, sheet_id: int, rows_to_fetch: int) -> bool:
        entry = self._data.get(spreadsheet_id, {}).get(str(sheet_id))
        if entry is None:
            return False
        if entry.get("dirty", False):
            return False
        if time.time() - entry.get("fetched_at", 0) > self._ttl:
            entry["dirty"] = True
            self._save()
            return False
        if entry.get("rows_fetched", 0) < rows_to_fetch:
            return False
        return True

    def get(self, spreadsheet_id: str, sheet_id: int, rows_to_fetch: int) -> dict | None:
        """Returns cached {headers, first_rows}, or None on miss/dirty/expired/insufficient rows."""
        if not self._is_valid(spreadsheet_id, sheet_id, rows_to_fetch):
            return None
        entry = self._data[spreadsheet_id][str(sheet_id)]
        logger.debug("Sheet data cache hit: %s/%s", spreadsheet_id, sheet_id)
        return {
            "headers": entry["headers"],
            "first_rows": entry["first_rows"][: rows_to_fetch - 1],
        }

    def store(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        headers: list,
        first_rows: list,
        rows_to_fetch: int,
    ):
        if spreadsheet_id not in self._data:
            self._data[spreadsheet_id] = {}
        self._data[spreadsheet_id][str(sheet_id)] = {
            "headers": headers,
            "first_rows": first_rows,
            "rows_fetched": rows_to_fetch,
            "fetched_at": time.time(),
            "dirty": False,
        }
        self._save()
        logger.debug("Cached sheet data for %s/%s", spreadsheet_id, sheet_id)

    def mark_dirty(self, spreadsheet_id: str, sheet_id: int | None = None):
        if spreadsheet_id not in self._data:
            return
        if sheet_id is not None:
            entry = self._data[spreadsheet_id].get(str(sheet_id))
            if entry:
                entry["dirty"] = True
                self._save()
                logger.debug("Marked sheet data dirty for %s/%s", spreadsheet_id, sheet_id)
        else:
            for entry in self._data[spreadsheet_id].values():
                entry["dirty"] = True
            self._save()
            logger.debug("Marked all sheet data dirty for %s", spreadsheet_id)

    def mark_all_dirty(self):
        for sheets in self._data.values():
            for entry in sheets.values():
                entry["dirty"] = True
        self._save()
        logger.debug("Invalidated all sheet data cache entries")


class DriveFolderCache:
    """Caches Drive folder listings keyed by (folder_id, mime_type)."""

    def __init__(self, path: str = DRIVE_FOLDER_CACHE_PATH, ttl: int = CACHE_TTL):
        self._path = path
        self._ttl = ttl
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self._path) as f:
                self._data = json.load(f)
            logger.debug(
                "Loaded drive folder cache from %s (%d entries)", self._path, len(self._data)
            )
        except FileNotFoundError:
            self._data = {}
        except Exception as e:
            logger.warning("Failed to load drive folder cache: %s", e)
            self._data = {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f)
        except Exception as e:
            logger.warning("Failed to save drive folder cache: %s", e)  # best-effort, don't crash

    def _key(self, folder_id: str, mime_type: str | None) -> str:
        return f"{folder_id}:{mime_type or ''}"

    def _is_valid(self, folder_id: str, mime_type: str | None) -> bool:
        entry = self._data.get(self._key(folder_id, mime_type))
        if entry is None:
            return False
        if entry.get("dirty", False):
            return False
        if time.time() - entry.get("fetched_at", 0) > self._ttl:
            entry["dirty"] = True
            self._save()
            return False
        return True

    def get(self, folder_id: str, mime_type: str | None) -> list | None:
        """Returns cached file list, or None on miss/dirty/expired."""
        if not self._is_valid(folder_id, mime_type):
            return None
        logger.debug("Drive folder cache hit: %s (mime=%s)", folder_id, mime_type)
        return self._data[self._key(folder_id, mime_type)]["files"]

    def store(self, folder_id: str, mime_type: str | None, files: list):
        self._data[self._key(folder_id, mime_type)] = {
            "files": files,
            "fetched_at": time.time(),
            "dirty": False,
        }
        self._save()
        logger.debug("Cached %d files for folder %s (mime=%s)", len(files), folder_id, mime_type)

    def mark_dirty(self, folder_id: str):
        for key in list(self._data):
            if key.startswith(f"{folder_id}:"):
                self._data[key]["dirty"] = True
        self._save()
        logger.debug("Marked drive folder cache dirty for %s", folder_id)

    def mark_all_dirty(self):
        for entry in self._data.values():
            entry["dirty"] = True
        self._save()
        logger.debug("Invalidated all drive folder cache entries")


class DocContentCache:
    """Caches Google Doc content keyed by file_id."""

    def __init__(self, path: str = DOC_CACHE_PATH, ttl: int = CACHE_TTL):
        self._path = path
        self._ttl = ttl
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self._path) as f:
                self._data = json.load(f)
            logger.debug("Loaded doc cache from %s (%d entries)", self._path, len(self._data))
        except FileNotFoundError:
            self._data = {}
        except Exception as e:
            logger.warning("Failed to load doc cache: %s", e)
            self._data = {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f)
        except Exception as e:
            logger.warning("Failed to save doc cache: %s", e)  # best-effort, don't crash

    def _is_valid(self, file_id: str) -> bool:
        entry = self._data.get(file_id)
        if entry is None:
            return False
        if entry.get("dirty", False):
            return False
        if time.time() - entry.get("fetched_at", 0) > self._ttl:
            entry["dirty"] = True
            self._save()
            return False
        return True

    def get(self, file_id: str) -> dict | None:
        """Returns cached doc response dict, or None on miss/dirty/expired."""
        if not self._is_valid(file_id):
            return None
        logger.debug("Doc cache hit: %s", file_id)
        return self._data[file_id]["doc"]

    def store(self, file_id: str, doc: dict):
        self._data[file_id] = {
            "doc": doc,
            "fetched_at": time.time(),
            "dirty": False,
        }
        self._save()
        logger.debug("Cached doc %s", file_id)

    def mark_dirty(self, file_id: str):
        if file_id in self._data:
            self._data[file_id]["dirty"] = True
            self._save()
            logger.debug("Marked doc cache dirty for %s", file_id)

    def mark_all_dirty(self):
        for entry in self._data.values():
            entry["dirty"] = True
        self._save()
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
        stale = cache._data.get(spreadsheet_id, {}).get("sheets")
        if stale:
            logger.warning("API call failed for %s, serving stale cache: %s", spreadsheet_id, e)
            return [SheetInfo(**s) for s in stale]
        raise
