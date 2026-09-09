import asyncio
import json
import os
from pathlib import Path
from typing import Any

# See docs/decisions/decision-grid-data-size-cap.md,
# docs/decisions/decision-response-size-cap-generalization.md, and
# docs/decisions/decision-response-size-cap-reevaluation-519.md for the live-tested
# numbers behind this default and cap/local_path design. The default was raised from
# 40000 to 1000000 in issue #519 after live-testing found the client-connection-death
# failure mode this cap defends against no longer reproduces (for the current primary
# MCP client) even at sizes well past the old default — the cap itself stays as
# defense-in-depth for other/untested MCP clients and genuinely extreme responses.
MAX_TOOL_RESPONSE_CHARS = int(os.environ.get("MAX_TOOL_RESPONSE_CHARS", "1000000"))


def enforce_response_size_cap(
    result: Any,
    *,
    tool_name: str,
    hint: str = "",
    local_path_available: bool = True,
    local_path_param: str = "local_path",
) -> None:
    """Raise ValueError if the serialized result exceeds the configured cap."""
    size = len(json.dumps(result))
    if size > MAX_TOOL_RESPONSE_CHARS:
        local_path_clause = (
            f"Pass {local_path_param} to write the result to disk instead of returning it "
            "inline (bypasses this cap), or set"
            if local_path_available
            else "set"
        )
        raise ValueError(
            f"{tool_name}: the response is {size} characters, over the "
            f"{MAX_TOOL_RESPONSE_CHARS}-character safety cap. {hint}"
            f"{local_path_clause} MAX_TOOL_RESPONSE_CHARS if your MCP client can "
            "handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS)."
        )


async def write_capped_result_to_disk(
    result: Any, local_path: str, *, default_filename: str, manifest_extra: dict[str, Any]
) -> dict[str, Any]:
    """Write result (dict or list) to local_path and return a manifest dict.

    Resolves a directory path via default_filename, mirroring get_sheet_data's
    original local_path handling from issue #235. This path exists specifically to
    hold data too large for the response-size cap, so the write itself is offloaded
    to a worker thread rather than blocking the event loop for however long a large
    write takes.
    """
    dest = Path(local_path)
    if dest.is_dir():
        dest = dest / default_filename

    def _write() -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(result))
        return dest.stat().st_size

    bytes_written = await asyncio.to_thread(_write)
    return {"local_path": str(dest), "bytes_written": bytes_written, **manifest_extra}
