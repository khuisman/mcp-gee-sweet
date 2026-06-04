import base64
import html as html_module
import io
import json
import logging
import mimetypes
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import markdown as _md
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload, MediaIoBaseDownload
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)

_SA_QUOTA_ERROR = (
    "Service accounts cannot create or copy files in personal Drive (no storage quota). "
    "Use OAuth or ADC auth for full Drive write access, or use a Shared Drive destination. "
    "Check server://auth-status for your current auth method and affected tools."
)

_EXPORT_MIME: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", ".pdf"),
    "html": ("text/html", ".html"),
    "txt": ("text/plain", ".txt"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "odt": ("application/vnd.oasis.opendocument.text", ".odt"),
    "rtf": ("application/rtf", ".rtf"),
    "epub": ("application/epub+zip", ".epub"),
    "csv": ("text/csv", ".csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "ods": ("application/vnd.oasis.opendocument.spreadsheet", ".ods"),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


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

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
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

        try:
            spreadsheet = (
                drive_service.files()
                .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

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

    @tool(annotations=ToolAnnotations(title="List File Permissions", readOnlyHint=True))
    def list_permissions(file_id: str, ctx: Context = None) -> list[dict[str, Any]]:
        """
        List all permissions on a file or folder in Google Drive.

        Args:
            file_id: The Google Drive file or folder ID.

        Returns:
            List of permissions, each with id, type, role, email_address (for user/group),
            domain (for domain permissions), display_name, expiration_time, and deleted flag.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        result = (
            drive_service.permissions()
            .list(
                fileId=file_id,
                fields="permissions(id,type,role,emailAddress,displayName,domain,expirationTime,deleted)",
                supportsAllDrives=True,
            )
            .execute()
        )

        return [
            {
                "id": p["id"],
                "type": p.get("type"),
                "role": p.get("role"),
                "email_address": p.get("emailAddress"),
                "display_name": p.get("displayName"),
                "domain": p.get("domain"),
                "expiration_time": p.get("expirationTime"),
                "deleted": p.get("deleted", False),
            }
            for p in result.get("permissions", [])
        ]

    @tool(annotations=ToolAnnotations(title="Update Permission", destructiveHint=True))
    def update_permission(
        file_id: str,
        permission_id: str,
        role: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Change the role on an existing permission for a file or folder.

        Args:
            file_id: The Google Drive file or folder ID.
            permission_id: The permission ID to update (from list_permissions).
            role: New role. One of: 'reader', 'commenter', 'writer'.

        Returns:
            Updated permissionId and role.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        _VALID_ROLES = ("reader", "commenter", "writer")
        if role not in _VALID_ROLES:
            return {"error": f"Invalid role '{role}'. Must be one of: {', '.join(_VALID_ROLES)}"}

        result = (
            drive_service.permissions()
            .update(
                fileId=file_id,
                permissionId=permission_id,
                body={"role": role},
                supportsAllDrives=True,
                fields="id,role",
            )
            .execute()
        )

        logger.debug("Updated permission %s on %s → %s", permission_id, file_id, role)
        return {"permissionId": result.get("id"), "role": result.get("role")}

    @tool(annotations=ToolAnnotations(title="Remove Permission", destructiveHint=True))
    def remove_permission(file_id: str, permission_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Revoke a permission on a file or folder.

        Args:
            file_id: The Google Drive file or folder ID.
            permission_id: The permission ID to remove (from list_permissions).

        Returns:
            Confirmation with fileId, permissionId, and action taken.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        drive_service.permissions().delete(
            fileId=file_id,
            permissionId=permission_id,
            supportsAllDrives=True,
        ).execute()

        logger.debug("Removed permission %s from %s", permission_id, file_id)
        return {"fileId": file_id, "permissionId": permission_id, "action": "removed"}

    @tool(annotations=ToolAnnotations(title="Share File", destructiveHint=True))
    def share_file(
        file_id: str,
        permissions: list[dict[str, str]],
        send_notification: bool = True,
        ctx: Context = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Share any file or folder with one or more principals.

        Args:
            file_id: The Google Drive file or folder ID.
            permissions: List of permission entries. Each must have 'type' and 'role'.
                         Additional fields depend on type:
                           type='user' or 'group' — requires 'email_address'
                           type='domain'          — requires 'domain'
                           type='anyone'          — no extra fields

                         type values: 'user', 'group', 'domain', 'anyone'
                         role values: 'reader', 'commenter', 'writer'

                         Example:
                         [
                             {'type': 'user', 'email_address': 'alice@example.com', 'role': 'writer'},
                             {'type': 'domain', 'domain': 'example.com', 'role': 'reader'},
                             {'type': 'anyone', 'role': 'reader'},
                         ]
            send_notification: Send notification email to user/group recipients (default True).

        Returns:
            Dictionary with 'successes' and 'failures' lists.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        _VALID_TYPES = ("user", "group", "domain", "anyone")
        _VALID_ROLES = ("reader", "commenter", "writer")

        successes = []
        failures = []

        for perm in permissions:
            perm_type = perm.get("type")
            role = perm.get("role", "reader")
            email_address = perm.get("email_address")
            domain = perm.get("domain")

            if perm_type not in _VALID_TYPES:
                failures.append(
                    {
                        "entry": perm,
                        "error": f"Invalid type '{perm_type}'. Must be one of: {', '.join(_VALID_TYPES)}",
                    }
                )
                continue

            if role not in _VALID_ROLES:
                failures.append(
                    {
                        "entry": perm,
                        "error": f"Invalid role '{role}'. Must be one of: {', '.join(_VALID_ROLES)}",
                    }
                )
                continue

            if perm_type in ("user", "group") and not email_address:
                failures.append(
                    {"entry": perm, "error": f"'email_address' required for type='{perm_type}'"}
                )
                continue

            if perm_type == "domain" and not domain:
                failures.append({"entry": perm, "error": "'domain' required for type='domain'"})
                continue

            body: dict[str, str] = {"type": perm_type, "role": role}
            if perm_type in ("user", "group"):
                body["emailAddress"] = email_address
            elif perm_type == "domain":
                body["domain"] = domain

            try:
                result = (
                    drive_service.permissions()
                    .create(
                        fileId=file_id,
                        body=body,
                        sendNotificationEmail=send_notification and perm_type in ("user", "group"),
                        supportsAllDrives=True,
                        fields="id",
                    )
                    .execute()
                )
                entry: dict[str, Any] = {
                    "type": perm_type,
                    "role": role,
                    "permissionId": result.get("id"),
                }
                if email_address:
                    entry["email_address"] = email_address
                if domain:
                    entry["domain"] = domain
                successes.append(entry)
            except Exception as e:
                error_details = str(e)
                if hasattr(e, "content"):
                    try:
                        error_content = json.loads(e.content)
                        error_details = error_content.get("error", {}).get("message", error_details)
                    except json.JSONDecodeError:
                        pass
                failures.append({"entry": perm, "error": f"Failed to share: {error_details}"})

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

    @tool(annotations=ToolAnnotations(title="List Shared Drives", readOnlyHint=True))
    def list_drives(
        query: str | None = None,
        max_results: int = 100,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List shared (Team) Drives accessible to the authenticated account.

        Args:
            query: Optional filter string. Supports Drive query syntax, e.g.
                   'name contains "Marketing"'. If omitted, all accessible
                   shared drives are returned.
            max_results: Maximum number of drives to return (default 100, max 200).

        Returns:
            List of shared drives, each with id, name, createdTime, and a
            capabilities summary (canAddChildren, canManageMembers, etc.).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = min(max(1, max_results), 200)

        kwargs: dict[str, Any] = {
            "pageSize": min(max_results, 100),
            "fields": "nextPageToken, drives(id, name, createdTime, capabilities)",
        }
        if query:
            kwargs["q"] = query

        drives: list[dict[str, Any]] = []
        while len(drives) < max_results:
            result = drive_service.drives().list(**kwargs).execute()
            for d in result.get("drives", []):
                drives.append(
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "created_time": d.get("createdTime"),
                        "capabilities": d.get("capabilities", {}),
                    }
                )
            next_token = result.get("nextPageToken")
            if not next_token or len(drives) >= max_results:
                break
            kwargs["pageToken"] = next_token

        logger.debug("Found %d shared drives", len(drives))
        return drives[:max_results]

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

        Note:
            Requires OAuth or ADC auth. Service accounts cannot copy files into personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        body: dict[str, Any] = {}
        if new_name:
            body["name"] = new_name
        if folder_id:
            body["parents"] = [folder_id]

        try:
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
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

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
            List of files with their ID, name, MIME type, modified time, and web link.
            Results are cached; call refresh_cache(folder_id=folder_id) to invalidate,
            or refresh_cache() to clear all caches.
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

        if export_format not in _EXPORT_MIME:
            raise ValueError(
                f"Unknown export_format '{export_format}'. "
                f"Valid options: {', '.join(_EXPORT_MIME)}, raw"
            )
        target_mime = _EXPORT_MIME[export_format][0]

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

        Note:
            Requires OAuth or ADC auth. Service accounts cannot upload files to personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
        """
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
        try:
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
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

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

    @tool(annotations=ToolAnnotations(title="Upload Local File", destructiveHint=True))
    def upload_local_file(
        local_path: str,
        parent_folder_id: str,
        name: str | None = None,
        skip_if_exists: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Upload a file from the local filesystem to a Google Drive folder.
        Handles binary and text files (images, PDFs, DOCX, XLSX, scripts, etc.).

        Args:
            local_path: Absolute path to the local file to upload.
            parent_folder_id: ID of the destination Drive folder.
            name: Name to give the file in Drive. Defaults to the local filename.
            skip_if_exists: If True (default), skip the upload and return the
                            existing file's metadata if a file with the same name
                            already exists in the destination folder.

        Returns:
            fileId, name, webViewLink, and 'skipped' (True if skip_if_exists fired).

        Note:
            Requires OAuth or ADC auth. Service accounts cannot upload files to personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        path = Path(local_path)
        if not path.is_file():
            raise ValueError(f"No file found at {local_path!r}")

        file_name = name or path.name

        if skip_if_exists:
            safe_name = file_name.replace("\\", "\\\\").replace("'", "\\'")
            existing = (
                drive_service.files()
                .list(
                    q=f"name='{safe_name}' and '{parent_folder_id}' in parents and trashed=false",
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="files(id, name, webViewLink)",
                    pageSize=1,
                )
                .execute()
            )
            hits = existing.get("files", [])
            if hits:
                logger.debug("Skipping upload — %s already exists as %s", file_name, hits[0]["id"])
                return {
                    "fileId": hits[0]["id"],
                    "name": hits[0]["name"],
                    "web_link": hits[0].get("webViewLink"),
                    "skipped": True,
                }

        mime, _ = mimetypes.guess_type(local_path)
        mime = mime or "application/octet-stream"

        metadata: dict[str, Any] = {"name": file_name, "parents": [parent_folder_id]}
        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        try:
            result = (
                drive_service.files()
                .create(
                    body=metadata,
                    media_body=media,
                    supportsAllDrives=True,
                    fields="id, name, webViewLink",
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

        lc.drive_folder_cache.mark_dirty(parent_folder_id)
        logger.debug("Uploaded %s → %s (%s)", local_path, result.get("id"), mime)
        return {
            "fileId": result.get("id"),
            "name": result.get("name", file_name),
            "web_link": result.get("webViewLink"),
            "skipped": False,
        }

    _SYSTEM_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}

    @tool(annotations=ToolAnnotations(title="Upload Local Folder", destructiveHint=True))
    def upload_local_folder(
        local_path: str,
        parent_folder_id: str,
        skip_if_exists: bool = True,
        skip_system_files: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Upload all files in a local directory (non-recursive) to a Google Drive folder.

        Args:
            local_path: Absolute path to the local directory.
            parent_folder_id: ID of the destination Drive folder.
            skip_if_exists: Skip files that already exist in the destination (default True).
            skip_system_files: Skip OS metadata files like .DS_Store (default True).

        Returns:
            Summary with lists of 'uploaded', 'skipped', and 'failed' filenames.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot upload files to personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        folder = Path(local_path)
        if not folder.is_dir():
            raise ValueError(f"No directory found at {local_path!r}")

        candidates = [p for p in folder.iterdir() if p.is_file()]
        if skip_system_files:
            candidates = [p for p in candidates if p.name not in _SYSTEM_FILES]

        uploaded: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []

        if skip_if_exists and candidates:
            existing_resp = (
                drive_service.files()
                .list(
                    q=f"'{parent_folder_id}' in parents and trashed=false",
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="files(name)",
                    pageSize=1000,
                )
                .execute()
            )
            existing_names = {f["name"] for f in existing_resp.get("files", [])}
        else:
            existing_names = set()

        for p in sorted(candidates):
            if skip_if_exists and p.name in existing_names:
                skipped.append(p.name)
                continue

            mime, _ = mimetypes.guess_type(str(p))
            mime = mime or "application/octet-stream"

            try:
                metadata: dict[str, Any] = {"name": p.name, "parents": [parent_folder_id]}
                media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
                drive_service.files().create(
                    body=metadata,
                    media_body=media,
                    supportsAllDrives=True,
                    fields="id",
                ).execute()
                uploaded.append(p.name)
                logger.debug("Uploaded %s (%s)", p.name, mime)
            except Exception as e:
                failed.append({"name": p.name, "error": str(e)})

        if uploaded:
            lc.drive_folder_cache.mark_dirty(parent_folder_id)

        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

    @tool(annotations=ToolAnnotations(title="Download File", readOnlyHint=True))
    def download_file(
        file_id: str,
        local_path: str,
        export_format: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Download a file from Google Drive to the local filesystem.

        For non-Google files the raw content is downloaded. For Google Workspace
        files (Docs, Sheets, Slides) an export_format is required to convert the
        file before download.

        If local_path is a directory, the file is saved inside it using the Drive
        filename (with an extension appended for exported Workspace files).

        Args:
            file_id: The Google Drive file ID.
            local_path: Destination file path or directory on the local filesystem.
            export_format: Required for Google Workspace files. One of:
                           Docs   → 'pdf', 'docx', 'html', 'txt', 'odt', 'rtf', 'epub'
                           Sheets → 'pdf', 'xlsx', 'csv', 'ods'
                           Slides → 'pdf', 'pptx'
                           For non-Google files omit this (raw download).

        Returns:
            local_path where the file was written, file name, and byte size.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        metadata = (
            drive_service.files()
            .get(fileId=file_id, fields="name, mimeType", supportsAllDrives=True)
            .execute()
        )
        drive_name = metadata["name"]
        file_mime = metadata.get("mimeType", "")
        is_workspace = file_mime.startswith("application/vnd.google-apps.")

        dest = Path(local_path)
        if dest.is_dir():
            if is_workspace and export_format:
                ext = _EXPORT_MIME[export_format][1] if export_format in _EXPORT_MIME else ""
                dest = dest / (drive_name + ext)
            else:
                dest = dest / drive_name

        dest.parent.mkdir(parents=True, exist_ok=True)

        if is_workspace:
            if not export_format:
                raise ValueError(
                    f"export_format is required for Google Workspace file '{drive_name}'. "
                    f"Valid options: {', '.join(_EXPORT_MIME)}"
                )
            if export_format not in _EXPORT_MIME:
                raise ValueError(
                    f"Unknown export_format '{export_format}'. Valid options: {', '.join(_EXPORT_MIME)}"
                )
            target_mime = _EXPORT_MIME[export_format][0]
            content = drive_service.files().export(fileId=file_id, mimeType=target_mime).execute()
            if not isinstance(content, bytes):
                content = content.encode("utf-8")
            dest.write_bytes(content)
        else:
            request = drive_service.files().get_media(fileId=file_id)
            with dest.open("wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

        size = dest.stat().st_size
        logger.debug("Downloaded %s → %s (%d bytes)", file_id, dest, size)
        return {"local_path": str(dest), "name": drive_name, "size_bytes": size}

    @tool(annotations=ToolAnnotations(title="Download Folder", readOnlyHint=True))
    def download_folder(
        folder_id: str,
        local_path: str,
        export_format: str | None = None,
        mime_type_filter: str | None = None,
        skip_if_exists: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Download all files in a Google Drive folder (non-recursive) to a local directory.

        For non-Google files the raw content is downloaded. Google Workspace files
        are skipped unless export_format is provided, in which case they are exported
        to that format.

        Args:
            folder_id: The Google Drive folder ID.
            local_path: Local directory to download files into (created if needed).
            export_format: If provided, Google Workspace files are exported to this
                           format (e.g. 'pdf', 'docx'). See download_file for full list.
                           Without this, Workspace files are skipped.
            mime_type_filter: Only download files matching this MIME type.
            skip_if_exists: Skip files that already exist at the destination (default True).

        Returns:
            Summary with lists of 'downloaded', 'skipped', and 'failed' filenames,
            plus total 'size_bytes' downloaded.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        dest_dir = Path(local_path)
        dest_dir.mkdir(parents=True, exist_ok=True)

        query = f"'{folder_id}' in parents and trashed=false"
        if mime_type_filter:
            safe = mime_type_filter.replace("'", "\\'")
            query += f" and mimeType='{safe}'"

        results = (
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, mimeType)",
                pageSize=1000,
                orderBy="name",
            )
            .execute()
        )

        downloaded: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []
        total_bytes = 0

        for f in results.get("files", []):
            fid = f["id"]
            fname = f["name"]
            fmime = f.get("mimeType", "")
            is_workspace = fmime.startswith("application/vnd.google-apps.")

            if is_workspace and not export_format:
                skipped.append(fname)
                continue

            if is_workspace:
                if export_format not in _EXPORT_MIME:
                    failed.append(
                        {"name": fname, "error": f"Unknown export_format '{export_format}'"}
                    )
                    continue
                ext = _EXPORT_MIME[export_format][1]
                dest_file = dest_dir / (fname + ext)
            else:
                dest_file = dest_dir / fname

            if skip_if_exists and dest_file.exists():
                skipped.append(dest_file.name)
                continue

            try:
                if is_workspace:
                    target_mime = _EXPORT_MIME[export_format][0]
                    content = (
                        drive_service.files().export(fileId=fid, mimeType=target_mime).execute()
                    )
                    if not isinstance(content, bytes):
                        content = content.encode("utf-8")
                    dest_file.write_bytes(content)
                else:
                    request = drive_service.files().get_media(fileId=fid)
                    with dest_file.open("wb") as fh:
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()

                size = dest_file.stat().st_size
                total_bytes += size
                downloaded.append(dest_file.name)
                logger.debug("Downloaded %s → %s (%d bytes)", fid, dest_file, size)
            except Exception as e:
                failed.append({"name": fname, "error": str(e)})

        return {
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "size_bytes": total_bytes,
        }

    _SYNC_MTIME_TOLERANCE = 5  # seconds — absorbs clock skew and upload-time drift

    @tool(annotations=ToolAnnotations(title="Sync Folder", destructiveHint=True))
    def sync_folder(
        folder_id: str,
        local_path: str,
        direction: str = "bidirectional",
        export_format: str | None = None,
        skip_system_files: bool = True,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Sync files between a Google Drive folder and a local directory.

        ## Sync logic

        Files are matched by name. For Google Workspace files (Docs, Sheets, Slides),
        the export extension is appended to form the local name — e.g. a Doc called
        'Notes' with export_format='docx' matches the local file 'Notes.docx'.
        Workspace files with no export_format are skipped entirely.

        For each matched name the action is decided as follows:

          Drive only  + direction includes download  → download
          Drive only  + direction is 'upload'        → skip
          Local only  + direction includes upload    → upload
          Local only  + direction is 'download'      → skip
          Both sides, mtimes within 5 s tolerance    → skip (already in sync)
          Both sides, local newer by > 5 s           → upload  (if direction includes upload)
          Both sides, Drive newer by > 5 s           → download (if direction includes download)
          Both sides, conflict (direction mismatch)  → skip, listed under 'conflicts'

        Modified times are compared in UTC. When a file is uploaded, its Drive
        modifiedTime is set to the local file's mtime so future syncs stay accurate.

        ## direction values

          'bidirectional' (default) — newer side wins; Drive-only files are downloaded,
                                      local-only files are uploaded.
          'upload'                  — only push local changes to Drive; Drive-only files
                                      and Drive-newer files are left alone.
          'download'                — only pull Drive changes locally; local-only files
                                      and local-newer files are left alone.

        ## dry_run

        When dry_run=True no files are transferred. The response includes an 'actions'
        list showing every file and what would happen, with the reason.

        Args:
            folder_id: Google Drive folder ID to sync against.
            local_path: Local directory path to sync against (created if needed).
            direction: 'bidirectional', 'upload', or 'download'.
            export_format: Required to include Workspace files in the sync. They are
                           exported/compared using this format (e.g. 'pdf', 'docx', 'csv').
            skip_system_files: Skip .DS_Store and similar OS metadata files (default True).
            dry_run: If True, plan the sync but transfer nothing.

        Returns:
            uploaded, downloaded, skipped, conflicts, failed lists (filenames),
            size_bytes transferred, dry_run flag, and — when dry_run=True — an
            'actions' list with {name, action, reason} for every file considered.
        """
        if direction not in ("bidirectional", "upload", "download"):
            raise ValueError(
                f"direction must be 'bidirectional', 'upload', or 'download', got '{direction}'"
            )
        if export_format and export_format not in _EXPORT_MIME:
            raise ValueError(
                f"Unknown export_format '{export_format}'. Valid: {', '.join(_EXPORT_MIME)}"
            )

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        dest_dir = Path(local_path)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # --- build Drive file map: local_name → {id, mimeType, drive_name, modifiedTime} ---
        results = (
            drive_service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, mimeType, modifiedTime)",
                pageSize=1000,
            )
            .execute()
        )
        drive_map: dict[str, dict] = {}
        for f in results.get("files", []):
            is_workspace = f["mimeType"].startswith("application/vnd.google-apps.")
            if is_workspace:
                if not export_format:
                    continue  # excluded without an export format
                local_name = f["name"] + _EXPORT_MIME[export_format][1]
            else:
                local_name = f["name"]
            drive_map[local_name] = f

        # --- build local file map: name → Path ---
        local_map: dict[str, Path] = {}
        for p in dest_dir.iterdir():
            if not p.is_file():
                continue
            if skip_system_files and p.name in _SYSTEM_FILES:
                continue
            local_map[p.name] = p

        # --- plan actions ---
        def _drive_mtime(entry: dict) -> datetime:
            return datetime.fromisoformat(entry["modifiedTime"].replace("Z", "+00:00"))

        def _local_mtime(p: Path) -> datetime:
            return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

        plan: list[dict[str, str]] = []
        for name in sorted(drive_map.keys() | local_map.keys()):
            in_drive = name in drive_map
            in_local = name in local_map

            if in_drive and not in_local:
                if direction in ("download", "bidirectional"):
                    plan.append({"name": name, "action": "download", "reason": "drive only"})
                else:
                    plan.append(
                        {"name": name, "action": "skip", "reason": "drive only, upload direction"}
                    )

            elif in_local and not in_drive:
                if direction in ("upload", "bidirectional"):
                    plan.append({"name": name, "action": "upload", "reason": "local only"})
                else:
                    plan.append(
                        {"name": name, "action": "skip", "reason": "local only, download direction"}
                    )

            else:
                dmtime = _drive_mtime(drive_map[name])
                lmtime = _local_mtime(local_map[name])
                diff = (lmtime - dmtime).total_seconds()

                if abs(diff) <= _SYNC_MTIME_TOLERANCE:
                    plan.append({"name": name, "action": "skip", "reason": "in sync"})
                elif diff > 0:
                    if direction in ("upload", "bidirectional"):
                        plan.append(
                            {
                                "name": name,
                                "action": "upload",
                                "reason": f"local newer by {diff:.0f}s",
                            }
                        )
                    else:
                        plan.append(
                            {
                                "name": name,
                                "action": "conflict",
                                "reason": f"local newer by {diff:.0f}s but direction is download",
                            }
                        )
                else:
                    if direction in ("download", "bidirectional"):
                        plan.append(
                            {
                                "name": name,
                                "action": "download",
                                "reason": f"drive newer by {-diff:.0f}s",
                            }
                        )
                    else:
                        plan.append(
                            {
                                "name": name,
                                "action": "conflict",
                                "reason": f"drive newer by {-diff:.0f}s but direction is upload",
                            }
                        )

        if dry_run:
            return {
                "actions": plan,
                "dry_run": True,
                "uploaded": [],
                "downloaded": [],
                "skipped": [p["name"] for p in plan if p["action"] == "skip"],
                "conflicts": [p["name"] for p in plan if p["action"] == "conflict"],
                "failed": [],
                "size_bytes": 0,
            }

        # --- execute ---
        uploaded: list[str] = []
        downloaded: list[str] = []
        skipped: list[str] = []
        conflicts: list[str] = []
        failed: list[dict[str, str]] = []
        total_bytes = 0

        for step in plan:
            name = step["name"]
            action = step["action"]

            if action == "skip":
                skipped.append(name)
                continue

            if action == "conflict":
                conflicts.append(name)
                continue

            if action == "upload":
                p = local_map[name]
                mime, _ = mimetypes.guess_type(str(p))
                mime = mime or "application/octet-stream"
                lmtime_str = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                )

                if name in drive_map:
                    # update existing file
                    fid = drive_map[name]["id"]
                    try:
                        media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
                        drive_service.files().update(
                            fileId=fid,
                            body={"modifiedTime": lmtime_str},
                            media_body=media,
                            supportsAllDrives=True,
                            fields="id",
                        ).execute()
                        uploaded.append(name)
                        logger.debug("Synced (update) %s → Drive", name)
                    except Exception as e:
                        failed.append({"name": name, "error": str(e)})
                else:
                    # create new file
                    try:
                        media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
                        drive_service.files().create(
                            body={"name": name, "parents": [folder_id], "modifiedTime": lmtime_str},
                            media_body=media,
                            supportsAllDrives=True,
                            fields="id",
                        ).execute()
                        uploaded.append(name)
                        logger.debug("Synced (create) %s → Drive", name)
                    except Exception as e:
                        failed.append({"name": name, "error": str(e)})

            elif action == "download":
                entry = drive_map[name]
                fid = entry["id"]
                is_workspace = entry["mimeType"].startswith("application/vnd.google-apps.")
                dest_file = dest_dir / name
                try:
                    if is_workspace:
                        target_mime = _EXPORT_MIME[export_format][0]
                        content = (
                            drive_service.files().export(fileId=fid, mimeType=target_mime).execute()
                        )
                        if not isinstance(content, bytes):
                            content = content.encode("utf-8")
                        dest_file.write_bytes(content)
                    else:
                        request = drive_service.files().get_media(fileId=fid)
                        with dest_file.open("wb") as fh:
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()
                    size = dest_file.stat().st_size
                    total_bytes += size
                    downloaded.append(name)
                    logger.debug("Synced (download) Drive → %s (%d bytes)", name, size)
                except Exception as e:
                    failed.append({"name": name, "error": str(e)})

        if uploaded or downloaded:
            lc.drive_folder_cache.mark_dirty(folder_id)

        return {
            "uploaded": uploaded,
            "downloaded": downloaded,
            "skipped": skipped,
            "conflicts": conflicts,
            "failed": failed,
            "size_bytes": total_bytes,
            "dry_run": False,
        }
