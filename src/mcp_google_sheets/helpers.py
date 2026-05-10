import re
from typing import Any, Dict, Optional


def _column_index_to_letter(index: int) -> str:
    """Convert 0-based column index to A1 notation letter (0='A', 25='Z', 26='AA', etc.)"""
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord('A')) + result
        index = index // 26 - 1
    return result


def _letter_to_column_index(letter: str) -> int:
    """Convert A1 notation letter to 0-based column index ('A'=0, 'Z'=25, 'AA'=26, etc.)"""
    result = 0
    for char in letter.upper():
        result = result * 26 + (ord(char) - ord('A') + 1)
    return result - 1


def _parse_a1_notation(range_str: str) -> Dict[str, int]:
    """
    Parse A1 notation range to row/column indices.

    Returns a dict with applicable keys: startRowIndex, endRowIndex,
    startColumnIndex, endColumnIndex. Not all keys present for all formats.
    """
    match = re.match(r'^([A-Z]+)?(\d+)?(?::([A-Z]+)?(\d+)?)?$', range_str.upper())

    if not match:
        raise ValueError(f"Invalid A1 notation: {range_str}")

    start_col, start_row, end_col, end_row = match.groups()
    result = {}

    if start_col:
        result['startColumnIndex'] = _letter_to_column_index(start_col)
    if start_row:
        result['startRowIndex'] = int(start_row) - 1  # A1 is 1-based, API is 0-based
    if end_col:
        result['endColumnIndex'] = _letter_to_column_index(end_col) + 1  # exclusive
    elif start_col:
        result['endColumnIndex'] = result['startColumnIndex'] + 1
    if end_row:
        result['endRowIndex'] = int(end_row)  # already exclusive
    elif start_row:
        result['endRowIndex'] = result['startRowIndex'] + 1

    return result


def _get_sheet_id(sheets_service: Any, spreadsheet_id: str, sheet_name: str) -> Optional[int]:
    """Return the numeric sheet ID for sheet_name, or None if not found."""
    try:
        spreadsheet = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields='sheets(properties(title,sheetId))'
        ).execute()
        for sheet in spreadsheet.get('sheets', []):
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']
        return None
    except Exception:
        return None
