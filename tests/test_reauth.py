"""Tests for re-authorizing OAuth from the failing tool call (#873): the refresh-failure
tracking in http_transport.py, the shared tool-call consent in auth.py, and the flow
_timed runs through reauth.py."""

import asyncio
import json
import logging
import threading
import time
import urllib.request
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError
from mcp import UrlElicitationRequiredError
from mcp.server.mcpserver.exceptions import ToolError

import mcp_gee_sweet.auth as auth_module
from mcp_gee_sweet import http_transport, reauth
from mcp_gee_sweet.auth import SpreadsheetContext
from mcp_gee_sweet.server import _timed

_INVALID_GRANT = RefreshError(
    "invalid_grant: Token has been expired or revoked.",
    {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
)
_URL = "https://accounts.example/o/oauth2/auth?client_id=x"


def _creds(refresh_token="rt-old"):
    creds = MagicMock()
    creds.refresh_token = refresh_token
    creds.has_scopes.return_value = True
    return creds


def _oauth_context(creds=None):
    return SpreadsheetContext(
        sheets_service=MagicMock(),
        drive_service=MagicMock(),
        docs_service=MagicMock(),
        calendar_service=MagicMock(),
        activity_service=MagicMock(),
        gmail_service=MagicMock(),
        auth_method="oauth",
        oauth_reauthorizable=True,
        credentials=creds if creds is not None else _creds(),
    )


def _degraded_context(reauthorizable=True):
    return auth_module._degraded_context("No usable OAuth token", reauthorizable=reauthorizable)


def _ctx(context, url_elicitation=True):
    caps = SimpleNamespace(
        elicitation=SimpleNamespace(url=object() if url_elicitation else None, form=object())
    )
    session = SimpleNamespace(client_capabilities=caps, send_elicit_complete=AsyncMock())
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=context, session=session, request=None)
    )


def _attempt(url=_URL):
    attempt = MagicMock()
    attempt.auth_url = url
    attempt.elicitation_id = "elic-1"
    return attempt


def _refresh_inside_tool():
    """What the transport does when Google rejects a refresh mid-call."""
    http_transport._note_refresh_failure(_INVALID_GRANT)


@pytest.fixture
def no_saved_token():
    with patch.object(auth_module, "load_saved_token", AsyncMock(return_value=None)) as load:
        yield load


@pytest.fixture
def offered():
    attempt = _attempt()
    with patch.object(auth_module, "start_user_consent", AsyncMock(return_value=attempt)) as start:
        start.attempt = attempt
        yield start


@pytest.fixture
def no_build():
    with patch.object(
        auth_module,
        "_build_services",
        side_effect=lambda creds: {
            name: MagicMock(name=name) for name in auth_module._SERVICE_VERSIONS
        },
    ) as build:
        yield build


class TestRefreshTracking:
    def test_transport_records_a_rejected_refresh(self):
        creds = MagicMock()
        creds.before_request.side_effect = _INVALID_GRANT
        http = http_transport._RefreshTrackingHttp(creds, http=MagicMock())
        with http_transport.track_refresh_failures() as call, pytest.raises(RefreshError):
            http.request("https://sheets.googleapis.com/x")
        assert call.refresh_error is _INVALID_GRANT

    def test_retryable_refresh_failure_isnt_recorded(self):
        # A token endpoint's own 5xx says nothing about the token.
        with http_transport.track_refresh_failures() as call:
            http_transport._note_refresh_failure(RefreshError("server error", retryable=True))
        assert call.refresh_error is None

    def test_outside_a_tool_call_nothing_is_recorded(self):
        http_transport._note_refresh_failure(_INVALID_GRANT)  # no error, no state

    async def test_recorded_from_worker_threads_and_gathered_tasks(self):
        async def one():
            await asyncio.to_thread(_refresh_inside_tool)

        with http_transport.track_refresh_failures() as call:
            await asyncio.gather(one(), one(), return_exceptions=True)
        assert call.refresh_error is _INVALID_GRANT

    def test_thread_http_rebuilds_when_the_service_credentials_change(self):
        service = MagicMock()
        first = http_transport.thread_http(service)
        assert http_transport.thread_http(service) is first
        service._http.credentials = MagicMock()
        second = http_transport.thread_http(service)
        assert second is not first
        assert second.credentials is service._http.credentials


class TestRefreshFailureDuringCall:
    """#906's requirement: the re-auth offer reaches tools that catch the error and
    return {"error": ...}, not only tools that let it propagate."""

    @staticmethod
    def _catching_tool():
        @_timed
        async def list_files(**kwargs):
            try:
                _refresh_inside_tool()
                raise _INVALID_GRANT
            except Exception as e:
                return {"error": f"List files failed: {e}"}

        return list_files

    @staticmethod
    def _propagating_tool():
        @_timed
        async def list_sheets(**kwargs):
            _refresh_inside_tool()
            raise _INVALID_GRANT

        return list_sheets

    @pytest.mark.parametrize("make_tool", ["_catching_tool", "_propagating_tool"])
    async def test_offers_url_elicitation(self, make_tool, no_saved_token, offered):
        tool = getattr(self, make_tool)()
        ctx = _ctx(_oauth_context())
        with pytest.raises(UrlElicitationRequiredError) as raised:
            await tool(ctx=ctx)
        [elicitation] = raised.value.elicitations
        assert elicitation.url == _URL
        assert elicitation.elicitation_id == "elic-1"
        # args[0], not the RefreshError tuple's repr.
        assert "Token has been expired or revoked" in elicitation.message
        assert "{'error'" not in elicitation.message
        offered.attempt.notify_on_completion.assert_called_once_with(ctx.request_context.session)

    @pytest.mark.parametrize("make_tool", ["_catching_tool", "_propagating_tool"])
    async def test_falls_back_to_url_in_tool_error(self, make_tool, no_saved_token, offered):
        tool = getattr(self, make_tool)()
        with pytest.raises(ToolError) as raised:
            await tool(ctx=_ctx(_oauth_context(), url_elicitation=False))
        assert isinstance(raised.value, reauth.ReauthorizationRequired)
        text = str(raised.value)
        assert _URL in text
        assert "retry the call" in text
        assert "Token has been expired or revoked" in text
        assert "{'error'" not in text

    async def test_newer_saved_token_is_adopted_and_the_call_asks_for_a_retry(self, no_build):
        context = _oauth_context(_creds("rt-old"))
        fresh = _creds("rt-new")
        with (
            patch.object(auth_module, "load_saved_token", AsyncMock(return_value=fresh)),
            patch.object(auth_module, "start_user_consent", AsyncMock()) as start,
            pytest.raises(reauth.ReauthorizationRequired, match="newer OAuth token"),
        ):
            await self._catching_tool()(ctx=_ctx(context))
        start.assert_not_called()
        assert context.credentials is fresh
        assert context.oauth_generation == auth_module._oauth_generation == 1

    async def test_saved_token_with_the_same_grant_isnt_adopted(self, offered):
        context = _oauth_context(_creds("rt-old"))
        with (
            patch.object(auth_module, "load_saved_token", AsyncMock(return_value=_creds("rt-old"))),
            pytest.raises(UrlElicitationRequiredError),
        ):
            await self._catching_tool()(ctx=_ctx(context))
        assert auth_module._oauth_generation == 0

    async def test_consent_that_cant_start_reports_why(self, no_saved_token):
        with (
            patch.object(
                auth_module, "start_user_consent", AsyncMock(side_effect=RuntimeError("no secrets"))
            ),
            pytest.raises(reauth.ReauthorizationRequired, match=r"mcp-gee-sweet auth.*no secrets"),
        ):
            await self._catching_tool()(ctx=_ctx(_oauth_context()))

    async def test_service_account_keeps_the_tool_result(self, offered):
        context = _oauth_context()
        context.auth_method = "service_account"
        context.oauth_reauthorizable = False
        result = await self._catching_tool()(ctx=_ctx(context))
        assert result["error"].startswith("List files failed")
        offered.assert_not_called()

    async def test_successful_call_is_untouched(self, offered):
        @_timed
        async def list_files(**kwargs):
            return ["ok"]

        assert await list_files(ctx=_ctx(_oauth_context())) == ["ok"]
        offered.assert_not_called()

    async def test_access_log_status_is_401(self, no_saved_token, offered):
        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = _Capture()
        access = logging.getLogger("mcp_gee_sweet.access")
        access.addHandler(handler)
        access.setLevel(logging.INFO)
        try:
            with pytest.raises(UrlElicitationRequiredError):
                await self._catching_tool()(ctx=_ctx(_oauth_context()))
        finally:
            access.removeHandler(handler)
        assert " 401 " in records[0]


class TestDegradedConnection:
    async def test_offers_consent_instead_of_running_the_tool(self, no_saved_token, offered):
        body = MagicMock()

        @_timed
        async def list_files(**kwargs):
            body()

        with pytest.raises(UrlElicitationRequiredError) as raised:
            await list_files(ctx=_ctx(_degraded_context()))
        body.assert_not_called()
        assert raised.value.elicitations[0].url == _URL

    async def test_fallback_text_doesnt_repeat_the_restart_instructions(
        self, no_saved_token, offered
    ):
        @_timed
        async def list_files(**kwargs):
            return []

        with pytest.raises(reauth.ReauthorizationRequired) as raised:
            await list_files(ctx=_ctx(_degraded_context(), url_elicitation=False))
        text = str(raised.value)
        assert text.startswith("No usable OAuth token at ")
        assert _URL in text
        assert "restart the server" not in text
        assert text.count("in a terminal") == 1

    async def test_consent_that_cant_start_keeps_the_degraded_message(self, no_saved_token):
        @_timed
        async def list_files(**kwargs):
            return []

        with (
            patch.object(
                auth_module, "start_user_consent", AsyncMock(side_effect=OSError("port in use"))
            ),
            pytest.raises(reauth.ReauthorizationRequired) as raised,
        ):
            await list_files(ctx=_ctx(_degraded_context()))
        text = str(raised.value)
        # _degraded_context's own message, then why no link could be offered.
        assert text.startswith("No usable OAuth token (The server couldn't offer")
        assert "port in use" in text

    async def test_usable_saved_token_is_adopted_and_the_tool_runs(self, no_build, offered):
        context = _degraded_context()
        fresh = _creds("rt-new")

        @_timed
        async def list_files(**kwargs):
            return ["ok"]

        with patch.object(auth_module, "load_saved_token", AsyncMock(return_value=fresh)):
            assert await list_files(ctx=_ctx(context)) == ["ok"]
        offered.assert_not_called()
        assert context.unauthorized_message is None
        assert context.auth_method == "oauth"
        assert context.credentials is fresh
        assert context.sheets_service is not None

    async def test_not_reauthorizable_keeps_the_plain_message(self, offered):
        @_timed
        async def list_files(**kwargs):
            return []

        with pytest.raises(ToolError, match="No usable OAuth token"):
            await list_files(ctx=_ctx(_degraded_context(reauthorizable=False)))
        offered.assert_not_called()

    async def test_token_another_connection_got_is_adopted_first(self, no_build, offered):
        auth_module.publish_oauth_credentials(_creds("rt-new"))
        context = _degraded_context()
        assert context.oauth_generation == 1  # built after the publish: already current
        context.oauth_generation = 0

        @_timed
        async def list_files(**kwargs):
            return ["ok"]

        with patch.object(auth_module, "load_saved_token", AsyncMock()) as load:
            assert await list_files(ctx=_ctx(context)) == ["ok"]
        load.assert_not_called()
        offered.assert_not_called()


class TestUserConsent:
    """auth.start_user_consent and the attempt it runs, with a real callback server."""

    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch, tmp_path):
        monkeypatch.setattr(auth_module, "_CONSENT_POLL_SECONDS", 0.05)
        monkeypatch.setattr(auth_module, "TOKEN_PATH", str(tmp_path / "token.json"))
        self.flow = MagicMock()
        self.flow.authorization_url.return_value = (_URL, "st")
        self.flow.credentials.to_json.return_value = json.dumps({"refresh_token": "rt-new"})
        self.flow.credentials.has_scopes.return_value = True
        self.tmp_path = tmp_path
        # Never a browser for a tool call's consent.
        with (
            patch.object(auth_module, "_new_flow", return_value=self.flow),
            patch.object(auth_module.webbrowser, "get", side_effect=AssertionError("browser")),
        ):
            yield

    async def _until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)

    async def _callback(self):
        redirect = self.flow.redirect_uri

        def hit():
            with urllib.request.urlopen(f"{redirect}?code=c&state=st", timeout=5) as resp:
                return resp.read()

        return await asyncio.to_thread(hit)

    async def test_one_listener_shared_by_every_failing_call(self):
        first, second = await asyncio.gather(
            auth_module.start_user_consent(), auth_module.start_user_consent()
        )
        assert first is second
        assert first.auth_url == _URL
        first.stop.set()

    async def test_callback_saves_the_token_and_publishes_it(self, no_build):
        attempt = await auth_module.start_user_consent()
        session = SimpleNamespace(send_elicit_complete=AsyncMock())
        attempt.notify_on_completion(session)
        assert b"completed" in await self._callback()
        await asyncio.wait_for(asyncio.shield(attempt.future), 5)
        await self._until(lambda: session.send_elicit_complete.await_count == 1)
        session.send_elicit_complete.assert_awaited_once_with(attempt.elicitation_id)
        token = self.tmp_path / "token.json"
        assert json.loads(token.read_text()) == {"refresh_token": "rt-new"}
        assert token.stat().st_mode & 0o777 == 0o600
        assert auth_module._oauth_generation == 1
        context = _oauth_context()
        assert auth_module.adopt_published_credentials(context)
        assert context.credentials is self.flow.credentials

    async def test_lifespan_waiter_leaving_doesnt_stop_a_tool_calls_attempt(self):
        attempt = await auth_module.start_user_consent()
        waiter = asyncio.ensure_future(auth_module._await_server_consent(["s"]))
        await self._until(lambda: attempt.waiters == 1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not attempt.stop.is_set()
        attempt.stop.set()

    async def test_failed_attempt_leaves_lifespan_consent_on(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_CONSENT_TIMEOUT_SECONDS", 0.1)
        attempt = await auth_module.start_user_consent()
        with pytest.raises(auth_module.OAuthConsentRequiredError):
            await asyncio.wait_for(asyncio.shield(attempt.future), 5)
        assert auth_module._interactive_consent is True
        # The next failing call gets a fresh attempt and URL.
        assert await auth_module.start_user_consent() is not attempt
        auth_module._consent_attempt.stop.set()

    async def test_works_with_stdio_consent_off(self):
        auth_module.set_interactive_consent(False)
        attempt = await auth_module.start_user_consent()
        assert attempt.auth_url == _URL
        attempt.stop.set()

    async def test_tool_call_joins_the_lifespans_pending_consent(self):
        release = threading.Event()

        def serve(flow, timeout_seconds, stop, on_url=None):
            on_url("https://accounts.example/lifespan")
            while not release.is_set() and not stop.is_set():
                time.sleep(0.01)
            raise auth_module._ConsentStopped()

        with patch.object(auth_module, "_serve_consent", serve):
            waiter = asyncio.ensure_future(auth_module._await_server_consent(["s"]))
            await self._until(
                lambda: (
                    auth_module._consent_attempt is not None
                    and auth_module._consent_attempt.auth_url is not None
                )
            )
            attempt = await auth_module.start_user_consent()
            assert attempt.auth_url == "https://accounts.example/lifespan"
            waiter.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await waiter


class TestLoadSavedToken:
    async def test_needing_consent_is_none(self):
        with patch.object(
            auth_module, "_oauth_creds", side_effect=auth_module._consent_off_error()
        ):
            assert await auth_module.load_saved_token() is None

    async def test_usable_token_is_returned(self):
        creds = _creds()
        with patch.object(auth_module, "_oauth_creds", return_value=creds):
            assert await auth_module.load_saved_token() is creds


class TestLifespanMarksReauthorizable:
    async def test_degraded_oauth_start_is_reauthorizable(self, monkeypatch):
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "oauth")
        with patch.object(
            auth_module, "_oauth_creds", side_effect=auth_module._consent_off_error()
        ):
            context = await auth_module._build_context()
        assert context.unauthorized_message
        assert context.oauth_reauthorizable is True

    async def test_oauth_start_records_its_credentials(self, monkeypatch, no_build):
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "oauth")
        creds = _creds()
        with patch.object(auth_module, "_oauth_creds", return_value=creds):
            context = await auth_module._build_context()
        assert context.oauth_reauthorizable is True
        assert context.credentials is creds

    async def test_service_account_start_isnt_reauthorizable(self, monkeypatch, no_build):
        monkeypatch.setattr(auth_module, "AUTH_METHOD", "service_account")
        with patch.object(auth_module, "_service_account_creds", return_value=MagicMock()):
            context = await auth_module._build_context()
        assert context.oauth_reauthorizable is False
