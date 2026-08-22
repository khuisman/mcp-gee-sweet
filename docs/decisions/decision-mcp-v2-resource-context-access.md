# Decision: Resource Context Access Under mcp v2 (issue #175)

**Date:** 2026-08-20
**Snapshot commit:** branch `chore/ash/issue-175` — see `src/mcp_gee_sweet/auth.py`, `src/mcp_gee_sweet/server.py`

## Background

Issue #175 tracked the eventual `mcp.server.fastmcp` → `mcp.server.mcpserver` migration once `mcp` v2 went stable (it did, 2026-08-20). The issue's own body described this as "a search-and-replace — no logic changes required," based on the module/class rename alone. That premise held for every tool file (`from mcp.server.fastmcp import Context` → `from mcp.server.mcpserver import Context`, ~15 files) and for the `_tool_manager`/`fn_metadata`/`arg_model` private-API chain `_enforce_strict_tool_args` relies on (verified live against mcp==2.0.0 — unchanged).

It did **not** hold for `server.py`'s two MCP resources (`server://auth-status`, `spreadsheet://{spreadsheet_id}/info`). Both previously called `mcp.get_context().request_context.lifespan_context` (issue #363) to reach `SpreadsheetContext`, the object `auth.py`'s `spreadsheet_lifespan` yields once at server startup. `mcp.server.mcpserver.MCPServer` (v2) has no `get_context()` method at all — confirmed by installing `mcp==2.0.0` in a scratch venv and inspecting `dir(MCPServer)` before writing any migration code, per this repo's "verify a ticket's API premise live before implementing" rule.

The replacement isn't uniform across the two resources, because v2's own Context-injection support for resource functions isn't uniform either:

- `spreadsheet://{spreadsheet_id}/info` is a **template** resource (its URI has a `{spreadsheet_id}` variable). v2's `MCPServer.resource()` decorator supports Context injection for template resources the same way it already does for tools — a function parameter with a `Context` type annotation gets it injected automatically per-request.
- `server://auth-status` is a **static** resource (no URI variables). v2's decorator explicitly rejects Context injection there: `ValueError: Resource 'server://auth-status' has no URI template variables, but the handler declares a Context parameter. Context injection for static resources is not supported.` (confirmed live). There is no `get_context()`, no contextvar-based ambient lookup (v2's low-level `Server`/`ServerRequestContext` machinery has none — verified by inspecting `mcp.server.lowlevel.server` and `mcp.server.context` source directly), and no other public mechanism to reach a running server's per-process state from a static resource function.

## Decision: split by mechanism, matched to what each resource actually needs

**`get_spreadsheet_info(spreadsheet_id: str, ctx: Context)`** — added `ctx: Context` as an ordinary injected parameter, reading `ctx.request_context.lifespan_context` exactly as every tool in this codebase already does. This is the officially-supported v2 mechanism for a template resource; nothing custom needed.

**`get_auth_status()`** — reads a new module-level singleton, `auth.get_lifespan_context()`, instead of going through Context at all:

```python
_lifespan_context: SpreadsheetContext | None = None

def get_lifespan_context() -> SpreadsheetContext:
    if _lifespan_context is None:
        raise RuntimeError("Server lifespan has not started yet")
    return _lifespan_context
```

`spreadsheet_lifespan` sets `_lifespan_context` immediately before yielding it. This isn't a workaround bolted on to route around a framework gap — `SpreadsheetContext` genuinely *is* process-wide, not per-request: the lifespan is an `@asynccontextmanager` that runs exactly once per server process and yields exactly one `SpreadsheetContext` for the process's entire lifetime (there's no per-connection or per-request re-authentication anywhere in this codebase). Reading it from a plain module-level reference is the accurate shape for state that doesn't vary by request, not a hack standing in for the "real" per-request Context path.

**Alternatives considered and rejected:**

- **Reach into private v2 internals for something `get_context()`-shaped** (e.g. a low-level `Server._request_ctx` contextvar). Rejected — confirmed live that v2's low-level `Server`/`ServerRequestContext` has no contextvar-based ambient-lookup mechanism at all (unlike v1's `Server.request_context`, which v1's `FastMCP.get_context()` built on). There's nothing private left to reach into; the capability was removed, not just hidden.
- **Turn `server://auth-status` into a template resource** (e.g. add a fake optional query variable like `server://auth-status{?_}`) purely to unlock v2's Context-injection path for templates. Rejected — this would expose a meaningless parameter in the resource's discoverable URI template for every client, just to route around a framework limitation, and the module-level singleton is simpler and has no such externally-visible side effect.
- **Give every tool/resource file its own reference to the lifespan object via closures at registration time**, instead of a shared getter. Rejected as unnecessary — `get_lifespan_context()` is a one-line accessor already colocated with `SpreadsheetContext`'s own definition in `auth.py`, and every other resource/tool that needs process state already imports from `auth.py` or gets it via `ctx.request_context.lifespan_context`, so this doesn't introduce a new import pattern.

## Other real (non-search-and-replace) gaps found during this migration

Verified live against mcp==2.0.0 before implementing, per this repo's standing rule:

- **Constructor `host`/`port` kwargs removed.** v1's `FastMCP(host=..., port=...)` has no v2 equivalent at construction time — v2 moved `host`/`port` to call-time kwargs on `sse_app()`/`run_sse_async()`/`run_streamable_http_async()`/`run()` itself. `server.py`'s `mcp = MCPServer(...)` dropped both kwargs; `app = mcp.sse_app(host=_resolved_host)` and `main()`'s `mcp.run(transport=transport, host=_resolved_host, port=_resolved_port)` (non-stdio branch only — stdio's own overload doesn't accept them) pass them at call time instead.
- **`ToolAnnotations` fields renamed to snake_case** (`readOnlyHint` → `read_only_hint`, `destructiveHint` → `destructive_hint`, etc.), with the camelCase name kept only as a Pydantic validation/serialization *alias* (matching the MCP wire protocol's own camelCase JSON, which is unchanged). Every `ToolAnnotations(readOnlyHint=True)`/`destructiveHint=True` construction call across the ~84 tool registrations in this codebase still works unmodified (confirmed live: `populate_by_name=True` accepts either name at construction), so those were deliberately left as-is rather than churned to snake_case for no functional benefit. The only real break was two test files reading `.readOnlyHint`/`.destructiveHint` back as attributes post-construction (only the real field name is readable that way in v2) — fixed in `tests/test_docs_comments.py` and `tests/test_docs_markdown_export.py`.

## Scope note

This decision only covers `server.py`'s two MCP *resources*. Every *tool* in this codebase already receives `ctx: Context` as an ordinary injected parameter (the pattern `get_spreadsheet_info` now also uses) and was entirely unaffected by the `get_context()` removal — tools never called it.
