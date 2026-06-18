# Decision: Google Docs Formatting Architecture

**Date:** 2026-06-17
**Status:** decided

> This is a point-in-time record. It captures context, alternatives, and reasoning as they were understood on the date above — not the current state of the project.

## Background

Active use of the MCP for real Google Docs work surfaced two complementary gaps:

1. **Precision editing** — no way to insert, delete, or style content at a specific document index in an existing doc. `write_doc_content` replaces the entire body; any targeted edit requires bypassing the MCP and calling the Docs API directly with raw batchUpdate JSON.

2. **Translation layer quality** — the HTML→Docs translator in `write_doc_content` and `create_doc` is ad-hoc: it silently drops unsupported tags, maps `<h2>`–`<h6>` all to HEADING_3, loses inline formatting (bold, italic, links) inside table cells, ignores `colspan`/`rowspan`, and drops nested tables. No explicit contract defines what is and isn't supported.

This prompted a design conversation about the right architecture: should the input format be HTML, Markdown, YAML, or something else? Should the MCP mediate through an abstraction or expose raw API operations? The issues raised were #41, #65–#70, #79–#82.

## Design Questions Considered

### 1. Direct API access vs. abstraction layer

These are not mutually exclusive. Raw API tools (operating on document indices) and a content-creation abstraction (operating on a human-readable input format) serve different use cases. The question is not which to build but where to draw the boundary.

**Decision:** build both. Direct API tools for precision editing of existing docs; abstraction layer for bulk content creation.

### 2. What input format for the abstraction layer?

**HTML/CSS:** AI tools already produce HTML fluently. Design-focused AI modes work natively in HTML/CSS. A CSS theme system (separate from content) would allow look-and-feel to be designed independently and applied at write time — mirroring how Google Docs itself separates named styles from content. Risk: HTML/CSS is vastly more expressive than what Docs supports; there is more surface area for misinterpreted or silently dropped constructs.

**YAML / terse structured format:** Only expresses what Docs actually supports. Less interpretation ambiguity. AI tools are less fluent in custom schemas; format is not transferable.

**Markdown:** AI tools are very fluent in Markdown. Simpler to parse than HTML. Would require a new parser but maps well to the Docs constructs we need (headings, paragraphs, bullets, links, tables).

**Multiple formats:** The right long-term architecture. If the translator pipeline has a clean intermediate representation (an AST), each input format is just a parser that compiles to that AST. Adding a new format later is "write another parser," not "rewrite the engine."

**Decision:** HTML as the primary input format, with a formal supported-subset contract. Markdown and YAML deferred — the AST layer (see below) makes them straightforward to add later. The SQL→protobuf analogy applies: the Docs API batchUpdate format is the "bytecode"; input formats are higher-level languages that compile to it.

### 3. How to formalize the translation contract?

The current parser is a single HTMLParser subclass that simultaneously parses HTML and emits Docs API requests. When a new construct is needed, it gets bolted on. The result is an implicit, untested contract.

**Decision:** Introduce a Document AST as the canonical intermediate between any input format and the Docs API. The AST explicitly defines what constructs the system supports. Unsupported constructs are documented gaps, not silent drops.

### 4. Style / look-and-feel

Separating content (what structure and text exists) from style (how it looks) mirrors how Google Docs itself works. A named theme config — font, heading sizes/colors, table borders and padding, header cell background — applied at write time enables a user to define their standard look once and apply it everywhere. A design AI can author or tweak the theme independently from the content.

**Decision:** CSS-like theme system is the right architecture. Deferred to Phase 3 — not blocking Phases 1 or 2.

## Architecture

### Two complementary layers

```
Input format (HTML)
       │
       ▼
  HTML parser  ──▶  Document AST  ──▶  Docs API requests (batchUpdate)
                          │
                    Theme config (Phase 3)
                    
Direct API tools (#79–#82):
  get_doc_structure / insert_doc_text / delete_doc_range /
  style_doc_range / insert_doc_table / style_doc_table_cells
```

### Document AST node types

| Node | Fields |
|------|--------|
| `Heading` | `level: 1–6`, `runs: list[Run]` |
| `Paragraph` | `runs: list[Run]` |
| `BulletItem` | `runs: list[Run]`, `depth: int` |
| `Table` | `rows: list[Row]`, `col_widths: list[float \| None]` |
| `Row` | `cells: list[Cell]` |
| `Cell` | `runs: list[Run]`, `colspan: int`, `rowspan: int`, `is_header: bool` |
| `Run` | `text: str`, `bold`, `italic`, `underline`, `strikethrough`, `link_url` |

### Supported HTML subset (the contract)

| Category | Elements |
|----------|----------|
| Block | `<h1>`–`<h6>`, `<p>`, `<ul>`/`<ol>`/`<li>`, `<table>`/`<thead>`/`<tbody>`/`<tr>`/`<th>`/`<td>` |
| Inline | `<a href>`, `<b>`/`<strong>`, `<i>`/`<em>`, `<u>`, `<s>` |
| Table attributes | `colspan`, `rowspan`, `width` |
| Everything else | Ignored (not an error) |

## Implementation Phases

### Phase 1: Direct API tools

New tools in `tools/docs.py` (or `tools/docs/`) wrapping Docs API batchUpdate operations at the index level. Independent of the input format question.

- `get_doc_structure` — full structural map with startIndex/endIndex per element (**prerequisite for all others**)
- `insert_doc_text` — `insertText` at a document index
- `delete_doc_range` — `deleteContentRange` for a start/end span
- `style_doc_range` — `updateParagraphStyle` / `updateTextStyle` for a list of index ranges
- `insert_doc_table` — `insertTable` at a document index; returns table startIndex
- `style_doc_table_cells` — `updateTableCellStyle` for borders, padding, background

Research question (from #70): can the cell indices of a freshly-inserted empty table be computed without re-fetching the document? This informs whether `insert_doc_table` can return useful cell indices immediately or whether callers always need a follow-up `get_doc_structure`.

**Issues addressed:** #79, #80, #81, #82 (implemented); #70 (researched and documented)

### Phase 2: Document AST + translator rewrite

Three-stage pipeline replacing the current monolithic HTMLParser:

- `tools/docs/ast.py` — AST dataclasses
- `tools/docs/html_parser.py` — HTML string → AST
- `tools/docs/emitter.py` — AST → Docs API batchUpdate requests

The two-phase table approach (insert empty table, re-fetch, fill cells) is preserved in the emitter unless Phase 1 research (#70) proves deterministic cell indexing is reliable.

**Issues resolved:** #41, #65, #66, #67, #68, #69, #70 (confirmed or refuted)

### Phase 3: CSS theme system (deferred)

Named style themes (font, heading styles, table defaults) stored as configs, applied at AST emit time. New tools: `get_doc_theme` (parse existing doc → theme), `list_themes`, `apply_theme`.

## Issue Disposition

| Issue | Title | Phase | Notes |
|-------|-------|-------|-------|
| #79 | `get_doc_structure` | 1 | Implement |
| #80 | `insertText` / `deleteContentRange` | 1 | Implement |
| #81 | `style_doc_range` | 1 | Implement |
| #82 | `insertTable` / `style_doc_table_cells` | 1 | Implement |
| #70 | Table cell index research | 1→2 | Research in Phase 1; resolved in Phase 2 emitter |
| #41 | H2 renders as H3 | 2 | Fix in new translator |
| #65 | Bold `<th>` cells | 2 | Fix in new translator |
| #66 | Column width from HTML | 2 | Fix in new translator |
| #67 | `colspan`/`rowspan` | 2 | Fix in new translator |
| #68 | Nested tables | 2 | Fix in new translator |
| #69 | Inline formatting in table cells | 2 | Fix in new translator |
