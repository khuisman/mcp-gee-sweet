# Contributing to mcp-gee-sweet

## Quick orientation

- `src/mcp_gee_sweet/tools/` — one file per tool category
- `docs/qa/tests/` — one QA test file per category, matching the tool files
- `docs/decisions/` — ADRs; `docs/design.md` — living principles doc
- `docs/qa/operations.yaml` — machine-readable QA operations manifest (see below)

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

Copy the environment template and fill in your credentials:

```bash
# .env is gitignored — create it at the repo root
cp /dev/null .env
```

At minimum you need one auth method and a Drive folder. See [Authentication in the README](README.md#-authentication--environment-variables-detailed) for all options.

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

### 3. Set up QA fixtures

Give your AI assistant a writable Drive folder and tell it to set up your fixtures:

> "Read `docs/qa/operations.yaml` and run the `setup_fixtures` operation. My Drive folder is at https://drive.google.com/drive/folders/YOUR_FOLDER_ID"

The assistant will:
- List the folder contents
- Identify or ask you to create the fixture spreadsheet and doc
- Populate them with known fixture data
- Write `TEST_*` IDs to your `.env`

**If you are using service account auth:** the folder and both files must be shared with the service account email. Find it at `service_account.json` → `client_email`. The service account cannot access files in personal Drive unless explicitly shared — see [the README](README.md#-google-cloud-platform-setup-detailed) for the sharing steps.

### 4. Run the server

```bash
make start   # Docker (recommended)
# or
uv run mcp-gee-sweet --transport sse
```

---

## QA operations

All QA workflows are defined in [`docs/qa/operations.yaml`](qa/operations.yaml). Any AI assistant that can read files can parse this manifest and offer the operations as a menu.

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

### Human confirmation flow

The `human_confirmation` operation steps through tests one at a time — the AI presents each prompt and its evaluation, you confirm the verdict. This is the primary QA method for new test cases and first-time verification. See [`docs/decisions/decision-testing.md`](decisions/decision-testing.md) for the full rationale and phased trust model.

---

## Adding a new tool

1. Add the implementation to the appropriate file in `src/mcp_gee_sweet/tools/`.
2. Add QA test cases to the matching file in `docs/qa/tests/` with the next sequential TC number.
3. Add the tool name to the `Available Tool Names` list in `README.md`.
4. Run `run_group` for the affected category to verify.

Every new tool must have at least:
- A happy-path test case
- An error/edge-case test case
- The tool included in the `docs/qa-checklist.md` attestation

See [`docs/design.md`](design.md) for the tool inclusion criteria and composite tool rules.

---

## Development workflow

```bash
make test        # unit tests (no credentials needed)
make lint        # ruff linter + formatter
make logs        # tail server logs (Docker)
make restart     # restart server after code changes, then restart your MCP client
```

Pre-commit hooks run `ruff` on staged files. If a commit is blocked, fix the lint issue and commit again — don't skip hooks.

---

## Pull requests

- Open a feature branch before pushing (`feat/`, `fix/`, `docs/` prefixes).
- New tools require QA test cases and a checklist entry — PRs without them will be asked to add them.
- Update `docs/design.md` if your change affects scope, tool inclusion criteria, or testing approach.
- If your change warrants a new ADR, add it to `docs/decisions/` following the existing format.
