"""Tests for scripts/gen_tool_docs.py.

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "gen_tool_docs.py"
_spec = importlib.util.spec_from_file_location("gen_tool_docs", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
gen_tool_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_tool_docs)


def make_func(name, doc, params=""):
    """Build a throwaway function with a given name, docstring, and parameter list."""
    ns = {}
    exec(f"def {name}({params}):\n    '''{doc}'''\n    pass", ns)
    return ns[name]


class TestCollectAndDocstrings:
    def test_collect_tools_returns_every_registered_tool(self):
        funcs = gen_tool_docs.collect_tools()
        names = {f.__name__ for f in funcs}
        assert "get_sheet_data" in names
        assert "create_doc" in names
        assert "list_calendars" in names
        assert len(funcs) == len(names)  # no duplicate registrations

    def test_require_docstrings_passes_on_real_tools(self):
        funcs = gen_tool_docs.collect_tools()
        gen_tool_docs.require_docstrings(funcs)  # should not raise

    def test_require_docstrings_raises_on_missing_docstring(self):
        def undocumented():
            pass

        with pytest.raises(RuntimeError, match="undocumented"):
            gen_tool_docs.require_docstrings([undocumented])


class TestSummaryAndParamList:
    def test_summary_takes_first_paragraph_only(self):
        func = make_func(
            "f",
            "Do the thing.\\n\\n    Args:\\n        x: unused\\n    ",
        )
        assert gen_tool_docs.summary(func) == "Do the thing."

    def test_summary_joins_wrapped_lines(self):
        func = make_func("f", "Do the\\n    thing across two lines.")
        assert gen_tool_docs.summary(func) == "Do the thing across two lines."

    def test_param_list_excludes_ctx_and_marks_optional(self):
        func = make_func("f", "doc", params="a, b=1, ctx=None")
        assert gen_tool_docs.param_list(func) == "`a`, `b?`"

    def test_param_list_empty_renders_em_dash(self):
        func = make_func("f", "doc", params="ctx=None")
        assert gen_tool_docs.param_list(func) == "—"


class TestRenderToolsMd:
    def test_covers_every_real_tool(self):
        # Section notes sometimes reference a tool by name too (e.g. `batch_update`
        # as the escape hatch), so assert presence rather than an exact count.
        funcs = gen_tool_docs.collect_tools()
        rendered = gen_tool_docs.render_tools_md(funcs)
        for func in funcs:
            assert f"`{func.__name__}`" in rendered

    def test_raises_when_a_tool_matches_no_section(self):
        def mystery_tool():
            """Does something undocumented in SECTIONS."""

        mystery_tool.__module__ = "mcp_gee_sweet.tools.nonexistent"
        with pytest.raises(RuntimeError, match="mystery_tool"):
            gen_tool_docs.render_tools_md([mystery_tool])


class TestRenderSubsetsBlock:
    def test_validates_against_real_tool_set(self):
        funcs = gen_tool_docs.collect_tools()
        known_names = {f.__name__ for f in funcs}
        gen_tool_docs.render_subsets_block(known_names)  # should not raise

    def test_raises_on_unknown_tool_in_subset(self):
        with pytest.raises(RuntimeError, match="Read-only Sheets"):
            gen_tool_docs.render_subsets_block(known_names=set())

    def test_renders_each_subset_with_its_tool_count(self):
        funcs = gen_tool_docs.collect_tools()
        known_names = {f.__name__ for f in funcs}
        rendered = gen_tool_docs.render_subsets_block(
            known_names, gen_tool_docs.service_subsets(funcs)
        )
        assert "**Read-only Sheets** (7 tools):" in rendered
        assert "**Docs + Drive (combined example)**" in rendered

    def test_raises_on_subset_at_client_limit(self):
        names = [f"tool_{i}" for i in range(gen_tool_docs.CLIENT_TOOL_LIMIT)]
        known_names = set(names)
        for _name, tool_names in gen_tool_docs.SUBSETS:
            known_names.update(tool_names)
        with pytest.raises(RuntimeError, match="too_big"):
            gen_tool_docs.render_subsets_block(known_names, [("too_big", names)])


class TestServiceSubsets:
    def test_each_service_subset_holds_its_sections_tools(self):
        funcs = gen_tool_docs.collect_tools()
        subsets = dict(gen_tool_docs.service_subsets(funcs))
        docs_tools = {
            f.__name__ for f in funcs if f.__module__.startswith("mcp_gee_sweet.tools.docs.")
        }
        assert set(subsets["All Docs tools"]) == docs_tools
        assert "list_spreadsheets" in subsets["All Sheets tools"]
        assert "list_spreadsheets" not in subsets["All Drive tools"]

    def test_combined_subset_is_the_union_of_its_parts(self):
        funcs = gen_tool_docs.collect_tools()
        subsets = dict(gen_tool_docs.service_subsets(funcs))
        name, parts = gen_tool_docs.COMBINED_SUBSET
        assert subsets[name] == [tool for part in parts for tool in subsets[part]]

    def test_every_generated_subset_is_under_the_client_limit(self):
        funcs = gen_tool_docs.collect_tools()
        for name, tool_names in gen_tool_docs.service_subsets(funcs):
            assert len(set(tool_names)) < gen_tool_docs.CLIENT_TOOL_LIMIT, name

    def test_raises_on_unknown_section(self, monkeypatch):
        monkeypatch.setattr(gen_tool_docs, "SERVICE_SUBSETS", [("Broken", ["No such section"])])
        with pytest.raises(RuntimeError, match="No such section"):
            gen_tool_docs.service_subsets([])


class TestWriteIfChanged:
    def test_writes_new_file_and_reports_changed(self, tmp_path):
        target = tmp_path / "out.md"
        assert gen_tool_docs.write_if_changed(target, "content") is True
        assert target.read_text() == "content"

    def test_no_write_when_content_matches(self, tmp_path):
        target = tmp_path / "out.md"
        target.write_text("content")
        mtime_before = target.stat().st_mtime_ns
        assert gen_tool_docs.write_if_changed(target, "content") is False
        assert target.stat().st_mtime_ns == mtime_before

    def test_overwrites_when_content_differs(self, tmp_path):
        target = tmp_path / "out.md"
        target.write_text("old")
        assert gen_tool_docs.write_if_changed(target, "new") is True
        assert target.read_text() == "new"


class TestMainIdempotency:
    def test_second_run_reports_up_to_date(self, tmp_path, monkeypatch, capsys):
        tools_md = tmp_path / "tools.md"
        config_md = tmp_path / "configuration.md"
        config_md.write_text("## Tool filtering\nstale text\n## Caching\nmore\n")

        monkeypatch.setattr(gen_tool_docs, "TOOLS_MD", tools_md)
        monkeypatch.setattr(gen_tool_docs, "CONFIG_MD", config_md)

        first = gen_tool_docs.main()
        assert first == 1
        second = gen_tool_docs.main()
        assert second == 0
        assert "up to date" in capsys.readouterr().out
