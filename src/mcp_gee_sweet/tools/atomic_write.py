"""Atomic local-file writes, shared by every Drive download (drive/transfer.py)
and the response-cap local_path dump (response_limits.py). Lives at the tools/
level so both can import it: transfer.py already imports response_limits."""

import contextlib
import errno
import os
import re
import secrets
import stat
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

# Every download, and every response-cap local_path write (#958), writes to a
# sibling temp file with this name and renames it onto the destination only once
# complete (_write_atomically, #844). A temp file only outlives its write when
# the process is killed mid-write; sync_folder and upload_local_folder never
# upload one and list it under 'skipped', and a Drive file with such a name is
# refused as a local filename (#887). No part of the destination's name is embedded, so the temp name
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
    also leaves `dest` untouched. The temp file is removed on any failure. It's
    fsynced before the rename and the directory after it, so a power loss can't
    leave `dest` empty or truncated either (#887).

    A symlink at `dest` is written through, as the old `open("wb")` did: the
    temp file goes next to the link's target and replaces the target. The new
    file gets the mode a fresh `open("wb")` would (0o666 less the umask), or the
    replaced file's permission bits when there was one (never its
    setuid/setgid/sticky bits, which an in-place write would have cleared), and
    the replaced file's owner and group when this process may set them (root,
    e.g. the Docker image writing into a bind mount). Nothing else on the old
    inode carries over (ACLs, xattrs, creation time), and a hard link to it
    keeps the old content; see docs/known-limitations.md.

    A rename needs write permission on the directory, not the file, so an
    existing file this process couldn't open for writing is refused up front
    with the same PermissionError `open("wb")` raised; otherwise a file the
    user made read-only would be silently replaced (PR #884 QA round 1).

    A character or block device at `dest` (e.g. /dev/null) can't be renamed
    over, so it's written directly, as `open("wb")` did, and `mtime` isn't
    stamped on it. A directory, FIFO, or socket is refused (_check_destination)
    before `write` runs, so a download isn't streamed only to fail at the
    rename, and a FIFO is never replaced or blocked on (#887).
    """
    target = Path(os.path.realpath(dest)) if dest.is_symlink() else dest
    target_st = _check_destination(target)
    if target_st is not None and _is_device(target_st):
        with open(target, "wb") as fh:
            write(fh)
        return
    tmp = target.with_name(_PARTIAL_DOWNLOAD_PREFIX + secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        try:
            fh = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with fh:
            write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        if target_st is not None:
            _copy_owner_and_mode(tmp, target_st)
        if mtime is not None:
            os.utime(tmp, (mtime, mtime))
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _fsync_directory(target.parent)


def _is_device(st: os.stat_result) -> bool:
    return stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode)


def _check_destination(dest: Path) -> os.stat_result | None:
    """Raise if _write_atomically can't write `dest`; else its stat, or None if absent.

    Callers that fetch content before writing (a Workspace export) call this
    first too, so a bad destination fails before the round trip. Raises
    IsADirectoryError for a directory, OSError(EINVAL) for a FIFO or socket,
    and PermissionError for a file this process can't open for writing (a
    rename only needs directory permission, so without this a read-only file
    would be silently replaced; PR #884 QA round 1). A symlink is followed.
    """
    try:
        st = dest.stat()
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(st.st_mode):
        raise IsADirectoryError(errno.EISDIR, "destination is a directory", str(dest))
    if not stat.S_ISREG(st.st_mode) and not _is_device(st):
        raise OSError(errno.EINVAL, "destination exists but isn't a regular file", str(dest))
    if not os.access(dest, os.W_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(dest))
    return st


def _copy_owner_and_mode(tmp: Path, old: os.stat_result) -> None:
    """Give `tmp` the replaced file's owner, group, and permission bits.

    Owner and group are best effort: only root can give a file away, and
    anyone else can only pick a group they belong to. When the full chown is
    refused, the group alone is still tried (PR #1001 QA round 1). chown runs
    before chmod because it can clear bits that chmod then sets.
    """
    if hasattr(os, "chown"):
        tmp_st = os.stat(tmp)
        if (tmp_st.st_uid, tmp_st.st_gid) != (old.st_uid, old.st_gid):
            try:
                os.chown(tmp, old.st_uid, old.st_gid)
            except OSError:
                if tmp_st.st_gid != old.st_gid:
                    with contextlib.suppress(OSError):
                        os.chown(tmp, -1, old.st_gid)
    os.chmod(tmp, old.st_mode & 0o777)


def _fsync_directory(directory: Path) -> None:
    """Persist a rename inside `directory`. Best effort: Windows can't open a
    directory, and some filesystems refuse to fsync one; the rename itself has
    already happened either way."""
    with contextlib.suppress(OSError):
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
