# Decision: A Scoped, Opt-In pytest Harness for the Local-Filesystem QA Gap

**Date:** 2026-08-22
**Issue:** [#50](https://github.com/khuisman/mcp-gee-sweet/issues/50)

## Background

`docs/qa/tests/drive_transfer.md` carries ~27 test cases tagged `⚠️ local-filesystem` — every case exercising `upload_local_file`/`upload_local_folder`, `download_file`/`download_folder`, and `sync_folder`. Per `docs/qa/README.md`, these "need file paths accessible to the MCP server process" and "cannot run in an AI-session QA run" — the human-led conductor flow (`docs/qa/run.md`) that [`decision-testing.md`](decision-testing.md) chose as the project's primary QA method has no guaranteed way to place a fixture file on the same host as the MCP server process it's driving (that flow is written for "a Claude session that has the mcp-gee-sweet MCP server connected" generically — nothing about it guarantees the client and server share a filesystem, e.g. a Docker-hosted SSE server driven from a separate machine). These cases are standing, permanent skips, not "pending."

Issue #50 asked whether a `pytest`-driven subprocess harness — start `uv run mcp-gee-sweet`, issue calls, check results — could cover them without manual intervention.

## What this does *not* reopen

`decision-testing.md` rejected "Option A: automated integration tests against real Google APIs" as the project's *primary* QA method, for reasons that still hold at full-suite scale: dedicated CI secrets and fixture maintenance, quota/rate-limit flakiness gating every PR, and a real cleanup burden across four Google APIs. This decision does not revisit that verdict — human-led verification (now Playwright-assisted for visual checks) stays primary for the ~250+ other test cases that *can* run that way.

What's different here: the local-filesystem cases aren't a case where Option A's automation is merely *nicer* than the chosen Option C — Option C is structurally unable to reach them at all, for any human, regardless of diligence. That's a gap in the chosen method's own coverage, not a case for re-litigating the method.

## Investigation findings

1. **The real constraint is broader than "local filesystem."** `spreadsheet_lifespan` (`auth.py`) authenticates *eagerly on server startup*, before any tool is called — so launching the server subprocess at all requires live, valid Google credentials, for literally any tool, not just the local-filesystem ones. A harness that can start the server can therefore also exercise the ~250 other tools; nothing scopes it to only the gap it was built for.
2. **This repo already has every piece needed, confirmed live.** The team-role `.mcp.json` config (`scripts/setup_team.sh`) launches each role's own server exactly this way — `uv run --directory <worktree> mcp-gee-sweet` over stdio, with `AUTH_METHOD`/`CREDENTIALS_PATH`/`TOKEN_PATH` (or `SERVICE_ACCOUNT_PATH`) pointing at per-worktree credential files. `scripts/oauth_setup.py` already reconstructs a valid `token.json` from `GOOGLE_OAUTH_REFRESH_TOKEN` with no browser flow, for exactly the "no manual intervention" requirement this issue asks about. Building the harness meant reusing this plumbing, not inventing new credential machinery.
3. **The `mcp` SDK (v2.0.0, already a dependency post-#642) has a first-class stdio client** — `mcp.client.stdio.stdio_client` + `mcp.ClientSession` — sufficient to drive the real subprocess and read `CallToolResult.structured_content` directly. No custom transport or protocol code was needed.
4. **CI has no live credentials and this stays true.** `.github/workflows/ci.yml` runs `uv run python -m pytest --tb=short` with no Google secrets configured. A subprocess harness fixes the *filesystem* barrier, not the *credentials* barrier — those are separate problems. Wiring live credentials into CI (via `GOOGLE_OAUTH_REFRESH_TOKEN` as a repo secret, the same mechanism `oauth_setup.py` already supports) is a distinct decision with its own cost/quota/secret-rotation tradeoffs, deliberately left open here rather than decided as a side effect of this ticket — see Scope below.

## Decision

Add `tests/integration/` — a `pytest` package, opt-in via `MCP_GEE_SWEET_LIVE_TESTS=1`, that:

- Spawns the real `mcp-gee-sweet` server as a subprocess over stdio using `mcp.client.stdio.stdio_client` + `ClientSession`.
- Auto-discovers credentials the same way `.mcp.json` already does (repo-root `credentials.json`+`token.json`, falling back to `service_account.json`), or honors an already-exported `AUTH_METHOD` so a developer's own setup isn't second-guessed.
- Reuses the existing `TEST_FOLDER_ID` QA fixture (root `.env`, `docs/qa/setup.md`) and creates a throwaway child folder per test session, deleted permanently on teardown — same fixture-pollution discipline `docs/qa/run.md` already documents for the manual flow.
- **Skips cleanly (not a failure) whenever the opt-in env var or credentials are absent** — verified live: the default `uv run python -m pytest` run (no env var set) collects and skips this package with zero live calls, so it's always safe to leave in `tests/` and it never affects the existing CI matrix as configured today.

This module lives under `tests/` (picked up by the existing `testpaths`) rather than a separate top-level directory, specifically *because* it self-skips safely — no `pyproject.toml`/CI wiring changes were needed to keep the default run green.

### Scope of this PR

Three representative tests prove the mechanism rather than porting all ~27 cases:

- `test_upload_local_file_round_trip` (covers the shape of TC-D93/94/97)
- `test_download_file_round_trip` (covers the shape of TC-D101/106)
- `test_sync_folder_upload` (covers the shape of TC-D113/117)

Each was run live against this repo's own QA fixture folder before this PR was opened (per this project's "verify a ticket's premise live" rule) — real subprocess, real Drive API calls, real cleanup.

**Not in scope, follow-up ticket:** `upload_local_folder`/`download_folder`, the `convert`/`convert_markdown` variants, `use_checksum`, `recursive`, and the various conflict/collision/error-path cases the remaining ~24 skipped QA cases cover. Each follows the identical pattern established here — no new mechanism needed, just more test functions.

**Explicitly deferred, needs a separate decision:** wiring `GOOGLE_OAUTH_REFRESH_TOKEN` into a GitHub Actions secret so this harness (or an expanded version of it) runs in CI rather than only ad hoc on a developer machine. That reopens exactly the secret-management and quota-flakiness tradeoffs `decision-testing.md` weighed for the full suite — worth deciding deliberately, not as a side effect of closing #50.

## What this means for the `⚠️ local-filesystem` QA tags

The tags stay. The human-led conductor flow in `docs/qa/run.md` still can't run these — that hasn't changed. `docs/qa/README.md` now cross-references this harness as the actual place this coverage lives, so a future reader doesn't read "always skipped" and stop looking.
