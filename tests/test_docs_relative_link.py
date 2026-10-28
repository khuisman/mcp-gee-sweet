"""#1120: a Markdown link whose target has no scheme must not reach the Docs API.

Docs normalises such a URL against its own origin, so "[the guide](./guide.md)"
landed as a link to http://./guide.md (and, from inside a Doc, as
http://docs.google.com/guide.md). The emitter now refuses to store a scheme-less
target: the run keeps its text and simply gets no link.
"""

from mcp_gee_sweet.tools.docs.ast import Image, Run
from mcp_gee_sweet.tools.docs.emitter import (
    _image_insert_requests,
    _run_style_requests,
    _storable_link_url,
)


def _link(text_style):
    return text_style.get("link", {}).get("url")


class TestStorableLinkUrl:
    def test_schemed_urls_pass_through(self):
        for url in (
            "https://example.com/guide.md",
            "http://example.com/x",
            "mailto:someone@example.com",
            "ftp://example.com/f",
        ):
            assert _storable_link_url(url) == url

    def test_scheme_case_and_other_schemes_pass_through(self):
        # A scheme is case-insensitive and not a closed list (RFC 3986), so an
        # allow-list of lowercase web schemes would drop links that resolve.
        for url in (
            "HTTPS://Example.com/Guide",
            "Mailto:someone@example.com",
            "tel:+905350000000",
            "ftps://example.com/f",
            "file:///tmp/report.pdf",
            "vscode://file/tmp/report.pdf",
        ):
            assert _storable_link_url(url) == url

    def test_padded_target_loses_the_padding(self):
        # HTML input like <a href=" https://example.com/x "> is a valid link;
        # the spaces are not part of the target and must not reach the API.
        assert _storable_link_url(" https://example.com/x ") == "https://example.com/x"
        assert _storable_link_url("\t#heading\n") == "#heading"

    def test_heading_anchor_passes_through(self):
        # Same-document '#slug' anchors are in-doc links, not relative paths;
        # _resolve_heading_anchors (#409) turns the accepted ones into full URLs.
        assert _storable_link_url("#heading") == "#heading"

    def test_relative_targets_are_not_storable(self):
        # Padding does not turn a relative path into a storable target.
        for url in (
            "./guide.md",
            "guide.md",
            "/guide.md",
            "///guide.md",
            "?q=1",
            " ./guide.md ",
        ):
            assert _storable_link_url(url) is None

    def test_host_targets_without_a_scheme_get_https(self):
        # #1180: a target that names a host is repaired, always to https.
        assert _storable_link_url("//example.com/x") == "https://example.com/x"
        assert _storable_link_url(" //example.com ") == "https://example.com"
        assert _storable_link_url("www.example.com") == "https://www.example.com"
        assert _storable_link_url("WWW.Example.com/a?b=1") == "https://WWW.Example.com/a?b=1"
        # Not a host: "www." alone, or "www" as a path segment.
        assert _storable_link_url("www.") is None
        assert _storable_link_url("www/guide.md") is None

    def test_none_stays_none(self):
        assert _storable_link_url(None) is None


class TestRunStyleRequests:
    """_run_style_requests emits one updateTextStyle carrying a textStyle dict and a
    comma-separated fields mask; a run with nothing to set emits no request at all."""

    def _style_and_fields(self, run):
        requests = _run_style_requests(run, 1, 6)
        assert len(requests) <= 1, requests
        if not requests:
            return {}, ""
        upd = requests[0]["updateTextStyle"]
        return upd["textStyle"], upd["fields"]

    def test_relative_link_emits_no_link_but_keeps_bold(self):
        style, fields = self._style_and_fields(
            Run(text="the guide", link_url="./guide.md", bold=True)
        )
        assert "link" not in style
        assert style["bold"] is True
        assert fields == "bold"

    def test_absolute_link_is_still_stored(self):
        style, fields = self._style_and_fields(
            Run(text="the guide", link_url="https://example.com/guide.md")
        )
        assert style["link"] == {"url": "https://example.com/guide.md"}
        assert fields == "link"

    def test_anchor_link_is_still_stored(self):
        style, _ = self._style_and_fields(Run(text="jump", link_url="#section-one"))
        assert style["link"] == {"url": "#section-one"}

    def test_run_with_only_a_relative_link_emits_nothing(self):
        style, fields = self._style_and_fields(Run(text="the guide", link_url="./guide.md"))
        assert style == {} and fields == ""


class TestImageLinkRequests:
    def _requests(self, link_url):
        image = Image(alt="chart", src="chart.png", link_url=link_url)
        return _image_insert_requests(image, "https://drive.example/blob", position=10)

    def test_relative_image_link_adds_no_style_request(self):
        requests = self._requests("./report.pdf")
        assert len(requests) == 1
        assert "insertInlineImage" in requests[0]

    def test_absolute_image_link_still_links_the_image(self):
        requests = self._requests("https://example.com/report.pdf")
        assert len(requests) == 2
        assert _link(requests[1]["updateTextStyle"]["textStyle"]) == (
            "https://example.com/report.pdf"
        )
