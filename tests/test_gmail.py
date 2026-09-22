"""Tests for tools/gmail.py (list_messages, send_message, modify_labels, etc.)."""

import base64
from email import message_from_bytes
from unittest.mock import MagicMock

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

        result = await _gmail_tools["reply_to_message"](
            message_id="m1", body="Thanks", ctx=ctx
        )

        send_body = gmail_svc.users.return_value.messages.return_value.send.call_args.kwargs["body"]
        assert send_body["threadId"] == "t1"
        parsed = message_from_bytes(base64.urlsafe_b64decode(send_body["raw"].encode("utf-8")))
        assert parsed["To"] == "alice@example.com"
        assert parsed["Subject"] == "Re: Hello"
        assert parsed["In-Reply-To"] == "<orig@example.com>"
        assert "<earlier@example.com>" in parsed["References"]
        assert "<orig@example.com>" in parsed["References"]
        assert result["id"] == "reply-1"

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
        gmail_svc.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            Exception("invalid")
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
        gmail_svc.users.return_value.messages.return_value.trash.return_value.execute.side_effect = (
            Exception("notFound")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["trash_message"](message_id="missing", ctx=ctx)

        assert "error" in result


class TestDeleteMessage:
    async def test_deletes_and_returns_confirmation(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.delete.return_value.execute.return_value = (
            None
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["delete_message"](message_id="m1", ctx=ctx)

        gmail_svc.users.return_value.messages.return_value.delete.assert_called_once_with(
            userId="me", id="m1"
        )
        assert result == {"message_id": "m1", "action": "deleted"}

    async def test_api_error_returns_error_dict(self):
        gmail_svc = MagicMock()
        gmail_svc.users.return_value.messages.return_value.delete.return_value.execute.side_effect = (
            Exception("notFound")
        )
        ctx = _make_ctx(gmail_service=gmail_svc)

        result = await _gmail_tools["delete_message"](message_id="missing", ctx=ctx)

        assert "error" in result
