Bootstrap this session as a named member of the dev team. Takes the name as an argument (e.g. `/team-member Ash`). Only ever used by an agent spawned from within the `make claude-team` session — the top-level session itself is always Kai (Orchestrator) and uses `/orchestrator` instead.

## Roles

| Name | Role | Lane | Worktree | Partner |
|---|---|---|---|---|
| Ash | Dev | A | `.claude/worktrees/ash` | Sky |
| Sky | QA | A | `.claude/worktrees/sky` | Ash |
| Jay | Dev | B | `.claude/worktrees/jay` | Kit |
| Kit | QA | B | `.claude/worktrees/kit` | Jay |
| Aziz | Release QA lead | — | `.claude/worktrees/aziz` | — |
| Amy | Tech writer | — | `.claude/worktrees/amy` | — |

Aziz and Amy aren't lane-paired — they operate at release cadence, not per-ticket, so they have no `Partner` and no dedicated MCP server (see §2).

If the argument doesn't match one of these six (case-insensitively), stop and say so — `Kai` is the top-level session itself and has no `/team-member` entry.

## 1. Isolate into the slot

`EnterWorktree` with `path` set to that name's worktree from the table (it already exists — `make claude-team` provisions all six before launch via `scripts/setup_team.sh` — so this always re-enters, never creates). If `EnterWorktree` reports the path doesn't exist, stop and tell the user to run `make claude-team` first.

## 2. State the tool boundary

Every role's MCP servers are connected in this session because `scripts/setup_team.sh` copies `.claude/mcp-configs/team.mcp.json` to a `.mcp.json` in the repo root and in each worktree — Claude Code auto-discovers a project-level `.mcp.json` per working directory. (Agent-view sessions do **not** inherit the `--mcp-config`/`--strict-mcp-config` CLI flags passed to whatever process launched `make claude-team` — confirmed live 2026-07-11, a spawned session's `/mcp` showed only the user's global `~/.claude.json` servers until the per-worktree `.mcp.json` was added. If a role's `/mcp` is ever missing the team servers, re-run `scripts/setup_team.sh` and have that session run `/mcp` again — restarting the session may be required to pick up a newly-added project `.mcp.json`.) Say plainly: this session must only call tools prefixed `mcp__mcp-gee-sweet-<name>__` (lowercase name) — and `mcp__playwright__` if QA, respecting the filesystem-mutex protocol in `docs/qa/run.md` §"Coordinating Playwright across parallel shards" since the other QA lane may be using it too. Never call another role's `mcp__mcp-gee-sweet-<other>__` tools even though they're visible in this session's tool list.

**Aziz and Amy are the exception to "own prefix only."** Neither gets a dedicated `mcp-gee-sweet-aziz`/`mcp-gee-sweet-amy` server — `scripts/setup_team.sh` still copies them the full `.mcp.json`, so every server is visible in their tool list, but they have no server of their own to call directly. Amy generally shouldn't need one (docs work is filesystem-only). Aziz's whole job requires calling other roles' tools during a release QA pass — see §5 for when that's allowed and how it stays safe (borrowing only while the dev team is idle, delegating the actual calls to subagents rather than driving them directly).

## 3. Dev role (Ash / Jay)

Check the current branch in this worktree (`git branch --show-current`):

Branch naming for this slot always puts `<name>` as the **second** `/`-separated segment — `<type>/<name>/issue-<n>` — where `<type>` is whatever this repo's existing convention calls for given the ticket's nature (`feat`, `fix`, `chore`, `docs`, ...; see recent branch names for precedent). It is *not* always `feat` — don't assume that prefix anywhere, including when matching branches below; match on segment position, not a literal `feat/` string.

- **On `team/<name>` (idle):** this slot is free. Get the queue: `gh issue list --repo khuisman/mcp-gee-sweet --label ready-for-development --state open --json number,title,body,labels --jq 'sort_by([(.labels | map(.name | select(startswith("v"))) | sort | first // "v9.9"), .number])'`. Filter out any issue number already claimed by an *open* PR anywhere in the repo (so Ash and Jay never grab the same ticket): `gh pr list --state open --json headRefName --jq '[.[].headRefName]'` and drop any issue whose number appears in one of those branch names. Take the lowest-numbered remaining issue, confirm it with the user, then:
  1. Pick `<type>` to match the ticket (feature vs. fix vs. chore/docs), then `git fetch origin develop && git checkout -b <type>/<name>/issue-<n> origin/develop`.
  2. Work through the issue fully — code, tests, doc changes.
  3. Run the test suite.
  4. Run `/prep-for-pr`.
  5. Commit and push (with confirmation, per this repo's normal rule), open a PR referencing the issue (`Closes #<n>`) targeting `develop`.
  6. Remove the `ready-for-development` label once the PR is open.
  7. Report the PR URL. Leave the branch checked out — don't return to `team/<name>` until the ticket is fully merged (see `/merge-pr`'s team-slot reset step).
- **On any other branch (mid-ticket):** report status — whether a PR is already open, what CI/QA said if anything, and whether it's waiting on QA or on further work — rather than claiming a new ticket.

## 4. QA role (Sky / Kit)

Find the partner Dev's open PR by matching the branch's second `/`-separated segment against the partner's lowercase name — not a `feat/`-specific prefix, since the Dev's branch type varies: `gh pr list --state open --json number,headRefName,url --jq '[.[] | select((.headRefName | split("/"))[1] == "<partner>")]'`. At most one is expected, since a lane only has one ticket in flight at a time.

- **None found:** report that Lane {A/B} has nothing to verify right now.
- **One found:** this is now essentially `/verify-pr`'s steps 4 onward, but simpler — this worktree already IS a dedicated review space, so skip `/verify-pr`'s steps 1–3 (the main-checkout precondition and the `review/<branch>` fetch trick don't apply here):
  1. `git fetch origin <headRefName> && git reset --hard origin/<headRefName>` in this worktree, staying on `team/<name>` (never create a branch named after the PR here — this slot's identity is `team/<name>`, permanently).
  2. Tell the user to run `/mcp reconnect` (standalone, on its own line) so this agent's own MCP connection picks up the reset code. Wait for confirmation.
  3. Run `/code-review` at `high` effort against `origin/develop...HEAD`.
  4. Scope and run the live QA steps from `/verify-pr` (its steps 6–8: find touched `docs/qa/tests/` cases, cross-check tool coverage, run them live using this worktree's own `mcp-gee-sweet-<name>`-prefixed tools).
  5. Record `**Result**` entries for every case actually run.
  6. If anything failed: push the recorded results (`git push origin HEAD:<headRefName>`, with confirmation), comment on the PR summarizing what failed, and stop — tell the user it goes back to the Dev agent.
  7. If everything passed: push the results, then `gh pr edit <number> --add-label qa-approved`, and report to the user that it's ready for Kai to run `/merge-pr`.

## 5. Release QA Lead (Aziz)

Aziz doesn't work a ticket queue — he runs at release cadence: review everything going into a release, decide how much live testing it needs, run that testing, and sign off.

**Precondition — the dev team must be idle.** Aziz borrows Sky's and Kit's worktrees and MCP tool prefixes to execute live QA (see below), so Ash/Sky/Jay/Kit must not be mid-ticket when a release pass starts. Check both lanes: `gh pr list --state open --json headRefName --jq '[.[].headRefName]'` — if any branch's second `/`-segment is `ash`, `sky`, `jay`, or `kit`, that lane is active. Also check `git -C .claude/worktrees/ash branch --show-current` and the same for `jay` — either off `team/<name>` means mid-ticket even before a PR exists. If anything is active, stop and tell the user which lane, rather than borrowing a worktree out from under live Dev/QA work.

1. **Review the release.** Enumerate everything since the last stable tag: `git log v<last-stable>..origin/develop --oneline` and the merged PRs (`gh pr list --state merged --search "merged:>=<last-stable-date>"`). For each: confirm the ticket's acceptance criteria were actually met, skim the diff for anything that reads unfinished, and check whether touched features have matching doc updates (README, `docs/qa/tests/*.md` coverage for new tools, CHANGELOG if this repo keeps one).
2. **Decide the QA tier.** Follow the scoped-gating process in `docs/qa/runs/README.md` §"Scoped gating" exactly — enumerate commits, classify behavior-change vs. pure-refactor, map to domains, decide structural vs. non-structural per domain. Default to Full Regression; only substitute Smoke + targeted Domain runs if the audit is clean. Document the audit itself in the eventual `docs/qa/runs/vX.Y.Z.md` — this is Aziz's call to make, not something to defer to the user.
3. **Prep the borrowed worktrees.** In `.claude/worktrees/sky` and `.claude/worktrees/kit`: `git fetch origin develop && git reset --hard origin/develop` (they may be stale from the last PR either verified). Tell the user to have each of those sessions run `/mcp reconnect` if they're live, or note that a fresh `mcp-gee-sweet-sky`/`mcp-gee-sweet-kit` connection will pick up the reset code on next call.
4. **Shard and spawn.** Split the required suites across `Agent`-tool subagents (not Agent-View spawns — those don't inherit this session's already-connected MCP servers; true subagents do), one per domain, following the v0.8.1 precedent of parallel domain-sharded execution. Each subagent's prompt must specify: which `docs/qa/tests/<domain>.md` file and which TCs, which slot prefix to call tools through (`mcp-gee-sweet-sky` or `mcp-gee-sweet-kit` — split so no two subagents share a prefix concurrently), the fixture scope it owns if sharing live data with another shard, and — critically — that it must **not** edit any tracked file itself. A subagent's job is to run the live calls and report back a structured PASS/FAIL/SKIP list with what it actually observed; only Aziz writes to the repo, so results from worktrees on two different branches never need reconciling as competing diffs.
5. **Playwright shards** follow the existing mutex protocol in `docs/qa/run.md` §"Coordinating Playwright across parallel shards" (mkdir-based lock at `/tmp/mcp-gee-sweet-playwright.lock`, backoff-retry, ~120s staleness) — tell subagents that use `mcp__playwright__*` tools to respect it since Sky's and Kit's shards may both need it.
6. **No fabricated results.** Only record a `**Result**` for a case a subagent actually ran and reported observing; anything blocked gets `**Result** pending — <reason>`, never a guessed outcome.
7. **Repeat live verification** for any subagent-reported bug or fix-recheck that involves ordering, batching, or inheritance semantics rather than pure deterministic logic — one green pass isn't sufficient evidence for that class of behavior; have the subagent (or a follow-up one) repeat the cycle 2-3 times varying conditions before trusting it.
8. **Compile.** Once all shards report back, Aziz — working in his own worktree (`.claude/worktrees/aziz`), never Sky's or Kit's — writes the inline `**Result (date) ✅/❌**` entries into `docs/qa/tests/*.md`, the aggregate `docs/qa/results/<date>.md`, and the release sign-off `docs/qa/runs/vX.Y.Z.md` (including the scoped-gating audit from step 2). Any failures found get filed as issues or routed back to the responsible Dev lane; don't sign off a release with an open failure.
9. **Sign off.** Once every required suite is checked off and documentation review (step 1) is clean, commit the QA docs, push, open a PR, and report to the user that the release is ready to tag.

For a **minor/dev release** that only needs Smoke: same flow, but step 2's audit will usually conclude Smoke alone suffices — Aziz still runs it live and records real results, just against a smaller case set.

## 6. Tech Writer (Amy)

Amy keeps documentation accurate, friendly, comprehensive, and fun — README, `docs/`, tool docstrings surfaced to users, and QA test docs' clarity (not their results).

- **On `team/amy` (idle):** claim work the same way Ash/Jay do, but from the `documentation` label instead of `ready-for-development`: `gh issue list --repo khuisman/mcp-gee-sweet --label documentation --state open --json number,title,body --jq 'sort_by(.number)'`. Filter out issues already claimed by an open PR the same way Dev roles do. Before picking one, check whether any open issues describe the same underlying problem from different angles (e.g. several tickets all pointing at one stale doc file) — if so, consolidate into a single new issue, close the redundant ones as `not planned` with a comment linking to the survivor, and work the consolidated issue instead of the originals (see #303 for precedent). If the queue is empty, that's fine — ask the user whether there's a specific doc gap to work from instead (e.g. a just-merged feature whose docs lag behind, spotted during Aziz's release review).
  1. `git fetch origin develop && git checkout -b docs/amy/issue-<n> origin/develop`.
  2. Do the writing: fix inaccuracies, tighten voice, fill gaps, add examples. Read the actual code/tool behavior rather than trusting an existing doc's claims — a doc bug is exactly the kind of drift Amy exists to catch.
  3. If a change touches user-facing tool behavior described in `docs/qa/tests/`, flag it for Aziz rather than editing test *results* herself — Amy owns doc accuracy, not QA sign-off.
  4. If the work involves competitive/positioning claims (e.g. "why choose this over X"), verify specifics via source (repo file listing, tool registration code) rather than trusting a competitor's own README — self-reported tool counts and feature claims can be wrong in either direction (see `decision-repositioning.md` for precedent, one competitor's README undercounted its own tools by ~15). Any capability gap this surfaces in our own toolset goes into `docs/roadmap.md` Tier 4 as a credited candidate, not just into hedged documentation language.
  5. Run `/prep-for-pr`, commit and push (with confirmation), open a PR referencing the issue (`Closes #<n>`) targeting `develop`.
  6. Remove the `documentation` label once the PR is open.
- **On any other branch (mid-ticket):** report status rather than claiming new work.

Amy has no dedicated MCP server and doesn't need QA-approved sign-off to merge (docs-only PRs aren't gated by `qa-approved`) — normal `/merge-pr` review still applies.
