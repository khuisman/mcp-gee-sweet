# Markdown rendering baseline, Phase 2 — 2026-10-18 (#1044)

The second live run of [`docs/qa/tests/docs_markdown.md`](../tests/docs_markdown.md): Phase 2, the 17 syntax fixtures (TC-MD101–117) and the 4 matrices (TC-MD201–204), 467 cases. Phase 1 is in [`2026-10-18-markdown.md`](2026-10-18-markdown.md). Document boundaries (TC-MD301–303) and document state (TC-MD401–404) are still to run.

**Result: 1,522 of 3,758 case × entry-point cells pass (40%); no TC passes.** Every case went through all 8 entry points twice. Across 498 screenshot pages, 478 were identical between the runs, 9 differed only by a spell-check squiggle, and 11 (EP-8 of TC-MD108 and TC-MD202) changed font, which fails Rule 4.

## Setup

- **Code under test:** `develop` at `504a5b2b`, the same server processes as Phase 1 (stdio servers load the package once at start). Two fixes merged to `develop` during the run and are **not** reflected here: #1089 (#1056, blockquote indent) and #1088 (#1057, soft-break export). Every "quote has a border but no indent" cell below predates #1089.
- **Servers and shards** as in Phase 1: A `kai-oauth` (TC-MD201, 101, 102, 113, 114, 115), B `oauth` (TC-MD202, 103, 111, 112, 116), C `kai-sa` (TC-MD203, 109, 110, 117), D `sa` (TC-MD204, 104, 105, 106, 107, 108). Lanes A and B were mid-ticket, so lane servers weren't used.
- **Approvals:** the Phase 1 write categories, plus "go ahead with phase 2, shares approved" for TC-MD112's temporary "anyone with the link" shares. Every image result reported `shared: false` afterwards (revoked).
- **Folders:** `QA-MD-2026-10-18-p2-run1` and `-p2-run2` under `TEST_FOLDER_ID`, one subfolder per shard with `ep5`/`ep6`/`ep7` children. Trashed after recording, with the image uploads TC-MD112 made outside them.
- **TC-MD112** used `md-images.local.md` (ignored) with the placeholders substituted; the Drive copy of `qa-fixture-pixel.png` sat in the run 1 folder.
- **TC-MD111** also ran EP-1 to EP-4 with `autolink_urls=False`.

## Method

Phase 2's fixtures hold many cases each, and the matrices run 8–11 pages, so the per-case screenshot of Phase 1 was replaced:

- **Deterministic page screenshots.** One `browser_run_code_unsafe` call per Doc set a 1400×2200 viewport, then captured page *k* at `.kix-appview-editor` scrollTop = (*k*−1)×1900 until the end of the document (`docs/qa/screenshots/md/p2-run<N>/EP-<n>/<TC>-<k>.jpeg`, gitignored). Each page shows several cases; together they cover the whole document.
- **By eye for one entry point per engine, pixel identity for its siblings.** Shards judged EP-1, EP-5 and EP-8 case by case. EP-2/3/4 were pixel-compared with EP-1 and EP-6/7 with EP-5, page by page (grayscale, threshold 40, Docs chrome, caret column and outline pane masked). Every sibling was pixel-identical except three spell-check squiggles (judged by eye: same content). EP-1 to EP-4 rendered identically to each other in every TC, and so did EP-5 to EP-7.
- **Run 2** re-rendered everything into a fresh folder with the same script and was pixel-compared page by page against Run 1, by each shard and again centrally. Every Run 2 file is newer than its Run 1 pair.
- **One judging gap closed:** in Run 1 shard A didn't read EP-5 pages 3, 4, 7, 8, 10, 11 and EP-8 pages 5, 6, 8 of TC-MD201 frame by frame. Run 2's shard A judged those pages case by case; no verdict changed (none of Run 1's ✅ cells were on them).

## Results by TC

Cells count each case once per entry point: ours = EP-1 to EP-4 (×4), Drive import = EP-5 to EP-7 (×3), EP-8 (×1); TC-MD111's `autolink_urls=False` variant adds ×4. Columns give cases passing per engine.

| TC | Fixture | Cases | Ours ✅ | Drive ✅ | EP-8 ✅ | Cells pass | Failures |
|---|---|---:|---:|---:|---:|---:|---|
| TC-MD101 | headings | 8 | 6 | 7 | 5 | 50/64 | #1116, #1101, #1102 |
| TC-MD102 | emphasis | 8 | 5 | 8 | 6 | 50/64 | #1116, #1077, #1093, #1102 |
| TC-MD103 | inline code | 6 | 6 | 0 | 0 | 24/48 | #1101, #1102 |
| TC-MD104 | code blocks | 10 | 10 | 0 | 0 | 40/80 | #1101, #1102 |
| TC-MD105 | list markers | 8 | 4 | 4 | 3 | 31/64 | #1115, #1116, #1118, #1101, #1102 |
| TC-MD106 | nesting | 16 | 4 | 0 | 2 | 18/128 | #1071, #1072, #1101, #1102 |
| TC-MD107 | blocks in items | 9 | 1 | 3 | 4 | 17/72 | #1115, #1094, #1101, #1102 |
| TC-MD108 | list boundaries | 9 | 3 | 2 | 3 | 21/72 | #1116, #1093, #1094, #1118, #1101, #1102 ⚠️ND |
| TC-MD109 | task lists | 6 | 5 | 2 | 1 | 27/48 | #1071, #1101, #1102 |
| TC-MD110 | blockquotes | 9 | 0 | 0 | 0 | 0/72 | #1056, #1093, #1098, #1101, #1102 |
| TC-MD111 | links | 12 | 9 (+11 noauto) | 10 | 7 | 117/144 | #1116, #1120, #1101, #1102 |
| TC-MD112 | images | 9 | 7 | 5 | 5 | 48/70 | #1121, #1073, #1101, #1102 |
| TC-MD113 | tables | 12 | 6 | 10 | 8 | 62/96 | #1095, #1116, #1077, #1098, #1101, #1102 |
| TC-MD114 | breaks and rules | 9 | 2 | 8 | 8 | 40/72 | #1093, #1117, #1116, #1096, #1101, #1102 |
| TC-MD115 | escapes | 7 | 6 | 7 | 5 | 50/56 | #1116, #1102 |
| TC-MD116 | inline HTML | 7 | 3 | 4 | 6 | 30/56 | #1077, #1119, #1117, #1101, #1102 |
| TC-MD117 | unicode | 7 | 5 | 3 | 3 | 32/56 | #1101, #1102; UN-04/UN-05 PARTIAL (fixture) |
| TC-MD201 | containment | 80 | 12 | 6 | 9 | 75/640 | #1115, #1094, #1072, #1056, #1122, #1101, #1102 |
| TC-MD202 | adjacency, no blank | 100 | 33 | 47 | 28 | 301/800 | #1116, #1093, #1096, #1056, #1097, #1073, #1101, #1102 ⚠️ND |
| TC-MD203 | adjacency, blank | 100 | 52 | 49 | 45 | 400/800 | #1115, #1056, #1096, #1097, #1098, #1101, #1102 |
| TC-MD204 | inline matrix | 32 | 12 | 12 | 5 | 89/256 | #1077, #1116, #1056, #1122, #1101, #1102 |
| **Total** | | **467** | | | | **1,522/3,758** | |

⚠️ND: EP-8's rendering changed between runs. IM-05 on EP-1/EP-2 is N/A per the plan (no file to resolve against) and is excluded from TC-MD112's total.

Per-case verdicts with what was observed are in the shard reports; the per-case grid isn't repeated here because every failing case maps to an issue above.

## Issues

New from Phase 2:

| Issue | Defect | Engine |
|---|---|---|
| #1115 | a loose list (blank lines between items) loses its bullets and numbers: `<p>` inside `<li>` replaces the item | ours |
| #1116 | switch the Markdown parser to CommonMark/GFM (decided): Python-Markdown can't start a block without a blank line, rejects `1)`, backslash breaks, `#hashtag`/`#######`, most escapes, bold inside italic, `www.`/email autolinks, `\|` in table code | ours, EP-8 |
| #1117 | a hard line break becomes a paragraph break (`<br>` → `\n`) | ours |
| #1118 | an ordered list's start number is ignored (no Docs API request sets it) | ours, EP-8 |
| #1119 | `<sub>`, `<sup>`, `<mark>` have no effect | ours |
| #1120 | a relative link becomes `http://./guide.md` | all |
| #1121 | a relative image path in a `.md` file isn't resolved against the file's directory | EP-3, EP-4 |
| #1122 | tables, rules and nested quotes inside a blockquote render outside it | ours |

Phase 2 evidence was added to #1071, #1072, #1073, #1077, #1093, #1094, #1096, #1097, #1098, #1101 and #1102.

## Nondeterminism (EP-8)

EP-8's fenced code font flipped again: TC-MD202 (every fenced block, all 9 pages) and TC-MD108 LX-09 were Arial in Run 1 and monospace in Run 2. Shard B re-opened the Run 1 TC-MD202 Doc afterwards and it still showed Arial, so the difference is stored in the Docs, not a screenshot timing artifact. The server process was the same in both runs, so the variance is Drive's HTML import (#1102; Phase 1 saw the same on 3 fixtures). The other 19 fixtures rendered identically through EP-8.

## Test-plan fix in this PR

`md-unicode.md` (TC-MD117) had a precomposed `é` where UN-04 needs `e` + U+0301, and plain spaces where UN-05 needs U+00A0 and U+2009, so neither case could test what it says. Fixed here; UN-04 and UN-05 are PARTIAL in this baseline and run properly next time.

## Findings that weren't filed

- **Pagination:** a short table split across a page break although the page had room (TC-MD203 AB-080), images pushed to the next page (AB-069), and BQ-09 starting a second page in both our engine and Drive's. Likely keep-with-next behaviour; not filed until it's shown to be ours.
- **Images uploaded outside the target folder:** `write_doc_content` and `update_doc_from_file` upload a local image to the server's default folder, since those tools take no folder argument. Expected, but each call leaves an image file behind after the share is revoked.
- **Drive's task items** render as native Docs checklists, not `● ☐` text; equivalent on screen, recorded under #1101.

## Process notes

- **Lock incidents (Run 1):** shard A acquired the Playwright lock in a background command and refreshed it late; another shard's stale recovery took it, and one of shard A's captures landed on another shard's Doc. Shard A discarded it and re-took it; the other shard confirmed every capture's Doc ID. Shard B also used stale recovery once on a 122-second-old lock. Run 2's rules required a foreground acquire, a keepalive, and 60 more seconds without an mtime change before stale recovery; no incidents. Lock waits reached 8 minutes with four shards and multi-page matrix Docs: the shared browser is the bottleneck of this suite.
- **Playwright's `filename` option** only reads scripts under the worktree, so shards passed the screenshot script inline or wrote it to the ignored `.playwright-mcp/`.
- No #1052 connection resets and no classifier denials in either run.

## Resource usage

| Run | Shard | Prefix | Tokens | Tool uses | Wall time |
|---|---|---|---|---|---|
| 1 | A | `kai-oauth` | 446,338 | 257 | ~73 min |
| 1 | B | `oauth` | 477,641 | 300 | ~72 min |
| 1 | C | `kai-sa` | 401,165 | 185 | ~71 min |
| 1 | D | `sa` | 414,482 | 241 | ~72 min |
| 2 | A | `kai-oauth` | 335,462 | 260 | ~53 min |
| 2 | B | `oauth` | 306,504 | 294 | ~66 min |
| 2 | C | `kai-sa` | 239,678 | 138 | ~41 min |
| 2 | D | `sa` | 268,986 | 194 | ~57 min |
| — | Aziz (setup, probes, compare, compile, filing) | — | _not measured per step_ | | |

Total across shards: about 2.89M tokens (Phase 1: about 2.66M).

## Next

TC-MD301–303 (document boundaries) and TC-MD401–404 (document state), on the user's go-ahead. After the fixes land, re-run Phase 1 and Phase 2 under the new parser (#1116) and engine choice (#1101).
