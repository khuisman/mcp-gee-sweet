"""Shared fake Google API services for unit tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from google.oauth2 import service_account


class FakeSheetsService:
    """A minimal spreadsheets().get(...).execute() stand-in. Give it either
    `result` (returned by every execute() call) or `exception` (raised
    instead). Shared so a change to the mocked call shape is made once
    (#392)."""

    _http = SimpleNamespace(credentials=None)

    def __init__(self, *, result: dict | None = None, exception: Exception | None = None):
        self._result = result
        self._exception = exception

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, fields):
        return self

    def execute(self, **kwargs):
        if self._exception is not None:
            raise self._exception
        return self._result


def as_service_account(service):
    """Give a mocked Google API service (a MagicMock or a fake class) service-
    account credentials, so tools.drive._quota_error_text renders
    _SA_QUOTA_ERROR for it. A service without them reads as a user identity
    (#1009)."""
    service._http = SimpleNamespace(credentials=MagicMock(spec=service_account.Credentials))
    return service


def use_local_file_policy(monkeypatch, **env):
    """Install the local-file policy (#796) that `env` (LOCAL_FILE_ACCESS,
    LOCAL_FILE_ROOTS, ...) would resolve to under a stdio launch, for the rest of
    the test. Returns the policy."""
    from mcp_gee_sweet import local_files

    policy = local_files.resolve_policy(env, ["mcp-gee-sweet"])
    monkeypatch.setattr(local_files, "POLICY", policy)
    return policy
