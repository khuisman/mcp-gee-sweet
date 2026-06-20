"""Document AST → Docs API batchUpdate requests."""

from __future__ import annotations

from .ast import BulletItem, DocNode, Heading, NamedBlock, Paragraph, Row, Run, Table


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
            # Checkbox glyph prefix for task list items
            prefix = ""
            if isinstance(node, BulletItem) and node.checked is not None:
                prefix = "☑ " if node.checked else "☐ "
            text = prefix + "".join(r.text for r in node.runs)
            if not text.strip():
                continue
            full_text += text + "\n"
            doc_end = start_index + len(full_text)
            segment_meta.append((node, doc_start, doc_end, len(prefix)))

    requests: list[dict] = []

    if full_text:
        requests.append({"insertText": {"location": {"index": start_index}, "text": full_text}})

        for node, doc_start, doc_end, prefix_len in segment_meta:
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
            elif isinstance(node, NamedBlock):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": node.style_type},
                            "fields": "namedStyleType",
                        }
                    }
                )
                requests.append({"deleteParagraphBullets": {"range": rng}})

            # Inline run styles for non-table content (bold, italic, links, font_family, etc.)
            # prefix_len skips past any checkbox glyph so run offsets stay accurate
            offset = prefix_len
            for run in node.runs:
                run_len = len(run.text)
                if run_len > 0:
                    style_reqs = _run_style_requests(
                        run, doc_start + offset, doc_start + offset + run_len
                    )
                    requests.extend(style_reqs)
                offset += run_len

    # insertTable requests in REVERSE order so earlier positions aren't shifted
    for i in range(len(tables) - 1, -1, -1):
        table = tables[i]
        num_rows = len(table.rows)
        num_cols = max((sum(c.colspan for c in row.cells) for row in table.rows), default=0)
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

    if run.font_family is not None:
        text_style["weightedFontFamily"] = {"fontFamily": run.font_family}
        fields.append("weightedFontFamily")

    if run.font_size is not None:
        text_style["fontSize"] = {"magnitude": run.font_size, "unit": "PT"}
        fields.append("fontSize")

    if run.foreground_color is not None:
        c = run.foreground_color
        text_style["foregroundColor"] = {
            "color": {"rgbColor": {"red": c.red, "green": c.green, "blue": c.blue}}
        }
        fields.append("foregroundColor")

    if run.background_color is not None:
        c = run.background_color
        text_style["backgroundColor"] = {
            "color": {"rgbColor": {"red": c.red, "green": c.green, "blue": c.blue}}
        }
        fields.append("backgroundColor")

    if run.baseline_offset is not None:
        text_style["baselineOffset"] = run.baseline_offset
        fields.append("baselineOffset")

    if run.small_caps is not None:
        text_style["smallCaps"] = run.small_caps
        fields.append("smallCaps")

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

    Phases:
      1. Re-fetch → get cell positions
      2. If any colspan/rowspan > 1: emit mergeTableCells, re-fetch
      3. If any cell has a nested_table: insert nested table shells, re-fetch
      4. Emit insertText + updateTextStyle for outer cells (high→low)
      5. If nested tables: re-fetch, fill nested cells (high→low)
      6. Emit updateTableColumnProperties for tables with col_widths
      7. If any cell has Phase 3 style fields: emit updateTableCellStyle

    Nested table limitations (first pass): one level of nesting only; cells
    containing a nested_table should not also contain text runs (runs are
    dropped); no colspan/rowspan or col_widths inside nested tables.
    """
    if not tables:
        return

    has_merges = any(
        cell.colspan > 1 or cell.rowspan > 1
        for table in tables
        for row in table.rows
        for cell in row.cells
    )
    has_nested = any(
        cell.nested_table is not None
        for table in tables
        for row in table.rows
        for cell in row.cells
    )

    # Step 1: re-fetch to get live cell positions
    live_doc = docs_service.documents().get(documentId=doc_id).execute()
    doc_tables = _top_level_tables(live_doc)

    # Step 2: outer merges
    if has_merges:
        merge_requests = _build_merge_requests(doc_tables, tables)
        if merge_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": merge_requests}
            ).execute()
            live_doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_tables = _top_level_tables(live_doc)

    # Step 3: insert nested table shells into cells
    if has_nested:
        nested_inserts = _build_nested_table_inserts(doc_tables, tables)
        if nested_inserts:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": nested_inserts}
            ).execute()
            live_doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_tables = _top_level_tables(live_doc)

    # Step 4: fill outer cell text
    fill_requests = _build_fill_requests(doc_tables, tables)
    if fill_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": fill_requests}
        ).execute()

    # Step 5: fill nested table cells
    if has_nested:
        live_doc = docs_service.documents().get(documentId=doc_id).execute()
        doc_tables = _top_level_tables(live_doc)
        n_doc, n_ast = _collect_nested_table_pairs(doc_tables, tables)
        nested_fill = _build_fill_requests(n_doc, n_ast)
        if nested_fill:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": nested_fill}
            ).execute()

    # Step 6: column widths — requires table startIndex from live doc
    width_requests = _build_width_requests(live_doc, tables)
    if width_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": width_requests}
        ).execute()

    # Step 7: Phase 3 cell styling (background, padding, borders)
    has_cell_styles = any(
        cell.background_color is not None
        or cell.padding_top is not None
        or cell.padding_right is not None
        or cell.padding_bottom is not None
        or cell.padding_left is not None
        or cell.border_color is not None
        or cell.border_width is not None
        or cell.border_dash_style is not None
        for table in tables
        for row in table.rows
        for cell in row.cells
    )
    if has_cell_styles:
        live_doc = docs_service.documents().get(documentId=doc_id).execute()
        doc_tables = _top_level_tables(live_doc)
        cell_style_requests = _build_cell_style_requests(doc_tables, tables)
        if cell_style_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": cell_style_requests}
            ).execute()


def _top_level_tables(live_doc: dict) -> list[dict]:
    return [
        elem["table"] for elem in live_doc.get("body", {}).get("content", []) if "table" in elem
    ]


def _build_nested_table_inserts(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Emit insertTable requests (HIGH→LOW) for nested tables that live inside outer cells."""
    inserts: list[tuple[int, dict]] = []
    for doc_table, ast_table in zip(doc_tables, ast_tables):
        doc_rows = doc_table.get("tableRows", [])
        phantom = _build_phantom_set(ast_table)
        total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
        if total_cols == 0:
            continue
        for r, (doc_row_entry, ast_row) in enumerate(zip(doc_rows, ast_table.rows)):
            doc_cells = sorted(
                doc_row_entry.get("tableCells", []), key=lambda c: c.get("startIndex", 0)
            )
            mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)
            for doc_cell, ast_cell_idx in zip(doc_cells, mapping):
                if ast_cell_idx is None:
                    continue
                nested = ast_row.cells[ast_cell_idx].nested_table
                if nested is None:
                    continue
                num_rows = len(nested.rows)
                num_cols = max(
                    (sum(c.colspan for c in row.cells) for row in nested.rows), default=0
                )
                if num_rows == 0 or num_cols == 0:
                    continue
                cell_content = doc_cell.get("content", [])
                if not cell_content:
                    continue
                para_start = cell_content[0].get("startIndex")
                if para_start is None:
                    continue
                inserts.append(
                    (
                        para_start,
                        {
                            "insertTable": {
                                "rows": num_rows,
                                "columns": num_cols,
                                "location": {"index": para_start},
                            }
                        },
                    )
                )
    inserts.sort(key=lambda x: x[0], reverse=True)
    return [req for _, req in inserts]


def _collect_nested_table_pairs(
    doc_tables: list[dict], ast_tables: list[Table]
) -> tuple[list[dict], list[Table]]:
    """Return (doc_table_list, ast_table_list) for nested tables found inside outer cells."""
    nested_doc: list[dict] = []
    nested_ast: list[Table] = []
    for doc_table, ast_table in zip(doc_tables, ast_tables):
        doc_rows = doc_table.get("tableRows", [])
        phantom = _build_phantom_set(ast_table)
        total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
        if total_cols == 0:
            continue
        for r, (doc_row_entry, ast_row) in enumerate(zip(doc_rows, ast_table.rows)):
            doc_cells = sorted(
                doc_row_entry.get("tableCells", []), key=lambda c: c.get("startIndex", 0)
            )
            mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)
            for doc_cell, ast_cell_idx in zip(doc_cells, mapping):
                if ast_cell_idx is None:
                    continue
                ast_cell = ast_row.cells[ast_cell_idx]
                if ast_cell.nested_table is None:
                    continue
                for elem in doc_cell.get("content", []):
                    if "table" in elem:
                        nested_doc.append(elem["table"])
                        nested_ast.append(ast_cell.nested_table)
                        break
    return nested_doc, nested_ast


def _build_phantom_set(ast_table: Table) -> set[tuple[int, int]]:
    """Return (row, col) logical positions covered by rowspan from a cell in an earlier row."""
    phantom: set[tuple[int, int]] = set()
    for r, ast_row in enumerate(ast_table.rows):
        col = 0
        for ast_cell in ast_row.cells:
            while (r, col) in phantom:
                col += 1
            for dr in range(ast_cell.rowspan):
                for dc in range(ast_cell.colspan):
                    if dr > 0 or dc > 0:
                        phantom.add((r + dr, col + dc))
            col += ast_cell.colspan
    return phantom


def _physical_to_ast_indices(
    r: int, ast_row: Row, phantom: set[tuple[int, int]], total_cols: int
) -> list[int | None]:
    """Map each physical doc cell index in row r to an AST cell index, or None if phantom.

    Physical cells = all logical columns except colspan-absorbed ones.
    Rowspan phantom cells are still physical (present in the doc after merge) but are skipped.
    """
    # Determine which logical cols are absorbed by colspan (not physical cells)
    absorbed: set[int] = set()
    logical_col = 0
    for ast_cell in ast_row.cells:
        while (r, logical_col) in phantom:
            logical_col += 1
        for dc in range(1, ast_cell.colspan):
            absorbed.add(logical_col + dc)
        logical_col += ast_cell.colspan

    mapping: list[int | None] = []
    ast_idx = 0
    for col in range(total_cols):
        if col in absorbed:
            # Colspan phantom — remains as a physical cell in the doc after mergeTableCells,
            # just like a rowspan phantom. Map to None so it gets skipped during fill.
            mapping.append(None)
        elif (r, col) in phantom:
            mapping.append(None)  # rowspan phantom — physical but owned by an earlier row
        else:
            mapping.append(ast_idx)
            ast_idx += 1
    return mapping


def _build_merge_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Emit mergeTableCells for any cell with colspan > 1 or rowspan > 1."""
    requests: list[dict] = []
    for doc_table, ast_table in zip(doc_tables, ast_tables):
        table_start = _table_start_index(doc_table)
        if table_start is None:
            continue

        phantom = _build_phantom_set(ast_table)

        for r, ast_row in enumerate(ast_table.rows):
            logical_col = 0
            # Each colspan merge removes (colspan-1) physical cells from this row;
            # rowspan phantoms remain as physical cells and don't shift column indices.
            colspan_removed = 0
            for ast_cell in ast_row.cells:
                while (r, logical_col) in phantom:
                    logical_col += 1
                if ast_cell.colspan > 1 or ast_cell.rowspan > 1:
                    physical_col = logical_col - colspan_removed
                    requests.append(
                        {
                            "mergeTableCells": {
                                "tableRange": {
                                    "tableCellLocation": {
                                        "tableStartLocation": {"index": table_start},
                                        "rowIndex": r,
                                        "columnIndex": physical_col,
                                    },
                                    "rowSpan": ast_cell.rowspan,
                                    "columnSpan": ast_cell.colspan,
                                }
                            }
                        }
                    )
                if ast_cell.colspan > 1:
                    colspan_removed += ast_cell.colspan - 1
                logical_col += ast_cell.colspan
    return requests


def _build_fill_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Build insertText + updateTextStyle requests for all table cells, sorted high→low."""
    all_requests: list[tuple[int, list[dict]]] = []

    for doc_table, ast_table in zip(doc_tables, ast_tables):
        doc_rows = doc_table.get("tableRows", [])
        phantom = _build_phantom_set(ast_table)
        total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
        if total_cols == 0:
            continue

        for r, (doc_row_entry, ast_row) in enumerate(zip(doc_rows, ast_table.rows)):
            # Sort by startIndex: after mergeTableCells, the API may return covered
            # (phantom) cells last rather than in column order.
            doc_cells = sorted(
                doc_row_entry.get("tableCells", []), key=lambda c: c.get("startIndex", 0)
            )
            mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)

            for doc_cell, ast_cell_idx in zip(doc_cells, mapping):
                if ast_cell_idx is None:
                    continue  # rowspan phantom — skip
                ast_cell = ast_row.cells[ast_cell_idx]
                cell_runs = ast_cell.runs
                cell_text = "".join(run.text for run in cell_runs)
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
                    {"insertText": {"location": {"index": para_start}, "text": cell_text}}
                )
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

    all_requests.sort(key=lambda x: x[0], reverse=True)
    return [req for _, reqs in all_requests for req in reqs]


def _build_cell_style_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Build updateTableCellStyle requests for cells with Phase 3 style fields set."""
    requests: list[dict] = []

    def _rgb(color) -> dict:
        return {"color": {"rgbColor": {"red": color.red, "green": color.green, "blue": color.blue}}}

    def _pt(magnitude: float) -> dict:
        return {"magnitude": magnitude, "unit": "PT"}

    for doc_table, ast_table in zip(doc_tables, ast_tables):
        table_start = _table_start_index(doc_table)
        if table_start is None:
            continue
        phantom = _build_phantom_set(ast_table)
        total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
        if total_cols == 0:
            continue

        for r, ast_row in enumerate(ast_table.rows):
            mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)
            for col, ast_cell_idx in enumerate(mapping):
                if ast_cell_idx is None:
                    continue
                ast_cell = ast_row.cells[ast_cell_idx]

                cell_style: dict = {}
                style_fields: list[str] = []

                if ast_cell.background_color is not None:
                    cell_style["backgroundColor"] = _rgb(ast_cell.background_color)
                    style_fields.append("backgroundColor")

                if ast_cell.padding_top is not None:
                    cell_style["paddingTop"] = _pt(ast_cell.padding_top)
                    style_fields.append("paddingTop")
                if ast_cell.padding_right is not None:
                    cell_style["paddingRight"] = _pt(ast_cell.padding_right)
                    style_fields.append("paddingRight")
                if ast_cell.padding_bottom is not None:
                    cell_style["paddingBottom"] = _pt(ast_cell.padding_bottom)
                    style_fields.append("paddingBottom")
                if ast_cell.padding_left is not None:
                    cell_style["paddingLeft"] = _pt(ast_cell.padding_left)
                    style_fields.append("paddingLeft")

                if any([ast_cell.border_color, ast_cell.border_width, ast_cell.border_dash_style]):
                    border: dict = {}
                    if ast_cell.border_color is not None:
                        border["color"] = _rgb(ast_cell.border_color)
                    if ast_cell.border_width is not None:
                        border["width"] = _pt(ast_cell.border_width)
                    if ast_cell.border_dash_style is not None:
                        border["dashStyle"] = ast_cell.border_dash_style
                    for side in ("borderTop", "borderBottom", "borderLeft", "borderRight"):
                        cell_style[side] = border
                        style_fields.append(side)

                if not style_fields:
                    continue

                requests.append(
                    {
                        "updateTableCellStyle": {
                            "tableCellStyle": cell_style,
                            "fields": ",".join(style_fields),
                            "tableRange": {
                                "tableCellLocation": {
                                    "tableStartLocation": {"index": table_start},
                                    "rowIndex": r,
                                    "columnIndex": col,
                                },
                                "rowSpan": 1,
                                "columnSpan": 1,
                            },
                        }
                    }
                )

    return requests


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
