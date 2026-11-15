"""Deprecating a tool or a tool parameter for one release (#1209): the helpers in
`deprecation.py`, registered through `server.tool()` against a fresh MCPServer so the
module's own registry stays as it is, and called through mcp's own `call_tool`."""

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_gee_sweet import server
from mcp_gee_sweet.deprecation import (
    DEPRECATION_WARNINGS_KEY,
    ToolDeprecation,
    deprecated_tool,
    deprecation_doc,
    renamed_params,
    tool_deprecation,
    with_deprecation_warnings,
)
from mcp_gee_sweet.tool_groups import Selection

_MODULE = "mcp_gee_sweet.tools.docs.comments"


@pytest.fixture
def fresh_mcp(monkeypatch):
    fresh = MCPServer("test")
    monkeypatch.setattr(server, "mcp", fresh)
    monkeypatch.setattr(server, "SELECTION", Selection.from_entries(("all",), {}))
    monkeypatch.setattr(server, "_known_tools", {})
    monkeypatch.setattr(server, "_registered_tool_modules", set())
    monkeypatch.setattr(server, "_registered_tools", {})
    monkeypatch.setattr(server, "_registered_aliases", [])
    monkeypatch.setattr(server, "_deprecated_tools", {})
    return fresh


def _ctx(srv):
    healthy = SimpleNamespace(unauthorized_message=None, auth_method="oauth")
    return Context(request_context=SimpleNamespace(lifespan_context=healthy), mcp_server=srv)


async def _call(srv, name, arguments):
    """The tool's structured result, through mcp's own argument validation and
    output conversion, so a warning that broke the output schema would fail here."""
    result = await srv.call_tool(name, arguments, _ctx(srv))
    return result.structured_content


def _list_comments():
    async def list_comments(doc_id: str, limit: int = 10, ctx: Context = None) -> dict[str, Any]:
        """List the comments.

        Args:
            doc_id: The document.
        """
        return {"doc_id": doc_id, "limit": limit}

    list_comments.__module__ = _MODULE
    return list_comments


class TestDeprecationDoc:
    def test_the_note_leads_and_the_body_is_dedented(self):
        doc = "Summary.\n\n        Args:\n            x: thing.\n        "
        assert (
            deprecation_doc("Deprecated.", doc) == "Deprecated.\n\nSummary.\n\nArgs:\n    x: thing."
        )

    def test_no_docstring(self):
        assert deprecation_doc("Deprecated.", None) == "Deprecated."


class TestWithDeprecationWarnings:
    def test_adds_a_list_without_mutating(self):
        result = {"a": 1}
        assert with_deprecation_warnings(result, ["w"]) == {"a": 1, DEPRECATION_WARNINGS_KEY: ["w"]}
        assert result == {"a": 1}

    def test_no_warnings_leaves_the_result_alone(self):
        result = {"a": 1}
        assert with_deprecation_warnings(result, []) is result


class TestDeprecatedTool:
    def _old_share(self):
        @deprecated_tool(use="`share_file`", removed_in="v1.0")
        async def old_share(file_id: str) -> dict[str, Any]:
            """Share a spreadsheet."""
            return {"shared": file_id}

        old_share.__module__ = "mcp_gee_sweet.tools.drive.sharing"
        return old_share

    def test_description_opens_with_the_replacement(self, fresh_mcp):
        server.tool()(self._old_share())
        description = fresh_mcp._tool_manager.get_tool("old_share").description
        assert (
            description
            == "Deprecated: use `share_file` instead. Removed in v1.0.\n\nShare a spreadsheet."
        )

    def test_it_still_works(self, fresh_mcp):
        server.tool()(self._old_share())
        assert tool_deprecation(self._old_share()) == ToolDeprecation("`share_file`", "v1.0")

    async def test_it_is_callable(self, fresh_mcp):
        server.tool()(self._old_share())
        assert await _call(fresh_mcp, "old_share", {"file_id": "f"}) == {"shared": "f"}

    def test_auth_status_lists_it(self, fresh_mcp):
        server.tool()(self._old_share())
        assert server._tool_selection_status()["deprecated_tools"] == ["old_share"]

    def test_naming_it_warns_at_startup(self, monkeypatch, fresh_mcp):
        server.tool()(self._old_share())
        warning = MagicMock()
        monkeypatch.setattr(server.logger, "warning", warning)
        server._log_selection_problems(Selection.from_entries(("old_share",), {}))
        assert [c.args for c in warning.call_args_list] == [
            (
                "ENABLED_TOOLS: %s is deprecated; use %s instead. It is removed in %s.",
                "old_share",
                "`share_file`",
                "v1.0",
            )
        ]

    @pytest.mark.parametrize("entries", [("all",), ("drive",), ("default",)])
    def test_a_group_stays_quiet(self, monkeypatch, fresh_mcp, entries):
        server.tool()(self._old_share())
        warning = MagicMock()
        monkeypatch.setattr(server.logger, "warning", warning)
        server._log_selection_problems(Selection.from_entries(entries, {}))
        assert warning.call_args_list == []

    def test_an_unmarked_tool_isnt_deprecated(self, fresh_mcp):
        server.tool()(_list_comments())
        assert server._tool_selection_status()["deprecated_tools"] == []


class TestRenamedParams:
    def _register(self, fresh_mcp, func=None, **old_to_new):
        func = func or _list_comments()
        server.tool()(
            renamed_params(removed_in="v1.0", **(old_to_new or {"file_id": "doc_id"}))(func)
        )
        return fresh_mcp._tool_manager.get_tool(func.__name__)

    async def test_the_new_name_has_no_warning(self, fresh_mcp):
        self._register(fresh_mcp)
        assert await _call(fresh_mcp, "list_comments", {"doc_id": "d"}) == {
            "doc_id": "d",
            "limit": 10,
        }

    async def test_the_old_name_works_and_warns(self, fresh_mcp):
        self._register(fresh_mcp)
        assert await _call(fresh_mcp, "list_comments", {"file_id": "d", "limit": 2}) == {
            "doc_id": "d",
            "limit": 2,
            DEPRECATION_WARNINGS_KEY: [
                "`file_id` is deprecated: use `doc_id`. `file_id` is removed in v1.0."
            ],
        }

    async def test_both_names_is_an_error(self, fresh_mcp):
        self._register(fresh_mcp)
        with pytest.raises(ToolError, match="Pass only `doc_id`"):
            await _call(fresh_mcp, "list_comments", {"file_id": "d", "doc_id": "d"})

    async def test_neither_name_is_an_error(self, fresh_mcp):
        self._register(fresh_mcp)
        with pytest.raises(ToolError, match="Missing required argument `doc_id`"):
            await _call(fresh_mcp, "list_comments", {})

    async def test_unknown_arguments_are_still_rejected(self, fresh_mcp):
        self._register(fresh_mcp)
        with pytest.raises(ToolError):
            await _call(fresh_mcp, "list_comments", {"doc_id": "d", "fileid": "d"})

    def test_schema_describes_the_old_name_as_deprecated(self, fresh_mcp):
        schema = self._register(fresh_mcp).parameters
        assert (
            schema["properties"]["file_id"]["description"]
            == "Deprecated: use `doc_id`. Removed in v1.0."
        )
        assert "doc_id" not in schema.get("required", [])
        assert set(schema["properties"]) == {"doc_id", "limit", "file_id"}

    async def test_an_optional_new_parameter_stays_optional_with_its_default(self, fresh_mcp):
        self._register(fresh_mcp, max_results="limit")
        assert await _call(fresh_mcp, "list_comments", {"doc_id": "d", "max_results": 4}) == {
            "doc_id": "d",
            "limit": 4,
            DEPRECATION_WARNINGS_KEY: [
                "`max_results` is deprecated: use `limit`. `max_results` is removed in v1.0."
            ],
        }
        schema = fresh_mcp._tool_manager.get_tool("list_comments").parameters
        assert schema["required"] == ["doc_id"]
        assert schema["properties"]["limit"]["default"] == 10

    async def test_both_names_with_the_new_one_off_its_default_is_an_error(self, fresh_mcp):
        self._register(fresh_mcp, max_results="limit")
        with pytest.raises(ToolError, match="Pass only `limit`"):
            await _call(fresh_mcp, "list_comments", {"doc_id": "d", "limit": 3, "max_results": 4})

    async def test_a_direct_positional_call_still_works(self):
        wrapped = renamed_params(removed_in="v1.0", file_id="doc_id")(_list_comments())
        assert await wrapped("d", 3) == {"doc_id": "d", "limit": 3}

    async def test_an_existing_warning_list_is_extended_not_replaced(self):
        async def tool(doc_id: str) -> dict[str, Any]:
            return {DEPRECATION_WARNINGS_KEY: ["earlier"]}

        wrapped = renamed_params(removed_in="v1.0", file_id="doc_id")(tool)
        result = await wrapped(file_id="d")
        assert result[DEPRECATION_WARNINGS_KEY][0] == "earlier"
        assert len(result[DEPRECATION_WARNINGS_KEY]) == 2

    def test_the_published_signature_reaches_the_generated_docs(self):
        wrapped = renamed_params(removed_in="v1.0", file_id="doc_id")(_list_comments())
        assert list(inspect.signature(wrapped).parameters) == ["doc_id", "limit", "ctx", "file_id"]

    @pytest.mark.parametrize(
        "annotation",
        [dict, dict[str, Any], dict[str, Any] | None],
    )
    def test_open_dict_results_are_accepted(self, annotation):
        async def tool(doc_id: str):
            return {}

        tool.__annotations__["return"] = annotation
        renamed_params(removed_in="v1.0", file_id="doc_id")(tool)

    @pytest.mark.parametrize(
        "annotation", [list[dict], str, dict[str, list[dict]], inspect.Parameter.empty]
    )
    def test_other_results_fail_at_import(self, annotation):
        async def tool(doc_id: str):
            return {}

        if annotation is not inspect.Parameter.empty:
            tool.__annotations__["return"] = annotation
        with pytest.raises(TypeError, match="must return dict"):
            renamed_params(removed_in="v1.0", file_id="doc_id")(tool)

    def test_a_missing_new_parameter_fails_at_import(self):
        with pytest.raises(TypeError, match="no parameter 'document_id'"):
            renamed_params(removed_in="v1.0", file_id="document_id")(_list_comments())

    def test_an_old_name_that_is_still_a_parameter_fails_at_import(self):
        with pytest.raises(TypeError, match="'limit' is still a parameter"):
            renamed_params(removed_in="v1.0", limit="doc_id")(_list_comments())

    def test_no_pairs_fails(self):
        with pytest.raises(ValueError):
            renamed_params(removed_in="v1.0")
