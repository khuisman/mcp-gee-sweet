import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .atomic_write import _write_atomically

# See docs/decisions/decision-grid-data-size-cap.md,
# docs/decisions/decision-response-size-cap-generalization.md, and
# docs/decisions/decision-response-size-cap-reevaluation-519.md for the live-tested
# numbers behind this default and cap/local_path design. The default was raised from
# 40000 to 1000000 in issue #519 after live-testing found the client-connection-death
# failure mode this cap defends against no longer reproduces (for the current primary
# MCP client) even at sizes well past the old default — the cap itself stays as
# defense-in-depth for other/untested MCP clients and genuinely extreme responses.
MAX_TOOL_RESPONSE_CHARS = int(os.environ.get("MAX_TOOL_RESPONSE_CHARS", "1000000"))


def clamp_max_results(value: int, cap: int) -> int:
    """Floor a caller-supplied max_results (or similarly-named page-size param) to
    1 and ceiling it to the calling tool's own cap.

    Shared across packages (originally extracted from drive/files.py's 8
    call sites, issue #737; also used by calendar.py) since this exact clamp
    expression tends to get hand-duplicated per tool otherwise — each tool
    still picks its own cap based on its own result size/cost; this only
    centralizes the clamp expression itself, not the cap values.
    """
    return min(max(1, value), cap)


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
        raise _over_cap_error(
            f"the response is {size} characters",
            tool_name=tool_name,
            hint=hint,
            local_path_available=local_path_available,
            local_path_param=local_path_param,
        )


def enforce_response_size_floor(
    min_size: int,
    *,
    tool_name: str,
    hint: str = "",
    local_path_available: bool = True,
    local_path_param: str = "local_path",
) -> None:
    """Raise the same error as enforce_response_size_cap, before any expensive fetch,
    when a known lower bound on the response's serialized size already exceeds the cap
    (e.g. get_message's large Gmail bodies, #825)."""
    if min_size > MAX_TOOL_RESPONSE_CHARS:
        raise _over_cap_error(
            f"the response would be at least {min_size} characters",
            tool_name=tool_name,
            hint=hint,
            local_path_available=local_path_available,
            local_path_param=local_path_param,
        )


def _over_cap_error(
    size_clause: str,
    *,
    tool_name: str,
    hint: str,
    local_path_available: bool,
    local_path_param: str,
) -> ValueError:
    local_path_clause = (
        f"Pass {local_path_param} to write the result to disk instead of returning it "
        "inline (bypasses this cap), or set"
        if local_path_available
        else "set"
    )
    return ValueError(
        f"{tool_name}: {size_clause}, over the "
        f"{MAX_TOOL_RESPONSE_CHARS}-character safety cap. {hint}"
        f"{local_path_clause} MAX_TOOL_RESPONSE_CHARS if your MCP client can "
        "handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS)."
    )


async def write_capped_result_to_disk(
    result: Any, local_path: str, *, default_filename: str, manifest_extra: dict[str, Any]
) -> dict[str, Any]:
    """Write result to local_path and return a manifest dict.

    A dict or list is written as JSON. A str is written verbatim as UTF-8 with no
    newline translation, so a text export (get_doc_as_markdown, #958) lands as the
    exact text the inline response would carry, not a JSON-quoted string. The
    write goes through _write_atomically, so a failure partway leaves any previous
    file at dest intact rather than a truncated one that still reads as valid
    Markdown (PR #982 QA round 1).

    Resolves a directory path via default_filename, mirroring get_sheet_data's
    original local_path handling from issue #235. A path ending in a separator is
    a directory whether or not it exists yet: it's created rather than written as
    a file named after it (#990), the same rule as drive/transfer.py's
    _validate_local_destination. This path exists specifically to hold data too
    large for the response-size cap, so the write itself is offloaded to a worker
    thread rather than blocking the event loop for however long a large write takes.
    """
    dest = Path(local_path)
    wants_dir = local_path.endswith(("/", os.sep))
    if wants_dir or dest.is_dir():
        dest = dest / default_filename

    def _write() -> int:
        text = result if isinstance(result, str) else json.dumps(result)
        if wants_dir and dest.parent.exists() and not dest.parent.is_dir():
            raise ValueError(
                f"local_path {local_path!r} ends in a separator, so it must be a "
                f"directory, but {str(dest.parent)!r} is an existing file"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(dest, lambda fh: fh.write(text.encode("utf-8")))
        return dest.stat().st_size

    bytes_written = await asyncio.to_thread(_write)
    return {"local_path": str(dest), "bytes_written": bytes_written, **manifest_extra}
