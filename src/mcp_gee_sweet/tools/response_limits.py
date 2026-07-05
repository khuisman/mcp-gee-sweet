import json
import os
from pathlib import Path
from typing import Any

# See docs/decisions/decision-grid-data-size-cap.md and
# docs/decisions/decision-response-size-cap-generalization.md for the live-tested
# numbers behind this default and cap/local_path design.
MAX_TOOL_RESPONSE_CHARS = int(os.environ.get("MAX_TOOL_RESPONSE_CHARS", "40000"))


def enforce_response_size_cap(
    result: Any, *, tool_name: str, hint: str = "", local_path_available: bool = True
) -> None:
    """Raise ValueError if the serialized result exceeds the configured cap."""
    size = len(json.dumps(result))
    if size > MAX_TOOL_RESPONSE_CHARS:
        local_path_clause = (
            "Pass local_path to write the result to disk instead of returning it inline "
            "(bypasses this cap), or set"
            if local_path_available
            else "set"
        )
        raise ValueError(
            f"{tool_name}: the response is {size} characters, over the "
            f"{MAX_TOOL_RESPONSE_CHARS}-character safety cap. {hint}"
            f"{local_path_clause} MAX_TOOL_RESPONSE_CHARS if your MCP client can "
            "handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS)."
        )


def write_capped_result_to_disk(
    result: Any, local_path: str, *, default_filename: str, manifest_extra: dict[str, Any]
) -> dict[str, Any]:
    """Write result (dict or list) to local_path and return a manifest dict.

    Resolves a directory path via default_filename, mirroring get_sheet_data's
    original local_path handling from issue #235.
    """
    dest = Path(local_path)
    if dest.is_dir():
        dest = dest / default_filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result))
    return {"local_path": str(dest), "bytes_written": dest.stat().st_size, **manifest_extra}
