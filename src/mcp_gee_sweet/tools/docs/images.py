"""Inline-image tools (insert_inline_image, insert_local_images) plus the size
validation, downscaling, and error-message clarification (#400) shared by every
insertInlineImage call site in this package, including markdown/HTML image embedding
in content.py's create_doc/write_doc_content (via _resolve_image_source, which
depends on these same six helpers just as heavily as the two tools below do — not
the reason for the merge). The two tools were merged into this module (#372) rather
than split into a differently-named one: issue #372 predates #400's creation of this
file, and by the time it was picked up, images.py already existed here for the
size-validation helpers — merging avoided colliding with a newly-invented module name.

Google Docs' insertInlineImage request rejects any image over ~25 megapixels or
~50MB with a bare "The provided image is too large" HttpError that names neither the
actual limit nor the image's own size — confirmed against
https://developers.google.com/workspace/docs/api/how-tos/images, which documents both
ceilings (PNG/JPEG/GIF only). The validation/downscaling helpers here give every
insertInlineImage call site a shared way to self-diagnose an oversized image *before*
ever calling the API, and — opt-in — automatically fix it by downscaling. Both limits
are checked independently (issue #562) — a low-compressibility image (e.g. noise data)
can be well under the megapixel ceiling while still over the byte-size one, so neither
check alone is sufficient. See docs/decisions/decision-pillow-image-dependency.md for
why Pillow was added as a dependency to do this, and the scope boundary that decision
implies.

Validation/downscaling only apply where a call site already has (or already fetches)
the image's own bytes or Drive-reported dimensions without new networking: a local file
path, or an already-uploaded Drive file (drive_file_id / "drive:" reference). A bare
http(s):// URI is deliberately out of scope — fetching arbitrary external content just
to validate it, or re-hosting a downscaled copy somewhere Google can fetch it from, is a
bigger behavior change than this fix warrants; see rewrite_too_large_error for the
fallback that still applies there.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import anyio.lowlevel
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from PIL import Image

from ...auth import after_abandoned_calls, execute_in_thread, thread_http
from ...local_files import LocalFileAccessError, check_read
from ..drive import _quota_error_text
from ..drive.transfer import _upload_local_file
from ..http_errors import is_storage_quota_error
from .indices import _collect_doc_paragraphs, utf16_len

logger = logging.getLogger(__name__)

# Google Docs' documented inline-image ceiling, in decimal megapixels (1,000,000 px —
# matching how Google's own docs express it, not a binary 1024*1024 "MP").
MAX_INLINE_IMAGE_MEGAPIXELS = 25
MAX_INLINE_IMAGE_PIXELS = MAX_INLINE_IMAGE_MEGAPIXELS * 1_000_000

# Google Docs' documented inline-image file-size ceiling, in decimal megabytes —
# same decimal convention as the megapixel constant above, not binary 1024*1024.
MAX_INLINE_IMAGE_MEGABYTES = 50
MAX_INLINE_IMAGE_BYTES = MAX_INLINE_IMAGE_MEGABYTES * 1_000_000

_DOCS_IMAGE_LIMITS_URL = "https://developers.google.com/workspace/docs/api/how-tos/images"

_FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif"}

# Every reason downscale_image_bytes can decline for an image already known to be
# oversized. "Too large to decode safely": Pillow's decompression-bomb guard refuses a
# full decode above ~179 megapixels, and downscaling needs one. "Still over the size
# limit": the bounded shrink loop ran out of attempts (#581).
_CANNOT_DOWNSCALE_REASONS = (
    "unreadable or corrupt image, animated, too large to decode safely, "
    "or still over the file-size limit after shrinking"
)


def _decode(data: bytes) -> Image.Image | None:
    """Best-effort full decode, pixel data included — returns None (not an exception)
    for anything Pillow can't read, since validation here is an additive convenience,
    not a gate: an undecodable file still gets its real answer straight from the Docs
    API, same as before #400. Only downscale_image_bytes needs the pixels; a size check
    uses _read_dimensions instead."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception:
        return None


def _read_dimensions(path: str | Path) -> tuple[int, int] | None:
    """Best-effort (width, height) from the image header alone, without decoding any
    pixel data (#560). None for content Pillow can't identify as an image, same as
    _decode.

    Opening the file happens outside the best-effort guard, so an unreadable file
    (missing, permission-denied) raises OSError to the caller instead of passing as
    "not an image" (PR #801 QA round 1).

    For the formats Docs accepts (PNG/JPEG/GIF), the format plugin is constructed
    directly rather than through Image.open. Image.open runs Pillow's decompression-
    bomb check on the header's claimed size and raises above ~179 megapixels. That
    guard protects a pixel decode, which never happens here. Through Image.open, the
    very largest images would read as "not an image" and skip the size limit
    entirely (PR #801 QA round 1). Other formats fall back to Image.open; Docs rejects
    them anyway."""
    with open(path, "rb") as fp:
        try:
            prefix = fp.read(16)
            Image.preinit()
            for fmt in ("PNG", "JPEG", "GIF"):
                factory, accept = Image.OPEN[fmt]
                result = accept(prefix) if accept else True
                if result and not isinstance(result, str):
                    fp.seek(0)
                    return factory(fp, str(path)).size
            fp.seek(0)
            with Image.open(fp) as img:
                return img.size
        except Exception:
            return None


def too_large_message(width: int, height: int) -> str:
    """Error text for an image whose pixel dimensions exceed the limit. Shared by the
    metadata-only check (Drive already reports width/height, no download needed) and
    the decode-based check below, so both paths give the caller the identical,
    actionable message."""
    megapixels = (width * height) / 1_000_000
    return (
        f"Image is {width}x{height} ({megapixels:.1f} megapixels), which exceeds "
        f"Google Docs' inline-image limit of {MAX_INLINE_IMAGE_MEGAPIXELS} megapixels "
        f"({_DOCS_IMAGE_LIMITS_URL}). Resize it before inserting, or pass "
        "auto_downscale=True to have it resized automatically."
    )


def check_dimensions(width: int, height: int) -> dict[str, Any] | None:
    """Returns {"error": ...} if width x height exceeds the limit, else None."""
    if width * height > MAX_INLINE_IMAGE_PIXELS:
        return {"error": too_large_message(width, height)}
    return None


def too_large_bytes_message(size_bytes: int) -> str:
    """Error text for an image whose file size exceeds Google's documented 50MB
    inline-image ceiling — a check independent of check_dimensions/too_large_message
    above, since a low-compressibility image (e.g. noise data) can be well under the
    megapixel limit while still exceeding the byte-size one (#562)."""
    megabytes = size_bytes / 1_000_000
    return (
        f"Image is {megabytes:.1f}MB, which exceeds Google Docs' inline-image "
        f"file-size limit of {MAX_INLINE_IMAGE_MEGABYTES}MB ({_DOCS_IMAGE_LIMITS_URL}). "
        "Resize it before inserting, or pass auto_downscale=True to have it resized "
        "automatically."
    )


def check_file_size(size_bytes: int) -> dict[str, Any] | None:
    """Returns {"error": ...} if size_bytes exceeds the file-size limit, else None."""
    if size_bytes > MAX_INLINE_IMAGE_BYTES:
        return {"error": too_large_bytes_message(size_bytes)}
    return None


def check_image_file(path: str | Path) -> dict[str, Any] | None:
    """Checks a local image file against the megapixel limit, if Pillow can identify
    it, then the file-size limit (always, regardless of whether it's a recognizable
    image). Dimensions come first to match check_drive_image_metadata, so an image
    over both limits gets the same error either way it's passed in. Returns None (no
    error, not a skip signal the caller needs to distinguish) when the file isn't a
    recognizable image and is within the size limit.

    Reads only stat() and the image header, never the whole file (#560): an
    under-limit image, the common case, is then read from disk exactly once, by the
    upload itself. Blocking I/O, so call it via asyncio.to_thread. Raises OSError if
    the file can't be opened or stat'd."""
    dimensions = _read_dimensions(path)
    if dimensions is not None:
        dimension_error = check_dimensions(*dimensions)
        if dimension_error is not None:
            return dimension_error
    return check_file_size(Path(path).stat().st_size)


def downscale_image_bytes(data: bytes) -> tuple[bytes, str] | None:
    """Resize image `data` to fit both the megapixel and file-size limits, preserving
    aspect ratio and format. Returns (resized_bytes, mime_type), or None if: the image
    can't be decoded; it's already within both limits (nothing to do — caller should
    keep using the original bytes/upload path); it's animated (Pillow's resize only
    touches the current frame, which would silently drop every other frame of an
    animated GIF — declining is safer than corrupting it); or the bounded shrink loop
    below still can't get it under the file-size limit (#581), so a caller never
    embeds still-oversized bytes as if the resize had worked.

    The byte-size limit can't be hit exactly on the first resize the way the
    megapixel one can: encoded size depends on compression, not just pixel count, so a
    single pixel-count-based scale is only an estimate for it. After an initial resize
    (scaled to satisfy whichever of the two limits needs the larger reduction), the
    result is re-encoded and, if still over the byte-size limit, shrunk further in a
    few bounded steps — needed for #562's own motivating case: a low-compressibility
    image that's already within the megapixel limit gets no scale-down from the
    megapixel math at all, so without this loop the byte-size limit would never
    actually be reached."""
    img = _decode(data)
    if img is None or getattr(img, "is_animated", False):
        return None
    width, height = img.size
    pixels = width * height
    if pixels <= MAX_INLINE_IMAGE_PIXELS and len(data) <= MAX_INLINE_IMAGE_BYTES:
        return None

    fmt = img.format or "PNG"

    def _encode(im: Image.Image) -> bytes:
        if fmt == "JPEG" and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format=fmt)
        return out.getvalue()

    scale = 1.0
    if pixels > MAX_INLINE_IMAGE_PIXELS:
        scale = min(scale, (MAX_INLINE_IMAGE_PIXELS / pixels) ** 0.5)
    if len(data) > MAX_INLINE_IMAGE_BYTES:
        scale = min(scale, (MAX_INLINE_IMAGE_BYTES / len(data)) ** 0.5)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    encoded = _encode(resized)

    attempts = 0
    while len(encoded) > MAX_INLINE_IMAGE_BYTES and attempts < 5:
        w, h = resized.size
        next_size = (max(1, int(w * 0.8)), max(1, int(h * 0.8)))
        if next_size == resized.size:
            break
        resized = resized.resize(next_size, Image.Resampling.LANCZOS)
        encoded = _encode(resized)
        attempts += 1

    if len(encoded) > MAX_INLINE_IMAGE_BYTES:
        return None
    return encoded, _FORMAT_MIME.get(fmt, "application/octet-stream")


def check_drive_image_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Checks a Drive file's own reported imageMediaMetadata dimensions and `size`
    field against the inline-image limits, without downloading the file — the
    metadata-only counterpart to check_image_file, shared by every call site that
    validates a drive_file_id/"drive:" source before deciding whether to embed it
    directly or downscale it first (issue #562's own consolidation of a pattern that
    used to be duplicated between insert_inline_image here and content.py's
    _resolve_image_source). Dimensions are checked first, matching
    downscale_image_bytes's own resize-by-pixels-first behavior. Returns the first
    violation found, or None if within both limits or the metadata doesn't report
    enough to check (e.g. a non-image binary with no imageMediaMetadata, or a
    width/height/`size` that isn't a number). Never raises: both call sites call it
    outside their try/except (#581)."""
    img_meta = metadata.get("imageMediaMetadata") or {}
    try:
        width, height = int(img_meta["width"]), int(img_meta["height"])
    except (KeyError, TypeError, ValueError):
        # Missing or malformed dimensions mean unknown; fall through to the size check.
        width = height = 0
    if width > 0 and height > 0:
        error = check_dimensions(width, height)
        if error is not None:
            return error
    try:
        size_bytes = int(metadata["size"])
    except (KeyError, TypeError, ValueError):
        # Drive sends `size` as a decimal string. Missing or malformed means unknown,
        # the same as missing dimensions: let the embed call be the judge.
        return None
    return check_file_size(size_bytes)


def rewrite_too_large_error(message: str) -> str:
    """Rewrites Google's own opaque insertInlineImage "too large" HttpError text
    (str(HttpError) — confirmed live and via issue #400's own repro to read
    '...Invalid requests[N].insertInlineImage: The provided image is too large.') to
    name the known cause, for call sites (a bare http(s):// uri) that can't
    pre-validate because they never fetch the image's own bytes. Returns the message
    unchanged for anything else, so an unrelated insertInlineImage failure (e.g. an
    unfetchable URL, #333) isn't misreported as a size problem.

    Deliberately limit-agnostic (#562 follow-up, PR #580 QA round 1): Google's error
    text doesn't say which of the two documented ceilings (megapixels or file size)
    was actually hit, and this call site never fetched the image's own bytes to check
    — naming only the megapixel limit, as this used to, gave actively misleading
    guidance ("check the image's pixel dimensions") for a byte-size-caused rejection."""
    if "insertInlineImage" in message and "too large" in message.lower():
        return (
            f"{message} This is very likely exceeding Google Docs' inline-image "
            f"limits of {MAX_INLINE_IMAGE_MEGAPIXELS} megapixels or "
            f"{MAX_INLINE_IMAGE_MEGABYTES}MB ({_DOCS_IMAGE_LIMITS_URL}) — resize it "
            "before retrying."
        )
    return message


async def share_image_file(
    drive_service,
    file_id: str,
    uri: str | None,
    existing_permission_ids: list[str] | None,
    *,
    created_here: bool,
) -> dict[str, Any]:
    """Shares a Drive file anyone:reader so the Docs backend can fetch it — it fetches
    inline images as an anonymous HTTP request regardless of the caller's own access
    (confirmed live in #332/#333). The one share step every uploaded or drive:-sourced
    image goes through (#511), so a change to its outcome shape can't miss a copy the
    way #649's fix did.

    `uri` is the file's webContentLink, which the caller already has from the call
    that created or looked up the file: Drive returns it from create() and get()
    alike, identical before and after sharing (confirmed live on #511), so no
    separate files().get() is needed. A missing link fails before sharing, rather
    than leaving an anyone:reader grant on a file nothing can embed.

    `existing_permission_ids` is the file's permissionIds from that same call. Drive's
    permissions.create() for an anyone grant that already exists returns the existing
    grant's fixed ID (e.g. "anyoneWithLink") rather than a new one (confirmed live,
    PR #842 QA round 1), so a returned ID already in that list means the file was
    already public before this call: the result then carries "already_shared": True
    and permission_id None, so nothing revokes a link someone else set up. This holds
    for a freshly uploaded file too, which can inherit a folder's link sharing.
    permissionIds, unlike the permissions field, is populated on Shared Drive items
    (confirmed live, PR #842).

    Returns {"uri", "file_id", "permission_id"} on success, else {"error": ...}. When
    created_here is True — the caller just uploaded this file — the error also carries
    "file_id", so the caller isn't left with an untracked orphan (#649, mirrors
    #420's fix in drive/transfer.py). A pre-existing file (a drive: source) never
    does: surfacing it in a failed-image outcome would let a caller with
    orphan-reclaim logic delete a file it never made (PR #652 QA round 1)."""
    orphan = {"file_id": file_id} if created_here else {}
    if not uri:
        return {"error": f"Drive returned no webContentLink for file {file_id!r}", **orphan}
    try:
        perm = await execute_in_thread(
            drive_service.permissions()
            .create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                supportsAllDrives=True,
                fields="id",
            )
            .execute,
            drive_service,
        )
    except Exception as e:
        return {"error": f"sharing failed for Drive file {file_id!r}: {e}", **orphan}
    permission_id = perm.get("id")
    if permission_id in (existing_permission_ids or []):
        return {"uri": uri, "file_id": file_id, "permission_id": None, "already_shared": True}
    return {"uri": uri, "file_id": file_id, "permission_id": permission_id}


async def revoke_image_shares(
    drive_service, shares: list[tuple[dict[str, Any], str, str | None]]
) -> None:
    """Revokes each (outcome_entry, file_id, permission_id) temporary anyone:reader
    grant, concurrently. On success sets entry["shared"] = False; on failure records
    entry["revoke_error"]. A None permission_id — a grant that pre-existed this call
    (share_image_file's already_shared) — is skipped, never revoked. Shared by
    _apply_doc_content and insert_local_images (#511)."""

    async def _revoke(entry: dict[str, Any], file_id: str, permission_id: str) -> None:
        try:
            await execute_in_thread(
                drive_service.permissions()
                .delete(fileId=file_id, permissionId=permission_id, supportsAllDrives=True)
                .execute,
                drive_service,
            )
            entry["shared"] = False
        except Exception as e:
            entry["revoke_error"] = str(e)

    # return_exceptions=True: _revoke already catches its own errors; this only
    # guards against anything unexpected escaping one revoke and skipping the rest.
    await asyncio.gather(
        *(_revoke(entry, fid, pid) for entry, fid, pid in shares if pid),
        return_exceptions=True,
    )


def log_images_after_failed_edit(
    doc_id: str, image_outcomes: list[dict[str, Any]], created_file_ids: set[str]
) -> None:
    """Warn about the image files an image-embedding call touched when its doc edit
    failed or the call was cancelled (#789, #883). A cancelled call returns nothing,
    so this log is the only record there. Files the call created (a local upload, a
    resized copy, a created-but-unshared orphan, #649) are listed apart from the
    caller's own pre-existing drive: sources, which are never orphans (PR #652 QA
    round 1). "still link-shared" names only shares the call granted and didn't
    revoke (revoke_sharing=False, or a failed revoke), not an already_shared link
    that predates the call. Shared by _apply_doc_content and insert_local_images, so
    the two can't drift (PR #903 QA round 1)."""
    touched = [e["fileId"] for e in image_outcomes if e.get("fileId")]
    if not touched:
        return
    created = [f for f in touched if f in created_file_ids]
    pre_existing = [f for f in touched if f not in created_file_ids]
    still_shared = [
        e["fileId"]
        for e in image_outcomes
        if e.get("fileId") and e.get("shared") and not e.get("already_shared")
    ]
    logger.warning(
        "Doc edit for %s failed or was cancelled after its images were resolved; files "
        "created by this call: %s; pre-existing files: %s; still link-shared by this "
        "call: %s",
        doc_id,
        ", ".join(created) or "none",
        ", ".join(pre_existing) or "none",
        ", ".join(still_shared) or "none",
    )


class ImageShareLifecycle:
    """The temporary-image-share lifecycle of one image-embedding doc edit (#908),
    shared by _apply_doc_content and insert_local_images so the two can't drift again
    (the cancellation gaps PR #903's QA found lived in their differences):

      1. `resolve()`: the image upload/share coroutines run as one gather shielded
         from cancellation. mcp cancels a request through an anyio cancel scope, and
         an upload cancelled mid-gather can have already granted an anyone:reader
         share whose permission ID would then never be recorded, or revoked (PR #877,
         #883). Every folder a result says a file was created in ("created_in") is
         marked dirty in the Drive folder cache (#666).
      2. The caller records each result: `shares` gets every (outcome_entry, file_id,
         permission_id) to revoke, `outcomes` every image's outcome entry, and
         `created_file_ids` the files this call created, for the warning log.
      3. `async with edit():` wraps the doc edit. On entry, a checkpoint lands a
         cancellation the shielded gather held off, before any edit is handed to a
         worker thread that asyncio.to_thread then couldn't stop (#904). Every exit
         marks the doc cache dirty, and so does any request the edit abandoned to a
         cancellation, once its thread actually finishes (#907). Then the shares are
         revoked (revoke_sharing=True), shielded so a cancellation can't cancel the
         revokes before they're sent, followed by a checkpoint that lands a
         cancellation the shield held off (#908). On a failed or cancelled exit, the
         touched files are logged as a warning, since a cancelled call returns
         nothing, and the exception propagates.
    """

    def __init__(self, lc: Any, doc_id: str, *, revoke_sharing: bool):
        self._drive_service = lc.drive_service
        self._doc_cache = lc.doc_cache
        self._drive_folder_cache = lc.drive_folder_cache
        self._doc_id = doc_id
        self._revoke_sharing = revoke_sharing
        self._revoked = False
        # True once the edit body has finished without raising, so a caller can
        # tell a cancellation during the revoke after it (the doc fully written)
        # from one during the edit itself.
        self.edit_completed = False
        self.shares: list[tuple[dict[str, Any], str, str | None]] = []
        self.outcomes: list[dict[str, Any]] = []
        self.created_file_ids: set[str] = set()

    async def resolve(
        self, coros: Iterable[Awaitable[dict[str, Any]]]
    ) -> list[dict[str, Any] | BaseException]:
        # return_exceptions=True: each image coroutine catches its own errors, but
        # this also guards against anything unexpected escaping one without one
        # failed image's exception aborting every other upload.
        with anyio.CancelScope(shield=True):
            results = await asyncio.gather(*coros, return_exceptions=True)
        folders = {r["created_in"] for r in results if isinstance(r, dict) and r.get("created_in")}
        for folder_id in sorted(folders):
            self._drive_folder_cache.mark_dirty(folder_id)
        return results

    def _mark_doc_dirty_after_abandoned_edit(self) -> None:
        logger.debug(
            "A cancelled edit of doc %s finished afterward; marking its cache dirty",
            self._doc_id,
        )
        self._doc_cache.mark_dirty(self._doc_id)

    async def _revoke(self) -> None:
        # Runs at most once, since a cancellation caught after the normal-path
        # revoke reaches it again.
        if self._revoked or not self._revoke_sharing:
            return
        self._revoked = True
        with anyio.CancelScope(shield=True):
            await revoke_image_shares(self._drive_service, self.shares)

    @asynccontextmanager
    async def edit(self) -> AsyncIterator[None]:
        try:
            await anyio.lowlevel.checkpoint()
            try:
                with after_abandoned_calls(self._mark_doc_dirty_after_abandoned_edit):
                    yield
                self.edit_completed = True
            finally:
                # The edit may or may not have been applied, so the cached doc
                # can't be trusted either way.
                self._doc_cache.mark_dirty(self._doc_id)
            await self._revoke()
            await anyio.lowlevel.checkpoint()
        except BaseException:
            try:
                await self._revoke()
            finally:
                log_images_after_failed_edit(self._doc_id, self.outcomes, self.created_file_ids)
            raise


def _with_created_in(result: dict[str, Any], folder_id: str | None) -> dict[str, Any]:
    """Tags a result whose file_id this call just created with "created_in", the Drive
    folder the file landed in, so ImageShareLifecycle can mark that folder's listing
    dirty (#666). A resized drive: copy lands next to its original, not in the
    caller's target folder, so the folder has to come from where the file was made.
    A root-level file (folder_id None) has no folder listing to invalidate."""
    if folder_id and result.get("file_id"):
        result["created_in"] = folder_id
    return result


async def upload_and_share_image(
    drive_service, data: bytes, mime_type: str, name: str, parent_folder_id: str | None
) -> dict[str, Any]:
    """Uploads `data` as a new Drive file and shares it anyone:reader — the same
    requirement every inline-image source needs, since the Docs backend fetches inline
    images as an anonymous HTTP request regardless of the caller's own access
    (confirmed live in #332/#333's own local-image paths). Only ever called with
    downscaled bytes, so its success result is share_image_file's plus
    "downscaled": True — the one place every auto_downscale path (local file or
    drive: source) gets the flag from, so no caller can drop it (PR #842 QA round 1).
    Returns {"uri": ..., "file_id": ..., "permission_id": ...} on success, {"error": ...} on failure before
    any Drive file was created, or {"error": ..., "file_id": ...} if create() succeeded
    but share_image_file failed afterward (#649): a bare error there would leave the
    newly-created file an untracked orphan with no record of its ID. Any result
    carrying file_id also carries "created_in" (see _with_created_in) when
    parent_folder_id is set."""
    file_body: dict[str, Any] = {"name": name}
    if parent_folder_id:
        file_body["parents"] = [parent_folder_id]
    media = MediaInMemoryUpload(data, mimetype=mime_type, resumable=False)
    try:
        created = await execute_in_thread(
            drive_service.files()
            .create(
                body=file_body,
                media_body=media,
                supportsAllDrives=True,
                fields="id,webContentLink,permissionIds",
            )
            .execute,
            drive_service,
        )
    except HttpError as e:
        if is_storage_quota_error(e):
            return {"error": _quota_error_text(drive_service)}
        return {"error": f"failed to upload resized image: {e}"}
    except Exception as e:
        return {"error": f"failed to upload resized image: {e}"}

    result = _with_created_in(
        await share_image_file(
            drive_service,
            created["id"],
            created.get("webContentLink"),
            created.get("permissionIds"),
            created_here=True,
        ),
        parent_folder_id,
    )
    if "error" in result:
        return result
    return {**result, "downscaled": True}


async def downscale_drive_file(
    drive_service, file_id: str, metadata: dict[str, Any], fallback_folder_id: str | None
) -> dict[str, Any]:
    """Downloads an existing Drive file's bytes, downscales them to fit the
    inline-image limit, and uploads the result as a new file — the original is left
    untouched, since silently overwriting a Drive file the caller didn't create for
    this purpose would be a surprising side effect — named f"{name} (resized)",
    shared anyone:reader. Returns {"uri": ..., "file_id": ..., "permission_id": ...}
    or {"error": ...}.

    `metadata` is the file's own Drive metadata (fetched with at least name,parents),
    which the caller already has from its check_drive_image_metadata call. The resized
    copy lands next to the original (its first parent), or in fallback_folder_id when
    Drive reports no parents. That fallback lives here, not at each call site, so
    insert_inline_image and content.py's _resolve_image_source can't drift (#560)."""
    name = metadata.get("name", file_id)
    parents = metadata.get("parents") or []
    parent_folder_id = parents[0] if parents else fallback_folder_id

    def _download() -> bytes:
        request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
        request.http = thread_http(drive_service)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    try:
        data = await asyncio.to_thread(_download)
    except Exception as e:
        return {"error": f"failed to download original image: {e}"}

    # Full decode + resize + re-encodes is CPU-heavy: keep it off the event loop.
    resized = await asyncio.to_thread(downscale_image_bytes, data)
    if resized is None:
        return {"error": f"image could not be downscaled ({_CANNOT_DOWNSCALE_REASONS})"}
    resized_bytes, mime_type = resized
    return await upload_and_share_image(
        drive_service, resized_bytes, mime_type, f"{name} (resized)", parent_folder_id
    )


async def prepare_local_image(
    drive_service, path: str, folder_id: str | None, *, auto_downscale: bool
) -> dict[str, Any] | None:
    """Size-gates a local image file before it's uploaded for embedding. Returns:

      - None: within both limits (or not an image Pillow recognizes) — the caller
        uploads the original file through its normal path, the only full read of it.
      - {"error": ...}: the file couldn't be read, or it's oversized and either
        auto_downscale=False or it can't be downscaled (_CANNOT_DOWNSCALE_REASONS).
      - otherwise, upload_and_share_image's own result for the resized bytes:
        {"uri", "file_id", "permission_id"} on success, or {"error", "file_id"?} on
        failure — a file_id there is a created-but-unshared orphan (#649).

    Shared by insert_local_images and content.py's _resolve_image_source (#560); each
    records the outcome in its own shape."""
    try:
        size_error = await asyncio.to_thread(check_image_file, path)
    except Exception as e:
        return {"error": f"failed to read local file: {e}"}
    if size_error is None:
        return None
    if not auto_downscale:
        return size_error

    try:
        data = await asyncio.to_thread(Path(path).read_bytes)
    except Exception as e:
        return {"error": f"failed to read local file: {e}"}
    downscaled = await asyncio.to_thread(downscale_image_bytes, data)
    if downscaled is None:
        return {
            "error": f"{size_error['error']} Could not auto-downscale it "
            f"({_CANNOT_DOWNSCALE_REASONS})."
        }
    resized_bytes, mime_type = downscaled
    return await upload_and_share_image(
        drive_service, resized_bytes, mime_type, Path(path).name, folder_id
    )


async def upload_and_share_local_image(
    drive_service, path: str, folder_id: str, *, auto_downscale: bool
) -> dict[str, Any]:
    """Size-gates, uploads, and shares one local image file for embedding — the whole
    local-path sequence insert_local_images and content.py's _resolve_image_source
    both need (#511). Returns share_image_file's shape: {"uri", "file_id",
    "permission_id"} on success (plus "downscaled": True if auto_downscale resized
    it), else {"error": ...}, carrying "file_id" only for a created-but-unshared
    orphan (#649) — including one _upload_local_file itself reports as fileId after
    a create() that succeeded before a later step failed (#420). Any result carrying
    file_id also carries "created_in": folder_id."""
    try:
        # Before prepare_local_image's stat and header read (#796).
        check_read(path)
    except LocalFileAccessError as e:
        return {"error": str(e)}
    prepared = await prepare_local_image(
        drive_service, path, folder_id, auto_downscale=auto_downscale
    )
    if prepared is not None:
        return prepared

    upload = await _upload_local_file(
        drive_service, path, folder_id, skip_if_exists=False, include_permission_ids=True
    )
    if "error" in upload:
        error: dict[str, Any] = {"error": upload["error"]}
        if orphan_id := upload.get("fileId"):
            error["file_id"] = orphan_id
        return _with_created_in(error, folder_id)
    return _with_created_in(
        await share_image_file(
            drive_service,
            upload["fileId"],
            upload.get("web_content_link"),
            upload.get("permission_ids"),
            created_here=True,
        ),
        folder_id,
    )


def record_image_outcome(entry: dict[str, Any], result: dict[str, Any]) -> bool:
    """Folds a share_image_file-shaped result into a caller-facing per-image outcome
    entry: its file_id (the shared file, or a created-but-unshared orphan, #649) as
    entry["fileId"], any error as entry["error"], and on success the "downscaled" and
    "already_shared" flags. Returns True on success. The one place both
    image-embedding tools record this (#511), so a field can't reach one tool's
    outcome but not the other's — the drift PR #652's QA round caught for fileId and
    PR #842's for downscaled."""
    if file_id := result.get("file_id"):
        entry["fileId"] = file_id
    if "error" in result:
        entry["error"] = result["error"]
        return False
    for flag in ("downscaled", "already_shared"):
        if result.get(flag):
            entry[flag] = True
    return True


def register(tool):
    @tool(annotations=ToolAnnotations(title="Insert Inline Image", destructiveHint=True))
    async def insert_inline_image(
        doc_id: str,
        index: int,
        uri: str | None = None,
        drive_file_id: str | None = None,
        width: float | None = None,
        height: float | None = None,
        auto_downscale: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an inline image at a specific index in a Google Doc.

        Provide either uri (a publicly accessible HTTPS image URL) or drive_file_id
        (a Drive file ID for an image stored in Drive). The image is inserted at the
        given document index.

        Use get_doc_structure to find a suitable insertion index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the image should be inserted.
            uri: A publicly accessible image URI (HTTPS). Mutually exclusive with drive_file_id.
            drive_file_id: A Google Drive file ID for an image stored in Drive. The
                Docs backend fetches the image over HTTP as an anonymous request, so
                the file must be shared as anyone-with-link (e.g. via share_file with
                {"type": "anyone", "role": "reader"}) — being accessible to the
                authenticated user alone is not sufficient and fails with "There was
                a problem retrieving the image" (confirmed live 2026-07-18).
                Mutually exclusive with uri.
            width: Optional image width in points.
            height: Optional image height in points.
            auto_downscale: Google Docs rejects any inline image over ~25 megapixels
                or ~50MB. When drive_file_id is provided and Drive's own reported
                dimensions or file size exceed either limit, the default (False)
                fails fast with a clear error naming the limit and the image's actual
                size — before ever calling the Docs API. Set True to instead resize
                it and embed the resized copy: the original Drive file is left
                untouched, a new file named "<original name> (resized)" is created
                alongside it and shared anyone:reader, and its own fileId is returned
                as resized_file_id. Ignored when uri is used instead of
                drive_file_id — there's no local copy of a bare uri to resize; an
                oversized uri source instead fails with a rewritten error explaining
                the likely cause, since pre-validating or re-hosting arbitrary
                external content is out of scope here (see docs/decisions/decision-
                pillow-image-dependency.md).

        Returns:
            Confirmation with docId and the insertion index. Also includes
            resized_file_id if drive_file_id was resized under auto_downscale,
            on an error result too, since the resized copy exists either way.
        """
        if not uri and not drive_file_id:
            return {"error": "Provide either uri or drive_file_id"}
        if uri and drive_file_id:
            return {"error": "Provide only one of uri or drive_file_id, not both"}

        lc = ctx.request_context.lifespan_context
        resized_file_id: str | None = None

        if drive_file_id:
            try:
                metadata = await execute_in_thread(
                    lc.drive_service.files()
                    .get(
                        fileId=drive_file_id,
                        fields="name,parents,webContentLink,imageMediaMetadata,size",
                        supportsAllDrives=True,
                    )
                    .execute,
                    lc.drive_service,
                )
                uri = metadata.get("webContentLink")
                if not uri:
                    return {"error": f"Could not get download link for Drive file {drive_file_id}"}
            except Exception as e:
                return {"error": f"Failed to get Drive file metadata: {e}"}

            size_error = check_drive_image_metadata(metadata)
            if size_error is not None:
                if not auto_downscale:
                    return size_error
                # Shielded, so a cancellation can't land after the resized copy was
                # created and shared but before its ID is known (the PR #877 rule).
                with anyio.CancelScope(shield=True):
                    resized = await downscale_drive_file(
                        lc.drive_service, drive_file_id, metadata, lc.folder_id
                    )
                if created_in := resized.pop("created_in", None):
                    lc.drive_folder_cache.mark_dirty(created_in)
                if "error" in resized:
                    return resized
                uri = resized["uri"]
                resized_file_id = resized["file_id"]

        image_request: dict[str, Any] = {
            "insertInlineImage": {
                "location": {"index": index},
                "uri": uri,
            }
        }
        if width is not None or height is not None:
            object_size: dict[str, Any] = {}
            if width is not None:
                object_size["width"] = {"magnitude": width, "unit": "PT"}
            if height is not None:
                object_size["height"] = {"magnitude": height, "unit": "PT"}
            image_request["insertInlineImage"]["objectSize"] = object_size

        # A resized copy exists and stays link-shared however the edit ends, so
        # every exit reports its ID: an error result carries it, and a cancelled
        # call, which returns nothing, logs it.
        failure: dict[str, Any] = {"resized_file_id": resized_file_id} if resized_file_id else {}
        try:
            # Lands a cancellation the shielded downscale held off, before the
            # edit is handed to a worker thread that can't be stopped (#904).
            await anyio.lowlevel.checkpoint()
            # A cancelled call's edit can still land after it returns (#907).
            with after_abandoned_calls(lambda: lc.doc_cache.mark_dirty(doc_id)):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": [image_request]})
                    .execute,
                    lc.docs_service,
                )
        except HttpError as e:
            return {"error": rewrite_too_large_error(str(e)), **failure}
        except Exception as e:
            return {"error": str(e), **failure}
        except BaseException:
            if resized_file_id:
                logger.warning(
                    "insert_inline_image for doc %s was cancelled; its resized copy %s "
                    "was created and stays link-shared",
                    doc_id,
                    resized_file_id,
                )
            raise
        finally:
            # Every exit: a failed request (a timeout, a 5xx) may still have been
            # applied, and a cancelled one may still land.
            lc.doc_cache.mark_dirty(doc_id)

        logger.debug("insert_inline_image: at index %d in doc %s", index, doc_id)
        result: dict[str, Any] = {"docId": doc_id, "index": index}
        if resized_file_id:
            result["resized_file_id"] = resized_file_id
        return result

    @tool(
        annotations=ToolAnnotations(title="Insert Local Images by Marker", destructiveHint=True),
        local_only=True,
    )
    async def insert_local_images(
        doc_id: str,
        images: list[dict],
        folder_id: str | None = None,
        revoke_sharing: bool = True,
        auto_downscale: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Upload local image files to Drive and swap each into a Google Doc at a
        plain-text marker, in one call.
        Not available when the server runs with LOCAL_FILE_ACCESS=off.

        Typical flow: write doc content with a unique plain-text placeholder per
        image (e.g. "IMGMARKERONE") via create_doc/write_doc_content/insert_doc_text,
        then call this tool once with the marker → local file mapping. Collapses the
        N manual upload/find/insert/delete round trips a multi-image doc would
        otherwise need into a single call.

        For each image: uploads the local file to Drive, shares it as
        anyone-with-link/reader (required — the Docs backend fetches inline images
        as an anonymous HTTP request, so a private file fails with "There was a
        problem retrieving the image"; confirmed live 2026-07-18), locates its
        marker's current position, inserts the image immediately before the marker
        text, then deletes the marker text. Once the image is actually embedded,
        that temporary share is revoked again by default (revoke_sharing=True) —
        revoking any earlier would break the embed, since Docs fetches the image at
        insertion time, not upload time. The revoke also runs if the document edit
        fails or the call is cancelled; a cancelled call returns nothing, so the
        uploaded file IDs are logged as a warning instead.

        All markers are located in a single pass over the document's current text
        before any edits are applied — markers are matched longest-first at each
        position, so one marker that's a substring of another (e.g. "IMG1" vs
        "IMG10") can't produce a false match or a false "occurs twice" collision.
        Uploads and shares run in parallel; the document edit is one batchUpdate
        applied highest-index-first so replacing one marker never invalidates
        another marker's already-computed position — same convention as
        insert_doc_text/delete_doc_range. Uploading and sharing happen before any
        document edit, so a failed upload never leaves the doc partially edited.

        Args:
            doc_id: The Google Doc file ID.
            images: List of image dicts, each with:
                marker (str): exact literal text already present in the doc body,
                    marking where this image goes. Matched as a whole token — not
                    immediately preceded or followed by another letter, digit, or
                    underscore — so a marker like "IMG1" can't falsely match inside
                    unrelated text like "IMG10". Must occur exactly once in the
                    document (searched case-sensitively) — an ambiguous or missing
                    marker fails just that image, not the whole call.
                local_path: absolute path to the local image file.
                width, height (float, optional): image size in points.
            folder_id: Drive folder to upload images into. Defaults to the server's
                configured default folder.
            revoke_sharing: Whether each image's temporary anyone:reader share is
                revoked again after it's embedded (default True). Set False to leave
                images shared instead — matches this tool's original behavior. A
                file that was already link-shared before the call (e.g. inherited
                from its folder) keeps its link and is reported with
                already_shared: true.
            auto_downscale: Google Docs rejects any inline image over ~25 megapixels
                or ~50MB. Each image's local file is checked against both limits
                before it's ever uploaded. The default (False) fails just that image
                with a clear error naming the limit and its actual size — other
                images in the same call are unaffected. Set True to instead resize an
                oversized image and upload the resized copy (the local file on disk
                is never modified); that outcome's entry gets downscaled: true.

        Returns:
            Dictionary with docId and results — a list of per-image outcomes in the
            same order as the `images` argument, each echoing marker and local_path
            plus either fileId + index + shared (+ revoke_error if a revoke attempt
            failed, + downscaled: true if auto_downscale resized it, +
            already_shared: true if the file was link-shared before this call) on
            success, or
            error on failure (marker not found, marker not unique, local file
            missing, oversized with auto_downscale off, upload failure, sharing
            failure, or — rare, since uploads happen first — a failed document edit;
            that last case keeps fileId and shared, with no index, since the upload
            and share happened even though the image was never placed). A sharing
            failure after the underlying Drive file was already created also carries
            fileId (#649) — the upload itself succeeded even though the share didn't.
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service
        drive_service = lc.drive_service
        target_folder_id = folder_id or lc.folder_id

        if not images:
            return {"error": "images list is empty"}
        if not target_folder_id:
            return {"error": "folder_id is required (no server default folder configured)"}

        try:
            doc = await execute_in_thread(
                docs_service.documents().get(documentId=doc_id).execute,
                docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        paragraphs = list(_collect_doc_paragraphs(doc.get("body", {}).get("content", [])))

        # Locate every requested marker in a single pass over the document. Two
        # measures guard against one marker being a substring of another piece of
        # text: (1) each match must be a whole token — not immediately preceded or
        # followed by another letter/digit/underscore — so a marker "IMG1" can't
        # match inside unrelated document text "IMG10"; (2) alternatives are tried
        # longest-first, so if two *requested* markers legitimately overlap at the
        # same position (e.g. both "IMG1" and "IMG10" are real, distinct markers
        # present in the doc), the longer one wins there rather than the shorter
        # one swallowing part of it.
        marker_texts = {img.get("marker") for img in images if img.get("marker")}
        located: dict[str, list[int]] = {m: [] for m in marker_texts}
        if marker_texts:
            alternation = "|".join(
                re.escape(m) for m in sorted(marker_texts, key=len, reverse=True)
            )
            combined = re.compile(rf"(?<![A-Za-z0-9_])(?:{alternation})(?![A-Za-z0-9_])")
            for para_text, para_indices in paragraphs:
                for m in combined.finditer(para_text):
                    located[m.group(0)].append(para_indices[m.start()])

        # outcomes is index-aligned with `images` throughout, so the returned
        # `results` list always matches caller input order regardless of the
        # order placements finish uploading or get written to the doc.
        outcomes: list[dict[str, Any] | None] = [None] * len(images)
        placements: list[dict[str, Any]] = []  # located + validated, ready to upload+place

        for i, image in enumerate(images):
            marker = image.get("marker")
            local_path = image.get("local_path")
            entry: dict[str, Any] = {"marker": marker, "local_path": local_path}

            if not marker:
                entry["error"] = "missing 'marker'"
                outcomes[i] = entry
                continue
            if not local_path:
                entry["error"] = "missing 'local_path'"
                outcomes[i] = entry
                continue
            try:
                # Before the stat, so a refused path reads the same whether or not
                # it exists (#796).
                is_file = check_read(local_path).is_file()
            except LocalFileAccessError as e:
                entry["error"] = str(e)
                outcomes[i] = entry
                continue
            if not is_file:
                entry["error"] = f"No file found at {local_path!r}"
                outcomes[i] = entry
                continue

            matches = located.get(marker, [])
            if not matches:
                entry["error"] = f"marker {marker!r} not found in document"
                outcomes[i] = entry
                continue
            if len(matches) > 1:
                entry["error"] = f"marker {marker!r} occurs {len(matches)} times; must be unique"
                outcomes[i] = entry
                continue

            placements.append(
                {
                    "index": i,
                    "entry": entry,
                    "marker_start": matches[0],
                    "marker_len": utf16_len(marker),
                    "local_path": local_path,
                    "width": image.get("width"),
                    "height": image.get("height"),
                }
            )

        lifecycle = ImageShareLifecycle(lc, doc_id, revoke_sharing=revoke_sharing)
        results = await lifecycle.resolve(
            upload_and_share_local_image(
                drive_service, p["local_path"], target_folder_id, auto_downscale=auto_downscale
            )
            for p in placements
        )
        ready: list[dict[str, Any]] = []
        for placement, result in zip(placements, results, strict=True):
            entry = placement["entry"]
            lifecycle.outcomes.append(entry)
            if isinstance(result, BaseException):
                entry["error"] = f"upload/share failed: {result}"
            # record_image_outcome also surfaces a created-but-unshared orphan's
            # file_id (#649), so the caller isn't left with no record of it.
            elif record_image_outcome(entry, result):
                placement["uri"] = result["uri"]
                lifecycle.shares.append((entry, result["file_id"], result["permission_id"]))
                # fileId/shared are kept regardless of how the doc edit below ends:
                # a failed or cancelled embed doesn't undo the upload+share that
                # already succeeded, so the file is still genuinely world-readable
                # and the caller needs fileId to trace it — silently dropping both
                # would leave it orphaned with zero signal (PR #502 review round 1,
                # finding #1).
                entry["shared"] = True
                ready.append(placement)
            # Every file here was uploaded by this call.
            if entry.get("fileId"):
                lifecycle.created_file_ids.add(entry["fileId"])
            outcomes[placement["index"]] = entry

        doc_edit_error: str | None = None
        async with lifecycle.edit():
            if ready:
                # Highest marker_start first, so an earlier (lower-index) marker's
                # position is never shifted by a later edit — same convention as
                # insert_doc_text.
                requests: list[dict[str, Any]] = []
                for placement in sorted(ready, key=lambda p: p["marker_start"], reverse=True):
                    marker_start = placement["marker_start"]
                    image_request: dict[str, Any] = {
                        "insertInlineImage": {
                            "location": {"index": marker_start},
                            "uri": placement["uri"],
                        }
                    }
                    width, height = placement.get("width"), placement.get("height")
                    if width is not None or height is not None:
                        object_size: dict[str, Any] = {}
                        if width is not None:
                            object_size["width"] = {"magnitude": width, "unit": "PT"}
                        if height is not None:
                            object_size["height"] = {"magnitude": height, "unit": "PT"}
                        image_request["insertInlineImage"]["objectSize"] = object_size
                    requests.append(image_request)
                    requests.append(
                        {
                            "deleteContentRange": {
                                "range": {
                                    "startIndex": marker_start + 1,
                                    "endIndex": marker_start + 1 + placement["marker_len"],
                                }
                            }
                        }
                    )

                try:
                    await execute_in_thread(
                        docs_service.documents()
                        .batchUpdate(documentId=doc_id, body={"requests": requests})
                        .execute,
                        docs_service,
                    )
                except Exception as e:
                    doc_edit_error = rewrite_too_large_error(str(e))

                for placement in ready:
                    entry = placement["entry"]
                    if doc_edit_error is not None:
                        entry["error"] = f"doc edit failed: {doc_edit_error}"
                    else:
                        entry["index"] = placement["marker_start"]

        logger.debug(
            "insert_local_images: %d/%d images placed in doc %s",
            0 if doc_edit_error is not None else len(ready),
            len(images),
            doc_id,
        )
        return {"docId": doc_id, "results": outcomes}
