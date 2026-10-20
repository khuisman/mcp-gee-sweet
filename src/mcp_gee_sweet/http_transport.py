import asyncio
import contextlib
import contextvars
import logging
import ssl
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError
from google_auth_httplib2 import AuthorizedHttp

logger = logging.getLogger(__name__)

_thread_local = threading.local()

_abandoned_call_hook: contextvars.ContextVar[Callable[[], None] | None] = contextvars.ContextVar(
    "mcp_gee_sweet_abandoned_call_hook", default=None
)


@contextmanager
def after_abandoned_calls(callback: Callable[[], None]) -> Iterator[None]:
    """Run `callback` on the event loop each time a request made inside this block is
    abandoned and later finishes (#907): the awaiting task was cancelled while the
    request's worker thread was already running. asyncio.to_thread can't stop that
    thread, so the request still lands after the cancellation has unwound, and a cache
    invalidated on the cancel path can be refilled from the pre-edit state in between.
    The callback runs once per such request, after it returns or raises; a request whose
    thread never started (or that finished before the cancellation) never triggers it."""
    token = _abandoned_call_hook.set(callback)
    try:
        yield
    finally:
        _abandoned_call_hook.reset(token)


class CallAuthState:
    """What a tool call's Google API requests learned about its credentials. Shared by
    every request the call makes, including those on gathered tasks and worker threads:
    both copy the context, and the copy still points at this same object."""

    def __init__(self) -> None:
        self.refresh_error: RefreshError | None = None


_call_auth_state: contextvars.ContextVar[CallAuthState | None] = contextvars.ContextVar(
    "mcp_gee_sweet_call_auth_state", default=None
)


@contextmanager
def track_refresh_failures() -> Iterator[CallAuthState]:
    """Record a refresh failure from any request made inside this block (#873). server.py's
    tool wrapper uses it so a revoked token is noticed even when the tool catches the
    error and returns `{"error": ...}`, as most tools do."""
    state = CallAuthState()
    token = _call_auth_state.set(state)
    try:
        yield state
    finally:
        _call_auth_state.reset(token)


def _note_refresh_failure(error: RefreshError) -> None:
    # A retryable failure (e.g. the token endpoint's own 5xx) says nothing about the
    # token, so it doesn't call for re-authorizing.
    if error.retryable:
        return
    state = _call_auth_state.get()
    if state is not None and state.refresh_error is None:
        state.refresh_error = error


# Measured 2026-10-19: Google's front end closes a keep-alive connection after 240 s
# idle. A FIN that arrives is harmless (httplib2 reconnects on the empty read), but one
# lost or delayed on the way, or a NAT/VPN entry that expires sooner, leaves a dead
# socket the client still thinks is open. Reconnecting well inside that window costs one
# TLS handshake after a minute of quiet.
_IDLE_RECONNECT_SECONDS = 60.0

# Methods safe to resend after a connection-level failure. A write isn't resent: the
# server may have applied it before the connection died, and a repeated create or
# append would land twice.
_RESENDABLE_METHODS = frozenset({"GET", "HEAD"})

# What a dead keep-alive connection raises on reuse: ECONNRESET/EPIPE (ConnectionError),
# ETIMEDOUT or a socket timeout (TimeoutError), or a TLS EOF.
_CONNECTION_ERRORS = (ConnectionError, TimeoutError, ssl.SSLEOFError)


class _StaleConnectionHttp(httplib2.Http):
    """httplib2.Http that doesn't reuse a pooled connection that has likely died (#1052).

    Staleness is per connection: a transport busy with one API host can still hold a
    token-endpoint connection that has sat idle since the last refresh. `_conn_request`
    is the one step every request on a connection passes through, AuthorizedHttp's
    token refresh included, so the idle check and the dead-connection close live there.

    Idle time is wall-clock time (`time.time()`), not `time.monotonic()`: the monotonic
    clock stops while a laptop sleeps, so a stdio server waking after hours would see
    seconds. A clock jump in either direction counts as idle; the worst case is one
    extra handshake.
    """

    def _conn_request(self, conn: Any, *args: Any, **kwargs: Any) -> Any:
        last_used = getattr(conn, "_mcp_gee_sweet_last_used", None)
        if last_used is not None and abs(time.time() - last_used) > _IDLE_RECONNECT_SECONDS:
            conn.close()  # httplib2 reconnects a connection whose socket is None
        try:
            return super()._conn_request(conn, *args, **kwargs)
        except _CONNECTION_ERRORS:
            # httplib2 drops a failed connection only on a socket timeout. Left pooled,
            # the dead socket would fail the next request to this host too.
            conn.close()
            raise
        finally:
            conn._mcp_gee_sweet_last_used = time.time()


class _ResendingRefreshRequest(google_auth_httplib2.Request):
    """The transport AuthorizedHttp hands the credentials for a token refresh, which runs
    before the request itself is sent. A refresh is safe to repeat, so one that hits a
    dead connection is resent once, whatever the method of the request it precedes.
    google-auth-httplib2 wraps only httplib2's own errors, so a socket error arrives raw."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().__call__(*args, **kwargs)
        except _CONNECTION_ERRORS as e:
            logger.info("Resending a token refresh on a new connection after %r", e)
            return super().__call__(*args, **kwargs)


def _is_resendable(method: str, headers: Any) -> bool:
    # googleapiclient sends a GET whose URI is over 2048 characters as a POST with an
    # x-http-method-override header; it's still a read.
    if isinstance(headers, dict):
        for name, value in headers.items():
            if name.lower() == "x-http-method-override":
                method = value
                break
    return method.upper() in _RESENDABLE_METHODS


class _RefreshTrackingHttp(AuthorizedHttp):
    """AuthorizedHttp that records a failed token refresh before raising it, and that
    survives a keep-alive connection Google dropped while the server sat idle (#1052).
    Every request goes through here: `.execute()` via execute_in_thread, and the media
    downloads that set `request.http = thread_http(...)` themselves.

    A transport is cached per worker thread, so its pooled connections sit unused
    whenever the server is idle. Once an idle connection has died without the client
    seeing the close, the first request on it fails with ECONNRESET or hangs until the
    OS times it out (ETIMEDOUT, 50-200 s). httplib2 retries neither. Over a
    `_StaleConnectionHttp` (as thread_http builds it), a connection idle longer than
    _IDLE_RECONNECT_SECONDS is closed before reuse and a connection that fails is
    closed. A read that still fails on a dead connection is resent once, and so is a
    token refresh (`_ResendingRefreshRequest`); a write is not.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._request = _ResendingRefreshRequest(self.http)

    def request(self, uri: str, method: str = "GET", *args: Any, **kwargs: Any) -> Any:
        if "_credential_refresh_attempt" in kwargs:
            # AuthorizedHttp re-entering after a 401 refresh: the outer call already
            # handles resending.
            return self._request_noting_refresh(uri, method, *args, **kwargs)
        try:
            return self._request_noting_refresh(uri, method, *args, **kwargs)
        except _CONNECTION_ERRORS as e:
            headers = kwargs.get("headers", args[1] if len(args) > 1 else None)
            if not _is_resendable(method, headers):
                raise
            logger.info("Resending %s on a new connection after %r", method, e)
            return self._request_noting_refresh(uri, method, *args, **kwargs)

    def _request_noting_refresh(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().request(*args, **kwargs)
        except RefreshError as e:
            _note_refresh_failure(e)
            raise


def thread_http(service: Any) -> AuthorizedHttp:
    """Per-thread HTTP transport for concurrent .execute() calls against `service`.

    asyncio.to_thread() runs .execute() calls in real OS threads; the shared service
    objects built once in spreadsheet_lifespan each carry a single httplib2 transport
    that isn't safe for concurrent use from multiple threads. Each thread gets its own,
    lazily built from the service's existing credentials and cached for reuse — do not
    remove this in favor of the shared service objects' default transport.

    A cached transport is reused only while it still holds the service's credentials:
    re-authorizing rebuilds the services (#873), and a new service can reuse a freed
    one's id().
    """
    cache = getattr(_thread_local, "http_by_service", None)
    if cache is None:
        cache = {}
        _thread_local.http_by_service = cache
    key = id(service)
    credentials = service._http.credentials
    http = cache.get(key)
    if http is None or http.credentials is not credentials:
        http = cache[key] = _RefreshTrackingHttp(credentials, http=_StaleConnectionHttp())
    return http


async def execute_in_thread(execute_fn: Any, service: Any) -> Any:
    """Run a Google API `.execute` bound method in a worker thread with a per-thread transport.

    `thread_http(service)` must be called *inside* the thread `asyncio.to_thread()` spawns —
    calling it eagerly as a kwarg (`http=thread_http(service)`) resolves it on the event-loop
    thread before the worker thread starts, so every concurrently-gathered call for a given
    service ends up resolving the same cached transport and sharing one httplib2.Http instance
    across multiple OS threads (issue #183 QA finding, TC-R36 — reproduced as SSL/connection
    errors under real concurrent load). Passing `execute_fn` (the unbound-but-not-yet-called
    `.execute` method) through and only calling `thread_http()` inside the lambda that
    `asyncio.to_thread()` actually runs on the worker thread fixes that.

    Inside an `after_abandoned_calls` block, a call whose awaiting task is cancelled
    while the worker thread is running triggers that block's callback once the thread
    finishes.
    """
    hook = _abandoned_call_hook.get()
    if hook is None:
        return await asyncio.to_thread(lambda: execute_fn(http=thread_http(service)))

    loop = asyncio.get_running_loop()
    lock = threading.Lock()
    finished = abandoned = False

    def _run_hook() -> None:
        try:
            hook()
        except Exception:
            logger.exception("after_abandoned_calls callback failed")

    def _run() -> Any:
        nonlocal finished
        try:
            return execute_fn(http=thread_http(service))
        finally:
            # The lock orders this against the cancel path below: either the call
            # finished first (the cancel path's own handling runs after it) or the
            # cancel path marked it abandoned first (the hook runs after it).
            with lock:
                finished = True
                notify = abandoned
            if notify:
                # RuntimeError: the loop already closed, so the process is shutting down.
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(_run_hook)

    try:
        return await asyncio.to_thread(_run)
    except BaseException:
        with lock:
            if not finished:
                abandoned = True
        raise
