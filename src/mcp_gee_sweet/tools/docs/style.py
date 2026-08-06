import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread

logger = logging.getLogger(__name__)


_NAMED_STYLE_TYPES = frozenset(
    {
        "NORMAL_TEXT",
        "HEADING_1",
        "HEADING_2",
        "HEADING_3",
        "HEADING_4",
        "HEADING_5",
        "HEADING_6",
        "TITLE",
        "SUBTITLE",
    }
)


def _read_body_styles(doc: dict) -> dict:
    """Derive a theme dict from body paragraph styles — first occurrence per named style type.

    AI-generated docs apply explicit styles to individual paragraphs and runs rather than
    setting namedStyles defaults. This function reads the actual applied styles from the body
    so the returned theme reflects what the document looks like. Subsequent paragraphs of
    the same namedStyleType with different styles are ignored (treated as intentional
    individual overrides outside the theme system).
    """
    theme: dict = {}
    for elem in doc.get("body", {}).get("content", []):
        para = elem.get("paragraph")
        if not para:
            continue
        style_type = para.get("paragraphStyle", {}).get("namedStyleType")
        if style_type not in _NAMED_STYLE_TYPES or style_type in theme:
            continue
        entry: dict = {}
        ps = para.get("paragraphStyle", {})
        if "lineSpacing" in ps:
            entry["line_spacing"] = ps["lineSpacing"]
        space_above = ps.get("spaceAbove", {}).get("magnitude")
        if space_above is not None:
            entry["space_above"] = space_above
        space_below = ps.get("spaceBelow", {}).get("magnitude")
        if space_below is not None:
            entry["space_below"] = space_below
        for element in para.get("elements", []):
            tr = element.get("textRun")
            if not tr or not tr.get("content", "").strip():
                continue
            ts = tr.get("textStyle", {})
            ff = ts.get("weightedFontFamily", {}).get("fontFamily")
            if ff:
                entry["font_family"] = ff
            fs = ts.get("fontSize", {}).get("magnitude")
            if fs is not None:
                entry["font_size"] = fs
            if "bold" in ts:
                entry["bold"] = ts["bold"]
            if "italic" in ts:
                entry["italic"] = ts["italic"]
            rgb = ts.get("foregroundColor", {}).get("color", {}).get("rgbColor")
            if rgb:
                entry["color"] = {k: rgb[k] for k in ("red", "green", "blue") if k in rgb}
            break  # first non-empty run only
        if entry:
            theme[style_type] = entry
    return theme


def _read_named_styles(doc: dict) -> dict:
    """Read a theme dict from a doc's namedStyles defaults.

    Returns what was set via Format > Paragraph styles > Update X to match in the
    Google Docs UI. For docs where styles were applied directly to paragraphs without
    updating named styles, this will reflect Google's defaults rather than the doc's
    actual appearance — use _read_body_styles in that case.
    """
    theme: dict = {}
    for style in doc.get("namedStyles", {}).get("styles", []):
        style_type = style.get("namedStyleType")
        if style_type not in _NAMED_STYLE_TYPES:
            continue
        entry: dict = {}
        ts = style.get("textStyle", {})
        ff = ts.get("weightedFontFamily", {}).get("fontFamily")
        if ff:
            entry["font_family"] = ff
        fs = ts.get("fontSize", {}).get("magnitude")
        if fs is not None:
            entry["font_size"] = fs
        if "bold" in ts:
            entry["bold"] = ts["bold"]
        if "italic" in ts:
            entry["italic"] = ts["italic"]
        rgb = ts.get("foregroundColor", {}).get("color", {}).get("rgbColor")
        if rgb:
            entry["color"] = {k: rgb[k] for k in ("red", "green", "blue") if k in rgb}
        ps = style.get("paragraphStyle", {})
        if "lineSpacing" in ps:
            entry["line_spacing"] = ps["lineSpacing"]
        space_above = ps.get("spaceAbove", {}).get("magnitude")
        if space_above is not None:
            entry["space_above"] = space_above
        space_below = ps.get("spaceBelow", {}).get("magnitude")
        if space_below is not None:
            entry["space_below"] = space_below
        if entry:
            theme[style_type] = entry
    return theme


def _text_style_and_fields(style: dict) -> tuple[dict, list[str]]:
    """Build a Docs API textStyle dict + field mask from a flat style dict keyed
    by bold/italic/underline/strikethrough/font_size/foreground_color/link_url.

    Shared by style_doc_range and insert_softbreak_paragraph so both tools draw
    per-run styling from the same key vocabulary and request-building logic.
    """
    text_style: dict = {}
    fields: list[str] = []
    for key in ("bold", "italic", "underline", "strikethrough"):
        if key in style:
            text_style[key] = style[key]
            fields.append(key)
    if "font_size" in style:
        text_style["fontSize"] = {"magnitude": style["font_size"], "unit": "PT"}
        fields.append("fontSize")
    if "foreground_color" in style:
        text_style["foregroundColor"] = {"color": {"rgbColor": style["foreground_color"]}}
        fields.append("foregroundColor")
    if "link_url" in style:
        # Clearing a link (link_url falsy) must omit "link" from textStyle
        # entirely rather than setting it to an empty Link{} object — the API
        # rejects an empty Link ("must include at least one type") since
        # that's not a valid Link value, but omitting the key while still
        # naming "link" in the field mask is the documented way to reset a
        # nested message field to its default (no link) (#408).
        if style["link_url"]:
            text_style["link"] = {"url": style["link_url"]}
        fields.append("link")
    return text_style, fields


def _build_named_style_requests(style_type: str, entry: dict) -> list[dict]:
    """Build an updateNamedStyle batchUpdate request for one named style type.

    Field mask paths use snake_case (per Docs API spec) and must include
    named_style_type. The root named_style prefix is implied by the API.
    """
    ts: dict = {}
    ts_fields: list[str] = []
    if "font_family" in entry:
        ts["weightedFontFamily"] = {"fontFamily": entry["font_family"]}
        ts_fields.append("text_style.weighted_font_family")
    if "font_size" in entry:
        ts["fontSize"] = {"magnitude": entry["font_size"], "unit": "PT"}
        ts_fields.append("text_style.font_size")
    if "bold" in entry:
        ts["bold"] = entry["bold"]
        ts_fields.append("text_style.bold")
    if "italic" in entry:
        ts["italic"] = entry["italic"]
        ts_fields.append("text_style.italic")
    if "color" in entry:
        ts["foregroundColor"] = {"color": {"rgbColor": entry["color"]}}
        ts_fields.append("text_style.foreground_color")

    ps: dict = {}
    ps_fields: list[str] = []
    if "line_spacing" in entry:
        ps["lineSpacing"] = entry["line_spacing"]
        ps_fields.append("paragraph_style.line_spacing")
    if "space_above" in entry:
        ps["spaceAbove"] = {"magnitude": entry["space_above"], "unit": "PT"}
        ps_fields.append("paragraph_style.space_above")
    if "space_below" in entry:
        ps["spaceBelow"] = {"magnitude": entry["space_below"], "unit": "PT"}
        ps_fields.append("paragraph_style.space_below")

    all_fields = ts_fields + ps_fields
    if not all_fields:
        return []

    # named_style_type must always be present in the field mask
    named_style: dict = {"namedStyleType": style_type}
    if ts:
        named_style["textStyle"] = ts
    if ps:
        named_style["paragraphStyle"] = ps

    return [
        {
            "updateNamedStyle": {
                "namedStyle": named_style,
                "fields": "named_style_type," + ",".join(all_fields),
            }
        }
    ]


def register(tool):
    @tool(annotations=ToolAnnotations(title="Style Document Range", destructiveHint=True))
    async def style_doc_range(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply paragraph and/or text styles to one or more index ranges in a Google Doc.

        Use get_doc_structure to obtain the startIndex and endIndex for each target range.
        Multiple ranges can be styled in a single call; all batchUpdate requests are
        sent together.

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts. Each dict must include start_index and end_index,
                plus any combination of the style fields below:

                Paragraph style:
                  named_style_type (str): NORMAL_TEXT, HEADING_1 … HEADING_6,
                      TITLE, SUBTITLE

                Text style:
                  bold (bool), italic (bool), underline (bool), strikethrough (bool)
                  font_size (float): size in points
                  foreground_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                  link_url (str | null): set a hyperlink (null to clear)

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}

        requests = []
        for r in ranges:
            rng = {"startIndex": r["start_index"], "endIndex": r["end_index"]}

            if "named_style_type" in r:
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": r["named_style_type"]},
                            "fields": "namedStyleType",
                        }
                    }
                )

            text_style, text_fields = _text_style_and_fields(r)

            # A link-clear-only range (link_url=null, #408) legitimately produces
            # an empty text_style with a non-empty field mask ("link") — the
            # request must still be sent, so gate on text_fields, not text_style.
            if text_fields:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": rng,
                            "textStyle": text_style,
                            "fields": ",".join(text_fields),
                        }
                    }
                )

        if not requests:
            return {"error": "no recognised style fields in any range"}

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("style_doc_range: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Style Document Table Cells", destructiveHint=True))
    async def style_doc_table_cells(
        doc_id: str,
        table_start_index: int,
        cells: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply border, padding, and background styles to table cells in a Google Doc.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure or
                insert_doc_table).
            cells: List of cell style dicts. Each dict must include row_index and
                column_index, plus any combination of:

                background_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                padding_top, padding_right, padding_bottom, padding_left (float): points
                border_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                    Applies the same color to all four borders (any edge not given its
                    own border_top/right/bottom/left below).
                border_width (float): border line width in points
                border_dash_style (str): "SOLID", "DOT", "DASH", "DASH_DOT",
                    "LONG_DASH", "LONG_DASH_DOT" (default SOLID)
                border_top, border_right, border_bottom, border_left (dict): optional
                    per-edge override, each {"color": {...}, "width": float,
                    "dash_style": str}. Any field omitted from a per-edge dict falls
                    back to the uniform border_color/border_width/border_dash_style
                    above, if given (the Docs API rejects a border with non-zero width
                    and no color as "transparent", so a width-only override needs a
                    color from somewhere). An edge with no border_<side> key falls back
                    entirely to the uniform border_color/border_width/border_dash_style,
                    if given; with neither, that edge's border is left untouched.
                row_span (int): default 1
                column_span (int): default 1

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.

        Example — standard data-room table style (grey header, thin border, 3.6pt padding):
            table_start_index: <from insert_doc_table>
            cells: [
              {"row_index": 0, "column_index": 0, "column_span": <num_cols>,
               "background_color": {"red": 0.953, "green": 0.953, "blue": 0.953},
               "padding_top": 3.6, "padding_right": 3.6,
               "padding_bottom": 3.6, "padding_left": 3.6,
               "border_color": {"red": 0, "green": 0, "blue": 0},
               "border_width": 0.5, "border_dash_style": "SOLID"}
            ]

        Example — signature line (bottom border only):
            cells: [
              {"row_index": 0, "column_index": 0,
               "border_bottom": {"color": {"red": 0, "green": 0, "blue": 0}, "width": 1.0}}
            ]

        For form-style column alignment (labels/values lined up without a visible
        table, since tabStops is read-only — #404), zero padding on every cell is
        the confirmed part of the recipe; whether border_width: 0 also suppresses
        a table's default visible border is not yet confirmed live. See
        docs/design/borderless-table-columns.md.
        """
        lc = ctx.request_context.lifespan_context
        if not cells:
            return {"error": "cells list is empty"}

        requests = []
        for cell in cells:
            table_cell_style = {}
            fields = []

            if "background_color" in cell:
                table_cell_style["backgroundColor"] = {
                    "color": {"rgbColor": cell["background_color"]}
                }
                fields.append("backgroundColor")

            for side in ("top", "right", "bottom", "left"):
                key = f"padding_{side}"
                if key in cell:
                    api_key = f"padding{side.capitalize()}"
                    table_cell_style[api_key] = {"magnitude": cell[key], "unit": "PT"}
                    fields.append(api_key)

            has_uniform_border = (
                "border_color" in cell or "border_width" in cell or "border_dash_style" in cell
            )
            uniform_border: dict | None = None
            if has_uniform_border:
                uniform_border = {}
                if "border_color" in cell:
                    uniform_border["color"] = {"color": {"rgbColor": cell["border_color"]}}
                if "border_width" in cell:
                    uniform_border["width"] = {"magnitude": cell["border_width"], "unit": "PT"}
                uniform_border["dashStyle"] = cell.get("border_dash_style", "SOLID")

            for side in ("top", "right", "bottom", "left"):
                edge_key = f"border_{side}"
                api_key = f"border{side.capitalize()}"
                if edge_key in cell:
                    edge_spec = cell[edge_key]
                    if not isinstance(edge_spec, dict):
                        return {
                            "error": f"'{edge_key}' must be a dict with optional "
                            f"'color'/'width'/'dash_style' keys, got "
                            f"{type(edge_spec).__name__}"
                        }
                    border = {}
                    if "color" in edge_spec:
                        border["color"] = {"color": {"rgbColor": edge_spec["color"]}}
                    elif uniform_border is not None and "color" in uniform_border:
                        # The Docs API rejects a border with a non-zero width and no
                        # color as "transparent" — an edge override that only sets
                        # width must still inherit a color from somewhere.
                        border["color"] = uniform_border["color"]
                    if "width" in edge_spec:
                        border["width"] = {"magnitude": edge_spec["width"], "unit": "PT"}
                    elif uniform_border is not None and "width" in uniform_border:
                        border["width"] = uniform_border["width"]
                    if "dash_style" in edge_spec:
                        border["dashStyle"] = edge_spec["dash_style"]
                    elif uniform_border is not None:
                        border["dashStyle"] = uniform_border["dashStyle"]
                    else:
                        border["dashStyle"] = "SOLID"
                    table_cell_style[api_key] = border
                    fields.append(api_key)
                elif uniform_border is not None:
                    table_cell_style[api_key] = uniform_border
                    fields.append(api_key)

            if not table_cell_style:
                continue

            requests.append(
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": table_cell_style,
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": cell["row_index"],
                                "columnIndex": cell["column_index"],
                            },
                            "rowSpan": cell.get("row_span", 1),
                            "columnSpan": cell.get("column_span", 1),
                        },
                        "fields": ",".join(fields),
                    }
                }
            )

        if not requests:
            return {"error": "no style fields found in any cell"}

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("style_doc_table_cells: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Create Paragraph Bullets", destructiveHint=True))
    async def create_paragraph_bullets(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Turn one or more paragraph ranges into a bulleted or numbered list, with
        explicit nesting depth (#334).

        Wraps the Docs API's createParagraphBullets/deleteParagraphBullets
        requests, working around two confirmed-live API quirks:

        - createParagraphBullets is a no-op on a paragraph that's already
          part of a list — it neither changes the existing nesting level nor
          consumes any leading tab characters meant to signal a new one
          (they're left behind as literal text). Every paragraph this tool
          touches is deleteParagraphBullets'd first (harmless even if it
          wasn't previously a list item) so createParagraphBullets always
          applies to a clean, non-list paragraph.
        - createParagraphBullets has no nestingLevel field of its own — the
          API infers each paragraph's depth from its own leading tab
          characters, but only relative to whatever ELSE is included in that
          *same* call. A paragraph immediately adjacent to an existing list
          item that call doesn't also cover gets pulled back to that
          neighbor's level regardless of its own tabs (the same class of bug
          PR #432 fixed in this project's own markdown-to-Doc converter).
          To keep every requested paragraph's relative depth correct, this
          tool fetches the document, resolves each requested range to the
          paragraph(s) it covers, and — for any that are already part of a
          list — expands the affected span to include their full contiguous
          run of same-list neighbors (preserving each neighbor's own current
          nesting level unchanged). Contiguous spans sharing one bullet
          preset are then submitted as a single createParagraphBullets call
          each, applied in descending document-position order so no
          not-yet-processed span's indices are invalidated by an earlier
          span's tab insertions.

        Use get_doc_structure to obtain start_index/end_index for each target
        range — typically one paragraph's own startIndex/endIndex, or a
        contiguous span covering several (all promoted to the same
        nesting_level/bullet_preset). For independent depths per paragraph,
        pass one range per paragraph.

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts, each with:
                start_index (int), end_index (int): from get_doc_structure —
                    must overlap at least one existing paragraph.
                bullet_preset (str, optional): "BULLET_DISC_CIRCLE_SQUARE"
                    (unordered, the default) or "NUMBERED_DECIMAL_ALPHA_ROMAN"
                    (ordered) — the only two presets this codebase has
                    confirmed live (see emitter.py). The Docs API defines
                    additional glyph/numbering presets not exercised here;
                    pass the literal API enum string to use one anyway.
                nesting_level (int, optional): 0 = top-level (default), 1 =
                    one level indented, etc. Must be >= 0.

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
            {"error": ...} if ranges is empty, a nesting_level is negative, a
            range doesn't overlap any paragraph, or the Docs API call fails.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}
        for r in ranges:
            if r.get("nesting_level", 0) < 0:
                return {"error": f"nesting_level must be >= 0, got {r['nesting_level']}"}

        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )

            body_paragraphs = [
                (
                    elem.get("startIndex", 0),
                    elem.get("endIndex", 0),
                    elem["paragraph"].get("bullet"),
                )
                for elem in doc.get("body", {}).get("content", [])
                if "paragraph" in elem
            ]
            by_start = {ps: (pe, b) for ps, pe, b in body_paragraphs}
            by_end = {pe: (ps, b) for ps, pe, b in body_paragraphs}

            requested: dict[tuple[int, int], dict] = {}
            for r in ranges:
                r_start, r_end = r["start_index"], r["end_index"]
                preset = r.get("bullet_preset", "BULLET_DISC_CIRCLE_SQUARE")
                nesting_level = r.get("nesting_level", 0)
                covered = [
                    (ps, pe) for ps, pe, _b in body_paragraphs if ps < r_end and pe > r_start
                ]
                if not covered:
                    return {"error": f"no paragraph overlaps range {r_start}-{r_end}"}
                for ps, pe in covered:
                    requested[(ps, pe)] = {
                        "start": ps,
                        "end": pe,
                        "nesting_level": nesting_level,
                        "preset": preset,
                    }

            # Expand each already-listed requested paragraph to include its
            # full contiguous same-listId neighbor run (see docstring) —
            # context paragraphs keep their own current nesting level.
            expanded: dict[tuple[int, int], dict] = dict(requested)
            for ps, pe, bullet in body_paragraphs:
                key = (ps, pe)
                if key not in requested or not bullet:
                    continue
                list_id = bullet.get("listId")
                preset = requested[key]["preset"]

                cursor = ps
                while cursor in by_end:
                    prev_start, prev_bullet = by_end[cursor]
                    if not prev_bullet or prev_bullet.get("listId") != list_id:
                        break
                    pkey = (prev_start, cursor)
                    if pkey not in expanded:
                        expanded[pkey] = {
                            "start": prev_start,
                            "end": cursor,
                            "nesting_level": prev_bullet.get("nestingLevel", 0),
                            "preset": preset,
                        }
                    cursor = prev_start

                cursor = pe
                while cursor in by_start:
                    next_end, next_bullet = by_start[cursor]
                    if not next_bullet or next_bullet.get("listId") != list_id:
                        break
                    nkey = (cursor, next_end)
                    if nkey not in expanded:
                        expanded[nkey] = {
                            "start": cursor,
                            "end": next_end,
                            "nesting_level": next_bullet.get("nestingLevel", 0),
                            "preset": preset,
                        }
                    cursor = next_end

            units = sorted(expanded.values(), key=lambda u: u["start"])

            # Group touching, same-preset paragraphs into runs — each run
            # gets exactly one createParagraphBullets call, since the API
            # infers nesting level relative to siblings within that one call.
            runs: list[list[dict]] = [[units[0]]]
            for u in units[1:]:
                last = runs[-1][-1]
                if u["start"] == last["end"] and u["preset"] == last["preset"]:
                    runs[-1].append(u)
                else:
                    runs.append([u])

            requests: list[dict] = []
            # Runs applied in descending document-position order so one
            # run's tab insertions never invalidate a not-yet-processed
            # run's own indices — same convention as insert_doc_text.
            for run in sorted(runs, key=lambda run: run[0]["start"], reverse=True):
                run_start = run[0]["start"]
                run_end = run[-1]["end"]
                requests.append(
                    {
                        "deleteParagraphBullets": {
                            "range": {"startIndex": run_start, "endIndex": run_end}
                        }
                    }
                )
                for unit in sorted(run, key=lambda u: u["start"], reverse=True):
                    if unit["nesting_level"]:
                        requests.append(
                            {
                                "insertText": {
                                    "location": {"index": unit["start"]},
                                    "text": "\t" * unit["nesting_level"],
                                }
                            }
                        )
                total_tabs = sum(u["nesting_level"] for u in run)
                requests.append(
                    {
                        "createParagraphBullets": {
                            "range": {
                                "startIndex": run_start,
                                "endIndex": run_end + total_tabs,
                            },
                            "bulletPreset": run[0]["preset"],
                        }
                    }
                )

            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("create_paragraph_bullets: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Delete Paragraph Bullets", destructiveHint=True))
    async def delete_paragraph_bullets(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Remove list membership (bullets/numbering) from one or more paragraph
        ranges, leaving each paragraph's text and other styling untouched (#334).

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts, each with start_index and end_index
                (from get_doc_structure).

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}

        requests = [
            {
                "deleteParagraphBullets": {
                    "range": {"startIndex": r["start_index"], "endIndex": r["end_index"]}
                }
            }
            for r in ranges
        ]

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("delete_paragraph_bullets: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Get Document Theme"))
    async def get_doc_theme(
        doc_id: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Derive a theme dict from a Google Doc's actual paragraph styles.

        Scans the document body and reads the style of the first paragraph found for
        each named style type (NORMAL_TEXT, HEADING_1 through HEADING_6, TITLE, SUBTITLE).
        Text-level fields (font_family, font_size, bold, italic, color) come from the
        first non-empty text run in that paragraph; paragraph-level fields (line_spacing,
        space_above, space_below) come from the paragraph's paragraphStyle. Only named
        style types that appear in the body are included.

        Subsequent paragraphs of the same named style type that differ in style are
        ignored — they are treated as intentional individual overrides outside the theme.

        Use this tool when styles were applied directly to paragraphs (the common case).
        Use get_doc_named_styles instead when the human explicitly set named style defaults
        via Format > Paragraph styles > Update X to match in the Google Docs UI. Calling
        both and comparing results lets you detect whether explicit named styles are in use.

        The returned dict is suitable for passing directly to apply_theme.

        Args:
            doc_id: The Google Doc file ID.

        Returns:
            Theme dict keyed by named style type. Empty dict if no explicit paragraph
            styles are found (e.g. the doc uses purely inherited named style defaults).
        """
        lc = ctx.request_context.lifespan_context
        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        return _read_body_styles(doc)

    @tool(annotations=ToolAnnotations(title="Get Document Named Styles"))
    async def get_doc_named_styles(
        doc_id: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Read a Google Doc's named style defaults and return them as a theme dict.

        Named styles are set via Format > Paragraph styles > Update X to match in the
        Google Docs UI. They define the default appearance for each style type and are
        inherited by paragraphs that have no explicit overrides.

        Most docs leave named styles at Google's defaults even when paragraphs look
        custom — because humans usually format text directly without updating named styles.
        In that case this tool returns Google's defaults (Arial/Roboto etc.), which may
        not reflect the doc's actual appearance. Use get_doc_theme to read what the doc
        actually looks like based on applied paragraph styles.

        Calling both tools and comparing results is useful: if they agree, named styles
        are in sync with actual content; if they differ, styles were applied directly to
        paragraphs without updating named style definitions.

        Args:
            doc_id: The Google Doc file ID.

        Returns:
            Theme dict keyed by named style type. Only entries with at least one
            non-default field are included. Returns an empty dict if named styles
            are at Google's defaults.
        """
        lc = ctx.request_context.lifespan_context
        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        return _read_named_styles(doc)

    @tool(annotations=ToolAnnotations(title="Apply Document Theme", destructiveHint=True))
    async def apply_theme(
        doc_id: str,
        theme: dict,
        overwrite: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply a theme dict to a Google Doc by updating its named style definitions.

        By default (overwrite=False), theme entries are applied as document-level named
        style defaults via updateNamedStyle. Paragraphs that have explicit individual style
        overrides are unaffected — their styles take precedence over the named style
        defaults. This preserves intentional per-paragraph variations (e.g. a section
        deliberately styled in a different colour).

        For AI-generated docs where all content uses explicit paragraph/run styles, the
        default mode updates the named style definitions but does not visually change
        existing content. New paragraphs added without explicit styles will inherit the
        updated named style defaults.

        Set overwrite=True to also apply the theme directly to all existing paragraphs,
        overwriting their current styles including any individual overrides.

        Theme entry keys (NORMAL_TEXT, HEADING_1–6, TITLE, SUBTITLE). Each entry can
        include (all optional):
          font_family (str), font_size (float, points), bold (bool), italic (bool),
          color (dict {"red": 0-1, "green": 0-1, "blue": 0-1}),
          line_spacing (float, 100=single, 115=1.15×, 150=1.5×),
          space_above (float, points), space_below (float, points)

        An optional "table" key applies styling to every table currently in the document:
          border_color (dict), border_width (float, points),
          border_dash_style (str, default "SOLID"),
          border_top, border_right, border_bottom, border_left (dict): optional
              per-edge override, each {"color": {...}, "width": float, "dash_style": str}.
              Any field omitted from a per-edge dict falls back to the uniform
              border_color/border_width/border_dash_style above, if given (the Docs API
              rejects a border with non-zero width and no color as "transparent", so a
              width-only override needs a color from somewhere). An edge with no
              border_<side> key falls back entirely to the uniform border_color/
              border_width/border_dash_style, if given.
          cell_padding (float, points — all four sides),
          header_background (dict) — first row only

        Args:
            doc_id: The Google Doc file ID.
            theme: Theme dict. See above for schema.
            overwrite: If True, also apply styles directly to existing paragraphs,
                overwriting individual per-paragraph style overrides.

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
        """
        lc = ctx.request_context.lifespan_context

        named_style_keys = {k: v for k, v in theme.items() if k in _NAMED_STYLE_TYPES}
        table_style = theme.get("table")

        if not named_style_keys and not table_style:
            return {"error": "theme contains no recognised style keys"}

        requests = []

        # Always update named style definitions for each theme entry
        for style_type, entry in named_style_keys.items():
            requests.extend(_build_named_style_requests(style_type, entry))

        # Fetch the doc only when needed (overwrite mode or table styling)
        doc: dict | None = None
        if overwrite or table_style:
            try:
                doc = await execute_in_thread(
                    lc.docs_service.documents().get(documentId=doc_id).execute,
                    lc.docs_service,
                )
            except Exception as e:
                return {"error": f"failed to fetch doc: {e}"}

        # When overwrite=True, also apply styles directly to all existing paragraphs
        if overwrite and named_style_keys and doc:
            for elem in doc.get("body", {}).get("content", []):
                para = elem.get("paragraph")
                if not para:
                    continue
                style_type = para.get("paragraphStyle", {}).get("namedStyleType")
                if style_type not in named_style_keys:
                    continue
                entry = named_style_keys[style_type]
                rng = {"startIndex": elem["startIndex"], "endIndex": elem["endIndex"]}

                ps: dict = {}
                ps_fields: list[str] = []
                if "line_spacing" in entry:
                    ps["lineSpacing"] = entry["line_spacing"]
                    ps_fields.append("lineSpacing")
                if "space_above" in entry:
                    ps["spaceAbove"] = {"magnitude": entry["space_above"], "unit": "PT"}
                    ps_fields.append("spaceAbove")
                if "space_below" in entry:
                    ps["spaceBelow"] = {"magnitude": entry["space_below"], "unit": "PT"}
                    ps_fields.append("spaceBelow")
                if ps_fields:
                    requests.append(
                        {
                            "updateParagraphStyle": {
                                "range": rng,
                                "paragraphStyle": ps,
                                "fields": ",".join(ps_fields),
                            }
                        }
                    )

                ts: dict = {}
                ts_fields: list[str] = []
                if "font_family" in entry:
                    ts["weightedFontFamily"] = {"fontFamily": entry["font_family"]}
                    ts_fields.append("weightedFontFamily")
                if "font_size" in entry:
                    ts["fontSize"] = {"magnitude": entry["font_size"], "unit": "PT"}
                    ts_fields.append("fontSize")
                if "bold" in entry:
                    ts["bold"] = entry["bold"]
                    ts_fields.append("bold")
                if "italic" in entry:
                    ts["italic"] = entry["italic"]
                    ts_fields.append("italic")
                if "color" in entry:
                    ts["foregroundColor"] = {"color": {"rgbColor": entry["color"]}}
                    ts_fields.append("foregroundColor")
                if ts_fields:
                    requests.append(
                        {
                            "updateTextStyle": {
                                "range": rng,
                                "textStyle": ts,
                                "fields": ",".join(ts_fields),
                            }
                        }
                    )

        if table_style and doc:
            has_uniform_border = any(
                k in table_style for k in ("border_color", "border_width", "border_dash_style")
            )
            uniform_border: dict | None = None
            if has_uniform_border:
                uniform_border = {}
                if "border_color" in table_style:
                    uniform_border["color"] = {"color": {"rgbColor": table_style["border_color"]}}
                if "border_width" in table_style:
                    uniform_border["width"] = {
                        "magnitude": table_style["border_width"],
                        "unit": "PT",
                    }
                uniform_border["dashStyle"] = table_style.get("border_dash_style", "SOLID")

            edge_borders: dict[str, dict] = {}
            for side in ("top", "right", "bottom", "left"):
                edge_key = f"border_{side}"
                if edge_key in table_style:
                    edge_spec = table_style[edge_key]
                    if not isinstance(edge_spec, dict):
                        return {
                            "error": f"table['{edge_key}'] must be a dict with optional "
                            f"'color'/'width'/'dash_style' keys, got "
                            f"{type(edge_spec).__name__}"
                        }
                    edge_border: dict = {}
                    if "color" in edge_spec:
                        edge_border["color"] = {"color": {"rgbColor": edge_spec["color"]}}
                    elif uniform_border is not None and "color" in uniform_border:
                        # The Docs API rejects a border with a non-zero width and no
                        # color as "transparent" — a width-only override needs a color
                        # from somewhere.
                        edge_border["color"] = uniform_border["color"]
                    if "width" in edge_spec:
                        edge_border["width"] = {"magnitude": edge_spec["width"], "unit": "PT"}
                    elif uniform_border is not None and "width" in uniform_border:
                        edge_border["width"] = uniform_border["width"]
                    if "dash_style" in edge_spec:
                        edge_border["dashStyle"] = edge_spec["dash_style"]
                    elif uniform_border is not None:
                        edge_border["dashStyle"] = uniform_border["dashStyle"]
                    else:
                        edge_border["dashStyle"] = "SOLID"
                    edge_borders[side] = edge_border

            has_borders = has_uniform_border or bool(edge_borders)

            for elem in doc.get("body", {}).get("content", []):
                if "table" not in elem:
                    continue
                table_start = elem.get("startIndex")
                if table_start is None:
                    continue
                doc_table = elem["table"]
                num_rows = doc_table.get("rows", 0)
                num_cols = doc_table.get("columns", 0)
                if num_rows == 0 or num_cols == 0:
                    continue

                for r in range(num_rows):
                    cell_style: dict = {}
                    style_fields: list[str] = []

                    if r == 0 and "header_background" in table_style:
                        cell_style["backgroundColor"] = {
                            "color": {"rgbColor": table_style["header_background"]}
                        }
                        style_fields.append("backgroundColor")

                    if "cell_padding" in table_style:
                        pad = table_style["cell_padding"]
                        for side in ("Top", "Right", "Bottom", "Left"):
                            cell_style[f"padding{side}"] = {"magnitude": pad, "unit": "PT"}
                            style_fields.append(f"padding{side}")

                    if has_borders:
                        for side in ("Top", "Right", "Bottom", "Left"):
                            resolved_border = edge_borders.get(side.lower(), uniform_border)
                            if resolved_border is None:
                                continue
                            cell_style[f"border{side}"] = resolved_border
                            style_fields.append(f"border{side}")

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
                                        "columnIndex": 0,
                                    },
                                    "rowSpan": 1,
                                    "columnSpan": num_cols,
                                },
                            }
                        }
                    )

        if not requests:
            return {"error": "no style requests could be built from the given theme"}

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("apply_theme: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}
