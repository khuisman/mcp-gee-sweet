"""Tests for batch_retry.send_dropping_failed_images, shared by the body and the table fill."""

import pytest

from mcp_gee_sweet.tools.docs.batch_retry import send_dropping_failed_images


class _Fails(Exception):
    def __init__(self, index: int):
        self.index = index


def _requests(*names: str) -> list[dict]:
    return [{"name": n} for n in names]


class _Batches:
    """run_batch fake: a batch holding a bad request fails naming the first one."""

    def __init__(self, bad: set[str], other_error: Exception | None = None):
        self.bad = bad
        self.other_error = other_error
        self.sent: list[list[str]] = []

    async def __call__(self, requests: list[dict]) -> None:
        names = [r["name"] for r in requests]
        self.sent.append(names)
        for i, n in enumerate(names):
            if n in self.bad:
                raise _Fails(i)
        if self.other_error is not None and "tail" in names:
            raise self.other_error


def _drop(requests: list[dict], e: Exception) -> int | None:
    if not isinstance(e, _Fails):
        return None
    requests.pop(e.index)
    return e.index


class TestSendDroppingFailedImages:
    async def test_no_failure_sends_once(self):
        batches = _Batches(set())
        applied = await send_dropping_failed_images(
            _requests("a", "b"), batches, _drop, lambda *_: 0
        )
        assert batches.sent == [["a", "b"]]
        assert [r["name"] for r in applied] == ["a", "b"]

    async def test_first_failure_resends_whole_batch(self):
        batches = _Batches({"b"})
        applied = await send_dropping_failed_images(
            _requests("a", "b", "c"), batches, _drop, lambda _r, index: index
        )
        assert batches.sent == [["a", "b", "c"], ["a", "c"]]
        assert [r["name"] for r in applied] == ["a", "c"]

    async def test_second_failure_splits_at_split_point(self):
        batches = _Batches({"b", "d"})
        landed: list[list[str]] = []
        applied = await send_dropping_failed_images(
            _requests("a", "b", "c", "d", "e"),
            batches,
            _drop,
            lambda _r, index: index,
            lambda batch: landed.append([r["name"] for r in batch]),
        )
        assert batches.sent == [
            ["a", "b", "c", "d", "e"],
            ["a", "c", "d", "e"],
            ["a", "c"],
            ["e"],
        ]
        assert landed == [["a", "c"], ["e"]]
        assert [r["name"] for r in applied] == ["a", "c", "e"]

    async def test_split_point_zero_keeps_whole_list_retries(self):
        batches = _Batches({"b", "d"})
        await send_dropping_failed_images(
            _requests("a", "b", "c", "d"), batches, _drop, lambda *_: 0
        )
        assert batches.sent == [["a", "b", "c", "d"], ["a", "c", "d"], ["a", "c"]]

    async def test_other_error_raises_after_head_landed(self):
        # The head of a split is applied before the rest fails for another reason;
        # on_applied has already reported it.
        batches = _Batches({"b", "d"}, other_error=RuntimeError("500"))
        landed: list[list[str]] = []
        with pytest.raises(RuntimeError):
            await send_dropping_failed_images(
                _requests("a", "b", "c", "d", "tail"),
                batches,
                _drop,
                lambda _r, index: index,
                lambda batch: landed.append([r["name"] for r in batch]),
            )
        assert landed == [["a", "c"]]

    async def test_every_request_dropped_returns_what_landed(self):
        batches = _Batches({"a", "b"})
        applied = await send_dropping_failed_images(
            _requests("a", "b"), batches, _drop, lambda *_: 0
        )
        assert applied == []
