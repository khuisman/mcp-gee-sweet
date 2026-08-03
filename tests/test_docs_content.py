"""Tests for docs content tools and HTML/Markdown pipeline."""

import json
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.docs import content as content_module
from mcp_gee_sweet.tools.docs.ast import (
    BulletItem,
    Cell,
    Heading,
    Image,
    Paragraph,
    Row,
    Run,
    Table,
)
from mcp_gee_sweet.tools.docs.content import (
    _collect_doc_paragraphs,
    _has_pending_anchor_links,
    _md_to_html,
    _resolve_heading_anchors,
    _resolve_image_source,
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

    async def test_h1_produces_heading_style(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    async def test_list_item_produces_bullet(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](title="Doc", content="<li>Item</li>", ctx=ctx)
        bullets = [r for r in self._batchupdate_requests(docs_svc) if "createParagraphBullets" in r]
        assert len(bullets) == 1

    async def test_no_content_skips_batchupdate(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](title="Doc", content=None, ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    async def test_inline_only_html_skips_batchupdate(self):
        """Tags with no block-level elements produce no requests; batchUpdate should not fire."""
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](title="Doc", content="<span>no blocks</span>", ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    async def test_bare_text_with_no_wrapping_tag_still_writes_content(self):
        """#343: plain text with no wrapping tag must not silently produce an
        empty doc body — batchUpdate should fire just as it would for the
        equivalent "<p>hello world</p>"."""
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](title="Doc", content="hello world", ctx=ctx)
        assert docs_svc.documents.return_value.batchUpdate.called

    async def test_quota_exceeded_returns_error_dict(self):
        """create_doc must return {"error": ...} on storageQuotaExceeded, not raise."""
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "Service accounts" in result["error"]
        assert "server://auth-status" in result["error"]

    async def test_non_quota_403_still_raises(self):
        """A 403 that is NOT storageQuotaExceeded must propagate — not be swallowed."""
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        with pytest.raises(HttpError):
            await _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)


# ---------------------------------------------------------------------------
# Markdown / code block / task list — html_parser
# ---------------------------------------------------------------------------


class TestInlineCode:
    async def test_inline_code_sets_font_family(self):
        nodes = html_to_ast("<p>Use <code>x = 1</code> here</p>")
        assert isinstance(nodes[0], Paragraph)
        code_run = next(r for r in nodes[0].runs if r.font_family)
        assert code_run.font_family == "Courier New"
        assert code_run.text == "x = 1"

    async def test_inline_code_plain_text_no_font_family(self):
        nodes = html_to_ast("<p>plain text</p>")
        for run in nodes[0].runs:
            assert run.font_family is None

    async def test_inline_code_preserves_surrounding_text(self):
        nodes = html_to_ast("<p>before <code>fn()</code> after</p>")
        texts = [r.text for r in nodes[0].runs]
        assert "before " in texts
        assert "fn()" in texts
        assert " after" in texts


class TestPreBlock:
    async def test_pre_code_creates_paragraph(self):
        nodes = html_to_ast("<pre><code>hello</code></pre>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)

    async def test_pre_code_sets_font_family_on_runs(self):
        nodes = html_to_ast("<pre><code>def foo(): pass</code></pre>")
        para = nodes[0]
        assert isinstance(para, Paragraph)
        assert all(r.font_family == "Courier New" for r in para.runs)

    async def test_pre_multiline_preserved_in_run_text(self):
        nodes = html_to_ast("<pre><code>line1\nline2</code></pre>")
        para = nodes[0]
        full = "".join(r.text for r in para.runs)
        assert "line1" in full
        assert "line2" in full
        assert "\n" in full

    async def test_pre_trailing_newline_stripped(self):
        # The markdown library appends a trailing \n inside <pre>; we strip it
        # so the emitter doesn't produce a spurious extra empty paragraph.
        nodes = html_to_ast("<pre><code>code\n</code></pre>")
        para = nodes[0]
        full = "".join(r.text for r in para.runs)
        assert not full.endswith("\n")

    async def test_pre_followed_by_paragraph(self):
        nodes = html_to_ast("<pre><code>code</code></pre><p>text</p>")
        assert len(nodes) == 2
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Paragraph)


class TestTaskList:
    async def test_checked_item_sets_checked_true(self):
        nodes = html_to_ast("<ul><li>[x] Done</li></ul>")
        bullet = next(n for n in nodes if isinstance(n, BulletItem))
        assert bullet.checked is True

    async def test_unchecked_item_sets_checked_false(self):
        nodes = html_to_ast("<ul><li>[ ] Todo</li></ul>")
        bullet = next(n for n in nodes if isinstance(n, BulletItem))
        assert bullet.checked is False

    async def test_checked_prefix_stripped_from_runs(self):
        nodes = html_to_ast("<ul><li>[x] Done</li></ul>")
        bullet = nodes[0]
        full_text = "".join(r.text for r in bullet.runs)
        assert "[x]" not in full_text
        assert "Done" in full_text

    async def test_unchecked_prefix_stripped_from_runs(self):
        nodes = html_to_ast("<ul><li>[ ] Todo</li></ul>")
        bullet = nodes[0]
        full_text = "".join(r.text for r in bullet.runs)
        assert "[ ]" not in full_text
        assert "Todo" in full_text

    async def test_uppercase_X_also_recognised(self):
        nodes = html_to_ast("<ul><li>[X] Done</li></ul>")
        bullet = nodes[0]
        assert bullet.checked is True

    async def test_normal_item_checked_is_none(self):
        nodes = html_to_ast("<ul><li>Regular item</li></ul>")
        bullet = nodes[0]
        assert bullet.checked is None

    async def test_checked_with_bold_text(self):
        nodes = html_to_ast("<ul><li>[x] <b>Important</b></li></ul>")
        bullet = nodes[0]
        assert bullet.checked is True
        # The bold run should survive
        bold_run = next((r for r in bullet.runs if r.bold), None)
        assert bold_run is not None
        assert bold_run.text == "Important"

    async def test_mixed_task_and_normal_items(self):
        nodes = html_to_ast("<ul><li>[x] Done</li><li>[ ] Todo</li><li>Plain</li></ul>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert bullets[0].checked is True
        assert bullets[1].checked is False
        assert bullets[2].checked is None


class TestNestedLists:
    """A nested <ul>/<ol> inside an <li> that also has its own text (#335, #336)."""

    def _bullets(self, html):
        return [n for n in html_to_ast(html) if isinstance(n, BulletItem)]

    def _texts_depths(self, html):
        return [("".join(r.text for r in b.runs), b.depth) for b in self._bullets(html)]

    async def test_parent_text_survives_alongside_nested_list(self):
        html = "<ul><li>Item text<ul><li>sub a</li><li>sub b</li></ul></li></ul>"
        assert self._texts_depths(html) == [
            ("Item text", 0),
            ("sub a", 1),
            ("sub b", 1),
        ]

    async def test_parent_bullet_precedes_its_children_in_document_order(self):
        # The AST is a flat, ordered list — a parent emitted after its children
        # would render in the wrong position regardless of its depth value.
        html = "<ul><li>Item text<ul><li>sub a</li></ul></li></ul>"
        bullets = self._bullets(html)
        assert [b.depth for b in bullets] == [0, 1]

    async def test_three_level_nesting_preserves_every_parent_text(self):
        html = (
            "<ul><li>Parent A has text"
            "<ul><li>Child A1 has text<ul><li>Grandchild A2a</li></ul></li></ul>"
            "</li></ul>"
        )
        assert self._texts_depths(html) == [
            ("Parent A has text", 0),
            ("Child A1 has text", 1),
            ("Grandchild A2a", 2),
        ]

    async def test_ordered_sibling_after_unordered_parent_text(self):
        html = "<ul><li>Parent B has text<ol><li>Child B1</li><li>Child B2</li></ol></li></ul>"
        bullets = self._bullets(html)
        assert [b.ordered for b in bullets] == [False, True, True]

    async def test_parent_with_no_own_text_unaffected(self):
        # Control case: an <li> that is just a wrapper around a nested list,
        # with no text of its own — nothing should be emitted for it, and
        # both children must still come through.
        html = "<ul><li><ul><li>Child A1</li><li>Child A2</li></ul></li></ul>"
        assert self._texts_depths(html) == [("Child A1", 1), ("Child A2", 1)]

    async def test_bold_run_in_parent_text_survives(self):
        html = "<ul><li>Item <b>text</b><ul><li>sub</li></ul></li></ul>"
        bullets = self._bullets(html)
        parent = bullets[0]
        bold_run = next((r for r in parent.runs if r.bold), None)
        assert bold_run is not None
        assert bold_run.text == "text"

    async def test_nested_list_via_markdown_preserves_parent_text(self):
        md = "- Item text:\n    - sub a\n    - sub b"
        html = _md_to_html(md)
        assert self._texts_depths(html) == [
            ("Item text:", 0),
            ("sub a", 1),
            ("sub b", 1),
        ]


class TestLiInterruptedByOtherBlocks:
    """A block tag other than <ul>/<ol> — <pre>, <table>, <p>, <h1-h6> — opening
    inside an open <li> that has its own text (#335 review round). The
    interrupting construct must not drop the <li>'s text, must not lose text
    after it closes but before the real </li>, and must not leak inline
    formatting state (e.g. an unclosed <b>) into everything that follows.
    """

    async def test_pre_inside_li_preserves_parent_text(self):
        nodes = html_to_ast("<ul><li>Note:<pre>code</pre></li></ul>")
        assert isinstance(nodes[0], BulletItem)
        assert "".join(r.text for r in nodes[0].runs) == "Note:"
        assert isinstance(nodes[1], Paragraph)
        assert "".join(r.text for r in nodes[1].runs) == "code"

    async def test_table_inside_li_preserves_parent_text(self):
        nodes = html_to_ast("<ul><li>Before<table><tr><td>cell</td></tr></table></li></ul>")
        assert isinstance(nodes[0], BulletItem)
        assert "".join(r.text for r in nodes[0].runs) == "Before"
        assert isinstance(nodes[1], Table)

    async def test_paragraph_inside_li_preserves_parent_text(self):
        nodes = html_to_ast("<ul><li>Before<p>Middle</p></li></ul>")
        assert isinstance(nodes[0], BulletItem)
        assert "".join(r.text for r in nodes[0].runs) == "Before"
        assert isinstance(nodes[1], Paragraph)
        assert "".join(r.text for r in nodes[1].runs) == "Middle"

    async def test_heading_inside_li_preserves_parent_text(self):
        nodes = html_to_ast("<ul><li>Before<h2>Middle</h2></li></ul>")
        assert isinstance(nodes[0], BulletItem)
        assert "".join(r.text for r in nodes[0].runs) == "Before"
        assert isinstance(nodes[1], Heading)
        assert "".join(r.text for r in nodes[1].runs) == "Middle"

    async def test_trailing_text_after_nested_list_is_not_dropped(self):
        html = "<ul><li>Parent<ul><li>Child</li></ul>trailing text</li></ul>"
        bullets = [n for n in html_to_ast(html) if isinstance(n, BulletItem)]
        texts_depths = [("".join(r.text for r in b.runs), b.depth) for b in bullets]
        assert texts_depths == [
            ("Parent", 0),
            ("Child", 1),
            ("trailing text", 0),
        ]

    async def test_unclosed_bold_does_not_leak_past_nested_list(self):
        html = "<ul><li>Item <b>bold text<ul><li>sub</li></ul></li></ul><p>After the list</p>"
        nodes = html_to_ast(html)
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        sub_run = next(r for r in bullets[1].runs if r.text == "sub")
        assert sub_run.bold is None
        paragraph = next(n for n in nodes if isinstance(n, Paragraph))
        after_run = next(r for r in paragraph.runs if r.text == "After the list")
        assert after_run.bold is None

    async def test_no_interruption_no_reopen_is_a_no_op(self):
        # Sanity check that ordinary (non-<li>) block boundaries are unaffected
        # by the new reopen bookkeeping.
        nodes = html_to_ast("<p>One</p><pre>two</pre><table><tr><td>three</td></tr></table>")
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Paragraph)
        assert isinstance(nodes[2], Table)


class TestBlockInterruptionGeneralizedBeyondLi:
    """Round 2 of #335's review: any open block — not just <li> — must survive
    a nested construct interrupting it, and malformed HTML must degrade
    locally rather than corrupting unrelated, well-formed content later in
    the document.
    """

    async def test_heading_interrupted_by_table_preserves_heading_text(self):
        nodes = html_to_ast("<h2>Heading text<table><tr><td>cell</td></tr></table></h2>")
        assert isinstance(nodes[0], Heading)
        assert "".join(r.text for r in nodes[0].runs) == "Heading text"
        assert isinstance(nodes[1], Table)

    async def test_paragraph_interrupted_by_table_does_not_splice_into_cell(self):
        # Regression guard for the specific corruption QA found: the outer
        # block's text must not end up concatenated into the nested
        # construct's own content (e.g. a table cell).
        nodes = html_to_ast("<p>Before<table><tr><td>cell</td></tr></table></p>")
        assert isinstance(nodes[0], Paragraph)
        assert "".join(r.text for r in nodes[0].runs) == "Before"
        table = nodes[1]
        assert isinstance(table, Table)
        cell_text = "".join(r.text for r in table.rows[0].cells[0].children if hasattr(r, "text"))
        assert cell_text == "cell"

    async def test_unclosed_p_inside_li_does_not_corrupt_later_content(self):
        # Malformed: <p> opened inside <li> is never explicitly closed. The
        # <li>'s own text must still survive, and — critically — a later,
        # well-formed paragraph elsewhere in the document must not be
        # corrupted by the stuck interruption frame this leaves behind.
        html = "<ul><li>text<p>unclosed</li></ul><p>Later unrelated paragraph</p>"
        nodes = html_to_ast(html)
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert len(bullets) == 1
        assert "".join(r.text for r in bullets[0].runs) == "text"
        paragraphs = [n for n in nodes if isinstance(n, Paragraph)]
        texts = ["".join(r.text for r in p.runs) for p in paragraphs]
        assert "Later unrelated paragraph" in texts

    async def test_mismatched_ol_closed_by_ul_does_not_corrupt_later_content(self):
        # Malformed: an <ol> is closed with </ul>. Block-node-type correctness
        # (this test's own concern) is handled by the block-interruption stack
        # independently of _list_ordered — #382 (see TestMismatchedListTags
        # below) covers the separate _list_ordered depth-desync this same
        # malformed input used to also cause.
        html = "<ol><li>Parent<ul><li>Child</li></ol></li></ul><p>Later text</p>"
        nodes = html_to_ast(html)
        paragraphs = [n for n in nodes if isinstance(n, Paragraph)]
        texts = ["".join(r.text for r in p.runs) for p in paragraphs]
        assert "Later text" in texts
        # The stray "Later text" must be a plain Paragraph, not spuriously
        # wrapped as a BulletItem by a leaked/misapplied reopen.
        later_node = next(n for n in nodes if "Later text" in "".join(r.text for r in n.runs))
        assert isinstance(later_node, Paragraph)

    async def test_stale_interruption_frame_not_reused_by_later_unrelated_list(self):
        # #450: a block-interruption frame left behind by a mismatched
        # <ol>/<ul> close must not be resumed later by a coincidental tag
        # match from a completely separate, well-formed list. Regression
        # guard distinct from test_mismatched_ol_closed_by_ul_does_not_
        # corrupt_later_content above: that html has no *later* list at all,
        # so it never exercised the stale-frame-reuse path this fix targets.
        html = "<h1>Start<ol><li>Item</li></ul><ol><li>Later item</li></ol>Trailing bare text"
        nodes = html_to_ast(html)
        assert isinstance(nodes[0], Heading)
        assert "".join(r.text for r in nodes[0].runs) == "Start"
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert [b.runs[0].text for b in bullets] == ["Item", "Later item"]
        trailing = next(n for n in nodes if "Trailing bare text" in "".join(r.text for r in n.runs))
        assert isinstance(trailing, Paragraph)

    async def test_resuming_a_frame_flushes_an_implicit_paragraph_open_since_the_interrupt(self):
        # PR #478 review round: bare top-level text directly inside a still-
        # open <ol>/<ul> (not wrapped in its own <li>) opens an *implicit*
        # paragraph via handle_data's bare-text path (#343) without going
        # through _interrupt_open_block, so it has no frame of its own on
        # _block_stack. Resuming an outer interrupted block used to
        # unconditionally overwrite self._block_tag and clear self._run_buf,
        # silently destroying that implicit paragraph's text instead of
        # flushing it first — reachable via a mismatched inner list close
        # (the discard path from the test above) immediately followed by an
        # exact-matching outer list close.
        html = "<h1>Start<ol><li>B<ul><li>C</li></ol>D</ol>E"
        nodes = html_to_ast(html)
        texts_by_type = [(type(n).__name__, "".join(r.text for r in n.runs)) for n in nodes]
        assert texts_by_type == [
            ("Heading", "Start"),
            ("BulletItem", "B"),
            ("BulletItem", "C"),
            ("Paragraph", "D"),
            ("Heading", "E"),
        ]


class TestMismatchedListTags:
    """#382: a mismatched <ol>/<ul> close tag must not permanently desync
    _list_ordered — every subsequent BulletItem.depth is computed from
    len(_list_ordered) - 1, so a stuck extra entry bleeds a bogus depth
    into completely unrelated, later, well-formed lists."""

    async def test_mismatched_close_does_not_leak_depth_into_later_list(self):
        html = (
            "<ol><li>Parent<ul><li>Child</li></ol></li></ul>"
            "<p>Later text</p>"
            "<ol><li>Fresh ordered item</li></ol>"
        )
        nodes = html_to_ast(html)
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        fresh = next(b for b in bullets if b.runs[0].text == "Fresh ordered item")
        assert fresh.depth == 0
        assert fresh.ordered is True

    async def test_mismatched_close_does_not_leak_depth_into_later_ul(self):
        # Same defect, opposite direction: a <ul> closed by a stray </ol>.
        html = "<ul><li>Parent<ol><li>Child</li></ul></li></ol><ul><li>Fresh unordered</li></ul>"
        nodes = html_to_ast(html)
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        fresh = next(b for b in bullets if b.runs[0].text == "Fresh unordered")
        assert fresh.depth == 0
        assert fresh.ordered is False

    async def test_well_formed_nesting_unaffected(self):
        # Regression guard: the fix must not change behavior for correctly
        # matched tags — only mismatched ones should be affected.
        html = "<ul><li>a<ol><li>b</li></ol></li></ul><ul><li>Fresh sibling</li></ul>"
        nodes = html_to_ast(html)
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        fresh = next(b for b in bullets if b.runs[0].text == "Fresh sibling")
        assert fresh.depth == 0
        assert fresh.ordered is False


class TestBareTopLevelText:
    """#343: text with no wrapping block tag at all must not be silently
    dropped, while text merely wrapped in a non-block tag (e.g. <span>) with
    no block ancestor keeps its existing intentional drop behavior — see
    test_inline_only_html_skips_batchupdate."""

    async def test_bare_text_gets_implicit_paragraph(self):
        nodes = html_to_ast("hello world")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)
        assert "".join(r.text for r in nodes[0].runs) == "hello world"

    async def test_span_wrapped_text_still_dropped(self):
        # Regression guard: an inline tag with no block ancestor is a
        # deliberate choice by the caller and stays dropped, unlike
        # genuinely bare text.
        assert html_to_ast("<span>no blocks</span>") == []

    async def test_bare_text_with_inline_formatting_preserves_it(self):
        nodes = html_to_ast("hello <b>world</b> foo")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)
        runs = nodes[0].runs
        assert [(r.text, r.bold) for r in runs] == [
            ("hello ", None),
            ("world", True),
            (" foo", None),
        ]

    async def test_whitespace_only_top_level_text_produces_nothing(self):
        assert html_to_ast("  \n\n  ") == []

    async def test_bare_text_before_and_after_explicit_block_both_survive(self):
        nodes = html_to_ast("plain<p>tagged</p>trailing")
        texts = ["".join(r.text for r in n.runs) for n in nodes]
        assert texts == ["plain", "tagged", "trailing"]

    async def test_bare_text_after_unclosed_void_tag_still_wrapped(self):
        # Regression guard (found in PR #385's own review round): a void
        # element written without a self-closing slash (e.g. "<meta ...>",
        # not "<meta ... />") never gets a matching close tag from
        # HTMLParser. An implementation that excludes only "br" from
        # _tag_depth would leave the counter stuck above 0 here, silently
        # re-dropping the trailing bare text — the exact #343 failure mode.
        # <img> itself no longer exercises this specific path since #333 gave
        # it its own dedicated bare-top-level handling (see the sibling test
        # below) — <meta> stands in as a still-fully-unsupported void tag.
        nodes = html_to_ast('<meta charset="utf-8">hello world')
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)
        assert "".join(r.text for r in nodes[0].runs) == "hello world"

    async def test_bare_img_before_trailing_text_preserves_boundary(self):
        # #333: a bare top-level <img> (no wrapping <p> — only reachable via
        # raw HTML, since markdown's own "![]()" always renders wrapped in a
        # <p>) now gets the same boundary-preserving treatment <hr> already
        # has (sibling test below): its own Paragraph node, with the trailing
        # text becoming a second node rather than folding into one.
        nodes = html_to_ast('<img src="x.png">hello world')
        assert len(nodes) == 2
        assert isinstance(nodes[0], Paragraph)
        assert len(nodes[0].runs) == 1
        assert isinstance(nodes[0].runs[0], Image)
        assert nodes[0].runs[0].src == "x.png"
        assert isinstance(nodes[1], Paragraph)
        assert "".join(r.text for r in nodes[1].runs) == "hello world"

    async def test_bare_hr_before_trailing_text_preserves_boundary_and_tag_depth(self):
        # Same #343 tag_depth regression guard as above, but for bare <hr>: since
        # #401, a bare top-level <hr> now also emits its own empty Paragraph node
        # (preserving the thematic break's block boundary) rather than being a
        # pure no-op — so the trailing text becomes a *second* node, not folded
        # into the same one.
        nodes = html_to_ast("<hr>hello world")
        assert len(nodes) == 2
        assert isinstance(nodes[0], Paragraph)
        assert nodes[0].runs == []
        assert isinstance(nodes[1], Paragraph)
        assert "".join(r.text for r in nodes[1].runs) == "hello world"


# ---------------------------------------------------------------------------
# Markdown pipeline — _md_to_html and _to_doc_requests
# ---------------------------------------------------------------------------


class TestMdToHtml:
    async def test_heading_converts(self):
        html = _md_to_html("# Title")
        assert "<h1>" in html

    async def test_bold_converts(self):
        html = _md_to_html("**bold**")
        assert "<strong>" in html

    async def test_italic_converts(self):
        html = _md_to_html("*italic*")
        assert "<em>" in html

    async def test_unordered_list(self):
        html = _md_to_html("- item one\n- item two\n")
        assert "<ul>" in html
        assert "<li>" in html

    async def test_ordered_list(self):
        html = _md_to_html("1. first\n2. second\n")
        assert "<ol>" in html

    async def test_link(self):
        html = _md_to_html("[click](https://example.com)")
        assert 'href="https://example.com"' in html

    async def test_pipe_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        html = _md_to_html(md)
        assert "<table>" in html

    async def test_fenced_code_block(self):
        md = "```python\nx = 1\n```\n"
        html = _md_to_html(md)
        assert "<pre>" in html
        assert "<code" in html  # may include class="language-python"

    async def test_escaped_dollar_renders_literal_dollar(self):
        # Python-Markdown's default ESCAPED_CHARS omits $ (unlike CommonMark), so \$
        # otherwise passes through untouched as a literal backslash+dollar (issue #213).
        html = _md_to_html(r"Cost: \$6,000")
        assert "$6,000" in html
        assert r"\$" not in html

    async def test_escaped_dollar_in_table_cell(self):
        md = "| Deductible | \\$6,000 |\n|---|---|\n"
        html = _md_to_html(md)
        assert "$6,000" in html
        assert r"\$" not in html

    async def test_unescaped_dollar_untouched(self):
        html = _md_to_html("Price is $5 not six")
        assert "Price is $5 not six" in html

    async def test_escaped_dollar_inside_fenced_code_stays_literal(self):
        # The escape must respect code protection like every other ESCAPED_CHARS entry —
        # a shell variable escape inside a code block is not the same $ as in prose.
        md = "```\nvar=\\$5\n```\n"
        html = _md_to_html(md)
        assert r"\$5" in html

    async def test_escaped_dollar_inside_inline_code_stays_literal(self):
        html = _md_to_html(r"Use `\$VAR` in shell")
        assert r"\$VAR" in html

    async def test_bare_url_autolinked(self):
        # Python-Markdown's core autolink only fires on <https://...> or [text](url),
        # leaving a bare URL as inert text (issue #248).
        html = _md_to_html("From: https://example.com/some-page")
        assert '<a href="https://example.com/some-page">https://example.com/some-page</a>' in html

    async def test_bare_url_trailing_period_not_swallowed(self):
        html = _md_to_html("Visit https://example.com/page. Thanks.")
        assert '<a href="https://example.com/page">https://example.com/page</a>. Thanks.' in html

    async def test_bare_url_wrapping_parens_not_swallowed(self):
        html = _md_to_html("See (https://example.com/page) for details")
        assert '(<a href="https://example.com/page">https://example.com/page</a>)' in html

    async def test_bare_url_with_internal_paren_preserved(self):
        html = _md_to_html("See https://example.com/wiki/Foo_(bar) here")
        assert 'href="https://example.com/wiki/Foo_(bar)"' in html

    async def test_bare_url_inside_markdown_link_not_double_linked(self):
        html = _md_to_html("[click](https://example.com)")
        assert html.count("<a ") == 1

    async def test_bare_url_inside_inline_code_untouched(self):
        html = _md_to_html("In code: `https://example.com`")
        assert "<code>https://example.com</code>" in html
        assert "<a " not in html

    async def test_bare_url_inside_fenced_code_untouched(self):
        md = "```\nhttps://example.com\n```\n"
        html = _md_to_html(md)
        assert "<a " not in html

    async def test_multiple_bare_urls_each_linked(self):
        html = _md_to_html("Multi https://a.example.com and https://b.example.com here")
        assert html.count("<a ") == 2

    async def test_autolink_urls_false_leaves_bare_url_as_text(self):
        html = _md_to_html("See https://example.com here", autolink_urls=False)
        assert html == "<p>See https://example.com here</p>"

    async def test_autolink_urls_false_does_not_affect_markdown_links(self):
        html = _md_to_html("[click](https://example.com)", autolink_urls=False)
        assert 'href="https://example.com"' in html


class TestToDocRequestsMarkdown:
    async def test_h1_in_markdown_produces_heading_1(self):
        requests, _ = _to_doc_requests("# Title", "markdown")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in styles

    async def test_markdown_matches_html_for_heading(self):
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

    async def test_markdown_list_produces_bullet(self):
        requests, _ = _to_doc_requests("- item\n", "markdown")
        assert any("createParagraphBullets" in r for r in requests)

    async def test_markdown_ordered_list_produces_numbered_bullet(self):
        requests, _ = _to_doc_requests("1. first\n", "markdown")
        bullet_reqs = [r for r in requests if "createParagraphBullets" in r]
        assert any("NUMBERED" in r["createParagraphBullets"]["bulletPreset"] for r in bullet_reqs)

    async def test_markdown_bare_url_emits_link_text_style(self):
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

    async def test_markdown_bare_url_autolink_urls_false_emits_no_link_text_style(self):
        requests, _ = _to_doc_requests(
            "From: https://example.com/some-page", "markdown", autolink_urls=False
        )
        link_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]
        ]
        assert link_reqs == []

    async def test_markdown_bold_emits_text_style(self):
        requests, _ = _to_doc_requests("**bold**\n", "markdown")
        bold_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold") is True
        ]
        assert len(bold_reqs) >= 1

    async def test_markdown_task_list_checked(self):
        requests, _ = _to_doc_requests("- [x] Done\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert "☑" in insert["insertText"]["text"]

    async def test_markdown_task_list_unchecked(self):
        requests, _ = _to_doc_requests("- [ ] Todo\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert "☐" in insert["insertText"]["text"]

    async def test_markdown_fenced_code_emits_font_family(self):
        requests, _ = _to_doc_requests("```\nx = 1\n```\n", "markdown")
        font_reqs = [
            r
            for r in requests
            if "updateTextStyle" in r and "weightedFontFamily" in r["updateTextStyle"]["textStyle"]
        ]
        assert len(font_reqs) >= 1

    async def test_markdown_image_and_thematic_break_preserve_paragraph_boundary(self):
        # #401 end-to-end repro: an unsupported image followed by a thematic
        # break, followed by real headings, must not fuse into one run of
        # touching text — each unsupported construct keeps its own blank line.
        md = "![Kindly Human](kh-logo.png)\n\n# Kindly Human\n\n---\n\n## PURPOSE\n"
        requests, _ = _to_doc_requests(md, "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "\nKindly Human\n\nPURPOSE\n"

    async def test_html_format_still_works(self):
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

    async def test_markdown_heading_in_create_doc(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](
            title="Doc", content="# Title", content_format="markdown", ctx=ctx
        )
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    async def test_html_format_default_unchanged(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types


class TestResolveImageSource:
    """Unit coverage for _resolve_image_source's three src kinds (#333)."""

    async def test_https_url_used_directly_no_upload_no_share(self):
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, "https://example.com/a.png", "folder1")
        assert result == {"uri": "https://example.com/a.png"}
        drive_svc.files.assert_not_called()
        drive_svc.permissions.assert_not_called()

    async def test_http_url_used_directly(self):
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, "http://example.com/a.png", "folder1")
        assert result == {"uri": "http://example.com/a.png"}

    async def test_drive_reference_shared_and_resolved(self):
        drive_svc = MagicMock()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert result == {
            "uri": "https://drive.google.com/uc?id=file1",
            "file_id": "file1",
            "permission_id": "perm1",
        }
        drive_svc.permissions.return_value.create.assert_called_once_with(
            fileId="file1",
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
            fields="id",
        )

    async def test_drive_reference_with_no_file_id_is_error(self):
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, "drive:", "folder1")
        assert "error" in result
        drive_svc.permissions.assert_not_called()

    async def test_local_path_missing_is_error(self, tmp_path):
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, str(tmp_path / "missing.png"), "folder1")
        assert "error" in result
        assert "No file found" in result["error"]

    async def test_local_path_with_no_folder_id_is_error(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, str(img), None)
        assert "error" in result
        assert "folder_id" in result["error"]

    async def test_local_path_uploaded_shared_and_resolved(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "uploaded1",
            "name": "pic.png",
            "webViewLink": "https://drive.google.com/file/d/uploaded1/view",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm2"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=uploaded1"
        }
        result = await _resolve_image_source(drive_svc, str(img), "folder1")
        assert result == {
            "uri": "https://drive.google.com/uc?id=uploaded1",
            "file_id": "uploaded1",
            "permission_id": "perm2",
        }

    async def test_sharing_failure_is_error(self, tmp_path):
        drive_svc = MagicMock()
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = RuntimeError(
            "boom"
        )
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert "error" in result
        assert "boom" in result["error"]

    async def test_missing_web_content_link_is_error(self):
        drive_svc = MagicMock()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {}
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert "error" in result
        assert "webContentLink" in result["error"]


class TestCreateDocImages:
    """End-to-end coverage for #333's markdown-image path through create_doc."""

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

    def _ctx(self, drive_svc, docs_svc, folder_id=None):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=folder_id,
            drive_folder_cache=MagicMock(),
        )

    def _batchupdate_requests(self, docs_svc):
        return docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]

    async def test_https_image_embedded_inline(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="![Alt](https://example.com/a.png)",
            content_format="markdown",
            ctx=ctx,
        )
        image_reqs = [r for r in self._batchupdate_requests(docs_svc) if "insertInlineImage" in r]
        assert len(image_reqs) == 1
        assert image_reqs[0]["insertInlineImage"]["uri"] == "https://example.com/a.png"
        # No upload/share needed for a public URL — nothing to revoke, so this
        # image contributes only "src" to its outcome entry.
        assert result["images"] == [{"src": "https://example.com/a.png"}]
        drive_svc.permissions.assert_not_called()

    async def test_drive_reference_image_shared_then_revoked_by_default(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="![Alt](drive:file1)",
            content_format="markdown",
            ctx=ctx,
        )
        assert result["images"] == [{"src": "drive:file1", "fileId": "file1", "shared": False}]
        drive_svc.permissions.return_value.delete.assert_called_once_with(
            fileId="file1", permissionId="perm1", supportsAllDrives=True
        )

    async def test_revoke_sharing_false_leaves_image_shared(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="![Alt](drive:file1)",
            content_format="markdown",
            revoke_sharing=False,
            ctx=ctx,
        )
        assert result["images"] == [{"src": "drive:file1", "fileId": "file1", "shared": True}]
        drive_svc.permissions.return_value.delete.assert_not_called()

    async def test_revoke_failure_reported_without_failing_call(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        drive_svc.permissions.return_value.delete.return_value.execute.side_effect = RuntimeError(
            "revoke boom"
        )
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="![Alt](drive:file1)",
            content_format="markdown",
            ctx=ctx,
        )
        assert result["images"] == [
            {
                "src": "drive:file1",
                "fileId": "file1",
                "shared": True,
                "revoke_error": "revoke boom",
            }
        ]

    async def test_unresolvable_image_reported_as_error_doc_still_created(self, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        missing = str(tmp_path / "missing.png")
        result = await _docs_tools["create_doc"](
            title="Doc",
            content=f"Before\n\n![Alt]({missing})\n\nAfter",
            content_format="markdown",
            ctx=ctx,
        )
        assert result["images"] == [{"src": missing, "error": f"No file found at {missing!r}"}]
        # The image itself never made it into the doc — no insertInlineImage request —
        # but the surrounding text still went through.
        image_reqs = [r for r in self._batchupdate_requests(docs_svc) if "insertInlineImage" in r]
        assert image_reqs == []
        insert = next(r for r in self._batchupdate_requests(docs_svc) if "insertText" in r)
        assert "Before" in insert["insertText"]["text"]
        assert "After" in insert["insertText"]["text"]

    async def test_no_images_omits_images_key(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](title="Doc", content="<p>plain</p>", ctx=ctx)
        assert "images" not in result

    def _insert_image_http_error(self, index: int) -> HttpError:
        resp = MagicMock()
        resp.status = 400
        message = (
            f"Invalid requests[{index}].insertInlineImage: There was a problem "
            "retrieving the image. The provided image should be publicly "
            "accessible, within size limit, and in supported formats."
        )
        content = json.dumps({"error": {"code": 400, "message": message}}).encode()
        return HttpError(
            resp=resp, content=content, uri="https://docs.googleapis.com/v1/documents/x:batchUpdate"
        )

    async def test_one_bad_image_url_does_not_fail_the_whole_document(self):
        # #333 live regression (TC-DOC102 Case 8, confirmed against the real Docs
        # API): a single unfetchable image URI made the Docs API reject the
        # *entire* batchUpdate — text, tables, and every other image in the same
        # call — since a rejected batch executes nothing. Google's own error
        # names the failing request's index directly, so the fix retries with
        # that exact request stripped rather than needing to recompute anything.
        drive_svc, docs_svc = self._make_services()
        good_uri = "https://example.com/good.png"
        bad_uri = "https://example.com/bad.png"
        content = f"Before\n\n![Good]({good_uri})\n\n![Bad]({bad_uri})\n\nAfter"
        # Two insertInlineImage requests are queued (good first in doc order —
        # see the fixture text — so the bad one is request index 1 among them,
        # but its actual index within the full combined request list is
        # whatever ast_to_requests produced; find it dynamically below instead
        # of hand-computing it, since that's exactly the kind of position
        # bookkeeping this fix is designed not to need).
        first_call_requests = []

        def batchupdate_side_effect(documentId, body):
            nonlocal first_call_requests
            m = MagicMock()
            if not first_call_requests:
                first_call_requests = body["requests"]
                bad_index = next(
                    i
                    for i, r in enumerate(body["requests"])
                    if r.get("insertInlineImage", {}).get("uri") == bad_uri
                )
                m.execute.side_effect = self._insert_image_http_error(bad_index)
            else:
                m.execute.return_value = {}
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = batchupdate_side_effect
        ctx = self._ctx(drive_svc, docs_svc)

        result = await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )

        outcomes = {o["src"]: o for o in result["images"]}
        assert "error" not in outcomes[good_uri]
        assert "error" in outcomes[bad_uri]
        assert "doc edit failed" in outcomes[bad_uri]["error"]

        # The retried (second) batchUpdate call must still contain the good
        # image's request and everything else — only the bad one was removed.
        second_call_requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"][
            "requests"
        ]
        assert any(
            r.get("insertInlineImage", {}).get("uri") == good_uri for r in second_call_requests
        )
        assert not any(
            r.get("insertInlineImage", {}).get("uri") == bad_uri for r in second_call_requests
        )
        assert docs_svc.documents.return_value.batchUpdate.call_count == 2


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

    async def test_md_file_creates_doc(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Hello\n\nParagraph text.\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        assert "docId" in result
        assert "error" not in result

    async def test_md_file_title_defaults_to_stem(self, tmp_path):
        md_file = tmp_path / "my-notes.md"
        md_file.write_text("# Content\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        create_body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert create_body["name"] == "my-notes"

    async def test_md_file_explicit_title_used(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Content\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc_from_file"](local_path=str(md_file), title="My Doc", ctx=ctx)
        create_body = drive_svc.files.return_value.create.call_args.kwargs["body"]
        assert create_body["name"] == "My Doc"

    async def test_md_file_heading_emitted(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Section\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    async def test_html_file_accepted(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<h2>Hello</h2>")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc_from_file"](local_path=str(html_file), ctx=ctx)
        assert "docId" in result
        assert "error" not in result

    async def test_file_not_found_returns_error(self, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc_from_file"](
            local_path=str(tmp_path / "missing.md"), ctx=ctx
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_unsupported_extension_returns_error(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("plain text")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc_from_file"](local_path=str(txt_file), ctx=ctx)
        assert "error" in result
        assert ".txt" in result["error"]


# ---------------------------------------------------------------------------
# get_doc_structure headingId (#409)
# ---------------------------------------------------------------------------


class TestGetDocStructureHeadingId:
    def _ctx(self, docs_svc):
        return _make_ctx(docs_service=docs_svc)

    def _doc(self, named_style, heading_id=None):
        pstyle = {"namedStyleType": named_style}
        if heading_id is not None:
            pstyle["headingId"] = heading_id
        return {
            "documentId": "doc1",
            "title": "Doc",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "paragraphStyle": pstyle,
                            "elements": [{"textRun": {"content": "Text\n", "textStyle": {}}}],
                        },
                    }
                ]
            },
        }

    async def test_heading_paragraph_includes_heading_id(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = self._doc(
            "HEADING_1", heading_id="h.abc123"
        )
        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))
        assert result["elements"][0]["headingId"] == "h.abc123"

    async def test_normal_paragraph_has_null_heading_id(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = self._doc(
            "NORMAL_TEXT"
        )
        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))
        assert result["elements"][0]["headingId"] is None


# ---------------------------------------------------------------------------
# Heading-anchor resolution (#409): _has_pending_anchor_links,
# _resolve_heading_anchors, and end-to-end via create_doc_from_file.
# ---------------------------------------------------------------------------


class TestHasPendingAnchorLinks:
    def test_true_for_hash_link(self):
        requests = [{"updateTextStyle": {"textStyle": {"link": {"url": "#some-slug"}}}}]
        assert _has_pending_anchor_links(requests, []) is True

    def test_false_for_ordinary_https_link(self):
        requests = [{"updateTextStyle": {"textStyle": {"link": {"url": "https://example.com"}}}}]
        assert _has_pending_anchor_links(requests, []) is False

    def test_false_when_no_link_requests(self):
        assert _has_pending_anchor_links([{"insertText": {"text": "hi"}}], []) is False

    def test_false_for_empty_requests(self):
        assert _has_pending_anchor_links([], []) is False

    def _table_with_link(self, link_url):
        return Table(
            rows=[
                Row(
                    cells=[
                        Cell(children=[Run(text="link text", link_url=link_url)]),
                    ]
                )
            ]
        )

    def test_true_for_table_cell_anchor_link_with_no_top_level_link(self):
        # Regression: a table-only anchor link (no top-level paragraph link at
        # all) must still be detected — fill_tables() builds and executes its
        # own requests separately, invisible to `requests` alone.
        table = self._table_with_link("#some-slug")
        assert _has_pending_anchor_links([], [table]) is True

    def test_false_for_table_cell_ordinary_link(self):
        table = self._table_with_link("https://example.com")
        assert _has_pending_anchor_links([], [table]) is False

    def test_true_for_anchor_link_in_nested_table(self):
        inner = self._table_with_link("#nested-slug")
        outer = Table(rows=[Row(cells=[Cell(children=[inner])])])
        assert _has_pending_anchor_links([], [outer]) is True


class TestResolveHeadingAnchorsHelper:
    def _doc_with_anchor(self, anchor_url, heading_text="Overview", heading_id="h.xyz"):
        return {
            "documentId": "doc1",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 1 + len(heading_text) + 1,
                        "paragraph": {
                            "paragraphStyle": {
                                "namedStyleType": "HEADING_1",
                                "headingId": heading_id,
                            },
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 1 + len(heading_text) + 1,
                                    "textRun": {"content": heading_text + "\n", "textStyle": {}},
                                }
                            ],
                        },
                    },
                    {
                        "startIndex": 20,
                        "endIndex": 25,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                            "elements": [
                                {
                                    "startIndex": 20,
                                    "endIndex": 25,
                                    "textRun": {
                                        "content": "Link\n",
                                        "textStyle": {"link": {"url": anchor_url}},
                                    },
                                }
                            ],
                        },
                    },
                ]
            },
        }

    async def test_matched_anchor_rewritten_to_heading_url(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = (
            self._doc_with_anchor("#overview", heading_text="Overview", heading_id="h.xyz")
        )
        summary = await _resolve_heading_anchors(docs_svc, "doc1")
        assert summary["resolved"] == [{"anchor": "#overview", "heading": "Overview"}]
        assert summary["stripped"] == []

        requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        assert len(requests) == 1
        style = requests[0]["updateTextStyle"]
        # "Link\n" is 5 UTF-16 units; the range is computed by advancing from
        # the run's own startIndex (20) through its content, matching
        # _collect_doc_paragraphs's convention — not read from the mock's
        # own (unused) endIndex field.
        assert style["range"] == {"startIndex": 20, "endIndex": 25}
        assert style["fields"] == "link"
        assert style["textStyle"]["link"]["url"] == (
            "https://docs.google.com/document/d/doc1/edit?tab=t.0#heading=h.xyz"
        )

    async def test_unmatched_anchor_stripped_not_guessed(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = (
            self._doc_with_anchor("#nonexistent", heading_text="Overview", heading_id="h.xyz")
        )
        summary = await _resolve_heading_anchors(docs_svc, "doc1")
        assert summary["resolved"] == []
        assert summary["stripped"] == ["#nonexistent"]

        requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        assert len(requests) == 1
        style = requests[0]["updateTextStyle"]
        # Omit the "link" key entirely (while still naming it in the field mask) —
        # setting textStyle.link = {} is rejected by the Docs API outright (#408).
        assert style["fields"] == "link"
        assert style["textStyle"] == {}

    async def test_no_anchor_links_skips_batchupdate(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "body": {"content": []},
        }
        summary = await _resolve_heading_anchors(docs_svc, "doc1")
        assert summary == {"resolved": [], "stripped": []}
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_anchor_link_inside_table_cell_is_resolved(self):
        # Regression: the body walk used to only look at top-level
        # elem.get("paragraph") and never descended into elem.get("table"),
        # so a #slug link inside a table cell was invisible.
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "paragraphStyle": {
                                "namedStyleType": "HEADING_1",
                                "headingId": "h.xyz",
                            },
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 10,
                                    "textRun": {"content": "Overview\n", "textStyle": {}},
                                }
                            ],
                        },
                    },
                    {
                        "startIndex": 20,
                        "endIndex": 40,
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "startIndex": 22,
                                            "endIndex": 35,
                                            "content": [
                                                {
                                                    "startIndex": 23,
                                                    "endIndex": 30,
                                                    "paragraph": {
                                                        "paragraphStyle": {
                                                            "namedStyleType": "NORMAL_TEXT"
                                                        },
                                                        "elements": [
                                                            {
                                                                "startIndex": 23,
                                                                "endIndex": 28,
                                                                "textRun": {
                                                                    "content": "Link\n",
                                                                    "textStyle": {
                                                                        "link": {"url": "#overview"}
                                                                    },
                                                                },
                                                            }
                                                        ],
                                                    },
                                                }
                                            ],
                                        }
                                    ]
                                }
                            ]
                        },
                    },
                ]
            },
        }
        summary = await _resolve_heading_anchors(docs_svc, "doc1")
        assert summary["resolved"] == [{"anchor": "#overview", "heading": "Overview"}]

        requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        style = requests[0]["updateTextStyle"]
        assert style["range"] == {"startIndex": 23, "endIndex": 28}
        assert style["textStyle"]["link"]["url"] == (
            "https://docs.google.com/document/d/doc1/edit?tab=t.0#heading=h.xyz"
        )

    async def test_anchor_on_doc_first_element_with_no_start_index_is_resolved(self):
        # Regression: the Docs API omits startIndex on a document's very
        # first element. The old code required both startIndex and endIndex
        # on the run itself and silently dropped the anchor when absent.
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "body": {
                "content": [
                    {
                        # No startIndex on this element at all (first element).
                        "endIndex": 6,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                            "elements": [
                                {
                                    # No startIndex on the run either.
                                    "endIndex": 6,
                                    "textRun": {
                                        "content": "Link\n",
                                        "textStyle": {"link": {"url": "#overview"}},
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "startIndex": 6,
                        "endIndex": 16,
                        "paragraph": {
                            "paragraphStyle": {
                                "namedStyleType": "HEADING_1",
                                "headingId": "h.xyz",
                            },
                            "elements": [
                                {
                                    "startIndex": 6,
                                    "endIndex": 15,
                                    "textRun": {"content": "Overview\n", "textStyle": {}},
                                }
                            ],
                        },
                    },
                ]
            },
        }
        summary = await _resolve_heading_anchors(docs_svc, "doc1")
        assert summary["resolved"] == [{"anchor": "#overview", "heading": "Overview"}]

        requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        style = requests[0]["updateTextStyle"]
        # Runs from offset 1 (the implicit start of the doc's first element,
        # same convention as _collect_doc_paragraphs) through the run's own
        # 5-UTF-16-unit content "Link\n".
        assert style["range"] == {"startIndex": 1, "endIndex": 6}


class TestCreateDocFromFileAnchorResolution:
    def _make_services(self, doc_id="doc123"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": doc_id,
            "name": "myfile",
            "parents": ["root"],
            "webViewLink": "https://example.com",
        }
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": doc_id,
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 10,
                        "paragraph": {
                            "paragraphStyle": {
                                "namedStyleType": "HEADING_1",
                                "headingId": "h.section",
                            },
                            "elements": [
                                {
                                    "startIndex": 1,
                                    "endIndex": 10,
                                    "textRun": {"content": "Section\n", "textStyle": {}},
                                }
                            ],
                        },
                    },
                    {
                        "startIndex": 20,
                        "endIndex": 25,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                            "elements": [
                                {
                                    "startIndex": 20,
                                    "endIndex": 25,
                                    "textRun": {
                                        "content": "link\n",
                                        "textStyle": {"link": {"url": "#section"}},
                                    },
                                }
                            ],
                        },
                    },
                ]
            },
        }
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            folder_id=None,
            drive_folder_cache=MagicMock(),
        )

    async def test_anchor_link_triggers_resolution_pass(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Section\n\n[jump](#section)\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)

        calls = docs_svc.documents.return_value.batchUpdate.call_args_list
        assert len(calls) == 2  # content insert, then anchor resolution
        resolution_requests = calls[1].kwargs["body"]["requests"]
        assert resolution_requests[0]["updateTextStyle"]["textStyle"]["link"]["url"] == (
            "https://docs.google.com/document/d/doc123/edit?tab=t.0#heading=h.section"
        )

    async def test_no_anchor_link_skips_resolution_pass(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Section\n\nJust text, no links.\n")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["create_doc_from_file"](local_path=str(md_file), ctx=ctx)

        calls = docs_svc.documents.return_value.batchUpdate.call_args_list
        assert len(calls) == 1  # only the content insert
        docs_svc.documents.return_value.get.assert_not_called()


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

    async def test_uri_only_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=5, uri="https://example.com/img.png", ctx=ctx
        )
        assert result == {"docId": "doc1", "index": 5}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["location"]["index"] == 5
        assert req["uri"] == "https://example.com/img.png"
        assert "objectSize" not in req

    async def test_width_and_height_included(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        await _docs_tools["insert_inline_image"](
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

    async def test_drive_file_id_fetches_web_content_link(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=3, drive_file_id="file1", ctx=ctx
        )
        assert "error" not in result
        drive_svc.files.return_value.get.assert_called_with(
            fileId="file1", fields="webContentLink", supportsAllDrives=True
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertInlineImage"]
        assert req["uri"] == "https://drive.google.com/uc?id=file1"

    async def test_missing_both_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_inline_image"](doc_id="doc1", index=1, ctx=ctx)
        assert "error" in result

    async def test_both_provided_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1",
            index=1,
            uri="https://example.com/img.png",
            drive_file_id="file1",
            ctx=ctx,
        )
        assert "error" in result

    async def test_drive_file_no_web_content_link_returns_error(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {}
        ctx = self._ctx(drive_svc=drive_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, drive_file_id="file1", ctx=ctx
        )
        assert "error" in result

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_inline_image"](
            doc_id="doc1", index=1, uri="https://example.com/img.png", ctx=ctx
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# insert_page_break (#148)
# ---------------------------------------------------------------------------


class TestInsertPageBreak:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_sends_correct_request(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_page_break"](doc_id="doc1", index=5, ctx=ctx)
        assert result == {"docId": "doc1", "index": 5}
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["insertPageBreak"]
        assert req["location"]["index"] == 5

    async def test_marks_doc_cache_dirty(self):
        docs_svc = MagicMock()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["insert_page_break"](doc_id="doc1", index=1, ctx=ctx)
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["insert_page_break"](doc_id="doc1", index=1, ctx=ctx)
        assert "error" in result


class TestCreateNamedRange:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _docs_svc(self, named_range_id="nr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createNamedRange": {"namedRangeId": named_range_id}}]
        }
        return docs_svc

    async def test_sends_correct_request(self):
        docs_svc = self._docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["createNamedRange"]
        assert req["name"] == "section-a"
        assert req["range"] == {"startIndex": 5, "endIndex": 10}
        assert result == {
            "docId": "doc1",
            "namedRangeId": "nr1",
            "name": "section-a",
            "startIndex": 5,
            "endIndex": 10,
        }

    async def test_marks_doc_cache_dirty(self):
        docs_svc = self._docs_svc()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        assert "error" in result

    async def test_success_response_with_empty_replies_returns_error_not_crash(self):
        """Regression (PR #337 review): a success response with no/empty replies must
        not raise IndexError/KeyError — every sibling tool in this file guarantees
        {"error": ...} instead."""
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        result = await _docs_tools["create_named_range"](
            doc_id="doc1", name="section-a", start_index=5, end_index=10, ctx=ctx
        )
        assert "error" in result
        doc_cache.mark_dirty.assert_not_called()


class TestCreateBookmark:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    def _docs_svc(self, named_range_id="nr1"):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": [{"createNamedRange": {"namedRangeId": named_range_id}}]
        }
        return docs_svc

    async def test_sends_single_character_named_range(self):
        docs_svc = self._docs_svc()
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        req = body["requests"][0]["createNamedRange"]
        assert req["name"] == "intro"
        assert req["range"] == {"startIndex": 7, "endIndex": 8}
        assert result == {
            "docId": "doc1",
            "namedRangeId": "nr1",
            "name": "intro",
            "index": 7,
        }

    async def test_marks_doc_cache_dirty(self):
        docs_svc = self._docs_svc()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc=docs_svc)
        result = await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        assert "error" in result

    async def test_success_response_with_empty_replies_returns_error_not_crash(self):
        """Regression (PR #337 review): a success response with no/empty replies must
        not raise IndexError/KeyError — every sibling tool in this file guarantees
        {"error": ...} instead."""
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        result = await _docs_tools["create_bookmark"](doc_id="doc1", name="intro", index=7, ctx=ctx)
        assert "error" in result
        doc_cache.mark_dirty.assert_not_called()


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

    async def test_returns_content(self):
        ctx = self._ctx()
        result = await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)
        assert result["content"] == "hello world"

    async def test_oversized_result_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(drive_svc=self._drive_svc(content=b"x" * 1000))
        with pytest.raises(ValueError, match="safety cap"):
            await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

    async def test_cached_oversized_result_also_raises(self, monkeypatch):
        # Regression: the cap check used to run only on the fetch path (before the
        # doc_cache early-return), so a cached oversized doc would bypass it on repeat
        # calls (issue #242).
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        cached_result = {"id": "doc1", "content": "x" * 1000}
        doc_cache = MagicMock(get=MagicMock(return_value=cached_result))
        ctx = self._ctx(doc_cache=doc_cache)
        with pytest.raises(ValueError, match="safety cap"):
            await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

    async def test_local_path_bypasses_cap_and_writes_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        ctx = self._ctx(drive_svc=self._drive_svc(content=b"x" * 1000))
        dest = tmp_path / "out.json"
        result = await _docs_tools["get_doc_content"](file_id="doc1", local_path=str(dest), ctx=ctx)
        assert result["local_path"] == str(dest)
        assert result["id"] == "doc1"
        written = json.loads(dest.read_text())
        assert written["content"] == "x" * 1000


class TestGetDocContentModifiedTimeValidation:
    """Regression test (issue #99 review): get_doc_content used to make two
    separate Drive files().get() calls on every cache miss when
    CACHE_VALIDATE_MODIFIED_TIME was enabled — one lightweight modifiedTime-only
    call to check for a cache hit, then a second, redundant full-metadata call
    that already includes modifiedTime. Fixed to reuse the first call's result.
    """

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

    async def test_cache_miss_makes_a_single_metadata_call(self, monkeypatch):
        monkeypatch.setattr(content_module, "CACHE_VALIDATE_MODIFIED_TIME", True)
        drive_svc = self._drive_svc()
        ctx = _make_ctx(
            drive_service=drive_svc,
            doc_cache=MagicMock(get=MagicMock(return_value=None)),
        )

        result = await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

        assert result["content"] == "hello world"
        assert drive_svc.files.return_value.get.call_count == 1

    async def test_cache_hit_makes_a_single_metadata_call_and_no_export(self, monkeypatch):
        monkeypatch.setattr(content_module, "CACHE_VALIDATE_MODIFIED_TIME", True)
        drive_svc = self._drive_svc()
        cached_result = {
            "id": "doc1",
            "content": "cached",
            "modified_time": "2026-01-01T00:00:00Z",
        }
        doc_cache = MagicMock(get=MagicMock(return_value=cached_result))
        ctx = _make_ctx(drive_service=drive_svc, doc_cache=doc_cache)

        result = await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

        assert result["content"] == "cached"
        assert drive_svc.files.return_value.get.call_count == 1
        drive_svc.files.return_value.export.assert_not_called()


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

    async def test_clears_trailing_mark_style_before_deleting_in_its_own_batch(self):
        drive_svc, docs_svc = self._make_services(end_index=50)
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["write_doc_content"](doc_id="doc1", content="<p>New content</p>", ctx=ctx)
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

    async def test_empty_doc_skips_clear_requests(self):
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["write_doc_content"](doc_id="doc1", content="<p>New content</p>", ctx=ctx)
        calls = self._batchupdate_calls(docs_svc)
        # Only one batchUpdate call (the content) — no separate clear/delete call.
        assert len(calls) == 1
        assert not any(
            "updateTextStyle" in r and r["updateTextStyle"].get("fields") == "*" for r in calls[0]
        )
        assert not any("deleteContentRange" in r for r in calls[0])

    async def test_https_image_embedded_and_reported(self):
        # write_doc_content shares _apply_doc_content with create_doc (#333) —
        # this is a thin wiring check, not a re-test of resolution logic
        # already covered by TestResolveImageSource/TestCreateDocImages.
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="![Alt](https://example.com/a.png)",
            content_format="markdown",
            ctx=ctx,
        )
        calls = self._batchupdate_calls(docs_svc)
        image_reqs = [r for r in calls[-1] if "insertInlineImage" in r]
        assert len(image_reqs) == 1
        assert image_reqs[0]["insertInlineImage"]["uri"] == "https://example.com/a.png"
        assert result["images"] == [{"src": "https://example.com/a.png"}]


def _build_doc_body(paragraph_runs: list[list[str]]) -> tuple[dict, list[tuple[int, str]]]:
    """Build a synthetic Docs API body from a list of paragraphs, each a list of
    textRun content strings (the last run of a paragraph should end in "\\n",
    matching how the real API terminates a paragraph). Returns (doc, paragraphs)
    where paragraphs is [(start_index, concatenated_text), ...] for computing
    expected offsets in tests without hand-counting characters."""
    idx = 1
    content = []
    paragraphs = []
    for runs in paragraph_runs:
        para_start = idx
        elements = []
        for text in runs:
            elements.append(
                {"startIndex": idx, "endIndex": idx + len(text), "textRun": {"content": text}}
            )
            idx += len(text)
        content.append(
            {"startIndex": para_start, "endIndex": idx, "paragraph": {"elements": elements}}
        )
        paragraphs.append((para_start, "".join(runs)))
    return {"body": {"content": content}}, paragraphs


class TestCollectDocParagraphs:
    def test_single_run_paragraph(self):
        doc, paragraphs = _build_doc_body([["Hello world\n"]])
        result = list(_collect_doc_paragraphs(doc["body"]["content"]))
        assert result == [("Hello world\n", list(range(1, 13)))]

    def test_multi_run_paragraph_indices_stay_contiguous(self):
        doc, _ = _build_doc_body([["Contact: ", "test@example.com", " again\n"]])
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        assert text == "Contact: test@example.com again\n"
        assert indices == list(range(1, 1 + len(text)))

    def test_missing_start_index_carries_offset_forward_instead_of_dropping(self):
        # Regression: the Docs API doesn't always populate a ParagraphElement's
        # startIndex (observed on a document's very first element). The old
        # implementation silently dropped any run missing it; this run's index
        # must instead be derived from the paragraph's own startIndex.
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "paragraph": {
                            "elements": [{"textRun": {"content": "no index\n"}}],
                        },
                    }
                ]
            }
        }
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        assert text == "no index\n"
        assert indices == list(range(1, 1 + len(text)))

    def test_missing_start_index_at_both_levels_defaults_to_document_start(self):
        # Regression: Google Docs body content is never index 0 — when the
        # very first element of a document omits startIndex at both the
        # paragraph and its first run (the actual documented quirk), the
        # fallback must be 1, not 0.
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": "no index anywhere\n"}}],
                        },
                    }
                ]
            }
        }
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        assert text == "no index anywhere\n"
        assert indices == list(range(1, 1 + len(text)))

    def test_astral_character_advances_offset_by_two_utf16_units(self):
        # Regression: Docs API indices are UTF-16 code units. "😀" (U+1F600) is
        # one Python character but a surrogate pair (2 units) in UTF-16 — the
        # character immediately after it must land 2 units past its own index,
        # not 1.
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"startIndex": 1, "textRun": {"content": "hi 😀 bye\n"}}],
                        },
                    }
                ]
            }
        }
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        emoji_pos = text.index("😀")
        assert indices[emoji_pos + 1] == indices[emoji_pos] + 2

    def test_recurses_into_table_cells(self):
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 2,
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [
                                                            {
                                                                "startIndex": 3,
                                                                "endIndex": 10,
                                                                "textRun": {
                                                                    "content": "cell one\n"
                                                                },
                                                            }
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                    }
                ]
            }
        }
        result = list(_collect_doc_paragraphs(doc["body"]["content"]))
        assert result == [("cell one\n", list(range(3, 12)))]

    def test_skips_non_text_paragraph_elements(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"startIndex": 1, "endIndex": 2, "pageBreak": {}},
                                {
                                    "startIndex": 2,
                                    "endIndex": 8,
                                    "textRun": {"content": "text\n"},
                                },
                            ]
                        }
                    }
                ]
            }
        }
        result = list(_collect_doc_paragraphs(doc["body"]["content"]))
        assert result == [("text\n", [2, 3, 4, 5, 6])]


class TestFindInDoc:
    def _ctx(self, docs_svc):
        return _make_ctx(docs_service=docs_svc)

    def _docs_svc(self, doc):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = doc
        return docs_svc

    async def test_docs_api_error_returns_error_dict(self):
        # Regression: documents().get() had no try/except, unlike every sibling
        # tool in this file — an invalid doc_id raised instead of returning
        # {"error": ...}.
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=404), content=b'{"error": {"message": "not found"}}'
        )
        ctx = self._ctx(docs_svc)

        result = await _docs_tools["find_in_doc"](doc_id="missing", query="x", ctx=ctx)

        assert "error" in result

    async def test_match_offset_after_astral_character_is_utf16_correct(self):
        # Regression: offsets used to be computed via enumerate() over Python
        # characters (code points). "😀" is 1 Python character but 2 UTF-16
        # units — a match after it must land 1 unit further than naive
        # code-point counting would put it.
        doc, _ = _build_doc_body([["hi 😀 needle\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="needle", ctx=ctx)

        assert len(results) == 1
        # "hi 😀 " is 5 Python chars before "needle" starts, so naive
        # code-point math (the old, buggy behavior) would put start_index at
        # 1 + 5 = 6. "😀" actually costs 2 UTF-16 units instead of 1, so the
        # correct start_index is one further, at 7.
        assert results[0]["start_index"] == 7

    async def test_literal_case_insensitive_by_default(self):
        doc, paragraphs = _build_doc_body([["Hello World\n"], ["another hello here\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="hello", ctx=ctx)

        assert len(results) == 2
        p0_start, p0_text = paragraphs[0]
        p1_start, p1_text = paragraphs[1]
        assert results[0]["start_index"] == p0_start
        assert results[0]["end_index"] == p0_start + len("Hello")
        assert results[0]["matched_text"] == "Hello"
        assert results[0]["context"] == "Hello World"
        assert results[1]["start_index"] == p1_start + p1_text.index("hello")
        assert results[1]["matched_text"] == "hello"

    async def test_case_sensitive_excludes_different_case(self):
        doc, _ = _build_doc_body([["Hello World\n"], ["another hello here\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](
            doc_id="doc1", query="hello", case_sensitive=True, ctx=ctx
        )

        assert len(results) == 1
        assert results[0]["matched_text"] == "hello"

    async def test_no_match_returns_empty_list(self):
        doc, _ = _build_doc_body([["Hello World\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="missing", ctx=ctx)

        assert results == []

    async def test_regex_query(self):
        doc, paragraphs = _build_doc_body(
            [["Contact: ", "test@example.com", " or admin@example.com\n"]]
        )
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](
            doc_id="doc1", query=r"[\w.]+@[\w.]+", regex=True, ctx=ctx
        )

        assert [r["matched_text"] for r in results] == ["test@example.com", "admin@example.com"]
        para_start, para_text = paragraphs[0]
        assert results[0]["start_index"] == para_start + para_text.index("test@example.com")

    async def test_invalid_regex_returns_error(self):
        doc, _ = _build_doc_body([["text\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        result = await _docs_tools["find_in_doc"](
            doc_id="doc1", query="(unclosed", regex=True, ctx=ctx
        )

        assert "error" in result

    async def test_zero_length_regex_match_is_skipped(self):
        doc, _ = _build_doc_body([["hello\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="z*", regex=True, ctx=ctx)

        assert results == []

    async def test_max_results_truncates(self):
        doc, _ = _build_doc_body([["aaaa\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="a", max_results=2, ctx=ctx)

        assert len(results) == 2

    async def test_searches_table_cell_text(self):
        doc = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [
                                                            {
                                                                "startIndex": 5,
                                                                "endIndex": 21,
                                                                "textRun": {
                                                                    "content": "needle in cell\n"
                                                                },
                                                            }
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="needle", ctx=ctx)

        assert len(results) == 1
        assert results[0]["start_index"] == 5
        assert results[0]["matched_text"] == "needle"

    async def test_oversized_result_raises(self, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        doc, _ = _build_doc_body([["needle needle needle\n"]])
        ctx = self._ctx(self._docs_svc(doc))

        with pytest.raises(ValueError, match="safety cap"):
            await _docs_tools["find_in_doc"](doc_id="doc1", query="needle", ctx=ctx)

    async def test_local_path_bypasses_cap_and_writes_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 5)
        doc, _ = _build_doc_body([["needle needle needle\n"]])
        ctx = self._ctx(self._docs_svc(doc))
        dest = tmp_path / "out.json"

        result = await _docs_tools["find_in_doc"](
            doc_id="doc1", query="needle", local_path=str(dest), ctx=ctx
        )

        assert result["local_path"] == str(dest)
        assert result["match_count"] == 3
        written = json.loads(dest.read_text())
        assert len(written) == 3


# ---------------------------------------------------------------------------
# insert_softbreak_paragraph (#332)
# ---------------------------------------------------------------------------


class TestInsertSoftbreakParagraph:
    def _ctx(self, docs_svc=None):
        return _make_ctx(docs_service=docs_svc or MagicMock(), doc_cache=MagicMock())

    async def test_lines_joined_with_soft_break(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "Line one"}, {"text": "Line two"}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        insert_req = body["requests"][0]["insertText"]
        assert insert_req["location"]["index"] == 10
        assert insert_req["text"] == "Line one\vLine two"

    async def test_paragraph_style_set_explicitly_over_whole_span(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=10,
            lines=[{"text": "abc"}, {"text": "de"}],
            named_style_type="HEADING_2",
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_req = body["requests"][1]["updateParagraphStyle"]
        assert style_req["paragraphStyle"]["namedStyleType"] == "HEADING_2"
        assert style_req["fields"] == "namedStyleType"
        # "abc" (3) + soft break (1) + "de" (2) = 6 units
        assert style_req["range"] == {"startIndex": 10, "endIndex": 16}
        assert result["start_index"] == 10
        assert result["end_index"] == 16

    async def test_line_ranges_and_per_line_bold_style(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "Document ID: X", "bold": True}, {"text": "Category: Y"}],
            ctx=ctx,
        )
        # Line 0: [1, 15); soft break at 15; line 1: [16, 27)
        assert result["line_ranges"] == [
            {"start_index": 1, "end_index": 15},
            {"start_index": 16, "end_index": 27},
        ]
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_requests = [r["updateTextStyle"] for r in body["requests"] if "updateTextStyle" in r]
        assert len(style_requests) == 1
        assert style_requests[0]["range"] == {"startIndex": 1, "endIndex": 15}
        assert style_requests[0]["textStyle"] == {"bold": True}
        assert style_requests[0]["fields"] == "bold"

    async def test_link_url_null_clears_link(self):
        # #408: shares _text_style_and_fields with style_doc_range, so a
        # link_url=None line must still send its clearing updateTextStyle
        # request rather than being skipped for having an empty textStyle.
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "no longer linked", "link_url": None}],
            ctx=ctx,
        )
        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        style_requests = [r["updateTextStyle"] for r in body["requests"] if "updateTextStyle" in r]
        assert len(style_requests) == 1
        assert style_requests[0]["fields"] == "link"
        assert "link" not in style_requests[0]["textStyle"]

    async def test_astral_character_advances_offset_by_two_utf16_units(self):
        docs_svc = MagicMock()
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "hi 😀"}, {"text": "next"}],
            ctx=ctx,
        )
        # "hi 😀" is 4 Python chars but 5 UTF-16 units (the emoji is a surrogate
        # pair) -> line 0 spans [1, 6), soft break at 6, line 1 starts at 7.
        assert result["line_ranges"][0] == {"start_index": 1, "end_index": 6}
        assert result["line_ranges"][1]["start_index"] == 7

    async def test_empty_lines_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[], ctx=ctx
        )
        assert "error" in result

    async def test_line_missing_text_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[{"bold": True}], ctx=ctx
        )
        assert "error" in result

    async def test_invalid_named_style_type_returns_error(self):
        ctx = self._ctx()
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1",
            index=1,
            lines=[{"text": "x"}],
            named_style_type="NOT_A_STYLE",
            ctx=ctx,
        )
        assert "error" in result

    async def test_marks_doc_cache_dirty(self):
        docs_svc = MagicMock()
        doc_cache = MagicMock()
        ctx = self._ctx(docs_svc)
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[{"text": "x"}], ctx=ctx
        )
        doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_api_error_returns_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "API error"
        )
        ctx = self._ctx(docs_svc)
        result = await _docs_tools["insert_softbreak_paragraph"](
            doc_id="doc1", index=1, lines=[{"text": "x"}], ctx=ctx
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# insert_local_images (#332)
# ---------------------------------------------------------------------------


class TestInsertLocalImages:
    def _ctx(self, docs_svc=None, drive_svc=None, folder_id=None):
        return _make_ctx(
            docs_service=docs_svc or MagicMock(),
            drive_service=drive_svc or MagicMock(),
            doc_cache=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id=folder_id,
        )

    def _docs_svc(self, doc):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = doc
        return docs_svc

    def _drive_svc(self, file_id="img1", web_content_link="https://drive.google.com/uc?id=img1"):
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": file_id,
            "name": "pic.png",
            "webViewLink": "https://drive.google.com/file/d/x/view",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "anyoneWithLink"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": web_content_link
        }
        return drive_svc

    async def test_empty_images_returns_error(self):
        ctx = self._ctx(folder_id="folder1")
        result = await _docs_tools["insert_local_images"](doc_id="doc1", images=[], ctx=ctx)
        assert "error" in result

    async def test_no_folder_id_returns_error(self):
        ctx = self._ctx()  # no folder_id param, no lc.folder_id default
        result = await _docs_tools["insert_local_images"](
            doc_id="doc1", images=[{"marker": "M", "local_path": "/x.png"}], ctx=ctx
        )
        assert "error" in result

    async def test_missing_local_file_reports_per_image_error(self, tmp_path):
        doc, _ = _build_doc_body([["before\n"], ["MARKER\n"], ["after\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(tmp_path / "missing.png")}],
            ctx=ctx,
        )

        assert len(result["results"]) == 1
        assert "error" in result["results"][0]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_marker_not_found_reports_per_image_error(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["before\n"], ["after\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "NOPE", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "not found" in result["results"][0]["error"]

    async def test_marker_not_unique_reports_per_image_error(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER here\n"], ["MARKER there\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "unique" in result["results"][0]["error"]

    async def test_successful_single_image_places_and_deletes_marker(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        # paragraphs: "before\n" [1,8), "MARKER\n" [8,15), "after\n" [15,21)
        doc, paragraphs = _build_doc_body([["before\n"], ["MARKER\n"], ["after\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc(file_id="img1")
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")
        marker_start = paragraphs[1][0]  # start index of the "MARKER\n" paragraph

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img), "width": 100.0}],
            ctx=ctx,
        )

        assert result["results"] == [
            {
                "marker": "MARKER",
                "local_path": str(img),
                "fileId": "img1",
                "index": marker_start,
                # revoke_sharing defaults to True — the temporary anyone:reader
                # share granted below is revoked again once the image is placed.
                "shared": False,
            }
        ]

        drive_svc.permissions.return_value.create.assert_called_once_with(
            fileId="img1",
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
            fields="id",
        )
        drive_svc.permissions.return_value.delete.assert_called_once_with(
            fileId="img1",
            permissionId="anyoneWithLink",
            supportsAllDrives=True,
        )

        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        image_req = body["requests"][0]["insertInlineImage"]
        assert image_req["location"]["index"] == marker_start
        assert image_req["uri"] == "https://drive.google.com/uc?id=img1"
        assert image_req["objectSize"]["width"] == {"magnitude": 100.0, "unit": "PT"}
        delete_req = body["requests"][1]["deleteContentRange"]
        assert delete_req["range"] == {
            "startIndex": marker_start + 1,
            "endIndex": marker_start + 1 + len("MARKER"),
        }

    async def test_multiple_images_processed_highest_marker_first(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, paragraphs = _build_doc_body([["ONE\n"], ["TWO\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "ONE", "local_path": str(img)},
                {"marker": "TWO", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        indices = [
            r["insertInlineImage"]["location"]["index"]
            for r in body["requests"]
            if "insertInlineImage" in r
        ]
        assert indices == sorted(indices, reverse=True)

    async def test_upload_failure_reports_per_image_error_and_skips_doc_edit(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_sharing_failure_reports_per_image_error_and_skips_doc_edit(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = Exception(
            "share failed"
        )
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_marks_caches_dirty_on_success(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        drive_svc = self._drive_svc()
        doc_cache = MagicMock()
        drive_folder_cache = MagicMock()
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=drive_svc, folder_id="folder1")
        ctx.request_context.lifespan_context.doc_cache = doc_cache
        ctx.request_context.lifespan_context.drive_folder_cache = drive_folder_cache

        await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        doc_cache.mark_dirty.assert_called_once_with("doc1")
        drive_folder_cache.mark_dirty.assert_called_once_with("folder1")

    async def test_docs_get_error_returns_top_level_error(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = Exception(
            "not found"
        )
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": "/x.png"}],
            ctx=ctx,
        )

        assert "error" in result

    async def test_substring_marker_not_present_is_not_falsely_matched(self, tmp_path):
        # Regression: plain substring search would match "IMG1" inside "IMG10"
        # even though "IMG1" never appears as its own marker in the document.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["IMG10\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "IMG1", "local_path": str(img)}],
            ctx=ctx,
        )

        assert "error" in result["results"][0]
        assert "not found" in result["results"][0]["error"]
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_substring_markers_both_present_resolve_to_correct_positions(self, tmp_path):
        # Regression: requesting both "IMG1" and "IMG10" where each appears exactly
        # once (in separate paragraphs) must not report a false "occurs twice" for
        # either — longest-first matching must not let "IMG10" ever get counted as
        # an extra occurrence of "IMG1".
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, paragraphs = _build_doc_body([["IMG1 here\n"], ["IMG10 there\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "IMG1", "local_path": str(img)},
                {"marker": "IMG10", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        assert all("error" not in r for r in result["results"])
        assert result["results"][0]["index"] == paragraphs[0][0]
        assert result["results"][1]["index"] == paragraphs[1][0]

    async def test_marker_with_astral_character_deletes_correct_utf16_span(self, tmp_path):
        # Regression: marker_len must be counted in UTF-16 units, not Python code
        # points — "😀" is 1 Python char but 2 UTF-16 units, so a naive len(marker)
        # would leave the deleteContentRange one unit short, stranding a character.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, paragraphs = _build_doc_body([["before 😀MARK after\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")
        para_start, para_text = paragraphs[0]
        marker = "😀MARK"
        marker_start = para_start + para_text.index(marker)
        # "😀" costs 2 UTF-16 units + "MARK" costs 4 -> 6 total, not len(marker) == 5.
        expected_end = marker_start + 1 + 6

        await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": marker, "local_path": str(img)}],
            ctx=ctx,
        )

        body = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]
        delete_req = next(
            r["deleteContentRange"] for r in body["requests"] if "deleteContentRange" in r
        )
        assert delete_req["range"]["endIndex"] == expected_end

    async def test_failed_batchupdate_entry_has_error_but_no_fileid(self, tmp_path):
        # Regression: the doc-edit-failure handler used to reuse the same entry
        # dict that already carried "fileId" from a successful upload, leaving
        # both fileId and error set — contradicting the documented either/or contract.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["MARKER\n"]])
        docs_svc = self._docs_svc(doc)
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = Exception(
            "batchUpdate failed"
        )
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[{"marker": "MARKER", "local_path": str(img)}],
            ctx=ctx,
        )

        entry = result["results"][0]
        assert "error" in entry
        assert "fileId" not in entry

    async def test_results_order_matches_images_input_order_not_doc_position_order(self, tmp_path):
        # Regression: successes used to be appended in descending-document-position
        # order (used internally for batchUpdate construction) while failures were
        # appended in input order, so results didn't line up with the images argument
        # whenever a caller listed markers in an order different from their document
        # position. Here "TWO" (input index 0) sits *after* "ONE" (input index 1) in
        # the document, so document-position order would put ONE first — but the
        # correct output order is input order: TWO's outcome, then ONE's.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["ONE\n"], ["TWO\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "TWO", "local_path": str(img)},
                {"marker": "ONE", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        assert [r["marker"] for r in result["results"]] == ["TWO", "ONE"]

    async def test_results_order_preserved_with_mixed_success_and_early_failure(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        doc, _ = _build_doc_body([["ONE\n"]])
        docs_svc = self._docs_svc(doc)
        ctx = self._ctx(docs_svc=docs_svc, drive_svc=self._drive_svc(), folder_id="folder1")

        result = await _docs_tools["insert_local_images"](
            doc_id="doc1",
            images=[
                {"marker": "MISSING", "local_path": str(img)},
                {"marker": "ONE", "local_path": str(img)},
            ],
            ctx=ctx,
        )

        assert [r["marker"] for r in result["results"]] == ["MISSING", "ONE"]
        assert "error" in result["results"][0]
        assert "error" not in result["results"][1]
