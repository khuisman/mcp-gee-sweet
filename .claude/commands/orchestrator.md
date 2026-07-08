Establish this session as the **orchestrator** — the one session responsible for ticket triage, roadmap grooming, live testing, and reviewing/merging PRs, as opposed to a worker session doing ticket implementation in a worktree.

Why this role split exists: `mcp-gee-sweet-oauth`/`mcp-gee-sweet-sa` (`~/.claude.json`) are global stdio servers running `uv run --directory <main checkout> mcp-gee-sweet`, and the `mcp-gee-sweet` docker-compose service bind-mounts `./src` from the main checkout too. Both always serve whatever is checked out in the **main checkout**, regardless of which directory (main checkout or any worktree) the calling session's shell is in. A worktree's code is invisible to every live MCP tool call until it's checked out in the main checkout or merged to `develop`. So only one place can ever do meaningful live testing — the main checkout — and only one session should treat it as home base at a time.

1. Confirm this session is running from the main checkout, not a `.claude/worktrees/*` path. If it's in a worktree, tell the user the orchestrator role requires the main checkout and ask whether to `ExitWorktree` (`keep`) first.
2. Check `git branch --show-current` and `git status --short` on the main checkout:
   - On `develop` and clean: ready.
   - On a feature branch, or dirty: flag it. Ticket implementation shouldn't live in the main checkout under this model — it blocks freely checking out other branches to live-test them. Ask the user whether to move that work into its own worktree (`start-worktree`) or continue as-is for now.
3. Report current state so the user can steer:
   - `git worktree list` — active worker worktrees
   - `gh pr list --repo khuisman/mcp-gee-sweet --state open` — PRs awaiting live-test/review/merge
   - `gh issue list --repo khuisman/mcp-gee-sweet --label ready-for-development --state open` — queued ticket(s)
4. State the orchestrator's responsibilities plainly:
   - Ticket triage and labeling (`ready-for-development`, version labels)
   - Roadmap grooming (`docs/roadmap.md` + the `project_v09_roadmap` memory)
   - Live/manual tool testing — only possible here
   - Reviewing worker PRs: checkout the branch in the main checkout to live-test before merging
   - Worktree cleanup after merge (`cleanup-worktrees`)

   Do NOT pick up ticket implementation directly in this session — hand it to a worker session via `start-worktree` (or `next-issue`, which does this automatically).
