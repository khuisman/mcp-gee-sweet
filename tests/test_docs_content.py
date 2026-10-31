"""Tests for docs content tools and HTML/Markdown pipeline."""

import inspect
import io
import json
import threading
from functools import partial
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, call, patch

import anyio
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
    _failed_insert_image_message,
    _failed_insert_image_request_index,
    _has_pending_anchor_links,
    _local_image_path,
    _md_to_html,
    _positional_insert_tail_start,
    _resolve_heading_anchors,
    _resolve_image_source,
    _to_doc_requests,
)
from mcp_gee_sweet.tools.docs.emitter import (
    ast_to_requests,
    extract_images,
    image_fallback_requests,
    image_fallback_text,
)
from mcp_gee_sweet.tools.docs.html_parser import html_to_ast
from mcp_gee_sweet.tools.drive import _USER_QUOTA_ERROR
from tests.conftest import IS_ROOT

from .fakes import as_service_account


def _make_png_bytes(width: int, height: int) -> bytes:
    """A real (but minimal-content) PNG at the given pixel dimensions, for #400's
    inline-image size-limit tests — Pillow needs to actually decode a header to read
    dimensions, so a fake byte string won't do."""
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color="red").save(buf, format="PNG")
    return buf.getvalue()


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False):
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
        drive_svc = as_service_account(MagicMock())
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        docs_svc = MagicMock()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "This service account has no My Drive storage" in result["error"]
        assert "server://auth-status" in result["error"]

    async def test_quota_exceeded_for_user_identity_says_storage_is_full(self):
        # A user whose own Drive is full must not be told to switch to OAuth (#1009).
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = self._ctx(drive_svc, MagicMock())
        result = await _docs_tools["create_doc"](title="Test", content="<p>hi</p>", ctx=ctx)
        assert result == {"error": _USER_QUOTA_ERROR}

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
        assert [type(n).__name__ for n in nodes] == ["BulletItem", "Paragraph", "Paragraph"]
        assert "".join(r.text for r in nodes[0].runs) == "Some intro"
        # Both the quote and the text after it are content of the one item (#1094).
        assert [n.list_depth for n in nodes[1:]] == [0, 0]
        assert "".join(r.text for r in nodes[2].runs) == "trailing"

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
        nodes = html_to_ast(html)
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        texts_depths = [("".join(r.text for r in b.runs), b.depth) for b in bullets]
        assert texts_depths == [("Parent", 0), ("Child", 1)]
        # The trailing text is more of Parent's content, not a new item (#1094).
        assert isinstance(nodes[2], Paragraph)
        assert "".join(r.text for r in nodes[2].runs) == "trailing text"
        assert nodes[2].list_depth == 0

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

    async def test_implicit_paragraph_open_resets_unsupported_content_flag(self):
        # #417: every other block-open path (pre, _BLOCK_TAGS, resume) resets
        # self._block_had_unsupported_content — the implicit top-level
        # paragraph opened for bare text (#343) didn't, leaving it stale from
        # whatever block closed just before. A dropped <img> (no src) inside
        # the preceding <p> sets the flag True; it must not still read True
        # once the following bare text opens its own implicit paragraph.
        from mcp_gee_sweet.tools.docs.html_parser import _AstParser

        parser = _AstParser()
        parser.feed("<p>Real text<img></p>Bare text")
        assert parser._block_had_unsupported_content is False

    async def test_implicit_paragraph_open_resets_resumed_flag(self):
        # #417 round 2: the same implicit-paragraph open path fixed above
        # also left self._block_resumed stale — a <table> interrupting an
        # open <p> and then closing sets self._block_resumed = True via
        # _resume_interrupted_block; the following </p> close doesn't touch
        # the flag at all, so it's still True by the time bare top-level
        # text opens its own implicit paragraph right after. Confirmed
        # live against the pre-round-2 code that this reproduces (True);
        # the shared _open_block() reset now clears it to False here too.
        from mcp_gee_sweet.tools.docs.html_parser import _AstParser

        parser = _AstParser()
        parser.feed("<p>Before<table><tr><td>cell</td></tr></table>After</p>Bare text")
        assert parser._block_resumed is False

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

    async def test_bare_hyphen_as_first_list_line_is_an_empty_item(self):
        """CommonMark allows an empty list item (#1075). Under Python-Markdown (#692) a
        bare '-' first line turned the whole list into one paragraph of text."""
        html = _md_to_html("-\n- item two\n- item three\n")
        assert html == "<ul>\n<li></li>\n<li>item two</li>\n<li>item three</li>\n</ul>\n"

    async def test_bare_hyphen_mid_list_is_an_empty_item_not_a_setext_heading(self):
        """Python-Markdown read a bare '-' after a list line as a setext H2 underline
        (#692). CommonMark gives a setext underline no power over a list item's text."""
        html = _md_to_html("- item one\n-\n- item three\n")
        assert "<h2>" not in html
        assert html == "<ul>\n<li>item one</li>\n<li></li>\n<li>item three</li>\n</ul>\n"

    async def test_bare_hyphen_workaround_nbsp_produces_empty_list_item(self):
        """The documented workaround (docs/known-limitations.md, #692): replacing
        the offending bare '-' line itself with a '- ' + non-breaking-space marker
        parses as a genuine empty list item in both manifestations above, instead
        of collapsing to a paragraph or heading."""
        nbsp = chr(0xA0)  # non-breaking space; ruff RUF001 flags it if written literally

        # First-line manifestation, fixed:
        html = _md_to_html(f"- {nbsp}\n- item two\n- item three\n")
        assert "<ul>" in html
        assert html.count("<li>") == 3

        # Mid-list / setext-heading manifestation, fixed:
        html = _md_to_html(f"- item one\n- {nbsp}\n- item three\n")
        assert "<h2>" not in html
        assert html.count("<li>") == 3

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
        # CommonMark escapes every ASCII punctuation character, $ included. Python-Markdown
        # didn't, and needed its own extension for it (issue #213).
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
        assert html == "<p>See https://example.com here</p>\n"

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

    async def test_markdown_multiline_fenced_code_uses_soft_breaks_not_newlines(self):
        # #719: the Docs API treats every "\n" in inserted text as a new
        # paragraph boundary, so a multi-line fenced code block's *internal*
        # line breaks must be written as "\v" (soft break) instead — this is
        # what keeps the whole block as one Docs paragraph rather than
        # fragmenting it into one NORMAL_TEXT paragraph per line.
        requests, _ = _to_doc_requests("```\nline1\nline2\nline3\n```\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        text = insert["insertText"]["text"]
        assert text == "line1\vline2\vline3\n"

    async def test_markdown_single_line_fenced_code_unaffected(self):
        # No embedded newline to substitute — a single-line fenced block's
        # insertText is unchanged by the #719 fix.
        requests, _ = _to_doc_requests("```\nx = 1\n```\n", "markdown")
        insert = next(r for r in requests if "insertText" in r)
        assert insert["insertText"]["text"] == "x = 1\n"

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

    @pytest.mark.skipif(IS_ROOT, reason="root ignores file permissions")
    async def test_local_path_unreadable_is_clean_read_error_without_upload(self, tmp_path):
        # PR #801 QA round 1: a permission-denied file must fail at the size gate
        # with a clean read error, not reach the upload.
        img = tmp_path / "locked.png"
        img.write_bytes(b"fake")
        img.chmod(0)
        drive_svc = MagicMock()
        try:
            result = await _resolve_image_source(drive_svc, str(img), "folder1")
        finally:
            img.chmod(0o644)
        assert result["error"].startswith("failed to read local file:")
        drive_svc.files.return_value.create.assert_not_called()

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
            "webContentLink": "https://drive.google.com/uc?id=uploaded1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm2"
        }
        result = await _resolve_image_source(drive_svc, str(img), "folder1")
        assert result == {
            "uri": "https://drive.google.com/uc?id=uploaded1",
            "file_id": "uploaded1",
            "permission_id": "perm2",
            "created_in": "folder1",
        }
        # #511: two Drive calls (create, share), no follow-up files().get().
        drive_svc.files.return_value.get.assert_not_called()

    async def test_sharing_failure_is_error(self, tmp_path):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "file1",
            "webContentLink": "https://drive.google.com/uc?id=file1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = RuntimeError(
            "boom"
        )
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert "error" in result
        assert "boom" in result["error"]
        # A "drive:" source is the caller's own pre-existing file — this call
        # created no orphan, so file_id must NOT be surfaced in a failed-image
        # outcome (a caller with orphan-reclaim logic could delete it) — PR #652
        # QA round 1, finding 2. Contrast test_local_upload_sharing_failure_*.
        assert "file_id" not in result

    async def test_local_upload_sharing_failure_returns_orphan_file_id(self, tmp_path):
        # Distinct from the drive:-reference case above: here the file was freshly
        # created by this call, so losing file_id on a sharing failure would mean
        # losing all record of a real, newly-created Drive file (#649).
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "uploaded1",
            "name": "pic.png",
            "webViewLink": "https://drive.google.com/file/d/uploaded1/view",
            "webContentLink": "https://drive.google.com/uc?id=uploaded1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = RuntimeError(
            "boom"
        )
        result = await _resolve_image_source(drive_svc, str(img), "folder1")
        assert "error" in result
        assert "boom" in result["error"]
        assert result["file_id"] == "uploaded1"

    async def test_missing_web_content_link_is_error(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {}
        result = await _resolve_image_source(drive_svc, "drive:file1", "folder1")
        assert "error" in result
        assert "webContentLink" in result["error"]
        # "drive:" source — no orphan created by this call, so no file_id (PR #652
        # QA round 1, finding 2).
        assert "file_id" not in result
        # #511: nothing can embed a file with no link, so it's never shared.
        drive_svc.permissions.return_value.create.assert_not_called()

    async def test_local_upload_missing_web_content_link_returns_orphan_file_id(self, tmp_path):
        # The local-upload counterpart to the drive: case above: the file was
        # freshly uploaded, so a missing webContentLink still leaves a real orphan
        # whose id must be surfaced (#649). Since #511 it fails before sharing.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "uploaded1",
            "name": "pic.png",
            "webViewLink": "https://drive.google.com/file/d/uploaded1/view",
        }
        result = await _resolve_image_source(drive_svc, str(img), "folder1")
        assert "error" in result
        assert "webContentLink" in result["error"]
        assert result["file_id"] == "uploaded1"
        drive_svc.permissions.return_value.create.assert_not_called()

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
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.png",
            "parents": ["folder1"],
            "imageMediaMetadata": {"width": 6000, "height": 6000},
        }
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "resized1",
            "webContentLink": "https://drive.google.com/uc?id=resized1",
        }
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
            "created_in": "folder1",
            "downscaled": True,
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
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "resized2",
            "webContentLink": "https://drive.google.com/uc?id=resized2",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm-resized2"
        }
        result = await _resolve_image_source(drive_svc, str(img), "folder1", auto_downscale=True)
        assert result == {
            "uri": "https://drive.google.com/uc?id=resized2",
            "file_id": "resized2",
            "permission_id": "perm-resized2",
            "created_in": "folder1",
            "downscaled": True,
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

    async def test_drive_reference_already_link_shared_is_not_revoked(self):
        # PR #842 QA round 1 F1 (reproduced live): share_file had already made the
        # file anyoneWithLink; embedding it must not remove that link.
        drive_svc, docs_svc = self._make_services()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "anyoneWithLink"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1",
            "permissionIds": ["owner1", "anyoneWithLink"],
        }
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="![Alt](drive:file1)",
            content_format="markdown",
            ctx=ctx,
        )
        assert result["images"] == [
            {"src": "drive:file1", "fileId": "file1", "shared": True, "already_shared": True}
        ]
        drive_svc.permissions.return_value.delete.assert_not_called()

    async def test_auto_downscaled_local_image_reports_downscaled(self, tmp_path):
        # PR #842 QA round 1 F3 (reproduced live): insert_local_images reported
        # downscaled for the same file; create_doc dropped it.
        img = tmp_path / "big.png"
        img.write_bytes(_make_png_bytes(6000, 6000))
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.create.return_value.execute.side_effect = [
            {"id": "doc123", "name": "Test", "parents": ["folder1"], "webViewLink": "x"},
            {"id": "r1", "webContentLink": "https://drive.google.com/uc?id=r1"},
        ]
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        result = await _docs_tools["create_doc"](
            title="Doc",
            content=f"![Big]({img})",
            content_format="markdown",
            auto_downscale=True,
            ctx=ctx,
        )
        assert result["images"] == [
            {"src": str(img), "fileId": "r1", "shared": False, "downscaled": True}
        ]

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

    def _shared_drive_image_services(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1"
        }
        return drive_svc, docs_svc

    def _assert_file1_revoked(self, drive_svc):
        drive_svc.permissions.return_value.delete.assert_called_once_with(
            fileId="file1", permissionId="perm1", supportsAllDrives=True
        )

    async def test_share_revoked_when_content_batch_update_raises(self):
        # #789: a non-image batchUpdate failure used to skip the revoke, leaving
        # the image anyone:reader with nothing reporting it. The failure now
        # comes back as an error result carrying the doc ID and image outcomes.
        drive_svc, docs_svc = self._shared_drive_image_services()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = (
            _other_403_error()
        )
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="Text\n\n![Alt](drive:file1)",
            content_format="markdown",
            ctx=ctx,
        )
        assert result["error"].startswith("doc edit failed: ")
        assert result["docId"] == "doc123"
        assert result["images"] == [{"src": "drive:file1", "fileId": "file1", "shared": False}]
        self._assert_file1_revoked(drive_svc)

    async def test_share_revoked_when_retry_after_image_drop_raises(self):
        # The first attempt names a bad image (a different, https one) and is
        # retried without it; the retry then fails for a non-image reason.
        drive_svc, docs_svc = self._shared_drive_image_services()
        ctx = self._ctx(drive_svc, docs_svc)
        bad_uri = "https://example.com/bad.png"
        content = f"![Bad]({bad_uri}) ![Alt](drive:file1)"
        fail_bad = self._fail_first_matching({bad_uri})
        calls = []

        def side_effect(documentId, body):
            calls.append(body["requests"])
            if len(calls) == 1:
                return fail_bad(documentId, body)
            m = MagicMock()
            m.execute.side_effect = _other_403_error()
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = side_effect
        result = await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )
        assert len(calls) == 2
        assert result["error"].startswith("doc edit failed: ")
        outcomes = {o["src"]: o for o in result["images"]}
        # The image dropped before the failure keeps its own error (#789 F4).
        assert "There was a problem retrieving the image" in outcomes[bad_uri]["error"]
        assert outcomes["drive:file1"] == {"src": "drive:file1", "fileId": "file1", "shared": False}
        self._assert_file1_revoked(drive_svc)

    async def test_share_revoked_when_fill_tables_raises(self):
        drive_svc, docs_svc = self._shared_drive_image_services()
        ctx = self._ctx(drive_svc, docs_svc)
        with patch.object(content_module, "fill_tables", side_effect=RuntimeError("fill boom")):
            result = await _docs_tools["create_doc"](
                title="Doc",
                content="![Alt](drive:file1)\n\n| a | b |\n|---|---|\n| 1 | 2 |",
                content_format="markdown",
                ctx=ctx,
            )
        assert result["error"] == "doc edit failed: fill boom"
        self._assert_file1_revoked(drive_svc)

    async def test_share_revoked_when_anchor_resolution_raises(self):
        drive_svc, docs_svc = self._shared_drive_image_services()
        ctx = self._ctx(drive_svc, docs_svc)
        with patch.object(
            content_module, "_resolve_heading_anchors", side_effect=RuntimeError("anchor boom")
        ):
            result = await _docs_tools["create_doc"](
                title="Doc",
                content="# Intro\n\n![Alt](drive:file1)\n\n[back](#intro)",
                content_format="markdown",
                ctx=ctx,
            )
        assert result["error"] == "doc edit failed: anchor boom"
        self._assert_file1_revoked(drive_svc)

    async def test_failed_edit_without_images_returns_error_result(self):
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = RuntimeError(
            "edit boom"
        )
        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        result = await _docs_tools["create_doc"](title="Doc", content="<p>Text</p>", ctx=ctx)
        assert result == {"error": "doc edit failed: edit boom", "docId": "doc123"}
        # The doc was created, so the folder listing changed either way.
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "folder1"
        )

    async def test_write_doc_content_failed_edit_returns_error_result(self):
        drive_svc, docs_svc = self._shared_drive_image_services()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "body": {"content": [{"endIndex": 2}]}
        }
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = RuntimeError(
            "edit boom"
        )
        ctx = _make_ctx(drive_service=drive_svc, docs_service=docs_svc, doc_cache=MagicMock())
        result = await _docs_tools["write_doc_content"](
            doc_id="doc9", content="![Alt](drive:file1)", content_format="markdown", ctx=ctx
        )
        assert result == {
            "error": "doc edit failed: edit boom",
            "docId": "doc9",
            "images": [{"src": "drive:file1", "fileId": "file1", "shared": False}],
        }
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_called_with("doc9")
        self._assert_file1_revoked(drive_svc)

    async def _create_doc_with_failing_edit(self, drive_svc, docs_svc, content, **kwargs):
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = RuntimeError(
            "edit boom"
        )
        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        with patch.object(images_module, "logger") as mock_logger:
            result = await _docs_tools["create_doc"](
                title="Doc", content=content, content_format="markdown", ctx=ctx, **kwargs
            )
        assert result["error"] == "doc edit failed: edit boom"
        return mock_logger

    async def test_failed_edit_logs_pre_existing_drive_file_apart_from_created(self):
        # PR #877 QA round 1 F2: a drive: source is the caller's own file, never an
        # orphan this call created.
        drive_svc, docs_svc = self._shared_drive_image_services()
        mock_logger = await self._create_doc_with_failing_edit(
            drive_svc, docs_svc, "![Alt](drive:file1)"
        )
        # (doc, created by this call, pre-existing, still link-shared by this call)
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "none", "file1", "none")

    async def test_failed_edit_logs_local_upload_as_created(self, tmp_path):
        img = tmp_path / "pixel.png"
        img.write_bytes(_make_png_bytes(2, 2))
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.create.return_value.execute.side_effect = [
            {"id": "doc123", "name": "Test", "parents": ["folder1"], "webViewLink": "x"},
            {"id": "up1", "webContentLink": "https://drive.google.com/uc?id=up1"},
        ]
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        mock_logger = await self._create_doc_with_failing_edit(
            drive_svc, docs_svc, f"![Pixel]({img})"
        )
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "up1", "none", "none")

    async def test_failed_edit_already_shared_file_not_logged_as_still_shared(self):
        # PR #877 QA round 1 F2: a link that predates the call isn't this call's leak.
        drive_svc, docs_svc = self._make_services()
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "anyoneWithLink"
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webContentLink": "https://drive.google.com/uc?id=file1",
            "permissionIds": ["owner1", "anyoneWithLink"],
        }
        mock_logger = await self._create_doc_with_failing_edit(
            drive_svc, docs_svc, "![Alt](drive:file1)"
        )
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "none", "file1", "none")
        drive_svc.permissions.return_value.delete.assert_not_called()

    async def test_failed_edit_with_revoke_sharing_false_keeps_share_and_logs_it(self):
        drive_svc, docs_svc = self._shared_drive_image_services()
        mock_logger = await self._create_doc_with_failing_edit(
            drive_svc, docs_svc, "![Alt](drive:file1)", revoke_sharing=False
        )
        drive_svc.permissions.return_value.delete.assert_not_called()
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "none", "file1", "file1")

    async def test_failed_edit_without_shared_images_logs_nothing(self):
        drive_svc, docs_svc = self._make_services()
        mock_logger = await self._create_doc_with_failing_edit(
            drive_svc, docs_svc, "![Alt](https://example.com/a.png)"
        )
        mock_logger.warning.assert_not_called()
        drive_svc.permissions.assert_not_called()

    @staticmethod
    def _blocking(started: threading.Event, release: threading.Event, value):
        def execute(**kwargs):
            started.set()
            release.wait(5)
            return value

        return execute

    async def _cancel_create_doc_once_started(self, ctx, started, release):
        """Run create_doc in an anyio task group (mcp cancels a request through an
        anyio cancel scope), cancel it once `started` fires, then let the blocked
        worker thread finish."""
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                partial(
                    _docs_tools["create_doc"],
                    title="Doc",
                    content="![Alt](drive:file1)",
                    content_format="markdown",
                    ctx=ctx,
                )
            )
            await anyio.to_thread.run_sync(started.wait, 5)
            tg.cancel_scope.cancel()
            release.set()

    async def test_share_revoked_when_cancelled_mid_edit(self):
        # PR #877 QA round 1 F1: the revoke is shielded, so a cancellation doesn't
        # also cancel the revoke it's waiting on, and the warning still fires.
        drive_svc, docs_svc = self._shared_drive_image_services()
        started, release = threading.Event(), threading.Event()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = (
            self._blocking(started, release, {})
        )
        ctx = self._ctx(drive_svc, docs_svc)
        with patch.object(images_module, "logger") as mock_logger:
            await self._cancel_create_doc_once_started(ctx, started, release)
        self._assert_file1_revoked(drive_svc)
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "none", "file1", "none")

    async def test_share_revoked_when_cancelled_mid_share(self):
        # PR #877 QA round 1 F1: cancelled while the share is being granted, the
        # resolution still finishes (shielded) so the new permission is recorded
        # and revoked instead of being lost with the cancelled gather.
        drive_svc, docs_svc = self._shared_drive_image_services()
        started, release = threading.Event(), threading.Event()
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = self._blocking(
            started, release, {"id": "perm1"}
        )
        ctx = self._ctx(drive_svc, docs_svc)
        await self._cancel_create_doc_once_started(ctx, started, release)
        self._assert_file1_revoked(drive_svc)
        # #904: the cancellation lands before the content batchUpdate is handed to
        # a worker thread that could no longer be stopped.
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_cancelled_mid_edit_marks_doc_dirty_after_edit_lands(self):
        # #907: the cancelled edit's worker thread still commits after the
        # cancellation unwinds, so the doc is marked dirty again once it does,
        # not only on the cancel path before it.
        drive_svc, docs_svc = self._shared_drive_image_services()
        started, release, landed = threading.Event(), threading.Event(), []

        def execute(**kwargs):
            started.set()
            release.wait(5)
            landed.append(True)
            return {}

        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = execute
        ctx = self._ctx(drive_svc, docs_svc)
        doc_cache = ctx.request_context.lifespan_context.doc_cache
        dirty_after_landing = []
        doc_cache.mark_dirty.side_effect = lambda doc_id: dirty_after_landing.append(
            (doc_id, bool(landed))
        )
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                partial(
                    _docs_tools["create_doc"],
                    title="Doc",
                    content="![Alt](drive:file1)",
                    content_format="markdown",
                    ctx=ctx,
                )
            )
            await anyio.to_thread.run_sync(started.wait, 5)
            tg.cancel_scope.cancel()
        assert dirty_after_landing == [("doc123", False)]
        release.set()
        with anyio.fail_after(2):
            while ("doc123", True) not in dirty_after_landing:
                await anyio.sleep(0.01)

    async def test_cancelled_create_doc_still_marks_target_folder_dirty(self):
        # PR #1029 QA round 1: the doc exists in the folder from the create on, so
        # a cancellation out of the content step still changes its listing.
        drive_svc, docs_svc = self._shared_drive_image_services()
        started, release = threading.Event(), threading.Event()
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = self._blocking(
            started, release, {"id": "perm1"}
        )
        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        await self._cancel_create_doc_once_started(ctx, started, release)
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_with(
            "folder1"
        )

    @pytest.mark.parametrize("tool_name", ["create_doc", "create_doc_from_file"])
    async def test_cancelled_mid_create_marks_folder_dirty_after_create_lands(
        self, tmp_path, tool_name
    ):
        # PR #1029 QA round 2: the create's worker thread can't be stopped, so the
        # Doc lands in the folder after the cancellation unwinds, past the
        # post-create mark_dirty. The folder is marked dirty once it lands.
        drive_svc, docs_svc = self._make_services()
        started, release, landed = threading.Event(), threading.Event(), []

        def create(**kwargs):
            started.set()
            release.wait(5)
            landed.append(True)
            return {"id": "doc123", "name": "Doc", "parents": ["folder1"], "webViewLink": "x"}

        drive_svc.files.return_value.create.return_value.execute.side_effect = create
        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        dirty_after_landing = []
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.side_effect = (
            lambda folder_id: dirty_after_landing.append((folder_id, bool(landed)))
        )
        if tool_name == "create_doc":
            call = partial(_docs_tools["create_doc"], title="Doc", content="Text", ctx=ctx)
        else:
            source = tmp_path / "doc.md"
            source.write_text("Text\n")
            call = partial(_docs_tools["create_doc_from_file"], local_path=str(source), ctx=ctx)
        async with anyio.create_task_group() as tg:
            tg.start_soon(call)
            await anyio.to_thread.run_sync(started.wait, 5)
            tg.cancel_scope.cancel()
        # #1030: the cancel path marks it too, before the create lands.
        assert dirty_after_landing == [("folder1", False)]
        release.set()
        with anyio.fail_after(2):
            while ("folder1", True) not in dirty_after_landing:
                await anyio.sleep(0.01)

    async def test_cancelled_mid_revoke_after_successful_edit_is_logged(self):
        # #908: a cancellation that arrives during the success path's shielded
        # revoke used to be absorbed by the shield with nothing logged.
        drive_svc, docs_svc = self._shared_drive_image_services()
        started, release = threading.Event(), threading.Event()
        drive_svc.permissions.return_value.delete.return_value.execute.side_effect = self._blocking(
            started, release, {}
        )
        ctx = self._ctx(drive_svc, docs_svc)
        with patch.object(images_module, "logger") as mock_logger:
            await self._cancel_create_doc_once_started(ctx, started, release)
        self._assert_file1_revoked(drive_svc)
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "none", "file1", "none")

    async def test_resized_drive_copy_marks_its_own_folder_dirty(self):
        # #666: a drive: source's resized copy lands next to the original, not in
        # the doc's folder, so that folder's listing changed too.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "big.png",
            "parents": ["origfolder"],
            "imageMediaMetadata": {"width": 6000, "height": 6000},
        }
        drive_svc.files.return_value.create.return_value.execute.side_effect = [
            {"id": "doc123", "name": "Test", "parents": ["folder1"], "webViewLink": "x"},
            {"id": "resized1", "webContentLink": "https://drive.google.com/uc?id=resized1"},
        ]
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        png_bytes = _make_png_bytes(6000, 6000)

        class _FakeDownloader:
            def __init__(self, fh, request):
                fh.write(png_bytes)

            def next_chunk(self):
                return None, True

        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        with (
            patch("mcp_gee_sweet.tools.docs.images.MediaIoBaseDownload", _FakeDownloader),
            patch("mcp_gee_sweet.tools.docs.images.thread_http"),
        ):
            result = await _docs_tools["create_doc"](
                title="Doc",
                content="![Big](drive:orig1)",
                content_format="markdown",
                auto_downscale=True,
                ctx=ctx,
            )
        assert result["images"][0]["fileId"] == "resized1"
        folder_cache = ctx.request_context.lifespan_context.drive_folder_cache
        dirtied = {c.args[0] for c in folder_cache.mark_dirty.call_args_list}
        assert dirtied == {"origfolder", "folder1"}

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
        assert result["images"] == [
            {"src": missing, "error": f"No file found at {missing!r}", "fallback_text": "Alt"}
        ]
        # The image itself never made it into the doc — no insertInlineImage request —
        # but the surrounding text still went through, and its alt text stands in for
        # it (#1099).
        image_reqs = [r for r in self._batchupdate_requests(docs_svc) if "insertInlineImage" in r]
        assert image_reqs == []
        texts = [
            r["insertText"]["text"]
            for r in self._batchupdate_requests(docs_svc)
            if "insertText" in r
        ]
        assert "Before" in texts[0]
        assert "After" in texts[0]
        assert texts[1:] == ["Alt"]

    async def test_sharing_failure_image_outcome_still_carries_file_id(self, tmp_path):
        # A local-upload source: the file was freshly created by this call, so
        # _resolve_image_source surfaces file_id alongside its sharing-step error
        # (#649) and the outcome-list assembly loop must not drop it (it
        # previously only copied result["error"], discarding any other key).
        # A "drive:" source is deliberately NOT used here — that path no longer
        # carries file_id on failure (PR #652 QA round 1, finding 2); see
        # test_drive_source_sharing_failure_omits_file_id below.
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake")
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive_svc.files.return_value.create.return_value.execute.side_effect = [
            {"id": "doc123", "name": "Test", "parents": ["folder1"], "webViewLink": "x"},
            {
                "id": "uploaded1",
                "name": "pic.png",
                "webViewLink": "y",
                "webContentLink": "https://drive.google.com/uc?id=uploaded1",
            },
        ]
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = RuntimeError(
            "boom"
        )
        ctx = self._ctx(drive_svc, docs_svc, folder_id="folder1")
        result = await _docs_tools["create_doc"](
            title="Doc",
            content=f"![Alt]({img})",
            content_format="markdown",
            ctx=ctx,
        )
        assert result["images"] == [
            {
                "src": str(img),
                "fileId": "uploaded1",
                "error": "sharing failed for Drive file 'uploaded1': boom",
                "fallback_text": "Alt",
            }
        ]
        image_reqs = [r for r in self._batchupdate_requests(docs_svc) if "insertInlineImage" in r]
        assert image_reqs == []

    async def test_drive_source_sharing_failure_omits_file_id(self):
        # Counterpart to the local-upload case above: a "drive:" source's sharing
        # failure must NOT surface file_id in the image outcome — that file is
        # the caller's own pre-existing artifact, and a caller with orphan-reclaim
        # logic keyed on "fileId in a failed outcome" could delete it (PR #652 QA
        # round 1, finding 2).
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "name": "file1",
            "webContentLink": "https://drive.google.com/uc?id=file1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.side_effect = RuntimeError(
            "boom"
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
                "error": "sharing failed for Drive file 'file1': boom",
                "fallback_text": "Alt",
            }
        ]
        image_reqs = [r for r in self._batchupdate_requests(docs_svc) if "insertInlineImage" in r]
        assert image_reqs == []

    async def test_no_images_omits_images_key(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](title="Doc", content="<p>plain</p>", ctx=ctx)
        assert "images" not in result

    # #1073: a one-row, two-cell table after a "x" paragraph, as documents().get()
    # returns it once phase 1 has inserted the table shell.
    _CELL_IMAGE_HTML = (
        '<p>x</p><table><tr><td>Logo</td><td><img src="{uri}"> after</td></tr></table>'
    )
    _CELL_IMAGE_LIVE_DOC: ClassVar[dict] = {
        "body": {
            "content": [
                {
                    "startIndex": 1,
                    "endIndex": 3,
                    "paragraph": {"elements": [{"textRun": {"content": "x\n"}}]},
                },
                {
                    "startIndex": 3,
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"startIndex": 5, "content": [{"startIndex": 6}]},
                                    {"startIndex": 8, "content": [{"startIndex": 9}]},
                                ]
                            }
                        ]
                    },
                },
            ]
        }
    }

    def _fill_batches(self, docs_svc) -> list[list[dict]]:
        return [
            c.kwargs["body"]["requests"]
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
            if any(
                r.get("insertText", {}).get("text") == "Logo" for r in c.kwargs["body"]["requests"]
            )
        ]

    async def test_table_cell_image_embedded_in_its_cell(self):
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.get.return_value.execute.return_value = (
            self._CELL_IMAGE_LIVE_DOC
        )
        uri = "https://example.com/cell.png"
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc", content=self._CELL_IMAGE_HTML.format(uri=uri), ctx=ctx
        )
        assert result["images"] == [{"src": uri}]
        [fill] = self._fill_batches(docs_svc)
        inserts = [r["insertInlineImage"] for r in fill if "insertInlineImage" in r]
        # The second cell's paragraph starts at 9; the image goes before " after".
        assert inserts == [{"uri": uri, "location": {"index": 9}}]
        assert {"insertText": {"location": {"index": 9}, "text": " after"}} in fill

    async def test_unfetchable_table_cell_image_dropped_and_reported(self):
        # One bad cell image must not lose the whole table fill: the batch is
        # retried without it, and the image's own entry says why.
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.get.return_value.execute.return_value = (
            self._CELL_IMAGE_LIVE_DOC
        )
        bad_uri = "https://example.com/bad.png"
        docs_svc.documents.return_value.batchUpdate.side_effect = self._fail_first_matching(
            {bad_uri}
        )
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc", content=self._CELL_IMAGE_HTML.format(uri=bad_uri), ctx=ctx
        )
        assert "error" not in result
        [entry] = result["images"]
        assert "doc edit failed" in entry["error"]
        assert "There was a problem retrieving the image" in entry["error"]
        failed, retry = self._fill_batches(docs_svc)
        assert retry == [r for r in failed if "insertInlineImage" not in r]
        assert any("insertText" in r for r in retry)

    async def test_partial_split_then_other_failure_reports_unplaced_cell_images(self):
        # PR #1215 QA round 2: after a split, the head of the fill batch has landed; if
        # the rest then fails for a non-image reason, an image in it must not read as
        # embedded in the DocEditError's outcome list.
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.get.return_value.execute.return_value = (
            self._CELL_IMAGE_LIVE_DOC
        )
        good, bad_b, bad_c = (f"https://example.com/{n}.png" for n in ("a", "b", "c"))
        html = (
            f'<p>x</p><table><tr><td><img src="{good}">Logo<img src="{bad_b}"></td>'
            f'<td><img src="{bad_c}"> after</td></tr></table>'
        )

        def batchupdate_side_effect(documentId, body):
            m = MagicMock()
            uris = [r.get("insertInlineImage", {}).get("uri") for r in body["requests"]]
            bad_index = next((i for i, u in enumerate(uris) if u in (bad_b, bad_c)), None)
            if bad_index is not None:
                m.execute.side_effect = self._insert_image_http_error(bad_index)
            elif [u for u in uris if u] == [good]:
                # The tail left after the split (bad_b's fallback text, then the good
                # image): a server error, not an image one.
                resp = MagicMock()
                resp.status = 500
                m.execute.side_effect = HttpError(resp=resp, content=b"{}", uri="x")
            else:
                m.execute.return_value = {}
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = batchupdate_side_effect
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](title="Doc", content=html, ctx=ctx)

        assert "error" in result
        outcomes = {o["src"]: o for o in result["images"]}
        assert outcomes[good]["error"] == ("not embedded: the doc edit failed before it was placed")
        assert outcomes[bad_b]["error"].startswith("doc edit failed:")
        assert outcomes[bad_c]["error"].startswith("doc edit failed:")
        # #1099: bad_c's fallback text went out in the head, which landed; bad_b's
        # was in the failed tail, so it isn't reported as shown.
        assert outcomes[bad_c]["fallback_text"] == "c.png"
        assert "fallback_text" not in outcomes[bad_b]

    async def test_body_batch_failure_reports_cell_images_as_unplaced(self):
        # PR #1215 QA round 3: a failure before the fill (here the phase-1 batch, which
        # inserts the table shell) must not leave cell images reading as embedded.
        drive_svc, docs_svc = self._make_services()
        uri = "https://example.com/cell.png"

        def batchupdate_side_effect(documentId, body):
            m = MagicMock()
            if any("insertTable" in r for r in body["requests"]):
                resp = MagicMock()
                resp.status = 500
                m.execute.side_effect = HttpError(resp=resp, content=b"{}", uri="x")
            else:
                m.execute.return_value = {}
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = batchupdate_side_effect
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc", content=self._CELL_IMAGE_HTML.format(uri=uri), ctx=ctx
        )
        assert "error" in result
        assert result["images"] == [
            {"src": uri, "error": "not embedded: the doc edit failed before it was placed"}
        ]

    async def test_cell_image_the_fill_never_placed_is_reported(self):
        # PR #1215 QA round 1: a resolved cell image whose cell the fill can't locate
        # gets no insert, and must not read as embedded.
        drive_svc, docs_svc = self._make_services()
        live_doc = json.loads(json.dumps(self._CELL_IMAGE_LIVE_DOC))
        live_doc["body"]["content"][1]["table"]["tableRows"][0]["tableCells"][1]["content"] = []
        docs_svc.documents.return_value.get.return_value.execute.return_value = live_doc
        uri = "https://example.com/cell.png"
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc"](
            title="Doc", content=self._CELL_IMAGE_HTML.format(uri=uri), ctx=ctx
        )
        assert result["images"] == [
            {"src": uri, "error": "not embedded: its table cell wasn't found in the document"}
        ]

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

        # #510: the caller-facing error comes from the API's own message, minus
        # the internal "Invalid requests[N]." lead-in and HttpError's display
        # wrapper.
        assert "requests[" not in outcomes[bad_uri]["error"]
        assert "<HttpError" not in outcomes[bad_uri]["error"]
        assert "There was a problem retrieving the image" in outcomes[bad_uri]["error"]

        # #510 QA round 1: K=1 stays two atomic calls — the retry is the whole
        # remaining list with only the bad image removed, never a split.
        calls = [
            c.kwargs["body"]["requests"]
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]
        assert len(calls) == 2
        full, retry = calls
        assert retry == [r for r in full if r.get("insertInlineImage", {}).get("uri") != bad_uri]

    def _fail_first_matching(self, bad_uris: set[str]):
        """batchUpdate side effect: fail on the first request (in list order) whose
        image uri is in bad_uris, mirroring the live API naming only one per
        error; succeed otherwise."""

        def side_effect(documentId, body):
            m = MagicMock()
            bad_index = next(
                (
                    i
                    for i, r in enumerate(body["requests"])
                    if r.get("insertInlineImage", {}).get("uri") in bad_uris
                ),
                None,
            )
            if bad_index is None:
                m.execute.return_value = {}
            else:
                m.execute.side_effect = self._insert_image_http_error(bad_index)
            return m

        return side_effect

    async def test_multiple_bad_images_retry_only_the_insert_tail(self):
        # #510: Google names only the first failing image per error (confirmed
        # live), so K bad images need K retries. The first retry is still one
        # atomic whole-list call; from the second bad image on, the text/style
        # prefix is committed once and only the positional-insert tail is retried.
        drive_svc, docs_svc = self._make_services()
        good_uri = "https://example.com/good.png"
        bad_uris = {
            "https://example.com/bad1.png",
            "https://example.com/bad2.png",
            "https://example.com/bad3.png",
        }
        content = (
            "Before\n\n![Bad1](https://example.com/bad1.png)\n\n![Good](https://example.com/good.png)"
            "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n![Bad2](https://example.com/bad2.png)"
            "\n\nMiddle\n\n![Bad3](https://example.com/bad3.png)\n\nAfter"
        )
        docs_svc.documents.return_value.batchUpdate.side_effect = self._fail_first_matching(
            bad_uris
        )
        ctx = self._ctx(drive_svc, docs_svc)

        # fill_tables (the table's cell-fill pass) isn't under test here.
        with patch.object(content_module, "fill_tables"):
            result = await _docs_tools["create_doc"](
                title="Doc", content=content, content_format="markdown", ctx=ctx
            )

        outcomes = {o["src"]: o for o in result["images"]}
        assert "error" not in outcomes[good_uri]
        assert all("doc edit failed" in outcomes[uri]["error"] for uri in bad_uris)
        # #1099: each bad image's alt text stands in for it.
        assert {outcomes[uri]["fallback_text"] for uri in bad_uris} == {"Bad1", "Bad2", "Bad3"}

        # Snapshots: the retry loop edits the list it sent in place.
        calls = [
            list(c.kwargs["body"]["requests"])
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]
        # full (fails bad #1), whole-list retry (fails bad #2), prefix commit,
        # tail (fails bad #3), tail (succeeds).
        _full, retry, prefix, *tail_attempts = calls
        assert len(tail_attempts) == 2
        assert any("insertText" in r for r in retry)
        assert not any("insertInlineImage" in r or "insertTable" in r for r in prefix)
        fallback_texts = {"Bad1", "Bad2", "Bad3"}
        for attempt in tail_attempts:
            # Each insertTable is followed by its placeholder's delete (#1097), and
            # each fallback text by its link request.
            assert all(
                "insertInlineImage" in r
                or "insertTable" in r
                or ("deleteContentRange" in r and "insertTable" in attempt[i - 1])
                or r.get("insertText", {}).get("text") in fallback_texts
                or (
                    r.get("updateTextStyle", {}).get("fields") == "link"
                    and attempt[i - 1].get("insertText", {}).get("text") in fallback_texts
                )
                for i, r in enumerate(attempt)
            )
        final_tail = tail_attempts[-1]
        assert [r["insertInlineImage"]["uri"] for r in final_tail if "insertInlineImage" in r] == [
            good_uri
        ]
        assert any("insertTable" in r for r in final_tail)
        assert sorted(
            r["insertText"]["text"]
            for r in final_tail
            if r.get("insertText", {}).get("text") in fallback_texts
        ) == ["Bad1", "Bad2", "Bad3"]

    @staticmethod
    def _image_link_ranges(requests: list[dict]) -> list[dict]:
        return [
            r["updateTextStyle"]["range"]
            for r in requests
            if r.get("updateTextStyle", {}).get("fields") == "link"
            and r["updateTextStyle"]["textStyle"]["link"]["url"].startswith("https://link/")
        ]

    async def test_bad_linked_image_link_moves_to_its_fallback_text(self):
        # #977: left behind, a dropped image's link request would link whatever
        # character now sits at the image's position. #1099: the image's alt text
        # takes its place, carrying the link over the text's whole range.
        drive_svc, docs_svc = self._make_services()
        bad_uri = "https://example.com/bad.png"
        content = (
            f"Before [![Bad]({bad_uri})](https://link/bad) and "
            "[![Good](https://example.com/good.png)](https://link/good) after"
        )
        # The retry pops from the same list it sent, so snapshot each call.
        sent: list[list[dict]] = []
        fail = self._fail_first_matching({bad_uri})

        def side_effect(documentId, body):
            sent.append(list(body["requests"]))
            return fail(documentId, body)

        docs_svc.documents.return_value.batchUpdate.side_effect = side_effect
        ctx = self._ctx(drive_svc, docs_svc)

        result = await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )

        bad_entry = {o["src"]: o for o in result["images"]}[bad_uri]
        assert "error" in bad_entry
        assert bad_entry["fallback_text"] == "Bad"
        full, retry = sent
        assert len(self._image_link_ranges(full)) == 2
        bad_index = next(
            i for i, r in enumerate(full) if r.get("insertInlineImage", {}).get("uri") == bad_uri
        )
        bad_position = full[bad_index]["insertInlineImage"]["location"]["index"]
        fallback = [
            {"insertText": {"location": {"index": bad_position}, "text": "Bad"}},
            {
                "updateTextStyle": {
                    "range": {"startIndex": bad_position, "endIndex": bad_position + 3},
                    "textStyle": {"link": {"url": "https://link/bad"}},
                    "fields": "link",
                }
            },
        ]
        assert retry == full[:bad_index] + fallback + full[bad_index + 2 :]
        good = next(r for r in retry if "insertInlineImage" in r)
        index = good["insertInlineImage"]["location"]["index"]
        assert sorted(self._image_link_ranges(retry), key=lambda r: r["startIndex"]) == sorted(
            [
                {"startIndex": index, "endIndex": index + 1},
                {"startIndex": bad_position, "endIndex": bad_position + 3},
            ],
            key=lambda r: r["startIndex"],
        )

    async def test_multiple_bad_linked_images_still_retry_only_the_insert_tail(self):
        # #977 + #510: link requests ride inside the positional-insert tail, so
        # the K>=2 split still finds every image there instead of falling back
        # to whole-list retries.
        drive_svc, docs_svc = self._make_services()
        bad_uris = {"https://example.com/bad1.png", "https://example.com/bad2.png"}
        content = (
            "Before\n\n[![Bad1](https://example.com/bad1.png)](https://link/1)\n\n"
            "[![Good](https://example.com/good.png)](https://link/good)\n\n"
            "[![Bad2](https://example.com/bad2.png)](https://link/2)\n\nAfter"
        )
        docs_svc.documents.return_value.batchUpdate.side_effect = self._fail_first_matching(
            bad_uris
        )
        ctx = self._ctx(drive_svc, docs_svc)

        await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )

        _full, _retry, prefix, tail = [
            c.kwargs["body"]["requests"]
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]
        assert not any("insertInlineImage" in r for r in prefix)
        assert self._image_link_ranges(prefix) == []
        assert [r["insertInlineImage"]["uri"] for r in tail if "insertInlineImage" in r] == [
            "https://example.com/good.png"
        ]
        # Descending positions: Bad2's fallback text, the good image, Bad1's fallback
        # text (#1099), each followed by its own link request.
        assert [
            r.get("insertText", {}).get("text") or r.get("insertInlineImage", {}).get("uri")
            for r in tail[::2]
        ] == ["Bad2", "https://example.com/good.png", "Bad1"]
        assert [r["updateTextStyle"]["textStyle"]["link"]["url"] for r in tail[1::2]] == [
            "https://link/2",
            "https://link/good",
            "https://link/1",
        ]
        index = tail[2]["insertInlineImage"]["location"]["index"]
        assert tail[3]["updateTextStyle"]["range"] == {"startIndex": index, "endIndex": index + 1}

    @staticmethod
    def _server_error() -> HttpError:
        return HttpError(resp=MagicMock(status=500), content=b'{"error": {"message": "x"}}')

    async def test_non_image_error_on_single_retry_propagates_with_nothing_committed(self):
        # #510 QA round 1: with one bad image the retry is atomic, so a
        # non-image failure there raises before anything reaches the doc.
        drive_svc, docs_svc = self._make_services()
        bad_uri = "https://example.com/bad.png"
        content = f"Before\n\n![Bad]({bad_uri})\n\nAfter"
        fail_bad = self._fail_first_matching({bad_uri})
        calls = []

        def side_effect(documentId, body):
            calls.append(body["requests"])
            if len(calls) == 1:
                return fail_bad(documentId, body)
            m = MagicMock()
            m.execute.side_effect = self._server_error()
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = side_effect
        ctx = self._ctx(drive_svc, docs_svc)

        result = await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )
        assert result["error"].startswith("doc edit failed: ")
        assert len(calls) == 2
        # The failed retry still carried the text: no call ever sent it alone.
        assert any("insertText" in r for r in calls[1])

    async def test_non_image_error_after_prefix_commit_propagates(self):
        # The documented K>=2 partial-write window: once the prefix is committed,
        # a non-image tail failure must still surface, not loop or be swallowed.
        # PR #877 QA round 1 F5: the shared drive: image's share is still revoked
        # and the warning still fires on this path.
        drive_svc, docs_svc = self._shared_drive_image_services()
        bad_uris = {"https://example.com/bad1.png", "https://example.com/bad2.png"}
        content = (
            "Before\n\n![Bad1](https://example.com/bad1.png)\n\n"
            "![Good](drive:file1)\n\n![Bad2](https://example.com/bad2.png)"
        )
        fail_bad = self._fail_first_matching(bad_uris)
        calls = []

        def side_effect(documentId, body):
            calls.append(body["requests"])
            if len(calls) <= 3:  # full, whole-list retry, prefix commit
                return fail_bad(documentId, body)
            m = MagicMock()
            m.execute.side_effect = self._server_error()
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = side_effect
        ctx = self._ctx(drive_svc, docs_svc)

        with patch.object(images_module, "logger") as mock_logger:
            result = await _docs_tools["create_doc"](
                title="Doc", content=content, content_format="markdown", ctx=ctx
            )
        assert result["error"].startswith("doc edit failed: ")
        assert len(calls) == 4
        assert not any("insertInlineImage" in r for r in calls[2])
        outcomes = {o["src"]: o for o in result["images"]}
        assert all("doc edit failed" in outcomes[uri]["error"] for uri in bad_uris)
        assert outcomes["drive:file1"] == {"src": "drive:file1", "fileId": "file1", "shared": False}
        self._assert_file1_revoked(drive_svc)
        assert mock_logger.warning.call_args.args[1:] == ("doc123", "none", "file1", "none")

    async def test_image_outside_insert_tail_falls_back_to_whole_list_retries(self):
        # #510 QA round 1: the tail boundary is inferred from request kinds. If
        # ast_to_requests ever emitted something after its positional-insert pass,
        # the scan would find no tail — the retry must degrade to the old
        # whole-list behavior instead of committing an image-bearing prefix.
        drive_svc, docs_svc = self._make_services()
        bad_uris = {"https://example.com/bad1.png", "https://example.com/bad2.png"}
        good_uri = "https://example.com/good.png"
        content = (
            f"Before\n\n![Bad1](https://example.com/bad1.png)\n\n![Good]({good_uri})"
            "\n\n![Bad2](https://example.com/bad2.png)"
        )
        trailing = {"updateDocumentStyle": {"documentStyle": {}, "fields": "marginTop"}}
        real_ast_to_requests = content_module.ast_to_requests

        def with_trailing_request(*args, **kwargs):
            requests, tables = real_ast_to_requests(*args, **kwargs)
            return [*requests, trailing], tables

        docs_svc.documents.return_value.batchUpdate.side_effect = self._fail_first_matching(
            bad_uris
        )
        ctx = self._ctx(drive_svc, docs_svc)

        with patch.object(content_module, "ast_to_requests", with_trailing_request):
            result = await _docs_tools["create_doc"](
                title="Doc", content=content, content_format="markdown", ctx=ctx
            )

        outcomes = {o["src"]: o for o in result["images"]}
        assert "error" not in outcomes[good_uri]
        calls = [
            c.kwargs["body"]["requests"]
            for c in docs_svc.documents.return_value.batchUpdate.call_args_list
        ]
        # full, retry (fails bad #2), retry (succeeds) — every call is the whole list.
        assert len(calls) == 3
        assert all(any("insertText" in r for r in call) for call in calls)
        assert calls[-1][-1] == trailing

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
        assert "50MB" in error
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
        # create_doc_from_file has no content_format parameter to suggest (#567).
        assert "content_format" not in result["error"]

    @pytest.mark.parametrize("kind", ["directory", "latin1"])
    async def test_unreadable_source_returns_error(self, tmp_path, kind):
        # PR #961 QA round 1: a path that exists but isn't a readable UTF-8 file
        # returns {"error": ...} instead of raising, and creates nothing.
        if kind == "directory":
            src = tmp_path / "dir.md"
            src.mkdir()
        else:
            src = tmp_path / "latin1.html"
            src.write_bytes("<p>caf\xe9</p>".encode("latin-1"))
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["create_doc_from_file"](local_path=str(src), ctx=ctx)
        assert "error" in result
        assert str(src) in result["error"]
        drive_svc.files.return_value.create.assert_not_called()


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
        # Read before the backup copy, and again after it (#878).
        assert docs_svc.documents.return_value.get.call_args_list == [
            call(documentId="doc1"),
            call(documentId="doc1"),
        ]

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
        assert "pass content_format explicitly" in result["error"]
        docs_svc.documents.return_value.get.assert_not_called()

    @pytest.mark.parametrize("kind", ["directory", "latin1"])
    async def test_unreadable_source_returns_error(self, tmp_path, kind):
        # PR #961 QA round 1: same as create_doc_from_file; the doc is never touched.
        if kind == "directory":
            src = tmp_path / "dir.md"
            src.mkdir()
        else:
            src = tmp_path / "latin1.html"
            src.write_bytes("<p>caf\xe9</p>".encode("latin-1"))
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(src), ctx=ctx
        )
        assert "error" in result
        assert str(src) in result["error"]
        docs_svc.documents.return_value.get.assert_not_called()

    def test_doc_content_flags_are_keyword_only(self):
        # #567 / PR #961 QA round 1: positional bools could be swapped at a call site
        # and still type-check, in both shared helpers.
        for fn, names in (
            (
                content_module._replace_doc_content,
                ("autolink_urls", "revoke_sharing", "auto_downscale", "allow_no_backup"),
            ),
            (
                content_module._apply_doc_content,
                ("target_folder_id", "revoke_sharing", "auto_downscale"),
            ),
        ):
            params = inspect.signature(fn).parameters
            for name in names:
                assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (fn.__name__, name)

    @pytest.mark.parametrize(
        "flags",
        [
            {"autolink_urls": False, "revoke_sharing": True, "auto_downscale": True},
            {"autolink_urls": True, "revoke_sharing": False, "auto_downscale": False},
        ],
    )
    async def test_flags_reach_apply_doc_content_unswapped(self, tmp_path, flags):
        # #567: _replace_doc_content's three bools are keyword-only, so each tool
        # flag must land in its own slot: autolink_urls in the conversion (#1240),
        # the other two in _apply_doc_content.
        md_file = tmp_path / "notes.md"
        md_file.write_text("text\n")
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        real_apply = content_module._apply_doc_content
        real_convert = content_module._convert_doc_content
        with (
            patch.object(
                content_module, "_apply_doc_content", return_value=content_module.AppliedContent()
            ) as apply,
            patch.object(content_module, "_convert_doc_content", wraps=real_convert) as convert,
        ):
            await _docs_tools["update_doc_from_file"](
                doc_id="doc1", local_path=str(md_file), ctx=ctx, **flags
            )
        # Bind against the real signatures so the assertion holds however the call
        # site passes them, and fails if the call wouldn't bind at all.
        bound = inspect.signature(real_apply).bind(*apply.call_args.args, **apply.call_args.kwargs)
        bound_convert = inspect.signature(real_convert).bind(
            *convert.call_args.args, **convert.call_args.kwargs
        )
        assert bound_convert.arguments["autolink_urls"] == flags["autolink_urls"]
        assert {k: bound.arguments[k] for k in ("revoke_sharing", "auto_downscale")} == {
            k: flags[k] for k in ("revoke_sharing", "auto_downscale")
        }

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
        final_mark = {"startIndex": 49, "endIndex": 50}
        assert clear_requests == [
            {"updateTextStyle": {"range": final_mark, "textStyle": {}, "fields": "*"}},
            # The final mark's paragraph style survives the clear too: a doc ending in a
            # heading made every new paragraph that heading (PR #1201 QA round 1).
            {"deleteParagraphBullets": {"range": final_mark}},
            {
                "updateParagraphStyle": {
                    "range": final_mark,
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "*",
                }
            },
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 49}}},
        ]
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


class TestGetDocStructureCodeBlockSoftBreak:
    """#731 (found in QA on #719's own PR): get_doc_structure built its text
    straight off the raw Docs API response with no reversal for emitter.py's
    "\\n" -> "\\v" substitution on a code-styled paragraph, leaking a literal
    "\\v" (U+000B) instead of restoring the original newline."""

    def _ctx(self, docs_svc):
        return _make_ctx(docs_service=docs_svc)

    async def test_courier_new_paragraph_soft_breaks_restored_to_newlines(self):
        style = {"weightedFontFamily": {"fontFamily": "Courier New"}}
        para = {
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "elements": [{"textRun": {"content": "line1\vline2\vline3\n", "textStyle": style}}],
        }
        doc = {
            "documentId": "doc1",
            "title": "Doc",
            "body": {"content": [{"startIndex": 1, "endIndex": 20, "paragraph": para}]},
        }
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = doc

        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))

        elem = result["elements"][0]
        assert "\v" not in elem["text"]
        assert elem["text"] == "line1\nline2\nline3\n"
        assert elem["runs"][0]["text"] == "line1\nline2\nline3\n"

    async def test_table_cell_courier_new_soft_breaks_restored_to_newlines(self):
        style = {"weightedFontFamily": {"fontFamily": "Courier New"}}
        cell = {
            "startIndex": 5,
            "endIndex": 20,
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "a\vb\n", "textStyle": style}},
                        ]
                    }
                }
            ],
        }
        doc = {
            "documentId": "doc1",
            "title": "Doc",
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 30,
                        "table": {"tableRows": [{"tableCells": [cell]}]},
                    }
                ]
            },
        }
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = doc

        result = await _docs_tools["get_doc_structure"](doc_id="doc1", ctx=self._ctx(docs_svc))

        cell_result = result["elements"][0]["cells"][0]
        assert "\v" not in cell_result["text"]
        assert cell_result["text"] == "a\nb"


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

    def test_true_for_table_cell_image_anchor_link(self):
        # #1073: a cell image's link goes in through the fill too.
        table = Table(rows=[Row(cells=[Cell(children=[Image(src="a", link_url="#slug")])])])
        assert _has_pending_anchor_links([], [table]) is True


class TestResolveHeadingAnchorsHelper:
    def _paragraph_elem(self, start, text, *, heading_id=None, link_url=None):
        """Build one body-content element: a heading paragraph (heading_id
        given) or a plain paragraph, optionally carrying a same-document
        '#slug' link on its one run. Shared by every fixture in this class
        (issue #454 QA finding — was previously duplicated between this
        helper and _doc_with_anchor below, two independent builders for the
        same JSON shape)."""
        end = start + len(text) + 1
        style = (
            {"namedStyleType": "HEADING_1", "headingId": heading_id}
            if heading_id
            else {"namedStyleType": "NORMAL_TEXT"}
        )
        text_style = {"link": {"url": link_url}} if link_url else {}
        return {
            "startIndex": start,
            "endIndex": end,
            "paragraph": {
                "paragraphStyle": style,
                "elements": [
                    {
                        "startIndex": start,
                        "endIndex": end,
                        "textRun": {"content": text + "\n", "textStyle": text_style},
                    }
                ],
            },
        }

    def _doc_with_anchor(self, anchor_url, heading_text="Overview", heading_id="h.xyz"):
        return {
            "documentId": "doc1",
            "body": {
                "content": [
                    self._paragraph_elem(1, heading_text, heading_id=heading_id),
                    self._paragraph_elem(20, "Link", link_url=anchor_url),
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

    async def test_linked_image_anchor_is_resolved(self):
        # #977: a linked image's link lives on its inlineObjectElement's own
        # textStyle, not a textRun, so "[![alt](src)](#overview)" needs the
        # walker to look there too.
        image_para = {
            "startIndex": 20,
            "endIndex": 23,
            "paragraph": {
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "elements": [
                    {
                        "startIndex": 20,
                        "endIndex": 21,
                        "textRun": {"content": "x", "textStyle": {}},
                    },
                    {
                        "startIndex": 21,
                        "endIndex": 22,
                        "inlineObjectElement": {
                            "inlineObjectId": "kix.1",
                            "textStyle": {"link": {"url": "#overview"}},
                        },
                    },
                    {
                        "startIndex": 22,
                        "endIndex": 23,
                        "textRun": {"content": "\n", "textStyle": {}},
                    },
                ],
            },
        }
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "body": {
                "content": [
                    self._paragraph_elem(1, "Overview", heading_id="h.xyz"),
                    image_para,
                ]
            },
        }
        summary = await _resolve_heading_anchors(docs_svc, "doc1")
        assert summary["resolved"] == [{"anchor": "#overview", "heading": "Overview"}]
        requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        assert [r["updateTextStyle"]["range"] for r in requests] == [
            {"startIndex": 21, "endIndex": 22}
        ]

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

    async def test_multiple_anchors_slugify_heading_list_once_per_scheme(self):
        # Regression (#454): resolving N anchors against the same heading
        # list must slugify that list once per known scheme, not once per
        # scheme per anchor — the whole point of precomputing scheme_slugs
        # once in _resolve_heading_anchors and threading it through every
        # resolve_heading_anchor call in the loop.
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "documentId": "doc1",
            "body": {
                "content": [
                    self._paragraph_elem(1, "Overview", heading_id="h.one"),
                    self._paragraph_elem(20, "Notes", heading_id="h.two"),
                    self._paragraph_elem(40, "Link A", link_url="#overview"),
                    self._paragraph_elem(60, "Link B", link_url="#notes"),
                    self._paragraph_elem(80, "Link C", link_url="#totally-unrelated"),
                ]
            },
        }

        from mcp_gee_sweet.tools.docs import anchors as anchors_module

        with patch(
            "mcp_gee_sweet.tools.docs.anchors._slugs_with_dedup",
            wraps=anchors_module._slugs_with_dedup,
        ) as spy:
            summary = await _resolve_heading_anchors(docs_svc, "doc1")

        assert {r["anchor"] for r in summary["resolved"]} == {"#overview", "#notes"}
        assert summary["stripped"] == ["#totally-unrelated"]
        # 3 anchors x 2 known schemes would be 6 calls without caching;
        # precomputing scheme_slugs once means exactly 2 (one per scheme).
        assert spy.call_count == 2


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

    @pytest.mark.parametrize("validate", [False, True])
    async def test_edit_landing_mid_fetch_isnt_overwritten_by_the_pre_edit_result(
        self, validate, monkeypatch
    ):
        # #1032: an edit's mark_dirty that lands while this call's export is in
        # flight must stop the export's pre-edit text being stored over it.
        from mcp_gee_sweet.cache import DocContentCache

        monkeypatch.setattr(content_module, "CACHE_VALIDATE_MODIFIED_TIME", validate)
        doc_cache = DocContentCache(db_path=":memory:", ttl=60, principal="test")
        drive_svc = self._drive_svc()

        def export_racing_an_edit(**kwargs):
            doc_cache.mark_dirty("doc1")
            return b"pre-edit text"

        drive_svc.files.return_value.export.return_value.execute.side_effect = export_racing_an_edit
        ctx = self._ctx(drive_svc=drive_svc, doc_cache=doc_cache)

        result = await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

        assert result["content"] == "pre-edit text"
        assert doc_cache.get("doc1") is None

    async def test_refetch_of_a_stale_entry_is_cached(self, monkeypatch):
        # PR #1264 QA round 1: get() marks a stale row dirty itself, which bumps the
        # key's epoch. A snapshot taken before get() made every refetch's store a
        # no-op, so a doc edited outside the server was re-exported on every call.
        from mcp_gee_sweet.cache import DocContentCache

        monkeypatch.setattr(content_module, "CACHE_VALIDATE_MODIFIED_TIME", True)
        doc_cache = DocContentCache(db_path=":memory:", ttl=60, principal="test")
        doc_cache.store(
            "doc1",
            {"id": "doc1", "modified_time": "2025-01-01T00:00:00Z", "content": "old"},
        )
        drive_svc = self._drive_svc()  # reports modifiedTime 2026-01-01T00:00:00Z
        ctx = self._ctx(drive_svc=drive_svc, doc_cache=doc_cache)

        result = await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)

        assert result["content"] == "hello world"
        assert doc_cache.get("doc1", "2026-01-01T00:00:00Z")["content"] == "hello world"

    async def test_fetch_with_no_concurrent_edit_is_cached(self):
        from mcp_gee_sweet.cache import DocContentCache

        doc_cache = DocContentCache(db_path=":memory:", ttl=60, principal="test")
        ctx = self._ctx(doc_cache=doc_cache)
        await _docs_tools["get_doc_content"](file_id="doc1", ctx=ctx)
        assert doc_cache.get("doc1")["content"] == "hello world"

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

        # First batchUpdate call: the final mark's text and paragraph style reset, then
        # the delete, nothing else.
        clear_requests = calls[0]
        assert len(clear_requests) == 4
        clear_style = clear_requests[0]["updateTextStyle"]
        assert clear_style["range"] == {"startIndex": 49, "endIndex": 50}
        assert clear_style["textStyle"] == {}
        assert clear_style["fields"] == "*"
        assert "deleteParagraphBullets" in clear_requests[1]
        assert clear_requests[2]["updateParagraphStyle"]["fields"] == "*"
        assert clear_requests[3]["deleteContentRange"]["range"] == {
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


class TestReplaceDocBackup:
    """#878: write_doc_content / update_doc_from_file copy a doc with content before
    clearing it, delete the copy once the new content is in, and keep it (named as
    backupId) when the replacement fails. Drive's revision history can't serve: the
    revision current before the clear is merged away by it (measured live)."""

    @staticmethod
    def _backup(can_delete=True):
        return {
            "id": "backup1",
            "name": "My Doc (backup before replace)",
            "capabilities": {"canDelete": can_delete},
        }

    def _make_services(self, end_index=50, backup=None):
        drive_svc = MagicMock()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webViewLink": "https://example.com"
        }
        drive_svc.files.return_value.copy.return_value.execute.return_value = (
            backup if backup is not None else self._backup()
        )
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "title": "My Doc",
            "body": {"content": [{"endIndex": end_index}]},
        }
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(drive_service=drive_svc, docs_service=docs_svc, doc_cache=MagicMock())

    @staticmethod
    def _batch_update_execute(docs_svc):
        return docs_svc.documents.return_value.batchUpdate.return_value.execute

    @staticmethod
    def _fail_content_write(docs_svc, exc):
        """The clear succeeds; the content batchUpdate after it raises `exc`."""
        calls = []

        def execute(**kwargs):
            calls.append(kwargs)
            if len(calls) > 1:
                raise exc
            return {}

        docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = execute

    async def _write(self, ctx, content="<p>New</p>"):
        return await _docs_tools["write_doc_content"](doc_id="doc1", content=content, ctx=ctx)

    async def test_backup_made_before_clear_and_deleted_after_success(self):
        drive_svc, docs_svc = self._make_services()
        order = []
        drive_svc.files.return_value.copy.return_value.execute.side_effect = lambda **kw: (
            order.append("copy") or self._backup()
        )
        self._batch_update_execute(docs_svc).side_effect = lambda **kw: order.append("edit") or {}
        result = await self._write(self._ctx(drive_svc, docs_svc))

        assert order[0] == "copy"
        drive_svc.files.return_value.copy.assert_called_once_with(
            fileId="doc1",
            body={"name": "My Doc (backup before replace)"},
            fields="id,name,parents,capabilities(canDelete)",
            supportsAllDrives=True,
        )
        drive_svc.files.return_value.delete.assert_called_once_with(
            fileId="backup1", supportsAllDrives=True
        )
        assert result == {"docId": "doc1", "web_link": "https://example.com"}

    async def test_backup_folder_marked_dirty_after_the_copy_and_after_its_removal(self):
        # #1030: the copy lands next to the doc and is then removed, so a listing of
        # that folder read in between would still show the removed copy.
        drive_svc, docs_svc = self._make_services(backup={**self._backup(), "parents": ["parent1"]})
        order = []
        drive_svc.files.return_value.copy.return_value.execute.side_effect = lambda **kw: (
            order.append("copy") or {**self._backup(), "parents": ["parent1"]}
        )
        drive_svc.files.return_value.delete.return_value.execute.side_effect = lambda **kw: (
            order.append("delete") or {}
        )
        ctx = self._ctx(drive_svc, docs_svc)
        folder_cache = ctx.request_context.lifespan_context.drive_folder_cache
        folder_cache.mark_dirty.side_effect = lambda folder_id: order.append(f"dirty {folder_id}")

        await self._write(ctx)

        assert order == ["copy", "dirty parent1", "delete", "dirty parent1"]
        folder_cache.mark_all_dirty.assert_not_called()

    async def test_failed_backup_copy_marks_every_folder_dirty(self):
        # The copy may have been made with its response lost, and only that
        # response names its folder.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = TimeoutError(
            "timed out"
        )
        ctx = self._ctx(drive_svc, docs_svc)
        await self._write(ctx)
        ctx.request_context.lifespan_context.drive_folder_cache.mark_all_dirty.assert_called()

    @pytest.mark.parametrize("error", [_quota_http_error, _other_403_error])
    async def test_rejected_backup_copy_invalidates_nothing(self, error):
        # A 4xx copy made nothing, so there's no listing to invalidate (PR #1264
        # QA round 1): a quota or permission refusal mustn't clear every folder.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = error()
        ctx = self._ctx(drive_svc, docs_svc)
        await self._write(ctx)
        folder_cache = ctx.request_context.lifespan_context.drive_folder_cache
        folder_cache.mark_all_dirty.assert_not_called()
        folder_cache.mark_dirty.assert_not_called()

    async def test_backup_trashed_when_it_cannot_be_deleted(self):
        # A Content manager on a Shared Drive can trash but not delete (#876).
        backup = self._backup(can_delete=False)
        drive_svc, docs_svc = self._make_services(backup=backup)
        await self._write(self._ctx(drive_svc, docs_svc))
        drive_svc.files.return_value.delete.assert_not_called()
        drive_svc.files.return_value.update.assert_called_once_with(
            fileId="backup1", body={"trashed": True}, fields="id", supportsAllDrives=True
        )

    async def test_backup_removal_failure_is_a_warning_not_an_error(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.delete.return_value.execute.side_effect = RuntimeError("gone")
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert "error" not in result
        assert result["warning"] == (
            "Couldn't remove the backup copy backup1 made before replacing the content; "
            "delete it manually (gone)."
        )

    async def test_empty_doc_is_not_backed_up(self):
        drive_svc, docs_svc = self._make_services(end_index=2)
        result = await self._write(self._ctx(drive_svc, docs_svc))
        drive_svc.files.return_value.copy.assert_not_called()
        assert "error" not in result

    async def test_failed_copy_leaves_doc_unchanged(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = _other_403_error()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await self._write(ctx)
        assert result["docId"] == "doc1"
        assert result["error"].startswith(
            "Couldn't back up the document before replacing its content, so it was left unchanged"
        )
        self._batch_update_execute(docs_svc).assert_not_called()
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_not_called()

    async def test_quota_error_on_copy_replaces_without_backup(self):
        # A service account writing into a user-owned doc can't own the copy, and
        # write_doc_content is the documented way to write such a doc.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result == {
            "docId": "doc1",
            "web_link": "https://example.com",
            "warning": (
                "The document's previous content was replaced without a backup copy "
                "(there's no Drive storage quota left for the copy)."
            ),
        }
        drive_svc.files.return_value.delete.assert_not_called()

    async def test_quota_error_on_copy_then_failed_write_says_no_backup(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        self._fail_content_write(docs_svc, RuntimeError("edit boom"))
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result == {
            "error": (
                "doc edit failed: edit boom. The document's previous content was cleared "
                "first and couldn't be backed up (there's no Drive storage quota left "
                "for the copy), so the document may be empty or partly written."
            ),
            "docId": "doc1",
        }

    @staticmethod
    def _reason_error(status, reason):
        return HttpError(
            resp=MagicMock(status=status),
            content=json.dumps({"error": {"errors": [{"reason": reason}]}}).encode(),
        )

    # #1018: the reason string for the folder case was measured live (2026-10-14):
    # files.copy by a caller who can edit the doc but only read or comment on its
    # folder (My Drive or Shared Drive) returns 403 insufficientFilePermissions.
    _FALLBACK_REASONS = (
        (
            "insufficientFilePermissions",
            "this account can't add a file to the document's folder",
        ),
        ("teamDriveFileLimitExceeded", "the document's Shared Drive is at its item limit"),
        ("numChildrenInNonRootLimitExceeded", "the document's folder is at its item limit"),
    )

    @pytest.mark.parametrize(("reason", "why"), _FALLBACK_REASONS)
    async def test_permission_or_limit_error_on_copy_replaces_with_warning(self, reason, why):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result == {
            "docId": "doc1",
            "web_link": "https://example.com",
            "warning": (
                f"The document's previous content was replaced without a backup copy ({why})."
            ),
        }
        # The clear and the content write both went out.
        assert self._batch_update_execute(docs_svc).call_count == 2
        drive_svc.files.return_value.delete.assert_not_called()

    @pytest.mark.parametrize(("reason", "why"), _FALLBACK_REASONS)
    async def test_permission_or_limit_error_on_copy_then_failed_write_says_no_backup(
        self, reason, why
    ):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        self._fail_content_write(docs_svc, RuntimeError("edit boom"))
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result == {
            "error": (
                f"doc edit failed: edit boom. The document's previous content was cleared "
                f"first and couldn't be backed up ({why}), so the document may be empty "
                f"or partly written."
            ),
            "docId": "doc1",
        }

    @pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
    async def test_rate_limit_403_on_copy_still_refuses(self, reason):
        # Drive returns these as 403s too; they mean "try again", not "can't copy here".
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result["error"].startswith(
            "Couldn't back up the document before replacing its content, so it was left unchanged"
        )
        self._batch_update_execute(docs_svc).assert_not_called()

    async def test_fallback_reason_with_other_status_still_refuses(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            400, "insufficientFilePermissions"
        )
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert "left unchanged" in result["error"]
        self._batch_update_execute(docs_svc).assert_not_called()

    async def test_no_backup_and_doc_emptied_during_copy_has_no_warning(self):
        # Nothing was cleared, so nothing was lost without a backup.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "insufficientFilePermissions"
        )
        docs_svc.documents.return_value.get.return_value.execute.side_effect = [
            {"title": "My Doc", "body": {"content": [{"endIndex": 50}]}},
            {"title": "My Doc", "body": {"content": [{"endIndex": 2}]}},
        ]
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result == {"docId": "doc1", "web_link": "https://example.com"}

    async def test_update_doc_from_file_no_backup_warning(self, tmp_path):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "insufficientFilePermissions"
        )
        src = tmp_path / "doc.md"
        src.write_text("# New\n", encoding="utf-8")
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(src), ctx=self._ctx(drive_svc, docs_svc)
        )
        assert result["warning"] == (
            "The document's previous content was replaced without a backup copy "
            "(this account can't add a file to the document's folder)."
        )

    # #1035: cannotCopyFile was measured live (2026-10-14): a writer on a doc whose
    # owner set downloadRestrictions' restrictedForWriters. These replace without a
    # backup only with allow_no_backup=True.
    _OPT_IN_REASONS = (
        ("cannotCopyFile", "the document's sharing settings don't allow this account to copy it"),
        (
            "activeItemCreationLimitExceeded",
            "this account is at its limit for creating Drive items",
        ),
    )

    @pytest.mark.parametrize(("reason", "why"), _OPT_IN_REASONS)
    async def test_opt_in_reason_refuses_by_default_and_names_the_flag(self, reason, why):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        ctx = self._ctx(drive_svc, docs_svc)
        result = await self._write(ctx)
        assert result == {
            "error": (
                f"Couldn't back up the document before replacing its content ({why}), so "
                f"it was left unchanged. To replace it without a backup, retry with "
                f"allow_no_backup=True. Its previous content then can't be recovered with "
                f"export_revision: Docs merges the revision from before the replace into "
                f"the replace's own."
            ),
            "docId": "doc1",
        }
        self._batch_update_execute(docs_svc).assert_not_called()
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_not_called()
        # Never backed up another way (export or download).
        drive_svc.files.return_value.export.assert_not_called()
        drive_svc.files.return_value.export_media.assert_not_called()
        drive_svc.files.return_value.get_media.assert_not_called()

    @staticmethod
    def _capabilities(drive_svc, can_edit=None, error=None):
        """files.get answers a capabilities read with `can_edit` (or raises
        `error`), and the webViewLink lookup as usual."""

        def get(**kwargs):
            request = MagicMock()
            if "capabilities" in kwargs.get("fields", ""):
                if error is not None:
                    request.execute.side_effect = error
                else:
                    request.execute.return_value = {"capabilities": {"canEdit": can_edit}}
            else:
                request.execute.return_value = {"webViewLink": "https://example.com"}
            return request

        drive_svc.files.return_value.get.side_effect = get

    @pytest.mark.parametrize("allow_no_backup", [False, True])
    @pytest.mark.parametrize(("reason", "why"), _OPT_IN_REASONS)
    async def test_opt_in_reason_for_non_editor_says_it_cannot_edit(
        self, reason, why, allow_no_backup
    ):
        # PR #1042 QA round 1: a reader gets cannotCopyFile under
        # copyRequiresWriterPermission, and the flag can't help it.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        self._capabilities(drive_svc, can_edit=False)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1", content="<p>New</p>", allow_no_backup=allow_no_backup, ctx=ctx
        )
        assert result == {
            "error": (
                f"This account can't edit the document, so it was left unchanged "
                f"(Drive also refused the backup copy: {why})."
            ),
            "docId": "doc1",
        }
        self._batch_update_execute(docs_svc).assert_not_called()
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_not_called()

    @pytest.mark.parametrize("allow_no_backup", [False, True])
    async def test_opt_in_reason_for_editor_follows_the_flag(self, allow_no_backup):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "cannotCopyFile"
        )
        self._capabilities(drive_svc, can_edit=True)
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=allow_no_backup,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        if allow_no_backup:
            assert "warning" in result and "error" not in result
        else:
            assert "retry with allow_no_backup=True" in result["error"]

    async def test_unreadable_capabilities_fall_back_to_the_flag(self):
        # The clear's own 4xx would still leave the doc unchanged for a non-editor.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "cannotCopyFile"
        )
        self._capabilities(drive_svc, error=self._reason_error(500, "backendError"))
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert "retry with allow_no_backup=True" in result["error"]

    async def test_capabilities_not_read_for_automatic_or_successful_backup(self):
        for side_effect in (None, self._reason_error(403, "insufficientFilePermissions")):
            drive_svc, docs_svc = self._make_services()
            if side_effect is not None:
                drive_svc.files.return_value.copy.return_value.execute.side_effect = side_effect
            await self._write(self._ctx(drive_svc, docs_svc))
            fields = [
                c.kwargs.get("fields") for c in drive_svc.files.return_value.get.call_args_list
            ]
            assert fields == ["webViewLink"]

    @pytest.mark.parametrize(("reason", "why"), _OPT_IN_REASONS)
    async def test_opt_in_reason_with_flag_replaces_with_warning(self, reason, why):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=True,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        assert result == {
            "docId": "doc1",
            "web_link": "https://example.com",
            "warning": (
                f"The document's previous content was replaced without a backup copy ({why})."
            ),
        }
        assert self._batch_update_execute(docs_svc).call_count == 2
        drive_svc.files.return_value.copy.return_value.execute.assert_called_once()
        drive_svc.files.return_value.delete.assert_not_called()

    @pytest.mark.parametrize(("reason", "why"), _OPT_IN_REASONS)
    async def test_opt_in_reason_with_flag_then_failed_write_says_no_backup(self, reason, why):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        self._fail_content_write(docs_svc, RuntimeError("edit boom"))
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=True,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        assert result == {
            "error": (
                f"doc edit failed: edit boom. The document's previous content was cleared "
                f"first and couldn't be backed up ({why}), so the document may be empty "
                f"or partly written."
            ),
            "docId": "doc1",
        }

    async def test_opt_in_reason_with_other_status_still_refuses_with_flag(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            400, "cannotCopyFile"
        )
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=True,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        assert result["error"].startswith(
            "Couldn't back up the document before replacing its content, so it was left unchanged"
        )
        self._batch_update_execute(docs_svc).assert_not_called()

    @pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
    async def test_flag_does_not_widen_to_other_copy_failures(self, reason):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, reason
        )
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=True,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        assert "allow_no_backup" not in result["error"]
        assert result["error"].startswith(
            "Couldn't back up the document before replacing its content, so it was left unchanged"
        )
        self._batch_update_execute(docs_svc).assert_not_called()

    @pytest.mark.parametrize("allow_no_backup", [False, True])
    async def test_flag_does_not_change_automatic_fallback(self, allow_no_backup):
        # #1018's reasons replace without a backup whatever the flag says.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "insufficientFilePermissions"
        )
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=allow_no_backup,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        assert result["warning"] == (
            "The document's previous content was replaced without a backup copy "
            "(this account can't add a file to the document's folder)."
        )

    async def test_flag_does_not_skip_a_backup_that_succeeds(self):
        drive_svc, docs_svc = self._make_services()
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="<p>New</p>",
            allow_no_backup=True,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        assert "warning" not in result
        drive_svc.files.return_value.copy.return_value.execute.assert_called_once()
        drive_svc.files.return_value.delete.return_value.execute.assert_called_once()

    @pytest.mark.parametrize("allow_no_backup", [False, True])
    async def test_update_doc_from_file_passes_allow_no_backup(self, tmp_path, allow_no_backup):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "cannotCopyFile"
        )
        src = tmp_path / "doc.md"
        src.write_text("# New\n", encoding="utf-8")
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1",
            local_path=str(src),
            allow_no_backup=allow_no_backup,
            ctx=self._ctx(drive_svc, docs_svc),
        )
        if allow_no_backup:
            assert result["warning"] == (
                "The document's previous content was replaced without a backup copy "
                "(the document's sharing settings don't allow this account to copy it)."
            )
        else:
            assert "retry with allow_no_backup=True" in result["error"]
            self._batch_update_execute(docs_svc).assert_not_called()

    async def test_failed_write_after_clear_keeps_backup_and_names_it(self):
        drive_svc, docs_svc = self._make_services()
        self._fail_content_write(docs_svc, RuntimeError("edit boom"))
        ctx = self._ctx(drive_svc, docs_svc)
        result = await self._write(ctx)
        assert result == {
            "error": (
                "doc edit failed: edit boom. The document's previous content was cleared "
                "first; a full copy of it is kept as 'My Doc (backup before replace)' "
                "(backupId)."
            ),
            "docId": "doc1",
            "backupId": "backup1",
        }
        drive_svc.files.return_value.delete.assert_not_called()
        drive_svc.files.return_value.update.assert_not_called()
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_called_with("doc1")

    async def test_failed_write_with_images_keeps_image_outcomes_and_backup(self):
        drive_svc, docs_svc = self._make_services()
        self._fail_content_write(docs_svc, RuntimeError("edit boom"))
        result = await self._write(
            self._ctx(drive_svc, docs_svc), content='<img src="https://example.com/a.png">'
        )
        assert result["backupId"] == "backup1"
        assert result["images"] == [{"src": "https://example.com/a.png"}]

    async def test_rejected_clear_discards_backup_and_reports_unchanged(self):
        drive_svc, docs_svc = self._make_services()
        self._batch_update_execute(docs_svc).side_effect = _other_403_error()
        ctx = self._ctx(drive_svc, docs_svc)
        result = await self._write(ctx)
        assert result["docId"] == "doc1"
        assert result["error"].startswith("Couldn't clear the document, so it was left unchanged")
        assert "backupId" not in result
        drive_svc.files.return_value.delete.assert_called_once_with(
            fileId="backup1", supportsAllDrives=True
        )
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_not_called()

    async def test_rejected_clear_reports_backup_removal_failure(self):
        drive_svc, docs_svc = self._make_services()
        self._batch_update_execute(docs_svc).side_effect = _other_403_error()
        drive_svc.files.return_value.delete.return_value.execute.side_effect = RuntimeError("gone")
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result["error"].startswith("Couldn't clear the document")
        assert result["warning"] == (
            "Couldn't remove the backup copy backup1 made before replacing the content; "
            "delete it manually (gone)."
        )

    async def test_non_http_clear_failure_keeps_backup(self):
        # A transport error doesn't say whether the clear landed, so the backup stays.
        drive_svc, docs_svc = self._make_services()
        self._batch_update_execute(docs_svc).side_effect = TimeoutError("timed out")
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result["backupId"] == "backup1"
        drive_svc.files.return_value.delete.assert_not_called()

    async def test_cancelled_after_clear_keeps_backup_and_logs_it(self):
        drive_svc, docs_svc = self._make_services()
        started, release = threading.Event(), threading.Event()
        calls = []

        def execute(**kwargs):
            calls.append(kwargs)
            if len(calls) > 1:  # the content write, after the clear
                started.set()
                release.wait(5)
            return {}

        self._batch_update_execute(docs_svc).side_effect = execute
        ctx = self._ctx(drive_svc, docs_svc)
        with patch.object(content_module, "logger") as mock_logger:
            async with anyio.create_task_group() as tg:
                tg.start_soon(partial(self._write, ctx))
                await anyio.to_thread.run_sync(started.wait, 5)
                tg.cancel_scope.cancel()
                release.set()
        drive_svc.files.return_value.delete.assert_not_called()
        mock_logger.warning.assert_called_once_with(
            "Replacing doc %s was cancelled; kept its backup copy %s", "doc1", "backup1"
        )

    async def test_cancelled_during_revoke_after_full_replace_discards_backup(self):
        # PR #1029 QA round 1 (reproduced live): a cancellation held off by the
        # image-share revoke lands after the new content fully landed. The doc was
        # replaced, so the backup is removed, not kept as if the write were partial.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webViewLink": "https://example.com",
            "webContentLink": "https://drive.google.com/uc?id=file1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        started, release = threading.Event(), threading.Event()

        def revoke(**kwargs):
            started.set()
            release.wait(5)
            return {}

        drive_svc.permissions.return_value.delete.return_value.execute.side_effect = revoke
        ctx = self._ctx(drive_svc, docs_svc)
        with patch.object(content_module, "logger") as mock_logger:
            async with anyio.create_task_group() as tg:
                tg.start_soon(partial(self._write, ctx, '<img src="drive:file1">'))
                await anyio.to_thread.run_sync(started.wait, 5)
                tg.cancel_scope.cancel()
                release.set()
        drive_svc.files.return_value.delete.assert_called_once_with(
            fileId="backup1", supportsAllDrives=True
        )
        kept = [c for c in mock_logger.warning.call_args_list if "kept its backup" in c.args[0]]
        assert kept == []

    async def test_cancelled_mid_clear_marks_doc_dirty_after_clear_lands(self):
        # #907: the clear's worker thread still commits after the cancellation
        # unwinds, so the doc is marked dirty again once it does.
        drive_svc, docs_svc = self._make_services()
        started, release, landed = threading.Event(), threading.Event(), []

        def execute(**kwargs):
            started.set()
            release.wait(5)
            landed.append(True)
            return {}

        self._batch_update_execute(docs_svc).side_effect = execute
        ctx = self._ctx(drive_svc, docs_svc)
        dirty_after_landing = []
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.side_effect = lambda doc_id: (
            dirty_after_landing.append((doc_id, bool(landed)))
        )
        async with anyio.create_task_group() as tg:
            tg.start_soon(partial(self._write, ctx))
            await anyio.to_thread.run_sync(started.wait, 5)
            tg.cancel_scope.cancel()
        assert ("doc1", True) not in dirty_after_landing
        release.set()
        with anyio.fail_after(2):
            while ("doc1", True) not in dirty_after_landing:
                await anyio.sleep(0.01)

    async def test_local_image_upload_marks_folder_dirty(self, tmp_path):
        # #666: the image is uploaded into the server's default folder, whose
        # listing then changed.
        img = tmp_path / "pixel.png"
        img.write_bytes(_make_png_bytes(2, 2))
        drive_svc, docs_svc = self._make_services(end_index=2)
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "up1",
            "webContentLink": "https://drive.google.com/uc?id=up1",
        }
        drive_svc.permissions.return_value.create.return_value.execute.return_value = {
            "id": "perm1"
        }
        ctx = _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            doc_cache=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id="folder1",
        )
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1", content=f"![Pixel]({img})", content_format="markdown", ctx=ctx
        )
        assert result["images"] == [{"src": str(img), "fileId": "up1", "shared": False}]
        ctx.request_context.lifespan_context.drive_folder_cache.mark_dirty.assert_called_once_with(
            "folder1"
        )

    async def test_update_doc_from_file_failed_write_names_backup(self, tmp_path):
        source = tmp_path / "doc.md"
        source.write_text("# New\n")
        drive_svc, docs_svc = self._make_services()
        self._fail_content_write(docs_svc, RuntimeError("edit boom"))
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc1", local_path=str(source), ctx=self._ctx(drive_svc, docs_svc)
        )
        assert result["backupId"] == "backup1"
        assert result["error"].startswith("doc edit failed: edit boom. ")

    # PR #1017 QA round 1.

    @staticmethod
    def _http_error(status):
        return HttpError(resp=MagicMock(status=status), content=b'{"error": {"message": "x"}}')

    async def test_5xx_on_clear_keeps_backup_and_says_may_have_cleared(self):
        # A 5xx doesn't say whether the clear ran; Sky reproduced one that had.
        drive_svc, docs_svc = self._make_services()
        self._batch_update_execute(docs_svc).side_effect = self._http_error(503)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await self._write(ctx)
        assert result["backupId"] == "backup1"
        assert "may have been cleared" in result["error"]
        drive_svc.files.return_value.delete.assert_not_called()
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_429_on_clear_is_rejected(self):
        drive_svc, docs_svc = self._make_services()
        self._batch_update_execute(docs_svc).side_effect = self._http_error(429)
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result["error"].startswith("Couldn't clear the document, so it was left unchanged")
        drive_svc.files.return_value.delete.assert_called_once()

    async def test_non_http_clear_failure_says_may_have_cleared(self):
        drive_svc, docs_svc = self._make_services()
        self._batch_update_execute(docs_svc).side_effect = ConnectionRefusedError()
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result["error"] == (
            "doc edit failed: ConnectionRefusedError. The document's previous content may "
            "have been cleared; a full copy of it is kept as "
            "'My Doc (backup before replace)' (backupId)."
        )

    async def test_clear_uses_end_index_read_after_the_copy(self):
        # The doc grew while the copy ran: the clear must cover the new text too.
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = [
            {"title": "My Doc", "body": {"content": [{"endIndex": 50}]}},
            {"title": "My Doc", "body": {"content": [{"endIndex": 80}]}},
        ]
        await self._write(self._ctx(drive_svc, docs_svc))
        clear = docs_svc.documents.return_value.batchUpdate.call_args_list[0].kwargs["body"]
        assert clear["requests"][-1]["deleteContentRange"]["range"] == {
            "startIndex": 1,
            "endIndex": 79,
        }

    async def test_doc_emptied_during_copy_is_not_cleared_but_backup_still_named(self):
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = [
            {"title": "My Doc", "body": {"content": [{"endIndex": 50}]}},
            {"title": "My Doc", "body": {"content": [{"endIndex": 2}]}},
        ]
        self._batch_update_execute(docs_svc).side_effect = RuntimeError("edit boom")
        result = await self._write(self._ctx(drive_svc, docs_svc))
        # Only the content write was sent, no clear.
        assert self._batch_update_execute(docs_svc).call_count == 1
        assert result["error"] == (
            "doc edit failed: edit boom. A full copy of the document from before this call "
            "is kept as 'My Doc (backup before replace)' (backupId)."
        )

    async def test_reread_failure_discards_backup_and_leaves_doc_unchanged(self):
        drive_svc, docs_svc = self._make_services()
        docs_svc.documents.return_value.get.return_value.execute.side_effect = [
            {"title": "My Doc", "body": {"content": [{"endIndex": 50}]}},
            RuntimeError("read boom"),
        ]
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result["error"] == (
            "Couldn't clear the document, so it was left unchanged: read boom"
        )
        self._batch_update_execute(docs_svc).assert_not_called()
        drive_svc.files.return_value.delete.assert_called_once()

    async def test_copy_retried_on_429(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = [
            self._http_error(429),
            self._backup(),
        ]
        with patch.object(content_module.anyio, "sleep", new_callable=AsyncMock) as mock_sleep:
            result = await self._write(self._ctx(drive_svc, docs_svc))
        assert "error" not in result
        assert drive_svc.files.return_value.copy.return_value.execute.call_count == 2
        mock_sleep.assert_called_once_with(1)

    async def test_copy_5xx_not_retried_and_names_possible_copy(self):
        # The copy may exist despite the 5xx; a retry would make a second one.
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._http_error(503)
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert drive_svc.files.return_value.copy.return_value.execute.call_count == 1
        assert result["error"].endswith(
            ". A copy named 'My Doc (backup before replace)' may still have been created "
            "next to the document; check for it and delete it"
        )
        self._batch_update_execute(docs_svc).assert_not_called()

    async def test_copy_4xx_does_not_mention_possible_copy(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = _other_403_error()
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert "may still have been created" not in result["error"]

    async def test_copy_timeout_is_bounded_and_names_possible_copy(self):
        drive_svc, docs_svc = self._make_services()
        release = threading.Event()

        def stalled(**kwargs):
            release.wait(5)
            return self._backup()

        drive_svc.files.return_value.copy.return_value.execute.side_effect = stalled
        try:
            with patch.object(content_module, "_BACKUP_COPY_TIMEOUT", 0.2):
                result = await self._write(self._ctx(drive_svc, docs_svc))
        finally:
            release.set()
        assert result["error"].startswith(
            "Couldn't back up the document before replacing its content, so it was left "
            "unchanged: TimeoutError. A copy named"
        )
        self._batch_update_execute(docs_svc).assert_not_called()

    async def test_link_lookup_failure_still_removes_backup_and_dirties_cache(self):
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.get.return_value.execute.side_effect = RuntimeError("get boom")
        ctx = self._ctx(drive_svc, docs_svc)
        with pytest.raises(RuntimeError, match="get boom"):
            await self._write(ctx)
        drive_svc.files.return_value.delete.assert_called_once_with(
            fileId="backup1", supportsAllDrives=True
        )
        # The doc was already replaced (PR #1017 QA round 2).
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_link_lookup_failure_after_no_backup_replace_still_reports_it(self):
        # The content was replaced with no backup; a lookup error alone wouldn't
        # tell the caller the old content is gone (PR #1034 QA round 1).
        drive_svc, docs_svc = self._make_services()
        drive_svc.files.return_value.copy.return_value.execute.side_effect = self._reason_error(
            403, "insufficientFilePermissions"
        )
        lookup_error = RuntimeError("get boom")
        drive_svc.files.return_value.get.return_value.execute.side_effect = lookup_error
        ctx = self._ctx(drive_svc, docs_svc)
        with pytest.raises(RuntimeError) as excinfo:
            await self._write(ctx)
        assert str(excinfo.value) == (
            "The document's previous content was replaced without a backup copy "
            "(this account can't add a file to the document's folder). The new content "
            "was written, but looking up the document's link failed: get boom"
        )
        assert excinfo.value.__cause__ is lookup_error
        ctx.request_context.lifespan_context.doc_cache.mark_dirty.assert_called_once_with("doc1")

    async def test_backup_removal_and_link_lookup_run_together(self):
        drive_svc, docs_svc = self._make_services()
        both = threading.Barrier(2, timeout=5)

        def delete_execute(**kwargs):
            both.wait()
            return {}

        def get_execute(**kwargs):
            both.wait()
            return {"webViewLink": "https://example.com"}

        drive_svc.files.return_value.delete.return_value.execute.side_effect = delete_execute
        drive_svc.files.return_value.get.return_value.execute.side_effect = get_execute
        result = await self._write(self._ctx(drive_svc, docs_svc))
        assert result == {"docId": "doc1", "web_link": "https://example.com"}


class TestConvertBeforeTouchingDoc:
    """#1240: the content is converted (Markdown → HTML → AST → requests) off the
    event loop before a doc is created, read, copied, or cleared, so a conversion
    that raises or is cancelled leaves the doc as it was."""

    def _make_services(self, end_index=50):
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "doc123",
            "name": "Doc",
            "parents": ["folder1"],
            "webViewLink": "https://example.com",
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {
            "webViewLink": "https://example.com"
        }
        drive_svc.files.return_value.copy.return_value.execute.return_value = {
            "id": "backup1",
            "name": "My Doc (backup before replace)",
            "capabilities": {"canDelete": True},
        }
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "title": "My Doc",
            "body": {"content": [{"endIndex": end_index}]},
        }
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            doc_cache=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id=None,
        )

    @staticmethod
    def _assert_untouched(drive_svc, docs_svc):
        docs_svc.documents.return_value.get.return_value.execute.assert_not_called()
        docs_svc.documents.return_value.batchUpdate.return_value.execute.assert_not_called()
        drive_svc.files.return_value.copy.return_value.execute.assert_not_called()
        drive_svc.files.return_value.create.return_value.execute.assert_not_called()

    @staticmethod
    async def _replace(tool, ctx, tmp_path, content="# New\n\ntext\n", **kwargs):
        if tool == "write_doc_content":
            return await _docs_tools[tool](
                doc_id="doc1", content=content, content_format="markdown", ctx=ctx, **kwargs
            )
        src = tmp_path / "notes.md"
        src.write_text(content)
        return await _docs_tools[tool](doc_id="doc1", local_path=str(src), ctx=ctx, **kwargs)

    @pytest.mark.parametrize("tool", ["write_doc_content", "update_doc_from_file"])
    @pytest.mark.parametrize("allow_no_backup", [False, True])
    async def test_conversion_error_leaves_doc_unchanged(self, tool, allow_no_backup, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        boom = RuntimeError("parser broke")
        with (
            patch.object(content_module, "_convert_doc_content", side_effect=boom),
            patch.object(content_module, "logger") as mock_logger,
        ):
            result = await self._replace(tool, ctx, tmp_path, allow_no_backup=allow_no_backup)
        # Returned, not raised, so the traceback is logged instead (PR #1296 QA round 1).
        assert mock_logger.error.call_args.kwargs["exc_info"] is boom
        assert result == {
            "error": (
                "Couldn't convert the content, so the document was left unchanged: "
                "RuntimeError: parser broke"
            ),
            "docId": "doc1",
        }
        self._assert_untouched(drive_svc, docs_svc)

    @pytest.mark.parametrize("tool", ["write_doc_content", "update_doc_from_file"])
    async def test_cancelled_conversion_leaves_doc_unchanged(self, tool, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        started, release = threading.Event(), threading.Event()
        real_convert = content_module._convert_doc_content

        def blocking_convert(*args):
            started.set()
            release.wait(5)
            return real_convert(*args)

        with patch.object(content_module, "_convert_doc_content", side_effect=blocking_convert):
            async with anyio.create_task_group() as tg:
                tg.start_soon(partial(self._replace, tool, ctx, tmp_path))
                await anyio.to_thread.run_sync(started.wait, 5)
                tg.cancel_scope.cancel()
                release.set()
        self._assert_untouched(drive_svc, docs_svc)

    @pytest.mark.parametrize("tool", ["create_doc", "create_doc_from_file"])
    async def test_conversion_error_creates_no_doc(self, tool, tmp_path):
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        boom = RuntimeError("parser broke")
        with (
            patch.object(content_module, "_convert_doc_content", side_effect=boom),
            patch.object(content_module, "logger") as mock_logger,
        ):
            if tool == "create_doc":
                result = await _docs_tools[tool](
                    title="Doc", content="# Hi\n", content_format="markdown", ctx=ctx
                )
            else:
                src = tmp_path / "notes.md"
                src.write_text("# Hi\n")
                result = await _docs_tools[tool](local_path=str(src), ctx=ctx)
        assert result == {
            "error": (
                "Couldn't convert the content, so no document was created: "
                "RuntimeError: parser broke"
            )
        }
        assert mock_logger.error.call_args.kwargs["exc_info"] is boom
        self._assert_untouched(drive_svc, docs_svc)

    @pytest.mark.parametrize("content_format", ["markdown", "html"])
    async def test_whole_conversion_runs_off_the_event_loop(self, content_format, tmp_path):
        # Kit's #1240 comment: html_to_ast and the request walk ran on the loop too.
        drive_svc, docs_svc = self._make_services(end_index=2)
        ctx = self._ctx(drive_svc, docs_svc)
        loop_thread = threading.get_ident()
        threads = []
        real = {
            name: getattr(content_module, name)
            for name in ("_md_to_html", "html_to_ast", "ast_to_requests")
        }

        def recording(name):
            def call(*args, **kwargs):
                threads.append((name, threading.get_ident()))
                return real[name](*args, **kwargs)

            return call

        content = "# Hi\n\ntext\n" if content_format == "markdown" else "<h1>Hi</h1><p>text</p>"
        with (
            patch.object(content_module, "_md_to_html", recording("_md_to_html")),
            patch.object(content_module, "html_to_ast", recording("html_to_ast")),
            patch.object(content_module, "ast_to_requests", recording("ast_to_requests")),
        ):
            result = await _docs_tools["write_doc_content"](
                doc_id="doc1", content=content, content_format=content_format, ctx=ctx
            )
        assert "error" not in result
        expected = {"html_to_ast", "ast_to_requests"}
        if content_format == "markdown":
            expected.add("_md_to_html")
        assert {name for name, _ in threads} == expected
        assert all(ident != loop_thread for _, ident in threads)

    async def test_unresolved_images_requests_match_their_fallback_text(self, tmp_path):
        # Requests are built before the images resolve, with a placeholder for every
        # image; an unresolved one's request is replaced by its fallback text, which
        # carries its link, and its own link request is dropped (#1099). The result
        # must be what ast_to_requests builds with every image, with exactly that
        # swap made at each unresolved image's position.
        drive_svc, docs_svc = self._make_services()
        ctx = self._ctx(drive_svc, docs_svc)
        missing = str(tmp_path / "missing.png")
        good = "https://example.com/good.png"
        content = (
            f"Before\n\n[![Bad]({missing})](https://example.com/bad-link)\n\n"
            f"[![Good]({good})](https://example.com/good-link)\n\n![Bad2]({missing})\n\nAfter"
        )
        result = await _docs_tools["create_doc"](
            title="Doc", content=content, content_format="markdown", ctx=ctx
        )
        assert [("error" in o) for o in result["images"]] == [True, False, True]
        assert [o.get("fallback_text") for o in result["images"]] == ["Bad", None, "Bad2"]

        nodes = html_to_ast(_md_to_html(content))
        images = extract_images(nodes)
        uris = {id(img): f"urn:test:{i}" for i, img in enumerate(images)}
        links: dict[int, dict] = {}
        built, _ = ast_to_requests(nodes, 1, uris, image_links=links)
        bad = {uris[id(images[0])]: images[0], uris[id(images[2])]: images[2]}
        bad_links = {
            id(links[id(r)])
            for r in built
            if r.get("insertInlineImage", {}).get("uri") in bad and id(r) in links
        }
        expected = []
        for r in built:
            uri = r.get("insertInlineImage", {}).get("uri")
            if id(r) in bad_links:
                continue
            if uri in bad:
                position = r["insertInlineImage"]["location"]["index"]
                expected.extend(image_fallback_requests(bad[uri], position))
            elif uri is not None:
                expected.append({"insertInlineImage": {**r["insertInlineImage"], "uri": good}})
            else:
                expected.append(r)
        sent = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        assert sent == expected
        links_sent = [
            r["updateTextStyle"]["textStyle"]["link"]["url"]
            for r in sent
            if "link" in r.get("updateTextStyle", {}).get("textStyle", {})
        ]
        # The bad image's link now sits on its fallback text, once.
        assert links_sent.count("https://example.com/bad-link") == 1
        assert "https://example.com/good-link" in links_sent


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

    async def test_courier_new_paragraph_soft_breaks_restored_to_newlines(self):
        # #731 (found in QA on #719's own PR): _collect_doc_paragraphs (which
        # find_in_doc uses) yielded a Courier-New run's content unmodified —
        # a multi-line code block written by #719's fix leaked a literal "\v"
        # (U+000B) into matched_text/context instead of the original "\n".
        style = {"weightedFontFamily": {"fontFamily": "Courier New"}}
        para = {
            "elements": [
                {
                    "startIndex": 1,
                    "textRun": {"content": "line1\vneedle\vline3\n", "textStyle": style},
                }
            ]
        }
        doc = {"body": {"content": [{"startIndex": 1, "endIndex": 19, "paragraph": para}]}}
        ctx = self._ctx(self._docs_svc(doc))

        results = await _docs_tools["find_in_doc"](doc_id="doc1", query="needle", ctx=ctx)

        assert len(results) == 1
        assert "\v" not in results[0]["context"]
        assert results[0]["context"] == "line1\nneedle\nline3"

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
        p0_start, _p0_text = paragraphs[0]
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


class TestFailedInsertImageRequestIndex:
    """#510: matched against the structured response (status + JSON body's
    error.message), not HttpError's own display formatting."""

    @staticmethod
    def _error(status: int, content: bytes) -> HttpError:
        resp = MagicMock()
        resp.status = status
        resp.reason = "Bad Request"
        return HttpError(resp=resp, content=content)

    def test_extracts_index_from_json_body(self):
        # Body shape as captured live against the real Docs API.
        body = {
            "error": {
                "code": 400,
                "message": "Invalid requests[28].insertInlineImage: There was a problem "
                "retrieving the image.",
                "status": "INVALID_ARGUMENT",
            }
        }
        assert _failed_insert_image_request_index(self._error(400, json.dumps(body).encode())) == 28

    def test_independent_of_httperror_display_format(self):
        body = {"error": {"message": "Invalid requests[3].insertInlineImage: nope"}}
        error = self._error(400, json.dumps(body).encode())
        with patch.object(HttpError, "__str__", lambda self: "reformatted"):
            assert _failed_insert_image_request_index(error) == 3

    def test_non_400_status_is_none(self):
        body = {"error": {"message": "Invalid requests[3].insertInlineImage: nope"}}
        error = self._error(500, json.dumps(body).encode())
        assert _failed_insert_image_request_index(error) is None

    def test_other_request_kind_is_none(self):
        body = {"error": {"message": "Invalid requests[3].insertText: bad index"}}
        error = self._error(400, json.dumps(body).encode())
        assert _failed_insert_image_request_index(error) is None

    @pytest.mark.parametrize(
        "content",
        [b"not json", b"[]", b'{"error": "flat"}', b"{}"],
    )
    def test_malformed_body_is_none(self, content):
        assert _failed_insert_image_request_index(self._error(400, content)) is None

    def test_caller_message_drops_internal_index_and_wrapper(self):
        body = {
            "error": {
                "message": "Invalid requests[2].insertInlineImage: There was a problem "
                "retrieving the image."
            }
        }
        message = _failed_insert_image_message(self._error(400, json.dumps(body).encode()))
        assert message == "insertInlineImage: There was a problem retrieving the image."

    def test_caller_message_still_rewrites_too_large(self):
        body = {
            "error": {
                "message": "Invalid requests[0].insertInlineImage: The provided image is too large."
            }
        }
        message = _failed_insert_image_message(self._error(400, json.dumps(body).encode()))
        assert message.startswith("insertInlineImage: The provided image is too large.")
        assert "25 megapixels" in message


class TestPositionalInsertTailStart:
    def test_ast_to_requests_puts_every_positional_insert_in_the_tail(self):
        # The invariant _apply_doc_content's split relies on (#510 QA round 1):
        # ast_to_requests emits nothing after its insertTable/insertInlineImage
        # pass, so the kind-based scan finds every such request. (The retry also
        # fails safe if this ever breaks — see
        # test_image_outside_insert_tail_falls_back_to_whole_list_retries.)
        md = (
            "# H\n\n![A](https://example.com/a.png)\n\n- one\n    - two\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n> quote ![B](https://example.com/b.png)\n\nEnd"
        )
        nodes = html_to_ast(_md_to_html(md))
        uris = {id(img): img.src for img in extract_images(nodes)}
        requests, _ = ast_to_requests(nodes, start_index=1, image_uris=uris)
        tail_start = _positional_insert_tail_start(requests)
        positional = [
            i for i, r in enumerate(requests) if "insertTable" in r or "insertInlineImage" in r
        ]
        assert len(positional) == 3
        assert all(i >= tail_start for i in positional)

    def test_tail_of_tables_and_images(self):
        requests = [
            {"insertText": {}},
            {"updateTextStyle": {}},
            {"insertInlineImage": {}},
            {"insertTable": {}},
            {"insertInlineImage": {}},
        ]
        assert _positional_insert_tail_start(requests) == 2

    @staticmethod
    def _link(start: int) -> dict:
        return {
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": start + 1},
                "textStyle": {"link": {"url": "https://t"}},
                "fields": "link",
            }
        }

    def test_image_link_request_stays_in_the_tail(self):
        # #977: a linked image's own link request, recorded in image_links,
        # counts as part of the tail.
        insert = {"insertInlineImage": {"location": {"index": 5}}}
        link = self._link(5)
        requests = [
            {"insertText": {}},
            {"updateTextStyle": {}},
            {"insertTable": {"location": {"index": 9}}},
            insert,
            link,
            {"insertInlineImage": {"location": {"index": 2}}},
        ]
        assert _positional_insert_tail_start(requests, {id(insert): link}) == 2

    def test_unrecorded_link_request_ends_the_tail(self):
        # Matched by identity, not shape: an identical-looking link request
        # that ast_to_requests didn't record ends the scan.
        insert = {"insertInlineImage": {"location": {"index": 5}}}
        recorded = self._link(5)
        requests = [{"insertText": {}}, insert, self._link(5)]
        assert _positional_insert_tail_start(requests, {id(insert): recorded}) == 3
        assert _positional_insert_tail_start(requests) == 3

    def test_ast_to_requests_records_each_image_link(self):
        md = "[![A](https://x/a.png)](https://t) ![B](https://x/b.png)"
        nodes = html_to_ast(_md_to_html(md))
        uris = {id(img): img.src for img in extract_images(nodes)}
        image_links: dict[int, dict] = {}
        requests, _ = ast_to_requests(nodes, image_uris=uris, image_links=image_links)
        inserts = {r["insertInlineImage"]["uri"]: r for r in requests if "insertInlineImage" in r}
        assert list(image_links) == [id(inserts["https://x/a.png"])]
        link = image_links[id(inserts["https://x/a.png"])]
        assert any(r is link for r in requests)
        assert _positional_insert_tail_start(requests, image_links) == requests.index(
            min(inserts.values(), key=requests.index)
        )

    def test_table_placeholder_delete_stays_in_the_tail(self):
        # #1097: the delete right after an insertTable removes that table's
        # placeholder paragraph, and is part of the positional pass.
        requests = [
            {"insertText": {}},
            {"deleteContentRange": {}},
            {"insertInlineImage": {}},
            {"insertTable": {}},
            {"deleteContentRange": {}},
            {"insertInlineImage": {}},
        ]
        assert _positional_insert_tail_start(requests) == 2

    def test_delete_not_after_a_table_ends_the_tail(self):
        # An isolated bullet run's anchor delete precedes the pass; it's not a
        # placeholder delete.
        requests = [
            {"insertText": {}},
            {"createParagraphBullets": {}},
            {"deleteContentRange": {}},
            {"insertTable": {}},
            {"deleteContentRange": {}},
        ]
        assert _positional_insert_tail_start(requests) == 3

    def test_no_tail(self):
        assert _positional_insert_tail_start([{"insertText": {}}]) == 1

    def test_all_tail(self):
        assert _positional_insert_tail_start([{"insertInlineImage": {}}]) == 0

    def test_empty(self):
        assert _positional_insert_tail_start([]) == 0

    def test_fallback_text_requests_count_as_tail(self):
        # #1099: an image's fallback text takes its place in the tail, so the K>=2
        # split still finds the tail's start.
        fallback = [{"insertText": {}}, {"updateTextStyle": {}}]
        requests = [{"insertText": {}}, *fallback, {"insertInlineImage": {}}]
        assert _positional_insert_tail_start(requests) == 3
        ids = {id(r) for r in fallback}
        assert _positional_insert_tail_start(requests, fallback_ids=ids) == 1


def _uploaded(path: str, folder_id: str, **_kwargs) -> dict:
    """upload_and_share_local_image's result for a local image that uploaded fine."""
    return {
        "uri": f"https://drive.example/{Path(path).name}",
        "file_id": f"file-{Path(path).name}",
        "permission_id": "perm1",
        "created_in": folder_id,
    }


class TestRelativeImagePaths:
    """#1121: a relative image path in a file is relative to that file's folder."""

    def test_relative_path_joined_to_source_dir(self, tmp_path):
        assert _local_image_path("../img/a.png", tmp_path / "docs") == str(
            tmp_path / "docs" / "../img/a.png"
        )

    def test_absolute_path_unchanged(self, tmp_path):
        absolute = str(tmp_path / "a.png")
        assert _local_image_path(absolute, Path("/elsewhere")) == absolute

    def test_no_source_dir_leaves_path_as_written(self):
        assert _local_image_path("img/a.png", None) == "img/a.png"

    async def test_missing_relative_file_names_where_it_looked(self, tmp_path):
        result = await _resolve_image_source(
            MagicMock(), "../a.png", "folder1", source_dir=tmp_path / "docs"
        )
        looked = str(tmp_path / "docs" / "../a.png")
        assert result == {"error": f"No file found at '../a.png' (looked for {looked!r})"}

    async def test_relative_path_goes_through_the_read_check(self, tmp_path):
        # #796: the joined path is what's checked, so a policy refusal reads the same
        # whether or not the file exists.
        refused = content_module.LocalFileAccessError("refused by policy")
        with patch.object(content_module, "check_read", side_effect=refused) as check:
            result = await _resolve_image_source(
                MagicMock(), "a.png", "folder1", source_dir=tmp_path
            )
        assert result == {"error": "refused by policy"}
        check.assert_called_once_with(str(tmp_path / "a.png"))

    @pytest.mark.parametrize("tool", ["create_doc_from_file", "update_doc_from_file"])
    async def test_file_tools_resolve_against_the_file(self, tmp_path, tool, monkeypatch):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "pixel.png").write_bytes(b"png")
        (tmp_path / "docs").mkdir()
        md = tmp_path / "docs" / "README.md"
        md.write_text("Text\n\n![Pixel](../img/pixel.png)\n")
        # The server's working directory is somewhere else entirely.
        monkeypatch.chdir("/")

        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "doc1",
            "name": "README",
            "parents": ["folder1"],
        }
        drive_svc.files.return_value.get.return_value.execute.return_value = {"parents": ["p1"]}
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "body": {"content": [{"endIndex": 2}]}
        }
        ctx = _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            doc_cache=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id="folder1",
        )
        upload = AsyncMock(side_effect=lambda _svc, path, folder, **kw: _uploaded(path, folder))
        with patch.object(content_module, "upload_and_share_local_image", upload):
            kwargs = {"doc_id": "doc1"} if tool == "update_doc_from_file" else {}
            result = await _docs_tools[tool](local_path=str(md), ctx=ctx, **kwargs)

        assert "error" not in result
        [entry] = result["images"]
        assert entry["src"] == "../img/pixel.png"
        assert "error" not in entry
        uploaded_path = upload.call_args.args[1]
        assert Path(uploaded_path).resolve() == (tmp_path / "img" / "pixel.png").resolve()


class TestReplaceImageFolder:
    """#1139: write_doc_content/update_doc_from_file upload a local image to folder_id,
    else the server's default folder, else the doc's own folder, and refuse before
    touching the doc when none is known."""

    def _services(self, parents=None):
        drive_svc = MagicMock()
        metadata = {"webViewLink": "https://example.com"}
        if parents is not None:
            metadata["parents"] = parents
        drive_svc.files.return_value.get.return_value.execute.return_value = metadata
        docs_svc = MagicMock()
        docs_svc.documents.return_value.get.return_value.execute.return_value = {
            "body": {"content": [{"endIndex": 50}]}
        }
        return drive_svc, docs_svc

    def _ctx(self, drive_svc, docs_svc, folder_id=None):
        return _make_ctx(
            drive_service=drive_svc,
            docs_service=docs_svc,
            doc_cache=MagicMock(),
            drive_folder_cache=MagicMock(),
            folder_id=folder_id,
        )

    def _parents_lookups(self, drive_svc) -> list:
        return [
            c
            for c in drive_svc.files.return_value.get.call_args_list
            if c.kwargs.get("fields") == "parents"
        ]

    async def _replace(self, tool, tmp_path, ctx, **kwargs):
        img = tmp_path / "pic.png"
        img.write_bytes(b"png")
        md = tmp_path / "doc.md"
        md.write_text("![Pic](pic.png)\n")
        if tool == "update_doc_from_file":
            return await _docs_tools[tool](doc_id="doc1", local_path=str(md), ctx=ctx, **kwargs)
        return await _docs_tools[tool](
            doc_id="doc1", content=f"![Pic]({img})", content_format="markdown", ctx=ctx, **kwargs
        )

    @pytest.mark.parametrize("tool", ["write_doc_content", "update_doc_from_file"])
    async def test_folder_id_wins(self, tmp_path, tool):
        drive_svc, docs_svc = self._services(parents=["docfolder"])
        ctx = self._ctx(drive_svc, docs_svc, folder_id="default")
        upload = AsyncMock(side_effect=lambda _svc, path, folder, **kw: _uploaded(path, folder))
        with patch.object(content_module, "upload_and_share_local_image", upload):
            result = await self._replace(tool, tmp_path, ctx, folder_id="mine")
        assert "error" not in result["images"][0]
        assert upload.call_args.args[2] == "mine"
        assert self._parents_lookups(drive_svc) == []

    @pytest.mark.parametrize("tool", ["write_doc_content", "update_doc_from_file"])
    async def test_server_default_before_doc_folder(self, tmp_path, tool):
        drive_svc, docs_svc = self._services(parents=["docfolder"])
        ctx = self._ctx(drive_svc, docs_svc, folder_id="default")
        upload = AsyncMock(side_effect=lambda _svc, path, folder, **kw: _uploaded(path, folder))
        with patch.object(content_module, "upload_and_share_local_image", upload):
            await self._replace(tool, tmp_path, ctx)
        assert upload.call_args.args[2] == "default"
        assert self._parents_lookups(drive_svc) == []

    @pytest.mark.parametrize("tool", ["write_doc_content", "update_doc_from_file"])
    async def test_doc_folder_when_nothing_else(self, tmp_path, tool):
        drive_svc, docs_svc = self._services(parents=["docfolder"])
        ctx = self._ctx(drive_svc, docs_svc)
        upload = AsyncMock(side_effect=lambda _svc, path, folder, **kw: _uploaded(path, folder))
        with patch.object(content_module, "upload_and_share_local_image", upload):
            result = await self._replace(tool, tmp_path, ctx)
        assert "error" not in result
        assert "error" not in result["images"][0]
        assert upload.call_args.args[2] == "docfolder"
        assert len(self._parents_lookups(drive_svc)) == 1

    @pytest.mark.parametrize("tool", ["write_doc_content", "update_doc_from_file"])
    async def test_no_folder_known_refuses_before_touching_the_doc(self, tmp_path, tool):
        # A doc shared from a folder this account can't see has no parents.
        drive_svc, docs_svc = self._services(parents=None)
        ctx = self._ctx(drive_svc, docs_svc)
        upload = AsyncMock()
        with patch.object(content_module, "upload_and_share_local_image", upload):
            result = await self._replace(tool, tmp_path, ctx)
        assert result["docId"] == "doc1"
        assert "Pass folder_id" in result["error"]
        assert "left unchanged" in result["error"]
        upload.assert_not_called()
        drive_svc.files.return_value.copy.assert_not_called()
        docs_svc.documents.return_value.batchUpdate.assert_not_called()

    async def test_no_lookup_without_local_images(self):
        drive_svc, docs_svc = self._services(parents=None)
        ctx = self._ctx(drive_svc, docs_svc)
        result = await _docs_tools["write_doc_content"](
            doc_id="doc1",
            content="![Pic](https://example.com/a.png)",
            content_format="markdown",
            ctx=ctx,
        )
        assert "error" not in result
        assert self._parents_lookups(drive_svc) == []

    async def test_create_doc_without_a_folder_uploads_next_to_the_new_doc(self, tmp_path):
        # The create tools get the same last fallback: the new doc's own folder,
        # here My Drive's root, which Drive reports as the created file's parent.
        img = tmp_path / "pic.png"
        img.write_bytes(b"png")
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "doc1",
            "name": "Doc",
            "parents": ["rootid"],
        }
        ctx = self._ctx(drive_svc, MagicMock())
        upload = AsyncMock(side_effect=lambda _svc, path, folder, **kw: _uploaded(path, folder))
        with patch.object(content_module, "upload_and_share_local_image", upload):
            result = await _docs_tools["create_doc"](
                title="Doc", content=f"![Pic]({img})", content_format="markdown", ctx=ctx
            )
        assert "error" not in result["images"][0]
        assert upload.call_args.args[2] == "rootid"


class TestImageFallbackText:
    """#1099: the text written in place of an image Docs can't embed."""

    @pytest.mark.parametrize(
        ("image", "expected"),
        [
            (Image(src="https://x/a.svg", alt="Build"), "Build"),
            (Image(src="https://x/a.svg", alt="  two\n words "), "two words"),
            (
                Image(src="https://img.shields.io/badge/build-passing-brightgreen", alt=""),
                "build-passing-brightgreen",
            ),
            (Image(src="https://x/my%20pic.svg?raw=true#frag"), "my pic.svg"),
            (Image(src="https://x/"), "image"),
            (Image(src="/home/someone/secret/dir/pic.png"), "pic.png"),
            (Image(src="drive:abc123"), "image"),
        ],
    )
    def test_text(self, image, expected):
        assert image_fallback_text(image) == expected

    def test_linked_fallback_carries_the_link(self):
        [insert, style] = image_fallback_requests(
            Image(src="https://x/a.svg", alt="Build", link_url="https://ci"), 5
        )
        assert insert == {"insertText": {"location": {"index": 5}, "text": "Build"}}
        assert style["updateTextStyle"] == {
            "range": {"startIndex": 5, "endIndex": 10},
            "textStyle": {"link": {"url": "https://ci"}},
            "fields": "link",
        }

    def test_unlinked_fallback_clears_an_inherited_link(self):
        # Inserted text takes the style of the character before it, a link included.
        [_insert, style] = image_fallback_requests(Image(src="https://x/a.svg", alt="A"), 5)
        assert style["updateTextStyle"]["textStyle"] == {}
        assert style["updateTextStyle"]["fields"] == "link"

    def test_unstorable_link_is_cleared_not_stored(self):
        # The same rule as a text link (#1120): a relative target goes nowhere.
        [_insert, style] = image_fallback_requests(
            Image(src="https://x/a.svg", alt="A", link_url="./guide.md"), 5
        )
        assert style["updateTextStyle"]["textStyle"] == {}

    async def test_unfetchable_badge_shows_linked_alt_text(self):
        # TC-MD004's badge: an SVG Docs can't embed keeps its alt text and link.
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "doc1",
            "name": "Doc",
            "parents": ["folder1"],
        }
        docs_svc = MagicMock()
        badge = "https://img.shields.io/badge/build-passing-brightgreen"
        sent: list[list[dict]] = []

        def side_effect(documentId, body):
            sent.append(list(body["requests"]))
            m = MagicMock()
            bad = [
                i
                for i, r in enumerate(body["requests"])
                if r.get("insertInlineImage", {}).get("uri") == badge
            ]
            if bad:
                message = (
                    f"Invalid requests[{bad[0]}].insertInlineImage: There was a problem "
                    "retrieving the image."
                )
                m.execute.side_effect = HttpError(
                    resp=MagicMock(status=400),
                    content=json.dumps({"error": {"code": 400, "message": message}}).encode(),
                )
            else:
                m.execute.return_value = {}
            return m

        docs_svc.documents.return_value.batchUpdate.side_effect = side_effect
        ctx = _make_ctx(drive_service=drive_svc, docs_service=docs_svc, folder_id="folder1")
        result = await _docs_tools["create_doc"](
            title="Doc",
            content=f"[![Build]({badge})](https://example.com/ci)",
            content_format="markdown",
            ctx=ctx,
        )
        [entry] = result["images"]
        assert entry["fallback_text"] == "Build"
        assert "There was a problem retrieving the image" in entry["error"]
        final = sent[-1]
        i = next(i for i, r in enumerate(final) if r.get("insertText", {}).get("text") == "Build")
        assert final[i + 1]["updateTextStyle"]["textStyle"] == {
            "link": {"url": "https://example.com/ci"}
        }
