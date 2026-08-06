import asyncio
import html as html_module
import logging
import re
import xml.etree.ElementTree as etree
from collections.abc import Iterator
from html.parser import HTMLParser
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
from .indices import utf16_len
from .style import _NAMED_STYLE_TYPES, _text_style_and_fields

logger = logging.getLogger(__name__)


def _html_to_text(html_content: str) -> str:
    """Convert HTML to plain text, preserving block-level line breaks."""
    _BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "tr", "blockquote"}

    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag == "br" or (tag in _BLOCK and self.parts and not self.parts[-1].endswith("\n")):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in _BLOCK:
                self.parts.append("\n")

        def handle_data(self, data):
            self.parts.append(data)

        def handle_entityref(self, name):
            self.parts.append(html_module.unescape(f"&{name};"))

        def handle_charref(self, name):
            self.parts.append(html_module.unescape(f"&#{name};"))

    extractor = _Extractor()
    extractor.feed(html_content)
    return "".join(extractor.parts).strip()


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
            if url[-1] in _BARE_URL_TRAILING_PUNCT:
                url = url[:-1]
            elif url[-1] == ")" and url.count("(") < url.count(")"):
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
    drive_service, src: str, target_folder_id: str | None
) -> dict[str, Any]:
    """Resolve an Image.src (#333) to a fetchable URI for insertInlineImage.

    Three source kinds:
      - a public http(s) URL: used as-is — no upload, no share, nothing to revoke.
      - "drive:<file_id>": an already-uploaded Drive file, shared anyone:reader — the
        same requirement a fresh local upload needs below, since the Docs backend
        fetches inline images as an anonymous HTTP request regardless of the caller's
        own access (confirmed live in #332's insert_local_images).
      - anything else: treated as a local filesystem path, uploaded to Drive first,
        then shared the same way as the drive: case.

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
    else:
        if not Path(src).is_file():
            return {"error": f"No file found at {src!r}"}
        if not target_folder_id:
            return {
                "error": "folder_id is required to upload a local image "
                "(no server default folder configured)"
            }
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


async def _apply_doc_content(
    docs_service,
    drive_service,
    doc_id: str,
    content: str,
    content_format: str,
    autolink_urls: bool,
    target_folder_id: str | None,
    revoke_sharing: bool,
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
            *(_resolve_image_source(drive_service, img.src, target_folder_id) for img in images),
            return_exceptions=True,
        )
        for img, result in zip(images, results):
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
                    # orphaned. An https:// source never had either field set.
                    entry["error"] = f"doc edit failed: {e}"
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


def _collect_doc_paragraphs(content: list[dict[str, Any]]) -> Iterator[tuple[str, list[int]]]:
    """Walk document body content, recursing into table cells, yielding each
    paragraph's text paired with a parallel list of document character indices
    (one per Python character in the text, in UTF-16 code units) — lets a
    match's in-paragraph span be translated back into document offsets usable
    with style_doc_range.

    A generator so a caller (e.g. find_in_doc bounding results by max_results)
    can stop pulling early without walking the rest of a large document.

    Each ParagraphElement carries its own startIndex, but the Docs API doesn't
    always populate it (observed on a document's very first element). When
    present it's trusted directly, resyncing the running offset; when absent,
    the offset just carries forward from the paragraph's own startIndex plus
    whatever's been consumed so far, so one missing field doesn't silently
    drop that element's text the way an unconditional skip would."""
    for elem in content:
        if "paragraph" in elem:
            # Google Docs body content is never index 0 — a missing startIndex
            # here only happens on the document's very first element, which
            # implicitly starts at 1 (same convention as tables.py/emitter.py).
            offset = elem.get("startIndex", 1)
            text_parts: list[str] = []
            indices: list[int] = []
            for pe in elem["paragraph"].get("elements", []):
                start = pe.get("startIndex")
                if start is not None:
                    offset = start
                tr = pe.get("textRun")
                if tr and tr.get("content"):
                    run_text = tr["content"]
                    text_parts.append(run_text)
                    for ch in run_text:
                        indices.append(offset)
                        offset += utf16_len(ch)
                else:
                    end = pe.get("endIndex")
                    if end is not None:
                        offset = end
            if text_parts:
                yield "".join(text_parts), indices
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    yield from _collect_doc_paragraphs(cell.get("content", []))


async def _create_named_range(
    docs_service, doc_cache, doc_id: str, name: str, start_index: int, end_index: int
) -> dict[str, Any]:
    """Shared implementation backing create_named_range and create_bookmark.

    Returns {"error": ...} on any API failure or a success response with no
    usable reply — never raises, matching every sibling tool in this file.
    """
    try:
        response = await execute_in_thread(
            docs_service.documents()
            .batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "createNamedRange": {
                                "name": name,
                                "range": {
                                    "startIndex": start_index,
                                    "endIndex": end_index,
                                },
                            }
                        }
                    ]
                },
            )
            .execute,
            docs_service,
        )
        replies = response.get("replies") or []
        named_range_id = (
            replies[0].get("createNamedRange", {}).get("namedRangeId") if replies else None
        )
        if not named_range_id:
            return {"error": "Docs API returned no namedRangeId for createNamedRange"}
    except Exception as e:
        return {"error": str(e)}

    doc_cache.mark_dirty(doc_id)
    return {
        "docId": doc_id,
        "namedRangeId": named_range_id,
        "name": name,
        "startIndex": start_index,
        "endIndex": end_index,
    }


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
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a Google Doc from a local .md or .html file.

        The file format is inferred from the extension: .md files are parsed as
        Markdown, .html / .htm files as HTML. The document title defaults to the
        filename without extension if not supplied.

        Images referenced from the file (markdown "![alt](src)" or HTML <img src=...>)
        are embedded inline the same way create_doc's own content_format='markdown'
        path handles them — see that tool's docstring for the src conventions and the
        revoke_sharing tradeoff.

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
            exceeds a safety cap (default 40,000 characters, set MAX_TOOL_RESPONSE_CHARS
            to change it) and local_path is not set. If local_path is set, returns
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
        path handles them — see that tool's docstring for the src conventions and the
        revoke_sharing tradeoff. A local-path image is uploaded into the server's default
        folder (no per-call override here — pass a "drive:<file_id>" or public URL src
        instead if you need control over where the image itself lives).

        Args:
            doc_id: The Google Doc file ID.
            content: Content to write into the document body.
            content_format: 'html' (default) or 'markdown'
            autolink_urls: When content_format='markdown', whether a bare http(s) URL
                becomes a real hyperlink (default True). Set False to leave bare URLs as
                plain text; to suppress just one URL, wrap it in backticks instead.
            revoke_sharing: Whether a local-path/drive: image's temporary anyone:reader
                share is revoked again after it's embedded (default True).

        Returns:
            Confirmation with the document ID and web link. Includes "images" (per-image
            outcomes) when content contained any images.
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service
        drive_service = lc.drive_service

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
            lc.folder_id,
            revoke_sharing,
        )

        metadata = await execute_in_thread(
            drive_service.files()
            .get(fileId=doc_id, fields="webViewLink", supportsAllDrives=True)
            .execute,
            drive_service,
        )

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("Wrote content to doc %s", doc_id)
        result: dict[str, Any] = {"docId": doc_id, "web_link": metadata.get("webViewLink")}
        if image_outcomes is not None:
            result["images"] = image_outcomes
        return result

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
            markdown-to-Doc conversion that flattened an intended nested list
            (#334) — sibling paragraphs that should differ in depth but share
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
            ValueError if the response exceeds a safety cap (default 40,000
            characters, set MAX_TOOL_RESPONSE_CHARS to change it) and
            local_path is not set — lower max_results, or pass local_path. If
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

    @tool(annotations=ToolAnnotations(title="Insert Document Text", destructiveHint=True))
    async def insert_doc_text(
        doc_id: str,
        insertions: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert text at one or more positions in a Google Doc.

        All indices are interpreted as positions in the document before any of
        the insertions in this call. Insertions are applied high-index-first so
        earlier indices are not shifted by later ones.

        Use get_doc_structure to obtain the correct target indices.

        Args:
            doc_id: The Google Doc file ID.
            insertions: List of insertion dicts. Required keys:
                index (int): document position to insert at.
                text (str): text to insert. "\\n" creates a new paragraph.
              Optional keys:
                segment_id (str): segmentId of the header or footer to insert into
                    (the headerId / footerId returned by create_header / create_footer).
                    Omit to insert into the document body.

        Returns:
            Confirmation with docId and count of insertions applied.
        """
        lc = ctx.request_context.lifespan_context
        if not insertions:
            return {"error": "insertions list is empty"}
        try:
            sorted_ops = sorted(insertions, key=lambda x: x["index"], reverse=True)
            requests = []
            for op in sorted_ops:
                location: dict[str, Any] = {"index": op["index"]}
                if "segment_id" in op:
                    location["segmentId"] = op["segment_id"]
                requests.append({"insertText": {"location": location, "text": op["text"]}})
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_doc_text: %d insertions in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "insertions": len(requests)}

    @tool(annotations=ToolAnnotations(title="Delete Document Range", destructiveHint=True))
    async def delete_doc_range(
        doc_id: str,
        deletions: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete one or more content ranges from a Google Doc.

        All indices are interpreted as positions in the document before any of
        the deletions in this call. Deletions are applied high-index-first so
        earlier indices are not shifted by later ones.

        Use get_doc_structure to obtain the correct start/end indices.

        Args:
            doc_id: The Google Doc file ID.
            deletions: List of {"start_index": int, "end_index": int}.
                The range [start_index, end_index) is deleted (end_index is exclusive).
                Do not include the document's final newline (last endIndex - 1).

        Returns:
            Confirmation with docId and count of deletions applied.

        Note:
            Including a paragraph's trailing paragraph mark in the deleted range
            merges that paragraph into the next one, and the merged result inherits
            the *next* paragraph's style (e.g. deleting through a NORMAL_TEXT
            paragraph's newline when the following paragraph is HEADING_1 leaves the
            surviving content styled as HEADING_1). Text inserted afterward at that
            position silently picks up the same inherited style. Follow a
            paragraph-mark-inclusive delete with an explicit updateParagraphStyle
            (style_doc_range's named_style_type, or insert_softbreak_paragraph's
            named_style_type) rather than assuming the original style survived.
        """
        lc = ctx.request_context.lifespan_context
        if not deletions:
            return {"error": "deletions list is empty"}
        try:
            sorted_ops = sorted(deletions, key=lambda x: x["start_index"], reverse=True)
            requests = [
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": op["start_index"],
                            "endIndex": op["end_index"],
                        }
                    }
                }
                for op in sorted_ops
            ]
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("delete_doc_range: %d deletions in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "deletions": len(requests)}

    @tool(annotations=ToolAnnotations(title="Create Named Range", destructiveHint=True))
    async def create_named_range(
        doc_id: str,
        name: str,
        start_index: int,
        end_index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a named range over a span of content in a Google Doc.

        A named range lets you reference a section of the document by name later
        (e.g. with ReplaceNamedRangeContentRequest via batch_update) without
        tracking raw indices yourself — the Docs API automatically shifts the
        range's bounds as content is inserted or deleted elsewhere in the doc.

        Use get_doc_structure to find start/end indices for the target span.

        Args:
            doc_id: The Google Doc file ID.
            name: Name for the range. Not required to be unique; 1-256 UTF-16 code units.
            start_index: Start of the range (inclusive).
            end_index: End of the range (exclusive).

        Returns:
            Confirmation with docId, namedRangeId, name, startIndex, endIndex.

        Note:
            Named ranges are not visible in the Docs UI and cannot be used as
            internal hyperlink targets (the Link object only supports UI-created
            bookmarks and headings, not named ranges) — they exist purely for
            programmatic reference via the API.
        """
        lc = ctx.request_context.lifespan_context
        result = await _create_named_range(
            lc.docs_service, lc.doc_cache, doc_id, name, start_index, end_index
        )
        if "error" not in result:
            logger.debug(
                "create_named_range: %r [%d, %d) in doc %s -> %s",
                name,
                start_index,
                end_index,
                doc_id,
                result["namedRangeId"],
            )
        return result

    @tool(annotations=ToolAnnotations(title="Create Bookmark", destructiveHint=True))
    async def create_bookmark(
        doc_id: str,
        name: str,
        index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a lightweight, named anchor point at a single position in a Google Doc.

        The Docs API has no dedicated bookmark-creation endpoint (Docs UI bookmarks
        can only be inserted by hand). This is a convenience wrapper around
        create_named_range that spans the single character at `index`, giving you a
        named position you can look up later without hardcoding raw indices — the
        range's bounds shift automatically as the API tracks surrounding edits.

        Use get_doc_structure to find a suitable index.

        Args:
            doc_id: The Google Doc file ID.
            name: Name for the bookmark. Not required to be unique; 1-256 UTF-16 code units.
            index: Document position to anchor at (the character at this index is
                included in the underlying named range).

        Returns:
            Confirmation with docId, namedRangeId, name, index.

        Note:
            This is not a Docs UI bookmark: it won't appear in Insert > Bookmark and
            cannot be used as an internal hyperlink target (the Link object only
            supports UI-created bookmarks and headings, not named ranges). Use
            create_named_range directly for an anchor spanning more than one character.
        """
        lc = ctx.request_context.lifespan_context
        result = await _create_named_range(
            lc.docs_service, lc.doc_cache, doc_id, name, index, index + 1
        )
        if "error" in result:
            return result
        logger.debug(
            "create_bookmark: %r at index %d in doc %s -> %s",
            name,
            index,
            doc_id,
            result["namedRangeId"],
        )
        return {
            "docId": result["docId"],
            "namedRangeId": result["namedRangeId"],
            "name": result["name"],
            "index": index,
        }

    @tool(annotations=ToolAnnotations(title="Insert Inline Image", destructiveHint=True))
    async def insert_inline_image(
        doc_id: str,
        index: int,
        uri: str | None = None,
        drive_file_id: str | None = None,
        width: float | None = None,
        height: float | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an inline image at a specific index in a Google Doc.

        Provide either uri (a publicly accessible HTTPS image URL) or drive_file_id
        (a Drive file ID for an image stored in Drive). The image is inserted at the
        given document index.

        Use get_doc_structure to find a suitable insertion index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the image should be inserted.
            uri: A publicly accessible image URI (HTTPS). Mutually exclusive with drive_file_id.
            drive_file_id: A Google Drive file ID for an image stored in Drive. The
                Docs backend fetches the image over HTTP as an anonymous request, so
                the file must be shared as anyone-with-link (e.g. via share_file with
                {"type": "anyone", "role": "reader"}) — being accessible to the
                authenticated user alone is not sufficient and fails with "There was
                a problem retrieving the image" (confirmed live 2026-07-18).
                Mutually exclusive with uri.
            width: Optional image width in points.
            height: Optional image height in points.

        Returns:
            Confirmation with docId and the insertion index.
        """
        if not uri and not drive_file_id:
            return {"error": "Provide either uri or drive_file_id"}
        if uri and drive_file_id:
            return {"error": "Provide only one of uri or drive_file_id, not both"}

        lc = ctx.request_context.lifespan_context

        if drive_file_id:
            try:
                metadata = await execute_in_thread(
                    lc.drive_service.files()
                    .get(fileId=drive_file_id, fields="webContentLink", supportsAllDrives=True)
                    .execute,
                    lc.drive_service,
                )
                uri = metadata.get("webContentLink")
                if not uri:
                    return {"error": f"Could not get download link for Drive file {drive_file_id}"}
            except Exception as e:
                return {"error": f"Failed to get Drive file metadata: {e}"}

        image_request: dict[str, Any] = {
            "insertInlineImage": {
                "location": {"index": index},
                "uri": uri,
            }
        }
        if width is not None or height is not None:
            object_size: dict[str, Any] = {}
            if width is not None:
                object_size["width"] = {"magnitude": width, "unit": "PT"}
            if height is not None:
                object_size["height"] = {"magnitude": height, "unit": "PT"}
            image_request["insertInlineImage"]["objectSize"] = object_size

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": [image_request]})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_inline_image: at index %d in doc %s", index, doc_id)
        return {"docId": doc_id, "index": index}

    @tool(annotations=ToolAnnotations(title="Insert Page Break", destructiveHint=True))
    async def insert_page_break(
        doc_id: str,
        index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an explicit page break at a specific index in a Google Doc.

        Use get_doc_structure to find a suitable insertion index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the page break should be inserted.

        Returns:
            Confirmation with docId and the insertion index.
        """
        lc = ctx.request_context.lifespan_context

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(
                    documentId=doc_id,
                    body={"requests": [{"insertPageBreak": {"location": {"index": index}}}]},
                )
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_page_break: at index %d in doc %s", index, doc_id)
        return {"docId": doc_id, "index": index}

    @tool(annotations=ToolAnnotations(title="Insert Soft-Break Paragraph", destructiveHint=True))
    async def insert_softbreak_paragraph(
        doc_id: str,
        index: int,
        lines: list[dict],
        named_style_type: str = "NORMAL_TEXT",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert a single paragraph built from multiple lines joined by soft line
        breaks (Shift+Enter in the Docs UI), with the paragraph's style set
        explicitly rather than inherited from whatever is at `index`.

        Use this for metadata/header-style blocks that must render as one tight
        paragraph with no blank line between rows — e.g. a document header block:
            Document ID: KH-OPS-001   (bold)
            Category: AWS / Database
            Source: ...
        insert_doc_text with "\\n" between lines creates separate paragraphs with a
        blank line between them instead. This also sidesteps delete_doc_range's
        paragraph-merge style-inheritance gotcha (see its docstring) by setting
        namedStyleType explicitly on the whole paragraph the block lands in, rather
        than leaving it to whichever neighboring paragraph it happened to merge into.

        To replace existing content with a soft-break block: delete it first with
        delete_doc_range, then call this tool at the same index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document position to insert at. Use get_doc_structure to find it.
            lines: List of line dicts, each with:
                text (str): the line's text (required, non-empty).
                Optional per-line text style, applied only to that line's own span
                (same vocabulary as style_doc_range's text-style fields):
                  bold, italic, underline, strikethrough (bool)
                  font_size (float): size in points
                  foreground_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                  link_url (str | null): set a hyperlink (null to clear)
            named_style_type: Paragraph style applied to the whole paragraph the
                inserted block ends up in (per Docs API updateParagraphStyle
                semantics, this covers the entire paragraph touched by the insert,
                not just the newly-inserted span). NORMAL_TEXT (default),
                HEADING_1 … HEADING_6, TITLE, SUBTITLE.

        Returns:
            Confirmation with docId, start_index, end_index (the inserted block's
            span), and line_ranges — a parallel list of {start_index, end_index}
            per line, usable directly with style_doc_range for any styling beyond
            what this call already applied.
        """
        lc = ctx.request_context.lifespan_context

        if not lines:
            return {"error": "lines list is empty"}
        for line in lines:
            if not line.get("text"):
                return {"error": "every line must have non-empty 'text'"}
        if named_style_type not in _NAMED_STYLE_TYPES:
            return {
                "error": f"invalid named_style_type {named_style_type!r}; must be one of: "
                f"{', '.join(sorted(_NAMED_STYLE_TYPES))}"
            }

        joined_text = "\v".join(line["text"] for line in lines)
        end_index = index + utf16_len(joined_text)

        requests: list[dict[str, Any]] = [
            {"insertText": {"location": {"index": index}, "text": joined_text}},
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": index, "endIndex": end_index},
                    "paragraphStyle": {"namedStyleType": named_style_type},
                    "fields": "namedStyleType",
                }
            },
        ]

        line_ranges: list[dict[str, int]] = []
        cursor = index
        for i, line in enumerate(lines):
            line_start = cursor
            line_end = line_start + utf16_len(line["text"])
            line_ranges.append({"start_index": line_start, "end_index": line_end})

            text_style, fields = _text_style_and_fields(line)
            # See style_doc_range's identical comment (#408): a link-clear-only
            # line legitimately produces an empty text_style with fields=["link"].
            if fields:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": {"startIndex": line_start, "endIndex": line_end},
                            "textStyle": text_style,
                            "fields": ",".join(fields),
                        }
                    }
                )

            cursor = line_end + (1 if i < len(lines) - 1 else 0)  # +1 for the "\v" separator

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug(
            "insert_softbreak_paragraph: %d lines at index %d in doc %s",
            len(lines),
            index,
            doc_id,
        )
        return {
            "docId": doc_id,
            "start_index": index,
            "end_index": end_index,
            "line_ranges": line_ranges,
        }

    @tool(annotations=ToolAnnotations(title="Insert Local Images by Marker", destructiveHint=True))
    async def insert_local_images(
        doc_id: str,
        images: list[dict],
        folder_id: str | None = None,
        revoke_sharing: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Upload local image files to Drive and swap each into a Google Doc at a
        plain-text marker, in one call.

        Typical flow: write doc content with a unique plain-text placeholder per
        image (e.g. "IMGMARKERONE") via create_doc/write_doc_content/insert_doc_text,
        then call this tool once with the marker → local file mapping. Collapses the
        N manual upload/find/insert/delete round trips a multi-image doc would
        otherwise need into a single call.

        For each image: uploads the local file to Drive, shares it as
        anyone-with-link/reader (required — the Docs backend fetches inline images
        as an anonymous HTTP request, so a private file fails with "There was a
        problem retrieving the image"; confirmed live 2026-07-18), locates its
        marker's current position, inserts the image immediately before the marker
        text, then deletes the marker text. Once the image is actually embedded,
        that temporary share is revoked again by default (revoke_sharing=True) —
        revoking any earlier would break the embed, since Docs fetches the image at
        insertion time, not upload time.

        All markers are located in a single pass over the document's current text
        before any edits are applied — markers are matched longest-first at each
        position, so one marker that's a substring of another (e.g. "IMG1" vs
        "IMG10") can't produce a false match or a false "occurs twice" collision.
        Uploads and shares run in parallel; the document edit is one batchUpdate
        applied highest-index-first so replacing one marker never invalidates
        another marker's already-computed position — same convention as
        insert_doc_text/delete_doc_range. Uploading and sharing happen before any
        document edit, so a failed upload never leaves the doc partially edited.

        Args:
            doc_id: The Google Doc file ID.
            images: List of image dicts, each with:
                marker (str): exact literal text already present in the doc body,
                    marking where this image goes. Matched as a whole token — not
                    immediately preceded or followed by another letter, digit, or
                    underscore — so a marker like "IMG1" can't falsely match inside
                    unrelated text like "IMG10". Must occur exactly once in the
                    document (searched case-sensitively) — an ambiguous or missing
                    marker fails just that image, not the whole call.
                local_path: absolute path to the local image file.
                width, height (float, optional): image size in points.
            folder_id: Drive folder to upload images into. Defaults to the server's
                configured default folder.
            revoke_sharing: Whether each image's temporary anyone:reader share is
                revoked again after it's embedded (default True). Set False to leave
                images shared instead — matches this tool's original behavior.

        Returns:
            Dictionary with docId and results — a list of per-image outcomes in the
            same order as the `images` argument, each echoing marker and local_path
            plus either fileId + index + shared (+ revoke_error if a revoke attempt
            failed) on success, or error on failure (marker not found, marker not
            unique, local file missing, upload failure, sharing failure, or — rare,
            since uploads happen first — a failed document edit; that last case
            never carries a fileId even though the upload itself succeeded, since
            the image was never actually placed).
        """
        lc = ctx.request_context.lifespan_context
        docs_service = lc.docs_service
        drive_service = lc.drive_service
        target_folder_id = folder_id or lc.folder_id

        if not images:
            return {"error": "images list is empty"}
        if not target_folder_id:
            return {"error": "folder_id is required (no server default folder configured)"}

        try:
            doc = await execute_in_thread(
                docs_service.documents().get(documentId=doc_id).execute,
                docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        paragraphs = list(_collect_doc_paragraphs(doc.get("body", {}).get("content", [])))

        # Locate every requested marker in a single pass over the document. Two
        # measures guard against one marker being a substring of another piece of
        # text: (1) each match must be a whole token — not immediately preceded or
        # followed by another letter/digit/underscore — so a marker "IMG1" can't
        # match inside unrelated document text "IMG10"; (2) alternatives are tried
        # longest-first, so if two *requested* markers legitimately overlap at the
        # same position (e.g. both "IMG1" and "IMG10" are real, distinct markers
        # present in the doc), the longer one wins there rather than the shorter
        # one swallowing part of it.
        marker_texts = {img.get("marker") for img in images if img.get("marker")}
        located: dict[str, list[int]] = {m: [] for m in marker_texts}
        if marker_texts:
            alternation = "|".join(
                re.escape(m) for m in sorted(marker_texts, key=len, reverse=True)
            )
            combined = re.compile(rf"(?<![A-Za-z0-9_])(?:{alternation})(?![A-Za-z0-9_])")
            for para_text, para_indices in paragraphs:
                for m in combined.finditer(para_text):
                    located[m.group(0)].append(para_indices[m.start()])

        # outcomes is index-aligned with `images` throughout, so the returned
        # `results` list always matches caller input order regardless of the
        # order placements finish uploading or get written to the doc.
        outcomes: list[dict[str, Any] | None] = [None] * len(images)
        placements: list[dict[str, Any]] = []  # located + validated, ready to upload+place

        for i, image in enumerate(images):
            marker = image.get("marker")
            local_path = image.get("local_path")
            entry: dict[str, Any] = {"marker": marker, "local_path": local_path}

            if not marker:
                entry["error"] = "missing 'marker'"
                outcomes[i] = entry
                continue
            if not local_path:
                entry["error"] = "missing 'local_path'"
                outcomes[i] = entry
                continue
            if not Path(local_path).is_file():
                entry["error"] = f"No file found at {local_path!r}"
                outcomes[i] = entry
                continue

            matches = located.get(marker, [])
            if not matches:
                entry["error"] = f"marker {marker!r} not found in document"
                outcomes[i] = entry
                continue
            if len(matches) > 1:
                entry["error"] = f"marker {marker!r} occurs {len(matches)} times; must be unique"
                outcomes[i] = entry
                continue

            placements.append(
                {
                    "index": i,
                    "entry": entry,
                    "marker_start": matches[0],
                    "marker_len": utf16_len(marker),
                    "local_path": local_path,
                    "width": image.get("width"),
                    "height": image.get("height"),
                }
            )

        async def _upload_and_share(placement: dict[str, Any]) -> None:
            entry = placement["entry"]
            try:
                upload = await _upload_local_file(
                    drive_service, placement["local_path"], target_folder_id, skip_if_exists=False
                )
                if "error" in upload:
                    entry["error"] = upload["error"]
                    placement["failed"] = True
                    return

                file_id = upload["fileId"]
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
                entry["error"] = f"upload/share failed: {e}"
                placement["failed"] = True
                return

            uri = metadata.get("webContentLink")
            if not uri:
                entry["error"] = (
                    f"uploaded and shared as {file_id} but Drive returned no webContentLink"
                )
                placement["failed"] = True
                return

            placement["file_id"] = file_id
            placement["permission_id"] = perm.get("id")
            placement["uri"] = uri
            entry["fileId"] = file_id

        if placements:
            # return_exceptions=True: _upload_and_share already catches its own
            # errors, but this also guards against anything unexpected escaping it
            # without one failed image's exception aborting every other upload.
            gather_results = await asyncio.gather(
                *(_upload_and_share(p) for p in placements), return_exceptions=True
            )
            for placement, result in zip(placements, gather_results):
                if isinstance(result, BaseException):
                    placement["failed"] = True
                    placement["entry"]["error"] = f"upload/share failed: {result}"

        if any("file_id" in p for p in placements):
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        for placement in placements:
            if placement.get("failed"):
                outcomes[placement["index"]] = placement["entry"]

        ready = [p for p in placements if not p.get("failed")]
        if not ready:
            return {"docId": doc_id, "results": outcomes}

        # Highest marker_start first, so an earlier (lower-index) marker's position
        # is never shifted by a later edit — same convention as insert_doc_text.
        requests: list[dict[str, Any]] = []
        for placement in sorted(ready, key=lambda p: p["marker_start"], reverse=True):
            marker_start = placement["marker_start"]
            image_request: dict[str, Any] = {
                "insertInlineImage": {
                    "location": {"index": marker_start},
                    "uri": placement["uri"],
                }
            }
            width, height = placement.get("width"), placement.get("height")
            if width is not None or height is not None:
                object_size: dict[str, Any] = {}
                if width is not None:
                    object_size["width"] = {"magnitude": width, "unit": "PT"}
                if height is not None:
                    object_size["height"] = {"magnitude": height, "unit": "PT"}
                image_request["insertInlineImage"]["objectSize"] = object_size
            requests.append(image_request)
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": marker_start + 1,
                            "endIndex": marker_start + 1 + placement["marker_len"],
                        }
                    }
                }
            )

        doc_edit_error: str | None = None
        try:
            await execute_in_thread(
                docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                docs_service,
            )
        except Exception as e:
            doc_edit_error = str(e)

        for placement in ready:
            entry = placement["entry"]
            # fileId/shared are kept regardless of doc_edit_error: a failed embed
            # doesn't undo the upload+share that already succeeded, so the file is
            # still genuinely world-readable and the caller needs fileId to trace
            # it — silently dropping both here would leave it orphaned with zero
            # signal (PR #502 review round 1, finding #1).
            entry["shared"] = True
            if doc_edit_error is not None:
                entry["error"] = f"doc edit failed: {doc_edit_error}"
            else:
                entry["index"] = placement["marker_start"]
            outcomes[placement["index"]] = entry

        if revoke_sharing:

            async def _revoke(placement: dict[str, Any]) -> None:
                try:
                    await execute_in_thread(
                        drive_service.permissions()
                        .delete(
                            fileId=placement["file_id"],
                            permissionId=placement["permission_id"],
                            supportsAllDrives=True,
                        )
                        .execute,
                        drive_service,
                    )
                    placement["entry"]["shared"] = False
                except Exception as e:
                    placement["entry"]["revoke_error"] = str(e)

            # return_exceptions=True: _revoke already catches its own errors, same
            # rationale as the upload/share gather above. Runs regardless of
            # doc_edit_error — an image that failed to embed was still genuinely
            # uploaded and shared, so a failed embed must not skip cleanup of that
            # real, temporary anyone:reader grant.
            await asyncio.gather(*(_revoke(p) for p in ready), return_exceptions=True)

        if doc_edit_error is None:
            lc.doc_cache.mark_dirty(doc_id)
        logger.debug(
            "insert_local_images: %d/%d images placed in doc %s",
            0 if doc_edit_error is not None else len(ready),
            len(images),
            doc_id,
        )
        return {"docId": doc_id, "results": outcomes}
