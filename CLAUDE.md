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
- `tools/sheets/structure.py` — sheet structure (`list_sheets`, `copy_sheet`, `duplicate_sheet`, `rename_sheet`, `create_sheet`, `delete_sheet`, `add_rows`, `add_columns`, `delete_rows`, `delete_columns`, `hide_rows`, `unhide_rows`, `hide_columns`, `unhide_columns`, `resize_rows`, `resize_columns`, `format_cells`, `update_borders`, `merge_cells`, `unmerge_cells`, `freeze`, `update_sheet_properties`, `sort_range`, `add_chart`)
- `tools/sheets/helpers.py` — A1 notation helpers (`_parse_a1_notation`, `_column_index_to_letter`, etc.)
- `tools/drive/files.py` — file/folder operations (`create_spreadsheet`, `import_csv_to_sheet`, `list_spreadsheets`, `list_files`, `search_files`, `create_folder`, `copy_file`, `move_file`, `rename_file`, `delete_file`, `list_shared_with_me`, `list_recent_files`, `get_storage_quota`, etc.)
- `tools/drive/sharing.py` — permissions (`share_spreadsheet`, `share_file`, `list_permissions`, `update_permission`, `remove_permission`)
- `tools/drive/transfer.py` — upload/download/sync/export/revisions
- `tools/drive/activity.py` — `list_file_activity` (Drive Activity API v2; requires `drive.activity.readonly` scope)
- `tools/docs/` — Google Docs package; `__init__.py` is a thin dispatcher that delegates to four submodules:
  - `docs/content.py` — helpers (`_html_to_text`, `_md_to_html`, `_to_doc_requests`, `_html_to_doc_requests`) and tools (`create_doc`, `get_doc_content`, `write_doc_content`, `create_doc_from_file`, `insert_doc_text`, `delete_doc_range`, `get_doc_structure`, `insert_inline_image`, `insert_page_break`, `create_named_range`, `create_bookmark`). The Docs API has no bookmark-creation endpoint — `create_bookmark` is a thin wrapper over `createNamedRange` spanning a single character; neither tool's output is a link target (only UI-created bookmarks/headings are)
  - `docs/tables.py` — tools (`insert_doc_table`, `insert_table_row`, `delete_table_row`, `insert_table_column`, `delete_table_column`, `merge_table_cells`)
  - `docs/style.py` — helpers (`_NAMED_STYLE_TYPES`, `_read_body_styles`, `_read_named_styles`, `_build_named_style_requests`) and tools (`style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `get_doc_named_styles`, `apply_theme`)
  - `docs/layout.py` — tools (`create_header`, `create_footer`)
  - `docs/comments.py` — tools (`list_doc_comments`, `add_doc_comment`, `resolve_doc_comment`) via the Drive `comments`/`replies` resource, not the Docs API
  - `docs/ast.py` — dataclass schema
  - `docs/html_parser.py` — HTML→AST
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

**Async execution** (`execute_in_thread` + `thread_http`, in `http_transport.py`): every `@tool()`-registered function is `async def`, and `_timed`'s wrapper is unconditionally `async def wrapper(...): return await func(...)` — so **any new tool must be `async def`**, even one with no Google API calls (see `tools/cache.py`'s `get_cache_ttl`/`set_cache_ttl`/`refresh_cache` for an example with an empty `await`-free body; a plain `def` there raises `TypeError` at call time since `await`ing a sync return value fails — `test_server.py::TestAllToolsAreAsync` guards against this recurring). Every `.execute()` call is wrapped `await execute_in_thread(chain.execute, service)` (`http_transport.py`, re-exported from `auth.py` for existing imports) — **do not** write `asyncio.to_thread(chain.execute, http=thread_http(service))` directly: `thread_http(service)` as an eagerly-evaluated kwarg resolves on the event-loop thread before the worker thread starts, so concurrent calls end up sharing one transport across threads (a real, live-reproduced bug, fixed in #183's follow-up round — see the decision doc). `execute_in_thread` defers the `thread_http()` call into the thread itself via a lambda. `thread_http()` hands each worker thread its own `AuthorizedHttp` transport built from the shared credentials, since the lifespan-scoped `sheets_service`/`drive_service`/etc. objects each carry one `httplib2` transport that isn't safe for concurrent use across threads. Six multi-call tools (`sync_folder`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `import_csv_to_sheet`, `share_spreadsheet`, `share_file`) parallelize their per-item work via `asyncio.gather(..., return_exceptions=True)` instead of looping serially. `cache.py`'s SQLite I/O deliberately stays synchronous, not `to_thread`-wrapped — see the comment in `cache.py::_open()`; the module's two Google-API-calling helpers (`get_modified_time`, `fetch_sheets`) are `async def` and do use `execute_in_thread` for their own `.execute()` calls. `_BaseCache.snapshot_epoch()`/`store(..., epoch=...)` guard against a `refresh_cache()` call landing mid-fetch and having its invalidation silently overwritten — only wired up for `SheetStructureCache`/`SheetDataCache` so far. Full rationale: `docs/decisions/decision-async-tool-execution.md`. When unit-testing genuine cross-thread concurrency (not just correctness) with a `threading.Barrier` or similar, the block must live inside the mocked `.execute()` call, not `.list()`/`.create()`/etc. — those are evaluated eagerly on the event-loop thread while building the call chain, before `execute_in_thread` ever hands off to a worker thread, so blocking there freezes the single-threaded event loop instead of proving concurrency (see `tests/drive/test_transfer.py::TestSyncFolderRecursive::test_recursive_sibling_subfolders_descend_concurrently`).

**Two Google API clients**: The server builds both a Sheets client (`sheets/v4`) and a Drive client (`drive/v3`). Most tools use only the Sheets client; `list_spreadsheets`, `create_spreadsheet`, `share_spreadsheet`, and `list_folders` use Drive. `create_spreadsheet` uses Drive to create the file (so it can place it in a folder), not the Sheets API.

**A1 notation helpers**: `_parse_a1_notation`, `_column_index_to_letter`, and `_letter_to_column_index` convert between A1 ranges and the 0-based row/column indices the Sheets batchUpdate API requires. The Sheets values API uses A1 notation directly; batchUpdate requires numeric indices — keep that distinction in mind when adding new tools.

**MCP resources**: Two resources are registered — `server://auth-status` (active auth method and Drive capability limits) and `spreadsheet://{spreadsheet_id}/info` (sheet list and grid properties). Both use `mcp.get_lifespan_context()` (not `ctx`) because resources don't receive a `Context` argument the same way tools do.

**`batch_update` tool**: This is a passthrough to the Sheets `spreadsheets().batchUpdate()` endpoint and accepts raw request objects. It's the escape hatch for any operation not covered by the named tools (formatting, conditional formatting, dimension properties, etc.).

## Development workflow

**MCP restart**: After `docker compose restart mcp-gee-sweet`, Claude Code does not automatically reconnect to the SSE server — you must restart Claude Code too to re-establish the connection.

**Generated tool docs**: `docs/tools.md` and the "Tool filtering" section of `docs/configuration.md` are generated by `scripts/gen_tool_docs.py` from the tool source (names, signatures, docstrings) — do not hand-edit the tool tables in either file. The script is wired into `.pre-commit-config.yaml` and runs whenever a file under `src/mcp_gee_sweet/tools/` or either generated doc changes; it fails the commit if a tool has no docstring, if a tool doesn't match any section in the script's `SECTIONS` config, or if a `SUBSETS` entry references a renamed/removed tool name. Run it manually with `uv run python scripts/gen_tool_docs.py`.

**PR creation**: open PRs ready-for-review (`gh pr create`, no `--draft`), not as drafts — draft should be an explicit, stated exception (e.g. genuinely incomplete work you want visible early), not the default. `gh pr merge --admin` refuses a draft PR outright (`merge-pr.md` now handles it by readying first), so an unnecessary draft is pure friction at merge time with no upside.

