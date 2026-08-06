"""Tests for server.py (_parse_enabled_tools, _auth_status_json, _timed, tool strict args)."""

import importlib.metadata
import inspect
import json
import logging
import sys
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

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

    def _get_status(self, auth_method):
        return json.loads(_auth_status_json(auth_method))

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

    def test_oauth_can_create_in_personal_drive(self):
        status = self._get_status("oauth")
        assert status["auth_method"] == "oauth"
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
        assert status["limitations"] == []

    def test_adc_can_create_in_personal_drive(self):
        status = self._get_status("adc")
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
        assert status["limitations"] == []


class TestResourcesReadLifespanContextViaGetContext:
    """Regression test for issue #363: both MCP resources called the nonexistent
    `mcp.get_lifespan_context()` (never a real FastMCP API, confirmed absent even
    in mcp==1.27.1, so not a regression from #350's SDK bump). TestAuthStatusResource
    above only exercises `_auth_status_json()` directly, never the resource function
    itself, so it never caught this. These tests call the actual resource functions
    and monkeypatch `mcp.get_context()` the way FastMCP really provides it, so a
    reintroduction of `get_lifespan_context()` (or any other API drift) fails loudly.
    """

    def _fake_context(self, **lifespan_attrs):
        fake_ctx = MagicMock()
        for k, v in lifespan_attrs.items():
            setattr(fake_ctx.request_context.lifespan_context, k, v)
        return fake_ctx

    def test_get_auth_status_reads_auth_method_via_get_context(self, monkeypatch):
        monkeypatch.setattr(mcp, "get_context", lambda: self._fake_context(auth_method="oauth"))
        result = json.loads(get_auth_status())
        assert result["auth_method"] == "oauth"

    async def test_get_spreadsheet_info_reads_sheets_service_via_get_context(self, monkeypatch):
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
        monkeypatch.setattr(
            mcp, "get_context", lambda: self._fake_context(sheets_service=sheets_service)
        )
        result = json.loads(await get_spreadsheet_info("some-spreadsheet-id"))
        assert result["title"] == "Test Sheet"
        assert result["sheets"] == [
            {"title": "Sheet1", "sheetId": 0, "gridProperties": {"rowCount": 10, "columnCount": 5}}
        ]


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
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
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

    FastMCP's auto-generated arg model defaults to extra="ignore" (pydantic's own
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
