"""Tests for tools/drive/files.py (search_spreadsheets, create_folder, move_file, delete_file, etc.)."""

import csv
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.cache import DriveFolderCache
from mcp_gee_sweet.tools.drive import _SA_QUOTA_ERROR, _USER_QUOTA_ERROR
from mcp_gee_sweet.tools.drive import files as drive_files_module

from ..fakes import as_service_account


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False, **_):
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
drive_files_module.register(_drive_tool)


def _assert_error_list(result, underlying: str) -> None:
    """The "error dict, not raised" contract: one {"error": ...} item carrying the
    underlying exception's text. Doesn't pin the message's prefix wording (#574)."""
    assert len(result) == 1
    assert set(result[0]) == {"error"}
    assert underlying in result[0]["error"]


class TestSearchSpreadsheets:
    """Bug: single quotes in query were interpolated raw into the Drive query string."""

    def _drive_service(self):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": []}
        return mock

    def _captured_q(self, drive_svc):
        return drive_svc.files.return_value.list.call_args.kwargs["q"]

    async def test_single_quote_is_escaped(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="it's a test", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    async def test_escaped_form_used_not_raw(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="O'Brien", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "O\\'Brien" in q
        # The apostrophe in 'O'Brien' must be preceded by a backslash
        idx = q.index("'Brien")
        assert q[idx - 1] == "\\"

    async def test_query_without_quotes_passes_through(self):
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="budget 2024", ctx=ctx)
        q = self._captured_q(drive_svc)
        assert "budget 2024" in q

    async def test_api_error_returns_error_dict_not_raised(self):
        """TC-D35: an API/auth failure must surface as [{"error": ...}], not propagate."""
        drive_svc = self._drive_service()
        drive_svc.files.return_value.list.return_value.execute.side_effect = RuntimeError(
            "simulated API failure"
        )
        ctx = _make_ctx(drive_service=drive_svc)
        result = await _drive_tools["search_spreadsheets"](query="budget 2024", ctx=ctx)
        _assert_error_list(result, "simulated API failure")

    async def test_requests_starred_field(self):
        """#388: search_spreadsheets shares search_files' starred exposure."""
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="budget", ctx=ctx)
        fields_arg = drive_svc.files.return_value.list.call_args.kwargs["fields"]
        assert "starred" in fields_arg

    async def test_result_includes_starred_field(self):
        drive_svc = MagicMock()
        drive_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {
                    "id": "fid1",
                    "name": "budget.gsheet",
                    "webViewLink": "https://drive.google.com/fid1",
                    "starred": True,
                }
            ]
        }
        ctx = _make_ctx(drive_service=drive_svc)
        result = await _drive_tools["search_spreadsheets"](query="budget", ctx=ctx)
        assert result[0]["starred"] is True

    async def test_query_excludes_trashed(self):
        """#1054: trashed spreadsheets came back from search_spreadsheets."""
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc)
        await _drive_tools["search_spreadsheets"](query="budget", ctx=ctx)
        # A top-level AND term, not ORed into the free-text group.
        assert self._captured_q(drive_svc) == (
            "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false and "
            "(name contains 'budget' or fullText contains 'budget')"
        )


class TestSearchFiles:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _captured_q(self, drive_svc):
        return drive_svc.files.return_value.list.call_args.kwargs["q"]

    async def test_requests_starred_field(self):
        """#388: get_file_metadata/list_files/search_files now surface starred."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="budget", ctx=ctx)
        fields_arg = svc.files.return_value.list.call_args.kwargs["fields"]
        assert "starred" in fields_arg

    async def test_result_includes_starred_field(self):
        svc = self._drive_service(
            files=[
                {
                    "id": "fid1",
                    "name": "budget.pdf",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "webViewLink": "https://drive.google.com/fid1",
                    "starred": True,
                }
            ]
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["search_files"](query="budget", ctx=ctx)
        assert result["files"][0]["starred"] is True

    async def test_single_quote_is_escaped(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="it's a test", ctx=ctx)
        q = self._captured_q(svc)
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    async def test_escaped_form_used_not_raw(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="O'Brien", ctx=ctx)
        q = self._captured_q(svc)
        assert "O\\'Brien" in q
        # The apostrophe in 'O'Brien' must be preceded by a backslash
        idx = q.index("'Brien")
        assert q[idx - 1] == "\\"

    async def test_query_without_quotes_passes_through(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="budget 2024", ctx=ctx)
        q = self._captured_q(svc)
        assert "budget 2024" in q

    async def test_mime_type_filter_added_to_query(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="budget", mime_type="application/pdf", ctx=ctx)
        q = self._captured_q(svc)
        assert "mimeType='application/pdf'" in q

    async def test_folder_id_filter_added_to_query(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="budget", folder_id="folder1", ctx=ctx)
        q = self._captured_q(svc)
        assert "'folder1' in parents" in q

    @pytest.mark.parametrize(
        ("kwargs", "extra"),
        [
            ({}, ""),
            (
                {"mime_type": "application/vnd.google-apps.folder"},
                " and mimeType='application/vnd.google-apps.folder'",
            ),
            ({"folder_id": "folder1"}, " and 'folder1' in parents"),
        ],
    )
    async def test_query_excludes_trashed(self, kwargs, extra):
        """#1054: trashed files and folders came back from search_files. The term
        must be a top-level AND, not ORed into the free-text group."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="budget", ctx=ctx, **kwargs)
        assert self._captured_q(svc) == (
            "(name contains 'budget' or fullText contains 'budget') and trashed=false" + extra
        )

    async def test_folder_id_quote_cannot_break_out_of_string(self):
        """#1054 round 1: an unescaped `'` in folder_id could close the string and
        OR in `trashed=true`, bypassing the trashed filter."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](
            query="budget", folder_id="x' in parents or trashed=true or 'y", ctx=ctx
        )
        assert self._captured_q(svc).endswith(
            " and trashed=false and 'x\\' in parents or trashed=true or \\'y' in parents"
        )

    async def test_folder_id_backslash_escaped(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["search_files"](query="budget", folder_id="a\\b", ctx=ctx)
        assert self._captured_q(svc).endswith(" and 'a\\\\b' in parents")

    async def test_api_error_returns_error_dict_not_raised(self):
        """An API/auth failure must surface as {"error": ...}, not propagate."""
        svc = self._drive_service()
        svc.files.return_value.list.return_value.execute.side_effect = RuntimeError(
            "simulated API failure"
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["search_files"](query="budget", ctx=ctx)
        assert set(result) == {"error"}
        assert "simulated API failure" in result["error"]


class TestSearchFilesFinder:
    """#1528: search_files absorbs search_spreadsheets, list_spreadsheets,
    list_folders, list_recent_files and list_shared_with_me, and returns
    {"files", "exhaustive"} (#1202)."""

    def _drive_service(self, response=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = (
            response if response is not None else {"files": []}
        )
        return mock

    async def _call(self, response=None, **kwargs):
        svc = self._drive_service(response)
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["search_files"](ctx=ctx, **kwargs)
        list_kwargs = svc.files.return_value.list.call_args
        return result, (list_kwargs.kwargs if list_kwargs else None)

    @pytest.mark.parametrize("query", [None, "", "   "])
    async def test_no_query_drops_the_text_clause(self, query):
        _, list_kwargs = await self._call(
            query=query, mime_type="application/vnd.google-apps.spreadsheet"
        )
        assert list_kwargs["q"] == (
            "trashed=false and mimeType='application/vnd.google-apps.spreadsheet'"
        )

    async def test_no_arguments_lists_everything_not_trashed(self):
        _, list_kwargs = await self._call()
        assert list_kwargs["q"] == "trashed=false"
        assert list_kwargs["corpora"] == "allDrives"
        assert list_kwargs["orderBy"] == "modifiedTime desc"
        assert list_kwargs["pageSize"] == 20

    @pytest.mark.parametrize(
        ("order_by", "expected"), [("modified", "modifiedTime desc"), ("name", "name")]
    )
    async def test_order_by(self, order_by, expected):
        _, list_kwargs = await self._call(order_by=order_by)
        assert list_kwargs["orderBy"] == expected

    async def test_name_order_with_query_is_an_error_without_a_call(self):
        """Drive answers orderBy=name on a fullText query with a 403 ("Sorting is not
        supported for queries with fullText terms", checked live)."""
        result, list_kwargs = await self._call(query="plan", order_by="name")
        assert "order_by='name'" in result["error"]
        assert list_kwargs is None

    async def test_blank_query_allows_name_order(self):
        result, list_kwargs = await self._call(query="  ", order_by="name")
        assert "error" not in result
        assert list_kwargs["orderBy"] == "name"

    async def test_invalid_order_by_is_an_error_without_a_call(self):
        result, list_kwargs = await self._call(order_by="size")
        assert "order_by" in result["error"]
        assert list_kwargs is None

    async def test_shared_with_me_keeps_default_corpus(self):
        """The user corpus holds what's shared directly with the caller, and
        sharedWithMe=true is the scope (#1127)."""
        _, list_kwargs = await self._call(shared_with_me=True)
        assert list_kwargs["q"] == "trashed=false and sharedWithMe=true"
        assert "corpora" not in list_kwargs
        assert list_kwargs["includeItemsFromAllDrives"] is True
        assert list_kwargs["supportsAllDrives"] is True

    async def test_modified_within_days_adds_a_cutoff(self, monkeypatch):
        from datetime import UTC, datetime

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)

        monkeypatch.setattr(drive_files_module, "datetime", _FixedDatetime)
        _, list_kwargs = await self._call(modified_within_days=7)
        assert list_kwargs["q"] == "trashed=false and modifiedTime > '2026-11-12T12:00:00'"

    @pytest.mark.parametrize("days", [0, -3, 36501, 1_000_000, 10**9])
    async def test_out_of_range_days_is_an_error_without_a_call(self, days):
        """PR #1558 QA round 1: a huge value overflowed the cutoff and crashed the
        call with no message."""
        result, list_kwargs = await self._call(modified_within_days=days)
        assert "modified_within_days" in result["error"]
        assert list_kwargs is None

    async def test_window_before_the_epoch_adds_no_clause(self):
        """Drive answers a modifiedTime before 1970 with 400 Invalid Value (checked
        live); a window reaching back that far holds every file anyway."""
        result, list_kwargs = await self._call(modified_within_days=36500)
        assert "error" not in result
        assert list_kwargs["q"] == "trashed=false"

    async def test_window_after_the_epoch_keeps_its_cutoff(self):
        _, list_kwargs = await self._call(modified_within_days=365)
        assert "modifiedTime > '" in list_kwargs["q"]

    async def test_file_with_empty_parents_maps_to_none(self):
        result, _ = await self._call(
            response={"files": [{"id": "f", "name": "n", "mimeType": "m", "parents": []}]}
        )
        assert result["files"][0]["parent"] is None

    async def test_unmappable_file_is_an_error_dict_not_raised(self):
        """PR #1558 QA round 1: the mapping ran outside the try, so a file it
        couldn't read escaped as an uncaught exception."""
        result, _ = await self._call(response={"files": [{"name": "no id"}]})
        assert set(result) == {"error"}
        assert result["error"].startswith("Search failed")

    async def test_filters_combine(self):
        _, list_kwargs = await self._call(
            query="plan",
            mime_type="application/vnd.google-apps.folder",
            folder_id="f1",
            shared_with_me=True,
        )
        assert list_kwargs["q"] == (
            "(name contains 'plan' or fullText contains 'plan') and trashed=false"
            " and mimeType='application/vnd.google-apps.folder' and 'f1' in parents"
            " and sharedWithMe=true"
        )

    async def test_max_results_clamped_at_1000(self):
        _, list_kwargs = await self._call(max_results=5000)
        assert list_kwargs["pageSize"] == 1000

    async def test_requests_truncation_signals(self):
        _, list_kwargs = await self._call()
        assert "nextPageToken" in list_kwargs["fields"]
        assert "incompleteSearch" in list_kwargs["fields"]

    @pytest.mark.parametrize(
        ("response_extra", "exhaustive"),
        [
            ({}, True),
            ({"nextPageToken": "tok"}, False),
            ({"incompleteSearch": True}, False),
            ({"incompleteSearch": False}, True),
        ],
    )
    async def test_exhaustive(self, response_extra, exhaustive):
        result, _ = await self._call(response={"files": [], **response_extra})
        assert result == {"files": [], "exhaustive": exhaustive}

    async def test_file_fields_include_created_time(self):
        result, _ = await self._call(
            response={
                "files": [
                    {
                        "id": "fid1",
                        "name": "Budget",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                        "createdTime": "2026-01-01T00:00:00Z",
                        "modifiedTime": "2026-06-01T00:00:00Z",
                        "owners": [{"emailAddress": "a@example.com"}],
                        "parents": ["par1"],
                        "webViewLink": "https://docs.google.com/x",
                        "starred": True,
                    }
                ]
            }
        )
        assert result["files"] == [
            {
                "id": "fid1",
                "name": "Budget",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "created_time": "2026-01-01T00:00:00Z",
                "modified_time": "2026-06-01T00:00:00Z",
                "owners": ["a@example.com"],
                "parent": "par1",
                "web_link": "https://docs.google.com/x",
                "starred": True,
            }
        ]


class TestFinderDeprecations:
    """#1528: the absorbed tools stay callable for one release, each description
    opening with what replaces it."""

    @pytest.mark.parametrize(
        ("tool_name", "replacement"),
        [
            ("search_spreadsheets", "`search_files` with `mime_type="),
            ("list_spreadsheets", "`search_files`"),
            ("list_folders", "`search_files`"),
            ("list_recent_files", "`search_files`"),
            ("list_shared_with_me", "`search_files`"),
            ("unstar_file", "`star_file` with `starred=False`"),
        ],
    )
    def test_deprecated(self, tool_name, replacement):
        from mcp_gee_sweet.deprecation import tool_deprecation

        func = _drive_tools[tool_name]
        assert tool_deprecation(func) is not None
        assert func.__doc__.startswith(f"Deprecated: use {replacement}")

    @pytest.mark.parametrize(
        ("tool_name", "needed"),
        [
            # PR #1558 QA round 1: following a note must give back what the old
            # default call returned: its count, its sort, and the renamed key.
            ("list_folders", ("`order_by='name'`", "`max_results=100`")),
            ("list_spreadsheets", ("`max_results=100`", "add `folder_id`")),
            ("list_shared_with_me", ("`max_results=50`", "`mimeType`")),
            ("list_recent_files", ("`mimeType`",)),
        ],
    )
    def test_note_names_what_keeps_the_old_result(self, tool_name, needed):
        note = _drive_tools[tool_name].__doc__.split("\n\n", 1)[0]
        for phrase in needed:
            assert phrase in note

    @pytest.mark.parametrize(
        ("tool_name", "phrase"),
        [
            ("list_spreadsheets", "plus `folder_id`"),
            ("search_spreadsheets", "special case"),
            ("list_spreadsheets", "List all spreadsheets"),
            ("search_files", "convenience wrapper"),
            ("list_files", "list_spreadsheets"),
            ("list_files", "cache entry"),
            ("list_spreadsheets", "nextPageToken"),
        ],
    )
    def test_description_drops_stale_claim(self, tool_name, phrase):
        assert phrase not in _drive_tools[tool_name].__doc__

    @pytest.mark.parametrize("tool_name", ["star_file", "search_files", "list_files"])
    def test_survivors_not_deprecated(self, tool_name):
        from mcp_gee_sweet.deprecation import tool_deprecation

        assert tool_deprecation(_drive_tools[tool_name]) is None


class TestFileMutations:
    """Mutating file ops (create_folder, move_file, delete_file) must invalidate the folder cache."""

    def _drive_file_response(self, **kwargs):
        defaults = {
            "id": "fid1",
            "name": "file.txt",
            "parents": ["parent1"],
            "mimeType": "text/plain",
            "webViewLink": "https://example.com",
        }
        return {**defaults, **kwargs}

    async def test_create_folder_with_parent_marks_dirty(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder",
            "name": "MyFolder",
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        await _drive_tools["create_folder"](name="MyFolder", parent_folder_id="par1", ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_create_folder_without_parent_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder",
            "name": "MyFolder",
            "parents": [],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        await _drive_tools["create_folder"](name="MyFolder", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()

    async def test_move_file_marks_old_and_new_parent_dirty(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["old_par"]}
        mock.files.return_value.update.return_value.execute.return_value = (
            self._drive_file_response(parents=["dest_par"])
        )
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["move_file"](file_id="fid1", destination_folder_id="dest_par", ctx=ctx)
        calls = [c.args[0] for c in folder_cache.mark_dirty.call_args_list]
        assert "old_par" in calls
        assert "dest_par" in calls

    async def test_delete_file_trash_marks_parent_dirty_before_trash(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        mock.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["delete_file"](file_id="fid1", permanent=False, ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_delete_file_permanent_marks_parent_dirty_before_delete(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        mock.files.return_value.delete.return_value.execute.return_value = None
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_delete_file_requests_capabilities_in_parents_lookup(self):
        """#876: the capability check rides on the existing get, no extra request."""
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"parents": ["par1"]}
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        mock.files.return_value.get.assert_called_once()
        fields = mock.files.return_value.get.call_args.kwargs["fields"]
        assert "canDelete" in fields
        assert "canTrash" in fields
        assert "driveId" in fields

    async def test_delete_file_permanent_without_can_delete_raises_before_delete(self):
        """#876: Content manager on a Shared Drive gets a clear error, not Drive's 404."""
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {
            "parents": ["par1"],
            "driveId": "drive1",
            "capabilities": {"canDelete": False, "canTrash": True},
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        with pytest.raises(ValueError, match="permanent=False") as exc_info:
            await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        assert "Shared Drive" in str(exc_info.value)
        mock.files.return_value.delete.assert_not_called()
        folder_cache.mark_dirty.assert_not_called()

    async def test_delete_file_permanent_without_can_delete_on_my_drive_omits_shared_drive_note(
        self,
    ):
        """A non-owner editor of a My Drive file also lacks canDelete; no Shared Drive aside."""
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {
            "parents": ["par1"],
            "capabilities": {"canDelete": False, "canTrash": True},
        }
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        with pytest.raises(ValueError) as exc_info:
            await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        assert "Shared Drive" not in str(exc_info.value)
        assert "permanent=False" in str(exc_info.value)
        mock.files.return_value.delete.assert_not_called()

    async def test_delete_file_permanent_without_delete_or_trash_omits_trash_hint(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {
            "parents": ["par1"],
            "capabilities": {"canDelete": False, "canTrash": False},
        }
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        with pytest.raises(ValueError) as exc_info:
            await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        assert "permanent=False" not in str(exc_info.value)
        mock.files.return_value.delete.assert_not_called()

    async def test_delete_file_permanent_with_can_delete_calls_delete(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {
            "parents": ["par1"],
            "capabilities": {"canDelete": True, "canTrash": True},
        }
        mock.files.return_value.delete.return_value.execute.return_value = None
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        result = await _drive_tools["delete_file"](file_id="fid1", permanent=True, ctx=ctx)
        mock.files.return_value.delete.assert_called_once_with(
            fileId="fid1", supportsAllDrives=True
        )
        assert result == {"fileId": "fid1", "action": "deleted"}

    async def test_delete_file_trash_ignores_can_delete_false(self):
        """Trashing only needs canTrash; a missing canDelete must not block it."""
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {
            "parents": ["par1"],
            "capabilities": {"canDelete": False, "canTrash": True},
        }
        mock.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        result = await _drive_tools["delete_file"](file_id="fid1", permanent=False, ctx=ctx)
        assert result == {"fileId": "fid1", "action": "trashed"}

    async def test_restore_file_marks_parent_dirty(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        result = await _drive_tools["restore_file"](file_id="fid1", ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"trashed": False},
            supportsAllDrives=True,
            fields="id,parents",
        )
        folder_cache.mark_dirty.assert_called_once_with("par1")
        assert result == {"fileId": "fid1", "action": "restored"}

    async def test_restore_file_no_parents_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {"id": "fid1"}
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["restore_file"](file_id="fid1", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()

    async def test_empty_trash_defaults_to_my_drive_no_drive_id(self):
        mock = MagicMock()
        mock.files.return_value.emptyTrash.return_value.execute.return_value = {}
        ctx = _make_ctx(drive_service=mock)
        result = await _drive_tools["empty_trash"](ctx=ctx)
        mock.files.return_value.emptyTrash.assert_called_once_with()
        assert result == {"action": "trash_emptied", "drive_id": None}

    async def test_empty_trash_with_drive_id_scopes_to_shared_drive(self):
        mock = MagicMock()
        mock.files.return_value.emptyTrash.return_value.execute.return_value = {}
        ctx = _make_ctx(drive_service=mock)
        result = await _drive_tools["empty_trash"](drive_id="shared1", ctx=ctx)
        mock.files.return_value.emptyTrash.assert_called_once_with(driveId="shared1")
        assert result == {"action": "trash_emptied", "drive_id": "shared1"}

    async def test_restore_file_nonexistent_id_propagates_error(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        with pytest.raises(HttpError):
            await _drive_tools["restore_file"](file_id="invalidid123xyz", ctx=ctx)

    async def test_empty_trash_api_error_propagates(self):
        mock = MagicMock()
        mock.files.return_value.emptyTrash.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock)
        with pytest.raises(HttpError):
            await _drive_tools["empty_trash"](ctx=ctx)


class TestCreateShortcut:
    """create_shortcut (#141) creates an application/vnd.google-apps.shortcut file."""

    async def test_explicit_name_and_folder_used_as_is(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "shortcut1",
            "name": "My Shortcut",
            "parents": ["par1"],
            "shortcutDetails": {"targetId": "target1", "targetMimeType": "text/plain"},
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        result = await _drive_tools["create_shortcut"](
            target_file_id="target1", folder_id="par1", name="My Shortcut", ctx=ctx
        )
        mock.files.return_value.get.assert_not_called()
        body = mock.files.return_value.create.call_args.kwargs["body"]
        assert body == {
            "name": "My Shortcut",
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": "target1"},
            "parents": ["par1"],
        }
        folder_cache.mark_dirty.assert_called_once_with("par1")
        assert result == {
            "shortcutId": "shortcut1",
            "name": "My Shortcut",
            "parent": "par1",
            "targetId": "target1",
            "targetMimeType": "text/plain",
        }

    async def test_no_name_defaults_to_target_file_name(self):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = {"name": "Original.txt"}
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "shortcut1",
            "name": "Original.txt",
            "parents": [],
            "shortcutDetails": {"targetId": "target1"},
        }
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        await _drive_tools["create_shortcut"](target_file_id="target1", ctx=ctx)
        mock.files.return_value.get.assert_called_once_with(
            fileId="target1", fields="name", supportsAllDrives=True
        )
        body = mock.files.return_value.create.call_args.kwargs["body"]
        assert body["name"] == "Original.txt"

    async def test_no_folder_id_falls_back_to_configured_default(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "shortcut1",
            "name": "Shortcut",
            "parents": ["default_folder"],
            "shortcutDetails": {"targetId": "target1"},
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(
            drive_service=mock, drive_folder_cache=folder_cache, folder_id="default_folder"
        )
        await _drive_tools["create_shortcut"](target_file_id="target1", name="Shortcut", ctx=ctx)
        body = mock.files.return_value.create.call_args.kwargs["body"]
        assert body["parents"] == ["default_folder"]
        folder_cache.mark_dirty.assert_called_once_with("default_folder")

    async def test_no_folder_no_default_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "shortcut1",
            "name": "Shortcut",
            "parents": [],
            "shortcutDetails": {"targetId": "target1"},
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache, folder_id=None)
        result = await _drive_tools["create_shortcut"](
            target_file_id="target1", name="Shortcut", ctx=ctx
        )
        folder_cache.mark_dirty.assert_not_called()
        assert result["parent"] == "root"


class TestStarFile:
    """star_file/unstar_file (#139) set starred via files().update and mark the
    file's parent folder(s) dirty in drive_folder_cache (#388, TC-D260)."""

    async def test_star_file_sets_starred_true(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": True,
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        result = await _drive_tools["star_file"](file_id="fid1", ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"starred": True},
            supportsAllDrives=True,
            fields="id, name, starred, parents",
        )
        assert result == {"fileId": "fid1", "name": "file.txt", "starred": True}
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_star_file_no_parents_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": True,
            "parents": [],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["star_file"](file_id="fid1", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()

    async def test_unstar_file_sets_starred_false(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": False,
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        result = await _drive_tools["unstar_file"](file_id="fid1", ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"starred": False},
            supportsAllDrives=True,
            fields="id, name, starred, parents",
        )
        assert result == {"fileId": "fid1", "name": "file.txt", "starred": False}
        folder_cache.mark_dirty.assert_called_once_with("par1")

    @pytest.mark.parametrize("starred", [True, False])
    async def test_star_file_starred_param(self, starred):
        """#1528: star_file(starred=False) is unstar_file."""
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": starred,
            "parents": ["par1"],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        result = await _drive_tools["star_file"](file_id="fid1", starred=starred, ctx=ctx)
        mock.files.return_value.update.assert_called_once_with(
            fileId="fid1",
            body={"starred": starred},
            supportsAllDrives=True,
            fields="id, name, starred, parents",
        )
        assert result == {"fileId": "fid1", "name": "file.txt", "starred": starred}
        folder_cache.mark_dirty.assert_called_once_with("par1")

    async def test_unstar_file_no_parents_no_dirty_call(self):
        mock = MagicMock()
        mock.files.return_value.update.return_value.execute.return_value = {
            "id": "fid1",
            "name": "file.txt",
            "starred": False,
            "parents": [],
        }
        folder_cache = MagicMock()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=folder_cache)
        await _drive_tools["unstar_file"](file_id="fid1", ctx=ctx)
        folder_cache.mark_dirty.assert_not_called()


def _quota_http_error():
    """Build a 403 storageQuotaExceeded HttpError as returned by the Drive API."""
    resp = MagicMock()
    resp.status = 403
    return HttpError(
        resp=resp,
        content=b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}',
    )


def _other_403_error():
    """Build a generic 403 that is NOT quota-related."""
    resp = MagicMock()
    resp.status = 403
    return HttpError(resp=resp, content=b'{"error": {"reason": "forbidden"}}')


class TestQuotaErrors:
    """create_spreadsheet and copy_file return a helpful error dict on storageQuotaExceeded.

    The raw Google 403 is replaced with an actionable message pointing the caller
    at server://auth-status and suggesting OAuth/ADC.  Non-quota 403s must still
    propagate so callers can distinguish permission errors from quota errors.
    """

    def _assert_helpful_error(self, result):
        assert "error" in result
        assert "storageQuotaExceeded" not in result["error"]
        assert "This service account has no My Drive storage" in result["error"]
        assert "server://auth-status" in result["error"]

    async def test_create_spreadsheet_quota_returns_error_dict(self):
        mock = as_service_account(MagicMock())
        mock.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        result = await _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)
        self._assert_helpful_error(result)

    async def test_copy_file_quota_returns_error_dict(self):
        mock = as_service_account(MagicMock())
        mock.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock())
        result = await _drive_tools["copy_file"](file_id="fid", ctx=ctx)
        self._assert_helpful_error(result)

    @pytest.mark.parametrize("tool", ["create_spreadsheet", "copy_file"])
    async def test_user_identity_quota_says_storage_is_full(self, tool):
        # A user whose own Drive is full must not be told to switch to OAuth (#1009).
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        mock.files.return_value.copy.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        kwargs = {"title": "Test"} if tool == "create_spreadsheet" else {"file_id": "fid"}
        result = await _drive_tools[tool](ctx=ctx, **kwargs)
        assert result == {"error": _USER_QUOTA_ERROR}

    async def test_create_spreadsheet_non_quota_403_still_raises(self):
        """A 403 that is not storageQuotaExceeded must propagate — not be swallowed."""
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(drive_service=mock, drive_folder_cache=MagicMock(), folder_id=None)
        with pytest.raises(HttpError):
            await _drive_tools["create_spreadsheet"](title="Test", ctx=ctx)


class TestListDrives:
    def _drive_service(self):
        return MagicMock()

    def _page(self, n, next_token=None):
        drives = [
            {"id": f"d{i}", "name": f"Drive {i}", "createdTime": "2026-01-01T00:00:00Z"}
            for i in range(n)
        ]
        result = {"drives": drives}
        if next_token:
            result["nextPageToken"] = next_token
        return result

    async def test_follows_next_page_token_across_pages(self):
        svc = self._drive_service()
        svc.drives.return_value.list.return_value.execute.side_effect = [
            self._page(100, next_token="page2"),
            self._page(60),
        ]
        ctx = _make_ctx(drive_service=svc)

        result = await _drive_tools["list_drives"](max_results=150, ctx=ctx)

        assert svc.drives.return_value.list.call_count == 2
        first_kwargs, second_kwargs = (
            c.kwargs for c in svc.drives.return_value.list.call_args_list
        )
        # googleapiclient drops None-valued params, so None means "first page".
        assert first_kwargs.get("pageToken") is None
        assert second_kwargs["pageToken"] == "page2"
        assert len(result) == 150

    async def test_stops_without_extra_call_when_no_next_page_token(self):
        svc = self._drive_service()
        svc.drives.return_value.list.return_value.execute.side_effect = [
            self._page(5),
        ]
        ctx = _make_ctx(drive_service=svc)

        result = await _drive_tools["list_drives"](max_results=100, ctx=ctx)

        assert svc.drives.return_value.list.call_count == 1
        assert len(result) == 5

    async def test_stops_once_max_results_reached_even_with_a_next_page_token(self):
        """No extra call once max_results drives are in hand, token or not."""
        svc = self._drive_service()
        svc.drives.return_value.list.return_value.execute.side_effect = [
            self._page(100, next_token="page2"),
        ]
        ctx = _make_ctx(drive_service=svc)

        result = await _drive_tools["list_drives"](max_results=100, ctx=ctx)

        assert svc.drives.return_value.list.call_count == 1
        assert len(result) == 100

    async def test_never_ending_page_token_is_bounded(self, monkeypatch):
        """#615: empty pages that always carry a nextPageToken must not loop forever."""
        from mcp_gee_sweet.tools.drive import files as files_module
        from mcp_gee_sweet.tools.pagination import PageLimitExceeded

        monkeypatch.setattr(files_module, "_LIST_DRIVES_MAX_PAGES", 3)
        svc = self._drive_service()
        svc.drives.return_value.list.return_value.execute.return_value = self._page(
            0, next_token="again"
        )
        ctx = _make_ctx(drive_service=svc)

        with pytest.raises(PageLimitExceeded):
            await _drive_tools["list_drives"](max_results=100, ctx=ctx)
        assert svc.drives.return_value.list.call_count == 3


class TestListSharedWithMe:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _list_call_kwargs(self, svc):
        return svc.files.return_value.list.call_args.kwargs

    async def test_query_includes_shared_with_me(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](ctx=ctx)
        kw = self._list_call_kwargs(svc)
        assert "sharedWithMe=true" in kw["q"]
        assert "trashed=false" in kw["q"]

    async def test_mime_type_filter_added_to_query(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](
            mime_type="application/vnd.google-apps.spreadsheet", ctx=ctx
        )
        kw = self._list_call_kwargs(svc)
        assert "application/vnd.google-apps.spreadsheet" in kw["q"]

    async def test_mime_type_single_quote_is_escaped(self):
        """Regression test for #494: a bare quote-doubling escape (SQL-style, not
        Drive's backslash convention) produced a malformed query, live-confirmed
        as an uncaught HttpError 400 'Invalid Value' from the real Drive API."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](mime_type="it's a test", ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    async def test_api_error_returns_error_dict_not_raised(self):
        svc = self._drive_service()
        svc.files.return_value.list.return_value.execute.side_effect = RuntimeError(
            "simulated API failure"
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["list_shared_with_me"](ctx=ctx)
        _assert_error_list(result, "simulated API failure")

    async def test_max_results_capped_at_200(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_shared_with_me"](max_results=999, ctx=ctx)
        assert self._list_call_kwargs(svc)["pageSize"] == 200

    async def test_result_shape(self):
        svc = self._drive_service(
            files=[
                {
                    "id": "fid1",
                    "name": "Shared Doc",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "owners": [{"emailAddress": "owner@example.com"}],
                    "webViewLink": "https://docs.google.com/fid1",
                }
            ]
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["list_shared_with_me"](ctx=ctx)
        assert len(result) == 1
        assert result[0]["id"] == "fid1"
        assert result[0]["owners"] == ["owner@example.com"]


class TestListRecentFiles:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _list_call_kwargs(self, svc):
        return svc.files.return_value.list.call_args.kwargs

    async def test_orders_by_modified_time_desc(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](ctx=ctx)
        assert self._list_call_kwargs(svc)["orderBy"] == "modifiedTime desc"

    async def test_days_filter_adds_modified_time_constraint(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](days=7, ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "modifiedTime >" in q

    async def test_no_days_filter_omits_time_constraint(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "modifiedTime >" not in q

    async def test_max_results_capped_at_100(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](max_results=500, ctx=ctx)
        assert self._list_call_kwargs(svc)["pageSize"] == 100

    async def test_mime_type_filter_applied(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](mime_type="application/pdf", ctx=ctx)
        assert "application/pdf" in self._list_call_kwargs(svc)["q"]

    async def test_mime_type_single_quote_is_escaped(self):
        """Sibling of TestListSharedWithMe's #494 regression test — list_recent_files
        had the identical quote-doubling bug at the same code review pass."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["list_recent_files"](mime_type="it's a test", ctx=ctx)
        q = self._list_call_kwargs(svc)["q"]
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    async def test_api_error_returns_error_dict_not_raised(self):
        svc = self._drive_service()
        svc.files.return_value.list.return_value.execute.side_effect = RuntimeError(
            "simulated API failure"
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["list_recent_files"](ctx=ctx)
        _assert_error_list(result, "simulated API failure")


class TestListFiles:
    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _ctx(self, svc):
        folder_cache = MagicMock()
        folder_cache.get.return_value = None
        return _make_ctx(drive_service=svc, drive_folder_cache=folder_cache)

    async def test_requests_md5checksum_field(self):
        svc = self._drive_service()
        ctx = self._ctx(svc)
        await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        fields_arg = svc.files.return_value.list.call_args.kwargs["fields"]
        assert "md5Checksum" in fields_arg

    async def test_folder_id_quote_cannot_break_out_of_string(self):
        """#1054 round 1: an unescaped `'` could OR in `trashed=true`."""
        svc = self._drive_service()
        ctx = self._ctx(svc)
        await _drive_tools["list_files"](folder_id="x' in parents or trashed=true or 'y", ctx=ctx)
        assert svc.files.return_value.list.call_args.kwargs["q"] == (
            "'x\\' in parents or trashed=true or \\'y' in parents and trashed=false"
        )

    async def test_result_includes_md5_checksum_for_binary_file(self):
        svc = self._drive_service(
            files=[
                {
                    "id": "fid1",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "webViewLink": "https://drive.google.com/fid1",
                    "md5Checksum": "d41d8cd98f00b204e9800998ecf8427e",
                }
            ]
        )
        ctx = self._ctx(svc)
        result = await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        assert result[0]["md5_checksum"] == "d41d8cd98f00b204e9800998ecf8427e"

    async def test_result_md5_checksum_none_for_workspace_file(self):
        # Drive omits md5Checksum entirely for Google Workspace files (Docs,
        # Sheets, Slides) since they have no fixed byte content.
        svc = self._drive_service(
            files=[
                {
                    "id": "fid2",
                    "name": "Notes",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "webViewLink": "https://docs.google.com/fid2",
                }
            ]
        )
        ctx = self._ctx(svc)
        result = await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        assert result[0]["md5_checksum"] is None

    async def test_requests_starred_field(self):
        """#388: get_file_metadata/list_files/search_files now surface starred."""
        svc = self._drive_service()
        ctx = self._ctx(svc)
        await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        fields_arg = svc.files.return_value.list.call_args.kwargs["fields"]
        assert "starred" in fields_arg

    async def test_result_includes_starred_field(self):
        svc = self._drive_service(
            files=[
                {
                    "id": "fid1",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "webViewLink": "https://drive.google.com/fid1",
                    "starred": True,
                }
            ]
        )
        ctx = self._ctx(svc)
        result = await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        assert result[0]["starred"] is True

    async def test_result_starred_defaults_false_when_absent(self):
        svc = self._drive_service(
            files=[
                {
                    "id": "fid2",
                    "name": "Notes",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "webViewLink": "https://docs.google.com/fid2",
                }
            ]
        )
        ctx = self._ctx(svc)
        result = await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        assert result[0]["starred"] is False

    async def test_mime_type_single_quote_is_escaped(self):
        """Regression test — mime_type was interpolated with zero escaping (not
        even the broken quote-doubling list_shared_with_me/list_recent_files had),
        live-confirmed as an uncaught HttpError 400 'Invalid Value' (PR #577 QA)."""
        svc = self._drive_service()
        ctx = self._ctx(svc)
        await _drive_tools["list_files"](folder_id="folder1", mime_type="it's a test", ctx=ctx)
        q = svc.files.return_value.list.call_args.kwargs["q"]
        assert "\\'" in q  # literal backslash-apostrophe present in query string

    async def test_api_error_returns_error_dict_not_raised(self):
        svc = self._drive_service()
        svc.files.return_value.list.return_value.execute.side_effect = RuntimeError(
            "simulated API failure"
        )
        ctx = self._ctx(svc)
        result = await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        _assert_error_list(result, "simulated API failure")

    async def test_requests_next_page_token(self):
        """#698: nextPageToken's absence is what marks a listing exhaustive."""
        svc = self._drive_service()
        ctx = self._ctx(svc)
        await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        fields_arg = svc.files.return_value.list.call_args.kwargs["fields"]
        assert "nextPageToken" in fields_arg
        assert "incompleteSearch" in fields_arg

    @pytest.mark.parametrize(
        ("response_extra", "expected_exhaustive"),
        [
            ({}, True),
            ({"nextPageToken": "tok"}, False),
            # PR #788 QA round 1: Drive flags a possibly-partial result this way.
            ({"incompleteSearch": True}, False),
        ],
    )
    async def test_store_exhaustive_flag_follows_next_page_token(
        self, response_extra, expected_exhaustive
    ):
        svc = self._drive_service()
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [],
            **response_extra,
        }
        ctx = self._ctx(svc)
        await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        folder_cache = ctx.request_context.lifespan_context.drive_folder_cache
        assert folder_cache.store.call_args.kwargs["exhaustive"] is expected_exhaustive

    async def test_mark_dirty_during_fetch_is_not_overwritten(self, tmp_path):
        """#698 finding 1, end to end with a real cache: a mutation that marks the
        folder dirty while list_files is awaiting Drive must survive the in-flight
        call's store() — the next list_files refetches instead of serving the
        pre-mutation listing."""
        folder_cache = DriveFolderCache(db_path=str(tmp_path / "c.db"), ttl=60, principal="test")
        svc = MagicMock()

        def execute_with_concurrent_mutation(*args, **kwargs):
            folder_cache.mark_dirty("folder1")  # e.g. upload_file into folder1
            return {"files": [{"id": "old", "name": "old.txt", "mimeType": "text/plain"}]}

        svc.files.return_value.list.return_value.execute.side_effect = (
            execute_with_concurrent_mutation
        )
        ctx = _make_ctx(drive_service=svc, drive_folder_cache=folder_cache)
        await _drive_tools["list_files"](folder_id="folder1", ctx=ctx)
        assert folder_cache.get("folder1", None, 100) is None


class TestListFolders:
    """#689: list_folders with no parent must fall back to DRIVE_FOLDER_ID
    (lc.folder_id), mirroring list_spreadsheets — not hardcode 'root' in parents."""

    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _captured_q(self, svc):
        return svc.files.return_value.list.call_args.kwargs["q"]

    async def test_no_parent_falls_back_to_configured_default(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id="default_folder")
        await _drive_tools["list_folders"](ctx=ctx)
        q = self._captured_q(svc)
        assert "'default_folder' in parents" in q
        assert "'root' in parents" not in q

    async def test_explicit_parent_overrides_configured_default(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id="default_folder")
        await _drive_tools["list_folders"](parent_folder_id="explicit_par", ctx=ctx)
        q = self._captured_q(svc)
        assert "'explicit_par' in parents" in q
        assert "default_folder" not in q

    async def test_no_parent_no_default_lists_across_my_drive(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_folders"](ctx=ctx)
        q = self._captured_q(svc)
        assert "in parents" not in q
        assert "'root'" not in q

    async def test_parent_folder_id_quote_cannot_break_out_of_string(self):
        """#1054 round 1: an unescaped `'` could OR in `trashed=true`."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_folders"](
            parent_folder_id="x' in parents or trashed=true or 'y", ctx=ctx
        )
        assert self._captured_q(svc) == (
            "mimeType='application/vnd.google-apps.folder' and trashed=false"
            " and 'x\\' in parents or trashed=true or \\'y' in parents"
        )

    async def test_result_shape_unchanged(self):
        svc = self._drive_service(
            files=[{"id": "f1", "name": "Sub", "parents": ["default_folder"]}]
        )
        ctx = _make_ctx(drive_service=svc, folder_id="default_folder")
        result = await _drive_tools["list_folders"](ctx=ctx)
        assert result == [{"id": "f1", "name": "Sub", "parent": "default_folder"}]

    def _captured_page_size(self, svc):
        return svc.files.return_value.list.call_args.kwargs["pageSize"]

    async def test_default_max_results_used_as_page_size(self):
        # #718: the no-parent + no-DRIVE_FOLDER_ID fallback previously issued a
        # single unpaginated call with no pageSize at all, silently truncated
        # at the API's own default (~100) with no caller control.
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_folders"](ctx=ctx)
        assert self._captured_page_size(svc) == 100

    async def test_max_results_passed_through_as_page_size(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_folders"](max_results=25, ctx=ctx)
        assert self._captured_page_size(svc) == 25

    async def test_max_results_clamped_to_1000(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_folders"](max_results=5000, ctx=ctx)
        assert self._captured_page_size(svc) == 1000

    async def test_max_results_clamped_to_at_least_1(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_folders"](max_results=0, ctx=ctx)
        assert self._captured_page_size(svc) == 1


class TestListSpreadsheets:
    """#718: list_spreadsheets had no max_results/pageSize at all — the
    no-parent + no-DRIVE_FOLDER_ID fallback was a single unpaginated call
    silently truncated at the API's own default with no caller control."""

    def _drive_service(self, files=None):
        mock = MagicMock()
        mock.files.return_value.list.return_value.execute.return_value = {"files": files or []}
        return mock

    def _captured_q(self, svc):
        return svc.files.return_value.list.call_args.kwargs["q"]

    def _captured_page_size(self, svc):
        return svc.files.return_value.list.call_args.kwargs["pageSize"]

    async def test_no_folder_no_default_lists_across_all_drives(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_spreadsheets"](ctx=ctx)
        q = self._captured_q(svc)
        assert "in parents" not in q
        assert svc.files.return_value.list.call_args.kwargs["includeItemsFromAllDrives"] is True

    async def test_result_shape_unchanged(self):
        svc = self._drive_service(files=[{"id": "s1", "name": "Budget"}])
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        result = await _drive_tools["list_spreadsheets"](ctx=ctx)
        assert result == [{"id": "s1", "title": "Budget"}]

    async def test_default_max_results_used_as_page_size(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_spreadsheets"](ctx=ctx)
        assert self._captured_page_size(svc) == 100

    async def test_max_results_passed_through_as_page_size(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_spreadsheets"](max_results=25, ctx=ctx)
        assert self._captured_page_size(svc) == 25

    async def test_max_results_clamped_to_1000(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_spreadsheets"](max_results=5000, ctx=ctx)
        assert self._captured_page_size(svc) == 1000

    async def test_max_results_clamped_to_at_least_1(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_spreadsheets"](max_results=0, ctx=ctx)
        assert self._captured_page_size(svc) == 1

    @pytest.mark.parametrize("folder_id", [None, "folder1"])
    async def test_query_excludes_trashed(self, folder_id):
        """#1054: trashed spreadsheets came back from list_spreadsheets."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=folder_id)
        await _drive_tools["list_spreadsheets"](ctx=ctx)
        expected = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        if folder_id:
            expected += f" and '{folder_id}' in parents"
        assert self._captured_q(svc) == expected

    async def test_folder_id_quote_cannot_break_out_of_string(self):
        """#1054 round 1: an unescaped `'` in folder_id could OR in `trashed=true`."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc, folder_id=None)
        await _drive_tools["list_spreadsheets"](
            folder_id="x' in parents or trashed=true or 'y", ctx=ctx
        )
        assert self._captured_q(svc) == (
            "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
            " and 'x\\' in parents or trashed=true or \\'y' in parents"
        )


class TestCorporaSelection:
    """#1127: with Drive's default "user" corpus, a service account's unscoped
    listing or search missed Shared Drive items it hadn't touched. An unscoped
    call must ask for corpora='allDrives'; a folder-scoped one keeps the default."""

    async def _call(self, tool_name, *, default_folder=None, **kwargs):
        svc = MagicMock()
        svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        ctx = _make_ctx(drive_service=svc, folder_id=default_folder)
        await _drive_tools[tool_name](ctx=ctx, **kwargs)
        return svc.files.return_value.list.call_args.kwargs

    @pytest.mark.parametrize(
        ("tool_name", "kwargs"),
        [
            ("list_spreadsheets", {}),
            ("list_folders", {}),
            ("search_files", {"query": "QA"}),
            ("search_files", {"query": "QA", "mime_type": "application/pdf"}),
            ("search_files", {}),
            ("search_files", {"modified_within_days": 3}),
            ("search_spreadsheets", {"query": "QA"}),
            ("list_recent_files", {}),
        ],
    )
    async def test_unscoped_call_searches_all_drives(self, tool_name, kwargs):
        list_kwargs = await self._call(tool_name, **kwargs)
        assert list_kwargs["corpora"] == "allDrives"
        assert list_kwargs["includeItemsFromAllDrives"] is True
        assert list_kwargs["supportsAllDrives"] is True

    @pytest.mark.parametrize(
        ("tool_name", "kwargs"),
        [
            ("list_spreadsheets", {"folder_id": "folder1"}),
            ("list_folders", {"parent_folder_id": "folder1"}),
            ("search_files", {"query": "QA", "folder_id": "folder1"}),
        ],
    )
    async def test_folder_scoped_call_keeps_default_corpus(self, tool_name, kwargs):
        assert "corpora" not in await self._call(tool_name, **kwargs)

    @pytest.mark.parametrize("tool_name", ["list_spreadsheets", "list_folders"])
    async def test_configured_default_folder_keeps_default_corpus(self, tool_name):
        # DRIVE_FOLDER_ID scopes the query just as an explicit folder does.
        assert "corpora" not in await self._call(tool_name, default_folder="default_folder")

    async def test_shared_with_me_keeps_default_corpus(self):
        # sharedWithMe=true is itself the scope; allDrives would add nothing.
        assert "corpora" not in await self._call("list_shared_with_me")

    async def test_shared_with_me_includes_shared_drive_items(self):
        """PR #1200 QA round 1: without these flags Drive leaves out a Shared
        Drive file shared directly with a caller who isn't a member of it."""
        list_kwargs = await self._call("list_shared_with_me")
        assert list_kwargs["includeItemsFromAllDrives"] is True
        assert list_kwargs["supportsAllDrives"] is True


class TestGetFileMetadata:
    def _drive_service(self, file=None):
        mock = MagicMock()
        mock.files.return_value.get.return_value.execute.return_value = file or {
            "id": "fid1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "md5Checksum": "d41d8cd98f00b204e9800998ecf8427e",
        }
        return mock

    async def test_requests_md5checksum_field(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["get_file_metadata"](file_id="fid1", ctx=ctx)
        fields_arg = svc.files.return_value.get.call_args.kwargs["fields"]
        assert "md5Checksum" in fields_arg

    async def test_result_includes_md5_checksum_for_binary_file(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_file_metadata"](file_id="fid1", ctx=ctx)
        assert result["md5_checksum"] == "d41d8cd98f00b204e9800998ecf8427e"

    async def test_result_md5_checksum_none_for_workspace_file(self):
        svc = self._drive_service(
            file={
                "id": "fid2",
                "name": "Notes",
                "mimeType": "application/vnd.google-apps.document",
            }
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_file_metadata"](file_id="fid2", ctx=ctx)
        assert result["md5_checksum"] is None

    async def test_requests_starred_field(self):
        """#388: previously there was no way to read a file's starred state
        independently of star_file/unstar_file's own mutation response."""
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["get_file_metadata"](file_id="fid1", ctx=ctx)
        fields_arg = svc.files.return_value.get.call_args.kwargs["fields"]
        assert "starred" in fields_arg

    async def test_result_includes_starred_true(self):
        svc = self._drive_service(
            file={
                "id": "fid1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "starred": True,
            }
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_file_metadata"](file_id="fid1", ctx=ctx)
        assert result["starred"] is True

    async def test_result_starred_defaults_false_when_absent(self):
        svc = self._drive_service(
            file={
                "id": "fid1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
            }
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_file_metadata"](file_id="fid1", ctx=ctx)
        assert result["starred"] is False


class TestGetStorageQuota:
    def _drive_service(self, quota=None, user=None):
        mock = MagicMock()
        mock.about.return_value.get.return_value.execute.return_value = {
            "storageQuota": quota
            or {
                "limit": "16106127360",
                "usage": "1073741824",
                "usageInDrive": "1000000000",
                "usageInDriveTrash": "73741824",
            },
            "user": user
            or {
                "emailAddress": "test@example.com",
                "displayName": "Test User",
            },
        }
        return mock

    async def test_returns_byte_values_as_integers(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert isinstance(result["limit_bytes"], int)
        assert isinstance(result["usage_bytes"], int)
        assert result["limit_bytes"] == 16106127360

    async def test_no_limit_key_returns_none(self):
        svc = self._drive_service(
            quota={"usage": "0", "usageInDrive": "0", "usageInDriveTrash": "0"}
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["limit_bytes"] is None

    async def test_limit_zero_string_returns_zero(self):
        # SA accounts: Drive API returns "0" (not absent), which casts to int 0
        svc = self._drive_service(
            quota={"limit": "0", "usage": "0", "usageInDrive": "0", "usageInDriveTrash": "0"}
        )
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["limit_bytes"] == 0

    async def test_includes_user_info(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        result = await _drive_tools["get_storage_quota"](ctx=ctx)
        assert result["email"] == "test@example.com"
        assert result["display_name"] == "Test User"

    async def test_requests_correct_fields(self):
        svc = self._drive_service()
        ctx = _make_ctx(drive_service=svc)
        await _drive_tools["get_storage_quota"](ctx=ctx)
        fields_arg = svc.about.return_value.get.call_args.kwargs["fields"]
        assert "storageQuota" in fields_arg
        assert "user" in fields_arg


class TestImportCsvToSheet:
    """import_csv_to_sheet: create a spreadsheet from a local CSV file."""

    def _drive_service(self):
        mock = MagicMock()
        mock.files.return_value.create.return_value.execute.return_value = {
            "id": "sheet123",
            "name": "Imported",
            "parents": ["folder1"],
            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123",
        }
        return mock

    def _sheets_service(self, sheet_title="Sheet1", row_count=1000, column_count=26):
        mock = MagicMock()
        mock.spreadsheets.return_value.get.return_value.execute.return_value = {
            "sheets": [
                {
                    "properties": {
                        "sheetId": 0,
                        "title": sheet_title,
                        "gridProperties": {
                            "rowCount": row_count,
                            "columnCount": column_count,
                        },
                    }
                }
            ]
        }
        mock.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        mock.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}
        return mock

    def _write_csv(self, tmp_path, rows, name="data.csv"):
        path = tmp_path / name
        path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        return path

    async def test_file_not_found_returns_error(self):
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](
            local_path="/no/such/file.csv", title="X", ctx=ctx
        )
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_unsupported_extension_returns_error(self, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" in result
        assert ".csv" in result["error"]

    async def test_empty_csv_returns_error(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" in result
        assert "empty" in result["error"].lower()

    async def test_creates_spreadsheet_and_writes_rows(self, tmp_path):
        path = self._write_csv(tmp_path, [["name", "age"], ["Alice", "30"], ["Bob", "25"]])
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        folder_cache = MagicMock()
        sheet_data_cache = MagicMock()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=folder_cache,
            sheet_data_cache=sheet_data_cache,
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="Imported", folder_id="folder1", ctx=ctx
        )

        assert result["spreadsheetId"] == "sheet123"
        assert result["title"] == "Imported"
        assert result["web_link"] == "https://docs.google.com/spreadsheets/d/sheet123"
        assert result["rows_written"] == 3

        update_call = sheets_svc.spreadsheets.return_value.values.return_value.update
        assert update_call.call_count == 1
        kwargs = update_call.call_args.kwargs
        assert kwargs["spreadsheetId"] == "sheet123"
        assert kwargs["range"] == "Sheet1!A1"
        assert kwargs["valueInputOption"] == "USER_ENTERED"
        assert kwargs["body"]["values"] == [
            ["name", "age"],
            ["Alice", "30"],
            ["Bob", "25"],
        ]
        folder_cache.mark_dirty.assert_called_once_with("folder1")
        sheet_data_cache.mark_dirty.assert_called_once_with("sheet123")
        # No rename (the default title matches); the grid shrinks to the data's 3x2.
        assert self._grid_requests(sheets_svc) == [{"columnCount": 2}, {"rowCount": 3}]

    async def _import_values(self, path):
        """Import `path` and return the values the one update wrote."""
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=self._drive_service(),
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="Imported", ctx=ctx
        )
        assert "error" not in result, result
        update_call = sheets_svc.spreadsheets.return_value.values.return_value.update
        return update_call.call_args.kwargs["body"]["values"]

    async def test_drops_a_leading_utf8_bom(self, tmp_path):
        """#1575: Excel's "CSV UTF-8" export starts with a BOM, which must not reach A1."""
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbfcase,value\nx,1\n")
        values = await self._import_values(path)
        assert values == [["case", "value"], ["x", "1"]]

    async def test_bom_before_a_quoted_first_field_still_parses_the_quotes(self, tmp_path):
        """With the BOM read as text, csv saw `\\ufeff"a,b"` and kept the quotes as data."""
        path = tmp_path / "bom_quoted.csv"
        path.write_bytes(b'\xef\xbb\xbf"a,b",c\n1,2\n')
        values = await self._import_values(path)
        assert values == [["a,b", "c"], ["1", "2"]]

    async def test_keeps_a_bom_character_that_is_not_leading(self, tmp_path):
        """Only the encoding signature is dropped; a U+FEFF later in the file is data."""
        path = tmp_path / "inner_bom.csv"
        path.write_bytes(b"h1,h2\nx,\xef\xbb\xbfy\n")
        values = await self._import_values(path)
        assert values == [["h1", "h2"], ["x", "\ufeffy"]]

    async def test_file_without_bom_reads_unchanged(self, tmp_path):
        path = tmp_path / "plain.csv"
        path.write_bytes("café,v\n1,2\n".encode())
        values = await self._import_values(path)
        assert values == [["café", "v"], ["1", "2"]]

    async def test_bom_only_file_is_empty(self, tmp_path):
        path = tmp_path / "bom_only.csv"
        path.write_bytes(b"\xef\xbb\xbf")
        ctx = _make_ctx()
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" in result
        assert "empty" in result["error"].lower()

    async def _import_error(self, path):
        """Import `path`, expecting an error result before any Drive call."""
        drive_svc = self._drive_service()
        ctx = _make_ctx(drive_service=drive_svc, sheets_service=self._sheets_service())
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert set(result) == {"error"}, result
        drive_svc.files.return_value.create.assert_not_called()
        return result["error"]

    async def test_non_utf8_file_returns_error_naming_utf8(self, tmp_path):
        """PR #1580 QA round 1: a cp1252 file raised UnicodeDecodeError out of the tool."""
        path = tmp_path / "cp1252.csv"
        path.write_bytes(b"caf\xe9,1\n")
        error = await self._import_error(path)
        assert "not valid UTF-8" in error
        assert "CSV UTF-8" in error

    async def test_directory_named_csv_returns_error(self, tmp_path):
        """PR #1580 QA round 1: a directory passed exists() and raised IsADirectoryError."""
        path = tmp_path / "folder.csv"
        path.mkdir()
        error = await self._import_error(path)
        assert error.startswith("Not a regular file")

    async def test_csv_parse_error_returns_error(self, tmp_path):
        """A field over csv's size limit raises csv.Error, which must not escape."""
        path = tmp_path / "big_field.csv"
        path.write_text("a," + "x" * 50 + "\n", encoding="utf-8")
        old_limit = csv.field_size_limit(10)
        try:
            error = await self._import_error(path)
        finally:
            csv.field_size_limit(old_limit)
        assert error.startswith("Could not parse CSV")

    async def test_read_oserror_returns_error(self, tmp_path, monkeypatch):
        path = tmp_path / "data.csv"
        path.write_text("a,b\n", encoding="utf-8")

        def _refuse(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "open", _refuse)
        error = await self._import_error(path)
        assert error == f"Could not read file {path}: Permission denied"

    async def test_pads_ragged_rows_to_common_width(self, tmp_path):
        path = tmp_path / "ragged.csv"
        path.write_text("a,b,c\n1,2\n", encoding="utf-8")
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        kwargs = sheets_svc.spreadsheets.return_value.values.return_value.update.call_args.kwargs
        assert kwargs["body"]["values"] == [["a", "b", "c"], ["1", "2", ""]]

    async def test_renames_default_sheet_when_sheet_name_differs(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service(sheet_title="Sheet1")
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="X", sheet_name="Imported Data", ctx=ctx
        )
        requests = sheets_svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"][
            "requests"
        ]
        assert requests[0]["updateSheetProperties"]["properties"]["title"] == "Imported Data"
        assert requests[0]["updateSheetProperties"]["properties"]["sheetId"] == 0
        assert requests[0]["updateSheetProperties"]["fields"] == "title"
        update_range = (
            sheets_svc.spreadsheets.return_value.values.return_value.update.call_args.kwargs[
                "range"
            ]
        )
        assert update_range == "'Imported Data'!A1"

    @staticmethod
    def _grid_requests(sheets_svc):
        """The gridProperties of each resize request sent, in order."""
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        if not batch.called:
            return []
        return [
            r["updateSheetProperties"]["properties"]["gridProperties"]
            for r in batch.call_args.kwargs["body"]["requests"]
            if "gridProperties" in r["updateSheetProperties"]["properties"]
        ]

    @staticmethod
    def _request_fields(sheets_svc):
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        assert batch.call_count == 1
        return [
            r["updateSheetProperties"]["fields"] for r in batch.call_args.kwargs["body"]["requests"]
        ]

    async def _import_grid(self, path, row_count=1000, column_count=26, cache=None):
        """Import `path` into a sheet whose grid starts at row_count x column_count."""
        sheets_svc = self._sheets_service(row_count=row_count, column_count=column_count)
        ctx = _make_ctx(
            drive_service=self._drive_service(),
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=cache or MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" not in result, result
        return sheets_svc

    async def test_resizes_grid_when_data_exceeds_it(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"], ["2"], ["3"]])
        cache = MagicMock()
        sheets_svc = await self._import_grid(path, row_count=1, column_count=1, cache=cache)
        assert self._grid_requests(sheets_svc) == [{"rowCount": 4}]
        assert self._request_fields(sheets_svc) == ["gridProperties.rowCount"]
        cache.mark_dirty.assert_called_once_with("sheet123")

    async def test_no_resize_when_grid_already_matches_data(self, tmp_path):
        path = self._write_csv(tmp_path, [["a", "b"], ["1", "2"]])
        cache = MagicMock()
        sheets_svc = await self._import_grid(path, row_count=2, column_count=2, cache=cache)
        sheets_svc.spreadsheets.return_value.batchUpdate.assert_not_called()
        cache.mark_dirty.assert_not_called()

    async def test_narrow_file_gets_its_own_width_not_26_columns(self, tmp_path):
        """#1573: padding to 26 columns counted 26 cells a row against the cell limit."""
        path = self._write_csv(tmp_path, [["a"]] + [[str(i)] for i in range(1500)])
        sheets_svc = await self._import_grid(path)
        assert self._grid_requests(sheets_svc) == [{"columnCount": 1}, {"rowCount": 1501}]

    async def test_short_file_gets_its_own_row_count_not_1000(self, tmp_path):
        path = self._write_csv(tmp_path, [["a", "b"], ["1", "2"]])
        sheets_svc = await self._import_grid(path)
        assert self._grid_requests(sheets_svc) == [{"columnCount": 2}, {"rowCount": 2}]

    async def test_wide_file_grows_columns_only(self, tmp_path):
        path = self._write_csv(tmp_path, [[f"c{i}" for i in range(40)]] * 1000)
        sheets_svc = await self._import_grid(path)
        assert self._grid_requests(sheets_svc) == [{"columnCount": 40}]

    async def test_columns_resize_before_rows_as_separate_requests(self, tmp_path):
        """Sheets checks a row change against the current column count, even when the
        same request sets both, so the column change must land first (checked live)."""
        path = self._write_csv(tmp_path, [["a", "b", "c"]] * 1200)
        sheets_svc = await self._import_grid(path)
        assert self._request_fields(sheets_svc) == [
            "gridProperties.columnCount",
            "gridProperties.rowCount",
        ]
        requests = sheets_svc.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"][
            "requests"
        ]
        assert all(r["updateSheetProperties"]["properties"]["sheetId"] == 0 for r in requests)

    async def test_rename_and_resize_share_one_batch(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=self._drive_service(),
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="X", sheet_name="Data", ctx=ctx
        )
        assert self._request_fields(sheets_svc) == [
            "title",
            "gridProperties.columnCount",
            "gridProperties.rowCount",
        ]

    async def test_blank_lines_only_file_gets_one_column(self, tmp_path):
        """csv yields [] for a blank line; a grid needs at least one column."""
        path = tmp_path / "blank.csv"
        path.write_text("\n\n\n", encoding="utf-8")
        sheets_svc = await self._import_grid(path)
        assert self._grid_requests(sheets_svc) == [{"columnCount": 1}, {"rowCount": 3}]

    def test_grid_limit_error_allows_exactly_the_limits(self):
        """Both limits are inclusive (checked live: 2,000,000 x 10 and 18,278 columns
        were accepted, one more of either refused)."""
        limit_error = drive_files_module._csv_grid_limit_error
        assert limit_error("f.csv", 2_000_000, 10) is None
        assert limit_error("f.csv", 1, 18_278) is None
        assert limit_error("f.csv", 769_231, 26) is not None
        assert limit_error("f.csv", 2_000_001, 10) is not None
        assert limit_error("f.csv", 1, 18_279) is not None

    async def test_csv_over_cell_limit_errors_before_create(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_SHEETS_CELL_LIMIT", 5)
        path = self._write_csv(tmp_path, [["a", "b"], ["1", "2"], ["3", "4"]])
        error = await self._import_error(path)
        assert "3 rows x 2 columns = 6 cells" in error
        assert "at most 5" in error
        assert "Nothing was created" in error

    async def test_csv_at_cell_limit_imports(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_SHEETS_CELL_LIMIT", 6)
        path = self._write_csv(tmp_path, [["a", "b"], ["1", "2"], ["3", "4"]])
        sheets_svc = await self._import_grid(path)
        assert self._grid_requests(sheets_svc) == [{"columnCount": 2}, {"rowCount": 3}]

    async def test_csv_over_column_limit_errors_before_create(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_SHEETS_COLUMN_LIMIT", 2)
        path = self._write_csv(tmp_path, [["a", "b", "c"]])
        error = await self._import_error(path)
        assert "3 columns" in error
        assert "at most 2" in error

    @staticmethod
    def _rate_limit_error():
        resp = MagicMock()
        resp.status = 429
        return HttpError(resp=resp, content=b'{"error": {"status": "RESOURCE_EXHAUSTED"}}')

    async def _import_with_update_effects(self, tmp_path, monkeypatch, effects, rows=None):
        """Import a CSV whose values().update().execute calls return/raise `effects`
        in order. Pauses are 0 s long. Returns (result, the update mock)."""
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_BASE_DELAY", 0.0)
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_MAX_DELAY", 0.0)
        path = self._write_csv(tmp_path, rows or [["a"], ["1"]])
        sheets_svc = self._sheets_service()
        update = sheets_svc.spreadsheets.return_value.values.return_value.update
        update.return_value.execute.side_effect = effects
        ctx = _make_ctx(
            drive_service=self._drive_service(),
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        return result, update

    async def test_rate_limited_chunk_is_retried(self, tmp_path, monkeypatch):
        """#1573: Sheets' 60 writes/min quota refused 93 of an 800k-row import's 160
        chunks, which were reported failed instead of sent again."""
        result, update = await self._import_with_update_effects(
            tmp_path, monkeypatch, [self._rate_limit_error(), self._rate_limit_error(), {}]
        )
        assert "error" not in result, result
        assert result["rows_written"] == 2
        assert update.return_value.execute.call_count == 3

    async def test_other_errors_are_not_retried(self, tmp_path, monkeypatch):
        """A 5xx may have landed and a 4xx other than 429 won't change: neither is resent."""
        for status in (400, 403, 500):
            resp = MagicMock()
            resp.status = status
            error = HttpError(resp=resp, content=b"{}")
            result, update = await self._import_with_update_effects(
                tmp_path, monkeypatch, [error, {}]
            )
            assert update.return_value.execute.call_count == 1, status
            if status == 500:
                assert result["failed_ranges"][0]["start_row"] == 1, status
            else:
                # The only chunk was refused, so the spreadsheet was removed (#1574).
                assert "No rows were written" in result["error"], status

    async def test_rate_limited_chunk_fails_once_max_wait_is_spent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_MAX_WAIT", 0.0)
        refusal = self._rate_limit_error()
        result, update = await self._import_with_update_effects(
            tmp_path, monkeypatch, [refusal, {}]
        )
        assert update.return_value.execute.call_count == 1
        # A final 429 wrote nothing, so the only chunk's refusal removes the spreadsheet.
        assert result == {
            "error": f"The row write was refused ({refusal}). No rows were written, "
            "and the new spreadsheet was deleted."
        }

    async def test_rate_limited_chunks_retry_alongside_ones_that_landed(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 1)
        rows = [["h"], ["1"], ["2"], ["3"]]
        effects = [{}, self._rate_limit_error(), {}, self._rate_limit_error(), {}, {}]
        result, update = await self._import_with_update_effects(
            tmp_path, monkeypatch, effects, rows=rows
        )
        assert "error" not in result, result
        assert result["rows_written"] == 4
        assert update.return_value.execute.call_count == 6
        ranges = {c.kwargs["range"] for c in update.call_args_list}
        assert ranges == {"Sheet1!A1", "Sheet1!A2", "Sheet1!A3", "Sheet1!A4"}

    def _quota_ctx(self, monkeypatch, delay):
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_BASE_DELAY", delay)
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_MAX_DELAY", delay)
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=self._drive_service(),
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        ctx.report_progress = AsyncMock()
        return ctx, sheets_svc

    async def test_rate_limited_resize_is_resent(self, tmp_path, monkeypatch):
        """PR #1589 QA round 1: the resize now goes out on almost every import and
        counts against the same quota; a 429 there raised out of the tool after the
        spreadsheet was created."""
        ctx, sheets_svc = self._quota_ctx(monkeypatch, 0.0)
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        batch.return_value.execute.side_effect = [self._rate_limit_error(), {}]
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" not in result, result
        assert result["rows_written"] == 2
        assert batch.return_value.execute.call_count == 2

    async def test_a_pause_reports_progress_when_it_starts(self, tmp_path, monkeypatch):
        """PR #1589 QA round 1: a pause can last a minute with no chunk finishing."""
        ctx, sheets_svc = self._quota_ctx(monkeypatch, 0.01)
        update = sheets_svc.spreadsheets.return_value.values.return_value.update
        update.return_value.execute.side_effect = [self._rate_limit_error(), {}]
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" not in result, result
        messages = [c.args[2] for c in ctx.report_progress.call_args_list]
        assert messages == ["Sheets write quota reached; waiting 0 s", "rows 1-2: ok"]

    async def test_chunks_large_row_counts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 2)
        rows = [["a"]] + [[str(i)] for i in range(5)]
        path = self._write_csv(tmp_path, rows)
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert result["rows_written"] == 6
        update_call = sheets_svc.spreadsheets.return_value.values.return_value.update
        assert update_call.call_count == 3
        # Chunks now write concurrently via asyncio.gather(), so completion order
        # (and thus call_args_list order) isn't guaranteed to match submission order —
        # compare as a set instead of an ordered list.
        ranges = {c.kwargs["range"] for c in update_call.call_args_list}
        assert ranges == {"Sheet1!A1", "Sheet1!A3", "Sheet1!A5"}

    async def test_reports_progress_per_chunk(self, tmp_path, monkeypatch):
        """#355: extends #316/#319's per-item ctx.report_progress pattern to
        import_csv_to_sheet's concurrent chunk writes."""
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 2)
        rows = [["h"]] + [[str(i)] for i in range(5)]
        path = self._write_csv(tmp_path, rows)
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        ctx.report_progress = AsyncMock()
        await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)

        assert ctx.report_progress.await_count == 3
        completed_values = sorted(c.args[0] for c in ctx.report_progress.await_args_list)
        assert completed_values == [1, 2, 3]
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 3  # total chunks
            assert ": ok" in c.args[2]

    async def test_report_progress_failure_does_not_demote_a_successful_chunk(
        self, tmp_path, monkeypatch
    ):
        """PR #351's review established this guard for download_folder/sync_folder:
        a broken notification channel must not turn an already-successful item into
        a failure. #355 extends the same pattern here."""
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 2)
        rows = [["h"], ["1"], ["2"]]
        path = self._write_csv(tmp_path, rows)
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        ctx.report_progress = AsyncMock(side_effect=RuntimeError("connection dropped"))
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert "error" not in result
        assert result["rows_written"] == 3

    async def test_partial_chunk_failure_reports_failed_and_written_ranges(
        self, tmp_path, monkeypatch
    ):
        """One chunk failing among several concurrent writes must not raise a bare
        exception — it must report exactly which row ranges failed vs. wrote
        successfully, since a concurrent partial failure can leave a hole mid-sheet
        rather than a clean truncated prefix (QA finding, #183)."""
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 2)
        rows = [["h"]] + [[str(i)] for i in range(6)]
        path = self._write_csv(tmp_path, rows)
        drive_svc = self._drive_service()
        sheets_svc = self._sheets_service()

        def _make_update_mock(**update_kwargs):
            m = MagicMock()
            if update_kwargs.get("range") == "Sheet1!A3":
                m.execute.side_effect = RuntimeError("simulated API failure")
            else:
                m.execute.return_value = {}
            return m

        sheets_svc.spreadsheets.return_value.values.return_value.update.side_effect = (
            _make_update_mock
        )

        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)

        assert "error" in result
        assert result["spreadsheetId"] == "sheet123"
        assert result["failed_ranges"] == [
            {"start_row": 3, "end_row": 4, "error": "simulated API failure"}
        ]
        written_starts = {w["start_row"] for w in result["written_ranges"]}
        assert written_starts == {1, 5, 7}

    async def test_storage_quota_error_returns_helpful_message(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        drive_svc = as_service_account(MagicMock())
        drive_svc.files.return_value.create.return_value.execute.side_effect = _quota_http_error()
        ctx = _make_ctx(drive_service=drive_svc, sheets_service=MagicMock(), folder_id=None)
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert result["error"] == _SA_QUOTA_ERROR

    async def test_other_403_error_reraises(self, tmp_path):
        path = self._write_csv(tmp_path, [["a"], ["1"]])
        drive_svc = MagicMock()
        drive_svc.files.return_value.create.return_value.execute.side_effect = _other_403_error()
        ctx = _make_ctx(drive_service=drive_svc, sheets_service=MagicMock(), folder_id=None)
        with pytest.raises(HttpError):
            await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)


def _http_error(status: int, body: bytes = b"{}") -> HttpError:
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=body)


class TestImportCsvFailureCleanup:
    """#1574: an import that fails before any row lands removes the spreadsheet it
    created, and never raises the setup's error bare."""

    _helpers = TestImportCsvToSheet()

    def _ctx(self, can_delete=True):
        drive_svc = self._helpers._drive_service()
        created = drive_svc.files.return_value.create.return_value.execute.return_value
        created["capabilities"] = {"canDelete": can_delete}
        sheets_svc = self._helpers._sheets_service()
        folder_cache = MagicMock()
        ctx = _make_ctx(
            drive_service=drive_svc,
            sheets_service=sheets_svc,
            drive_folder_cache=folder_cache,
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        return ctx, drive_svc, sheets_svc, folder_cache

    async def _run(self, ctx, tmp_path, rows=None):
        path = self._helpers._write_csv(tmp_path, rows or [["a"], ["1"]])
        return await _drive_tools["import_csv_to_sheet"](
            local_path=str(path), title="X", folder_id="folder1", ctx=ctx
        )

    async def test_create_asks_for_can_delete(self, tmp_path):
        ctx, drive_svc, _, _ = self._ctx()
        await self._run(ctx, tmp_path)
        fields = drive_svc.files.return_value.create.call_args.kwargs["fields"]
        assert "capabilities(canDelete)" in fields

    async def test_success_removes_nothing(self, tmp_path):
        ctx, drive_svc, _, _ = self._ctx()
        result = await self._run(ctx, tmp_path)
        assert result["rows_written"] == 2
        drive_svc.files.return_value.delete.assert_not_called()
        drive_svc.files.return_value.update.assert_not_called()

    async def test_refused_resize_deletes_the_spreadsheet(self, tmp_path):
        """The live case: a grid over the 20M-cell limit raised a raw HttpError and
        left an empty spreadsheet in the folder."""
        ctx, drive_svc, sheets_svc, folder_cache = self._ctx()
        refusal = _http_error(400, b'{"error": {"message": "above the limit"}}')
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        batch.return_value.execute.side_effect = refusal
        result = await self._run(ctx, tmp_path)
        assert result == {
            "error": f"Setting up the sheet failed ({refusal}). No rows were written, "
            "and the new spreadsheet was deleted."
        }
        delete = drive_svc.files.return_value.delete
        delete.assert_called_once_with(fileId="sheet123", supportsAllDrives=True)
        sheets_svc.spreadsheets.return_value.values.return_value.update.assert_not_called()
        folder_cache.mark_dirty.assert_called_with("folder1")

    async def test_resize_that_may_have_landed_still_deletes(self, tmp_path):
        """No row write has started, so a 5xx or timeout on the resize loses nothing."""
        for error in (_http_error(500), TimeoutError("timed out")):
            ctx, drive_svc, sheets_svc, _ = self._ctx()
            batch = sheets_svc.spreadsheets.return_value.batchUpdate
            batch.return_value.execute.side_effect = error
            result = await self._run(ctx, tmp_path)
            assert set(result) == {"error"}, error
            assert "was deleted" in result["error"], error
            drive_svc.files.return_value.delete.assert_called_once()

    async def test_failed_sheet_read_deletes_the_spreadsheet(self, tmp_path):
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        sheets_svc.spreadsheets.return_value.get.return_value.execute.side_effect = _http_error(503)
        result = await self._run(ctx, tmp_path)
        assert set(result) == {"error"}
        assert result["error"].startswith("Setting up the sheet failed (")
        drive_svc.files.return_value.delete.assert_called_once()

    async def test_trashes_when_the_identity_cannot_delete(self, tmp_path):
        """A Content manager on a Shared Drive can trash but not delete (#876)."""
        ctx, drive_svc, sheets_svc, _ = self._ctx(can_delete=False)
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        batch.return_value.execute.side_effect = _http_error(400)
        result = await self._run(ctx, tmp_path)
        assert result["error"].endswith("the new spreadsheet was moved to the trash.")
        drive_svc.files.return_value.delete.assert_not_called()
        drive_svc.files.return_value.update.assert_called_once_with(
            fileId="sheet123", body={"trashed": True}, supportsAllDrives=True, fields="id"
        )

    async def test_removal_is_retried_on_transient_errors(self, tmp_path):
        """PR #1599 QA round 1: one 5xx or 429 on the removal left the spreadsheet."""
        for can_delete, method in ((True, "delete"), (False, "update")):
            ctx, drive_svc, sheets_svc, _ = self._ctx(can_delete=can_delete)
            batch = sheets_svc.spreadsheets.return_value.batchUpdate
            batch.return_value.execute.side_effect = _http_error(400)
            await self._run(ctx, tmp_path)
            execute = getattr(drive_svc.files.return_value, method).return_value.execute
            execute.assert_called_once()
            assert execute.call_args.kwargs["num_retries"] == drive_files_module._CLEANUP_RETRIES

    async def test_404_after_a_retried_delete_counts_as_deleted(self, tmp_path):
        """A retried delete whose earlier attempt landed finds the file gone. The folder
        is still invalidated for it (PR #1599 QA round 2: `invalidating` skips its
        callback on a 4xx that leaves the block)."""
        ctx, drive_svc, sheets_svc, folder_cache = self._ctx(can_delete=True)
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        batch.return_value.execute.side_effect = _http_error(400)
        drive_svc.files.return_value.delete.return_value.execute.side_effect = _http_error(404)
        result = await self._run(ctx, tmp_path)
        assert set(result) == {"error"}
        assert result["error"].endswith("the new spreadsheet was deleted.")
        # Once for the create, once for the delete.
        assert [c.args for c in folder_cache.mark_dirty.call_args_list] == [("folder1",)] * 2

    async def test_404_without_known_delete_permission_is_a_failed_removal(self, tmp_path):
        """Drive answers a delete it doesn't permit with a 404 too (#876), so a 404 is
        trusted only when the create said canDelete is true."""
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        created = drive_svc.files.return_value.create.return_value.execute.return_value
        del created["capabilities"]
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        batch.return_value.execute.side_effect = _http_error(400)
        drive_svc.files.return_value.delete.return_value.execute.side_effect = _http_error(404)
        result = await self._run(ctx, tmp_path)
        assert result["spreadsheetId"] == "sheet123"
        assert "it is left in place" in result["error"]

    async def test_failed_removal_names_the_spreadsheet(self, tmp_path):
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        batch = sheets_svc.spreadsheets.return_value.batchUpdate
        batch.return_value.execute.side_effect = _http_error(400)
        drive_svc.files.return_value.delete.return_value.execute.side_effect = RuntimeError(
            "delete broke"
        )
        result = await self._run(ctx, tmp_path)
        assert "Removing the new, empty spreadsheet failed too (delete broke)" in (result["error"])
        assert result["spreadsheetId"] == "sheet123"
        assert result["title"] == "Imported"
        assert result["web_link"] == "https://docs.google.com/spreadsheets/d/sheet123"

    def _chunk_effects(self, sheets_svc, by_range):
        """values().update(range=R).execute raises by_range[R] when given, else succeeds."""

        def _update(**kwargs):
            m = MagicMock()
            effect = by_range.get(kwargs["range"])
            if effect is None:
                m.execute.return_value = {}
            else:
                m.execute.side_effect = effect
            return m

        sheets_svc.spreadsheets.return_value.values.return_value.update.side_effect = _update

    async def test_every_chunk_refused_deletes_the_spreadsheet(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 1)
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        refusal = _http_error(400)
        self._chunk_effects(sheets_svc, {"Sheet1!A1": refusal, "Sheet1!A2": _http_error(403)})
        result = await self._run(ctx, tmp_path)
        assert result == {
            "error": f"All 2 row writes were refused ({refusal}). No rows were written, "
            "and the new spreadsheet was deleted."
        }
        drive_svc.files.return_value.delete.assert_called_once()

    async def test_a_chunk_that_may_have_landed_keeps_the_spreadsheet(self, tmp_path, monkeypatch):
        """A 5xx may have been written, so the partial-failure result stands."""
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 1)
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        self._chunk_effects(
            sheets_svc, {"Sheet1!A1": _http_error(400), "Sheet1!A2": _http_error(500)}
        )
        result = await self._run(ctx, tmp_path)
        assert result["spreadsheetId"] == "sheet123"
        assert [r["start_row"] for r in result["failed_ranges"]] == [1, 2]
        drive_svc.files.return_value.delete.assert_not_called()

    async def test_some_rows_written_keeps_the_spreadsheet(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 1)
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        self._chunk_effects(sheets_svc, {"Sheet1!A1": _http_error(400)})
        result = await self._run(ctx, tmp_path)
        assert result["written_ranges"] == [{"start_row": 2, "end_row": 2}]
        assert "rejected" not in result["failed_ranges"][0]
        drive_svc.files.return_value.delete.assert_not_called()

    async def test_unexpected_chunk_exception_keeps_the_spreadsheet(self, tmp_path):
        """A non-HttpError says nothing about whether the write landed."""
        ctx, drive_svc, sheets_svc, _ = self._ctx()
        self._chunk_effects(sheets_svc, {"Sheet1!A1": RuntimeError("boom")})
        result = await self._run(ctx, tmp_path)
        assert result["failed_ranges"][0]["error"] == "boom"
        drive_svc.files.return_value.delete.assert_not_called()


class TestRateLimitPause:
    """_RateLimitPause: one import's shared pause for its chunk writes (#1573)."""

    @pytest.fixture
    def clock(self, monkeypatch):
        now = [1000.0]
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = lambda: now[0]
        monkeypatch.setattr(drive_files_module, "time", fake_time)
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_BASE_DELAY", 5.0)
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_MAX_DELAY", 60.0)
        monkeypatch.setattr(drive_files_module, "_CSV_RATE_LIMIT_MAX_WAIT", 600.0)
        return now

    @pytest.fixture
    def slept(self, clock, monkeypatch):
        """Sleeps advance the fake clock instead of waiting."""
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds

        monkeypatch.setattr(drive_files_module.asyncio, "sleep", fake_sleep)
        return slept

    @staticmethod
    def _refusal():
        resp = MagicMock()
        resp.status = 429
        return HttpError(resp=resp, content=b"{}")

    @staticmethod
    async def _no_report(seconds):
        pass

    def test_a_429_pauses_every_write_for_the_base_delay(self, clock):
        pause = drive_files_module._RateLimitPause()
        assert pause._rate_limited(sent_at=1000.0) == 5.0
        assert pause._resume_at == 1005.0

    def test_a_429_on_a_request_sent_before_the_pause_does_not_extend_it(self, clock):
        pause = drive_files_module._RateLimitPause()
        pause._rate_limited(sent_at=1000.0)
        clock[0] = 1001.0
        # In flight when the pause began: it says nothing new about the quota.
        assert pause._rate_limited(sent_at=999.5) == 0.0
        assert pause._resume_at == 1005.0

    def test_a_429_after_the_pause_doubles_it_up_to_the_cap(self, clock):
        pause = drive_files_module._RateLimitPause()
        waits = []
        for _ in range(6):
            waits.append(pause._rate_limited(sent_at=clock[0]))
            clock[0] = pause._resume_at
        assert waits == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]

    def test_a_success_sent_after_the_pause_resets_the_delay(self, clock):
        pause = drive_files_module._RateLimitPause()
        pause._rate_limited(sent_at=clock[0])
        clock[0] = pause._resume_at
        pause._rate_limited(sent_at=clock[0])
        clock[0] = pause._resume_at
        pause._succeeded(sent_at=clock[0])
        assert pause._rate_limited(sent_at=clock[0]) == 5.0

    def test_a_success_sent_before_the_pause_keeps_the_delay(self, clock):
        """PR #1589 QA round 1: a late 200 from an earlier burst reset the doubling, so
        the pause never grew past the base delay."""
        pause = drive_files_module._RateLimitPause()
        pause._rate_limited(sent_at=1000.0)  # 5 s, started at 1000
        clock[0] = 1005.0
        pause._rate_limited(sent_at=1005.0)  # 10 s, started at 1005
        pause._succeeded(sent_at=1002.0)  # sent before that pause began
        clock[0] = 1015.0
        assert pause._rate_limited(sent_at=1015.0) == 20.0

    def test_no_pause_runs_past_the_deadline(self, clock):
        pause = drive_files_module._RateLimitPause()
        clock[0] = 1598.0
        assert pause._rate_limited(sent_at=clock[0]) == 2.0
        assert pause._resume_at == 1600.0

    def test_a_429_at_the_deadline_is_final(self, clock):
        pause = drive_files_module._RateLimitPause()
        clock[0] = 1600.0
        assert pause._rate_limited(sent_at=clock[0]) is None

    async def test_send_waits_out_the_pause_then_resends(self, clock, slept):
        pause = drive_files_module._RateLimitPause()
        outcomes = [self._refusal(), "done"]
        sends = []

        async def call():
            sends.append(clock[0])
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        reports = []

        async def on_pause(seconds):
            reports.append(seconds)

        assert await pause.send(call, on_pause) == "done"
        assert sends == [1000.0, 1005.0]
        assert slept == [5.0]
        assert reports == [5.0]

    async def test_send_waits_out_a_pause_already_on_without_reporting_it(self, clock, slept):
        """Another write started this pause and reported it; this one only waits."""
        pause = drive_files_module._RateLimitPause()
        pause._rate_limited(sent_at=1000.0)
        reports = []

        async def on_pause(seconds):
            reports.append(seconds)

        sends = []

        async def call():
            sends.append(clock[0])
            return "ok"

        assert await pause.send(call, on_pause) == "ok"
        assert sends == [1005.0]
        assert slept == [5.0]
        assert reports == []

    async def test_send_raises_other_errors_without_resending(self, clock, slept):
        pause = drive_files_module._RateLimitPause()
        resp = MagicMock()
        resp.status = 500
        calls = []

        async def call():
            calls.append(1)
            raise HttpError(resp=resp, content=b"{}")

        with pytest.raises(HttpError):
            await pause.send(call, self._no_report)
        assert calls == [1]
        assert slept == []

    async def test_send_raises_the_429_once_the_deadline_has_passed(self, clock, slept):
        pause = drive_files_module._RateLimitPause()
        calls = []

        async def call():
            calls.append(clock[0])
            raise self._refusal()

        with pytest.raises(HttpError):
            await pause.send(call, self._no_report)
        # 5, 10, 20, 40, then 60 s pauses until the last one is cut at the deadline.
        assert calls[-1] == 1600.0
        assert sum(slept) == 600.0


class TestCsvImportWriteConcurrency:
    """PR #1589 QA round 1: with no limit, every chunk passed the pause at once and
    queued in the thread pool, to be sent during a later pause."""

    async def test_writes_in_flight_never_exceed_the_limit(self, tmp_path, monkeypatch):
        import threading
        import time as real_time

        monkeypatch.setattr(drive_files_module, "_CSV_IMPORT_CHUNK_ROWS", 1)
        monkeypatch.setattr(drive_files_module, "_CSV_WRITE_CONCURRENCY", 2)
        lock = threading.Lock()
        in_flight = [0]
        peak = [0]

        def execute(*args, **kwargs):
            with lock:
                in_flight[0] += 1
                peak[0] = max(peak[0], in_flight[0])
            real_time.sleep(0.02)
            with lock:
                in_flight[0] -= 1
            return {}

        path = tmp_path / "rows.csv"
        path.write_text("".join(f"{i}\n" for i in range(12)), encoding="utf-8")
        helper = TestImportCsvToSheet()
        sheets_svc = helper._sheets_service(row_count=12, column_count=1)
        update = sheets_svc.spreadsheets.return_value.values.return_value.update
        update.return_value.execute.side_effect = execute
        ctx = _make_ctx(
            drive_service=helper._drive_service(),
            sheets_service=sheets_svc,
            drive_folder_cache=MagicMock(),
            sheet_data_cache=MagicMock(),
            cache=MagicMock(),
            folder_id=None,
        )
        result = await _drive_tools["import_csv_to_sheet"](local_path=str(path), title="X", ctx=ctx)
        assert result["rows_written"] == 12
        assert update.return_value.execute.call_count == 12
        assert peak[0] == 2
