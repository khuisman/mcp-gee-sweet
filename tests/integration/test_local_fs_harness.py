"""
Live-filesystem integration harness (issue #50).

Proves a pytest-driven subprocess can cover the `⚠️ local-filesystem` QA test
cases (docs/qa/tests/drive_transfer.md) without a human or an AI chat session
in the loop: it starts the real `mcp-gee-sweet` server, drives it over stdio
with real local files, and asserts against real Google Drive responses.

Opt-in only — see conftest.py's `_live_tests_enabled` and docs/qa/README.md's
"⚠️ local-filesystem" note. Skips cleanly (not a failure) whenever
MCP_GEE_SWEET_LIVE_TESTS or credentials aren't present, so this module is
always safe to include in the default `testpaths`.

This covers upload_local_file, download_file, and sync_folder(direction=
'upload') as a representative slice of the ~27 skipped QA cases — proving the
mechanism, not replacing the full QA suite. See the decision doc for why the
remaining cases (upload_local_folder, download_folder, bidirectional/
recursive/convert/checksum sync variants) are follow-up rather than in scope
here: docs/decisions/decision-local-fs-test-harness.md.
"""

import pytest

from .conftest import live_session_with_scratch_folder

pytestmark = pytest.mark.live_fs


async def test_upload_local_file_round_trip(tmp_path):
    async with live_session_with_scratch_folder() as (session, scratch_drive_folder):
        local_file = tmp_path / "mcp-gee-sweet-live-fs-upload.txt"
        local_file.write_text("hello from the live-filesystem harness\n")

        result = await session.call_tool(
            "upload_local_file",
            {"local_path": str(local_file), "parent_folder_id": scratch_drive_folder},
        )
        uploaded = result.structured_content
        assert not result.is_error, uploaded
        assert uploaded["name"] == local_file.name
        assert uploaded.get("skipped") is not True

        metadata = await session.call_tool("get_file_metadata", {"file_id": uploaded["fileId"]})
        assert metadata.structured_content["name"] == local_file.name


async def test_download_file_round_trip(tmp_path):
    async with live_session_with_scratch_folder() as (session, scratch_drive_folder):
        content = "round trip via download_file\n"
        local_source = tmp_path / "mcp-gee-sweet-live-fs-download-src.txt"
        local_source.write_text(content)

        uploaded = (
            await session.call_tool(
                "upload_local_file",
                {"local_path": str(local_source), "parent_folder_id": scratch_drive_folder},
            )
        ).structured_content

        download_dest = tmp_path / "downloaded.txt"
        result = await session.call_tool(
            "download_file",
            {"file_id": uploaded["fileId"], "local_path": str(download_dest)},
        )
        assert not result.is_error, result.structured_content
        assert download_dest.read_text() == content


async def test_sync_folder_upload(tmp_path):
    async with live_session_with_scratch_folder() as (session, scratch_drive_folder):
        local_dir = tmp_path / "sync-src"
        local_dir.mkdir()
        (local_dir / "mcp-gee-sweet-live-fs-sync.txt").write_text("synced via sync_folder\n")

        result = await session.call_tool(
            "sync_folder",
            {
                "folder_id": scratch_drive_folder,
                "local_path": str(local_dir),
                "direction": "upload",
            },
        )
        summary = result.structured_content
        assert not result.is_error, summary
        assert "mcp-gee-sweet-live-fs-sync.txt" in summary["uploaded"]

        listing = await session.call_tool("list_files", {"folder_id": scratch_drive_folder})
        names = {f["name"] for f in listing.structured_content["result"]}
        assert "mcp-gee-sweet-live-fs-sync.txt" in names
