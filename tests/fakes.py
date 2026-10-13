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
