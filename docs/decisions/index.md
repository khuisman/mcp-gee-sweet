# Decision Log

Point-in-time records of specific decisions — context, alternatives, and reasoning as they stood when each call was made. For current policy and principles, see [Design Principles](../design.md).

| Doc | Date | Status | Summary |
|---|---|---|---|
| [Project Fork](decision-fork.md) | 2026-05-09 | decided | Fork from xing5/mcp-google-sheets; alternatives evaluated |
| [Composite Tools](decision-composite-tools.md) | 2026-05-22 | decided | Case analysis of specific composite tools approved or ruled out |
| [Testing Approach](decision-testing.md) | 2026-05-13 | decided | Why AI-directed manual verification over automated integration tests |
| [Publishing Strategy](decision-publishing.md) | 2026-05-23 | draft | Two-track PyPI release (stable + edge); version injection open |
| [Docs Formatting Architecture](decision-docs-formatting.md) | 2026-06-17 | decided | Two-layer approach (direct API tools + HTML abstraction via AST); phase plan for #41, #65–#70, #79–#82 |
| [Chart Theming and Phase 3 Integration](decision-chart-theming.md) | 2026-06-17 | decided | No parsing layer for charts; no Vega-Lite adoption; unified brand config (docs + charts sections) for Phase 3 theme system |
| [Grid Data Size Cap](decision-grid-data-size-cap.md) | 2026-07-03 | decided | Post-fetch response-size check (not pre-fetch cell-count estimate) for `get_sheet_data(include_grid_data=True)`; configurable cap + `local_path` bypass; empirically falsified two earlier approaches |
| [Cache Invalidation](decision-cache-invalidation.md) | 2026-07-07 | decided | `set_cache_ttl` tool for runtime TTL; `modifiedTime`-based validation for sheet/doc caches only (not folders/calendar); opt-out via `CACHE_VALIDATE_MODIFIED_TIME` |
| [Dev-Team Roles](decision-dev-team.md) | 2026-07-11 | decided | Named Orchestrator/Dev/QA ×2-lane team, persistent worktree slots, one combined MCP config for Agent View, branch-prefix lane routing |
| [Async Tool Execution](decision-async-tool-execution.md) | 2026-07-12 | decided | Full tool layer converted to `async def` + `asyncio.to_thread()`; `asyncio.gather()` for 6 multi-call tools; per-thread HTTP transport fix for the newly-introduced shared-service concurrency risk; `cache.py` stays synchronous by design |
| [Release QA Lead and Tech Writer Roles](decision-release-docs-roles.md) | 2026-07-12 | decided | Aziz/Amy persistent slots, no dedicated MCP server, Aziz borrows Sky/Kit via `Agent`-tool subagents for sharded live release QA, Amy claims `documentation`-labeled issues |
| [Repositioning](decision-repositioning.md) | 2026-07-14 | decided | Source-verified comparison vs. official Google Workspace MCP (dev preview, no Sheets/Docs coverage at all) and community alternatives; informational framing, not a superiority claim; narrows the Docs "deepest" claim, surfaces gaps to `roadmap.md` Tier 4 |
