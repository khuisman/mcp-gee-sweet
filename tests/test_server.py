"""Tests for server.py (_parse_enabled_tools, _auth_status_json)."""

import json
import sys

from mcp_gee_sweet.server import _auth_status_json, _parse_enabled_tools


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
