from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...cache import fetch_sheets
from .helpers import _get_sheet_id, _get_sheet_index, _parse_a1_notation

_VALID_CHART_TYPES = ["COLUMN", "BAR", "LINE", "AREA", "PIE", "SCATTER", "COMBO", "HISTOGRAM"]


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
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

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
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

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
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        end_index = (end_row if end_row is not None else start_row) + 1  # exclusive

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
            Result of the operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        sheet_id = await _get_sheet_id(
            sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
        )
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        end_index = (end_column if end_column is not None else start_column) + 1  # exclusive

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

        indices = _parse_a1_notation(range)

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

        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": indices.get("startRowIndex", 0),
            "startColumnIndex": indices.get("startColumnIndex", 0),
        }
        if "endRowIndex" in indices:
            grid_range["endRowIndex"] = indices["endRowIndex"]
        if "endColumnIndex" in indices:
            grid_range["endColumnIndex"] = indices["endColumnIndex"]

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": grid_range,
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

        indices = _parse_a1_notation(range)
        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": indices.get("startRowIndex", 0),
            "startColumnIndex": indices.get("startColumnIndex", 0),
        }
        if "endRowIndex" in indices:
            grid_range["endRowIndex"] = indices["endRowIndex"]
        if "endColumnIndex" in indices:
            grid_range["endColumnIndex"] = indices["endColumnIndex"]

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "mergeCells": {
                                "range": grid_range,
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

        indices = _parse_a1_notation(range)
        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": indices.get("startRowIndex", 0),
            "startColumnIndex": indices.get("startColumnIndex", 0),
        }
        if "endRowIndex" in indices:
            grid_range["endRowIndex"] = indices["endRowIndex"]
        if "endColumnIndex" in indices:
            grid_range["endColumnIndex"] = indices["endColumnIndex"]

        return await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"unmergeCells": {"range": grid_range}}]},
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

        indices = _parse_a1_notation(range)
        col_start = indices.get("startColumnIndex", 0)

        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": indices.get("startRowIndex", 0),
            "startColumnIndex": col_start,
        }
        if "endRowIndex" in indices:
            grid_range["endRowIndex"] = indices["endRowIndex"]
        if "endColumnIndex" in indices:
            grid_range["endColumnIndex"] = indices["endColumnIndex"]

        if sort_order is None:
            sort_order = [{"column_index": 0, "order": "ASCENDING"}]

        sort_specs = [
            {
                "dimensionIndex": col_start + s["column_index"],
                "sortOrder": s.get("order", "ASCENDING").upper(),
            }
            for s in sort_order
        ]

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

        chart_type = chart_type.upper()
        if chart_type not in _VALID_CHART_TYPES:
            return {
                "error": f"Invalid chart type '{chart_type}'. Must be one of: {', '.join(_VALID_CHART_TYPES)}"
            }

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
