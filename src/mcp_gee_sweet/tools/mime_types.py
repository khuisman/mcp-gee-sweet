import mimetypes

OCTET_STREAM = "application/octet-stream"

# What a compressed file's guess_type() encoding means as a MIME type. guess_type
# reports "x.csv.gz" as ("text/csv", "gzip"), and the bytes are gzip, not CSV.
_ENCODING_MIME_TYPES = {
    "gzip": "application/gzip",
    "bzip2": "application/x-bzip2",
    "xz": "application/x-xz",
    "compress": "application/x-compress",
    "br": "application/x-brotli",
}

# Python's built-in extension table only. A bare MimeTypes() builds its table from
# the module's built-in defaults; what mimetypes.init() reads from /etc/mime.types,
# Apache's files, or the Windows registry goes only into the module-level database,
# so a guess doesn't depend on the host (PR #928 QA: a Windows host with Excel maps
# .csv to application/vnd.ms-excel).
_MIME_TYPES = mimetypes.MimeTypes()


def guess_mime_type(filename: str) -> str:
    """The file's MIME type from its filename extension, or application/octet-stream
    when unknown.

    A compressed file gets its compression type, not the type of what's inside it
    ("x.csv.gz" is application/gzip, not text/csv; #930). Shared by Gmail
    attachments and Drive uploads (upload_local_file, upload_local_folder,
    sync_folder), so the two can't drift apart.
    """
    mime_type, encoding = _MIME_TYPES.guess_type(filename)
    if encoding:
        return _ENCODING_MIME_TYPES.get(encoding, OCTET_STREAM)
    return mime_type or OCTET_STREAM
