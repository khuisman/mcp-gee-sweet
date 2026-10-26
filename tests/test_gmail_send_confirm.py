"""Tests for GMAIL_SEND=confirm (#1081): a send saves a draft and delivers it only
after the user confirms it in a form elicitation."""

import base64
import itertools
from contextlib import asynccontextmanager
from email import message_from_bytes
from email.message import Message
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from mcp import Client
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    ElicitResult,
    FormElicitationCapability,
    UrlElicitationCapability,
)

from mcp_gee_sweet.tools import gmail as gmail_module

PRIMARY = "me@corp.example"


def _payload(part: Message) -> dict:
    """A parsed MIME part in the shape Gmail's format='full' returns it."""
    headers = [{"name": k, "value": str(v)} for k, v in part.items()]
    if part.is_multipart():
        return {
            "mimeType": part.get_content_type(),
            "filename": "",
            "headers": headers,
            "body": {"size": 0},
            "parts": [_payload(p) for p in part.get_payload()],
        }
    data = part.get_payload(decode=True) or b""
    filename = part.get_filename() or ""
    body: dict = {"size": len(data)}
    if filename:
        body["attachmentId"] = f"att-{filename}"
    else:
        body["data"] = base64.urlsafe_b64encode(data).decode()
    return {
        "mimeType": part.get_content_type(),
        "filename": filename,
        "headers": headers,
        "body": body,
    }


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, **_kwargs):
        return self._fn()


class FakeGmail:
    """A stateful stand-in for the Gmail API calls the send tools make. Drafts keep
    their raw message; each create or update gives the draft a new message ID, and a
    full read stamps From the way Gmail does (both checked live, #1081)."""

    _http = SimpleNamespace(credentials=None)

    def __init__(self, *, primary=PRIMARY, aliases=()):
        self.primary = primary
        self.aliases = list(aliases)
        self.drafts_store: dict[str, dict] = {}
        self.delivered: list[dict] = []
        self._ids = itertools.count(1)
        self.original = {
            "id": "orig-1",
            "threadId": "thread-orig",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@corp.example>"},
                    {"name": "To", "value": PRIMARY},
                    {"name": "Subject", "value": "Lunch"},
                    {"name": "Message-ID", "value": "<orig@mail>"},
                ]
            },
        }

    # Resource chain
    def users(self):
        return self

    def settings(self):
        return self

    def sendAs(self):
        return self

    def list(self, userId):
        entries = [{"sendAsEmail": self.primary, "isPrimary": True}]
        entries += [{"sendAsEmail": a} for a in self.aliases]
        return _Exec(lambda: {"sendAs": entries})

    def getProfile(self, userId):
        return _Exec(lambda: {"emailAddress": self.primary})

    def drafts(self):
        return _Drafts(self)

    def messages(self):
        return _Messages(self)

    # Helpers
    def new_id(self, prefix):
        return f"{prefix}-{next(self._ids)}"

    def store_draft(self, message: dict) -> dict:
        draft_id = self.new_id("draft")
        self.drafts_store[draft_id] = {
            "raw": message["raw"],
            "threadId": message.get("threadId") or self.new_id("thread"),
            "message_id": self.new_id("msg"),
        }
        return self.draft_stub(draft_id)

    def draft_stub(self, draft_id):
        d = self.drafts_store[draft_id]
        return {"id": draft_id, "message": {"id": d["message_id"], "threadId": d["threadId"]}}

    def edit_draft(self, draft_id):
        """What update_draft does to a draft: same ID, new message ID."""
        self.drafts_store[draft_id]["message_id"] = self.new_id("msg")

    def parsed(self, raw: str) -> Message:
        return message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


class _Drafts:
    def __init__(self, fake: FakeGmail):
        self.fake = fake

    def create(self, userId, body):
        return _Exec(lambda: self.fake.store_draft(body["message"]))

    def get(self, userId, id, format):
        def run():
            if id not in self.fake.drafts_store:
                raise Exception(f"Requested entity was not found: {id}")
            d = self.fake.drafts_store[id]
            stub = self.fake.draft_stub(id)
            if format == "minimal":
                return stub
            msg = self.fake.parsed(d["raw"])
            if "From" not in msg:
                msg["From"] = self.fake.primary
            stub["message"].update(labelIds=["DRAFT"], payload=_payload(msg))
            return stub

        return _Exec(run)

    def send(self, userId, body):
        def run():
            d = self.fake.drafts_store.pop(body["id"])
            self.fake.delivered.append({"via": "drafts.send", "draft_id": body["id"], **d})
            return {"id": self.fake.new_id("sent"), "threadId": d["threadId"], "labelIds": ["SENT"]}

        return _Exec(run)


class _Messages:
    def __init__(self, fake: FakeGmail):
        self.fake = fake

    def get(self, userId, id, format):
        return _Exec(lambda: self.fake.original)

    def send(self, userId, body):
        def run():
            self.fake.delivered.append({"via": "messages.send", **body})
            return {"id": self.fake.new_id("sent"), "threadId": "t", "labelIds": ["SENT"]}

        return _Exec(run)


def _tools():
    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    gmail_module.register(tool)
    return captured


TOOLS = _tools()

_FORM = ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability()))


def _ctx(fake, *, capabilities=_FORM, can_send=True, answer=None):
    """A tool Context whose client declares `capabilities` and answers the
    confirmation with `answer` (a result, or an exception to raise)."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = SimpleNamespace(
        gmail_service=fake, gmail_own_addresses=None, gmail_primary_address=None
    )
    ctx.request_context.session = SimpleNamespace(
        can_send_request=can_send, client_capabilities=capabilities
    )
    if isinstance(answer, BaseException):
        ctx.elicit = AsyncMock(side_effect=answer)
    else:
        ctx.elicit = AsyncMock(return_value=answer)
    return ctx


def _yes():
    return AcceptedElicitation(data=gmail_module._SendConfirmation(send=True))


@pytest.fixture(autouse=True)
def _confirm_mode(monkeypatch):
    monkeypatch.setattr(gmail_module, "GMAIL_SEND", "confirm")
    monkeypatch.setattr(gmail_module, "GMAIL_SEND_WARN_RECIPIENTS", 10)


async def _send_message(fake, ctx, **overrides):
    kwargs = {"to": "bob@corp.example", "subject": "Hi", "body": "Hello Bob", "ctx": ctx}
    kwargs.update(overrides)
    return await TOOLS["send_message"](**kwargs)


class TestSendMessageConfirm:
    async def test_accept_sends_the_draft(self):
        fake = FakeGmail()
        ctx = _ctx(fake, answer=_yes())

        result = await _send_message(fake, ctx)

        assert result["sent"] is True
        assert result["id"].startswith("sent-")
        assert [d["via"] for d in fake.delivered] == ["drafts.send"]
        assert result["draft_id"] == fake.delivered[0]["draft_id"]
        ctx.elicit.assert_awaited_once()

    @pytest.mark.parametrize(
        ("answer", "reason"),
        [
            (DeclinedElicitation(), "declined"),
            (CancelledElicitation(), "cancelled"),
            (AcceptedElicitation(data=gmail_module._SendConfirmation(send=False)), "declined"),
            (ValueError("accepted with no content"), "error"),
            (NoBackChannelError("elicitation/create"), "no_elicitation"),
        ],
    )
    async def test_anything_but_an_explicit_yes_holds_the_draft(self, answer, reason):
        fake = FakeGmail()

        result = await _send_message(fake, _ctx(fake, answer=answer))

        assert result["sent"] is False
        assert result["reason"] == reason
        assert fake.delivered == []
        assert result["draft_id"] in fake.drafts_store
        assert "Drafts folder" in result["note"]

    async def test_timeout_holds_the_draft(self, monkeypatch):
        monkeypatch.setattr(gmail_module, "_CONFIRM_TIMEOUT_SECONDS", 0.05)
        fake = FakeGmail()
        ctx = _ctx(fake)

        async def never_answers(*_args, **_kwargs):
            await anyio.sleep(10)

        ctx.elicit = never_answers

        result = await _send_message(fake, ctx)

        assert result["sent"] is False
        assert result["reason"] == "timeout"
        assert fake.delivered == []
        assert result["draft_id"] in fake.drafts_store

    @pytest.mark.parametrize(
        ("capabilities", "can_send"),
        [
            (ClientCapabilities(), True),
            (None, True),
            (
                ClientCapabilities(
                    elicitation=ElicitationCapability(url=UrlElicitationCapability())
                ),
                True,
            ),
            # A 2026-07-28 connection: the capability is declared but the server
            # has no channel to send the request on.
            (_FORM, False),
        ],
    )
    async def test_client_that_cant_elicit_gets_a_held_draft(self, capabilities, can_send):
        fake = FakeGmail()
        ctx = _ctx(fake, capabilities=capabilities, can_send=can_send, answer=_yes())

        result = await _send_message(fake, ctx)

        assert result["sent"] is False
        assert result["reason"] == "no_elicitation"
        assert result["draft_id"] in fake.drafts_store
        assert fake.delivered == []
        ctx.elicit.assert_not_awaited()

    async def test_bare_elicitation_capability_counts_as_form(self):
        fake = FakeGmail()
        ctx = _ctx(
            fake,
            capabilities=ClientCapabilities(elicitation=ElicitationCapability()),
            answer=_yes(),
        )

        result = await _send_message(fake, ctx)

        assert result["sent"] is True

    async def test_draft_edited_during_confirmation_is_not_sent(self):
        fake = FakeGmail()
        ctx = _ctx(fake)

        async def answer_after_edit(*_args, **_kwargs):
            # e.g. a parallel update_draft call while the user reads the form.
            [draft_id] = fake.drafts_store
            fake.edit_draft(draft_id)
            return _yes()

        ctx.elicit = answer_after_edit

        result = await _send_message(fake, ctx)

        assert result["sent"] is False
        assert result["reason"] == "changed"
        assert fake.delivered == []

    async def test_confirmation_shows_flags_first_then_every_recipient(self):
        fake = FakeGmail()
        ctx = _ctx(fake, answer=DeclinedElicitation())

        await _send_message(
            fake,
            ctx,
            to=["Bob <bob@corp.example>", "out@other.example"],
            cc="carol@corp.example",
            bcc="dave@corp.example",
            subject="Plan",
            body="x" * 600,
            attachments=[
                {"content_base64": base64.b64encode(b"data").decode(), "filename": "plan.pdf"}
            ],
        )

        text = ctx.elicit.await_args.args[0]
        lines = text.splitlines()
        assert lines[0] == "Send this email?"
        assert lines[1].startswith("⚠ 1 recipient(s) outside your organization: out@other.example")
        assert lines[2].startswith("⚠ 1 hidden (Bcc) recipient(s): dave@corp.example")
        assert f"From: {PRIMARY}" in lines
        assert "To: Bob <bob@corp.example>, out@other.example" in lines
        assert "Cc: carol@corp.example" in lines
        assert "Bcc: dave@corp.example" in lines
        assert "Subject: Plan" in lines
        assert "Attachments: plan.pdf" in lines
        assert lines[-1] == "x" * gmail_module._PREVIEW_BODY_CHARS + "…"

    async def test_api_failure_after_draft_reports_the_draft(self):
        fake = FakeGmail()
        ctx = _ctx(fake, answer=_yes())
        fake.drafts = lambda: _FailingSendDrafts(fake)

        result = await _send_message(fake, ctx)

        assert "error" in result
        assert result["draft_id"] in fake.drafts_store
        assert "Drafts folder" in result["error"]


class _FailingSendDrafts(_Drafts):
    def send(self, userId, body):
        def run():
            raise Exception("backend error")

        return _Exec(run)


class TestReplyConfirm:
    async def test_held_reply_draft_sits_in_the_original_thread(self):
        fake = FakeGmail()

        result = await TOOLS["reply_to_message"](
            message_id="orig-1", body="Sure", ctx=_ctx(fake, can_send=False)
        )

        assert result["sent"] is False
        draft = fake.drafts_store[result["draft_id"]]
        assert draft["threadId"] == "thread-orig"
        parsed = fake.parsed(draft["raw"])
        assert parsed["To"] == "Alice <alice@corp.example>"
        assert parsed["In-Reply-To"] == "<orig@mail>"
        assert parsed["Subject"] == "Re: Lunch"
        assert fake.delivered == []

    async def test_accepted_reply_is_sent_from_the_draft(self):
        fake = FakeGmail()

        result = await TOOLS["reply_to_message"](
            message_id="orig-1", body="Sure", ctx=_ctx(fake, answer=_yes())
        )

        assert result["sent"] is True
        assert [d["via"] for d in fake.delivered] == ["drafts.send"]
        assert fake.delivered[0]["threadId"] == "thread-orig"


class TestSendDraftConfirm:
    async def _draft(self, fake):
        created = await TOOLS["create_draft"](
            to="bob@corp.example", subject="Hi", body="Hello", ctx=_ctx(fake)
        )
        return created["id"]

    async def test_create_then_send_without_confirmation_delivers_nothing(self):
        fake = FakeGmail()
        draft_id = await self._draft(fake)

        result = await TOOLS["send_draft"](draft_id=draft_id, ctx=_ctx(fake, can_send=False))

        assert result["sent"] is False
        assert result["reason"] == "no_elicitation"
        assert "still in Gmail's Drafts folder" in result["note"]
        assert fake.delivered == []
        assert draft_id in fake.drafts_store

    async def test_confirmed_draft_is_sent(self):
        fake = FakeGmail()
        draft_id = await self._draft(fake)

        result = await TOOLS["send_draft"](draft_id=draft_id, ctx=_ctx(fake, answer=_yes()))

        assert result["sent"] is True
        assert fake.delivered[0]["draft_id"] == draft_id

    async def test_declined_draft_is_not_sent(self):
        fake = FakeGmail()
        draft_id = await self._draft(fake)

        result = await TOOLS["send_draft"](
            draft_id=draft_id, ctx=_ctx(fake, answer=DeclinedElicitation())
        )

        assert result["sent"] is False
        assert fake.delivered == []

    async def test_draft_changed_after_confirmation_is_refused(self):
        fake = FakeGmail()
        draft_id = await self._draft(fake)
        ctx = _ctx(fake)

        async def answer_after_edit(*_args, **_kwargs):
            fake.edit_draft(draft_id)
            return _yes()

        ctx.elicit = answer_after_edit

        result = await TOOLS["send_draft"](draft_id=draft_id, ctx=ctx)

        assert result["sent"] is False
        assert result["reason"] == "changed"
        assert fake.delivered == []

    async def test_unknown_draft_is_an_error_without_drafts_folder_claim(self):
        fake = FakeGmail()

        result = await TOOLS["send_draft"](draft_id="nope", ctx=_ctx(fake, answer=_yes()))

        assert "not found" in result["error"]
        assert "Drafts folder" not in result["error"]
        assert fake.delivered == []


class TestDirectMode:
    @pytest.fixture(autouse=True)
    def _direct(self, monkeypatch):
        monkeypatch.setattr(gmail_module, "GMAIL_SEND", "direct")

    async def test_send_message_delivers_at_once(self):
        fake = FakeGmail()
        ctx = _ctx(fake, answer=_yes())

        result = await _send_message(fake, ctx)

        assert result["sent"] is True
        assert [d["via"] for d in fake.delivered] == ["messages.send"]
        assert fake.drafts_store == {}
        ctx.elicit.assert_not_awaited()

    async def test_reply_delivers_at_once(self):
        fake = FakeGmail()

        result = await TOOLS["reply_to_message"](
            message_id="orig-1", body="Sure", ctx=_ctx(fake, can_send=False)
        )

        assert result["sent"] is True
        assert [d["via"] for d in fake.delivered] == ["messages.send"]

    async def test_send_draft_delivers_at_once(self):
        fake = FakeGmail()
        draft_id = (
            await TOOLS["create_draft"](to="b@corp.example", subject="s", body="b", ctx=_ctx(fake))
        )["id"]

        result = await TOOLS["send_draft"](draft_id=draft_id, ctx=_ctx(fake, can_send=False))

        assert result["sent"] is True
        assert fake.delivered[0]["via"] == "drafts.send"


class TestRecipientFlags:
    def _flags(
        self, *, to=None, cc=None, bcc=None, primary: str | None = PRIMARY, own=None, threshold=10
    ):
        return gmail_module._recipient_flags(
            to=to,
            cc=cc,
            bcc=bcc,
            primary=primary,
            own=set(own if own is not None else {primary} if primary else set()),
            threshold=threshold,
        )

    def _names(self, flags):
        return [f["flag"] for f in flags]

    def test_workspace_flags_outside_domain_and_subdomain(self):
        flags = self._flags(to="a@corp.example, b@sub.corp.example, c@other.example")

        [outside] = flags
        assert outside["flag"] == "outside_organization"
        assert outside["addresses"] == ["b@sub.corp.example", "c@other.example"]

    def test_alias_domains_count_as_inside(self):
        flags = self._flags(to="a@brand.example", own={PRIMARY, "me@brand.example"})

        assert flags == []

    @pytest.mark.parametrize("primary", ["me@gmail.com", "me@googlemail.com"])
    def test_consumer_account_never_flags_outside(self, primary):
        flags = self._flags(to="a@corp.example, b@other.example", primary=primary)

        assert "outside_organization" not in self._names(flags)

    def test_unknown_primary_says_the_check_did_not_run(self):
        flags = self._flags(to="a@other.example", primary=None)

        assert self._names(flags) == ["outside_organization_unchecked"]

    def test_eleven_unique_recipients_trip_many_counting_bcc(self):
        to = ", ".join(f"u{i}@corp.example" for i in range(9))
        flags = self._flags(to=to + ", U0@corp.example", cc="c@corp.example", bcc="b@corp.example")

        assert "many_recipients" in self._names(flags)
        many = next(f for f in flags if f["flag"] == "many_recipients")
        assert many["count"] == 11

    def test_ten_unique_recipients_do_not_trip_many(self):
        to = ", ".join(f"u{i}@corp.example" for i in range(9))
        flags = self._flags(to=to, bcc="b@corp.example")

        assert "many_recipients" not in self._names(flags)

    def test_threshold_is_configurable(self):
        flags = self._flags(to="a@corp.example, b@corp.example, c@corp.example", threshold=2)

        assert "many_recipients" in self._names(flags)

    def test_any_bcc_trips_hidden(self):
        flags = self._flags(to="a@corp.example", bcc="h1@corp.example, h2@corp.example")

        [hidden] = flags
        assert hidden["flag"] == "hidden_recipients"
        assert hidden["count"] == 2

    async def test_held_result_carries_flags(self):
        fake = FakeGmail()

        result = await _send_message(
            fake, _ctx(fake, can_send=False), to="x@other.example", bcc="h@corp.example"
        )

        assert self._names(result["recipient_flags"]) == [
            "outside_organization",
            "hidden_recipients",
        ]


class TestSettings:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, "confirm"),
            ("confirm", "confirm"),
            ("DIRECT", "direct"),
            ("bogus", "confirm"),
            ("", "confirm"),
        ],
    )
    def test_gmail_send(self, monkeypatch, raw, expected):
        if raw is None:
            monkeypatch.delenv("GMAIL_SEND", raising=False)
        else:
            monkeypatch.setenv("GMAIL_SEND", raw)

        assert gmail_module._gmail_send_mode() == expected

    @pytest.mark.parametrize(
        ("raw", "expected"), [(None, 10), ("3", 3), ("0", 0), ("-1", 10), ("many", 10)]
    )
    def test_warn_recipients(self, monkeypatch, raw, expected):
        if raw is None:
            monkeypatch.delenv("GMAIL_SEND_WARN_RECIPIENTS", raising=False)
        else:
            monkeypatch.setenv("GMAIL_SEND_WARN_RECIPIENTS", raw)

        assert gmail_module._warn_recipients_threshold() == expected

    async def test_threshold_setting_reaches_the_flags(self, monkeypatch):
        monkeypatch.setattr(gmail_module, "GMAIL_SEND_WARN_RECIPIENTS", 1)
        fake = FakeGmail()

        result = await _send_message(
            fake, _ctx(fake, can_send=False), to="a@corp.example, b@corp.example"
        )

        assert [f["flag"] for f in result["recipient_flags"]] == ["many_recipients"]


def _server(fake: FakeGmail) -> MCPServer:
    """An in-process MCPServer with the Gmail tools over `fake`, for driving them
    through a real mcp.Client in either protocol era."""

    @asynccontextmanager
    async def lifespan(_server):
        yield SimpleNamespace(
            gmail_service=fake, gmail_own_addresses=None, gmail_primary_address=None
        )

    server = MCPServer("gmail-confirm-test", lifespan=lifespan)

    def tool(annotations=None, local_only=False):
        def decorator(func):
            server.tool(annotations=annotations)(func)
            return func

        return decorator

    gmail_module.register(tool)
    return server


async def _accept(context, params):
    return ElicitResult(action="accept", content={"send": True})


class TestThroughMcpClient:
    async def test_legacy_handshake_confirms_and_sends(self):
        fake = FakeGmail()
        async with Client(_server(fake), mode="legacy", elicitation_callback=_accept) as client:
            result = await client.call_tool(
                "send_message", {"to": "bob@corp.example", "subject": "Hi", "body": "Hello"}
            )

        assert result.structured_content["sent"] is True
        assert [d["via"] for d in fake.delivered] == ["drafts.send"]

    async def test_2026_07_28_holds_messages_and_refuses_send_draft(self):
        fake = FakeGmail()
        async with Client(_server(fake), mode="2026-07-28", elicitation_callback=_accept) as client:
            sent = await client.call_tool(
                "send_message", {"to": "bob@corp.example", "subject": "Hi", "body": "Hello"}
            )
            reply = await client.call_tool(
                "reply_to_message", {"message_id": "orig-1", "body": "Sure"}
            )
            created = await client.call_tool(
                "create_draft", {"to": "bob@corp.example", "subject": "Hi", "body": "Hello"}
            )
            refused = await client.call_tool(
                "send_draft", {"draft_id": created.structured_content["id"]}
            )

        for result in (sent, reply, refused):
            assert not result.is_error
            assert result.structured_content["sent"] is False
            assert result.structured_content["reason"] == "no_elicitation"
            assert result.structured_content["draft_id"] in fake.drafts_store
        assert fake.delivered == []
