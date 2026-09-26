"""Tests for scripts/qa_gmail_fixtures.py (#821).

Covers the pure pieces — MIME builders, the fixture catalog, and .env writing.
The Gmail API calls are exercised live by running the script itself. Loaded via
importlib like the other script tests (test_gen_tool_docs.py).
"""

import base64
import email
import importlib.util
import sys
from email import policy
from email.message import EmailMessage
from pathlib import Path
from typing import cast

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "qa_gmail_fixtures.py"
_spec = importlib.util.spec_from_file_location("qa_gmail_fixtures", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
fx = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fx  # @dataclass resolves annotations through sys.modules
_spec.loader.exec_module(fx)

QA = "qa@example.test"
SENDER = "sender@example.test"


def _roundtrip(msg) -> EmailMessage:
    """Parse a built message back the way Gmail would receive it."""
    raw = base64.urlsafe_b64decode(fx.encode(msg))
    return cast(EmailMessage, email.message_from_bytes(raw, policy=policy.default))


class TestCatalog:
    def test_every_inserted_fixture_has_a_builder(self):
        inserted = {f.key for f in fx.FIXTURES if f.source == "inserted"}
        assert inserted == set(fx.INSERT_BUILDERS)

    def test_every_sent_fixture_has_a_subject(self):
        sent = {f.key for f in fx.FIXTURES if f.source == "sent"}
        assert sent == set(fx.SENT_SUBJECTS)

    def test_subjects_are_unique_except_the_shared_page_prefix(self):
        subjects = [fx.expected_subject(f.key) for f in fx.FIXTURES]
        assert len(subjects) == len(set(subjects))
        assert all(fx.expected_subject(f"page-{n}").startswith("[mcp-qa:page]") for n in (1, 7))

    def test_env_keys_are_unique(self):
        keys = [f.env_key for f in fx.FIXTURES if f.env_key]
        assert len(keys) == len(set(keys))

    def test_every_subject_carries_the_tag(self):
        assert all(fx.expected_subject(f.key).startswith("[mcp-qa:") for f in fx.FIXTURES)


class TestInsertedBuilders:
    def test_planted_headers(self):
        m = _roundtrip(fx.build_latin1(QA))
        assert m["To"] == QA
        assert m["X-MCP-QA-Fixture"] == "latin1"
        assert m["Message-ID"]
        assert m["Subject"] == fx.expected_subject("latin1")

    def test_latin1_is_really_latin1(self):
        m = _roundtrip(fx.build_latin1(QA))
        assert m.get_content_charset() == "iso-8859-1"
        assert "Café" in m.get_content()

    def test_reply_to_points_at_a_plus_address(self):
        m = _roundtrip(fx.build_reply_to(QA))
        assert m["Reply-To"] == "qa+tc-gm23@example.test"
        assert "noreply@example.invalid" in m["From"]

    def test_inline_image_has_content_id_and_no_filename(self):
        m = _roundtrip(fx.build_inline(QA))
        assert m.get_content_type() == "multipart/related"
        img = next(p for p in m.walk() if p.get_content_type() == "image/png")
        assert img["Content-ID"] == "<mcp-qa-inline-png>"
        assert img.get_filename() is None

    def test_page_subjects(self):
        assert fx.expected_subject("page-3") == "[mcp-qa:page] 3/7"


class TestSentBuilders:
    def test_addressing(self):
        m = _roundtrip(fx.build_sent("plain", QA, SENDER))
        assert (m["To"], m["From"]) == (QA, SENDER)
        assert m["Cc"] is None and m["Bcc"] is None

    def test_attachments(self):
        m = _roundtrip(fx.build_sent("attachments", QA, SENDER))
        names = {p.get_filename(): p.get_content_type() for p in m.iter_attachments()}
        assert names == {"mcp-qa.pdf": "application/pdf", "mcp-qa.csv": "text/csv"}

    def test_forwarded_is_a_real_rfc822_part_after_the_outer_body(self):
        m = _roundtrip(fx.build_sent("forwarded", QA, SENDER))
        parts = cast(list[EmailMessage], list(m.iter_parts()))
        assert parts[0].get_content_type() == "text/plain"
        assert "outer body" in parts[0].get_content()
        assert parts[1].get_content_type() == "message/rfc822"
        assert parts[1]["Content-Transfer-Encoding"] in (None, "7bit", "8bit")

    def test_unicode_subject_survives(self):
        m = _roundtrip(fx.build_sent("alt-unicode", QA, SENDER))
        assert m["Subject"] == fx.SENT_SUBJECTS["alt-unicode"]
        assert "🎉" in m["Subject"]

    def test_large_body_size(self):
        m = _roundtrip(fx.build_sent("large-body", QA, SENDER))
        plain = next(p for p in m.walk() if p.get_content_type() == "text/plain")
        assert len(plain.get_content()) >= fx.LARGE_BODY_CHARS

    def test_reply_threads_and_prefixes_once(self):
        r = fx.reply_message("b", QA, SENDER, "Re: [mcp-qa:thread] x", "<a@x>", "<z@x> <a@x>")
        assert r["Subject"] == "Re: [mcp-qa:thread] x"
        assert r["In-Reply-To"] == "<a@x>"
        assert r["References"] == "<z@x> <a@x>"


class TestEnvFile:
    def test_updates_in_place_and_appends_new_keys(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# keep me\nTEST_DOC_ID=abc\nTEST_MESSAGE_ID=old  # comment\n")
        changed = fx.write_env(env, {"TEST_MESSAGE_ID": "new", "TEST_GMAIL_LABEL_ID": "L1"})
        assert set(changed) == {"TEST_MESSAGE_ID", "TEST_GMAIL_LABEL_ID"}
        text = env.read_text()
        assert "# keep me" in text and "TEST_DOC_ID=abc" in text
        assert fx.read_env(env)["TEST_MESSAGE_ID"] == "new"
        assert fx.read_env(env)["TEST_GMAIL_LABEL_ID"] == "L1"

    def test_no_change_leaves_file_untouched(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("TEST_MESSAGE_ID=same\n")
        before = env.stat().st_mtime_ns
        assert fx.write_env(env, {"TEST_MESSAGE_ID": "same"}) == []
        assert env.stat().st_mtime_ns == before

    def test_creates_missing_file(self, tmp_path):
        env = tmp_path / ".env"
        fx.write_env(env, {"TEST_GMAIL_ADDRESS": QA})
        assert fx.read_env(env) == {"TEST_GMAIL_ADDRESS": QA}


class TestPartTree:
    def test_reports_where_the_body_lives(self):
        payload = {
            "mimeType": "multipart/alternative",
            "body": {"size": 0},
            "parts": [
                {"mimeType": "text/plain", "body": {"size": 5, "data": "aGVsbG8="}},
                {"mimeType": "text/html", "body": {"size": 9, "attachmentId": "A1"}},
            ],
        }
        lines = fx.part_tree(payload)
        assert "body=data" in lines[1]
        assert "body=attachmentId" in lines[2]
        assert lines[2].startswith("  ")
