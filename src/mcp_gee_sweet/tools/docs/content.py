import html as html_module
import logging
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import markdown as _md
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..drive import _SA_QUOTA_ERROR
from .ast import Table
from .emitter import ast_to_requests, fill_tables
from .html_parser import html_to_ast

logger = logging.getLogger(__name__)


def _html_to_text(html_content: str) -> str:
    """Convert HTML to plain text, preserving block-level line breaks."""
    _BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "tr", "blockquote"}

    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag == "br" or (tag in _BLOCK and self.parts and not self.parts[-1].endswith("\n")):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in _BLOCK:
                self.parts.append("\n")

        def handle_data(self, data):
            self.parts.append(data)

        def handle_entityref(self, name):
            self.parts.append(html_module.unescape(f"&{name};"))

        def handle_charref(self, name):
            self.parts.append(html_module.unescape(f"&#{name};"))

    extractor = _Extractor()
    extractor.feed(html_content)
    return "".join(extractor.parts).strip()


def _md_to_html(md_text: str) -> str:
    """Convert Markdown to HTML using the Python markdown library (tables, fenced_code, sane_lists extensions)."""
    return _md.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])


def _to_doc_requests(
    content: str, content_format: str = "html", start_index: int = 1
) -> tuple[list[dict], list[Table]]:
    """Convert HTML or Markdown to Docs API batchUpdate requests via the AST pipeline.

    Returns (requests, tables) where tables is a list of Table AST nodes. Table cells
    are NOT filled here — call fill_tables() after executing the returned requests.
    """
    if content_format == "markdown":
        content = _md_to_html(content)
    nodes = html_to_ast(content)
    return ast_to_requests(nodes, start_index)


def _html_to_doc_requests(
    html_content: str, start_index: int = 1
) -> tuple[list[dict], list[Table]]:
    return _to_doc_requests(html_content, "html", start_index)


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Document", destructiveHint=True))
    def create_doc(
        title: str,
        content: str | None = None,
        folder_id: str | None = None,
        content_format: str = "html",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new Google Doc, optionally with initial content.

        Content is interpreted as HTML by default. Pass content_format='markdown' to supply
        Markdown instead (headings, bold, italic, lists, links, tables, fenced code blocks,
        and task list items are all supported). Tables are appended after all paragraph
        content. Nested tables are not supported.

        Args:
            title: The title of the new document
            content: Optional content for the document body
            folder_id: Optional Google Drive folder ID where the document should be created.
                      If not provided, creates in the root of My Drive.
            content_format: 'html' (default) or 'markdown'

        Returns:
            Information about the newly created document including its ID and web link

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Workaround for service accounts: create the file manually in Drive, then use
            write_doc_content to populate it. Check server://auth-status for your current
            auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        docs_service = lc.docs_service
        target_folder_id = folder_id or lc.folder_id

        file_body: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            doc = (
                drive_service.files()
                .create(
                    supportsAllDrives=True,
                    body=file_body,
                    fields="id, name, parents, webViewLink",
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug(
            "Doc created with ID: %s%s",
            doc_id,
            f" in folder {target_folder_id}" if target_folder_id else " in root",
        )

        if content:
            content_requests, tables = _to_doc_requests(content, content_format, start_index=1)
            if content_requests:
                docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": content_requests}
                ).execute()
            fill_tables(docs_service, doc_id, tables)

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        return {
            "docId": doc_id,
            "title": doc.get("name", title),
            "folder": parents[0] if parents else "root",
            "web_link": doc.get("webViewLink"),
        }

    @tool(annotations=ToolAnnotations(title="Create Document from File", destructiveHint=True))
    def create_doc_from_file(
        local_path: str,
        title: str | None = None,
        folder_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a Google Doc from a local .md or .html file.

        The file format is inferred from the extension: .md files are parsed as
        Markdown, .html / .htm files as HTML. The document title defaults to the
        filename without extension if not supplied.

        Args:
            local_path: Absolute or relative path to the local file.
            title: Document title. Defaults to the filename stem.
            folder_id: Optional Google Drive folder ID. Defaults to server default folder.

        Returns:
            Information about the newly created document including its ID and web link.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Check server://auth-status for your current auth method.
        """
        path = Path(local_path)
        if not path.exists():
            return {"error": f"File not found: {local_path}"}

        ext = path.suffix.lower()
        if ext == ".md":
            content_format = "markdown"
        elif ext in (".html", ".htm"):
            content_format = "html"
        else:
            return {"error": f"Unsupported file extension '{ext}'. Use .md or .html/.htm"}

        content = path.read_text(encoding="utf-8")
        doc_title = title or path.stem

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        docs_service = lc.docs_service
        target_folder_id = folder_id or lc.folder_id

        file_body: dict[str, Any] = {
            "name": doc_title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            doc = (
                drive_service.files()
                .create(
                    supportsAllDrives=True,
                    body=file_body,
                    fields="id, name, parents, webViewLink",
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug("Doc created from file %s with ID: %s", local_path, doc_id)

        if content:
            content_requests, tables = _to_doc_requests(content, content_format, start_index=1)
            if content_requests:
                docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": content_requests}
                ).execute()
            fill_tables(docs_service, doc_id, tables)

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        return {
            "docId": doc_id,
            "title": doc.get("name", doc_title),
            "folder": parents[0] if parents else "root",
            "web_link": doc.get("webViewLink"),
        }

    @tool(annotations=ToolAnnotations(title="Get Document Content", readOnlyHint=True))
    def get_doc_content(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Get the plain text content of a Google Doc.

        Args:
            file_id: The Google Drive file ID of the document.

        Returns:
            Dictionary with the document's text content and metadata. Results are
            cached; call refresh_cache(doc_id=file_id) to invalidate, or
            refresh_cache() to clear all caches.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        doc_cache = lc.doc_cache

        cached = doc_cache.get(file_id)
        if cached is not None:
            return cached

        metadata = (
            drive_service.files()
            .get(
                fileId=file_id, fields="id, name, modifiedTime, webViewLink", supportsAllDrives=True
            )
            .execute()
        )

        content = drive_service.files().export(fileId=file_id, mimeType="text/plain").execute()

        result = {
            "id": metadata["id"],
            "name": metadata["name"],
            "modified_time": metadata.get("modifiedTime"),
            "web_link": metadata.get("webViewLink"),
            "content": content.decode("utf-8") if isinstance(content, bytes) else content,
        }
        doc_cache.store(file_id, result)
        return result

    @tool(annotations=ToolAnnotations(title="Write Document Content", destructiveHint=True))
    def write_doc_content(
        doc_id: str,
        content: str,
        content_format: str = "html",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace the full content of an existing Google Doc.

        Content is interpreted as HTML by default. Pass content_format='markdown' to supply
        Markdown instead. Headings, paragraphs, lists, links, tables, fenced code blocks,
        and task list items are all supported. Tables are appended after all
        paragraph content. Use this to populate a doc created manually in Drive (bypassing
        service account storage quota limits).

        Args:
            doc_id: The Google Doc file ID.
            content: Content to write into the document body.
            content_format: 'html' (default) or 'markdown'

        Returns:
            Confirmation with the document ID and web link.
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service
        drive_service = lc.drive_service

        doc = docs_service.documents().get(documentId=doc_id).execute()
        body_content = doc.get("body", {}).get("content", [])
        end_index = body_content[-1].get("endIndex", 2) if body_content else 2

        clear_requests = []
        if end_index > 2:
            clear_requests.append(
                {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}
            )

        content_requests, tables = _to_doc_requests(content, content_format, start_index=1)
        all_requests = clear_requests + content_requests
        if all_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": all_requests}
            ).execute()
        fill_tables(docs_service, doc_id, tables)

        metadata = (
            drive_service.files()
            .get(fileId=doc_id, fields="webViewLink", supportsAllDrives=True)
            .execute()
        )

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("Wrote content to doc %s", doc_id)
        return {"docId": doc_id, "web_link": metadata.get("webViewLink")}

    @tool(annotations=ToolAnnotations(title="Get Document Structure", readOnlyHint=True))
    def get_doc_structure(doc_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Return the full structural map of a Google Doc body with element indices.

        Every batchUpdate operation (insert, delete, style, table) requires knowing
        the startIndex and endIndex of the target element. This tool exposes those
        indices alongside paragraph styles, text run formatting, and table cell positions.

        Args:
            doc_id: The Google Doc file ID.

        Returns:
            Dictionary with docId, title, and an elements list. Each element has:
            - type: "paragraph" | "table" | "sectionBreak" | "tableOfContents"
            - startIndex, endIndex
            Paragraphs also include namedStyleType, text, and a runs list (each run
            has text, bold, italic, underline, strikethrough, font_size, link_url).
            Tables include rows, columns, and a cells list (each cell has row, col,
            startIndex, endIndex, paragraphStartIndex, text).
        """
        lc = ctx.request_context.lifespan_context
        try:
            doc = lc.docs_service.documents().get(documentId=doc_id).execute()
        except Exception as e:
            return {"error": str(e)}

        elements = []
        for elem in doc.get("body", {}).get("content", []):
            if "paragraph" in elem:
                para = elem["paragraph"]
                named_style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
                runs = []
                for pe in para.get("elements", []):
                    tr = pe.get("textRun")
                    if not tr:
                        continue
                    ts = tr.get("textStyle", {})
                    runs.append(
                        {
                            "text": tr.get("content", ""),
                            "bold": ts.get("bold"),
                            "italic": ts.get("italic"),
                            "underline": ts.get("underline"),
                            "strikethrough": ts.get("strikethrough"),
                            "font_size": ts["fontSize"].get("magnitude")
                            if "fontSize" in ts
                            else None,
                            "link_url": ts["link"].get("url") if "link" in ts else None,
                        }
                    )
                elements.append(
                    {
                        "type": "paragraph",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                        "namedStyleType": named_style,
                        "text": "".join(r["text"] for r in runs),
                        "runs": runs,
                    }
                )
            elif "table" in elem:
                table = elem["table"]
                cells = []
                for r, row in enumerate(table.get("tableRows", [])):
                    for c, cell in enumerate(row.get("tableCells", [])):
                        content = cell.get("content", [])
                        para_start = content[0].get("startIndex") if content else None
                        cell_text = "".join(
                            pe.get("textRun", {}).get("content", "")
                            for ce in content
                            if "paragraph" in ce
                            for pe in ce["paragraph"].get("elements", [])
                        )
                        cells.append(
                            {
                                "row": r,
                                "col": c,
                                "startIndex": cell.get("startIndex"),
                                "endIndex": cell.get("endIndex"),
                                "paragraphStartIndex": para_start,
                                "text": cell_text.strip(),
                            }
                        )
                elements.append(
                    {
                        "type": "table",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                        "rows": table.get("rows", 0),
                        "columns": table.get("columns", 0),
                        "cells": cells,
                    }
                )
            elif "sectionBreak" in elem:
                elements.append(
                    {
                        "type": "sectionBreak",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                    }
                )
            elif "tableOfContents" in elem:
                elements.append(
                    {
                        "type": "tableOfContents",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                    }
                )

        logger.debug("get_doc_structure: %d elements in doc %s", len(elements), doc_id)
        return {
            "docId": doc.get("documentId"),
            "title": doc.get("title"),
            "elements": elements,
        }

    @tool(annotations=ToolAnnotations(title="Insert Document Text", destructiveHint=True))
    def insert_doc_text(
        doc_id: str,
        insertions: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert text at one or more positions in a Google Doc.

        All indices are interpreted as positions in the document before any of
        the insertions in this call. Insertions are applied high-index-first so
        earlier indices are not shifted by later ones.

        Use get_doc_structure to obtain the correct target indices.

        Args:
            doc_id: The Google Doc file ID.
            insertions: List of insertion dicts. Required keys:
                index (int): document position to insert at.
                text (str): text to insert. "\\n" creates a new paragraph.
              Optional keys:
                segment_id (str): segmentId of the header or footer to insert into
                    (the headerId / footerId returned by create_header / create_footer).
                    Omit to insert into the document body.

        Returns:
            Confirmation with docId and count of insertions applied.
        """
        lc = ctx.request_context.lifespan_context
        if not insertions:
            return {"error": "insertions list is empty"}
        try:
            sorted_ops = sorted(insertions, key=lambda x: x["index"], reverse=True)
            requests = []
            for op in sorted_ops:
                location: dict[str, Any] = {"index": op["index"]}
                if "segment_id" in op:
                    location["segmentId"] = op["segment_id"]
                requests.append({"insertText": {"location": location, "text": op["text"]}})
            lc.docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()
        except Exception as e:
            return {"error": str(e)}
        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_doc_text: %d insertions in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "insertions": len(requests)}

    @tool(annotations=ToolAnnotations(title="Delete Document Range", destructiveHint=True))
    def delete_doc_range(
        doc_id: str,
        deletions: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete one or more content ranges from a Google Doc.

        All indices are interpreted as positions in the document before any of
        the deletions in this call. Deletions are applied high-index-first so
        earlier indices are not shifted by later ones.

        Use get_doc_structure to obtain the correct start/end indices.

        Args:
            doc_id: The Google Doc file ID.
            deletions: List of {"start_index": int, "end_index": int}.
                The range [start_index, end_index) is deleted (end_index is exclusive).
                Do not include the document's final newline (last endIndex - 1).

        Returns:
            Confirmation with docId and count of deletions applied.
        """
        lc = ctx.request_context.lifespan_context
        if not deletions:
            return {"error": "deletions list is empty"}
        try:
            sorted_ops = sorted(deletions, key=lambda x: x["start_index"], reverse=True)
            requests = [
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": op["start_index"],
                            "endIndex": op["end_index"],
                        }
                    }
                }
                for op in sorted_ops
            ]
            lc.docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()
        except Exception as e:
            return {"error": str(e)}
        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("delete_doc_range: %d deletions in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "deletions": len(requests)}

    @tool(annotations=ToolAnnotations(title="Insert Inline Image", destructiveHint=True))
    def insert_inline_image(
        doc_id: str,
        index: int,
        uri: str | None = None,
        drive_file_id: str | None = None,
        width: float | None = None,
        height: float | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an inline image at a specific index in a Google Doc.

        Provide either uri (a publicly accessible HTTPS image URL) or drive_file_id
        (a Drive file ID for an image stored in Drive). The image is inserted at the
        given document index.

        Use get_doc_structure to find a suitable insertion index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the image should be inserted.
            uri: A publicly accessible image URI (HTTPS). Mutually exclusive with drive_file_id.
            drive_file_id: A Google Drive file ID for an image stored in Drive.
                The file must be accessible by the authenticated user.
                Mutually exclusive with uri.
            width: Optional image width in points.
            height: Optional image height in points.

        Returns:
            Confirmation with docId and the insertion index.
        """
        if not uri and not drive_file_id:
            return {"error": "Provide either uri or drive_file_id"}
        if uri and drive_file_id:
            return {"error": "Provide only one of uri or drive_file_id, not both"}

        lc = ctx.request_context.lifespan_context

        if drive_file_id:
            try:
                metadata = (
                    lc.drive_service.files()
                    .get(fileId=drive_file_id, fields="webContentLink", supportsAllDrives=True)
                    .execute()
                )
                uri = metadata.get("webContentLink")
                if not uri:
                    return {"error": f"Could not get download link for Drive file {drive_file_id}"}
            except Exception as e:
                return {"error": f"Failed to get Drive file metadata: {e}"}

        image_request: dict[str, Any] = {
            "insertInlineImage": {
                "location": {"index": index},
                "uri": uri,
            }
        }
        if width is not None or height is not None:
            object_size: dict[str, Any] = {}
            if width is not None:
                object_size["width"] = {"magnitude": width, "unit": "PT"}
            if height is not None:
                object_size["height"] = {"magnitude": height, "unit": "PT"}
            image_request["insertInlineImage"]["objectSize"] = object_size

        try:
            lc.docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": [image_request]}
            ).execute()
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_inline_image: at index %d in doc %s", index, doc_id)
        return {"docId": doc_id, "index": index}
