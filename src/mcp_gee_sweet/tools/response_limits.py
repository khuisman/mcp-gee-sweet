import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .atomic_write import _check_destination, _is_partial_download, _write_atomically

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


def _local_dir_blocker(path: Path) -> Path | None:
    """The nearest existing component of `path` (itself, then its parents), if
    it isn't a directory; None when `path` can be created with mkdir -p.

    A dangling symlink counts as existing: mkdir can't create a directory over it.
    """
    for p in (path, *path.parents):
        if p.exists() or p.is_symlink():
            return None if p.is_dir() else p
    return None


def _is_dangling_symlink(path: Path) -> bool:
    return path.is_symlink() and not path.exists()


def _blocked_destination_error(
    local_path: str,
    blocker: Path,
    ending_made_dir: bool = False,
    *,
    local_path_param: str = "local_path",
) -> ValueError:
    """The ValueError for a local_path that `blocker` stops from being written.

    `ending_made_dir`: `blocker` is the destination itself, and only local_path's
    ending (a trailing separator, '.' or '..') made it a directory target. The
    message then says so, since dropping that ending writes a file there instead.
    `local_path_param` names the caller's parameter (e.g. sync_folder's
    result_local_path).
    """
    if _is_dangling_symlink(blocker):
        return ValueError(
            f"{local_path_param} {local_path!r} has a symlink to a missing target "
            f"at {str(blocker)!r}"
        )
    message = (
        f"{local_path_param} {local_path!r} has a non-directory path component at {str(blocker)!r}"
    )
    if ending_made_dir:
        message += (
            f"; {local_path_param} ends in a path separator or '.', which makes it a "
            "directory target. Remove that ending to write a file at that path instead"
        )
    return ValueError(message)


def validate_local_destination(
    local_path: str, *, is_dir: bool = False, local_path_param: str = "local_path"
) -> tuple[Path, bool]:
    """Reject a blocked local destination before anything is fetched or written.

    The destination must be a directory when `is_dir` is set or local_path ends
    in a separator, '.' or '..' (Path() drops a trailing '/.', so a check on the
    Path alone would read 'dir/.' as a file named 'dir'). Otherwise it's a file
    and only its parents must be directories: an existing regular file there may
    still be replaced, but a dangling symlink is refused, the same as a dangling
    symlink at a directory target (#874). Returns (Path(local_path), wants_dir).

    Shared by write_capped_result_to_disk (#990) and drive/transfer.py's download
    and sync tools, which call it before their Drive requests.
    """
    dest = Path(local_path)
    ending_made_dir = os.path.basename(local_path) in ("", ".", "..")
    wants_dir = is_dir or ending_made_dir
    if wants_dir:
        blocker = _local_dir_blocker(dest)
    elif _is_dangling_symlink(dest):
        blocker = dest
    else:
        blocker = _local_dir_blocker(dest.parent)
    if blocker is not None:
        raise _blocked_destination_error(
            local_path,
            blocker,
            ending_made_dir and not is_dir and blocker == dest,
            local_path_param=local_path_param,
        )
    if not wants_dir and not dest.is_dir():
        # A FIFO, socket, or unwritable file at a file destination fails here,
        # not after a Workspace export's round trip (PR #1001 QA round 1). An
        # existing directory without a trailing separator is a directory target.
        _check_destination(dest)
    return dest, wants_dir


def _safe_filename(name: str) -> str:
    """`name` as a single ordinary path component, for joining onto a directory.

    Separators ('/' and '\\', on every platform) and NUL become '_', and so does
    the ':' of a Windows drive-qualified name like 'C:x'. '.', '..', and the
    temp-file prefix _write_atomically reserves get a leading '_'. A sheet named
    '../x' therefore writes '.._x_data.json' inside the chosen directory, not
    'x_data.json' beside it (PR #1000 QA round 2).
    """
    for ch in ("/", "\\", "\x00"):
        name = name.replace(ch, "_")
    if Path(name).anchor:
        name = name.replace(":", "_")
    if name in ("", ".", "..") or _is_partial_download(name):
        name = "_" + name
    return name


async def write_capped_result_to_disk(
    result: Any,
    local_path: str,
    *,
    default_filename: str,
    manifest_extra: dict[str, Any],
    local_path_param: str = "local_path",
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
    a file named after it (#990). A non-directory parent component (an existing file
    or a dangling symlink) raises ValueError via validate_local_destination instead
    of an OSError from mkdir, and an existing file is never overwritten for a
    trailing-separator path. An existing file at a plain file path is replaced.

    default_filename can carry caller text (get_sheet_data's sheet name), so it's
    reduced to one ordinary path component (_safe_filename) before the join, and the
    joined file gets the same checks as a file local_path: a dangling symlink there
    is refused rather than written through (PR #1000 QA round 2).

    This path exists specifically to hold data too large for the response-size cap,
    so the write itself is offloaded to a worker thread rather than blocking the
    event loop for however long a large write takes.
    """

    def _write() -> tuple[Path, int]:
        dest, wants_dir = validate_local_destination(local_path, local_path_param=local_path_param)
        if wants_dir or dest.is_dir():
            dest = dest / _safe_filename(default_filename)
            if _is_dangling_symlink(dest):
                raise _blocked_destination_error(
                    local_path, dest, local_path_param=local_path_param
                )
            _check_destination(dest)
        text = result if isinstance(result, str) else json.dumps(result)
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(dest, lambda fh: fh.write(text.encode("utf-8")))
        return dest, dest.stat().st_size

    dest, bytes_written = await asyncio.to_thread(_write)
    return {"local_path": str(dest), "bytes_written": bytes_written, **manifest_extra}
