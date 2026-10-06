"""Tests for SingleResponseGuard: a SIGTERM with an open SSE stream (#868)."""

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
    async def test_a_single_response_passes_through_untouched(self):
        send = _StrictSend()
        await SingleResponseGuard(_app_sending(_START, _CHUNK, _END))(
            _HTTP_SCOPE, _never_receive, send
        )
        assert send.messages == [_START, _CHUNK, _END]

    async def test_a_second_response_on_an_open_stream_closes_it_and_is_dropped(self):
        # The #868 shape: the stream is cut off without its closing body, then
        # mcp's empty Response() starts a second response on the same connection.
        send = _StrictSend()
        late_response = ({"type": "http.response.start", "status": 200, "headers": []}, _END)
        app = _app_sending(_START, _CHUNK, *late_response)
        await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _CHUNK, _END]
        assert send.complete

    async def test_a_second_response_after_a_complete_one_is_dropped(self):
        send = _StrictSend()
        app = _app_sending(_START, _END, _START, _END)
        await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)
        assert send.messages == [_START, _END]

    async def test_other_misuse_still_reaches_the_server(self):
        # Only a duplicate start is absorbed; a body after completion still raises.
        send = _StrictSend()
        app = _app_sending(_START, _END, _CHUNK)
        with pytest.raises(RuntimeError, match="after response already completed"):
            await SingleResponseGuard(app)(_HTTP_SCOPE, _never_receive, send)

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
