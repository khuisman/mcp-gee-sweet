"""Shared fake Google API services for unit tests."""

from types import SimpleNamespace


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
