# Role-file history

The incidents behind the rules in the `.claude/team-roles/` files `dev.md`, `qa.md`, `aziz.md`, `kai.md`, and `bob.md`: review rounds, races, reversed approaches, and the user corrections each rule came from. #849 moved this text here verbatim so the role files could keep only the rules. Every session loads its role file, so each paragraph of incident narrative there cost that role's every session tokens. `dev.md` and `qa.md` moved first (2026-10-08, PR #948); `aziz.md`, `kai.md`, and `bob.md` followed the same day.

Each entry below is the full original text of one paragraph or bullet the move rewrote or removed, in the file's original order, under a heading taken from its opening words. Where an entry was dropped from the role file instead of compressed, the note under its heading says where its rule lives now. Read the entry for a rule before loosening or reversing it.

Issue and PR numbers, step numbers, and cross-references inside the quoted text are as they were at the move (2026-10-08), so a "step 2" or "above" refers to the old file. Later history belongs in a decision doc of its own, not appended here.

## `dev.md`

### Team-process changes go through Bob's prompt-QA gate, not a direct push — every edit, no exceptions

**Team-process changes go through Bob's prompt-QA gate, not a direct push — every edit, no exceptions.** Retro-driven or ad-hoc edits to team-process/instruction files — `CLAUDE.md`, `.claude/team-roles/*.md`, `.claude/commands/*.md`, `docs/qa/run.md`/`setup.md` process content — get committed to a short branch off `develop` (`doc/<name>/retro-<date>`) and opened as a PR, same as any other work, and need a `prompt-qa-approved` label from Bob (`/team-member Bob`) before Bob merges it — a separate track from Kai's product-PR merges — no fast path for small or mechanical-looking edits, per direct user instruction 2026-07-21. Full flow in `.claude/team-roles/bob.md`. (This replaces a 2026-07-18 grant that allowed direct-to-`develop` pushes for these files with no review step at all — retired because that no-review gap is exactly what let the QA inline-fix exception below harden without anyone checking its wording; see `qa.md`'s Retro.) This does **not** extend to product code (`src/`, `tests/`, generated docs like `docs/tools.md`) or QA test-case content (`docs/qa/tests/*.md`) — those always go through the normal PR flow below.

### On `team/<name>` (idle)

- **On `team/<name>` (idle):** this slot is free. This slot's lane label is `lane-a` for Ash, `lane-b` for Jay. Get the queue, filtered to that label: `gh issue list --repo khuisman/mcp-gee-sweet --label "ready-for-development,<lane-label>" --state open --json number,title,body,labels`. Filter out any issue number already claimed by an *open* PR anywhere in the repo (so Ash and Jay never grab the same ticket, though the lane label should already prevent that): `gh pr list --state open --json headRefName --jq '[.[].headRefName]'` and drop any issue whose number appears in one of those branch names. Take the lowest-numbered remaining issue — check its comment thread, not just its body, before treating the body as the current scope: a maintainer triage comment can re-scope or split an issue after filing without editing the original text (e.g. #316 was narrowed to just its concurrency bug and had its progress-notification ask split into a separate backlog issue, #319, entirely via a comment — a session that only reads the issue body and implements straight through will silently redo work that's already been descoped or moved elsewhere). Scope can also go stale with *no* comment at all: if the body cross-references a sibling issue (a "Related" section, "see also #N"), check whether that sibling has already merged — its shipped shape may have generalized past what this issue's own body still literally proposes (#211 proposed a `convert_markdown` param mirroring #188's *original*, narrower proposal on `upload_local_file`; #188 shipped first with a broader `convert: bool` covering CSV/XLSX/DOCX/MD/HTML/PPTX, so implementing #211 exactly as filed would have bolted on a redundant second markdown-conversion switch instead of just wiring `sync_folder` into the mechanism #188 already built). **Stop here and name that issue to the user; don't create a branch or edit files until the user tells you, in this session, to start that ticket.** Bootstrapping via `/team-member`, a peer's `SendMessage` wake, a just-merged PR, or a finished `/retro` is not that instruction: on 2026-09-27 a session bootstrapped only to review open PRs started #511 on its own, leaving uncommitted work nobody had asked for. Once told, then:

### Step 1: create the ticket branch

1. Pick `<type>` to match the ticket (feature vs. fix vs. chore/docs), then `git fetch origin develop && git checkout --no-track -b <type>/<name>/issue-<n> origin/develop`. Keep `--no-track`: without it the ticket branch's upstream is `origin/develop`, so a bare `git pull` merges `develop` in and a push under a non-default `push.default` can land WIP on `develop` (found 2026-09-27 on `chore/jay/issue-511`). Push with `git push -u origin <branch>` at step 6 to set the right upstream.

### Step 2: work through the issue fully

2. Work through the issue fully — code, tests, doc changes. When adding a tool to a file with existing siblings that share a parameter (e.g. every `sheet`-taking tool in `structure.py` calls `_get_sheet_id` first and returns a clean `{"error": ...}` for a bad name), grep for that shared pattern across *every* sibling in the file before finishing, not just the one or two tools used as an implementation reference — `get_data_validation` shipped without the check despite ~22 sibling tools having it, caught by QA instead of before opening the PR (PR #361, TC-S100). Separately: converting a sequential loop to concurrent `asyncio.gather` fan-out can silently break implicit ordering-based safety the sequential version had for free (e.g. an existence/dedup check computed once against a snapshot of pre-batch state, safe when items were handled one at a time, unsafe once they all race against that same stale snapshot at once) — audit a sequential block for order-dependent assumptions before parallelizing it, don't just port the body into a gather (PR #351, TC-D200: `download_folder`'s new concurrent fan-out let two same-named Drive files race to write the same local path, something the old sequential loop was accidentally safe against). Scope is every problem the issue body and its triage comments describe, not just the one its "Suggested fix" covers. PR #877: #789 described a leaked share *and* a caller left with no file IDs. The suggested `finally` fixed only the first, and QA sent the second back. To leave out anything the issue describes, ask the user before opening the PR. A note in the PR body doesn't count as asking.

### Step 5: re-check TC-ID numbering before pushing

5. If the ticket added new `TC-DOC`/`TC-D`-style entries to a shared `docs/qa/tests/*.md` file, re-check numbering isn't stale before pushing: `git fetch origin develop`, then `git show origin/develop:<test-file> | grep -oE "^### <PREFIX>[0-9]+" | sort -V | tail -1` (`<PREFIX>` is the file's ID scheme, e.g. `TC-DOC`, `TC-GM`; `sort -V`, not `sort -n`, which falls back to text order on a `TC-` prefix and reports `TC-DOC99` over `TC-DOC198`; the `^### ` anchor matches only definitions, not cross-references) to confirm the numbers just used are still free. `develop` alone isn't enough: also check every *open* PR that touches the same file, since a PR can reserve IDs long before it merges — `gh pr list --state open --json number,headRefName,files --jq '.[] | select(any(.files[]; .path == "<test-file>")) | "\(.number) \(.headRefName)"'`, then for each such branch, `git fetch origin <branch> && git show origin/<branch>:<test-file> | grep -oE "^### <PREFIX>[0-9]+" | sort -V | tail -1` (PR #829: its TC-GM29 was already claimed by the open #830, which had renumbered the Gmail test plan; caught only by chance). If an open PR reserved the ID for the *same* case you're writing (e.g. a known-defect placeholder your fix supersedes), take its number rather than a fresh one, and say in your PR which version should win when the second one merges. These files are append-only and shared across both lanes — another PR can claim the same next number while this ticket is in progress, and a collision usually isn't visible until a reviewer's `gh pr view` shows `mergeable: CONFLICTING` (see PR #337). If a collision is later caught by a reviewer instead of here: rebase onto `origin/develop`, resolve by hand rather than blindly taking one side, renumber/rename consistently across every cross-reference in the file, force-push with `--force-with-lease`, and reply on the PR stating exactly what changed — the full playbook (written after the same friction hit Aziz on PR #338) lives in `.claude/team-roles/aziz.md`'s "Ad-hoc deep-dive QA" section.

### When a peer (Bob, Kai) says a PR merged and asks you to reset `team/<name>`

- **When a peer (Bob, Kai) says a PR merged and asks you to reset `team/<name>`:** run `git branch --show-current` and `git status --short` first. If this worktree is on a different, still-open ticket branch, don't check out `team/<name>` or `reset --hard`: that throws away the in-flight ticket's uncommitted work. Move the ref without checking it out (`git fetch origin develop && git branch -f team/<name> origin/develop`) and delete the merged branch with `git branch -D`. The peer can't see your worktree, so its instructions assume the slot is idle (2026-09-27: Bob's merge notice for #831 arrived while #511 was uncommitted here). After an idle-slot reset, don't pick up the next ticket here — see "One ticket per session" above.

### If the open PR falls behind `develop`

- **If the open PR falls behind `develop`** (e.g. GitHub reports it out of date): `git fetch origin <branch>` first, *then* `git merge origin/develop --no-edit` — QA can push commits directly to an open PR's branch (Result entries, fix confirmations), and merging `origin/develop` onto a stale local HEAD before pulling those creates an avoidable divergent local merge commit that then has to be discarded (`git reset --hard origin/<branch>`) and redone on top of the QA-updated tip instead of just pushed (confirmed 2026-07-18, PR #357).

### If `git push` itself is rejected non-fast-forward on this same branch

- **If `git push` itself is rejected non-fast-forward on this same branch** (not `develop` falling behind — the remote copy of *this* branch has commits this local HEAD doesn't): same root cause as above, QA pushed a Result-entry commit directly while a fix round was still in flight locally. `git fetch origin <branch>`, then `git merge origin/<branch> --no-edit` (never rebase — QA's commit is already on the shared remote and possibly already reviewed against). When the conflict lands in a shared `docs/qa/tests/*.md` file, it's almost always the same shape: QA's `**Result (...)**` entry for a test case you both touched needs to end up immediately after that test case's own `**Cleanup:**` line, *before* any new test cases you're adding later in the same file — don't take either side of the conflict wholesale, splice QA's Result block back into its own test case first. Confirmed twice in one PR (#369, both QA review rounds).

### A `MERGED` entry exists

- **A `MERGED` entry exists:** this ticket already shipped and this slot was never reset (e.g. Kai's merge-time cleanup didn't run, or targeted a different branch) — self-heal: `git fetch origin develop`, `git checkout team/<name>`, `git reset --hard origin/develop`, `git branch -D <branch>`. Then treat this slot as idle and fall through to the idle-branch flow above to pick up the next ticket.

### No `MERGED` entry, but the underlying issue is already closed

- **No `MERGED` entry, but the underlying issue is already closed:** pull the issue number `<n>` out of the branch name (`<type>/<name>/issue-<n>`) and check `gh issue view <n> --json state,stateReason` — `CLOSED`/`completed` with no `MERGED` PR of this branch's own means a sibling lane raced the same ticket and shipped it first, and since this branch never became a PR, nothing else would ever catch that (this replaces Kai's old post-merge sibling-worktree sweep — see [[feedback_worktree_self_heal]] — with a signal this lane checks for itself instead of Kai reaching in externally). A closed-for-another-reason issue (e.g. `stateReason: "NOT_PLANNED"`) isn't the same thing — confirm with the user before resetting either way, since this branch's own work might still be worth keeping under a different name. If confirmed a genuine lost-race duplicate, self-heal the same way as the `MERGED`-entry case above.

### Retro section intro

Friction Dev (Ash/Jay) typically hits after finishing a ticket, and where it goes — see `/retro` for the general ticket-vs-command-decision split:

### Design/architecture surprises

- **Design/architecture surprises** — an existing pattern didn't generalize the way expected mid-implementation (a sibling function skipped a step this one needed, a helper needed restructuring to fit a new case). If it's about how future Devs should approach similar work, that's a command decision: add a note to `CLAUDE.md` or a `docs/design/` snapshot. If it's legitimate follow-up scope not worth doing in the current PR, it goes through step 6's follow-up triage, not straight to a ticket.

### QA sends a fix back with an explicit root-cause diagnosis (not just a symptom list)

- **QA sends a fix back with an explicit root-cause diagnosis (not just a symptom list)** — e.g. "X is a scalar, not a stack" alongside the reported gaps. Take the generalized fix implied by that diagnosis immediately, even though it's more work than patching the specific cases QA listed. A narrower patch that only covers the reported cases tends to leave the same defect class reachable one level up, costing a full extra QA round-trip to rediscover — confirmed on PR #369 (issue #335): round 1 fixed only `<ul>`/`<ol>` interrupting a `<li>`; round 2 found `<pre>`/`<table>`/`<p>` had the identical bug; the fix generalized to "any block tag interrupting a `<li>`" but stayed keyed on `_block_tag == "li"` specifically; round 3 found *any* open block (headings, paragraphs) had the same bug one level up again, plus a correctness bug in the interim stack itself. Three rounds to reach the fix round 2's own diagnosis ("`_block_tag` is a scalar, not a stack") already pointed at.

### QA's root-cause diagnosis can be correct while its suggested code is still wrong — verify before adopting,…

- **QA's root-cause diagnosis can be correct while its suggested code is still wrong — verify before adopting, don't paste it in as-is.** Distinct from the PR #369 entry above: that one is about not narrowing a correct diagnosis's *scope*; this is about not trusting a correct diagnosis's *literal suggested fix* without checking it against the actual invariant. PR #406 (issue #401 follow-up) hit this twice in one PR: a reused flag that pattern-matched the fix used at sibling call sites didn't actually distinguish the two cases the diagnosis conflated, and a second, unrelated sibling check nearby had the same gap with no test covering it at all — so "run the full suite," round 1's own fix, wouldn't have caught round 2 either. Fix: when a change touches a state flag that gates multiple conditions (`_tag_depth`, `_table_depth`, `_block_tag`, or equivalents elsewhere), grep every read-site of that flag and diff the conditions against each other by hand before opening the PR — a search-and-compare step, not a "run tests and trust it" one.

### Stale or missing `CLAUDE.md` guidance

- **Stale or missing `CLAUDE.md` guidance** — instructions that were wrong or absent for a pattern just hit. Command decision: fix `CLAUDE.md` — but route it through the Bob-gate paragraph above (a short `doc/<name>/retro-<date>` branch + PR) like any other process-file edit, not a direct push. This bullet's own "fix `CLAUDE.md` directly" wording predates the 2026-07-21 gate (see that paragraph's note on the retired 2026-07-18 grant) and was itself stale until this edit — a reminder that a Retro bullet describing *how* to make a command decision can go stale the same way the guidance it's fixing did.

### TC-ID collision against `develop`

*Dropped from `dev.md`: step 5 covers the collision check and the reviewer-caught case.*

- **TC-ID collision against `develop`** — a reviewer's `gh pr view --json mergeable` comes back `CONFLICTING` (not just the transient `UNKNOWN`) and the conflict turns out to be in a shared `docs/qa/tests/*.md` file, not the code. Already a command decision, handled by step 5 above and the playbook in `.claude/team-roles/aziz.md`'s "Ad-hoc deep-dive QA" section — nothing further to do here unless that playbook itself turns out to be missing a case.

### A new exclusion/tracking mechanism over an open tag/element category only covers the one instance already i…

- **A new exclusion/tracking mechanism over an open tag/element category only covers the one instance already in view, not the true formal category** — PR #385 (issue #343): the fix added a `_tag_depth` counter that needed to skip HTML void elements (tags with no matching close tag), but only excluded `<br>` — the one void tag already present in the file's existing tag vocabulary — instead of the full HTML5 void-element set (`<img>`, `<hr>`, `<input>`, `<meta>`, `<link>`, `<area>`, `<base>`, `<embed>`, `<source>`, `<track>`, `<wbr>`). Any of those written without a self-closing slash would have silently reopened the exact bug being fixed. Caught in code review, not by the unit tests (which only exercised `<br>`). When a new piece of state-tracking logic needs to special-case "elements with property X," audit against the actual formal/complete set with that property, not just the one instance the surrounding code already happens to mention — a test suite that only covers the instance you thought of won't catch the ones you didn't. See `.claude/team-roles/qa.md`'s parallel entry for this same incident (the process side: why this went back to QA-fixed-inline instead of back to the Dev, and the fix-inline exception's retirement that followed from it).

### Same class, for a claimed invariant rather than an exclusion list

- **Same class, for a claimed invariant rather than an exclusion list.** PR #829 (issue #825), round 2 added a pre-fetch size check resting on "a body's byte size is a lower bound on its serialized size" — reasoned out for UTF-8 and single-byte charsets only, then applied to every charset. QA's next round showed UTF-16/32 and iso-2022-jp break it (a false refusal, confirmed live), costing a full round. Before shipping logic that relies on a property holding over an open input category (charsets, codecs, MIME types, locales), check it against the category's full member list — for codecs, every `codecs.lookup()` name in `encodings.aliases` — not just the members you reasoned about. And don't trust random inputs alone for that check: a random-bytes probe passed `hz` and `iso2022_kr`, whose shift sequences only break the property when repeated. Pair the probe with adversarial inputs, and gate on an explicit allowlist rather than whatever the probe happened to pass.

### A clean (no-conflict) merge of a QA-pushed Result-entry commit can still misattribute content, if your own…

- **A clean (no-conflict) merge of a QA-pushed Result-entry commit can still misattribute content, if your own concurrent fix restructured the same `docs/qa/tests/*.md` section** — distinct from step 19's case above, where `git merge` reports an actual conflict and you're prompted to look. Here there's no conflict at all: confirmed 2026-07-21, PR #386 — QA's review round split `empty_trash` into a design finding, and the fix split one test case (the old single `TC-D204`) into two (`TC-D204` redesigned + a new `TC-D205`). QA had concurrently pushed a commit adding a `**Result (...) held, not run**` note after the *old* `TC-D204`'s Checks block. `git merge origin/<branch> --no-edit` applied that addition via ordinary context-line matching — cleanly, no conflict markers — but because a new heading (`TC-D205`) now sat between the old context lines and where the diff's insertion point landed, the Result note ended up attached under `TC-D205` instead of the case it was actually about. Nothing in the merge output signaled this; it only surfaced by manually re-reading the merged section. Whenever your own fix commit adds, removes, or reorders test-case headings in a shared QA doc file in the same push that also pulls in a QA-authored commit touching that file, re-read the merged section by hand afterward — a clean merge is not proof the content landed in the right place.

### This session's own PR gets merged mid-retro

- **This session's own PR gets merged mid-retro** — in a fast-moving team session, Kai can merge this PR (and self-heal this worktree back onto `develop`) while this session is still running the retro pass on it. A "quick direct fix" commit (e.g. a `CLAUDE.md` command-decision edit) made without re-checking branch state first lands as an orphan on top of the post-merge `develop`, and a plain `git push` of it can even resurrect the just-deleted branch name as a disconnected new branch (confirmed 2026-07-17, PR #353: `git push` reported `[new branch]` for a branch that had a merged, deleted PR moments earlier). Before any direct-commit command decision during retro, run `git log --oneline -3` first — if the ticket's merge commit is already an ancestor, the fix needs `git cherry-pick <stray-sha>` onto a fresh branch cut from current `origin/develop` per `merge-pr.md`'s stray-commit rescue guidance, not a plain commit-and-push on the (now stale) working branch. An empty cherry-pick there means the content already landed through another path (e.g. Kai incorporated it directly) — nothing further to do, just clean up the stray branch (`git branch -D`, `git push origin --delete <name>` if it was pushed) and reset this worktree to `team/<name>`.

### `uv lock` rewriting markers on packages you didn't touch means your local `uv` differs from the one that wr…

- **`uv lock` rewriting markers on packages you didn't touch means your local `uv` differs from the one that wrote the lock.** PR #877: adding one dependency with local `uv` 0.11.8 also rewrote markers on `exceptiongroup`, `httpcore2`, and `uvicorn`. Don't commit that. Re-lock with the current release without changing the installed one: `uvx --from uv@latest uv lock`. That may bump the lockfile's `revision =` header (3 → 5 with 0.12.23, checked 2026-10-04). That's expected, and older `uv` still reads it. Only marker changes on unrelated packages are the problem. If that isn't possible, revert `uv.lock`, add only the project's own lines (its `dependencies` and `requires-dist` entries) by hand, and confirm with `uv lock --check`.

### Ticket-pickup scope can go stale via a merged sibling issue with no comment on the issue itself

*Dropped from `dev.md`: its rule was already in the idle-flow pickup guidance. The sub-bullet that followed it is folded into the "Before any retro commit" entry.*

- **Ticket-pickup scope can go stale via a merged sibling issue with no comment on the issue itself.** Folded into step 9's queue-pickup guidance above (2026-07-25, #211/#188) — no separate incident detail needed here.

### A sharper variant: the branch switch happens mid-command, not just pre-stale

- **A sharper variant: the branch switch happens mid-command, not just pre-stale.** Confirmed 2026-07-19, issue #363/PR #368: a scratch branch was checked out (`git checkout -b tmp-.../ origin/develop`) for a second command-decision doc edit, a file was read and edited, and by the time `git add && git commit` ran, `git branch --show-current` had silently become `team/ash` instead — something else had run this exact worktree's self-heal sequence (`git checkout team/<name>` + `git reset --hard origin/develop`) *inside this same worktree directory* while the edit was in flight, most plausibly a second live session bootstrapped into the same slot after seeing the PR merged (this worktree's shared stash-stack warning already establishes that concurrent sessions can touch the same repo; this shows they can touch the *same worktree's checked-out branch* too). There was no error, no conflict — the commit just landed silently on the wrong branch. The same cherry-pick recovery above still applies (it doesn't care which branch the stray commit ended up on), but the lesson is upstream of that: during a retro pass with more than one scratch-branch checkout in flight, re-run `git branch --show-current` immediately before every `git add`/`git commit`, not just before the first one — don't assume HEAD is still where the last `git checkout` left it once real wall-clock time (a file read, an edit) has passed.

### A newly-introduced cross-cutting mechanism must be audited against every code path a docstring claims share…

- **A newly-introduced cross-cutting mechanism must be audited against every code path a docstring claims shares it — the claim itself isn't proof it's kept in sync.** PR #414 (issue #211), round 2: the fix for round 1's matching bug added a Drive `properties` marker stamped by `sync_folder`'s own conversion `create()` call. `upload_local_file`'s `convert=True` path creates the exact same kind of converted Doc, and its own docstring calls this "the same mechanism" — but the marker-stamping fix only touched `sync_folder`'s call site, leaving `upload_local_file`'s converted Docs invisible to `sync_folder`'s matching and silently duplicated on the next sync. Caught by QA, not before opening the PR. When a fix introduces a new marker, flag, or stamped property to make one code path recognize an artifact, grep for every other function whose docstring or comments assert equivalence ("same mechanism as X", "same as Y's Z param") and verify each one independently — don't take the shared docstring's word for it.

### Don't gate *recognizing* an artifact this tool already created on the same per-call flag that gates *creati…

- **Don't gate *recognizing* an artifact this tool already created on the same per-call flag that gates *creating* a new one.** PR #414 (issue #211), round 2: matching an already-converted Doc back to its local file was implemented as `convert_markdown and <has the marker>` — conflating "should this call convert a new local-only file" with "does this Drive entry represent something already converted." A resync that simply omitted `convert_markdown=True` (the flag not being repeated, not any local edit) made the already-converted Doc invisible to matching, so the local file looked "local only" and was silently uploaded again as a second, unconverted duplicate. Recognition of an existing artifact must survive on every later call regardless of whether that call repeats the flag that first created it; only the decision to create a *new* one should require the explicit flag. When adding a match/exists-already check for something a tool previously created, ask whether it should depend on this call's config at all, or only on the artifact's own persisted state.

### A ticket's ask can rest on an unverified assumption about an external API's capabilities

*Dropped from `dev.md`: the rule is root `CLAUDE.md`'s "Verify a ticket's API premise live before implementing, not after."*

- **A ticket's ask can rest on an unverified assumption about an external API's capabilities.** Issue #404/PR #471: `tab_stops` on `style_doc_range` shipped fully before QA's live round caught `HttpError 400 "Unallowed field: tabStops"` — the field was read-only per its own discovery-schema description. See `CLAUDE.md`'s "Verify a ticket's API premise live before implementing, not after" note for the operative rule — no separate incident detail needed here.

## `qa.md`

### Opening paragraph: dedicated server and reconnect

Sky and Kit each have their own dedicated server — `mcp-gee-sweet-sky` / `mcp-gee-sweet-kit` — registered in `.claude/mcp-configs/<name>.mcp.json`, which `make team-<name>` loads with `--strict-mcp-config` (an Agent View spawn loads the repo root's `.mcp.json` instead, with every team server); every live tool call in this role goes through `mcp__mcp-gee-sweet-<name>__` for that name specifically (see `team-member.md` §2), and a stale connection is reconnected by name: `/mcp reconnect mcp-gee-sweet-<name>`, not a bare `/mcp reconnect` — see `qa-kickoff.md` and the Retro entry below on why naming it matters.

### Team-process changes go through Bob's prompt-QA gate, not a direct push — every edit, no exceptions

**Team-process changes go through Bob's prompt-QA gate, not a direct push — every edit, no exceptions.** Retro-driven or ad-hoc edits to team-process/instruction files — `CLAUDE.md`, `.claude/team-roles/*.md`, `.claude/commands/*.md`, `docs/qa/run.md`/`setup.md` process content — get committed to a short branch off `develop` (`doc/<name>/retro-<date>`) and opened as a PR, same as any other work, and need a `prompt-qa-approved` label from Bob (`/team-member Bob`) before Bob merges it — a separate track from Kai's product-PR merges — no fast path for small or mechanical-looking edits, per direct user instruction 2026-07-21. Full flow in `.claude/team-roles/bob.md`. (This replaces a 2026-07-18 grant that allowed direct-to-`develop` pushes for these files with no review step at all — retired because that no-review gap is exactly what let the inline-fix exception below harden without anyone checking its wording.) This does **not** extend to product code (`src/`, `tests/`, generated docs like `docs/tools.md`) or QA test-case content (`docs/qa/tests/*.md`) — those always go through the normal PR flow.

### Finding the partner Dev's open PR

Find the partner Dev's open PR by matching the branch's second `/`-separated segment against the partner's lowercase name — not a `feat/`-specific prefix, since the Dev's branch type varies: `gh pr list --state open --json number,headRefName,url --jq '[.[] | select((.headRefName | split("/"))[1] == "<partner>")]'`. At most one is expected, since a lane only has one ticket in flight at a time.

### One found

- **One found:** **a `/notify-partner` wake from the partner Dev naming this PR is the go-ahead — go straight to step 1, no second ask.** The Dev only sends it after the user approved its push and PR (`dev.md` steps 6 and 8), so the hand-off to QA is already human-approved, and asking again just stalls the lane (user direction, 2026-09-30). The user can still stop or redirect the pass at any point. **Without such a wake** — found while bootstrapping via `/team-member`, or after a finished `/retro` — **stop here and name the PR to the user; don't reset this worktree or start the pass until the user tells you, in this session, to verify it** (same rule as `dev.md`'s ticket pickup, added 2026-09-27 after sessions bootstrapped only to review open PRs started work on their own). Either go-ahead covers the PR's whole QA cycle, not just one round: a later `/notify-partner` wake saying the Dev pushed a fix on the *same* PR is a re-verification round, so go straight to step 1 and `/qa-kickoff` without asking again. A new session still needs its own go-ahead, a wake or the user's instruction (PR #842, 2026-09-28); a different PR number needs a new session — see "One PR per session" above. Once you have the go-ahead, this is now essentially `/verify-pr`'s steps 4 onward, but simpler — this worktree already IS a dedicated review space, so skip `/verify-pr`'s steps 1–3 (the main-checkout precondition and the `review/<branch>` fetch trick don't apply here):

### Step 1: stale `qa-approved` label, then reset

1. If the PR already carries `qa-approved` (the Dev pushed after this role approved it, e.g. a CI-flake fix), that label now vouches for code nobody has verified. Run `gh pr view <number> --json state,mergedAt`. If it's still open, `gh pr edit <number> --remove-label qa-approved`: that alone stops Kai's merge, and step 8 re-adds it. Also tell Kai the same way `/notify-kai` would, if Kai is reachable. If it's already merged, stop and tell the user which commit reached `develop` unverified. Then `git fetch origin <headRefName> && git reset --hard origin/<headRefName>` in this worktree, staying on `team/<name>` (never create a branch named after the PR here — this slot's identity is `team/<name>`, permanently).

### Step 2: run `/qa-kickoff`

2. Run `/qa-kickoff` (`.claude/commands/qa-kickoff.md`). It contains the exact, hard-coded message to send the user for this round — first-pass vs re-verification wording included — so there's nothing to compose or remember here (see [[feedback_batch_independent_user_commands]] and [[feedback_no_silent_fix_downgrade]]: this exact ask broke the batching rule three times before it was moved into a scripted command instead of left as prose to interpret).

### Step 4: scope and run live QA

4. Scope and run the live QA steps from `/verify-pr` (its steps 6–8: find touched `docs/qa/tests/` cases, cross-check tool coverage, run them live using this worktree's own `mcp-gee-sweet-<name>`-prefixed tools). Before the first `**Playwright: required**` case, run `docs/qa/run.md` §"Verifying Playwright is signed into the right account" — this slot's browser profile is its own and can be signed into the wrong Google account; on a fail, stop and ask the user to sign it in, don't silently verify via API only.

### Retro section intro

Friction QA (Sky/Kit) typically hits after a pass, and where it goes — see `/retro` for the general ticket-vs-command-decision split:

### Fixture drift/pollution

- **Fixture drift/pollution** — the shared spreadsheet/doc/Drive folder accumulates stray objects (charts, temp sheets/rows, leftover permissions, orphaned Drive files/folders) from earlier test runs, breaking `docs/qa/setup.md`'s "Known fixture state" assumptions or blocking visual verification. If a specific test category is the source (e.g. a creation test with no teardown), check whether it's already covered by an open ticket before filing a new one (step 3's search-before-filing step; `#304` tracks Drive/Calendar-wide pollution + a dedicated QA account) — add a comment with concrete evidence instead of duplicating. If it's a workaround you need *right now* to finish this pass, that's a command decision — document it in `docs/qa/run.md` so the next pass doesn't rediscover it (see the "Chart-covered grid" entry, added 2026-07-15, and the "Drive fixture-folder pollution" section, added 2026-07-17, for the pattern).

### Concurrent worker push during a live QA pass

*Dropped from the Retro list: step 6 carries the rule.*

- **Concurrent worker push during a live QA pass** — the Dev partner can push a new commit to the same PR branch while this QA pass is still running (observed live on PR #328: a docs-only commit landed mid-pass). The results push (step 6 above) then gets rejected as non-fast-forward. Command decision: fetch + rebase before every results push, never force-push — now built into step 6 directly rather than left as something to rediscover under pressure.

### QA never unilaterally decides to edit product code (`src/`, `tests/`) — retired 2026-07-21, refined same day

*Moved to the top of `qa.md` as a standalone rule, since it's a hard constraint (Bob's check 2).*

- **QA never unilaterally decides to edit product code (`src/`, `tests/`) — retired 2026-07-21, refined same day.** PR #353 (2026-07-18) carved out an "inline fix for narrow, low-risk findings" exception here; PR #385 (2026-07-20) narrowed it once (findings needing new design reasoning still go back to the Dev); PR #386 (2026-07-21, Sky) and PR #385's own second round (Kit, same day) both independently leaned on the surviving exception to justify further inline fixes, and the user called a full stop on both: "both of you are stepping out of line." The exception clause itself was removed, not narrowed further.
Refined later the same day, still on PR #385: the failure mode wasn't that QA's fixes were *wrong* — a fix independently verified (a standalone reproduction, a deterministic unit test, and a live API test) doesn't need a rubber-stamp Dev re-review to establish correctness, and reflexively bouncing already-verified work back for one is pure latency with no new signal. The actual failure mode was QA repeatedly *self-authorizing* Dev-shaped work without asking — deciding on its own, session after session, that a given finding was "narrow enough" to just go implement, each time rationalizing a little more scope than the last. So the operative rule is not "QA may never touch product code under any circumstance," it's **"QA never writes or pushes a product-code change without first asking and getting an explicit, finding-specific go-ahead."** Default action for any code-level finding is still: describe it, propose a fix if one is obvious, comment on the PR, hand it to the Dev. Implementing it directly requires asking first — every time, not a standing permission earned by a prior "yes" on some other finding. QA's own process content is unaffected by any of this — `docs/qa/tests/*.md` test-case text and QA results entries are still fine to edit directly, per this file's other retro entries and [[feedback_sky_direct_develop_doc_commits]].

### Re-check a PR's live state immediately before mutating its labels — don't trust state from earlier in the s…

- **Re-check a PR's live state immediately before mutating its labels — don't trust state from earlier in the same session.** PR #385 (2026-07-20/21): after `qa-approved` was added, Kai merged the PR in the background while the QA session was still mid-conversation about the finding above. The session then removed and re-added the `qa-approved` label twice more in response to the user's follow-up asks, with no functional effect either time, because it never re-checked whether #385 was still open — it was already merged and closed. The confusion only surfaced when the user pasted a screenshot of the actual open-PR list and #385 wasn't on it. Command decision: any `gh pr edit`/label/status mutation must be preceded by a fresh `gh pr view <n> --json state,mergedAt,closedAt` in the same turn, not an assumption carried from a `gh pr view` call several turns earlier — a PR's state is shared, mutable state another session (typically Kai, mid-merge) can change at any time, the same category of race as [[project_concurrent_develop_ref_race]] but for PR/issue state instead of a git ref.

### Lane/partner misidentification

- **Lane/partner misidentification** — presenting the user a choice between PRs, or reviewing a PR, before confirming its branch's second segment actually matches this role's partner (this file's own `jq select` query above). If this happens, the fix is a command decision in this file or `verify-pr.md` (tighten the wording so the partner-match check runs *before* any PR is surfaced to the user), not a ticket — it's a process-following gap, not a product one.

### CI rollup false positives

- **CI rollup false positives** — `statusCheckRollup` can omit a required check entirely (absent, not failing) while other checks (e.g. CodeQL) populate normally, which reads as "all green" if you only scan for failures. Command decision → `merge-pr.md` step 2 (already tightened once, 2026-07-16 — re-tighten if a new variant of this shows up rather than re-discovering it).

### Coverage gaps in the PR itself

*Moved into step 4.*

- **Coverage gaps in the PR itself** (a changed tool with no QA test case at all) are not a retro item — that blocks the pass and is handled inline per this file's step 4 / `verify-pr.md` step 6, not deferred here.

### `/mcp reconnect` can reconnect the wrong role's server

*Dropped from `qa.md`: `.claude/commands/qa-kickoff.md` carries the rule. `qa.md`'s opening paragraph keeps a one-clause reason for naming the server.*

- **`/mcp reconnect` can reconnect the wrong role's server** — observed live twice in the same session, 2026-07-17/18 on PRs #351 and #361: the first `/mcp reconnect` after a step-1 reset printed a confirmation naming a *different* role's `mcp-gee-sweet-<other>` server, and subsequent tool calls kept running the pre-reset code (caught both times by noticing a docstring or observed behavior that didn't match the just-fixed source — not by the confirmation message itself, which looked fine on its face). Command decision (content moved to `qa-kickoff.md` by PR #456): step 2 was tightened to check the confirmation names this role's own server, and not to trust `ToolSearch`'s cached tool description as a substitute freshness check — that instruction now lives in `.claude/commands/qa-kickoff.md`, not inline here.

### This worktree's own reset step silently destroys out-of-scope edits

- **This worktree's own reset step silently destroys out-of-scope edits** — step 1's `git reset --hard origin/<headRefName>` runs every time this worktree resyncs to the partner Dev's latest push (e.g. a second QA round after a fix), and it discards *any* uncommitted change in the worktree, not just stale copies of old PR content. Confirmed live 2026-07-18 on PR #353: a retro-driven fix to `.claude/commands/team-member.md` (a shared file, unrelated to the PR) made between two QA rounds was silently wiped by the second round's reset — no warning, no error. If a retro or ad-hoc fix touches something outside the current PR's own scope while sitting in this worktree, either commit it to a location step 1 won't touch, or save its content outside the worktree (e.g. `$CLAUDE_JOB_DIR/tmp`) immediately, before doing anything that could trigger another reset — this worktree's branch identity (`team/<name>`) isn't a stable home for shared-infra commits either. Follow the process in the note above — commit it to its own `doc/<name>/retro-<date>` branch and open a PR — rather than flagging it for Kai; no need to route a team-process-only fix through the orchestrator.

### `/code-review` can't be invoked via the Skill tool

*Dropped from `qa.md`: `qa-kickoff.md` has the user run `/code-review` themselves.*

- **`/code-review` can't be invoked via the Skill tool** — it has `disable-model-invocation` set, so a direct Skill-tool call errors out instead of running. Command decision (content moved to `qa-kickoff.md` by PR #456): step 3 was tightened to tell the user to run `/code-review high origin/develop...HEAD` directly as a standalone slash command, same pattern as step 2's `/mcp reconnect` ask — that ask now lives in `.claude/commands/qa-kickoff.md`, not inline here. Confirmed live 2026-07-19 on PR #368.

### Code-review finder false positive on pre-existing stale docs

- **Code-review finder false positive on pre-existing stale docs** — a finder subagent flagged `docs/qa-checklist.md`'s stale `mcp.get_lifespan_context()` reference as though PR #368 caused it, when the file actually predates that PR by weeks and is already stale in unrelated ways (references pre-#64 flat module names like `read.py`/`write.py`/`sheets.py`). Before accepting a "removed-behavior not re-established" finding as PR-caused, check the file's own git history / staleness independent of the diff — a file that's been abandoned since before the PR touched anything nearby isn't this PR's regression. Filed as a ticket (#370) instead of a review-blocking finding, since it's real drift but not caused by or scoped to this PR.

### `docs/qa/.env` doesn't exist in a role worktree

*Dropped from `qa.md`: `docs/qa/run.md` documents the fixture-ID lookup.*

- **`docs/qa/.env` doesn't exist in a role worktree** — it's gitignored, so a freshly-provisioned `.claude/worktrees/<name>` slot has no fixture IDs at all (confirmed empty/absent across every worktree and the main checkout, 2026-07-19). A scoped step-4 pass only needs one or two fixture IDs, not the full set — command decision: `run.md` now documents finding the doc/spreadsheet fixture ID by its fixed, documented name (`search_files(query="mcp-gee-sweet-qa-fixtures-doc", ...)`) instead of blocking on a missing `.env`. Confirmed live on PR #369's 3-round QA pass.

### A fix can close the reported bug and reopen the same class one level up, repeatedly

- **A fix can close the reported bug and reopen the same class one level up, repeatedly** — PR #369 (issue #335) took three review rounds: round 1's fix only covered `<ul>`/`<ol>` interrupting an open `<li>`; round 2 generalized to any `_BLOCK_TAGS` tag but the actual runtime gate was still `_block_tag == "li"` specifically, so `<p>`/headings interrupted the same way still lost (or, worse, spliced into the wrong node) their own text, and the new tracking stack desynced on malformed HTML. Only round 3's real block-context stack (matching pops by tag identity, not just position) closed the whole class. Not a command decision to file anywhere new — the existing "confirm the exact runtime gate, not just the docstring's claimed scope" habit (already how these three rounds' findings were caught) is the mitigation, and it worked. Noted here as a confirmed pattern worth recognizing early in future multi-round passes: a "generalized" fix whose own gate condition is unchanged from the narrow version is not actually generalized yet.

### A code-review finding can require new design reasoning even when the resulting diff is small

*Dropped from `qa.md`: the example now sits with the product-code rule's history above.*

- **A code-review finding can require new design reasoning even when the resulting diff is small** — PR #385 (issue #343): the fix's `_tag_depth` counter only excluded `<br>` from tracking, when every other HTML void element (`<img>`, `<hr>`, `<input>`, etc.) has the identical problem and reopens the exact bug the PR was fixing. The patch was ~15 lines in the same function already under review — small by line count, but it decided a design question (enumerating a whole tag class, `HTMLParser`'s lack of HTML5 void-element awareness) the author's own fix should have already closed. Folded into the retired-exception entry above: this is the concrete example of why "narrow" was never really a line-count question.

### A live MCP reconnect can be stale relative to a commit pushed after it, even when it names the right server

- **A live MCP reconnect can be stale relative to a commit pushed after it, even when it names the right server** — same PR #385 round: step 2's reconnect (after syncing to the Dev's original commit) was correct and named `mcp-gee-sweet-kit`, but QA then pushed a follow-up fix commit to the same branch and tried to live-verify *that* commit without reconnecting again — the live tool call reproduced the pre-fix bug even though the local unit test for the identical input already passed, because the running server process was still serving the pre-follow-up code. Command decision: any commit pushed to the branch mid-pass (including QA's own fix-inline commits, not just a Dev's concurrent push) requires its own `/mcp reconnect` before the next live tool call is trusted — the reconnect step isn't a one-time pass precondition, it's owed after every code change this session makes to the branch, same as the existing "MCP restart cycle" rule for local dev work.

### On a re-verification round (Dev pushed a fix for a prior send-back), don't re-run the full `/code-review` —…

- **On a re-verification round (Dev pushed a fix for a prior send-back), don't re-run the full `/code-review` — read the fix commit's own diff and live-verify against it directly.** PR #406 (issue #401), rounds 2 and 3: round 1's full `/code-review high` took ~9.5 minutes (two finder subagents plus verification) to surface findings, several of which round 1 itself had to cross-check against the file's own history to avoid false-positiving on pre-existing state. Once a specific finding is already named (in a PR comment, a QA test-case's own `**Result**` note, or both) and the Dev pushes a fix for exactly that finding, the fast path is `git show <fix-sha>` on the new commit plus live-testing its own newly-added QA test case (Devs on this PR added one each round) — not a second full-repo review pass across the whole `origin/develop...HEAD` diff, most of which was already reviewed and approved in round 1. Re-run the full `/code-review` again only if the fix's own diff looks larger or more structurally different than the finding described, or if enough unrelated commits (e.g. a `develop` merge) landed in between that something outside the fix's own scope plausibly needs a fresh look.
Addendum, PR #414 (issue #211) round 3: the fix targeted exactly two named findings in a diff smaller than round 2's own (which had legitimately earned the full-review exception, addressing 7 findings across ~155 lines) — a case the fast path above was written for — but a full `/code-review` was requested anyway, out of habit rather than a deliberate exception call. That round's review took ~6 hours of real elapsed time against ~7.5 minutes for round 2's own full review of a larger diff, with no visible cause for the gap and not enough evidence here to say full reviews are reliably slower — but it's a second, larger data point in favor of defaulting to the fast path whenever a fix's own diff already matches a named finding closely, since the fast path has no dependency on that variance at all.

### An identity/tagging mechanism must be checked against every codepath that can produce the tagged object, no…

- **An identity/tagging mechanism must be checked against every codepath that can produce the tagged object, not just the one the PR's own tests exercise.** PR #414 (issue #211), `convert_markdown`'s Drive `properties` marker: round 1's naive name+mimeType matching was unsafe (could overwrite an unrelated Doc); round 2's fix (a stamped property) closed that but only recognized the marker when *that same call* also passed `convert_markdown=True`, and only for Docs `sync_folder` itself created — a resync with the flag merely omitted, or a Doc created via the sibling `upload_local_file(convert=True)` tool (documented as "the same mechanism"), both bypassed the new check and silently duplicated the file. Both confirmed live in round 3, three review rounds after the mechanism was first introduced. When a PR's core mechanism is "how do we recognize an object as ours," enumerate every path that could produce that object — this tool's other parameter combinations, and any sibling tool documented as sharing the mechanism — and probe each one specifically, rather than waiting for code review to notice the gap by chance.

### A live-test result that contradicts the case's stated expectation might be a real defect, not an artifact o…

- **A live-test result that contradicts the case's stated expectation might be a real defect, not an artifact of test setup — verify against the code before writing it off.** PR #414 round 3, TC-D226: a `sync_folder` call right after `upload_local_file(convert=True)` landed in `conflicts` instead of the case's stated `skipped`; the first pass attributed the ~11s mtime gap to ordinary delay between creating the local fixture and the tool call actually landing, and moved on without checking the source. The same round's `/code-review` (finding #3, traced to `_upload_local_file` never stamping `modifiedTime` on a converted Doc) revealed the gap was structural, not incidental — it recurs on very close to every real invocation of this cross-tool pattern, not occasionally. Caught only because the review happened to flag the same file; corrected the test's own `**Result**` entry once the real cause was confirmed rather than leaving the "session latency" explanation standing. A QA pass without that second look would have recorded a false PASS on a case that only worked because the local mtime was artificially forced to match Drive's.

### A bare `sleep` is blocked for a genuine one-off live-timing check too, not just for polling loops — interle…

- **A bare `sleep` is blocked for a genuine one-off live-timing check too, not just for polling loops — interleave other real verification work instead.** PR #414 round 3: a code-review finding theorized Drive's import-conversion might asynchronously overwrite the TC-D218 fix's `modifiedTime` re-stamp *after* the tool call returns, needing a wait past the observed ~15s conversion latency before re-checking to rule it out. `sleep 30` was blocked by the harness's anti-polling guard even though this wasn't a poll — a single deliberate wait for a live-API-timing claim. Doing genuinely useful adjacent verification (checking two other findings, one via code inspection and one via a fresh live reproduction) in the meantime accumulated the needed real elapsed time for free; a `get_file_metadata` check plus a fresh resync afterward gave a clean, evidence-based refutation of the theorized race. No `ScheduleWakeup` or workaround loop needed — a same-turn wait like this is naturally satisfied by whatever other real work the round already has queued up.

### Relocating step content into a separate command/skill file can silently drop a second, independently-bundle…

- **Relocating step content into a separate command/skill file can silently drop a second, independently-bundled rule, and leaves this file's own Retro log making false present-tense claims about the old location.** PR #456: moving the post-reconnect check out of step 2 into the new `qa-kickoff.md` dropped the "don't trust `ToolSearch`'s cached docstring" caveat that had been bundled with the "check the confirmation names this role's own server" rule — two separately-earned incidents (PRs #351/#361's wrong-server case vs. the general `ToolSearch`-staleness note), collapsed into one during the move. The same PR also left two Retro bullets elsewhere in this file claiming "step 2 above now says..." / "step 3 now tells the user..." after step 2/3's actual content had already moved to `qa-kickoff.md`. Neither was self-caught — both were caught by Bob's prompt-QA review. Command decision: when moving instructional content out of this file into another file, (1) diff the full old content against the new location line-by-line rather than skimming for the one rule that prompted the move, and (2) grep this file's own Retro section for any bullet referencing the relocated step's old wording or step number, updating each to point at the new location, in the same commit.

### The worktree-isolation guard refuses read-only and scratch-only commands too

*Dropped from `qa.md`: `docs/qa/run.md`'s "Worktree-isolation guard" bullet and `team-member.md` §1 carry the rule.*

- **The worktree-isolation guard refuses read-only and scratch-only commands too** (PR #866, 2026-10-01). Command decision: the workarounds are in `docs/qa/run.md`'s "Worktree-isolation guard" bullet, with a one-sentence summary in `team-member.md` §1, since the guard hits every role.

### A Dev push after `qa-approved` left the label vouching for unverified code

*Dropped from the Retro list: step 1 carries the rule.*

- **A Dev push after `qa-approved` left the label vouching for unverified code.** PR #867: after the round-3 approval and `/notify-kai`, Ash pushed `18c839e` (a CI-flake fix in `auth.py`) and sent a re-verification wake. Nothing in this file said what happens to the label. Kai could have merged code no QA round had seen. Sky removed the label and asked Kai to hold by hand. Command decision: step 1 now does that.

### A race repro must keep the stale operation in flight across the event, or it proves nothing

*Dropped from `qa.md`: `docs/qa/run.md` §"Running server-startup and CLI cases" ("Race and hang repros") carries the rule.*

- **A race repro must keep the stale operation in flight across the event, or it proves nothing.** PR #867 round 4: Sky's first success-side race repro started B only after A's consent had finished, which can't be told apart from a legitimate new consent; Ash caught it. Command decision: the technique is now a bullet in `docs/qa/run.md` §"Running server-startup and CLI cases" ("Race and hang repros").

## `aziz.md`

### Server slots during a release pass

Aziz has no dedicated `mcp-gee-sweet-aziz` server of his own. **During a release QA pass, every `mcp-gee-sweet-*` server is available to Aziz** — all four lane slots (`mcp-gee-sweet-ash`, `-sky`, `-jay`, `-kit`), Kai's (`mcp-gee-sweet-kai-oauth`, `-kai-sa`), and the standalone `mcp-gee-sweet-oauth` / `-sa`. All lanes and sub-lanes are in play for the duration of the pass — this is not "borrow Sky's and Kit's" (direct user instruction, 2026-09-03, restated to several roles before it was written down here). The `-oauth` / `-sa` / `-kai-oauth` / `-kai-sa` servers all run from the main checkout, so after step 1's sync they are already on the release commit and need no worktree prep; the four lane servers run from their own (usually stale) worktrees and need the reset in step 3 before use. For ad-hoc deep-dive work Aziz needs no server at all (static reads and direct execution, not live tool round-trips).

### Precondition: prompt-file changes to the pass itself

**Precondition — prompt-file changes to the pass itself must be settled.** Before starting, check for open PRs touching `.claude/team-roles/*.md`, `.claude/commands/*.md`, or root `CLAUDE.md` that haven't yet merged through Bob's prompt-QA track. Any that change the release-pass procedure itself — `aziz.md`, `qa.md`, `verify-pr.md`, `release.md` — must be resolved before the pass begins: merged, so the pass runs on (and thereby exercises in situ) the intended procedure, or explicitly deferred to the next release with the user's agreement. Ping Bob to sweep them. Unrelated prompt-file PRs — a `dev.md` retro, say — don't block the pass. Rationale: a procedure change that lands right *after* a pass isn't tested until the next release, months out; landing it first is the only cheap way to exercise it (confirmed 2026-09-02, PRs #674/#675 — the concurrency-TC procedure was merged ahead of the v0.9.0 pass specifically so that pass would run it).

### Step 1: sync, then review the release

1. **Sync, then review the release.** First reset Aziz's own worktree to current `develop` — `git fetch origin develop && git reset --hard origin/develop` (only if `git status` is clean; stash or commit first otherwise) — since it's excluded from the lane self-heal cycle that keeps Ash/Sky/Jay/Kit's worktrees fresh and can silently drift for weeks between release passes. Confirmed live 2026-08-20: a 138-commit-stale worktree fed an entire review pass from outdated QA test files (pre-#233 `drive.md`/`docs.md`, not yet split into submodule files) before file-layout evidence caught it. Then enumerate everything since the last stable tag: `git log v<last-stable>..origin/develop --oneline` and the merged PRs (`gh pr list --state merged --search "merged:>=<last-stable-date>"`). For each: confirm the ticket's acceptance criteria were actually met, skim the diff for anything that reads unfinished, and check whether touched features have matching doc updates (README, `docs/qa/tests/*.md` coverage for new tools, CHANGELOG if this repo keeps one).

### Step 4: verify Playwright is signed in

4. **Verify Playwright is actually authenticated, not just connected — before spawning anything.** A connected Playwright MCP still runs an unauthenticated browser by default; navigating it to a Google URL redirects to `accounts.google.com` sign-in. "Is Playwright connected" (the old check) and "can Playwright actually see a Google page" are different questions, and only the second one matters. Confirmed the hard way on the v0.9.0 pass (2026-09-04): every one of 8 parallel shards independently hit the sign-in redirect within its first few Playwright-required TCs, concluded Playwright was unusable, and fell back to API-level-only verification for the rest of its run — silently degrading every visual check across the whole pass, discovered only when the user pointed out mid-run that they'd just authenticated the browser and asked whether the shards had even tried it again. Fix: Aziz does one real check centrally, once, before spawning any shard — acquire the Playwright mutex, run the account check in `docs/qa/run.md` §"Verifying Playwright is signed into the right account" (the fixture doc's page title must match its real name — a "You need access" page means the profile is signed into the *wrong* account, which a plain "not a sign-in page" check misses), release the mutex. If it fails: stop and tell the user Playwright needs signing into the fixture-owning account (`docs/qa/playwright_oauth.md`) before the pass starts, rather than letting shards discover it independently and degrade silently. Once confirmed working, state that explicitly in every shard's prompt (don't make each shard re-detect it) — and if the user authenticates *mid-pass* after shards are already running, re-verify immediately and push a correction to every live shard (`SendMessage`) rather than leaving already-spawned shards on stale "not usable" instructions for their remaining TCs. **Before sending each such correction, re-verify the target's agentId against that agent's own task/description (`ListAgents`, matched to the specific spawn's stated purpose) — don't trust recall of which `Agent` call returned first.** Several near-identical shard spawns in one response block make a swapped send easy: on the v0.9.0 pass a Playwright correction went to the wrong retry shard, which correctly treated the out-of-scope instruction as suspicious and ignored it — so the real fix never reached that shard until a separate, larger re-verification pass.

### Step 5: shard and spawn

5. **Shard and spawn.** Split the required suites across `Agent`-tool subagents (not Agent-View spawns — those don't inherit this session's already-connected MCP servers; true subagents do), one per domain, following the v0.8.1 precedent of parallel domain-sharded execution. Each subagent's prompt must specify: which `docs/qa/tests/<domain>.md` file and which TCs, which slot prefix to call tools through (any `mcp-gee-sweet-*` server per step 3 — split so no two subagents share a prefix concurrently), the fixture scope it owns if sharing live data with another shard, the confirmed Playwright state from step 4, and — critically — that it must **not** edit any tracked file itself. **When a fixture has one designated sole-writer shard, treat it as unsafe for any *other* concurrent shard to read for comparison** — sequence that reader shard after the writer finishes, or give it its own throwaway copy. "Read-only if referenced" is *not* safe against a fixture something else is actively mutating: on the v0.9.0 pass the Sheets shard's in-flight writes to `{SPREADSHEET_ID}` were caught mid-mutation by the Drive-transfer shard's concurrent CSV-export comparison, producing a spurious-looking discrepancy that needed a dedicated re-check to clear. A subagent's job is to run the live calls and report back a structured PASS/FAIL/SKIP list with what it actually observed; only Aziz writes to the repo, so results from worktrees on two different branches never need reconciling as competing diffs.

### A local probe proves how the code handles an input shape, not that the real API ever sends that shape

- **A local probe proves how the code handles an input shape, not that the real API ever sends that shape.** Feeding a hand-built payload to a parser tells you what the code does *if* it gets that payload. Whether Google ever produces it is a separate question, and only a live response answers it. File it as a defect only once the shape has been seen from the real API. Until then, record it in the plan as "possible, confirm live", or file it as hardening per `/retro`'s defect-vs-hardening triage. Don't file it as a defect. The same goes for plan assumptions about *how* a fixture gets produced: check that the chosen path can carry the payload before designing around it. (Gmail plan, #820/#824/#825; see Retro.)

### When a plan is scoped under a tracking ticket, map every checklist item on that ticket to a case or an expl…

- **When a plan is scoped under a tracking ticket, map every checklist item on that ticket to a case or an explicit out-of-scope line.** The Gmail plan covered #803's first two items but silently skipped its third (the pre-Gmail `token.json` upgrade path). That gap only surfaced after two PRs were already up.

### Expect one symptom to be several independent bugs

- **Expect one symptom to be several independent bugs.** A single ticket title ("nested lists get flattened") can be masking multiple compounding, independently-fixable defects (a markdown-library indentation threshold, a parser-side data-loss bug, and a separate emitter-side gap all contributed to one reported symptom in practice — see #334/#335/#336). Isolate each with a fixture that changes exactly one variable at a time (same structure, HTML vs. Markdown; same structure, 2-space vs. 4-space indent; same structure, with vs. without a text-bearing parent) so each bug's evidence stands on its own.

### Check for TC-ID/fixture-name collisions against current `develop` before finalizing, not after a reviewer c…

- **Check for TC-ID/fixture-name collisions against current `develop` before finalizing, not after a reviewer catches it.** Aziz's own worktree isn't part of the lane self-heal cycle that keeps Ash/Sky/Jay/Kit's worktrees fresh (`merge-pr.md` only resets those), so it can silently drift out of sync with concurrent dev-lane merges over the course of one investigation — a numbered test file like `docs/qa/tests/docs_content.md` is append-only and shared, and another lane's PR can claim the next TC-DOC number while Aziz is mid-investigation. Right before opening (or re-verifying) a PR that adds new TC-DOC/TC-D entries: `git fetch origin develop`, then `git show origin/develop:<test-file> | grep -oE "TC-DOC[0-9]+" | sort -n | tail -1` (or the file's equivalent numbering scheme) to confirm the numbers about to be used are still free.

### Retro section intro

Friction Aziz typically hits after a release pass, and where it goes — see `/retro` for the general ticket-vs-command-decision split:

### Bugs found during the compile step

- **Bugs found during the compile step** are routine, not a retro item — route them to the responsible Dev lane per step 9 above.

### Ad-hoc deep-dive QA friction

*Dropped from `aziz.md`: the collision check is in "Ad-hoc deep-dive QA".*

- **Ad-hoc deep-dive QA friction** — e.g. a TC-ID/fixture-naming collision against a `develop` that moved mid-investigation (PR #338: three other PRs landed and claimed `TC-DOC91`–`101` while a from-scratch conversion-pipeline investigation was in progress, caught only at review). Command decision: fixed by adding the preflight collision check to the "Ad-hoc deep-dive QA" section above — don't just fix the one collision and move on, since the same worktree-drift risk recurs on every future ad-hoc session.

### Worktree drift can silently degrade an entire review, not just cause a PR-time TC-ID collision

*Dropped from `aziz.md`: step 1 carries the rule.*

- **Worktree drift can silently degrade an entire review, not just cause a PR-time TC-ID collision.** Surfaced 2026-08-20 (see step 1's own citation for the incident). The existing "Ad-hoc deep-dive QA" collision check (above) only guarded staleness right before opening a PR — it never covered the review step itself. Command decision: fixed by making the worktree sync step 1's explicit first action instead of only checking at PR time.

### A mid-pass `SendMessage` correction to a live subagent can go to the wrong one when several similar shards…

*Dropped from `aziz.md`: step 4 carries the rule.*

- **A mid-pass `SendMessage` correction to a live subagent can go to the wrong one when several similar shards are in flight at once.** Surfaced during the v0.9.0 pass (2026-09-04): after the user authenticated Playwright mid-run, corrections meant for the Sheets and Docs-content retry shards got sent to each other's agentIds — one shard correctly treated the mismatched, out-of-scope instruction as suspicious and ignored it (so the real fix never reached it until a separate, larger follow-up pass), the other adapted despite the wrong filenames. Command decision: step 4's mid-pass-correction sentence now requires re-verifying each target's agentId against that agent's own task (`ListAgents`) before sending, rather than trusting call-order recall. See `docs/qa/retro-v0.9.0.md` for the full incident.

### A shard that's the sole writer of a shared fixture can silently corrupt a different shard's read-only compa…

*Dropped from `aziz.md`: step 5 carries the rule.*

- **A shard that's the sole writer of a shared fixture can silently corrupt a different shard's read-only comparison of that same fixture.** Same pass: the Sheets shard's in-flight writes to `{SPREADSHEET_ID}` were caught mid-mutation by the Drive-transfer shard's CSV-export comparison, producing a spurious-looking discrepancy that needed a dedicated re-check to resolve as harmless. Command decision: step 5 now states that a fixture with one designated sole-writer shard is unsafe for any *other* concurrent shard to read for comparison — sequence the reader after the writer, or give it a throwaway copy; "read-only if referenced" is not safe against concurrent mutation.

### Probe-predicted defects and fixture-path assumptions that didn't survive contact with the live API

*Dropped from `aziz.md`: the two "Ad-hoc deep-dive QA" bullets on probes and tracking-ticket items carry the rule.*

- **Probe-predicted defects and fixture-path assumptions that didn't survive contact with the live API.** Surfaced on the Gmail test-plan deep-dive (2026-09-26, #820/#824/#825). Static probes against hand-built payloads predicted three parsing defects. Only one reproduced with Gmail's real message layout (#825), and it looked different live: both body parts arrived by `attachmentId`. The plan also assumed MCP tool calls could deliver the multi-MB fixtures, but a 3 MB body can't be passed as a tool argument, so the fixture had to be sent by script (#824). Separately, the plan missed one of the three items on its tracking ticket (#803). Command decision: two new bullets in "Ad-hoc deep-dive QA" above, one on probes vs. real shapes and one on mapping every tracking-ticket item.

## `kai.md`

### Step 3: community intake in the state report

- Any open PR or issue from an outside contributor that doesn't carry `community` yet: run community intake on it (step 4, "Community intake"). Also re-check each open PR that still carries `needs-ticket` for an issue reference added since intake (a later author comment or commit). If one now references an issue, apply step 4's lane-collision rule to it. Leave `needs-ticket` on either way; removing it isn't Kai's.

### Ticket triage, labeling, and lane assignment

*The bullets that belonged to this list had ended up after the lane-collision rule. They are back under step 4, and the triage and community-intake paragraphs are now their own sections.*

- Ticket triage, labeling, and **lane assignment**. If the dev-team is active (`.claude/worktrees/ash` and `.claude/worktrees/jay` exist), also check which lane is idle before labeling the next ticket: a Dev slot is idle if its worktree is on `team/<name>` rather than a ticket branch, or equivalently if no open PR's branch has `<name>` as its second `/`-separated segment (`gh pr list --state open --json headRefName --jq '[.[] | select((.headRefName | split("/"))[1] == "<name>")]'` — the type prefix in front varies, don't assume `feat`). Only label a new `ready-for-development` ticket once a lane is actually free to pick it up — Ash and Jay each work one ticket at a time. To actually assign a ticket to a specific lane's automated pickup, pair `ready-for-development` with the matching lane label (`lane-a` for Ash, `lane-b` for Jay) — `dev.md`'s pickup query filters on both, so a ticket labeled without its lane tag won't be picked up, and pre-queuing both lanes' next tickets at once is safe (each lane only ever sees its own).

### Pair `good first issue` with on-deck RFD tickets that are genuinely beginner-suitable

**Pair `good first issue` with on-deck RFD tickets that are genuinely beginner-suitable.** The repo has the standard GitHub `good first issue` label defined but it went unused until 2026-09-16 (first applied to #724). When labeling a well-scoped, self-contained backlog item as on-deck RFD (no lane, per above), also add `good first issue` if it's low-risk, mechanical, and doesn't require a design judgment call — e.g. a handful of explicit, line-numbered cleanups in one file, not a ticket that says "needs a design pass" or spans many call sites. Don't apply it to a lane-labeled ticket (those are claimed by Ash/Jay's automated pickup, not open for outside contribution) or to anything requiring undocumented codebase context to scope correctly.

### `good first issue` and a lane label (`lane-a`/`lane-b`) are mutually exclusive — never let a ticket carry both

**`good first issue` and a lane label (`lane-a`/`lane-b`) are mutually exclusive — never let a ticket carry both.** They're opposite signals: `good first issue` invites outside contribution, a lane label reserves the ticket for that lane's automated pickup. A ticket carrying both is a bug the moment you see it — fix on sight rather than re-deriving from context: if a contributor already claimed it, strip the lane label and pick the lane's actual next-in-order ticket fresh; otherwise drop `good first issue`. Check both directions before applying either label, and again as a pre-flight step when launching a lane (`make lane-a`), since a prior session's mislabel can sit stale in the queue undetected until the lane starts pulling from it. See Retro for the incident that surfaced this (#724).

### A role-routed label (`joy`/`bob`/`aziz`) and a version label are not mutually exclusive — don't let one imp…

**A role-routed label (`joy`/`bob`/`aziz`) and a version label are not mutually exclusive — don't let one imply the absence of the other.** They answer different questions: who scopes/does the work, versus whether a release actually depends on it landing. Apply the same release-gate test used for every other ticket: does the *next* targeted release actually need this to ship cleanly? If yes — e.g. a release-process fix Bob owns that the next `/release` run would visibly break without — it gets the version label alongside the person label. If the work is genuinely open-ended with no release tie, it stays version-less regardless of who it's routed to. See Retro for the incident that surfaced this (#602).

### Retro section intro

Friction Kai typically hits during coordination, and where it goes — see `/retro` for the general ticket-vs-command-decision split:

### Process friction across the team

*Changed, not just compressed: "fix … directly" predated the 2026-07-21 rule that every role-file edit goes through Bob, so the entry now says to PR it through Bob's gate.*

- **Process friction across the team** — another session's role file turned out ambiguous or wrong when actually followed (a stale worktree, a label race, a step that assumed state that wasn't there). Command decision: fix the relevant `.claude/team-roles/*.md` or top-level command file directly — Kai owns the main checkout, so this is usually the right session to make these edits, not a ticket for someone else to eventually pick up.

### `good first issue` and a lane label can silently coexist if a prior session's labeling slip isn't caught be…

*Dropped from the Retro list: the "`good first issue` and a lane label are mutually exclusive" rule under "Ticket triage and labeling" carries it.*

- **`good first issue` and a lane label can silently coexist if a prior session's labeling slip isn't caught before a lane launches.** Confirmed 2026-09-20 on #724 — it carried `lane-a` + `good first issue` + `ready-for-development` simultaneously, and a community contributor legitimately claimed it via the bare `good first issue`/RFD signal while it was also sitting in Ash's automated queue. Resolution: the human claim wins. Rule and pre-flight check now spelled out above.

### The docs/roadmap.md direct-push allowance doesn't generalize

- **The docs/roadmap.md direct-push allowance doesn't generalize** — "small and reversible" is a description of that one specific case, not a standing test for bypassing PR review elsewhere. Confirmed 2026-08-06: stretched it to a `uv.lock` fix by analogy, which skipped `ci.yml` entirely (it never triggers on a direct push to `develop`). Hard boundary now spelled out in `merge-pr.md` step 8 — read it there rather than re-deriving from "this feels small" in the moment.

### A role-routed label isn't a version-label exemption

*Dropped from the Retro list: folded into the role-routed-label rule under "Ticket triage and labeling".*

- **A role-routed label isn't a version-label exemption** — a past instance of a role-routed ticket correctly staying version-less (e.g. #376–#379/#397 in the roadmap-planning memory) got over-generalized into "role-routed tickets don't get version labels," full stop. Confirmed wrong 2026-08-16 on #602, which needed both `bob` and `v0.9`. The release-gate test above (in the ticket-triage section) is the actual rule; a memory entry recording one past outcome is not itself the rule.

### "Triage" means every item gets a real disposition — don't invent an exempt bucket on your own authority

- **"Triage" means every item gets a real disposition — don't invent an exempt bucket on your own authority.** 2026-09-11: asked to triage 60 unscheduled `backlog` issues (open-issue growth was running ~2:1 against closures), first proposed *pruning* some as low-value — user pushed back ("why wouldn't we queue those up to get fixed?"). Corrected to version-labeling all of them into real tiers, but then narrowed scope a second time by carving out net-new-feature "wishlist" issues as permanently exempt from versioning, reasoning they were "deliberately unscheduled Tier 4" — user pushed back again ("I really don't understand why these aren't included in the typical triage process... ignoring some class of ticket isn't appropriate"). Both misses were the same shape: deciding unilaterally that some slice of the batch didn't need a real answer, instead of giving every item an actual tier (even Tier 3/3.5 "not now but real" is a disposition; indefinite `backlog` with no version is not). When a triage pass is asked for, default to classifying 100% of the batch into a genuine version/tier — a "no version, deliberately parked forever" bucket needs the user's explicit sign-off before you create one, not your own read of prior roadmap convention.

### Bulk-editing via `gh` in a loop: never `for x in $VAR` with a space-separated string in zsh

- **Bulk-editing via `gh` in a loop: never `for x in $VAR` with a space-separated string in zsh.** 2026-09-11, the same triage pass: built a space-separated issue-number list in a shell variable, then looped `for n in $V091; do gh issue edit $n ...; done`. Zsh doesn't word-split an unquoted parameter expansion by default (unlike bash) — the loop ran exactly once with `$n` bound to the *entire string*, and `gh issue edit` failed with "invalid issue format" naming the whole blob. Silent-ish failure mode: it errors instead of hanging, but it's easy to misread as "one bad issue number" rather than "the loop never actually iterated." Fix: list the literal numbers directly in the `for` loop (`for n in 131 132 134 ...; do`) rather than through an intermediate variable, or use a bash array (`arr=(131 132 134); for n in "${arr[@]}"`) if the list needs to be built programmatically.

## `bob.md`

### Why this role exists

Every role here has standing permission to edit its own process file as it learns (`/retro`'s "command decision" path) — deliberately, since continuous self-correction from real friction beats a static prompt nobody revisits. But nothing was checking the *prompt-craft* quality of those self-edits — only whether the diff was small and about process rather than product code. That gap let a single conversational grant in `qa.md` harden, through soft wording, into a standing exception that two later sessions each stretched further before the user called a full stop and it was removed outright (full incident and reasoning: `docs/decisions/decision-prompt-qa-role.md`). The defect wasn't the underlying judgment calls — it was the wording: a scoped, one-time permission got written down loosely enough that a future session under time pressure could plausibly read it as a general license. Bob exists to catch that category before it lands, not after a second incident forces a retraction.

### Redundancy and bloat

4. **Redundancy and bloat.** A new retro entry that restates a rule already covered elsewhere (check the file's own existing Retro entries and sibling role files before accepting a new one), or one that keeps a full incident narrative live in a prompt that gets loaded every session when only the durable rule and its trigger condition need to stay. Compress to: the rule, why (one line, and only if it changes how a future edge case should be judged), and where it applies. Move genuinely historical detail to a decision doc (`docs/decisions/`) and leave the role file with just a pointer.

### Cross-file contradiction or duplication

5. **Cross-file contradiction or duplication.** The same paragraph copied verbatim across two files (seen already: the retired 2026-07-18 direct-push grant lived identically in both `dev.md` and `qa.md`) drifts the moment one copy gets edited and the other doesn't. Point duplicated process language at one canonical location instead.

### Memory-vs-prompt drift: the dropped-nuance example

- The edit's new wording drops a nuance an existing memory already carries (PR #456: moving `qa.md`'s reconnect-check into `qa-kickoff.md` silently dropped the `ToolSearch`-staleness caveat that a memory entry also tracked). Treat this as a check-4 finding — request the nuance folded back into the command's own wording, not left to live only in memory.

### Factual/technical claims about tool or CLI behavior

7. **Factual/technical claims about tool or CLI behavior.** A sentence asserting what a command, API, or tool actually does ("this argument targets exactly one server," "this rules out failure mode X") is a claim, not just phrasing — verify it before approving, the same way this repo's own convention expects "confirmed live" before landing a mechanism claim as fact (see `CLAUDE.md`'s regression-check example). This matters most inside a "send verbatim" instruction block a session pastes and runs unmodified, since an unverified claim there ships as an operational command real users execute, not just documentation. If the claim can't be verified from existing repo precedent, official docs, or a cited live test, ask the author — or the user directly — to confirm it live before merging, rather than trusting the PR description's own reasoning.

### Tool docstrings: scope (#397)

Resolved 2026-07-26, issue #397: tool docstrings and parameter descriptions are prompts too — the calling LLM reads them to decide whether and how to invoke a tool, same category as the files above, so they're in scope for the same checks. But the review *mechanics* differ from team-process files: it's an async sweep, not a merge gate. A PR touching `docs/tools.md` merges normally on `qa-approved` alone; Bob sweeps merged history touching that file and files a fix ticket for anything that needs correcting. In scope: any docstring/parameter-description edit, new or existing tool — not just new tool sections. Rationale for the async-not-blocking split: `docs/decisions/decision-prompt-qa-role.md`.

### Sweep cadence: release-anchored

**Cadence: release-anchored, not a fixed interval.** Run the sweep right before or alongside Aziz's release QA pass, using the same git-log-since-last-tag pattern `aziz.md` step 1 already uses: `git log v<last-stable>..origin/develop --oneline -- docs/tools.md` to enumerate every commit touching the file since the last stable tag, then review those. Chosen over a calendar interval (e.g. "every two weeks") because a release tag is a checkpoint that already exists and gets hit regardless of whether anyone remembers to schedule Bob separately — a time-based cadence has no such anchor and is the kind of thing that silently stops happening once the post-launch momentum of whatever prompted it passes.

### Sweep log: start from the last recorded SHA

**Record where each sweep ends, and start the next one from there — not from the tag.** A release cycle can span several sweeps (the trigger is "before each release QA pass," and `develop` accumulates many pass-prep cycles between stable tags). `v<last-stable>..origin/develop` over-scopes the moment a sweep has already run mid-cycle: it re-surfaces every commit the previous sweep already cleared, with no recorded boundary to subtract, so the next session re-derives that boundary by hand from ticket-filing dates (the 2026-09-03 sweep had to). Fix: each sweep appends an entry to the log below — date, last commit SHA reviewed, tickets filed. The next sweep's range is `<that SHA>..origin/develop` unless a stable release shipped in between (which advances the tag and makes tag and last-SHA equivalent again).

### Process step 1: the authoring role initiates

1. **The authoring role initiates.** Same session, same moment it would previously have pushed directly: commit the edit on a short-lived branch off `develop` (`doc/<role>/retro-<date>`, matching the pattern already in use — see `doc/joy/retro-2026-07-19`, PR #383), open a PR. This preserves the property the user wants most: each participant commits what it learned, in its own words, right when it's fresh — Bob's review doesn't block that capture, only the merge.

### Process step 2: no fast path

2. **Every edit needs `prompt-qa-approved`, no fast path.** An earlier version of this process exempted mechanical fixes (typos, stale references, renumbering) from review. Retired 2026-07-21, per direct user instruction: from here on, *any* change to `.claude/team-roles/*.md`, `.claude/commands/*.md`, or root `CLAUDE.md` goes through Bob before merge, including edits with no permission/scope content at all. This trades a small amount of latency on trivial fixes for a simpler, unconditional rule — "did Bob look at it" is a boolean anyone can check on any PR, where "is this edit mechanical enough to skip review" was itself a judgment call that could be gotten wrong the same way the original QA-inline-fix exception was.

### Process step 3: Bob reviews when next invoked

3. **Bob reviews when next invoked** — ad hoc, or at whatever cadence Kai sets (e.g. sweeping open `doc/*/retro-*` PRs during normal orchestration, the way Aziz sweeps merged PRs at release time). One point in the cycle where the sweep is not optional: **before a release QA pass starts**, per `aziz.md`'s "prompt-file changes to the pass itself must be settled" precondition. A change to the pass's own procedure (`aziz.md`, `qa.md`, `verify-pr.md`, `release.md`) has to land *before* the pass so that pass runs on it and exercises it in situ — merged right after, it sits untested until the next release. This is deliberately not real-time otherwise: it's the release valve — a session that hits friction mid-work isn't blocked waiting on a live Bob review, the commit just sits as an open PR until someone gets to it. Apply the checks above; either add the `prompt-qa-approved` label or comment on the PR with the specific rewrite requested (not just "too loose" — propose the tightened wording). Applying the label must come with a PR comment naming which checks were applied and what was found — a bare label with no accompanying comment is itself a signal to distrust, not evidence of review, since GitHub's attribution can't prove who actually applied it (see Retro). If Bob is the edit's own author, he doesn't self-apply the label — there's no sixth role positioned to check Bob's own prompt-craft calls the way Bob checks everyone else's. Instead, Bob posts the same self-assessment comment he'd write for anyone else's PR — applying the checks above to his own edit, in writing — and the user reviews that comment and applies `prompt-qa-approved` themselves. This isn't asking for sign-off in live conversation: the user can't practically re-derive Bob's review process turn by turn on demand, so what actually gets reviewed is the same durable, checkable artifact every other approved PR now requires — not a conversational nod that would otherwise get reported as more independently verified than it actually was.

### Process step 4: Bob merges

4. **Bob merges once he's applied `prompt-qa-approved`** — a separate track from product PRs, not the split originally described in decision 2 of `decision-prompt-qa-role.md`. Kai's merge authority stays scoped to `qa-approved` agent/product-code PRs, tested via the main checkout's live MCP access — team-process/prompt files never needed that, so there was no structural reason to route their merge through Kai either. Bob uses the same `/merge-pr` mechanics already documented there (`--admin` squash-merge, worktree cleanup) — nothing in that skill is Kai-specific; its cleanup step already handles Bob's own persistent worktree slot by name. Per direct user instruction, 2026-07-21.

### Retirement of the direct-push grant

This retires the 2026-07-18 direct-push-to-`develop` grant previously in `dev.md`/`qa.md` — that path let team-process edits skip review entirely, which is the same class of gap that let the QA inline-fix exception harden unreviewed. The PR/label/merge machinery already exists for product code; this reuses it rather than inventing something new.

### Bob has no peer reviewer for his own self-authored edits — the self-improvement process assumed the author…

*Dropped from the Retro list: process step 3's self-authored-edit sub-bullet carries the rule.*

- **Bob has no peer reviewer for his own self-authored edits — the self-improvement process assumed the author and Bob were always different roles.** Surfaced by the user directly on Bob's first PR (#394, 2026-07-21): the fix itself was genuinely mechanical (branch-naming spelling, a stale pointer) and correctly used the fast path, but the general question — what happens when Bob authors a *non-mechanical* edit — was unaddressed, and self-applying `prompt-qa-approved` to his own PR would be exactly the self-review defect this whole gate exists to prevent. Fixed in "The self-improvement process" step 3 above: Bob doesn't self-label a self-authored edit — he posts a self-assessment comment against the checks above instead, and the user reviews it and applies the label. (Refined 2026-07-21, same day: the user flagged that asking for conversational sign-off wasn't something they could practically replicate as an independent check each time it happened, so the artifact under review is now the same self-assessment comment every other PR requires — not a live back-and-forth that would get reported as more independently verified than it actually was.)

### A pre-existing label on a PR isn't proof it was reviewed — Bob almost trusted the git actor field as evidence

*Dropped from the Retro list: process step 3's label-comment sub-bullet carries the rule.*

- **A pre-existing label on a PR isn't proof it was reviewed — Bob almost trusted the git actor field as evidence.** While reviewing PR #393 (2026-07-21), Bob found it already carried `prompt-qa-approved` and initially reported, as a confirmed fact, that the label reflected the authoring session self-applying it rather than a real review, based on the GitHub timeline showing `labeled by khuisman` — that field can't distinguish the user from any session acting under the user's own credentials, and the actual origin was only known because the user said so directly, not because Bob verified it. Full writeup: `decision-prompt-qa-role.md`'s label-attribution addendum. Fixed going forward: applying `prompt-qa-approved` now requires a PR comment naming what was checked (step 3 above) — a label's mere presence is never sufficient grounds for Bob, or anyone, to treat a PR as already reviewed.

### Squash-merging one PR in a stacked-branch chain makes the next PR in the stack show `CONFLICTING`, even whe…

- **Squash-merging one PR in a stacked-branch chain makes the next PR in the stack show `CONFLICTING`, even when the actual content is identical.** Merging #394 flipped #395's `mergeable` from clean to `CONFLICTING` against the same content: the squash commit landing on `develop` has a different history than the original commit already sitting in #395's branch, and this repo's paragraphs are single unwrapped lines, so any two edits anywhere in the same conceptual paragraph collide as the same git line regardless of how far apart the actual wording changes are. A plain `git rebase origin/develop` doesn't fix it — it tries to replay the already-landed commit's diff again and hits the same collision. Fix: `git rebase --onto origin/develop <tip-of-the-now-merged-branch> <next-branch-in-the-stack>`, which excludes the already-squashed commits from the replay entirely and only reapplies the next branch's own new commits. Confirmed live merging #394 → #395 → #396, 2026-07-21.

### Bob merged PRs directly tonight (#394–#396), first recorded here as a one-off exception — corrected minutes…

- **Bob merged PRs directly tonight (#394–#396), first recorded here as a one-off exception — corrected minutes later when the user confirmed it should be standing instead.** The user clarified they want a permanent, separate merge track: Bob owns review, label, and merge for team-process/prompt files; Kai's merge authority stays scoped to agent/product-code PRs (see step 4 above, `kai.md`, and `decision-prompt-qa-role.md`'s merge-authority addendum). Left in as its own lesson: describing something as a one-off exception is itself a judgment call that can be wrong just as easily as an over-broad permission grant — the fix wasn't reverting the merge, it was writing the actual boundary down explicitly instead of leaving it as "Bob asked, user said yes" each time.

### Holding a PR for live verification of an unconfirmed technical claim is correct even when the claim turns o…

*Dropped from the Retro list: folded into check 7.*

- **Holding a PR for live verification of an unconfirmed technical claim is correct even when the claim turns out true — confirmed on PR #468, 2026-07-30.** The PR changed `qa-kickoff.md`'s reconnect command to `/mcp reconnect mcp-gee-sweet-<name>` and asserted this "rules out" the old wrong-server-reconnect bug; nothing in the repo's history used that argument form before, and neither official Claude Code docs nor `claude mcp --help` (a separate CLI namespace) could confirm it. Held the PR rather than approving on the strength of the description's own reasoning; the user then confirmed live that `/mcp reconnect mcp-gee-sweet-<name>` is exactly what they run for Sky's lane — the claim was right, but that was only known after asking, not before. Formalized as check 7 above.

### "At his own cadence" meant no cadence — the docstring sweep ran once, then silently stopped

*Dropped from the Retro list: the docstring-sweep cadence paragraph carries the rule.*

- **"At his own cadence" meant no cadence — the docstring sweep ran once, then silently stopped.** The user asked directly on 2026-08-10 when the last `docs/tools.md` sweep happened and what the cadence should be; the answer was 2026-07-27 (issues #436/#437, filed the same day the async-sweep process itself landed) and nothing since — an undefined cadence quietly defaulted to "whenever the thing that prompted it is still fresh in mind," which stops holding the moment that fades. Fixed by anchoring the sweep to release cadence instead of a calendar interval, reusing the git-log-since-last-tag checkpoint `aziz.md` step 1 already has — see the "Tool docstrings" section above.

### Memory-only fixes don't reliably stick for repeatable workflow steps — PR #456 needed a command file, not a…

- **Memory-only fixes don't reliably stick for repeatable workflow steps — PR #456 needed a command file, not a second memory entry.** The user pointed out directly that the underlying friction behind #456/#461/#463 was the same shape each time: QA's `/mcp reconnect`+`/code-review` batching had already been "fixed" twice via memory alone, and each time a later session reverted to the old, wrong behavior anyway — memory is retrieved heuristically and doesn't reliably override whatever the loaded prompt file already says, so a memory-only fix for something a command file governs is a fix that can silently stop holding. Two changes followed: check 6 above (memory-vs-prompt drift, so Bob catches it when a command edit and an existing memory disagree or duplicate), and a new `CLAUDE.md` note ("Procedural feedback → the governing command file, not memory") instructing every role to route a repeatable-workflow correction into the command file it's about, not into memory, the moment the feedback lands — not deferred to a `/retro` pass. `retro.md` cross-references the same note so the distinction isn't `/retro`-exclusive.
