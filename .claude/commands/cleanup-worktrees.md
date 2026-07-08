Remove worktrees under `.claude/worktrees/` whose branch has a merged PR, so completed tickets don't pile up as stale directories. Safe by default: never deletes anything with uncommitted or unpushed changes — those are reported, not touched.

1. List current worktrees: `git worktree list --porcelain`. Skip the main checkout (the entry with no `.claude/worktrees/` path).
2. For each remaining worktree, get its branch name and check whether it has a merged PR:
   ```
   gh pr list --repo khuisman/mcp-gee-sweet --state merged --head <branch> --json number,url,mergedAt
   ```
3. For each worktree whose branch has a merged PR, check it's safe to remove:
   - No uncommitted changes: `git -C <path> status --porcelain` must be empty.
   - No unpushed commits: `git -C <path> log @{upstream}.. --oneline` must be empty (if the branch has no upstream, e.g. already deleted on the remote post-merge, treat a clean `status --porcelain` as sufficient).
   - If both checks pass, remove it: `git worktree remove <path>`, then `git branch -d <branch>`.
   - If either check fails, skip it and note what's uncommitted or unpushed — never force-remove.
4. Leave alone any worktree whose branch has no merged PR (open PR, no PR yet, or PR closed without merging).
5. Run `git worktree prune` to clear any stale administrative entries left behind.
6. Report a summary: worktrees removed (with their PR link), worktrees skipped as dirty (with what's blocking removal), and worktrees still open (with PR/issue status).
