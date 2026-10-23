# Decision: Impact × Reach Triage and a Follow-Up Chain Stop Rule

**Date:** 2026-10-13
**Snapshot commit:** branch `develop`
**Issue:** #1024. Thresholds approved by the maintainer as written on 2026-10-13.

## Background

v0.9.2 collected 178 issues. A one-pass hand classification of their text by impact × reach (reach is estimated; there's no usage telemetry yet, see #646) found that about 15 changed behavior a typical user would hit or be badly hurt by, and about 15 more were real but narrow. Most of the rest were rare-input defects, error-message polish, internal hygiene, tests, or team process.

| Impact ↓ / Reach → | Common | Narrow | Rare / latent |
|---|---|---|---|
| Severe (data loss, exposure, hang, unusable) | 4 | 6 | 5 |
| Silently wrong output | 5 | 15 | 8 |
| Loud failure / message quality | 1 | 10 | 7 |

Plus 42 hygiene, 24 tests/QA, 19 process/CI, 15 features, 7 docs, and 10 bundle tickets.

The high-yield tickets clustered at seams: auth or install (#811, #833, #872), the new Gmail domain (#790–#793), a non-default deployment shape such as a service account or a Shared Drive (#689, #989), and a dependency upgrade (#872). Almost none came from repeated review of parsing or formatting code.

The long tail came from two places the existing rules didn't cover:

1. **Follow-up chains.** One real defect, then each fix's review files the next, smaller edge case: #690 → #724 → #836 → #874 → #887 → #990 → #1012 (7 tickets over 5 weeks); #439 → #713 → #714 → #715 → #727; #747 → #757 → #926 → #954 → #955; #936 → #938 → #951 → #969 → #984 → #977. Every follow-up cleared a `qa.md` step 3 bar as written. Nothing asked whether an area had had enough.
2. **Paths other than `from-review`.** `kai.md`'s in-flight label rule (#995) covered only `from-review` tickets. The 2026-09-11 backlog triage moved "everything fixing/hardening/testing already-shipped functionality" into this release in one step, which is where most of the hygiene tickets came from.

## Decisions

1. **One rubric on every path into a version.** `kai.md` "Version labels" places a defect or hygiene ticket by its impact × reach cell, whether it arrives through backlog triage, `/retro`, a Dev follow-up, or a review finding. It replaces the #995 two-condition rule: condition (a) survives as "a regression since the last stable tag", and condition (b), an observed failure, now lifts only a `wrong/narrow` ticket into the in-flight release. Features, docs, test/QA, and process tickets aren't placed by it.
2. **Hygiene never gets a release label of its own.** It's folded into a ticket that already touches the file, or into a timeboxed bundle no release waits on.
3. **Chain stop rule.** After a root defect's second follow-up in its function family, later tickets in that family go to the next version unless severe or observed. The alternative is declaring the area done and recording its residual edges in `docs/known-limitations.md` (#692's precedent). `qa.md` step 3 and `dev.md` step 6 make the filer state the chain position so Kai can apply it.
4. **Seam questions.** `qa.md` step 4 asks four seam questions each pass (install/auth, new domain or tool, service account and Shared Drive, dependency move) and records the answers in the round's comment. `dev.md` step 2 asks the Dev the same questions before the PR.
5. **Measured.** `decision-review-finding-ticket-bar.md` decision 11 extends its 2026-10-18 checkpoint to count `from-review` tickets by cell.
6. **Data exposure means across a trust boundary** (maintainer, 2026-10-22, PR #1159): to another OS user, another tenant, or a network peer. Mixing the data of two identities the same person controls is `wrong`, not `severe`.

## Prompt-QA notes (Bob, 2026-10-13)

Two gaps in the approved text were filled in the role files and flagged for the maintainer on the PR rather than decided silently:

- The approved rubric doesn't place `loud/common`. `kai.md` sends it to the user unless it breaks install, auth, or first run.
- "Narrow" reach names deployment shape (service account, Shared Drive, SSE) as an example. The issue cites those as seams, not as a reach class, so this is an interpretation.
