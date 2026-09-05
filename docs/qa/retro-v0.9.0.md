# QA Retro — v0.9.0 Full Regression

**Run date:** 2026-09-03 → 2026-09-05
**Auth:** OAuth (6 server prefixes) + Service Account (2 prefixes)
**Results:** [docs/qa/results/2026-09-04.md](results/2026-09-04.md)
**Run file:** [docs/qa/runs/v0.9.0.md](runs/v0.9.0.md)
**Scope:** First pass using every `mcp-gee-sweet-*` server slot (not just borrowed Sky/Kit) — 750 TCs across 14 files, 674 exercised, 44 real Playwright screenshots, a full concurrency-barrier run (TC-I24/TC-I02)

---

## What went well

**8-way full-slot sharding cut wall-clock time substantially.** Using all 8 available server prefixes (6 OAuth: `ash`/`sky`/`jay`/`kit`/`kai-oauth`/`oauth`; 2 SA: `kai-sa`/`sa`) instead of the previous 2-3-way borrowed-Sky/Kit model let every domain run truly in parallel. Codified in `aziz.md` via PR #685, per direct user instruction after this exact rule had been given verbally to multiple prior sessions without ever landing in a file.

**A compile script beat manual per-TC editing for writing 674 inline Results.** Parsing each shard's own structured `TC | Outcome | Observation` table into one JSON mapping, then bulk-inserting `**Result (date)**` blocks via a script, was far faster and more consistent than hand-editing 14 files one TC at a time — and the script's own bug (see below) was caught cheaply via `git diff --stat`/spot-checks *before* committing, exactly because the change was mechanical and reviewable as a diff rather than 674 individual edits.

**Two real, narrow, one-session-fixable bugs found and shipped same-day.** BUG-SS (`share_spreadsheet` missing `supportsAllDrives=True`) and BUG-CACHE (folder-listing cache key omits `max_results`) were both confirmed live, filed, routed to a Dev lane, fixed, and live-re-verified against the real fixture within the same session the pass ran — no multi-day gap between "found" and "shipped."

**The SA-fixture-gap + targeted-OAuth-re-run pattern gave full coverage without redoing a whole domain.** When the Calendar shard discovered the service account wasn't subscribed to the real fixture calendar, running the full 77-TC suite against SA-owned substitutes first (valid tool-behavior coverage) and then a small targeted re-run of just the fixture-identity-sensitive TCs against the real calendar was much cheaper than re-running the whole domain twice.

**The concurrency-barrier procedure (TC-I24/TC-I02) worked cleanly on first real use** — the `mkdir`-barrier mechanism itself needed no debugging; the only errors hit were subagents' own tool-call parameter typos (self-corrected), not the barrier logic.

---

## What didn't go well

### 1. Playwright authentication was never verified before kickoff

All 8 shards independently hit an unauthenticated-browser sign-in redirect within their first few `**Playwright: required**` TCs, concluded Playwright was unusable, and silently degraded to API-only verification for their entire remaining run. Nobody — including Aziz — checked *before spawning* whether Playwright could actually reach a Google page, only whether the MCP was connected. Discovered only because the user asked mid-pass whether the shards had even retried it after authenticating. **Fixed:** PR #686 — `aziz.md` now has a dedicated step to verify Playwright with a real navigate, once, centrally, before any shard spawns.

### 2. Agent-ID mixup when correcting two similar concurrently-running subagents

After the user authenticated Playwright mid-pass, corrections were sent to the two still-running shards (Sheets retry, Docs-content retry) — but the two agent IDs got swapped, so each shard received a correction naming the *other* shard's file. The Sheets shard correctly treated the mismatched instruction as out-of-scope/suspicious and ignored it (good defensive behavior, but it meant the real fix never reached it — a second, larger re-verification pass was needed later to close the gap). The Docs-content shard got a wrong-filename message but adapted the general instruction to its own actual file. **Lesson:** when sending `SendMessage` corrections to multiple similar in-flight subagents, don't trust recall of "which Agent call came first" — re-verify the agentId-to-role mapping (e.g. via `ListAgents`, matching against each agent's own task description) immediately before sending, every time.

### 3. Cross-shard fixture interference wasn't designed out of the shard plan

The Sheets shard was the sole writer of `{SPREADSHEET_ID}`, but the Drive-transfer shard was also given it as a "read-only if referenced" fixture for CSV-export comparison TCs (TC-D86/D104). The Sheets shard's writes were caught mid-mutation by a concurrent export read, producing a spurious-looking discrepancy that needed a dedicated re-check to resolve (harmless in the end, but cost a diagnostic detour). **Lesson:** a shard that's the sole writer of a shared fixture should be treated as making that fixture *unsafe to read* for comparison purposes by any other concurrent shard — either sequence the reader after the writer, or give the reader its own throwaway copy, rather than assuming "read-only" is safe against a fixture something else is actively mutating.

### 4. A dangerous staged git revert appeared mid-session, caught only by habit

After several branch switches in this session (four different feature branches plus `develop`, crossing a same-branch-name conflict with the main checkout), the Aziz worktree's git *index* ended up with staged changes that would have silently reverted the just-merged BUG-CACHE fix (removing `max_results` from the cache key again) had they been committed without inspection. Caught only because `git status`/`git diff --cached` were checked before committing, per existing practice — not because anything flagged it proactively. Root cause not fully diagnosed (likely worktree/branch-name interaction from the session's own many switches); no reproduction attempted since the fix (a clean `git reset --hard origin/develop`) was immediate and sufficient. **Lesson:** after a long session with several branch switches, treat "clean status right after a reset" as a snapshot, not a guarantee — re-check status/diff again immediately before every commit, especially on a shared branch like `develop`, not just once per session.

### 5. Test-design cross-contamination from overlapping scratch ranges

TC-S39/S40 (merge/unmerge) and TC-S93/S94 (data validation) were re-verified by the same subagent against overlapping ranges on the `Empty` scratch sheet. Google Sheets' own merge/validation-carryover behavior overwrote one range's dropdown rule with a checkbox rule from the merge — not a tool defect (confirmed via `get_data_validation`), but it looked like one until investigated. **Lesson:** independent TCs sharing one scratch sheet within a single subagent run should use disjoint ranges, not overlapping ones.

### 6. OAuth token refresh failing for fresh processes, discovered mid-pass

The main-checkout `token.json`'s refresh token started failing (`invalid_grant`) for any *new* script/process partway through the pass, while already-running MCP server processes (holding an already-refreshed in-memory token) were unaffected. This blocked one live re-verification (TC-DOC159), which was instead disposed via a source-diff argument. Not caused by the pass, but discovered during it, and the workaround (re-run `scripts/oauth_setup.py`) wasn't applied mid-session since the already-running servers were sufficient for everything else.

---

## Action items

### Process (aziz.md / run.md)
- [x] Playwright-auth pre-flight verification, done once centrally before spawning shards (PR #686)
- [x] All-slots server access codified, not just borrowed Sky/Kit (PR #685)
- [ ] Add an explicit `SendMessage`-correction step to `aziz.md`: before messaging a live subagent, re-verify its agentId against its own task/description (e.g. via `ListAgents`), every time — don't rely on call-order memory
- [ ] Add a shard-planning note to `aziz.md`/`run.md`: a shard that's the sole writer of a shared fixture makes that fixture unsafe for a *different* shard's read-for-comparison use at the same time — sequence or isolate, don't assume "read-only" is safe
- [ ] Add a scratch-range note to `run.md`: independent TCs sharing one scratch sheet within a run should use disjoint ranges

### Follow-up not yet a ticket
- [ ] Investigate why the Aziz worktree's git index picked up a stale/reverting staged state mid-session after multiple branch switches — no repro attempted yet, only worked around
- [ ] Consider whether OAuth token refresh reliability needs a documented re-auth cadence, given it silently failed for fresh processes mid-session while running servers were unaffected

### For next retro
- Track: did the SendMessage agentId-verification step actually prevent a repeat of the mixup next time multiple similar subagents are in flight?
- Track: did sequencing/isolating shared-fixture shards eliminate cross-shard interference next Full Regression pass?
