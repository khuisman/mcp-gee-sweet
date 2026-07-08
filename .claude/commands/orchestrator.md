Establish this session as the **orchestrator** — the one session responsible for ticket triage, roadmap grooming, live testing, and reviewing/merging PRs, as opposed to a worker session doing ticket implementation in a worktree.

Why this role split exists: any locally-configured MCP server that runs this project via `uv run --directory <path>` (check your global MCP config for one pointing at this repo), plus the `mcp-gee-sweet` docker-compose service (bind-mounts `./src`), always serve whatever is checked out at that fixed path — the main checkout, not whichever worktree a session's shell happens to be in. A worktree's code is invisible to every live MCP tool call until it's checked out in the main checkout or merged to the default branch. So only one place can ever do meaningful live testing — the main checkout — and only one session should treat it as home base at a time.

1. Confirm this session is running from the main checkout, not a `.claude/worktrees/*` path. If it's in a worktree, tell the user the orchestrator role requires the main checkout and ask whether to `ExitWorktree` (`keep`) first.
2. Check `git branch --show-current` and `git status --short` on the main checkout:
   - On `develop` and clean: ready.
   - On a feature branch, or dirty: flag it. Ticket implementation shouldn't live in the main checkout under this model — it blocks freely checking out other branches to live-test them. Ask the user whether to move that work into its own worktree (`start-worktree`) or continue as-is for now.
3. Report current state so the user can steer:
   - `git worktree list` — active worker worktrees
   - `gh pr list --state open` — PRs awaiting live-test/review/merge (run from inside the repo so `gh` infers it from the git remote — don't hardcode a repo slug, forks won't match)
   - `gh issue list --label ready-for-development --state open` — queued ticket(s)
4. State the orchestrator's responsibilities plainly:
   - Ticket triage and labeling (`ready-for-development`, version labels)
   - Roadmap grooming (`docs/roadmap.md` + whichever roadmap-planning memory is currently active — check the memory index rather than assuming a specific version-numbered file)
   - Live/manual tool testing — only possible here
   - Reviewing worker PRs: `verify-pr` (code review + scoped live QA against real Google APIs) before `merge-pr`
   - Worktree cleanup after merge (`cleanup-worktrees`)

   Do NOT pick up ticket implementation directly in this session — hand it to a worker session via `start-worktree` (or `next-issue`, which does this automatically).
