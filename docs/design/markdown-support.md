# Design: Markdown Support for Google Docs Tools

**Status:** Shipped. `content_format='markdown'` on `create_doc`/`write_doc_content`, plus
`create_doc_from_file`, landed via #102/#103/#104 (PR #105); bare-URL autolinking (`autolink_urls`)
landed separately via #248 (PR #265). Live-verified: [2026-06-28 QA results](../qa/results/2026-06-28.md),
[2026-07-04 QA results](../qa/results/2026-07-04-docs.md).

## Problem

`create_doc` and `write_doc_content` only accept HTML. Users who work primarily with `.md` files
have to convert manually before calling these tools. The project already has the `markdown`
library as a dependency (used in `transfer.py`) and a clean HTML → AST → Docs API pipeline, but
markdown content never flows through that pipeline.

## Solution

Add a `markdown → HTML` shim at the docs layer, then expose it in two ways:
1. A `content_format` parameter on `create_doc` and `write_doc_content`
2. A new `create_doc_from_file` tool for uploading local `.md` / `.html` files

This intentionally does **not** use Drive's native HTML importer (which `upload_file` already
does when `convert_to_doc=True`). Routing through our AST pipeline gives consistent formatting
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
import markdown as _md   # already a dep; add import at top of docs/__init__.py

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
| `~~strikethrough~~` | `<del>` | `Run(strikethrough=True)` | strikethrough |
| `[text](url)` | `<a href=...>` | `Run(link_url=...)` | hyperlink |
| bare `https://url` | `<a href=...>` (autolink extension) | `Run(link_url=...)` | hyperlink — disable via `autolink_urls=False` |
| `- item` | `<ul><li>` | `BulletItem(ordered=False)` | disc bullet list |
| `1. item` | `<ol><li>` | `BulletItem(ordered=True)` | numbered list |
| `- [x] item` | `<input type="checkbox" checked>` | `BulletItem(checked=True)` | bullet with a `☑`/`☐` glyph prefix |
| `\| a \| b \|` | `<table>` | `Table` | table via two-phase fill |
| `` `code` `` | `<code>` | `Run(font_family="Courier New")` | monospace text run |
| ` ```code block``` ` | `<pre><code>` | `Paragraph` (all runs `font_family="Courier New"`) | monospace paragraph |

Code blocks and inline code render with `font_family="Courier New"` on every run (#103) — no
further code-block-specific styling (background shading, line numbers) is planned.

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
  `<hr>` paragraph — acceptable for now)
