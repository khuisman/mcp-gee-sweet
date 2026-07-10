Verify an open worker PR before merging: code review plus live QA testing against real Google APIs. This only works from the orchestrator session in the main checkout — see `/orchestrator` for why (live MCP tools always serve the main checkout's code, never a worktree's).

CI (the "Lint and test" check `/merge-pr` already gates on) covers unit tests. It cannot cover code review judgment or live calls against real Google APIs, since those need credentials and fixtures CI doesn't have. That's what this skill does instead — it's the step between a worker's PR going up and `/merge-pr`.

1. **Preconditions.** Confirm this session is in the main checkout, not a worktree (same check as `/orchestrator` step 1). If the main checkout has uncommitted changes, stop and ask the user how to proceed — don't stash or discard anything.

2. **Identify the PR.** Take a PR number as an argument if given, otherwise use `gh pr list --state open` and ask the user which one if there's more than one. Get its details: `gh pr view <number> --json number,title,url,headRefName,baseRefName,statusCheckRollup,mergeable,mergeStateStatus`. If `mergeable` is `CONFLICTING`, stop here — report it and say the branch needs a rebase onto `<baseRefName>` before verification is worth doing. Don't spend code-review or live-QA effort on a branch that can't merge as-is; that cost is only worth paying once it's rebased.

3. **Check out the branch.** Don't use `gh pr checkout <number>` directly — if the worker's own worktree still has `<headRefName>` checked out (the normal case while that worker session is active), it fails with "already checked out," and the only recovery `gh` offers is unlocking/removing that worktree, which disrupts the worker for no reason. Git only blocks two worktrees from sharing the same branch *name*, not the same commit — so fetch the PR's branch into a locally-named review branch instead:
   ```
   git fetch origin <headRefName>:review/<headRefName> --force
   git checkout review/<headRefName>
   git branch --set-upstream-to=origin/<headRefName> review/<headRefName>
   ```
   This points the main checkout at the exact same commit without touching the worker's worktree at all. The `--set-upstream-to` matters: without it, `gh pr view`/`gh pr merge` with no PR number can't map the local `review/<headRefName>` branch back to the PR later (their current-branch auto-detection relies on tracked-branch info, not name matching) — `/merge-pr` should also be run with the PR number as an explicit argument here rather than relying on that auto-detection. When pushing QA-result commits later (step 9), push to the PR's real branch name via a refspec: `git push origin review/<headRefName>:<headRefName>`. Delete the local `review/<headRefName>` branch once you're done with this PR (switch away first, then `git branch -D review/<headRefName>`) so it doesn't accumulate across sessions.

4. **Reconnect the MCP server.** The server hot-reloads on file change, but this Claude session's MCP connection stays on the old process. Tell the user to run:
   ```
   /mcp reconnect
   ```
   on its own line, standalone (not embedded in other text). Wait for confirmation before continuing — live tests run against stale code otherwise.

5. **Code review.** Run `/code-review` at `high` effort against the diff (`<baseRefName>...<headRefName>`, typically `develop...HEAD`). Report findings before moving on to live testing — if it surfaces a correctness bug, ask the user whether to still proceed with live QA or send the PR back to the worker first.

6. **Scope the live QA run.** Don't run the full suite. Find what this PR actually touches:
   - `git diff origin/<baseRefName>...HEAD --name-only -- docs/qa/tests/` — new or modified test case files.
   - Within those, identify test cases that are new or whose `Prompt`/`Setup`/`Checks` changed (not ones only touched by unrelated reflow). These are mandatory.
   - Cross-check against `git diff origin/<baseRefName>...HEAD --name-only -- src/mcp_gee_sweet/tools/` — for each changed tool, confirm there's at least one QA test case covering it in scope; if a changed tool has no corresponding test case at all, flag that as a gap rather than silently skipping it.
   - Existing passing test cases for the same tool (regression) are optional spot-checks, not mandatory re-runs — full regression is `docs/qa/run.md`'s job, run periodically, not per-PR.

7. **Run the scoped test cases live.** Follow each test case's `Prompt`/`Setup` against the fixtures in `docs/qa/.env` (see `docs/qa/setup.md` if fixtures aren't configured), using the now-reconnected MCP tools. For `**Playwright: required**` cases, use the connected Playwright MCP if available; if not connected, tell the user and ask whether to proceed without visual verification or connect it first.

8. **Record results honestly.** For each test case actually executed, add `**Result (<date>) ✅ PASS**` or `**Result (<date>) ❌ FAIL — <what happened>**` directly below its `Checks` block. Never write a Result for a case you didn't actually invoke — if something blocks a case (fixture missing, tool errors before completing), write `**Result (<date>)** pending — <reason>` and say so plainly rather than guessing the outcome.

9. **Commit and push the results.** If any Result entries were added, they need to land in a real file edit. If this session runs under an isolation policy that blocks edits outside `.claude/worktrees/*` (background jobs do — regardless of which branch is checked out in the main checkout), don't spin up a fresh throwaway worktree per PR (churn — create, edit, commit, push, remove, repeat). Instead keep **one persistent scratch worktree** for the whole orchestrator session, e.g. `.claude/worktrees/qa-scratch`, and reuse it every time this step comes up:
   ```
   git worktree add .claude/worktrees/qa-scratch -b orchestrator-qa-scratch develop   # first time only
   ```
   Its own branch name (`orchestrator-qa-scratch`) is arbitrary and never touches any PR branch, so it can never conflict with a worker's worktree. Each time this step comes up: enter it (`EnterWorktree` with `path`), `git fetch origin <headRefName> && git reset --hard origin/<headRefName>` to line it up with the PR's latest commit, make the edits, commit (`qa: record live verification for PR #<number>`), then push straight to the PR's real branch via refspec — same trick as step 3:
   ```
   git push origin HEAD:<headRefName>
   ```
   Ask before pushing, per this repo's normal commit/push confirmation rule. Leave the scratch worktree in place afterward (`ExitWorktree` with `action: "keep"`) for next time — don't remove it between PRs, only if the user asks for a cleanup pass.

10. **Report.** Summarize: code review findings (if any), which test cases passed/failed/pending, any coverage gaps found in step 6, and whether the branch looks ready to merge. If everything passed, say the next step is `/merge-pr`. If something failed, say the PR needs to go back to its worker session — don't attempt the fix yourself here; this session's job is verification, not implementation.

Leave the branch checked out either way — `/merge-pr` operates on the current branch's PR, and if it needs rework, the worker's own worktree still has the branch open there too.
