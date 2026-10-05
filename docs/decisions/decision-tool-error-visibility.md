# Decision: Which Tool Errors Reach the Client Under mcp 2.3 (issue #872)

**Date:** 2026-10-04
**Snapshot commit:** branch `fix/ash/issue-872`. See `src/mcp_gee_sweet/server.py` (`_CLIENT_VISIBLE_ERRORS`, `_client_error_message`, `_timed`, `get_spreadsheet_info`).

## Background

Up to mcp 2.2, `Tool.run` wrapped any exception a tool raised as `ToolError(f"Error executing tool {name}: {e}")`, so the exception's text always reached the client. This codebase relied on that. The degraded-start `OAuthConsentRequiredError` (#811) is raised rather than returned, so it fits a list-typed tool's output schema. Deliberate argument errors are `ValueError`s (A1-notation parsing, the response-size cap, `sync_folder`'s `result_local_path` check). Many tools let a Google `HttpError` propagate.

mcp 2.3.0 (2026-10-02) splits failures into anticipated and crash (checked in its source: `tools/base.py` `Tool.run`, `exceptions.py`):

- `ToolError` / `ResourceError`: the client sees `Error executing tool <name>: <text>`, logged at INFO.
- `MCPError`: passed through as a protocol error.
- Anything else: `UnexpectedToolError("Error executing tool <name>")`. The text stays on the server, which logs the traceback at ERROR.

Resources work the same way: a non-`ResourceError` becomes `UnexpectedResourceError`, and the template path reports `Error creating resource from template <uri>`.

`pyproject.toml` allowed `mcp>=2.0.0` while `uv.lock` pinned 2.0.0. So CI and the lane servers never saw 2.3, but a PyPI/`uvx` install resolved it. In a live repro, a revoked refresh token gave `['Error executing tool get_storage_quota']` and nothing else.

## Decision: allowlist the failures a caller can act on, at the wrapper

`_timed` re-raises an allowlist of exception types as `ToolError` with the original text, chained as `__cause__`:

| Type | Why the caller needs the text |
|---|---|
| `OAuthConsentRequiredError`, `MissingOAuthScopesError` | the `mcp-gee-sweet auth` instructions |
| `googleapiclient.errors.HttpError` | not found / permission denied / quota, with the request URL |
| `google.auth.exceptions.GoogleAuthError` | credential refresh and transport failures. A `RefreshError` on an OAuth connection also gets `reauthorize_instructions()`, since a token revoked after startup needs the same fix as #811 |
| `httplib2.HttpLib2Error`, `OSError` | network failures, plus local-path errors in the transfer tools |
| `ValueError` | every deliberate argument rejection in `tools/` raises one |

Anything else (`KeyError`, `TypeError`, an emitter `RuntimeError` invariant) stays a crash: mcp withholds its text and logs the traceback. A tool that wants a new kind of failure shown should raise `ToolError`, or one of the types above, rather than widening the list to `Exception`.

`get_spreadsheet_info` applies the same allowlist and raises `ResourceError`, since mcp handles resource errors through a separate path.

Alternatives considered:

- **Forward every exception's text (restore 2.0 behavior).** Rejected. A crash's text is internal detail (`KeyError: 'sheets'`), not something the model can act on, and mcp 2.3 withholds it on purpose.
- **Make `OAuthConsentRequiredError` subclass `ToolError`.** That fixes only the degraded start. Google API, `ValueError` and network errors would still be hidden. It also gives an auth-layer exception a dependency on the MCP framework, while that exception is also raised from the lifespan, outside any tool call.
- **Convert each tool to catch and return `{"error": ...}`.** Not possible for list-typed tools (the output schema rejects a dict), and it means touching ~150 tools to fix one wrapper-level behavior change.

Audit: every deliberate `raise` under `src/mcp_gee_sweet/tools/` is a `ValueError` or `OSError` (`PermissionError`). Two exceptions: `docs/emitter.py`'s `_apply_merges` `RuntimeError`, which `_apply_doc_content` wraps in `DocEditError` and every caller turns into an error dict, and the `BaseException` re-raises in `transfer.py` (cancellation). So no tool body needed to change.

## Dependency pin

`mcp>=2.3.0,<3`, with the lock bumped to 2.3.0, so CI runs the version users get. The lower bound also guarantees the 2.3 semantics this design assumes. `<3` keeps the next major from landing unannounced through `uvx`. A minor release can still change behavior (2.3 just did), so the lock should be bumped on purpose, not just on Dependabot's schedule.
