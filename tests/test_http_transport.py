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
import pytest

from mcp_gee_sweet import http_transport

# Captured before the autouse fixture below swaps thread_http out.
_real_thread_http = http_transport.thread_http


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
        buffer = b""
        try:
            while True:
                # One request is its headers plus Content-Length bytes of body,
                # however the client splits them across TCP segments.
                while b"\r\n\r\n" not in buffer:
                    data = conn.recv(65536)
                    if not data:
                        return
                    buffer += data
                head, buffer = buffer.split(b"\r\n\r\n", 1)
                length = 0
                for line in head.split(b"\r\n")[1:]:
                    name, _, value = line.partition(b":")
                    if name.strip().lower() == b"content-length":
                        length = int(value)
                while len(buffer) < length:
                    data = conn.recv(65536)
                    if not data:
                        return
                    buffer += data
                buffer = buffer[length:]
                self.requests.append(head.split(b" ", 1)[0])
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
    return http_transport._RefreshTrackingHttp(
        MagicMock(), http=http_transport._StaleConnectionHttp()
    )


@pytest.fixture
def quiet_server():
    # Never resets: every reconnect it sees is the client's own doing.
    server = _ResettingServer(idle_reset=60)
    yield server
    server.close()


def test_resetting_server_counts_a_split_post_once(quiet_server):
    # http.client can send a POST's body in its own segment; the fixture must still
    # see one request, or the `requests` assertions below flake.
    port = int(quiet_server.url.rsplit(":", 1)[1].strip("/"))
    with socket.create_connection(("127.0.0.1", port)) as client:
        client.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\n")
        time.sleep(0.05)
        client.sendall(b"hello")
        assert client.recv(65536).startswith(b"HTTP/1.1 200")
        time.sleep(0.1)  # let a miscounted body land before checking
    assert quiet_server.requests == [b"POST"]


class TestStaleConnections:
    """#1052: a per-thread transport's pooled connection dies while the server idles."""

    def test_thread_http_builds_the_stale_aware_transport(self):
        http = _real_thread_http(MagicMock())
        assert isinstance(http, http_transport._RefreshTrackingHttp)
        assert isinstance(http.http, http_transport._StaleConnectionHttp)
        assert isinstance(http._request, http_transport._ResendingRefreshRequest)

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

    def test_failed_write_does_not_leave_its_dead_connection_pooled(self, resetting_server):
        http = _transport()
        http.request(resetting_server.url)
        time.sleep(0.6)
        with pytest.raises(http_transport._CONNECTION_ERRORS):
            http.request(resetting_server.url, "POST", body="x")
        # The next write reconnects instead of failing on the same dead socket.
        assert http.request(resetting_server.url, "POST", body="x")[0].status == 200
        assert resetting_server.connections == 2

    def test_method_override_read_is_resent(self, resetting_server):
        # googleapiclient turns a GET with a URI over 2048 characters into this.
        http = _transport()
        http.request(resetting_server.url)
        time.sleep(0.6)
        response, _ = http.request(
            resetting_server.url,
            "POST",
            body="q=...",
            headers={"X-HTTP-Method-Override": "GET"},
        )
        assert response.status == 200
        assert resetting_server.requests == [b"GET", b"POST"]

    def test_idle_time_counts_system_sleep(self, quiet_server):
        # time.monotonic() stops while a laptop sleeps; a wall-clock jump of an hour
        # with no monotonic movement must still count as idle.
        http = _transport()
        http.request(quiet_server.url)
        now = time.time()
        with patch.object(http_transport.time, "time", return_value=now + 3600):
            http.request(quiet_server.url)
        assert quiet_server.connections == 2

    def test_clock_jumping_backward_also_reconnects(self, quiet_server):
        http = _transport()
        http.request(quiet_server.url)
        now = time.time()
        with patch.object(http_transport.time, "time", return_value=now - 3600):
            http.request(quiet_server.url)
        assert quiet_server.connections == 2

    def test_idle_is_tracked_per_connection(self, quiet_server):
        # A transport kept busy on one host still reconnects a second host's
        # connection that has sat idle, e.g. the token endpoint's between refreshes.
        other = _ResettingServer(idle_reset=60)
        try:
            http = _transport()
            with patch.object(http_transport, "_IDLE_RECONNECT_SECONDS", 0.3):
                http.request(other.url)
                for _ in range(5):
                    http.request(quiet_server.url)
                    time.sleep(0.1)
                http.request(other.url)
            assert quiet_server.connections == 1
            assert other.connections == 2
        finally:
            other.close()

    def test_refresh_on_a_dead_connection_is_resent_before_a_write(self, quiet_server):
        # The refresh runs before the write is sent, so resending it is safe even
        # though the write itself is never resent.
        token_server = _ResettingServer()
        refresh = {"due": True}

        def before_request(request, method, uri, headers):
            if refresh["due"]:
                request(token_server.url, method="POST", body="grant_type=refresh_token")

        creds = MagicMock()
        creds.before_request.side_effect = before_request
        try:
            http = http_transport._RefreshTrackingHttp(
                creds, http=http_transport._StaleConnectionHttp()
            )
            http.request(quiet_server.url, "POST", body="x")
            time.sleep(0.6)  # the token server resets its idle connection
            assert http.request(quiet_server.url, "POST", body="x")[0].status == 200
            assert token_server.connections == 2
            assert quiet_server.requests == [b"POST", b"POST"]
        finally:
            token_server.close()

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


class _SilentServer:
    """Accepts connections, reads requests, and never answers: a local stand-in for a
    pooled connection that died with no RST or FIN, so the client's next read would
    block until the OS gives up (#1129)."""

    def __init__(self):
        self.connections = 0
        self.requests: list[bytes] = []
        self._open: list[socket.socket] = []
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
            self._open.append(conn)
            threading.Thread(target=self._swallow, args=(conn,), daemon=True).start()

    def _swallow(self, conn):
        buffer = b""
        while True:
            try:
                data = conn.recv(65536)
            except OSError:
                return
            if not data:
                return
            buffer += data
            while b"\r\n\r\n" in buffer:
                head, buffer = buffer.split(b"\r\n\r\n", 1)
                self.requests.append(head.split(b" ", 1)[0])

    def close(self):
        self._sock.close()
        for conn in self._open:
            conn.close()


class _ResumeIncompleteServer:
    """Answers every request with Drive's resumable-upload "308 Resume Incomplete":
    a Range header and no Location."""

    def __init__(self):
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
            with conn:
                buffer = b""
                while b"\r\n\r\n" not in buffer:
                    data = conn.recv(65536)
                    if not data:
                        break
                    buffer += data
                conn.sendall(
                    b"HTTP/1.1 308 Resume Incomplete\r\nRange: bytes=0-4\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )

    def close(self):
        self._sock.close()


@pytest.fixture
def silent_server():
    server = _SilentServer()
    yield server
    server.close()


def _timing_out_transport(timeout=0.3):
    return http_transport._RefreshTrackingHttp(
        MagicMock(), http=http_transport._StaleConnectionHttp(timeout=timeout)
    )


class TestSocketTimeout:
    """#1129: a connection that dies silently must not hang a call until ETIMEDOUT."""

    def test_thread_http_sets_the_socket_timeout(self):
        http = _real_thread_http(MagicMock())
        assert http.http.timeout == http_transport._HTTP_TIMEOUT_SECONDS

    def test_default_matches_googleapiclient(self, monkeypatch):
        from googleapiclient.http import DEFAULT_HTTP_TIMEOUT_SEC

        monkeypatch.delenv("HTTP_TIMEOUT_SECONDS", raising=False)
        assert http_transport._http_timeout_seconds() == DEFAULT_HTTP_TIMEOUT_SEC

    def test_env_var_sets_the_timeout(self, monkeypatch):
        monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "300")
        assert http_transport._http_timeout_seconds() == 300

    @pytest.mark.parametrize("raw", ["abc", "0", "-5", "nan", ""])
    def test_invalid_env_var_falls_back_to_the_default(self, monkeypatch, raw):
        from googleapiclient.http import DEFAULT_HTTP_TIMEOUT_SEC

        monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", raw)
        with patch.object(http_transport, "logger") as mock_logger:
            assert http_transport._http_timeout_seconds() == DEFAULT_HTTP_TIMEOUT_SEC
        assert mock_logger.warning.called

    @pytest.mark.parametrize("raw", ["inf", "1e10", "86401"])
    def test_huge_env_var_is_capped(self, monkeypatch, raw):
        # Past the platform's time_t, connect() raises OverflowError on every request.
        monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", raw)
        with patch.object(http_transport, "logger") as mock_logger:
            assert http_transport._http_timeout_seconds() == 86400
        assert mock_logger.warning.called

    def test_the_cap_itself_is_accepted(self, monkeypatch):
        monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "86400")
        with patch.object(http_transport, "logger") as mock_logger:
            assert http_transport._http_timeout_seconds() == 86400
        assert not mock_logger.warning.called

    def test_capped_timeout_can_connect(self, quiet_server):
        http = _timing_out_transport(timeout=http_transport._MAX_HTTP_TIMEOUT_SECONDS)
        assert http.request(quiet_server.url)[0].status == 200

    def test_silent_read_times_out_after_one_resend(self, silent_server):
        http = _timing_out_transport()
        start = time.monotonic()
        with pytest.raises(TimeoutError) as excinfo:
            http.request(silent_server.url)
        # Two bounded waits, not a hang until the OS gives up.
        assert time.monotonic() - start < 5
        assert silent_server.requests == [b"GET", b"GET"]
        message = str(excinfo.value)
        assert "no data from Google for 0.3 s" in message
        assert "resent it once on a new connection" in message
        assert "HTTP_TIMEOUT_SECONDS" in message

    def test_silent_write_times_out_without_a_resend(self, silent_server):
        http = _timing_out_transport()
        with pytest.raises(TimeoutError) as excinfo:
            http.request(silent_server.url, "POST", body="x")
        assert silent_server.requests == [b"POST"]
        message = str(excinfo.value)
        assert "didn't resend it" in message
        assert "may still have applied it" in message
        assert "resent it once" not in message

    def test_timed_out_connection_is_not_reused(self, silent_server):
        # After a timeout the next request reconnects instead of reading the
        # previous request's late answer off the same socket.
        http = _timing_out_transport()
        with pytest.raises(TimeoutError):
            http.request(silent_server.url, "POST", body="x")
        with pytest.raises(TimeoutError):
            http.request(silent_server.url, "POST", body="x")
        assert silent_server.connections == 2

    def test_os_timeout_message_does_not_claim_the_socket_timeout(self):
        inner = MagicMock()
        inner.connections = {}
        inner.timeout = 60
        inner.request.side_effect = TimeoutError(60, "Operation timed out")
        http = http_transport._RefreshTrackingHttp(MagicMock(), http=inner)
        with pytest.raises(TimeoutError) as excinfo:
            http.request("https://sheets.googleapis.com/x", "POST", body="x")
        message = str(excinfo.value)
        assert "stopped responding" in message
        assert "60 s" not in message

    def test_other_connection_errors_keep_their_own_type(self):
        inner = MagicMock()
        inner.connections = {}
        inner.request.side_effect = ConnectionResetError(54, "reset")
        http = http_transport._RefreshTrackingHttp(MagicMock(), http=inner)
        with pytest.raises(ConnectionResetError):
            http.request("https://sheets.googleapis.com/x", "POST", body="x")


class TestMatchesBuildHttp:
    """#1129: the per-thread transport drifted from googleapiclient's build_http() on
    two settings. Compare against a live build_http() so the next one fails here."""

    def test_settings_match_build_http(self, monkeypatch):
        from googleapiclient.http import build_http

        monkeypatch.setattr(socket, "getdefaulttimeout", lambda: None)
        reference = build_http()
        ours = _real_thread_http(MagicMock()).http
        for name in ("timeout", "redirect_codes", "follow_redirects", "follow_all_redirects"):
            assert getattr(ours, name) == getattr(reference, name), name

    def test_only_known_attributes_differ(self, monkeypatch):
        # A setting build_http() starts setting in a later googleapiclient shows up
        # here as an unexpected difference.
        from googleapiclient.http import build_http

        monkeypatch.setattr(socket, "getdefaulttimeout", lambda: None)
        reference = vars(build_http())
        ours = vars(_real_thread_http(MagicMock()).http)
        differing = {
            name
            for name in reference.keys() | ours.keys()
            if not callable(reference.get(name)) and reference.get(name) != ours.get(name)
        }
        # Per-instance containers that compare by identity, not settings.
        per_instance = {
            "connections",
            "certificates",
            "credentials",
            "authorizations",
            "proxy_info",
        }
        assert differing <= per_instance, differing


class TestResumableUploadStatus:
    """#1129: Drive's "308 Resume Incomplete" is a resumable-upload status, not a
    redirect; httplib2 would raise RedirectMissingLocation on it."""

    def test_308_reaches_the_caller(self):
        server = _ResumeIncompleteServer()
        try:
            response, _ = _transport().request(server.url, "PUT", body="hello")
        finally:
            server.close()
        assert response.status == 308
        assert response["range"] == "bytes=0-4"

    def test_other_redirects_are_still_followed(self):
        assert 302 in http_transport._StaleConnectionHttp().redirect_codes
