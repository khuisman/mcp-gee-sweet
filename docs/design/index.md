# Design Documents

Detailed implementation design docs — file layouts, data models, algorithm choices, and trade-offs as they were understood when each piece of work was planned.

These are more granular than the [decision records](../decisions/index.md), which capture *why* a direction was chosen. Design docs capture *how* something is built.

| Doc | Date | Scope |
|---|---|---|
| [Docs AST Pipeline](docs-ast-pipeline.md) | 2026-06-17 | Phase 2 HTML→AST→Docs API pipeline — AST node design, file layout, emitter algorithm, test plan |
| [Heading-Anchor Resolution](heading-anchor-resolution.md) | 2026-07-28 | Resolving GitHub/GitLab `#slug` heading-anchor links to working Docs jump links — multi-scheme slugifier, strip-if-unmatched policy, opinionated-layer-over-primitive rationale |
| [Native Markdown/HTML Image Support](image-conversion.md) | 2026-08-02 | `Image` as a zero-width AST node vs. a marker-based alternative, the combined table+image descending-position insertion pass, three-source-kind resolution + share/revoke lifecycle, the retry-on-image-failure fix, and the deliberate table-cell-image gap |
| [Borderless-Table Columns](borderless-table-columns.md) | 2026-08-02 | Form-style column alignment via a zero-padding table, once `tabStops` was found read-only (#404) — border-suppression step flagged unverified pending live check |
| [Blockquote Representation](blockquote-representation.md) | 2026-08-06 | Flat `blockquote_depth` field (mirroring `BulletItem.depth`) vs. a wrapper node; left border + scaled indent via `paragraphStyle.borderLeft`, live-verified writable before implementing |
| [Module Implementation History](module-history.md) | 2026-09-29 | Per-PR history behind root `CLAUDE.md`'s module and workflow rules, moved there verbatim by #849 so `CLAUDE.md` keeps only lasting rules and invariants |
| [SSE OAuth Consent Off the Event Loop](sse-consent-off-event-loop.md) | 2026-10-01 | #833: the SSE consent wait on a daemon thread with a stoppable callback server, shared across connections, ended by sse_starlette's shutdown flag on SIGTERM |
| [Re-authorizing OAuth from the Failing Tool Call](oauth-reauthorize-from-tool-call.md) | 2026-10-06 | #873/#906: a revoked or missing token offers the consent link from the failing call (URL elicitation, or the link in the `ToolError`), detected at `thread_http`'s transport so tools that catch errors are covered, adopted in place on every connection |
