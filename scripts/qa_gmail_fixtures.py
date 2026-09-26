#!/usr/bin/env python3
"""
Gmail QA fixture seeder (docs/qa/gmail-test-plan.md §3, issue #821).

Builds the fixture mailbox the TC-GM cases read from, without depending on
whatever happens to be in the real inbox. Two kinds of fixture:

- **Inserted** — planted in the QA mailbox with `users.messages.insert`, for
  shapes `send_message` can't produce (custom Reply-To, Latin-1 charset,
  multipart/related inline image, pre-labeled SPAM/TRASH). Nothing is sent.
- **Sent** — really delivered by Gmail: the *sender* mailbox sends to the QA
  mailbox (and, for the two-party thread, the QA mailbox replies back). Only
  the `send` command does this, and only between those two addresses.

Every fixture carries a `[mcp-qa:<key>]` subject prefix and the user label
`mcp-qa-fixture`. Reruns find existing fixtures by subject and reuse them, so
the script is idempotent. Fixture IDs are written to the `.env` file only,
never to a tracked file.

Usage:
    uv run python scripts/qa_gmail_fixtures.py status
    uv run python scripts/qa_gmail_fixtures.py seed            # inserted fixtures + label + .env
    uv run python scripts/qa_gmail_fixtures.py send --sender-token PATH [--dry-run]
    uv run python scripts/qa_gmail_fixtures.py seed            # again: picks up the sent ones
    uv run python scripts/qa_gmail_fixtures.py inspect         # MIME part tree of every fixture
    uv run python scripts/qa_gmail_fixtures.py reset           # trash all fixtures + [mcp-qa debris

Options:
    --env-file PATH      .env to read TEST_GMAIL_* from and write IDs to
                         (default: <repo root>/.env)
    --qa-token PATH      OAuth token for the QA mailbox (default: TOKEN_PATH)
    --sender-token PATH  OAuth token for the sender mailbox (`send` only)

Both tokens need the `gmail.modify` scope. Tokens are refreshed in memory and
never written back.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LABEL_NAME = "mcp-qa-fixture"
SUBJECT_TAG = "mcp-qa"
FIXTURE_HEADER = "X-MCP-QA-Fixture"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
PAGE_COUNT = 7
LARGE_BODY_CHARS = 3_000_000  # #803 item 2: does Gmail hand a big body back by attachmentId?
BIG_THREAD_MESSAGES = 3
BIG_THREAD_BODY_CHARS = 400_000  # x3 comfortably exceeds the 1,000,000-char default cap
DELIVERY_TIMEOUT_S = 180
PLANTED_FROM = "mcp-qa fixture <fixture@example.invalid>"

# A 1x1 transparent PNG and a minimal one-page PDF: small, valid, deterministic.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
TINY_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 72 72]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def subject_for(key: str, rest: str = "") -> str:
    return f"[{SUBJECT_TAG}:{key}]" + (f" {rest}" if rest else "")


def plus_address(address: str, tag: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local}+{tag}@{domain}"


# ---------------------------------------------------------------------------
# Fixture catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
    key: str
    source: str  # "inserted" | "sent"
    env_key: str | None
    # "message" records the message ID, "thread" the thread ID.
    record: str = "message"
    # Extra system labels to apply after insert ("SPAM", "TRASH").
    final_state: str | None = None
    # A sent thread fixture is complete once its thread has this many messages.
    min_thread_len: int = 1


FIXTURES: list[Fixture] = [
    Fixture("plain", "sent", "TEST_MESSAGE_ID"),
    Fixture("alt-unicode", "sent", "TEST_GMAIL_UNICODE_ID"),
    Fixture("attachments", "sent", "TEST_GMAIL_ATTACH_ID"),
    Fixture("inline", "inserted", "TEST_GMAIL_INLINE_ID"),
    Fixture("thread", "sent", "TEST_THREAD_ID", record="thread", min_thread_len=3),
    Fixture("reply-to", "inserted", "TEST_GMAIL_REPLYTO_ID"),
    Fixture("forwarded", "sent", "TEST_GMAIL_FWD_ID"),
    Fixture("large-body", "sent", "TEST_GMAIL_LARGE_ID"),
    Fixture(
        "over-cap-thread",
        "sent",
        "TEST_GMAIL_BIG_THREAD_ID",
        record="thread",
        min_thread_len=BIG_THREAD_MESSAGES,
    ),
    Fixture("latin1", "inserted", "TEST_GMAIL_LATIN1_ID"),
    *[Fixture(f"page-{n}", "inserted", None) for n in range(1, PAGE_COUNT + 1)],
    Fixture("spam", "inserted", None, final_state="SPAM"),
    Fixture("trash", "inserted", None, final_state="TRASH"),
]
FIXTURES_BY_KEY = {f.key: f for f in FIXTURES}


# --- inserted fixture builders: (qa_address) -> Message ----------------------


def _planted(msg: Message, key: str, qa: str, subject: str) -> Message:
    msg["From"] = PLANTED_FROM
    msg["To"] = qa
    msg["Subject"] = subject
    msg[FIXTURE_HEADER] = key
    msg["Message-ID"] = make_msgid(domain="mcp-qa.example.invalid")
    return msg


def build_inline(qa: str) -> Message:
    """multipart/related: HTML body referencing an inline PNG by Content-ID, the
    image part carrying no filename (plan §5 P3)."""
    root = MIMEMultipart("related")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("Inline image fixture (plain part).", "plain", "utf-8"))
    alt.attach(
        MIMEText(
            '<p>Inline image fixture.</p><img src="cid:mcp-qa-inline-png" alt="dot">',
            "html",
            "utf-8",
        )
    )
    root.attach(alt)
    img = MIMEImage(TINY_PNG, _subtype="png")
    img.add_header("Content-ID", "<mcp-qa-inline-png>")
    img.add_header("Content-Disposition", "inline")  # deliberately no filename
    root.attach(img)
    return _planted(root, "inline", qa, subject_for("inline", "inline image, no filename"))


def build_reply_to(qa: str) -> Message:
    msg = MIMEText("mcp-gee-sweet reply-to fixture (TC-GM23).", "plain", "utf-8")
    _planted(msg, "reply-to", qa, subject_for("reply-to", "Reply-To differs from From"))
    msg.replace_header("From", "No Reply <noreply@example.invalid>")
    msg["Reply-To"] = plus_address(qa, "tc-gm23")
    return msg


def build_latin1(qa: str) -> Message:
    msg = MIMEText("Café, niño, façade - ISO-8859-1 body (#792).", "plain", "iso-8859-1")
    return _planted(msg, "latin1", qa, subject_for("latin1", "iso-8859-1 body"))


def build_page(n: int) -> Callable[[str], Message]:
    def build(qa: str) -> Message:
        msg = MIMEText(f"Pagination fixture {n} of {PAGE_COUNT}.", "plain", "utf-8")
        # One shared subject prefix so GM33 can match all seven with one query.
        return _planted(msg, f"page-{n}", qa, subject_for("page", f"{n}/{PAGE_COUNT}"))

    return build


def build_simple(key: str) -> Callable[[str], Message]:
    def build(qa: str) -> Message:
        msg = MIMEText(f"mcp-gee-sweet {key} fixture.", "plain", "utf-8")
        return _planted(msg, key, qa, subject_for(key))

    return build


INSERT_BUILDERS: dict[str, Callable[[str], Message]] = {
    "inline": build_inline,
    "reply-to": build_reply_to,
    "latin1": build_latin1,
    "spam": build_simple("spam"),
    "trash": build_simple("trash"),
    **{f"page-{n}": build_page(n) for n in range(1, PAGE_COUNT + 1)},
}


def expected_subject(key: str) -> str:
    """The exact subject a fixture is found by. For inserted ones it's whatever the
    builder writes; for sent ones it's what `send` writes."""
    if key in INSERT_BUILDERS:
        return str(INSERT_BUILDERS[key]("qa@example.invalid")["Subject"])
    return SENT_SUBJECTS[key]


# --- sent fixture builders: (to, sender) -> Message ---------------------------

SENT_SUBJECTS = {
    "plain": subject_for("plain", "plain text"),
    "alt-unicode": subject_for("alt-unicode", "Ünïcødé ✓ 🎉 subject"),
    "attachments": subject_for("attachments", "PDF + CSV"),
    "thread": subject_for("thread", "two-party thread"),
    "forwarded": subject_for("forwarded", "forwarded message attached"),
    "large-body": subject_for("large-body", f"~{LARGE_BODY_CHARS // 1_000_000} MB body"),
    "over-cap-thread": subject_for("over-cap-thread", "oversized thread"),
}


def _addressed(msg: Message, to: str, sender: str, subject: str) -> Message:
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    return msg


def build_sent(key: str, to: str, sender: str) -> Message:
    subject = SENT_SUBJECTS[key]
    if key == "plain":
        msg: Message = MIMEText("mcp-gee-sweet plain fixture.", "plain", "utf-8")
    elif key == "alt-unicode":
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText("Grüße aus Zürich — naïve café, 日本語, emoji 🎉🚀.", "plain", "utf-8"))
        msg.attach(
            MIMEText(
                "<p>Grüße aus <b>Zürich</b> — naïve café, 日本語, emoji 🎉🚀.</p>",
                "html",
                "utf-8",
            )
        )
    elif key == "attachments":
        msg = MIMEMultipart("mixed")
        msg.attach(
            MIMEText("mcp-gee-sweet attachments fixture: a PDF and a CSV.", "plain", "utf-8")
        )
        pdf = MIMEApplication(TINY_PDF, _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="mcp-qa.pdf")
        msg.attach(pdf)
        csv = MIMEText("name,qty\nwidget,3\ngadget,5\n", "csv", "utf-8")
        csv.add_header("Content-Disposition", "attachment", filename="mcp-qa.csv")
        msg.attach(csv)
    elif key == "forwarded":
        # What a mail client's "forward as attachment" produces: a real
        # message/rfc822 part (not base64 application data) after the outer body.
        inner = MIMEText("inner body — the forwarded message's own text.", "plain", "utf-8")
        inner["From"] = PLANTED_FROM
        inner["To"] = sender
        inner["Subject"] = "mcp-qa forwarded inner message"
        inner["Message-ID"] = make_msgid(domain="mcp-qa.example.invalid")
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText("outer body — the forwarder's own note.", "plain", "utf-8"))
        part = MIMEMessage(inner)
        part.add_header("Content-Disposition", "attachment", filename="forwarded.eml")
        msg.attach(part)
    elif key == "large-body":
        # Both alternatives large, since #803 asks about text/html as well as text/plain.
        line = "mcp-gee-sweet large-body fixture line. " * 2 + "\n"
        plain = (line * (LARGE_BODY_CHARS // len(line) + 1))[:LARGE_BODY_CHARS]
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText("<pre>" + plain + "</pre>", "html", "utf-8"))
    else:
        raise ValueError(f"no single-message sent builder for {key!r}")
    return _addressed(msg, to, sender, subject)


def big_body(n: int) -> str:
    line = f"mcp-gee-sweet over-cap-thread message {n}. " * 2 + "\n"
    return (line * (BIG_THREAD_BODY_CHARS // len(line) + 1))[:BIG_THREAD_BODY_CHARS]


def reply_message(
    body: str, to: str, sender: str, subject: str, in_reply_to: str, references: str
) -> Message:
    msg = MIMEText(body, "plain", "utf-8")
    _addressed(msg, to, sender, subject if subject.startswith("Re: ") else f"Re: {subject}")
    msg["In-Reply-To"] = in_reply_to
    msg["References"] = references
    return msg


def encode(msg: Message) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ---------------------------------------------------------------------------
# .env handling
# ---------------------------------------------------------------------------


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m:
            values[m.group(1)] = m.group(2).split(" #", 1)[0].strip().strip("'\"")
    return values


def write_env(path: Path, updates: dict[str, str]) -> list[str]:
    """Set each key in place (preserving every other line), appending new keys
    under a Gmail header. Returns the keys whose value actually changed."""
    lines = path.read_text().splitlines() if path.exists() else []
    current = read_env(path)
    changed = [k for k, v in updates.items() if current.get(k) != v]
    if not changed:
        return []
    remaining = dict(updates)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in remaining:
            lines[i] = f"{m.group(1)}={remaining.pop(m.group(1))}"
    if remaining:
        if "# Gmail QA fixtures (scripts/qa_gmail_fixtures.py)" not in lines:
            lines += ["", "# Gmail QA fixtures (scripts/qa_gmail_fixtures.py)"]
        lines += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(lines) + "\n")
    return changed


# ---------------------------------------------------------------------------
# Gmail API
# ---------------------------------------------------------------------------


def gmail_service(token_path: str) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    with open(token_path) as f:
        info = json.load(f)
    creds = Credentials.from_authorized_user_info(info)
    if not creds.has_scopes([GMAIL_SCOPE]):
        sys.exit(f"ERROR: token at {token_path!r} lacks {GMAIL_SCOPE}. Re-authorize it first.")
    if not creds.valid:
        creds.refresh(Request())  # in memory only; the token file is left untouched
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def mailbox_address(svc: Any) -> str:
    return svc.users().getProfile(userId="me").execute()["emailAddress"]


def ensure_label(svc: Any, create: bool) -> str | None:
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == LABEL_NAME:
            return label["id"]
    if not create:
        return None
    body = {"name": LABEL_NAME, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    return svc.users().labels().create(userId="me", body=body).execute()["id"]


def header(msg: dict[str, Any], name: str) -> str | None:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def find_by_subject(svc: Any, subject: str) -> list[dict[str, Any]]:
    """Messages whose Subject is exactly `subject`, oldest first. Gmail search is
    token-based and fuzzy about punctuation, so the query only narrows the
    candidates; the exact match is checked on the header itself."""
    words = re.sub(r"[^\w-]+", " ", subject).split()
    q = "subject:(" + " ".join(f'"{w}"' for w in words) + ")"
    ids: list[str] = []
    req = svc.users().messages().list(userId="me", q=q, includeSpamTrash=True, maxResults=100)
    while req is not None:
        resp = req.execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        req = svc.users().messages().list_next(req, resp)
    found = []
    for mid in ids:
        m = (
            svc.users()
            .messages()
            .get(
                userId="me",
                id=mid,
                format="metadata",
                metadataHeaders=["Subject", "Message-ID", "From"],
            )
            .execute()
        )
        if header(m, "Subject") == subject:
            found.append(m)
    return sorted(found, key=lambda m: int(m.get("internalDate", 0)))


def is_trashed(m: dict[str, Any]) -> bool:
    return "TRASH" in m.get("labelIds", [])


def locate(svc: Any, fx: Fixture) -> dict[str, Any] | None:
    """The live copy of a fixture in the QA mailbox, or None. A fixture whose final
    state is TRASH is expected to be trashed; any other trashed copy doesn't count."""
    for m in find_by_subject(svc, expected_subject(fx.key)):
        if is_trashed(m) == (fx.final_state == "TRASH") and "SENT" not in m.get("labelIds", []):
            return m
    return None


def rescue_from_spam(svc: Any, thread_id: str | None, m: dict[str, Any]) -> int:
    """Move a fixture (or, for a thread fixture, every message in its thread) out
    of SPAM into INBOX. Returns how many messages were moved."""
    if thread_id:
        t = svc.users().threads().get(userId="me", id=thread_id, format="minimal").execute()
        messages = t.get("messages", [])
    else:
        # A freshly inserted message's response carries no labelIds; re-read it.
        messages = [svc.users().messages().get(userId="me", id=m["id"], format="minimal").execute()]
    moved = 0
    for msg in messages:
        if "SPAM" in msg.get("labelIds", []):
            svc.users().messages().modify(
                userId="me",
                id=msg["id"],
                body={"addLabelIds": ["INBOX"], "removeLabelIds": ["SPAM"]},
            ).execute()
            moved += 1
    return moved


def thread_len(svc: Any, thread_id: str) -> int:
    t = svc.users().threads().get(userId="me", id=thread_id, format="minimal").execute()
    return len(t.get("messages", []))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def fixture_states(svc: Any) -> dict[str, tuple[str, dict[str, Any] | None]]:
    """key -> (state, message) where state is present / incomplete / missing."""
    states: dict[str, tuple[str, dict[str, Any] | None]] = {}
    for fx in FIXTURES:
        m = locate(svc, fx)
        if m is None:
            states[fx.key] = ("missing", None)
        elif fx.min_thread_len > 1 and thread_len(svc, m["threadId"]) < fx.min_thread_len:
            states[fx.key] = ("incomplete", m)
        else:
            states[fx.key] = ("present", m)
    return states


def cmd_status(qa: Any, env_path: Path) -> int:
    env = read_env(env_path)
    print(f"QA mailbox label {LABEL_NAME!r}: {ensure_label(qa, create=False) or 'missing'}")
    print(f"{'key':<17} {'source':<9} {'state':<11} env")
    missing = 0
    for key, (state, m) in fixture_states(qa).items():
        fx = FIXTURES_BY_KEY[key]
        env_note = ""
        if fx.env_key:
            want = (m or {}).get("threadId" if fx.record == "thread" else "id")
            have = env.get(fx.env_key)
            env_note = f"{fx.env_key} {'ok' if want and have == want else 'stale/unset'}"
        print(f"{key:<17} {fx.source:<9} {state:<11} {env_note}")
        missing += state != "present"
    return 1 if missing else 0


def cmd_seed(qa: Any, env_path: Path) -> int:
    qa_addr = mailbox_address(qa)
    label_id = ensure_label(qa, create=True)
    assert label_id
    updates = {"TEST_GMAIL_ADDRESS": qa_addr, "TEST_GMAIL_LABEL_ID": label_id}
    not_ready = []
    for fx in FIXTURES:
        m = locate(qa, fx)
        if m is None and fx.source == "inserted":
            raw = encode(INSERT_BUILDERS[fx.key](qa_addr))
            m = (
                qa.users()
                .messages()
                .insert(userId="me", body={"raw": raw, "labelIds": ["INBOX"]})
                .execute()
            )
            print(f"inserted  {fx.key}")
        if m is None:
            not_ready.append(f"{fx.key} (missing; run `send`)")
            continue
        # Label first: a message already in SPAM/TRASH still takes a user label.
        if fx.record == "thread":
            qa.users().threads().modify(
                userId="me", id=m["threadId"], body={"addLabelIds": [label_id]}
            ).execute()
        else:
            qa.users().messages().modify(
                userId="me", id=m["id"], body={"addLabelIds": [label_id]}
            ).execute()
        if fx.final_state is None:
            # Gmail's filter can junk a sent fixture (seen live: plain, attachments,
            # large-body). Read cases exclude spam by default, so move it back.
            unspammed = rescue_from_spam(qa, m["threadId"] if fx.record == "thread" else None, m)
            if unspammed:
                print(f"unspammed {fx.key} ({unspammed} message(s))")
        elif fx.final_state == "SPAM" and "SPAM" not in m.get("labelIds", []):
            qa.users().messages().modify(
                userId="me", id=m["id"], body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}
            ).execute()
        elif fx.final_state == "TRASH" and not is_trashed(m):
            qa.users().messages().trash(userId="me", id=m["id"]).execute()
        if fx.min_thread_len > 1 and thread_len(qa, m["threadId"]) < fx.min_thread_len:
            not_ready.append(f"{fx.key} (thread incomplete; `reset` then `send` again)")
        if fx.env_key:
            updates[fx.env_key] = m["threadId"] if fx.record == "thread" else m["id"]
    changed = write_env(env_path, updates)
    print(f"{env_path}: {', '.join(changed) if changed else 'no changes'}")
    for item in not_ready:
        print(f"NOT READY: {item}")
    return 1 if not_ready else 0


def wait_for(qa: Any, subject: str, message_id: str | None = None) -> dict[str, Any]:
    """Block until a message with this exact subject (and, if given, Message-ID)
    has been delivered to the QA mailbox and isn't our own sent copy."""
    deadline = time.monotonic() + DELIVERY_TIMEOUT_S
    while time.monotonic() < deadline:
        for m in find_by_subject(qa, subject):
            if "SENT" in m.get("labelIds", []) or is_trashed(m):
                continue
            if message_id is None or header(m, "Message-ID") == message_id:
                return m
        time.sleep(5)
    sys.exit(f"ERROR: {subject!r} not delivered to the QA mailbox within {DELIVERY_TIMEOUT_S}s")


def cmd_send(qa: Any, sender: Any, env_path: Path, dry_run: bool) -> int:
    qa_addr = mailbox_address(qa)
    sender_addr = mailbox_address(sender)
    if qa_addr.lower() == sender_addr.lower():
        sys.exit("ERROR: the sender token and the QA token are the same mailbox.")

    def send(svc: Any, msg: Message, thread_id: str | None = None) -> str:
        """Send, then return the Message-ID Gmail actually stamped on it, read back
        from the sending mailbox's own copy of that message."""
        # Hard guard: mail only ever moves between the two QA mailboxes, no Cc/Bcc.
        allowed = {qa_addr.lower(), sender_addr.lower()}
        if str(msg["To"]).lower() not in allowed or msg["Cc"] or msg["Bcc"]:
            sys.exit(f"ERROR: refusing to send to {msg['To']!r}; only the two QA mailboxes.")
        body: dict[str, Any] = {"raw": encode(msg)}
        if thread_id:
            body["threadId"] = thread_id
        sent = svc.users().messages().send(userId="me", body=body).execute()
        meta = (
            svc.users()
            .messages()
            .get(userId="me", id=sent["id"], format="metadata", metadataHeaders=["Message-ID"])
            .execute()
        )
        return header(meta, "Message-ID") or ""

    states = fixture_states(qa)
    todo = [f for f in FIXTURES if f.source == "sent" and states[f.key][0] != "present"]
    blocked = [f.key for f in todo if states[f.key][0] == "incomplete"]
    if blocked:
        sys.exit(f"ERROR: incomplete thread fixture(s) {blocked}; run `reset` first.")
    print(f"sender -> QA mailbox; to send: {[f.key for f in todo] or 'nothing'}")
    if dry_run or not todo:
        return 0

    for fx in todo:
        subj = SENT_SUBJECTS[fx.key]
        if fx.key == "thread":
            opening = MIMEText("Sender opens the thread fixture (message 1).", "plain", "utf-8")
            first_mid = send(sender, _addressed(opening, qa_addr, sender_addr, subj))
            first = wait_for(qa, subj, first_mid)
            # The QA mailbox replies back to the sender, in its own copy of the thread.
            qa_reply = reply_message(
                "QA mailbox reply (thread fixture, message 2).",
                sender_addr,
                qa_addr,
                subj,
                first_mid,
                first_mid,
            )
            qa_reply_mid = send(qa, qa_reply, thread_id=first["threadId"])
            # The sender answers the QA reply; References chains both earlier IDs.
            third = reply_message(
                "Sender reply (thread fixture, message 3).",
                qa_addr,
                sender_addr,
                subj,
                qa_reply_mid,
                f"{first_mid} {qa_reply_mid}",
            )
            wait_for(qa, str(third["Subject"]), send(sender, third))
        elif fx.key == "over-cap-thread":
            refs: list[str] = []
            for n in range(1, BIG_THREAD_MESSAGES + 1):
                if n == 1:
                    msg: Message = _addressed(
                        MIMEText(big_body(n), "plain", "utf-8"), qa_addr, sender_addr, subj
                    )
                else:
                    msg = reply_message(
                        big_body(n), qa_addr, sender_addr, subj, refs[-1], " ".join(refs)
                    )
                mid = send(sender, msg)
                wait_for(qa, str(msg["Subject"]), mid)
                refs.append(mid)
        else:
            mid = send(sender, build_sent(fx.key, qa_addr, sender_addr))
            wait_for(qa, subj, mid)
        print(f"sent      {fx.key}")

    write_env(env_path, {"TEST_GMAIL_SENDER_ADDRESS": sender_addr})
    print("Done. Run `seed` again to label the sent fixtures and record their IDs.")
    return 0


def part_tree(part: dict[str, Any], depth: int = 0) -> list[str]:
    body = part.get("body", {})
    where = "attachmentId" if body.get("attachmentId") else ("data" if body.get("data") else "-")
    line = (
        f"{'  ' * depth}{part.get('mimeType')}  size={body.get('size', 0)}  body={where}"
        f"  filename={part.get('filename') or '-'}"
    )
    out = [line]
    for child in part.get("parts", []):
        out += part_tree(child, depth + 1)
    return out


def cmd_inspect(qa: Any) -> int:
    """Raw Gmail part structure of every present fixture: the ground truth for
    GM27 (inline image), GM28 (rfc822 expansion) and GM29 (#803 attachmentId)."""
    for fx in FIXTURES:
        m = locate(qa, fx)
        if m is None:
            print(f"== {fx.key}: missing")
            continue
        full = qa.users().messages().get(userId="me", id=m["id"], format="full").execute()
        print(f"== {fx.key}  labels={','.join(full.get('labelIds', []))}")
        print("\n".join("   " + line for line in part_tree(full["payload"])))
    return 0


def cmd_reset(qa: Any) -> int:
    """Trash every fixture and every `[mcp-qa` message or draft a test run left
    behind, in the QA mailbox only. Drafts are deleted (the API has no draft trash)."""
    label_id = ensure_label(qa, create=False)
    queries = [f'subject:"{SUBJECT_TAG}"'] + ([f"label:{LABEL_NAME}"] if label_id else [])
    ids: set[str] = set()
    for q in queries:
        req = qa.users().messages().list(userId="me", q=q, includeSpamTrash=True, maxResults=500)
        while req is not None:
            resp = req.execute()
            ids |= {m["id"] for m in resp.get("messages", [])}
            req = qa.users().messages().list_next(req, resp)
    trashed = 0
    for mid in sorted(ids):
        m = (
            qa.users()
            .messages()
            .get(userId="me", id=mid, format="metadata", metadataHeaders=["Subject"])
            .execute()
        )
        subj = header(m, "Subject") or ""
        if is_trashed(m):
            continue
        if label_id in m.get("labelIds", []) or f"[{SUBJECT_TAG}" in subj:
            qa.users().messages().trash(userId="me", id=mid).execute()
            trashed += 1
    drafts = 0
    resp = qa.users().drafts().list(userId="me", q=f'subject:"{SUBJECT_TAG}"').execute()
    for d in resp.get("drafts", []):
        dm = qa.users().drafts().get(userId="me", id=d["id"], format="metadata").execute()
        if f"[{SUBJECT_TAG}" in (header(dm["message"], "Subject") or ""):
            qa.users().drafts().delete(userId="me", id=d["id"]).execute()
            drafts += 1
    print(f"trashed {trashed} message(s), deleted {drafts} draft(s). Run `send` then `seed`.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["status", "seed", "send", "inspect", "reset"])
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--qa-token")
    parser.add_argument("--sender-token")
    parser.add_argument("--dry-run", action="store_true", help="send: list what would be sent")
    args = parser.parse_args()

    qa_token = args.qa_token or os.environ.get("TOKEN_PATH") or str(REPO_ROOT / "token.json")
    qa = gmail_service(qa_token)
    if args.command == "status":
        return cmd_status(qa, args.env_file)
    if args.command == "seed":
        return cmd_seed(qa, args.env_file)
    if args.command == "inspect":
        return cmd_inspect(qa)
    if args.command == "reset":
        return cmd_reset(qa)
    if not args.sender_token:
        parser.error("send needs --sender-token (the sender mailbox's OAuth token)")
    return cmd_send(qa, gmail_service(args.sender_token), args.env_file, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
