#!/usr/bin/env python
"""
Google Spreadsheet MCP Server
A Model Context Protocol (MCP) server built with FastMCP for interacting with Google Sheets.
"""

import functools
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

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from .auth import execute_in_thread, spreadsheet_lifespan  # noqa: E402


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

mcp = FastMCP(
    "Google Spreadsheet",
    dependencies=["google-auth", "google-auth-oauthlib", "google-api-python-client"],
    lifespan=spreadsheet_lifespan,
    host=_resolved_host,
    port=_resolved_port,
)

app = mcp.sse_app()


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

    FastMCP's auto-generated per-tool pydantic arg model defaults to extra="ignore"
    (pydantic's own default) — neither func_metadata() nor Tool.from_function expose
    a public way to opt into extra="forbid". Verified absent in mcp 1.27.1 through
    1.28.1 (this project's full allowed range, mcp>=1.27.0,<2.0.0). This reaches into
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


_SA_LIMITED_TOOLS = [
    "create_spreadsheet",
    "create_doc",
    "copy_file",
    "upload_file",
    "upload_local_file",
    "upload_local_folder",
    "sync_folder (upload and bidirectional directions)",
]


def _auth_status_json(auth_method: str) -> str:
    """Return a JSON string describing the auth method and its Drive limitations."""
    if auth_method == "service_account":
        return json.dumps(
            {
                "auth_method": "service_account",
                "can_create_in_personal_drive": False,
                "limited_tools": _SA_LIMITED_TOOLS,
                "reason": (
                    "Service accounts have no Drive storage quota and cannot create "
                    "or copy files in personal Drive. These tools will return an error "
                    "unless a Shared Drive destination is used."
                ),
                "alternatives": "Switch to OAuth (CREDENTIALS_PATH) or ADC for full tool coverage.",
            },
            indent=2,
        )
    return json.dumps(
        {
            "auth_method": auth_method,
            "can_create_in_personal_drive": True,
            "limited_tools": [],
            "reason": None,
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
    context = mcp.get_context().request_context.lifespan_context
    return _auth_status_json(context.auth_method)


@mcp.resource("spreadsheet://{spreadsheet_id}/info")
async def get_spreadsheet_info(spreadsheet_id: str) -> str:
    """
    Get basic information about a Google Spreadsheet.

    Args:
        spreadsheet_id: The ID of the spreadsheet

    Returns:
        JSON string with spreadsheet information
    """
    context = mcp.get_context().request_context.lifespan_context
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
    else:
        mcp.run(transport=transport)
