"""Document AST → Docs API batchUpdate requests."""

from __future__ import annotations

import logging

from .ast import BulletItem, Cell, DocNode, Heading, NamedBlock, Paragraph, Row, Run, Table

logger = logging.getLogger(__name__)


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
            num_rows = len(node.rows)
            num_cols = max((sum(c.colspan for c in row.cells) for row in node.rows), default=0)
            if num_rows == 0 or num_cols == 0:
                # No insertTable request is emitted below for a degenerate table, so it must
                # not be added to `tables` either — fill_tables() zips this list positionally
                # against the tables actually present in the live doc, and a table with no
                # insertTable request never shows up there.
                continue
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
      3. Fill plain cells (no nested table) — insertText + updateTextStyle, high→low
      4. Fill cells with a nested table, segment by segment (see
         _fill_nested_cell_content) — text and tables in true source order,
         recursing into any depth of further nesting. Each nested table's own
         merges are handled by _fill_table_fully, mirroring phase 2 above (#109).
      5. Emit updateTableColumnProperties for tables with col_widths
      6. If any cell has Phase 3 style fields: emit updateTableCellStyle

    Nested table limitations: no col_widths inside nested tables. colspan/
    rowspan (#109) and text sharing a cell with one or more nested tables
    (#108, #275) are both fully supported, at any nesting depth — each run of
    text, merge, and nested table renders in the same order and shape it had
    in the source.
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
        any(isinstance(child, Table) for child in cell.children)
        for table in tables
        for row in table.rows
        for cell in row.cells
    )

    # Step 1: fetch doc; collapse blank paragraphs stranded immediately before tables (an
    # artifact of phase-1 insertText displacing the doc's initial empty paragraph).  The
    # Docs API rejects deleteContentRange on these paragraphs because a paragraph before a
    # table is structurally required, so we shrink them to zero visual height instead.
    live_doc = docs_service.documents().get(documentId=doc_id).execute()
    blank_collapses = _build_blank_para_before_table_collapses(live_doc)
    if blank_collapses:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": blank_collapses}
        ).execute()
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

    # Step 3: fill plain cells (no nested table) in one bulk batch
    fill_requests = _build_fill_requests(doc_tables, tables)
    if fill_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": fill_requests}
        ).execute()

    # Step 4: fill cells that contain a nested table, preserving true content order
    # at any nesting depth
    if has_nested:
        _fill_nested_cell_content(docs_service, doc_id, tables)

    # Step 5: column widths — requires table startIndex from live doc
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


def _ast_cell_to_doc_cell(doc_table: dict, ast_table: Table, r: int, ast_col: int) -> dict | None:
    """Return the physical doc cell for logical (row=r, ast column=ast_col)."""
    doc_rows = doc_table.get("tableRows", [])
    if r >= len(doc_rows):
        return None
    phantom = _build_phantom_set(ast_table)
    ast_row = ast_table.rows[r]
    total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
    doc_cells = sorted(doc_rows[r].get("tableCells", []), key=lambda c: c.get("startIndex", 0))
    mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)
    for doc_cell, ast_cell_idx in zip(doc_cells, mapping):
        if ast_cell_idx == ast_col:
            return doc_cell
    return None


def _is_insertable_table(child: Run | Table) -> bool:
    """A Table child only actually gets an insertTable shell (and thus a
    paragraph/table/paragraph split in the live doc) if it has at least one row
    and one column — see the `num_rows > 0 and num_cols > 0` guard where
    insertTable requests are built. A degenerate table (e.g. a row with no
    cells — reachable, pre-clamp-fix, via colspan="0"/rowspan="0" HTML) must
    NOT be counted as "already inserted" by cursor/paragraph-counting logic,
    or every later segment in the same cell resolves to the wrong paragraph.
    """
    if not isinstance(child, Table):
        return False
    num_rows = len(child.rows)
    num_cols = max((sum(c.colspan for c in row.cells) for row in child.rows), default=0)
    return num_rows > 0 and num_cols > 0


def _cell_para_start_for_cursor(doc_cell: dict, ast_cell: Cell, cursor: int) -> int | None:
    """Return the startIndex of the paragraph a cell's next unfilled segment belongs in.

    A cell's `content` alternates paragraph/table/paragraph/table/... — the Nth
    paragraph (0-indexed) is the one immediately after the Nth already-inserted
    nested table, where N = how many *insertable* Table children precede
    `cursor` (see _is_insertable_table). This is the paragraph's own
    startIndex — callers inserting a Table (not text) must add
    _text_offset_since_last_table() on top, since earlier text in the same
    paragraph (inserted in a prior round) isn't reflected in the paragraph's
    unchanged startIndex.
    """
    tables_before = sum(1 for child in ast_cell.children[:cursor] if _is_insertable_table(child))
    paragraphs = [elem for elem in doc_cell.get("content", []) if "paragraph" in elem]
    if tables_before >= len(paragraphs):
        return None
    return paragraphs[tables_before].get("startIndex")


def _text_offset_since_last_table(children: list[Run | Table], cursor: int) -> int:
    """Sum of Run text lengths between the nearest preceding *insertable* Table
    (exclusive) and cursor — a degenerate table is transparent here since it
    was never actually inserted (see _is_insertable_table).

    A Table's insertion point is its paragraph's startIndex *plus* this offset,
    since any leading text already inserted into that same paragraph (in an
    earlier round) shifts where the table must land but doesn't change the
    paragraph's own startIndex.
    """
    offset = 0
    for i in range(cursor - 1, -1, -1):
        child = children[i]
        if _is_insertable_table(child):
            break
        if isinstance(child, Run):
            offset += len(child.text)
    return offset


def _find_nth_table_in_cell(
    doc_table: dict, ast_table: Table, r: int, c: int, occurrence: int
) -> dict | None:
    """Return the `occurrence`-th (0-indexed) nested table element inside cell (r, c)."""
    doc_cell = _ast_cell_to_doc_cell(doc_table, ast_table, r, c)
    if doc_cell is None:
        return None
    nested_tables = [elem["table"] for elem in doc_cell.get("content", []) if "table" in elem]
    if occurrence >= len(nested_tables):
        return None
    return nested_tables[occurrence]


def _run_group_fill_requests(runs: list[Run], para_start: int) -> list[dict]:
    """Build insertText + updateTextStyle requests for a contiguous run of text."""
    text = "".join(run.text for run in runs)
    if not text:
        return []
    requests: list[dict] = [
        {"insertText": {"location": {"index": para_start}, "text": text}},
        # Clear any fontSize inherited from a preceding heading — see _build_fill_requests.
        {
            "updateTextStyle": {
                "range": {"startIndex": para_start, "endIndex": para_start + len(text)},
                "textStyle": {},
                "fields": "fontSize",
            }
        },
    ]
    offset = 0
    for run in runs:
        run_len = len(run.text)
        if run_len > 0:
            requests.extend(
                _run_style_requests(run, para_start + offset, para_start + offset + run_len)
            )
        offset += run_len
    return requests


def _fill_nested_cell_content(docs_service, doc_id: str, tables: list[Table]) -> None:
    """Fill every cell that contains a nested table, preserving true content order.

    Cells with no nested table are handled in bulk by _build_fill_requests instead
    (faster, one batch for the whole document). This function only processes cells
    whose `children` include at least one Table, recursing into any depth of
    further nesting (#108, #275): each round emits one contiguous segment — a
    run of text or one nested table's shell — per still-pending cell, sorted
    high→low within the round, then re-fetches before the next round.
    """
    _fill_children_recursive(
        docs_service, doc_id, lambda live_doc: _top_level_tables(live_doc), tables
    )


def _fill_children_recursive(
    docs_service,
    doc_id: str,
    resolve,
    ast_tables: list[Table],
    _doc_tables: list[dict] | None = None,
) -> None:
    """resolve(live_doc) -> doc_table dicts positionally matching ast_tables.

    _doc_tables: already-fetched, still-valid doc_tables to seed the first
    round with — pass this when the caller knows nothing has changed in the
    live doc since it last fetched, to avoid a redundant re-fetch.
    """
    pending: dict[tuple[int, int, int], int] = {}
    for t, table in enumerate(ast_tables):
        for r, row in enumerate(table.rows):
            for c, cell in enumerate(row.cells):
                if any(isinstance(child, Table) for child in cell.children):
                    pending[(t, r, c)] = 0
    if not pending:
        return

    if _doc_tables is not None:
        doc_tables = _doc_tables
    else:
        live_doc = docs_service.documents().get(documentId=doc_id).execute()
        doc_tables = resolve(live_doc)

    while pending:
        round_requests: list[tuple[int, list[dict]]] = []
        table_inserts: list[tuple[int, int, int, int, Table]] = []  # (t, r, c, occurrence, table)
        done = []

        for (t, r, c), cursor in pending.items():
            doc_table = doc_tables[t] if t < len(doc_tables) else None
            ast_table = ast_tables[t]
            ast_cell = ast_table.rows[r].cells[c]
            children = ast_cell.children
            if doc_table is None or cursor >= len(children):
                done.append((t, r, c))
                continue
            doc_cell = _ast_cell_to_doc_cell(doc_table, ast_table, r, c)
            if doc_cell is None:
                done.append((t, r, c))
                continue
            para_start = _cell_para_start_for_cursor(doc_cell, ast_cell, cursor)
            if para_start is None:
                done.append((t, r, c))
                continue

            child = children[cursor]
            if isinstance(child, Table):
                num_rows = len(child.rows)
                num_cols = max(
                    (sum(cc.colspan for cc in row.cells) for row in child.rows), default=0
                )
                occurrence = sum(1 for ch in children[:cursor] if _is_insertable_table(ch))
                # Any text already inserted earlier this round-chain, in the same
                # paragraph, shifts the table's landing spot past that text.
                table_start = para_start + _text_offset_since_last_table(children, cursor)
                if num_rows > 0 and num_cols > 0:
                    round_requests.append(
                        (
                            table_start,
                            [
                                {
                                    "insertTable": {
                                        "rows": num_rows,
                                        "columns": num_cols,
                                        "location": {"index": table_start},
                                    }
                                }
                            ],
                        )
                    )
                    table_inserts.append((t, r, c, occurrence, child))
                new_cursor = cursor + 1
            else:
                j = cursor
                run_group: list[Run] = []
                while j < len(children) and isinstance(children[j], Run):
                    next_run = children[j]
                    assert isinstance(next_run, Run)
                    run_group.append(next_run)
                    j += 1
                reqs = _run_group_fill_requests(run_group, para_start)
                if reqs:
                    round_requests.append((para_start, reqs))
                new_cursor = j

            pending[(t, r, c)] = new_cursor
            if new_cursor >= len(children):
                done.append((t, r, c))

        for key in done:
            del pending[key]

        if round_requests:
            round_requests.sort(key=lambda x: x[0], reverse=True)
            batch = [req for _, reqs in round_requests for req in reqs]
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": batch}
            ).execute()
        # No `break` here even when a round emits no requests (e.g. a degenerate
        # zero-column table skipped by the `num_rows > 0 and num_cols > 0` guard
        # above): cursors still advance every round for every non-done cell, so
        # `pending` truthfulness alone correctly drives loop termination — a
        # `break` on empty round_requests would silently abandon any cells whose
        # only remaining work that round was such a skip.

        for t, r, c, occurrence, table_child in table_inserts:
            parent_resolve = resolve

            def child_resolve(live_doc, _resolve=parent_resolve, _t=t, _r=r, _c=c, _occ=occurrence):
                parent_tables = _resolve(live_doc)
                if _t >= len(parent_tables) or parent_tables[_t] is None:
                    return [None]
                return [_find_nth_table_in_cell(parent_tables[_t], ast_tables[_t], _r, _c, _occ)]

            # This performs its own batchUpdate(s), which shift indices for any
            # outer-cell content that comes after this nested table — the outer
            # loop's own doc_tables (re-fetched below) must reflect that.
            _fill_table_fully(docs_service, doc_id, child_resolve, table_child)

        if pending:
            live_doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_tables = resolve(live_doc)


def _fill_table_fully(docs_service, doc_id: str, resolve, ast_table: Table) -> None:
    """Fill one (typically just-inserted) table's cells: merges first, then
    plain cells in bulk, then cells with a further nested table via the
    recursive round algorithm.

    Every nested table needs this — not just ones with further nesting — since
    a nested table's own plain-text cells (and merges) are never touched by the
    top-level fill_tables passes (those only see the outer tables list).
    """
    live_doc = docs_service.documents().get(documentId=doc_id).execute()
    doc_tables = resolve(live_doc)
    if not doc_tables or doc_tables[0] is None:
        logger.debug(
            "_fill_table_fully: could not locate nested table in live doc %s — "
            "skipping fill for this table (it will render as an empty shell)",
            doc_id,
        )
        return

    has_merges = any(
        cell.colspan > 1 or cell.rowspan > 1 for row in ast_table.rows for cell in row.cells
    )
    if has_merges:
        merge_requests = _build_merge_requests(doc_tables, [ast_table])
        if merge_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": merge_requests}
            ).execute()
            live_doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_tables = resolve(live_doc)
            if not doc_tables or doc_tables[0] is None:
                logger.debug(
                    "_fill_table_fully: nested table vanished after merge in live doc %s — "
                    "skipping fill for this table (it will render as an empty shell)",
                    doc_id,
                )
                return

    fill_requests = _build_fill_requests(doc_tables, [ast_table])
    if fill_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": fill_requests}
        ).execute()
        # The bulk fill just shifted indices — the recursive call must re-fetch.
        _fill_children_recursive(docs_service, doc_id, resolve, [ast_table])
    else:
        # Nothing changed since doc_tables was fetched above — reuse it instead
        # of having the recursive call redundantly re-fetch identical data.
        _fill_children_recursive(docs_service, doc_id, resolve, [ast_table], _doc_tables=doc_tables)


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
    """Build insertText + updateTextStyle requests for cells with no nested table,
    sorted high→low, so they can all be emitted in one batch. Cells that contain a
    nested table are skipped here — _fill_nested_cell_content handles those instead,
    since a nested table needs its own live-index re-fetch cycle.
    """
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
                if any(isinstance(child, Table) for child in ast_cell.children):
                    continue  # handled by _fill_nested_cell_content instead
                cell_runs = [child for child in ast_cell.children if isinstance(child, Run)]
                cell_text = "".join(run.text for run in cell_runs)
                if not cell_text:
                    continue
                cell_content = doc_cell.get("content", [])
                if not cell_content:
                    continue
                para_start = cell_content[0].get("startIndex")
                if para_start is None:
                    continue

                cell_requests = _run_group_fill_requests(cell_runs, para_start)
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


def _build_blank_para_before_table_collapses(live_doc: dict) -> list[dict]:
    """Return updateParagraphStyle + updateTextStyle requests that collapse empty paragraphs
    immediately before tables to zero visual height.

    Phase-1 insertText displaces the doc's initial empty paragraph, leaving a blank line
    stranded between the preceding content and the table.  deleteContentRange is rejected by
    the Docs API for these paragraphs (a paragraph before a table is structurally required),
    so we shrink them instead: spaceAbove/Below = 0, lineSpacing = 1 (1% of normal),
    fontSize = 1 pt.  Only paragraphs whose sole content is a newline are affected.
    """
    content = live_doc.get("body", {}).get("content", [])
    requests: list[dict] = []
    for i, elem in enumerate(content):
        if "table" not in elem or i == 0:
            continue
        prev = content[i - 1]
        if "paragraph" not in prev:
            continue
        para_text = "".join(
            el.get("textRun", {}).get("content", "") for el in prev["paragraph"].get("elements", [])
        )
        if para_text != "\n":
            continue
        start = prev.get("startIndex")
        end = prev.get("endIndex")
        if start is None or end is None:
            continue
        rng = {"startIndex": start, "endIndex": end}
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": {
                        "spaceAbove": {"magnitude": 0, "unit": "PT"},
                        "spaceBelow": {"magnitude": 0, "unit": "PT"},
                        "lineSpacing": 1,
                    },
                    "fields": "spaceAbove,spaceBelow,lineSpacing",
                }
            }
        )
        requests.append(
            {
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"fontSize": {"magnitude": 1, "unit": "PT"}},
                    "fields": "fontSize",
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
