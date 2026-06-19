# Design: Docs AST Pipeline (Phase 2)

**Date:** 2026-06-17 (updated 2026-06-18)  
**Issue:** [#87](https://github.com/khuisman/mcp-gee-sweet/issues/87)  
**Status:** complete (Phase 2 implemented; AST schema is final)

> Point-in-time implementation design — captures the data model, file layout, algorithm choices, and scope decisions as they were made. See [decision-docs-formatting.md](../decisions/decision-docs-formatting.md) for the architectural "why".

---

## Problem

`docs.py` has a monolithic `_DocParser` (HTMLParser subclass) that simultaneously parses HTML and emits Docs API requests. It has several known bugs:

- **#41** — `<h2>`–`<h6>` all collapse to `HEADING_3`
- **#65** — `<th>` cells not bolded
- **#66** — `width` on `<col>`/`<td>` ignored; no `updateTableColumnProperties` emitted
- **#67** — `colspan`/`rowspan` ignored; no `mergeTableCells` emitted
- **#69** — inline formatting (`<b>`, `<i>`, `<u>`, `<s>`, `<a>`) inside table cells is lost

Adding fixes piecemeal would make the parser more complex. This design replaces it with a three-stage pipeline: HTML → AST → Docs API requests.

---

## File Layout

```
src/mcp_gee_sweet/tools/docs.py        ← deleted
src/mcp_gee_sweet/tools/docs/
    __init__.py     — register(), _html_to_doc_requests wrapper, _html_to_text (preserves test imports)
    ast.py          — comprehensive AST dataclasses
    html_parser.py  — html_to_ast(html: str) -> list[DocNode]
    emitter.py      — ast_to_requests(nodes, start_index) -> (requests, list[Table])
                      fill_tables(docs_service, doc_id, tables: list[Table]) -> None
```

`tools/__init__.py` does `from . import docs; docs.register(tool)` — unchanged; the package satisfies it.  
Test file imports `from mcp_gee_sweet.tools.docs import _html_to_doc_requests, _html_to_text` — satisfied by `__init__.py`.

---

## AST Node Design

The AST is designed as the **final product** — the complete schema covers all Docs API content-formatting operations. Phase 3 styling fields are present as `None` defaults; the emitter ignores them until Phase 3 adds a `theme_applier.py`. This mirrors the ChartSpec decision (PR #84): design fully now, implement incrementally.

```python
@dataclass
class RGBColor:
    red: float
    green: float
    blue: float

@dataclass
class ParagraphStyle:
    alignment: str | None = None            # LEFT, CENTER, RIGHT, JUSTIFIED
    indent_start: float | None = None       # pt
    indent_end: float | None = None         # pt
    indent_first_line: float | None = None  # pt
    space_above: float | None = None        # pt
    space_below: float | None = None        # pt
    line_spacing: float | None = None       # 100=single, 150=1.5×, 200=double
    page_break_before: bool | None = None
    keep_lines_together: bool | None = None
    keep_with_next: bool | None = None

@dataclass
class Run:
    text: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strikethrough: bool | None = None
    link_url: str | None = None
    font_size: float | None = None                # Phase 3 only
    foreground_color: RGBColor | None = None      # Phase 3 only
    font_family: str | None = None                # Phase 3 only
    background_color: RGBColor | None = None      # Phase 3 only; text highlight
    baseline_offset: str | None = None            # Phase 3 only; SUPERSCRIPT, SUBSCRIPT
    small_caps: bool | None = None                # Phase 3 only

@dataclass
class Cell:
    runs: list[Run]
    colspan: int = 1
    rowspan: int = 1                              # AST only; emitter deferred (see below)
    is_header: bool = False                       # <th> → runs get bold=True
    content_alignment: str | None = None          # TOP, MIDDLE, BOTTOM
    background_color: RGBColor | None = None      # Phase 3 only
    padding_top: float | None = None              # Phase 3 only
    padding_right: float | None = None            # Phase 3 only
    padding_bottom: float | None = None           # Phase 3 only
    padding_left: float | None = None             # Phase 3 only
    border_color: RGBColor | None = None          # Phase 3 only
    border_width: float | None = None             # Phase 3 only
    border_dash_style: str | None = None          # Phase 3 only

@dataclass
class Row:
    cells: list[Cell]
    minimum_height: float | None = None           # pt
    is_header_row: bool = False

@dataclass
class Table:
    rows: list[Row]
    col_widths: list[float | None] = field(default_factory=list)  # Phase 2
    table_alignment: str | None = None            # ALIGNED_START, CENTER, ALIGNED_END

@dataclass
class Heading:
    level: int  # 1–6, maps directly to HEADING_1…HEADING_6
    runs: list[Run]
    paragraph_style: ParagraphStyle | None = None

@dataclass
class Paragraph:
    runs: list[Run]
    paragraph_style: ParagraphStyle | None = None

@dataclass
class BulletItem:
    runs: list[Run]
    depth: int = 0
    ordered: bool = False
    paragraph_style: ParagraphStyle | None = None

@dataclass
class NamedBlock:
    style_type: str  # TITLE, SUBTITLE, NORMAL_TEXT
    runs: list[Run]
    paragraph_style: ParagraphStyle | None = None

DocNode = Union[Heading, Paragraph, BulletItem, Table, NamedBlock]
```

**Out of scope for the AST:** images, page headers/footers, footnotes, charts (separate ChartSpec path), named ranges, table of contents.

**`NamedBlock`:** covers TITLE and SUBTITLE named styles not expressible as `Heading(level=1–6)`. `html_parser.py` does not emit `NamedBlock` yet; it will be added when the HTML subset is extended (e.g. a `data-style="title"` attribute convention, or a dedicated `<title>` wrapper element).

**`ParagraphStyle`:** shared across `Heading`, `Paragraph`, `BulletItem`, and `NamedBlock`. The html_parser ignores it for now (HTML has no structural equivalent for most of these properties). Phase 3 theme application will set these fields via the `theme_applier.py`.

---

## html_parser.py

`html_to_ast(html: str) -> list[DocNode]`

Standard-library `HTMLParser` subclass. Tracks tag context and emits AST nodes on end-tags.

### Block elements → AST nodes

| HTML | AST node | Notes |
|------|----------|-------|
| `<h1>`–`<h6>` | `Heading(level=1–6, runs=...)` | Fixes #41 |
| `<p>` | `Paragraph(runs=...)` | |
| `<li>` | `BulletItem(runs=..., ordered=...)` | `ordered` from enclosing `<ol>`/`<ul>` |
| `<table>` | `Table(rows=..., col_widths=...)` | |
| `<th>` | `Cell(is_header=True, runs=[Run(text, bold=True)])` | Fixes #65 |
| `<td colspan="N">` | `Cell(colspan=N, runs=...)` | Fixes #67 (colspan; rowspan deferred) |

### Inline elements → Run fields

Tracked as a stack of active formatters. Each active formatter contributes a field to the next Run emitted.

| HTML | Run field |
|------|-----------|
| `<b>`, `<strong>` | `bold=True` |
| `<i>`, `<em>` | `italic=True` |
| `<u>` | `underline=True` |
| `<s>` | `strikethrough=True` |
| `<a href="url">` | `link_url=url` |

Inline elements work inside `<td>`, `<th>`, `<p>`, `<li>`, and headings — fixing #69 for table cells.

### Column widths

`<col width="N">` or `<td width="N">` → `Table.col_widths[i]`

- Numeric value assumed to be pixels; converted: `pt = px * 72 / 96`
- Percentage widths skipped (can't resolve without page width)

Fixes #66.

### Deferred

- **Rowspan** — `rowspan` attr captured into `Cell.rowspan` but emitter does not yet emit `mergeTableCells` for row merges; the phantom-cell mapping after merge is complex. Follow-on ticket.
- **Nested tables** — `<table>` inside `<td>` is out of scope (#68). Recursive AST node exists; multi-pass insert deferred.

---

## emitter.py

### ast_to_requests(nodes, start_index=1) → (requests, tables)

Returns `(phase1_requests, list[Table])` where `tables` are the Table AST nodes (no longer `list[list[list[str]]]`).

**Phase 1 requests built:**

1. One `insertText` for all non-table text (concatenated with `\n` separators)
2. For each heading: `updateParagraphStyle(HEADING_{level})` + `deleteParagraphBullets`
3. For each paragraph: `deleteParagraphBullets`
4. For each bullet: `createParagraphBullets` (preset varies by `ordered`)
5. For each `link_url` run in non-table content: `updateTextStyle(link=...)`
6. `insertTable` requests in **reverse** order (last-to-first preserves earlier positions)

### fill_tables(docs_service, doc_id, tables) → None

Replaces the old `_fill_tables` / `_fill_table_cell_requests_from_doc`.

```
1. Re-fetch doc → get live table structure
2. If any cell has colspan > 1:
   a. Emit mergeTableCells batch for all such cells (across all tables)
   b. Re-fetch doc → get post-merge cell positions
3. For all cells across all tables, sorted HIGH→LOW by paragraphStartIndex:
   a. insertText with joined run text
   b. For each run with a styling field (bold/italic/etc.):
      updateTextStyle at [para_start + offset, para_start + offset + len(run.text)]
4. If any table has col_widths:
   Emit updateTableColumnProperties per column with a non-None width
```

**Index arithmetic for styled runs:**

```
offset = 0
for run in cell.runs:
    run_start = paragraphStartIndex + offset
    run_end   = run_start + len(run.text)
    if run has any style field:
        emit updateTextStyle([run_start, run_end], ...)
    offset += len(run.text)
```

All fill requests sorted high→low by `insertText` location index to prevent shifting.

---

## Test Changes (tests/test_docs.py)

| Existing test | Change |
|---|---|
| `test_h2_produces_heading_3` | Rename → `test_h2_produces_heading_2`, assert `HEADING_2` |
| `test_table_data_returned_in_tables` | Update: `tables[0]` is now a `Table` AST node |

New tests to add:

| Test | Assertion |
|---|---|
| `test_h3_to_h6_produce_correct_levels` | Each maps to its own `HEADING_N` |
| `test_th_cell_has_bold_run` | `<th>X</th>` → `tables[0].rows[0].cells[0].runs[0].bold == True` |
| `test_inline_bold_in_td` | `<td><b>foo</b></td>` → cell run with `bold=True` |
| `test_inline_link_in_td` | `<td><a href="url">x</a></td>` → cell run with `link_url=url` |
| `test_colspan_in_table` | `<td colspan="2">` → `Cell.colspan == 2` |
| `test_col_width_parsed` | `<col width="72">` → `Table.col_widths[0] ≈ 54.0` (72px → 54pt) |

---

## Scope Boundaries

| Feature | In Phase 2? | Notes |
|---|---|---|
| Correct heading levels h1–h6 | Yes | #41 |
| `<th>` bold | Yes | #65 |
| Inline formatting in cells | Yes | #69 |
| Column widths | Yes | #66 |
| Colspan | Yes | #67 partial |
| Rowspan | No | `Cell.rowspan` in AST; emitter deferred |
| Nested tables | No | #68 deferred |
| Phase 3 styling fields (colors, fonts) | No | In AST as `None`; emitter ignores them |
| `<ol>` ordered bullets | Yes | `BulletItem.ordered` → different bullet preset |
