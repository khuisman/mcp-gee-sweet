#!/usr/bin/env python
"""
Google Spreadsheet MCP Server
A Model Context Protocol (MCP) server built with MCPServer for interacting with Google Sheets.
"""

import functools
import importlib.metadata
import json
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.WARNING,  # keeps third-party HTTP response bodies out of logs
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
    force=True,
)
logger = logging.getLogger(__name__)
logging.getLogger("sse_starlette.sse").setLevel(logging.WARNING)  # suppress keepalive ping noise

# Startup version banner: confirming which build is running is basic operational
# info, not verbosity-gated debug output, so it gets its own always-on logger
# with a dedicated handler and propagate=False — independent of DEBUG_LEVEL and
# the root WARNING default above, which would otherwise silently swallow it
# (issue #356 QA round: a plain logger.info() call was blocked by root's
# inherited WARNING level when DEBUG_LEVEL was unset, and re-filtered by the
# DEBUG_LEVEL block's own handler level when it was set to anything above INFO).
_version_logger = logging.getLogger(f"{__name__}.version")
_version_logger.setLevel(logging.INFO)
_version_logger.propagate = False
_version_handler = logging.StreamHandler(sys.stderr)
_version_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
_version_logger.addHandler(_version_handler)
# DEBUG_LEVEL controls all package and access logging. Accepts standard level names (DEBUG, INFO, WARNING…).
if _level_name := os.getenv("DEBUG_LEVEL"):
    _level = getattr(logging, _level_name.upper(), logging.DEBUG)
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    # Package logger — give it a direct handler so uvicorn's dictConfig can't suppress it.
    _pkg_logger = logging.getLogger("mcp_gee_sweet")
    _pkg_logger.setLevel(_level)
    _h = logging.StreamHandler(sys.stderr)
    _h.setLevel(_level)
    _h.setFormatter(_fmt)
    _pkg_logger.addHandler(_h)
    if _log_file := os.getenv("LOG_FILE"):
        _fh = logging.FileHandler(_log_file)
        _fh.setLevel(_level)
        _fh.setFormatter(_fmt)
        _pkg_logger.addHandler(_fh)
    _pkg_logger.propagate = False

    # uvicorn access logger — stderr (Docker captures it) + optional file for local SSE.
    _access_fmt = logging.Formatter("%(asctime)s %(message)s")
    _access_logger = logging.getLogger("uvicorn.access")
    _access_logger.setLevel(_level)
    _access_h = logging.StreamHandler(sys.stderr)
    _access_h.setLevel(_level)
    _access_h.setFormatter(_access_fmt)
    _access_logger.addHandler(_access_h)
    _access_logger.propagate = False

    # mcp_gee_sweet.access — tool-level access log; propagates to parent for LOG_FILE.
    # Optional ACCESS_LOG_FILE writes access lines separately (nginx-style, no debug noise).
    if _access_log_file := os.getenv("ACCESS_LOG_FILE"):
        _tool_access_logger = logging.getLogger("mcp_gee_sweet.access")
        _tool_access_fh = logging.FileHandler(_access_log_file)
        _tool_access_fh.setLevel(logging.INFO)
        _tool_access_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        _tool_access_logger.addHandler(_tool_access_fh)

from mcp.server.mcpserver import Context, MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from .auth import execute_in_thread, get_lifespan_context, spreadsheet_lifespan  # noqa: E402


def _parse_enabled_tools() -> set | None:
    enabled_tools_str = None
    for i, arg in enumerate(sys.argv):
        if arg == "--include-tools" and i + 1 < len(sys.argv):
            enabled_tools_str = sys.argv[i + 1]
            break
    if not enabled_tools_str:
        enabled_tools_str = os.environ.get("ENABLED_TOOLS")
    if not enabled_tools_str:
        return None
    tools = {t.strip() for t in enabled_tools_str.split(",") if t.strip()}
    return tools if tools else None


ENABLED_TOOLS = _parse_enabled_tools()

_resolved_host = os.environ.get("HOST") or os.environ.get("FASTMCP_HOST") or "0.0.0.0"
_resolved_port_str = os.environ.get("PORT") or os.environ.get("FASTMCP_PORT") or "8000"
try:
    _resolved_port = int(_resolved_port_str)
except ValueError:
    _resolved_port = 8000

mcp = MCPServer(
    "Google Spreadsheet",
    dependencies=["google-auth", "google-auth-oauthlib", "google-api-python-client"],
    lifespan=spreadsheet_lifespan,
)

# mcp v2 moved host/port from the constructor to call-time kwargs on
# sse_app()/run_sse_async()/run() itself (confirmed live against mcp==2.0.0, issue #175)
app = mcp.sse_app(host=_resolved_host)


_tool_access_logger = logging.getLogger("mcp_gee_sweet.access")


def _timed(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        status = 200
        try:
            return await func(*args, **kwargs)
        except Exception:
            status = 500
            raise
        finally:
            elapsed = time.perf_counter() - start
            ctx = kwargs.get("ctx")
            req = getattr(ctx, "request_context", None)
            req = getattr(req, "request", req)  # unwrap if nested
            ip = getattr(getattr(req, "client", None), "host", None) or "-"
            ua = (getattr(req, "headers", None) or {}).get("user-agent", "-")
            _tool_access_logger.info(
                '"%s" %s "TOOL %s" %d %.3fs', ip, ua, func.__name__, status, elapsed
            )

    return wrapper


def _enforce_strict_tool_args(tool_name: str) -> None:
    """Reject unrecognized kwargs instead of silently ignoring them (issue #239).

    MCPServer's auto-generated per-tool pydantic arg model defaults to extra="ignore"
    (pydantic's own default) — neither func_metadata() nor Tool.from_function expose
    a public way to opt into extra="forbid". Verified absent in mcp 1.27.1 through
    2.0.0 (confirmed live against mcp==2.0.0, issue #175 — the private
    _tool_manager/fn_metadata/arg_model chain this function relies on is unchanged
    from v1 to v2). This reaches into
    private ToolManager/FuncMetadata internals to flip it after registration.
    model_rebuild(force=True) is REQUIRED: pydantic v2 bakes `extra` behavior into a
    compiled core schema at class-creation time, so mutating model_config alone is
    silently a no-op without it. If a future mcp upgrade has moved these internals,
    tests/test_server.py::TestToolStrictArgs will fail loudly in CI.
    """
    registered = mcp._tool_manager.get_tool(tool_name)
    arg_model = registered.fn_metadata.arg_model
    arg_model.model_config["extra"] = "forbid"
    arg_model.model_rebuild(force=True)


def tool(annotations: ToolAnnotations | None = None):
    def decorator(func):
        tool_name = func.__name__
        if ENABLED_TOOLS is None or tool_name in ENABLED_TOOLS:
            timed = _timed(func)
            if annotations:
                mcp.tool(annotations=annotations)(timed)
            else:
                mcp.tool()(timed)
            _enforce_strict_tool_args(tool_name)
            return timed
        return func

    return decorator


# Register all tools
from .tools import register_all  # noqa: E402

register_all(tool)


# Service-account restrictions fall into distinct failure classes with their own
# reason/alternatives text — bolting a new tool onto one class's reason string is
# wrong when its actual failure mode differs (issue #447: transfer_ownership fails
# because a service account has no personal Drive *identity*, not the storage-quota
# problem every other entry here shares).
_SA_LIMITATIONS = [
    {
        "category": "no_drive_storage_quota",
        "tools": [
            "create_spreadsheet",
            "create_doc",
            "copy_file",
            "upload_file",
            "upload_local_file",
            "upload_local_folder",
            "sync_folder",
        ],
        "reason": (
            "Service accounts have no Drive storage quota and cannot create "
            "or copy files in personal Drive. These tools will return an error "
            "unless a Shared Drive destination is used. For sync_folder, this "
            "only applies to its upload and bidirectional directions."
        ),
        "alternatives": "Switch to OAuth (CREDENTIALS_PATH) or ADC for full tool coverage.",
    },
    {
        "category": "no_personal_drive_identity",
        "tools": ["transfer_ownership"],
        "reason": (
            "Service accounts have no personal Drive identity to transfer file "
            "ownership to/from, so Drive's API rejects the transfer."
        ),
        # Deliberately doesn't offer ADC here: ADC may itself resolve to a
        # service-account-backed credential (metadata service, or
        # GOOGLE_APPLICATION_CREDENTIALS pointed at a key file) with the exact same
        # identity limitation, which auth.py's is_service_account_identity flag
        # (#506) now detects and folds into this same limited branch — but "switch
        # to ADC" still isn't a *fix* on its own, since a caller would have to
        # additionally know to point ADC at a real user credential specifically.
        "alternatives": "Switch to OAuth (CREDENTIALS_PATH) for full tool coverage.",
    },
]


def _sa_limitations_for(auth_method: str) -> list[dict]:
    """`_SA_LIMITATIONS`, with the quota category's `alternatives` adjusted when the
    caller is already on ADC (issue #506): telling an ADC session backed by a
    service account to "switch to ADC" is circular, since it's already there.
    """
    if auth_method != "adc":
        return _SA_LIMITATIONS
    adjusted = []
    for lim in _SA_LIMITATIONS:
        if lim["category"] == "no_drive_storage_quota":
            lim = {
                **lim,
                "alternatives": (
                    "Switch to OAuth (CREDENTIALS_PATH), or point ADC at a real "
                    "user credential (e.g. `gcloud auth application-default "
                    "login`) instead of a service-account-backed one."
                ),
            }
        adjusted.append(lim)
    return adjusted


def _auth_status_json(auth_method: str, is_service_account_identity: bool = False) -> str:
    """Return a JSON string describing the auth method and its Drive limitations.

    `is_service_account_identity` covers issue #506: `auth_method == "adc"` alone
    doesn't say whether `google.auth.default()` resolved to a real user or a
    service-account-backed credential (GCE/Cloud Run/GKE metadata identity, or
    `GOOGLE_APPLICATION_CREDENTIALS` pointed at a key file) — the latter has the
    exact same Drive limitations as `auth_method == "service_account"`, even though
    the auth *method* used to reach it was ADC.
    """
    if auth_method == "service_account" or is_service_account_identity:
        limitations = _sa_limitations_for(auth_method)
        return json.dumps(
            {
                "auth_method": auth_method,
                "is_service_account_identity": True,
                "can_create_in_personal_drive": False,
                "limited_tools": [t for lim in limitations for t in lim["tools"]],
                "limitations": limitations,
            },
            indent=2,
        )
    return json.dumps(
        {
            "auth_method": auth_method,
            "is_service_account_identity": False,
            "can_create_in_personal_drive": True,
            "limited_tools": [],
            "limitations": [],
        },
        indent=2,
    )


@mcp.resource("server://auth-status")
def get_auth_status() -> str:
    """
    Current authentication method and its Drive capability limitations.

    Returns a JSON summary of the active auth method and which tools are
    restricted. Useful for deciding which tools to attempt before calling them.
    """
    # mcp v2 dropped get_context() with no replacement for a static (non-templated)
    # resource — Context injection isn't supported there at all (confirmed live
    # against mcp==2.0.0, issue #175). SpreadsheetContext is a process-wide singleton
    # set once by the lifespan, so get_lifespan_context() reads it directly.
    context = get_lifespan_context()
    return _auth_status_json(context.auth_method, context.is_service_account_identity)


@mcp.resource("spreadsheet://{spreadsheet_id}/info")
async def get_spreadsheet_info(spreadsheet_id: str, ctx: Context) -> str:
    """
    Get basic information about a Google Spreadsheet.

    Args:
        spreadsheet_id: The ID of the spreadsheet

    Returns:
        JSON string with spreadsheet information
    """
    context = ctx.request_context.lifespan_context
    sheets_service = context.sheets_service

    spreadsheet = await execute_in_thread(
        sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute,
        sheets_service,
    )
    info = {
        "title": spreadsheet.get("properties", {}).get("title", "Unknown"),
        "sheets": [
            {
                "title": sheet["properties"]["title"],
                "sheetId": sheet["properties"]["sheetId"],
                "gridProperties": sheet["properties"].get("gridProperties", {}),
            }
            for sheet in spreadsheet.get("sheets", [])
        ],
    }

    return json.dumps(info, indent=2)


def main():
    try:
        version = importlib.metadata.version("mcp-gee-sweet")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    _version_logger.info("mcp-gee-sweet version %s", version)

    if ENABLED_TOOLS is not None:
        logger.debug("Tool filtering enabled. Active tools: %s", ", ".join(sorted(ENABLED_TOOLS)))
    else:
        logger.debug("Tool filtering disabled. All tools are enabled.")

    transport = "stdio"
    reload = False
    for i, arg in enumerate(sys.argv):
        if arg == "--transport" and i + 1 < len(sys.argv):
            transport = sys.argv[i + 1]
        if arg == "--reload":
            reload = True

    if reload and transport == "sse":
        import uvicorn

        uvicorn.run(
            "mcp_gee_sweet.server:app",
            host=_resolved_host,
            port=_resolved_port,
            reload=True,
        )
    elif transport == "stdio":
        mcp.run(transport=transport)
    else:
        # mcp v2 moved host/port from the constructor to call-time kwargs (see the
        # mcp.sse_app() call above) — stdio's own overload doesn't accept them.
        mcp.run(transport=transport, host=_resolved_host, port=_resolved_port)
