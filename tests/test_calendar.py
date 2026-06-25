"""Tests for tools/calendar.py (list_calendars, create_event, list_events, find_free_slots, etc.)."""

from unittest.mock import MagicMock

from mcp_gee_sweet.tools import calendar as calendar_module


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

    def test_returns_cached_result_without_calling_api(self):
        """When the cache holds data, calendarList().list() must not be called."""
        cal_svc = MagicMock()
        cache = MagicMock()
        cached_data = [{"id": "primary", "summary": "My Calendar"}]
        cache.get_list.return_value = cached_data
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = _cal_tools["list_calendars"](ctx=ctx)

        assert result is cached_data
        cal_svc.calendarList.return_value.list.assert_not_called()

    def test_cache_miss_calls_api_maps_fields_and_stores_in_cache(self):
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

        result = _cal_tools["list_calendars"](ctx=ctx)

        assert len(result) == 1
        assert result[0]["id"] == "cal-1"
        assert result[0]["time_zone"] == "America/Los_Angeles"
        assert result[0]["access_role"] == "owner"
        cache.store_list.assert_called_once_with(result)


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

    def test_ten_char_start_produces_date_key_not_datetime(self):
        """A 'YYYY-MM-DD' start string must result in body['start']['date'], not 'dateTime'."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["create_event"](
            calendar_id="primary",
            summary="Holiday",
            start="2026-07-04",
            end="2026-07-05",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert "date" in body["start"]
        assert "dateTime" not in body["start"]

    def test_full_rfc3339_start_produces_datetime_key(self):
        """A full datetime string must result in body['start']['dateTime']."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["create_event"](
            calendar_id="primary",
            summary="Meeting",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert "dateTime" in body["start"]
        assert "date" not in body["start"]

    def test_marks_calendar_cache_dirty_after_successful_insert(self):
        """calendar_cache.mark_dirty must be called with the calendar_id on success."""
        cal_svc = self._cal_svc()
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        _cal_tools["create_event"](
            calendar_id="cal-1",
            summary="Meeting",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        cache.mark_dirty.assert_called_once_with("cal-1")

    def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """When events().insert() raises, result must be {"error": ...} and cache stays clean."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.insert.return_value.execute.side_effect = Exception(
            "quotaExceeded"
        )
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = _cal_tools["create_event"](
            calendar_id="primary",
            summary="Meeting",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        assert "error" in result
        cache.mark_dirty.assert_not_called()

    def test_recurrence_is_passed_in_body_when_provided(self):
        """RRULE strings must appear in body['recurrence'] when recurrence param is given."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["create_event"](
            calendar_id="primary",
            summary="Weekly Standup",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T10:30:00Z",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]

    def test_recurrence_absent_from_body_when_not_provided(self):
        """When recurrence is omitted, body must not include a recurrence key."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["create_event"](
            calendar_id="primary",
            summary="One-Off",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T11:00:00Z",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.insert.call_args.kwargs["body"]
        assert "recurrence" not in body

    def test_recurrence_included_in_response(self):
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

        result = _cal_tools["create_event"](
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

    def test_max_results_above_2500_is_clamped_to_2500(self):
        """Passing max_results=9999 must result in maxResults=2500 in the API call."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        _cal_tools["list_events"](calendar_id="primary", max_results=9999, ctx=ctx)

        list_kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert list_kwargs["maxResults"] == 2500

    def test_max_results_zero_is_raised_to_1(self):
        """Passing max_results=0 must result in maxResults=1, not 0."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        _cal_tools["list_events"](calendar_id="primary", max_results=0, ctx=ctx)

        list_kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert list_kwargs["maxResults"] == 1

    def test_all_day_event_returns_date_string_not_datetime(self):
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

        result = _cal_tools["list_events"](calendar_id="primary", ctx=ctx)

        assert result[0]["start"] == "2026-07-04"
        assert result[0]["end"] == "2026-07-05"

    def test_expand_recurring_false_sets_singleevents_false_and_omits_orderby(self):
        """expand_recurring=False must pass singleEvents=False and omit orderBy."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        _cal_tools["list_events"](calendar_id="primary", expand_recurring=False, ctx=ctx)

        kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert kwargs["singleEvents"] is False
        assert "orderBy" not in kwargs

    def test_expand_recurring_true_sets_singleevents_true_and_orderby_starttime(self):
        """Default expand_recurring=True must pass singleEvents=True and orderBy='startTime'."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.list.return_value.execute.return_value = {"items": []}
        ctx = _make_ctx(calendar_service=cal_svc)

        _cal_tools["list_events"](calendar_id="primary", ctx=ctx)

        kwargs = cal_svc.events.return_value.list.call_args.kwargs
        assert kwargs["singleEvents"] is True
        assert kwargs["orderBy"] == "startTime"

    def test_recurrence_included_in_list_events_response(self):
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

        result = _cal_tools["list_events"](calendar_id="primary", expand_recurring=False, ctx=ctx)

        assert result[0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]


class TestFindFreeSlots:
    """find_free_slots computes the complement of merged busy intervals."""

    def _cal_svc(self, cal_id, busy_periods):
        mock = MagicMock()
        mock.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {cal_id: {"busy": [{"start": s, "end": e} for s, e in busy_periods]}}
        }
        return mock

    def test_two_non_overlapping_busy_periods_produce_three_free_slots(self):
        """busy=[10-11, 14-15] in a 9-18 window → free=[9-10, 11-14, 15-18]."""
        cal_svc = self._cal_svc(
            "primary",
            [
                ("2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z"),
                ("2026-06-15T14:00:00Z", "2026-06-15T15:00:00Z"),
            ],
        )
        ctx = _make_ctx(calendar_service=cal_svc)

        result = _cal_tools["find_free_slots"](
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

    def test_overlapping_busy_periods_are_merged_before_free_slot_calculation(self):
        """busy=[10-12, 11-13] must be merged to [10-13] → free=[9-10, 13-18]."""
        cal_svc = self._cal_svc(
            "primary",
            [
                ("2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z"),
                ("2026-06-15T11:00:00Z", "2026-06-15T13:00:00Z"),
            ],
        )
        ctx = _make_ctx(calendar_service=cal_svc)

        result = _cal_tools["find_free_slots"](
            calendar_ids=["primary"],
            time_min="2026-06-15T09:00:00Z",
            time_max="2026-06-15T18:00:00Z",
            ctx=ctx,
        )

        slots = result["free_slots"]
        assert len(slots) == 2
        assert slots[0]["end"] == "2026-06-15T10:00:00Z"
        assert slots[1]["start"] == "2026-06-15T13:00:00Z"

    def test_no_busy_periods_means_full_window_is_free(self):
        """With an empty busy list, the entire window is returned as a single free slot."""
        cal_svc = self._cal_svc("primary", [])
        ctx = _make_ctx(calendar_service=cal_svc)

        result = _cal_tools["find_free_slots"](
            calendar_ids=["primary"],
            time_min="2026-06-15T09:00:00Z",
            time_max="2026-06-15T18:00:00Z",
            ctx=ctx,
        )

        assert result["free_slots"] == [
            {"start": "2026-06-15T09:00:00Z", "end": "2026-06-15T18:00:00Z"}
        ]

    def test_api_error_returns_error_dict(self):
        """An exception from freebusy().query() must return {"error": ...} without raising."""
        cal_svc = MagicMock()
        cal_svc.freebusy.return_value.query.return_value.execute.side_effect = Exception(
            "access denied"
        )
        ctx = _make_ctx(calendar_service=cal_svc)

        result = _cal_tools["find_free_slots"](
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

    def test_only_summary_in_body_when_only_summary_provided(self):
        """If only summary is given, the patch body must not include start, end, or attendees."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["update_event"](
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

    def test_marks_cache_dirty_with_correct_calendar_id(self):
        """After a successful patch, calendar_cache.mark_dirty is called with the calendar_id."""
        cal_svc = self._cal_svc()
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        _cal_tools["update_event"](
            calendar_id="cal-2",
            event_id="evt-1",
            summary="New Title",
            ctx=ctx,
        )
        cache.mark_dirty.assert_called_once_with("cal-2")

    def test_recurrence_in_body_when_provided(self):
        """When recurrence is provided, body must include it for the API call."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            recurrence=["RRULE:FREQ=DAILY;COUNT=5"],
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=DAILY;COUNT=5"]

    def test_empty_recurrence_list_removes_recurrence(self):
        """Passing recurrence=[] must send an empty list to clear the recurring rule."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            recurrence=[],
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert body["recurrence"] == []

    def test_recurrence_absent_from_body_when_not_provided(self):
        """When recurrence is omitted, body must not include a recurrence key."""
        cal_svc = self._cal_svc()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=MagicMock())

        _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            summary="Title only",
            ctx=ctx,
        )
        body = cal_svc.events.return_value.patch.call_args.kwargs["body"]
        assert "recurrence" not in body

    def test_recurrence_included_in_response(self):
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

        result = _cal_tools["update_event"](
            calendar_id="primary",
            event_id="evt-1",
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO"],
            ctx=ctx,
        )
        assert result["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]


class TestDeleteEvent:
    """delete_event returns a structured confirmation and invalidates the cache."""

    def test_success_returns_confirmation_dict_and_marks_cache_dirty(self):
        """Result must be {calendar_id, event_id, action='deleted'} and cache is dirtied."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.delete.return_value.execute.return_value = None
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = _cal_tools["delete_event"](calendar_id="cal-1", event_id="evt-1", ctx=ctx)

        assert result == {"calendar_id": "cal-1", "event_id": "evt-1", "action": "deleted"}
        cache.mark_dirty.assert_called_once_with("cal-1")

    def test_api_error_returns_error_dict_without_marking_cache_dirty(self):
        """If delete raises, result has 'error' key and the cache must not be dirtied."""
        cal_svc = MagicMock()
        cal_svc.events.return_value.delete.return_value.execute.side_effect = Exception("Not Found")
        cache = MagicMock()
        ctx = _make_ctx(calendar_service=cal_svc, calendar_cache=cache)

        result = _cal_tools["delete_event"](calendar_id="cal-1", event_id="evt-missing", ctx=ctx)

        assert "error" in result
        cache.mark_dirty.assert_not_called()
