import asyncio
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

from ...auth import execute_in_thread, thread_http
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


async def _list_drive_children(drive_service, folder_id: str) -> tuple[list[dict], list[dict]]:
    """Return (files, folders) among the direct children of a Drive folder."""
    results = await execute_in_thread(
        drive_service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="files(id, name, mimeType, modifiedTime)",
            pageSize=1000,
        )
        .execute,
        drive_service,
    )
    files: list[dict] = []
    folders: list[dict] = []
    for f in results.get("files", []):
        if f["mimeType"] == "application/vnd.google-apps.folder":
            folders.append(f)
        else:
            files.append(f)
    return files, folders


async def _sync_level(
    lc,
    drive_service,
    drive_folder_id: str | None,
    dest_dir: Path,
    rel_prefix: str,
    direction: str,
    export_format: str | None,
    skip_system_files: bool,
    dry_run: bool,
    recursive: bool,
    uploaded: list[str],
    downloaded: list[str],
    skipped: list[str],
    conflicts: list[str],
    failed: list[dict[str, str]],
    actions: list[dict[str, str]],
    folders_skipped: list[str],
    ctx: Context,
    progress_count: list[int],
) -> int:
    """
    Sync the files directly inside one Drive-folder/local-dir pair and, if `recursive`,
    descend into subfolders matched by name. `drive_folder_id=None` simulates a Drive
    folder that doesn't exist yet (used for dry-run planning of a not-yet-created
    upload-direction folder) — no Drive API call is made and drive-side maps stay empty.

    Returns bytes downloaded at this level and below; all other results are appended
    into the shared accumulator lists/dicts passed in from the top-level call.
    """
    drive_files: list[dict] = []
    drive_folders: list[dict] = []
    if drive_folder_id is not None:
        drive_files, drive_folders = await _list_drive_children(drive_service, drive_folder_id)

    drive_map: dict[str, dict] = {}
    for f in drive_files:
        is_workspace = f["mimeType"].startswith("application/vnd.google-apps.")
        if is_workspace:
            if not export_format:
                continue  # excluded without an export format
            local_name = f["name"] + _EXPORT_MIME[export_format][1]
        else:
            local_name = f["name"]
        drive_map[local_name] = f

    local_map: dict[str, Path] = {}
    if dest_dir.is_dir():
        for p in dest_dir.iterdir():
            if not p.is_file():
                continue
            if skip_system_files and p.name in _SYSTEM_FILES:
                continue
            local_map[p.name] = p

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
                        {"name": name, "action": "upload", "reason": f"local newer by {diff:.0f}s"}
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

    for step in plan:
        actions.append({**step, "name": f"{rel_prefix}{step['name']}"})

    total_bytes = 0

    if dry_run:
        for step in plan:
            rel_name = f"{rel_prefix}{step['name']}"
            if step["action"] == "skip":
                skipped.append(rel_name)
            elif step["action"] == "conflict":
                conflicts.append(rel_name)
            # upload/download actions aren't materialized during dry_run
    else:

        async def _run_one(step: dict[str, str]) -> dict[str, Any]:
            name = step["name"]
            action = step["action"]

            if action == "skip":
                return {"kind": "skip", "name": name}

            if action == "conflict":
                return {"kind": "conflict", "name": name}

            if action == "upload":
                p = local_map[name]
                mime, _ = mimetypes.guess_type(str(p))
                mime = mime or "application/octet-stream"
                lmtime_str = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                )

                try:
                    media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
                    if name in drive_map:
                        fid = drive_map[name]["id"]
                        await execute_in_thread(
                            drive_service.files()
                            .update(
                                fileId=fid,
                                body={"modifiedTime": lmtime_str},
                                media_body=media,
                                supportsAllDrives=True,
                                fields="id",
                            )
                            .execute,
                            drive_service,
                        )
                        logger.debug("Synced (update) %s%s → Drive", rel_prefix, name)
                    else:
                        await execute_in_thread(
                            drive_service.files()
                            .create(
                                body={
                                    "name": name,
                                    "parents": [drive_folder_id],
                                    "modifiedTime": lmtime_str,
                                },
                                media_body=media,
                                supportsAllDrives=True,
                                fields="id",
                            )
                            .execute,
                            drive_service,
                        )
                        logger.debug("Synced (create) %s%s → Drive", rel_prefix, name)
                    return {"kind": "upload_ok", "name": name}
                except Exception as e:
                    return {"kind": "upload_fail", "name": name, "error": str(e)}

            # action == "download"
            entry = drive_map[name]
            fid = entry["id"]
            is_workspace = entry["mimeType"].startswith("application/vnd.google-apps.")
            dest_file = dest_dir / name
            try:
                if is_workspace:
                    target_mime = _EXPORT_MIME[export_format][0]
                    content = await execute_in_thread(
                        drive_service.files().export(fileId=fid, mimeType=target_mime).execute,
                        drive_service,
                    )
                    if not isinstance(content, bytes):
                        content = content.encode("utf-8")
                    await asyncio.to_thread(dest_file.write_bytes, content)
                else:

                    def _download_to_completion(fid=fid, dest_file=dest_file) -> None:
                        request = drive_service.files().get_media(fileId=fid)
                        request.http = thread_http(drive_service)
                        with dest_file.open("wb") as fh:
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()

                    await asyncio.to_thread(_download_to_completion)
                size = dest_file.stat().st_size
                logger.debug("Synced (download) Drive → %s%s (%d bytes)", rel_prefix, name, size)
                return {"kind": "download_ok", "name": name, "bytes": size}
            except Exception as e:
                return {"kind": "download_fail", "name": name, "error": str(e)}

        async def _run_one_with_progress(step: dict[str, str]) -> dict[str, Any]:
            result = await _run_one(step)
            # Report per-item, not after the whole gather resolves — the gather
            # blocks until every concurrent transfer at this level finishes, so
            # reporting afterward would deliver a single silent burst instead of
            # live progress during the wait (the actual complaint in #316).
            if result["kind"] in ("upload_ok", "upload_fail", "download_ok", "download_fail"):
                progress_count[0] += 1
                await ctx.report_progress(
                    progress_count[0],
                    None,
                    f"{rel_prefix}{result['name']}: {result['kind']}",
                )
            return result

        # return_exceptions=True: every failure path inside _run_one is already caught
        # and converted into a *_fail result dict, but this also lets every in-flight
        # transfer finish before surfacing an unexpected exception, instead of
        # orphaning in-flight uploads/downloads. Thread-pool default (~32 workers)
        # means very large plans queue rather than fully parallelizing — timing stays
        # accurate, just with diminishing returns past that.
        raw = await asyncio.gather(
            *(_run_one_with_progress(step) for step in plan), return_exceptions=True
        )

        level_changed = False
        for step, o in zip(plan, raw, strict=True):
            rel_name = f"{rel_prefix}{step['name']}"
            if isinstance(o, BaseException):
                failed.append({"name": rel_name, "error": str(o)})
                continue
            kind = o["kind"]
            if kind == "skip":
                skipped.append(rel_name)
            elif kind == "conflict":
                conflicts.append(rel_name)
            elif kind == "upload_ok":
                uploaded.append(rel_name)
                level_changed = True
            elif kind == "download_ok":
                downloaded.append(rel_name)
                total_bytes += o["bytes"]
                level_changed = True
            else:  # upload_fail / download_fail
                failed.append({"name": rel_name, "error": o["error"]})

        if level_changed:
            lc.drive_folder_cache.mark_dirty(drive_folder_id)

    if recursive:
        drive_folder_map = {f["name"]: f for f in drive_folders}
        local_folder_map: dict[str, Path] = {}
        if dest_dir.is_dir():
            for p in dest_dir.iterdir():
                if not p.is_dir():
                    continue
                if skip_system_files and p.name in _SYSTEM_FILES:
                    continue
                local_folder_map[p.name] = p

        # (child_drive_id, child_dest_dir, child_rel_prefix) for every subfolder that
        # survives the prep step below and is ready to be recursed into.
        child_calls: list[tuple[str | None, Path, str]] = []

        for name in sorted(drive_folder_map.keys() | local_folder_map.keys()):
            in_drive = name in drive_folder_map
            in_local = name in local_folder_map
            child_rel_prefix = f"{rel_prefix}{name}/"
            child_dest_dir = dest_dir / name

            if in_drive and in_local:
                child_drive_id = drive_folder_map[name]["id"]
            elif in_drive:
                if direction not in ("download", "bidirectional"):
                    folders_skipped.append(child_rel_prefix)
                    continue
                child_drive_id = drive_folder_map[name]["id"]
                if not dry_run:
                    # A Drive file and a Drive folder can share a name (they're keyed
                    # by ID, not name) — if the file-level pass above just downloaded
                    # a same-named file here, exist_ok=True won't save us since the
                    # existing path isn't a directory.
                    if child_dest_dir.exists() and not child_dest_dir.is_dir():
                        failed.append(
                            {
                                "name": child_rel_prefix,
                                "error": (
                                    f"cannot create local folder '{name}': a file with "
                                    "the same name already exists at this path"
                                ),
                            }
                        )
                        continue
                    child_dest_dir.mkdir(parents=True, exist_ok=True)
            else:  # local only
                if direction not in ("upload", "bidirectional"):
                    folders_skipped.append(child_rel_prefix)
                    continue
                if dry_run:
                    child_drive_id = None  # simulate: not created yet
                else:
                    try:
                        created = await execute_in_thread(
                            drive_service.files()
                            .create(
                                body={
                                    "name": name,
                                    "mimeType": "application/vnd.google-apps.folder",
                                    "parents": [drive_folder_id],
                                },
                                supportsAllDrives=True,
                                fields="id",
                            )
                            .execute,
                            drive_service,
                        )
                    except Exception as e:
                        failed.append({"name": child_rel_prefix, "error": str(e)})
                        continue
                    child_drive_id = created["id"]
                    lc.drive_folder_cache.mark_dirty(drive_folder_id)

            child_calls.append((child_drive_id, child_dest_dir, child_rel_prefix))

        async def _descend(
            child_drive_id: str | None, child_dest_dir: Path, child_rel_prefix: str
        ) -> int:
            return await _sync_level(
                lc,
                drive_service,
                child_drive_id,
                child_dest_dir,
                child_rel_prefix,
                direction,
                export_format,
                skip_system_files,
                dry_run,
                recursive,
                uploaded,
                downloaded,
                skipped,
                conflicts,
                failed,
                actions,
                folders_skipped,
                ctx,
                progress_count,
            )

        # Sibling subfolders are independent — descend into all of them concurrently
        # instead of awaiting one at a time, same rationale as the file-level gather
        # above. Shared accumulator lists are safe to append into concurrently since
        # asyncio coroutines never actually run in parallel, only interleaved at
        # await points.
        child_results = await asyncio.gather(
            *(_descend(*c) for c in child_calls), return_exceptions=True
        )
        for (_, _, child_rel_prefix), r in zip(child_calls, child_results, strict=True):
            if isinstance(r, BaseException):
                failed.append({"name": child_rel_prefix, "error": str(r)})
            else:
                total_bytes += r

    return total_bytes


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
    async def export_file(
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

        metadata = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="id, name, mimeType", supportsAllDrives=True)
            .execute,
            drive_service,
        )
        file_mime = metadata.get("mimeType", "")
        is_google_workspace = file_mime.startswith("application/vnd.google-apps.")

        if export_format == "raw" or not is_google_workspace:

            def _download_to_completion() -> bytes:
                request = drive_service.files().get_media(fileId=file_id)
                request.http = thread_http(drive_service)
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return buf.getvalue()

            raw_bytes = await asyncio.to_thread(_download_to_completion)
            target_mime = file_mime
            content_bytes = raw_bytes
        else:
            if export_format not in _EXPORT_MIME:
                raise ValueError(
                    f"Unknown export_format '{export_format}'. "
                    f"Valid options: {', '.join(_EXPORT_MIME)}, raw"
                )
            target_mime = _EXPORT_MIME[export_format][0]
            content_bytes = await execute_in_thread(
                drive_service.files().export(fileId=file_id, mimeType=target_mime).execute,
                drive_service,
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
    async def list_revisions(file_id: str, ctx: Context = None) -> list[dict[str, Any]]:
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
        result = await execute_in_thread(
            drive_service.revisions()
            .list(
                fileId=file_id,
                fields="revisions(id,modifiedTime,lastModifyingUser/displayName,keepForever)",
            )
            .execute,
            drive_service,
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
    async def export_revision(
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

        revision = await execute_in_thread(
            drive_service.revisions()
            .get(fileId=file_id, revisionId=revision_id, fields="exportLinks,modifiedTime")
            .execute,
            drive_service,
        )

        xlsx_url = revision.get("exportLinks", {}).get(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        if not xlsx_url:
            raise ValueError(
                f"No XLSX export available for revision {revision_id}. "
                "The file may not be a Google Sheets file."
            )

        # thread_http(drive_service) must be called inside the worker thread's closure, not
        # eagerly here on the event-loop thread — see execute_in_thread's docstring in auth.py.
        _, content = await asyncio.to_thread(lambda: thread_http(drive_service).request(xlsx_url))
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
    async def upload_file(
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
            result = await execute_in_thread(
                drive_service.files()
                .create(
                    body=file_body,
                    media_body=media,
                    supportsAllDrives=True,
                    fields="id, name, parents, webViewLink",
                )
                .execute,
                drive_service,
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
    async def upload_local_file(
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
            existing = await execute_in_thread(
                drive_service.files()
                .list(
                    q=f"name='{safe_name}' and '{parent_folder_id}' in parents and trashed=false",
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="files(id, name, webViewLink)",
                    pageSize=1,
                )
                .execute,
                drive_service,
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
            result = await execute_in_thread(
                drive_service.files()
                .create(
                    body=metadata,
                    media_body=media,
                    supportsAllDrives=True,
                    fields="id, name, webViewLink",
                )
                .execute,
                drive_service,
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
    async def upload_local_folder(
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
            existing_resp = await execute_in_thread(
                drive_service.files()
                .list(
                    q=f"'{parent_folder_id}' in parents and trashed=false",
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="files(name)",
                    pageSize=1000,
                )
                .execute,
                drive_service,
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
                await execute_in_thread(
                    drive_service.files()
                    .create(
                        body=metadata,
                        media_body=media,
                        supportsAllDrives=True,
                        fields="id",
                    )
                    .execute,
                    drive_service,
                )
                uploaded.append(p.name)
                logger.debug("Uploaded %s (%s)", p.name, mime)
            except Exception as e:
                failed.append({"name": p.name, "error": str(e)})

        if uploaded:
            lc.drive_folder_cache.mark_dirty(parent_folder_id)

        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

    @tool(annotations=ToolAnnotations(title="Download File", readOnlyHint=True))
    async def download_file(
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

        metadata = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="name, mimeType", supportsAllDrives=True)
            .execute,
            drive_service,
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
            content = await execute_in_thread(
                drive_service.files().export(fileId=file_id, mimeType=target_mime).execute,
                drive_service,
            )
            if not isinstance(content, bytes):
                content = content.encode("utf-8")
            await asyncio.to_thread(dest.write_bytes, content)
        else:

            def _download_to_completion() -> None:
                request = drive_service.files().get_media(fileId=file_id)
                request.http = thread_http(drive_service)
                with dest.open("wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

            await asyncio.to_thread(_download_to_completion)

        size = dest.stat().st_size
        logger.debug("Downloaded %s → %s (%d bytes)", file_id, dest, size)
        return {"local_path": str(dest), "name": drive_name, "size_bytes": size}

    @tool(annotations=ToolAnnotations(title="Download Folder", readOnlyHint=True))
    async def download_folder(
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
        to that format. Subfolders are always skipped, regardless of export_format —
        this tool never descends into them.

        Files transfer concurrently rather than one at a time. If the caller supplied
        a progressToken, a `notifications/progress` update is sent as each file
        finishes (e.g. "12/217: report.pdf: ok").

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

        results = await execute_in_thread(
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
            .execute,
            drive_service,
        )

        downloaded: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []
        total_bytes = 0

        candidates: list[tuple[str, str, bool, Path]] = []
        for f in results.get("files", []):
            fid = f["id"]
            fname = f["name"]
            fmime = f.get("mimeType", "")

            if fmime == "application/vnd.google-apps.folder":
                # Non-recursive: subfolders are never descended into or exported.
                skipped.append(fname)
                continue

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

            candidates.append((fid, fname, is_workspace, dest_file))

        total = len(candidates)
        completed = 0

        async def _download_one(
            fid: str, fname: str, is_workspace: bool, dest_file: Path
        ) -> dict[str, Any]:
            nonlocal completed
            try:
                if is_workspace:
                    target_mime = _EXPORT_MIME[export_format][0]
                    content = await execute_in_thread(
                        drive_service.files().export(fileId=fid, mimeType=target_mime).execute,
                        drive_service,
                    )
                    if not isinstance(content, bytes):
                        content = content.encode("utf-8")
                    await asyncio.to_thread(dest_file.write_bytes, content)
                else:

                    def _download_to_completion(fid=fid, dest_file=dest_file) -> None:
                        request = drive_service.files().get_media(fileId=fid)
                        request.http = thread_http(drive_service)
                        with dest_file.open("wb") as fh:
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()

                    await asyncio.to_thread(_download_to_completion)

                size = dest_file.stat().st_size
                logger.debug("Downloaded %s → %s (%d bytes)", fid, dest_file, size)
                result: dict[str, Any] = {"kind": "ok", "name": dest_file.name, "bytes": size}
            except Exception as e:
                result = {"kind": "fail", "name": fname, "error": str(e)}

            # Reported here, inside the per-item coroutine, so updates stream in as
            # each concurrent download finishes rather than arriving in one burst
            # after asyncio.gather resolves — see #316.
            completed += 1
            await ctx.report_progress(completed, total, f"{completed}/{total}: {result['name']}")
            return result

        # Concurrent fan-out, same pattern as _sync_level's _run_one: previously this
        # was a sequential `for` loop awaiting one transfer at a time (#316), which
        # measured 1.04s/file and scaled linearly with folder size.
        raw = await asyncio.gather(*(_download_one(*c) for c in candidates), return_exceptions=True)

        for c, o in zip(candidates, raw, strict=True):
            if isinstance(o, BaseException):
                failed.append({"name": c[1], "error": str(o)})
                continue
            if o["kind"] == "ok":
                downloaded.append(o["name"])
                total_bytes += o["bytes"]
            else:
                failed.append({"name": o["name"], "error": o["error"]})

        return {
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "size_bytes": total_bytes,
        }

    @tool(annotations=ToolAnnotations(title="Sync Folder", destructiveHint=True))
    async def sync_folder(
        folder_id: str,
        local_path: str,
        direction: str = "bidirectional",
        export_format: str | None = None,
        skip_system_files: bool = True,
        dry_run: bool = False,
        recursive: bool = False,
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

        ## recursive

        By default (recursive=False) only files directly inside `folder_id` /
        `local_path` are considered — subfolders are ignored entirely, on either side.

        When recursive=True, subfolders matched by name (same rules as files) are
        walked to any depth. A subfolder present on only one side is only descended
        into — and created on the missing side — when `direction` would actually
        create it there:
          - a Drive-only subfolder is downloaded (local dir created) when direction
            includes download; left alone under 'upload' direction.
          - a local-only subfolder is uploaded (Drive folder created) when direction
            includes upload; left alone under 'download' direction.
        Subfolders left alone this way are listed under 'folders_skipped' (relative
        path, trailing '/') instead of being silently ignored.

        ## dry_run

        When dry_run=True no files or folders are created/transferred. The response
        includes an 'actions' list showing every file considered at every level
        visited, with the reason.

        ## Progress

        File transfers within each level run concurrently rather than one at a time.
        If the caller supplied a progressToken, a `notifications/progress` update is
        sent as each individual upload/download completes (skips and conflicts don't
        emit updates — they're free, not transfers). No update is sent during dry_run,
        since nothing is transferred.

        Args:
            folder_id: Google Drive folder ID to sync against.
            local_path: Local directory path to sync against (created if needed).
            direction: 'bidirectional', 'upload', or 'download'.
            export_format: Required to include Workspace files in the sync. They are
                           exported/compared using this format (e.g. 'pdf', 'docx', 'csv').
            skip_system_files: Skip .DS_Store and similar OS metadata files (default True).
            dry_run: If True, plan the sync but transfer nothing.
            recursive: If True, also sync matching subfolders at any depth (see above).
                       Defaults to False — a single call only covers the top-level folder.

        Returns:
            uploaded, downloaded, skipped, conflicts, failed lists (relative paths —
            just the filename at the top level, 'subdir/name' for nested matches when
            recursive descends), 'folders_skipped' (relative subfolder paths not
            entered — always empty when recursive=False), size_bytes transferred,
            dry_run flag, and — when dry_run=True — an 'actions' list with
            {name, action, reason} for every file considered at every level visited.
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

        uploaded: list[str] = []
        downloaded: list[str] = []
        skipped: list[str] = []
        conflicts: list[str] = []
        failed: list[dict[str, str]] = []
        actions: list[dict[str, str]] = []
        folders_skipped: list[str] = []

        total_bytes = await _sync_level(
            lc,
            drive_service,
            folder_id,
            dest_dir,
            "",
            direction,
            export_format,
            skip_system_files,
            dry_run,
            recursive,
            uploaded,
            downloaded,
            skipped,
            conflicts,
            failed,
            actions,
            folders_skipped,
            ctx,
            [0],
        )

        result: dict[str, Any] = {
            "uploaded": uploaded,
            "downloaded": downloaded,
            "skipped": skipped,
            "conflicts": conflicts,
            "failed": failed,
            "folders_skipped": folders_skipped,
            "size_bytes": total_bytes,
            "dry_run": dry_run,
        }
        if dry_run:
            result["actions"] = actions

        # recursive=True removes the previous implicit bound (one folder's direct
        # children) on every list here, especially 'actions' during a dry run — the
        # decision doc's own reproduction case (22 subfolders / ~225 files) is a
        # realistic scale to hit the cap.
        enforce_response_size_cap(
            result,
            tool_name="sync_folder",
            hint="Recursive syncs can produce very large result lists. Narrow "
            "folder_id, direction, or recursive scope, or ",
            local_path_available=False,
        )
        return result
