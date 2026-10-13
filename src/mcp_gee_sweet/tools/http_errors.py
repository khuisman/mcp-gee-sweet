"""Shared HttpError classification.

Every check of a Google API error's `reason` goes through `http_error_has_reason`,
so the matching logic lives in one place. It matches the reason as a quoted
JSON string in the raw body; switching to parsing the structured
`error.errors[].reason` field would happen here.
"""

from googleapiclient.errors import HttpError


def http_error_has_reason(e: BaseException, status: int, reason: str) -> bool:
    """Whether `e` is an HttpError with this status whose body names this reason.
    The reason is matched as a quoted JSON string, so one reason that's a prefix
    of another (cannotChangeOwnAcl / cannotChangeOwnerAcl) can't false-match."""
    return (
        isinstance(e, HttpError)
        and e.resp.status == status
        and f'"{reason}"'.encode() in (e.content or b"")
    )


def is_storage_quota_error(e: BaseException) -> bool:
    """True for Drive's storageQuotaExceeded HttpError (403): the "this identity
    has no personal storage" failure a service account hits on a non-Shared-Drive
    target, which the shared `_SA_QUOTA_ERROR` text explains."""
    return http_error_has_reason(e, 403, "storageQuotaExceeded")
