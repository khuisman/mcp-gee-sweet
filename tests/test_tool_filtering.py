import sys

from mcp_gee_sweet.server import _parse_enabled_tools


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
