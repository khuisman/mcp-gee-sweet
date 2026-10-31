"""Tests for tools/front_matter.py: plan rule D3, leading YAML front matter (#1173)."""

import time

import pytest

from mcp_gee_sweet.tools import front_matter
from mcp_gee_sweet.tools.front_matter import strip_front_matter

FIXTURE = "---\ntitle: Front matter\nauthor: QA\n---\n\n# Body heading\n\nBody text.\n"


class TestStripped:
    def test_ds14_fixture(self):
        assert strip_front_matter(FIXTURE) == "# Body heading\n\nBody text.\n"

    @pytest.mark.parametrize("newline", ["\r\n", "\r"])
    def test_other_line_endings_are_kept(self, newline):
        text = FIXTURE.replace("\n", newline)
        assert strip_front_matter(text) == f"# Body heading{newline}{newline}Body text.{newline}"

    def test_dots_close_the_block(self):
        assert strip_front_matter("---\ntitle: x\n...\nBody\n") == "Body\n"

    def test_byte_order_mark_goes_with_the_block(self):
        assert strip_front_matter("﻿---\ntitle: x\n---\nBody\n") == "Body\n"

    def test_trailing_whitespace_on_delimiters(self):
        assert strip_front_matter("--- \t\ntitle: x\n---  \nBody\n") == "Body\n"

    def test_nested_values_comments_and_blank_lines(self):
        text = (
            "---\n"
            "# a comment\n"
            "title: x\n"
            "\n"
            "tags:\n"
            "  - one\n"
            "  - two\n"
            "summary: >\n"
            "  folded text: with a colon\n"
            '"quoted key": 1\n'
            "'single': 2\n"
            "url: https://example.com/a:b\n"
            "empty:\n"
            "---\n"
            "Body\n"
        )
        assert strip_front_matter(text) == "Body\n"

    def test_only_front_matter(self):
        assert strip_front_matter("---\ntitle: x\n---") == ""

    def test_blank_lines_after_are_dropped_but_not_indentation(self):
        assert strip_front_matter("---\na: 1\n---\n\n \t\n    code\n") == "    code\n"

    def test_no_break_space_line_after_is_kept(self):
        """A line holding a no-break space is an authored spacer, not blank."""
        text = "---\ntitle: x\n---\n\N{NO-BREAK SPACE}\nBody\n"
        assert strip_front_matter(text) == "\N{NO-BREAK SPACE}\nBody\n"

    def test_column_0_list_under_a_key(self):
        """What yaml.dump and many Jekyll/Hugo templates write (PR #1303 QA round 1)."""
        text = "---\ntitle: Post\ntags:\n- one\n- two\n-\n---\nBody\n"
        assert strip_front_matter(text) == "Body\n"

    def test_column_0_list_under_a_key_with_a_comment(self):
        assert strip_front_matter("---\ntags: # list\n- one\n---\nBody\n") == "Body\n"

    @pytest.mark.parametrize(
        "block",
        [
            "tags: [a,\nb]\n",
            "tags: [a, [b,\nc], d]\nnext: 1\n",
            "map: {a: 1,\nb: 2}\n",
            'desc: "multi\nline"\n',
            'desc: "escaped \\" quote\nstill open"\n',
            "desc: 'it''s\nopen'\n",
            'tags: [a, "b,\n]c"]\n',
            "tags: [a, # comment ]\nb]\n",
        ],
        ids=[
            "flow-sequence",
            "nested-flow",
            "flow-mapping",
            "double-quoted",
            "escaped-quote",
            "single-quoted",
            "quoted-in-flow",
            "comment-in-flow",
        ],
    )
    def test_value_continued_on_column_0_lines(self, block):
        assert strip_front_matter(f"---\n{block}---\nBody\n") == "Body\n"

    def test_quotes_inside_a_plain_value_open_nothing(self):
        text = "---\ntitle: Don't \"stop\"\nlist: [it's, x]\n---\nBody\n"
        assert strip_front_matter(text) == "Body\n"


class TestUnchanged:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "# Heading\n\nBody\n",
            # A rule, then a setext Heading 2: the block isn't a mapping.
            "---\nSome text\n---\n",
            # Two thematic breaks: an empty block isn't front matter.
            "---\n---\nBody\n",
            # Unclosed.
            "---\ntitle: x\n\nBody\n",
            # A rule later in the file, not at the start.
            "Intro\n\n---\ntitle: x\n---\n",
            # Indented opening line.
            " ---\ntitle: x\n---\n",
            # A top-level sequence, not a mapping.
            "---\n- a\n- b\n---\n",
            # A key line followed by a line that isn't one.
            "---\ntitle: x\nplain text\n---\n",
            # "key:value" without a space isn't a key.
            "---\nhttp://example.com\n---\n",
            # Four dashes is a rule, not a delimiter.
            "----\ntitle: x\n----\n",
            # \v and \f don't end a line, so this opening line isn't "---".
            "---\vtitle: x\n---\n",
            # A list item after a key that has a value on its line isn't YAML.
            "---\ntitle: x\n- one\n---\n",
            # A list before any key.
            "---\n- one\ntitle: x\n---\n",
            # A value still open at the closing line: not a valid mapping.
            '---\ndesc: "never closed\n---\nBody\n',
            "---\ntags: [a,\n---\nBody\n",
        ],
    )
    def test_not_front_matter(self, text):
        assert strip_front_matter(text) == text

    def test_text_not_starting_with_a_delimiter_isnt_split(self, monkeypatch):
        """The common case, most Markdown, returns before any line splitting."""

        class _NoSplit:
            def finditer(self, *args):
                raise AssertionError("split into lines")

        monkeypatch.setattr(front_matter, "_LINE_RE", _NoSplit())
        assert strip_front_matter("# Heading\n\nBody\n") == "# Heading\n\nBody\n"

    def test_lines_after_the_block_arent_split(self, monkeypatch):
        """Scanning stops at the closing delimiter (and the blank lines after it)."""
        seen = []
        real = front_matter._LINE_RE

        class _Counting:
            def finditer(self, text, pos=0):
                for m in real.finditer(text, pos):
                    seen.append(m.group())
                    yield m

        monkeypatch.setattr(front_matter, "_LINE_RE", _Counting())
        assert strip_front_matter("---\na: 1\n---\nBody\nmore\nlines\n") == "Body\nmore\nlines\n"
        assert "more\n" not in seen


@pytest.mark.parametrize(
    "text",
    [
        "---\n" + "a" + " " * 200_000 + "\n",
        "---\nk: [" + "[" * 200_000 + "\n",
        '---\nk: "' + "\\ " * 200_000 + "\n",
        "---\nk: [" + " , " * 200_000 + "\n",
    ],
    ids=["spaces", "nested-flow", "escapes", "flow-separators"],
)
def test_linear_on_long_lines(text):
    """A long line inside an unclosed block doesn't backtrack or rescan."""
    start = time.perf_counter()
    assert strip_front_matter(text) == text
    assert time.perf_counter() - start < 1.0
