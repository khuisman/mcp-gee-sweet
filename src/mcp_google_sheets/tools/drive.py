import html as html_module
import json
import logging
from html.parser import HTMLParser
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)


def _html_to_text(html_content: str) -> str:
    """Convert HTML to plain text, preserving block-level line breaks."""
    _BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "tr", "blockquote"}

    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag == "br":
                self.parts.append("\n")
            elif tag in _BLOCK and self.parts and not self.parts[-1].endswith("\n"):
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


def _html_to_doc_requests(html_content: str, start_index: int = 1) -> list[dict]:
    """Convert HTML to Docs API batchUpdate requests with heading, bullet, and link formatting.

    Mapping: h1 → HEADING_1, h2-h6 → HEADING_3, li → bullet, <a href> → link.
    Indices are UTF-16 code units; for BMP-only content Python len() is correct.
    """

    class _DocParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.segments: list[tuple[str, str, list]] = []  # (tag, text, links)
            self._tag: str | None = None
            self._buf: list[str] = []
            self._pending_links: list[tuple[int, int, str]] = []  # (char_start, char_end, url)
            self._in_anchor = False
            self._anchor_url: str | None = None
            self._anchor_char_start = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
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
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
                raw = "".join(self._buf)
                text = raw.strip()
                if text:
                    leading_ws = len(raw) - len(raw.lstrip())
                    adjusted_links = [
                        (max(0, s - leading_ws), max(0, e - leading_ws), u)
                        for s, e, u in self._pending_links
                    ]
                    self.segments.append((self._tag, text, adjusted_links))
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
            if self._tag:
                self._buf.append(data)

        def handle_entityref(self, name):
            if self._tag:
                self._buf.append(html_module.unescape(f"&{name};"))

        def handle_charref(self, name):
            if self._tag:
                self._buf.append(html_module.unescape(f"&#{name};"))

    parser = _DocParser()
    parser.feed(html_content)

    if not parser.segments:
        return []

    full_text = "".join(text + "\n" for _, text, _ in parser.segments)
    requests: list[dict] = [{"insertText": {"location": {"index": start_index}, "text": full_text}}]

    idx = start_index
    for tag, text, links in parser.segments:
        seg_end = idx + len(text) + 1  # +1 for the trailing \n
        if tag == "h1":
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": idx, "endIndex": seg_end},
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "fields": "namedStyleType",
                    }
                }
            )
        elif tag in ("h2", "h3", "h4", "h5", "h6"):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": idx, "endIndex": seg_end},
                        "paragraphStyle": {"namedStyleType": "HEADING_3"},
                        "fields": "namedStyleType",
                    }
                }
            )
        elif tag == "li":
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": idx, "endIndex": seg_end},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )
        for link_start, link_end, url in links:
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": idx + link_start,
                            "endIndex": idx + link_end,
                        },
                        "textStyle": {"link": {"url": url}},
                        "fields": "link",
                    }
                }
            )
        idx = seg_end

    return requests


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Spreadsheet", destructiveHint=True))
    def create_spreadsheet(
        title: str, folder_id: str | None = None, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Create a new Google Spreadsheet.

        Args:
            title: The title of the new spreadsheet
            folder_id: Optional Google Drive folder ID where the spreadsheet should be created.
                      If not provided, uses the configured default folder or creates in root.

        Returns:
            Information about the newly created spreadsheet including its ID
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_folder_id = folder_id or lc.folder_id

        file_body = {
            "name": title,
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        spreadsheet = (
            drive_service.files()
            .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
            .execute()
        )

        spreadsheet_id = spreadsheet.get("id")
        parents = spreadsheet.get("parents")
        logger.debug(
            "Spreadsheet created with ID: %s%s",
            spreadsheet_id,
            f" in folder {target_folder_id}" if target_folder_id else " in root",
        )

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        return {
            "spreadsheetId": spreadsheet_id,
            "title": spreadsheet.get("name", title),
            "folder": parents[0] if parents else "root",
        }

    @tool(annotations=ToolAnnotations(title="Create Document", destructiveHint=True))
    def create_doc(
        title: str,
        content: str | None = None,
        folder_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new Google Doc, optionally with initial content.

        Content is interpreted as HTML. Basic formatting (headings, paragraphs, lists,
        line breaks) is preserved as plain text in the document body. Inline markup like
        <strong>/<em> and <a href="..."> link text is included but not styled.

        Args:
            title: The title of the new document
            content: Optional HTML content for the document body
            folder_id: Optional Google Drive folder ID where the document should be created.
                      If not provided, creates in the root of My Drive.

        Returns:
            Information about the newly created document including its ID and web link
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

        doc = (
            drive_service.files()
            .create(
                supportsAllDrives=True,
                body=file_body,
                fields="id, name, parents, webViewLink",
            )
            .execute()
        )

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug(
            "Doc created with ID: %s%s",
            doc_id,
            f" in folder {target_folder_id}" if target_folder_id else " in root",
        )

        if content:
            plain_text = _html_to_text(content)
            if plain_text:
                docs_service.documents().batchUpdate(
                    documentId=doc_id,
                    body={
                        "requests": [{"insertText": {"location": {"index": 1}, "text": plain_text}}]
                    },
                ).execute()

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        return {
            "docId": doc_id,
            "title": doc.get("name", title),
            "folder": parents[0] if parents else "root",
            "web_link": doc.get("webViewLink"),
        }

    @tool(annotations=ToolAnnotations(title="List Spreadsheets", readOnlyHint=True))
    def list_spreadsheets(
        folder_id: str | None = None, ctx: Context = None
    ) -> list[dict[str, str]]:
        """
        List all spreadsheets in the specified Google Drive folder.
        If no folder is specified, uses the configured default folder or lists from 'My Drive'.

        Args:
            folder_id: Optional Google Drive folder ID to search in.
                      If not provided, uses the configured default folder or searches 'My Drive'.

        Returns:
            List of spreadsheets with their ID and title
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        target_folder_id = folder_id or ctx.request_context.lifespan_context.folder_id

        query = "mimeType='application/vnd.google-apps.spreadsheet'"
        if target_folder_id:
            query += f" and '{target_folder_id}' in parents"
            logger.debug("Searching for spreadsheets in folder: %s", target_folder_id)
        else:
            logger.debug("Searching for spreadsheets in 'My Drive'")

        results = (
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        return [{"id": f["id"], "title": f["name"]} for f in results.get("files", [])]

    @tool(annotations=ToolAnnotations(title="Share Spreadsheet", destructiveHint=True))
    def share_spreadsheet(
        spreadsheet_id: str,
        recipients: list[dict[str, str]],
        send_notification: bool = True,
        ctx: Context = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Share a Google Spreadsheet with multiple users via email, assigning specific roles.

        Args:
            spreadsheet_id: The ID of the spreadsheet to share.
            recipients: A list of dictionaries, each containing 'email_address' and 'role'.
                        The role should be one of: 'reader', 'commenter', 'writer'.
                        Example: [
                            {'email_address': 'user1@example.com', 'role': 'writer'},
                            {'email_address': 'user2@example.com', 'role': 'reader'}
                        ]
            send_notification: Whether to send a notification email to the users. Defaults to True.

        Returns:
            A dictionary containing lists of 'successes' and 'failures'.
            Each item in the lists includes the email address and the outcome.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        successes = []
        failures = []

        for recipient in recipients:
            email_address = recipient.get("email_address")
            role = recipient.get("role", "writer")

            if not email_address:
                failures.append(
                    {"email_address": None, "error": "Missing email_address in recipient entry."}
                )
                continue

            if role not in ["reader", "commenter", "writer"]:
                failures.append(
                    {
                        "email_address": email_address,
                        "error": f"Invalid role '{role}'. Must be 'reader', 'commenter', or 'writer'.",
                    }
                )
                continue

            try:
                result = (
                    drive_service.permissions()
                    .create(
                        fileId=spreadsheet_id,
                        body={"type": "user", "role": role, "emailAddress": email_address},
                        sendNotificationEmail=send_notification,
                        fields="id",
                    )
                    .execute()
                )
                successes.append(
                    {"email_address": email_address, "role": role, "permissionId": result.get("id")}
                )
            except Exception as e:
                error_details = str(e)
                if hasattr(e, "content"):
                    try:
                        error_content = json.loads(e.content)
                        error_details = error_content.get("error", {}).get("message", error_details)
                    except json.JSONDecodeError:
                        pass
                failures.append(
                    {"email_address": email_address, "error": f"Failed to share: {error_details}"}
                )

        return {"successes": successes, "failures": failures}

    @tool(annotations=ToolAnnotations(title="List Folders", readOnlyHint=True))
    def list_folders(
        parent_folder_id: str | None = None, ctx: Context = None
    ) -> list[dict[str, str]]:
        """
        List all folders in the specified Google Drive folder.
        If no parent folder is specified, lists folders from 'My Drive' root.

        Args:
            parent_folder_id: Optional Google Drive folder ID to search within.
                             If not provided, searches the root of 'My Drive'.

        Returns:
            List of folders with their ID, name, and parent information
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        query = "mimeType='application/vnd.google-apps.folder'"
        if parent_folder_id:
            query += f" and '{parent_folder_id}' in parents"
            logger.debug("Searching for folders in parent folder: %s", parent_folder_id)
        else:
            query += " and 'root' in parents"
            logger.debug("Searching for folders in 'My Drive' root")

        results = (
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, parents)",
                orderBy="name",
            )
            .execute()
        )

        return [
            {
                "id": f["id"],
                "name": f["name"],
                "parent": f.get("parents", ["root"])[0] if f.get("parents") else "root",
            }
            for f in results.get("files", [])
        ]

    @tool(
        annotations=ToolAnnotations(
            title="Search Spreadsheets by Name or Content", readOnlyHint=True
        )
    )
    def search_spreadsheets(
        query: str, max_results: int = 20, ctx: Context = None
    ) -> list[dict[str, Any]]:
        """
        Search for spreadsheets in Google Drive by name or content.

        Args:
            query: Search query string. Searches in file name and content.
                   Examples: "budget 2024", "sales report", "project tracker"
            max_results: Maximum number of results to return (default 20, max 100)

        Returns:
            List of matching spreadsheets with their ID, name, and metadata
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = min(max(1, max_results), 100)

        search_query = (
            f"mimeType='application/vnd.google-apps.spreadsheet' and "
            f"(name contains '{query}' or fullText contains '{query}')"
        )

        try:
            results = (
                drive_service.files()
                .list(
                    q=search_query,
                    pageSize=max_results,
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="files(id, name, createdTime, modifiedTime, owners, webViewLink)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )

            return [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "created_time": f.get("createdTime"),
                    "modified_time": f.get("modifiedTime"),
                    "owners": [owner.get("emailAddress") for owner in f.get("owners", [])],
                    "web_link": f.get("webViewLink"),
                }
                for f in results.get("files", [])
            ]
        except Exception as e:
            return [{"error": f"Search failed: {e!s}"}]

    @tool(annotations=ToolAnnotations(title="List Files", readOnlyHint=True))
    def list_files(
        folder_id: str,
        mime_type: str | None = None,
        max_results: int = 100,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List files in a Google Drive folder, optionally filtered by MIME type.

        Args:
            folder_id: The Google Drive folder ID to list files from.
            mime_type: Optional MIME type filter. Common values:
                       'application/vnd.google-apps.document' (Google Docs)
                       'application/vnd.google-apps.spreadsheet' (Google Sheets)
                       'application/vnd.google-apps.folder' (folders)
            max_results: Maximum number of results to return (default 100, max 1000)

        Returns:
            List of files with their ID, name, MIME type, modified time, and web link
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        folder_cache = lc.drive_folder_cache
        max_results = min(max(1, max_results), 1000)

        cached = folder_cache.get(folder_id, mime_type)
        if cached is not None:
            return cached

        query = f"'{folder_id}' in parents and trashed=false"
        if mime_type:
            query += f" and mimeType='{mime_type}'"

        results = (
            drive_service.files()
            .list(
                q=query,
                pageSize=max_results,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                orderBy="name",
            )
            .execute()
        )

        files = [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "modified_time": f.get("modifiedTime"),
                "web_link": f.get("webViewLink"),
            }
            for f in results.get("files", [])
        ]
        folder_cache.store(folder_id, mime_type, files)
        return files

    @tool(annotations=ToolAnnotations(title="Get Document Content", readOnlyHint=True))
    def get_doc_content(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Get the plain text content of a Google Doc.

        Args:
            file_id: The Google Drive file ID of the document.

        Returns:
            Dictionary with the document's text content and metadata
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        metadata = (
            drive_service.files()
            .get(
                fileId=file_id, fields="id, name, modifiedTime, webViewLink", supportsAllDrives=True
            )
            .execute()
        )

        content = drive_service.files().export(fileId=file_id, mimeType="text/plain").execute()

        return {
            "id": metadata["id"],
            "name": metadata["name"],
            "modified_time": metadata.get("modifiedTime"),
            "web_link": metadata.get("webViewLink"),
            "content": content.decode("utf-8") if isinstance(content, bytes) else content,
        }

    @tool(annotations=ToolAnnotations(title="Write Document Content", destructiveHint=True))
    def write_doc_content(
        doc_id: str,
        content: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace the full content of an existing Google Doc.

        Content is interpreted as HTML. Basic formatting (headings, paragraphs, lists,
        line breaks) is preserved as plain text. Use this to populate a doc that was
        created manually in Drive (bypassing service account storage quota limits).

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

        content_requests = _html_to_doc_requests(content, start_index=1)
        all_requests = clear_requests + content_requests
        if all_requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": all_requests}
            ).execute()

        metadata = (
            drive_service.files()
            .get(fileId=doc_id, fields="webViewLink", supportsAllDrives=True)
            .execute()
        )

        logger.debug("Wrote content to doc %s", doc_id)
        return {"docId": doc_id, "web_link": metadata.get("webViewLink")}
