"""An embedded image and its fallback text take their character style from the span
they sit in, and nothing from the character before them (#1334, #1475)."""

import pytest

from mcp_gee_sweet.tools.docs.ast import BulletItem, Image, Paragraph, RGBColor, Run
from mcp_gee_sweet.tools.docs.emitter import (
    _IMAGE_TEXT_STYLE_FIELDS,
    _LINKED_IMAGE_TEXT_STYLE_FIELDS,
    CellImages,
    ImageFallbacks,
    _image_insert_requests,
    ast_to_requests,
    drop_image_style_requests,
    extract_images,
    image_fallback_requests,
    list_item_image_ids,
)
from mcp_gee_sweet.tools.docs.html_parser import _INLINE_CHARACTER_STYLES, html_to_ast
from mcp_gee_sweet.tools.docs.md_to_html import _md_to_html

_PNG = "https://x/a.png"
_YELLOW = {"color": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 0.0}}}


def _images(content: str, content_format: str = "markdown") -> list[Image]:
    html = _md_to_html(content) if content_format == "markdown" else content
    return extract_images(html_to_ast(html))


def _style_after_insert(requests: list[dict]) -> dict:
    """The updateTextStyle that styles the one image `requests` embeds."""
    [at] = [i for i, r in enumerate(requests) if "insertInlineImage" in r]
    return next(r for r in requests[at + 1 :] if "updateTextStyle" in r)["updateTextStyle"]


def _fields(style: dict) -> set[str]:
    return set(style["fields"].split(","))


class TestFieldList:
    def test_pinned(self):
        # Spelled out, not read back from the constant: a dropped or misspelled field
        # would otherwise pass every test that compares against it.
        assert _IMAGE_TEXT_STYLE_FIELDS == (
            "bold,italic,underline,strikethrough,baselineOffset,smallCaps,backgroundColor,"
            "weightedFontFamily,link"
        )

    @pytest.mark.parametrize("kept", ["fontSize", "foregroundColor"])
    def test_size_and_color_stay_the_paragraphs(self, kept):
        # Deliberately not named, so a fallback reads like the text around it (#1099).
        assert kept not in _IMAGE_TEXT_STYLE_FIELDS.split(",")

    def test_linked_pinned(self):
        assert _LINKED_IMAGE_TEXT_STYLE_FIELDS == (
            "bold,italic,strikethrough,baselineOffset,smallCaps,backgroundColor,"
            "weightedFontFamily,link"
        )


class TestLinkedUnderline:
    """Docs underlines text a link sets; clearing underline in the same request took
    that away from linked fallback text (#1504)."""

    def test_linked_fallback_leaves_underline_to_docs(self):
        image = Image(src="https://x/bad.svg", alt="lfb", link_url="https://ci")
        [_insert, style] = image_fallback_requests(image, 3)
        assert "underline" not in _fields(style["updateTextStyle"])
        assert style["updateTextStyle"]["textStyle"] == {"link": {"url": "https://ci"}}

    def test_linked_image_leaves_underline_to_docs(self):
        image = Image(src=_PNG, link_url="https://ci")
        [_insert, style] = _image_insert_requests(image, _PNG, 3)
        assert "underline" not in _fields(style["updateTextStyle"])

    def test_underlined_span_sets_it(self):
        image = Image(src="https://x/bad.svg", alt="u", link_url="https://ci", underline=True)
        [_insert, style] = image_fallback_requests(image, 3)
        assert style["updateTextStyle"]["textStyle"]["underline"] is True
        assert "underline" in _fields(style["updateTextStyle"])

    @pytest.mark.parametrize("link_url", [None, "./relative.md"])
    def test_unlinked_still_clears_it(self, link_url):
        # An unstorable link is no link: an underline from the run before is cleared.
        image = Image(src="https://x/bad.svg", alt="p", link_url=link_url)
        [_insert, style] = image_fallback_requests(image, 3)
        assert "underline" in _fields(style["updateTextStyle"])
        assert style["updateTextStyle"]["textStyle"] == {}


class TestOneInlineStyleMapping:
    """A bare top-level <img> reads its style from _INLINE_CHARACTER_STYLES, the mapping
    the tag sets handle_starttag uses are derived from, so every inline style tag must
    style it, an <img> in a block, and text the same way."""

    @pytest.mark.parametrize("tag", sorted(_INLINE_CHARACTER_STYLES))
    def test_bare_and_in_block_image_and_text_agree(self, tag):
        field_name, value = _INLINE_CHARACTER_STYLES[tag]
        [bare] = _images(f'<{tag}><img src="{_PNG}"></{tag}>', "html")
        nodes = html_to_ast(f'<p><{tag}>t<img src="{_PNG}"></{tag}></p>')
        [paragraph] = nodes
        [run, in_block] = paragraph.runs
        assert getattr(bare, field_name) == value
        assert getattr(in_block, field_name) == value
        assert getattr(run, field_name) == value

    def test_bare_image_doesnt_share_the_mappings_color(self):
        [a] = _images(f'<mark><img src="{_PNG}"></mark>', "html")
        assert a.background_color is not _INLINE_CHARACTER_STYLES["mark"][1]


class TestParserRecordsTheEnclosingStyle:
    @pytest.mark.parametrize(
        ("content", "field", "value"),
        [
            (f"**Build: ![status]({_PNG}) passing**", "bold", True),
            (f"*a ![s]({_PNG}) b*", "italic", True),
            (f"~~a ![s]({_PNG}) b~~", "strikethrough", True),
            (f"<u>a ![s]({_PNG})</u>", "underline", True),
            (f"<mark>a ![s]({_PNG})</mark>", "background_color", RGBColor(1.0, 1.0, 0.0)),
            (f"<sup>a ![s]({_PNG})</sup>", "baseline_offset", "SUPERSCRIPT"),
            (f"<sub>a ![s]({_PNG})</sub>", "baseline_offset", "SUBSCRIPT"),
        ],
    )
    def test_inline_tag(self, content, field, value):
        [image] = _images(content)
        assert getattr(image, field) == value

    def test_code_span(self):
        [image] = _images(f'<p><code>c <img src="{_PNG}"></code></p>', "html")
        assert image.font_family == "Courier New"

    def test_top_level_image_inside_only_an_inline_tag(self):
        # The bare-<img> path, which opens its own paragraph.
        [image] = _images(f'<b><img src="{_PNG}"></b>', "html")
        assert image.bold is True

    def test_top_level_image_innermost_baseline_wins(self):
        [image] = _images(f'<sup><mark><sub><img src="{_PNG}"></sub></mark></sup>', "html")
        assert image.baseline_offset == "SUBSCRIPT"
        assert image.background_color == RGBColor(1.0, 1.0, 0.0)

    def test_top_level_image_after_a_closed_inline_tag(self):
        [image] = _images(f'<i>x</i><img src="{_PNG}">', "html")
        assert image.italic is None

    def test_table_cell(self):
        [image] = _images(f'<table><tr><td><s><img src="{_PNG}"></s></td></tr></table>', "html")
        assert image.strikethrough is True

    def test_styles_before_the_image_dont_reach_it(self):
        [image] = _images(f"<sup>2</sup> **b** <mark>m</mark> `c` ![s]({_PNG})")
        assert (
            image.bold,
            image.italic,
            image.underline,
            image.strikethrough,
            image.background_color,
            image.baseline_offset,
            image.small_caps,
            image.font_family,
        ) == (None,) * 8


class TestEmbeddedImage:
    def _style(self, content: str) -> dict:
        nodes = html_to_ast(_md_to_html(content))
        uris = {id(img): img.src for img in extract_images(nodes)}
        requests, _ = ast_to_requests(nodes, image_uris=uris)
        return _style_after_insert(requests)

    def test_superscript_bold_and_highlight_before_it_are_cleared(self):
        # #1334: the image would take these from the character before it.
        for before in ("<sup>2</sup>", "**b**", "<mark>m</mark>", "~~s~~", "`c`"):
            style = self._style(f"x {before}![s]({_PNG})")
            assert style["textStyle"] == {}, before
            assert {
                "baselineOffset",
                "bold",
                "backgroundColor",
                "strikethrough",
                "weightedFontFamily",
            } <= _fields(style), before

    def test_its_own_span_is_set(self):
        style = self._style(f"**Build: ![status]({_PNG}) passing**")
        assert style["textStyle"] == {"bold": True}
        assert style["range"]["endIndex"] - style["range"]["startIndex"] == 1

    def test_highlight_and_link_together(self):
        style = self._style(f"<mark>[![s]({_PNG})](https://ci)</mark>")
        assert style["textStyle"] == {
            "backgroundColor": _YELLOW,
            "link": {"url": "https://ci"},
        }

    def test_every_set_field_is_named(self):
        image = Image(
            src=_PNG,
            bold=True,
            italic=True,
            underline=True,
            strikethrough=True,
            background_color=RGBColor(1.0, 1.0, 0.0),
            baseline_offset="SUBSCRIPT",
            small_caps=True,
            font_family="Courier New",
            link_url="https://ci",
        )
        [_insert, style] = _image_insert_requests(image, _PNG, 4)
        text_style = style["updateTextStyle"]["textStyle"]
        assert set(text_style) == _fields(style["updateTextStyle"])


class TestFallbackText:
    def test_takes_its_images_span_style(self):
        [image] = _images("**Build: ![status](https://x/bad.svg) passing**")
        [insert, style] = image_fallback_requests(image, 8)
        assert insert["insertText"]["text"] == "status"
        assert style["updateTextStyle"]["range"] == {"startIndex": 8, "endIndex": 14}
        assert style["updateTextStyle"]["textStyle"] == {"bold": True}

    def test_code_font_before_it_is_cleared(self):
        # ``Run `make` ![build](bad.svg)`` read back as `make build` (#1475).
        [image] = _images("Run `make` ![build](https://x/bad.svg)")
        [_insert, style] = image_fallback_requests(image, 10)
        assert "weightedFontFamily" in _fields(style["updateTextStyle"])
        assert "weightedFontFamily" not in style["updateTextStyle"]["textStyle"]

    def test_inside_a_code_span_keeps_the_code_font(self):
        [image] = _images('<p><code>c <img alt="b" src="https://x/bad.svg"></code></p>', "html")
        [_insert, style] = image_fallback_requests(image, 3)
        assert style["updateTextStyle"]["textStyle"] == {
            "weightedFontFamily": {"fontFamily": "Courier New"}
        }

    def test_cell_fallback_keeps_its_span_style(self):
        image = Image(src="https://x/bad.svg", alt="b", bold=True)
        cell = CellImages({}, None, lambda _e: None, lambda *_: None)
        [_insert, style] = cell.insert_requests(image, 7)
        assert style["updateTextStyle"]["textStyle"] == {"bold": True}


class TestListItemMarkerGuard:
    """A style request covering a list paragraph's whole text restyles its marker
    (#1383), so a styled image's goes behind a throwaway character."""

    def _requests(self, item: BulletItem) -> tuple[list[dict], dict[int, list[dict]]]:
        styles: dict[int, list[dict]] = {}
        uris = {id(img): img.src for img in extract_images([item])}
        requests, _ = ast_to_requests([item], image_uris=uris, image_styles=styles)
        return requests, styles

    def test_styled_image_is_guarded(self):
        image = Image(src=_PNG, bold=True)
        requests, styles = self._requests(BulletItem(runs=[image], depth=0, ordered=False))
        [insert] = [r for r in requests if "insertInlineImage" in r]
        position = insert["insertInlineImage"]["location"]["index"]
        guard_in, style, guard_out = styles[id(insert)]
        assert guard_in == {"insertText": {"location": {"index": position + 1}, "text": "​"}}
        assert style["updateTextStyle"]["range"] == {
            "startIndex": position,
            "endIndex": position + 1,
        }
        assert guard_out == {
            "deleteContentRange": {"range": {"startIndex": position + 1, "endIndex": position + 2}}
        }

    def test_clearing_only_needs_no_guard(self):
        image = Image(src=_PNG)
        requests, styles = self._requests(BulletItem(runs=[image], depth=0, ordered=False))
        [insert] = [r for r in requests if "insertInlineImage" in r]
        [style] = styles[id(insert)]
        assert style["updateTextStyle"]["textStyle"] == {}

    def test_paragraph_image_isnt_guarded(self):
        image = Image(src=_PNG, bold=True)
        uris = {id(image): _PNG}
        styles: dict[int, list[dict]] = {}
        ast_to_requests([Paragraph(runs=[image])], image_uris=uris, image_styles=styles)
        [[style]] = styles.values()
        assert style["updateTextStyle"]["textStyle"] == {"bold": True}

    def test_fallback_in_a_list_item_is_guarded(self):
        image = Image(src="https://x/bad.svg", alt="badge", link_url="https://ci")
        item = BulletItem(runs=[Run("a "), image], depth=0, ordered=False)
        fallbacks = ImageFallbacks(list_item_image_ids([item]))
        insert, guard_in, style, guard_out = fallbacks.requests(image, 3)
        assert insert["insertText"]["text"] == "badge"
        assert guard_in["insertText"] == {"location": {"index": 8}, "text": "​"}
        assert style["updateTextStyle"]["textStyle"] == {"link": {"url": "https://ci"}}
        assert guard_out["deleteContentRange"]["range"] == {"startIndex": 8, "endIndex": 9}

    def test_list_item_image_ids(self):
        inside, outside = Image(src="a"), Image(src="b")
        nodes = [
            BulletItem(runs=[Run("x"), inside], depth=0, ordered=False),
            Paragraph(runs=[outside]),
        ]
        assert list_item_image_ids(nodes) == {id(inside)}


class TestDropImageStyleRequests:
    def test_removes_the_requests_right_after_the_insert(self):
        insert, a, b = {"insertInlineImage": {}}, {"insertText": {}}, {"updateTextStyle": {}}
        other = {"updateTextStyle": {}}
        requests = [other, insert, a, b, other]
        drop_image_style_requests(requests, 1, [a, b])
        assert requests == [other, insert, other]
        assert requests[2] is other

    def test_falls_back_to_identity_when_not_adjacent(self):
        insert, style, between = {"insertInlineImage": {}}, {"updateTextStyle": {}}, {"x": 1}
        requests = [insert, between, style]
        assert drop_image_style_requests(requests, 0, [style]) == 0
        assert requests == [insert, between]

    def test_adjacent_returns_the_same_index(self):
        insert, style = {"insertInlineImage": {}}, {"updateTextStyle": {}}
        requests = [{"x": 1}, insert, style]
        assert drop_image_style_requests(requests, 1, [style]) == 1

    def test_backstop_returns_where_the_insert_moved(self):
        # A style request ahead of its insert shifts it left; the caller then replaces
        # the insert itself, not the request after it.
        insert, style, after = {"insertInlineImage": {}}, {"updateTextStyle": {}}, {"x": 1}
        requests = [style, insert, after]
        index = drop_image_style_requests(requests, 1, [style])
        assert requests[index] is insert
        assert requests == [insert, after]

    def test_an_equal_looking_request_isnt_dropped(self):
        insert, style = {"insertInlineImage": {}}, {"updateTextStyle": {}}
        lookalike = {"updateTextStyle": {}}
        requests = [insert, lookalike, style]
        drop_image_style_requests(requests, 0, [style])
        assert len(requests) == 2 and requests[1] is lookalike
