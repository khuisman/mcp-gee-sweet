"""Tests for scripts/kai_status.py (#1195).

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import (same pattern as test_gen_tool_docs.py).
Only the pure classifiers are tested; the sections are thin `gh`/`git`/`uv`
wrappers around them.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "kai_status.py"
_spec = importlib.util.spec_from_file_location("kai_status", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
kai_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kai_status)


class TestFixStatus:
    def test_fixed_on_develop_when_locked_at_highest_fix(self):
        """An alert stays open after its fix merges until Dependabot's next
        scan (#1155, #1182, 2026-10-23), so the lockfile decides, not the
        alert's state."""
        status = kai_status.fix_status("4.2.1", ["4.2.1"], [(1193, "4.2.1")])
        assert status.startswith("fixed on develop")

    def test_fixed_on_develop_when_locked_above_fix(self):
        assert kai_status.fix_status("21.14.10", ["21.14.13"], []).startswith("fixed on develop")

    def test_every_locked_version_must_clear_the_fix(self):
        """uv.lock can pin one package at two versions under different
        markers; the lower one is still vulnerable."""
        status = kai_status.fix_status("2.0", ["1.9", "2.1"], [])
        assert status.startswith("no fix")

    def test_open_pr_reaching_the_fix(self):
        status = kai_status.fix_status("21.14.13", ["21.14.9"], [(1192, "21.14.13")])
        assert status == "open Dependabot PR #1192 (-> 21.14.13)"

    def test_open_pr_short_of_highest_fix_does_not_count(self):
        status = kai_status.fix_status("21.14.13", ["21.14.9"], [(1190, "21.14.10")])
        assert status.startswith("no fix")

    def test_versions_compare_numerically_not_lexically(self):
        """'21.14.9' sorts after '21.14.13' as a string."""
        assert kai_status.fix_status("21.14.13", ["21.14.9"], []).startswith("no fix")

    def test_no_patched_version(self):
        assert kai_status.fix_status(None, ["1.0"], [(5, "9.9")]).startswith("no fix (no patched")

    def test_package_missing_from_lock(self):
        assert "not in uv.lock" in kai_status.fix_status("1.0", [], [])


class TestUserReach:
    def test_dev_only(self):
        tree = (
            "filelock v3.29.0\n"
            "├── python-discovery v1.6.1\n"
            "│   └── virtualenv v21.14.9\n"
            "│       └── pre-commit v4.6.2\n"
            "│           └── mcp-gee-sweet (group: dev)\n"
            "└── virtualenv v21.14.9 (*)\n"
        )
        assert kai_status.user_reach(tree) == "dev-only (group: dev)"

    def test_runtime_path_ships_even_if_a_dev_path_exists(self):
        tree = (
            "certifi v2026.1.1\n"
            "├── httplib2 v0.31.0\n"
            "│   └── mcp-gee-sweet\n"
            "└── requests v2.32.0\n"
            "    └── mkdocs v1.6.1\n"
            "        └── mcp-gee-sweet (group: dev)\n"
        )
        assert kai_status.user_reach(tree) == "ships to users"

    def test_direct_runtime_dependency_with_version_suffix(self):
        tree = "pillow v12.0.0\n└── mcp-gee-sweet v0.9.4\n"
        assert kai_status.user_reach(tree) == "ships to users"

    def test_extra(self):
        tree = "foo v1.0\n└── mcp-gee-sweet (extra: gmail)\n"
        assert kai_status.user_reach(tree) == "ships with extra(s): gmail"

    def test_not_reached(self):
        assert kai_status.user_reach("") == "not reached from this project"


class TestDependabotPrTarget:
    def test_single_package_bump(self):
        title = "chore(deps): bump filelock from 3.29.0 to 4.2.1"
        assert kai_status.dependabot_pr_target(title) == ("filelock", "4.2.1")

    def test_grouped_bump_names_no_package(self):
        title = "chore(deps): bump the pip group across 1 directory with 3 updates"
        assert kai_status.dependabot_pr_target(title) is None


class TestLockedVersions:
    def test_skips_editable_project_and_collects_split_pins(self):
        lock = (
            "version = 1\n"
            '[[package]]\nname = "mcp-gee-sweet"\nsource = { editable = "." }\n'
            '[[package]]\nname = "Foo"\nversion = "1.0"\n'
            '[[package]]\nname = "foo"\nversion = "2.0"\n'
        )
        assert kai_status.locked_versions(lock) == {"foo": ["1.0", "2.0"]}


class TestContributorsAndBranches:
    def test_maintainers_and_bots_are_not_outside(self):
        assert not kai_status.is_outside_contributor({"login": "kh-kev", "is_bot": False})
        assert not kai_status.is_outside_contributor({"login": "app/dependabot", "is_bot": True})
        assert kai_status.is_outside_contributor({"login": "someone", "is_bot": False})

    def test_branch_owner_ignores_type_prefix(self):
        assert kai_status.branch_owner("fix/ash/issue-1129") == "ash"
        assert kai_status.branch_owner("docs/amy/issue-590") == "amy"
        assert kai_status.branch_owner("team/ash") is None
        assert kai_status.branch_owner("fix/loose-list-item-bullets-1111") is None


class TestSummarizeChecks:
    def test_flags_absent_lint_and_test(self):
        """merge-pr.md step 2: a rollup with no failures can still mean the
        suite never ran."""
        rollup = [{"name": "CodeQL", "conclusion": "SUCCESS"}]
        assert kai_status.summarize_checks(rollup).endswith("Lint and test ABSENT")

    def test_counts_pending_and_success(self):
        rollup = [
            {"name": "Lint and test (Python 3.11)", "conclusion": "SUCCESS"},
            {"name": "Lint and test (Python 3.12)", "conclusion": "", "status": "IN_PROGRESS"},
        ]
        assert kai_status.summarize_checks(rollup) == "1 pending, 1 success"


def test_age_days():
    now = datetime(2026, 10, 24, 12, tzinfo=UTC)
    assert kai_status.age_days("2026-10-20T13:00:00Z", now) == 3
