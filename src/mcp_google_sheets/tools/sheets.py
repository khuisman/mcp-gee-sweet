from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Sheets", readOnlyHint=True))
    def list_sheets(spreadsheet_id: str, ctx: Context = None) -> List[str]:
        """
        List all sheets in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)

        Returns:
            List of sheet names
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return [sheet['properties']['title'] for sheet in spreadsheet['sheets']]

    @tool(annotations=ToolAnnotations(title="Copy Sheet", destructiveHint=True))
    def copy_sheet(src_spreadsheet: str,
                   src_sheet: str,
                   dst_spreadsheet: str,
                   dst_sheet: str,
                   ctx: Context = None) -> Dict[str, Any]:
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
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        src = sheets_service.spreadsheets().get(spreadsheetId=src_spreadsheet).execute()
        src_sheet_id = next(
            (s['properties']['sheetId'] for s in src['sheets']
             if s['properties']['title'] == src_sheet),
            None
        )

        if src_sheet_id is None:
            return {"error": f"Source sheet '{src_sheet}' not found"}

        copy_result = sheets_service.spreadsheets().sheets().copyTo(
            spreadsheetId=src_spreadsheet,
            sheetId=src_sheet_id,
            body={"destinationSpreadsheetId": dst_spreadsheet}
        ).execute()

        if 'title' in copy_result and copy_result['title'] != dst_sheet:
            rename_result = sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=dst_spreadsheet,
                body={"requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": copy_result['sheetId'], "title": dst_sheet},
                    "fields": "title"
                }}]}
            ).execute()
            return {"copy": copy_result, "rename": rename_result}

        return {"copy": copy_result}

    @tool(annotations=ToolAnnotations(title="Rename Sheet", destructiveHint=True))
    def rename_sheet(spreadsheet: str,
                     sheet: str,
                     new_name: str,
                     ctx: Context = None) -> Dict[str, Any]:
        """
        Rename a sheet in a Google Spreadsheet.

        Args:
            spreadsheet: Spreadsheet ID
            sheet: Current sheet name
            new_name: New sheet name

        Returns:
            Result of the operation
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        spreadsheet_data = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet).execute()
        sheet_id = next(
            (s['properties']['sheetId'] for s in spreadsheet_data['sheets']
             if s['properties']['title'] == sheet),
            None
        )

        if sheet_id is None:
            return {"error": f"Sheet '{sheet}' not found"}

        result = sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet,
            body={"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "title": new_name},
                "fields": "title"
            }}]}
        ).execute()

        return result

    @tool(annotations=ToolAnnotations(title="Create Sheet", destructiveHint=True))
    def create_sheet(spreadsheet_id: str,
                     title: str,
                     ctx: Context = None) -> Dict[str, Any]:
        """
        Create a new sheet tab in an existing Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet
            title: The title for the new sheet

        Returns:
            Information about the newly created sheet
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        result = sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]}
        ).execute()

        new_sheet_props = result['replies'][0]['addSheet']['properties']
        return {
            'sheetId': new_sheet_props['sheetId'],
            'title': new_sheet_props['title'],
            'index': new_sheet_props.get('index'),
            'spreadsheetId': spreadsheet_id
        }
