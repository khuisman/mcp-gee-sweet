"""Gmail tools — messages, threads, labels, drafts, and organization primitives."""

import asyncio
import base64
import binascii
import codecs
import logging
import re
from dataclasses import dataclass, field
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, getaddresses
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ..auth import execute_in_thread, get_gmail_unauthorized_message
from .concurrency import gather_with_fallback
from .response_limits import (
    clamp_max_results,
    enforce_response_size_cap,
    enforce_response_size_floor,
    write_capped_result_to_disk,
)

logger = logging.getLogger(__name__)

_USER = "me"
_GMAIL_LIST_MAX = 500


def _format_address_header(value: str | list[str] | None) -> str | None:
    """Build a To/Cc/Bcc header with RFC 2047-safe display names via formataddr."""
    if value is None:
        return None
    chunks = value if isinstance(value, list) else [value]
    formatted = [formataddr((name, addr)) for name, addr in getaddresses(chunks) if addr]
    return ", ".join(formatted) if formatted else None


async def _own_addresses(gmail_service: Any) -> set[str]:
    """Every address the authenticated mailbox sends as, lowercased: its send-as
    aliases (users.settings.sendAs.list, which includes the primary address), or
    just the primary address (users.getProfile) if the alias list can't be read.
    Empty if neither call succeeds."""
    try:
        result = await execute_in_thread(
            gmail_service.users().settings().sendAs().list(userId=_USER).execute,
            gmail_service,
        )
        aliases = {
            a["sendAsEmail"].strip().lower()
            for a in (result or {}).get("sendAs") or []
            if isinstance(a.get("sendAsEmail"), str) and a["sendAsEmail"].strip()
        }
        if aliases:
            return aliases
    except Exception:
        logger.debug("Could not list send-as aliases", exc_info=True)
    try:
        profile = await execute_in_thread(
            gmail_service.users().getProfile(userId=_USER).execute,
            gmail_service,
        )
    except Exception:
        logger.debug("Could not resolve mailbox email via getProfile", exc_info=True)
        return set()
    email = (profile or {}).get("emailAddress")
    return {email.strip().lower()} if isinstance(email, str) and email.strip() else set()


def _reply_recipients(
    *,
    original_from: str,
    original_reply_to: str,
    original_to: str,
    original_cc: str,
    sent_label: bool,
    reply_all: bool,
    own: set[str],
) -> tuple[str | None, str | None]:
    """Resolve a reply's To/Cc the way a standard mail client does (#791).

    The original counts as the mailbox's own message when it carries Gmail's SENT
    label or its From is one of the mailbox's own addresses (`own`: primary plus
    send-as aliases).

    - Replying to someone else's message goes to its Reply-To when present (mailing
      lists, support desks, no-reply senders), otherwise its From.
    - Replying to the mailbox's own message goes to that message's original To (or
      its Cc, when it had no other To), not back to the mailbox. Its Reply-To is
      ignored, since it pointed other people at us.
    - reply_all adds the original To, and the original Cc as Cc.
    - The mailbox's own addresses and duplicates are dropped everywhere, plain reply
      included. If that empties To, Cc is promoted into To.

    If nobody else is left at all (a message the mailbox sent only to itself, or a
    Reply-To pointing back at the mailbox), the reply goes to the reply target
    unfiltered, so plain reply and reply_all agree and never fall back to a From
    that Reply-To asked to avoid.
    """
    from_self = sent_label or any(
        addr.lower() in own for _, addr in getaddresses([original_from]) if addr
    )
    primary = original_to if from_self else (original_reply_to or original_from)

    seen = set(own)
    to_parts: list[str] = []
    cc_parts: list[str] = []

    def add(target: list[str], header_value: str | None) -> None:
        for name, addr in getaddresses([header_value or ""]):
            if not addr:
                continue
            key = addr.lower()
            if key in seen:
                continue
            seen.add(key)
            target.append(formataddr((name, addr)))

    add(to_parts, primary)
    if reply_all:
        add(to_parts, original_to)
        add(cc_parts, original_cc)
    elif from_self and not to_parts:
        # Own message with no one else in To (e.g. Cc-only): reply to its Cc.
        add(to_parts, original_cc)

    if not to_parts and cc_parts:
        to_parts, cc_parts = cc_parts, []

    to = ", ".join(to_parts) if to_parts else None
    cc = ", ".join(cc_parts) if cc_parts else None
    if not to:
        to = _format_address_header(primary) or _format_address_header(original_from)
    return to, cc


def _header_map(headers: list[dict[str, str]] | None) -> dict[str, str]:
    return {h["name"].lower(): h.get("value", "") for h in (headers or []) if "name" in h}


_B64URL_NON_ALPHABET = re.compile(r"[^A-Za-z0-9_\-+/]")

# Charset labels commonly wrong in real mail, keyed by codecs.lookup()'s normalized
# name (#825 review). "us-ascii" is often really UTF-8, a superset that decodes pure
# ASCII identically. "iso-8859-1" is often really windows-1252, whose smart quotes
# and dashes would otherwise decode as C1 control characters (the WHATWG Encoding
# standard maps that label to windows-1252 for the same reason).
_CHARSET_ALIASES = {"ascii": "utf-8", "iso8859-1": "cp1252"}

# Most attachments.get calls one get_message/get_thread call keeps in flight. A long
# thread of large messages would otherwise fire them all at once and trip Gmail's
# per-user concurrency limit, nulling out a varying subset of bodies (#825 review).
_BODY_FETCH_CONCURRENCY = 4


def _decode_body_data(data: str | None, charset: str = "utf-8") -> str:
    """Decode a Gmail base64url body string to text.

    Inline ``body.data`` is always UTF-8, regardless of the part's own
    ``Content-Type`` charset: the Gmail API transcodes it to UTF-8 but leaves the
    original charset label on the header, so decoding with the declared charset
    would double-decode (confirmed live on PR #816: iso-8859-1 ``Caf=E9`` arrives as
    ``Caf\\xc3\\xa9``). A body fetched via ``users.messages.attachments.get`` is the
    opposite: raw bytes in the declared charset (confirmed live on #825: the same
    ``Caf=E9`` arrives as ``Caf\\xe9``), so that caller passes the part's charset.
    Common mislabels are remapped via ``_CHARSET_ALIASES``; an unknown charset, or
    one that isn't a text encoding, falls back to UTF-8.

    Missing padding is repaired. Characters outside the base64 alphabet (whitespace,
    line breaks, existing ``=``) are stripped first so they don't skew the padding
    count. Raises ``binascii.Error`` only for data no padding can repair.
    """
    if not data:
        return ""
    cleaned = _B64URL_NON_ALPHABET.sub("", data)
    raw = base64.urlsafe_b64decode(cleaned + "=" * (-len(cleaned) % 4))
    try:
        codec = codecs.lookup(charset).name
    except LookupError:
        codec = "utf-8"
    codec = _CHARSET_ALIASES.get(codec, codec)
    try:
        return raw.decode(codec, errors="replace")
    except (LookupError, UnicodeError):
        # LookupError: a codec that isn't a text encoding (e.g. "base64").
        # UnicodeError: a codec that rejects errors="replace" (e.g. "idna").
        return raw.decode("utf-8", errors="replace")


def _part_header_params(part: dict[str, Any]) -> Message:
    """The part's Content-Type / Content-Disposition headers, parsed for their params."""
    parsed = Message()
    for h in part.get("headers") or []:
        if h.get("name", "").lower() in ("content-type", "content-disposition"):
            parsed[h["name"]] = h.get("value", "")
    return parsed


def _decode_inline_part(part: dict[str, Any], errors: list[dict[str, Any]]) -> str | None:
    """Decode a part's inline body.data, recording a failure in errors."""
    try:
        return _decode_body_data((part.get("body") or {}).get("data"))
    except binascii.Error as e:
        errors.append(
            {"part_id": part.get("partId"), "mime_type": part.get("mimeType"), "error": str(e)}
        )
        return None


_BODY_SLOTS = {"text/plain": "plain", "text/html": "html"}


@dataclass
class _DeferredBody:
    """A body part Gmail delivered by attachmentId instead of inline data (#825)."""

    slot: str
    part_id: str | None
    mime_type: str
    attachment_id: str
    charset: str
    size: int
    # The first later inline part of the same type, decoded only if this fetch fails.
    fallback: dict[str, Any] | None = None


def _as_deferred_body(part: dict[str, Any], slot: str) -> _DeferredBody | None:
    """The part as a deferred body if Gmail delivered it by attachmentId with no inline
    data and it isn't marked as an attachment; else None. Headers are parsed only
    here, for the rare part that gets this far (#825 review)."""
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId")
    if not attachment_id or body.get("data"):
        return None
    headers = _part_header_params(part)
    if headers.get_content_disposition() == "attachment":
        return None
    return _DeferredBody(
        slot=slot,
        part_id=part.get("partId"),
        mime_type=part.get("mimeType", ""),
        attachment_id=attachment_id,
        charset=headers.get_content_charset() or "utf-8",
        size=body.get("size") or 0,
    )


@dataclass
class _PayloadParts:
    plain: str | None = None
    html: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    decode_errors: list[dict[str, Any]] = field(default_factory=list)
    deferred_bodies: list[_DeferredBody] = field(default_factory=list)


def _extract_bodies_and_attachments(payload: dict[str, Any]) -> _PayloadParts:
    """Walk a Gmail message payload into bodies, attachment metadata, and errors.

    A text part whose data can't be decoded is skipped and recorded in
    decode_errors rather than failing the whole message, so its headers, other body
    part, and attachments still come back; a later part of the same type can still
    fill that body.

    Gmail delivers a large text body (somewhere between ~400 KB and 3 MB) by
    ``attachmentId`` with no inline data and no filename (#825). A nameless
    text/plain or text/html part like that, not marked ``Content-Disposition:
    attachment`` and not inside an attached ``message/rfc822``, claims its body slot
    and is listed in deferred_bodies for the caller to fetch, instead of being
    reported as a nameless attachment. The first part of each type still wins; a
    later inline part of that type is kept as the fetch's fallback.
    """
    out = _PayloadParts()
    claimed: set[str] = set()
    pending: dict[str, _DeferredBody] = {}

    def walk(part: dict[str, Any], in_rfc822: bool) -> None:
        mime_type = part.get("mimeType", "")
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        data = body.get("data")
        attachment_id = body.get("attachmentId")
        slot = _BODY_SLOTS.get(mime_type)
        deferred = (
            _as_deferred_body(part, slot)
            if slot and slot not in claimed and not filename and not in_rfc822
            else None
        )

        if deferred is not None:
            claimed.add(deferred.slot)
            pending[deferred.slot] = deferred
            out.deferred_bodies.append(deferred)
        elif filename or attachment_id:
            out.attachments.append(
                {
                    "filename": filename or None,
                    "mime_type": mime_type or None,
                    "size": body.get("size"),
                    "attachment_id": attachment_id,
                }
            )
        elif data and slot and slot not in claimed:
            text = _decode_inline_part(part, out.decode_errors)
            if text is not None:
                claimed.add(slot)
                setattr(out, slot, text)
        elif data and slot in pending and pending[slot].fallback is None:
            pending[slot].fallback = part

        for child in part.get("parts") or []:
            walk(child, in_rfc822 or mime_type == "message/rfc822")

    walk(payload or {}, False)
    return out


async def _fetch_deferred_body(
    gmail_service: Any, message_id: str, deferred: _DeferredBody, limit: asyncio.Semaphore
) -> dict[str, Any]:
    """Fetch and decode one body part Gmail delivered by attachmentId (#825).

    Returns {"text": str} on success, or {"fetch_error": ...} / {"decode_error": ...}.
    """
    async with limit:
        try:
            result = await execute_in_thread(
                gmail_service.users()
                .messages()
                .attachments()
                .get(userId=_USER, messageId=message_id, id=deferred.attachment_id)
                .execute,
                gmail_service,
            )
        except Exception as e:
            return {"fetch_error": str(e)}
    data = (result or {}).get("data")
    if not data:
        return {"fetch_error": "attachments.get returned no data"}
    try:
        return {"text": _decode_body_data(data, deferred.charset)}
    except binascii.Error as e:
        return {"decode_error": str(e)}


@dataclass
class _PendingMessage:
    """A message shaped except for its deferred bodies, which aren't fetched yet."""

    shaped: dict[str, Any]
    parts: _PayloadParts | None


def _start_shaping(msg: dict[str, Any], *, include_body: bool = True) -> _PendingMessage:
    payload = msg.get("payload") or {}
    headers = _header_map(payload.get("headers"))
    shaped: dict[str, Any] = {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "snippet": msg.get("snippet"),
        "label_ids": msg.get("labelIds") or [],
        "internal_date": msg.get("internalDate"),
        "size_estimate": msg.get("sizeEstimate"),
        "headers": {
            "from": headers.get("from"),
            # Surfaced because reply_to_message prefers it over From when replying
            # to someone else's message (#791).
            "reply_to": headers.get("reply-to"),
            "to": headers.get("to"),
            "cc": headers.get("cc"),
            "bcc": headers.get("bcc"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
            "message_id": headers.get("message-id"),
            "in_reply_to": headers.get("in-reply-to"),
            "references": headers.get("references"),
        },
    }
    parts = _extract_bodies_and_attachments(payload) if include_body else None
    return _PendingMessage(shaped, parts)


def _deferred_body_bytes(pending: list[_PendingMessage]) -> int:
    """Total decoded size of every not-yet-fetched body.

    A lower bound on those bodies' serialized size: json.dumps escapes non-ASCII,
    so every byte of body text serializes to at least one character. Lets a caller
    reject an over-cap response before downloading anything (#825 review).
    """
    return sum(d.size for p in pending if p.parts for d in p.parts.deferred_bodies)


async def _finish_shaping(
    gmail_service: Any, pending: _PendingMessage, limit: asyncio.Semaphore
) -> dict[str, Any]:
    shaped, parts = pending.shaped, pending.parts
    if parts is None:
        return shaped
    fetch_errors: list[dict[str, Any]] = []
    fetched = await gather_with_fallback(
        parts.deferred_bodies,
        lambda d: _fetch_deferred_body(gmail_service, shaped["id"], d, limit),
        lambda _d, exc: {"fetch_error": str(exc)},
    )
    for deferred, outcome in zip(parts.deferred_bodies, fetched, strict=True):
        if "text" in outcome:
            setattr(parts, deferred.slot, outcome["text"])
            continue
        where = {
            "part_id": deferred.part_id,
            "mime_type": deferred.mime_type,
            "attachment_id": deferred.attachment_id,
        }
        if "decode_error" in outcome:
            parts.decode_errors.append({**where, "error": outcome["decode_error"]})
        else:
            fetch_errors.append({**where, "error": outcome["fetch_error"]})
        if deferred.fallback is not None:
            setattr(
                parts, deferred.slot, _decode_inline_part(deferred.fallback, parts.decode_errors)
            )
    shaped["body_plain"] = parts.plain
    shaped["body_html"] = parts.html
    shaped["attachments"] = parts.attachments
    if parts.decode_errors:
        shaped["body_decode_errors"] = parts.decode_errors
    if fetch_errors:
        shaped["body_fetch_errors"] = fetch_errors
    return shaped


async def _finish_shaping_all(
    gmail_service: Any, pending: list[_PendingMessage]
) -> list[dict[str, Any]]:
    limit = asyncio.Semaphore(_BODY_FETCH_CONCURRENCY)
    return list(await asyncio.gather(*(_finish_shaping(gmail_service, p, limit) for p in pending)))


def _manifest_body_errors(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Body fetch/decode errors to surface in a local_path manifest, so a failed body
    doesn't look like success unless the caller opens the written file (#825 review)."""
    out: dict[str, Any] = {}
    for key in ("body_fetch_errors", "body_decode_errors"):
        entries = [{"message_id": m["id"], **e} for m in messages for e in m.get(key, [])]
        if entries:
            out[key] = entries
    return out


def _shape_label(label: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": label["id"],
        "name": label.get("name", ""),
        "type": label.get("type"),
        "message_list_visibility": label.get("messageListVisibility"),
        "label_list_visibility": label.get("labelListVisibility"),
    }


def _read_attachment_bytes(att: dict[str, Any]) -> tuple[str, str, bytes]:
    """Resolve an attachment dict to (filename, mime_type, raw bytes)."""
    filename = att.get("filename") or "attachment"
    mime_type = att.get("mime_type") or "application/octet-stream"
    if att.get("local_path"):
        path = Path(att["local_path"])
        return filename if att.get("filename") else path.name, mime_type, path.read_bytes()
    if att.get("content_base64"):
        return filename, mime_type, base64.b64decode(att["content_base64"])
    raise ValueError(
        "Each attachment needs either local_path or content_base64 "
        "(plus optional filename and mime_type)."
    )


def _build_raw_message(
    *,
    to: str | list[str],
    subject: str,
    body: str,
    body_html: str | None = None,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Build a base64url-encoded RFC 2822 message for the Gmail API `raw` field."""

    to_str = _format_address_header(to) or ""
    has_attachments = bool(attachments)
    use_alternative = body_html is not None

    if has_attachments:
        root: MIMEMultipart = MIMEMultipart("mixed")
        if use_alternative:
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body, "plain", "utf-8"))
            alt.attach(MIMEText(body_html, "html", "utf-8"))
            root.attach(alt)
        else:
            root.attach(MIMEText(body, "plain", "utf-8"))
        for att in attachments or []:
            filename, mime_type, raw = _read_attachment_bytes(att)
            maintype, _, subtype = mime_type.partition("/")
            part = MIMEApplication(raw, _subtype=subtype or "octet-stream")
            if maintype and maintype != "application":
                part.set_type(mime_type)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            root.attach(part)
        msg = root
    elif use_alternative:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["To"] = to_str
    msg["Subject"] = subject
    if cc_str := _format_address_header(cc):
        msg["Cc"] = cc_str
    if bcc_str := _format_address_header(bcc):
        msg["Bcc"] = bcc_str
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Messages", readOnlyHint=True))
    async def list_messages(
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 50,
        page_token: str | None = None,
        include_spam_trash: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        List messages in the authenticated user's mailbox.

        Args:
            query: Gmail search syntax filter, e.g. 'from:alice@example.com is:unread'.
            label_ids: Only return messages that have all of these label IDs
                       (e.g. ['INBOX', 'UNREAD']).
            max_results: Maximum number of messages to return (default 50, max 500).
            page_token: Continuation token from a previous response for pagination.
            include_spam_trash: When True, include messages from SPAM and TRASH.

        Returns:
            Dictionary with messages (id, thread_id), optional next_page_token, and
            result_size_estimate. Use get_message for headers/body. On API failure,
            returns {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        max_results = clamp_max_results(max_results, _GMAIL_LIST_MAX)
        kwargs: dict[str, Any] = {
            "userId": _USER,
            "maxResults": max_results,
            "includeSpamTrash": include_spam_trash,
        }
        if query:
            kwargs["q"] = query
        if label_ids:
            kwargs["labelIds"] = label_ids
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = await execute_in_thread(
                lc.gmail_service.users().messages().list(**kwargs).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        messages = [
            {"id": m["id"], "thread_id": m.get("threadId")} for m in result.get("messages", [])
        ]
        out: dict[str, Any] = {
            "messages": messages,
            "result_size_estimate": result.get("resultSizeEstimate"),
        }
        if npt := result.get("nextPageToken"):
            out["next_page_token"] = npt
        enforce_response_size_cap(
            out,
            tool_name="list_messages",
            hint="Lower max_results and paginate via next_page_token, or ",
            local_path_available=False,
        )
        return out

    @tool(annotations=ToolAnnotations(title="Get Message", readOnlyHint=True))
    async def get_message(
        message_id: str, local_path: str | None = None, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Fetch a single message by ID, including headers, body, and attachment metadata.

        Args:
            message_id: The Gmail message ID (from list_messages or get_thread).
            local_path: Optional local filesystem path (file or directory) to write the
                        message JSON to instead of returning it inline. Bypasses the
                        response-size cap, for messages with very large bodies.

        Returns:
            Message with id, thread_id, snippet, label_ids, headers (from/to/cc/bcc/
            subject/date/message_id), body_plain, body_html, and attachments metadata
            (filename, mime_type, size, attachment_id). A large body that Gmail
            delivers separately is fetched and returned in body_plain/body_html like
            any other. A text part whose data can't be decoded leaves its body null
            and is listed in body_decode_errors; a separately delivered body that
            can't be fetched leaves its body null and is listed in body_fetch_errors
            (both: part_id, mime_type, error, plus attachment_id for a separately
            delivered part; present only when non-empty). Raises an error naming the
            size if the message is over the response-size cap and local_path is not
            set; a separately delivered body already over the cap raises before
            being downloaded. If local_path is set, returns {local_path, message_id,
            bytes_written} instead, plus body_fetch_errors / body_decode_errors
            (each entry with message_id) when present. On API failure,
            {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            msg = await execute_in_thread(
                lc.gmail_service.users()
                .messages()
                .get(userId=_USER, id=message_id, format="full")
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        hint = "The message body is large. "
        pending = [_start_shaping(msg, include_body=True)]
        if not local_path:
            enforce_response_size_floor(
                _deferred_body_bytes(pending), tool_name="get_message", hint=hint
            )
        [shaped] = await _finish_shaping_all(lc.gmail_service, pending)
        if local_path:
            return await write_capped_result_to_disk(
                shaped,
                local_path,
                default_filename=f"message_{message_id}.json",
                manifest_extra={"message_id": message_id, **_manifest_body_errors([shaped])},
            )
        enforce_response_size_cap(shaped, tool_name="get_message", hint=hint)
        return shaped

    @tool(annotations=ToolAnnotations(title="List Threads", readOnlyHint=True))
    async def list_threads(
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 50,
        page_token: str | None = None,
        include_spam_trash: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        List conversation threads in the authenticated user's mailbox.

        Args:
            query: Gmail search syntax filter, e.g. 'subject:invoice newer_than:7d'.
            label_ids: Only return threads that have all of these label IDs.
            max_results: Maximum number of threads to return (default 50, max 500).
            page_token: Continuation token from a previous response for pagination.
            include_spam_trash: When True, include threads from SPAM and TRASH.

        Returns:
            Dictionary with threads (id, snippet, history_id), optional next_page_token,
            and result_size_estimate. Use get_thread for full messages. On API failure,
            returns {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        max_results = clamp_max_results(max_results, _GMAIL_LIST_MAX)
        kwargs: dict[str, Any] = {
            "userId": _USER,
            "maxResults": max_results,
            "includeSpamTrash": include_spam_trash,
        }
        if query:
            kwargs["q"] = query
        if label_ids:
            kwargs["labelIds"] = label_ids
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = await execute_in_thread(
                lc.gmail_service.users().threads().list(**kwargs).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        threads = [
            {
                "id": t["id"],
                "snippet": t.get("snippet"),
                "history_id": t.get("historyId"),
            }
            for t in result.get("threads", [])
        ]
        out: dict[str, Any] = {
            "threads": threads,
            "result_size_estimate": result.get("resultSizeEstimate"),
        }
        if npt := result.get("nextPageToken"):
            out["next_page_token"] = npt
        enforce_response_size_cap(
            out,
            tool_name="list_threads",
            hint="Lower max_results and paginate via next_page_token, or ",
            local_path_available=False,
        )
        return out

    @tool(annotations=ToolAnnotations(title="Get Thread", readOnlyHint=True))
    async def get_thread(
        thread_id: str, local_path: str | None = None, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Fetch all messages in a conversation thread.

        Args:
            thread_id: The Gmail thread ID (from list_threads or a message's thread_id).
            local_path: Optional local filesystem path (file or directory) to write the
                        thread JSON to instead of returning it inline. Bypasses the
                        response-size cap, for threads with very large bodies.

        Returns:
            Thread with id, snippet, history_id, and messages (same shape as get_message).
            Raises an error naming the size if the thread is over the response-size cap
            and local_path is not set. If local_path is set, returns {local_path,
            thread_id, message_count, bytes_written} instead, plus body_fetch_errors /
            body_decode_errors (each entry with message_id) when present. On API
            failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            thread = await execute_in_thread(
                lc.gmail_service.users()
                .threads()
                .get(userId=_USER, id=thread_id, format="full")
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        hint = "The thread is large; use get_message on individual IDs. "
        pending = [_start_shaping(m, include_body=True) for m in thread.get("messages", [])]
        if not local_path:
            enforce_response_size_floor(
                _deferred_body_bytes(pending), tool_name="get_thread", hint=hint
            )
        shaped = {
            "id": thread["id"],
            "snippet": thread.get("snippet"),
            "history_id": thread.get("historyId"),
            "messages": await _finish_shaping_all(lc.gmail_service, pending),
        }
        if local_path:
            return await write_capped_result_to_disk(
                shaped,
                local_path,
                default_filename=f"thread_{thread_id}.json",
                manifest_extra={
                    "thread_id": thread_id,
                    "message_count": len(shaped["messages"]),
                    **_manifest_body_errors(shaped["messages"]),
                },
            )
        enforce_response_size_cap(shaped, tool_name="get_thread", hint=hint)
        return shaped

    @tool(annotations=ToolAnnotations(title="List Labels", readOnlyHint=True))
    async def list_labels(ctx: Context = None) -> list[dict[str, Any]] | dict[str, Any]:
        """
        List all labels in the authenticated user's mailbox (system and user-defined).

        Returns:
            List of labels with id, name, type, message_list_visibility, and
            label_list_visibility. On API failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            result = await execute_in_thread(
                lc.gmail_service.users().labels().list(userId=_USER).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        return [_shape_label(label) for label in result.get("labels", [])]

    @tool(annotations=ToolAnnotations(title="Send Message", destructiveHint=True))
    async def send_message(
        to: str | list[str],
        subject: str,
        body: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        body_html: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Send a new email message.

        Args:
            to: Recipient email address, or a list of addresses.
            subject: Email subject line.
            body: Plain-text body.
            cc: Optional CC address or list of addresses.
            bcc: Optional BCC address or list of addresses.
            body_html: Optional HTML body (sent alongside the plain-text body).
            attachments: Optional list of attachment dicts. Each needs either
                         local_path or content_base64, plus optional filename and
                         mime_type (default application/octet-stream).

        Returns:
            Sent message id, thread_id, and label_ids. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            raw = _build_raw_message(
                to=to,
                subject=subject,
                body=body,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                attachments=attachments,
            )
            sent = await execute_in_thread(
                lc.gmail_service.users().messages().send(userId=_USER, body={"raw": raw}).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Sent message %s", sent.get("id"))
        return {
            "id": sent["id"],
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds") or [],
        }

    @tool(annotations=ToolAnnotations(title="Create Draft", destructiveHint=True))
    async def create_draft(
        to: str | list[str],
        subject: str,
        body: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        body_html: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a draft email without sending it.

        Args:
            to: Recipient email address, or a list of addresses.
            subject: Email subject line.
            body: Plain-text body.
            cc: Optional CC address or list of addresses.
            bcc: Optional BCC address or list of addresses.
            body_html: Optional HTML body (sent alongside the plain-text body).
            attachments: Optional list of attachment dicts. Each needs either
                         local_path or content_base64, plus optional filename and
                         mime_type.

        Returns:
            Draft id and nested message id/thread_id. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            raw = _build_raw_message(
                to=to,
                subject=subject,
                body=body,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                attachments=attachments,
            )
            draft = await execute_in_thread(
                lc.gmail_service.users()
                .drafts()
                .create(userId=_USER, body={"message": {"raw": raw}})
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        message = draft.get("message") or {}
        logger.debug("Created draft %s", draft.get("id"))
        return {
            "id": draft["id"],
            "message": {
                "id": message.get("id"),
                "thread_id": message.get("threadId"),
                "label_ids": message.get("labelIds") or [],
            },
        }

    @tool(annotations=ToolAnnotations(title="Send Draft", destructiveHint=True))
    async def send_draft(draft_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Send an existing draft by ID.

        Args:
            draft_id: The draft ID returned by create_draft.

        Returns:
            Sent message id, thread_id, and label_ids. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            sent = await execute_in_thread(
                lc.gmail_service.users().drafts().send(userId=_USER, body={"id": draft_id}).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Sent draft %s as message %s", draft_id, sent.get("id"))
        return {
            "id": sent["id"],
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds") or [],
        }

    @tool(annotations=ToolAnnotations(title="Reply to Message", destructiveHint=True))
    async def reply_to_message(
        message_id: str,
        body: str,
        body_html: str | None = None,
        reply_all: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Send a reply in an existing thread.

        Fetches the original message for Subject / Message-ID / References headers
        and sets the reply's threadId so Gmail groups it correctly.

        Args:
            message_id: ID of the message being replied to.
            body: Plain-text reply body.
            body_html: Optional HTML reply body.
            reply_all: When True, also include the original To and Cc recipients
                       in addition to the reply target.

        Recipients follow standard mail-client rules: the reply goes to the
        original's Reply-To if it has one, otherwise its From. Replying to a
        message you sent yourself goes to that message's original To (or its Cc,
        if nobody else was in To) instead. Your own addresses, including send-as
        aliases, are left off the recipients unless nobody else is on the message.

        Returns:
            Sent message id, thread_id, and label_ids. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            original = await execute_in_thread(
                lc.gmail_service.users()
                .messages()
                .get(userId=_USER, id=message_id, format="metadata")
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        headers = _header_map((original.get("payload") or {}).get("headers"))
        original_from = headers.get("from", "")
        original_to = headers.get("to", "")
        original_cc = headers.get("cc", "")
        subject = headers.get("subject") or ""
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        elif not subject:
            subject = "Re:"

        original_message_id = headers.get("message-id", "")
        prior_refs = headers.get("references", "")
        if original_message_id and prior_refs:
            references = f"{prior_refs} {original_message_id}"
        else:
            references = prior_refs or original_message_id or None

        # The mailbox's own addresses are needed for plain replies too: to drop them
        # from the recipients, and to recognize its own message when it lacks SENT.
        to, cc = _reply_recipients(
            original_from=original_from,
            original_reply_to=headers.get("reply-to", ""),
            original_to=original_to,
            original_cc=original_cc,
            sent_label="SENT" in (original.get("labelIds") or []),
            reply_all=reply_all,
            own=await _own_addresses(lc.gmail_service),
        )

        if not to:
            return {"error": "Original message has no From header to reply to."}

        try:
            raw = _build_raw_message(
                to=to,
                subject=subject,
                body=body,
                body_html=body_html,
                cc=cc,
                in_reply_to=original_message_id or None,
                references=references,
            )
            sent = await execute_in_thread(
                lc.gmail_service.users()
                .messages()
                .send(
                    userId=_USER,
                    body={"raw": raw, "threadId": original.get("threadId")},
                )
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Replied to message %s with %s", message_id, sent.get("id"))
        return {
            "id": sent["id"],
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds") or [],
        }

    @tool(annotations=ToolAnnotations(title="Modify Labels", destructiveHint=True))
    async def modify_labels(
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
        message_id: str | None = None,
        thread_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Add or remove labels on a message or an entire thread.

        Common label IDs: INBOX (archive = remove INBOX), UNREAD (mark read =
        remove UNREAD; mark unread = add UNREAD), STARRED, IMPORTANT, TRASH, SPAM.
        User labels use their id from list_labels.

        Args:
            add_label_ids: Label IDs to add.
            remove_label_ids: Label IDs to remove.
            message_id: Target a single message. Provide message_id or thread_id,
                        not both.
            thread_id: Target every message in a thread. Provide message_id or
                       thread_id, not both.

        Returns:
            For a message: id, thread_id, label_ids. For a thread: id and messages
            (id + label_ids each). On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        if bool(message_id) == bool(thread_id):
            return {
                "error": "Provide exactly one of message_id or thread_id.",
            }
        if not add_label_ids and not remove_label_ids:
            return {"error": "Provide at least one of add_label_ids or remove_label_ids."}

        body: dict[str, Any] = {}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids

        lc = ctx.request_context.lifespan_context
        try:
            if message_id:
                result = await execute_in_thread(
                    lc.gmail_service.users()
                    .messages()
                    .modify(userId=_USER, id=message_id, body=body)
                    .execute,
                    lc.gmail_service,
                )
                return {
                    "id": result["id"],
                    "thread_id": result.get("threadId"),
                    "label_ids": result.get("labelIds") or [],
                }

            result = await execute_in_thread(
                lc.gmail_service.users()
                .threads()
                .modify(userId=_USER, id=thread_id, body=body)
                .execute,
                lc.gmail_service,
            )
            return {
                "id": result["id"],
                "messages": [
                    {
                        "id": m["id"],
                        "label_ids": m.get("labelIds") or [],
                    }
                    for m in result.get("messages", [])
                ],
            }
        except Exception as e:
            return {"error": str(e)}

    @tool(annotations=ToolAnnotations(title="Trash Message", destructiveHint=True))
    async def trash_message(message_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Move a message to trash (recoverable).

        Permanent delete is intentionally not exposed — it requires the full
        https://mail.google.com/ scope, which this server does not request.

        Args:
            message_id: The Gmail message ID to trash.

        Returns:
            Message id, thread_id, label_ids, and action 'trashed'. On failure,
            {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            result = await execute_in_thread(
                lc.gmail_service.users().messages().trash(userId=_USER, id=message_id).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        return {
            "id": result["id"],
            "thread_id": result.get("threadId"),
            "label_ids": result.get("labelIds") or [],
            "action": "trashed",
        }
