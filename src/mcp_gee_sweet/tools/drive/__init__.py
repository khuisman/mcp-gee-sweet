from typing import Any

from ...auth import _is_service_account_credential

_SA_QUOTA_ERROR = (
    "Service accounts cannot create or copy files in personal Drive (no storage quota). "
    "Use OAuth or ADC auth for full Drive write access, or use a Shared Drive destination. "
    "Check server://auth-status for your current auth method and affected tools."
)

_USER_QUOTA_ERROR = (
    "This account's Google Drive storage is full. Free up space or add storage, then try again."
)


def _quota_error_text(service: Any) -> str:
    """The storageQuotaExceeded message for the identity behind `service`.

    A service account has no personal storage, so it needs _SA_QUOTA_ERROR's
    advice (switch auth, or target a Shared Drive). A user identity already has
    storage that's full, so that advice would mislead it (#1009). The identity
    comes from the service's own credentials, the same check that sets
    SpreadsheetContext.is_service_account_identity, so every site that has a
    service can render the right text without the flag being passed down."""
    credentials = getattr(getattr(service, "_http", None), "credentials", None)
    if _is_service_account_credential(credentials):
        return _SA_QUOTA_ERROR
    return _USER_QUOTA_ERROR


def _escape_drive_query_mime_type(mime_type: str) -> str:
    """Escape a mimeType value for embedding in a Drive `files().list()` `q` string.

    Drive's query grammar uses a backslash escape for a literal single quote inside
    a quoted string value (not SQL-style quote-doubling — see #494). A mimeType
    never itself contains a backslash, so unlike a free-text search term this only
    needs the single-quote escape, not the backslash-then-quote pair.
    """
    return mime_type.replace("'", "\\'")
