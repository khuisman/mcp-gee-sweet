import re
from typing import TYPE_CHECKING, Any, Literal

from ...auth import execute_in_thread
from ..docs.indices import utf16_len

if TYPE_CHECKING:
    from ...cache import SheetStructureCache


def _quote_sheet_name(name: str) -> str:
    """Wrap a sheet name in single quotes if it contains spaces or special chars.

    The Sheets API requires 'Sheet Name'!A1:B2 when the name has non-word characters.
    Single quotes inside the name are escaped by doubling them per API spec.
    """
    if re.search(r"[^A-Za-z0-9_]", name):
        return "'" + name.replace("'", "''") + "'"
    return name


def _column_index_to_letter(index: int) -> str:
    """Convert 0-based column index to A1 notation letter (0='A', 25='Z', 26='AA', etc.)"""
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord("A")) + result
        index = index // 26 - 1
    return result


def _letter_to_column_index(letter: str) -> int:
    """Convert A1 notation letter to 0-based column index ('A'=0, 'Z'=25, 'AA'=26, etc.)"""
    result = 0
    for char in letter.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def _utf16_len(text: str) -> int:
    """UTF-16 code units a string occupies. Sheets API TextFormatRun.startIndex
    counts UTF-16 code units, not Python code points — an astral-plane character
    (most emoji, some CJK/math symbols) is one Python str character but a 2-unit
    surrogate pair, the same accounting the Docs API tools use for their own
    startIndex/endIndex fields — delegates to utf16_len (tools/docs/indices.py)
    rather than duplicating its per-character logic."""
    return utf16_len(text)


def _parse_a1_notation(range_str: str) -> dict[str, int]:
    """
    Parse A1 notation range to row/column indices.

    Returns a dict with applicable keys: startRowIndex, endRowIndex,
    startColumnIndex, endColumnIndex. Not all keys present for all formats.
    Open-ended ranges (e.g. "B2:D") omit endRowIndex so the API treats them
    as extending to the last row of the sheet.

    Raises ValueError for empty/malformed strings, a row number below 1
    (matched by the regex's bare \\d+ but not a valid 1-based A1 row, e.g.
    "A0"), or an end bound at or before its start bound (e.g. "A5:A2" or
    "A5:A4") — otherwise these reach the Sheets API as a raw HttpError
    instead of the local {"error": ...} every call site returns on a
    ValueError from this function (issue #747 QA round 1).
    """
    if not range_str:
        raise ValueError("Invalid A1 notation: empty string")

    match = re.match(r"^([A-Z]+)?(\d+)?(?::([A-Z]+)?(\d+)?)?$", range_str.upper())

    if not match:
        raise ValueError(f"Invalid A1 notation: {range_str}")

    start_col, start_row, end_col, end_row = match.groups()
    has_colon = ":" in range_str

    if (start_row is not None and int(start_row) < 1) or (end_row is not None and int(end_row) < 1):
        raise ValueError(f"Invalid A1 notation: row must be 1 or greater: {range_str}")

    result = {}

    if start_col:
        result["startColumnIndex"] = _letter_to_column_index(start_col)
    if start_row:
        result["startRowIndex"] = int(start_row) - 1  # A1 is 1-based, API is 0-based
    if end_col:
        result["endColumnIndex"] = _letter_to_column_index(end_col) + 1  # exclusive
    elif start_col and not has_colon:
        # Single cell or bare column — close the range to one column
        result["endColumnIndex"] = result["startColumnIndex"] + 1
    if end_row:
        result["endRowIndex"] = int(end_row)  # already exclusive
    elif start_row and not has_colon:
        # Single cell or bare row — close the range to one row
        result["endRowIndex"] = result["startRowIndex"] + 1

    if "endRowIndex" in result and result["endRowIndex"] <= result.get("startRowIndex", 0):
        raise ValueError(f"Invalid A1 notation: end row precedes start row: {range_str}")
    if "endColumnIndex" in result and result["endColumnIndex"] <= result.get("startColumnIndex", 0):
        raise ValueError(f"Invalid A1 notation: end column precedes start column: {range_str}")

    return result


def _parse_a1_notation_or_error(
    range_str: str,
) -> tuple[dict[str, Any] | None, dict[str, int] | None]:
    """Same as _parse_a1_notation, but returns (error, None) on invalid input
    instead of raising, matching this codebase's established error-or-None
    convention (_enum_value_error, _resolve_end_index_or_error in
    structure.py) instead of requiring every call site to wrap this in its
    own try/except ValueError (issue #747 QA round 1).

    Returns (None, indices) on success, or (error, None) on failure.
    """
    try:
        return None, _parse_a1_notation(range_str)
    except ValueError as e:
        return {"error": str(e)}, None


async def _find_sheet_properties(
    sheets_service: Any,
    spreadsheet_id: str,
    match_key: Literal["title", "sheetId"],
    match_value: Any,
) -> dict[str, Any] | None:
    """Fetch spreadsheet metadata and return the properties dict of the one
    sheet whose match_key equals match_value, or None if no sheet matches.

    Shared by _get_sheet_id (match_key="title") and _get_sheet_index
    (match_key="sheetId") — both used to independently fetch spreadsheet
    metadata and linear-scan for a match, which meant issue #384's "let
    exceptions propagate instead of swallowing to None" fix had to be
    applied twice (#391 caught _get_sheet_index missing it). A transient API
    failure (rate limit, timeout, auth hiccup) propagates as an exception
    here instead of being swallowed into None, so callers don't misreport
    it as "not found" (#384/#391, now enforced in one place — #442).

    match_key is indexed with `properties[match_key]`, not `.get()` — a
    sheet whose properties genuinely lack the field raises KeyError rather
    than being silently treated as "no match," preserving the same
    raise-on-missing-field guarantee #384/#391 established for the original
    bracket-access code this replaced (PR #754 review round 1).
    """
    spreadsheet = await execute_in_thread(
        sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(title,sheetId,index)")
        .execute,
        sheets_service,
    )
    for sheet in spreadsheet.get("sheets", []):
        properties = sheet["properties"]
        if properties[match_key] == match_value:
            return properties
    return None


async def _get_sheet_id(
    sheets_service: Any,
    spreadsheet_id: str,
    sheet_name: str,
    cache: "SheetStructureCache | None" = None,
    drive_service: Any = None,
) -> int | None:
    """Return the numeric sheet ID for sheet_name, or None if not found.

    None means the sheet genuinely doesn't exist among the spreadsheet's
    sheets. See _find_sheet_properties for the exception-propagation
    behavior (issue #384) shared with _get_sheet_index.
    """
    if cache is not None:
        from ...cache import fetch_sheets

        sheets = await fetch_sheets(sheets_service, spreadsheet_id, cache, drive_service)
        for s in sheets:
            if s.title == sheet_name:
                return s.sheet_id
        # Sheet not in cache — mark dirty in case structure changed
        cache.mark_dirty(spreadsheet_id)
        return None

    properties = await _find_sheet_properties(
        sheets_service, spreadsheet_id, match_key="title", match_value=sheet_name
    )
    return properties["sheetId"] if properties else None


async def _get_sheet_index(sheets_service: Any, spreadsheet_id: str, sheet_id: int) -> int | None:
    """Return the current 0-based tab position of sheet_id, or None if not found.

    None means the sheet genuinely doesn't exist among the spreadsheet's
    sheets. See _find_sheet_properties for the exception-propagation
    behavior (issue #391, mirroring #384) shared with _get_sheet_id.
    """
    properties = await _find_sheet_properties(
        sheets_service, spreadsheet_id, match_key="sheetId", match_value=sheet_id
    )
    return properties["index"] if properties else None
