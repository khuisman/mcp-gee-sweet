# Decision: Human-Led Verification with Phased AI Trust

**Date:** 2026-05-13 (revised 2026-06-02)
**Snapshot commit:** [`d94f81ab`](https://github.com/khuisman/mcp-gee-sweet/commit/d94f81ab9e313d8a3cc4c46d141777e4e8069c14) — QA framework as it existed when this decision was first made

> This is a living decision record. The original decision (2026-05-13) established the QA framework structure. This revision corrects a mischaracterisation of Option C and extends the decision with a phased evolution plan toward a hybrid human + AI verification system.

---

## Background

As the tool count grew past 30 across Sheets, Drive, Docs, and Calendar, the question of how to verify correctness became real. Every tool is ultimately a wrapper around a live Google API — the interesting failure modes are things like malformed A1 notation, wrong MIME type handling, cache staleness after a write, and API edge cases that only surface against real data. The question was how to catch those reliably without building a full CI integration harness.

Two categories of testing were already in place at this point:

- **Unit tests** (`tests/test_tools.py`) — cover helpers, HTML conversion, tool filtering, cache TTL/invalidation logic, and A1 notation parsing. These don't require credentials and run in CI via `pytest`.
- **Ad hoc manual testing** — tools were being exercised during development by issuing prompts against a running server, but there was no structure, no repeatability, and no shared record of what had been checked.

The question was what to put in the gap between unit tests and shipping.

## Options Considered

### Option A: Automated integration tests against real Google APIs

Write `pytest` tests that authenticate with a service account, call tools against real Drive/Sheets/Calendar resources, and assert on responses.

**Pros:**
- Repeatable, runnable in CI
- Catches regressions automatically

**Cons:**
- Requires a dedicated Google test account, service account credentials stored in CI secrets, and a real Drive folder/spreadsheet/doc/calendar maintained as fixtures
- API rate limits and quota introduce test flakiness that has nothing to do with correctness
- Google Workspace APIs have no local equivalent — no sandbox, no emulator. "Integration test" means a real API call with real side effects
- Credential rotation, fixture drift, and quota exhaustion are ongoing maintenance costs
- Tests would need to clean up after themselves across Drive, Docs, Calendar, and Sheets — a substantial engineering surface

### Option B: Mocked unit tests for tool behavior

Mock the Google API clients and write unit tests that assert tools call the right methods with the right arguments.

**Pros:**
- No credentials, fast, runnable in CI

**Cons:**
- Tests the mock, not the API. The bugs that actually surface — wrong MIME type in an export, A1 notation that the Sheets API silently ignores, a Drive query that doesn't escape single quotes — are all behaviors of the real API, not of this project's code
- A mocked test that passes is not evidence that the tool works

### Option C: Human-led structured verification with AI assistance (chosen)

Write structured test cases as natural language prompts paired with explicit check lists. A human runs each prompt against the live MCP server and evaluates the response against the checks. Claude assists by presenting prompts, interpreting structured output, and carrying state between tests — but human judgment is the verification step. Results are recorded in a QA checklist (`docs/qa-checklist.md`) that a human signs off on.

> **Correction from original write-up:** The original description said "A Claude session evaluates the responses against the checks and saves a results report." That overstated AI autonomy. The intent was always human-driven: Claude surfaces the prompt and the checks, a person runs it and decides pass/fail.

**Pros:**
- Tests run against the real Google APIs with real credentials — the same conditions as production
- Natural language checks can express things that are hard to assert programmatically: "open the doc in a browser and verify the heading renders correctly", "confirm the file no longer appears in Drive UI"
- Claude can carry intermediate state between tests (e.g. a `permissionId` returned by one test used in the next), handle test ordering, and prompt the user before destructive operations
- Test cases are readable by anyone — no test framework knowledge required
- Tests are grouped by tool category (`read.md`, `write.md`, `sheets.md`, `drive.md`, `charts.md`, `infra.md`) so a human can run one category at a time
- The conductor prompt pattern makes a full suite run a single paste operation

**Cons:**
- Not automated — requires a human to initiate a run
- Not in CI — regressions aren't caught automatically on every commit
- Pass/fail judgment rests with the human; AI assistance introduces a question of how much to trust AI evaluation

## Decision

**Use human-led structured verification as the primary QA method for tool correctness.** Unit tests remain in CI for logic that doesn't require API calls (helpers, caching, filtering). Integration tests against real APIs are deferred — the cost/benefit doesn't make sense at current scale, and the structured human-led approach exercises real APIs with lower setup overhead.

The framework consists of:

- **`docs/qa/tests/*.md`** — one file per tool category, each test case a prompt + check list with a TC-prefixed identifier
- **`docs/qa/setup.md`** — one-time fixture setup (a real spreadsheet, doc, folder, and calendar in Drive)
- **`docs/qa/run.md`** — the conductor prompt; paste into a Claude session with the server connected to run the full suite
- **`docs/qa-checklist.md`** — the attestation document; each TC is a checkbox that someone signs off on having run

## Phased Evolution: Toward Hybrid Human + AI Trust

The current framework works but leaves an open question: how much should AI evaluation be trusted, and how do we know when a previously-verified test still holds? The following phases describe the planned evolution.

### Phase 1 — Run the suite; learn what AI verification actually produces (current)

Run the existing test suite with AI assistance evaluating results alongside the human. Goal: discover what works well and what doesn't. Specific things to learn:

- Where does AI evaluation agree with human judgment? Where does it diverge?
- Which test categories are well-suited to AI evaluation (structured output, deterministic checks) vs. require human eyes (rendering, Drive UI state)?
- Are there checks that are currently underspecified — ambiguous enough that AI and human reach different verdicts?
- What fixture assumptions break or drift in practice?

Findings from this phase inform whether and how much AI evaluation can be trusted in Phase 2.

### Phase 2 — Track human approval through structured sign-off (next)

Build a sign-off record per test case that captures: who approved, when, at what commit. The checklist (`docs/qa-checklist.md`) becomes the source of truth for approval state.

Rules:
- **New test cases** always require human execution and sign-off before AI-only re-runs are permitted.
- **Sign-off record** includes: TC identifier, approver, date, commit SHA of the tool file at time of approval, fixture version.
- **AI-only re-runs** are permitted only for tests that have a human sign-off on record.

This phase doesn't change how tests run — it adds the tracking layer on top of the existing workflow.

### Phase 3 — Invalidate human approval on stated conditions (future)

Once sign-off tracking exists, introduce rules that automatically mark a previously-approved TC as requiring re-verification:

- **Tool file changed** — a commit touches the source file for the tool under test (e.g. `src/mcp_gee_sweet/tools/read.py` changed → all TC-R## approvals invalidated)
- **Fixture mutated** — a destructive test ran and the fixture spreadsheet/doc/calendar was not reset (tracked via a fixture checksum or version marker in `fixtures.local.md`)
- **Explicit override** — a human marks a TC as needing re-verification (e.g. after an API behavior change or a known regression)

Tests invalidated by Phase 3 rules drop back to requiring human re-approval before AI-only re-runs resume. This creates a ratchet: verified tests stay verified until there's a stated reason they might not be.

---

## When to Re-evaluate the Framework Itself

This decision should be revisited if:

- The project gains contributors who need a way to verify correctness without a Google account configured
- A CI-friendly Google API sandbox or emulator becomes available
- Repeated regressions in a specific area make the manual cycle too slow to catch them
- Phase 1 findings show AI evaluation is unreliable enough to make Phase 2/3 not worth building
