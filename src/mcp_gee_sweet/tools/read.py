from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..cache import SheetInfo, fetch_sheets
from ..helpers import _column_index_to_letter, _quote_sheet_name


def register(tool):
    @tool(annotations=ToolAnnotations(title="Get Sheet Data", readOnlyHint=True))
    def get_sheet_data(
        spreadsheet_id: str,
        sheet: str,
        range: str | None = None,
        include_grid_data: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Get data from a specific sheet in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            range: Optional cell range in A1 notation (e.g., 'A1:C10'). If not provided, gets all data.
            include_grid_data: If True, includes cell formatting and other metadata in the response.
                Note: Setting this to True will significantly increase the response size and token usage
                when parsing the response, as it includes detailed cell formatting information.
                Default is False (returns values only, more efficient).

        Returns:
            Grid data structure with either full metadata or just values from Google Sheets API, depending on include_grid_data parameter
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        quoted = _quote_sheet_name(sheet)
        full_range = f"{quoted}!{range}" if range else quoted

        if include_grid_data:
            result = (
                sheets_service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id, ranges=[full_range], includeGridData=True)
                .execute()
            )
        else:
            values_result = (
                sheets_service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=full_range)
                .execute()
            )
            result = {
                "spreadsheetId": spreadsheet_id,
                "valueRanges": [{"range": full_range, "values": values_result.get("values", [])}],
            }

        return result

    @tool(annotations=ToolAnnotations(title="Get Sheet Formulas", readOnlyHint=True))
    def get_sheet_formulas(
        spreadsheet_id: str, sheet: str, range: str | None = None, ctx: Context = None
    ) -> list[list[Any]]:
        """
        Get formulas from a specific sheet in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            range: Optional cell range in A1 notation (e.g., 'A1:C10'). If not provided, gets all formulas from the sheet.

        Returns:
            A 2D array of the sheet formulas.
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        quoted = _quote_sheet_name(sheet)
        full_range = f"{quoted}!{range}" if range else quoted

        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=full_range, valueRenderOption="FORMULA")
            .execute()
        )

        return result.get("values", [])

    @tool(annotations=ToolAnnotations(title="Get Multiple Sheet Data", readOnlyHint=True))
    def get_multiple_sheet_data(
        queries: list[dict[str, str]], ctx: Context = None
    ) -> list[dict[str, Any]]:
        """
        Get data from multiple specific ranges in Google Spreadsheets.

        Args:
            queries: A list of dictionaries, each specifying a query.
                     Each dictionary should have 'spreadsheet_id', 'sheet', and 'range' keys.
                     Example: [{'spreadsheet_id': 'abc', 'sheet': 'Sheet1', 'range': 'A1:B5'},
                               {'spreadsheet_id': 'xyz', 'sheet': 'Data', 'range': 'C1:C10'}]

        Returns:
            A list of dictionaries, each containing the original query parameters
            and the fetched 'data' or an 'error'.
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service
        results = []

        for query in queries:
            spreadsheet_id = query.get("spreadsheet_id")
            sheet = query.get("sheet")
            range_str = query.get("range")

            if not all([spreadsheet_id, sheet, range_str]):
                results.append(
                    {**query, "error": "Missing required keys (spreadsheet_id, sheet, range)"}
                )
                continue

            try:
                full_range = f"{_quote_sheet_name(str(sheet))}!{range_str}"
                result = (
                    sheets_service.spreadsheets()
                    .values()
                    .get(spreadsheetId=spreadsheet_id, range=full_range)
                    .execute()
                )
                results.append({**query, "data": result.get("values", [])})
            except Exception as e:
                results.append({**query, "error": str(e)})

        return results

    @tool(annotations=ToolAnnotations(title="Get Multiple Spreadsheet Summary", readOnlyHint=True))
    def get_multiple_spreadsheet_summary(
        spreadsheet_ids: list[str], rows_to_fetch: int = 5, ctx: Context = None
    ) -> list[dict[str, Any]]:
        """
        Get a summary of multiple Google Spreadsheets, including sheet names,
        headers, and the first few rows of data for each sheet.

        Args:
            spreadsheet_ids: A list of spreadsheet IDs to summarize.
            rows_to_fetch: The number of rows (including header) to fetch for the summary (default: 5).

        Returns:
            A list of dictionaries, each representing a spreadsheet summary.
            Includes spreadsheet title, sheet summaries (title, headers, first rows), or an error.
            Results are cached; call refresh_cache(spreadsheet_id=<id>) to invalidate,
            or refresh_cache() to clear all caches.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service
        data_cache = lc.sheet_data_cache
        structure_cache = lc.cache
        summaries = []

        for spreadsheet_id in spreadsheet_ids:
            summary_data = {
                "spreadsheet_id": spreadsheet_id,
                "title": None,
                "sheets": [],
                "error": None,
            }
            try:
                cached_sheets = structure_cache.get_sheets(spreadsheet_id)
                cached_title = structure_cache.get_title(spreadsheet_id)

                if cached_sheets is not None and cached_title is not None:
                    sheet_infos = cached_sheets
                    summary_data["title"] = cached_title
                else:
                    spreadsheet = (
                        sheets_service.spreadsheets()
                        .get(
                            spreadsheetId=spreadsheet_id,
                            fields="properties.title,sheets(properties(title,sheetId))",
                        )
                        .execute()
                    )
                    title = spreadsheet.get("properties", {}).get("title", "Unknown Title")
                    summary_data["title"] = title
                    sheet_infos = [
                        SheetInfo(
                            title=s["properties"]["title"],
                            sheet_id=s["properties"]["sheetId"],
                        )
                        for s in spreadsheet.get("sheets", [])
                        if s.get("properties", {}).get("title")
                    ]
                    structure_cache.store(spreadsheet_id, sheet_infos, title=title)

                sheet_summaries = []
                for sheet_info in sheet_infos:
                    sheet_summary = {
                        "title": sheet_info.title,
                        "sheet_id": sheet_info.sheet_id,
                        "headers": [],
                        "first_rows": [],
                        "error": None,
                    }

                    cached = data_cache.get(spreadsheet_id, sheet_info.sheet_id, rows_to_fetch)
                    if cached is not None:
                        sheet_summary["headers"] = cached["headers"]
                        sheet_summary["first_rows"] = cached["first_rows"]
                        sheet_summaries.append(sheet_summary)
                        continue

                    try:
                        max_row = max(1, rows_to_fetch)
                        range_to_get = f"{_quote_sheet_name(sheet_info.title)}!A1:{max_row}"
                        result = (
                            sheets_service.spreadsheets()
                            .values()
                            .get(spreadsheetId=spreadsheet_id, range=range_to_get)
                            .execute()
                        )
                        values = result.get("values", [])
                        headers = values[0] if values else []
                        first_rows = values[1:max_row] if len(values) > 1 else []
                        sheet_summary["headers"] = headers
                        sheet_summary["first_rows"] = first_rows
                        data_cache.store(
                            spreadsheet_id, sheet_info.sheet_id, headers, first_rows, rows_to_fetch
                        )
                    except Exception as sheet_e:
                        sheet_summary["error"] = (
                            f"Error fetching data for sheet {sheet_info.title}: {sheet_e}"
                        )

                    sheet_summaries.append(sheet_summary)

                summary_data["sheets"] = sheet_summaries

            except Exception as e:
                summary_data["error"] = f"Error fetching spreadsheet {spreadsheet_id}: {e}"

            summaries.append(summary_data)

        return summaries

    @tool(annotations=ToolAnnotations(title="Find Cells", readOnlyHint=True))
    def find_in_spreadsheet(
        spreadsheet_id: str,
        query: str,
        sheet: str | None = None,
        case_sensitive: bool = False,
        max_results: int = 50,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        Find cells containing a specific value in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            query: The text to search for in cell values
            sheet: Optional sheet name to search in. If not provided, searches all sheets.
            case_sensitive: Whether the search should be case-sensitive (default False)
            max_results: Maximum number of results to return (default 50)

        Returns:
            List of found cells with their location (sheet, cell in A1 notation) and value
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service
        results = []

        try:
            all_sheets = fetch_sheets(sheets_service, spreadsheet_id, lc.cache)
            sheets_to_search = [s.title for s in all_sheets if sheet is None or s.title == sheet]

            if not sheets_to_search:
                return [{"error": f"Sheet '{sheet}' not found"}]

            search_query = query if case_sensitive else query.lower()

            for sheet_name in sheets_to_search:
                if len(results) >= max_results:
                    break

                response = (
                    sheets_service.spreadsheets()
                    .values()
                    .get(spreadsheetId=spreadsheet_id, range=_quote_sheet_name(sheet_name))
                    .execute()
                )

                for row_idx, row in enumerate(response.get("values", [])):
                    if len(results) >= max_results:
                        break
                    for col_idx, cell_value in enumerate(row):
                        if len(results) >= max_results:
                            break
                        cell_str = str(cell_value)
                        compare_value = cell_str if case_sensitive else cell_str.lower()
                        if search_query in compare_value:
                            results.append(
                                {
                                    "sheet": sheet_name,
                                    "cell": f"{_column_index_to_letter(col_idx)}{row_idx + 1}",
                                    "value": cell_value,
                                }
                            )

            return results

        except Exception as e:
            return [{"error": f"Search failed: {e!s}"}]
