import pytest

from mcp_gee_sweet import auth


@pytest.fixture(autouse=True)
def _reset_auth_process_state(monkeypatch):
    """server.main() and spreadsheet_lifespan set process-wide auth flags (#811):
    main() over stdio turns off interactive consent, and a degraded lifespan leaves
    every tool raising. Restore both after each test so neither leaks into the next."""
    monkeypatch.setattr(auth, "_interactive_consent", True)
    monkeypatch.setattr(auth, "_oauth_unauthorized_message", None)
