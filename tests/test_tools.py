"""Regression tests for four bugs fixed in the post-merge code review."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import drive as drive_module
from mcp_gee_sweet.tools import sheets as sheets_module
from mcp_gee_sweet.tools import write as write_module


def _make_tool_registry():
    """Capture tool functions by name without going through FastMCP."""
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


_drive_tool, _drive_tools = _make_tool_registry()
drive_module.register(_drive_tool)

_sheets_tool, _sheets_tools = _make_tool_registry()
sheets_module.register(_sheets_tool)

_write_tool, _write_tools = _make_tool_registry()
write_module.register(_write_tool)


class TestSearchSpreadsheetsQueryEscape:
    """Bug: single quotes in query were interpolated raw into the Drive query string."""

    def _drive_service(self):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": []}
        return mock

    def _captured_q(self, drive_svc):
        return drive_svc.files.return_value.list.call_args.kwargs["q"]

    def test_single_quote_is_escaped(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        _drive_tools["search_spreadsheets"](query="it's a test", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    def test_escaped_form_used_not_raw(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        _drive_tools["search_spreadsheets"](query="O'Brien", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "O\\'Brien" in q
        # The apostrophe in 'O'Brien' must be preceded by a backslash
        idx = q.index("'Brien")
        assert q[idx - 1] == "\\"

    def test_query_without_quotes_passes_through(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        _drive_tools["search_spreadsheets"](query="budget 2024", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "budget 2024" in q


class TestCreateDocHtmlFormatting:
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

    def _make_ctx(self, drive_svc, docs_svc):
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
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content="<h1>Title</h1>", ctx=ctx)
        heading_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in self._batchupdate_requests(docs_svc)
            if "updateParagraphStyle" in r
        ]
        assert "HEADING_1" in heading_types

    def test_list_item_produces_bullet(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content="<li>Item</li>", ctx=ctx)
        bullets = [r for r in self._batchupdate_requests(docs_svc) if "createParagraphBullets" in r]
        assert len(bullets) == 1

    def test_no_content_skips_batchupdate(self):
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content=None, ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called

    def test_inline_only_html_skips_batchupdate(self):
        """Tags with no block-level elements produce no requests; batchUpdate should not fire."""
        drive_svc, docs_svc = self._make_services()
        ctx = self._make_ctx(drive_svc, docs_svc)
        _drive_tools["create_doc"](title="Doc", content="<span>no blocks</span>", ctx=ctx)
        assert not docs_svc.documents.return_value.batchUpdate.called


class TestCopySheetRename:
    """Bug: rename was silently skipped when API response omitted the 'title' key."""

    def _mock_sheets(self, copy_result):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": 0}}]
        }
        (
            mock.spreadsheets.return_value.sheets.return_value.copyTo.return_value.execute.return_value
        ) = copy_result
        return mock

    def _rename_titles(self, mock_sheets):
        body = mock_sheets.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
        return [
            r["updateSheetProperties"]["properties"]["title"]
            for r in body["requests"]
            if "updateSheetProperties" in r
        ]

    def test_rename_triggered_when_title_absent_from_response(self):
        """The old guard `if 'title' in copy_result` would silently skip this case."""
        mock_sheets = self._mock_sheets({"sheetId": 42})  # no "title" key
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        _sheets_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="My Sheet",
            ctx=ctx,
        )
        assert mock_sheets.spreadsheets.return_value.batchUpdate.called
        assert "My Sheet" in self._rename_titles(mock_sheets)

    def test_rename_triggered_when_title_differs(self):
        mock_sheets = self._mock_sheets({"sheetId": 42, "title": "Copy of Sheet1"})
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        _sheets_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Renamed",
            ctx=ctx,
        )
        assert mock_sheets.spreadsheets.return_value.batchUpdate.called

    def test_rename_skipped_when_title_already_matches(self):
        mock_sheets = self._mock_sheets({"sheetId": 42, "title": "Target Name"})
        ctx = _make_ctx(sheets_service=mock_sheets, cache=MagicMock())
        _sheets_tools["copy_sheet"](
            src_spreadsheet="src",
            src_sheet="Sheet1",
            dst_spreadsheet="dst",
            dst_sheet="Target Name",
            ctx=ctx,
        )
        assert not mock_sheets.spreadsheets.return_value.batchUpdate.called


class TestBatchUpdateCacheInvalidation:
    """Bug: batch_update only invalidated sheet_data_cache, leaving structure cache stale."""

    def _mock_sheets(self):
        mock = MagicMock()
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {
            "replies": []
        }
        return mock

    def test_structure_cache_marked_dirty(self):
        mock_cache = MagicMock()
        ctx = _make_ctx(
            sheets_service=self._mock_sheets(),
            cache=mock_cache,
            sheet_data_cache=MagicMock(),
        )
        _write_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"addSheet": {"properties": {"title": "New Sheet"}}}],
            ctx=ctx,
        )
        mock_cache.mark_dirty.assert_called_once_with("abc123")

    def test_data_cache_still_marked_dirty(self):
        mock_data_cache = MagicMock()
        ctx = _make_ctx(
            sheets_service=self._mock_sheets(),
            cache=MagicMock(),
            sheet_data_cache=mock_data_cache,
        )
        _write_tools["batch_update"](
            spreadsheet_id="abc123",
            requests=[{"updateCells": {}}],
            ctx=ctx,
        )
        mock_data_cache.mark_dirty.assert_called_once_with("abc123")
