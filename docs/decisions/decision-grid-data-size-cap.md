# Decision: Response-Size Safety Net for get_sheet_data(include_grid_data=True)

**Date:** 2026-07-03
**Snapshot commit:** branch `feat/issue-235-grid-data-range` — see `src/mcp_gee_sweet/tools/sheets/data.py`

**Update (2026-07-03, issue #242):** `MAX_GRID_DATA_RESPONSE_CHARS` referenced below was renamed to `MAX_TOOL_RESPONSE_CHARS` and generalized to 5 more tools — see `docs/decisions/decision-response-size-cap-generalization.md`. This doc is left as-is below as the historical record of the original decision.

## Background

Issue #235: `get_sheet_data(include_grid_data=True)` without a `range` fetches the sheet's full padded grid (often 1000x26 by default, regardless of actual content). In the reported case, the server-side Sheets API call succeeded (`200` in under a second), but the MCP client reported "Connection closed" — the failure was downstream of this server, in the client/transport layer, with no exception for the server to catch.

## Options Considered

### Option A: Require an explicit range

Raise a `ValueError` if `include_grid_data=True` and `range` is omitted, forcing the caller to supply a bounded range up front.

**Pros:** simplest possible fix; turns a silent transport failure into an immediate, actionable error.

**Cons:** pushes the burden onto the caller (typically an LLM) to already know the sheet's used extent before it can safely ask for formatting — usually means an extra round-trip (a values-only call first) just to learn the range, spending tokens on something the server can trivially compute itself. Rejected as poor UX once raised in review.

### Option B: Auto-detect used range + pre-fetch cell-count cap

Auto-detect the used range from a values-only probe when `range` is omitted (removes the guesswork), and reject the request before fetching if the resolved range's cell count exceeds a fixed threshold (initially 2000 cells), estimated from the issue's own numbers (150 cells ≈ 107KB, ~713 bytes/cell).

**Cons — falsified by live testing:** a live test against a real spreadsheet found cell count doesn't predict response size at all. A 26,000-cell **blank** range (a fresh sheet's default padding) returned almost nothing — Sheets omits `rowData` entirely for cells with no explicit formatting. A 1,300-cell range with real formatting applied (bold, background, number format) returned 983,982 characters and broke the session's own client. A pre-fetch estimate based on range shape can't distinguish these two cases; cutting the cap at any fixed cell count either blocks working requests (blank/lightly-formatted large ranges) or lets truly dangerous ones (small but densely-formatted ranges) through.

### Option C: Auto-detect used range + post-fetch response-size check (chosen)

Keep auto-detection (still correct and valuable — it prevents ever requesting formatting for irrelevant padding). Replace the pre-fetch cell-count estimate with a check on the **actual serialized response**, made after the Sheets API call completes (which is fast either way, per the issue's own account) but before returning it through the MCP tool response.

A second live-testing round, this time applying real formatting and binary-searching range size against the session's own MCP client, found the actual failure point much lower than the cell-count-based guess would have suggested:

| Cells | Characters | Result |
|---|---|---|
| 60 | (not captured — succeeded) | ✅ |
| 65 | 51,208 | ❌ |
| 75 | 58,784 | ❌ |
| 100 | 77,694 | ❌ |
| 500 | 380,494 | ❌ |
| 1,300 | 983,982 | ❌ |

This placed the real limit around 48,000–51,000 characters for that session — which matches Claude Code's documented default of 25,000 tokens per MCP tool response (`MAX_MCP_OUTPUT_TOKENS`), given this densely-nested, repeated-key JSON (`userEnteredFormat`, `backgroundColorStyle`, `rgbColor` on every cell) tokenizes at roughly 2 characters/token rather than the ~4 chars/token typical of prose.

Two consequences follow directly from this finding:

1. **The cap has to be measured, not estimated.** There's no way to know from range shape alone how formatted a range's cells are, so the check runs on `len(json.dumps(result))` after the fetch.
2. **The cap has to be configurable, not fixed.** `MAX_MCP_OUTPUT_TOKENS` is a client-side setting the server has no visibility into — a different MCP client, or the same client with a raised limit, has a different real threshold. `MAX_GRID_DATA_RESPONSE_CHARS` (default `40000`, chosen with margin below the ~48-51K observed here) lets an operator match their own client's actual configuration.

`local_path` (optional file/directory path) was added as an escape hatch that bypasses the cap entirely by writing the result to disk instead of returning it inline — this avoids the client output-token limit altogether, at the cost of the same server-filesystem-locality caveat `download_file`/`download_folder` already carry (meaningful for stdio and shared-volume SSE deployments; not useful for a remote SSE client with no shared filesystem).

## Decision

**Use Option C.** Auto-detect the used range when omitted; check the actual serialized response size after fetching, not an estimate beforehand; make the cap configurable via `MAX_GRID_DATA_RESPONSE_CHARS`; offer `local_path` as an unconditional bypass.

The chosen default (`40000` characters) is explicitly documented in code as *one environment's observed limit, not a universal constant* — it should not be read as an authoritative number for all MCP clients.

## Follow-up

Issue #242 tracks generalizing this pattern (post-fetch size check + configurable cap + `local_path` bypass) to other tools that can return large responses (`export_file`, `get_doc_content`, `get_multiple_sheet_data`, etc.) — out of scope for #235's fix, which is deliberately scoped to the one tool named in the bug report. That follow-up also needs to address that `MAX_GRID_DATA_RESPONSE_CHARS` was named for its one-tool scope and won't generalize as-is.

## When to Re-evaluate

- If #242 generalizes this pattern, this decision's env var naming and per-tool scoping should be revisited together, not left as a precedent copied ad hoc.
- If Claude Code's `MAX_MCP_OUTPUT_TOKENS` default changes, or another MCP client with a materially different limit becomes a primary consumer of this server, the default cap value should be re-measured rather than assumed to still be well-calibrated.
