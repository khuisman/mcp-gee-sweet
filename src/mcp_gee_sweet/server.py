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
# Give our package a direct handler so uvicorn's dictConfig can't suppress DEBUG output.
if os.getenv("DEBUG"):
    _pkg_logger = logging.getLogger("mcp_gee_sweet")
    _pkg_logger.setLevel(logging.DEBUG)
    _h = logging.StreamHandler(sys.stderr)
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _pkg_logger.addHandler(_h)
    _pkg_logger.propagate = False

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from .auth import spreadsheet_lifespan  # noqa: E402


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


def _timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            logger.debug("%s took %.3fs", func.__name__, time.perf_counter() - start)

    return wrapper


def tool(annotations: ToolAnnotations | None = None):
    def decorator(func):
        tool_name = func.__name__
        if ENABLED_TOOLS is None or tool_name in ENABLED_TOOLS:
            timed = _timed(func)
            if annotations:
                return mcp.tool(annotations=annotations)(timed)
            else:
                return mcp.tool()(timed)
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
    context = mcp.get_lifespan_context()
    return _auth_status_json(context.auth_method)


@mcp.resource("spreadsheet://{spreadsheet_id}/info")
def get_spreadsheet_info(spreadsheet_id: str) -> str:
    """
    Get basic information about a Google Spreadsheet.

    Args:
        spreadsheet_id: The ID of the spreadsheet

    Returns:
        JSON string with spreadsheet information
    """
    context = mcp.get_lifespan_context()
    sheets_service = context.sheets_service

    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
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
