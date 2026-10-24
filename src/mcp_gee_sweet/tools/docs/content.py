import asyncio
import logging
import re
import xml.etree.ElementTree as etree
from pathlib import Path
from typing import Any

import anyio
import markdown as _md
from googleapiclient.errors import HttpError
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import SpreadsheetContext, after_abandoned_calls, execute_in_thread
from ...cache import CACHE_VALIDATE_MODIFIED_TIME
from ...local_files import LocalFileAccessError, check_read, check_write
from ..drive import _quota_error_text
from ..drive.transfer import _GOOGLE_DOC_MIME
from ..http_errors import http_error_has_reason, is_storage_quota_error
from ..response_limits import enforce_response_size_cap, write_capped_result_to_disk
from .anchors import compute_scheme_slugs, resolve_heading_anchor
from .ast import Run, Table
from .emitter import ast_to_requests, extract_images, fill_tables
from .html_parser import html_to_ast
from .images import (
    ImageShareLifecycle,
    check_drive_image_metadata,
    downscale_drive_file,
    record_image_outcome,
    rewrite_too_large_error,
    share_image_file,
    upload_and_share_local_image,
)
from .indices import _collect_doc_paragraphs, decode_code_run_text, utf16_len
from .markdown_export import _discard_temp_doc
from .style import _add_or_clear_field

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
_FAILED_REQUEST_PREFIX_RE = re.compile(r"^Invalid requests\[\d+\]\.")


def _failed_insert_image_request_index(error: HttpError) -> int | None:
    """Extract the failing request's index from a batchUpdate HttpError whose
    message names an insertInlineImage request specifically (#333) — e.g.
    'Invalid requests[28].insertInlineImage: There was a problem retrieving the
    image...'. Returns None for any other error shape, so the caller re-raises
    instead of misinterpreting an unrelated failure as an image-fetch problem.

    Matches the status code plus error.reason — which HttpError fills from the
    JSON body's error.message — rather than str(error), whose display wrapper
    could change independently of the API's own error body (#510). Body shape
    confirmed live: {"error": {"code": 400, "message": "Invalid
    requests[N].insertInlineImage: ...", "status": "INVALID_ARGUMENT"}}, naming
    only the first failing image even when several in the same batch are
    unfetchable.
    """
    if error.resp.status != 400 or not isinstance(error.reason, str):
        return None
    match = _FAILED_INSERT_IMAGE_INDEX_RE.search(error.reason)
    return int(match.group(1)) if match else None


def _failed_insert_image_message(error: HttpError) -> str:
    """Caller-facing text for an image dropped by _apply_doc_content's retry: the
    API's own message minus its 'Invalid requests[N].' lead-in, since N indexes
    whichever internal retry batch failed and means nothing to the caller."""
    return rewrite_too_large_error(_FAILED_REQUEST_PREFIX_RE.sub("", error.reason))


_POSITIONAL_INSERT_KEYS = ("insertTable", "insertInlineImage")


def _positional_insert_tail_start(
    requests: list[dict], image_links: dict[int, dict] | None = None
) -> int:
    """Index where ast_to_requests's trailing stage-3 pass (the descending-position
    insertTable + insertInlineImage requests — see its docstring) begins: the start
    of the maximal suffix made up only of those two request kinds, plus each linked
    image's own link request (#977). `image_links` is the id(insert) -> link
    request map ast_to_requests filled; a link request counts by identity."""
    link_ids = {id(link) for link in (image_links or {}).values()}
    start = len(requests)
    while start > 0 and (
        id(requests[start - 1]) in link_ids
        or any(key in requests[start - 1] for key in _POSITIONAL_INSERT_KEYS)
    ):
        start -= 1
    return start


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
    "permission_id": ...} for a drive:/local source (plus "downscaled": True for a
    local file auto_downscale resized) — the permission_id is the
    just-granted anyone:reader permission, for the caller to revoke once the doc edit
    that embeds this image is over, whether it succeeded or not (revoking any earlier
    would break the embed, since Docs fetches the image at insertion time, not upload
    time; #789). Returns
    {"error": ...} on failure. If this call *uploaded* a local file and only the
    sharing step afterward failed, the error also carries {"file_id": ...} so the
    caller isn't left with an untracked orphan (#649, mirrors #420's fix in
    drive/transfer.py). A "drive:" source's sharing failure deliberately does NOT
    carry file_id — that file is the caller's own pre-existing artifact, not an
    orphan this call created, and surfacing it in a failed-image outcome would let a
    caller with orphan-reclaim logic delete a file it never made (PR #652 QA round 1).
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
                    fields="name,parents,imageMediaMetadata,size,webContentLink,permissionIds",
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
            return await downscale_drive_file(
                drive_service, file_id, drive_metadata, target_folder_id
            )
        # A "drive:" file pre-existed this call, so a sharing failure never reports
        # it as an orphan (created_here=False) — see the docstring.
        return await share_image_file(
            drive_service,
            file_id,
            drive_metadata.get("webContentLink"),
            drive_metadata.get("permissionIds"),
            created_here=False,
        )
    else:
        try:
            # Before the stat, so a refused path reads the same whether or not it
            # exists (#796).
            if not check_read(src).is_file():
                return {"error": f"No file found at {src!r}"}
        except LocalFileAccessError as e:
            return {"error": str(e)}
        if not target_folder_id:
            return {
                "error": "folder_id is required to upload a local image "
                "(no server default folder configured)"
            }

        return await upload_and_share_local_image(
            drive_service, src, target_folder_id, auto_downscale=auto_downscale
        )


_SOURCE_FILE_FORMATS = {".md": "markdown", ".html": "html", ".htm": "html"}


def _read_doc_source_file(
    local_path: str, content_format: str | None, *, format_overridable: bool
) -> tuple[str, str] | dict[str, Any]:
    """Shared file reading for create_doc_from_file / update_doc_from_file (#567):
    returns (content, content_format), or {"error": ...} for a missing file, a path
    that isn't a regular file, an unreadable or non-UTF-8 file, or an extension with
    no inferable format. content_format=None infers it from the extension.
    format_overridable says whether the calling tool takes a content_format
    parameter, so the error only suggests one when it exists.

    Reads the file, so callers run it via asyncio.to_thread."""
    try:
        path = check_read(local_path)
    except LocalFileAccessError as e:
        return {"error": str(e)}
    if not path.exists():
        return {"error": f"File not found: {local_path}"}
    if not path.is_file():
        return {"error": f"Not a regular file: {local_path}"}
    if content_format is None:
        # The caller's own suffix, not the resolved one: a symlink keeps its link name.
        ext = Path(local_path).suffix.lower()
        inferred = _SOURCE_FILE_FORMATS.get(ext)
        if inferred is None:
            hint = ", or pass content_format explicitly." if format_overridable else ""
            return {"error": f"Unsupported file extension '{ext}'. Use .md or .html/.htm{hint}"}
        content_format = inferred
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return {"error": f"File is not valid UTF-8: {local_path} ({e.reason} at byte {e.start})"}
    except OSError as e:
        return {"error": f"Could not read file {local_path}: {e.strerror or e}"}
    return content, content_format


# A bound on the backup copy (all attempts), since it runs shielded from
# cancellation and a cancel waits for shielded work. Measured at 2.5-4 s for a
# 20 KB doc; a doc with many images takes longer.
_BACKUP_COPY_TIMEOUT = 60

# A 429 on the copy is retried this many times, with exponential backoff. A 429
# means Drive ran nothing; a 5xx isn't retried, since the copy may already exist
# and a retry would make another one.
_BACKUP_COPY_RATE_LIMIT_RETRIES = 3


def _was_rejected(e: BaseException) -> bool:
    """True if `e` is an HttpError the API answered with a 4xx, meaning the
    request ran nothing. A 5xx, a timeout, or a transport error doesn't say
    whether the request landed."""
    return isinstance(e, HttpError) and 400 <= int(e.resp.status) < 500


def _no_backup_reason(e: BaseException) -> str | None:
    """Why a failed backup copy lets the replace go ahead without one, or None if
    the failure must stop it (#1018). Decided by Drive's error reason, not the
    status: rateLimitExceeded and userRateLimitExceeded are 403s too, and they
    stop it. insufficientFilePermissions is what Drive returns when the caller can
    edit the doc but not add a file to its folder (measured live, 2026-10-14).
    teamDriveFileLimitExceeded and numChildrenInNonRootLimitExceeded are a Shared
    Drive's and a My Drive folder's item limits (documented reasons; they can't be
    produced in QA)."""
    if is_storage_quota_error(e):
        # Worded for both causes: a service account with no storage, and a user
        # whose destination is full (#1009).
        return "there's no Drive storage quota left for the copy"
    if http_error_has_reason(e, 403, "insufficientFilePermissions"):
        return "this account can't add a file to the document's folder"
    if http_error_has_reason(e, 403, "teamDriveFileLimitExceeded"):
        return "the document's Shared Drive is at its item limit"
    if http_error_has_reason(e, 403, "numChildrenInNonRootLimitExceeded"):
        return "the document's folder is at its item limit"
    return None


def _opt_in_no_backup_reason(e: BaseException) -> str | None:
    """Why a failed backup copy lets the replace go ahead without one only when the
    caller passed allow_no_backup=True, or None (#1035). cannotCopyFile is what a
    writer gets when downloadRestrictions' restrictedForWriters is set (measured
    live, 2026-10-14); the same writer also gets cannotExportFile, so the backup is
    never made another way. It isn't worded as the owner's choice, since a Shared
    Drive doc has no owner (PR #1042 QA round 1). activeItemCreationLimitExceeded is
    the account's item-creation cap (a documented reason; it can't be produced in
    QA)."""
    if http_error_has_reason(e, 403, "cannotCopyFile"):
        return "the document's sharing settings don't allow this account to copy it"
    if http_error_has_reason(e, 403, "activeItemCreationLimitExceeded"):
        return "this account is at its limit for creating Drive items"
    return None


async def _can_edit(drive_service, doc_id: str) -> bool | None:
    """The doc's capabilities.canEdit for this account, or None if it can't be
    read. On None the caller goes on as if it could edit: a clear it can't make
    gets a 4xx, which still leaves the doc unchanged."""
    try:
        file = await execute_in_thread(
            drive_service.files()
            .get(fileId=doc_id, fields="capabilities(canEdit)", supportsAllDrives=True)
            .execute,
            drive_service,
        )
    except Exception as e:
        logger.debug("Couldn't read doc %s's capabilities: %s", doc_id, e)
        return None
    can_edit = file.get("capabilities", {}).get("canEdit")
    return can_edit if isinstance(can_edit, bool) else None


def _describe(e: BaseException) -> str:
    """str(e), or the exception's type name when that's empty (a TimeoutError)."""
    return str(e) or type(e).__name__


async def _copy_for_backup(drive_service, doc_id: str, name: str) -> dict[str, Any]:
    """files.copy of `doc_id` named `name`, next to the source. Retries a 429
    only, within _BACKUP_COPY_TIMEOUT for every attempt together."""
    request = drive_service.files().copy(
        fileId=doc_id,
        body={"name": name},
        fields="id,name,capabilities(canDelete)",
        supportsAllDrives=True,
    )
    with anyio.fail_after(_BACKUP_COPY_TIMEOUT):
        for attempt in range(_BACKUP_COPY_RATE_LIMIT_RETRIES + 1):
            try:
                return await execute_in_thread(request.execute, drive_service)
            except HttpError as e:
                if int(e.resp.status) != 429 or attempt == _BACKUP_COPY_RATE_LIMIT_RETRIES:
                    raise
            await anyio.sleep(2**attempt)
    raise AssertionError("unreachable")


async def _create_doc_file(
    lc: SpreadsheetContext, file_body: dict[str, Any], target_folder_id: str | None
) -> dict[str, Any]:
    """Drive files.create for create_doc / create_doc_from_file. A cancelled create
    can still land after the call unwinds, putting the Doc in the folder with no
    later step to invalidate its listing, so the folder is marked dirty again once
    an abandoned create finishes (#907; PR #1029 QA round 2)."""
    drive_service = lc.drive_service
    request = drive_service.files().create(
        supportsAllDrives=True,
        body=file_body,
        fields="id, name, parents, webViewLink",
    )
    if not target_folder_id:
        return await execute_in_thread(request.execute, drive_service)
    with after_abandoned_calls(lambda: lc.drive_folder_cache.mark_dirty(target_folder_id)):
        return await execute_in_thread(request.execute, drive_service)


async def _doc_end_index(docs_service, doc_id: str) -> tuple[dict[str, Any], int]:
    """The doc and its body's endIndex (2 for an empty doc)."""
    doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id).execute,
        docs_service,
    )
    body_content = doc.get("body", {}).get("content", [])
    return doc, body_content[-1].get("endIndex", 2) if body_content else 2


async def _replace_doc_content(
    lc: SpreadsheetContext,
    doc_id: str,
    content: str,
    content_format: str,
    *,
    autolink_urls: bool,
    revoke_sharing: bool,
    auto_downscale: bool,
    allow_no_backup: bool,
) -> dict[str, Any]:
    """Shared body for write_doc_content / update_doc_from_file (#341): clears an
    existing doc's content, then replaces it via _apply_doc_content. Extracted so
    the clear-then-insert mechanism (including the same-batch insertText
    style-inheritance quirk below) has exactly one implementation instead of two
    copies that could drift out of sync.

    The flags are keyword-only (#567), here and in _apply_doc_content: as
    positional bools, swapping two at a call site would type-check and silently do
    the wrong thing.

    A doc with content is copied with Drive before the clear (#878), and the copy
    is deleted once the new content is in. If anything after the copy fails or is
    cancelled, the copy is kept and a failure result names it as "backupId". Drive's
    revision history can't serve this: Docs merges the revision current before the
    clear into the clear's own revision at once, so its ID is a 404 straight away
    (measured live; see docs/design/doc-replace-backup.md). A failed copy leaves the
    doc untouched and returns an error, except for the reasons _no_backup_reason
    accepts (storage quota, no right to add to the doc's folder, a full Shared
    Drive; #1018): a caller who can edit the doc could write it before #878, so it
    replaces without a backup, and both a success and a failure say so. The reasons
    _opt_in_no_backup_reason accepts (sharing settings block copying, the
    account's item-creation cap) do the same only with allow_no_backup=True, and
    otherwise refuse with an error that names the flag (#1035). An account that
    can't edit the doc is refused for that instead, whatever the flag says.

    The doc is unchanged, and the copy removed, only when a step before the clear
    fails or the clear gets a 4xx. A clear that fails any other way (a 5xx, a
    timeout, a transport error) may have landed, so the copy is kept and the error
    says the content may have been cleared (PR #1017 QA round 1).
    """
    docs_service = lc.docs_service
    drive_service = lc.drive_service
    doc_cache = lc.doc_cache
    doc, end_index = await _doc_end_index(docs_service, doc_id)

    backup: dict[str, Any] = {}
    no_backup_reason: str | None = None
    opt_in_reason: str | None = None
    if end_index > 2:
        backup_name = f"{doc.get('title') or doc_id} (backup before replace)"
        # Shielded, so a cancellation can't land after Drive made the copy but
        # before its ID is recorded (the PR #877 rule); bounded inside by
        # _BACKUP_COPY_TIMEOUT.
        with anyio.CancelScope(shield=True):
            try:
                backup = await _copy_for_backup(drive_service, doc_id, backup_name)
            except Exception as e:
                no_backup_reason = _no_backup_reason(e)
                opt_in_reason = _opt_in_no_backup_reason(e)
                if no_backup_reason is None and opt_in_reason is None:
                    error = (
                        f"Couldn't back up the document before replacing its content, "
                        f"so it was left unchanged: {_describe(e)}"
                    )
                    if not _was_rejected(e):
                        # Drive may have made the copy and lost the response.
                        error += (
                            f". A copy named {backup_name!r} may still have been created "
                            f"next to the document; check for it and delete it"
                        )
                    return {"error": error, "docId": doc_id}
                if no_backup_reason is not None:
                    logger.warning(
                        "Replacing doc %s without a backup: %s", doc_id, no_backup_reason
                    )

        if opt_in_reason is not None:
            # Outside the shield: nothing was created, so a cancel here loses
            # nothing. A reader gets cannotCopyFile too (copyRequiresWriterPermission),
            # and the flag can't help it, so it's told the real problem (PR #1042 QA
            # round 1).
            if await _can_edit(drive_service, doc_id) is False:
                return {
                    "error": (
                        f"This account can't edit the document, so it was left unchanged "
                        f"(Drive also refused the backup copy: {opt_in_reason})."
                    ),
                    "docId": doc_id,
                }
            if not allow_no_backup:
                return {
                    "error": (
                        f"Couldn't back up the document before replacing its content "
                        f"({opt_in_reason}), so it was left unchanged. To replace it "
                        f"without a backup, retry with allow_no_backup=True. Its previous "
                        f"content then can't be recovered with export_revision: Docs "
                        f"merges the revision from before the replace into the "
                        f"replace's own."
                    ),
                    "docId": doc_id,
                }
            no_backup_reason = opt_in_reason
            logger.warning("Replacing doc %s without a backup: %s", doc_id, no_backup_reason)

        # Re-read after the copy, which takes seconds: a concurrent edit meanwhile
        # would otherwise survive the clear (the doc grew) or make it fail (it
        # shrank).
        try:
            _, end_index = await _doc_end_index(docs_service, doc_id)
        except BaseException as e:
            return await _unchanged_result(drive_service, backup, doc_id, e)

    def _failed(e: BaseException, cleared: str) -> dict[str, Any]:
        """The result for a failure once the clear was sent; `cleared` is "yes",
        "maybe", or "no" (the doc was empty by the time the clear would run)."""
        doc_cache.mark_dirty(doc_id)
        if not isinstance(e, Exception):
            if backup.get("id"):
                logger.warning(
                    "Replacing doc %s was cancelled; kept its backup copy %s", doc_id, backup["id"]
                )
            raise e
        if isinstance(e, DocEditError):
            result = _doc_edit_failure_result(e, doc_id)
        else:
            result = {"error": f"doc edit failed: {_describe(e)}", "docId": doc_id}
        state = {
            "yes": "The document's previous content was cleared first",
            "maybe": "The document's previous content may have been cleared",
        }.get(cleared)
        if backup.get("id"):
            if state:
                result["error"] += (
                    f". {state}; a full copy of it is kept as {backup['name']!r} (backupId)."
                )
            else:
                result["error"] += (
                    f". A full copy of the document from before this call is kept as "
                    f"{backup['name']!r} (backupId)."
                )
            result["backupId"] = backup["id"]
        elif no_backup_reason and state:
            result["error"] += (
                f". {state} and couldn't be backed up ({no_backup_reason}), so the "
                f"document may be empty or partly written."
            )
        return result

    if end_index > 2:
        # The document's final paragraph mark can't be deleted by the Docs API (only
        # everything before it), so an explicit textStyle override left there by prior
        # content — e.g. the font_size:1 collapse applied to a blank paragraph before a
        # table, see _build_blank_para_before_table_collapses in emitter.py — would
        # otherwise survive this "clear" and can leak into newly-inserted content below.
        # Reset it before deleting, while its original index range is still valid.
        clear_requests = [
            {
                "updateTextStyle": {
                    "range": {"startIndex": end_index - 1, "endIndex": end_index},
                    "textStyle": {},
                    "fields": "*",
                }
            },
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}},
        ]
        # Sent as its own batchUpdate, not combined with the insert below: live testing
        # showed the Docs API resolves a same-batch insertText's inherited formatting
        # from a pre-batch snapshot, so contamination survived even after the clear
        # request above ran earlier in that same batch. A separate call forces the
        # insert to see the already-cleared document state.
        try:
            # A cancelled call's clear can still land after it returns (#907).
            with after_abandoned_calls(lambda: doc_cache.mark_dirty(doc_id)):
                await execute_in_thread(
                    docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": clear_requests})
                    .execute,
                    docs_service,
                )
        except BaseException as e:
            if _was_rejected(e):
                return await _unchanged_result(drive_service, backup, doc_id, e)
            return _failed(e, "maybe")
        cleared = "yes"
    else:
        cleared = "no"

    lifecycle = ImageShareLifecycle(lc, doc_id, revoke_sharing=revoke_sharing)
    try:
        image_outcomes = await _apply_doc_content(
            lc,
            doc_id,
            content,
            content_format,
            autolink_urls=autolink_urls,
            target_folder_id=lc.folder_id,
            revoke_sharing=revoke_sharing,
            auto_downscale=auto_downscale,
            lifecycle=lifecycle,
        )
    except BaseException as e:
        if lifecycle.edit_completed and not isinstance(e, Exception):
            # Cancelled during the image-share revoke, after the new content had
            # fully landed (PR #1029 QA round 1): the doc was replaced, so the
            # backup isn't needed.
            warning = await _discard_backup(drive_service, backup)
            if warning:
                logger.warning(
                    "Replacing doc %s was cancelled after it finished: %s", doc_id, warning
                )
            raise
        return _failed(e, cleared)
    # _apply_doc_content's lifecycle already marked the doc dirty, before the link
    # lookup below, which can still raise with the doc already replaced (PR #1017
    # QA round 2).

    no_backup_warning = (
        f"The document's previous content was replaced without a backup copy ({no_backup_reason})."
        if no_backup_reason and cleared == "yes"
        else None
    )

    # The backup's removal and the link lookup are independent, so they run
    # together. The removal catches its own errors; a lookup error is re-raised
    # after the removal finishes.
    warning: str | None = None
    metadata: dict[str, Any] = {}
    lookup_error: Exception | None = None

    async def _remove_backup() -> None:
        nonlocal warning
        warning = await _discard_backup(drive_service, backup)

    async with anyio.create_task_group() as tg:
        tg.start_soon(_remove_backup)
        try:
            metadata = await execute_in_thread(
                drive_service.files()
                .get(fileId=doc_id, fields="webViewLink", supportsAllDrives=True)
                .execute,
                drive_service,
            )
        except Exception as e:
            lookup_error = e
    if lookup_error is not None:
        if no_backup_warning:
            # The caller must still learn the old content is gone; the lookup
            # error alone wouldn't say so (PR #1034 QA round 1).
            raise RuntimeError(
                f"{no_backup_warning} The new content was written, but looking up "
                f"the document's link failed: {_describe(lookup_error)}"
            ) from lookup_error
        raise lookup_error

    logger.debug("Replaced content in doc %s", doc_id)
    result: dict[str, Any] = {"docId": doc_id, "web_link": metadata.get("webViewLink")}
    if image_outcomes is not None:
        result["images"] = image_outcomes
    if warning:
        result["warning"] = warning
    elif no_backup_warning:
        result["warning"] = no_backup_warning
    return result


async def _unchanged_result(
    drive_service, backup: dict[str, Any], doc_id: str, e: BaseException
) -> dict[str, Any]:
    """_replace_doc_content's result when it stopped before changing the doc: the
    backup isn't needed, so it's removed. A cancellation is re-raised after."""
    warning = await _discard_backup(drive_service, backup)
    if not isinstance(e, Exception):
        raise e
    result: dict[str, Any] = {
        "error": f"Couldn't clear the document, so it was left unchanged: {_describe(e)}",
        "docId": doc_id,
    }
    if warning:
        result["warning"] = warning
    return result


async def _discard_backup(drive_service, backup: dict[str, Any]) -> str | None:
    """Remove _replace_doc_content's backup copy, if one was made. Shielded, so a
    cancellation doesn't leave the copy behind. Returns a warning for the caller's
    result if the removal failed, else None."""
    if not backup.get("id"):
        return None
    with anyio.CancelScope(shield=True):
        cleanup_error = await _discard_temp_doc(
            drive_service, backup["id"], backup.get("capabilities", {}).get("canDelete", True)
        )
    if not cleanup_error:
        return None
    return (
        f"Couldn't remove the backup copy {backup['id']} made before replacing "
        f"the content; delete it manually ({cleanup_error})."
    )


class DocEditError(Exception):
    """_apply_doc_content's doc edit raised after its images were resolved (#789).
    Carries the per-image outcome list, which would otherwise be lost with the
    exception, so the calling tool can return it alongside the error the way
    insert_local_images does. The original exception is chained as __cause__."""

    def __init__(self, cause: Exception, image_outcomes: list[dict[str, Any]]):
        super().__init__(f"doc edit failed: {cause}")
        self.image_outcomes = image_outcomes


def _doc_edit_failure_result(e: DocEditError, doc_id: str) -> dict[str, Any]:
    """The tool response for a DocEditError: the error, the doc's ID (the doc
    exists, possibly partly written), and the per-image outcomes when there are
    any, so every file ID an image step created or shared reaches the caller."""
    result: dict[str, Any] = {"error": str(e), "docId": doc_id}
    if e.image_outcomes:
        result["images"] = e.image_outcomes
    return result


async def _apply_doc_content(
    lc: SpreadsheetContext,
    doc_id: str,
    content: str,
    content_format: str,
    *,
    autolink_urls: bool,
    target_folder_id: str | None,
    revoke_sharing: bool,
    auto_downscale: bool = False,
    lifecycle: ImageShareLifecycle | None = None,
) -> list[dict[str, Any]] | None:
    """Shared content-insertion body for create_doc / create_doc_from_file /
    write_doc_content (#333): converts content to AST, resolves any markdown/HTML
    images to fetchable URIs (uploading + temporarily sharing local paths and
    drive: references, matching insert_local_images's own lifecycle), runs the
    phase-1 batchUpdate, fills tables, resolves heading anchors, and finally
    best-effort revokes each image's temporary share (revoke_sharing=True, the
    default) once the doc edit is over — revoking any earlier would break the
    embed, since Docs fetches the image at insertion time, not upload time. The
    revoke runs whether the edit succeeded, raised, or was cancelled (#789), and
    both the image-resolution phase and the revoke are shielded from cancellation
    so a share that was granted is always known and always revoked. A failed edit
    raises DocEditError carrying the outcome list (the original exception chained
    as its cause); a cancellation propagates as-is. Either way the touched file IDs
    are also logged as a warning. That lifecycle, and the doc and folder cache
    invalidation that goes with it, is images.ImageShareLifecycle's (#908), shared
    with insert_local_images. A caller that needs to know how far a cancelled call
    got passes its own `lifecycle` (built for this doc_id and revoke_sharing) and
    reads its edit_completed afterward.

    auto_downscale (#400) is passed straight through to _resolve_image_source for
    each image — see that function's own docstring for the per-source-kind behavior
    and the http(s) scope boundary.

    Returns the per-image outcome list (None if the content had no images at all)
    for the caller to fold into its own response — each entry has src, plus either
    fileId + shared (+ revoke_error if a revoke attempt failed, + downscaled if
    auto_downscale resized it, + already_shared if the file was link-shared before
    this call, so its link was left in place) on success, or error
    on failure (also carrying fileId if the underlying Drive file was already
    created/found before a subsequent sharing failure — #649). Mirrors
    insert_local_images's own outcome shape for consistency.
    """
    html_content = (
        _md_to_html(content, autolink_urls=autolink_urls)
        if content_format == "markdown"
        else content
    )
    nodes = html_to_ast(html_content)

    images = extract_images(nodes)
    docs_service = lc.docs_service
    drive_service = lc.drive_service
    # The lifecycle records, for the shielded revoke and the warning log: in
    # .shares, the (outcome_entry, file_id, permission_id) of each image this call
    # shared, revoked once the doc edit below is over, whether it succeeded or
    # raised (#789) — a retry-removed image (see below) stays there, since it was
    # still uploaded and shared; in .created_file_ids, the files this call itself
    # created (a local upload, or a drive: source's resized copy), as opposed to a
    # caller's pre-existing drive: file, which the failed-edit warning must never
    # present as an orphan (PR #877 QA round 1).
    if lifecycle is None:
        lifecycle = ImageShareLifecycle(lc, doc_id, revoke_sharing=revoke_sharing)
    image_outcomes = lifecycle.outcomes
    # All keyed by id(img) — the only value guaranteed unique per image.
    # Neither a resolved URI nor a computed document position is safe to key on:
    # two images can resolve to the identical URI (the same picture used twice),
    # and two images with no separating content can land at the identical
    # position (PR #502 review round 1, finding #2) — either would make a
    # same-key lookup below silently pick the wrong image's outcome entry.
    entry_by_id: dict[int, dict[str, Any]] = {}
    real_uri_by_id: dict[int, str] = {}
    # ast_to_requests needs *some* URI per resolved image up front to build its
    # insertInlineImage requests — placeholders here (guaranteed unique, unlike
    # the real URIs) are swapped for the real ones below, in the same pass that
    # records which request dict came from which image.
    placeholder_uris: dict[int, str] = {}

    if images:
        results = await lifecycle.resolve(
            _resolve_image_source(drive_service, img.src, target_folder_id, auto_downscale)
            for img in images
        )
        for img, result in zip(images, results, strict=True):
            entry: dict[str, Any] = {"src": img.src}
            if isinstance(result, BaseException):
                entry["error"] = str(result)
            # record_image_outcome also surfaces a created-but-unshared orphan's
            # file_id (#649), so the caller isn't left with no record of it.
            elif record_image_outcome(entry, result):
                img_id = id(img)
                entry_by_id[img_id] = entry
                real_uri_by_id[img_id] = result["uri"]
                placeholder_uris[img_id] = f"urn:mcp-gee-sweet:pending-image:{img_id}"
                file_id = result.get("file_id")
                permission_id = result.get("permission_id")
                if file_id and permission_id:
                    entry["shared"] = True
                    lifecycle.shares.append((entry, file_id, permission_id))
                elif result.get("already_shared"):
                    # Public before this call: still shared, and never revoked —
                    # that link isn't this call's to remove (PR #842 QA round 1).
                    entry["shared"] = True
            file_id = entry.get("fileId")
            if file_id and (
                not img.src.startswith("drive:") or file_id != img.src[len("drive:") :]
            ):
                lifecycle.created_file_ids.add(file_id)
            image_outcomes.append(entry)

    # Everything from here to the revoke can raise (ast_to_requests, the content
    # batchUpdate, a non-image retry failure, fill_tables, anchor resolution) or be
    # cancelled, and by now every local-path/drive: image above is already shared
    # anyone:reader. So the lifecycle revokes on every exit, not only after success
    # (#789): revoking after a failed edit is harmless, since a doc that did embed
    # an image holds its own copy and one that didn't never needed the share.
    try:
        async with lifecycle.edit():
            image_links: dict[int, dict] = {}
            content_requests, tables = ast_to_requests(
                nodes, start_index=1, image_uris=placeholder_uris, image_links=image_links
            )

            # Swap each request's placeholder URI for the real one, recording which
            # image produced that exact request *object* (by its own id()) so the retry
            # below can trace a failure back to the right image without relying on URI
            # or position, both of which two images can share (see the comment above).
            # The retry's list copies and slices copy references, not the dicts, so id()
            # still matches — deep-copying any of them would silently break this lookup.
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
                # what makes this retry possible without re-deriving that index
                # some other way.
                #
                # Only the first failing image is named per error (confirmed live), so K
                # bad images need K retries. Resending the whole document each time would
                # be K+1 full-size round trips (#510). So: the first retry (K=1, the common
                # case) is still one atomic call of the whole remaining list. Only if that
                # names a *second* bad image does the list split: everything ahead of
                # ast_to_requests's trailing descending-position insertTable/
                # insertInlineImage pass (the "prefix": text, styles, bullets) is sent once
                # on its own, then only that small tail is retried per further bad image.
                # That boundary is the only safe split point: every prefix request must run
                # before any positional insert, while within the tail each insert lands at
                # or before every insert already applied, so dropping one never shifts the
                # rest.
                #
                # Residual partial-write window (K>=2 only): once the prefix has committed,
                # a tail retry failing for any *non*-image reason raises with the text
                # already in the doc but no tables or images (and fill_tables never runs).
                # Every path through K<=1 stays all-or-nothing.
                #
                # A dropped image's error is recorded on its outcome entry as it's dropped.
                # If a later call raises instead, those entries are kept: the raise
                # becomes a DocEditError carrying the whole outcome list (#789), so an
                # image dropped before the failure still reports its own error too.

                async def _batch_update(requests: list[dict]) -> None:
                    await execute_in_thread(
                        docs_service.documents()
                        .batchUpdate(documentId=doc_id, body={"requests": requests})
                        .execute,
                        docs_service,
                    )

                def _drop_failed_image(requests: list[dict], e: HttpError) -> bool:
                    """Pop the insertInlineImage request `e` names from `requests` (the
                    batch that raised `e`), plus its link request if the image was
                    linked (#977), recording the failure on its image's outcome
                    entry. False if `e` isn't an image-fetch failure, so the caller
                    re-raises."""
                    bad_index = _failed_insert_image_request_index(e)
                    if bad_index is None or bad_index >= len(requests):
                        return False
                    bad_request = requests.pop(bad_index)
                    # Left in place, the link would land on whatever character now
                    # sits at the image's position. Matched by identity: the list
                    # holds the same dict objects ast_to_requests recorded.
                    link = image_links.get(id(bad_request))
                    if link is not None:
                        link_index = next(i for i, r in enumerate(requests) if r is link)
                        requests.pop(link_index)
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
                        entry["error"] = f"doc edit failed: {_failed_insert_image_message(e)}"
                    return True

                committed: list[dict] = []
                remaining = list(content_requests)
                image_failures = 0
                while remaining:
                    try:
                        await _batch_update(remaining)
                        break
                    except HttpError as e:
                        if not _drop_failed_image(remaining, e):
                            raise
                        image_failures += 1
                        if image_failures != 2:
                            continue
                        tail_start = _positional_insert_tail_start(remaining, image_links)
                        # Fail-safe: split only if every image request really is in the
                        # tail. If ast_to_requests ever emits something after its
                        # positional-insert pass, the boundary scan comes up short —
                        # fall back to whole-list retries rather than committing an
                        # image-bearing prefix whose image failures couldn't be retried.
                        if any("insertInlineImage" in r for r in remaining[:tail_start]):
                            continue
                        if tail_start:
                            await _batch_update(remaining[:tail_start])
                        committed = remaining[:tail_start]
                        remaining = remaining[tail_start:]
                content_requests = committed + remaining
            await fill_tables(docs_service, doc_id, tables)
            if _has_pending_anchor_links(content_requests, tables):
                await _resolve_heading_anchors(docs_service, doc_id)
    except Exception as e:
        # The outcome list rides on the error so the calling tool can return it; a
        # raise alone would lose every file ID (#789). The lifecycle has already
        # revoked the shares and logged the touched files.
        raise DocEditError(e, image_outcomes) from e
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
    runs for any run or inline image whose link_url starts with '#'.

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
                    # A linked image carries its link on the inlineObjectElement's
                    # own textStyle (#977).
                    link_url = (
                        pe.get("inlineObjectElement", {})
                        .get("textStyle", {})
                        .get("link", {})
                        .get("url", "")
                    )
                    if link_url.startswith("#") and end is not None:
                        anchor_runs.append((link_url, run_start, end))

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
    # heading_texts is the same for every anchor in this document — compute
    # each slugify scheme's full slug list once and reuse it per anchor,
    # rather than paying that cost again for every anchor (issue #454).
    scheme_slugs = compute_scheme_slugs(heading_texts)
    for anchor, start, end in anchor_runs:
        match_idx = resolve_heading_anchor(anchor, heading_texts, scheme_slugs)
        text_style: dict[str, Any] = {}
        fields: list[str] = []
        if match_idx is not None:
            heading_url = (
                f"https://docs.google.com/document/d/{doc_id}"
                f"/edit?tab=t.0#heading={heading_ids[match_idx]}"
            )
            _add_or_clear_field(text_style, fields, "link", {"url": heading_url})
            resolved.append({"anchor": anchor, "heading": heading_texts[match_idx]})
        else:
            # _add_or_clear_field(..., None) omits "link" from textStyle while
            # still naming it in fields — see that helper's own docstring
            # (#408/#448) for why an empty textStyle here is correct, not a
            # bug, and the single place this "omit but mask" contract lives.
            _add_or_clear_field(text_style, fields, "link", None)
            stripped.append(anchor)
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": text_style,
                    "fields": ",".join(fields),
                }
            }
        )

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
        task list items, and images are all supported). Each table is inserted where it
        appears in the content. A table nested inside a table cell needs HTML content;
        Markdown has no syntax for one.

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

        A local-path or drive: image over Google Docs' ~25-megapixel or ~50MB
        inline-image limit fails with a clear error naming the limit it exceeds and
        its actual dimensions or file size, before any upload/share happens — set
        auto_downscale=True to resize it instead (see that arg's own docs). A public http(s) image can't be pre-validated this way; an
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
                share is revoked again after it's embedded (default True). An
                image file that was already link-shared before the call keeps its
                link and is reported with already_shared: true.
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False). A drive: source gets a new " (resized)"
                copy created alongside the original (left untouched); a local-path
                source uploads the resized bytes directly instead of the original file.
                No effect on a public http(s) image source (see above).

        Returns:
            Information about the newly created document including its ID and web link.
            Includes "images" (per-image outcomes) when content contained any images.
            If writing the content fails after the doc was created, returns
            {"error", "docId", "images"} instead, with any temporary image share
            already revoked.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Works on Shared Drives regardless of auth method.
            Workaround for service accounts: create the file manually in Drive, then use
            write_doc_content to populate it. Check server://auth-status for your current
            auth method.
        """
        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_folder_id = folder_id or lc.folder_id

        file_body: dict[str, Any] = {
            "name": title,
            "mimeType": _GOOGLE_DOC_MIME,
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            doc = await _create_doc_file(lc, file_body, target_folder_id)
        except HttpError as e:
            if is_storage_quota_error(e):
                return {"error": _quota_error_text(drive_service)}
            raise

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug(
            "Doc created with ID: %s%s",
            doc_id,
            f" in folder {target_folder_id}" if target_folder_id else " in root",
        )

        # Right after the create, not after the content: the doc is in the folder
        # from here on, however the content step ends (a failure or a
        # cancellation; PR #1029 QA round 1).
        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        image_outcomes = None
        if content:
            try:
                image_outcomes = await _apply_doc_content(
                    lc,
                    doc_id,
                    content,
                    content_format,
                    autolink_urls=autolink_urls,
                    target_folder_id=target_folder_id,
                    revoke_sharing=revoke_sharing,
                    auto_downscale=auto_downscale,
                )
            except DocEditError as e:
                return _doc_edit_failure_result(e, doc_id)

        result: dict[str, Any] = {
            "docId": doc_id,
            "title": doc.get("name", title),
            "folder": parents[0] if parents else "root",
            "web_link": doc.get("webViewLink"),
        }
        if image_outcomes is not None:
            result["images"] = image_outcomes
        return result

    @tool(
        annotations=ToolAnnotations(title="Create Document from File", destructiveHint=True),
        local_only=True,
    )
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
        Not available when the server runs with LOCAL_FILE_ACCESS=off.

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
                share is revoked again after it's embedded (default True). An
                image file that was already link-shared before the call keeps its
                link and is reported with already_shared: true.
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False) — see create_doc's own docstring.

        Returns:
            Information about the newly created document including its ID and web link.
            Includes "images" (per-image outcomes) when the file contained any images.
            If writing the content fails after the doc was created, returns
            {"error", "docId", "images"} instead, with any temporary image share
            already revoked.

        Note:
            Requires OAuth or ADC auth. Service accounts cannot create files in personal
            Drive (no storage quota). Check server://auth-status for your current auth method.
        """
        source = await asyncio.to_thread(
            _read_doc_source_file, local_path, None, format_overridable=False
        )
        if isinstance(source, dict):
            return source
        content, content_format = source
        doc_title = title or Path(local_path).stem

        lc = ctx.request_context.lifespan_context
        drive_service = lc.drive_service
        target_folder_id = folder_id or lc.folder_id

        file_body: dict[str, Any] = {
            "name": doc_title,
            "mimeType": _GOOGLE_DOC_MIME,
        }
        if target_folder_id:
            file_body["parents"] = [target_folder_id]

        try:
            doc = await _create_doc_file(lc, file_body, target_folder_id)
        except HttpError as e:
            if is_storage_quota_error(e):
                return {"error": _quota_error_text(drive_service)}
            raise

        doc_id = doc.get("id")
        parents = doc.get("parents")
        logger.debug("Doc created from file %s with ID: %s", local_path, doc_id)

        # Right after the create, not after the content: the doc is in the folder
        # from here on, however the content step ends (a failure or a
        # cancellation; PR #1029 QA round 1).
        if target_folder_id:
            lc.drive_folder_cache.mark_dirty(target_folder_id)

        image_outcomes = None
        if content:
            try:
                image_outcomes = await _apply_doc_content(
                    lc,
                    doc_id,
                    content,
                    content_format,
                    autolink_urls=autolink_urls,
                    target_folder_id=target_folder_id,
                    revoke_sharing=revoke_sharing,
                    auto_downscale=auto_downscale,
                )
            except DocEditError as e:
                return _doc_edit_failure_result(e, doc_id)

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
                A path ending in '/' is a directory, created if missing. A file in place
                of a parent directory, or at a path ending in '/', raises ValueError; an
                existing file at a plain file path is replaced.
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
        if local_path:
            # Before any fetch, so a refused destination costs no API call (#796).
            check_write(local_path)
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
        allow_no_backup: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace the full content of an existing Google Doc.

        Content is interpreted as HTML by default. Pass content_format='markdown' to supply
        Markdown instead. Headings, paragraphs, lists, links, tables, fenced code blocks,
        task list items, and images are all supported. Each table is inserted where it
        appears in the content. Use this to populate a doc created manually in Drive (bypassing
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
                share is revoked again after it's embedded (default True). An
                image file that was already link-shared before the call keeps its
                link and is reported with already_shared: true.
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False) — see create_doc's own docstring.
            allow_no_backup: Replace the content even when Drive refuses the backup
                copy (below) because the doc's sharing settings don't allow this
                account to copy it, or the account is at its item-creation limit
                (default False: the call refuses and leaves the doc unchanged). It
                has no effect when the account can't edit the doc.

        Returns:
            Confirmation with the document ID and web link. Includes "images" (per-image
            outcomes) when content contained any images.
            Includes "warning" if the backup copy (below) couldn't be removed, or
            if the content was replaced without one.
            Before clearing a doc that has content, a full copy of it is made in Drive,
            next to the doc, and deleted again once the new content is in. If the copy
            fails, nothing is changed and an error is returned, except when Drive
            refuses it for storage quota, because the account can't add a file to the
            doc's folder, or because the folder or Shared Drive is at its item limit:
            the replace then goes ahead without a backup. When sharing settings
            don't allow copying or the account is at its item-creation limit, it
            goes ahead without a backup only with allow_no_backup=True. If writing the
            new content fails, returns {"error", "docId", "backupId", "images"}
            instead, with any temporary image share already revoked: the doc may be
            empty or partly written, and backupId is the kept copy of its previous
            content. When the replace went ahead without a backup there's no
            backupId, and the error says the previous content couldn't be backed
            up: it can't be recovered.
        """
        lc = ctx.request_context.lifespan_context
        return await _replace_doc_content(
            lc,
            doc_id,
            content,
            content_format,
            autolink_urls=autolink_urls,
            revoke_sharing=revoke_sharing,
            auto_downscale=auto_downscale,
            allow_no_backup=allow_no_backup,
        )

    @tool(
        annotations=ToolAnnotations(title="Update Document from File", destructiveHint=True),
        local_only=True,
    )
    async def update_doc_from_file(
        doc_id: str,
        local_path: str,
        content_format: str | None = None,
        autolink_urls: bool = True,
        revoke_sharing: bool = True,
        auto_downscale: bool = False,
        allow_no_backup: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace an existing Google Doc's content in place from a local .md or .html file.
        Not available when the server runs with LOCAL_FILE_ACCESS=off.

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
                share is revoked again after it's embedded (default True). An
                image file that was already link-shared before the call keeps its
                link and is reported with already_shared: true.
            auto_downscale: Resize an oversized local-path/drive: image instead of
                failing it (default False) — see create_doc's own docstring.
            allow_no_backup: Replace the content even when Drive refuses the backup
                copy (below) because the doc's sharing settings don't allow this
                account to copy it, or the account is at its item-creation limit
                (default False: the call refuses and leaves the doc unchanged). It
                has no effect when the account can't edit the doc.

        Returns:
            Confirmation with the document ID and web link. Includes "images" (per-image
            outcomes) when the file contained any images.
            Includes "warning" if the backup copy (below) couldn't be removed, or
            if the content was replaced without one.
            Before clearing a doc that has content, a full copy of it is made in Drive,
            next to the doc, and deleted again once the new content is in. If the copy
            fails, nothing is changed and an error is returned, except when Drive
            refuses it for storage quota, because the account can't add a file to the
            doc's folder, or because the folder or Shared Drive is at its item limit:
            the replace then goes ahead without a backup. When sharing settings
            don't allow copying or the account is at its item-creation limit, it
            goes ahead without a backup only with allow_no_backup=True. If writing the
            new content fails, returns {"error", "docId", "backupId", "images"}
            instead, with any temporary image share already revoked: the doc may be
            empty or partly written, and backupId is the kept copy of its previous
            content. When the replace went ahead without a backup there's no
            backupId, and the error says the previous content couldn't be backed
            up: it can't be recovered.
        """
        source = await asyncio.to_thread(
            _read_doc_source_file, local_path, content_format, format_overridable=True
        )
        if isinstance(source, dict):
            return source
        content, content_format = source

        lc = ctx.request_context.lifespan_context
        return await _replace_doc_content(
            lc,
            doc_id,
            content,
            content_format,
            autolink_urls=autolink_urls,
            revoke_sharing=revoke_sharing,
            auto_downscale=auto_downscale,
            allow_no_backup=allow_no_backup,
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
            bold, italic, underline, strikethrough, font_size, link_url; an
            inline image is a run with type "inlineObject", its inlineObjectId,
            and its own startIndex/endIndex, and empty text), and
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
            — an ordinary URL, no special Link-object field required.
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
                    if "inlineObjectElement" in pe:
                        # #1070: an inline image occupies one index but has no text.
                        # Report it with its own index so edits can target it.
                        ioe = pe["inlineObjectElement"]
                        runs.append(
                            {
                                "type": "inlineObject",
                                "inlineObjectId": ioe.get("inlineObjectId"),
                                "startIndex": pe.get("startIndex", 0),
                                "endIndex": pe.get("endIndex", 0),
                                "text": "",
                                "bold": None,
                                "italic": None,
                                "underline": None,
                                "strikethrough": None,
                                "font_size": None,
                                "link_url": None,
                            }
                        )
                        continue
                    tr = pe.get("textRun")
                    if not tr:
                        continue
                    ts = tr.get("textStyle", {})
                    runs.append(
                        {
                            "text": decode_code_run_text(tr.get("content", ""), ts),
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
                            decode_code_run_text(
                                pe.get("textRun", {}).get("content", ""),
                                pe.get("textRun", {}).get("textStyle", {}),
                            )
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
                A path ending in '/' is a directory, created if missing. A file in place
                of a parent directory, or at a path ending in '/', raises ValueError; an
                existing file at a plain file path is replaced.
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
        if local_path:
            # Before any fetch, so a refused destination costs no API call (#796).
            check_write(local_path)
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
