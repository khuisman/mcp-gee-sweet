"""Tests for tools/drive/comments.py: list_file_comments, add_file_comment,
reply_to_comment, and the deprecated resolve_doc_comment (#151, #663)."""

import inspect
import json
import typing
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import Context
from pydantic import ValidationError

from mcp_gee_sweet import server, tool_groups
from mcp_gee_sweet.deprecation import DEPRECATION_WARNINGS_KEY, tool_deprecation
from mcp_gee_sweet.tools.drive import comments as comments_module


def _make_tool_registry():
    captured = {}
    captured_annotations = {}

    def tool(annotations=None, local_only=False, **_):
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


_comments_tool, _tools, _annotations = _make_tool_registry()
comments_module.register(_comments_tool)


class TestToolAnnotations:
    """Mutating comment tools must set destructive_hint, like every other mutating tool.

    ToolAnnotations still accepts either the camelCase wire alias or the snake_case
    field name at construction time (mcp v2 kept `populate_by_name=True`), but only
    the real field name (snake_case as of mcp==2.0.0, issue #175) is readable back
    as an attribute — confirmed live.
    """

    def test_add_file_comment_has_destructive_hint(self):
        assert _annotations["add_file_comment"].destructive_hint is True

    def test_resolve_doc_comment_has_destructive_hint(self):
        assert _annotations["resolve_doc_comment"].destructive_hint is True

    def test_list_file_comments_is_read_only_not_destructive(self):
        assert _annotations["list_file_comments"].read_only_hint is True


class TestListFileComments:
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
        result = await _tools["list_file_comments"](file_id="doc1", ctx=ctx)

        assert result["file_id"] == "doc1"
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
        result = await _tools["list_file_comments"](file_id="doc1", ctx=ctx)
        assert result == {"file_id": "doc1", "comments": []}

    async def test_next_page_token_included_when_present(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {
            "comments": [],
            "nextPageToken": "tok-123",
        }
        ctx = self._ctx(drive)
        result = await _tools["list_file_comments"](file_id="doc1", ctx=ctx)
        assert result["next_page_token"] == "tok-123"

    async def test_next_page_token_omitted_when_absent(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        ctx = self._ctx(drive)
        result = await _tools["list_file_comments"](file_id="doc1", ctx=ctx)
        assert "next_page_token" not in result

    async def test_page_size_clamped_to_valid_range(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        ctx = self._ctx(drive)
        await _tools["list_file_comments"](file_id="doc1", page_size=500, ctx=ctx)
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
        result = await _tools["list_file_comments"](file_id="doc1", ctx=ctx)
        assert result["comments"][0]["quoted_text"] is None

    async def test_quoted_text_is_html_unescaped(self):
        # Drive returns quotedFileContent.value HTML-escaped (#984, seen live).
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {
            "comments": [
                {
                    "id": "c1",
                    "content": "note",
                    "quotedFileContent": {
                        "value": "Caf&#233; and Tom &amp; Jerry, a &lt; b, say &quot;hi&quot; it&#39;s"
                    },
                    "replies": [],
                },
                {
                    "id": "c2",
                    "content": "literal entity",
                    "quotedFileContent": {"value": "&amp;amp; literal"},
                    "replies": [],
                },
            ]
        }
        ctx = self._ctx(drive)
        result = await _tools["list_file_comments"](file_id="doc1", ctx=ctx)
        assert [c["quoted_text"] for c in result["comments"]] == [
            'Café and Tom & Jerry, a < b, say "hi" it\'s',
            "&amp; literal",
        ]


class TestAddFileComment:
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
        result = await _tools["add_file_comment"](file_id="doc1", content="New comment", ctx=ctx)
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
        result = await _tools["add_file_comment"](
            file_id="doc1",
            content="New comment",
            quoted_text="the anchored sentence",
            ctx=ctx,
        )
        create_body = drive.comments.return_value.create.call_args.kwargs["body"]
        assert create_body["quotedFileContent"] == {"value": "the anchored sentence"}
        assert result["quoted_text"] == "the anchored sentence"

    async def test_quoted_text_echo_is_html_unescaped(self):
        drive = self._drive_svc()
        drive.comments.return_value.create.return_value.execute.return_value[
            "quotedFileContent"
        ] = {"value": "Caf&#233; &lt;b&gt; &amp; &quot;x&quot;"}
        ctx = self._ctx(drive)
        result = await _tools["add_file_comment"](
            file_id="doc1", content="c", quoted_text='Café <b> & "x"', ctx=ctx
        )
        create_body = drive.comments.return_value.create.call_args.kwargs["body"]
        assert create_body["quotedFileContent"] == {"value": 'Café <b> & "x"'}
        assert result["quoted_text"] == 'Café <b> & "x"'

    async def test_file_id_passed_through_to_api(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        await _tools["add_file_comment"](file_id="doc-xyz", content="hi", ctx=ctx)
        assert drive.comments.return_value.create.call_args.kwargs["fileId"] == "doc-xyz"

    async def test_anchor_is_passed_through_and_echoed(self):
        region = '{"r": "head", "a": [{"rect": {"x": 1, "y": 2, "w": 3, "h": 4}}]}'
        drive = self._drive_svc()
        drive.comments.return_value.create.return_value.execute.return_value["anchor"] = region
        ctx = self._ctx(drive)
        result = await _tools["add_file_comment"](
            file_id="img1", content="here", anchor=region, ctx=ctx
        )
        call_kwargs = drive.comments.return_value.create.call_args.kwargs
        assert call_kwargs["body"] == {"content": "here", "anchor": region}
        assert "anchor" in call_kwargs["fields"].split(",")
        assert result["anchor"] == region

    async def test_no_anchor_sends_none_and_echoes_none(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        result = await _tools["add_file_comment"](file_id="f1", content="hi", ctx=ctx)
        assert "anchor" not in drive.comments.return_value.create.call_args.kwargs["body"]
        assert result["anchor"] is None

    def test_docstring_says_anchoring_is_inert_in_the_google_editors(self):
        doc = " ".join(_tools["add_file_comment"].__doc__.split())
        assert "doesn't pin the comment to a position" in doc
        assert "the Google editors ignore it" in doc

    async def test_maps_author_to_snake_case(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        result = await _tools["add_file_comment"](file_id="doc1", content="hi", ctx=ctx)
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
        result = await _tools["resolve_doc_comment"](doc_id="doc1", comment_id="c1", ctx=ctx)
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
        await _tools["resolve_doc_comment"](
            doc_id="doc1", comment_id="c1", reply_content="Fixed, thanks!", ctx=ctx
        )
        create_body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert create_body == {"action": "resolve", "content": "Fixed, thanks!"}

    async def test_whitespace_reply_content_isnt_sent(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        await _tools["resolve_doc_comment"](
            doc_id="doc1", comment_id="c1", reply_content="  ", ctx=ctx
        )
        create_body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert create_body == {"action": "resolve"}

    async def test_ids_passed_through_to_api(self):
        drive = self._drive_svc()
        ctx = self._ctx(drive)
        await _tools["resolve_doc_comment"](doc_id="doc-A", comment_id="comment-B", ctx=ctx)
        call_kwargs = drive.replies.return_value.create.call_args.kwargs
        assert call_kwargs["fileId"] == "doc-A"
        assert call_kwargs["commentId"] == "comment-B"


def _http_error(status: int, message: str) -> HttpError:
    resp = MagicMock()
    resp.status = status
    content = json.dumps({"error": {"message": message}}).encode()
    return HttpError(resp=resp, content=content)


class TestReplyToComment:
    def _drive_svc(self, **reply):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.return_value = {
            "id": "r-new",
            "createdTime": "2026-11-19T00:00:00Z",
            **reply,
        }
        return drive

    def test_annotations_mark_it_destructive(self):
        assert _annotations["reply_to_comment"].destructive_hint is True

    async def test_plain_reply_sends_content_without_an_action(self):
        drive = self._drive_svc(content="Thanks")
        result = await _tools["reply_to_comment"](
            file_id="f1", comment_id="c1", content="Thanks", ctx=_make_ctx(drive_service=drive)
        )
        call_kwargs = drive.replies.return_value.create.call_args.kwargs
        assert call_kwargs["body"] == {"content": "Thanks"}
        assert call_kwargs["fileId"] == "f1" and call_kwargs["commentId"] == "c1"
        assert result == {
            "file_id": "f1",
            "comment_id": "c1",
            "reply_id": "r-new",
            "action": None,
            "content": "Thanks",
            "created_time": "2026-11-19T00:00:00Z",
        }

    @pytest.mark.parametrize("action", ["resolve", "reopen"])
    async def test_action_without_content(self, action):
        # Drive returns an empty string for a reply with no text (seen live, #663).
        drive = self._drive_svc(action=action, content="")
        result = await _tools["reply_to_comment"](
            file_id="f1", comment_id="c1", action=action, ctx=_make_ctx(drive_service=drive)
        )
        assert drive.replies.return_value.create.call_args.kwargs["body"] == {"action": action}
        assert result["action"] == action
        assert result["content"] == ""

    async def test_action_with_content(self):
        drive = self._drive_svc(action="resolve", content="Done")
        await _tools["reply_to_comment"](
            file_id="f1",
            comment_id="c1",
            content="Done",
            action="resolve",
            ctx=_make_ctx(drive_service=drive),
        )
        body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert body == {"action": "resolve", "content": "Done"}

    @pytest.mark.parametrize("content", [None, "", "   ", "\n\t "])
    async def test_neither_content_nor_action_is_an_error_without_a_call(self, content):
        drive = MagicMock()
        result = await _tools["reply_to_comment"](
            file_id="f1", comment_id="c1", content=content, ctx=_make_ctx(drive_service=drive)
        )
        assert "error" in result
        drive.replies.assert_not_called()

    async def test_whitespace_content_with_an_action_isnt_sent(self):
        # Drive stores whitespace-only content as an empty reply (PR #1563 round 1).
        drive = self._drive_svc(action="resolve", content="")
        await _tools["reply_to_comment"](
            file_id="f1",
            comment_id="c1",
            content="   ",
            action="resolve",
            ctx=_make_ctx(drive_service=drive),
        )
        body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert body == {"action": "resolve"}

    async def test_content_keeps_its_own_whitespace(self):
        drive = self._drive_svc(content="  hi  ")
        await _tools["reply_to_comment"](
            file_id="f1", comment_id="c1", content="  hi  ", ctx=_make_ctx(drive_service=drive)
        )
        body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert body == {"content": "  hi  "}

    def test_docstring_says_a_plain_reply_reopens_a_resolved_comment(self):
        # Drive reopens it itself, and returns action "reopen" (PR #1563 round 4, seen live).
        doc = " ".join(_tools["reply_to_comment"].__doc__.split())
        assert "A plain reply to a resolved comment reopens it" in doc
        assert '"reopen" when a plain reply reopened a resolved one' in doc

    def test_action_is_limited_to_resolve_and_reopen(self):
        # mcp validates arguments against this annotation before the call.
        sig = inspect.signature(_tools["reply_to_comment"])
        assert typing.get_args(sig.parameters["action"].annotation) == (
            typing.Literal["resolve", "reopen"],
            type(None),
        )


class TestApiErrorsPropagate:
    """An API failure raises out of the tool, so the caller sees Drive's own error,
    never an empty list or a success (the live cases in drive_comments.md check the
    same)."""

    async def test_list_on_a_missing_file(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.side_effect = _http_error(
            404, "File not found: nope."
        )
        with pytest.raises(HttpError, match="File not found"):
            await _tools["list_file_comments"](file_id="nope", ctx=_make_ctx(drive_service=drive))

    async def test_add_without_comment_permission(self):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.side_effect = _http_error(
            403, "The user does not have sufficient permissions for this file."
        )
        with pytest.raises(HttpError, match="sufficient permissions"):
            await _tools["add_file_comment"](
                file_id="f1", content="hi", ctx=_make_ctx(drive_service=drive)
            )

    async def test_reply_to_a_missing_comment(self):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.side_effect = _http_error(
            404, "Comment not found: nope."
        )
        with pytest.raises(HttpError, match="Comment not found"):
            await _tools["reply_to_comment"](
                file_id="f1",
                comment_id="nope",
                action="resolve",
                ctx=_make_ctx(drive_service=drive),
            )

    async def test_resolve_doc_comment_on_a_missing_comment(self):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.side_effect = _http_error(
            404, "Comment not found: nope."
        )
        with pytest.raises(HttpError, match="Comment not found"):
            await _tools["resolve_doc_comment"](
                doc_id="f1", comment_id="nope", ctx=_make_ctx(drive_service=drive)
            )


class TestDeprecatedNames:
    """#663: the old tool names, `doc_id`, and resolve_doc_comment last one release."""

    @pytest.mark.parametrize(
        ("old", "new"),
        [("list_doc_comments", "list_file_comments"), ("add_doc_comment", "add_file_comment")],
    )
    def test_old_tool_names_are_renamed_entries(self, old, new):
        assert tool_groups.RENAMED_TOOLS[old].new == new
        assert tool_groups.RENAMED_TOOLS[old].removed_in == comments_module.COMMENTS_RENAMED_IN

    async def test_list_accepts_doc_id_with_a_warning(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        result = await _tools["list_file_comments"](
            doc_id="doc1", ctx=_make_ctx(drive_service=drive)
        )
        assert drive.comments.return_value.list.call_args.kwargs["fileId"] == "doc1"
        assert result["file_id"] == "doc1"
        assert result[DEPRECATION_WARNINGS_KEY] == [
            "`doc_id` is deprecated: use `file_id`. `doc_id` is removed in the next "
            "feature release."
        ]

    async def test_add_accepts_doc_id_with_a_warning(self):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.return_value = {"id": "c1"}
        result = await _tools["add_file_comment"](
            doc_id="doc1", content="hi", ctx=_make_ctx(drive_service=drive)
        )
        assert drive.comments.return_value.create.call_args.kwargs["fileId"] == "doc1"
        assert result["id"] == "c1"
        assert DEPRECATION_WARNINGS_KEY in result

    async def test_file_id_alone_has_no_warning(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        result = await _tools["list_file_comments"](
            file_id="doc1", ctx=_make_ctx(drive_service=drive)
        )
        assert DEPRECATION_WARNINGS_KEY not in result

    def test_resolve_doc_comment_is_deprecated_toward_reply_to_comment(self):
        func = _tools["resolve_doc_comment"]
        assert tool_deprecation(func).use == "`reply_to_comment` with `action='resolve'`"
        assert func.__doc__.startswith(
            "Deprecated: use `reply_to_comment` with `action='resolve'` instead."
        )


def _server_ctx(drive):
    lifespan = SimpleNamespace(unauthorized_message=None, auth_method="oauth", drive_service=drive)
    return Context(
        request_context=SimpleNamespace(lifespan_context=lifespan), mcp_server=server.mcp
    )


class TestRegisteredAliases:
    """Through the server's own registry (the test process runs with ENABLED_TOOLS=all,
    which registers every alias) and mcp's argument validation, so a call made the way
    an old client makes it is what's tested."""

    def test_aliases_are_registered(self):
        assert {"list_doc_comments", "add_doc_comment"} <= set(server._registered_aliases)

    async def test_old_name_with_old_parameter(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        result = await server.mcp.call_tool(
            "list_doc_comments", {"doc_id": "doc1"}, _server_ctx(drive)
        )
        content = result.structured_content
        assert content["file_id"] == "doc1"
        assert content[DEPRECATION_WARNINGS_KEY]

    async def test_old_name_with_new_parameter(self):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.return_value = {"id": "c1"}
        result = await server.mcp.call_tool(
            "add_doc_comment", {"file_id": "doc1", "content": "hi"}, _server_ctx(drive)
        )
        assert result.structured_content["id"] == "c1"
        assert DEPRECATION_WARNINGS_KEY not in result.structured_content

    async def test_reply_to_comment_refuses_an_unknown_action(self):
        drive = MagicMock()
        with pytest.raises(Exception, match="action"):
            await server.mcp.call_tool(
                "reply_to_comment",
                {"file_id": "f1", "comment_id": "c1", "action": "delete"},
                _server_ctx(drive),
            )
        drive.replies.assert_not_called()


_TC_D315_ANCHOR = (
    '{"r": "head", "a": [{"rect": {"x": 10, "y": 20, "w": 30, "h": 40, "mw": 100, "mh": 100}}]}'
)

# Every text parameter of the comment tools, whose registered annotation must be
# exactly `str` so mcp doesn't pre-parse it as JSON.
_TEXT_PARAMS = {
    "list_file_comments": ("page_token",),
    "add_file_comment": ("content", "quoted_text", "anchor"),
    "reply_to_comment": ("content",),
    "resolve_doc_comment": ("reply_content",),
}

# The optional ones among them (OptionalText): null means not given.
_OPTIONAL_TEXT_PARAMS = [
    (tool, param)
    for tool, params in _TEXT_PARAMS.items()
    for param in params
    if (tool, param) != ("add_file_comment", "content")
]


class TestJsonLookingTextReachesDriveVerbatim:
    """mcp's pre_parse_json runs json.loads on a string argument unless its
    annotation is exactly `str` (PR #1563 round 2: `anchor: str | None` rejected
    every drive#commentRegion it documents). Called through the server's own
    registry, so the pre-parse step runs as it does for a client."""

    @pytest.mark.parametrize(
        ("tool_name", "param"),
        [(tool, param) for tool, params in _TEXT_PARAMS.items() for param in params],
    )
    def test_registered_annotation_is_exactly_str(self, tool_name, param):
        # renamed_params republishes the signature, so check what mcp registered.
        tool = server.mcp._tool_manager.get_tool(tool_name)
        assert tool.fn_metadata.arg_model.model_fields[param].annotation is str

    async def test_anchor_from_tc_d315(self):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.return_value = {
            "id": "c1",
            "anchor": _TC_D315_ANCHOR,
        }
        result = await server.mcp.call_tool(
            "add_file_comment",
            {"file_id": "f1", "content": "QA TC-D315 anchored", "anchor": _TC_D315_ANCHOR},
            _server_ctx(drive),
        )
        body = drive.comments.return_value.create.call_args.kwargs["body"]
        assert body["anchor"] == _TC_D315_ANCHOR
        assert result.structured_content["anchor"] == _TC_D315_ANCHOR

    async def test_quoted_text_that_parses_as_json(self):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.return_value = {"id": "c1"}
        await server.mcp.call_tool(
            "add_file_comment",
            {"file_id": "f1", "content": "[1, 2]", "quoted_text": '{"k": null}'},
            _server_ctx(drive),
        )
        body = drive.comments.return_value.create.call_args.kwargs["body"]
        assert body == {"content": "[1, 2]", "quotedFileContent": {"value": '{"k": null}'}}

    @pytest.mark.parametrize("content", ["null", "[1, 2]", '{"a": 1}'])
    async def test_reply_content_that_parses_as_json(self, content):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.return_value = {"id": "r1"}
        result = await server.mcp.call_tool(
            "reply_to_comment",
            {"file_id": "f1", "comment_id": "c1", "content": content},
            _server_ctx(drive),
        )
        assert "error" not in result.structured_content
        assert drive.replies.return_value.create.call_args.kwargs["body"] == {"content": content}

    async def test_resolve_doc_comment_reply_content_that_parses_as_json(self):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.return_value = {"id": "r1"}
        await server.mcp.call_tool(
            "resolve_doc_comment",
            {"doc_id": "d1", "comment_id": "c1", "reply_content": "[1, 2]"},
            _server_ctx(drive),
        )
        body = drive.replies.return_value.create.call_args.kwargs["body"]
        assert body == {"action": "resolve", "content": "[1, 2]"}

    async def test_no_page_token_sends_none(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        await server.mcp.call_tool("list_file_comments", {"file_id": "f1"}, _server_ctx(drive))
        assert drive.comments.return_value.list.call_args.kwargs["pageToken"] is None


class TestExplicitNullStillMeansNotGiven:
    """A bare `str` refused an explicit null that `str | None` accepted (PR #1563
    round 3): a pager sending page_token=null on its first call, or an old client of
    the deprecated names. OptionalText reads null as "", through the server's own
    argument parsing."""

    @pytest.mark.parametrize(("tool_name", "param"), _OPTIONAL_TEXT_PARAMS)
    def test_null_validates_as_empty(self, tool_name, param):
        tool = server.mcp._tool_manager.get_tool(tool_name)
        fields = tool.fn_metadata.arg_model.model_fields
        args = {name: "x" for name, field in fields.items() if field.is_required()}
        args[param] = None
        parsed = tool.fn_metadata.pre_parse_json(args)
        assert getattr(tool.fn_metadata.arg_model.model_validate(parsed), param) == ""

    async def test_null_page_token_through_the_old_name(self):
        drive = MagicMock()
        drive.comments.return_value.list.return_value.execute.return_value = {"comments": []}
        result = await server.mcp.call_tool(
            "list_doc_comments", {"doc_id": "d1", "page_token": None}, _server_ctx(drive)
        )
        assert result.structured_content["file_id"] == "d1"
        assert drive.comments.return_value.list.call_args.kwargs["pageToken"] is None

    async def test_null_quoted_text_and_anchor(self):
        drive = MagicMock()
        drive.comments.return_value.create.return_value.execute.return_value = {"id": "c1"}
        await server.mcp.call_tool(
            "add_file_comment",
            {"file_id": "f1", "content": "hi", "quoted_text": None, "anchor": None},
            _server_ctx(drive),
        )
        assert drive.comments.return_value.create.call_args.kwargs["body"] == {"content": "hi"}

    async def test_null_content_with_an_action(self):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.return_value = {"id": "r1"}
        await server.mcp.call_tool(
            "reply_to_comment",
            {"file_id": "f1", "comment_id": "c1", "content": None, "action": "resolve"},
            _server_ctx(drive),
        )
        assert drive.replies.return_value.create.call_args.kwargs["body"] == {"action": "resolve"}

    async def test_null_content_alone_is_the_neither_given_error(self):
        drive = MagicMock()
        result = await server.mcp.call_tool(
            "reply_to_comment",
            {"file_id": "f1", "comment_id": "c1", "content": None},
            _server_ctx(drive),
        )
        assert "error" in result.structured_content
        drive.replies.assert_not_called()

    async def test_null_reply_content_on_resolve_doc_comment(self):
        drive = MagicMock()
        drive.replies.return_value.create.return_value.execute.return_value = {"id": "r1"}
        await server.mcp.call_tool(
            "resolve_doc_comment",
            {"doc_id": "d1", "comment_id": "c1", "reply_content": None},
            _server_ctx(drive),
        )
        assert drive.replies.return_value.create.call_args.kwargs["body"] == {"action": "resolve"}

    @pytest.mark.parametrize(("tool_name", "param"), _OPTIONAL_TEXT_PARAMS)
    def test_schema_is_an_optional_string(self, tool_name, param):
        # The published schema stays a string with a "" default.
        tool = server.mcp._tool_manager.get_tool(tool_name)
        prop = tool.parameters["properties"][param]
        assert prop["type"] == "string" and prop["default"] == ""

    def test_required_content_still_refuses_null(self):
        tool = server.mcp._tool_manager.get_tool("add_file_comment")
        parsed = tool.fn_metadata.pre_parse_json({"file_id": "f1", "content": None})
        with pytest.raises(ValidationError):
            tool.fn_metadata.arg_model.model_validate(parsed)
