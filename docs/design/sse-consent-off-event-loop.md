# SSE OAuth Consent Off the Event Loop

**Date:** 2026-10-01 · **Issue:** #833 (follow-up to #811 / PR #828) · **Module:** `src/mcp_gee_sweet/auth.py`

## Problem

Under `--transport sse` with no usable OAuth token, the lifespan ran the browser consent (`InstalledAppFlow.run_local_server`) directly on the event loop. Until the user consented or `OAUTH_CONSENT_TIMEOUT_SECONDS` passed:

- every other request stalled, because the loop was blocked
- SIGTERM didn't stop the server. Uvicorn's shutdown waits for open connections, and the connection holding the consent couldn't finish until its lifespan did. QA had to SIGKILL it (TC-I38, TC-I40).

## Design

### 1. The lifespan awaits a daemon thread

`_oauth_creds(defer_consent=True)` does everything up to the consent (token load, refresh), then raises `_ConsentDeferred` instead of running it. `_oauth_creds_async()` (what the lifespan calls) runs that on a daemon thread (`oauth-token`), so a hanging token endpoint can't block the loop either (PR #867 QA round 1). On `_ConsentDeferred` it awaits `_await_server_consent()`, which runs the flow on a thread named `oauth-consent`. Both go through `_run_in_daemon_thread` and `_await_unless_shutdown` (§4).

These are **daemon threads, not `asyncio.to_thread`**. Interpreter shutdown joins the default executor's worker threads, so a consent still waiting there would hold process exit until the timeout. The hang would just move from the event loop to shutdown (Kai's triage note on #833).

The sync `_oauth_creds()` (no flag) still runs the consent inline. Only scratch scripts use it that way; the server never does.

### 2. Our own callback server instead of `run_local_server`

`_serve_consent()` replaces the library's `run_local_server` for the server's consent. It does the same steps: a `wsgiref` server on a random localhost port, `flow.authorization_url()`, open the browser, take the first request, `flow.fetch_token()`. It changes two things:

- **Stoppable.** The library makes one blocking `handle_request()` call for the whole timeout, so nothing outside the call can end it early. Ours calls `handle_request()` with a 0.5s timeout in a loop, checking the deadline and a `threading.Event`.
- **Prompt on stderr without `redirect_stdout`.** The library `print()`s its prompt to stdout, and #811 moved it with `redirect_stdout(sys.stderr)`. That swaps `sys.stdout` for every thread in the process, which was harmless only while nothing else could run. We `print(..., file=sys.stderr)` ourselves.

The same first-request semantics are kept: a stray request ends the wait, and fails on the state check (TC-I40 run 2). The request handler has a 5s socket timeout: a connection that sends nothing (a browser preconnect, a port scanner) would otherwise block `handle_request()` in `readline()` with no deadline or stop check (PR #867 QA round 1). The dropped connection is logged at debug, not as a traceback. A missing browser (`webbrowser.Error`, e.g. in a container) no longer fails the flow; the URL is on stderr regardless. The request handler logs nothing, since the request line carries the authorization code. `mcp-gee-sweet auth` keeps using the library's `run_local_server`, because a terminal is where its stdout prompt belongs.

### 3. One shared attempt

`_consent_attempt` is process-wide on purpose. A connection that opens while a consent is in flight awaits the same future (one prompt, one callback port) instead of starting a second consent. Each waiter awaits it through `asyncio.shield`, so cancelling one connection doesn't cancel the attempt for the others. When the last waiter is cancelled, the stop event is set. The thread then exits within one poll and closes the port. That kind of cancellation isn't a failed attempt, so `_interactive_consent` stays on.

The "no retry after a failed attempt" rule from #811 is unchanged, but its reason has changed. The wait no longer blocks the server. Retrying would make an unattended server print a new prompt and hold each new connection for the timeout.

Consent is turned off **when the attempt settles with an error**, on the loop, before any waiter sees the failure (`_ConsentAttempt._on_settle`), not later in the lifespan. Two reasons (PR #867 QA round 1). A waterfall that falls back to a service account never reaches `_degrade_unauthorized`, so the next connection prompted again. And with the lifespan doing it, a connection opening in the few loop hops between the future failing and the lifespan degrading saw a settled attempt with consent still on, and started another.

### 4. Noticing shutdown

The lifespan runs inside the SSE request, and nothing cancels it on SIGTERM: sse_starlette ends the response stream, but `connect_sse`'s task group still waits for the body (the lifespan). So `_await_unless_shutdown` polls `sse_starlette.sse.AppStatus.should_exit` alongside the future. That flag is sse_starlette's public shutdown signal, set from uvicorn's exit handler, and it's how SSE streams learn to close. When it flips, the waiter raises `OAuthConsentRequiredError("...the server shut down before the browser consent completed...")`. The lifespan then degrades normally, the connection finishes, and uvicorn exits. The consent thread is stopped the same way as for a cancellation.

## Verified live (2026-10-01, dummy installed-app client JSON, `BROWSER=/usr/bin/true`)

| | `develop` before | this change |
|---|---|---|
| `POST /messages/` during the wait | no answer within 5s | `400` in 0.07s |
| SIGTERM during the wait | still running after 15s | exited in 0.39s, both ports released |
| A, then B during the wait (timeout 4s) | n/a | 1 prompt, both degrade "within 4s"; C afterward degrades with no wait |
| Stray callback request | | degrades in 0.08s (`MismatchingStateError`) |

An `Exception in ASGI application ... Expected ASGI message 'http.response.body'` traceback at shutdown appears on `develop` too, for any SSE stream open at SIGTERM, so it's unrelated to this change.

## Not changed

The synchronous `_oauth_creds()` (no flag) still runs everything inline, for scratch scripts. `_server_shutting_down` reads only `AppStatus.should_exit`, not sse_starlette's fallback that introspects uvicorn's signal handler: its monkey-patch works in our launch path (TC-I43).
