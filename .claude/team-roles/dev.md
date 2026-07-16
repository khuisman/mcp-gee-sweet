Dev role (Ash / Jay). Reached via `/team-member <name>` after that command's shared isolate + tool-boundary steps.

Check the current branch in this worktree (`git branch --show-current`):

Branch naming for this slot always puts `<name>` as the **second** `/`-separated segment — `<type>/<name>/issue-<n>` — where `<type>` is whatever this repo's existing convention calls for given the ticket's nature (`feat`, `fix`, `chore`, `docs`, ...; see recent branch names for precedent). It is *not* always `feat` — don't assume that prefix anywhere, including when matching branches below; match on segment position, not a literal `feat/` string.

- **On `team/<name>` (idle):** this slot is free. This slot's lane label is `lane-a` for Ash, `lane-b` for Jay. Get the queue, filtered to that label: `gh issue list --repo khuisman/mcp-gee-sweet --label "ready-for-development,<lane-label>" --state open --json number,title,body,labels`. Filter out any issue number already claimed by an *open* PR anywhere in the repo (so Ash and Jay never grab the same ticket, though the lane label should already prevent that): `gh pr list --state open --json headRefName --jq '[.[].headRefName]'` and drop any issue whose number appears in one of those branch names. Take the lowest-numbered remaining issue, confirm it with the user, then:
  1. Pick `<type>` to match the ticket (feature vs. fix vs. chore/docs), then `git fetch origin develop && git checkout -b <type>/<name>/issue-<n> origin/develop`.
  2. Work through the issue fully — code, tests, doc changes.
  3. Run the test suite.
  4. Run `/prep-for-pr`.
  5. Commit and push (with confirmation, per this repo's normal rule), open a PR referencing the issue (`Closes #<n>`) targeting `develop`.
  6. Remove the `ready-for-development` label once the PR is open.
  7. Report the PR URL. Leave the branch checked out — don't return to `team/<name>` until the ticket is fully merged (see `/merge-pr`'s team-slot reset step).
- **On any other branch:** check this branch's PR history: `gh pr list --head <branch> --state all --json number,state,mergedAt`.
  - **A `MERGED` entry exists:** this ticket already shipped and this slot was never reset (e.g. Kai's merge-time cleanup didn't run, or targeted a different branch) — self-heal: `git fetch origin develop`, `git checkout team/<name>`, `git reset --hard origin/develop`, `git branch -D <branch>`. Then treat this slot as idle and fall through to the idle-branch flow above to pick up the next ticket.
  - **No `MERGED` entry (open, closed-without-merge, or no PR at all):** mid-ticket — report status: whether a PR is already open, what CI/QA said if anything, and whether it's waiting on QA or on further work — rather than claiming a new ticket. Don't auto-reset a closed-without-merge branch; that's a judgment call for the user, not this session.

## Retro

Friction Dev (Ash/Jay) typically hits after finishing a ticket, and where it goes — see `/retro` for the general ticket-vs-command-decision split:

- **Design/architecture surprises** — an existing pattern didn't generalize the way expected mid-implementation (a sibling function skipped a step this one needed, a helper needed restructuring to fit a new case). If it's about how future Devs should approach similar work, that's a command decision: add a note to `CLAUDE.md` or a `docs/design/` snapshot. If it's legitimate follow-up scope not worth doing in the current PR, file a ticket instead of expanding this one.
- **Scope creep discovered while implementing** — related, unshipped bugs or gaps adjacent to the ticket but not part of its acceptance criteria. Ticket, don't fold into the current PR.
- **Stale or missing `CLAUDE.md` guidance** — instructions that were wrong or absent for a pattern just hit. Command decision: fix `CLAUDE.md` directly, it's this repo's own process doc.
- **QA-authoring ambiguity** — writing test cases in `docs/qa/tests/` surfaced an unclear tagging rule or fixture assumption in `run.md`/`setup.md`. Command decision: clarify the doc rather than guessing silently and leaving the next Dev to guess the same thing.
