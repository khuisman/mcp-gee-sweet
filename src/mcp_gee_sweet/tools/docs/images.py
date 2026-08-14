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
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from PIL import Image

from ...auth import execute_in_thread, thread_http
from ..drive import _SA_QUOTA_ERROR
from ..drive.transfer import _upload_local_file
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


def _decode(data: bytes) -> Image.Image | None:
    """Best-effort decode — returns None (not an exception) for anything Pillow can't
    read, since validation here is an additive convenience, not a gate: an undecodable
    file still gets its real answer straight from the Docs API, same as before #400."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
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


def check_image_bytes(data: bytes) -> dict[str, Any] | None:
    """Checks `data` against both the file-size limit (always, regardless of whether
    it decodes as an image) and, if it decodes, the megapixel limit. Returns None (no
    error, not a skip signal the caller needs to distinguish) when the bytes can't be
    decoded and are within the size limit."""
    size_error = check_file_size(len(data))
    if size_error is not None:
        return size_error
    img = _decode(data)
    if img is None:
        return None
    return check_dimensions(*img.size)


def downscale_image_bytes(data: bytes) -> tuple[bytes, str] | None:
    """Resize image `data` to fit both the megapixel and file-size limits, preserving
    aspect ratio and format. Returns (resized_bytes, mime_type), or None if: the image
    can't be decoded; it's already within both limits (nothing to do — caller should
    keep using the original bytes/upload path); or it's animated (Pillow's resize only
    touches the current frame, which would silently drop every other frame of an
    animated GIF — declining is safer than corrupting it).

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

    return encoded, _FORMAT_MIME.get(fmt, "application/octet-stream")


def check_drive_image_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Checks a Drive file's own reported imageMediaMetadata dimensions and `size`
    field against the inline-image limits, without downloading the file — the
    metadata-only counterpart to check_image_bytes, shared by every call site that
    validates a drive_file_id/"drive:" source before deciding whether to embed it
    directly or downscale it first (issue #562's own consolidation of a pattern that
    used to be duplicated between insert_inline_image here and content.py's
    _resolve_image_source). Dimensions are checked first, matching
    downscale_image_bytes's own resize-by-pixels-first behavior. Returns the first
    violation found, or None if within both limits or the metadata doesn't report
    enough to check (e.g. a non-image binary with no imageMediaMetadata)."""
    img_meta = metadata.get("imageMediaMetadata") or {}
    width, height = img_meta.get("width"), img_meta.get("height")
    if width and height:
        error = check_dimensions(width, height)
        if error is not None:
            return error
    size = metadata.get("size")
    if size is not None:
        return check_file_size(int(size))
    return None


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


async def upload_and_share_image(
    drive_service, data: bytes, mime_type: str, name: str, parent_folder_id: str | None
) -> dict[str, Any]:
    """Uploads `data` as a new Drive file and shares it anyone:reader — the same
    requirement every inline-image source needs, since the Docs backend fetches inline
    images as an anonymous HTTP request regardless of the caller's own access
    (confirmed live in #332/#333's own local-image paths). Returns {"uri": ...,
    "file_id": ..., "permission_id": ...} on success or {"error": ...} on failure,
    mirroring _resolve_image_source's own outcome shape."""
    file_body: dict[str, Any] = {"name": name}
    if parent_folder_id:
        file_body["parents"] = [parent_folder_id]
    media = MediaInMemoryUpload(data, mimetype=mime_type, resumable=False)
    try:
        created = await execute_in_thread(
            drive_service.files()
            .create(body=file_body, media_body=media, supportsAllDrives=True, fields="id")
            .execute,
            drive_service,
        )
        new_file_id = created["id"]
        perm = await execute_in_thread(
            drive_service.permissions()
            .create(
                fileId=new_file_id,
                body={"type": "anyone", "role": "reader"},
                supportsAllDrives=True,
                fields="id",
            )
            .execute,
            drive_service,
        )
        metadata = await execute_in_thread(
            drive_service.files()
            .get(fileId=new_file_id, fields="webContentLink", supportsAllDrives=True)
            .execute,
            drive_service,
        )
    except HttpError as e:
        if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
            return {"error": _SA_QUOTA_ERROR}
        return {"error": f"failed to upload resized image: {e}"}
    except Exception as e:
        return {"error": f"failed to upload resized image: {e}"}

    uri = metadata.get("webContentLink")
    if not uri:
        return {
            "error": f"resized image {new_file_id} uploaded but Drive returned no webContentLink"
        }
    return {"uri": uri, "file_id": new_file_id, "permission_id": perm.get("id")}


async def downscale_drive_file(
    drive_service, file_id: str, *, name: str, parent_folder_id: str | None
) -> dict[str, Any]:
    """Downloads an existing Drive file's bytes, downscales them to fit the
    inline-image limit, and uploads the result as a new file — the original is left
    untouched, since silently overwriting a Drive file the caller didn't create for
    this purpose would be a surprising side effect — named f"{name} (resized)",
    shared anyone:reader. Returns {"uri": ..., "file_id": ..., "permission_id": ...}
    or {"error": ...}."""

    def _download() -> bytes:
        request = drive_service.files().get_media(fileId=file_id)
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

    resized = downscale_image_bytes(data)
    if resized is None:
        return {"error": "image could not be downscaled (unreadable format, or animated)"}
    resized_bytes, mime_type = resized
    return await upload_and_share_image(
        drive_service, resized_bytes, mime_type, f"{name} (resized)", parent_folder_id
    )


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
            resized_file_id if drive_file_id was resized under auto_downscale.
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
                original_parents = metadata.get("parents") or []
                resized = await downscale_drive_file(
                    lc.drive_service,
                    drive_file_id,
                    name=metadata.get("name", drive_file_id),
                    parent_folder_id=original_parents[0] if original_parents else lc.folder_id,
                )
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

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": [image_request]})
                .execute,
                lc.docs_service,
            )
        except HttpError as e:
            return {"error": rewrite_too_large_error(str(e))}
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_inline_image: at index %d in doc %s", index, doc_id)
        result: dict[str, Any] = {"docId": doc_id, "index": index}
        if resized_file_id:
            result["resized_file_id"] = resized_file_id
        return result

    @tool(annotations=ToolAnnotations(title="Insert Local Images by Marker", destructiveHint=True))
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
        insertion time, not upload time.

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
                images shared instead — matches this tool's original behavior.
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
            failed, + downscaled: true if auto_downscale resized it) on success, or
            error on failure (marker not found, marker not unique, local file
            missing, oversized with auto_downscale off, upload failure, sharing
            failure, or — rare, since uploads happen first — a failed document edit;
            that last case never carries a fileId even though the upload itself
            succeeded, since the image was never actually placed).
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
            if not Path(local_path).is_file():
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

        async def _upload_and_share(placement: dict[str, Any]) -> None:
            entry = placement["entry"]
            local_path = placement["local_path"]

            try:
                data = await asyncio.to_thread(Path(local_path).read_bytes)
            except Exception as e:
                entry["error"] = f"failed to read local file: {e}"
                placement["failed"] = True
                return

            size_error = check_image_bytes(data)
            if size_error is not None:
                if not auto_downscale:
                    entry["error"] = size_error["error"]
                    placement["failed"] = True
                    return
                downscaled = downscale_image_bytes(data)
                if downscaled is None:
                    entry["error"] = (
                        f"{size_error['error']} Could not auto-downscale it "
                        "(unreadable format, or animated)."
                    )
                    placement["failed"] = True
                    return
                resized_bytes, mime_type = downscaled
                result = await upload_and_share_image(
                    drive_service, resized_bytes, mime_type, Path(local_path).name, target_folder_id
                )
                if "error" in result:
                    entry["error"] = result["error"]
                    placement["failed"] = True
                    return
                placement["file_id"] = result["file_id"]
                placement["permission_id"] = result["permission_id"]
                placement["uri"] = result["uri"]
                entry["fileId"] = result["file_id"]
                entry["downscaled"] = True
                return

            try:
                upload = await _upload_local_file(
                    drive_service, local_path, target_folder_id, skip_if_exists=False
                )
                if "error" in upload:
                    entry["error"] = upload["error"]
                    placement["failed"] = True
                    return

                file_id = upload["fileId"]
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
                metadata = await execute_in_thread(
                    drive_service.files()
                    .get(fileId=file_id, fields="webContentLink", supportsAllDrives=True)
                    .execute,
                    drive_service,
                )
            except Exception as e:
                entry["error"] = f"upload/share failed: {e}"
                placement["failed"] = True
                return

            uri = metadata.get("webContentLink")
            if not uri:
                entry["error"] = (
                    f"uploaded and shared as {file_id} but Drive returned no webContentLink"
                )
                placement["failed"] = True
                return

            placement["file_id"] = file_id
            placement["permission_id"] = perm.get("id")
            placement["uri"] = uri
            entry["fileId"] = file_id

        if placements:
            # return_exceptions=True: _upload_and_share already catches its own
            # errors, but this also guards against anything unexpected escaping it
            # without one failed image's exception aborting every other upload.
            gather_results = await asyncio.gather(
                *(_upload_and_share(p) for p in placements), return_exceptions=True
            )
            for placement, result in zip(placements, gather_results):
                if isinstance(result, BaseException):
                    placement["failed"] = True
                    placement["entry"]["error"] = f"upload/share failed: {result}"

        if any("file_id" in p for p in placements):
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        for placement in placements:
            if placement.get("failed"):
                outcomes[placement["index"]] = placement["entry"]

        ready = [p for p in placements if not p.get("failed")]
        if not ready:
            return {"docId": doc_id, "results": outcomes}

        # Highest marker_start first, so an earlier (lower-index) marker's position
        # is never shifted by a later edit — same convention as insert_doc_text.
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

        doc_edit_error: str | None = None
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
            # fileId/shared are kept regardless of doc_edit_error: a failed embed
            # doesn't undo the upload+share that already succeeded, so the file is
            # still genuinely world-readable and the caller needs fileId to trace
            # it — silently dropping both here would leave it orphaned with zero
            # signal (PR #502 review round 1, finding #1).
            entry["shared"] = True
            if doc_edit_error is not None:
                entry["error"] = f"doc edit failed: {doc_edit_error}"
            else:
                entry["index"] = placement["marker_start"]
            outcomes[placement["index"]] = entry

        if revoke_sharing:

            async def _revoke(placement: dict[str, Any]) -> None:
                try:
                    await execute_in_thread(
                        drive_service.permissions()
                        .delete(
                            fileId=placement["file_id"],
                            permissionId=placement["permission_id"],
                            supportsAllDrives=True,
                        )
                        .execute,
                        drive_service,
                    )
                    placement["entry"]["shared"] = False
                except Exception as e:
                    placement["entry"]["revoke_error"] = str(e)

            # return_exceptions=True: _revoke already catches its own errors, same
            # rationale as the upload/share gather above. Runs regardless of
            # doc_edit_error — an image that failed to embed was still genuinely
            # uploaded and shared, so a failed embed must not skip cleanup of that
            # real, temporary anyone:reader grant.
            await asyncio.gather(*(_revoke(p) for p in ready), return_exceptions=True)

        if doc_edit_error is None:
            lc.doc_cache.mark_dirty(doc_id)
        logger.debug(
            "insert_local_images: %d/%d images placed in doc %s",
            0 if doc_edit_error is not None else len(ready),
            len(images),
            doc_id,
        )
        return {"docId": doc_id, "results": outcomes}
