import asyncio
import base64
import contextlib
import errno
import hashlib
import io
import logging
import mimetypes
import os
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal

import markdown as _md
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload, MediaIoBaseDownload
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread, thread_http
from ..pagination import iter_pages
from ..response_limits import enforce_response_size_cap, write_capped_result_to_disk
from . import _SA_QUOTA_ERROR, _escape_drive_query_mime_type

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

# Every download writes to a sibling temp file with this name and renames it
# onto the destination only once complete (_write_atomically, #844). A temp
# file only outlives its download when the process is killed mid-write;
# sync_folder and upload_local_folder skip one so a leftover partial is never
# uploaded. No part of the destination's name is embedded, so the temp name
# can't exceed the filesystem's name-length limit.
_PARTIAL_DOWNLOAD_PREFIX = ".gee-sweet-partial-"
_PARTIAL_DOWNLOAD_RE = re.compile(r"\.gee-sweet-partial-[0-9a-f]{16}")

_SYNC_MTIME_TOLERANCE = 5  # seconds — absorbs clock skew and upload-time drift

# use_checksum hashes every both-sides pair with a Drive md5Checksum (#716), so
# a steady-state folder reads every file back before any transfer starts. The
# reads run concurrently, capped here so a large folder doesn't queue
# hundreds of whole-file reads against the same disk at once (PR #841 QA).
_SYNC_HASH_CONCURRENCY = 8

# Custom Drive file property set on a Google Doc created via convert_markdown's
# native import conversion, recording the exact local filename it was created
# from. Matching converted-md Docs back to their local file by this property
# (rather than by current Drive display name + mimeType alone) means an
# unrelated pre-existing Doc a human happened to name "notes.md" never matches
# (it lacks the property), and a later Drive-side rename/case-change of the Doc
# doesn't desync the match either, since the stored source name never changes
# (#414 QA review, findings #2 and #7). Still stamped whenever the raw name fits
# Drive's per-property byte cap, and still honored on read, but no longer the
# only way sync_folder recognizes one: a name too long for this key is
# recognized through _CONVERT_SOURCE_PROP instead (#805) — see
# _converted_md_source_name.
_CONVERT_MARKDOWN_SOURCE_PROP = "geeSweetConvertMarkdownSource"

# Generalization of _CONVERT_MARKDOWN_SOURCE_PROP to every native import
# conversion _upload_local_file performs (CSV/XLSX/DOCX/MD/HTML/PPTX), recording
# the exact source filename the converted file was created from. Exists so
# upload_local_folder's skip_if_exists check can tell a converted file this
# tool itself created (whose display name Drive may have extension-stripped,
# e.g. "report.csv" -> "report") apart from an unrelated file that merely
# shares the stem and target mimeType (#769). A separate key rather than
# reusing _CONVERT_MARKDOWN_SOURCE_PROP for every type: sync_folder's
# _is_converted_md_entry treats that marker on any Doc as "converted from a
# local .md", which a .docx/.html-converted Doc is not. sync_folder does read
# this key too (#805), but only accepts it on a Doc whose recorded source is
# itself a .md name.
_CONVERT_SOURCE_PROP = "geeSweetConvertSource"

# sync_folder's change detection for a convert_markdown Doc, which can't use
# Drive's modifiedTime: the Docs backend updates it asynchronously, minutes
# behind, so it both overwrites the post-create restamp and hides real Drive
# edits (#814; see docs/decisions/decision-converted-doc-change-detection.md).
# Instead, every converted-.md upload stamps the local file's exact mtime (the
# local side's reference) and the upload time, a re-upload also stamps the
# Doc's latest revision ID from just before it (the baseline), and the first
# sync after an upload records the import's own revision ID. A Drive edit then
# shows as a newer latest revision. A Doc without
# _CONVERTED_MD_SOURCE_MTIME_PROP (converted before #814) stays on the
# modifiedTime comparison until its next re-upload.
_CONVERTED_MD_SOURCE_MTIME_PROP = "geeSweetSourceMtime"
_CONVERTED_MD_UPLOADED_AT_PROP = "geeSweetUploadedAt"
_CONVERTED_MD_BASELINE_REV_PROP = "geeSweetBaselineRevision"
_CONVERTED_MD_IMPORT_REV_PROP = "geeSweetImportRevision"

# The source-mtime stamp and the local mtime it's compared with both come from
# a stat() on this machine, at microsecond precision, so there's no clock skew
# to absorb. _SYNC_MTIME_TOLERANCE's 5s would hide a local save made within 5s
# of the upload (PR #854 QA round 1). This only absorbs float rounding.
_CONVERTED_MD_STAMP_TOLERANCE = 0.001

# An import's revision appears seconds after the upload. A candidate import
# revision timestamped later than this after the upload isn't the import: Drive
# merged the import into a later edit when it compacted the history, so the Doc
# was edited (PR #854 QA round 1). Generous, to absorb conversion lag and the
# skew between this machine's clock (the upload time) and Drive's.
_CONVERTED_MD_IMPORT_WINDOW = 600

# Backward skew allowed when a pruned baseline forces finding the import by
# time instead: the first revision no earlier than this before the upload.
_CONVERTED_MD_CLOCK_SKEW = 60

# One revisions.list per converted Doc present on both sides, run concurrently
# after the plan loop, capped the same way as use_checksum's hash reads.
_SYNC_REVISION_CONCURRENCY = 8

# Google Workspace Doc mimeType, requested via Drive's native import-conversion
# trick (upload with the source format's mimeType while setting the destination
# file's own mimeType to this target) from two independent places: _CONVERT_MIME
# below (local-file uploads, dispatched by extension, also covers Sheets/Slides
# targets) and upload_file's convert_to_doc param (raw text/markdown/html content,
# always targets a Doc since it has no extension to dispatch on). Shared here as
# the single source of truth for the literal so the two can't drift apart on it —
# see upload_file's own convert_to_doc branch for the other call site (#412).
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"

# extension -> (source mimeType to upload as, target Google Workspace mimeType to
# request via Drive's native import conversion). Distinct from _EXPORT_MIME above,
# which maps the other direction (Google type -> downloadable export format).
_CONVERT_MIME: dict[str, tuple[str, str]] = {
    ".csv": ("text/csv", "application/vnd.google-apps.spreadsheet"),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.spreadsheet",
    ),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _GOOGLE_DOC_MIME,
    ),
    ".md": ("text/markdown", _GOOGLE_DOC_MIME),
    ".html": ("text/html", _GOOGLE_DOC_MIME),
    ".htm": ("text/html", _GOOGLE_DOC_MIME),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.google-apps.presentation",
    ),
}

# Shared core clause cited by every message that reports a convert_markdown Doc
# as un-syncable Drive -> local: Drive's native import conversion (local .md ->
# Doc) has no reverse direction. Previously worded independently at three call
# sites (drive-only plan conflict, drive-newer plan conflict, download-execution
# guard), which meant a future wording change was three literals to find and
# edit by hand instead of one (#424, folded from #421 finding #2).
_NO_REVERSE_CONVERSION_CLAUSE = "convert_markdown Docs have no reverse conversion"


def _converted_md_source_name(f: dict) -> str | None:
    """The local .md filename a convert_markdown Doc was converted from, or None
    when Drive file resource `f` isn't one.

    Read from _CONVERT_MARKDOWN_SOURCE_PROP when present: every Doc converted
    before #805 carries only that key, and must keep matching after upgrade.
    Otherwise from _CONVERT_SOURCE_PROP, accepted only for a .md source so a
    .docx/.html-converted Doc never counts. That marker holds either the raw
    name or, for a name too long for Drive's per-property byte cap, a digest of
    it (_convert_source_marker). A digest can't be read back, so the source
    name is then taken from the Doc's own display name, which keeps its ".md"
    suffix, and accepted only if it re-encodes to the same digest (#805). The
    raw form survives a Drive-side rename; the digest form doesn't — a renamed
    over-long Doc stops matching and reads as an unrelated Doc, the same as a
    human-made one."""
    if f["mimeType"] != _GOOGLE_DOC_MIME:
        return None
    props = f.get("properties") or {}
    legacy = props.get(_CONVERT_MARKDOWN_SOURCE_PROP)
    if legacy is not None:
        return legacy
    generic = props.get(_CONVERT_SOURCE_PROP)
    if generic is None:
        return None
    # The raw form first, then the display name for a digest. A "sha256:..."
    # digest is itself short enough to pass as raw, so "does it re-encode to
    # itself" can't tell the two forms apart; the .md check on each candidate
    # does, since a digest never ends in ".md".
    for source in (generic, f["name"]):
        if Path(source).suffix.lower() == ".md" and _convert_source_marker(source) == generic:
            return source
    return None


def _is_converted_md_entry(f: dict) -> bool:
    """Whether a Drive file resource `f` (as returned by _list_drive_children,
    carrying mimeType/properties) represents a convert_markdown Doc — a Google
    Doc created via native import conversion from a local .md file, identified
    by a conversion marker naming a .md source (see _converted_md_source_name),
    not by mimeType alone (an ordinary human-created Doc has the identical
    mimeType).

    Computed on demand from the resource's own fields rather than cached as a
    synthetic "_is_converted_md" key spread into drive_map's entries — keeps
    drive_map a plain passthrough of Drive's own file resource shape instead of
    mixing in internal bookkeeping (#421 finding #6), and gives every site that
    needs this classification (the drive_map build loop's grouping, both plan
    branches, the upload-execution reimport check, the download-execution
    guard) exactly one place to agree with when this classification's rules
    change, instead of 5 independently-written checks — a duplication that had
    already caused a missed site once (#414 QA review round 3, finding #1) and
    was flagged again on round-3 review as still fragile (#424)."""
    return _converted_md_source_name(f) is not None


def _is_workspace_entry(f: dict) -> bool:
    """Whether a Drive file resource `f` is a native Google Workspace file
    (Doc/Sheet/Slide/etc., mimeType starting "application/vnd.google-apps.").

    Computed on demand rather than cached onto drive_map, for the same reason
    _is_converted_md_entry is (#421 finding #6, #424) — _sync_level's own
    drive_map-build loop and its two nested execution closures (_run_one's
    both-sides and download branches), plus export_file/download_file's own
    fetched-metadata dicts and download_folder's own files().list() results,
    each independently recomputed this same `.startswith(...)` check inline
    (#474, extended to the latter three during QA on PR #765); centralizing
    it here gives all six exactly one place to agree with, without
    reintroducing a synthetic key on drive_map's entries. Works against any
    dict carrying Drive's own "mimeType" field, not just a drive_map entry."""
    return f["mimeType"].startswith("application/vnd.google-apps.")


def _is_quota_error(exc: Exception) -> bool:
    """True for Drive's storageQuotaExceeded HttpError (403) — the "this identity
    has no personal storage" failure a service account hits on a non-Shared-Drive
    target, which the shared _SA_QUOTA_ERROR text explains."""
    return (
        isinstance(exc, HttpError)
        and exc.resp.status == 403
        and b"storageQuotaExceeded" in (exc.content or b"")
    )


def _quota_error_detail(exc: Exception) -> str:
    """Render an exception as a user-facing 'error' string: the friendly
    _SA_QUOTA_ERROR text for a storageQuotaExceeded HttpError, else str(exc).
    Keeps every quota-error site in this file rendering the same way — including
    catch-all `except Exception` handlers where a bare `except HttpError` quota
    check would otherwise be skipped and leak the raw error blob (#670)."""
    return _SA_QUOTA_ERROR if _is_quota_error(exc) else str(exc)


def _restamp_failure_result(file_id: str, exc: Exception) -> dict[str, Any]:
    """Shared result for the narrow case where create() succeeded but the
    follow-up metadata-only modifiedTime restamp (convert / convert_markdown
    uploads only) then failed. The created Drive file is real — pairing the
    error with its fileId keeps that orphan findable instead of losing its ID
    entirely (#420). A storageQuotaExceeded HttpError is rendered with the
    shared _SA_QUOTA_ERROR text, matching every other quota-error site in this
    file — the original per-site restamp except caught only bare Exception and
    would have leaked a raw str(e) here (#650). Callers layer their own result
    shape on top (e.g. _sync_level._run_one's kind/name keys)."""
    detail = _quota_error_detail(exc)
    return {
        "error": (
            f"created Drive file {file_id!r} but failed to restamp its modifiedTime: {detail}"
        ),
        "fileId": file_id,
    }


def _validate_local_destination(local_path: str) -> tuple[Path, bool]:
    """Reject a non-directory path component before making any Drive request.

    A trailing separator means the destination itself must be a directory;
    otherwise the destination is a file and only its parents must be directories.
    Existing regular files at an explicit file destination may still be replaced.
    """
    dest = Path(local_path)
    wants_dir = local_path.endswith(("/", os.sep))
    start = dest if wants_dir else dest.parent
    for path in (start, *start.parents):
        if path.exists() or path.is_symlink():
            if not path.is_dir():
                raise ValueError(
                    f"local_path {local_path!r} has a non-directory path component at {str(path)!r}"
                )
            break
    return dest, wants_dir


def _unsafe_name_reason(name: str) -> str | None:
    """Why `name` can't be used as one local path component, or None if it can.

    Drive names are arbitrary text (Drive accepts '/' and '..' unchanged), so a
    name joined onto a local directory unchecked can resolve outside it. Only a
    single, ordinary component is allowed. '\\' is refused on every platform,
    not just Windows, where it's a separator, so the same names are refused as
    separators whichever OS runs the server.
    """
    if not name:
        return "name is empty"
    if "\x00" in name:
        return "name contains a NUL character"
    if "/" in name or "\\" in name:
        return "name contains a path separator"
    if name in (".", ".."):
        return f"name is the special path segment {name!r}"
    # Catches a Windows drive-qualified name such as 'C:x' (relative but
    # anchored to another drive); the separator check above already covers
    # every POSIX absolute path.
    if Path(name).is_absolute() or Path(name).anchor:
        return "name is an absolute path"
    return None


def _safe_local_dest(base: Path, name: str, resolved_base: Path | None = None) -> Path:
    """`base / name`, after checking that the result stays inside `base`.

    The one place every Drive-supplied name is joined onto a local directory
    (download_file, download_folder, _sync_level's files and subfolders).
    Raises ValueError for a name _unsafe_name_reason refuses, or, as a
    backstop, when the joined path doesn't stay under the resolved `base`. The
    error's text is the reason alone, so each caller can phrase it around the
    name its user sees. A caller joining many names onto one directory passes
    `resolved_base` (`base.resolve()`, computed once) to skip a filesystem
    call per name. The final component is deliberately not resolved: a
    symlink the user put inside `base` keeps working as it did, and a Drive
    name can't create one.
    """
    reason = _unsafe_name_reason(name)
    if reason is None:
        if resolved_base is None:
            resolved_base = base.resolve()
        candidate = Path(os.path.normpath(resolved_base / name))
        if candidate == resolved_base or not candidate.is_relative_to(resolved_base):
            reason = "name resolves outside the target directory"
    if reason is not None:
        raise ValueError(reason)
    return base / name


def _unsafe_name_step(
    name: str,
    reason: str,
    in_drive: bool,
    in_local: bool,
    direction: str,
    drive_count: int = 0,
) -> "_SyncStep":
    """sync_folder's plan step for a name _safe_local_dest refused, shared by
    the file plan and the subfolder pass so both report it the same way.

    A name on one side only that this direction never acts on stays the plain
    skip it always was. Anything else is 'unsafe_name'. `drive_count` is how
    many Drive entries carry the name: several can, and all are reported in
    this one step, as a collision is."""
    if in_drive and not in_local and direction == "upload":
        return _SyncStep(name=name, action="skip", reason="drive only, upload direction")
    if in_local and not in_drive and direction == "download":
        return _SyncStep(name=name, action="skip", reason="local only, download direction")
    if drive_count > 1:
        reason = f"{reason} ({drive_count} Drive entries have this name)"
    return _SyncStep(name=name, action="unsafe_name", reason=f"{reason}; not synced")


def _local_mtime_dt(path: Path, st: os.stat_result | None = None) -> datetime:
    """A local file's mtime as an aware UTC datetime. The one place that reads
    it, so sync_folder's mtime comparison and every modifiedTime value this
    module stamps can't drift apart (#435). Pass `st` to reuse a stat the
    caller already made (and guarded) instead of statting again."""
    if st is None:
        st = path.stat()
    return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)


def _drive_time_str(dt: datetime) -> str:
    """`dt` in the RFC 3339 form Drive's modifiedTime field takes, truncated to
    whole seconds."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _is_partial_download(name: str) -> bool:
    """Whether `name` is a temp file _write_atomically left behind."""
    return _PARTIAL_DOWNLOAD_RE.fullmatch(name) is not None


def _write_atomically(
    dest: Path, write: Callable[[BinaryIO], object], mtime: float | None = None
) -> None:
    """Run `write` against a sibling temp file, then rename it onto `dest`.

    `dest` only ever holds its previous content or the complete new content.
    Writing straight into `dest` left a truncated file behind when a download
    failed partway, with a current mtime that made sync_folder treat it as the
    newer copy and upload it over the intact Drive file (#844). `mtime`, when
    given, is stamped on the temp file before the rename, so a failed restamp
    also leaves `dest` untouched. The temp file is removed on any failure.

    A symlink at `dest` is written through, as the old `open("wb")` did: the
    temp file goes next to the link's target and replaces the target. The new
    file gets the mode a fresh `open("wb")` would (0o666 less the umask), or the
    replaced file's permission bits when there was one (never its
    setuid/setgid/sticky bits, which an in-place write would have cleared). A
    hard link to the old file keeps the old content, since the rename swaps in
    a new inode.

    A rename needs write permission on the directory, not the file, so an
    existing file this process couldn't open for writing is refused up front
    with the same PermissionError `open("wb")` raised; otherwise a file the
    user made read-only would be silently replaced (PR #884 QA round 1).
    """
    target = Path(os.path.realpath(dest)) if dest.is_symlink() else dest
    if target.exists() and not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(target))
    tmp = target.with_name(_PARTIAL_DOWNLOAD_PREFIX + secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as fh:
            write(fh)
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp, target.stat().st_mode & 0o777)
        if mtime is not None:
            os.utime(tmp, (mtime, mtime))
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _local_mtime_str(path: Path) -> str:
    """_local_mtime_dt in the RFC 3339 form Drive's modifiedTime field takes."""
    return _drive_time_str(_local_mtime_dt(path))


def _parse_time(value: str | None) -> datetime | None:
    """An RFC 3339 timestamp (Drive's, or one this module stamped) as an aware
    datetime, or None when absent or unreadable."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _converted_md_upload_properties(
    lmtime: datetime, *, reupload: bool = False, baseline_rev: str | None = None
) -> dict[str, str | None]:
    """The #814 change-detection properties a converted-.md upload stamps.

    The source mtime keeps full microsecond precision, so the next sync can
    compare it exactly (_CONVERTED_MD_STAMP_TOLERANCE). The upload time lets
    the next sync recognize the import's revision by its timestamp
    (_CONVERTED_MD_IMPORT_WINDOW). A re-upload also stamps the Doc's latest
    revision from before the update() as the baseline and clears the previous
    import revision. A new Doc needs neither: its first revision is the import.
    Every caller stamps through here, so they can't disagree on the set."""
    props: dict[str, str | None] = {
        _CONVERTED_MD_SOURCE_MTIME_PROP: lmtime.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        _CONVERTED_MD_UPLOADED_AT_PROP: _drive_time_str(datetime.now(timezone.utc)),
    }
    if reupload:
        props[_CONVERTED_MD_BASELINE_REV_PROP] = baseline_rev
        props[_CONVERTED_MD_IMPORT_REV_PROP] = None
    return props


async def _restamp_modified_time(
    drive_service: Any, file_id: str, lmtime_str: str
) -> dict[str, Any] | None:
    """Re-apply modifiedTime to a file that create() just produced via Drive's
    native import conversion. Under conversion, create() doesn't keep the
    modifiedTime requested in its body — the new file carries Drive's own
    "now" instead — while a metadata-only update() issued afterward doesn't
    trigger reconversion. No single call can do both, so every conversion costs
    this second call (#421 finding #5).

    The restamp doesn't reliably stick, though. For a Google Doc, Drive updates
    modifiedTime from the Docs backend asynchronously, minutes behind, and that
    late update can land after this one and overwrite it (#814; it held 40s+ in
    PR #817 QA round 1, but drifted up to 29s in TC-D266). So sync_folder no
    longer relies on it for a convert_markdown Doc: that Doc's change detection
    runs off properties and revision history instead (see
    _CONVERTED_MD_SOURCE_MTIME_PROP). For such a Doc the restamp is cosmetic,
    keeping Drive's displayed "last modified" near the source mtime.

    Needed for every conversion type, not just .md → Doc: sync_folder matches
    a converted Sheet/Slides/Doc back to its local source through
    export_format's suffix scheme and compares mtimes, and Drive strips ".csv"
    from a converted Sheet's display name, so export_format='csv' maps it
    straight back to the local file. An unrestamped CSV → Sheet would read as
    "Drive newer" on the next sync exactly the way an unrestamped .md → Doc
    would (#435 declined gating this on .md for that reason). Those types still
    compare modifiedTime and so can still hit the race; see #818.

    Returns None on success, or _restamp_failure_result's {"error", "fileId"}
    on failure — create() already succeeded, so the file is real and its ID
    must not be lost (#420). Shared by _upload_local_file and
    _sync_level._run_one so a future change to this workaround lands in both
    (#435)."""
    try:
        await execute_in_thread(
            drive_service.files()
            .update(
                fileId=file_id,
                body={"modifiedTime": lmtime_str},
                supportsAllDrives=True,
                fields="id",
            )
            .execute,
            drive_service,
        )
    except Exception as e:
        return _restamp_failure_result(file_id, e)
    return None


def _format_bytes_note(so_far: int, total: int | None) -> str:
    """Progress-message byte-count suffix shared by download_folder's
    _download_one and _sync_level's _run_one_with_progress (#352 QA review,
    finding #3 — these were previously duplicated with different shapes despite
    an inline comment claiming they shared "the same principle"). `total` is
    the accurate upfront byte total when every candidate's size is known ahead
    of time (download_folder only — sync_folder never has one, recursive
    descent discovers files level by level), or None otherwise. Checked via
    `is not None`, not truthiness — a genuine all-zero-byte total (e.g. a
    batch of only empty files) must still render as 'N/0 bytes' rather than
    silently falling back to the less precise running-count form (finding #2:
    the original per-site checks each truthy-tested the total instead)."""
    if total is not None:
        return f", {so_far}/{total} bytes"
    if so_far:
        return f", {so_far} bytes so far"
    return ""


def _should_skip_existing_upload(
    convert_mime: tuple[str, str] | None, existing_mime_types: Iterable[str]
) -> bool:
    """Whether an upload can be skipped because the destination name is
    already taken, given the mimeTypes of every existing Drive entry sharing
    that name.

    Without convert (convert_mime is None), any existing entry means skip —
    name presence alone. With convert, only an entry already in the target
    Workspace mimeType counts: a same-named file still in its original
    (unconverted) format isn't the converted duplicate skip_if_exists is
    meant to detect (#188 QA review, PR #410).

    Shared by _upload_local_file's own skip_if_exists check and
    upload_local_folder's bulk one below — previously hand-duplicated between
    the two with no shared helper, so a future change to one (e.g.
    case-insensitive mimeType comparison, a new _CONVERT_MIME entry) could
    silently leave the other diverged with nothing flagging the drift (#514,
    surfaced during PR #505's review of #411)."""
    existing_mime_types = set(existing_mime_types)
    if not existing_mime_types:
        return False
    if convert_mime is None:
        return True
    return convert_mime[1] in existing_mime_types


def _existing_upload_match(convert_mime: tuple[str, str] | None, hits: list[dict]) -> dict | None:
    """Return whichever Drive file resource in `hits` (all sharing the
    destination name) represents the existing duplicate skip_if_exists is
    meant to detect, or None if none qualifies — same decision as
    _should_skip_existing_upload above, but returning the specific matching
    entry instead of a bool. _upload_local_file needs this: once more than
    one hit can come back for a shared name, it can no longer assume hits[0]
    is the one that matched (#514 QA round 1, PR #767 — pageSize=1 previously
    made this moot by construction, capping the check to a single entry
    regardless of how many Drive actually returned for the name)."""
    for h in hits:
        if _should_skip_existing_upload(convert_mime, [h.get("mimeType", "")]):
            return h
    return None


# Drive caps each custom property's key + value at 124 UTF-8 bytes; a create()
# carrying a longer one fails with 403 propertyLengthLimitExceeded — yet Drive
# still creates the file, unmarked, leaving an orphan the error result can't
# name (confirmed live, PR #800 QA round 1).
_DRIVE_PROPERTY_MAX_BYTES = 124


def _property_fits(key: str, value: str) -> bool:
    """Whether a Drive custom property fits _DRIVE_PROPERTY_MAX_BYTES."""
    return len(key.encode("utf-8")) + len(value.encode("utf-8")) <= _DRIVE_PROPERTY_MAX_BYTES


def _convert_source_marker(source_name: str) -> str:
    """The _CONVERT_SOURCE_PROP value recorded for (and later compared against)
    a conversion from `source_name`: the name itself when it fits the property
    byte cap, otherwise a fixed-length "sha256:<hex>" digest of it — so a long
    or multibyte filename still gets a verifiable marker instead of either
    failing the create() or going unmarked (PR #800 QA round 1). Writer and
    reader both go through here, so the two can't disagree on the encoding."""
    if _property_fits(_CONVERT_SOURCE_PROP, source_name):
        return source_name
    return "sha256:" + hashlib.sha256(source_name.encode("utf-8")).hexdigest()


def _convert_properties(file_name: str) -> dict[str, str]:
    """Drive `properties` to stamp on a conversion of `file_name`.

    Always _CONVERT_SOURCE_PROP (#769), via _convert_source_marker so it never
    exceeds the byte cap. For a .md source, also _CONVERT_MARKDOWN_SOURCE_PROP
    (#414) — but only when the raw name fits, since that value is read back
    verbatim as the local filename and a digest there would match nothing. An
    over-long .md name goes without it, and sync_folder recognizes the Doc
    through the generic marker instead (#805). Both upload_local_file's convert
    path and sync_folder's own convert_markdown path stamp through here, so
    neither can send a property over the cap."""
    props = {_CONVERT_SOURCE_PROP: _convert_source_marker(file_name)}
    if Path(file_name).suffix.lower() == ".md" and _property_fits(
        _CONVERT_MARKDOWN_SOURCE_PROP, file_name
    ):
        props[_CONVERT_MARKDOWN_SOURCE_PROP] = file_name
    return props


def _has_convert_marker(f: dict) -> bool:
    """Whether Drive file resource `f` carries either conversion marker."""
    props = f.get("properties") or {}
    return (
        props.get(_CONVERT_SOURCE_PROP) is not None
        or props.get(_CONVERT_MARKDOWN_SOURCE_PROP) is not None
    )


def _marker_names_source(f: dict, source_name: str) -> bool:
    """Whether `f`'s conversion marker records `source_name` as its source.
    Checks _CONVERT_SOURCE_PROP (encoded via _convert_source_marker) and falls
    back to _CONVERT_MARKDOWN_SOURCE_PROP (raw name) — a .md Doc converted by
    sync_folder's own convert_markdown path before #805 carries only the latter, and
    is just as much "ours" (#769)."""
    props = f.get("properties") or {}
    generic = props.get(_CONVERT_SOURCE_PROP)
    if generic is not None and generic == _convert_source_marker(source_name):
        return True
    md = props.get(_CONVERT_MARKDOWN_SOURCE_PROP)
    return md is not None and md == source_name


def _find_existing_upload(
    convert_mime: tuple[str, str] | None,
    source_name: str,
    name_hits: list[dict],
    stem_hits: list[dict],
) -> tuple[dict, bool] | None:
    """The skip_if_exists decision shared by _upload_local_file and
    upload_local_folder's bulk check, so the two can't drift apart on it (#514,
    extended to the stem/marker lookup per PR #800 QA round 1). Returns
    (matching entry, verified) when the upload should be skipped, else None.

    `name_hits` are existing entries whose name equals `source_name`;
    `stem_hits` those named after its extension-stripped stem (only consulted
    under convert, since Drive's import conversion strips the extension from
    some converted types' display name — TC-D215/TC-D243).

    - A full-name match (via _existing_upload_match) is always verified.
    - A target-mimeType stem hit whose marker names `source_name` is verified —
      provably the converted duplicate this tool created.
    - Otherwise, a target-mimeType stem hit with no marker at all is an
      unverified match: possibly converted before the marker existed, possibly
      an unrelated file sharing the name. Still skipped (no duplicate
      re-uploads of legacy conversions), but flagged so the caller can report
      the ambiguity (#769).
    - A stem hit marked with a *different* source is provably not this file's
      duplicate and never matches."""
    match = _existing_upload_match(convert_mime, name_hits)
    if match is not None:
        return match, True
    if convert_mime is None:
        return None
    unverified: dict | None = None
    for h in stem_hits:
        if h.get("mimeType") != convert_mime[1]:
            continue
        if _marker_names_source(h, source_name):
            return h, True
        if unverified is None and not _has_convert_marker(h):
            unverified = h
    return (unverified, False) if unverified is not None else None


def _unverified_skip_reason(matched_name: str) -> str:
    return (
        f"name-only match, unverified: an existing {matched_name!r} in the target "
        "format has no conversion marker, so it may be an earlier conversion of "
        "this file or an unrelated file sharing its name"
    )


async def _upload_local_file(
    drive_service,
    local_path: str,
    parent_folder_id: str,
    name: str | None = None,
    skip_if_exists: bool = True,
    convert: bool = False,
    include_permission_ids: bool = False,
) -> dict[str, Any]:
    """Upload a local file to a Drive folder. Shared core behind the upload_local_file
    tool and docs/images.py's insert_local_images (imported cross-package the same
    way docs/content.py imports _SA_QUOTA_ERROR from tools/drive/__init__.py).

    include_permission_ids=True also returns the new file's permissionIds as
    permission_ids, from the same create() call. docs/images.py's
    share_image_file needs them to tell a grant it creates from one the file
    inherited (PR #842). Off by default so the upload_local_file tool's own
    response stays unchanged.

    convert=True requests Drive's native import conversion (CSV/XLSX -> Sheets,
    DOCX/MD/HTML -> Docs, PPTX -> Slides) by uploading with the source format's
    mimeType while setting the destination file's mimeType to the target Google
    Workspace type — this is distinct from create_doc_from_file, which parses the
    file locally and rebuilds it via Docs API requests instead of Drive's importer.
    upload_file's convert_to_doc param implements the identical trick for raw
    text/markdown/html content instead of a local file — see _GOOGLE_DOC_MIME
    above, shared by both so they can't drift apart on the target mimeType (#412)."""
    path = Path(local_path)
    if not path.is_file():
        raise ValueError(f"No file found at {local_path!r}")

    file_name = name or path.name

    convert_mime: tuple[str, str] | None = None
    if convert:
        # Derived from the effective destination name, not local_path's suffix —
        # a name= override changes what conversion applies (#188 QA review, PR #410).
        dest_suffix = Path(file_name).suffix.lower()
        convert_mime = _CONVERT_MIME.get(dest_suffix)
        if convert_mime is None:
            supported = ", ".join(sorted(_CONVERT_MIME))
            return {
                "error": (
                    f"Conversion not supported for extension {dest_suffix!r}. "
                    f"Supported extensions: {supported}"
                )
            }

    if skip_if_exists:
        # Under convert, also look up the extension-stripped stem — Drive's
        # import conversion drops the extension from some converted types'
        # display name, and without this a converted duplicate this tool itself
        # created was invisible here while upload_local_folder's bulk check
        # already recognized it (PR #800 QA round 1). One query covers both.
        stem = Path(file_name).stem if convert_mime is not None else None
        lookup_names = [file_name] if stem is None else [file_name, stem]
        name_clause = " or ".join(
            "name='{}'".format(n.replace("\\", "\\\\").replace("'", "\\'")) for n in lookup_names
        )
        existing = await execute_in_thread(
            drive_service.files()
            .list(
                q=f"({name_clause}) and '{parent_folder_id}' in parents and trashed=false",
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                # properties only under convert — nothing else reads the marker.
                fields=(
                    "files(id, name, webViewLink, mimeType, properties)"
                    if convert_mime is not None
                    else "files(id, name, webViewLink, mimeType)"
                ),
            )
            .execute,
            drive_service,
        )
        hits = existing.get("files", [])
        # pageSize deliberately left at the API default (100), not capped to 1
        # — Drive allows more than one file to share this name, and the match
        # (via _find_existing_upload, not necessarily hits[0]) needs every
        # candidate visible to pick the correct one to report back (#514 QA
        # round 1, PR #767).
        found = _find_existing_upload(
            convert_mime,
            file_name,
            [h for h in hits if h.get("name") == file_name],
            [h for h in hits if stem is not None and h.get("name") == stem],
        )
        if found is not None:
            match, verified = found
            logger.debug("Skipping upload — %s already exists as %s", file_name, match["id"])
            skip_result: dict[str, Any] = {
                "fileId": match["id"],
                "name": match["name"],
                "web_link": match.get("webViewLink"),
                "skipped": True,
            }
            if not verified:
                skip_result["skipped_unverified"] = True
                skip_result["reason"] = _unverified_skip_reason(match["name"])
            return skip_result

    # Stamped on every upload, not just the convert_mime branch — a plain upload
    # used to get Drive's own creation timestamp instead of the local file's mtime,
    # which is the actual root cause of sync_folder's use_checksum needing to exist
    # at all: without this, a file uploaded here always reads as "Drive newer" on
    # the very next sync_folder call regardless of content (#274 PR #472 review,
    # finding #2). Drive honors modifiedTime in the create() body directly for a
    # plain upload (no import-conversion in the way), so no follow-up update() is
    # needed here the way the convert_mime branch below requires.
    metadata: dict[str, Any] = {
        "name": file_name,
        "parents": [parent_folder_id],
    }
    if convert_mime is not None:
        mime, target_mime = convert_mime
        metadata["mimeType"] = target_mime
        # Stamped on every conversion, so both skip_if_exists paths can
        # recognize this file as ours even after Drive strips the source
        # extension from its display name (#769) — and, for .md, so
        # sync_folder's convert_markdown matching recognizes it too (#414 QA
        # review round 3, finding #2). _convert_properties keeps every value
        # within Drive's per-property byte cap (PR #800 QA round 1).
        metadata["properties"] = _convert_properties(file_name)
    else:
        mime, _ = mimetypes.guess_type(local_path)
        mime = mime or "application/octet-stream"
    try:
        # Inside the try, so a file that vanishes or becomes unreadable after
        # the is_file() check above returns {"error": ...} instead of raising
        # out of the tool (PR #817 QA).
        lmtime = _local_mtime_dt(path)
        lmtime_str = _drive_time_str(lmtime)
        metadata["modifiedTime"] = lmtime_str
        if convert_mime is not None and Path(file_name).suffix.lower() == ".md":
            # sync_folder's change-detection references for this Doc (#814).
            metadata["properties"] = {
                **metadata["properties"],
                **_converted_md_upload_properties(lmtime),
            }
        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        result = await execute_in_thread(
            drive_service.files()
            .create(
                body=metadata,
                media_body=media,
                supportsAllDrives=True,
                # webContentLink saves an image-embedding caller a follow-up
                # files().get() (#511); it's absent for a converted Workspace file.
                fields="id, name, webViewLink, webContentLink"
                + (", permissionIds" if include_permission_ids else ""),
            )
            .execute,
            drive_service,
        )
    except HttpError as e:
        return {"error": _quota_error_detail(e)}
    except Exception as e:
        # The upload_local_file tool has no try/except of its own, so a create()
        # failure must be caught here rather than propagate uncaught (#422 QA
        # review, finding #1). Nothing was created in this branch, so a bare
        # error with no fileId is correct — a restamp failure after create()
        # *did* succeed is reported with its fileId by _restamp_modified_time
        # (#420).
        return {"error": str(e)}

    if convert_mime is not None:
        # See _restamp_modified_time for why every conversion type needs this.
        # A plain (non-converting) upload has no such override — the create()
        # body's modifiedTime above already sticks, no restamp needed.
        restamp_failure = await _restamp_modified_time(drive_service, result["id"], lmtime_str)
        if restamp_failure is not None:
            return restamp_failure

    logger.debug("Uploaded %s → %s (%s)", local_path, result.get("id"), mime)
    uploaded = {
        "fileId": result.get("id"),
        "name": result.get("name", file_name),
        "web_link": result.get("webViewLink"),
        "skipped": False,
    }
    if web_content_link := result.get("webContentLink"):
        uploaded["web_content_link"] = web_content_link
    if include_permission_ids:
        uploaded["permission_ids"] = result.get("permissionIds")
    return uploaded


def _local_md5(path: Path) -> str:
    """Stream-hash a local file — mirrors Drive's md5Checksum so sync_folder's
    use_checksum path can compare content directly instead of inferring change
    from modifiedTime alone."""
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _list_drive_children(drive_service, folder_id: str) -> tuple[list[dict], list[dict]]:
    """Return (files, folders) among the direct children of a Drive folder."""
    results = await execute_in_thread(
        drive_service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="files(id, name, mimeType, modifiedTime, properties, md5Checksum, size)",
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


_SyncAction = Literal[
    "skip",
    "conflict",
    "collision",
    "unsafe_name",
    "local_read_fail",
    "drive_read_fail",
    "upload",
    "download",
]


@dataclass
class _SyncStep:
    """One name _sync_level has planned an action for, replacing the previous
    untyped dict[str, str] (#749) — the same fragility #740's _DownloadCandidate
    (below) fixed for download_folder's candidates: a plan.append({...}) site
    that dropped or renamed a key, or a step["..."] read that typo'd one, had
    no type error to catch it, just a silent runtime KeyError (or a
    silently-wrong value from a typo'd Literal). action is one of _SyncAction's
    values, not a bare str, so a call site passing an action _run_one doesn't
    actually branch on is now a type-checker error too."""

    name: str
    action: _SyncAction
    reason: str


def _diverged_same_mtime_step(name: str, evidence: str) -> _SyncStep:
    """The conflict for a both-sides pair whose content has diverged while its
    mtimes agree, whatever showed the divergence (a byte-size mismatch, #659,
    or an md5 mismatch, #716). Always a conflict, never an auto-transfer: the
    mtimes agree, so which side is newer is unknown, and the diff-based
    branches already report a conflict rather than overwrite a target they
    *can* tell is newer (local-newer + direction='download', drive-newer +
    direction='upload'). This case knows strictly less, so it must be at least
    as cautious (PR #712 QA round 1)."""
    return _SyncStep(
        name=name,
        action="conflict",
        reason=(
            f"content differs ({evidence}) but mtimes match — can't tell which side "
            "is newer; touch the newer file, or delete the stale copy, then re-sync"
        ),
    )


def _mtime_step(name: str, diff: float, direction: str, is_converted_md: bool) -> _SyncStep:
    """The plan step for a both-sides pair decided from mtimes alone, `diff`
    being local minus Drive in seconds. Also the fallback a use_checksum
    mismatch lands on when the mtimes disagree, since content differing
    doesn't by itself say which side is newer."""
    if abs(diff) <= _SYNC_MTIME_TOLERANCE:
        return _SyncStep(name=name, action="skip", reason="in sync")
    if diff > 0:
        if direction in ("upload", "bidirectional"):
            return _SyncStep(name=name, action="upload", reason=f"local newer by {diff:.0f}s")
        return _SyncStep(
            name=name,
            action="conflict",
            reason=f"local newer by {diff:.0f}s but direction is download",
        )
    if is_converted_md:
        # Same reasoning as the drive-only case in _sync_level: this Doc can't
        # be downloaded regardless of direction. Only a legacy converted Doc
        # (no _CONVERTED_MD_SOURCE_MTIME_PROP) reaches this; the rest go through
        # _converted_md_step. For a legacy Doc this fires on a real Drive edit,
        # and also when the async modifiedTime update beat the restamp (#814).
        return _SyncStep(
            name=name,
            action="conflict",
            reason=(
                f"drive newer by {-diff:.0f}s but {_NO_REVERSE_CONVERSION_CLAUSE} — "
                "re-upload the local file to update Drive"
            ),
        )
    if direction in ("download", "bidirectional"):
        return _SyncStep(name=name, action="download", reason=f"drive newer by {-diff:.0f}s")
    return _SyncStep(
        name=name,
        action="conflict",
        reason=f"drive newer by {-diff:.0f}s but direction is upload",
    )


@dataclass
class _HashJob:
    """A both-sides pair use_checksum will hash once the plan loop finishes.
    `index` is its placeholder step's position in the plan (already holding
    the mtime-based fallback), so the hashes can run concurrently and still
    land back in name order."""

    index: int
    name: str
    drive_md5: str
    within_tolerance: bool


@dataclass
class _RevisionJob:
    """A both-sides convert_markdown Doc whose Drive side _sync_level will check
    through revision history once the plan loop finishes (#814). `index` is its
    placeholder step's position in the plan; `local_diff` is the local mtime
    minus the stamped _CONVERTED_MD_SOURCE_MTIME_PROP, in seconds."""

    index: int
    name: str
    entry: dict
    source_mtime: datetime
    local_diff: float


def _converted_md_source_mtime(f: dict) -> datetime | None:
    """The local mtime stamped on convert_markdown Doc `f` at its last upload,
    or None for a Doc converted before #814 (or one whose value is unreadable),
    which stays on the modifiedTime comparison."""
    return _parse_time((f.get("properties") or {}).get(_CONVERTED_MD_SOURCE_MTIME_PROP))


# 100 pages of 1,000 revisions: only a nextPageToken that never goes falsy reaches it.
_REVISIONS_MAX_PAGES = 100


async def _list_revisions(drive_service, file_id: str) -> list[dict]:
    """Every revision of `file_id` as {id, modifiedTime}, oldest first, across
    all pages."""
    revisions: list[dict] = []
    async for resp in iter_pages(
        lambda token: drive_service.revisions().list(
            fileId=file_id,
            fields="nextPageToken, revisions(id, modifiedTime)",
            pageSize=1000,
            pageToken=token,
        ),
        drive_service,
        max_pages=_REVISIONS_MAX_PAGES,
    ):
        revisions.extend(resp.get("revisions", []))
    return revisions


_ConvertedMdDriveState = Literal["unchanged", "changed", "pending", "baseline_missing"]


def _converted_md_drive_state(
    props: dict, revisions: list[dict]
) -> tuple[_ConvertedMdDriveState, str | None]:
    """Whether a convert_markdown Doc was edited in Drive since its last upload,
    judged from its revision history rather than modifiedTime (#814). Returns
    (state, import revision to record, if newly identified). `revisions` must
    be non-empty; the caller treats an empty history as a read failure, since
    every Doc has at least its import (PR #854 QA round 1).

    Once the import's revision ID is recorded, the Doc was edited in Drive
    exactly when its latest revision is a different one: an edit never merges
    into the import's revision (measured live, see the decision doc), and Drive
    trimming older revisions doesn't touch the latest.

    Until then, the import is the first revision after the baseline stamped
    just before the re-upload, or the Doc's first revision if it has no
    baseline (a new Doc). A baseline Drive has since pruned falls back to the
    first revision timestamped at or after the upload. No such revision yet
    means the sync ran seconds after the upload: 'pending', retried next sync.
    A candidate timestamped well after the upload (past
    _CONVERTED_MD_IMPORT_WINDOW) isn't the import at all: Drive merged the
    import into a later edit while compacting the history, which happens only
    if the first sync comes long after a Drive edit (PR #854 QA round 1), so
    that's 'changed'. Without the upload time (a Doc stamped by an earlier
    build of #814), a pruned baseline is 'baseline_missing'."""
    ids = [r["id"] for r in revisions]
    recorded = props.get(_CONVERTED_MD_IMPORT_REV_PROP)
    if recorded is not None:
        return ("unchanged" if ids[-1] == recorded else "changed"), None
    uploaded_at = _parse_time(props.get(_CONVERTED_MD_UPLOADED_AT_PROP))
    baseline = props.get(_CONVERTED_MD_BASELINE_REV_PROP)
    if baseline is None:
        start = 0
    elif baseline in ids:
        start = ids.index(baseline) + 1
    elif uploaded_at is not None:
        earliest = uploaded_at.timestamp() - _CONVERTED_MD_CLOCK_SKEW
        start = next(
            (
                i
                for i, r in enumerate(revisions)
                if (t := _parse_time(r.get("modifiedTime"))) is not None
                and t.timestamp() >= earliest
            ),
            len(revisions),
        )
    else:
        return "baseline_missing", None
    if start >= len(revisions):
        return "pending", None
    candidate = revisions[start]
    candidate_time = _parse_time(candidate.get("modifiedTime"))
    if (
        uploaded_at is not None
        and candidate_time is not None
        and (candidate_time - uploaded_at).total_seconds() > _CONVERTED_MD_IMPORT_WINDOW
    ):
        return "changed", None
    return ("unchanged" if ids[-1] == candidate["id"] else "changed"), candidate["id"]


def _converted_md_step(
    name: str, local_diff: float, drive_state: _ConvertedMdDriveState, direction: str
) -> _SyncStep:
    """The plan step for a both-sides convert_markdown Doc that carries #814's
    properties. `local_diff` is the local mtime minus the mtime stamped at the
    last upload, compared exactly (_CONVERTED_MD_STAMP_TOLERANCE). Drive's
    modifiedTime is never consulted (see _CONVERTED_MD_SOURCE_MTIME_PROP).

    A Drive edit is always a conflict: there is no reverse conversion to
    download it, and re-uploading would overwrite it, including when the local
    file changed too (the case the modifiedTime comparison used to upload
    straight over)."""
    if local_diff < -_CONVERTED_MD_STAMP_TOLERANCE:
        return _SyncStep(
            name=name,
            action="conflict",
            reason=(
                f"local .md is {-local_diff:.0f}s older than the version last uploaded "
                "(rolled back?) — can't tell which side is newer; touch the local file, "
                "or remove the Doc in Drive, then re-sync"
            ),
        )
    local_changed = local_diff > _CONVERTED_MD_STAMP_TOLERANCE
    if drive_state == "baseline_missing":
        return _SyncStep(
            name=name,
            action="conflict",
            reason=(
                "can't tell whether the Doc was edited in Drive: the revision recorded "
                "before its last upload is gone from its history — rename or remove the "
                "Doc in Drive, then re-sync to upload a fresh copy"
            ),
        )
    if drive_state == "changed":
        if local_changed:
            reason = (
                "edited both locally and in Drive since the last upload — re-uploading "
                f"would overwrite the Drive edit, and {_NO_REVERSE_CONVERSION_CLAUSE}; "
                "merge the Drive edits into the local .md, then rename or remove the "
                "Doc in Drive and re-sync"
            )
        else:
            reason = (
                f"edited in Drive since the last upload, but {_NO_REVERSE_CONVERSION_CLAUSE} "
                "— merge the Drive edits into the local .md, then rename or remove the "
                "Doc in Drive and re-sync"
            )
        return _SyncStep(name=name, action="conflict", reason=reason)
    if not local_changed:
        return _SyncStep(name=name, action="skip", reason="in sync")
    if direction not in ("upload", "bidirectional"):
        # Before the pending check: under 'download' this never uploads, so
        # "re-sync to upload it" would be wrong (PR #854 QA round 1).
        return _SyncStep(
            name=name,
            action="conflict",
            reason="local .md changed since the last upload but direction is download",
        )
    if drive_state == "pending":
        # Re-uploading now would stamp a baseline taken before the previous
        # upload's import revision appeared, so that import would later read
        # as a Drive edit. Waiting one sync costs nothing.
        return _SyncStep(
            name=name,
            action="skip",
            reason=(
                "local .md changed, but the previous upload hasn't shown up in the "
                "Doc's revision history yet — re-sync in a minute to upload it"
            ),
        )
    return _SyncStep(
        name=name,
        action="upload",
        reason=f"local .md changed {local_diff:.0f}s after the last upload",
    )


async def _sync_level(
    lc,
    drive_service,
    drive_folder_id: str | None,
    dest_dir: Path,
    rel_prefix: str,
    direction: str,
    export_format: str | None,
    convert_markdown: bool,
    use_checksum: bool,
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
    progress_bytes: list[int],
) -> int:
    """
    Sync the files directly inside one Drive-folder/local-dir pair and, if `recursive`,
    descend into subfolders matched by name. `drive_folder_id=None` simulates a Drive
    folder that doesn't exist yet (used for dry-run planning of a not-yet-created
    upload-direction folder) — no Drive API call is made and drive-side maps stay empty.

    convert_markdown=True (#211) treats a local .md file's upload as a request for
    Drive's native import conversion (same mechanism as upload_local_file's convert
    param, #188): uploaded with mimetype='text/markdown', landing as a Google Doc
    that keeps the original '.md' name. Since the converted file is still named
    '<name>.md' in Drive, it's matched back to its local counterpart directly (not
    via the export_format suffix scheme used for other Workspace files) so re-syncs
    settle into "in sync" instead of re-uploading a duplicate on every run. Such a
    Doc's changes aren't judged from Drive's modifiedTime, which lags Docs edits
    by minutes (#814): the local side compares against the mtime stamped at
    upload, the Drive side against revision history (_converted_md_step). A Doc
    converted before #814 carries no stamp and keeps the mtime comparison until
    its next re-upload.

    use_checksum=True (#274) adds a content check, after the (cheap) mtime diff and
    byte-size check but before the mtime-based direction decision, for names
    present on both sides — skipped when dry_run is True, so a dry_run preview
    never pays for a hash read (PR #472 review, finding #3); an affected dry_run
    step's reason ends in "(checksum not verified in dry_run)" instead, since
    the real run can reach a different verdict (PR #841 QA). Since this reads
    every such file, the reads run after the plan loop, concurrently, capped at
    _SYNC_HASH_CONCURRENCY. When it runs: if the
    local file's md5 hash matches Drive's own md5Checksum, the pair is treated as
    in sync regardless of how far apart their modifiedTimes are — this is what
    actually fixes upload_local_file's non-stamped modifiedTime causing a spurious
    re-download, not just a same-mtime coincidence (also fixed at the root in
    _upload_local_file itself, below — this remains useful for cases the root fix
    doesn't cover, e.g. a local overwrite that happens to preserve mtime). Only
    applies to non-Workspace files with a real md5Checksum (Docs/Sheets/Slides and
    convert_markdown Docs have none); those fall back to mtime-only comparison
    exactly as when use_checksum=False. A checksum mismatch on a pair whose
    mtimes disagree doesn't short-circuit anything — it falls through to the
    existing mtime-based direction decision below (reusing the diff already
    computed), since content differing doesn't by itself say which side is newer.
    A mismatch on a pair whose mtimes are within tolerance (and whose sizes
    match) is a 'conflict' for every direction, for the same reason as the
    byte-size case below (#716): an explicit use_checksum=True is an accuracy
    opt-in, so it verifies within-tolerance pairs too instead of trusting mtime
    alone, and that is the only way to catch a same-size, mtime-preserving
    edit. A local read failure (file vanished, lost permission, etc. between the
    directory scan and the plan's stat or this read) reports that one name under
    'failed' instead of raising out of the whole call (finding #1; PR #841 QA
    extended it to the stat).

    Independently of use_checksum (#659): for a both-sides pair whose mtimes are
    within tolerance, the local file's byte size is compared against Drive's
    reported `size` (already in the folder listing; one stat, no read, so this
    runs during dry_run too). If they differ the content has definitely diverged
    — most often a rename-in-place, where `mv` preserves the mtime so the
    equal-mtime skip would hide it forever — and the pair is reported as a
    'conflict' for every direction, never auto-transferred: the mtimes agree so
    recency is unknown, and the 'diff'-based branches below already report
    'conflict' rather than overwrite a target they *can* tell is newer, so this
    branch (which knows less) must be at least as cautious. Non-Workspace files
    only (Workspace/convert_markdown files report no `size`). A same-size edit
    that also preserves mtime still reads as "in sync" unless use_checksum=True
    (above), since only a hash can see it.

    Returns bytes downloaded at this level and below; all other results are appended
    into the shared accumulator lists/dicts passed in from the top-level call.
    """
    drive_files: list[dict] = []
    drive_folders: list[dict] = []
    if drive_folder_id is not None:
        drive_files, drive_folders = await _list_drive_children(drive_service, drive_folder_id)

    drive_map: dict[str, dict] = {}
    collision_names: set[str] = set()
    collision_reasons: dict[str, str] = {}
    # Names that can't be a single local path component (see
    # _unsafe_name_reason), mapped to why. They never enter drive_map or
    # local_map, so nothing below can join one onto dest_dir.
    unsafe_names: dict[str, str] = {}
    # Every Drive entry under an unsafe name is counted, so duplicates don't
    # vanish from the output (the same gap #422 closed for collisions).
    unsafe_drive_counts: dict[str, int] = {}
    unsafe_local_names: set[str] = set()
    for f in drive_files:
        is_workspace = _is_workspace_entry(f)
        # Deliberately independent of this call's convert_markdown flag: a Doc
        # already carries the marker property from whenever it was created, and
        # matching must recognize it on every later sync regardless of whether
        # that particular call happens to pass convert_markdown=True. Gating this
        # on the flag (round 2) meant a resync with the flag merely omitted saw
        # the local .md as "local only" and silently created a second, plain-text
        # duplicate next to the existing Doc (#414 QA review round 3, finding #1).
        md_source = _converted_md_source_name(f)
        if md_source is not None:
            # The recorded source name, not f["name"] — see _converted_md_source_name.
            local_name = md_source
        elif is_workspace:
            if not export_format:
                continue  # excluded without an export format
            local_name = f["name"] + _EXPORT_MIME[export_format][1]
        else:
            local_name = f["name"]

        # Checked on local_name, not f["name"]: a converted Doc's source name
        # comes from its Drive properties, which whoever shared it controls too.
        unsafe_reason = _unsafe_name_reason(local_name)
        if unsafe_reason is not None:
            unsafe_names[local_name] = unsafe_reason
            unsafe_drive_counts[local_name] = unsafe_drive_counts.get(local_name, 0) + 1
            continue
        if local_name in collision_names:
            continue
        if local_name in drive_map:
            # Drive allows more than one entry to share the same display name —
            # whichever was enumerated last used to silently win the drive_map
            # slot, making every other entry with that name completely invisible
            # to this sync (never uploaded, downloaded, or reported anywhere).
            # Originally this only fired when _is_converted_md differed between
            # the two entries (a plain file vs. a convert_markdown Doc, #422's
            # own reported scenario) — leaving any same-type collision (two plain
            # files, or two convert_markdown Docs, sharing a name) silently
            # overwritten just the same (#422 QA review, finding #2). The reason
            # is recorded here but not written to `failed` yet — that only
            # happens for a real run (see the plan loop below), so a dry_run
            # preview shows this as a `conflict` instead of a `failed` entry that
            # implies something was actually attempted (finding #4).
            existing_is_converted = _is_converted_md_entry(drive_map[local_name])
            if existing_is_converted != (md_source is not None):
                detail = "a plain file and a convert_markdown Doc"
            elif md_source is not None:
                detail = "two convert_markdown Docs"
            else:
                detail = "multiple files"
            collision_reasons[local_name] = (
                f"{detail} are named '{local_name}' in this Drive folder — sync "
                "can't tell which one the local file matches; rename or remove "
                "one of them in Drive"
            )
            collision_names.add(local_name)
            del drive_map[local_name]
            continue
        # drive_map stays a plain passthrough of Drive's own file resource — no
        # synthetic "_is_converted_md" key spread in (#421 finding #6); every
        # site below that needs this classification recomputes it on demand via
        # _is_converted_md_entry. That's a few dict lookups plus, for a
        # digest-marked Doc only, a sha256 of a ~100-byte name (#805):
        # microseconds, far below the Drive round trip each file already
        # costs, so not worth a parallel cache that could drift from drive_map.
        drive_map[local_name] = f

    local_map: dict[str, Path] = {}
    if dest_dir.is_dir():
        for p in dest_dir.iterdir():
            if not p.is_file():
                continue
            if skip_system_files and p.name in _SYSTEM_FILES:
                continue
            if _is_partial_download(p.name):
                continue
            # Only a backslash (a separator on Windows, legal in a POSIX name) can
            # fail this for a name the OS listed. Such a file would upload under
            # a name this check then refuses on the Drive side, so it'd never
            # match again; refuse it up front instead.
            unsafe_reason = _unsafe_name_reason(p.name)
            if unsafe_reason is not None:
                unsafe_names[p.name] = unsafe_reason
                unsafe_local_names.add(p.name)
                continue
            local_map[p.name] = p

    def _drive_mtime(entry: dict) -> datetime:
        return datetime.fromisoformat(entry["modifiedTime"].replace("Z", "+00:00"))

    plan: list[_SyncStep] = []
    hash_jobs: list[_HashJob] = []
    revision_jobs: list[_RevisionJob] = []
    for name in sorted(drive_map.keys() | local_map.keys() | collision_names | unsafe_names.keys()):
        if name in unsafe_names:
            # Same shape as local_read_fail: one 'failed' entry on a real run,
            # never an exception out of the whole call.
            plan.append(
                _unsafe_name_step(
                    name,
                    unsafe_names[name],
                    in_drive=name in unsafe_drive_counts,
                    in_local=name in unsafe_local_names,
                    direction=direction,
                    drive_count=unsafe_drive_counts.get(name, 0),
                )
            )
            continue
        if name in collision_names:
            # Route through the normal plan machinery (like every other action)
            # rather than a bare `continue` — the earlier version silently
            # dropped this name from every output list whenever a *local* file
            # also happened to share it, with zero acknowledgment anywhere
            # (#422 QA review, finding #3). Reported as 'conflict' during
            # dry_run (a preview, not a failure) and as a real 'failed' entry
            # once execution is actually attempted — see the collision handling
            # in the dry_run branch and _run_one below.
            plan.append(_SyncStep(name=name, action="collision", reason=collision_reasons[name]))
            continue
        in_drive = name in drive_map
        in_local = name in local_map

        if in_drive and not in_local:
            if direction not in ("download", "bidirectional"):
                # Upload-only callers don't care about drive-only content, whether
                # or not it's a convert_markdown Doc — checking _is_converted_md
                # first (as the pre-#422 code did) reported "conflict" even under
                # direction='upload', where an ordinary drive-only file would have
                # reported a plain "skip" (#422, finding #3).
                plan.append(
                    _SyncStep(name=name, action="skip", reason="drive only, upload direction")
                )
            elif _is_converted_md_entry(drive_map[name]):
                # A convert_markdown Doc has no reverse conversion — queuing this as
                # a "download" here (as the pre-#414 code did) would either crash on
                # the runtime guard below or, worse, write export_format's binary
                # export content into a file still named .md if export_format was
                # also set (#414 QA review, findings #1 and #4). Report it plainly
                # up front instead, in both dry_run and a real run.
                plan.append(
                    _SyncStep(
                        name=name,
                        action="conflict",
                        reason=(
                            f"drive-only convert_markdown Doc — {_NO_REVERSE_CONVERSION_CLAUSE}; "
                            "add a matching local .md or remove it in Drive"
                        ),
                    )
                )
            else:
                plan.append(_SyncStep(name=name, action="download", reason="drive only"))

        elif in_local and not in_drive:
            if direction in ("upload", "bidirectional"):
                plan.append(_SyncStep(name=name, action="upload", reason="local only"))
            else:
                plan.append(
                    _SyncStep(name=name, action="skip", reason="local only, download direction")
                )

        else:
            # One guarded stat feeds both the mtime and the size check. A file
            # deleted (or made unreadable) between the directory scan above and
            # here degrades to one 'failed' entry instead of raising out of the
            # whole call — the same vanish race #817 closed on the upload path
            # (PR #841 QA).
            try:
                st = local_map[name].stat()
            except OSError as e:
                plan.append(_SyncStep(name=name, action="local_read_fail", reason=str(e)))
                continue
            lmtime = _local_mtime_dt(local_map[name], st)
            entry = drive_map[name]

            # A convert_markdown Doc stamped by #814 never compares against
            # Drive's modifiedTime, which lags Docs edits by minutes. Its local
            # side is judged here against the stamped source mtime; its Drive
            # side needs revision history, fetched concurrently below, so it
            # holds a placeholder step until then.
            source_mtime = (
                _converted_md_source_mtime(entry) if _is_converted_md_entry(entry) else None
            )
            if source_mtime is not None:
                revision_jobs.append(
                    _RevisionJob(
                        index=len(plan),
                        name=name,
                        entry=entry,
                        source_mtime=source_mtime,
                        local_diff=(lmtime - source_mtime).total_seconds(),
                    )
                )
                plan.append(_SyncStep(name=name, action="skip", reason="revision check pending"))
                continue

            dmtime = _drive_mtime(entry)
            diff = (lmtime - dmtime).total_seconds()
            is_workspace = _is_workspace_entry(entry)
            within_tolerance = abs(diff) <= _SYNC_MTIME_TOLERANCE

            # Byte-size divergence check, only meaningful once the mtimes agree:
            # Drive reports `size` for every non-Workspace file, so an
            # equal-mtime pair whose sizes differ has definitely diverged — most
            # often a rename-in-place (`mv` preserves mtime), which the plain "in
            # sync" skip would otherwise hide forever, since nothing re-bumps the
            # mtime (#659). No read, so this still runs during dry_run, and it
            # runs before the hash below so a size mismatch never pays for a
            # read it doesn't need (#716). Workspace / convert_markdown files
            # report no `size` and fall through.
            if within_tolerance:
                drive_size = entry.get("size") if not is_workspace else None
                if drive_size is not None and st.st_size != int(drive_size):
                    plan.append(
                        _diverged_same_mtime_step(name, "local and Drive byte sizes disagree")
                    )
                    continue

            step = _mtime_step(name, diff, direction, _is_converted_md_entry(entry))

            # use_checksum is an explicit accuracy opt-in, so it verifies every
            # both-sides pair with a real md5Checksum — including a within-
            # tolerance, same-size one, which is the only way to catch a
            # same-size edit that also preserved mtime (#716; #274/#659 gated it
            # on the mtimes already disagreeing, leaving that gap). The hash is
            # deferred to a concurrent pass below; `step` sits in the plan as the
            # mtime-only fallback until then. Skipped during dry_run, which is a
            # cheap no-read preview (#274 PR #472 review, finding #3) — but the
            # preview says so, since a real run can reach a different verdict
            # (a within-tolerance mismatch previews as "in sync" and runs as a
            # conflict; PR #841 QA).
            drive_md5 = entry.get("md5Checksum") if not is_workspace else None
            if use_checksum and drive_md5 is not None:
                if dry_run:
                    step.reason += " (checksum not verified in dry_run)"
                else:
                    hash_jobs.append(
                        _HashJob(
                            index=len(plan),
                            name=name,
                            drive_md5=drive_md5,
                            within_tolerance=within_tolerance,
                        )
                    )
            plan.append(step)

    if hash_jobs:
        sem = asyncio.Semaphore(_SYNC_HASH_CONCURRENCY)

        async def _hash_one(job: _HashJob) -> str:
            async with sem:
                return await asyncio.to_thread(_local_md5, local_map[job.name])

        hashes = await asyncio.gather(*(_hash_one(j) for j in hash_jobs), return_exceptions=True)
        for job, local_md5 in zip(hash_jobs, hashes, strict=True):
            if isinstance(local_md5, OSError):
                # The file vanished, lost read permission, or became an
                # unreadable special file after it was statted — one 'failed'
                # entry, not an exception out of the whole call (#274 PR #472
                # review, finding #1).
                plan[job.index] = _SyncStep(
                    name=job.name, action="local_read_fail", reason=str(local_md5)
                )
            elif isinstance(local_md5, BaseException):
                raise local_md5
            elif local_md5 == job.drive_md5:
                plan[job.index] = _SyncStep(
                    name=job.name, action="skip", reason="content identical (checksum match)"
                )
            elif job.within_tolerance:
                plan[job.index] = _diverged_same_mtime_step(job.name, "checksum mismatch")
            # Otherwise the mtimes disagree and the content does too: keep the
            # mtime-based fallback already in the plan, since a mismatch doesn't
            # say which side is newer. One that resolves to 'upload' reads this
            # file a second time (MediaFileUpload streams it for the transfer) —
            # a known, accepted cost (#274 PR #472 review, finding #4): avoiding
            # it would mean buffering the whole file in memory across both reads,
            # a worse tradeoff for large files than one extra, likely
            # page-cache-warm, disk read.

    # Each converted Doc's latest revision as the plan saw it, so an upload can
    # tell whether Drive moved on between planning and the update() (PR #854
    # QA round 1).
    planned_latest_revision: dict[str, str] = {}
    # Recording an import revision changes the Doc's properties (and, for an
    # unedited Doc, re-sends modifiedTime), so the folder cache must be
    # invalidated like any other metadata write here (PR #854 QA round 1).
    recorded_metadata = False
    if revision_jobs:
        # Runs during dry_run too: it's one metadata read per Doc, and without
        # it the preview couldn't show a Drive edit at all. Only recording a
        # newly identified import revision (a write) waits for a real run.
        rev_sem = asyncio.Semaphore(_SYNC_REVISION_CONCURRENCY)

        async def _revisions_one(job: _RevisionJob) -> list[dict]:
            async with rev_sem:
                return await _list_revisions(drive_service, job.entry["id"])

        revision_lists = await asyncio.gather(
            *(_revisions_one(j) for j in revision_jobs), return_exceptions=True
        )
        to_record: list[tuple[_RevisionJob, str, bool]] = []
        for job, revisions in zip(revision_jobs, revision_lists, strict=True):
            if isinstance(revisions, BaseException) and not isinstance(revisions, Exception):
                raise revisions
            if isinstance(revisions, Exception) or not revisions:
                # Without revision history the Drive side is unknown, and
                # guessing "unchanged" could hide an edit this check exists to
                # catch. Every Doc has at least its import revision, so an
                # empty list is a bad read too, not an edit: reading it as one
                # would point the user at replacing the Doc (PR #854 QA round
                # 1). One failed entry for this name, not the whole call.
                detail = (
                    _quota_error_detail(revisions)
                    if isinstance(revisions, Exception)
                    else "Drive returned an empty revision history"
                )
                plan[job.index] = _SyncStep(
                    name=job.name,
                    action="drive_read_fail",
                    reason=f"couldn't read the Doc's revision history to check for Drive edits: {detail}",
                )
                continue
            planned_latest_revision[job.name] = revisions[-1]["id"]
            drive_state, import_rev = _converted_md_drive_state(
                job.entry.get("properties") or {}, revisions
            )
            step = _converted_md_step(job.name, job.local_diff, drive_state, direction)
            plan[job.index] = step
            # An upload re-stamps these properties anyway.
            if import_rev is not None and not dry_run and step.action != "upload":
                to_record.append((job, import_rev, drive_state == "unchanged"))

        async def _record_import_revision(
            job: _RevisionJob, revision_id: str, unedited: bool
        ) -> None:
            # A property write bumps modifiedTime to "now" (seen live), so it
            # always re-sends one. An unedited Doc gets the cosmetic restamp
            # value. A Drive-edited one keeps Drive's own value from the
            # listing: re-sending the source mtime reset an edit's timestamp
            # and made the Doc look unedited, and leaving it out stamped the
            # sync's own time over the edit's (both seen live, PR #854 QA
            # round 1). If that value still lags the edit, the Docs backend's
            # own late update lands afterward, as it does without this write.
            body: dict[str, Any] = {
                "properties": {_CONVERTED_MD_IMPORT_REV_PROP: revision_id},
                "modifiedTime": (
                    _drive_time_str(job.source_mtime) if unedited else job.entry["modifiedTime"]
                ),
            }
            async with rev_sem:
                await execute_in_thread(
                    drive_service.files()
                    .update(
                        fileId=job.entry["id"],
                        body=body,
                        supportsAllDrives=True,
                        fields="id",
                    )
                    .execute,
                    drive_service,
                )

        recorded = await asyncio.gather(
            *(_record_import_revision(*args) for args in to_record),
            return_exceptions=True,
        )
        for (job, _, _), outcome in zip(to_record, recorded, strict=True):
            if isinstance(outcome, Exception):
                # Harmless: the next sync identifies the same import revision
                # from the baseline again and retries the write.
                logger.debug(
                    "Failed to record import revision on %s", job.entry["id"], exc_info=outcome
                )
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                recorded_metadata = True

    # Resolved once per level for every _safe_local_dest call below, rather
    # than once per file on the event loop.
    resolved_dest_dir = dest_dir.resolve()

    # Only dry_run ever reads `actions` (see the result-assembly comment below), so
    # a real run skips building it entirely rather than paying the cost of a plan
    # entry per file only to discard the whole list (#521).
    if dry_run:
        for step in plan:
            actions.append(
                {
                    "name": f"{rel_prefix}{step.name}",
                    "action": step.action,
                    "reason": step.reason,
                }
            )

    total_bytes = 0

    # dry_run leaves uploaded/downloaded/skipped/conflicts/failed empty rather than
    # duplicating each name (plus a now-redundant bare action label) into a flat
    # list alongside its already-complete entry in `actions` — that duplication is
    # what pushed a moderately-sized folder's dry-run response over the response
    # size cap (#512) despite `actions` alone (name + action + reason for every
    # item considered) already being a complete, non-redundant picture of the plan.
    if not dry_run:

        async def _run_one(step: _SyncStep) -> dict[str, Any]:
            name = step.name
            action = step.action

            if action == "skip":
                return {"kind": "skip", "name": name}

            if action == "conflict":
                return {"kind": "conflict", "name": name}

            if action == "collision":
                # No API call was ever attempted for this name — it was excluded
                # from drive_map entirely once the collision was detected. A real
                # run reports it as a genuine failure (unlike the dry_run preview
                # above), since nothing was synced and the ambiguity needs a
                # human to resolve it.
                return {"kind": "collision_fail", "name": name, "error": step.reason}

            if action == "unsafe_name":
                return {"kind": "unsafe_name_fail", "name": name, "error": step.reason}

            if action == "local_read_fail":
                # The local file became unreadable (deleted, permission-denied, a
                # special file) between the directory scan and the plan's stat or
                # use_checksum's hash read — surfaced as a clean failure for this
                # one name rather than propagating out of the whole call.
                return {"kind": "local_read_fail", "name": name, "error": step.reason}

            if action == "drive_read_fail":
                return {"kind": "drive_read_fail", "name": name, "error": step.reason}

            if action == "upload":
                p = local_map[name]
                # Matching (drive_map, above) now recognizes an already-converted Doc
                # regardless of whether this call passes convert_markdown — so the
                # reimport mime for an *existing* match must follow the same rule:
                # once matched to a Doc that's already the converted type, treat this
                # upload as a conversion reimport even if convert_markdown is False
                # this call, or a plain-text re-upload would silently re-import into
                # (or fail against) a file that Drive still considers a Google Doc.
                is_existing_converted = name in drive_map and _is_converted_md_entry(
                    drive_map[name]
                )
                convert_this = (convert_markdown or is_existing_converted) and (
                    p.suffix.lower() == ".md"
                )
                # Only meaningful (and only read below) when convert_this is True;
                # declared here so every later `if convert_this:`-guarded read is
                # provably bound without looking up _CONVERT_MIME[".md"] for every
                # non-.md upload regardless of extension (#421 finding #4).
                convert_target_mime: str | None = None
                if convert_this:
                    mime, convert_target_mime = _CONVERT_MIME[".md"]
                else:
                    mime, _ = mimetypes.guess_type(str(p))
                    mime = mime or "application/octet-stream"
                try:
                    # Inside the try: the file can vanish or become unreadable
                    # between the scan and here, and that must land as this
                    # item's upload_fail, not escape the gather (PR #817 QA).
                    lmtime = _local_mtime_dt(p)
                    lmtime_str = _drive_time_str(lmtime)
                    media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
                    if name in drive_map:
                        existing = drive_map[name]
                        fid = existing["id"]
                        if convert_this and existing["mimeType"] != convert_target_mime:
                            # This .md was previously synced with convert_markdown=False
                            # and landed as a plain Drive file. Drive's API has no
                            # supported way to convert an existing file's type via
                            # update() — only create() honors import conversion — so
                            # silently re-uploading here would just overwrite the plain
                            # file's raw content without ever promoting it to a Doc
                            # (#414 QA review, finding #3). Surface this explicitly
                            # instead of doing something that looks like it worked.
                            return {
                                "kind": "upload_fail",
                                "name": name,
                                "error": (
                                    f"'{name}' already exists in Drive as a plain file, "
                                    "not a converted Doc — convert_markdown cannot promote "
                                    "an existing file's type; delete it in Drive and "
                                    "re-sync to convert"
                                ),
                            }
                        # No mimeType here: the existing file is already the
                        # Google Doc convert_this implies, re-uploading text/markdown
                        # content re-imports it in place without changing its type.
                        update_body: dict[str, Any] = {"modifiedTime": lmtime_str}
                        if convert_this:
                            # #814: the Doc's latest revision from just before
                            # this re-import is the baseline the next sync finds
                            # the import after. Read fresh here, before the
                            # update(), so it can't race the import itself. A
                            # failed read fails this upload before anything
                            # changed. A legacy Doc gains the properties here.
                            revisions = await _list_revisions(drive_service, fid)
                            latest = revisions[-1]["id"] if revisions else None
                            planned = planned_latest_revision.get(name)
                            if planned is not None and latest != planned:
                                # Edited in Drive after this sync planned the
                                # upload. Uploading now would overwrite that
                                # edit and absorb it into the baseline (PR
                                # #854 QA round 1); the next sync reports it.
                                logger.debug(
                                    "Not uploading %s%s: Drive revision moved from %s to %s "
                                    "since planning",
                                    rel_prefix,
                                    name,
                                    planned,
                                    latest,
                                )
                                return {"kind": "conflict", "name": name}
                            update_body["properties"] = _converted_md_upload_properties(
                                lmtime, reupload=True, baseline_rev=latest
                            )
                        await execute_in_thread(
                            drive_service.files()
                            .update(
                                fileId=fid,
                                body=update_body,
                                media_body=media,
                                supportsAllDrives=True,
                                fields="id",
                            )
                            .execute,
                            drive_service,
                        )
                        synced_id = fid
                        logger.debug("Synced (update) %s%s → Drive", rel_prefix, name)
                    else:
                        body: dict[str, Any] = {
                            "name": name,
                            "parents": [drive_folder_id],
                            "modifiedTime": lmtime_str,
                        }
                        if convert_this:
                            body["mimeType"] = convert_target_mime
                            # Via _convert_properties, never the raw name as a
                            # property value: Drive rejects a key + value over
                            # 124 bytes with 403 propertyLengthLimitExceeded
                            # *after* creating the file, so a long .md name used
                            # to leave another untracked Doc behind on every
                            # run (#805). The source mtime is #814's local-side
                            # reference; a new Doc needs no baseline revision.
                            body["properties"] = {
                                **_convert_properties(name),
                                **_converted_md_upload_properties(lmtime),
                            }
                        created = await execute_in_thread(
                            drive_service.files()
                            .create(
                                body=body,
                                media_body=media,
                                supportsAllDrives=True,
                                fields="id",
                            )
                            .execute,
                            drive_service,
                        )
                        if convert_this:
                            # Cosmetic since #814: this Doc's change detection
                            # runs off the properties above, not modifiedTime.
                            # See _restamp_modified_time.
                            restamp_failure = await _restamp_modified_time(
                                drive_service, created["id"], lmtime_str
                            )
                            if restamp_failure is not None:
                                return {"kind": "upload_fail", "name": name, **restamp_failure}
                        synced_id = created["id"]
                        logger.debug("Synced (create) %s%s → Drive", rel_prefix, name)
                    try:
                        size = p.stat().st_size
                    except OSError as e:
                        # The Drive write above already succeeded — synced_id names a
                        # real Drive object even though this stat then failed (e.g.
                        # the local file was deleted/moved in the window between the
                        # write and this stat). Report fileId alongside the error so
                        # it isn't left untracked, mirroring the restamp-failure
                        # pattern above (#420/#650) for the same reason (#352 QA
                        # review, finding #1).
                        return {
                            "kind": "upload_fail",
                            "name": name,
                            "error": (
                                f"synced to Drive file {synced_id!r} but failed to stat "
                                f"the local file afterward: {e}"
                            ),
                            "fileId": synced_id,
                        }
                    return {"kind": "upload_ok", "name": name, "bytes": size}
                except Exception as e:
                    # Catch-all for the create()/update() calls above — a
                    # storageQuotaExceeded HttpError lands here too, so render it
                    # through _quota_error_detail rather than a bare str(e) that
                    # would leak Drive's raw error blob (#670).
                    return {
                        "kind": "upload_fail",
                        "name": name,
                        "error": _quota_error_detail(e),
                    }

            # action == "download"
            entry = drive_map[name]
            fid = entry["id"]
            is_workspace = _is_workspace_entry(entry)
            if is_workspace and _is_converted_md_entry(entry):
                # No reverse conversion exists (Google Doc -> markdown), regardless of
                # export_format — exporting one of these via export_format would write
                # e.g. binary PDF/DOCX export content into a file still named '.md'
                # instead of failing cleanly (#414 QA review, finding #1). The plan-
                # building loop above already keeps this action from being reached in
                # the normal case (queues 'conflict' instead of 'download'); this is a
                # defense-in-depth guard for the same invariant.
                return {
                    "kind": "download_fail",
                    "name": name,
                    "error": (
                        f"Cannot download a convert_markdown Doc: {_NO_REVERSE_CONVERSION_CLAUSE} "
                        "— edit the local .md file and re-sync to update Drive"
                    ),
                }
            if is_workspace and not export_format:
                # Unreachable in practice: a plain Workspace file with no
                # export_format never enters drive_map (see the build loop above),
                # and a convert_markdown twin is already handled above regardless of
                # export_format. Kept as a defensive fallback rather than relying on
                # that invariant never changing — surfaces a clean error instead of
                # the KeyError _EXPORT_MIME[None] would raise if it ever became
                # reachable.
                return {
                    "kind": "download_fail",
                    "name": name,
                    "error": (
                        "Cannot download native Google Doc without export_format "
                        "(convert_markdown has no reverse conversion)"
                    ),
                }
            try:
                # The plan already routed unsafe names to 'unsafe_name'; this is
                # the shared backstop, and a refusal lands as download_fail.
                dest_file = _safe_local_dest(dest_dir, name, resolved_dest_dir)
                # Mirror what the upload branch above does in reverse: set the
                # local file's mtime to Drive's modifiedTime so the round trip
                # stays within _SYNC_MTIME_TOLERANCE on the next sync. Without
                # this the local mtime is "now" (write time), which is always
                # later than Drive's original timestamp — the next sync sees the
                # file as locally newer and re-uploads it, indefinitely (#346).
                # _write_atomically stamps it before the rename, so a failed
                # download never leaves a "newer" partial in place (#844).
                drive_ts = _drive_mtime(entry).timestamp()
                if is_workspace:
                    target_mime = _EXPORT_MIME[export_format][0]
                    content = await execute_in_thread(
                        drive_service.files().export(fileId=fid, mimeType=target_mime).execute,
                        drive_service,
                    )
                    if not isinstance(content, bytes):
                        content = content.encode("utf-8")
                    await asyncio.to_thread(
                        _write_atomically, dest_file, lambda fh, c=content: fh.write(c), drive_ts
                    )
                else:

                    def _download_to_completion(fid=fid, dest_file=dest_file) -> None:
                        request = drive_service.files().get_media(
                            fileId=fid, supportsAllDrives=True
                        )
                        request.http = thread_http(drive_service)

                        def _stream(fh: BinaryIO) -> None:
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()

                        _write_atomically(dest_file, _stream, drive_ts)

                    await asyncio.to_thread(_download_to_completion)
                size = dest_file.stat().st_size
                logger.debug("Synced (download) Drive → %s%s (%d bytes)", rel_prefix, name, size)
                return {"kind": "download_ok", "name": name, "bytes": size}
            except Exception as e:
                return {"kind": "download_fail", "name": name, "error": str(e)}

        async def _run_one_with_progress(step: _SyncStep) -> dict[str, Any]:
            result = await _run_one(step)
            # Report per-item, not after the whole gather resolves — the gather
            # blocks until every concurrent transfer at this level finishes, so
            # reporting afterward would deliver a single silent burst instead of
            # live progress during the wait (the actual complaint in #316).
            if result["kind"] in ("upload_ok", "upload_fail", "download_ok", "download_fail"):
                progress_count[0] += 1
                # progress stays file-count-based with no total (recursive descent
                # means the overall file count isn't known upfront) — bytes
                # transferred so far are supplementary context in the message only
                # (#352). sync_folder never has a reliable upfront byte total
                # (unlike download_folder), so total is always None here.
                bytes_note = ""
                if "bytes" in result:
                    progress_bytes[0] += result["bytes"]
                    bytes_note = _format_bytes_note(progress_bytes[0], None)
                try:
                    await ctx.report_progress(
                        progress_count[0],
                        None,
                        f"{rel_prefix}{result['name']}: {result['kind']}{bytes_note}",
                    )
                except Exception:
                    # The transfer already succeeded or failed on its own terms —
                    # a broken notification channel (e.g. a dropped session) must
                    # not overwrite that outcome with a spurious failure. PR #351
                    # review: this was previously unguarded and a report_progress
                    # exception here would propagate out, turning an already-
                    # successful transfer into a "failed" item at the gather below.
                    logger.debug(
                        "report_progress failed for %s%s", rel_prefix, result["name"], exc_info=True
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

        level_changed = recorded_metadata
        for step, o in zip(plan, raw, strict=True):
            rel_name = f"{rel_prefix}{step.name}"
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
            else:  # upload/download/collision/unsafe_name/local_read/drive_read _fail
                entry = {"name": rel_name, "error": o["error"]}
                if "fileId" in o:
                    # Set only for the create()-succeeded-but-restamp-failed case
                    # (#420) — a genuine orphan now exists in Drive, so its ID
                    # rides along in the failed entry rather than being lost.
                    entry["fileId"] = o["fileId"]
                    # create() genuinely succeeded here even though the overall
                    # step is reported as upload_fail — the folder's contents
                    # changed and the cache must be invalidated the same as a
                    # real upload_ok, or a cached list_files/get_multiple_* call
                    # on this folder won't reflect the orphan (QA round 1, PR #645).
                    level_changed = True
                failed.append(entry)

        if level_changed:
            lc.drive_folder_cache.mark_dirty(drive_folder_id)

    if recursive:
        drive_folder_map = {f["name"]: f for f in drive_folders}
        drive_folder_counts: dict[str, int] = {}
        for f in drive_folders:
            drive_folder_counts[f["name"]] = drive_folder_counts.get(f["name"], 0) + 1
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

            # Same rule as the file plan above, checked before the join: a
            # folder name like '..' would otherwise be created, downloaded
            # into, or (bidirectional) uploaded from outside dest_dir. Routed
            # the way a file's plan step is: a skip, a dry_run action, or a
            # 'failed' entry on a real run.
            try:
                child_dest_dir = _safe_local_dest(dest_dir, name, resolved_dest_dir)
            except ValueError as e:
                step = _unsafe_name_step(
                    name,
                    str(e),
                    in_drive=in_drive,
                    in_local=in_local,
                    direction=direction,
                    drive_count=drive_folder_counts.get(name, 0),
                )
                if step.action == "skip":
                    folders_skipped.append(child_rel_prefix)
                elif dry_run:
                    actions.append(
                        {"name": child_rel_prefix, "action": step.action, "reason": step.reason}
                    )
                else:
                    failed.append({"name": child_rel_prefix, "error": step.reason})
                continue

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
                convert_markdown,
                use_checksum,
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
                progress_bytes,
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


@dataclass
class _DownloadCandidate:
    """One file download_folder has decided to transfer, replacing the
    previous 5-element positional tuple (#740) — a reorder or added field
    there had no type error to catch a call site that unpacked it
    positionally (_download_one(*c[:4]), c[1] for the name, sum(s for *_, s
    in candidates ...)). size is None for a Workspace export (the export's
    byte size isn't known until it completes) or when Drive simply didn't
    report one; every other candidate's size is known upfront from the same
    listing call, at no extra cost (#352)."""

    file_id: str
    name: str
    is_workspace: bool
    dest_file: Path
    size: int | None


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
            cap (see MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured
            default) — base64 encoding inflates raw file size by ~33%, so binary exports hit this
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
        is_google_workspace = _is_workspace_entry(metadata)

        if export_format == "raw" or not is_google_workspace:

            def _download_to_completion() -> bytes:
                request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
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
                            and Drive converts it (no formatting preserved). Uses the same
                            Drive native-import-conversion trick as upload_local_file's
                            convert param, simplified to always target a Doc since this
                            tool has no file extension to dispatch Sheets/Slides on.

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
            ).encode()
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
            # Same Drive native-import-conversion trick as _upload_local_file's
            # convert/_CONVERT_MIME path above (upload with the source mimeType,
            # override the destination mimeType to request conversion) — simpler
            # here since this tool only ever targets a Doc, never Sheets/Slides.
            # Shares _GOOGLE_DOC_MIME as the single source of truth for that
            # value so the two mechanisms can't drift apart on it (#412).
            file_body["mimeType"] = _GOOGLE_DOC_MIME

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
            if _is_quota_error(e):
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
        convert: bool = False,
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
                            already exists in the destination folder. With
                            convert=True, only an existing file already in the
                            target format counts, and one named after the
                            extension-stripped stem (Drive strips the extension on
                            some conversions, e.g. 'report.csv' -> 'report') counts
                            too — see Returns for how an unverified stem match is
                            reported.
            convert: If True, request Drive's native import conversion instead of
                     uploading as-is: .csv/.xlsx -> Google Sheets, .docx/.md/.html/.htm
                     -> Google Docs, .pptx -> Google Slides. Any other extension
                     returns an error. Default False (upload preserving original format).
                     A .md conversion is recognized by sync_folder's convert_markdown
                     matching too (same underlying mechanism, #211) — a later
                     sync_folder call on the same folder won't create a duplicate.
                     For .md specifically, create_doc_from_file is a local-pipeline
                     alternative: it parses the file and rebuilds it via Docs API
                     requests instead of Drive's importer, supporting more Markdown
                     features (tables, nested lists, task items, fenced code blocks)
                     at the cost of more API calls, versus this single-call
                     Drive-native import.

        Returns:
            fileId, name, webViewLink, and 'skipped' (True if skip_if_exists fired) on
            success, plus web_content_link (a direct download link) for a new
            non-converted upload. A skip on a stem match whose existing file carries no marker
            proving this tool converted it from this file (an earlier conversion
            predating the marker, or an unrelated file sharing the name) also sets
            'skipped_unverified': True plus a 'reason'; pass skip_if_exists=False to
            upload anyway. On failure, 'error' — plus a 'fileId' alongside it in the narrow
            case where convert=True and the file was actually created in Drive but a
            follow-up metadata call then failed (#420): that fileId names a real,
            already-created Drive file, not something to retry creating again.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot upload files to personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Check server://auth-status for your current auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service

        result = await _upload_local_file(
            drive_service, local_path, parent_folder_id, name, skip_if_exists, convert
        )
        # "fileId" alongside "error" means create() genuinely succeeded and only
        # the follow-up restamp failed (#420) — the folder's contents changed
        # even though this call reports an error, so the cache must still be
        # invalidated. Checked as its own case, not just "fileId" in result" —
        # a plain skip also carries the pre-existing file's fileId and must NOT
        # mark the cache dirty, since nothing changed (QA round 1, PR #645).
        orphaned = "error" in result and "fileId" in result
        if ("error" not in result and not result.get("skipped")) or orphaned:
            lc.drive_folder_cache.mark_dirty(parent_folder_id)
        return result

    @tool(annotations=ToolAnnotations(title="Upload Local Folder", destructiveHint=True))
    async def upload_local_folder(
        local_path: str,
        parent_folder_id: str,
        skip_if_exists: bool = True,
        skip_system_files: bool = True,
        convert: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Upload all files in a local directory (non-recursive) to a Google Drive folder.

        Args:
            local_path: Absolute path to the local directory.
            parent_folder_id: ID of the destination Drive folder.
            skip_if_exists: Skip files that already exist in the destination (default True).
            skip_system_files: Skip OS metadata files like .DS_Store (default True).
            convert: If True, request Drive's native import conversion for every file —
                     same mapping as upload_local_file's convert param: .csv/.xlsx ->
                     Google Sheets, .docx/.md/.html/.htm -> Google Docs, .pptx -> Google
                     Slides. A file whose extension isn't in that mapping is reported in
                     'failed' rather than uploaded as-is, matching upload_local_file's
                     own convert=True behavior for an unsupported extension. Default
                     False (upload every file preserving its original format).

        Returns:
            Summary with lists of 'uploaded', 'skipped', 'skipped_unverified', and
            'failed'. 'uploaded'/'skipped' are filenames. 'skipped_unverified' (only
            ever populated under convert=True) holds {name, matched_name, reason}
            entries for files skipped because an existing file in the target format is
            named after the local file's extension-stripped stem (Drive strips the
            extension on some conversions, e.g. 'report.csv' -> 'report') but carries
            no marker proving this tool created it from that file — it may be an
            earlier conversion predating the marker, or an unrelated file sharing the
            name. Nothing was uploaded for these; pass skip_if_exists=False to upload
            one anyway (upload_local_file applies the same check). Each
            'failed' entry is {name, error} plus a 'fileId' in the narrow convert=True
            case where the file was actually created in Drive but a follow-up metadata
            call then failed (#420) — see upload_local_file's own Returns docs.

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

        candidates = [
            p for p in folder.iterdir() if p.is_file() and not _is_partial_download(p.name)
        ]
        if skip_system_files:
            candidates = [p for p in candidates if p.name not in _SYSTEM_FILES]

        uploaded: list[str] = []
        skipped: list[str] = []
        skipped_unverified: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        any_created = False

        # dict[str, list[dict]], not a single entry per name — Drive allows more
        # than one file to share a name, and collapsing to one (the previous
        # shape) meant an already-converted duplicate could be masked by an
        # unrelated same-named raw file's mimeType winning the dict slot
        # depending on response ordering, silently reconverting or skipping the
        # wrong thing (#514, surfaced during PR #505's review of #411). Full
        # entries rather than just mimeTypes so the stem match below can read
        # each one's conversion marker (#769).
        existing_by_name: dict[str, list[dict]] = {}
        if skip_if_exists and candidates:
            # fields includes mimeType (not just name) so the convert=True case below
            # can tell an already-converted duplicate apart from a same-named file
            # still in its original format — mirrors _upload_local_file's own
            # convert-aware skip_if_exists check (issue #411).
            existing_resp = await execute_in_thread(
                drive_service.files()
                .list(
                    q=f"'{parent_folder_id}' in parents and trashed=false",
                    spaces="drive",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    # properties only under convert — nothing else reads the
                    # conversion marker (PR #800 QA round 1).
                    fields=(
                        "files(name, mimeType, properties)" if convert else "files(name, mimeType)"
                    ),
                    pageSize=1000,
                )
                .execute,
                drive_service,
            )
            for f in existing_resp.get("files", []):
                existing_by_name.setdefault(f["name"], []).append(f)

        for p in sorted(candidates):
            # Gated explicitly on skip_if_exists here, rather than relying on
            # existing_by_name being empty when it's False — a future change
            # that populates existing_by_name for an unrelated reason (e.g.
            # always fetching it for logging) would otherwise silently
            # re-enable skip behavior even when a caller explicitly passed
            # skip_if_exists=False (#514).
            if skip_if_exists:
                target_mime = _CONVERT_MIME.get(p.suffix.lower()) if convert else None
                if convert and target_mime is None:
                    # Unsupported extension under convert=True — this bulk
                    # shortcut must never skip here regardless of any
                    # same-named existing entry; fall through so
                    # _upload_local_file's own unsupported-extension check
                    # (which runs before its own existence check) reports the
                    # correct error into `failed` instead of this silently
                    # skipping it (the branch below funnels through
                    # _find_existing_upload, per #514 QA round 1, PR #767 —
                    # collapsing this case into that same call would have
                    # reintroduced the bug: convert_mime=None there means
                    # "not converting", not "converting but unsupported").
                    pass
                else:
                    # Drive's native import-conversion strips the source extension
                    # from some converted types' display name (confirmed live for
                    # CSV, TC-D215/TC-D243) but keeps it for others (.md,
                    # TC-D240) — check both the original name and the
                    # extension-stripped stem independently so either naming
                    # behavior, or both existing at once (a raw duplicate
                    # alongside an already-converted one), is recognized
                    # correctly (PR #505 review, issue #411). Only relevant
                    # under convert — the stem is the same as the name
                    # otherwise, so this is a no-op when not converting.
                    #
                    # The two lookups aren't equally trustworthy, though: a
                    # full-name match stays unconditional, but a stem match
                    # alone can't tell this tool's own extension-stripped
                    # conversion apart from an unrelated file that happens to
                    # share the stem and target mimeType (#769). So a stem
                    # match counts as ours only via the conversion marker; an
                    # unmarked one (e.g. converted before the marker existed)
                    # is still skipped — no duplicate re-uploads — but
                    # reported separately in skipped_unverified so the
                    # ambiguity is visible. Decided by _find_existing_upload,
                    # shared with _upload_local_file's own per-file check.
                    found = _find_existing_upload(
                        target_mime,
                        p.name,
                        existing_by_name.get(p.name, []),
                        existing_by_name.get(p.stem, []) if convert else [],
                    )
                    if found is not None:
                        match, verified = found
                        if verified:
                            skipped.append(p.name)
                        else:
                            skipped_unverified.append(
                                {
                                    "name": p.name,
                                    "matched_name": match["name"],
                                    "reason": _unverified_skip_reason(match["name"]),
                                }
                            )
                        continue

            # skip_if_exists=False here — existence was already decided above from the
            # single bulk list() call, so _upload_local_file doesn't need its own
            # per-file check (preserves the one-list-call-per-run contract, TC-D100).
            try:
                result = await _upload_local_file(
                    drive_service, str(p), parent_folder_id, skip_if_exists=False, convert=convert
                )
            except Exception as e:
                # _upload_local_file raises ValueError uncaught if the file no
                # longer exists at call time (e.g. deleted between the directory
                # scan above and this file's turn in the loop) — without this,
                # one missing file crashed the whole call, discarding every
                # already-accumulated uploaded/skipped/failed result instead of
                # recording a single failed entry (PR #505 review, issue #411).
                failed.append({"name": p.name, "error": str(e)})
                continue

            if "error" in result:
                entry = {"name": p.name, "error": result["error"]}
                if "fileId" in result:
                    # Set only for the create()-succeeded-but-restamp-failed case
                    # (#420) — a genuine orphan now exists in Drive, so its ID
                    # rides along in the failed entry rather than being lost.
                    entry["fileId"] = result["fileId"]
                    # create() genuinely succeeded here despite the overall
                    # failure — the folder changed, so this must still count
                    # for cache invalidation below even though it never reaches
                    # `uploaded` (QA round 1, PR #645).
                    any_created = True
                failed.append(entry)
            else:
                uploaded.append(p.name)
                any_created = True
                logger.debug("Uploaded %s", p.name)

        if any_created:
            lc.drive_folder_cache.mark_dirty(parent_folder_id)

        return {
            "uploaded": uploaded,
            "skipped": skipped,
            "skipped_unverified": skipped_unverified,
            "failed": failed,
        }

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
        filename (with an extension appended for exported Workspace files). A
        local_path ending in a path separator is always treated as a directory
        target, and is created (mkdir -p) if it doesn't exist yet. A Drive name
        that isn't a single ordinary filename (it contains '/' or '\\', is '.' or
        '..', etc.) is refused for a directory target with a ValueError, before
        anything is written; pass a full file path as local_path instead.

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

        dest, wants_dir = _validate_local_destination(local_path)

        metadata = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="name, mimeType", supportsAllDrives=True)
            .execute,
            drive_service,
        )
        drive_name = metadata["name"]
        is_workspace = _is_workspace_entry(metadata)

        if wants_dir or dest.is_dir():
            # The Drive name becomes the local filename only for a directory
            # target. Checked before the mkdir below, so a refused name raises
            # ValueError with nothing written.
            if is_workspace and export_format:
                ext = _EXPORT_MIME[export_format][1] if export_format in _EXPORT_MIME else ""
                local_name = drive_name + ext
            else:
                local_name = drive_name
            try:
                target = _safe_local_dest(dest, local_name)
            except ValueError as e:
                raise ValueError(
                    f"Drive file name {drive_name!r} can't be used as a local filename: "
                    f"{e}. Pass a full file path as local_path to choose the name."
                ) from None
            dest.mkdir(parents=True, exist_ok=True)
            dest = target

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
            await asyncio.to_thread(_write_atomically, dest, lambda fh: fh.write(content))
        else:

            def _download_to_completion() -> None:
                request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
                request.http = thread_http(drive_service)

                def _stream(fh: BinaryIO) -> None:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

                _write_atomically(dest, _stream)

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
        progress_unit: Literal["files", "bytes"] = "files",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Download all files in a Google Drive folder (non-recursive) to a local directory.

        For non-Google files the raw content is downloaded. Google Workspace files
        are skipped unless export_format is provided, in which case they are exported
        to that format. Subfolders are always skipped, regardless of export_format —
        this tool never descends into them. A file whose Drive name isn't a single
        ordinary filename (it contains '/' or '\\', is '.' or '..', etc.) is
        listed under 'failed' and not downloaded.

        Files transfer concurrently rather than one at a time. If the caller supplied
        a progressToken, a `notifications/progress` update is sent as each file
        finishes (e.g. "12/217: report.pdf: ok"). The message text always adds bytes
        transferred so far as supplementary context (#352), e.g.
        "12/217, 4823001/98234112 bytes: report.pdf: ok" when every candidate's
        size is known upfront, or "12/217, 4823001 bytes so far: report.pdf: ok"
        when one or more candidates (a Workspace export) has an unknown size.

        The structured `progress`/`total` fields default to file-count
        (progress_unit='files'), for consistency with every other progress-reporting
        tool in this file. Pass progress_unit='bytes' to report bytes transferred
        instead, for a client that renders a progress bar from the structured fields
        alone rather than parsing the message text (#741) — this only takes effect
        when every candidate's size is known upfront (see _DownloadCandidate's
        docstring); otherwise it silently falls back to file-count, since there's no
        reliable byte total to report against.

        Args:
            folder_id: The Google Drive folder ID.
            local_path: Local directory to download files into (created if needed).
            export_format: If provided, Google Workspace files are exported to this
                           format (e.g. 'pdf', 'docx'). See download_file for full list.
                           Without this, Workspace files are skipped.
            mime_type_filter: Only download files matching this MIME type.
            skip_if_exists: Skip files that already exist at the destination (default True).
            progress_unit: 'files' (default) or 'bytes' — which metric feeds the
                           structured progress/total fields reported via
                           notifications/progress. Falls back to 'files' when not
                           every candidate's size is known upfront.

        Returns:
            Summary with lists of 'downloaded', 'skipped', and 'failed' filenames,
            plus total 'size_bytes' downloaded.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        dest_dir = Path(local_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        resolved_dest_dir = dest_dir.resolve()

        query = f"'{folder_id}' in parents and trashed=false"
        if mime_type_filter:
            safe = _escape_drive_query_mime_type(mime_type_filter)
            query += f" and mimeType='{safe}'"

        results = await execute_in_thread(
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                fields="files(id, name, mimeType, size)",
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

        candidates: list[_DownloadCandidate] = []
        claimed_dest: set[str] = set()
        for f in results.get("files", []):
            fid = f["id"]
            fname = f["name"]
            fmime = f.get("mimeType", "")
            fsize = int(f["size"]) if f.get("size") is not None else None

            if fmime == "application/vnd.google-apps.folder":
                # Non-recursive: subfolders are never descended into or exported.
                skipped.append(fname)
                continue

            is_workspace = _is_workspace_entry(f)

            if is_workspace and not export_format:
                skipped.append(fname)
                continue

            if is_workspace:
                if export_format not in _EXPORT_MIME:
                    failed.append(
                        {"name": fname, "error": f"Unknown export_format '{export_format}'"}
                    )
                    continue
                local_name = fname + _EXPORT_MIME[export_format][1]
            else:
                local_name = fname
            try:
                dest_file = _safe_local_dest(dest_dir, local_name, resolved_dest_dir)
            except ValueError as e:
                # One failed entry, like the duplicate-name case below; the
                # rest of the folder still downloads.
                failed.append(
                    {"name": fname, "error": f"{fname!r} can't be used as a local filename: {e}"}
                )
                continue

            if skip_if_exists and dest_file.exists():
                skipped.append(dest_file.name)
                continue

            # Drive allows two files with the same name (distinct IDs) in one
            # folder; the local filesystem doesn't. Concurrent transfers below
            # would otherwise race to write the identical path — keep the first
            # candidate and record the rest as failed instead of silently
            # clobbering content or double-counting size_bytes (PR #351 review,
            # live-reproduced against a fixture folder with duplicate names).
            dest_key = str(dest_file)
            if dest_key in claimed_dest:
                failed.append(
                    {
                        "name": fname,
                        "error": (
                            f"duplicate filename: another file named '{dest_file.name}' "
                            "already claims this destination path — only the first is "
                            "downloaded"
                        ),
                    }
                )
                continue
            claimed_dest.add(dest_key)

            # size=None for a Workspace candidate — see _DownloadCandidate's docstring.
            candidates.append(
                _DownloadCandidate(
                    file_id=fid,
                    name=fname,
                    is_workspace=is_workspace,
                    dest_file=dest_file,
                    size=None if is_workspace else fsize,
                )
            )

        total = len(candidates)
        # List-box, not a bare int + nonlocal: matches _sync_level's
        # progress_count/progress_bytes idiom (#354) for one shared
        # convention in this file, though nonlocal was already safe here
        # (no await between read and write) — this is purely a style match.
        completed = [0]
        bytes_completed = [0]
        # Separate from bytes_completed (real bytes transferred, message-text-only,
        # success-only — see below): this one backs the structured progress field
        # when report_bytes is true, and must reach total_bytes_expected exactly
        # once every candidate has been attempted, success or fail, the same way
        # completed[0] reaches `total` unconditionally in file-count mode. Advancing
        # it by the candidate's own *declared* size on every outcome (not just on
        # success, unlike bytes_completed) is what guarantees that — a failed
        # candidate's size would otherwise stay baked into the denominator
        # (total_bytes_expected sums every candidate) while never being added to
        # the numerator, so the final call would report less than 100% even though
        # the operation is fully done (#741 QA review, finding #1).
        bytes_accounted = [0]
        # A reliable upfront total requires every candidate's size to be known
        # (see _DownloadCandidate's docstring for why one can be None) — with one
        # unknown, the message falls back to a running count with no denominator
        # rather than implying a precision it doesn't have.
        total_bytes_expected = sum(c.size for c in candidates if c.size is not None)
        bytes_total_known = all(c.size is not None for c in candidates)
        # #741: byte-based structured progress is only meaningful when there's a
        # reliable total to report against — silently fall back to file-count
        # rather than reporting a byte "total" that's actually just a running
        # count with no denominator.
        report_bytes = progress_unit == "bytes" and bytes_total_known

        async def _download_one(candidate: _DownloadCandidate) -> dict[str, Any]:
            try:
                if candidate.is_workspace:
                    target_mime = _EXPORT_MIME[export_format][0]
                    content = await execute_in_thread(
                        drive_service.files()
                        .export(fileId=candidate.file_id, mimeType=target_mime)
                        .execute,
                        drive_service,
                    )
                    if not isinstance(content, bytes):
                        content = content.encode("utf-8")
                    await asyncio.to_thread(
                        _write_atomically, candidate.dest_file, lambda fh: fh.write(content)
                    )
                else:

                    def _download_to_completion(
                        fid=candidate.file_id, dest_file=candidate.dest_file
                    ) -> None:
                        request = drive_service.files().get_media(
                            fileId=fid, supportsAllDrives=True
                        )
                        request.http = thread_http(drive_service)

                        def _stream(fh: BinaryIO) -> None:
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()

                        _write_atomically(dest_file, _stream)

                    await asyncio.to_thread(_download_to_completion)

                size = candidate.dest_file.stat().st_size
                logger.debug(
                    "Downloaded %s → %s (%d bytes)", candidate.file_id, candidate.dest_file, size
                )
                result: dict[str, Any] = {
                    "kind": "ok",
                    "name": candidate.dest_file.name,
                    "bytes": size,
                }
            except Exception as e:
                result = {"kind": "fail", "name": candidate.name, "error": str(e)}

            # Reported here, inside the per-item coroutine, so updates stream in as
            # each concurrent download finishes rather than arriving in one burst
            # after asyncio.gather resolves — see #316.
            completed[0] += 1
            if result["kind"] == "ok":
                bytes_completed[0] += result["bytes"]
            # bytes_accounted advances on every outcome (see its own comment above)
            # so byte-mode progress still reaches full completion when a candidate
            # fails; candidate.size is never None here when report_bytes is true
            # (bytes_total_known already guarantees it).
            bytes_accounted[0] += candidate.size or 0
            # progress/total stay file-count-based by default (see the docstring's
            # #352 note) — bytes transferred so far are supplementary context in the
            # message only. With progress_unit='bytes' (#741) the structured fields
            # below use byte totals instead; the message text is unaffected either way.
            bytes_note = _format_bytes_note(
                bytes_completed[0], total_bytes_expected if bytes_total_known else None
            )
            try:
                progress = bytes_accounted[0] if report_bytes else completed[0]
                progress_total = total_bytes_expected if report_bytes else total
                await ctx.report_progress(
                    progress,
                    progress_total,
                    f"{completed[0]}/{total}{bytes_note}: {result['name']}: {result['kind']}",
                )
            except Exception:
                # The download already succeeded or failed on its own terms — a
                # broken notification channel must not overwrite that outcome.
                # PR #351 review: this was previously unguarded and a
                # report_progress exception here would propagate out, turning an
                # already-successful download into a "failed" item at the
                # gather below.
                logger.debug("report_progress failed for %s", result["name"], exc_info=True)
            return result

        # Concurrent fan-out, same pattern as _sync_level's _run_one: previously this
        # was a sequential `for` loop awaiting one transfer at a time (#316), which
        # measured 1.04s/file and scaled linearly with folder size.
        raw = await asyncio.gather(*(_download_one(c) for c in candidates), return_exceptions=True)

        for c, o in zip(candidates, raw, strict=True):
            if isinstance(o, BaseException):
                failed.append({"name": c.name, "error": str(o)})
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
        convert_markdown: bool = False,
        use_checksum: bool = False,
        skip_system_files: bool = True,
        dry_run: bool = False,
        recursive: bool = False,
        result_local_path: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Sync files between a Google Drive folder and a local directory.

        ## Sync logic

        Files are matched by name. For Google Workspace files (Docs, Sheets, Slides),
        the export extension is appended to form the local name — e.g. a Doc called
        'Notes' with export_format='docx' matches the local file 'Notes.docx'.
        Workspace files with no export_format are skipped entirely — except a Doc
        produced by convert_markdown, which keeps its '.md' name and matches its
        local .md file directly regardless of export_format (see convert_markdown
        below).

        For each matched name the action is decided as follows:

          Drive only  + direction includes download  → download
          Drive only  + direction is 'upload'        → skip
          Local only  + direction includes upload    → upload
          Local only  + direction is 'download'      → skip
          Both sides, mtimes within 5 s tolerance    → skip (already in sync)
          Both sides, mtimes match but byte sizes differ → conflict (content
                                                      diverged; recency unknown — any direction)
          Both sides, mtimes and sizes match but md5 differs → conflict (use_checksum=True
                                                      only; recency unknown — any direction)
          Both sides, local newer by > 5 s           → upload  (if direction includes upload)
          Both sides, Drive newer by > 5 s           → download (if direction includes download)
          Both sides, conflict (direction mismatch)  → skip, listed under 'conflicts'

        A name that isn't a single ordinary filename (it contains '/' or '\\', is
        '.' or '..', etc.), for a file or a subfolder on either side, is never
        synced: it's listed under 'failed' (action 'unsafe_name' in a dry_run),
        unless it exists only on the side this direction wouldn't act on, where
        it's skipped as usual.

        Modified times are compared in UTC. When a file is uploaded, its Drive
        modifiedTime is set to the local file's mtime so future syncs stay accurate.
        A convert_markdown Doc is the exception: its changes are tracked through
        properties and revision history instead (see convert_markdown below).

        The "mtimes match but byte sizes differ" row (#659) exists because equal
        mtimes don't guarantee equal content: a rename-in-place (`mv` keeps the
        mtime) leaves a name pointing at different bytes with an unchanged
        timestamp, which the plain equal-mtime skip would hide permanently.
        Drive's `size` is already in the folder listing, so this check is nearly
        free (one stat) and runs during dry_run too. It is always a 'conflict',
        never an auto-transfer: the mtimes agree, so which side is newer is
        unknown, and a directional sync already reports 'conflict' rather than
        overwrite a target it *can* tell is newer. It only applies to non-Workspace
        files (Workspace and convert_markdown files report no `size`). A same-size
        content edit that also preserves mtime is still reported as "in sync"
        unless use_checksum=True (below) — hashing every within-tolerance pair by
        default would make every sync read every file.

        When use_checksum=True, every name present on both sides is checked for a
        content match (local md5 vs. Drive's md5Checksum) before the direction
        decision above runs — a match is always treated as in sync regardless of
        how far apart the modifiedTimes are. This includes a pair whose mtimes
        are within tolerance and whose sizes match: a checksum mismatch there
        means a same-size, mtime-preserving content change, reported as a
        'conflict' for every direction (recency unknown, same as the byte-size
        row above). A within-tolerance pair whose sizes already differ is
        reported by the byte-size row without being read. Every such file is
        read, so this costs a full read of the folder's matched content on
        every sync (run concurrently, a few files at a time). Skipped during
        dry_run, so this never turns a cheap preview into a full read of every
        file — an affected step's reason then ends in "(checksum not verified in
        dry_run)", since the real run may decide differently. This catches cases mtime alone gets wrong: content uploaded via
        upload_local_file reading as "Drive newer" and getting needlessly
        re-downloaded (upload_local_file now also stamps modifiedTime to match the
        local file directly, so this mainly helps for other causes of drift, e.g. a
        local overwrite that happens to preserve mtime), or a local regeneration
        that changes mtime without changing bytes reading as "local newer." A local
        read failure for one file (deleted, permission-denied, etc.) reports that
        name under 'failed' rather than aborting the whole call. Only
        applies to files with a real md5Checksum — Google Workspace files (Docs,
        Sheets, Slides) and convert_markdown Docs have none and always fall back
        to the mtime comparison. A checksum mismatch doesn't change anything by
        itself when the mtimes disagree; it just falls through to the same
        mtime-based direction decision used when use_checksum=False.

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

        When dry_run=True no files or folders are created/transferred. 'uploaded',
        'downloaded', 'skipped', 'conflicts', and 'failed' are always empty in this
        mode (nothing was materialized to report there) — the response instead
        includes an 'actions' list with {name, action, reason} for every file
        considered at every level visited; this is the complete, non-redundant
        picture of what a real run would do and why, without duplicating each name
        into a second, action-labelless list alongside it (#512).

        ## Progress

        File transfers within each level run concurrently rather than one at a time.
        If the caller supplied a progressToken, a `notifications/progress` update is
        sent as each individual upload/download completes (skips and conflicts don't
        emit updates — they're free, not transfers). No update is sent during dry_run,
        since nothing is transferred. `progress` stays a running file-transfer count
        with no `total` (recursive descent means the overall file count isn't known
        upfront) — the message text adds a running total of bytes transferred so far
        as supplementary context (#352), e.g. "notes.txt: upload_ok, 40231 bytes
        so far".

        Args:
            folder_id: Google Drive folder ID to sync against.
            local_path: Local directory path to sync against (created if needed).
            direction: 'bidirectional', 'upload', or 'download'.
            export_format: Required to include Workspace files in the sync. They are
                           exported/compared using this format (e.g. 'pdf', 'docx', 'csv').
            convert_markdown: If True, local .md files are uploaded via Drive's native
                           import conversion, landing as Google Docs (still named
                           '<name>.md') instead of raw text files — same mechanism as
                           upload_local_file's convert param (#188), and a Doc created
                           either way is recognized by this matching. The converted Doc
                           is matched back to its local .md file directly on later
                           syncs (independent of export_format, and independent of
                           whether a later sync passes convert_markdown=True again),
                           so edits round-trip normally instead of re-uploading a
                           duplicate every run. Matching is scoped to Docs carrying an
                           internal Drive property this tool sets on conversion — a
                           pre-existing Doc a human happened to name '<name>.md' is
                           never mistaken for one and never has its content
                           overwritten. There is no reverse conversion: if the Doc is
                           edited in Drive, or has no local counterpart at all, that
                           entry is reported under 'conflicts' instead of downloaded.
                           A converted Doc's changes aren't judged from modifiedTime,
                           which Drive updates minutes behind a Docs edit: the local
                           .md is compared with the mtime recorded at its last upload,
                           and a Drive edit is detected from the Doc's revision history
                           (one extra metadata call per converted Doc per sync). A Doc
                           edited in Drive is a conflict even when the local .md changed
                           too, rather than being overwritten by the upload. A local
                           change made within seconds of the previous upload waits for
                           a later sync. A Doc converted by an older version of this
                           tool keeps the modifiedTime comparison until it's next
                           re-uploaded.
                           A .md previously synced with convert_markdown=False can't be
                           promoted to a Doc in place — that entry is reported under
                           'failed' with an explanatory message; delete it in Drive and
                           re-sync to convert it.
            use_checksum: If True, treat a name present on both sides as in sync
                           whenever its local md5 hash matches Drive's md5Checksum,
                           regardless of modifiedTime drift, and report a
                           within-tolerance pair whose hashes differ as a conflict
                           (see above). Reads every both-sides file with a Drive
                           md5Checksum. Default False (mtime + size comparison).
            skip_system_files: Skip .DS_Store and similar OS metadata files (default True).
            dry_run: If True, plan the sync but transfer nothing.
            recursive: If True, also sync matching subfolders at any depth (see above).
                       Defaults to False — a single call only covers the top-level folder.
            result_local_path: If set, write the result to this file/directory path
                       instead of returning it inline, unconditionally bypassing the
                       response-size safety cap below — useful for a large recursive
                       sync (dry_run or real) whose result would otherwise exceed it.
                       Returns a manifest ({local_path, bytes_written, folder_id,
                       dry_run}) instead of the sync result itself. Must not be
                       `local_path` or a path inside it — `local_path` is scanned as
                       sync input on every call, so a result manifest written there
                       would show up as a new local-only file on the next sync (and
                       get uploaded to Drive on a real run); raises ValueError if it
                       resolves inside `local_path`.

        Returns:
            uploaded, downloaded, skipped, conflicts, failed lists (relative paths —
            just the filename at the top level, 'subdir/name' for nested matches when
            recursive descends; always empty when dry_run=True, see the dry_run
            section above), 'folders_skipped' (relative subfolder paths not entered —
            always empty when recursive=False), size_bytes transferred, dry_run flag,
            and — when dry_run=True — an 'actions' list with {name, action, reason}
            for every file considered at every level visited. Each 'failed' entry is
            {name, error} plus a 'fileId' in the narrow convert_markdown case where
            create() actually succeeded in Drive but a follow-up metadata call then
            failed (#420) — that fileId names a real, already-created Drive file, not
            something the next sync will retry creating from scratch. Raises
            ValueError if the response exceeds a safety cap (see
            MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured
            default, or pass result_local_path to bypass it and write to disk
            instead) — a recursive sync/preview over many files is the most likely
            way to hit this.
        """
        if direction not in ("bidirectional", "upload", "download"):
            return {
                "error": f"Invalid direction '{direction}'. "
                "Use 'upload', 'download', or 'bidirectional'."
            }
        if export_format and export_format not in _EXPORT_MIME:
            return {
                "error": f"Unknown export_format '{export_format}'. "
                f"Valid: {', '.join(_EXPORT_MIME)}"
            }

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        dest_dir = Path(local_path)
        dest_dir.mkdir(parents=True, exist_ok=True)

        if result_local_path:
            # local_path is also a live input directory this same call scans — unlike
            # every other capped tool's local_path (a pure output destination), writing
            # the result manifest inside it would make the manifest file itself show up
            # as a new local-only entry on the very next sync, and get uploaded to Drive
            # on a real (non-dry_run) run (QA finding, PR #518 review, live-reproduced).
            result_path_resolved = Path(result_local_path).resolve()
            dest_dir_resolved = dest_dir.resolve()
            if (
                result_path_resolved == dest_dir_resolved
                or dest_dir_resolved in result_path_resolved.parents
            ):
                raise ValueError(
                    f"result_local_path ('{result_local_path}') must not be local_path "
                    f"('{local_path}') or a path inside it — local_path is scanned as "
                    "sync input, so writing the result manifest there would make it show "
                    "up as a new local-only file on the next sync. Use a separate directory."
                )

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
            convert_markdown,
            use_checksum,
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

        if result_local_path:
            return await write_capped_result_to_disk(
                result,
                result_local_path,
                default_filename=f"{folder_id}_sync_result.json",
                manifest_extra={"folder_id": folder_id, "dry_run": dry_run},
            )

        # recursive=True removes the previous implicit bound (one folder's direct
        # children) on every list here, especially 'actions' during a dry run — the
        # decision doc's own reproduction case (22 subfolders / ~225 files) is a
        # realistic scale to hit the cap.
        enforce_response_size_cap(
            result,
            tool_name="sync_folder",
            hint="Recursive syncs can produce very large result lists. Narrow "
            "folder_id, direction, or recursive scope, or ",
            local_path_param="result_local_path",
        )
        return result
