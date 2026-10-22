"""Bearer-token authentication for the SSE and streamable-HTTP transports.

``BearerAuth`` is a pure-ASGI middleware. ``server.py`` wraps both HTTP apps as
``SingleResponseGuard(BearerAuth(app))``, around the app itself rather than at
launch, because ``--reload`` serves those apps by import string. With
``MCP_SERVER_TOKEN`` set, every ``http`` request (whatever its path) and every
``websocket`` without ``Authorization: Bearer <token>`` is refused; ``lifespan``
always passes through, or mcp's session manager never starts.

With no token the middleware still fails closed, so a launch that skips ``main()``
(``uvicorn mcp_gee_sweet.server:app --host 0.0.0.0``) isn't left open. It passes a
request only with a valid ``ALLOW_UNAUTHENTICATED_HTTP`` on a non-loopback ``HOST``,
or when the connection's
local address (``scope["server"]``, uvicorn's per-connection ``getsockname()``) is
loopback and the ``Host`` header names loopback. Never ``scope["client"]``: uvicorn's
proxy-headers middleware rewrites it from ``X-Forwarded-For``. The ``Host`` check
covers DNS rebinding, which mcp leaves off when ``app`` is built for a non-loopback
``HOST``. ``check_startup``, which ``main()`` runs for the HTTP transports only, is
the loud early error for the same rule; stdio, ``mcp-gee-sweet auth`` and the doc
generator import ``server`` and never trip it. Settings are read per request:
construction reads nothing and never raises.

Never log the token, anything derived from it, or the incoming ``Authorization``
header (CodeQL's clear-text-logging alert blocks merge; see CLAUDE.md).
"""

import hmac
import ipaddress
import logging
import os
import threading

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Messages spell these names out as literals rather than interpolating a
# *TOKEN*-named variable, which CodeQL treats as logging a secret.
_TOKEN_SETTING = "MCP_SERVER_TOKEN"
_OPT_OUT_SETTING = "ALLOW_UNAUTHENTICATED_HTTP"
_OPT_OUT_VALUES = ("1", "true")

# Same response for a missing and a wrong token, so a caller can't tell them apart.
_UNAUTHORIZED_HEADERS = [
    (b"content-type", b"text/plain; charset=utf-8"),
    (b"www-authenticate", b"Bearer"),
]
_UNAUTHORIZED_BODY = b"Unauthorized"
# RFC 6455 policy violation.
_WEBSOCKET_POLICY_VIOLATION = 1008
# Set after the first no-token rejection is logged at WARNING; later ones go to DEBUG.
_no_token_rejection_logged = threading.Event()


def _configured_secret() -> bytes | None:
    """The configured token as bytes, or None when it's unset, empty or whitespace."""
    value = os.environ.get(_TOKEN_SETTING, "").strip()
    return value.encode("utf-8") if value else None


def _opt_out_state() -> str:
    """ALLOW_UNAUTHENTICATED_HTTP as "on", "off" (unset or blank) or "invalid"."""
    value = os.environ.get(_OPT_OUT_SETTING, "").strip()
    if not value:
        return "off"
    return "on" if value.lower() in _OPT_OUT_VALUES else "invalid"


def is_loopback(host: str) -> bool:
    """Whether binding `host` keeps the server reachable from this machine only."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_startup(host: str, transport: str) -> None:
    """Stop an HTTP transport before it serves on an unsafe setting.

    Raises SystemExit with a one-line message, like an invalid LOCAL_FILE_ACCESS.
    """
    opt_out_state = _opt_out_state()
    if opt_out_state == "invalid":
        # The value isn't echoed: it's sometimes where a token gets pasted by mistake.
        raise SystemExit(
            "mcp-gee-sweet: ALLOW_UNAUTHENTICATED_HTTP isn't valid (use 1 or true, or unset it)"
        )
    opt_out = opt_out_state == "on"
    has_secret = _configured_secret() is not None

    if has_secret:
        if opt_out:
            logger.warning(
                "ALLOW_UNAUTHENTICATED_HTTP is ignored because MCP_SERVER_TOKEN is set; "
                "every request still needs the token"
            )
        return
    if is_loopback(host):
        return
    if opt_out:
        logger.warning(
            "Serving --transport %s on %s without authentication "
            "(ALLOW_UNAUTHENTICATED_HTTP is set). Anyone who can reach this address can "
            "call every tool, and there is no DNS-rebinding protection off loopback",
            transport,
            host,
        )
        return
    raise SystemExit(
        f"mcp-gee-sweet: refusing to serve --transport {transport} on {host} without "
        "authentication: set MCP_SERVER_TOKEN, set HOST to a loopback address such as "
        "127.0.0.1, or set ALLOW_UNAUTHENTICATED_HTTP=1 behind a reverse proxy that "
        "authenticates"
    )


def _authorized(scope: Scope, secret: bytes) -> bool:
    for name, value in scope.get("headers", ()):
        if name.lower() != b"authorization":
            continue
        scheme, _, credentials = value.strip().partition(b" ")
        if scheme.lower() != b"bearer":
            return False
        return hmac.compare_digest(credentials.strip(), secret)
    return False


def _host_header_is_loopback(scope: Scope) -> bool:
    """Whether the Host header is `localhost` or a loopback IP literal, with or without a
    port. The same rule as is_loopback, so any loopback HOST that starts is reachable.
    An IP literal can't be a DNS-rebinding name; `localhost` is the only name accepted."""
    for name, value in scope.get("headers", ()):
        if name.lower() != b"host":
            continue
        try:
            host = value.strip().decode("ascii")
        except UnicodeDecodeError:
            return False
        if host.startswith("["):
            address, bracket, rest = host[1:].partition("]")
            if not bracket or (rest and not rest.startswith(":")):
                return False
            # Only an IPv6 literal goes in brackets, never a name.
            return address.lower() != "localhost" and is_loopback(address)
        return is_loopback(host.partition(":")[0])
    return False


def _unauthenticated_allowed(scope: Scope, bind_host: str) -> bool:
    """With no token: a valid opt-out off loopback, or a loopback connection naming a
    loopback Host. The opt-out does nothing on a loopback `bind_host`: it's for a
    network-facing server behind a proxy, and must not lift the Host check there."""
    if _opt_out_state() == "on" and not is_loopback(bind_host):
        return True
    server = scope.get("server")
    if not server or not isinstance(server[0], str) or server[1] is None:
        # No address, or a Unix socket's (path, None).
        return False
    return is_loopback(server[0]) and _host_header_is_loopback(scope)


class BearerAuth:
    """Refuse HTTP and websocket requests without the configured bearer token.

    `host` is the address the app is built for (server.py's resolved HOST); it only
    decides whether ALLOW_UNAUTHENTICATED_HTTP applies.
    """

    def __init__(self, app: ASGIApp, host: str) -> None:
        self.app = app
        self.host = host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        secret = _configured_secret()
        if _authorized(scope, secret) if secret else _unauthenticated_allowed(scope, self.host):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else "-"
        if secret:
            logger.warning(
                "Rejected an unauthenticated request from %s to %s", client_ip, scope.get("path")
            )
        elif not _no_token_rejection_logged.is_set():
            # Once per process, so a scanner can't flood the log.
            _no_token_rejection_logged.set()
            logger.warning(
                "Rejected a request from %s to %s: MCP_SERVER_TOKEN is unset, so only "
                "loopback connections naming a loopback Host are served (further "
                "rejections are logged at DEBUG)",
                client_ip,
                scope.get("path"),
            )
        else:
            logger.debug("Rejected a request from %s to %s", client_ip, scope.get("path"))
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": _WEBSOCKET_POLICY_VIOLATION})
            return
        await send({"type": "http.response.start", "status": 401, "headers": _UNAUTHORIZED_HEADERS})
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
