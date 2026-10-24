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
| TC-I66 (single publish workflow, issue #1124) | Not reachable via any MCP tool or unit test: it checks a GitHub Actions run and PyPI's attestation record. Manual / live QA only, once after #1124 merges and once at the next stable release — see TC-I66 below |
| TC-I67 (socket timeout and resumable-upload 308, issue #1129) | Unit-tested in `tests/test_http_transport.py` (`TestSocketTimeout`, `TestResumableUploadStatus`) against local sockets that never answer or answer 308. Live QA for the real Drive upload path over 100 MB and the configured server's timeout message — see TC-I67 below |

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a CACHE_TTL/CACHE_DB_PATH change or a restart.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Two-subagent barrier, 20/20 iterations: every write succeeded, every concurrent read returned data, 0 "database is locked" in the log.

---

### TC-I03: CACHE_DB_PATH env var respected

**Setup**
Set `CACHE_DB_PATH=/tmp/qa_test_cache.db` and restart the server.

**Prompt**
> "List the sheets in {SPREADSHEET_ID}"

**Checks**
- File `/tmp/qa_test_cache.db` is created (check with `ls /tmp/qa_test_cache.db`)
- The default path (`mcp-gee-sweet/cache.db` in the user's cache directory; `/tmp/mcp_gee_sweet.db` before 0.9.3) is NOT used
- Restore `CACHE_DB_PATH` to default after this test

**Result (2026-09-04) ⏭️ SKIP**
requires CACHE_DB_PATH env + restart — pre-approved, unit-tested (tests/test_cache.py db_path override)

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a CACHE_TTL/CACHE_DB_PATH change or a restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a CACHE_TTL/CACHE_DB_PATH change or a restart.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

**Result (2026-10-20) ⚠️ PARTIAL — v0.9.3 post-advisory re-check @ c90b88d3**
`kai-sa` (service account): step 0 → 1800; step 1 was a hit (warmed by TC-S23), so its miss check couldn't be seen; `set_cache_ttl(3)` → 3 with the process-wide warning; readback 3; after 5 s `Cache TTL expired for <copy>, marking dirty` and a re-fetch. Restored to 1800.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Two-subagent barrier, 20/20 iterations on kai-sa: no cross-contamination, no SSL/connection errors (server pre-warmed to rule out the stale-connection defect).

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-08-04, mcp-gee-sweet-kit, oauth):** ⚠️ PARTIAL on the full-access check only — `{"auth_method": "oauth", "can_create_in_personal_drive": true, "limited_tools": [], "limitations": []}`. The other four checks are **pending** — they require a `service_account`-authed server, and Kit's own dedicated server (`mcp-gee-sweet-kit`) is OAuth-only; per the team tool-boundary rule, QA doesn't call another role's `mcp-gee-sweet-<other>` server (`kai-sa`, or the standalone `mcp-gee-sweet-sa`) even when visible in the session's tool list. Needs a session with a service-account-authed server (Kai, via `mcp-gee-sweet-kai-sa`) to complete.
**Corrected (2026-10-17, #1044 audit):** only the full-access check ran; the other four were pending.

**Result (2026-09-04) ✅ PASS**
Same live service_account resource read as TC-I25. All checks: `limited_tools` includes `transfer_ownership`; `limitations` is a 2-entry list, each with category/tools/reason/alternatives; `no_personal_drive_identity` → `tools==["transfer_ownership"]`, reason mentions "identity" (not "storage quota"), alternatives has no ADC mention; `no_drive_storage_quota` → the original 7 tools (create_spreadsheet, create_doc, copy_file, upload_file, upload_local_file, upload_local_folder, sync_folder), excludes transfer_ownership; oauth/full-access branch → `limited_tools:[]`, `limitations:[]`.

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
SA checks pass; the OAuth sub-check needs a different auth method.

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

**Result (2026-08-05, mcp-gee-sweet-sky, oauth):** ⚠️ PARTIAL on the full-access check only — `{"auth_method": "oauth", "can_create_in_personal_drive": true, "limited_tools": [], "limitations": []}`, confirming no crash/regression under oauth. Both `sync_folder`-specific checks are **pending** — same tool-boundary constraint as TC-I27: they require a `service_account`-authed server, and Sky's own dedicated server (`mcp-gee-sweet-sky`) is OAuth-only, so QA doesn't call `mcp-gee-sweet-kai-sa` (or the standalone `mcp-gee-sweet-sa`) even though visible in the session's tool list. Source inspected directly instead (`src/mcp_gee_sweet/server.py` `_SA_LIMITATIONS`): `no_drive_storage_quota.tools` now contains the bare `"sync_folder"` (no longer the old parenthetical string), and its `reason` ends with "For sync_folder, this only applies to its upload and bidirectional directions." — matches both checks by static read. Unit tests (`tests/test_server.py::TestAuthStatusResource::test_service_account_storage_quota_limitation`) also pass locally. Needs a session with a service-account-authed server (Kai, via `mcp-gee-sweet-kai-sa`) to complete live.
**Corrected (2026-10-17, #1044 audit):** only the full-access check ran; both `sync_folder` checks were pending.

**Result (2026-09-04) ✅ PASS**
Same live service_account resource read. `"sync_folder" in limited_tools` is exact-True (bare name, not the old `"sync_folder (upload and bidirectional directions)"` string). `no_drive_storage_quota` reason text ends: "For sync_folder, this only applies to its upload and bidirectional directions."

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs the mcp-publisher CLI and a registry publish.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an ADC-backed SA environment.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a tool-filtered restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a tool-filtered restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a tool-filtered restart.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a different auth environment and a restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a different auth environment and a restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a different auth environment and a restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a different auth environment and a restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a different auth environment and a restart.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an SSE/streamable-http server or SIGTERM.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs DEBUG_LEVEL=INFO and a restart.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

---

### TC-I20: .env file loaded at startup

**Setup**
Add `DEBUG_LEVEL=DEBUG` to `src/mcp_gee_sweet/.env` (no shell export, no MCP client config change). Restart the server.

**Checks**
- Debug logging is active without setting the env var in the shell or MCP client
- `make dev-logs` shows startup and access log lines as expected
- 🔍 Set `DEBUG_LEVEL=WARNING` in the shell alongside `DEBUG_LEVEL=DEBUG` in `.env` — shell env wins, no debug output appears

**Result (2026-06-23) ✅** `DEBUG_LEVEL=DEBUG` and `LOG_FILE` set only in `src/mcp_gee_sweet/.env` (no shell export, no MCP client config). Server produced startup DEBUG lines and access log entries — confirms `.env` is loaded at startup. Env precedence test (shell override) pending separate verification.

**Result (2026-09-04) ⚠️ PARTIAL**
`.mcp.json` sets NO DEBUG_LEVEL/LOG_FILE for any server (only AUTH_METHOD/SERVICE_ACCOUNT_PATH), yet debug+access logging is fully active → `src/mcp_gee_sweet/.env` (main checkout) is loaded at startup by `__init__.py` dotenv. Confirmed `.env` keys: DEBUG_LEVEL=DEBUG, LOG_FILE, ACCESS_LOG_FILE, DRIVE_FOLDER_ID. 🔍 shell-precedence sub-check (shell DEBUG_LEVEL=WARNING overriding .env) NOT executed — needs a restart with a conflicting shell var; recorded PASS per 🔍 rule, that sub-behavior unobserved this run.
**Corrected (2026-10-17, #1044 audit):** the shell-precedence sub-check wasn't run.

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
.env values are active with no .mcp.json override; shell precedence needs a restart.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an SSE/streamable-http server or SIGTERM.

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

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
SA checks pass; the OAuth sub-check needs a different auth method.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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
- `list_spreadsheets` returns an error result whose text says there's no usable OAuth token at `<nonexistent path>`. Since #873 (a client with no elicitation callback, as here) the text then gives a `https://accounts.google.com/...` consent link, and the alternative of running `mcp-gee-sweet auth` (and `uvx mcp-gee-sweet auth` for a PyPI install) with the same `TOKEN_PATH`/`CREDENTIALS_PATH`/`ENABLED_TOOLS`, then retrying the call. It no longer says to restart.
- `auth-status` reports `auth_method: "none"`, `limited_tools: ["*"]`, and one `oauth_not_authorized` limitation
- `<tmp log>` has a `WARNING ... Starting without Google access:` line and a `"TOOL list_spreadsheets" 401` access line
- `<nonexistent path>` still does not exist

**Cleanup:** delete the temp log.

**Result (2026-09-26, PR #828 round 1 @ 69d6dbf, Sky) ✅ PASS**
Real `mcp` SDK `stdio_client` + `ClientSession`. `initialize` OK in 1.9s, 0 `Please visit` in stderr or LOG_FILE. `list_spreadsheets` returned an error result: `No usable OAuth token at '<nonexistent>', and this server can't ask for consent itself over the stdio transport. To authorize, run \`mcp-gee-sweet auth\` in a terminal (\`uvx mcp-gee-sweet auth\` for a PyPI install) with the same TOKEN_PATH (...), CREDENTIALS_PATH (...) and ENABLED_TOOLS as this server, then restart the server.` `auth-status`: `auth_method: "none"`, `limited_tools: ["*"]`, one `oauth_not_authorized` limitation. LOG_FILE has `WARNING mcp_gee_sweet.auth Starting without Google access: ...` and `"TOOL list_spreadsheets" 401`. The token path's parent dir was never created.

**Result (2026-09-26, PR #828 round 2 @ f633c4c, Sky) ✅ PASS**
Same as round 1: `initialize` 1.8s, error result with the instructions (now ending `then restart the server or reconnect to it.`), `auth-status` `none` / `oauth_not_authorized`, `"TOOL list_spreadsheets" 401`, 0 `Please visit`. Gate now reads the connection's own `lifespan_context.unauthorized_message`.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ✅ PASS**
`initialize` 1.9s, 0 `Please visit` in the log. `list_spreadsheets` error text: `No usable OAuth token at '<nonexistent>'. To re-authorize, open this link in a browser and approve access within <N>s, then retry the call: https://accounts.google.com/o/oauth2/auth?...`, then `Or run \`mcp-gee-sweet auth\` ... (\`uvx mcp-gee-sweet auth\` ...) ... then retry the call: the server picks up the new token without a restart.` No restart instruction in the tool text. `auth-status`: `none`, `["*"]`, one `oauth_not_authorized`. The log has `Starting without Google access:` and `"TOOL list_spreadsheets" 401`. The token path still doesn't exist. (`auth-status`'s own `reason`/`alternatives` still say `then restart the server or reconnect to it`, which is review finding 9, not this case's check.)

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
`initialize` 1.7s, 0 `Please visit`. `list_spreadsheets`: `No usable OAuth token at '<nonexistent>'.`, then the link, then the CLI alternative ending `then retry the call: the server picks up the new token without a restart.`. No restart wording. `auth-status` `none` / `["*"]` / one `oauth_not_authorized`. The log has `Starting without Google access:` and `"TOOL list_spreadsheets" 401`. The token path still doesn't exist.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Claude Code hook tests need headless claude -p from a lane worktree.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Claude Code hook tests need headless claude -p from a lane worktree.

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

An `Exception in ASGI application ... Expected ASGI message 'http.response.body', but got 'http.response.start'` traceback during shutdown isn't a failure of this case. Any SSE stream open at SIGTERM used to produce it, with or without a consent wait (pre-existing, seen on `develop` before #833). Fixed in #868, which TC-I47 covers.

**Cleanup:** if the server is still running, SIGKILL its process group and record the case as failed.

**Result (2026-10-01, PR #867 round 1 @ 9f34468, Sky) ✅ PASS**
`mcp` SDK `sse_client`, `OAUTH_CONSENT_TIMEOUT_SECONDS=120`. Step 2: POST answered `404` in 0.016s. The case said `400`, but an unknown all-zero session id is 404; corrected above. Step 3: exactly 1 `Please visit`. Step 5: SIGTERM to the server pid exited in 4.6s; stderr has `...the server shut down before the browser consent completed`; `lsof` empty for both `<port>` and `<cb>`. A and B both ended with `Connection closed` (expected: the server exited). Probe outside the case (PR comment, finding 1): with `OAUTH_CONSENT_TIMEOUT_SECONDS=4` and a silent TCP connection held open on `<cb>`, A was still waiting after 20s and resolved only once the silent connection closed. SIGTERM still exits (0.56s) because the consent thread is a daemon.

**Result (2026-10-01, PR #867 round 2 @ a4c18c9, Sky) ✅ PASS**
Step 2: POST `404` in 0.017s. Step 3: 1 `Please visit`. Step 5: SIGTERM exit in 0.61s, the shut-down message was logged, and `lsof` was empty for `<port>` and `<cb>`. Re-checked the round-1 findings outside the case. (1) Silent TCP connection on `<cb>` with `OAUTH_CONSENT_TIMEOUT_SECONDS=4`: degraded at 5.2s (`within 4s`) and the stderr had 0 tracebacks. (2) Waterfall (`AUTH_METHOD` unset, `SERVICE_ACCOUNT_PATH` set, timeout 4s), two sequential connections: 1 `Please visit` in total, and both connections ran on the service account. (3) Token refresh hanging (expired token, `HTTPS_PROXY` pointed at a blackhole): a POST during it answered in 0.017s, and SIGTERM exited in 0.6s with `the server shut down while loading the token`. Separately, with `AUTH_METHOD=oauth` and a token missing required scopes (`MissingOAuthScopesError`), SIGTERM intermittently hung at `Waiting for background tasks to complete` past 30s: 3 of 39 runs on the PR code, 0 of 14 on `develop`. Reported on the PR.

**Result (2026-10-01, PR #867 round 3 @ de28f97, Sky) ✅ PASS**
Step 2: POST `404` in 0.015s. Step 3: 1 `Please visit`. Step 5: SIGTERM exit 0.60s, the shut-down message was logged, and `lsof` was empty for both ports. The round-1/2 probes still hold: a silent connection on `<cb>` degrades at 5.2s; the waterfall shows 1 prompt across two connections; with the refresh hanging, a POST answers in 0.018s and SIGTERM exits in 0.56s with `shut down while loading the token`.

**Result (2026-10-01, PR #867 round 5 @ b306ce0, Sky) ✅ PASS**
Step 2: `404` in 0.013s. Step 3: 1 `Please visit`. Step 5: SIGTERM exit 0.65s, the shut-down message was logged, and `lsof` was empty for both ports. The earlier probes still pass: a silent `<cb>` connection degrades at 5.2s; the waterfall shows 1 prompt across two connections; with the refresh hanging, a POST answers in 0.017s and SIGTERM exits in 0.44s. All four states of the shared consent attempt were checked with standalone scripts against the real `_oauth_creds_async`. **Running:** joins it (`test_concurrent_connections_share_one_consent`). **Failed:** consent-off error, no new attempt. **Succeeded, with a token load in flight across the success:** that load re-reads the token, 1 consent in total; `18c839e` ran 2. **Succeeded, then the token deleted:** a new consent runs, as intended. **Stopped (the last waiter cancelled):** the next connection starts a new attempt and gets creds.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an SSE/streamable-http server or SIGTERM.

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

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an SSE/streamable-http server or SIGTERM.

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
- The result has `is_error: true`, and its text is `Error executing tool get_storage_quota: No usable OAuth token at '<scratch token>' ...`, followed by the `mcp-gee-sweet auth` / `uvx mcp-gee-sweet auth` instructions naming the same `TOKEN_PATH` and `CREDENTIALS_PATH`. Since #873 a consent link comes before those instructions (see TC-I48–TC-I52); this case only checks that the text reaches the client.
- The text is not only `Error executing tool get_storage_quota`

**Cleanup:** delete the scratch files.

**Result (2026-10-04, PR #905 round 1 @ da73f20, Sky) ✅ PASS**
mcp 2.3.0. Startup refresh failed (`invalid_client`) and the server started degraded. `get_storage_quota` returned `is_error: True` with `Error executing tool get_storage_quota: No usable OAuth token at '<scratch token>' ...`, followed by the `mcp-gee-sweet auth` / `uvx mcp-gee-sweet auth` instructions naming the scratch `TOKEN_PATH` and `CREDENTIALS_PATH`. Access line: `"TOOL get_storage_quota" 401`. Scratch files deleted.

**Result (2026-10-04, PR #905 round 2 @ 42ab5e6, Sky) ✅ PASS**
Same as round 1 after the degraded start began raising `ToolError` directly: `is_error: True`, identical `mcp-gee-sweet auth` text, access line `401`.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ✅ PASS**
mcp 2.3.0, bogus scratch client JSON, expired token with a bogus refresh token. `get_storage_quota`: `is_error: True`, text starts `Error executing tool get_storage_quota: No usable OAuth token at '<scratch token>'.`, then the consent link (built from the bogus client ID), then the `mcp-gee-sweet auth` / `uvx mcp-gee-sweet auth` alternative naming the scratch `TOKEN_PATH` and `CREDENTIALS_PATH`. Not the bare `Error executing tool get_storage_quota`.

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
mcp 2.3.0. Same as round 1: `is_error: True`, starts `Error executing tool get_storage_quota: No usable OAuth token at '<scratch token>'.`, with the `mcp-gee-sweet auth` / `uvx mcp-gee-sweet auth` alternative naming the scratch paths. Not the bare text.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (sa); resource reads via an mcp SDK stdio client with the slot's config.

---

### TC-I47: SIGTERM with an SSE stream open shuts down without an ASGI traceback (issue #868) ⚠️ local-filesystem

**Background:** on SIGTERM, sse_starlette cancels an open SSE stream without sending its closing chunk, and mcp's `/sse` endpoint then returns an empty `Response()` on the same connection. uvicorn rejected that second response with `Exception in ASGI application ... RuntimeError: Expected ASGI message 'http.response.body', but got 'http.response.start'` on every shutdown with a stream open, and the client saw a truncated chunked stream. `SingleResponseGuard` (`sse_shutdown.py`) now closes the cut-off stream and drops the late second response, but only once `AppStatus.should_exit` is set. Before shutdown it passes everything through, so uvicorn still reports a genuine double response, and after an ordinary client disconnect uvicorn no-ops mcp's late `Response()` itself. `main()` serves the guarded app for plain `--transport sse` as well as `--reload`, since `mcp.run(transport="sse")` builds its own unguarded app. It launches it the way mcp's `run_sse_async()` does (`anyio.run(uvicorn.Server(config).serve)`), not with `uvicorn.run()`, which would pick uvloop when installed.

**Setup:** none beyond a checkout of this branch. No Google credentials are needed: the case only needs an idle, fully started SSE connection.

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `HOST=127.0.0.1`, `PORT=<free port>`, `AUTH_METHOD=oauth`, `CREDENTIALS_PATH=<nonexistent>`, `TOKEN_PATH=<nonexistent>`, `DEBUG_LEVEL=DEBUG`, `PYTHONUNBUFFERED=1`, stdout and stderr to one file.
1. Open `GET http://127.0.0.1:<port>/sse` (e.g. Python `urllib.request.urlopen`) and read the first line (`event: endpoint`). Wait 3 seconds
2. Send the server process `SIGTERM` (not SIGKILL) and time its exit. Then read the rest of the SSE response to EOF
3. Repeat steps 1–2 two more times against a fresh server, then once more with `--reload` added to the command line
4. Start a fresh server the same way; with the `mcp` SDK's `sse_client` + `ClientSession`, `initialize` and `list_tools`, close the session, then SIGTERM the server

**Checks**
- 2, 3: the log has no `Exception in ASGI application`, no `RuntimeError: Expected ASGI message`, and no `ASGI callable returned without completing response`. (The setup's nonexistent `CREDENTIALS_PATH` logs a `DEBUG ... Auth failure detail` traceback ending in `RuntimeError: '<path>' not found` at connection time; that's the expected degraded start, not a failure.) With `DEBUG_LEVEL=DEBUG` it has `DEBUG mcp_gee_sweet.sse_shutdown Dropping a second response on /sse during shutdown (#868)`
- 2, 3: the server exits within a few seconds of SIGTERM, and `lsof -i :<port>` is empty afterwards
- 2, 3: reading the SSE response to the end ends with a clean EOF, not an `IncompleteRead` (before this fix the chunked stream was never terminated)
- 4: `initialize` and `list_tools` succeed (the guard doesn't touch a normal session), and the log has no traceback other than the expected `Auth failure detail` one
- 4: the log has no `Dropping a second response` line at all. The session's stream closed before SIGTERM, so the guard has nothing to drop, and it acts only during shutdown (round 1 found it acting on an ordinary client disconnect). Don't check the line's order against uvicorn's `Shutting down` instead: in steps 2–3 the two are logged in either order during a real shutdown.

**Cleanup:** SIGKILL any server still running (and record the case as failed).

**Result (2026-10-05, PR #911 round 1 @ d6ba1ec, Sky) ✅ PASS**
uvicorn 0.47.0, run through `uv run` (so the parent's exit code is uv's 143 after forwarding SIGTERM; `--reload` exits 0). Steps 2–3 (three plain runs plus one `--reload`): every log has the `Dropping a second response on /sse (#868)` line and none of the three error strings. The server exits 0.2–0.8s after SIGTERM, the SSE response reads to a clean EOF, and the port is free afterwards. Baseline: the same driver against an `origin/develop` export logs `Exception in ASGI application ... RuntimeError: Expected ASGI message 'http.response.body', but got 'http.response.start'`, and the client gets `IncompleteRead(64 bytes read)`. Step 4: `initialize` and `list_tools` (139 tools) succeed, with no ASGI error. But the log shows `Dropping a second response on /sse (#868)` right after the client closed its session, about 1s *before* SIGTERM. So the guard also handles mcp's late `Response()` after an ordinary client disconnect, not only at shutdown (see the round-1 PR comment). Side check: `--transport streamable-http` with an open `GET /mcp` stream still logs `ASGI callable returned without completing response.` on SIGTERM, and the client gets `IncompleteRead(0 bytes read)`. That transport isn't in this PR's scope; filed as #917.

**Result (2026-10-05, PR #911 round 2 @ 1f138a5, Sky) ✅ PASS**
Same drivers as round 1. Steps 2–3 (three plain runs plus one `--reload`): each log has `Dropping a second response on /sse during shutdown (#868)` and none of the three error strings. The server exits 0.2–0.6s after SIGTERM, every SSE response reads to a clean EOF, and the ports are free. The drop line and uvicorn's `Shutting down` were logged in either order across these runs, so I changed step 4's check from an ordering check to an absence check. Step 4: `initialize` and `list_tools` (139 tools) succeed, and the log has no `Dropping` line and no ASGI error. So after an ordinary client disconnect, the late `Response()` now reaches uvicorn, which ignores it without error. Plain `--transport sse` now launches via `anyio.run(uvicorn.Server(config).serve)` and behaves the same as `--reload`.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an SSE/streamable-http server or SIGTERM.

---

### TC-I48: a token revoked mid-session offers the consent link from tools that catch the error and from tools that raise it (issue #873/#906) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** most tools catch a `RefreshError` in their own `except Exception` and return `{"error": ...}`, so #905's re-authorize hint in `_timed` never reached them (#906). `thread_http`'s transport now records a rejected refresh on the call, and `_timed` replaces the tool's result with the re-authorization offer. A client with no URL-elicitation support gets the link in the `ToolError` text. The text uses the error's `args[0]`, not the `RefreshError` tuple's repr.

**Setup**
- A real OAuth client JSON (`CREDENTIALS_PATH`) and a working `token.json` for it.
- A scratch copy of that token (mode `0600`) with `token` set to `ya29.invalid`, `refresh_token` set to `1//invalid`, and `expiry` one hour in the future. Startup then accepts the token without refreshing, and the first API call gets a 401, refreshes, and Google answers `invalid_grant`.
- Run `refresh_cache` first, or use IDs not in the shared `/tmp/mcp_gee_sweet.db` cache: a cache hit makes no API call, so no refresh happens.

**Action**
Run the server under the `mcp` SDK's `stdio_client` + `ClientSession`, with **no** `elicitation_callback`, and with `DEBUG_LEVEL=INFO`, `LOG_FILE=<tmp log>`:

```
AUTH_METHOD=oauth
TOKEN_PATH=<scratch token>
CREDENTIALS_PATH=<oauth client json>
OAUTH_CONSENT_TIMEOUT_SECONDS=120
BROWSER=/usr/bin/false
```

1. Call `list_files` with `folder_id: "root"`, `max_results: 1` (catches the error itself)
2. Call `list_sheets` with any real spreadsheet ID (lets the error propagate)

**Checks**
- 1 and 2: an error result whose text starts `Error executing tool <name>: Google rejected the OAuth token refresh: invalid_grant: ...`, then `To re-authorize, open this link in a browser and approve access within <N>s, then retry the call: https://accounts.google.com/o/oauth2/auth?...` (`<N>` at most 120: the time the link has left), then the `mcp-gee-sweet auth` alternative naming the scratch `TOKEN_PATH` and `CREDENTIALS_PATH`, ending `then retry the call: the server picks up the new token without a restart.`
- The part of either text before `The call may have partly completed` has no `{'error'` (the tuple repr)
- 1 only (round 2): the text ends `The call may have partly completed before the token was rejected; the tool reported: {"error": "List files failed: ..."}`, the tool's own result, which the offer replaced. 2 has no such sentence (the tool raised the refresh error itself)
- Run step 1 three more times: the log has only one more `Token refresh failed` warning in total (the unchanged `TOKEN_PATH` isn't reloaded again), and no `Gmail tools disabled` line from these calls
- Both calls give the *same* link. Its `redirect_uri` is `http://localhost:<port>/`, and a TCP connect to that port succeeds (one listener, still open)
- No browser opened, and no `Please visit this URL` line in stderr or the log
- `<tmp log>` has `"TOOL list_files" 401` and `"TOOL list_sheets" 401`

**Cleanup:** delete the scratch token and log.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ✅ PASS**
`stdio_client` + `ClientSession`, no elicitation callback, `CACHE_DB_PATH` pointed at a scratch file. Both `list_files` and `list_sheets`: `is_error: true`, text `Error executing tool <name>: Google rejected the OAuth token refresh: invalid_grant: Bad Request. To re-authorize, open this link in a browser and approve access within 120s, then retry the call: https://accounts.google.com/o/oauth2/auth?...`, then the `mcp-gee-sweet auth` alternative naming the scratch `TOKEN_PATH`/`CREDENTIALS_PATH`. No `{'error'` and no `List files failed`. Same link for both, `redirect_uri=http://localhost:60833/`, and a TCP connect to it succeeded. 0 `Please visit`. Log: `"TOOL list_files" 401 0.242s`, `"TOOL list_sheets" 401 7.408s`. Side observation: every token reload re-logs `WARNING ... Gmail tools disabled` (this token lacks `gmail.modify`), so each reload rewrites the process-wide Gmail gate (review finding 4).

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
Both texts as specified, with time left `119s` and `118s` (not the full 120). The CLI alternative ends `... without a restart.`. 1 (`list_files`) ends `The call may have partly completed before the token was rejected; the tool reported: [{"error": "List files failed: ('invalid_grant: Bad Request', {...})"}]`. The tuple repr appears only inside that reported result, never before it. 2 (`list_sheets`) has no such sentence. Same link for both, and its port is open. Step 1 three more times: each `401` in 0.09s, 0 `Token refresh failed` lines in total (this token isn't expired, so the reload never refreshes, and the unchanged file is skipped), and only the startup `Gmail tools disabled` line (1 in the log, against one per reload in round 1). 0 `Please visit`.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

---

### TC-I49: a client with URL elicitation gets a `-32042` error carrying the consent link (issue #873) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** a client that declares `elicitation.url` gets `UrlElicitationRequiredError`, a JSON-RPC protocol error, not a tool result. The client shows the link and asks the user before opening it. Claude Code declares this capability (2.1.291).

**Setup:** as TC-I48.

**Action:** as TC-I48, but pass an `elicitation_callback` to `ClientSession`, which makes the SDK declare `elicitation: {form, url}`. Catch the `MCPError` each call raises.

**Checks**
- 1 and 2: the error's code is `-32042`. `UrlElicitationRequiredError.from_error(e.error).elicitations` has one entry, whose `url` is a `https://accounts.google.com/o/oauth2/auth?...` link and whose `message` starts `Google rejected the OAuth token refresh: invalid_grant: ...` and says to open the page and retry
- Both calls carry the same `elicitation_id` and the same `url`
- `<tmp log>` has `"TOOL list_files" 401` and `"TOOL list_sheets" 401`

**Cleanup:** delete the scratch token and log.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ✅ PASS**
With an `elicitation_callback` (returns cancel; never invoked, since the server raises rather than sending an in-call request). Both calls raised `MCPError` code `-32042`. `from_error(...).elicitations` had one entry each, with `url` `https://accounts.google.com/o/oauth2/auth?...` and `message` `Google rejected the OAuth token refresh: invalid_grant: Bad Request. Open this Google sign-in page to re-authorize mcp-gee-sweet (the link works for 120s), then retry.` Same `elicitation_id` and same `url` for both, and the callback port was open. Log: `"TOOL list_files" 401`, `"TOOL list_sheets" 401`.

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
Same as round 1: both calls `-32042`, the same `elicitation_id` and `url`, port open, `401` access lines, 0 `Please visit`.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

---

### TC-I50: after `mcp-gee-sweet auth` (or any new token in `TOKEN_PATH`), the next call recovers without a restart (issue #873) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** before #873, the CLI needed a server restart or reconnect afterwards. A failing call now re-reads `TOKEN_PATH` first, and adopts a usable token whose refresh token differs from the failing one.

**Setup:** as TC-I48, plus a second scratch path that doesn't exist yet.

**Action**
1. Start the TC-I48 client with `TOKEN_PATH=<nonexistent second path>` (a degraded start). Call `list_files` (`folder_id: "root"`, `max_results: 1`): expect the consent-link error. Without stopping the server, copy the working `token.json` to `<second path>`. Call `list_files` and `list_sheets` again
2. Start a fresh client with `TOKEN_PATH=<scratch token>` (revoked, as in TC-I48). Call `list_sheets`: expect the consent-link error. Copy the working `token.json` over `<scratch token>`. Call `list_sheets` twice more

**Checks**
- 1: after the copy, both calls succeed. The log has `INFO mcp_gee_sweet.auth OAuth credentials reloaded; this connection is authorized again` once, and `200` access lines
- 2: the first call after the copy returns an error ending `The server has since loaded a newer OAuth token; retry the call.` (a mid-session failure doesn't re-run the tool), and the next call succeeds with `200`
- Neither server was restarted

**Cleanup:** delete the scratch tokens and logs.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ✅ PASS**
Step 1: the first `list_files` gave the consent-link error (`401`). After copying the working token in, `list_files` and `list_sheets` (`Sales Notes & Misc Empty`) both returned `200`, with one `INFO mcp_gee_sweet.auth OAuth credentials reloaded; this connection is authorized again`. Step 2: `list_sheets` gave the consent-link error. After the copy, the next call returned `... The server has since loaded a newer OAuth token; retry the call.` (`401`, one `reloaded` line), and the call after that returned `200`. Same server process throughout.

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
Step 1: `401` with the link, then after the copy `OAuth credentials reloaded ...` once, `list_files` `200` and `list_sheets` `200`. Step 2: `401` with the link, then after the copy `... The server has since loaded a newer OAuth token; retry the call.` (`401`), then `200`. Side observation on step 2's first post-copy call: it now ends `The call may have partly completed ...; the tool reported: ["Sales", "Notes & Misc", "Empty"]`. `list_sheets` actually succeeded from the structure cache (the cache's `modifiedTime` check is where the revoked refresh failed and was recorded), and `_timed` replaced that success with the retry message. That's the design (a recorded failure replaces the result, now carried in the text), not a defect.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

---

### TC-I51: completing the offered consent in a browser saves the token and the retried call succeeds (issue #873) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** the end-to-end path the issue asks for: the user opens the offered link, approves, and the callback saves the token. The token is written `0600`, and every connection adopts it on its next call. Needs a browser on the server's machine, signed in to the Google account (by hand, or Playwright under the `docs/qa/run.md` mutex).

**Setup:** as TC-I48, with `OAUTH_CONSENT_TIMEOUT_SECONDS=300`.

**Action**
1. As TC-I48 step 1: get the consent link from `list_files`
2. Open the link in the browser and approve every requested scope. The callback page reads `The authentication flow has completed. You may close this window.`
3. Call `list_files` again, then `list_sheets`

**Checks**
- 3: both calls succeed
- `<scratch token>` now has a different `refresh_token` from the bogus one and is mode `0600` (`stat -f %Lp` prints `600`)
- The callback port from the link is closed after step 2
- The server opened no browser itself at any point

**Cleanup:** revoke the new grant at https://myaccount.google.com/permissions if it was made for a scratch account, and delete the scratch token and log.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ✅ PASS**
`OAUTH_CONSENT_TIMEOUT_SECONDS=300`, a stdio session held open, and a fresh `CACHE_DB_PATH` (a cache shared with an earlier run served `list_files` with no API call, so no refresh happened: use a fresh cache for this case). The first `list_files` gave the link (`401`). Playwright, under the mutex, after the fixture-doc sign-in check: the account chooser, the Workspace account, then **Allow** led to `http://localhost:<port>/?state=...&code=...`, which read `The authentication flow has completed. You may close this window.` The scratch token's `refresh_token` changed and its mode is `0o600`. A TCP connect to the callback port then failed (closed). Log: `OAuth credentials reloaded ...`, then `list_files` `200` and `list_sheets` `200`. 0 `Please visit`, and no browser opened by the server (`BROWSER=/usr/bin/false`). The grant was on the fixture-owning Workspace account for the team's existing OAuth client, so nothing to revoke.

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
Same flow as round 1 (Playwright under the mutex, Workspace account, **Allow**): the callback page completed, the scratch token's `refresh_token` changed with mode `0o600`, the callback port then closed, and `OAuth credentials reloaded ...` was followed by `list_files` `200` and `list_sheets` `200`. 0 `Please visit`.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

---

### TC-I52: in Claude Code, a revoked token shows the consent prompt instead of an error (issue #873) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** the client-side half of TC-I49, in the client the team uses. Needs an interactive Claude Code session (`claude -p` cancels URL elicitation on its own).

**Setup:** register a stdio server in a scratch MCP config, using the TC-I48 scratch token and env, and start an interactive `claude --mcp-config <scratch config> --strict-mcp-config`.

**Action:** ask Claude to call that server's `list_files` with `folder_id: "root"`, `max_results: 1`. When the URL prompt appears, accept it, approve the consent in the browser that opens, then ask Claude to retry the call.

**Checks**
- Claude Code shows a prompt with the `accounts.google.com` link and the elicitation message, before anything opens
- After the consent, the retried call returns the file listing
- Record whether Claude Code retried by itself after `notifications/elicitation/complete` or needed the explicit retry. Either is a pass; the behavior is the client's.

**Cleanup:** delete the scratch config, token, and log.

**Result (2026-10-06, PR #925 round 1 @ db4f13d, Sky) ⏭️ NOT RUN**
Needs a human driving an interactive Claude Code session; a lane QA session can't accept the client's URL prompt itself. TC-I49 covers the wire format (`-32042` with the elicitation). Pending a human-driven run.

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ⏭️ NOT RUN**
Same reason as round 1: needs a human in an interactive Claude Code session.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

---

### TC-I53: over SSE, a connection opening while a tool call's consent link is pending starts at once, offers the same link, and leaves server consent on (PR #925 QA round 1) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** in round 1, connection B's lifespan joined the consent a tool call on connection A had offered. B waited the whole `OAUTH_CONSENT_TIMEOUT_SECONDS` with no prompt shown anywhere. It then degraded through `_disable_consent_after_failure`, so connection C reported `an earlier browser consent in this server process didn't complete`. Now a lifespan that finds a tool call's consent pending starts without access straight away (`disables_consent=False`), and its first tool call offers the same link. Separately, a tool call that offers a *lifespan's* link marks it `offered`, so the last lifespan waiter leaving no longer closes its callback port.

**Setup**
- The TC-I48 scratch token (dead access token, bogus refresh token, expiry in the future), and a way to rewrite it with `expiry` one hour in the *past*.
- A free port.

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `AUTH_METHOD=oauth`, `TOKEN_PATH=<scratch token>`, `CREDENTIALS_PATH=<oauth client json>`, `OAUTH_CONSENT_TIMEOUT_SECONDS=25`, `HOST=127.0.0.1`, `PORT=<port>`, `BROWSER=/usr/bin/false`, `DEBUG_LEVEL=INFO`, stdout and stderr to one log. With the `mcp` SDK's `sse_client` + `ClientSession` (no elicitation callback):
1. Connection A: `initialize`, call `list_files` (`folder_id: "root"`, `max_results: 1`), read `server://auth-status`
2. Rewrite the scratch token with an expired `expiry` (still the bogus refresh token)
3. Connection B: as A. Then connection C: as A

**Checks**
- 1: the TC-I48 consent-link error
- 3: B and C each finish `initialize` within a couple of seconds (not the 25s timeout), and their `list_files` error starts `No usable OAuth token at '<scratch token>'. To re-authorize, open this link ...` with the *same* link A got and a time left of at most 25s
- No `auth-status` read's `oauth_not_authorized` limitation has `restart the server` in its text (a `gmail_not_authorized` one still says to restart, by design, if the token lacks `gmail.modify`)
- The log has 0 `Please visit` lines, 0 `earlier browser consent` lines, and two `Starting without Google access: ... a re-authorization link a tool call offered is still open` lines (B and C)

**Cleanup:** SIGTERM the server; delete the scratch token and log.

**Result (2026-10-06, PR #925 round 2 @ a3af056, Sky) ✅ PASS**
SSE on `127.0.0.1:8937`, `OAUTH_CONSENT_TIMEOUT_SECONDS=25`. A: `initialize` 0.2s, then the TC-I48 link with `within 24s`. After expiring the token: B and C each `initialize` in 0.1s (not 25s), and each `list_files` starts `No usable OAuth token at '<scratch token>'. To re-authorize, open this link ... within 24s` with the *same* link A got. The log has 0 `Please visit`, 0 `earlier browser consent`, and 2 `Starting without Google access: ... a re-authorization link a tool call offered is still open` lines. SIGTERM exited cleanly. B's and C's `auth-status` have no `restart the server`. A's does, from its `gmail_not_authorized` limitation: the team token lacks `gmail.modify`, and a missing scope still needs a restart by design. So I narrowed that check's wording to the `oauth_not_authorized` limitation.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

### TC-I54: replacing a nearly expired tool-call link leaves the old link working until its stated deadline (PR #925 QA round 2) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** a tool call's own consent attempt with less than `min(60, timeout/2)` seconds left isn't offered again; the next failing call gets a fresh link. In round 2 that replacement also stopped the old attempt, so link 1's callback port closed while its offer still promised it several more seconds, and a user on link 1's consent page landed on a dead localhost redirect. Now the old attempt keeps listening until its own deadline. The two attempts share a group: whichever completes publishes the token and sends `elicitation/complete` to both attempts' clients (unit-tested in `tests/test_reauth.py::TestUserConsent::test_either_link_completes_and_notifies_both_clients`).

**Setup**
- The TC-I48 scratch token (dead access token, bogus refresh token).

**Action**
Start a stdio session against `uv run mcp-gee-sweet` with `AUTH_METHOD=oauth`, `TOKEN_PATH=<scratch token>`, `CREDENTIALS_PATH=<oauth client json>`, `OAUTH_CONSENT_TIMEOUT_SECONDS=25` (replacement threshold 12s), `BROWSER=/usr/bin/false`, `DEBUG_LEVEL=INFO`, `LOG_FILE=<tmp log>`, using the `mcp` SDK's `stdio_client` + `ClientSession` (no elicitation callback):
1. Call `list_files` (`folder_id: "root"`, `max_results: 1`). Note the link (link 1), its `within <N>s`, and the time of the call; link 1's deadline is that time plus `<N>`
2. 16s after step 1, call `list_files` again. Note its link (link 2)
3. 2s after step 2, TCP-connect to link 1's and link 2's `redirect_uri` ports
4. 2s after link 1's deadline, TCP-connect to both ports again

**Checks**
- 1: the TC-I48 consent-link error, `within 24s` or `within 25s`
- 2: a *different* link, with a different `redirect_uri` port, and a time left of at least 23s
- 3: both connects succeed (link 1 still open, with time left on its stated deadline)
- 4: link 1's connect is refused (closed at its own deadline), and link 2's still succeeds
- The log has 0 `Please visit` lines

**Cleanup:** end the session; delete the scratch token and log.

**Result (2026-10-08, PR #925 round 3 @ e5f6fed, Sky) ✅ PASS**
mcp 2.3.0, stdio, fresh `CACHE_DB_PATH`. Step 1: `Google rejected the OAuth token refresh: invalid_grant ...`, link 1 `within 24s`, port 63319. Step 2 at +16.1s: a different link, port 63322, `within 24s`. Step 3 at +18.1s: both ports open (round 2 had link 1 closed by now). Step 4 at +26.0s (link 1's deadline +24s): link 1 refused, link 2 open. 0 `Please visit`.
Extra check (the fix's "either link completes" claim, TC-I51-style): `OAUTH_CONSENT_TIMEOUT_SECONDS=120` (threshold 60s). Link 1 `within 119s`. At +61.6s a second `list_files` gave link 2 (a different port), with both ports open. Playwright, under the mutex, after the fixture-doc sign-in check, then completed consent through **link 1** (the replaced one): account chooser, the Workspace account, **Allow**, and the callback page on link 1's port read `The authentication flow has completed. You may close this window.` The scratch token's `refresh_token` changed and its mode is `0o600`. Link 1's port then closed, and the retried `list_files` succeeded. Link 2's port stayed open after the consent completed, as designed: it listens until its own deadline. 0 `Please visit`. Scratch files deleted.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs OAuth token manipulation, a degraded start, SSE, or the auth consent flow.

---

### TC-I55: SIGTERM with a streamable-http `GET /mcp` stream open closes the stream cleanly (issue #917) ⚠️ local-filesystem

**Background:** TC-I47's sibling on the other HTTP transport. On SIGTERM, sse_starlette cancels the open `GET /mcp` event stream without its closing chunk, and mcp's handler then simply returns. Nothing follows the cut-off body, so uvicorn logged `ASGI callable returned without completing response.` and the client got a chunked body that never terminated (`IncompleteRead(0 bytes read)`). `SingleResponseGuard` (`sse_shutdown.py`) now sends the missing closing body when the app returns during shutdown with a started, unfinished response. Outside shutdown it leaves that alone, so uvicorn still reports a genuine incomplete response. `main()` serves `--transport streamable-http` through the guard with the same launch as `--transport sse` (`anyio.run(uvicorn.Server(config).serve)`), instead of `mcp.run(transport="streamable-http")`, which builds its own unguarded app.

**Setup:** none beyond a checkout of this branch. No Google credentials are needed: the case only needs an initialized session with its GET stream open.

**Action**
Start `uv run mcp-gee-sweet --transport streamable-http` with `HOST=127.0.0.1`, `PORT=<free port>`, `AUTH_METHOD=oauth`, `CREDENTIALS_PATH=<nonexistent>`, `TOKEN_PATH=<nonexistent>`, `DEBUG_LEVEL=DEBUG`, `PYTHONUNBUFFERED=1`, stdout and stderr to one file.
1. With Python `http.client`: `POST /mcp` a JSON-RPC `initialize` (`Content-Type: application/json`, `Accept: application/json, text/event-stream`) and keep the returned `mcp-session-id` header. `POST /mcp` `notifications/initialized` with that session ID (expect `202`). Then, on a separate connection, open `GET /mcp` with `Accept: text/event-stream` and the session ID, and read the response status (expect `200`). Wait 2 seconds
2. Send the server process `SIGTERM` (not SIGKILL) and time its exit. Then read the GET response to EOF
3. Repeat steps 1–2 two more times against a fresh server, then once more with `--reload` added to the command line
4. Start a fresh server the same way; with the `mcp` SDK's `streamable_http_client` + `ClientSession`, `initialize` and `list_tools`, close the session, then SIGTERM the server
5. Run `uv run mcp-gee-sweet --transport websocket`

**Checks**
- 2, 3: reading the GET response to the end ends with a clean EOF (an empty body), not an `IncompleteRead`
- 2, 3: the log has no `ASGI callable returned without completing response`, no `Exception in ASGI application`, and no `RuntimeError: Expected ASGI message`. (The nonexistent `CREDENTIALS_PATH` logs the expected `Auth failure detail` traceback ending in `RuntimeError: '<path>' not found`, as in TC-I47.) With `DEBUG_LEVEL=DEBUG` it has `DEBUG mcp_gee_sweet.sse_shutdown Closing a response cut off on /mcp during shutdown (#917)`
- 2, 3: the server exits within a few seconds of SIGTERM, and `lsof -i :<port>` is empty afterwards
- 3 (`--reload` run): the log has `Started reloader process`, so `--reload` is honored for streamable-http rather than silently ignored
- 4: `initialize` and `list_tools` succeed (the guard doesn't touch a normal session), and the log has no ASGI error and no `Closing a response cut off` line
- 5: exits non-zero with `mcp-gee-sweet: unknown --transport 'websocket' (use stdio, sse, or streamable-http)` on stderr, and no traceback
- Re-run TC-I47's steps 1–2 once: `--transport sse` still passes, since it shares the guard and the launch helper

**Cleanup:** SIGKILL any server still running (and record the case as failed).

**Result (2026-10-10, PR #975 round 1 @ 5e3fad2, Sky) ✅ PASS**
uvicorn 0.47.0, mcp 2.3.0, run through `uv run` (exit code 143 is uv forwarding SIGTERM). Steps 1–3 (three fresh servers, `http.client`): `initialize` 200, `notifications/initialized` 202, `GET /mcp` 200. After SIGTERM each GET read to a clean EOF (0 bytes, no `IncompleteRead`). Every log has `Closing a response cut off on /mcp during shutdown (#917)` and none of the three error strings. The servers exited 0.55s, 0.61s, and 0.55s after SIGTERM. `lsof -i :<port>` showed only the driver's own client sockets in `CLOSE_WAIT`, with no server process or listener. Step 4: SDK `streamable_http_client` `initialize` + `list_tools` returned 139 tools, with no ASGI error and no `Closing a response cut off` line; exit 0.13s, port free. TC-I47 recheck: steps 1–2 once (`event: endpoint`, `Dropping a second response on /sse during shutdown (#868)`, clean EOF, exit 0.18s, port free) and step 4 once (139 tools, no `Dropping` line), all passing. Side check outside the case: `--transport streamable-http --reload` starts with no reloader and no warning that `--reload` is ignored (sent back on the PR).

**Result (2026-10-10, PR #975 round 2 @ f5987b8, Sky) ✅ PASS**
Same driver as round 1 (uvicorn 0.47.0, mcp 2.3.0, `uv run`). Steps 1–3 (three plain runs): `initialize` 200, `notifications/initialized` 202, `GET /mcp` 200. Each GET read to a clean EOF (0 bytes), and each log has the `#917` close line and none of the three error strings. The servers exited 0.60–0.61s after SIGTERM, with no listener left. Step 3 `--reload` run: `Started reloader process ... using StatReload`, the same `#917` close line, a clean EOF, and exit 0.76s (uvicorn's reloader exits 0). Extra check: touching `src/mcp_gee_sweet/sse_shutdown.py` under `--reload` logged `StatReload detected changes ... Reloading...` and started a new server process, so the reload works and isn't only a banner. Step 4: SDK session, 139 tools, no close line and no ASGI error, exit 0.23s. Step 5: `mcp-gee-sweet: unknown --transport 'websocket' (use stdio, sse, or streamable-http)`, exit 1, no traceback. Extra check: `--reload` with stdio logs `WARNING ... --reload applies only to the sse and streamable-http transports; ignoring it`. TC-I47 recheck: steps 1–2 once (`#868` drop line, clean EOF, exit 0.60s, port free).

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an SSE/streamable-http server or SIGTERM.

---

### TC-I56: over SSE with `LOCAL_FILE_ACCESS` unset, local-only tools aren't registered and an optional `local_path` is refused before any fetch (issue #796) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** #796's policy defaults to `off` under any network transport, because a network-facing server's caller isn't necessarily its operator. In `off` mode the nine tools that only work on local files aren't registered. Tools with an optional local path stay registered and refuse it at entry, before any Google API call, so a refused destination costs no fetch and never reports an unrelated API error first. Design: `docs/design/local-file-access-policy.md`.

**Setup:** a checkout of this branch with working OAuth credentials in `src/mcp_gee_sweet/.env` (or `CREDENTIALS_PATH`/`TOKEN_PATH`). A spreadsheet ID the account can read (`QA_SPREADSHEET_ID`). Make sure `LOCAL_FILE_ACCESS` and `LOCAL_FILE_ROOTS` are unset in the environment *and* not set in `.env`. An empty scratch directory `<scratch>`.

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `HOST=127.0.0.1`, `PORT=<free port>`. With the `mcp` SDK's `sse_client` + `ClientSession`:
1. `initialize`, then `list_tools`
2. `read_resource("server://auth-status")`
3. `call_tool("get_sheet_data", {"spreadsheet_id": QA_SPREADSHEET_ID, "sheet": "Sheet1", "local_path": "<scratch>/out.json"})`
4. `call_tool("get_sheet_data", {"spreadsheet_id": "not-a-real-id", "sheet": "Sheet1", "local_path": "<scratch>/out.json"})`
5. `call_tool("create_doc", {"title": "TC-I56 image probe", "content": "Text\n\n![x](<scratch>/x.png)", "content_format": "markdown"})` after writing any small PNG to `<scratch>/x.png`

**Checks**
- 1: none of `upload_local_file`, `upload_local_folder`, `download_file`, `download_folder`, `sync_folder`, `import_csv_to_sheet`, `create_doc_from_file`, `update_doc_from_file`, `insert_local_images` is listed. `get_sheet_data`, `send_message`, `create_doc` are.
- 2: `local_file_access` is `{"mode": "off", "explicit": false, "roots": [], "unregistered_tools": [<the nine names above, sorted>]}`
- 3 and 4: both return an error whose text is exactly `local file access is disabled on this server: LOCAL_FILE_ACCESS is unset, which means off for the sse transport`. Step 4 does **not** report an HttpError 404, which proves the refusal comes before the fetch
- 3, 4: `<scratch>` is still empty
- 5: the doc is created with its text. The result's image outcome for `<scratch>/x.png` carries the same refusal text, and no file was uploaded to Drive for it

**Cleanup:** `delete_file` the TC-I56 doc. SIGTERM the server.

**Result (2026-10-15, PR #1039 round 1 @ fb49e7d, Sky) ✅ PASS**
mcp 2.3.0, uvicorn 0.47.0, `uv run mcp-gee-sweet --transport sse`, SDK `sse_client`, OAuth, `LOCAL_FILE_ACCESS`/`LOCAL_FILE_ROOTS` unset in the environment and both `.env` files. Step 1: none of the nine local-only tools listed; `get_sheet_data`, `send_message`, `create_doc` listed. Step 2: `{"mode": "off", "explicit": false, "roots": [], "unregistered_tools": [<the nine, sorted>]}`. Steps 3 and 4: both `is_error` with exactly `local file access is disabled on this server: LOCAL_FILE_ACCESS is unset, which means off for the sse transport`; step 4 reported no 404. `<scratch>` held only `x.png` afterwards. Step 5: doc created with its text, `images[0].error` the same refusal text, and no PNG appeared in the target folder. Doc deleted.

**Result (2026-10-15, PR #1039 round 2 @ 6ba5297, Sky) ✅ PASS**
Same driver as round 1, fresh subprocess on this head. Steps 1–5 matched round 1 exactly: no local-only tools listed, `{"mode": "off", "explicit": false, ...}` with the nine sorted, both `get_sheet_data` calls refused with the defaulted-off text (no 404), `<scratch>` held only `x.png`, and the doc was created with the image's per-item refusal. Doc deleted.

**Result (2026-10-16, PR #1039 round 3 @ b8d0ced, Sky) ✅ PASS**
Same driver, fresh subprocess on this head. Steps 1–5 matched round 2: no local-only tools listed, `{"mode": "off", "explicit": false, ...}` with the nine sorted, both `get_sheet_data` calls refused with the defaulted-off text (no 404), `<scratch>` held only `x.png`, and the doc was created with the image's per-item refusal. Scratch folder trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs SSE, a LOCAL_FILE_ACCESS change, an invalid startup setting, or an HTTP transport.

---

### TC-I57: `LOCAL_FILE_ACCESS=roots` allows paths inside a root and refuses the rest, symlinks included (issue #796) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** In `roots` mode a path is resolved, symlinks included, and must land under a `LOCAL_FILE_ROOTS` directory. The refusal lists the allowed directories so a caller can choose a valid path. During a folder walk each entry is checked, so a symlink inside a root that points outside it is refused while the rest of the walk continues.

**Setup:** working OAuth credentials, a Drive scratch folder (`QA_SCRATCH_FOLDER_ID`). Local directories `<root>` and `<outside>` (siblings, not nested). Files: `<root>/ok.txt` (`fine`), `<outside>/secret.txt` (`secret`), and a symlink `<root>/escape.txt` → `<outside>/secret.txt`.

**Action**
Start `uv run mcp-gee-sweet --transport sse` with `HOST=127.0.0.1`, `PORT=<free port>`, `LOCAL_FILE_ACCESS=roots`, `LOCAL_FILE_ROOTS=<root>`. With the SDK client:
1. `list_tools`, then `read_resource("server://auth-status")`
2. `call_tool("upload_local_file", {"local_path": "<root>/ok.txt", "parent_folder_id": QA_SCRATCH_FOLDER_ID, "skip_if_exists": false})`
3. `call_tool("upload_local_file", {"local_path": "<outside>/secret.txt", "parent_folder_id": QA_SCRATCH_FOLDER_ID})`
4. `call_tool("upload_local_file", {"local_path": "<root>/escape.txt", "parent_folder_id": QA_SCRATCH_FOLDER_ID})`
5. `call_tool("upload_local_file", {"local_path": "<root>/../<outside basename>/secret.txt", "parent_folder_id": QA_SCRATCH_FOLDER_ID})`
6. `call_tool("sync_folder", {"folder_id": QA_SCRATCH_FOLDER_ID, "local_path": "<root>", "direction": "upload", "dry_run": true})`
7. `call_tool("upload_local_folder", {"local_path": "<root>", "parent_folder_id": QA_SCRATCH_FOLDER_ID, "skip_if_exists": false})`

**Checks**
- 1: all nine local-only tools are listed. `local_file_access` is `{"mode": "roots", "explicit": true, "roots": ["<root>"], "unregistered_tools": []}`
- 2: succeeds, returning a `fileId`
- 3, 4, 5: each fails with `<the path as passed> is outside this server's LOCAL_FILE_ROOTS. Allowed directories: <root>`, and no file is created in `QA_SCRATCH_FOLDER_ID` (check with `list_files`)
- 6: `actions` has `escape.txt` with `action: "local_read_fail"` and a reason containing `outside this server's LOCAL_FILE_ROOTS`. `ok.txt` is planned normally
- 7: `uploaded` is `["ok.txt"]` and `failed` has one entry, `escape.txt`, with the same refusal text. `secret` never appears in Drive

**Cleanup:** `delete_file` every file the case created in `QA_SCRATCH_FOLDER_ID`. SIGTERM the server. Remove `<root>` and `<outside>`.

**Result (2026-10-15, PR #1039 round 1 @ fb49e7d, Sky) ✅ PASS**
Same driver as TC-I56, with `LOCAL_FILE_ACCESS=roots`, `LOCAL_FILE_ROOTS=<root>`. Step 1: all nine local-only tools listed; `{"mode": "roots", "explicit": true, "roots": ["<root>"], "unregistered_tools": []}`. Step 2: `fileId` returned. Steps 3, 4 (symlink) and 5 (`..` traversal): each `<path as passed> is outside this server's LOCAL_FILE_ROOTS. Allowed directories: <root>`. Step 6: `escape.txt` → `local_read_fail` with that reason plus `; not synced`; `ok.txt` → `skip` / `in sync`. Step 7: `uploaded: ["ok.txt"]`, `failed: [{escape.txt, <same refusal>}]`. `list_files` on the scratch folder never showed `secret.txt` or `escape.txt`. Note: a first harness run crashed after step 2 and left extra `ok.txt` copies, which made step 6 plan `collision`; the copies were deleted and the case rerun clean, as recorded here.

**Result (2026-10-15, PR #1039 round 2 @ 6ba5297, Sky) ✅ PASS**
Fresh subprocess on this head. Step 1: nine listed, roots status as expected. Step 2: `fileId`. Steps 3–5: the same `outside this server's LOCAL_FILE_ROOTS` refusal for each. Step 6: `escape.txt` → `local_read_fail`, `ok.txt` → `skip` / `in sync`. Step 7: `uploaded: ["ok.txt"]`, `failed: [escape.txt]`. Neither `secret.txt` nor `escape.txt` reached Drive. Scratch folder deleted.

**Result (2026-10-16, PR #1039 round 3 @ b8d0ced, Sky) ✅ PASS**
Fresh subprocess on this head, in its own empty Drive folder. Step 1: nine listed, `{"mode": "roots", "explicit": true, "roots": ["<root>"], ...}`. Step 2: `fileId`. Steps 3–5: the `outside this server's LOCAL_FILE_ROOTS` refusal for each. Step 6: `escape.txt` → `local_read_fail`, `ok.txt` → `skip`. Step 7: `uploaded: ["ok.txt"]`, `failed: [escape.txt]`. A first run in a folder that already held a control `ok.txt` planned `collision` at step 6 (fixture, not product); this clean rerun is the one recorded. Scratch folder trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs SSE, a LOCAL_FILE_ACCESS change, an invalid startup setting, or an HTTP transport.

---

### TC-I58: the server's own credential files are refused in `full` mode too (issue #796) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** In every mode, including stdio's default `full`, tools can't read or write the server's own `CREDENTIALS_PATH`, `TOKEN_PATH`, `SERVICE_ACCOUNT_PATH`, `.env`, ADC key files, cache DB, or log files. Files are matched by identity, so a hardlink or symlink to the token is refused too, and a write target that doesn't exist yet is still refused, so a download can't plant a token.

**Setup:** a server whose `TOKEN_PATH` is a real OAuth token (a stdio server launched from this branch, e.g. via an MCP client config pointing at `uv run mcp-gee-sweet`). A Drive scratch folder holding a small text file named `token.json` (`QA_TOKEN_NAMED_FILE_ID`). A hardlink `<scratch>/innocent.json` to `TOKEN_PATH` (`ln <TOKEN_PATH> <scratch>/innocent.json`). For step 6: a subdirectory `<directory containing TOKEN_PATH>/sub`, a symlink `<scratch>/link` → that subdirectory (`ln -s <directory containing TOKEN_PATH>/sub <scratch>/link`), and a Drive subfolder of `QA_SCRATCH_FOLDER_ID` holding one copy of `QA_TOKEN_NAMED_FILE_ID` named exactly `TOKEN_PATH`'s basename (`copy_file`, then `move_file`).

**Action**
1. `upload_local_file(local_path=<TOKEN_PATH>, parent_folder_id=QA_SCRATCH_FOLDER_ID)`
2. `upload_local_file(local_path="<scratch>/innocent.json", parent_folder_id=QA_SCRATCH_FOLDER_ID)`
3. `create_draft(to=<QA mailbox>, subject="TC-I58", body="x", attachments=[{"local_path": <TOKEN_PATH>}])`
4. `download_file(file_id=QA_TOKEN_NAMED_FILE_ID, local_path=<directory containing TOKEN_PATH>)`
5. `read_resource("server://auth-status")`
6. `download_folder(folder_id=<the step-6 Drive subfolder>, local_path="<scratch>/link/..", skip_if_exists=false)`. The kernel resolves `link` before `..`, so this writes into `<directory containing TOKEN_PATH>`, not `<scratch>`

**Checks**
- 1–4: each fails with `<path> is one of this server's own credential, config, cache, or log files and can't be read by a tool` (`written` for step 4)
- 1, 2: no file is created in `QA_SCRATCH_FOLDER_ID`. 3: no draft is created (check `list_messages` with `label_ids=["DRAFT"]`). 4: `TOKEN_PATH`'s content and mtime are unchanged
- 5: `local_file_access` is `{"mode": "full", "explicit": false, "roots": [], "unregistered_tools": []}`
- 6: `downloaded` is empty and `failed` holds the one file, with the `... can't be written by a tool` refusal naming the path as passed (`<scratch>/link/../<TOKEN_PATH basename>`), which the kernel resolves into `<directory containing TOKEN_PATH>`. `TOKEN_PATH`'s content and mtime are unchanged (PR #1039 QA round 2)

**Cleanup:** `rm <scratch>/innocent.json` (the hardlink, not the token) and `rm <scratch>/link` (the symlink); `rmdir <directory containing TOKEN_PATH>/sub`. Trash the step-6 Drive subfolder. Leave `QA_TOKEN_NAMED_FILE_ID` for re-runs.

**Result (2026-10-15, PR #1039 round 1 @ fb49e7d, Sky) ⚠️ PARTIAL: steps 1, 2, 4 run against a deny-listed log file, not `TOKEN_PATH`; step 3 pending**
This role's stdio `mcp-gee-sweet-sky` server (defaulted `full`). Claude Code's auto-mode classifier refused creating a hardlink to the real OAuth token, so the identity check was exercised with `LOG_FILE` (`/tmp/mcp-gee-sweet.log`), which goes through the same `_is_denied` path. Step 1 (`upload_local_file` on `LOG_FILE`): `... is one of this server's own credential, config, cache, or log files and can't be read by a tool`. Step 2 (a hardlink to `LOG_FILE` in a scratch dir, same inode confirmed with `ls -li`): the same refusal, naming the hardlink path. Step 4 (`download_file` of a Drive file named `mcp-gee-sweet.log` to `/tmp/`): `/tmp/mcp-gee-sweet.log is one of ... and can't be written by a tool`. Steps 1–2 added nothing to the scratch folder. Step 3 **pending**: the classifier also refused `create_draft` with an attachment, and this slot's token lacks the Gmail scope anyway. Step 5: `{"mode": "full", "explicit": false, "roots": [], "unregistered_tools": []}`. Not yet run: steps 1, 2 and 4 against the real `TOKEN_PATH`.

**Result (2026-10-15, PR #1039 round 2 @ 6ba5297, Sky) ⚠️ PARTIAL: steps 1, 2, 4 against `LOG_FILE`; step 3 pending; a regression found outside the case's steps**
Fresh SSE subprocess on this head with an explicit `LOCAL_FILE_ACCESS=full` and `LOG_FILE=<denied>/log.txt` (round 1's substitution, for the same reason). Step 1: `<denied>/log.txt ... can't be read by a tool`. Step 2 (hardlink `<scratch>/innocent-log.txt`): the same refusal. Step 4 (as `download_folder(local_path=<denied>)` of a Drive folder holding `log.txt`): `failed: [{log.txt, "... can't be written by a tool"}]`. Step 5: `{"mode": "full", "explicit": true, ...}`, as expected for the explicit setting. Step 3 still pending. **Outside the steps:** `download_folder(local_path="<scratch>/link/..", skip_if_exists=false)`, where `<scratch>/link` → `<denied>/sub`, *downloaded* `log.txt` and overwrote the deny-listed `LOG_FILE` with the Drive file's content. `many_checks()`' `_realpath` collapses `..` with `abspath` before resolving the symlink, so the check sees `<scratch>/log.txt`, while the write's `<scratch>/link/../log.txt` lands in `<denied>`. At round 1's head the plain `realpath` refused it. Sent back on the PR.

**Result (2026-10-16, PR #1039 round 3 @ b8d0ced, Sky) ⚠️ PARTIAL: steps 1, 2, 4, 6 against `LOG_FILE`; step 3 pending**
Fresh SSE subprocess on this head, explicit `LOCAL_FILE_ACCESS=full`, `LOG_FILE=<denied>/log.txt` (the same substitution as rounds 1–2). Steps 1, 2, 4: the same refusals as round 2. Step 5: `{"mode": "full", "explicit": true, ...}`. Step 6, with `<scratch>/link` → `<denied>/sub` and a Drive folder holding `log.txt` plus the control files `a.txt` and `ok.txt`: `download_folder(local_path="<scratch>/link/..", skip_if_exists=false)` put `log.txt` in `failed` with `<scratch>/link/../log.txt is one of this server's own credential, config, cache, or log files and can't be written by a tool`. The same probe through `sync_folder(direction="download")` failed `log.txt` with the same refusal plus `; not synced`. `LOG_FILE`'s head was unchanged after both. The control files landed in `<denied>`, not `<scratch>`, so the walk really did go through the symlink. Step 3 still pending (the auto-mode classifier and the slot token's missing Gmail scope, as in round 1).

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
requires-oauth; step 5 covered by server://auth-status local_file_access mode "full".

---

### TC-I59: an invalid local-file setting stops the server at startup with a one-line message (issue #796) ⚠️ local-filesystem

**Background:** `LOCAL_FILE_ACCESS`/`LOCAL_FILE_ROOTS` are validated at import, but an invalid setting only resolves to `off` there, with its reason recorded. `main()` exits on it before serving, so a misconfigured server never serves, while `mcp-gee-sweet auth` and `scripts/gen_tool_docs.py` still run (PR #1039 QA round 1, finding 4). A `LOCAL_FILE_ROOTS` set outside `roots` mode only warns. With `ENABLED_TOOLS` naming a local-only tool that `off` mode drops, the server warns which ones are missing and why.

**Setup:** none beyond a checkout of this branch. No Google credentials are needed.

**Action**
Run each with `uv run mcp-gee-sweet --transport sse` and `HOST=127.0.0.1`, `PORT=<free port>`, stderr captured. Stop a server that starts with SIGTERM after 3 seconds.
1. `LOCAL_FILE_ACCESS=everything`
2. `LOCAL_FILE_ACCESS=roots` with `LOCAL_FILE_ROOTS` unset
3. `LOCAL_FILE_ACCESS=roots`, `LOCAL_FILE_ROOTS=/no/such/dir`
4. `LOCAL_FILE_ACCESS=full`, `LOCAL_FILE_ROOTS=/tmp`
5. `LOCAL_FILE_ACCESS=off`, `ENABLED_TOOLS=sync_folder,get_sheet_data`
6. `LOCAL_FILE_ACCESS=roots`, `LOCAL_FILE_ROOTS=/no/such/dir`, running `uv run mcp-gee-sweet auth --help` instead of the server
7. `LOCAL_FILE_ACCESS=everything`, running `uv run python scripts/gen_tool_docs.py` instead of the server

**Checks**
- 1: exits non-zero with `mcp-gee-sweet: LOCAL_FILE_ACCESS='everything' isn't valid (use full, roots, or off)` and no traceback. Steps 1–3 also log one `ERROR mcp_gee_sweet.local_files Local file access is off: <the same reason>` line first
- 2: exits non-zero with `mcp-gee-sweet: LOCAL_FILE_ACCESS=roots needs LOCAL_FILE_ROOTS, a ':'-separated list of directories`
- 3: exits non-zero with `mcp-gee-sweet: LOCAL_FILE_ROOTS entry '/no/such/dir' isn't an existing directory`
- 4: starts; stderr has `LOCAL_FILE_ROOTS is set but ignored: it applies only when LOCAL_FILE_ACCESS=roots`
- 5: starts; stderr has `LOCAL_FILE_ACCESS=off: not registering local-only tools named in ENABLED_TOOLS: sync_folder`, and an SDK `list_tools` returns only `get_sheet_data`
- 6: exits 0 and prints `usage: mcp-gee-sweet auth`, so a root that isn't mounted yet doesn't block re-authorization
- 7: exits 0 with `gen_tool_docs: docs already up to date` (on a clean checkout), and `git status` shows no change to `docs/tools.md`: the generated docs list every tool whatever the policy

**Cleanup:** SIGKILL any server still running.

**Result (2026-10-15, PR #1039 round 1 @ fb49e7d, Sky) ✅ PASS**
`uv run mcp-gee-sweet --transport sse`, stdout and stderr captured. Steps 1–3: exit 1 with exactly the three expected one-line messages and no traceback. Step 4: started; `WARNING mcp_gee_sweet.local_files LOCAL_FILE_ROOTS is set but ignored: it applies only when LOCAL_FILE_ACCESS=roots`. Step 5: started; `WARNING mcp_gee_sweet.server LOCAL_FILE_ACCESS=off: not registering local-only tools named in ENABLED_TOOLS: sync_folder`, and SDK `list_tools` returned `["get_sheet_data"]`. Exit 143 for the started servers is uv forwarding SIGTERM.

**Result (2026-10-15, PR #1039 round 2 @ 6ba5297, Sky) ✅ PASS**
Steps 1–3: exit 1 with the three one-line messages, no traceback, each preceded by `ERROR mcp_gee_sweet.local_files Local file access is off: <the same reason>`. Step 4: started, with the ignored-roots warning. Step 5: started, with the `ENABLED_TOOLS` warning, and `list_tools` returned `["get_sheet_data"]`. Step 6: exit 0, `usage: mcp-gee-sweet auth [-h] [--no-browser] [--include-tools INCLUDE_TOOLS]`. Step 7: exit 0, the `ERROR ... isn't valid` line, then `gen_tool_docs: docs already up to date`; `git status` clean.

**Result (2026-10-16, PR #1039 round 3 @ b8d0ced, Sky) ✅ PASS**
Steps 1–3: exit 1 with the three one-line messages, each preceded by the `ERROR ... Local file access is off: <reason>` line, no traceback. Step 4: started, with the ignored-roots warning. Step 5: started, with the `ENABLED_TOOLS` warning; `list_tools` returned `["get_sheet_data"]`. Step 6: exit 0, `usage: mcp-gee-sweet auth [-h] [--no-browser] [--include-tools INCLUDE_TOOLS]`. Step 7: `gen_tool_docs: docs already up to date`, and `git status` showed no change outside this file.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs SSE, a LOCAL_FILE_ACCESS change, an invalid startup setting, or an HTTP transport.

---

### TC-I60: an HTTP request reaching a defaulted `full` policy is refused (issue #796) ⚠️ requires-oauth ⚠️ local-filesystem

**Background:** The transport default is read from `--transport` on the command line. A server served some other way, such as `uvicorn mcp_gee_sweet.server:app` directly, has no `--transport`, so it resolves to stdio's default `full` while actually serving SSE. `_timed` marks every call that arrives over HTTP, and the policy then refuses all local access unless `LOCAL_FILE_ACCESS` was set explicitly, logging one warning. The local-only tools are registered in that launch, but every call they make is refused.

**Setup:** working OAuth credentials (a call needs Google services to reach the tool body). A scratch file `<scratch>/a.txt`. `LOCAL_FILE_ACCESS` unset in the environment and in `.env`.

**Action**
1. Start `uv run uvicorn mcp_gee_sweet.server:app --host 127.0.0.1 --port <free port>`. With the SDK's `sse_client`: `list_tools`, then `call_tool("upload_local_file", {"local_path": "<scratch>/a.txt", "parent_folder_id": QA_SCRATCH_FOLDER_ID})` twice. SIGTERM the server
2. Same with `LOCAL_FILE_ACCESS=full` set, calling `upload_local_file` once

**Checks**
- 1: `upload_local_file` is listed. Both calls fail with `local file access is disabled for HTTP requests unless LOCAL_FILE_ACCESS is set explicitly`, nothing is uploaded, and the server log has exactly one `Refusing local file access for an HTTP request` warning
- 2: the upload succeeds (an explicit `full` over HTTP is the operator's choice)

**Cleanup:** `delete_file` the step-2 upload. SIGTERM the server.

**Result (2026-10-15, PR #1039 round 1 @ fb49e7d, Sky) ✅ PASS**
`uv run uvicorn mcp_gee_sweet.server:app` (uvicorn 0.47.0), OAuth, SDK `sse_client`. Step 1: `upload_local_file` listed; both calls returned `local file access is disabled for HTTP requests unless LOCAL_FILE_ACCESS is set explicitly`; the run's stderr has exactly one `Refusing local file access for an HTTP request` warning; nothing uploaded. Step 2 (`LOCAL_FILE_ACCESS=full`): upload succeeded, no warning. Upload deleted.

**Result (2026-10-15, PR #1039 round 2 @ 6ba5297, Sky) ✅ PASS**
Same driver, fresh subprocesses on this head. Step 1: listed, both calls refused, exactly one tripwire warning in the run's stderr. Step 2: upload succeeded, no warning. Scratch folder deleted.

**Result (2026-10-16, PR #1039 round 3 @ b8d0ced, Sky) ✅ PASS**
Same driver, fresh subprocesses on this head. Step 1: `upload_local_file` listed, both calls refused with `local file access is disabled for HTTP requests unless LOCAL_FILE_ACCESS is set explicitly`, and exactly one `Refusing local file access for an HTTP request` warning (the same record appears once in `LOG_FILE` and once in stderr). Step 2: upload succeeded, no warning. Scratch folder trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs SSE, a LOCAL_FILE_ACCESS change, an invalid startup setting, or an HTTP transport.

---

### TC-I61: with `MCP_SERVER_TOKEN` set, SSE and streamable HTTP reject every request without the bearer token (GHSA-mpw3-mr4r-6cqh) ⚠️ local-filesystem

**Background:** the SSE and streamable HTTP transports used to accept any request, on every interface by default, so a network peer could call every tool as the configured Google identity. `BearerAuth` (`http_auth.py`) now sits inside `SingleResponseGuard` on both apps (`server.app` and `_streamable_http_app()`), and checks every HTTP request against `MCP_SERVER_TOKEN`. A missing and a wrong token get the same 401. The token is read per request and never logged. The same wrapping covers `--reload`, which serves those apps by import string.

**Setup:** a token `T` from `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. A free port. Google access isn't needed: `AUTH_METHOD=oauth` with a nonexistent `CREDENTIALS_PATH` and `TOKEN_PATH` starts degraded, which still answers `initialize` and `list_tools`. Find this machine's LAN address (`ipconfig getifaddr en0` on macOS). Run each server in its own process group, stdout and stderr to one log (`docs/qa/run.md` §"Running server-startup and CLI cases").

**Action**
1. Start `uv run mcp-gee-sweet --transport sse` with `HOST=0.0.0.0`, `PORT=<port>`, `MCP_SERVER_TOKEN=T`, `AUTH_METHOD=oauth`, `CREDENTIALS_PATH=<nonexistent>`, `TOKEN_PATH=<nonexistent>`, `DEBUG_LEVEL=INFO`, `PYTHONUNBUFFERED=1`. Against `http://<LAN address>:<port>`, with `http.client` or `urllib`:
   a. `GET /sse` with no `Authorization` header
   b. `GET /sse` with `Authorization: Bearer wrong`
   c. `GET /sse` with `Authorization: Bearer T` followed by one extra character
   d. `POST /messages/?session_id=00000000000000000000000000000000` with no header
   e. With the SDK's `sse_client(url, headers={"Authorization": "Bearer T"})` + `ClientSession`: `initialize`, then `list_tools`
   f. Same as e with `"bearer T"` (lowercase scheme)
   SIGTERM the server.
2. Start `uv run mcp-gee-sweet --transport streamable-http` with the same environment. Against `http://<LAN address>:<port>/mcp`:
   a. `POST /mcp` with a JSON-RPC `initialize` request and `Accept: application/json, text/event-stream`, with no `Authorization` header
   b. With the SDK's `streamable_http_client` and the `Authorization: Bearer T` header: `initialize`, then `list_tools`
   SIGTERM the server.
3. Repeat step 1a and 1e once with `--transport sse --reload`.
4. `grep -c` the token `T` in every log from steps 1–3.

**Checks**
- 1a–1d, 2a: each gets `401` with `WWW-Authenticate: Bearer`, and 1a, 1b, 1c and 1d have byte-identical status, headers (apart from `date`) and body
- 1e, 1f, 2b: `initialize` succeeds and `list_tools` returns the full tool list
- 1: the log has one `Rejected an unauthenticated request` warning per rejected request, each naming the client's address and the path (`/sse`, `/messages/`), and no `Authorization` header value
- 3: same as 1a (401) and 1e (tools listed) under the reloader
- 4: `0` in every log

**Cleanup:** SIGTERM any server still running (by pid, never `pkill -f`). Delete the logs.

**Note for the probe:** an in-process probe of `server._streamable_http_app()` (Starlette `TestClient`) gets `401` with or without `MCP_SERVER_TOKEN`: with no token the middleware serves only a loopback local address (`scope["server"]`) naming a loopback `Host`, and `TestClient`'s default `testserver` is neither.

**Result (2026-10-19) ✅ PASS — Kit, GHSA-mpw3 fork PR #1 @ 46ce96b1**
Real servers on `0.0.0.0`, driven over the LAN address, token from `secrets.token_urlsafe(32)`. Steps 1a–1d and a non-ASCII `Bearer é` header all got `401` + `WWW-Authenticate: Bearer`, and 1a–1d were byte-identical (status, headers minus `date`, body `Unauthorized`). 1e, 1f and 2b listed 130 tools. 2a got `401`. Under `--reload` (step 3), 401 without the header and 130 tools with it. The log had 5 `Rejected an unauthenticated request` warnings for 5 rejections, each naming the LAN client and `/sse` or `/messages/`, and no `Authorization` value. Step 4: the token appears in no log or stdout capture. Joy's in-process repro (`_streamable_http_app()`, LAN client and Host) got `401` on `initialize` and `tools/list`, with `MCP_SERVER_TOKEN` set and unset alike, 0 tools exposed.

**Result (2026-10-19) ✅ PASS — Kit, GHSA-mpw3 fork PR #1 @ 15638736 (round 2)**
Steps 1–4 rerun on real servers after `BearerAuth` gained its `host` argument; every check matched round 1 (byte-identical `401`s, 130 tools for 1e/1f/2b and under `--reload`, one warning per rejection, token in no log).

---

### TC-I62: an HTTP transport on a non-loopback address with no token refuses to start; the default address is loopback (GHSA-mpw3-mr4r-6cqh) ⚠️ local-filesystem

**Background:** `main()` runs `http_auth.check_startup()` for `--transport sse` and `--transport streamable-http`, with or without `--reload`, before serving. A non-loopback `HOST` (anything but `127.0.0.0/8`, `::1` or `localhost`) with `MCP_SERVER_TOKEN` unset or blank stops the server, unless `ALLOW_UNAUTHENTICATED_HTTP` is `1` or `true`. Any other opt-out value stops it on every address. `HOST` now defaults to `127.0.0.1`. stdio and `mcp-gee-sweet auth` never run the check.

**Setup:** a free port for each step. `HOST`, `FASTMCP_HOST`, `MCP_SERVER_TOKEN` and `ALLOW_UNAUTHENTICATED_HTTP` unset in the environment and in `src/mcp_gee_sweet/.env`, except where a step sets them. `AUTH_METHOD=oauth`, nonexistent `CREDENTIALS_PATH`/`TOKEN_PATH`, `PYTHONUNBUFFERED=1`, stdout and stderr captured. Stop a server that starts with SIGTERM after 3 seconds.

**Action**
1. `--transport sse` with `HOST=0.0.0.0`
2. `--transport streamable-http --reload` with `HOST=0.0.0.0`, `MCP_SERVER_TOKEN=` (empty)
3. `--transport sse` with `HOST=<LAN address>`, `MCP_SERVER_TOKEN="   "`
4. `--transport sse` with `HOST=127.0.0.1`, `ALLOW_UNAUTHENTICATED_HTTP=yes`
5. `--transport sse` with `HOST=0.0.0.0`, `ALLOW_UNAUTHENTICATED_HTTP=1`. While it runs, `GET http://127.0.0.1:<port>/sse` with no header
6. `--transport sse` with `HOST=0.0.0.0`, `MCP_SERVER_TOKEN=T`, `ALLOW_UNAUTHENTICATED_HTTP=true`. While it runs, `GET /sse` with no header
7. `--transport sse` with no `HOST`. While it runs: `lsof -nP -iTCP:<port> -sTCP:LISTEN`, then `GET http://127.0.0.1:<port>/sse` with no header, then `GET http://<LAN address>:<port>/sse`
8. stdio (`uv run mcp-gee-sweet`, no `--transport`) with `HOST=0.0.0.0` and `ALLOW_UNAUTHENTICATED_HTTP=bogus`: send an `initialize` request on stdin. Point `CREDENTIALS_PATH` at a file that exists (a dummy `{"installed": {...}}` client JSON is enough): under stdio a missing client JSON exits at startup (#790's fail-fast), which isn't what this step checks
9. `uv run mcp-gee-sweet auth --help` with `HOST=0.0.0.0`
10. Launch without `main()`: `uv run uvicorn mcp_gee_sweet.server:app --host 0.0.0.0 --port <port>` with no token and no opt-out. While it runs: `GET http://<LAN address>:<port>/sse`; `GET http://127.0.0.1:<port>/sse`; the same loopback GET with `Host: evil.example:<port>`; the same with `X-Forwarded-For: 127.0.0.1` sent to the LAN address. Then `grep -c 'MCP_SERVER_TOKEN is unset'` the log. Then relaunch the same command twice more: with `HOST=0.0.0.0` and `ALLOW_UNAUTHENTICATED_HTTP=1`, `GET http://<LAN address>:<port>/sse`; with `ALLOW_UNAUTHENTICATED_HTTP=yes` (no `HOST`), the LAN GET and the plain loopback GET
11. Optional, if Docker is available: `docker build -t mcp-gee-sweet-qa .`, then `docker run --rm -p 127.0.0.1:<port>:8000 mcp-gee-sweet-qa` with no `-e MCP_SERVER_TOKEN`
12. `--transport sse` with `HOST=127.0.0.2`, no token (macOS only answers on `127.0.0.1` until `sudo ifconfig lo0 alias 127.0.0.2 up`; remove it after with `sudo ifconfig lo0 -alias 127.0.0.2`. Without that, check the same requests in-process: Starlette `TestClient(server.app, base_url="http://127.0.0.2:8000")` with `HOST=127.0.0.2` set before import). While it runs, `GET http://127.0.0.2:<port>/sse`. Then relaunch with `ALLOW_UNAUTHENTICATED_HTTP=1` added, and send the same GET twice: once plain, once with `Host: attacker.example:<port>`
13. `--transport sse` with `HOST=0.0.0.0` and `MCP_SERVER_TOKEN=` (set but empty, as docker-compose passes it when its own `.env` lacks it), with `MCP_SERVER_TOKEN=T` in `src/mcp_gee_sweet/.env`. While it runs, `GET http://<LAN address>:<port>/sse` with no header, then with `Authorization: Bearer T`

**Checks**
- 1, 2, 3: exit 1 with one line, `mcp-gee-sweet: refusing to serve --transport <transport> on <host> without authentication: ...`, naming `MCP_SERVER_TOKEN`, `HOST` and `ALLOW_UNAUTHENTICATED_HTTP`. No traceback, nothing listens on the port, and 2 never logs `Started reloader process`
- 4: exit 1 with one line naming `ALLOW_UNAUTHENTICATED_HTTP` and `1 or true`, without echoing `yes`
- 5: starts; the log has a warning that it is serving `0.0.0.0` without authentication; the GET gets `200` and `event: endpoint`
- 6: starts; the log has `ALLOW_UNAUTHENTICATED_HTTP is ignored because MCP_SERVER_TOKEN is set`; the GET gets `401`
- 7: `lsof` shows a listener on `127.0.0.1:<port>` only; the loopback GET gets `200`; the LAN GET fails to connect
- 8: the server answers `initialize`; no refusal
- 9: prints the `auth` usage and exits 0
- 10: it starts (no `main()`, so no startup check). The LAN GET gets `401` with `WWW-Authenticate: Bearer`; the plain loopback GET gets `200` and `event: endpoint`; the `evil.example` Host and the `X-Forwarded-For` request get `401`. The grep counts `1`: one warning however many requests were refused. With `HOST=0.0.0.0` and the opt-out, the LAN GET gets `200` and `event: endpoint` (without `HOST`, the app is built for the `127.0.0.1` default, where the opt-out does nothing, so the LAN GET gets `401`). With the invalid opt-out, the LAN GET gets `401`, the loopback GET `200`, and the server keeps running with no traceback
- 11: the container exits at once with the step-1 message for `0.0.0.0`
- 12: both launches start. The plain GET gets `200` and `event: endpoint` both times (any `127.0.0.0/8` bind that starts is reachable). The `attacker.example` Host gets `401`: the opt-out does nothing on a loopback `HOST`
- 13: starts (the blank variable doesn't hide the `.env` token); the plain GET gets `401`, the bearer GET `200` and `event: endpoint`

**Cleanup:** SIGTERM any server still running (by pid). `docker rmi mcp-gee-sweet-qa` if step 11 ran. Remove the step-13 line from `src/mcp_gee_sweet/.env`.

**Result (2026-10-19) ✅ PASS — Kit, GHSA-mpw3 fork PR #1 @ 46ce96b1**
Steps 1–3: exit 1, one `refusing to serve` line naming all three settings, no traceback, nothing listening; step 2 never started the reloader. Step 4: exit 1 naming `1 or true`, `yes` not echoed. Step 5: started, serving-without-authentication warning, loopback GET `200` + `event: endpoint`. Step 6: ignored-opt-out warning, GET `401`. Step 7: `lsof` showed `127.0.0.1:<port>` only; loopback GET `200`, LAN GET connection refused. Step 8: `initialize` answered (first attempt used a nonexistent `CREDENTIALS_PATH` and hit #790's stdio fail-fast; the step now says to use a dummy client file). Step 9: usage, exit 0. Step 10: LAN `401`, loopback `200` + `event: endpoint`, `evil.example` Host `401`, `X-Forwarded-For: 127.0.0.1` to the LAN address `401`; one `MCP_SERVER_TOKEN is unset` warning over 8 rejections. Step 10's relaunches: with the opt-out and no `HOST`, the LAN GET got mcp's `421` (Host check built for the `127.0.0.1` default); with `HOST=0.0.0.0` and the opt-out, `200`; with `ALLOW_UNAUTHENTICATED_HTTP=yes`, LAN `401`, loopback `200`, no crash or traceback. Step 11: the container exited 1 about 6 s after start with the step-1 line for `0.0.0.0`.

**Result (2026-10-19) ✅ PASS — Kit, GHSA-mpw3 fork PR #1 @ 15638736 (round 2)**
Steps 1–10 rerun on real servers, all matching round 1 except the intended change in step 10: with the opt-out and no `HOST`, the LAN GET now gets our `401` (the opt-out does nothing on the loopback default), and with `HOST=0.0.0.0` and the opt-out it still gets `200`. Step 12 ran in-process (no `lo0` alias, so no sudo): with `HOST=127.0.0.2`, `check_startup` passed, the built `BearerAuth` layer had `host` `127.0.0.2`, a `127.0.0.2:8000` Host passed through, and `attacker.example:8000` got `401` + `WWW-Authenticate: Bearer`, with and without `ALLOW_UNAUTHENTICATED_HTTP=1`. Step 13: with `MCP_SERVER_TOKEN=` in the environment and the token in `src/mcp_gee_sweet/.env`, the server started on `0.0.0.0`; plain GET `401`, bearer GET `200` + `event: endpoint`; `.env` restored. Step 11 not rerun: the Dockerfile is unchanged since round 1 and the container sets no token.

---

### TC-I63: two Google identities sharing one cache DB never see each other's entries (GHSA-8jqx-w7j8-6xwm) ⚠️ local-filesystem

**Background:** every cache row carries the Google identity it was fetched as (`drive:<permissionId>`, else `sa:<service account email>`), and every read filters on it. Invalidation doesn't: `refresh_cache` and write-side invalidation reach every identity's rows. A cached sheet list is served stale only on a 5xx, 429 or network failure, never in place of a 403/404. Run the servers from this lane's own worktree, not the shared `-oauth`/`-sa` MCP servers, which serve main-checkout code.

**Setup:** a fresh scratch path `C=<tmp>/qa-cache/cache.db`, with `<tmp>/qa-cache` created (empty) before each run. An explicit `CACHE_DB_PATH` never creates its parent directory, on `develop` or the fix: with it missing, both servers log `falling back to :memory:`, share nothing, and the case passes vacuously. Check each log has no `not usable`/`unusable` line before reading any result. Two stdio servers, each driven by an SDK `stdio_client` + `ClientSession` script per `docs/qa/run.md` §"Running server-startup and CLI cases in a scoped lane pass", both with `CACHE_DB_PATH=$C`, `DEBUG_LEVEL=DEBUG` and their own `LOG_FILE`: server **A** with `AUTH_METHOD=oauth` (the fixture OAuth account), server **B** with `AUTH_METHOD=service_account`. `{SPREADSHEET_ID}` below is a scratch spreadsheet that only A can open, *not* the fixture `TEST_SPREADSHEET_ID`, which the service account can read (it's on the Shared Drive). Create it in A's My Drive root with a fresh-interpreter script (`drive.files().create(body={"name": ..., "mimeType": "application/vnd.google-apps.spreadsheet"})` on `auth._oauth_creds()`, per CLAUDE.md "MCP restart"), not with `create_spreadsheet`, which puts it in `DRIVE_FOLDER_ID`. B's service account must also have no access to A's calendars. Run steps 1–2 on the fork's `develop` first (before resetting to the fix branch), then the whole case on the fix branch.

**Action**
1. A: `list_calendars()`; record the calendar IDs. Then B: `list_calendars()`.
2. A: `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`. Then B: `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`. Then A: `refresh_cache(spreadsheet_id="{SPREADSHEET_ID}")`, and B: `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")` again.
3. With both servers stopped: `sqlite3 $C "SELECT DISTINCT principal, namespace FROM cache"`.
4. Restart A only. `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")` twice; grep A's log for `Cache hit`.
5. With A still running, start B and call `refresh_cache()` (no arguments). Then A: `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`; grep A's log again.

**Checks**
- On `develop` (the defect): B's step-1 `list_calendars` returns A's calendars, or B's step-2 `list_sheets` returns A's sheet names instead of an error. Record which.
- On the fix branch:
  - 1: B's list contains none of A's calendar IDs (only calendars B itself is subscribed to, possibly none).
  - 2: both of B's `list_sheets` calls return an error (403/404 permission text), never A's sheet names, including after A's `refresh_cache` left A's row dirty (the old stale fallback).
  - 3: two distinct `principal` values, each `drive:...` or `sa:...`; no row has an empty principal.
  - 4: the second call logs `Cache hit` (A's own entry is still served to A).
  - 5: A's call after B's flush logs no new `Cache hit` for `{SPREADSHEET_ID}` (B's invalidation reached A's row) and still returns the sheet names.

**Cleanup:** stop both servers; `rm -rf <tmp>/qa-cache`; delete the scratch spreadsheet.

**Result (2026-10-20, GHSA-8jqx fork PR #1 round 1 @ 9e6f4d06, Kit) ✅ PASS**
Two-server SDK driver from the Kit worktree, A-only scratch spreadsheet (2 sheets) in A's My Drive. Fork `develop` @ b009e72d, steps 1–2 (defect reproduced, both ways): B's `list_calendars` returned all 3 of A's calendar IDs (B itself has 0); B's `list_sheets` returned A's sheet names, and again after A's `refresh_cache` (stale fallback). A first `develop` run with `<tmp>/qa-cache` missing fell back to `:memory:` on both servers and showed no leak, hence the setup fix above. Fix branch, directory created first, no `not usable` lines: 1: B got 0 calendars, overlap with A 0. 2: both B calls 403 `The caller does not have permission`. 3: 2 distinct principals, both `drive:...` (the SA resolves its own `permissionId`), 0 empty; rows `calendar` ×2, `sheet_structure`. 4: after restart the first call re-fetched (row still dirty from step 2's refresh), the second logged `Cache hit: 2 sheets`. 5: after B's `refresh_cache()` (`invalidated: all`), A's call logged `Cached 2 sheets` and no new `Cache hit`, sheet names returned. DB file `-rw-------`. Scratch spreadsheet deleted, scratch dirs removed.

**Result (2026-10-20, GHSA-8jqx fork PR #1 round 2 @ 18a0e4bc, Kit) ✅ PASS**
Same driver, fresh A-only scratch spreadsheet, `<tmp>/qa-cache` created first, no `not usable` lines in either log. 1: B 0 calendars, overlap with A 0. 2: both B calls 403. 3: 2 distinct `drive:` principals, 0 empty. 4: second call `Cache hit: 2 sheets`. 5: after B's `refresh_cache()`, A re-fetched (`Cached 2 sheets`), no new hit. The `cache opened` lines now appear only when a cache is first used, and name the real path. Scratch spreadsheet deleted, scratch dirs removed.

**Result (2026-10-20, GHSA-8jqx fork PR #1 round 4 @ 295b5118, Kit) ✅ PASS**
Rerun after merging `develop` and the GHSA-mpw3 branch in. Same driver, fresh A-only scratch spreadsheet, no `not usable` lines. 1: B 0 calendars, overlap with A 0. 2: both B calls 403. 3: 2 distinct `drive:` principals, 0 empty. 4: second call `Cache hit: 2 sheets`. 5: after B's `refresh_cache()` (`invalidated: all`), A re-fetched (`Cached 2 sheets`), no new hit. DB `-rw-------`. Outside the case, over SSE with `MCP_SERVER_TOKEN` set: an unauthenticated `GET /sse` got `401` before any cache DB existed; two authenticated connections both bound the same `drive:` principal, and the second was served from the first's entry. Scratch spreadsheet deleted, scratch dirs removed.

---

### TC-I64: the default cache location is per-user and owner-only; a symlinked cache isn't used (GHSA-8jqx-w7j8-6xwm) ⚠️ local-filesystem

**Background:** with `CACHE_DB_PATH` unset, the DB is `~/Library/Caches/mcp-gee-sweet/cache.db` (macOS), or `$XDG_CACHE_HOME` / `~/.cache` plus `mcp-gee-sweet/cache.db` (Linux). The directory is `0700`, the DB and its `-wal`/`-shm` files `0600`. A directory or file owned by another user, or a symlink in place of one, makes the server warn and cache in memory. The old `/tmp/mcp_gee_sweet.db` is tightened to `0600` if it's ours, never deleted. Importing the package creates nothing.

**Setup:** a scratch `HOME=<tmp>/home` (created, empty), `XDG_CACHE_HOME` unset, `CACHE_DB_PATH` unset in the environment and in `src/mcp_gee_sweet/.env`, `umask 022`. A stdio server driven by an SDK client script (as in TC-I63), `AUTH_METHOD=oauth` with `TOKEN_PATH`/`CREDENTIALS_PATH` pointing at the fixture files, `DEBUG_LEVEL=DEBUG`, `LOG_FILE` set. `D` below is the platform's default cache directory under the scratch home.

**Action**
1. `HOME=<tmp>/home uv run python -c "import mcp_gee_sweet.server"`, then `find <tmp>/home`.
2. Start the server; `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`; stop it. `stat -f '%Sp %N' D D/cache.db*` (Linux: `stat -c '%A %n'`).
3. `chmod 755 D`; start the server, make one call, stop it; `stat` `D`.
4. Unless a `/tmp/mcp_gee_sweet.db` already exists (then record its owner and mode, and skip the rest of this step): create it, owned by you, mode `0644`. Start the server, make one call, stop it; `stat` it.
5. `rm -rf D`, then `ln -s <tmp>/elsewhere D` (`<tmp>/elsewhere` an empty directory). Start the server, `list_sheets` twice, stop it.
6. `rm D`. Set `CACHE_DB_PATH=<tmp>/explicit/cache.db`, after creating `<tmp>/explicit` with mode `0755` and an empty `cache.db` in it with mode `0644`. Start, one call, stop; `stat` the directory and the file.
7. `CACHE_DB_PATH=:memory:`: start, one call, stop; `find <tmp>/home <tmp>/explicit -newer <tmp>/explicit/cache.db`.
8. `CACHE_DB_PATH` unset again, `LOCAL_FILE_ACCESS=full`: start, then `upload_local_file(local_path="D/cache.db", parent_folder_id="{FOLDER_ID}")` (`parent_folder_id` is required; without it the call fails argument validation before the policy check runs).

**Checks**
- 1: `find` lists only `<tmp>/home` itself: nothing created at import.
- 2: `D` is `drwx------`; `cache.db` (and any `-wal`/`-shm`) is `-rw-------`.
- 3: `D` is `drwx------` again.
- 4: `/tmp/mcp_gee_sweet.db` is `-rw-------` and still exists.
- 5: the log has `Cache file not usable (... isn't a directory), falling back to :memory:`; both calls succeed; `<tmp>/elsewhere` stays empty.
- 6: the file is `-rw-------`; its directory is still `drwxr-xr-x`.
- 7: `find` prints nothing; the call succeeds.
- 8: refused with `... is one of this server's own credential, config, cache, or log files and can't be read by a tool`; nothing uploaded.
- Another user's directory or file needs a second uid, so it's unit-tested only (`tests/test_cache_isolation.py::TestPermissions`).

**Cleanup:** `rm -rf <tmp>/home <tmp>/elsewhere <tmp>/explicit`. If step 4 created `/tmp/mcp_gee_sweet.db`, delete it and its `-wal`/`-shm`.

**Result (2026-10-20, GHSA-8jqx fork PR #1 round 1 @ 9e6f4d06, Kit) ✅ PASS (step 4 skipped)**
SDK driver from the Kit worktree, macOS, `umask 022`, scratch `HOME` (with `UV_CACHE_DIR` pointed at the real uv cache so `uv` itself writes nothing under it). 1: `find` lists only `<tmp>/home`. 2: `D` `drwx------`, `cache.db` `-rw-------` (no sidecars left after stop). 3: `D` chmod'd to `drwxr-xr-x`, back to `drwx------` after one call. 4: skipped, `/tmp/mcp_gee_sweet.db` already exists, ours, already `-rw-------`; tightening covered by unit tests only this round. 5: log `Cache file not usable (<tmp>/home/Library/Caches/mcp-gee-sweet isn't a directory), falling back to :memory:`; both calls returned the sheet names; `<tmp>/elsewhere` empty. 6: `cache.db` `-rw-------`, `<tmp>/explicit` still `drwxr-xr-x`. 7: call succeeded, `find -newer` printed nothing. 8: first run without `parent_folder_id` failed pydantic validation (step text fixed above); rerun refused with `... is one of this server's own credential, config, cache, or log files and can't be read by a tool`, nothing uploaded. Scratch dirs removed.

**Result (2026-10-20, GHSA-8jqx fork PR #1 round 2 @ 18a0e4bc, Kit) ✅ PASS (step 4 skipped)**
Same driver, all 8 steps. 1: nothing created at import. 2: `D` `drwx------`, `cache.db` `-rw-------`. 3: `drwxr-xr-x` tightened back to `drwx------`. 4: skipped, same `/tmp/mcp_gee_sweet.db` (ours, `-rw-------`). 5: `Cache file not usable (... isn't a directory), falling back to :memory:`, and the only `cache opened` line reads `sheet_structure cache opened: :memory:` (round 1 logged the refused path here); both calls succeeded; `<tmp>/elsewhere` empty. 6: file `-rw-------`, directory still `drwxr-xr-x`. 7: `find -newer` empty. 8: refused by the deny-list, nothing uploaded. Outside the case: `check_read` now refuses `/tmp/mcp_gee_sweet.db` and `-wal` (round 1 allowed them), and in `python:3.12-slim-bullseye` (glibc 2.31) both an explicit and the default cache open and write, with the file `-rw-------` and directory `drwx------` (round 1 raised `NotImplementedError`). Scratch dirs removed.

**Result (2026-10-20, GHSA-8jqx fork PR #1 round 4 @ 295b5118, Kit) ✅ PASS (step 4 skipped)**
Rerun after merging `develop` and the GHSA-mpw3 branch in. Same driver, all 8 steps, every check matching round 2. 1: nothing created at import. 2: `D` `drwx------`, `cache.db` `-rw-------`. 3: tightened back to `drwx------`. 4: skipped, same `/tmp/mcp_gee_sweet.db` (ours, `-rw-------`). 5: `not usable ... falling back to :memory:`, `cache opened: :memory:`, both calls succeeded, `<tmp>/elsewhere` empty. 6: file `-rw-------`, directory still `drwxr-xr-x`. 7: `find -newer` empty. 8: refused by the deny-list. Scratch dirs removed.

---

### TC-I65: the first calls after a long idle don't fail on a stale connection (issue #1052)

**Background:** `thread_http` caches one transport per worker thread, and a thread's pooled keep-alive connection sits unused while the server is idle. Before #1052, the first request on a connection Google had since dropped failed with no retry: `[Errno 54] Connection reset by peer` at once, or `[Errno 60] Operation timed out` after 50–200 s. In a wide `get_multiple_sheet_data` call that showed up as one per-query `error` among otherwise correct results. Now a pooled connection idle longer than `_IDLE_RECONNECT_SECONDS` (wall-clock time, so a laptop's sleep counts) is closed before reuse, a connection that fails is closed rather than left pooled, and a read (GET, HEAD, or a method-override GET) or a token refresh that still hits a dead connection is resent once. Writes are never resent, so step 3 checks that a write after idle succeeds on its first attempt. The mocked unit tests can't show what Google's front end actually does to an idle connection, so this needs a live server and real idle time.

**Setup:** a server that has already made a few calls, so its worker threads hold pooled connections. Before each step, leave it idle (no tool calls at all) for **at least 10 minutes**, the idle time that reproduced the defect in the v0.9.2 pass.

**Action**
1. After the idle wait, call `get_multiple_sheet_data` with 12 single-cell queries: `queries` = `[{"spreadsheet_id": "{SPREADSHEET_ID}", "sheet": "Sales", "range": "A1"}, …]` over `A1`, `B1`, `C1`, `A2`, `B2`, `C2`, `A3`, `B3`, `C3`, `A4`, `B4`, `C4`. Time the call
2. Idle again, then repeat step 1 with 24 queries, one per cell of `A1:D6`
3. Idle again, then `create_folder` with `name: "TC-I65 idle write"` and `parent_folder_id: QA_SCRATCH_FOLDER_ID`
4. Run steps 1–3 on a second server prefix too (both OAuth and service account, if both are available)

**Checks**
- 1, 2: every query returns its cell's data, none has an `error` field, and the call returns in a few seconds (no 50–200 s stall)
- 3: the folder is created on the first call, with no `Connection reset by peer`, `Broken pipe`, or `Operation timed out` error
- 4: the same on the second server

**Cleanup:** `delete_file` each `TC-I65 idle write` folder.

**Result (2026-10-19) ⚠️ PARTIAL — PR #1126 round 1 (Sky) @ 9cc9baa6**
OAuth server (`mcp-gee-sweet-sky`), warmed at 22:12 with a 12-query fan-out, then left idle 10+ min before each step. Step 1 (22:22): 12/12 cells correct, no `error`, returned in under a second. Step 2 (22:33): 24/24 correct, no `error`, under a second. Step 3 (22:44): `create_folder` succeeded on the first call; folder trashed afterwards. The server log has no live `Resending` line, so the idle close alone handled every stale connection. Didn't run: check 4. This lane has no service-account server; the service-account run is left for the release pass.

**Result (2026-10-20) ⚠️ PARTIAL — PR #1126 round 2 (Sky) @ 4e854115**
Re-run after the per-connection rewrite (`_StaleConnectionHttp`), on the OAuth server (`mcp-gee-sweet-sky`). Warmed at 23:28 with a 12-query fan-out, then left idle 10+ min before each step. Step 1 (23:39): 12/12 correct, no `error`, under a second. Step 2 (23:50): 24/24 correct, no `error`, under a second. Step 3 (00:01): `create_folder` succeeded on the first call; folder trashed afterwards. No live `Resending` line in the server log, so the per-connection idle close handled every stale connection. Didn't run: check 4. This lane has no service-account server; the service-account run is left for the release pass.

**Result (2026-10-20) ✅ PASS — v0.9.3 release pass (Aziz) @ b60f0391 (#1052 merged; `http_transport.py` identical at the c90b88d3 release candidate)**
Both main-checkout servers at once: `mcp-gee-sweet-sa` (service account) and `mcp-gee-sweet-oauth` (OAuth), processes started 22:37 after #1052's merge. Warmed at 23:02 with the 12-query fan-out (12/12 each), then no calls to either server for 10.5 min before each step. Step 1 (23:13): 12/12 correct on each, no `error`, 1.8 s and 1.5 s. Step 2 (23:24): 24/24 (`A1:D6`) correct on each, no `error`, 1.9 s and 1.5 s. Step 3 (23:35): `create_folder` in `TEST_FOLDER_ID` succeeded on the first call on each (1.9 s, 1.5 s); both folders trashed afterwards. Check 4 met: the service-account run Sky's lane couldn't do. The shared server log has no `Resending`, `Connection reset`, `Broken pipe` or `timed out` line since the servers started. Stale wording: `QA_SCRATCH_FOLDER_ID` isn't defined in `.env.template` or anywhere else; `TEST_FOLDER_ID` was used.

### TC-I66: dev and stable releases both publish through `publish.yml`, with no PyPI provenance warning (issue #1124)

**Background:** PyPI flags a release whose trusted-publisher workflow differs from the previous release's with a "Change of provenance" warning on its page. Dev builds came from `publish-dev.yml` and stable releases from `release.yml`, and a dev build always precedes a stable release, so v0.9.2's page carried the warning. PyPI compares against the previous *upload*, not the previous stable release: v0.9.1's page carries the warning although v0.9.0 and v0.9.1 both came from `release.yml`, because a `publish-dev.yml` dev build came between them. #1124 merges both tracks into `.github/workflows/publish.yml`. The first upload through `publish.yml` follows a `publish-dev.yml` build, so it's expected to carry the warning once; that's the transition, not a failure. No MCP tool or unit test reaches a GitHub Actions run or PyPI's attestation record, so this is a manual check after merge and after the next stable release.

**Setup**
- PyPI has a trusted publisher registered for `publish.yml` in this repo (the maintainer step on #1124).
- For checks 1–2: a push to `develop` touching `src/**`, `tests/**`, `pyproject.toml`, or `uv.lock` has landed since #1124 merged.
- For checks 3–5: a stable GitHub Release has been published since #1124 merged, **and** at least one dev build published through `publish.yml` before it (checks 1–2 passed first). Merging #1124 alone publishes nothing, since it touches no `src/**`. If the release's predecessor upload is still a `publish-dev.yml` build, check 5 fails while the workflow is behaving correctly: record SKIP for check 5, not FAIL.

**Action**
1. `gh run list --workflow=publish.yml --event push --limit 1`, then `gh run view <run-id>`. Note the published `X.Y.Z.devN` version from the build log or `pip index versions mcp-gee-sweet --pre`.
2. Read the dev wheel's provenance: `curl -s https://pypi.org/pypi/mcp-gee-sweet/<version>/json` for the `.whl` filename in `urls[]`, then `curl -s "https://pypi.org/integrity/mcp-gee-sweet/<version>/<filename>/provenance"`.
3. `gh run list --workflow=publish.yml --event release --limit 1`, then `gh run view <run-id>`.
4. Repeat step 2 for the stable version's wheel.
5. Open `https://pypi.org/project/mcp-gee-sweet/<stable version>/`.

**Checks**
- 1, 3: the run completed with `success`; its jobs are `Run tests`, `Build distribution`, and `Upload to PyPI`, and `Upload to PyPI` ran.
- 2, 4: every `attestation_bundles[].publisher` is `{"kind": "GitHub", "repository": "khuisman/mcp-gee-sweet", "workflow": "publish.yml", ...}`. `release.yml` or `publish-dev.yml` there means the upload didn't go through the new file.
- 5: the release page shows no "Change of provenance" warning.

**Re-run cadence:** once after the first qualifying `develop` push following #1124's merge (checks 1–2), and once at the first stable release after that (checks 3–5). After that, only if `publish.yml` is renamed or split.

**Result (2026-10-20) ✅ PASS (checks 1–2) — v0.9.3 release pass (Aziz) @ c90b88d3**
Check 1: the two `publish.yml` push runs after #1124's merge, 39553304435 (746136d4, the GHSA-mpw3 merge) and 39553920594 (c90b88d3, the GHSA-8jqx merge), both concluded `success`, with jobs `Run tests`, `Build distribution` and `Upload to PyPI`, all `success`. Check 2: the wheels for `0.9.3.dev34` and `0.9.3.dev35` each carry one attestation bundle whose publisher is `{"kind": "GitHub", "repository": "khuisman/mcp-gee-sweet", "workflow": "publish.yml", "environment": null}`. So PyPI's last upload before the stable 0.9.3 comes through `publish.yml`. Checks 3–5 run after 0.9.3 is published.

**Result (2026-10-20) ✅ PASS (checks 3–5) — v0.9.3 stable release (Aziz) @ b5e2810b**
Check 3: `publish.yml` run 39557996212, event `release`, on b5e2810b, concluded `success`, with `Run tests`, `Build distribution` and `Upload to PyPI` all `success`. Check 4: the `mcp_gee_sweet-0.9.3-py3-none-any.whl` provenance has one attestation bundle, publisher `{"kind": "GitHub", "repository": "khuisman/mcp-gee-sweet", "workflow": "publish.yml", "environment": null}`; the uploads just before it were `0.9.3.dev34` and `dev35`, both through `publish.yml`. Check 5 (Playwright, since `curl` gets PyPI's "Client Challenge" page): the 0.9.3 page's Provenance section reads "Full provenance — All 2 files in this release have provenance metadata", with no "Change of provenance" banner. Control: the 0.9.2 page, loaded the same way, still shows the "Change of provenance" banner.

### TC-I67: uploads over 100 MB complete, and a request that gets no answer fails with a readable message (issue #1129)

**Background:** `thread_http` built each per-thread transport as a bare `httplib2.Http()`, unlike the `build_http()` that `build()` gives the services' own transports. That left out two settings. First, there was no socket timeout, so a pooled connection that died silently (no RST or FIN) blocked a request until the OS gave up: 50–200 s, or a 30-minute hang seen live in the TC-MD301 run. Now each socket operation is bounded by `HTTP_TIMEOUT_SECONDS` (default 60, googleapiclient's own default). A timed-out read is resent once on a new connection; a timed-out write isn't resent, and its error says it may have landed. Second, 308 was still treated as a redirect. Drive answers each non-final chunk of a resumable upload with "308 Resume Incomplete" and no `Location`, so any upload larger than googleapiclient's 100 MB chunk failed with `Redirected but the response is missing a Location: header.` (reproduced live before the fix). Unit tests cover both against local sockets; this case checks the real Drive upload path and the configured server. Steps 3–5 need a server started with its own env, as `docs/qa/run.md` §"Running server-startup and CLI cases in a scoped lane pass" describes.

**Setup:** a 150 MB file of random bytes, e.g. `head -c 157286400 /dev/urandom > /tmp/tc-i67-150mb.bin`. The steps say `/tmp`; a lane uses its own scratch directory instead.

**Action**
1. `upload_local_file(local_path="/tmp/tc-i67-150mb.bin", parent_folder_id="{TEST_FOLDER_ID}", skip_if_exists=false)`
2. `get_file_metadata(file_id=<the id from step 1>)`
3. Start a server with `HTTP_TIMEOUT_SECONDS=abc` and `CACHE_DB_PATH=:memory:` (so the call can't be answered from cache), and call `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`
4. Start a server with `HTTP_TIMEOUT_SECONDS=0.001` and `CACHE_DB_PATH=:memory:`, and call `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`
5. On the same server as step 4, call `create_folder(name="TC-I67 timeout write", parent_folder_id="{TEST_FOLDER_ID}")`
6. Start a server with `HTTP_TIMEOUT_SECONDS=inf` and `CACHE_DB_PATH=:memory:`, and call `list_sheets(spreadsheet_id="{SPREADSHEET_ID}")`

**Checks**
- 1: the upload succeeds, with no `RedirectMissingLocation` or "missing a Location" error
- 2: `size` is `157286400`
- 3: the server log has one warning, `Ignoring HTTP_TIMEOUT_SECONDS='abc': not a positive number; using 60`, and `list_sheets` returns the sheet list
- 4: the call fails within a few seconds, not minutes, and the error starts `Google API request timed out:`. It says the connection layer resent the read once on a new connection, and names `HTTP_TIMEOUT_SECONDS`
- 5: the error starts `Google API request timed out:` and says it was a write the connection layer didn't resend, which may still have been applied. It doesn't say it was resent
- 6: the server log has one warning, `HTTP_TIMEOUT_SECONDS='inf' is over the 86400 s maximum; using 86400`, and `list_sheets` returns the sheet list, with no `OverflowError`

**Cleanup:** `delete_file` the step 1 upload, and any `TC-I67 timeout write` folder in `{TEST_FOLDER_ID}` (step 5 can time out before or after Drive creates it). Delete `/tmp/tc-i67-150mb.bin`.


**Result (2026-10-24) ✅ PASS — PR #1198 round 1 (Sky) @ e9719f2b**
Step 1: `upload_local_file` of a 157286400-byte random file into `{TEST_FOLDER_ID}` (Shared Drive, OAuth) succeeded, with no `RedirectMissingLocation`. Step 2: `size` `157286400`, `md5_checksum` matches the local file. Step 3 (stdio server, `HTTP_TIMEOUT_SECONDS=abc`, `CACHE_DB_PATH=:memory:`): one warning `Ignoring HTTP_TIMEOUT_SECONDS='abc': not a positive number; using 60`, and `list_sheets` returned `Sales | Notes & Misc | Empty`. Step 4 (`0.001`): `list_sheets` failed in 0.42 s with `Google API request timed out: no data from Google for 0.001 s. This was a read, so it was retried once on a new connection, which also failed. If Google needs longer to answer this request, raise HTTP_TIMEOUT_SECONDS.` Step 5: `create_folder` failed in 0.05 s with the write wording (`This was a write, so it wasn't retried, and Google may still have applied it ...`), and nothing about a retry. Cleanup: no `TC-I67 timeout write` folder in `{TEST_FOLDER_ID}`, since the connect timed out before the write was sent. Upload trashed. Off-case probe: `HTTP_TIMEOUT_SECONDS=inf` logs no warning, and every tool call then fails with a bare `Error executing tool list_sheets` (`OverflowError: timestamp out of range for platform time_t` from `sock.settimeout`). Sent back on the PR, not a TC-I67 check.

**Result (2026-10-24) ✅ PASS — PR #1198 round 2 (Sky) @ 4324571d**
Step 1: a fresh 157286400-byte upload into `{TEST_FOLDER_ID}` succeeded (OAuth, Shared Drive, after `/mcp reconnect`). Step 2: `size` `157286400`, md5 matches the local file. Step 3: warning `Ignoring HTTP_TIMEOUT_SECONDS='abc': not a positive number; using 60`, and `list_sheets` returned `Sales | Notes & Misc | Empty` (the first attempt got a transient Sheets `503 The service is currently unavailable` after 51 s, and the rerun passed). Step 4: failed in 0.42 s with `... This was a read, so the connection layer resent it once on a new connection, which also failed. ...`. Step 5: failed in 0.05 s with `... This was a write, so the connection layer didn't resend it, and Google may still have applied it ...`. Step 6: warning `HTTP_TIMEOUT_SECONDS='inf' is over the 86400 s maximum; using 86400`, and `list_sheets` returned the sheet list with no `OverflowError`. An extra `1e10` probe behaved the same. Cleanup: no `TC-I67 timeout write` folder; upload trashed.
