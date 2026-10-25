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

import asyncio
import functools
import hashlib
import logging
from typing import Any

import anyio
import anyio.lowlevel
from googleapiclient.http import MediaInMemoryUpload
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread, thread_http
from ...local_files import check_write
from ..drive.transfer import (
    _DOCX_MIME,
    _GOOGLE_DOC_MIME,
    _fetch_revision_export,
    _quota_error_detail,
)
from ..pagination import iter_pages
from ..response_limits import enforce_response_size_cap, write_capped_result_to_disk
from .anchors import _github_style_slugify, _slugs_with_dedup
from .ast import Heading, NamedBlock, Run
from .ast_to_markdown import ast_to_markdown
from .comments import _COMMENT_FIELDS, _map_comment
from .doc_to_ast import _paragraph_to_node, document_to_ast

logger = logging.getLogger(__name__)

# 1,000 pages of 100 comments: only a nextPageToken that never goes falsy reaches it.
_COMMENTS_MAX_PAGES = 1000

# Image fetches per revision export, run concurrently.
_REVISION_IMAGE_CONCURRENCY = 8

# googleapiclient retries a 5xx or 429 this many times, with exponential backoff.
_CLEANUP_RETRIES = 3


async def _fetch_open_comments(drive_service, doc_id: str) -> list[dict[str, Any]]:
    """Paginate through every non-deleted, non-resolved comment on doc_id,
    mapped via comments.py's own _map_comment for one shared shape with
    list_doc_comments' own output."""
    comments: list[dict[str, Any]] = []
    async for response in iter_pages(
        lambda token: drive_service.comments().list(
            fileId=doc_id,
            pageSize=100,
            pageToken=token,
            includeDeleted=False,
            fields=f"comments({_COMMENT_FIELDS}),nextPageToken",
        ),
        drive_service,
        max_pages=_COMMENTS_MAX_PAGES,
    ):
        comments.extend(_map_comment(c) for c in response.get("comments", []))
    return [c for c in comments if not c["resolved"]]


def _iter_text_styles(node: Any):
    """Every textStyle dict under `node`: text runs' and inline images' alike."""
    if isinstance(node, dict):
        ts = node.get("textStyle")
        if isinstance(ts, dict):
            yield ts
        for value in node.values():
            yield from _iter_text_styles(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_text_styles(item)


def _rendered_heading_slugs(document: dict) -> dict[str, str]:
    """headingId -> '#slug' fragment for each paragraph that renders as a
    Markdown heading, in document order.

    Classified by doc_to_ast's own _paragraph_to_node rather than by
    namedStyleType, since a paragraph with a headingId doesn't always render as
    a heading: a bulleted heading renders as a list item, and one in a table
    cell as cell text (PR #988 QA round 1). Counting those would shift every
    later duplicate's -1/-2 suffix onto the wrong heading. TITLE/SUBTITLE
    render as H1/H2, so they count."""
    ids: list[str] = []
    texts: list[str] = []
    for elem in document.get("body", {}).get("content", []):
        para = elem.get("paragraph")
        if not para:
            continue
        heading_id = para.get("paragraphStyle", {}).get("headingId")
        if not heading_id:
            continue
        # Only headings are kept, and only headingId paragraphs are seen: no list numbers.
        node = _paragraph_to_node(para, document, list_counter=None)
        if not isinstance(node, Heading | NamedBlock):
            continue
        ids.append(heading_id)
        texts.append("".join(r.text for r in node.runs if isinstance(r, Run)).strip())
    slugs = _slugs_with_dedup(texts, _github_style_slugify)
    return {heading_id: slug for heading_id, slug in zip(ids, slugs, strict=True) if slug}


def _stabilize_internal_links(document: dict) -> None:
    """Rewrite links to a heading in a revision's temporary Doc as '#slug'
    anchors, and drop links to a bookmark, in place.

    The temporary Doc's ID and every heading/bookmark ID in it are new on each
    import (measured live, #959), so the same-document URL doc_to_ast builds
    would differ between any two exports and point at a deleted Doc. A heading
    link becomes a GitHub-style slug of the heading's text, deduplicated like
    anchors.py's resolver expects, so it survives a round trip through the
    write side. A heading link whose target doesn't render as a heading is
    dropped, and so is every bookmark link: a bookmark has no text to name it,
    and any '#fragment' made up for one could be resolved by the write side's
    fuzzy matcher to some heading (PR #988 QA round 1). A link to the wrong
    place is worse than none."""
    slugs = _rendered_heading_slugs(document)
    for ts in _iter_text_styles(document.get("body", {})):
        link = ts.get("link")
        if not link or link.get("url"):
            continue
        heading_id = (link.get("heading") or {}).get("id") or link.get("headingId")
        slug = slugs.get(heading_id) if heading_id else None
        if slug:
            ts["link"] = {"url": f"#{slug}"}
        else:
            del ts["link"]


async def _stabilize_images(drive_service, document: dict) -> None:
    """Replace each inline image's contentUri in a revision's temporary Doc with
    `image:sha256-<hash>` of its bytes, in place.

    The contentUri is new on every import, but the bytes are the same
    (measured live, #959), so hashing them keeps two exports diffable and still
    shows a changed image. The URL itself isn't kept: it stops serving once the
    temporary Doc is deleted (PR #988 QA round 1). A failed fetch gets
    `image:unavailable` instead."""
    objects = [
        props
        for obj in document.get("inlineObjects", {}).values()
        if (
            props := obj.get("inlineObjectProperties", {})
            .get("embeddedObject", {})
            .get("imageProperties", {})
        ).get("contentUri")
    ]
    if not objects:
        return
    sem = asyncio.Semaphore(_REVISION_IMAGE_CONCURRENCY)

    async def _hash(uri: str) -> str:
        async with sem:
            resp, content = await asyncio.to_thread(lambda: thread_http(drive_service).request(uri))
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        return hashlib.sha256(content).hexdigest()[:16]

    uris = [props["contentUri"] for props in objects]
    hashes = await asyncio.gather(*(_hash(u) for u in uris), return_exceptions=True)
    for props, uri, digest in zip(objects, uris, hashes, strict=True):
        if isinstance(digest, BaseException) and not isinstance(digest, Exception):
            raise digest
        if isinstance(digest, Exception):
            logger.warning("Couldn't fetch revision image %s: %s", uri, digest)
            props["contentUri"] = "image:unavailable"
        else:
            props["contentUri"] = f"image:sha256-{digest}"


async def _discard_temp_doc(drive_service, file_id: str, can_delete: bool) -> str | None:
    """Delete (or, without permanent-delete permission, trash) a temporary Doc:
    a revision export's import here, or _replace_doc_content's pre-clear backup
    (#878). Returns an error string instead of raising, so a failed cleanup
    never hides the calling tool's own outcome."""
    try:
        if can_delete:
            request = drive_service.files().delete(fileId=file_id, supportsAllDrives=True)
        else:
            # A Content manager on a Shared Drive can trash but not delete (#876).
            request = drive_service.files().update(
                fileId=file_id, body={"trashed": True}, fields="id", supportsAllDrives=True
            )
        # Retried on a 5xx or 429: a failed removal leaves a stray copy in Drive.
        await execute_in_thread(
            functools.partial(request.execute, num_retries=_CLEANUP_RETRIES), drive_service
        )
    except Exception as e:
        logger.warning("Couldn't remove temporary Doc %s: %s", file_id, e)
        return str(e)
    return None


async def export_doc_revision_markdown(
    drive_service,
    docs_service,
    file_id: str,
    revision_id: str,
    docx_url: str,
    folder_id: str | None,
) -> dict[str, Any]:
    """A Google Doc revision as Markdown, through get_doc_as_markdown's own
    converter (#959). Returns {"markdown"}, plus "warning" if the temporary
    Doc couldn't be removed.

    The Docs API reads only a document's current state, and Drive exports an
    old revision only as a file. Google's own Markdown and HTML exports lose
    code blocks, blockquotes, inline code and list structure (measured live),
    so the revision is exported as DOCX, imported into a temporary Google Doc,
    read with document_to_ast/ast_to_markdown, and the temporary Doc removed.
    See docs/design/doc-revision-export.md."""
    docx = await _fetch_revision_export(drive_service, docx_url, revision_id)
    body: dict[str, Any] = {
        "name": f"export_revision temp ({file_id} r{revision_id})",
        "mimeType": _GOOGLE_DOC_MIME,
    }
    if folder_id:
        body["parents"] = [folder_id]

    temp: dict[str, Any] = {}
    cleanup_error: str | None = None
    try:
        # Shielded, so a cancellation can't land after Drive created the Doc but
        # before its ID is recorded for cleanup (the PR #877 rule).
        with anyio.CancelScope(shield=True):
            try:
                temp = await execute_in_thread(
                    drive_service.files()
                    .create(
                        body=body,
                        # Resumable: Drive takes a multipart upload only up to 5 MB, and
                        # a revision with embedded images can exceed it.
                        media_body=MediaInMemoryUpload(docx, mimetype=_DOCX_MIME, resumable=True),
                        fields="id,capabilities(canDelete)",
                        supportsAllDrives=True,
                    )
                    .execute,
                    drive_service,
                )
            except Exception as e:
                raise ValueError(
                    f"Couldn't import revision {revision_id} into a temporary Doc: "
                    f"{_quota_error_detail(e, drive_service)}"
                ) from e
        await anyio.lowlevel.checkpoint()
        document = await execute_in_thread(
            docs_service.documents().get(documentId=temp["id"]).execute,
            docs_service,
        )
        await _stabilize_images(drive_service, document)
    finally:
        if temp.get("id"):
            with anyio.CancelScope(shield=True):
                cleanup_error = await _discard_temp_doc(
                    drive_service,
                    temp["id"],
                    temp.get("capabilities", {}).get("canDelete", True),
                )

    _stabilize_internal_links(document)
    result: dict[str, Any] = {
        "markdown": ast_to_markdown(document_to_ast(document)),
    }
    if cleanup_error:
        result["warning"] = (
            f"Couldn't remove the temporary Doc {temp['id']} this export created; "
            f"delete it manually ({cleanup_error})."
        )
    return result


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
            local_path: Optional local filesystem path to write the Markdown to
                instead of returning it inline. The file holds the raw Markdown
                text (UTF-8), byte-identical to the inline markdown field,
                including the comments section when include_comments is True.
                A directory path writes <doc_id>.md inside it; a path ending in
                '/' is a directory, created if missing. A file in place of a parent
                directory, or at a path ending in '/', raises ValueError; an existing
                file at a plain file path is replaced.
                Bypasses the response-size cap.

        Returns:
            Dictionary with doc_id, title, and markdown (the full Markdown
            text) — or {local_path, doc_id, title, bytes_written} if local_path
            is set.
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
        if local_path:
            # Before any fetch, so a refused destination costs no API call (#796).
            check_write(local_path)
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
                markdown,
                local_path,
                default_filename=f"{doc_id}.md",
                manifest_extra={"doc_id": doc_id, "title": result["title"]},
            )

        enforce_response_size_cap(result, tool_name="get_doc_as_markdown")
        return result
