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
            insertions: List of {"index": int, "text": str}. A "\\n" in text
                creates a new paragraph; inserting "\\n" inside an existing paragraph
                splits it at that point.

        Returns:
            Confirmation with docId and count of insertions applied.
        """
        lc = ctx.request_context.lifespan_context
        if not insertions:
            return {"error": "insertions list is empty"}
        try:
            sorted_ops = sorted(insertions, key=lambda x: x["index"], reverse=True)
            requests = [
                {"insertText": {"location": {"index": op["index"]}, "text": op["text"]}}
                for op in sorted_ops
            ]
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

    @tool(annotations=ToolAnnotations(title="Style Document Range", destructiveHint=True))
    def style_doc_range(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply paragraph and/or text styles to one or more index ranges in a Google Doc.

        Use get_doc_structure to obtain the startIndex and endIndex for each target range.
        Multiple ranges can be styled in a single call; all batchUpdate requests are
        sent together.

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts. Each dict must include start_index and end_index,
                plus any combination of the style fields below:

                Paragraph style:
                  named_style_type (str): NORMAL_TEXT, HEADING_1 … HEADING_6,
                      TITLE, SUBTITLE

                Text style:
                  bold (bool), italic (bool), underline (bool), strikethrough (bool)
                  font_size (float): size in points
                  foreground_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                  link_url (str | null): set a hyperlink (null to clear)

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}

        requests = []
        for r in ranges:
            rng = {"startIndex": r["start_index"], "endIndex": r["end_index"]}

            if "named_style_type" in r:
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": r["named_style_type"]},
                            "fields": "namedStyleType",
                        }
                    }
                )

            text_style = {}
            text_fields = []
            for key, api_key in [
                ("bold", "bold"),
                ("italic", "italic"),
                ("underline", "underline"),
                ("strikethrough", "strikethrough"),
            ]:
                if key in r:
                    text_style[api_key] = r[key]
                    text_fields.append(api_key)
            if "font_size" in r:
                text_style["fontSize"] = {"magnitude": r["font_size"], "unit": "PT"}
                text_fields.append("fontSize")
            if "foreground_color" in r:
                text_style["foregroundColor"] = {"color": {"rgbColor": r["foreground_color"]}}
                text_fields.append("foregroundColor")
            if "link_url" in r:
                text_style["link"] = {"url": r["link_url"]} if r["link_url"] else {}
                text_fields.append("link")

            if text_style:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": rng,
                            "textStyle": text_style,
                            "fields": ",".join(text_fields),
                        }
                    }
                )

        if not requests:
            return {"error": "no recognised style fields in any range"}

        try:
            lc.docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("style_doc_range: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Insert Document Table", destructiveHint=True))
    def insert_doc_table(
        doc_id: str,
        index: int,
        rows: int,
        columns: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an empty table at a specific position in a Google Doc.

        The table is inserted at the given index. The document is re-fetched
        immediately to return the actual cell indices. Use those indices with
        insert_doc_text (targeting each cell's paragraphStartIndex) to fill cells,
        or with style_doc_table_cells to apply formatting.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the table should be inserted.
                Use get_doc_structure to find a suitable position (e.g. the
                endIndex of the paragraph before the intended location).
            rows: Number of table rows.
            columns: Number of table columns.

        Returns:
            precedingParagraphIndex (= index), tableStartIndex (= index + 1),
            tableEndIndex, rows, columns, and a cells list (each cell has row,
            col, startIndex, endIndex, paragraphStartIndex).
            To fully delete the table later, delete the range
            [precedingParagraphIndex, tableEndIndex] in one call.
        """
        lc = ctx.request_context.lifespan_context
        try:
            lc.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "insertTable": {
                                "rows": rows,
                                "columns": columns,
                                "location": {"index": index},
                            }
                        }
                    ]
                },
            ).execute()
        except Exception as e:
            return {"error": str(e)}

        try:
            doc = lc.docs_service.documents().get(documentId=doc_id).execute()
        except Exception as e:
            return {"error": f"table inserted but re-fetch failed: {e}"}

        table_elems = [
            elem
            for elem in doc.get("body", {}).get("content", [])
            if "table" in elem and elem.get("startIndex", 0) >= index - 1
        ]
        table_elems.sort(key=lambda e: e.get("startIndex", 0))

        for elem in table_elems:
            table = elem["table"]
            cells = []
            for r, row in enumerate(table.get("tableRows", [])):
                for c, cell in enumerate(row.get("tableCells", [])):
                    content = cell.get("content", [])
                    para_start = content[0].get("startIndex") if content else None
                    cells.append(
                        {
                            "row": r,
                            "col": c,
                            "startIndex": cell.get("startIndex"),
                            "endIndex": cell.get("endIndex"),
                            "paragraphStartIndex": para_start,
                        }
                    )
            lc.doc_cache.mark_dirty(doc_id)
            logger.debug(
                "insert_doc_table: %dx%d at index %d in doc %s", rows, columns, index, doc_id
            )
            table_start = elem.get("startIndex")
            return {
                "docId": doc_id,
                "precedingParagraphIndex": table_start - 1,
                "tableStartIndex": table_start,
                "tableEndIndex": elem.get("endIndex"),
                "rows": rows,
                "columns": columns,
                "cells": cells,
            }

        return {"error": "table inserted but could not locate it in re-fetched doc"}

    @tool(annotations=ToolAnnotations(title="Style Document Table Cells", destructiveHint=True))
    def style_doc_table_cells(
        doc_id: str,
        table_start_index: int,
        cells: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply border, padding, and background styles to table cells in a Google Doc.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure or
                insert_doc_table).
            cells: List of cell style dicts. Each dict must include row_index and
                column_index, plus any combination of:

                background_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                padding_top, padding_right, padding_bottom, padding_left (float): points
                border_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                    Applies the same color to all four borders.
                border_width (float): border line width in points
                border_dash_style (str): "SOLID", "DOT", "DASH", "DASH_DOT",
                    "LONG_DASH", "LONG_DASH_DOT" (default SOLID)
                row_span (int): default 1
                column_span (int): default 1

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.

        Example — standard data-room table style (grey header, thin border, 3.6pt padding):
            table_start_index: <from insert_doc_table>
            cells: [
              {"row_index": 0, "column_index": 0, "column_span": <num_cols>,
               "background_color": {"red": 0.953, "green": 0.953, "blue": 0.953},
               "padding_top": 3.6, "padding_right": 3.6,
               "padding_bottom": 3.6, "padding_left": 3.6,
               "border_color": {"red": 0, "green": 0, "blue": 0},
               "border_width": 0.5, "border_dash_style": "SOLID"}
            ]
        """
        lc = ctx.request_context.lifespan_context
        if not cells:
            return {"error": "cells list is empty"}

        requests = []
        for cell in cells:
            table_cell_style = {}
            fields = []

            if "background_color" in cell:
                table_cell_style["backgroundColor"] = {
                    "color": {"rgbColor": cell["background_color"]}
                }
                fields.append("backgroundColor")

            for side in ("top", "right", "bottom", "left"):
                key = f"padding_{side}"
                if key in cell:
                    api_key = f"padding{side.capitalize()}"
                    table_cell_style[api_key] = {"magnitude": cell[key], "unit": "PT"}
                    fields.append(api_key)

            if "border_color" in cell or "border_width" in cell or "border_dash_style" in cell:
                border = {}
                if "border_color" in cell:
                    border["color"] = {"color": {"rgbColor": cell["border_color"]}}
                if "border_width" in cell:
                    border["width"] = {"magnitude": cell["border_width"], "unit": "PT"}
                border["dashStyle"] = cell.get("border_dash_style", "SOLID")
                for side in ("Top", "Right", "Bottom", "Left"):
                    api_key = f"border{side}"
                    table_cell_style[api_key] = border
                    fields.append(api_key)

            if not table_cell_style:
                continue

            requests.append(
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": table_cell_style,
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": cell["row_index"],
                                "columnIndex": cell["column_index"],
                            },
                            "rowSpan": cell.get("row_span", 1),
                            "columnSpan": cell.get("column_span", 1),
                        },
                        "fields": ",".join(fields),
                    }
                }
            )

        if not requests:
            return {"error": "no style fields found in any cell"}

        try:
            lc.docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("style_doc_table_cells: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}
