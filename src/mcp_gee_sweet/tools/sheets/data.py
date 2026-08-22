import asyncio
import logging
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...cache import CACHE_VALIDATE_MODIFIED_TIME, SheetInfo, fetch_sheets, get_modified_time
from ..response_limits import enforce_response_size_cap, write_capped_result_to_disk
from .helpers import (
    _column_index_to_letter,
    _get_sheet_id,
    _parse_a1_notation,
    _quote_sheet_name,
    _utf16_len,
)

logger = logging.getLogger(__name__)

# Cell count turned out not to predict response size at all: a live test found a
# 26,000-cell *blank* range (a fresh sheet's default 1000x26 padding) returns almost
# nothing — Sheets omits rowData entirely for cells with no explicit formatting. A
# range with real formatting applied (bold, background, number format) costs roughly
# 700-780 bytes/cell instead, consistent with issue #235's own numbers (150 cells ->
# ~107KB, ~713 bytes/cell). Explicit per-cell CellFormat data is what's expensive, not
# the range's raw dimensions, and we can't know how formatted a range is without
# fetching it — so this checks the *actual* serialized response after the fetch, not
# an estimate beforehand. See docs/decisions/decision-grid-data-size-cap.md and
# docs/decisions/decision-response-size-cap-generalization.md for the full live-tested
# numbers behind the shared MAX_TOOL_RESPONSE_CHARS cap (response_limits.py).


def _build_rich_text_cell(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a Sheets API CellData dict from a list of {"text", "hyperlink"} runs.

    startIndex is UTF-16 code units per the Sheets API spec (confirmed via the
    API reference), not Python string length — see _utf16_len.
    """
    text_parts = []
    text_format_runs = []
    offset = 0
    has_hyperlink = False
    for run in runs:
        text = run.get("text", "")
        text_parts.append(text)
        run_format: dict[str, Any] = {}
        hyperlink = run.get("hyperlink")
        if hyperlink:
            run_format["link"] = {"uri": hyperlink}
            has_hyperlink = True
        entry: dict[str, Any] = {"format": run_format}
        if offset > 0:
            entry["startIndex"] = offset
        text_format_runs.append(entry)
        offset += _utf16_len(text)

    cell: dict[str, Any] = {
        "userEnteredValue": {"stringValue": "".join(text_parts)},
        "textFormatRuns": text_format_runs,
    }
    if has_hyperlink:
        cell["userEnteredFormat"] = {"hyperlinkDisplayType": "LINKED"}
    return cell


def register(tool):
    @tool(annotations=ToolAnnotations(title="Get Sheet Data", readOnlyHint=True))
    async def get_sheet_data(
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
                Raises ValueError if the actual response size exceeds a safety cap (see
                MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured default —
                raise it to match a higher MAX_MCP_OUTPUT_TOKENS in your MCP client) and
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
            values_result = await execute_in_thread(
                sheets_service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=quoted)
                .execute,
                sheets_service,
            )
            values = values_result.get("values", [])
            if values:
                last_col_index = max(len(row) for row in values) - 1
                range = f"A1:{_column_index_to_letter(max(last_col_index, 0))}{len(values)}"
            else:
                range = "A1"

        full_range = f"{quoted}!{range}" if range else quoted

        if include_grid_data:
            result = await execute_in_thread(
                sheets_service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id, ranges=[full_range], includeGridData=True)
                .execute,
                sheets_service,
            )
            # Cell count doesn't predict response size — a blank padded range costs almost
            # nothing, a densely formatted one can blow past a client's size limit even at a
            # modest cell count (issue #235). Check the real serialized size, not an estimate.
            if not local_path:
                enforce_response_size_cap(
                    result,
                    tool_name="get_sheet_data(include_grid_data=True)",
                    hint="Densely formatted cells serialize to ~700+ bytes each, so even a "
                    "modest range can produce a response large enough to break the client "
                    "connection. Narrow the range, or ",
                )
        else:
            values_result = await execute_in_thread(
                sheets_service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=full_range)
                .execute,
                sheets_service,
            )
            result = {
                "spreadsheetId": spreadsheet_id,
                "valueRanges": [{"range": full_range, "values": values_result.get("values", [])}],
            }

        if local_path:
            return await write_capped_result_to_disk(
                result,
                local_path,
                default_filename=f"{sheet}_data.json",
                manifest_extra={
                    "spreadsheet_id": spreadsheet_id,
                    "sheet": sheet,
                    "range": full_range,
                },
            )

        return result

    @tool(annotations=ToolAnnotations(title="Get Sheet Formulas", readOnlyHint=True))
    async def get_sheet_formulas(
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

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=full_range, valueRenderOption="FORMULA")
            .execute,
            sheets_service,
        )

        return result.get("values", [])

    @tool(annotations=ToolAnnotations(title="Get Multiple Sheet Data", readOnlyHint=True))
    async def get_multiple_sheet_data(
        queries: list[dict[str, str]], local_path: str | None = None, ctx: Context = None
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Get data from multiple specific ranges in Google Spreadsheets.

        Args:
            queries: A list of dictionaries, each specifying a query.
                     Each dictionary must have 'spreadsheet_id' and 'sheet' keys.
                     'range' is optional; omitting it returns the entire sheet.
                     Example: [{'spreadsheet_id': 'abc', 'sheet': 'Sheet1', 'range': 'A1:B5'},
                               {'spreadsheet_id': 'xyz', 'sheet': 'Data'}]
            local_path: Optional local filesystem path (file or directory) to write the
                result to instead of returning it inline. Bypasses the response-size cap.
                Same caveat as download_file/download_folder: this path is resolved on the
                *server's* filesystem, not the caller's.

        Returns:
            A list of dictionaries, each containing the original query parameters
            and the fetched 'data' or an 'error'. Raises ValueError if the response
            exceeds a safety cap (see MAX_TOOL_RESPONSE_CHARS in docs/configuration.md
            for the configured default) and local_path is not set — split into fewer queries per call,
            or pass local_path. If local_path is set, returns
            {local_path, query_count, bytes_written} instead.
        """
        sheets_service = ctx.request_context.lifespan_context.sheets_service

        async def _fetch_one(query: dict[str, str]) -> dict[str, Any]:
            spreadsheet_id = query.get("spreadsheet_id")
            sheet = query.get("sheet")
            range_str = query.get("range")

            if not all([spreadsheet_id, sheet]):
                return {**query, "error": "Missing required keys (spreadsheet_id, sheet)"}

            try:
                quoted = _quote_sheet_name(str(sheet))
                full_range = f"{quoted}!{range_str}" if range_str else quoted
                result = await execute_in_thread(
                    sheets_service.spreadsheets()
                    .values()
                    .get(spreadsheetId=spreadsheet_id, range=full_range)
                    .execute,
                    sheets_service,
                )
                return {**query, "data": result.get("values", [])}
            except Exception as e:
                return {**query, "error": str(e)}

        # return_exceptions=True: each _fetch_one already catches its own errors and
        # returns a tagged dict, but this also lets any genuinely unexpected exception
        # finish alongside the rest of the batch instead of orphaning in-flight tasks.
        raw = await asyncio.gather(*(_fetch_one(q) for q in queries), return_exceptions=True)
        results = [
            r if not isinstance(r, BaseException) else {**q, "error": str(r)}
            for q, r in zip(queries, raw, strict=True)
        ]

        if local_path:
            return await write_capped_result_to_disk(
                results,
                local_path,
                default_filename="multiple_sheet_data.json",
                manifest_extra={"query_count": len(queries)},
            )

        enforce_response_size_cap(results, tool_name="get_multiple_sheet_data")
        return results

    @tool(annotations=ToolAnnotations(title="Get Multiple Spreadsheet Summary", readOnlyHint=True))
    async def get_multiple_spreadsheet_summary(
        spreadsheet_ids: list[str],
        rows_to_fetch: int = 5,
        local_path: str | None = None,
        ctx: Context = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Get a summary of multiple Google Spreadsheets, including sheet names,
        headers, and the first few rows of data for each sheet.

        Args:
            spreadsheet_ids: A list of spreadsheet IDs to summarize.
            rows_to_fetch: The number of rows (including header) to fetch for the summary (default: 5).
            local_path: Optional local filesystem path (file or directory) to write the
                result to instead of returning it inline. Bypasses the response-size cap.
                Same caveat as download_file/download_folder: this path is resolved on the
                *server's* filesystem, not the caller's.

        Returns:
            A list of dictionaries, each representing a spreadsheet summary.
            Includes spreadsheet title, sheet summaries (title, headers, first rows), or an error.
            Results are cached; call refresh_cache(spreadsheet_id=<id>) to invalidate,
            or refresh_cache() to clear all caches. Raises ValueError if the response
            exceeds a safety cap (see MAX_TOOL_RESPONSE_CHARS in docs/configuration.md
            for the configured default) and local_path is not set — summarize fewer spreadsheets per
            call, lower rows_to_fetch, or pass local_path. If local_path is set, returns
            {local_path, spreadsheet_count, bytes_written} instead.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service
        drive_service = lc.drive_service
        data_cache = lc.sheet_data_cache
        structure_cache = lc.cache

        async def _summarize_one(spreadsheet_id: str) -> dict[str, Any]:
            summary_data = {
                "spreadsheet_id": spreadsheet_id,
                "title": None,
                "sheets": [],
                "error": None,
            }
            try:
                current_mtime = (
                    await get_modified_time(drive_service, spreadsheet_id)
                    if CACHE_VALIDATE_MODIFIED_TIME
                    else None
                )
                cached_sheets = structure_cache.get_sheets(
                    spreadsheet_id, current_modified_time=current_mtime
                )
                cached_title = structure_cache.get_title(
                    spreadsheet_id, current_modified_time=current_mtime
                )

                if cached_sheets is not None and cached_title is not None:
                    sheet_infos = cached_sheets
                    summary_data["title"] = cached_title
                else:
                    # Snapshotted before the API await so store() can detect a
                    # concurrent mark_dirty() (e.g. refresh_cache()) landing mid-fetch
                    # and skip overwriting it — see snapshot_epoch()'s docstring.
                    structure_epoch = structure_cache.snapshot_epoch()
                    spreadsheet = await execute_in_thread(
                        sheets_service.spreadsheets()
                        .get(
                            spreadsheetId=spreadsheet_id,
                            fields="properties.title,sheets(properties(title,sheetId))",
                        )
                        .execute,
                        sheets_service,
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
                    structure_cache.store(
                        spreadsheet_id,
                        sheet_infos,
                        title=title,
                        modified_time=current_mtime,
                        epoch=structure_epoch,
                    )

                # Kept sequential within a spreadsheet — modest sheet counts don't
                # justify nested gather complexity, and it keeps sheet_summaries
                # trivially ordered to match sheet_infos.
                sheet_summaries = []
                for sheet_info in sheet_infos:
                    sheet_summary = {
                        "title": sheet_info.title,
                        "sheet_id": sheet_info.sheet_id,
                        "headers": [],
                        "first_rows": [],
                        "error": None,
                    }

                    # Reused from the structure-check above rather than refetched per
                    # sheet: modifiedTime is a Drive file-level property, identical for
                    # every sheet tab in the same spreadsheet at a given instant. A
                    # per-sheet refetch (QA finding, #183) bought a race-window benefit
                    # (catching an edit mid-request) too marginal to justify N redundant
                    # Drive API calls per spreadsheet as sheet count grows.
                    sheet_mtime = current_mtime
                    cached = data_cache.get(
                        spreadsheet_id,
                        sheet_info.sheet_id,
                        rows_to_fetch,
                        current_modified_time=sheet_mtime,
                    )
                    if cached is not None:
                        sheet_summary["headers"] = cached["headers"]
                        sheet_summary["first_rows"] = cached["first_rows"]
                        sheet_summaries.append(sheet_summary)
                        continue

                    try:
                        max_row = max(1, rows_to_fetch)
                        range_to_get = f"{_quote_sheet_name(sheet_info.title)}!A1:{max_row}"
                        data_epoch = data_cache.snapshot_epoch()
                        result = await execute_in_thread(
                            sheets_service.spreadsheets()
                            .values()
                            .get(spreadsheetId=spreadsheet_id, range=range_to_get)
                            .execute,
                            sheets_service,
                        )
                        values = result.get("values", [])
                        headers = values[0] if values else []
                        first_rows = values[1:max_row] if len(values) > 1 else []
                        sheet_summary["headers"] = headers
                        sheet_summary["first_rows"] = first_rows
                        data_cache.store(
                            spreadsheet_id,
                            sheet_info.sheet_id,
                            headers,
                            first_rows,
                            rows_to_fetch,
                            modified_time=sheet_mtime,
                            epoch=data_epoch,
                        )
                    except Exception as sheet_e:
                        sheet_summary["error"] = (
                            f"Error fetching data for sheet {sheet_info.title}: {sheet_e}"
                        )

                    sheet_summaries.append(sheet_summary)

                summary_data["sheets"] = sheet_summaries

            except Exception as e:
                summary_data["error"] = f"Error fetching spreadsheet {spreadsheet_id}: {e}"

            return summary_data

        # return_exceptions=True: _summarize_one already catches its own errors, but this
        # also lets any genuinely unexpected exception finish alongside the rest of the
        # batch instead of orphaning in-flight tasks. gather() preserves input order.
        raw = await asyncio.gather(
            *(_summarize_one(sid) for sid in spreadsheet_ids), return_exceptions=True
        )
        summaries = [
            r
            if not isinstance(r, BaseException)
            else {
                "spreadsheet_id": sid,
                "title": None,
                "sheets": [],
                "error": f"Error fetching spreadsheet {sid}: {r}",
            }
            for sid, r in zip(spreadsheet_ids, raw, strict=True)
        ]

        if local_path:
            return await write_capped_result_to_disk(
                summaries,
                local_path,
                default_filename="multiple_spreadsheet_summary.json",
                manifest_extra={"spreadsheet_count": len(spreadsheet_ids)},
            )

        enforce_response_size_cap(summaries, tool_name="get_multiple_spreadsheet_summary")
        return summaries

    @tool(annotations=ToolAnnotations(title="Find Cells", readOnlyHint=True))
    async def find_in_spreadsheet(
        spreadsheet_id: str,
        query: str,
        sheet: str | None = None,
        case_sensitive: bool = False,
        max_results: int = 50,
        local_path: str | None = None,
        ctx: Context = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Find cells containing a specific value in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            query: The text to search for in cell values
            sheet: Optional sheet name to search in. If not provided, searches all sheets.
            case_sensitive: Whether the search should be case-sensitive (default False)
            max_results: Maximum number of results to return (default 50)
            local_path: Optional local filesystem path (file or directory) to write the
                result to instead of returning it inline. Bypasses the response-size cap.
                Same caveat as download_file/download_folder: this path is resolved on the
                *server's* filesystem, not the caller's.

        Returns:
            List of found cells with their location (sheet, cell in A1 notation) and value.
            max_results bounds match count, not response size — matched cell values can
            still be large. Raises ValueError if the response exceeds a safety cap
            (see MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured
            default) and local_path is not set — lower max_results, or pass local_path. If local_path
            is set, returns {local_path, spreadsheet_id, query, match_count, bytes_written}
            instead.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service
        results = []

        try:
            all_sheets = await fetch_sheets(
                sheets_service, spreadsheet_id, lc.cache, lc.drive_service
            )
            sheets_to_search = [s.title for s in all_sheets if sheet is None or s.title == sheet]

            if not sheets_to_search:
                results = [{"error": f"Sheet '{sheet}' not found"}]
            else:
                search_query = query if case_sensitive else query.lower()

                for sheet_name in sheets_to_search:
                    if len(results) >= max_results:
                        break

                    response = await execute_in_thread(
                        sheets_service.spreadsheets()
                        .values()
                        .get(spreadsheetId=spreadsheet_id, range=_quote_sheet_name(sheet_name))
                        .execute,
                        sheets_service,
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

        except Exception as e:
            results = [{"error": f"Search failed: {e!s}"}]

        if local_path:
            return await write_capped_result_to_disk(
                results,
                local_path,
                default_filename="find_in_spreadsheet_results.json",
                manifest_extra={
                    "spreadsheet_id": spreadsheet_id,
                    "query": query,
                    "match_count": len(results),
                },
            )

        enforce_response_size_cap(results, tool_name="find_in_spreadsheet")
        return results

    @tool(annotations=ToolAnnotations(title="Clear Values", destructiveHint=True))
    async def clear_values(
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

        return await execute_in_thread(
            lc.sheets_service.spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=full_range, body={})
            .execute,
            lc.sheets_service,
        )

    @tool(annotations=ToolAnnotations(title="Update Cells", destructiveHint=True))
    async def update_cells(
        spreadsheet_id: str, sheet: str, range: str, data: list[list[Any]], ctx: Context = None
    ) -> dict[str, Any]:
        """
        Update cells in a Google Spreadsheet.

        Args:
            spreadsheet_id: The ID of the spreadsheet (found in the URL)
            sheet: The name of the sheet
            range: Cell range in A1 notation (e.g., 'A1:C10')
            data: 2D array of values to update. Each cell is normally a plain
                scalar (str/int/float/bool), parsed the same way as typing it
                into the Sheets UI (USER_ENTERED — formulas, dates, etc. are
                recognized). For a partial (rich-text) hyperlink or mixed-format
                run within a single cell, pass a list of run dicts instead, e.g.
                [{"text": "See "}, {"text": "docs", "hyperlink": "https://..."}]
                — each run's "text" is concatenated into the cell's literal
                string value (not USER_ENTERED-parsed) and an optional
                "hyperlink" links just that run.

        Returns:
            Result of the update operation. If `data` contains only plain cells
            or only rich-text cells, this is that single API call's raw response.
            If it mixes both kinds, this is
            {"values_update": <plain-cell response>, "rich_text_update": <rich-text response>}
            since the two are separate API calls and neither result should be
            silently dropped.
        """
        lc = ctx.request_context.lifespan_context
        sheets_service = lc.sheets_service

        rich_text_cells: list[tuple[int, int, list[dict[str, Any]]]] = []
        plain_cells: list[tuple[int, int, Any]] = []
        for row_idx, row in enumerate(data):
            for col_idx, cell in enumerate(row):
                if isinstance(cell, list):
                    if not cell:
                        return {"error": "Rich-text cell runs list cannot be empty"}
                    for run in cell:
                        if not isinstance(run, dict) or not isinstance(run.get("text"), str):
                            return {
                                "error": "Rich-text cell runs must be dicts with a string "
                                "'text' key, e.g. {'text': ..., 'hyperlink': ...}"
                            }
                    rich_text_cells.append((row_idx, col_idx, cell))
                else:
                    plain_cells.append((row_idx, col_idx, cell))

        if not rich_text_cells and not plain_cells:
            return {"error": "data cannot be empty"}

        result: dict[str, Any] = {}

        if plain_cells and not rich_text_cells:
            # Plain-only: write the whole rectangle in one call, same as before
            # rich-text cells existed.
            result["values_update"] = await execute_in_thread(
                sheets_service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{_quote_sheet_name(sheet)}!{range}",
                    valueInputOption="USER_ENTERED",
                    body={"values": data},
                )
                .execute,
                sheets_service,
            )
            lc.sheet_data_cache.mark_dirty(spreadsheet_id)
        elif plain_cells:
            # Mixed call: write only the actual plain-cell positions, addressed
            # individually, rather than the whole rectangle. Writing the whole
            # rectangle would require blanking the rich-text cell positions to ""
            # first and relying on the rich-text batchUpdate below to overwrite
            # them back — if that second call then failed, the blank was never
            # restored and the rich-text cells' prior content was lost for good.
            # Per-cell targeting means the two calls never touch each other's
            # cells, so either one failing can't corrupt the other's data.
            indices = _parse_a1_notation(range)
            start_row = indices.get("startRowIndex", 0)
            start_col = indices.get("startColumnIndex", 0)
            plain_data = [
                {
                    "range": f"{_quote_sheet_name(sheet)}!"
                    f"{_column_index_to_letter(start_col + col_idx)}{start_row + row_idx + 1}",
                    "values": [[cell]],
                }
                for row_idx, col_idx, cell in plain_cells
            ]
            result["values_update"] = await execute_in_thread(
                sheets_service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": plain_data},
                )
                .execute,
                sheets_service,
            )
            lc.sheet_data_cache.mark_dirty(spreadsheet_id)

        if rich_text_cells:
            sheet_id = await _get_sheet_id(
                sheets_service, spreadsheet_id, sheet, lc.cache, lc.drive_service
            )
            if sheet_id is None:
                return {"error": f"Sheet '{sheet}' not found"}

            indices = _parse_a1_notation(range)
            start_row = indices.get("startRowIndex", 0)
            start_col = indices.get("startColumnIndex", 0)

            requests = [
                {
                    "updateCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row + row_idx,
                            "endRowIndex": start_row + row_idx + 1,
                            "startColumnIndex": start_col + col_idx,
                            "endColumnIndex": start_col + col_idx + 1,
                        },
                        "rows": [{"values": [_build_rich_text_cell(runs)]}],
                        "fields": "userEnteredValue,userEnteredFormat.hyperlinkDisplayType,"
                        "textFormatRuns",
                    }
                }
                for row_idx, col_idx, runs in rich_text_cells
            ]

            result["rich_text_update"] = await execute_in_thread(
                sheets_service.spreadsheets()
                .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
                .execute,
                sheets_service,
            )
            lc.sheet_data_cache.mark_dirty(spreadsheet_id)

        if len(result) == 1:
            return next(iter(result.values()))
        return result

    @tool(annotations=ToolAnnotations(title="Batch Update Cells", destructiveHint=True))
    async def batch_update_cells(
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

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": data},
            )
            .execute,
            sheets_service,
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
    async def batch_update(
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

        result = await execute_in_thread(
            sheets_service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
            .execute,
            sheets_service,
        )

        lc.cache.mark_dirty(spreadsheet_id)
        lc.sheet_data_cache.mark_dirty(spreadsheet_id)
        return result
