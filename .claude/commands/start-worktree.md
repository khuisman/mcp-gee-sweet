Create an isolated git worktree for parallel work in this repo, with the same local configuration as the main checkout (credentials, env, and a synced virtualenv), so it can run alongside other sessions without touching their branches or files.

1. Determine the worktree name: use the argument passed to this command if given (e.g. an issue number or short slug, sanitized to letters/digits/dots/underscores/dashes). If no argument was given, ask the user for a short name before proceeding.
2. Call `EnterWorktree` with that name. This creates the worktree under `.claude/worktrees/<name>/`, branches it from `origin/develop` (the repo's default branch), and switches the session into it.
3. Copy the untracked local config that `git worktree` does not check out, from the original repo root (the directory the session was in before `EnterWorktree`) into the new worktree root: `.env`, `credentials.json`, `service_account.json`, `token.json`, `.claude/settings.local.json`. Skip any file that doesn't exist in the source.
4. Run `uv sync` in the new worktree to build its own virtualenv — worktrees don't share `.venv`.
5. Confirm the worktree is ready: report its path and current branch to the user.

Do not modify the original checkout's files. If the user later asks to leave this worktree, use `ExitWorktree` with `keep` unless they explicitly say to discard the work.
