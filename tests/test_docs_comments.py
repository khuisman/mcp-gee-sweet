"""Tests for docs comments tools — list_doc_comments, add_doc_comment, resolve_doc_comment (#151)."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import docs as docs_module


def _make_tool_registry():
    captured = {}
    captured_annotations = {}

    def tool(annotations=None):
        def decorator(func):
            captured[func.__name__] = func
            captured_annotations[func.__name__] = annotations
            return func

        return decorator

    return tool, captured, captured_annotations


def _make_ctx(**services):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    for k, v in services.items():
        setattr(lc, k, v)
    return ctx


_docs_tool, _docs_tools, _docs_annotations = _make_tool_registry()
docs_module.register(_docs_tool)


class TestToolAnnotations:
    """Mutating comment tools must set destructive_hint, like every other mutating tool.

    ToolAnnotations still accepts either the camelCase wire alias or the snake_case
    field name at construction time (mcp v2 kept `populate_by_name=True`), but only
    the real field name (snake_case as of mcp==2.0.0, issue #175) is readable back
    as an attribute — confirmed live.
    """

    def test_add_doc_comment_has_destructive_hint(self):
        assert _docs_annotations["add_doc_comment"].destructive_hint is True

    def test_resolve_doc_comment_has_destructive_hint(self):
        assert _docs_annotations["resolve_doc_comment"].destructive_hint is True

    def test_list_doc_comments_is_read_only_not_destructive(self):
        assert _docs_annotations["list_doc_comments"].read_only_hint is True


class TestListDocComments:
    def _ctx(self, drive_svc=None):
        return _make_ctx(drive_service=drive_svc or MagicMock())

    async def test_maps_camel_case_fields_to_snake_case_output(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {
            "comments": [
                {
                    "id": "c1",
                    "content": "Looks good",
                    "author": {"displayName": "Alice", "emailAddress": "alice@example.com"},
                    "createdTime": "2026-07-01T00:00:00Z",
                    "modifiedTime": "2026-07-01T00:00:00Z",
                    "resolved": False,
                    "deleted": False,
                    "quotedFileContent": {"value": "the quoted sentence"},
                    "replies": [
                        {
                            "id": "r1",
                            "content": "Agreed",
                            "author": {"displayName": "Bob", "emailAddress": "bob@example.com"},
                            "createdTime": "2026-07-01T01:00:00Z",
                            "modifiedTime": "2026-07-01T01:05:00Z",
                            "action": None,
                            "deleted": False,
                        }
                    ],
                }
            ]
        }
        ctx = self._ctx(drive)
        result = await _docs_tools["list_doc_comments"](doc_id="doc1", ctx=ctx)

        assert result["doc_id"] == "doc1"
        assert len(result["comments"]) == 1
        comment = result["comments"][0]
        assert comment["id"] == "c1"
        assert comment["author"] == {"display_name": "Alice", "email_address": "alice@example.com"}
        assert comment["created_time"] == "2026-07-01T00:00:00Z"
        assert comment["quoted_text"] == "the quoted sentence"
        assert comment["resolved"] is False
        assert len(comment["replies"]) == 1
        assert comment["replies"][0]["author"]["display_name"] == "Bob"
        assert comment["replies"][0]["modified_time"] == "2026-07-01T01:05:00Z"

    async def test_empty_comments_returns_empty_list(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        ctx = self._ctx(drive)
        result = await _docs_tools["list_doc_comments"](doc_id="doc1", ctx=ctx)
        assert result == {"doc_id": "doc1", "comments": []}

    async def test_next_page_token_included_when_present(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {
            "comments": [],
            "nextPageToken": "tok-123",
        }
        ctx = self._ctx(drive)
        result = await _docs_tools["list_doc_comments"](doc_id="doc1", ctx=ctx)
        assert result["next_page_token"] == "tok-123"

    async def test_next_page_token_omitted_when_absent(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        ctx = self._ctx(drive)
        result = await _docs_tools["list_doc_comments"](doc_id="doc1", ctx=ctx)
        assert "next_page_token" not in result

    async def test_page_size_clamped_to_valid_range(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        ctx = self._ctx(drive)
        await _docs_tools["list_doc_comments"](doc_id="doc1", page_size=500, ctx=ctx)
        call_kwargs = drive.comments.return_value.list.call_args.kwargs
        assert call_kwargs["pageSize"] == 100

    async def test_comment_with_no_quoted_content_has_none_quoted_text(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {
            "comments": [
                {
                    "id": "c1",
                    "content": "General note",
                    "author": {"displayName": "Alice"},
                    "createdTime": "2026-07-01T00:00:00Z",
                    "resolved": False,
                    "deleted": False,
                    "replies": [],
                }
            ]
        }
        ctx = self._ctx(drive)
        result = await _docs_tools["list_doc_comments"](doc_id="doc1", ctx=ctx)
        assert result["comments"][0]["quoted_text"] is None


class TestAddDocComment:
    def _ctx(self, drive_svc=None):
        return _make_ctx(drive_service=drive_svc or MagicMock())

    def _drive_svc(self, comment_id="c-new"):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.return_value = {
            "id": comment_id,
            "content": "New comment",
            "author": {"displayName": "Alice", "emailAddress": "alice@example.com"},
            "createdTime": "2026-07-01T00:00:00Z",
        }
        return drive

    async def test_creates_comment_without_quoted_text(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        result = await _docs_tools["add_doc_comment"](doc_id="doc1", content="New comment", ctx=ctx)
        create_body = drive.comments.return_value.create.call_args.kwargs["body"]
        assert create_body == {"content": "New comment"}
        assert result["id"] == "c-new"
        assert result["quoted_text"] is None

    async def test_creates_comment_with_quoted_text_anchor(self):
        drive = self._drive_svc()
        drive.comments.return_value.create.return_value.execute.return_value[
            "quotedFileContent"
        ] = {"value": "the anchored sentence"}
        ctx = self._ctx(drive)
        result = await _docs_tools["add_doc_comment"](
            doc_id="doc1",
            content="New comment",
            quoted_text="the anchored sentence",
            ctx=ctx,
        )
        create_body = drive.comments.return_value.create.call_args.kwargs["body"]
        assert create_body["quotedFileContent"] == {"value": "the anchored sentence"}
        assert result["quoted_text"] == "the anchored sentence"

    async def test_file_id_passed_through_to_api(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        await _docs_tools["add_doc_comment"](doc_id="doc-xyz", content="hi", ctx=ctx)
        assert drive.comments.return_value.create.call_args.kwargs["fileId"] == "doc-xyz"

    async def test_maps_author_to_snake_case(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        result = await _docs_tools["add_doc_comment"](doc_id="doc1", content="hi", ctx=ctx)
        assert result["author"] == {"display_name": "Alice", "email_address": "alice@example.com"}


class TestResolveDocComment:
    def _ctx(self, drive_svc=None):
        return _make_ctx(drive_service=drive_svc or MagicMock())

    def _drive_svc(self, reply_id="r-new"):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.return_value = {
            "id": reply_id,
            "action": "resolve",
        }
        return drive

    async def test_resolves_without_reply_content(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        result = await _docs_tools["resolve_doc_comment"](doc_id="doc1", comment_id="c1", ctx=ctx)
        create_body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert create_body == {"action": "resolve"}
        assert result == {
            "doc_id": "doc1",
            "comment_id": "c1",
            "reply_id": "r-new",
            "action": "resolve",
        }

    async def test_resolves_with_reply_content(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        await _docs_tools["resolve_doc_comment"](
            doc_id="doc1", comment_id="c1", reply_content="Fixed, thanks!", ctx=ctx
        )
        create_body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert create_body == {"action": "resolve", "content": "Fixed, thanks!"}

    async def test_ids_passed_through_to_api(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        await _docs_tools["resolve_doc_comment"](doc_id="doc-A", comment_id="comment-B", ctx=ctx)
        call_kwargs = drive.replies.return_value.create.call_args.kwargs
        assert call_kwargs["fileId"] == "doc-A"
        assert call_kwargs["commentId"] == "comment-B"
