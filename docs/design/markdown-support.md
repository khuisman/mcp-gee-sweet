# Design: Markdown Support for Google Docs Tools

**Status:** Shipped. `content_format='markdown'` on `create_doc`/`write_doc_content`, plus
`create_doc_from_file`, landed via #102/#103/#104 (PR #105); bare-URL autolinking (`autolink_urls`)
landed separately via #248 (PR #265). Live-verified: [2026-06-28 QA results](../qa/results/2026-06-28.md),
[2026-07-04 QA results](../qa/results/2026-07-04-docs.md).

**Parser superseded (#1116):** the Python-Markdown call below was replaced with markdown-it-py
(CommonMark plus GFM) in `docs/md_to_html.py`; see
[`markdown-parser.md`](markdown-parser.md). The MD → HTML → AST shape this doc argues for is
unchanged.

## Problem

`create_doc` and `write_doc_content` only accept HTML. Users who work primarily with `.md` files
have to convert manually before calling these tools. The project already has the `markdown`
library as a dependency (used in `transfer.py`) and a clean HTML → AST → Docs API pipeline, but
markdown content never flows through that pipeline.

## Solution

Add a `markdown → HTML` shim at the docs layer, then expose it in two ways:
1. A `content_format` parameter on `create_doc` and `write_doc_content`
2. A new `create_doc_from_file` tool for uploading local `.md` / `.html` files

This intentionally does **not** use Drive's native HTML importer (which `upload_file` did for a
Markdown source with `convert_to_doc=True` until #1102 routed it through this pipeline too). Routing through our AST pipeline gives consistent formatting
control and benefits from all the Phase 2 work (correct heading levels, colspan, header cells,
column widths, etc.).

## Why MD → HTML → AST (not a direct MD → AST parser)

Markdown is defined by its spec as shorthand for HTML — the spec describes every construct
in terms of its HTML output, not in terms of a semantic document model. So `markdown` the
library isn't doing a lossy conversion; it's doing exactly what the format specifies. Chaining
it into `html_to_ast` is two well-tested parsers each doing precisely what they were designed
for, not two approximations stacked on top of each other.

A direct MD → AST parser would duplicate all the logic already in `html_to_ast` (heading
detection, inline formatting stacks, list depth tracking, table parsing) — more code, more
edge cases, two things to maintain.

**The one real exception**: constructs that don't survive the HTML round-trip cleanly:

- **Code blocks** — `<pre><code>` carries no semantic signal that our HTML parser acted on until
  text styles landed, so they used to fall through to plain text.
- **Task list state** — `- [x] item` emits `<input type="checkbox" checked>` in HTML; the HTML
  parser ignores raw `<input>`, so checked/unchecked state had to be captured earlier, at the
  markdown layer itself.

**Resolved by #104**: task-list markers are stripped from the item's text and captured on
`BulletItem.checked`, and the emitter prepends a `☑`/`☐` glyph — not a `BULLET_CHECKBOX` preset
list. **Resolved by #103**: `<pre>`/`<code>` now set `font_family="Courier New"` on their runs
(tracked via `html_parser.py`'s `_in_pre`/`_code_depth`), emitted through `weightedFontFamily` in
`emitter.py` — no separate `CodeBlock` AST node was needed. The HTML intermediary handled both
constructs without needing to become a direct MD → AST parser.

## File changed

**Only one file** at the time this landed: `src/mcp_gee_sweet/tools/docs/__init__.py`. The
Docs package was later split by domain (#64); this logic now lives in
`src/mcp_gee_sweet/tools/docs/content.py`.

---

## Implementation

### 1. New import + helper

```python
import markdown as _md  # already a dep; add import at top of docs/__init__.py


def _md_to_html(md_text: str) -> str:
    return _md.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
```

Extensions chosen:
- `tables` — GitHub-flavored pipe tables → `<table>`
- `fenced_code` — triple-backtick blocks → `<pre><code>` (renders as plain text for now)
- `sane_lists` — correct mixed list handling
- `nl2br` intentionally **excluded** — single newlines within a paragraph should be
  ignored (standard Markdown), not become `<br>` tags

### 2. Extend `_html_to_doc_requests` → `_to_doc_requests`

Replace:
```python
def _html_to_doc_requests(html_content, start_index=1):
    nodes = html_to_ast(html_content)
    return ast_to_requests(nodes, start_index)
```

With:
```python
def _to_doc_requests(content, content_format="html", start_index=1):
    if content_format == "markdown":
        content = _md_to_html(content)
    nodes = html_to_ast(content)
    return ast_to_requests(nodes, start_index)
```

Update both call sites in `create_doc` and `write_doc_content`.

### 3. `create_doc` — add `content_format` param

```python
def create_doc(title, content=None, folder_id=None, content_format="html", ctx=None):
```

Docstring update:
> Content is interpreted as HTML by default. Pass `content_format='markdown'` to supply
> GitHub-flavored Markdown instead.

### 4. `write_doc_content` — add `content_format` param

```python
def write_doc_content(doc_id, content, content_format="html", ctx=None):
```

Same docstring update.

### 5. New tool: `create_doc_from_file`

```python
@tool(annotations=ToolAnnotations(title="Create Document from File", destructiveHint=True))
def create_doc_from_file(
    local_path: str,
    title: str | None = None,
    folder_id: str | None = None,
    ctx: Context = None,
) -> dict:
    """
    Create a Google Doc from a local .md or .html file.

    Format is inferred from the file extension (.md → markdown, .html/.htm → HTML).
    Title defaults to the filename without extension.

    Note: same auth constraints as create_doc — requires OAuth or ADC for personal Drive.
    """
    from pathlib import Path

    path = Path(local_path)
    if not path.exists():
        return {"error": f"File not found: {local_path}"}

    ext = path.suffix.lower()
    if ext == ".md":
        content_format = "markdown"
    elif ext in (".html", ".htm"):
        content_format = "html"
    else:
        return {"error": f"Unsupported file extension '{ext}'. Use .md or .html"}

    content = path.read_text(encoding="utf-8")
    doc_title = title or path.stem

    # --- same body as create_doc from here ---
    lc = ctx.request_context.lifespan_context
    drive_service = lc.drive_service
    docs_service = lc.docs_service
    target_folder_id = folder_id or lc.folder_id
    # ... create file, call _to_doc_requests(content, content_format, 1), fill_tables, etc.
```

The tool body is a copy of `create_doc`'s internals (can't call a registered tool from
another registered tool), passing `content_format` through to `_to_doc_requests`.

---

## Markdown → Docs mapping

| Markdown input | HTML emitted | AST node | Google Docs result |
|---|---|---|---|
| `# Heading 1` | `<h1>` | `Heading(level=1)` | HEADING_1 paragraph style |
| `**bold**` | `<strong>` | `Run(bold=True)` | bold text run |
| `*italic*` | `<em>` | `Run(italic=True)` | italic text run |
| `~~strikethrough~~` | `<s>` (GFM strikethrough) | `Run(strikethrough=True)` | struck-through text run (#1077) |
| `<s>`, `<strike>`, `<del>` (inline HTML) | passed through | `Run(strikethrough=True)` | struck-through text run (#1077) |
| `<sub>`, `<sup>` (inline HTML) | passed through | `Run(baseline_offset="SUBSCRIPT"/"SUPERSCRIPT")`; the innermost open tag wins | subscript / superscript text run (#1119) |
| `<mark>` (inline HTML) | passed through | `Run(background_color=` yellow `)` | yellow-highlighted text run (#1119) |
| `[text](url)` | `<a href=...>` | `Run(link_url=...)` | hyperlink |
| bare `https://url` | `<a href=...>` (autolink extension) | `Run(link_url=...)` | hyperlink — disable via `autolink_urls=False` |
| `[![alt](src)](url)` | `<a href=...><img ...></a>` | `Image(link_url=...)` | linked inline image (#977) |
| `- item` | `<ul><li>` | `BulletItem(ordered=False)` | disc bullet list |
| `1. item` | `<ol><li>` | `BulletItem(ordered=True)` | numbered list |
| `3. item` | `<ol start="3"><li>` | `BulletItem(ordered=True, number=3)` | joins the last list if it stopped at 2, else literal numbers (`list-start-numbers.md`) |
| `- [x] item` | `<input type="checkbox" checked>` | `BulletItem(checked=True)` | bullet with a `☑`/`☐` glyph prefix |
| a block indented under an item (a second paragraph, code, a quote, a heading, a table, a rule, an image) | the block inside the `<li>` | that block's own node with `list_depth` = the item's depth (#1094) | no bullet, indented to the item's text (a quote one step further, with its border); the list continues past it, so the next item keeps its number |
| `- # Heading` (a heading as the item's own text) | `<li><h1>` | `BulletItem(heading_level=1)` | a bulleted HEADING_1 paragraph (#1094) |
| `\| a \| b \|` | `<table>` | `Table` | table via two-phase fill |
| `` `code` `` | `<code>` | `Run(font_family="Courier New")` | monospace text run |
| ` ```code block``` ` | `<pre><code>` | `Paragraph` (all runs `font_family="Courier New"`) | monospace paragraph, 8pt above and below (#1098) |
| `> quoted text` | `<blockquote><p>` | `Paragraph(blockquote_depth=1)` (or `Heading`/`BulletItem`/`NamedBlock`, whichever the quoted content is) | left border + indent, scaled by nesting depth (#476), 8pt above and below the quote; adjacent quotes kept apart (#1098) — see [blockquote-representation.md](blockquote-representation.md) |

A blank line between two paragraphs is 10pt of `spaceBelow` on the first (#1382), what Docs'
own "Add space after paragraph" adds, close to the 8pt around code blocks and quotes. Drive's
import makes the same gap with an empty paragraph instead, which would read back as content.
The gap goes between two plain paragraphs in the same quote depth and list item, and between
an item's text and a paragraph inside that item, a literal item's included. Inside a quote, an
item's text gets none: the paragraph has a different indent, so Docs leaves the gap out of the
bar. A spacer line (`&nbsp;`) is a gap already, and a
list, a heading or a table keeps its own look next to a paragraph. A paragraph in a table cell
gets none: cells stay compact, and Markdown can't write one.

The gap is set on each paragraph, and the API has no other way to write it short of changing
NORMAL_TEXT for the whole Doc, lists and table cells included. A value on a paragraph beats the
named style, so a theme's spacing has to win some other way, in either order:

- A Doc that already has NORMAL_TEXT spacing gets no gaps: `_replace_doc_content` reads it
  (`_has_own_paragraph_spacing`) and drops them from the converted requests
  (`without_paragraph_gaps`). Spacing of exactly 0 can't be told from the default.
- `apply_theme` with a NORMAL_TEXT `space_above` or `space_below` hands the gap paragraphs back to
  the named style (`_clear_paragraph_gap_requests`), found by the value `PARAGRAPH_GAP_PT`, which
  no other spacing the emitter writes uses.

`get_doc_theme` must not report what the emitter wrote as the Doc's theme: applying it would
set that spacing across the target Doc, lists and cells included. So NORMAL_TEXT comes from body
text, not a quote, a rule, an empty line or a code block (`_is_block_paragraph`), which it knows
by Courier New and its 8pt on both sides, since a Doc set in Courier by hand is body text. Its
spacing leaves out 8pt and 10pt (`_body_style_entry`), which also covers a paragraph beside a
quoted table: that has the quote's 8pt and no border. A Doc with no body text at all takes
NORMAL_TEXT from its first block with text, font but not those values. The first paragraph of a
style decides even with no explicit style, and a text field counts only when every run in it
shares that field, or one run's inline bold or code span would read as the Doc's body text.

`get_doc_as_markdown` doesn't read paragraph spacing, so the export is the same with or without
gaps (checked live on r06).

A list marker stays plain whatever style its item's text has (#1383), as it does in a browser,
so one list's markers match. A marker's look is `paragraph.bullet.textStyle`, which matches the
screen. Checked live, what sets it:

| Moment | What the marker takes |
|---|---|
| `createParagraphBullets` | Every style the paragraph's whole text shares, however many requests set it: a bold item in two runs still gets a bold marker. The newline's own style doesn't matter, and clearing it before or after changes nothing. |
| A later `updateTextStyle` | That request's style, if its range covers all of the paragraph's text, with or without the newline. Two requests that only add up to the whole text leave the marker alone. |

So a `BulletItem`'s run styles go after the whole bullet pass (`_item_run_style_requests`), and
a run that is the item's whole text is styled with a throwaway zero-width space after it, deleted
by the next request, because no split works for a one-character item. A heading item's marker
keeps its heading's size and weight: that comes from the named style, not from a run. This
corrects #1383's own reading that a marker follows the last run: r06's step 3 differs because it's
the only step not bold throughout, and an item that's plain then bold had a plain marker already.

Code blocks and inline code render with `font_family="Courier New"` on every run (#103) — no
further code-block-specific styling (background shading, line numbers) is planned.

A multi-line code block's own internal line breaks are emitted as `"\v"` (soft break), not
`"\n"` — the Docs API treats a literal `"\n"` as a new paragraph boundary regardless of styling,
which used to fragment one fenced block into one `NORMAL_TEXT` Docs paragraph per line (#719),
contradicting the "monospace **paragraph**" (singular) mapping above. See `CLAUDE.md`'s
`docs/emitter.py` paragraph for the full fix, including the matching read-side reversal in
`doc_to_ast.py`.

---

## Verification

1. `uv run python -m pytest tests/` — no regressions
2. New unit tests in `tests/test_docs.py`:
   - `_md_to_html` produces expected HTML for headings, bold, lists, tables
   - `_to_doc_requests("# Hello", content_format="markdown")` produces the same AST/requests
     as `_to_doc_requests("<h1>Hello</h1>", content_format="html")`
3. Smoke test via `create_doc_from_file` on a real `.md` file
4. Add QA checklist entry to `docs/qa/tests/docs.md`

---

## What this does NOT do

- Does not change `upload_file`'s markdown path (that goes through Drive's native importer,
  which is fine for raw uploads)
- Does not support nested tables (a table inside a table cell) via Markdown — the `markdown`
  library's table syntax can't express one; see `docs/known-limitations.md`'s Google Docs
  section for the HTML-input workaround
- Does not support `.md` files with front matter (YAML front matter would show up as a
  `<hr>` paragraph — acceptable for now). Superseded: plan rule D3 omits it from the Doc
  through every entry point (#1173, `tools/front_matter.py`).
