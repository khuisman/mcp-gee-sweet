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
