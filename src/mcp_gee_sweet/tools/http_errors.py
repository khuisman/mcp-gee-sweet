"""Shared matching for Google API HTTP status and reason names."""

from googleapiclient.errors import HttpError


def http_error_has_reason(error: BaseException, status: int, reason: str) -> bool:
    """Match a complete quoted reason name, avoiding prefix/suffix false matches."""
    return (
        isinstance(error, HttpError)
        and error.resp.status == status
        and f'"{reason}"'.encode() in (error.content or b"")
    )
