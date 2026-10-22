import os

import pytest

from mcp_gee_sweet import auth, cache, reauth

# Windows-safe root check: os.geteuid does not exist there, and a direct call
# inside a @pytest.mark.skipif decorator (evaluated at import time) makes the
# whole module fail to collect instead of skipping the affected tests.
IS_ROOT = getattr(os, "geteuid", lambda: -1)() == 0


@pytest.fixture(autouse=True)
def _isolated_cache_db(monkeypatch, tmp_path):
    """Every cache a test opens without its own db_path (a SpreadsheetContext's
    defaults, a lifespan's rebinding) goes to this test's own file, never the
    developer's real cache directory or the legacy shared /tmp file."""
    path = str(tmp_path / "cache.db")
    monkeypatch.setenv("CACHE_DB_PATH", path)
    monkeypatch.setattr(cache, "CACHE_DB_PATH", path)
    monkeypatch.setattr(cache, "_legacy_db_checked", True)
    return path


@pytest.fixture(autouse=True)
def _reset_auth_process_state(monkeypatch):
    """server.main() over stdio, and a lifespan that degrades after a failed consent,
    turn off interactive consent for the rest of the process (#811). Restore it after
    each test so it doesn't leak into the next. Same for the shared in-flight consent
    attempt (#833), stdio's raise-on-auth-failure mode (PR #867), and the OAuth token
    published by a re-authorization (#873)."""
    monkeypatch.setattr(auth, "_interactive_consent", True)
    monkeypatch.setattr(auth, "_interactive_consent_off_reason", auth._STDIO_NO_CONSENT_REASON)
    monkeypatch.setattr(auth, "_consent_attempt", None)
    monkeypatch.setattr(auth, "_raise_auth_failures", False)
    monkeypatch.setattr(auth, "_oauth_generation", 0)
    monkeypatch.setattr(auth, "_oauth_latest_creds", None)
    monkeypatch.setattr(auth, "_gmail_unauthorized_message", None)
    monkeypatch.setattr(reauth, "_rejected_token_stat", reauth._unchanged_token_marker)


@pytest.fixture(autouse=True)
def _no_http_auth_settings(monkeypatch):
    """A developer's .env may set the HTTP auth settings; tests start from neither."""
    monkeypatch.delenv("MCP_SERVER_TOKEN", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_HTTP", raising=False)
