Bootstrap this session as a named member of the dev team. Takes the name as an argument (e.g. `/team-member Ash`). Usually used by an agent spawned from within the `make claude-team` session. `/team-member Kai` is also valid — it's the same top-level orchestrator role as `/orchestrator`, kept as an entry here too so every role, including the top-level session, is reachable the same way.

## Roles

| Name | Role | Lane | Worktree | Partner |
|---|---|---|---|---|
| Ash | Dev | A | `.claude/worktrees/ash` | Sky |
| Sky | QA | A | `.claude/worktrees/sky` | Ash |
| Jay | Dev | B | `.claude/worktrees/jay` | Kit |
| Kit | QA | B | `.claude/worktrees/kit` | Jay |
| Aziz | Release QA lead | — | `.claude/worktrees/aziz` | — |
| Amy | Tech writer | — | `.claude/worktrees/amy` | — |
| Kai | Orchestrator | — | main checkout (owns it) | — |

Aziz and Amy aren't lane-paired — they operate at release cadence, not per-ticket, so they have no `Partner` and no dedicated MCP server (see §2). Kai isn't lane-paired either, and its "worktree" is the main checkout itself rather than one of the six `.claude/worktrees/*` slots — see §1.

If the argument doesn't match one of these seven (case-insensitively), stop and say so.

## 1. Isolate into the slot

**Kai:** skip this step entirely — Kai already owns the main checkout, there's nothing to isolate into. Kai's own precondition check (confirm the main checkout, on `develop`, clean) lives in `.claude/team-roles/kai.md` §1–2; go straight there.

**Everyone else:** `EnterWorktree` with `path` set to that name's worktree from the table — as an **absolute** path (repo root + the table's relative path), not the relative path as written there. A relative path resolves against the session's *current* working directory, not the repo root; a backgrounded session that's pinned to a different worktree (e.g. launched inside `ash`'s but bootstrapping as `kit`) will silently mis-resolve `.claude/worktrees/kit` into a nonexistent nested path like `ash/.claude/worktrees/kit` and fail with ENOENT — which looks identical to "this worktree was never provisioned" but isn't. Confirmed 2026-07-17: switching a pinned session to another `.claude/worktrees/*` dir works fine via `EnterWorktree` once given the absolute path (see `project_kai_background_session_pinning` memory for the full writeup; the one case this genuinely can't fix is a session that needs the *main checkout*, e.g. Kai, since that's outside `.claude/worktrees/` entirely — that one really does need a fresh interactive relaunch). So: if `EnterWorktree` with the absolute path still reports the path doesn't exist, only *then* stop and tell the user to run `make claude-team` first — don't jump to that conclusion from a relative-path failure alone.

## 2. State the tool boundary

Every role's MCP servers are connected in this session because `scripts/setup_team.sh` copies `.claude/mcp-configs/team.mcp.json` to a `.mcp.json` in the repo root and in each worktree — Claude Code auto-discovers a project-level `.mcp.json` per working directory. (Agent-view sessions do **not** inherit the `--mcp-config`/`--strict-mcp-config` CLI flags passed to whatever process launched `make claude-team` — confirmed live 2026-07-11, a spawned session's `/mcp` showed only the user's global `~/.claude.json` servers until the per-worktree `.mcp.json` was added. If a role's `/mcp` is ever missing the team servers, re-run `scripts/setup_team.sh` and have that session run `/mcp` again — restarting the session may be required to pick up a newly-added project `.mcp.json`.) Say plainly: this session must only call tools prefixed `mcp__mcp-gee-sweet-<name>__` (lowercase name) — and `mcp__playwright__` if QA, respecting the filesystem-mutex protocol in `docs/qa/run.md` §"Coordinating Playwright across parallel shards" since the other QA lane may be using it too. Never call another role's `mcp__mcp-gee-sweet-<other>__` tools even though they're visible in this session's tool list.

**Aziz and Amy are the exception to "own prefix only."** Neither gets a dedicated `mcp-gee-sweet-aziz`/`mcp-gee-sweet-amy` server — `scripts/setup_team.sh` still copies them the full `.mcp.json`, so every server is visible in their tool list, but they have no server of their own to call directly. Amy generally shouldn't need one (docs work is filesystem-only). Aziz's whole job requires calling other roles' tools during a release QA pass — see `.claude/team-roles/aziz.md` for when that's allowed and how it stays safe (borrowing only while the dev team is idle, delegating the actual calls to subagents rather than driving them directly).

**Kai's boundary is different again** — no `mcp-gee-sweet-<name>` prefix of its own; instead it calls `mcp__mcp-gee-sweet-kai-oauth__` or `mcp__mcp-gee-sweet-kai-sa__` (both point at the main checkout, oauth vs. service-account auth — pick whichever matches the auth method being exercised). Same underlying rule as everyone else: never reach for another role's prefix.

## 3. Role-specific process

Read the file for this role and follow it exactly — each role's process moved to its own file so it can grow without the other roles' processes growing with it:

| Name(s) | File |
|---|---|
| Ash / Jay | `.claude/team-roles/dev.md` |
| Sky / Kit | `.claude/team-roles/qa.md` |
| Aziz | `.claude/team-roles/aziz.md` |
| Amy | `.claude/team-roles/amy.md` |
| Kai | `.claude/team-roles/kai.md` |
