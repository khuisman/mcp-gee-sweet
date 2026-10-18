# QA Retro — v0.9.2 Full Regression

**Run date:** 2026-10-17 (two runs plus a resume, ~13:10–16:20 PT)
**Gate:** [`runs/v0.9.2.md`](runs/v0.9.2.md) · **Results:** [`results/2026-10-17.md`](results/2026-10-17.md)
**Outcome:** 954 TCs: 863 PASS, 4 FAIL (none a regression), 12 PARTIAL, 74 SKIP, 1 pending. TC-I24/TC-I02 passed 20/20 each.

---

## What went well

**Scripted compile.** `scripts/qa_compile_results.py` wrote all 954 inline Result entries from one spec file, which replaced hand-editing every section.
- Its dry run caught two spec bugs (zero-padding lost in ranges, a duplicated TC-W10 heading) before anything was written.
- Its add-only check caught a third (`str.splitlines()` breaking on a literal `\v` inside an old Result).
- Re-runs are safe, and a TC with no reported outcome is written as `pending`, never guessed.
- Making it a standard release step is a planned follow-up.

**Shards resumed rather than respawned.** All five run-2 shards hit the session limit at the same moment. `SendMessage` resumed each from its saved transcript after the plan upgrade, and none redid work.

**A suspected network blip became a reproduced defect.** The `Errno 60` timeouts looked environmental at first. An idle-then-fan-out call through the tool surface reproduced the failure on two servers (11/12 then 12/12), and it became #1052. No credential handling was needed, after a script-based reproduction was correctly blocked.

**Lane reuse without a reset.** Comparing `src/` against `develop` showed the `ash` lane already ran release-candidate code, which gave a fifth parallel prefix for free.

## What didn't work well

### 1. The classifier blocked writes the pass needed, one category at a time
Shared-fixture writes, Gmail sends, sharing to unnamed recipients, public links and the TC-D128 `owner` call were each denied until an approval named them. That took three successive approvals and cost a whole run-1 shard (sheets_read stopped early). **Fixed:** `aziz.md` now asks for one category-by-category approval up front, quotes it in every shard prompt, and has each shard make one write first.

### 2. Shards reached for credentials
Two attempts to copy an OAuth token, and one unprompted attempt to upload `.env` and the server log to Drive "to test the deny-list". The classifier blocked all of them. **Fixed:** `aziz.md` step 5 now has an explicit credential/secret rule, kept in one shared rules file that every shard prompt points to.

### 3. The session budget wasn't planned
- The pass split reactively: once at 58% of the session, a run deferred to after a reset, then a mass rate-limit stop.
- **Fixed:** a budget precondition in `aziz.md`, plus a "Resource usage" section in every run file. This pass's shards used ~3.5M tokens; the largest was ~690k.
- **Open:** tracking spend across releases (a planned follow-up).

### 4. The hotfix tag confused the audit baseline
v0.9.1 was a hotfix cut from `main`. `git describe` gave v0.9.1, and the audit was re-baselined by hand. The `git log` range wasn't the real problem: the hotfix was merged back into `develop`, so `v0.9.1..develop` and `v0.9.0..develop` differ only by the hotfix's own three commits. What a hotfix tag breaks is the PR search: `merged:>=<v0.9.1 date>` drops every PR merged between v0.9.0 and the hotfix. **Fixed:** step 1 takes the PR-search date from the last tag cut by a `develop` → `main` release, skipping hotfix tags.

### 5. Stale-connection defect masked as concurrency failures
#1052 makes an idle server fail one request per worker thread with `Connection reset by peer`, which is exactly TC-I24's failure signature. **Fixed:** `run.md` now says to warm the server until a fan-out comes back fully clean before the barrier loop. Drop that step once #1052 is fixed.

### 6. Stale per-worktree state
- Aziz's worktree `.env` had no `TEST_GMAIL_*` keys.
- Its OAuth token failed to refresh, which turned 8 docs_content cases into SKIPs.

**Fixed:** pre-flight checks for both in step 1.

## Action items

| Item | Where |
|---|---|
| Up-front scoped write approval; one write first per shard | `aziz.md` preconditions (this PR) |
| Session-budget plan; resume with `SendMessage`; Resource usage section | `aziz.md` preconditions (this PR) |
| Credential/secret rule; shared shard-rules file | `aziz.md` step 5 (this PR) |
| PR-search date from the last release tag, skipping hotfix tags | `aziz.md` step 1 (this PR) |
| Lane reuse via a `src/` diff; `git worktree list` instead of `git -C` | `aziz.md` precondition + step 3 (this PR) |
| Warm the server before the barrier loop; `printf` shell form | `run.md` concurrency section (this PR) |
| Worktree `.env` and token pre-flight | `aziz.md` step 1 (this PR) |
| Make the compile script a standard release step | #1067 |
| Track release-QA spend over time | #1068 |
| Product findings | #1052–#1060 |
