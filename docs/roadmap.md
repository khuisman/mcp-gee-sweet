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
| [**v0.9.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9) | ✅ Tier 2 complete — power-user and structured-work layer, plus defects that surfaced after v0.8.1 shipped ([#248](https://github.com/khuisman/mcp-gee-sweet/issues/248)) | Published 2026-09-08 |
| [**v0.9.1**](https://github.com/khuisman/mcp-gee-sweet/releases/tag/v0.9.1) | ✅ Security hotfix cut from v0.9.0 — `download_file`, `download_folder`, and `sync_folder` keep every write inside `local_path`. Nothing else from `develop` | Published 2026-10-04 |
| [**v0.9.2**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.2) | Post-release defect fixes & infrastructure addons, plus the Gmail domain (pulled forward from v1.1+ 2026-09-23, community PR #786) | Stabilizes before Tier 3 begins |
| [**v0.9.3**](https://github.com/khuisman/mcp-gee-sweet/releases/tag/v0.9.3) | ✅ Security release — fixes GHSA-mpw3-mr4r-6cqh and GHSA-8jqx-w7j8-6xwm, plus what merged since v0.9.2 (#1052, #1124) | Published 2026-10-21 |
| [**v0.9.4**](https://github.com/khuisman/mcp-gee-sweet/releases/tag/v0.9.4) | ✅ Security hotfix cut from v0.9.3: Pillow 13.0.0 for 12.3.0's open CVEs, which drops Python 3.10 ([#1158](https://github.com/khuisman/mcp-gee-sweet/issues/1158)). Nothing else from `develop` | Published 2026-10-22 |
| [**ornithomimus**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22planned%3A+ornithomimus%22) | Queued, next after v0.9.4. Feature set: Markdown → Docs fidelity (#1044 and its defects), comments as a first-class capability (breaking rename), Gmail sending safety, launch readiness. Plus a ranked fill (was v0.9.4 until 2026-10-22) | Gets a number when it goes in flight |
| [**ankylosaurus**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22planned%3A+ankylosaurus%22) | Queued: hardening. Feature set not yet set; fill candidates moved from the v0.9.4 feature set (then numbered v0.9.3) and the decision backlog 2026-10-18 | Gets a number when it goes in flight |
| [**v1.0.0**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av1.0) | API stability declaration — Tier 3 items that make the cut + any breaking cleanups from v0.8–0.9 | Backwards-compatibility commitment |
| [**v1.1.0+**](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22v1.1%2B%22) | Future domains — Tasks (separate minor release, needs a new API client; Gmail pulled forward to v0.9.2) | Expanded scope |

Tier 4 items remain backlog with no assigned version.

**Queued versions are named, not numbered** (#1085). A version is a named feature set plus a locked fill. Until it's in flight, its section below is headed by its name and its tickets carry a `planned: <name>` label, so queued versions can be reordered and a hotfix doesn't renumber them. Only the in-flight version gets a number (the next tag in sequence); at that point its `planned:` label becomes `vX.Y.Z` and its section heading becomes `vX.Y.Z — <Name>`. The full rules are in `.claude/team-roles/kai.md` §"Release scoping".

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
- [x] Define and document community PR expectations — template, testing bar for non-tool PRs, scope/size convention, CLA/DCO/code-of-conduct decision, review turnaround ([#237](https://github.com/khuisman/mcp-gee-sweet/issues/237))

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
- [x] `sync_folder`'s `convert_markdown` upload path: two Drive files sharing the same `geeSweetConvertMarkdownSource` property (e.g. a Drive-UI copy of a converted Doc) collide as the same `drive_map` key — the later one in iteration order silently wins with no error. Narrow trigger, flagged non-blocking during PR #414's round 2 QA review ([#419](https://github.com/khuisman/mcp-gee-sweet/issues/419))
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
- [x] Docs version switcher never renders and each release's `mike deploy` overwrites the previous version instead of versioning alongside it — the `latest`/`develop` split from #267 isn't actually working — config/workflow fix in PR #668; post-merge `gh-pages` ops (purged the stale pre-`mike` tree, `mike set-default develop`) done + live-verified: root redirects to `/develop/`, switcher renders, stale paths 404 ([#667](https://github.com/khuisman/mcp-gee-sweet/issues/667))

**Documentation**
- [x] Tool-count figures have drifted out of sync across README/`docs/roadmap.md`/`docs/tools.md` (the only auto-generated one, authoritative at 122) — generate the hand-maintained ones instead of manually recounting each time this is caught. Routed to Amy (PR #550) ([#467](https://github.com/khuisman/mcp-gee-sweet/issues/467))
- [x] Document `transfer_ownership`'s `server://auth-status` limitation once #447's schema work lands — the tool's own docstring already promises discoverability via that resource. Delivered as part of #447's own PR (`docs/auth.md`'s limitation bullet, `decision-auth-status-limitation-categories.md`, and QA's TC-I27) rather than as separate follow-up work; audited and confirmed complete, no additional doc changes needed. (PR #507) ([#503](https://github.com/khuisman/mcp-gee-sweet/issues/503))
- [x] Rewrite positioning/differentiation in README and `docs/index.md` — official Google MCP servers are now in developer preview, which undercuts the current "no official alternative exists" framing; lead with concrete differentiators (tool breadth, stability/QA gate, design philosophy) instead, checked against what the official servers actually cover (PR #306) ([#263](https://github.com/khuisman/mcp-gee-sweet/issues/263))
- [x] Markdown-support documentation gaps — README/`docs/tools.md`/`docs/known-limitations.md`/`docs/design/markdown-support.md` never caught up to the Docs markdown-input pipeline shipped via #102/#103/#104/#248; consolidates #297/#298/#299/#302 (PR #482) ([#303](https://github.com/khuisman/mcp-gee-sweet/issues/303))
- [x] `CLAUDE.md`'s `convert_markdown` note overstates its download-branch guard as reachable — round-2 review moved that case earlier in the plan-building loop, where it's now classified `conflict`, not `failed`; the guard described is dead defensive code, not live behavior. Found during PR #414's round-3 review, routed to Amy ([#423](https://github.com/khuisman/mcp-gee-sweet/issues/423)) (PR #492)

**v0.9.0 Full Regression QA pass (2026-09-04)** — 623 PASS / 12 FAIL / 38 SKIP / 1 N/A across 674 TCs (effective 630 PASS / 5 FAIL after the two fixes below); see `docs/qa/runs/v0.9.0.md` for the full sign-off. Unconditional sign-off finalized in PR #703 — cleared to tag. Two real bugs found, both routed to lane B and now shipped:
- [x] `share_spreadsheet` fails with "File not found" on any Shared Drive file — missing `supportsAllDrives=True` on its `permissions().create()` call, the only one in `sharing.py` without it (`ready-for-development`, `lane-b`) ([#687](https://github.com/khuisman/mcp-gee-sweet/issues/687)) (PR #695)
- [x] Folder-listing cache key omits `max_results` — silent truncation on a cache hit, and a small-limit fetch poisons the cache for later larger-limit calls (`ready-for-development`, `lane-b`) ([#688](https://github.com/khuisman/mcp-gee-sweet/issues/688)) (PR #697)

### v0.9.2 — Post-release defect fixes & infrastructure addons _(target: [v0.9.2](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.2), before Tier 3 begins)_

_Renumbered from v0.9.1 on 2026-10-04: v0.9.1 shipped as a security hotfix cut from v0.9.0, so this release (and the old v0.9.2, now v0.9.3) moved up one. The GitHub labels were renamed to match._

Same shape as v0.8.1 — stabilize on defects that surfaced since v0.9.0 shipped, plus a handful of infrastructure/tooling additions that don't belong to any specific tool tier. Started because v0.9.0's own scope kept growing past its original Tier 2 definition; splitting this out keeps that pattern from repeating indefinitely. The one exception to its original "no new tools" scope is the Gmail domain, pulled forward from v1.1+ on 2026-09-23 because a community contributor had already implemented it (see **Gmail domain** below).

**Defects**
- [x] Isolated depth>0 bullet run renders the wrong glyph (disc instead of circle) despite correct indentation (PR #711) ([#439](https://github.com/khuisman/mcp-gee-sweet/issues/439))
- [x] `create_paragraph_bullets` (`style.py`) has the same isolated-run collapse-to-`nestingLevel 0` bug #439 fixed in `emitter.py` only — port PR #711's anchor-paragraph approach to the sibling path (PR #723) ([#713](https://github.com/khuisman/mcp-gee-sweet/issues/713))
- [x] Lock in the isolated-run rendering rule — an isolated bullet run renders at its true depth (`depth N` → `nestingLevel N`) at *every* depth, never clamped (decided 2026-09-09: consistency over avoiding orphaned indent; the markup generator owns the depth it emits). Extend TC-DOC190 with a `min_depth >= 2` case; state the rule in `emitter.py`'s bullet-pass comment and the `docs/emitter.py` paragraph of `CLAUDE.md` (PR #731) ([#714](https://github.com/khuisman/mcp-gee-sweet/issues/714))
- [x] `create_doc` markdown: a fenced code block whose body is raw HTML tags renders as loose plain paragraphs (fence ignored, indentation flattened) instead of a monospaced code block — python-markdown's raw-HTML-block handling appears to pre-empt `fenced_code`. Surfaced during #714 triage (PR #730) ([#719](https://github.com/khuisman/mcp-gee-sweet/issues/719))
- [x] **Bundle:** Docs write side (emitter, html_parser, images, content), one PR closing [#509](https://github.com/khuisman/mcp-gee-sweet/issues/509), [#567](https://github.com/khuisman/mcp-gee-sweet/issues/567), [#581](https://github.com/khuisman/mcp-gee-sweet/issues/581), [#638](https://github.com/khuisman/mcp-gee-sweet/issues/638), [#715](https://github.com/khuisman/mcp-gee-sweet/issues/715) — lane A (PR #961) ([#894](https://github.com/khuisman/mcp-gee-sweet/issues/894))
- [x] **Bundle:** Calendar hardening, one PR closing [#459](https://github.com/khuisman/mcp-gee-sweet/issues/459), [#615](https://github.com/khuisman/mcp-gee-sweet/issues/615), [#626](https://github.com/khuisman/mcp-gee-sweet/issues/626), [#627](https://github.com/khuisman/mcp-gee-sweet/issues/627), [#726](https://github.com/khuisman/mcp-gee-sweet/issues/726) — lane B (PR #912) ([#890](https://github.com/khuisman/mcp-gee-sweet/issues/890))
- [x] `delete_file(permanent=True)` surfaces a misleading 404 when the caller can trash but not permanently delete (Shared Drive Content manager) — an agent can read it as "already gone" and skip cleanup; check `capabilities.canDelete` first — lane B ([#876](https://github.com/khuisman/mcp-gee-sweet/issues/876)) (PR #888)
- [x] SSE: SIGTERM with an SSE stream open logs an "Exception in ASGI application" traceback; the server still exits cleanly, pre-existing before #833 — lane A (PR #911) ([#868](https://github.com/khuisman/mcp-gee-sweet/issues/868))
- [x] `sync_folder`'s `convert_markdown` restamp-failure handling: quota-message gap, duplicated create()+update() try/except, test fixture isolation — companion to #420 (PR #669) ([#650](https://github.com/khuisman/mcp-gee-sweet/issues/650))
- [x] `sync_folder convert_markdown`'s `modifiedTime` restamp fires for all convert types (over-broad), and its create()+update() pattern is duplicated across two call sites ([#435](https://github.com/khuisman/mcp-gee-sweet/issues/435)) (PR #817)
- [x] `_sync_level._run_one`'s outer catch-all leaks a raw `storageQuotaExceeded` message instead of the friendly `_SA_QUOTA_ERROR` used everywhere else — #669 follow-up, same friendly-error-consistency shape as #614/#459 (PR #710) ([#670](https://github.com/khuisman/mcp-gee-sweet/issues/670))
- [x] `sync_folder` reports "in sync" when mtimes match but content differs (an in-place rename that preserves mtime) — `use_checksum` doesn't catch it either; equal-mtime + size-divergence now reports `conflict` for every direction (PR #712) ([#659](https://github.com/khuisman/mcp-gee-sweet/issues/659))
- [x] `sync_folder`: an explicit `use_checksum=True` should verify a same-size within-tolerance pair too, overriding the `abs(diff) > _SYNC_MTIME_TOLERANCE` gate that #659 left in place — #712 follow-up ([#716](https://github.com/khuisman/mcp-gee-sweet/issues/716)) (PR #841)
- [x] `list_folders` with no parent hardcodes `'root' in parents`, ignoring `DRIVE_FOLDER_ID` — wrong scope on any Shared-Drive deployment / no results for a pure service account. Found in the v0.9.0 QA pass (TC-D27), has an explicit-parent workaround (PR #717) ([#689](https://github.com/khuisman/mcp-gee-sweet/issues/689))
- [x] `download_file` with a non-existent trailing-slash directory creates a clobbering file instead of the directory. Found in the v0.9.0 QA pass (PR #722) ([#690](https://github.com/khuisman/mcp-gee-sweet/issues/690))
- [x] `find_free_slots`'s per-calendar error shape is less detailed than `list_all_events`'s for the same failure mode. Found in the v0.9.0 QA pass (PR #725) ([#691](https://github.com/khuisman/mcp-gee-sweet/issues/691))
- [x] A bare `-` marker alone on its line isn't recognized as a list item by python-markdown regardless of indentation — distinct from the tracked `sane_lists` threshold bug. Found in the v0.9.0 QA pass; documented as a known limitation rather than fixed (PR #733) ([#692](https://github.com/khuisman/mcp-gee-sweet/issues/692))
- [x] PyPI project page drops the logo — README `<img src>` is a relative path, which PyPI's `readme_renderer` strips. Found on the published v0.9.0 page (PR #707) ([#706](https://github.com/khuisman/mcp-gee-sweet/issues/706))
- [x] PyPI project page 404s four README links (`CONTRIBUTING.md`, `docs/qa/runs`, `docs/qa/README.md`, `LICENSE`): repo-relative, same class as #706, which `/release` step 4 checks for images only. `loud/narrow`, in-flight by user decision since a published README can't be changed (PR #1063) ([#1062](https://github.com/khuisman/mcp-gee-sweet/issues/1062))
- [x] `sync_folder`/`upload_local_file` convert: Drive's `modifiedTime` for a Google Doc lags real edits by minutes, and the async import can overwrite the post-create restamp. Change detection for `convert_markdown` Docs needs a new signal. Joy scopes; decision doc in PR #819 ([#814](https://github.com/khuisman/mcp-gee-sweet/issues/814)) (PR #854)
- [x] `sync_folder` convert_markdown: a Drive-edited converted Doc stays a `conflict` on every run, and the only way out today is replacing the Doc (new file ID, loses sharing/comments/links). Decide: accept the Drive version as the baseline, force-upload, or both. #814 follow-up; Joy scopes ([#860](https://github.com/khuisman/mcp-gee-sweet/issues/860)) (PR #1016)
- [x] auth: with no `token.json`, a stdio server blocks on OAuth consent with no timeout, and the consent prompt goes to the protocol channel ([#811](https://github.com/khuisman/mcp-gee-sweet/issues/811)) (PR #828)
- [x] auth: under `--transport sse`, the OAuth consent wait runs synchronously on the event loop, stalling every other session and ignoring SIGTERM until consent or timeout. #811 follow-up, found in PR #828 ([#833](https://github.com/khuisman/mcp-gee-sweet/issues/833)) (PR #867)
- [x] Tool errors are opaque on PyPI installs: `mcp` 2.3 (what `uvx` resolves; the lock pins 2.0.0) hides any non-`ToolError` exception text, so #811's "run `mcp-gee-sweet auth`" message and uncaught Google API errors reach the client as a bare `Error executing tool <name>`. Observed live. Urgent: lane-a, next after #844 ([#872](https://github.com/khuisman/mcp-gee-sweet/issues/872)) (PR #905)
- [x] auth: offer OAuth re-authorization from the failing tool call, via URL-mode elicitation with the consent URL in a `ToolError` as fallback, then rebuild services in place. Covers a refresh token revoked mid-session too. No unprompted browser. Lane-a, after #872 ([#873](https://github.com/khuisman/mcp-gee-sweet/issues/873)) (PR #925)
- [x] sheets: an A1 range with a dangling colon (`A1:`, `A:`, `5:`, `:5`, `:B`, `:B5`) passes `_parse_a1_notation` and widens through `_grid_range` to the whole sheet or a bigger rectangle. Hits every `_grid_range_or_error` tool; for `sort_range`/`merge_cells` it changes data. Found reviewing community PR #922, which rejects only a bare `":"` (merged). Also covers `1:B` and non-ASCII `.upper()` cases (see issue comment). Community PR #931 claims it (pulled from lane B 2026-10-08; back to lane B if #931 stalls) ([#926](https://github.com/khuisman/mcp-gee-sweet/issues/926)) (PR 931)
- [x] `get_doc_as_markdown` mangles inline code containing backticks. Community PR #923 (community-PR track, closes it on merge) ([#936](https://github.com/khuisman/mcp-gee-sweet/issues/936)) (PR #923)
- [x] `get_doc_as_markdown`: remaining code-span/code-block delimiter gaps (fixed ``` fence, lost edge spaces, merged adjacent code runs, newlines and `|` inside inline code, strict-CommonMark test coverage). Same before and after #923, not a regression; found reviewing it. Same files as the #893 read-side bundle. Item 1 shipped in community PR #940; items 2–6 lane B; defect, so ahead of #893 (PR #968) ([#938](https://github.com/khuisman/mcp-gee-sweet/issues/938))
- [x] SIGTERM with an open streamable-http `GET /mcp` stream truncates it ("ASGI callable returned without completing response"); sibling of #868 — lane A, after #894 (PR #975) ([#917](https://github.com/khuisman/mcp-gee-sweet/issues/917))
- [x] `get_doc_as_markdown`: a paragraph exported as a fenced code block drops links on its code runs and images (`_render_code_block` keeps only run text). Found reviewing #940 — lane B, after #938 (same file), ahead of #958 (PR #976) ([#951](https://github.com/khuisman/mcp-gee-sweet/issues/951))
- [x] `get_doc_as_markdown`: plain text ending in `!` right before a linked run exports as `![…](…)`, which renders as an image. Affects every link, not just code; fix belongs in `_escape`'s cross-run handling. Found in PR #968 — lane B, after #951 (same file), ahead of #958 (PR #981) ([#969](https://github.com/khuisman/mcp-gee-sweet/issues/969))
- [x] `get_doc_as_markdown(local_path=…)` writes the JSON result envelope, not the markdown: `markdown_export.py` routes through the generic JSON-to-disk helper — lane B, after #938 (same read-side area) (PR #982) ([#958](https://github.com/khuisman/mcp-gee-sweet/issues/958))
- [x] `add_chart`: a cell-to-row (`B2:5`) or row-only (`1:5`) range silently charts one column — `_per_column_ranges` defaults `endColumnIndex` to start+1. Found reviewing #931 — lane A, after #917 (PR #983) ([#954](https://github.com/khuisman/mcp-gee-sweet/issues/954))
- [x] `_parse_a1_notation` hardening: one compiled grammar, index bounds, validate before the sheet-ID fetch. #931 review follow-ups, no behavior change for valid input — lane A, after #954 (same A1 area); its QA also runs #953's live checks for #931 (folded in) (PR #986) ([#955](https://github.com/khuisman/mcp-gee-sweet/issues/955))
- [x] Write side drops image links: `[![alt](src)](url)` (or `<a href><img></a>`) imports through `create_doc`/`create_doc_from_file`/`write_doc_content` without its URL, so it doesn't round-trip with #951's export. Found in PR #976 — lane A, after #955 (PR #992) ([#977](https://github.com/khuisman/mcp-gee-sweet/issues/977))
- [x] Comment quoted text comes back HTML-escaped (`Caf&#233;`) from `add_doc_comment`, `list_doc_comments`, and `get_doc_as_markdown(include_comments=True)`: `comments.py` passes Drive's escaped `quotedFileContent.value` through unchanged. Found reviewing #958 — lane B, after #959 (defect, next pick) (PR #991) ([#984](https://github.com/khuisman/mcp-gee-sweet/issues/984))
- [x] `write_capped_result_to_disk` writes `dir/` as a file when the directory doesn't exist: a trailing separator should mean "directory" (create it, append `default_filename`). Shared by every `local_path` writer. Found in PR #988 — lane B, after #984 (defect) (PR #1000) ([#990](https://github.com/khuisman/mcp-gee-sweet/issues/990))

**Sheets hardening** _(triaged out of `backlog` 2026-09-11 — see the "Backlog triage" note below)_
- [x] `update_sheet_properties`/dimension-tool hardening + dedup follow-ups from PR #321's review ([#323](https://github.com/khuisman/mcp-gee-sweet/issues/323)) (PR #734)
- [x] `update_borders` hardening + dedup follow-ups from PR #325's review ([#330](https://github.com/khuisman/mcp-gee-sweet/issues/330)) (PR #738)
- [x] No tool clears a data validation rule, and no tool exposes a range's numeric `sheetId` ([#365](https://github.com/khuisman/mcp-gee-sweet/issues/365)) (PR #745)
- [x] `add_data_validation`: validate the `values` count/shape against `condition_type` before the API call ([#366](https://github.com/khuisman/mcp-gee-sweet/issues/366)) (PR #750)
- [x] Dedupe `_get_sheet_id`/`_get_sheet_index` lookup logic; add happy-path test coverage ([#442](https://github.com/khuisman/mcp-gee-sweet/issues/442)) (PR #754)
- [x] `_parse_a1_notation`/`_grid_range` raise an uncaught `ValueError` on invalid A1 notation instead of returning `{"error": ...}`, across ~10 call sites in `data.py`/`structure.py` (PR #745 follow-up) ([#747](https://github.com/khuisman/mcp-gee-sweet/issues/747)) (PR #756)
- [x] `add_data_validation`'s docstring and `_CONDITION_VALUE_COUNTS` are two independently-maintained sources of the same per-`condition_type` fact, no derivation link — needs a design pass (PR #750 follow-up) ([#751](https://github.com/khuisman/mcp-gee-sweet/issues/751)) (PR #759)
- [x] `update_cells`'s plain-cells branch (+ `get_sheet_data`/`get_sheet_formulas`/`get_multiple_sheet_data`/`clear_values`) hand a raw range string to the Sheets values API with no local validation, leaking a raw `HttpError` on malformed input (PR #756 follow-up) ([#757](https://github.com/khuisman/mcp-gee-sweet/issues/757)) (PR #764)

**Docs hardening & dedup** _(triaged out of `backlog` 2026-09-11)_
- [x] `html_parser.py`: readability + reset-consistency nits in `_emit_block_node`/`_block_had_unsupported_content` ([#417](https://github.com/khuisman/mcp-gee-sweet/issues/417)) (PR #766)
- [x] `emitter.py`: non-blocking cleanup findings from PR #432's nested-bullet review ([#434](https://github.com/khuisman/mcp-gee-sweet/issues/434)) (PR #768)
- [x] `html_parser`: a resumed block's genuine trailing `&nbsp;` is still silently dropped after #402's fix ([#444](https://github.com/khuisman/mcp-gee-sweet/issues/444)) (PR #772)
- [x] `docs/style.py`/`docs/content.py`: no shared helper for the "omit key but keep field mask" link-clear pattern ([#448](https://github.com/khuisman/mcp-gee-sweet/issues/448)) (PR #778)
- [x] `html_parser`: merge identical `ol`/`ul` close-tag branches in `handle_endtag` ([#451](https://github.com/khuisman/mcp-gee-sweet/issues/451)) (PR #779)
- [x] Heading-anchor resolution (#409): minor duplication/efficiency cleanups in `anchors.py`/`content.py` ([#454](https://github.com/khuisman/mcp-gee-sweet/issues/454)) (PR #783)
- [x] `insert_local_images`/`create_doc`: image alt text is parsed but never used. Closed as infeasible — no Docs API request can write `EmbeddedObject.title`/`description`, confirmed via live discovery-schema check ([#508](https://github.com/khuisman/mcp-gee-sweet/issues/508))
- [x] `content.py`: image-fetch-failure retry mechanism is fragile, resends the whole document per bad image ([#510](https://github.com/khuisman/mcp-gee-sweet/issues/510)) (PR #787)
- [x] `content.py`: duplicated image upload/share/revoke logic across `create_doc` and `insert_local_images`, plus an avoidable extra Drive round trip ([#511](https://github.com/khuisman/mcp-gee-sweet/issues/511)) (PR #842)
- [x] `docs/images.py` oversized-image handling: duplicated logic + unneeded full pixel decode (#400 follow-up) ([#560](https://github.com/khuisman/mcp-gee-sweet/issues/560)) (PR #801)
- [x] `write_doc_content`/`update_doc_from_file` leave the doc empty when the replacement fails after the clear — fixed by a pre-clear backup copy that is named in the error (`backupId`) and deleted on success; this replaced the 2026-10-04 revision-ID plan (`docs/design/doc-replace-backup.md`) — lane A, ahead of #957 (defect; same write path) ([#878](https://github.com/khuisman/mcp-gee-sweet/issues/878)) (PR #1017)
- [x] `download_file` (missing `export_format`) and `sync_folder(dry_run=True)` create local directories on calls that write nothing. Observed in Aziz's v0.9.1 hotfix regression pass; predates v0.9.1 — lane A, after #878 (defect, ahead of #957) ([#1012](https://github.com/khuisman/mcp-gee-sweet/issues/1012)) (PR #1023)
- [x] `write_doc_content`/`update_doc_from_file` refuse the write when the pre-clear backup copy can't be created in the doc's folder (no permission to add files there, or the Shared Drive is at its item limit). Decision 2026-10-13: fall back to replacing without a backup, chosen by Drive's error reason and not the HTTP status, with a `warning` on success. New in v0.9.2 via #878 (from-review condition (a)) — lane A, after #1012, ahead of #957 (same write path) ([#1018](https://github.com/khuisman/mcp-gee-sweet/issues/1018)) (PR #1034)
- [x] `write_doc_content`/`update_doc_from_file`: decide whether the `cannotCopyFile` (owner restricted copying for writers) and `activeItemCreationLimitExceeded` backup-copy refusals also replace without a backup, as #1018 does for the folder case. `loud/narrow`, regression since v0.9.1 (#878 introduced the copy); 2nd follow-up in #878's chain. Found in PR #1034's review — lane A, after #796. Decision 2026-10-15: keep refusing by default, with an opt-in `allow_no_backup` override; #1018's three reasons unchanged ([#1035](https://github.com/khuisman/mcp-gee-sweet/issues/1035)) (PR #1042)
- [x] CLAUDE.md: fix the stale `_SA_QUOTA_ERROR` invariant (PR #1006 made it false) and add the GHSA-hx2f `_safe_local_dest` rule for Drive-name joins. CLAUDE.md-only, via Bob's gate. Kept by maintainer decision 2026-10-13 (not a review-bar ticket) — Bob, v0.9.2 ([#1014](https://github.com/khuisman/mcp-gee-sweet/issues/1014)) (PR #1043)
- [x] `export_revision`: support Google Docs revisions (returned as markdown), and fix `list_revisions`' docstring claim that native-file revisions are pruned after 30 days. Also what #878's recovery path points callers at — lane B, after #958 (PR #988) ([#959](https://github.com/khuisman/mcp-gee-sweet/issues/959))
- [x] `export_revision`'s temporary Doc exposes an old revision's content to the default folder's audience (a whole Shared Drive) — decided 2026-10-11: under OAuth create it in My Drive root; a service account keeps the default folder, and that remaining exposure goes in `docs/known-limitations.md`. Found in PR #988 — lane B, after #990 (PR #1006) ([#989](https://github.com/khuisman/mcp-gee-sweet/issues/989))
- [x] Quota-exceeded error tells a user identity to switch to OAuth: `_quota_error_detail` renders `_SA_QUOTA_ERROR` for every identity. Found in PR #1006's QA — v0.9.2 under condition (a): #1006 (this release) makes it reachable for an OAuth user with a full My Drive (PR #1006) ([#1009](https://github.com/khuisman/mcp-gee-sweet/issues/1009))
- [x] `insert_local_images`: temporary `anyone:reader` image shares aren't revoked when the call is cancelled — apply PR #877's shielded-cleanup pattern — lane B ([#883](https://github.com/khuisman/mcp-gee-sweet/issues/883)) (PR #903)
- [x] **Bundle:** Docs image-share cancellation follow-ups (from PR #903), one PR closing [#904](https://github.com/khuisman/mcp-gee-sweet/issues/904), [#907](https://github.com/khuisman/mcp-gee-sweet/issues/907), [#908](https://github.com/khuisman/mcp-gee-sweet/issues/908), [#666](https://github.com/khuisman/mcp-gee-sweet/issues/666) — lane B, moved from lane A 2026-10-13 so it runs alongside lane A's #1012 and #1018 (shares `content.py` with #1018, different functions) ([#909](https://github.com/khuisman/mcp-gee-sweet/issues/909)) (PR #1029)
- [x] `_apply_doc_content`: temporary `anyone:reader` image shares aren't revoked when the doc edit raises — revoke pass should run in a `finally`. Same share/revoke surface as #666 and #511 ([#789](https://github.com/khuisman/mcp-gee-sweet/issues/789)) (PR #877)
- [x] Extract a shared helper for the isolated-bullet-run zero-tab anchor mechanic (`emitter.py` ↔ `style.py`); harden its regression test (`lane-a`) ([#727](https://github.com/khuisman/mcp-gee-sweet/issues/727)) (PR #735)

**Drive hardening & dedup** _(triaged out of `backlog` 2026-09-11)_
- [x] `download_folder`/`sync_folder` progress notifications: report bytes transferred, not just file count ([#352](https://github.com/khuisman/mcp-gee-sweet/issues/352)) (PR #739)
- [x] `download_folder`'s `candidates` tuple: fragile positional access across consumer sites, could be a dataclass (PR #739 follow-up) ([#740](https://github.com/khuisman/mcp-gee-sweet/issues/740)) (PR #748)
- [x] `download_folder`: opt-in flag to report byte-based `progress`/`total` in `report_progress`'s structured fields (default stays file-count for consistency) (PR #739 follow-up, decision resolved) ([#741](https://github.com/khuisman/mcp-gee-sweet/issues/741)) (PR #753)
- [x] Unify the two progress-counter idioms in `transfer.py` (nonlocal vs. list-box) ([#354](https://github.com/khuisman/mcp-gee-sweet/issues/354)) (PR #746)
- [x] Extend notifications/progress to the remaining `asyncio.gather`-based multi-call tools ([#355](https://github.com/khuisman/mcp-gee-sweet/issues/355)) (PR #758)
- [x] `sync_folder`'s `plan`/`step` dicts have the same untyped-access fragility #740's dataclass fix addressed for `download_folder` (PR #748 follow-up) ([#749](https://github.com/khuisman/mcp-gee-sweet/issues/749)) (PR #755)
- [x] Expose starred state via `get_file_metadata`/`list_files` — `star_file`/`unstar_file` (#139) set it but nothing reads it back ([#388](https://github.com/khuisman/mcp-gee-sweet/issues/388)) (PR #760)
- [x] `drive`: consolidate `convert_markdown`'s duplicated matching/messaging logic in `transfer.py` (PR #414 follow-up) ([#424](https://github.com/khuisman/mcp-gee-sweet/issues/424)) (PR #763)
- [x] `sync_folder`: `is_workspace` recomputed inline in the `use_checksum` block instead of reusing `drive_map`'s stashed value ([#474](https://github.com/khuisman/mcp-gee-sweet/issues/474)) (PR #765)
- [x] `upload_local_folder`: `convert` skip logic has a duplicate-name edge case + logic duplication vs. `_upload_local_file` ([#514](https://github.com/khuisman/mcp-gee-sweet/issues/514)) (PR #767)
- [x] `sync_folder`: `actions` list built unconditionally even when `dry_run=False` ([#521](https://github.com/khuisman/mcp-gee-sweet/issues/521)) (PR #770)
- [x] Extend the `_GOOGLE_DOC_MIME` sweep to remaining hardcoded-literal and comparison sites (#412 follow-up) ([#544](https://github.com/khuisman/mcp-gee-sweet/issues/544)) (PR #777)
- [x] `refactor(drive)`: dedupe `mime_type` quote-escaping and list-files response mapping in `files.py` ([#578](https://github.com/khuisman/mcp-gee-sweet/issues/578)) (PR #780)
- [x] `list_folders`/`list_spreadsheets` no-parent + no-`DRIVE_FOLDER_ID` path is unbounded across all drives, no `max_results` (`lane-a`) ([#718](https://github.com/khuisman/mcp-gee-sweet/issues/718)) (PR #736)
- [x] `download_file` trailing-slash guard: fail-fast ordering, dead `os.altsep` clause, raw `NotADirectoryError` surface (PR #722 follow-up) ([#724](https://github.com/khuisman/mcp-gee-sweet/issues/724)) (PR #827)
- [x] `upload_local_folder(convert=True)`: an unrelated Drive file sharing a candidate's extension-stripped name can cause a false-positive skip — decided 2026-09-23: Drive `properties` marker on converted uploads, legacy name-only matches still skip but are flagged as unverified ([#769](https://github.com/khuisman/mcp-gee-sweet/issues/769)) (PR #800)
- [x] `sync_folder(convert_markdown=True)`: a `.md` name over ~95 bytes overflows Drive's 124-byte property cap — upload fails with `propertyLengthLimitExceeded` but Drive still creates an unmarked orphan Doc, repeated on every sync. Needs a design call on converted-Doc recognition (PR #800 follow-up) ([#805](https://github.com/khuisman/mcp-gee-sweet/issues/805)) (PR #812)
- [x] Deduplicate the `max_results` clamp expression, hand-copied 8x across `drive/files.py` with inconsistent caps (PR #736 follow-up) ([#737](https://github.com/khuisman/mcp-gee-sweet/issues/737)) (PR #781)
- [x] `download_file`: one pre-flight `local_path` check before any Drive call, for both trailing-slash and plain branches, naming the blocking path (#724/#827 follow-up; on-deck, `good first issue`) (PR #855) ([#836](https://github.com/khuisman/mcp-gee-sweet/issues/836))
- [x] `sync_folder`: a failed mid-stream download leaves a truncated local file with a fresh mtime, which the next sync uploads over the intact Drive copy — download to a temp file and `os.replace` on success; check `download_file`/`download_folder` too. Found by code review, not yet observed live (lane-a, after #814 since both touch `_run_one`) ([#844](https://github.com/khuisman/mcp-gee-sweet/issues/844)) (PR #884)
- [x] **Bundle:** Drive transfer follow-ups (`download_file` preflight + `_write_atomically`), one PR closing [#874](https://github.com/khuisman/mcp-gee-sweet/issues/874), [#887](https://github.com/khuisman/mcp-gee-sweet/issues/887) — lane A (PR #1001) ([#895](https://github.com/khuisman/mcp-gee-sweet/issues/895))
- [x] `upload_local_file`/`sync_folder`: compressed files upload with the inner MIME type (`x.csv.gz` → `text/csv`). Lane A, after #895 (both touch `transfer.py` uploads); community PR #934 closed unmerged 2026-10-10 (PR #1002) ([#930](https://github.com/khuisman/mcp-gee-sweet/issues/930))
- [x] `sync_folder`: `size_bytes` never counts uploaded bytes, so an upload-only sync reports 0 (found in PR #1002's QA, observed live). Lane A, after #930 (PR #1007) ([#1003](https://github.com/khuisman/mcp-gee-sweet/issues/1003))
- [x] Share one HttpError reason-check helper across the `storageQuotaExceeded` sites. Lane A, after #1003; community PR #921 closed unmerged 2026-10-10 (PR #1011) ([#916](https://github.com/khuisman/mcp-gee-sweet/issues/916))

**Testing** _(triaged out of `backlog` 2026-09-11)_
- [x] **Bundle:** test-suite tightening, one PR closing [#392](https://github.com/khuisman/mcp-gee-sweet/issues/392), [#526](https://github.com/khuisman/mcp-gee-sweet/issues/526), [#551](https://github.com/khuisman/mcp-gee-sweet/issues/551), [#561](https://github.com/khuisman/mcp-gee-sweet/issues/561), [#574](https://github.com/khuisman/mcp-gee-sweet/issues/574) — lane B (PR #924) ([#891](https://github.com/khuisman/mcp-gee-sweet/issues/891))
- [x] Live verification for PR #922 (reject unbounded A1 ranges); coverage in PR #929 (PR #929) ([#927](https://github.com/khuisman/mcp-gee-sweet/issues/927))
- [x] Live verification for community PR #940 (literal fences in code-block exports) ([#952](https://github.com/khuisman/mcp-gee-sweet/issues/952)) (PR #1027)

**Infrastructure**
- [x] pre-commit's `ruff` hook pins v0.11.9 while CI runs the project's locked 0.16.x, so a commit can pass a lint CI rejects. Seen live on PR #1000 (RUF043, three red CI runs). Moved out of the #897 bundle 2026-10-12 — lane B, after #989 ([#974](https://github.com/khuisman/mcp-gee-sweet/issues/974)) (PR #1022)
- [x] `/release` + `prep-for-pr` backstop checks for README render breakage on PyPI — the human-facing companion to #708's CI guard, routed to Bob ([#709](https://github.com/khuisman/mcp-gee-sweet/issues/709)) (PR #967)
- [x] `supportsAllDrives=True` is hand-inlined at ~58 Drive call sites — retrofitted twice now (#687 plus its own original miss); wants a shared wrapper or lint guard so a new call site can't omit it ([#696](https://github.com/khuisman/mcp-gee-sweet/issues/696)) (PR #784)
- [x] Extract a shared `_BaseCache` helper for the `rows_fetched` sufficiency check + epoch-guarded store — #688's fix copy-pasted the pattern into `DriveFolderCache` instead, and the epoch guard is still missing there ([#698](https://github.com/khuisman/mcp-gee-sweet/issues/698)) (PR #788)
- [x] Team setup: give each worktree only its own MCP server — other roles' tool names are an estimated ~15–20k of the ~80k lane bootstrap; measure first. Prioritized 2026-09-29, lane-b ahead of #789 ([#850](https://github.com/khuisman/mcp-gee-sweet/issues/850)) (PR #856)
- [x] Context-size backstop hook for lane sessions, plus a warning before a cold `--resume` — code half of #843; lane-b after #850 ([#847](https://github.com/khuisman/mcp-gee-sweet/issues/847)) (PR #866)
- [x] Cut `CLAUDE.md` and the role files down to lasting rules + pointers, moving per-PR history to `docs/design/`/`docs/decisions/` — Amy writes it (user-assigned), Bob reviews each PR under the prompt-QA gate; can land as one PR per file (PR #852, #948, #950) ([#849](https://github.com/khuisman/mcp-gee-sweet/issues/849))
- [x] `merge-pr.md` step 6: guard the team-slot reset against in-flight work on another ticket, mirroring #837's receiving-side guard in `dev.md` — Bob's track ([#838](https://github.com/khuisman/mcp-gee-sweet/issues/838)) (PR #853)
- [x] Kai applies `community` at intake to outside-contributor PRs/issues, plus `needs-ticket` (PR with no linked issue) and `verify-content` (unreproduced contributor issue), and its prompt says how to resolve a community PR colliding with a lane ticket — Bob's track (PR #943) ([#942](https://github.com/khuisman/mcp-gee-sweet/issues/942))
- [x] Kai intake follow-up: find a PR's issue references in comments and commit messages too, and report (don't act on) an unreferenced PR that likely duplicates a lane issue — Bob's track (PR #946) ([#945](https://github.com/khuisman/mcp-gee-sweet/issues/945))
- [x] Team launch: pin each role's model and effort explicitly in the Makefile instead of inheriting the client default — Bob's track (PR #949) ([#947](https://github.com/khuisman/mcp-gee-sweet/issues/947))
- [x] `qa.md` steps 7–8: every QA round comment starts with the fixed line `## QA round <N> (<Name>) @ <short-sha>: <sent back|approved>`, so round counts and verdicts are machine-readable — Bob's track ([#960](https://github.com/khuisman/mcp-gee-sweet/issues/960)) (PR #962)

**Gmail domain** _(pulled forward from v1.1+ 2026-09-23; implementation is community PR #786, merged 2026-09-25)_
- [x] Gmail domain primitives ([#785](https://github.com/khuisman/mcp-gee-sweet/issues/785)), via community PR #786
- [x] Gmail scopes opt-in + verify granted scopes at startup. Existing OAuth tokens weren't granted the new scopes, so refresh likely fails into a surprise browser consent or a headless hang. **Must ship in the same release as #786** ([#790](https://github.com/khuisman/mcp-gee-sweet/issues/790)) (PR #807)
- [x] `reply_to_message` should honor Reply-To and handle replies to your own sent mail ([#791](https://github.com/khuisman/mcp-gee-sweet/issues/791)) (PR #815)
- [x] Decode message bodies using the part's charset; tolerate missing base64 padding ([#792](https://github.com/khuisman/mcp-gee-sweet/issues/792)) (PR #816)
- [x] `get_message`/`get_thread` return no body when Gmail delivers a large (~MB) `text/plain`/`text/html` part by `attachmentId`. Found in #803's live QA ([#825](https://github.com/khuisman/mcp-gee-sweet/issues/825)) (PR #829)
- [x] `get_thread`/`get_message`: add a body-less option — a long thread trips the response-size cap and there's no other way to get its message IDs, so it can't be read at all ([#793](https://github.com/khuisman/mcp-gee-sweet/issues/793)) (PR #885)
- [x] **Bundle:** Gmail cleanup, one PR closing [#795](https://github.com/khuisman/mcp-gee-sweet/issues/795), [#802](https://github.com/khuisman/mcp-gee-sweet/issues/802), [#823](https://github.com/khuisman/mcp-gee-sweet/issues/823) — lane B ([#896](https://github.com/khuisman/mcp-gee-sweet/issues/896)) (PR #928)
- [x] Local-file read policy across local-path tools — in a remote/SSE deployment these read the server's own filesystem (token, SA key), and Gmail attachments can now mail them out. Decided 2026-10-04: `LOCAL_FILE_ACCESS=full|roots|off` (default `off` under SSE/HTTP), one shared check for every local read and write; also covers `_read_doc_source_file`'s synchronous read. Lane A after #1018, `solo-only`: lane B holds after #909 until it ships ([#796](https://github.com/khuisman/mcp-gee-sweet/issues/796)) (PR #1039)
- [x] Release-pass Gmail QA (`docs/qa/tests/gmail.md`, added by #786). Many cases are destructive (send/draft/trash), so they need a dedicated mailbox fixture plan — Aziz ([#803](https://github.com/khuisman/mcp-gee-sweet/issues/803))
- [x] Rewrite TC-GM01–22 prescriptively, add TC-GM26–44 and the Smoke rows, per `docs/qa/gmail-test-plan.md` §4. Part of #803, Aziz ([#822](https://github.com/khuisman/mcp-gee-sweet/issues/822))
- [x] README and `docs/index.md`: add Gmail coverage (recounted per-domain tool counts) and remove the comparisons with other MCP servers. Docs-only, no file overlap with PR #1039, so it runs alongside #796 despite the `solo-only` hold (user decision 2026-10-16) — lane B ([#1033](https://github.com/khuisman/mcp-gee-sweet/issues/1033)) (PR #1041)

Tool surface (from the original v1.1+ plan):

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
- [ ] ~~`delete_message` — permanently delete a message~~ — dropped from #786 in review: needs the full `https://mail.google.com/` scope

**QA & docs** _(moved out of v0.9.0 2026-09-02 so they don't gate the release; see [#629](https://github.com/khuisman/mcp-gee-sweet/issues/629), closed)_
- [x] `CONTRIBUTING.md`: say how a ticketless PR is handled — a bug fix gets a maintainer-filed issue, a feature needs an issue explaining its reasoning first — Amy ([#941](https://github.com/khuisman/mcp-gee-sweet/issues/941)) (PR #944)
- [x] `list_files`/`get_file_metadata` docstrings cite a stale `upload_local_file` `modifiedTime` caveat (fixed at the root by PR #472) and carry a broken self-referential contrast — from Bob's `docs/tools.md` docstring sweep; Dev/QA track, batches with #682/#683 ([#681](https://github.com/khuisman/mcp-gee-sweet/issues/681)) (PR 898)
- [x] `create_doc` family docstrings name only the ~25MP inline-image limit; the ~50MB byte-size limit (#562) is equally enforced, and 3 deferring docstrings inherit the gap — from Bob's `docs/tools.md` docstring sweep. Routed to Amy (`documentation`); closed community PR #932 has a diff ([#682](https://github.com/khuisman/mcp-gee-sweet/issues/682)) (PR 970)
- [x] QA test-doc cross-reference cleanup after the `drive.md`/`docs.md` split (PR #582) — triaged out of `backlog` 2026-09-11 ([#590](https://github.com/khuisman/mcp-gee-sweet/issues/590)) (PR #851)
- [x] Stale "upload_local_file doesn't stamp modifiedTime" premise remains after #898; TC-D238 no longer reliably reproduces its drift. Routed to Amy (`documentation`); community PR #933 closed unmerged 2026-10-10, and its diff has a working TC-D238 setup. Touches `transfer.py` docstrings alongside lane A's #930/#916; the reworked TC-D238 needs a live run by QA (#956 closed as a duplicate) ([#913](https://github.com/khuisman/mcp-gee-sweet/issues/913)) (PR 973)

**Backlog triage, 2026-09-11 (Kai orchestrator session):** open issues were growing ~2:1 against closures (37 opened vs. 20 closed over the prior 14 days); the 60 issues sitting in unscheduled `backlog` with no version were the other half of that — filed as legitimate findings, never given a real release slot. Retriaged all 60 into actual tiers rather than pruning them: everything fixing/hardening/testing already-shipped functionality went into this v0.9.1 release (now v0.9.2) (the sections above marked "triaged out of `backlog`"), one comments-API cleanup went to v0.9.2 (now v0.9.3) (below, since it overlaps that release's own comments-generalization work), and net-new capabilities that were never started went to Tier 3 (v1.0) or a new lighter-weight tier below Tier 3 (v1.1+) based on scope — see those sections. `backlog` (no version) is now empty; going forward, an issue either has a version or gets triaged promptly, it doesn't accumulate unversioned.

### v0.9.3 _(target: [v0.9.3](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.3))_

Ships ahead of the Markdown-fidelity feature set (now _ornithomimus_, below): what merged since v0.9.2, plus #1052 and #1124. Maintainer decision 2026-10-19.

- [x] Blockquote indent invisible on single-line quotes (no `indentFirstLine`) — `wrong/narrow, observed`; #1044-relevant — lane B ([#1056](https://github.com/khuisman/mcp-gee-sweet/issues/1056)) (PR #1089)
- [x] Stale per-thread HTTP connection fails the first call after idle (`Errno 54`/`Errno 60`), with no retry. Placed in v0.9.3 by the user 2026-10-17; re-read 2026-10-18 as `severe` (a call can hang for minutes), observed: urgent in-flight, exempt from the fill lock; lane A after #1057 ([#1052](https://github.com/khuisman/mcp-gee-sweet/issues/1052)) (PR #1126)
- [x] `get_doc_as_markdown` emits a raw `\u000b` for a soft line break in non-code text — `wrong/narrow, observed`; #1044-relevant — lane A ([#1057](https://github.com/khuisman/mcp-gee-sweet/issues/1057)) (PR #1088)
- [x] Publish dev and stable releases from one workflow file, so PyPI stops flagging every stable release with a "Change of provenance" warning. Added to the locked fill by the maintainer 2026-10-19; lane A after #1052; maintainer adds the new trusted publisher on PyPI before merge ([#1124](https://github.com/khuisman/mcp-gee-sweet/issues/1124)) (PR #1131)
- [x] Release-scoping rules in `kai.md`: a version is a named feature set plus a locked 10–15-item fill, ships when the feature set is done; `planned: <name>` labels until in flight; feature-placement order; `needs-version-call` circuit breaker. Process ticket, v0.9.3 by the release-gate test: v0.9.3's fill is to be set under these rules. Kai writes it, Bob reviews (prompt-QA). The backlog re-triage is separate and maintainer-led ([#1085](https://github.com/khuisman/mcp-gee-sweet/issues/1085)) (PR #1106)
- [x] Fix the stale Tier 4 "zero comment tooling on Docs today" line; close or re-scope #142 (asks for what #151 already shipped under different naming). ([#662](https://github.com/khuisman/mcp-gee-sweet/issues/662)) (PR #978)
- [x] `html_parser`: the `</a>` of an href-less anchor nested in a linked one pops the outer link, so text or an image after it is written unlinked. Found in PR #992's QA, which sent back the same bug in its new `_bare_link_url` stack; may close with PR #992 — lane A; moved from v0.9.2 2026-10-11 (pre-existing, invalid nested HTML only) (PR #992) ([#994](https://github.com/khuisman/mcp-gee-sweet/issues/994))
- [x] `list_spreadsheets`, `search_files`, `search_spreadsheets` return trashed files — `wrong/common` — lane A ([#1054](https://github.com/khuisman/mcp-gee-sweet/issues/1054)) (PR #1083)
- [x] Table column widths fail on any table after the first in a written doc (stale `startIndex` in `fill_tables`) — `loud/narrow`, observed — lane B ([#1053](https://github.com/khuisman/mcp-gee-sweet/issues/1053)) (PR #1082)
- [x] `style_doc_range` has no `font_family` parameter — can't apply monospace to an existing range — community PR #1026 ([#720](https://github.com/khuisman/mcp-gee-sweet/issues/720)) (PR #1026)

### v0.9.4 — hotfix _(target: [v0.9.4](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.4))_

Security hotfix cut from the v0.9.3 tag, with nothing else from `develop` (maintainer decision 2026-10-22). Pillow 12.3.0 has open CVEs, and the only fixed release, 13.0.0, needs Python 3.11+, so this release drops Python 3.10. The release notes say so, and that 3.10 users stay on v0.9.3 until they move to 3.11+. The change reaches `develop` through community PR #1161; the hotfix is a lane-A backport of the same change onto v0.9.3, with `uv.lock` regenerated on the tag.

- [x] Pillow 12.3.0 has 9 open security alerts (1 critical); the fix (13.0.0) needs Python 3.11+ ([#1158](https://github.com/khuisman/mcp-gee-sweet/issues/1158)) (PR #1161; shipped in v0.9.4 via PR #1172)
- [x] Backport the Pillow 13 / drop-3.10 change onto v0.9.3 — lane A ([#1169](https://github.com/khuisman/mcp-gee-sweet/issues/1169)) (PR #1172)

### v0.9.5 — hotfix _(target: [v0.9.5](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av0.9.5))_

Security hotfix cut from the v0.9.4 tag, with nothing else from `develop` (maintainer decision 2026-10-24). The eMudhra/emSign CA incident makes any certifi older than `2026.10.19` trust forgeable TLS chains. v0.9.4's lock pins `2026.5.20`, and `pyproject.toml` sets no minimum. The fix lands on `develop` first, then is cherry-picked onto the tag (`release.md` §"Hotfix from the last tag").

- [x] Require `certifi>=2026.10.19` and ship it as the v0.9.5 hotfix. `severe/narrow` — lane A, after #1069 ([#1217](https://github.com/khuisman/mcp-gee-sweet/issues/1217)) (PR #1218; shipped in v0.9.5 via PR #1219)

### ornithomimus — launch release: Markdown fidelity, Gmail sending safety, launch readiness _(queued, label [`planned: ornithomimus`](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22planned%3A+ornithomimus%22); gets a number when it goes in flight)_

Feature set and fill set by the maintainer 2026-10-18, under the release-scoping rules in [#1085](https://github.com/khuisman/mcp-gee-sweet/issues/1085). The release ships when the feature set is done and passes release QA. **Locked 2026-10-18**, after Aziz's #1044 Phase 1 baseline: the baseline's defects joined the Markdown feature set, and #646, #957, #1078, #1100, #1103 and #1104 moved to ankylosaurus. From here only urgent fixes join (the rubric's in-flight cases and security fixes); Phase 2 findings come in only that way.

**Re-split 2026-10-24 (maintainer):** ornithomimus is the launch release: Markdown → Docs fidelity, Gmail sending safety, launch readiness, and #1060 for the release pass. The comments feature set (with its breaking rename), the docstring and `font_family` fill items, #1076, #897 and #1202 moved to _ankylosaurus_ (#1069 went too, then came back the same day as a Markdown fidelity item), which now carries every breaking rename together. #1205 joined the Gmail feature set.

**Renamed 2026-10-22 (maintainer):** this feature set was v0.9.4 until the Pillow hotfix took that number. It's queued again as _ornithomimus_, ahead of _ankylosaurus_, and its open tickets moved from `v0.9.4` to `planned: ornithomimus`. The fill lock above still holds.

**Renumbering, 2026-10-19/20 (maintainer):** this feature set was v0.9.3. 0.9.3 now ships ahead of it (section above), so it is v0.9.4; every open ticket here moved to the `v0.9.4` label on 2026-10-20, and its shipped items moved to the v0.9.3 section.

**Feature set: Markdown → Docs fidelity**

- [ ] QA: Playwright-verified test plan for Markdown → Google Docs rendering (full syntax, every entry point) — absorbs #477 (full-construct fixture), closed into it 2026-10-18 ([#1044](https://github.com/khuisman/mcp-gee-sweet/issues/1044))
- [x] Markdown sub-lists indented 2 or 3 spaces don't nest ([#1071](https://github.com/khuisman/mcp-gee-sweet/issues/1071)) (PR #1228)
- [x] A numbered list restarts its numbering after a nested bullet list. #1241, the reverse case in the same run grouping, was folded in (maintainer, 2026-10-28) but PR #1286 didn't fix it, so #1241 stays open below — lane A ([#1072](https://github.com/khuisman/mcp-gee-sweet/issues/1072)) (PR #1286)
- [x] Two adjacent Markdown lists render as one Docs list. `wrong/narrow`, observed in TC-MD105/108. Folded into #1072 (maintainer, 2026-10-28), but PR #1286 didn't fix it: it needs a list boundary in the AST — lane A ([#1241](https://github.com/khuisman/mcp-gee-sweet/issues/1241)) (PR #1295)
- [x] Images inside table cells are dropped silently ([#1073](https://github.com/khuisman/mcp-gee-sweet/issues/1073)) (PR #1215)
- [ ] HTML input: whitespace between list tags becomes stray bullet paragraphs ([#1074](https://github.com/khuisman/mcp-gee-sweet/issues/1074))
- [ ] A bare '-' (empty list item) isn't recognized in Markdown ([#1075](https://github.com/khuisman/mcp-gee-sweet/issues/1075))
- [ ] **Bundle:** Markdown/HTML inline styles — one PR closing [#1077](https://github.com/khuisman/mcp-gee-sweet/issues/1077) (strikethrough, `<del>`) and [#1119](https://github.com/khuisman/mcp-gee-sweet/issues/1119) (`<sub>`, `<sup>`, `<mark>`); after PR #1228, check how much of #1077 the GFM strikethrough rule already fixed. Bundled 2026-10-25 (maintainer) ([#1231](https://github.com/khuisman/mcp-gee-sweet/issues/1231))
- [x] get_doc_as_markdown indents a numbered sub-list under a numbered item by only 2 spaces, so it re-imports flat. Found in the 0.9.3 release-QA pass ([#1128](https://github.com/khuisman/mcp-gee-sweet/issues/1128)) (PR #1234)
- [x] get_doc_as_markdown renumbers a numbered list from 1 after a table (or any block) interrupts it, so it re-imports as two lists. `wrong/narrow`, observed in PR #1201 QA ([#1208](https://github.com/khuisman/mcp-gee-sweet/issues/1208)) (PR #1234)
- [x] create_paragraph_bullets adds the requested nesting level to an item's current level instead of setting it. It's the repair path `get_doc_structure` points to for a Markdown conversion that flattened a nested list, so it belongs with Markdown fidelity; moved back from ankylosaurus 2026-10-24 (maintainer) — lane A ([#1069](https://github.com/khuisman/mcp-gee-sweet/issues/1069)) (PR #1216)
- [ ] **Bundle:** Markdown/HTML image sources — one PR closing [#1121](https://github.com/khuisman/mcp-gee-sweet/issues/1121) (relative path against the `.md` file), [#1139](https://github.com/khuisman/mcp-gee-sweet/issues/1139) (`update_doc_from_file` has no `folder_id`) and [#1099](https://github.com/khuisman/mcp-gee-sweet/issues/1099) (unfetchable image dropped without a trace); after PR #1228. Bundled 2026-10-25 (maintainer) ([#1232](https://github.com/khuisman/mcp-gee-sweet/issues/1232))
- [x] YAML front matter is rendered as text instead of omitted (plan rule D3). Triaged 2026-10-24 ([#1173](https://github.com/khuisman/mcp-gee-sweet/issues/1173)) (PR #1303)
- [x] Markdown/HTML conversion: tell the caller when a link is dropped. Added 2026-10-24 (maintainer) ([#1180](https://github.com/khuisman/mcp-gee-sweet/issues/1180)) (PR #1272)
- [x] search_files/search_spreadsheets/list_spreadsheets miss Shared Drive files under a service account when no folder is given. `wrong/narrow`, observed in the 0.9.3 release-QA pass; v0.9.3's fill is locked ([#1127](https://github.com/khuisman/mcp-gee-sweet/issues/1127)) (PR #1200)
- [x] Loose list items (<li><p>…</p></li>) lose their bullet — community PR #1164 (pulled from lane A), html_parser cluster ([#1111](https://github.com/khuisman/mcp-gee-sweet/issues/1111)) (PR #1164)
- [ ] **Bundle:** Markdown/HTML line breaks — one PR closing [#1093](https://github.com/khuisman/mcp-gee-sweet/issues/1093) (soft break), [#1117](https://github.com/khuisman/mcp-gee-sweet/issues/1117) (hard break) and [#1091](https://github.com/khuisman/mcp-gee-sweet/issues/1091) (`<br>` in prose), html_parser cluster; after PR #1228. Bundled 2026-10-25 (maintainer) ([#1230](https://github.com/khuisman/mcp-gee-sweet/issues/1230))
- [x] A fenced code block or second paragraph inside a list item breaks the list — html_parser cluster; fence half may fold into #1116 ([#1094](https://github.com/khuisman/mcp-gee-sweet/issues/1094)) (PR #1301)
- [x] Adjacent blocks run together: separate quotes merge, consecutive code blocks merge, quotes have no spacing — lane B, after #1056 ([#1098](https://github.com/khuisman/mcp-gee-sweet/issues/1098)) (PR #1199)
- [ ] A thematic break (`---`) renders as an empty paragraph ([#1096](https://github.com/khuisman/mcp-gee-sweet/issues/1096))
- [ ] GFM table column alignment is ignored ([#1095](https://github.com/khuisman/mcp-gee-sweet/issues/1095))
- [x] A table takes on the style of the paragraph that follows it ([#1097](https://github.com/khuisman/mcp-gee-sweet/issues/1097)) (PR #1201)
- [x] Drive's native Markdown import (EP-5 to EP-7) renders differently from our converter — ornithomimus scope: document EP-5 to EP-7 as Drive's engine; routing is #1113 ([#1101](https://github.com/khuisman/mcp-gee-sweet/issues/1101)) (PR #1270)
- [x] `upload_file(source_format="markdown", convert_to_doc=True)` (EP-8) loses list nesting, code styling and task glyphs, and is nondeterministic — route EP-8 through the create_doc Markdown path, plus a CHANGELOG line ([#1102](https://github.com/khuisman/mcp-gee-sweet/issues/1102)) (PR #1283)
- [x] Switch the Markdown parser to CommonMark/GFM (decided 2026-10-18), keeping the HTML → AST → Docs pipeline. Absorbs Joy's spike [#1112](https://github.com/khuisman/mcp-gee-sweet/issues/1112), closed into it 2026-10-24. Doesn't fix #1071 on its own (needs a pre-pass), nor #1093/#1115/#1117 (HTML → AST step) ([#1116](https://github.com/khuisman/mcp-gee-sweet/issues/1116)) (PR #1228)
- [x] A loose list (blank lines between items) loses its bullets and numbers — #1044 Phase 2 finding; HTML → AST step, not fixed by #1116 alone ([#1115](https://github.com/khuisman/mcp-gee-sweet/issues/1115)) (PR #1164)
- [ ] An ordered list's start number is ignored; the Docs API has no request that sets it, so a fix needs a workaround — #1044 Phase 2 finding ([#1118](https://github.com/khuisman/mcp-gee-sweet/issues/1118))
- [ ] Tables, rules and nested quotes inside a blockquote render outside it — #1044 Phase 2 finding ([#1122](https://github.com/khuisman/mcp-gee-sweet/issues/1122))
- [x] A relative link becomes `http://./guide.md` — community PR ([#1120](https://github.com/khuisman/mcp-gee-sweet/issues/1120)) (PR #1149)
- [x] Blank paragraph before a table keeps the preceding heading's style — community PR ([#1092](https://github.com/khuisman/mcp-gee-sweet/issues/1092)) (PR #1138)

**Feature set: Gmail sending safety**

- [x] Safe-by-default sending: `send_message`/`reply_to_message`/`send_draft` don't deliver without explicit confirmation (drafts-first or elicitation), flag external-domain and over-threshold recipients, documented opt-out. Behavior change, needs a `CHANGELOG.md` note. Spec updated 2026-10-25 from Joy's design pass (detection needs `elicitation.form` and `can_send_request`; catch `NoBackChannelError`; refuse a draft changed after confirmation); hold lifted (maintainer). The 2026-07-28 round trip, #1235, is not planned ([#1081](https://github.com/khuisman/mcp-gee-sweet/issues/1081)) (PR #1249)
- [x] Gmail: list, get, update and delete drafts, so a drafts-first flow can be managed end to end. Added 2026-10-24 ([#1205](https://github.com/khuisman/mcp-gee-sweet/issues/1205)) (PR #1227)

**Feature set: launch readiness**

- [x] Ship an MCP Bundle (.mcpb) for one-click install; the Smithery listing was dropped, since Smithery ends its CLI and connection services 2026-10-31 ([#1036](https://github.com/khuisman/mcp-gee-sweet/issues/1036)) (PR #1255)
- [ ] Demo screenshot or GIF for the README — routed to Amy; how the asset gets produced is still open ([#589](https://github.com/khuisman/mcp-gee-sweet/issues/589))
- [ ] Fact-check and word competitive/benchmark claims once real benchmark numbers exist — routed to Amy, triaged out of `backlog` 2026-09-11 — only if the competitor comparisons come back; otherwise it moves out. Labeled `planned: ornithomimus` 2026-10-24 ([#585](https://github.com/khuisman/mcp-gee-sweet/issues/585))
- [x] CI tests Python 3.11–3.13 only; add 3.14 and 3.15, and fold in #1171's Python 3.10 leftovers. Added 2026-10-24 ([#1212](https://github.com/khuisman/mcp-gee-sweet/issues/1212)) (PR #1222)
- [x] Make Lint and test 3.14/3.15 required status checks on `develop` and `main` — #1212 review follow-up, a branch-protection settings change with no PR ([#1224](https://github.com/khuisman/mcp-gee-sweet/issues/1224))
- [x] A next-release label so contributors can find what ships next. Added 2026-10-24 (maintainer) ([#1185](https://github.com/khuisman/mcp-gee-sweet/issues/1185)) (PR #1253)
- [ ] Docs for client tool limits: VS Code's 128-tools-per-request cap breaks a default install on the first call. README note, `configuration.md` subsets framed around client limits, per-client snippets, a known-limitations entry; VS Code and Cursor checks may be Aziz's. Added 2026-10-24 (maintainer) ([#1214](https://github.com/khuisman/mcp-gee-sweet/issues/1214)) (docs landed in PR #1254; VS Code + Copilot and Cursor live checks still open)

**Fill** _(rank order, locked 2026-10-18)_

- [x] transfer.py interpolates folder IDs unescaped into Drive queries ([#1084](https://github.com/khuisman/mcp-gee-sweet/issues/1084)) (PR #1140)
- [x] get_doc_structure hides inline images, so an image's index can't be found ([#1070](https://github.com/khuisman/mcp-gee-sweet/issues/1070)) (PR #1110)
- [x] thread_http's per-thread `httplib2.Http` has no socket timeout, so a silently dropped connection hangs a call until ETIMEDOUT. `severe`, observed: a 30-minute `create_doc_from_file` hang in the #1044 run left an empty Doc. Joined after the lock and ranked first by the maintainer, 2026-10-22 ([#1129](https://github.com/khuisman/mcp-gee-sweet/issues/1129)) (PR #1198)
- [x] `transfer_ownership(send_notification=False)` can never succeed — `loud/narrow` ([#1055](https://github.com/khuisman/mcp-gee-sweet/issues/1055)) (PR #1142)
- [x] Refresh stale TC expectations found in the v0.9.2 pass ([#1060](https://github.com/khuisman/mcp-gee-sweet/issues/1060)) (PR #1271)
- [x] Test modules fail to collect on Windows (`os.geteuid()` in skipif decorators) — community PR ([#1156](https://github.com/khuisman/mcp-gee-sweet/issues/1156)) (PR #1162)
- [x] `setup_team.sh` never re-syncs a slot's credentials after they change, so release QA ran on stale identities — release-gate, Aziz ([#1223](https://github.com/khuisman/mcp-gee-sweet/issues/1223)) (PR #1225)
- [x] `write_doc_content`/`update_doc_from_file` clear the Doc before converting the Markdown, so a failed conversion with no backup leaves it empty. `severe/rare`; joined the locked fill 2026-10-28 (maintainer) — lane B after #1102 ([#1240](https://github.com/khuisman/mcp-gee-sweet/issues/1240)) (PR #1296)
- [x] A bare `www.` autolink gets `http://` while an explicit `www.` target gets `https://` (#1180). `wrong/common` now that the maintainer chose https for both, 2026-10-28; joined the locked fill ([#1281](https://github.com/khuisman/mcp-gee-sweet/issues/1281)) (PR #1298)
- [x] Drive transfer tools raise `HttpError` on a 404 instead of returning an error result. `loud/narrow`; community PR #1278 merged 2026-10-31; moved from ankylosaurus, the maintainer's call to ship it here ([#1275](https://github.com/khuisman/mcp-gee-sweet/issues/1275)) (PR #1278)
- [x] `style_doc_range` with only `font_family` clears bold on the range. `wrong/narrow`, observed, not a regression; community PR #1279 merged 2026-10-31; moved from ankylosaurus, the maintainer's call to ship it here ([#1273](https://github.com/khuisman/mcp-gee-sweet/issues/1273)) (PR #1279)
- [x] A table inside a list item renders at the left margin instead of under the item's text (C14). `wrong/narrow`, observed in #1268's live check; fixed by #1094's change, confirmed live 2026-10-31 (TC-MD201 CT-08/18/28/38/48/58) ([#1277](https://github.com/khuisman/mcp-gee-sweet/issues/1277)) (PR #1301)
- [ ] `get_doc_as_markdown` exports a block inside a list item at the margin, and a quote inside an item as `> >`. `wrong/narrow`, observed; the quote half is a regression since v0.9.5 (PR #1301 put it at 72pt). Joined the locked fill 2026-10-31 (maintainer); from PR #1301's review — lane A ([#1302](https://github.com/khuisman/mcp-gee-sweet/issues/1302))

**Live QA for merged community PRs** _(their code ships in this release; run on the gee-sweet-biz side)_

- [x] qa: live verification for PR #1110 (inline images in get_doc_structure runs) ([#1157](https://github.com/khuisman/mcp-gee-sweet/issues/1157)) (live PASS 2026-10-27)
- [x] qa: live verification for PR #1138 (blank paragraph before a table) ([#1160](https://github.com/khuisman/mcp-gee-sweet/issues/1160)) (live PASS 2026-10-27)
- [x] qa: live verification for PR #1140 (escaped folder IDs in transfer.py queries) ([#1167](https://github.com/khuisman/mcp-gee-sweet/issues/1167)) (live PASS 2026-10-27)
- [x] qa: live verification for PR #1149 (scheme-less link targets) ([#1190](https://github.com/khuisman/mcp-gee-sweet/issues/1190)) (live PASS 2026-10-27)
- [x] qa: live verification for PR #1026 (`font_family` in `style_doc_range`). Moved from ankylosaurus 2026-10-31 (maintainer) so the #1273 fix shipping here is checked live ([#1153](https://github.com/khuisman/mcp-gee-sweet/issues/1153)) (live PASS 2026-10-31; heading-bold add-on failed → #1300)
- [x] qa: live verification for PR #1279 (`font_family` keeps direct bold, table cells, explicit `bold` in the same call) ([#1299](https://github.com/khuisman/mcp-gee-sweet/issues/1299)) (live PASS 2026-10-31)
- [ ] qa: live verification for PR #1164 (loose list items keep their bullets); run after #1228 so it covers the new parser ([#1268](https://github.com/khuisman/mcp-gee-sweet/issues/1268))
- [x] qa: point docs_markdown.md's EP-5 to EP-7 expected rendering at the Drive-importer known-limitations entry; closes out #1101 ([#1263](https://github.com/khuisman/mcp-gee-sweet/issues/1263)) (PR #1270)

Moved out 2026-10-18: [#379](https://github.com/khuisman/mcp-gee-sweet/issues/379) (unversioned, Joy decides whether to do it); [#378](https://github.com/khuisman/mcp-gee-sweet/issues/378) closed (ASYNC240 stays off). Everything else formerly here is under _ankylosaurus_ below.

### ankylosaurus — hardening and tool-surface cleanup _(queued, label [`planned: ankylosaurus`](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22planned%3A+ankylosaurus%22); gets a number when it goes in flight)_

Fill candidates moved from v0.9.3 and the decision-needed backlog on 2026-10-18. The maintainer sets this version's feature set and locks its fill when it opens.

**Re-split 2026-10-24 (maintainer):** ankylosaurus is now hardening plus tool-surface cleanup. It carries all the breaking renames together: the comments generalization (moved from ornithomimus, below) and #665's `share_spreadsheet` removal. It also gets the docstring cleanup, and whatever the tool-reduction spike recommends.

**Feature set: comments** _(moved from ornithomimus 2026-10-24)_ — follows [`docs/decisions/decision-comments-first-class.md`](decisions/decision-comments-first-class.md) ([#661](https://github.com/khuisman/mcp-gee-sweet/issues/661)) and ships a breaking rename that the release notes must call out.

- [ ] Deprecation policy for renamed and removed tools: an old name stays as an alias for one release, with a CHANGELOG note. Prerequisite of #663/#664 and #665, decided 2026-10-24 ([#1209](https://github.com/khuisman/mcp-gee-sweet/issues/1209))
- [ ] Generalize the three comment tools to `tools/drive/comments.py` and rename `list_doc_comments`/`add_doc_comment`/`resolve_doc_comment` → `list_file_comments`/`add_file_comment`/`resolve_comment` (param `doc_id` → `file_id`); retire `tools/docs/comments.py`. Breaking change. ([#663](https://github.com/khuisman/mcp-gee-sweet/issues/663))
- [ ] Full `comments`/`replies` CRUD parity — `get`/`update`/`delete` for comments; plain `reply`/`reopen`/`update`/`delete`/`list` for replies. Depends on #663. ([#664](https://github.com/khuisman/mcp-gee-sweet/issues/664))
- [ ] Follow-up cleanup for the docs comments API (`add_doc_comment`/`resolve_doc_comment`/`list_doc_comments`) — same surface #663/#664 generalize, do it there rather than twice; triaged out of `backlog` 2026-09-11 ([#329](https://github.com/khuisman/mcp-gee-sweet/issues/329))

**Moved from ornithomimus at the re-split, 2026-10-24**

- [ ] create_bookmark doesn't create a bookmark Docs lists — docstring fix (option 2) now ([#1076](https://github.com/khuisman/mcp-gee-sweet/issues/1076))
- [ ] **Docstrings, one item:** Tool docstrings: strip internal issue refs again, and add a guard test ([#1045](https://github.com/khuisman/mcp-gee-sweet/issues/1045)), Docstrings: 'Requires OAuth or ADC auth' is wrong for a service account on a Shared Drive ([#1046](https://github.com/khuisman/mcp-gee-sweet/issues/1046)), list_spreadsheets docstring sends callers to list_files for a result cap it now has ([#1047](https://github.com/khuisman/mcp-gee-sweet/issues/1047)), Docstring fixes: named-style resets, and set_cache_ttl's transport claim ([#1058](https://github.com/khuisman/mcp-gee-sweet/issues/1058)), Docstrings: create_paragraph_bullets carries internal API-quirk mechanics plus residual bare issue refs in style.py tool docstrings ([#683](https://github.com/khuisman/mcp-gee-sweet/issues/683)), Docstring ref guard: cover every tool regardless of env, tighten the pattern, finish the prose cleanup ([#1197](https://github.com/khuisman/mcp-gee-sweet/issues/1197))
- [ ] **`font_family`, one item:** Document `font_family` on `insert_softbreak_paragraph` and widen the style_doc_range font test ([#1037](https://github.com/khuisman/mcp-gee-sweet/issues/1037)), Harden `font_family` in Docs text-style requests: preserve weight, reject empty values, share one builder ([#1038](https://github.com/khuisman/mcp-gee-sweet/issues/1038))
- [ ] **Bundle:** CI tidy (on deck, no lane), one PR closing [#536](https://github.com/khuisman/mcp-gee-sweet/issues/536), [#619](https://github.com/khuisman/mcp-gee-sweet/issues/619), [#308](https://github.com/khuisman/mcp-gee-sweet/issues/308), [#708](https://github.com/khuisman/mcp-gee-sweet/issues/708) ([#897](https://github.com/khuisman/mcp-gee-sweet/issues/897))
- [ ] Unscoped Drive listings don't surface `incompleteSearch` under `corpora=allDrives`, so a partial result reads as complete. Review follow-up from PR #1200; changes five tools' output schema, `decision-needed` ([#1202](https://github.com/khuisman/mcp-gee-sweet/issues/1202))

**Decided behavior changes**

- [ ] `batch_update_cells` empty input — validation error vs silent no-op — decided 2026-10-18: return `{"error": ...}` ([#32](https://github.com/khuisman/mcp-gee-sweet/issues/32))
- [ ] `search_spreadsheets` empty query — return all or require non-empty input — decided 2026-10-18: return `{"error": ...}` pointing to `list_spreadsheets` ([#39](https://github.com/khuisman/mcp-gee-sweet/issues/39))
- [ ] Deprecate `share_spreadsheet` in favor of `share_file`, and remove it before 1.0 (decided 2026-10-18) ([#665](https://github.com/khuisman/mcp-gee-sweet/issues/665))

**Candidates**

- [ ] Optional expiration on sharing tools ([#1059](https://github.com/khuisman/mcp-gee-sweet/issues/1059))
- [ ] `server://auth-status` doesn't list `export_revision` under a service account's `no_drive_storage_quota` limits. Found in PR #1006's QA; predates v0.9.2 and not observed failing, so v0.9.3 per the review-ticket rule ([#1010](https://github.com/khuisman/mcp-gee-sweet/issues/1010))
- [ ] `_parse_a1_notation` rejects `A:B5`, which the Sheets values API accepts as `A5:B` — decided 2026-10-11: keep rejecting (a destructive GridRange tool acting on "row 5 onward" is worse than an error); document in the docstring that this is deliberately stricter than Sheets. Found in PR #986 — lane A; moved from v0.9.2 2026-10-11 (docstring only, current behavior is the safe one) ([#987](https://github.com/khuisman/mcp-gee-sweet/issues/987))
- [ ] **Bundle:** Calendar follow-ups from PR #912, one PR closing [#915](https://github.com/khuisman/mcp-gee-sweet/issues/915), [#918](https://github.com/khuisman/mcp-gee-sweet/issues/918) — lane B, after #892 ([#985](https://github.com/khuisman/mcp-gee-sweet/issues/985))
- [ ] **Bundle:** Docs read side (`doc_to_ast`/`ast_to_markdown`), one PR closing [#596](https://github.com/khuisman/mcp-gee-sweet/issues/596), [#600](https://github.com/khuisman/mcp-gee-sweet/issues/600), [#732](https://github.com/khuisman/mcp-gee-sweet/issues/732) — lane B ([#893](https://github.com/khuisman/mcp-gee-sweet/issues/893))
- [ ] **Bundle:** server/infra hygiene (start after #872), one PR closing [#517](https://github.com/khuisman/mcp-gee-sweet/issues/517), [#607](https://github.com/khuisman/mcp-gee-sweet/issues/607), [#614](https://github.com/khuisman/mcp-gee-sweet/issues/614), [#579](https://github.com/khuisman/mcp-gee-sweet/issues/579), [#637](https://github.com/khuisman/mcp-gee-sweet/issues/637) — lane B ([#892](https://github.com/khuisman/mcp-gee-sweet/issues/892))
- [ ] Dedicated QA calendar, teardown for creation-only tests, and a `cleanup_stray_artifacts` sweep — split from #304, no second account needed — Aziz ([#886](https://github.com/khuisman/mcp-gee-sweet/issues/886))
- [ ] `sync_folder(export_format=...)`: converted Sheets/Slides probably have #814's `modifiedTime` lag and restamp race too. Suspected, not yet observed ([#818](https://github.com/khuisman/mcp-gee-sweet/issues/818))
- [ ] Add a tool to set (and read back) Google Docs table column widths — `tableColumnProperties` isn't reachable through any tool today ([#809](https://github.com/khuisman/mcp-gee-sweet/issues/809))
- [ ] **Bundle:** Docs link storability — one PR closing [#1189](https://github.com/khuisman/mcp-gee-sweet/issues/1189) (refuse `javascript:`/`vbscript:`/`data:`; decided 2026-10-25: converter falls back to plain text, `style_doc_range` errors), [#1179](https://github.com/khuisman/mcp-gee-sweet/issues/1179) (scheme-less `link_url` in `style_doc_range`), [#1191](https://github.com/khuisman/mcp-gee-sweet/issues/1191) (drive-letter and host:port targets, padded cell anchors) and [#1237](https://github.com/khuisman/mcp-gee-sweet/issues/1237) (`get_doc_as_markdown` re-emits script links), through one shared helper. Bundled 2026-10-25 (maintainer) ([#1238](https://github.com/khuisman/mcp-gee-sweet/issues/1238))
- [ ] `create_spreadsheet`/`import_csv_to_sheet` response has no web link, unlike sibling create/copy tools — enhancement or fix TC-D01's expectation instead, still open. Found in the v0.9.0 QA pass ([#693](https://github.com/khuisman/mcp-gee-sweet/issues/693))
- [ ] Several `drive_files.md` cases assume My-Drive semantics now that fixtures live in a Shared Drive (TC-D58/D61/D03/D59/D27/D04/D175); TC-D27 overlaps #689's `list_folders` gap — Aziz reviews during Full Regression prep ([#680](https://github.com/khuisman/mcp-gee-sweet/issues/680))
- [ ] QA `.env` has no single source of truth — `setup_team.sh` only copies `.env` into a worktree when absent, so fixture-ID changes never propagate (had to hand-sync 9 copies for #305); also `run.md` vs `setup.md` disagree on `docs/qa/.env` vs repo-root `.env`. Surfaced by PR #677, relates to [#648](https://github.com/khuisman/mcp-gee-sweet/issues/648) ([#679](https://github.com/khuisman/mcp-gee-sweet/issues/679))
- [ ] TC-DOC80 can no longer trip the response-size cap post-#519 — large-doc fixture is under the raised default; needs a per-case low-cap override — Aziz ([#678](https://github.com/khuisman/mcp-gee-sweet/issues/678))
- [ ] Automate the mechanical `release.md` steps as GitHub Actions ([#660](https://github.com/khuisman/mcp-gee-sweet/issues/660))
- [ ] Harden `tests/integration`'s local-fs live QA harness — error surfacing on API failures, subprocess/handshake timeouts, cleanup-masking a real test failure, per-test subprocess overhead ([#648](https://github.com/khuisman/mcp-gee-sweet/issues/648))
- [ ] Define the correctness rubric and own execution for the composite-vs-primitive efficiency benchmark — Aziz ([#584](https://github.com/khuisman/mcp-gee-sweet/issues/584))
- [ ] `qa`: `search_files` has no unit test coverage for the error-dict path ([#573](https://github.com/khuisman/mcp-gee-sweet/issues/573))
- [ ] Investigate other MCP clients' response-overflow handling for platform-specific `MAX_TOOL_RESPONSE_CHARS` guidance ([#555](https://github.com/khuisman/mcp-gee-sweet/issues/555))
- [ ] Automated tooling for dependency-bump security review — today's manual skim can miss a well-disguised supply-chain compromise ([#520](https://github.com/khuisman/mcp-gee-sweet/issues/520))
- [ ] Split `tools/sheets/structure.py` by domain (1865 lines, 25 tools) ([#376](https://github.com/khuisman/mcp-gee-sweet/issues/376))
- [ ] Domain and public sharing tests (TC-D135–D139) — decision landed 2026-09-02: provision a real non-Google test email for external-share coverage; the `type=anyone` public-link tests stay unresolved (exposure risk not yet accepted) ([#49](https://github.com/khuisman/mcp-gee-sweet/issues/49))

**Moved from v0.9.3 at the lock, 2026-10-18**

- [ ] `update_doc_from_file`: opt-in incremental (`mode="patch"`) update that diffs block by block and rewrites only changed blocks, so comment anchors and revision history survive — lane A, after #878 (same write-path files) ([#957](https://github.com/khuisman/mcp-gee-sweet/issues/957))
- [ ] Interaction-log middleware for tool calls — structured, append-only JSONL log per call (inputs, duration, cache hit, error), opt-in ID redaction, swappable backend ([#646](https://github.com/khuisman/mcp-gee-sweet/issues/646))
- [ ] get_doc_as_markdown: nested-table placeholder runs into the cell text ([#1078](https://github.com/khuisman/mcp-gee-sweet/issues/1078))
- [ ] A document ending in a table can get a blank last page ([#1100](https://github.com/khuisman/mcp-gee-sweet/issues/1100))
- [ ] `get_doc_as_markdown` exports the collapsed pre-table paragraph as an empty heading ([#1103](https://github.com/khuisman/mcp-gee-sweet/issues/1103))
- [ ] `get_doc_as_markdown` exports Drive-imported lists as blockquoted numbered items ([#1104](https://github.com/khuisman/mcp-gee-sweet/issues/1104))
- [ ] Design: route Drive's Markdown import paths (EP-5 to EP-7) through our converter — Joy design; EP-5 to EP-7 stay on Drive's engine in v0.9.3 ([#1113](https://github.com/khuisman/mcp-gee-sweet/issues/1113))

**Triaged in 2026-10-18**

- [ ] `create_paragraph_bullets` drops a blockquoted paragraph's quote indent — `wrong/narrow`, observed; from PR #1089's review, after v0.9.3's lock ([#1090](https://github.com/khuisman/mcp-gee-sweet/issues/1090))
- [x] Document as a known limitation: a list inside a blockquote draws its border at the list indent, not the quote's. Maintainer's call 2026-10-29, after community PR #1258 (closed) showed Docs draws the border at `indentStart`, the same setting as the item's hanging indent. Out of ankylosaurus since then: a docs ticket with no version label, Amy ([#1242](https://github.com/khuisman/mcp-gee-sweet/issues/1242)) (PR #1294)
- [x] DocContentCache.store has no epoch guard; a pre-edit fetch can overwrite an edit's mark_dirty — `wrong/rare` ([#1032](https://github.com/khuisman/mcp-gee-sweet/issues/1032)) (PR #1264)
- [x] Doc-edit tools outside content/images leave the doc cache stale when cancelled mid-edit — `wrong/rare` ([#1030](https://github.com/khuisman/mcp-gee-sweet/issues/1030)) (PR #1264)
- [ ] Sheets and Calendar write tools leave their caches stale when cancelled or failed mid-write. `wrong/rare`; found in PR #1264, the same gap #1030 closed for Docs and Drive ([#1265](https://github.com/khuisman/mcp-gee-sweet/issues/1265))
- [ ] pre-commit's ruff-format hook skips Markdown, but CI's ruff format --check . formats it ([#1087](https://github.com/khuisman/mcp-gee-sweet/issues/1087))
- [ ] Make scripts/qa_compile_results.py the standard compile step of a release QA pass ([#1067](https://github.com/khuisman/mcp-gee-sweet/issues/1067))
- [ ] Track release-QA spend across releases so passes can be sized ahead of time ([#1068](https://github.com/khuisman/mcp-gee-sweet/issues/1068))

**Triaged in 2026-10-24**

- [x] transfer.py folder listings stop at 1,000 children: `download_folder` truncates, `sync_folder` and `upload_local_folder` upload duplicates. `wrong/narrow` ([#1165](https://github.com/khuisman/mcp-gee-sweet/issues/1165)) (PR #1261)
- [ ] Drive query escaping: the MIME filter skips backslash; consolidate the escape sites. `loud/rare` ([#1166](https://github.com/khuisman/mcp-gee-sweet/issues/1166))
- [ ] `transfer_ownership` follow-ups: `send_notification` has one valid value (schema change); consumer and shared-drive transfers fail opaquely. `loud/narrow` ([#1181](https://github.com/khuisman/mcp-gee-sweet/issues/1181))
- [ ] Cache TTL docs and log line say process-wide; under SSE it's per connection. Docs, with the docstring cleanup ([#1187](https://github.com/khuisman/mcp-gee-sweet/issues/1187))
- [ ] Service-account storage limit: remaining docstrings and docs disagree with #1046's corrected note. Docs, with the docstring cleanup ([#1188](https://github.com/khuisman/mcp-gee-sweet/issues/1188))
- [ ] Windows: permission and symlink tests fail now that their modules collect (#1162 follow-up). `loud/narrow`, test-only ([#1194](https://github.com/khuisman/mcp-gee-sweet/issues/1194))
- [ ] `insert_inline_image(drive_file_id=)` should grant and revoke the temporary `anyone:reader` share itself through `ImageShareLifecycle`, like the Markdown image path, instead of pushing a `share_file` call onto the caller. Tool-surface cleanup; version call 2026-10-25 (maintainer) ([#1183](https://github.com/khuisman/mcp-gee-sweet/issues/1183))
- [ ] HTML table cells: source newlines become paragraph breaks instead of collapsing like a browser. Enhancement; whether a cell newline should collapse was left open in PR #1215 ([#1221](https://github.com/khuisman/mcp-gee-sweet/issues/1221))
- [ ] HTML input: source line breaks at a block's start or end become empty paragraphs (pretty-printed HTML). `wrong/narrow`, not observed; found in PR #1228, grouped with #1221 ([#1229](https://github.com/khuisman/mcp-gee-sweet/issues/1229))
- [ ] html_parser: edge cases in a list item's transparent `<p>` (trailing line breaks, etc.). `wrong/narrow`, not observed; found in PR #1164's review ([#1266](https://github.com/khuisman/mcp-gee-sweet/issues/1266))
- [ ] Reauth offer (#873) on MCP 2026-07-28 connections: capability-only check and a retired `-32042`. `loud/rare`; found in #1081's design pass ([#1236](https://github.com/khuisman/mcp-gee-sweet/issues/1236))

**Triaged in 2026-10-28**

- [ ] Drive tools: one `HttpError` policy after #1278 (lost logging and access-log status, the `isError` contract across sibling tools, stale text, quota/5xx tests). `loud/narrow`; from the #1278 review, after it merges ([#1287](https://github.com/khuisman/mcp-gee-sweet/issues/1287))
- [ ] `style_doc_range` font-only bold restore (after #1279): no revision guard between the read and the write, unmasked read, read error indistinguishable from a write error, no table-cell test. `wrong/rare`; from the #1279 review ([#1289](https://github.com/khuisman/mcp-gee-sweet/issues/1289))
- [ ] Markdown D1: also move a fence or paragraph indented beside a moved sub-list marker. Enhancement, needs the maintainer's parse-rule call ([#1243](https://github.com/khuisman/mcp-gee-sweet/issues/1243))
- [ ] Markdown task lists as native Docs checkboxes (`BULLET_CHECKBOX`) instead of a disc bullet plus a glyph. First check live whether the API can set the checked state ([#1280](https://github.com/khuisman/mcp-gee-sweet/issues/1280))

**Triaged in 2026-10-29**

- [ ] Markdown links to `file:` and script schemes render as literal `[text](target)` source, with no `dropped_links` entry. `wrong/narrow`, regression since v0.9.5 (PR #1228's markdown-it switch); placed here by the maintainer (2026-10-29), not in ornithomimus's locked fill, though the rubric allows a regression there. #1291 closed as its duplicate ([#1290](https://github.com/khuisman/mcp-gee-sweet/issues/1290))
- [ ] `create_paragraph_bullets` restarts a numbered list's numbering after a nested list of the other type: its same-`listId` expansion walks only adjacent paragraphs, so it re-bullets the items after the nested list as a new list. `wrong/narrow`, observed (live on PR #1286), not a regression; from PR #1286's review. Grouped with #1090, the same function ([#1288](https://github.com/khuisman/mcp-gee-sweet/issues/1288))
- [ ] `create_paragraph_bullets` puts a paragraph one level too deep, in the wrong list, when the paragraph before it is in a same-preset list. `wrong/narrow`, observed (live, PR #1295); from PR #1295's review. `decision-needed`: whether it should join that list at the requested level or start its own ([#1297](https://github.com/khuisman/mcp-gee-sweet/issues/1297))

**Triaged in 2026-10-31**

- [ ] `style_doc_range`: a `font_family`-only change turns off bold inherited from a named style (Docs writes `bold: false`). `wrong/narrow`, observed in #1153's live check; the second follow-up in #1273's family, after #1289 ([#1300](https://github.com/khuisman/mcp-gee-sweet/issues/1300))
- [ ] `upload_local_file(convert=True)`: a `name=` without an extension errors instead of falling back to `local_path`'s extension. `loud/narrow`; the drop-`.md`-from-the-Doc-name half split out to #1309 ([#1307](https://github.com/khuisman/mcp-gee-sweet/issues/1307))

### velociraptor — Parity 1 _(queued, label [`planned: velociraptor`](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22planned%3A+velociraptor%22); gets a number when it goes in flight)_

Queued after _ankylosaurus_ (maintainer, 2026-10-24): the first parity release. The maintainer sets its feature set and locks its fill when it opens.

- [ ] Docs: read every tab of a multi-tab document, and let writes target a tab ([#1203](https://github.com/khuisman/mcp-gee-sweet/issues/1203))
- [ ] Docs: find and replace text (`replace_doc_text`), including multi-placeholder replacement ([#1204](https://github.com/khuisman/mcp-gee-sweet/issues/1204))
- [ ] Gmail: forward a message (`forward_message`) ([#1206](https://github.com/khuisman/mcp-gee-sweet/issues/1206))
- [ ] Calendar: respond to an invitation (`respond_to_event`) ([#1207](https://github.com/khuisman/mcp-gee-sweet/issues/1207))
- [ ] Calendar: conference data, auto-create a Google Meet link on events. Moved from Tier 3 (`v1.0`) 2026-10-24 ([#161](https://github.com/khuisman/mcp-gee-sweet/issues/161))

### Tier 3 — Advanced / occasionally needed _(target: [v1.0.0](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3Av1.0))_

**Sheets**
- [ ] `add_conditional_formatting` / `delete_conditional_formatting` ([#129](https://github.com/khuisman/mcp-gee-sweet/issues/129)) _(freema/mcp-gsheets)_
- [ ] `add_named_range` / `delete_named_range` ([#130](https://github.com/khuisman/mcp-gee-sweet/issues/130)) _(piotr-agier/google-drive-mcp)_
- [ ] `protect_sheet` / `protect_range` — lock a sheet or range against edits ([#128](https://github.com/khuisman/mcp-gee-sweet/issues/128)) _(piotr-agier/google-drive-mcp)_
- [ ] `set_basic_filter` / `clear_basic_filter` — toggle autofilter on a range ([#196](https://github.com/khuisman/mcp-gee-sweet/issues/196)) _(freema/mcp-gsheets)_
- [ ] `get_sheet_dimensions` — read column widths, row heights, frozen counts; triaged out of `backlog` 2026-09-11 ([#132](https://github.com/khuisman/mcp-gee-sweet/issues/132)) _(freema/mcp-gsheets)_
- [ ] `add_note` / `clear_note` — cell notes (distinct from comments); triaged out of `backlog` 2026-09-11 ([#131](https://github.com/khuisman/mcp-gee-sweet/issues/131)) _(freema/mcp-gsheets)_
- [ ] Developer metadata — key-value metadata attached to rows, columns, or ranges; triaged out of `backlog` 2026-09-11 ([#134](https://github.com/khuisman/mcp-gee-sweet/issues/134))

**Calendar**
- [ ] `quick_add` — create an event from a natural language string ([#159](https://github.com/khuisman/mcp-gee-sweet/issues/159))
- [ ] Event color coding — `colorId` on create/update ([#160](https://github.com/khuisman/mcp-gee-sweet/issues/160))
- [ ] Event attachments — link Drive files to events ([#162](https://github.com/khuisman/mcp-gee-sweet/issues/162))
- [ ] Reminders — per-event override reminders (email, popup, minutes before) ([#163](https://github.com/khuisman/mcp-gee-sweet/issues/163))
- [ ] Working location / OOO / Focus time events; triaged out of `backlog` 2026-09-11 ([#164](https://github.com/khuisman/mcp-gee-sweet/issues/164))

**Docs**
- [ ] `create_footnote` — footnote at a run index ([#149](https://github.com/khuisman/mcp-gee-sweet/issues/149))
- [ ] `create_table_of_contents` ([#153](https://github.com/khuisman/mcp-gee-sweet/issues/153))
- [ ] `insert_section_break` — section breaks for per-section column/margin layout ([#154](https://github.com/khuisman/mcp-gee-sweet/issues/154))
- [ ] Raw `batchUpdate` passthrough for Docs (escape hatch, mirroring Sheets' `batch_update`); triaged out of `backlog` 2026-09-11 ([#339](https://github.com/khuisman/mcp-gee-sweet/issues/339))
- [ ] Read/list/delete tools for named ranges (asymmetric with existing `create_named_range`); triaged out of `backlog` 2026-09-11 ([#340](https://github.com/khuisman/mcp-gee-sweet/issues/340))

**Drive**
- [x] File comments — list and add comments on Drive files — closed as superseded: `list_doc_comments`/`add_doc_comment` (#151, PR #324) already call the generic Drive `comments` resource and work on any file type; the rename to file-generic names is #663 and the rest of CRUD is #664, both v0.9.3 ([#142](https://github.com/khuisman/mcp-gee-sweet/issues/142))
- [ ] Watch notifications — webhook push on file changes ([#143](https://github.com/khuisman/mcp-gee-sweet/issues/143))
- [ ] Labels API — custom metadata labels on Drive files ([#144](https://github.com/khuisman/mcp-gee-sweet/issues/144))
- [ ] `empty_trash` — optional fan-out across all accessible Shared Drives in one call, instead of one call per drive; considered and deliberately deferred during #386's review ([#389](https://github.com/khuisman/mcp-gee-sweet/issues/389))

**Gmail**
- [ ] Service-account Gmail via domain-wide delegation (`with_subject()` in `_service_account_creds`) — Gmail is OAuth-only until then ([#794](https://github.com/khuisman/mcp-gee-sweet/issues/794))

### Tier 3.5 — Planned but bigger-lift _(target: [v1.1+](https://github.com/khuisman/mcp-gee-sweet/issues?q=is%3Aissue+label%3A%22v1.1%2B%22))_

Net-new capabilities substantial enough (new subsystem, external infra like webhooks) to warrant their own design pass rather than a single PR — later than Tier 3, still a real target rather than an indefinitely-parked wishlist item.

- [ ] Pivot tables — create and update pivot table specs via batchUpdate; triaged out of `backlog` 2026-09-11 ([#133](https://github.com/khuisman/mcp-gee-sweet/issues/133))
- [ ] Calendar watch notifications — webhook push on calendar or event changes; triaged out of `backlog` 2026-09-11 ([#165](https://github.com/khuisman/mcp-gee-sweet/issues/165))
- [ ] `get_doc_as_markdown`: parallelize doc fetch and comments fetch ([#595](https://github.com/khuisman/mcp-gee-sweet/issues/595))

### Tier 4 — Nice to have / niche _(no assigned version)_

**Sheets**
- [ ] Conditional formatting rules — add/get/delete _(a-bonus/google-docs-mcp)_
- [ ] Protected ranges — protect/unprotect a range _(a-bonus/google-docs-mcp)_
- [ ] Dropdown / data validation on a range _(a-bonus/google-docs-mcp)_
- [ ] Row grouping (outline/collapse) — group/ungroup rows _(a-bonus/google-docs-mcp)_
- [ ] Auto-resize columns/rows to fit content _(a-bonus/google-docs-mcp)_
- [ ] Write-side column widths / row heights — companion to the read-only `get_sheet_dimensions` above ([#132](https://github.com/khuisman/mcp-gee-sweet/issues/132)) _(a-bonus/google-docs-mcp)_
- [ ] Native Sheets "Tables" object support (create/list/get/delete/update a structured Table, distinct from a plain range) — a newer Sheets API feature we don't touch at all _(a-bonus/google-docs-mcp)_
- [ ] Copy formatting only, without values (paste-special-style) _(a-bonus/google-docs-mcp)_

**Docs**
- [ ] Multi-tab document support (list/add/rename tabs) — Google Docs' newer per-document tabs feature _(a-bonus/google-docs-mcp)_
- [ ] Smart chips — date chips, person chips, rich links; `list_smart_chips` to enumerate existing ones _(a-bonus/google-docs-mcp)_
- [ ] Section breaks and per-section page styling _(a-bonus/google-docs-mcp)_
- [ ] Page breaks _(a-bonus/google-docs-mcp)_
- [ ] Table structure discovery and cloning (read a table's row/column structure; clone an existing table) _(a-bonus/google-docs-mcp)_
- [ ] Finer-grained table styling — per-border, per-column-width, per-row-height table styling beyond what `style_doc_table_cells` currently exposes _(a-bonus/google-docs-mcp)_
- [ ] Footnote management _(piotr-agier/google-drive-mcp)_

**Infrastructure**
- [x] `notifications/progress` feedback for long-running transfer calls (`download_folder`, `sync_folder`) — no tool uses MCP progress reporting today, would establish a new pattern; split from #316 (PR #351) ([#319](https://github.com/khuisman/mcp-gee-sweet/issues/319))
- [ ] `kai_status.py`: report open code-scanning alerts on `develop`, and say in `kai.md` what Kai does with them. On deck, no version; the `kai.md` part needs Bob's prompt-QA ([#1304](https://github.com/khuisman/mcp-gee-sweet/issues/1304))

### Decisions Needed — blocking backlog _(no assigned version)_

All eleven Phase 1 QA decisions were settled 2026-10-18: #31, #37 and #40 were already done in code; #33, #34, #35, #36, #38 and #78 keep current behavior; #32 and #39 moved to _ankylosaurus_ as small fixes.

- [ ] Converted Markdown Doc keeps `.md` in its Drive name: keep it, drop it everywhere (sync and `skip_if_exists` then need another match), or drop it only for an explicit `name=`. Split from #1307's fix 2; Joy scopes; version follows the decision ([#1309](https://github.com/khuisman/mcp-gee-sweet/issues/1309))

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
- [ ] QA gaps targeted for v0.9 — disposition of v0.8.0 SKIP entries, done, triaged the rest below ([x] [#227](https://github.com/khuisman/mcp-gee-sweet/issues/227), PR #493); dedicated QA Google account + calendar + pollution root-cause fixes, consolidates #225/#226/#249 — deferred out of v0.9.0 (2026-09-02, paid-account cost not justified for the volume); revisit via alternate OAuth client configs; split 2026-10-04: multi-user testing stays here at v1.0, pollution cleanup moved to [#886](https://github.com/khuisman/mcp-gee-sweet/issues/886) (v0.9.3) ([#304](https://github.com/khuisman/mcp-gee-sweet/issues/304)); second Drive folder + shared drive fixtures, consolidates #44/#48 — done as a full fixture-set re-provision into the `mcp-gee-sweet-shared` Shared Drive (Workspace-org migration overtook the original scope); `TEST_FOLDER_2_ID` half retired, TC-D123 permanently skipped ([x] [#305](https://github.com/khuisman/mcp-gee-sweet/issues/305), PR #677); two Aziz-routed test-doc fixups surfaced by PR #677's fixture re-provisioning, both to be handled during Full Regression pass prep — TC-DOC80 can no longer trip the response cap post-#519, needs a per-case low-cap override ([#678](https://github.com/khuisman/mcp-gee-sweet/issues/678)); several `drive_files.md` cases assume My-Drive semantics now that fixtures live in a Shared Drive (TC-D58/D61/D03/D59/D27/D04/D175), and TC-D27 may expose a real `list_folders` Shared-Drive tool gap ([#680](https://github.com/khuisman/mcp-gee-sweet/issues/680)); domain/public sharing coverage — moved to v0.9.1 (2026-09-02) ([#49](https://github.com/khuisman/mcp-gee-sweet/issues/49)); local-filesystem coverage ([x] [#50](https://github.com/khuisman/mcp-gee-sweet/issues/50), PR #644); environment-constraint coverage — closed 2026-09-02 as duplicate, untangled into #305 (shared drives) / #49 (external + public sharing) / #304 (second account, deferred) / #673 (concurrent-session procedure) ([x] [#53](https://github.com/khuisman/mcp-gee-sweet/issues/53)); concurrent-session test procedure — 2 subagents + `mkdir` barrier against a main-checkout server, split from #53 — procedure + pre-approved-SKIP retirement via PR #675, `aziz.md` release-pass wiring via PR #674; live TC-I24/TC-I02/TC-R36 runs happen in the v0.9.0 Full Regression pass (tracked in `docs/qa/runs/v0.9.0.md`), not a standalone issue ([x] [#673](https://github.com/khuisman/mcp-gee-sweet/issues/673), PRs #674/#675); split `drive.md`/`docs.md` test files by submodule, do before #264/#224 to avoid a file-rename conflict ([x] [#233](https://github.com/khuisman/mcp-gee-sweet/issues/233), PR #582); Playwright tag consistency audit + formalize the required/spot-check/skip tiers, raised while fixing #248, sequenced after #233 ([x] [#264](https://github.com/khuisman/mcp-gee-sweet/issues/264), PR #592, #598); image fixtures for `insert_inline_image`, sequenced after #233 ([x] [#224](https://github.com/khuisman/mcp-gee-sweet/issues/224), PR #639); dedicated screenshots folder, independent of the rest ([x] [#231](https://github.com/khuisman/mcp-gee-sweet/issues/231), PR #583); `add_chart` test cases leave charts behind with no teardown, polluting the shared Sales fixture across every QA run — same pollution-cluster shape as #304/#305 ([x] [#322](https://github.com/khuisman/mcp-gee-sweet/issues/322), PR #633); plus 7 small unit-test-coverage gaps filed 2026-08-02/08, each self-contained/ad hoc pickup — [x] [#487](https://github.com/khuisman/mcp-gee-sweet/issues/487) (PR #559), [x] [#488](https://github.com/khuisman/mcp-gee-sweet/issues/488) (PR #563), [x] [#489](https://github.com/khuisman/mcp-gee-sweet/issues/489) (PR #569), [x] [#490](https://github.com/khuisman/mcp-gee-sweet/issues/490) (PR #572), [x] [#491](https://github.com/khuisman/mcp-gee-sweet/issues/491) (PR #575), [x] [#494](https://github.com/khuisman/mcp-gee-sweet/issues/494) (PR #577), [x] [#495](https://github.com/khuisman/mcp-gee-sweet/issues/495) (PR #634)
- See [GitHub Issues (label: qa)](https://github.com/khuisman/mcp-gee-sweet/issues?q=label%3Aqa) for open QA gaps and fixture issues

---

## Infrastructure / internal

- [x] Migrate cache persistence — replaced four `/tmp/*.json` files with a single SQLite DB (`/tmp/mcp_gee_sweet.db`, configurable via `CACHE_DB_PATH`); one table, four namespaces; WAL mode
- [x] Open PR to xing5 from `upstream-observability` branch (structured logging, per-tool timing, `cache_discovery=False`) — [PR #79](https://github.com/xing5/mcp-google-sheets/pull/79)
- [x] Fork repo and rename to `mcp-gee-sweet`; README credits xing5, freema, and piotr-agier
- [x] PyPI publish — v0.7.0 stable on PyPI; dev track publishes `0.7.0.devN` on every push to `develop`
- [x] Live QA system — fixture setup, per-release run files (`docs/qa/runs/vX.Y.Z.md`), Playwright OAuth automation ([#173](https://github.com/khuisman/mcp-gee-sweet/issues/173)) _(gate for v0.8.0)_ (done 2026-06-26)
- [ ] CLAUDE.md's html_parser invariant doesn't describe a list item's transparent `<p>` (from PR #1164). Bob, no version ([#1267](https://github.com/khuisman/mcp-gee-sweet/issues/1267))
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
