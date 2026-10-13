#!/usr/bin/env python3
"""
Where does export_revision put its temporary Doc? (TC-D289, issue #989)

The temporary Doc is removed before export_revision returns, so no tool call
can see its parent folder afterward. This script runs the real export_revision
code from this checkout against a scratch Doc and reads the temporary Doc's
parents just before its removal.

It uses this checkout's OAuth token and DRIVE_FOLDER_ID (from
src/mcp_gee_sweet/.env), and sets the connection's identity flag by --identity:
`user` takes the OAuth branch, `service-account` the service-account branch
(same OAuth credentials, so only the folder choice differs). DRIVE_FOLDER_ID
must point at a Shared Drive folder for the service-account branch to mean
anything. Only booleans are printed, never IDs.

Usage:
    uv run python scripts/qa_revision_temp_doc_parent.py --identity user
    uv run python scripts/qa_revision_temp_doc_parent.py --identity service-account
"""

import argparse
import asyncio
import os
from unittest.mock import MagicMock

from googleapiclient.discovery import build

import mcp_gee_sweet  # noqa: F401  (loads src/mcp_gee_sweet/.env)
from mcp_gee_sweet import auth
from mcp_gee_sweet.http_transport import execute_in_thread
from mcp_gee_sweet.tools.docs import markdown_export
from mcp_gee_sweet.tools.drive import transfer

_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


def _register_tools() -> dict:
    tools: dict = {}

    def tool(annotations=None):
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    transfer.register(tool)
    return tools


async def main(identity: str) -> None:
    seen: dict = {}
    original_discard = markdown_export._discard_temp_doc

    async def spy_discard(drive_service, file_id, can_delete):
        seen.update(
            await execute_in_thread(
                drive_service.files()
                .get(fileId=file_id, fields="parents,driveId", supportsAllDrives=True)
                .execute,
                drive_service,
            )
        )
        return await original_discard(drive_service, file_id, can_delete)

    markdown_export._discard_temp_doc = spy_discard

    creds = auth._oauth_creds()
    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)
    folder_id = os.environ.get("DRIVE_FOLDER_ID")
    root_id = drive.files().get(fileId="root", fields="id").execute()["id"]

    doc_id = (
        drive.files()
        .create(body={"name": "qa-989-probe", "mimeType": _GOOGLE_DOC_MIME}, fields="id")
        .execute()["id"]
    )
    try:
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": "probe 989"}}]},
        ).execute()
        revisions = (
            drive.revisions().list(fileId=doc_id, fields="revisions(id)").execute()["revisions"]
        )

        ctx = MagicMock()
        lc = ctx.request_context.lifespan_context
        lc.drive_service, lc.docs_service, lc.folder_id = drive, docs, folder_id
        lc.is_service_account_identity = identity == "service-account"

        result = await _register_tools()["export_revision"](
            file_id=doc_id, revision_id=revisions[-1]["id"], ctx=ctx
        )
        parents = seen.get("parents", [])
        print(f"identity: {identity}")
        print(f"DRIVE_FOLDER_ID set: {bool(folder_id)}")
        print(f"markdown: {result.get('markdown')!r}")
        print(f"warning: {result.get('warning')}")
        print(f"temp Doc in My Drive root: {parents == [root_id]}")
        print(f"temp Doc in DRIVE_FOLDER_ID: {bool(folder_id) and parents == [folder_id]}")
        print(f"temp Doc in a Shared Drive: {bool(seen.get('driveId'))}")
    finally:
        drive.files().delete(fileId=doc_id).execute()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--identity", choices=["user", "service-account"], required=True)
    asyncio.run(main(parser.parse_args().identity))
