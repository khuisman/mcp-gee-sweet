"""Tests for tools/gmail.py (list_messages, send_message, modify_labels, etc.)."""

import base64
import binascii
import codecs
import contextlib
import encodings.aliases
import inspect
import json
import random
import threading
import time
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


def _text_part(
    mime_type: str, data: str, *, charset: str | None = None, part_id: str = "0"
) -> dict:
    headers = []
    if charset is not None:
        headers.append({"name": "Content-Type", "value": f"{mime_type}; charset={charset}"})
    return {"partId": part_id, "mimeType": mime_type, "headers": headers, "body": {"data": data}}


def _message(msg_id: str, *parts: dict) -> dict:
    return {
        "id": msg_id,
        "threadId": "t1",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": f"subject {msg_id}"}],
            "parts": list(parts),
        },
    }


# 5 base64 characters: no amount of padding makes this valid.
_CORRUPT_B64 = "abcde"


class TestDecodeBody:
    """#792 / PR #816: always UTF-8 (Gmail pre-transcodes), tolerant of missing padding."""

    @pytest.mark.parametrize("charset", ["iso-8859-1", "windows-1252", "shift_jis", "koi8-r"])
    async def test_declared_non_utf8_charset_is_ignored(self, charset):
        # The Gmail API transcodes body.data to UTF-8 but keeps the original charset
        # label, so the label must not drive decoding (confirmed live, PR #816 QA).
        text = "Café “quotes” こんにちは Привет"
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            _message("m1", _text_part("text/plain", _b64(text.encode("utf-8")), charset=charset))
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == text
        assert "body_decode_errors" not in result

    def test_invalid_utf8_uses_replacement_chars(self):
        assert gmail_module._decode_body_data(_b64(b"a\xffb")) == "a�b"

    @pytest.mark.parametrize("raw", [b"a", b"ab", b"abc", b"abcd", b"Hello plain"])
    def test_unpadded_input_decodes(self, raw):
        assert gmail_module._decode_body_data(_b64(raw, pad=False)) == raw.decode()

    @pytest.mark.parametrize("data", ["YWJj\nZA", "YWJj\r\nZA", " YWJjZA ", "YWJj ZA=="])
    def test_whitespace_does_not_skew_padding(self, data):
        assert gmail_module._decode_body_data(data) == "abcd"

    def test_irreparable_data_raises_binascii_error(self):
        with pytest.raises(binascii.Error):
            gmail_module._decode_body_data(_CORRUPT_B64)

    async def test_get_message_corrupt_part_keeps_rest_of_message(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            _message(
                "m1",
                _text_part("text/plain", _CORRUPT_B64, part_id="0"),
                _text_part("text/html", _b64(b"<p>ok</p>"), part_id="1"),
                {
                    "partId": "2",
                    "filename": "note.txt",
                    "mimeType": "text/plain",
                    "body": {"attachmentId": "att-1", "size": 4},
                },
            )
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert "error" not in result
        assert result["headers"]["subject"] == "subject m1"
        assert result["body_plain"] is None
        assert result["body_html"] == "<p>ok</p>"
        assert result["attachments"][0]["attachment_id"] == "att-1"
        assert len(result["body_decode_errors"]) == 1
        assert result["body_decode_errors"][0]["part_id"] == "0"
        assert result["body_decode_errors"][0]["mime_type"] == "text/plain"

    async def test_later_part_of_same_type_fills_body_after_corrupt_one(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            _message(
                "m1",
                _text_part("text/plain", _CORRUPT_B64, part_id="0"),
                _text_part("text/plain", _b64(b"second"), part_id="1"),
            )
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "second"
        assert [e["part_id"] for e in result["body_decode_errors"]] == ["0"]

    async def test_get_thread_corrupt_message_does_not_fail_thread(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [
                _message("m1", _text_part("text/plain", _CORRUPT_B64)),
                _message("m2", _text_part("text/plain", _b64(b"ab", pad=False))),
            ],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

        assert "error" not in result
        first, second = result["messages"]
        assert first["body_plain"] is None
        assert first["body_decode_errors"][0]["mime_type"] == "text/plain"
        assert second["body_plain"] == "ab"
        assert "body_decode_errors" not in second


def _deferred_part(
    mime_type: str,
    attachment_id: str,
    *,
    part_id: str = "0",
    charset: str | None = "UTF-8",
    disposition: str | None = None,
    filename: str = "",
    size: int = 1000,
) -> dict:
    """A text part as Gmail delivers a large body: attachmentId, no data (#825)."""
    headers = []
    if charset is not None:
        headers.append({"name": "Content-Type", "value": f'{mime_type}; charset="{charset}"'})
    if disposition is not None:
        headers.append({"name": "Content-Disposition", "value": disposition})
    return {
        "partId": part_id,
        "mimeType": mime_type,
        "filename": filename,
        "headers": headers,
        "body": {"attachmentId": attachment_id, "size": size},
    }


def _gmail_with_attachments(
    message: dict | None = None, data_by_id: dict[str, str | Exception] | None = None
) -> MagicMock:
    """A gmail service whose attachments.get returns data_by_id[id]; an Exception
    value is raised instead."""
    data_by_id = data_by_id or {}
    gmail_svc = MagicMock()
    messages = gmail_svc.users.return_value.messages.return_value
    if message is not None:
        messages.get.return_value.execute.return_value = message

    def get(userId, messageId, id):
        req = MagicMock()
        value = data_by_id[id]
        if isinstance(value, Exception):
            req.execute.side_effect = value
        else:
            req.execute.return_value = {"size": len(value), "data": value}
        return req

    messages.attachments.return_value.get.side_effect = get
    return gmail_svc


class TestDeferredBody:
    """#825: Gmail delivers a large text body by attachmentId, with no inline data."""

    async def test_plain_and_html_are_fetched_and_not_listed_as_attachments(self):
        msg = _message(
            "m1",
            _deferred_part("text/plain", "att-plain", part_id="0"),
            _deferred_part("text/html", "att-html", part_id="1"),
        )
        gmail_svc = _gmail_with_attachments(
            msg, {"att-plain": _b64(b"big plain"), "att-html": _b64(b"<p>big</p>")}
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "big plain"
        assert result["body_html"] == "<p>big</p>"
        assert result["attachments"] == []
        assert "body_fetch_errors" not in result
        get = gmail_svc.users.return_value.messages.return_value.attachments.return_value.get
        assert sorted(c.kwargs["id"] for c in get.call_args_list) == ["att-html", "att-plain"]
        assert {c.kwargs["messageId"] for c in get.call_args_list} == {"m1"}

    async def test_single_part_message_body_is_fetched(self):
        msg = {
            "id": "m1",
            "threadId": "t1",
            "payload": {
                **_deferred_part("text/plain", "att-1", part_id=""),
                "headers": [
                    {"name": "Subject", "value": "big"},
                    {"name": "Content-Type", "value": "text/plain; charset=UTF-8"},
                ],
            },
        }
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _b64(b"whole body")})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "whole body"
        assert result["headers"]["subject"] == "big"
        assert result["attachments"] == []

    @pytest.mark.parametrize("charset", ["iso-8859-1", "windows-1252", "shift_jis", "koi8-r"])
    async def test_fetched_body_decodes_with_declared_charset(self, charset):
        # Unlike inline body.data, attachments.get returns the part's raw bytes
        # untranscoded (confirmed live on #825: latin-1 "Café" arrives as Caf\xe9).
        text = {"shift_jis": "こんにちは", "koi8-r": "Привет"}.get(charset, "Café crème")
        msg = _message("m1", _deferred_part("text/plain", "att-1", charset=charset))
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _b64(text.encode(charset))})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == text

    @pytest.mark.parametrize("charset", [None, "x-no-such-charset"])
    async def test_missing_or_unknown_charset_falls_back_to_utf8(self, charset):
        msg = _message("m1", _deferred_part("text/plain", "att-1", charset=charset))
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _b64("Café".encode())})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "Café"

    @pytest.mark.parametrize(
        "part",
        [
            _deferred_part("text/plain", "att-1", disposition="attachment"),
            _deferred_part("text/plain", "att-1", filename="notes.txt"),
            _deferred_part("text/csv", "att-1"),
        ],
        ids=["disposition-attachment", "named", "not-a-body-type"],
    )
    async def test_real_attachments_are_not_fetched(self, part):
        gmail_svc = _gmail_with_attachments(_message("m1", part))
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] is None
        assert [a["attachment_id"] for a in result["attachments"]] == ["att-1"]
        attachments = gmail_svc.users.return_value.messages.return_value.attachments
        attachments.return_value.get.assert_not_called()

    async def test_inline_body_first_wins_over_later_deferred_part(self):
        msg = _message(
            "m1",
            _text_part("text/plain", _b64(b"inline"), part_id="0"),
            _deferred_part("text/plain", "att-1", part_id="1"),
        )
        gmail_svc = _gmail_with_attachments(msg)
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "inline"
        assert [a["attachment_id"] for a in result["attachments"]] == ["att-1"]
        attachments = gmail_svc.users.return_value.messages.return_value.attachments
        attachments.return_value.get.assert_not_called()

    async def test_deferred_body_first_wins_over_later_inline_part(self):
        msg = _message(
            "m1",
            _deferred_part("text/plain", "att-1", part_id="0"),
            _text_part("text/plain", _b64(b"inline"), part_id="1"),
        )
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _b64(b"deferred")})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "deferred"

    async def test_fetch_failure_keeps_rest_of_message(self):
        msg = _message(
            "m1",
            _deferred_part("text/plain", "att-plain", part_id="0"),
            _deferred_part("text/html", "att-html", part_id="1"),
        )
        gmail_svc = _gmail_with_attachments(
            msg, {"att-plain": Exception("backendError"), "att-html": _b64(b"<p>ok</p>")}
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert "error" not in result
        assert result["body_plain"] is None
        assert result["body_html"] == "<p>ok</p>"
        assert result["body_fetch_errors"] == [
            {
                "part_id": "0",
                "mime_type": "text/plain",
                "attachment_id": "att-plain",
                "error": "backendError",
            }
        ]
        assert "body_decode_errors" not in result

    async def test_corrupt_fetched_data_is_a_decode_error(self):
        msg = _message("m1", _deferred_part("text/plain", "att-1", part_id="0"))
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _CORRUPT_B64})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] is None
        assert result["body_decode_errors"][0]["part_id"] == "0"
        assert "body_fetch_errors" not in result

    async def test_fetch_failure_falls_back_to_later_inline_part(self):
        msg = _message(
            "m1",
            _deferred_part("text/plain", "att-1", part_id="0"),
            _text_part("text/plain", _b64(b"inline fallback"), part_id="1"),
        )
        gmail_svc = _gmail_with_attachments(msg, {"att-1": Exception("backendError")})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "inline fallback"
        assert result["body_fetch_errors"][0]["attachment_id"] == "att-1"

    async def test_unused_fallback_part_is_not_decoded(self):
        # A later corrupt inline part only matters if the fetch fails.
        msg = _message(
            "m1",
            _deferred_part("text/plain", "att-1", part_id="0"),
            _text_part("text/plain", _CORRUPT_B64, part_id="1"),
        )
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _b64(b"fetched")})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "fetched"
        assert "body_decode_errors" not in result

    @pytest.mark.parametrize("response", [{}, {"size": 10}, {"size": 10, "data": ""}, None])
    async def test_missing_data_is_a_fetch_error(self, response):
        msg = _message("m1", _deferred_part("text/plain", "att-1", part_id="0"))
        gmail_svc = _gmail_with_attachments(msg)
        attachments = gmail_svc.users.return_value.messages.return_value.attachments
        attachments.return_value.get.side_effect = None
        attachments.return_value.get.return_value.execute.return_value = response
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] is None
        assert result["body_fetch_errors"] == [
            {
                "part_id": "0",
                "mime_type": "text/plain",
                "attachment_id": "att-1",
                "error": "attachments.get returned no data",
            }
        ]

    async def test_part_inside_attached_rfc822_is_not_a_body(self):
        forwarded = {
            "partId": "1",
            "mimeType": "message/rfc822",
            "filename": "",
            "body": {"size": 0},
            "parts": [
                {
                    "partId": "1.0",
                    "mimeType": "multipart/alternative",
                    "parts": [_deferred_part("text/html", "att-inner", part_id="1.0.1")],
                }
            ],
        }
        msg = _message("m1", _text_part("text/plain", _b64(b"outer"), part_id="0"), forwarded)
        gmail_svc = _gmail_with_attachments(msg)
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == "outer"
        assert result["body_html"] is None
        assert [a["attachment_id"] for a in result["attachments"]] == ["att-inner"]
        attachments = gmail_svc.users.return_value.messages.return_value.attachments
        attachments.return_value.get.assert_not_called()

    @pytest.mark.parametrize(
        ("label", "raw", "expected"),
        [
            ("us-ascii", "Café “quoted”".encode(), "Café “quoted”"),
            ("iso-8859-1", "“Smart” \u2013 quotes".encode("cp1252"), "“Smart” \u2013 quotes"),
            ("latin1", "Café\u2019s".encode("cp1252"), "Café\u2019s"),
        ],
    )
    async def test_common_charset_mislabels_are_remapped(self, label, raw, expected):
        msg = _message("m1", _deferred_part("text/plain", "att-1", charset=label))
        gmail_svc = _gmail_with_attachments(msg, {"att-1": _b64(raw)})
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        assert result["body_plain"] == expected

    @pytest.mark.parametrize("charset", ["idna", "base64", "rot13"])
    def test_non_text_codecs_fall_back_to_utf8(self, charset):
        assert gmail_module._decode_body_data(_b64("Café".encode()), charset) == "Café"

    async def test_thread_fetches_are_bounded(self, monkeypatch):
        monkeypatch.setattr(gmail_module, "_BODY_FETCH_CONCURRENCY", 3)
        lock = threading.Lock()
        in_flight = 0
        peak = 0

        def slow_execute(**_kwargs):
            nonlocal in_flight, peak
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(0.02)
            with lock:
                in_flight -= 1
            return {"size": 1, "data": _b64(b"x")}

        gmail_svc = MagicMock()
        attachments = gmail_svc.users.return_value.messages.return_value.attachments
        attachments.return_value.get.return_value.execute.side_effect = slow_execute
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [
                _message(
                    f"m{i}",
                    _deferred_part("text/plain", f"p{i}", part_id="0"),
                    _deferred_part("text/html", f"h{i}", part_id="1"),
                )
                for i in range(6)
            ],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

        assert [m["body_plain"] for m in result["messages"]] == ["x"] * 6
        assert attachments.return_value.get.return_value.execute.call_count == 12
        assert peak == 3

    async def test_get_thread_fetches_each_messages_deferred_body(self):
        gmail_svc = _gmail_with_attachments(
            None, {"att-a": _b64(b"body a"), "att-b": _b64(b"body b")}
        )
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [
                _message("m1", _deferred_part("text/plain", "att-a")),
                _message("m2", _deferred_part("text/plain", "att-b")),
            ],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

        assert [m["body_plain"] for m in result["messages"]] == ["body a", "body b"]
        get = gmail_svc.users.return_value.messages.return_value.attachments.return_value.get
        assert sorted((c.kwargs["messageId"], c.kwargs["id"]) for c in get.call_args_list) == [
            ("m1", "att-a"),
            ("m2", "att-b"),
        ]


class TestMessageSizeCap:
    """#825: a fetched large body goes through the normal cap, with a local_path bypass."""

    @pytest.fixture
    def small_cap(self, monkeypatch):
        from mcp_gee_sweet.tools import response_limits

        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 200)

    def _large(self) -> MagicMock:
        return _gmail_with_attachments(
            _message("m1", _deferred_part("text/plain", "att-1")), {"att-1": _b64(b"x" * 500)}
        )

    async def test_get_message_over_cap_raises_and_names_local_path(self, small_cap):
        ctx = _make_ctx(gmail_service=self._large())

        with pytest.raises(ValueError, match=r"get_message.*Pass local_path"):
            await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

    async def test_get_message_local_path_writes_full_message(self, small_cap, tmp_path):
        ctx = _make_ctx(gmail_service=self._large())

        result = await _gmail_tools["get_message"](
            message_id="m1", local_path=str(tmp_path), ctx=ctx
        )

        dest = tmp_path / "message_m1.json"
        assert result == {
            "local_path": str(dest),
            "bytes_written": dest.stat().st_size,
            "message_id": "m1",
        }
        assert json.loads(dest.read_text())["body_plain"] == "x" * 500

    async def test_over_cap_deferred_bodies_are_not_downloaded(self, small_cap):
        gmail_svc = self._large()
        ctx = _make_ctx(gmail_service=gmail_svc)

        with pytest.raises(ValueError, match=r"would be at least 1000 characters"):
            await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

        attachments = gmail_svc.users.return_value.messages.return_value.attachments
        attachments.return_value.get.assert_not_called()

    @pytest.mark.parametrize(
        ("charset", "text"),
        [
            ("utf-16", "plain ascii body " * 60),
            ("utf-32", "plain ascii body " * 60),
            # Alternating scripts force an escape sequence around every character.
            ("iso-2022-jp", "a\u6f22" * 600),
        ],
        ids=["utf-16", "utf-32", "iso-2022-jp"],
    )
    async def test_floor_ignores_codecs_whose_bytes_overstate_size(
        self, monkeypatch, charset, text
    ):
        # PR #829 QA round 2: body.size counts bytes in the part's own charset, which
        # for these codecs exceeds the serialized size, so the floor must not use it.
        from mcp_gee_sweet.tools import response_limits

        raw = text.encode(charset)

        def service():
            return _gmail_with_attachments(
                _message(
                    "m1", _deferred_part("text/plain", "att-1", charset=charset, size=len(raw))
                ),
                {"att-1": _b64(raw)},
            )

        full = await _gmail_tools["get_message"](
            message_id="m1", ctx=_make_ctx(gmail_service=service())
        )
        assert full["body_plain"] == text
        serialized = len(json.dumps(full))
        assert len(raw) > serialized  # the regression's precondition
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", serialized)

        result = await _gmail_tools["get_message"](
            message_id="m1", ctx=_make_ctx(gmail_service=service())
        )

        assert result["body_plain"] == text

    async def test_post_fetch_cap_still_applies_when_size_underreported(self, small_cap):
        gmail_svc = _gmail_with_attachments(
            _message("m1", _deferred_part("text/plain", "att-1", size=10)),
            {"att-1": _b64(b"x" * 500)},
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        with pytest.raises(ValueError, match=r"get_message: the response is \d+ characters"):
            await _gmail_tools["get_message"](message_id="m1", ctx=ctx)

    async def test_get_message_manifest_surfaces_body_errors(self, tmp_path):
        gmail_svc = _gmail_with_attachments(
            _message("m1", _deferred_part("text/plain", "att-1", part_id="0")),
            {"att-1": Exception("backendError")},
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_message"](
            message_id="m1", local_path=str(tmp_path), ctx=ctx
        )

        assert result["body_fetch_errors"] == [
            {
                "message_id": "m1",
                "part_id": "0",
                "mime_type": "text/plain",
                "attachment_id": "att-1",
                "error": "backendError",
            }
        ]
        assert "body_decode_errors" not in result

    async def test_get_thread_manifest_surfaces_each_messages_errors(self, tmp_path):
        gmail_svc = _gmail_with_attachments(
            None, {"att-a": Exception("backendError"), "att-b": _CORRUPT_B64}
        )
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [
                _message("m1", _deferred_part("text/plain", "att-a")),
                _message("m2", _deferred_part("text/plain", "att-b")),
            ],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["get_thread"](thread_id="t1", local_path=str(tmp_path), ctx=ctx)

        assert [(e["message_id"], e["attachment_id"]) for e in result["body_fetch_errors"]] == [
            ("m1", "att-a")
        ]
        assert [(e["message_id"], e["attachment_id"]) for e in result["body_decode_errors"]] == [
            ("m2", "att-b")
        ]

    async def test_manifest_has_no_error_keys_on_success(self, small_cap, tmp_path):
        ctx = _make_ctx(gmail_service=self._large())

        result = await _gmail_tools["get_message"](
            message_id="m1", local_path=str(tmp_path), ctx=ctx
        )

        assert set(result) == {"local_path", "bytes_written", "message_id"}

    async def test_get_thread_over_cap_raises_and_names_local_path(self, small_cap):
        gmail_svc = self._large()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [_message("m1", _deferred_part("text/plain", "att-1"))],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)

        with pytest.raises(ValueError, match=r"get_thread.*Pass local_path"):
            await _gmail_tools["get_thread"](thread_id="t1", ctx=ctx)

    async def test_get_thread_local_path_writes_full_thread(self, small_cap, tmp_path):
        gmail_svc = self._large()
        gmail_svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [_message("m1", _deferred_part("text/plain", "att-1"))],
        }
        ctx = _make_ctx(gmail_service=gmail_svc)
        dest = tmp_path / "out" / "thread.json"

        result = await _gmail_tools["get_thread"](thread_id="t1", local_path=str(dest), ctx=ctx)

        assert result["local_path"] == str(dest)
        assert result["thread_id"] == "t1"
        assert result["message_count"] == 1
        assert json.loads(dest.read_text())["messages"][0]["body_plain"] == "x" * 500


class TestSizeFloorCodecs:
    """PR #829 QA round 2: _deferred_body_bytes may count a part's byte size only
    when its codec guarantees at least one serialized JSON character per byte."""

    @staticmethod
    def _counted_codecs() -> list[str]:
        names = set()
        for alias in set(encodings.aliases.aliases.values()):
            try:
                names.add(codecs.lookup(alias).name)
            except LookupError:
                continue
        return sorted(n for n in names if gmail_module._bytes_bound_serialized_size(n))

    def test_every_counted_codec_serializes_at_least_one_char_per_byte(self):
        rng = random.Random(825)
        blobs = [bytes(rng.randrange(256) for _ in range(2000)) for _ in range(5)]
        blobs.append(bytes(range(256)) * 4)
        texts = [
            "Hello, world\n",
            "Caf\u00e9 \u201cq\u201d \u20ac",
            "\u3053\u3093\u306b\u3061\u306f",
            "\u041f\u0440\u0438",
        ]
        counted = self._counted_codecs()
        assert "utf-8" in counted and "cp1252" in counted and "shift_jis" in counted
        for codec in counted:
            samples = list(blobs)
            for text in texts:
                with contextlib.suppress(UnicodeEncodeError):
                    samples.append(text.encode(codec) * 20)
            for raw in samples:
                decoded = raw.decode(codec, errors="replace")
                assert len(json.dumps(decoded)) - 2 >= len(raw), codec

    @pytest.mark.parametrize(
        "charset",
        ["utf-16", "utf-16-le", "utf-32", "utf-7", "iso-2022-jp", "iso-2022-kr", "hz", "idna"],
    )
    def test_wide_and_stateful_codecs_are_not_counted(self, charset):
        codec = gmail_module._codec_for(charset)
        assert not gmail_module._bytes_bound_serialized_size(codec)


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
