import mimetypes

import pytest

from mcp_gee_sweet.tools.mime_types import guess_mime_type


class TestGuessMimeType:
    """#930: the shared filename → MIME type guess behind Gmail attachments and
    Drive uploads."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("report.csv.gz", "application/gzip"),
            ("dump.sql.bz2", "application/x-bzip2"),
            ("data.json.xz", "application/x-xz"),
            ("old.tar.Z", "application/x-compress"),
            ("page.html.br", "application/x-brotli"),
            # .tgz is .tar.gz by mimetypes' suffix_map.
            ("bundle.tgz", "application/gzip"),
        ],
    )
    def test_compressed_file_gets_its_compression_type(self, filename, expected):
        assert guess_mime_type(filename) == expected

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("report.csv", "text/csv"),
            ("photo.JPG", "image/jpeg"),
            ("archive.tar", "application/x-tar"),
        ],
    )
    def test_uncompressed_file_gets_its_own_type(self, filename, expected):
        assert guess_mime_type(filename) == expected

    @pytest.mark.parametrize("filename", ["README", "weird.zzzunknown", ""])
    def test_unknown_is_octet_stream(self, filename):
        assert guess_mime_type(filename) == "application/octet-stream"

    def test_path_with_directories_uses_the_basename(self):
        assert guess_mime_type("/tmp/some.dir/report.csv.gz") == "application/gzip"

    def test_ignores_host_mimetypes_database(self, monkeypatch):
        # PR #928 QA: e.g. a Windows host with Excel maps .csv to vnd.ms-excel.
        monkeypatch.setattr(
            mimetypes, "guess_type", lambda *a, **k: ("application/vnd.ms-excel", None)
        )

        assert guess_mime_type("data.csv") == "text/csv"
