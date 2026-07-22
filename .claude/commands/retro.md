Process the friction and findings from the unit of work you just finished — a PR reviewed, a ticket implemented, a release cut, a doc pass, an orchestration cycle — into a durable form, so the next session in your seat doesn't rediscover the same thing from scratch.

This is discretionary, not a gate. No role's process file requires running this — invoke it when you actually hit friction worth preserving, skip it when a pass was clean. Symmetric with `/team-member`/`/next-issue` on the other end of a work cycle: those are prompts you may follow to *pick up* work; this is the one for *closing out* a piece of it.

**Only process real findings from the work you just did.** Don't invent hypothetical friction to fill out the exercise, and don't pad with things this file already tells you to do routinely (e.g. a QA coverage gap that blocks the PR itself — that's handled inline by `qa.md`/`verify-pr.md`, not a retro item). If nothing survives that filter, say so and stop.

## The two dispositions

For each real finding, decide which bucket it belongs in — most sessions will have some of both:

**Ticket** — a durable product or system finding that needs to be scheduled, prioritized, or fixed by someone later: a bug, a coverage gap, a design inconsistency, tech debt. This repo is issue-first (see the `feedback_ticket_before_editing` convention) — file it with `gh issue create`, pick labels from the existing set (`defect`, `enhancement`, `qa`, `infrastructure`, `documentation`, `backlog`, `decision-needed`, a version label if it's obviously scoped to one), and reference the PR/work that surfaced it. Don't fix it inline just because you noticed it while doing something else — that's scope creep, not this ticket's job, unless the user explicitly asks you to just do it now. Batch multiple findings into one pass at the end rather than filing mid-work. Roadmap grooming (folding the new issue into `docs/roadmap.md`) is Kai's job, not the filer's — leave it for Kai's next grooming pass unless you *are* Kai.

Before filing, triage defect vs. hardening honestly: has a failure actually been observed (a wrong result, a crash, a silently-corrupted state), or are you flagging an input this code merely doesn't validate yet? The latter is real and worth a ticket, but label and word it as hardening, not as a confirmed defect — don't let "I found something" inflate its severity.

**Command decision** — operational knowledge that should change how the *next* session in this same seat behaves: a process gap, a doc gap, a technique that worked (or didn't), a fixture gotcha, a missing step in a skill file. This isn't roadmap-worthy scope, so skip the ticket — edit the relevant process/skill doc directly, right now, and say what you changed. Examples already in this repo: `docs/qa/run.md`'s Playwright limitations list, `docs/qa/retro-v0.8.0.md`'s action items, a role file's own process fixes.

Every command-decision edit still needs a PR — it never lands straight on `develop`, no matter how small: commit it on its own short branch (`doc/<role>/retro-<date>`), open a PR, and get `prompt-qa-approved` from Bob before it merges. See `.claude/team-roles/bob.md` for why and the full flow.

## Your role's details

Read the `## Retro` section in your own role file (`.claude/team-roles/<role>.md`) for the friction categories specific to your seat and which docs each maps to. If that section doesn't exist yet, you're the first to run this from that seat — add one, following the pattern already written for the other roles, and say so in your report.

## Report

State what you filed (issue numbers + one-line summaries) and what you changed directly (files + one-line summaries). Don't just say "processed 3 findings" — name them, the same way you'd report any other work.
