import asyncio
import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httplib2
from google.auth.exceptions import RefreshError
from google_auth_httplib2 import AuthorizedHttp

_thread_local = threading.local()


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


class _RefreshTrackingHttp(AuthorizedHttp):
    """AuthorizedHttp that records a failed token refresh before raising it. Every
    request goes through here: `.execute()` via execute_in_thread, and the media
    downloads that set `request.http = thread_http(...)` themselves."""

    def request(self, *args: Any, **kwargs: Any) -> Any:
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
        http = cache[key] = _RefreshTrackingHttp(credentials, http=httplib2.Http())
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
    """
    return await asyncio.to_thread(lambda: execute_fn(http=thread_http(service)))
