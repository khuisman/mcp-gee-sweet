# Decision: Named Dev-Team Roles with Isolated Worktrees + MCP Slots (issue #290)

**Date:** 2026-07-11
**Snapshot commit:** branch `feat/dev-team`

## Background

The existing `/orchestrator` workflow puts all post-implementation work — code review, live QA against real Google APIs, and merging — on one session (the main checkout), because live MCP tool calls only ever reach whatever code is checked out at a fixed filesystem path. `/verify-pr` works around this by fetching a worker's PR branch into a locally-named `review/<branch>` in the main checkout, testing it there, then pushing results back via a refspec. That workaround exists solely because nothing else can reach the branch's code live.

The goal here is to let review/QA happen in its own dedicated, isolated worktree — in parallel, without occupying the main checkout — by giving each role its own persistent worktree and its own MCP server connection.

## Decisions

### 1. Five named roles, not generic "worker"/"reviewer" labels

Kai (Orchestrator, main checkout), and two lanes each pairing a Dev and a QA agent: Ash/Sky (Lane A), Jay/Kit (Lane B). Names are short (≤3 characters), gender-neutral placeholders — arbitrary identity tags for the worktree/branch/MCP-key naming scheme, not meant to imply anything beyond "which slot." Orchestrator sheds code review and live QA to the QA role; QA absorbs review, live testing, re-review, and sign-off. A lane runs at most one ticket at a time, which is what makes PR-to-lane routing unambiguous (decision 4).

### 2. Persistent slots, not per-ticket worktrees

The existing `/start-worktree`/`/next-issue` pattern creates a fresh worktree per ticket, removed after merge. Rejected for the four team roles: recreating a worktree (and its MCP server's `--directory`) every ticket would mean regenerating the MCP config on every cycle, and the whole point of naming these roles is a small fixed set of slots a human can track by name. Instead Ash/Sky/Jay/Kit each get one worktree that lives for the project's lifetime, resting on its own `team/<name>` branch and cycling: idle (`team/<name>`, at `origin/develop`) → active (checked out to a ticket/PR branch) → idle again after merge. `develop` itself is never checked out in a team-slot worktree — it's always checked out in the main checkout, so no other worktree can share that branch name.

### 3. One combined MCP config, not one config per role

The original framing assumed launching each role as its own `claude --mcp-config <role>.json --strict-mcp-config` process. Reconsidered once the actual usage pattern was clarified: this is driven from Claude Code's Agent View — one top-level `claude` invocation, then agents spawned from within it. A spawned agent always inherits whatever MCP servers its parent connected to at *its own* start; nothing spawned later can add a new connection, and there is no way to scope an already-running session down to a subset of its servers per-subagent. So five separate strict-mode processes doesn't fit — instead `.claude/mcp-configs/team.mcp.json` defines all six server entries (four role servers, Kai's own oauth/service-account pair, one shared `playwright`) side by side, loaded once. Every spawned agent can see every role's tools; the boundary is `/team-member` instructing each agent which prefix is its own, not a process wall. Accepted as a known tradeoff — worth revisiting (e.g. per-agent permission allow-lists) only if that discipline proves leaky in practice.

### 4. Branch-name prefix for lane routing, not a GitHub label or project board

Dev branches are named `feat/<devname>/issue-<n>` (extending the existing `feat/issue-<n>` convention with a name prefix). A QA agent finds its paired Dev's open PR with `gh pr list --state open --json headRefName --jq 'select(.headRefName | startswith("feat/<partner>/"))'`. Considered a `lane:a`/`lane:b` GitHub label instead — rejected as an extra piece of state to keep in sync for no real benefit, since the branch name already carries the same information and a lane only ever has one ticket in flight at a time (so the lookup is never ambiguous). The new `qa-approved` label *is* still used, but for sign-off state, not routing — routing needs no state at all beyond the branch name.

### 5. `/cleanup-worktrees` must never touch the four team-slot worktrees

Its existing rule — remove any worktree whose branch has a merged PR and is clean — would otherwise delete a team-slot worktree the moment its first ticket's PR merges, since a just-merged `feat/ash/issue-<n>` branch matches exactly that rule. Two changes: `/merge-pr`'s cleanup step now resets a team-slot worktree back to `team/<name>` in place (rather than removing the worktree) as soon as its PR merges, and `/cleanup-worktrees` itself unconditionally skips the four team-slot paths regardless of branch/PR state, as a second line of defense.

## When to Re-evaluate

- If the shared-MCP-config tool boundary (decision 3) turns out to be leaky in practice (an agent calling another role's tools by mistake), look at per-agent permission allow-lists rather than reintroducing per-role processes — Agent View's constraints haven't changed, so separate processes still won't fit the workflow.
- If a third lane is ever added, the branch-prefix routing (decision 4) and the role table in `/team-member` both need a new row — there's no dynamic registry, this is a small hardcoded set by design.
- If dev-team ticket volume grows past what two lanes can absorb, revisit whether Kai's own ticket-triage lane-assignment logic (in `/orchestrator`) still scales as a manual check, or needs to become closer to a real scheduler.
