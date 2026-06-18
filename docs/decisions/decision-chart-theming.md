# Decision: Chart Theming and Phase 3 Integration

**Date:** 2026-06-17
**Status:** decided

> This is a point-in-time record. It captures context, alternatives, and reasoning as they were understood on the date above — not the current state of the project.

## Background

The [Docs Formatting Architecture](decision-docs-formatting.md) decision (PR #83) established a Phase 3 CSS-like theme system for Google Docs — named style configs covering fonts, heading colors, and table styling, applied at AST emit time. Phase 3 as written is scoped entirely to Docs.

A follow-up design conversation asked whether chart formatting could fit within the same templating system. The question matters before Phase 3 is implemented: if the theme format is designed Docs-only, retrofitting chart support later risks incompatible config structures and a fractured `apply_theme` interface.

The current `add_chart` tool (`tools/sheets/structure.py`) handles data and structure — chart type, A1 data ranges, axis labels, positioning — but exposes no visual styling. Series colors, fonts, gridlines, legend styling, axis label formatting, and background color are all available in the Sheets API `chartSpec` but not surfaced. This gap is the chart-side counterpart to the Docs styling gap that motivated Phase 3.

## Design Questions Considered

### 1. Does chart support warrant a parsing layer?

The Docs AST exists because there is a significant translation gap: HTML (rich, free-form) must be converted to Docs batchUpdate requests (index-based, API-specific). The parser, AST, and emitter are three distinct stages because the input and output representations are fundamentally different.

Charts have no equivalent gap. `add_chart` parameters — chart type string, A1 range, axis labels, width, height — map directly and legibly to the Sheets API `chartSpec` structure. The existing branching on chart type is conditional JSON construction, not translation. There is no free-form input to parse.

**Decision:** No parsing layer. A `ChartSpec` typed intermediate representation is appropriate (see Architecture below) as the target for theme application, but it is not a parser — it organizes existing parameter logic, not a translation pipeline.

### 2. Should an external chart spec format (e.g. Vega-Lite) be adopted as input?

Vega-Lite is the closest well-documented match: declarative JSON, a clear separation between data encoding and visual config, and a vocabulary (mark type, encoding channels, config block) that AI tools produce fluently. Its design language is legible and transferable.

However, formal adoption would create the same silent-drop problem the Docs decision identified in the HTML parser — just imported from outside rather than grown internally. Vega-Lite can express things the Sheets API cannot: faceting, arbitrary data transforms, layered marks with different encodings, interactive selections. A caller writing valid Vega-Lite would have no signal that features are silently unsupported. The contract would overpromise.

**Decision:** No formal adoption. Vega-Lite serves as a design reference — its organizing concepts (mark, encoding, config) inform how `ChartSpec` is structured — but the contract is scoped to what Sheets can actually deliver. This avoids the overpromise problem while preserving legibility for anyone familiar with Vega-Lite.

### 3. How should chart theming integrate with the Docs Phase 3 theme system?

The theme resolver's job is the same in both cases: take a content description (AST node or ChartSpec) and a named theme config, and produce styled API requests. The surface differs (Docs batchUpdate vs. Sheets batchUpdate chartSpec), but the abstraction is identical. A theme system designed Docs-only would require a separate, parallel system for charts — duplicating the `list_themes` / `apply_theme` interface and splitting what should be a unified brand config into two uncoordinated files.

The natural shape is a single brand config with surface-specific sections:

```yaml
# brand-theme.yaml
docs:
  heading_font: "Google Sans"
  heading_colors: ["#1a73e8", "#185abc", "#1557b0"]
  table_border_color: "#dadce0"
  table_header_background: "#e8f0fe"

charts:
  palette: ["#1a73e8", "#34a853", "#fbbc04", "#ea4335"]
  font: "Google Sans"
  gridline_color: "#f1f3f4"
  legend_position: "RIGHT_LEGEND"
  background_color: "#ffffff"
```

`apply_theme` routes to the correct resolver (Docs AST emitter or ChartSpec emitter) based on context. `list_themes` is surface-agnostic. A workflow creating both a doc and a chart applies the same theme name to both and gets consistent brand output without the caller coordinating styles manually.

**Decision:** Unified brand config with surface-specific sections. Phase 3 must be designed with this generality from the start — the theme format, storage mechanism, and `apply_theme` interface should treat Docs as the first consumer, not the only one.

### 4. Is there a deeper integration between charts and docs?

The Docs API supports embedded charts — a chart created in Sheets can be linked and embedded in a Google Doc. A workflow that produces a themed doc with a themed embedded chart, both governed by the same brand config, is the fullest expression of the templating system: a single `apply_theme` call governs look-and-feel across both surfaces.

**Decision:** Worth noting as a future direction. Embedded chart support does not affect Phase 1 or 2 and is not a prerequisite for Phase 3. It is the logical endpoint of the unified theme system once both surface resolvers exist.

## Architecture

```
Brand theme config (YAML/JSON)
  ├── docs:   heading_font, heading_colors, table_border_style, ...
  └── charts: palette, font, gridlines, legend_style, ...

Theme resolver
  ├── Docs branch:   theme.docs  →  applied at AST emit  →  Docs batchUpdate requests
  └── Charts branch: theme.charts →  applied at ChartSpec emit  →  Sheets batchUpdate chartSpec

ChartSpec (typed intermediate representation)
  mark:     chart type (COLUMN, BAR, LINE, PIE, ...)
  encoding: domain range, series ranges, axis labels
  config:   visual overrides (palette, font, gridlines, ...)
```

`ChartSpec` is not a parser output — it is a typed reorganization of what `add_chart` already constructs inline. It serves as the emit target for theme application: the theme resolver populates `config` fields from the brand config, then `ChartSpec` emits the final Sheets API `chartSpec` dict. Callers that do not use themes get the same behavior as today; callers that specify a theme get consistent visual styling without passing individual color and font parameters.

The `ChartSpec` organizing concepts — mark, encoding, config — are drawn from Vega-Lite's vocabulary for legibility, without creating a dependency on or promise to support the full Vega-Lite spec.
