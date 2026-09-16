"""Tests for tools/concurrency.py — shared per-item progress/gather helpers,
extracted from 5 duplicated call sites (issue #355, QA review PR #758)."""

from unittest.mock import AsyncMock, MagicMock

from mcp_gee_sweet.tools.concurrency import gather_with_fallback, report_progress_safe


class TestReportProgressSafe:
    async def test_forwards_args_to_ctx_report_progress(self):
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()
        await report_progress_safe(ctx, 2, 5, "item: ok", "item")
        ctx.report_progress.assert_awaited_once_with(2, 5, "item: ok")

    async def test_swallows_report_progress_failure(self):
        """PR #351's original guard: a broken notification channel must not raise
        out of the caller — the caller's own already-computed result stands
        regardless of notification-channel failure."""
        ctx = MagicMock()
        ctx.report_progress = AsyncMock(side_effect=RuntimeError("connection dropped"))
        await report_progress_safe(ctx, 1, 1, "item: ok", "item")  # must not raise


class TestGatherWithFallback:
    async def test_preserves_order_and_results(self):
        async def double(x: int) -> int:
            return x * 2

        result = await gather_with_fallback([1, 2, 3], double, lambda x, e: -1)
        assert result == [2, 4, 6]

    async def test_exception_replaced_by_fallback_without_losing_order(self):
        async def maybe_fail(x: int) -> int:
            if x == 2:
                raise ValueError("boom")
            return x * 2

        result = await gather_with_fallback([1, 2, 3], maybe_fail, lambda x, e: f"fallback:{x}:{e}")
        assert result == [2, "fallback:2:boom", 6]

    async def test_fallback_receives_the_original_item_even_when_not_a_dict(self):
        """The motivating case (QA review, PR #758, finding #1): an item that isn't
        a dict must still reach make_fallback intact, not raise while building the
        fallback result itself."""

        async def always_fail(x) -> dict:
            raise TypeError("not a dict")

        result = await gather_with_fallback(
            ["not-a-dict"], always_fail, lambda item, e: {"entry": item, "error": str(e)}
        )
        assert result == [{"entry": "not-a-dict", "error": "not a dict"}]
