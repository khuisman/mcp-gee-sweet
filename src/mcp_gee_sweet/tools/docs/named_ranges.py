import logging
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread

logger = logging.getLogger(__name__)


async def _create_named_range(
    docs_service, doc_cache, doc_id: str, name: str, start_index: int, end_index: int
) -> dict[str, Any]:
    """Shared implementation backing create_named_range and create_bookmark.

    Returns {"error": ...} on any API failure or a success response with no
    usable reply — never raises, matching every sibling tool in this file.
    """
    try:
        response = await execute_in_thread(
            docs_service.documents()
            .batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "createNamedRange": {
                                "name": name,
                                "range": {
                                    "startIndex": start_index,
                                    "endIndex": end_index,
                                },
                            }
                        }
                    ]
                },
            )
            .execute,
            docs_service,
        )
        replies = response.get("replies") or []
        named_range_id = (
            replies[0].get("createNamedRange", {}).get("namedRangeId") if replies else None
        )
        if not named_range_id:
            return {"error": "Docs API returned no namedRangeId for createNamedRange"}
    except Exception as e:
        return {"error": str(e)}

    doc_cache.mark_dirty(doc_id)
    return {
        "docId": doc_id,
        "namedRangeId": named_range_id,
        "name": name,
        "startIndex": start_index,
        "endIndex": end_index,
    }


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Named Range", destructiveHint=True))
    async def create_named_range(
        doc_id: str,
        name: str,
        start_index: int,
        end_index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a named range over a span of content in a Google Doc.

        A named range lets you reference a section of the document by name later
        (e.g. with ReplaceNamedRangeContentRequest via batch_update) without
        tracking raw indices yourself — the Docs API automatically shifts the
        range's bounds as content is inserted or deleted elsewhere in the doc.

        Use get_doc_structure to find start/end indices for the target span.

        Args:
            doc_id: The Google Doc file ID.
            name: Name for the range. Not required to be unique; 1-256 UTF-16 code units.
            start_index: Start of the range (inclusive).
            end_index: End of the range (exclusive).

        Returns:
            Confirmation with docId, namedRangeId, name, startIndex, endIndex.

        Note:
            Named ranges are not visible in the Docs UI and cannot be used as
            internal hyperlink targets (the Link object only supports UI-created
            bookmarks and headings, not named ranges) — they exist purely for
            programmatic reference via the API.
        """
        lc = ctx.request_context.lifespan_context
        result = await _create_named_range(
            lc.docs_service, lc.doc_cache, doc_id, name, start_index, end_index
        )
        if "error" not in result:
            logger.debug(
                "create_named_range: %r [%d, %d) in doc %s -> %s",
                name,
                start_index,
                end_index,
                doc_id,
                result["namedRangeId"],
            )
        return result

    @tool(annotations=ToolAnnotations(title="Create Bookmark", destructiveHint=True))
    async def create_bookmark(
        doc_id: str,
        name: str,
        index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a lightweight, named anchor point at a single position in a Google Doc.

        The Docs API has no dedicated bookmark-creation endpoint (Docs UI bookmarks
        can only be inserted by hand). This is a convenience wrapper around
        create_named_range that spans the single character at `index`, giving you a
        named position you can look up later without hardcoding raw indices — the
        range's bounds shift automatically as the API tracks surrounding edits.

        Use get_doc_structure to find a suitable index.

        Args:
            doc_id: The Google Doc file ID.
            name: Name for the bookmark. Not required to be unique; 1-256 UTF-16 code units.
            index: Document position to anchor at (the character at this index is
                included in the underlying named range).

        Returns:
            Confirmation with docId, namedRangeId, name, index.

        Note:
            This is not a Docs UI bookmark: it won't appear in Insert > Bookmark and
            cannot be used as an internal hyperlink target (the Link object only
            supports UI-created bookmarks and headings, not named ranges). Use
            create_named_range directly for an anchor spanning more than one character.
        """
        lc = ctx.request_context.lifespan_context
        result = await _create_named_range(
            lc.docs_service, lc.doc_cache, doc_id, name, index, index + 1
        )
        if "error" in result:
            return result
        logger.debug(
            "create_bookmark: %r at index %d in doc %s -> %s",
            name,
            index,
            doc_id,
            result["namedRangeId"],
        )
        return {
            "docId": result["docId"],
            "namedRangeId": result["namedRangeId"],
            "name": result["name"],
            "index": index,
        }
