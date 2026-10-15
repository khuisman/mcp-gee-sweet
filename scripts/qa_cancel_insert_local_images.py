#!/usr/bin/env python3
"""
Cancel a live image-embedding doc edit mid-flight (TC-DOC203 #883, TC-DOC222 #909).

No MCP client can cancel a tool call at a chosen point, so this script runs the
checkout's own `insert_local_images` (default) or `write_doc_content`
(`--tool write_doc_content`, which goes through `_apply_doc_content`) against the
real Docs/Drive APIs inside an anyio task group (mcp cancels a request through an
anyio cancel scope) and cancels it at one of these points:

- `share`      — while the image's anyone:reader permission is being granted,
  inside the upload gather.
- `share-fail` — the same, but the share then fails instead of being granted,
  leaving a created-but-unshared upload (#649) and nothing to embed.
- `edit`       — just before the doc's `batchUpdate` is sent.
- `inflight`   — while the `batchUpdate` is running on its worker thread. The
  thread can't be stopped, so the edit may still land after the cancel.
- `revoke`     — while the post-edit revoke of the temporary share is running.

A gate on `execute_in_thread` (in `images` and `content`) holds the matching
request for a few seconds so the cancel lands there deterministically, then lets
it through (`share-fail` raises instead; `inflight` sends it at once and cancels
while it runs). The tool's own WARNING log (the only record a cancelled call
leaves) is printed to stderr.

Every doc-cache invalidation is printed as `doc cache marked dirty for <id>
(edit landed: yes|no)`, and the script waits for an in-flight edit to finish
before exiting, so the `inflight` point shows whether the doc is marked dirty
again once the abandoned edit lands (#907). A `batchUpdate` sent counts as
landed once its worker thread returns or raises; one the cancel
stopped before it was sent isn't counted.

With `--tool write_doc_content`, MARKER is ignored and the doc's content is
replaced with `Before`, the image, `After`. Use an empty doc, so there's no
clear `batchUpdate` (and no backup copy) ahead of the content one.

Usage:
    uv run python scripts/qa_cancel_insert_local_images.py DOC_ID FOLDER_ID PNG_PATH MARKER POINT [--keep-shared] [--tool write_doc_content]

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
from mcp_gee_sweet.tools.docs import content, images

_HOLD_SECONDS = 3
_LANDING_WAIT_SECONDS = 15
_POINTS = ["share", "share-fail", "edit", "inflight", "revoke"]
_TOOLS = ["insert_local_images", "write_doc_content"]


def _register_tools() -> dict:
    captured = {}

    def tool(annotations=None):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    docs.register(tool)
    return captured


def _request(execute_fn) -> tuple[str, str]:
    request = getattr(execute_fn, "__self__", None)
    return getattr(request, "uri", ""), getattr(request, "method", "")


def _matches(execute_fn, point: str) -> bool:
    uri, method = _request(execute_fn)
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

    sent: list[bool] = []  # one entry per batchUpdate whose worker thread started it
    landed: list[bool] = []  # one entry per batchUpdate whose thread returned or raised

    def _mark_dirty(doc_id: str) -> None:
        print(
            f"doc cache marked dirty for {doc_id} "
            f"(edit landed: {'yes' if len(landed) == len(sent) and landed else 'no'})"
        )

    lc.doc_cache.mark_dirty.side_effect = _mark_dirty

    reached = anyio.Event()

    def _gate(original):
        async def gated(execute_fn, service):
            run = execute_fn
            if ":batchUpdate" in _request(execute_fn)[0]:
                # Counted on the worker thread: `sent` once the request actually
                # starts (a request the gate held and the cancel stopped never
                # does), `landed` once it returns or raises.
                def run(**kwargs):
                    sent.append(True)
                    try:
                        return execute_fn(**kwargs)
                    finally:
                        landed.append(True)

            if reached.is_set() or not _matches(execute_fn, args.point):
                return await original(run, service)
            reached.set()
            if args.point == "inflight":
                # original() hands the request to a worker thread before its first
                # suspension, so the cancel lands while the batchUpdate is running.
                return await original(run, service)
            await anyio.sleep(_HOLD_SECONDS)
            if args.point == "share-fail":
                raise RuntimeError("share-fail: simulated permission failure")
            return await original(run, service)

        return gated

    images.execute_in_thread = _gate(images.execute_in_thread)
    content.execute_in_thread = _gate(content.execute_in_thread)
    tools = _register_tools()
    if args.tool == "write_doc_content":
        call = partial(
            tools["write_doc_content"],
            doc_id=args.doc_id,
            content=f"Before\n\n![Pixel]({args.png_path})\n\nAfter",
            content_format="markdown",
            revoke_sharing=not args.keep_shared,
            ctx=ctx,
        )
    else:
        call = partial(
            tools["insert_local_images"],
            doc_id=args.doc_id,
            images=[{"marker": args.marker, "local_path": args.png_path}],
            revoke_sharing=not args.keep_shared,
            ctx=ctx,
        )
    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        with anyio.fail_after(60):
            await reached.wait()
        tg.cancel_scope.cancel()
    print(f"cancelled at {args.point!r}; the tool returned nothing")

    # An abandoned edit's thread keeps running; wait for it, then give its
    # loop callback a moment to run.
    with anyio.move_on_after(_LANDING_WAIT_SECONDS):
        while len(landed) < len(sent):
            await anyio.sleep(0.1)
    await anyio.sleep(0.5)
    print(f"batchUpdates sent: {len(sent)}; landed: {len(landed)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("doc_id")
    parser.add_argument("folder_id")
    parser.add_argument("png_path")
    parser.add_argument("marker")
    parser.add_argument("point", choices=_POINTS)
    parser.add_argument("--keep-shared", action="store_true")
    parser.add_argument("--tool", choices=_TOOLS, default="insert_local_images")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    anyio.run(main, parser.parse_args())
