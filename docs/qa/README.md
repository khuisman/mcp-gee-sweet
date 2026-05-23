# QA Workflow

Prompt-driven integration tests for mcp-gee-sweet. Each test case is a natural language prompt you issue to Claude via the MCP server, paired with a list of things to verify in the response.

## Prerequisites

- A running mcp-gee-sweet server (Docker or `uv run mcp-gee-sweet`)
- Auth configured (service account or OAuth) with access to your Google Drive
- Claude Desktop or Claude Code connected to the server

## Steps

1. **Set up fixtures** — follow [`setup.md`](setup.md) to create your test spreadsheet and doc. Takes about 2 minutes.
2. **Record your IDs** — copy `fixtures.template.md` → `fixtures.local.md` (gitignored) and fill in the IDs from step 1.
3. **Run tests** — open a test file in `tests/`, substitute your IDs for the `{PLACEHOLDER}` values, and paste each prompt into Claude.
4. **Verify** — check each item in the **Checks** list against what Claude returns.
5. **Report failures** — open a GitHub issue with the TC number, the exact prompt you used, and what you observed.

## Test files

| File | Category | TC prefix |
|---|---|---|
| [tests/read.md](tests/read.md) | Read tools | TC-R## |
| [tests/write.md](tests/write.md) | Write tools | TC-W## |
| [tests/sheets.md](tests/sheets.md) | Sheet management | TC-S## |
| [tests/drive.md](tests/drive.md) | Drive tools | TC-D## |
| [tests/charts.md](tests/charts.md) | Chart tools | TC-C## |
| [tests/infra.md](tests/infra.md) | Infrastructure | TC-I## |

## Notes

- Tests marked **⚠️ destructive** mutate the fixture spreadsheet. Run these last within their section or reset fixtures afterward using the seed prompt in `setup.md`.
- Tests marked **🔍 product decision** have no single correct answer — note what you observed and open an issue if the behavior seems wrong.
- Cache hit tests (TC-R17, TC-S02, etc.) require checking server logs: `make logs` or `docker compose logs mcp-gee-sweet`.

## Contributing

If you find a bug or surprising behavior, open a GitHub issue. To add a new test case, submit a PR adding it to the relevant file in `tests/` with the next sequential TC number.
