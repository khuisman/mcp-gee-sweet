"""Tests for docs content tools and HTML/Markdown pipeline."""

import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Paragraph,
)
from mcp_gee_sweet.tools.docs.content import (
    _md_to_html,
    _to_doc_requests,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast


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


_docs_tool, _docs_tools = _make_tool_registry()
docs_module.register(_docs_tool)


def _quota_http_error():
    resp = MagicMock()
    resp.status = 403
    return HttpError(
        resp=resp,
        content=b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}',
    )


def _other_403_error():
    resp = MagicMock()
    resp.status = 403
    return HttpError(resp=resp, content=b'{"error": {"reason": "forbidden"}}')


class TestCreateDoc:
    """Bug: create_doc used _html_to_text (plain text) instead of _html_to_doc_requests."""

    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "Test",
            "parents": ["folder1"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_h1_produces_heading_style(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_list_item_produces_bullet(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<li>Item</li>", ctx=ctx)
        bullets = [r for r in self._batchupdate_requests(docs_svc) if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_no_content_skips_batchupdate(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content=None, ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    def test_inline_only_html_skips_batchupdate(self):
        """Tags with no block-level elements produce no requests; batchUpdate should not fire."""
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<span>no blocks</span>", ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    def test_quota_exceeded_returns_error_dict(self):
        """create_doc must return {"error": ...} on storageQuotaExceeded, not raise."""
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    def test_non_quota_403_still_raises(self):
        """A 403 that is NOT storageQuotaExceeded must propagate — not be swallowed."""
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        with pytest.raises(HttpError):
            _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)


# ---------------------------------------------------------------------------
# Markdown / code block / task list — html_parser
# ---------------------------------------------------------------------------


class TestInlineCode:
    def test_inline_code_sets_font_family(self):
        nodes = html_to_ast("<p>Use <code>x = 1</code> here</p>")
        assert isinstance(nodes[0], Paragraph)
        code_run = next(r for r in nodes[0].runs if r.font_family)
        assert code_run.font_family == "Courier New"
        assert code_run.text == "x = 1"

    def test_inline_code_plain_text_no_font_family(self):
        nodes = html_to_ast("<p>plain text</p>")
        for run in nodes[0].runs:
            assert run.font_family is None

    def test_inline_code_preserves_surrounding_text(self):
        nodes = html_to_ast("<p>before <code>fn()</code> after</p>")
        texts = [r.text for r in nodes[0].runs]
        assert "before " in texts
        assert "fn()" in texts
        assert " after" in texts


class TestPreBlock:
    def test_pre_code_creates_paragraph(self):
        nodes = html_to_ast("<pre><code>hello</code></pre>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)

    def test_pre_code_sets_font_family_on_runs(self):
        nodes = html_to_ast("<pre><code>def foo(): pass</code></pre>")
        para = nodes[0]
        assert isinstance(para, Paragraph)
        assert all(r.font_family == "Courier New" for r in para.runs)

    def test_pre_multiline_preserved_in_run_text(self):
        nodes = html_to_ast("<pre><code>line1\nline2</code></pre>")
        para = nodes[0]
        full = "".join(r.text for r in para.runs)
        assert "line1" in full
        assert "line2" in full
        assert "\n" in full

    def test_pre_trailing_newline_stripped(self):
        # The markdown library appends a trailing \n inside <pre>; we strip it
        # so the emitter doesn't produce a spurious extra empty paragraph.
        nodes = html_to_ast("<pre><code>code\n</code></pre>")
        para = nodes[0]
        full = "".join(r.text for r in para.runs)
        assert not full.endswith("\n")

    def test_pre_followed_by_paragraph(self):
        nodes = html_to_ast("<pre><code>code</code></pre><p>text</p>")
        assert len(nodes) == 2
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Paragraph)


class TestTaskList:
    def test_checked_item_sets_checked_true(self):
        nodes = html_to_ast("<ul><li>[x] Done</li></ul>")
        bullet = next(n for n in nodes if isinstance(n, BulletItem))
        assert bullet.checked is True

    def test_unchecked_item_sets_checked_false(self):
        nodes = html_to_ast("<ul><li>[ ] Todo</li></ul>")
        bullet = next(n for n in nodes if isinstance(n, BulletItem))
        assert bullet.checked is False

    def test_checked_prefix_stripped_from_runs(self):
        nodes = html_to_ast("<ul><li>[x] Done</li></ul>")
        bullet = nodes[0]
        full_text = "".join(r.text for r in bullet.runs)
        assert "[x]" not in full_text
        assert "Done" in full_text

    def test_unchecked_prefix_stripped_from_runs(self):
        nodes = html_to_ast("<ul><li>[ ] Todo</li></ul>")
        bullet = nodes[0]
        full_text = "".join(r.text for r in bullet.runs)
        assert "[ ]" not in full_text
        assert "Todo" in full_text

    def test_uppercase_X_also_recognised(self):
        nodes = html_to_ast("<ul><li>[X] Done</li></ul>")
        bullet = nodes[0]
        assert bullet.checked is True

    def test_normal_item_checked_is_none(self):
        nodes = html_to_ast("<ul><li>Regular item</li></ul>")
        bullet = nodes[0]
        assert bullet.checked is None

    def test_checked_with_bold_text(self):
        nodes = html_to_ast("<ul><li>[x] <b>Important</b></li></ul>")
        bullet = nodes[0]
        assert bullet.checked is True
        # The bold run should survive
        bold_run = next((r for r in bullet.runs if r.bold), None)
        assert bold_run is not None
        assert bold_run.text == "Important"

    def test_mixed_task_and_normal_items(self):
        nodes = html_to_ast("<ul><li>[x] Done</li><li>[ ] Todo</li><li>Plain</li></ul>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert bullets[0].checked is True
        assert bullets[1].checked is False
        assert bullets[2].checked is None


# ---------------------------------------------------------------------------
# Markdown pipeline — _md_to_html and _to_doc_requests
# ---------------------------------------------------------------------------


class TestMdToHtml:
    def test_heading_converts(self):
        html = _md_to_html("# Title")
        assert "<h1>" in html

    def test_bold_converts(self):
        html = _md_to_html("**bold**")
        assert "<strong>" in html

    def test_italic_converts(self):
        html = _md_to_html("*italic*")
        assert "<em>" in html

    def test_unordered_list(self):
        html = _md_to_html("- item one\n- item two\n")
        assert "<ul>" in html
        assert "<li>" in html

    def test_ordered_list(self):
        html = _md_to_html("1. first\n2. second\n")
        assert "<ol>" in html

    def test_link(self):
        html = _md_to_html("[click](https://example.com)")
        assert 'href="https://example.com"' in html

    def test_pipe_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        html = _md_to_html(md)
        assert "<table>" in html

    def test_fenced_code_block(self):
        md = "```python\nx = 1\n```\n"
        html = _md_to_html(md)
        assert "<pre>" in html
        assert "<code" in html  # may include class="language-python"

    def test_escaped_dollar_renders_literal_dollar(self):
        # Python-Markdown's default ESCAPED_CHARS omits $ (unlike CommonMark), so \$
        # otherwise passes through untouched as a literal backslash+dollar (issue #213).
        html = _md_to_html(r"Cost: \$6,000")
        assert "$6,000" in html
        assert r"\$" not in html

    def test_escaped_dollar_in_table_cell(self):
        md = "| Deductible | \\$6,000 |\n|---|---|\n"
        html = _md_to_html(md)
        assert "$6,000" in html
        assert r"\$" not in html

    def test_unescaped_dollar_untouched(self):
        html = _md_to_html("Price is $5 not six")
        assert "Price is $5 not six" in html

    def test_escaped_dollar_inside_fenced_code_stays_literal(self):
        # The escape must respect code protection like every other ESCAPED_CHARS entry —
        # a shell variable escape inside a code block is not the same $ as in prose.
        md = "```\nvar=\\$5\n```\n"
        html = _md_to_html(md)
        assert r"\$5" in html

    def test_escaped_dollar_inside_inline_code_stays_literal(self):
        html = _md_to_html(r"Use `\$VAR` in shell")
        assert r"\$VAR" in html

    def test_bare_url_autolinked(self):
        # Python-Markdown's core autolink only fires on <https://...> or [text](url),
        # leaving a bare URL as inert text (issue #248).
        html = _md_to_html("From: https://example.com/some-page")
        assert '<a href="https://example.com/some-page">https://example.com/some-page</a>' in html

    def test_bare_url_trailing_period_not_swallowed(self):
        html = _md_to_html("Visit https://example.com/page. Thanks.")
        assert '<a href="https://example.com/page">https://example.com/page</a>. Thanks.' in html

    def test_bare_url_wrapping_parens_not_swallowed(self):
        html = _md_to_html("See (https://example.com/page) for details")
        assert '(<a href="https://example.com/page">https://example.com/page</a>)' in html

    def test_bare_url_with_internal_paren_preserved(self):
        html = _md_to_html("See https://example.com/wiki/Foo_(bar) here")
        assert 'href="https://example.com/wiki/Foo_(bar)"' in html

    def test_bare_url_inside_markdown_link_not_double_linked(self):
        html = _md_to_html("[click](https://example.com)")
        assert html.count("<a ") == 1

    def test_bare_url_inside_inline_code_untouched(self):
        html = _md_to_html("In code: `https://example.com`")
        assert "<code>https://example.com</code>" in html
        assert "<a " not in html

    def test_bare_url_inside_fenced_code_untouched(self):
        md = "```\nhttps://example.com\n```\n"
        html = _md_to_html(md)
        assert "<a " not in html

    def test_multiple_bare_urls_each_linked(self):
        html = _md_to_html("Multi https://a.example.com and https://b.example.com here")
        assert html.count("<a ") == 2

    def test_autolink_urls_false_leaves_bare_url_as_text(self):
        html = _md_to_html("See https://example.com here", autolink_urls=False)
        assert html == "<p>See https://example.com here</p>"

    def test_autolink_urls_false_does_not_affect_markdown_links(self):
        html = _md_to_html("[click](https://example.com)", autolink_urls=False)
        assert 'href="https://example.com"' in html


class TestToDocRequestsMarkdown:
    def test_h1_in_markdown_produces_heading_1(self):
        requests, _ = _to_doc_requests("# Title", "markdown")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in styles

    def test_markdown_matches_html_for_heading(self):
        md_reqs, _ = _to_doc_requests("# Title", "markdown")
        html_reqs, _ = _to_doc_requests("<h1>Title</h1>", "html")
        md_styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in md_reqs
            if "updateParagraphStyle" in r
        ]
        html_styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in html_reqs
            if "updateParagraphStyle" in r
        ]
        assert md_styles == html_styles

    def test_markdown_list_produces_bullet(self):
        requests, _ = _to_doc_requests("- item\n", "markdown")
        assert any("createParagraphBullets" in r for r in requests)

    def test_markdown_ordered_list_produces_numbered_bullet(self):
        requests, _ = _to_doc_requests("1. first\n", "markdown")
        bullet_reqs = [r for r in requests if "createParagraphBullets" in r]
        assert any("NUMBERED" in r["createParagraphBullets"]["bulletPreset"] for r in bullet_reqs)

    def test_markdown_bare_url_emits_link_text_style(self):
        # End-to-end for issue #248: a bare URL in markdown must produce a real
        # updateTextStyle/link request targeting the URL's own range, not just
        # render as a plain <a> tag in the intermediate HTML.
        requests, _ = _to_doc_requests("From: https://example.com/some-page", "markdown")
        link_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(link_reqs) == 1
        assert (
            link_reqs[0]["updateTextStyle"]["textStyle"]["link"]["url"]
            == "https://example.com/some-page"
        )

    def test_markdown_bare_url_autolink_urls_false_emits_no_link_text_style(self):
        requests, _ = _to_doc_requests(
            "From: https://example.com/some-page", "markdown", autolink_urls=False
        )
        link_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]
        ]
        assert link_reqs == []

    def test_markdown_bold_emits_text_style(self):
        requests, _ = _to_doc_requests("**bold**\n", "markdown")
        bold_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        ]
        assert len(bold_reqs) >= 1

    def test_markdown_task_list_checked(self):
        requests, _ = _to_doc_requests("- [x] Done\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert "☑" in insert["insertText"]["text"]

    def test_markdown_task_list_unchecked(self):
        requests, _ = _to_doc_requests("- [ ] Todo\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert "☐" in insert["insertText"]["text"]

    def test_markdown_fenced_code_emits_font_family(self):
        requests, _ = _to_doc_requests("```\nx = 1\n```\n", "markdown")
        font_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "weightedFontFamily" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(font_reqs) >= 1

    def test_html_format_still_works(self):
        requests, _ = _to_doc_requests("<h2>Sub</h2>", "html")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_2" in styles


# ---------------------------------------------------------------------------
# create_doc content_format and create_doc_from_file
# ---------------------------------------------------------------------------


class TestCreateDocMarkdown:
    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "Test",
            "parents": ["folder1"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_markdown_heading_in_create_doc(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](
            title="Doc", content="# Title", content_format="markdown", ctx=ctx
        )
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_html_format_default_unchanged(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types


class TestCreateDocFromFile:
    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "myfile",
            "parents": ["root"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    def test_md_file_creates_doc(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Hello\n\nParagraph text.\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        assert "docId" in result
        assert "error" not in result

    def test_md_file_title_defaults_to_stem(self, tmp_path):
        md_file = tmp_path / "my-notes.md"
        md_file.write_text("# Content\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        create_body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert create_body["name"] == "my-notes"

    def test_md_file_explicit_title_used(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Content\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc_from_file"](local_path=str(md_file), title="My Doc", ctx=ctx)
        create_body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert create_body["name"] == "My Doc"

    def test_md_file_heading_emitted(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Section\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_html_file_accepted(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<h2>Hello</h2>")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](local_path=str(html_file), ctx=ctx)
        assert "docId" in result
        assert "error" not in result

    def test_file_not_found_returns_error(self, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](
            local_path=str(tmp_path / "missing.md"), ctx=ctx
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_unsupported_extension_returns_error(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("plain text")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = _docs_tools["create_doc_from_file"](local_path=str(txt_file), ctx=ctx)
        assert "error" in result
        assert ".txt" in result["error"]


# ---------------------------------------------------------------------------
# insert_inline_image (#145)
# ---------------------------------------------------------------------------


class TestInsertInlineImage:
    def _ctx(self, docs_svc=None, drive_svc=None):
        return _make_ctx(
            docs_service=docs_svc or MagicMock(),
            drive_service=drive_svc or MagicMock(),
            doc_cache=MagicMock(),
        )

    def test_uri_only_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=5, uri="https://example.com/img.png", ctx=ctx
        )
        assert result == {"docId": "doc1", "index": 5}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["location"]["index"] == 5
        assert req["uri"] == "https://example.com/img.png"
        assert "objectSize" not in req

    def test_width_and_height_included(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            width=200.0,
            height=100.0,
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["objectSize"]["width"] == {"magnitude": 200.0, "unit": "PT"}
        assert req["objectSize"]["height"] == {"magnitude": 100.0, "unit": "PT"}

    def test_drive_file_id_fetches_web_content_link(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=3, drive_file_id="file1", ctx=ctx
        )
        assert "error" not in result
        drive_svc.files.return_value.get.assert_called_with(
            fileId="file1", fields="webContentLink", supportsAllDrives=True
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["uri"] == "https://drive.google.com/uc?id=file1"

    def test_missing_both_returns_error(self):
        ctx = self._ctx()
        result = _docs_tools["insert_inline_image"](doc_id="doc1", index=1, ctx=ctx)
        assert "error" in result

    def test_both_provided_returns_error(self):
        ctx = self._ctx()
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            drive_file_id="file1",
            ctx=ctx,
        )
        assert "error" in result

    def test_drive_file_no_web_content_link_returns_error(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {}
        ctx = self._ctx(drive_svc=drive_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, drive_file_id="file1", ctx=ctx
        )
        assert "error" in result

    def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, uri="https://example.com/img.png", ctx=ctx
        )
        assert "error" in result


class TestGetDocContent:
    def _drive_svc(self, content=b"hello world"):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {
            "id": "doc1",
            "name": "Test Doc",
            "modifiedTime": "2026-01-01T00:00:00Z",
            "webViewLink": "https://example.com/doc1",
        }
        svc.files.return_value.export.return_value.execute.return_value = content
        return svc

    def _ctx(self, drive_svc=None, doc_cache=None):
        return _make_ctx(
            drive_service=drive_svc or self._drive_svc(),
            doc_cache=doc_cache or MagicMock(get=MagicMock(return_value=None)),
        )

    def test_returns_content(self):
        ctx = self._ctx()
        result = _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)
        assert result["content"] == "hello world"

    def test_oversized_result_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(drive_svc=self._drive_svc(content=b"x" * 1000))
        with pytest.raises(ValueError, match="safety cap"):
            _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

    def test_cached_oversized_result_also_raises(self, monkeypatch):
        # Regression: the cap check used to run only on the fetch path (before the
        # doc_cache early-return), so a cached oversized doc would bypass it on repeat
        # calls (issue #242).
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        cached_result = {"id": "doc1", "content": "x" * 1000}
        doc_cache = MagicMock(get=MagicMock(return_value=cached_result))
        ctx = self._ctx(doc_cache=doc_cache)
        with pytest.raises(ValueError, match="safety cap"):
            _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

    def test_local_path_bypasses_cap_and_writes_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(drive_svc=self._drive_svc(content=b"x" * 1000))
        dest = tmp_path / "out.json"
        result = _docs_tools["get_doc_content"](file_id="doc1", local_path=str(dest), ctx=ctx)
        assert result["local_path"] == str(dest)
        assert result["id"] == "doc1"
        written = json.loads(dest.read_text())
        assert written["content"] == "x" * 1000


class TestWriteDocContent:
    """Bug (#255): clear+reinsert left a stale textStyle override on the document's
    trailing paragraph mark (which the Docs API won't let deleteContentRange remove),
    letting it leak into newly-inserted content on the next write_doc_content call.

    The clear (updateTextStyle + deleteContentRange) and the new content's insertText
    must be sent as two SEPARATE batchUpdate calls, not combined into one: live testing
    against the real Docs API showed a same-batch insertText resolves its inherited
    formatting from a pre-batch snapshot, so contamination survived even after the
    clear request ran earlier in that same batch. See content.py's write_doc_content
    for the full account.
    """

    def _make_services(self, end_index=50):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webViewLink": "https://example.com"
        }
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "body": {"content": [{"endIndex": end_index}]}
        }
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            doc_cache=MagicMock(),
        )

    def _batchupdate_calls(self, docs_svc):
        return [
            c.kwargs["body"]["requests"]
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]

    def test_clears_trailing_mark_style_before_deleting_in_its_own_batch(self):
        drive_svc, docs_svc = self._make_services(end_index=50)
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["write_doc_content"](doc_id="doc1", content="<p>New content</p>", ctx=ctx)
        calls = self._batchupdate_calls(docs_svc)

        # First batchUpdate call: clear + delete, nothing else.
        clear_requests = calls[0]
        assert len(clear_requests) == 2
        clear_style = clear_requests[0]["updateTextStyle"]
        assert clear_style["range"] == {"startIndex": 49, "endIndex": 50}
        assert clear_style["textStyle"] == {}
        assert clear_style["fields"] == "*"
        assert clear_requests[1]["deleteContentRange"]["range"] == {
            "startIndex": 1,
            "endIndex": 49,
        }

        # Second batchUpdate call: the new content, sent separately.
        content_requests = calls[1]
        assert not any(
            "updateTextStyle" in r and r["updateTextStyle"].get("fields") == "*"
            for r in content_requests
        )
        assert not any("deleteContentRange" in r for r in content_requests)
        assert any("insertText" in r for r in content_requests)

    def test_empty_doc_skips_clear_requests(self):
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        _docs_tools["write_doc_content"](doc_id="doc1", content="<p>New content</p>", ctx=ctx)
        calls = self._batchupdate_calls(docs_svc)
        # Only one batchUpdate call (the content) — no separate clear/delete call.
        assert len(calls) == 1
        assert not any(
            "updateTextStyle" in r and r["updateTextStyle"].get("fields") == "*" for r in calls[0]
        )
        assert not any("deleteContentRange" in r for r in calls[0])
