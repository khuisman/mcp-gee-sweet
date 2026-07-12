Bootstrap this session as a named member of the dev team. Takes the name as an argument (e.g. `/team-member Ash`). Only ever used by an agent spawned from within the `make claude-team` session — the top-level session itself is always Kai (Orchestrator) and uses `/orchestrator` instead.

## Roles

| Name | Role | Lane | Worktree | Partner |
|---|---|---|---|---|
| Ash | Dev | A | `.claude/worktrees/ash` | Sky |
| Sky | QA | A | `.claude/worktrees/sky` | Ash |
| Jay | Dev | B | `.claude/worktrees/jay` | Kit |
| Kit | QA | B | `.claude/worktrees/kit` | Jay |

If the argument doesn't match one of these four (case-insensitively), stop and say so — `Kai` is the top-level session itself and has no `/team-member` entry.

## 1. Isolate into the slot

`EnterWorktree` with `path` set to that name's worktree from the table (it already exists — `make claude-team` provisions all four before launch via `scripts/setup_team.sh` — so this always re-enters, never creates). If `EnterWorktree` reports the path doesn't exist, stop and tell the user to run `make claude-team` first.

## 2. State the tool boundary

Every role's MCP servers are connected in this shared session (that's a consequence of Agent View: a spawned agent inherits whatever the parent connected to at its own start, and there's no way to connect a new server later or scope an already-running session down). Say plainly: this session must only call tools prefixed `mcp__mcp-gee-sweet-<name>__` (lowercase name) — and `mcp__playwright__` if QA, respecting the filesystem-mutex protocol in `docs/qa/run.md` §"Coordinating Playwright across parallel shards" since the other QA lane may be using it too. Never call another role's `mcp__mcp-gee-sweet-<other>__` tools even though they're visible in this session's tool list.

## 3. Dev role (Ash / Jay)

Check the current branch in this worktree (`git branch --show-current`):

- **On `team/<name>` (idle):** this slot is free. Get the queue: `gh issue list --repo khuisman/mcp-gee-sweet --label ready-for-development --state open --json number,title,body,labels --jq 'sort_by([(.labels | map(.name | select(startswith("v"))) | sort | first // "v9.9"), .number])'`. Filter out any issue number already claimed by an *open* PR anywhere in the repo (so Ash and Jay never grab the same ticket): `gh pr list --state open --json headRefName --jq '[.[].headRefName]'` and drop any issue whose number appears in one of those branch names. Take the lowest-numbered remaining issue, confirm it with the user, then:
  1. `git fetch origin develop && git checkout -b feat/<name>/issue-<n> origin/develop`
  2. Work through the issue fully — code, tests, doc changes.
  3. Run the test suite.
  4. Run `/prep-for-pr`.
  5. Commit and push (with confirmation, per this repo's normal rule), open a PR referencing the issue (`Closes #<n>`) targeting `develop`.
  6. Remove the `ready-for-development` label once the PR is open.
  7. Report the PR URL. Leave the branch checked out — don't return to `team/<name>` until the ticket is fully merged (see `/merge-pr`'s team-slot reset step).
- **On `feat/<name>/issue-<n>` (mid-ticket):** report status — whether a PR is already open, what CI/QA said if anything, and whether it's waiting on QA or on further work — rather than claiming a new ticket.

## 4. QA role (Sky / Kit)

Find the partner Dev's open PR by branch prefix: `gh pr list --state open --json number,headRefName,url --jq '[.[] | select(.headRefName | startswith("feat/<partner>/"))]'` (lowercase partner name from the table). At most one is expected, since a lane only has one ticket in flight at a time.

- **None found:** report that Lane {A/B} has nothing to verify right now.
- **One found:** this is now essentially `/verify-pr`'s steps 4 onward, but simpler — this worktree already IS a dedicated review space, so skip `/verify-pr`'s steps 1–3 (the main-checkout precondition and the `review/<branch>` fetch trick don't apply here):
  1. `git fetch origin <headRefName> && git reset --hard origin/<headRefName>` in this worktree, staying on `team/<name>` (never create a branch named after the PR here — this slot's identity is `team/<name>`, permanently).
  2. Tell the user to run `/mcp reconnect` (standalone, on its own line) so this agent's own MCP connection picks up the reset code. Wait for confirmation.
  3. Run `/code-review` at `high` effort against `origin/develop...HEAD`.
  4. Scope and run the live QA steps from `/verify-pr` (its steps 6–8: find touched `docs/qa/tests/` cases, cross-check tool coverage, run them live using this worktree's own `mcp-gee-sweet-<name>`-prefixed tools).
  5. Record `**Result**` entries for every case actually run.
  6. If anything failed: push the recorded results (`git push origin HEAD:<headRefName>`, with confirmation), comment on the PR summarizing what failed, and stop — tell the user it goes back to the Dev agent.
  7. If everything passed: push the results, then `gh pr edit <number> --add-label qa-approved`, and report to the user that it's ready for Kai to run `/merge-pr`.
