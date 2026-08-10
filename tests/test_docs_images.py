"""Tests for docs/images.py — inline-image size validation and downscaling (#400)."""

import io
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError
from PIL import Image as PILImage

from mcp_gee_sweet.tools.docs import images


def _png_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color="blue").save(buf, format="PNG")
    return buf.getvalue()


class TestCheckDimensions:
    def test_within_limit_returns_none(self):
        assert images.check_dimensions(5000, 5000) is None  # exactly 25MP

    def test_over_limit_returns_error(self):
        result = images.check_dimensions(14609, 2434)
        assert result is not None
        assert "35.6 megapixels" in result["error"]
        assert "25 megapixels" in result["error"]
        assert "auto_downscale=True" in result["error"]

    def test_at_exact_limit_is_not_an_error(self):
        assert images.check_dimensions(5000, 5000) is None
        assert images.check_dimensions(5001, 5000) is not None


class TestCheckImageBytes:
    def test_oversized_png_returns_error(self):
        result = images.check_image_bytes(_png_bytes(6000, 6000))
        assert result is not None
        assert "36.0 megapixels" in result["error"]

    def test_undersized_png_returns_none(self):
        assert images.check_image_bytes(_png_bytes(100, 100)) is None

    def test_undecodable_bytes_returns_none(self):
        # Validation is additive, not a gate — an unreadable file still gets its
        # real answer straight from the Docs API, same as before #400.
        assert images.check_image_bytes(b"not an image") is None


class TestDownscaleImageBytes:
    def test_oversized_png_downscales_to_within_limit(self):
        result = images.downscale_image_bytes(_png_bytes(6000, 6000))
        assert result is not None
        resized_bytes, mime_type = result
        assert mime_type == "image/png"
        with PILImage.open(io.BytesIO(resized_bytes)) as img:
            width, height = img.size
        assert width * height <= images.MAX_INLINE_IMAGE_PIXELS

    def test_undersized_png_returns_none(self):
        # Nothing to do — caller should keep using the original bytes/upload path.
        assert images.downscale_image_bytes(_png_bytes(100, 100)) is None

    def test_undecodable_bytes_returns_none(self):
        assert images.downscale_image_bytes(b"not an image") is None

    def test_animated_gif_declines_rather_than_dropping_frames(self):
        frames = [
            PILImage.new("RGB", (6000, 6000), color="red"),
            PILImage.new("RGB", (6000, 6000), color="blue"),
        ]
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
        assert images.downscale_image_bytes(buf.getvalue()) is None

    def test_oversized_jpeg_preserves_format_and_converts_rgba_to_rgb(self):
        buf = io.BytesIO()
        # RGBA can't be saved as JPEG directly — this exercises the conversion.
        PILImage.new("RGBA", (6000, 6000), color=(0, 0, 255, 128)).convert("RGB").save(
            buf, format="JPEG"
        )
        result = images.downscale_image_bytes(buf.getvalue())
        assert result is not None
        resized_bytes, mime_type = result
        assert mime_type == "image/jpeg"
        with PILImage.open(io.BytesIO(resized_bytes)) as img:
            assert img.format == "JPEG"


class TestTooLargeMessage:
    def test_names_limit_and_actual_size(self):
        msg = images.too_large_message(14609, 2434)
        assert "14609x2434" in msg
        assert "35.6 megapixels" in msg
        assert "25 megapixels" in msg
        assert images._DOCS_IMAGE_LIMITS_URL in msg


class TestRewriteTooLargeError:
    def test_rewrites_matching_too_large_message(self):
        original = "Invalid requests[0].insertInlineImage: The provided image is too large."
        rewritten = images.rewrite_too_large_error(original)
        assert original in rewritten
        assert "25 megapixels" in rewritten
        assert images._DOCS_IMAGE_LIMITS_URL in rewritten

    def test_leaves_unrelated_insertinlineimage_error_unchanged(self):
        original = (
            "Invalid requests[0].insertInlineImage: There was a problem retrieving the image."
        )
        assert images.rewrite_too_large_error(original) == original

    def test_leaves_unrelated_error_unchanged(self):
        original = "Some other batchUpdate failure entirely."
        assert images.rewrite_too_large_error(original) == original


class TestUploadAndShareImage:
    async def test_success_returns_uri_file_id_permission_id(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "new1"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=new1"
        }

        result = await images.upload_and_share_image(
            drive_svc, b"fake-bytes", "image/png", "pic.png", "folder1"
        )

        assert result == {
            "uri": "https://drive.google.com/uc?id=new1",
            "file_id": "new1",
            "permission_id": "perm1",
        }
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"] == {"name": "pic.png", "parents": ["folder1"]}

    async def test_no_parent_folder_omits_parents_key(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "new1"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=new1"
        }

        await images.upload_and_share_image(drive_svc, b"fake-bytes", "image/png", "pic.png", None)

        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert "parents" not in create_kwargs["body"]

    async def test_quota_exceeded_returns_sa_quota_error(self):
        drive_svc = MagicMock()
        resp = MagicMock()
        resp.status = 403
        drive_svc.files.return_value.create.return_value.execute.side_effect = HttpError(
            resp=resp,
            content=b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}',
            uri="https://www.googleapis.com/drive/v3/files",
        )

        result = await images.upload_and_share_image(
            drive_svc, b"fake-bytes", "image/png", "pic.png", "folder1"
        )
        assert result["error"] == images._SA_QUOTA_ERROR

    async def test_missing_web_content_link_is_error(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "new1"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {}

        result = await images.upload_and_share_image(
            drive_svc, b"fake-bytes", "image/png", "pic.png", "folder1"
        )
        assert "error" in result
        assert "webContentLink" in result["error"]


class TestDownscaleDriveFile:
    async def test_success_uploads_resized_copy_with_suffixed_name(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "resized1"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=resized1"
        }

        png_bytes = _png_bytes(6000, 6000)

        class _FakeDownloader:
            def __init__(self, fh, request):
                fh.write(png_bytes)

            def next_chunk(self):
                return None, True

        with (
            patch("mcp_gee_sweet.tools.docs.images.MediaIoBaseDownload", _FakeDownloader),
            patch("mcp_gee_sweet.tools.docs.images.thread_http"),
        ):
            result = await images.downscale_drive_file(
                drive_svc, "orig1", name="logo.png", parent_folder_id="folder1"
            )

        assert result == {
            "uri": "https://drive.google.com/uc?id=resized1",
            "file_id": "resized1",
            "permission_id": "perm1",
        }
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["name"] == "logo.png (resized)"
        assert create_kwargs["body"]["parents"] == ["folder1"]
        # The original file is never touched — no update()/delete() call against it.
        drive_svc.files.return_value.update.assert_not_called()
        drive_svc.files.return_value.delete.assert_not_called()

    async def test_download_failure_is_error(self):
        drive_svc = MagicMock()

        class _FailingDownloader:
            def __init__(self, fh, request):
                pass

            def next_chunk(self):
                raise RuntimeError("network boom")

        with (
            patch("mcp_gee_sweet.tools.docs.images.MediaIoBaseDownload", _FailingDownloader),
            patch("mcp_gee_sweet.tools.docs.images.thread_http"),
        ):
            result = await images.downscale_drive_file(
                drive_svc, "orig1", name="logo.png", parent_folder_id="folder1"
            )

        assert "error" in result
        assert "network boom" in result["error"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_already_within_limit_source_is_error(self):
        # downscale_drive_file is only meant to be called once a caller's own size
        # check already found the image oversized; if the bytes it downloads turn
        # out to already fit, downscale_image_bytes correctly returns None (nothing
        # to do), and that must surface as an error here rather than silently
        # uploading a no-op "resized" copy.
        drive_svc = MagicMock()
        png_bytes = _png_bytes(100, 100)

        class _FakeDownloader:
            def __init__(self, fh, request):
                fh.write(png_bytes)

            def next_chunk(self):
                return None, True

        with (
            patch("mcp_gee_sweet.tools.docs.images.MediaIoBaseDownload", _FakeDownloader),
            patch("mcp_gee_sweet.tools.docs.images.thread_http"),
        ):
            result = await images.downscale_drive_file(
                drive_svc, "orig1", name="logo.png", parent_folder_id="folder1"
            )

        assert "error" in result
        drive_svc.files.return_value.create.assert_not_called()
