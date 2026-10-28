#!/usr/bin/env python3
"""Print Kai's startup state report (`.claude/team-roles/kai.md` step 3, #1195).

Usage:
    uv run python scripts/kai_status.py [--no-fetch]

Gathers what kai.md step 3 used to have Kai rebuild by hand, one section per
query, and prints it. It only reads: no labels, comments, or branch changes.
The one exception is a `git fetch origin develop` (skipped with `--no-fetch`),
which moves only the remote-tracking ref, so the Dependabot section compares
against the real `origin/develop` rather than a stale copy.

The judgment calls stay in kai.md: community intake labeling, lane collisions,
which ticket to queue next, and every merge. This script just lays out the
state those rules act on. A section that fails for any reason prints
`ERROR:` and the report carries on, so one missing permission (e.g.
advisories) or missing tool doesn't hide the rest.

`gh` infers the repo from the git remote (and `gh api` fills `{owner}/{repo}`
from it), so the repo slug isn't hardcoded. The maintainer logins, lane map,
and project name below are this repo's own.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent

# Maintainer accounts. kai.md decides "outside contributor" by login, not by
# GitHub's authorAssociation, which reports kh-kev as NONE. Keep this in sync
# with kai.md's "Community intake" list.
MAINTAINERS = frozenset({"khuisman", "kh-kev"})

# Dev slot → its lane label. QA slots follow their Dev's lane.
LANE_OF_DEV = {"ash": "lane-a", "jay": "lane-b"}

PROJECT_NAME = "mcp-gee-sweet"


class CommandError(RuntimeError):
    pass


def run(cmd: list[str], cwd: Path = ROOT) -> str:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except OSError as e:  # e.g. `gh` not on PATH
        raise CommandError(f"`{cmd[0]}` could not run: {e}") from e
    if proc.returncode != 0:
        raise CommandError(
            f"`{' '.join(cmd)}` failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def gh_json(args: list[str]) -> list:
    out = run(["gh", *args])
    return json.loads(out) if out.strip() else []


# --- Pure classification (unit-tested) -------------------------------------


def is_outside_contributor(author: dict) -> bool:
    return not author.get("is_bot") and author.get("login") not in MAINTAINERS


def branch_owner(head_ref: str) -> str | None:
    """The slot name in `<type>/<name>/...`, or None for any other shape."""
    parts = head_ref.split("/")
    return parts[1] if len(parts) >= 3 else None


def is_ticket_branch(head_ref: str, dev: str) -> bool:
    """`<type>/<dev>/issue-<n>`, the shape dev.md names for a ticket branch."""
    return re.fullmatch(rf"[^/]+/{re.escape(dev)}/issue-\d+", head_ref) is not None


def parse_worktrees(porcelain: str, main: Path) -> dict[str, str]:
    """`git worktree list --porcelain` → {slot name or path: branch}.

    A worktree under `<main>/.claude/worktrees/` is keyed by its slot name; any
    other one by its full path, so a directory that happens to be named `ash`
    elsewhere can't stand in for that slot. The main checkout is left out:
    the checkout section covers it.
    """
    slots = main / ".claude" / "worktrees"
    out: dict[str, str] = {}
    path: Path | None = None
    for ln in porcelain.splitlines():
        if ln.startswith("worktree "):
            path = Path(ln.removeprefix("worktree "))
            continue
        if path is None or path == main:
            continue
        if ln.startswith("branch "):
            branch = ln.removeprefix("branch refs/heads/")
        elif ln == "detached":
            branch = "(detached)"
        else:
            continue
        out[path.name if path.parent == slots else str(path)] = branch
    return out


def _version(text: str | None) -> Version | None:
    if not text:
        return None
    try:
        return Version(text)
    except InvalidVersion:
        return None


_BUMP_RE = re.compile(r"\bbump (?P<pkg>\S+) from (?P<old>\S+) to (?P<new>\S+)", re.IGNORECASE)


def dependabot_pr_target(title: str) -> tuple[str, str] | None:
    """(package, target version) from a Dependabot title, or None.

    Only the single-package `bump X from A to B` form; a grouped bump names no
    one package, so it never counts as a package's fix PR.
    """
    m = _BUMP_RE.search(title)
    return (canonicalize_name(m["pkg"]), m["new"]) if m else None


def locked_versions(lock_text: str) -> dict[str, list[str]]:
    """Package name → every version uv.lock pins it at (markers can split one)."""
    out: dict[str, list[str]] = {}
    for pkg in tomllib.loads(lock_text).get("package", []):
        # The project's own editable entry has no version; nothing to compare.
        if "version" in pkg:
            out.setdefault(canonicalize_name(pkg["name"]), []).append(pkg["version"])
    return out


def fix_status(
    highest_fix: str | None,
    locked: list[str],
    pr_targets: list[tuple[int, str]],
) -> str:
    """kai.md step 3's fix status: exactly one of fixed on develop, an open
    Dependabot PR, or no fix.

    Fixed on develop means every locked version is at or above the highest
    fix, which is how an alert can stay open after its fix merged (Dependabot
    closes it only on a later scan). A PR counts only if it bumps to at least
    the highest fix.
    """
    fix = _version(highest_fix)
    if fix is None:
        return "no fix (no patched version published)"
    locked_v = [v for v in map(_version, locked) if v is not None]
    if locked_v and min(locked_v) >= fix:
        return f"fixed on develop ({', '.join(locked)} >= {highest_fix})"
    for number, target in pr_targets:
        tv = _version(target)
        if tv is not None and tv >= fix:
            return f"open Dependabot PR #{number} (-> {target})"
    return f"no fix (locked {', '.join(locked) or 'not in uv.lock'}, needs >= {highest_fix})"


def package_status(
    fixes: list[str | None],
    locked: list[str],
    pr_targets: list[tuple[int, str]],
) -> str:
    """Fix status for one package's alerts, given each alert's patched version.

    An alert with no patched version can't be fixed, but it doesn't hide a
    PR or a develop fix that closes the package's other alerts: the status is
    computed over the patched ones and the rest are counted alongside it.
    """
    patched = [v for f in fixes if (v := _version(f)) is not None]
    if not patched:
        return fix_status(None, locked, pr_targets)
    status = fix_status(str(max(patched)), locked, pr_targets)
    unpatched = len(fixes) - len(patched)
    if unpatched:
        status += (
            f"; covers {len(patched)} of {len(fixes)} alerts, {unpatched} with no patched version"
        )
    return status


def user_reach(invert_tree: str) -> str:
    """Classify `uv tree --invert --package X` output.

    A path ending at the project with no `(group: ...)` is a runtime path, so
    the package ships; `(extra: ...)` ships to anyone installing that extra.
    Only paths that all end in a dependency group are dev-only. Don't use the
    alert's own `scope` field instead: it reported pre-commit's virtualenv as
    runtime (2026-10-23).
    """
    roots = [
        ln for ln in invert_tree.splitlines() if re.search(rf"\b{re.escape(PROJECT_NAME)}\b", ln)
    ]
    if not roots:
        return "not reached from this project"
    if any("(group:" not in ln and "(extra:" not in ln for ln in roots):
        return "ships to users"
    if any("(extra:" in ln for ln in roots):
        extras = sorted(set(re.findall(r"\(extra: ([^)]+)\)", "\n".join(roots))))
        return f"ships with extra(s): {', '.join(extras)}"
    groups = sorted(set(re.findall(r"\(group: ([^)]+)\)", "\n".join(roots))))
    return f"dev-only (group: {', '.join(groups)})"


def summarize_checks(rollup: list[dict]) -> str:
    """One-line CI summary that also flags a missing `Lint and test` entry,
    which merge-pr.md step 2 treats as not-run, not as passing."""
    counts: dict[str, int] = {}
    has_lint = False
    for check in rollup or []:
        name = check.get("name") or check.get("context") or ""
        has_lint |= name.startswith("Lint and test")
        # A CheckRun has a conclusion once it completes; a StatusContext has a state.
        state = (check.get("conclusion") or check.get("state") or "PENDING").upper()
        counts[state] = counts.get(state, 0) + 1
    parts = [f"{n} {s.lower()}" for s, n in sorted(counts.items())]
    summary = ", ".join(parts) or "no checks"
    return summary if has_lint else f"{summary}; Lint and test ABSENT"


def solo_only_conflict(rfd: list[dict]) -> bool:
    """True when a `solo-only` ticket is ready alongside any other ready ticket.

    A solo-only ticket alone in the queue is the correct state (kai.md
    "Ticket triage and labeling"), so it isn't flagged.
    """
    return len(rfd) > 1 and any("solo-only" in _labels(i) for i in rfd)


def age_days(iso: str, now: datetime) -> int:
    return (now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days


def _labels(item: dict) -> list[str]:
    return [lb["name"] for lb in item.get("labels", [])]


# --- Sections ---------------------------------------------------------------


def main_checkout() -> Path:
    """The main checkout, even when this script runs from a worktree's copy."""
    common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]).strip()
    return Path(common).parent


def section_checkout() -> list[str]:
    main = main_checkout()
    branch = run(["git", "branch", "--show-current"], cwd=main).strip() or "(detached)"
    dirty = run(["git", "status", "--short"], cwd=main).splitlines()
    behind = run(["git", "rev-list", "--count", "HEAD..origin/develop"], cwd=main).strip()
    lines = [
        f"branch: {branch}",
        f"working tree: {'clean' if not dirty else f'{len(dirty)} changed path(s)'}",
    ]
    lines.append(f"behind origin/develop: {behind} commit(s)")
    if branch != "develop" or dirty:
        lines.append("FLAG: kai.md step 2 expects develop and clean")
    return lines


def section_worktrees() -> tuple[list[str], dict[str, str]]:
    main = main_checkout()
    slots = main / ".claude" / "worktrees"
    branches = parse_worktrees(run(["git", "worktree", "list", "--porcelain"]), main)
    lines = []
    for name, branch in sorted(branches.items()):
        state = "idle" if branch == f"team/{name}" else "busy"
        dirty = ""
        wt = slots / name
        if wt.is_dir():
            n = len(run(["git", "status", "--short"], cwd=wt).splitlines())
            dirty = f", {n} uncommitted" if n else ""
        lines.append(f"{name:<12} {branch}  [{state}{dirty}]")
    return lines, branches


def lane_state(dev: str, slot_branch: str | None, dev_prs: list[dict]) -> str:
    """Whether a Dev lane is free or busy (kai.md step 4, #1250).

    Only a ticket branch's PR holds the lane: a `doc/<dev>/retro-<date>` PR
    claims no issue, and dev.md's pickup doesn't wait on it. A `parked` PR
    doesn't hold it either: neither the PR nor the slot still sitting on its
    branch (dev.md treats that slot as idle). An unknown slot branch counts as
    busy, so a missing worktree never reads as free.
    """
    tickets = [p for p in dev_prs if is_ticket_branch(p["headRefName"], dev)]
    if any("parked" not in _labels(p) for p in tickets):
        return "busy"
    parked_branches = {p["headRefName"] for p in tickets}
    if slot_branch == f"team/{dev}" or slot_branch in parked_branches:
        return "free"
    return "busy"


def section_lanes(branches: dict[str, str], prs: list[dict], rfd: list[dict]) -> list[str]:
    lines = []
    for dev, lane in LANE_OF_DEV.items():
        queued = [f"#{i['number']}" for i in rfd if lane in _labels(i)]
        mine = [p for p in prs if branch_owner(p["headRefName"]) == dev]
        tickets = [p for p in mine if is_ticket_branch(p["headRefName"], dev)]
        active = [f"#{p['number']}" for p in tickets if "parked" not in _labels(p)]
        parked = [f"#{p['number']}" for p in tickets if "parked" in _labels(p)]
        lines.append(
            f"{lane} ({dev}): {lane_state(dev, branches.get(dev), mine)}; "
            f"slot on {branches.get(dev, '?')}; queued {', '.join(queued) or 'nothing'}; "
            f"open PR {', '.join(active) or 'none'}; parked {', '.join(parked) or 'none'}"
        )
    return lines


def section_prs(prs: list[dict]) -> list[str]:
    lines = []
    for p in prs:
        draft = " DRAFT" if p.get("isDraft") else ""
        lines.append(
            f"#{p['number']} [{p['author']['login']}] {p['headRefName']}{draft}\n"
            f"      {p['title']}\n"
            f"      labels: {', '.join(_labels(p)) or '-'} | CI: {summarize_checks(p.get('statusCheckRollup') or [])}"
        )
    return lines or ["none"]


def section_rfd(rfd: list[dict]) -> list[str]:
    lines = []
    for i in rfd:
        labels = _labels(i)
        lanes = [lb for lb in labels if lb in LANE_OF_DEV.values()]
        where = lanes[0] if lanes else "on deck"
        lines.append(f"#{i['number']} ({where}) {i['title']}  [{', '.join(labels)}]")
        if lanes and "good first issue" in labels:
            lines.append(
                f"      FLAG: carries both good first issue and {lanes[0]} (kai.md: fix on sight)"
            )
    if solo_only_conflict(rfd):
        lines.append("FLAG: a solo-only ticket is ready-for-development alongside other tickets")
    return lines or ["none"]


def section_community(prs: list[dict], issues: list[dict]) -> list[str]:
    lines = []
    for kind, items in (("PR", prs), ("issue", issues)):
        for item in items:
            if not is_outside_contributor(item["author"]):
                continue
            labels = _labels(item)
            if "community" not in labels:
                lines.append(
                    f"needs intake: {kind} #{item['number']} [{item['author']['login']}] {item['title']}"
                )
            elif kind == "PR" and "needs-ticket" in labels:
                lines.append(
                    f"re-check issue refs: PR #{item['number']} still carries needs-ticket"
                )
            elif kind == "issue" and "verify-content" in labels:
                lines.append(f"waiting for reproduction: issue #{item['number']} {item['title']}")
    return lines or ["nothing to do"]


def section_advisories(now: datetime) -> list[str]:
    advisories = gh_json(["api", "repos/{owner}/{repo}/security-advisories?state=triage"])
    # ID, age, and summary only: nothing else about a report goes anywhere
    # (security-advisory.md rule 1).
    rows = sorted(advisories, key=lambda a: a["created_at"])
    return [f"{a['ghsa_id']}  {age_days(a['created_at'], now)}d  {a['summary']}" for a in rows] or [
        "none in triage"
    ]


def _alert_fix(alert: dict) -> str | None:
    return (alert["security_vulnerability"].get("first_patched_version") or {}).get("identifier")


def _severity_text(alerts: list[dict]) -> str:
    counts: dict[str, int] = {}
    for a in alerts:
        sev = a["security_advisory"]["severity"]
        counts[sev] = counts.get(sev, 0) + 1
    return ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))


def section_dependabot(prs: list[dict]) -> list[str]:
    pages = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            "repos/{owner}/{repo}/dependabot/alerts?state=open&per_page=100",
        ]
    )
    alerts = [a for page in pages for a in page]
    if not alerts:
        return ["no open alerts"]

    pip = [a for a in alerts if a["dependency"]["package"]["ecosystem"] == "pip"]
    other = [a for a in alerts if a["dependency"]["package"]["ecosystem"] != "pip"]
    lines = []

    if pip:
        # Fix status and reach both read origin/develop's lockfile, not the
        # working tree's, so the two halves of a row describe the same lock.
        lock_text = run(["git", "show", "origin/develop:uv.lock"])
        locked = locked_versions(lock_text)
        pr_targets: dict[str, list[tuple[int, str]]] = {}
        for p in prs:
            if p["author"].get("is_bot") and (t := dependabot_pr_target(p["title"])):
                pr_targets.setdefault(t[0], []).append((p["number"], t[1]))

        by_pkg: dict[str, list[dict]] = {}
        for a in pip:
            by_pkg.setdefault(canonicalize_name(a["dependency"]["package"]["name"]), []).append(a)

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "pyproject.toml").write_text(
                run(["git", "show", "origin/develop:pyproject.toml"])
            )
            (project / "uv.lock").write_text(lock_text)
            for pkg, pkg_alerts in sorted(by_pkg.items()):
                try:
                    tree = run(
                        ["uv", "tree", "--frozen", "--project", tmp, "--invert", "--package", pkg]
                    )
                    reach = user_reach(tree)
                except CommandError as e:
                    reach = f"unknown ({e})"
                status = package_status(
                    [_alert_fix(a) for a in pkg_alerts],
                    locked.get(pkg, []),
                    pr_targets.get(pkg, []),
                )
                lines.append(f"{pkg}: {len(pkg_alerts)} alert(s) ({_severity_text(pkg_alerts)})")
                lines.append(f"      status: {status}")
                lines.append(f"      reach: {reach}")
                lines.append(
                    f"      alerts: {', '.join('#' + str(a['number']) for a in pkg_alerts)}"
                )

    # No lockfile or uv tree for other ecosystems (e.g. github-actions); just
    # what the alert itself says.
    for a in other:
        pkg = a["dependency"]["package"]
        lines.append(
            f"{pkg['ecosystem']} {pkg['name']}: alert #{a['number']} "
            f"({a['security_advisory']['severity']}), fix {_alert_fix(a) or 'none'}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-fetch", action="store_true", help="skip `git fetch origin develop`")
    args = parser.parse_args(argv)

    if not args.no_fetch:
        try:
            run(["git", "fetch", "--quiet", "origin", "develop"])
        except CommandError as e:
            print(f"warning: {e}; comparing against the existing origin/develop", file=sys.stderr)

    now = datetime.now(UTC)
    pr_fields = "number,title,headRefName,author,labels,isDraft,statusCheckRollup"
    issue_fields = "number,title,author,labels"
    cache: dict[str, list[dict]] = {}

    def fetch(key: str, args: list[str]) -> list[dict]:
        if key not in cache:
            cache[key] = gh_json(args)
        return cache[key]

    def prs() -> list[dict]:
        return fetch(
            "prs", ["pr", "list", "--state", "open", "--limit", "200", "--json", pr_fields]
        )

    def issues() -> list[dict]:
        return fetch(
            "issues", ["issue", "list", "--state", "open", "--limit", "500", "--json", issue_fields]
        )

    def rfd() -> list[dict]:
        return [i for i in issues() if "ready-for-development" in _labels(i)]

    branches: dict[str, str] = {}

    def worktrees() -> list[str]:
        lines, found = section_worktrees()
        branches.update(found)
        return lines

    sections = [
        ("Main checkout", section_checkout),
        ("Worktrees", worktrees),
        ("Lanes", lambda: section_lanes(branches, prs(), rfd())),
        ("Open PRs", lambda: section_prs(prs())),
        ("Ready for development", lambda: section_rfd(rfd())),
        ("Community intake", lambda: section_community(prs(), issues())),
        ("Private vulnerability reports (triage)", lambda: section_advisories(now)),
        ("Dependabot alerts", lambda: section_dependabot(prs())),
    ]
    failed = False
    for title, build in sections:
        print(f"== {title} ==")
        try:
            body = build()
        except Exception as e:  # the contract: one section's failure never ends the report
            failed = True
            body = [f"ERROR: {type(e).__name__}: {e}"]
        for line in body:
            print(f"  {line}")
        print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
