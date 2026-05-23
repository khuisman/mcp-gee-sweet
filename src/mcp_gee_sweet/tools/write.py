from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..helpers import _get_sheet_id, _quote_sheet_name


def register(tool):
    @tool(annotations=ToolAnnotations(title="Update Cells", destructiveHint=True))
    def update_cells(
        spreadsheet_id: str, sheet: str, range: str, data: list[list[Any]], ctx: Context = None
    ) -> dict[str, Any]:
        """
        Update cells in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            range: Cell range in A1 notation (e.g., 'A1:C10')
            data: 2D array of values to update

        Returns:
            Result of the update operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        result = (
            sheets_service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"{_quote_sheet_name(sheet)}!{range}",
                valueInputOption="USER_ENTERED",
                body={"values": data},
            )
            .execute()
        )

        lc.sheet_data_cache.mark_dirty(spreadsheet_id)
        return result

    @tool(annotations=ToolAnnotations(title="Batch Update Cells", destructiveHint=True))
    def batch_update_cells(
        spreadsheet_id: str, sheet: str, ranges: dict[str, list[list[Any]]], ctx: Context = None
    ) -> dict[str, Any]:
        """
        Batch update multiple ranges in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            ranges: Dictionary mapping range strings to 2D arrays of values
                   e.g., {'A1:B2': [[1, 2], [3, 4]], 'D1:E2': [['a', 'b'], ['c', 'd']]}

        Returns:
            Result of the batch update operation
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        data = [
            {"range": f"{_quote_sheet_name(sheet)}!{range_str}", "values": values}
            for range_str, values in ranges.items()
        ]

        result = (
            sheets_service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": data},
            )
            .execute()
        )

        lc.sheet_data_cache.mark_dirty(spreadsheet_id)
        return result

    @tool(annotations=ToolAnnotations(title="Add Rows", destructiveHint=True))
    def add_rows(
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

        sheet_id = _get_sheet_id(sheets_service, spreadsheet_id, sheet, lc.cache)
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        start = start_row if start_row is not None else 0
        result = (
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
            .execute()
        )

        return result

    @tool(annotations=ToolAnnotations(title="Add Columns", destructiveHint=True))
    def add_columns(
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

        sheet_id = _get_sheet_id(sheets_service, spreadsheet_id, sheet, lc.cache)
        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        start = start_column if start_column is not None else 0
        result = (
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
            .execute()
        )

        return result

    @tool(annotations=ToolAnnotations(title="Batch Update", destructiveHint=True))
    def batch_update(
        spreadsheet_id: str, requests: list[dict[str, Any]], ctx: Context = None
    ) -> dict[str, Any]:
        """
        Execute a batch update on a Google Spreadsheet using the full batchUpdate endpoint.
        This provides access to all batchUpdate operations including adding sheets, updating properties,
        inserting/deleting dimensions, formatting, and more.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            requests: A list of request objects. Each request object can contain any valid batchUpdate operation.
                     Common operations include:
                     - addSheet: Add a new sheet
                     - updateSheetProperties: Update sheet properties (title, grid properties, etc.)
                     - insertDimension: Insert rows or columns
                     - deleteDimension: Delete rows or columns
                     - updateCells: Update cell values and formatting
                     - updateBorders: Update cell borders
                     - addConditionalFormatRule: Add conditional formatting
                     - deleteConditionalFormatRule: Remove conditional formatting
                     - updateDimensionProperties: Update row/column properties
                     - and many more...

                     Example requests:
                     [
                         {
                             "addSheet": {
                                 "properties": {
                                     "title": "New Sheet"
                                 }
                             }
                         },
                         {
                             "updateSheetProperties": {
                                 "properties": {
                                     "sheetId": 0,
                                     "title": "Renamed Sheet"
                                 },
                                 "fields": "title"
                             }
                         },
                         {
                             "insertDimension": {
                                 "range": {
                                     "sheetId": 0,
                                     "dimension": "ROWS",
                                     "startIndex": 1,
                                     "endIndex": 3
                                 }
                             }
                         }
                     ]

        Returns:
            Result of the batch update operation, including replies for each request
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        if not requests:
            return {"error": "requests list cannot be empty"}
        if not all(isinstance(req, dict) for req in requests):
            return {"error": "Each request must be a dictionary"}

        result = (
            sheets_service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
            .execute()
        )

        lc.cache.mark_dirty(spreadsheet_id)
        lc.sheet_data_cache.mark_dirty(spreadsheet_id)
        return result
