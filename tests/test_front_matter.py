"""Tests for tools/front_matter.py: plan rule D3, leading YAML front matter (#1173)."""

import time

import pytest

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
        assert strip_front_matter("---\na: 1\n---\n\n  \n    code\n") == "    code\n"


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
        ],
    )
    def test_not_front_matter(self, text):
        assert strip_front_matter(text) == text


def test_linear_on_long_lines():
    """A long line inside an unclosed block doesn't backtrack quadratically."""
    text = "---\n" + "a" + " " * 200_000 + "\n"
    start = time.perf_counter()
    assert strip_front_matter(text) == text
    assert time.perf_counter() - start < 1.0
