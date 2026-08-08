"""Inline-image size validation, downscaling, and error-message clarification (#400).

Google Docs' insertInlineImage request rejects any image over ~25 megapixels with a
bare "The provided image is too large" HttpError that names neither the actual limit
nor the image's own size — confirmed against
https://developers.google.com/workspace/docs/api/how-tos/images, which documents the
ceiling as 25 megapixels (also 50MB, PNG/JPEG/GIF only). This module gives every
insertInlineImage call site in this package a shared way to self-diagnose an oversized
image *before* ever calling the API, and — opt-in — automatically fix it by
downscaling. See docs/decisions/decision-pillow-image-dependency.md for why Pillow was
added as a dependency to do this, and the scope boundary that decision implies.

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
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from PIL import Image

from ...auth import execute_in_thread, thread_http
from ..drive import _SA_QUOTA_ERROR

# Google Docs' documented inline-image ceiling, in decimal megapixels (1,000,000 px —
# matching how Google's own docs express it, not a binary 1024*1024 "MP").
MAX_INLINE_IMAGE_MEGAPIXELS = 25
MAX_INLINE_IMAGE_PIXELS = MAX_INLINE_IMAGE_MEGAPIXELS * 1_000_000

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


def check_image_bytes(data: bytes) -> dict[str, Any] | None:
    """Same as check_dimensions, decoding `data` first. Returns None (no error, not a
    skip signal the caller needs to distinguish) when the bytes can't be decoded."""
    img = _decode(data)
    if img is None:
        return None
    return check_dimensions(*img.size)


def downscale_image_bytes(data: bytes) -> tuple[bytes, str] | None:
    """Resize image `data` to fit the megapixel limit, preserving aspect ratio and
    format. Returns (resized_bytes, mime_type), or None if: the image can't be
    decoded; it's already within the limit (nothing to do — caller should keep using
    the original bytes/upload path); or it's animated (Pillow's resize only touches
    the current frame, which would silently drop every other frame of an animated GIF
    — declining is safer than corrupting it)."""
    img = _decode(data)
    if img is None or getattr(img, "is_animated", False):
        return None
    width, height = img.size
    pixels = width * height
    if pixels <= MAX_INLINE_IMAGE_PIXELS:
        return None
    scale = (MAX_INLINE_IMAGE_PIXELS / pixels) ** 0.5
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    fmt = img.format or "PNG"
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    if fmt == "JPEG" and resized.mode not in ("RGB", "L"):
        resized = resized.convert("RGB")
    out = io.BytesIO()
    resized.save(out, format=fmt)
    return out.getvalue(), _FORMAT_MIME.get(fmt, "application/octet-stream")


def rewrite_too_large_error(message: str) -> str:
    """Rewrites Google's own opaque insertInlineImage "too large" HttpError text
    (str(HttpError) — confirmed live and via issue #400's own repro to read
    '...Invalid requests[N].insertInlineImage: The provided image is too large.') to
    name the known cause, for call sites (a bare http(s):// uri) that can't
    pre-validate because they never fetch the image's own bytes. Returns the message
    unchanged for anything else, so an unrelated insertInlineImage failure (e.g. an
    unfetchable URL, #333) isn't misreported as a size problem."""
    if "insertInlineImage" in message and "too large" in message.lower():
        return (
            f"{message} This is very likely Google Docs' inline-image limit of "
            f"{MAX_INLINE_IMAGE_MEGAPIXELS} megapixels ({_DOCS_IMAGE_LIMITS_URL}) — "
            "check the image's pixel dimensions and resize it before retrying."
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
