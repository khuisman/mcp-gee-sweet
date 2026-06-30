import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from . import _SA_QUOTA_ERROR

logger = logging.getLogger(__name__)


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

        query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
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
        mime = f["mimeType"]
        result: dict[str, Any] = {
            "id": f["id"],
            "name": f["name"],
            "mimeType": mime,
            "parents": f.get("parents", []),
            "created_time": f.get("createdTime"),
            "modified_time": f.get("modifiedTime"),
            "owners": [o.get("emailAddress") for o in f.get("owners", [])],
            "web_link": f.get("webViewLink"),
            "trashed": f.get("trashed", False),
        }
        # Workspace files (Docs, Sheets, Slides, etc.) don't consume storage quota;
        # the Drive API returns quotaBytesUsed as "size", which is misleading.
        if not mime.startswith("application/vnd.google-apps.") and f.get("size") is not None:
            result["size"] = f["size"]
        return result

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

    @tool(annotations=ToolAnnotations(title="List Shared With Me", readOnlyHint=True))
    def list_shared_with_me(
        mime_type: str | None = None,
        max_results: int = 50,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List files explicitly shared with the authenticated user.

        Args:
            mime_type: Optional MIME type filter, e.g.
                       'application/vnd.google-apps.spreadsheet'.
            max_results: Maximum number of files to return (default 50, max 200).

        Returns:
            List of shared files with id, name, mime_type, modified_time, owners,
            and web_link, ordered by modification time descending.
            Note: With service account auth, returns files shared with the service
            account email, not files shared with a personal user.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = min(max(1, max_results), 200)

        parts = ["sharedWithMe=true", "trashed=false"]
        if mime_type:
            parts.append(f"mimeType='{mime_type.replace(chr(39), chr(39) * 2)}'")

        results = (
            drive_service.files()
            .list(
                q=" and ".join(parts),
                pageSize=max_results,
                spaces="drive",
                fields="files(id, name, mimeType, modifiedTime, owners, webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        return [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "modified_time": f.get("modifiedTime"),
                "owners": [o.get("emailAddress") for o in f.get("owners", [])],
                "web_link": f.get("webViewLink"),
            }
            for f in results.get("files", [])
        ]

    @tool(annotations=ToolAnnotations(title="List Recent Files", readOnlyHint=True))
    def list_recent_files(
        max_results: int = 20,
        days: int | None = None,
        mime_type: str | None = None,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List recently modified files in Drive, newest first.

        Args:
            max_results: Maximum number of files to return (default 20, max 100).
            days: If provided, only return files modified within the last N days.
            mime_type: Optional MIME type filter.

        Returns:
            List of files with id, name, mime_type, modified_time, owners, and web_link,
            ordered by modification time descending.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = min(max(1, max_results), 100)

        parts = ["trashed=false"]
        if days is not None and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            parts.append(f"modifiedTime > '{cutoff}'")
        if mime_type:
            parts.append(f"mimeType='{mime_type.replace(chr(39), chr(39) * 2)}'")

        results = (
            drive_service.files()
            .list(
                q=" and ".join(parts),
                pageSize=max_results,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, mimeType, modifiedTime, owners, webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        return [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "modified_time": f.get("modifiedTime"),
                "owners": [o.get("emailAddress") for o in f.get("owners", [])],
                "web_link": f.get("webViewLink"),
            }
            for f in results.get("files", [])
        ]

    @tool(annotations=ToolAnnotations(title="Get Storage Quota", readOnlyHint=True))
    def get_storage_quota(ctx: Context = None) -> dict[str, Any]:
        """
        Get Drive storage usage and limits for the authenticated account.

        Returns:
            Storage quota with limit_bytes, usage_bytes, usage_in_drive_bytes,
            usage_in_trash_bytes, email, and display_name. All byte values are
            integers. limit_bytes is None if the key is absent, or 0 if the API
            returns "0" (typical for service accounts with no personal quota).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        about = drive_service.about().get(fields="storageQuota,user").execute()

        quota = about.get("storageQuota", {})
        user = about.get("user", {})

        return {
            "email": user.get("emailAddress"),
            "display_name": user.get("displayName"),
            "limit_bytes": int(quota["limit"]) if quota.get("limit") else None,
            "usage_bytes": int(quota.get("usage", 0)),
            "usage_in_drive_bytes": int(quota.get("usageInDrive", 0)),
            "usage_in_trash_bytes": int(quota.get("usageInDriveTrash", 0)),
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
