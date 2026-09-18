# Decision: Generate `add_data_validation`'s condition_type docstring from `_CONDITION_SPECS` (issue #751)

**Date:** 2026-09-15
**Snapshot commit:** branch `chore/jay/issue-751` — see `src/mcp_gee_sweet/tools/sheets/structure.py`

## Background

`_CONDITION_VALUE_COUNTS` (the per-`condition_type` expected `values` length, used by `_condition_value_count_error` to reject a mismatched call locally instead of round-tripping to a raw Sheets API 400 — issue #366) and `add_data_validation`'s own docstring (the prose enumerating each `condition_type` and what `values` means for it) encoded the same per-condition-type fact in two independently hand-maintained places. Nothing tied them together — a future edit to one had no mechanism forcing the other to follow, so the tool's documented behavior could silently drift from what it actually enforces. Issue #751 filed this without prescribing a fix, listing three options: a cheap key-set-parity test, generating the docstring from a single richer table, or accepting the duplication with cross-reference comments.

## Decision: single `_CONDITION_SPECS` table, docstring generated from it at import time

`_CONDITION_SPECS: dict[str, _ConditionSpec]` is the one source of truth — each entry is a `_ConditionSpec(counts, doc, group)` NamedTuple holding the expected `values` length(s), the prose describing what `values` means for that `condition_type`, and an explicit `group` tag naming which docstring line it renders on. `_condition_value_count_error` reads `spec.counts` from `_CONDITION_SPECS` directly — there is no separate `_CONDITION_VALUE_COUNTS` table. `_condition_type_doc_block()` renders the docstring's bullet list via `itertools.groupby(_CONDITION_SPECS.items(), key=lambda kv: kv[1].group)` (dict insertion order already puts each group's members together) — e.g. every one-numeric-value `NUMBER_*` type lands on one line, the same grouping the original hand-written prose used. `_render_condition_group` soft-wraps a long line with `textwrap.wrap`, matching this file's other hand-written docstring blocks.

**Grouping keys on an explicit tag, not incidental `(counts, doc)` equality.** An earlier version of this fix grouped directly on `spec` equality. `TEXT_IS_EMAIL`, `TEXT_IS_URL`, `BLANK`, and `NOT_BLANK` all share the identical `(counts=(0,), doc="no values")` spec and sit adjacent in `_CONDITION_SPECS`, so that version silently collapsed two semantically unrelated condition_type families (text-format validity vs. blank-cell checks) onto one generated line — a live-confirmed regression from the original hand-written docstring's two separate lines, caught in QA review (PR #759). Two condition_types can end up with identical rendered text while remaining semantically distinct; grouping on the explicit `group` tag instead means they can never silently merge just because their text happens to coincide. `_condition_type_doc_block` asserts every member of a `group` shares an identical spec, since two entries tagged with the same group but different counts/doc would be a `_CONDITION_SPECS` authoring bug, not a legitimate grouping.

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

`test_condition_specs_covers_every_valid_condition_type` guards `_CONDITION_SPECS`'s own key set against `_VALID_CONDITION_TYPES` drift. `test_add_data_validation_docstring_matches_condition_specs` guards the generator's actual output — for every `group`, that group's canonical rendered text (names plus `spec.doc`) must appear in the generated docstring, not just each `condition_type` name somewhere in it (a name-presence-only check passed even while the grouping bug above silently merged four distinct condition_types onto one line). `test_condition_type_doc_block_never_merges_different_groups` asserts the invariant directly: no single rendered line ever names condition_types from more than one `group`. `test_add_data_validation_registered_docstring_survives_timed_wrapping` guards the `__doc__`-before-`tool()` ordering itself — wrapping the captured function with the real `_timed` and confirming the docstring survives, since a swap of those two lines would silently register the tool with no docstring.
