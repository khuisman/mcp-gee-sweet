import asyncio
import threading
from typing import Any

import httplib2
from google_auth_httplib2 import AuthorizedHttp

_thread_local = threading.local()


def thread_http(service: Any) -> AuthorizedHttp:
    """Per-thread HTTP transport for concurrent .execute() calls against `service`.

    asyncio.to_thread() runs .execute() calls in real OS threads; the shared service
    objects built once in spreadsheet_lifespan each carry a single httplib2 transport
    that isn't safe for concurrent use from multiple threads. Each thread gets its own,
    lazily built from the service's existing credentials and cached for reuse — do not
    remove this in favor of the shared service objects' default transport.
    """
    cache = getattr(_thread_local, "http_by_service", None)
    if cache is None:
        cache = {}
        _thread_local.http_by_service = cache
    key = id(service)
    if key not in cache:
        cache[key] = AuthorizedHttp(service._http.credentials, http=httplib2.Http())
    return cache[key]


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
