"""Tests for auth.py — _service_account_creds, _oauth_creds, and the lifespan waterfall."""

import asyncio
import base64
import json
import socket
import threading
import time
import urllib.request
import webbrowser
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from google.auth import (
    compute_engine,
    external_account_authorized_user,
    identity_pool,
    impersonated_credentials,
)
from google.oauth2 import gdch_credentials, service_account
from google.oauth2.credentials import Credentials as UserCredentials

import mcp_gee_sweet.auth as auth_module
from mcp_gee_sweet.auth import (
    _is_service_account_credential,
    _oauth_creds,
    _service_account_creds,
    get_lifespan_context,
    spreadsheet_lifespan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64_encode(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _run_lifespan(monkeypatch, auth_method, mock_oauth, mock_sa, mock_adc):
    """Run spreadsheet_lifespan with mocked helpers and googleapiclient.build."""
    monkeypatch.setattr(auth_module, "AUTH_METHOD", auth_method)
    mock_build = MagicMock()
    server = MagicMock()

    with (
        patch("mcp_gee_sweet.auth._oauth_creds", mock_oauth),
        patch("mcp_gee_sweet.auth._service_account_creds", mock_sa),
        patch("google.auth.default", mock_adc),
        patch("googleapiclient.discovery.build", mock_build),
    ):

        async def _run():
            async with spreadsheet_lifespan(server) as ctx:
                return ctx

        return asyncio.run(_run())


# ---------------------------------------------------------------------------
# _service_account_creds
# ---------------------------------------------------------------------------


class TestServiceAccountCreds:
    def test_credentials_config_calls_from_info(self, monkeypatch):
        sa_info = {"type": "service_account", "project_id": "p"}
        monkeypatch.setattr(auth_module, "CREDENTIALS_CONFIG", _b64_encode(sa_info))
        mock_creds = MagicMock()
        with patch(
            "mcp_gee_sweet.auth.service_account.Credentials.from_service_account_info",
            return_value=mock_creds,
        ) as m:
            result = _service_account_creds()
            m.assert_called_once_with(sa_info, scopes=auth_module.SCOPES)
            assert result is mock_creds

    def test_credentials_config_takes_precedence_over_path(self, monkeypatch, tmp_path):
        sa_info = {"type": "service_account"}
        monkeypatch.setattr(auth_module, "CREDENTIALS_CONFIG", _b64_encode(sa_info))
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH", str(tmp_path / "sa.json"))
        with (
            patch("mcp_gee_sweet.auth.service_account.Credentials.from_service_account_info"),
            patch(
                "mcp_gee_sweet.auth.service_account.Credentials.from_service_account_file"
            ) as mock_file,
        ):
            _service_account_creds()
            mock_file.assert_not_called()

    def test_service_account_path_file_exists(self, monkeypatch, tmp_path):
        sa_path = tmp_path / "sa.json"
        sa_path.write_text("{}")  # file must exist; content doesn't matter (mocked)
        monkeypatch.setattr(auth_module, "CREDENTIALS_CONFIG", None)
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH", str(sa_path))
        mock_creds = MagicMock()
        with patch(
            "mcp_gee_sweet.auth.service_account.Credentials.from_service_account_file",
            return_value=mock_creds,
        ) as m:
            result = _service_account_creds()
            m.assert_called_once_with(str(sa_path), scopes=auth_module.SCOPES)
            assert result is mock_creds

    def test_service_account_path_missing_returns_none(self, monkeypatch):
        monkeypatch.setattr(auth_module, "CREDENTIALS_CONFIG", None)
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH", "/nonexistent/sa.json")
        assert _service_account_creds() is None

    def test_neither_configured_returns_none(self, monkeypatch):
        monkeypatch.setattr(auth_module, "CREDENTIALS_CONFIG", None)
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH", "/nonexistent/sa.json")
        assert _service_account_creds() is None


# ---------------------------------------------------------------------------
# _is_service_account_credential
# ---------------------------------------------------------------------------


class TestIsServiceAccountCredential:
    def test_service_account_credentials_is_service_account(self):
        creds = service_account.Credentials.__new__(service_account.Credentials)
        assert _is_service_account_credential(creds) is True

    def test_compute_engine_credentials_is_service_account(self):
        """ADC on GCE/Cloud Run/GKE resolves to the metadata-service identity,
        which has the same no-personal-Drive limitations as an explicit service
        account key (#506)."""
        creds = compute_engine.Credentials.__new__(compute_engine.Credentials)
        assert _is_service_account_credential(creds) is True

    def test_user_oauth_credentials_is_not_service_account(self):
        """Both a real OAuth flow and a user-backed ADC session
        (`gcloud auth application-default login`) resolve to this exact class."""
        creds = UserCredentials.__new__(UserCredentials)
        assert _is_service_account_credential(creds) is False

    def test_arbitrary_object_is_not_service_account(self):
        assert _is_service_account_credential(object()) is False

    def test_workload_identity_federation_is_service_account(self):
        """PR #613 QA round 1: google.auth._default's own dispatch table can
        resolve ADC to a Workload Identity Federation credential — `identity_pool`
        here as a representative `external_account.Credentials` subclass (`aws`
        and `pluggable` are the other two; `external_account.Credentials` itself
        can't be instantiated, even via __new__, since it's abstract)."""
        creds = identity_pool.Credentials.__new__(identity_pool.Credentials)
        assert _is_service_account_credential(creds) is True

    def test_impersonated_service_account_is_service_account(self):
        """Common in CI: ADC resolving to an impersonated service account."""
        creds = impersonated_credentials.Credentials.__new__(impersonated_credentials.Credentials)
        assert _is_service_account_credential(creds) is True

    def test_gdch_service_account_is_service_account(self):
        creds = gdch_credentials.ServiceAccountCredentials.__new__(
            gdch_credentials.ServiceAccountCredentials
        )
        assert _is_service_account_credential(creds) is True

    def test_workforce_identity_federation_authorized_user_is_not_service_account(self):
        """Deliberately excluded: per its own module docstring, this credential
        class "usually access[es] resources on behalf of a user (resource
        owner)" via Workforce Identity Federation — a real human authenticated
        through an external IdP, not a service identity."""
        creds = external_account_authorized_user.Credentials.__new__(
            external_account_authorized_user.Credentials
        )
        assert _is_service_account_credential(creds) is False


# ---------------------------------------------------------------------------
# _oauth_creds
# ---------------------------------------------------------------------------


class TestOAuthCreds:
    def test_valid_token_file_returns_creds(self, monkeypatch, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"token": "tok"}))
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = True
        with patch(
            "mcp_gee_sweet.auth.Credentials.from_authorized_user_info",
            return_value=mock_creds,
        ):
            result = _oauth_creds()
            assert result is mock_creds

    def test_expired_token_refreshes_and_saves(self, monkeypatch, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"token": "old"}))
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-tok"
        mock_creds.to_json.return_value = json.dumps({"token": "new"})

        with patch(
            "mcp_gee_sweet.auth.Credentials.from_authorized_user_info",
            return_value=mock_creds,
        ):
            result = _oauth_creds()
            mock_creds.refresh.assert_called_once()
            assert result is mock_creds
            assert json.loads(token_path.read_text())["token"] == "new"

    def test_expired_token_refresh_fails_falls_through_to_flow(self, monkeypatch, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"token": "old"}))
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-tok"
        mock_creds.refresh.side_effect = Exception("network error")

        fresh_creds = MagicMock()
        fresh_creds.to_json.return_value = json.dumps({"token": "fresh"})

        with (
            patch(
                "mcp_gee_sweet.auth.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file"),
            patch("mcp_gee_sweet.auth._serve_consent", return_value=fresh_creds),
        ):
            result = _oauth_creds()
            assert result is fresh_creds

    def test_no_token_file_runs_flow(self, monkeypatch, tmp_path):
        token_path = tmp_path / "token.json"  # does not exist
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))

        fresh_creds = MagicMock()
        fresh_creds.to_json.return_value = json.dumps({"token": "new"})

        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as m,
            patch("mcp_gee_sweet.auth._serve_consent", return_value=fresh_creds),
        ):
            result = _oauth_creds()
            m.assert_called_once_with(str(creds_path), auth_module.SCOPES)
            assert result is fresh_creds
            assert token_path.exists()

    def test_no_token_no_credentials_file_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(tmp_path / "missing.json"))
        with pytest.raises(RuntimeError, match="not found"):
            _oauth_creds()


def _token_info(scopes, *, expired=False):
    info = {
        "token": "tok",
        "refresh_token": "refresh-tok",
        "client_id": "cid",
        "client_secret": "secret",
        "expiry": "2000-01-01T00:00:00Z" if expired else "2999-01-01T00:00:00Z",
    }
    if scopes is not None:
        info["scopes"] = scopes
    return info


class TestRequiredScopes:
    def test_gmail_enabled_requests_gmail_modify_only(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_gmail_enabled", True)
        scopes = auth_module.required_scopes()
        assert "https://www.googleapis.com/auth/gmail.modify" in scopes
        # #790: modify covers read and send; the narrower scopes were redundant.
        assert "https://www.googleapis.com/auth/gmail.readonly" not in scopes
        assert "https://www.googleapis.com/auth/gmail.send" not in scopes

    def test_gmail_disabled_requests_no_gmail_scope(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_gmail_enabled", False)
        scopes = auth_module.required_scopes()
        assert scopes == auth_module.BASE_SCOPES
        assert not any("gmail" in s for s in scopes)

    def test_service_account_uses_required_scopes(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_gmail_enabled", False)
        monkeypatch.setattr(auth_module, "CREDENTIALS_CONFIG", _b64_encode({"type": "x"}))
        with patch("mcp_gee_sweet.auth.service_account.Credentials.from_service_account_info") as m:
            _service_account_creds()
        assert m.call_args.kwargs["scopes"] == auth_module.BASE_SCOPES


class TestOAuthScopeCheck:
    """#790: a token authorized for fewer scopes than the registered tools need
    fails fast with a clear message instead of refreshing into `invalid_scope` and
    then opening a browser consent (or hanging a headless deployment)."""

    def _setup(self, monkeypatch, tmp_path, info, *, gmail_enabled=True):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps(info))
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        monkeypatch.setattr(auth_module, "_gmail_enabled", gmail_enabled)
        monkeypatch.setattr(auth_module, "_gmail_unauthorized_message", None)
        return token_path

    def test_pre_gmail_token_with_gmail_enabled_degrades_without_flow(self, monkeypatch, tmp_path):
        # PR #807 QA round 1: a Gmail-only shortfall must not stop the server from
        # starting — a stdio client drops stderr and would only see "Connection
        # closed". The token loads at its own granted scopes and Gmail is flagged.
        self._setup(monkeypatch, tmp_path, _token_info(auth_module.BASE_SCOPES))
        with patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow:
            creds = _oauth_creds()
        flow.assert_not_called()
        assert sorted(creds.scopes) == sorted(auth_module.BASE_SCOPES)
        message = auth_module.get_gmail_unauthorized_message()
        assert message is not None
        assert "gmail.modify" in message
        assert "mcp-gee-sweet auth" in message and "token.json" in message
        assert "ENABLED_TOOLS" in message  # the no-Gmail way out

    def test_lifespan_starts_on_gmail_only_shortfall(self, monkeypatch, tmp_path):
        # The whole point of degrading: spreadsheet_lifespan (real _oauth_creds, no
        # mock) yields a context instead of raising, so the server finishes starting.
        self._setup(monkeypatch, tmp_path, _token_info(auth_module.BASE_SCOPES))
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "oauth")
        with patch("googleapiclient.discovery.build"):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()) as ctx:
                    return ctx

            ctx = asyncio.run(_run())
        assert ctx.auth_method == "oauth"
        assert auth_module.get_gmail_unauthorized_message() is not None

    def test_missing_base_scope_still_fails_clearly_without_flow(self, monkeypatch, tmp_path):
        granted = [s for s in auth_module.SCOPES if not s.endswith("/calendar")]
        self._setup(monkeypatch, tmp_path, _token_info(granted))
        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow,
            pytest.raises(auth_module.MissingOAuthScopesError) as exc,
        ):
            _oauth_creds()
        flow.assert_not_called()
        assert "auth/calendar" in str(exc.value)
        assert auth_module.get_gmail_unauthorized_message() is None

    def test_missing_base_and_gmail_scopes_still_fails(self, monkeypatch, tmp_path):
        granted = [s for s in auth_module.BASE_SCOPES if not s.endswith("/calendar")]
        self._setup(monkeypatch, tmp_path, _token_info(granted))
        with pytest.raises(auth_module.MissingOAuthScopesError) as exc:
            _oauth_creds()
        assert "auth/calendar" in str(exc.value) and "gmail.modify" in str(exc.value)

    def test_full_token_clears_a_stale_gmail_flag(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, _token_info(auth_module.SCOPES))
        monkeypatch.setattr(auth_module, "_gmail_unauthorized_message", "stale")
        _oauth_creds()
        assert auth_module.get_gmail_unauthorized_message() is None

    def test_pre_gmail_token_with_gmail_disabled_loads_normally(self, monkeypatch, tmp_path):
        self._setup(
            monkeypatch, tmp_path, _token_info(auth_module.BASE_SCOPES), gmail_enabled=False
        )
        creds = _oauth_creds()
        assert isinstance(creds, UserCredentials)
        assert sorted(creds.scopes) == sorted(auth_module.BASE_SCOPES)

    def test_token_with_all_scopes_loads_with_its_own_saved_scopes(self, monkeypatch, tmp_path):
        # A token from #786's era also holds gmail.readonly/gmail.send. It passes
        # the check, and keeps its own scope list, so a later refresh never asks for
        # anything it wasn't granted.
        saved = [*auth_module.SCOPES, "https://www.googleapis.com/auth/gmail.readonly"]
        self._setup(monkeypatch, tmp_path, _token_info(saved))
        creds = _oauth_creds()
        assert sorted(creds.scopes) == sorted(saved)

    def test_token_without_saved_scopes_keeps_prior_behavior(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path, _token_info(None))
        creds = _oauth_creds()
        assert sorted(creds.scopes) == sorted(auth_module.SCOPES)

    def test_refresh_invalid_scope_fails_clearly_without_flow(self, monkeypatch, tmp_path):
        # The saved record can overstate the grant (e.g. a hand-built token.json).
        # Here even the Gmail-less retry fails, so a base scope is what's ungranted.
        token_path = self._setup(
            monkeypatch, tmp_path, _token_info(auth_module.SCOPES, expired=True)
        )
        before = token_path.read_text()
        with (
            patch(
                "mcp_gee_sweet.auth.Credentials.refresh",
                side_effect=Exception("('invalid_scope: Bad Request', {})"),
            ) as refresh,
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow,
            pytest.raises(auth_module.MissingOAuthScopesError),
        ):
            _oauth_creds()
        flow.assert_not_called()
        assert refresh.call_count == 2  # original + the Gmail-less retry
        assert token_path.read_text() == before
        assert auth_module.get_gmail_unauthorized_message() is None

    def test_refresh_invalid_scope_only_for_gmail_degrades(self, monkeypatch, tmp_path):
        token_path = self._setup(
            monkeypatch, tmp_path, _token_info(auth_module.SCOPES, expired=True)
        )
        before = token_path.read_text()
        with (
            patch(
                "mcp_gee_sweet.auth.Credentials.refresh",
                side_effect=[Exception("('invalid_scope: Bad Request', {})"), None],
            ),
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow,
        ):
            creds = _oauth_creds()
        flow.assert_not_called()
        assert sorted(creds.scopes) == sorted(auth_module.BASE_SCOPES)
        assert "gmail.modify" in (auth_module.get_gmail_unauthorized_message() or "")
        # Saved token keeps its own record; re-authorizing stays delete-and-restart.
        assert token_path.read_text() == before

    def test_refresh_invalid_scope_with_gmail_disabled_has_nothing_to_drop(
        self, monkeypatch, tmp_path
    ):
        self._setup(
            monkeypatch,
            tmp_path,
            _token_info(auth_module.BASE_SCOPES, expired=True),
            gmail_enabled=False,
        )
        with (
            patch(
                "mcp_gee_sweet.auth.Credentials.refresh",
                side_effect=Exception("('invalid_scope: Bad Request', {})"),
            ) as refresh,
            pytest.raises(auth_module.MissingOAuthScopesError),
        ):
            _oauth_creds()
        assert refresh.call_count == 1

    def test_no_token_flow_requests_only_required_scopes(self, monkeypatch, tmp_path):
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        monkeypatch.setattr(auth_module, "_gmail_enabled", False)
        fresh = MagicMock()
        fresh.to_json.return_value = "{}"
        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as m,
            patch("mcp_gee_sweet.auth._serve_consent", return_value=fresh),
        ):
            _oauth_creds()
        m.assert_called_once_with(str(creds_path), auth_module.BASE_SCOPES)


# ---------------------------------------------------------------------------
# spreadsheet_lifespan — AUTH_METHOD pinning and waterfall
# ---------------------------------------------------------------------------


class TestLifespanAuthMethod:
    def test_pinned_service_account_uses_sa_creds(self, monkeypatch):
        sa_creds = service_account.Credentials.__new__(service_account.Credentials)
        ctx = _run_lifespan(
            monkeypatch,
            auth_method="service_account",
            mock_oauth=MagicMock(side_effect=Exception("should not call")),
            mock_sa=MagicMock(return_value=sa_creds),
            mock_adc=MagicMock(side_effect=Exception("should not call")),
        )
        assert ctx.auth_method == "service_account"
        assert ctx.is_service_account_identity is True

    def test_pinned_service_account_no_creds_raises(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_raise_auth_failures", True)  # stdio
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "service_account")
        with (
            patch("mcp_gee_sweet.auth._service_account_creds", return_value=None),
            patch("googleapiclient.discovery.build"),
            pytest.raises(RuntimeError, match="service_account"),
        ):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()):
                    pass

            asyncio.run(_run())

    def test_pinned_oauth_calls_oauth_creds(self, monkeypatch):
        user_creds = UserCredentials.__new__(UserCredentials)
        ctx = _run_lifespan(
            monkeypatch,
            auth_method="oauth",
            mock_oauth=MagicMock(return_value=user_creds),
            mock_sa=MagicMock(side_effect=Exception("should not call")),
            mock_adc=MagicMock(side_effect=Exception("should not call")),
        )
        assert ctx.auth_method == "oauth"
        assert ctx.is_service_account_identity is False

    def test_pinned_adc_uses_google_auth_default(self, monkeypatch):
        mock_adc_creds = MagicMock()
        ctx = _run_lifespan(
            monkeypatch,
            auth_method="adc",
            mock_oauth=MagicMock(side_effect=Exception("should not call")),
            mock_sa=MagicMock(side_effect=Exception("should not call")),
            mock_adc=MagicMock(return_value=(mock_adc_creds, "test-project")),
        )
        assert ctx.auth_method == "adc"

    def test_pinned_adc_user_backed_sets_is_service_account_identity_false(self, monkeypatch):
        user_creds = UserCredentials.__new__(UserCredentials)
        ctx = _run_lifespan(
            monkeypatch,
            auth_method="adc",
            mock_oauth=MagicMock(side_effect=Exception("should not call")),
            mock_sa=MagicMock(side_effect=Exception("should not call")),
            mock_adc=MagicMock(return_value=(user_creds, "test-project")),
        )
        assert ctx.auth_method == "adc"
        assert ctx.is_service_account_identity is False

    def test_pinned_adc_service_account_backed_sets_is_service_account_identity_true(
        self, monkeypatch
    ):
        """Issue #506: ADC on GCE/Cloud Run/GKE, or GOOGLE_APPLICATION_CREDENTIALS
        pointed at a key file, resolves to a service-account credential — the
        context needs to flag this even though auth_method itself stays "adc"."""
        sa_creds = compute_engine.Credentials.__new__(compute_engine.Credentials)
        ctx = _run_lifespan(
            monkeypatch,
            auth_method="adc",
            mock_oauth=MagicMock(side_effect=Exception("should not call")),
            mock_sa=MagicMock(side_effect=Exception("should not call")),
            mock_adc=MagicMock(return_value=(sa_creds, "test-project")),
        )
        assert ctx.auth_method == "adc"
        assert ctx.is_service_account_identity is True

    def test_pinned_adc_no_adc_raises(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_raise_auth_failures", True)  # stdio
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "adc")
        with (
            patch("google.auth.default", side_effect=Exception("no ADC")),
            patch("googleapiclient.discovery.build"),
            pytest.raises(RuntimeError, match="ADC"),
        ):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()):
                    pass

            asyncio.run(_run())


class TestLifespanWaterfall:
    def test_waterfall_missing_oauth_scopes_is_not_masked_by_service_account(self, monkeypatch):
        # #790: a token on disk means OAuth is intended; silently switching to a
        # service account would hide the scope problem behind cryptic Gmail 400s.
        monkeypatch.setattr(auth_module, "_raise_auth_failures", True)  # stdio
        sa = MagicMock()
        with pytest.raises(auth_module.MissingOAuthScopesError):
            _run_lifespan(
                monkeypatch,
                None,
                MagicMock(side_effect=auth_module.MissingOAuthScopesError("missing")),
                sa,
                MagicMock(),
            )
        sa.assert_not_called()

    def test_waterfall_oauth_wins(self, monkeypatch):
        mock_oauth_creds = MagicMock()
        ctx = _run_lifespan(
            monkeypatch,
            auth_method=None,
            mock_oauth=MagicMock(return_value=mock_oauth_creds),
            mock_sa=MagicMock(side_effect=Exception("should not call")),
            mock_adc=MagicMock(side_effect=Exception("should not call")),
        )
        assert ctx.auth_method == "oauth"

    def test_waterfall_oauth_fails_sa_wins(self, monkeypatch):
        mock_sa_creds = MagicMock()
        ctx = _run_lifespan(
            monkeypatch,
            auth_method=None,
            mock_oauth=MagicMock(side_effect=Exception("no OAuth")),
            mock_sa=MagicMock(return_value=mock_sa_creds),
            mock_adc=MagicMock(side_effect=Exception("should not call")),
        )
        assert ctx.auth_method == "service_account"

    def test_waterfall_oauth_and_sa_fail_adc_wins(self, monkeypatch):
        mock_adc_creds = MagicMock()
        ctx = _run_lifespan(
            monkeypatch,
            auth_method=None,
            mock_oauth=MagicMock(side_effect=Exception("no OAuth")),
            mock_sa=MagicMock(return_value=None),
            mock_adc=MagicMock(return_value=(mock_adc_creds, "proj")),
        )
        assert ctx.auth_method == "adc"

    def test_waterfall_all_fail_raises(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_raise_auth_failures", True)  # stdio
        monkeypatch.setattr(auth_module, "AUTH_METHOD", None)
        with (
            patch("mcp_gee_sweet.auth._oauth_creds", side_effect=Exception("no OAuth")),
            patch("mcp_gee_sweet.auth._service_account_creds", return_value=None),
            patch("google.auth.default", side_effect=Exception("no ADC")),
            patch("googleapiclient.discovery.build"),
            pytest.raises(RuntimeError, match="All authentication"),
        ):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()):
                    pass

            asyncio.run(_run())

    def test_waterfall_context_sets_auth_method_on_context(self, monkeypatch):
        """SpreadsheetContext.auth_method is set correctly by the lifespan."""
        mock_sa_creds = MagicMock()
        ctx = _run_lifespan(
            monkeypatch,
            auth_method=None,
            mock_oauth=MagicMock(side_effect=Exception("no OAuth")),
            mock_sa=MagicMock(return_value=mock_sa_creds),
            mock_adc=MagicMock(side_effect=Exception("should not call")),
        )
        assert ctx.auth_method == "service_account"
        # Confirm all six services were built
        assert ctx.sheets_service is not None
        assert ctx.drive_service is not None
        assert ctx.docs_service is not None
        assert ctx.calendar_service is not None
        assert ctx.activity_service is not None
        assert ctx.gmail_service is not None


# ---------------------------------------------------------------------------
# get_lifespan_context — module-level singleton lifecycle (issue #175, PR #642
# QA round 1): the lifespan's `finally` block must reset `_lifespan_context`
# back to None on exit, not just set it on entry. Left as `finally: pass`, the
# static server://auth-status resource would silently keep serving a torn-down
# SpreadsheetContext after the lifespan exits instead of raising the
# RuntimeError get_lifespan_context()'s own docstring promises.
# ---------------------------------------------------------------------------


class TestGetLifespanContext:
    def test_raises_before_lifespan_has_ever_started(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_lifespan_context", None)
        with pytest.raises(RuntimeError, match="has not started"):
            get_lifespan_context()

    def test_returns_context_while_lifespan_is_active(self, monkeypatch):
        sa_creds = service_account.Credentials.__new__(service_account.Credentials)
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "service_account")
        mock_build = MagicMock()

        with (
            patch("mcp_gee_sweet.auth._service_account_creds", return_value=sa_creds),
            patch("googleapiclient.discovery.build", mock_build),
        ):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()) as ctx:
                    assert get_lifespan_context() is ctx

            asyncio.run(_run())

    def test_raises_again_after_lifespan_exits(self, monkeypatch):
        """Regression test: `finally: pass` left the module-level singleton
        pointing at the torn-down context after exit instead of resetting it,
        so a later get_lifespan_context() call silently returned stale state
        instead of the RuntimeError it's supposed to raise outside a request.
        """
        sa_creds = service_account.Credentials.__new__(service_account.Credentials)
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "service_account")
        mock_build = MagicMock()

        with (
            patch("mcp_gee_sweet.auth._service_account_creds", return_value=sa_creds),
            patch("googleapiclient.discovery.build", mock_build),
        ):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()):
                    pass

            asyncio.run(_run())

        with pytest.raises(RuntimeError, match="has not started"):
            get_lifespan_context()


# ---------------------------------------------------------------------------
# #811: no usable token under stdio (or an unfinished consent) degrades instead of
# blocking startup on a consent flow whose prompt went to the protocol channel.
# ---------------------------------------------------------------------------


class TestConsentRequired:
    def _setup(self, monkeypatch, tmp_path):
        token_path = tmp_path / "token.json"  # does not exist
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        return token_path

    def test_stdio_no_token_raises_without_running_flow(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        auth_module.set_interactive_consent(False)
        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow,
            pytest.raises(auth_module.OAuthConsentRequiredError, match="mcp-gee-sweet auth"),
        ):
            _oauth_creds()
        flow.assert_not_called()

    def test_stdio_failed_refresh_raises_without_running_flow(self, monkeypatch, tmp_path):
        # An expired token whose refresh fails (e.g. invalid_grant) used to fall
        # through to the consent flow — the same hang, reached from a token on disk.
        token_path = self._setup(monkeypatch, tmp_path)
        token_path.write_text(json.dumps({"token": "old"}))
        auth_module.set_interactive_consent(False)
        stale = MagicMock(expired=True, refresh_token="r")
        stale.refresh.side_effect = Exception("invalid_grant")
        with (
            patch("mcp_gee_sweet.auth.Credentials.from_authorized_user_info", return_value=stale),
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow,
            pytest.raises(auth_module.OAuthConsentRequiredError),
        ):
            _oauth_creds()
        flow.assert_not_called()

    def test_stdio_missing_client_secrets_still_reports_not_found(self, monkeypatch, tmp_path):
        # No client secrets means OAuth isn't configured at all: a plain failure the
        # waterfall moves past, not a consent problem.
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(tmp_path / "missing.json"))
        auth_module.set_interactive_consent(False)
        with pytest.raises(RuntimeError, match="not found") as exc:
            _oauth_creds()
        assert not isinstance(exc.value, auth_module.OAuthConsentRequiredError)

    def test_interactive_flow_is_bounded_and_saves_the_token(self, monkeypatch, tmp_path):
        token_path = self._setup(monkeypatch, tmp_path)
        fresh = MagicMock()
        fresh.to_json.return_value = json.dumps({"token": "new"})
        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file"),
            patch("mcp_gee_sweet.auth._serve_consent", return_value=fresh) as serve,
        ):
            assert _oauth_creds() is fresh
        assert serve.call_args.args[1] == auth_module._CONSENT_TIMEOUT_SECONDS
        assert token_path.exists()

    def test_interactive_flow_timeout_raises_consent_required(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file"),
            patch(
                "mcp_gee_sweet.auth._serve_consent",
                side_effect=auth_module.WSGITimeoutError("timed out"),
            ),
            pytest.raises(auth_module.OAuthConsentRequiredError, match="within 300s"),
        ):
            _oauth_creds()

    @pytest.mark.parametrize(
        "error",
        [
            Exception("(access_denied) The user denied the request"),  # clicked Deny
            Warning("Scope has changed from ... to ..."),  # unticked a scope
            Exception("(mismatching_state) CSRF Warning!"),  # a stray request
        ],
    )
    def test_any_consent_failure_degrades_like_a_timeout(self, monkeypatch, tmp_path, error):
        # PR #828 QA round 1: only the timeout degraded; Deny etc. escaped the lifespan.
        self._setup(monkeypatch, tmp_path)
        with (
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file"),
            patch("mcp_gee_sweet.auth._serve_consent", side_effect=error),
            pytest.raises(auth_module.OAuthConsentRequiredError, match="consent failed") as exc,
        ):
            _oauth_creds()
        assert str(error) in str(exc.value)
        assert "mcp-gee-sweet auth" in str(exc.value)

    def test_after_a_failed_attempt_the_reason_names_it_not_stdio(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        auth_module._degrade_unauthorized("first connection's message")
        with pytest.raises(auth_module.OAuthConsentRequiredError) as exc:
            _oauth_creds()
        assert "earlier browser consent" in str(exc.value)
        assert "stdio" not in str(exc.value)

    def test_transport_error_on_refresh_keeps_the_token(self, monkeypatch, tmp_path):
        # PR #828 QA round 1: Google unreachable at startup (network not up yet) isn't
        # a bad token; it must not degrade and tell the user to re-authorize.
        from google.auth.exceptions import TransportError

        token_path = self._setup(monkeypatch, tmp_path)
        token_path.write_text(json.dumps({"token": "old"}))
        auth_module.set_interactive_consent(False)
        stale = MagicMock(expired=True, refresh_token="r")
        stale.refresh.side_effect = TransportError("connection refused")
        with (
            patch("mcp_gee_sweet.auth.Credentials.from_authorized_user_info", return_value=stale),
            patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow,
        ):
            assert _oauth_creds() is stale
        flow.assert_not_called()
        assert json.loads(token_path.read_text()) == {"token": "old"}

    def test_refreshed_token_is_rewritten_owner_only(self, monkeypatch, tmp_path):
        token_path = self._setup(monkeypatch, tmp_path)
        token_path.write_text(json.dumps({"token": "old"}))
        token_path.chmod(0o644)
        creds = MagicMock(expired=True, refresh_token="r")
        creds.to_json.return_value = json.dumps({"token": "new"})
        with patch("mcp_gee_sweet.auth.Credentials.from_authorized_user_info", return_value=creds):
            _oauth_creds()
        assert token_path.stat().st_mode & 0o777 == 0o600


# ---------------------------------------------------------------------------
# #833: under SSE the consent wait used to run on the event loop, stalling every
# other connection and keeping SIGTERM from stopping the server.
# ---------------------------------------------------------------------------


def _blocking_serve(release: threading.Event, result, started: threading.Event | None = None):
    """A stand-in for auth._serve_consent that waits like the real one: until
    `release`, or until `stop` is set."""

    def serve(flow, timeout_seconds, stop):
        if started is not None:
            started.set()
        while not release.is_set():
            if stop.is_set():
                raise auth_module._ConsentStopped()
            time.sleep(0.01)
        return result

    return serve


class TestServeConsent:
    def _flow(self):
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.example/auth?x=1", "st")
        return flow

    def _serve_in_thread(self, flow, timeout_seconds, stop):
        box = {}

        def run():
            try:
                box["result"] = auth_module._serve_consent(flow, timeout_seconds, stop)
            except BaseException as e:
                box["error"] = e

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, box

    def _wait_for_redirect_uri(self, flow):
        deadline = time.monotonic() + 5
        while not isinstance(flow.redirect_uri, str):
            assert time.monotonic() < deadline, "callback server never started"
            time.sleep(0.01)
        return flow.redirect_uri

    def test_callback_completes_the_flow_with_the_prompt_on_stderr(self, monkeypatch, capsys):
        monkeypatch.setattr(auth_module, "_CONSENT_POLL_SECONDS", 0.05)
        flow = self._flow()
        with patch.object(auth_module.webbrowser, "get", side_effect=webbrowser.Error("none")):
            thread, box = self._serve_in_thread(flow, 30, threading.Event())
            redirect = self._wait_for_redirect_uri(flow)
            with urllib.request.urlopen(f"{redirect}?code=c&state=st", timeout=5) as resp:
                assert b"completed" in resp.read()
            thread.join(5)
        assert box == {"result": flow.credentials}
        flow.fetch_token.assert_called_once_with(
            authorization_response=f"{redirect.replace('http', 'https', 1)}?code=c&state=st"
        )
        out, err = capsys.readouterr()
        assert out == ""
        assert (
            "Please visit this URL to authorize this application: https://accounts.example" in err
        )
        port = int(redirect.rstrip("/").rsplit(":", 1)[1])
        with pytest.raises(OSError):
            socket.create_connection(("localhost", port), timeout=1).close()

    def test_stop_ends_the_wait_and_closes_the_port(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_CONSENT_POLL_SECONDS", 0.05)
        flow = self._flow()
        stop = threading.Event()
        with patch.object(auth_module.webbrowser, "get"):
            thread, box = self._serve_in_thread(flow, 300, stop)
            redirect = self._wait_for_redirect_uri(flow)
            stop.set()
            thread.join(2)
        assert not thread.is_alive()
        assert isinstance(box.get("error"), auth_module._ConsentStopped)
        flow.fetch_token.assert_not_called()
        port = int(redirect.rstrip("/").rsplit(":", 1)[1])
        with pytest.raises(OSError):
            socket.create_connection(("localhost", port), timeout=1).close()

    def test_times_out(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_CONSENT_POLL_SECONDS", 0.05)
        with (
            patch.object(auth_module.webbrowser, "get"),
            pytest.raises(auth_module.WSGITimeoutError),
        ):
            auth_module._serve_consent(self._flow(), 0.1, threading.Event())

    def test_a_silent_connection_doesnt_hold_off_the_timeout(self, monkeypatch, capsys):
        # PR #867 QA round 1: a connection that sends nothing (browser preconnect,
        # port scanner) blocked handle_request() in readline(), so the deadline and
        # stop checks never ran again until the client hung up.
        assert 0 < (auth_module._CallbackHandler.timeout or 0) <= 10
        monkeypatch.setattr(auth_module, "_CONSENT_POLL_SECONDS", 0.05)
        monkeypatch.setattr(auth_module._CallbackHandler, "timeout", 0.3)  # keep the test fast
        flow = self._flow()
        with patch.object(auth_module.webbrowser, "get"):
            thread, box = self._serve_in_thread(flow, 0.5, threading.Event())
            redirect = self._wait_for_redirect_uri(flow)
            port = int(redirect.rstrip("/").rsplit(":", 1)[1])
            silent = socket.create_connection(("localhost", port), timeout=5)
            try:
                thread.join(3)
                assert not thread.is_alive(), "the silent connection held off the timeout"
            finally:
                silent.close()
        assert isinstance(box.get("error"), auth_module.WSGITimeoutError)
        assert "Traceback" not in capsys.readouterr().err


class TestConsentOffEventLoop:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        monkeypatch.setattr(auth_module, "_CONSENT_POLL_SECONDS", 0.05)
        from sse_starlette.sse import AppStatus

        monkeypatch.setattr(AppStatus, "should_exit", False)
        with patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file"):
            yield

    def _fresh(self):
        fresh = MagicMock()
        fresh.to_json.return_value = json.dumps({"token": "new"})
        return fresh

    def test_event_loop_keeps_running_during_the_wait(self):
        release, started, fresh = threading.Event(), threading.Event(), self._fresh()

        async def _run():
            consent = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            ticks = 0
            for _ in range(5):  # the loop is free while the consent waits
                await asyncio.sleep(0.01)
                ticks += 1
            assert not consent.done()
            release.set()
            return ticks, await consent

        with patch("mcp_gee_sweet.auth._serve_consent", _blocking_serve(release, fresh, started)):
            ticks, creds = asyncio.run(_run())
        assert ticks == 5
        assert creds is fresh

    def test_consent_runs_on_a_daemon_thread(self):
        release, started = threading.Event(), threading.Event()

        async def _run():
            consent = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            threads = [t for t in threading.enumerate() if t.name == "oauth-consent"]
            release.set()
            await consent
            return threads

        with patch(
            "mcp_gee_sweet.auth._serve_consent", _blocking_serve(release, self._fresh(), started)
        ):
            threads = asyncio.run(_run())
        assert len(threads) == 1 and threads[0].daemon

    def test_concurrent_connections_share_one_consent(self):
        release, fresh = threading.Event(), self._fresh()
        serve = MagicMock(side_effect=_blocking_serve(release, fresh))

        async def _run():
            first = asyncio.create_task(auth_module._oauth_creds_async())
            second = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.sleep(0.1)
            release.set()
            return await asyncio.gather(first, second)

        with patch("mcp_gee_sweet.auth._serve_consent", serve):
            results = asyncio.run(_run())
        assert results == [fresh, fresh]
        serve.assert_called_once()

    def test_consent_failure_reaches_every_waiter(self):
        # The failure is held until both connections have joined the attempt: each
        # one's token load runs on its own thread, so without the gate the second
        # could arrive after the failure (see the next test). That's what made this
        # flaky in CI (PR #867).
        release = threading.Event()

        def _fail_when_released(flow, timeout_seconds, stop):
            release.wait(5)
            raise auth_module.WSGITimeoutError("timed out")

        serve = MagicMock(side_effect=_fail_when_released)

        async def _run():
            first = asyncio.create_task(auth_module._oauth_creds_async())
            second = asyncio.create_task(auth_module._oauth_creds_async())
            deadline = time.monotonic() + 5
            while (attempt := auth_module._consent_attempt) is None or attempt.waiters < 2:
                assert time.monotonic() < deadline, "both connections never joined"
                await asyncio.sleep(0.01)
            release.set()
            return await asyncio.gather(first, second, return_exceptions=True)

        with patch("mcp_gee_sweet.auth._serve_consent", serve):
            results = asyncio.run(_run())
        assert all(isinstance(r, auth_module.OAuthConsentRequiredError) for r in results)
        assert all("within 300s" in str(r) for r in results)
        serve.assert_called_once()

    def test_a_connection_arriving_after_a_failure_doesnt_start_another_consent(self):
        # PR #867 CI flake: the token load decides consent is needed on a thread. If an
        # attempt fails (turning consent off) before that caller gets back to the
        # loop, it must not start a second consent.
        auth_module.set_interactive_consent(False, reason="an earlier browser consent failed")
        serve = MagicMock()

        async def _run():
            return await auth_module._oauth_creds_async()

        with (
            patch(
                "mcp_gee_sweet.auth._oauth_creds",
                side_effect=auth_module._ConsentDeferred(auth_module.BASE_SCOPES),
            ),
            patch("mcp_gee_sweet.auth._serve_consent", serve),
            pytest.raises(
                auth_module.OAuthConsentRequiredError, match="an earlier browser consent failed"
            ),
        ):
            asyncio.run(_run())
        serve.assert_not_called()

    def test_a_load_that_raced_a_successful_consent_reads_the_token_again(self):
        # PR #867 QA round 4: B's token load runs on its own thread. If it reads
        # TOKEN_PATH just before A's consent saves the token, B used to reach the loop
        # after A finished and start a second consent. It now reloads the token.
        fresh, saved = self._fresh(), self._fresh()
        b_loading, a_done = threading.Event(), threading.Event()
        calls = []

        def _load(**kwargs):
            calls.append(threading.current_thread().name)
            if len(calls) == 1:  # B: reads before A saves, then stalls past A's success
                b_loading.set()
                a_done.wait(5)
                raise auth_module._ConsentDeferred(auth_module.BASE_SCOPES)
            if len(calls) == 2:  # A: no token yet
                raise auth_module._ConsentDeferred(auth_module.BASE_SCOPES)
            return saved  # B's reload: the token A saved

        serve = MagicMock(return_value=fresh)

        async def _run():
            b = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(b_loading.wait, 5)
            a = await auth_module._oauth_creds_async()
            a_done.set()
            return a, await b

        with (
            patch("mcp_gee_sweet.auth._oauth_creds", side_effect=_load),
            patch("mcp_gee_sweet.auth._serve_consent", serve),
        ):
            a, b = asyncio.run(_run())
        assert a is fresh
        assert b is saved
        serve.assert_called_once()

    def test_a_consent_needed_after_an_earlier_success_still_runs(self):
        # The reload is only for a load that overlapped the success. A connection
        # whose load starts afterwards and still finds no usable token (e.g. the token
        # was deleted to re-authorize) gets a new consent, not the old credentials.
        first, second = self._fresh(), self._fresh()
        serve = MagicMock(side_effect=[first, second])

        async def _run():
            return await auth_module._oauth_creds_async(), await auth_module._oauth_creds_async()

        with (
            patch(
                "mcp_gee_sweet.auth._oauth_creds",
                side_effect=auth_module._ConsentDeferred(auth_module.BASE_SCOPES),
            ),
            patch("mcp_gee_sweet.auth._serve_consent", serve),
        ):
            results = asyncio.run(_run())
        assert results == (first, second)
        assert serve.call_count == 2

    def test_server_shutdown_ends_the_wait_and_stops_the_thread(self):
        from sse_starlette.sse import AppStatus

        release, started = threading.Event(), threading.Event()

        async def _run():
            consent = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            AppStatus.should_exit = True  # what uvicorn's SIGTERM handler sets
            with pytest.raises(auth_module.OAuthConsentRequiredError, match="shut down"):
                await asyncio.wait_for(consent, 2)
            return auth_module._consent_attempt

        with patch(
            "mcp_gee_sweet.auth._serve_consent", _blocking_serve(release, self._fresh(), started)
        ):
            attempt = asyncio.run(_run())
        assert attempt.stop.is_set()
        deadline = time.monotonic() + 2
        while any(t.name == "oauth-consent" for t in threading.enumerate()):
            assert time.monotonic() < deadline, "consent thread kept running"
            time.sleep(0.01)

    def test_lifespan_degrades_on_shutdown_mid_consent(self, monkeypatch):
        from sse_starlette.sse import AppStatus

        monkeypatch.setattr(auth_module, "AUTH_METHOD", "oauth")
        release, started = threading.Event(), threading.Event()

        async def _run():
            async def _shutdown_once_waiting():
                await asyncio.to_thread(started.wait, 5)
                AppStatus.should_exit = True

            trigger = asyncio.create_task(_shutdown_once_waiting())
            async with spreadsheet_lifespan(MagicMock()) as ctx:
                await trigger
                return ctx

        with (
            patch(
                "mcp_gee_sweet.auth._serve_consent",
                _blocking_serve(release, self._fresh(), started),
            ),
            patch("googleapiclient.discovery.build") as build,
        ):
            ctx = asyncio.run(_run())
        assert ctx.auth_method == "none"
        assert "shut down before the browser consent completed" in ctx.unauthorized_message
        build.assert_not_called()

    def test_cancelling_the_last_waiter_stops_the_wait(self):
        release, started = threading.Event(), threading.Event()

        async def _run():
            consent = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            consent.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consent
            return auth_module._consent_attempt

        with patch(
            "mcp_gee_sweet.auth._serve_consent", _blocking_serve(release, self._fresh(), started)
        ):
            attempt = asyncio.run(_run())
        assert attempt.stop.is_set()
        # Not a failed attempt: a later connection may still run the consent.
        assert auth_module._interactive_consent is True

    def test_cancelling_one_of_two_waiters_keeps_the_wait(self):
        release, started, fresh = threading.Event(), threading.Event(), self._fresh()

        async def _run():
            first = asyncio.create_task(auth_module._oauth_creds_async())
            second = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            await asyncio.sleep(0.05)
            first.cancel()
            await asyncio.sleep(0.05)
            stopped = auth_module._consent_attempt.stop.is_set()
            release.set()
            return stopped, await second

        with patch("mcp_gee_sweet.auth._serve_consent", _blocking_serve(release, fresh, started)):
            stopped, creds = asyncio.run(_run())
        assert stopped is False
        assert creds is fresh

    def test_failed_attempt_turns_off_consent_even_when_the_waterfall_falls_back(self, monkeypatch):
        # PR #867 QA round 1: a waterfall that falls back to a service account after
        # a failed consent never reached _degrade_unauthorized, so the next connection
        # prompted again and waited out the timeout again.
        monkeypatch.setattr(auth_module, "AUTH_METHOD", None)
        serve = MagicMock(side_effect=auth_module.WSGITimeoutError("timed out"))

        async def _run():
            async with spreadsheet_lifespan(MagicMock()) as ctx:
                return ctx

        with (
            patch("mcp_gee_sweet.auth._serve_consent", serve),
            patch("mcp_gee_sweet.auth._service_account_creds", return_value=MagicMock()),
            patch("googleapiclient.discovery.build"),
        ):
            first = asyncio.run(_run())
            second = asyncio.run(_run())
        assert first.auth_method == second.auth_method == "service_account"
        assert auth_module._interactive_consent is False
        serve.assert_called_once()

    def test_consent_is_off_before_any_waiter_sees_the_failure(self):
        # PR #867 QA round 1: turning consent off in the lifespan left a gap of a few
        # loop hops in which a new connection saw a settled attempt with consent
        # still on, and started a second one.
        seen = []

        async def _run():
            consent = asyncio.create_task(auth_module._oauth_creds_async())
            consent.add_done_callback(lambda _: seen.append(auth_module._interactive_consent))
            with pytest.raises(auth_module.OAuthConsentRequiredError):
                await consent

        with patch(
            "mcp_gee_sweet.auth._serve_consent",
            side_effect=auth_module.WSGITimeoutError("timed out"),
        ):
            asyncio.run(_run())
        assert seen == [False]

    def test_token_refresh_runs_off_the_event_loop(self):
        # PR #867 QA round 1: a hanging token endpoint blocked the loop the same way
        # the consent wait did.
        release, started, fresh = threading.Event(), threading.Event(), self._fresh()

        def _hanging_refresh(**kwargs):
            started.set()
            release.wait(5)
            return fresh

        async def _run():
            loading = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            for _ in range(5):
                await asyncio.sleep(0.01)
            assert not loading.done()
            release.set()
            return await loading

        with patch("mcp_gee_sweet.auth._oauth_creds", side_effect=_hanging_refresh):
            assert asyncio.run(_run()) is fresh

    def test_shutdown_ends_a_hanging_token_refresh(self):
        from sse_starlette.sse import AppStatus

        release, started = threading.Event(), threading.Event()

        def _hanging_refresh(**kwargs):
            started.set()
            release.wait(5)

        async def _run():
            loading = asyncio.create_task(auth_module._oauth_creds_async())
            await asyncio.to_thread(started.wait, 5)
            AppStatus.should_exit = True
            with pytest.raises(auth_module.OAuthConsentRequiredError, match="loading the token"):
                await asyncio.wait_for(loading, 2)

        try:
            with patch("mcp_gee_sweet.auth._oauth_creds", side_effect=_hanging_refresh):
                asyncio.run(_run())
        finally:
            release.set()


class TestAuthFailureDegradesOutsideStdio:
    """PR #867 QA round 2: over SSE a lifespan that raises after its first await
    leaves a raced-in POST parked forever in mcp's transport, and SIGTERM waits on
    it (python-sdk#3616). Outside stdio, an auth failure starts the connection
    without Google access instead, with the failure as every tool's error."""

    def _run(self, monkeypatch, auth_method, **patches):
        monkeypatch.setattr(auth_module, "AUTH_METHOD", auth_method)
        build = MagicMock()
        with ExitStack() as stack:
            stack.enter_context(patch("googleapiclient.discovery.build", build))
            for name, kw in patches.items():
                stack.enter_context(patch(f"mcp_gee_sweet.auth.{name}", **kw))

            async def _run():
                async with spreadsheet_lifespan(MagicMock()) as ctx:
                    assert get_lifespan_context() is ctx
                    return ctx

            ctx = asyncio.run(_run())
        build.assert_not_called()
        assert ctx.auth_method == "none"
        assert ctx.sheets_service is None
        return ctx

    def test_missing_scopes_degrades_with_the_reauthorize_message(self, monkeypatch):
        error = auth_module.MissingOAuthScopesError("missing drive scope; run mcp-gee-sweet auth")
        ctx = self._run(monkeypatch, "oauth", _oauth_creds={"side_effect": error})
        assert ctx.unauthorized_message == "missing drive scope; run mcp-gee-sweet auth"

    def test_missing_scopes_in_the_waterfall_still_isnt_masked(self, monkeypatch):
        # #790's rule holds: the service account isn't used to hide the shortfall.
        error = auth_module.MissingOAuthScopesError("missing drive scope")
        sa = MagicMock(return_value=MagicMock())
        ctx = self._run(
            monkeypatch,
            None,
            _oauth_creds={"side_effect": error},
            _service_account_creds={"new": sa},
        )
        assert ctx.unauthorized_message == "missing drive scope"
        sa.assert_not_called()

    def test_all_methods_failed_degrades_and_names_the_cause(self, monkeypatch):
        monkeypatch.setattr(auth_module, "AUTH_METHOD", None)
        with patch("google.auth.default", side_effect=Exception("no ADC")):
            ctx = self._run(
                monkeypatch,
                None,
                _oauth_creds={"side_effect": Exception("no OAuth")},
                _service_account_creds={"return_value": None},
            )
        assert "All authentication methods failed" in ctx.unauthorized_message
        assert "no ADC" in ctx.unauthorized_message

    def test_pinned_service_account_without_creds_degrades(self, monkeypatch):
        ctx = self._run(
            monkeypatch, "service_account", _service_account_creds={"return_value": None}
        )
        assert "AUTH_METHOD=service_account but no credentials found" in ctx.unauthorized_message

    def test_lifespan_context_is_cleared_after_a_degraded_connection(self, monkeypatch):
        self._run(monkeypatch, "service_account", _service_account_creds={"return_value": None})
        with pytest.raises(RuntimeError, match="has not started"):
            get_lifespan_context()


class TestConsentTimeoutSetting:
    def test_default_is_300(self, monkeypatch):
        monkeypatch.delenv("OAUTH_CONSENT_TIMEOUT_SECONDS", raising=False)
        assert auth_module._consent_timeout_seconds() == 300

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OAUTH_CONSENT_TIMEOUT_SECONDS", "5")
        assert auth_module._consent_timeout_seconds() == 5

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OAUTH_CONSENT_TIMEOUT_SECONDS", "soon")
        assert auth_module._consent_timeout_seconds() == 300


class TestLifespanDegradesOnConsentRequired:
    _consent = auth_module.OAuthConsentRequiredError("run mcp-gee-sweet auth")

    def test_pinned_oauth_starts_without_services(self, monkeypatch):
        build = MagicMock()
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "oauth")
        with (
            patch("mcp_gee_sweet.auth._oauth_creds", side_effect=self._consent),
            patch("googleapiclient.discovery.build", build),
        ):

            async def _run():
                async with spreadsheet_lifespan(MagicMock()) as ctx:
                    assert get_lifespan_context() is ctx
                    return ctx

            ctx = asyncio.run(_run())
        assert ctx.auth_method == "none"
        assert ctx.sheets_service is None and ctx.gmail_service is None
        assert ctx.unauthorized_message == "run mcp-gee-sweet auth"
        build.assert_not_called()
        with pytest.raises(RuntimeError, match="has not started"):
            get_lifespan_context()

    def test_waterfall_consent_required_still_falls_through_to_service_account(self, monkeypatch):
        ctx = _run_lifespan(
            monkeypatch,
            None,
            MagicMock(side_effect=self._consent),
            MagicMock(return_value=MagicMock()),
            MagicMock(side_effect=Exception("should not call")),
        )
        assert ctx.auth_method == "service_account"
        assert ctx.unauthorized_message is None

    def test_waterfall_consent_required_with_nothing_else_degrades(self, monkeypatch):
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH_EXPLICIT", False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        ctx = _run_lifespan(
            monkeypatch,
            None,
            MagicMock(side_effect=self._consent),
            MagicMock(return_value=None),
            MagicMock(side_effect=Exception("no ADC")),
        )
        assert ctx.auth_method == "none"
        assert ctx.unauthorized_message == "run mcp-gee-sweet auth"

    def test_waterfall_degrade_reports_an_explicitly_configured_fallback(
        self, monkeypatch, tmp_path
    ):
        # PR #828 QA round 1: a broken SERVICE_ACCOUNT_PATH / ADC setup must not hide
        # behind "run mcp-gee-sweet auth".
        missing_sa = str(tmp_path / "sa.json")
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH", missing_sa)
        monkeypatch.setattr(auth_module, "SERVICE_ACCOUNT_PATH_EXPLICIT", True)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "adc.json"))
        ctx = _run_lifespan(
            monkeypatch,
            None,
            MagicMock(side_effect=self._consent),
            MagicMock(return_value=None),
            MagicMock(side_effect=Exception("adc.json was not found")),
        )
        assert ctx.unauthorized_message.startswith("run mcp-gee-sweet auth")
        assert missing_sa in ctx.unauthorized_message
        assert "adc.json was not found" in ctx.unauthorized_message

    def test_degrading_turns_off_further_consent_attempts(self, monkeypatch):
        # PR #828 QA round 1: under SSE the lifespan runs per connection. After one
        # failed attempt, later connections must not block the loop on another.
        _run_lifespan(
            monkeypatch,
            "oauth",
            MagicMock(side_effect=self._consent),
            MagicMock(),
            MagicMock(),
        )
        assert auth_module._interactive_consent is False

    def test_connections_keep_their_own_degraded_state(self, monkeypatch):
        # A later connection that finds a token (after `mcp-gee-sweet auth`) must not
        # clear the message an earlier, still-open degraded connection relies on.
        degraded = _run_lifespan(
            monkeypatch, "oauth", MagicMock(side_effect=self._consent), MagicMock(), MagicMock()
        )
        healthy = _run_lifespan(
            monkeypatch, "oauth", MagicMock(return_value=MagicMock()), MagicMock(), MagicMock()
        )
        assert degraded.unauthorized_message == "run mcp-gee-sweet auth"
        assert healthy.unauthorized_message is None
        assert healthy.auth_method == "oauth"


class TestRunAuthCommand:
    def test_runs_flow_for_required_scopes_and_saves_token(self, monkeypatch, tmp_path, capsys):
        token_path = tmp_path / "token.json"
        token_path.write_text(json.dumps({"token": "old"}))  # overwritten, not reused
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(token_path))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        monkeypatch.setattr(auth_module, "_gmail_enabled", False)
        fresh = MagicMock()
        fresh.to_json.return_value = json.dumps({"token": "new"})
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fresh
        with patch(
            "mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow
        ) as m:
            assert auth_module.run_auth_command(open_browser=False) == 0
        m.assert_called_once_with(str(creds_path), auth_module.BASE_SCOPES)
        assert mock_flow.run_local_server.call_args.kwargs["open_browser"] is False
        assert json.loads(token_path.read_text())["token"] == "new"
        assert token_path.stat().st_mode & 0o777 == 0o600
        assert str(token_path) in capsys.readouterr().out

    def test_missing_client_secrets_exits_nonzero(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(tmp_path / "missing.json"))
        assert auth_module.run_auth_command() == 1
        assert "not found" in capsys.readouterr().err

    def test_missing_token_directory_fails_before_consent(self, monkeypatch, tmp_path, capsys):
        # PR #828 QA round 1: this used to fail in open() *after* the consent,
        # losing the refresh token the user had just granted.
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "nope" / "token.json"))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        with patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as flow:
            assert auth_module.run_auth_command() == 1
        flow.assert_not_called()
        assert "doesn't exist" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "error",
        [
            Exception("(access_denied) The user denied the request"),
            Warning("Scope has changed from ... to ..."),
            ValueError("Client secrets must be for a web or installed app."),
        ],
    )
    def test_flow_failures_print_an_error_not_a_traceback(
        self, monkeypatch, tmp_path, capsys, error
    ):
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        monkeypatch.setattr(auth_module, "CREDENTIALS_PATH", str(creds_path))
        with patch(
            "mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file", side_effect=error
        ):
            assert auth_module.run_auth_command() == 1
        err = capsys.readouterr().err
        assert err.startswith("ERROR: ")
        assert str(error) in err
        assert not (tmp_path / "token.json").exists()
