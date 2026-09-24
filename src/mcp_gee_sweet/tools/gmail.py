"""Gmail tools — messages, threads, labels, drafts, and organization primitives."""

import base64
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, getaddresses
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ..auth import execute_in_thread
from .response_limits import clamp_max_results, enforce_response_size_cap

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


async def _mailbox_email(gmail_service: Any) -> str | None:
    """Return the authenticated mailbox address (users.getProfile), or None."""
    try:
        profile = await execute_in_thread(
            gmail_service.users().getProfile(userId=_USER).execute,
            gmail_service,
        )
    except Exception:
        logger.debug("Could not resolve mailbox email via getProfile", exc_info=True)
        return None
    email = (profile or {}).get("emailAddress")
    return email.strip() if isinstance(email, str) and email.strip() else None


def _reply_all_recipients(
    *,
    original_from: str,
    original_to: str,
    original_cc: str,
    mailbox: str | None,
) -> tuple[str | None, str | None]:
    """Build reply-all To/Cc, excluding the authenticated mailbox."""
    exclude = {mailbox.lower()} if mailbox else set()
    seen: set[str] = set(exclude)
    to_parts: list[str] = []
    cc_parts: list[str] = []

    def add(target: list[str], header_value: str | None) -> None:
        if not header_value:
            return
        for name, addr in getaddresses([header_value]):
            if not addr:
                continue
            key = addr.lower()
            if key in seen:
                continue
            seen.add(key)
            target.append(formataddr((name, addr)))

    add(to_parts, original_from)
    add(to_parts, original_to)
    add(cc_parts, original_cc)

    to = ", ".join(to_parts) if to_parts else None
    cc = ", ".join(cc_parts) if cc_parts else None
    return to, cc


def _header_map(headers: list[dict[str, str]] | None) -> dict[str, str]:
    return {h["name"].lower(): h.get("value", "") for h in (headers or []) if "name" in h}


def _decode_body_data(data: str | None) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _extract_bodies_and_attachments(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Walk a Gmail message payload; return (plain, html, attachment metadata)."""
    plain: str | None = None
    html: str | None = None
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        nonlocal plain, html
        mime_type = part.get("mimeType", "")
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        data = body.get("data")
        attachment_id = body.get("attachmentId")

        if filename or attachment_id:
            attachments.append(
                {
                    "filename": filename or None,
                    "mime_type": mime_type or None,
                    "size": body.get("size"),
                    "attachment_id": attachment_id,
                }
            )
        elif data and mime_type == "text/plain" and plain is None:
            plain = _decode_body_data(data)
        elif data and mime_type == "text/html" and html is None:
            html = _decode_body_data(data)

        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return plain, html, attachments


def _shape_message(msg: dict[str, Any], *, include_body: bool = True) -> dict[str, Any]:
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
    if include_body:
        plain, html, attachments = _extract_bodies_and_attachments(payload)
        shaped["body_plain"] = plain
        shaped["body_html"] = html
        shaped["attachments"] = attachments
    return shaped


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
    async def get_message(message_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Fetch a single message by ID, including headers, body, and attachment metadata.

        Args:
            message_id: The Gmail message ID (from list_messages or get_thread).

        Returns:
            Message with id, thread_id, snippet, label_ids, headers (from/to/cc/bcc/
            subject/date/message_id), body_plain, body_html, and attachments metadata
            (filename, mime_type, size, attachment_id). On API failure, {"error": "..."}.
        """
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

        shaped = _shape_message(msg, include_body=True)
        enforce_response_size_cap(
            shaped,
            tool_name="get_message",
            hint="The message body is large; ",
            local_path_available=False,
        )
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
    async def get_thread(thread_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Fetch all messages in a conversation thread.

        Args:
            thread_id: The Gmail thread ID (from list_threads or a message's thread_id).

        Returns:
            Thread with id, snippet, history_id, and messages (same shape as get_message).
            On API failure, {"error": "..."}.
        """
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

        shaped = {
            "id": thread["id"],
            "snippet": thread.get("snippet"),
            "history_id": thread.get("historyId"),
            "messages": [_shape_message(m, include_body=True) for m in thread.get("messages", [])],
        }
        enforce_response_size_cap(
            shaped,
            tool_name="get_thread",
            hint="The thread is large; use get_message on individual IDs, or ",
            local_path_available=False,
        )
        return shaped

    @tool(annotations=ToolAnnotations(title="List Labels", readOnlyHint=True))
    async def list_labels(ctx: Context = None) -> list[dict[str, Any]] | dict[str, Any]:
        """
        List all labels in the authenticated user's mailbox (system and user-defined).

        Returns:
            List of labels with id, name, type, message_list_visibility, and
            label_list_visibility. On API failure, {"error": "..."}.
        """
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
            reply_all: When True, include the original To and Cc recipients
                       (except the authenticated mailbox) in addition to From.

        Returns:
            Sent message id, thread_id, and label_ids. On failure, {"error": "..."}.
        """
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

        if reply_all:
            mailbox = await _mailbox_email(lc.gmail_service)
            to, cc = _reply_all_recipients(
                original_from=original_from,
                original_to=original_to,
                original_cc=original_cc,
                mailbox=mailbox,
            )
        else:
            to = _format_address_header(original_from)
            cc = None

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
