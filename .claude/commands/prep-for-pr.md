# PR Readiness Checklist

Review the current branch against this checklist and report the status of each item. Be specific — name the files, test IDs, or code paths involved rather than answering generically.

## 1. Tests

- [ ] **Unit tests written** — are there new tests in `tests/` covering the changed code?
- [ ] **Unit tests passing** — has `uv run python -m pytest tests/` been run and passed?
- [ ] **Regression coverage** — were tests that touch the modified files (not just new tests) also run?
- [ ] **QA test cases written** — are there AI-driven test cases in `docs/qa/tests/` for the new/changed tools?

**Live QA execution is out of scope for this checklist.** If this session is a worker in a `.claude/worktrees/*` checkout, running live QA tools here would exercise the main checkout's code, not this branch's changes — the result would look real but prove nothing. Do not run live tests and do not write `**Result**` entries from a worktree. That happens in the orchestrator's `/verify-pr` pass after the PR is open, in the main checkout, where the branch's actual code is reachable by the live MCP tools. Leave the `**Result**` line off new/changed test cases entirely — don't stub it as "pending," just omit it so `/verify-pr` adds the first real one.

## 2. QA test case tags

- [ ] **`⚠️ requires-oauth` accuracy** — scan all new and modified test cases:
  - Tag IS present when: the tool itself requires OAuth (e.g. creates files in personal Drive: `create_doc`, `create_doc_from_file`)
  - Tag IS NOT present when: the tool is auth-agnostic and only the test fixture happens to live in personal Drive (`write_doc_content`, `get_doc_structure`, `insert_doc_text`, `delete_doc_range`, `style_doc_range`, `style_doc_table_cells`, etc.)
  - Tag IS NOT present on error-path tests that return before making any API call

- [ ] **`**Playwright: required**` accuracy** — scan all new and modified test cases (see `docs/qa/run.md` for the tag's runtime behavior):
  - Tag IS present when: the check verifies a mutation with a visual signature the API-level response can't fully confirm (formatting, hyperlinks, images, charts, layout)
  - Tag IS NOT present when: the test is read-only, an error path, or a count/pagination check with no visual component
  - Note: this tier definition is a working rule, not yet formalized in `docs/qa/run.md` — see the open TODO in `docs/qa/retro-v0.8.0.md`. Flag inconsistency rather than silently picking a side.

## 3. Safety

- [ ] **No resource IDs committed** — no Google Drive/Docs/Sheets/Calendar IDs appear in committed files. IDs belong in `.env` or `fixtures.local.md` (both gitignored).
- [ ] **No secrets or credentials** — no API keys, tokens, or service account JSON content committed.

## 4. Documentation

- [ ] **Design doc** — if the work involved an architectural decision or a non-obvious design choice, is it captured in `docs/design/`?
- [ ] **CLAUDE.md** — if a new tool was added or the architecture changed, does `CLAUDE.md` reflect it?
- [ ] **`docs/auth.md` — Required Google APIs** — if the change adds a new Google API client or OAuth scope, is the API listed under "Required Google APIs" in `docs/auth.md`? Is the scope added to the `gcloud` ADC login command? Is there a re-auth note if an existing scope was added?

## 5. PR hygiene

- [ ] **Feature branch** — changes are on a named branch, not directly on `main`.
- [ ] **Issues referenced** — the PR body includes `Closes #N` for every issue this work resolves. Check the branch name, commit messages, and code for issue numbers — all referenced tickets must be linked, not just the primary one.
- [ ] **PR preview shown** — the full PR title and body were displayed to the user for review before the PR was opened.
- [ ] **No auto-push** — `git push` only happened after the user approved.
