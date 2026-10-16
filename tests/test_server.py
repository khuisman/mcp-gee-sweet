"""Tests for server.py (_parse_enabled_tools, _auth_status_json, _timed, tool strict args)."""

import importlib.metadata
import inspect
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import anyio
import pytest
import uvicorn
from google.auth.exceptions import RefreshError
from googleapiclient import errors as googleapiclient_errors
from googleapiclient.errors import HttpError
from httplib2 import Response
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError, UnexpectedToolError
from pydantic import ValidationError
from starlette.requests import Request
from uvicorn.importer import import_from_string

from mcp_gee_sweet import auth as auth_module
from mcp_gee_sweet import local_files, server
from mcp_gee_sweet.server import (
    _auth_status_json,
    _parse_enabled_tools,
    _timed,
    _version_logger,
    get_auth_status,
    get_spreadsheet_info,
    main,
    mcp,
    tool,
)
from mcp_gee_sweet.sse_shutdown import SingleResponseGuard

from .fakes import use_local_file_policy


def _http_error(status: int, message: str) -> HttpError:
    body = json.dumps({"error": {"code": status, "message": message}}).encode()
    return HttpError(Response({"status": status}), body, uri="https://example.invalid/x")


class TestAllToolsAreAsync:
    """Regression test for issue #183: _timed's wrapper is unconditionally
    `async def wrapper(...): return await func(...)`, so any tool registered as
    a plain `def` breaks with TypeError at call time. This is invisible to the
    rest of the test suite — every other test captures the raw inner function
    via a fake tool registry, bypassing _timed entirely. Already hit once for
    tools/cache.py's get_cache_ttl/set_cache_ttl/refresh_cache (zero .execute()
    calls, so missed by the .execute()-driven async conversion sweep); this
    guards against it recurring for any future tool with no I/O of its own.
    """

    def test_every_registered_tool_is_async(self):
        tools = mcp._tool_manager.list_tools()
        assert tools, "no tools registered — registration may be broken"
        sync_tools = sorted(
            t.name for t in tools if not inspect.iscoroutinefunction(inspect.unwrap(t.fn))
        )
        assert sync_tools == [], f"non-async tool(s) found: {sync_tools}"


class TestGmailScopeGate:
    """#790: auth requests Gmail's mailbox scope only when a Gmail tool is registered."""

    def test_default_registration_enables_gmail(self):
        # The test process registers every tool (no ENABLED_TOOLS filter).
        assert "mcp_gee_sweet.tools.gmail" in server._registered_tool_modules
        assert auth_module._gmail_enabled is True

    def test_filter_without_gmail_tools_leaves_gmail_module_unregistered(self, monkeypatch):
        recorded: set[str] = set()
        monkeypatch.setattr(server, "ENABLED_TOOLS", {"get_sheet_data"})
        monkeypatch.setattr(server, "_registered_tool_modules", recorded)

        def list_messages():  # stands in for a Gmail tool
            pass

        list_messages.__module__ = "mcp_gee_sweet.tools.gmail"
        tool()(list_messages)
        assert recorded == set()


class TestParseEnabledTools:
    def test_no_filter_returns_none(self, monkeypatch):
        monkeypatch.delenv("ENABLED_TOOLS", raising=False)
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        assert _parse_enabled_tools() is None

    def test_env_var_single_tool(self, monkeypatch):
        monkeypatch.setenv("ENABLED_TOOLS", "get_sheet_data")
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        result = _parse_enabled_tools()
        assert result == {"get_sheet_data"}

    def test_env_var_multiple_tools(self, monkeypatch):
        monkeypatch.setenv("ENABLED_TOOLS", "get_sheet_data,update_cells,list_sheets")
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        result = _parse_enabled_tools()
        assert result == {"get_sheet_data", "update_cells", "list_sheets"}

    def test_env_var_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("ENABLED_TOOLS", "get_sheet_data, update_cells , list_sheets")
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        result = _parse_enabled_tools()
        assert result == {"get_sheet_data", "update_cells", "list_sheets"}

    def test_cli_arg_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("ENABLED_TOOLS", "update_cells")
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--include-tools", "get_sheet_data"])
        result = _parse_enabled_tools()
        assert result == {"get_sheet_data"}

    def test_cli_arg_multiple_tools(self, monkeypatch):
        monkeypatch.delenv("ENABLED_TOOLS", raising=False)
        monkeypatch.setattr(
            sys, "argv", ["mcp-gee-sweet", "--include-tools", "get_sheet_data,list_sheets"]
        )
        result = _parse_enabled_tools()
        assert result == {"get_sheet_data", "list_sheets"}

    def test_empty_env_var_returns_none(self, monkeypatch):
        monkeypatch.setenv("ENABLED_TOOLS", "")
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        assert _parse_enabled_tools() is None

    def test_cli_arg_missing_value_falls_through_to_env(self, monkeypatch):
        monkeypatch.setenv("ENABLED_TOOLS", "get_sheet_data")
        # --include-tools is the last arg with no following value
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--include-tools"])
        result = _parse_enabled_tools()
        assert result == {"get_sheet_data"}


class TestAuthStatusResource:
    """server://auth-status resource returns correct capabilities per auth method."""

    def _get_status(self, auth_method, is_service_account_identity=False):
        return json.loads(_auth_status_json(auth_method, is_service_account_identity))

    def test_service_account_cannot_create_in_personal_drive(self):
        status = self._get_status("service_account")
        assert status["auth_method"] == "service_account"
        assert status["can_create_in_personal_drive"] is False

    def test_service_account_lists_limited_tools(self):
        status = self._get_status("service_account")
        assert len(status["limited_tools"]) > 0
        assert "create_spreadsheet" in status["limited_tools"]
        assert "create_doc" in status["limited_tools"]
        assert "copy_file" in status["limited_tools"]
        assert "upload_file" in status["limited_tools"]
        assert "upload_local_file" in status["limited_tools"]
        assert "upload_local_folder" in status["limited_tools"]
        assert "sync_folder" in status["limited_tools"]
        assert "transfer_ownership" in status["limited_tools"]

    def test_service_account_storage_quota_limitation(self):
        """Issue #447: each failure class gets its own reason/alternatives — a tool
        limited for one reason (no storage quota) shouldn't share text with a tool
        limited for a different reason (no personal Drive identity)."""
        status = self._get_status("service_account")
        quota = next(
            lim for lim in status["limitations"] if lim["category"] == "no_drive_storage_quota"
        )
        assert "create_spreadsheet" in quota["tools"]
        assert "transfer_ownership" not in quota["tools"]
        assert "storage quota" in quota["reason"].lower()
        # sync_folder is listed by exact name, with its direction caveat in the
        # reason text (#516); guard the caveat against a reword dropping it (#526).
        assert "sync_folder" in quota["tools"]
        assert "sync_folder" in quota["reason"]
        assert "upload and bidirectional" in quota["reason"]
        assert quota["alternatives"] is not None

    def test_service_account_transfer_ownership_limitation(self):
        status = self._get_status("service_account")
        identity = next(
            lim for lim in status["limitations"] if lim["category"] == "no_personal_drive_identity"
        )
        assert identity["tools"] == ["transfer_ownership"]
        assert "identity" in identity["reason"].lower()
        # Alternatives must not claim ADC fixes this — ADC may itself resolve to a
        # service-account-backed credential with the same limitation (see #506).
        assert "adc" not in identity["alternatives"].lower()

    def test_service_account_gmail_limitation_lists_every_gmail_tool(self):
        # #790: auth-status is what docs/auth.md points users at for "which tools
        # won't work on a service account". Compared against the tools the gmail
        # module actually registers, so a new Gmail tool can't be left off.
        status = self._get_status("service_account")
        mailbox = next(lim for lim in status["limitations"] if lim["category"] == "no_user_mailbox")
        gmail_tools = sorted(
            t.name
            for t in mcp._tool_manager.list_tools()
            if inspect.unwrap(t.fn).__module__ == "mcp_gee_sweet.tools.gmail"
        )
        assert gmail_tools, "no Gmail tools registered — registration may be broken"
        assert sorted(mailbox["tools"]) == gmail_tools
        assert set(gmail_tools) <= set(status["limited_tools"])
        assert "adc" not in mailbox["alternatives"].lower()

    def test_adc_service_account_identity_also_reports_gmail_limitation(self):
        status = self._get_status("adc", is_service_account_identity=True)
        assert "send_message" in status["limited_tools"]

    def test_oauth_can_create_in_personal_drive(self):
        status = self._get_status("oauth")
        assert status["auth_method"] == "oauth"
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
        assert status["limitations"] == []

    def test_oauth_gmail_not_authorized_is_reported(self):
        # #790: a Gmail-only scope shortfall degrades instead of failing startup;
        # auth-status surfaces it so a client can see it before calling a Gmail tool.
        status = json.loads(_auth_status_json("oauth", False, "re-authorize please"))
        gmail = next(
            lim for lim in status["limitations"] if lim["category"] == "gmail_not_authorized"
        )
        assert gmail["reason"] == "re-authorize please"
        assert "send_message" in gmail["tools"]
        assert status["limited_tools"] == gmail["tools"]
        assert status["can_create_in_personal_drive"] is True

    def test_oauth_not_authorized_limits_every_tool(self):
        # #811: a degraded start (no Google access at all) reports every tool limited,
        # with the instructions for authorizing.
        status = json.loads(_auth_status_json("none", False, None, "no usable token"))
        assert status["auth_method"] == "none"
        assert status["limited_tools"] == ["*"]
        [lim] = status["limitations"]
        assert lim["category"] == "oauth_not_authorized"
        assert lim["reason"] == "no usable token"
        assert "mcp-gee-sweet auth" in lim["alternatives"]

    def test_gmail_not_authorized_points_at_auth_command(self):
        status = json.loads(_auth_status_json("oauth", False, "re-authorize please"))
        [gmail] = status["limitations"]
        assert "mcp-gee-sweet auth" in gmail["alternatives"]
        assert "oauth_setup" not in gmail["alternatives"]

    def test_adc_can_create_in_personal_drive(self):
        status = self._get_status("adc")
        assert status["is_service_account_identity"] is False
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
        assert status["limitations"] == []

    def test_adc_service_account_identity_reports_same_limitations_as_service_account(self):
        """Issue #506: auth_method stays "adc" (that's how the credential was
        actually obtained), but a service-account-backed ADC identity gets the
        same restrictions as auth_method == "service_account"."""
        status = self._get_status("adc", is_service_account_identity=True)
        assert status["auth_method"] == "adc"
        assert status["is_service_account_identity"] is True
        assert status["can_create_in_personal_drive"] is False
        assert "create_spreadsheet" in status["limited_tools"]
        assert "transfer_ownership" in status["limited_tools"]

    def test_adc_service_account_identity_quota_alternatives_do_not_suggest_adc(self):
        """Telling an ADC session already backed by a service account to "switch to
        ADC" would be circular — the alternatives text needs to say something an
        ADC caller can actually act on instead."""
        status = self._get_status("adc", is_service_account_identity=True)
        quota = next(
            lim for lim in status["limitations"] if lim["category"] == "no_drive_storage_quota"
        )
        assert "switch to adc" not in quota["alternatives"].lower()
        assert "oauth" in quota["alternatives"].lower()

    def test_service_account_quota_alternatives_still_suggest_adc(self):
        """The AUTH_METHOD=service_account case (not ADC-backed) is unaffected by
        the #506 fix — ADC is still a genuine escape hatch there."""
        status = self._get_status("service_account")
        quota = next(
            lim for lim in status["limitations"] if lim["category"] == "no_drive_storage_quota"
        )
        assert "adc" in quota["alternatives"].lower()


class TestResourcesReadLifespanContext:
    """Regression coverage for issue #363 (FastMCP had no `get_lifespan_context()`,
    confirmed never a real API even in mcp==1.27.1) carried forward through the
    mcp v2 migration (issue #175): v2's `MCPServer` dropped `get_context()` entirely,
    with no replacement for a static (non-templated) resource — Context injection
    there raises `ValueError` outright (confirmed live against mcp==2.0.0). So
    `get_auth_status` now reads the process-wide `auth.get_lifespan_context()`
    directly instead of going through Context at all, while `get_spreadsheet_info`
    (a template resource, where v2 *does* support it) takes `ctx: Context` as an
    ordinary injected parameter. These tests exercise both real mechanisms so a
    reintroduction of the old `get_context()`/`get_lifespan_context()` calls (or any
    other API drift) fails loudly.
    """

    def _fake_context(self, **lifespan_attrs):
        fake_ctx = MagicMock()
        for k, v in lifespan_attrs.items():
            setattr(fake_ctx.request_context.lifespan_context, k, v)
        return fake_ctx

    def test_get_auth_status_reads_auth_method_via_get_lifespan_context(self, monkeypatch):
        monkeypatch.setattr(
            server,
            "get_lifespan_context",
            lambda: SimpleNamespace(
                auth_method="oauth", is_service_account_identity=False, unauthorized_message=None
            ),
        )
        result = json.loads(get_auth_status())
        assert result["auth_method"] == "oauth"
        assert result["is_service_account_identity"] is False

    async def test_get_spreadsheet_info_reads_sheets_service_via_injected_context(self):
        sheets_service = MagicMock()
        sheets_service.spreadsheets.return_value.get.return_value.execute.return_value = {
            "properties": {"title": "Test Sheet"},
            "sheets": [
                {
                    "properties": {
                        "title": "Sheet1",
                        "sheetId": 0,
                        "gridProperties": {"rowCount": 10, "columnCount": 5},
                    }
                }
            ],
        }
        fake_ctx = self._fake_context(sheets_service=sheets_service)
        result = json.loads(await get_spreadsheet_info("some-spreadsheet-id", fake_ctx))
        assert result["title"] == "Test Sheet"
        assert result["sheets"] == [
            {"title": "Sheet1", "sheetId": 0, "gridProperties": {"rowCount": 10, "columnCount": 5}}
        ]

    async def test_get_spreadsheet_info_degraded_start_raises_authorize_message(self):
        fake_ctx = self._fake_context(
            sheets_service=None, unauthorized_message="run mcp-gee-sweet auth"
        )
        # A ResourceError, not the RuntimeError subclass: mcp 2.3 withholds any other
        # exception's text from the client (#872).
        with pytest.raises(ResourceError, match="run mcp-gee-sweet auth"):
            await get_spreadsheet_info("some-spreadsheet-id", fake_ctx)

    async def test_get_spreadsheet_info_google_api_error_keeps_its_text(self):
        sheets_service = MagicMock()
        sheets_service.spreadsheets.return_value.get.return_value.execute.side_effect = _http_error(
            404, "Requested entity was not found."
        )
        fake_ctx = self._fake_context(sheets_service=sheets_service)
        with pytest.raises(ResourceError, match="Requested entity was not found") as exc:
            await get_spreadsheet_info("some-spreadsheet-id", fake_ctx)
        assert isinstance(exc.value.__cause__, HttpError)

    def test_get_auth_status_reports_degraded_start(self, monkeypatch):
        monkeypatch.setattr(
            server,
            "get_lifespan_context",
            lambda: SimpleNamespace(
                auth_method="none",
                is_service_account_identity=False,
                unauthorized_message="no usable token",
            ),
        )
        result = json.loads(get_auth_status())
        assert result["limitations"][0]["category"] == "oauth_not_authorized"


class TestTimed:
    """_timed wraps tool functions to emit a per-call access log line."""

    @pytest.fixture(autouse=True)
    def capture_access_log(self):
        """Capture mcp_gee_sweet.access records regardless of propagation settings.

        DEBUG_LEVEL in .env sets mcp_gee_sweet.propagate=False at import time,
        so caplog's root handler never sees the records. We re-enable propagation
        and attach a direct MemoryHandler to the access logger for the duration of
        each test.
        """
        self._access_records = []

        class _Capture(logging.Handler):
            def emit(inner_self, record):
                self._access_records.append(record)

        self._capture_handler = _Capture(level=logging.DEBUG)
        access_logger = logging.getLogger("mcp_gee_sweet.access")
        access_logger.addHandler(self._capture_handler)
        access_logger.setLevel(logging.DEBUG)
        yield
        access_logger.removeHandler(self._capture_handler)

    def _access_messages(self):
        return [r.getMessage() for r in self._access_records]

    async def test_returns_function_result(self):
        @_timed
        async def my_func(**_kwargs):
            return 42

        assert await my_func() == 42

    async def test_reraises_exception(self):
        @_timed
        async def my_func(**_kwargs):
            raise KeyError("boom")

        with pytest.raises(KeyError, match="boom"):
            await my_func()

    async def test_logs_success_access_line(self):
        @_timed
        async def list_files(**kwargs):
            return []

        await list_files()

        msgs = self._access_messages()
        assert len(msgs) == 1
        assert '"TOOL list_files"' in msgs[0]
        assert "200" in msgs[0]

    async def test_logs_500_on_exception(self):
        @_timed
        async def my_func(**_kwargs):
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await my_func()

        msgs = self._access_messages()
        assert len(msgs) == 1
        assert "500" in msgs[0]

    async def test_falls_back_to_dash_without_ctx(self):
        @_timed
        async def my_func(**_kwargs):
            return None

        await my_func()

        msgs = self._access_messages()
        assert len(msgs) == 1
        assert '"-"' in msgs[0]

    async def test_extracts_ip_and_ua_from_ctx(self):
        ctx = MagicMock()
        ctx.request_context.request.client.host = "1.2.3.4"
        ctx.request_context.request.headers = {"user-agent": "test-client/1.0"}

        @_timed
        async def my_func(**_kwargs):
            return None

        await my_func(ctx=ctx)

        msgs = self._access_messages()
        assert len(msgs) == 1
        assert "1.2.3.4" in msgs[0]
        assert "test-client/1.0" in msgs[0]

    async def test_elapsed_time_appears_in_log(self):
        @_timed
        async def my_func(**_kwargs):
            return None

        await my_func()

        msgs = self._access_messages()
        assert msgs[0].endswith("s")

    async def test_degraded_start_raises_instead_of_running_the_tool(self, monkeypatch):
        # #811: with no Google services, every tool reports how to authorize. Raised,
        # not returned, since a {"error": ...} dict would fail a list-typed tool's
        # output schema. Read from the call's own lifespan context (per connection).
        ctx = MagicMock()
        ctx.request_context.lifespan_context.unauthorized_message = "run mcp-gee-sweet auth"
        body = MagicMock()

        @_timed
        async def list_files(**kwargs):
            body()
            return []

        # A ToolError, so mcp 2.3 shows the client its text (#872).
        with pytest.raises(ToolError, match="mcp-gee-sweet auth"):
            await list_files(ctx=ctx)
        body.assert_not_called()
        assert "401" in self._access_messages()[0]

    async def test_healthy_context_runs_the_tool(self):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.unauthorized_message = None

        @_timed
        async def list_files(**kwargs):
            return ["ok"]

        assert await list_files(ctx=ctx) == ["ok"]


class TestClientVisibleErrors:
    """#872: from mcp 2.3, only a ToolError's text reaches the client; anything else
    becomes a bare "Error executing tool <name>". _timed re-raises the failures a
    caller can act on as ToolError and leaves real crashes to mcp."""

    @staticmethod
    def _ctx(auth_method="oauth"):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.unauthorized_message = None
        ctx.request_context.lifespan_context.auth_method = auth_method
        return ctx

    @staticmethod
    def _raising(exc):
        @_timed
        async def some_tool(**kwargs):
            raise exc

        return some_tool

    @pytest.mark.parametrize(
        "exc, text",
        [
            (_http_error(404, "File not found: abc."), "File not found: abc."),
            (ValueError("Invalid A1 notation: empty string"), "Invalid A1 notation"),
            (FileNotFoundError(2, "No such file or directory", "/x/y.csv"), "/x/y.csv"),
            (auth_module.MissingOAuthScopesError("missing gmail scope"), "missing gmail"),
            (TimeoutError(), "TimeoutError"),
        ],
    )
    async def test_anticipated_failure_becomes_tool_error_with_its_text(self, exc, text):
        with pytest.raises(ToolError, match=text) as raised:
            await self._raising(exc)(ctx=self._ctx())
        assert raised.value.__cause__ is exc

    @pytest.mark.parametrize(
        "exc",
        [
            googleapiclient_errors.MediaUploadSizeError("Media larger than: 100"),
            googleapiclient_errors.UnacceptableMimeTypeError("Mime type not allowed"),
            googleapiclient_errors.UnknownFileType("/x/y.bin"),
        ],
    )
    async def test_non_http_google_api_client_errors_keep_their_text(self, exc):
        # Subclasses of googleapiclient.errors.Error that aren't HttpError.
        with pytest.raises(ToolError, match=str(exc)):
            await self._raising(exc)(ctx=self._ctx())

    async def test_oauth_refresh_failure_points_at_the_auth_command(self):
        # google-auth raises RefreshError(message, response_dict): the client gets the
        # message, not the tuple's repr.
        exc = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
        )
        with pytest.raises(ToolError) as raised:
            await self._raising(exc)(ctx=self._ctx("oauth"))
        assert str(raised.value).startswith(
            "Google rejected the OAuth token refresh: "
            "invalid_grant: Token has been expired or revoked. To authorize, run "
        )
        assert "{" not in str(raised.value)
        assert "mcp-gee-sweet auth" in str(raised.value)

    async def test_non_oauth_refresh_failure_keeps_only_its_own_text(self):
        exc = RefreshError("invalid_grant: account not found", {"error": "invalid_grant"})
        with pytest.raises(ToolError) as raised:
            await self._raising(exc)(ctx=self._ctx("service_account"))
        assert str(raised.value) == "invalid_grant: account not found"

    @staticmethod
    def _capture(logger_name):
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = records.append
        target = logging.getLogger(logger_name)
        target.addHandler(handler)
        target.setLevel(logging.DEBUG)
        return records, lambda: target.removeHandler(handler)

    @pytest.mark.parametrize(
        "exc, auth_method, status",
        [
            (RefreshError("invalid_grant", {}), "oauth", "401"),
            (auth_module.MissingOAuthScopesError("missing gmail scope"), "oauth", "401"),
            (RefreshError("invalid_grant", {}), "service_account", "500"),
            (_http_error(404, "File not found: abc."), "oauth", "500"),
            (ToolError("deliberate"), "oauth", "500"),
            (KeyError("crash"), "oauth", "500"),
        ],
    )
    async def test_access_log_status_separates_auth_failures(self, exc, auth_method, status):
        records, remove = self._capture("mcp_gee_sweet.access")
        try:
            with pytest.raises(KeyError if isinstance(exc, KeyError) else ToolError):
                await self._raising(exc)(ctx=self._ctx(auth_method))
        finally:
            remove()
        assert f'"TOOL some_tool" {status} ' in records[0].getMessage()

    async def test_translated_error_is_logged_with_its_traceback(self):
        # mcp logs a ToolError without a traceback, and a translated error can still be
        # our own bug (an HttpError 400 from a malformed request), so _timed logs it.
        records, remove = self._capture("mcp_gee_sweet.server")
        try:
            exc = _http_error(400, "Invalid requests[0]: bad field")
            with pytest.raises(ToolError):
                await self._raising(exc)(ctx=self._ctx())
        finally:
            remove()
        logged = [r for r in records if r.exc_info and r.exc_info[1] is exc]
        assert len(logged) == 1
        assert logged[0].levelno == logging.WARNING

    async def test_tool_error_passes_through_unchanged(self):
        exc = ToolError("already deliberate")
        with pytest.raises(ToolError) as raised:
            await self._raising(exc)(ctx=self._ctx())
        assert raised.value is exc

    async def test_unexpected_crash_is_left_for_mcp_to_mask(self):
        exc = KeyError("sheets")
        with pytest.raises(KeyError) as raised:
            await self._raising(exc)(ctx=self._ctx())
        assert raised.value is exc

    async def test_text_reaches_the_client_through_mcp_call_tool(self):
        # End to end through the installed mcp's Tool.run, which is what changed in 2.3.
        srv = MCPServer("t")

        @_timed
        async def get_storage_quota(ctx: Context) -> dict:
            raise _http_error(403, "The caller does not have permission")

        @_timed
        async def crashing_tool(ctx: Context) -> dict:
            raise KeyError("internal detail")

        srv.add_tool(get_storage_quota)
        srv.add_tool(crashing_tool)
        healthy = SimpleNamespace(unauthorized_message=None, auth_method="oauth")
        ctx = Context(request_context=SimpleNamespace(lifespan_context=healthy), mcp_server=srv)

        with pytest.raises(ToolError) as raised:
            await srv.call_tool("get_storage_quota", {}, ctx)
        assert not isinstance(raised.value, UnexpectedToolError)
        assert "The caller does not have permission" in str(raised.value)

        with pytest.raises(UnexpectedToolError) as raised:
            await srv.call_tool("crashing_tool", {}, ctx)
        assert "internal detail" not in str(raised.value)

    async def test_degraded_start_text_reaches_the_client_through_mcp_call_tool(self):
        srv = MCPServer("t")

        @_timed
        async def get_storage_quota(ctx: Context) -> dict:
            return {}

        srv.add_tool(get_storage_quota)
        degraded = SimpleNamespace(unauthorized_message="Run `mcp-gee-sweet auth`.")
        ctx = Context(request_context=SimpleNamespace(lifespan_context=degraded), mcp_server=srv)

        with pytest.raises(ToolError) as raised:
            await srv.call_tool("get_storage_quota", {}, ctx)
        assert not isinstance(raised.value, UnexpectedToolError)
        assert "mcp-gee-sweet auth" in str(raised.value)


class TestMainAuthAndTransport:
    """#811: `mcp-gee-sweet auth` dispatches to the consent command, and stdio turns
    off the in-server consent flow."""

    def test_auth_subcommand_runs_auth_command_and_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "auth", "--no-browser"])
        run = MagicMock()
        monkeypatch.setattr(mcp, "run", run)
        auth_cmd = MagicMock(return_value=0)
        monkeypatch.setattr(server, "run_auth_command", auth_cmd)
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        auth_cmd.assert_called_once_with(open_browser=False)
        run.assert_not_called()

    @pytest.mark.parametrize(
        "argv",
        [
            ["--include-tools", "list_spreadsheets", "auth", "--no-browser"],
            ["auth", "--include-tools", "list_spreadsheets", "--no-browser"],
            ["--no-browser", "auth"],
        ],
    )
    def test_auth_is_found_wherever_it_appears(self, monkeypatch, argv):
        # PR #828 QA round 1, reproduced live: with --include-tools first, `auth`
        # was missed and a stdio server started waiting on stdin.
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", *argv])
        run = MagicMock()
        monkeypatch.setattr(mcp, "run", run)
        auth_cmd = MagicMock(return_value=0)
        monkeypatch.setattr(server, "run_auth_command", auth_cmd)
        with pytest.raises(SystemExit):
            main()
        auth_cmd.assert_called_once_with(open_browser=False)
        run.assert_not_called()

    def test_auth_tool_name_is_not_a_subcommand(self, monkeypatch):
        # A tool called "auth" passed to --include-tools is a value, not the command.
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--include-tools", "auth"])
        run = MagicMock()
        monkeypatch.setattr(mcp, "run", run)
        auth_cmd = MagicMock()
        monkeypatch.setattr(server, "run_auth_command", auth_cmd)
        main()
        auth_cmd.assert_not_called()
        run.assert_called_once()

    def test_auth_rejects_unknown_flags(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "auth", "--no-browswer"])
        auth_cmd = MagicMock()
        monkeypatch.setattr(server, "run_auth_command", auth_cmd)
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
        auth_cmd.assert_not_called()
        assert "--no-browswer" in capsys.readouterr().err

    def test_stdio_disables_interactive_consent(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        monkeypatch.setattr(mcp, "run", MagicMock())
        main()
        assert auth_module._interactive_consent is False
        assert auth_module._raise_auth_failures is True

    def test_sse_keeps_interactive_consent(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--transport", "sse"])
        monkeypatch.setattr(anyio, "run", MagicMock())
        main()
        assert auth_module._interactive_consent is True
        assert auth_module._raise_auth_failures is False

    def test_sse_serves_the_guarded_app_like_run_sse_async(self, monkeypatch):
        # #868: mcp.run(transport="sse") builds its own app without SingleResponseGuard,
        # so main() serves the guarded app with run_sse_async()'s own launch:
        # anyio.run(uvicorn.Server(config).serve), not uvicorn.run (which picks uvloop).
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--transport", "sse"])
        monkeypatch.setattr(server, "_resolved_host", "127.0.0.9")
        monkeypatch.setattr(server, "_resolved_port", 47123)
        monkeypatch.setattr(mcp.settings, "log_level", "DEBUG")
        mcp_run, uvicorn_run, anyio_run = MagicMock(), MagicMock(), MagicMock()
        monkeypatch.setattr(mcp, "run", mcp_run)
        monkeypatch.setattr(uvicorn, "run", uvicorn_run)
        monkeypatch.setattr(anyio, "run", anyio_run)
        main()
        mcp_run.assert_not_called()
        uvicorn_run.assert_not_called()
        (serve,) = anyio_run.call_args.args
        assert serve.__func__ is uvicorn.Server.serve
        config = serve.__self__.config
        assert isinstance(server.app, SingleResponseGuard)
        assert config.app is server.app
        assert (config.host, config.port, config.log_level) == ("127.0.0.9", 47123, "debug")

    def test_streamable_http_serves_a_guarded_app_like_run_streamable_http_async(self, monkeypatch):
        # #917: mcp.run(transport="streamable-http") builds its own unguarded app, so
        # main() wraps mcp's streamable_http_app and launches it the same way as SSE.
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--transport", "streamable-http"])
        monkeypatch.setattr(server, "_resolved_host", "127.0.0.9")
        monkeypatch.setattr(server, "_resolved_port", 47123)
        monkeypatch.setattr(mcp.settings, "log_level", "DEBUG")
        built = MagicMock(name="streamable_http_app")
        build = MagicMock(return_value=built)
        mcp_run, uvicorn_run, anyio_run = MagicMock(), MagicMock(), MagicMock()
        monkeypatch.setattr(mcp, "streamable_http_app", build)
        monkeypatch.setattr(mcp, "run", mcp_run)
        monkeypatch.setattr(uvicorn, "run", uvicorn_run)
        monkeypatch.setattr(anyio, "run", anyio_run)
        main()
        mcp_run.assert_not_called()
        uvicorn_run.assert_not_called()
        build.assert_called_once_with(host="127.0.0.9")
        (serve,) = anyio_run.call_args.args
        assert serve.__func__ is uvicorn.Server.serve
        config = serve.__self__.config
        assert isinstance(config.app, SingleResponseGuard)
        assert config.app.app is built
        assert (config.host, config.port, config.log_level) == ("127.0.0.9", 47123, "debug")
        assert auth_module._interactive_consent is True
        assert auth_module._raise_auth_failures is False

    def test_unknown_transport_exits_with_a_message(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--transport", "websocket"])
        mcp_run, uvicorn_run, anyio_run = MagicMock(), MagicMock(), MagicMock()
        monkeypatch.setattr(mcp, "run", mcp_run)
        monkeypatch.setattr(uvicorn, "run", uvicorn_run)
        monkeypatch.setattr(anyio, "run", anyio_run)
        with pytest.raises(SystemExit) as exc:
            main()
        assert "unknown --transport 'websocket'" in str(exc.value.code)
        mcp_run.assert_not_called()
        uvicorn_run.assert_not_called()
        anyio_run.assert_not_called()

    @pytest.mark.parametrize(
        ("transport", "target", "factory"),
        [
            ("sse", "mcp_gee_sweet.server:app", False),
            ("streamable-http", "mcp_gee_sweet.server:_streamable_http_app", True),
        ],
    )
    def test_reload_serves_the_guarded_app_for_each_http_transport(
        self, monkeypatch, transport, target, factory
    ):
        # --reload used to be honored for sse only and silently dropped for
        # streamable-http (PR #975 QA round 1).
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--transport", transport, "--reload"])
        monkeypatch.setattr(server, "_resolved_host", "127.0.0.9")
        monkeypatch.setattr(server, "_resolved_port", 47123)
        uvicorn_run, anyio_run = MagicMock(), MagicMock()
        monkeypatch.setattr(uvicorn, "run", uvicorn_run)
        monkeypatch.setattr(anyio, "run", anyio_run)
        main()
        anyio_run.assert_not_called()
        uvicorn_run.assert_called_once_with(
            target, factory=factory, host="127.0.0.9", port=47123, reload=True
        )

    def test_reload_target_factory_builds_a_guarded_streamable_http_app(self, monkeypatch):
        built = MagicMock(name="streamable_http_app")
        monkeypatch.setattr(mcp, "streamable_http_app", MagicMock(return_value=built))
        # Resolve the reload target the way uvicorn's reloader worker does.
        factory = import_from_string("mcp_gee_sweet.server:_streamable_http_app")
        guarded = factory()
        assert isinstance(guarded, SingleResponseGuard)
        assert guarded.app is built

    def test_reload_with_stdio_warns_and_runs_stdio(self, monkeypatch, caplog):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet", "--reload"])
        mcp_run, uvicorn_run = MagicMock(), MagicMock()
        monkeypatch.setattr(mcp, "run", mcp_run)
        monkeypatch.setattr(uvicorn, "run", uvicorn_run)
        with caplog.at_level(logging.WARNING, logger=server.logger.name):
            main()
        uvicorn_run.assert_not_called()
        mcp_run.assert_called_once_with(transport="stdio")
        assert "--reload applies only to the sse and streamable-http transports" in caplog.text


class TestMainLogsVersion:
    """Issue #356: main() logs the running package version at startup so a
    deployed instance's version can be confirmed from logs alone.

    _version_logger has propagate=False and its own dedicated handler (module
    load time, unconditional — see server.py), so it never reaches caplog's
    root-attached handler. Same quirk TestTimed's capture_access_log fixture
    documents for mcp_gee_sweet.access; worked around the same way here rather
    than relying on caplog, so this passes regardless of whether DEBUG_LEVEL
    is set in the environment (the original version of this test only passed
    when DEBUG_LEVEL was unset — see PR #479's QA round).
    """

    @pytest.fixture(autouse=True)
    def capture_version_log(self):
        self._version_records = []

        class _Capture(logging.Handler):
            def emit(inner_self, record):
                self._version_records.append(record)

        capture_handler = _Capture(level=logging.DEBUG)
        _version_logger.addHandler(capture_handler)
        yield
        _version_logger.removeHandler(capture_handler)

    def test_logs_resolved_version(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        monkeypatch.setattr(mcp, "run", MagicMock())
        main()

        version_records = [r for r in self._version_records if "mcp-gee-sweet version" in r.message]
        assert version_records, "expected a startup log line with the package version"
        assert importlib.metadata.version("mcp-gee-sweet") in version_records[0].message

    def test_falls_back_when_package_metadata_missing(self, monkeypatch):
        """Issue #481: a broken/repackaged install (or invoking main() without the
        package installed) makes importlib.metadata.version raise
        PackageNotFoundError. main() should log a placeholder and keep starting
        up instead of crashing before tool-filtering/transport setup.
        """
        monkeypatch.setattr(sys, "argv", ["mcp-gee-sweet"])
        monkeypatch.setattr(mcp, "run", MagicMock())

        def _raise(name):
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(importlib.metadata, "version", _raise)
        main()

        version_records = [r for r in self._version_records if "mcp-gee-sweet version" in r.message]
        assert version_records, "expected a startup log line even when metadata is unresolvable"
        assert "unknown" in version_records[0].message


class TestToolStrictArgs:
    """tool() rejects unrecognized kwargs instead of silently ignoring them (issue #239).

    MCPServer's auto-generated arg model defaults to extra="ignore" (pydantic's own
    default); tool() flips it to extra="forbid" after registration via private
    ToolManager/FuncMetadata internals — see _enforce_strict_tool_args's docstring.
    """

    def test_registers_dummy_tool_valid_args_still_pass(self):
        @tool()
        def _test_strict_dummy_tool(known_arg: str, ctx=None) -> str:
            return known_arg

        registered = mcp._tool_manager.get_tool("_test_strict_dummy_tool")
        result = registered.fn_metadata.arg_model.model_validate({"known_arg": "x"})
        assert result.known_arg == "x"

    def test_registers_dummy_tool_unknown_kwarg_rejected(self):
        @tool()
        def _test_strict_dummy_tool_2(known_arg: str, ctx=None) -> str:
            return known_arg

        registered = mcp._tool_manager.get_tool("_test_strict_dummy_tool_2")
        with pytest.raises(ValidationError, match="unexpected_kwarg"):
            registered.fn_metadata.arg_model.model_validate(
                {"known_arg": "x", "unexpected_kwarg": "y"}
            )

    def test_real_production_tool_rejects_unknown_kwarg(self):
        # Proves the fix applies universally across all ~84 tools via the shared
        # decorator (register_all(tool) already ran at module import), not just to a
        # test-only registration.
        registered = mcp._tool_manager.get_tool("list_sheets")
        with pytest.raises(ValidationError, match="extra_forbidden"):
            registered.fn_metadata.arg_model.model_validate(
                {"spreadsheet_id": "abc123", "bogus_kwarg": "x"}
            )

    def test_real_production_tool_still_accepts_valid_args(self):
        registered = mcp._tool_manager.get_tool("list_sheets")
        result = registered.fn_metadata.arg_model.model_validate({"spreadsheet_id": "abc123"})
        assert result.spreadsheet_id == "abc123"


# The tools that take local paths, and where each one's local-file policy check
# lives (#796, docs/design/local-file-access-policy.md §5). A new tool with a
# local-path parameter fails TestLocalPathToolsAreCovered until it's added here,
# with its check in place.
_LOCAL_ONLY_TOOLS = {
    "create_doc_from_file",
    "download_file",
    "download_folder",
    "import_csv_to_sheet",
    "insert_local_images",
    "sync_folder",
    "update_doc_from_file",
    "upload_local_file",
    "upload_local_folder",
}
_OPTIONAL_LOCAL_PATH_TOOLS = {
    # response_limits.write_capped_result_to_disk
    "export_revision",
    "find_in_doc",
    "find_in_spreadsheet",
    "get_doc_as_markdown",
    "get_doc_content",
    "get_message",
    "get_multiple_sheet_data",
    "get_multiple_spreadsheet_summary",
    "get_sheet_data",
    "get_thread",
    # gmail._read_attachment_bytes
    "create_draft",
    "send_message",
    # content._resolve_image_source (Markdown/HTML image sources)
    "create_doc",
    "write_doc_content",
}
_LOCAL_PATH_PARAMS = {"local_path", "result_local_path", "attachments", "images"}


def _captured_registrations():
    """Every tool function with the local_only flag its decorator passed."""
    from mcp_gee_sweet.tools import register_all

    captured = {}

    def capture(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = (func, local_only)
            return func

        return decorator

    register_all(capture)
    return captured


class TestLocalOnlyRegistration:
    """#796: LOCAL_FILE_ACCESS=off doesn't register tools that can only work on
    local files."""

    def test_exactly_the_local_only_tools_are_flagged(self):
        flagged = {name for name, (_, flag) in _captured_registrations().items() if flag}
        assert flagged == _LOCAL_ONLY_TOOLS

    def test_off_mode_skips_a_local_only_tool(self, monkeypatch):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="off")
        dropped: list[str] = []
        monkeypatch.setattr(server, "_unregistered_local_only_tools", dropped)
        monkeypatch.setattr(server, "ENABLED_TOOLS", None)
        fake_mcp = MagicMock()
        monkeypatch.setattr(server, "mcp", fake_mcp)

        async def sync_folder():
            pass

        assert tool(local_only=True)(sync_folder) is sync_folder
        fake_mcp.tool.assert_not_called()
        assert dropped == ["sync_folder"]

    def test_enabled_tools_filter_wins_before_the_policy(self, monkeypatch):
        # A tool ENABLED_TOOLS already leaves out isn't one "the policy dropped".
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="off")
        dropped: list[str] = []
        monkeypatch.setattr(server, "_unregistered_local_only_tools", dropped)
        monkeypatch.setattr(server, "ENABLED_TOOLS", {"get_sheet_data"})

        async def sync_folder():
            pass

        tool(local_only=True)(sync_folder)
        assert dropped == []

    def test_full_mode_registers_every_local_only_tool(self):
        # The test process runs with the stdio default, full.
        registered = {t.name for t in mcp._tool_manager.list_tools()}
        assert registered >= _LOCAL_ONLY_TOOLS


def _import_server_in_subprocess(argv: list[str], env: dict[str, str]):
    """Import mcp_gee_sweet.server in a fresh interpreter, as a launch with `argv`
    would, and return (registered tool names, stderr). The policy and registration
    both happen at import, so only a fresh process exercises them for real."""
    code = (
        "import json, sys\n"
        f"sys.argv = {argv!r}\n"
        "from mcp_gee_sweet import server\n"
        "print(json.dumps(sorted(t.name for t in server.mcp._tool_manager.list_tools())))\n"
    )
    full_env = {
        k: v for k, v in os.environ.items() if k not in ("LOCAL_FILE_ACCESS", "ENABLED_TOOLS")
    }
    full_env.update(env)
    proc = subprocess.run(
        [sys.executable, "-c", code], env=full_env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    return set(json.loads(proc.stdout.strip().splitlines()[-1])), proc.stderr


class TestLocalFilePolicyAtImport:
    def test_sse_default_leaves_local_only_tools_unregistered(self):
        names, _ = _import_server_in_subprocess(["mcp-gee-sweet", "--transport", "sse"], {})
        assert not (names & _LOCAL_ONLY_TOOLS)
        # Tools with only an optional local path stay registered.
        assert {"get_sheet_data", "send_message", "create_doc"} <= names

    def test_explicit_full_under_sse_registers_them(self):
        names, _ = _import_server_in_subprocess(
            ["mcp-gee-sweet", "--transport", "sse"], {"LOCAL_FILE_ACCESS": "full"}
        )
        assert names >= _LOCAL_ONLY_TOOLS

    def test_enabled_tools_naming_a_dropped_tool_warns(self):
        names, stderr = _import_server_in_subprocess(
            ["mcp-gee-sweet"],
            {"LOCAL_FILE_ACCESS": "off", "ENABLED_TOOLS": "sync_folder,get_sheet_data"},
        )
        assert names == {"get_sheet_data"}
        assert "not registering local-only tools named in ENABLED_TOOLS: sync_folder" in stderr


class TestLocalPathToolsAreCovered:
    """A guard: every tool that takes a local path is one whose policy check is
    placed (#796). A new one fails here until someone decides where its check goes."""

    def test_every_local_path_tool_is_accounted_for(self):
        takes_local_path = {
            name
            for name, (func, _) in _captured_registrations().items()
            if _LOCAL_PATH_PARAMS & set(inspect.signature(func).parameters)
        }
        # create_doc / write_doc_content take local image paths inside their content.
        assert takes_local_path | {"create_doc", "write_doc_content"} == (
            _LOCAL_ONLY_TOOLS | _OPTIONAL_LOCAL_PATH_TOOLS
        )


class TestAuthStatusLocalFileAccess:
    """#796 §9: server://auth-status reports the local-file policy."""

    @pytest.mark.parametrize(
        "args",
        [
            ("oauth", False, None, None),
            ("service_account", True, None, None),
            ("none", False, None, "no usable token"),
        ],
    )
    def test_present_in_every_branch(self, monkeypatch, args):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        monkeypatch.setattr(server, "_unregistered_local_only_tools", [])
        status = json.loads(_auth_status_json(*args))
        assert status["local_file_access"] == {
            "mode": "full",
            "explicit": True,
            "roots": [],
            "unregistered_tools": [],
        }

    def test_roots_mode_lists_roots(self, monkeypatch, tmp_path):
        use_local_file_policy(
            monkeypatch, LOCAL_FILE_ACCESS="roots", LOCAL_FILE_ROOTS=str(tmp_path)
        )
        status = json.loads(_auth_status_json("oauth"))
        assert status["local_file_access"]["mode"] == "roots"
        assert status["local_file_access"]["roots"] == [str(tmp_path)]

    def test_off_mode_lists_unregistered_tools(self, monkeypatch):
        monkeypatch.setattr(
            local_files, "POLICY", local_files.resolve_policy({}, ["x", "--transport", "sse"])
        )
        monkeypatch.setattr(
            server, "_unregistered_local_only_tools", ["sync_folder", "download_file"]
        )
        status = json.loads(_auth_status_json("oauth"))
        assert status["local_file_access"] == {
            "mode": "off",
            "explicit": False,
            "roots": [],
            "unregistered_tools": ["download_file", "sync_folder"],
        }


class TestTimedMarksHttpRequests:
    """#796 §2: _timed tells the local-file policy whether a call came over HTTP."""

    @staticmethod
    def _ctx(request):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.unauthorized_message = None
        ctx.request_context.request = request
        return ctx

    async def _seen(self, request):
        @_timed
        async def some_tool(**kwargs):
            return local_files.request_over_http.get()

        return await some_tool(ctx=self._ctx(request))

    async def test_starlette_request_is_http(self):
        request = Request({"type": "http", "headers": [], "client": ("1.2.3.4", 1)})
        assert await self._seen(request) is True

    async def test_stdio_has_no_request(self):
        assert await self._seen(None) is False

    async def test_reset_after_the_call(self):
        await self._seen(Request({"type": "http", "headers": []}))
        assert local_files.request_over_http.get() is False


class TestInvalidPolicyOnlyStopsServing:
    """QA round 1, finding 4: an invalid LOCAL_FILE_ACCESS must not block the
    `mcp-gee-sweet auth` recovery subcommand or the tool-doc generator; only
    serving refuses to start on it."""

    @staticmethod
    def _run(code: str, env: dict[str, str]):
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("LOCAL_FILE")}
        full_env.update(env)
        return subprocess.run(
            [sys.executable, "-c", code], env=full_env, capture_output=True, text=True, timeout=120
        )

    def test_serving_exits_with_the_one_line_message(self):
        proc = self._run(
            "import sys\n"
            "sys.argv = ['mcp-gee-sweet', '--transport', 'sse']\n"
            "from mcp_gee_sweet import main\n"
            "main()\n",
            {"LOCAL_FILE_ACCESS": "bogus"},
        )
        assert proc.returncode == 1
        assert (
            "mcp-gee-sweet: LOCAL_FILE_ACCESS='bogus' isn't valid (use full, roots, or off)"
            in proc.stderr
        )
        assert "Traceback" not in proc.stderr

    def test_auth_subcommand_still_parses(self):
        proc = self._run(
            "import sys\n"
            "sys.argv = ['mcp-gee-sweet', 'auth', '--help']\n"
            "from mcp_gee_sweet import main\n"
            "main()\n",
            {"LOCAL_FILE_ACCESS": "roots", "LOCAL_FILE_ROOTS": "/not/mounted/yet"},
        )
        assert proc.returncode == 0, proc.stderr
        assert "usage: mcp-gee-sweet auth" in proc.stdout

    def test_gen_tool_docs_still_collects_every_tool(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        proc = self._run(
            "import sys\n"
            f"sys.path.insert(0, {str(scripts)!r})\n"
            "import gen_tool_docs\n"
            "print(len(gen_tool_docs.collect_tools()))\n",
            {"LOCAL_FILE_ACCESS": "bogus"},
        )
        assert proc.returncode == 0, proc.stderr
        # Every tool, local-only ones included: the docs never depend on the policy.
        assert int(proc.stdout.strip().splitlines()[-1]) == len(_captured_registrations())
