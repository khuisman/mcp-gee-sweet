# Style Guide

Code-level convention: how source and tests are organized, and what tooling enforces automatically. For product/architecture policy (what belongs in this server, when to build a composite tool), see [Design Principles](design.md). For the reasoning behind a specific past decision, see the [Decision Log](decisions/index.md).

This is a v0, written after months of fast iteration with no retroactive documentation of the conventions that emerged. It codifies what the codebase already does in practice, plus a couple of low-churn additions — it isn't a wishlist of everything a style guide could cover. Sections not yet here (docstring conventions beyond the tool-docstring check below, error handling outside the modules [Error handling](#error-handling) covers, naming, type-hint policy) are gaps to assess later, not omissions decided against.

---

## Module size and domain splitting

There's no enforced line-count limit. The signal that a file needs splitting is **domain cohesion, not size** — a file mixing unrelated responsibilities should split along those lines even if it's short; a large file that's genuinely one cohesive domain doesn't need to shrink for its own sake.

In practice, files that grow past ~1000 lines have tended to be the ones that *did* drift into bundling unrelated responsibilities — treat crossing that size as a prompt to check, not a rule to enforce mechanically.

**Precedent:** `tools/docs/__init__.py` was split into `content.py`/`tables.py`/`style.py`/`layout.py` (PR #232) once it outgrew being one file. `content.py` has since grown large enough to warrant the same treatment — planned extraction into `named_ranges.py`, `editing.py`, `images.py` (#371, #372, both open), each a self-contained domain with its own dependency footprint verified against real ticket history before committing to the split (see `architecture/content-py-split-plan.md`-style verification, not a split done on line-count alone).

**Known outlier:** `tools/sheets/structure.py` has grown larger than `content.py` was before its own split — tracked in #376.

When a split is warranted, split by domain (mirroring the existing `sheets/`, `drive/`, `docs/` package boundaries), not by arbitrary line ranges.

---

## Test structure — mirror `tools/` 1:1

Every module under `src/mcp_gee_sweet/tools/<domain>/<module>.py` should have a corresponding `tests/<domain>/test_<module>.py`. This is already true for `sheets/` and `drive/`:

```
tools/sheets/structure.py   ↔  tests/sheets/test_structure.py
tools/drive/transfer.py     ↔  tests/drive/test_transfer.py
```

A single-file domain (no subpackage in `src/`) gets a single flat test file — no subpackage needed until the source itself becomes one: `tools/calendar.py` ↔ `tests/test_calendar.py`, `cache.py` ↔ `tests/test_cache.py`, `response_limits.py` ↔ `tests/test_response_limits.py`, and the top-level `auth.py`/`server.py`/`http_transport.py` similarly.

`tools/docs/` hasn't been promoted to a test subpackage yet — `tests/test_docs_content.py` currently covers everything that's about to become four separate modules (`content.py`, `named_ranges.py`, `editing.py`, `images.py`). #371 and #372 include splitting the corresponding tests as part of their scope.

**Going forward:** a PR that splits a `tools/` module splits its test file in the same PR — not as a follow-up, and not left for whoever notices the mismatch later.

---

## Linting — Ruff

**Current config** lives in `pyproject.toml`'s `[tool.ruff]` and `[tool.ruff.lint]` tables; `uv run ruff check --show-settings` prints the resolved rule set. It isn't copied here, since a copy drifts out of date.

The Ruff version is the project's own locked dev dependency (`uv.lock`). CI and the pre-commit hooks both run it through `uv run --frozen ruff`, so pre-commit applies the same Ruff version and config as CI (#974). Pre-commit checks staged Python files; CI checks the whole tree. A commit that changes `pyproject.toml` or `uv.lock` also runs a whole-tree `ruff check .` and `ruff format --check .`, since a config or version change can fail files the commit doesn't touch.

Expanding the rule set further is tracked, not decided here:
- #378 — `ASYNC` (needs a manual per-call-site look, not a blanket enable)
- #379 — `ANN` (needs a phased adoption plan, not a flag flip)

---

## Formatting

`ruff format` runs via pre-commit (`.pre-commit-config.yaml`) alongside `ruff check --fix`, both as `uv run --frozen` hooks on the locked Ruff version. Nothing further to configure here — formatting is already automatic and enforced at commit time.

---

## Error handling

A tool reports a Google API failure in one of two ways, and the client sees the error text either way:

- **Raise it.** `server._timed` turns an exception it recognizes (`_CLIENT_VISIBLE_ERRORS`: an `HttpError`, an auth error, a transport error, `ValueError`, `OSError`) into a `ToolError` carrying the exception's text, and logs the original with its traceback first. Nothing about a raised `HttpError` is lost or hidden from the client.
- **Return `{"error": "..."}`.** The tool catches at its own boundary and returns a result dict. The call succeeds as far as MCP is concerned, and the dict can carry more than the message.

Which to use (#329):

- **`tools/docs/*.py` returns `{"error": ...}`.** Every tool there catches the document read or edit it's built around and returns the error dict, often with what it knows about the doc (`docId`, the work that landed before the failure). Write a new Docs tool the same way. Two calls still raise: the deprecated `get_doc_content`, which keeps its behavior until it's removed, and `get_doc_as_markdown`'s optional comments read (`include_comments`).
- **`tools/drive/comments.py` raises.** Its tools let Drive's error through. `update_comment` returns `{"error": ...}` where Drive's answer would mislead: it answers an edit of a deleted comment or reply with a bare 500 or 400, so the tool reads the target back and returns a clear message when it's deleted (otherwise re-raising Drive's own error), and it answers an edit by anyone but the author with a 200 and the old text. A new comments tool raises too, unless Drive's answer misleads like that.
- **Anywhere, catch when the tool has something to add**: an ID of something it created before the failure (`_restamp_failure_result`'s `fileId`), partial results, or a message clearer than Google's. A bare `except Exception: return {"error": str(e)}` adds nothing that raising wouldn't.
- **A tool whose return type isn't a dict raises.** A `list[...]`-typed tool can't return `{"error": ...}`: the dict fails its output schema.
- **Don't change an existing tool from one form to the other in passing.** Callers can depend on either shape, so a switch is a behavior change and gets its own ticket.

---

## Playwright

The operational protocol (lock path, acquire/release, staleness recovery for coordinating a single browser tab across parallel QA shards) already lives in [`docs/qa/run.md`](qa/run.md#coordinating-playwright-across-parallel-shards) — that's QA-execution detail, not code style, so it's linked here rather than duplicated.

---

## Assessment process

When this guide gains a new section or an existing recommendation changes, re-run the relevant check (Ruff dry-run, file-size scan, test-mirror scan) against the current codebase and file findings as GitHub issues — one per violation or violation category, same as any other ticket — rather than accumulating a separate audit document that drifts out of sync with the roadmap.
