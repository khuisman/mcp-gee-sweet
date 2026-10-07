"""Filename-based MIME guessing for raw file bytes."""

import mimetypes

_ENCODING_MIME_TYPES = {
    "gzip": "application/gzip",
    "bzip2": "application/x-bzip2",
    "xz": "application/x-xz",
    "compress": "application/x-compress",
    "br": "application/x-brotli",
}


def guess_mime_type(filename: str) -> str:
    """Use the compression MIME type when bytes are encoded, not the inner type."""
    mime_type, encoding = mimetypes.guess_type(filename)
    if encoding:
        return _ENCODING_MIME_TYPES.get(encoding, "application/octet-stream")
    return mime_type or "application/octet-stream"
