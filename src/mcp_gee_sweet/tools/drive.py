import base64
import html as html_module
import io
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
            content_requests = _html_to_doc_requests(content, start_index=1)
            if content_requests:
                docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": content_requests}
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

    @tool(annotations=ToolAnnotations(title="Create Folder", destructiveHint=True))
    def create_folder(
        name: str, parent_folder_id: str | None = None, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Create a new folder in Google Drive.

        Args:
            name: The name of the new folder
            parent_folder_id: Optional parent folder ID. If not provided, creates in
                              the configured default folder or the root of My Drive.

        Returns:
            Information about the newly created folder including its ID
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_parent_id = parent_folder_id or lc.folder_id

        file_body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if target_parent_id:
            file_body["parents"] = [target_parent_id]

        folder = (
            drive_service.files()
            .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
            .execute()
        )

        folder_id = folder.get("id")
        parents = folder.get("parents")
        logger.debug("Folder created with ID: %s", folder_id)

        if target_parent_id:
            lc.drive_folder_cache.mark_dirty(target_parent_id)

        return {
            "folderId": folder_id,
            "name": folder.get("name", name),
            "parent": parents[0] if parents else "root",
        }

    @tool(annotations=ToolAnnotations(title="Move File", destructiveHint=True))
    def move_file(file_id: str, destination_folder_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Move a file or folder to a different folder in Google Drive.

        Args:
            file_id: The ID of the file or folder to move
            destination_folder_id: The ID of the destination folder

        Returns:
            Updated file metadata including new parent folder
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        existing = (
            drive_service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        previous_parents = ",".join(existing.get("parents", []))

        updated = (
            drive_service.files()
            .update(
                fileId=file_id,
                addParents=destination_folder_id,
                removeParents=previous_parents,
                supportsAllDrives=True,
                fields="id, name, parents, mimeType",
            )
            .execute()
        )

        logger.debug("Moved file %s to folder %s", file_id, destination_folder_id)

        for old_parent in existing.get("parents", []):
            lc.drive_folder_cache.mark_dirty(old_parent)
        lc.drive_folder_cache.mark_dirty(destination_folder_id)

        parents = updated.get("parents", [])
        return {
            "fileId": updated.get("id"),
            "name": updated.get("name"),
            "mimeType": updated.get("mimeType"),
            "parent": parents[0] if parents else "root",
        }

    @tool(annotations=ToolAnnotations(title="Rename File", destructiveHint=True))
    def rename_file(file_id: str, new_name: str, ctx: Context = None) -> dict[str, Any]:
        """
        Rename a file or folder in Google Drive.

        Args:
            file_id: The ID of the file or folder to rename.
            new_name: The new name.

        Returns:
            Updated fileId, name, and parent folder ID.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        updated = (
            drive_service.files()
            .update(
                fileId=file_id,
                body={"name": new_name},
                supportsAllDrives=True,
                fields="id, name, parents",
            )
            .execute()
        )

        parents = updated.get("parents", [])
        for parent in parents:
            lc.drive_folder_cache.mark_dirty(parent)
        logger.debug("Renamed file %s to %s", file_id, new_name)
        return {
            "fileId": updated.get("id"),
            "name": updated.get("name"),
            "parent": parents[0] if parents else "root",
        }

    @tool(annotations=ToolAnnotations(title="Copy File", destructiveHint=True))
    def copy_file(
        file_id: str,
        new_name: str | None = None,
        folder_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Copy a file in Google Drive.

        Args:
            file_id: The ID of the file to copy.
            new_name: Name for the copy. Defaults to 'Copy of <original name>'.
            folder_id: Destination folder ID. Defaults to the same folder as the original.

        Returns:
            fileId, name, mimeType, parent, and webViewLink of the new copy.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        body: dict[str, Any] = {}
        if new_name:
            body["name"] = new_name
        if folder_id:
            body["parents"] = [folder_id]

        copied = (
            drive_service.files()
            .copy(
                fileId=file_id,
                body=body,
                supportsAllDrives=True,
                fields="id, name, mimeType, parents, webViewLink",
            )
            .execute()
        )

        parents = copied.get("parents", [])
        for parent in parents:
            lc.drive_folder_cache.mark_dirty(parent)
        logger.debug("Copied file %s → %s", file_id, copied.get("id"))
        return {
            "fileId": copied.get("id"),
            "name": copied.get("name"),
            "mimeType": copied.get("mimeType"),
            "parent": parents[0] if parents else "root",
            "web_link": copied.get("webViewLink"),
        }

    @tool(annotations=ToolAnnotations(title="Trash or Delete File", destructiveHint=True))
    def delete_file(file_id: str, permanent: bool = False, ctx: Context = None) -> dict[str, Any]:
        """
        Move a file to the trash or permanently delete it.

        Args:
            file_id: The ID of the file or folder to remove.
            permanent: If False (default), moves to trash (recoverable).
                       If True, permanently deletes — this cannot be undone.

        Returns:
            Confirmation with fileId and action taken ('trashed' or 'deleted').
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        # Fetch parents before deletion so we can invalidate the cache
        existing = (
            drive_service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        for parent in existing.get("parents", []):
            lc.drive_folder_cache.mark_dirty(parent)

        if permanent:
            drive_service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            logger.debug("Permanently deleted file %s", file_id)
            return {"fileId": file_id, "action": "deleted"}

        drive_service.files().update(
            fileId=file_id,
            body={"trashed": True},
            supportsAllDrives=True,
            fields="id",
        ).execute()
        logger.debug("Trashed file %s", file_id)
        return {"fileId": file_id, "action": "trashed"}

    @tool(annotations=ToolAnnotations(title="Search Files", readOnlyHint=True))
    def search_files(
        query: str,
        mime_type: str | None = None,
        folder_id: str | None = None,
        max_results: int = 20,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        Search for files in Google Drive by name or content.

        Args:
            query: Search string matched against file name and full text.
            mime_type: Optional MIME type filter, e.g.
                       'application/vnd.google-apps.document',
                       'application/vnd.google-apps.spreadsheet',
                       'application/pdf'.
            folder_id: Optional folder to restrict the search to.
            max_results: Maximum results to return (default 20, max 100).

        Returns:
            List of matching files with id, name, mimeType, modified time, owners,
            parent folder, and webViewLink.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = min(max(1, max_results), 100)

        safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
        parts = [f"(name contains '{safe_query}' or fullText contains '{safe_query}')"]
        if mime_type:
            safe_mime = mime_type.replace("'", "\\'")
            parts.append(f"mimeType='{safe_mime}'")
        if folder_id:
            parts.append(f"'{folder_id}' in parents")

        try:
            results = (
                drive_service.files()
                .list(
                    q=" and ".join(parts),
                    pageSize=max_results,
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="files(id, name, mimeType, createdTime, modifiedTime, owners, parents, webViewLink)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            return [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "mimeType": f["mimeType"],
                    "modified_time": f.get("modifiedTime"),
                    "owners": [o.get("emailAddress") for o in f.get("owners", [])],
                    "parent": f.get("parents", [None])[0],
                    "web_link": f.get("webViewLink"),
                }
                for f in results.get("files", [])
            ]
        except Exception as e:
            return [{"error": f"Search failed: {e!s}"}]

    @tool(annotations=ToolAnnotations(title="Get File Metadata", readOnlyHint=True))
    def get_file_metadata(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Get metadata for any file or folder in Google Drive.

        Args:
            file_id: The Google Drive file or folder ID.

        Returns:
            id, name, mimeType, parents, createdTime, modifiedTime, size,
            owners, webViewLink, and trashed status.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        f = (
            drive_service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, parents, createdTime, modifiedTime, size, owners, webViewLink, trashed",
                supportsAllDrives=True,
            )
            .execute()
        )
        return {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "parents": f.get("parents", []),
            "created_time": f.get("createdTime"),
            "modified_time": f.get("modifiedTime"),
            "size": f.get("size"),
            "owners": [o.get("emailAddress") for o in f.get("owners", [])],
            "web_link": f.get("webViewLink"),
            "trashed": f.get("trashed", False),
        }

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

        safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
        search_query = (
            f"mimeType='application/vnd.google-apps.spreadsheet' and "
            f"(name contains '{safe_query}' or fullText contains '{safe_query}')"
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

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("Wrote content to doc %s", doc_id)
        return {"docId": doc_id, "web_link": metadata.get("webViewLink")}

    @tool(annotations=ToolAnnotations(title="Export File", readOnlyHint=True))
    def export_file(
        file_id: str,
        export_format: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Export or download a file from Google Drive.

        For Google Workspace files (Docs, Sheets, Slides) the file is converted to the
        requested format. For non-Google files the raw content is downloaded.

        Supported export_format values:
          All Google types:  'pdf', 'html'
          Google Docs:       'txt', 'docx', 'odt', 'rtf', 'epub'
          Google Sheets:     'csv', 'xlsx', 'ods'
          Google Slides:     'pptx'
          Non-Google files:  'raw'

        Args:
            file_id: The Google Drive file ID.
            export_format: One of the format strings above.

        Returns:
            fileId, name, mime_type, format, encoding ('utf-8' or 'base64'), content.
            Text formats (txt, html, csv, rtf) are returned as plain strings; all others
            are base64-encoded bytes.
        """
        from googleapiclient.http import MediaIoBaseDownload

        _EXPORT_MIME = {
            "pdf": "application/pdf",
            "html": "text/html",
            "txt": "text/plain",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "odt": "application/vnd.oasis.opendocument.text",
            "rtf": "application/rtf",
            "epub": "application/epub+zip",
            "csv": "text/csv",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "ods": "application/vnd.oasis.opendocument.spreadsheet",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        _TEXT_MIME_PREFIXES = ("text/",)

        drive_service = ctx.request_context.lifespan_context.drive_service

        metadata = (
            drive_service.files()
            .get(fileId=file_id, fields="id, name, mimeType", supportsAllDrives=True)
            .execute()
        )
        file_mime = metadata.get("mimeType", "")
        is_google_workspace = file_mime.startswith("application/vnd.google-apps.")

        if export_format == "raw" or not is_google_workspace:
            request = drive_service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            raw_bytes = buf.getvalue()
            is_text = any(file_mime.startswith(p) for p in _TEXT_MIME_PREFIXES)
            if is_text:
                return {
                    "fileId": file_id,
                    "name": metadata["name"],
                    "mime_type": file_mime,
                    "format": export_format,
                    "encoding": "utf-8",
                    "content": raw_bytes.decode("utf-8", errors="replace"),
                }
            return {
                "fileId": file_id,
                "name": metadata["name"],
                "mime_type": file_mime,
                "format": export_format,
                "encoding": "base64",
                "content": base64.b64encode(raw_bytes).decode("ascii"),
            }

        target_mime = _EXPORT_MIME.get(export_format)
        if not target_mime:
            raise ValueError(
                f"Unknown export_format '{export_format}'. "
                f"Valid options: {', '.join(_EXPORT_MIME)}, raw"
            )

        content_bytes = drive_service.files().export(fileId=file_id, mimeType=target_mime).execute()
        is_text = any(target_mime.startswith(p) for p in _TEXT_MIME_PREFIXES)
        if is_text:
            return {
                "fileId": file_id,
                "name": metadata["name"],
                "mime_type": target_mime,
                "format": export_format,
                "encoding": "utf-8",
                "content": content_bytes.decode("utf-8")
                if isinstance(content_bytes, bytes)
                else content_bytes,
            }
        return {
            "fileId": file_id,
            "name": metadata["name"],
            "mime_type": target_mime,
            "format": export_format,
            "encoding": "base64",
            "content": base64.b64encode(content_bytes).decode("ascii"),
        }

    @tool(annotations=ToolAnnotations(title="Upload File", destructiveHint=True))
    def upload_file(
        name: str,
        content: str,
        source_format: str = "text",
        folder_id: str | None = None,
        convert_to_doc: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Upload a text file to Google Drive, optionally converting it to a Google Doc.

        Args:
            name: File name (include extension, e.g. 'notes.md', 'report.html').
            content: Text content to upload.
            source_format: How to interpret the content. One of:
                           'markdown' — Markdown text; converted to HTML before upload.
                           'html'     — Raw HTML.
                           'text'     — Plain text (default).
            folder_id: Destination folder ID. Defaults to the configured folder or Drive root.
            convert_to_doc: If True, create a Google Doc instead of a raw file.
                            'markdown' and 'html' sources retain heading, list, and link
                            formatting via Drive's HTML import. 'text' uploads as plain text
                            and Drive converts it (no formatting preserved).

        Returns:
            fileId, name, parent folder ID, and webViewLink of the created file.
        """
        import markdown as _md
        from googleapiclient.http import MediaInMemoryUpload

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_folder_id = folder_id or lc.folder_id

        if source_format == "markdown":
            html_body = _md.markdown(content, extensions=["extra"])
            upload_content = (
                f"<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
                f"<body>{html_body}</body></html>"
            ).encode("utf-8")
            upload_mime = "text/html"
        elif source_format == "html":
            upload_content = content.encode("utf-8")
            upload_mime = "text/html"
        else:
            upload_content = content.encode("utf-8")
            upload_mime = "text/plain"

        file_body: dict[str, Any] = {"name": name}
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        if convert_to_doc:
            file_body["mimeType"] = "application/vnd.google-apps.document"

        media = MediaInMemoryUpload(upload_content, mimetype=upload_mime, resumable=False)
        result = (
            drive_service.files()
            .create(
                body=file_body,
                media_body=media,
                supportsAllDrives=True,
                fields="id, name, parents, webViewLink",
            )
            .execute()
        )

        file_id = result.get("id")
        parents = result.get("parents", [])
        logger.debug("Uploaded %s as file %s (convert_to_doc=%s)", name, file_id, convert_to_doc)

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        return {
            "fileId": file_id,
            "name": result.get("name", name),
            "parent": parents[0] if parents else "root",
            "web_link": result.get("webViewLink"),
        }
