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
