"""Tests for docs/images.py — inline-image tools (insert_inline_image,
insert_local_images) plus size validation and downscaling (#400)."""

import io
import json
import os
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError
from PIL import Image as PILImage

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs import images


def _png_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color="blue").save(buf, format="PNG")
    return buf.getvalue()


def _make_png_bytes(width: int, height: int) -> bytes:
    """A real (but minimal-content) PNG at the given pixel dimensions, for #400's
    inline-image size-limit tests — Pillow needs to actually decode a header to read
    dimensions, so a fake byte string won't do."""
    return _png_bytes(width, height)


def _noise_png_bytes(width: int, height: int) -> bytes:
    """A real, Pillow-decodable PNG of random (incompressible) pixel data, for #562's
    byte-size (not megapixel) limit tests — unlike _png_bytes' solid color, which PNG
    compresses to near-nothing regardless of dimensions, noise data stays large so
    downscaling actually has to shrink pixel count to reduce encoded size."""
    buf = io.BytesIO()
    img = PILImage.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _make_tool_registry():
    captured = {}

    def tool(annotations=None):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


def _make_ctx(**services):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    for k, v in services.items():
        setattr(lc, k, v)
    return ctx


_docs_tool, _docs_tools = _make_tool_registry()
docs_module.register(_docs_tool)


def _quota_http_error():
    resp = MagicMock()
    resp.status = 403
    return HttpError(
        resp=resp,
        content=b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}',
    )


def _build_doc_body(paragraph_runs: list[list[str]]) -> tuple[dict, list[tuple[int, str]]]:
    """Build a synthetic Docs API body from a list of paragraphs, each a list of
    textRun content strings (the last run of a paragraph should end in "\\n",
    matching how the real API terminates a paragraph). Returns (doc, paragraphs)
    where paragraphs is [(start_index, concatenated_text), ...] for computing
    expected offsets in tests without hand-counting characters."""
    idx = 1
    content = []
    paragraphs = []
    for runs in paragraph_runs:
        para_start = idx
        elements = []
        for text in runs:
            elements.append(
                {"startIndex": idx, "endIndex": idx + len(text), "textRun": {"content": text}}
            )
            idx += len(text)
        content.append(
            {"startIndex": para_start, "endIndex": idx, "paragraph": {"elements": elements}}
        )
        paragraphs.append((para_start, "".join(runs)))
    return {"body": {"content": content}}, paragraphs


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


class TestCheckFileSize:
    def test_within_limit_returns_none(self):
        assert images.check_file_size(images.MAX_INLINE_IMAGE_BYTES) is None

    def test_over_limit_returns_error(self):
        result = images.check_file_size(images.MAX_INLINE_IMAGE_BYTES + 1)
        assert result is not None
        assert "50MB" in result["error"]

    def test_at_exact_limit_is_not_an_error(self):
        assert images.check_file_size(images.MAX_INLINE_IMAGE_BYTES) is None
        assert images.check_file_size(images.MAX_INLINE_IMAGE_BYTES + 1) is not None


class TestTooLargeBytesMessage:
    def test_names_limit_and_actual_size(self):
        msg = images.too_large_bytes_message(75_000_000)
        assert "75.0MB" in msg
        assert "50MB" in msg
        assert "auto_downscale=True" in msg
        assert images._DOCS_IMAGE_LIMITS_URL in msg


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

    def test_over_byte_limit_but_under_megapixel_limit_returns_byte_error(self, monkeypatch):
        # #562's motivating case: a low-compressibility image that's well under the
        # megapixel limit but still oversized in raw bytes — the byte-size check must
        # catch it even though check_dimensions alone would pass it. A tiny threshold
        # stands in for Google's real 50MB ceiling so the test doesn't need to
        # generate an actual multi-megabyte image.
        monkeypatch.setattr(images, "MAX_INLINE_IMAGE_BYTES", 10)
        result = images.check_image_bytes(_png_bytes(100, 100))
        assert result is not None
        assert "MB" in result["error"]
        assert "megapixels" not in result["error"]  # the byte check fired, not the pixel one

    def test_over_byte_limit_takes_precedence_over_undecodable(self, monkeypatch):
        # The byte-size check applies to any oversized data, decodable or not —
        # unlike the megapixel check, which is a no-op for undecodable bytes.
        monkeypatch.setattr(images, "MAX_INLINE_IMAGE_BYTES", 5)
        result = images.check_image_bytes(b"not an image but over the tiny limit")
        assert result is not None


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

    def test_over_byte_limit_but_under_megapixel_limit_still_downscales(self, monkeypatch):
        # #562: the megapixel-based scale factor alone is a no-op here (the image is
        # already within that limit), so downscale_image_bytes must fall back to its
        # own byte-size-driven shrink loop to make any progress at all. Noise data (not
        # _png_bytes' solid color, which PNG would compress to near-nothing regardless
        # of dimensions) keeps the encoded size tied to pixel count; a tiny threshold
        # stands in for Google's real 50MB ceiling so the fixture can stay small.
        monkeypatch.setattr(images, "MAX_INLINE_IMAGE_BYTES", 3000)
        original = _noise_png_bytes(80, 80)
        assert len(original) > 3000
        result = images.downscale_image_bytes(original)
        assert result is not None
        resized_bytes, mime_type = result
        assert mime_type == "image/png"
        assert len(resized_bytes) <= 3000
        with PILImage.open(io.BytesIO(resized_bytes)) as img:
            assert img.size[0] * img.size[1] < 80 * 80

    def test_within_both_limits_returns_none(self):
        assert images.downscale_image_bytes(_png_bytes(100, 100)) is None


class TestCheckDriveImageMetadata:
    def test_within_both_limits_returns_none(self):
        metadata = {"imageMediaMetadata": {"width": 100, "height": 100}, "size": "1000"}
        assert images.check_drive_image_metadata(metadata) is None

    def test_over_dimension_limit_returns_error(self):
        metadata = {"imageMediaMetadata": {"width": 14609, "height": 2434}, "size": "1000"}
        result = images.check_drive_image_metadata(metadata)
        assert result is not None
        assert "35.6 megapixels" in result["error"]

    def test_over_byte_limit_but_under_dimension_limit_returns_error(self):
        metadata = {
            "imageMediaMetadata": {"width": 100, "height": 100},
            "size": str(images.MAX_INLINE_IMAGE_BYTES + 1),
        }
        result = images.check_drive_image_metadata(metadata)
        assert result is not None
        assert "50MB" in result["error"]

    def test_no_metadata_available_returns_none(self):
        # A non-image binary, or metadata that doesn't report enough to check —
        # nothing to validate against, so no error (same additive-not-a-gate
        # philosophy as check_image_bytes' undecodable-bytes case).
        assert images.check_drive_image_metadata({}) is None

    def test_dimension_violation_checked_before_size(self):
        # Both a dimension and a size violation present — dimensions win, matching
        # downscale_image_bytes' own resize-by-pixels-first behavior.
        metadata = {
            "imageMediaMetadata": {"width": 14609, "height": 2434},
            "size": str(images.MAX_INLINE_IMAGE_BYTES + 1),
        }
        result = images.check_drive_image_metadata(metadata)
        assert result is not None
        assert "megapixels" in result["error"]


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
        # Limit-agnostic (#562 QA round 1) — Google's error doesn't say which of the
        # two limits was hit, and this call site never fetched the bytes to check.
        assert "25 megapixels" in rewritten
        assert "50MB" in rewritten
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


# ---------------------------------------------------------------------------
# insert_inline_image (#145)
# ---------------------------------------------------------------------------


class TestInsertInlineImage:
    def _ctx(self, docs_svc=None, drive_svc=None):
        return _make_ctx(
            docs_service=docs_svc or MagicMock(),
            drive_service=drive_svc or MagicMock(),
            doc_cache=MagicMock(),
        )

    async def test_uri_only_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=5, uri="https://example.com/img.png", ctx=ctx
        )
        assert result == {"docId": "doc1", "index": 5}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["location"]["index"] == 5
        assert req["uri"] == "https://example.com/img.png"
        assert "objectSize" not in req

    async def test_width_and_height_included(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            width=200.0,
            height=100.0,
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["objectSize"]["width"] == {"magnitude": 200.0, "unit": "PT"}
        assert req["objectSize"]["height"] == {"magnitude": 100.0, "unit": "PT"}

    async def test_drive_file_id_fetches_web_content_link(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=3, drive_file_id="file1", ctx=ctx
        )
        assert "error" not in result
        drive_svc.files.return_value.get.assert_called_with(
            fileId="file1",
            fields="name,parents,webContentLink,imageMediaMetadata,size",
            supportsAllDrives=True,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["uri"] == "https://drive.google.com/uc?id=file1"

    async def test_missing_both_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_inline_image"](doc_id="doc1", index=1, ctx=ctx)
        assert "error" in result

    async def test_both_provided_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            drive_file_id="file1",
            ctx=ctx,
        )
        assert "error" in result

    async def test_drive_file_no_web_content_link_returns_error(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {}
        ctx = self._ctx(drive_svc=drive_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, drive_file_id="file1", ctx=ctx
        )
        assert "error" in result

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, uri="https://example.com/img.png", ctx=ctx
        )
        assert "error" in result

    async def test_oversized_drive_image_fails_fast_without_batchupdate(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.png",
            "webContentLink": "https://drive.google.com/uc?id=file1",
            "imageMediaMetadata": {"width": 14609, "height": 2434},
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, drive_file_id="file1", ctx=ctx
        )
        assert "error" in result
        assert "35.6 megapixels" in result["error"]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_oversized_by_bytes_drive_image_fails_fast_without_batchupdate(self):
        # #562: an image under the megapixel limit but over Google's byte-size limit,
        # caught via Drive's own reported "size" — no download needed.
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.png",
            "webContentLink": "https://drive.google.com/uc?id=file1",
            "imageMediaMetadata": {"width": 100, "height": 100},
            "size": str(images.MAX_INLINE_IMAGE_BYTES + 1),
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, drive_file_id="file1", ctx=ctx
        )
        assert "error" in result
        assert "50MB" in result["error"]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_oversized_drive_image_auto_downscale_inserts_resized_copy(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.side_effect = [
            {
                "name": "big.png",
                "parents": ["folder1"],
                "webContentLink": "https://drive.google.com/uc?id=file1",
                "imageMediaMetadata": {"width": 6000, "height": 6000},
            },
            {"webContentLink": "https://drive.google.com/uc?id=resized1"},
        ]
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "resized1"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm-resized"
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)

        png_bytes = _make_png_bytes(6000, 6000)

        class _FakeDownloader:
            def __init__(self, fh, request):
                fh.write(png_bytes)

            def next_chunk(self):
                return None, True

        with (
            patch("mcp_gee_sweet.tools.docs.images.MediaIoBaseDownload", _FakeDownloader),
            patch("mcp_gee_sweet.tools.docs.images.thread_http"),
        ):
            result = await _docs_tools["insert_inline_image"](
                doc_id="doc1",
                index=1,
                drive_file_id="file1",
                auto_downscale=True,
                ctx=ctx,
            )

        assert "error" not in result
        assert result["resized_file_id"] == "resized1"
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["uri"] == "https://drive.google.com/uc?id=resized1"

    async def test_too_large_batchupdate_error_is_rewritten(self):
        docs_svc = MagicMock()
        resp = MagicMock()
        resp.status = 400
        message = "Invalid requests[0].insertInlineImage: The provided image is too large."
        content = json.dumps({"error": {"code": 400, "message": message}}).encode()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=resp, content=content, uri="https://docs.googleapis.com/v1/documents/x:batchUpdate"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, uri="https://example.com/img.png", ctx=ctx
        )
        assert "error" in result
        assert "25 megapixels" in result["error"]
        assert "50MB" in result["error"]
        assert "auto_downscale" not in result["error"]  # uri source can't use it


# ---------------------------------------------------------------------------
# insert_local_images (#332)
# ---------------------------------------------------------------------------


class TestInsertLocalImages:
    def _ctx(self, docs_svc=None, drive_svc=None, folder_id=None):
        return _make_ctx(
            docs_service=docs_svc or MagicMock(),
            drive_service=drive_svc or MagicMock(),
            doc_cache=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id=folder_id,
        )

    def _docs_svc(self, doc):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = doc
        return docs_svc

    def _drive_svc(self, file_id="img1", web_content_link="https://drive.google.com/uc?id=img1"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": file_id,
            "name": "pic.png",
            "webViewLink": "https://drive.google.com/file/d/x/view",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "anyoneWithLink"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": web_content_link
        }
        return drive_svc

    async def test_empty_images_returns_error(self):
        ctx = self._ctx(folder_id="folder1")
        result = await _docs_tools["insert_local_images"](doc_id="doc1", images=[], ctx=ctx)
        assert "error" in result

    async def test_no_folder_id_returns_error(self):
        ctx = self._ctx()  # no folder_id param, no lc.folder_id default
        result = await _docs_tools["insert_local_images"](
            doc_id="doc1", images=[{"marker": "M", "local_path": "/x.png"}], ctx=ctx
        )
        assert "error" in result

    async def test_missing_local_file_reports_per_image_error(self, tmp_path):
        doc, _ = _build_doc_body([["before\n"], ["MARKER\n"], ["after\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(tmp_path / "missing.png")}],
            ctx=ctx,
        )

        assert len(result["results"]) == 1
        assert "error" in result["results"][0]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_marker_not_found_reports_per_image_error(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["before\n"], ["after\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "NOPE", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "not found" in result["results"][0]["error"]

    async def test_marker_not_unique_reports_per_image_error(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER here\n"], ["MARKER there\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "unique" in result["results"][0]["error"]

    async def test_successful_single_image_places_and_deletes_marker(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        # paragraphs: "before\n" [1,8), "MARKER\n" [8,15), "after\n" [15,21)
        doc, paragraphs = _build_doc_body([["before\n"], ["MARKER\n"], ["after\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc(file_id="img1")
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")
        marker_start = paragraphs[1][0]  # start index of the "MARKER\n" paragraph

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img), "width": 100.0}],
            ctx=ctx,
        )

        assert result["results"] == [
            {
                "marker": "MARKER",
                "local_path": str(img),
                "fileId": "img1",
                "index": marker_start,
                # revoke_sharing defaults to True — the temporary anyone:reader
                # share granted below is revoked again once the image is placed.
                "shared": False,
            }
        ]

        drive_svc.permissions.return_value.create.assert_called_once_with(
            fileId="img1",
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
            fields="id",
        )
        drive_svc.permissions.return_value.delete.assert_called_once_with(
            fileId="img1",
            permissionId="anyoneWithLink",
            supportsAllDrives=True,
        )

        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        image_req = body["requests"][0]["insertInlineImage"]
        assert image_req["location"]["index"] == marker_start
        assert image_req["uri"] == "https://drive.google.com/uc?id=img1"
        assert image_req["objectSize"]["width"] == {"magnitude": 100.0, "unit": "PT"}
        delete_req = body["requests"][1]["deleteContentRange"]
        assert delete_req["range"] == {
            "startIndex": marker_start + 1,
            "endIndex": marker_start + 1 + len("MARKER"),
        }

    async def test_multiple_images_processed_highest_marker_first(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, paragraphs = _build_doc_body([["ONE\n"], ["TWO\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "ONE", "local_path": str(img)},
                {"marker": "TWO", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        indices = [
            r["insertInlineImage"]["location"]["index"]
            for r in body["requests"]
            if "insertInlineImage" in r
        ]
        assert indices == sorted(indices, reverse=True)

    async def test_upload_failure_reports_per_image_error_and_skips_doc_edit(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_sharing_failure_reports_per_image_error_and_skips_doc_edit(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = Exception(
            "share failed"
        )
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_marks_caches_dirty_on_success(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        doc_cache = MagicMock()
        drive_folder_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        ctx.request_context.lifespan_context.drive_folder_cache = drive_folder_cache

        await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        doc_cache.mark_dirty.assert_called_once_with("doc1")
        drive_folder_cache.mark_dirty.assert_called_once_with("folder1")

    async def test_docs_get_error_returns_top_level_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = Exception(
            "not found"
        )
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": "/x.png"}],
            ctx=ctx,
        )

        assert "error" in result

    async def test_substring_marker_not_present_is_not_falsely_matched(self, tmp_path):
        # Regression: plain substring search would match "IMG1" inside "IMG10"
        # even though "IMG1" never appears as its own marker in the document.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["IMG10\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "IMG1", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "not found" in result["results"][0]["error"]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_substring_markers_both_present_resolve_to_correct_positions(self, tmp_path):
        # Regression: requesting both "IMG1" and "IMG10" where each appears exactly
        # once (in separate paragraphs) must not report a false "occurs twice" for
        # either — longest-first matching must not let "IMG10" ever get counted as
        # an extra occurrence of "IMG1".
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, paragraphs = _build_doc_body([["IMG1 here\n"], ["IMG10 there\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "IMG1", "local_path": str(img)},
                {"marker": "IMG10", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        assert all("error" not in r for r in result["results"])
        assert result["results"][0]["index"] == paragraphs[0][0]
        assert result["results"][1]["index"] == paragraphs[1][0]

    async def test_marker_with_astral_character_deletes_correct_utf16_span(self, tmp_path):
        # Regression: marker_len must be counted in UTF-16 units, not Python code
        # points — "😀" is 1 Python char but 2 UTF-16 units, so a naive len(marker)
        # would leave the deleteContentRange one unit short, stranding a character.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, paragraphs = _build_doc_body([["before 😀MARK after\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")
        para_start, para_text = paragraphs[0]
        marker = "😀MARK"
        marker_start = para_start + para_text.index(marker)
        # "😀" costs 2 UTF-16 units + "MARK" costs 4 -> 6 total, not len(marker) == 5.
        expected_end = marker_start + 1 + 6

        await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": marker, "local_path": str(img)}],
            ctx=ctx,
        )

        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        delete_req = next(
            r["deleteContentRange"] for r in body["requests"] if "deleteContentRange" in r
        )
        assert delete_req["range"]["endIndex"] == expected_end

    async def test_failed_batchupdate_entry_keeps_fileid_and_is_revoked(self, tmp_path):
        # PR #502 review round 1, finding #1: a doc-edit failure used to pop
        # "fileId" and return immediately, before ever reaching the revoke
        # logic — the image was genuinely uploaded and shared, but the caller
        # had no fileId to trace it and it was left world-readable forever.
        # Fixed version keeps fileId, still runs the revoke_sharing-respecting
        # cleanup, and reports the outcome honestly (error *and* shared status).
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "batchUpdate failed"
        )
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        entry = result["results"][0]
        assert entry["error"] == "doc edit failed: batchUpdate failed"
        assert entry["fileId"] == "img1"
        # revoke_sharing defaults True — the temporary share is still cleaned up
        # even though the embed itself failed.
        assert entry["shared"] is False
        drive_svc.permissions.return_value.delete.assert_called_once_with(
            fileId="img1", permissionId="anyoneWithLink", supportsAllDrives=True
        )

    async def test_failed_batchupdate_too_large_error_is_rewritten(self, tmp_path):
        # QA round 1 finding (PR #554): this doc-edit-failure path is one of three
        # insertInlineImage call sites #400 touched, but the only one that didn't
        # apply rewrite_too_large_error — an image that got this far (oversized but
        # undecodable by Pillow, so pre-validation silently skipped it) still got
        # Google's raw, opaque message instead of the clarified one.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        resp = MagicMock()
        resp.status = 400
        message = "Invalid requests[0].insertInlineImage: The provided image is too large."
        content = json.dumps({"error": {"code": 400, "message": message}}).encode()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = HttpError(
            resp=resp, content=content, uri="https://docs.googleapis.com/v1/documents/x:batchUpdate"
        )
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        error = result["results"][0]["error"]
        assert message in error
        assert "25 megapixels" in error
        assert "50MB" in error

    async def test_failed_batchupdate_with_revoke_sharing_false_leaves_image_shared(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "batchUpdate failed"
        )
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            revoke_sharing=False,
            ctx=ctx,
        )

        entry = result["results"][0]
        assert entry["error"] == "doc edit failed: batchUpdate failed"
        assert entry["fileId"] == "img1"
        assert entry["shared"] is True
        drive_svc.permissions.return_value.delete.assert_not_called()

    async def test_results_order_matches_images_input_order_not_doc_position_order(self, tmp_path):
        # Regression: successes used to be appended in descending-document-position
        # order (used internally for batchUpdate construction) while failures were
        # appended in input order, so results didn't line up with the images argument
        # whenever a caller listed markers in an order different from their document
        # position. Here "TWO" (input index 0) sits *after* "ONE" (input index 1) in
        # the document, so document-position order would put ONE first — but the
        # correct output order is input order: TWO's outcome, then ONE's.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["ONE\n"], ["TWO\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "TWO", "local_path": str(img)},
                {"marker": "ONE", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        assert [r["marker"] for r in result["results"]] == ["TWO", "ONE"]

    async def test_results_order_preserved_with_mixed_success_and_early_failure(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["ONE\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "MISSING", "local_path": str(img)},
                {"marker": "ONE", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        assert [r["marker"] for r in result["results"]] == ["MISSING", "ONE"]
        assert "error" in result["results"][0]
        assert "error" not in result["results"][1]

    async def test_oversized_local_image_fails_fast_without_upload(self, tmp_path):
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(14609, 2434))
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "35.6 megapixels" in result["results"][0]["error"]
        drive_svc.files.return_value.create.assert_not_called()
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_oversized_by_bytes_local_image_fails_fast_without_upload(
        self, tmp_path, monkeypatch
    ):
        # #562: an image under the megapixel limit but over Google's byte-size limit.
        # A patched threshold stands in for Google's real 50MB ceiling so the fixture
        # can stay a small, ordinary PNG.
        monkeypatch.setattr(images, "MAX_INLINE_IMAGE_BYTES", 10)
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(100, 100))
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        drive_svc.files.return_value.create.assert_not_called()
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_oversized_local_image_auto_downscale_uploads_resized_bytes(self, tmp_path):
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(6000, 6000))
        doc, paragraphs = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc(file_id="resized1")
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")
        marker_start = paragraphs[0][0]

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            auto_downscale=True,
            ctx=ctx,
        )

        assert result["results"] == [
            {
                "marker": "MARKER",
                "local_path": str(img),
                "fileId": "resized1",
                "downscaled": True,
                "index": marker_start,
                "shared": False,
            }
        ]
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["name"] == "big.png"
        # The full-size original bytes were never uploaded as-is — only the
        # resized copy — so create() was called exactly once, not once per
        # attempt.
        drive_svc.files.return_value.create.assert_called_once()
