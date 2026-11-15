"""Tool groups and deprecated aliases in ENABLED_TOOLS (#1364), plus the CI guards
that keep the groups inside the client caps they exist for."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_gee_sweet import server, tool_groups
from mcp_gee_sweet.tool_groups import Renamed, Selection

ROOT = Path(__file__).resolve().parent.parent

# The snapshot the issue pins: a change to `default` is a deliberate edit here.
DEFAULT_SNAPSHOT = {
    "get_doc_as_markdown",
    "get_doc_structure",
    "create_doc",
    "write_doc_content",
    "find_in_doc",
    "insert_doc_text",
    "delete_doc_range",
    "style_doc_range",
    "search_files",
    "list_files",
    "get_file_metadata",
    "export_file",
    "upload_file",
    "create_folder",
    "rename_file",
    "copy_file",
    "share_file",
    "get_sheet_data",
    "get_sheet_formulas",
    "list_sheets",
    "find_in_spreadsheet",
    "update_cells",
    "create_spreadsheet",
    "batch_update",
    "list_messages",
    "get_thread",
    "send_message",
    "reply_to_message",
    "create_draft",
    "list_drafts",
    "send_draft",
    "modify_labels",
    "list_events",
    "get_event",
    "create_event",
    "update_event",
    "delete_event",
    "find_free_slots",
}
DEFAULT_CAP = 40
SERVICE_GROUP_CAP = 100


def _registrations() -> dict[str, frozenset[str]]:
    """Every tool with its groups, from the decorator flags, as server.tool computes them."""
    from mcp_gee_sweet.tools import register_all

    captured = {}

    def capture(annotations=None, *, local_only=False, default=False, groups=()):
        def decorator(func):
            captured[func.__name__] = tool_groups.tool_groups(
                func.__module__, default=default, local_only=local_only, groups=groups
            )
            return func

        return decorator

    register_all(capture)
    return captured


def _members(group: str) -> set[str]:
    return {name for name, groups in _registrations().items() if group in groups}


class TestGroupGuards:
    def test_default_is_the_snapshot(self):
        assert _members("default") == DEFAULT_SNAPSHOT

    def test_default_is_within_the_cap(self):
        assert len(_members("default")) <= DEFAULT_CAP

    @pytest.mark.parametrize("group", tool_groups.SERVICE_GROUPS)
    def test_each_service_group_is_within_the_cap(self, group):
        members = _members(group)
        assert members, f"{group} has no tools"
        assert len(members) <= SERVICE_GROUP_CAP

    def test_every_tool_has_a_service_group(self):
        no_service = [
            name
            for name, groups in _registrations().items()
            if not groups.intersection(tool_groups.SERVICE_GROUPS)
        ]
        assert no_service == []

    @pytest.mark.parametrize("group", tool_groups.DECLARED_GROUPS)
    def test_each_declared_group_has_members(self, group):
        assert _members(group)

    def test_comments_group(self):
        assert _members("comments") == {
            "list_doc_comments",
            "add_doc_comment",
            "resolve_doc_comment",
        }

    def test_local_files_is_exactly_the_local_only_tools(self):
        from .test_server import _LOCAL_ONLY_TOOLS

        assert _members("local-files") == _LOCAL_ONLY_TOOLS

    def test_group_and_tool_names_are_disjoint(self):
        assert not tool_groups.GROUP_NAMES & set(_registrations())

    def test_old_names_are_neither_tools_nor_groups_and_point_at_a_tool(self):
        tools = set(_registrations())
        for old, renamed in tool_groups.RENAMED_TOOLS.items():
            assert old not in tools | tool_groups.GROUP_NAMES
            assert renamed.new in tools

    def test_an_unknown_declared_group_fails_at_import(self):
        with pytest.raises(ValueError, match="unknown tool group"):
            tool_groups.tool_groups("mcp_gee_sweet.tools.gmail", groups=("coments",))


# Values in the user docs: `ENABLED_TOOLS=...` or the JSON `"ENABLED_TOOLS": "..."`.
# Only lowercase identifier entries are checked, so a placeholder like `<your list>`
# or `${user_config.enabled_tools}` is left alone.
_DOC_VALUE = re.compile(r'ENABLED_TOOLS(?:=|": ")([A-Za-z0-9_,\-]+)')
_ENTRY = re.compile(r"^[a-z][a-z0-9_\-]*$")


def _user_docs() -> list[Path]:
    """README and the published docs, not the QA, design or decision records, which
    quote invalid values on purpose."""
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


class TestDocsNameRealEntries:
    def test_every_entry_in_the_docs_exists(self):
        known = set(_registrations()) | tool_groups.GROUP_NAMES | set(tool_groups.RENAMED_TOOLS)
        unknown = []
        for path in _user_docs():
            for value in _DOC_VALUE.findall(path.read_text()):
                for entry in value.split(","):
                    if entry and _ENTRY.match(entry) and entry not in known:
                        unknown.append(f"{path.relative_to(ROOT)}: {entry}")
        assert unknown == []


class TestSelection:
    def test_unset_selects_default_only(self):
        selection = Selection.from_entries(())
        assert selection.entries == ("default",) and not selection.configured
        assert selection.selects("get_sheet_data", frozenset({"default", "sheets"}))
        assert not selection.selects("add_rows", frozenset({"sheets"}))

    def test_union_of_a_group_and_a_name(self):
        selection = Selection.from_entries(("docs", "list_events"))
        assert selection.selects("add_doc_comment", frozenset({"docs", "comments"}))
        assert selection.selects("list_events", frozenset({"calendar", "default"}))
        assert not selection.selects("get_event", frozenset({"calendar", "default"}))

    def test_all_selects_everything(self):
        assert Selection.from_entries(("all",)).selects("x", frozenset())

    def test_unknown_entries_keep_their_order(self):
        selection = Selection.from_entries(("ALL", "docs", "get_sheet_dta", "get_sheet_data"))
        assert selection.unknown_entries({"get_sheet_data"}) == ["ALL", "get_sheet_dta"]

    def test_an_old_name_selects_its_new_tool_and_is_known(self):
        renamed = {"old_tool": Renamed("new_tool", "v1.0")}
        selection = Selection.from_entries(("old_tool",), renamed)
        assert selection.selects("new_tool", frozenset())
        assert selection.unknown_entries({"new_tool"}) == []
        assert selection.aliases_for("new_tool") == ["old_tool"]

    def test_all_registers_aliases_and_a_group_never_does(self):
        renamed = {"old_tool": Renamed("new_tool", "v1.0")}
        assert Selection.from_entries(("all",), renamed).aliases_for("new_tool") == ["old_tool"]
        by_group = Selection.from_entries(("docs", "new_tool"), renamed)
        assert by_group.aliases_for("new_tool") == []

    def test_describe_default(self):
        line = Selection.from_entries(()).describe({"a", "b", "c"})
        assert line.startswith("Tools: this server loads the default tool group, out of 3.")
        assert "local-files" in line and "or all." in line

    def test_describe_groups_and_names(self):
        line = Selection.from_entries(("docs", "gmail", "list_events", "bogus")).describe(
            {"list_events", "x"}
        )
        assert line.startswith(
            "Tools: this server loads the docs, gmail tool groups plus 1 individually "
            "named tool, out of 2."
        )

    def test_describe_all(self):
        line = Selection.from_entries(("all",)).describe({"a", "b"})
        assert line == "Tools: every tool is loaded (2), because ENABLED_TOOLS includes all."


class TestAliasRegistration:
    """An old name registers a callable alias of the new tool, in-process against a
    fresh MCPServer so the module's own registry stays as it is."""

    @pytest.fixture
    def fresh_mcp(self, monkeypatch):
        fresh = MCPServer("test")
        monkeypatch.setattr(server, "mcp", fresh)
        monkeypatch.setattr(server, "_known_tools", {})
        monkeypatch.setattr(server, "_registered_tool_modules", set())
        return fresh

    @staticmethod
    def _new_tool():
        async def new_tool(value: int) -> dict:
            """Do the thing."""
            return {"value": value}

        new_tool.__module__ = "mcp_gee_sweet.tools.sheets.data"
        return new_tool

    def _select(self, monkeypatch, *entries):
        renamed = {"old_tool": Renamed("new_tool", "v1.0")}
        monkeypatch.setattr(server, "SELECTION", Selection.from_entries(entries, renamed))

    def test_named_old_name_registers_both(self, monkeypatch, fresh_mcp):
        self._select(monkeypatch, "old_tool")
        server.tool()(self._new_tool())
        tools = {t.name: t for t in fresh_mcp._tool_manager.list_tools()}
        assert set(tools) == {"new_tool", "old_tool"}
        assert tools["old_tool"].description.startswith(
            "Deprecated: use `new_tool`. Removed in v1.0."
        )
        assert "Do the thing." in tools["old_tool"].description

    async def test_the_alias_calls_the_new_tool(self, monkeypatch, fresh_mcp):
        self._select(monkeypatch, "old_tool")
        server.tool()(self._new_tool())
        alias = fresh_mcp._tool_manager.get_tool("old_tool")
        assert await alias.fn(value=3) == {"value": 3}

    def test_the_alias_rejects_unknown_arguments(self, monkeypatch, fresh_mcp):
        self._select(monkeypatch, "old_tool")
        server.tool()(self._new_tool())
        arg_model = fresh_mcp._tool_manager.get_tool("old_tool").fn_metadata.arg_model
        assert arg_model.model_config["extra"] == "forbid"

    def test_a_group_registers_only_the_new_tool(self, monkeypatch, fresh_mcp):
        self._select(monkeypatch, "sheets")
        server.tool()(self._new_tool())
        assert {t.name for t in fresh_mcp._tool_manager.list_tools()} == {"new_tool"}

    def test_all_registers_the_alias(self, monkeypatch, fresh_mcp):
        self._select(monkeypatch, "all")
        server.tool()(self._new_tool())
        assert {t.name for t in fresh_mcp._tool_manager.list_tools()} == {
            "new_tool",
            "old_tool",
        }

    def test_an_old_name_warns_once(self, monkeypatch):
        warning = MagicMock()
        monkeypatch.setattr(server.logger, "warning", warning)
        renamed = {"old_tool": Renamed("new_tool", "v1.0")}
        server._log_selection_problems(Selection.from_entries(("old_tool",), renamed))
        assert [c.args for c in warning.call_args_list] == [
            (
                "ENABLED_TOOLS: %s was renamed %s; loading %s. The old name is removed in %s.",
                "old_tool",
                "new_tool",
                "new_tool",
                "v1.0",
            )
        ]


class TestUnknownEntryWarning:
    def _warnings(self, monkeypatch, *entries):
        warning = MagicMock()
        monkeypatch.setattr(server.logger, "warning", warning)
        server._log_selection_problems(Selection.from_entries(entries))
        return [c.args for c in warning.call_args_list]

    def test_one_unknown_entry(self, monkeypatch):
        args = self._warnings(monkeypatch, "ALL")
        assert len(args) == 1
        assert args[0][1:] == ("ALL", "s")
        assert args[0][0] % args[0][1:] == (
            "ENABLED_TOOLS: ignoring ALL, which names no tool or tool group. "
            "Names are case-sensitive; see docs/tools.md for tool names."
        )

    def test_several_unknown_entries(self, monkeypatch):
        args = self._warnings(monkeypatch, "get_sheet_dta", "docs", "Docs")
        assert args[0][0] % args[0][1:] == (
            "ENABLED_TOOLS: ignoring get_sheet_dta, Docs, which name no tool or tool group. "
            "Names are case-sensitive; see docs/tools.md for tool names."
        )

    @pytest.mark.parametrize("entries", [(), ("all",), ("docs", "get_sheet_data", "local-files")])
    def test_known_entries_stay_quiet(self, monkeypatch, entries):
        assert self._warnings(monkeypatch, *entries) == []


def _launch(env: dict[str, str]) -> tuple[list[str], bool, str, str]:
    """Import the server in a fresh interpreter with `env`: its registered tools,
    whether Gmail's scope is requested, its `instructions`, and stderr."""
    code = (
        "import json, sys\n"
        "sys.argv = ['mcp-gee-sweet']\n"
        "from mcp_gee_sweet import auth, server\n"
        "print(json.dumps([sorted(t.name for t in server.mcp._tool_manager.list_tools()),\n"
        "    auth._gmail_enabled, server.mcp.instructions]))\n"
    )
    full_env = {
        k: v for k, v in os.environ.items() if k not in ("LOCAL_FILE_ACCESS", "ENABLED_TOOLS")
    }
    full_env.update(env)
    proc = subprocess.run(
        [sys.executable, "-c", code], env=full_env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    names, gmail, instructions = json.loads(proc.stdout.strip().splitlines()[-1])
    return names, gmail, instructions, proc.stderr


class TestLaunch:
    """The acceptance criteria, on a real import."""

    def test_unset_registers_exactly_default(self):
        names, gmail, instructions, _ = _launch({})
        assert set(names) == DEFAULT_SNAPSHOT
        assert gmail is True
        assert instructions.startswith("Tools: this server loads the default tool group")

    def test_empty_is_unset(self):
        names, *_ = _launch({"ENABLED_TOOLS": ""})
        assert set(names) == DEFAULT_SNAPSHOT

    def test_all_registers_every_tool(self):
        names, _, instructions, _ = _launch({"ENABLED_TOOLS": "all"})
        assert set(names) == set(_registrations())
        assert instructions.startswith("Tools: every tool is loaded")

    def test_a_group_and_a_name_leave_gmail_out(self):
        names, gmail, _, stderr = _launch({"ENABLED_TOOLS": "docs,list_events"})
        assert set(names) == _members("docs") | {"list_events"}
        assert gmail is False
        assert "ENABLED_TOOLS: ignoring" not in stderr

    @pytest.mark.parametrize("value", ["ALL", "get_sheet_dta"])
    def test_an_unknown_entry_warns_and_the_server_still_starts(self, value):
        names, _, _, stderr = _launch({"ENABLED_TOOLS": value})
        assert names == []
        assert f"ENABLED_TOOLS: ignoring {value}, which names no tool or tool group." in stderr

    def test_auth_status_reports_the_selection(self):
        code = (
            "import json, sys\n"
            "sys.argv = ['mcp-gee-sweet']\n"
            "from mcp_gee_sweet import server\n"
            "print(json.dumps(json.loads(server._auth_status_json('oauth'))['tool_selection']))\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "ENABLED_TOOLS"}
        env["ENABLED_TOOLS"] = "gmail,get_sheet_data"
        proc = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout.strip().splitlines()[-1]) == {
            "entries": ["gmail", "get_sheet_data"],
            "configured": True,
            "registered_tools": len(_members("gmail")) + 1,
        }


class TestAuthStatusToolSelection:
    @pytest.mark.parametrize(
        "args",
        [
            ("oauth", False, None, None),
            ("service_account", True, None, None),
            ("none", False, None, "no usable token"),
        ],
    )
    def test_present_in_every_branch(self, monkeypatch, args):
        monkeypatch.setattr(server, "SELECTION", Selection.from_entries(()))
        status = json.loads(server._auth_status_json(*args))
        assert status["tool_selection"] == {
            "entries": ["default"],
            "configured": False,
            "registered_tools": len(server.mcp._tool_manager.list_tools()),
        }
