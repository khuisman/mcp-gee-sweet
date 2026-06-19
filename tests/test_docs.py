"""Tests for docs package — HTML pipeline and tool registration."""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs import _html_to_doc_requests, _html_to_text
from mcp_gee_sweet.tools.docs.ast import BulletItem, Heading, Paragraph, Table
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


class TestHtmlToText:
    def test_plain_paragraph(self):
        assert _html_to_text("<p>Hello world</p>") == "Hello world"

    def test_multiple_paragraphs(self):
        result = _html_to_text("<p>First</p><p>Second</p>")
        assert "First" in result
        assert "Second" in result
        assert result.index("First") < result.index("Second")

    def test_line_break(self):
        result = _html_to_text("Line one<br>Line two")
        assert "\n" in result

    def test_strips_tags(self):
        result = _html_to_text("<h1>Title</h1><p>Body</p>")
        assert "<h1>" not in result
        assert "Title" in result
        assert "Body" in result

    def test_html_entities(self):
        assert "&amp;" not in _html_to_text("<p>fish &amp; chips</p>")
        assert "fish & chips" in _html_to_text("<p>fish &amp; chips</p>")

    def test_numeric_html_entity(self):
        result = _html_to_text("<p>&#169;</p>")
        assert "©" in result

    def test_empty_input(self):
        assert _html_to_text("") == ""

    def test_plain_text_passthrough(self):
        assert _html_to_text("just text") == "just text"


class TestHtmlToDocRequests:
    def test_empty_input_returns_empty(self):
        requests, tables = _html_to_doc_requests("")
        assert requests == []
        assert tables == []

    def test_paragraph_produces_insert_text(self):
        requests, _ = _html_to_doc_requests("<p>Hello</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert "Hello" in insert["insertText"]["text"]

    def test_h1_produces_heading_1(self):
        requests, _ = _html_to_doc_requests("<h1>Title</h1>")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in styles

    def test_h2_produces_heading_2(self):
        requests, _ = _html_to_doc_requests("<h2>Subtitle</h2>")
        styles = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in requests
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_2" in styles

    def test_list_item_produces_bullet(self):
        requests, _ = _html_to_doc_requests("<li>Item</li>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_anchor_produces_link_style(self):
        requests, _ = _html_to_doc_requests('<p><a href="https://example.com">click</a></p>')
        links = [
            r
            for r in requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"].get("textStyle", {})
        ]
        assert len(links) == 1
        assert links[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://example.com"

    def test_start_index_offset(self):
        requests_default, _ = _html_to_doc_requests("<p>Hi</p>", start_index=1)
        requests_offset, _ = _html_to_doc_requests("<p>Hi</p>", start_index=10)
        default_insert = next(r for r in requests_default if "insertText" in r)
        offset_insert = next(r for r in requests_offset if "insertText" in r)
        assert offset_insert["insertText"]["location"]["index"] == 10
        assert default_insert["insertText"]["location"]["index"] == 1

    def test_indices_are_contiguous(self):
        requests, _ = _html_to_doc_requests("<p>First</p><p>Second</p>")
        insert = next(r for r in requests if "insertText" in r)
        full_text = insert["insertText"]["text"]
        assert full_text == "First\nSecond\n"

    def test_list_item_inside_ul(self):
        requests, _ = _html_to_doc_requests("<ul><li>Item one</li><li>Item two</li></ul>")
        bullets = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullets) == 2

    def test_whitespace_only_paragraph_skipped(self):
        requests, _ = _html_to_doc_requests("<p>   </p><p>Real content</p>")
        insert = next(r for r in requests if "insertText" in r)
        assert "Real content" in insert["insertText"]["text"]
        assert insert["insertText"]["text"].strip() == "Real content"

    def test_table_produces_insert_table_request(self):
        requests, tables = _html_to_doc_requests(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
        table_reqs = [r for r in requests if "insertTable" in r]
        assert len(table_reqs) == 1
        assert table_reqs[0]["insertTable"]["rows"] == 2
        assert table_reqs[0]["insertTable"]["columns"] == 2

    def test_table_data_returned_in_tables(self):
        _, tables = _html_to_doc_requests(
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
        assert len(tables) == 1
        # tables are now Table AST nodes
        assert len(tables[0].rows) == 2
        assert tables[0].rows[0].cells[0].runs[0].text == "A"
        assert tables[0].rows[0].cells[1].runs[0].text == "B"
        assert tables[0].rows[1].cells[0].runs[0].text == "1"
        assert tables[0].rows[1].cells[1].runs[0].text == "2"

    def test_table_interleaved_with_text(self):
        html = "<h2>Before</h2><table><tr><td>X</td></tr></table><h2>After</h2>"
        requests, tables = _html_to_doc_requests(html)
        insert_texts = [r for r in requests if "insertText" in r]
        insert_tables = [r for r in requests if "insertTable" in r]
        # All text ("Before\nAfter\n") in one insertText; table inserted between them
        assert len(insert_texts) == 1
        assert len(insert_tables) == 1
        all_text = insert_texts[0]["insertText"]["text"]
        assert "Before" in all_text and "After" in all_text
        # Table position is between the two text segments (after "Before\n" = 7 chars)
        text_start = insert_texts[0]["insertText"]["location"]["index"]
        table_idx = insert_tables[0]["insertTable"]["location"]["index"]
        assert text_start <= table_idx <= text_start + len("Before\n")

    def test_heading_gets_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<h1>Title</h1>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert has_delete

    def test_paragraph_gets_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<p>Body</p>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert has_delete

    def test_li_does_not_get_delete_bullets(self):
        requests, _ = _html_to_doc_requests("<li>Item</li>")
        has_delete = any("deleteParagraphBullets" in r for r in requests)
        assert not has_delete

    def test_table_no_cell_inserttext_in_requests(self):
        requests, _ = _html_to_doc_requests("<table><tr><td>hello</td></tr></table>")
        # Cell content must NOT appear in this batch — it goes in a second phase
        cell_inserts = [
            r for r in requests if "insertText" in r and "hello" in r["insertText"].get("text", "")
        ]
        assert cell_inserts == []

    def test_adjacent_tables_order_preserved(self):
        html = "<table><tr><td>T1</td></tr></table><table><tr><td>T2</td></tr></table>"
        requests, tables = _html_to_doc_requests(html)
        insert_tables = [r for r in requests if "insertTable" in r]
        assert len(insert_tables) == 2
        assert len(tables) == 2
        assert tables[0].rows[0].cells[0].runs[0].text == "T1"
        assert tables[1].rows[0].cells[0].runs[0].text == "T2"
        # Both tables share the same insert position (no text between them).
        # Reverse-order insertion means T1 ends up at a lower index than T2 in the doc,
        # so T1's position must be <= T2's position in the request list (last request = T1).
        t1_req = insert_tables[-1]  # inserted last → lands first in doc
        t2_req = insert_tables[-2]  # inserted first → lands second in doc
        assert (
            t1_req["insertTable"]["location"]["index"] <= t2_req["insertTable"]["location"]["index"]
        )


class TestHtmlToAst:
    """Tests for the AST layer — html_to_ast and the nodes it produces."""

    def test_h1_to_h6_correct_levels(self):
        for level in range(1, 7):
            nodes = html_to_ast(f"<h{level}>Title</h{level}>")
            assert len(nodes) == 1
            assert isinstance(nodes[0], Heading)
            assert nodes[0].level == level

    def test_paragraph_node(self):
        nodes = html_to_ast("<p>Hello</p>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Paragraph)
        assert nodes[0].runs[0].text == "Hello"

    def test_bullet_item_from_ul(self):
        nodes = html_to_ast("<ul><li>Item</li></ul>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert len(bullets) == 1
        assert bullets[0].ordered is False

    def test_bullet_item_from_ol(self):
        nodes = html_to_ast("<ol><li>Item</li></ol>")
        bullets = [n for n in nodes if isinstance(n, BulletItem)]
        assert len(bullets) == 1
        assert bullets[0].ordered is True

    def test_inline_bold_in_paragraph(self):
        nodes = html_to_ast("<p><b>bold</b> plain</p>")
        assert isinstance(nodes[0], Paragraph)
        runs = nodes[0].runs
        bold_run = next(r for r in runs if r.bold)
        assert bold_run.text == "bold"
        plain_run = next(r for r in runs if not r.bold)
        assert "plain" in plain_run.text

    def test_inline_italic_in_paragraph(self):
        nodes = html_to_ast("<p><i>italic</i></p>")
        assert nodes[0].runs[0].italic is True

    def test_inline_link_in_paragraph(self):
        nodes = html_to_ast('<p><a href="https://example.com">click</a></p>')
        link_run = next(r for r in nodes[0].runs if r.link_url)
        assert link_run.link_url == "https://example.com"

    def test_th_cell_has_bold_run(self):
        nodes = html_to_ast("<table><tr><th>Header</th></tr></table>")
        table = nodes[0]
        assert isinstance(table, Table)
        cell = table.rows[0].cells[0]
        assert cell.is_header is True
        assert cell.runs[0].bold is True

    def test_td_cell_text(self):
        nodes = html_to_ast("<table><tr><td>Data</td></tr></table>")
        table = nodes[0]
        cell = table.rows[0].cells[0]
        assert cell.is_header is False
        assert cell.runs[0].text == "Data"

    def test_inline_bold_in_td(self):
        nodes = html_to_ast("<table><tr><td><b>bold cell</b></td></tr></table>")
        cell = nodes[0].rows[0].cells[0]
        assert cell.runs[0].bold is True
        assert cell.runs[0].text == "bold cell"

    def test_inline_link_in_td(self):
        nodes = html_to_ast('<table><tr><td><a href="https://x.com">link</a></td></tr></table>')
        cell = nodes[0].rows[0].cells[0]
        link_run = next(r for r in cell.runs if r.link_url)
        assert link_run.link_url == "https://x.com"

    def test_colspan_on_td(self):
        nodes = html_to_ast('<table><tr><td colspan="2">wide</td></tr></table>')
        cell = nodes[0].rows[0].cells[0]
        assert cell.colspan == 2

    def test_default_colspan_is_1(self):
        nodes = html_to_ast("<table><tr><td>x</td></tr></table>")
        assert nodes[0].rows[0].cells[0].colspan == 1

    def test_col_width_parsed_from_col_tag(self):
        # 96px → 72pt (96 * 72 / 96 = 72)
        nodes = html_to_ast('<table><col width="96"><tr><td>x</td></tr></table>')
        assert isinstance(nodes[0], Table)
        widths = nodes[0].col_widths
        assert len(widths) == 1
        assert widths[0] == pytest.approx(72.0)

    def test_col_width_parsed_from_td_first_row(self):
        nodes = html_to_ast('<table><tr><td width="96">x</td></tr></table>')
        assert isinstance(nodes[0], Table)
        widths = nodes[0].col_widths
        assert len(widths) == 1
        assert widths[0] == pytest.approx(72.0)

    def test_h3_to_h6_correct_heading_levels_in_requests(self):
        for level in range(3, 7):
            requests, _ = _html_to_doc_requests(f"<h{level}>Title</h{level}>")
            styles = [
                r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
                for r in requests
                if "updateParagraphStyle" in r
            ]
            assert f"HEADING_{level}" in styles


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
