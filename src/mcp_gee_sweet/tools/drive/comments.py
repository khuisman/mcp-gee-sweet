"""Comments on any Drive file, through the Drive `comments`/`replies` resource (#663).

The resource takes any `fileId` Drive supports comments on (Docs, Sheets, Slides,
and other files), so nothing here is Docs-specific. The shape follows
`docs/design/tool-reduction.md`, "Comments: a smaller shape": resolving and
reopening are replies with an action, so they go through `reply_to_comment`, and
editing or deleting a reply is `update_comment`/`delete_comment` with `reply_id` (#664).
"""

import html
import logging
from typing import Any, Literal

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...deprecation import deprecated_tool, renamed_params
from ..params import OptionalText
from ..response_limits import clamp_max_results, enforce_response_size_cap, finish_list_page
from . import _user_fields

logger = logging.getLogger(__name__)

# When the deprecated names (`list_doc_comments`, `add_doc_comment`, their `doc_id`,
# and `resolve_doc_comment`) go. Their RENAMED_TOOLS entries carry the same value.
COMMENTS_RENAMED_IN = "the next feature release"

# Only what _map_comment reads: `htmlContent` was requested and never used (#329).
_COMMENT_FIELDS = (
    "id,content,author(displayName,emailAddress),createdTime,"
    "modifiedTime,resolved,deleted,quotedFileContent(value),"
    "replies(id,content,author(displayName,emailAddress),createdTime,modifiedTime,"
    "action,deleted)"
)
_REPLY_FIELDS = "id,action,content,createdTime"
# get_file_comment reads a comment without its replies, then the replies through
# replies.list, with the same reply fields _map_reply reads.
_COMMENT_ONLY_FIELDS, _REPLY_LIST_FIELDS = _COMMENT_FIELDS.removesuffix(")").split(",replies(")
_REPLIES_PAGE_SIZE = 100  # replies.list's maximum
_EDIT_FIELDS = "id,content,modifiedTime"

# Every optional text parameter here is `OptionalText = ""`, never `str | None`
# (which mcp pre-parses as JSON) or a bare `str` (which refuses an explicit null);
# see tools/params.py (PR #1563 rounds 2 and 3).


def _map_author(author: dict[str, Any] | None) -> dict[str, Any] | None:
    return _user_fields(author) if author else None


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


def _quoted_text(resource: dict[str, Any]) -> str | None:
    """The plain text a comment is anchored to. Drive returns
    quotedFileContent.value HTML-escaped ("Caf&#233;", "&amp;") even though
    it was written as plain text, and escapes a literal "&amp;" in the
    anchor as "&amp;amp;", so unescaping once restores it exactly (#984)."""
    quoted = resource.get("quotedFileContent")
    if not quoted or quoted.get("value") is None:
        return None
    return html.unescape(quoted["value"])


def _map_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("id"),
        "content": comment.get("content"),
        "author": _map_author(comment.get("author")),
        "created_time": comment.get("createdTime"),
        "modified_time": comment.get("modifiedTime"),
        "resolved": comment.get("resolved", False),
        "deleted": comment.get("deleted", False),
        "quoted_text": _quoted_text(comment),
        "replies": [_map_reply(r) for r in comment.get("replies", [])],
    }


def _trim(text: str) -> str:
    """`text` with its ends trimmed at least as far as Drive trims a comment's or
    reply's: every character up to U+0020, control characters included, as Java's
    `String.trim()` does (PR #1578 QA round 1), plus anything `str.strip()` takes.
    The set covers Drive's, so trimming Drive's stored text and the text sent
    gives the same result whenever the edit landed."""
    start, end = 0, len(text)
    while start < end and (text[start] <= " " or text[start].isspace()):
        start += 1
    while end > start and (text[end - 1] <= " " or text[end - 1].isspace()):
        end -= 1
    return text[start:end]


def _has_text(content: str | None) -> bool:
    """Whether `content` holds anything Drive would keep. Drive stores a comment or
    reply of only whitespace or control characters as `content: ""`, a blank entry
    on the thread (PR #1563, PR #1578)."""
    return bool(content and _trim(content))


async def _create_reply(
    drive_service, file_id: str, comment_id: str, content: str | None, action: str | None
) -> dict[str, Any]:
    """Post one reply (`replies.create`), with `action` when given. The raw resource.
    Whitespace-only `content` isn't sent: Drive stores it as an empty reply."""
    body: dict[str, Any] = {}
    if action:
        body["action"] = action
    if _has_text(content):
        body["content"] = content
    return await execute_in_thread(
        drive_service.replies()
        .create(fileId=file_id, commentId=comment_id, body=body, fields=_REPLY_FIELDS)
        .execute,
        drive_service,
    )


async def _list_all_replies(
    drive_service, file_id: str, comment_id: str, include_deleted: bool
) -> list[dict[str, Any]]:
    """Every reply on a comment, oldest first, through every page of
    `replies.list`. `comments.get` returned 150 replies inline in a live check,
    but Drive documents no limit on how many it returns, so the replies come
    from the paged resource instead (#664). An error on a later page propagates:
    a partial thread would read as the whole one."""
    replies: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        page = await execute_in_thread(
            drive_service.replies()
            .list(
                fileId=file_id,
                commentId=comment_id,
                pageSize=_REPLIES_PAGE_SIZE,
                pageToken=page_token,
                includeDeleted=include_deleted,
                fields=f"replies({_REPLY_LIST_FIELDS}),nextPageToken",
            )
            .execute,
            drive_service,
        )
        replies.extend(page.get("replies", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            return replies


async def _deleted_edit_target(
    drive_service, file_id: str, comment_id: str, reply_id: str
) -> str | None:
    """After a failed edit, name the comment or reply it targeted if that one is
    deleted, else None. Drive answers an edit of a deleted comment with a bare 500
    and of a deleted reply with a 400 "Invalid Value" (both checked live, #664), and
    neither says why. Any error reading it back is None, so the caller raises
    Drive's own error."""
    try:
        if reply_id:
            target = await execute_in_thread(
                drive_service.replies()
                .get(
                    fileId=file_id,
                    commentId=comment_id,
                    replyId=reply_id,
                    includeDeleted=True,
                    fields="deleted",
                )
                .execute,
                drive_service,
            )
        else:
            target = await execute_in_thread(
                drive_service.comments()
                .get(fileId=file_id, commentId=comment_id, includeDeleted=True, fields="deleted")
                .execute,
                drive_service,
            )
    except Exception:  # Drive's error from the edit is the one to report.
        logger.debug("Couldn't read back the failed edit's target", exc_info=True)
        return None
    if not target.get("deleted"):
        return None
    return f"reply {reply_id}" if reply_id else f"comment {comment_id}"


def register(tool):
    @tool(
        annotations=ToolAnnotations(title="List File Comments", readOnlyHint=True),
        groups=("comments",),
    )
    @renamed_params(doc_id="file_id", removed_in=COMMENTS_RENAMED_IN)
    async def list_file_comments(
        file_id: str,
        page_size: int = 20,
        page_token: OptionalText = "",
        include_deleted: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        List the comments (and their replies) on a Drive file: a Google Doc, Sheet,
        or Slides deck, or any other file Drive supports comments on.

        Args:
            file_id: The file's ID.
            page_size: Maximum number of comments to return per page (default 20).
            page_token: Continuation token from a previous response for pagination.
            include_deleted: Whether to include deleted comments (default False).

        Returns:
            Dictionary with:
            - file_id: echoed back for reference
            - comments: list of comments, each with id, content, author
              (display_name, email_address), created_time, modified_time, resolved,
              deleted, quoted_text (the anchored text, if any), and replies. Each
              reply has id, content, author, created_time, modified_time, deleted,
              and action ("resolve" or "reopen", or None for an ordinary reply) —
              replies have no resolved or quoted_text field of their own; a
              comment's resolved status is derived from its most recent reply's
              action.
            - next_page_token: present when more results are available
            Raises ValueError if the response exceeds a safety cap (see
            MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured default) —
            lower page_size and paginate via next_page_token instead of raising the cap.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        response = await execute_in_thread(
            drive_service.comments()
            .list(
                fileId=file_id,
                pageSize=clamp_max_results(page_size, 100),
                pageToken=page_token or None,
                includeDeleted=include_deleted,
                fields=f"comments({_COMMENT_FIELDS}),nextPageToken",
            )
            .execute,
            drive_service,
        )

        result: dict[str, Any] = {
            "file_id": file_id,
            "comments": [_map_comment(c) for c in response.get("comments", [])],
        }
        return finish_list_page(
            result, response, tool_name="list_file_comments", page_param="page_size"
        )

    @tool(
        annotations=ToolAnnotations(title="Add File Comment", destructiveHint=True),
        groups=("comments",),
    )
    @renamed_params(doc_id="file_id", removed_in=COMMENTS_RENAMED_IN)
    async def add_file_comment(
        file_id: str,
        content: str,
        quoted_text: OptionalText = "",
        anchor: OptionalText = "",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add a comment to a Drive file: a Google Doc, Sheet, or Slides deck, or any
        other file Drive supports comments on.

        Args:
            file_id: The file's ID.
            content: The comment text.
            quoted_text: Optional text the comment quotes, shown with the comment
                         as the text it refers to. It doesn't pin the comment to a
                         position: in a Doc, Sheet or Slides deck the comment is
                         unanchored (it isn't attached to that text, a cell, or a
                         slide), since Drive's API can't anchor a comment in the
                         Google editors.
            anchor: Optional Drive anchor region, passed through as given (a JSON
                    string in Drive's `drive#commentRegion` format). Drive's own
                    viewer may honor it for a non-Google file such as an image or
                    PDF; the Google editors ignore it, so it can't pin a comment to
                    a cell or a range in a Doc, Sheet or Slides deck.

        Returns:
            Dictionary with id, content, author (display_name, email_address),
            created_time, quoted_text (echoed, if set), and anchor (echoed as Drive
            stored it, if set).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        body: dict[str, Any] = {"content": content}
        if quoted_text:
            body["quotedFileContent"] = {"value": quoted_text}
        if anchor:
            body["anchor"] = anchor

        result = await execute_in_thread(
            drive_service.comments()
            .create(
                fileId=file_id,
                body=body,
                fields=(
                    "id,content,author(displayName,emailAddress),createdTime,"
                    "quotedFileContent(value),anchor"
                ),
            )
            .execute,
            drive_service,
        )

        logger.debug("Added comment %s to file %s", result.get("id"), file_id)
        return {
            "id": result.get("id"),
            "content": result.get("content"),
            "author": _map_author(result.get("author")),
            "created_time": result.get("createdTime"),
            "quoted_text": _quoted_text(result),
            "anchor": result.get("anchor"),
        }

    @tool(
        annotations=ToolAnnotations(title="Reply to Comment", destructiveHint=True),
        groups=("comments",),
    )
    async def reply_to_comment(
        file_id: str,
        comment_id: str,
        content: OptionalText = "",
        action: Literal["resolve", "reopen"] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Reply to a comment on a Drive file, and optionally resolve or reopen it.
        Resolving and reopening are replies with an action, so they go through this
        tool too.

        Args:
            file_id: The file's ID.
            comment_id: The comment's ID (from list_file_comments).
            content: The reply text. Required for a plain reply; optional with an
                     action. Text that is only whitespace or control characters counts
                     as none.
            action: "resolve" to mark the comment resolved, "reopen" to reopen a
                    resolved one, or omit for a plain reply. A plain reply to a
                    resolved comment reopens it: Drive does that itself, as its
                    own UI does.

        Returns:
            Dictionary with file_id, comment_id, reply_id, action (None for a plain
            reply to an open comment, "reopen" when a plain reply reopened a
            resolved one), content, and created_time. Returns {"error": ...} without
            posting anything when neither content (other than whitespace) nor
            action is given.
        """
        if not _has_text(content) and not action:
            return {
                "error": "Pass content for a plain reply, or an action ('resolve' or "
                "'reopen'); a reply with neither has nothing to post."
            }
        drive_service = ctx.request_context.lifespan_context.drive_service

        result = await _create_reply(drive_service, file_id, comment_id, content, action)

        logger.debug("Replied to comment %s on file %s (action %s)", comment_id, file_id, action)
        return {
            "file_id": file_id,
            "comment_id": comment_id,
            "reply_id": result.get("id"),
            "action": result.get("action"),
            "content": result.get("content"),
            "created_time": result.get("createdTime"),
        }

    @tool(
        annotations=ToolAnnotations(title="Get File Comment", readOnlyHint=True),
        groups=("comments",),
    )
    async def get_file_comment(
        file_id: str,
        comment_id: str,
        include_deleted: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Get one comment on a Drive file, with every reply on it.

        Args:
            file_id: The file's ID.
            comment_id: The comment's ID (from list_file_comments).
            include_deleted: Whether to return a deleted comment, and the deleted
                             replies on a comment (default False). A deleted
                             comment or reply comes back with deleted True and no
                             content. Without it, getting a deleted comment fails
                             as not found.

        Returns:
            Dictionary with file_id and comment: the comment's id, content, author
            (display_name, email_address), created_time, modified_time, resolved,
            deleted, quoted_text (the anchored text, if any), and replies, oldest
            first: every reply on the comment, however many, each with id,
            content, author, created_time, modified_time, deleted, and action
            ("resolve" or "reopen", or None for an ordinary reply).
            Raises ValueError if the response exceeds a safety cap (see
            MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured
            default).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        comment = await execute_in_thread(
            drive_service.comments()
            .get(
                fileId=file_id,
                commentId=comment_id,
                includeDeleted=include_deleted,
                fields=_COMMENT_ONLY_FIELDS,
            )
            .execute,
            drive_service,
        )
        comment["replies"] = await _list_all_replies(
            drive_service, file_id, comment_id, include_deleted
        )

        result = {"file_id": file_id, "comment": _map_comment(comment)}
        enforce_response_size_cap(result, tool_name="get_file_comment", local_path_available=False)
        return result

    @tool(
        annotations=ToolAnnotations(title="Update Comment", destructiveHint=True),
        groups=("comments",),
    )
    async def update_comment(
        file_id: str,
        comment_id: str,
        content: str,
        reply_id: OptionalText = "",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace the text of a comment on a Drive file, or of one reply to it.

        Args:
            file_id: The file's ID.
            comment_id: The comment's ID (from list_file_comments).
            content: The new text, replacing the old. Drive trims whitespace and
                     control characters from its start and end. Text that is
                     only whitespace or control characters isn't sent:
                     Drive would store it as an empty comment.
            reply_id: A reply's ID (from list_file_comments or get_file_comment)
                      to edit that reply instead of the comment. A reply that
                      resolved or reopened the comment keeps its action.

        Returns:
            Dictionary with file_id, comment_id, reply_id (None when the comment
            itself was edited), content, and modified_time. Returns {"error": ...}
            without changing anything when content is empty or only whitespace
            or control characters,
            or when the comment or reply is deleted. Only the author of a comment
            or reply can edit it: Drive ignores anyone else's edit, so that
            returns {"error": ..., "content": <the text left in place>}.
            Resolving or reopening is reply_to_comment's action, not an edit.
        """
        if not _has_text(content):
            return {
                "error": "Pass the new text as content; text that is empty or only "
                "whitespace or control characters would leave the comment blank. "
                "To remove it, use "
                "delete_comment."
            }
        drive_service = ctx.request_context.lifespan_context.drive_service

        body = {"content": content}
        if reply_id:
            request = drive_service.replies().update(
                fileId=file_id,
                commentId=comment_id,
                replyId=reply_id,
                body=body,
                fields=_EDIT_FIELDS,
            )
        else:
            request = drive_service.comments().update(
                fileId=file_id, commentId=comment_id, body=body, fields=_EDIT_FIELDS
            )
        try:
            result = await execute_in_thread(request.execute, drive_service)
        except HttpError as e:
            if e.resp.status != 400 and e.resp.status < 500:
                raise
            deleted = await _deleted_edit_target(drive_service, file_id, comment_id, reply_id)
            if deleted is None:
                raise
            return {
                "error": f"The {deleted} is deleted, so it can't be edited. Post a new "
                "reply with reply_to_comment, or a new comment with add_file_comment."
            }

        # Drive ignores an edit by anyone but the author and still answers 200,
        # returning the old text (checked live both ways between a user and a
        # service account, #664). It also trims the text's ends, so compare both
        # trimmed through _trim, whose set covers Drive's.
        stored = result.get("content") or ""
        if _trim(stored) != _trim(content):
            target = f"reply {reply_id}" if reply_id else f"comment {comment_id}"
            return {
                "error": f"Drive left the {target} unchanged: only its author can edit "
                "it, and Drive ignores an edit from anyone else without an error.",
                "content": stored,
            }

        logger.debug(
            "Updated %s on comment %s, file %s",
            f"reply {reply_id}" if reply_id else "the comment",
            comment_id,
            file_id,
        )
        return {
            "file_id": file_id,
            "comment_id": comment_id,
            "reply_id": reply_id or None,
            "content": result.get("content"),
            "modified_time": result.get("modifiedTime"),
        }

    @tool(
        annotations=ToolAnnotations(title="Delete Comment", destructiveHint=True),
        groups=("comments",),
    )
    async def delete_comment(
        file_id: str,
        comment_id: str,
        reply_id: OptionalText = "",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete a comment on a Drive file, with its replies, or one reply to it.

        Args:
            file_id: The file's ID.
            comment_id: The comment's ID (from list_file_comments).
            reply_id: A reply's ID (from list_file_comments or get_file_comment)
                      to delete only that reply, leaving the comment and its
                      other replies.

        Returns:
            Dictionary with file_id, comment_id, reply_id (None when the comment
            was deleted), and deleted (True). A deleted comment or reply is left
            out of list_file_comments and get_file_comment unless they're called
            with include_deleted=True, which shows it with deleted True and no
            content. Once a comment is deleted, deleting it or any of its replies
            again fails as not found. Drive can refuse to delete another
            author's comment or reply (HttpError 403).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        if reply_id:
            request = drive_service.replies().delete(
                fileId=file_id, commentId=comment_id, replyId=reply_id
            )
        else:
            request = drive_service.comments().delete(fileId=file_id, commentId=comment_id)
        await execute_in_thread(request.execute, drive_service)

        logger.debug(
            "Deleted %s on comment %s, file %s",
            f"reply {reply_id}" if reply_id else "the comment",
            comment_id,
            file_id,
        )
        return {
            "file_id": file_id,
            "comment_id": comment_id,
            "reply_id": reply_id or None,
            "deleted": True,
        }

    @tool(
        annotations=ToolAnnotations(title="Resolve Document Comment", destructiveHint=True),
        groups=("comments",),
    )
    @deprecated_tool(
        use="`reply_to_comment` with `action='resolve'`", removed_in=COMMENTS_RENAMED_IN
    )
    async def resolve_doc_comment(
        doc_id: str,
        comment_id: str,
        reply_content: OptionalText = "",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Mark a comment on a Google Doc as resolved, by posting a reply with a
        "resolve" action via the Drive comments resource.

        Args:
            doc_id: The Google Doc file ID.
            comment_id: The ID of the comment to resolve (from list_file_comments).
            reply_content: Optional text to attach to the resolving reply (text
                           that is only whitespace or control characters isn't sent).

        Returns:
            Dictionary with doc_id, comment_id, reply id, and action ("resolve").
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        result = await _create_reply(drive_service, doc_id, comment_id, reply_content, "resolve")

        logger.debug("Resolved comment %s on doc %s", comment_id, doc_id)
        return {
            "doc_id": doc_id,
            "comment_id": comment_id,
            "reply_id": result.get("id"),
            "action": result.get("action"),
        }
