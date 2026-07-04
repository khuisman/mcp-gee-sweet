import base64
import io
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown as _md
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload, MediaIoBaseDownload
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..response_limits import enforce_response_size_cap
from . import _SA_QUOTA_ERROR

logger = logging.getLogger(__name__)

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

_SYSTEM_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}

_SYNC_MTIME_TOLERANCE = 5  # seconds — absorbs clock skew and upload-time drift


def _xlsx_range_values(ws, range_str: str | None) -> list[list]:
    """Return cell values from an openpyxl worksheet for the given A1 range (or all data)."""
    if not range_str:
        return [[c.value for c in row] for row in ws.iter_rows()]
    cells = ws[range_str]
    # ws[range] returns a tuple-of-tuples for a multi-cell range, a tuple of cells
    # for a single row/column slice, or a single Cell for a single address.
    if isinstance(cells, tuple) and cells and isinstance(cells[0], tuple):
        return [[c.value for c in row] for row in cells]
    if isinstance(cells, tuple):
        return [[c.value for c in cells]]
    return [[cells.value]]


def register(tool):
    @tool(annotations=ToolAnnotations(title="Export File", readOnlyHint=True))
    def export_file(
        file_id: str,
        export_format: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Export or download a file from Google Drive.

        **Prefer `download_file` when saving to disk** — this tool returns raw
        base64-encoded bytes for binary formats (xlsx, pdf, docx, etc.) that require
        manual decoding. Use `export_file` only when you need the file content in-memory.

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
            are base64-encoded bytes. Raises ValueError if the response exceeds a safety
            cap (default 40,000 characters, set MAX_TOOL_RESPONSE_CHARS to change it) —
            base64 encoding inflates raw file size by ~33%, so binary exports hit this
            cap at a much smaller *file* size than text ones. Call download_file instead
            for anything but small files; it writes raw bytes straight to disk with no
            base64/JSON overhead.
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
            target_mime = file_mime
            content_bytes = raw_bytes
        else:
            if export_format not in _EXPORT_MIME:
                raise ValueError(
                    f"Unknown export_format '{export_format}'. "
                    f"Valid options: {', '.join(_EXPORT_MIME)}, raw"
                )
            target_mime = _EXPORT_MIME[export_format][0]
            content_bytes = (
                drive_service.files().export(fileId=file_id, mimeType=target_mime).execute()
            )
            if isinstance(content_bytes, str):
                content_bytes = content_bytes.encode("utf-8")

        is_text = any(target_mime.startswith(p) for p in _TEXT_MIME_PREFIXES)
        result = {
            "fileId": file_id,
            "name": metadata["name"],
            "mime_type": target_mime,
            "format": export_format,
            "encoding": "utf-8" if is_text else "base64",
            "content": content_bytes.decode("utf-8", errors="replace")
            if is_text
            else base64.b64encode(content_bytes).decode("ascii"),
        }
        enforce_response_size_cap(
            result,
            tool_name="export_file",
            hint="Base64 encoding inflates raw file size by ~33%. Call download_file "
            "instead to write the file straight to disk without this overhead, or ",
            local_path_available=False,
        )
        return result

    @tool(annotations=ToolAnnotations(title="List Revisions", readOnlyHint=True))
    def list_revisions(file_id: str, ctx: Context = None) -> list[dict[str, Any]]:
        """
        List available revisions for a Google Drive file (Sheets, Docs, or any file).

        Returns revisions in chronological order with their ID, timestamp, and the
        user who made the change. Use the revision ID with export_revision to read
        cell data from a historical version of a spreadsheet.

        Note: Google Drive retains all revisions for 30 days, then auto-prunes unless
        keepForever is set on the revision.

        Args:
            file_id: The Google Drive file ID.

        Returns:
            List of revisions, each with revisionId, modifiedTime, modifiedBy, keepForever.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        result = (
            drive_service.revisions()
            .list(
                fileId=file_id,
                fields="revisions(id,modifiedTime,lastModifyingUser/displayName,keepForever)",
            )
            .execute()
        )
        return [
            {
                "revisionId": r["id"],
                "modifiedTime": r.get("modifiedTime"),
                "modifiedBy": r.get("lastModifyingUser", {}).get("displayName"),
                "keepForever": r.get("keepForever", False),
            }
            for r in result.get("revisions", [])
        ]

    @tool(annotations=ToolAnnotations(title="Export Revision", readOnlyHint=True))
    def export_revision(
        file_id: str,
        revision_id: str,
        range: str | None = None,
        sheet: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Export a historical revision of a Google Sheets file and return its cell data.

        Downloads the revision as an XLSX file and returns the values for the requested
        sheet and range. Use list_revisions to find the revision_id.

        Typical recovery workflow:
          1. list_revisions → find the revision ID from the timestamp before data was lost
          2. export_revision → read the affected range from that revision
          3. batch_update_cells → write the recovered values back to the current sheet

        Note: each call downloads the full file — for large spreadsheets this may be slow.

        Args:
            file_id:     The Google Drive file ID of the spreadsheet.
            revision_id: The revision ID from list_revisions.
            range:       A1 notation range to return, e.g. "A1:D20". Omit for all data.
            sheet:       Sheet (tab) name. Defaults to the first sheet.

        Returns:
            revisionId, modifiedTime, sheet name, range, and values as a list of rows.
        """
        import openpyxl

        drive_service = ctx.request_context.lifespan_context.drive_service

        revision = (
            drive_service.revisions()
            .get(fileId=file_id, revisionId=revision_id, fields="exportLinks,modifiedTime")
            .execute()
        )

        xlsx_url = revision.get("exportLinks", {}).get(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        if not xlsx_url:
            raise ValueError(
                f"No XLSX export available for revision {revision_id}. "
                "The file may not be a Google Sheets file."
            )

        _, content = drive_service._http.request(xlsx_url)
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)

        ws = wb[sheet] if sheet else wb.active
        sheet_name = ws.title
        values = _xlsx_range_values(ws, range)

        wb.close()
        return {
            "revisionId": revision_id,
            "modifiedTime": revision.get("modifiedTime"),
            "sheet": sheet_name,
            "range": range,
            "values": values,
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
