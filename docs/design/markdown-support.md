# Design: Markdown Support for Google Docs Tools

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

- **Code blocks** — `<pre><code>` carries no semantic signal that our HTML parser acts on, so
  they fall through to plain text. A direct parser could emit a `CodeBlock` AST node. This
  matters once Phase 3 text styles land (`font_family` → monospace), but there's nothing to
  do with such a node until then.
- **Task list state** — `- [x] item` emits `<input type="checkbox" checked>` in HTML. Our
  HTML parser ignores `<input>`, so checked/unchecked state is lost. Google Docs has no native
  checkbox API for paragraph bullets, so representation needs a decision (Unicode glyphs vs.
  `BULLET_CHECKBOX` preset).

Both are tracked as separate issues. The HTML intermediary is right for the base case; those
two constructs are where targeted extensions will eventually be needed.

## File changed

**Only one file**: `src/mcp_gee_sweet/tools/docs/__init__.py`

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
| `- item` | `<ul><li>` | `BulletItem(ordered=False)` | disc bullet list |
| `1. item` | `<ol><li>` | `BulletItem(ordered=True)` | numbered list |
| `\| a \| b \|` | `<table>` | `Table` | table via two-phase fill |
| `` `code` `` | `<code>` | plain `Run` | plain text (no mono yet) |
| ` ```code block``` ` | `<pre><code>` | plain text | plain text (no mono yet) |

Code blocks render as plain paragraphs — no special styling. A future issue could add
`<pre>` / `<code>` → monospace font handling via Phase 3 text styles (`font_family`).

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
- Does not add Phase 3 monospace styling for code blocks (separate issue)
- Does not support `.md` files with front matter (YAML front matter would show up as a
  `<hr>` paragraph — acceptable for now)
