# HTTP Socket Timeout on the Per-Thread Transport

**Date:** 2026-10-24
**Status:** decided
**Issue:** #1129 (follow-up to #1052)

## Background

`thread_http` gives each worker thread its own transport (`decision-async-tool-execution.md` §1, §6). It built that transport as a bare `httplib2.Http()`. The services' own transports come from `googleapiclient.discovery.build()`, which uses `googleapiclient.http.build_http()`, and that function sets two things the bare constructor doesn't:

1. **A socket timeout** of `DEFAULT_HTTP_TIMEOUT_SEC` (60 s), unless `socket.setdefaulttimeout()` is set.
2. **308 removed from `redirect_codes`**, because Drive uses 308 ("Resume Incomplete") for resumable uploads, not as a redirect.

Nearly every request goes through `thread_http`, so the server effectively ran with neither.

**No timeout.** #1052 (PR #1126) closes a pooled connection after `_IDLE_RECONNECT_SECONDS` idle and resends a read once on a connection error. A connection that dies silently inside that window, with no RST or FIN, still blocks the next read until the OS gives up. That took 50–200 s in the v0.9.2 pass. On 2026-10-22 a `create_doc_from_file` call hung for 30 minutes, until the MCP client's own idle timeout, and an immediate retry finished in 4 s (#1129 comment, TC-MD301 run).

**308 as a redirect.** httplib2 follows a 308 even on a `PUT` and raises `RedirectMissingLocation` when there's no `Location` header. Drive answers each non-final chunk of a resumable upload with a 308 that has a `Range` header and no `Location`. googleapiclient's default chunk is 100 MB, so every `upload_local_file`, `upload_local_folder`, or `sync_folder` upload larger than that failed. Reproduced live on 2026-10-24 with a 101 MB upload through `thread_http` (`Redirected but the response is missing a Location: header.`); it passes after the fix, and so does a 210 MB, three-chunk upload. Nobody had reported it; it surfaced while comparing `thread_http` against `build_http()` for this ticket.

## Decisions

### 1. A per-operation socket timeout, defaulting to googleapiclient's 60 s

`thread_http` passes `timeout=_HTTP_TIMEOUT_SECONDS` to `_StaleConnectionHttp`. httplib2 hands it to the connection, which calls `settimeout()` on the socket. It bounds each blocking socket operation separately: the connect, each `send()` (an HTTPS body goes out through `SSLSocket.sendall`, which sends in pieces with the timeout reset for each piece), and each `recv()`. It is **not** a limit on the whole request. A 500 MB download or upload that keeps moving bytes never hits it. Only a server that sends nothing for that long does, which means either a dead connection or a request Google takes that long to start answering.

The default is googleapiclient's own `DEFAULT_HTTP_TIMEOUT_SEC`, imported rather than copied. It's the value every `build()`-built client already uses, including this server's shared service transports before `thread_http` replaced them per call. So the default restores googleapiclient's standard behavior rather than picking a new number. The risk the issue raised, a legitimately slow request (a large export or `batchUpdate`) being cut off, has the same exposure every default googleapiclient user has. For an operator who hits it, `HTTP_TIMEOUT_SECONDS` raises the limit (next section).

A timed-out read is resent once on a new connection. That falls out of #1052's existing handling: `TimeoutError` is already in `_CONNECTION_ERRORS`, and httplib2 closes a connection on a socket timeout. So a silently dead connection now costs one timeout plus a fresh request instead of an unbounded hang. For a read that's at most 2 × the timeout, or about 4 × when the token refresh before it hangs too: `_ResendingRefreshRequest` waits twice within one attempt, and the read's resend repeats the refresh. A caller's `execute(num_retries=N)` multiplies that again, since googleapiclient's own retry catches the timeout and resends.

### 2. `HTTP_TIMEOUT_SECONDS` is configurable

This follows the project's knobs-not-hardcoding philosophy. Valid values are positive numbers (fractions are allowed). An invalid, zero, negative, or NaN value logs a warning and uses the default: zero can't mean "no timeout", because a 0 socket timeout means non-blocking. A value over one day (`_MAX_HTTP_TIMEOUT_SECONDS`), `inf` included, logs a warning and uses one day. `settimeout()` accepts a value past the platform's `time_t`, but every later `connect()` raises `OverflowError` (`1e10` on macOS, found in PR #1198 QA round 1), which failed every tool call. It's read once at import, like `MAX_TOOL_RESPONSE_CHARS`. `socket.setdefaulttimeout()` isn't consulted, unlike `build_http()`: the server never sets it, and an env var is the documented interface.

### 3. A timeout error that says what happened

A raw socket timeout's text is just `timed out`. For a write it leaves out the one thing the caller has to know: Google may have applied the change before the response was lost, so blindly retrying can apply it twice. `_RefreshTrackingHttp.request` re-raises a timeout as a `TimeoutError` (same type, so `_timed`'s `OSError` allowlist and every `except` still match) whose message:

- states the wait (`no data from Google for 60 s`) when the socket timeout fired. When the OS's own `ETIMEDOUT` fired (an `errno` is set), it says the connection stopped responding, without claiming a duration it didn't measure;
- says the connection layer resent a read once and it also failed, or didn't resend a write, which may still have been applied, so check before repeating it. It's worded for this transport only: a caller's `execute(num_retries=N)` can still resend either one, and `markdown_export._discard_temp_doc` does;
- names `HTTP_TIMEOUT_SECONDS`.

A timeout during the token refresh that precedes a write also gets the write wording. The write itself was never sent there, but the message only says it *may* have been applied, which stays true.

### 4. 308 is not a redirect on the per-thread transport

`_StaleConnectionHttp.__init__` removes 308 from `redirect_codes`, as `build_http()` does. Google APIs don't use 308 as a redirect, and other redirect codes are still followed.

## Alternatives not taken

- **Connect timeout only.** It bounds a handshake to an unreachable host, but not the observed failure: a read on an already-established connection that died.
- **TCP keepalive on pooled sockets.** Keepalive probes would detect a dead peer even while a long server-side operation is pending, without capping think-time. But the timing options are platform-specific (`TCP_KEEPIDLE` on Linux, `TCP_KEEPALIVE` on macOS, different again on Windows), httplib2 gives no hook between `connect()` and the first request to set them, and a NAT or proxy can answer probes for a dead upstream. The socket timeout covers the observed hang on every platform with one line.
- **A whole-request deadline.** It would cut off long transfers that are working fine, which is exactly the trade-off the issue warned against.

## Verification

- `tests/test_http_transport.py::TestMatchesBuildHttp` compares the per-thread transport's settings against a live `build_http()`, so the next setting googleapiclient adds there fails CI instead of drifting silently.
- `tests/test_http_transport.py::TestSocketTimeout`: against a local server that accepts and never answers, a read raises after exactly two bounded waits, a write after one with no resend, and a timed-out connection isn't reused. Also covers the env-var parsing and the OS-`ETIMEDOUT` message. `TestResumableUploadStatus`: a 308 with no `Location` reaches the caller, and 302 is still followed. The new tests fail against the unfixed module.
- Live (fresh interpreter, OAuth, Shared Drive): a 101 MB resumable upload through `thread_http` fails before the fix; after it, the 101 MB upload and a 210 MB (three-chunk) one both pass, and the 101 MB upload passes as the service account too. With the timeout patched to 0.001 s, a Drive `files.get` and a `files.create` each fail in under 0.1 s with the read and write messages above, and the timed-out create left no folder behind.
- QA: `docs/qa/tests/infra.md` TC-I67.
