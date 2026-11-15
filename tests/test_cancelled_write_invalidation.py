"""#1030, #1265: a write tool cancelled while its request's worker thread runs still has
that request land after the cancellation unwinds (asyncio.to_thread can't stop the
thread). Every Docs edit tool outside content/images, every Drive tool that
changes a folder's contents, and every Sheets and Calendar write tool must
invalidate its cache on the cancel path, and
again once the abandoned request finishes, or a later read serves the pre-edit
state until the TTL expires. A request that fails may also have been applied (a
timeout), so a failure invalidates too."""

import contextlib
import threading
from functools import partial
from unittest.mock import MagicMock

import anyio
import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet import http_transport
from mcp_gee_sweet.cache import CalendarCache, SheetInfo
from mcp_gee_sweet.http_transport import execute_in_thread, invalidating
from mcp_gee_sweet.tools import calendar as calendar_module
from mcp_gee_sweet.tools import docs as docs_module
from mcp_gee_sweet.tools.drive import _FolderInvalidation
from mcp_gee_sweet.tools.drive import files as files_module
from mcp_gee_sweet.tools.drive import transfer as transfer_module
from mcp_gee_sweet.tools.sheets import data as sheets_data_module
from mcp_gee_sweet.tools.sheets import structure as sheets_structure_module


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
_drive_tool, _drive_tools = _make_tool_registry()
files_module.register(_drive_tool)
transfer_module.register(_drive_tool)
# create_doc / create_doc_from_file are Drive creates too (PR #1264 QA round 1).
docs_module.register(_drive_tool)


def _rejection(status=404):
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=b'{"error": {"errors": [{"reason": "notFound"}]}}')


class _Blocking:
    """An `.execute` that blocks until released, then records that it landed."""

    def __init__(self, result=None):
        self.started = threading.Event()
        self.release = threading.Event()
        self.landed = False
        self._result = {} if result is None else result

    def __call__(self, **kwargs):
        self.started.set()
        self.release.wait(5)
        self.landed = True
        return self._result


async def _cancel_mid_request(call, blocking: _Blocking) -> None:
    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        await anyio.to_thread.run_sync(blocking.started.wait, 5)
        tg.cancel_scope.cancel()


async def _wait_for(predicate, timeout=2.0):
    with anyio.fail_after(timeout):
        while not predicate():
            await anyio.sleep(0.01)


# ---------------------------------------------------------------------------
# Docs edit tools
# ---------------------------------------------------------------------------

# One paragraph covering index 1-10, enough for every tool that reads the doc
# before its edit (create_paragraph_bullets) or after it (insert_doc_table).
_DOC = {
    "documentId": "doc1",
    "body": {
        "content": [
            {
                "startIndex": 1,
                "endIndex": 10,
                "paragraph": {"elements": [{"textRun": {"content": "Item one\n"}}]},
            }
        ]
    },
}

_DOC_TOOL_CALLS = {
    "insert_doc_text": {"insertions": [{"index": 1, "text": "x"}]},
    "delete_doc_range": {"deletions": [{"start_index": 1, "end_index": 2}]},
    "insert_page_break": {"index": 1},
    "insert_softbreak_paragraph": {"index": 1, "lines": [{"text": "a"}, {"text": "b"}]},
    "style_doc_range": {"ranges": [{"start_index": 1, "end_index": 5, "bold": True}]},
    "style_doc_table_cells": {
        "table_start_index": 5,
        "cells": [{"row_index": 0, "column_index": 0, "border_width": 0.5}],
    },
    "create_paragraph_bullets": {"ranges": [{"start_index": 1, "end_index": 10}]},
    "delete_paragraph_bullets": {"ranges": [{"start_index": 1, "end_index": 10}]},
    "apply_theme": {"theme": {"HEADING_1": {"font_family": "Georgia"}}},
    "insert_doc_table": {"index": 1, "rows": 1, "columns": 1},
    "insert_table_row": {"table_start_index": 5, "row_index": 0},
    "delete_table_row": {"table_start_index": 5, "row_index": 0},
    "insert_table_column": {"table_start_index": 5, "column_index": 0},
    "delete_table_column": {"table_start_index": 5, "column_index": 0},
    "merge_table_cells": {"table_start_index": 5, "row_index": 0, "column_index": 0},
    "create_header": {"content": "Header"},
    "create_footer": {"content": "Footer"},
    "create_named_range": {"name": "r", "start_index": 1, "end_index": 3},
    "create_bookmark": {"name": "b", "index": 1},
}


def _docs_ctx(execute):
    docs_svc = MagicMock()
    docs_svc.documents.return_value.get.return_value.execute.return_value = _DOC
    docs_svc.documents.return_value.batchUpdate.return_value.execute.side_effect = execute
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.docs_service = docs_svc
    lc.doc_cache = MagicMock()
    return ctx, lc.doc_cache


def test_every_doc_edit_tool_is_covered():
    # A Docs tool that edits through batchUpdate outside content.py/images.py
    # (which #907/#1029 already cover) has to be listed above.
    doc_tool_modules = {"editing", "style", "tables", "layout", "named_ranges"}
    edit_tools = {
        name
        for name, fn in _docs_tools.items()
        if fn.__module__.rsplit(".", 1)[-1] in doc_tool_modules and not name.startswith("get_")
    }
    assert edit_tools == set(_DOC_TOOL_CALLS)


@pytest.mark.parametrize("tool_name", sorted(_DOC_TOOL_CALLS))
async def test_doc_tool_cancelled_mid_edit_marks_doc_dirty_again_once_it_lands(tool_name):
    blocking = _Blocking()
    ctx, doc_cache = _docs_ctx(blocking)
    seen = []
    doc_cache.mark_dirty.side_effect = lambda doc_id: seen.append((doc_id, blocking.landed))

    await _cancel_mid_request(
        partial(_docs_tools[tool_name], doc_id="doc1", ctx=ctx, **_DOC_TOOL_CALLS[tool_name]),
        blocking,
    )
    # The cancel path's own invalidation, before the edit has landed.
    assert seen == [("doc1", False)]

    blocking.release.set()
    await _wait_for(lambda: ("doc1", True) in seen)


@pytest.mark.parametrize("tool_name", sorted(_DOC_TOOL_CALLS))
async def test_doc_tool_failed_edit_marks_doc_dirty(tool_name):
    def execute(**kwargs):
        raise TimeoutError("timed out; the edit may have been applied")

    ctx, doc_cache = _docs_ctx(execute)
    result = await _docs_tools[tool_name](doc_id="doc1", ctx=ctx, **_DOC_TOOL_CALLS[tool_name])
    assert "error" in result or "warning" in result
    doc_cache.mark_dirty.assert_called_with("doc1")


@pytest.mark.parametrize("tool_name", sorted(_DOC_TOOL_CALLS))
async def test_doc_tool_successful_edit_marks_doc_dirty(tool_name):
    ctx, doc_cache = _docs_ctx(lambda **kwargs: {})
    await _docs_tools[tool_name](doc_id="doc1", ctx=ctx, **_DOC_TOOL_CALLS[tool_name])
    doc_cache.mark_dirty.assert_called_with("doc1")


# ---------------------------------------------------------------------------
# Drive tools that change a folder's contents
# ---------------------------------------------------------------------------


def _drive_ctx(write_execute, tmp_path):
    drive_svc = MagicMock()
    files = drive_svc.files.return_value
    # Every read the tools make before their write: an existing file's parents
    # (move/delete), a shortcut target's name, an upload's existence check.
    files.get.return_value.execute.return_value = {
        "parents": ["old-parent"],
        "name": "target",
        "mimeType": "text/plain",
        "capabilities": {"canDelete": True, "canTrash": True},
    }
    files.list.return_value.execute.return_value = {"files": []}
    for method in ("create", "copy", "update", "delete"):
        getattr(files, method).return_value.execute.side_effect = write_execute
    sheets_svc = MagicMock()
    # import_csv_to_sheet reads the new spreadsheet's default sheet after creating it.
    sheets_svc.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [
            {
                "properties": {
                    "sheetId": 0,
                    "title": "Sheet1",
                    "gridProperties": {"rowCount": 1000, "columnCount": 26},
                }
            }
        ]
    }
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.drive_service = drive_svc
    lc.sheets_service = sheets_svc
    lc.folder_id = None
    lc.drive_folder_cache = MagicMock()
    return ctx, lc.drive_folder_cache


def _drive_tool_calls(tmp_path):
    """Each tool's arguments, and the folders whose listing its write changes.
    None means only the write's response could name the folder, so a write that
    never returns one must mark every listing dirty."""
    local_file = tmp_path / "a.txt"
    local_file.write_text("hello")
    csv_file = tmp_path / "a.csv"
    csv_file.write_text("a,b\n1,2\n")
    folder = tmp_path / "dir"
    folder.mkdir()
    (folder / "b.txt").write_text("hi")
    md_file = tmp_path / "doc.md"
    md_file.write_text("Text\n")
    return {
        "create_spreadsheet": ({"title": "t", "folder_id": "f1"}, {"f1"}),
        "import_csv_to_sheet": (
            {"local_path": str(csv_file), "title": "t", "folder_id": "f1"},
            {"f1"},
        ),
        "create_folder": ({"name": "n", "parent_folder_id": "f1"}, {"f1"}),
        "create_shortcut": ({"target_file_id": "t1", "folder_id": "f1", "name": "s"}, {"f1"}),
        "copy_file": ({"file_id": "x", "folder_id": "f1"}, {"f1"}),
        "copy_file_in_place": ({"file_id": "x"}, None),
        "move_file": ({"file_id": "x", "destination_folder_id": "f1"}, {"f1", "old-parent"}),
        "rename_file": ({"file_id": "x", "new_name": "y"}, None),
        "star_file": ({"file_id": "x"}, None),
        "unstar_file": ({"file_id": "x"}, None),
        "delete_file": ({"file_id": "x"}, {"old-parent"}),
        "delete_file_permanently": ({"file_id": "x", "permanent": True}, {"old-parent"}),
        "restore_file": ({"file_id": "x"}, None),
        "upload_file": ({"name": "n", "content": "c", "folder_id": "f1"}, {"f1"}),
        "upload_local_file": ({"local_path": str(local_file), "parent_folder_id": "f1"}, {"f1"}),
        "upload_local_folder": ({"local_path": str(folder), "parent_folder_id": "f1"}, {"f1"}),
        "create_doc": ({"title": "t", "folder_id": "f1"}, {"f1"}),
        "create_doc_from_file": ({"local_path": str(md_file), "folder_id": "f1"}, {"f1"}),
    }


_DRIVE_TOOL_CASES = [
    "copy_file",
    "copy_file_in_place",
    "create_doc",
    "create_doc_from_file",
    "create_folder",
    "create_shortcut",
    "create_spreadsheet",
    "delete_file",
    "delete_file_permanently",
    "import_csv_to_sheet",
    "move_file",
    "rename_file",
    "restore_file",
    "star_file",
    "unstar_file",
    "upload_file",
    "upload_local_file",
    "upload_local_folder",
]

# A case that exercises a second path through one tool.
_CASE_TOOL = {"copy_file_in_place": "copy_file", "delete_file_permanently": "delete_file"}


def _tool_for(case: str):
    return _drive_tools[_CASE_TOOL.get(case, case)]


def _record(folder_cache):
    seen: list = []
    folder_cache.mark_dirty.side_effect = lambda folder_id: seen.append(folder_id)
    folder_cache.mark_all_dirty.side_effect = lambda: seen.append("*")
    return seen


@pytest.mark.parametrize("case", _DRIVE_TOOL_CASES)
async def test_drive_tool_cancelled_mid_write_marks_folder_dirty_again_once_it_lands(
    case, tmp_path
):
    kwargs, folders = _drive_tool_calls(tmp_path)[case]
    expected = {"*"} if folders is None else folders
    blocking = _Blocking({"id": "new", "parents": ["p1"]})
    ctx, folder_cache = _drive_ctx(blocking, tmp_path)
    seen = _record(folder_cache)

    await _cancel_mid_request(partial(_tool_for(case), ctx=ctx, **kwargs), blocking)
    assert set(seen) == expected

    landed_from = len(seen)
    blocking.release.set()
    await _wait_for(lambda: set(seen[landed_from:]) == expected)


@pytest.mark.parametrize("case", _DRIVE_TOOL_CASES)
async def test_drive_tool_failed_write_marks_folder_dirty(case, tmp_path):
    kwargs, folders = _drive_tool_calls(tmp_path)[case]
    expected = {"*"} if folders is None else folders

    def execute(**kw):
        raise TimeoutError("timed out; the write may have been applied")

    ctx, folder_cache = _drive_ctx(execute, tmp_path)
    seen = _record(folder_cache)
    with contextlib.suppress(TimeoutError):
        await _tool_for(case)(ctx=ctx, **kwargs)
    assert set(seen) == expected


@pytest.mark.parametrize("case", _DRIVE_TOOL_CASES)
async def test_drive_tool_successful_write_marks_only_its_folders(case, tmp_path):
    kwargs, folders = _drive_tool_calls(tmp_path)[case]
    # A response names the file's parents, so a success never needs mark_all_dirty.
    expected = {"p1"} if folders is None else folders
    ctx, folder_cache = _drive_ctx(lambda **kw: {"id": "new", "parents": ["p1"]}, tmp_path)
    seen = _record(folder_cache)
    await _tool_for(case)(ctx=ctx, **kwargs)
    assert set(seen) == expected


# The two uploads catch the error inside _upload_local_file and decide from its
# result, which can't tell a 4xx from a timeout, so they mark their one known
# folder; every other tool marks nothing.
_REJECTION_STILL_MARKS = {"upload_local_file": {"f1"}, "upload_local_folder": {"f1"}}


@pytest.mark.parametrize("case", _DRIVE_TOOL_CASES)
async def test_drive_tool_rejected_write_marks_nothing(case, tmp_path):
    # A 4xx ran nothing (PR #1264 QA round 1): a typo'd file ID passed to
    # rename_file used to clear every folder listing.
    kwargs, _ = _drive_tool_calls(tmp_path)[case]

    def execute(**kw):
        raise _rejection()

    ctx, folder_cache = _drive_ctx(execute, tmp_path)
    seen = _record(folder_cache)
    with contextlib.suppress(HttpError):
        await _tool_for(case)(ctx=ctx, **kwargs)
    assert set(seen) == _REJECTION_STILL_MARKS.get(case, set())


@pytest.mark.parametrize("case", _DRIVE_TOOL_CASES)
async def test_drive_tool_success_whose_response_names_no_folder_marks_only_known_ones(
    case, tmp_path
):
    # A non-owner's rename of a file shared with them: the response has no
    # parents, and there's no listing of theirs to mark (PR #1264 QA round 1).
    kwargs, folders = _drive_tool_calls(tmp_path)[case]
    ctx, folder_cache = _drive_ctx(lambda **kw: {"id": "new"}, tmp_path)
    seen = _record(folder_cache)
    await _tool_for(case)(ctx=ctx, **kwargs)
    assert set(seen) == (folders or set())


@pytest.mark.parametrize("tool_name", sorted(_DOC_TOOL_CALLS))
async def test_doc_tool_rejected_edit_marks_nothing(tool_name):
    def execute(**kwargs):
        raise _rejection(400)

    ctx, doc_cache = _docs_ctx(execute)
    await _docs_tools[tool_name](doc_id="doc1", ctx=ctx, **_DOC_TOOL_CALLS[tool_name])
    doc_cache.mark_dirty.assert_not_called()


# ---------------------------------------------------------------------------
# _FolderInvalidation
# ---------------------------------------------------------------------------


def _lc():
    lc = MagicMock()
    lc.drive_folder_cache = MagicMock()
    return lc


def test_folder_invalidation_marks_known_folders():
    lc = _lc()
    _FolderInvalidation(lc, "a", None, "b")()
    assert {c.args[0] for c in lc.drive_folder_cache.mark_dirty.call_args_list} == {"a", "b"}
    lc.drive_folder_cache.mark_all_dirty.assert_not_called()


def test_folder_invalidation_with_no_known_folder_marks_everything():
    lc = _lc()
    _FolderInvalidation(lc)()
    lc.drive_folder_cache.mark_all_dirty.assert_called_once_with()
    lc.drive_folder_cache.mark_dirty.assert_not_called()


def test_folder_invalidation_takes_response_parents_only_when_none_known():
    lc = _lc()
    unknown = _FolderInvalidation(lc)
    unknown.found(["p1"])
    unknown()
    lc.drive_folder_cache.mark_dirty.assert_called_once_with("p1")

    lc = _lc()
    known = _FolderInvalidation(lc, "f1")
    known.found(["p1"])
    known()
    lc.drive_folder_cache.mark_dirty.assert_called_once_with("f1")


def test_folder_invalidation_answered_with_no_parents_marks_nothing():
    lc = _lc()
    invalidate = _FolderInvalidation(lc)
    invalidate.found(None)
    invalidate()
    lc.drive_folder_cache.mark_all_dirty.assert_not_called()
    lc.drive_folder_cache.mark_dirty.assert_not_called()


# ---------------------------------------------------------------------------
# import_csv_to_sheet's sheet caches
# ---------------------------------------------------------------------------


async def test_import_csv_marks_sheet_data_dirty_when_a_chunk_write_is_cancelled(tmp_path):
    csv_file = tmp_path / "a.csv"
    csv_file.write_text("a,b\n1,2\n")
    ctx, _ = _drive_ctx(lambda **kw: {"id": "sid", "parents": ["f1"]}, tmp_path)
    lc = ctx.request_context.lifespan_context
    blocking = _Blocking()
    sheets = lc.sheets_service.spreadsheets.return_value
    sheets.values.return_value.update.return_value.execute.side_effect = blocking
    seen = []
    lc.sheet_data_cache.mark_dirty.side_effect = lambda sid: seen.append((sid, blocking.landed))

    await _cancel_mid_request(
        partial(
            _drive_tools["import_csv_to_sheet"],
            local_path=str(csv_file),
            title="t",
            folder_id="f1",
            ctx=ctx,
        ),
        blocking,
    )
    assert seen == [("sid", False)]
    blocking.release.set()
    await _wait_for(lambda: ("sid", True) in seen)


async def test_import_csv_marks_sheet_structure_dirty_when_its_rename_fails(tmp_path):
    # A sheet name other than the default makes the import rename the sheet.
    csv_file = tmp_path / "a.csv"
    csv_file.write_text("a,b\n1,2\n")
    ctx, _ = _drive_ctx(lambda **kw: {"id": "sid", "parents": ["f1"]}, tmp_path)
    lc = ctx.request_context.lifespan_context
    sheets = lc.sheets_service.spreadsheets.return_value
    sheets.batchUpdate.return_value.execute.side_effect = TimeoutError("may have landed")

    with contextlib.suppress(TimeoutError):
        await _drive_tools["import_csv_to_sheet"](
            local_path=str(csv_file), title="t", folder_id="f1", sheet_name="Data", ctx=ctx
        )
    lc.cache.mark_dirty.assert_called_with("sid")


# ---------------------------------------------------------------------------
# Sheets write tools (#1265)
# ---------------------------------------------------------------------------

# What each write changes: "structure" is the sheet list (lc.cache), "data" the
# headers and first rows (lc.sheet_data_cache). copy_sheet writes to "dst".
_SHEET_TOOL_CALLS = {
    "clear_values": ({"spreadsheet_id": "sid", "sheet": "Sheet1"}, {("data", "sid")}),
    "update_cells": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "range": "A1", "data": [["x"]]},
        {("data", "sid")},
    ),
    "update_cells_rich_text": (
        {
            "spreadsheet_id": "sid",
            "sheet": "Sheet1",
            "range": "A1",
            "data": [[[{"text": "x", "hyperlink": "https://example.com"}]]],
        },
        {("data", "sid")},
    ),
    "update_cells_mixed": (
        {
            "spreadsheet_id": "sid",
            "sheet": "Sheet1",
            "range": "A1:B1",
            "data": [["x", [{"text": "y"}]]],
        },
        {("data", "sid")},
    ),
    "batch_update_cells": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "ranges": {"A1": [["x"]]}},
        {("data", "sid")},
    ),
    "batch_update": (
        {"spreadsheet_id": "sid", "requests": [{"addSheet": {}}]},
        {("structure", "sid"), ("data", "sid")},
    ),
    "copy_sheet": (
        {
            "src_spreadsheet": "sid",
            "src_sheet": "Sheet1",
            "dst_spreadsheet": "dst",
            "dst_sheet": "Renamed",
        },
        {("structure", "dst")},
    ),
    "duplicate_sheet": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "insert_index": 1},
        {("structure", "sid")},
    ),
    "rename_sheet": (
        {"spreadsheet": "sid", "sheet": "Sheet1", "new_name": "n"},
        {("structure", "sid")},
    ),
    "create_sheet": ({"spreadsheet_id": "sid", "title": "t"}, {("structure", "sid")}),
    "delete_sheet": ({"spreadsheet_id": "sid", "sheet": "Sheet1"}, {("structure", "sid")}),
    "add_rows": ({"spreadsheet_id": "sid", "sheet": "Sheet1", "count": 1}, {("data", "sid")}),
    "add_columns": ({"spreadsheet_id": "sid", "sheet": "Sheet1", "count": 1}, {("data", "sid")}),
    "delete_rows": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "start_row": 0},
        {("data", "sid")},
    ),
    "delete_columns": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "start_column": 0},
        {("data", "sid")},
    ),
    "sort_range": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "range": "A1:B5"},
        {("data", "sid")},
    ),
    # A number format changes the FORMATTED_VALUE strings the data cache holds.
    "format_cells": (
        {
            "spreadsheet_id": "sid",
            "sheet": "Sheet1",
            "range": "A1",
            "number_format_type": "CURRENCY",
        },
        {("data", "sid")},
    ),
    "format_cells_bold": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "range": "A1", "bold": True},
        set(),
    ),
    # A merge clears every merged cell's value but the top-left one.
    "merge_cells": (
        {"spreadsheet_id": "sid", "sheet": "Sheet1", "range": "A1:C1"},
        {("data", "sid")},
    ),
}
_SHEET_CASE_TOOL = {
    "update_cells_rich_text": "update_cells",
    "update_cells_mixed": "update_cells",
    "format_cells_bold": "format_cells",
}

_sheets_tool, _sheets_tools = _make_tool_registry()
sheets_data_module.register(_sheets_tool)
sheets_structure_module.register(_sheets_tool)

# Every response a sheets write can need: the new sheet's properties for
# duplicate_sheet/create_sheet, and copy_sheet's new sheetId.
_SHEET_WRITE_RESPONSE = {
    "sheetId": 7,
    "title": "Copy of Sheet1",
    "replies": [
        {
            "duplicateSheet": {"properties": {"sheetId": 7, "title": "t"}},
            "addSheet": {"properties": {"sheetId": 7, "title": "t"}},
        }
    ],
}


def _sheets_ctx(execute):
    sheets_svc = MagicMock()
    spreadsheets = sheets_svc.spreadsheets.return_value
    for chain in (
        spreadsheets.batchUpdate.return_value,
        spreadsheets.sheets.return_value.copyTo.return_value,
        spreadsheets.values.return_value.update.return_value,
        spreadsheets.values.return_value.batchUpdate.return_value,
        spreadsheets.values.return_value.clear.return_value,
    ):
        chain.execute.side_effect = execute
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.sheets_service = sheets_svc
    lc.drive_service = None  # no modifiedTime check on the sheet lookup
    lc.cache.get_sheets.return_value = [SheetInfo(title="Sheet1", sheet_id=0)]
    seen: list = []
    lc.cache.mark_dirty.side_effect = lambda sid: seen.append(("structure", sid))
    lc.sheet_data_cache.mark_dirty.side_effect = lambda sid: seen.append(("data", sid))
    return ctx, seen


def _sheet_tool(case: str):
    return _sheets_tools[_SHEET_CASE_TOOL.get(case, case)]


def test_every_sheets_write_is_covered():
    # Every tool that reached a cache invalidation before #1265, plus the data
    # writes that had none (clear_values, rows/columns, sort_range).
    covered = {_SHEET_CASE_TOOL.get(c, c) for c in _SHEET_TOOL_CALLS}
    assert {
        "clear_values",
        "update_cells",
        "batch_update_cells",
        "batch_update",
        "copy_sheet",
        "duplicate_sheet",
        "rename_sheet",
        "create_sheet",
        "delete_sheet",
        "add_rows",
        "add_columns",
        "delete_rows",
        "delete_columns",
        "sort_range",
        "format_cells",
        "merge_cells",
    } == covered


@pytest.mark.parametrize("case", sorted(_SHEET_TOOL_CALLS))
async def test_sheets_tool_cancelled_mid_write_marks_dirty_again_once_it_lands(case):
    kwargs, expected = _SHEET_TOOL_CALLS[case]
    blocking = _Blocking(_SHEET_WRITE_RESPONSE)
    ctx, seen = _sheets_ctx(blocking)

    await _cancel_mid_request(partial(_sheet_tool(case), ctx=ctx, **kwargs), blocking)
    assert set(seen) == expected

    landed_from = len(seen)
    blocking.release.set()
    await _wait_for(lambda: set(seen[landed_from:]) == expected)


@pytest.mark.parametrize("case", sorted(_SHEET_TOOL_CALLS))
async def test_sheets_tool_failed_write_marks_dirty(case):
    def execute(**kw):
        raise TimeoutError("timed out; the write may have been applied")

    kwargs, expected = _SHEET_TOOL_CALLS[case]
    ctx, seen = _sheets_ctx(execute)
    with contextlib.suppress(TimeoutError):
        await _sheet_tool(case)(ctx=ctx, **kwargs)
    assert set(seen) == expected


@pytest.mark.parametrize("case", sorted(_SHEET_TOOL_CALLS))
async def test_sheets_tool_successful_write_marks_dirty(case):
    kwargs, expected = _SHEET_TOOL_CALLS[case]
    ctx, seen = _sheets_ctx(lambda **kw: _SHEET_WRITE_RESPONSE)
    await _sheet_tool(case)(ctx=ctx, **kwargs)
    assert set(seen) == expected


@pytest.mark.parametrize("case", sorted(_SHEET_TOOL_CALLS))
async def test_sheets_tool_rejected_write_marks_nothing(case):
    def execute(**kw):
        raise _rejection(400)

    kwargs, _ = _SHEET_TOOL_CALLS[case]
    ctx, seen = _sheets_ctx(execute)
    with contextlib.suppress(HttpError):
        await _sheet_tool(case)(ctx=ctx, **kwargs)
    assert seen == []


async def test_copy_sheet_invalidates_when_its_copy_lands_and_rename_is_rejected():
    # The copy adds a tab; the rename then gets a 400 (the name is taken).
    ctx, seen = _sheets_ctx(lambda **kw: _SHEET_WRITE_RESPONSE)
    spreadsheets = ctx.request_context.lifespan_context.sheets_service.spreadsheets.return_value

    def taken(**kw):
        raise _rejection(400)

    spreadsheets.batchUpdate.return_value.execute.side_effect = taken
    kwargs, expected = _SHEET_TOOL_CALLS["copy_sheet"]

    with contextlib.suppress(HttpError):
        await _sheets_tools["copy_sheet"](ctx=ctx, **kwargs)
    assert set(seen) == expected


# ---------------------------------------------------------------------------
# invalidating: a 4xx after a write that may have landed (#1265)
# ---------------------------------------------------------------------------


def _request(method: str, outcome):
    """An `.execute` bound to a request object with `method`, as googleapiclient's is."""

    class _Request:
        def __init__(self) -> None:
            self.method = method

        def execute(self, **kw):
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    return _Request().execute


async def _run_block(*requests):
    calls = []
    with contextlib.suppress(HttpError, TimeoutError), invalidating(lambda: calls.append(True)):
        for execute in requests:
            await execute_in_thread(execute, None)
    return len(calls)


@pytest.fixture
def _no_transport(monkeypatch):
    monkeypatch.setattr(http_transport, "thread_http", lambda service: None)


@pytest.mark.usefixtures("_no_transport")
class TestInvalidatingAfterALandedWrite:
    async def test_a_lone_rejection_skips_the_callback(self):
        assert await _run_block(_request("POST", _rejection(400))) == 0

    async def test_a_rejection_after_a_landed_write_runs_it(self):
        assert await _run_block(_request("POST", {}), _request("POST", _rejection(400))) == 1

    async def test_a_rejection_after_a_write_that_may_have_landed_runs_it(self):
        # The block's caller caught the timeout and went on to a second write.
        async def timed_out_then_rejected():
            with contextlib.suppress(TimeoutError):
                await execute_in_thread(_request("POST", TimeoutError("?")), None)
            await execute_in_thread(_request("PATCH", _rejection(400)), None)

        calls = []
        with contextlib.suppress(HttpError), invalidating(lambda: calls.append(True)):
            await timed_out_then_rejected()
        assert calls == [True]

    async def test_a_rejection_after_a_read_skips_it(self):
        assert await _run_block(_request("GET", {}), _request("POST", _rejection(400))) == 0

    async def test_a_rejection_after_a_rejected_write_skips_it(self):
        assert (
            await _run_block(_request("POST", _rejection(409)), _request("POST", _rejection(400)))
            == 0
        )

    async def test_a_nested_blocks_landed_write_counts_for_the_outer_block(self):
        outer, inner = [], []
        with contextlib.suppress(HttpError), invalidating(lambda: outer.append(True)):
            with invalidating(lambda: inner.append(True)):
                await execute_in_thread(_request("POST", {}), None)
            await execute_in_thread(_request("POST", _rejection(400)), None)
        assert inner == [True]
        assert outer == [True]


# ---------------------------------------------------------------------------
# Calendar write tools (#1265)
# ---------------------------------------------------------------------------

_cal_tool, _cal_tools = _make_tool_registry()
calendar_module.register(_cal_tool)

# Every calendar write marks every calendar entry ("all"): `get_calendar` caches
# under the caller's spelling, so `primary` and the address are two entries.
_CAL_TOOL_CALLS = {
    "create_calendar": ({"summary": "s"}, {"all"}),
    "update_calendar": ({"calendar_id": "cal1", "summary": "s", "color_id": "3"}, {"all"}),
    "delete_calendar": ({"calendar_id": "cal1"}, {"all"}),
    "add_calendar_to_list": ({"calendar_id": "cal1"}, {"all"}),
    "remove_calendar_from_list": ({"calendar_id": "cal1"}, {"all"}),
    "add_calendar_acl": (
        {"calendar_id": "cal1", "role": "reader", "scope_type": "user", "scope_value": "a@b.c"},
        {"all"},
    ),
    "remove_calendar_acl": ({"calendar_id": "cal1", "rule_id": "r1"}, {"all"}),
}

# calendar_cache holds no event data, so an event write invalidates nothing.
_CAL_EVENT_CALLS = {
    "create_event": {
        "calendar_id": "cal1",
        "summary": "e",
        "start": "2026-01-01",
        "end": "2026-01-02",
    },
    "update_event": {"calendar_id": "cal1", "event_id": "ev1", "summary": "e"},
    "delete_event": {"calendar_id": "cal1", "event_id": "ev1"},
}


def _calendar_ctx(execute):
    cal_svc = MagicMock()
    for resource, methods in (
        ("calendars", ("insert", "patch", "delete")),
        ("calendarList", ("insert", "patch", "delete")),
        ("acl", ("insert", "delete")),
        ("events", ("insert", "patch", "delete")),
    ):
        for method in methods:
            chain = getattr(getattr(cal_svc, resource).return_value, method).return_value
            chain.execute.side_effect = execute
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.calendar_service = cal_svc
    seen: list = []
    lc.calendar_cache.mark_dirty.side_effect = lambda cid: seen.append(cid)
    lc.calendar_cache.mark_all_dirty.side_effect = lambda: seen.append("all")
    return ctx, seen


_CAL_WRITE_RESPONSE = {"id": "cal1", "start": {"date": "2026-01-01"}, "end": {}}


def test_every_calendar_write_is_covered():
    writes = {
        name for name, fn in _cal_tools.items() if not name.startswith(("list_", "get_", "find_"))
    }
    assert writes == set(_CAL_TOOL_CALLS) | set(_CAL_EVENT_CALLS)


@pytest.mark.parametrize("tool_name", sorted(_CAL_EVENT_CALLS))
async def test_event_write_invalidates_nothing_on_any_outcome(tool_name):
    kwargs = _CAL_EVENT_CALLS[tool_name]

    ctx, seen = _calendar_ctx(lambda **kw: _CAL_WRITE_RESPONSE)
    await _cal_tools[tool_name](ctx=ctx, **kwargs)

    def timeout(**kw):
        raise TimeoutError("may have landed")

    failed_ctx, failed_seen = _calendar_ctx(timeout)
    assert "error" in await _cal_tools[tool_name](ctx=failed_ctx, **kwargs)

    blocking = _Blocking(_CAL_WRITE_RESPONSE)
    cancelled_ctx, cancelled_seen = _calendar_ctx(blocking)
    await _cancel_mid_request(partial(_cal_tools[tool_name], ctx=cancelled_ctx, **kwargs), blocking)
    blocking.release.set()
    await _wait_for(lambda: blocking.landed)
    await anyio.sleep(0.05)  # let an abandoned-call hook, if any, run on the loop

    assert seen == failed_seen == cancelled_seen == []


async def test_update_calendar_invalidates_when_its_patch_lands_and_color_is_rejected():
    # calendars().patch lands; calendarList().patch(colorId=...) returns a 400.
    ctx, seen = _calendar_ctx(lambda **kw: _CAL_WRITE_RESPONSE)
    cal_svc = ctx.request_context.lifespan_context.calendar_service

    def bad_color(**kw):
        raise _rejection(400)

    cal_svc.calendarList.return_value.patch.return_value.execute.side_effect = bad_color

    result = await _cal_tools["update_calendar"](
        calendar_id="cal1", summary="renamed", color_id="999", ctx=ctx
    )
    assert "error" in result
    assert seen == ["all"]


@pytest.mark.parametrize("tool_name", sorted(_CAL_TOOL_CALLS))
async def test_calendar_tool_cancelled_mid_write_marks_dirty_again_once_it_lands(tool_name):
    kwargs, expected = _CAL_TOOL_CALLS[tool_name]
    blocking = _Blocking(_CAL_WRITE_RESPONSE)
    ctx, seen = _calendar_ctx(blocking)

    await _cancel_mid_request(partial(_cal_tools[tool_name], ctx=ctx, **kwargs), blocking)
    assert set(seen) == expected

    landed_from = len(seen)
    blocking.release.set()
    await _wait_for(lambda: set(seen[landed_from:]) == expected)


@pytest.mark.parametrize("tool_name", sorted(_CAL_TOOL_CALLS))
async def test_calendar_tool_failed_write_marks_dirty(tool_name):
    def execute(**kw):
        raise TimeoutError("timed out; the write may have been applied")

    kwargs, expected = _CAL_TOOL_CALLS[tool_name]
    ctx, seen = _calendar_ctx(execute)
    result = await _cal_tools[tool_name](ctx=ctx, **kwargs)
    assert "error" in result
    assert set(seen) == expected


@pytest.mark.parametrize("tool_name", sorted(_CAL_TOOL_CALLS))
async def test_calendar_tool_successful_write_marks_dirty(tool_name):
    kwargs, expected = _CAL_TOOL_CALLS[tool_name]
    ctx, seen = _calendar_ctx(lambda **kw: _CAL_WRITE_RESPONSE)
    await _cal_tools[tool_name](ctx=ctx, **kwargs)
    assert set(seen) == expected


@pytest.mark.parametrize("tool_name", sorted(_CAL_TOOL_CALLS))
async def test_calendar_tool_rejected_write_marks_nothing(tool_name):
    def execute(**kw):
        raise _rejection(403)

    kwargs, _ = _CAL_TOOL_CALLS[tool_name]
    ctx, seen = _calendar_ctx(execute)
    result = await _cal_tools[tool_name](ctx=ctx, **kwargs)
    assert "error" in result
    assert seen == []


# ---------------------------------------------------------------------------
# Calendar reads don't overwrite an invalidation that lands mid-fetch (#1265)
# ---------------------------------------------------------------------------


def _calendar_read_ctx(cache, execute_attr, response):
    cal_svc = MagicMock()

    def execute(**kw):
        # A write's invalidation landing while the read is in flight.
        cache.mark_dirty("cal1")
        return response

    getattr(
        cal_svc.calendarList.return_value, execute_attr
    ).return_value.execute.side_effect = execute
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.calendar_service = cal_svc
    lc.calendar_cache = cache
    return ctx


async def test_calendar_list_fetch_does_not_overwrite_a_mid_fetch_invalidation():
    cache = CalendarCache(db_path=":memory:", ttl=60, principal="test")
    ctx = _calendar_read_ctx(cache, "list", {"items": [{"id": "cal1", "summary": "old"}]})

    result = await _cal_tools["list_calendars"](ctx=ctx)

    assert [c["summary"] for c in result] == ["old"]
    assert cache.get_list() is None


async def test_get_calendar_fetch_does_not_overwrite_a_mid_fetch_invalidation():
    cache = CalendarCache(db_path=":memory:", ttl=60, principal="test")
    ctx = _calendar_read_ctx(cache, "get", {"id": "cal1", "summary": "old"})

    result = await _cal_tools["get_calendar"](calendar_id="cal1", ctx=ctx)

    assert result["summary"] == "old"
    assert cache.get("cal1") is None


async def test_calendar_list_fetch_stores_when_nothing_invalidates():
    cache = CalendarCache(db_path=":memory:", ttl=60, principal="test")
    cal_svc = MagicMock()
    cal_svc.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "cal1", "summary": "s"}]
    }
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    lc.calendar_service = cal_svc
    lc.calendar_cache = cache

    await _cal_tools["list_calendars"](ctx=ctx)

    assert [c["id"] for c in cache.get_list()] == ["cal1"]
