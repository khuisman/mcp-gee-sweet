# Decision: Generate `add_data_validation`'s condition_type docstring from `_CONDITION_SPECS` (issue #751)

**Date:** 2026-09-15
**Snapshot commit:** branch `chore/jay/issue-751` — see `src/mcp_gee_sweet/tools/sheets/structure.py`

## Background

`_CONDITION_VALUE_COUNTS` (the per-`condition_type` expected `values` length, used by `_condition_value_count_error` to reject a mismatched call locally instead of round-tripping to a raw Sheets API 400 — issue #366) and `add_data_validation`'s own docstring (the prose enumerating each `condition_type` and what `values` means for it) encoded the same per-condition-type fact in two independently hand-maintained places. Nothing tied them together — a future edit to one had no mechanism forcing the other to follow, so the tool's documented behavior could silently drift from what it actually enforces. Issue #751 filed this without prescribing a fix, listing three options: a cheap key-set-parity test, generating the docstring from a single richer table, or accepting the duplication with cross-reference comments.

## Decision: single `_CONDITION_SPECS` table, docstring generated from it at import time

`_CONDITION_SPECS: dict[str, _ConditionSpec]` is now the one source of truth — each entry is a `_ConditionSpec(counts, doc)` NamedTuple holding both the expected `values` length(s) and the prose describing what `values` means for that `condition_type`. `_CONDITION_VALUE_COUNTS` is derived from it (`{k: v.counts for k, v in _CONDITION_SPECS.items()}`), kept under its old name since `_condition_value_count_error` and an existing test (`test_condition_value_counts_covers_every_valid_condition_type`) already key off it. `_condition_type_doc_block()` renders the docstring's bullet list by grouping consecutive `_CONDITION_SPECS` entries that share the exact same `(counts, doc)` — e.g. every one-numeric-value `NUMBER_*` type lands on one line, the same grouping the original hand-written prose used.

**The generated docstring can't be assigned as a plain literal.** A docstring is recognized by the compiler as the first bare string-literal statement in a function body — an f-string or `.format()`-derived value isn't a compile-time constant, so it silently doesn't populate `__doc__` even as the first statement. And decorator application (`@tool(...)`) happens synchronously as part of executing the `def` statement, with no window afterward to mutate `__doc__` before `tool()`'s `_timed` wrapper runs `functools.wraps(func)` (which copies `__doc__` onto the wrapper at that moment). So `add_data_validation` is defined with no docstring, then explicitly:

```python
add_data_validation.__doc__ = _ADD_DATA_VALIDATION_DOCSTRING
add_data_validation = tool(
    annotations=ToolAnnotations(title="Add Data Validation", destructiveHint=True)
)(add_data_validation)
```

— `__doc__` is set on the raw function *before* `tool()` wraps it, decomposing the `@tool(...)` sugar into its two explicit steps so the assignment lands in time. Every other tool in this codebase can keep using `@tool(...)` decorator sugar unchanged; this pattern is only needed by a tool whose docstring must be computed rather than written as a literal.

`_ADD_DATA_VALIDATION_DOCSTRING` itself is a module-level f-string built from a static template plus `_condition_type_doc_block()`'s output — this is an ordinary variable assignment, not a docstring position, so the f-string restriction above doesn't apply to it.

## Alternatives considered and rejected

- **Cheap key-set-parity test only** (`set(_CONDITION_VALUE_COUNTS) == set(_VALID_CONDITION_TYPES)`) — already existed pre-#751 and is still true post-fix, but the issue itself called out that this only guards against a missing/extra `condition_type` key, not the docstring's prose actually matching each type's real count. Insufficient alone.
- **Accept duplication, add cross-reference comments** — lowest effort, but leaves the actual drift risk (the thing #751 was filed about) completely unaddressed; a future edit to one side still has no enforcement mechanism, just a comment someone can miss.

## Test coverage

`test_condition_specs_covers_every_valid_condition_type` guards `_CONDITION_SPECS`'s own key set (the actual source of truth, not just its derived `_CONDITION_VALUE_COUNTS` dict) against `_VALID_CONDITION_TYPES` drift. `test_add_data_validation_docstring_generated_from_condition_specs` guards the generator itself — every `condition_type` must actually appear in the rendered docstring text, catching a grouping bug that could silently drop or mis-render an entry.
