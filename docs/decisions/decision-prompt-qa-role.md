# Decision: Prompt QA Role (Bob) and a Gated Self-Improvement Process

**Date:** 2026-07-21
**Snapshot commit:** branch `develop`

## Background

Every team role can edit its own process file as it learns friction (`/retro`'s "command decision" path) — deliberate, since continuous self-correction from real incidents beats a static prompt nobody revisits. As of 2026-07-18, edits to team-process/instruction files (`CLAUDE.md`, `.claude/team-roles/*.md`, `.claude/commands/*.md`, `docs/qa/run.md`/`setup.md`) could additionally skip the PR/CI review step entirely and push straight to `develop`, gated only by a per-push human confirmation.

That no-review path is what let a real incident compound instead of getting caught early: `qa.md` accumulated an "inline fix for narrow, low-risk findings" exception (PR #353) starting from a single conversational grant, written into the role file in language soft enough ("narrow," "low-risk") that two later sessions (PR #385, #386) each independently reasoned their way to standing on it for progressively larger fixes — until the user had to call a full stop and the exception was removed outright. Nothing in the previous process checked the *wording* of a self-authored permission grant before it landed; only whether the diff was small and about process rather than product code. A GitHub PR review would have caught this the same way code review catches an overbroad `except Exception:` — but team-process edits had been explicitly exempted from that review, on the reasoning that "it's not product code."

## Decisions

### 1. A dedicated role for prompt-craft review, not folded into an existing one

None of the existing roles has "does this wording hold up to how an LLM actually reads instructions" as its lens: Kai reviews for process-following gaps, QA/Aziz for product correctness, Amy for doc accuracy, Joy for cross-repo architecture. Bob (Senior Prompt Engineer) is a new persistent slot — same shape as Aziz/Amy/Joy: `team/bob` branch, `.claude/worktrees/bob`, no dedicated MCP server (this work is filesystem-only), not lane-paired, ad hoc/Kai-set cadence rather than per-ticket. See `.claude/team-roles/bob.md` for what he checks: permission/scope language, placement and recency effects on precedence, ambiguous referents, redundancy/bloat, and cross-file duplication.

### 2. Team-process edits go through the same PR/label/merge machinery as product code, not new machinery

Rejected building a separate review pipeline. Team-process PRs now follow the exact shape already in use for product PRs: authoring role commits to a short branch off `develop` (`docs/<role>/retro-<date>`, a pattern already organically in use — see `doc/joy/retro-2026-07-19`, PR #383) and opens a PR; Bob reviews and applies `prompt-qa-approved` (parallel to `qa-approved`); Kai merges once the label is present, without re-doing Bob's review — the same split Kai already holds for QA-approved product PRs. This retires the 2026-07-18 direct-push grant in `dev.md`/`qa.md`.

### 3. A fast path for mechanical fixes, so the gate targets the actual risk

Not every command-decision edit is risky — most are typo fixes, stale cross-references, renumbering. Gating 100% of team-process edits behind Bob would reintroduce exactly the friction/bloat problem the user flagged (self-improvement moving too slowly, or role sessions batching real learning into rare, larger edits to avoid the overhead). Only edits that grant, widen, or restate permission/scope language, or add a new standing rule future sessions will reason from, need `prompt-qa-approved`. A mechanical fix merges the normal way, same as any small doc PR today.

### 4. Who initiates: the authoring role, not Bob and not the user

The property the user explicitly wants to keep is each participant capturing what it learned, in its own words, at the moment it's fresh — that's what makes continuous self-improvement work, and gating on Bob's live availability would kill it (most sessions don't overlap with a live Bob session). So the authoring role still commits and opens the PR immediately, same trigger as before (`/retro`'s command-decision path). Bob's review is deliberately asynchronous — the open PR *is* the release valve the user asked for: a session that hits friction mid-work commits what it learned and moves on; the fix sits reviewable whenever someone gets to it, rather than blocking the session or forcing a same-session review.

## When to Re-evaluate

- If `prompt-qa-approved` PRs pile up unreviewed for long stretches because no session bootstraps as Bob often enough, the "ad hoc, Kai-set cadence" review trigger isn't working — consider having Kai sweep for open `docs/*/retro-*` PRs as a standing step in its own orchestration pass (parallel to how Aziz sweeps merged PRs at release time), rather than relying on someone remembering to invoke Bob.
- If the mechanical-fix/permission-language line (decision 3) proves hard to call correctly in practice — sessions either over-routing trivial fixes to Bob or under-routing real permission grants around him — tighten the definition in `bob.md` with more worked examples rather than removing the fast path.
- If a second incident of the same shape (an unreviewed self-grant hardening into a standing exception) occurs *after* this process is live, that's a sign the gate itself needs strengthening (e.g. requiring `prompt-qa-approved` unconditionally, dropping the fast path) rather than a one-off wording fix.
