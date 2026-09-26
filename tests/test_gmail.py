"""Tests for tools/gmail.py (list_messages, send_message, modify_labels, etc.)."""

import base64
import inspect
from email import message_from_bytes
from email.utils import getaddresses
from unittest.mock import MagicMock

import pytest

from mcp_gee_sweet import auth as auth_module
from mcp_gee_sweet.tools import gmail as gmail_module


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


def _raw_payload_from_send_call(gmail_svc) -> bytes:
    body = gmail_svc.users.return_value.messages.return_value.send.call_args.kwargs["body"]
    return base64.urlsafe_b64decode(body["raw"].encode("utf-8"))


_gmail_tool, _gmail_tools = _make_tool_registry()
gmail_module.register(_gmail_tool)


class TestGmailNotAuthorized:
    """#790 / PR #807 QA round 1: when the OAuth token lacks only the Gmail scope,
    the server still starts and every Gmail tool returns the re-authorize message
    as its error (a tool result the user can see) without touching the API."""

    @pytest.mark.parametrize("name", sorted(_gmail_tools))
    async def test_every_gmail_tool_returns_message_without_api_call(self, monkeypatch, name):
        monkeypatch.setattr(auth_module, "_gmail_unauthorized_message", "re-authorize please")
        fn = _gmail_tools[name]
        kwargs = {
            p.name: "x"
            for p in inspect.signature(fn).parameters.values()
            if p.default is inspect.Parameter.empty and p.name != "ctx"
        }
        gmail_svc = MagicMock()
        result = await fn(**kwargs, ctx=_make_ctx(gmail_service=gmail_svc))
        assert result == {"error": "re-authorize please"}
        gmail_svc.users.assert_not_called()

    async def test_unflagged_gmail_tool_calls_api(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_gmail_unauthorized_message", None)
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": []
        }
        await _gmail_tools["list_labels"](ctx=_make_ctx(gmail_service=gmail_svc))
        gmail_svc.users.assert_called()


class TestListMessages:
    async def test_passes_query_labels_and_maps_results(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t1"}],
            "nextPageToken": "page-2",
            "resultSizeEstimate": 42,
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["list_messages"](
            query="is:unread",
            label_ids=["INBOX"],
            max_results=10,
            page_token="page-1",
            ctx=ctx,
        )

        kwargs = gmail_svc.users.return_value.messages.return_value.list.call_args.kwargs
        assert kwargs["userId"] == "me"
        assert kwargs["q"] == "is:unread"
        assert kwargs["labelIds"] == ["INBOX"]
        assert kwargs["maxResults"] == 10
        assert kwargs["pageToken"] == "page-1"
        assert result["messages"] == [
            {"id": "m1", "thread_id": "t1"},
            {"id": "m2", "thread_id": "t1"},
        ]
        assert result["next_page_token"] == "page-2"
        assert result["result_size_estimate"] == 42

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            Exception("forbidden")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["list_messages"](ctx=ctx)

        assert "error" in result
        assert "forbidden" in result["error"]


class TestGetMessage:
    async def test_shapes_headers_body_and_attachments(self):
        plain_b64 = base64.urlsafe_b64encode(b"Hello plain").decode()
        html_b64 = base64.urlsafe_b64encode(b"<p>Hello</p>").decode()
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "m1",
            "threadId": "t1",
            "snippet": "Hello",
            "labelIds": ["INBOX"],
            "internalDate": "1700000000000",
            "sizeEstimate": 123,
            "payload": {
                "headers": [
                    {"name": "From", "value": "a@example.com"},
                    {"name": "Reply-To", "value": "r@example.com"},
                    {"name": "To", "value": "b@example.com"},
                    {"name": "Subject", "value": "Hi"},
                    {"name": "Message-ID", "value": "<mid@example.com>"},
                ],
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": plain_b64},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": html_b64},
                    },
                    {
                        "filename": "note.txt",
                        "mimeType": "text/plain",
                        "body": {"attachmentId": "att-1", "size": 4},
                    },
                ],
            },
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["id"] == "m1"
        assert result["thread_id"] == "t1"
        assert result["headers"]["from"] == "a@example.com"
        assert result["headers"]["reply_to"] == "r@example.com"
        assert result["headers"]["subject"] == "Hi"
        assert result["body_plain"] == "Hello plain"
        assert result["body_html"] == "<p>Hello</p>"
        assert result["attachments"][0]["filename"] == "note.txt"
        assert result["attachments"][0]["attachment_id"] == "att-1"
        gmail_svc.users.return_value.messages.return_value.get.assert_called_once_with(
            userId="me", id="m1", format="full"
        )

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.side_effect = (
            Exception("notFound")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="missing", ctx=ctx)

        assert "error" in result


def _b64(raw: bytes, *, pad: bool = True) -> str:
    encoded = base64.urlsafe_b64encode(raw).decode()
    return encoded if pad else encoded.rstrip("=")


def _single_part_message(data: str, content_type: str | None) -> dict:
    headers = [{"name": "Subject", "value": "s"}]
    if content_type is not None:
        headers.append({"name": "Content-Type", "value": content_type})
    return {
        "id": "m1",
        "threadId": "t1",
        "payload": {"mimeType": "text/plain", "headers": headers, "body": {"data": data}},
    }


class TestDecodeBody:
    """#792: honor the part's charset and tolerate missing base64 padding."""

    @pytest.mark.parametrize(
        ("text", "charset"),
        [
            ("Café crème, naïve", "ISO-8859-1"),
            ("\u201cSmart quotes\u201d \u2013 \u20ac5", "windows-1252"),
            ("こんにちは世界", "Shift_JIS"),
            ("Привет", "koi8-r"),
        ],
    )
    def test_decodes_using_declared_charset(self, text, charset):
        data = _b64(text.encode(charset))
        assert gmail_module._decode_body_data(data, charset) == text

    def test_no_charset_defaults_to_utf8(self):
        assert gmail_module._decode_body_data(_b64("héllo ✓".encode())) == "héllo ✓"

    def test_unknown_charset_falls_back_to_utf8(self):
        data = _b64("héllo".encode())
        assert gmail_module._decode_body_data(data, "x-not-a-real-charset") == "héllo"

    def test_mislabeled_ascii_retries_as_utf8(self):
        data = _b64("naïve".encode())
        assert gmail_module._decode_body_data(data, "us-ascii") == "naïve"

    def test_undecodable_bytes_use_replacement_chars(self):
        # 0xff is invalid in both us-ascii and utf-8.
        assert gmail_module._decode_body_data(_b64(b"a\xffb"), "us-ascii") == "a\ufffdb"

    @pytest.mark.parametrize("raw", [b"a", b"ab", b"abc", b"abcd", b"Hello plain"])
    def test_unpadded_input_decodes(self, raw):
        assert gmail_module._decode_body_data(_b64(raw, pad=False)) == raw.decode()

    def test_part_charset_reads_quoted_param_case_insensitively(self):
        part = {"headers": [{"name": "content-type", "value": 'text/plain; CHARSET="Shift_JIS"'}]}
        assert gmail_module._part_charset(part) == "shift_jis"

    def test_part_charset_absent(self):
        assert gmail_module._part_charset({"headers": [{"name": "Subject", "value": "x"}]}) is None
        assert gmail_module._part_charset({}) is None

    async def test_get_message_uses_each_parts_own_charset(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "m1",
            "threadId": "t1",
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [{"name": "Content-Type", "value": "multipart/alternative; boundary=x"}],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}
                        ],
                        "body": {"data": _b64("Café".encode("iso-8859-1"), pad=False)},
                    },
                    {
                        "mimeType": "text/html",
                        "headers": [
                            {"name": "Content-Type", "value": "text/html; charset=shift_jis"}
                        ],
                        "body": {"data": _b64("<p>日本</p>".encode("shift_jis"))},
                    },
                ],
            },
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "Café"
        assert result["body_html"] == "<p>日本</p>"

    async def test_get_message_corrupt_base64_returns_error_dict(self):
        gmail_svc = MagicMock()
        # 5 data characters: no amount of padding makes this valid base64.
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            _single_part_message("abcde", "text/plain; charset=utf-8")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert "error" in result
        assert "m1" in result["error"]

    async def test_get_thread_unpadded_body_decodes(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [_single_part_message(_b64(b"ab", pad=False), None)],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

        assert result["messages"][0]["body_plain"] == "ab"

    async def test_get_thread_corrupt_base64_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [_single_part_message("abcde", None)],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

        assert "error" in result
        assert "t1" in result["error"]


class TestListThreads:
    async def test_maps_threads_and_pagination(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "t1", "snippet": "hi", "historyId": "99"}],
            "resultSizeEstimate": 1,
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["list_threads"](query="from:me", ctx=ctx)

        kwargs = gmail_svc.users.return_value.threads.return_value.list.call_args.kwargs
        assert kwargs["q"] == "from:me"
        assert result["threads"] == [{"id": "t1", "snippet": "hi", "history_id": "99"}]
        assert "next_page_token" not in result

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.list.return_value.execute.side_effect = (
            Exception("boom")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["list_threads"](ctx=ctx)

        assert "error" in result


class TestGetThread:
    async def test_shapes_all_messages(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "snippet": "thread",
            "historyId": "5",
            "messages": [
                {
                    "id": "m1",
                    "threadId": "t1",
                    "snippet": "one",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [{"name": "Subject", "value": "One"}],
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"one").decode()},
                    },
                }
            ],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

        assert result["id"] == "t1"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["body_plain"] == "one"
        assert result["messages"][0]["headers"]["subject"] == "One"

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.side_effect = (
            Exception("notFound")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="missing", ctx=ctx)

        assert "error" in result


class TestListLabels:
    async def test_maps_system_and_user_labels(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": [
                {"id": "INBOX", "name": "INBOX", "type": "system"},
                {
                    "id": "Label_1",
                    "name": "Work",
                    "type": "user",
                    "messageListVisibility": "show",
                    "labelListVisibility": "labelShow",
                },
            ]
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["list_labels"](ctx=ctx)

        assert result[0]["id"] == "INBOX"
        assert result[1]["name"] == "Work"
        assert result[1]["type"] == "user"

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.labels.return_value.list.return_value.execute.side_effect = (
            Exception("denied")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["list_labels"](ctx=ctx)

        assert "error" in result


class TestSendMessage:
    async def test_builds_raw_mime_and_maps_response(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "sent-1",
            "threadId": "t-new",
            "labelIds": ["SENT"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["send_message"](
            to="bob@example.com",
            subject="Hello",
            body="Hi Bob",
            cc="cc@example.com",
            ctx=ctx,
        )

        raw = _raw_payload_from_send_call(gmail_svc)
        parsed = message_from_bytes(raw)
        assert parsed["To"] == "bob@example.com"
        assert parsed["Subject"] == "Hello"
        assert parsed["Cc"] == "cc@example.com"
        assert result == {"id": "sent-1", "thread_id": "t-new", "label_ids": ["SENT"]}

    async def test_encodes_non_ascii_display_names_without_mangling_address(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "sent-2",
            "threadId": "t-new",
            "labelIds": ["SENT"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["send_message"](
            to="José García <jose@example.com>",
            subject="Hola",
            body="Hi",
            ctx=ctx,
        )

        raw = _raw_payload_from_send_call(gmail_svc)
        # Address must remain cleartext ASCII even when the display name is encoded.
        assert b"jose@example.com" in raw
        assert b"=?utf-8?" in raw.lower() or b"=?UTF-8?" in raw
        parsed = message_from_bytes(raw)
        assert "jose@example.com" in parsed["To"]
        assert result["id"] == "sent-2"

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.send.return_value.execute.side_effect = (
            Exception("quotaExceeded")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["send_message"](
            to="bob@example.com", subject="Hi", body="x", ctx=ctx
        )

        assert "error" in result


class TestCreateDraft:
    async def test_creates_draft_with_message_wrapper(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "d1",
            "message": {"id": "m-draft", "threadId": "t1", "labelIds": ["DRAFT"]},
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["create_draft"](
            to="bob@example.com", subject="Draft", body="later", ctx=ctx
        )

        body = gmail_svc.users.return_value.drafts.return_value.create.call_args.kwargs["body"]
        assert "raw" in body["message"]
        assert result["id"] == "d1"
        assert result["message"]["id"] == "m-draft"

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.drafts.return_value.create.return_value.execute.side_effect = (
            Exception("fail")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["create_draft"](
            to="bob@example.com", subject="Draft", body="later", ctx=ctx
        )

        assert "error" in result


class TestSendDraft:
    async def test_sends_by_draft_id(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.drafts.return_value.send.return_value.execute.return_value = {
            "id": "sent-d",
            "threadId": "t1",
            "labelIds": ["SENT"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["send_draft"](draft_id="d1", ctx=ctx)

        kwargs = gmail_svc.users.return_value.drafts.return_value.send.call_args.kwargs
        assert kwargs["body"] == {"id": "d1"}
        assert result["id"] == "sent-d"

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.drafts.return_value.send.return_value.execute.side_effect = (
            Exception("notFound")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["send_draft"](draft_id="missing", ctx=ctx)

        assert "error" in result


class TestReplyToMessage:
    async def test_sets_reply_headers_and_thread_id(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "m1",
            "threadId": "t1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "To", "value": "me@example.com"},
                    {"name": "Cc", "value": "cc@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Message-ID", "value": "<orig@example.com>"},
                    {"name": "References", "value": "<earlier@example.com>"},
                ]
            },
        }
        gmail_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply-1",
            "threadId": "t1",
            "labelIds": ["SENT"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["reply_to_message"](message_id="m1", body="Thanks", ctx=ctx)

        send_body = gmail_svc.users.return_value.messages.return_value.send.call_args.kwargs["body"]
        assert send_body["threadId"] == "t1"
        parsed = message_from_bytes(base64.urlsafe_b64decode(send_body["raw"].encode("utf-8")))
        assert parsed["To"] == "alice@example.com"
        assert parsed["Subject"] == "Re: Hello"
        assert parsed["In-Reply-To"] == "<orig@example.com>"
        assert "<earlier@example.com>" in parsed["References"]
        assert "<orig@example.com>" in parsed["References"]
        assert result["id"] == "reply-1"

    async def test_reply_all_excludes_authenticated_mailbox(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "me@example.com",
        }
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "m1",
            "threadId": "t1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "To", "value": "Me <me@example.com>, Bob <bob@example.com>"},
                    {"name": "Cc", "value": "Carol <carol@example.com>, me@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Message-ID", "value": "<orig@example.com>"},
                ]
            },
        }
        gmail_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply-all-1",
            "threadId": "t1",
            "labelIds": ["SENT"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["reply_to_message"](
            message_id="m1", body="Thanks all", reply_all=True, ctx=ctx
        )

        gmail_svc.users.return_value.getProfile.assert_called_once_with(userId="me")
        send_body = gmail_svc.users.return_value.messages.return_value.send.call_args.kwargs["body"]
        parsed = message_from_bytes(base64.urlsafe_b64decode(send_body["raw"].encode("utf-8")))
        to_addrs = {addr.lower() for _, addr in getaddresses([parsed["To"] or ""]) if addr}
        cc_addrs = {addr.lower() for _, addr in getaddresses([parsed["Cc"] or ""]) if addr}
        assert "me@example.com" not in to_addrs
        assert "me@example.com" not in cc_addrs
        assert "alice@example.com" in to_addrs
        assert "bob@example.com" in to_addrs
        assert "carol@example.com" in cc_addrs
        assert result["id"] == "reply-all-1"

    async def test_api_error_on_fetch_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.side_effect = (
            Exception("notFound")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["reply_to_message"](
            message_id="missing", body="Thanks", ctx=ctx
        )

        assert "error" in result


def _reply_recipients_for(
    headers, *, label_ids=None, reply_all=False, mailbox="me@example.com", aliases=()
):
    """Run reply_to_message against a stubbed original; return (To, Cc) address sets."""
    gmail_svc = MagicMock()
    gmail_svc.users.return_value.settings.return_value.sendAs.return_value.list.return_value.execute.return_value = {
        "sendAs": [{"sendAsEmail": a} for a in (mailbox, *aliases)],
    }
    gmail_svc.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": mailbox,
    }
    gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": label_ids or ["INBOX"],
        "payload": {
            "headers": [{"name": k, "value": v} for k, v in headers.items()]
            + [{"name": "Subject", "value": "Hi"}, {"name": "Message-ID", "value": "<o@x>"}]
        },
    }
    gmail_svc.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "r1",
        "threadId": "t1",
    }
    ctx = _make_ctx(gmail_service=gmail_svc)

    async def run():
        result = await _gmail_tools["reply_to_message"](
            message_id="m1", body="ok", reply_all=reply_all, ctx=ctx
        )
        assert "error" not in result, result
        parsed = message_from_bytes(_raw_payload_from_send_call(gmail_svc))
        to = {a.lower() for _, a in getaddresses([parsed["To"] or ""]) if a}
        cc = {a.lower() for _, a in getaddresses([parsed["Cc"] or ""]) if a}
        return to, cc, gmail_svc

    return run()


class TestReplyRecipients:
    """#791: resolve reply recipients like a standard mail client."""

    async def test_reply_to_header_wins_over_from(self):
        to, cc, _ = await _reply_recipients_for(
            {
                "From": "No Reply <noreply@vendor.example>",
                "Reply-To": "Support <support@vendor.example>",
                "To": "me@example.com",
            }
        )
        assert to == {"support@vendor.example"}
        assert cc == set()

    async def test_plain_reply_without_reply_to_uses_from(self):
        to, _, gmail_svc = await _reply_recipients_for(
            {"From": "alice@example.com", "To": "me@example.com"}
        )
        assert to == {"alice@example.com"}
        # sendAs.list includes the primary address, so no getProfile fallback.
        gmail_svc.users.return_value.getProfile.assert_not_called()

    async def test_plain_reply_drops_own_address(self):
        # QA round 1 finding 1 (reproduced live): own message To: me, me+x.
        to, _, _ = await _reply_recipients_for(
            {"From": "me@example.com", "To": "me@example.com, bob@example.com"},
            label_ids=["SENT"],
        )
        assert to == {"bob@example.com"}

    async def test_plain_reply_drops_own_address_from_reply_to(self):
        to, _, _ = await _reply_recipients_for(
            {
                "From": "alice@example.com",
                "Reply-To": "me@example.com, team@example.com",
                "To": "me@example.com",
            }
        )
        assert to == {"team@example.com"}

    async def test_plain_reply_detects_own_message_by_address_without_sent_label(self):
        # Finding 3: a message the mailbox sent from another client, without SENT.
        to, _, _ = await _reply_recipients_for(
            {"From": "Me <ME@example.com>", "To": "bob@example.com"},
        )
        assert to == {"bob@example.com"}

    async def test_own_cc_only_message_plain_reply_goes_to_cc(self):
        # Finding 2 (reproduced live): own message with only a Cc, no To.
        to, cc, _ = await _reply_recipients_for(
            {"From": "me@example.com", "Cc": "carol@example.com"},
            label_ids=["SENT"],
        )
        assert to == {"carol@example.com"}
        assert cc == set()

    async def test_own_cc_only_message_reply_all_promotes_cc_and_excludes_self(self):
        to, cc, _ = await _reply_recipients_for(
            {"From": "me@example.com", "Cc": "carol@example.com"},
            label_ids=["SENT"],
            reply_all=True,
        )
        assert to == {"carol@example.com"}
        assert cc == set()

    async def test_reply_to_self_falls_back_to_reply_to_not_noreply_from(self):
        # Finding 4: plain reply and reply_all must agree, and never pick the
        # no-reply From that Reply-To exists to avoid.
        headers = {
            "From": "noreply@tool.example",
            "Reply-To": "me@example.com",
            "To": "me@example.com",
        }
        plain_to, _, _ = await _reply_recipients_for(headers)
        all_to, all_cc, _ = await _reply_recipients_for(headers, reply_all=True)
        assert plain_to == all_to == {"me@example.com"}
        assert all_cc == set()

    async def test_send_as_aliases_are_excluded_and_mark_own_mail(self):
        # Finding 5: aliases from sendAs.list count as the mailbox.
        to, cc, _ = await _reply_recipients_for(
            {
                "From": "Work Me <me@work.example>",
                "To": "bob@example.com, me@example.com",
                "Cc": "me@work.example, carol@example.com",
            },
            reply_all=True,
            aliases=("me@work.example",),
        )
        assert to == {"bob@example.com"}
        assert cc == {"carol@example.com"}

    async def test_send_as_failure_falls_back_to_profile(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.settings.return_value.sendAs.return_value.list.return_value.execute.side_effect = Exception(
            "forbidden"
        )
        gmail_svc.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "Me@Example.com",
        }
        assert await gmail_module._own_addresses(gmail_svc) == {"me@example.com"}

    async def test_reply_to_with_multiple_addresses_keeps_all(self):
        to, _, _ = await _reply_recipients_for(
            {
                "From": "alice@example.com",
                "Reply-To": "a@example.com, b@example.com",
                "To": "me@example.com",
            }
        )
        assert to == {"a@example.com", "b@example.com"}

    async def test_reply_all_uses_reply_to_instead_of_from(self):
        # Mailing-list shape: From is the poster, Reply-To and To are the list.
        to, cc, _ = await _reply_recipients_for(
            {
                "From": "poster@example.com",
                "Reply-To": "list@lists.example",
                "To": "list@lists.example",
                "Cc": "me@example.com, carol@example.com",
            },
            reply_all=True,
        )
        assert to == {"list@lists.example"}
        assert cc == {"carol@example.com"}

    async def test_reply_to_own_sent_message_goes_to_original_to(self):
        to, _, _ = await _reply_recipients_for(
            {"From": "Me <me@example.com>", "To": "Bob <bob@example.com>"},
            label_ids=["SENT"],
        )
        assert to == {"bob@example.com"}

    async def test_own_sent_message_ignores_its_own_reply_to(self):
        to, _, _ = await _reply_recipients_for(
            {
                "From": "me@example.com",
                "Reply-To": "team@example.com",
                "To": "bob@example.com",
            },
            label_ids=["SENT"],
        )
        assert to == {"bob@example.com"}

    async def test_reply_all_to_own_sent_message(self):
        to, cc, _ = await _reply_recipients_for(
            {
                "From": "me@example.com",
                "To": "bob@example.com, dan@example.com",
                "Cc": "carol@example.com, me@example.com",
            },
            label_ids=["SENT"],
            reply_all=True,
        )
        assert to == {"bob@example.com", "dan@example.com"}
        assert cc == {"carol@example.com"}

    async def test_reply_all_detects_own_message_by_address_without_sent_label(self):
        # e.g. a message the mailbox sent from another client, filed without SENT.
        to, _, _ = await _reply_recipients_for(
            {"From": "Me <ME@example.com>", "To": "bob@example.com"},
            reply_all=True,
        )
        assert to == {"bob@example.com"}

    async def test_message_sent_only_to_self_falls_back_to_self(self):
        to, _, _ = await _reply_recipients_for(
            {"From": "me@example.com", "To": "me@example.com"},
            label_ids=["SENT", "INBOX"],
            reply_all=True,
        )
        assert to == {"me@example.com"}

    async def test_message_to_self_with_cc_goes_to_cc_not_self(self):
        # Companion to the above: the self fallback applies only when nobody else
        # is on the message, so it never swallows a Cc'd person.
        for reply_all in (False, True):
            to, cc, _ = await _reply_recipients_for(
                {"From": "me@example.com", "To": "me@example.com", "Cc": "carol@example.com"},
                label_ids=["SENT", "INBOX"],
                reply_all=reply_all,
            )
            assert to == {"carol@example.com"}, reply_all
            assert cc == set()


class TestModifyLabels:
    async def test_modifies_message_labels(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.modify.return_value.execute.return_value = {
            "id": "m1",
            "threadId": "t1",
            "labelIds": ["INBOX"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["modify_labels"](
            message_id="m1", remove_label_ids=["UNREAD"], ctx=ctx
        )

        kwargs = gmail_svc.users.return_value.messages.return_value.modify.call_args.kwargs
        assert kwargs["id"] == "m1"
        assert kwargs["body"] == {"removeLabelIds": ["UNREAD"]}
        assert result["label_ids"] == ["INBOX"]

    async def test_modifies_thread_labels(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.modify.return_value.execute.return_value = {
            "id": "t1",
            "messages": [{"id": "m1", "labelIds": ["STARRED"]}],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["modify_labels"](
            thread_id="t1", add_label_ids=["STARRED"], ctx=ctx
        )

        assert result["id"] == "t1"
        assert result["messages"][0]["label_ids"] == ["STARRED"]

    async def test_rejects_missing_target(self):
        ctx = _make_ctx(gmail_service=MagicMock())

        result = await _gmail_tools["modify_labels"](add_label_ids=["STARRED"], ctx=ctx)

        assert "error" in result
        assert "exactly one" in result["error"]

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.modify.return_value.execute.side_effect = Exception(
            "invalid"
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["modify_labels"](
            message_id="m1", add_label_ids=["STARRED"], ctx=ctx
        )

        assert "error" in result


class TestTrashMessage:
    async def test_trashes_and_maps_response(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.trash.return_value.execute.return_value = {
            "id": "m1",
            "threadId": "t1",
            "labelIds": ["TRASH"],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["trash_message"](message_id="m1", ctx=ctx)

        assert result == {
            "id": "m1",
            "thread_id": "t1",
            "label_ids": ["TRASH"],
            "action": "trashed",
        }

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.trash.return_value.execute.side_effect = Exception(
            "notFound"
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["trash_message"](message_id="missing", ctx=ctx)

        assert "error" in result
