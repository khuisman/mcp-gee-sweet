"""Tests for tools/response_limits.py — shared response-size safety net (issue #242)."""

import ast
import importlib
import json
import os
import re
from pathlib import Path

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
        with pytest.raises(ValueError, match="Lower max_results"):
            response_limits.enforce_response_size_cap(
                {"a": "bb"}, tool_name="some_tool", hint="Lower max_results and paginate. "
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

    def test_local_path_unavailable_starts_a_new_sentence(self, monkeypatch):
        """#1430: with local_path unavailable the env-var clause is its own
        sentence, so it must not start lowercase after the period."""
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_cap(
                {"a": "bb"}, tool_name="some_tool", local_path_available=False
            )
        assert "safety cap. Set MAX_TOOL_RESPONSE_CHARS" in str(exc_info.value)

    def test_full_sentence_hint_with_local_path_starts_a_new_sentence(self, monkeypatch):
        """#1430: a hint is a complete sentence, so the text after it starts a
        fresh sentence — 'Pass local_path' is never spliced onto a trailing
        'or ' (the get_sheet_data case)."""
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_cap(
                {"a": "bb"},
                tool_name="some_tool",
                hint="Narrow the range. ",
            )
        assert "Narrow the range. Pass local_path to write the result" in str(exc_info.value)

    def test_full_sentence_hint_without_local_path_reads_as_one_message(self, monkeypatch):
        """#1430: the list_messages/list_file_activity/list_doc_comments form —
        hint sentence, then the env-var sentence, capitalized."""
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        with pytest.raises(ValueError) as exc_info:
            response_limits.enforce_response_size_cap(
                {"a": "bb"},
                tool_name="some_tool",
                hint="Lower max_results and paginate via next_page_token. ",
                local_path_available=False,
            )
        assert "next_page_token. Set MAX_TOOL_RESPONSE_CHARS" in str(exc_info.value)

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


_ENFORCE_CALL_NAMES = ("enforce_response_size_cap", "enforce_response_size_floor")


def _call_name(func: ast.expr) -> str | None:
    """The plain function name of a call target: `enforce_response_size_cap(...)`
    or `response_limits.enforce_response_size_cap(...)` both resolve to the name."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _resolve_hint_expr(
    node: ast.expr,
    scope: dict[str, list[ast.expr]],
    where: str,
    resolving: frozenset[str] = frozenset(),
) -> set[str]:
    """Every string `node` can evaluate to as a hint, or AssertionError.

    Concatenated strings and f-strings fold whole (#1552: the old collector
    collected their pieces as whole hints). A hint that can't be resolved
    statically — a computed variable, a dynamic f-string field — fails loudly
    naming the call site, instead of being skipped.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return {node.value}
        raise AssertionError(f"{where}: hint is the non-string constant {node.value!r}")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_hint_expr(node.left, scope, where, resolving)
        right = _resolve_hint_expr(node.right, scope, where, resolving)
        return {a + b for a in left for b in right}
    if isinstance(node, ast.JoinedStr):
        combos = {""}
        for value in node.values:
            combos = {
                c + p for c in combos for p in _resolve_hint_expr(value, scope, where, resolving)
            }
        return combos
    if isinstance(node, ast.FormattedValue):
        # str()-approximation of the format spec/conversion; hints interpolate
        # plain values, and an unresolvable field still fails loudly below.
        return {str(v) for v in _resolve_hint_expr(node.value, scope, where, resolving)}
    if isinstance(node, ast.IfExp):
        return _resolve_hint_expr(node.body, scope, where, resolving) | _resolve_hint_expr(
            node.orelse, scope, where, resolving
        )
    if isinstance(node, ast.Name):
        if node.id in resolving:
            raise AssertionError(f"{where}: hint {node.id!r} is self-referential")
        assigned = scope.get(node.id)
        if not assigned:
            raise AssertionError(
                f"{where}: hint reads {node.id!r}, which no assignment in this "
                "function's scope defines"
            )
        values: set[str] = set()
        for value in assigned:
            values |= _resolve_hint_expr(value, scope, where, resolving | {node.id})
        return values
    if isinstance(node, ast.Call) and _call_name(node.func) == "pagination_hint":
        page_params: set[str] = set()
        if len(node.args) == 1:
            page_params |= _resolve_hint_expr(node.args[0], scope, where, resolving)
        for kw in node.keywords:
            if kw.arg == "page_param":
                page_params |= _resolve_hint_expr(kw.value, scope, where, resolving)
        if not page_params:
            raise AssertionError(
                f"{where}: pagination_hint() call with no statically resolvable page_param"
            )
        return {response_limits.pagination_hint(page) for page in page_params}
    raise AssertionError(
        f"{where}: hint expression of type {type(node).__name__} can't be resolved statically"
    )


def _iter_own_stmts(stmts: list[ast.stmt]):
    """Every statement in these statements, compound bodies included, but not
    the bodies of functions defined among them — those get their own scope."""
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, field, None)
            if isinstance(sub, list):
                yield from _iter_own_stmts(sub)
        if isinstance(stmt, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            for handler in stmt.handlers:
                yield from _iter_own_stmts(handler.body)


def _collect_scope_hints(
    body: list[ast.stmt],
    scope: dict[str, list[ast.expr]],
    filename: str,
    hints: set[str],
) -> None:
    """Collect this scope's hint values, then recurse into its functions.

    Assignments are recorded for the whole scope before any call in it is
    resolved, so a `hint = ...` beside the call resolves regardless of
    statement order. Each function defined here is visited with its own scope
    (a copy of this one), so two tools that each build a local `hint` don't
    merge (#1552)."""
    own = list(_iter_own_stmts(body))
    for stmt in own:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    scope.setdefault(target.id, []).append(stmt.value)
    for stmt in own:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and _call_name(node.func) in _ENFORCE_CALL_NAMES:
                where = f"{filename}:{node.lineno}"
                for kw in node.keywords:
                    if kw.arg == "hint":
                        hints |= _resolve_hint_expr(kw.value, scope, where)
    for stmt in own:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect_scope_hints(stmt.body, dict(scope), filename, hints)


def _collect_cap_hints(src: Path | None = None) -> list[str]:
    """Every hint string reachable from a size-cap call site in src/ (#1465):
    constant `hint=` arguments, the string values of local `hint = ...`
    assignments those calls read by name (gmail builds its get_message/
    get_thread/get_draft hints conditionally; sync_folder builds its hint
    from the call's own arguments), and `pagination_hint(...)` calls with
    constant arguments — positional or `page_param=` by keyword (#1552).
    Both direct calls and `response_limits.enforce_*` attribute calls count.
    Concatenated and f-string hints fold whole; any hint that can't be
    resolved statically fails loudly naming the call site. Call sites with no
    hint (the empty default) contribute nothing."""
    if src is None:
        src = Path(__file__).resolve().parents[1] / "src" / "mcp_gee_sweet"
    hints: set[str] = set()
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _collect_scope_hints(tree.body, {}, path.name, hints)
    return sorted(hints)


class TestCapHintsAreCompleteSentences:
    """#1465: nothing enforced #1430's full-sentence hint form — two callers
    shipped old ", or " fragments before anyone noticed. These pin the form for
    every hint in src/, so a new call site can't quietly reintroduce one."""

    def test_collects_the_known_call_sites(self):
        hints = _collect_cap_hints()
        assert len(hints) >= 9, hints
        assert all(hints), hints
        assert "Lower max_results and paginate via next_page_token. " in hints
        assert "Lower page_size and paginate via next_page_token. " in hints
        assert "The message body is large. " in hints
        # #1552: sync_folder's hint is built from the call's own arguments —
        # every reachable variant lands here as its own complete sentence.
        assert (
            "Recursive syncs can produce very large result lists. Sync a "
            "narrower subfolder, a single direction, or set recursive=False. " in hints
        )
        assert (
            "Recursive syncs can produce very large result lists. Sync a "
            "narrower subfolder or set recursive=False. " in hints
        )
        assert (
            "A folder's direct children can still produce a very large result "
            "list. Sync a narrower subfolder or a single direction. " in hints
        )
        assert (
            "A folder's direct children can still produce a very large result "
            "list. Sync a narrower subfolder. " in hints
        )

    def test_every_hint_ends_a_complete_sentence(self):
        for hint in _collect_cap_hints():
            assert hint.endswith(". "), repr(hint)

    def test_no_composed_message_splices_sentences(self, monkeypatch):
        # The composed message must never contain ", or " followed by a capital
        # letter — the shape the old fragments read as ("…overhead, or Set
        # MAX_TOOL_RESPONSE_CHARS…").
        for hint in _collect_cap_hints():
            for usable in (True, False):

                def _usable(value: bool = usable) -> bool:
                    return value

                monkeypatch.setattr(response_limits.local_files, "local_paths_usable", _usable)
                message = str(
                    response_limits._over_cap_error(
                        "the response is 2 characters",
                        tool_name="some_tool",
                        hint=hint,
                        local_path_available=True,
                        local_path_param="local_path",
                    )
                )
                assert not re.search(r", or [A-Z]", message), message


class TestCollectCapHints:
    """#1552: the collector itself — attribute call sites, keyword pagination
    hints, whole-string folding, per-function scoping and loud failure."""

    def _pkg(self, tmp_path, text):
        src = tmp_path / "pkg"
        src.mkdir(exist_ok=True)
        (src / "a.py").write_text(text, encoding="utf-8")
        return src

    def test_attribute_call_sites_are_collected(self, tmp_path):
        # response_limits.enforce_response_size_cap(...) — an Attribute call
        # target the old collector walked past entirely.
        src = self._pkg(
            tmp_path,
            "def one(x):\n"
            "    response_limits.enforce_response_size_cap(\n"
            '        x, tool_name="t", hint="A full sentence. "\n'
            "    )\n",
        )
        assert _collect_cap_hints(src) == ["A full sentence. "]

    def test_pagination_hint_by_keyword_resolves(self, tmp_path):
        # pagination_hint(page_param=...) crashed the old collector with a
        # TypeError (it read only positional args).
        src = self._pkg(
            tmp_path,
            "def one(x):\n"
            "    enforce_response_size_cap(\n"
            '        x, tool_name="t", hint=pagination_hint(page_param="page_size")\n'
            "    )\n",
        )
        assert _collect_cap_hints(src) == ["Lower page_size and paginate via next_page_token. "]

    def test_concatenated_and_f_string_hints_fold_whole(self, tmp_path):
        # The old collector collected the pieces of a concatenated or
        # f-string hint as whole hints; both fold to the full string now.
        src = self._pkg(
            tmp_path,
            "def one(x):\n"
            '    hint = "Sync a " + "narrower subfolder. "\n'
            '    enforce_response_size_cap(x, tool_name="t", hint=hint)\n'
            "\n"
            "def two():\n"
            '    page = "max_results"\n'
            "    enforce_response_size_cap(\n"
            '        x, tool_name="t", hint=f"Lower {page} and paginate. "\n'
            "    )\n",
        )
        assert _collect_cap_hints(src) == [
            "Lower max_results and paginate. ",
            "Sync a narrower subfolder. ",
        ]

    def test_assignments_do_not_merge_across_functions(self, tmp_path):
        # The old collector kept one assignment map per file, so a `hint`
        # built in a second tool leaked into the first tool's call.
        src = self._pkg(
            tmp_path,
            "def one(x):\n"
            '    hint = "One sentence. "\n'
            '    enforce_response_size_cap(x, tool_name="t", hint=hint)\n'
            "\n"
            "def two(x):\n"
            '    hint = "fragment without a period"\n'
            "    other(x, hint)\n",
        )
        assert _collect_cap_hints(src) == ["One sentence. "]

    def test_unresolvable_hint_fails_loudly(self, tmp_path):
        src = self._pkg(
            tmp_path,
            'def one(p):\n    enforce_response_size_cap(x, tool_name="t", hint=build_hint(p))\n',
        )
        with pytest.raises(AssertionError, match="can't be resolved statically"):
            _collect_cap_hints(src)

    def test_dynamic_f_string_field_fails_loudly(self, tmp_path):
        src = self._pkg(
            tmp_path,
            "def one(p):\n"
            "    enforce_response_size_cap(\n"
            '        x, tool_name="t", hint=f"Lower {p} and paginate. "\n'
            "    )\n",
        )
        with pytest.raises(AssertionError, match="no assignment in this"):
            _collect_cap_hints(src)


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

    async def test_default_filename_with_separators_stays_inside_the_directory(self, tmp_path):
        """PR #1000 QA round 2: a sheet named '../x' wrote x_data.json beside the
        chosen directory, and 'a/b' created a subdirectory."""
        out = tmp_path / "out"
        for name, expected in (
            ("../x_data.json", ".._x_data.json"),
            ("a/b_data.json", "a_b_data.json"),
        ):
            result = await response_limits.write_capped_result_to_disk(
                {"a": 1}, f"{out}/", default_filename=name, manifest_extra={}
            )
            assert result["local_path"] == str(out / expected)
        assert sorted(p.name for p in out.iterdir()) == [".._x_data.json", "a_b_data.json"]
        assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]

    async def test_dangling_symlink_at_joined_filename_raises(self, tmp_path):
        """PR #1000 QA round 2: a dangling symlink at <dir>/<default_filename> was
        written through to its target; the same symlink as local_path is refused."""
        out = tmp_path / "out"
        out.mkdir()
        (out / "fallback.json").symlink_to(tmp_path / "elsewhere")
        with pytest.raises(ValueError, match="symlink to a missing target"):
            await response_limits.write_capped_result_to_disk(
                {"a": 1}, f"{out}/", default_filename="fallback.json", manifest_extra={}
            )
        assert not (tmp_path / "elsewhere").exists()

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
        with pytest.raises(ValueError, match=r"^result_local_path "):
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


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Sheet1_data.json", "Sheet1_data.json"),
            ("../x_data.json", ".._x_data.json"),
            ("a/b\\c_data.json", "a_b_c_data.json"),
            ("nul\x00_data.json", "nul__data.json"),
            (".", "_."),
            ("..", "_.."),
            (".gee-sweet-partial-0123456789abcdef", "_.gee-sweet-partial-0123456789abcdef"),
        ],
    )
    def test_reduces_to_one_ordinary_component(self, name, expected):
        assert response_limits._safe_filename(name) == expected
