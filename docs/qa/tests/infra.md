# Infrastructure — QA Test Cases

Covers: cache behavior, tool filtering, auth fallback chain, and transport. These tests often require server-side configuration changes rather than just issuing a prompt.

Fixtures: see [`docs/qa/setup.md`](../setup.md).

## Coverage strategy

Most infrastructure behaviours are verified by unit tests rather than live QA prompts. A subprocess-based pytest fixture (start/stop the server with different env vars per test) was assessed in issue #51 and **rejected** — the setup cost outweighs the benefit at current scale, and the logic under test is directly unit-testable by patching module-level constants and mocking credential calls.

| TC range | Coverage strategy |
|---|---|
| TC-I01, I03 (cache TTL, DB path) | Unit-tested in `tests/test_cache.py` — TTL expiry and `db_path` override are exercised directly |
| TC-I04 (cache persistence across restart) | SQLite persistence is a property of the DB file, not the server — not worth a subprocess test |
| TC-I05–I07 (tool filtering) | Unit-tested in `tests/test_server.py` — `_parse_enabled_tools()` is fully covered |
| TC-I08–I12 (auth variants) | Unit tests tracked in #98 — mock `_service_account_creds`, `_oauth_creds`, and ADC |
| TC-I02 (WAL concurrency) | Manual / live QA only — requires true concurrent requests |
| TC-I13, I14 (transport) | Manual / live QA only — verify once per environment setup |
| TC-I15 (hot reload) | Manual / live QA only — known uvicorn + SSE limitation, observe and note |
| TC-I16–I20 (logging) | ✅ Already live-tested and passed — see Result entries below |
| DB recovery (issue #212) | Unit-tested in `tests/test_cache.py` `TestOpenFallback` — read-only file, read-only dir, and `:memory:` fallback all covered |
| Tool doc generation (issue #94) | `scripts/gen_tool_docs.py` is a build-time/pre-commit script, not an MCP tool — no live prompt applies. Unit-tested in `tests/test_gen_tool_docs.py`: every registered tool is covered by a section and has a docstring, subset validation catches unknown tool names, and `main()` is idempotent on a second run |
| TC-I21 (strict tool arg validation, issue #239) | ✅ Unit-tested in `tests/test_server.py::TestToolStrictArgs` (dummy tool + real `list_sheets`) and live-tested — see Result entry below |
| TC-I22 (`set_cache_ttl`, issue #99) | Unit-tested in `tests/test_cache.py` (`set_ttl` on all 5 cache classes) — TTL change takes effect on the next lookup without a restart |
| TC-I23 (`CACHE_VALIDATE_MODIFIED_TIME`, issue #99) | Unit-tested in `tests/test_cache.py` (modified-time comparison in `_get_valid`, `get_modified_time` helper, `fetch_sheets` wiring). Live verification needs an edit path outside the MCP tools' own `mark_dirty` calls (which already invalidate immediately) — see TC-I23 below for the Playwright-based approach |

---

## Cache behavior

### TC-I01: Structure cache TTL — stale entry causes re-fetch

**Setup**
Set `CACHE_TTL=10` (10 seconds) in your server config, restart the server.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}, wait 15 seconds, then list them again"

**Checks**
- First call: cache miss, API fetch, result cached
- Second call (after TTL): cache miss again, fresh API fetch
- Logs show two separate API calls
- Restore `CACHE_TTL` to default (1800) after this test

---

### TC-I02: SQLite WAL mode — concurrent reads during a write

**Setup**
This is a timing-dependent test. Issue a write (e.g. `update_cells`) and a read (`get_sheet_data`) as close to simultaneously as possible — two browser tabs or two terminal sessions both calling the MCP server.

**Checks**
- Read does not block or error while write is in progress
- Both calls return valid responses
- No SQLite locking error in logs

---

### TC-I03: CACHE_DB_PATH env var respected

**Setup**
Set `CACHE_DB_PATH=/tmp/qa_test_cache.db` and restart the server.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- File `/tmp/qa_test_cache.db` is created (check with `ls /tmp/qa_test_cache.db`)
- Default path `/tmp/mcp_gee_sweet.db` is NOT used
- Restore `CACHE_DB_PATH` to default after this test

---

### TC-I04: Cache persists across server restarts

**Prompt** (step 1 — warm the cache)
> "Summarize {SPREADSHEET_ID}"

**Setup** (step 2)
Restart the MCP server (`docker compose restart mcp-gee-sweet` or stop/start `uv run`).

**Prompt** (step 3 — check cache)
> "Summarize {SPREADSHEET_ID} again"

**Checks**
- After restart, second call shows `cache hit` in logs (SQLite file survived restart)
- Data returned matches what was cached before restart
- 🔍 **Product decision:** stale cache after restart is a known trade-off; note whether this is acceptable for the use case

---

### TC-I22: `set_cache_ttl` — runtime TTL change takes effect without restart (issue #99)

**Prompt** (step 1 — warm the cache, default TTL)
> "List the sheets in {SPREADSHEET_ID}"

**Prompt** (step 2 — lower the TTL at runtime)
> "Set the cache TTL to 3 seconds"

**Prompt** (step 3 — confirm the new TTL is honored)
> "Wait 5 seconds, then list the sheets in {SPREADSHEET_ID} again"

**Checks**
- Step 2 returns `{"ttl_seconds": 3}`
- Step 1's call is a cache miss (cold or expired from a prior test) — API fetch, result cached
- Step 3's call is a cache miss too, despite no server restart between steps — confirms the lowered TTL applied to the already-cached entry once evaluated, not just newly stored ones
- Restore the TTL after this test: `"Set the cache TTL to 1800"`

---

### TC-I23: `CACHE_VALIDATE_MODIFIED_TIME` — external edit invalidates cache before TTL expires (issue #99)

**Background:** by default, a sheet-structure/data or doc-content cache hit is checked against the source file's live Drive `modifiedTime` before being served. This matters specifically for edits that don't go through this MCP session's own write tools (which already call `mark_dirty` immediately) — e.g. another Claude session, or a person editing the file directly in the Sheets/Docs UI.

**Setup**
1. Warm the cache: "List the sheets in {SPREADSHEET_ID}"
2. Using the browser (Playwright), open {SPREADSHEET_ID} in the Sheets UI and rename one sheet tab directly (not through any MCP tool) — this changes Drive's `modifiedTime` without calling `mark_dirty`.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- The renamed sheet's new title is reflected in the result, even though `CACHE_TTL` has not elapsed since step 1 — the `modifiedTime` mismatch invalidated the cache entry immediately
- Logs show a lightweight `files.get` call (`fields=modifiedTime`) preceding the decision, distinct from the fuller `spreadsheets.get` fetch that follows on the resulting miss

Note: Playwright is used here only as the mechanism to make an edit outside the MCP tool surface (step 2 of Setup) — the actual pass/fail check is a plain API-response comparison, not a visual confirmation. Doesn't fit the existing `Playwright: required` tag definition (visual mutation the API can't confirm), so left untagged; flagging in case this is a second, distinct case the tag convention should eventually cover.

**Cleanup:** rename the sheet back to its original name.

---

## Tool filtering (`ENABLED_TOOLS`)

### TC-I05: CLI flag — only specified tools registered

**Setup**
Start server with: `uv run mcp-gee-sweet --include-tools get_sheet_data,list_sheets`

**Prompt**
> "List the files in my Drive folder"

**Checks**
- Returns "tool not found" or similar — `list_files` is not registered
- `get_sheet_data` and `list_sheets` still work normally

---

### TC-I06: ENABLED_TOOLS env var — same behavior as CLI flag

**Setup**
Set `ENABLED_TOOLS=get_sheet_data,list_sheets` and restart the server.

**Prompt**
> "Update cells in {SPREADSHEET_ID}"

**Checks**
- Returns "tool not found" — `update_cells` not registered
- Behavior identical to TC-I05

---

### TC-I07: Unlisted tool called by name

**Setup**
Same as TC-I05 or TC-I06 (only 2 tools enabled).

**Prompt**
> "Add a chart to {SPREADSHEET_ID}"

**Checks**
- MCP client returns "tool not found" for `add_chart`
- Server does not crash — just a missing tool, not an error

---

## Tool argument validation

### TC-I21: Unrecognized tool kwargs raise a validation error instead of being silently dropped (issue #239)

**Background:** FastMCP's auto-generated per-tool pydantic arg model defaults to `extra="ignore"` (pydantic's own default) — a typo'd or unknown kwarg previously fell through silently instead of erroring. Fixed centrally in the `tool()` decorator (`server.py`'s `_enforce_strict_tool_args`), which flips every registered tool's arg model to `extra="forbid"` via private FastMCP `ToolManager`/`FuncMetadata` internals (no public hook exists in `mcp` 1.27.1–1.28.1, the project's full allowed range) — applies to all ~84 tools uniformly since they all register through the same decorator. Unit-tested in `tests/test_server.py::TestToolStrictArgs` (both a throwaway dummy tool and a real production tool, `list_sheets`).

**Prompt**
> Call `list_sheets` with `spreadsheet_id={SPREADSHEET_ID}` plus an extra unrecognized kwarg, e.g. `bogus_kwarg="test"`.

**Checks**
- Call raises a validation error naming the unrecognized field and `extra_forbidden`, rather than silently succeeding
- A normal call with only valid args still succeeds (no false positives from the fix)

**Result (2026-07-04) ✅ PASS**
`list_sheets(spreadsheet_id={SPREADSHEET_ID}, bogus_kwarg="test")` raised: `1 validation error for list_sheetsArguments\nbogus_kwarg\n  Extra inputs are not permitted [type=extra_forbidden, input_value='test', input_type=str]`. Follow-up call with only `spreadsheet_id` succeeded normally, returning the sheet list — confirms the fix doesn't affect legitimate calls.

---

## Auth fallback chain

### TC-I08: CREDENTIALS_CONFIG (base64 service account)

**Setup**
Set only `CREDENTIALS_CONFIG` (base64-encoded service account JSON). Remove all other auth env vars.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Auth succeeds via `CREDENTIALS_CONFIG`
- Tool returns results normally
- Logs show service account auth path

---

### TC-I09: SERVICE_ACCOUNT_PATH

**Setup**
Set only `SERVICE_ACCOUNT_PATH` (path to service account JSON file). Remove `CREDENTIALS_CONFIG`.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Auth succeeds via `SERVICE_ACCOUNT_PATH`
- Tool returns results normally

---

### TC-I10: OAuth flow (CREDENTIALS_PATH / TOKEN_PATH) ⚠️ requires-oauth

**Setup**
Set `CREDENTIALS_PATH` and `TOKEN_PATH`. Remove service account env vars. If no token exists, a browser window should open for Google login.

**Prompt**
> "List my spreadsheets"

**Checks**
- OAuth flow completes (browser opens if needed)
- Tool returns results as the authenticated user (not service account)
- `create_spreadsheet` / `create_doc` land in personal Drive under this auth

---

### TC-I11: Application Default Credentials (ADC)

**Setup**
Run `gcloud auth application-default login` first. Remove all other auth env vars.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Auth succeeds via ADC
- Tool returns results normally

---

### TC-I12: No credentials — server fails to start with clear error

**Setup**
Remove all auth env vars. Start the server.

**Checks**
- Server fails to start
- Error message is clear about missing credentials — not an opaque exception
- Server does not start in a broken state and accept connections

---

## Transport

### TC-I13: stdio transport

**Setup**
Run `uv run mcp-gee-sweet` (default stdio transport). Connect from an MCP client (e.g. Claude Desktop with stdio config).

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Connection established via stdio
- Tool returns results normally

---

### TC-I14: SSE transport

**Setup**
Run `uv run mcp-gee-sweet --transport sse` or `make start`. Connect from Claude Desktop with SSE config pointing to `http://localhost:47000/sse`.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Connection established via SSE
- Tool returns results normally
- Server accessible at the configured port

---

## Logging

### TC-I16: DEBUG_LEVEL=DEBUG — debug and access logs appear

**Setup**
Set `DEBUG_LEVEL=DEBUG` and `LOG_FILE=/tmp/mcp-gee-sweet.log` in `src/mcp_gee_sweet/.env`. Restart the server.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- `make dev-logs` shows cache-open DEBUG lines at startup
- After the tool call, an INFO line from `mcp_gee_sweet.access` appears: `"-" - "TOOL list_sheets" 200 X.XXXs`
- Both log levels present (`DEBUG` and `INFO`) and differentiated by logger name

**Result (2026-06-23) ✅** `DEBUG_LEVEL=DEBUG` and `LOG_FILE` active via `.env`. After `list_spreadsheets`:
- Startup: `DEBUG mcp_gee_sweet.cache` lines present (5 cache-open entries)
- Access: `2026-06-23 23:00:34,893 INFO mcp_gee_sweet.access "-" - "TOOL list_spreadsheets" 200 0.668s`
- Logger names correctly differentiated in same file

---

### TC-I17: DEBUG_LEVEL=INFO — access logs only, no debug lines

**Setup**
Set `DEBUG_LEVEL=INFO` and `LOG_FILE=/tmp/mcp-gee-sweet.log`. Restart the server.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- No `DEBUG` lines in the log (cache-open messages suppressed)
- Access log `INFO mcp_gee_sweet.access` line still appears for the tool call

**Result (2026-06-23) ✅** `DEBUG_LEVEL=INFO` set in `.env`, server restarted. After `list_spreadsheets`: only `INFO mcp_gee_sweet.access "-" - "TOOL list_spreadsheets" 200 0.612s` appeared — no `DEBUG` cache-open lines or drive search lines. Access log correctly fires at INFO level.

---

### TC-I18: LOG_FILE — server output written to file

**Setup**
Set `DEBUG_LEVEL=DEBUG` and `LOG_FILE=/tmp/mcp-gee-sweet.log`. Restart the server.

**Checks**
- `/tmp/mcp-gee-sweet.log` is created on startup
- `make dev-logs` tails it correctly
- File contains startup cache-open lines and per-call access lines

**Result (2026-06-23) ✅** `/tmp/mcp-gee-sweet.log` created on startup (466 lines after one session). Contains cache-open DEBUG lines and per-call INFO access lines. `make dev-logs` tails it correctly.

---

### TC-I19: ACCESS_LOG_FILE — access lines written to separate file

**Setup**
Set `DEBUG_LEVEL=DEBUG`, `LOG_FILE=/tmp/mcp-gee-sweet.log`, and `ACCESS_LOG_FILE=/tmp/mcp-gee-sweet-access.log`. Restart the server.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- `make access-logs` shows only the `mcp_gee_sweet.access` line — no DEBUG noise
- `make dev-logs` shows both debug lines and the access line (mixed)
- The same tool call produces one entry in each file

**Result (2026-06-23) ✅** `ACCESS_LOG_FILE=/tmp/mcp-gee-sweet-access.log` set in `.env`. After `list_spreadsheets`, the access log contains only: `"-" - "TOOL list_spreadsheets" 200 0.668s` — no DEBUG cache-open noise. Mixed output confirmed in LOG_FILE.

---

### TC-I20: .env file loaded at startup

**Setup**
Add `DEBUG_LEVEL=DEBUG` to `src/mcp_gee_sweet/.env` (no shell export, no MCP client config change). Restart the server.

**Checks**
- Debug logging is active without setting the env var in the shell or MCP client
- `make dev-logs` shows startup and access log lines as expected
- 🔍 Set `DEBUG_LEVEL=WARNING` in the shell alongside `DEBUG_LEVEL=DEBUG` in `.env` — shell env wins, no debug output appears

**Result (2026-06-23) ✅** `DEBUG_LEVEL=DEBUG` and `LOG_FILE` set only in `src/mcp_gee_sweet/.env` (no shell export, no MCP client config). Server produced startup DEBUG lines and access log entries — confirms `.env` is loaded at startup. Env precedence test (shell override) pending separate verification.

---

### TC-I15: Hot reload with SSE

**Setup**
Start server with `--reload` flag and SSE transport.

**Action**
Make a trivial change to a source file (e.g. add a space and save).

**Checks**
- 🔍 **Known issue:** uvicorn hot-reload may not complete while SSE connections are alive
- Note whether reload fires, whether it completes, and whether the MCP client reconnects
- See [roadmap.md](../../roadmap.md) for context
