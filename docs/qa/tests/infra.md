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
| TC-I02 (WAL concurrency), TC-I24 (cross-request transport) | Live QA via the two-subagent `mkdir`-barrier procedure in `docs/qa/run.md` §"Running true-concurrency test cases" — run during the release pass, not skipped (#673) |
| TC-I13, I14 (transport) | ✅ Live-tested post-#175 mcp v2 migration — see Result entries below |
| TC-I15 (hot reload) | Manual / live QA only — known uvicorn + SSE limitation, observe and note |
| TC-I16–I20 (logging) | ✅ Already live-tested and passed — see Result entries below |
| DB recovery (issue #212) | Unit-tested in `tests/test_cache.py` `TestOpenFallback` — read-only file, read-only dir, and `:memory:` fallback all covered |
| Tool doc generation (issue #94) | `scripts/gen_tool_docs.py` is a build-time/pre-commit script, not an MCP tool — no live prompt applies. Unit-tested in `tests/test_gen_tool_docs.py`: every registered tool is covered by a section and has a docstring, subset validation catches unknown tool names, and `main()` is idempotent on a second run |
| TC-I21 (strict tool arg validation, issue #239) | ✅ Unit-tested in `tests/test_server.py::TestToolStrictArgs` (dummy tool + real `list_sheets`) and live-tested — see Result entry below |
| TC-I22 (`set_cache_ttl`/`get_cache_ttl`, issue #99) | Unit-tested in `tests/test_cache.py` (`set_ttl`/`get_ttl` on all 5 cache classes) — TTL change takes effect on the next lookup without a restart, and is readable back |
| TC-I23 (`CACHE_VALIDATE_MODIFIED_TIME`, issue #99) | Unit-tested in `tests/test_cache.py` (modified-time comparison in `_get_valid`, `get_modified_time` helper, `fetch_sheets` wiring). Live verification needs an edit path outside the MCP tools' own `mark_dirty` calls (which already invalidate immediately) — see TC-I23 below for the Playwright-based approach |
| TC-I25, I26 (MCP resources reach lifespan context, issue #363; mechanism changed under mcp v2, issue #175) | Unit-tested in `tests/test_server.py::TestResourcesReadLifespanContext` (monkeypatches `auth.get_lifespan_context()` for the static `server://auth-status` resource, passes a fake `ctx: Context` directly for the template `spreadsheet://{id}/info` resource — mcp v2's `MCPServer` dropped `get_context()` with no replacement for static resources, confirmed live against mcp==2.0.0). ✅ Live re-verified post-migration against the real SDK — see Result entries below |
| TC-I29 (`server.json` registry manifest, issue #586) | Not reachable via any MCP tool or prompt — `server.json` is a static repo-root manifest consumed by the external `mcp-publisher` CLI and the official MCP registry, not the running server. Identity/consistency (name, PyPI identifier, `mcp-name` marker) is unit-tested in `tests/test_server_json.py`. Manual / live QA only — verify once, after each stable release that changes `server.json`'s `version` — see TC-I29 below |
| TC-I41, I42 (lane context-size hook, issue #847) | `scripts/lane_context_hook.py` is a Claude Code hook, not an MCP tool. Transcript parsing, lane scoping, warning bands and resume gating are unit-tested in `tests/test_lane_context_hook.py`. Live QA runs a headless `claude -p` session from a lane worktree with `--include-hook-events`, so the hook's real input and output are visible in the stream |

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

**Result (2026-09-04) ⏭️ SKIP**
requires CACHE_TTL=10 + server restart — pre-approved, unit-tested (tests/test_cache.py TTL expiry)

---

### TC-I02: SQLite WAL mode — concurrent reads during a write

**Setup**
This is a timing-dependent test needing two genuinely simultaneous requests to one server, which a single client session can't produce. Run it via the two-subagent `mkdir`-barrier procedure in [`docs/qa/run.md`](../run.md) §"Running true-concurrency test cases" — subagent `a` issues the write (`update_cells` to `Empty!A1`), subagent `b` the read (`get_sheet_data` on `Sales!A1:C3`), both released from the barrier together, looped 20–50×.

**Checks**
- Read does not block or error while write is in progress
- Both calls return valid responses on every iteration
- No SQLite locking error (`database is locked` / `SQLITE_BUSY` / `OperationalError`) in any `result-b-*` file, and none in the server `LOG_FILE` over the run window if it's reachable

**Result (2026-09-04) ✅ PASS**
Two-subagent mkdir-barrier procedure, mcp-gee-sweet-kai-sa, 25 iterations: subagent a wrote a per-iteration sentinel to Empty!A1 (25/25 succeeded), subagent b concurrently read Sales!A1:C3 (25/25 succeeded, zero database is locked / SQLITE_BUSY / OperationalError / empty / SSL errors). LOG_FILE grepped over the run window for locking errors — none found. #280 WAL busy_timeout fix holds under 25 concurrent write+read pairs.

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

**Result (2026-09-04) ⏭️ SKIP**
requires CACHE_DB_PATH env + restart — pre-approved, unit-tested (tests/test_cache.py db_path override)

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

**Result (2026-09-04) ⏭️ SKIP**
requires server restart to test cache persistence — pre-approved (SQLite file property, not server)

---

### TC-I22: `set_cache_ttl`/`get_cache_ttl` — runtime TTL change takes effect without restart (issue #99)

**Prompt** (step 0 — record the starting TTL, to restore later)
> "What's the current cache TTL?"

**Prompt** (step 1 — warm the cache, default TTL)
> "List the sheets in {SPREADSHEET_ID}"

**Prompt** (step 2 — lower the TTL at runtime)
> "Set the cache TTL to 3 seconds"

**Prompt** (step 3 — confirm the new TTL is readable back)
> "What's the current cache TTL now?"

**Prompt** (step 4 — confirm the new TTL is honored)
> "Wait 5 seconds, then list the sheets in {SPREADSHEET_ID} again"

**Checks**
- Step 0 returns `{"ttl_seconds": 1800}` (the default, assuming no prior test left it changed)
- Step 2 returns `{"ttl_seconds": 3}`
- Step 3 returns `{"ttl_seconds": 3}` — `get_cache_ttl` reflects the change immediately
- Step 1's call is a cache miss (cold or expired from a prior test) — API fetch, result cached
- Step 4's call is a cache miss too, despite no server restart between steps — confirms the lowered TTL applied to the already-cached entry once evaluated, not just newly stored ones
- Restore the TTL after this test: `"Set the cache TTL to 1800"`

**Result (2026-07-08) ✅ PASS**
Ran all 5 steps live against `TEST_SPREADSHEET_ID`. Step 0: `get_cache_ttl` → `{"ttl_seconds": 1800}`. Step 1: `list_sheets` cache miss, warmed. Step 2: `set_cache_ttl(3)` → `{"ttl_seconds": 3}`; log emitted `WARNING mcp_gee_sweet.tools.cache Cache TTL changed process-wide 1800s -> 3s (affects all concurrent sessions)`. Step 3: `get_cache_ttl` → `{"ttl_seconds": 3}`, immediate readback confirmed. Step 4: after a 5s wait, `list_sheets` again — log showed `Cache TTL expired for <id>, marking dirty` followed by a fresh `Cached 4 sheets`, confirming the lowered TTL applied retroactively to the already-cached entry. Restored TTL to 1800 (`get_cache_ttl` confirmed).

**Result (2026-09-04) ✅ PASS**
Step 0 `get_cache_ttl` → `{"ttl_seconds":1800}`. Step 2 `set_cache_ttl(3)` → `{"ttl_seconds":3}`; log emitted `WARNING mcp_gee_sweet.tools.cache Cache TTL changed process-wide 1800s -> 3s (affects all concurrent sessions)`. Step 3 `get_cache_ttl` → `{"ttl_seconds":3}` (immediate readback). Step 4 (after ~5s wait): log showed `DEBUG mcp_gee_sweet.cache Cache TTL expired for 1dBzY4Wuufx8OtHbQsYO8PQNGV-z5g0Vr_TnKzNCXZYs, marking dirty` then a fresh `list_sheets` 200 — lowered TTL applied retroactively to the already-cached entry, no restart. Restored: `set_cache_ttl(1800)` → `WARNING ... 3s -> 1800s`; `get_cache_ttl` → `{"ttl_seconds":1800}`. (Step-1 cold-miss check not isolatable — entry was already warm from TC-I21 on the shared process; step-4 retroactive-expiry is the load-bearing #99 behavior and is confirmed.)

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

**Result (2026-07-08) ✅ PASS**
Warmed the structure cache via `list_sheets("BrandNew"...)`, then used Playwright to rename the "BrandNew" tab to "BrandNewRenamedQA" directly in the Sheets UI. Immediate `list_sheets` call (no wait, `CACHE_TTL` at default 1800s) returned the new name. Log showed `DEBUG mcp_gee_sweet.cache Source modified since cache for <id>, marking dirty` — the modifiedTime-mismatch path, distinct from the `Cache TTL expired` path — immediately followed by a fresh `Cached 4 sheets`. Renamed back via Playwright; confirmed reverted.

**Supplementary live check (2026-07-08) — cache-poisoning regression from code review, not a scripted TC:** the code review on this PR's first pass (before the `6d4a59b` fix) found that `_get_sheet_id` (backing ~11 write-path tools: `add_rows`, `rename_sheet`, `format_cells`, etc.) called `fetch_sheets()` without `drive_service`, storing the shared structure-cache row with `modified_time=None` — silently disabling staleness detection for *all* subsequent readers of that spreadsheet, including `list_sheets`. Verified the fix closes this end-to-end: `refresh_cache` (cold) → `freeze(sheet="EmptyRenamedQA")` (write-path call, cache MISS/STORE) → renamed "EmptyRenamedQA" back to "Empty" via Playwright → `list_sheets` (read-path, no explicit refresh) immediately returned `"Empty"`, with the log showing `Source modified since cache... marking dirty` right after the write-path's own store. Confirms the write-path cache entry now carries a valid `modified_time`, so it no longer poisons reads by other tools.

TC-I22/TC-I23 (issue #99) are the only mandatory live QA cases for this PR (see `git diff origin/develop...HEAD -- docs/qa/tests/`). No existing test case directly exercises the `_get_sheet_id`/write-path fix or `get_multiple_spreadsheet_summary`'s per-sheet `modified_time` fix — the supplementary check above covers the more severe of the two live; the `get_multiple_spreadsheet_summary` gap is lower-risk (confirmed correct by code trace + unit tests, not independently live-verified here).

**Result (2026-09-04) ⏭️ SKIP**
Requires an edit to the fixture spreadsheet made OUTSIDE this process's tool surface (Playwright tab-rename) to bump Drive modifiedTime without calling mark_dirty. Unsafe this pass: other shards were concurrently issuing `update_cells` against the same fixture (seen in live log), and HARD RULE limits me to `mcp__mcp-gee-sweet-sa__` so I can't use another server process as the external editor either. Unit-tested (tests/test_cache.py modified-time path) + live-passed 2026-07-08.

---

### TC-I24: Concurrent tool calls don't corrupt each other's responses (issue #183)

**Background:** #183 converted the entire tool layer to `async def`, running each Google API call via `asyncio.to_thread()` so multiple calls can execute in real OS threads simultaneously — both within one gather()-restructured tool call and across two separate, simultaneous client requests. The shared `sheets_service`/`drive_service`/etc. objects built once at server startup carry a single `httplib2`-based transport that isn't safe for concurrent use by itself; the fix (`auth.thread_http()`) gives each thread its own transport, built from the shared credentials, passed via `execute(http=...)` at every call site. This is the one thing the mocked unit test suite structurally cannot verify — mocks don't exercise a real shared transport, so a regression here (e.g. someone reverts to the shared service objects' default transport "for simplicity") would pass every unit test and still corrupt live responses under load.

**Setup**
A single client session awaits each tool result before issuing the next, so it cannot hold two requests in flight — running both calls "back-to-back" in one session does **not** produce true concurrency. Run this via the two-subagent `mkdir`-barrier procedure in [`docs/qa/run.md`](../run.md) §"Running true-concurrency test cases": subagent `a` calls `get_sheet_data` on `{SPREADSHEET_ID}` / `Sales!A1:C3`, subagent `b` calls `get_sheet_data` on a **second, distinct** spreadsheet + range with different known values, both released from the barrier together, looped 20–50×.

**Checks**
- On every iteration, `result-a-*` contains only `{SPREADSHEET_ID}`'s data and `result-b-*` only the second spreadsheet's — no row from one appears in the other's file
- No result on any iteration is empty, truncated, or an SSL/connection error (`record layer failure`, `Connection reset by peer`, `Remote end closed connection without response`) — any of these is the signature of the two concurrent `.execute()` calls interfering with a shared transport

**Note:** also implicitly covered by TC-D176/TC-D177/TC-D178/TC-D179/TC-R36/TC-R37 above, each of which forces several genuinely concurrent `.execute()` calls within a single gather()-restructured tool and checks per-item attribution. This case adds the cross-request angle (two separate tool calls, not one batched call) that those don't cover.

**Result (2026-09-04) ✅ PASS**
Two-subagent mkdir-barrier procedure, mcp-gee-sweet-kai-sa, 25 iterations, two distinct spreadsheets. 24/25 (subagent a) and 23/25 (subagent b) valid data points after self-inflicted param-syntax errors in the first 1-2 iterations self-corrected (not transport errors). Every result-a-* held only {SPREADSHEET_ID} data, every result-b-* only the second spreadsheet's — zero cross-contamination across 47 valid calls, zero SSL/connection-error signature (record layer failure / Connection reset by peer / Remote end closed connection). #183 shared-transport fix holds.

---

### TC-I25: `server://auth-status` resource resolves lifespan context (issue #363)

**Background:** Both `server.py` resources previously called `mcp.get_lifespan_context()`, which never existed on `FastMCP` (confirmed absent as far back as `mcp==1.27.1` — not a regression from #350's SDK bump). Every read raised `'FastMCP' object has no attribute 'get_lifespan_context'`. Fixed to use `mcp.get_context().request_context.lifespan_context`, the same path every tool already uses via `ctx.request_context.lifespan_context`. This reproduces the exact regression scenario, not just a happy-path spot check.

**Setup**
Server running with any auth method.

**Action**
Call `ReadMcpResourceTool` with `uri: "server://auth-status"` against this server.

**Checks**
- No `AttributeError` / `'FastMCP' object has no attribute 'get_lifespan_context'`
- Returns valid JSON with `auth_method` matching the server's actual configured auth method

**Result:** ✅ PASS (2026-07-19, mcp-gee-sweet-sky, oauth). `{"auth_method": "oauth", "can_create_in_personal_drive": true, "limited_tools": [], "reason": null}` — no AttributeError, `auth_method` matches configured oauth.

**Note (#447):** the flat `"reason"`/`"alternatives"` fields shown in the Result above no longer exist — see TC-I27 for the current per-limitation `"limitations"` shape. This case's own checks (no AttributeError, `auth_method` matches) are unaffected by that schema change and don't need re-running.

**Note (#175):** the mcp v1→v2 SDK migration replaced the underlying mechanism this case exercises — `MCPServer` (mcp v2) dropped `get_context()` entirely, with no replacement for a static (non-templated) resource like this one (Context injection raises `ValueError` outright there, confirmed live against mcp==2.0.0). `get_auth_status` now reads a process-wide singleton (`auth.get_lifespan_context()`, set once by the lifespan) instead of going through Context at all. The 2026-07-19 Result above proved the old `mcp.get_context()` path worked; it does not prove this new path works against the real SDK.

**Result (2026-08-21, mcp-gee-sweet-sky, oauth, mcp==2.0.0):** ✅ PASS — live re-verification post-#175 migration. `{"auth_method": "oauth", "is_service_account_identity": false, "can_create_in_personal_drive": true, "limited_tools": [], "limitations": []}` — no AttributeError/ValueError, `auth_method` matches configured oauth. Confirms `auth.get_lifespan_context()` resolves the real lifespan-set module state through the actual resource-read protocol against the real SDK, not just against the unit tests' mocked `auth.get_lifespan_context()`.

**Result (2026-09-04) ✅ PASS**
`server://auth-status` read through the real SDK resource dispatch (`MCPServer.read_resource("server://auth-status")`, mcp==2.0.0) inside the real `spreadsheet_lifespan` under `AUTH_METHOD=service_account`: returned valid JSON, no AttributeError/ValueError, `auth_method: "service_account"` matches configured. Exercises the #175/#363 static-resource path (`get_lifespan_context()` singleton, no `get_context()`). Cross-checked: `_auth_status_json("oauth")` full-access branch → `limited_tools:[]`, `limitations:[]`. NOTE: no `ReadMcpResourceTool` in this session, so this is the SDK's in-process `read_resource` dispatch, not a JSON-RPC wire read.

---

### TC-I27: `server://auth-status` reports per-tool limitation categories, not one shared reason (issue #447)

**Background:** `_auth_status_json` used to attach a single `reason`/`alternatives` string to every tool in `_SA_LIMITED_TOOLS`, written specifically around the storage-quota failure class (`create_spreadsheet`, `create_doc`, `copy_file`, the upload tools, `sync_folder`). `transfer_ownership` (#140) fails for a different reason — no personal Drive *identity*, not a quota problem — so it was left off that list entirely rather than get an inaccurate reason attached to it. Fixed by splitting `_SA_LIMITATIONS` into categories, each with its own `tools`/`reason`/`alternatives`, so `limited_tools` (flattened across categories, for a quick membership check) and the new `limitations` array (the categorized detail) both include `transfer_ownership` with text that's actually true for it. `alternatives` for this category deliberately does not mention ADC — see #506, filed alongside this fix, for why ADC can't be assumed to always fix a personal-Drive-identity limitation.

**Setup**
Server running with `AUTH_METHOD=service_account` (e.g. `mcp-gee-sweet-sa` / `mcp-gee-sweet-kai-sa`).

**Action**
Call `ReadMcpResourceTool` with `uri: "server://auth-status"` against that server.

**Checks**
- `limited_tools` includes `"transfer_ownership"` alongside the existing quota-limited tools
- `limitations` is a list of ≥2 entries, each with `category`, `tools`, `reason`, `alternatives`
- The entry with `category: "no_personal_drive_identity"` has `tools == ["transfer_ownership"]`, its `reason` mentions "identity" (not "storage quota"), and its `alternatives` does not mention ADC
- The entry with `category: "no_drive_storage_quota"` still contains the original 7 tools and does not contain `transfer_ownership`
- A full-access auth method (`oauth`/`adc`) still returns `limited_tools: []`, `limitations: []`

**Result (2026-08-04, mcp-gee-sweet-kit, oauth):** ✅ PASS on the full-access check only — `{"auth_method": "oauth", "can_create_in_personal_drive": true, "limited_tools": [], "limitations": []}`. The other four checks are **pending** — they require a `service_account`-authed server, and Kit's own dedicated server (`mcp-gee-sweet-kit`) is OAuth-only; per the team tool-boundary rule, QA doesn't call another role's `mcp-gee-sweet-<other>` server (`kai-sa`, or the standalone `mcp-gee-sweet-sa`) even when visible in the session's tool list. Needs a session with a service-account-authed server (Kai, via `mcp-gee-sweet-kai-sa`) to complete.

**Result (2026-09-04) ✅ PASS**
Same live service_account resource read as TC-I25. All checks: `limited_tools` includes `transfer_ownership`; `limitations` is a 2-entry list, each with category/tools/reason/alternatives; `no_personal_drive_identity` → `tools==["transfer_ownership"]`, reason mentions "identity" (not "storage quota"), alternatives has no ADC mention; `no_drive_storage_quota` → the original 7 tools (create_spreadsheet, create_doc, copy_file, upload_file, upload_local_file, upload_local_folder, sync_folder), excludes transfer_ownership; oauth/full-access branch → `limited_tools:[]`, `limitations:[]`.

---

### TC-I28: `sync_folder` reports as a literal, exact `limited_tools` entry (issue #516)

**Background:** `_SA_LIMITATIONS`'s `no_drive_storage_quota` category carried `sync_folder` as `"sync_folder (upload and bidirectional directions)"` instead of the bare tool name — a string that predates PR #507's per-category restructuring and was carried forward unchanged. This silently defeats the field's own documented contract: a caller doing `"sync_folder" in status["limited_tools"]` (the exact membership check TC-I27's "original 7 tools" check doesn't itself perform literally) got `False` even though `sync_folder` genuinely is restricted under a service account. Fixed by using the bare tool name and moving the upload/bidirectional-only distinction into the category's `reason` text instead.

**Setup**
Server running with `AUTH_METHOD=service_account` (e.g. `mcp-gee-sweet-sa` / `mcp-gee-sweet-kai-sa`).

**Action**
Call `ReadMcpResourceTool` with `uri: "server://auth-status"` against that server.

**Checks**
- `"sync_folder" in limited_tools` is `True` (exact string match — not a substring like `"sync_folder (upload and bidirectional directions)"`)
- The `no_drive_storage_quota` entry's `reason` text mentions the upload/bidirectional-only distinction for `sync_folder`

**Result (2026-08-05, mcp-gee-sweet-sky, oauth):** ✅ PASS on the full-access check only — `{"auth_method": "oauth", "can_create_in_personal_drive": true, "limited_tools": [], "limitations": []}`, confirming no crash/regression under oauth. Both `sync_folder`-specific checks are **pending** — same tool-boundary constraint as TC-I27: they require a `service_account`-authed server, and Sky's own dedicated server (`mcp-gee-sweet-sky`) is OAuth-only, so QA doesn't call `mcp-gee-sweet-kai-sa` (or the standalone `mcp-gee-sweet-sa`) even though visible in the session's tool list. Source inspected directly instead (`src/mcp_gee_sweet/server.py` `_SA_LIMITATIONS`): `no_drive_storage_quota.tools` now contains the bare `"sync_folder"` (no longer the old parenthetical string), and its `reason` ends with "For sync_folder, this only applies to its upload and bidirectional directions." — matches both checks by static read. Unit tests (`tests/test_server.py::TestAuthStatusResource::test_service_account_storage_quota_limitation`) also pass locally. Needs a session with a service-account-authed server (Kai, via `mcp-gee-sweet-kai-sa`) to complete live.

**Result (2026-09-04) ✅ PASS**
Same live service_account resource read. `"sync_folder" in limited_tools` is exact-True (bare name, not the old `"sync_folder (upload and bidirectional directions)"` string). `no_drive_storage_quota` reason text ends: "For sync_folder, this only applies to its upload and bidirectional directions."

---

### TC-I26: `spreadsheet://{id}/info` resource resolves lifespan context (issue #363)

**Background:** Same regression and fix as TC-I25, but for the resource that actually calls the Sheets API (`execute_in_thread` off `context.sheets_service`) — proves the fix works on the `async def` resource path too, not just the sync one.

**Setup**
Server running with any auth method.

**Action**
Call `ReadMcpResourceTool` with `uri: "spreadsheet://{SPREADSHEET_ID}/info"` against this server.

**Checks**
- No `AttributeError` / `'FastMCP' object has no attribute 'get_lifespan_context'`
- Returns valid JSON with `title` and a `sheets` array matching the spreadsheet's actual tabs

**Result:** ✅ PASS (2026-07-19, mcp-gee-sweet-sky, TEST_SPREADSHEET_ID). Returned `title: "mcp-gee-sweet-qa-fixtures"` and 4 sheets (`Sales`, `Notes & Misc`, `BrandNew`, `Empty`) matching the fixture's actual tabs — no AttributeError.

**Note (#175):** the mcp v1→v2 SDK migration changed how this resource reaches the lifespan context. `spreadsheet://{id}/info` is a template resource, and mcp v2 *does* support Context injection there (unlike the static `server://auth-status` resource in TC-I25) — `get_spreadsheet_info` now takes `ctx: Context` as an ordinary injected parameter instead of calling the now-removed `mcp.get_context()`. The 2026-07-19 Result above proved the old path worked; it does not prove this new injected-parameter path works against the real SDK.

**Result (2026-08-21, mcp-gee-sweet-sky, oauth, mcp==2.0.0):** ✅ PASS — live re-verification post-#175 migration, against `mcp-gee-sweet-qa-fixtures` (`15hOwO1Jay26PyxjjYtq9Pq-gEd8lDa81g-C13-GyvCA`). Returned `title: "mcp-gee-sweet-qa-fixtures"` and 4 sheets (`Sales`, `Notes & Misc`, `BrandNew`, `Empty`) matching the fixture's actual tabs — no AttributeError/ValueError. Confirms v2's native `ctx: Context` injection resolves the real lifespan context through the actual resource-read protocol against the real SDK.

**Result (2026-09-04) ⏭️ SKIP**
`spreadsheet://{id}/info` is a template resource; in-process `MCPServer.read_resource(...)` raises `ValueError: Context is not available outside of a request` by design (needs a live MCP request context), and this session has no `ReadMcpResourceTool` to do a real protocol read. Underlying path IS live-healthy: `mcp-gee-sweet-sa`'s `context.sheets_service` + `execute_in_thread` served every Sheets call this shard made. Unit test `tests/test_server.py::TestResourcesReadLifespanContext::test_get_spreadsheet_info_reads_sheets_service_via_injected_context` PASSES on release commit 756eb89; live-passed 2026-08-21 post-#175. Needs a resource-capable conductor session to close live.

---

### TC-I29: `server.json` registry manifest validates and the server is discoverable in the official MCP registry (issue #586)

**Background:** `server.json` at the repo root is a static manifest consumed by the `mcp-publisher` CLI and the official MCP registry (`registry.modelcontextprotocol.io`), not by the running `mcp-gee-sweet` server itself — there's no MCP tool call or prompt that exercises it. Structural consistency against `pyproject.toml`/`README.md` (server name, PyPI package identifier, the `mcp-name` ownership marker) is unit-tested in `tests/test_server_json.py`; this test case covers what only the real CLI and the real registry can confirm: schema validity, PyPI ownership verification via the `mcp-name` marker, and that the publish actually landed.

**Setup**
- `mcp-publisher` CLI installed (`brew install mcp-publisher`, or the curl-and-tar one-liner in the [publishing quickstart](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx)).
- `server.json`'s `packages[].version` (and top-level `version`) matches a version of `mcp-gee-sweet` actually published on PyPI, since ownership verification fetches that exact release's README from PyPI.
- Namespace `io.github.khuisman` authenticated via `mcp-publisher login github` (GitHub device-code flow).

**Action**
1. `mcp-publisher validate server.json` from the repo root.
2. `mcp-publisher publish` from the repo root.
3. `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.khuisman/mcp-gee-sweet"`

**Checks**
- Step 1 reports `server.json is valid`, no schema errors.
- Step 2 succeeds (`✓ Successfully published`) — a failure here most often means the `mcp-name: io.github.khuisman/mcp-gee-sweet` marker isn't present (or isn't on its own line / isn't terminated by a boundary character) in the README of the exact PyPI release `server.json` points at.
- Step 3's JSON response includes a server entry with `name: "io.github.khuisman/mcp-gee-sweet"` and a `version` matching `server.json`.

**Re-run cadence:** every stable release that bumps `server.json`'s `version` to track the new PyPI release — not once-and-done, since a stale `version` there means the registry keeps pointing at an old release.

**Result (2026-09-04) ⏭️ SKIP**
`server.json` registry manifest — not reachable via any MCP tool; needs `mcp-publisher` CLI + a real publish to registry.modelcontextprotocol.io. Identity/consistency unit-tested in tests/test_server_json.py. Re-run only after a stable release that bumps server.json version.

---

### TC-I30: `server://auth-status` distinguishes a real-user ADC session from a service-account-backed one (issue #506)

**Background:** `auth_method == "adc"` alone doesn't say whether `google.auth.default()` resolved to a real user credential (`gcloud auth application-default login`) or a service-account-backed one (a GCE/Cloud Run/GKE attached metadata identity, or `GOOGLE_APPLICATION_CREDENTIALS` pointed at a service account key file) — before this fix, both got tagged plain `"adc"` with `can_create_in_personal_drive: true` and zero limitations, which is wrong for the service-account-backed case. Fixed by `auth.py::_is_service_account_credential` inspecting the resolved credential's actual class (`service_account.Credentials` / `compute_engine.Credentials` → service account; `google.oauth2.credentials.Credentials` → real user) and setting a new `SpreadsheetContext.is_service_account_identity` flag independent of `auth_method`; `_auth_status_json` folds that flag into the same limited branch `auth_method == "service_account"` already takes, and swaps the quota category's `alternatives` text so it doesn't tell an already-ADC caller to "switch to ADC."

**Setup:** two variants, since this needs two different ADC-resolved credential types to compare:
- **User-backed ADC:** same as TC-I11 (`gcloud auth application-default login`, all other auth env vars unset, `AUTH_METHOD=adc`).
- **Service-account-backed ADC:** `GOOGLE_APPLICATION_CREDENTIALS` pointed at a service account key file (or a GCE/Cloud Run/GKE instance with an attached service account identity), `AUTH_METHOD=adc`.

**Action**
Call `ReadMcpResourceTool` with `uri: "server://auth-status"` against each server.

**Checks**
- User-backed ADC: `auth_method: "adc"`, `is_service_account_identity: false`, `can_create_in_personal_drive: true`, `limited_tools: []`, `limitations: []`.
- Service-account-backed ADC: `auth_method: "adc"` (not rewritten to `"service_account"`), `is_service_account_identity: true`, `can_create_in_personal_drive: false`, `limited_tools` includes the same tools a `service_account`-authed server reports (e.g. `create_spreadsheet`, `transfer_ownership`), and the `no_drive_storage_quota` entry's `alternatives` mentions pointing ADC at a real user credential rather than "switch to ADC" (contrast with TC-I27, where a genuine `AUTH_METHOD=service_account` session's `alternatives` still does mention ADC as a real escape hatch).

**Note:** needs an environment where ADC actually resolves to a service-account-backed credential; no team server is currently provisioned that way (Kai's `mcp-gee-sweet-kai-sa`/the standalone `mcp-gee-sweet-sa` both use `AUTH_METHOD=service_account` directly, not ADC). Unit coverage in `tests/test_auth.py::TestIsServiceAccountCredential`/`TestLifespanAuthMethod::test_pinned_adc_*_backed_sets_is_service_account_identity_*` and `tests/test_server.py::TestAuthStatusResource::test_adc_service_account_identity_*` exercises the classification and JSON-shape logic directly against real `google-auth` credential classes in the meantime.

**Result (2026-09-04) ⏭️ SKIP**
Needs an environment where ADC resolves to a service-account-backed credential (AUTH_METHOD=adc + GOOGLE_APPLICATION_CREDENTIALS key file / metadata identity). Running server is `AUTH_METHOD=service_account` directly, not ADC; no such server provisioned. Unit-tested in tests/test_auth.py::TestIsServiceAccountCredential + tests/test_server.py::TestAuthStatusResource.

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

**Result (2026-09-04) ⏭️ SKIP**
requires `--include-tools` CLI restart — pre-approved, unit-tested (_parse_enabled_tools)

---

### TC-I06: ENABLED_TOOLS env var — same behavior as CLI flag

**Setup**
Set `ENABLED_TOOLS=get_sheet_data,list_sheets` and restart the server.

**Prompt**
> "Update cells in {SPREADSHEET_ID}"

**Checks**
- Returns "tool not found" — `update_cells` not registered
- Behavior identical to TC-I05

**Result (2026-09-04) ⏭️ SKIP**
requires ENABLED_TOOLS env + restart — pre-approved, unit-tested

---

### TC-I07: Unlisted tool called by name

**Setup**
Same as TC-I05 or TC-I06 (only 2 tools enabled).

**Prompt**
> "Add a chart to {SPREADSHEET_ID}"

**Checks**
- MCP client returns "tool not found" for `add_chart`
- Server does not crash — just a missing tool, not an error

**Result (2026-09-04) ⏭️ SKIP**
requires tool-filtered server restart — pre-approved, unit-tested

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

**Result (2026-08-21, mcp-gee-sweet-sky, oauth, mcp==2.0.0):** ✅ PASS — re-verified post-#175 migration, since `_enforce_strict_tool_args` reaches into private `ToolManager`/`FuncMetadata`/`arg_model` internals that a major SDK bump could plausibly change shape without any public API signal. `list_sheets(spreadsheet_id=<qa-fixtures id>, bogus_kwarg="test")` raised the identical `1 validation error for list_sheetsArguments\nbogus_kwarg\n  Extra inputs are not permitted [type=extra_forbidden, ...]`; the same call without the bogus kwarg succeeded normally. Confirms the private-internals hack still works unchanged against real mcp==2.0.0.

**Result (2026-09-04) ✅ PASS**
`list_sheets(spreadsheet_id=<fixture>, bogus_kwarg="test")` raised: `1 validation error for list_sheetsArguments / bogus_kwarg / Extra inputs are not permitted [type=extra_forbidden, input_value='test', input_type=str]`. Clean call (spreadsheet_id only) succeeded → `["Sales","Empty","Notes & Misc"]`. Both checks met.

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

**Result (2026-09-04) ⏭️ SKIP**
requires CREDENTIALS_CONFIG-only auth env + restart — pre-approved, unit-tracked (#98)

---

### TC-I09: SERVICE_ACCOUNT_PATH

**Setup**
Set only `SERVICE_ACCOUNT_PATH` (path to service account JSON file). Remove `CREDENTIALS_CONFIG`.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Auth succeeds via `SERVICE_ACCOUNT_PATH`
- Tool returns results normally

**Result (2026-09-04) ⏭️ SKIP**
requires SERVICE_ACCOUNT_PATH-only auth env + restart — pre-approved, unit-tracked (#98). (Note: running server IS service-account-authed via SERVICE_ACCOUNT_PATH and all SA tool calls succeeded this shard.)

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

**Result (2026-09-04) ⏭️ SKIP**
requires OAuth-only auth env + restart — pre-approved

---

### TC-I11: Application Default Credentials (ADC)

**Setup**
Run `gcloud auth application-default login` first. Remove all other auth env vars.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- Auth succeeds via ADC
- Tool returns results normally

**Result (2026-09-04) ⏭️ SKIP**
requires ADC-only auth env + restart — pre-approved, unit-tracked (#98)

---

### TC-I12: No credentials — server fails to start with clear error

**Setup**
Remove all auth env vars. Start the server.

**Checks**
- Server fails to start
- Error message is clear about missing credentials — not an opaque exception
- Server does not start in a broken state and accept connections

**Result (2026-09-04) ⏭️ SKIP**
requires starting server with no creds — pre-approved

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

**Result (2026-08-21, mcp-gee-sweet-sky, oauth, mcp==2.0.0):** ✅ PASS — exercised continuously throughout this PR's #175 QA pass (every tool call in this round, e.g. `list_sheets`, `search_spreadsheets`, ran over this exact stdio connection against real mcp==2.0.0). `list_sheets(spreadsheet_id=<qa-fixtures id>)` returned `["Sales", "Notes & Misc", "BrandNew", "Empty"]` matching the fixture's actual tabs.

**Result (2026-09-04) ⏭️ SKIP**
stdio transport — pre-approved. (Implicitly exercised: this session's entire MCP connection to `mcp-gee-sweet-sa` is stdio; every tool call below rode it. list_sheets returned ["Sales","Empty","Notes & Misc"].)

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

**Result (2026-08-21, mcp-gee-sweet-sky's own worktree code, oauth, mcp==2.0.0):** ✅ PASS — first-recorded live run, and the PR's own regression target for issue #175 (`mcp.sse_app()`/`mcp.run()` moved `host`/`port` from constructor kwargs to call-time kwargs under mcp v2 — see `server.py`'s `app = mcp.sse_app(host=_resolved_host)` and `main()`'s `mcp.run(transport=transport, host=_resolved_host, port=_resolved_port)`). Started `uv run mcp-gee-sweet --transport sse` with `PORT=47031`; connected with the real `mcp` SDK's own `mcp.client.sse.sse_client` + `ClientSession` (not Claude Desktop, but a genuine SSE protocol round trip — `initialize()` then `call_tool()`); `list_sheets(spreadsheet_id=<qa-fixtures id>)` returned `["Sales", "Notes & Misc", "BrandNew", "Empty"]` matching the fixture's actual tabs. Confirms the SSE app construction and transport-kwarg plumbing work end-to-end against the real SDK, not just that `mcp.sse_app()` doesn't raise at import time.

**Result (2026-09-04) ⏭️ SKIP**
SSE transport requires launching a separate `--transport sse` server process — this shard cannot start/reconfigure servers. Live-passed 2026-08-21 post-#175 (real SDK sse_client round trip).

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

**Result (2026-09-04) ✅ PASS**
Live `/tmp/mcp-gee-sweet.log` shows both levels differentiated by logger name: `DEBUG mcp_gee_sweet.cache` (cache open at startup — confirmed via fresh-process run: 5x "sheet_structure/sheet_data/... cache opened: /tmp/mcp_gee_sweet.db"; plus runtime "Cache hit"/"Cache TTL expired" lines) AND `INFO mcp_gee_sweet.access "-" - "TOOL <name>" <status> <elapsed>s`. My own calls logged with exact documented format, e.g. `"-" - "TOOL list_sheets" 200 0.714s`, `"-" - "TOOL get_cache_ttl" 200 0.000s`. Both 200 and 500 statuses seen in the wild.

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

**Result (2026-09-04) ⏭️ SKIP**
Running server is at DEBUG_LEVEL=DEBUG; the INFO-only (no-DEBUG-lines) variant needs an `.env` edit + restart this shard can't perform. Previously live-passed 2026-06-23.

---

### TC-I18: LOG_FILE — server output written to file

**Setup**
Set `DEBUG_LEVEL=DEBUG` and `LOG_FILE=/tmp/mcp-gee-sweet.log`. Restart the server.

**Checks**
- `/tmp/mcp-gee-sweet.log` is created on startup
- `make dev-logs` tails it correctly
- File contains startup cache-open lines and per-call access lines

**Result (2026-06-23) ✅** `/tmp/mcp-gee-sweet.log` created on startup (466 lines after one session). Contains cache-open DEBUG lines and per-call INFO access lines. `make dev-logs` tails it correctly.

**Result (2026-09-04) ✅ PASS**
`LOG_FILE=/tmp/mcp-gee-sweet.log` exists (~297KB), actively appended (mtime = now), contains startup cache-open DEBUG lines + per-call `INFO mcp_gee_sweet.access` lines. `make dev-logs` is a plain `tail -f` of this file — verified the file directly instead.

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

**Result (2026-09-04) ✅ PASS**
`ACCESS_LOG_FILE=/tmp/mcp-gee-sweet-access.log` contains ONLY nginx-style access lines (`<ts> "-" - "TOOL x" <status> <elapsed>s`) — no DEBUG noise, no `INFO mcp_gee_sweet.access` logger prefix. Same call appears once in each file: e.g. my `get_cache_ttl` at 22:31:07 in access log AND in main LOG_FILE (with the `INFO mcp_gee_sweet.access` prefix, alongside DEBUG lines).

---

### TC-I20: .env file loaded at startup

**Setup**
Add `DEBUG_LEVEL=DEBUG` to `src/mcp_gee_sweet/.env` (no shell export, no MCP client config change). Restart the server.

**Checks**
- Debug logging is active without setting the env var in the shell or MCP client
- `make dev-logs` shows startup and access log lines as expected
- 🔍 Set `DEBUG_LEVEL=WARNING` in the shell alongside `DEBUG_LEVEL=DEBUG` in `.env` — shell env wins, no debug output appears

**Result (2026-06-23) ✅** `DEBUG_LEVEL=DEBUG` and `LOG_FILE` set only in `src/mcp_gee_sweet/.env` (no shell export, no MCP client config). Server produced startup DEBUG lines and access log entries — confirms `.env` is loaded at startup. Env precedence test (shell override) pending separate verification.

**Result (2026-09-04) ✅ PASS**
`.mcp.json` sets NO DEBUG_LEVEL/LOG_FILE for any server (only AUTH_METHOD/SERVICE_ACCOUNT_PATH), yet debug+access logging is fully active → `src/mcp_gee_sweet/.env` (main checkout) is loaded at startup by `__init__.py` dotenv. Confirmed `.env` keys: DEBUG_LEVEL=DEBUG, LOG_FILE, ACCESS_LOG_FILE, DRIVE_FOLDER_ID. 🔍 shell-precedence sub-check (shell DEBUG_LEVEL=WARNING overriding .env) NOT executed — needs a restart with a conflicting shell var; recorded PASS per 🔍 rule, that sub-behavior unobserved this run.

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

**Result (2026-09-04) ⏭️ SKIP**
SSE hot-reload — pre-approved, manual/live-only known uvicorn+SSE limitation

---

### TC-I31: `server://auth-status` lists every Gmail tool under a `no_user_mailbox` limitation on a service account (issue #790)

**Background:** #786 added Gmail tools and `docs/auth.md` points users at `server://auth-status` to see which tools won't work on a service account, but `_SA_LIMITATIONS` had no Gmail entry. On a service account (or ADC resolving to one), auth-status reported no Gmail limitation while every Gmail tool failed with a cryptic 400. #790 added a `no_user_mailbox` category.

**Setup**
Server running with `AUTH_METHOD=service_account` (e.g. `mcp-gee-sweet-sa` / `mcp-gee-sweet-kai-sa`), plus any OAuth server for the last check.

**Action**
Call `ReadMcpResourceTool` with `uri: "server://auth-status"` against the service-account server, then against the OAuth server.

**Checks**
- `limitations` contains an entry with `category: "no_user_mailbox"`
- That entry's `tools` is exactly: `list_messages`, `get_message`, `list_threads`, `get_thread`, `list_labels`, `send_message`, `create_draft`, `send_draft`, `reply_to_message`, `modify_labels`, `trash_message` (order not significant)
- All 11 also appear in the flattened `limited_tools`
- The entry's `alternatives` names OAuth and does not mention ADC
- The existing `no_drive_storage_quota` and `no_personal_drive_identity` entries are unchanged (TC-I27)
- On the OAuth server (whose token includes `gmail.modify`; otherwise see TC-I32): `limited_tools: []`, `limitations: []`

---

### TC-I32: a pre-Gmail OAuth token starts the server without Gmail; Gmail tools return the re-authorize error, never a browser consent (issue #790) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** #786 added the Gmail scopes to every auth request. An existing `token.json` was never granted them. Refreshing it with the new scope list returns `invalid_scope` (confirmed live), and the old code then fell into `InstalledAppFlow.run_local_server`: a surprise browser consent, or a hang for a headless/stdio deployment. #790 checks the token's saved `scopes` against what the registered tools need. PR #807's first version then failed startup with `MissingOAuthScopesError`, but QA round 1 found that under a stdio client that error goes to stderr, which the client drops: all the user saw was `Connection closed`. So when **only** the Gmail scope is missing, the server now starts at the token's own granted scopes and every Gmail tool returns the re-authorize message as its tool result. This reproduces the upgrade scenario itself.

**Setup**
- A copy of an OAuth `token.json` whose saved `scopes` lack `https://www.googleapis.com/auth/gmail.modify` but include the four base scopes (`spreadsheets`, `drive`, `calendar`, `drive.activity.readonly`). Any token authorized before #786 qualifies; the team QA token did as of 2026-09-25. Check with: `python3 -c "import json;print(json.load(open('<copy>'))['scopes'])"`. Work on a copy only, never the shared token.
- To exercise the refresh path as well, set the copy's `"expiry"` to `"2000-01-01T00:00:00Z"`.

**Action**
Register this as a temporary stdio MCP server (or run it under an MCP client) with **no** `ENABLED_TOOLS` / `--include-tools` (so the Gmail tools are registered) and `AUTH_METHOD` unset (waterfall):

```
TOKEN_PATH=<copy>
CREDENTIALS_PATH=<oauth client json>
```

Then call, in order:
1. `list_spreadsheets` with `max_results: 1`
2. `list_labels` (no arguments)
3. `send_message` with `to: "nobody@example.com"`, `subject: "TC-I32"`, `body: "should not send"`
4. `ReadMcpResourceTool` with `uri: "server://auth-status"`

**Checks**
- The server connects (no `Connection closed`), with no browser window and no `Please visit this URL to authorize` prompt
- `list_spreadsheets` returns a normal result (the expired token refreshed at its own scopes)
- `list_labels` and `send_message` each return `{"error": ...}` whose text names `https://www.googleapis.com/auth/gmail.modify`, says to run `mcp-gee-sweet auth` with the server's `TOKEN_PATH`/`CREDENTIALS_PATH` and then restart (issue #811; before it, the text said to delete the token file or run `scripts/oauth_setup.py`), and mentions leaving the Gmail tools out of `ENABLED_TOOLS` / `--include-tools`. No message is sent.
- `auth-status` reports `auth_method: "oauth"` and a `limitations` entry with `category: "gmail_not_authorized"` whose `tools` lists all 11 Gmail tools; those 11 are also the whole of `limited_tools`
- The server did **not** start on a service account instead
- The token copy's `scopes` afterwards still lack every `gmail.*` scope

**Cleanup:** remove the temporary server registration and delete the token copy.

**Result (2026-09-25, PR #807 round 2 @ 8f67604, Kit) ✅ PASS**
Ran against this worktree's code with a real `mcp` SDK stdio client (`stdio_client` + `ClientSession`, a genuine MCP round trip) instead of a registered Claude Code server. Token copy = the team QA token as of 2026-09-25 (4 base scopes, no `gmail.modify`), `expiry` forced to 2000-01-01. `AUTH_METHOD` unset, `SERVICE_ACCOUNT_PATH` also set so a silent SA fallback would have been possible, no `ENABLED_TOOLS` (139 tools registered, Gmail included). Server connected; no browser, no `Please visit` prompt. Log: `WARNING mcp_gee_sweet.auth Gmail tools disabled: ...`, then `Refreshing expired OAuth token...`, then `Waterfall: using OAuth` (not the service account). `list_spreadsheets(max_results=1)` → 200, no error (empty list: the fixture folder has no spreadsheets at its root). `list_labels` and `send_message(to=nobody@example.com, ...)` each returned `{"error": "The OAuth token at '<copy>' wasn't authorized for scope(s) the enabled tools require: https://www.googleapis.com/auth/gmail.modify. Delete '<copy>' and restart the server (or run scripts/oauth_setup.py) to re-authorize. The Gmail tools are what need them: to run without Gmail instead, leave the Gmail tools out of ENABLED_TOOLS / --include-tools."}` in 0.000s (no API call, nothing sent). `auth-status`: `auth_method: "oauth"`, one `gmail_not_authorized` limitation listing all 11 Gmail tools, and those 11 are the whole of `limited_tools`. Token copy afterwards: `expiry` advanced (refresh succeeded), `scopes` unchanged with no `gmail.*`.

---

### TC-I33: with the Gmail tools filtered out, a pre-Gmail OAuth token keeps working and no Gmail scope is requested (issue #790) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** #790 requests Gmail's mailbox scope only when a Gmail tool is registered. An `ENABLED_TOOLS` filter without Gmail tools must neither require nor request it, so an existing pre-Gmail token keeps working after the upgrade with no re-consent.

**Setup**
Same token copy as TC-I32 (saved `scopes` lack `gmail.modify`). To exercise the refresh path as well, set the copy's `"expiry"` to `"2000-01-01T00:00:00Z"`.

**Action**
Register this as a temporary stdio MCP server (or run it under an MCP client) with:

```
TOKEN_PATH=<copy>
CREDENTIALS_PATH=<oauth client json>
AUTH_METHOD=oauth
ENABLED_TOOLS=list_spreadsheets,get_cache_ttl
```

Call `list_spreadsheets` with `max_results: 1`, then `ReadMcpResourceTool` with `uri: "server://auth-status"`.

**Checks**
- The server starts with no browser consent and no `MissingOAuthScopesError`
- `list_spreadsheets` returns a normal result (the expired token refreshed successfully)
- The token copy's `scopes` afterwards still lack every `gmail.*` scope (nothing extra was requested on refresh)
- `auth-status` reports `auth_method: "oauth"`, `limited_tools: []`

**Cleanup:** remove the temporary server registration and delete the token copy.

**Result (2026-09-25, PR #807 round 2 @ 8f67604, Kit) ✅ PASS**
Same real-SDK stdio client; separate token copy (4 base scopes, `expiry` forced to 2000-01-01), `AUTH_METHOD=oauth`, `ENABLED_TOOLS=list_spreadsheets,get_cache_ttl`. Connected with 2 tools registered (no Gmail) and no browser consent. `list_spreadsheets(max_results=1)` → 200, no error. `auth-status`: `auth_method: "oauth"`, `limited_tools: []`, `limitations: []`. Token copy afterwards: `expiry` advanced (refreshed), `scopes` still the 4 base scopes, no `gmail.*`. Log has 0 `Gmail`/`MissingOAuth` lines.

---

### TC-I34: an OAuth token missing a base (non-Gmail) scope still fails at startup, logs the reason, and never opens a browser consent (issue #790) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** TC-I32's degrade only covers a Gmail-only shortfall. A token missing one of the base scopes can't serve most tools, so startup still stops with `MissingOAuthScopesError`, and the waterfall does not swallow it into a silent service-account fallback. Because stdio clients drop stderr, the error is also logged through the package logger so `LOG_FILE` captures it.

**Setup**
A copy of a full OAuth `token.json`, hand-edited so its saved `scopes` list omits `https://www.googleapis.com/auth/calendar` (leave `expiry` in the future so no refresh happens). Work on a copy only, never the shared token.

**Action**
From the repo checkout under test, with `AUTH_METHOD` unset (waterfall), a service account also configured if available, and no `ENABLED_TOOLS`:

```bash
TOKEN_PATH=<copy> CREDENTIALS_PATH=<oauth client json> DEBUG_LEVEL=DEBUG LOG_FILE=<tmp log> uv run mcp-gee-sweet < /dev/null
```

Repeat once with `AUTH_METHOD=oauth`.

**Checks**
- The process exits on its own with a non-zero status within a few seconds (no hang), and no browser window or `Please visit this URL to authorize` prompt appears
- stderr contains `MissingOAuthScopesError` with a message naming `https://www.googleapis.com/auth/calendar` and telling you to run `mcp-gee-sweet auth` and then restart (issue #811; before it, the text said to delete the token file or run `scripts/oauth_setup.py`)
- `<tmp log>` contains an `OAuth startup failed:` line with the same message
- Waterfall run: no `Waterfall: using service account` line
- The token copy's contents are unchanged afterwards

**Cleanup:** delete the token copy and the temp log.

**Result (2026-09-25, PR #807 round 2 @ 8f67604, Kit) ✅ PASS**
Token copy: `calendar` removed from `scopes` (`spreadsheets`, `drive`, `drive.activity.readonly`, `gmail.modify` kept), `expiry` in the future. Waterfall run (`AUTH_METHOD` unset, `SERVICE_ACCOUNT_PATH` set): exit 1 after ~2s. stderr has `MissingOAuthScopesError: The OAuth token at '<copy>' wasn't authorized for scope(s) the enabled tools require: https://www.googleapis.com/auth/calendar. Delete '<copy>' and restart the server (or run scripts/oauth_setup.py) ...`. LOG_FILE has `ERROR mcp_gee_sweet.auth OAuth startup failed: <same message>`, 0 `Waterfall: using service account` lines, 0 `Please visit` prompts. `AUTH_METHOD=oauth` run: identical (exit 1 after ~2s, same stderr + log line). Token copy's sha1 unchanged across both runs.

---

### TC-I35: stdio with no token starts without Google access; tools return the `mcp-gee-sweet auth` instructions, never a browser consent (issue #811) ⚠️ local-filesystem

**Background:** with no usable token, `_oauth_creds` used to call `InstalledAppFlow.run_local_server` inside the lifespan. Under stdio that blocked startup with no timeout, `print()`ed the "Please visit this URL" prompt onto stdout (the JSON-RPC channel), and the client gave up (`CONNECT_TIMEOUT` after 30s in Claude Code). #811 turns the in-server consent off for stdio. With `AUTH_METHOD=oauth`, the server starts without Google services, and every tool raises the authorize instructions.

**Setup**
- An OAuth client JSON (`CREDENTIALS_PATH`). No user token is needed; any client JSON works, since no consent runs.
- A `TOKEN_PATH` that does not exist, in a directory that does. A missing parent directory fails the pre-consent writability check instead, which under SSE (TC-I38, TC-I40) degrades before any prompt is printed.

**Action**
Run the server under a real MCP stdio client (e.g. the `mcp` SDK's `stdio_client` + `ClientSession`), with `DEBUG_LEVEL=DEBUG` and `LOG_FILE=<tmp log>`:

```
AUTH_METHOD=oauth
TOKEN_PATH=<nonexistent path>
CREDENTIALS_PATH=<oauth client json>
BROWSER=/usr/bin/true
```

Then call `list_spreadsheets` with `max_results: 1`, and read `server://auth-status`.

**Checks**
- `initialize` completes within a few seconds, with no browser window and no `Please visit` text (the stdio stream stays valid JSON-RPC)
- `list_spreadsheets` returns an error result whose text says there's no usable OAuth token at `<nonexistent path>`, and tells you to run `mcp-gee-sweet auth` (and `uvx mcp-gee-sweet auth` for a PyPI install) with the same `TOKEN_PATH`/`CREDENTIALS_PATH`/`ENABLED_TOOLS`, then restart
- `auth-status` reports `auth_method: "none"`, `limited_tools: ["*"]`, and one `oauth_not_authorized` limitation
- `<tmp log>` has a `WARNING ... Starting without Google access:` line and a `"TOOL list_spreadsheets" 401` access line
- `<nonexistent path>` still does not exist

**Cleanup:** delete the temp log.

**Result (2026-09-26, PR #828 round 1 @ 69d6dbf, Sky) ✅ PASS**
Real `mcp` SDK `stdio_client` + `ClientSession`. `initialize` OK in 1.9s, 0 `Please visit` in stderr or LOG_FILE. `list_spreadsheets` returned an error result: `No usable OAuth token at '<nonexistent>', and this server can't ask for consent itself over the stdio transport. To authorize, run \`mcp-gee-sweet auth\` in a terminal (\`uvx mcp-gee-sweet auth\` for a PyPI install) with the same TOKEN_PATH (...), CREDENTIALS_PATH (...) and ENABLED_TOOLS as this server, then restart the server.` `auth-status`: `auth_method: "none"`, `limited_tools: ["*"]`, one `oauth_not_authorized` limitation. LOG_FILE has `WARNING mcp_gee_sweet.auth Starting without Google access: ...` and `"TOOL list_spreadsheets" 401`. The token path's parent dir was never created.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
Same as round 1: `initialize` 1.8s, error result with the instructions (now ending `then restart the server or reconnect to it.`), `auth-status` `none` / `oauth_not_authorized`, `"TOOL list_spreadsheets" 401`, 0 `Please visit`. Gate now reads the connection's own `lifespan_context.unauthorized_message`.

---

### TC-I36: stdio waterfall with no token falls through to a service account, and starts without access only if nothing else works (issue #811) ⚠️ local-filesystem

**Background:** in the waterfall, OAuth needing consent is a reason to try the service account and ADC, not to fail. If neither is available, the OAuth client JSON on disk shows OAuth was the intended method, so the server starts without access and reports the OAuth instructions, rather than failing with "All authentication methods failed" (which a stdio client would only see as `Connection closed`).

**Setup:** same as TC-I35, plus the team service-account key file for run 1.

**Action**
Run 1 (`AUTH_METHOD` unset, `SERVICE_ACCOUNT_PATH=<SA key>`): call `list_spreadsheets` with `max_results: 1`, then read `server://auth-status`.
Run 2 (`AUTH_METHOD` unset, `SERVICE_ACCOUNT_PATH=<nonexistent>`, `CREDENTIALS_CONFIG` empty, `GOOGLE_APPLICATION_CREDENTIALS=<nonexistent>`): same calls.

**Checks**
- Run 1: `list_spreadsheets` returns a normal result; `auth-status` reports `auth_method: "service_account"`; the log has `Waterfall: OAuth needs consent` then `Waterfall: using service account`
- Run 2: same outcome as TC-I35 (error result with the `mcp-gee-sweet auth` instructions, `auth_method: "none"`)
- Neither run shows a browser window or a `Please visit` prompt

**Cleanup:** none.

**Result (2026-09-26, PR #828 round 1 @ 69d6dbf, Sky) ✅ PASS**
Run 1 (team SA key): `initialize` 1.7s, `list_spreadsheets` normal result (`is_error=False`), `auth-status` `auth_method: "service_account"`; log has `Waterfall: OAuth needs consent (...), trying service account` then `Waterfall: using service account`. Run 2 (SA/ADC paths nonexistent, `CREDENTIALS_CONFIG` empty): same outcome as TC-I35 (error result with the `mcp-gee-sweet auth` instructions, `auth_method: "none"`, `401` access line); log has `Waterfall: ADC unavailable (File <nonexistent> was not found.)` then the `Starting without Google access` warning. 0 `Please visit` in either run.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
Run 1: `list_spreadsheets` normal, `auth_method: "service_account"`, `OAuth needs consent` → `using service account`. Run 2: degraded as TC-I35; the warning now ends `The fallbacks weren't usable either: no service account key file at SERVICE_ACCOUNT_PATH ('<nonexistent>'); ADC failed (File <nonexistent> was not found.).` Extra probe (not a check here): a *malformed* SA key file or `CREDENTIALS_CONFIG` still fails startup outright (stdio client sees `Connection closed`) with the SA exception, since the waterfall's SA step has no try, same as before this PR. That's not masking, so it's not a finding.

---

### TC-I37: `mcp-gee-sweet auth` writes a token a stdio server then uses (issue #811) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** `scripts/oauth_setup.py` isn't in the wheel, so a PyPI/`uvx` user had no way to authorize except restarting the server and completing a consent flow they might not see. #811 adds the `mcp-gee-sweet auth` subcommand. It runs the consent for the scopes the registered tools need and overwrites `TOKEN_PATH`.

**Setup**
- The team OAuth client JSON (`CREDENTIALS_PATH`) and a scratch `TOKEN_PATH` that does not exist yet.
- Playwright to complete the consent page (see `docs/qa/playwright_oauth.md`), respecting the Playwright mutex in `docs/qa/run.md`.

**Action**
1. In a terminal: `TOKEN_PATH=<scratch> CREDENTIALS_PATH=<client json> ENABLED_TOOLS=list_spreadsheets uv run mcp-gee-sweet auth --no-browser`
2. Navigate Playwright to the printed URL and complete the consent.
3. Start a stdio server with the same three env vars and `AUTH_METHOD=oauth`; call `list_spreadsheets` with `max_results: 1`.
4. Deny path: delete `<scratch>`, rerun step 1, and on the consent page click **Cancel** / deny instead of allowing.

**Checks**
- Step 1 prints `Credentials :`, `Token target:` and `Scopes :` lines. The scopes are the four base scopes only, with no `gmail.modify` (the `ENABLED_TOOLS` filter narrows them), followed by a `Please visit this URL` line with an `accounts.google.com` URL
- After consent, the command prints `Saved the token to <scratch>` and exits 0; `<scratch>` exists, its `scopes` list the four base scopes, and its mode is `0600` (`stat -f %Lp <scratch>` on macOS, `stat -c %a` on Linux prints `600`)
- Step 3's `list_spreadsheets` returns a normal result, and `auth-status` reports `auth_method: "oauth"`
- Step 4: the command exits 1 with a single `ERROR: ...` line on stderr naming the denial (e.g. `access_denied`), no Python traceback, and `<scratch>` is not created
- With a nonexistent `CREDENTIALS_PATH`, `mcp-gee-sweet auth` exits 1 with `ERROR: ... not found` on stderr

**Cleanup:** delete `<scratch>`, and revoke the scratch grant at https://myaccount.google.com/permissions if it created a separate entry.

**Result (2026-09-26, PR #828 round 1 @ 69d6dbf, Sky) ⏳ PARTIAL — consent steps deferred to the fix round**
Step 1 (killed before consent): printed `Credentials :`, `Token target:`, `Scopes      :` with the four base scopes only (no `gmail.modify`), then `Please visit this URL to authorize this application: https://accounts.google.com/o/oauth2/auth?...`; no token written. Error case: nonexistent `CREDENTIALS_PATH` exited 1 with `ERROR: '<path>' not found. Set CREDENTIALS_PATH or provide credentials.json.` on stderr. Steps 2–3 (Playwright consent, then a stdio server using the new token) not run this round: `run_auth_command` changes in the round-1 send-back (code-review findings 4/5/10 on PR #828), so the consent path is re-run against the fixed code. Also observed live (finding 5): `mcp-gee-sweet --include-tools list_spreadsheets auth --no-browser` skipped the auth branch entirely (no `Credentials :` line) and started a stdio MCP server instead.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
Playwright signed-in check passed (fixture doc title). Step 1: `Credentials :` / `Token target:` / `Scopes      :` (4 base scopes, no `gmail.modify`) + `Please visit` URL. Step 2: chose the Workspace fixture account, Allow → callback `?state=...&code=...&scope=<4 base scopes>`. Command printed `Saved the token to <scratch>. Restart the server to pick it up.`, exit 0; `stat -f %Lp` = `600`; token `scopes` = the 4 base scopes. Step 3: stdio `list_spreadsheets` normal result, `auth-status` `auth_method: "oauth"`, no limitations. Step 4 (deny): Cancel → callback `?error=access_denied`; exit 1, stderr `ERROR: AccessDeniedError: (access_denied) `, 0 `Traceback`, no token file. Same OAuth client + account as the existing grant, so no separate permissions entry to revoke.

---

### TC-I38: over SSE, a missing token still runs the consent flow, with its prompt on stderr only (issue #811) ⚠️ local-filesystem

**Background:** an SSE server has no protocol traffic on stdout, but #811 still moves the consent prompt to stderr, and bounds the wait at 5 minutes (`OAUTH_CONSENT_TIMEOUT_SECONDS`). On a timeout, the server starts without access, the same way TC-I35 does (see TC-I40 for that path).

**Setup:** same as TC-I35.

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `AUTH_METHOD=oauth`, `TOKEN_PATH=<nonexistent>`, `CREDENTIALS_PATH=<client json>`, `BROWSER=/usr/bin/true`, `PORT=<free port>`, `PYTHONUNBUFFERED=1`, with stdout and stderr redirected to separate files. Open `http://127.0.0.1:<port>/sse` to trigger the lifespan, wait a few seconds, then send the server `SIGTERM` (since #833 it stops the server during the consent wait; TC-I43 covers that).

**Checks**
- The stdout file has no `Please visit` line. It may hold uvicorn access-log lines (`"GET /sse HTTP/1.1" 200`): since #833 the event loop keeps serving while the consent waits, and uvicorn logs access to stdout
- The stderr file contains `Please visit this URL to authorize this application: https://accounts.google.com/...`

**Cleanup:** make sure nothing is still listening on `<port>` (`lsof -i :<port>`).

**Result (2026-09-26, PR #828 round 1 @ 69d6dbf, Sky) ✅ PASS**
stdout file 0 bytes. stderr has `Please visit this URL to authorize this application: https://accounts.google.com/o/oauth2/auth?...` (full scope set incl. `gmail.modify`, redirect to a random localhost port), after the uvicorn startup lines and `AUTH_METHOD=oauth`. Process group SIGKILLed; `lsof -i :<port>` empty afterward.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
stdout 0 bytes; stderr has the `Please visit ... https://accounts.google.com/o/oauth2/auth?...` prompt; port released. (A first attempt with `TOKEN_PATH` under a nonexistent directory printed no prompt: the new pre-consent writability check degraded with `the browser consent failed (RuntimeError: The directory for TOKEN_PATH ... doesn't exist...)`, and later connections logged `an earlier browser consent in this server process didn't complete`. Correct behavior; the Setup now says the parent directory must exist.)

**Result (2026-10-01, PR #867 round 1 @ 9f34468, Sky) ✅ PASS**
Stopped with SIGTERM, not SIGKILL. stdout had 0 `Please visit` lines, only uvicorn access lines (`GET /sse 200`, `POST /messages/ 202`). stderr had `Please visit this URL to authorize this application: https://accounts.google.com/...`. Server exited on SIGTERM and the port was released.

---

### TC-I39: `mcp-gee-sweet auth` argument handling and pre-consent checks (issue #811) ⚠️ local-filesystem

**Background:** PR #828 QA round 1 found that `auth` was only recognized as the first argument. `mcp-gee-sweet --include-tools X auth` started a stdio server instead, although `docs/auth.md` documents `--include-tools` as narrowing the scopes. Unknown flags were silently ignored. A missing `TOKEN_PATH` directory also only failed *after* the consent, losing the refresh token the user had just granted.

**Setup:** any OAuth client JSON (no consent is completed), a scratch directory.

**Action** (each with `CREDENTIALS_PATH=<client json>`, `BROWSER=/usr/bin/true`, stdin from `/dev/null`)
1. `TOKEN_PATH=<scratch>/t.json uv run mcp-gee-sweet --include-tools list_spreadsheets auth --no-browser`: kill it once the URL is printed
2. `uv run mcp-gee-sweet auth --no-browswer` (typo intended)
3. `TOKEN_PATH=<scratch>/no-such-dir/t.json uv run mcp-gee-sweet auth --no-browser`
4. `uv run mcp-gee-sweet --include-tools auth` with `AUTH_METHOD=oauth TOKEN_PATH=<scratch>/t.json`: kill it after a few seconds (a tool named `auth` is a value here, not the subcommand)

**Checks**
- 1: prints `Credentials :`, a `Scopes :` line with the four base scopes only, and a `Please visit this URL` line. It's the auth command, not a server
- 2: exits 2 with `mcp-gee-sweet auth: error: unrecognized arguments: --no-browswer`
- 3: exits 1 with `ERROR: RuntimeError: The directory for TOKEN_PATH (...) doesn't exist. Create it first.`, and no `Please visit` line (it fails before the consent starts)
- 4: no `Credentials :` line; the process runs as a stdio server (with stdin from `/dev/null` it exits on EOF right away, so the evidence is the lifespan's `Starting without Google access` line on stderr, not the process staying alive)
- No run leaves a token file behind in `<scratch>`

**Cleanup:** delete `<scratch>`.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
1: `Credentials :`, `Scopes      :` with the 4 base scopes, `Please visit` URL (the auth command, not a server). 2: exit 2, `mcp-gee-sweet auth: error: unrecognized arguments: --no-browswer`. 3: exit 1, `ERROR: RuntimeError: The directory for TOKEN_PATH ('<scratch>/no-such-dir/t.json') doesn't exist. Create it first.`, 0 `Please visit`, 0 `Traceback`. 4: 0 `Credentials :` lines; stderr has `WARNING mcp_gee_sweet.auth Starting without Google access: ...` (a stdio server's lifespan), exited on stdin EOF. No token file left in `<scratch>`.

---

### TC-I40: SSE with no token: one consent attempt per process, per-connection state, and any consent failure degrades (issue #811) ⚠️ local-filesystem

**Background:** mcp v2 runs the lifespan once per SSE connection. PR #828 round 1 kept the degraded state in a process-wide global and re-ran the blocking consent on every connection. A second connection cleared the message the first one relied on, and each attempt blocked every session for the full timeout. Only a timeout degraded; a stray request to the callback port (or a Deny) failed the lifespan outright. Now the state lives on each connection's context, and the consent is attempted at most once per process. After that, connections re-read `TOKEN_PATH`. Any consent failure degrades. `OAUTH_CONSENT_TIMEOUT_SECONDS` shortens the wait for this test.

**Setup:** same as TC-I35. A small script using the `mcp` SDK's `sse_client` + `ClientSession`.

**Action**
Run 1: start `uv run mcp-gee-sweet --transport sse` with `AUTH_METHOD=oauth`, `TOKEN_PATH=<nonexistent>`, `CREDENTIALS_PATH=<client json>`, `BROWSER=/usr/bin/true`, `PORT=<free port>`, `OAUTH_CONSENT_TIMEOUT_SECONDS=4`, stderr to a file, in its own process group.
1. Open connection A, `initialize`, call `list_spreadsheets` with `max_results: 1`
2. While A stays open, open connection B, `initialize`, call the same tool, and close B
3. Call the tool on A again

Run 2: restart the server the same way. Open a connection (its `initialize` blocks on the consent). While it waits, read the callback port from the `redirect_uri=http%3A%2F%2Flocalhost%3A<port>` in the stderr file, and send `GET http://localhost:<port>/?state=bogus&code=x`.

**Checks**
- Run 1, A: opening the connection takes about 4s (the lifespan, and so the consent wait, runs when the SSE stream opens, before `initialize`); the tool error says the browser consent wasn't completed within 4s and gives the `mcp-gee-sweet auth` instructions
- Run 1, B: the connection opens and initializes in well under a second (no second consent wait); the tool error says an earlier browser consent in this server process didn't complete
- Run 1, step 3: A's error still says `within 4s` (B didn't overwrite it)
- Run 1: the stderr file has exactly one `Please visit` prompt
- Run 2: the connection initializes right after the stray request (no 4s wait), and its tool error says `the browser consent failed` with the `mcp-gee-sweet auth` instructions. The lifespan doesn't crash.

**Cleanup:** SIGTERM each server (it exits within a few seconds, #833); confirm `lsof -i :<port>` is empty.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
`mcp` SDK `sse_client`. Run 1: A opened (≈4s consent wait inside the SSE connect; `initialize` itself 0.0s) → error `...the browser consent wasn't completed within 4s. To authorize, run \`mcp-gee-sweet auth\`...`. B (A still open): connected + initialized 0.00s → `...an earlier browser consent in this server process didn't complete (it isn't retried, since waiting for it blocks every connection)`. A again: still `within 4s`. stderr: exactly 1 `Please visit`. Run 2: stray `GET http://localhost:<cb>/?state=bogus&code=x` fired while the connection was opening; connect+init finished 0.02s after it, tool error `...the browser consent failed (MismatchingStateError: (mismatching_state) CSRF Warning! State not equal in request and response.). To authorize, run \`mcp-gee-sweet auth\`...`; lifespan didn't crash. `lsof -i :<port>` empty after both.

**Result (2026-10-01, PR #867 round 1 @ 9f34468, Sky) ✅ PASS**
`mcp` SDK `sse_client`. Run 1: A open+init 4.09s; tool error `...the browser consent wasn't completed within 4s. To authorize, run \`mcp-gee-sweet auth\`...`. B (A still open) open+init 0.01s; error `...an earlier browser consent in this server process didn't complete (it isn't retried, so new connections don't each wait for it again)`. A again: still `within 4s`. stderr had exactly 1 `Please visit`. Run 2: init 0.01s after the stray `GET /?state=bogus&code=x`; error `...the browser consent failed (MismatchingStateError: ...)`, and the lifespan didn't crash. SIGTERM exits took 0.28s each, and `lsof -i :<port>` was empty after both.

**Result (2026-10-01, PR #867 round 2 @ a4c18c9, Sky) ✅ PASS**
Same as round 1. Run 1: A open+init 4.09s with `within 4s`; B 0.01s with `an earlier browser consent ... didn't complete`; A again still `within 4s`; 1 `Please visit`. Run 2: init 0.01s after the stray request; `the browser consent failed (MismatchingStateError ...)`. SIGTERM exits 0.17s / 0.23s, and `lsof` was empty.

**Result (2026-10-01, PR #867 round 3 @ de28f97, Sky) ✅ PASS**
Run 1: A 4.10s with `within 4s`; B 0.01s with `an earlier browser consent ... didn't complete`; A again still `within 4s`; 1 `Please visit`. Run 2: init 0.01s after the stray request, `the browser consent failed (MismatchingStateError ...)`. SIGTERM exits 0.24s / 0.24s. (Run 1's `lsof -i :<port>` matched an unrelated macOS process, `PowerChime`, on the same port number over IPv6. That was port reuse, not the server.)

**Result (2026-10-01, PR #867 round 5 @ b306ce0, Sky) ✅ PASS**
Run 1: A 4.08s with `within 4s`; B 0.01s with `an earlier browser consent ... didn't complete`; A again still `within 4s`; 1 `Please visit`. Run 2: init 0.01s after the stray request, `the browser consent failed`. SIGTERM exits 0.29s / 0.27s, and `lsof` was empty.

---

### TC-I41: the Stop hook warns a lane session once its context passes the threshold, once per band (issue #847) ⚠️ local-filesystem

**Background:** `.claude/settings.json` runs `scripts/lane_context_hook.py` on every `Stop`. Inside a lane worktree (`.claude/worktrees/{ash,jay,sky,kit}`) it sums the latest main-thread assistant message's `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` from the session's own `transcript_path`. Past `LANE_CONTEXT_WARN_TOKENS` (default `DEFAULT_WARN_TOKENS` in the script) it shows a `systemMessage` suggesting `/clear` + `/team-member <Name>`. It warns again only after each further `LANE_CONTEXT_WARN_STEP` (default `DEFAULT_WARN_STEP`) tokens, tracked per session under `$TMPDIR/mcp-gee-sweet-lane-context/`. Other cwds get no output. The env vars lower the threshold so a fresh session crosses it.

**Setup:** this lane's worktree checked out on the PR branch (`.claude/settings.json` there carries the hook). `<scratch>` is a fresh empty directory used as `TMPDIR`.

**Action** (all from the lane worktree root)
1. `LANE_CONTEXT_WARN_TOKENS=1000 LANE_CONTEXT_WARN_STEP=10000000 TMPDIR=<scratch> claude -p "Reply with just: ok" --model haiku --output-format stream-json --verbose --include-hook-events > <scratch>/s1.jsonl`. Note the `session_id` from its `init` line.
2. Same env, `claude -p "Reply with just: ok again" --resume <session_id> --model haiku --output-format stream-json --verbose --include-hook-events > <scratch>/s2.jsonl`
3. Pipe a hand-built Stop payload into the script with a non-lane cwd: `echo '{"hook_event_name":"Stop","cwd":"<repo root>/.claude/worktrees/bob","session_id":"x","transcript_path":"<step 1 transcript>"}' | LANE_CONTEXT_WARN_TOKENS=1000 TMPDIR=<scratch> python3 scripts/lane_context_hook.py`. The step 1 transcript is `~/.claude/projects/<lane worktree path, with / and . replaced by ->/<session_id>.jsonl`.

**Checks**
- Step 1: a `hook_response` line with `"hook_event":"Stop"`, `exit_code` 0 and empty `stderr`, whose `output` is a `systemMessage` starting `Lane context is ~<N>k tokens (warning threshold 1k)` and ending `/clear, then /team-member <Lane>.` (this lane's name, capitalized). `<N>k` matches the step 1 `assistant` line's `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, rounded to thousands. An `informational` line shows the same text as `Stop says: ...`.
- Step 2: the Stop `hook_response` has an empty `output` (same band, so no second warning), and there's no `Stop says:` line.
- Step 3: no output, exit 0.

**Cleanup:** remove `<scratch>`. The headless sessions stay in this lane's transcript directory.

**Result (2026-10-01, PR #866 round 1 @ 9e649ac, Kit) ✅ PASS**
Claude Code 2.1.287, `kit` worktree. Step 1: Stop `hook_response` exit 0, empty `stderr`, `output` `{"systemMessage": "Lane context is ~41k tokens (warning threshold 1k). ... start fresh: /clear, then /team-member Kit."}`; the `assistant` line's three usage fields sum to 41019; `informational` line `Stop says: Lane context is ~41k tokens ...`. State file under `<scratch>/mcp-gee-sweet-lane-context/` held `0`. Step 2 (`--resume`): Stop `output` empty, no `Stop says:` line (`SessionStart:resume` also empty, since no `LANE_RESUME_WARN_TOKENS` override). Step 3 (`cwd` = `.../worktrees/bob`): no output, exit 0.

**Result (2026-10-01, PR #866 round 2 @ 3cf654a, Kit) ✅ PASS**
Re-ran step 1 against the guarded settings.json command: Stop `hook_response` exit 0 with `Lane context is ~39k tokens (warning threshold 1k). ... /clear, then /team-member Kit.` and one `Stop says:` line. Round 1 finding (missing script): a scratch project whose Stop hook uses the same guarded command with no `scripts/lane_context_hook.py` now gives exit 0, `outcome: "success"`, empty output and stderr (round 1's unguarded command: exit 2, `outcome: "error"`, `can't open file`).

---

### TC-I42: resuming a large lane session whose prompt cache has expired warns before the first request (issue #847) ⚠️ local-filesystem

**Background:** on `SessionStart` with source `resume` or `fork`, Claude Code (2.1.251+) passes `context_tokens`, `prompt_cache_likely_expired` and `estimated_cache_write_usd`. The hook warns when the cache has likely expired and `context_tokens` is at least `LANE_RESUME_WARN_TOKENS` (default `DEFAULT_RESUME_WARN_TOKENS` in the script). A warm-cache resume stays silent. `--fork-session` leaves the original transcript untouched; the hook sees it as `SessionStart:fork`.

**Setup:** pick a session in this lane's transcript directory last modified more than 2 hours ago (cache expired), with a small context so the test is cheap. `<scratch>` as in TC-I41.

**Action** (from the lane worktree root)
1. `LANE_RESUME_WARN_TOKENS=1000 TMPDIR=<scratch> claude -p "Reply with just: ok" --resume <old session_id> --fork-session --model haiku --output-format stream-json --verbose --include-hook-events > <scratch>/r1.jsonl`
2. Immediately repeat step 1 against the session step 1 forked (its `session_id` from `r1.jsonl`'s `init` line), so the cache is warm.

**Checks**
- Step 1: a `hook_response` line with `"hook_name":"SessionStart:fork"`, exit 0, whose `output` is a `systemMessage` starting `Resuming a ~<N>k-token lane session with an expired prompt cache` and containing a `(~$<cost>)` clause and `/clear, then /team-member <Lane>`.
- Step 2: the SessionStart `hook_response` has an empty `output` (cache not expired).

**Cleanup:** remove `<scratch>`.

**Result (2026-10-01, PR #866 round 1 @ 9e649ac, Kit) ✅ PASS**
Claude Code 2.1.287, `kit` worktree. Old session: a ~43k-token `kit` transcript last modified 2026-09-29. Step 1: `hook_name` `SessionStart:fork`, exit 0, `output` `{"systemMessage": "Resuming a ~43k-token lane session with an expired prompt cache: the first request re-writes all of it (~$0.34). If this session's ticket is done or between rounds, /clear, then /team-member Kit is cheaper."}`. Step 2 (fork of step 1's fork, seconds later): `SessionStart:fork` `output` empty.

**Result (2026-10-01, PR #866 round 2 @ 3cf654a, Kit) ✅ PASS**
Re-ran step 1 (same 2026-09-29 session) after the `type(cost) in (int, float)` change: `SessionStart:fork` exit 0, `output` `Resuming a ~43k-token lane session with an expired prompt cache: the first request re-writes all of it (~$0.34). ... /clear, then /team-member Kit is cheaper.` The cost clause, which round 1's `int | float` check dropped under Python 3.9, is present. `tests/test_lane_context_hook.py::TestRunsUnderPython39` ran (not skipped) against `/usr/bin/python3` 3.9.6. All 46 tests in the file pass. Step 2 not re-run: the warm-cache path is unchanged by the fix.

---

### TC-I43: SSE consent wait doesn't stall other connections, and SIGTERM stops the server (issue #833) ⚠️ local-filesystem

**Background:** the consent wait used to run on the event loop. Until consent or `OAUTH_CONSENT_TIMEOUT_SECONDS` (default 300), every other request stalled, and SIGTERM didn't stop the server (uvicorn waits for open connections, and this one couldn't finish), so QA had to SIGKILL it. The wait now runs on a daemon thread that the lifespan awaits. Connections that arrive during the wait share it (one prompt, one callback port). On SIGTERM, a waiting lifespan starts the connection degraded with a "server shut down" message, and the callback server closes.

**Setup:** same as TC-I35. A small script using the `mcp` SDK's `sse_client` + `ClientSession`.

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `AUTH_METHOD=oauth`, `TOKEN_PATH=<nonexistent>`, `CREDENTIALS_PATH=<client json>`, `BROWSER=/usr/bin/true`, `PORT=<free port>`, `OAUTH_CONSENT_TIMEOUT_SECONDS=120`, `DEBUG_LEVEL=INFO`, `PYTHONUNBUFFERED=1`, stderr to a file, in its own process group.
1. Open connection A (`sse_client`); its connect blocks on the consent. Leave it waiting
2. While A waits, time `POST http://127.0.0.1:<port>/messages/?session_id=00000000000000000000000000000000` with body `{}`
3. While A waits, open connection B the same way and leave it waiting too
4. Read the callback port from `redirect_uri=http%3A%2F%2Flocalhost%3A<cb>` in the stderr file
5. Send the server process `SIGTERM` (not SIGKILL, and not the process group) and time how long it takes to exit

**Checks**
- 2: the POST answers `404` (no such session) in well under a second (before #833: no answer until the consent ended)
- 3: the stderr file has exactly one `Please visit` prompt (B shares A's consent instead of starting a second one)
- 5: the server exits within a few seconds (before #833: it kept running until the 120s timeout)
- 5: the stderr file has `Starting without Google access: ... the server shut down before the browser consent completed`
- 5: `lsof -i :<port>` and `lsof -i :<cb>` are both empty afterward

An `Exception in ASGI application ... Expected ASGI message 'http.response.body', but got 'http.response.start'` traceback during shutdown isn't a failure of this case: any SSE stream open at SIGTERM produces it, with or without a consent wait (pre-existing, seen on `develop` before #833).

**Cleanup:** if the server is still running, SIGKILL its process group and record the case as failed.

**Result (2026-10-01, PR #867 round 1 @ 9f34468, Sky) ✅ PASS**
`mcp` SDK `sse_client`, `OAUTH_CONSENT_TIMEOUT_SECONDS=120`. Step 2: POST answered `404` in 0.016s. The case said `400`, but an unknown all-zero session id is 404; corrected above. Step 3: exactly 1 `Please visit`. Step 5: SIGTERM to the server pid exited in 4.6s; stderr has `...the server shut down before the browser consent completed`; `lsof` empty for both `<port>` and `<cb>`. A and B both ended with `Connection closed` (expected: the server exited). Probe outside the case (PR comment, finding 1): with `OAUTH_CONSENT_TIMEOUT_SECONDS=4` and a silent TCP connection held open on `<cb>`, A was still waiting after 20s and resolved only once the silent connection closed. SIGTERM still exits (0.56s) because the consent thread is a daemon.

**Result (2026-10-01, PR #867 round 2 @ a4c18c9, Sky) ✅ PASS**
Step 2: POST `404` in 0.017s. Step 3: 1 `Please visit`. Step 5: SIGTERM exit in 0.61s, the shut-down message was logged, and `lsof` was empty for `<port>` and `<cb>`. Re-checked the round-1 findings outside the case. (1) Silent TCP connection on `<cb>` with `OAUTH_CONSENT_TIMEOUT_SECONDS=4`: degraded at 5.2s (`within 4s`) and the stderr had 0 tracebacks. (2) Waterfall (`AUTH_METHOD` unset, `SERVICE_ACCOUNT_PATH` set, timeout 4s), two sequential connections: 1 `Please visit` in total, and both connections ran on the service account. (3) Token refresh hanging (expired token, `HTTPS_PROXY` pointed at a blackhole): a POST during it answered in 0.017s, and SIGTERM exited in 0.6s with `the server shut down while loading the token`. Separately, with `AUTH_METHOD=oauth` and a token missing required scopes (`MissingOAuthScopesError`), SIGTERM intermittently hung at `Waiting for background tasks to complete` past 30s: 3 of 39 runs on the PR code, 0 of 14 on `develop`. Reported on the PR.

**Result (2026-10-01, PR #867 round 3 @ de28f97, Sky) ✅ PASS**
Step 2: POST `404` in 0.015s. Step 3: 1 `Please visit`. Step 5: SIGTERM exit 0.60s, the shut-down message was logged, and `lsof` was empty for both ports. The round-1/2 probes still hold: a silent connection on `<cb>` degrades at 5.2s; the waterfall shows 1 prompt across two connections; with the refresh hanging, a POST answers in 0.018s and SIGTERM exits in 0.56s with `shut down while loading the token`.

**Result (2026-10-01, PR #867 round 5 @ b306ce0, Sky) ✅ PASS**
Step 2: `404` in 0.013s. Step 3: 1 `Please visit`. Step 5: SIGTERM exit 0.65s, the shut-down message was logged, and `lsof` was empty for both ports. The earlier probes still pass: a silent `<cb>` connection degrades at 5.2s; the waterfall shows 1 prompt across two connections; with the refresh hanging, a POST answers in 0.017s and SIGTERM exits in 0.44s. All four states of the shared consent attempt were checked with standalone scripts against the real `_oauth_creds_async`. **Running:** joins it (`test_concurrent_connections_share_one_consent`). **Failed:** consent-off error, no new attempt. **Succeeded, with a token load in flight across the success:** that load re-reads the token, 1 consent in total; `18c839e` ran 2. **Succeeded, then the token deleted:** a new consent runs, as intended. **Stopped (the last waiter cancelled):** the next connection starts a new attempt and gets creds.

---

### TC-I44: over SSE, an auth failure starts the connection without Google access, and SIGTERM still exits (PR #867) ⚠️ local-filesystem

**Background:** once the token load moved off the event loop (#833), a lifespan that raised (e.g. `MissingOAuthScopesError`) did so after the SSE `endpoint` event had gone out. A client that POSTs `initialize` the instant it sees the endpoint got `202`, and that POST then waited forever in mcp's transport, because the session's stream is never closed when the lifespan fails (python-sdk#3616). SIGTERM then hung at `Waiting for background tasks to complete`. Over SSE, an auth failure now starts the connection without Google access, and every tool returns the failure as its error. Stdio still exits on it (#790).

**Setup:** an OAuth client JSON, and a token file `<scratch>/token.json` whose `scopes` is only `["https://www.googleapis.com/auth/drive"]` (any `token`/`refresh_token`/`client_id`/`client_secret`, with an `expiry` in the future so no refresh is attempted).

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `AUTH_METHOD=oauth`, `TOKEN_PATH=<scratch>/token.json`, `CREDENTIALS_PATH=<client json>`, `PORT=<free port>`, `DEBUG_LEVEL=INFO`, `PYTHONUNBUFFERED=1`, stderr to a file, in its own process group.
1. With the `mcp` SDK's `sse_client` + `ClientSession`: `initialize`, then call `list_spreadsheets` with `max_results: 1`
2. The race, 10 times against a fresh server each time: open `GET /sse` on a raw socket, and the moment the `endpoint` event's `session_id` arrives, `POST /messages/?session_id=<id>` with an `initialize` request. Wait 0.5s, then send the server `SIGTERM` and time its exit
3. Restart the same way with `AUTH_METHOD` unset and no service account or ADC configured; repeat step 1

**Checks**
- 1: `initialize` succeeds. The tool result is an error that names the missing scopes (`wasn't authorized for scope(s) the enabled tools require: ...`) and gives the `mcp-gee-sweet auth` instructions
- 1: the stderr file has `ERROR mcp_gee_sweet.auth Starting without Google access: The OAuth token at ...`
- 2: every POST answers `202`, and every server exits within a few seconds of SIGTERM (before this fix: hung every time)
- 3: the tool error is the missing-scopes message again (a token on disk means OAuth was intended, so #790 still doesn't fall through to another method)

**Cleanup:** SIGKILL any server process group still running (and record the case as failed); delete `<scratch>`.

**Result (2026-10-01, PR #867 round 3 @ de28f97, Sky) ✅ PASS**
Step 1: `initialize` OK; the tool error is `The OAuth token at ... wasn't authorized for scope(s) the enabled tools require: ...`, and the stderr has the `ERROR mcp_gee_sweet.auth Starting without Google access: The OAuth token at` line. SIGTERM exit 0.23s. Step 2: 10 of 10 POSTs answered `202`, and SIGTERM exited in 0.49–0.56s every time. Control: the same raw-socket race against round 2's `a4c18c9` hung 3 of 3, so the case does exercise the bug. Step 3 (`AUTH_METHOD` unset): same missing-scopes error, SIGTERM exit 0.12s. Also checked: stdio with the same token still exits (code 1, missing-scopes error on stderr, empty stdout), per #790.

**Result (2026-10-01, PR #867 round 5 @ b306ce0, Sky) ✅ PASS**
Step 1: missing-scopes tool error plus the `ERROR ... Starting without Google access` line; SIGTERM 0.23s. Step 2: 10 of 10 POSTs `202`, SIGTERM 0.50–0.60s. Step 3: same error, SIGTERM 0.18s. Stdio with the same token still exits with code 1.

---

### TC-I45: on mcp 2.3+, a degraded start's `mcp-gee-sweet auth` instructions reach the client (issue #872) ⚠️ local-filesystem

**Background:** from mcp 2.3, `Tool.run` withholds the text of any exception that isn't a `ToolError`/`ResourceError`/`MCPError`. The client sees only `Error executing tool <name>`. The degraded-start `OAuthConsentRequiredError` (#811) is a `RuntimeError`, so a PyPI/`uvx` install (which resolved mcp 2.3.0 while `uv.lock` still pinned 2.0.0) hid the authorize instructions entirely. `_timed` now re-raises it as a `ToolError`. This is TC-I35's scenario with an expired token whose refresh fails, the way it was observed live.

**Setup**
- Confirm the server's environment has mcp 2.3 or later: `uv run python -c "import importlib.metadata as m; print(m.version('mcp'))"`.
- A scratch OAuth client JSON (any `installed` client; bogus `client_id`/`client_secret` are fine).
- A scratch token file whose `scopes` lists every scope in `auth.SCOPES` plus `GMAIL_SCOPES`, with a bogus `refresh_token` and an `expiry` in the past, so the startup refresh fails.

**Action**
Run the server under a real MCP stdio client (the `mcp` SDK's `stdio_client` + `ClientSession`) with:

```
AUTH_METHOD=oauth
TOKEN_PATH=<scratch token>
CREDENTIALS_PATH=<scratch client json>
ENABLED_TOOLS=get_storage_quota
```

Call `get_storage_quota` with no arguments.

**Checks**
- The result has `is_error: true`, and its text is `Error executing tool get_storage_quota: No usable OAuth token at '<scratch token>' ...`, followed by the `mcp-gee-sweet auth` / `uvx mcp-gee-sweet auth` instructions naming the same `TOKEN_PATH` and `CREDENTIALS_PATH`
- The text is not only `Error executing tool get_storage_quota`

**Cleanup:** delete the scratch files.

**Result (2026-10-04, PR #905 round 1 @ da73f20, Sky) ✅ PASS**
mcp 2.3.0. Startup refresh failed (`invalid_client`) and the server started degraded. `get_storage_quota` returned `is_error: True` with `Error executing tool get_storage_quota: No usable OAuth token at '<scratch token>' ...`, followed by the `mcp-gee-sweet auth` / `uvx mcp-gee-sweet auth` instructions naming the scratch `TOKEN_PATH` and `CREDENTIALS_PATH`. Access line: `"TOOL get_storage_quota" 401`. Scratch files deleted.

**Result (2026-10-04, PR #905 round 2 @ 42ab5e6, Sky) ✅ PASS**
Same as round 1 after the degraded start began raising `ToolError` directly: `is_error: True`, identical `mcp-gee-sweet auth` text, access line `401`.

---

### TC-I46: on mcp 2.3+, a Google API error a tool raises keeps its text, for a tool and for `spreadsheet://{id}/info` (issue #872)

**Background:** most tools catch `HttpError` and return `{"error": ...}`, but some let it propagate (e.g. `list_sheets`, whose return type is a list). From mcp 2.3 that text was withheld, so a bad ID or a permission problem reached the client as a bare `Error executing tool list_sheets`. `_timed` now re-raises Google API, auth, network, `ValueError` and `OSError` failures as `ToolError` with their own text. `get_spreadsheet_info` does the same with `ResourceError`. Any other exception is still a crash: mcp withholds its text and logs the traceback.

**Setup:** a server running this branch's code on mcp 2.3 or later, with working credentials (any auth method).

**Action**
1. Call `list_sheets` with `spreadsheet_id: "bogus-spreadsheet-id-872"`
2. Read the resource `spreadsheet://bogus-spreadsheet-id-872/info`

**Checks**
- 1: an error result whose text starts `Error executing tool list_sheets: <HttpError 404 when requesting https://sheets.googleapis.com/v4/spreadsheets/bogus-spreadsheet-id-872` and contains `Requested entity was not found.`
- 2: the read fails with a protocol error whose message contains `Requested entity was not found.`, not only `Error creating resource from template spreadsheet://bogus-spreadsheet-id-872/info`

**Cleanup:** none.

**Result (2026-10-04, PR #905 round 1 @ da73f20, Sky) ✅ PASS**
Live `mcp-gee-sweet-sky` server, OAuth, mcp 2.3.0. 1: `Error executing tool list_sheets: <HttpError 404 when requesting https://sheets.googleapis.com/v4/spreadsheets/bogus-spreadsheet-id-872?fields=... returned "Requested entity was not found.". ...>`. 2: the resource read failed with `<HttpError 404 when requesting https://sheets.googleapis.com/v4/spreadsheets/bogus-spreadsheet-id-872?alt=json returned "Requested entity was not found.". ...>`, not the bare template error.

**Result (2026-10-04, PR #905 round 2 @ 42ab5e6, Sky) ✅ PASS**
Live `mcp-gee-sweet-sky` server, mcp 2.3.0: steps 1 and 2 return the same `HttpError 404 ... Requested entity was not found.` text as round 1. Extra check over a stdio subprocess with the same credentials (`DEBUG_LEVEL=INFO`): the server logs `WARNING mcp_gee_sweet.server Reporting HttpError to the client: ...` with the full traceback through `execute_in_thread`, and the access line is `"TOOL list_sheets" 500`.
