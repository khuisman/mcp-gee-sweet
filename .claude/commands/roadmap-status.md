Produce a role-based "what's left, who's doing it, and where the actual bottleneck is" report for one version target — the leaderboard Kai currently reconstructs by hand each time from `gh issue list`/`gh pr list`/worktree state (issue #622). Read-only: this command never edits labels, files, or issues, only reports on them. Runs from any checkout that has the persistent dev-team worktrees present (the main checkout, or any `.claude/worktrees/*` slot) — step 5 locates the main checkout root via `git rev-parse --git-common-dir` before building the `.claude/worktrees/ash`/`jay` paths off it, rather than a bare relative path, so it resolves correctly regardless of which worktree the session itself is in (a bare relative path does not: confirmed live, it resolves against the session's own cwd and silently fails from inside any worktree other than the main checkout — see `team-member.md`'s own EnterWorktree note for the same gotcha).

**Usage:** `/roadmap-status [<version-label> | next | backlog]` — no argument resolves to the current release-cadence target (step 1).

## 1. Resolve the target label

- **`backlog`** — use the literal `backlog` label as-is; skip the rest of this step.
- **An explicit version label** (`v1.0`, `v0.8.1`, etc.) — confirm it exists first (`gh label list --json name --jq '.[].name'`); if it doesn't, stop and list the version labels that do exist rather than silently querying an empty set.
- **No argument, or `next`** — resolve dynamically against `docs/roadmap.md`'s "Release cadence" table rather than hardcoding a version here: this file gets loaded every time the command runs, and a hardcoded "current" version goes stale the moment that version ships (see `feedback_no_hardcoded_moving_target_docs` memory — the same class of drift as the hardcoded tool-count bugs it documents).
  1. Read the table's first column top to bottom to get the version labels in cadence order (currently v0.7 → v0.8 → v0.8.1 → v0.9 → v1.0 → v1.1+, but re-read it live each run — a new row gets added every release).
  2. Get the last shipped tag: `git tag --list 'v*' | sort -V | tail -1`.
  3. Normalize it to a table label: drop a trailing `.0` (`v0.8.0` → `v0.8`); a non-`.0` patch tag stays as-is (`v0.8.1` → `v0.8.1`). Locate that label's row in the table.
  4. **Default target** (no argument) = the label in the next row after the last-shipped row — whatever hasn't shipped yet.
  5. **`next`** = the label one row further, after the default target's own row.
  6. If there's no row after the one you need (e.g. default target resolves past the table's last row), stop and say so rather than guessing.

## 2. Fetch open issues

```
gh issue list --repo khuisman/mcp-gee-sweet --label <resolved-label> --state open --json number,title,labels
```

If this returns zero issues, report that plainly (`0 open issues for <resolved-label>`) and stop — no need to run the remaining steps against an empty set.

## 3. Bucket each issue by role

Check each issue's labels against this list in order; **first match wins**, so an issue with multiple role-shaped labels still lands in exactly one bucket:

1. `bob`
2. `aziz`
3. `joy`
4. `qa`
5. `documentation`
6. `lane-a` or `lane-b`, **only** if `ready-for-development` is also present (a lane label without RFD hasn't cleared triage yet — falls through)
7. **unlaned dev** — `ready-for-development` present, `enhancement` or `defect` present, neither `lane-a` nor `lane-b` present
8. **not yet actionable** — `decision-needed` present, or `ready-for-development` absent and nothing above matched
9. **unowned** — none of the above matched at all (no role label, no RFD, no decision-needed — just sitting there)

**Flag mislabeled catch-alls, don't just count them.** Bucket 5 (`documentation`) and bucket 9 are both places a ticket can hide because no better label exists yet, not because the bucket is actually right for it — issue #588 ("add a repo icon/logo") carries `documentation` even though the work is graphic-design, not writing, because there's no `design` role/label in this repo. Before finalizing the buckets, skim the title (and body if the title's ambiguous) of every issue in buckets 5 and 9: if the actual work needs a competency no current team role owns — visual/graphic design is the known case, there may be others — pull it out into its own **unowned/gap** line instead of folding it silently into whichever label it happened to carry. This is a judgment call, not a keyword match; don't hardcode a trigger-word list for it.

## 4. Differentiate lane-ready from needs-human (buckets 4, 7, and non-`decision-needed` bucket 8)

Bucket 4's `qa` label identifies *subject matter* (test coverage, fixtures, infra), not an owning executor — Sky and Kit have no standalone backlog-pickup mechanism at all (`.claude/team-roles/qa.md` is purely reactive: it only activates when a partner Dev already has an open PR to verify). A `qa`-labeled issue is therefore either dev-shaped work waiting on triage — the same as bucket 7 — or something that needs the maintainer directly; it is never something Sky/Kit will pick up on their own initiative. Run this audit over every issue in bucket 4, every issue in bucket 7, and any bucket-8 issue that landed there via the "RFD absent and nothing above matched" clause rather than an actual `decision-needed` label.

For each candidate, apply these four tests in order — confirmed live 2026-08-18 auditing all 12 open `v0.9` issues (session behind PR #628 and issue #629): 3 of 12 were genuinely lane-ready (#495, #377, #224), 4 needed the maintainer directly (#305, #304, #53, #49), one was a design gap already covered by the bucket-5/9 flag above (#588), one fit Joy (#50), and one was Bob's (#602):

1. **Repo-only acceptance criteria?** Lane-ready work closes with a git diff + passing tests alone. If "done" depends on something that has to exist *outside* the repo and doesn't already (a new Google account, a Shared Drive, a real non-Google email address, a Workspace admin setting) — no service-account/OAuth credential this team holds can self-provision that — it needs the maintainer, full stop, regardless of how implementable the rest of the ticket reads.
2. **Implementation verb, or decision verb?** "Add a test that...", "add the categories to `[tool.ruff.lint] select`" → implementation, lane-ready candidate. "Decide whether...", "Decision needed:", a title prefixed `Plan:` → the ticket hasn't been triaged into a decision yet; implementing anything off it means guessing at a call that isn't a lane's to make.
3. **Bounded, or an epic bundling unlike things?** One mirrored test, one config change with an exact command — lane-sized. A checklist spanning account creation + code + an open investigation isn't one unit of work; it needs decomposing into pieces that individually pass test 1 before any piece gets a lane label.
4. **Precedent to mirror, or open-ended?** "Mirror the existing test `X`" or exact dry-run counts already given — promotable on sight. "Investigate whether X is feasible" with no prior art — needs a feasibility pass first (Joy's remit per `.claude/team-roles/joy.md`, not a lane's).

Tests 1–2 are near-binary from the issue text alone; 3–4 are judgment calls — read the full issue body, not just the title, before ruling (issue #322 only revealed its split code/live-action nature past the title: adding test-file teardown is lane-doable, but the one-time sweep of already-polluted live fixture state is a live action, not a pure diff).

Tag each audited issue as one of: **lane-ready**, **needs-you** (fails test 1, or is an explicit decision per test 2), **needs-decomposition** (fails test 3), or **needs-scoping** (fails test 4 — route to Joy). Carry these tags into the report in step 6.

## 5. Cross-reference dev issues (buckets 6 and 7) against real state

For every issue in the lane bucket (6) or unlaned-dev bucket (7):

- **Open PR check** (applies to both): `gh pr list --state open --json number,headRefName`, then look for `issue-<N>` anywhere in `headRefName` — confirmed live as this repo's branch convention (`fix/jay/issue-458`, `docs/amy/issue-601`, `chore/jay/issue-605`). A match means **in-progress** regardless of bucket.
- **Worktree check** (lane bucket only, when no PR match yet): resolve the main checkout root once — `root=$(dirname "$(git rev-parse --git-common-dir)")` — then `git -C "$root/.claude/worktrees/ash" branch --show-current` for `lane-a` issues, `git -C "$root/.claude/worktrees/jay" branch --show-current` for `lane-b` issues. Use `--git-common-dir`, not `--show-toplevel`: from inside a linked worktree, `--show-toplevel` returns that worktree's own root (worktrees don't nest under each other), while `--git-common-dir` always points at the main checkout's shared `.git` regardless of which worktree the session is in — confirmed live from inside `.claude/worktrees/bob`. If the current branch matches `issue-<N>` for one of that lane's bucketed issues, it's **in-progress** even before a PR exists.
- Anything in the lane bucket with neither match is **queued** (RFD + lane label, not picked up yet).
- Anything in the unlaned-dev bucket with no PR match is **on-deck** (RFD, no lane — open for `/next-issue` or outside contribution).
- Everything in bucket 8 is **blocked** by definition (no RFD) — no PR/worktree check needed, the label state already answers it.

## 6. Report

One row per bucket: role, open count, in-progress count (from step 5, where applicable), issue numbers. Within each bucket, also call out how many of its issues additionally carry `decision-needed` — a role's queue depth and its *actionable* depth are different numbers, and the callout below needs the second one. For buckets audited in step 4 (4, 7, and non-`decision-needed` bucket 8), break the issue list down by the tag each issue earned there instead of listing it as one undifferentiated count — a `qa` bucket that's "7 open" reads very differently once it's "2 lane-ready, 4 needs-you, 1 needs-scoping."

```
## Roadmap status — <resolved-label>

| Bucket | Open | In-progress | Issues |
|---|---|---|---|
| Bob | ... | ... | #... |
| Aziz | ... | ... | #... |
| Joy | ... | ... | #... — <M needs-scoping from step 4> |
| QA | ... | ... | #... — <lane-ready: #...; needs-you: #...; needs-decomposition: #...; needs-scoping: #...> (N need a decision) |
| Documentation (Amy) | ... | ... | #... |
| Dev — lane-a (Ash) | ... | ... in-progress, ... queued | #... |
| Dev — lane-b (Jay) | ... | ... in-progress, ... queued | #... |
| Dev — on-deck (unlaned) | ... | ... | #... — <lane-ready: #...; needs-you: #...; needs-decomposition: #...; needs-scoping: #...> |
| Not yet actionable | ... | — | #... — <needs-you: #...; still untriaged (no audit signal either way): #...> |
| Unowned / gap | ... | — | #... — <why: no role owns this yet> |
```

Close with a one-line callout naming where the actual depth is — not just the biggest raw count, but the biggest count of issues that are both open, actionable, *and* lane-ready right now (a bucket that's mostly `decision-needed` or `needs-you` isn't a throughput problem, it's a decision problem — see issue #629 for a worked example of consolidating a batch of `needs-you` findings into one maintainer-facing ticket rather than leaving the signal scattered). E.g.: "QA: 7 open, 2 lane-ready, 4 need your decision (consolidated in #629), not more dev throughput."
