import logging
from typing import Any, Literal

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...deprecation import deprecated_tool
from .invalidation import doc_invalidating

logger = logging.getLogger(__name__)

# create_header/create_footer are removed in favor of create_header_or_footer
# (#1527) in the next feature release, per docs/design.md "Renaming or Removing a Tool".
_HEADER_OR_FOOTER_REMOVED_IN = "the next feature release"

# The Docs API's HeaderFooterType takes only DEFAULT, and no request creates a
# first-page header or footer: createHeader rejects any other type, and with
# useFirstPageHeaderFooter set it still makes only the default one (both checked
# live, #1527).
_FIRST_PAGE_ERROR = (
    "A first-page {kind} can't be created through the Docs API, which only creates "
    "the default {kind}. Add one in the Docs UI (Insert > Headers & footers, "
    "'Different first page')."
)


async def _create_header_or_footer(
    lc, doc_id: str, kind: str, content: str | None
) -> dict[str, Any]:
    """Shared implementation behind create_header_or_footer and
    create_header/create_footer, so both send the same requests.

    Returns {"id": <headerId or footerId>}, plus "warning" if the content insert
    failed; {"id": None, "warning": ...} if the ID couldn't be found (no content
    is inserted then); or {"error": ...}."""
    if kind not in ("header", "footer"):
        return {"error": f"kind must be 'header' or 'footer', got {kind!r}"}
    request_name = "createHeader" if kind == "header" else "createFooter"
    id_field = f"{kind}Id"

    segment_id = None
    try:
        with doc_invalidating(lc.doc_cache, doc_id):
            response = await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(
                    documentId=doc_id,
                    body={"requests": [{request_name: {"type": "DEFAULT"}}]},
                )
                .execute,
                lc.docs_service,
            )
        replies = response.get("replies") or []
        if replies:
            # The reply is keyed by the request's own name (checked live, #1527).
            segment_id = (replies[0].get(request_name) or {}).get(id_field)
    except HttpError as e:
        if "already exists" not in str(e).lower():
            return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

    # The doc already had one, or the reply didn't name it: read it from documentStyle.
    lookup_error = None
    if segment_id is None:
        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id, fields="documentStyle").execute,
                lc.docs_service,
            )
            segment_id = doc.get("documentStyle", {}).get(
                "defaultHeaderId" if kind == "header" else "defaultFooterId"
            )
        except Exception as e:
            lookup_error = str(e)

    if segment_id is None:
        # Never a silent None: say why there's no ID, and that content wasn't written
        # (PR #1548 QA round 1).
        reason = (
            f"its ID couldn't be read ({lookup_error})"
            if lookup_error
            else "the doc reports no default " + kind
        )
        warning = f"{kind.capitalize()} not confirmed: {reason}."
        if content:
            warning += " The content was not inserted."
        return {"id": None, "warning": warning}

    if content:
        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={
                            "requests": [
                                {
                                    "insertText": {
                                        "text": content,
                                        "location": {"index": 0, "segmentId": segment_id},
                                    }
                                }
                            ]
                        },
                    )
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {
                "id": segment_id,
                "warning": f"{kind.capitalize()} created but content insert failed: {e}",
            }

    logger.debug("create %s: %sId=%s in doc %s", kind, kind, segment_id, doc_id)
    return {"id": segment_id}


def register(tool):
    @tool(
        annotations=ToolAnnotations(title="Create Document Header or Footer", destructiveHint=True)
    )
    async def create_header_or_footer(
        doc_id: str,
        kind: Literal["header", "footer"],
        content: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add a page header or footer to a Google Doc, shown on every page.

        Creates the doc's default header or footer and optionally inserts plain
        text into it. If the doc already has one, the text is inserted at its
        start. For rich formatting, use insert_doc_text with the returned
        headerId or footerId as segmentId after calling this tool. The Docs API
        can't create a first-page-only header or footer; add one in the Docs UI.

        Args:
            doc_id: The Google Doc file ID.
            kind: "header" or "footer".
            content: Optional plain text content to insert into it.

        Returns:
            Confirmation with docId, kind, and headerId (for a header) or footerId
            (for a footer). Use that ID as the segmentId in subsequent
            insert_doc_text calls to add formatted content. Includes "warning" if
            it was created but the content insert failed, or if its ID couldn't be
            read (the ID is then null and no content was inserted).
        """
        result = await _create_header_or_footer(
            ctx.request_context.lifespan_context, doc_id, kind, content
        )
        if "error" in result:
            return result
        out = {"docId": doc_id, "kind": kind, f"{kind}Id": result["id"]}
        if "warning" in result:
            out["warning"] = result["warning"]
        return out

    @tool(annotations=ToolAnnotations(title="Create Document Header", destructiveHint=True))
    @deprecated_tool(
        use="`create_header_or_footer` with `kind='header'`",
        removed_in=_HEADER_OR_FOOTER_REMOVED_IN,
    )
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
            header_type: "DEFAULT" (all pages, the default). "FIRST_PAGE_HEADER"
                returns an error: the Docs API can't create a first-page header.
            content: Optional plain text content to insert into the header.

        Returns:
            Confirmation with docId and headerId. Use headerId as the segmentId in
            subsequent insert_doc_text calls to add formatted content.
        """
        if header_type == "FIRST_PAGE_HEADER":
            return {"error": _FIRST_PAGE_ERROR.format(kind="header")}
        if header_type != "DEFAULT":
            return {"error": f"Invalid header_type '{header_type}'. Use DEFAULT"}
        result = await _create_header_or_footer(
            ctx.request_context.lifespan_context, doc_id, "header", content
        )
        if "error" in result:
            return result
        out = {"docId": doc_id, "headerId": result["id"]}
        if "warning" in result:
            out["warning"] = result["warning"]
        return out

    @tool(annotations=ToolAnnotations(title="Create Document Footer", destructiveHint=True))
    @deprecated_tool(
        use="`create_header_or_footer` with `kind='footer'`",
        removed_in=_HEADER_OR_FOOTER_REMOVED_IN,
    )
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
            footer_type: "DEFAULT" (all pages, the default). "FIRST_PAGE_FOOTER"
                returns an error: the Docs API can't create a first-page footer.
            content: Optional plain text content to insert into the footer.

        Returns:
            Confirmation with docId and footerId. Use footerId as the segmentId in
            subsequent insert_doc_text calls to add formatted content.
        """
        if footer_type == "FIRST_PAGE_FOOTER":
            return {"error": _FIRST_PAGE_ERROR.format(kind="footer")}
        if footer_type != "DEFAULT":
            return {"error": f"Invalid footer_type '{footer_type}'. Use DEFAULT"}
        result = await _create_header_or_footer(
            ctx.request_context.lifespan_context, doc_id, "footer", content
        )
        if "error" in result:
            return result
        out = {"docId": doc_id, "footerId": result["id"]}
        if "warning" in result:
            out["warning"] = result["warning"]
        return out
