import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CACHE_PATH = os.environ.get("CACHE_PATH", "/tmp/mcp_sheet_cache.json")
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

    def store(self, spreadsheet_id: str, sheets: list[SheetInfo]):
        self._data[spreadsheet_id] = {
            "sheets": [{"title": s.title, "sheet_id": s.sheet_id} for s in sheets],
            "fetched_at": time.time(),
            "dirty": False,
        }
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
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title,sheetId))")
            .execute()
        )
        sheets = [
            SheetInfo(title=s["properties"]["title"], sheet_id=s["properties"]["sheetId"])
            for s in spreadsheet.get("sheets", [])
        ]
        cache.store(spreadsheet_id, sheets)
        return sheets
    except Exception as e:
        # Fall back to stale cache rather than hard-failing
        stale = cache._data.get(spreadsheet_id, {}).get("sheets")
        if stale:
            logger.warning("API call failed for %s, serving stale cache: %s", spreadsheet_id, e)
            return [SheetInfo(**s) for s in stale]
        raise
