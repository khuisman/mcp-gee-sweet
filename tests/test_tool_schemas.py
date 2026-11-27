"""Lint every registered tool's schemas for client compatibility.

Some MCP clients silently drop a tool whose schema uses a construct they don't
support, or whose name breaks their naming rules: the tool just isn't in the
client's list, and nothing tells the user. These tests check the schemas exactly
as `tools/list` serves them (`MCPServer.list_tools()`, dumped by alias, the wire
form), so a schema change in any tool fails CI instead.

Each rule cites the client documentation or behavior behind it, checked
2026-11-26. Drop a rule once no supported client needs it.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest

from mcp_gee_sweet import local_files
from mcp_gee_sweet.server import mcp

# Rule 1: the schema root is a plain object: `"type": "object"`, with no
# composition keyword beside it.
# - Anthropic Messages API rejects the request with 400 "input_schema does not
#   support oneOf, allOf, or anyOf at the top level" (Claude Code reports
#   anthropics/claude-code#4886 and #27337 quote it; the "Define tools" page,
#   https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools,
#   doesn't state it). One bad tool fails the whole request, not only that tool.
# - OpenAI structured outputs / strict function calling: "Root objects must not
#   be anyOf and must be an object"
#   (https://developers.openai.com/api/docs/guides/structured-outputs,
#   "Supported schemas").
# - MCP spec (2025-11-25, schema.ts): `Tool.inputSchema` and `Tool.outputSchema`
#   are both typed `{ type: "object"; ... }`.
ROOT_TYPE = "object"
ROOT_COMPOSITION_KEYWORDS = ("oneOf", "anyOf", "allOf")

# Rule 2: no `$ref` anywhere (inline the definition instead).
# - Gemini function calling: "Only a subset of the OpenAPI schema is supported"
#   (https://ai.google.dev/gemini-api/docs/function-calling); the
#   FunctionDeclaration reference describes `parameters` as a Schema object
#   reflecting the OpenAPI 3.0.3 Parameter Object, which has no `$ref`
#   (https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/Shared.Types/FunctionDeclaration).
#   Client adapters for it inline or strip references before sending.
# - OpenAI strict mode and the Claude API do accept `$ref`; Gemini is the
#   client that needs this rule.
REF_KEYWORD = "$ref"

# Rule 3: tool names.
# - OpenAI function name: "Must be a-z, A-Z, 0-9, or contain underscores and
#   dashes, with a maximum length of 64" (openai-python's
#   `FunctionDefinition.name`, the API reference's text); the API's 400 for a
#   bad name quotes ^[a-zA-Z0-9_-]{1,64}$.
# - The Claude API allows ^[a-zA-Z0-9_-]{1,128}$ (define-tools page above), and
#   the MCP spec (2025-11-25, server/tools) allows 1-128 characters including
#   `.`, so OpenAI's rule is the strictest one a supported client applies.
TOOL_NAME_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,64}")

# JSON Schema keywords whose value maps names to subschemas: the map's keys are
# property or definition names, not keywords, so a property named "$ref" isn't
# a reference.
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
)
# Keywords whose value is instance data, not a schema: a `$ref` key inside a
# `default` object is just data.
_DATA_KEYWORDS = frozenset({"enum", "const", "default", "examples"})


def _pointer_token(key: str | int) -> str:
    """One JSON Pointer token (RFC 6901 escaping)."""
    return str(key).replace("~", "~0").replace("/", "~1")


def _find_refs(schema: Any, path: str = "") -> Iterator[str]:
    """Yield the JSON Pointer of every `$ref` keyword in `schema`."""
    if isinstance(schema, list):
        for i, item in enumerate(schema):
            yield from _find_refs(item, f"{path}/{i}")
        return
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        here = f"{path}/{_pointer_token(key)}"
        if key == REF_KEYWORD:
            yield here
        elif key in _DATA_KEYWORDS:
            continue
        elif key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for name, sub in value.items():
                yield from _find_refs(sub, f"{here}/{_pointer_token(name)}")
        else:
            yield from _find_refs(value, here)


def schema_problems(tool_name: str, field: str, schema: dict[str, Any]) -> list[str]:
    """Every rule `schema` breaks, each naming the tool and the offending path."""
    problems = []
    if schema.get("type") != ROOT_TYPE:
        problems.append(
            f"{tool_name}: {field}/type: root type is {schema.get('type')!r}, not {ROOT_TYPE!r}"
        )
    problems += [
        f"{tool_name}: {field}/{keyword}: `{keyword}` at the schema root"
        for keyword in ROOT_COMPOSITION_KEYWORDS
        if keyword in schema
    ]
    problems += [
        f"{tool_name}: {field}{pointer}: `$ref` (inline the definition)"
        for pointer in _find_refs(schema)
    ]
    return problems


def name_problems(tool_name: str) -> list[str]:
    if TOOL_NAME_PATTERN.fullmatch(tool_name):
        return []
    return [f"{tool_name!r}: tool name doesn't match ^{TOOL_NAME_PATTERN.pattern}$"]


async def _served_tools() -> list[dict[str, Any]]:
    tools = await mcp.list_tools()
    assert tools, "no tools registered — registration may be broken"
    return [t.model_dump(by_alias=True, mode="json", exclude_none=True) for t in tools]


class TestServedToolSchemas:
    """The suite runs with ENABLED_TOOLS=all and LOCAL_FILE_ACCESS=full (conftest), so
    every tool and alias is checked."""

    def test_local_only_tools_are_registered(self):
        # LOCAL_FILE_ACCESS=off drops the local-only tools after selection, and this
        # lint would then pass without seeing them.
        assert local_files.POLICY.mode is not local_files.LocalFileAccess.OFF

    async def test_input_and_output_schemas_are_client_compatible(self):
        problems: list[str] = []
        for tool in await _served_tools():
            for field in ("inputSchema", "outputSchema"):
                if (schema := tool.get(field)) is not None:
                    problems += schema_problems(tool["name"], field, schema)
        assert problems == [], "tool schema(s) some clients drop:\n" + "\n".join(problems)

    async def test_tool_names_are_client_compatible(self):
        problems = [p for tool in await _served_tools() for p in name_problems(tool["name"])]
        assert problems == [], "tool name(s) some clients reject:\n" + "\n".join(problems)

    async def test_output_schemas_are_served(self):
        # Guards the output-schema half of the lint against a dump that drops the
        # field: at least some tools declare one.
        assert any("outputSchema" in tool for tool in await _served_tools())


class TestSchemaProblems:
    """The checker itself: each rule fails with the tool name and the offending path."""

    @pytest.mark.parametrize("keyword", ROOT_COMPOSITION_KEYWORDS)
    def test_root_composition_keyword(self, keyword):
        schema = {"type": "object", keyword: [{"type": "object"}, {"type": "object"}]}
        assert schema_problems("t", "inputSchema", schema) == [
            f"t: inputSchema/{keyword}: `{keyword}` at the schema root"
        ]

    @pytest.mark.parametrize("root_type", [None, "array", ["object", "null"]])
    def test_root_type_must_be_object(self, root_type):
        schema = {"properties": {}} if root_type is None else {"type": root_type}
        assert schema_problems("t", "outputSchema", schema) == [
            f"t: outputSchema/type: root type is {root_type!r}, not 'object'"
        ]

    def test_nested_composition_keyword_is_allowed(self):
        schema = {
            "type": "object",
            "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        }
        assert schema_problems("t", "inputSchema", schema) == []

    def test_ref_anywhere_reports_its_pointer(self):
        schema = {
            "type": "object",
            "properties": {
                "a": {"$ref": "#/$defs/A"},
                "b": {"type": "array", "items": {"anyOf": [{"$ref": "#/$defs/B"}]}},
            },
            "$defs": {"A": {"type": "string"}, "B": {"type": "integer"}},
        }
        assert schema_problems("t", "outputSchema", schema) == [
            "t: outputSchema/properties/a/$ref: `$ref` (inline the definition)",
            "t: outputSchema/properties/b/items/anyOf/0/$ref: `$ref` (inline the definition)",
        ]

    def test_property_named_ref_is_not_a_ref(self):
        schema = {"type": "object", "properties": {"$ref": {"type": "string"}}}
        assert schema_problems("t", "inputSchema", schema) == []

    def test_ref_key_in_instance_data_is_not_a_ref(self):
        schema = {
            "type": "object",
            "properties": {
                "x": {
                    "type": "object",
                    "default": {"$ref": "data"},
                    "examples": [{"$ref": "data"}],
                    "enum": [{"$ref": "data"}],
                    "const": {"$ref": "data"},
                }
            },
        }
        assert schema_problems("t", "inputSchema", schema) == []

    def test_pointer_escapes_slash_and_tilde(self):
        schema = {"type": "object", "properties": {"a/b~c": {"$ref": "#/x"}}}
        assert schema_problems("t", "inputSchema", schema) == [
            "t: inputSchema/properties/a~1b~0c/$ref: `$ref` (inline the definition)"
        ]


class TestNameProblems:
    @pytest.mark.parametrize("name", ["get_sheet_data", "a", "a-b_C9", "x" * 64])
    def test_valid(self, name):
        assert name_problems(name) == []

    @pytest.mark.parametrize("name", ["", "x" * 65, "has.dot", "has space", "naïve"])
    def test_invalid(self, name):
        assert name_problems(name) == [f"{name!r}: tool name doesn't match ^[a-zA-Z0-9_-]{{1,64}}$"]
