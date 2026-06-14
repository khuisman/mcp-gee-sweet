import re
from typing import TYPE_CHECKING, Any

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


def _parse_a1_notation(range_str: str) -> dict[str, int]:
    """
    Parse A1 notation range to row/column indices.

    Returns a dict with applicable keys: startRowIndex, endRowIndex,
    startColumnIndex, endColumnIndex. Not all keys present for all formats.
    Open-ended ranges (e.g. "B2:D") omit endRowIndex so the API treats them
    as extending to the last row of the sheet.
    """
    if not range_str:
        raise ValueError("Invalid A1 notation: empty string")

    match = re.match(r"^([A-Z]+)?(\d+)?(?::([A-Z]+)?(\d+)?)?$", range_str.upper())

    if not match:
        raise ValueError(f"Invalid A1 notation: {range_str}")

    start_col, start_row, end_col, end_row = match.groups()
    has_colon = ":" in range_str
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

    return result


def _get_sheet_id(
    sheets_service: Any,
    spreadsheet_id: str,
    sheet_name: str,
    cache: "SheetStructureCache | None" = None,
) -> int | None:
    """Return the numeric sheet ID for sheet_name, or None if not found."""
    if cache is not None:
        from ...cache import fetch_sheets

        try:
            sheets = fetch_sheets(sheets_service, spreadsheet_id, cache)
            for s in sheets:
                if s.title == sheet_name:
                    return s.sheet_id
            # Sheet not in cache — mark dirty in case structure changed
            cache.mark_dirty(spreadsheet_id)
            return None
        except Exception:
            return None

    try:
        spreadsheet = (
            sheets_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title,sheetId))")
            .execute()
        )
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
        return None
    except Exception:
        return None
