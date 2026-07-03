import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...cache import SheetInfo, fetch_sheets
from .helpers import _column_index_to_letter, _quote_sheet_name

logger = logging.getLogger(__name__)

# Cell count turned out not to predict response size at all: a live test found a
# 26,000-cell *blank* range (a fresh sheet's default 1000x26 padding) returns almost
# nothing — Sheets omits rowData entirely for cells with no explicit formatting. A
# range with real formatting applied (bold, background, number format) costs roughly
# 700-780 bytes/cell instead, consistent with issue #235's own numbers (150 cells ->
# ~107KB, ~713 bytes/cell). Explicit per-cell CellFormat data is what's expensive, not
# the range's raw dimensions, and we can't know how formatted a range is without
# fetching it — so this checks the *actual* serialized response after the fetch, not
# an estimate beforehand.
#
# A live binary search against this session's own client (same formatting applied,
# range size varied) found the actual failure point much lower than expected:
#   60 cells succeeded; 65 cells (51,208 chars) failed; 75 cells (58,784) failed;
#   100 cells (77,694) failed; 500 cells (380,494) failed; 1,300 cells (983,982) failed.
# That places the real limit around 48,000-51,000 characters. This matches Claude
# Code's documented default of 25,000 tokens per MCP tool response (configurable via
# MAX_MCP_OUTPUT_TOKENS): this densely-nested, repeated-key JSON tokenizes at roughly
# 2 chars/token rather than the ~4 chars/token typical of prose, so 25,000 tokens lands
# right around 50,000 characters. That token cap is a *client-side* setting the server
# has no visibility into — a different client, or the same client with a raised
# MAX_MCP_OUTPUT_TOKENS, will have a different real limit (likely higher; this project
# happens to be developed against Claude Code, but isn't the only possible consumer).
# 40,000 gives margin below what was actually observed here — still just one
# environment's data point, not a universal constant. Set MAX_GRID_DATA_RESPONSE_CHARS
# to match your own client's configured limit if you've raised it (roughly 2
# characters per token observed for this kind of densely-formatted JSON, though the
# exact ratio depends on content).
_MAX_GRID_DATA_RESPONSE_CHARS = int(os.environ.get("MAX_GRID_DATA_RESPONSE_CHARS", "40000"))


def _enforce_grid_data_response_cap(result: dict) -> None:
    """Raise ValueError if the serialized grid-data result is too large to return inline."""
    size = len(json.dumps(result))
    if size > _MAX_GRID_DATA_RESPONSE_CHARS:
        raise ValueError(
            f"get_sheet_data(include_grid_data=True): the response is {size} characters, "
            f"over the {_MAX_GRID_DATA_RESPONSE_CHARS}-character safety cap. Densely "
            "formatted cells serialize to ~700+ bytes each, so even a modest range can "
            "produce a response large enough to break the client connection. Narrow the "
            "range; pass local_path to write the result to disk instead of returning it "
            "inline (bypasses this cap); or set MAX_GRID_DATA_RESPONSE_CHARS if your MCP "
            "client can handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS)."
        )


def register(tool):
    @tool(annotations=ToolAnnotations(title="Get Sheet Data", readOnlyHint=True))
    def get_sheet_data(
        spreadsheet_id: str,
        sheet: str,
        range: str | None = None,
        include_grid_data: bool = False,
        local_path: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Get data from a specific sheet in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            range: Optional cell range in A1 notation (e.g., 'A1:C10'). If not provided, gets all data.
                With include_grid_data=True and no range, the used range is auto-detected (see below)
                rather than fetching the sheet's full padded grid.
            include_grid_data: If True, includes cell formatting and other metadata in the response.
                Note: Setting this to True will significantly increase the response size and token usage
                when parsing the response, as it includes detailed cell formatting information —
                densely formatted cells serialize to hundreds of bytes each.
                If range is omitted, the actual used range is auto-detected first (one extra lightweight
                values-only request) and formatting is fetched only for that — sheets default to a padded
                1000x26 grid regardless of actual content, and fetching per-cell formatting for the full
                padded grid instead of just your data can produce a response large enough to break the
                client connection.
                Default is False (returns values only, more efficient).
                Raises ValueError if the actual response size exceeds a safety cap
                (default 40,000 characters, set MAX_GRID_DATA_RESPONSE_CHARS to change it —
                e.g. to match a raised MAX_MCP_OUTPUT_TOKENS in your MCP client) and
                local_path is not set — narrow the range, retry, or pass local_path to
                bypass the cap entirely.
            local_path: Optional local filesystem path (file or directory) to write the result
                to instead of returning it inline. Bypasses the include_grid_data response-size cap.
                Same caveat as download_file/download_folder: this path is resolved on the
                *server's* filesystem, not the caller's — over SSE that's only useful if the
                path is on a volume the caller can also reach; for stdio it's the same machine.

        Returns:
            Grid data structure with either full metadata or just values from Google Sheets API,
            depending on include_grid_data parameter. If local_path is set, returns
            {local_path, spreadsheet_id, sheet, range, bytes_written} instead.
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        quoted = _quote_sheet_name(sheet)

        if include_grid_data and not range:
            # Auto-detect the used range so we don't fetch formatting for the sheet's full
            # padded grid (often 1000x26 by default, regardless of actual content) — issue #235.
            values_result = (
                sheets_service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=quoted)
                .execute()
            )
            values = values_result.get("values", [])
            if values:
                last_col_index = max(len(row) for row in values) - 1
                range = f"A1:{_column_index_to_letter(max(last_col_index, 0))}{len(values)}"
            else:
                range = "A1"

        full_range = f"{quoted}!{range}" if range else quoted

        if include_grid_data:
            result = (
                sheets_service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id, ranges=[full_range], includeGridData=True)
                .execute()
            )
            # Cell count doesn't predict response size — a blank padded range costs almost
            # nothing, a densely formatted one can blow past a client's size limit even at a
            # modest cell count (issue #235). Check the real serialized size, not an estimate.
            if not local_path:
                _enforce_grid_data_response_cap(result)
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

        if local_path:
            dest = Path(local_path)
            if dest.is_dir():
                dest = dest / f"{sheet}_data.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(result))
            return {
                "local_path": str(dest),
                "spreadsheet_id": spreadsheet_id,
                "sheet": sheet,
                "range": full_range,
                "bytes_written": dest.stat().st_size,
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
                     Each dictionary must have 'spreadsheet_id' and 'sheet' keys.
                     'range' is optional; omitting it returns the entire sheet.
                     Example: [{'spreadsheet_id': 'abc', 'sheet': 'Sheet1', 'range': 'A1:B5'},
                               {'spreadsheet_id': 'xyz', 'sheet': 'Data'}]

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

            if not all([spreadsheet_id, sheet]):
                results.append({**query, "error": "Missing required keys (spreadsheet_id, sheet)"})
                continue

            try:
                quoted = _quote_sheet_name(str(sheet))
                full_range = f"{quoted}!{range_str}" if range_str else quoted
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

    @tool(annotations=ToolAnnotations(title="Clear Values", destructiveHint=True))
    def clear_values(
        spreadsheet_id: str,
        sheet: str,
        range: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Clear cell content in a range without touching formatting.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            range: A1 notation range to clear (e.g., 'A1:D10').
                   If omitted, clears the entire sheet.

        Returns:
            Result of the clear operation
        """
        lc = ctx.request_context.lifespan_context
        quoted = _quote_sheet_name(sheet)
        full_range = f"{quoted}!{range}" if range else quoted

        return (
            lc.sheets_service.spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=full_range, body={})
            .execute()
        )

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

        # Normalize empty-array rows to rows of empty strings so the Sheets API
        # counts them as written cells. [] rows are treated as no-ops by the API
        # and are silently excluded from updatedRange, which causes callers to
        # think the last data row was dropped and re-write it as a duplicate.
        def _normalize(values: list[list]) -> list[list]:
            width = max((len(r) for r in values if r), default=0)
            return [r if r else [""] * width for r in values]

        data = [
            {"range": f"{_quote_sheet_name(sheet)}!{range_str}", "values": _normalize(values)}
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

        logger.debug(
            "batch_update_cells raw response: input_ranges=%s row_counts=%s response=%s",
            list(ranges.keys()),
            [len(v) for v in ranges.values()],
            result,
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
