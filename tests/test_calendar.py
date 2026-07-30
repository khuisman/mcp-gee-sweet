"""Tests for tools/calendar.py (list_calendars, create_event, list_events, find_free_slots, etc.)."""

from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools import calendar as calendar_module


def _cannot_unsubscribe_owned_error():
    resp = MagicMock()
    resp.status = 403
    return HttpError(
        resp=resp,
        content=b'{"error": {"errors": [{"reason": "cannotUnsubscribeFromOwnedCalendar"}]}}',
    )


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


_cal_tool, _cal_tools = _make_tool_registry()
calendar_module.register(_cal_tool)


class TestListCalendars:
    """list_calendars uses calendar_cache to avoid redundant API calls."""

    async def test_returns_cached_result_without_calling_api(self):
        """When the cache holds data, calendarList().list() must not be called."""
        cal_svc = MagicMock()
        cache = MagicMock()
        cached_data = [{"id": "primary", "summary": "My Calendar"}]
        cache.get_list.return_value = cached_data
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["list_calendars"](ctx=ctx)

        assert result is cached_data
        cal_svc.calendarList.return_value.list.assert_not_called()

    async def test_cache_miss_calls_api_maps_fields_and_stores_in_cache(self):
        """On a cache miss the API is called, results are field-mapped, and stored via cache.store_list."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "cal-1",
                    "summary": "Work",
                    "timeZone": "America/Los_Angeles",
                    "accessRole": "owner",
                    "primary": True,
                }
            ]
        }
        cache = MagicMock()
        cache.get_list.return_value = None  # explicit cache miss
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["list_calendars"](ctx=ctx)

        assert len(result) == 1
        assert result[0]["id"] == "cal-1"
        assert result[0]["time_zone"] == "America/Los_Angeles"
        assert result[0]["access_role"] == "owner"
        cache.store_list.assert_called_once_with(result)


class TestCreateCalendar:
    """create_calendar inserts a new secondary calendar and invalidates the list cache."""

    async def test_builds_body_from_provided_fields_and_maps_response(self):
        """summary/description/timezone go in the insert body; response is field-mapped."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.insert.return_value.execute.return_value = {
            "id": "new-cal-1",
            "summary": "Team Events",
            "description": "Shared team calendar",
            "timeZone": "America/Los_Angeles",
        }
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["create_calendar"](
            summary="Team Events",
            description="Shared team calendar",
            timezone="America/Los_Angeles",
            ctx=ctx,
        )

        body = cal_svc.calendars.return_value.insert.call_args.kwargs["body"]
        assert body == {
            "summary": "Team Events",
            "description": "Shared team calendar",
            "timeZone": "America/Los_Angeles",
        }
        assert result["id"] == "new-cal-1"
        assert result["time_zone"] == "America/Los_Angeles"

    async def test_omits_optional_fields_from_body_when_not_provided(self):
        """When description/timezone are omitted, the insert body must only have summary."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.insert.return_value.execute.return_value = {
            "id": "new-cal-2",
            "summary": "Minimal",
        }
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["create_calendar"](summary="Minimal", ctx=ctx)

        body = cal_svc.calendars.return_value.insert.call_args.kwargs["body"]
        assert body == {"summary": "Minimal"}

    async def test_marks_cache_dirty_with_new_calendar_id(self):
        """calendar_cache.mark_dirty must be called with the newly created calendar's id."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.insert.return_value.execute.return_value = {
            "id": "new-cal-3",
            "summary": "Test",
        }
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        await _cal_tools["create_calendar"](summary="Test", ctx=ctx)

        cache.mark_dirty.assert_called_once_with("new-cal-3")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """When calendars().insert() raises, result must be {"error": ...} and cache stays clean."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.insert.return_value.execute.side_effect = Exception(
            "quotaExceeded"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["create_calendar"](summary="Test", ctx=ctx)

        assert "error" in result
        cache.mark_dirty.assert_not_called()


class TestUpdateCalendar:
    """update_calendar uses patch semantics for core fields and calendarList for color."""

    async def test_only_summary_in_body_when_only_summary_provided(self):
        """If only summary is given, the patch body must not include description or timeZone."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.patch.return_value.execute.return_value = {
            "id": "cal-1",
            "summary": "Renamed",
        }
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["update_calendar"](calendar_id="cal-1", summary="Renamed", ctx=ctx)

        body = cal_svc.calendars.return_value.patch.call_args.kwargs["body"]
        assert body == {"summary": "Renamed"}

    async def test_color_id_patches_calendar_list_not_calendars_resource(self):
        """color_id must go through calendarList().patch(), not calendars().patch()."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.get.return_value.execute.return_value = {
            "id": "cal-1",
            "summary": "Existing",
        }
        cal_svc.calendarList.return_value.patch.return_value.execute.return_value = {"colorId": "5"}
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        result = await _cal_tools["update_calendar"](calendar_id="cal-1", color_id="5", ctx=ctx)

        cal_svc.calendars.return_value.patch.assert_not_called()
        cal_svc.calendarList.return_value.patch.assert_called_once_with(
            calendarId="cal-1", body={"colorId": "5"}
        )
        assert result["color_id"] == "5"

    async def test_no_fields_provided_falls_back_to_get_without_patching(self):
        """With no fields set, the tool must fetch via calendars().get(), not patch()."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.get.return_value.execute.return_value = {
            "id": "cal-1",
            "summary": "Unchanged",
        }
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        result = await _cal_tools["update_calendar"](calendar_id="cal-1", ctx=ctx)

        cal_svc.calendars.return_value.patch.assert_not_called()
        cal_svc.calendars.return_value.get.assert_called_once_with(calendarId="cal-1")
        assert result["summary"] == "Unchanged"
        assert result["color_id"] is None

    async def test_marks_cache_dirty_with_correct_calendar_id(self):
        """After a successful update, calendar_cache.mark_dirty is called with the calendar_id."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.patch.return_value.execute.return_value = {
            "id": "cal-2",
            "summary": "Renamed",
        }
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        await _cal_tools["update_calendar"](calendar_id="cal-2", summary="Renamed", ctx=ctx)

        cache.mark_dirty.assert_called_once_with("cal-2")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """When calendars().patch() raises, result must be {"error": ...} and cache stays clean."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.patch.return_value.execute.side_effect = Exception(
            "notFound"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["update_calendar"](
            calendar_id="cal-missing", summary="Renamed", ctx=ctx
        )

        assert "error" in result
        cache.mark_dirty.assert_not_called()


class TestDeleteCalendar:
    """delete_calendar returns a structured confirmation and invalidates the cache."""

    async def test_success_returns_confirmation_dict_and_marks_cache_dirty(self):
        """Result must be {calendar_id, action='deleted'} and cache is dirtied."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.delete.return_value.execute.return_value = None
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["delete_calendar"](calendar_id="cal-1", ctx=ctx)

        assert result == {"calendar_id": "cal-1", "action": "deleted"}
        cache.mark_dirty.assert_called_once_with("cal-1")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """If delete raises, result has 'error' key and the cache must not be dirtied."""
        cal_svc = MagicMock()
        cal_svc.calendars.return_value.delete.return_value.execute.side_effect = Exception(
            "Not Found"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["delete_calendar"](calendar_id="cal-missing", ctx=ctx)

        assert "error" in result
        cache.mark_dirty.assert_not_called()


class TestAddCalendarToList:
    """add_calendar_to_list subscribes via calendarList().insert() and invalidates the cache."""

    async def test_builds_body_from_calendar_id_and_maps_response(self):
        """calendar_id goes in body['id']; response is field-mapped including color_id."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.insert.return_value.execute.return_value = {
            "id": "shared-cal@example.com",
            "summary": "Shared Calendar",
            "timeZone": "America/Los_Angeles",
            "accessRole": "reader",
            "primary": False,
            "colorId": "5",
        }
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["add_calendar_to_list"](
            calendar_id="shared-cal@example.com", color_id="5", ctx=ctx
        )

        body = cal_svc.calendarList.return_value.insert.call_args.kwargs["body"]
        assert body == {"id": "shared-cal@example.com", "colorId": "5"}
        assert result["id"] == "shared-cal@example.com"
        assert result["access_role"] == "reader"
        assert result["color_id"] == "5"

    async def test_omits_color_id_from_body_when_not_provided(self):
        """When color_id is omitted, the insert body must only have 'id'."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.insert.return_value.execute.return_value = {
            "id": "shared-cal@example.com",
            "summary": "Shared Calendar",
        }
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["add_calendar_to_list"](calendar_id="shared-cal@example.com", ctx=ctx)

        body = cal_svc.calendarList.return_value.insert.call_args.kwargs["body"]
        assert body == {"id": "shared-cal@example.com"}

    async def test_marks_cache_dirty_with_calendar_id(self):
        """calendar_cache.mark_dirty must be called with the subscribed calendar's id."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.insert.return_value.execute.return_value = {
            "id": "shared-cal@example.com",
            "summary": "Shared Calendar",
        }
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        await _cal_tools["add_calendar_to_list"](calendar_id="shared-cal@example.com", ctx=ctx)

        cache.mark_dirty.assert_called_once_with("shared-cal@example.com")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """When calendarList().insert() raises, result must be {"error": ...} and cache stays clean."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.insert.return_value.execute.side_effect = Exception(
            "notFound"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["add_calendar_to_list"](
            calendar_id="bad-cal@example.com", ctx=ctx
        )

        assert "error" in result
        cache.mark_dirty.assert_not_called()


class TestRemoveCalendarFromList:
    """remove_calendar_from_list returns a structured confirmation and invalidates the cache."""

    async def test_success_returns_confirmation_dict_and_marks_cache_dirty(self):
        """Result must be {calendar_id, action='removed_from_list'} and cache is dirtied."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.delete.return_value.execute.return_value = None
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["remove_calendar_from_list"](calendar_id="cal-1", ctx=ctx)

        assert result == {"calendar_id": "cal-1", "action": "removed_from_list"}
        cache.mark_dirty.assert_called_once_with("cal-1")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """If delete raises, result has 'error' key and the cache must not be dirtied."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.delete.return_value.execute.side_effect = Exception(
            "Not Found"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["remove_calendar_from_list"](calendar_id="cal-missing", ctx=ctx)

        assert "error" in result
        cache.mark_dirty.assert_not_called()

    async def test_cannot_unsubscribe_from_owned_calendar_returns_actionable_message(self):
        """Google's cannotUnsubscribeFromOwnedCalendar 403 must map to a message pointing at delete_calendar."""
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.delete.return_value.execute.side_effect = (
            _cannot_unsubscribe_owned_error()
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["remove_calendar_from_list"](calendar_id="owned-cal", ctx=ctx)

        assert "delete_calendar" in result["error"]
        cache.mark_dirty.assert_not_called()

    async def test_other_403_error_falls_back_to_raw_message(self):
        """A 403 for a different reason must not be swallowed by the owned-calendar special case."""
        resp = MagicMock()
        resp.status = 403
        cal_svc = MagicMock()
        cal_svc.calendarList.return_value.delete.return_value.execute.side_effect = HttpError(
            resp=resp, content=b'{"error": {"errors": [{"reason": "forbidden"}]}}'
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["remove_calendar_from_list"](calendar_id="cal-1", ctx=ctx)

        assert "delete_calendar" not in result["error"]
        cache.mark_dirty.assert_not_called()


class TestListCalendarAcl:
    """list_calendar_acl uses acl().list() and field-maps the scope sub-dict."""

    async def test_maps_rules_including_scope_type_and_value(self):
        """Each rule's scope.{type,value} must be flattened into scope_type/scope_value."""
        cal_svc = MagicMock()
        cal_svc.acl.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "user:someone@example.com",
                    "role": "writer",
                    "scope": {"type": "user", "value": "someone@example.com"},
                },
                {
                    "id": "default",
                    "role": "freeBusyReader",
                    "scope": {"type": "default"},
                },
            ]
        }
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["list_calendar_acl"](calendar_id="cal-1", ctx=ctx)

        assert result[0] == {
            "id": "user:someone@example.com",
            "role": "writer",
            "scope_type": "user",
            "scope_value": "someone@example.com",
        }
        assert result[1] == {
            "id": "default",
            "role": "freeBusyReader",
            "scope_type": "default",
            "scope_value": None,
        }

    async def test_api_error_returns_error_list(self):
        """When acl().list() raises, result must be [{"error": ...}]."""
        cal_svc = MagicMock()
        cal_svc.acl.return_value.list.return_value.execute.side_effect = Exception("Not Found")
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["list_calendar_acl"](calendar_id="cal-missing", ctx=ctx)

        assert result == [{"error": "Not Found"}]


class TestAddCalendarAcl:
    """add_calendar_acl validates role/scope_type before calling acl().insert()."""

    async def test_invalid_role_returns_error_without_calling_api(self):
        cal_svc = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1", role="admin", scope_value="a@example.com", ctx=ctx
        )

        assert "error" in result
        cal_svc.acl.return_value.insert.assert_not_called()

    async def test_invalid_scope_type_returns_error_without_calling_api(self):
        cal_svc = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1", role="reader", scope_type="everyone", ctx=ctx
        )

        assert "error" in result
        cal_svc.acl.return_value.insert.assert_not_called()

    async def test_missing_scope_value_for_non_default_scope_returns_error(self):
        cal_svc = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1", role="reader", scope_type="user", scope_value=None, ctx=ctx
        )

        assert "error" in result
        cal_svc.acl.return_value.insert.assert_not_called()

    async def test_default_scope_type_omits_value_and_scope_value_not_required(self):
        """scope_type='default' must not require scope_value and body must omit 'value'."""
        cal_svc = MagicMock()
        cal_svc.acl.return_value.insert.return_value.execute.return_value = {
            "id": "default",
            "role": "freeBusyReader",
            "scope": {"type": "default"},
        }
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1", role="freeBusyReader", scope_type="default", ctx=ctx
        )

        body = cal_svc.acl.return_value.insert.call_args.kwargs["body"]
        assert body == {"role": "freeBusyReader", "scope": {"type": "default"}}
        assert result["scope_type"] == "default"
        assert result["scope_value"] is None

    async def test_builds_body_and_maps_response_for_user_scope(self):
        cal_svc = MagicMock()
        cal_svc.acl.return_value.insert.return_value.execute.return_value = {
            "id": "user:someone@example.com",
            "role": "writer",
            "scope": {"type": "user", "value": "someone@example.com"},
        }
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1",
            role="writer",
            scope_type="user",
            scope_value="someone@example.com",
            send_notifications=False,
            ctx=ctx,
        )

        call_kwargs = cal_svc.acl.return_value.insert.call_args.kwargs
        assert call_kwargs["calendarId"] == "cal-1"
        assert call_kwargs["body"] == {
            "role": "writer",
            "scope": {"type": "user", "value": "someone@example.com"},
        }
        assert call_kwargs["sendNotifications"] is False
        assert result == {
            "id": "user:someone@example.com",
            "role": "writer",
            "scope_type": "user",
            "scope_value": "someone@example.com",
        }

    async def test_marks_cache_dirty_with_calendar_id(self):
        """calendar_cache.mark_dirty must be called so a stale cached access_role isn't served."""
        cal_svc = MagicMock()
        cal_svc.acl.return_value.insert.return_value.execute.return_value = {
            "id": "user:someone@example.com",
            "role": "writer",
            "scope": {"type": "user", "value": "someone@example.com"},
        }
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1",
            role="writer",
            scope_type="user",
            scope_value="someone@example.com",
            ctx=ctx,
        )

        cache.mark_dirty.assert_called_once_with("cal-1")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        cal_svc = MagicMock()
        cal_svc.acl.return_value.insert.return_value.execute.side_effect = Exception(
            "Invalid sharee"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1", role="reader", scope_value="bad", ctx=ctx
        )

        assert "error" in result
        cache.mark_dirty.assert_not_called()

    async def test_validation_error_does_not_mark_cache_dirty(self):
        """A rejected role must not reach the API call, and must not dirty the cache either."""
        cal_svc = MagicMock()
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["add_calendar_acl"](
            calendar_id="cal-1", role="admin", scope_value="a@example.com", ctx=ctx
        )

        assert "error" in result
        cache.mark_dirty.assert_not_called()


class TestRemoveCalendarAcl:
    """remove_calendar_acl calls acl().delete() and returns a structured confirmation."""

    async def test_success_returns_confirmation_dict_and_marks_cache_dirty(self):
        cal_svc = MagicMock()
        cal_svc.acl.return_value.delete.return_value.execute.return_value = None
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["remove_calendar_acl"](
            calendar_id="cal-1", rule_id="user:someone@example.com", ctx=ctx
        )

        assert result == {
            "calendar_id": "cal-1",
            "rule_id": "user:someone@example.com",
            "action": "removed",
        }
        cal_svc.acl.return_value.delete.assert_called_once_with(
            calendarId="cal-1", ruleId="user:someone@example.com"
        )
        cache.mark_dirty.assert_called_once_with("cal-1")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        cal_svc = MagicMock()
        cal_svc.acl.return_value.delete.return_value.execute.side_effect = Exception("Not Found")
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["remove_calendar_acl"](
            calendar_id="cal-1", rule_id="rule-missing", ctx=ctx
        )

        assert "error" in result
        cache.mark_dirty.assert_not_called()


class TestCreateEvent:
    """create_event detects all-day events, passes attendees, and invalidates the cache."""

    def _cal_svc(self, event_id="evt-1"):
        mock = MagicMock()
        mock.events.return_value.insert.return_value.execute.return_value = {
            "id": event_id,
            "summary": "Test",
            "start": {"dateTime": "2026-06-15T10:00:00Z"},
            "end": {"dateTime": "2026-06-15T11:00:00Z"},
            "htmlLink": "https://calendar.google.com/event?eid=abc",
            "status": "confirmed",
        }
        return mock

    async def test_ten_char_start_produces_date_key_not_datetime(self):
        """A 'YYYY-MM-DD' start string must result in body['start']['date'], not 'dateTime'."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["create_event"](
            calendar_id="primary",
            summary="Holiday",
            start="2026-07-04",
            end="2026-07-05",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert "date" in body["start"]
        assert "dateTime" not in body["start"]

    async def test_full_rfc3339_start_produces_datetime_key(self):
        """A full datetime string must result in body['start']['dateTime']."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["create_event"](
            calendar_id="primary",
            summary="Meeting",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert "dateTime" in body["start"]
        assert "date" not in body["start"]

    async def test_marks_calendar_cache_dirty_after_successful_insert(self):
        """calendar_cache.mark_dirty must be called with the calendar_id on success."""
        cal_svc = self._cal_svc()
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        await _cal_tools["create_event"](
            calendar_id="cal-1",
            summary="Meeting",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        cache.mark_dirty.assert_called_once_with("cal-1")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """When events().insert() raises, result must be {"error": ...} and cache stays clean."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.insert.return_value.execute.side_effect = Exception(
            "quotaExceeded"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["create_event"](
            calendar_id="primary",
            summary="Meeting",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        assert "error" in result
        cache.mark_dirty.assert_not_called()

    async def test_recurrence_is_passed_in_body_when_provided(self):
        """RRULE strings must appear in body['recurrence'] when recurrence param is given."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["create_event"](
            calendar_id="primary",
            summary="Weekly Standup",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T10:30:00Z",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]

    async def test_recurrence_absent_from_body_when_not_provided(self):
        """When recurrence is omitted, body must not include a recurrence key."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["create_event"](
            calendar_id="primary",
            summary="One-Off",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert "recurrence" not in body

    async def test_recurrence_included_in_response(self):
        """When the API echoes recurrence, it must appear in the returned dict."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt-2",
            "summary": "Weekly",
            "start": {"dateTime": "2026-06-15T10:00:00Z"},
            "end": {"dateTime": "2026-06-15T10:30:00Z"},
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            "htmlLink": "https://example.com",
            "status": "confirmed",
        }
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        result = await _cal_tools["create_event"](
            calendar_id="primary",
            summary="Weekly",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T10:30:00Z",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            ctx=ctx,
        )
        assert result["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]


class TestListEvents:
    """list_events clamps max_results and maps start/end correctly for all-day events."""

    async def test_max_results_above_2500_is_clamped_to_2500(self):
        """Passing max_results=9999 must result in maxResults=2500 in the API call."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        await _cal_tools["list_events"](calendar_id="primary", max_results=9999, ctx=ctx)

        list_kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert list_kwargs["maxResults"] == 2500

    async def test_max_results_zero_is_raised_to_1(self):
        """Passing max_results=0 must result in maxResults=1, not 0."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        await _cal_tools["list_events"](calendar_id="primary", max_results=0, ctx=ctx)

        list_kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert list_kwargs["maxResults"] == 1

    async def test_all_day_event_returns_date_string_not_datetime(self):
        """Events with start.date (no .dateTime) must use the date field in the output."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "evt-1",
                    "summary": "Independence Day",
                    "start": {"date": "2026-07-04"},
                    "end": {"date": "2026-07-05"},
                }
            ]
        }
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["list_events"](calendar_id="primary", ctx=ctx)

        assert result[0]["start"] == "2026-07-04"
        assert result[0]["end"] == "2026-07-05"

    async def test_expand_recurring_false_sets_singleevents_false_and_omits_orderby(self):
        """expand_recurring=False must pass singleEvents=False and omit orderBy."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        await _cal_tools["list_events"](calendar_id="primary", expand_recurring=False, ctx=ctx)

        kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert kwargs["singleEvents"] is False
        assert "orderBy" not in kwargs

    async def test_expand_recurring_true_sets_singleevents_true_and_orderby_starttime(self):
        """Default expand_recurring=True must pass singleEvents=True and orderBy='startTime'."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        await _cal_tools["list_events"](calendar_id="primary", ctx=ctx)

        kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert kwargs["singleEvents"] is True
        assert kwargs["orderBy"] == "startTime"

    async def test_recurrence_included_in_list_events_response(self):
        """Events with a recurrence field must include it in the returned dict."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "evt-1",
                    "summary": "Weekly",
                    "start": {"dateTime": "2026-06-15T10:00:00Z"},
                    "end": {"dateTime": "2026-06-15T10:30:00Z"},
                    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
                }
            ]
        }
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["list_events"](
            calendar_id="primary", expand_recurring=False, ctx=ctx
        )

        assert result[0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]


class TestFindFreeSlots:
    """find_free_slots computes the complement of merged busy intervals."""

    def _cal_svc(self, cal_id, busy_periods):
        mock = MagicMock()
        mock.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {cal_id: {"busy": [{"start": s, "end": e} for s, e in busy_periods]}}
        }
        return mock

    async def test_two_non_overlapping_busy_periods_produce_three_free_slots(self):
        """busy=[10-11, 14-15] in a 9-18 window → free=[9-10, 11-14, 15-18]."""
        cal_svc = self._cal_svc(
            "primary",
            [
                ("2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z"),
                ("2026-06-15T14:00:00Z", "2026-06-15T15:00:00Z"),
            ],
        )
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["find_free_slots"](
            calendar_ids=["primary"],
            time_min="2026-06-15T09:00:00Z",
            time_max="2026-06-15T18:00:00Z",
            ctx=ctx,
        )

        slots = result["free_slots"]
        assert len(slots) == 3
        assert slots[0] == {"start": "2026-06-15T09:00:00Z", "end": "2026-06-15T10:00:00Z"}
        assert slots[1] == {"start": "2026-06-15T11:00:00Z", "end": "2026-06-15T14:00:00Z"}
        assert slots[2] == {"start": "2026-06-15T15:00:00Z", "end": "2026-06-15T18:00:00Z"}

    async def test_overlapping_busy_periods_are_merged_before_free_slot_calculation(self):
        """busy=[10-12, 11-13] must be merged to [10-13] → free=[9-10, 13-18]."""
        cal_svc = self._cal_svc(
            "primary",
            [
                ("2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z"),
                ("2026-06-15T11:00:00Z", "2026-06-15T13:00:00Z"),
            ],
        )
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["find_free_slots"](
            calendar_ids=["primary"],
            time_min="2026-06-15T09:00:00Z",
            time_max="2026-06-15T18:00:00Z",
            ctx=ctx,
        )

        slots = result["free_slots"]
        assert len(slots) == 2
        assert slots[0]["end"] == "2026-06-15T10:00:00Z"
        assert slots[1]["start"] == "2026-06-15T13:00:00Z"

    async def test_no_busy_periods_means_full_window_is_free(self):
        """With an empty busy list, the entire window is returned as a single free slot."""
        cal_svc = self._cal_svc("primary", [])
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["find_free_slots"](
            calendar_ids=["primary"],
            time_min="2026-06-15T09:00:00Z",
            time_max="2026-06-15T18:00:00Z",
            ctx=ctx,
        )

        assert result["free_slots"] == [
            {"start": "2026-06-15T09:00:00Z", "end": "2026-06-15T18:00:00Z"}
        ]

    async def test_api_error_returns_error_dict(self):
        """An exception from freebusy().query() must return {"error": ...} without raising."""
        cal_svc = MagicMock()
        cal_svc.freebusy.return_value.query.return_value.execute.side_effect = Exception(
            "access denied"
        )
        ctx = _make_ctx(calendar_service=cal_svc)

        result = await _cal_tools["find_free_slots"](
            calendar_ids=["primary"],
            time_min="2026-06-15T09:00:00Z",
            time_max="2026-06-15T18:00:00Z",
            ctx=ctx,
        )
        assert "error" in result


class TestUpdateEvent:
    """update_event uses patch semantics — only provided fields go in the API body."""

    def _cal_svc(self):
        mock = MagicMock()
        mock.events.return_value.patch.return_value.execute.return_value = {
            "id": "evt-1",
            "summary": "New Title",
            "start": {"dateTime": "2026-06-15T10:00:00Z"},
            "end": {"dateTime": "2026-06-15T11:00:00Z"},
            "htmlLink": "https://example.com",
            "status": "confirmed",
        }
        return mock

    async def test_only_summary_in_body_when_only_summary_provided(self):
        """If only summary is given, the patch body must not include start, end, or attendees."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            summary="New Title",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert "summary" in body
        assert "start" not in body
        assert "end" not in body
        assert "attendees" not in body

    async def test_marks_cache_dirty_with_correct_calendar_id(self):
        """After a successful patch, calendar_cache.mark_dirty is called with the calendar_id."""
        cal_svc = self._cal_svc()
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        await _cal_tools["update_event"](
            calendar_id="cal-2",
            event_id="evt-1",
            summary="New Title",
            ctx=ctx,
        )
        cache.mark_dirty.assert_called_once_with("cal-2")

    async def test_recurrence_in_body_when_provided(self):
        """When recurrence is provided, body must include it for the API call."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            recurrence=["RRULE:FREQ=DAILY;COUNT=5"],
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=DAILY;COUNT=5"]

    async def test_empty_recurrence_list_removes_recurrence(self):
        """Passing recurrence=[] must send an empty list to clear the recurring rule."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            recurrence=[],
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert body["recurrence"] == []

    async def test_recurrence_absent_from_body_when_not_provided(self):
        """When recurrence is omitted, body must not include a recurrence key."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        await _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            summary="Title only",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert "recurrence" not in body

    async def test_recurrence_included_in_response(self):
        """When the API echoes recurrence, it must appear in the returned dict."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.patch.return_value.execute.return_value = {
            "id": "evt-1",
            "summary": "Weekly",
            "start": {"dateTime": "2026-06-15T10:00:00Z"},
            "end": {"dateTime": "2026-06-15T10:30:00Z"},
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            "htmlLink": "https://example.com",
            "status": "confirmed",
        }
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        result = await _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            ctx=ctx,
        )
        assert result["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]


class TestDeleteEvent:
    """delete_event returns a structured confirmation and invalidates the cache."""

    async def test_success_returns_confirmation_dict_and_marks_cache_dirty(self):
        """Result must be {calendar_id, event_id, action='deleted'} and cache is dirtied."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.delete.return_value.execute.return_value = None
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["delete_event"](calendar_id="cal-1", event_id="evt-1", ctx=ctx)

        assert result == {"calendar_id": "cal-1", "event_id": "evt-1", "action": "deleted"}
        cache.mark_dirty.assert_called_once_with("cal-1")

    async def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """If delete raises, result has 'error' key and the cache must not be dirtied."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.delete.return_value.execute.side_effect = Exception("Not Found")
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = await _cal_tools["delete_event"](
            calendar_id="cal-1", event_id="evt-missing", ctx=ctx
        )

        assert "error" in result
        cache.mark_dirty.assert_not_called()
