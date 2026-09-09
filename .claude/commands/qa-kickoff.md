Invoked from `.claude/team-roles/qa.md` step 2, after resetting this worktree to the partner Dev's PR branch. Determine which case applies, then send the user **exactly** the block below as your next message — verbatim, no rewording, no splitting across turns — except substitute `<name>` with this role's own lowercase name (e.g. `sky`, `kit`) so the block is directly copy-pasteable:

**First QA pass on this PR** (no `/code-review` has run against it yet this cycle):

```
/mcp reconnect mcp-gee-sweet-<name>
/code-review high origin/develop...HEAD
```

**Re-verification round** (Dev pushed a fix for a previously-named finding):

```
/mcp reconnect mcp-gee-sweet-<name>
```

On a re-verification round, do not ask for `/code-review` again. After the reconnect lands, run `git show <fix-sha>` on the Dev's new commit yourself and live-verify against its own new QA test case (see `.claude/team-roles/qa.md` Retro). Fall back to a full `/code-review` only if the fix's diff is structurally larger than the named finding, or unrelated commits landed in between.

Either way, once the reconnect confirmation lands, check it names *this role's own* `mcp-gee-sweet-<name>` server before trusting any live tool result — naming the server explicitly in the command above rules out the old bare-`/mcp reconnect` failure mode where the wrong role's server got reconnected, but the confirmation is still worth a glance. Don't rely on `ToolSearch`'s cached tool description as a substitute freshness check either — it can keep showing the pre-reset docstring even after a correct reconnect. Treat a live tool call's own observed behavior as the only reliable signal a reconnect actually took effect.
