"""Gmail tools — messages, threads, labels, drafts, and organization primitives."""

import asyncio
import base64
import binascii
import codecs
import functools
import logging
import os
import re
import time
from dataclasses import dataclass, field
from email import encoders, message_from_bytes, policy
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesHeaderParser
from email.utils import formataddr, getaddresses
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from ..auth import execute_in_thread, get_gmail_unauthorized_message
from ..local_files import check_read, check_write
from ..reauth import _session as reauth_session
from .concurrency import gather_with_fallback
from .mime_types import OCTET_STREAM, guess_mime_type
from .response_limits import (
    clamp_max_results,
    enforce_response_size_cap,
    enforce_response_size_floor,
    write_capped_result_to_disk,
)

logger = logging.getLogger(__name__)

_USER = "me"
_GMAIL_LIST_MAX = 500

_GMAIL_SEND_MODES = ("confirm", "direct")
_DEFAULT_WARN_RECIPIENTS = 10


def _gmail_send_mode() -> str:
    """GMAIL_SEND (#1081): 'confirm' (default) or 'direct'. An unrecognized value
    falls back to 'confirm', the mode that can't deliver mail by mistake."""
    raw = os.environ.get("GMAIL_SEND", "confirm").strip().lower() or "confirm"
    if raw not in _GMAIL_SEND_MODES:
        logger.warning("Ignoring GMAIL_SEND=%r: expected confirm or direct; using confirm", raw)
        return "confirm"
    return raw


def _warn_recipients_threshold() -> int:
    """GMAIL_SEND_WARN_RECIPIENTS (#1081): flag a send to more unique recipients
    than this. Default 10."""
    raw = os.environ.get("GMAIL_SEND_WARN_RECIPIENTS")
    if raw is None or not raw.strip():
        return _DEFAULT_WARN_RECIPIENTS
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        logger.warning(
            "Ignoring GMAIL_SEND_WARN_RECIPIENTS=%r: not a non-negative integer; using %d",
            raw,
            _DEFAULT_WARN_RECIPIENTS,
        )
        return _DEFAULT_WARN_RECIPIENTS
    return value


GMAIL_SEND = _gmail_send_mode()
GMAIL_SEND_WARN_RECIPIENTS = _warn_recipients_threshold()


def _format_address_header(value: str | list[str] | None) -> str | None:
    """Build a To/Cc/Bcc header with RFC 2047-safe display names via formataddr."""
    if value is None:
        return None
    chunks = value if isinstance(value, list) else [value]
    formatted = [formataddr((name, addr)) for name, addr in getaddresses(chunks) if addr]
    return ", ".join(formatted) if formatted else None


_OWN_ADDRESSES_UNRESOLVED = (
    "Couldn't look up this mailbox's own address, so it may be among the recipients, "
    "and a reply to your own message may have gone back to you."
)
_ALIASES_UNRESOLVED = (
    "Couldn't list this mailbox's send-as aliases, so only its primary address was "
    "left off the recipients."
)
_ALIASES_EMPTY = (
    "Gmail listed no send-as addresses for this mailbox, so only its primary address "
    "was left off the recipients."
)

# How long a resolved own-address set is reused. Send-as aliases can be added or
# removed while the server runs (PR #928 QA), so the cache expires instead of
# living for the whole connection; refresh_cache also clears it.
_OWN_ADDRESSES_TTL_SECONDS = 600


async def _own_addresses(lc: Any) -> tuple[set[str], str | None]:
    """Every address the authenticated mailbox sends as, lowercased, plus a warning
    when that set is incomplete (#802).

    Reads the send-as aliases (users.settings.sendAs.list, which includes the primary
    address), falling back to just the primary address (users.getProfile) if the
    alias list can't be read or lists nothing. Empty, with a warning, if neither
    works. A complete answer is cached on the connection's lifespan context for
    _OWN_ADDRESSES_TTL_SECONDS (cleared by refresh_cache); an incomplete one isn't
    cached, so the next call retries.

    Also records the mailbox's primary address on lc.gmail_primary_address whenever
    either lookup names it, for _recipient_flags' organization check (#1081).
    """
    cached = getattr(lc, "gmail_own_addresses", None)
    if isinstance(cached, tuple) and time.monotonic() - cached[1] < _OWN_ADDRESSES_TTL_SECONDS:
        return set(cached[0]), None
    gmail_service = lc.gmail_service
    alias_warning = _ALIASES_UNRESOLVED
    try:
        result = await execute_in_thread(
            gmail_service.users().settings().sendAs().list(userId=_USER).execute,
            gmail_service,
        )
        entries = [
            a
            for a in (result or {}).get("sendAs") or []
            if isinstance(a.get("sendAsEmail"), str) and a["sendAsEmail"].strip()
        ]
        aliases = {a["sendAsEmail"].strip().lower() for a in entries}
        if aliases:
            primary = next((a for a in entries if a.get("isPrimary") is True), None)
            if primary is not None:
                lc.gmail_primary_address = primary["sendAsEmail"].strip().lower()
            lc.gmail_own_addresses = (frozenset(aliases), time.monotonic())
            return aliases, None
        logger.warning("users.settings.sendAs.list returned no send-as addresses")
        alias_warning = _ALIASES_EMPTY
    except Exception:
        logger.warning("Could not list send-as aliases", exc_info=True)
    try:
        profile = await execute_in_thread(
            gmail_service.users().getProfile(userId=_USER).execute,
            gmail_service,
        )
    except Exception:
        logger.warning("Could not resolve mailbox email via getProfile", exc_info=True)
        return set(), _OWN_ADDRESSES_UNRESOLVED
    email = (profile or {}).get("emailAddress")
    if isinstance(email, str) and email.strip():
        lc.gmail_primary_address = email.strip().lower()
        return {email.strip().lower()}, alias_warning
    logger.warning("users.getProfile returned no emailAddress")
    return set(), _OWN_ADDRESSES_UNRESOLVED


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


def _codec_for(charset: str) -> str:
    """The codec a declared charset decodes with: its normalized codecs.lookup() name,
    remapped via _CHARSET_ALIASES, or UTF-8 for an unknown name."""
    try:
        codec = codecs.lookup(charset).name
    except LookupError:
        return "utf-8"
    return _CHARSET_ALIASES.get(codec, codec)


# Codecs where every encoded byte serializes to at least one JSON character (#825,
# PR #829 QA round 2): ASCII-compatible and stateless, so an ASCII byte decodes to one
# character and every multi-byte sequence (or invalid byte) to a non-ASCII one, which
# json.dumps escapes to 6+ characters. That makes a part's byte size a lower bound on
# its serialized size. Deliberately excluded: UTF-16/32 (2-4 bytes per ASCII
# character), and stateful codecs whose escape/shift sequences decode to nothing
# (UTF-7, iso-2022-*, hz). Anything not listed is simply left out of the bound.
_SIZE_FLOOR_CODEC_PREFIXES = ("cp", "iso8859-", "koi8-", "mac-")
_SIZE_FLOOR_CODECS = frozenset(
    {
        "utf-8",
        "tis-620",
        "hp-roman8",
        "kz1048",
        "ptcp154",
        "big5",
        "big5hkscs",
        "euc_jp",
        "euc_jis_2004",
        "euc_jisx0213",
        "euc_kr",
        "gb2312",
        "gbk",
        "gb18030",
        "johab",
        "shift_jis",
        "shift_jis_2004",
        "shift_jisx0213",
    }
)


def _bytes_bound_serialized_size(codec: str) -> bool:
    return codec in _SIZE_FLOOR_CODECS or codec.startswith(_SIZE_FLOOR_CODEC_PREFIXES)


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
        return raw.decode(_codec_for(charset), errors="replace")
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


# The headers a shaped message surfaces, as (result key, header name). Also the
# metadataHeaders filter for a body-less fetch, so it requests exactly these (#793).
_SHAPED_HEADERS = (
    ("from", "From"),
    # Surfaced because reply_to_message prefers it over From when replying to
    # someone else's message (#791).
    ("reply_to", "Reply-To"),
    ("to", "To"),
    ("cc", "Cc"),
    ("bcc", "Bcc"),
    ("subject", "Subject"),
    ("date", "Date"),
    ("message_id", "Message-ID"),
    ("in_reply_to", "In-Reply-To"),
    ("references", "References"),
)


def _get_format_kwargs(include_body: bool) -> dict[str, Any]:
    """The format kwargs for messages.get / threads.get. 'metadata' returns headers,
    snippet, labels, and size but no payload parts, so no body or attachment data;
    metadataHeaders keeps it from also returning every Received/ARC/DKIM header
    that shaping would drop (#793)."""
    if include_body:
        return {"format": "full"}
    return {"format": "metadata", "metadataHeaders": [name for _, name in _SHAPED_HEADERS]}


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
        "headers": {key: headers.get(name.lower()) for key, name in _SHAPED_HEADERS},
    }
    parts = _extract_bodies_and_attachments(payload) if include_body else None
    return _PendingMessage(shaped, parts)


def _deferred_body_bytes(pending: list[_PendingMessage]) -> int:
    """A lower bound on the serialized size of every not-yet-fetched body.

    Sums the encoded byte size of each part whose codec guarantees at least one JSON
    character per byte (_bytes_bound_serialized_size); any other part counts as 0.
    Lets a caller reject an over-cap response before downloading anything (#825
    review). Undercounting only skips this early exit: the post-fetch cap check
    still applies.
    """
    return sum(
        d.size
        for p in pending
        if p.parts
        for d in p.parts.deferred_bodies
        if _bytes_bound_serialized_size(_codec_for(d.charset))
    )


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


# A type/subtype with both halves non-empty. "application/" or "/pdf" would
# otherwise go out verbatim as a broken Content-Type (PR #928 QA round 2).
_MIME_TYPE_RE = re.compile(r"[^/\s;]+/[^/\s;]+\Z")


def _guess_attachment_mime_type(filename: str) -> str:
    """The attachment's MIME type from its filename extension (#802), or
    application/octet-stream when unknown.

    A compressed file gets its compression type, not the type of what's inside it.
    A guessed message/* or multipart/* type (.eml, .mht) also falls back to
    application/octet-stream: those types forbid the base64 encoding every
    attachment is sent with (RFC 2046 §5.2.1), and re-parsing the file into a real
    message/rfc822 part could alter bytes the caller never asked to change (PR #928
    QA).
    """
    mime_type = guess_mime_type(filename)
    if mime_type.partition("/")[0] in ("message", "multipart"):
        return OCTET_STREAM
    return mime_type


def _read_attachment_bytes(att: dict[str, Any]) -> tuple[str, str | None, bytes]:
    """Resolve an attachment dict to (filename, explicit mime_type or None, raw
    bytes). Reads local_path from disk, so it runs off the event loop (via
    _compose_raw)."""
    if att.get("local_path"):
        # The caller's own name, not the resolved one: a symlink keeps its link name.
        filename = att.get("filename") or Path(att["local_path"]).name
        data = check_read(att["local_path"]).read_bytes()
    elif att.get("content_base64"):
        filename = att.get("filename") or "attachment"
        data = base64.b64decode(att["content_base64"])
    else:
        raise ValueError(
            "Each attachment needs either local_path or content_base64 "
            "(plus optional filename and mime_type)."
        )
    return filename, att.get("mime_type") or None, data


def _attachment_part(filename: str, explicit_mime_type: str | None, raw: bytes) -> Message:
    """Build one attachment's MIME part.

    An explicit mime_type is used as given, parameters included (e.g.
    "text/plain; charset=iso-8859-1"); otherwise the type is guessed from the
    filename. A text/* part without a charset gets charset=utf-8 when its bytes are
    valid UTF-8, since a text part with no charset reads as US-ASCII (RFC 2046
    §4.1.2) and non-ASCII text would show as mojibake when previewed inline (PR #928
    QA). A guessed text/* type whose bytes aren't UTF-8 is sent as
    application/octet-stream instead, as before #802; an explicit one is left
    alone. An explicit message/rfc822 is attached as a real message part; any other
    explicit message/* or multipart/* type raises ValueError, since it can't be
    sent base64-encoded.
    """
    params: list[tuple[str, str]] = []
    if explicit_mime_type:
        if not _MIME_TYPE_RE.match(explicit_mime_type.partition(";")[0].strip()):
            raise ValueError(
                f"Attachment mime_type {explicit_mime_type!r} isn't a type/subtype "
                "such as 'application/pdf'."
            )
        header = Message()
        header["Content-Type"] = explicit_mime_type
        content_type = header.get_content_type()
        params = [(k, v) for k, v in (header.get_params() or [])[1:] if isinstance(v, str)]
    else:
        content_type = _guess_attachment_mime_type(filename)
    maintype, _, subtype = content_type.partition("/")

    if content_type == "message/rfc822":
        part: Message = MIMEMessage(message_from_bytes(raw))
    elif maintype in ("message", "multipart"):
        raise ValueError(
            f"Attachment mime_type {content_type!r} can't be sent as an attachment. "
            "Omit mime_type, or use application/octet-stream."
        )
    else:
        if maintype == "text" and not any(k.lower() == "charset" for k, _ in params):
            try:
                raw.decode("utf-8")
                params.append(("charset", "utf-8"))
            except UnicodeDecodeError:
                if not explicit_mime_type:
                    maintype, subtype = "application", "octet-stream"
        part = MIMEBase(maintype, subtype)
        for key, value in params:
            part.set_param(key, value)
        part.set_payload(raw)
        encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    return part


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
    from_: str | None = None,
    attachment_parts: list[Message] | None = None,
    inline_parts: list[Message] | None = None,
) -> str:
    """Build a base64url-encoded RFC 2822 message for the Gmail API `raw` field.

    For update_draft: from_ is a From address, encoded like To. attachment_parts are
    already-built MIME parts, attached before any `attachments`. inline_parts (each
    with a Content-ID) go in a multipart/related with body_html, so its cid:
    references resolve; with no body_html they're ordinary attachments.
    """

    to_str = _format_address_header(to) or ""
    html_part: Message | None = None
    if body_html is not None:
        html_part = MIMEText(body_html, "html", "utf-8")
        if inline_parts:
            related = MIMEMultipart("related")
            related.attach(html_part)
            for part in inline_parts:
                related.attach(part)
            html_part = related
    trailing = [*(attachment_parts or []), *([] if html_part else inline_parts or [])]

    if attachments or trailing:
        root: MIMEMultipart = MIMEMultipart("mixed")
        if html_part:
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body, "plain", "utf-8"))
            alt.attach(html_part)
            root.attach(alt)
        else:
            root.attach(MIMEText(body, "plain", "utf-8"))
        for part in trailing:
            root.attach(part)
        for att in attachments or []:
            root.attach(_attachment_part(*_read_attachment_bytes(att)))
        msg = root
    elif html_part:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(html_part)
    else:
        msg = MIMEText(body, "plain", "utf-8")

    if from_str := _format_address_header(from_):
        msg["From"] = from_str
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


async def _compose_raw(**kwargs: Any) -> str:
    """_build_raw_message off the event loop: it reads attachment files from disk and
    base64-encodes them, which would stall concurrent tool calls (#802)."""
    return await asyncio.to_thread(functools.partial(_build_raw_message, **kwargs))


def _list_kwargs(
    *,
    query: str | None,
    label_ids: list[str] | None,
    max_results: int,
    page_token: str | None,
    include_spam_trash: bool,
) -> dict[str, Any]:
    """The messages.list / threads.list / drafts.list kwargs shared by the list tools.
    drafts.list takes no labelIds; list_drafts passes label_ids=None."""
    kwargs: dict[str, Any] = {
        "userId": _USER,
        "maxResults": clamp_max_results(max_results, _GMAIL_LIST_MAX),
        "includeSpamTrash": include_spam_trash,
    }
    if query:
        kwargs["q"] = query
    if label_ids:
        kwargs["labelIds"] = label_ids
    if page_token:
        kwargs["pageToken"] = page_token
    return kwargs


def _list_page(
    result: dict[str, Any], key: str, items: list[dict[str, Any]], tool_name: str
) -> dict[str, Any]:
    """Shape one list page: the items under `key`, result_size_estimate, and
    next_page_token when there is one, checked against the response-size cap."""
    out: dict[str, Any] = {key: items, "result_size_estimate": result.get("resultSizeEstimate")}
    if npt := result.get("nextPageToken"):
        out["next_page_token"] = npt
    enforce_response_size_cap(
        out,
        tool_name=tool_name,
        hint="Lower max_results and paginate via next_page_token, or ",
        local_path_available=False,
    )
    return out


def _message_summary(msg: dict[str, Any]) -> dict[str, Any]:
    """The id / thread_id / label_ids shape every message-returning write tool uses."""
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "label_ids": msg.get("labelIds") or [],
    }


def _draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    """The id + nested message shape create_draft and update_draft return."""
    message = draft.get("message") or {}
    return {
        "id": draft["id"],
        "message": {
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "label_ids": message.get("labelIds") or [],
        },
    }


async def _fetch_draft_entry(
    gmail_service: Any, stub: dict[str, Any], limit: asyncio.Semaphore
) -> dict[str, Any]:
    """One list_drafts entry: the draft id plus its message in get_message's
    include_body=False shape. Fetched with messages.get, whose metadataHeaders filter
    drafts.get lacks, so only the shaped headers come back (#793). A draft that
    can't be read (e.g. sent or updated since the list call) keeps its ids and gets
    an error."""
    stub_message = stub.get("message") or {}
    message_id = stub_message.get("id")
    error = "drafts.list returned no message id"
    if message_id:
        async with limit:
            try:
                msg = await execute_in_thread(
                    gmail_service.users()
                    .messages()
                    .get(userId=_USER, id=message_id, **_get_format_kwargs(False))
                    .execute,
                    gmail_service,
                )
                return {"id": stub["id"], "message": _start_shaping(msg, include_body=False).shaped}
            except Exception as e:
                error = str(e)
    return {
        "id": stub["id"],
        "message": {"id": message_id, "thread_id": stub_message.get("threadId")},
        "error": error,
    }


def _unfold(value: Any) -> str | None:
    """A header value as text with its RFC 5322 folding line breaks removed, or None
    if blank."""
    return "".join(str(value or "").splitlines()).strip() or None


def _carried_parts(msg: Message) -> tuple[list[Message], list[Message]]:
    """Every part of a parsed draft except its plain and HTML bodies, split into
    (attachments, inline parts). That covers everything get_message lists as an
    attachment. A body is the first nameless, non-attachment text/plain or text/html
    part, the same rule _extract_bodies_and_attachments uses. An inline part has a
    Content-ID and no attachment disposition. Doesn't look inside an attached
    message, so its own parts stay with it."""
    attachments: list[Message] = []
    inline: list[Message] = []
    claimed: set[str] = set()

    def walk(part: Message) -> None:
        for child in part.get_payload():
            if child.get_content_maintype() == "multipart":
                walk(child)
                continue
            disposition = child.get_content_disposition()
            slot = _BODY_SLOTS.get(child.get_content_type())
            is_body = slot and disposition != "attachment" and not child.get_filename()
            if is_body and slot not in claimed:
                claimed.add(slot)
                continue
            if child["Content-ID"] and disposition != "attachment":
                inline.append(child)
            else:
                attachments.append(child)

    if msg.get_content_maintype() == "multipart":
        walk(msg)
    return attachments, inline


@dataclass
class _ExistingDraft:
    """What update_draft carries over from the draft it replaces."""

    thread_id: str | None
    from_: str | None
    in_reply_to: str | None
    references: str | None
    attachments: list[Message] = field(default_factory=list)
    inline: list[Message] = field(default_factory=list)


def _existing_draft_from_raw(message: dict[str, Any]) -> _ExistingDraft:
    """Parse a format='raw' draft message. Runs off the event loop: the raw message
    includes every attachment's bytes.

    Headers are read with policy.default, which decodes RFC 2047 words and raw 8-bit
    UTF-8 alike, so From reaches _build_raw_message as the same text the metadata
    path gives it (PR #1227 QA). The parts are parsed with compat32 and attached
    as-is, so their bytes aren't re-encoded.
    """
    data = message.get("raw") or ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    headers = BytesHeaderParser(policy=policy.default).parsebytes(raw)
    attachments, inline = _carried_parts(message_from_bytes(raw))
    return _ExistingDraft(
        thread_id=message.get("threadId"),
        from_=_unfold(headers.get("From")),
        in_reply_to=_unfold(headers.get("In-Reply-To")),
        references=_unfold(headers.get("References")),
        attachments=attachments,
        inline=inline,
    )


def _existing_draft_from_metadata(message: dict[str, Any]) -> _ExistingDraft:
    headers = _header_map((message.get("payload") or {}).get("headers"))
    return _ExistingDraft(
        thread_id=message.get("threadId"),
        from_=headers.get("from") or None,
        in_reply_to=headers.get("in-reply-to") or None,
        references=headers.get("references") or None,
    )


# --- Safe-by-default sending (#1081) -------------------------------------------------
#
# Under GMAIL_SEND=confirm, send_message and reply_to_message save a draft first, and
# a draft is sent only after the user confirms it in a form elicitation. Every
# outcome but an explicit yes leaves the draft unsent in Gmail's Drafts folder.

# Consumer Gmail domains: every account there shares one, so "outside your
# organization" means nothing and isn't flagged.
_CONSUMER_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

# How long a send confirmation waits for the user's answer before the draft is held.
_CONFIRM_TIMEOUT_SECONDS = 600

# How much of the body the confirmation shows.
_PREVIEW_BODY_CHARS = 500

_HELD_REASONS = {
    "no_elicitation": "This MCP client can't show a send confirmation, so the email wasn't sent.",
    "declined": "The send wasn't confirmed, so the email wasn't sent.",
    "cancelled": "The send confirmation was cancelled, so the email wasn't sent.",
    "timeout": (
        f"The send confirmation got no answer within {_CONFIRM_TIMEOUT_SECONDS} seconds, so "
        "the email wasn't sent."
    ),
    "error": "The send confirmation failed, so the email wasn't sent.",
    "changed": (
        "The draft changed after the send was confirmed, so it wasn't sent: what was "
        "confirmed is no longer what would go out."
    ),
}


class _SendConfirmation(BaseModel):
    """The form the user answers. Required, with no default, so an empty acceptance
    fails validation and holds the draft instead of sending it."""

    send: bool = Field(title="Send this email now", description="Check to send it.")


def _unique_addresses(*headers: str | None) -> list[str]:
    """Every address in the given header values, lowercased, first occurrence kept."""
    seen: dict[str, None] = {}
    for _, addr in getaddresses([h for h in headers if h]):
        if addr:
            seen.setdefault(addr.strip().lower(), None)
    return list(seen)


def _domain(address: str) -> str:
    return address.rpartition("@")[2].lower()


def _recipient_flags(
    *,
    to: str | None,
    cc: str | None,
    bcc: str | None,
    primary: str | None,
    own: set[str],
    threshold: int,
) -> list[dict[str, Any]]:
    """The warnings a send shows before (or instead of) delivery.

    - outside_organization: on a Workspace account (primary address outside
      _CONSUMER_DOMAINS), each recipient whose domain isn't the primary's or a
      non-consumer send-as alias's. Exact match, so sub.example.com is outside
      example.com. If the primary
      address is unknown, an outside_organization_unchecked note says the check
      didn't run, rather than implying every recipient is inside.
    - many_recipients: more than `threshold` unique addresses across To, Cc and Bcc.
    - hidden_recipients: any Bcc.
    """
    flags: list[dict[str, Any]] = []
    everyone = _unique_addresses(to, cc, bcc)
    if primary is None:
        flags.append(
            {
                "flag": "outside_organization_unchecked",
                "message": (
                    "Couldn't look up this mailbox's own address, so recipients outside "
                    "your organization aren't flagged."
                ),
            }
        )
    elif _domain(primary) not in _CONSUMER_DOMAINS:
        # A consumer send-as alias (e.g. a personal gmail.com address added to a
        # Workspace mailbox) doesn't make that domain part of the organization:
        # counting it would hide the flag for every gmail.com recipient.
        org = {_domain(primary)}
        org |= {d for d in (_domain(a) for a in own) if d not in _CONSUMER_DOMAINS}
        outside = [a for a in everyone if _domain(a) not in org]
        if outside:
            flags.append(
                {
                    "flag": "outside_organization",
                    "message": f"{len(outside)} recipient(s) outside your organization: "
                    + ", ".join(outside),
                    "addresses": outside,
                }
            )
    if len(everyone) > threshold:
        flags.append(
            {
                "flag": "many_recipients",
                "message": f"{len(everyone)} recipients (warning threshold {threshold}).",
                "count": len(everyone),
                "threshold": threshold,
            }
        )
    hidden = _unique_addresses(bcc)
    if hidden:
        flags.append(
            {
                "flag": "hidden_recipients",
                "message": f"{len(hidden)} hidden (Bcc) recipient(s): " + ", ".join(hidden),
                "count": len(hidden),
            }
        )
    return flags


@dataclass
class _DraftPreview:
    """A stored draft as Gmail holds it: what the confirmation shows and what
    drafts.send would deliver. message_id changes on every drafts.update (checked live,
    #1081), so it identifies the confirmed content."""

    draft_id: str
    message_id: str | None
    thread_id: str | None
    label_ids: list[str]
    from_: str | None
    to: str | None
    cc: str | None
    bcc: str | None
    subject: str | None
    body_plain: str
    # The HTML part as text, or None without one. Recipients' mail apps show the HTML
    # part when there is one, so the confirmation has to show it too.
    body_html_text: str | None
    attachment_names: list[str]


class _HtmlText(HTMLParser):
    """An HTML body's visible text, one line per block, for the confirmation. An
    approximation of what a mail app shows, erring toward showing too much: only
    elements whose content no client renders are hidden, and the content of an
    Outlook conditional comment (<!--[if mso]>...<![endif]-->) is shown, since
    Outlook renders it."""

    _BLOCKS = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
        | {"blockquote", "pre", "table", "ul", "ol", "hr", "section", "article"}
    )
    # Not "head": an HTML5 parser closes an unclosed <head> at the first body
    # content, so hiding it would hide what recipients see (PR #1249 QA round 2).
    # What legitimately sits in a head (title, style, script) is hidden by its own tag.
    _HIDDEN = frozenset({"script", "style", "title", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._HIDDEN:
            self._hidden_depth += 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        # "[if mso]>...<![endif]" for <!--[if mso]>...<![endif]-->.
        if self._hidden_depth or not data.lstrip().startswith("[if"):
            return
        _, _, inner = data.partition("]>")
        inner = inner.rsplit("<![endif]", 1)[0]
        self.parts += ["\n", _html_to_text(inner), "\n"]


def _html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


async def _read_draft_preview(gmail_service: Any, draft_id: str) -> _DraftPreview:
    """Read a draft back from Gmail, so the confirmation describes the stored message
    (Gmail stamps its From, checked live) rather than the tool's own arguments."""
    draft = await execute_in_thread(
        gmail_service.users().drafts().get(userId=_USER, id=draft_id, format="full").execute,
        gmail_service,
    )
    message = draft.get("message") or {}
    [shaped] = await _finish_shaping_all(gmail_service, [_start_shaping(message)])
    headers = shaped.get("headers") or {}
    html = shaped.get("body_html")
    return _DraftPreview(
        draft_id=draft.get("id") or draft_id,
        message_id=message.get("id"),
        thread_id=message.get("threadId"),
        label_ids=message.get("labelIds") or [],
        from_=headers.get("from"),
        to=headers.get("to"),
        cc=headers.get("cc"),
        bcc=headers.get("bcc"),
        subject=headers.get("subject"),
        body_plain=shaped.get("body_plain") or "",
        body_html_text=_html_to_text(html) if html else None,
        attachment_names=[
            a.get("filename") or "(unnamed)" for a in shaped.get("attachments") or []
        ],
    )


def _one_line(value: str) -> str:
    """A draft-supplied value (subject, display name, filename) on one line, so it
    can't add a line of its own that reads like the server's."""
    return " ".join(value.split())


def _display_addresses(header: str | None) -> list[str]:
    """A header's addresses for a person to read: the decoded display name as is,
    never re-encoded (formataddr would show RFC 2047 base64 for a non-ASCII name, and
    raises on a non-ASCII address)."""
    out = []
    for name, addr in getaddresses([header or ""]):
        if addr:
            out.append(_one_line(f"{name} <{addr}>" if name else addr))
    return out


def _fenced(label: str, text: str) -> list[str]:
    """`text` under a label saying how much of it is shown, every line prefixed with
    "│ ", so nothing in it can pass for one of the server's own lines."""
    shown = text[:_PREVIEW_BODY_CHARS]
    if len(text) > _PREVIEW_BODY_CHARS:
        heading = f"{label} (first {_PREVIEW_BODY_CHARS} of {len(text)} characters):"
        shown = shown.rstrip() + "…"
    else:
        heading = f"{label} ({len(text)} characters):"
    return [heading, *(f"│ {line}" for line in shown.splitlines() or [""])]


def _confirmation_text(preview: _DraftPreview, flags: list[dict[str, Any]]) -> str:
    """The confirmation message: flags first, then sender, every recipient grouped by
    To/Cc/Bcc, subject, attachment names, and the body, fenced. An HTML part is shown
    as text too, unless its text is the plain body's."""
    lines = ["Send this email?"]
    lines += [f"⚠ {_one_line(f['message'])}" for f in flags]
    lines.append("")
    lines.append(f"From: {_one_line(preview.from_ or 'your default Gmail address')}")
    for label, value in (("To", preview.to), ("Cc", preview.cc), ("Bcc", preview.bcc)):
        if addresses := _display_addresses(value):
            lines.append(f"{label}: " + ", ".join(addresses))
    lines.append(f"Subject: {_one_line(preview.subject or '') or '(no subject)'}")
    if preview.attachment_names:
        lines.append("Attachments: " + ", ".join(_one_line(n) for n in preview.attachment_names))
    lines.append("")
    plain, html = preview.body_plain, preview.body_html_text
    if plain or html is None:
        lines += _fenced("Body", plain) if plain else ["Body: (empty)"]
    if html is not None:
        if plain and " ".join(html.split()) == " ".join(plain.split()):
            lines.append("The HTML version shows the same text.")
        else:
            lines.append("")
            lines += _fenced("HTML version, which most mail apps show, as text", html)
    return "\n".join(lines)


def _can_elicit_form(ctx: Any) -> bool:
    """Whether this call can ask the user through a form elicitation: the client
    declares form mode (a bare `elicitation: {}` counts, as in mcp's own check) AND
    the request has a back-channel to send it on. On a 2026-07-28 connection the
    client still declares the capability, but can_send_request is False (#1081
    design pass), so the capability alone isn't enough."""
    session = reauth_session(ctx)
    if getattr(session, "can_send_request", False) is not True:
        return False
    elicitation = getattr(getattr(session, "client_capabilities", None), "elicitation", None)
    if elicitation is None:
        return False
    return elicitation.form is not None or elicitation.url is None


async def _ask_to_send(ctx: Any, preview: _DraftPreview, flags: list[dict[str, Any]]) -> str:
    """Ask the user to confirm. 'accepted' only for an explicit yes; otherwise the
    reason the draft is held (a key of _HELD_REASONS)."""
    try:
        with anyio.fail_after(_CONFIRM_TIMEOUT_SECONDS):
            result = await ctx.elicit(_confirmation_text(preview, flags), _SendConfirmation)
    except NoBackChannelError:
        # The channel dropped after _can_elicit_form's check. Caught here: it's an
        # MCPError, which would otherwise end the call as a protocol error and lose
        # the draft_id.
        return "no_elicitation"
    except TimeoutError:
        return "timeout"
    except Exception:
        logger.warning("Send confirmation for draft %s failed", preview.draft_id, exc_info=True)
        return "error"
    if result.action == "accept":
        return "accepted" if result.data.send is True else "declined"
    return "cancelled" if result.action == "cancel" else "declined"


def _held_result(
    preview: _DraftPreview, reason: str, flags: list[dict[str, Any]], *, created: bool
) -> dict[str, Any]:
    """The result when the email isn't sent: where the draft is and why."""
    where = (
        "It's saved as a draft in Gmail's Drafts folder"
        if created
        else "The draft is still in Gmail's Drafts folder"
    )
    return {
        "sent": False,
        "reason": reason,
        "draft_id": preview.draft_id,
        "message": {
            "id": preview.message_id,
            "thread_id": preview.thread_id,
            "label_ids": preview.label_ids,
        },
        "recipient_flags": flags,
        "note": f"{_HELD_REASONS[reason]} {where} (draft_id {preview.draft_id}), to review "
        "and send from Gmail.",
    }


async def _confirm_and_send_draft(
    ctx: Any, lc: Any, draft_id: str, *, created: bool
) -> dict[str, Any]:
    """GMAIL_SEND=confirm's send: read the draft back, ask the user, and send it only
    on an explicit yes and only if it's unchanged since the confirmation was built.
    `created` says the draft was made by this call (send_message/reply_to_message)
    rather than passed in (send_draft), which only changes the wording.

    An API failure returns {"error", "draft_id"}, so a caller whose draft this call
    created still learns where it is."""
    try:
        return await _confirm_and_send_steps(ctx, lc, draft_id, created=created)
    except Exception as e:
        if not created:
            return {"error": str(e), "draft_id": draft_id}
        return {
            "error": f"{e} (This call saved the email as draft {draft_id} in Gmail's "
            "Drafts folder; check the Sent folder too before retrying.)",
            "draft_id": draft_id,
        }


async def _draft_then_confirm(ctx: Any, lc: Any, message: dict[str, Any]) -> dict[str, Any]:
    """GMAIL_SEND=confirm's send_message/reply_to_message: save `message` ({"raw",
    optional "threadId"}) as a draft, then confirm and send it like send_draft. A
    drafts.create failure raises, for the tool's own {"error": ...}: nothing was
    saved, so there's no draft to name."""
    draft = await execute_in_thread(
        lc.gmail_service.users().drafts().create(userId=_USER, body={"message": message}).execute,
        lc.gmail_service,
    )
    return await _confirm_and_send_draft(ctx, lc, draft["id"], created=True)


async def _confirm_and_send_steps(
    ctx: Any, lc: Any, draft_id: str, *, created: bool
) -> dict[str, Any]:
    # Independent reads; both finish before the form appears. _own_addresses never
    # raises (it degrades to a warning), so a preview failure is the only error here.
    preview, (own, _) = await asyncio.gather(
        _read_draft_preview(lc.gmail_service, draft_id), _own_addresses(lc)
    )
    primary = getattr(lc, "gmail_primary_address", None)
    flags = _recipient_flags(
        to=preview.to,
        cc=preview.cc,
        bcc=preview.bcc,
        primary=primary if isinstance(primary, str) else None,
        own=own,
        threshold=GMAIL_SEND_WARN_RECIPIENTS,
    )
    if not _can_elicit_form(ctx):
        return _held_result(preview, "no_elicitation", flags, created=created)
    outcome = await _ask_to_send(ctx, preview, flags)
    if outcome != "accepted":
        return _held_result(preview, outcome, flags, created=created)

    # drafts.send takes no precondition, so the check is a re-read just before the
    # send: update_draft (e.g. a parallel call) replaces the message ID. The window
    # between the two requests remains; it's as short as the API allows.
    current = await execute_in_thread(
        lc.gmail_service.users().drafts().get(userId=_USER, id=draft_id, format="minimal").execute,
        lc.gmail_service,
    )
    if (current.get("message") or {}).get("id") != preview.message_id:
        return _held_result(preview, "changed", flags, created=created)
    sent = await execute_in_thread(
        lc.gmail_service.users().drafts().send(userId=_USER, body={"id": draft_id}).execute,
        lc.gmail_service,
    )
    logger.debug("Sent confirmed draft %s as message %s", draft_id, sent.get("id"))
    return {**_message_summary(sent), "sent": True, "draft_id": draft_id, "recipient_flags": flags}


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
        kwargs = _list_kwargs(
            query=query,
            label_ids=label_ids,
            max_results=max_results,
            page_token=page_token,
            include_spam_trash=include_spam_trash,
        )
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
        return _list_page(result, "messages", messages, "list_messages")

    @tool(annotations=ToolAnnotations(title="Get Message", readOnlyHint=True))
    async def get_message(
        message_id: str,
        local_path: str | None = None,
        include_body: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Fetch a single message by ID, including headers, body, and attachment metadata.

        Args:
            message_id: The Gmail message ID (from list_messages or get_thread).
            local_path: Optional local filesystem path (file or directory) to write the
                        message JSON to instead of returning it inline. Bypasses the
                        response-size cap, for messages with very large bodies. A
                        path ending in '/' is a directory, created if missing. A file
                        in place of a parent directory, or at a path ending in '/',
                        raises ValueError; an existing file at a plain file path is
                        replaced.
            include_body: When False, fetch only metadata (Gmail's format='metadata'):
                          no body is downloaded, and body_plain, body_html, and
                          attachments are left out of the result.

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
            (each entry with message_id) when present. With include_body=False, only
            id, thread_id, snippet, label_ids, internal_date, size_estimate, and
            headers. On API failure, {"error": "..."}.
        """
        if local_path:
            # Before any fetch, so a refused destination costs no API call (#796).
            check_write(local_path)
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            msg = await execute_in_thread(
                lc.gmail_service.users()
                .messages()
                .get(userId=_USER, id=message_id, **_get_format_kwargs(include_body))
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        # No body is fetched with include_body=False, so only headers can be large.
        hint = "The message body is large. " if include_body else "The message headers are large. "
        pending = [_start_shaping(msg, include_body=include_body)]
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
        kwargs = _list_kwargs(
            query=query,
            label_ids=label_ids,
            max_results=max_results,
            page_token=page_token,
            include_spam_trash=include_spam_trash,
        )
        try:
            result = await execute_in_thread(
                lc.gmail_service.users().threads().list(**kwargs).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        threads = [
            {"id": t["id"], "snippet": t.get("snippet"), "history_id": t.get("historyId")}
            for t in result.get("threads", [])
        ]
        return _list_page(result, "threads", threads, "list_threads")

    @tool(annotations=ToolAnnotations(title="Get Thread", readOnlyHint=True))
    async def get_thread(
        thread_id: str,
        local_path: str | None = None,
        include_body: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Fetch all messages in a conversation thread.

        Args:
            thread_id: The Gmail thread ID (from list_threads or a message's thread_id).
            local_path: Optional local filesystem path (file or directory) to write the
                        thread JSON to instead of returning it inline. Bypasses the
                        response-size cap, for threads with very large bodies. A
                        path ending in '/' is a directory, created if missing. A file
                        in place of a parent directory, or at a path ending in '/',
                        raises ValueError; an existing file at a plain file path is
                        replaced.
            include_body: When False, fetch only each message's metadata (Gmail's
                          format='metadata'): no body is downloaded, and body_plain,
                          body_html, and attachments are left out. Use it to list a
                          thread too large to read whole, then get_message each ID.

        Returns:
            Thread with id, snippet, history_id, and messages (same shape as get_message,
            including its include_body=False shape).
            Raises an error naming the size if the thread is over the response-size cap
            and local_path is not set. If local_path is set, returns {local_path,
            thread_id, message_count, bytes_written} instead, plus body_fetch_errors /
            body_decode_errors (each entry with message_id) when present. On API
            failure, {"error": "..."}.
        """
        if local_path:
            # Before any fetch, so a refused destination costs no API call (#796).
            check_write(local_path)
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            thread = await execute_in_thread(
                lc.gmail_service.users()
                .threads()
                .get(userId=_USER, id=thread_id, **_get_format_kwargs(include_body))
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        hint = (
            "The thread is large; call get_thread with include_body=False to list its "
            "message IDs and headers, then get_message on individual IDs. "
            if include_body
            else "The thread has too many messages to list inline. "
        )
        pending = [_start_shaping(m, include_body=include_body) for m in thread.get("messages", [])]
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
        Send a new email message, after the user confirms it (by default).

        By default (GMAIL_SEND=confirm) the message is saved as a Gmail draft and
        sent only when the user confirms it in a form the MCP client shows, which
        lists the sender, every recipient, the subject, attachment names, the start
        of the body, and any recipient flags. Declining, cancelling, no answer, or a
        client that can't show the form leaves it as an unsent draft. Confirmation
        needs a client on the 2025-11-25 handshake; on 2026-07-28 connections mail
        stays a draft. Claude Code currently connects on 2026-07-28, so from it every
        send is held as a draft. A client hook that auto-accepts confirmations with a yes
        makes this the same as GMAIL_SEND=direct, which sends at once.

        Args:
            to: Recipient email address, or a list of addresses.
            subject: Email subject line.
            body: Plain-text body.
            cc: Optional CC address or list of addresses.
            bcc: Optional BCC address or list of addresses.
            body_html: Optional HTML body (sent alongside the plain-text body).
            attachments: Optional list of attachment dicts. Each needs either
                         local_path or content_base64, plus optional filename and
                         mime_type (guessed from the filename's extension when
                         omitted, else application/octet-stream).

        Returns:
            Once sent: sent true, the sent message id, thread_id, and label_ids,
            plus (under confirm) draft_id and recipient_flags. If not sent: sent
            false, reason (no_elicitation, declined, cancelled, timeout, error, or
            changed), draft_id, message {id, thread_id, label_ids}, recipient_flags
            (each {flag, message, ...}: outside_organization, many_recipients,
            hidden_recipients, or outside_organization_unchecked), and a note
            saying the email is waiting in Gmail's Drafts folder. On failure,
            {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            raw = await _compose_raw(
                to=to,
                subject=subject,
                body=body,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                attachments=attachments,
            )
            if GMAIL_SEND == "confirm":
                return await _draft_then_confirm(ctx, lc, {"raw": raw})
            sent = await execute_in_thread(
                lc.gmail_service.users().messages().send(userId=_USER, body={"raw": raw}).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Sent message %s", sent.get("id"))
        return {**_message_summary(sent), "sent": True}

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
                         mime_type (guessed from the filename's extension when
                         omitted, else application/octet-stream).

        Returns:
            Draft id and nested message id/thread_id. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            raw = await _compose_raw(
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

        logger.debug("Created draft %s", draft.get("id"))
        return _draft_summary(draft)

    @tool(annotations=ToolAnnotations(title="Send Draft", destructiveHint=True))
    async def send_draft(draft_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Send an existing draft by ID, after the user confirms it (by default).

        By default (GMAIL_SEND=confirm) the user confirms the draft in a form the
        MCP client shows, built from the draft as Gmail stores it, and only an
        explicit yes sends it. If the client can't show the form, or the user
        doesn't confirm, nothing is sent and the draft stays in Gmail's Drafts
        folder. A draft changed after the confirmation (e.g. by update_draft) is
        refused, not sent. Confirmation needs a client on the 2025-11-25 handshake;
        on 2026-07-28 connections (Claude Code, currently) this tool refuses. A client
        hook that
        auto-accepts confirmations with a yes makes this the same as
        GMAIL_SEND=direct, which sends at once.

        Args:
            draft_id: The draft ID returned by create_draft.

        Returns:
            Once sent: sent true, the sent message id, thread_id, and label_ids,
            plus (under confirm) draft_id and recipient_flags. If refused: sent
            false with the same reason, draft_id, message, recipient_flags, and
            note fields as send_message. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        if GMAIL_SEND == "confirm":
            return await _confirm_and_send_draft(ctx, lc, draft_id, created=False)
        try:
            sent = await execute_in_thread(
                lc.gmail_service.users().drafts().send(userId=_USER, body={"id": draft_id}).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Sent draft %s as message %s", draft_id, sent.get("id"))
        return {**_message_summary(sent), "sent": True}

    @tool(annotations=ToolAnnotations(title="List Drafts", readOnlyHint=True))
    async def list_drafts(
        query: str | None = None,
        max_results: int = 50,
        page_token: str | None = None,
        include_spam_trash: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        List drafts in the authenticated user's mailbox.

        Args:
            query: Gmail search syntax filter, e.g. 'to:alice@example.com subject:invoice'.
            max_results: Maximum number of drafts to return (default 50, max 500).
            page_token: Continuation token from a previous response for pagination.
            include_spam_trash: When True, include drafts from SPAM and TRASH.

        Returns:
            Dictionary with drafts, optional next_page_token, and
            result_size_estimate. Each draft is {"id": draft ID (for get_draft,
            update_draft, delete_draft and send_draft), "message": ...}, where message
            is get_message's include_body=False shape: id, thread_id, snippet,
            label_ids, internal_date, size_estimate, and headers (to, cc, bcc,
            subject, date, ...). A draft that can't be read (e.g. sent or updated
            since it was listed) has message {id, thread_id} and an error. On API
            failure, returns {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        kwargs = _list_kwargs(
            query=query,
            label_ids=None,
            max_results=max_results,
            page_token=page_token,
            include_spam_trash=include_spam_trash,
        )
        try:
            result = await execute_in_thread(
                lc.gmail_service.users().drafts().list(**kwargs).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        # drafts.list returns only ids, so each draft's headers take a messages.get,
        # capped like body fetches to stay under Gmail's per-user concurrency limit.
        limit = asyncio.Semaphore(_BODY_FETCH_CONCURRENCY)
        drafts = await gather_with_fallback(
            result.get("drafts", []),
            lambda stub: _fetch_draft_entry(lc.gmail_service, stub, limit),
            lambda stub, exc: {"id": stub["id"], "error": str(exc)},
        )
        return _list_page(result, "drafts", drafts, "list_drafts")

    @tool(annotations=ToolAnnotations(title="Get Draft", readOnlyHint=True))
    async def get_draft(
        draft_id: str,
        local_path: str | None = None,
        include_body: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Fetch a single draft by ID, including headers, body, and attachment metadata.

        Args:
            draft_id: The draft ID (from list_drafts or create_draft).
            local_path: Optional local filesystem path (file or directory) to write the
                        draft JSON to instead of returning it inline. Bypasses the
                        response-size cap, for drafts with very large bodies. A path
                        ending in '/' is a directory, created if missing. A file in
                        place of a parent directory, or at a path ending in '/',
                        raises ValueError; an existing file at a plain file path is
                        replaced.
            include_body: When False, fetch only metadata: no body is downloaded, and
                          body_plain, body_html, and attachments are left out.

        Returns:
            {"id": draft ID, "message": ...}, where message has the same shape as
            get_message's result (including its include_body=False shape and its
            body_decode_errors / body_fetch_errors). Raises an error naming the size
            if the draft is over the response-size cap and local_path is not set. If
            local_path is set, returns {local_path, draft_id, bytes_written} instead,
            plus body_fetch_errors / body_decode_errors (each entry with message_id)
            when present. On API failure, {"error": "..."}.
        """
        if local_path:
            # Before any fetch, so a refused destination costs no API call (#796).
            check_write(local_path)
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            # drafts.get has no metadataHeaders filter; shaping drops the extra headers.
            draft = await execute_in_thread(
                lc.gmail_service.users()
                .drafts()
                .get(userId=_USER, id=draft_id, format="full" if include_body else "metadata")
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        hint = "The draft body is large. " if include_body else "The draft headers are large. "
        pending = [_start_shaping(draft.get("message") or {}, include_body=include_body)]
        if not local_path:
            enforce_response_size_floor(
                _deferred_body_bytes(pending), tool_name="get_draft", hint=hint
            )
        [message] = await _finish_shaping_all(lc.gmail_service, pending)
        shaped = {"id": draft["id"], "message": message}
        if local_path:
            return await write_capped_result_to_disk(
                shaped,
                local_path,
                default_filename=f"draft_{draft_id}.json",
                manifest_extra={"draft_id": draft_id, **_manifest_body_errors([message])},
            )
        enforce_response_size_cap(shaped, tool_name="get_draft", hint=hint)
        return shaped

    @tool(annotations=ToolAnnotations(title="Update Draft", destructiveHint=True))
    async def update_draft(
        draft_id: str,
        to: str | list[str],
        subject: str,
        body: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        body_html: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        keep_attachments: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Replace a draft's content without sending it. The draft keeps its ID.

        The call's arguments replace the draft's old content: omitted cc, bcc,
        body_html, and attachments are removed, not kept. A reply draft stays in
        its thread, keeping its In-Reply-To and References headers, as long as the
        subject still matches the thread's (Gmail's threading rule). The draft's
        From (e.g. a send-as alias chosen in Gmail) is also kept.

        Args:
            draft_id: The draft ID (from list_drafts or create_draft).
            to: Recipient email address, or a list of addresses.
            subject: Email subject line.
            body: Plain-text body.
            cc: Optional CC address or list of addresses.
            bcc: Optional BCC address or list of addresses.
            body_html: Optional HTML body (sent alongside the plain-text body).
            attachments: Optional list of attachment dicts to add. Each needs either
                         local_path or content_base64, plus optional filename and
                         mime_type (guessed from the filename's extension when
                         omitted, else application/octet-stream).
            keep_attachments: When True, keep every part of the draft except its
                              plain and HTML bodies (so every attachment get_draft
                              lists), ahead of any in attachments. Inline images
                              (parts with a Content-ID) stay inline with the new
                              body_html, so its cid: references still resolve;
                              without body_html they become ordinary attachments.

        Returns:
            Draft id and nested message id/thread_id/label_ids. The message id
            changes on every update; the draft id doesn't. On failure,
            {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            # Read the new attachments first, so a refused or missing local_path
            # fails before any API call (#796).
            new_parts = await asyncio.to_thread(
                lambda: [_attachment_part(*_read_attachment_bytes(a)) for a in attachments or []]
            )
            # 'raw' only when the old attachments are needed: it carries their bytes.
            current = await execute_in_thread(
                lc.gmail_service.users()
                .drafts()
                .get(userId=_USER, id=draft_id, format="raw" if keep_attachments else "metadata")
                .execute,
                lc.gmail_service,
            )
            message = current.get("message") or {}
            if keep_attachments:
                existing = await asyncio.to_thread(_existing_draft_from_raw, message)
            else:
                existing = _existing_draft_from_metadata(message)
            raw = await _compose_raw(
                to=to,
                subject=subject,
                body=body,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                in_reply_to=existing.in_reply_to,
                references=existing.references,
                from_=existing.from_,
                attachment_parts=[*existing.attachments, *new_parts],
                inline_parts=existing.inline,
            )
            new_message: dict[str, Any] = {"raw": raw}
            if existing.thread_id:
                new_message["threadId"] = existing.thread_id
            updated = await execute_in_thread(
                lc.gmail_service.users()
                .drafts()
                .update(userId=_USER, id=draft_id, body={"id": draft_id, "message": new_message})
                .execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Updated draft %s", draft_id)
        return _draft_summary(updated)

    @tool(annotations=ToolAnnotations(title="Delete Draft", destructiveHint=True))
    async def delete_draft(draft_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Permanently delete a draft. Unlike trash_message, it can't be recovered.

        Args:
            draft_id: The draft ID (from list_drafts or create_draft).

        Returns:
            {"id": draft_id, "action": "deleted"}. On failure, {"error": "..."}.
        """
        if unauthorized := get_gmail_unauthorized_message():
            return {"error": unauthorized}
        lc = ctx.request_context.lifespan_context
        try:
            await execute_in_thread(
                lc.gmail_service.users().drafts().delete(userId=_USER, id=draft_id).execute,
                lc.gmail_service,
            )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("Deleted draft %s", draft_id)
        return {"id": draft_id, "action": "deleted"}

    @tool(annotations=ToolAnnotations(title="Reply to Message", destructiveHint=True))
    async def reply_to_message(
        message_id: str,
        body: str,
        body_html: str | None = None,
        reply_all: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Send a reply in an existing thread, after the user confirms it (by default).

        Fetches the original message for Subject / Message-ID / References headers
        and sets the reply's threadId so Gmail groups it correctly.

        By default (GMAIL_SEND=confirm) the reply is saved as a draft in the
        original thread and sent only when the user confirms it, exactly as
        send_message describes; otherwise it waits in Gmail's Drafts folder.
        GMAIL_SEND=direct sends at once.

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
            The same shapes as send_message: sent true with the sent message id,
            thread_id, and label_ids, or sent false with the held draft. A
            reply_all, or a reply to your own sent message, also has a warning when
            your own addresses couldn't be fully looked up (so you may be among the
            recipients). On failure, {"error": "..."}.
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
        own, own_warning = await _own_addresses(lc)
        sent_label = "SENT" in (original.get("labelIds") or [])
        to, cc = _reply_recipients(
            original_from=original_from,
            original_reply_to=headers.get("reply-to", ""),
            original_to=original_to,
            original_cc=original_cc,
            sent_label=sent_label,
            reply_all=reply_all,
            own=own,
        )

        if not to:
            return {"error": "Original message has no From header to reply to."}

        try:
            raw = await _compose_raw(
                to=to,
                subject=subject,
                body=body,
                body_html=body_html,
                cc=cc,
                in_reply_to=original_message_id or None,
                references=references,
            )
            reply = {"raw": raw, "threadId": original.get("threadId")}
            if GMAIL_SEND == "confirm":
                out = await _draft_then_confirm(ctx, lc, reply)
            else:
                sent = await execute_in_thread(
                    lc.gmail_service.users().messages().send(userId=_USER, body=reply).execute,
                    lc.gmail_service,
                )
                logger.debug("Replied to message %s with %s", message_id, sent.get("id"))
                out = {**_message_summary(sent), "sent": True}
        except Exception as e:
            return {"error": str(e)}

        # Only warn when the own-address set decided the recipients: reply_all, or a
        # reply to the mailbox's own (SENT) message. A plain reply to someone else's
        # message goes to their Reply-To/From either way (PR #928 QA). Not covered: a
        # message sent from an unlisted alias via another client, without SENT.
        if own_warning and (reply_all or sent_label):
            out["warning"] = own_warning
        return out

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
                return _message_summary(result)

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
