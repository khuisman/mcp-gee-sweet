import asyncio
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ..sheets.helpers import _quote_sheet_name
from . import _SA_QUOTA_ERROR

logger = logging.getLogger(__name__)

_CSV_IMPORT_CHUNK_ROWS = 5000


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Spreadsheet", destructiveHint=True))
    async def create_spreadsheet(
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
            spreadsheet = await execute_in_thread(
                drive_service.files()
                .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
                .execute,
                drive_service,
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

    @tool(annotations=ToolAnnotations(title="Import CSV to Sheet", destructiveHint=True))
    async def import_csv_to_sheet(
        local_path: str,
        title: str,
        folder_id: str | None = None,
        sheet_name: str = "Sheet1",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new Google Spreadsheet populated from a local CSV file.

        Reads the CSV, creates the spreadsheet, expands the sheet's grid to fit
        the data (avoiding the default 1000-row/26-column limit), and writes
        every row in one or more batched value updates.

        Args:
            local_path: Absolute path to the local .csv file.
            title: Title for the new spreadsheet.
            folder_id: Optional Google Drive folder ID where the spreadsheet should
                      be created. If not provided, uses the configured default
                      folder or creates in root.
            sheet_name: Name of the sheet the data is written to (default "Sheet1").

        Returns:
            spreadsheetId, title, web_link, and rows_written on full success. Rows are
            written in row-range chunks that run concurrently; if one or more chunks
            fail, the spreadsheet (already created) may have some rows missing — not
            necessarily a clean prefix. In that case returns an 'error' summary plus
            spreadsheetId, title, web_link, rows_attempted, failed_ranges (start_row,
            end_row, error per failed chunk), and written_ranges (start_row, end_row
            per chunk that succeeded), so the missing rows can be retried precisely.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
        """
        path = Path(local_path)
        if not path.exists():
            return {"error": f"File not found: {local_path}"}
        if path.suffix.lower() != ".csv":
            return {"error": f"Unsupported file extension '{path.suffix}'. Use .csv"}

        def _read_csv() -> list[list[str]]:
            with path.open(newline="", encoding="utf-8") as f:
                return list(csv.reader(f))

        rows = await asyncio.to_thread(_read_csv)

        if not rows:
            return {"error": f"CSV file is empty: {local_path}"}

        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        sheets_service = lc.sheets_service
        target_folder_id = folder_id or lc.folder_id

        file_body = {"name": title, "mimeType": "application/vnd.google-apps.spreadsheet"}
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            spreadsheet = await execute_in_thread(
                drive_service.files()
                .create(
                    supportsAllDrives=True,
                    body=file_body,
                    fields="id, name, parents, webViewLink",
                )
                .execute,
                drive_service,
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

        spreadsheet_id = spreadsheet.get("id")
        target_folder_id = target_folder_id or (spreadsheet.get("parents", [None])[0])

        spreadsheet_meta = await execute_in_thread(
            sheets_service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties))",
            )
            .execute,
            sheets_service,
        )
        default_sheet = spreadsheet_meta.get("sheets", [{}])[0]
        default_props = default_sheet.get("properties", {})
        sheet_id = default_props.get("sheetId", 0)
        default_title = default_props.get("title")
        grid = default_props.get("gridProperties", {})

        requests: list[dict[str, Any]] = []
        if default_title != sheet_name:
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "title": sheet_name},
                        "fields": "title",
                    }
                }
            )
        needed_rows, needed_cols = len(rows), width
        if needed_rows > grid.get("rowCount", 1000) or needed_cols > grid.get("columnCount", 26):
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {
                                "rowCount": max(needed_rows, grid.get("rowCount", 1000)),
                                "columnCount": max(needed_cols, grid.get("columnCount", 26)),
                            },
                        },
                        "fields": "gridProperties.rowCount,gridProperties.columnCount",
                    }
                }
            )

        if requests:
            await execute_in_thread(
                sheets_service.spreadsheets()
                .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
                .execute,
                sheets_service,
            )
            lc.cache.mark_dirty(spreadsheet_id)

        quoted_sheet = _quote_sheet_name(sheet_name)

        async def _write_chunk(start: int, chunk: list[list]) -> dict[str, Any]:
            row_range = {"start_row": start + 1, "end_row": start + len(chunk)}
            try:
                await execute_in_thread(
                    sheets_service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=spreadsheet_id,
                        range=f"{quoted_sheet}!A{start + 1}",
                        valueInputOption="USER_ENTERED",
                        body={"values": chunk},
                    )
                    .execute,
                    sheets_service,
                )
                return {**row_range, "ok": True}
            except Exception as e:
                return {**row_range, "ok": False, "error": str(e)}

        # Safe to parallelize: each chunk writes a disjoint row range of the same
        # sheet (A{start+1} onward, non-overlapping), so there's no read-modify-write
        # race between chunks. Unlike the old sequential loop — where a failure left a
        # clean truncated prefix — a concurrent failure can leave a hole mid-sheet (an
        # earlier chunk can still be in flight when a later one succeeds), so failures
        # are reported per-range rather than as a single opaque exception.
        chunks = [
            (start, rows[start : start + _CSV_IMPORT_CHUNK_ROWS])
            for start in range(0, len(rows), _CSV_IMPORT_CHUNK_ROWS)
        ]
        chunk_results: list[dict[str, Any]] = []
        if chunks:
            raw = await asyncio.gather(
                *(_write_chunk(start, chunk) for start, chunk in chunks), return_exceptions=True
            )
            chunk_results = [
                r
                if not isinstance(r, BaseException)
                else {
                    "start_row": start + 1,
                    "end_row": start + len(chunk),
                    "ok": False,
                    "error": str(r),
                }
                for (start, chunk), r in zip(chunks, raw, strict=True)
            ]

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)
        lc.sheet_data_cache.mark_dirty(spreadsheet_id)

        failed_ranges = [
            {"start_row": r["start_row"], "end_row": r["end_row"], "error": r["error"]}
            for r in chunk_results
            if not r["ok"]
        ]
        if failed_ranges:
            written_ranges = [
                {"start_row": r["start_row"], "end_row": r["end_row"]}
                for r in chunk_results
                if r["ok"]
            ]
            return {
                "error": (
                    f"{len(failed_ranges)} of {len(chunk_results)} row-range write(s) failed. "
                    "The spreadsheet was already created and some rows may be missing "
                    "(not necessarily a clean prefix — chunks write concurrently). See "
                    "failed_ranges for exactly which rows need to be retried."
                ),
                "spreadsheetId": spreadsheet_id,
                "title": spreadsheet.get("name", title),
                "web_link": spreadsheet.get("webViewLink"),
                "rows_attempted": len(rows),
                "failed_ranges": failed_ranges,
                "written_ranges": written_ranges,
            }

        logger.debug(
            "Imported CSV %s into spreadsheet %s (%d rows, %d cols)",
            local_path,
            spreadsheet_id,
            len(rows),
            width,
        )

        return {
            "spreadsheetId": spreadsheet_id,
            "title": spreadsheet.get("name", title),
            "web_link": spreadsheet.get("webViewLink"),
            "rows_written": len(rows),
        }

    @tool(annotations=ToolAnnotations(title="List Spreadsheets", readOnlyHint=True))
    async def list_spreadsheets(
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

        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name)",
                orderBy="modifiedTime desc",
            )
            .execute,
            drive_service,
        )

        return [{"id": f["id"], "title": f["name"]} for f in results.get("files", [])]

    @tool(annotations=ToolAnnotations(title="List Folders", readOnlyHint=True))
    async def list_folders(
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

        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, parents)",
                orderBy="name",
            )
            .execute,
            drive_service,
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
    async def list_drives(
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

        # Sequential by nature — each page's pageToken depends on the previous
        # response, so this isn't a gather() candidate.
        drives: list[dict[str, Any]] = []
        while len(drives) < max_results:
            result = await execute_in_thread(
                drive_service.drives().list(**kwargs).execute,
                drive_service,
            )
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
    async def list_files(
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

        results = await execute_in_thread(
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
            .execute,
            drive_service,
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
    async def search_files(
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
            results = await execute_in_thread(
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
                .execute,
                drive_service,
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
    async def search_spreadsheets(
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
            results = await execute_in_thread(
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
                .execute,
                drive_service,
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
    async def get_file_metadata(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Get metadata for any file or folder in Google Drive.

        Args:
            file_id: The Google Drive file or folder ID.

        Returns:
            id, name, mimeType, parents, createdTime, modifiedTime, size,
            owners, webViewLink, and trashed status.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        f = await execute_in_thread(
            drive_service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, parents, createdTime, modifiedTime, size, owners, webViewLink, trashed",
                supportsAllDrives=True,
            )
            .execute,
            drive_service,
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
    async def create_folder(
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

        folder = await execute_in_thread(
            drive_service.files()
            .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
            .execute,
            drive_service,
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
    async def copy_file(
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
            copied = await execute_in_thread(
                drive_service.files()
                .copy(
                    fileId=file_id,
                    body=body,
                    supportsAllDrives=True,
                    fields="id, name, mimeType, parents, webViewLink",
                )
                .execute,
                drive_service,
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
    async def move_file(
        file_id: str, destination_folder_id: str, ctx: Context = None
    ) -> dict[str, Any]:
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

        existing = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute,
            drive_service,
        )
        previous_parents = ",".join(existing.get("parents", []))

        updated = await execute_in_thread(
            drive_service.files()
            .update(
                fileId=file_id,
                addParents=destination_folder_id,
                removeParents=previous_parents,
                supportsAllDrives=True,
                fields="id, name, parents, mimeType",
            )
            .execute,
            drive_service,
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
    async def rename_file(file_id: str, new_name: str, ctx: Context = None) -> dict[str, Any]:
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

        updated = await execute_in_thread(
            drive_service.files()
            .update(
                fileId=file_id,
                body={"name": new_name},
                supportsAllDrives=True,
                fields="id, name, parents",
            )
            .execute,
            drive_service,
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
    async def list_shared_with_me(
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

        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=" and ".join(parts),
                pageSize=max_results,
                spaces="drive",
                fields="files(id, name, mimeType, modifiedTime, owners, webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute,
            drive_service,
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
    async def list_recent_files(
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

        results = await execute_in_thread(
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
            .execute,
            drive_service,
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
    async def get_storage_quota(ctx: Context = None) -> dict[str, Any]:
        """
        Get Drive storage usage and limits for the authenticated account.

        Returns:
            Storage quota with limit_bytes, usage_bytes, usage_in_drive_bytes,
            usage_in_trash_bytes, email, and display_name. All byte values are
            integers. limit_bytes is None if the key is absent, or 0 if the API
            returns "0" (typical for service accounts with no personal quota).
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        about = await execute_in_thread(
            drive_service.about().get(fields="storageQuota,user").execute,
            drive_service,
        )

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
    async def delete_file(
        file_id: str, permanent: bool = False, ctx: Context = None
    ) -> dict[str, Any]:
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
        existing = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute,
            drive_service,
        )
        for parent in existing.get("parents", []):
            lc.drive_folder_cache.mark_dirty(parent)

        if permanent:
            await execute_in_thread(
                drive_service.files().delete(fileId=file_id, supportsAllDrives=True).execute,
                drive_service,
            )
            logger.debug("Permanently deleted file %s", file_id)
            return {"fileId": file_id, "action": "deleted"}

        await execute_in_thread(
            drive_service.files()
            .update(
                fileId=file_id,
                body={"trashed": True},
                supportsAllDrives=True,
                fields="id",
            )
            .execute,
            drive_service,
        )
        logger.debug("Trashed file %s", file_id)
        return {"fileId": file_id, "action": "trashed"}
