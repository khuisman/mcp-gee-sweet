import html as html_module
import logging
from html.parser import HTMLParser
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from .drive import _SA_QUOTA_ERROR

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


def _fill_table_cell_requests_from_doc(doc: dict, tables_data: list[list[list[str]]]) -> list[dict]:
    """Return insertText requests for table cells using live cell indices from a fetched doc."""
    doc_tables = [
        element["table"] for element in doc.get("body", {}).get("content", []) if "table" in element
    ]

    fill_requests = []
    for doc_table, table_data in zip(doc_tables, tables_data):
        if not table_data:
            continue
        for r, table_row_entry in enumerate(doc_table.get("tableRows", [])):
            if r >= len(table_data):
                break
            for c, doc_cell in enumerate(table_row_entry.get("tableCells", [])):
                if c >= len(table_data[r]):
                    break
                cell_text = table_data[r][c]
                if not cell_text:
                    continue
                cell_content = doc_cell.get("content", [])
                if cell_content:
                    fill_requests.append(
                        {
                            "insertText": {
                                "location": {"index": cell_content[0]["startIndex"]},
                                "text": cell_text,
                            }
                        }
                    )

    # Sort high → low so each insertion does not shift indices of unprocessed cells
    fill_requests.sort(key=lambda r: r["insertText"]["location"]["index"], reverse=True)
    return fill_requests


def _fill_tables(docs_service, doc_id: str, tables: list[list[list[str]]]) -> None:
    """Re-fetch doc and fill table cells in a second batchUpdate; no-op if tables is empty."""
    if not tables:
        return
    live_doc = docs_service.documents().get(documentId=doc_id).execute()
    fill_requests = _fill_table_cell_requests_from_doc(live_doc, tables)
    if fill_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id, body={"requests": fill_requests}
        ).execute()


def _html_to_doc_requests(
    html_content: str, start_index: int = 1
) -> tuple[list[dict], list[list[list[str]]]]:
    """Convert HTML to Docs API batchUpdate requests with heading, bullet, link, and table formatting.

    Mapping: h1 → HEADING_1, h2-h6 → HEADING_3, li → bullet, <a href> → link,
    <table> → Docs table (empty structure, interleaved in document order). Indices are
    UTF-16 code units; for BMP-only content Python len() is correct.

    Returns (requests, tables_data). Table cells are NOT filled here — the caller must
    execute a second batchUpdate using _fill_table_cell_requests_from_doc after fetching
    the updated document to obtain actual cell indices.
    """

    class _DocParser(HTMLParser):
        def __init__(self):
            super().__init__()
            # Ordered list of items as they appear in the HTML source.
            # Each item is ("segment", tag, text, links) or ("table", rows).
            self.items: list[tuple] = []
            self._tag: str | None = None
            self._buf: list[str] = []
            self._pending_links: list[tuple[int, int, str]] = []
            self._in_anchor = False
            self._anchor_url: str | None = None
            self._anchor_char_start = 0
            self._table_depth = 0
            self._current_table: list[list[str]] = []
            self._current_row: list[str] = []
            self._in_cell = False
            self._cell_buf: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self._table_depth += 1
                if self._table_depth == 1:
                    self._current_table = []
            elif tag == "tr" and self._table_depth == 1:
                self._current_row = []
            elif tag in ("td", "th") and self._table_depth == 1:
                self._in_cell = True
                self._cell_buf = []
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li") and not self._table_depth:
                self._tag = tag
                self._buf = []
                self._pending_links = []
            elif tag == "a" and self._tag:
                href = dict(attrs).get("href", "")
                if href:
                    self._in_anchor = True
                    self._anchor_url = href
                    self._anchor_char_start = sum(len(b) for b in self._buf)

        def handle_endtag(self, tag):
            if tag == "table":
                if self._table_depth == 1 and self._current_table:
                    self.items.append(("table", self._current_table))
                    self._current_table = []
                self._table_depth -= 1
            elif tag == "tr" and self._table_depth == 1:
                if self._current_row:
                    self._current_table.append(self._current_row)
                self._current_row = []
            elif tag in ("td", "th") and self._table_depth == 1:
                self._current_row.append("".join(self._cell_buf).strip())
                self._in_cell = False
                self._cell_buf = []
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li") and not self._table_depth:
                raw = "".join(self._buf)
                text = raw.strip()
                if text:
                    leading_ws = len(raw) - len(raw.lstrip())
                    adjusted_links = [
                        (max(0, s - leading_ws), max(0, e - leading_ws), u)
                        for s, e, u in self._pending_links
                    ]
                    self.items.append((self._tag, text, adjusted_links))
                self._tag = None
                self._buf = []
                self._pending_links = []
                self._in_anchor = False
            elif tag == "a" and self._tag and self._in_anchor:
                char_end = sum(len(b) for b in self._buf)
                self._pending_links.append((self._anchor_char_start, char_end, self._anchor_url))
                self._in_anchor = False
                self._anchor_url = None

        def handle_data(self, data):
            if self._in_cell:
                self._cell_buf.append(data)
            elif self._tag:
                self._buf.append(data)

        def handle_entityref(self, name):
            text = html_module.unescape(f"&{name};")
            if self._in_cell:
                self._cell_buf.append(text)
            elif self._tag:
                self._buf.append(text)

        def handle_charref(self, name):
            text = html_module.unescape(f"&#{name};")
            if self._in_cell:
                self._cell_buf.append(text)
            elif self._tag:
                self._buf.append(text)

    parser = _DocParser()
    parser.feed(html_content)

    if not parser.items:
        return [], []

    # --- Build full text and per-segment metadata, tracking where tables belong ---
    # All text segments are concatenated into one string. Table insertion positions are
    # tracked as absolute document indices in the text-only document (after start_index).
    # Tables are then appended to the request list in REVERSE order so each insertion
    # does not shift the index of tables that precede it.
    full_text = ""
    segment_meta: list[tuple] = []  # (tag, doc_start, doc_end, links)
    tables_data: list[list[list[str]]] = []
    table_insert_positions: list[int] = []  # doc index where each table should be inserted

    for item in parser.items:
        if item[0] == "table":
            _, table_rows = item
            tables_data.append(table_rows)
            # Table is inserted at the current end of the text in document index space
            table_insert_positions.append(start_index + len(full_text))
        else:
            tag, text, links = item
            doc_start = start_index + len(full_text)
            full_text += text + "\n"
            doc_end = start_index + len(full_text)
            segment_meta.append((tag, doc_start, doc_end, links))

    requests: list[dict] = []

    # --- One insertText for all paragraph content ---
    if full_text:
        requests.append({"insertText": {"location": {"index": start_index}, "text": full_text}})

        for tag, doc_start, doc_end, links in segment_meta:
            rng = {"startIndex": doc_start, "endIndex": doc_end}

            if tag == "h1":
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": "HEADING_1"},
                            "fields": "namedStyleType",
                        }
                    }
                )
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif tag in ("h2", "h3", "h4", "h5", "h6"):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": "HEADING_3"},
                            "fields": "namedStyleType",
                        }
                    }
                )
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif tag == "p":
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif tag == "li":
                requests.append(
                    {
                        "createParagraphBullets": {
                            "range": rng,
                            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                        }
                    }
                )

            for link_start, link_end, url in links:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": {
                                "startIndex": doc_start + link_start,
                                "endIndex": doc_start + link_end,
                            },
                            "textStyle": {"link": {"url": url}},
                            "fields": "link",
                        }
                    }
                )

    # --- insertTable requests in REVERSE order ---
    # Inserting last-to-first ensures each table's position is unaffected by later
    # insertions (which only shift content at higher indices).
    for i in range(len(tables_data) - 1, -1, -1):
        table_rows = tables_data[i]
        num_rows = len(table_rows)
        num_cols = max((len(row) for row in table_rows), default=0)
        if num_rows > 0 and num_cols > 0:
            requests.append(
                {
                    "insertTable": {
                        "rows": num_rows,
                        "columns": num_cols,
                        "location": {"index": table_insert_positions[i]},
                    }
                }
            )

    return requests, tables_data


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Document", destructiveHint=True))
    def create_doc(
        title: str,
        content: str | None = None,
        folder_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new Google Doc, optionally with initial content.

        Content is interpreted as HTML. Headings, paragraphs, lists, links, and tables
        are converted to the corresponding Google Docs formatting. Tables are appended
        after all paragraph content. Nested tables are not supported.

        Args:
            title: The title of the new document
            content: Optional HTML content for the document body
            folder_id: Optional Google Drive folder ID where the document should be created.
                      If not provided, creates in the root of My Drive.

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

        file_body = {
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
            content_requests, tables = _html_to_doc_requests(content, start_index=1)
            if content_requests:
                docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": content_requests}
                ).execute()
            _fill_tables(docs_service, doc_id, tables)

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        return {
            "docId": doc_id,
            "title": doc.get("name", title),
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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace the full content of an existing Google Doc.

        Content is interpreted as HTML. Headings, paragraphs, lists, links, and tables
        are converted to the corresponding Google Docs formatting. Tables are appended
        after all paragraph content. Use this to populate a doc that was created
        manually in Drive (bypassing service account storage quota limits).

        Args:
            doc_id: The Google Doc file ID.
            content: HTML content to write into the document body.

        Returns:
            Confirmation with the document ID and web link.
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service
        drive_service = lc.drive_service

        # Get current doc to find its end index so we can clear existing content
        doc = docs_service.documents().get(documentId=doc_id).execute()
        body_content = doc.get("body", {}).get("content", [])
        end_index = body_content[-1].get("endIndex", 2) if body_content else 2

        clear_requests = []
        # Delete everything except the final paragraph marker (endIndex is exclusive)
        if end_index > 2:
            clear_requests.append(
                {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}
            )

        content_requests, tables = _html_to_doc_requests(content, start_index=1)
        all_requests = clear_requests + content_requests
        if all_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": all_requests}
            ).execute()
        _fill_tables(docs_service, doc_id, tables)

        metadata = (
            drive_service.files()
            .get(fileId=doc_id, fields="webViewLink", supportsAllDrives=True)
            .execute()
        )

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("Wrote content to doc %s", doc_id)
        return {"docId": doc_id, "web_link": metadata.get("webViewLink")}
