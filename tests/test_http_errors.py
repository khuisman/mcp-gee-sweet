"""Tests for the shared HttpError reason check (tools/http_errors.py, #916)."""

from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools.http_errors import http_error_has_reason, is_storage_quota_error


def _http_error(status: int, reason: str | None = None, content: bytes | None = None):
    resp = MagicMock()
    resp.status = status
    if content is None and reason is not None:
        content = f'{{"error": {{"errors": [{{"reason": "{reason}"}}]}}}}'.encode()
    return HttpError(resp=resp, content=content)


class TestHttpErrorHasReason:
    def test_prefix_reasons_do_not_cross_match(self):
        """cannotChangeOwnAcl and cannotChangeOwnerAcl must not cross-match (#890)."""
        own = _http_error(403, "cannotChangeOwnAcl")
        owner = _http_error(403, "cannotChangeOwnerAcl")

        assert http_error_has_reason(own, 403, "cannotChangeOwnAcl")
        assert not http_error_has_reason(own, 403, "cannotChangeOwnerAcl")
        assert http_error_has_reason(owner, 403, "cannotChangeOwnerAcl")
        assert not http_error_has_reason(owner, 403, "cannotChangeOwnAcl")

    def test_status_must_match(self):
        assert not http_error_has_reason(
            _http_error(403, "cannotChangeOwnerAcl"), 404, "cannotChangeOwnerAcl"
        )

    def test_non_http_error_never_matches(self):
        assert not http_error_has_reason(
            Exception('"cannotChangeOwnerAcl"'), 403, "cannotChangeOwnerAcl"
        )

    def test_empty_content_does_not_match(self):
        assert not http_error_has_reason(_http_error(403, content=b""), 403, "anyReason")


class TestIsStorageQuotaError:
    def test_quota_403_matches(self):
        assert is_storage_quota_error(_http_error(403, "storageQuotaExceeded"))

    def test_other_403_reason_does_not_match(self):
        assert not is_storage_quota_error(_http_error(403, "insufficientPermissions"))

    def test_quota_reason_on_other_status_does_not_match(self):
        assert not is_storage_quota_error(_http_error(500, "storageQuotaExceeded"))

    def test_non_http_error_does_not_match(self):
        assert not is_storage_quota_error(ValueError("storageQuotaExceeded"))
