from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations


def register(tool):
    @tool(annotations=ToolAnnotations(title="Refresh Cache", readOnlyHint=True))
    def refresh_cache(
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
