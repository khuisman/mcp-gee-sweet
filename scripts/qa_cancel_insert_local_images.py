#!/usr/bin/env python3
"""
Cancel a live `insert_local_images` call mid-flight (TC-DOC203, issue #883).

No MCP client can cancel a tool call at a chosen point, so this script runs the
checkout's own `insert_local_images` against the real Docs/Drive APIs inside an
anyio task group (mcp cancels a request through an anyio cancel scope) and
cancels it at one of these points:

- `share`      — while the image's anyone:reader permission is being granted,
  inside the upload gather.
- `share-fail` — the same, but the share then fails instead of being granted,
  leaving a created-but-unshared upload (#649) and nothing to embed.
- `edit`       — just before the doc's `batchUpdate` is sent.
- `inflight`   — while the `batchUpdate` is running on its worker thread. The
  thread can't be stopped, so the edit may still land after the cancel.
- `revoke`     — while the post-edit revoke of the temporary share is running.

A gate on `images.execute_in_thread` holds the matching request for a few
seconds so the cancel lands there deterministically, then lets it through
(`share-fail` raises instead; `inflight` sends it at once and cancels while it
runs). The tool's own WARNING log (the only record a cancelled call leaves) is
printed to stderr.

Usage:
    uv run python scripts/qa_cancel_insert_local_images.py DOC_ID FOLDER_ID PNG_PATH MARKER POINT [--keep-shared]

`--keep-shared` passes `revoke_sharing=False`. Uses the OAuth token from
`TOKEN_PATH`, like the server under test.
"""

from __future__ import annotations

import argparse
import logging
from functools import partial
from unittest.mock import MagicMock

import anyio
from googleapiclient.discovery import build

from mcp_gee_sweet.auth import _oauth_creds
from mcp_gee_sweet.tools import docs
from mcp_gee_sweet.tools.docs import images

_HOLD_SECONDS = 3
_POINTS = ["share", "share-fail", "edit", "inflight", "revoke"]


def _register_tools() -> dict:
    captured = {}

    def tool(annotations=None):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    docs.register(tool)
    return captured


def _matches(execute_fn, point: str) -> bool:
    request = getattr(execute_fn, "__self__", None)
    uri = getattr(request, "uri", "")
    method = getattr(request, "method", "")
    if point in ("share", "share-fail"):
        return "/permissions" in uri and method == "POST"
    if point == "revoke":
        return "/permissions" in uri and method == "DELETE"
    return ":batchUpdate" in uri


async def main(args: argparse.Namespace) -> None:
    creds = _oauth_creds()
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    lc.drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    lc.folder_id = args.folder_id

    reached = anyio.Event()
    original = images.execute_in_thread

    async def gated(execute_fn, service):
        if reached.is_set() or not _matches(execute_fn, args.point):
            return await original(execute_fn, service)
        reached.set()
        if args.point == "inflight":
            # original() hands the request to a worker thread before its first
            # suspension, so the cancel lands while the batchUpdate is running.
            return await original(execute_fn, service)
        await anyio.sleep(_HOLD_SECONDS)
        if args.point == "share-fail":
            raise RuntimeError("share-fail: simulated permission failure")
        return await original(execute_fn, service)

    images.execute_in_thread = gated
    tool = _register_tools()["insert_local_images"]
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            partial(
                tool,
                doc_id=args.doc_id,
                images=[{"marker": args.marker, "local_path": args.png_path}],
                revoke_sharing=not args.keep_shared,
                ctx=ctx,
            )
        )
        with anyio.fail_after(60):
            await reached.wait()
        tg.cancel_scope.cancel()
    print(f"cancelled at {args.point!r}; the tool returned nothing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("doc_id")
    parser.add_argument("folder_id")
    parser.add_argument("png_path")
    parser.add_argument("marker")
    parser.add_argument("point", choices=_POINTS)
    parser.add_argument("--keep-shared", action="store_true")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    anyio.run(main, parser.parse_args())
