#!/usr/bin/env python3
"""
Cancel a live write tool while its write request runs on its worker thread (#1030).

No MCP client can cancel a tool call at a chosen point, so this script runs the
checkout's own tool against the real Docs/Drive APIs inside an anyio task group
(mcp cancels a request through an anyio cancel scope). A gate on
`execute_in_thread` holds the tool's first write request (any method but GET) on
its worker thread for a few seconds before sending it, and the script cancels
the call during that hold. The thread can't be stopped, so the write still lands
after the cancellation has unwound.

Every cache invalidation is printed as `doc cache marked dirty for <id>`,
`folder cache marked dirty for <id>`, or `folder cache: every folder marked dirty`,
each followed by `(write landed: yes|no)`. The script waits for the held write
to finish before exiting, so the output shows whether the cache is invalidated
on the cancel path and again once the abandoned write lands.

Tools and the arguments each needs:
- `insert_doc_text --doc-id D`: inserts `INFLIGHT1030 ` at index 1.
- `insert_doc_table --doc-id D`: inserts a 1x1 table at index 1.
- `create_folder --folder-id F`: creates `TC-D1030 folder` in F.
- `rename_file --file-id X`: renames X to `TC-D1030 renamed`. Only the response
  names the folder, so a cancelled rename marks every folder listing dirty.
- `move_file --file-id X --folder-id F`: moves X into F.
- `sync_folder --folder-id F --local-path DIR`: an upload-direction sync of DIR.

Usage:
    uv run python scripts/qa_cancel_inflight_write.py TOOL [--doc-id D] [--file-id X] [--folder-id F] [--local-path DIR]

Uses the OAuth token from `TOKEN_PATH`, like the server under test.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from functools import partial
from unittest.mock import AsyncMock, MagicMock

import anyio
from googleapiclient.discovery import build

from mcp_gee_sweet.auth import _oauth_creds
from mcp_gee_sweet.tools import docs
from mcp_gee_sweet.tools.docs import editing, tables
from mcp_gee_sweet.tools.drive import files, transfer

_HOLD_SECONDS = 3
_LANDING_WAIT_SECONDS = 30
_TOOLS = [
    "insert_doc_text",
    "insert_doc_table",
    "create_folder",
    "rename_file",
    "move_file",
    "sync_folder",
]


def _register_tools() -> dict:
    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    docs.register(tool)
    files.register(tool)
    transfer.register(tool)
    return captured


def _method(execute_fn) -> str:
    return getattr(getattr(execute_fn, "__self__", None), "method", "")


async def main(args: argparse.Namespace) -> None:
    creds = _oauth_creds()
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    lc = ctx.request_context.lifespan_context
    lc.docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    lc.drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    lc.folder_id = None

    sent: list[bool] = []  # one entry per write whose worker thread started it
    landed: list[bool] = []  # one entry per write whose thread returned or raised
    claimed: list[bool] = []  # the first write the gate saw, which it holds
    held = threading.Event()

    def _landed_note() -> str:
        return f"(write landed: {'yes' if landed and len(landed) == len(sent) else 'no'})"

    lc.doc_cache.mark_dirty.side_effect = lambda doc_id: print(
        f"doc cache marked dirty for {doc_id} {_landed_note()}"
    )
    lc.drive_folder_cache.mark_dirty.side_effect = lambda folder_id: print(
        f"folder cache marked dirty for {folder_id} {_landed_note()}"
    )
    lc.drive_folder_cache.mark_all_dirty.side_effect = lambda: print(
        f"folder cache: every folder marked dirty {_landed_note()}"
    )
    # Reads always miss, so every read goes to the API.
    lc.drive_folder_cache.get.return_value = None
    lc.doc_cache.get.return_value = None

    def _gate(original):
        async def gated(execute_fn, service):
            if _method(execute_fn) in ("", "GET"):
                return await original(execute_fn, service)

            # Decided on the loop, so two gathered writes can't both be held.
            first = not claimed
            claimed.append(True)

            # Counted on the worker thread: `sent` once it starts, `landed` once
            # the request returns or raises. Only the first write is held.
            def run(**kwargs):
                sent.append(True)
                try:
                    if first:
                        held.set()
                        time.sleep(_HOLD_SECONDS)
                    return execute_fn(**kwargs)
                finally:
                    landed.append(True)

            return await original(run, service)

        return gated

    for module in (editing, tables, files, transfer):
        module.execute_in_thread = _gate(module.execute_in_thread)
    tools = _register_tools()

    calls = {
        "insert_doc_text": lambda: partial(
            tools["insert_doc_text"],
            doc_id=args.doc_id,
            insertions=[{"index": 1, "text": "INFLIGHT1030 "}],
        ),
        "insert_doc_table": lambda: partial(
            tools["insert_doc_table"], doc_id=args.doc_id, index=1, rows=1, columns=1
        ),
        "create_folder": lambda: partial(
            tools["create_folder"], name="TC-D1030 folder", parent_folder_id=args.folder_id
        ),
        "rename_file": lambda: partial(
            tools["rename_file"], file_id=args.file_id, new_name="TC-D1030 renamed"
        ),
        "move_file": lambda: partial(
            tools["move_file"], file_id=args.file_id, destination_folder_id=args.folder_id
        ),
        "sync_folder": lambda: partial(
            tools["sync_folder"],
            folder_id=args.folder_id,
            local_path=args.local_path,
            direction="upload",
        ),
    }
    call = partial(calls[args.tool](), ctx=ctx)

    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        await anyio.to_thread.run_sync(held.wait, 60)
        tg.cancel_scope.cancel()
    print(f"cancelled {args.tool} while its write was in flight; the tool returned nothing")

    # The abandoned write's thread keeps running; wait for it, then give its
    # loop callback a moment to run.
    with anyio.move_on_after(_LANDING_WAIT_SECONDS):
        while len(landed) < len(sent):
            await anyio.sleep(0.1)
    await anyio.sleep(0.5)
    print(f"writes sent: {len(sent)}; landed: {len(landed)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tool", choices=_TOOLS)
    parser.add_argument("--doc-id")
    parser.add_argument("--file-id")
    parser.add_argument("--folder-id")
    parser.add_argument("--local-path")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    anyio.run(main, parser.parse_args())
