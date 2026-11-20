"""Tests for scripts/kai_status.py (#1195).

The script lives outside the mcp_gee_sweet package, so it's loaded here via
importlib rather than a normal import (same pattern as test_gen_tool_docs.py).
Mostly the pure classifiers are tested; most sections are thin `gh`/`git`/`uv`
wrappers around them. Sections that take their fetch as a parameter
(Community intake, Sessions) are tested with a stub in its place.
"""

import importlib.util
import json
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

    def test_retro_pr_does_not_hold_the_lane(self):
        pr = self._pr("doc/jay/retro-2026-10-25")
        assert kai_status.lane_state("jay", "team/jay", [pr]) == "free"

    def test_retro_pr_beside_a_parked_ticket(self):
        prs = [self._pr("fix/jay/issue-1116", "parked"), self._pr("doc/jay/retro-2026-10-25")]
        assert kai_status.lane_state("jay", "team/jay", prs) == "free"

    def test_ticket_branch_shape(self):
        assert kai_status.is_ticket_branch("fix/jay/issue-1116", "jay")
        assert kai_status.is_ticket_branch("docs/jay/issue-590", "jay")
        assert not kai_status.is_ticket_branch("doc/jay/retro-2026-10-25", "jay")
        assert not kai_status.is_ticket_branch("fix/ash/issue-1116", "jay")
        assert not kai_status.is_ticket_branch("fix/jay/issue-1116-followup", "jay")


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
        monkeypatch.setattr(kai_status, "section_sessions", lambda prs, now: ["sessions"])
        assert kai_status.main(["--no-fetch"]) == 1
        out = capsys.readouterr().out
        assert "ERROR: ValueError: unexpected" in out
        assert "== Dependabot alerts ==\n  dep" in out


LABELED_AT = "2026-10-24T00:00:00Z"
NOW = datetime(2026, 11, 12, tzinfo=UTC)


def _labeled(at=LABELED_AT, name="awaiting-contributor"):
    return {"event": "labeled", "created_at": at, "label": {"name": name}}


def _activity(
    timeline=(), reviews=(), review_comments=(), head_pushed_at: str | None = "2026-10-21T00:00:00Z"
):
    return {
        "timeline": [_labeled(), *timeline],
        "reviews": list(reviews),
        "review_comments": list(review_comments),
        "head_pushed_at": head_pushed_at,
    }


class TestWaitingDays:
    """kai.md "Stalled community PRs" (#1454): the wait starts at the latest
    `awaiting-contributor` label and ends at a push or an author reply."""

    def test_no_activity_since_the_label(self):
        activity = _activity(
            timeline=[
                {
                    "event": "commented",
                    "created_at": "2026-10-21T00:00:00Z",
                    "actor": {"login": "c"},
                },
                {"event": "cross-referenced", "created_at": "2026-11-06T00:00:00Z"},
            ]
        )
        assert kai_status.waiting_days(activity, "c", NOW) == 19

    @pytest.mark.parametrize(
        "where, reply",
        [
            (
                "timeline",
                {
                    "event": "commented",
                    "created_at": "2026-10-30T00:00:00Z",
                    "actor": {"login": "c"},
                },
            ),
            (
                "timeline",
                {
                    "event": "reviewed",
                    "submitted_at": "2026-10-30T00:00:00Z",
                    "user": {"login": "c"},
                },
            ),
            ("reviews", {"submitted_at": "2026-10-30T00:00:00Z", "user": {"login": "c"}}),
            # PR #1455 QA round 1: a review-thread reply is in neither the
            # timeline nor the reviews list (checked live on #631).
            ("review_comments", {"created_at": "2026-10-30T00:00:00Z", "user": {"login": "c"}}),
        ],
    )
    def test_an_author_reply_anywhere_ends_the_wait(self, where, reply):
        activity = _activity(**{where: [reply]})
        assert kai_status.waiting_days(activity, "c", NOW) is None

    def test_a_maintainer_reply_does_not_end_it(self):
        reply = {"created_at": "2026-11-01T00:00:00Z", "user": {"login": "m"}}
        activity = _activity(review_comments=[reply])
        assert kai_status.waiting_days(activity, "c", NOW) == 19

    def test_a_commit_made_before_the_label_but_pushed_after_ends_it(self):
        """PR #1455 QA round 1: the committer date is when it was committed,
        not pushed, so the head's first check suite times the push."""
        commit = {"event": "committed", "committer": {"date": "2026-10-20T00:00:00Z"}}
        activity = _activity(timeline=[commit], head_pushed_at="2026-10-30T00:00:00Z")
        assert kai_status.waiting_days(activity, "c", NOW) is None

    def test_head_pushed_before_the_label_keeps_it_waiting(self):
        commit = {"event": "committed", "committer": {"date": "2026-10-30T00:00:00Z"}}
        activity = _activity(timeline=[commit], head_pushed_at="2026-10-21T00:00:00Z")
        assert kai_status.waiting_days(activity, "c", NOW) == 19

    def test_without_a_check_suite_the_committer_date_is_used(self):
        commit = {"event": "committed", "committer": {"date": "2026-10-30T00:00:00Z"}}
        activity = _activity(timeline=[commit], head_pushed_at=None)
        assert kai_status.waiting_days(activity, "c", NOW) is None

    def test_a_force_push_ends_it(self):
        force = {"event": "head_ref_force_pushed", "created_at": "2026-10-30T00:00:00Z"}
        assert kai_status.waiting_days(_activity(timeline=[force]), "c", NOW) is None

    def test_the_latest_label_starts_the_wait(self):
        activity = _activity(timeline=[_labeled("2026-10-01T00:00:00Z")])
        assert kai_status.waiting_days(activity, "c", NOW) == 19

    def test_never_labeled(self):
        activity = _activity()
        activity["timeline"] = [_labeled(name="review-ready")]
        assert kai_status.waiting_days(activity, "c", NOW) is None


class TestSectionCommunityStalled:
    @staticmethod
    def pr(number, labels=("community", "awaiting-contributor"), can_modify=True):
        return {
            "number": number,
            "title": f"t{number}",
            "headRefOid": f"sha{number}",
            "author": {"login": "c", "is_bot": False},
            "labels": [{"name": n} for n in labels],
            "maintainerCanModify": can_modify,
        }

    def test_reports_only_prs_past_the_threshold(self):
        started = {
            "sha1": LABELED_AT,
            "sha2": "2026-10-30T00:00:00Z",
            "sha3": "2026-10-29T00:00:00Z",
        }

        def fetch(number, head_sha):
            activity = _activity()
            activity["timeline"] = [_labeled(started[head_sha])]
            return activity

        prs = [self.pr(1), self.pr(2), self.pr(3, can_modify=False)]
        assert kai_status.section_community(prs, [], NOW, fetch) == [
            "stalled: PR #1 [c] 19d awaiting-contributor, maintainer edits allowed  t1",
            "stalled: PR #3 [c] 14d awaiting-contributor, no maintainer edits  t3",
        ]

    def test_activity_fetched_only_for_awaiting_prs(self):
        def fetch(number, head_sha):
            raise AssertionError("fetched")

        pr = self.pr(1, labels=("community", "review-ready"))
        assert kai_status.section_community([pr], [], NOW, fetch) == ["nothing to do"]

    def test_a_failed_fetch_costs_only_that_pr(self):
        """PR #1455 QA round 1: one error used to take the whole section."""

        def fetch(number, head_sha):
            if number == 1:
                raise kai_status.CommandError("rate limited")
            return _activity()

        needs_intake = self.pr(3, labels=())
        lines = kai_status.section_community([self.pr(1), self.pr(2), needs_intake], [], NOW, fetch)
        assert lines == [
            "stall check failed: PR #1: CommandError: rate limited",
            "stalled: PR #2 [c] 19d awaiting-contributor, maintainer edits allowed  t2",
            "needs intake: PR #3 [c] t3",
        ]


SESSION_NOW = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)


def _status(**overrides):
    status = {
        "name": "Rio",
        "updated": "2026-11-20T05:40Z",
        "state": "working",
        "pr": None,
        "issue": None,
        "round": None,
        "doing": "resolving the develop conflict",
        "waiting_on": None,
    }
    status.update(overrides)
    return status


def _team_pr(number, login="khuisman", labels=(), is_bot=False):
    return {
        "number": number,
        "headRefName": f"fix/ash/issue-{number}",
        "author": {"login": login, "is_bot": is_bot},
        "labels": [{"name": n} for n in labels],
    }


def _verdict(at, verdict="approved", name="Rio", rnd=2):
    body = f"## QA round {rnd} ({name}) @ abc1234: {verdict}\n\nResults.\n\n— {name}"
    return {"createdAt": at, "body": body}


def _view(state="OPEN", comments=(), reviews=()):
    return {"state": state, "comments": list(comments), "reviews": list(reviews)}


class TestSectionSessions:
    """kai_status.py's Sessions section (#1557)."""

    @staticmethod
    def write(root, slot, content):
        base = root if slot is None else root / ".claude" / "worktrees" / slot
        path = base / ".workspace" / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    @staticmethod
    def no_fetch(number):
        raise AssertionError(f"fetched PR #{number}")

    def section(self, root, prs=(), fetch=None):
        return kai_status.section_sessions(
            list(prs), SESSION_NOW, root=root, fetch=fetch or self.no_fetch
        )

    @staticmethod
    def flags(lines):
        # A FLAG opens the line, or follows the slot column (a malformed file),
        # never inside a status's own printed text.
        return [
            ln for ln in lines if ln.lstrip().startswith("FLAG:") or ln[15:].startswith("FLAG:")
        ]

    def test_fresh_working_entry_does_not_flag(self, tmp_path):
        self.write(tmp_path, "rio", _status())
        assert self.section(tmp_path) == [
            "main checkout  no status published",
            "rio            Rio: working; holds nothing; updated 20m ago; "
            "doing: resolving the develop conflict",
        ]

    def test_held_items_and_waiting_on_are_shown(self, tmp_path):
        self.write(
            tmp_path,
            None,
            _status(name="Kai", state="waiting-user", issue=1557, waiting_on="the user's yes"),
        )
        assert self.section(tmp_path) == [
            "main checkout  Kai: waiting-user; issue #1557; updated 20m ago; "
            "doing: resolving the develop conflict; waiting on: the user's yes"
        ]

    def test_missing_file_is_no_status_never_idle(self, tmp_path):
        (tmp_path / ".claude" / "worktrees" / "ash").mkdir(parents=True)
        lines = self.section(tmp_path)
        assert "ash            no status published" in lines
        assert not any("idle" in ln for ln in lines)
        assert self.flags(lines) == []

    def test_stale_working_entry_flags(self, tmp_path):
        self.write(tmp_path, "rio", _status(updated="2026-11-20T03:30Z"))
        assert self.flags(self.section(tmp_path)) == [
            "      FLAG: still working after 2h30m with no update (threshold 2h00m); "
            "the session may have stopped"
        ]

    def test_stale_threshold_applies_only_to_working(self, tmp_path):
        self.write(tmp_path, "rio", _status(updated="2026-11-19T03:30Z", state="idle"))
        self.write(tmp_path, "ash", _status(updated="2026-11-19T03:30Z", state="waiting-user"))
        assert self.flags(self.section(tmp_path)) == []

    @pytest.mark.parametrize(
        "content, problem",
        [
            ("{not json", "not valid JSON"),
            ("[1, 2]", "not a JSON object"),
            (json.dumps({"name": "Rio"}), "missing field(s): updated, state, pr"),
            (json.dumps(_status(state="busy")), "state is not one of"),
            (json.dumps(_status(updated="20 minutes ago")), "updated is not YYYY-MM-DDTHH:MMZ"),
            (json.dumps(_status(updated="2026-13-40T05:40Z")), "updated is not a real UTC time"),
            (json.dumps(_status(pr="1556")), "pr is not a positive integer or null"),
            (json.dumps(_status(pr=True)), "pr is not a positive integer or null"),
            (json.dumps(_status(doing=None)), "doing is not a non-empty string"),
        ],
    )
    def test_malformed_file_flags_without_crashing(self, tmp_path, content, problem):
        self.write(tmp_path, "rio", content)
        self.write(tmp_path, "ash", _status(name="Ash"))
        lines = self.section(tmp_path)
        (bad,) = [ln for ln in lines if ln.startswith("rio")]
        assert bad.startswith("rio            FLAG: malformed status file: ")
        assert problem in bad
        assert any(ln.startswith("ash            Ash: working") for ln in lines)

    def test_oversized_file_is_not_parsed(self, tmp_path):
        self.write(tmp_path, "rio", " " * (kai_status.STATUS_MAX_BYTES + 1))
        assert "larger than" in self.section(tmp_path)[1]

    def test_untrusted_text_is_printed_on_one_clean_line(self, tmp_path):
        doing = "line one\nFLAG: forged\x1b[31m red" + "x" * 500
        self.write(tmp_path, None, _status(name="Kai", doing=doing))
        lines = self.section(tmp_path)
        assert len(lines) == 1
        assert "\n" not in lines[0] and "\x1b" not in lines[0]
        assert "doing: line one FLAG: forged?[31m red" in lines[0]
        assert lines[0].endswith("...")
        assert self.flags(lines) == []

    def test_waiting_agent_after_a_newer_verdict_flags(self, tmp_path):
        self.write(tmp_path, "ash", _status(name="Ash", state="waiting-agent", pr=1556))
        view = _view(
            comments=[
                _verdict("2026-11-20T04:00:00Z", "sent back", rnd=1),
                {"createdAt": "2026-11-20T05:58:00Z", "body": "unrelated comment"},
                _verdict("2026-11-20T05:50:12Z"),
            ]
        )
        lines = self.section(tmp_path, [_team_pr(1556)], fetch=lambda n: view)
        assert self.flags(lines) == [
            "      FLAG: waiting-agent on PR #1556, but a QA verdict was posted after this "
            "status (2026-11-20T05:50Z): ## QA round 2 (Rio) @ abc1234: approved"
        ]

    def test_older_verdict_does_not_flag(self, tmp_path):
        self.write(tmp_path, "ash", _status(name="Ash", state="waiting-agent", pr=1556))
        view = _view(comments=[_verdict("2026-11-20T05:00:00Z", "sent back")])
        assert self.flags(self.section(tmp_path, [_team_pr(1556)], fetch=lambda n: view)) == []

    def test_verdict_in_the_status_minute_does_not_flag(self, tmp_path):
        """A QA session writes `updated` in the same minute it posts its
        verdict; the minute-precision timestamp can't order them."""
        self.write(tmp_path, "rio", _status(state="waiting-agent", pr=1556, round=2))
        view = _view(comments=[_verdict("2026-11-20T05:40:45Z")])
        assert self.flags(self.section(tmp_path, [_team_pr(1556)], fetch=lambda n: view)) == []

    def test_verdict_as_a_review_counts(self, tmp_path):
        self.write(tmp_path, "ash", _status(name="Ash", state="waiting-agent", pr=7))
        review = {"submittedAt": "2026-11-20T05:45:00Z", "body": _verdict("x")["body"]}
        view = _view(reviews=[review])
        flags = self.flags(self.section(tmp_path, [_team_pr(7)], fetch=lambda n: view))
        assert len(flags) == 1 and "waiting-agent on PR #7" in flags[0]

    @pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
    def test_claimed_pr_that_is_no_longer_open_flags(self, tmp_path, state):
        self.write(tmp_path, "rio", _status(pr=1500))
        assert self.flags(self.section(tmp_path, fetch=lambda n: _view(state))) == [
            f"      FLAG: claims PR #1500, which is {state.lower()}"
        ]

    def test_unclaimed_team_pr_flags_but_community_and_bot_prs_do_not(self, tmp_path):
        self.write(tmp_path, "rio", _status(pr=1))
        prs = [
            _team_pr(1),
            _team_pr(2),
            _team_pr(3, login="kh-kev", labels=("community",)),
            _team_pr(4, login="someone"),
            _team_pr(5, login="app/dependabot", is_bot=True),
        ]
        assert self.flags(self.section(tmp_path, prs, fetch=lambda n: _view())) == [
            "FLAG: open PR #2 (fix/ash/issue-2) is claimed by no status file"
        ]

    def test_a_malformed_file_claims_nothing(self, tmp_path):
        self.write(tmp_path, "rio", json.dumps({"pr": 1}))
        flags = self.flags(self.section(tmp_path, [_team_pr(1)]))
        assert flags[-1] == "FLAG: open PR #1 (fix/ash/issue-1) is claimed by no status file"

    def test_a_failed_pr_fetch_costs_only_that_entry(self, tmp_path):
        self.write(tmp_path, "ash", _status(name="Ash", pr=1))
        self.write(tmp_path, "rio", _status(pr=2, updated="2026-11-20T01:00Z"))

        def fetch(number):
            if number == 1:
                raise kai_status.CommandError("rate limited")
            return _view()

        lines = self.section(tmp_path, [_team_pr(1), _team_pr(2)], fetch=fetch)
        assert "      PR check failed: #1: CommandError: rate limited" in lines
        assert any("still working after 5h00m" in ln for ln in lines)

    def test_each_claimed_pr_is_fetched_once(self, tmp_path):
        self.write(tmp_path, "ash", _status(name="Ash", pr=1))
        self.write(tmp_path, "rio", _status(pr=1))
        calls = []

        def fetch(number):
            calls.append(number)
            return _view()

        self.section(tmp_path, [_team_pr(1)], fetch=fetch)
        assert calls == [1]
