# Feature Roadmap

This doc is a high-level orientation — feature ideas, architectural direction, and historical context. **Active work is tracked in [GitHub Issues](https://github.com/khuisman/mcp-gee-sweet/issues).** When a roadmap item is scheduled, an issue is opened; the checkbox here stays as a reference.

Features are ordered by practical priority within each tier, cross-domain. Items marked with a source were identified by auditing competing projects — see [decision-fork.md](decisions/decision-fork.md) for full credits.

## What's implemented

Sheets, Drive, Docs, and Calendar are all covered — see [Tools](tools.md) for the full, auto-generated, per-domain list of every tool and its parameters. That list is regenerated from the source tool registry on every commit, so it's never out of sync the way a hand-maintained enumeration here would be.

---

## Release cadence

| Version | Scope | Signal |
|---------|-------|--------|
| [**v0.7.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.7) | ✅ First stable PyPI release — 63 tools across Sheets, Drive, Docs, Calendar | Published 2026-06-21 |
| [**v0.8.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8) | ✅ Tier 1 complete — all "frequently needed" items across all domains (84 tools) | Published 2026-06-29 |
| [**v0.8.1**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8.1) | Defect & documentation cleanup — no new tools, ships the QA/refactor work already on `develop` plus fixes for #235, #242, #213, #239, #236 | Stabilizes before Tier 2 feature work begins |
| [**v0.9.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9) | Tier 2 complete — power-user and structured-work layer (~20 tools), plus defects that surfaced after v0.8.1 shipped ([#248](https://github.com/khuisman/mcp-gee-sweet/issues/248)) | Covers most real workflows |
| [**v0.9.1**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.1) | Post-release defect fixes & infrastructure addons — no new tools, same shape as v0.8.1 | Stabilizes before Tier 3 begins |
| [**v0.9.2**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.2) | Comments as a first-class, cross-suite capability — generalize + complete the Drive `comments`/`replies` surface ([#661](https://github.com/khuisman/mcp-gee-sweet/issues/661)); ships a breaking rename | Closes out the comments story before Tier 3 |
| [**v1.0.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av1.0) | API stability declaration — Tier 3 items that make the cut + any breaking cleanups from v0.8–0.9 | Backwards-compatibility commitment |
| [**v1.1.0+**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22v1.1%2B%22) | Future domains — Tasks, Gmail (separate minor releases, each needs a new API client) | Expanded scope |

Tier 4 items remain backlog with no assigned version.

---

## Roadmap

### Tier 1 — High value, frequently needed _(target: [v0.8.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8))_

**Infrastructure**
- [x] PyPI publish — OIDC trusted publishing ([#55](https://github.com/khuisman/mcp-gee-sweet/issues/55)) — v0.7.0 stable live; `uvx mcp-gee-sweet` works

**Sheets**
- [x] `delete_sheet` — delete a tab by name or sheetId ([#115](https://github.com/khuisman/mcp-gee-sweet/issues/115)) _(freema/mcp-gsheets)_
- [x] `clear_values` — clear cell content in a range without touching formatting ([#116](https://github.com/khuisman/mcp-gee-sweet/issues/116)) _(freema/mcp-gsheets)_
- [x] `delete_rows` / `delete_columns` — remove rows or columns by index ([#117](https://github.com/khuisman/mcp-gee-sweet/issues/117)) _(freema/mcp-gsheets)_
- [x] `format_cells` — background color, font, alignment, number format on a range ([#118](https://github.com/khuisman/mcp-gee-sweet/issues/118)) _(freema/mcp-gsheets)_
- [x] `merge_cells` / `unmerge_cells` — merge a range into one cell ([#119](https://github.com/khuisman/mcp-gee-sweet/issues/119)) _(freema/mcp-gsheets)_
- [x] `freeze` — freeze rows and/or columns ([#120](https://github.com/khuisman/mcp-gee-sweet/issues/120))
- [x] `sort_range` — sort a range by one or more columns ([#121](https://github.com/khuisman/mcp-gee-sweet/issues/121))

**Calendar**
- [x] Recurring events — RRULE support in `create_event` and `update_event`; `expand_recurring` in `list_events`; instance vs master scope documented ([#155](https://github.com/khuisman/mcp-gee-sweet/issues/155))

**Docs**
- [x] `insert_inline_image` — insert an image at a document index ([#145](https://github.com/khuisman/mcp-gee-sweet/issues/145))
- [x] Table structural ops — `insert_table_row`, `delete_table_row`, `insert_table_column`, `delete_table_column` ([#146](https://github.com/khuisman/mcp-gee-sweet/issues/146))
- [x] `create_header` / `create_footer` — page headers and footers ([#147](https://github.com/khuisman/mcp-gee-sweet/issues/147))

**Drive**
- [x] `list_shared_with_me` — files explicitly shared with the authenticated user ([#135](https://github.com/khuisman/mcp-gee-sweet/issues/135))
- [x] `list_recent_files` — files recently accessed or modified ([#136](https://github.com/khuisman/mcp-gee-sweet/issues/136))
- [x] `get_storage_quota` — Drive storage usage and limits ([#137](https://github.com/khuisman/mcp-gee-sweet/issues/137))

### v0.8.1 — Defect & documentation cleanup _(target: [v0.8.1](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.8.1), before Tier 2 begins)_

No new tools. Stabilize on what Tier 1 shipped before starting Tier 2 feature work.

**Already on `develop`, awaiting release**
- [x] Playwright per-test tagging policy, conductor prompt improvements (PR #228)
- [x] QA test case fixes — `share_file` fixtures, TC-D148 setup, Playwright tags (PR #229)
- [x] SQLite cache defensive recovery from read-only/corrupted DB files at connect time (PR #230)
- [x] `tools/docs/__init__.py` split into `content.py`/`tables.py`/`style.py`/`layout.py` (PR #232)

**Remaining defects to fix before cutting the release**
- [x] `get_sheet_data(include_grid_data=True)` without a range fetches the full padded grid instead of the used range ([#235](https://github.com/khuisman/mcp-gee-sweet/issues/235))
- [x] Generalize the #235 response-size safety net (post-fetch size check + configurable cap + `local_path` bypass) to other tools that can return large responses — `export_file`, `get_doc_content`, `get_multiple_sheet_data`, `find_in_spreadsheet`, `list_file_activity`. Oversized responses silently kill the MCP session today (client-side output cap, e.g. Claude Code's `MAX_MCP_OUTPUT_TOKENS`), requiring a server restart to recover — confirmed live, not hypothetical. Renamed `MAX_GRID_DATA_RESPONSE_CHARS` to `MAX_TOOL_RESPONSE_CHARS` (single global cap); live-verified thresholds per tool ([#242](https://github.com/khuisman/mcp-gee-sweet/issues/242))
- [x] `create_doc_from_file` markdown `$` escape renders as literal backslash+dollar in the doc — Python-Markdown's default `ESCAPED_CHARS` omitted `$` (unlike CommonMark); fixed via a small extension adding it, respecting code-span/fenced-code protection ([#213](https://github.com/khuisman/mcp-gee-sweet/issues/213))
- [x] Unknown tool parameters are silently dropped instead of raising a validation error — FastMCP's generated pydantic arg models default to ignoring extra fields, so a typo'd kwarg (e.g. `parent_id` instead of `parent_folder_id`) silently falls back to default behavior instead of erroring. Fixed centrally in the `tool()` decorator (applies to all ~84 tools uniformly) ([#239](https://github.com/khuisman/mcp-gee-sweet/issues/239))
- [x] Auto-generate `docs/tools.md` from tool source as a pre-commit hook — makes the manual tools.md backfill in #236 unnecessary (PR #240) ([#94](https://github.com/khuisman/mcp-gee-sweet/issues/94))
- [x] Correct `docs/roadmap.md`'s own tool catalog counts, `known-limitations.md`'s `list_all_events` entry, and rework README's/`docs/client-setup.md`'s Configuration examples to lead with OAuth (not service account) for local/dev quick-start — currently mismatches the project's own auth priority order and PyPI's page inherits it verbatim ([#236](https://github.com/khuisman/mcp-gee-sweet/issues/236))
- [x] Rewrite `CONTRIBUTING.md` — fix broken links to removed README anchors, fix stale "Available Tool Names" and `bug`-label references, add better local-dev setup examples including observability (`DEBUG_LEVEL`/`LOG_FILE`/`ACCESS_LOG_FILE`) ([#95](https://github.com/khuisman/mcp-gee-sweet/issues/95))
- [ ] Define and document community PR expectations — template, testing bar for non-tool PRs, scope/size convention, CLA/DCO/code-of-conduct decision, review turnaround ([#237](https://github.com/khuisman/mcp-gee-sweet/issues/237))

### Tier 2 — Useful for structured work, plus defects surfaced since v0.8.1 _(target: [v0.9.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9))_

**Defects** _(found after v0.8.1 shipped; too late for that release, don't warrant a standalone patch)_
- [x] Dev prereleases become unreachable once the base version's stable release ships — `format-jinja` never bumps past the last tag, so `X.Y.Z.devN` is a PEP 440 pre-release of the already-published `X.Y.Z` and always loses precedence to it; fix is `bump = true` in `[tool.uv-dynamic-versioning]` (PR #318) ([#317](https://github.com/khuisman/mcp-gee-sweet/issues/317))
- [x] `sync_folder` doesn't recurse into subfolders — one-level-only Drive query silently reports a clean "in sync" result while ignoring every nested file (confirmed live: 225 files across 22 subfolders ignored, only the root-level file seen) (PR #328) ([#315](https://github.com/khuisman/mcp-gee-sweet/issues/315))
- [x] `download_folder`'s file loop is genuinely sequential (`for f in ...: await asyncio.to_thread(...)`) — the one multi-file transfer path missed when the `asyncio.gather` pattern was established (#183); `sync_folder`'s own transfer step already uses it correctly (PR #351) ([#316](https://github.com/khuisman/mcp-gee-sweet/issues/316))
- [x] `sync_folder` re-uploads every file after its first download — download never sets the local file's mtime to match Drive's `modifiedTime`, so any real time gap past the 5s tolerance makes the local copy look "locally newer" on the next sync; confirmed live during #315/#328 QA, reproduces on both new and long-standing files, unrelated to recursion (PR #357) ([#346](https://github.com/khuisman/mcp-gee-sweet/issues/346))
- [x] Bare URLs in markdown content aren't autolinked — Python-Markdown's built-in autolink only fires on `<https://...>` or `[text](url)`, not a bare URL (PR #265) ([#248](https://github.com/khuisman/mcp-gee-sweet/issues/248))
- [x] `zip(doc_tables, ast_tables)` in `emitter.py` silently cross-pairs tables when one is skipped (zero-row/zero-col table), misapplying fill/merge/style requests to the wrong table — surfaced during #276's review (PR #282) ([#277](https://github.com/khuisman/mcp-gee-sweet/issues/277))
- [x] Nested `<li>` silently deletes the parent list item's own text (HTML and Markdown paths) — `handle_starttag` clobbers the outer block's in-progress run buffer with no save/restore; found by Aziz auditing the markdown/HTML-to-Doc pipeline (PR #369) ([#335](https://github.com/khuisman/mcp-gee-sweet/issues/335))
- [x] Nested bullet/numbered list depth is computed correctly but never emitted as Docs indentation — every list renders flat regardless of source nesting; `ast_to_requests` never reads `BulletItem.depth`; found alongside #335 — was held back until #360 merged (both rewrite the same `ast_to_requests` bullet-handling logic in `emitter.py`); #360 shipped 2026-07-24, so `ready-for-development`/`lane-b` again, queued behind #402 ([#336](https://github.com/khuisman/mcp-gee-sweet/issues/336)) (PR #432)
- [x] `emitter.py` computes Docs API insertion offsets via Python `len()` instead of UTF-16 code units — wrong for any astral-plane character (most emoji, some CJK/math symbols); fixed via external contributor PR #360, live-verified in PR #407 — unblocks #372's `content.py` split (PR #360) ([#358](https://github.com/khuisman/mcp-gee-sweet/issues/358))
- [x] `spreadsheet://{id}/info` MCP resource throws `'FastMCP' object has no attribute 'get_lifespan_context'` — discovered live during #361's QA, possibly a regression from the mcp SDK bump (#349/#350) (PR #368) ([#363](https://github.com/khuisman/mcp-gee-sweet/issues/363))
- [x] Plain-text content (no wrapping tag) silently produces an empty doc body (PR #385) ([#343](https://github.com/khuisman/mcp-gee-sweet/issues/343))
- [x] `_get_sheet_id` catches all exceptions from the sheet-lookup fetch and returns `None`, the same value it returns when the sheet genuinely doesn't exist — every caller (24 call sites) then misreports a transient API error as "sheet not found"; flagged during #380/#89's QA (PR #390) ([#384](https://github.com/khuisman/mcp-gee-sweet/issues/384))
- [x] `_AstParser.handle_endtag` pops `_list_ordered` only on a matching close tag — a mismatched `<ol>`/`<ul>` pair leaves it permanently desynced, corrupting nesting depth for every subsequent list in the document; pre-existing, confirmed live during #369/#335's review — `ready-for-development`/`lane-b` re-added now that #401/#402 (both shipped) are no longer blocking it, queued behind #408/#409 (PR #449) ([#382](https://github.com/khuisman/mcp-gee-sweet/issues/382))
- [x] When the markdown-to-Doc converter can't represent a construct (unsupported image path, thematic break `---`, or anything else unhandled), it deletes that construct's entire paragraph rather than leaving an empty block — breaks fidelity with how every CommonMark viewer degrades (paragraph boundaries hold even when an inline element fails to resolve); confirmed live across 21 real policy documents converted via `create_doc_from_file`, every one needed manual `insert_doc_text` patches to restore lost paragraph breaks. General fix, not image-specific; doesn't require #333's image rendering to land first (PR #406) ([#401](https://github.com/khuisman/mcp-gee-sweet/issues/401))
- [x] Paragraphs containing only whitespace/`&nbsp;` are silently dropped — distinct root cause from #401 (this is an ordinary, fully-understood HTML character reference, not an unsupported construct; likely an empty-after-strip check skipping emission), but same silent-collapse symptom and same real-document discovery session (PR #441) ([#402](https://github.com/khuisman/mcp-gee-sweet/issues/402))
- [x] `style_doc_range` rejects `link_url=null` with "Links must include at least one type" instead of clearing an existing hyperlink — found while trying to strip a dead `#slug` anchor link left over from markdown conversion (see #409) (PR #446) ([#408](https://github.com/khuisman/mcp-gee-sweet/issues/408))
- [x] Markdown-to-Doc conversion keeps GitHub/GitLab-style `#slug` heading-anchor links as dead hyperlinks instead of resolving them to Docs-native internal links (`createNamedRange`/bookmark targets) — links render correctly on the source Markdown host but go nowhere once converted. Depends on #408 (need working link-clearing/rewriting first). (PR #453) ([#409](https://github.com/khuisman/mcp-gee-sweet/issues/409))
- [x] `_get_sheet_index` has the identical catch-and-swallow bug `_get_sheet_id` was just fixed for (#384/PR #390) — misreports transient API failures as "sheet not found" to its only caller, `duplicate_sheet`'s `insert_index` default. Same fix shape as #384, same file family (sheets, not docs) as #384's own fix (PR #440) ([#391](https://github.com/khuisman/mcp-gee-sweet/issues/391))
- [x] Thematic breaks (`---`) are silently dropped during markdown conversion with zero trace, worse than `docs/design/markdown-support.md` anticipated (that doc only discusses front-matter incidentally rendering as an `<hr>` paragraph, not vanishing entirely); confirmed resolved as a side effect of #401's general fix (PR #406) — closed as duplicate, no separate PR ([#399](https://github.com/khuisman/mcp-gee-sweet/issues/399))
- [x] `html_parser.py`: mismatched `<ol>`/`<ul>` close can leave a stale block-interruption frame that a later, unrelated list closes by coincidence — pre-existing, confirmed live during #382's own review round, distinct from #382's own fix (PR #478) ([#450](https://github.com/khuisman/mcp-gee-sweet/issues/450))
- [x] `html_parser.py`: whitespace-only `<pre>` resumed-block flush doesn't get the fresh-vs-resumed gate #402's fix gave other block tags — found during #402's own review round, pre-existing, confirmed live. Docs domain, sequence behind lane-b's current queue (PR #515) ([#443](https://github.com/khuisman/mcp-gee-sweet/issues/443))
- [x] Neither the AST schema nor `html_parser.py` has any concept of a blockquote — `<blockquote>`/`> quoted text` silently converts to a plain, visually indistinguishable `Paragraph`, no indent or styling of any kind. Docs domain, same conversion-pipeline surface as #334 (lane-b's current ticket) — sequence behind it rather than run in parallel ([#476](https://github.com/khuisman/mcp-gee-sweet/issues/476)) (PR #546)
- [x] Inline-image pre-validation (#400) only checks Google's 25-megapixel ceiling, not its 50MB file-size ceiling — a large, low-compressibility image under the megapixel limit passes `check_image_bytes` silently and only fails later at the real Docs API call; `auto_downscale=True` also has no effect for this case, since the downscale path only triggers off a `check_image_bytes` error. Confirmed live during #400/PR #554's QA round 2. ([#562](https://github.com/khuisman/mcp-gee-sweet/issues/562), PR #580)
- [x] `list_calendar_acl` doesn't handle pagination (`nextPageToken`) — silently returns only the first page for a calendar with enough sharing entries to paginate. Calendar domain, found during #158's review round ([#460](https://github.com/khuisman/mcp-gee-sweet/issues/460)) (PR #612)
- [x] `add_calendar_acl` silently ignores `scope_value` when `scope_type='default'` instead of rejecting it — docstring implies it's optional/ignored but the real behavior is undocumented silent acceptance of a value that has no effect; live-verified. Calendar domain, found during #158's review round ([#458](https://github.com/khuisman/mcp-gee-sweet/issues/458)) (PR #616)
- [x] Three `convert_markdown` matching/status-reporting edge cases found during PR #414's round-3 review — `drive_map` has no collision guard between a plain file and a converted Doc sharing the same name; `_upload_local_file` never stamps `modifiedTime` on a converted Doc, so it falls outside the sync tolerance and reports `conflict` instead of `skipped` on almost every first re-sync after `upload_local_file(convert=True)`; a drive-only converted Doc always reports `conflict` even when `direction='upload'`. Two of the three confirmed live. `ready-for-development`/`lane-a` — scoped entirely to `transfer.py`, distinct from lane-b's docs-emitter defect chain, so it runs in parallel rather than queuing behind it ([#422](https://github.com/khuisman/mcp-gee-sweet/issues/422)) (PR #433)

**Sheets**
- [x] `update_borders` — border style, width, color on a range (PR #325) ([#122](https://github.com/khuisman/mcp-gee-sweet/issues/122)) _(freema/mcp-gsheets)_
- [x] `hide_rows` / `hide_columns` / unhide — toggle row or column visibility ([#123](https://github.com/khuisman/mcp-gee-sweet/issues/123)) _(freema/mcp-gsheets)_ (PR #311)
- [x] `resize_rows` / `resize_columns` — set pixel height/width, or auto-fit to content (PR #321) ([#124](https://github.com/khuisman/mcp-gee-sweet/issues/124)) _(freema/mcp-gsheets)_
- [x] `add_data_validation` / `get_data_validation` — dropdowns, checkboxes, value constraints ([#125](https://github.com/khuisman/mcp-gee-sweet/issues/125)) _(freema/mcp-gsheets)_ (PR #361)
- [x] `update_sheet_properties` — tab color, hide/show gridlines (PR #301) ([#126](https://github.com/khuisman/mcp-gee-sweet/issues/126)) _(freema/mcp-gsheets)_
- [x] `duplicate_sheet` — copy a sheet within the same spreadsheet (PR #286) ([#127](https://github.com/khuisman/mcp-gee-sweet/issues/127))
- [x] Partial (rich-text) hyperlinks in `update_cells` (PR #380) ([#89](https://github.com/khuisman/mcp-gee-sweet/issues/89))
- [x] `import_csv_to_sheet` — populate a spreadsheet from a local CSV file (PR #272) ([#187](https://github.com/khuisman/mcp-gee-sweet/issues/187))

**Calendar**
- [x] `create_calendar` / `update_calendar` / `delete_calendar` — calendar lifecycle (PR #266) ([#156](https://github.com/khuisman/mcp-gee-sweet/issues/156))
- [x] `add_calendar_to_list` / `remove_calendar_from_list` — subscribe/unsubscribe (PR #269) ([#157](https://github.com/khuisman/mcp-gee-sweet/issues/157))
- [x] Calendar ACL — share a calendar with users or groups (PR #455) ([#158](https://github.com/khuisman/mcp-gee-sweet/issues/158))
- [x] `list_all_events` — query all subscribed calendars in parallel, reusing the `asyncio.gather`/`execute_in_thread` pattern #183 established and the inline-per-item-error convention already used by `get_multiple_sheet_data`/`share_spreadsheet`/`share_file` (both open questions resolved; no longer decision-blocked) `ready-for-development`/`lane-a` ([#194](https://github.com/khuisman/mcp-gee-sweet/issues/194)) (PR #464)
- [x] Non-blocking follow-ups from #194/PR #464's review: `scripts/gen_tool_docs.py`'s "Calendar only" `SUBSETS` entry omits `list_all_events`, shaping code duplicated with `list_events`, no concurrency cap on the parallel fan-out. No lane assignment yet ([#466](https://github.com/khuisman/mcp-gee-sweet/issues/466)) (PR #625)

**Docs**
- [x] `insert_page_break` — explicit page break at an index ([#148](https://github.com/khuisman/mcp-gee-sweet/issues/148)) (PR #314)
- [x] `merge_table_cells` — merge cells in an existing table (distinct from write-time colspan) ([#150](https://github.com/khuisman/mcp-gee-sweet/issues/150)) (PR #310)
- [x] Comments API — list, add, resolve doc comments (PR #324) ([#151](https://github.com/khuisman/mcp-gee-sweet/issues/151))
- [x] `create_named_range` / `create_bookmark` — anchor points for internal links (PR #337) ([#152](https://github.com/khuisman/mcp-gee-sweet/issues/152))
- [x] Rowspan emitter — closed as duplicate, already implemented via #100 (rowspan support) and PR #287 (nested-table colspan/rowspan) ([#195](https://github.com/khuisman/mcp-gee-sweet/issues/195))
- [x] Warn/error on mixed text + nested table in same cell — shipped as the fuller `Cell.children: list[Run | Table]` ordered model, also fixing trailing-text-after-nested-table ordering ([#275](https://github.com/khuisman/mcp-gee-sweet/issues/275)) in the same PR (PR #276) ([#108](https://github.com/khuisman/mcp-gee-sweet/issues/108))
- [x] colspan/rowspan inside nested tables (PR #287) ([#109](https://github.com/khuisman/mcp-gee-sweet/issues/109))
- [x] `find_in_doc` — search doc text and return match locations, parallel to `find_in_spreadsheet`; removes the manual index math currently needed to retrofit links (or any style) onto text already in a doc, raised while fixing #248 (PR #353) ([#262](https://github.com/khuisman/mcp-gee-sweet/issues/262))
- [x] Markdown-to-Doc image support — `![alt](path)` silently dropped today; local file path, `drive:<id>`, or HTTPS URL should all resolve to an inline image at the right position — deprioritized behind formatting fixes (#401/#402/#399, #403/#404) per user request; no lane assignment yet (PR #502) ([#333](https://github.com/khuisman/mcp-gee-sweet/issues/333))
- [x] `insert_inline_image` fails with the raw Google Docs API error ("The provided image is too large") for images over ~25 megapixels — no upfront size check, no mention of the actual limit or the image's own megapixel count; diagnosing required external tooling (`sips`) and prior knowledge of Google's ceiling. Same image codepath as #333, which has since shipped (PR #502) — no longer blocked. ([#400](https://github.com/khuisman/mcp-gee-sweet/issues/400)) (PR #554)
- [x] Expose paragraph list/nesting info in `get_doc_structure`, plus a tool to set/change bullet membership and nesting level on an existing range (`createParagraphBullets`/`deleteParagraphBullets` equivalent) — markdown converter currently flattens indented sub-lists into the parent list with no way to detect or fix it after the fact ([#334](https://github.com/khuisman/mcp-gee-sweet/issues/334)) (PR #524)
- [x] Soft-break paragraph helper (single paragraph, multiple lines joined by soft breaks, explicit named style) + document `delete_doc_range`'s paragraph-merge-inherits-neighbor-style behavior ([#332](https://github.com/khuisman/mcp-gee-sweet/issues/332)) (PR #362)
- [x] `update_doc_from_file` — update an existing Doc in place from a local `.md`/`.html` file, reading server-side like `create_doc_from_file` instead of round-tripping full content through the caller's context; real friction confirmed live — reporter had to fake this via delete-then-recreate. Wants #401/#402 landed first so the same paragraph-collapse defects don't just resurface via the update path ([#341](https://github.com/khuisman/mcp-gee-sweet/issues/341)) (PR #564)
- [x] `style_doc_table_cells` applies `border_color`/`border_width`/`border_dash_style` uniformly to all four cell edges — no per-edge control (top/bottom/left/right independently), even though the Docs API's own `TableCellBorder` supports it; blocks the classic "signature line" (bottom-border-only) cell pattern. Queued for lane-b behind #409/#382's remaining defect chain (defect-before-enhancement precedent) ([#403](https://github.com/khuisman/mcp-gee-sweet/issues/403)) (PR #462)
- [x] No way to set custom paragraph tab stops — Docs API supports `tabStops` on `paragraphStyle` directly, wrapper doesn't expose it; needed for form-style label/value column alignment without building a full table. Closed as infeasible — `ParagraphStyle.tabStops` is read-only in the Docs API, confirmed via live discovery-schema check (PR #471); follow-up #473 documented the borderless-table workaround ([#404](https://github.com/khuisman/mcp-gee-sweet/issues/404))
- [x] Markdown export for Google Docs — `get_doc_content` (and/or `export_file`) has no markdown output, only plain-text; the write side already has a full HTML→AST→emitter markdown pipeline, but nothing mirrors it on read. Real competitive gap (taylorwilsdon's server has this). No lane assignment yet ([#300](https://github.com/khuisman/mcp-gee-sweet/issues/300)) (PR #591)
- [x] Extract `named_ranges.py` from `content.py` — `create_named_range`/`create_bookmark` share one private helper and have no dependency on anything else in the file; zero-risk mechanical move, do first, unblocks #339/#340 to be built directly against the new module ([#371](https://github.com/khuisman/mcp-gee-sweet/issues/371)) (PR #570)
- [x] Split remaining `content.py` responsibilities into `editing.py` (range-mutation tools) and `images.py` (image insertion), relocate the shared `_collect_doc_paragraphs`/`_utf16_units` offset helpers into `ast.py`, drop dead `_html_to_text` — sequenced after #360 merges, since that PR touches the exact helpers being relocated ([#372](https://github.com/khuisman/mcp-gee-sweet/issues/372), PR #576)

**Drive**
- [x] `restore_file` / `empty_trash` — undelete or permanently purge trashed files (PR #386) ([#138](https://github.com/khuisman/mcp-gee-sweet/issues/138))
- [x] `star_file` / `unstar_file` — mark files with a star for easy retrieval (PR #387) ([#139](https://github.com/khuisman/mcp-gee-sweet/issues/139))
- [x] `transfer_ownership` — transfer a file to another user (PR #445) ([#140](https://github.com/khuisman/mcp-gee-sweet/issues/140))
- [x] `create_shortcut` — create a Drive shortcut to a file (PR #405) ([#141](https://github.com/khuisman/mcp-gee-sweet/issues/141))
- [x] `sync_folder` — option to convert markdown files to Google Docs on upload (PR #414) ([#211](https://github.com/khuisman/mcp-gee-sweet/issues/211))
- [x] `upload_local_file` with Drive format conversion (CSV→Sheets, MD→Docs) (PR #410) ([#188](https://github.com/khuisman/mcp-gee-sweet/issues/188))
- [x] Expose `md5Checksum` in `list_files`/`get_file_metadata` for real content-diffing, and let `sync_folder` diff by checksum instead of/in addition to `modifiedTime` — mtime is unreliable across in-place overwrites, `upload_local_file`'s "now" stamp, and content-preserving regenerations; related to #239 (PR #472) ([#274](https://github.com/khuisman/mcp-gee-sweet/issues/274))
- [x] Drive Activity API — file change history ([#72](https://github.com/khuisman/mcp-gee-sweet/issues/72))
- [x] `upload_local_folder` doesn't route through `_upload_local_file`, so the `convert` capability (#188) is unreachable from bulk folder uploads — no way to bulk-import a folder of CSV/DOCX/PPTX into native Workspace formats. Same domain as #274, candidate for lane-a once #274 ships (PR #505) ([#411](https://github.com/khuisman/mcp-gee-sweet/issues/411))
- [x] Reconcile the two independent Drive-conversion mechanisms — `_upload_local_file`'s `_CONVERT_MIME` map and `upload_file`'s `convert_to_doc` param do the same thing (source mimetype upload + destination-metadata mimeType override) with no cross-reference; risk of drift as more conversion paths get added. Related to #411 ([#412](https://github.com/khuisman/mcp-gee-sweet/issues/412), PR #543)
- [ ] `sync_folder`'s `convert_markdown` upload path: two Drive files sharing the same `geeSweetConvertMarkdownSource` property (e.g. a Drive-UI copy of a converted Doc) collide as the same `drive_map` key — the later one in iteration order silently wins with no error. Narrow trigger, flagged non-blocking during PR #414's round 2 QA review ([#419](https://github.com/khuisman/mcp-gee-sweet/issues/419))
- [x] `sync_folder`'s `convert_markdown` upload path: `create()` and its metadata-only `update()` re-stamp share one `try`/`except` — a transient failure in the second call after a successful `create()` reports `upload_fail` even though the Doc now exists in Drive, leaving an untracked orphan with no ID recorded. Same code path as #419 — candidate for one PR fixing both (PR #645) ([#420](https://github.com/khuisman/mcp-gee-sweet/issues/420))

**Infrastructure**
- [x] Harden concurrent-session access — fail-open on cache read/write errors, `busy_timeout` (PR #280) ([#234](https://github.com/khuisman/mcp-gee-sweet/issues/234))
- [x] Cache reliability & configurability — runtime-configurable TTL, smarter invalidation for shared files (PR #284) ([#99](https://github.com/khuisman/mcp-gee-sweet/issues/99))
- [x] Async tool execution — `asyncio.gather()` for parallel Google API calls; establishes the project's parallel-call pattern, which [#194](https://github.com/khuisman/mcp-gee-sweet/issues/194) should reuse rather than introducing its own `ThreadPoolExecutor` (PR #293) ([#183](https://github.com/khuisman/mcp-gee-sweet/issues/183))
- [x] Log the running `mcp-gee-sweet` package version at startup — `server.py::main()` logs tool-filtering state but never the version, which is dynamic (`uv-dynamic-versioning`) so needs an `importlib.metadata.version()` lookup rather than a static string (PR #479) ([#356](https://github.com/khuisman/mcp-gee-sweet/issues/356))
- [x] `server.py::main()`'s new version-logging call (#356) has no fallback for `importlib.metadata.PackageNotFoundError` — a broken/repackaged install or invoking `main()` directly without the package installed crashes the whole server before any tool-filtering log or transport startup, instead of degrading gracefully. Found during #356's own QA (PR #483) ([#481](https://github.com/khuisman/mcp-gee-sweet/issues/481))
- [x] `transfer_ownership` missing from `server://auth-status`'s `_SA_LIMITED_TOOLS` despite its own docstring documenting the OAuth-only restriction — found during #140's review. Needed a design call on generalizing `_auth_status_json`'s failure-reason schema (storage-quota vs. no-Drive-identity are different failure classes), so routed to Joy instead of Amy. (PR #507) ([#447](https://github.com/khuisman/mcp-gee-sweet/issues/447))
- [x] `server://auth-status`'s `auth_method: "adc"` can't distinguish a real user credential from a service-account-backed one (GCE/Cloud Run/GKE metadata identity, or `GOOGLE_APPLICATION_CREDENTIALS` pointed at a key file) — both get tagged plain `"adc"` with `can_create_in_personal_drive: true` and zero limitations, which is wrong whenever ADC resolves to a service account. Found during #447's design work; not blocking it. `ready-for-development` (on deck, no lane yet) ([#506](https://github.com/khuisman/mcp-gee-sweet/issues/506)) (PR #613)
- [x] Dependabot's `pip`-ecosystem config doesn't always regenerate `uv.lock` for a version bump (confirmed on 2 of 7 PRs in the same batch) — silently defeats every `--frozen` CI/release install, which doesn't validate lock-vs-manifest consistency. Immediate drift fixed by hand 2026-08-06; switched to native `uv` ecosystem config and added a lockfile-sync CI guard ([#528](https://github.com/khuisman/mcp-gee-sweet/issues/528), PR #533)
- [x] Migrate `mcp.server.fastmcp` → `mcp.server.mcpserver` (mcp SDK v2) — was held as a watch-item while v2 was alpha; `mcp` hit 2.0.0 stable 2026-08-20, live-confirmed `fastmcp` is fully removed (not deprecated) and `mcpserver.MCPServer` exists as expected (PR #642) ([#175](https://github.com/khuisman/mcp-gee-sweet/issues/175))

**Documentation**
- [x] Tool-count figures have drifted out of sync across README/`docs/roadmap.md`/`docs/tools.md` (the only auto-generated one, authoritative at 122) — generate the hand-maintained ones instead of manually recounting each time this is caught. Routed to Amy (PR #550) ([#467](https://github.com/khuisman/mcp-gee-sweet/issues/467))
- [x] Document `transfer_ownership`'s `server://auth-status` limitation once #447's schema work lands — the tool's own docstring already promises discoverability via that resource. Delivered as part of #447's own PR (`docs/auth.md`'s limitation bullet, `decision-auth-status-limitation-categories.md`, and QA's TC-I27) rather than as separate follow-up work; audited and confirmed complete, no additional doc changes needed. (PR #507) ([#503](https://github.com/khuisman/mcp-gee-sweet/issues/503))
- [x] Rewrite positioning/differentiation in README and `docs/index.md` — official Google MCP servers are now in developer preview, which undercuts the current "no official alternative exists" framing; lead with concrete differentiators (tool breadth, stability/QA gate, design philosophy) instead, checked against what the official servers actually cover (PR #306) ([#263](https://github.com/khuisman/mcp-gee-sweet/issues/263))
- [x] Markdown-support documentation gaps — README/`docs/tools.md`/`docs/known-limitations.md`/`docs/design/markdown-support.md` never caught up to the Docs markdown-input pipeline shipped via #102/#103/#104/#248; consolidates #297/#298/#299/#302 (PR #482) ([#303](https://github.com/khuisman/mcp-gee-sweet/issues/303))
- [x] `CLAUDE.md`'s `convert_markdown` note overstates its download-branch guard as reachable — round-2 review moved that case earlier in the plan-building loop, where it's now classified `conflict`, not `failed`; the guard described is dead defensive code, not live behavior. Found during PR #414's round-3 review, routed to Amy ([#423](https://github.com/khuisman/mcp-gee-sweet/issues/423)) (PR #492)

### v0.9.1 — Post-release defect fixes & infrastructure addons _(target: [v0.9.1](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.1), before Tier 3 begins)_

No new tools. Same shape as v0.8.1 — stabilize on defects that surfaced since v0.9.0 shipped, plus a handful of infrastructure/tooling additions that don't belong to any specific tool tier. Started because v0.9.0's own scope kept growing past its original Tier 2 definition; splitting this out keeps that pattern from repeating indefinitely.

**Defects**
- [ ] Isolated depth>0 bullet run renders the wrong glyph (disc instead of circle) despite correct indentation ([#439](https://github.com/khuisman/mcp-gee-sweet/issues/439))
- [ ] `_auth_status_json` silently overrides a caller passing an inconsistent `is_service_account_identity` instead of erroring or reconciling ([#614](https://github.com/khuisman/mcp-gee-sweet/issues/614))
- [ ] `_timed` logs a `200` status for tool calls that catch their own exception and return `{error: ...}` — observability reports success for a call that actually failed ([#579](https://github.com/khuisman/mcp-gee-sweet/issues/579))
- [ ] `emitter.py` table-cell images have no cursor-advance handling — latent infinite loop if that code path is ever reached ([#509](https://github.com/khuisman/mcp-gee-sweet/issues/509))
- [ ] Calendar ACL tools use a bare `except Exception` instead of the `HttpError` friendly-error pattern used elsewhere in `calendar.py` ([#459](https://github.com/khuisman/mcp-gee-sweet/issues/459))
- [ ] `sync_folder`'s `convert_markdown` restamp-failure handling: quota-message gap, duplicated create()+update() try/except, test fixture isolation — companion to #420 ([#650](https://github.com/khuisman/mcp-gee-sweet/issues/650))
- [ ] `sync_folder convert_markdown`'s `modifiedTime` restamp fires for all convert types (over-broad), and its create()+update() pattern is duplicated across two call sites ([#435](https://github.com/khuisman/mcp-gee-sweet/issues/435))
- [ ] Harden `tests/integration`'s local-fs live QA harness — error surfacing on API failures, subprocess/handshake timeouts, cleanup-masking a real test failure, per-test subprocess overhead ([#648](https://github.com/khuisman/mcp-gee-sweet/issues/648))

**Infrastructure**
- [ ] Interaction-log middleware for tool calls — structured, append-only JSONL log per call (inputs, duration, cache hit, error), opt-in ID redaction, swappable backend ([#646](https://github.com/khuisman/mcp-gee-sweet/issues/646))
- [ ] Automated tooling for dependency-bump security review — today's manual skim can miss a well-disguised supply-chain compromise ([#520](https://github.com/khuisman/mcp-gee-sweet/issues/520))
- [ ] CI: dedupe lint/format-check and lockfile-check across the Python version matrix ([#619](https://github.com/khuisman/mcp-gee-sweet/issues/619))
- [ ] Consolidate `uv lock --check` + `uv sync --frozen` into a single `uv sync --locked` step ([#536](https://github.com/khuisman/mcp-gee-sweet/issues/536))
- [ ] Catch stale hardcoded tool counts in prose docs at commit time, instead of by hand each time drift is caught ([#308](https://github.com/khuisman/mcp-gee-sweet/issues/308))

### v0.9.2 — Comments as a first-class, cross-suite capability _(target: [v0.9.2](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.2), before Tier 3 begins)_

Follows the design in [`docs/decisions/decision-comments-first-class.md`](decisions/decision-comments-first-class.md) ([#661](https://github.com/khuisman/mcp-gee-sweet/issues/661)): the Drive `comments`/`replies` resource is one generic, file-type-agnostic capability, but the codebase only ships a Docs-named `list`/`add`/`resolve` subset (#151). This release generalizes and completes it. Ships a breaking rename — no alias/deprecation mechanism exists in this codebase, so it must be called out explicitly in the release notes.

- [ ] Generalize the three comment tools to `tools/drive/comments.py` and rename `list_doc_comments`/`add_doc_comment`/`resolve_doc_comment` → `list_file_comments`/`add_file_comment`/`resolve_comment` (param `doc_id` → `file_id`); retire `tools/docs/comments.py`. Breaking change. ([#663](https://github.com/khuisman/mcp-gee-sweet/issues/663))
- [ ] Full `comments`/`replies` CRUD parity — `get`/`update`/`delete` for comments; plain `reply`/`reopen`/`update`/`delete`/`list` for replies. Depends on #663. ([#664](https://github.com/khuisman/mcp-gee-sweet/issues/664))
- [ ] Fix the stale Tier 4 "zero comment tooling on Docs today" line; close or re-scope #142 (asks for what #151 already shipped under different naming). ([#662](https://github.com/khuisman/mcp-gee-sweet/issues/662))
- [ ] **Decision needed:** deprecate `share_spreadsheet` in favor of `share_file` (a strict superset over the same `permissions()` resource), or keep both and document why. Same pattern as #151/#142, with a longer compatibility tail. ([#665](https://github.com/khuisman/mcp-gee-sweet/issues/665))

### Tier 3 — Advanced / occasionally needed _(target: [v1.0.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av1.0))_

**Sheets**
- [ ] `add_conditional_formatting` / `delete_conditional_formatting` ([#129](https://github.com/khuisman/mcp-gee-sweet/issues/129)) _(freema/mcp-gsheets)_
- [ ] `add_named_range` / `delete_named_range` ([#130](https://github.com/khuisman/mcp-gee-sweet/issues/130)) _(piotr-agier/google-drive-mcp)_
- [ ] `protect_sheet` / `protect_range` — lock a sheet or range against edits ([#128](https://github.com/khuisman/mcp-gee-sweet/issues/128)) _(piotr-agier/google-drive-mcp)_
- [ ] `set_basic_filter` / `clear_basic_filter` — toggle autofilter on a range ([#196](https://github.com/khuisman/mcp-gee-sweet/issues/196)) _(freema/mcp-gsheets)_

**Calendar**
- [ ] `quick_add` — create an event from a natural language string ([#159](https://github.com/khuisman/mcp-gee-sweet/issues/159))
- [ ] Event color coding — `colorId` on create/update ([#160](https://github.com/khuisman/mcp-gee-sweet/issues/160))
- [ ] Conference data — auto-create Google Meet link ([#161](https://github.com/khuisman/mcp-gee-sweet/issues/161))
- [ ] Event attachments — link Drive files to events ([#162](https://github.com/khuisman/mcp-gee-sweet/issues/162))
- [ ] Reminders — per-event override reminders (email, popup, minutes before) ([#163](https://github.com/khuisman/mcp-gee-sweet/issues/163))

**Docs**
- [ ] `create_footnote` — footnote at a run index ([#149](https://github.com/khuisman/mcp-gee-sweet/issues/149))
- [ ] `create_table_of_contents` ([#153](https://github.com/khuisman/mcp-gee-sweet/issues/153))
- [ ] `insert_section_break` — section breaks for per-section column/margin layout ([#154](https://github.com/khuisman/mcp-gee-sweet/issues/154))

**Drive**
- [ ] File comments — list and add comments on Drive files ([#142](https://github.com/khuisman/mcp-gee-sweet/issues/142))
- [ ] Watch notifications — webhook push on file changes ([#143](https://github.com/khuisman/mcp-gee-sweet/issues/143))
- [ ] Labels API — custom metadata labels on Drive files ([#144](https://github.com/khuisman/mcp-gee-sweet/issues/144))
- [ ] `empty_trash` — optional fan-out across all accessible Shared Drives in one call, instead of one call per drive; considered and deliberately deferred during #386's review ([#389](https://github.com/khuisman/mcp-gee-sweet/issues/389))

### Tier 4 — Nice to have / niche _(no assigned version)_

**Sheets**
- [ ] `get_sheet_dimensions` — read column widths, row heights, frozen counts ([#132](https://github.com/khuisman/mcp-gee-sweet/issues/132)) _(freema/mcp-gsheets)_
- [ ] `add_note` / `clear_note` — cell notes (distinct from comments) ([#131](https://github.com/khuisman/mcp-gee-sweet/issues/131)) _(freema/mcp-gsheets)_
- [ ] Pivot tables — create and update pivot table specs via batchUpdate ([#133](https://github.com/khuisman/mcp-gee-sweet/issues/133))
- [ ] Developer metadata — key-value metadata attached to rows, columns, or ranges ([#134](https://github.com/khuisman/mcp-gee-sweet/issues/134))
- [ ] Sheet comments and cell notes (add/get/list/reply/resolve/delete) — we have zero comment tooling on Sheets today _(a-bonus/google-docs-mcp)_
- [ ] Conditional formatting rules — add/get/delete _(a-bonus/google-docs-mcp)_
- [ ] Protected ranges — protect/unprotect a range _(a-bonus/google-docs-mcp)_
- [ ] Dropdown / data validation on a range _(a-bonus/google-docs-mcp)_
- [ ] Row grouping (outline/collapse) — group/ungroup rows _(a-bonus/google-docs-mcp)_
- [ ] Auto-resize columns/rows to fit content _(a-bonus/google-docs-mcp)_
- [ ] Write-side column widths / row heights — companion to the read-only `get_sheet_dimensions` above ([#132](https://github.com/khuisman/mcp-gee-sweet/issues/132)) _(a-bonus/google-docs-mcp)_
- [ ] Native Sheets "Tables" object support (create/list/get/delete/update a structured Table, distinct from a plain range) — a newer Sheets API feature we don't touch at all _(a-bonus/google-docs-mcp)_
- [ ] Copy formatting only, without values (paste-special-style) _(a-bonus/google-docs-mcp)_

**Docs**
- [ ] Doc comments (add/get/list/reply/resolve/delete) — we have zero comment tooling on Docs today _(a-bonus/google-docs-mcp)_
- [ ] Multi-tab document support (list/add/rename tabs) — Google Docs' newer per-document tabs feature _(a-bonus/google-docs-mcp)_
- [ ] Smart chips — date chips, person chips, rich links; `list_smart_chips` to enumerate existing ones _(a-bonus/google-docs-mcp)_
- [ ] Section breaks and per-section page styling _(a-bonus/google-docs-mcp)_
- [ ] Page breaks _(a-bonus/google-docs-mcp)_
- [ ] Table structure discovery and cloning (read a table's row/column structure; clone an existing table) _(a-bonus/google-docs-mcp)_
- [ ] Finer-grained table styling — per-border, per-column-width, per-row-height table styling beyond what `style_doc_table_cells` currently exposes _(a-bonus/google-docs-mcp)_
- [ ] Footnote management _(piotr-agier/google-drive-mcp)_

**Calendar**
- [ ] Working location / OOO / Focus time events ([#164](https://github.com/khuisman/mcp-gee-sweet/issues/164))
- [ ] Watch notifications — webhook push on calendar or event changes ([#165](https://github.com/khuisman/mcp-gee-sweet/issues/165))

**Infrastructure**
- [x] `notifications/progress` feedback for long-running transfer calls (`download_folder`, `sync_folder`) — no tool uses MCP progress reporting today, would establish a new pattern; split from #316 (PR #351) ([#319](https://github.com/khuisman/mcp-gee-sweet/issues/319))

### Decisions Needed — blocking backlog _(no assigned version)_

Design questions raised during Phase 1 QA that need a deliberate product/API decision rather than just code. Each blocks whichever tool it names until resolved — pick these up opportunistically alongside the tool they affect, or dedicate a pass to clear the backlog.

- [ ] `get_sheet_data` on an unknown sheet — exception vs structured error ([#31](https://github.com/khuisman/mcp-gee-sweet/issues/31))
- [ ] `batch_update_cells` empty input — validation error vs silent no-op ([#32](https://github.com/khuisman/mcp-gee-sweet/issues/32))
- [ ] `add_rows` count cap — accept unlimited or enforce a maximum ([#33](https://github.com/khuisman/mcp-gee-sweet/issues/33))
- [ ] `rename_sheet` same-name — skip the API call or always round-trip ([#34](https://github.com/khuisman/mcp-gee-sweet/issues/34))
- [ ] `create_sheet` duplicate title — API error or auto-suffix ([#35](https://github.com/khuisman/mcp-gee-sweet/issues/35))
- [ ] Hide Drive-create tools from the toolset when service account auth is detected ([#36](https://github.com/khuisman/mcp-gee-sweet/issues/36))
- [ ] `list_spreadsheets` with no folder — all accessible or Drive root ([#37](https://github.com/khuisman/mcp-gee-sweet/issues/37))
- [ ] Validate ownership before `share_spreadsheet` / `share_file` ([#38](https://github.com/khuisman/mcp-gee-sweet/issues/38))
- [ ] `search_spreadsheets` empty query — return all or require non-empty input ([#39](https://github.com/khuisman/mcp-gee-sweet/issues/39))
- [ ] `get_file_metadata` size field for Workspace files — normalize or document ([#40](https://github.com/khuisman/mcp-gee-sweet/issues/40))
- [ ] `rows_to_fetch=0` — clamp to 1 or return all rows ([#78](https://github.com/khuisman/mcp-gee-sweet/issues/78))

---

## Bugs found in Phase 1 QA run (2026-06-02)

### `add_chart` — multi-column range fails (BUG-1)
**Severity:** High — affects all practical chart use cases.
The tool passes the full data range (e.g. `A1:D5`) as a single `ChartSourceRange`. The Sheets API requires separate source range objects per column — one for the domain (X axis / categories) and one per series. Fix: parse the A1 range, split into domain (first column) and series (remaining columns), pass as separate entries in `sources`. ✅ Fixed.

### `add_chart` HISTOGRAM — wrong API spec (BUG-2)
**Severity:** Medium — HISTOGRAM specifically broken even after BUG-1 fixed.
`HISTOGRAM` is not a valid `BasicChartType` enum value. The Sheets API uses a `histogramChart` spec field rather than `basicChart.chartType`. Fix: detect `chart_type == "HISTOGRAM"` and build a `histogramChart` spec instead. ✅ Fixed.

### `add_chart` BAR — wrong series target axis (BUG-3)
**Severity:** Medium — BAR charts fail with "series may only target the BOTTOM_AXIS".
BAR charts (horizontal) have a horizontal value axis. Series must target `BOTTOM_AXIS`, not `LEFT_AXIS`. Fix: detect `chart_type == "BAR"` and set `targetAxis` accordingly. ✅ Fixed.

### `add_chart` COMBO — no per-series type specified (BUG-4)
**Severity:** Medium — COMBO charts fail with "No basic chart type specified".
The Sheets API requires each series in a COMBO chart to declare its own `type`. Fix: when `chart_type == "COMBO"`, add `type: COLUMN` to all series except the last, which gets `type: LINE`. ✅ Fixed.

### TC-W03 — test case assumption wrong
The test expected the API to silently truncate a 2D array that's wider than the target range. The API actually rejects it with a 400 error. The test case needs to be updated to reflect correct API behaviour. ✅ Fixed.

---

## Testing

### Unit tests (456 passing as of 2026-06-24)
- [x] Add `pytest` and `pytest-cov` as dev dependencies
- [x] Cache logic — TTL expiry, dirty flag, partial invalidation for all five cache classes; in-memory SQLite
- [x] A1 notation helpers — `_parse_a1_notation`, `_column_index_to_letter`, `_letter_to_column_index`
- [x] Tool filtering — tools excluded when not in `ENABLED_TOOLS`
- [x] Service account quota error handling — structured error on 403 quota exceeded; non-quota 403s raise
- [x] `server://auth-status` resource — correct capabilities for service_account, oauth, and adc
- [x] Docs AST pipeline — `html_to_ast`, `ast_to_requests`, `fill_tables`, nested table emitter, cell style emitter, run style Phase 3 fields
- [x] Docs tools — `write_doc_content`, `style_doc_range`, `style_doc_table_cells`, `get_doc_theme`, `get_doc_named_styles`, `apply_theme`
- [x] Fix BUG-1–4: `add_chart` multi-column ranges, HISTOGRAM spec, BAR axis, COMBO per-series types
- [x] Update TC-W03 test case — API rejects oversized 2D arrays, does not silently truncate

### Live QA (AI-driven test cases in `docs/qa/tests/`)
- [x] Sheets read, write, management, charts — `sheets_read.md`, `sheets_write.md`, `sheets_mgmt.md`, `sheets_charts.md`
- [x] Drive files and sharing — `drive.md`
- [x] Google Docs tools (all 13) — `docs.md`
- [x] Calendar tools — `calendar.md`
- [x] Infrastructure — `infra.md`
- [ ] QA gaps targeted for v0.9 — disposition of v0.8.0 SKIP entries, done, triaged the rest below ([x] [#227](https://github.com/khuisman/mcp-gee-sweet/issues/227), PR #493); dedicated QA Google account + calendar + pollution root-cause fixes, consolidates #225/#226/#249 ([#304](https://github.com/khuisman/mcp-gee-sweet/issues/304)); second Drive folder + shared drive fixtures, consolidates #44/#48 ([#305](https://github.com/khuisman/mcp-gee-sweet/issues/305)); domain/public sharing coverage ([#49](https://github.com/khuisman/mcp-gee-sweet/issues/49)); local-filesystem coverage ([x] [#50](https://github.com/khuisman/mcp-gee-sweet/issues/50), PR #644); environment-constraint coverage, likely closes as duplicate once #48/#49 are disposed — not yet closed ([#53](https://github.com/khuisman/mcp-gee-sweet/issues/53)); split `drive.md`/`docs.md` test files by submodule, do before #264/#224 to avoid a file-rename conflict ([x] [#233](https://github.com/khuisman/mcp-gee-sweet/issues/233), PR #582); Playwright tag consistency audit + formalize the required/spot-check/skip tiers, raised while fixing #248, sequenced after #233 ([x] [#264](https://github.com/khuisman/mcp-gee-sweet/issues/264), PR #592, #598); image fixtures for `insert_inline_image`, sequenced after #233 ([x] [#224](https://github.com/khuisman/mcp-gee-sweet/issues/224), PR #639); dedicated screenshots folder, independent of the rest ([x] [#231](https://github.com/khuisman/mcp-gee-sweet/issues/231), PR #583); `add_chart` test cases leave charts behind with no teardown, polluting the shared Sales fixture across every QA run — same pollution-cluster shape as #304/#305 ([x] [#322](https://github.com/khuisman/mcp-gee-sweet/issues/322), PR #633); plus 7 small unit-test-coverage gaps filed 2026-08-02/08, each self-contained/ad hoc pickup — [x] [#487](https://github.com/khuisman/mcp-gee-sweet/issues/487) (PR #559), [x] [#488](https://github.com/khuisman/mcp-gee-sweet/issues/488) (PR #563), [x] [#489](https://github.com/khuisman/mcp-gee-sweet/issues/489) (PR #569), [x] [#490](https://github.com/khuisman/mcp-gee-sweet/issues/490) (PR #572), [x] [#491](https://github.com/khuisman/mcp-gee-sweet/issues/491) (PR #575), [x] [#494](https://github.com/khuisman/mcp-gee-sweet/issues/494) (PR #577), [x] [#495](https://github.com/khuisman/mcp-gee-sweet/issues/495) (PR #634)
- See [GitHub Issues (label: qa)](https://github.com/khuisman/mcp-gee-sweet/issues?q=label%3Aqa) for open QA gaps and fixture issues

---

## Infrastructure / internal

- [x] Migrate cache persistence — replaced four `/tmp/*.json` files with a single SQLite DB (`/tmp/mcp_gee_sweet.db`, configurable via `CACHE_DB_PATH`); one table, four namespaces; WAL mode
- [x] Open PR to xing5 from `upstream-observability` branch (structured logging, per-tool timing, `cache_discovery=False`) — [PR #79](https://github.com/xing5/mcp-google-sheets/pull/79)
- [x] Fork repo and rename to `mcp-gee-sweet`; README credits xing5, freema, and piotr-agier
- [x] PyPI publish — v0.7.0 stable on PyPI; dev track publishes `0.7.0.devN` on every push to `develop`
- [ ] Live QA system — fixture setup, per-release run files (`docs/qa/runs/vX.Y.Z.md`), Playwright OAuth automation ([#173](https://github.com/khuisman/mcp-gee-sweet/issues/173)) _(gate for v0.8.0)_
- See [GitHub Issues (label: infrastructure)](https://github.com/khuisman/mcp-gee-sweet/issues?q=label%3Ainfrastructure) for open infrastructure work

---

## Future domains

### Tasks

Requires `tasks/v1` client and `https://www.googleapis.com/auth/tasks` scope. Add `tasks_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan alongside the existing clients.

**Task lists**
- [ ] `list_task_lists` — list all task lists for the authenticated user
- [ ] `get_task_list` — fetch metadata for a single task list
- [ ] `create_task_list` — create a new task list
- [ ] `delete_task_list` — delete a task list and all its tasks

**Tasks**
- [ ] `list_tasks` — list tasks in a task list with optional due date filter and completed/hidden flags
- [ ] `get_task` — fetch a single task by task list ID + task ID
- [ ] `create_task` — create a task (title, notes, due date, parent for subtasks)
- [ ] `update_task` — update fields on an existing task (`tasks().patch()`)
- [ ] `delete_task` — delete a task
- [ ] `complete_task` — mark a task as completed (shortcut for `update_task` with `status='completed'`)
- [ ] `clear_completed` — delete all completed tasks from a list (`tasks().clear()`)

### Gmail

Requires `gmail/v1` client and `https://www.googleapis.com/auth/gmail.modify` scope (or narrower `gmail.readonly` / `gmail.send` scopes where appropriate). Add `gmail_service` to `SpreadsheetContext` and wire up in `auth.py` lifespan.

**Reading**
- [ ] `list_messages` — list messages with optional query string (same syntax as Gmail search), label filter, and pagination
- [ ] `get_message` — fetch a single message by ID; return headers, body (plain text + HTML), and attachment metadata
- [ ] `list_threads` — list conversation threads with optional query and label filter
- [ ] `get_thread` — fetch all messages in a thread
- [ ] `list_labels` — list all labels (system and user-defined)

**Sending and drafts**
- [ ] `send_message` — send an email (to, cc, bcc, subject, body, optional attachments)
- [ ] `create_draft` — create a draft without sending
- [ ] `send_draft` — send an existing draft by ID
- [ ] `reply_to_message` — send a reply in an existing thread

**Organization**
- [ ] `modify_labels` — add or remove labels from a message or thread (covers archive, mark read/unread, star, etc.)
- [ ] `trash_message` — move a message to trash
- [ ] `delete_message` — permanently delete a message

---

## Potential / under consideration

- **Google Keep** — philosophically in scope (Workspace productivity tool) but the Keep API v1 is read-only for most operations and was historically restricted to Workspace Business/Enterprise accounts. Creating and editing notes via an officially supported third-party API is not currently possible. Revisit if Google opens the API further.

- **SQLite cache encryption at rest** — the cache DB (`/tmp/mcp_gee_sweet.db`) stores Google Sheets data in plaintext. For deployments that handle sensitive data, consider [SQLCipher](https://www.zetetic.net/sqlcipher/) (open-source, AES-256, mostly API-compatible with standard SQLite) or rely on filesystem-level encryption (FileVault, LUKS, BitLocker). The official SQLite Encryption Extension (SEE) is an alternative but is commercial/proprietary. Not needed for typical local-dev use.

---

## Inspiration and credits

- [xing5/mcp-google-sheets](https://github.com/xing5/mcp-google-sheets) — original upstream this project was forked from
- [freema/mcp-gsheets](https://github.com/freema/mcp-gsheets) — most comprehensive Sheets-specific MCP server; primary source for formatting, validation, and sheet property roadmap items
- [piotr-agier/google-drive-mcp](https://github.com/piotr-agier/google-drive-mcp) — full Workspace suite; primary source for Drive file operations, permissions, and named/protected range roadmap items
- [a-bonus/google-docs-mcp](https://github.com/a-bonus/google-docs-mcp) — source-verified ~44 Sheets tools / ~39 Docs tools (one-file-per-operation style, exceeds its own README's claimed counts); primary source for the Sheets comments/conditional-formatting/protected-ranges/validation/grouping cluster and the Docs comments/tabs/smart-chips/section-breaks cluster added 2026-07-14
- [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp) — 12-service, source-verified 115-tool server; only project reviewed with a confirmed Markdown *export* tool (`get_doc_as_markdown`, see [#300](https://github.com/khuisman/mcp-gee-sweet/issues/300)) — our Markdown support is currently input-only
