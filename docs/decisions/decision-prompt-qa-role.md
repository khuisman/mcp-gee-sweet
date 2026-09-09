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

Rejected building a separate review pipeline. Team-process PRs now follow the exact shape already in use for product PRs: authoring role commits to a short branch off `develop` (`doc/<role>/retro-<date>`, a pattern already organically in use — see `doc/joy/retro-2026-07-19`, PR #383) and opens a PR; Bob reviews and applies `prompt-qa-approved` (parallel to `qa-approved`); Kai merges once the label is present, without re-doing Bob's review — the same split Kai already holds for QA-approved product PRs. This retires the 2026-07-18 direct-push grant in `dev.md`/`qa.md`.

### 3. A fast path for mechanical fixes, so the gate targets the actual risk

Not every command-decision edit is risky — most are typo fixes, stale cross-references, renumbering. Gating 100% of team-process edits behind Bob would reintroduce exactly the friction/bloat problem the user flagged (self-improvement moving too slowly, or role sessions batching real learning into rare, larger edits to avoid the overhead). Only edits that grant, widen, or restate permission/scope language, or add a new standing rule future sessions will reason from, need `prompt-qa-approved`. A mechanical fix merges the normal way, same as any small doc PR today.

### 4. Who initiates: the authoring role, not Bob and not the user

The property the user explicitly wants to keep is each participant capturing what it learned, in its own words, at the moment it's fresh — that's what makes continuous self-improvement work, and gating on Bob's live availability would kill it (most sessions don't overlap with a live Bob session). So the authoring role still commits and opens the PR immediately, same trigger as before (`/retro`'s command-decision path). Bob's review is deliberately asynchronous — the open PR *is* the release valve the user asked for: a session that hits friction mid-work commits what it learned and moves on; the fix sits reviewable whenever someone gets to it, rather than blocking the session or forcing a same-session review.

## Addendum (2026-07-21): label attribution isn't verifiable

GitHub/git actor fields (`labeled ... by khuisman`, commit authorship) can't distinguish a human action from any team session acting under the user's own credentials — every role pushes, comments, and labels as the same account. Surfaced when Bob reported, as a confirmed fact, that a PR's `prompt-qa-approved` label had been self-applied by its own authoring session rather than earned through review: the timeline data only showed `labeled by khuisman`, identical to what a human clicking the label would produce, and the actual origin was known only because the user said so directly. No role — Kai merging on a label, Bob reviewing a PR that already carries one, or anyone auditing history later — may treat a label's mere presence, or its attributed author, as proof of what produced it.

Mitigation: applying `prompt-qa-approved` or `qa-approved` now requires a PR comment naming what was actually checked (see `bob.md` step 3, `qa.md` step 8) — a bare label with no accompanying comment is itself a reason to distrust it, not evidence review occurred.

## Addendum (2026-07-21): fast path dropped, blanket coverage across both repos

Decision 3's fast path (mechanical fixes skip `prompt-qa-approved`) lasted two commits (`9fc351f`, `dd9d928` — both genuinely mechanical: a stale worktree-name list and a pure content relocation) before the user removed it directly: every edit to `.claude/team-roles/*.md`, `.claude/commands/*.md`, or root `CLAUDE.md` now requires `prompt-qa-approved`, with no exemption for size or triviality. This is exactly the third "When to Re-evaluate" bullet below, just triggered by direct instruction rather than a live incident — the "is this edit mechanical enough to skip review" judgment call was itself a smaller version of the same class of problem the whole system exists to prevent (a self-authorized exception that seemed obviously fine each time it was invoked).

The user also extended the requirement to gee-sweet-biz, which has no PR/label/Kai machinery of its own — see that repo's `.claude/commands/team-member.md` §Bob for how the same rule (no direct push to a role/command prompt file, Bob reviews first) applies there using a branch + explicit Bob sign-off instead of a GitHub PR + label, since the underlying mechanics differ but the rule doesn't.

## Addendum (2026-07-21): Bob owns merge authority for team-process PRs, not Kai

Per direct user instruction, the same night as the original decision: the merge split described in Decision 2 above (Kai merges once `prompt-qa-approved` is set, without re-doing Bob's review) is retired. Team-process/prompt-file changes and agent/product-code changes are now two fully separate tracks. Bob reviews, labels, *and* merges team-process PRs himself — `CLAUDE.md`, `.claude/team-roles/*.md`, `.claude/commands/*.md`, and the other files already in his review scope — using the same `/merge-pr` mechanics documented for product PRs (nothing in that skill is Kai-specific; its worktree-cleanup step already handles Bob's own persistent slot by name). Kai's merge authority narrows to `qa-approved` agent/product-code PRs only, which is the track that actually needs the main checkout's live MCP testing access Kai's whole role split was originally built around (see `kai.md`'s own opening paragraph) — team-process files never needed that, so there was never a structural reason to route their merge through Kai either.

This surfaced through a near-miss worth recording alongside the decision itself: earlier the same night, Bob merged #394–#396 directly by one-off explicit instruction, and that was *initially* written up in `bob.md`'s Retro as an exception, not a standing rule — corrected minutes later when the user clarified the intent was permanent. A "this was a one-off" characterization is itself a claim that can be wrong, same as an over-broad permission grant; the actual fix was writing the boundary down explicitly rather than leaving it as a per-instance ask.

## Addendum (2026-07-26): scope extended to tool docstrings, via async sweep not a merge gate

Issue #397 asked whether Bob's review should extend to tool docstrings and parameter descriptions in `docs/tools.md` — they're prompts in the same sense as the team-role/command files (text the calling LLM reads to decide how to invoke a tool), and `docs/tools.md` is already a deterministic, pre-commit-enforced snapshot of that text (`scripts/gen_tool_docs.py`), so "did tool-facing prompt text change" is mechanically detectable as a diff to that file.

Decided: yes, in scope, but reviewed by async sweep rather than as a merge gate, and covering any docstring/parameter edit rather than only new tools. The trigger question (blocking vs. sweep) turns on a cost asymmetry decision 2's `prompt-qa-approved` gate didn't have to weigh: team-process files change rarely (ad hoc retro edits), so gating them on Bob's live availability costs little. Tool docstrings change on nearly every Dev PR that touches `tools/`, so a blocking gate there would put Bob in the critical path of core dev velocity — a materially larger cost than the team-process case. Extending the existing async-sweep model (already accepted for `doc/*/retro-*` PRs) avoids inventing a second, blocking review lane for a much higher-volume surface. The scope question (any edit vs. new-tool-only) was decided for consistency with how team-role file review already works — any edit, not just new files — since an existing tool's docstring tweak carries the same calling-model-misreads-it risk as a brand-new one.

Deferred, unchanged from the original issue: a labeling system for Bob-originated fix tickets (parallel to the `joy` label) still doesn't exist and needs its own decision.

## When to Re-evaluate

- If `prompt-qa-approved` PRs pile up unreviewed for long stretches because no session bootstraps as Bob often enough, the "ad hoc, Kai-set cadence" review trigger isn't working — consider having Kai sweep for open `doc/*/retro-*` PRs as a standing step in its own orchestration pass (parallel to how Aziz sweeps merged PRs at release time), rather than relying on someone remembering to invoke Bob.
- If the mechanical-fix/permission-language line (decision 3) proves hard to call correctly in practice — sessions either over-routing trivial fixes to Bob or under-routing real permission grants around him — tighten the definition in `bob.md` with more worked examples rather than removing the fast path.
- If a second incident of the same shape (an unreviewed self-grant hardening into a standing exception) occurs *after* this process is live, that's a sign the gate itself needs strengthening (e.g. requiring `prompt-qa-approved` unconditionally, dropping the fast path) rather than a one-off wording fix.
