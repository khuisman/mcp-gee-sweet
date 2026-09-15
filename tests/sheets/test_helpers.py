from types import SimpleNamespace

import pytest

from mcp_gee_sweet.cache import SheetInfo, SheetStructureCache
from mcp_gee_sweet.tools.sheets.helpers import (
    _column_index_to_letter,
    _get_sheet_id,
    _get_sheet_index,
    _letter_to_column_index,
    _parse_a1_notation,
)


class TestColumnIndexToLetter:
    def test_single_letters(self):
        assert _column_index_to_letter(0) == "A"
        assert _column_index_to_letter(25) == "Z"

    def test_double_letters(self):
        assert _column_index_to_letter(26) == "AA"
        assert _column_index_to_letter(27) == "AB"
        assert _column_index_to_letter(51) == "AZ"
        assert _column_index_to_letter(52) == "BA"

    def test_triple_letters(self):
        assert _column_index_to_letter(702) == "AAA"


class TestLetterToColumnIndex:
    def test_single_letters(self):
        assert _letter_to_column_index("A") == 0
        assert _letter_to_column_index("Z") == 25

    def test_double_letters(self):
        assert _letter_to_column_index("AA") == 26
        assert _letter_to_column_index("AB") == 27
        assert _letter_to_column_index("AZ") == 51
        assert _letter_to_column_index("BA") == 52

    def test_case_insensitive(self):
        assert _letter_to_column_index("a") == _letter_to_column_index("A")
        assert _letter_to_column_index("aa") == _letter_to_column_index("AA")

    def test_roundtrip(self):
        for i in range(200):
            assert _letter_to_column_index(_column_index_to_letter(i)) == i


class TestParseA1Notation:
    def test_single_cell(self):
        result = _parse_a1_notation("A1")
        assert result["startColumnIndex"] == 0
        assert result["startRowIndex"] == 0
        assert result["endColumnIndex"] == 1
        assert result["endRowIndex"] == 1

    def test_range(self):
        result = _parse_a1_notation("A1:C3")
        assert result["startColumnIndex"] == 0
        assert result["startRowIndex"] == 0
        assert result["endColumnIndex"] == 3  # exclusive
        assert result["endRowIndex"] == 3  # exclusive

    def test_column_only(self):
        result = _parse_a1_notation("B")
        assert result["startColumnIndex"] == 1
        assert result["endColumnIndex"] == 2
        assert "startRowIndex" not in result

    def test_row_range_only(self):
        result = _parse_a1_notation("1:3")
        assert result["startRowIndex"] == 0
        assert result["endRowIndex"] == 3
        assert "startColumnIndex" not in result

    def test_column_range_only(self):
        result = _parse_a1_notation("A:C")
        assert result["startColumnIndex"] == 0
        assert result["endColumnIndex"] == 3  # exclusive
        assert "startRowIndex" not in result

    def test_open_ended_range(self):
        # B2:D — colon present but no end row; endRowIndex should be absent (open-ended)
        result = _parse_a1_notation("B2:D")
        assert result["startColumnIndex"] == 1
        assert result["startRowIndex"] == 1
        assert result["endColumnIndex"] == 4  # exclusive
        assert "endRowIndex" not in result

    def test_multi_letter_column(self):
        result = _parse_a1_notation("AA1:AB2")
        assert result["startColumnIndex"] == 26
        assert result["endColumnIndex"] == 28  # exclusive

    def test_invalid_notation_raises(self):
        with pytest.raises(ValueError):
            _parse_a1_notation("Sheet1!A1")

    def test_invalid_empty_string_raises(self):
        with pytest.raises(ValueError):
            _parse_a1_notation("")

    def test_invalid_garbage_raises(self):
        with pytest.raises(ValueError):
            _parse_a1_notation("??!!")


class _FakeSheetsService:
    """A minimal spreadsheets().get(...).execute() stand-in. Give it either
    `result` (returned by every execute() call) or `exception` (raised
    instead) — covers the transient-failure, genuine-not-found, and
    real-match fixture shapes that used to be three separate, near-identical
    hand-rolled classes (PR #754 review)."""

    _http = SimpleNamespace(credentials=None)

    def __init__(self, *, result: dict | None = None, exception: Exception | None = None):
        self._result = result
        self._exception = exception

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, fields):
        return self

    def execute(self, **kwargs):
        if self._exception is not None:
            raise self._exception
        return self._result


_ONE_OTHER_SHEET = {"sheets": [{"properties": {"title": "Other", "sheetId": 0}}]}
_TWO_SHEETS = {
    "sheets": [
        {"properties": {"title": "Sheet1", "sheetId": 0, "index": 0}},
        {"properties": {"title": "Sheet2", "sheetId": 123456, "index": 1}},
    ]
}


def _raising_service() -> _FakeSheetsService:
    """Simulates a transient API failure (rate limit, timeout, auth hiccup)."""
    return _FakeSheetsService(exception=TimeoutError("simulated transient API failure"))


def _empty_service() -> _FakeSheetsService:
    """A real API response where the sheet genuinely doesn't exist."""
    return _FakeSheetsService(result=_ONE_OTHER_SHEET)


def _matching_service() -> _FakeSheetsService:
    """A real API response with more than one sheet, so a happy-path lookup
    exercises picking the right match rather than trivially returning the
    only entry present."""
    return _FakeSheetsService(result=_TWO_SHEETS)


class TestGetSheetIdExceptionPropagation:
    """Regression test for issue #384: _get_sheet_id used to catch every
    exception and return None, the same value returned for a genuine
    "sheet not found" — so callers misreported transient API failures as
    a missing sheet. It should now let those exceptions propagate."""

    async def test_no_cache_transient_api_error_propagates(self):
        with pytest.raises(TimeoutError):
            await _get_sheet_id(_raising_service(), "sid", "Sheet1")

    async def test_no_cache_genuine_missing_sheet_still_returns_none(self):
        sheet_id = await _get_sheet_id(_empty_service(), "sid", "Sheet1")
        assert sheet_id is None

    async def test_no_cache_matching_sheet_returns_its_id(self):
        """Happy-path coverage (PR #442 review, issue #442) — the existing
        exception-propagation/not-found tests never exercised a genuine
        match, so a bug in the match/return logic itself (wrong dict key,
        returning the wrong sheet's id) would have passed unnoticed."""
        sheet_id = await _get_sheet_id(_matching_service(), "sid", "Sheet2")
        assert sheet_id == 123456

    async def test_with_cache_matching_sheet_returns_its_id(self):
        # _raising_service() here proves the cache path never touches the
        # API at all for a fresh, matching cache entry — if it did, this
        # would raise TimeoutError instead of returning.
        cache = SheetStructureCache(db_path=":memory:", ttl=1000)
        cache.store(
            "sid",
            [SheetInfo(title="Sheet1", sheet_id=0), SheetInfo(title="Sheet2", sheet_id=123456)],
        )
        sheet_id = await _get_sheet_id(_raising_service(), "sid", "Sheet2", cache)
        assert sheet_id == 123456

    async def test_with_cache_transient_api_error_propagates(self):
        cache = SheetStructureCache(db_path=":memory:", ttl=1000)
        with pytest.raises(TimeoutError):
            await _get_sheet_id(_raising_service(), "sid", "Sheet1", cache)

    async def test_with_cache_stale_fallback_still_returns_none_for_missing_sheet(self):
        # A stale cache entry exists but doesn't contain "Missing" — the API
        # refetch fails, fetch_sheets() falls back to serving the stale
        # entry (its own documented behavior), and the sheet genuinely isn't
        # in it, so _get_sheet_id should still resolve to None, not raise.
        cache = SheetStructureCache(db_path=":memory:", ttl=1000)
        cache.store("sid", [SheetInfo(title="Other", sheet_id=0)])
        cache.mark_dirty("sid")  # force a refetch attempt that will fail

        sheet_id = await _get_sheet_id(_raising_service(), "sid", "Missing", cache)

        assert sheet_id is None


class TestGetSheetIndexExceptionPropagation:
    """Regression test for issue #391: _get_sheet_index had the same
    catch-and-swallow bug #384 fixed in _get_sheet_id — it caught every
    exception and returned None, the same value returned for a genuine
    "sheet not found". It should now let those exceptions propagate."""

    async def test_transient_api_error_propagates(self):
        with pytest.raises(TimeoutError):
            await _get_sheet_index(_raising_service(), "sid", 0)

    async def test_genuine_missing_sheet_still_returns_none(self):
        sheet_index = await _get_sheet_index(_empty_service(), "sid", 999)
        assert sheet_index is None

    async def test_matching_sheet_returns_its_index(self):
        """Happy-path coverage (PR #442 review, issue #442) — same gap as
        TestGetSheetIdExceptionPropagation above."""
        sheet_index = await _get_sheet_index(_matching_service(), "sid", 123456)
        assert sheet_index == 1
