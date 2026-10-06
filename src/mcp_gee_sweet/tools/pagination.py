from collections.abc import AsyncIterator, Callable
from typing import Any

from ..auth import execute_in_thread


class PageLimitExceeded(Exception):
    """A list endpoint kept returning a nextPageToken past the caller's page bound."""

    def __init__(self, max_pages: int):
        super().__init__(
            f"stopped after {max_pages} pages: the API was still returning a nextPageToken"
        )
        self.max_pages = max_pages


async def iter_pages(
    build_request: Callable[[str | None], Any],
    service: Any,
    *,
    max_pages: int,
) -> AsyncIterator[dict[str, Any]]:
    """Yield each page of a Google list endpoint, following nextPageToken.

    `build_request(page_token)` returns the unexecuted request for one page; it
    gets `None` for the first page (googleapiclient drops None-valued params, so
    passing `pageToken=page_token` straight through is fine). Pages are fetched
    sequentially, since each token comes from the previous response.

    Raises PageLimitExceeded after yielding `max_pages` pages if the API still
    returns a token, so a token that never goes falsy can't hang the call. A
    caller that wants partial results keeps what it accumulated from the pages
    already yielded, the same as for an API error raised mid-iteration (#615).

    Shared by every tool that exhausts a paginated listing internally, so the
    next one reuses this instead of hand-rolling a sixth loop (#615 item 4).
    """
    page_token: str | None = None
    for _ in range(max_pages):
        page = await execute_in_thread(build_request(page_token).execute, service)
        yield page
        page_token = page.get("nextPageToken")
        if not page_token:
            return
    raise PageLimitExceeded(max_pages)
