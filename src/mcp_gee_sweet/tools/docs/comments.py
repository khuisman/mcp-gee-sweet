import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ..response_limits import enforce_response_size_cap

logger = logging.getLogger(__name__)

_COMMENT_FIELDS = (
    "id,content,htmlContent,author(displayName,emailAddress),createdTime,"
    "modifiedTime,resolved,deleted,quotedFileContent(value),"
    "replies(id,content,author(displayName,emailAddress),createdTime,modifiedTime,"
    "action,deleted)"
)


def _map_author(author: dict[str, Any] | None) -> dict[str, Any] | None:
    if not author:
        return None
    return {
        "display_name": author.get("displayName"),
        "email_address": author.get("emailAddress"),
    }


def _map_reply(reply: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": reply.get("id"),
        "content": reply.get("content"),
        "author": _map_author(reply.get("author")),
        "created_time": reply.get("createdTime"),
        "modified_time": reply.get("modifiedTime"),
        "action": reply.get("action"),
        "deleted": reply.get("deleted", False),
    }


def _map_comment(comment: dict[str, Any]) -> dict[str, Any]:
    quoted = comment.get("quotedFileContent")
    return {
        "id": comment.get("id"),
        "content": comment.get("content"),
        "author": _map_author(comment.get("author")),
        "created_time": comment.get("createdTime"),
        "modified_time": comment.get("modifiedTime"),
        "resolved": comment.get("resolved", False),
        "deleted": comment.get("deleted", False),
        "quoted_text": quoted.get("value") if quoted else None,
        "replies": [_map_reply(r) for r in comment.get("replies", [])],
    }


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Document Comments", readOnlyHint=True))
    async def list_doc_comments(
        doc_id: str,
        page_size: int = 20,
        page_token: str | None = None,
        include_deleted: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        List comments (and their replies) on a Google Doc via the Drive comments resource.

        Args:
            doc_id: The Google Doc file ID.
            page_size: Maximum number of comments to return per page (default 20).
            page_token: Continuation token from a previous response for pagination.
            include_deleted: Whether to include deleted comments (default False).

        Returns:
            Dictionary with:
            - doc_id: echoed back for reference
            - comments: list of comments, each with id, content, author
              (display_name, email_address), created_time, modified_time, resolved,
              deleted, quoted_text (the anchored text, if any), and replies. Each
              reply has id, content, author, created_time, modified_time, deleted,
              and action ("resolve" or "reopen", or None for an ordinary reply) —
              replies have no resolved or quoted_text field of their own; a
              comment's resolved status is derived from its most recent reply's
              action.
            - next_page_token: present when more results are available
            Raises ValueError if the response exceeds a safety cap (default 40,000
            characters, set MAX_TOOL_RESPONSE_CHARS to change it) — lower page_size
            and paginate via next_page_token instead of raising the cap.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        response = await execute_in_thread(
            drive_service.comments()
            .list(
                fileId=doc_id,
                pageSize=max(1, min(page_size, 100)),
                pageToken=page_token,
                includeDeleted=include_deleted,
                fields=f"comments({_COMMENT_FIELDS}),nextPageToken",
            )
            .execute,
            drive_service,
        )

        result: dict[str, Any] = {
            "doc_id": doc_id,
            "comments": [_map_comment(c) for c in response.get("comments", [])],
        }
        if npt := response.get("nextPageToken"):
            result["next_page_token"] = npt

        enforce_response_size_cap(
            result,
            tool_name="list_doc_comments",
            hint="Lower page_size and paginate via next_page_token, or ",
            local_path_available=False,
        )

        return result

    @tool(annotations=ToolAnnotations(title="Add Document Comment", destructiveHint=True))
    async def add_doc_comment(
        doc_id: str,
        content: str,
        quoted_text: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add a comment to a Google Doc via the Drive comments resource.

        Args:
            doc_id: The Google Doc file ID.
            content: The comment text.
            quoted_text: Optional text from the document to anchor the comment to,
                         shown as the quoted range the comment refers to.

        Returns:
            Dictionary with id, content, author (display_name, email_address),
            created_time, and quoted_text (echoing the anchor, if one was set).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        body: dict[str, Any] = {"content": content}
        if quoted_text:
            body["quotedFileContent"] = {"value": quoted_text}

        result = await execute_in_thread(
            drive_service.comments()
            .create(
                fileId=doc_id,
                body=body,
                fields="id,content,author(displayName,emailAddress),createdTime,quotedFileContent(value)",
            )
            .execute,
            drive_service,
        )

        quoted = result.get("quotedFileContent")
        logger.debug("Added comment %s to doc %s", result.get("id"), doc_id)
        return {
            "id": result.get("id"),
            "content": result.get("content"),
            "author": _map_author(result.get("author")),
            "created_time": result.get("createdTime"),
            "quoted_text": quoted.get("value") if quoted else None,
        }

    @tool(annotations=ToolAnnotations(title="Resolve Document Comment", destructiveHint=True))
    async def resolve_doc_comment(
        doc_id: str,
        comment_id: str,
        reply_content: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Mark a comment on a Google Doc as resolved, by posting a reply with a
        "resolve" action via the Drive comments resource.

        Args:
            doc_id: The Google Doc file ID.
            comment_id: The ID of the comment to resolve (from list_doc_comments).
            reply_content: Optional text to attach to the resolving reply.

        Returns:
            Dictionary with doc_id, comment_id, reply id, and action ("resolve").
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        body: dict[str, Any] = {"action": "resolve"}
        if reply_content:
            body["content"] = reply_content

        result = await execute_in_thread(
            drive_service.replies()
            .create(
                fileId=doc_id,
                commentId=comment_id,
                body=body,
                fields="id,action,content,createdTime",
            )
            .execute,
            drive_service,
        )

        logger.debug("Resolved comment %s on doc %s", comment_id, doc_id)
        return {
            "doc_id": doc_id,
            "comment_id": comment_id,
            "reply_id": result.get("id"),
            "action": result.get("action"),
        }
