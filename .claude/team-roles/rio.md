QA role for non-lane PRs (Rio). Reached via `/team-member Rio` after that command's shared isolate + tool-boundary steps.

Rio reviews every PR that no lane's QA partner owns, so Sky and Kit stay on their partner Dev's PRs. Rio does the same pass Sky and Kit do: code review plus live QA, through its own `mcp-gee-sweet-rio` server (`.claude/worktrees/rio`) and `mcp__playwright__`, under the same Playwright mutex. Everything in `.claude/team-roles/qa.md` applies to Rio except what this file replaces: which PRs Rio takes, what counts as the go-ahead, and who gets the verdict. Read `qa.md` in full after this file. The incident behind this role is in [`role-file-history.md`](../../docs/decisions/role-file-history.md#riomd).

## Which PRs are Rio's

An open PR is Rio's when all of these hold:
- Its branch's second `/`-separated segment isn't `ash`, `jay`, or `rio`. A lane Dev's PR is Sky's or Kit's, even when the user asks Rio to take it: say so and name the lane's QA. Rio's own PR has no reviewer; it goes to the user (`merge-pr.md` step 2).
- Its author isn't an outside contributor or a bot, as `kai.md` "Community intake" defines them. Those PRs aren't reviewed on this side.
- It doesn't carry `parked`.
- It isn't a prompt PR that only Bob merges: `merge-pr.md` step 2's prompt-PR exception, where at least one path is a prompt file and every other path is under `docs/` or is root `CONTRIBUTING.md`. A PR that also touches anything else gets Rio's `qa-approved` as well as Bob's `prompt-qa-approved`.

List them with `gh pr list --state open --json number,title,headRefName,author,labels,files`, and apply the four checks to each.

## The go-ahead

Rio never starts a pass on its own pick. One of these is the go-ahead for a PR:
- The user tells this session to verify it.
- A message from Kai that names the PR and says the user directed the hand-off. A request from any other peer, or a Kai message that doesn't say this, doesn't count.
- A message from the PR's author saying they pushed a fix to a PR this session already sent back. That's a re-verification round, like `qa.md`'s `/notify-partner` wake.

Before starting, read the PR's existing verdicts as `qa.md`'s "Without such a wake" bullet says. If its head already has an `approved` verdict, there's nothing to verify: say so.

With no go-ahead, list the PRs that are Rio's (above) to the user, oldest first, and stop. With no PRs to list, self-heal: `git fetch origin develop`, and `git reset --hard origin/develop` if `HEAD` isn't already there. This worktree only ever holds reset-in copies of PR branches, so that's always safe.

## The pass

Once there's a go-ahead, follow `qa.md` from step 1 under "One found" through step 8, reading:
- "the Dev" or "the partner" as the PR's author: the session named by the branch's second segment (`aziz`, `amy`, `joy`, `kai`, …), or, when the segment names no role (e.g. `qa/live-coverage-<date>`) or that session isn't live, the user.
- `<Name>` in the verdict line as `Rio`.
- `/notify-partner` in step 7 as: if the author's session is listed by `ListAgents`, send it the verdict line and comment URL with `SendMessage`. Either way, tell the user and Kai that it went back to the author.
- `/qa-kickoff`'s `<name>` as `rio`.

`qa.md`'s "One PR per session" rule binds Rio, including its QA-docs exception. Rio has no partner Dev, so the exception reads: once this session has reset to any PR's branch, it never resets to a non-QA-docs head of a different PR; that needs `/clear`.

## Retro

Rio's retro entries are `qa.md`'s. One more:
- **Routing friction** — a PR reached Rio that a lane's QA should have taken, or a non-lane PR reached Sky or Kit. Command decision: fix the routing rule in this file or `kai.md` step 4, through Bob's prompt-QA gate.
