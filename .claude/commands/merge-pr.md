Merge the current branch's PR and clean up its worktree. Uses `--admin` only to bypass the required-review gate (this is a solo-maintainer repo, so a second approver is never coming) — it must never be used to bypass a failing or pending status check.

1. Get the PR for the current branch: `gh pr view --json number,title,url,state,mergeable,statusCheckRollup,reviewDecision`. If there's no open PR for this branch, stop and tell the user.
2. Verify it's actually safe to merge:
   - `state` must be `OPEN`.
   - Every check in `statusCheckRollup` (in particular "Lint and test") must show success. If anything is failing or still pending, stop and report which — do not merge, and do not wait/poll.
   - `mergeable` must not be `CONFLICTING`.
3. Show the user a summary: PR number, title, URL, check status, and review status (expected to be blocked only on the missing-approval requirement). State plainly that merging will use `--admin` to bypass that review gate. Ask for explicit confirmation before proceeding.
4. On confirmation, squash-merge (matching this repo's existing history — commits land on `develop` as a single `title (#number)` commit): `gh pr merge <number> --admin --squash`. The remote branch is auto-deleted on merge (repo setting), so don't pass `--delete-branch`.
5. Clean up the local worktree:
   - If this session created the current worktree (i.e. it got here via `/start-worktree` or `/next-issue` earlier in this same session), use `ExitWorktree` with `action: "remove"`.
   - Otherwise (worktree predates this session), fall back to manual cleanup from the main checkout: `git worktree remove <path>`, then `git branch -d <branch>`, then `git worktree prune`.
6. Update the roadmap: from the main checkout on `develop`, `git pull` then check `docs/roadmap.md` for a checkbox line referencing the issue(s) this PR closes (search by issue number). If found, check it off (`- [ ]` → `- [x]`) and append `(PR <number>)` in the existing style (e.g. `(PR #280)`) — see recent `- [x]` entries for the exact convention. If the roadmap has no line item for this issue (not every ticket is roadmap-tracked — chores, follow-up defects, etc.), skip this step silently. Commit directly to `develop` (`docs(roadmap): check off #<issue> (PR <number>)`) and push — `develop`'s branch protection has `enforce_admins: false`, so a direct push by the repo owner is allowed for this kind of small, reversible, docs-only change; don't open a separate PR for it.
7. Report a summary: the merge commit, the now-merged PR URL, confirmation the worktree was removed, and whether the roadmap was updated.
