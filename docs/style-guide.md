# Style Guide

Code-level convention: how source and tests are organized, and what tooling enforces automatically. For product/architecture policy (what belongs in this server, when to build a composite tool), see [Design Principles](design.md). For the reasoning behind a specific past decision, see the [Decision Log](decisions/index.md).

This is a v0, written after months of fast iteration with no retroactive documentation of the conventions that emerged. It codifies what the codebase already does in practice, plus a couple of low-churn additions — it isn't a wishlist of everything a style guide could cover. Sections not yet here (docstring conventions beyond the tool-docstring check below, error-handling patterns, naming, type-hint policy) are gaps to assess later, not omissions decided against.

---

## Module size and domain splitting

There's no enforced line-count limit. The signal that a file needs splitting is **domain cohesion, not size** — a file mixing unrelated responsibilities should split along those lines even if it's short; a large file that's genuinely one cohesive domain doesn't need to shrink for its own sake.

In practice, files that grow past ~1000 lines have tended to be the ones that *did* drift into bundling unrelated responsibilities — treat crossing that size as a prompt to check, not a rule to enforce mechanically.

**Precedent:** `tools/docs/__init__.py` was split into `content.py`/`tables.py`/`style.py`/`layout.py` (PR #232) once it outgrew being one file. `content.py` itself (1591 lines) is undergoing the same treatment now — extracted into `named_ranges.py`, `editing.py`, `images.py` (#371, #372), each a self-contained domain with its own dependency footprint verified against real ticket history before committing to the split (see `architecture/content-py-split-plan.md`-style verification, not a split done on line-count alone).

**Known outlier, not yet addressed:** `tools/sheets/structure.py` is 1865 lines — larger than `content.py` was before its split — with no ticket filed yet. Noted here as an assessment finding; fixing it is separate follow-up work, not part of this doc.

When a split is warranted, split by domain (mirroring the existing `sheets/`, `drive/`, `docs/` package boundaries), not by arbitrary line ranges.

---

## Test structure — mirror `tools/` 1:1

Every module under `src/mcp_gee_sweet/tools/<domain>/<module>.py` should have a corresponding `tests/<domain>/test_<module>.py`. This is already true for `sheets/` and `drive/`:

```
tools/sheets/structure.py   ↔  tests/sheets/test_structure.py
tools/drive/transfer.py     ↔  tests/drive/test_transfer.py
```

A single-file domain (no subpackage in `src/`) gets a single flat test file — no subpackage needed until the source itself becomes one: `tools/calendar.py` ↔ `tests/test_calendar.py`, `cache.py` ↔ `tests/test_cache.py`, `response_limits.py` ↔ `tests/test_response_limits.py`, and the top-level `auth.py`/`server.py`/`http_transport.py` similarly.

**Gap found while sequencing #371/#372:** `tools/docs/` never got promoted to a test subpackage the way `sheets/`/`drive/` did — `tests/test_docs_content.py` alone currently covers everything that's about to become four separate modules (`content.py`, `named_ranges.py`, `editing.py`, `images.py`). #371 and #372 now include splitting the corresponding tests as part of their scope, so this resolves as those land.

**Going forward:** a PR that splits a `tools/` module splits its test file in the same PR — not as a follow-up, and not left for whoever notices the mismatch later.

---

## Linting — Ruff

**Current config** (`pyproject.toml`): `line-length = 100`, `target-version = "py310"`, and an empty `[tool.ruff.lint]` — meaning only Ruff's bare defaults are active. Checked directly against this repo's `ruff` (`ruff check --show-settings`): that resolves to the `E`/`F`/`I`/`W` categories — pycodestyle errors, pyflakes, import sorting, pycodestyle warnings. The repo currently passes `ruff check .` cleanly under this set.

**Assessed, not yet applied** — dry-run counts for categories not currently selected (`ruff check --select <CAT> .`, without touching `pyproject.toml`):

| Category | Hits | What it catches |
|---|---|---|
| `UP` (pyupgrade) | 2 | Outdated syntax for the `py310` target |
| `B` (bugbear) | 11 | Likely-bug patterns |
| `C4` (comprehensions) | 0 | Comprehension simplifications |
| `SIM` (simplify) | 6 | Simplifiable conditionals/expressions |
| `RUF` (ruff-specific) | 23 | Misc — mostly stale `noqa` comments referencing rules that aren't enabled, plus a couple of ambiguous-unicode-in-comment hits |
| `ASYNC` | 16 | All `ASYNC240` — sync `pathlib.Path` calls inside `async def` functions |
| `ANN` (annotations) | 1635 | Missing type annotations |

**Recommendation:** adopt `UP`, `B`, `C4`, `SIM`, `RUF` — low churn (0–23 hits each, `--fix` handles most of it), real signal. `B905` is worth calling out specifically: it flags `zip()` without `strict=`, which is exactly the bug class behind [#277](https://github.com/khuisman/mcp-gee-sweet/issues/277) (`zip(doc_tables, ast_tables)` silently cross-pairing mismatched sequences) — that one was caught by hand during a PR review; this rule would catch the next instance of the same pattern at write time, in any of the 11 current call sites (`emitter.py` mostly) that don't yet specify `strict=`.

**Deliberately not recommending yet:**
- `ASYNC` — all 16 hits are `ASYNC240`, which assumes a `trio`/`anyio` async model. This project's async model is `asyncio.to_thread` via `execute_in_thread` (see `CLAUDE.md`'s async-execution notes), so the rule's suggested fix doesn't directly apply. The underlying question — should these particular sync `Path` calls go through `execute_in_thread` too — is worth a manual look call-by-call, not a blanket rule enable.
- `ANN` — 1635 hits. Full type-annotation coverage is a real undertaking, not a minimal-default addition; if pursued, it needs its own phased adoption plan, not a flag flip here.

Applying the recommended set to `pyproject.toml` is a separate follow-up decision — this doc records the assessment, not the change itself.

---

## Formatting

`ruff-format` runs via pre-commit (`.pre-commit-config.yaml`) alongside `ruff --fix`. Nothing further to configure here — formatting is already automatic and enforced at commit time.

---

## Playwright

The operational protocol (lock path, acquire/release, staleness recovery for coordinating a single browser tab across parallel QA shards) already lives in [`docs/qa/run.md`](qa/run.md#coordinating-playwright-across-parallel-shards) — that's QA-execution detail, not code style, so it's linked here rather than duplicated.

---

## Assessment process

When this guide gains a new section or an existing recommendation changes, re-run the relevant check (Ruff dry-run, file-size scan, test-mirror scan) against the current codebase and file findings as GitHub issues — one per violation or violation category, same as any other ticket — rather than accumulating a separate audit document that drifts out of sync with the roadmap.
