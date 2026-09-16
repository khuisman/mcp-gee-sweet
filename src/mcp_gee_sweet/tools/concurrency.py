import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from mcp.server.mcpserver import Context

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


async def report_progress_safe(
    ctx: Context, completed: int, total: int | None, message: str, label: str
) -> None:
    """Report per-item progress via ctx.report_progress, swallowing (and debug-logging)
    any failure from the notification channel itself.

    The item's own already-computed result must never be demoted to a failure just
    because the progress notification couldn't be sent (e.g. a dropped client
    session) — see #316/#319 (PR #351 review), which first established this guard for
    download_folder/sync_folder; #355 extracted it here after the same ~10-line
    try/except block was copy-pasted across 5 more call sites (QA review, PR #758).
    """
    try:
        await ctx.report_progress(completed, total, message)
    except Exception:
        logger.debug("report_progress failed for %s", label, exc_info=True)


async def gather_with_fallback(
    items: Sequence[T],
    coro_fn: Callable[[T], Awaitable[R]],
    make_fallback: Callable[[T, BaseException], R],
) -> list[R]:
    """Run coro_fn(item) concurrently for every item via asyncio.gather(...,
    return_exceptions=True), replacing any exception that escaped coro_fn with
    make_fallback(item, exc) — preserving input order.

    coro_fn is expected to catch its own per-item errors already (this is a
    defensive net for whatever still escapes, e.g. a genuinely unexpected bug), the
    same return_exceptions=True rationale every gather call site in this codebase
    already documents inline. Extracted (#355, QA review PR #758) after the same
    gather+zip+fallback shape was hand-rolled independently at 3 call sites with
    diverging safety properties — one of which (get_multiple_sheet_data) didn't
    guard against a non-dict item the way its siblings did.
    """
    raw = await asyncio.gather(*(coro_fn(item) for item in items), return_exceptions=True)
    return [
        r if not isinstance(r, BaseException) else make_fallback(item, r)
        for item, r in zip(items, raw, strict=True)
    ]
