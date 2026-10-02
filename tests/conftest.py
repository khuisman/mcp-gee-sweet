import pytest

from mcp_gee_sweet import auth


@pytest.fixture(autouse=True)
def _reset_auth_process_state(monkeypatch):
    """server.main() over stdio, and a lifespan that degrades after a failed consent,
    turn off interactive consent for the rest of the process (#811). Restore it after
    each test so it doesn't leak into the next. Same for the shared in-flight consent
    attempt (#833) and stdio's raise-on-auth-failure mode (PR #867)."""
    monkeypatch.setattr(auth, "_interactive_consent", True)
    monkeypatch.setattr(auth, "_interactive_consent_off_reason", auth._STDIO_NO_CONSENT_REASON)
    monkeypatch.setattr(auth, "_consent_attempt", None)
    monkeypatch.setattr(auth, "_raise_auth_failures", False)
