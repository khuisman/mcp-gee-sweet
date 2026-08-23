"""
Shared helpers for the live-filesystem integration harness (issue #50).

These tests spawn the real `mcp-gee-sweet` server as a subprocess and drive it
over stdio with the `mcp` SDK's own client, hitting real Google APIs. They are
opt-in only — see docs/qa/README.md's "⚠️ local-filesystem" note for why, and
how to run them.

`live_session`/`live_session_with_scratch_folder` are plain async context
managers, not pytest fixtures, deliberately: the MCP SDK's stdio_client and
ClientSession both wrap an anyio task group, and anyio cancel scopes must
exit in the same asyncio Task they were entered in. pytest-asyncio's
async-generator-fixture teardown always runs setup and teardown as two
separate top-level Tasks (confirmed live, both function- and session-scoped —
"Attempted to exit cancel scope in a different task than it was entered in"),
so a fixture can never satisfy that invariant no matter how it's scoped.
Keeping connect-and-disconnect inside one `async with` in the test body's own
Task sidesteps the incompatibility entirely.
"""

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]

# Same waterfall order server.py's own auth.py documents: OAuth first (personal
# Drive access), service account as fallback.
_OAUTH_CREDS = REPO_ROOT / "credentials.json"
_OAUTH_TOKEN = REPO_ROOT / "token.json"
_SERVICE_ACCOUNT = REPO_ROOT / "service_account.json"


def _discover_auth_env() -> dict[str, str] | None:
    """Build the subprocess env vars needed to authenticate, or None if nothing usable is found.

    Honors AUTH_METHOD if the caller already exported it (so a developer's own
    setup isn't second-guessed); otherwise auto-discovers the same repo-root
    credential files `.mcp.json` already points every team-role server at.
    """
    if os.environ.get("AUTH_METHOD"):
        return {}  # nothing extra to add — inherit as-is via get_default_environment()

    if _OAUTH_CREDS.exists() and _OAUTH_TOKEN.exists():
        return {
            "AUTH_METHOD": "oauth",
            "CREDENTIALS_PATH": str(_OAUTH_CREDS),
            "TOKEN_PATH": str(_OAUTH_TOKEN),
        }
    if _SERVICE_ACCOUNT.exists():
        return {"AUTH_METHOD": "service_account", "SERVICE_ACCOUNT_PATH": str(_SERVICE_ACCOUNT)}
    return None


def _live_test_folder_id() -> str | None:
    root_env = dotenv_values(REPO_ROOT / ".env")
    return os.environ.get("TEST_FOLDER_ID") or root_env.get("TEST_FOLDER_ID")


def _live_tests_enabled() -> tuple[bool, str]:
    if not os.environ.get("MCP_GEE_SWEET_LIVE_TESTS"):
        return False, "MCP_GEE_SWEET_LIVE_TESTS is not set — opt in to run this harness"
    if _discover_auth_env() is None:
        return False, (
            "no usable Google credentials found (checked AUTH_METHOD env var and "
            f"{_OAUTH_CREDS.name}/{_OAUTH_TOKEN.name}/{_SERVICE_ACCOUNT.name} at repo root)"
        )
    if not _live_test_folder_id():
        return False, "TEST_FOLDER_ID not set (env var or repo-root .env) — see docs/qa/setup.md"
    return True, ""


@asynccontextmanager
async def live_session() -> AsyncIterator[ClientSession]:
    """A live ClientSession talking to a real `mcp-gee-sweet` subprocess over stdio.

    Skips the calling test (via pytest.skip) when the opt-in env var or
    credentials aren't present, rather than raising — see module docstring for
    why this is a plain async context manager, not a pytest fixture.
    """
    enabled, reason = _live_tests_enabled()
    if not enabled:
        pytest.skip(reason)

    env = {**(_discover_auth_env() or {})}
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(REPO_ROOT), "mcp-gee-sweet"],
        env=env,
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


@asynccontextmanager
async def live_session_with_scratch_folder() -> AsyncIterator[tuple[ClientSession, str]]:
    """A live session plus a throwaway Drive folder under TEST_FOLDER_ID, deleted on exit.

    Keeps this harness's artifacts out of TEST_FOLDER_ID's own top level per
    docs/qa/run.md's fixture-pollution guidance.
    """
    async with live_session() as session:
        result = await session.call_tool(
            "create_folder",
            {
                "name": f"mcp-gee-sweet-live-fs-{int(time.time())}",
                "parent_folder_id": _live_test_folder_id(),
            },
        )
        folder_id = result.structured_content["folderId"]
        try:
            yield session, folder_id
        finally:
            # Best-effort: observed live (2026-08-22) that Drive's cascade delete on a
            # permanently-deleted folder can miss a child created moments earlier in the
            # same run, leaving it parentless in My Drive root rather than gone — an
            # eventual-consistency quirk on Drive's side, not something worth a
            # list-children-and-delete-each-first workaround for a scratch dev fixture.
            await session.call_tool("delete_file", {"file_id": folder_id, "permanent": True})
