"""Tests for SingleResponseGuard: a SIGTERM with an open SSE stream (#868, #917)."""

import json
import threading

import anyio
import pytest
from mcp.server.mcpserver import MCPServer
from sse_starlette import sse as sse_starlette_sse
from sse_starlette.sse import AppStatus

from mcp_gee_sweet.sse_shutdown import SingleResponseGuard

_HTTP_SCOPE = {"type": "http", "method": "GET", "path": "/sse"}


class _StrictSend:
    """Records sends, enforcing the ordering checks of uvicorn's h11 ``send``."""

    def __init__(self):
        self.messages = []
        self.started = False
        self.complete = False

    async def __call__(self, message):
        if not self.started:
            if message["type"] != "http.response.start":
                raise RuntimeError(
                    f"Expected ASGI message 'http.response.start', but got '{message['type']}'."
                )
            self.started = True
        elif not self.complete:
            if message["type"] != "http.response.body":
                raise RuntimeError(
                    f"Expected ASGI message 'http.response.body', but got '{message['type']}'."
                )
            if not message.get("more_body", False):
                self.complete = True
        else:
            raise RuntimeError(
                f"Unexpected ASGI message '{message['type']}' sent, after response already completed."
            )
        self.messages.append(message)


async def _never_receive():
    await anyio.sleep_forever()


def _app_sending(*messages):
    async def app(scope, receive, send):
        for message in messages:
            await send(message)

    return app


_START = {"type": "http.response.start", "status": 200, "headers": []}
_CHUNK = {"type": "http.response.body", "body": b"data: x\n\n", "more_body": True}
_END = {"type": "http.response.body", "body": b"", "more_body": False}


class TestSingleResponseGuard:
    @pytest.fixture
    def shutting_down(self, monkeypatch):
        monkeypatch.setattr(AppStatus, "should_exit", True)

    @pytest.fixture(autouse=True)
    def _not_shutting_down_by_default(self, monkeypatch):
        monkeypatch.setattr(AppStatus, "should_exit", False)

    @pytest.mark.parametrize("should_exit", [False, True])
    async def test_a_single_response_passes_through_untouched(self, monkeypatch, should_exit):
        monkeypatch.setattr(AppStatus, "should_exit", should_exit)
        send = _StrictSend()
        await SingleResponseGuard(_app_sending(_START, _CHUNK, _END))(
            _HTTP_SCOPE, _never_receive, send
        )
        assert send.messages == [_START, _CHUNK, _END]

    @pytest.mark.parametrize(
        "messages",
        [(_START, _CHUNK, _START, _END), (_START, _END, _START, _END)],
        ids=["open", "complete"],
    )
    async def test_before_shutdown_a_second_response_still_reaches_the_server(self, messages):
        # PR #911 QA round 1: outside shutdown a double response is a real bug, so
        # uvicorn must still see (and report) it, and an open stream isn't closed.
        send = _StrictSend()
        with pytest.raises(RuntimeError, match=r"'http\.response\.start'"):
            await SingleResponseGuard(_app_sending(*messages))(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == list(messages[:2])

    @pytest.mark.usefixtures("shutting_down")
    async def test_a_second_response_on_an_open_stream_closes_it_and_is_dropped(self):
        # The #868 shape: the stream is cut off without its closing body, then
        # mcp's empty Response() starts a second response on the same connection.
        send = _StrictSend()
        late_response = ({"type": "http.response.start", "status": 200, "headers": []}, _END)
        app = _app_sending(_START, _CHUNK, *late_response)
        await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _CHUNK, _END]
        assert send.complete

    @pytest.mark.usefixtures("shutting_down")
    async def test_a_second_response_after_a_complete_one_is_dropped(self):
        send = _StrictSend()
        app = _app_sending(_START, _END, _START, _END)
        await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _END]

    @pytest.mark.usefixtures("shutting_down")
    async def test_other_misuse_still_reaches_the_server(self):
        # Only a duplicate start is absorbed, even during shutdown; a body after
        # completion still raises.
        send = _StrictSend()
        app = _app_sending(_START, _END, _CHUNK)
        with pytest.raises(RuntimeError, match="after response already completed"):
            await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)

    @pytest.mark.usefixtures("shutting_down")
    async def test_a_response_cut_off_with_nothing_after_it_is_closed(self):
        # The #917 shape: streamable-http's handler just returns after the cut.
        send = _StrictSend()
        await SingleResponseGuard(_app_sending(_START, _CHUNK))(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _CHUNK, _END]
        assert send.complete

    async def test_before_shutdown_an_unfinished_response_is_left_for_the_server(self):
        # Outside shutdown it's a genuine bug, so uvicorn should still report it.
        send = _StrictSend()
        await SingleResponseGuard(_app_sending(_START, _CHUNK))(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _CHUNK]
        assert not send.complete

    @pytest.mark.usefixtures("shutting_down")
    async def test_an_app_that_never_started_a_response_gets_no_body(self):
        send = _StrictSend()
        await SingleResponseGuard(_app_sending())(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == []

    @pytest.mark.usefixtures("shutting_down")
    async def test_an_app_that_raises_mid_stream_is_not_closed_over(self):
        # A crash is uvicorn's to report; the guard only finishes a normal return.
        async def app(scope, receive, send):
            await send(_START)
            await send(_CHUNK)
            raise ValueError("boom")

        send = _StrictSend()
        with pytest.raises(ValueError, match="boom"):
            await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _CHUNK]

    async def test_non_http_scopes_pass_straight_through(self):
        seen = []

        async def app(scope, receive, send):
            seen.append((scope, send))

        def send(message):  # never wrapped, so never awaited
            raise AssertionError

        scope = {"type": "lifespan"}
        await SingleResponseGuard(app)(scope, _never_receive, send)
        assert seen == [(scope, send)]


class TestShutdownWithOpenSseStream:
    """mcp's real sse_app, shut down the way uvicorn's SIGTERM handler does."""

    @pytest.fixture(autouse=True)
    def _fresh_shutdown_state(self, monkeypatch):
        monkeypatch.setattr(AppStatus, "should_exit", False)
        # sse_starlette's shutdown watcher is per thread; don't inherit another test's.
        monkeypatch.setattr(sse_starlette_sse, "_thread_state", threading.local())

    @staticmethod
    async def _serve_then_shut_down(app):
        send = _StrictSend()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/sse",
            "raw_path": b"/sse",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:8000"), (b"accept", b"text/event-stream")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        }
        errors = []

        async def serve():
            try:
                await app(scope, _never_receive, send)
            except Exception as exc:  # what uvicorn logs as "Exception in ASGI application"
                errors.append(exc)

        with anyio.fail_after(10):
            async with anyio.create_task_group() as tg:
                tg.start_soon(serve)
                while not send.messages:  # the stream is open once its endpoint event is out
                    await anyio.sleep(0.01)
                AppStatus.should_exit = True
        return send, errors

    async def test_unguarded_app_reproduces_the_traceback(self):
        # Pins the premise: without the guard, mcp's sse_app hits uvicorn's check.
        _, errors = await self._serve_then_shut_down(MCPServer("t").sse_app(host="0.0.0.0"))
        assert len(errors) == 1
        assert "but got 'http.response.start'" in str(errors[0])

    async def test_guarded_app_shuts_down_cleanly(self):
        app = SingleResponseGuard(MCPServer("t").sse_app(host="0.0.0.0"))
        send, errors = await self._serve_then_shut_down(app)
        assert errors == []
        starts = [m for m in send.messages if m["type"] == "http.response.start"]
        assert len(starts) == 1
        assert send.messages[-1] == _END
        assert send.complete


def _http_scope(method, path, headers):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000"), *headers],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


class TestShutdownWithOpenStreamableHttpGetStream:
    """mcp's real streamable_http_app with an open ``GET /mcp`` stream at shutdown (#917)."""

    @pytest.fixture(autouse=True)
    def _fresh_shutdown_state(self, monkeypatch):
        monkeypatch.setattr(AppStatus, "should_exit", False)
        monkeypatch.setattr(sse_starlette_sse, "_thread_state", threading.local())

    @staticmethod
    def _receive_body(payload):
        # The transport reads the request body first, even for a GET, so deliver
        # it (empty for a GET, as uvicorn does), then block like an open connection.
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await anyio.sleep_forever()

        return receive

    async def _post(self, app, body, session_id=None):
        headers = [
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
        ]
        if session_id:
            headers.append((b"mcp-session-id", session_id.encode()))
        send = _StrictSend()
        await app(
            _http_scope("POST", "/mcp", headers),
            self._receive_body(json.dumps(body).encode()),
            send,
        )
        return dict(send.messages[0]["headers"]).get(b"mcp-session-id", b"").decode()

    async def _serve_get_then_shut_down(self, app, starlette_app):
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
        send = _StrictSend()
        errors = []
        async with starlette_app.router.lifespan_context(starlette_app):
            session_id = await self._post(app, initialize)
            assert session_id
            await self._post(
                app, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id
            )
            headers = [(b"accept", b"text/event-stream"), (b"mcp-session-id", session_id.encode())]

            async def serve():
                try:
                    await app(_http_scope("GET", "/mcp", headers), self._receive_body(b""), send)
                except Exception as exc:  # what uvicorn logs as "Exception in ASGI application"
                    errors.append(exc)

            with anyio.fail_after(10):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(serve)
                    while not send.messages:  # the stream is open once its headers are out
                        await anyio.sleep(0.01)
                    AppStatus.should_exit = True
        return send, errors

    async def test_unguarded_app_leaves_the_stream_unfinished(self):
        # Pins the premise: uvicorn's "ASGI callable returned without completing response".
        starlette_app = MCPServer("t").streamable_http_app(host="0.0.0.0")
        send, errors = await self._serve_get_then_shut_down(starlette_app, starlette_app)
        assert errors == []
        assert send.started and not send.complete

    async def test_guarded_app_closes_the_stream(self):
        starlette_app = MCPServer("t").streamable_http_app(host="0.0.0.0")
        guarded = SingleResponseGuard(starlette_app)
        send, errors = await self._serve_get_then_shut_down(guarded, starlette_app)
        assert errors == []
        assert send.messages[-1] == _END
        assert send.complete
