"""#1180: a Markdown/HTML conversion that writes a link as plain text says so.

Since #1120 the emitter drops a link target the Docs API can't store (no scheme,
e.g. "./guide.md"), and since #409 the anchor pass strips a "#slug" link no heading
matches. Both used to leave the tool reporting plain success. Every Markdown/HTML
entry point now returns the dropped targets under "dropped_links".
"""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.docs.ast import Cell, Image, Paragraph, Row, Run, Table
from mcp_gee_sweet.tools.docs.emitter import unstorable_link_urls


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


_docs_tool, _docs_tools = _make_tool_registry()
docs_module.register(_docs_tool)


def _ctx(drive_svc, docs_svc):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.drive_service = drive_svc
    lc.docs_service = docs_svc
    lc.folder_id = None
    lc.drive_folder_cache = MagicMock()
    lc.doc_cache = MagicMock()
    return ctx


def _services(doc_body: list[dict] | None = None):
    """Drive/Docs mocks for both a create (files().create) and a replace into an
    empty doc (documents().get end index 2, so no clear and no backup)."""
    drive_svc = MagicMock()
    drive_svc.files.return_value.create.return_value.execute.return_value = {
        "id": "doc123",
        "name": "Doc",
        "parents": ["root"],
        "webViewLink": "https://example.com",
    }
    drive_svc.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://example.com"
    }
    docs_svc = MagicMock()
    docs_svc.documents.return_value.get.return_value.execute.return_value = {
        "documentId": "doc123",
        "body": {"content": doc_body if doc_body is not None else [{"endIndex": 2}]},
    }
    return drive_svc, docs_svc


def _para(start: int, text: str, *, heading_id: str | None = None, link: str | None = None):
    style = {"namedStyleType": "HEADING_1", "headingId": heading_id} if heading_id else {}
    text_style = {"link": {"url": link}} if link else {}
    end = start + len(text)
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {
            "paragraphStyle": style or {"namedStyleType": "NORMAL_TEXT"},
            "elements": [
                {
                    "startIndex": start,
                    "endIndex": end,
                    "textRun": {"content": text, "textStyle": text_style},
                }
            ],
        },
    }


class TestUnstorableLinkUrls:
    def test_collects_scheme_less_targets_only(self):
        nodes = [
            Paragraph(
                runs=[
                    Run(text="a", link_url="./guide.md"),
                    Run(text="b", link_url="https://example.com"),
                    Run(text="c", link_url="#section"),
                    Run(text="d", link_url="mailto:x@example.com"),
                    Run(text="e"),
                    Run(text="f", link_url="/guide.md"),
                    # Rewritten to https (#1180), so kept, not dropped.
                    Run(text="g", link_url="//example.com/x"),
                    Run(text="h", link_url="www.example.com"),
                ]
            )
        ]
        assert unstorable_link_urls(nodes) == ["./guide.md", "/guide.md"]

    def test_linked_image_and_nested_table_cell_count(self):
        inner = Table(rows=[Row(cells=[Cell(children=[Run(text="in", link_url="deep.md")])])])
        outer = Table(
            rows=[
                Row(
                    cells=[
                        Cell(children=[Run(text="cell", link_url="/cell.md")]),
                        Cell(children=[inner]),
                    ]
                )
            ]
        )
        nodes = [
            Paragraph(runs=[Image(src="https://example.com/a.png", link_url="img.md")]),
            outer,
        ]
        assert unstorable_link_urls(nodes) == ["img.md", "/cell.md", "deep.md"]

    def test_repeated_target_reported_once_in_first_seen_order(self):
        nodes = [
            Paragraph(runs=[Run(text="a", link_url="b.md"), Run(text="b", link_url="a.md")]),
            Paragraph(runs=[Run(text="c", link_url="b.md")]),
        ]
        assert unstorable_link_urls(nodes) == ["b.md", "a.md"]


class TestCreateDocReportsDroppedLinks:
    async def test_relative_link_is_reported(self):
        drive_svc, docs_svc = _services()
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="See [the guide](./guide.md) and [the site](https://example.com).",
            content_format="markdown",
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert result["dropped_links"] == [{"url": "./guide.md", "reason": "no_scheme"}]

    async def test_host_links_are_written_as_https_and_not_reported(self):
        drive_svc, docs_svc = _services()
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="[a](//example.com/x) and [b](www.example.com/y)",
            content_format="markdown",
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert "dropped_links" not in result
        requests = docs_svc.documents.return_value.batchUpdate.call_args.kwargs["body"]["requests"]
        urls = [
            r["updateTextStyle"]["textStyle"]["link"]["url"]
            for r in requests
            if "link" in r.get("updateTextStyle", {}).get("textStyle", {})
        ]
        assert urls == ["https://example.com/x", "https://www.example.com/y"]

    async def test_html_relative_link_is_reported(self):
        drive_svc, docs_svc = _services()
        result = await _docs_tools["create_doc"](
            title="Doc",
            content='<p><a href="/guide.md">guide</a></p>',
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert result["dropped_links"] == [{"url": "/guide.md", "reason": "no_scheme"}]

    async def test_no_dropped_links_key_when_every_link_is_kept(self):
        drive_svc, docs_svc = _services()
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="[site](https://example.com) and [mail](mailto:x@example.com)",
            content_format="markdown",
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert "dropped_links" not in result

    async def test_unmatched_anchor_is_reported_once_and_matched_one_is_not(self):
        # The anchor pass reads the written doc back: one heading, and three anchor
        # runs, two of them to a heading that doesn't exist.
        drive_svc, docs_svc = _services(
            [
                _para(1, "Section\n", heading_id="h.section"),
                _para(9, "ok\n", link="#section"),
                _para(12, "gone\n", link="#missing"),
                _para(17, "again\n", link="#missing"),
            ]
        )
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="# Section\n\n[ok](#section)\n\n[gone](#missing)\n\n[again](#missing)\n",
            content_format="markdown",
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert result["dropped_links"] == [{"url": "#missing", "reason": "no_matching_heading"}]

    async def test_both_kinds_are_reported_relative_first(self):
        drive_svc, docs_svc = _services(
            [_para(1, "Section\n", heading_id="h.section"), _para(9, "gone\n", link="#nope")]
        )
        result = await _docs_tools["create_doc"](
            title="Doc",
            content="# Section\n\n[gone](#nope) [file](notes.md)\n",
            content_format="markdown",
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert result["dropped_links"] == [
            {"url": "notes.md", "reason": "no_scheme"},
            {"url": "#nope", "reason": "no_matching_heading"},
        ]


class TestOtherEntryPointsReportDroppedLinks:
    async def test_create_doc_from_file(self, tmp_path):
        md_file = tmp_path / "doc.md"
        md_file.write_text("[the guide](./guide.md)\n")
        drive_svc, docs_svc = _services()
        result = await _docs_tools["create_doc_from_file"](
            local_path=str(md_file), ctx=_ctx(drive_svc, docs_svc)
        )
        assert result["dropped_links"] == [{"url": "./guide.md", "reason": "no_scheme"}]

    async def test_write_doc_content(self):
        drive_svc, docs_svc = _services()
        result = await _docs_tools["write_doc_content"](
            doc_id="doc123",
            content="[the guide](./guide.md)",
            content_format="markdown",
            ctx=_ctx(drive_svc, docs_svc),
        )
        assert "error" not in result
        assert result["dropped_links"] == [{"url": "./guide.md", "reason": "no_scheme"}]

    async def test_update_doc_from_file(self, tmp_path):
        html_file = tmp_path / "doc.html"
        html_file.write_text('<p><a href="guide.html">guide</a></p>')
        drive_svc, docs_svc = _services()
        result = await _docs_tools["update_doc_from_file"](
            doc_id="doc123", local_path=str(html_file), ctx=_ctx(drive_svc, docs_svc)
        )
        assert "error" not in result
        assert result["dropped_links"] == [{"url": "guide.html", "reason": "no_scheme"}]
