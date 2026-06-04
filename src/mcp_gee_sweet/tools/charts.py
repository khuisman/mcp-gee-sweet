from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..helpers import _get_sheet_id, _parse_a1_notation

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
    @tool(annotations=ToolAnnotations(title="Add Chart", destructiveHint=True))
    def add_chart(
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

        sheet_id = _get_sheet_id(sheets_service, spreadsheet_id, sheet, lc.cache)
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
            chart_spec = {
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
            result = (
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
                .execute()
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
