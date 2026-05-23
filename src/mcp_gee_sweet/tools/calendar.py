import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Calendars", readOnlyHint=True))
    def list_calendars(
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List all calendars in the authenticated account's calendar list.

        Returns:
            List of calendars, each with id, summary, description, time_zone,
            access_role, and primary flag. Results are cached; call
            refresh_cache(calendar_id=<id>) to invalidate a specific calendar,
            or refresh_cache() to clear all caches.
        """
        lc = ctx.request_context.lifespan_context
        calendar_service = lc.calendar_service
        cache = lc.calendar_cache

        cached = cache.get_list()
        if cached is not None:
            return cached

        result = calendar_service.calendarList().list().execute()
        calendars = []
        for item in result.get("items", []):
            calendars.append(
                {
                    "id": item["id"],
                    "summary": item.get("summary", ""),
                    "description": item.get("description", ""),
                    "time_zone": item.get("timeZone", ""),
                    "access_role": item.get("accessRole", ""),
                    "primary": item.get("primary", False),
                }
            )

        cache.store_list(calendars)
        logger.debug("Found %d calendars", len(calendars))
        return calendars

    @tool(annotations=ToolAnnotations(title="Get Calendar", readOnlyHint=True))
    def get_calendar(
        calendar_id: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Get metadata for a single calendar.

        Args:
            calendar_id: The calendar ID (usually an email address, or 'primary').

        Returns:
            Calendar metadata: id, summary, description, time_zone, access_role,
            location, and primary flag. Results are cached; call
            refresh_cache(calendar_id=calendar_id) to invalidate, or
            refresh_cache() to clear all caches.
        """
        lc = ctx.request_context.lifespan_context
        calendar_service = lc.calendar_service
        cache = lc.calendar_cache

        cached = cache.get(calendar_id)
        if cached is not None:
            return cached

        try:
            item = calendar_service.calendarList().get(calendarId=calendar_id).execute()
            result = {
                "id": item["id"],
                "summary": item.get("summary", ""),
                "description": item.get("description", ""),
                "time_zone": item.get("timeZone", ""),
                "access_role": item.get("accessRole", ""),
                "location": item.get("location", ""),
                "primary": item.get("primary", False),
            }
            cache.store(calendar_id, result)
            return result
        except Exception as e:
            return {"error": str(e)}

    # Not cached: results depend on a time window and change continuously as events are added/modified.
    @tool(annotations=ToolAnnotations(title="List Events", readOnlyHint=True))
    def list_events(
        calendar_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        max_results: int = 50,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List events in a calendar, optionally filtered by time range or search query.

        Args:
            calendar_id: The calendar ID (usually an email address, or 'primary').
            time_min: Lower bound for event start time, RFC3339 format
                      e.g. '2026-05-22T00:00:00Z'. Defaults to now if omitted.
            time_max: Upper bound for event start time, RFC3339 format.
            query: Free-text search string matched against summary, description,
                   location, attendee emails, and organizer.
            max_results: Maximum events to return (default 50, max 2500).

        Returns:
            List of events with id, summary, start, end, location, description,
            status, organizer, attendees, and htmlLink.
        """
        calendar_service = ctx.request_context.lifespan_context.calendar_service
        max_results = min(max(1, max_results), 2500)

        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            kwargs["timeMin"] = time_min
        if time_max:
            kwargs["timeMax"] = time_max
        if query:
            kwargs["q"] = query

        try:
            result = calendar_service.events().list(**kwargs).execute()
            events = []
            for e in result.get("items", []):
                start = e.get("start", {})
                end = e.get("end", {})
                events.append(
                    {
                        "id": e["id"],
                        "summary": e.get("summary", ""),
                        "start": start.get("dateTime") or start.get("date"),
                        "end": end.get("dateTime") or end.get("date"),
                        "location": e.get("location", ""),
                        "description": e.get("description", ""),
                        "status": e.get("status", ""),
                        "organizer": e.get("organizer", {}).get("email", ""),
                        "attendees": [a.get("email") for a in e.get("attendees", [])],
                        "html_link": e.get("htmlLink", ""),
                    }
                )
            logger.debug("Found %d events in calendar %s", len(events), calendar_id)
            return events
        except Exception as e:
            return [{"error": str(e)}]

    # Not cached: event details can change at any time (updates, RSVP responses, cancellations).
    @tool(annotations=ToolAnnotations(title="Get Event", readOnlyHint=True))
    def get_event(
        calendar_id: str,
        event_id: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Get a single calendar event by ID.

        Args:
            calendar_id: The calendar ID (usually an email address, or 'primary').
            event_id: The event ID.

        Returns:
            Full event details: id, summary, start, end, location, description,
            status, organizer, attendees, recurrence, and htmlLink.
        """
        calendar_service = ctx.request_context.lifespan_context.calendar_service

        try:
            e = calendar_service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            start = e.get("start", {})
            end = e.get("end", {})
            return {
                "id": e["id"],
                "summary": e.get("summary", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": e.get("location", ""),
                "description": e.get("description", ""),
                "status": e.get("status", ""),
                "organizer": e.get("organizer", {}).get("email", ""),
                "attendees": [
                    {"email": a.get("email"), "response": a.get("responseStatus")}
                    for a in e.get("attendees", [])
                ],
                "recurrence": e.get("recurrence", []),
                "html_link": e.get("htmlLink", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    @tool(annotations=ToolAnnotations(title="Create Event", destructiveHint=True))
    def create_event(
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        time_zone: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new event in a calendar.

        Args:
            calendar_id: The calendar ID (usually an email address, or 'primary').
            summary: Event title.
            start: Start datetime in RFC3339 format ('2026-05-22T14:00:00-07:00')
                   or date-only ('2026-05-22') for all-day events.
            end: End datetime or date in the same format as start.
            description: Optional event description.
            location: Optional location string.
            attendees: Optional list of attendee email addresses.
            time_zone: IANA timezone name (e.g. 'America/Los_Angeles'). Required
                       when start/end are date-only all-day events.

        Returns:
            Created event with id, summary, start, end, and htmlLink.
        """
        calendar_service = ctx.request_context.lifespan_context.calendar_service

        def _dt_field(value: str, tz: str | None) -> dict[str, str]:
            if "T" in value:
                field: dict[str, str] = {"dateTime": value}
                if tz:
                    field["timeZone"] = tz
                return field
            return {"date": value, **({"timeZone": tz} if tz else {})}

        body: dict[str, Any] = {
            "summary": summary,
            "start": _dt_field(start, time_zone),
            "end": _dt_field(end, time_zone),
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]

        try:
            e = calendar_service.events().insert(calendarId=calendar_id, body=body).execute()
            start_val = e.get("start", {})
            end_val = e.get("end", {})
            return {
                "id": e["id"],
                "summary": e.get("summary", ""),
                "start": start_val.get("dateTime") or start_val.get("date"),
                "end": end_val.get("dateTime") or end_val.get("date"),
                "html_link": e.get("htmlLink", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    @tool(annotations=ToolAnnotations(title="Update Event", destructiveHint=True))
    def update_event(
        calendar_id: str,
        event_id: str,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        time_zone: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Update fields on an existing calendar event. Only provided fields are changed.

        Args:
            calendar_id: The calendar ID (usually an email address, or 'primary').
            event_id: The event ID to update.
            summary: New event title.
            start: New start datetime (RFC3339) or date.
            end: New end datetime (RFC3339) or date.
            description: New description.
            location: New location.
            time_zone: IANA timezone name, applied to start/end if provided.

        Returns:
            Updated event with id, summary, start, end, and htmlLink.
        """
        calendar_service = ctx.request_context.lifespan_context.calendar_service

        def _dt_field(value: str, tz: str | None) -> dict[str, str]:
            if "T" in value:
                field: dict[str, str] = {"dateTime": value}
                if tz:
                    field["timeZone"] = tz
                return field
            return {"date": value, **({"timeZone": tz} if tz else {})}

        patch: dict[str, Any] = {}
        if summary is not None:
            patch["summary"] = summary
        if start is not None:
            patch["start"] = _dt_field(start, time_zone)
        if end is not None:
            patch["end"] = _dt_field(end, time_zone)
        if description is not None:
            patch["description"] = description
        if location is not None:
            patch["location"] = location

        try:
            e = (
                calendar_service.events()
                .patch(calendarId=calendar_id, eventId=event_id, body=patch)
                .execute()
            )
            start_val = e.get("start", {})
            end_val = e.get("end", {})
            return {
                "id": e["id"],
                "summary": e.get("summary", ""),
                "start": start_val.get("dateTime") or start_val.get("date"),
                "end": end_val.get("dateTime") or end_val.get("date"),
                "html_link": e.get("htmlLink", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    @tool(annotations=ToolAnnotations(title="Delete Event", destructiveHint=True))
    def delete_event(
        calendar_id: str,
        event_id: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete a calendar event.

        Args:
            calendar_id: The calendar ID (usually an email address, or 'primary').
            event_id: The event ID to delete.

        Returns:
            {'deleted': True} on success, or {'error': ...} on failure.
        """
        calendar_service = ctx.request_context.lifespan_context.calendar_service

        try:
            calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.debug("Deleted event %s from calendar %s", event_id, calendar_id)
            return {"deleted": True}
        except Exception as e:
            return {"error": str(e)}

    # Not cached: free/busy data is inherently time-sensitive; stale results would be actively wrong.
    @tool(annotations=ToolAnnotations(title="Find Free Slots", readOnlyHint=True))
    def find_free_slots(
        calendar_ids: list[str],
        time_min: str,
        time_max: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Find busy periods for one or more calendars within a time window.
        Use the gaps between busy periods to identify free slots.

        Args:
            calendar_ids: List of calendar IDs to check.
            time_min: Start of the window, RFC3339 format (e.g. '2026-05-22T00:00:00Z').
            time_max: End of the window, RFC3339 format.

        Returns:
            Dict with 'time_min', 'time_max', and 'busy' — a map of calendar_id
            to list of {'start', 'end'} busy periods.
        """
        calendar_service = ctx.request_context.lifespan_context.calendar_service

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cid} for cid in calendar_ids],
        }

        try:
            result = calendar_service.freebusy().query(body=body).execute()
            busy: dict[str, list[dict[str, str]]] = {}
            for cid, info in result.get("calendars", {}).items():
                busy[cid] = [{"start": p["start"], "end": p["end"]} for p in info.get("busy", [])]
            return {
                "time_min": time_min,
                "time_max": time_max,
                "busy": busy,
            }
        except Exception as e:
            return {"error": str(e)}
