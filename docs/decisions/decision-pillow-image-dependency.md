# Decision: Add Pillow as a Dependency for Inline-Image Size Handling

**Date:** 2026-08-07
**Snapshot commit:** branch `feat/jay/issue-400` — see `src/mcp_gee_sweet/tools/docs/images.py`

## Background

Issue #400: `insert_inline_image` (and its sibling image-insert paths — `insert_local_images`,
and the markdown/HTML image embedding shared by `create_doc`/`create_doc_from_file`/
`write_doc_content`) fails with Google's raw, opaque `HttpError 400 "...The provided image is
too large."` for any image over Google Docs' documented ~25-megapixel inline-image ceiling
(confirmed: <https://developers.google.com/workspace/docs/api/how-tos/images>). The ask covers
both a clear pre-validated error and an opt-in automatic downscale.

Reading real pixel dimensions and, for the opt-in path, actually resizing arbitrary PNG/JPEG/GIF
image bytes requires a real image-decoding library. This repo had no such dependency before
this issue.

## Options Considered

### Option A: Hand-rolled header parsing, no downscale

Parse PNG (`IHDR` chunk), JPEG (`SOF` markers), and GIF (logical screen descriptor) headers
by hand to read `width`/`height` without a new dependency. Covers the pre-validation half of
the ask (clear error naming the limit and the image's actual size) but not the auto-downscale
half — an actual resize requires decoding and re-encoding pixel data, which header parsing
can't do.

**Pros:** zero new dependency, smaller Docker image, no new CVE surface.
**Cons:** only satisfies part of the confirmed scope (user explicitly asked for both the error
path and the opt-in auto-downscale, not one or the other).

### Option B: Add Pillow (chosen)

Use Pillow (`PIL.Image`) for both dimension reads and the downscale resize — one code path
instead of two, and no hand-rolled per-format header parsing to maintain.

**Pros:** covers the full confirmed scope with one library; ships as precompiled wheels for
all platforms this project targets (no C toolchain needed at install/build time, including in
the Docker image); mature, widely-used, actively maintained.
**Cons:** a new mandatory (not optional-extra) dependency — every install pulls it in, not just
callers who use `auto_downscale`.

## Decision

**Use Option B.** Added `Pillow>=11.0.0` to `pyproject.toml`'s core `dependencies` (not an
optional extra) — confirmed with the user before adding it, given it affects every install's
dependency footprint and the Docker image, not just this one ticket. `tools/docs/images.py`
is the single module that imports it; every insertInlineImage call site goes through that
module rather than importing `PIL` directly.

## Scope boundary this decision implies

Validation + auto-downscale only apply where a call site already has (or already fetches) the
image's own bytes or Drive-reported dimensions without new networking: a local file path, an
already-uploaded Drive file (`drive_file_id` / `"drive:"` reference). A bare `http(s)://` URI
is out of scope for both — fetching arbitrary external content just to validate it, or
re-hosting a downscaled copy somewhere Google can fetch it from, would be a materially bigger
behavior change than this fix warrants. Those sources instead get the minimum fallback from
the issue's own third ask-bullet: the raw `HttpError` is caught and its message rewritten to
name the known cause, without image-specific numbers.

## When to Re-evaluate

If a future ticket wants `uri`-source validation/downscaling too (would need to add an HTTP
fetch and, for downscale, a re-upload/re-hosting step), that's new scope on top of this
decision, not an extension of it — revisit whether Pillow is still the right tool once that
shape is known, though it very likely still is.
