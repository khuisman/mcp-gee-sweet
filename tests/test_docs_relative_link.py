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
from mcp_gee_sweet.tools.docs.md_to_html import _md_to_html


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

    def test_www_host_with_a_port_gets_https_not_a_scheme_pass_through(self):
        # PR #1272 QA round 1: "www.example.com:" reads as a scheme, so the www
        # rule must run first, or Docs stores the link as http://.
        assert _storable_link_url("www.example.com:8443/x") == "https://www.example.com:8443/x"
        assert _storable_link_url("www.example.com:8443") == "https://www.example.com:8443"

    def test_double_slash_without_a_host_is_dropped(self):
        for url in ("//", "//?q=1", "//#x", "// x", "//example.com/a b"):
            assert _storable_link_url(url) is None, url

    def test_double_slash_host_starts_with_a_letter_or_digit(self):
        # PR #1272 QA round 2: "//:80" and "//-" were stored as dead https links.
        for url in ("//:80", "//-", "//.example.com", "//_x"):
            assert _storable_link_url(url) is None, url
        assert _storable_link_url("//localhost:8080/x") == "https://localhost:8080/x"
        assert _storable_link_url("//10.0.0.1/x") == "https://10.0.0.1/x"

    def test_www_needs_a_gfm_domain(self):
        # GFM's extended www autolink: "www." then a domain with at least one more
        # ".", and no whitespace anywhere.
        for url in ("WWW.md", "www.md", "www.foo bar", "www.example.com/a b", "www..com"):
            assert _storable_link_url(url) is None, url
        assert _storable_link_url("www.config.js") == "https://www.config.js"
        assert _storable_link_url("www.a-b_c.example.org?q=1#f") == (
            "https://www.a-b_c.example.org?q=1#f"
        )

    def test_www_domain_check_matches_the_autolinker(self):
        # PR #1272 QA round 2: GFM allows no "_" in a domain's last two segments,
        # and the rewrite uses the autolinker's own check, so the two agree.
        assert _storable_link_url("www.foo_bar.example_x") is None
        assert _storable_link_url("www.example.foo_bar") is None
        assert _md_to_html("see www.example.foo_bar") == "<p>see www.example.foo_bar</p>\n"
        assert _storable_link_url("www.foo_bar.example.com") == "https://www.foo_bar.example.com"
        assert 'href="https://www.foo_bar.example.com"' in _md_to_html("www.foo_bar.example.com")

    def test_www_autolink_and_written_www_link_get_the_same_scheme(self):
        # #1281: a bare www. autolink follows #1180's https rule, so one host
        # doesn't get http:// and https:// in the same doc.
        html = _md_to_html("see www.example.com and [y](www.example.com)")
        assert 'href="https://www.example.com"' in html
        assert _storable_link_url("www.example.com") == "https://www.example.com"
        assert "http://" not in html

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
