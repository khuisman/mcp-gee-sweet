QA role (Sky / Kit). Reached via `/team-member <name>` after that command's shared isolate + tool-boundary steps.

Find the partner Dev's open PR by matching the branch's second `/`-separated segment against the partner's lowercase name — not a `feat/`-specific prefix, since the Dev's branch type varies: `gh pr list --state open --json number,headRefName,url --jq '[.[] | select((.headRefName | split("/"))[1] == "<partner>")]'`. At most one is expected, since a lane only has one ticket in flight at a time.

- **None found:** self-heal first — `git fetch origin develop`. If this worktree's `HEAD` isn't already `origin/develop`, `git reset --hard origin/develop`: since the partner has no open PR right now, any leftover commits here are a stale copy of a PR this lane previously reviewed (now merged or closed) — this worktree never holds original work of its own, only reset-in copies of a Dev's PR branch, so it's always safe to discard. Then report that Lane {A/B} has nothing to verify right now.
- **One found:** this is now essentially `/verify-pr`'s steps 4 onward, but simpler — this worktree already IS a dedicated review space, so skip `/verify-pr`'s steps 1–3 (the main-checkout precondition and the `review/<branch>` fetch trick don't apply here):
  1. `git fetch origin <headRefName> && git reset --hard origin/<headRefName>` in this worktree, staying on `team/<name>` (never create a branch named after the PR here — this slot's identity is `team/<name>`, permanently).
  2. Tell the user to run `/mcp reconnect` (standalone, on its own line) so this agent's own MCP connection picks up the reset code. Wait for confirmation.
  3. Run `/code-review` at `high` effort against `origin/develop...HEAD`.
  4. Scope and run the live QA steps from `/verify-pr` (its steps 6–8: find touched `docs/qa/tests/` cases, cross-check tool coverage, run them live using this worktree's own `mcp-gee-sweet-<name>`-prefixed tools).
  5. Record `**Result**` entries for every case actually run.
  6. If anything failed: push the recorded results (`git push origin HEAD:<headRefName>`, with confirmation), comment on the PR summarizing what failed, and stop — tell the user it goes back to the Dev agent.
  7. If everything passed: push the results, then `gh pr edit <number> --add-label qa-approved`, and report to the user that it's ready for Kai to run `/merge-pr`.
