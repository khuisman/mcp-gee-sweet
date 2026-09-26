"""Tests for auth.py — _service_account_creds, _oauth_creds, and the lifespan waterfall."""

import asyncio
import base64
import json
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
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fresh_creds

        with (
            patch(
                "mcp_gee_sweet.auth.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
            patch(
                "mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ),
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
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fresh_creds

        with patch(
            "mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file",
            return_value=mock_flow,
        ) as m:
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
        assert "Delete" in message and "token.json" in message
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
        with patch("mcp_gee_sweet.auth.InstalledAppFlow.from_client_secrets_file") as m:
            m.return_value.run_local_server.return_value = fresh
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
