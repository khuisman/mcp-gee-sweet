import asyncio
import logging
import re
import xml.etree.ElementTree as etree
from pathlib import Path
from typing import Any

import markdown as _md
from googleapiclient.errors import HttpError
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...cache import CACHE_VALIDATE_MODIFIED_TIME
from ..drive import _SA_QUOTA_ERROR
from ..drive.transfer import _upload_local_file
from ..response_limits import enforce_response_size_cap, write_capped_result_to_disk
from .anchors import resolve_heading_anchor
from .ast import Run, Table
from .emitter import ast_to_requests, extract_images, fill_tables
from .html_parser import html_to_ast
from .images import (
    check_drive_image_metadata,
    check_image_bytes,
    downscale_drive_file,
    downscale_image_bytes,
    rewrite_too_large_error,
    upload_and_share_image,
)
from .indices import _collect_doc_paragraphs, utf16_len

logger = logging.getLogger(__name__)


class _DollarEscapeExtension(Extension):
    """Treat \\$ as an escape for a literal $, matching CommonMark's escapable-punctuation
    set. Python-Markdown's default ESCAPED_CHARS omits $ (issue #213), so \\$ otherwise
    passes through untouched into the rendered Doc as a literal backslash+dollar — visible
    in prose written to defeat LaTeX/math renderers that treat $ as a delimiter."""

    def extendMarkdown(self, md):
        if "$" not in md.ESCAPED_CHARS:
            md.ESCAPED_CHARS.append("$")


_BARE_URL_PATTERN = r'(https?://[^\s<>"]+)'
_BARE_URL_TRAILING_PUNCT = ".,;:!?"


class _BareUrlInlineProcessor(InlineProcessor):
    """Autolink a bare http(s) URL left as plain text.

    Registered at low priority so it only sees text that survived
    Python-Markdown's built-in link/autolink/code-span processing untouched —
    an already-linked or code-spanned URL is never re-matched here."""

    def handleMatch(self, m, data):
        url = m.group(1)
        # Trim trailing sentence punctuation and an unmatched closing paren, matching
        # CommonMark/GFM extended autolink behavior — "see https://x.com." shouldn't
        # swallow the period, and "(https://x.com)" shouldn't swallow the paren.
        while url:
            if url[-1] in _BARE_URL_TRAILING_PUNCT or (
                url[-1] == ")" and url.count("(") < url.count(")")
            ):
                url = url[:-1]
            else:
                break
        el = etree.Element("a")
        el.set("href", url)
        el.text = url
        return el, m.start(1), m.start(1) + len(url)


class _BareUrlAutolinkExtension(Extension):
    """Autolink bare http(s):// URLs, matching CommonMark/GFM extended autolinks.
    Python-Markdown's core autolink only fires on <https://...> or [text](url)
    (issue #248) — a bare URL in prose is otherwise left as inert text."""

    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            _BareUrlInlineProcessor(_BARE_URL_PATTERN, md), "bare_url_autolink", 3
        )


def _md_to_html(md_text: str, autolink_urls: bool = True) -> str:
    """Convert Markdown to HTML using the Python markdown library (tables, fenced_code,
    sane_lists extensions, plus bare-URL autolinking and the \\$ escape fix).

    autolink_urls=False skips the bare-URL extension for callers who want a URL to
    render as plain text — e.g. a placeholder or example. Per-URL suppression (rather
    than disabling it for the whole call) is available by wrapping just that URL in
    backticks, which already protects it as an inline code span."""
    extensions = ["tables", "fenced_code", "sane_lists", _DollarEscapeExtension()]
    if autolink_urls:
        extensions.append(_BareUrlAutolinkExtension())
    return _md.markdown(md_text, extensions=extensions)


def _to_doc_requests(
    content: str,
    content_format: str = "html",
    start_index: int = 1,
    autolink_urls: bool = True,
) -> tuple[list[dict], list[Table]]:
    """Convert HTML or Markdown to Docs API batchUpdate requests via the AST pipeline.

    Returns (requests, tables) where tables is a list of Table AST nodes. Table cells
    are NOT filled here — call fill_tables() after executing the returned requests.
    autolink_urls only affects content_format="markdown" — see _md_to_html.
    """
    if content_format == "markdown":
        content = _md_to_html(content, autolink_urls=autolink_urls)
    nodes = html_to_ast(content)
    return ast_to_requests(nodes, start_index)


def _html_to_doc_requests(
    html_content: str, start_index: int = 1
) -> tuple[list[dict], list[Table]]:
    return _to_doc_requests(html_content, "html", start_index)


_FAILED_INSERT_IMAGE_INDEX_RE = re.compile(r"requests\[(\d+)\]\.insertInlineImage")


def _failed_insert_image_request_index(error: HttpError) -> int | None:
    """Extract the failing request's index from a batchUpdate HttpError whose
    message names an insertInlineImage request specifically (#333) — e.g.
    'Invalid requests[28].insertInlineImage: There was a problem retrieving the
    image...' (confirmed live via TC-DOC102 Case 8's deliberately unreachable
    URL). Returns None for any other error shape, so the caller re-raises
    instead of misinterpreting an unrelated failure as an image-fetch problem.
    Searches str(error) rather than error.content/error.reason — HttpError's
    own __str__ is what was confirmed live to carry this exact text; matching
    against the raw (bytes, JSON-shaped) content directly would need its own
    separate live confirmation this change doesn't have.
    """
    match = _FAILED_INSERT_IMAGE_INDEX_RE.search(str(error))
    return int(match.group(1)) if match else None


async def _resolve_image_source(
    drive_service, src: str, target_folder_id: str | None, auto_downscale: bool = False
) -> dict[str, Any]:
    """Resolve an Image.src (#333) to a fetchable URI for insertInlineImage.

    Three source kinds:
      - a public http(s) URL: used as-is — no upload, no share, nothing to revoke, and
        (per #400's scope boundary — see docs/decisions/decision-pillow-image-
        dependency.md) no size pre-validation either, since that would mean fetching
        arbitrary external content just to check it.
      - "drive:<file_id>": an already-uploaded Drive file, shared anyone:reader — the
        same requirement a fresh local upload needs below, since the Docs backend
        fetches inline images as an anonymous HTTP request regardless of the caller's
        own access (confirmed live in #332's insert_local_images).
      - anything else: treated as a local filesystem path, uploaded to Drive first,
        then shared the same way as the drive: case.

    The drive: and local-path kinds are both checked against Google Docs' ~25-
    megapixel and ~50MB inline-image limits (#400, #562) before ever being embedded —
    a drive: file's dimensions and size come straight from Drive's own metadata (no
    download needed); a local file's are read directly off disk. The default
    (auto_downscale=False) returns {"error": ...} naming the limit and the image's
    actual size, before any
    upload/share happens. auto_downscale=True instead resizes it: a drive: source gets
    a new " (resized)" copy created alongside the original (left untouched); a
    local-path source uploads the resized bytes directly instead of the original file.

    Returns {"uri": ...} for an http(s) source, or {"uri": ..., "file_id": ...,
    "permission_id": ...} for a drive:/local source — the permission_id is the
    just-granted anyone:reader permission, for the caller to revoke once the doc edit
    that actually embeds this image has succeeded (revoking any earlier would break the
    embed, since Docs fetches the image at insertion time, not upload time). Returns
    {"error": ...} on any failure.
    """
    if src.startswith("http://") or src.startswith("https://"):
        return {"uri": src}

    if src.startswith("drive:"):
        file_id = src[len("drive:") :]
        if not file_id:
            return {"error": "'drive:' reference has no file ID"}

        try:
            drive_metadata = await execute_in_thread(
                drive_service.files()
                .get(
                    fileId=file_id,
                    fields="name,parents,imageMediaMetadata,size",
                    supportsAllDrives=True,
                )
                .execute,
                drive_service,
            )
        except Exception as e:
            return {"error": f"failed to get Drive file metadata: {e}"}

        size_error = check_drive_image_metadata(drive_metadata)
        if size_error is not None:
            if not auto_downscale:
                return size_error
            parents = drive_metadata.get("parents") or []
            return await downscale_drive_file(
                drive_service,
                file_id,
                name=drive_metadata.get("name", file_id),
                parent_folder_id=parents[0] if parents else target_folder_id,
            )
    else:
        if not Path(src).is_file():
            return {"error": f"No file found at {src!r}"}
        if not target_folder_id:
            return {
                "error": "folder_id is required to upload a local image "
                "(no server default folder configured)"
            }

        try:
            data = await asyncio.to_thread(Path(src).read_bytes)
        except Exception as e:
            return {"error": f"failed to read local file: {e}"}

        size_error = check_image_bytes(data)
        if size_error is not None:
            if not auto_downscale:
                return size_error
            downscaled = downscale_image_bytes(data)
            if downscaled is None:
                return {
                    "error": f"{size_error['error']} Could not auto-downscale it "
                    "(unreadable format, or animated)."
                }
            resized_bytes, mime_type = downscaled
            return await upload_and_share_image(
                drive_service, resized_bytes, mime_type, Path(src).name, target_folder_id
            )

        upload = await _upload_local_file(
            drive_service, src, target_folder_id, skip_if_exists=False
        )
        if "error" in upload:
            return {"error": upload["error"]}
        file_id = upload["fileId"]

    try:
        perm = await execute_in_thread(
            drive_service.permissions()
            .create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                supportsAllDrives=True,
                fields="id",
            )
            .execute,
            drive_service,
        )
        metadata = await execute_in_thread(
            drive_service.files()
            .get(fileId=file_id, fields="webContentLink", supportsAllDrives=True)
            .execute,
            drive_service,
        )
    except Exception as e:
        return {"error": f"sharing failed: {e}"}

    uri = metadata.get("webContentLink")
    if not uri:
        return {"error": f"file {file_id} shared but Drive returned no webContentLink"}

    return {"uri": uri, "file_id": file_id, "permission_id": perm.get("id")}


async def _replace_doc_content(
    docs_service,
    drive_service,
    doc_cache,
    folder_id: str | None,
    doc_id: str,
    content: str,
    content_format: str,
    autolink_urls: bool,
    revoke_sharing: bool,
    auto_downscale: bool,
) -> dict[str, Any]:
    """Shared body for write_doc_content / update_doc_from_file (#341): clears an
    existing doc's content, then replaces it via _apply_doc_content. Extracted so
    the clear-then-insert mechanism (including the same-batch insertText
    style-inheritance quirk below) has exactly one implementation instead of two
    copies that could drift out of sync.
    """
    doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id).execute,
        docs_service,
    )
    body_content = doc.get("body", {}).get("content", [])
    end_index = body_content[-1].get("endIndex", 2) if body_content else 2

    clear_requests = []
    if end_index > 2:
        # The document's final paragraph mark can't be deleted by the Docs API (only
        # everything before it), so an explicit textStyle override left there by prior
        # content — e.g. the font_size:1 collapse applied to a blank paragraph before a
        # table, see _build_blank_para_before_table_collapses in emitter.py — would
        # otherwise survive this "clear" and can leak into newly-inserted content below.
        # Reset it before deleting, while its original index range is still valid.
        clear_requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": end_index - 1, "endIndex": end_index},
                    "textStyle": {},
                    "fields": "*",
                }
            }
        )
        clear_requests.append(
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}
        )
        # Sent as its own batchUpdate, not combined with the insert below: live testing
        # showed the Docs API resolves a same-batch insertText's inherited formatting
        # from a pre-batch snapshot, so contamination survived even after the clear
        # request above ran earlier in that same batch. A separate call forces the
        # insert to see the already-cleared document state.
        await execute_in_thread(
            docs_service.documents()
            .batchUpdate(documentId=doc_id, body={"requests": clear_requests})
            .execute,
            docs_service,
        )

    image_outcomes = await _apply_doc_content(
        docs_service,
        drive_service,
        doc_id,
        content,
        content_format,
        autolink_urls,
        folder_id,
        revoke_sharing,
        auto_downscale,
    )

    metadata = await execute_in_thread(
        drive_service.files()
        .get(fileId=doc_id, fields="webViewLink", supportsAllDrives=True)
        .execute,
        drive_service,
    )

    doc_cache.mark_dirty(doc_id)
    logger.debug("Replaced content in doc %s", doc_id)
    result: dict[str, Any] = {"docId": doc_id, "web_link": metadata.get("webViewLink")}
    if image_outcomes is not None:
        result["images"] = image_outcomes
    return result


async def _apply_doc_content(
    docs_service,
    drive_service,
    doc_id: str,
    content: str,
    content_format: str,
    autolink_urls: bool,
    target_folder_id: str | None,
    revoke_sharing: bool,
    auto_downscale: bool = False,
) -> list[dict[str, Any]] | None:
    """Shared content-insertion body for create_doc / create_doc_from_file /
    write_doc_content (#333): converts content to AST, resolves any markdown/HTML
    images to fetchable URIs (uploading + temporarily sharing local paths and
    drive: references, matching insert_local_images's own lifecycle), runs the
    phase-1 batchUpdate, fills tables, resolves heading anchors, and finally
    best-effort revokes each image's temporary share (revoke_sharing=True, the
    default) now that the doc edit embedding it has already succeeded — revoking
    any earlier would break the embed, since Docs fetches the image at insertion
    time, not upload time.

    auto_downscale (#400) is passed straight through to _resolve_image_source for
    each image — see that function's own docstring for the per-source-kind behavior
    and the http(s) scope boundary.

    Returns the per-image outcome list (None if the content had no images at all)
    for the caller to fold into its own response — each entry has src, plus either
    fileId + shared (+ revoke_error if a revoke attempt failed) on success, or error
    on failure. Mirrors insert_local_images's own outcome shape for consistency.
    """
    html_content = (
        _md_to_html(content, autolink_urls=autolink_urls)
        if content_format == "markdown"
        else content
    )
    nodes = html_to_ast(html_content)

    images = extract_images(nodes)
    image_outcomes: list[dict[str, Any]] = []
    # All three keyed by id(img) — the only value guaranteed unique per image.
    # Neither a resolved URI nor a computed document position is safe to key on:
    # two images can resolve to the identical URI (the same picture used twice),
    # and two images with no separating content can land at the identical
    # position (PR #502 review round 1, finding #2) — either would make a
    # same-key lookup below silently pick the wrong image's outcome entry.
    entry_by_id: dict[int, dict[str, Any]] = {}
    real_uri_by_id: dict[int, str] = {}
    # (outcome_entry, file_id, permission_id) for images successfully shared —
    # revoked only after the doc edit below actually succeeds. A retry-removed
    # image (see below) is dropped from this list before revoke runs, since it
    # was never actually placed.
    pending_revokes: dict[int, tuple[dict[str, Any], str, str]] = {}
    # ast_to_requests needs *some* URI per resolved image up front to build its
    # insertInlineImage requests — placeholders here (guaranteed unique, unlike
    # the real URIs) are swapped for the real ones below, in the same pass that
    # records which request dict came from which image.
    placeholder_uris: dict[int, str] = {}

    if images:
        # return_exceptions=True: _resolve_image_source already catches its own
        # errors, but this also guards against anything unexpected escaping it
        # without one failed image's exception aborting every other resolution.
        results = await asyncio.gather(
            *(
                _resolve_image_source(drive_service, img.src, target_folder_id, auto_downscale)
                for img in images
            ),
            return_exceptions=True,
        )
        for img, result in zip(images, results, strict=True):
            entry: dict[str, Any] = {"src": img.src}
            if isinstance(result, BaseException):
                entry["error"] = str(result)
            elif "error" in result:
                entry["error"] = result["error"]
            else:
                img_id = id(img)
                entry_by_id[img_id] = entry
                real_uri_by_id[img_id] = result["uri"]
                placeholder_uris[img_id] = f"urn:mcp-gee-sweet:pending-image:{img_id}"
                file_id = result.get("file_id")
                permission_id = result.get("permission_id")
                if file_id:
                    entry["fileId"] = file_id
                if file_id and permission_id:
                    entry["shared"] = True
                    pending_revokes[img_id] = (entry, file_id, permission_id)
            image_outcomes.append(entry)

    content_requests, tables = ast_to_requests(nodes, start_index=1, image_uris=placeholder_uris)

    # Swap each request's placeholder URI for the real one, recording which
    # image produced that exact request *object* (by its own id(), stable
    # across the `list(content_requests)` shallow copy below) so the retry
    # loop can trace a failure back to the right image without relying on URI
    # or position, both of which two images can share (see the comment above).
    placeholder_to_img_id = {
        placeholder: img_id for img_id, placeholder in placeholder_uris.items()
    }
    request_id_to_img_id: dict[int, int] = {}
    for req in content_requests:
        inline = req.get("insertInlineImage")
        if inline is None:
            continue
        img_id = placeholder_to_img_id.get(inline["uri"])
        if img_id is not None:
            request_id_to_img_id[id(req)] = img_id
            inline["uri"] = real_uri_by_id[img_id]

    if content_requests:
        # A resolved image's URI is only proven *reachable to us*, not necessarily
        # fetchable by Google's own (unauthenticated, separate-network-path)
        # image-fetching service at insertion time — confirmed live (#333 QA,
        # TC-DOC102 Case 8's deliberately unreachable URL): a single bad
        # insertInlineImage request makes the Docs API reject the *entire*
        # batchUpdate, silently losing every other request in the same call
        # (text, styles, tables, and every other image) even though only one
        # request was actually invalid. Since a rejected batchUpdate executes
        # nothing at all, the remaining requests' positions are untouched by a
        # failed attempt — so a bad request can simply be stripped and the
        # exact same list retried, with no position recomputation needed.
        # Google's own error message gives the failing request's index
        # directly ("Invalid requests[N].insertInlineImage: ..."), which is
        # what makes this retry loop possible without re-deriving that index
        # some other way.
        remaining_requests = list(content_requests)
        while True:
            try:
                await execute_in_thread(
                    docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": remaining_requests})
                    .execute,
                    docs_service,
                )
                break
            except HttpError as e:
                bad_index = _failed_insert_image_request_index(e)
                if bad_index is None or bad_index >= len(remaining_requests):
                    raise
                bad_request = remaining_requests.pop(bad_index)
                img_id = request_id_to_img_id.get(id(bad_request))
                entry = entry_by_id.get(img_id) if img_id is not None else None
                if entry is not None:
                    # fileId/shared are left as-is: a local-path/drive: source was
                    # genuinely uploaded and shared even though embedding it
                    # failed, so that's still real information for the caller —
                    # and it still goes through the normal revoke_sharing-
                    # respecting cleanup below rather than being silently
                    # orphaned. An https:// source never had either field set — and
                    # is the one source kind #400's pre-validation doesn't cover, so
                    # this is its only chance to learn the size-limit cause at all.
                    entry["error"] = f"doc edit failed: {rewrite_too_large_error(str(e))}"
        content_requests = remaining_requests
    await fill_tables(docs_service, doc_id, tables)
    if _has_pending_anchor_links(content_requests, tables):
        await _resolve_heading_anchors(docs_service, doc_id)

    if pending_revokes and revoke_sharing:

        async def _revoke(entry: dict[str, Any], file_id: str, permission_id: str) -> None:
            try:
                await execute_in_thread(
                    drive_service.permissions()
                    .delete(fileId=file_id, permissionId=permission_id, supportsAllDrives=True)
                    .execute,
                    drive_service,
                )
                entry["shared"] = False
            except Exception as e:
                entry["revoke_error"] = str(e)

        # return_exceptions=True: _revoke already catches its own errors, same
        # rationale as the resolution gather above.
        await asyncio.gather(
            *(
                _revoke(entry, file_id, permission_id)
                for entry, file_id, permission_id in pending_revokes.values()
            ),
            return_exceptions=True,
        )

    return image_outcomes or None


def _table_has_pending_anchor_link(table: Table) -> bool:
    """True if any cell in `table` (recursing into nested tables) carries a
    Run with a same-document '#slug' link_url."""
    for row in table.rows:
        for cell in row.cells:
            for child in cell.children:
                if isinstance(child, Run):
                    if child.link_url and child.link_url.startswith("#"):
                        return True
                elif isinstance(child, Table) and _table_has_pending_anchor_link(child):
                    return True
    return False


def _has_pending_anchor_links(requests: list[dict], tables: list[Table]) -> bool:
    """True if any updateTextStyle request in `requests` sets a same-document
    '#slug' hyperlink, or any not-yet-filled table cell carries one — the
    leftover shape a converted GitHub/GitLab-style heading-anchor link takes
    before resolution. Used to skip the anchor-resolution pass (an extra
    documents().get() + batchUpdate) entirely for the common case of content
    with no such links. `tables` must be checked separately from `requests`:
    fill_tables() builds and executes its own requests for table cell content
    after this function is called, so a table-only anchor link is otherwise
    invisible to this guard."""
    if any(
        req.get("updateTextStyle", {})
        .get("textStyle", {})
        .get("link", {})
        .get("url", "")
        .startswith("#")
        for req in requests
    ):
        return True
    return any(_table_has_pending_anchor_link(t) for t in tables)


def _walk_headings_and_anchor_runs(
    content: list[dict[str, Any]],
) -> tuple[list[tuple[str, str]], list[tuple[str, int, int]]]:
    """Recursively walk document body content, including table cells,
    collecting (heading_text, heading_id) pairs and (anchor_url, start, end)
    runs for any run whose link_url starts with '#'.

    Mirrors _collect_doc_paragraphs's two correctness properties: it recurses
    into table cells (a heading or an anchor link living inside a table cell
    is otherwise invisible), and it carries the running offset forward when a
    ParagraphElement's own startIndex is absent rather than dropping that
    element — the Docs API omits startIndex on a document's very first
    element (observed, not merely a defensive guess; see
    _collect_doc_paragraphs's own docstring for the same note)."""
    headings: list[tuple[str, str]] = []
    anchor_runs: list[tuple[str, int, int]] = []

    for elem in content:
        if "paragraph" in elem:
            para = elem["paragraph"]
            pstyle = para.get("paragraphStyle", {})
            is_heading = pstyle.get("namedStyleType", "NORMAL_TEXT") != "NORMAL_TEXT"
            heading_id = pstyle.get("headingId")

            offset = elem.get("startIndex", 1)
            text_parts: list[str] = []
            for pe in para.get("elements", []):
                start = pe.get("startIndex")
                if start is not None:
                    offset = start
                run_start = offset
                tr = pe.get("textRun")
                if tr and tr.get("content"):
                    run_text = tr["content"]
                    text_parts.append(run_text)
                    for ch in run_text:
                        offset += utf16_len(ch)
                    link_url = tr.get("textStyle", {}).get("link", {}).get("url", "")
                    if link_url.startswith("#"):
                        anchor_runs.append((link_url, run_start, offset))
                else:
                    end = pe.get("endIndex")
                    if end is not None:
                        offset = end

            if is_heading and heading_id:
                headings.append(("".join(text_parts).strip(), heading_id))
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    sub_headings, sub_anchor_runs = _walk_headings_and_anchor_runs(
                        cell.get("content", [])
                    )
                    headings.extend(sub_headings)
                    anchor_runs.extend(sub_anchor_runs)

    return headings, anchor_runs


async def _resolve_heading_anchors(docs_service, doc_id: str) -> dict[str, Any]:
    """Rewrite same-document '#slug' hyperlinks left over from markdown/HTML
    conversion (GitHub/GitLab-style heading anchors, issue #409) into working
    Docs heading-jump links, or strip them to plain text when no heading
    matches with reasonable confidence — a dead-looking link is bad, but a
    link silently pointing at the wrong section is worse.

    Runs as a second pass after the doc's content already exists: the target
    heading's headingId is generated server-side and isn't knowable until
    the heading paragraph has actually been created. Returns a summary dict;
    callers only need this for QA/debugging, not error handling — matched
    and unmatched links are both handled here, nothing propagates as an error.
    """
    doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id).execute,
        docs_service,
    )

    heading_pairs, anchor_runs = _walk_headings_and_anchor_runs(
        doc.get("body", {}).get("content", [])
    )
    heading_texts = [text for text, _ in heading_pairs]
    heading_ids = [heading_id for _, heading_id in heading_pairs]

    if not anchor_runs:
        return {"resolved": [], "stripped": []}

    resolved: list[dict[str, str]] = []
    stripped: list[str] = []
    requests: list[dict[str, Any]] = []
    for anchor, start, end in anchor_runs:
        match_idx = resolve_heading_anchor(anchor, heading_texts)
        if match_idx is not None:
            heading_url = (
                f"https://docs.google.com/document/d/{doc_id}"
                f"/edit?tab=t.0#heading={heading_ids[match_idx]}"
            )
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"link": {"url": heading_url}},
                        "fields": "link",
                    }
                }
            )
            resolved.append({"anchor": anchor, "heading": heading_texts[match_idx]})
        else:
            # Omit the "link" key while still naming it in the field mask — the
            # correct way to reset a nested message field to its default (no
            # link) per Docs API fields-mask semantics; see style.py's identical
            # #408 fix for why textStyle.link = {} is rejected outright.
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {},
                        "fields": "link",
                    }
                }
            )
            stripped.append(anchor)

    await execute_in_thread(
        docs_service.documents()
        .batchUpdate(documentId=doc_id, body={"requests": requests})
        .execute,
        docs_service,
    )

    return {"resolved": resolved, "stripped": stripped}


def register(tool):
    @tool(annotations=ToolAnnotations(title="Create Document", destructiveHint=True))
    async def create_doc(
        title: str,
        content: str | None = None,
        folder_id: str | None = None,
        content_format: str = "html",
        autolink_urls: bool = True,
        revoke_sharing: bool = True,
        auto_downscale: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new Google Doc, optionally with initial content.

        Content is interpreted as HTML by default. Pass content_format='markdown' to supply
        Markdown instead (headings, bold, italic, lists, links, tables, fenced code blocks,
        task list items, and images are all supported). Tables are appended after all
        paragraph content. Nested tables are not supported.

        Images: a markdown "![alt](src)" (or an HTML <img src=...>) is embedded inline.
        `src` may be a local filesystem path (uploaded to Drive automatically), a
        "drive:<file_id>" reference to an already-uploaded file, or a public http(s) URL
        (used directly). A local-path or drive: image is temporarily shared anyone-with-
        link/reader — required, since the Docs backend fetches inline images as an
        anonymous HTTP request — then, by default, that share is revoked again once the
        image is actually embedded (revoke_sharing=False leaves it shared instead; see
        insert_local_images for the same tradeoff). Table-cell images are not yet
        supported and are silently dropped. Per-image outcomes (including any resolution
        or sharing failure) are returned under "images" when the content had any.

        A local-path or drive: image over Google Docs' ~25-megapixel inline-image limit
        fails with a clear error naming the limit and its actual size, before any
        upload/share happens — set auto_downscale=True to resize it instead (see that
        arg's own docs). A public http(s) image can't be pre-validated this way; an
        oversized one instead fails at the embed step with a rewritten error explaining
        the likely cause.

        Args:
            title: The title of the new document
            content: Optional content for the document body
            folder_id: Optional Google Drive folder ID where the document should be created.
                      If not provided, creates in the root of My Drive.
            content_format: 'html' (default) or 'markdown'
            autolink_urls: When content_format='markdown', whether a bare http(s) URL (not
                already wrapped in a Markdown link or angle brackets) becomes a real
                hyperlink (default True). Set False to leave bare URLs as plain text; to
                suppress just one URL instead of the whole call, wrap it in backticks.
            revoke_sharing: Whether a local-path/drive: image's temporary anyone:reader
                share is revoked again after it's embedded (default True).
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False). A drive: source gets a new " (resized)"
                copy created alongside the original (left untouched); a local-path
                source uploads the resized bytes directly instead of the original file.
                No effect on a public http(s) image source (see above).

        Returns:
            Information about the newly created document including its ID and web link.
            Includes "images" (per-image outcomes) when content contained any images.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Workaround for service accounts: create the file manually in Drive, then use
            write_doc_content to populate it. Check server://auth-status for your current
            auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        docs_service = lc.docs_service
        target_folder_id = folder_id or lc.folder_id

        file_body: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            doc = await execute_in_thread(
                drive_service.files()
                .create(
                    supportsAllDrives=True,
                    body=file_body,
                    fields="id, name, parents, webViewLink",
                )
                .execute,
                drive_service,
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug(
            "Doc created with ID: %s%s",
            doc_id,
            f" in folder {target_folder_id}" if target_folder_id else " in root",
        )

        image_outcomes = None
        if content:
            image_outcomes = await _apply_doc_content(
                docs_service,
                drive_service,
                doc_id,
                content,
                content_format,
                autolink_urls,
                target_folder_id,
                revoke_sharing,
                auto_downscale,
            )

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        result: dict[str, Any] = {
            "docId": doc_id,
            "title": doc.get("name", title),
            "folder": parents[0] if parents else "root",
            "web_link": doc.get("webViewLink"),
        }
        if image_outcomes is not None:
            result["images"] = image_outcomes
        return result

    @tool(annotations=ToolAnnotations(title="Create Document from File", destructiveHint=True))
    async def create_doc_from_file(
        local_path: str,
        title: str | None = None,
        folder_id: str | None = None,
        autolink_urls: bool = True,
        revoke_sharing: bool = True,
        auto_downscale: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a Google Doc from a local .md or .html file.

        The file format is inferred from the extension: .md files are parsed as
        Markdown, .html / .htm files as HTML. The document title defaults to the
        filename without extension if not supplied.

        Images referenced from the file (markdown "![alt](src)" or HTML <img src=...>)
        are embedded inline the same way create_doc's own content_format='markdown'
        path handles them — see that tool's docstring for the src conventions, the
        revoke_sharing tradeoff, and the auto_downscale size-limit behavior.

        For .md files specifically, upload_local_file(convert=True) is a Drive-native
        alternative: one API call using Drive's own import converter, versus this
        tool's local parse-and-rebuild pipeline. This tool supports more Markdown
        features (tables, nested lists, task items, fenced code blocks, inline
        images) at the cost of more Docs API calls; Drive's importer is a single
        call but its fidelity is whatever Drive's own converter does.

        Args:
            local_path: Absolute or relative path to the local file.
            title: Document title. Defaults to the filename stem.
            folder_id: Optional Google Drive folder ID. Defaults to server default folder.
            autolink_urls: For .md files, whether a bare http(s) URL becomes a real
                hyperlink (default True). Set False to leave bare URLs as plain text;
                to suppress just one URL, wrap it in backticks instead. No effect on
                .html files.
            revoke_sharing: Whether a local-path/drive: image's temporary anyone:reader
                share is revoked again after it's embedded (default True).
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False) — see create_doc's own docstring.

        Returns:
            Information about the newly created document including its ID and web link.
            Includes "images" (per-image outcomes) when the file contained any images.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Check server://auth-status for your current auth method.
        """
        path = Path(local_path)
        if not path.exists():
            return {"error": f"File not found: {local_path}"}

        ext = path.suffix.lower()
        if ext == ".md":
            content_format = "markdown"
        elif ext in (".html", ".htm"):
            content_format = "html"
        else:
            return {"error": f"Unsupported file extension '{ext}'. Use .md or .html/.htm"}

        content = path.read_text(encoding="utf-8")
        doc_title = title or path.stem

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        docs_service = lc.docs_service
        target_folder_id = folder_id or lc.folder_id

        file_body: dict[str, Any] = {
            "name": doc_title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            doc = await execute_in_thread(
                drive_service.files()
                .create(
                    supportsAllDrives=True,
                    body=file_body,
                    fields="id, name, parents, webViewLink",
                )
                .execute,
                drive_service,
            )
        except HttpError as e:
            if e.resp.status == 403 and b"storageQuotaExceeded" in (e.content or b""):
                return {"error": _SA_QUOTA_ERROR}
            raise

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug("Doc created from file %s with ID: %s", local_path, doc_id)

        image_outcomes = None
        if content:
            image_outcomes = await _apply_doc_content(
                docs_service,
                drive_service,
                doc_id,
                content,
                content_format,
                autolink_urls,
                target_folder_id,
                revoke_sharing,
                auto_downscale,
            )

        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        result: dict[str, Any] = {
            "docId": doc_id,
            "title": doc.get("name", doc_title),
            "folder": parents[0] if parents else "root",
            "web_link": doc.get("webViewLink"),
        }
        if image_outcomes is not None:
            result["images"] = image_outcomes
        return result

    @tool(annotations=ToolAnnotations(title="Get Document Content", readOnlyHint=True))
    async def get_doc_content(
        file_id: str, local_path: str | None = None, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Get the plain text content of a Google Doc.

        Args:
            file_id: The Google Drive file ID of the document.
            local_path: Optional local filesystem path (file or directory) to write the
                result to instead of returning it inline. Bypasses the response-size cap.
                Same caveat as download_file/download_folder: this path is resolved on the
                *server's* filesystem, not the caller's.

        Returns:
            Dictionary with the document's text content and metadata. Results are
            cached; call refresh_cache(doc_id=file_id) to invalidate, or
            refresh_cache() to clear all caches. Raises ValueError if the response
            exceeds a safety cap (see MAX_TOOL_RESPONSE_CHARS in docs/configuration.md
            for the configured default) and local_path is not set. If local_path is set, returns
            {local_path, id, bytes_written} instead.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        doc_cache = lc.doc_cache

        # When validation is on, fetch full metadata (not just modifiedTime) up
        # front: it's the same call cost as the lightweight helper, and reusing it
        # on a cache miss avoids a second, redundant files().get() for the same
        # fields.
        metadata = None
        current_mtime = None
        if CACHE_VALIDATE_MODIFIED_TIME:
            metadata = await execute_in_thread(
                drive_service.files()
                .get(
                    fileId=file_id,
                    fields="id, name, modifiedTime, webViewLink",
                    supportsAllDrives=True,
                )
                .execute,
                drive_service,
            )
            current_mtime = metadata.get("modifiedTime")

        result = doc_cache.get(file_id, current_modified_time=current_mtime)
        if result is None:
            if metadata is None:
                metadata = await execute_in_thread(
                    drive_service.files()
                    .get(
                        fileId=file_id,
                        fields="id, name, modifiedTime, webViewLink",
                        supportsAllDrives=True,
                    )
                    .execute,
                    drive_service,
                )

            content = await execute_in_thread(
                drive_service.files().export(fileId=file_id, mimeType="text/plain").execute,
                drive_service,
            )

            result = {
                "id": metadata["id"],
                "name": metadata["name"],
                "modified_time": metadata.get("modifiedTime"),
                "web_link": metadata.get("webViewLink"),
                "content": content.decode("utf-8") if isinstance(content, bytes) else content,
            }
            doc_cache.store(file_id, result)

        if local_path:
            return await write_capped_result_to_disk(
                result,
                local_path,
                default_filename=f"{file_id}_content.json",
                manifest_extra={"id": file_id},
            )

        enforce_response_size_cap(result, tool_name="get_doc_content")
        return result

    @tool(annotations=ToolAnnotations(title="Write Document Content", destructiveHint=True))
    async def write_doc_content(
        doc_id: str,
        content: str,
        content_format: str = "html",
        autolink_urls: bool = True,
        revoke_sharing: bool = True,
        auto_downscale: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace the full content of an existing Google Doc.

        Content is interpreted as HTML by default. Pass content_format='markdown' to supply
        Markdown instead. Headings, paragraphs, lists, links, tables, fenced code blocks,
        task list items, and images are all supported. Tables are appended after all
        paragraph content. Use this to populate a doc created manually in Drive (bypassing
        service account storage quota limits).

        Images are embedded inline the same way create_doc's own content_format='markdown'
        path handles them — see that tool's docstring for the src conventions, the
        revoke_sharing tradeoff, and the auto_downscale size-limit behavior. A
        local-path image is uploaded into the server's default folder (no per-call
        override here — pass a "drive:<file_id>" or public URL src instead if you need
        control over where the image itself lives).

        Args:
            doc_id: The Google Doc file ID.
            content: Content to write into the document body.
            content_format: 'html' (default) or 'markdown'
            autolink_urls: When content_format='markdown', whether a bare http(s) URL
                becomes a real hyperlink (default True). Set False to leave bare URLs as
                plain text; to suppress just one URL, wrap it in backticks instead.
            revoke_sharing: Whether a local-path/drive: image's temporary anyone:reader
                share is revoked again after it's embedded (default True).
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False) — see create_doc's own docstring.

        Returns:
            Confirmation with the document ID and web link. Includes "images" (per-image
            outcomes) when content contained any images.
        """
        lc = ctx.request_context.lifespan_context
        return await _replace_doc_content(
            lc.docs_service,
            lc.drive_service,
            lc.doc_cache,
            lc.folder_id,
            doc_id,
            content,
            content_format,
            autolink_urls,
            revoke_sharing,
            auto_downscale,
        )

    @tool(annotations=ToolAnnotations(title="Update Document from File", destructiveHint=True))
    async def update_doc_from_file(
        doc_id: str,
        local_path: str,
        content_format: str | None = None,
        autolink_urls: bool = True,
        revoke_sharing: bool = True,
        auto_downscale: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace an existing Google Doc's content in place from a local .md or .html file.

        Reads local_path server-side the same way create_doc_from_file does (file
        format inferred from extension, or pass content_format to override), then
        replaces the doc's content the same way write_doc_content does — preserving
        the doc's ID, URL, permissions, and Drive location. Unlike calling
        create_doc_from_file again, this never mints a duplicate Doc, and unlike
        write_doc_content, the caller never has to read the file into its own
        context — the server reads it directly.

        Images referenced from the file (markdown "![alt](src)" or HTML <img src=...>)
        are embedded inline the same way create_doc's own content_format='markdown'
        path handles them — see that tool's docstring for the src conventions, the
        revoke_sharing tradeoff, and the auto_downscale size-limit behavior.

        Args:
            doc_id: The Google Doc file ID to update in place.
            local_path: Absolute or relative path to the local file.
            content_format: 'markdown' or 'html'. Defaults to inferring from
                local_path's extension (.md -> markdown, .html/.htm -> html); pass
                explicitly to override the extension-based guess.
            autolink_urls: For markdown content, whether a bare http(s) URL becomes a
                real hyperlink (default True). Set False to leave bare URLs as plain
                text; to suppress just one URL, wrap it in backticks instead. No
                effect on HTML content.
            revoke_sharing: Whether a local-path/drive: image's temporary anyone:reader
                share is revoked again after it's embedded (default True).
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False) — see create_doc's own docstring.

        Returns:
            Confirmation with the document ID and web link. Includes "images" (per-image
            outcomes) when the file contained any images.
        """
        path = Path(local_path)
        if not path.exists():
            return {"error": f"File not found: {local_path}"}

        if content_format is None:
            ext = path.suffix.lower()
            if ext == ".md":
                content_format = "markdown"
            elif ext in (".html", ".htm"):
                content_format = "html"
            else:
                return {
                    "error": (
                        f"Unsupported file extension '{ext}'. Use .md or .html/.htm, "
                        "or pass content_format explicitly."
                    )
                }

        content = path.read_text(encoding="utf-8")

        lc = ctx.request_context.lifespan_context
        return await _replace_doc_content(
            lc.docs_service,
            lc.drive_service,
            lc.doc_cache,
            lc.folder_id,
            doc_id,
            content,
            content_format,
            autolink_urls,
            revoke_sharing,
            auto_downscale,
        )

    @tool(annotations=ToolAnnotations(title="Get Document Structure", readOnlyHint=True))
    async def get_doc_structure(doc_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Return the full structural map of a Google Doc body with element indices.

        Every batchUpdate operation (insert, delete, style, table) requires knowing
        the startIndex and endIndex of the target element. This tool exposes those
        indices alongside paragraph styles, text run formatting, and table cell positions.

        Args:
            doc_id: The Google Doc file ID.

        Returns:
            Dictionary with docId, title, and an elements list. Each element has:
            - type: "paragraph" | "table" | "sectionBreak" | "tableOfContents"
            - startIndex, endIndex
            Paragraphs also include namedStyleType, text, headingId (Google's internal
            ID for this heading, present only when namedStyleType is HEADING_1..6 —
            e.g. "h.abc123"; null otherwise), a runs list (each run has text,
            bold, italic, underline, strikethrough, font_size, link_url), and
            bullet (null for a non-list paragraph; otherwise {listId,
            nestingLevel} — nestingLevel is 0 for a top-level list item, absent
            from the raw API response in that case, normalized to 0 here so
            every list paragraph reports a level). Use this to detect a
            markdown-to-Doc conversion that flattened an intended nested list —
            sibling paragraphs that should differ in depth but share
            the same nestingLevel — then fix it with create_paragraph_bullets.
            Tables include rows, columns, and a cells list (each cell has row, col,
            startIndex, endIndex, paragraphStartIndex, text).

        Note:
            headingId is the piece needed to build a working in-doc jump link: set
            link_url via style_doc_range to
            f"https://docs.google.com/document/d/{doc_id}/edit?tab=t.0#heading={heading_id}"
            — an ordinary URL, no special Link-object field required. Confirmed live
            2026-07-24 (issue #409).
        """
        lc = ctx.request_context.lifespan_context
        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        elements = []
        for elem in doc.get("body", {}).get("content", []):
            if "paragraph" in elem:
                para = elem["paragraph"]
                pstyle = para.get("paragraphStyle", {})
                named_style = pstyle.get("namedStyleType", "NORMAL_TEXT")
                # The API only ever populates headingId for a paragraph the Docs UI
                # would offer as a "Headings & bookmarks" link target (HEADING_1..6,
                # and TITLE/SUBTITLE) — no client-side filtering needed here.
                heading_id = pstyle.get("headingId")
                bullet = para.get("bullet")
                bullet_info = (
                    {
                        "listId": bullet.get("listId"),
                        "nestingLevel": bullet.get("nestingLevel", 0),
                    }
                    if bullet
                    else None
                )
                runs = []
                for pe in para.get("elements", []):
                    tr = pe.get("textRun")
                    if not tr:
                        continue
                    ts = tr.get("textStyle", {})
                    runs.append(
                        {
                            "text": tr.get("content", ""),
                            "bold": ts.get("bold"),
                            "italic": ts.get("italic"),
                            "underline": ts.get("underline"),
                            "strikethrough": ts.get("strikethrough"),
                            "font_size": ts["fontSize"].get("magnitude")
                            if "fontSize" in ts
                            else None,
                            "link_url": ts["link"].get("url") if "link" in ts else None,
                        }
                    )
                elements.append(
                    {
                        "type": "paragraph",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                        "namedStyleType": named_style,
                        "headingId": heading_id,
                        "bullet": bullet_info,
                        "text": "".join(r["text"] for r in runs),
                        "runs": runs,
                    }
                )
            elif "table" in elem:
                table = elem["table"]
                cells = []
                for r, row in enumerate(table.get("tableRows", [])):
                    for c, cell in enumerate(row.get("tableCells", [])):
                        content = cell.get("content", [])
                        para_start = content[0].get("startIndex") if content else None
                        cell_text = "".join(
                            pe.get("textRun", {}).get("content", "")
                            for ce in content
                            if "paragraph" in ce
                            for pe in ce["paragraph"].get("elements", [])
                        )
                        cells.append(
                            {
                                "row": r,
                                "col": c,
                                "startIndex": cell.get("startIndex"),
                                "endIndex": cell.get("endIndex"),
                                "paragraphStartIndex": para_start,
                                "text": cell_text.strip(),
                            }
                        )
                elements.append(
                    {
                        "type": "table",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                        "rows": table.get("rows", 0),
                        "columns": table.get("columns", 0),
                        "cells": cells,
                    }
                )
            elif "sectionBreak" in elem:
                elements.append(
                    {
                        "type": "sectionBreak",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                    }
                )
            elif "tableOfContents" in elem:
                elements.append(
                    {
                        "type": "tableOfContents",
                        "startIndex": elem.get("startIndex", 0),
                        "endIndex": elem.get("endIndex", 0),
                    }
                )

        logger.debug("get_doc_structure: %d elements in doc %s", len(elements), doc_id)
        return {
            "docId": doc.get("documentId"),
            "title": doc.get("title"),
            "elements": elements,
        }

    @tool(annotations=ToolAnnotations(title="Find in Document", readOnlyHint=True))
    async def find_in_doc(
        doc_id: str,
        query: str,
        regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 50,
        local_path: str | None = None,
        ctx: Context = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Search a Google Doc's text and return match locations as document
        character offsets.

        Matches feed directly into style_doc_range's ranges — e.g. to link up
        bare URLs already sitting in a doc: find_in_doc(doc_id,
        query=r'https?://[^\\s<>"]+(?<![.,;:!?)])', regex=True), then
        style_doc_range with link_url per match. The trailing negative
        lookbehind keeps a URL followed by sentence punctuation (or an
        unmatched closing paren) from swallowing it into the link.

        Args:
            doc_id: The Google Doc file ID.
            query: Text to search for. Interpreted literally by default; pass
                regex=True to treat it as a Python regular expression.
            regex: Whether query is a regular expression (default False).
            case_sensitive: Whether the search is case-sensitive (default False).
            max_results: Maximum number of matches to return (default 50).
            local_path: Optional local filesystem path (file or directory) to write the
                result to instead of returning it inline. Bypasses the response-size cap.
                Same caveat as download_file/download_folder: this path is resolved on the
                *server's* filesystem, not the caller's.

        Returns:
            List of matches, each with start_index/end_index (document offsets
            usable directly as a style_doc_range range), matched_text, and
            context (the containing paragraph's full text). Searches paragraph
            text in the document body, including table cells; headers,
            footers, and footnotes are not searched. A zero-length regex match
            (e.g. "x*" with no "x" present) is skipped. Returns {"error": ...}
            if query is an invalid regex, or if the Docs API call itself fails
            (e.g. doc_id doesn't exist). max_results bounds match count, not
            response size — matched context can still be large. Raises
            ValueError if the response exceeds a safety cap (see
            MAX_TOOL_RESPONSE_CHARS in docs/configuration.md for the configured
            default) and local_path is not set — lower max_results, or pass local_path. If
            local_path is set, returns {local_path, doc_id, query, match_count,
            bytes_written} instead.
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags) if regex else re.compile(re.escape(query), flags)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}

        try:
            doc = await execute_in_thread(
                docs_service.documents().get(documentId=doc_id).execute,
                docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        results: list[dict[str, Any]] = []
        for para_text, para_indices in _collect_doc_paragraphs(
            doc.get("body", {}).get("content", [])
        ):
            if len(results) >= max_results:
                break
            for m in pattern.finditer(para_text):
                if len(results) >= max_results:
                    break
                start_char, end_char = m.start(), m.end()
                if start_char == end_char:
                    continue
                results.append(
                    {
                        "start_index": para_indices[start_char],
                        "end_index": para_indices[end_char - 1]
                        + utf16_len(para_text[end_char - 1]),
                        "matched_text": para_text[start_char:end_char],
                        "context": para_text.rstrip("\n"),
                    }
                )

        if local_path:
            return await write_capped_result_to_disk(
                results,
                local_path,
                default_filename="find_in_doc_results.json",
                manifest_extra={
                    "doc_id": doc_id,
                    "query": query,
                    "match_count": len(results),
                },
            )

        enforce_response_size_cap(results, tool_name="find_in_doc")
        return results
