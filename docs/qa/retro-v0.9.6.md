# QA Retro — v0.9.6 (ornithomimus) Full Regression

**Run date:** 2026-11-07/08 (Run 1 00:15–00:40 and 09:45–10:30, Run 2 10:45–14:30 and 19:30–20:30, Run 3 20:45–21:40 PT)
**Gate:** [`runs/v0.9.6.md`](runs/v0.9.6.md) · **Results:** [`results/2026-11-08.md`](results/2026-11-08.md), [`results/2026-11-08-markdown.md`](results/2026-11-08-markdown.md) (on PR #1431 until it merges)
**Outcome:** 1,056 results: 967 PASS, 20 FAIL (one regression, #1414), 30 PARTIAL, 39 SKIP. TC-I24 and TC-I02 passed 20/20 each. Release held for #1427, #1100, #1419 and #1429. About 13M subagent tokens; about 7 hours of working time across roughly 22 hours.

---

## What went well

- **Run 3 ran clean.** Six shards, four of them on their own `playwright-<k>` server and two with no browser, each on its own copy of the fixture spreadsheet, finished in under an hour with no browser incidents. Each closed its own tab.
- **The retakes ran clean.** After the Run 2 failures, four retake shards, one per server, took 128 captures in about 15 minutes with no timeouts.
- **The Doc-ID check on every capture** caught every capture that landed on another shard's Doc. No graded result came from a crossed capture.
- **The true-concurrency barrier** ran TC-I24 and TC-I02 at 20 iterations each, with a Python watcher (the isolation guard refuses the shell loop) and the access log confirming each pair overlapped.
- **A scripted Unicode render.** R6 rendered TC-MD117's UN-04/05 from the fixture's bytes and confirmed every code point raw, closing a gap earlier passes had without knowing it.
- **Merging shard results by script** wrote 1,056 inline results with no hand edits. A dry run caught grouped headings (`TC-S105 / TC-S106 / …`) and a lettered ID (TC-S57b) before anything was written.

## What didn't work well

### 1. More browser shards than Playwright servers

Run 2 put seven shards on four servers, two per server under the mkdir mutex, as `aziz.md` step 7 allowed. A capture batch held the lock past its 180 s staleness, so a waiting shard broke a live lock; shards drove each other's tab, and one shard's broken staleness check (GNU `stat` in place of BSD's) kept removing another's lock for 20 minutes. The servers hung for 30 minutes at a time, then all four disconnected at about 14:00. Nothing could run until the user reconnected them that evening. The fix was always available: one shard per server, which the retakes then did.

### 2. Nothing closed its tabs

`run.md` said never to close a tab, so every shard opened one and left it. Sixteen were open by the end of Run 2, which likely added to the hangs.

### 3. A shard started its own agents

Shard M7 started nine helper agents (about 1.8M tokens, on top of its own 400k). No prompt ruled it out.

### 4. The disk filled during Run 1

Something outside the pass filled the disk at about 00:40 (the pass's own files were under 75 MB). Every write failed, so shards couldn't record results and the shards resumed afterwards had no memory of their work. Their earlier reports were transcribed from messages and fresh shards finished the remaining cases. The pass sat stopped overnight.

### 5. The tool channel changes some characters

Combining marks are NFC-normalized, U+00A0/U+2009/U+3000 become spaces, U+212A becomes `K`, and CRLF can't be sent inline. Cases passing that content inline were testing a different input. Found by M4 with a probe Doc; earlier passes likely had the same blind spot.

### 6. Smaller items

- **Gmail fixtures purged.** Gmail deleted the spam and trash fixtures after 30 days, so TC-GM35 couldn't run (#1420).
- **An existing compile script went unused.** `scripts/qa_compile_results.py` (#1067) wasn't used, because it takes a one-line note per case and this pass's shards wrote full result paragraphs; a separate merge script was written instead.
- **A wrong skip.** A shard skipped TC-DOC224–226 for "no service-account credentials" although the worktree has its own key at the default path; the conductor caught it at compile.
- **A miscount.** The conductor's first Markdown tally said 32 of 52 TCs passed; the merged count was 36.
- **Stale wording.** Shards noted more than 30 cases whose wording no longer matches correct behavior. None changed a verdict; they're listed in each shard's notes, kept in `.workspace/qa/v0.9.6-ornithomimus/shard-results/` in Aziz's worktree.

## Action items

### Done in this retro's PR

- `docs/qa/run.md`: never more Playwright shards than `playwright-<k>` servers; check the Doc ID on every capture; one Doc per call, no mouse-wheel loops; close your own tab last, and the conductor clears the rest; the mutex is only for the default `playwright` server; a section on content the tool channel can't carry; the barrier watcher as a script; "don't start agents of your own" in the barrier worker template.
- `.claude/team-roles/aziz.md`: step 7 caps Playwright shards at the server count; step 5 forbids shards starting agents, keeps shard reports in `.workspace/`, and says what to do on ENOSPC; step 1 notes free disk space; step 10 clears the browser's tabs.
- `docs/decisions/role-file-history.md`: the incident behind those rules.

### Open

- Gmail fixture check in pre-flight: #1420.
- Make the compile script the standard step, accepting full result paragraphs as well as one-line notes: #1067.
- Update the stale case wording the shards listed.
