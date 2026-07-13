# Decision: Release QA Lead and Tech Writer Roles (issue #295)

**Date:** 2026-07-12
**Snapshot commit:** branch `feat/dev-team-2/issue-295`

## Background

[Dev-Team Roles](decision-dev-team.md) gave Ash/Sky (Lane A) and Jay/Kit (Lane B) persistent worktrees for per-ticket Dev/QA work. Two responsibilities don't fit that per-ticket shape: reviewing an entire release for correctness and documentation quality before it ships, and keeping documentation accurate/friendly/comprehensive on an ongoing basis. Both need their own isolated worktree to work independently of the two lanes, per the same rationale as decision-dev-team's decision 2.

## Decisions

### 1. Two more persistent slots, not a repurposed lane

Aziz (release QA lead) and Amy (tech writer) each get a `team/<name>` worktree slot exactly like Ash/Sky/Jay/Kit — added to `scripts/setup_team.sh`'s worktree-provisioning loop and to the persistent-slot exclusion lists in `/merge-pr` and `/cleanup-worktrees` (now six names, not four). They are not a third lane: neither is Dev/QA-paired, both work at release or on-demand cadence rather than one-ticket-at-a-time, and the role table in `/team-member` reflects that with `—` for Lane and Partner.

### 2. No dedicated MCP server for Aziz or Amy

`scripts/setup_team.sh`'s `role_server` generation loop stays at four entries (Ash/Sky/Jay/Kit); Aziz and Amy are added to worktree provisioning only, not to that loop — no new `mcp-gee-sweet-aziz`/`mcp-gee-sweet-amy` server process starts. Both still receive the same combined `.mcp.json` copy every slot gets (per decision-dev-team's decision 3), so every server is visible in their tool list even though neither owns one. Amy's work is filesystem-only and doesn't need one. Aziz's live-QA work needs to call Sky's and Kit's tools directly (see decision 3) — giving him a server of his own would just be a second, redundant path to the same underlying MCP process each already runs, and the borrowed connection has the same in-session `.mcp.json` guarantee, so it costs nothing to skip.

### 3. Aziz borrows Sky's/Kit's slots via `Agent`-tool subagents, not a new Playwright/API identity

Live release QA needs the same real Google API + Playwright access Sky/Kit already have. Considered provisioning Aziz a third authenticated identity — rejected as unnecessary duplication of credentials and Playwright browser state for something that only runs periodically, at release time, when the dev team is idle by design (the user's explicit precondition: dev-team work and release QA never run concurrently). Instead Aziz resets Sky's and Kit's worktrees to `origin/develop` before a pass, then spawns `Agent`-tool subagents — true in-session subagents, which inherit whatever MCP servers their parent (Aziz's own session) is already connected to, per the established distinction from decision-dev-team's decision 3 fallout: this is different from an Agent-View "switch session" spawn, which does *not* inherit anything (confirmed live 2026-07-11, see `/team-member` §2). Each subagent is told which slot prefix (`mcp-gee-sweet-sky` or `mcp-gee-sweet-kit`) to call through and which domain/test file to run, mirroring the v0.8.1 QA pass's four-parallel-domain-shard structure. Subagents report structured PASS/FAIL back rather than editing any tracked file themselves — only Aziz, in his own worktree, writes the inline `**Result**` annotations, the aggregate results file, and the release sign-off doc, so two subagents running against Sky's and Kit's separately-checked-out worktrees never produce competing diffs to reconcile.

### 4. QA-tier decision reuses the existing scoped-gating audit, made explicitly Aziz's call

`docs/qa/runs/README.md` already documents a source-diff audit (enumerate commits, classify behavior-change vs. pure-refactor, map to domains, decide structural vs. non-structural) for when Full Regression can be substituted with Smoke + targeted Domain runs. Rather than inventing a separate process for "what does Aziz decide for a minor release," `/team-member`'s Aziz section points directly at that existing process and treats it as Aziz's responsibility to run and document per release, not a per-release ad hoc judgment call by whoever happens to be doing the release.

### 5. Existing Playwright lockfile and no-fabricated-results conventions carry over unchanged

Both were already established (`docs/qa/run.md` §"Coordinating Playwright across parallel shards"; the no-fabricated-results and repeat-live-verification disciplines from prior QA passes) and needed no new design — Aziz's subagents follow them exactly as any QA session would. Formalized in `/team-member` §5 rather than restated in a new doc.

### 6. Amy claims work via a `documentation` label, mirroring `ready-for-development`

Reuses the pre-existing `documentation` GitHub label rather than introducing a new one. Amy's PRs are not gated by `qa-approved` (that gate stays scoped to the four dev-lane names per decision-dev-team's decision 4) — normal `/merge-pr` review applies, since docs-only changes don't carry the same live-API regression risk that motivated the QA-approval gate for Dev-lane code.

## When to Re-evaluate

- If Aziz's borrowed-worktree model proves leaky (e.g. a subagent edits a tracked file despite instructions, or two shards collide on the same Playwright lock more than the backoff-retry tolerates), reconsider giving Aziz a dedicated Playwright/API identity after all — decision 3's rejection was based on avoided duplication for an infrequent workflow, not a hard constraint.
- If Amy's doc-quality work starts needing live tool verification (not just static accuracy checks), reconsider whether she needs read-only access to a slot's MCP tools rather than staying filesystem-only (decision 2).
