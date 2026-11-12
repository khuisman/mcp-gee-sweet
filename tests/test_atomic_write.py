import os
import stat
from datetime import UTC, datetime

import pytest

from mcp_gee_sweet.tools import atomic_write
from tests.conftest import IS_ROOT


def _partial_files(directory):
    return [p.name for p in directory.iterdir() if atomic_write._is_partial_download(p.name)]


class TestWriteAtomically:
    """#844: _write_atomically, the shared write path behind every download."""

    def test_failure_leaves_existing_file_and_no_temp(self, tmp_path):
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"original")

        def _write(fh):
            fh.write(b"partial")
            raise OSError("disk full")

        with pytest.raises(OSError, match="disk full"):
            atomic_write._write_atomically(dest, _write)
        assert dest.read_bytes() == b"original"
        assert _partial_files(tmp_path) == []

    def test_success_replaces_content_and_stamps_mtime(self, tmp_path):
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"original")
        stamp = datetime(2024, 6, 1, tzinfo=UTC).timestamp()

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"), stamp)

        assert dest.read_bytes() == b"new"
        assert dest.stat().st_mtime == stamp
        assert _partial_files(tmp_path) == []

    def test_existing_file_mode_is_kept(self, tmp_path):
        dest = tmp_path / "f.sh"
        dest.write_bytes(b"old")
        dest.chmod(0o750)

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.stat().st_mode & 0o777 == 0o750

    @pytest.mark.skipif(IS_ROOT, reason="root can write a 0o444 file")
    def test_read_only_destination_is_refused_not_replaced(self, tmp_path):
        """PR #884 QA round 1: a rename only needs directory write permission,
        so a file the user made read-only was silently replaced. The old
        open('wb') raised PermissionError; that refusal is kept."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"protected")
        dest.chmod(0o444)

        with pytest.raises(PermissionError):
            atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.read_bytes() == b"protected"
        assert dest.stat().st_mode & 0o777 == 0o444
        assert _partial_files(tmp_path) == []

    @pytest.mark.skipif(IS_ROOT, reason="root can write a 0o444 file")
    def test_read_only_symlink_target_is_refused(self, tmp_path):
        real = tmp_path / "real.bin"
        real.write_bytes(b"protected")
        real.chmod(0o444)
        link = tmp_path / "link.bin"
        link.symlink_to(real)

        with pytest.raises(PermissionError):
            atomic_write._write_atomically(link, lambda fh: fh.write(b"new"))

        assert real.read_bytes() == b"protected"

    def test_setuid_setgid_sticky_bits_are_not_carried_over(self, tmp_path):
        """PR #884 QA round 1: an in-place write by a non-root process has the
        kernel clear setuid/setgid, so the replacement mustn't copy them."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"old")
        dest.chmod(0o4755)

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.stat().st_mode & 0o7777 == 0o755

    def test_new_file_gets_umask_default_mode(self, tmp_path):
        """Same mode a plain open('wb') would give, not mkstemp's 0o600."""
        reference = tmp_path / "reference"
        reference.write_bytes(b"")
        dest = tmp_path / "f.bin"

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.stat().st_mode & 0o777 == reference.stat().st_mode & 0o777

    def test_symlink_destination_is_written_through(self, tmp_path):
        """_safe_local_dest keeps a user's symlink inside the target directory
        working; the rename must replace the link's target, not the link."""
        real = tmp_path / "elsewhere" / "real.bin"
        real.parent.mkdir()
        real.write_bytes(b"old")
        link = tmp_path / "link.bin"
        link.symlink_to(real)

        atomic_write._write_atomically(link, lambda fh: fh.write(b"new"))

        assert link.is_symlink()
        assert real.read_bytes() == b"new"
        assert _partial_files(real.parent) == []

    def test_temp_file_and_directory_are_fsynced(self, tmp_path, monkeypatch):
        """#887: without an fsync before the rename, a power loss could leave
        dest empty or truncated, contradicting the docstring."""
        synced: list[int] = []
        real_fsync = os.fsync

        def _record(fd):
            synced.append(fd)
            return real_fsync(fd)

        monkeypatch.setattr(atomic_write.os, "fsync", _record)
        dest = tmp_path / "f.bin"

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert len(synced) == 2  # the temp file, then the directory
        assert dest.read_bytes() == b"new"

    def test_fdopen_failure_closes_fd_and_removes_temp(self, tmp_path, monkeypatch):
        """#887: the fd from os.open leaked when os.fdopen raised."""
        closed: list[int] = []
        real_close = os.close

        def _fdopen_fails(fd, *args, **kwargs):
            raise OSError("fdopen failed")

        def _record_close(fd):
            closed.append(fd)
            return real_close(fd)

        monkeypatch.setattr(atomic_write.os, "fdopen", _fdopen_fails)
        monkeypatch.setattr(atomic_write.os, "close", _record_close)
        dest = tmp_path / "f.bin"

        with pytest.raises(OSError, match="fdopen failed"):
            atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert len(closed) == 1
        assert _partial_files(tmp_path) == []
        assert not dest.exists()

    def test_owner_and_group_are_carried_over(self, tmp_path, monkeypatch):
        """#887: replacing the inode dropped owner/group, so a root process
        (the Docker image) turned a host user's file into a root:root one."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"old")
        real_stat = os.stat
        calls: list[tuple] = []

        def _foreign_owner_stat(path, *args, **kwargs):
            st = real_stat(path, *args, **kwargs)
            if os.fspath(path) == str(dest):
                fields = list(st)
                fields[4], fields[5] = 4242, 4343  # st_uid, st_gid
                return os.stat_result(fields)
            return st

        monkeypatch.setattr(atomic_write.Path, "stat", lambda self, **kw: _foreign_owner_stat(self))
        monkeypatch.setattr(atomic_write.os, "chown", lambda p, u, g: calls.append((u, g)))

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert calls == [(4242, 4343)]
        assert dest.read_bytes() == b"new"

    def test_group_alone_is_kept_when_full_chown_is_refused(self, tmp_path, monkeypatch):
        """PR #1001 QA round 1: a non-root process can't set another user as
        owner, so the full chown failed and the group was silently lost too."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"old")
        real_stat = os.stat
        calls: list[tuple] = []

        def _foreign_owner_stat(path, *args, **kwargs):
            st = real_stat(path, *args, **kwargs)
            if os.fspath(path) == str(dest):
                fields = list(st)
                fields[4], fields[5] = 4242, 4343
                return os.stat_result(fields)
            return st

        def _chown(path, uid, gid):
            calls.append((uid, gid))
            if uid != -1:
                raise PermissionError("not permitted")

        monkeypatch.setattr(atomic_write.Path, "stat", lambda self, **kw: _foreign_owner_stat(self))
        monkeypatch.setattr(atomic_write.os, "chown", _chown)

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert calls == [(4242, 4343), (-1, 4343)]
        assert dest.read_bytes() == b"new"

    def test_directory_destination_is_refused_before_writing(self, tmp_path):
        """PR #1001 QA round 1: a directory at dest let the whole download
        stream into the temp file, then failed at the rename with an error
        naming the internal temp file."""
        dest = tmp_path / "hello.txt"
        dest.mkdir()
        wrote: list[bool] = []

        with pytest.raises(IsADirectoryError, match=r"hello\.txt"):
            atomic_write._write_atomically(dest, lambda fh: wrote.append(True))

        assert wrote == []
        assert _partial_files(tmp_path) == []

    def test_failed_chown_is_ignored(self, tmp_path, monkeypatch):
        """A non-root process can't give a file away; the write still succeeds."""
        dest = tmp_path / "f.bin"
        dest.write_bytes(b"old")
        real_stat = os.stat

        def _foreign_owner_stat(path, *args, **kwargs):
            st = real_stat(path, *args, **kwargs)
            if os.fspath(path) == str(dest):
                fields = list(st)
                fields[4] = 4242
                return os.stat_result(fields)
            return st

        def _chown_denied(*args):
            raise PermissionError("not permitted")

        monkeypatch.setattr(atomic_write.Path, "stat", lambda self, **kw: _foreign_owner_stat(self))
        monkeypatch.setattr(atomic_write.os, "chown", _chown_denied)

        atomic_write._write_atomically(dest, lambda fh: fh.write(b"new"))

        assert dest.read_bytes() == b"new"

    def test_character_device_is_written_directly(self, tmp_path):
        """#887: /dev/null can't be renamed over; the old open('wb') wrote to
        it, and a symlink to it is followed the same way."""
        link = tmp_path / "out"
        link.symlink_to("/dev/null")

        atomic_write._write_atomically(link, lambda fh: fh.write(b"discarded"), 12345.0)

        assert link.is_symlink()
        assert _partial_files(tmp_path) == []

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
    def test_fifo_is_refused_not_replaced(self, tmp_path):
        """#887: a FIFO would be replaced by a regular file, or block a direct
        write until a reader appeared."""
        fifo = tmp_path / "pipe"
        os.mkfifo(fifo)

        wrote: list[bool] = []
        with pytest.raises(OSError, match="isn't a regular file"):
            atomic_write._write_atomically(fifo, lambda fh: wrote.append(True))

        assert wrote == []

        assert stat.S_ISFIFO(os.lstat(fifo).st_mode)
        assert _partial_files(tmp_path) == []

    def test_partial_name_matcher_is_exact(self):
        assert atomic_write._is_partial_download(".gee-sweet-partial-0123456789abcdef")
        assert not atomic_write._is_partial_download("gee-sweet-partial-0123456789abcdef")
        assert not atomic_write._is_partial_download(".gee-sweet-partial-0123456789abcdef.txt")
        assert not atomic_write._is_partial_download("notes.txt")
