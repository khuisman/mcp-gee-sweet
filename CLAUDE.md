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

- `tools/sheets/data.py` — read/write cell data (`get_sheet_data`, `get_sheet_formulas`, `get_multiple_*`, `find_in_spreadsheet`, `update_cells`, `batch_update_cells`, `batch_update`)
- `tools/sheets/structure.py` — sheet structure (`list_sheets`, `copy_sheet`, `rename_sheet`, `create_sheet`, `add_rows`, `add_columns`, `add_chart`)
- `tools/sheets/helpers.py` — A1 notation helpers (`_parse_a1_notation`, `_column_index_to_letter`, etc.)
- `tools/drive/files.py` — file/folder operations (`create_spreadsheet`, `list_spreadsheets`, `list_files`, `search_files`, `create_folder`, `copy_file`, `move_file`, `rename_file`, `delete_file`, etc.)
- `tools/drive/sharing.py` — permissions (`share_spreadsheet`, `share_file`, `list_permissions`, `update_permission`, `remove_permission`)
- `tools/drive/transfer.py` — upload/download/sync/export/revisions
- `tools/docs/` — Google Docs package (`create_doc`, `get_doc_content`, `write_doc_content`, `create_doc_from_file`, `insert_doc_text`, `delete_doc_range`, `get_doc_structure`, `style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `apply_theme`); sub-modules: `ast.py` (dataclass schema), `html_parser.py` (HTML→AST), `emitter.py` (AST→Docs API requests + multi-phase table fill including nested table and cell styling support)
- `tools/cache.py` — `refresh_cache`
- `tools/calendar.py` — Calendar API tools

`__init__.py` just re-exports `main()`.

**Startup / auth** (`spreadsheet_lifespan`): FastMCP lifespan context manager that authenticates on server start and injects a `SpreadsheetContext` (holding `sheets_service` and `drive_service`) into every tool call via `ctx.request_context.lifespan_context`.

The project philosophy is to be as powerful and flexible as possible by default, while giving security-conscious users the configuration knobs to lock things down. Two mechanisms reflect this:

- **Auth** (`AUTH_METHOD`): out of the box the waterfall tries everything so the server just works; setting `AUTH_METHOD` restricts it to exactly one method with no fallback.
- **Tool surface** (`ENABLED_TOOLS` / `--include-tools`): by default all tools are registered; setting `ENABLED_TOOLS` to a comma-separated list of function names limits the server to exactly that subset. This lets operators expose only the tools their users need.

By default (`AUTH_METHOD` unset), auth falls through in order: OAuth (`CREDENTIALS_PATH`/`TOKEN_PATH`) → service account (`CREDENTIALS_CONFIG` or `SERVICE_ACCOUNT_PATH`) → Application Default Credentials. OAuth is tried first because it authenticates as the user (full personal Drive access); service account is a fallback for headless/server deployments.

Set `AUTH_METHOD` to pin a specific method with no fallback — removes ambiguity for security audits, CI, or testing a tool's behavior under a known credential type:
- `AUTH_METHOD=oauth` — OAuth only; fails fast if credentials are missing
- `AUTH_METHOD=service_account` — service account only; requires `CREDENTIALS_CONFIG` or `SERVICE_ACCOUNT_PATH`
- `AUTH_METHOD=adc` — ADC only

**Tool registration** (`tool` decorator wrapper): A custom `@tool()` decorator wraps `@mcp.tool()`. It checks `ENABLED_TOOLS` (set via `ENABLED_TOOLS` env var or `--include-tools` CLI arg) and skips registration for any tool not in the allowlist. This is how tool filtering works — tools simply aren't registered with FastMCP rather than being conditionally hidden.

**Two Google API clients**: The server builds both a Sheets client (`sheets/v4`) and a Drive client (`drive/v3`). Most tools use only the Sheets client; `list_spreadsheets`, `create_spreadsheet`, `share_spreadsheet`, and `list_folders` use Drive. `create_spreadsheet` uses Drive to create the file (so it can place it in a folder), not the Sheets API.

**A1 notation helpers**: `_parse_a1_notation`, `_column_index_to_letter`, and `_letter_to_column_index` convert between A1 ranges and the 0-based row/column indices the Sheets batchUpdate API requires. The Sheets values API uses A1 notation directly; batchUpdate requires numeric indices — keep that distinction in mind when adding new tools.

**MCP resources**: Two resources are registered — `server://auth-status` (active auth method and Drive capability limits) and `spreadsheet://{spreadsheet_id}/info` (sheet list and grid properties). Both use `mcp.get_lifespan_context()` (not `ctx`) because resources don't receive a `Context` argument the same way tools do.

**`batch_update` tool**: This is a passthrough to the Sheets `spreadsheets().batchUpdate()` endpoint and accepts raw request objects. It's the escape hatch for any operation not covered by the named tools (formatting, conditional formatting, dimension properties, etc.).

## Development workflow

**MCP restart**: After `docker compose restart mcp-gee-sweet`, Claude Code does not automatically reconnect to the SSE server — you must restart Claude Code too to re-establish the connection.

