# Contributing to mcp-gee-sweet

## Quick orientation

- `src/mcp_gee_sweet/tools/` — one file per tool category (`sheets/`, `drive/`, `docs/`, `calendar.py`, `cache.py`)
- `docs/qa/tests/` — one QA test file per category, matching the tool files
- `docs/decisions/` — ADRs (why a design choice was made); `docs/design.md` — living principles doc (how the project works today)
- `docs/qa/operations.yaml` — machine-readable QA operations manifest (see [QA operations](#qa-operations))
- `docs/tools.md` and the "Tool filtering" section of `docs/configuration.md` are **generated** from tool docstrings by `scripts/gen_tool_docs.py` — never hand-edit their tool tables (see [Adding a new tool](#adding-a-new-tool))

---

## First-time setup

### 1. Clone and install

```bash
git clone https://github.com/khuisman/mcp-gee-sweet.git
cd mcp-gee-sweet
uv sync
make install-hooks
```

### 2. Configure auth and environment

Two ways to supply configuration — pick whichever fits how you're running the server:

- **`src/mcp_gee_sweet/.env` file** — the server loads it at startup, so this works regardless of transport. Copy the template and fill in what you need:
  ```bash
  cp src/mcp_gee_sweet/.env.template src/mcp_gee_sweet/.env
  ```
- **Your MCP client's config directly** — if you're pointing your client at `uv run --directory /path/to/mcp-gee-sweet mcp-gee-sweet` (the README's stdio quick-start), you can set env vars in the client's `env` block instead, the same way the [MCP client config](https://khuisman.github.io/mcp-gee-sweet/latest/client-setup/) examples do. Many contributors find this a better day-to-day experience than maintaining a separate `.env` file — client config takes precedence over `.env` either way.

At minimum you need one auth method and a Drive folder. Full details on all four methods (including GCP setup steps) are in [Authentication](https://khuisman.github.io/mcp-gee-sweet/latest/auth/); the full environment variable reference is in [Configuration](https://khuisman.github.io/mcp-gee-sweet/latest/configuration/).

#### Choosing an auth method

| Method | Setup | QA coverage | Best for |
|---|---|---|---|
| **Service account** | Place `service_account.json` in repo root; share your Drive folder with the service account email | ~85% of tests — Drive file creation/copy/upload skipped (service accounts have no Drive storage quota) | Headless server deployment; most development work |
| **OAuth** | Download OAuth client JSON; set `CREDENTIALS_PATH`; browser login on first run | ~95% of tests — all Drive create/copy/upload tests eligible | Full QA runs; local development with a personal Drive |
| **ADC** | `gcloud auth application-default login` | Same as OAuth | Google Cloud environments; local dev with gcloud installed |

**For contributors:** service account covers all read, write, sheets, and chart tests. If you're adding or fixing Drive create/copy/upload tools, OAuth or ADC gives full coverage. Set `QA_AUTH_METHOD` in `.env` to match — the QA conductor will warn you which tests will be skipped before each run.

The most common setup for local development:

```
SERVICE_ACCOUNT_PATH=./service_account.json
DRIVE_FOLDER_ID=<your folder id>
QA_AUTH_METHOD=service_account
```

**If you're testing against your personal Google account (OAuth/ADC),** QA runs create real calendar events, docs, and sheets in your live Drive/Calendar. Use a dedicated QA Drive folder and, if possible, a separate test calendar rather than your primary one — it makes cleanup trivial and keeps test artifacts from mixing with real data. Run `reset_fixtures` (below) after destructive test runs.

### 3. Set up QA fixtures

Give your AI assistant a writable Drive folder and tell it to set up your fixtures:

> "Read `docs/qa/operations.yaml` and run the `setup_fixtures` operation. My Drive folder is at https://drive.google.com/drive/folders/YOUR_FOLDER_ID"

The assistant will:
- List the folder contents
- Identify or ask you to create the fixture spreadsheet and doc
- Populate them with known fixture data
- Write `TEST_*` IDs to your `.env`

**If you are using service account auth:** the folder and both files must be shared with the service account email. Find it at `service_account.json` → `client_email`. The service account cannot access files in personal Drive unless explicitly shared — see [Authentication](https://khuisman.github.io/mcp-gee-sweet/latest/auth/) for the sharing steps.

### 4. Enable observability

Tool call debugging relies almost entirely on the access log, not print-statement debugging — turn it on before you start iterating on a tool:

```
DEBUG_LEVEL=DEBUG
LOG_FILE=/tmp/mcp-gee-sweet.log
ACCESS_LOG_FILE=/tmp/mcp-gee-sweet-access.log   # optional, access-only view
```

Every tool call emits one line to the access log:

```
2026-06-23 22:45:19 INFO mcp_gee_sweet.access "127.0.0.1" "claude-code/1.x" "TOOL list_recent_files" 200 0.475s
```

- `make dev-logs` — tail `LOG_FILE` (stdio; stderr is dropped by the MCP host, so this is the only way to see server output)
- `make logs` — tail Docker container logs directly (SSE; `DEBUG_LEVEL=DEBUG` is already the Docker Compose default, no `.env` change needed)
- `make access-logs` — tail `ACCESS_LOG_FILE` only, if set

Full details on log levels and file routing: [Configuration → Logging](https://khuisman.github.io/mcp-gee-sweet/latest/configuration/).

### 5. Run the server

```bash
make start   # Docker (recommended)
# or
uv run mcp-gee-sweet --transport sse
```

---

## QA operations

All QA workflows are defined in [`docs/qa/operations.yaml`](docs/qa/operations.yaml). Any AI assistant that can read files can parse this manifest and offer the operations as a menu.

**To see what's available:**
> "Read `docs/qa/operations.yaml` and tell me what QA operations are available and which ones I can run right now."

The assistant will check preconditions (`.env` keys, server connectivity) and tell you which operations are ready.

| Operation | When to use |
|---|---|
| `setup_fixtures` | First time; or after losing your `.env` |
| `reset_fixtures` | After destructive tests; any time fixture state is uncertain |
| `run_suite` | Full regression run across all tool categories |
| `run_group` | Focused run after changing a specific tool category |
| `human_confirmation` | Step-by-step with human sign-off on each result |

### Running a group

> "Read `docs/qa/operations.yaml` and run the `run_group` operation for `sheets`."

Available groups: `read`, `write`, `sheets`, `drive`, `charts`, `calendar`, `infra`

### Visual verification with Playwright

The primary QA method today is `run_suite`/`run_group` with Playwright-backed visual verification: test cases tagged **Playwright: required** in their test file get a real browser check via the Playwright MCP after the tool call, confirming what the API response claims actually happened in Drive/Docs/Sheets/Calendar. See [`docs/qa/run.md`](docs/qa/run.md) for how the conductor drives this.

`human_confirmation` (stepping through tests one at a time with a human sign-off on each verdict) is also defined in `docs/qa/operations.yaml`, but isn't the current default — it's held in reserve for verification judgment calls that Playwright snapshots can't resolve on their own, which is likely to matter more once formatting/rendering-behavior work picks up. See [`docs/decisions/decision-testing.md`](docs/decisions/decision-testing.md) for the full rationale, including what changed since the original phased-trust plan.

---

## Adding a new tool

1. Add the implementation to the appropriate file in `src/mcp_gee_sweet/tools/`, with a docstring — `scripts/gen_tool_docs.py` fails the pre-commit hook if a registered tool has no docstring, since it's the sole source for the generated docs.
2. Add QA test cases to the matching file in `docs/qa/tests/` with the next sequential TC number.
3. Run `uv run python scripts/gen_tool_docs.py` (or just commit — the pre-commit hook runs it automatically) to regenerate `docs/tools.md` and the "Tool filtering" section of `docs/configuration.md`.
4. Run `run_group` for the affected category to verify.

Every new tool must have at least:
- A happy-path test case
- An error/edge-case test case
- The tool included in the `docs/qa-checklist.md` attestation
- The tool's happy-path TC added to the smoke suite in `docs/qa/runs/README.md`

See [Design Principles](https://khuisman.github.io/mcp-gee-sweet/latest/design/) for the tool inclusion criteria and composite tool rules.

---

## Development workflow

```bash
make test        # unit tests (no credentials needed)
make lint        # ruff linter + formatter
make dev-logs    # tail server log file (stdio; requires LOG_FILE)
make logs        # tail container logs (Docker/SSE)
make restart     # restart server after code changes, then restart your MCP client
```

Pre-commit hooks run `ruff` (and `scripts/gen_tool_docs.py` if tool files changed) on staged files. If a commit is blocked, fix the issue and commit again — don't skip hooks.

---

## Tracking work

Active tasks, defects, product decisions, and QA gaps are tracked in [GitHub Issues](https://github.com/khuisman/mcp-gee-sweet/issues). Labels in active use:

| Label | Used for |
|---|---|
| `defect` | Confirmed bugs — something isn't working |
| `documentation` | Improvements or additions to documentation |
| `decision-needed` | Observed behaviours that need a deliberate product or design decision |
| `qa` | Missing fixtures, test infrastructure plans, QA gaps |
| `infrastructure` | Build, CI, publishing, dev tooling |
| `enhancement` | New features from the roadmap tiers |
| `ready-for-development` | Scoped, actionable, no blocking decisions needed — ready to build |
| `backlog` | Tier 4 — nice to have, no assigned version |
| `v0.7`, `v0.8`, `v0.8.1`, `v0.9`, `v1.0`, `v1.1+` | Release/version targets — see `docs/roadmap.md` |

`docs/roadmap.md` is an orientation doc — feature ideas, tier definitions, and historical context. Open an issue when a feature is scheduled to be built; tag it `ready-for-development` once it's unblocked.

---

## Pull requests

This project has an opinionated roadmap and is maintained by one person. The direct path to a merged PR is a **bug fix with a clear reproduction**, or an **issue already labeled `ready-for-development`** (only maintainers can apply labels, so this is always a deliberate go-ahead, not a self-service queue). Broader feature ideas are welcome as issue discussions — they may get folded into the roadmap over time, but implementation is planned rather than crowd-sourced. If you're not sure which category your change falls into, open an issue first rather than a PR.

- One issue per PR — keep scope matched to what the issue actually asks for.
- Open a feature branch before pushing (`feat/`, `fix/`, `docs/` prefixes).
- Fill out the PR template: what changed and why, the issue it closes, and what testing confirms it. Testing bar by change type:
  - **Bug fix** — a unit test that reproduces the bug and confirms the fix. A live `docs/qa/tests/*.md` test case (see [QA operations](#qa-operations)) is welcome too if you have QA fixtures configured, but it's not required to merge — we'll add live QA coverage as a follow-up before the fix ships in a release.
  - **Refactor** — existing unit tests and QA test cases for the touched code still pass; note explicitly if behavior is unchanged.
  - **New tool** — QA test cases and a checklist entry, see [Adding a new tool](#adding-a-new-tool). PRs without them will be asked to add them.
  - **Docs only** — no tests required, but run `make lint` and let pre-commit hooks pass.
- Update `docs/design.md` if your change affects scope, tool inclusion criteria, or testing approach.
- If your change warrants a new ADR, add it to `docs/decisions/` following the existing format.
- Review turnaround is best-effort — there's no guaranteed response time.

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md).

## Release gate

A completed `docs/qa/runs/vX.Y.Z.md` — with all required suites checked off and results files linked — is required before tagging a stable release. See [`docs/qa/runs/README.md`](docs/qa/runs/README.md) for the suite tier definitions and how to run.
