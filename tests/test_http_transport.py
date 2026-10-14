"""Tests for http_transport.after_abandoned_calls (#907): a request abandoned to a
cancellation while its worker thread runs still lands, so the caller's cache
invalidation has to follow the thread, not the cancellation."""

import threading
from unittest.mock import MagicMock, patch

import anyio
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
