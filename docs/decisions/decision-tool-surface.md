# Decision: Tool Surface — Approaches Considered and Rejected

**Date:** 2026-11-14
**Snapshot commit:** [`7c887e29`](https://github.com/khuisman/mcp-gee-sweet/commit/7c887e29) — codebase as it existed when this record was written
**Issue:** [#1514](https://github.com/khuisman/mcp-gee-sweet/issues/1514)

> This is a point-in-time record. It gathers decisions already made in issues, PR threads and earlier decision docs, so the next proposal to shrink the tool list starts from them instead of reopening them. It decides nothing new. The proposal that follows from it is [`docs/design/tool-reduction.md`](../design/tool-reduction.md).

## Background

At this snapshot the server registers 143 tools under `ENABLED_TOOLS=all`. Several clients cap the number of tools they accept (VS Code 128 per request, Windsurf 100 across servers, Antigravity 100 per server, Cursor per model; `docs/client-setup.md`), and every tool's description and schema costs context on every call (`docs/design.md`, "Tool count as a cost").

Two changes already answer the cap: tool groups (#1364, PR #1501), so an unset `ENABLED_TOOLS` loads the `default` group of at most 40 tools, and a one-release deprecation policy for renamed and removed tools (#1209, PR #1507). The approaches below were considered along the way and rejected or narrowed. Until now most of them were recorded only in #1364's issue body.

## Rejected

### 1. Dynamic disclosure: a meta-tool that loads more tools, or `notifications/tools/list_changed`

Start with a small list and grow it during the session, either through a tool the model calls to "enable Gmail" or by sending `list_changed` when the server decides more tools are needed.

**Rejected** in #1364's design, for two reasons:
- Clients don't reliably act on a changing tool list. A model that never sees the new tools can't use them, and nothing tells it they exist.
- OAuth scopes are fixed by the tools registered when the server starts (`set_gmail_enabled`, #790). Enabling Gmail mid-session would need a scope the token never asked for, so the new tools would fail with an auth error until the user consented again.

Client-side tool search does the useful half of this already. Claude Code defers tool schemas until a search finds them, and current VS Code with Copilot ran "Search Tools" first and never hit its 128-tool cap with the full set (#1214, Kai's live check 2026-11-11). Disclosure is the client's job; the server's job is a list that's worth searching.

### 2. One "executor" tool that runs any operation by name

Register one tool such as `run(operation, args)` in front of every operation, so the client sees one tool.

**Rejected** in #1364's design. Each tool's `ToolAnnotations` (`readOnlyHint`, `destructiveHint`) and its input schema are what clients act on. ChatGPT treats a tool without `readOnlyHint` as a write and drops it on read-only plans (#1358), clients check arguments against the schema before a call, and Claude Code permission rules allow or deny by tool name (`docs/design.md`, "Renaming or Removing a Tool"). One executor tool would carry a single annotation and a single free-form schema for every operation, so a user couldn't allow reads and deny deletes, and the model would lose the schema that guides a correct call. `batch_update` is the one deliberate exception: a raw passthrough for the Sheets long tail, kept because the alternative is a named tool per request type (`docs/design.md`, "The `batch_update` rule").

### 3. A separate setting for groups

Add a new variable such as `ENABLED_GROUPS` alongside `ENABLED_TOOLS`.

**Rejected** in #1364's design. `ENABLED_TOOLS` takes tool names and group names in one list and registers their union, so every existing value keeps working and there's one place to look. Group and tool names are kept disjoint by a CI check, so an entry is never ambiguous.

### 4. Server-side composite tools for workflows the client can chain

Wrap common multi-step workflows in one tool each.

**Rejected** for anything the client chains reliably, by [`decision-composite-tools.md`](decision-composite-tools.md) (2026-05-22): `create_from_template`, `log_calendar_to_sheet`, `book_next_free_slot`, `find_and_update_row` and `markdown_to_doc` were ruled out, and the rule became `docs/design.md`'s "When to Build a Composite". The same rule was applied later:
- [`decision-gmail-domain.md`](decision-gmail-domain.md): `find_unanswered` and `send_reminders` rejected.
- [`decision-comments-first-class.md`](decision-comments-first-class.md) §1: one comment tool set over any `file_id`, not per-service wrappers such as `list_sheet_comments`. It names the condition for revisiting: an operator asking to restrict comments by service.

Composites stay allowed where the client fails without them: binary data, pagination loops, and encoding decisions. This restates `docs/design.md`'s "When to Build a Composite"; it isn't a new restriction and doesn't affect any existing tool.

## Narrowed

### 5. Aliases for renamed tools register only when asked for

The first form of #1209 kept every old name as an alias for a release. The maintainer narrowed it on 2026-11-03 (comment on #1209): a callable alias registers only when the old name is listed in `ENABLED_TOOLS` or the server runs with `all`. Groups, `default` included, never carry an alias, so aliases don't count against a client's cap. The cost, accepted: on a default install an old-name call fails right after the rename. Implemented in `tool_groups.RENAMED_TOOLS` and `server._alias_of`.

## Premise that didn't hold

### 6. VS Code's 128-tool error on a default install

#1214 was filed on the premise that VS Code fails on the first call when a server registers more than 128 tools. Kai's live check (2026-11-11, 139 tools on 0.9.5) found no error: Copilot looked tools up on demand. The docs now describe the error as observed rather than certain, and the cap stays a reason for `default`, not a hard failure to design around. Cursor, Windsurf and Antigravity were not re-checked.

## Not yet decided

- **ChatGPT's tool budget.** A reported limit of about 5,000 tokens of tool definitions is unconfirmed. It's one of #1364's live checks for Aziz. If it's real, #1364 already says the answer is shorter descriptions (#1358) plus a documented smaller list, not another group.
- **Cutting the total.** Groups change what a client sees by default; they don't change the total. Which sibling tools should merge is the subject of [`docs/design/tool-reduction.md`](../design/tool-reduction.md).

## When to revisit

- Dynamic disclosure (1), if MCP clients reliably honor `list_changed` and the scope problem has an answer, for example incremental OAuth consent from a tool call (#873's path).
- The executor tool (2): no foreseeable trigger. Annotations and per-name permissions are the reason, and both are getting more important to clients.
- Alias narrowing (5), if users report old-name failures on default installs after a rename.
