# Re-authorizing OAuth from the Failing Tool Call

**Issue:** #873 (folds in #906) · **Date:** 2026-10-06 · **Status:** implemented

## Problem

Before this change, an OAuth server with no usable token stayed broken until someone ran a terminal command and restarted it:

- **Degraded start (#811).** With no usable token at startup, a stdio server starts without Google access. Every tool returned "run `mcp-gee-sweet auth`, then restart the server or reconnect".
- **Mid-session refresh failure.** The token was revoked or expired after a good start. #811 didn't cover this. PR #905 added a re-authorize hint in `_timed`, but most tools catch the `RefreshError` in their own `except Exception` and return `{"error": ...}` before `_timed` sees it (#906). So `list_files` showed a raw tuple repr with no hint, while `list_sheets`, which lets the error propagate, showed the hint.

The goal is to recover in place, without the server opening a browser unprompted (one of #811's complaints), and without the model having to know about a separate tool.

## Client support (checked first, as the issue asked)

A probe server logged the `initialize` capabilities of Claude Code 2.1.291 as `{"elicitation": {"form": {}, "url": {}}, "roots": {...}}`, protocol `2026-07-28`. So URL-mode elicitation is the main path, and the `ToolError` text is the fallback for other clients.

Under `claude -p` (no human), a tool raising `UrlElicitationRequiredError` came back to the model as "URL elicitation was canceled by the user". A headless client never shows the link. That's the client's behavior, and the CLI alternative still covers it.

## Design

### Mechanism: `UrlElicitationRequiredError`, not an in-call `ctx.elicit_url`

The tool call raises `UrlElicitationRequiredError` (JSON-RPC `-32042`). mcp's `Tool.run` re-raises an `MCPError` as a protocol error instead of wrapping it as a tool result.

The in-call alternative, `ctx.elicit_url()`, sends a server-to-client request and keeps the call open while the user decides. It would hold the call for up to `OAUTH_CONSENT_TIMEOUT_SECONDS`, and it needs a back-channel, which a 2026-07-28 request context may lack (`NoBackChannelError`). The error form returns immediately, and the consent runs on independently of any call.

When the consent completes, the server sends `notifications/elicitation/complete` to every session it offered the URL to. This is best effort: a gone session or a missing channel is logged at debug level and ignored.

### Noticing a rejected refresh in every tool

The issue comment pointed at `execute_in_thread` as the single choke point. It isn't quite one: media downloads (`MediaIoBaseDownload.next_chunk`) set `request.http = thread_http(service)` and never go through `execute_in_thread`. Every Google request does go through `thread_http`'s transport, so that's where the hook sits. `_RefreshTrackingHttp` (an `AuthorizedHttp` subclass) records a non-retryable `RefreshError` on a per-call `CallAuthState` before re-raising it.

`_timed` opens the state with `track_refresh_failures()`, a `ContextVar` holding a mutable object. Gathered tasks and `asyncio.to_thread` workers copy the context, and the copy points at the same object, so a failure on any of them is seen. After the tool body returns or raises, a recorded failure replaces whatever the tool produced (including an `{"error": ...}` dict) with the re-authorization offer. The 86 tool-level `except` blocks stay untouched.

A retryable `RefreshError` (the token endpoint's own 5xx) isn't recorded: it says nothing about the token.

### Recovery order (`reauth.py`)

Both entry points, `before_call` (degraded connection) and `after_refresh_failure` (mid-session), try in order:

1. **Adopt a token this process already got.** `publish_oauth_credentials` bumps a process-wide generation. A context built from an older generation rebuilds its services in place (`apply_oauth_credentials`) on its next call. One `TOKEN_PATH` means one token for every connection.
2. **Reload `TOKEN_PATH`** (`load_saved_token`, on a daemon thread like the rest of the auth code). This picks up a token `mcp-gee-sweet auth` wrote, so the CLI no longer needs a restart. In the mid-session case a reloaded token with the *same* refresh token as the failing one is rejected: it's the same revoked grant. Two guards (PR #925 QA round 1):
   - **The reload doesn't touch the Gmail gate.** It runs `_oauth_creds(record_gmail=False)`, so the process-wide `_gmail_unauthorized_message` isn't reset and re-set by every connection's reload, whether or not anything gets adopted. `publish_oauth_credentials` sets the gate from the token actually adopted.
   - **An unchanged file isn't reloaded again.** After a reload finds nothing to adopt, `TOKEN_PATH`'s `(mtime_ns, size)` is remembered, and the reload is skipped until the file changes. Without this, a revoked token on disk cost a failing refresh round-trip and a warning on every call. `mcp-gee-sweet auth` rewrites the file, so it's still picked up.
3. **Offer consent.** Start or join the shared listener and raise the elicitation, or the `ToolError` with the URL. The offer states the time the link actually has left (`_ConsentAttempt.remaining_seconds`), not the full timeout. A tool call's own attempt with less than `min(60, timeout/2)` seconds left is replaced by a fresh one rather than handed out. The replaced attempt isn't stopped: a client already holds its link, and its offer promised that link until its deadline. In PR #925's second round it was stopped, and QA reproduced a link dying with 7.9s of its stated time left. So two listeners can overlap, for at most `min(60, timeout/2)` seconds. The two attempts share a `group`, and whichever completes publishes the token and sends `elicitation/complete` to both attempts' clients.

When a degraded connection adopts a token, the tool body then runs normally. When a mid-session failure adopts one, the call ends with "a newer token was loaded; retry the call". The tool isn't re-run automatically, because a multi-request tool may already have made changes before the refresh failed. So the offer carries what the tool itself reported (`describe_outcome`, truncated at 1,500 characters): "The call may have partly completed before the token was rejected; the tool reported: ...". The model then knows what may already have happened.

### One listener per process, shared with the lifespan

`start_user_consent` reuses `_consent_attempt`, the slot #833 made process-wide. So a tool call that arrives during an SSE lifespan consent offers *that* consent's URL (`_serve_consent`'s new `on_url` callback records it), and marks it `offered`: once a client holds the link, the last lifespan waiter leaving no longer stops the attempt and closes its port. `_ConsentListener` splits binding the callback server and building the URL from the wait, so the URL exists before anything blocks. The build runs on a daemon thread. If the call is cancelled during it, a done callback closes the listener once it's bound. That's a callback rather than an `await` in cleanup, so a cancel scope's re-delivered cancellation can't skip it.

The reverse doesn't join. A lifespan that needs consent while a tool call's attempt is pending doesn't wait on it: nothing would be shown to anyone for that wait. It starts without access at once, raising `OAuthConsentRequiredError(disables_consent=False)` so degrading doesn't turn consent off, and the connection's first tool call offers the same link. In PR #925's first round the lifespan did join. QA reproduced the result over SSE: a connection waited out the whole timeout with no prompt, then turned server consent off for every later connection.

A tool call's attempt (`user_started`) differs from a lifespan's in three ways:

- It never opens a browser and prints no stderr prompt; the client shows the URL.
- No waiter's departure stops it, since the call that started it has already returned. It runs to its timeout.
- Its failure doesn't turn off `_interactive_consent`.

### Restart wording

`reauthorize_instructions(restart=False)` ends "then retry the call: the server picks up the new token without a restart". It's used everywhere the token is missing or rejected: the degraded-start messages, `server://auth-status`, and the offer's CLI alternative. `mcp-gee-sweet auth` prints the same. Only the missing-scope messages (#790, including Gmail's) still say to restart, since nothing reloads the token there.

`_client_error` keeps its re-authorize hint for a non-retryable `RefreshError` that reaches it without going through the offer. A *retryable* one (the token endpoint's own 5xx) gets no hint, and it is reported as a plain error.

### The issue's open questions

- **SSE's "consent is never retried" rule.** It still governs the server's *own* consent in the lifespan, which an unattended server shouldn't keep restarting for every connection. A tool-call consent is started by a user, from a client, one at a time. Its failure only means the next failing call offers a fresh URL. `start_user_consent` deliberately ignores `_interactive_consent`, which is also what lets it run under stdio.
- **`mcp-gee-sweet auth`'s role.** It becomes the secondary path. It's still documented in `docs/auth.md` and still named in every offer, for clients that can't show the link. It's still the only fix for a missing-scope token (below).

### `thread_http` cache

Rebuilding the services makes new service objects, and CPython can reuse a freed object's `id()`. The per-thread transport cache was keyed on `id(service)` alone, so a rebuilt service could get a stale transport holding the revoked credentials. A cached transport is now reused only while `http.credentials is service._http.credentials`.

## Limitations

- **Missing scopes aren't offered.** A token lacking a base scope still stops a stdio server at startup (#790), and a Gmail-only shortfall still degrades only the Gmail tools. Both still need `mcp-gee-sweet auth` and a restart.
- **The callback listens on `localhost`.** The browser that completes the consent must run on the server's machine. This already applied to the lifespan's own SSE consent; it matters more now that a remote SSE client can be shown the link.
- **A headless client cancels the elicitation.** The user never sees the link (see above).
