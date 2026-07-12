"""Tests for server.py (_parse_enabled_tools, _auth_status_json, _timed, tool strict args)."""

import json
import logging
import sys
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from mcp_gee_sweet.server import _auth_status_json, _parse_enabled_tools, _timed, mcp, tool


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

    def test_service_account_includes_reason_and_alternative(self):
        status = self._get_status("service_account")
        assert status["reason"] is not None
        assert "storage quota" in status["reason"].lower()
        assert status["alternatives"] is not None

    def test_oauth_can_create_in_personal_drive(self):
        status = self._get_status("oauth")
        assert status["auth_method"] == "oauth"
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []
        assert status["reason"] is None

    def test_adc_can_create_in_personal_drive(self):
        status = self._get_status("adc")
        assert status["can_create_in_personal_drive"] is True
        assert status["limited_tools"] == []


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
