# Decision: Async Tool Execution (issue #183)

**Date:** 2026-07-12
**Snapshot commit:** branch `feat/ash/issue-183`

## Background

Every tool in this server made Google API calls synchronously and sequentially, even when a single tool logically does several independent calls — syncing N files, fetching N sheets, sharing with N recipients. FastMCP supports async tool handlers natively, so the fix is to convert the tool layer to `async def`, push each blocking `.execute()` call onto a worker thread via `asyncio.to_thread()`, and use `asyncio.gather()` to run genuinely independent calls within one tool concurrently instead of one at a time.

This touches all 13 tool files (`~144` `.execute()` call sites) plus two non-`@tool` helper chains that tool functions call into: `sheets/helpers.py` (`_get_sheet_id`, `_get_sheet_index`) and `docs/emitter.py` (`fill_tables` and its recursive fill chain).

## Decisions

### 1. Shared-transport thread-safety fix (new scope, found during design review)

Direct inspection of `mcp`'s `func_metadata.call_fn_with_arg_validation` confirmed sync tool handlers previously ran straight on the event loop thread — the server was effectively single-threaded for tool execution, so there was no existing thread-safety exposure. Converting to `to_thread`/`gather` changes that: multiple `.execute()` calls can now genuinely run in parallel OS threads against the *same* `sheets_service`/`drive_service`/etc. objects that `auth.py` builds once at startup and reuses forever. `google-api-python-client`'s default `httplib2`-backed transport is not safe for concurrent use of one instance — a new risk introduced by this change, not a pre-existing one, and in scope to fix here.

**The mechanism:** `googleapiclient.http.HttpRequest.execute()` accepts an `http=` override — no need to rebuild whole service objects per thread, just swap the transport at the call site. `auth.py` gained a `thread_http(service)` helper: a `threading.local()`-cached `AuthorizedHttp` per (thread, service), built from the credentials already attached to that service's `Resource` object (`service._http.credentials`, set by `googleapiclient.discovery.build()`). Standard call sites became `await asyncio.to_thread(chain.execute, http=thread_http(service))`.

`MediaIoBaseDownload.next_chunk()` doesn't accept an `http=` override (it reads `self._request.http` internally), so the three/four chunked-download sites (`export_file`, `download_file`, `download_folder`, `sync_folder`) instead set `request.http = thread_http(drive_service)` before starting the chunked loop, then wrap the whole loop in one `to_thread` call.

### 2. `cache.py` (SQLite) stays fully synchronous

Deliberate, not an oversight: only the actual Google API `.execute()` call inside a cache-touching helper gets `to_thread`-wrapped; the sync `cache.get()`/`cache.store()` calls stay on the single event-loop thread, interleaved between `await`s. Since only one coroutine runs on the event loop at a time (`to_thread` only offloads the specific blocking call it wraps), concurrent SQLite access never actually occurs even under `gather()` — no lock needed. A comment at the top of `cache.py`'s `_open()` spells this out so a future edit doesn't "fix" it by adding `to_thread`/locks that would actually introduce the race they're meant to prevent.

### 3. `gather()` restructuring — six tools, uniform pattern

Named in the issue: `sync_folder`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`. Extended per the issue's own "any tool that currently loops over API calls serially" scope to three more found during design review: `import_csv_to_sheet` (chunked row writes to disjoint ranges), `share_spreadsheet`, `share_file` (per-recipient/per-permission loops).

**`batch_update_cells` scope correction:** the issue named it as a parallelization target, but it has no loop over API calls — it's a single already-batched `.execute()` call (the loop present is a pure Python list comprehension building the request body, no I/O). Gave it the standard async/`to_thread` conversion only; there was nothing to `gather()`.

Shared pattern across all six: extract per-item work into an inner `async def`, gather with `return_exceptions=True`, reduce in one pass afterward. `return_exceptions=True` matters even though each per-item helper already catches its own errors and returns a tagged result — it also lets every in-flight item finish before an unexpected exception (a genuine bug, not the expected per-item failure path) surfaces, instead of orphaning still-running tasks. `gather()` preserves the order of the awaitables list, so `get_multiple_sheet_data`/`get_multiple_spreadsheet_summary` need no reordering. `share_spreadsheet`/`share_file`/`sync_folder` bucket results by outcome (successes/failures, uploaded/downloaded/failed) — relative order *within* a bucket now reflects completion order, not input order, since each item still carries its own identity (email, filename) in its result. `sync_folder`'s reduce pass also sums `total_bytes` and populates five separate lists from one tagged-result stream, avoiding concurrent mutation of shared accumulators entirely (only the single-threaded reduce pass after `gather()` touches them).

`asyncio.to_thread`'s default executor caps at `min(32, os.cpu_count() + 4)` workers, shared process-wide — a batch larger than that queues rather than fully parallelizing. Timing stays accurate, just with diminishing returns past the cap; noted at each `gather()` site so it isn't mistaken for a bug later.

### 4. Test infrastructure: `pytest-asyncio`, `asyncio_mode = "auto"`

Confirmed via user decision over two alternatives (anyio pytest plugin, manual `asyncio.run()` wrapper per test). `asyncio_mode = "auto"` means converting a test is purely mechanical — `def test_x():` → `async def test_x():` plus `await` at each call site — no `@pytest.mark.asyncio` decorators needed anywhere. `MagicMock`/`Mock`-based service chains needed no changes; `asyncio.to_thread(mock_chain.execute, http=...)` runs the sync mock callable in a worker thread and awaits the result normally — the mocks don't know or care about the extra `http=` kwarg.

### 5. A bug the mocked test suite structurally couldn't catch

`_timed`'s wrapper (`server.py`) became unconditionally `async def ...: return await func(...)`. Any tool registered through `tool()` that was *not* itself converted to `async def` would break at call time — `await` on a plain sync return value raises `TypeError`. `tools/cache.py`'s three tools (`get_cache_ttl`, `set_cache_ttl`, `refresh_cache`) have zero `.execute()` calls, so they were correctly left out of the `.execute()`-driven conversion sweep — but that left them as plain `def` under an `async def`-only wrapper. Every existing unit test captures the raw inner function via a fake tool registry, bypassing `_timed` entirely, so `pytest -q` stayed green throughout even with this broken. Only caught by importing `server.py` directly and checking `inspect.iscoroutinefunction()` on every registered tool's unwrapped inner function — a check worth keeping in mind for any future addition of a tool with no I/O of its own. Fixed by converting all three to `async def` (trivial — no `await` needed inside, they just satisfy the wrapper's calling convention).

## Verification

- Full unit suite (665 tests) green; `ruff check` clean; zero unwrapped `.execute()` calls remaining (`grep -rn "\.execute()" src/mcp_gee_sweet/tools/`).
- Manual smoke test: 5 concurrent `sync_folder` uploads (each artificially delayed 0.2s in the mock) completed in ~0.22s total, not the ~1.0s a serial implementation would take — confirms real concurrency, not just non-blocking syntax.
- Live QA: see `docs/qa/tests/infra.md` TC-I24 and the six new per-tool cases (`docs/qa/tests/drive.md` TC-D176–179, `docs/qa/tests/sheets_read.md` TC-R36–37) — each forces enough distinct, identifiable concurrent items to catch cross-item attribution corruption under the real Drive/Sheets transport, which no mock can exercise.

## Round 2 — QA findings from PR #293 review (2026-07-13)

QA (`/code-review --effort high` + live testing) sent the PR back with one live-reproduced blocking bug (TC-R36) and 8 further code-review findings. All 10 are fixed here.

### 6. The actual `thread_http()` bug: eager kwarg evaluation, not per-thread isolation

The mechanism described in §1 was correct in intent but broken in every call site: `await asyncio.to_thread(chain.execute, http=thread_http(service))` evaluates `thread_http(service)` as a keyword argument *before* `to_thread` schedules the worker thread — Python evaluates all arguments to a call before making the call. So `thread_http()` always ran on the event-loop thread, and every concurrently-gathered call for a given service resolved the *same* cached transport, which then got used by N worker threads simultaneously — the exact hazard §1 was meant to prevent. Live-reproduced as intermittent SSL/connection errors under real concurrent load (`docs/qa/tests/sheets_read.md` TC-R36).

**Fix:** `http_transport.py` (new module, extracted from `auth.py` to avoid a circular import with `cache.py` — see #9 below) gained `execute_in_thread(execute_fn, service)`:

```python
async def execute_in_thread(execute_fn: Any, service: Any) -> Any:
    return await asyncio.to_thread(lambda: execute_fn(http=thread_http(service)))
```

`execute_fn` is the *bound but not yet called* `.execute` method (evaluating it is just attribute access — harmless on the event-loop thread); `thread_http(service)` is now called *inside* the lambda `to_thread` runs on the worker thread. All 141 standard call sites converted from `asyncio.to_thread(chain.execute, http=thread_http(service))` to `execute_in_thread(chain.execute, service)` via a verified 1:1 mechanical transform (every site's preceding line ended in `.execute,` and following line was a bare `)`, confirmed by scripted audit before transforming — no ambiguous block boundaries, unlike the regex-corruption incidents from round 1). One non-standard site (`export_revision`'s raw `.request()` call) fixed by hand with the same lambda-deferral pattern.

### 7. `get_spreadsheet_info` MCP resource handler was still fully synchronous

`server.py`'s `@mcp.resource("spreadsheet://{spreadsheet_id}/info")` handler predates the tool-layer conversion and was out of scope per the original plan ("tool files," not `@mcp.resource` handlers) — but that left one synchronous `.execute()` call blocking the event loop during a live API request, undermining the point of the whole conversion for that one code path. Converted to `async def`, wrapped via `execute_in_thread`.

### 8. `get_modified_time()`/`fetch_sheets()` in `cache.py` issued unwrapped blocking Google API calls

Both are cache-touching helpers, not `@tool()`-registered functions, so they were missed by the tool-file-scoped conversion sweep despite being called from async tool code (`sheets/data.py`, `sheets/helpers.py`, `sheets/structure.py`) — every call blocked the event loop for the duration of the underlying Drive/Sheets API request. Converted both to `async def`, wrapped their `.execute()` calls via `execute_in_thread`, and awaited all call sites. This is *not* the same decision as "`cache.py`'s SQLite I/O stays synchronous" (§2) — that's about the sync `cache.get()`/`store()` calls, which correctly stay unwrapped; this is about the actual network call these two helpers make before touching the cache at all.

### 9. Extracted `thread_http`/`execute_in_thread` into `http_transport.py`

Fixing #8 requires `cache.py` to call `execute_in_thread`, but `execute_in_thread` lived in `auth.py`, which already imports from `cache.py` (`SheetStructureCache` et al.) — a circular import. Moved both functions into a new `http_transport.py` with no dependency on either module; `auth.py` re-exports them (`from .http_transport import execute_in_thread, thread_http`) so none of the 13 tool files' `from ...auth import execute_in_thread, thread_http` imports needed to change.

### 10. `share_spreadsheet`/`share_file` lost the identity of a malformed input entry

Both tools' per-item `_share_one` closures extracted fields via `.get()` *before* entering their own try/except — a non-dict entry (e.g. a bare string in the `recipients`/`permissions` list) raised `AttributeError` from that very first `.get()` call, escaping to the outer `gather(..., return_exceptions=True)` catch-all, which only records `{"email_address": None, "error": ...}` / `{"entry": None, "error": ...}` — indistinguishable from any other anonymous failure if multiple bad entries were in the same batch. Fixed by wrapping each closure's entire body (field extraction included) in its own try/except, echoing the raw input back as `entry` even when extraction itself is what failed.

### 11. `import_csv_to_sheet`'s concurrent chunk writer could leave holes mid-sheet on partial failure

Before #183, a chunk-write failure stopped the (then-sequential) loop immediately, leaving a clean truncated prefix — rows 1..N present, nothing after. Under `asyncio.gather()`, chunks write concurrently, so a later chunk can succeed while an earlier one is still failing, leaving an ambiguous *hole* rather than a clean boundary, with the old code surfacing only the first raw exception and no indication of which rows were affected. Fixed: `_write_chunk` now returns a tagged `{start_row, end_row, ok, error?}` result instead of raising; on any failure the tool returns (rather than raises) an error payload with `failed_ranges` and `written_ranges` (each with exact row boundaries) so the missing rows can be retried precisely, alongside the already-created `spreadsheetId`.

### 12. Redundant per-sheet `get_modified_time()` call in `get_multiple_spreadsheet_summary`

The per-sheet loop refetched `get_modified_time(drive_service, spreadsheet_id)` for every sheet, even though `modifiedTime` is a Drive *file-level* property — identical for every sheet tab in the same spreadsheet at a given instant. The original comment justified this as catching an edit that happened mid-request, but that race-window benefit is marginal compared to N redundant Drive API calls per spreadsheet (now each one a full `execute_in_thread` round trip). Deduplicated: `sheet_mtime` now reuses `current_mtime` captured once before the per-sheet loop.

### 13. `get_multiple_spreadsheet_summary` was missing response-cap/`local_path` parity with its sibling

`get_multiple_sheet_data` and `find_in_spreadsheet` both call `enforce_response_size_cap` and support a `local_path` bypass; `get_multiple_spreadsheet_summary` did neither, so a large enough batch could silently produce an oversized response with no safety net and no way to redirect it to disk. Added both, matching the sibling tools' contract exactly (`{local_path, spreadsheet_count, bytes_written}` manifest shape).

### 14. Local-filesystem I/O sites still ran unwrapped on the event loop

Three sites did blocking disk I/O directly in async tool bodies, with no `to_thread` wrap — harmless for small files but blocking the whole event loop for however long a large read/write takes, which specifically undermines the paths meant to handle *large* results: the CSV read in `import_csv_to_sheet` (`csv.reader` over the whole file), `write_capped_result_to_disk` (exists specifically to hold data too large for the response cap), and the single-shot `dest.write_bytes(content)` sites in `transfer.py`'s Workspace-file export paths (the chunked-download closures were already correctly wrapped). All three wrapped in `asyncio.to_thread`; `write_capped_result_to_disk` becoming `async def` required `await` at its 5 call sites (`sheets/data.py` ×4, `docs/content.py` ×1).

### 15. Cache-invalidation race: a concurrent `refresh_cache()` could be silently undone

`refresh_cache(spreadsheet_id=X)` calls `mark_dirty()`, which sets `dirty=1`. Every cache class's `store()` does `INSERT OR REPLACE ... dirty=0` unconditionally. Before #183, a tool call ran to completion on the event loop with no interleaving point, so a read-then-store sequence for a given key could never be interrupted by another call — this race genuinely could not happen. Now that reads have a real `await` (the `.execute()` call), a `refresh_cache()` call landing *during* another read's in-flight fetch for the same key has its `dirty=1` silently overwritten back to `dirty=0` once that read's `store()` runs afterward — erasing the invalidation's effect with no error or signal.

**Fix:** an in-memory (not persisted — resets are fine, a fresh process has a fresh cache anyway), per-cache-instance monotonic epoch counter, bumped on every `mark_dirty`/`mark_all_dirty`. `_BaseCache` gained `snapshot_epoch()` (call before starting a fetch) and `_store_if_fresh(sql, params, epoch)` (skip the write entirely if the epoch changed between snapshot and store — i.e. an invalidation happened mid-fetch). Deliberately coarse (one counter per cache *instance*, not per-key): a concurrent invalidation for any key blocks in-flight stores for all keys in that cache, causing occasional spurious cache-miss refetches for unrelated keys rather than a precise per-key fix — a correctness-safe tradeoff against a full per-key generation-counter schema migration, scoped to the two caches actually touched by this PR's newly-concurrent code paths (`SheetStructureCache` via `fetch_sheets`/`get_multiple_spreadsheet_summary`, `SheetDataCache` via the latter's per-sheet loop). `store()` gained an optional `epoch: int | None = None` kwarg on both classes — omitting it (as every pre-existing caller does) preserves the old unconditional-write behavior exactly, so this is purely additive.

DriveFolderCache/DocContentCache/CalendarCache's `store()` methods have the identical theoretical race (any tool call is now async, so *any* two calls can interleave, not just gather()'d ones) but weren't part of this fix — out of scope since their tools aren't part of this PR's newly-introduced concurrency and Sky's finding cited only the sheets-side call sites.

### Round 2 verification

- Full unit suite (674 tests, up from 665) green; `ruff check`/`ruff format --check` clean; zero unwrapped `.execute()` calls remain.
- New regression tests: `test_server.py::TestAllToolsAreAsync` (enumerates every registered tool via `mcp._tool_manager.list_tools()` and asserts `inspect.iscoroutinefunction(inspect.unwrap(tool.fn))` — the exact check that caught #5 in round 1, now automated instead of a one-off manual introspection); `test_sharing.py`'s two `test_malformed_non_dict_entry_stays_attributable` tests; `test_files.py::test_partial_chunk_failure_reports_failed_and_written_ranges`; `test_cache.py`'s `test_store_with_stale_epoch_is_skipped`/`test_store_with_current_epoch_succeeds` pairs for both `SheetStructureCache` and `SheetDataCache`.
- Live re-verification of TC-R36 (the concurrency bug's original reproduction) still needed from QA — not re-run live as part of this fix pass; see the "Dev note" appended to that test case in `docs/qa/tests/sheets_read.md`.
