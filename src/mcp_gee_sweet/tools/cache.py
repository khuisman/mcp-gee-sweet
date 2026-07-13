import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="Get Cache TTL", readOnlyHint=True))
    async def get_cache_ttl(ctx: Context = None) -> dict[str, Any]:
        """
        Read the cache TTL currently in effect for this running process.

        Returns:
            {"ttl_seconds": <int>}. All five cache namespaces are always kept in
            sync by set_cache_ttl, so a single value represents all of them.
        """
        lc = ctx.request_context.lifespan_context
        return {"ttl_seconds": lc.cache.get_ttl()}

    @tool(annotations=ToolAnnotations(title="Set Cache TTL"))
    async def set_cache_ttl(ttl_seconds: int, ctx: Context = None) -> dict[str, Any]:
        """
        Change the cache time-to-live at runtime, without restarting the server.

        This server runs in SSE mode with one shared cache per process — changing
        the TTL here affects every concurrent client session, not just the caller.
        Use get_cache_ttl first if you need to restore the previous value afterward.

        Args:
            ttl_seconds: New TTL in seconds, applied to all five cache namespaces
                (sheet structure, sheet data, Drive folders, docs, calendars).
                Must be >= 0; 0 effectively disables TTL-based caching (every
                entry is immediately eligible for expiry).

        Returns:
            Confirmation with the new TTL. Applies only to this running process —
            set CACHE_TTL in the environment/.env for the startup default.
        """
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")

        lc = ctx.request_context.lifespan_context
        previous = lc.cache.get_ttl()
        for cache in (
            lc.cache,
            lc.sheet_data_cache,
            lc.drive_folder_cache,
            lc.doc_cache,
            lc.calendar_cache,
        ):
            cache.set_ttl(ttl_seconds)

        logger.warning(
            "Cache TTL changed process-wide %ds -> %ds (affects all concurrent sessions)",
            previous,
            ttl_seconds,
        )
        return {"ttl_seconds": ttl_seconds}

    @tool(annotations=ToolAnnotations(title="Refresh Cache", readOnlyHint=True))
    async def refresh_cache(
        spreadsheet_id: str | None = None,
        doc_id: str | None = None,
        folder_id: str | None = None,
        calendar_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Invalidate caches, forcing a fresh fetch on next use.

        Args:
            spreadsheet_id: Invalidate sheet structure and data cache for this spreadsheet.
            doc_id: Invalidate doc content cache for this Google Doc file ID.
            folder_id: Invalidate Drive folder listing cache for this folder ID.
            calendar_id: Invalidate calendar metadata cache for this calendar ID.
            If none are provided, invalidates all caches (sheets, data, folders,
            docs, and calendars).

        Returns:
            Confirmation of what was invalidated
        """
        lc = ctx.request_context.lifespan_context

        if any([spreadsheet_id, doc_id, folder_id, calendar_id]):
            invalidated = []
            if spreadsheet_id:
                lc.cache.mark_dirty(spreadsheet_id)
                lc.sheet_data_cache.mark_dirty(spreadsheet_id)
                invalidated.append(f"spreadsheet:{spreadsheet_id}")
            if doc_id:
                lc.doc_cache.mark_dirty(doc_id)
                invalidated.append(f"doc:{doc_id}")
            if folder_id:
                lc.drive_folder_cache.mark_dirty(folder_id)
                invalidated.append(f"folder:{folder_id}")
            if calendar_id:
                lc.calendar_cache.mark_dirty(calendar_id)
                invalidated.append(f"calendar:{calendar_id}")
            return {"invalidated": invalidated}
        else:
            lc.cache.mark_all_dirty()
            lc.sheet_data_cache.mark_all_dirty()
            lc.drive_folder_cache.mark_all_dirty()
            lc.doc_cache.mark_all_dirty()
            lc.calendar_cache.mark_all_dirty()
            return {"invalidated": "all"}
