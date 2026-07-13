import logging
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Document Header", destructiveHint=True))
    async def create_header(
        doc_id: str,
        header_type: str = "DEFAULT",
        content: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add a page header to a Google Doc.

        Creates a header section and optionally inserts plain text content into it.
        For rich formatting, use insert_doc_text with the returned headerId as segmentId
        after calling this tool.

        Args:
            doc_id: The Google Doc file ID.
            header_type: "DEFAULT" (all pages, default) or "FIRST_PAGE_HEADER"
                (applies only to the first page — requires useFirstPageHeaderFooter to
                be set on the document section, which the Docs UI handles automatically).
            content: Optional plain text content to insert into the header.

        Returns:
            Confirmation with docId and headerId. Use headerId as the segmentId in
            subsequent insert_doc_text calls to add formatted content.
        """
        if header_type not in ("DEFAULT", "FIRST_PAGE_HEADER"):
            return {
                "error": f"Invalid header_type '{header_type}'. Use DEFAULT or FIRST_PAGE_HEADER"
            }

        lc = ctx.request_context.lifespan_context
        header_id = None
        try:
            response = await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(
                    documentId=doc_id,
                    body={
                        "requests": [
                            {
                                "createHeader": {
                                    "type": header_type,
                                }
                            }
                        ]
                    },
                )
                .execute,
                lc.docs_service,
            )
            replies = response.get("replies") or []
            if replies:
                header_id = replies[0].get("createHeaderResponse", {}).get("headerId")
        except HttpError as e:
            if "already exists" not in str(e).lower():
                return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

        # Fallback: if headerId not in response (or header already existed), read from documentStyle
        if header_id is None:
            try:
                doc = await execute_in_thread(
                    lc.docs_service.documents()
                    .get(documentId=doc_id, fields="documentStyle")
                    .execute,
                    lc.docs_service,
                )
                style = doc.get("documentStyle", {})
                header_id = (
                    style.get("defaultHeaderId")
                    if header_type == "DEFAULT"
                    else style.get("firstPageHeaderId")
                )
            except Exception:
                pass

        if content and header_id:
            try:
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={
                            "requests": [
                                {
                                    "insertText": {
                                        "text": content,
                                        "location": {"index": 0, "segmentId": header_id},
                                    }
                                }
                            ]
                        },
                    )
                    .execute,
                    lc.docs_service,
                )
            except Exception as e:
                lc.doc_cache.mark_dirty(doc_id)
                return {
                    "docId": doc_id,
                    "headerId": header_id,
                    "warning": f"Header created but content insert failed: {e}",
                }

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("create_header: type=%s headerId=%s in doc %s", header_type, header_id, doc_id)
        return {"docId": doc_id, "headerId": header_id}

    @tool(annotations=ToolAnnotations(title="Create Document Footer", destructiveHint=True))
    async def create_footer(
        doc_id: str,
        footer_type: str = "DEFAULT",
        content: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add a page footer to a Google Doc.

        Creates a footer section and optionally inserts plain text content into it.
        For rich formatting, use insert_doc_text with the returned footerId as segmentId
        after calling this tool.

        Args:
            doc_id: The Google Doc file ID.
            footer_type: "DEFAULT" (all pages, default) or "FIRST_PAGE_FOOTER"
                (applies only to the first page — requires useFirstPageHeaderFooter to
                be set on the document section, which the Docs UI handles automatically).
            content: Optional plain text content to insert into the footer.

        Returns:
            Confirmation with docId and footerId. Use footerId as the segmentId in
            subsequent insert_doc_text calls to add formatted content.
        """
        if footer_type not in ("DEFAULT", "FIRST_PAGE_FOOTER"):
            return {
                "error": f"Invalid footer_type '{footer_type}'. Use DEFAULT or FIRST_PAGE_FOOTER"
            }

        lc = ctx.request_context.lifespan_context
        footer_id = None
        try:
            response = await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(
                    documentId=doc_id,
                    body={
                        "requests": [
                            {
                                "createFooter": {
                                    "type": footer_type,
                                }
                            }
                        ]
                    },
                )
                .execute,
                lc.docs_service,
            )
            replies = response.get("replies") or []
            if replies:
                footer_id = replies[0].get("createFooterResponse", {}).get("footerId")
        except HttpError as e:
            if "already exists" not in str(e).lower():
                return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

        # Fallback: if footerId not in response (or footer already existed), read from documentStyle
        if footer_id is None:
            try:
                doc = await execute_in_thread(
                    lc.docs_service.documents()
                    .get(documentId=doc_id, fields="documentStyle")
                    .execute,
                    lc.docs_service,
                )
                style = doc.get("documentStyle", {})
                footer_id = (
                    style.get("defaultFooterId")
                    if footer_type == "DEFAULT"
                    else style.get("firstPageFooterId")
                )
            except Exception:
                pass

        if content and footer_id:
            try:
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={
                            "requests": [
                                {
                                    "insertText": {
                                        "text": content,
                                        "location": {"index": 0, "segmentId": footer_id},
                                    }
                                }
                            ]
                        },
                    )
                    .execute,
                    lc.docs_service,
                )
            except Exception as e:
                lc.doc_cache.mark_dirty(doc_id)
                return {
                    "docId": doc_id,
                    "footerId": footer_id,
                    "warning": f"Footer created but content insert failed: {e}",
                }

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("create_footer: type=%s footerId=%s in doc %s", footer_type, footer_id, doc_id)
        return {"docId": doc_id, "footerId": footer_id}
