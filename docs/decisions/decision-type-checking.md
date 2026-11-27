# Decision: Type Checking in CI

**Date:** 2026-11-27
**Status:** decided (maintainer, 2026-11-27): option C, pyright in basic mode on `src/` as a
CI gate.
**Tracking:** #379
**Snapshot commit:** `develop` at `729cb79d`

## Background

#379 asked whether to adopt Ruff's `ANN` rules (annotation presence) and, if so, how. It
listed four open questions: new code only or backfill, which modules first, presence
rules or a real type checker, and whether it is worth the churn at all. Kai's note
(2026-10-18) left the call on doing it at all to this review.

Today nothing checks types. CI (`.github/workflows/ci.yml`) runs `uv lock --check`,
`ruff check` (rules `E, F, W, I, UP, B, C4, SIM, RUF`, no `ANN`), `ruff format --check` and
pytest on Python 3.11 to 3.15. `pyrightconfig.json` only points an editor at `.venv` (#270).
`docs/style-guide.md` lists type-hint policy as a gap to assess later.

All figures below are static and local (ruff via `uvx`, pyright 1.1.414 via `uvx`, against
the project's `.venv`). No tool was called through a server.

## Where the code stands

**Annotation coverage.** 949 of `src/`'s 1,145 functions (83%) annotate every parameter and
the return type. `ruff check --select ANN` finds 358 gaps in `src/` (158 unannotated
parameters, 109 missing return types, 91 `Any`) and about 9,000 in `tests/`, mostly test
functions with no `-> None`. #379's figure of 1,635 was counted with `--select ANN .` on an
older tree whose commit isn't recorded.

**Type errors.** `pyright src` in its default (basic) mode reports **680 errors** in 24 of
`src/`'s 53 files. 600 of them come from three patterns:

| Pattern | Errors | Cause |
|---|---|---|
| `ctx.request_context.lifespan_context.sheets_service` and the like | 297 | Tools annotate `ctx: Context`, whose lifespan type parameter defaults to `dict[str, Any]`, so every attribute of `SpreadsheetContext` is unknown. |
| `ctx: Context = None` | 154 | The parameter's default is `None` but its type isn't optional. mcp always injects it; the default exists only so the parameter can follow defaulted ones. |
| `ToolAnnotations(title=..., readOnlyHint=True)` | 149 | `ToolAnnotations` declares `read_only_hint` and accepts `readOnlyHint` only as a pydantic alias, which the checker doesn't see. |

The other 80 are spread thinly. Most are `X | None` passed where `X` is required, 16 are
"possibly unbound" variables (for example `resized` in `docs/images.py`,
`drive_service` in `drive/transfer.py`, `cleanup_error` in `docs/content.py`), a handful are `None` member access
(`doc_to_ast.py`, `emitter.py`), and one is `auth.py:1001` passing `Credentials | None` to a
`Credentials` parameter. None of them has been checked as a real bug or a false positive.
Some will be guarded at runtime in ways the checker can't follow.

### The three patterns are cheap to clear (prototyped)

On a scratch copy of `src/` (not committed):

1. `ToolContext = Context[SpreadsheetContext, Any]` in `auth.py`, used for every injected
   `ctx`. mcp still finds the parameter (`find_context_parameter` accepts it, since a
   parameterized pydantic generic is a real subclass of `Context`).
2. `INJECTED: Any = None` as the parameter's default, `ctx: ToolContext = INJECTED`.
3. `readOnlyHint=` → `read_only_hint=` (and the other three hints) at every
   `ToolAnnotations(...)`.

18 files change, nearly all mechanically. pyright goes from 680 errors to 84. Eight of those
84 are helpers still annotated with the bare `Context` (such as `tools/concurrency.py`),
which the same alias covers, so about 76 remain to triage. With `ENABLED_TOOLS=all` the
server still registers 156 tools, as `develop` does, `get_cache_ttl` still gets `ctx`
injected, and its annotations read back unchanged.

## Options

### Option A: do nothing

Keep annotations as a convention, unchecked.

**Pros:** no churn, no new CI step.
**Cons:** the 83% coverage is already paid for and buys nothing in CI. The 80 non-systemic
errors include the shapes review keeps finding by hand (possibly unbound on an error path,
`None` passed where a value is required), and nothing stops new ones.

### Option B: Ruff's `ANN` rules

Add `ANN` to Ruff's `select`, for `src/` only or for new code.

**Pros:** no new tool; Ruff already runs.
**Cons:** checks that an annotation exists, not that it's right. It would flag the 358 gaps
and none of the 680 errors. On `tests/` it is about 9,000 hits of churn with no bug-finding
value.

### Option C: pyright, basic mode, on `src/`, in CI

Clear the three patterns, triage the rest to zero (fix, or a line-level ignore with a
reason), then add a `pyright` step to the `Lint and test` job so new errors fail it.

**Pros:** checks correctness, which is where the value is. pyright already runs in
maintainers' editors (that's what `pyrightconfig.json` is for), so CI and editors agree.
Basic mode is permissive about unannotated code, so the 17% of unannotated functions
don't block the gate. It starts at zero and stays there.
**Cons:** the triage of about 76 errors is real work, and a few may be real bugs that need
their own fix. A new dev dependency: the PyPI `pyright` wrapper fetches Node on first run,
so pin `pyright[nodejs]` (Node from a wheel, no network fetch at check time) in the dev
group rather than `uvx pyright`, whose version floats. Pin `pythonVersion = "3.11"`, the
floor, so a construct newer than 3.11 is caught. Run it once, not once per matrix
interpreter.

### Option D: strict checking (pyright `strict`, or mypy `--strict`)

**Pros:** the strongest guarantee.
**Cons:** every function annotated, every `Any` justified, before the gate can turn on.
googleapiclient's resources are dynamically built and untyped, so strict mode pushes
`Any` or stubs through every tool body that calls an API. That is a project, not a ticket.
mypy would also be a second checker beside the one editors already run.

## Lean

**C.** It turns annotations the code already mostly has into a check that catches the bug
shapes review keeps finding, for about one ticket of work, and the prototype shows the
bulk of it is mechanical. B checks the wrong thing, D costs far more than it returns here,
and A leaves the 83% unused.

`tests/` stays out of the gate under C. Annotating test functions finds nothing.

If C is taken, the work is one ticket: the three fixes, the triage to zero, the pinned dev
dependency and the CI step. The gate can't turn on until the count is zero, so splitting
the fixes from the gate would leave a ticket with nothing to show. Any triaged error that
turns out to be a user-visible bug gets its own ticket, so the typing PR doesn't carry
behavior fixes.

## Decision

**Decided (maintainer, 2026-11-27): option C.** The implementation ticket is filed
separately from #379.
