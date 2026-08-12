"""Tests for docs content tools and HTML/Markdown pipeline."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from PIL import Image as PILImage

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.docs import content as content_module
from mcp_gee_sweet.tools.docs import images as images_module
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
    _has_pending_anchor_links,
    _md_to_html,
    _resolve_heading_anchors,
    _resolve_image_source,
    _to_doc_requests,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast


def _make_png_bytes(width: int, height: int) -> bytes:
    """A real (but minimal-content) PNG at the given pixel dimensions, for #400's
    inline-image size-limit tests — Pillow needs to actually decode a header to read
    dimensions, so a fake byte string won't do."""
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color="red").save(buf, format="PNG")
    return buf.getvalue()


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

    async def test_pre_resumed_after_table_drops_whitespace_only_trailing_flush(self):
        # #443: a <pre> interrupted by a nested table, then resumed, whose
        # trailing flush is whitespace-only, is markup-formatting noise (the
        # same fresh-vs-resumed distinction _emit_block_node already draws
        # for <p>/<li>/headings, #401/#402) — not a spurious visible-space
        # paragraph.
        nodes = html_to_ast("<pre>code<table><tr><td>cell</td></tr></table>   </pre>")
        assert len(nodes) == 2
        assert isinstance(nodes[0], Paragraph)
        assert "".join(r.text for r in nodes[0].runs) == "code"
        assert isinstance(nodes[1], Table)

    async def test_pre_resumed_after_table_keeps_real_trailing_text(self):
        nodes = html_to_ast("<pre>code<table><tr><td>cell</td></tr></table>more code</pre>")
        assert len(nodes) == 3
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Table)
        assert isinstance(nodes[2], Paragraph)
        assert "".join(r.text for r in nodes[2].runs) == "more code"

    async def test_fresh_pre_whitespace_only_content_is_preserved(self):
        # Unlike the resumed case above, a *fresh* <pre> (never interrupted)
        # keeps its whitespace unconditionally — every character inside
        # <pre> is normally significant.
        nodes = html_to_ast("<pre>   </pre>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)
        assert "".join(r.text for r in nodes[0].runs) == "   "

    async def test_pre_resumed_after_table_keeps_boundary_when_content_was_dropped(self):
        # QA round 1 (PR #515): a resumed <pre> whose trailing flush is
        # whitespace-only *and* had genuinely dropped unsupported content
        # (e.g. a bare <hr> inside <pre>) must still get a boundary node —
        # the same preserve_if_empty guarantee _emit_block_node gives every
        # other block type — rather than vanishing exactly like the pure-
        # noise case above and leaving no trace that content was dropped.
        nodes = html_to_ast("<pre>code<table><tr><td>cell</td></tr></table> <hr></pre>")
        assert len(nodes) == 3
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Table)
        assert isinstance(nodes[2], Paragraph)
        assert "".join(r.text for r in nodes[2].runs) == " "

    async def test_pre_resumed_after_table_keeps_empty_boundary_when_content_was_dropped(self):
        # Same as above but with zero surviving whitespace at all (nothing
        # between the closing </table> and the dropped <hr>) — the boundary
        # node must still be emitted, with empty runs, matching
        # _emit_block_node's own runs=[] preserve_if_empty path (#401).
        nodes = html_to_ast("<pre>code<table><tr><td>cell</td></tr></table><hr></pre>")
        assert len(nodes) == 3
        assert isinstance(nodes[0], Paragraph)
        assert isinstance(nodes[1], Table)
        assert isinstance(nodes[2], Paragraph)
        assert nodes[2].runs == []


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


class TestBlockquote:
    """Blockquote representation via a flat blockquote_depth field (#476), mirroring
    how BulletItem.depth encodes list nesting rather than a wrapper node."""

    async def test_simple_blockquote_paragraph_depth_1(self):
        nodes = html_to_ast("<blockquote><p>A quoted line</p></blockquote><p>after</p>")
        assert [n.blockquote_depth for n in nodes] == [1, 0]
        assert "".join(r.text for r in nodes[0].runs) == "A quoted line"

    async def test_non_blockquote_nodes_default_to_depth_0(self):
        nodes = html_to_ast("<p>plain</p>")
        assert nodes[0].blockquote_depth == 0

    async def test_nested_blockquote_increments_depth(self):
        md = "> outer\n> > nested\n\nafter\n"
        html = _md_to_html(md)
        nodes = html_to_ast(html)
        assert [n.blockquote_depth for n in nodes] == [1, 2, 0]

    async def test_blockquote_interrupting_open_li_isolates_depth(self):
        # Text inside the <li> but outside the <blockquote> must stay at depth 0;
        # only the blockquote's own content is tagged — mirroring how a nested
        # <ul> inside an <li> flushes the parent's own text separately (#335).
        html = "<ul><li>Some intro<blockquote><p>quoted</p></blockquote>trailing</li></ul>"
        nodes = html_to_ast(html)
        assert [n.blockquote_depth for n in nodes] == [0, 1, 0]
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert "".join(r.text for r in bullets[0].runs) == "Some intro"
        assert "".join(r.text for r in bullets[1].runs) == "trailing"

    async def test_blockquote_wrapping_list_tags_bullet_items(self):
        html = "<blockquote><ul><li>a</li><li>b</li></ul></blockquote>"
        bullets = [n for n in html_to_ast(html) if isinstance(n, BulletItem)]
        assert [b.blockquote_depth for b in bullets] == [1, 1]

    async def test_blockquote_wrapping_heading(self):
        nodes = html_to_ast("<blockquote><h2>Quoted Heading</h2></blockquote>")
        heading = next(n for n in nodes if isinstance(n, Heading))
        assert heading.blockquote_depth == 1

    async def test_markdown_blockquote_via_gt_syntax(self):
        html = _md_to_html("> quoted text\n")
        nodes = html_to_ast(html)
        assert nodes[0].blockquote_depth == 1
        assert "".join(r.text for r in nodes[0].runs) == "quoted text"

    async def test_depth_resets_after_blockquote_closes(self):
        html = (
            "<blockquote><p>in</p></blockquote><p>out</p><blockquote><p>in again</p></blockquote>"
        )
        nodes = html_to_ast(html)
        assert [n.blockquote_depth for n in nodes] == [1, 0, 1]

    # QA round 1 (PR #546): three Paragraph-construction sites other than
    # _emit_block_node's own dispatch — bare <hr>, bare <img>, and <pre>'s own
    # close handler — built their Paragraph node directly without passing
    # blockquote_depth=self._blockquote_depth, so each silently defaulted to 0
    # when it was the sole content of a <blockquote>.

    async def test_bare_hr_inside_blockquote_gets_depth(self):
        nodes = html_to_ast("<blockquote><hr></blockquote>")
        assert nodes[0].blockquote_depth == 1

    async def test_bare_img_inside_blockquote_gets_depth(self):
        nodes = html_to_ast('<blockquote><img src="x.png"></blockquote>')
        assert nodes[0].blockquote_depth == 1

    async def test_pre_inside_blockquote_gets_depth(self):
        nodes = html_to_ast("<blockquote><pre>code here</pre></blockquote>")
        assert nodes[0].blockquote_depth == 1

    # QA round 1 (PR #546): a <blockquote> that opens with nothing outer to
    # interrupt pushes no frame onto _block_stack (see _interrupt_open_block).
    # If its own inner content is malformed (missing its own close tag),
    # _resume_interrupted_block("blockquote") used to bail out before ever
    # flushing that still-open inner block, since its flush-before-resume step
    # was only reachable when a frame existed. The still-open block then
    # absorbed the following sibling text and reported blockquote_depth=0.
    async def test_malformed_blockquote_at_top_level_still_splits_and_tags_depth(self):
        nodes = html_to_ast("<blockquote><p>text</blockquote>after")
        assert [(n.blockquote_depth, "".join(r.text for r in n.runs)) for n in nodes] == [
            (1, "text"),
            (0, "after"),
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

    async def test_frameless_top_level_wrapper_still_flushes_implicit_paragraph(self):
        # #476 QA round 1: the #478 fix above only reached its flush-before-
        # resume step from inside the "a frame exists on _block_stack" branch.
        # A wrapper construct that opens with *nothing* outer to interrupt (so
        # _interrupt_open_block pushes no frame at all) whose own bare
        # top-level text (implicit paragraph, #343) is still open when the
        # wrapper's own close tag arrives fell through the earlier
        # `if not self._block_stack: return` guard without ever flushing —
        # confirmed as a pre-existing gap, not something new to blockquote
        # (the same shape reproduces for <ol>/<table>/<pre> at top level too).
        nodes = html_to_ast("<ul>text</ul>after")
        texts = ["".join(r.text for r in n.runs) for n in nodes]
        assert texts == ["text", "after"]


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
        drive_svc.files.return_value.get.return_value.execute.return_value = {"name": "file1"}
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

    async def test_oversized_drive_image_fails_fast_without_sharing(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.png",
            "imageMediaMetadata": {"width": 14609, "height": 2434},
        }
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert "error" in result
        assert "35.6 megapixels" in result["error"]
        assert "auto_downscale=True" in result["error"]
        drive_svc.permissions.assert_not_called()

    async def test_oversized_by_bytes_drive_image_fails_fast_without_sharing(self):
        # #562: an image under the megapixel limit but over Google's byte-size limit,
        # caught via Drive's own reported "size" — no download needed.
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.png",
            "imageMediaMetadata": {"width": 100, "height": 100},
            "size": str(images_module.MAX_INLINE_IMAGE_BYTES + 1),
        }
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert "error" in result
        assert "50MB" in result["error"]
        drive_svc.permissions.assert_not_called()

    async def test_undersized_drive_image_still_shares_normally(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "small.png",
            "imageMediaMetadata": {"width": 100, "height": 100},
            "webContentLink": "https://drive.google.com/uc?id=file1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert result == {
            "uri": "https://drive.google.com/uc?id=file1",
            "file_id": "file1",
            "permission_id": "perm1",
        }

    async def test_oversized_drive_image_auto_downscale_creates_resized_copy(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.side_effect = [
            {
                "name": "big.png",
                "parents": ["folder1"],
                "imageMediaMetadata": {"width": 6000, "height": 6000},
            },
            {"webContentLink": "https://drive.google.com/uc?id=resized1"},
        ]
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "resized1"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm-resized"
        }

        png_bytes = _make_png_bytes(6000, 6000)

        class _FakeDownloader:
            def __init__(self, fh, request):
                fh.write(png_bytes)

            def next_chunk(self):
                return None, True

        with (
            patch("mcp_gee_sweet.tools.docs.images.MediaIoBaseDownload", _FakeDownloader),
            patch("mcp_gee_sweet.tools.docs.images.thread_http"),
        ):
            result = await _resolve_image_source(
                drive_svc, "drive:file1", "folder1", auto_downscale=True
            )

        assert result == {
            "uri": "https://drive.google.com/uc?id=resized1",
            "file_id": "resized1",
            "permission_id": "perm-resized",
        }
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["name"] == "big.png (resized)"
        assert create_kwargs["body"]["parents"] == ["folder1"]

    async def test_oversized_local_image_fails_fast_without_upload(self, tmp_path):
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(14609, 2434))
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, str(img), "folder1")
        assert "error" in result
        assert "35.6 megapixels" in result["error"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_oversized_by_bytes_local_image_fails_fast_without_upload(
        self, tmp_path, monkeypatch
    ):
        # #562: an image under the megapixel limit but over Google's byte-size limit.
        # A patched threshold stands in for Google's real 50MB ceiling so the fixture
        # can stay a small, ordinary PNG.
        monkeypatch.setattr(images_module, "MAX_INLINE_IMAGE_BYTES", 10)
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(100, 100))
        drive_svc = MagicMock()
        result = await _resolve_image_source(drive_svc, str(img), "folder1")
        assert "error" in result
        assert "50MB" in result["error"]
        drive_svc.files.return_value.create.assert_not_called()

    async def test_oversized_local_image_auto_downscale_uploads_resized_bytes(self, tmp_path):
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(6000, 6000))
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {"id": "resized2"}
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm-resized2"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=resized2"
        }
        result = await _resolve_image_source(drive_svc, str(img), "folder1", auto_downscale=True)
        assert result == {
            "uri": "https://drive.google.com/uc?id=resized2",
            "file_id": "resized2",
            "permission_id": "perm-resized2",
        }
        create_kwargs = drive_svc.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"]["name"] == "big.png"


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

    async def test_oversized_uri_image_error_is_rewritten(self):
        # A bare http(s) image source can't be pre-validated (#400's scope boundary
        # — see docs/decisions/decision-pillow-image-dependency.md): this is its only
        # chance to learn the size-limit cause, via the same retry-and-rewrite path
        # test_one_bad_image_url_does_not_fail_the_whole_document exercises above.
        drive_svc, docs_svc = self._make_services()
        uri = "https://example.com/huge.png"

        def batchupdate_side_effect(documentId, body):
            m = MagicMock()
            bad_index = next(
                (
                    i
                    for i, r in enumerate(body["requests"])
                    if r.get("insertInlineImage", {}).get("uri") == uri
                ),
                None,
            )
            if bad_index is None:
                # A batchUpdate call unrelated to the image request (e.g. bullet
                # handling for an unrelated part of the content pipeline) —
                # succeed normally, same as the real API would.
                m.execute.return_value = {}
                return m
            resp = MagicMock()
            resp.status = 400
            message = (
                f"Invalid requests[{bad_index}].insertInlineImage: The provided image is too large."
            )
            content = json.dumps({"error": {"code": 400, "message": message}}).encode()
            if not batchupdate_side_effect.called:
                batchupdate_side_effect.called = True
                m.execute.side_effect = HttpError(
                    resp=resp,
                    content=content,
                    uri="https://docs.googleapis.com/v1/documents/x:batchUpdate",
                )
            else:
                m.execute.return_value = {}
            return m

        batchupdate_side_effect.called = False
        docs_svc.documents.return_value.batchUpdate.side_effect = batchupdate_side_effect
        ctx = self._ctx(drive_svc, docs_svc)

        result = await _docs_tools["create_doc"](
            title="Doc", content=f"![Huge]({uri})", content_format="markdown", ctx=ctx
        )

        error = result["images"][0]["error"]
        assert "25 megapixels" in error
        assert "auto_downscale" not in error  # uri source can't use it
        assert docs_svc.documents.return_value.batchUpdate.call_count == 2

    async def test_duplicate_image_uri_retry_failure_attributed_to_correct_image(self):
        # PR #502 review round 1, finding #2: two images resolving to the
        # *identical* URI (the same picture referenced twice) used to
        # misattribute a retry failure via a uri-keyed lookup (last
        # registration wins) — a failure on the first (lowest-position)
        # occurrence's request could get reported against the second
        # (successfully embedded) image's outcome entry instead. Fixed via
        # id(img)-keyed tracking that survives the placeholder-uri swap
        # ast_to_requests needs internally.
        drive_svc, docs_svc = self._make_services()
        same_uri = "https://example.com/same.png"
        content = f"![First]({same_uri})\n\n![Second]({same_uri})"
        first_call_requests = []

        def batchupdate_side_effect(documentId, body):
            nonlocal first_call_requests
            m = MagicMock()
            if not first_call_requests:
                first_call_requests = body["requests"]
                image_reqs = [r for r in body["requests"] if "insertInlineImage" in r]
                assert len(image_reqs) == 2
                # Fail the lowest-position (first-in-document) image request.
                first_image_req = min(
                    image_reqs, key=lambda r: r["insertInlineImage"]["location"]["index"]
                )
                bad_index = body["requests"].index(first_image_req)
                m.execute.side_effect = self._insert_image_http_error(bad_index)
            else:
                m.execute.return_value = {}
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = batchupdate_side_effect
        ctx = self._ctx(drive_svc, docs_svc)

        result = await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )

        outcomes = result["images"]
        assert len(outcomes) == 2
        # The first (document-order) entry is the one whose request was failed
        # above — it must carry the error, and the second (genuinely
        # successful) entry must not, despite sharing the identical src/uri.
        assert "error" in outcomes[0]
        assert "error" not in outcomes[1]


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


class TestUpdateDocFromFile:
    """update_doc_from_file (#341) combines create_doc_from_file's server-side file
    reading (extension inference, error handling) with write_doc_content's in-place
    clear+replace mechanism, via the shared _replace_doc_content helper — so it never
    mints a duplicate Doc the way re-running create_doc_from_file would."""

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
            folder_id=None,
        )

    def _batchupdate_calls(self, docs_svc):
        return [
            c.kwargs["body"]["requests"]
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]

    async def test_md_file_replaces_content_in_place(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("# Hello\n\nParagraph text.\n")
        drive_svc, docs_svc = self._make_services(end_index=50)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(md_file), ctx=ctx
        )
        assert result["docId"] == "doc1"
        assert "error" not in result
        # No new Doc created — only the existing one's content was touched.
        drive_svc.files.return_value.create.assert_not_called()
        docs_svc.documents.return_value.get.assert_called_once_with(documentId="doc1")

    async def test_md_file_heading_emitted(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Section\n")
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["update_doc_from_file"](doc_id="doc1", local_path=str(md_file), ctx=ctx)
        calls = self._batchupdate_calls(docs_svc)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in calls[-1]
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    async def test_html_file_accepted(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<h2>Hello</h2>")
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(html_file), ctx=ctx
        )
        assert "docId" in result
        assert "error" not in result

    async def test_content_format_override_wins_over_extension(self, tmp_path):
        # A .txt file has no inferred format, but an explicit content_format still works.
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("# Heading\n")
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(txt_file), content_format="markdown", ctx=ctx
        )
        assert "error" not in result
        calls = self._batchupdate_calls(docs_svc)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in calls[-1]
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    async def test_file_not_found_returns_error(self, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(tmp_path / "missing.md"), ctx=ctx
        )
        assert "error" in result
        assert "not found" in result["error"].lower()
        docs_svc.documents.return_value.get.assert_not_called()

    async def test_unsupported_extension_returns_error(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("plain text")
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(txt_file), ctx=ctx
        )
        assert "error" in result
        assert ".txt" in result["error"]
        docs_svc.documents.return_value.get.assert_not_called()

    async def test_clears_trailing_mark_style_before_deleting_in_its_own_batch(self, tmp_path):
        # Same clear-then-insert mechanism as write_doc_content (#255) — verified here
        # too since it's now shared via _replace_doc_content.
        md_file = tmp_path / "notes.md"
        md_file.write_text("New content\n")
        drive_svc, docs_svc = self._make_services(end_index=50)
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["update_doc_from_file"](doc_id="doc1", local_path=str(md_file), ctx=ctx)
        calls = self._batchupdate_calls(docs_svc)

        clear_requests = calls[0]
        assert len(clear_requests) == 2
        assert clear_requests[0]["updateTextStyle"]["range"] == {
            "startIndex": 49,
            "endIndex": 50,
        }
        assert clear_requests[1]["deleteContentRange"]["range"] == {
            "startIndex": 1,
            "endIndex": 49,
        }
        content_requests = calls[1]
        assert any("insertText" in r for r in content_requests)

    async def test_empty_doc_skips_clear_requests(self, tmp_path):
        md_file = tmp_path / "notes.md"
        md_file.write_text("New content\n")
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        await _docs_tools["update_doc_from_file"](doc_id="doc1", local_path=str(md_file), ctx=ctx)
        calls = self._batchupdate_calls(docs_svc)
        assert len(calls) == 1
        assert not any("deleteContentRange" in r for r in calls[0])


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


class TestGetDocStructureBullet:
    """#334: get_doc_structure surfaces each paragraph's list membership/nesting."""

    def _ctx(self, docs_svc):
        return _make_ctx(docs_service=docs_svc)

    def _doc(self, bullet=None):
        para = {
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "elements": [{"textRun": {"content": "Item\n", "textStyle": {}}}],
        }
        if bullet is not None:
            para["bullet"] = bullet
        return {
            "documentId": "doc1",
            "title": "Doc",
            "body": {"content": [{"startIndex": 1, "endIndex": 10, "paragraph": para}]},
        }

    async def test_non_list_paragraph_has_null_bullet(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = self._doc()
        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))
        assert result["elements"][0]["bullet"] is None

    async def test_list_paragraph_reports_bullet_and_nesting_level(self):
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = self._doc(
            bullet={"listId": "list1", "nestingLevel": 2}
        )
        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))
        assert result["elements"][0]["bullet"] == {"listId": "list1", "nestingLevel": 2}

    async def test_top_level_bullet_normalizes_missing_nesting_level_to_zero(self):
        # The Docs API omits nestingLevel entirely for a top-level (depth 0)
        # list item rather than sending an explicit 0 — get_doc_structure
        # normalizes so every list paragraph reports a level.
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = self._doc(
            bullet={"listId": "list1"}
        )
        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))
        assert result["elements"][0]["bullet"] == {"listId": "list1", "nestingLevel": 0}


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
