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
| `OAUTH_CONSENT_TIMEOUT_SECONDS` | SSE only: how long the server waits for the browser consent when there's no usable OAuth token, before starting without Google access. See [Authentication](auth.md) | `300` |
| `CREDENTIALS_CONFIG` | Base64-encoded credentials JSON (for containers) | — |
| `ENABLED_TOOLS` | Comma-separated list of tool names to register | all tools |
| `LOCAL_FILE_ACCESS` | Which local files tools may read and write: `full`, `roots`, or `off`. See [Local file access](#local-file-access) | `full` under stdio, `off` under SSE and streamable HTTP |
| `LOCAL_FILE_ROOTS` | With `LOCAL_FILE_ACCESS=roots`, the directories tools may use, separated by `:` (`;` on Windows), like `PATH` | — |
| `CACHE_DB_PATH` | Path to the SQLite cache database | `/tmp/mcp_gee_sweet.db` |
| `CACHE_TTL` | Cache time-to-live in seconds. Also adjustable at runtime via the `set_cache_ttl` tool, no restart needed | `1800` (30 min) |
| `CACHE_VALIDATE_MODIFIED_TIME` | Validate sheet/doc cache hits against Drive's `modifiedTime` before serving them, catching edits from other sessions without waiting out the TTL. Costs one extra Drive API call per cache lookup | `true` |
| `MAX_TOOL_RESPONSE_CHARS` | Safety cap on response size, in characters, for tools that can return large inline payloads (`get_sheet_data`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `find_in_spreadsheet`, `get_doc_content`, `find_in_doc`, `list_doc_comments`, `list_file_activity`, `export_file`, `sync_folder`, `list_all_events`, `list_calendar_acl`, `get_message`, `get_thread`). Defense-in-depth against MCP clients that don't degrade gracefully on an oversized tool response — see [decision-response-size-cap-reevaluation-519.md](decisions/decision-response-size-cap-reevaluation-519.md) for why the default was raised and what it does and doesn't protect against | `1000000` |
| `LIST_ALL_EVENTS_MAX_CONCURRENCY` | Most calendars `list_all_events` queries at once, shared across every concurrent `list_all_events` call on the server, to stay under the Calendar API's per-user rate limit. Raise it for faster fan-out on accounts subscribed to many calendars; lower it for a stricter rate-limit posture. Values below 1 are treated as 1 | `20` |
| `HOST` (or `FASTMCP_HOST`) | Bind address for SSE transport. `FASTMCP_HOST` is a fallback if `HOST` isn't set | `0.0.0.0` |
| `PORT` (or `FASTMCP_PORT`) | Port for SSE transport. `FASTMCP_PORT` is a fallback if `PORT` isn't set | `8000` |
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

<!-- Auto-generated by `scripts/gen_tool_docs.py` — do not edit by hand, your changes will be overwritten on the next commit. -->

By default all 139 tools are registered. Use `ENABLED_TOOLS` (or `--include-tools` on the CLI) to restrict the server to exactly the tools you need. This reduces the AI's context window cost — each registered tool is a name the model must reason about on every call.

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
get_sheet_data,get_sheet_formulas,get_multiple_sheet_data,get_multiple_spreadsheet_summary,find_in_spreadsheet,list_sheets,list_spreadsheets,update_cells,batch_update_cells,create_sheet,rename_sheet,add_rows,add_columns,import_csv_to_sheet
```

**Docs only:**
```
create_doc,create_doc_from_file,get_doc_content,get_doc_structure,find_in_doc,write_doc_content,update_doc_from_file,insert_doc_text,insert_doc_table,delete_doc_range,style_doc_range,style_doc_table_cells
```

**Calendar only:**
```
list_calendars,get_calendar,create_calendar,update_calendar,delete_calendar,add_calendar_to_list,remove_calendar_from_list,list_calendar_acl,add_calendar_acl,remove_calendar_acl,list_events,list_all_events,get_event,create_event,update_event,delete_event,find_free_slots
```

**Gmail only:**
```
list_messages,get_message,list_threads,get_thread,list_labels,send_message,create_draft,send_draft,reply_to_message,modify_labels,trash_message
```

See [Tools](tools.md) for the full list of tool names.

## Local file access

Some tools read or write files on the machine the server runs on: uploads, downloads, `sync_folder`, `create_doc_from_file`, Gmail attachments, local images in Markdown, and the `local_path` destination that large results can be written to. `LOCAL_FILE_ACCESS` decides which files they may use:

| Mode | What tools may use |
|---|---|
| `full` | Any local path the server process can open |
| `roots` | Only paths under a directory listed in `LOCAL_FILE_ROOTS`. Paths are resolved first, symlinks included, so a link inside a root that points outside it is refused |
| `off` | No local files |

**Default:** `full` under stdio, where the caller is the person running the server, and `off` under SSE and streamable HTTP, where it may not be. A network-facing server that should use local files needs `LOCAL_FILE_ACCESS` set explicitly.

**Always refused, in every mode:** the server's own credential, config, cache, and log files. That's `CREDENTIALS_PATH`, `TOKEN_PATH`, `SERVICE_ACCOUNT_PATH`, `GOOGLE_APPLICATION_CREDENTIALS`, gcloud's default ADC file, `src/mcp_gee_sweet/.env`, `CACHE_DB_PATH` (and its `-wal`/`-shm` files), `LOG_FILE`, and `ACCESS_LOG_FILE`. A file is matched by identity, so a hardlink or a differently cased path to one of them is refused too.

**In `off` mode** these tools aren't registered, since they can only work on local files: `upload_local_file`, `upload_local_folder`, `download_file`, `download_folder`, `sync_folder`, `import_csv_to_sheet`, `create_doc_from_file`, `update_doc_from_file`, and `insert_local_images`. Tools with an optional local path stay registered and return an error if one is used. That covers `local_path` on large-result tools, Gmail's `attachments[].local_path` (`content_base64` still works), and local image paths in `create_doc`/`write_doc_content` content, which fail per image while the doc is still written.

During a folder walk (`upload_local_folder`, `download_folder`, `sync_folder`), each file and subfolder is checked, not just the top directory. A refused entry is listed under `failed`, and the rest of the walk continues.

`server://auth-status` reports the active policy under `local_file_access`: its `mode`, whether it was set `explicit`ly, the `roots` in `roots` mode, and the `unregistered_tools` that `off` mode left out.

Docker example, with the host's `./data` directory as the only one tools may use:

```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/data:/data" \
  -e LOCAL_FILE_ACCESS=roots \
  -e LOCAL_FILE_ROOTS=/data \
  -e CREDENTIALS_CONFIG=<base64> \
  mcp-gee-sweet
```

An invalid `LOCAL_FILE_ACCESS` value, `roots` mode without `LOCAL_FILE_ROOTS`, or a root that isn't an existing directory stops the server at startup, before it serves. `mcp-gee-sweet auth` still runs, so a root that isn't mounted yet doesn't block re-authorization. Design: [local-file-access-policy.md](design/local-file-access-policy.md).

## Caching

The server caches responses in a local SQLite database to reduce API calls and latency. Five namespaces are cached: sheet structure, sheet data, Drive folder listings, doc content, and calendar metadata.

- TTL-based expiry: controlled by `CACHE_TTL` (default 30 minutes); change it at runtime with the `set_cache_ttl` tool instead of restarting the server
- Dirty invalidation: write operations mark the relevant cache entries stale immediately
- Change-based invalidation: for sheet structure/data and doc content (the namespaces keyed by a single Drive file), a cache hit is checked against that file's live `modifiedTime` before being served — an edit from another session or tab invalidates the entry immediately instead of waiting out the TTL. Controlled by `CACHE_VALIDATE_MODIFIED_TIME` (default `true`); disable it if the extra Drive API call per lookup isn't worth the freshness guarantee for your usage pattern. Not applied to Drive folder listings (a folder's own `modifiedTime` doesn't change when its children do) or calendar metadata (no comparable field via the Calendar API)
- Scoped flush: `refresh_cache` accepts a `spreadsheet_id`, `doc_id`, `folder_id`, or `calendar_id` to invalidate only that resource; omit all params to flush everything

The DB path defaults to `/tmp/mcp_gee_sweet.db`. Set `CACHE_DB_PATH` to a persistent location if you want the cache to survive container restarts.
