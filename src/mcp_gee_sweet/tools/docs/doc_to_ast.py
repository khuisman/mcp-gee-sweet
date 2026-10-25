"""Docs API `documents().get()` response -> this project's own AST (docs/ast.py).

The read-side inverse of emitter.py's AST -> Docs API requests: walks the live
document structure into the same node types the write pipeline (html_parser.py
-> emitter.py) already produces, so markdown_export.py's AST -> Markdown pass
can reuse exactly the mapping markdown-support.md documents for the write
direction, just run backwards.

Only the document's default tab is read (matches get_doc_structure's existing
scope) — multi-tab documents (includeTabsContent) are out of scope here too.
"""

from __future__ import annotations

from .ast import (
    BulletItem,
    Cell,
    DocNode,
    Heading,
    Image,
    NamedBlock,
    Paragraph,
    RGBColor,
    Row,
    Run,
    Table,
)
from .emitter import _BLOCKQUOTE_INDENT_PT_PER_LEVEL, list_level_indents

_HEADING_LEVELS = {f"HEADING_{i}": i for i in range(1, 7)}

# Checkbox glyphs the emitter prepends to a checked/unchecked task item's text
# (#336's design decision — a literal glyph prefix, not a BULLET_CHECKBOX
# preset list; see emitter.py's own comment). Recognized here on read-back the
# same way the write side writes them, character-for-character.
_CHECKED_PREFIX = "☑ "  # "☑ "
_UNCHECKED_PREFIX = "☐ "  # "☐ "


def document_to_ast(document: dict) -> list[DocNode]:
    """Walk a `documents().get()` response body into a list of DocNode."""
    nodes: list[DocNode] = []
    list_counts: dict[str, list[int]] = {}
    for elem in document.get("body", {}).get("content", []):
        if "paragraph" in elem:
            node = _paragraph_to_node(elem["paragraph"], document)
            if isinstance(node, BulletItem):
                _number_list_item(node, elem["paragraph"]["bullet"], document, list_counts)
            if node is not None:
                nodes.append(node)
        elif "table" in elem:
            nodes.append(_table_elem_to_ast(elem["table"], document))
        # sectionBreak, tableOfContents: no Markdown equivalent, silently skipped
        # — same "unsupported construct" convention html_parser.py uses on write.
    return nodes


def _number_list_item(
    node: BulletItem, bullet: dict, document: dict, list_counts: dict[str, list[int]]
) -> None:
    """Set an ordered item's `number` to its ordinal in its Docs list (#1208).

    Docs numbers a list by listId, so a table, quote, code block or paragraph
    between two items doesn't restart it, and ast_to_markdown's old "1." on
    every item read the continuation as a new list. Counts are per listId and
    nesting level, and an item clears the counts of every level deeper than
    its own, since Docs restarts a sublist under each new parent item. A
    level's `startNumber` offsets its count; Docs treats 0 as 1."""
    counts = list_counts.setdefault(bullet.get("listId", ""), [])
    level = node.depth
    del counts[level + 1 :]
    counts.extend([0] * (level + 1 - len(counts)))
    counts[level] += 1
    if node.ordered:
        start = (_nesting_level(bullet, document) or {}).get("startNumber") or 1
        node.number = start + counts[level] - 1


def _paragraph_to_node(para: dict, document: dict) -> DocNode | None:
    pstyle = para.get("paragraphStyle", {})
    named_style = pstyle.get("namedStyleType", "NORMAL_TEXT")
    runs = _paragraph_runs(para, document)
    bullet = para.get("bullet")
    blockquote_depth = _infer_blockquote_depth(
        pstyle, _list_level_indent_start(bullet, document) if bullet else 0
    )

    if bullet:
        checked = None
        if runs and isinstance(runs[0], Run):
            if runs[0].text.startswith(_CHECKED_PREFIX):
                checked = True
                runs[0].text = runs[0].text[len(_CHECKED_PREFIX) :]
            elif runs[0].text.startswith(_UNCHECKED_PREFIX):
                checked = False
                runs[0].text = runs[0].text[len(_UNCHECKED_PREFIX) :]
        return BulletItem(
            runs=runs,
            depth=bullet.get("nestingLevel", 0),
            ordered=_bullet_is_ordered(bullet, document),
            checked=checked,
            blockquote_depth=blockquote_depth,
        )

    if named_style in _HEADING_LEVELS:
        return Heading(
            level=_HEADING_LEVELS[named_style], runs=runs, blockquote_depth=blockquote_depth
        )
    if named_style in ("TITLE", "SUBTITLE"):
        return NamedBlock(style_type=named_style, runs=runs, blockquote_depth=blockquote_depth)
    return Paragraph(runs=runs, blockquote_depth=blockquote_depth)


def _nesting_level(bullet: dict, document: dict) -> dict | None:
    """The doc's `lists` entry for this list item's own nesting level, or None if
    the doc doesn't define it."""
    levels = (
        document.get("lists", {})
        .get(bullet.get("listId"), {})
        .get("listProperties", {})
        .get("nestingLevels", [])
    )
    level = bullet.get("nestingLevel", 0)
    return levels[level] if level < len(levels) else None


def _bullet_is_ordered(bullet: dict, document: dict) -> bool:
    """Mirrors style.py's create_paragraph_bullets `infer_preset` — a list's
    nesting-level glyph info is the only signal for ordered vs. unordered,
    since `bullet` itself carries no preset field of its own."""
    level = _nesting_level(bullet, document)
    return level is not None and "glyphType" in level


def _list_level_indent_start(bullet: dict, document: dict) -> float:
    """indentStart, in points, that a list item's own list level gives it, before any
    blockquote indent emitter.py adds on top (#1056). Read from the doc's `lists`
    map, falling back to the presets emitter.py writes."""
    level = _nesting_level(bullet, document)
    if level is not None and "indentStart" in level:
        return level["indentStart"].get("magnitude", 0)
    return list_level_indents(bullet.get("nestingLevel", 0))[1]


def _infer_blockquote_depth(pstyle: dict, base_indent: float = 0) -> int:
    """Best-effort inverse of emitter.py's _blockquote_style_request: a
    paragraph carrying both our own borderLeft styling and a nonzero
    indentStart is treated as a blockquote at the depth that indent implies.
    indentStart alone (no borderLeft) is not enough — plenty of ordinary
    paragraphs use indentation for reasons unrelated to a quote.

    base_indent is the indentStart the paragraph would have without the quote:
    a list item's own level indent, 0 otherwise. A bordered list item at or
    below it (written before #1056, when the bullets call overwrote the quote
    indent) still reads as depth 1."""
    if not pstyle.get("borderLeft"):
        return 0
    indent = pstyle.get("indentStart", {}).get("magnitude", 0)
    if indent <= 0:
        return 0
    return max(1, round((indent - base_indent) / _BLOCKQUOTE_INDENT_PT_PER_LEVEL))


def _paragraph_runs(para: dict, document: dict) -> list[Run | Image]:
    items: list[Run | Image] = []
    for pe in para.get("elements", []):
        if "textRun" in pe:
            tr = pe["textRun"]
            content = tr.get("content", "")
            if content == "":
                continue
            ts = tr.get("textStyle", {})
            items.append(_text_run_to_run(content, ts, _link_url(ts, document)))
        elif "inlineObjectElement" in pe:
            ioe = pe["inlineObjectElement"]
            # A linked image carries the link on its element's own textStyle,
            # the same as a text run (#951, confirmed live).
            link_url = _link_url(ioe.get("textStyle", {}), document)
            image = _resolve_inline_image(ioe.get("inlineObjectId"), document, link_url)
            if image is not None:
                items.append(image)
        # footnoteReference, horizontalRule, pageBreak, columnBreak, autoText,
        # richLink, person, equation: no Markdown equivalent, silently skipped.

    # Every paragraph's content ends with a trailing "\n" (Docs API convention)
    # — strip exactly one from the end of the last Run, dropping it entirely if
    # that empties it (mirrors html_parser.py's own <pre>-close trailing-\n strip).
    if items and isinstance(items[-1], Run) and items[-1].text.endswith("\n"):
        items[-1].text = items[-1].text[:-1]
        if items[-1].text == "":
            items.pop()
    return items


def _link_url(ts: dict, document: dict) -> str | None:
    """The URL for a textStyle's link, or None when there is no link.

    Docs reports a link to a heading or bookmark in this document by ID, with
    no `url` (confirmed live for a heading: `{"headingId": "h.x"}`, #951). It's
    rebuilt as the same-document URL the Docs UI uses, the form
    get_doc_structure's docstring documents for heading links. The newer
    `heading`/`bookmark` objects carry a `tabId`; the deprecated flat fields
    don't, so they fall back to the first tab, the only one this walker reads."""
    link = ts.get("link")
    if not link:
        return None
    if link.get("url"):
        return link["url"]
    doc_id = document.get("documentId")
    if not doc_id:
        return None
    for kind in ("heading", "bookmark"):
        target = link.get(kind) or {}
        target_id = target.get("id") or link.get(f"{kind}Id")
        if target_id:
            tab = target.get("tabId") or link.get("tabId") or "t.0"
            return f"https://docs.google.com/document/d/{doc_id}/edit?tab={tab}#{kind}={target_id}"
    return None


def _text_run_to_run(text: str, ts: dict, link_url: str | None = None) -> Run:
    fg = ts.get("foregroundColor", {}).get("color", {}).get("rgbColor")
    bg = ts.get("backgroundColor", {}).get("color", {}).get("rgbColor")
    baseline = ts.get("baselineOffset")
    # A soft break ("\v") is a line break inside the paragraph, whatever
    # wrote it: emitter.py's code-block line breaks (#719) or
    # insert_softbreak_paragraph in prose (#1057). The AST spells a line break
    # inside a run "\n", the same as html_parser.py's <br>.
    text = text.replace("\v", "\n")
    return Run(
        text=text,
        bold=ts.get("bold"),
        italic=ts.get("italic"),
        underline=ts.get("underline"),
        strikethrough=ts.get("strikethrough"),
        link_url=link_url,
        font_size=ts.get("fontSize", {}).get("magnitude"),
        foreground_color=_rgb_color(fg),
        font_family=ts.get("weightedFontFamily", {}).get("fontFamily"),
        background_color=_rgb_color(bg),
        baseline_offset=baseline if baseline not in (None, "NONE") else None,
        small_caps=ts.get("smallCaps"),
    )


def _rgb_color(rgb: dict | None) -> RGBColor | None:
    if not rgb:
        return None
    return RGBColor(red=rgb.get("red", 0.0), green=rgb.get("green", 0.0), blue=rgb.get("blue", 0.0))


def _resolve_inline_image(
    object_id: str | None, document: dict, link_url: str | None = None
) -> Image | None:
    if not object_id:
        return None
    obj = document.get("inlineObjects", {}).get(object_id)
    if not obj:
        return None
    embedded = obj.get("inlineObjectProperties", {}).get("embeddedObject", {})
    uri = embedded.get("imageProperties", {}).get("contentUri")
    if not uri:
        return None
    size = embedded.get("size", {})
    return Image(
        src=uri,
        alt=embedded.get("title") or embedded.get("description") or None,
        width=size.get("width", {}).get("magnitude"),
        height=size.get("height", {}).get("magnitude"),
        link_url=link_url,
    )


def _table_elem_to_ast(table: dict, document: dict) -> Table:
    """A merged cell (colspan/rowspan > 1) does NOT remove the physical
    tableCells[] entries it covers — Google's Docs API leaves an empty,
    ordinary-looking (columnSpan=1, rowSpan=1) phantom cell at every absorbed
    position, both for a colspan's own row and for every later row a rowspan
    reaches into (confirmed live: a colspan=2 cell's row has 2 physical
    entries, not 1; a rowspan=2 cell's second row has a leading empty phantom
    entry before the row's real content). There's no field marking a cell as
    "this is a phantom" — the only way to tell is to track, while walking
    cells left-to-right/top-to-bottom, which (row, col) positions an earlier
    real cell's own colspan/rowspan already claims, exactly mirroring
    emitter.py's write-side phantom-set logic (`_build_phantom_set`) but
    computed forward from the live doc instead of backward from a known AST.
    Originally missed entirely (#591 QA round 1) — treating every physical
    cell as real corrupted colspan tables with extra blank columns and
    silently dropped a rowspan'd row's own trailing real cells.
    """
    doc_rows = table.get("tableRows", [])
    covered: set[tuple[int, int]] = set()
    rows: list[Row] = []
    for r, doc_row in enumerate(doc_rows):
        physical_cells = sorted(doc_row.get("tableCells", []), key=lambda c: c.get("startIndex", 0))
        cells: list[Cell] = []
        col = 0
        for doc_cell in physical_cells:
            if (r, col) in covered:
                # Phantom entry (this row's own colspan carry-over, or a
                # rowspan reaching down from an earlier row) — consumed, not
                # added to the AST.
                col += 1
                continue
            style = doc_cell.get("tableCellStyle", {})
            colspan = style.get("columnSpan", 1)
            rowspan = style.get("rowSpan", 1)
            cells.append(
                Cell(
                    children=_cell_content_to_children(doc_cell.get("content", []), document),
                    colspan=colspan,
                    rowspan=rowspan,
                )
            )
            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr == 0 and dc == 0:
                        continue
                    covered.add((r + dr, col + dc))
            col += 1
        rows.append(Row(cells=cells))

    col_widths = [
        cp.get("width", {}).get("magnitude")
        for cp in table.get("tableStyle", {}).get("tableColumnProperties", [])
    ]
    return Table(rows=rows, col_widths=col_widths)


def _cell_content_to_children(content: list[dict], document: dict) -> list[Run | Image | Table]:
    """Flatten a table cell's content into the flat Run|Image|Table children
    list our AST expects (Cell.children has no per-paragraph structure — see
    ast.py). Multiple paragraphs within one cell are joined with a "\\n",
    matching the only way html_parser.py's write side ever gets a line break
    inside a cell (an explicit <br>).

    A paragraph with no runs at all (a deliberate blank-line spacer — the
    same shape `test_paragraph_that_is_only_a_newline_becomes_empty_runs`
    covers at the top level) used to be `continue`d past entirely, silently
    merging it into whichever paragraphs sit on either side (#594) — unlike
    html_parser.py's write-side handling of whitespace-only paragraphs. Fixed
    by treating an empty-runs paragraph the same as any other for the
    seen_content/joiner bookkeeping below: it contributes no text of its own,
    but still counts as content once seen, so the next real paragraph gets
    its own separate "\\n" joiner on top of the blank paragraph's — two
    newlines between two lines of real text, preserving the spacer instead of
    collapsing it away."""
    children: list[Run | Image | Table] = []
    seen_content = False
    for elem in content:
        if "paragraph" in elem:
            runs = _paragraph_runs(elem["paragraph"], document)
            if seen_content:
                if runs and isinstance(runs[0], Run):
                    runs[0].text = "\n" + runs[0].text
                else:
                    children.append(Run(text="\n"))
            children.extend(runs)
            seen_content = True
        elif "table" in elem:
            children.append(_table_elem_to_ast(elem["table"], document))
            seen_content = True
    return children
