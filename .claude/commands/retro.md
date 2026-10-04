Process the friction and findings from the unit of work you just finished — a PR reviewed, a ticket implemented, a release cut, a doc pass, an orchestration cycle — into a durable form, so the next session in your seat doesn't rediscover the same thing from scratch.

**Only the user starts a retro.** Never run this on your own initiative. When you finish a piece of work and hit friction worth preserving, end your report with one line naming it and offering `/retro`; if the pass was clean, say nothing. Once the user says go, that approval covers committing, pushing, and opening the PR for this retro's own `doc/<role>/retro-<date>` branch; don't ask again for those steps. This is a deliberate exception to the standing ask-before-commit/push/PR rule, and it stops there: merging stays with Bob, and a ticket filed with `gh issue create` still gets its usual preview-and-ask first. (2026-09-27: three lanes each ran a retro nobody asked for within 15 minutes, #831/#832/#834. The user's objection was that retros were performed unasked, not that PRs were opened for them.)

**Only process real findings from the work you just did.** Don't invent hypothetical friction to fill out the exercise, and don't pad with things this file already tells you to do routinely (e.g. a QA coverage gap that blocks the PR itself — that's handled inline by `qa.md`/`verify-pr.md`, not a retro item). If nothing survives that filter, say so and stop.

## The two dispositions

For each real finding, decide which bucket it belongs in — most sessions will have some of both:

**Ticket** — a durable product or system finding that needs to be scheduled, prioritized, or fixed by someone later: a bug, a coverage gap, a design inconsistency, tech debt. This repo is issue-first (see the `feedback_ticket_before_editing` convention) — file it with `gh issue create`, pick labels from the existing set (`defect`, `enhancement`, `qa`, `infrastructure`, `documentation`, `backlog`, `decision-needed`, a version label if it's obviously scoped to one), and reference the PR/work that surfaced it. Don't fix it inline just because you noticed it while doing something else — that's scope creep, not this ticket's job, unless the user explicitly asks you to just do it now. Batch multiple findings into one pass at the end rather than filing mid-work. Roadmap grooming (folding the new issue into `docs/roadmap.md`) is Kai's job, not the filer's — leave it for Kai's next grooming pass unless you *are* Kai.

A finding about the PR you just reviewed or implemented clears the same bar as a review finding: one of the four bars in `qa.md` step 3, named in the ticket body as `bar N: <reason>`, with the `from-review` label. If that PR is still open, send the finding back to it instead of filing. If it's merged, there's nothing left to send back to: when a failure was actually observed, file it as `defect` with `from-review` and give "merged" as the reason. Otherwise, if it clears no bar, record it in the retro's report to the user (and in the retro PR's description, if there is one) and don't file it.

Also before filing, search for an existing ticket: `gh issue list --state open --search "<function or file name> <symptom>"`. Another lane or an earlier round may already have filed it. If an open issue describes the same defect (same code path and same failure, not just a shared keyword), comment the new evidence there instead of filing a duplicate.

Before filing, triage defect vs. hardening honestly: has a failure actually been observed (a wrong result, a crash, a silently-corrupted state), or are you flagging an input this code merely doesn't validate yet? The latter is real and worth a ticket, but label and word it as hardening, not as a confirmed defect — don't let "I found something" inflate its severity.

**Command decision** — operational knowledge that should change how the *next* session in this same seat behaves: a process gap, a doc gap, a technique that worked (or didn't), a fixture gotcha, a missing step in a skill file. This isn't roadmap-worthy scope, so skip the ticket — edit the relevant process/skill doc directly, right now, and say what you changed. Examples already in this repo: `docs/qa/run.md`'s Playwright limitations list, `docs/qa/retro-v0.8.0.md`'s action items, a role file's own process fixes.

This same command-vs-memory distinction applies any time feedback lands, not just at a `/retro` pass — see `CLAUDE.md`'s "Procedural feedback" note: a repeatable workflow correction belongs in the command file it's about, not in a memory entry that competes with it.

Every command-decision edit still needs a PR — it never lands straight on `develop`, no matter how small: commit it on its own short branch (`doc/<role>/retro-<date>`), open a PR, and get `prompt-qa-approved` from Bob before it merges. See `.claude/team-roles/bob.md` for why and the full flow.

## Your role's details

Read the `## Retro` section in your own role file (`.claude/team-roles/<role>.md`) for the friction categories specific to your seat and which docs each maps to. If that section doesn't exist yet, you're the first to run this from that seat — add one, following the pattern already written for the other roles, and say so in your report.

## Report

State what you filed (issue numbers + one-line summaries) and what you changed directly (files + one-line summaries). Don't just say "processed 3 findings" — name them, the same way you'd report any other work.
