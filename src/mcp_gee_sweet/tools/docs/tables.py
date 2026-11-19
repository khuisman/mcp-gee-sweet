import logging
from typing import Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...deprecation import deprecated_tool
from .invalidation import doc_invalidating

logger = logging.getLogger(__name__)

# Every table tool removed in favor of a *_table_row_or_column tool (#1527) goes in
# the next feature release, per docs/design.md "Renaming or Removing a Tool".
_ROW_OR_COLUMN_REMOVED_IN = "the next feature release"

_DIMENSIONS = ("row", "column")


def _dimension_error(dimension: str) -> dict[str, Any] | None:
    """An {"error": ...} dict unless `dimension` is `row` or `column`. The tool
    schema already restricts it; this covers direct calls."""
    if dimension not in _DIMENSIONS:
        return {"error": f"dimension must be 'row' or 'column', got {dimension!r}"}
    return None


def _cell_location(table_start_index: int, dimension: str, index: int) -> dict[str, Any]:
    """The tableCellLocation naming row `index` (column 0) or column `index` (row 0)."""
    return {
        "tableStartLocation": {"index": table_start_index},
        "rowIndex": index if dimension == "row" else 0,
        "columnIndex": index if dimension == "column" else 0,
    }


async def _send_table_request(lc, doc_id: str, request: dict[str, Any]) -> dict[str, Any] | None:
    """Send one table edit request. Returns an {"error": ...} dict, or None once sent."""
    try:
        with doc_invalidating(lc.doc_cache, doc_id):
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": [request]})
                .execute,
                lc.docs_service,
            )
    except Exception as e:
        return {"error": str(e)}
    return None


async def _insert_table_dimension(
    lc, doc_id: str, dimension: str, table_start_index: int, index: int, after: bool
) -> dict[str, Any] | None:
    """Shared implementation behind insert_table_row_or_column and
    insert_table_row/insert_table_column, so both send the same request. Returns an
    {"error": ...} dict, or None once the row or column is inserted."""
    error = _dimension_error(dimension)
    if error:
        return error
    location = _cell_location(table_start_index, dimension, index)
    if dimension == "row":
        request = {"insertTableRow": {"tableCellLocation": location, "insertBelow": after}}
    else:
        request = {"insertTableColumn": {"tableCellLocation": location, "insertRight": after}}
    error = await _send_table_request(lc, doc_id, request)
    if error:
        return error
    logger.debug(
        "insert table %s %d (after=%s) in table at %d in doc %s",
        dimension,
        index,
        after,
        table_start_index,
        doc_id,
    )
    return None


async def _delete_table_dimension(
    lc, doc_id: str, dimension: str, table_start_index: int, index: int
) -> dict[str, Any] | None:
    """Shared implementation behind delete_table_row_or_column and
    delete_table_row/delete_table_column, so both send the same request. Returns an
    {"error": ...} dict, or None once the row or column is deleted."""
    error = _dimension_error(dimension)
    if error:
        return error
    name = "deleteTableRow" if dimension == "row" else "deleteTableColumn"
    request = {name: {"tableCellLocation": _cell_location(table_start_index, dimension, index)}}
    error = await _send_table_request(lc, doc_id, request)
    if error:
        return error
    logger.debug(
        "delete table %s %d from table at %d in doc %s",
        dimension,
        index,
        table_start_index,
        doc_id,
    )
    return None


def register(tool):
    @tool(annotations=ToolAnnotations(title="Insert Document Table", destructiveHint=True))
    async def insert_doc_table(
        doc_id: str,
        index: int,
        rows: int,
        columns: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an empty table at a specific position in a Google Doc.

        The table is inserted at the given index. The document is re-fetched
        immediately to return the actual cell indices. Use those indices with
        insert_doc_text (targeting each cell's paragraphStartIndex) to fill cells,
        or with style_doc_table_cells to apply formatting.

        Also useful for form-style column alignment (labels/values lined up without
        a visible table) — a zero-padding table gives exact column positions where
        tabStops would otherwise be needed (tabStops itself is read-only). See
        docs/design/borderless-table-columns.md for the full recipe.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the table should be inserted.
                Use get_doc_structure to find a suitable position (e.g. the
                endIndex of the paragraph before the intended location).
            rows: Number of table rows.
            columns: Number of table columns.

        Returns:
            precedingParagraphIndex (= index), tableStartIndex (= index + 1),
            tableEndIndex, rows, columns, and a cells list (each cell has row,
            col, startIndex, endIndex, paragraphStartIndex).
            To fully delete the table later, delete the range
            [precedingParagraphIndex, tableEndIndex] in one call.
        """
        lc = ctx.request_context.lifespan_context
        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={
                            "requests": [
                                {
                                    "insertTable": {
                                        "rows": rows,
                                        "columns": columns,
                                        "location": {"index": index},
                                    }
                                }
                            ]
                        },
                    )
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": f"table inserted but re-fetch failed: {e}"}

        table_elems = [
            elem
            for elem in doc.get("body", {}).get("content", [])
            if "table" in elem and elem.get("startIndex", 0) >= index - 1
        ]
        table_elems.sort(key=lambda e: e.get("startIndex", 0))

        for elem in table_elems:
            table = elem["table"]
            cells = []
            for r, row in enumerate(table.get("tableRows", [])):
                for c, cell in enumerate(row.get("tableCells", [])):
                    content = cell.get("content", [])
                    para_start = content[0].get("startIndex") if content else None
                    cells.append(
                        {
                            "row": r,
                            "col": c,
                            "startIndex": cell.get("startIndex"),
                            "endIndex": cell.get("endIndex"),
                            "paragraphStartIndex": para_start,
                        }
                    )
            logger.debug(
                "insert_doc_table: %dx%d at index %d in doc %s", rows, columns, index, doc_id
            )
            table_start = elem.get("startIndex")
            return {
                "docId": doc_id,
                "precedingParagraphIndex": table_start - 1,
                "tableStartIndex": table_start,
                "tableEndIndex": elem.get("endIndex"),
                "rows": rows,
                "columns": columns,
                "cells": cells,
            }

        return {"error": "table inserted but could not locate it in re-fetched doc"}

    @tool(annotations=ToolAnnotations(title="Insert Table Row or Column", destructiveHint=True))
    async def insert_table_row_or_column(
        doc_id: str,
        dimension: Literal["row", "column"],
        table_start_index: int,
        index: int,
        after: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert a row or a column into an existing table in a Google Doc.

        Use get_doc_structure to find the table's startIndex and the row or
        column to insert next to.

        Args:
            doc_id: The Google Doc file ID.
            dimension: "row" to insert a row, "column" to insert a column.
            table_start_index: The startIndex of the table (from get_doc_structure).
            index: Zero-based index of the row or column to insert next to.
            after: If True (default), insert below the row or to the right of the
                column. If False, insert above the row or to the left of the column.

        Returns:
            Confirmation with docId, table_start_index, dimension, and the index used.
        """
        error = await _insert_table_dimension(
            ctx.request_context.lifespan_context,
            doc_id,
            dimension,
            table_start_index,
            index,
            after,
        )
        if error:
            return error
        return {
            "docId": doc_id,
            "table_start_index": table_start_index,
            "dimension": dimension,
            "index": index,
        }

    @tool(annotations=ToolAnnotations(title="Insert Table Row", destructiveHint=True))
    @deprecated_tool(
        use="`insert_table_row_or_column` with `dimension='row'` (`row_index` becomes "
        "`index`, `insert_below` becomes `after`)",
        removed_in=_ROW_OR_COLUMN_REMOVED_IN,
    )
    async def insert_table_row(
        doc_id: str,
        table_start_index: int,
        row_index: int,
        insert_below: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert a row into an existing table in a Google Doc.

        Use get_doc_structure to find the table's startIndex and the row_index to
        insert relative to.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure).
            row_index: The row to insert relative to.
            insert_below: If True (default), insert below the specified row.
                If False, insert above it.

        Returns:
            Confirmation with docId, table_start_index, and the row_index used.
        """
        error = await _insert_table_dimension(
            ctx.request_context.lifespan_context,
            doc_id,
            "row",
            table_start_index,
            row_index,
            insert_below,
        )
        if error:
            return error
        return {"docId": doc_id, "table_start_index": table_start_index, "row_index": row_index}

    @tool(annotations=ToolAnnotations(title="Delete Table Row or Column", destructiveHint=True))
    async def delete_table_row_or_column(
        doc_id: str,
        dimension: Literal["row", "column"],
        table_start_index: int,
        index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete a row or a column from an existing table in a Google Doc.

        Use get_doc_structure to find the table's startIndex and the row or
        column to delete.

        Args:
            doc_id: The Google Doc file ID.
            dimension: "row" to delete a row, "column" to delete a column.
            table_start_index: The startIndex of the table (from get_doc_structure).
            index: Zero-based index of the row or column to delete.

        Returns:
            Confirmation with docId, table_start_index, dimension, and the deleted index.
        """
        error = await _delete_table_dimension(
            ctx.request_context.lifespan_context, doc_id, dimension, table_start_index, index
        )
        if error:
            return error
        return {
            "docId": doc_id,
            "table_start_index": table_start_index,
            "dimension": dimension,
            "index": index,
        }

    @tool(annotations=ToolAnnotations(title="Delete Table Row", destructiveHint=True))
    @deprecated_tool(
        use="`delete_table_row_or_column` with `dimension='row'` (`row_index` becomes `index`)",
        removed_in=_ROW_OR_COLUMN_REMOVED_IN,
    )
    async def delete_table_row(
        doc_id: str,
        table_start_index: int,
        row_index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete a row from an existing table in a Google Doc.

        Use get_doc_structure to find the table's startIndex and the row_index to delete.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure).
            row_index: Zero-based index of the row to delete.

        Returns:
            Confirmation with docId, table_start_index, and deleted row_index.
        """
        error = await _delete_table_dimension(
            ctx.request_context.lifespan_context, doc_id, "row", table_start_index, row_index
        )
        if error:
            return error
        return {"docId": doc_id, "table_start_index": table_start_index, "row_index": row_index}

    @tool(annotations=ToolAnnotations(title="Insert Table Column", destructiveHint=True))
    @deprecated_tool(
        use="`insert_table_row_or_column` with `dimension='column'` (`column_index` becomes "
        "`index`, `insert_right` becomes `after`)",
        removed_in=_ROW_OR_COLUMN_REMOVED_IN,
    )
    async def insert_table_column(
        doc_id: str,
        table_start_index: int,
        column_index: int,
        insert_right: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert a column into an existing table in a Google Doc.

        Use get_doc_structure to find the table's startIndex and the column_index to
        insert relative to.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure).
            column_index: The column to insert relative to.
            insert_right: If True (default), insert to the right of the specified column.
                If False, insert to the left.

        Returns:
            Confirmation with docId, table_start_index, and the column_index used.
        """
        error = await _insert_table_dimension(
            ctx.request_context.lifespan_context,
            doc_id,
            "column",
            table_start_index,
            column_index,
            insert_right,
        )
        if error:
            return error
        return {
            "docId": doc_id,
            "table_start_index": table_start_index,
            "column_index": column_index,
        }

    @tool(annotations=ToolAnnotations(title="Merge Table Cells", destructiveHint=True))
    async def merge_table_cells(
        doc_id: str,
        table_start_index: int,
        row_index: int,
        column_index: int,
        row_span: int = 1,
        column_span: int = 1,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Merge a rectangular range of cells in an existing table into one cell.

        Use get_doc_structure to find the table's startIndex and the row/column
        of the merge range's top-left (anchor) cell. Merging doesn't delete
        content or shift character indices: cells covered by the merge remain
        physical entries in the doc, they're just no longer independently
        addressable in the rendered table.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure).
            row_index: Zero-based row of the merge range's top-left cell.
            column_index: Zero-based column of the merge range's top-left cell.
            row_span: Number of rows the merged cell should span (default 1).
            column_span: Number of columns the merged cell should span (default 1).

        Returns:
            Confirmation with docId, table_start_index, row_index, column_index,
            row_span, and column_span.
        """
        lc = ctx.request_context.lifespan_context
        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={
                            "requests": [
                                {
                                    "mergeTableCells": {
                                        "tableRange": {
                                            "tableCellLocation": {
                                                "tableStartLocation": {"index": table_start_index},
                                                "rowIndex": row_index,
                                                "columnIndex": column_index,
                                            },
                                            "rowSpan": row_span,
                                            "columnSpan": column_span,
                                        }
                                    }
                                }
                            ]
                        },
                    )
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug(
            "merge_table_cells: (%d,%d) span %dx%d in table at %d in doc %s",
            row_index,
            column_index,
            row_span,
            column_span,
            table_start_index,
            doc_id,
        )
        return {
            "docId": doc_id,
            "table_start_index": table_start_index,
            "row_index": row_index,
            "column_index": column_index,
            "row_span": row_span,
            "column_span": column_span,
        }

    @tool(annotations=ToolAnnotations(title="Delete Table Column", destructiveHint=True))
    @deprecated_tool(
        use="`delete_table_row_or_column` with `dimension='column'` (`column_index` becomes "
        "`index`)",
        removed_in=_ROW_OR_COLUMN_REMOVED_IN,
    )
    async def delete_table_column(
        doc_id: str,
        table_start_index: int,
        column_index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete a column from an existing table in a Google Doc.

        Use get_doc_structure to find the table's startIndex and the column_index to delete.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure).
            column_index: Zero-based index of the column to delete.

        Returns:
            Confirmation with docId, table_start_index, and deleted column_index.
        """
        error = await _delete_table_dimension(
            ctx.request_context.lifespan_context,
            doc_id,
            "column",
            table_start_index,
            column_index,
        )
        if error:
            return error
        return {
            "docId": doc_id,
            "table_start_index": table_start_index,
            "column_index": column_index,
        }
