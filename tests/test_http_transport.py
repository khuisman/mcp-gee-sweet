"""Tests for http_transport.after_abandoned_calls (#907): a request abandoned to a
cancellation while its worker thread runs still lands, so the caller's cache
invalidation has to follow the thread, not the cancellation. Also the per-thread
transport's handling of a pooled connection that died while idle (#1052)."""

import socket
import ssl
import struct
import threading
import time
from unittest.mock import MagicMock, patch

import anyio
import httplib2
import pytest

from mcp_gee_sweet import http_transport


@pytest.fixture(autouse=True)
def _no_real_transport():
    # execute_in_thread builds a per-thread transport from the service's
    # credentials; these tests never make a real request.
    with patch.object(http_transport, "thread_http", return_value=MagicMock()):
        yield


def _blocking_execute(started: threading.Event, release: threading.Event, landed: list):
    def execute(**kwargs):
        started.set()
        release.wait(5)
        landed.append(True)
        return {}

    return execute


async def _wait_for(predicate, timeout=2.0):
    with anyio.fail_after(timeout):
        while not predicate():
            await anyio.sleep(0.01)


async def _cancel_once_started(execute, started):
    async with anyio.create_task_group() as tg:

        async def _call():
            await http_transport.execute_in_thread(execute, MagicMock())

        tg.start_soon(_call)
        await anyio.to_thread.run_sync(started.wait, 5)
        tg.cancel_scope.cancel()


async def test_callback_runs_after_abandoned_call_finishes():
    started, release, landed = threading.Event(), threading.Event(), []
    seen_landed = []
    with http_transport.after_abandoned_calls(lambda: seen_landed.append(bool(landed))):
        await _cancel_once_started(_blocking_execute(started, release, landed), started)
    # The cancellation has unwound, but the request hasn't landed yet.
    assert seen_landed == []
    release.set()
    await _wait_for(lambda: seen_landed)
    assert seen_landed == [True]


async def test_callback_not_run_for_a_call_that_completes():
    calls = []
    with http_transport.after_abandoned_calls(lambda: calls.append(1)):
        assert await http_transport.execute_in_thread(lambda **kw: {"ok": 1}, MagicMock()) == {
            "ok": 1
        }
    await anyio.sleep(0.05)
    assert calls == []


async def test_callback_not_run_for_a_call_that_raises():
    calls = []

    def execute(**kwargs):
        raise RuntimeError("boom")

    with (
        http_transport.after_abandoned_calls(lambda: calls.append(1)),
        pytest.raises(RuntimeError),
    ):
        await http_transport.execute_in_thread(execute, MagicMock())
    await anyio.sleep(0.05)
    assert calls == []


async def test_abandoned_call_that_then_raises_still_runs_callback():
    started, release = threading.Event(), threading.Event()
    calls = []

    def execute(**kwargs):
        started.set()
        release.wait(5)
        raise RuntimeError("landed with an error")

    with http_transport.after_abandoned_calls(lambda: calls.append(1)):
        await _cancel_once_started(execute, started)
    release.set()
    await _wait_for(lambda: calls)
    assert calls == [1]


async def test_no_callback_outside_the_block():
    started, release, landed = threading.Event(), threading.Event(), []
    calls = []
    with http_transport.after_abandoned_calls(lambda: calls.append(1)):
        pass
    await _cancel_once_started(_blocking_execute(started, release, landed), started)
    release.set()
    await _wait_for(lambda: landed)
    await anyio.sleep(0.05)
    assert calls == []


async def test_failing_callback_is_logged_not_raised():
    started, release, landed = threading.Event(), threading.Event(), []

    def boom():
        raise RuntimeError("callback boom")

    with (
        patch.object(http_transport, "logger") as mock_logger,
        http_transport.after_abandoned_calls(boom),
    ):
        await _cancel_once_started(_blocking_execute(started, release, landed), started)
        release.set()
        await _wait_for(lambda: mock_logger.exception.called)


class _ResettingServer:
    """Plain-HTTP keep-alive server that resets (RST) a connection left idle for
    `idle_reset` seconds: a local stand-in for Google's front end dropping a pooled
    connection while the MCP server sits idle (#1052)."""

    def __init__(self, idle_reset: float = 0.3):
        self.idle_reset = idle_reset
        self.connections = 0
        self.requests: list[bytes] = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen()
        self.url = f"http://127.0.0.1:{self._sock.getsockname()[1]}/"
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        conn.settimeout(self.idle_reset)
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    return
                self.requests.append(data.split(b" ", 1)[0])
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except TimeoutError:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        finally:
            conn.close()

    def close(self):
        self._sock.close()


@pytest.fixture
def resetting_server():
    server = _ResettingServer()
    yield server
    server.close()


def _transport():
    # A real httplib2.Http, so the dead pooled connection is a real socket.
    return http_transport._RefreshTrackingHttp(MagicMock(), http=httplib2.Http())


class TestStaleConnections:
    """#1052: a per-thread transport's pooled connection dies while the server idles."""

    def test_idle_transport_reconnects_instead_of_reusing(self, resetting_server):
        http = _transport()
        with patch.object(http_transport, "_IDLE_RECONNECT_SECONDS", 0.1):
            assert http.request(resetting_server.url, "POST", body="x")[0].status == 200
            time.sleep(0.6)  # past both the idle threshold and the server's reset
            # A POST isn't resent, so this passes only because the dead connection
            # was closed before the request instead of reused.
            assert http.request(resetting_server.url, "POST", body="x")[0].status == 200
        assert resetting_server.connections == 2

    def test_recently_used_transport_keeps_its_connection(self, resetting_server):
        http = _transport()
        http.request(resetting_server.url)
        http.request(resetting_server.url)
        assert resetting_server.connections == 1

    def test_get_on_a_dead_connection_is_resent_once(self, resetting_server):
        http = _transport()
        http.request(resetting_server.url)
        time.sleep(0.6)  # the server resets it, but it's within the idle threshold
        assert http.request(resetting_server.url)[0].status == 200
        assert resetting_server.connections == 2

    def test_write_on_a_dead_connection_is_not_resent(self, resetting_server):
        http = _transport()
        http.request(resetting_server.url)
        time.sleep(0.6)
        with pytest.raises(http_transport._CONNECTION_ERRORS):
            http.request(resetting_server.url, "POST", body="x")
        assert resetting_server.requests == [b"GET"]

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionResetError(54, "Connection reset by peer"),
            BrokenPipeError(32, "Broken pipe"),
            TimeoutError(60, "Operation timed out"),
            ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
        ],
    )
    def test_get_is_resent_at_most_once(self, error):
        inner = MagicMock()
        inner.connections = {}
        inner.request.side_effect = error
        http = http_transport._RefreshTrackingHttp(MagicMock(), http=inner)
        with pytest.raises(type(error)):
            http.request("https://sheets.googleapis.com/x")
        assert inner.request.call_count == 2

    def test_other_errors_are_not_resent(self):
        inner = MagicMock()
        inner.connections = {}
        inner.request.side_effect = ValueError("not a connection error")
        http = http_transport._RefreshTrackingHttp(MagicMock(), http=inner)
        with pytest.raises(ValueError):
            http.request("https://sheets.googleapis.com/x")
        assert inner.request.call_count == 1

    def test_refresh_reentry_does_not_resend_twice(self):
        # A 401 makes AuthorizedHttp refresh and call request() again; a connection
        # error there must not get a second resend on top of the outer call's.
        inner = MagicMock()
        inner.connections = {}
        unauthorized = MagicMock(status=401)
        inner.request.side_effect = [
            (unauthorized, b""),
            ConnectionResetError(54, "reset"),
            ConnectionResetError(54, "reset"),
        ]
        http = http_transport._RefreshTrackingHttp(MagicMock(), http=inner)
        with pytest.raises(ConnectionResetError):
            http.request("https://sheets.googleapis.com/x")
        assert inner.request.call_count == 3
