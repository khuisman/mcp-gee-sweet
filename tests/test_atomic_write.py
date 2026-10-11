import os
from datetime import datetime, timezone

import pytest

from mcp_gee_sweet.tools import atomic_write


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
        stamp = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()

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

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0o444 file")
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

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0o444 file")
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

    def test_partial_name_matcher_is_exact(self):
        assert atomic_write._is_partial_download(".gee-sweet-partial-0123456789abcdef")
        assert not atomic_write._is_partial_download("gee-sweet-partial-0123456789abcdef")
        assert not atomic_write._is_partial_download(".gee-sweet-partial-0123456789abcdef.txt")
        assert not atomic_write._is_partial_download("notes.txt")
