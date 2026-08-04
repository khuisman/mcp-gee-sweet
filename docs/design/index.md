# Design Documents

Detailed implementation design docs — file layouts, data models, algorithm choices, and trade-offs as they were understood when each piece of work was planned.

These are more granular than the [decision records](../decisions/index.md), which capture *why* a direction was chosen. Design docs capture *how* something is built.

| Doc | Date | Scope |
|---|---|---|
| [Docs AST Pipeline](docs-ast-pipeline.md) | 2026-06-17 | Phase 2 HTML→AST→Docs API pipeline — AST node design, file layout, emitter algorithm, test plan |
| [Heading-Anchor Resolution](heading-anchor-resolution.md) | 2026-07-28 | Resolving GitHub/GitLab `#slug` heading-anchor links to working Docs jump links — multi-scheme slugifier, strip-if-unmatched policy, opinionated-layer-over-primitive rationale |
| [Native Markdown/HTML Image Support](image-conversion.md) | 2026-08-02 | `Image` as a zero-width AST node vs. a marker-based alternative, the combined table+image descending-position insertion pass, three-source-kind resolution + share/revoke lifecycle, the retry-on-image-failure fix, and the deliberate table-cell-image gap |
| [Borderless-Table Columns](borderless-table-columns.md) | 2026-08-02 | Form-style column alignment via a zero-padding table, once `tabStops` was found read-only (#404) — border-suppression step flagged unverified pending live check |
