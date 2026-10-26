"""Tests for scripts/kai_status.py (#1195).

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import (same pattern as test_gen_tool_docs.py).
Only the pure classifiers are tested; the sections are thin `gh`/`git`/`uv`
wrappers around them.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

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


class TestPackageStatus:
    def test_unpatched_alert_does_not_hide_a_fix_for_the_others(self):
        """PR #1196 QA round 1: one alert with no patched version used to turn
        the whole package into "no fix", hiding a PR that closes the rest."""
        status = kai_status.package_status(["2.0", None, "1.5"], ["1.0"], [(7, "2.0")])
        assert status == (
            "open Dependabot PR #7 (-> 2.0); covers 2 of 3 alerts, 1 with no patched version"
        )

    def test_all_unpatched(self):
        assert kai_status.package_status([None, None], ["1.0"], []).startswith("no fix (no patched")

    def test_invalid_fix_version_is_treated_as_unpatched(self):
        """`max(fixes, key=Version)` used to raise InvalidVersion here."""
        status = kai_status.package_status(["not-a-version", "1.2"], ["1.2"], [])
        assert status.startswith("fixed on develop") and "1 with no patched version" in status


class TestCanonicalNames:
    def test_title_and_lock_names_meet_under_pep_503(self):
        """uv.lock stores normalized names; an alert or title spelling one with
        `_` or `.` must still match it."""
        assert kai_status.dependabot_pr_target("bump Typing_Extensions from 4.0 to 4.1") == (
            "typing-extensions",
            "4.1",
        )
        lock = '[[package]]\nname = "zope.interface"\nversion = "7.0"\n'
        assert kai_status.locked_versions(lock) == {"zope-interface": ["7.0"]}


class TestSoloOnlyConflict:
    def _issue(self, *labels):
        return {"labels": [{"name": lb} for lb in ("ready-for-development", *labels)]}

    def test_solo_only_alone_is_the_correct_state(self):
        assert not kai_status.solo_only_conflict([self._issue("solo-only")])

    def test_solo_only_alongside_another_ticket(self):
        assert kai_status.solo_only_conflict([self._issue("solo-only"), self._issue("lane-a")])

    def test_no_solo_only(self):
        assert not kai_status.solo_only_conflict([self._issue(), self._issue()])


class TestLaneState:
    """A `parked` PR doesn't hold its lane (#1250)."""

    def _pr(self, branch, *labels):
        return {"headRefName": branch, "labels": [{"name": lb} for lb in labels]}

    def test_idle_slot_no_pr(self):
        assert kai_status.lane_state("jay", "team/jay", []) == "free"

    def test_open_pr_holds_the_lane(self):
        pr = self._pr("fix/jay/issue-1116")
        assert kai_status.lane_state("jay", "team/jay", [pr]) == "busy"

    def test_parked_pr_with_slot_moved(self):
        pr = self._pr("fix/jay/issue-1116", "parked")
        assert kai_status.lane_state("jay", "team/jay", [pr]) == "free"

    def test_parked_pr_with_slot_still_on_its_branch(self):
        pr = self._pr("fix/jay/issue-1116", "parked")
        assert kai_status.lane_state("jay", "fix/jay/issue-1116", [pr]) == "free"

    def test_parked_pr_plus_an_active_one(self):
        prs = [self._pr("fix/jay/issue-1116", "parked"), self._pr("fix/jay/issue-1036")]
        assert kai_status.lane_state("jay", "fix/jay/issue-1036", prs) == "busy"

    def test_ticket_branch_before_its_pr_opens(self):
        pr = self._pr("fix/jay/issue-1116", "parked")
        assert kai_status.lane_state("jay", "feat/jay/issue-1036", [pr]) == "busy"

    def test_unknown_slot_is_busy(self):
        assert kai_status.lane_state("jay", None, []) == "busy"


class TestParseWorktrees:
    MAIN = Path("/repo")

    def test_keys_slots_by_name_and_others_by_path(self):
        porcelain = (
            "worktree /repo\nHEAD a\nbranch refs/heads/develop\n\n"
            "worktree /repo/.claude/worktrees/ash\nHEAD b\nbranch refs/heads/team/ash\n\n"
            "worktree /elsewhere/jay\nHEAD c\nbranch refs/heads/scratch\n"
        )
        assert kai_status.parse_worktrees(porcelain, self.MAIN) == {
            "ash": "team/ash",
            "/elsewhere/jay": "scratch",
        }

    def test_detached_follows_the_same_keying(self):
        """PR #1196 QA round 1: a detached worktree was keyed by directory name
        unconditionally, so a detached main checkout listed as a slot and a
        detached `.../ash` elsewhere overwrote lane A's entry."""
        porcelain = (
            "worktree /repo\nHEAD a\ndetached\n\n"
            "worktree /repo/.claude/worktrees/ash\nHEAD b\nbranch refs/heads/team/ash\n\n"
            "worktree /tmp/ash\nHEAD c\ndetached\n"
        )
        assert kai_status.parse_worktrees(porcelain, self.MAIN) == {
            "ash": "team/ash",
            "/tmp/ash": "(detached)",
        }


class TestRunAndMain:
    def test_missing_executable_is_a_command_error(self):
        """PR #1196 QA round 1: with `gh` off PATH, FileNotFoundError escaped
        and the script died after the Worktrees section."""
        with pytest.raises(kai_status.CommandError, match="could not run"):
            kai_status.run(["definitely-not-a-real-command-1195"])

    def test_empty_gh_output_is_an_empty_list(self, monkeypatch):
        monkeypatch.setattr(kai_status, "run", lambda cmd, cwd=None: "")
        assert kai_status.gh_json(["pr", "list"]) == []

    def test_every_section_runs_when_one_raises_unexpectedly(self, monkeypatch, capsys):
        def boom(*a, **k):
            raise ValueError("unexpected")

        monkeypatch.setattr(kai_status, "section_checkout", boom)
        monkeypatch.setattr(kai_status, "section_worktrees", lambda: (["wt"], {}))
        monkeypatch.setattr(kai_status, "gh_json", lambda args: [])
        monkeypatch.setattr(kai_status, "section_dependabot", lambda prs: ["dep"])
        assert kai_status.main(["--no-fetch"]) == 1
        out = capsys.readouterr().out
        assert "ERROR: ValueError: unexpected" in out
        assert "== Dependabot alerts ==\n  dep" in out
