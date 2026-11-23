import asyncio
import csv
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypeVar

import anyio
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread, invalidating, is_rejection
from ...deprecation import deprecated_tool
from ...local_files import LocalFileAccessError, check_read
from ..concurrency import gather_with_fallback, report_progress_safe
from ..http_errors import is_storage_quota_error
from ..pagination import iter_pages
from ..response_limits import clamp_max_results
from ..sheets.helpers import _quote_sheet_name
from . import (
    _escape_drive_query_mime_type,
    _escape_drive_query_value,
    _FolderInvalidation,
    _quota_error_text,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CSV_IMPORT_CHUNK_ROWS = 5000

# Sheets allows 60 write requests per minute per user, so an import of more than 60
# chunks (300k rows) has writes refused with 429 (measured live: 93 of 160, #1573).
# A refusal pauses every write of the import; each pause after a refused retry
# doubles, from the base to the cap, and no pause runs past the max wait, counted
# from the import's first write, after which a refusal is final.
_CSV_RATE_LIMIT_BASE_DELAY = 5.0
_CSV_RATE_LIMIT_MAX_DELAY = 60.0
_CSV_RATE_LIMIT_MAX_WAIT = 600.0

# An import's writes in flight at once. Below the default executor's smallest size
# (min(32, cpu + 4) is at least 5), so a write that passes the pause is sent then,
# not queued behind a busy thread and sent during a later pause (PR #1589 QA round 1).
_CSV_WRITE_CONCURRENCY = 4

# Sheets' grid limits, both inclusive (checked live, #1573): a workbook holds at most
# 20,000,000 cells, and a sheet at most 18,278 columns (ZZZ).
_SHEETS_CELL_LIMIT = 20_000_000
_SHEETS_COLUMN_LIMIT = 18_278

# Resends of the request that removes a failed import's spreadsheet (#1574), the same
# as markdown_export's _CLEANUP_RETRIES for its temporary Docs.
_CLEANUP_RETRIES = 3


def _csv_grid_limit_error(local_path: str, rows: int, columns: int) -> str | None:
    """The error for a CSV too large for one sheet, or None when it fits.

    Checked before the spreadsheet is created, so a refused file leaves nothing
    behind.
    """
    if columns > _SHEETS_COLUMN_LIMIT:
        return (
            f"CSV {local_path} has {columns:,} columns; a Google Sheet holds at most "
            f"{_SHEETS_COLUMN_LIMIT:,}. Nothing was created."
        )
    if rows * columns > _SHEETS_CELL_LIMIT:
        return (
            f"CSV {local_path} needs {rows:,} rows x {columns:,} columns = "
            f"{rows * columns:,} cells; a Google Sheets spreadsheet holds at most "
            f"{_SHEETS_CELL_LIMIT:,}. Split the file and import each part. "
            "Nothing was created."
        )
    return None


def _is_rate_limited(e: BaseException) -> bool:
    """A 429: Sheets refused the request for its quota and applied nothing, so it is
    safe to send again."""
    return isinstance(e, HttpError) and int(e.resp.status) == 429


class _RateLimitPause:
    """One import's shared pause for its Sheets writes (#1573).

    The write quota is per user, not per request, so a 429 on one write means every
    write sent now would be refused too: it pauses them all instead of letting each
    retry on its own and spend the window's requests on refusals. Every write goes
    through send(), which holds one of _CSV_WRITE_CONCURRENCY slots, so a write is
    sent when it passes the pause, never queued behind a thread until a later pause.

    A reply to a request sent before the current pause began says nothing about the
    window the pause waits for: its 429 doesn't extend the pause, and its success
    doesn't reset the delay. A 429 on a request sent after it doubles the delay; a
    success resets it. No pause runs past the deadline, and a 429 at or after the
    deadline is final.
    """

    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(_CSV_WRITE_CONCURRENCY)
        self._delay = 0.0
        self._pause_started = float("-inf")
        self._resume_at = 0.0
        self._deadline = time.monotonic() + _CSV_RATE_LIMIT_MAX_WAIT

    async def send(
        self,
        call: Callable[[], Awaitable[T]],
        on_pause: Callable[[float], Awaitable[None]],
    ) -> T:
        """Await call() once a slot is free and no pause is on, resending it on a 429
        until the deadline. on_pause(seconds) is awaited when a 429 starts a new
        pause. Any other error, or a 429 at or after the deadline, is raised."""
        async with self._slots:
            while True:
                sent_at = await self._wait()
                try:
                    result = await call()
                except Exception as e:
                    if not _is_rate_limited(e):
                        raise
                    paused_for = self._rate_limited(sent_at)
                    if paused_for is None:
                        raise
                    if paused_for:
                        await on_pause(paused_for)
                    continue
                self._succeeded(sent_at)
                return result

    async def _wait(self) -> float:
        """Wait out any pause; returns the send time."""
        while (remaining := self._resume_at - time.monotonic()) > 0:
            await asyncio.sleep(remaining)
        return time.monotonic()

    def _succeeded(self, sent_at: float) -> None:
        if sent_at >= self._pause_started:
            self._delay = 0.0

    def _rate_limited(self, sent_at: float) -> float | None:
        """Record a 429 on a request sent at `sent_at`. Returns None when it is final
        (the deadline has passed), the length of the pause it started, or 0.0 when a
        pause it doesn't extend is already on."""
        now = time.monotonic()
        if now >= self._deadline:
            return None
        if sent_at < self._pause_started:
            return 0.0
        self._delay = min(
            _CSV_RATE_LIMIT_MAX_DELAY, max(_CSV_RATE_LIMIT_BASE_DELAY, self._delay * 2)
        )
        self._pause_started = now
        self._resume_at = min(now + self._delay, self._deadline)
        return self._resume_at - now


async def _discard_new_spreadsheet(
    drive_service, spreadsheet: dict[str, Any], invalidate: _FolderInvalidation
) -> str:
    """Remove a spreadsheet import_csv_to_sheet created when the import failed before
    any row could have landed, so a failed import leaves nothing behind (#1574).

    Deleted outright, or moved to the trash when the create's response says this
    identity can't delete it (a Content manager on a Shared Drive can only trash).
    Returns "deleted" or "trashed"; raises whatever the request raised. Retried on a
    5xx or 429, the same policy as markdown_export._discard_temp_doc, since a failed
    removal leaves the empty spreadsheet behind. Shielded, so a cancellation arriving
    meanwhile doesn't abandon the cleanup halfway.
    """
    file_id = spreadsheet["id"]
    capabilities = spreadsheet.get("capabilities", {})
    can_delete = capabilities.get("canDelete") is not False
    files = drive_service.files()
    if can_delete:
        request = files.delete(fileId=file_id, supportsAllDrives=True)
    else:
        request = files.update(
            fileId=file_id, body={"trashed": True}, supportsAllDrives=True, fields="id"
        )
    with anyio.CancelScope(shield=True), invalidating(invalidate):
        try:
            await execute_in_thread(
                functools.partial(request.execute, num_retries=_CLEANUP_RETRIES), drive_service
            )
        except HttpError as e:
            # A retried delete whose earlier attempt landed gets a 404. Only trusted
            # when the create said this identity may delete: without that permission
            # Drive answers a delete with a misleading 404 too (#876). Caught inside
            # `invalidating`, which skips its callback on a 4xx, so the folder is
            # still marked dirty for the delete that landed (PR #1599 QA round 2).
            if not (capabilities.get("canDelete") is True and int(e.resp.status) == 404):
                raise
    return "deleted" if can_delete else "trashed"


def _grid_resize_requests(
    sheet_id: int, grid: dict[str, Any], rows: int, columns: int
) -> list[dict[str, Any]]:
    """updateSheetProperties requests that size a sheet's grid to rows x columns.

    The column change goes first, as its own request: Sheets checks a row change
    against the sheet's current column count even when one request sets both, so
    growing the default 1000x26 grid to 1,000,000 x 20 in one request is refused
    as 26M cells (checked live, #1573).
    """
    requests = []
    for field, wanted, default in (("columnCount", columns, 26), ("rowCount", rows, 1000)):
        if grid.get(field, default) != wanted:
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "gridProperties": {field: wanted}},
                        "fields": f"gridProperties.{field}",
                    }
                }
            )
    return requests


# max_results caps list_drives at 200 drives (2 full pages); the page bound only
# stops a nextPageToken that never goes falsy over empty pages (#615).
_LIST_DRIVES_MAX_PAGES = 50

# The five Drive finders search_files absorbed, and unstar_file, which star_file
# absorbed (#1528, docs/design/tool-reduction.md tiers B1 and A).
_FINDER_REMOVED_IN = "the next feature release"

# search_files' modified_within_days ceiling: 100 years. A larger value overflows
# the cutoff's datetime arithmetic (PR #1558 QA round 1).
_MAX_MODIFIED_WITHIN_DAYS = 36500
_DRIVE_EARLIEST_TIME = datetime(1970, 1, 1, tzinfo=UTC)

# search_files' order_by values, as Drive's orderBy.
_SEARCH_ORDER_BY = {"modified": "modifiedTime desc", "name": "name"}

_SEARCH_FILE_FIELDS = (
    "nextPageToken, incompleteSearch, "
    "files(id, name, mimeType, createdTime, modifiedTime, owners, parents, webViewLink, starred)"
)


def _corpora_kwargs(folder_id: str | None) -> dict[str, str]:
    """files().list() corpus for a query that may or may not be folder-scoped.

    Drive's default corpus is "user", which leaves out Shared Drive items the
    caller hasn't created or opened, even with includeItemsFromAllDrives=True: a
    service account's unscoped search found 2 of 14 matches (#1127). An
    "in parents" query isn't affected (checked live under both identities), so it
    keeps the default rather than paying for the slower allDrives corpus.
    """
    return {} if folder_id else {"corpora": "allDrives"}


async def _list_drive_files(
    drive_service,
    q: str,
    max_results: int,
    error_prefix: str,
    extra_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Shared execute+map+error-handling body for list_shared_with_me/list_recent_files.

    Both tools query files().list() against the same result field set and shape
    the response identically; only the query string, page size, and (for
    list_recent_files) the corpus differ, passed via extra_kwargs. Both include
    Shared Drive items: without the all-drives flags, Drive leaves out a Shared
    Drive file even when it was shared directly with the caller.
    """
    try:
        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=q,
                pageSize=max_results,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, mimeType, modifiedTime, owners, webViewLink)",
                orderBy="modifiedTime desc",
                **(extra_kwargs or {}),
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
    except Exception as e:
        return [{"error": f"{error_prefix} failed: {e!s}"}]


def register(tool):
    @tool(
        annotations=ToolAnnotations(title="Create Spreadsheet", destructiveHint=True),
        default=True,
        groups=("sheets",),
    )
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
            A service account has no My Drive storage, so it can only create files in a
            Shared Drive; a user identity (OAuth, or ADC with user credentials) can
            use either. ADC can also resolve to a service identity, which has the same Shared Drive-only limit.
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

        invalidate = _FolderInvalidation(lc, target_folder_id)
        try:
            with invalidating(invalidate):
                spreadsheet = await execute_in_thread(
                    drive_service.files()
                    .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
                    .execute,
                    drive_service,
                )
                invalidate.found(spreadsheet.get("parents"))
        except HttpError as e:
            if is_storage_quota_error(e):
                return {"error": _quota_error_text(drive_service)}
            raise

        spreadsheet_id = spreadsheet.get("id")
        parents = spreadsheet.get("parents")
        logger.debug(
            "Spreadsheet created with ID: %s%s",
            spreadsheet_id,
            f" in folder {target_folder_id}" if target_folder_id else " in root",
        )

        return {
            "spreadsheetId": spreadsheet_id,
            "title": spreadsheet.get("name", title),
            "folder": parents[0] if parents else "root",
        }

    @tool(
        annotations=ToolAnnotations(title="Import CSV to Sheet", destructiveHint=True),
        local_only=True,
        groups=("sheets",),
    )
    async def import_csv_to_sheet(
        local_path: str,
        title: str,
        folder_id: str | None = None,
        sheet_name: str = "Sheet1",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new Google Spreadsheet populated from a local CSV file.
        Not available when the server runs with LOCAL_FILE_ACCESS=off.

        Reads the CSV as UTF-8, dropping a leading byte-order mark (Excel's
        "CSV UTF-8" export writes one); a file in another encoding returns an
        error before anything is created. Then creates the spreadsheet, sizes
        the sheet's grid to exactly the data's rows and columns (replacing the
        default 1000x26 grid, so a short or narrow file gets no blank padding),
        and writes every row in one or more batched value updates.

        A CSV over Google Sheets' limits (20,000,000 cells, or 18,278 columns)
        returns an error before anything is created.

        Row chunks write concurrently rather than one at a time. If the
        caller supplied a progressToken, a `notifications/progress` update is sent
        as each chunk finishes. Sheets allows 60 writes a minute, so a file of
        more than 300,000 rows waits for its quota between writes and can take
        several minutes, with a progress update each time it starts waiting.
        Retrying stops 10 minutes after the import's first write; a chunk
        refused after that is reported in failed_ranges.

        Args:
            local_path: Absolute path to the local .csv file.
            title: Title for the new spreadsheet.
            folder_id: Optional Google Drive folder ID where the spreadsheet should
                      be created. If not provided, uses the configured default
                      folder or creates in root.
            sheet_name: Name of the sheet the data is written to (default "Sheet1").

        Returns:
            spreadsheetId, title, web_link, and rows_written on full success. If the
            import fails before any row is written (setting up the sheet fails, or
            Sheets refuses every row write), the new spreadsheet is removed (deleted,
            or moved to the trash where the caller can't delete it) and only 'error'
            is returned; if removing it fails too, the error says so and
            spreadsheetId, title, and web_link name it. Rows are written in
            row-range chunks that run concurrently; otherwise, if one or more chunks
            fail, the spreadsheet may have some rows missing — not necessarily
            a clean prefix. In that case returns an 'error' summary plus
            spreadsheetId, title, web_link, rows_attempted, failed_ranges (start_row,
            end_row, error per failed chunk), and written_ranges (start_row, end_row
            per chunk that succeeded), so the missing rows can be retried precisely.

        Note:
            A service account has no My Drive storage, so it can only create files in a
            Shared Drive; a user identity (OAuth, or ADC with user credentials) can
            use either. ADC can also resolve to a service identity, which has the same Shared Drive-only limit.
            Check server://auth-status for your current auth method.
        """
        try:
            # Before any stat, so a refused path reads the same whether or not it exists.
            path = check_read(local_path)
        except LocalFileAccessError as e:
            return {"error": str(e)}
        if not path.exists():
            return {"error": f"File not found: {local_path}"}
        if not path.is_file():
            return {"error": f"Not a regular file: {local_path}"}
        suffix = Path(local_path).suffix
        if suffix.lower() != ".csv":
            return {"error": f"Unsupported file extension '{suffix}'. Use .csv"}

        def _read_csv() -> list[list[str]]:
            # utf-8-sig drops a leading byte-order mark (Excel's "CSV UTF-8" writes
            # one), which would otherwise stay in cell A1 (#1575).
            with path.open(newline="", encoding="utf-8-sig") as f:
                return list(csv.reader(f))

        try:
            rows = await asyncio.to_thread(_read_csv)
        except UnicodeDecodeError as e:
            # No byte offset: the decoder reports one within its current buffer,
            # not within the file.
            return {
                "error": f"File is not valid UTF-8: {local_path} ({e.reason}). "
                'Save it as UTF-8 (in Excel, "CSV UTF-8") and import again.'
            }
        except csv.Error as e:
            return {"error": f"Could not parse CSV {local_path}: {e}"}
        except OSError as e:
            return {"error": f"Could not read file {local_path}: {e.strerror or e}"}

        if not rows:
            return {"error": f"CSV file is empty: {local_path}"}

        width = max(len(row) for row in rows)
        # A file of blank lines has no columns, and a grid needs at least one.
        grid_columns = max(width, 1)
        # Before the padding, which a refused file shouldn't pay for.
        if limit_error := _csv_grid_limit_error(local_path, len(rows), grid_columns):
            return {"error": limit_error}
        rows = [row + [""] * (width - len(row)) for row in rows]

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        sheets_service = lc.sheets_service
        target_folder_id = folder_id or lc.folder_id

        file_body = {"name": title, "mimeType": "application/vnd.google-apps.spreadsheet"}
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        # Right after the create, not after the chunk writes: the spreadsheet is in
        # the folder from here on, however the rest of the import ends.
        invalidate = _FolderInvalidation(lc, target_folder_id)
        try:
            with invalidating(invalidate):
                spreadsheet = await execute_in_thread(
                    drive_service.files()
                    .create(
                        supportsAllDrives=True,
                        body=file_body,
                        # canDelete picks how a failed import removes it (#1574).
                        fields="id, name, parents, webViewLink, capabilities(canDelete)",
                    )
                    .execute,
                    drive_service,
                )
                invalidate.found(spreadsheet.get("parents"))
        except HttpError as e:
            if is_storage_quota_error(e):
                return {"error": _quota_error_text(drive_service)}
            raise

        spreadsheet_id = spreadsheet.get("id")
        target_folder_id = target_folder_id or (spreadsheet.get("parents", [None])[0])

        async def _failed_before_rows(error: str) -> dict[str, Any]:
            """The result of an import that failed before any row could have landed:
            the spreadsheet is removed, so nothing is left behind (#1574). Only if
            that fails too does the result name it."""
            try:
                action = await _discard_new_spreadsheet(drive_service, spreadsheet, invalidate)
            except Exception as e:
                logger.warning(
                    "import_csv_to_sheet: couldn't remove spreadsheet %s after a failed import",
                    spreadsheet_id,
                    exc_info=True,
                )
                return {
                    "error": (
                        f"{error} Removing the new, empty spreadsheet failed too ({e}); "
                        "it is left in place."
                    ),
                    "spreadsheetId": spreadsheet_id,
                    "title": spreadsheet.get("name", title),
                    "web_link": spreadsheet.get("webViewLink"),
                }
            removed = "deleted" if action == "deleted" else "moved to the trash"
            return {
                "error": f"{error} No rows were written, and the new spreadsheet was {removed}."
            }

        # The rename and resize have no rows to lose, so any failure here, a raw
        # HttpError included, removes the spreadsheet rather than leaving it empty.
        pause = _RateLimitPause()
        completed = [0]
        chunks = [
            (start, rows[start : start + _CSV_IMPORT_CHUNK_ROWS])
            for start in range(0, len(rows), _CSV_IMPORT_CHUNK_ROWS)
        ]
        total_chunks = len(chunks)

        async def _report_pause(seconds: float) -> None:
            # A pause can last a minute with no chunk finishing; a client that resets
            # its timeout on progress would otherwise hear nothing (PR #1589 QA round 1).
            await report_progress_safe(
                ctx,
                completed[0],
                total_chunks,
                f"Sheets write quota reached; waiting {seconds:.0f} s",
                "write quota pause",
            )

        try:
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
            # Exactly the data's size, never padded to the default 1000x26: the padding
            # counts against the workbook's cell limit, so a 1-column CSV over ~769k
            # rows was refused as 26 cells a row (#1573).
            requests.extend(_grid_resize_requests(sheet_id, grid, len(rows), grid_columns))

            # Every Sheets write, the rename and resize included, counts against the
            # same per-user write quota, so all of them go through one pause.
            if requests:
                with invalidating(lambda: lc.cache.mark_dirty(spreadsheet_id)):
                    await pause.send(
                        lambda: execute_in_thread(
                            sheets_service.spreadsheets()
                            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
                            .execute,
                            sheets_service,
                        ),
                        _report_pause,
                    )
        except Exception as e:
            return await _failed_before_rows(f"Setting up the sheet failed ({e}).")

        # Safe to parallelize: each chunk writes a disjoint row range of the same
        # sheet (A{start+1} onward, non-overlapping), so there's no read-modify-write
        # race between chunks. Unlike the old sequential loop — where a failure left a
        # clean truncated prefix — a concurrent failure can leave a hole mid-sheet (an
        # earlier chunk can still be in flight when a later one succeeds), so failures
        # are reported per-range rather than as a single opaque exception.
        quoted_sheet = _quote_sheet_name(sheet_name)

        async def _write_chunk(item: tuple[int, list[list]]) -> dict[str, Any]:
            start, chunk = item
            row_range = {"start_row": start + 1, "end_row": start + len(chunk)}
            try:
                await pause.send(
                    lambda: execute_in_thread(
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
                    ),
                    _report_pause,
                )
                result = {**row_range, "ok": True}
            except Exception as e:
                # rejected: a 4xx, so Sheets wrote none of this chunk's rows.
                result = {**row_range, "ok": False, "error": str(e), "rejected": is_rejection(e)}

            # Reported here, inside the per-item coroutine, so updates stream in as
            # each concurrent chunk write finishes rather than arriving in one burst
            # after asyncio.gather resolves — see #316/#319's original rationale,
            # extended to this tool by #355.
            completed[0] += 1
            row_label = f"rows {row_range['start_row']}-{row_range['end_row']}"
            await report_progress_safe(
                ctx,
                completed[0],
                total_chunks,
                f"{row_label}: {'ok' if result['ok'] else 'error'}",
                row_label,
            )
            return result

        def _chunk_fallback(item: tuple[int, list[list]], exc: BaseException) -> dict[str, Any]:
            start, chunk = item
            return {
                "start_row": start + 1,
                "end_row": start + len(chunk),
                "ok": False,
                "error": str(exc),
                "rejected": False,
            }

        with invalidating(lambda: lc.sheet_data_cache.mark_dirty(spreadsheet_id)):
            chunk_results: list[dict[str, Any]] = (
                await gather_with_fallback(chunks, _write_chunk, _chunk_fallback) if chunks else []
            )

        # Every chunk refused outright: no row landed, so nothing is worth keeping.
        # A chunk that failed any other way (a 5xx, a timeout) may have been written,
        # and then the partial-failure result below names the spreadsheet (#1574).
        if chunk_results and all(r.get("rejected") for r in chunk_results):
            first = chunk_results[0]["error"]
            count = len(chunk_results)
            refused = "The row write was" if count == 1 else f"All {count} row writes were"
            return await _failed_before_rows(f"{refused} refused ({first}).")

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

    @tool(
        annotations=ToolAnnotations(title="List Spreadsheets", readOnlyHint=True),
        groups=("sheets",),
    )
    @deprecated_tool(
        use=(
            "`search_files` (add `folder_id` for one folder) with "
            "`mime_type='application/vnd.google-apps.spreadsheet'` and this tool's default "
            "`max_results=100`"
        ),
        removed_in=_FINDER_REMOVED_IN,
    )
    async def list_spreadsheets(
        folder_id: str | None = None, max_results: int = 100, ctx: Context = None
    ) -> list[dict[str, str]]:
        """
        List spreadsheets in a Google Drive folder, newest modified first.
        If no folder is specified, uses the configured default folder; if that's
        also unset, searches across 'My Drive' AND every shared drive the
        authenticated account can access (corpora='allDrives') — not just
        'My Drive'.

        Returns at most max_results (clamped at 1000) from one page, and the
        list can be incomplete even when it's shorter than max_results.

        Args:
            folder_id: Optional Google Drive folder ID to search in.
                      If not provided, uses the configured default folder or searches
                      'My Drive' and every shared drive the account can access.
            max_results: Maximum number of results to return (default 100, max 1000).

        Returns:
            List of spreadsheets with their ID and title. Trashed files are excluded; to find one to restore, use
            get_file_metadata or restore_file with its file ID.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        target_folder_id = folder_id or ctx.request_context.lifespan_context.folder_id
        max_results = clamp_max_results(max_results, 1000)

        query = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        if target_folder_id:
            query += f" and '{_escape_drive_query_value(target_folder_id)}' in parents"
            logger.debug("Searching for spreadsheets in folder: %s", target_folder_id)
        else:
            logger.debug("Searching for spreadsheets across 'My Drive' and shared drives")

        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                pageSize=max_results,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                **_corpora_kwargs(target_folder_id),
                fields="files(id, name)",
                orderBy="modifiedTime desc",
            )
            .execute,
            drive_service,
        )

        return [{"id": f["id"], "title": f["name"]} for f in results.get("files", [])]

    @tool(annotations=ToolAnnotations(title="List Folders", readOnlyHint=True))
    @deprecated_tool(
        use=(
            "`search_files` (which never defaults to the configured folder) with "
            "`folder_id`, `mime_type='application/vnd.google-apps.folder'`, and this tool's "
            "`order_by='name'` and `max_results=100`"
        ),
        removed_in=_FINDER_REMOVED_IN,
    )
    async def list_folders(
        parent_folder_id: str | None = None, max_results: int = 100, ctx: Context = None
    ) -> list[dict[str, str]]:
        """
        List the folders in a Google Drive folder, sorted by name.
        If no parent is specified, uses the configured default folder
        (DRIVE_FOLDER_ID); if that is also unset, searches across 'My Drive' AND
        every shared drive the authenticated account can access
        (corpora='allDrives') — not just 'My Drive'.

        Args:
            parent_folder_id: Optional Google Drive folder ID to search within.
                             If not provided, uses the configured default folder
                             or searches 'My Drive' and every shared drive the
                             account can access.
            max_results: Maximum number of results to return (default 100, max 1000).

        Returns:
            List of folders with their ID, name, and parent information
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_folder_id = parent_folder_id or lc.folder_id
        max_results = clamp_max_results(max_results, 1000)

        query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
        if target_folder_id:
            query += f" and '{_escape_drive_query_value(target_folder_id)}' in parents"
            logger.debug("Searching for folders in parent folder: %s", target_folder_id)
        else:
            logger.debug("Searching for folders across 'My Drive' and shared drives")

        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                pageSize=max_results,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                **_corpora_kwargs(target_folder_id),
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
        max_results = clamp_max_results(max_results, 200)

        kwargs: dict[str, Any] = {
            "pageSize": min(max_results, 100),
            "fields": "nextPageToken, drives(id, name, createdTime, capabilities)",
        }
        if query:
            kwargs["q"] = query

        drives: list[dict[str, Any]] = []
        async with aclosing(
            iter_pages(
                lambda token: drive_service.drives().list(**kwargs, pageToken=token),
                drive_service,
                max_pages=_LIST_DRIVES_MAX_PAGES,
            )
        ) as pages:
            async for result in pages:
                for d in result.get("drives", []):
                    drives.append(
                        {
                            "id": d["id"],
                            "name": d["name"],
                            "created_time": d.get("createdTime"),
                            "capabilities": d.get("capabilities", {}),
                        }
                    )
                if len(drives) >= max_results:
                    break

        logger.debug("Found %d shared drives", len(drives))
        return drives[:max_results]

    @tool(annotations=ToolAnnotations(title="List Files", readOnlyHint=True), default=True)
    async def list_files(
        folder_id: str,
        mime_type: str | None = None,
        max_results: int = 100,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List files in a Google Drive folder, optionally filtered by MIME type,
        sorted by name.

        To search by name or content, across drives, or by date, use
        search_files; its description lists how the two differ.

        Returns at most max_results (clamped at 1000) from one page, and the
        list can be incomplete even when it's shorter than max_results.

        Args:
            folder_id: The Google Drive folder ID to list files from.
            mime_type: Optional MIME type filter. Common values:
                       'application/vnd.google-apps.document' (Google Docs)
                       'application/vnd.google-apps.spreadsheet' (Google Sheets)
                       'application/vnd.google-apps.folder' (folders)
            max_results: Maximum number of results to return (default 100, max 1000)

        Returns:
            List of files with their ID, name, MIME type, modified time, web link,
            starred status, and md5_checksum. md5_checksum is only present for
            binary files — Google Workspace files (Docs, Sheets, Slides, etc.) have
            no fixed byte content and the Drive API omits the field for them, so
            it's None for those. Compare it to a local file's md5 to detect real
            content drift instead of inferring change from modifiedTime alone;
            sync_folder(use_checksum=True) does that comparison itself (see its
            docstring for the cases where modifiedTime misleads).
            Results are cached; call refresh_cache(folder_id=folder_id) to invalidate,
            or refresh_cache() to clear all caches.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        folder_cache = lc.drive_folder_cache
        max_results = clamp_max_results(max_results, 1000)

        cached = folder_cache.get(folder_id, mime_type, max_results)
        if cached is not None:
            return cached

        query = f"'{_escape_drive_query_value(folder_id)}' in parents and trashed=false"
        if mime_type:
            safe_mime = _escape_drive_query_mime_type(mime_type)
            query += f" and mimeType='{safe_mime}'"

        try:
            epoch = folder_cache.snapshot_epoch()
            results = await execute_in_thread(
                drive_service.files()
                .list(
                    q=query,
                    pageSize=max_results,
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="nextPageToken, incompleteSearch, files(id, name, mimeType, modifiedTime, webViewLink, starred, md5Checksum)",
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
                    "starred": f.get("starred", False),
                    "md5_checksum": f.get("md5Checksum"),
                }
                for f in results.get("files", [])
            ]
            # Complete only with no nextPageToken and no incompleteSearch flag. A short
            # page alone doesn't prove it — Drive may return fewer than pageSize with
            # more left — and incompleteSearch marks a possibly partial result.
            folder_cache.store(
                folder_id,
                mime_type,
                files,
                max_results,
                epoch=epoch,
                exhaustive=not results.get("nextPageToken") and not results.get("incompleteSearch"),
            )
            return files
        except Exception as e:
            return [{"error": f"List files failed: {e!s}"}]

    @tool(
        annotations=ToolAnnotations(title="Search Files", readOnlyHint=True),
        default=True,
        groups=("sheets",),
    )
    async def search_files(
        query: str | None = None,
        mime_type: str | None = None,
        folder_id: str | None = None,
        max_results: int = 20,
        shared_with_me: bool = False,
        modified_within_days: int | None = None,
        order_by: Literal["modified", "name"] = "modified",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Find files and folders in Google Drive: by name or content, by type, in
        one folder, shared with you, or recently modified. Every filter is
        optional, and the ones given combine. With no folder_id and no
        shared_with_me, it searches 'My Drive' AND every shared drive the
        authenticated account can access (corpora='allDrives').

        Common calls:
            spreadsheets: mime_type='application/vnd.google-apps.spreadsheet'
            folders in a folder: mime_type='application/vnd.google-apps.folder',
                folder_id=...
            recently modified: modified_within_days=7
            shared with you: shared_with_me=True

        How this differs from list_files, which lists one folder's contents:
        - Sort: newest modified first by default (order_by='name' sorts by name
          when there's no query); list_files always sorts by name.
        - Fields: this returns created_time, owners and parent; list_files
          returns md5_checksum instead.
        - Cache: this always asks Drive; list_files is cached.
        - Folder: folder_id is optional here; list_files requires it. Neither
          falls back to the server's default folder (DRIVE_FOLDER_ID): with no
          folder_id this searches every drive.

        Args:
            query: Optional search string matched against file name and full
                   text. Omit it to filter by the other arguments alone.
            mime_type: Optional MIME type filter, e.g.
                       'application/vnd.google-apps.document',
                       'application/vnd.google-apps.spreadsheet',
                       'application/vnd.google-apps.folder',
                       'application/pdf'.
            folder_id: Optional folder whose direct children to search.
            max_results: Maximum results to return (default 20, max 1000).
            shared_with_me: Only files shared with the authenticated account by
                            someone else (with a service account, files shared with
                            its email address).
            modified_within_days: Only files modified within the last N days
                                  (1 to 36500).
            order_by: 'modified' (newest first, the default) or 'name'. 'name'
                      needs no query: Drive won't sort a search by content.

        Returns:
            {"files": [...], "exhaustive": bool}. Each file has id, name,
            mimeType, created_time, modified_time, owners, parent, web_link and
            starred. exhaustive is false when Drive has more matches than were
            returned or reports a partial search across drives; narrow the
            filters or raise max_results. Trashed files are excluded; to find one
            to restore, use get_file_metadata or restore_file with its file ID.
            {"error": ...} if the search fails.
        """
        if modified_within_days is not None and not (
            1 <= modified_within_days <= _MAX_MODIFIED_WITHIN_DAYS
        ):
            return {
                "error": (
                    f"modified_within_days must be from 1 to {_MAX_MODIFIED_WITHIN_DAYS}, "
                    f"not {modified_within_days}."
                )
            }
        if order_by not in _SEARCH_ORDER_BY:
            return {"error": f"order_by must be 'modified' or 'name', not {order_by!r}."}
        has_query = bool(query and query.strip())
        # Drive refuses every orderBy but modifiedTime desc on a fullText query
        # ("Sorting is not supported for queries with fullText terms", checked live).
        # Sorting the page here would be the newest N by name, not the first N.
        if has_query and order_by != "modified":
            return {
                "error": (
                    "order_by='name' can't be combined with query: Drive doesn't sort a "
                    "search by content. Omit query to sort by name, or use the default "
                    "order_by='modified'."
                )
            }

        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = clamp_max_results(max_results, 1000)

        parts = []
        if has_query:
            safe_query = _escape_drive_query_value(query)
            parts.append(f"(name contains '{safe_query}' or fullText contains '{safe_query}')")
        parts.append("trashed=false")
        if mime_type:
            safe_mime = _escape_drive_query_mime_type(mime_type)
            parts.append(f"mimeType='{safe_mime}'")
        if folder_id:
            parts.append(f"'{_escape_drive_query_value(folder_id)}' in parents")
        if shared_with_me:
            parts.append("sharedWithMe=true")
        if modified_within_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=modified_within_days)
            # Drive refuses a modifiedTime before the Unix epoch ("Invalid Value",
            # checked live), and a window reaching back that far holds every file,
            # so it adds no clause.
            if cutoff > _DRIVE_EARLIEST_TIME:
                parts.append(f"modifiedTime > '{cutoff.strftime('%Y-%m-%dT%H:%M:%S')}'")

        # sharedWithMe=true is its own scope, and the default "user" corpus already
        # holds what's shared directly with the caller, so it keeps that corpus.
        corpora = {} if shared_with_me else _corpora_kwargs(folder_id)

        try:
            results = await execute_in_thread(
                drive_service.files()
                .list(
                    q=" and ".join(parts),
                    pageSize=max_results,
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    **corpora,
                    fields=_SEARCH_FILE_FIELDS,
                    orderBy=_SEARCH_ORDER_BY[order_by],
                )
                .execute,
                drive_service,
            )
            # Inside the try, so a file the mapping can't read returns an error
            # dict rather than raising (PR #1558 QA round 1).
            files = [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "mimeType": f.get("mimeType"),
                    "created_time": f.get("createdTime"),
                    "modified_time": f.get("modifiedTime"),
                    "owners": [o.get("emailAddress") for o in f.get("owners", [])],
                    "parent": (f.get("parents") or [None])[0],
                    "web_link": f.get("webViewLink"),
                    "starred": f.get("starred", False),
                }
                for f in results.get("files", [])
            ]
        except Exception as e:
            return {"error": f"Search failed: {e!s}"}

        # A short page doesn't prove the list is complete: Drive can return fewer
        # than pageSize with more left, and incompleteSearch marks a partial
        # all-drives search (#1202).
        return {
            "files": files,
            "exhaustive": not results.get("nextPageToken") and not results.get("incompleteSearch"),
        }

    @tool(
        annotations=ToolAnnotations(
            title="Search Spreadsheets by Name or Content", readOnlyHint=True
        ),
        groups=("sheets",),
    )
    @deprecated_tool(
        use="`search_files` with `mime_type='application/vnd.google-apps.spreadsheet'`",
        removed_in=_FINDER_REMOVED_IN,
    )
    async def search_spreadsheets(
        query: str, max_results: int = 20, ctx: Context = None
    ) -> list[dict[str, Any]]:
        """
        Search for spreadsheets in Google Drive by name or content, across
        'My Drive' AND every shared drive the authenticated account can access
        (corpora='allDrives').

        Args:
            query: Search query string. Searches in file name and content.
                   Examples: "budget 2024", "sales report", "project tracker"
            max_results: Maximum number of results to return (default 20, max 100)

        Returns:
            List of matching spreadsheets with their ID, name, metadata, and
            starred status. Trashed files are excluded; to find one to restore, use
            get_file_metadata or restore_file with its file ID.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = clamp_max_results(max_results, 100)

        safe_query = _escape_drive_query_value(query)
        search_query = (
            f"mimeType='application/vnd.google-apps.spreadsheet' and trashed=false and "
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
                    **_corpora_kwargs(None),
                    fields="files(id, name, createdTime, modifiedTime, owners, webViewLink, starred)",
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
                    "starred": f.get("starred", False),
                }
                for f in results.get("files", [])
            ]
        except Exception as e:
            return [{"error": f"Search failed: {e!s}"}]

    @tool(annotations=ToolAnnotations(title="Get File Metadata", readOnlyHint=True), default=True)
    async def get_file_metadata(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Get metadata for any file or folder in Google Drive.

        Args:
            file_id: The Google Drive file or folder ID.

        Returns:
            id, name, mimeType, parents, createdTime, modifiedTime, size,
            owners, webViewLink, trashed status, starred status, and md5_checksum.
            md5_checksum (like size) is only present for binary files — Google
            Workspace files have no fixed byte content and the Drive API omits it
            for them. Compare it to a local file's md5 to detect real content
            drift instead of inferring change from modifiedTime alone;
            sync_folder(use_checksum=True) does that comparison itself (see its
            docstring for the cases where modifiedTime misleads). starred is the
            state star_file sets.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        f = await execute_in_thread(
            drive_service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, parents, createdTime, modifiedTime, size, owners, webViewLink, trashed, starred, md5Checksum",
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
            "starred": f.get("starred", False),
            "md5_checksum": f.get("md5Checksum"),
        }
        # Workspace files (Docs, Sheets, Slides, etc.) don't consume storage quota;
        # the Drive API returns quotaBytesUsed as "size", which is misleading.
        if not mime.startswith("application/vnd.google-apps.") and f.get("size") is not None:
            result["size"] = f["size"]
        return result

    @tool(annotations=ToolAnnotations(title="Create Folder", destructiveHint=True), default=True)
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

        invalidate = _FolderInvalidation(lc, target_parent_id)
        with invalidating(invalidate):
            folder = await execute_in_thread(
                drive_service.files()
                .create(supportsAllDrives=True, body=file_body, fields="id, name, parents")
                .execute,
                drive_service,
            )
            invalidate.found(folder.get("parents"))

        folder_id = folder.get("id")
        parents = folder.get("parents")
        logger.debug("Folder created with ID: %s", folder_id)

        return {
            "folderId": folder_id,
            "name": folder.get("name", name),
            "parent": parents[0] if parents else "root",
        }

    @tool(annotations=ToolAnnotations(title="Create Shortcut", destructiveHint=True))
    async def create_shortcut(
        target_file_id: str,
        folder_id: str | None = None,
        name: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a Drive shortcut pointing to an existing file.

        Args:
            target_file_id: The ID of the file the shortcut should point to.
            folder_id: Destination folder ID for the shortcut. If not provided, uses
                      the configured default folder or creates in root.
            name: Name for the shortcut. Defaults to the target file's own name.

        Returns:
            shortcutId, name, parent, targetId, and targetMimeType of the new shortcut.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_parent_id = folder_id or lc.folder_id

        shortcut_name = name
        if not shortcut_name:
            target = await execute_in_thread(
                drive_service.files()
                .get(fileId=target_file_id, fields="name", supportsAllDrives=True)
                .execute,
                drive_service,
            )
            shortcut_name = target["name"]

        file_body: dict[str, Any] = {
            "name": shortcut_name,
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": target_file_id},
        }
        if target_parent_id:
            file_body["parents"] = [target_parent_id]

        invalidate = _FolderInvalidation(lc, target_parent_id)
        with invalidating(invalidate):
            shortcut = await execute_in_thread(
                drive_service.files()
                .create(
                    supportsAllDrives=True,
                    body=file_body,
                    fields="id, name, parents, shortcutDetails",
                )
                .execute,
                drive_service,
            )
            invalidate.found(shortcut.get("parents"))

        parents = shortcut.get("parents")
        logger.debug(
            "Shortcut created with ID: %s -> target %s", shortcut.get("id"), target_file_id
        )

        details = shortcut.get("shortcutDetails", {})
        return {
            "shortcutId": shortcut.get("id"),
            "name": shortcut.get("name", shortcut_name),
            "parent": parents[0] if parents else "root",
            "targetId": details.get("targetId", target_file_id),
            "targetMimeType": details.get("targetMimeType"),
        }

    @tool(annotations=ToolAnnotations(title="Copy File", destructiveHint=True), default=True)
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
            A service account has no My Drive storage, so it can only copy files into a
            Shared Drive; a user identity (OAuth, or ADC with user credentials) can
            use either. ADC can also resolve to a service identity, which has the same Shared Drive-only limit.
            Check server://auth-status for your current auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        body: dict[str, Any] = {}
        if new_name:
            body["name"] = new_name
        if folder_id:
            body["parents"] = [folder_id]

        invalidate = _FolderInvalidation(lc, folder_id)
        try:
            with invalidating(invalidate):
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
                invalidate.found(copied.get("parents"))
        except HttpError as e:
            if is_storage_quota_error(e):
                return {"error": _quota_error_text(drive_service)}
            raise

        parents = copied.get("parents", [])
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

        with invalidating(
            _FolderInvalidation(lc, destination_folder_id, *existing.get("parents", []))
        ):
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

        parents = updated.get("parents", [])
        return {
            "fileId": updated.get("id"),
            "name": updated.get("name"),
            "mimeType": updated.get("mimeType"),
            "parent": parents[0] if parents else "root",
        }

    @tool(annotations=ToolAnnotations(title="Rename File", destructiveHint=True), default=True)
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

        invalidate = _FolderInvalidation(lc)
        with invalidating(invalidate):
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
            invalidate.found(updated.get("parents"))

        parents = updated.get("parents", [])
        logger.debug("Renamed file %s to %s", file_id, new_name)
        return {
            "fileId": updated.get("id"),
            "name": updated.get("name"),
            "parent": parents[0] if parents else "root",
        }

    async def _set_starred(lc, file_id: str, starred: bool) -> dict[str, Any]:
        drive_service = lc.drive_service
        invalidate = _FolderInvalidation(lc)
        with invalidating(invalidate):
            updated = await execute_in_thread(
                drive_service.files()
                .update(
                    fileId=file_id,
                    body={"starred": starred},
                    supportsAllDrives=True,
                    fields="id, name, starred, parents",
                )
                .execute,
                drive_service,
            )
            invalidate.found(updated.get("parents"))
        logger.debug("%s file %s", "Starred" if starred else "Unstarred", file_id)
        return {
            "fileId": updated.get("id"),
            "name": updated.get("name"),
            "starred": updated.get("starred", False),
        }

    @tool(annotations=ToolAnnotations(title="Star File"))
    async def star_file(file_id: str, starred: bool = True, ctx: Context = None) -> dict[str, Any]:
        """
        Star or unstar a file or folder in Google Drive.

        Args:
            file_id: The ID of the file or folder.
            starred: True (the default) to star it, False to remove its star.

        Returns:
            fileId, name, and the resulting starred state.
        """
        return await _set_starred(ctx.request_context.lifespan_context, file_id, starred)

    @tool(annotations=ToolAnnotations(title="Unstar File"))
    @deprecated_tool(use="`star_file` with `starred=False`", removed_in=_FINDER_REMOVED_IN)
    async def unstar_file(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Remove a file or folder's starred marker in Google Drive.

        Args:
            file_id: The ID of the file or folder to unstar.

        Returns:
            fileId, name, and the resulting starred state.
        """
        return await _set_starred(ctx.request_context.lifespan_context, file_id, False)

    @tool(annotations=ToolAnnotations(title="List Shared With Me", readOnlyHint=True))
    @deprecated_tool(
        use=(
            "`search_files` (whose files carry `mimeType`, not `mime_type`) with "
            "`shared_with_me=True` and this tool's default `max_results=50`"
        ),
        removed_in=_FINDER_REMOVED_IN,
    )
    async def list_shared_with_me(
        mime_type: str | None = None,
        max_results: int = 50,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List files explicitly shared with the authenticated user, including
        shared drive files shared with them directly.

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
        max_results = clamp_max_results(max_results, 200)

        parts = ["sharedWithMe=true", "trashed=false"]
        if mime_type:
            safe_mime = _escape_drive_query_mime_type(mime_type)
            parts.append(f"mimeType='{safe_mime}'")

        return await _list_drive_files(
            drive_service, " and ".join(parts), max_results, "List shared with me"
        )

    @tool(annotations=ToolAnnotations(title="List Recent Files", readOnlyHint=True))
    @deprecated_tool(
        use=(
            "`search_files` (newest first by default; its files carry `mimeType`, not "
            "`mime_type`) with `modified_within_days`"
        ),
        removed_in=_FINDER_REMOVED_IN,
    )
    async def list_recent_files(
        max_results: int = 20,
        days: int | None = None,
        mime_type: str | None = None,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List recently modified files in Drive, newest first, across 'My Drive'
        AND every shared drive the authenticated account can access
        (corpora='allDrives').

        Args:
            max_results: Maximum number of files to return (default 20, max 100).
            days: If provided, only return files modified within the last N days.
            mime_type: Optional MIME type filter.

        Returns:
            List of files with id, name, mime_type, modified_time, owners, and web_link,
            ordered by modification time descending.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        max_results = clamp_max_results(max_results, 100)

        parts = ["trashed=false"]
        if days is not None and days > 0:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
            parts.append(f"modifiedTime > '{cutoff}'")
        if mime_type:
            safe_mime = _escape_drive_query_mime_type(mime_type)
            parts.append(f"mimeType='{safe_mime}'")

        return await _list_drive_files(
            drive_service,
            " and ".join(parts),
            max_results,
            "List recent files",
            extra_kwargs=_corpora_kwargs(None),
        )

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
                       Raises ValueError, without deleting anything, if the
                       caller can't permanently delete the file (e.g. a
                       Content manager on a Shared Drive, who can only trash).

        Returns:
            Confirmation with fileId and action taken ('trashed' or 'deleted').
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        # Fetch parents before deletion so we can invalidate the cache, plus
        # capabilities: on a Shared Drive a Content manager can trash but not
        # permanently delete, and Drive reports that missing permission as a
        # misleading 404 "File not found" (#876).
        existing = await execute_in_thread(
            drive_service.files()
            .get(
                fileId=file_id,
                fields="parents,driveId,capabilities(canDelete,canTrash)",
                supportsAllDrives=True,
            )
            .execute,
            drive_service,
        )
        capabilities = existing.get("capabilities", {})
        if permanent and capabilities.get("canDelete") is False:
            # canDelete is also false for a non-owner editor of a My Drive
            # file, so only mention Shared Drive roles when the file is on one.
            shared_drive_note = (
                " On a Shared Drive this usually requires the Manager role."
                if existing.get("driveId")
                else ""
            )
            trash_hint = (
                " Use permanent=False to move it to the trash instead."
                if capabilities.get("canTrash")
                else ""
            )
            raise ValueError(
                f"Cannot permanently delete file {file_id}: the authenticated identity "
                f"lacks permanent-delete permission on it.{shared_drive_note}{trash_hint}"
            )
        with invalidating(_FolderInvalidation(lc, *existing.get("parents", []))):
            if permanent:
                await execute_in_thread(
                    drive_service.files().delete(fileId=file_id, supportsAllDrives=True).execute,
                    drive_service,
                )
            else:
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
        if permanent:
            logger.debug("Permanently deleted file %s", file_id)
            return {"fileId": file_id, "action": "deleted"}
        logger.debug("Trashed file %s", file_id)
        return {"fileId": file_id, "action": "trashed"}

    @tool(annotations=ToolAnnotations(title="Restore File", destructiveHint=True))
    async def restore_file(file_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Restore a trashed file or folder back to its original location — undoes
        `delete_file` when it was called without `permanent=True`. Raises an
        API error (does not silently no-op) if the file was permanently
        deleted or otherwise no longer exists — permanent deletion can't be
        recovered from.

        Args:
            file_id: The ID of the trashed file or folder to restore.

        Returns:
            Confirmation with fileId and action taken ('restored').
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        invalidate = _FolderInvalidation(lc)
        with invalidating(invalidate):
            result = await execute_in_thread(
                drive_service.files()
                .update(
                    fileId=file_id,
                    body={"trashed": False},
                    supportsAllDrives=True,
                    fields="id,parents",
                )
                .execute,
                drive_service,
            )
            invalidate.found(result.get("parents"))

        logger.debug("Restored file %s", file_id)
        return {"fileId": file_id, "action": "restored"}

    @tool(annotations=ToolAnnotations(title="Empty Trash", destructiveHint=True))
    async def empty_trash(drive_id: str | None = None, ctx: Context = None) -> dict[str, Any]:
        """
        Permanently delete every trashed file in a single trash. This cannot
        be undone — unlike `delete_file`'s default (recoverable) trash
        behavior, there is no restoring a file after this.

        Args:
            drive_id: If omitted (default), empties the caller's own My Drive
                trash only. If set to a Shared Drive's ID (see `list_drives`),
                empties that Shared Drive's trash instead. A single call only
                ever targets one trash — to empty several Shared Drives' trash,
                call this once per `drive_id`.

        Returns:
            Confirmation that the trash was emptied, echoing which drive
            (drive_id, or None for My Drive) was targeted.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        kwargs: dict[str, Any] = {}
        if drive_id:
            kwargs["driveId"] = drive_id

        await execute_in_thread(
            drive_service.files().emptyTrash(**kwargs).execute,
            drive_service,
        )
        logger.debug("Emptied trash (drive_id=%s)", drive_id)
        return {"action": "trash_emptied", "drive_id": drive_id}
