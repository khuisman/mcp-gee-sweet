# Decision: Repositioning — README / docs "Why it exists" (issue #263)

**Date:** 2026-07-14
**Snapshot commit:** branch `docs/amy/issue-263`

## Background

`README.md`'s intro and `docs/index.md`'s "Why it exists" both lead with: "Google does not provide an official MCP server for Sheets or Drive (as of mid-2026)." Google's Workspace Developer Preview Program has since shipped official MCP servers for some products, which undercuts that framing as the *sole* justification for this project's existence (issue #263). The obvious fix — lead with concrete differentiators instead — has a tone risk: a "here's why we're better than Google's own offering" framing reads as brash, and it also ignores that several community projects predate or exceed Google's official coverage in places. Decision: do the comparison properly, present it as an informational table where the official servers are one option among several (not the bar every claim has to clear), and only claim what's actually source-verified.

## Research: the competitive landscape (as of 2026-07-14)

### Official Google Workspace MCP servers (Developer Preview Program)

Per `developers.google.com/workspace/guides/configure-mcp-servers`: **"Developer Preview: Available as part of the Google Workspace Developer Preview Program, which grants early access to certain features."** Five products have a dedicated server — Gmail (10 tools), Drive (8 tools), Calendar (9 tools), People API (3 tools), Chat (4 tools). **Google Sheets, Google Docs, Google Forms, and Google Sites have no dedicated official MCP server at all** — not developer-preview, not anything. This is the opposite of what issue #263 assumed: for our two deepest domains, the original "no official alternative exists" claim is still literally true today. For Drive and Calendar, an official (preview-stage) alternative now exists, but it's a fraction of this project's surface (32 Drive tools / 13 Calendar tools here vs. 8 / 9 there).

The December 2025 Google Cloud "GA MCP support" announcement (BigQuery, GKE, GCE, Maps) is a separate product line — Cloud infrastructure, not Workspace productivity — and is explicitly out of scope per this project's own scope table in `design.md`. Not a relevant comparator here.

### Community alternatives (source-verified where noted, not just README claims)

| Project | Domains | Tool depth | Maintenance | License |
|---|---|---|---|---|
| [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) (our fork origin) | Sheets, Drive | ~19 tools | Active, slow cadence; last commit ~2mo ago | MIT |
| [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp) | 12 services (Gmail, Drive, Calendar, Docs, Sheets, Slides, Forms, Chat, Apps Script, Tasks, Contacts, Search) | Source-verified 115 tools (Docs 18, Sheets 12) | Very active, last commit 6 days ago, 2,847★ | MIT |
| [a-bonus/google-docs-mcp](https://github.com/a-bonus/google-docs-mcp) | Docs, Sheets, Drive, Gmail, Calendar | Source-verified ~44 Sheets tools / ~39 Docs tools (index-file registration count) — **exceeds** its own README's claimed 32/24, one-file-per-operation style | Active | MIT |
| [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) | Drive, Docs, Sheets, Slides, Calendar | Docs ~17 (deeper on tabs/footnotes than us), Sheets 8 (shallow — no batch passthrough, no charts) | Very active, committed same day as this research | MIT |
| [ngs/google-mcp-server](https://github.com/ngs/google-mcp-server) | Calendar, Drive, Gmail, Sheets, Docs, Slides | README claims 60+; Sheets/Docs sections explicitly thin (3+ tools each) | Stale — 2★, last commit ~5mo ago | MIT |
| [aaronsb/google-workspace-mcp](https://github.com/aaronsb/google-workspace-mcp) | Gmail, Calendar, Drive, Docs, Sheets, Tasks, Meet | 11 coarse "mega-tools" (e.g. `manage_docs`), not fine-grained ops | Very active | Apache-2.0 |
| [j3k0/mcp-google-workspace](https://github.com/j3k0/mcp-google-workspace) | Gmail, Calendar only | ~15 tools | Moderately active | MIT |

## Decisions

### 1. Framing: informational comparison, not a superiority claim

The README/docs rewrite presents a comparison table where Google's official servers are one row among several — not the standard every other row is measured against. No "beats Google" language. Each claim in the table must be traceable to this doc.

### 2. Sheets: claim holds, but on breadth-of-named-operations + `batch_update` escape hatch, not raw tool count

a-bonus/google-docs-mcp has more raw Sheets tools than us (37 explicitly registered, ~44 including the comments submodule) — confirmed by reading `src/tools/sheets/index.ts`, not just their README. Nobody reviewed matches the *combination* of full formulas/structure/formatting/charts read-write **plus** `batch_update`'s raw passthrough escape hatch (an explicit design choice, see `design.md`'s "Tool count is a cost" — this project deliberately keeps the named-tool surface smaller and pushes long-tail operations through one escape hatch rather than registering a named tool per operation, which is the opposite philosophy from a-bonus's one-file-per-operation style). The differentiator is real but is a design-philosophy claim, not a "most tools" claim — those are different things and only the former is defensible.

### 3. Docs: narrow from "deepest, full stop" to "AST-based theming and structural fidelity"

Two source-confirmed gaps mean an unqualified "deepest in Docs" claim doesn't survive scrutiny:
- **Markdown export.** `taylorwilsdon/google_workspace_mcp` has a real `get_doc_as_markdown` tool (confirmed in `gdocs/docs_tools.py`, not just claimed). This project's Markdown support is currently input-only (`_md_to_html` on the write path via `create_doc`/`write_doc_content`) — there is no export equivalent. Tracked as [#300](https://github.com/khuisman/mcp-gee-sweet/issues/300); this research is added there as corroborating evidence, not hidden from the positioning copy.
- **Footnotes and multi-tab documents.** `piotr-agier/google-drive-mcp` has footnote management; a-bonus has multi-tab support (`addTab`/`renameTab`/`listDocumentTabs`). Neither is in this project's toolset.

What still looks like a genuine, unmatched strength: the AST-based theming pipeline (`apply_theme`, `get_doc_theme`, `get_doc_named_styles`) and the N-round nested-table-fill emitter (see `project_docs_table_pattern` design history) — nothing reviewed has an equivalent. The rewritten copy leads with *this*, specifically, rather than an unqualified "deepest" claim.

### 4. New capability gaps surfaced by this audit are roadmap candidates, not positioning claims to omit or paper over

Sheets (comments, conditional formatting, protected ranges, dropdown validation, row grouping, auto-resize, write-side dimensions, the native Sheets "Tables" object, copy-formatting-only) and Docs (comments, multi-tab, smart chips, section/page breaks, table structure discovery, finer-grained table styling) gaps found during this research are added to `docs/roadmap.md` Tier 4, credited to their source project, per the existing competitive-audit-sourcing convention (`freema/mcp-gsheets`, `piotr-agier/google-drive-mcp` are already credited there the same way). They stay as unchecked candidates — per `design.md`, the roadmap tracks candidates until there's a real use case, not every gap found in an audit.

### 5. `decision-fork.md` stays a historical record

Per issue #263's own instruction: add a pointer note to `decision-fork.md` marking it superseded by this doc for *current* positioning, without rewriting its original reasoning — it remains an accurate record of the 2026-05-09 fork decision and the alternatives evaluated at that time.

### 6. Correction: our own tool counts were also unverified — caught in PR review, not before

The first draft of this doc and the comparison table pulled *our own* per-domain tool counts from `docs/roadmap.md`'s "What's implemented" section (Sheets 24, Drive 31, Docs 20, Calendar 8) without independently counting from source — the exact mistake this whole rewrite exists to avoid in competitors. PR review (`gh pr view 306`, comment from `khuisman`) caught it by counting `@tool(...)` registrations directly. Recounted via the same mechanism `scripts/gen_tool_docs.py` already uses (`register_all()` with a capturing decorator, not grep) and found the actual counts materially higher: **Sheets 25** (`duplicate_sheet` was undocumented in `roadmap.md`), **Drive 32** (`import_csv_to_sheet` was undocumented), **Docs 20** (accurate, no change), **Calendar 13** (an entire calendar-management sub-feature — `create_calendar`/`update_calendar`/`delete_calendar`/`add_calendar_to_list`/`remove_calendar_from_list` — was missing from `roadmap.md` entirely, not just miscounted). Total across the four domains: **90**, not 84 (the stale "84 tools" headline in `README.md`/`docs/index.md` was corrected too — it dated to the v0.8.0 release and was never bumped as tools shipped afterward).

This doc's own tables and `docs/roadmap.md`'s "What's implemented" headers are corrected to match. Follow-up: file a ticket to extend `scripts/gen_tool_docs.py` (or add a companion pre-commit check) to validate hardcoded tool counts in prose docs against the live source count, so this class of drift fails a commit instead of requiring a human reviewer to catch it by hand — `collect_tools()` already has the exact data needed, grouped by module.

## What changes in the docs

- `README.md` — intro paragraph, replacing the stale "no official alternative" framing with the breadth/design-philosophy/AST-theming differentiators above, informational tone.
- `docs/index.md` — "Why it exists" section, same content adapted to that doc's structure.
- `docs/decisions/decision-fork.md` — one-line pointer note added, not rewritten.
- `docs/decisions/index.md` — row added for this doc.
- `docs/roadmap.md` — Tier 4 gap candidates + credits (already applied ahead of this doc, during the research pass).
