from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...cache import fetch_sheets
from .helpers import (
    _column_index_to_letter,
    _get_sheet_id,
    _get_sheet_index,
    _parse_a1_notation,
    _quote_sheet_name,
)

_VALID_CHART_TYPES = ["COLUMN", "BAR", "LINE", "AREA", "PIE", "SCATTER", "COMBO", "HISTOGRAM"]

_VALID_BORDER_STYLES = [
    "DOTTED",
    "DASHED",
    "SOLID",
    "SOLID_MEDIUM",
    "SOLID_THICK",
    "DOUBLE",
    "NONE",
]

_VALID_SORT_ORDERS = ["ASCENDING", "DESCENDING"]

_VALID_CONDITION_TYPES = [
    "BOOLEAN",
    "TEXT_CONTAINS",
    "TEXT_NOT_CONTAINS",
    "TEXT_STARTS_WITH",
    "TEXT_ENDS_WITH",
    "TEXT_EQ",
    "TEXT_IS_EMAIL",
    "TEXT_IS_URL",
    "DATE_EQ",
    "DATE_BEFORE",
    "DATE_AFTER",
    "DATE_ON_OR_BEFORE",
    "DATE_ON_OR_AFTER",
    "DATE_BETWEEN",
    "DATE_NOT_BETWEEN",
    "DATE_IS_VALID",
    "NUMBER_GREATER",
    "NUMBER_GREATER_THAN_EQ",
    "NUMBER_LESS",
    "NUMBER_LESS_THAN_EQ",
    "NUMBER_EQ",
    "NUMBER_NOT_EQ",
    "NUMBER_BETWEEN",
    "NUMBER_NOT_BETWEEN",
    "ONE_OF_RANGE",
    "ONE_OF_LIST",
    "BLANK",
    "NOT_BLANK",
    "CUSTOM_FORMULA",
]

# Expected `values` count per condition_type, per add_data_validation's own
# docstring (issue #366) — None means "at least 1, no upper bound"
# (ONE_OF_LIST's dropdown items), a tuple means "exactly one of these counts"
# (BOOLEAN accepts 0 for a plain checkbox or 2 for custom checked/unchecked
# labels). Without this, a mismatched call still fails, just as a raw Sheets
# API 400 after a round-trip instead of a local, immediate {"error": ...}.
_CONDITION_VALUE_COUNTS: dict[str, tuple[int, ...] | None] = {
    "BOOLEAN": (0, 2),
    "TEXT_CONTAINS": (1,),
    "TEXT_NOT_CONTAINS": (1,),
    "TEXT_STARTS_WITH": (1,),
    "TEXT_ENDS_WITH": (1,),
    "TEXT_EQ": (1,),
    "TEXT_IS_EMAIL": (0,),
    "TEXT_IS_URL": (0,),
    "DATE_EQ": (1,),
    "DATE_BEFORE": (1,),
    "DATE_AFTER": (1,),
    "DATE_ON_OR_BEFORE": (1,),
    "DATE_ON_OR_AFTER": (1,),
    "DATE_BETWEEN": (2,),
    "DATE_NOT_BETWEEN": (2,),
    "DATE_IS_VALID": (0,),
    "NUMBER_GREATER": (1,),
    "NUMBER_GREATER_THAN_EQ": (1,),
    "NUMBER_LESS": (1,),
    "NUMBER_LESS_THAN_EQ": (1,),
    "NUMBER_EQ": (1,),
    "NUMBER_NOT_EQ": (1,),
    "NUMBER_BETWEEN": (2,),
    "NUMBER_NOT_BETWEEN": (2,),
    "ONE_OF_RANGE": (1,),
    "ONE_OF_LIST": None,
    "BLANK": (0,),
    "NOT_BLANK": (0,),
    "CUSTOM_FORMULA": (1,),
}


def _condition_value_count_error(
    condition_type: str, values: list[str] | None
) -> dict[str, Any] | None:
    """Return an {"error": ...} dict if `values` doesn't match the count
    condition_type expects. Assumes condition_type is already a valid,
    upper-cased member of _VALID_CONDITION_TYPES.

    condition_type not being a key in _CONDITION_VALUE_COUNTS (a future
    desync between the two tables — guarded against by
    TestAddDataValidation::test_condition_value_counts_covers_every_valid_condition_type)
    skips the local check rather than raising a KeyError; the real Sheets
    API still validates the request either way (PR #750 review).
    """
    if condition_type not in _CONDITION_VALUE_COUNTS:
        return None
    count = len(values) if values else 0
    expected = _CONDITION_VALUE_COUNTS[condition_type]
    if expected is None:
        if count < 1:
            return {
                "error": f"condition_type '{condition_type}' requires at least 1 value, got {count}"
            }
        return None
    if count not in expected:
        needed = " or ".join(str(n) for n in expected)
        return {
            "error": f"condition_type '{condition_type}' requires exactly {needed} value(s), got {count}"
        }
    return None


def _border_spec(border: dict) -> dict[str, Any]:
    """Convert a {"style", "color", "width"} dict into a Sheets API Border object.

    Only "style" is validated locally (by the caller, against
    _VALID_BORDER_STYLES) — "color"/"width" are passed through unchecked, so a
    malformed value surfaces only as a raw Sheets API 400.
    """
    spec: dict[str, Any] = {"style": border["style"].upper()}
    if "color" in border:
        spec["color"] = border["color"]
    if "width" in border:
        spec["width"] = border["width"]
    return spec


def _grid_range(sheet_id: int, range_str: str) -> dict[str, Any]:
    """Build a Sheets API GridRange dict from an A1 notation range string."""
    indices = _parse_a1_notation(range_str)
    grid_range: dict[str, Any] = {
        "sheetId": sheet_id,
        "startRowIndex": indices.get("startRowIndex", 0),
        "startColumnIndex": indices.get("startColumnIndex", 0),
    }
    if "endRowIndex" in indices:
        grid_range["endRowIndex"] = indices["endRowIndex"]
    if "endColumnIndex" in indices:
        grid_range["endColumnIndex"] = indices["endColumnIndex"]
    return grid_range


async def _apply_data_validation(
    sheets_service,
    spreadsheet_id: str,
    sheet: str,
    range_str: str,
    cache,
    drive_service,
    rule: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve `sheet` to a sheetId and issue a setDataValidation request.

    `rule=None` omits the rule field, which clears any existing rule on the
    range (clear_data_validation); a rule dict sets one (add_data_validation).
    Shared scaffolding extracted per PR #745 review — the two callers were
    duplicating this sheet-resolution + _grid_range + batchUpdate block
    almost verbatim.
    """
    sheet_id = await _get_sheet_id(sheets_service, spreadsheet_id, sheet, cache, drive_service)
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}

    set_data_validation: dict[str, Any] = {"range": _grid_range(sheet_id, range_str)}
    if rule is not None:
        set_data_validation["rule"] = rule

    return await execute_in_thread(
        sheets_service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"setDataValidation": set_data_validation}]},
        )
        .execute,
        sheets_service,
    )


def _enum_value_error(
    value: str, valid_values: list[str], field_name: str, context: str | None = None
) -> dict[str, Any] | None:
    """Return an {"error": ...} dict if value.upper() isn't in valid_values.

    context, when given, is appended to the message verbatim (e.g.
    "for 'top'" or "for column_index 0") for a caller that validates the
    same field under several different keys — the caller controls the full
    wording, including any quoting, since callers disagree on the shape.
    """
    if value.upper() not in valid_values:
        suffix = f" {context}" if context else ""
        return {
            "error": f"Invalid {field_name} '{value}'{suffix}. Must be one of: {', '.join(valid_values)}"
        }
    return None


def _per_column_ranges(sheet_id: int, indices: dict) -> list[dict]:
    """Split a parsed A1 range into one source-range dict per column.

    The Sheets addChart API requires each entry in a ChartSourceRange.sources
    list to span exactly one row or one column.  Passing a multi-column
    rectangle as a single source produces a 400 error.
    """
    row_start = indices.get("startRowIndex", 0)
    row_end = indices.get("endRowIndex")
    col_start = indices.get("startColumnIndex", 0)
    col_end = indices.get("endColumnIndex", col_start + 1)

    base = {"sheetId": sheet_id, "startRowIndex": row_start, "startColumnIndex": 0}
    if row_end is not None:
        base["endRowIndex"] = row_end

    return [
        {**base, "startColumnIndex": col, "endColumnIndex": col + 1}
        for col in range(col_start, col_end)
    ]


def _range_order_error(
    start: int, end: int | None, start_label: str, end_label: str
) -> dict[str, Any] | None:
    """Return an {"error": ...} dict if end (inclusive, when given) precedes start."""
    if end is not None and end < start:
        return {"error": f"{end_label} ({end}) must be >= {start_label} ({start})"}
    return None


def _positive_value_error(name: str, value: int) -> dict[str, Any] | None:
    """Return an {"error": ...} dict if value is not a positive integer."""
    if value <= 0:
        return {"error": f"{name} must be positive, got {value}"}
    return None


def _non_negative_value_error(name: str, value: int) -> dict[str, Any] | None:
    """Return an {"error": ...} dict if value is negative."""
    if value < 0:
        return {"error": f"{name} must be non-negative, got {value}"}
    return None


def _resolve_end_index_or_error(
    start: int, end: int | None, start_label: str, end_label: str
) -> tuple[dict[str, Any] | None, int | None]:
    """Validate an inclusive end (if given) against start, then compute the
    exclusive end index the Sheets API expects.

    Returns (error, None) on failure, or (None, end_index) on success.
    """
    error = _range_order_error(start, end, start_label, end_label)
    if error:
        return error, None
    return None, (end if end is not None else start) + 1


async def _update_dimension_properties(
    sheets_service,
    spreadsheet_id: str,
    sheet_id: int,
    dimension: str,
    start_index: int,
    end_index: int,
    properties: dict[str, Any],
    fields: str,
) -> dict[str, Any]:
    return await execute_in_thread(
        sheets_service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": dimension,
                                "startIndex": start_index,
                                "endIndex": end_index,
                            },
                            "properties": properties,
                            "fields": fields,
                        }
                    }
                ]
            },
        )
        .execute,
        sheets_service,
    )


async def _auto_resize_dimension(
    sheets_service,
    spreadsheet_id: str,
    sheet_id: int,
    dimension: str,
    start_index: int,
    end_index: int,
) -> dict[str, Any]:
    return await execute_in_thread(
        sheets_service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": sheet_id,
                                "dimension": dimension,
                                "startIndex": start_index,
                                "endIndex": end_index,
                            }
                        }
                    }
                ]
            },
        )
        .execute,
        sheets_service,
    )


def _validate_resize_params(
    start_index: int,
    end_index_inclusive: int | None,
    pixel_size: int | None,
    auto_resize: bool,
    start_label: str,
    end_label: str,
) -> tuple[dict[str, Any] | None, int | None]:
    """Pure parameter validation for resize_rows/resize_columns — no I/O, so it
    can be unit-tested without a mock service.

    Returns (error, None) on failure, or (None, end_index) on success.
    """
    if pixel_size is None and not auto_resize:
        return {"error": "Specify pixel_size or set auto_resize=True"}, None
    if pixel_size is not None and auto_resize:
        return {"error": "Specify only one of pixel_size or auto_resize"}, None

    error = _non_negative_value_error(start_label, start_index)
    if error:
        return error, None

    error, end_index = _resolve_end_index_or_error(
        start_index, end_index_inclusive, start_label, end_label
    )
    if error:
        return error, None

    if pixel_size is not None:
        error = _positive_value_error("pixel_size", pixel_size)
        if error:
            return error, None

    return None, end_index


async def _resize_dimension(
    lc,
    spreadsheet_id: str,
    sheet: str,
    dimension: str,
    start_index: int,
    end_index_inclusive: int | None,
    pixel_size: int | None,
    auto_resize: bool,
    start_label: str,
    end_label: str,
) -> dict[str, Any]:
    """Shared implementation behind resize_rows/resize_columns."""
    sheets_service = lc.sheets_service

    sheet_id = await _get_sheet_id(
        sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
    )
    if sheet_id is None:
        return {"error": f"Sheet '{sheet}' not found"}

    error, end_index = _validate_resize_params(
        start_index, end_index_inclusive, pixel_size, auto_resize, start_label, end_label
    )
    if error:
        return error
    assert end_index is not None  # guaranteed whenever error is None

    if auto_resize:
        return await _auto_resize_dimension(
            sheets_service, spreadsheet_id, sheet_id, dimension, start_index, end_index
        )

    return await _update_dimension_properties(
        sheets_service,
        spreadsheet_id,
        sheet_id,
        dimension,
        start_index,
        end_index,
        {"pixelSize": pixel_size},
        "pixelSize",
    )


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Sheets", readOnlyHint=True))
    async def list_sheets(spreadsheet_id: str, ctx: Context = None) -> list[str]:
        """
        List all sheets in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)

        Returns:
            List of sheet names. Results are cached; call
            refresh_cache(spreadsheet_id=spreadsheet_id) to invalidate, or
            refresh_cache() to clear all caches.
        """
        lc = ctx.request_context.lifespan_context
        sheets = await fetch_sheets(lc.sheets_service, spreadsheet_id, lc.cache, lc.drive_service)
        return [s.title for s in sheets]

    @tool(annotations=ToolAnnotations(title="Copy Sheet", destructiveHint=True))
    async def copy_sheet(
        src_spreadsheet: str,
        src_sheet: str,
        dst_spreadsheet: str,
        dst_sheet: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Copy a sheet from one spreadsheet to another.

        Args:
            src_spreadsheet: Source spreadsheet ID
            src_sheet: Source sheet name
            dst_spreadsheet: Destination spreadsheet ID
            dst_sheet: Destination sheet name

        Returns:
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        src = await execute_in_thread(
            sheets_service.spreadsheets().get(spreadsheetId=src_spreadsheet).execute,
            sheets_service,
        )
        src_sheet_id = next(
            (
                s["properties"]["sheetId"]
                for s in src["sheets"]
                if s["properties"]["title"] == src_sheet
            ),
            None,
        )

        if src_sheet_id is None:
            return {"error": f"Source sheet '{src_sheet}' not found"}

        copy_result = await execute_in_thread(
            sheets_service.spreadsheets()
            .sheets()
            .copyTo(
                spreadsheetId=src_spreadsheet,
                sheetId=src_sheet_id,
                body={"destinationSpreadsheetId": dst_spreadsheet},
            )
            .execute,
            sheets_service,
        )

        result = {"copy": copy_result}

        if copy_result.get("title") != dst_sheet:
            rename_result = await execute_in_thread(
                sheets_service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=dst_spreadsheet,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": copy_result["sheetId"],
                                        "title": dst_sheet,
                                    },
                                    "fields": "title",
                                }
                            }
                        ]
                    },
                )
                .execute,
                sheets_service,
            )
            result["rename"] = rename_result

        lc.cache.mark_dirty(dst_spreadsheet)
        return result

    @tool(annotations=ToolAnnotations(title="Duplicate Sheet", destructiveHint=True))
    async def duplicate_sheet(
        spreadsheet_id: str,
        sheet: str,
        new_name: str | None = None,
        insert_index: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Duplicate a sheet tab within the same spreadsheet.

        Distinct from copy_sheet, which copies a sheet across spreadsheets.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet to duplicate
            new_name: Optional title for the new sheet. Defaults to Google's
                auto-generated name (e.g. "Copy of Sheet1") if omitted.
            insert_index: Optional 0-based tab position for the new sheet.
                Defaults to immediately after the source sheet if omitted.

        Returns:
            Information about the newly created sheet
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        duplicate_request: dict[str, Any] = {"sourceSheetId": sheet_id}
        if insert_index is not None:
            duplicate_request["insertSheetIndex"] = insert_index
        else:
            source_index = await _get_sheet_index(sheets_service, spreadsheet_id, sheet_id)
            if source_index is not None:
                duplicate_request["insertSheetIndex"] = source_index + 1
        if new_name is not None:
            duplicate_request["newSheetName"] = new_name

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"duplicateSheet": duplicate_request}]},
            )
            .execute,
            sheets_service,
        )

        lc.cache.mark_dirty(spreadsheet_id)

        new_sheet_props = result["replies"][0]["duplicateSheet"]["properties"]
        return {
            "sheetId": new_sheet_props["sheetId"],
            "title": new_sheet_props["title"],
            "index": new_sheet_props.get("index"),
            "spreadsheetId": spreadsheet_id,
        }

    @tool(annotations=ToolAnnotations(title="Rename Sheet", destructiveHint=True))
    async def rename_sheet(
        spreadsheet: str, sheet: str, new_name: str, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Rename a sheet in a Google Spreadsheet.

        Args:
            spreadsheet: Spreadsheet ID
            sheet: Current sheet name
            new_name: New sheet name

        Returns:
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        spreadsheet_data = await execute_in_thread(
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet).execute,
            sheets_service,
        )
        sheet_id = next(
            (
                s["properties"]["sheetId"]
                for s in spreadsheet_data["sheets"]
                if s["properties"]["title"] == sheet
            ),
            None,
        )

        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": sheet_id, "title": new_name},
                                "fields": "title",
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

        lc.cache.mark_dirty(spreadsheet)
        return result

    @tool(annotations=ToolAnnotations(title="Create Sheet", destructiveHint=True))
    async def create_sheet(spreadsheet_id: str, title: str, ctx: Context = None) -> dict[str, Any]:
        """
        Create a new sheet tab in an existing Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            title: The title for the new sheet

        Returns:
            Information about the newly created sheet
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            )
            .execute,
            sheets_service,
        )

        lc.cache.mark_dirty(spreadsheet_id)

        new_sheet_props = result["replies"][0]["addSheet"]["properties"]
        return {
            "sheetId": new_sheet_props["sheetId"],
            "title": new_sheet_props["title"],
            "index": new_sheet_props.get("index"),
            "spreadsheetId": spreadsheet_id,
        }

    @tool(annotations=ToolAnnotations(title="Add Rows", destructiveHint=True))
    async def add_rows(
        spreadsheet_id: str,
        sheet: str,
        count: int,
        start_row: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add rows to a sheet in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            count: Number of rows to add
            start_row: 0-based row index to start adding. If not provided, adds at the beginning.

        Returns:
            Result of the operation. Returns {"error": ...} without calling the
            Sheets API if start_row is negative or count isn't positive.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        if start_row is not None:
            error = _non_negative_value_error("start_row", start_row)
            if error:
                return error

        error = _positive_value_error("count", count)
        if error:
            return error

        start = start_row if start_row is not None else 0
        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": start,
                                    "endIndex": start + count,
                                },
                                "inheritFromBefore": start_row is not None and start_row > 0,
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

        return result

    @tool(annotations=ToolAnnotations(title="Add Columns", destructiveHint=True))
    async def add_columns(
        spreadsheet_id: str,
        sheet: str,
        count: int,
        start_column: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add columns to a sheet in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            count: Number of columns to add
            start_column: 0-based column index to start adding. If not provided, adds at the beginning.

        Returns:
            Result of the operation. Returns {"error": ...} without calling the
            Sheets API if start_column is negative or count isn't positive.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        if start_column is not None:
            error = _non_negative_value_error("start_column", start_column)
            if error:
                return error

        error = _positive_value_error("count", count)
        if error:
            return error

        start = start_column if start_column is not None else 0
        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": start,
                                    "endIndex": start + count,
                                },
                                "inheritFromBefore": start_column is not None and start_column > 0,
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

        return result

    @tool(annotations=ToolAnnotations(title="Delete Sheet", destructiveHint=True))
    async def delete_sheet(spreadsheet_id: str, sheet: str, ctx: Context = None) -> dict[str, Any]:
        """
        Delete a sheet tab from a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet to delete

        Returns:
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
            )
            .execute,
            sheets_service,
        )

        lc.cache.mark_dirty(spreadsheet_id)
        return result

    @tool(annotations=ToolAnnotations(title="Delete Rows", destructiveHint=True))
    async def delete_rows(
        spreadsheet_id: str,
        sheet: str,
        start_row: int,
        end_row: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete rows from a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_row: 0-based index of the first row to delete
            end_row: 0-based index of the last row to delete (inclusive).
                     If omitted, deletes only start_row.

        Returns:
            Result of the operation. Returns {"error": ...} without calling the
            Sheets API if start_row is negative or end_row precedes start_row.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        error = _non_negative_value_error("start_row", start_row)
        if error:
            return error

        error, end_index = _resolve_end_index_or_error(start_row, end_row, "start_row", "end_row")
        if error:
            return error

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": start_row,
                                    "endIndex": end_index,
                                }
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Delete Columns", destructiveHint=True))
    async def delete_columns(
        spreadsheet_id: str,
        sheet: str,
        start_column: int,
        end_column: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete columns from a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_column: 0-based index of the first column to delete (0 = column A)
            end_column: 0-based index of the last column to delete (inclusive).
                        If omitted, deletes only start_column.

        Returns:
            Result of the operation. Returns {"error": ...} without calling the
            Sheets API if start_column is negative or end_column precedes start_column.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        error = _non_negative_value_error("start_column", start_column)
        if error:
            return error

        error, end_index = _resolve_end_index_or_error(
            start_column, end_column, "start_column", "end_column"
        )
        if error:
            return error

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": start_column,
                                    "endIndex": end_index,
                                }
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Hide Rows", destructiveHint=True))
    async def hide_rows(
        spreadsheet_id: str,
        sheet: str,
        start_row: int,
        end_row: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Hide rows in a sheet from view.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_row: 0-based index of the first row to hide
            end_row: 0-based index of the last row to hide (inclusive).
                     If omitted, hides only start_row.

        Returns:
            Result of the batchUpdate operation. Returns {"error": ...} without
            calling the Sheets API if start_row is negative or end_row precedes start_row.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        error = _non_negative_value_error("start_row", start_row)
        if error:
            return error

        error, end_index = _resolve_end_index_or_error(start_row, end_row, "start_row", "end_row")
        if error:
            return error

        return await _update_dimension_properties(
            sheets_service,
            spreadsheet_id,
            sheet_id,
            "ROWS",
            start_row,
            end_index,
            {"hiddenByUser": True},
            "hiddenByUser",
        )

    @tool(annotations=ToolAnnotations(title="Unhide Rows", destructiveHint=True))
    async def unhide_rows(
        spreadsheet_id: str,
        sheet: str,
        start_row: int,
        end_row: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Unhide previously hidden rows in a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_row: 0-based index of the first row to unhide
            end_row: 0-based index of the last row to unhide (inclusive).
                     If omitted, unhides only start_row.

        Returns:
            Result of the batchUpdate operation. Returns {"error": ...} without
            calling the Sheets API if start_row is negative or end_row precedes start_row.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        error = _non_negative_value_error("start_row", start_row)
        if error:
            return error

        error, end_index = _resolve_end_index_or_error(start_row, end_row, "start_row", "end_row")
        if error:
            return error

        return await _update_dimension_properties(
            sheets_service,
            spreadsheet_id,
            sheet_id,
            "ROWS",
            start_row,
            end_index,
            {"hiddenByUser": False},
            "hiddenByUser",
        )

    @tool(annotations=ToolAnnotations(title="Hide Columns", destructiveHint=True))
    async def hide_columns(
        spreadsheet_id: str,
        sheet: str,
        start_column: int,
        end_column: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Hide columns in a sheet from view.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_column: 0-based index of the first column to hide (0 = column A)
            end_column: 0-based index of the last column to hide (inclusive).
                        If omitted, hides only start_column.

        Returns:
            Result of the batchUpdate operation. Returns {"error": ...} without
            calling the Sheets API if start_column is negative or end_column precedes start_column.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        error = _non_negative_value_error("start_column", start_column)
        if error:
            return error

        error, end_index = _resolve_end_index_or_error(
            start_column, end_column, "start_column", "end_column"
        )
        if error:
            return error

        return await _update_dimension_properties(
            sheets_service,
            spreadsheet_id,
            sheet_id,
            "COLUMNS",
            start_column,
            end_index,
            {"hiddenByUser": True},
            "hiddenByUser",
        )

    @tool(annotations=ToolAnnotations(title="Unhide Columns", destructiveHint=True))
    async def unhide_columns(
        spreadsheet_id: str,
        sheet: str,
        start_column: int,
        end_column: int | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Unhide previously hidden columns in a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_column: 0-based index of the first column to unhide (0 = column A)
            end_column: 0-based index of the last column to unhide (inclusive).
                        If omitted, unhides only start_column.

        Returns:
            Result of the batchUpdate operation. Returns {"error": ...} without
            calling the Sheets API if start_column is negative or end_column precedes start_column.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        error = _non_negative_value_error("start_column", start_column)
        if error:
            return error

        error, end_index = _resolve_end_index_or_error(
            start_column, end_column, "start_column", "end_column"
        )
        if error:
            return error

        return await _update_dimension_properties(
            sheets_service,
            spreadsheet_id,
            sheet_id,
            "COLUMNS",
            start_column,
            end_index,
            {"hiddenByUser": False},
            "hiddenByUser",
        )

    @tool(annotations=ToolAnnotations(title="Resize Rows", destructiveHint=True))
    async def resize_rows(
        spreadsheet_id: str,
        sheet: str,
        start_row: int,
        end_row: int | None = None,
        pixel_size: int | None = None,
        auto_resize: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Set an explicit pixel height for rows, or auto-fit them to content.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_row: 0-based index of the first row to resize
            end_row: 0-based index of the last row to resize (inclusive).
                     If omitted, resizes only start_row.
            pixel_size: Explicit row height in pixels. Mutually exclusive with auto_resize.
            auto_resize: If True, auto-fit row height to content instead of setting
                         an explicit pixel_size.

        Returns:
            Result of the batchUpdate operation. Returns {"error": ...} without
            calling the Sheets API if start_row is negative, end_row precedes
            start_row, or pixel_size isn't positive.
        """
        lc = ctx.request_context.lifespan_context
        return await _resize_dimension(
            lc,
            spreadsheet_id,
            sheet,
            "ROWS",
            start_row,
            end_row,
            pixel_size,
            auto_resize,
            "start_row",
            "end_row",
        )

    @tool(annotations=ToolAnnotations(title="Resize Columns", destructiveHint=True))
    async def resize_columns(
        spreadsheet_id: str,
        sheet: str,
        start_column: int,
        end_column: int | None = None,
        pixel_size: int | None = None,
        auto_resize: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Set an explicit pixel width for columns, or auto-fit them to content.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            start_column: 0-based index of the first column to resize (0 = column A)
            end_column: 0-based index of the last column to resize (inclusive).
                        If omitted, resizes only start_column.
            pixel_size: Explicit column width in pixels. Mutually exclusive with auto_resize.
            auto_resize: If True, auto-fit column width to content instead of setting
                         an explicit pixel_size.

        Returns:
            Result of the batchUpdate operation. Returns {"error": ...} without
            calling the Sheets API if start_column is negative, end_column precedes
            start_column, or pixel_size isn't positive.
        """
        lc = ctx.request_context.lifespan_context
        return await _resize_dimension(
            lc,
            spreadsheet_id,
            sheet,
            "COLUMNS",
            start_column,
            end_column,
            pixel_size,
            auto_resize,
            "start_column",
            "end_column",
        )

    @tool(annotations=ToolAnnotations(title="Format Cells", destructiveHint=True))
    async def format_cells(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        bold: bool | None = None,
        italic: bool | None = None,
        strikethrough: bool | None = None,
        font_size: int | None = None,
        font_color: dict | None = None,
        background_color: dict | None = None,
        horizontal_alignment: str | None = None,
        vertical_alignment: str | None = None,
        number_format_type: str | None = None,
        number_format_pattern: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply formatting to a cell range (background color, font, alignment, number format).

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to format (e.g. "A1:D5")
            bold: Set bold text
            italic: Set italic text
            strikethrough: Set strikethrough
            font_size: Font size in points
            font_color: RGB color dict, e.g. {"red": 1.0, "green": 0.0, "blue": 0.0}
            background_color: RGB color dict for cell background
            horizontal_alignment: "LEFT", "CENTER", or "RIGHT"
            vertical_alignment: "TOP", "MIDDLE", or "BOTTOM"
            number_format_type: "TEXT", "NUMBER", "PERCENT", "CURRENCY", "DATE",
                                "TIME", "DATE_TIME", "SCIENTIFIC"
            number_format_pattern: Custom number format pattern, e.g. "#,##0.00"

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        cell_format: dict[str, Any] = {}
        fields: list[str] = []

        text_format: dict[str, Any] = {}
        if bold is not None:
            text_format["bold"] = bold
        if italic is not None:
            text_format["italic"] = italic
        if strikethrough is not None:
            text_format["strikethrough"] = strikethrough
        if font_size is not None:
            text_format["fontSize"] = font_size
        if font_color is not None:
            text_format["foregroundColor"] = font_color
        if text_format:
            cell_format["textFormat"] = text_format
            fields.append("userEnteredFormat.textFormat")

        if background_color is not None:
            cell_format["backgroundColor"] = background_color
            fields.append("userEnteredFormat.backgroundColor")

        if horizontal_alignment is not None:
            cell_format["horizontalAlignment"] = horizontal_alignment.upper()
            fields.append("userEnteredFormat.horizontalAlignment")

        if vertical_alignment is not None:
            cell_format["verticalAlignment"] = vertical_alignment.upper()
            fields.append("userEnteredFormat.verticalAlignment")

        if number_format_type is not None or number_format_pattern is not None:
            number_format: dict[str, Any] = {}
            if number_format_type is not None:
                number_format["type"] = number_format_type.upper()
            if number_format_pattern is not None:
                number_format["pattern"] = number_format_pattern
            cell_format["numberFormat"] = number_format
            fields.append("userEnteredFormat.numberFormat")

        if not fields:
            return {"error": "No formatting parameters provided"}

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": _grid_range(sheet_id, range),
                                "cell": {"userEnteredFormat": cell_format},
                                "fields": ",".join(fields),
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Update Borders", destructiveHint=True))
    async def update_borders(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        top: dict | None = None,
        bottom: dict | None = None,
        left: dict | None = None,
        right: dict | None = None,
        inner_horizontal: dict | None = None,
        inner_vertical: dict | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply or clear borders on the edges of a cell range.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to border (e.g. "A1:D5")
            top: Border spec for the top edge of the range, e.g.
                 {"style": "SOLID", "color": {"red": 0.0, "green": 0.0, "blue": 0.0}}.
                 "style" is required and must be one of "DOTTED", "DASHED", "SOLID",
                 "SOLID_MEDIUM", "SOLID_THICK", "DOUBLE", or "NONE" (clears the border).
                 "color" is an optional RGB dict. "width" is optional and deprecated
                 by the Sheets API in favor of "style", but still accepted.
            bottom: Border spec for the bottom edge, same shape as top.
            left: Border spec for the left edge, same shape as top.
            right: Border spec for the right edge, same shape as top.
            inner_horizontal: Border spec for the horizontal lines between rows
                               inside the range, same shape as top.
            inner_vertical: Border spec for the vertical lines between columns
                             inside the range, same shape as top.

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        edges = {
            "top": top,
            "bottom": bottom,
            "left": left,
            "right": right,
            "innerHorizontal": inner_horizontal,
            "innerVertical": inner_vertical,
        }
        provided = {key: value for key, value in edges.items() if value is not None}
        if not provided:
            return {"error": "No border parameters provided"}

        update_borders_request: dict[str, Any] = {}
        for key, border in provided.items():
            if "style" not in border:
                return {"error": f"Border spec for '{key}' is missing required 'style' key"}
            if not isinstance(border["style"], str):
                return {"error": f"Border spec for '{key}' has a non-string 'style' value"}
            error = _enum_value_error(
                border["style"], _VALID_BORDER_STYLES, "border style", f"for '{key}'"
            )
            if error:
                return error
            update_borders_request[key] = _border_spec(border)

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        update_borders_request["range"] = _grid_range(sheet_id, range)

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"updateBorders": update_borders_request}]},
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Add Data Validation", destructiveHint=True))
    async def add_data_validation(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        condition_type: str,
        values: list[str] | None = None,
        input_message: str | None = None,
        strict: bool = True,
        show_custom_ui: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Set a data validation rule on a cell range — dropdown lists, checkboxes, or
        date/number/text constraints.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to validate (e.g. "A2:A100")
            condition_type: One of the Sheets API's condition types:
                "ONE_OF_LIST"      — dropdown of custom values (values = the list items)
                "ONE_OF_RANGE"     — dropdown sourced from another range (values = one
                                     item, the source range in A1 notation, e.g.
                                     ["Sheet2!A:A"] — a leading "=" is added
                                     automatically if you omit it)
                "BOOLEAN"          — checkbox (omit values for a plain TRUE/FALSE
                                     checkbox, or give two values for custom
                                     checked/unchecked labels)
                "NUMBER_GREATER", "NUMBER_GREATER_THAN_EQ", "NUMBER_LESS",
                "NUMBER_LESS_THAN_EQ", "NUMBER_EQ", "NUMBER_NOT_EQ" — one numeric value
                "NUMBER_BETWEEN", "NUMBER_NOT_BETWEEN" — two numeric values
                "DATE_EQ", "DATE_BEFORE", "DATE_AFTER", "DATE_ON_OR_BEFORE",
                "DATE_ON_OR_AFTER" — one date value, e.g. "2025-01-01"
                "DATE_BETWEEN", "DATE_NOT_BETWEEN" — two date values
                "DATE_IS_VALID"    — no values; any parseable date passes
                "TEXT_CONTAINS", "TEXT_NOT_CONTAINS", "TEXT_STARTS_WITH",
                "TEXT_ENDS_WITH", "TEXT_EQ" — one text value
                "TEXT_IS_EMAIL", "TEXT_IS_URL" — no values
                "BLANK", "NOT_BLANK" — no values
                "CUSTOM_FORMULA"   — one formula string, e.g. "=A1>0"
            values: Condition values as plain strings — see condition_type above for
                    how many each type expects. Numbers and dates are passed as
                    strings; the Sheets API parses them per the cell's format.
            input_message: Optional help text shown when a user selects a cell in range.
            strict: If True (default), reject input that fails the rule. If False,
                    show a warning but still allow it.
            show_custom_ui: If True (default), show the built-in dropdown/checkbox UI
                    for condition types that support one (ONE_OF_LIST, ONE_OF_RANGE,
                    BOOLEAN). Ignored by condition types with no UI (e.g. NUMBER_*,
                    TEXT_*).

        Returns:
            Result of the batchUpdate operation.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        error = _enum_value_error(condition_type, _VALID_CONDITION_TYPES, "condition_type")
        if error:
            return error
        normalized_type = condition_type.upper()

        error = _condition_value_count_error(normalized_type, values)
        if error:
            return error

        condition: dict[str, Any] = {"type": normalized_type}
        if values:
            # ONE_OF_RANGE's userEnteredValue must be a formula-style range reference
            # (a leading "=") or the real Sheets API rejects it with a 400 — confirmed
            # live in PR #361 review (TC-S99). Auto-prepend rather than erroring, since
            # a bare "Sheet2!A:A" (no "=") is the more natural way to write a range.
            if normalized_type == "ONE_OF_RANGE":
                condition["values"] = [
                    {"userEnteredValue": v if v.startswith("=") else f"={v}"} for v in values
                ]
            else:
                condition["values"] = [{"userEnteredValue": str(v)} for v in values]

        rule: dict[str, Any] = {
            "condition": condition,
            "strict": strict,
            "showCustomUi": show_custom_ui,
        }
        if input_message is not None:
            rule["inputMessage"] = input_message

        return await _apply_data_validation(
            sheets_service, spreadsheet_id, sheet, range, lc.cache, lc.drive_service, rule
        )

    @tool(annotations=ToolAnnotations(title="Get Data Validation", readOnlyHint=True))
    async def get_data_validation(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        ctx: Context = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Read existing data validation rules for a cell range.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to inspect (e.g. "A1:A100")

        Returns:
            List of {cell, rule} for every cell in the range that has a validation
            rule; cells without one are omitted. 'rule' matches the Sheets API's
            DataValidationRule shape: {condition: {type, values}, inputMessage,
            strict, showCustomUi}. Returns {"error": ...} if the sheet isn't found.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        # Every other sheet-taking tool in this file checks existence first — this
        # one didn't, and a bad sheet name raised a raw HttpError straight through
        # to the client instead of the clean {"error": ...} its sibling
        # add_data_validation already returns (PR #361 review, TC-S100).
        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        quoted = _quote_sheet_name(sheet)
        full_range = f"{quoted}!{range}"

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                ranges=[full_range],
                fields="sheets.data(startRow,startColumn,rowData.values.dataValidation)",
            )
            .execute,
            sheets_service,
        )

        sheets_data = result.get("sheets", [])
        if not sheets_data:
            return []
        grid_data_list = sheets_data[0].get("data", [])
        if not grid_data_list:
            return []
        grid_data = grid_data_list[0]

        start_row = grid_data.get("startRow", 0)
        start_col = grid_data.get("startColumn", 0)

        matches: list[dict[str, Any]] = []
        for row_offset, row in enumerate(grid_data.get("rowData", [])):
            for col_offset, cell in enumerate(row.get("values", [])):
                rule = cell.get("dataValidation")
                if rule is None:
                    continue
                row_index = start_row + row_offset
                col_index = start_col + col_offset
                cell_ref = f"{_column_index_to_letter(col_index)}{row_index + 1}"
                matches.append({"cell": cell_ref, "rule": rule})

        return matches

    @tool(annotations=ToolAnnotations(title="Clear Data Validation", destructiveHint=True))
    async def clear_data_validation(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Clear any data validation rule from a cell range.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to clear (e.g. "A2:A100")

        Returns:
            Result of the batchUpdate operation.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        return await _apply_data_validation(
            sheets_service, spreadsheet_id, sheet, range, lc.cache, lc.drive_service, None
        )

    @tool(annotations=ToolAnnotations(title="Merge Cells", destructiveHint=True))
    async def merge_cells(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        merge_type: str = "MERGE_ALL",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Merge a range of cells into one cell.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to merge (e.g. "A1:C3")
            merge_type: "MERGE_ALL" (default), "MERGE_COLUMNS" (merge each column
                        independently), or "MERGE_ROWS" (merge each row independently)

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "mergeCells": {
                                "range": _grid_range(sheet_id, range),
                                "mergeType": merge_type.upper(),
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Unmerge Cells", destructiveHint=True))
    async def unmerge_cells(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Unmerge all merged cells in a range.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to unmerge (e.g. "A1:C3")

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"unmergeCells": {"range": _grid_range(sheet_id, range)}}]},
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Freeze Rows/Columns"))
    async def freeze(
        spreadsheet_id: str,
        sheet: str,
        rows: int = 0,
        columns: int = 0,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Freeze rows and/or columns in a sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            rows: Number of rows to freeze (0 to unfreeze all rows)
            columns: Number of columns to freeze (0 to unfreeze all columns)

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": sheet_id,
                                    "gridProperties": {
                                        "frozenRowCount": rows,
                                        "frozenColumnCount": columns,
                                    },
                                },
                                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Update Sheet Properties"))
    async def update_sheet_properties(
        spreadsheet_id: str,
        sheet: str,
        tab_color: dict | None = None,
        show_gridlines: bool | None = None,
        right_to_left: bool | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Update sheet-level display properties: tab color, gridline visibility,
        right-to-left layout.

        Note: the Sheets API does not expose row/column header visibility as a
        settable sheet property, so it isn't included here. Frozen row/column
        counts are handled separately by the freeze tool.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            tab_color: RGB color dict for the sheet tab, e.g.
                       {"red": 1.0, "green": 0.0, "blue": 0.0}. Pass {} to
                       clear the tab color back to the default.
            show_gridlines: Whether gridlines are shown in the UI. False hides them.
            right_to_left: Whether the sheet uses right-to-left layout.

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        properties: dict[str, Any] = {"sheetId": sheet_id}
        fields: list[str] = []

        if tab_color is not None:
            if tab_color == {}:
                # tabColor has no explicit-presence tracking on the wire, so an
                # empty dict is indistinguishable from black (0,0,0). The newer
                # tabColorStyle field does support clearing back to the default.
                properties["tabColorStyle"] = {}
                fields.append("tabColorStyle")
            else:
                properties["tabColor"] = tab_color
                fields.append("tabColor")

        if show_gridlines is not None:
            properties["gridProperties"] = {"hideGridlines": not show_gridlines}
            fields.append("gridProperties.hideGridlines")

        if right_to_left is not None:
            properties["rightToLeft"] = right_to_left
            fields.append("rightToLeft")

        if not fields:
            return {"error": "No properties provided to update"}

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": properties,
                                "fields": ",".join(fields),
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Sort Range"))
    async def sort_range(
        spreadsheet_id: str,
        sheet: str,
        range: str,
        sort_order: list[dict] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Sort a range by one or more columns.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            sheet: The name of the sheet
            range: A1 notation range to sort (e.g. "A1:D100")
            sort_order: List of sort specs, each with:
                        - "column_index": 0-based column index within the range
                        - "order": "ASCENDING" (default) or "DESCENDING"
                        If omitted, sorts by the first column ascending.

        Returns:
            Result of the batchUpdate operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        grid_range = _grid_range(sheet_id, range)
        col_start = grid_range["startColumnIndex"]

        if sort_order is None:
            sort_order = [{"column_index": 0, "order": "ASCENDING"}]

        sort_specs = []
        for i, s in enumerate(sort_order):
            if "column_index" not in s:
                return {"error": f"Sort spec at index {i} is missing required 'column_index' key"}
            if not isinstance(s["column_index"], int) or isinstance(s["column_index"], bool):
                return {"error": f"Sort spec at index {i} has a non-integer 'column_index' value"}

            order = s.get("order", "ASCENDING")
            if not isinstance(order, str):
                return {
                    "error": f"Sort spec for column_index {s['column_index']} "
                    "has a non-string 'order' value"
                }
            error = _enum_value_error(
                order, _VALID_SORT_ORDERS, "sort order", f"for column_index {s['column_index']}"
            )
            if error:
                return error

            sort_specs.append(
                {
                    "dimensionIndex": col_start + s["column_index"],
                    "sortOrder": order.upper(),
                }
            )

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "sortRange": {
                                "range": grid_range,
                                "sortSpecs": sort_specs,
                            }
                        }
                    ]
                },
            )
            .execute,
            sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Add Chart", destructiveHint=True))
    async def add_chart(
        spreadsheet_id: str,
        sheet: str,
        chart_type: str,
        data_range: str,
        title: str | None = None,
        x_axis_label: str | None = None,
        y_axis_label: str | None = None,
        position_x: int = 0,
        position_y: int = 0,
        width: int = 600,
        height: int = 400,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add a chart to a Google Spreadsheet.

        Creates a chart from the specified data range with customizable type, title, and positioning.
        The chart is added as a floating element on the sheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet containing the data
            chart_type: Type of chart to create. Supported types:
                       - COLUMN: Vertical bar chart
                       - BAR: Horizontal bar chart
                       - LINE: Line chart
                       - AREA: Area chart
                       - PIE: Pie chart
                       - SCATTER: Scatter plot
                       - COMBO: Combination chart
                       - HISTOGRAM: Histogram
            data_range: A1 notation range for chart data (e.g., 'A1:C10').
                       The first row is typically treated as headers.
            title: Optional title for the chart
            x_axis_label: Optional label for the X axis (bottom axis)
            y_axis_label: Optional label for the Y axis (left axis)
            position_x: Horizontal position offset in pixels from the top-left corner (default: 0)
            position_y: Vertical position offset in pixels from the top-left corner (default: 0)
            width: Width of the chart in pixels (default: 600)
            height: Height of the chart in pixels (default: 400)

        Returns:
            Result of the chart creation operation

        Examples:
            Create a column chart showing sales data:
            add_chart(
                spreadsheet_id="abc123",
                sheet="Sales",
                chart_type="COLUMN",
                data_range="A1:B13",
                title="Monthly Sales",
                x_axis_label="Month",
                y_axis_label="Revenue ($)"
            )

            Create a pie chart for market share:
            add_chart(
                spreadsheet_id="abc123",
                sheet="Market",
                chart_type="PIE",
                data_range="A1:B5",
                title="Market Share by Product"
            )
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        error = _enum_value_error(chart_type, _VALID_CHART_TYPES, "chart type")
        if error:
            return error
        chart_type = chart_type.upper()

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found in spreadsheet"}

        try:
            range_indices = _parse_a1_notation(data_range)
        except ValueError as e:
            return {"error": str(e)}

        col_ranges = _per_column_ranges(sheet_id, range_indices)
        domain_col = col_ranges[0]
        series_cols = col_ranges[1:] if len(col_ranges) > 1 else col_ranges

        if chart_type == "PIE":
            chart_spec: dict[str, Any] = {
                "pieChart": {
                    "legendPosition": "RIGHT_LEGEND",
                    "domain": {"sourceRange": {"sources": [domain_col]}},
                    "series": {"sourceRange": {"sources": [series_cols[0]]}},
                }
            }
            if title:
                chart_spec["title"] = title

        elif chart_type == "HISTOGRAM":
            chart_spec = {
                "histogramChart": {
                    "legendPosition": "RIGHT_LEGEND",
                    "series": [{"data": {"sourceRange": {"sources": [col]}}} for col in col_ranges],
                }
            }
            if title:
                chart_spec["title"] = title

        else:
            # BAR charts use a horizontal value axis; all other basic types use LEFT_AXIS.
            series_axis = "BOTTOM_AXIS" if chart_type == "BAR" else "LEFT_AXIS"

            def _series_entry(col, idx, total):
                entry = {
                    "series": {"sourceRange": {"sources": [col]}},
                    "targetAxis": series_axis,
                }
                # COMBO requires an explicit per-series type; default to COLUMN + LINE overlay.
                if chart_type == "COMBO":
                    entry["type"] = "LINE" if idx == total - 1 else "COLUMN"
                return entry

            chart_spec = {
                "basicChart": {
                    "chartType": chart_type,
                    "legendPosition": "RIGHT_LEGEND",
                    "axis": [],
                    "domains": [{"domain": {"sourceRange": {"sources": [domain_col]}}}],
                    "series": [
                        _series_entry(col, i, len(series_cols)) for i, col in enumerate(series_cols)
                    ],
                    "headerCount": 1,
                }
            }
            if title:
                chart_spec["title"] = title

            chart_spec["basicChart"]["axis"].append(
                {"position": "BOTTOM_AXIS", "title": x_axis_label}
                if x_axis_label
                else {"position": "BOTTOM_AXIS"}
            )
            chart_spec["basicChart"]["axis"].append(
                {"position": "LEFT_AXIS", "title": y_axis_label}
                if y_axis_label
                else {"position": "LEFT_AXIS"}
            )

        try:
            result = await execute_in_thread(
                sheets_service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "addChart": {
                                    "chart": {
                                        "spec": chart_spec,
                                        "position": {
                                            "overlayPosition": {
                                                "anchorCell": {
                                                    "sheetId": sheet_id,
                                                    "rowIndex": 0,
                                                    "columnIndex": 0,
                                                },
                                                "offsetXPixels": position_x,
                                                "offsetYPixels": position_y,
                                                "widthPixels": width,
                                                "heightPixels": height,
                                            }
                                        },
                                    }
                                }
                            }
                        ]
                    },
                )
                .execute,
                sheets_service,
            )

            return {
                "success": True,
                "message": f"Chart '{title or chart_type}' added successfully",
                "chartId": result.get("replies", [{}])[0]
                .get("addChart", {})
                .get("chart", {})
                .get("chartId"),
                "result": result,
            }
        except Exception as e:
            return {"error": f"Failed to add chart: {e!s}"}
