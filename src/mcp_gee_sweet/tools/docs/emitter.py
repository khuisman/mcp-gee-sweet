"""Document AST → Docs API batchUpdate requests."""

from __future__ import annotations

from .ast import BulletItem, DocNode, Heading, Paragraph, Run, Table


def ast_to_requests(nodes: list[DocNode], start_index: int = 1) -> tuple[list[dict], list[Table]]:
    """Convert AST nodes to phase-1 batchUpdate requests and a list of Table nodes.

    Phase-1 requests cover all non-table text (one insertText), paragraph/heading styles,
    bullets, inline link styles, and insertTable requests (in reverse order).

    Tables are NOT filled here. The caller must execute a second pass using fill_tables()
    after running the phase-1 batchUpdate, so that live cell indices are available.

    Returns (requests, tables) where tables is the list of Table AST nodes in document
    order.
    """
    full_text = ""
    segment_meta: list[tuple] = []  # (node, doc_start, doc_end)
    tables: list[Table] = []
    table_positions: list[int] = []  # doc index for each table

    for node in nodes:
        if isinstance(node, Table):
            tables.append(node)
            table_positions.append(start_index + len(full_text))
        else:
            doc_start = start_index + len(full_text)
            text = "".join(r.text for r in node.runs)
            if not text.strip():
                continue
            full_text += text + "\n"
            doc_end = start_index + len(full_text)
            segment_meta.append((node, doc_start, doc_end))

    requests: list[dict] = []

    if full_text:
        requests.append({"insertText": {"location": {"index": start_index}, "text": full_text}})

        for node, doc_start, doc_end in segment_meta:
            rng = {"startIndex": doc_start, "endIndex": doc_end}

            if isinstance(node, Heading):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": f"HEADING_{node.level}"},
                            "fields": "namedStyleType",
                        }
                    }
                )
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif isinstance(node, Paragraph):
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif isinstance(node, BulletItem):
                preset = (
                    "NUMBERED_DECIMAL_ALPHA_ROMAN" if node.ordered else "BULLET_DISC_CIRCLE_SQUARE"
                )
                requests.append(
                    {
                        "createParagraphBullets": {
                            "range": rng,
                            "bulletPreset": preset,
                        }
                    }
                )

            # Inline link styles for non-table runs
            offset = 0
            for run in node.runs:
                run_len = len(run.text)
                if run.link_url:
                    requests.append(
                        {
                            "updateTextStyle": {
                                "range": {
                                    "startIndex": doc_start + offset,
                                    "endIndex": doc_start + offset + run_len,
                                },
                                "textStyle": {"link": {"url": run.link_url}},
                                "fields": "link",
                            }
                        }
                    )
                offset += run_len

    # insertTable requests in REVERSE order so earlier positions aren't shifted
    for i in range(len(tables) - 1, -1, -1):
        table = tables[i]
        num_rows = len(table.rows)
        num_cols = max((len(row.cells) for row in table.rows), default=0)
        if num_rows > 0 and num_cols > 0:
            requests.append(
                {
                    "insertTable": {
                        "rows": num_rows,
                        "columns": num_cols,
                        "location": {"index": table_positions[i]},
                    }
                }
            )

    return requests, tables


def _run_style_requests(run: Run, start: int, end: int) -> list[dict]:
    """Return updateTextStyle requests for all non-None style fields on a Run."""
    text_style: dict = {}
    fields: list[str] = []

    for key, api_key in [
        ("bold", "bold"),
        ("italic", "italic"),
        ("underline", "underline"),
        ("strikethrough", "strikethrough"),
    ]:
        val = getattr(run, key)
        if val is not None:
            text_style[api_key] = val
            fields.append(api_key)

    if run.link_url is not None:
        text_style["link"] = {"url": run.link_url}
        fields.append("link")

    if not fields:
        return []

    return [
        {
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": text_style,
                "fields": ",".join(fields),
            }
        }
    ]


def fill_tables(docs_service, doc_id: str, tables: list[Table]) -> None:
    """Fill table cells and apply inline styles using live cell indices.

    Two-phase for tables with colspan merges:
      1. Re-fetch → get cell positions
      2. If any colspan > 1: emit mergeTableCells, re-fetch again
      3. Emit insertText + updateTextStyle for all cells (high→low)
      4. Emit updateTableColumnProperties for tables with col_widths
    """
    if not tables:
        return

    # Phase A: check whether any merges are needed
    has_merges = any(
        cell.colspan > 1 for table in tables for row in table.rows for cell in row.cells
    )

    # Step 1: re-fetch to get live cell positions
    live_doc = docs_service.documents().get(documentId=doc_id).execute()
    doc_tables = [
        elem["table"] for elem in live_doc.get("body", {}).get("content", []) if "table" in elem
    ]

    if has_merges:
        merge_requests = _build_merge_requests(doc_tables, tables)
        if merge_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": merge_requests}
            ).execute()
            # Re-fetch to get post-merge cell positions
            live_doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_tables = [
                elem["table"]
                for elem in live_doc.get("body", {}).get("content", [])
                if "table" in elem
            ]

    # Step 2: fill cell content
    fill_requests = _build_fill_requests(doc_tables, tables)
    if fill_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": fill_requests}
        ).execute()

    # Step 3: column widths — requires table startIndex from live doc
    width_requests = _build_width_requests(live_doc, tables)
    if width_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": width_requests}
        ).execute()


def _build_merge_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Emit mergeTableCells for any cell with colspan > 1."""
    requests: list[dict] = []
    for doc_table, ast_table in zip(doc_tables, ast_tables):
        table_start = _table_start_index(doc_table)
        if table_start is None:
            continue
        for r, (doc_row, ast_row) in enumerate(zip(doc_table.get("tableRows", []), ast_table.rows)):
            for c, ast_cell in enumerate(ast_row.cells):
                if ast_cell.colspan > 1:
                    requests.append(
                        {
                            "mergeTableCells": {
                                "tableRange": {
                                    "tableCellLocation": {
                                        "tableStartLocation": {"index": table_start},
                                        "rowIndex": r,
                                        "columnIndex": c,
                                    },
                                    "rowSpan": 1,
                                    "columnSpan": ast_cell.colspan,
                                }
                            }
                        }
                    )
    return requests


def _build_fill_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Build insertText + updateTextStyle requests for all table cells, sorted high→low."""
    all_requests: list[tuple[int, list[dict]]] = []  # (index, requests_for_this_cell)

    for doc_table, ast_table in zip(doc_tables, ast_tables):
        doc_rows = doc_table.get("tableRows", [])
        ast_rows = ast_table.rows

        # After colspan merges, the physical doc may have fewer cells per row.
        # We match doc cells to ast cells in order, skipping phantom positions.
        # Simple approach: iterate doc cells and ast cells in parallel.
        doc_cell_iter = (
            (doc_cell, ast_row.cells[c] if c < len(ast_row.cells) else None)
            for ast_row, doc_row_entry in zip(ast_rows, doc_rows)
            for c, doc_cell in enumerate(doc_row_entry.get("tableCells", []))
        )

        for doc_cell, ast_cell in doc_cell_iter:
            if ast_cell is None:
                continue
            cell_runs = ast_cell.runs
            cell_text = "".join(r.text for r in cell_runs)
            if not cell_text:
                continue
            cell_content = doc_cell.get("content", [])
            if not cell_content:
                continue
            para_start = cell_content[0].get("startIndex")
            if para_start is None:
                continue

            cell_requests: list[dict] = []
            cell_requests.append(
                {
                    "insertText": {
                        "location": {"index": para_start},
                        "text": cell_text,
                    }
                }
            )
            # Style requests for individual runs
            offset = 0
            for run in cell_runs:
                run_len = len(run.text)
                if run_len > 0:
                    style_reqs = _run_style_requests(
                        run, para_start + offset, para_start + offset + run_len
                    )
                    cell_requests.extend(style_reqs)
                offset += run_len

            all_requests.append((para_start, cell_requests))

    # Sort high→low by paragraph start index
    all_requests.sort(key=lambda x: x[0], reverse=True)
    return [req for _, reqs in all_requests for req in reqs]


def _build_width_requests(live_doc: dict, ast_tables: list[Table]) -> list[dict]:
    """Build updateTableColumnProperties requests for tables with col_widths."""
    requests: list[dict] = []
    doc_table_elems = [
        elem for elem in live_doc.get("body", {}).get("content", []) if "table" in elem
    ]

    for elem, ast_table in zip(doc_table_elems, ast_tables):
        if not ast_table.col_widths:
            continue
        table_start = elem.get("startIndex")
        if table_start is None:
            continue
        for col_idx, width_pt in enumerate(ast_table.col_widths):
            if width_pt is None:
                continue
            requests.append(
                {
                    "updateTableColumnProperties": {
                        "tableStartLocation": {"index": table_start},
                        "columnIndices": [col_idx],
                        "tableColumnProperties": {
                            "widthType": "FIXED_WIDTH",
                            "width": {"magnitude": width_pt, "unit": "PT"},
                        },
                        "fields": "width,widthType",
                    }
                }
            )

    return requests


def _table_start_index(doc_table: dict) -> int | None:
    """Return the tableStartLocation index for a doc table element."""
    rows = doc_table.get("tableRows", [])
    if not rows:
        return None
    cells = rows[0].get("tableCells", [])
    if not cells:
        return None
    return cells[0].get("startIndex", 1) - 2  # rough: table startIndex = first cell - 2
