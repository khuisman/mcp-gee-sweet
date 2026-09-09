"""Tests for tools/drive/activity.py (list_file_activity)."""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import response_limits
from mcp_gee_sweet.tools.drive import activity as activity_module


def _make_tool_registry():
    captured = {}

    def tool(annotations=None):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


def _make_ctx(activity_svc):
    ctx = MagicMock()
    ctx.request_context.lifespan_context.activity_service = activity_svc
    return ctx


def _activity_svc(activities=None, next_page_token=None):
    svc = MagicMock()
    response = {"activities": activities or []}
    if next_page_token:
        response["nextPageToken"] = next_page_token
    svc.activity.return_value.query.return_value.execute.return_value = response
    return svc


_tool, _tools = _make_tool_registry()
activity_module.register(_tool)
list_file_activity = _tools["list_file_activity"]


class TestListFileActivity:
    async def test_returns_file_id(self):
        ctx = _make_ctx(_activity_svc())
        result = await list_file_activity(file_id="abc123", ctx=ctx)
        assert result["file_id"] == "abc123"

    async def test_empty_response(self):
        ctx = _make_ctx(_activity_svc())
        result = await list_file_activity(file_id="abc123", ctx=ctx)
        assert result["activities"] == []
        assert "next_page_token" not in result

    async def test_request_body_uses_items_prefix(self):
        svc = _activity_svc()
        ctx = _make_ctx(svc)
        await list_file_activity(file_id="abc123", ctx=ctx)
        body = svc.activity.return_value.query.call_args.kwargs["body"]
        assert body["itemName"] == "items/abc123"

    async def test_page_size_clamped_to_100(self):
        svc = _activity_svc()
        ctx = _make_ctx(svc)
        await list_file_activity(file_id="f", page_size=999, ctx=ctx)
        body = svc.activity.return_value.query.call_args.kwargs["body"]
        assert body["pageSize"] == 100

    async def test_oversized_result_raises(self, monkeypatch):
        # A file with many collaborators can produce a large actors list on a single
        # activity entry — page_size alone doesn't bound an individual entry's size.
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        activities = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "primaryActionDetail": {"edit": {}},
                "actors": [
                    {"user": {"knownUser": {"personName": f"people/{i}"}}} for i in range(50)
                ],
            }
        ]
        svc = _activity_svc(activities=activities)
        ctx = _make_ctx(svc)
        with pytest.raises(ValueError, match="safety cap"):
            await list_file_activity(file_id="abc123", ctx=ctx)

    async def test_error_points_to_page_size_not_local_path(self, monkeypatch):
        # list_file_activity has no local_path param — page_size/pagination is the
        # correct remedy, so the error must say so and must not reference local_path.
        monkeypatch.setattr(response_limits, "MAX_TOOL_RESPONSE_CHARS", 10)
        svc = _activity_svc(
            activities=[
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "primaryActionDetail": {"edit": {}},
                    "actors": [],
                }
            ]
        )
        ctx = _make_ctx(svc)
        with pytest.raises(ValueError) as exc_info:
            await list_file_activity(file_id="abc123", ctx=ctx)
        msg = str(exc_info.value)
        assert "page_size" in msg
        assert "local_path" not in msg

    async def test_page_size_clamped_to_1(self):
        svc = _activity_svc()
        ctx = _make_ctx(svc)
        await list_file_activity(file_id="f", page_size=0, ctx=ctx)
        body = svc.activity.return_value.query.call_args.kwargs["body"]
        assert body["pageSize"] == 1

    async def test_page_token_passed_when_provided(self):
        svc = _activity_svc()
        ctx = _make_ctx(svc)
        await list_file_activity(file_id="f", page_token="tok123", ctx=ctx)
        body = svc.activity.return_value.query.call_args.kwargs["body"]
        assert body["pageToken"] == "tok123"

    async def test_page_token_absent_when_none(self):
        svc = _activity_svc()
        ctx = _make_ctx(svc)
        await list_file_activity(file_id="f", ctx=ctx)
        body = svc.activity.return_value.query.call_args.kwargs["body"]
        assert "pageToken" not in body

    async def test_next_page_token_in_result(self):
        ctx = _make_ctx(_activity_svc(next_page_token="npt_abc"))
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert result["next_page_token"] == "npt_abc"

    async def test_edit_action_parsed(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "primaryActionDetail": {"edit": {}},
                        "actors": [],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert result["activities"][0]["action"] == "edit"

    async def test_permission_change_action_parsed(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "primaryActionDetail": {"permissionChange": {}},
                        "actors": [],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert result["activities"][0]["action"] == "permission_change"

    async def test_unknown_action_falls_back(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "primaryActionDetail": {"someFutureAction": {}},
                        "actors": [],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert result["activities"][0]["action"] == "unknown"

    async def test_known_user_actor_parsed(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "primaryActionDetail": {"edit": {}},
                        "actors": [
                            {
                                "user": {
                                    "knownUser": {
                                        "personName": "people/12345",
                                        "isCurrentUser": True,
                                    }
                                }
                            }
                        ],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        actor = result["activities"][0]["actors"][0]
        assert actor["type"] == "user"
        assert actor["person_name"] == "people/12345"
        assert actor["is_current_user"] is True

    async def test_anonymous_actor_parsed(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "primaryActionDetail": {"edit": {}},
                        "actors": [{"anonymous": {}}],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert result["activities"][0]["actors"][0]["type"] == "anonymous"

    async def test_system_actor_parsed(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "primaryActionDetail": {"systemEvent": {}},
                        "actors": [{"system": {"type": "USER_DELETION"}}],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        actor = result["activities"][0]["actors"][0]
        assert actor["type"] == "system"
        assert actor["event"] == "USER_DELETION"

    async def test_http_error_returns_error_dict(self):
        svc = MagicMock()
        resp = MagicMock()
        resp.status = 403
        svc.activity.return_value.query.return_value.execute.side_effect = HttpError(
            resp=resp, content=b"Forbidden"
        )
        ctx = _make_ctx(svc)
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert "error" in result

    async def test_timestamp_from_timerange_when_no_timestamp(self):
        ctx = _make_ctx(
            _activity_svc(
                activities=[
                    {
                        "timeRange": {"endTime": "2024-06-01T12:00:00Z"},
                        "primaryActionDetail": {"edit": {}},
                        "actors": [],
                    }
                ]
            )
        )
        result = await list_file_activity(file_id="f", ctx=ctx)
        assert result["activities"][0]["timestamp"] == "2024-06-01T12:00:00Z"
