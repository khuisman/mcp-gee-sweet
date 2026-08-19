Produce a role-based "what's left, who's doing it, and where the actual bottleneck is" report for one version target — the leaderboard Kai currently reconstructs by hand each time from `gh issue list`/`gh pr list`/worktree state (issue #622). Read-only: this command never edits labels, files, or issues, only reports on them. Runs from any checkout that has the persistent dev-team worktrees present (the main checkout, or any `.claude/worktrees/*` slot) — step 4 locates the main checkout root via `git rev-parse --git-common-dir` before building the `.claude/worktrees/ash`/`jay` paths off it, rather than a bare relative path, so it resolves correctly regardless of which worktree the session itself is in (a bare relative path does not: confirmed live, it resolves against the session's own cwd and silently fails from inside any worktree other than the main checkout — see `team-member.md`'s own EnterWorktree note for the same gotcha).

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

## 4. Cross-reference dev issues (buckets 6 and 7) against real state

For every issue in the lane bucket (6) or unlaned-dev bucket (7):

- **Open PR check** (applies to both): `gh pr list --state open --json number,headRefName`, then look for `issue-<N>` anywhere in `headRefName` — confirmed live as this repo's branch convention (`fix/jay/issue-458`, `docs/amy/issue-601`, `chore/jay/issue-605`). A match means **in-progress** regardless of bucket.
- **Worktree check** (lane bucket only, when no PR match yet): resolve the main checkout root once — `root=$(dirname "$(git rev-parse --git-common-dir)")` — then `git -C "$root/.claude/worktrees/ash" branch --show-current` for `lane-a` issues, `git -C "$root/.claude/worktrees/jay" branch --show-current` for `lane-b` issues. Use `--git-common-dir`, not `--show-toplevel`: from inside a linked worktree, `--show-toplevel` returns that worktree's own root (worktrees don't nest under each other), while `--git-common-dir` always points at the main checkout's shared `.git` regardless of which worktree the session is in — confirmed live from inside `.claude/worktrees/bob`. If the current branch matches `issue-<N>` for one of that lane's bucketed issues, it's **in-progress** even before a PR exists.
- Anything in the lane bucket with neither match is **queued** (RFD + lane label, not picked up yet).
- Anything in the unlaned-dev bucket with no PR match is **on-deck** (RFD, no lane — open for `/next-issue` or outside contribution).
- Everything in bucket 8 is **blocked** by definition (no RFD) — no PR/worktree check needed, the label state already answers it.

## 5. Report

One row per bucket: role, open count, in-progress count (from step 4, where applicable), issue numbers. Within each bucket, also call out how many of its issues additionally carry `decision-needed` — a role's queue depth and its *actionable* depth are different numbers, and the callout below needs the second one.

```
## Roadmap status — <resolved-label>

| Bucket | Open | In-progress | Issues |
|---|---|---|---|
| Bob | ... | ... | #... |
| Aziz | ... | ... | #... |
| Joy | ... | ... | #... |
| QA | ... | ... | #... (N need a decision) |
| Documentation (Amy) | ... | ... | #... |
| Dev — lane-a (Ash) | ... | ... in-progress, ... queued | #... |
| Dev — lane-b (Jay) | ... | ... in-progress, ... queued | #... |
| Dev — on-deck (unlaned) | ... | ... | #... |
| Not yet actionable | ... | — | #... |
| Unowned / gap | ... | — | #... — <why: no role owns this yet> |
```

Close with a one-line callout naming where the actual depth is — not just the biggest raw count, but the biggest count of issues that are both open *and* actionable right now (a bucket that's mostly `decision-needed` isn't a throughput problem, it's a decision problem). E.g.: "QA: 8 open, 2 need your decision, not more dev throughput."
