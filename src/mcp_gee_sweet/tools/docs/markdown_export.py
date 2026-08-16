"""Docs -> Markdown export tool (issue #300) — the read-side counterpart to
create_doc/write_doc_content's content_format='markdown' write path.

Deliberately does NOT reuse export_file(export_format='html') + an HTML->Markdown
library: Google's raw Docs HTML export is heavily styled (redundant inline spans),
which would need fragile cleanup heuristics to convert cleanly. Instead this walks
the Docs API structure into this project's own AST (doc_to_ast.py) and serializes
that AST to Markdown (ast_to_markdown.py) — symmetric with the write direction and
reuses the exact node types/mapping the write pipeline already trusts. See
docs/design/doc-to-markdown.md for the full decision writeup.
"""

import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ..response_limits import enforce_response_size_cap, write_capped_result_to_disk
from .ast_to_markdown import ast_to_markdown
from .comments import _COMMENT_FIELDS, _map_comment
from .doc_to_ast import document_to_ast

logger = logging.getLogger(__name__)


async def _fetch_open_comments(drive_service, doc_id: str) -> list[dict[str, Any]]:
    """Paginate through every non-deleted, non-resolved comment on doc_id,
    mapped via comments.py's own _map_comment for one shared shape with
    list_doc_comments' own output."""
    comments: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = await execute_in_thread(
            drive_service.comments()
            .list(
                fileId=doc_id,
                pageSize=100,
                pageToken=page_token,
                includeDeleted=False,
                fields=f"comments({_COMMENT_FIELDS}),nextPageToken",
            )
            .execute,
            drive_service,
        )
        comments.extend(_map_comment(c) for c in response.get("comments", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return [c for c in comments if not c["resolved"]]


def register(tool):
    @tool(annotations=ToolAnnotations(title="Get Document as Markdown", readOnlyHint=True))
    async def get_doc_as_markdown(
        doc_id: str,
        include_comments: bool = False,
        local_path: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Export a Google Doc's content as GitHub-flavored Markdown.

        The inverse of create_doc/write_doc_content's content_format='markdown'
        path — walks the Docs API structure into this project's own AST and
        serializes it to Markdown, rather than converting Docs' own HTML export.
        Supports headings, bold/italic/strikethrough/links, nested bullet and
        numbered lists, task-list checkboxes, blockquotes, inline code and code
        blocks, images, and tables (including nested tables, best-effort — see
        Known limitations below).

        Args:
            doc_id: The Google Doc file ID.
            include_comments: When True, appends a "## Comments" section listing
                every open (non-resolved) comment's author, quoted anchor text,
                content, and replies, via the same Drive comments resource
                list_doc_comments uses. Default False.
            local_path: Optional local filesystem path to write the result to
                instead of returning it inline. Bypasses the response-size cap.

        Returns:
            Dictionary with doc_id, title, and markdown (the full Markdown
            text) — or {local_path, doc_id, bytes_written} if local_path is set.
            Raises ValueError if the response exceeds a safety cap (see
            MAX_TOOL_RESPONSE_CHARS in docs/configuration.md) and local_path is
            not set.

        Known limitations:
            - A table nested inside another table's cell has no Markdown table
              syntax to express it — that cell renders a placeholder note
              instead (the write side has the identical gap in reverse; see
              docs/design/markdown-support.md's "What this does NOT do").
            - Inline images resolve to Drive's temporary contentUri, which
              expires (roughly 30 minutes) — re-export if the Markdown is
              consumed well after generation.
            - Only the document's default tab is read (matches
              get_doc_structure's existing scope) — multi-tab documents are
              out of scope.
            - namedStyleType TITLE/SUBTITLE map to H1/H2; Markdown has no
              equivalent to Docs' distinct Title/Subtitle paragraph styles.
            - Merged table cells (colspan/rowspan) render best-effort: GFM
              pipe tables have no merge concept, so a spanned cell's text
              lands in its first column and the rest render blank.
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service
        try:
            document = await execute_in_thread(
                docs_service.documents().get(documentId=doc_id).execute,
                docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        nodes = document_to_ast(document)

        comments = None
        if include_comments:
            comments = await _fetch_open_comments(lc.drive_service, doc_id)

        markdown = ast_to_markdown(nodes, comments=comments)
        result: dict[str, Any] = {
            "doc_id": doc_id,
            "title": document.get("title"),
            "markdown": markdown,
        }

        if local_path:
            return await write_capped_result_to_disk(
                result,
                local_path,
                default_filename=f"{doc_id}_markdown.json",
                manifest_extra={"doc_id": doc_id},
            )

        enforce_response_size_cap(result, tool_name="get_doc_as_markdown")
        return result
