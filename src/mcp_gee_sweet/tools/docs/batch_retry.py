"""Send a Docs batchUpdate, dropping each inline image Google can't fetch.

One unfetchable insertInlineImage makes the Docs API reject a whole batchUpdate, and a
rejected batch applies nothing, so the image can be dropped and the rest resent (#333).
Google's error names only the first failing image, in request order, so K bad images
take K retries. Resending everything each time is K+1 full-size calls (#510), so once a
second image fails the batch splits: the requests ahead of the split are sent once, and
only the rest is retried. Where it's safe to split depends on how the batch was built,
so the caller says. The body of a doc and its table cells share this loop (#1073).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


async def send_dropping_failed_images(
    requests: list[dict],
    run_batch: Callable[[list[dict]], Awaitable[None]],
    drop: Callable[[list[dict], Exception], int | None],
    split_point: Callable[[list[dict], int], int],
    on_applied: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    """Send `requests`, dropping each image Google can't fetch, and return what was applied.

    drop(remaining, error) pops the image request `error` names (and anything that goes
    with it, such as its link request) from `remaining` and returns the index it was at,
    or returns None for any other error, which is then raised. From the second dropped
    image on, split_point(remaining, index) gives where to split the batch, with 0 for
    no split: remaining[:cut] is sent on its own and only remaining[cut:] is retried.
    on_applied is called with every batch that succeeds, including a split-off head, so
    a caller can tell what landed even when a later batch raises.

    The head of a split goes out once, unretried. Google names the first failing image
    in request order, so no image ahead of the one just dropped is known to fail; if one
    does anyway, its error is raised, with the head's earlier part not yet applied.
    """
    committed: list[dict] = []
    remaining = list(requests)
    failures = 0
    while remaining:
        try:
            await run_batch(remaining)
        except Exception as e:
            index = drop(remaining, e)
            if index is None:
                raise
            failures += 1
            cut = split_point(remaining, index) if failures >= 2 else 0
            if cut:
                head = remaining[:cut]
                await run_batch(head)
                if on_applied is not None:
                    on_applied(head)
                committed.extend(head)
                remaining = remaining[cut:]
            continue
        if on_applied is not None:
            on_applied(remaining)
        return committed + remaining
    return committed
