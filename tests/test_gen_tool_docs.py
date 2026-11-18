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


def _groups_by_name() -> dict[str, frozenset[str]]:
    groups: dict[str, frozenset[str]] = {}
    gen_tool_docs.collect_tools(groups)
    return groups


class TestCollectGroups:
    """#1364: the script reads each tool's groups as the server computes them."""

    def test_matches_the_server_computation(self):
        # server._known_tools is what server.tool() recorded at import for every
        # tool, registered or not; the test process runs with ENABLED_TOOLS=all.
        from mcp_gee_sweet import server

        assert _groups_by_name() == server._known_tools

    def test_capture_takes_exactly_server_tools_flags(self, monkeypatch):
        # No catch-all: a new server.tool() flag must fail the script, not vanish.
        import inspect

        from mcp_gee_sweet import server

        captured = {}

        def register_all(tool):
            captured["params"] = list(inspect.signature(tool).parameters)

        monkeypatch.setattr(gen_tool_docs, "register_all", register_all)
        gen_tool_docs.collect_tools()
        assert captured["params"] == list(inspect.signature(server.tool).parameters)

    def test_records_the_default_group(self):
        from .test_tool_groups import DEFAULT_SNAPSHOT

        default = {name for name, groups in _groups_by_name().items() if "default" in groups}
        assert default == DEFAULT_SNAPSHOT


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
        groups: dict[str, frozenset[str]] = {}
        funcs = gen_tool_docs.collect_tools(groups)
        rendered = gen_tool_docs.render_tools_md(funcs, groups)
        for func in funcs:
            assert f"`{func.__name__}`" in rendered

    def test_each_row_lists_the_tools_groups(self):
        groups: dict[str, frozenset[str]] = {}
        funcs = gen_tool_docs.collect_tools(groups)
        rows = {
            line.split("|")[1].strip(): line.split("|")[-2].strip()
            for line in gen_tool_docs.render_tools_md(funcs, groups).splitlines()
            if line.startswith("| `")
        }
        assert rows["`create_doc_from_file`"] == "`docs`, `local-files`"
        assert rows["`add_doc_comment`"] == "`docs`, `comments`"
        assert rows["`list_labels`"] == "`gmail`, `default`"
        assert rows["`refresh_cache`"] == "`cache`"
        # A tool in a second service group lists its own module's first (#1511).
        assert rows["`list_spreadsheets`"] == "`drive`, `sheets`"
        assert rows["`create_spreadsheet`"] == "`drive`, `sheets`, `default`"
        assert rows["`import_csv_to_sheet`"] == "`drive`, `sheets`, `local-files`"

    def test_raises_when_a_tool_matches_no_section(self):
        def mystery_tool():
            """Does something undocumented in SECTIONS."""

        mystery_tool.__module__ = "mcp_gee_sweet.tools.nonexistent"
        with pytest.raises(RuntimeError, match="mystery_tool"):
            gen_tool_docs.render_tools_md([mystery_tool], {"mystery_tool": frozenset()})


class TestRenderFilteringBlock:
    def test_states_the_default_count(self):
        groups = _groups_by_name()
        default = [name for name, g in groups.items() if "default" in g]
        rendered = gen_tool_docs.render_filtering_block(groups).replace("\n", " ")
        assert f"registers the `default` tool group, {len(default)} of the {len(groups)}" in (
            rendered
        )

    def test_one_row_per_group_with_its_count(self):
        from mcp_gee_sweet import tool_groups

        groups = _groups_by_name()
        rendered = gen_tool_docs.render_filtering_block(groups)
        rows = {
            line.split("|")[1].strip(): int(line.split("|")[2])
            for line in rendered.splitlines()
            if line.startswith("| `")
        }
        assert set(rows) == {f"`{g}`" for g in tool_groups.GROUP_NAMES}
        assert rows["`all`"] == len(groups)
        for group in tool_groups.GROUP_NAMES - {"all"}:
            assert rows[f"`{group}`"] == sum(group in g for g in groups.values()), group

    def test_lists_the_default_tools(self):
        from .test_tool_groups import DEFAULT_SNAPSHOT

        rendered = gen_tool_docs.render_filtering_block(_groups_by_name())
        lines = rendered.splitlines()
        listed = lines[lines.index("**What `default` holds:**") + 2]
        assert set(listed.split(",")) == DEFAULT_SNAPSHOT

    def test_raises_on_an_undocumented_group(self, monkeypatch):
        descriptions = dict(gen_tool_docs.GROUP_DESCRIPTIONS)
        del descriptions["comments"]
        monkeypatch.setattr(gen_tool_docs, "GROUP_DESCRIPTIONS", descriptions)
        with pytest.raises(RuntimeError, match="undocumented: comments"):
            gen_tool_docs.render_filtering_block(_groups_by_name())

    def test_raises_on_an_unknown_group(self, monkeypatch):
        descriptions = {**gen_tool_docs.GROUP_DESCRIPTIONS, "bogus": "x"}
        monkeypatch.setattr(gen_tool_docs, "GROUP_DESCRIPTIONS", descriptions)
        with pytest.raises(RuntimeError, match="unknown: bogus"):
            gen_tool_docs.render_filtering_block(_groups_by_name())

    def test_raises_on_a_group_at_the_client_limit(self):
        limit = gen_tool_docs.CLIENT_TOOL_LIMIT
        groups = {
            **_groups_by_name(),
            **{f"tool_{i}": frozenset({"docs"}) for i in range(limit)},
        }
        with pytest.raises(RuntimeError, match="'docs' has"):
            gen_tool_docs.render_filtering_block(groups)

    def test_all_counts_the_deprecated_aliases(self, monkeypatch):
        from mcp_gee_sweet import tool_groups

        groups = _groups_by_name()
        monkeypatch.setattr(
            tool_groups,
            "RENAMED_TOOLS",
            {
                "old_a": tool_groups.Renamed("create_doc", "9.9"),
                "old_b": tool_groups.Renamed("list_files", "9.9"),
            },
        )
        rendered = gen_tool_docs.render_filtering_block(groups)
        assert f"| `all` | {len(groups) + 2} |" in rendered
        # The opening sentence counts tools, not aliases.
        assert f"of the {len(groups)} tools" in rendered.replace("\n", " ")

    def test_derived_lists_name_the_groups_own_tools(self):
        groups = _groups_by_name()
        rendered = gen_tool_docs.render_filtering_block(groups)
        for group in ("cache", "comments"):
            row = next(line for line in rendered.splitlines() if line.startswith(f"| `{group}` |"))
            for name, member_of in groups.items():
                assert (f"`{name}`" in row) == (group in member_of), (group, name)

    def test_raises_on_a_false_membership_claim(self, monkeypatch):
        monkeypatch.setattr(
            gen_tool_docs, "MEMBERSHIP_CLAIMS", (("create_spreadsheet", "docs", True),)
        )
        with pytest.raises(RuntimeError, match="create_spreadsheet in docs"):
            gen_tool_docs.render_filtering_block(_groups_by_name())

    def test_raises_when_a_left_out_tool_joins_default(self):
        groups = _groups_by_name()
        groups["sync_folder"] = groups["sync_folder"] | {"default"}
        with pytest.raises(RuntimeError, match="sync_folder not in default"):
            gen_tool_docs.render_filtering_block(groups)

    def test_raises_on_a_renamed_tool_named_in_the_prose(self):
        groups = _groups_by_name()
        groups["get_cache_ttl_v2"] = groups.pop("get_cache_ttl")
        # The cache row is derived, so it follows the rename; a hand-written name
        # elsewhere doesn't, and check_names catches it.
        gen_tool_docs.render_filtering_block(groups)  # should not raise
        groups["insert_doc_table_v2"] = groups.pop("insert_doc_table")
        with pytest.raises(RuntimeError, match="insert_doc_table"):
            gen_tool_docs.render_filtering_block(groups)

    @pytest.mark.parametrize(
        ("count", "expected"),
        [(39, "is also under the 40"), (40, "is exactly the 40"), (41, "is over the 40")],
    )
    def test_old_cursor_note_matches_the_count(self, count, expected):
        assert expected in gen_tool_docs._old_cursor_note(count)

    def test_all_may_exceed_the_client_limit(self):
        groups = _groups_by_name()
        assert len(groups) >= gen_tool_docs.CLIENT_TOOL_LIMIT
        gen_tool_docs.render_filtering_block(groups)  # should not raise


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
