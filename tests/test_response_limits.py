"""Tests for tools/response_limits.py — shared response-size safety net (issue #242)."""

import importlib
import json

import pytest

from mcp_gee_sweet.tools import response_limits


class TestEnforceResponseSizeCap:
    def test_under_cap_succeeds(self):
        response_limits.enforce_response_size_cap({"filler": "x" * 10}, tool_name="some_tool")

    def test_over_cap_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 500)
        with pytest.raises(ValueError, match="safety cap"):
            response_limits.enforce_response_size_cap({"filler": "x" * 1000}, tool_name="some_tool")

    def test_works_on_list_results(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 500)
        with pytest.raises(ValueError, match="safety cap"):
            response_limits.enforce_response_size_cap(
                [{"filler": "x" * 1000}], tool_name="some_tool"
            )

    def test_error_names_the_tool_and_measured_size(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        with pytest.raises(ValueError, match="some_tool") as exc_info:
            response_limits.enforce_response_size_cap({"a": "bb"}, tool_name="some_tool")
        assert "10-character safety cap" in str(exc_info.value)

    def test_hint_is_included_in_message(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError, match="lower max_results"):
            response_limits.enforce_response_size_cap(
                {"a": "bb"}, tool_name="some_tool", hint="lower max_results, or "
            )

    def test_local_path_mentioned_when_available(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError, match="local_path"):
            response_limits.enforce_response_size_cap({"a": "bb"}, tool_name="some_tool")

    def test_local_path_omitted_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_cap(
                {"a": "bb"}, tool_name="some_tool", local_path_available=False
            )
        assert "local_path" not in str(exc_info.value)

    def test_env_var_sets_cap_at_import_time(self, monkeypatch):
        monkeypatch.setenv("MAX_TOOL_RESPONSE_CHARS", "12345")
        reloaded = importlib.reload(response_limits)
        try:
            assert reloaded.MAX_TOOL_RESPONSE_CHARS == 12345
        finally:
            monkeypatch.delenv("MAX_TOOL_RESPONSE_CHARS", raising=False)
            importlib.reload(response_limits)


class TestWriteCappedResultToDisk:
    async def test_writes_dict_result(self, tmp_path):
        dest = tmp_path / "out.json"
        result = await response_limits.write_capped_result_to_disk(
            {"a": 1}, str(dest), default_filename="fallback.json", manifest_extra={"id": "x"}
        )
        assert result["local_path"] == str(dest)
        assert result["id"] == "x"
        assert result["bytes_written"] == dest.stat().st_size
        assert json.loads(dest.read_text()) == {"a": 1}

    async def test_writes_list_result(self, tmp_path):
        dest = tmp_path / "out.json"
        await response_limits.write_capped_result_to_disk(
            [{"a": 1}, {"b": 2}], str(dest), default_filename="fallback.json", manifest_extra={}
        )
        assert json.loads(dest.read_text()) == [{"a": 1}, {"b": 2}]

    async def test_directory_path_uses_default_filename(self, tmp_path):
        result = await response_limits.write_capped_result_to_disk(
            {"a": 1}, str(tmp_path), default_filename="fallback.json", manifest_extra={}
        )
        dest = tmp_path / "fallback.json"
        assert result["local_path"] == str(dest)
        assert dest.exists()

    async def test_creates_missing_parent_dirs(self, tmp_path):
        dest = tmp_path / "nested" / "sub" / "out.json"
        await response_limits.write_capped_result_to_disk(
            {"a": 1}, str(dest), default_filename="fallback.json", manifest_extra={}
        )
        assert dest.exists()

    async def test_bypasses_cap_even_when_genuinely_oversized(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        dest = tmp_path / "out.json"
        big_result = {"filler": "x" * 1000}
        result = await response_limits.write_capped_result_to_disk(
            big_result, str(dest), default_filename="fallback.json", manifest_extra={}
        )
        assert json.loads(dest.read_text()) == big_result
        assert result["bytes_written"] == dest.stat().st_size
