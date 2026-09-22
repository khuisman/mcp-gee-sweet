"""Tests for scripts/check_supports_all_drives.py.

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import (same pattern as test_gen_tool_docs.py).
"""

import importlib.util
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_supports_all_drives.py"
_spec = importlib.util.spec_from_file_location("check_supports_all_drives", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
check_supports_all_drives = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_supports_all_drives)

find_violations_in_source = check_supports_all_drives.find_violations_in_source


class TestFindViolationsInSource:
    def test_flags_files_call_missing_kwarg(self):
        src = 'drive_service.files().get(fileId="x", fields="id").execute()'
        violations = find_violations_in_source(src)
        assert violations == [(1, "files", "get")]

    def test_flags_permissions_call_missing_kwarg(self):
        src = 'drive_service.permissions().create(fileId="x", body={}).execute()'
        violations = find_violations_in_source(src)
        assert violations == [(1, "permissions", "create")]

    def test_does_not_flag_when_kwarg_present(self):
        src = 'drive_service.files().get(fileId="x", fields="id", supportsAllDrives=True).execute()'
        assert find_violations_in_source(src) == []

    def test_does_not_flag_multiline_chained_call_with_kwarg(self):
        """Regression: this codebase's actual style chains the call across lines —
        a naive string/regex check could miss the kwarg depending on formatting;
        the AST-based check must not care about line breaks."""
        src = """
result = (
    drive_service.files()
    .get(
        fileId="x",
        fields="id",
        supportsAllDrives=True,
    )
    .execute()
)
"""
        assert find_violations_in_source(src) == []

    def test_does_not_flag_resource_without_the_param(self):
        """comments()/replies()/revisions()/drives()/about() don't accept
        supportsAllDrives at all (confirmed against the live Drive v3 discovery
        document) — a call on one of these must never be flagged."""
        src = 'drive_service.comments().list(fileId="x").execute()'
        assert find_violations_in_source(src) == []

    def test_does_not_flag_files_method_without_the_param(self):
        """files().export()/emptyTrash()/generateIds() etc. aren't in the
        checked method set — they don't accept supportsAllDrives either."""
        src = 'drive_service.files().export(fileId="x", mimeType="application/pdf").execute()'
        assert find_violations_in_source(src) == []

    def test_skips_kwargs_spread_rather_than_false_positive(self):
        """A **kwargs spread can't be statically verified either way — the
        checker must not guess and flag it."""
        src = "drive_service.files().list(**kwargs).execute()"
        assert find_violations_in_source(src) == []

    def test_works_regardless_of_receiver_variable_name(self):
        """The check is structural (matches .files()/.permissions() shape), not
        tied to a variable literally named drive_service."""
        src = 'some_other_service.files().delete(fileId="x").execute()'
        assert find_violations_in_source(src) == [(1, "files", "delete")]

    def test_ignores_unrelated_calls(self):
        src = 'sheets_service.spreadsheets().get(spreadsheetId="x").execute()'
        assert find_violations_in_source(src) == []


class TestRealCodebase:
    def test_no_violations_in_current_source_tree(self):
        """The real codebase's 58 existing call sites (issue #696) must all
        already carry supportsAllDrives — this is the regression guard the
        pre-commit hook enforces going forward."""
        src_root = Path(__file__).resolve().parent.parent / "src" / "mcp_gee_sweet"
        all_violations = []
        for path in sorted(src_root.rglob("*.py")):
            for lineno, resource, method in check_supports_all_drives.find_violations(path):
                all_violations.append((path.relative_to(src_root), lineno, resource, method))
        assert all_violations == []
