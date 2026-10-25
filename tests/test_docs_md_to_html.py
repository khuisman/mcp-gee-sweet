"""Tests for md_to_html — the CommonMark/GFM Markdown parser behind every Markdown
entry point (#1116), and the html_parser shapes markdown-it's HTML reaches."""

import pytest

from mcp_gee_sweet.tools.docs.ast import BulletItem, Heading, Paragraph, Run, Table
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast
from mcp_gee_sweet.tools.docs.md_to_html import (
    _closes_fence,
    _md_to_html,
    _nest_lists,
    _separate_tables,
)


def _ast(md: str):
    return html_to_ast(_md_to_html(md))


def _text(node) -> str:
    return "".join(r.text for r in node.runs if isinstance(r, Run))


def _outline(md: str) -> list[tuple]:
    """(node type, depth or level, text) for each top-level node."""
    out = []
    for n in _ast(md):
        if isinstance(n, BulletItem):
            out.append(("OL" if n.ordered else "UL", n.depth, _text(n)))
        elif isinstance(n, Heading):
            out.append(("H", n.level, _text(n)))
        elif isinstance(n, Paragraph):
            out.append(("P", n.blockquote_depth, _text(n)))
        elif isinstance(n, Table):
            out.append(("TABLE", len(n.rows), ""))
    return out


class TestIssueTableCases:
    """The departures #1116's body lists, one test per row."""

    @pytest.mark.parametrize(
        "md, expected",
        [
            (
                "Para\n- a\n- b",
                [("P", 0, "Para"), ("UL", 0, "a"), ("UL", 0, "b")],
            ),
            (
                "Para\n1. a\n2. b",
                [("P", 0, "Para"), ("OL", 0, "a"), ("OL", 0, "b")],
            ),
            (
                "> q\n- a",
                [("P", 1, "q"), ("UL", 0, "a")],
            ),
            (
                "| K | V |\n|---|---|\n| k | v |\n- a",
                [("TABLE", 2, ""), ("UL", 0, "a")],
            ),
        ],
    )
    def test_block_directly_under_another_starts_its_own(self, md, expected):
        assert _outline(md) == expected

    def test_paren_ordered_marker(self):
        assert _outline("1) One\n2) Two") == [("OL", 0, "One"), ("OL", 0, "Two")]

    def test_backslash_hard_break(self):
        assert "a<br />\nb" in _md_to_html("a\\\nb")

    def test_seven_hashes_are_a_paragraph(self):
        assert _outline("####### Seven") == [("P", 0, "####### Seven")]

    def test_hashtag_is_a_paragraph(self):
        assert _outline("#hashtag") == [("P", 0, "#hashtag")]

    def test_every_ascii_punctuation_escape_drops_the_backslash(self):
        escaped = "".join("\\" + c for c in "\"%&',/:;<=?@^~$")
        assert _outline(escaped) == [("P", 0, "\"%&',/:;<=?@^~$")]

    def test_bold_inside_italic(self):
        (para,) = _ast("*Italic with **bold inside** and back*")
        assert [(r.text, r.bold, r.italic) for r in para.runs] == [
            ("Italic with ", None, True),
            ("bold inside", True, True),
            (" and back", None, True),
        ]

    def test_www_and_email_autolinks(self):
        (para,) = _ast("Visit www.example.com or write to me@example.com.")
        links = [(r.text, r.link_url) for r in para.runs if r.link_url]
        assert links == [
            ("www.example.com", "http://www.example.com"),
            ("me@example.com", "mailto:me@example.com"),
        ]

    def test_escaped_pipe_in_table_code_span(self):
        (table,) = _ast("| A |\n|---|\n| `a \\| b` |")
        cell = table.rows[1].cells[0]
        assert [r.text for r in cell.children] == ["a | b"]


class TestStrikethrough:
    def test_tildes_strike_through(self):
        (para,) = _ast("This is ~~gone~~ now")
        assert [(r.text, r.strikethrough) for r in para.runs] == [
            ("This is ", None),
            ("gone", True),
            (" now", None),
        ]


class TestGfmAutolinks:
    @pytest.mark.parametrize(
        "text, href",
        [
            ("see https://x.com/a.", "https://x.com/a"),
            ("(https://x.com)", "https://x.com"),
            ("https://x.com/a_(b)_c)", "https://x.com/a_(b)_c"),
            ("www.x.com?q=1&r=2!", "http://www.x.com?q=1&r=2"),
            ("http://localhost:8000/x", "http://localhost:8000/x"),
            ("www.commonmark.org/a.b.", "http://www.commonmark.org/a.b"),
            ("https://x.com/&hl;", "https://x.com/"),
            ("*https://em.example*", "https://em.example"),
            ("foo@bar.baz.com.", "mailto:foo@bar.baz.com"),
        ],
    )
    def test_linked_and_trimmed(self, text, href):
        assert f'href="{href}"' in _md_to_html(text).replace("&amp;", "&")

    @pytest.mark.parametrize(
        "text",
        [
            "README.md",
            "file.py",
            "example.com",
            "ftp://x.org",
            "www.a_b.com",
            "`https://code.example`",
            "x-https://x.com",
            "a@b",
        ],
    )
    def test_not_linked(self, text):
        assert "<a " not in _md_to_html(text)

    def test_url_inside_markdown_link_not_relinked(self):
        assert _md_to_html("[see www.x.com](https://y.com)").count("<a ") == 1

    def test_url_inside_raw_html_link_not_relinked(self):
        html = _md_to_html('<a href="https://y.com">www.x.com</a>')
        assert html.count("<a ") == 1

    def test_autolink_urls_false_leaves_www_and_email(self):
        html = _md_to_html("www.x.com me@x.com https://x.com", autolink_urls=False)
        assert "<a " not in html


class TestDestinationsKeptAsWritten:
    def test_non_ascii_image_path_not_percent_encoded(self):
        (para,) = _ast("![a](./café.png)")
        assert para.runs[0].src == "./café.png"

    def test_link_url_not_percent_encoded(self):
        (para,) = _ast("[l](https://x.com/é?a=1&b=2)")
        assert para.runs[0].link_url == "https://x.com/é?a=1&b=2"

    def test_javascript_link_still_refused(self):
        assert "<a " not in _md_to_html("[j](javascript:alert(1))")


class TestSpacedImagePath:
    def test_path_with_spaces_is_an_image(self):
        (para,) = _ast("![shot](/Users/me/Screen Shot 2026-10-25 at 9.41.03 AM.png)")
        assert para.runs[0].src == "/Users/me/Screen Shot 2026-10-25 at 9.41.03 AM.png"

    def test_linked_spaced_image(self):
        (para,) = _ast("[![h](./a b.png)](https://x.com)")
        assert (para.runs[0].src, para.runs[0].link_url) == ("./a b.png", "https://x.com")

    def test_title_still_parsed_by_commonmark(self):
        assert 'title="t"' in _md_to_html('![c](./x.png "t")')

    def test_link_with_spaces_stays_text(self):
        assert "<a " not in _md_to_html("[l](./a b.png)")

    def test_inside_code_span_untouched(self):
        assert "<img" not in _md_to_html("`![g](a b)`")


class TestSeparateTables:
    """Plan rule D2."""

    @pytest.mark.parametrize(
        "md, first",
        [
            ("Para\n| K | V |\n|---|---|\n| k | v |", ("P", 0, "Para")),
            ("- A\n| K | V |\n|---|---|\n| k | v |", ("UL", 0, "A")),
            ("1. A\n| K | V |\n|---|---|\n| k | v |", ("OL", 0, "A")),
            ("> Q\n| K | V |\n|---|---|\n| k | v |", ("P", 1, "Q")),
        ],
    )
    def test_table_after_block_is_separate(self, md, first):
        assert _outline(md) == [first, ("TABLE", 2, "")]

    def test_table_written_inside_a_quote_stays_inside(self):
        html = _md_to_html("> Q\n> | K | V |\n> |---|---|\n> | k | v |")
        assert html.index("<table>") < html.index("</blockquote>")

    def test_table_then_table_is_one_table(self):
        # GFM: a table ends only at a blank line or another block (AJ-078).
        md = "| K | V |\n|---|---|\n| k | v |\n| K | V |\n|---|---|\n| k | v |"
        assert _outline(md) == [("TABLE", 5, "")]

    def test_fenced_table_untouched(self):
        md = "Para\n```\n| K | V |\n|---|---|\n```"
        assert _separate_tables(md) == md


class TestNestLists:
    """Plan rule D1 (#1071)."""

    @pytest.mark.parametrize("indent", ["  ", "   ", "    ", "\t"])
    @pytest.mark.parametrize("parent, child", [("-", "-"), ("-", "1."), ("1.", "-"), ("1.", "1.")])
    def test_three_levels_and_back(self, indent, parent, child):
        # TC-MD106 LN-01 to LN-16: every indent width x parent/child type.
        def marker(m, n):
            return f"{n}." if m == "1." else "-"

        md = "\n".join(
            [
                f"{marker(parent, 1)} Top one",
                f"{indent}{marker(child, 1)} Child one",
                f"{indent * 2}{marker(parent, 1)} Grandchild one",
                f"{indent * 2}{marker(parent, 2)} Grandchild two",
                f"{indent}{marker(child, 2)} Child two",
                f"{marker(parent, 2)} Top two",
            ]
        )
        p = "OL" if parent == "1." else "UL"
        c = "OL" if child == "1." else "UL"
        assert _outline(md) == [
            (p, 0, "Top one"),
            (c, 1, "Child one"),
            (p, 2, "Grandchild one"),
            (p, 2, "Grandchild two"),
            (c, 1, "Child two"),
            (p, 0, "Top two"),
        ]

    def test_r16_agenda_keeps_its_numbering(self):
        md = "1. Opening\n  - Recap\n  - Rules\n2. Brainstorm\n  - Vote\n3. Wrap-up"
        assert _outline(md) == [
            ("OL", 0, "Opening"),
            ("UL", 1, "Recap"),
            ("UL", 1, "Rules"),
            ("OL", 0, "Brainstorm"),
            ("UL", 1, "Vote"),
            ("OL", 0, "Wrap-up"),
        ]
        assert "<ol start" not in _md_to_html(md)

    def test_one_space_is_a_sibling(self):
        assert _outline("- a\n - b") == [("UL", 0, "a"), ("UL", 0, "b")]

    def test_fenced_code_in_a_shifted_item_moves_with_it(self):
        md = "1. A\n  - a1\n\n    ```\n    code\n    ```\n2. B"
        assert _nest_lists(md) == "1. A\n   - a1\n\n     ```\n     code\n     ```\n2. B"

    def test_top_level_fence_untouched(self):
        md = "1. A\n\n```\n  - not a list\n```"
        assert _nest_lists(md) == md

    def test_list_ends_at_a_heading(self):
        md = "1. A\n# H\n  - b"
        assert _nest_lists(md) == md

    def test_list_ends_after_a_blank_and_unindented_text(self):
        md = "1. A\n\ntext\n  - b"
        assert _nest_lists(md) == md

    def test_thematic_break_is_not_a_marker(self):
        md = "- a\n  * * *"
        assert _nest_lists(md) == md

    def test_nesting_inside_a_quote(self):
        nodes = _ast("> 1. A\n>   - a1\n> 2. B")
        assert [
            (type(n).__name__, getattr(n, "depth", None), _text(n), n.blockquote_depth)
            for n in nodes
        ] == [
            ("BulletItem", 0, "A", 1),
            ("BulletItem", 1, "a1", 1),
            ("BulletItem", 0, "B", 1),
        ]

    def test_nesting_inside_a_nested_quote(self):
        assert _nest_lists("> > 1. A\n> >   - a1") == "> > 1. A\n> >    - a1"

    def test_quote_after_a_list_is_its_own_run(self):
        md = "1. A\n\n> 1. Q\n>   - q1"
        assert _nest_lists(md) == "1. A\n\n> 1. Q\n>    - q1"

    def test_crlf_blank_line_still_ends_the_list(self):
        md = "1. A\r\n\r\ntext\r\n  - b"
        assert _outline(md) == [("OL", 0, "A"), ("P", 0, "text"), ("UL", 0, "b")]

    def test_crlf_nesting(self):
        assert _outline("1. A\r\n  - a1\r\n2. B") == [
            ("OL", 0, "A"),
            ("UL", 1, "a1"),
            ("OL", 0, "B"),
        ]

    def test_four_space_indent_unchanged(self):
        md = "1. A\n    - a1\n        - a2"
        assert _nest_lists(md) == md


class TestClosesFence:
    def test_info_string_does_not_close(self):
        assert not _closes_fence("```python", "```")

    def test_longer_fence_closes(self):
        assert _closes_fence("  ````  ", "```")

    def test_other_character_does_not_close(self):
        assert not _closes_fence("~~~", "```")


class TestHtmlShapesFromMarkdownIt:
    """html_parser changes for shapes Python-Markdown never produced."""

    def test_newline_before_nested_list_is_not_text(self):
        nodes = html_to_ast("<ul>\n<li>a\n<ul>\n<li>b</li>\n</ul>\n</li>\n</ul>\n")
        assert [_text(n) for n in nodes] == ["a", "b"]

    def test_newline_before_nested_code_block_is_not_text(self):
        nodes = html_to_ast("<ul><li>a\n<pre><code>x</code></pre></li></ul>")
        assert _text(nodes[0]) == "a"

    def test_br_before_nested_list_keeps_its_break(self):
        nodes = html_to_ast("<ul><li>a<br />\n<ul><li>b</li></ul></li></ul>")
        assert _text(nodes[0]) == "a\n"

    def test_rule_inside_list_item_after_text(self):
        nodes = html_to_ast("<ul>\n<li>Item\n<hr />\n</li>\n<li>Next</li>\n</ul>")
        assert [(type(n).__name__, _text(n)) for n in nodes] == [
            ("BulletItem", "Item"),
            ("Paragraph", ""),
            ("BulletItem", "Next"),
        ]

    def test_rule_inside_paragraph_after_text(self):
        nodes = html_to_ast("<p>a<hr>b</p>")
        assert [(type(n).__name__, _text(n)) for n in nodes] == [
            ("Paragraph", "a"),
            ("Paragraph", ""),
            ("Paragraph", "b"),
        ]
