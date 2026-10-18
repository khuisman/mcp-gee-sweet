# PASS-result audit — 2026-10-17 (#1044)

Every `**Result**` recorded as PASS across `docs/qa/tests/*.md` was read in full: 2,087 entries in 15 suites. The question for each was whether it describes a defect, or claims a check that didn't run. Keyword scans were used only to cross-check the reading.

Corrections are made in place: the Result header's verdict is changed and a `**Corrected (2026-10-17, #1044 audit):**` line is appended to that Result, so the original text stays readable.

## Summary

| Outcome | Results | What changed |
|---|---:|---|
| PASS that describes a product defect | 15 | header → ❌ FAIL, linked to an open issue (or to the fix, where one landed) |
| PASS whose defect was resolved later, but the record didn't say so | 3 | correction note only |
| PASS although a required check didn't run | 47 | header → ⚠️ PARTIAL, naming the check |
| Genuine PASS | the rest | none |

## PASS results that describe a defect → FAIL

| Case | Result | Defect | Tracking |
|---|---|---|---|
| TC-DOC105 | 2026-09-04 | 2/3-space nested Markdown lists flatten; ordered sub-items show as literal `1.`/`2.` | #1071 (#334 closed) |
| TC-DOC104 | 2026-07-27 r2, 2026-09-04 | whitespace between `</li>` and `<ul>` in HTML leaves stray empty bullets that consume numbers ("Top ordered 2" shows "3.") | #1074 |
| TC-DOC190 | 2026-09-08 | same stray bullets, "out of scope" | #1074 |
| TC-DOC102 | 2026-09-04 | table-cell images dropped silently; the Checks require them | #1073 |
| TC-DOC103 | 2026-09-04 | same | #1073 |
| TC-DOC106 | 2026-09-04 | bare `-` list marker renders as literal text; #692 closed it as a limitation | #1075 |
| TC-DOC109 | 2026-07-17, 2026-09-04 | `create_bookmark` makes no bookmark Docs lists | #1076 |
| TC-DOC173 | 2026-08-15, 2026-09-04 | strikethrough "passed" on literal `~~` text: the Markdown write path has no strikethrough | #1077 |
| TC-DOC178 | 2026-08-15 | "cosmetic nit (not filed)": nested-table placeholder runs into the cell text | #1078 |
| TC-D38 | 2026-09-04 | folder cache served a truncated list | fixed by PR #697 (#688) |
| TC-D226 | 2026-07-25 | the check expected `skipped`, the run got `conflicts` | fixed later in the same PR (TC-D228) |
| TC-S103 | 2026-07-28 r1 | raw `KeyError`/`TypeError`/`HttpError` leaks; round sent back | fixed in round 2 (`5648a91`) |

## Resolved later, record didn't say so → note only

| Case | Result | Note added |
|---|---|---|
| TC-DOC155 | 2026-08-06 | the original FAIL was the 2-space nesting defect, not a test-case bug (#1071) |
| TC-S133 | 2026-10-11 r2 | BLANK/NOT_BLANK reaching the API: removed from the enum in round 3, verified by TC-S134 |
| TC-D265 | 2026-09-24 | long `.md` names (#805/#806, closed): fix is in `_sync_level` via `_convert_properties` with unit tests; live re-check added as TC-MD303 |

## PASS although a required check didn't run → PARTIAL

All are `**Playwright: required**` cases (or a case's own listed sub-check) whose result says the check was skipped, replaced, or never exercised:

- **2026-09-04 (v0.9.0 pass, browser not signed in):** TC-DOC12, TC-DOC68–71, TC-DOC74, TC-DOC91, TC-DOC92, TC-DOC139, TC-DOC146, TC-DOC159 (not run at all; carried forward), TC-CAL20, TC-S63, TC-S93, TC-W33, TC-D137, TC-D152–154 (vacuous: no shared files), TC-I20.
- **2026-10-17 (v0.9.2 pass):** TC-CAL20, CAL21, CAL24–26, CAL28, CAL36–40: the fixture-owner browser can't see SA-owned calendars. **These TCs have no valid visual verification at all right now**; the fix is a calendar the browser account can see (#886). TC-R34: the 200-query cap check wasn't run.
- **Earlier PR rounds:** TC-DOC32, DOC33, DOC38, DOC42, DOC47 (June: bold/monospace "visual only" or "confirmed by unit tests"), TC-DOC37 and DOC82 (2026-08-19 regression rounds, structural only), TC-DOC139 (2026-07-27), TC-DOC143 (2026-07-28), TC-DOC152 (2026-08-02, 2026-10-04), TC-DOC202 (2026-10-04, log check not run), TC-S93 (2026-07-17), TC-I27 and TC-I28 (2026-08-04/05: only the full-access check ran).

Not corrected, because `run.md` names the substitute check: TC-S73, TC-S79 (row/column `pixelSize` from grid data), TC-S85–S87 (borders from grid data), TC-D136 (sharing confirmed via `list_permissions`).

## The #1044 table, row by row

| Case | Finding |
|---|---|
| TC-DOC105 | Corrected to FAIL; #1071. `docs/known-limitations.md` no longer points at the closed #334. |
| TC-DOC104, TC-DOC190 | Corrected to FAIL; #1074. |
| TC-DOC102, TC-DOC153 | TC-DOC102 (and DOC103) corrected to FAIL. TC-DOC153 stays PASS: its stated purpose is that the gap fails without a hang, and that held. The gap itself is now a known limitation tied to #1073. |
| TC-DOC109 | Corrected to FAIL; #1076; known-limitations entry added. |
| TC-DOC32, DOC42, DOC47 | The June results are now PARTIAL. The 2026-09-04 results do cite Playwright screenshots (DOC32 bold, DOC42 and DOC47 Courier New), so these were confirmed on screen once. TC-MD103/104/113 check them again on every entry point. |
| TC-D265 | Fix verified in code and unit tests (see above); live re-check is TC-MD303. |
| TC-S103 | Fixed in PR #452 round 2 and re-confirmed 2026-09-04. The round-1 result is now FAIL. No new issue needed. |
| TC-S133 | The outcome was recorded under TC-S134 (round 3 removed BLANK/NOT_BLANK from the enum). Note added. No new issue needed. |

## Judgment call: PASS with defects found by out-of-scope probes

Many PR-round results read "PASS (checks as written); sent back on probes" (e.g. TC-DOC203, DOC207, DOC209, DOC216, DOC217, DOC218, DOC222, DOC225, D279, D284, D285, D287, GM47, I43). Each says plainly that the case's own checks passed, names the probe defects, and a later round of the same PR records the fix. These stay PASS. The QA rule added with this audit (see #1044) makes that the required form: an out-of-scope defect must be sent back on the PR or linked to an open issue in the same Result.

## Not corrected, for a decision

- **TC-D17, TC-D41:** the Checks themselves declare "Known limitation: no `nextPageToken` continuation; results silently truncated at `max_results`". That's honest, but the limitation has no open issue and isn't in `docs/known-limitations.md`.
- **TC-D89 (2026-09-04):** `upload_file(source_format='markdown')` uploads `text/html` even with `convert_to_doc=false`, which the result calls "by design per docstring, but a footgun". That's a product decision, not a defect.
- **v0.9.2's open findings** (`docs/qa/runs/v0.9.2.md`, "Bugs found"): one is still unfiled, `get_doc_as_markdown` misreading bullets in Docs from Drive's HTML import ("repeat before filing"). TC-MD's EP-8 renders exercise that import path at scale.
