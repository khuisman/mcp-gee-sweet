"""Tests for http_auth.py: bearer-token auth on the SSE and streamable-HTTP apps, and
the startup check that refuses a network-facing server with no authentication."""

import logging

import anyio
import pytest
from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from mcp_gee_sweet import http_auth
from mcp_gee_sweet.http_auth import BearerAuth, check_startup, is_loopback
from mcp_gee_sweet.sse_shutdown import SingleResponseGuard

TOKEN = "s3cret-Token-value-0123456789"


class _Inner:
    """An ASGI app that records each scope it sees and answers 200."""

    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        elif scope["type"] == "lifespan":
            await receive()
            await send({"type": "lifespan.startup.complete"})


_LOOPBACK_SERVER = ("127.0.0.1", 8000)
# The address the app is built for: server.py's default HOST.
_BIND = "127.0.0.1"


def _call(
    app,
    scope_type="http",
    path="/mcp",
    headers=(),
    client=("192.168.1.99", 50000),
    server=_LOOPBACK_SERVER,
    host=b"127.0.0.1:8000",
):
    """Run one ASGI call against `app` and return the messages it sent. The defaults
    are a loopback connection naming a loopback Host, which passes with no token."""
    scope = {
        "type": scope_type,
        "path": path,
        "headers": ([(b"host", host)] if host is not None else []) + list(headers),
        "client": client,
        "server": server,
    }
    sent = []

    async def receive():
        if scope_type == "lifespan":
            return {"type": "lifespan.startup"}
        if scope_type == "websocket":
            return {"type": "websocket.connect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    anyio.run(app, scope, receive, send)
    return sent


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def _auth(value: bytes):
    return [(b"authorization", value)]


@pytest.fixture(autouse=True)
def _fresh_no_token_warning():
    http_auth._no_token_rejection_logged.clear()
    yield
    http_auth._no_token_rejection_logged.clear()


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_TOKEN", TOKEN)
    return TOKEN


class TestBearerAuth:
    def test_no_token_passes_a_loopback_connection_naming_a_loopback_host(self):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND))
        assert _status(sent) == 200
        assert len(inner.scopes) == 1

    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_empty_or_whitespace_token_is_unset(self, monkeypatch, value):
        monkeypatch.setenv("MCP_SERVER_TOKEN", value)
        inner = _Inner()
        assert _status(_call(BearerAuth(inner, host=_BIND))) == 200

    def test_correct_token_reaches_the_app(self, token):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND), headers=_auth(f"Bearer {token}".encode()))
        assert _status(sent) == 200
        assert len(inner.scopes) == 1

    @pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
    def test_scheme_is_case_insensitive(self, token, scheme):
        sent = _call(BearerAuth(_Inner(), host=_BIND), headers=_auth(f"{scheme} {token}".encode()))
        assert _status(sent) == 200

    def test_surrounding_whitespace_in_the_configured_token_is_ignored(self, monkeypatch):
        monkeypatch.setenv("MCP_SERVER_TOKEN", f"  {TOKEN}\n")
        sent = _call(BearerAuth(_Inner(), host=_BIND), headers=_auth(f"Bearer {TOKEN}".encode()))
        assert _status(sent) == 200

    @pytest.mark.parametrize(
        "headers",
        [
            [],
            _auth(b""),
            _auth(b"Bearer"),
            _auth(b"Bearer "),
            _auth(b"Bearer wrong-token"),
            _auth(f"Bearer {TOKEN}x".encode()),
            _auth(f"Bearer {TOKEN[:-1]}".encode()),
            _auth(f"Basic {TOKEN}".encode()),
            _auth(TOKEN.encode()),
            _auth("Bearer jeton-é-ü-日本".encode()),
            _auth(b"Bearer \xff\xfe\x80"),
        ],
        ids=[
            "missing",
            "empty",
            "scheme-only",
            "scheme-space",
            "wrong",
            "longer",
            "prefix",
            "basic-scheme",
            "no-scheme",
            "non-ascii-utf8",
            "non-utf8-bytes",
        ],
    )
    def test_missing_or_wrong_token_is_rejected_the_same_way(self, token, headers):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND), headers=headers)
        start = sent[0]
        assert start["status"] == 401
        assert (b"www-authenticate", b"Bearer") in start["headers"]
        assert inner.scopes == []
        # Identical to the missing-header response, so a caller can't tell a wrong
        # token from a missing one.
        assert sent == _call(BearerAuth(_Inner(), host=_BIND))

    @pytest.mark.parametrize("path", ["/sse", "/messages/", "/messages", "/mcp", "/", "/other"])
    def test_every_http_path_is_checked(self, token, path):
        inner = _Inner()
        assert _status(_call(BearerAuth(inner, host=_BIND), path=path)) == 401
        assert inner.scopes == []

    def test_lifespan_passes_through_with_a_token_set(self, token):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND), scope_type="lifespan")
        assert sent == [{"type": "lifespan.startup.complete"}]
        assert [s["type"] for s in inner.scopes] == ["lifespan"]

    def test_unauthenticated_websocket_is_closed(self, token):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND), scope_type="websocket")
        assert sent == [{"type": "websocket.close", "code": 1008}]
        assert inner.scopes == []

    def test_token_is_read_per_request_not_at_construction(self, monkeypatch):
        monkeypatch.delenv("MCP_SERVER_TOKEN", raising=False)
        app = BearerAuth(_Inner(), host=_BIND)
        monkeypatch.setenv("MCP_SERVER_TOKEN", TOKEN)
        assert _status(_call(app)) == 401

    def test_construction_never_raises_on_bad_settings(self, monkeypatch):
        monkeypatch.setenv("MCP_SERVER_TOKEN", "  ")
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", "maybe")
        BearerAuth(_Inner(), host=_BIND)

    def test_rejection_logs_client_and_path_but_never_the_token(self, token, caplog):
        with caplog.at_level(logging.DEBUG):
            _call(
                BearerAuth(_Inner(), host=_BIND),
                path="/messages/",
                headers=_auth(b"Bearer guessed-" + TOKEN.encode()),
            )
        assert "192.168.1.99" in caplog.text
        assert "/messages/" in caplog.text
        assert TOKEN not in caplog.text
        assert "guessed-" not in caplog.text

    def test_accepted_request_logs_nothing_about_the_token(self, token, caplog):
        with caplog.at_level(logging.DEBUG):
            _call(BearerAuth(_Inner(), host=_BIND), headers=_auth(f"Bearer {token}".encode()))
        assert TOKEN not in caplog.text


class TestNoTokenFailsClosed:
    """With no token the middleware itself refuses anything but a loopback connection
    naming a loopback Host, so a launch that skips main()'s check isn't left open."""

    def test_non_loopback_local_address_is_refused(self):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND), server=("192.168.1.5", 8000))
        assert _status(sent) == 401
        assert inner.scopes == []
        # The same response as a missing or wrong token.
        assert sent == _call(BearerAuth(_Inner(), host=_BIND), server=("0.0.0.0", 8000))

    @pytest.mark.parametrize("host", [b"evil.example:8000", b"evil.example", b"192.168.1.5:8000"])
    def test_loopback_connection_with_a_foreign_host_is_refused(self, host):
        # DNS rebinding: a web page reaching the server over a real loopback connection.
        assert _status(_call(BearerAuth(_Inner(), host=_BIND), host=host)) == 401

    def test_missing_host_header_is_refused(self):
        assert _status(_call(BearerAuth(_Inner(), host=_BIND), host=None)) == 401

    @pytest.mark.parametrize(
        "host",
        [
            b"localhost:8000",
            b"localhost",
            b"LocalHost:8000",
            b"127.0.0.1",
            b"127.0.0.1:8000",
            b"[::1]:8000",
            b"[::1]",
            b"127.0.0.2:8000",
            b"127.255.0.9",
            b"[0:0:0:0:0:0:0:1]:8000",
        ],
    )
    def test_loopback_host_names_pass(self, host):
        assert _status(_call(BearerAuth(_Inner(), host=_BIND), host=host)) == 200

    @pytest.mark.parametrize(
        "host",
        [
            b"[::1]x",
            b"[::1",
            b"[localhost]:8000",
            b"localhost.evil.example",
            b"127.0.0.1.evil.example:80",
            b"128.0.0.1",
            b"0177.0.0.1",
            b"::1",
            "127.0.0.1é".encode(),
        ],
    )
    def test_lookalike_host_names_are_refused(self, host):
        assert _status(_call(BearerAuth(_Inner(), host=_BIND), host=host)) == 401

    @pytest.mark.parametrize("server", [("::1", 8000), ("127.0.0.9", 8000)])
    def test_other_loopback_local_addresses_pass(self, server):
        assert _status(_call(BearerAuth(_Inner(), host=_BIND), server=server)) == 200

    def test_any_loopback_host_that_starts_is_reachable(self):
        # PR round-3 QA F1: check_startup accepts all of 127/8, so a 127.0.0.2 bind
        # must serve its own Host instead of answering 401 to everything.
        check_startup("127.0.0.2", "sse")
        sent = _call(
            BearerAuth(_Inner(), host="127.0.0.2"),
            server=("127.0.0.2", 8000),
            host=b"127.0.0.2:8000",
        )
        assert _status(sent) == 200

    @pytest.mark.parametrize("server", [None, ("/tmp/mcp.sock", None)], ids=["none", "uds"])
    def test_no_or_unix_socket_local_address_is_refused(self, server):
        assert _status(_call(BearerAuth(_Inner(), host=_BIND), server=server)) == 401

    @pytest.mark.parametrize("value", ["1", "true"])
    def test_valid_opt_out_passes_a_non_loopback_connection(self, monkeypatch, value):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", value)
        app = BearerAuth(_Inner(), host="0.0.0.0")
        sent = _call(app, server=("192.168.1.5", 8000), host=b"myhost:8000")
        assert _status(sent) == 200

    @pytest.mark.parametrize("bind", ["127.0.0.1", "127.0.0.2", "localhost", "::1"])
    def test_opt_out_does_nothing_on_a_loopback_bind(self, monkeypatch, bind):
        # QA F3: on a loopback HOST the opt-out must not lift the Host check, or a
        # rebinding page reaches the server (mcp's own check is off for 127.0.0.2).
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", "1")
        app = BearerAuth(_Inner(), host=bind)
        assert _status(_call(app, host=b"attacker.example:8000")) == 401
        assert _status(_call(app, server=("192.168.1.5", 8000))) == 401
        assert _status(_call(app)) == 200

    @pytest.mark.parametrize("value", ["yes", "0", "bogus"])
    def test_invalid_opt_out_is_off_and_never_raises(self, monkeypatch, value):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", value)
        sent = _call(BearerAuth(_Inner(), host=_BIND), server=("192.168.1.5", 8000))
        assert _status(sent) == 401

    def test_spoofed_loopback_client_doesnt_count(self):
        # uvicorn rewrites `client` from X-Forwarded-For; only `server` is trusted.
        sent = _call(
            BearerAuth(_Inner(), host=_BIND), client=("127.0.0.1", 50000), server=("10.0.0.2", 8000)
        )
        assert _status(sent) == 401

    def test_lifespan_passes_with_no_token(self):
        inner = _Inner()
        sent = _call(BearerAuth(inner, host=_BIND), scope_type="lifespan", server=None, host=None)
        assert sent == [{"type": "lifespan.startup.complete"}]

    def test_websocket_from_a_non_loopback_address_is_closed(self):
        sent = _call(
            BearerAuth(_Inner(), host=_BIND), scope_type="websocket", server=("192.168.1.5", 8000)
        )
        assert sent == [{"type": "websocket.close", "code": 1008}]

    def test_rejection_is_logged_once_at_warning_then_at_debug(self, caplog):
        app = BearerAuth(_Inner(), host=_BIND)
        with caplog.at_level(logging.DEBUG, logger=http_auth.logger.name):
            for _ in range(3):
                _call(app, server=("192.168.1.5", 8000))
            _call(BearerAuth(_Inner(), host=_BIND), server=("192.168.1.5", 8000))
        levels = [r.levelname for r in caplog.records]
        assert levels == ["WARNING", "DEBUG", "DEBUG", "DEBUG"]
        assert "MCP_SERVER_TOKEN is unset" in caplog.records[0].getMessage()
        assert "192.168.1.99" in caplog.records[0].getMessage()
        assert "/mcp" in caplog.records[0].getMessage()


class TestIsLoopback:
    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("127.0.0.1", True),
            ("127.0.0.9", True),
            ("::1", True),
            ("localhost", True),
            ("LocalHost", True),
            ("0.0.0.0", False),
            ("::", False),
            ("192.168.1.5", False),
            ("10.0.0.1", False),
            ("example.com", False),
            ("localhost.example.com", False),
            ("[::1]", False),
            ("", False),
        ],
    )
    def test_is_loopback(self, host, expected):
        assert is_loopback(host) is expected


class TestCheckStartup:
    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "myhost.lan"])
    def test_non_loopback_without_a_token_refuses_to_start(self, host):
        with pytest.raises(SystemExit) as exc:
            check_startup(host, "sse")
        message = str(exc.value.code)
        assert message.startswith("mcp-gee-sweet: ")
        assert "MCP_SERVER_TOKEN" in message
        assert "ALLOW_UNAUTHENTICATED_HTTP" in message
        assert host in message

    @pytest.mark.parametrize("value", ["", "   "])
    def test_empty_token_refuses_to_start(self, monkeypatch, value):
        monkeypatch.setenv("MCP_SERVER_TOKEN", value)
        with pytest.raises(SystemExit):
            check_startup("0.0.0.0", "streamable-http")

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_non_loopback_with_a_token_starts(self, token, transport):
        check_startup("0.0.0.0", transport)

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
    def test_loopback_without_a_token_starts(self, host):
        check_startup(host, "sse")

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", " true "])
    def test_opt_out_starts_without_a_token_and_warns(self, monkeypatch, caplog, value):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", value)
        with caplog.at_level(logging.WARNING, logger=http_auth.logger.name):
            check_startup("0.0.0.0", "sse")
        assert "without authentication" in caplog.text
        assert "0.0.0.0" in caplog.text

    @pytest.mark.parametrize("value", ["0", "false", "yes", "on", "2", "maybe"])
    @pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1"])
    def test_invalid_opt_out_value_refuses_to_start(self, monkeypatch, value, host):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", value)
        with pytest.raises(SystemExit) as exc:
            check_startup(host, "sse")
        message = str(exc.value.code)
        assert "ALLOW_UNAUTHENTICATED_HTTP" in message
        # The value isn't echoed: someone may have pasted the token there.
        assert f"{value!r}" not in message

    def test_invalid_opt_out_refuses_even_with_a_token(self, token, monkeypatch):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", "yes")
        with pytest.raises(SystemExit):
            check_startup("0.0.0.0", "sse")

    def test_empty_opt_out_is_unset(self, monkeypatch):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", "")
        with pytest.raises(SystemExit):
            check_startup("0.0.0.0", "sse")

    def test_token_and_opt_out_enforces_the_token_and_warns(self, token, monkeypatch, caplog):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", "1")
        with caplog.at_level(logging.WARNING, logger=http_auth.logger.name):
            check_startup("0.0.0.0", "sse")
        assert "ALLOW_UNAUTHENTICATED_HTTP is ignored" in caplog.text
        assert _status(_call(BearerAuth(_Inner(), host=_BIND))) == 401

    def test_opt_out_on_loopback_is_a_no_op(self, monkeypatch, caplog):
        monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", "1")
        with caplog.at_level(logging.WARNING, logger=http_auth.logger.name):
            check_startup("127.0.0.1", "sse")
        assert caplog.text == ""

    @pytest.mark.parametrize("opt_out", [None, "1", "bogus"])
    @pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1"])
    def test_logs_and_messages_never_contain_the_token(
        self, token, monkeypatch, caplog, opt_out, host
    ):
        if opt_out is not None:
            monkeypatch.setenv("ALLOW_UNAUTHENTICATED_HTTP", opt_out)
        with caplog.at_level(logging.DEBUG):
            try:
                check_startup(host, "sse")
            except SystemExit as exc:
                assert TOKEN not in str(exc.code)
        assert TOKEN not in caplog.text


_MCP_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class TestStreamableHttpEndToEnd:
    """A real mcp streamable-HTTP app behind the same wrapping main() serves. A throwaway
    MCPServer with no lifespan keeps this off Google credentials."""

    def _app(self):
        app = MCPServer("t").streamable_http_app(host="127.0.0.1")
        return SingleResponseGuard(BearerAuth(app, host="127.0.0.1"))

    def test_initialize_works_with_the_token(self, token):
        # The ASGI lifespan must reach mcp's app, or its session manager never starts
        # and every request fails.
        with TestClient(self._app(), base_url="http://127.0.0.1:8000") as client:
            r = client.post(
                "/mcp",
                headers={**_MCP_HEADERS, "Authorization": f"Bearer {token}"},
                json=_MCP_INIT,
            )
        assert r.status_code == 200
        assert "mcp-session-id" in r.headers

    def test_initialize_without_the_token_is_rejected(self, token):
        with TestClient(self._app(), base_url="http://127.0.0.1:8000") as client:
            r = client.post("/mcp", headers=_MCP_HEADERS, json=_MCP_INIT)
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
