# Configuration

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `AUTH_METHOD` | Pin auth to one method: `oauth`, `service_account`, `adc` | waterfall |
| `SERVICE_ACCOUNT_PATH` | Path to service account JSON key | — |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google's standard service account path (feeds ADC) | — |
| `DRIVE_FOLDER_ID` | Default Drive folder for service account operations | — |
| `CREDENTIALS_PATH` | Path to OAuth client ID JSON | `credentials.json` |
| `TOKEN_PATH` | Path to store the OAuth refresh token | `token.json` |
| `CREDENTIALS_CONFIG` | Base64-encoded credentials JSON (for containers) | — |
| `ENABLED_TOOLS` | Comma-separated list of tool names to register | all tools |
| `CACHE_DB_PATH` | Path to the SQLite cache database | `/tmp/mcp_gee_sweet.db` |
| `CACHE_TTL` | Cache time-to-live in seconds | `1800` (30 min) |
| `HOST` | Bind address for SSE transport | `0.0.0.0` |
| `PORT` | Port for SSE transport | `8000` |
| `DEBUG_LEVEL` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` — controls package and access logs | — |
| `LOG_FILE` | Write server logs to this file path (requires `DEBUG_LEVEL`) | — |
| `ACCESS_LOG_FILE` | Write tool access logs to this file path (requires `DEBUG_LEVEL`) | — |

See [Authentication](auth.md) for auth-specific variable details.

## .env file

The server loads `src/mcp_gee_sweet/.env` at startup (before any environment variables are read), so you can configure it without shell exports or MCP client config changes. A template with all available variables is at `src/mcp_gee_sweet/.env.template` — copy it to `.env` and uncomment what you need.

Environment variables set by the OS or the MCP client always take precedence over `.env`.

## Logging

By default the server logs warnings and above to stderr. Set `DEBUG_LEVEL` to enable richer output — it controls both the package logger and uvicorn HTTP access logs with a single value.

```ini
# src/mcp_gee_sweet/.env
DEBUG_LEVEL=DEBUG   # DEBUG | INFO | WARNING | ERROR
```

Every tool call emits a single access log line at `INFO` level to the `mcp_gee_sweet.access` logger:

```
2026-06-23 22:45:19 INFO mcp_gee_sweet.access "127.0.0.1" "claude-code/1.x" "TOOL list_recent_files" 200 0.475s
```

IP and user agent are populated from the HTTP request in SSE mode; they fall back to `-` in stdio mode.

**Docker** (`make logs`): `DEBUG_LEVEL=DEBUG` is the default in `docker-compose.yml`. Server logs, tool access lines, and uvicorn HTTP access logs all write to stderr; Docker captures everything in `make logs`.

**stdio** (OAuth server via Claude Code): stderr is dropped by the host. Set `LOG_FILE` to capture all output — server debug lines and access log lines are mixed in the same file, differentiated by logger name (`mcp_gee_sweet.server` vs `mcp_gee_sweet.access`). Set `ACCESS_LOG_FILE` to also write access lines to a separate file.

```ini
DEBUG_LEVEL=DEBUG
LOG_FILE=/tmp/mcp-gee-sweet.log
ACCESS_LOG_FILE=/tmp/mcp-gee-sweet-access.log   # optional, access-only view
```

```bash
make dev-logs      # tail mixed server + access logs
make access-logs   # tail access lines only (requires ACCESS_LOG_FILE)
```

Access logs are emitted at `INFO` level — they appear when `DEBUG_LEVEL` is `DEBUG` or `INFO` and are suppressed at `WARNING` or above.

**Claude Desktop:** logs are written automatically to `~/Library/Logs/Claude/mcp-server-<name>.log` — no extra configuration needed.

## Tool filtering

By default all 60 tools are registered. Use `ENABLED_TOOLS` (or `--include-tools` on the CLI) to restrict the server to exactly the tools you need. This reduces the AI's context window cost — each registered tool is a name the model must reason about on every call.

```bash
# Environment variable
ENABLED_TOOLS=get_sheet_data,update_cells,list_spreadsheets,list_sheets

# CLI flag
uv run mcp-gee-sweet --include-tools get_sheet_data,update_cells,list_spreadsheets
```

If neither is set, all tools are registered.

### Suggested subsets

**Read-only Sheets:**
```
get_sheet_data,get_sheet_formulas,get_multiple_sheet_data,get_multiple_spreadsheet_summary,find_in_spreadsheet,list_sheets,list_spreadsheets
```

**Sheets read + write:**
```
get_sheet_data,get_sheet_formulas,get_multiple_sheet_data,get_multiple_spreadsheet_summary,find_in_spreadsheet,list_sheets,list_spreadsheets,update_cells,batch_update_cells,create_sheet,rename_sheet,add_rows,add_columns
```

**Docs only:**
```
create_doc,get_doc_content,get_doc_structure,write_doc_content,insert_doc_text,insert_doc_table,delete_doc_range,style_doc_range,style_doc_table_cells
```

**Calendar only:**
```
list_calendars,get_calendar,list_events,get_event,create_event,update_event,delete_event,find_free_slots
```

See [Tools](tools.md) for the full list of tool names.

## Caching

The server caches responses in a local SQLite database to reduce API calls and latency. Five namespaces are cached: sheet structure, sheet data, Drive folder listings, doc content, and calendar metadata.

- TTL-based expiry: controlled by `CACHE_TTL` (default 30 minutes)
- Dirty invalidation: write operations mark the relevant cache entries stale immediately
- Scoped flush: `refresh_cache` accepts a `spreadsheet_id`, `doc_id`, `folder_id`, or `calendar_id` to invalidate only that resource; omit all params to flush everything

The DB path defaults to `/tmp/mcp_gee_sweet.db`. Set `CACHE_DB_PATH` to a persistent location if you want the cache to survive container restarts.
