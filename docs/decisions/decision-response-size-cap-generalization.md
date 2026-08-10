# Decision: Generalizing the Response-Size Safety Net (issue #242)

**Date:** 2026-07-03
**Snapshot commit:** branch `feat/issue-242-response-size-safety-net` — see `src/mcp_gee_sweet/tools/response_limits.py`

**Update (2026-08-07, issue #519):** the shared `40000`-character default named throughout this doc was raised to `1000000`, and the cap now covers more tools than the 6 (1 original + 5 here) this doc scoped — see `docs/decisions/decision-response-size-cap-reevaluation-519.md`. This doc is left as-is below as the historical record of the original generalization decision.

## Background

Issue #235 (see `docs/decisions/decision-grid-data-size-cap.md`) added a response-size safety net to exactly one tool, `get_sheet_data(include_grid_data=True)`: an MCP client (e.g. Claude Code, via `MAX_MCP_OUTPUT_TOKENS`) enforces a hard cap on tool response size, and exceeding it doesn't degrade gracefully — it silently kills the MCP session, requiring a full server restart to recover. That decision doc explicitly flagged #242 as the follow-up to generalize the pattern to other tools, and warned that `MAX_GRID_DATA_RESPONSE_CHARS` was scoped to one tool and wouldn't generalize as named.

This is a confirmed defect, not a hypothetical hardening gap: the silent-session-death failure mode has been observed live. What was unmapped was *which other tools* can trigger it and at what real thresholds — verifying that requires generating fixtures above the ceiling per tool, which gets most of the way to the fix anyway, so investigation and fix were scoped as one unit (`docs/roadmap.md`, v0.8.1).

## Scope

Five more tools, in priority order by how easily they can produce an oversized response:

1. `export_file` — base64-encodes binary content inline, unbounded, no existing size control
2. `get_doc_content` — full unbounded plain-text export of a doc
3. `get_multiple_sheet_data` — unbounded query list, each returning a full value range
4. `find_in_spreadsheet` — bounds match *count* (`max_results`) but not match *size*
5. `list_file_activity` — already Drive-API-paginated and lowest risk of the five

## Decisions

### 1. Single global env var, not per-tool

Considered three options: (A) one global `MAX_TOOL_RESPONSE_CHARS` for all 6 capped tools, (B) six separate per-tool vars, (C) a hybrid — global default with a per-tool override reserved for `export_file` (whose base64 encoding inflates raw file size ~33%, making it structurally different from the others).

**Chose (A), confirmed with the user.** One knob is simpler to discover and configure than six, and the marginal precision a per-tool override buys wasn't judged worth the added config surface — an operator who needs a materially higher ceiling for `export_file` specifically can raise the shared var, or use `download_file` instead (see below).

`MAX_GRID_DATA_RESPONSE_CHARS` (from #235) was renamed to `MAX_TOOL_RESPONSE_CHARS` as part of this change — free to do since #235 hadn't shipped in a released package version yet (still pre-release on `develop`). The cap constant and check logic now live in one shared module, `src/mcp_gee_sweet/tools/response_limits.py` (`enforce_response_size_cap`, `write_capped_result_to_disk`), imported cross-package by each tool module the same way `tools/drive/__init__.py`'s `_SA_QUOTA_ERROR` already is.

### 2. `export_file` gets the cap but not `local_path`

`local_path` on the other four tools writes `json.dumps(result)` to disk as an escape hatch. For `export_file`, that would mean writing a JSON file *containing a base64 string* — a worse artifact than what already exists: `download_file` (pre-existing tool) writes the raw file bytes straight to disk with no base64 or JSON wrapping overhead. Adding a redundant, structurally worse bypass just for API symmetry with the other tools wasn't worth it. `export_file`'s cap error message points to `download_file` instead.

### 3. `list_file_activity` gets the cap, no `local_path`, no dedicated live-fixture verification

Already paginated (`page_size` clamped 1–100) and low per-item size — the only realistic exposure is a single activity's `actors` list ballooning on a file with many collaborators. Included the cap for defense-in-depth (cheap — one shared-helper call), but:
- No `local_path`: the natural remedy for "too much" here is `page_size`/pagination, not writing timeline fragments to disk.
- No dedicated live-fixture verification (see below): reproducing hundreds of real Drive Activity events cheaply isn't practical, and the risk is real but rare.

### 4. `get_doc_content` cache-ordering bug fixed while touched

The `doc_cache` early-return previously ran *before* any cap logic could — a cached oversized doc would bypass the cap on repeat calls. Fixed so the cap check runs on both the cache-hit and cache-miss paths (see `tests/test_docs_content.py::TestGetDocContent::test_cached_oversized_result_also_raises`).

## Live-tested thresholds

Live-verified against the real QA fixture spreadsheet/docs on 2026-07-03, after reconnecting the MCP session to this branch. Full detail in `docs/qa/tests/sheets_read.md` (TC-R34, TC-R35), `docs/qa/tests/docs.md` (TC-DOC80), `docs/qa/tests/drive.md` (TC-D167, TC-D168).

| Tool | Real fixture | Measured size | Cap tripped? |
|---|---|---|---|
| `get_doc_content` | `TEST_LARGE_DOC_ID` grown to ~49,700 chars (seeded via `insert_doc_text`) | 49,700 chars | ✅ (fetch path and cached path both) |
| `export_file` (xlsx) | Small QA fixture spreadsheet (3 sheets, mostly tiny) | 54,280 chars | ✅ — even a small workbook's base64-encoded xlsx export exceeds the cap |
| `get_multiple_sheet_data` | 200 queries against a 6x4 range (`Sales` sheet) | 150,106 chars | ✅ — query *count* alone is a real vector, independent of per-query range size |
| `find_in_spreadsheet` | 10 cells x ~4,785 chars each, all matching (well under `max_results=50`) | 42,491 chars | ✅ — confirms `max_results` bounds count, not size |
| `list_file_activity` | N/A — no dedicated fixture, per the scoping decision above | N/A | Not live-tested; unit-tested only (defense-in-depth) |

Two findings worth calling out:

1. **`export_file` trips the cap far more readily than the others.** A workbook small enough that its *values* fit trivially under the cap still blows past it once base64-encoded — this validates the concern raised during design (item 2 above) and confirms `download_file` is the practical default, not `export_file`, for anything but the smallest files.
2. **`get_multiple_sheet_data`'s query-count axis is real and independent of range size** — 200 queries against a *tiny* 6x4 range (not a large one) already produced a 150K-character response. This means the cap protects against "many small things" just as much as "one big thing," which the original #235 cap (single range, single tool) never had to consider.

## When to Re-evaluate

- If a materially different MCP client (different `MAX_MCP_OUTPUT_TOKENS` or equivalent) becomes a primary consumer, the shared `40000`-character default should be re-measured, not assumed to still be well-calibrated — same caveat #235 already carries.
- If `export_file` usage in practice shows the shared cap is routinely too restrictive for legitimate small-to-medium binary exports, revisit the per-tool-override hybrid (option C) that was considered and set aside here.
