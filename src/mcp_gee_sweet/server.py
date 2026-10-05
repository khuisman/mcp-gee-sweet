#!/usr/bin/env python
"""
Google Spreadsheet MCP Server
A Model Context Protocol (MCP) server built with MCPServer for interacting with Google Sheets.
"""

import argparse
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

from google.auth.exceptions import GoogleAuthError, RefreshError  # noqa: E402
from googleapiclient.errors import Error as GoogleApiClientError  # noqa: E402
from httplib2 import HttpLib2Error  # noqa: E402
from mcp.server.mcpserver import Context, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ResourceError, ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from .auth import (  # noqa: E402
    MissingOAuthScopesError,
    execute_in_thread,
    get_gmail_unauthorized_message,
    get_lifespan_context,
    reauthorize_instructions,
    run_auth_command,
    set_gmail_enabled,
    set_interactive_consent,
    set_raise_auth_failures,
    spreadsheet_lifespan,
)


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


def _lifespan(ctx):
    """This call's own lifespan context (per connection under SSE, #811), or None."""
    return getattr(getattr(ctx, "request_context", None), "lifespan_context", None)


def _unauthorized_message(ctx) -> str | None:
    """The degraded-start message on this call's own lifespan context, if any. Per
    connection: under SSE each connection runs its own lifespan (#811)."""
    message = getattr(_lifespan(ctx), "unauthorized_message", None)
    return message if isinstance(message, str) else None


# Failures a caller can act on: auth problems, Google API client errors, network
# failures, bad arguments a tool rejects with ValueError, and local file errors. From
# mcp 2.3, only ToolError/ResourceError text reaches the client; any other exception
# becomes a bare "Error executing tool <name>" (#872). So these are re-raised as
# ToolError (or ResourceError, for a resource) with their own text. Anything else is a
# crash: mcp withholds its text from the client and logs the traceback.
_CLIENT_VISIBLE_ERRORS = (
    MissingOAuthScopesError,
    GoogleApiClientError,
    GoogleAuthError,
    HttpLib2Error,
    ValueError,
    OSError,
)


def _client_error(exc: Exception, ctx) -> tuple[str, int] | None:
    """The text the client should see for `exc` and the access-log status, or None to
    leave it to mcp as a crash."""
    if isinstance(exc, GoogleAuthError) and exc.args and isinstance(exc.args[0], str):
        # google-auth raises e.g. RefreshError(message, response_dict), whose str()
        # is the tuple's repr.
        text = exc.args[0]
    else:
        text = str(exc) or type(exc).__name__
    if isinstance(exc, RefreshError) and getattr(_lifespan(ctx), "auth_method", None) == "oauth":
        # A refresh token revoked or expired after startup: same fix as #811.
        return (
            f"Google rejected the OAuth token refresh: {text.rstrip('.')}. "
            f"{reauthorize_instructions()}",
            401,
        )
    if isinstance(exc, MissingOAuthScopesError):
        return text, 401
    if isinstance(exc, _CLIENT_VISIBLE_ERRORS):
        return text, 500
    return None


def _client_visible(
    exc: Exception, ctx, error_cls: type[Exception]
) -> tuple[Exception, int] | None:
    """`exc` as `error_cls` (ToolError or ResourceError) plus its access-log status, or
    None for a crash. mcp logs a ToolError/ResourceError without a traceback, and one of
    these can still be our own bug (a malformed request's HttpError 400, a
    JSONDecodeError), so the original is logged here with its traceback first."""
    if (client_error := _client_error(exc, ctx)) is None:
        return None
    message, status = client_error
    logger.warning("Reporting %s to the client: %s", type(exc).__name__, exc, exc_info=exc)
    return error_cls(message), status


def _timed(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        status = 200
        try:
            # Degraded start (#811): this connection has no Google services, so no
            # tool can run. Raised rather than returned so it works whatever the
            # tool's return type, and as a ToolError so mcp shows the client its text.
            if unauthorized := _unauthorized_message(kwargs.get("ctx")):
                status = 401
                raise ToolError(unauthorized)
            return await func(*args, **kwargs)
        except ToolError:
            if status == 200:
                status = 500
            raise
        except Exception as e:
            status = 500
            if (visible := _client_visible(e, kwargs.get("ctx"), ToolError)) is None:
                raise
            error, status = visible
            raise error from e
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
    2.3.0 (confirmed live against mcp==2.0.0, issue #175, and re-checked against the
    locked mcp==2.3.0, #872 — the private _tool_manager/fn_metadata/arg_model chain
    this function relies on is unchanged from v1 through 2.3). This reaches into
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


# Modules that registered at least one tool, so auth can request a domain's scopes
# only when that domain has a registered tool (#790).
_registered_tool_modules: set[str] = set()


def tool(annotations: ToolAnnotations | None = None):
    def decorator(func):
        tool_name = func.__name__
        if ENABLED_TOOLS is None or tool_name in ENABLED_TOOLS:
            _registered_tool_modules.add(func.__module__)
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
from .tools import gmail as _gmail_tools  # noqa: E402
from .tools import register_all  # noqa: E402

register_all(tool)
# Runs before the lifespan (i.e. before auth), so Gmail's mailbox scope is only
# requested when an ENABLED_TOOLS filter leaves at least one Gmail tool in (#790).
set_gmail_enabled(_gmail_tools.__name__ in _registered_tool_modules)


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
    {
        "category": "no_user_mailbox",
        "tools": [
            "list_messages",
            "get_message",
            "list_threads",
            "get_thread",
            "list_labels",
            "send_message",
            "create_draft",
            "send_draft",
            "reply_to_message",
            "modify_labels",
            "trash_message",
        ],
        "reason": (
            "Service accounts have no Gmail mailbox of their own, and acting on a "
            "user's mailbox via domain-wide delegation isn't wired up yet, so every "
            "Gmail tool fails."
        ),
        # Same reasoning as no_personal_drive_identity above for not offering ADC.
        "alternatives": "Switch to OAuth (CREDENTIALS_PATH) to use the Gmail tools.",
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


def _auth_status_json(
    auth_method: str,
    is_service_account_identity: bool = False,
    gmail_unauthorized: str | None = None,
    oauth_unauthorized: str | None = None,
) -> str:
    """Return a JSON string describing the auth method and its Drive limitations.

    `oauth_unauthorized` is the context's `unauthorized_message`: set when the
    server started without any Google access because OAuth needs consent it couldn't
    ask for (#811). Every tool is limited then, reported as `"*"`.

    `gmail_unauthorized` is `auth.get_gmail_unauthorized_message()`: set when an
    OAuth token is missing only the Gmail scope, so the server started without Gmail
    (#790). Reported as its own limitation so a client can see it before calling a
    Gmail tool, not only from that tool's error.

    `is_service_account_identity` covers issue #506: `auth_method == "adc"` alone
    doesn't say whether `google.auth.default()` resolved to a real user or a
    service-account-backed credential (GCE/Cloud Run/GKE metadata identity, or
    `GOOGLE_APPLICATION_CREDENTIALS` pointed at a key file) — the latter has the
    exact same Drive limitations as `auth_method == "service_account"`, even though
    the auth *method* used to reach it was ADC.
    """
    if oauth_unauthorized:
        return json.dumps(
            {
                "auth_method": auth_method,
                "is_service_account_identity": False,
                "can_create_in_personal_drive": False,
                "limited_tools": ["*"],
                "limitations": [
                    {
                        "category": "oauth_not_authorized",
                        "tools": ["*"],
                        "reason": oauth_unauthorized,
                        "alternatives": reauthorize_instructions(),
                    }
                ],
            },
            indent=2,
        )
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
    limitations = []
    if gmail_unauthorized:
        mailbox = next(lim for lim in _SA_LIMITATIONS if lim["category"] == "no_user_mailbox")
        limitations.append(
            {
                "category": "gmail_not_authorized",
                "tools": mailbox["tools"],
                "reason": gmail_unauthorized,
                "alternatives": f"{reauthorize_instructions()} Or leave the Gmail tools "
                "out of ENABLED_TOOLS.",
            }
        )
    return json.dumps(
        {
            "auth_method": auth_method,
            "is_service_account_identity": False,
            "can_create_in_personal_drive": True,
            "limited_tools": [t for lim in limitations for t in lim["tools"]],
            "limitations": limitations,
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
    return _auth_status_json(
        context.auth_method,
        context.is_service_account_identity,
        get_gmail_unauthorized_message(),
        context.unauthorized_message,
    )


@mcp.resource("spreadsheet://{spreadsheet_id}/info")
async def get_spreadsheet_info(spreadsheet_id: str, ctx: Context) -> str:
    """
    Get basic information about a Google Spreadsheet.

    Args:
        spreadsheet_id: The ID of the spreadsheet

    Returns:
        JSON string with spreadsheet information
    """
    if unauthorized := _unauthorized_message(ctx):
        raise ResourceError(unauthorized)
    context = ctx.request_context.lifespan_context
    sheets_service = context.sheets_service

    try:
        spreadsheet = await execute_in_thread(
            sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute,
            sheets_service,
        )
    except Exception as e:
        # Same rule as _timed: mcp 2.3 withholds a non-ResourceError's text (#872).
        if (visible := _client_visible(e, ctx, ResourceError)) is None:
            raise
        raise visible[0] from e
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


# Server options that take a value, so their value isn't mistaken for a subcommand.
_VALUE_OPTIONS = {"--include-tools", "--transport"}


def _is_auth_command(argv: list[str]) -> bool:
    """Whether the positional `auth` subcommand appears anywhere in argv, so
    `mcp-gee-sweet --include-tools X auth` works as well as `auth --include-tools X`."""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in _VALUE_OPTIONS:
            i += 2
            continue
        if arg == "auth":
            return True
        i += 1
    return False


def _auth_main(argv: list[str]) -> int:
    """`mcp-gee-sweet auth` (#811). Strict about its flags: a typo like --no-browswer
    would otherwise silently open a browser. Tool registration has already run at
    import, so --include-tools / ENABLED_TOOLS narrow the scopes the same way they
    do for the server."""
    parser = argparse.ArgumentParser(
        prog="mcp-gee-sweet auth",
        description="Authorize OAuth access and save the token to TOKEN_PATH.",
    )
    parser.add_argument("auth")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="print the consent URL instead of opening a browser",
    )
    parser.add_argument(
        "--include-tools",
        help="comma-separated tools the server will register; narrows the scopes",
    )
    args = parser.parse_args(argv)
    return run_auth_command(open_browser=not args.no_browser)


def main():
    if _is_auth_command(sys.argv[1:]):
        sys.exit(_auth_main(sys.argv[1:]))

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
        # stdout is the protocol channel and nobody is watching for a browser tab, so
        # a missing token degrades instead of running the consent flow (#811).
        set_interactive_consent(False)
        # A failed auth stops a stdio server outright (#790); other transports start
        # the connection without Google access instead (PR #867).
        set_raise_auth_failures(True)
        mcp.run(transport=transport)
    else:
        # mcp v2 moved host/port from the constructor to call-time kwargs (see the
        # mcp.sse_app() call above) — stdio's own overload doesn't accept them.
        mcp.run(transport=transport, host=_resolved_host, port=_resolved_port)
