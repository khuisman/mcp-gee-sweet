# Decision: AI-Directed Manual Verification over Automated Integration Tests

**Date:** 2026-05-13
**Snapshot commit:** [`d94f81ab`](https://github.com/khuisman/mcp-gee-sweet/commit/d94f81ab9e313d8a3cc4c46d141777e4e8069c14) — QA framework as it existed when this decision was made

> This is a point-in-time record. It captures context, alternatives, and reasoning as they were understood on the date above — not the current state of the project.

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

### Option C: AI-directed manual verification (chosen)

Write structured test cases as natural language prompts paired with explicit check lists. A Claude session connected to the live MCP server executes the prompts, evaluates the responses against the checks, and saves a results report. The same AI that uses the tools verifies them.

**Pros:**
- Tests run against the real Google APIs with real credentials — the same conditions as production
- Natural language checks can express things that are hard to assert programmatically: "open the doc in a browser and verify the heading renders correctly", "confirm the file no longer appears in Drive UI"
- Claude can carry intermediate state between tests (e.g. a `permissionId` returned by one test used in the next), handle test ordering, and ask the user before running destructive operations
- Test cases are readable by anyone — no test framework knowledge required
- The conductor prompt pattern makes a full suite run a single paste operation

**Cons:**
- Not automated — requires a human to initiate a run
- Not in CI — regressions aren't caught automatically on every commit
- Results are only as reliable as Claude's evaluation of the checks

## Decision

**Use AI-directed manual verification as the primary QA method for tool correctness.** Unit tests remain in CI for logic that doesn't require API calls (helpers, caching, filtering). Integration tests against real APIs are deferred — the cost/benefit doesn't make sense at current scale, and the AI-directed approach exercises real APIs with lower setup overhead.

The framework consists of:

- **`docs/qa/tests/*.md`** — one file per tool category, each test case a prompt + check list with a TC-prefixed identifier
- **`docs/qa/setup.md`** — one-time fixture setup (a real spreadsheet, doc, folder, and calendar in Drive)
- **`docs/qa/run.md`** — the conductor prompt; paste into a Claude session with the server connected to run the full suite
- **`docs/qa-checklist.md`** — the attestation document; each TC is a checkbox that someone signs off on having run

## When to Re-evaluate

This decision should be revisited if:

- The project gains contributors who need a way to verify correctness without a Google account configured
- A CI-friendly Google API sandbox or emulator becomes available
- Repeated regressions in a specific area make the manual cycle too slow to catch them
