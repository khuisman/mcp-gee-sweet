"""Atomic local-file writes, shared by every Drive download (drive/transfer.py)
and the response-cap local_path dump (response_limits.py). Lives at the tools/
level so both can import it: transfer.py already imports response_limits."""

import contextlib
import errno
import os
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

# Every download, and every response-cap local_path write (#958), writes to a
# sibling temp file with this name and renames it onto the destination only once
# complete (_write_atomically, #844). A temp file only outlives its write when
# the process is killed mid-write; sync_folder and upload_local_folder skip one
# so a leftover partial is never uploaded. No part of the destination's name is embedded, so the temp name
# can't exceed the filesystem's name-length limit.
_PARTIAL_DOWNLOAD_PREFIX = ".gee-sweet-partial-"
_PARTIAL_DOWNLOAD_RE = re.compile(r"\.gee-sweet-partial-[0-9a-f]{16}")


def _is_partial_download(name: str) -> bool:
    """Whether `name` is a temp file _write_atomically left behind."""
    return _PARTIAL_DOWNLOAD_RE.fullmatch(name) is not None


def _write_atomically(
    dest: Path, write: Callable[[BinaryIO], object], mtime: float | None = None
) -> None:
    """Run `write` against a sibling temp file, then rename it onto `dest`.

    `dest` only ever holds its previous content or the complete new content.
    Writing straight into `dest` left a truncated file behind when a download
    failed partway, with a current mtime that made sync_folder treat it as the
    newer copy and upload it over the intact Drive file (#844). `mtime`, when
    given, is stamped on the temp file before the rename, so a failed restamp
    also leaves `dest` untouched. The temp file is removed on any failure.

    A symlink at `dest` is written through, as the old `open("wb")` did: the
    temp file goes next to the link's target and replaces the target. The new
    file gets the mode a fresh `open("wb")` would (0o666 less the umask), or the
    replaced file's permission bits when there was one (never its
    setuid/setgid/sticky bits, which an in-place write would have cleared). A
    hard link to the old file keeps the old content, since the rename swaps in
    a new inode.

    A rename needs write permission on the directory, not the file, so an
    existing file this process couldn't open for writing is refused up front
    with the same PermissionError `open("wb")` raised; otherwise a file the
    user made read-only would be silently replaced (PR #884 QA round 1).
    """
    target = Path(os.path.realpath(dest)) if dest.is_symlink() else dest
    if target.exists() and not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(target))
    tmp = target.with_name(_PARTIAL_DOWNLOAD_PREFIX + secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as fh:
            write(fh)
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp, target.stat().st_mode & 0o777)
        if mtime is not None:
            os.utime(tmp, (mtime, mtime))
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
