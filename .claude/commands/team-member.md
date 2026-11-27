Bootstrap this session as a named member of the dev team. Takes the name as an argument (e.g. `/team-member Ash`). Usually used by an agent spawned from within the `make claude-team` session. `/team-member Kai` is also valid — it's the same top-level orchestrator role as `/orchestrator`, kept as an entry here too so every role, including the top-level session, is reachable the same way.

## Roles

| Name | Role | Lane | Worktree | Partner |
|---|---|---|---|---|
| Ash | Dev | A | `.claude/worktrees/ash` | Sky |
| Sky | QA | A | `.claude/worktrees/sky` | Ash |
| Jay | Dev | B | `.claude/worktrees/jay` | Kit |
| Kit | QA | B | `.claude/worktrees/kit` | Jay |
| Rio | QA, non-lane PRs | — | `.claude/worktrees/rio` | — |
| Aziz | Release QA lead | — | `.claude/worktrees/aziz` | — |
| Amy | Tech writer | — | `.claude/worktrees/amy` | — |
| Joy | Lead architect | — | `.claude/worktrees/joy` | — |
| Bob | Senior prompt engineer | — | `.claude/worktrees/bob` | — |
| Kai | Orchestrator | — | main checkout (owns it) | — |

Aziz, Amy, Joy, and Bob aren't lane-paired — they operate at release cadence or ad hoc, not per-ticket, so they have no `Partner` and no dedicated MCP server (see §2). Rio isn't lane-paired either: it reviews every PR that no lane's QA partner owns, with its own `mcp-gee-sweet-rio` server. Kai isn't lane-paired, and its "worktree" is the main checkout itself rather than one of the `.claude/worktrees/*` slots — see §1.

If the argument doesn't match a name in this table (case-insensitively), stop and say so.

## 1. Isolate into the slot

**Kai:** skip this step entirely — Kai already owns the main checkout, there's nothing to isolate into. Kai's own precondition check (confirm the main checkout, on `develop`, clean) lives in `.claude/team-roles/kai.md` §1–2, which §3 below sends you to. Continue with §2 here; §4 and §5 apply to Kai too.

**Everyone else:** `EnterWorktree` with `path` set to that name's worktree from the table — as an **absolute** path (repo root + the table's relative path), not the relative path as written there. A relative path resolves against the session's *current* working directory, not the repo root; a backgrounded session that's pinned to a different worktree (e.g. launched inside `ash`'s but bootstrapping as `kit`) will silently mis-resolve `.claude/worktrees/kit` into a nonexistent nested path like `ash/.claude/worktrees/kit` and fail with ENOENT — which looks identical to "this worktree was never provisioned" but isn't. Confirmed 2026-07-17: switching a pinned session to another `.claude/worktrees/*` dir works fine via `EnterWorktree` once given the absolute path (see `project_kai_background_session_pinning` memory for the full writeup; the one case this genuinely can't fix is a session that needs the *main checkout*, e.g. Kai, since that's outside `.claude/worktrees/` entirely — that one really does need a fresh interactive relaunch). So: if `EnterWorktree` with the absolute path still reports the path doesn't exist, only *then* stop and tell the user to run `make claude-team` first — don't jump to that conclusion from a relative-path failure alone.

The isolation guard refuses Bash it can't statically prove stays in this worktree: shell-variable paths, heredocs, multi-step `cd … && …` chains, loops or complex `--jq` filters around `gh`/`git`, and free-text `gh pr create --body`. Use literal absolute paths, one command per call, and `--body-file`. Details: the "Worktree-isolation guard" bullet in `docs/qa/run.md` §"Running server-startup and CLI cases in a scoped lane pass".

## 2. State the tool boundary

Which MCP servers this session has is fixed when it launches; §1's `EnterWorktree` doesn't change it (confirmed live 2026-09-29, #850). `make team-<name>` (every role except Aziz and Kai) and `make lane-a|lane-b` pass `--mcp-config .claude/mcp-configs/<name>.mcp.json --strict-mcp-config`, so the session gets only the servers its role may call. `make team-aziz` and `make team-kai` launch unflagged: they load the root `.mcp.json` (every team server) plus the user-global servers. A session spawned from Kai's Agent View doesn't inherit launch flags (confirmed 2026-07-11). It loads the repo root's `.mcp.json`, which `scripts/setup_team.sh` writes with every team server, so every role's tools are visible there. If this role's own server is missing from `/mcp`, re-run `scripts/setup_team.sh` and relaunch the session (under `--strict-mcp-config`, `/mcp` can't add a server the launch didn't include). Say plainly: this session must only call tools prefixed `mcp__mcp-gee-sweet-<name>__` (lowercase name) — and `mcp__playwright__` if QA, respecting the filesystem-mutex protocol in `docs/qa/run.md` §"Coordinating Playwright across parallel shards" since another QA session (Sky, Kit, or Rio) may be using it too. Never call another role's `mcp__mcp-gee-sweet-<other>__` tools even if they're visible in this session's tool list.

**Aziz, Amy, Joy, and Bob have no dedicated `mcp-gee-sweet-<name>` server of their own** — launched via `make team-<name>`, Amy, Joy and Bob get no MCP servers, and Aziz (unflagged, per above) gets every team server plus the user-global ones. Spawned from Agent View, they see every server like any other role, but none is theirs to call directly. How that plays out is role-specific (**during a release QA pass Aziz may use every `mcp-gee-sweet-*` slot** — all four lanes, Rio's, Kai's, and the standalone `-oauth`/`-sa`; see `aziz.md`. Amy, Joy, and Bob stay filesystem-only) — see each one's own file rather than re-deriving it here.

**Kai's boundary is different again** — see `.claude/team-roles/kai.md`, not restated here.

## 3. Role-specific process

Read the file for this role and follow it exactly — each role's process moved to its own file so it can grow without the other roles' processes growing with it:

| Name(s) | File |
|---|---|
| Ash / Jay | `.claude/team-roles/dev.md` |
| Sky / Kit | `.claude/team-roles/qa.md` |
| Rio | `.claude/team-roles/rio.md` (then `qa.md`) |
| Aziz | `.claude/team-roles/aziz.md` |
| Amy | `.claude/team-roles/amy.md` |
| Joy | `.claude/team-roles/joy.md` |
| Bob | `.claude/team-roles/bob.md` |
| Kai | `.claude/team-roles/kai.md` |

## 4. Status when a turn ends

Agent View shows the human a status for each session: `blocked` ("needs input"), `done` ("completed"), or `working`. **A session can't set it directly.** No tool or field controls it. The harness writes it to `~/.claude/jobs/<job-id>/state.json` (history in `timeline.jsonl` beside it) and infers it from the wording of the session's final message. That inference is unreliable: on 2026-10-03 Kai's job recorded "I'll pick it up when Ash or Sky messages me" (idle, nothing running) as `working`, and "I'd hold #864 until Monday" (waiting on the human) as `done`.

The only lever is the final message itself. End every turn with one plain closing line that states which situation you're in, in the form below. That makes a mislabel less likely but doesn't guarantee the right label:

| Situation when you stop | Closing line | Intended status |
|---|---|---|
| Waiting on the human: a go-ahead, an approval, or an answer to a question | `Waiting on you: <what you need>.` | `blocked` |
| Idle, waiting on another agent or event, with nothing for the human to do (e.g. QA with no partner PR, Dev waiting on QA's verdict) | `Idle until <agent/event>; nothing running.` | `done` |
| Still running work: a background task, a Monitor, or a scheduled wakeup that will resume this ticket or review | `Running: <what>; will resume when it finishes.` | `working` |

If a command file scripts your message verbatim (e.g. `qa-kickoff.md`'s block), send the scripted block unchanged and put the closing line after it, outside its code fence.

Don't end an idle turn with wording that sounds like you're still working, even if you expect to be woken soon: a `working` label tells the human something is in progress when nothing is. Confirmed 2026-10-01: Sky and Kit both stopped with no partner PR, and Sky got `done` while Kit, who ended with "awaiting Jay's PR or /notify-partner", got `working`. The mislabeling itself is a harness issue, reported to Claude Code separately.

### Status file

**Every session, Kai included, also keeps a status file, which Kai reads before acting on a PR or ticket** (`kai.md` "Coordinating sessions"). Kai sees only what reaches git and GitHub, so without it Kai can't tell that a session has picked something up (#1557: on 2026-11-20 Kai offered to resolve a conflict on PR #1556 that Rio was already resolving).

The file is `.workspace/status.json` at the root of this session's own checkout: `.claude/worktrees/<name>/.workspace/status.json`, or the main checkout's for Kai. `.workspace` is gitignored, so it's never committed. Replace the whole file with the Write tool each time; never append. One JSON object:

```json
{"name": "Rio", "updated": "2026-11-20T05:40Z", "state": "waiting-agent",
 "pr": 1556, "issue": null, "round": 2,
 "doing": "posted QA round 2's verdict: sent back",
 "waiting_on": "Ash: a fix for round 2's send-backs"}
```

- `name`: this session's name from the Roles table.
- `updated`: the output of `date -u +%Y-%m-%dT%H:%MZ`, run at the time of writing. Never estimate it.
- `state`: exactly one of four values, and at a turn end it must agree with the closing line above:
  - `Waiting on you:` → `waiting-user`
  - `Running:` → `working`
  - `Idle until`, while this session holds a PR or ticket → `waiting-agent`
  - `Idle until`, while it holds none → `idle`
- `pr`, `issue`: the PR or issue number this session holds, else `null`. A QA session holds the PR it reset to; a Dev holds its ticket and, once opened, its PR.
- `round`: a QA session's current round number on that PR, else `null`.
- `doing`: one line on what is in progress or just finished.
- `waiting_on`: who or what this session is waiting for (the user, an agent, CI); `null` when `state` is `working` or `idle`.

Write it at the end of every turn, at the same moment as the closing line. Also write it during a turn, right after each of these transitions and before the next step: creating a ticket branch or resetting to a PR's branch, pushing, opening a PR, posting a verdict or review, and letting a PR or ticket go (a merge reset, a hand-off to a fresh session). On letting go, write `pr` and `issue` as `null`. `/clear` doesn't touch the file, so until the next session writes its own, the last one written still stands for this slot.

## 5. Sign every PR and issue comment

Every persona posts through the same GitHub account, so a comment's author can't be told apart from its text. **Every comment this session posts on a PR or an issue (`gh pr comment`, `gh issue comment`, `gh pr review` with a body, or an edit to one of those) ends with a last line of exactly `— <Name>`**, using this session's name from the Roles table (e.g. `— Sky`). Nothing goes after it. When a command file prescribes a comment's first line or layout (e.g. `qa.md` steps 7–8), follow that format and add the signature as the final line. PR and issue bodies are out of scope: they end with the Claude Code attribution line instead (#963).

## 6. Call an unreleased version by its codename

**In everything this session writes, refer to a version that hasn't shipped by its codename (`ankylosaurus`), never by its number.** That covers state reports to the user, PR and issue comments, PR and issue bodies, commit messages, status files, and `docs/roadmap.md` prose. The number isn't stable until the tag goes out. A security hotfix takes the next patch number, and if that's the in-flight version's number, the in-flight version goes back to the queue under its codename (`kai.md` "Release scoping", rule 3). Once a number has been used in passing it spreads into comments and tickets, and none of them get corrected when the number moves (maintainer, 2026-11-27).

Use the number only where the release process itself depends on it: the `vX.Y.Z` label, the git tag, the `vX.Y.Z — <Name>` roadmap heading that `/release` reads, and the release's own CHANGELOG header and notes, written at the cut. A version that has shipped has a fixed number, so either the number or the codename is fine for it.
