# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Run locally from the cloned repo:
```bash
uv run mcp-gee-sweet
uv run mcp-gee-sweet --transport sse   # SSE instead of stdio
```

Build and publish:
```bash
uv build       # produces dist/*.whl
uv sync        # install deps from uv.lock
```

Docker:
```bash
docker build -t mcp-gee-sweet .
docker run --rm -p 8000:8000 \
  -e CREDENTIALS_CONFIG=<base64> \
  -e DRIVE_FOLDER_ID=<id> \
  mcp-gee-sweet
```

Tests live in `tests/` and can be run with `uv run pytest`.

## Architecture

Logic is split across `src/mcp_gee_sweet/`: `server.py` (MCP setup, tool decorator, resources), `auth.py` (lifespan, `SpreadsheetContext`), and `tools/` (domain-based layout):

- `tools/sheets/data.py` — read/write cell data (`get_sheet_data`, `get_sheet_formulas`, `get_multiple_*`, `find_in_spreadsheet`, `clear_values`, `update_cells`, `batch_update_cells`, `batch_update`)
- `tools/sheets/structure.py` — sheet structure (`list_sheets`, `copy_sheet`, `duplicate_sheet`, `rename_sheet`, `create_sheet`, `delete_sheet`, `add_rows`, `add_columns`, `delete_rows`, `delete_columns`, `hide_rows`, `unhide_rows`, `hide_columns`, `unhide_columns`, `resize_rows`, `resize_columns`, `format_cells`, `update_borders`, `add_data_validation`, `get_data_validation`, `merge_cells`, `unmerge_cells`, `freeze`, `update_sheet_properties`, `sort_range`, `add_chart`)
- `tools/sheets/helpers.py` — A1 notation helpers (`_parse_a1_notation`, `_column_index_to_letter`, etc.)
- `tools/drive/files.py` — file/folder operations (`create_spreadsheet`, `import_csv_to_sheet`, `list_spreadsheets`, `list_files`, `search_files`, `create_folder`, `copy_file`, `move_file`, `rename_file`, `delete_file`, `list_shared_with_me`, `list_recent_files`, `get_storage_quota`, etc.)
- `tools/drive/sharing.py` — permissions (`share_spreadsheet`, `share_file`, `list_permissions`, `update_permission`, `remove_permission`)
- `tools/drive/transfer.py` — upload/download/sync/export/revisions; `_upload_local_file` (the core behind the `upload_local_file` tool) is a module-level helper so `docs/content.py`'s `insert_local_images` can call it directly, imported cross-package the same way `docs/content.py` imports `_SA_QUOTA_ERROR` from `tools/drive/__init__.py`
- `tools/drive/activity.py` — `list_file_activity` (Drive Activity API v2; requires `drive.activity.readonly` scope)
- `tools/docs/` — Google Docs package; `__init__.py` is a thin dispatcher that delegates to four submodules:
  - `docs/content.py` — helpers (`_html_to_text`, `_md_to_html`, `_to_doc_requests`, `_html_to_doc_requests`, `_collect_doc_paragraphs`) and tools (`create_doc`, `get_doc_content`, `write_doc_content`, `create_doc_from_file`, `insert_doc_text`, `delete_doc_range`, `get_doc_structure`, `find_in_doc`, `insert_inline_image`, `insert_page_break`, `insert_softbreak_paragraph`, `insert_local_images`, `create_named_range`, `create_bookmark`). The Docs API has no bookmark-creation endpoint — `create_bookmark` is a thin wrapper over `createNamedRange` spanning a single character; neither tool's output is a link target (only UI-created bookmarks/headings are). `find_in_doc` searches paragraph text (including table cells) and returns `start_index`/`end_index` offsets in UTF-16 code units usable directly with `style_doc_range` — `_collect_doc_paragraphs` is a generator (so a caller can stop early once `max_results` is hit) that walks the Docs API body, trusting each `ParagraphElement`'s own `startIndex` when present and otherwise carrying the running offset forward rather than dropping that element, since the API doesn't always populate it (seen on a document's first element). `insert_softbreak_paragraph` joins multiple lines with a literal `"\v"` (vertical tab) character in a single `insertText` call — confirmed live that the Docs API stores this as one paragraph element rather than splitting it, matching the Docs UI's own Shift+Enter soft-break convention — and sets `namedStyleType` explicitly over the inserted span rather than leaving it to whatever the insertion point would otherwise inherit. `insert_local_images` uploads local image files and swaps each into the doc at a plain-text marker in one call; confirmed live that `insertInlineImage` with a `drive_file_id` fails with "There was a problem retrieving the image" unless the file is first shared `anyone`/`reader` — the Docs backend fetches the image as an anonymous HTTP request, so being accessible to the authenticated user alone is not enough (this also applies to the existing `insert_inline_image` tool's `drive_file_id` path, not just the new one; its docstring now says so).
  - `docs/tables.py` — tools (`insert_doc_table`, `insert_table_row`, `delete_table_row`, `insert_table_column`, `delete_table_column`, `merge_table_cells`)
  - `docs/style.py` — helpers (`_NAMED_STYLE_TYPES`, `_read_body_styles`, `_read_named_styles`, `_build_named_style_requests`) and tools (`style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `get_doc_named_styles`, `apply_theme`)
  - `docs/layout.py` — tools (`create_header`, `create_footer`)
  - `docs/comments.py` — tools (`list_doc_comments`, `add_doc_comment`, `resolve_doc_comment`) via the Drive `comments`/`replies` resource, not the Docs API
  - `docs/ast.py` — dataclass schema
  - `docs/html_parser.py` — HTML→AST. `_AstParser.handle_data` only buffers text while a block context is open (`<p>`/`<li>`/heading/table cell) — text with no wrapping block tag was silently dropped (#343). Fixed via a generic `_tag_depth` counter tracking open non-block tags: bare top-level text (depth 0, e.g. `"hello world"` with zero surrounding tags) now gets an implicit paragraph wrap, while text merely wrapped in an inline tag with no block ancestor (e.g. `<span>no blocks</span>`, depth 1) stays an intentional no-op, matching `test_inline_only_html_skips_batchupdate`. `_finalize()` (called once after `parser.feed()` in `html_to_ast`) flushes whatever block is still open at end-of-input, since the implicit paragraph never gets a real closing tag.
  - `docs/emitter.py` — AST→Docs API requests + multi-phase table fill including nested table and cell styling support
- `tools/cache.py` — `refresh_cache`, `set_cache_ttl`/`get_cache_ttl` (runtime TTL change, no restart needed)
- `tools/calendar.py` — Calendar API tools
- `tools/response_limits.py` — shared response-size safety net (`enforce_response_size_cap`, `write_capped_result_to_disk`); imported cross-package the same way `tools/drive/__init__.py`'s `_SA_QUOTA_ERROR` is. Cap configured via `MAX_TOOL_RESPONSE_CHARS` (default 40000); see `docs/decisions/decision-response-size-cap-generalization.md`

`__init__.py` loads `src/mcp_gee_sweet/.env` via `python-dotenv` before importing `server`, so env vars from that file are in `os.environ` by the time any module-level `os.environ.get()` runs. Priority: real env var > `.env` > default.

**Startup / auth** (`spreadsheet_lifespan`): FastMCP lifespan context manager that authenticates on server start and injects a `SpreadsheetContext` (holding `sheets_service`, `drive_service`, `docs_service`, `calendar_service`, and `activity_service`) into every tool call via `ctx.request_context.lifespan_context`.

The project philosophy is to be as powerful and flexible as possible by default, while giving security-conscious users the configuration knobs to lock things down. Two mechanisms reflect this:

- **Auth** (`AUTH_METHOD`): out of the box the waterfall tries everything so the server just works; setting `AUTH_METHOD` restricts it to exactly one method with no fallback.
- **Tool surface** (`ENABLED_TOOLS` / `--include-tools`): by default all tools are registered; setting `ENABLED_TOOLS` to a comma-separated list of function names limits the server to exactly that subset. This lets operators expose only the tools their users need.

By default (`AUTH_METHOD` unset), auth falls through in order: OAuth (`CREDENTIALS_PATH`/`TOKEN_PATH`) → service account (`CREDENTIALS_CONFIG` or `SERVICE_ACCOUNT_PATH`) → Application Default Credentials. OAuth is tried first because it authenticates as the user (full personal Drive access); service account is a fallback for headless/server deployments.

Set `AUTH_METHOD` to pin a specific method with no fallback — removes ambiguity for security audits, CI, or testing a tool's behavior under a known credential type:
- `AUTH_METHOD=oauth` — OAuth only; fails fast if credentials are missing
- `AUTH_METHOD=service_account` — service account only; requires `CREDENTIALS_CONFIG` or `SERVICE_ACCOUNT_PATH`
- `AUTH_METHOD=adc` — ADC only

**Logging** (`DEBUG_LEVEL` env var): when set, configures the `mcp_gee_sweet` package logger and `uvicorn.access` logger to the given level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). The `_timed` wrapper in `server.py` emits one `INFO` line per tool call to `mcp_gee_sweet.access` — format: `"IP" "UA" "TOOL name" status elapsed`. IP/UA come from `ctx.request_context` in SSE mode; fall back to `-` in stdio. `LOG_FILE` and `ACCESS_LOG_FILE` env vars write logs to file (required for stdio where stderr is dropped by the host). Runtime config lives in `src/mcp_gee_sweet/.env` (gitignored); template at `src/mcp_gee_sweet/.env.template`.

**Tool registration** (`tool` decorator wrapper): A custom `@tool()` decorator wraps `@mcp.tool()`. It checks `ENABLED_TOOLS` (set via `ENABLED_TOOLS` env var or `--include-tools` CLI arg) and skips registration for any tool not in the allowlist. This is how tool filtering works — tools simply aren't registered with FastMCP rather than being conditionally hidden.

**Async execution** (`execute_in_thread` + `thread_http`, in `http_transport.py`): every `@tool()`-registered function is `async def`, and `_timed`'s wrapper is unconditionally `async def wrapper(...): return await func(...)` — so **any new tool must be `async def`**, even one with no Google API calls (see `tools/cache.py`'s `get_cache_ttl`/`set_cache_ttl`/`refresh_cache` for an example with an empty `await`-free body; a plain `def` there raises `TypeError` at call time since `await`ing a sync return value fails — `test_server.py::TestAllToolsAreAsync` guards against this recurring). Every `.execute()` call is wrapped `await execute_in_thread(chain.execute, service)` (`http_transport.py`, re-exported from `auth.py` for existing imports) — **do not** write `asyncio.to_thread(chain.execute, http=thread_http(service))` directly: `thread_http(service)` as an eagerly-evaluated kwarg resolves on the event-loop thread before the worker thread starts, so concurrent calls end up sharing one transport across threads (a real, live-reproduced bug, fixed in #183's follow-up round — see the decision doc). `execute_in_thread` defers the `thread_http()` call into the thread itself via a lambda. `thread_http()` hands each worker thread its own `AuthorizedHttp` transport built from the shared credentials, since the lifespan-scoped `sheets_service`/`drive_service`/etc. objects each carry one `httplib2` transport that isn't safe for concurrent use across threads. Six multi-call tools (`sync_folder`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `import_csv_to_sheet`, `share_spreadsheet`, `share_file`) parallelize their per-item work via `asyncio.gather(..., return_exceptions=True)` instead of looping serially. `cache.py`'s SQLite I/O deliberately stays synchronous, not `to_thread`-wrapped — see the comment in `cache.py::_open()`; the module's two Google-API-calling helpers (`get_modified_time`, `fetch_sheets`) are `async def` and do use `execute_in_thread` for their own `.execute()` calls. `_BaseCache.snapshot_epoch()`/`store(..., epoch=...)` guard against a `refresh_cache()` call landing mid-fetch and having its invalidation silently overwritten — only wired up for `SheetStructureCache`/`SheetDataCache` so far. Full rationale: `docs/decisions/decision-async-tool-execution.md`. When unit-testing genuine cross-thread concurrency (not just correctness) with a `threading.Barrier` or similar, the block must live inside the mocked `.execute()` call, not `.list()`/`.create()`/etc. — those are evaluated eagerly on the event-loop thread while building the call chain, before `execute_in_thread` ever hands off to a worker thread, so blocking there freezes the single-threaded event loop instead of proving concurrency (see `tests/drive/test_transfer.py::TestSyncFolderRecursive::test_recursive_sibling_subfolders_descend_concurrently`). `download_folder`/`sync_folder` (#316/#319) added `ctx.report_progress()` calls from inside each item's own per-item coroutine so updates stream as concurrent transfers complete rather than arriving in one burst after the whole `gather` resolves — any future tool adding progress reporting to a gather-based batch (tracked for the remaining `asyncio.gather` tools in #355) must wrap that `report_progress` call in its own try/except: it's awaited *after* the item's real work already succeeded or failed, with no other guard around it, so a report_progress exception (e.g. a dropped client session) would otherwise propagate out, get caught by the outer `gather(..., return_exceptions=True)`, and overwrite an already-successful result with a spurious failure — confirmed live and fixed in PR #351's review round.

**Two Google API clients**: The server builds both a Sheets client (`sheets/v4`) and a Drive client (`drive/v3`). Most tools use only the Sheets client; `list_spreadsheets`, `create_spreadsheet`, `share_spreadsheet`, and `list_folders` use Drive. `create_spreadsheet` uses Drive to create the file (so it can place it in a folder), not the Sheets API.

**A1 notation helpers**: `_parse_a1_notation`, `_column_index_to_letter`, and `_letter_to_column_index` convert between A1 ranges and the 0-based row/column indices the Sheets batchUpdate API requires. The Sheets values API uses A1 notation directly; batchUpdate requires numeric indices — keep that distinction in mind when adding new tools.

**Docs API indices are UTF-16 code units, not Python code points**: every `startIndex`/`endIndex` in the Docs API counts UTF-16 code units — an astral-plane character (most emoji, some CJK/math symbols) is one Python `str` character but a 2-unit surrogate pair. `content.py`'s `find_in_doc`/`_collect_doc_paragraphs` accounts for this via `_utf16_units`. `emitter.py`'s offset math (table positions, paragraph-style ranges, inline run-style ranges) does not — it derives offsets from plain `len()`/`enumerate()`, a confirmed-pattern bug tracked in #358. Any new code deriving a Docs API index from Python string length needs `_utf16_units`-style accounting instead of raw `len()`.

**MCP resources**: Two resources are registered — `server://auth-status` (active auth method and Drive capability limits) and `spreadsheet://{spreadsheet_id}/info` (sheet list and grid properties). Neither takes a `ctx` argument the way tools do, so both fetch it explicitly via `mcp.get_context().request_context.lifespan_context` — `FastMCP` has no `get_lifespan_context()` method (confirmed absent as far back as `mcp==1.27.1`, so this was never a regression from #350's SDK bump; it was a pre-existing bug invisible to unit tests since `TestAuthStatusResource` only exercised `_auth_status_json()` directly, never the resource function itself — fixed in #363). `get_context()` returns a `Context` whose `.request_context.lifespan_context` is the same `SpreadsheetContext` tools reach via `ctx.request_context.lifespan_context`.

**`batch_update` tool**: This is a passthrough to the Sheets `spreadsheets().batchUpdate()` endpoint and accepts raw request objects. It's the escape hatch for any operation not covered by the named tools (formatting, conditional formatting, dimension properties, etc.).

## Development workflow

**MCP restart**: After `docker compose restart mcp-gee-sweet`, Claude Code does not automatically reconnect to the SSE server — you must restart Claude Code too to re-establish the connection.

**Generated tool docs**: `docs/tools.md` and the "Tool filtering" section of `docs/configuration.md` are generated by `scripts/gen_tool_docs.py` from the tool source (names, signatures, docstrings) — do not hand-edit the tool tables in either file. The script is wired into `.pre-commit-config.yaml` and runs whenever a file under `src/mcp_gee_sweet/tools/` or either generated doc changes; it fails the commit if a tool has no docstring, if a tool doesn't match any section in the script's `SECTIONS` config, or if a `SUBSETS` entry references a renamed/removed tool name. Run it manually with `uv run python scripts/gen_tool_docs.py`.

**PR creation**: open PRs ready-for-review (`gh pr create`, no `--draft`), not as drafts — draft should be an explicit, stated exception (e.g. genuinely incomplete work you want visible early), not the default. `gh pr merge --admin` refuses a draft PR outright (`merge-pr.md` now handles it by readying first), so an unnecessary draft is pure friction at merge time with no upside.

**Regression vs. pre-existing bug after a dependency bump**: when a bug report asks "is this a regression from the recent SDK bump" (e.g. issue #363 against #350's `mcp>=1.28.1` change), don't answer from memory or by reading changelogs alone — install the *old* pinned version in a scratch venv and check the specific API surface directly against it (e.g. `python3 -m venv /tmp/x && ./x/bin/pip install "mcp==1.27.1" && ./x/bin/python -c "from mcp.server.fastmcp import FastMCP; print(hasattr(FastMCP, 'get_lifespan_context'))"`). Confirmed in #363: `FastMCP.get_lifespan_context()` looked like it could've been removed by the bump, but it never existed even at `1.27.1` — the scratch-venv check settled the question in seconds instead of guessing from a diff.

