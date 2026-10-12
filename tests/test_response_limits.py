"""Tests for tools/response_limits.py — shared response-size safety net (issue #242)."""

import importlib
import json
import os

import pytest

from mcp_gee_sweet.tools import response_limits


class TestEnforceResponseSizeFloor:
    """#825: reject a known-over-cap response before fetching it."""

    def test_at_or_under_cap_succeeds(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 100)
        response_limits.enforce_response_size_floor(100, tool_name="some_tool")

    def test_over_cap_raises_with_lower_bound_wording(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 100)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_floor(
                101, tool_name="some_tool", hint="Big body. "
            )
        message = str(exc_info.value)
        assert message.startswith("some_tool: the response would be at least 101 characters")
        assert "100-character safety cap. Big body. Pass local_path" in message

    def test_local_path_omitted_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 1)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_floor(
                2, tool_name="some_tool", local_path_available=False
            )
        assert "local_path" not in str(exc_info.value)


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

    def test_local_path_param_overrides_hint_name(self, monkeypatch):
        # sync_folder's own local_path param already means the sync destination
        # (#512) — it needs the hint to name a different param for the response
        # offramp instead of the generic default.
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_cap(
                {"a": "bb"}, tool_name="some_tool", local_path_param="result_local_path"
            )
        assert "result_local_path" in str(exc_info.value)

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

    async def test_str_result_written_verbatim(self, tmp_path):
        """#958: a str is written as raw UTF-8 text, not JSON-quoted, with no
        newline translation."""
        dest = tmp_path / "out.md"
        text = '# Title\r\nline "two" 😀\n'
        result = await response_limits.write_capped_result_to_disk(
            text, str(dest), default_filename="fallback.md", manifest_extra={}
        )
        assert dest.read_bytes() == text.encode("utf-8")
        assert result["bytes_written"] == len(text.encode("utf-8"))

    async def test_failed_write_leaves_previous_file_intact(self, tmp_path, monkeypatch):
        """PR #982 QA round 1: a write that fails partway must not leave a
        truncated file over a previous good export."""
        dest = tmp_path / "out.md"
        dest.write_text("previous export", encoding="utf-8")

        def _replace_fails(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _replace_fails)
        with pytest.raises(OSError, match="disk full"):
            await response_limits.write_capped_result_to_disk(
                "new export", str(dest), default_filename="fallback.md", manifest_extra={}
            )
        assert dest.read_text(encoding="utf-8") == "previous export"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["out.md"]

    async def test_directory_path_uses_default_filename(self, tmp_path):
        result = await response_limits.write_capped_result_to_disk(
            {"a": 1}, str(tmp_path), default_filename="fallback.json", manifest_extra={}
        )
        dest = tmp_path / "fallback.json"
        assert result["local_path"] == str(dest)
        assert dest.exists()

    async def test_missing_directory_with_trailing_slash_is_created(self, tmp_path):
        """#990: 'dir/' for a directory that doesn't exist yet means a directory,
        not a file named 'dir'."""
        missing = tmp_path / "new" / "sub"
        result = await response_limits.write_capped_result_to_disk(
            {"a": 1}, f"{missing}/", default_filename="fallback.json", manifest_extra={}
        )
        dest = missing / "fallback.json"
        assert missing.is_dir()
        assert result["local_path"] == str(dest)
        assert json.loads(dest.read_text()) == {"a": 1}

    async def test_existing_directory_with_trailing_slash_uses_default_filename(self, tmp_path):
        result = await response_limits.write_capped_result_to_disk(
            "text", f"{tmp_path}/", default_filename="fallback.md", manifest_extra={}
        )
        dest = tmp_path / "fallback.md"
        assert result["local_path"] == str(dest)
        assert dest.read_text() == "text"

    async def test_trailing_slash_on_existing_file_raises_and_keeps_file(self, tmp_path):
        """#990: a trailing slash naming an existing regular file is refused,
        never overwritten as if the slash weren't there."""
        existing = tmp_path / "out"
        existing.write_text("keep me", encoding="utf-8")
        with pytest.raises(ValueError, match="non-directory path component"):
            await response_limits.write_capped_result_to_disk(
                {"a": 1}, f"{existing}/", default_filename="fallback.json", manifest_extra={}
            )
        assert existing.read_text(encoding="utf-8") == "keep me"

    async def test_existing_file_further_up_the_path_raises(self, tmp_path):
        """PR #1000 QA round 1: 'file/sub/' raised a raw NotADirectoryError
        from mkdir; every ancestor is checked, not just the immediate parent."""
        existing = tmp_path / "out"
        existing.write_text("keep me", encoding="utf-8")
        for local_path in (f"{existing}/sub/", f"{existing}/sub/x.json"):
            with pytest.raises(ValueError, match=r"non-directory path component at '.*out'"):
                await response_limits.write_capped_result_to_disk(
                    {"a": 1}, local_path, default_filename="fallback.json", manifest_extra={}
                )
        assert existing.read_text(encoding="utf-8") == "keep me"

    async def test_dangling_symlink_with_trailing_slash_raises(self, tmp_path):
        """PR #1000 QA round 1: a dangling symlink raised a raw FileExistsError."""
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "missing")
        with pytest.raises(ValueError, match="symlink to a missing target"):
            await response_limits.write_capped_result_to_disk(
                {"a": 1}, f"{link}/", default_filename="fallback.json", manifest_extra={}
            )
        assert not (tmp_path / "missing").exists()

    async def test_missing_directory_with_trailing_dot_is_created(self, tmp_path):
        """Path() drops a trailing '/.', so 'dir/.' must be read from the string,
        the same as download_file (#874)."""
        missing = tmp_path / "new"
        result = await response_limits.write_capped_result_to_disk(
            {"a": 1}, f"{missing}/.", default_filename="fallback.json", manifest_extra={}
        )
        assert missing.is_dir()
        assert json.loads((missing / "fallback.json").read_text()) == {"a": 1}
        assert result["bytes_written"] == (missing / "fallback.json").stat().st_size

    async def test_error_names_the_callers_parameter(self, tmp_path):
        existing = tmp_path / "out"
        existing.write_text("keep me", encoding="utf-8")
        with pytest.raises(ValueError, match="^result_local_path "):
            await response_limits.write_capped_result_to_disk(
                {"a": 1},
                f"{existing}/",
                default_filename="fallback.json",
                manifest_extra={},
                local_path_param="result_local_path",
            )

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
