from collections.abc import Iterable
from typing import Any

from ...auth import _is_service_account_credential

_SA_QUOTA_ERROR = (
    "This service account has no My Drive storage, so it can create files only in a "
    "Shared Drive. Target a Shared Drive folder, or authenticate as a user (OAuth, or ADC "
    "with user credentials). If the destination is already a Shared Drive, its "
    "organization storage is full. Check server://auth-status for your current auth "
    "method and affected tools."
)

_USER_QUOTA_ERROR = (
    "Google Drive storage is full for this destination: your My Drive, or the Shared "
    "Drive's organization storage. Free up space or add storage, then try again."
)


def _quota_error_text(service: Any) -> str:
    """The storageQuotaExceeded message for the identity behind `service`, for
    an error http_errors.is_storage_quota_error has matched.

    A service account has no personal storage, so it needs _SA_QUOTA_ERROR's
    advice (target a Shared Drive or authenticate as a user, or the Shared Drive
    it already targets is full). That covers an ADC-resolved service identity
    too, which "use OAuth or ADC" would mislead (PR #1006 QA round 6). A user identity's
    destination is full, either its My Drive or a Shared Drive's pooled
    organization storage, so that advice would mislead it (#1009). The identity
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


def _escape_drive_query_value(value: str) -> str:
    """Escape an arbitrary caller-supplied value (a search term, a folder ID) for a
    quoted string in a Drive `files().list()` `q` string: backslash first, then the
    single quote. Unescaped, a `'` in a folder ID could close the string and OR in
    its own terms, e.g. `trashed=true` past the `trashed=false` filter (#1054).
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


class _FolderInvalidation:
    """The callback for `invalidating` around a Drive write that adds, removes, or
    changes a file: it marks dirty the listing of every folder the file is in (#1030).

    `folders` are the ones known before the write; when there are none,
    `found(parents)` takes the ones its response names. A write that only its
    response can place (a rename, a copy without a destination) leaves none known
    if it fails or is abandoned, so the callback then marks every folder listing
    dirty rather than leaving one stale.
    """

    def __init__(self, lc: Any, *folders: str | None):
        self._cache = lc.drive_folder_cache
        self._folders = {f for f in folders if f}

    def found(self, parents: Iterable[str] | None) -> None:
        if not self._folders:
            self._folders = {p for p in parents or () if p}

    def __call__(self) -> None:
        if not self._folders:
            self._cache.mark_all_dirty()
            return
        for folder_id in self._folders:
            self._cache.mark_dirty(folder_id)
