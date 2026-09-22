_SA_QUOTA_ERROR = (
    "Service accounts cannot create or copy files in personal Drive (no storage quota). "
    "Use OAuth or ADC auth for full Drive write access, or use a Shared Drive destination. "
    "Check server://auth-status for your current auth method and affected tools."
)


def _escape_drive_query_mime_type(mime_type: str) -> str:
    """Escape a mimeType value for embedding in a Drive `files().list()` `q` string.

    Drive's query grammar uses a backslash escape for a literal single quote inside
    a quoted string value (not SQL-style quote-doubling — see #494). A mimeType
    never itself contains a backslash, so unlike a free-text search term this only
    needs the single-quote escape, not the backslash-then-quote pair.
    """
    return mime_type.replace("'", "\\'")
