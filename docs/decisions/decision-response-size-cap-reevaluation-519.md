# Decision: Response-Size Cap Re-Evaluation (issue #519)

**Date:** 2026-08-07
**Snapshot commit:** branch `feat/joy/issue-519` — see `src/mcp_gee_sweet/tools/response_limits.py`

## Background

Both prior decision docs ([Grid Data Size Cap](decision-grid-data-size-cap.md), [Response-Size Cap Generalization](decision-response-size-cap-generalization.md)) named the same re-evaluation trigger in their own "When to Re-evaluate" sections: if the MCP client's behavior around an oversized tool response changes, the cap should be re-measured, not assumed still necessary.

Issue #512's own comment thread raised exactly this: an *uncapped* tool (`list_files`) returned an 85,993-character response, and the MCP client (Claude Code) handled the overflow gracefully — auto-saved the full result to a local file and returned a pointer, with no error and no dropped connection. That's a real data point against the original #235 finding, where a 983,982-character response produced "Connection closed" and killed the session outright.

Issue #519 asked whether that original failure mode — the actual justification for `MAX_TOOL_RESPONSE_CHARS` existing at all — still reproduces today.

## What was tested, and how

Live-verified against the real OAuth-connected MCP client (this session's `mcp-gee-sweet-oauth` user-scoped connection, not any dev-lane role's server), using `get_sheet_data(include_grid_data=False)` — a code path with **no cap logic on it at all**, confirmed by reading `sheets/data.py` before testing (the `enforce_response_size_cap` call only exists inside the `include_grid_data=True` branch; the values-only branch used here has no cap and no `local_path` handling). This isolates the client's own behavior with nothing from this server's cap mechanism in the way.

Four scratch spreadsheets were created (via `import_csv_to_sheet`, content generated locally to avoid Python's csv module's 131072-char single-field limit — worked around by writing many 20,000-char rows instead of one giant field), read back, and deleted:

| Response size | Result |
|---|---|
| 85,993 chars (#512's own report, not re-run) | ✅ graceful — auto-saved to file, pointer returned |
| 160,150 chars | ✅ graceful |
| 500,235 chars | ✅ graceful |
| 1,000,360 chars | ✅ graceful — this is the same size class as #235's 983,982-char failure |
| 2,000,610 chars | ✅ graceful — 50x the old 40,000 default |

At every size, including the one that replicates #235's original death-zone almost exactly, the client redirected the response to a file (under its own session directory, not anything this server's code produced — confirmed by grepping the source for the exact strings in the client's message and finding zero matches) instead of dropping the connection.

**What this does not establish:** a ceiling above 2MB where the client's own graceful handling might still break down, or whether this behavior is specific to the current Claude Code client version versus something that was already present. Neither claim is made here — only that, for the client actually driving this investigation, right now, the specific failure mode this cap exists to prevent did not reproduce at any tested size.

## Options considered

1. **Keep the cap and its default unchanged.** Safest, but demonstrably over-restrictive now — it converts a case the client would handle gracefully into a hard `ValueError` that returns zero data (this is exactly what #512 reported for `sync_folder`'s dry-run).
2. **Raise the default, keep the hard-error mechanism.** Chosen — see below.
3. **Drop the cap entirely, rely on client-side handling.** Rejected: the cap's own stated purpose from day one was to protect against MCP clients that *don't* have graceful overflow handling — a case this investigation didn't and can't rule out, since only one client was tested. Removing the mechanism trades a known, cheap safety net for an assumption that holds for exactly one client.
4. **Make the existing opt-in `local_path` bypass automatic** (write to a server-side file and return a manifest instead of raising, whenever the cap would otherwise trip). Considered a genuinely reasonable alternative — it would protect any MCP client uniformly rather than depending on Claude Code's specific behavior. Not chosen for this issue because it inherits the same server-filesystem-locality caveat `local_path` already carries (useless to a remote SSE caller with no shared volume) and is a larger behavioral change than a config default bump. Worth reconsidering if #555's cross-client investigation finds clients that don't degrade gracefully on their own.

## Decision

**Raise `MAX_TOOL_RESPONSE_CHARS`'s default from `40000` to `1000000`.** Keep the cap mechanism itself — it remains valuable defense-in-depth for MCP clients other than the one tested here, and for responses larger than the 2MB actually verified.

`1000000` was chosen with the same margin-below-the-verified-ceiling logic as the original `40000` default (chosen "with margin below the ~48-51K observed" client limit at the time): it sits at 2x margin below the 2MB confirmed-safe in this round of testing, while being large enough to fix real complaints like #512's `sync_folder` dry-run failure (which tripped at just 40,119 characters) and comfortably clear most legitimate use of the 11 currently-capped tools.

**Scope note, unrelated to the size decision itself:** the cap now applies to 11 tools (`get_sheet_data`, `get_multiple_sheet_data`, `get_multiple_spreadsheet_summary`, `find_in_spreadsheet`, `get_doc_content`, `find_in_doc`, `list_doc_comments`, `list_file_activity`, `export_file`, `sync_folder`, `list_all_events`), not the 7 the original #519 ticket title assumed — the generalization doc's own tool list (5 tools + the original `get_sheet_data`) has grown without that doc being updated to track it. `docs/configuration.md`'s config table now lists the current 11.

## Not addressed here

- **Platform-specific guidance for other MCP clients.** `MAX_TOOL_RESPONSE_CHARS` remains a fairly esoteric config value — an operator has to already understand their own client's overflow behavior to tune it sensibly, and this investigation only characterized one client. Filed as [#555](https://github.com/khuisman/mcp-gee-sweet/issues/555).
- **QA fixture re-baselining.** Several existing QA test cases (`docs/qa/tests/sheets_read.md` TC-R03c/TC-R34/TC-R35, `docs/qa/tests/docs.md` TC-DOC80, `docs/qa/tests/drive.md`'s `export_file`/`sync_folder` cap tests) assert the *old* 40,000-character threshold and the fixture sizes needed to trip it. Those assertions are now stale relative to the new default and will need larger fixtures to still exercise the cap-trip path on a future live QA pass. Left untouched here — this was a scoped config-and-docs change, not a QA-suite rewrite, and fixture redesign is QA's call to make, not something to bundle in unreviewed.

## When to Re-evaluate

- If #555 finds an MCP client without graceful overflow handling becoming a primary consumer of this server, the case for keeping (or even lowering) a conservative cap gets stronger — don't assume this decision generalizes past the one client tested here.
- If Claude Code's own overflow-handling behavior changes again (in either direction), or a response naturally exceeding several MB becomes a realistic use case for one of the 11 capped tools, re-measure rather than assume `1000000` stays well-calibrated — same caveat every prior doc in this chain has carried.
