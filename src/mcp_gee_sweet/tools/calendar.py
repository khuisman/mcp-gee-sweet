import logging
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Calendars", readOnlyHint=True))
    def list_calendars(ctx: Context = None) -> list[dict[str, Any]]:
        """
        List all calendars accessible to the authenticated user.

        Returns:
            List of calendars with id, summary, time_zone, access_role, and primary flag.
            Results are cached; call refresh_cache(calendar_id=...) to invalidate.
        """
        lc = ctx.request_context.lifespan_context
        cache = lc.calendar_cache

        cached = cache.get_list()
        if cached is not None:
            return cached

        result = lc.calendar_service.calendarList().list().execute()
        calendars = [
            {
                "id": c["id"],
                "summary": c.get("summary", ""),
                "time_zone": c.get("timeZone"),
                "access_role": c.get("accessRole"),
                "primary": c.get("primary", False),
            }
            for c in result.get("items", [])
        ]
        cache.store_list(calendars)
        return calendars

    @tool(annotations=ToolAnnotations(title="Get Calendar", readOnlyHint=True))
    def get_calendar(calendar_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Fetch metadata for a single calendar.

        Args:
            calendar_id: The calendar ID, or 'primary' for the user's primary calendar.

        Returns:
            Calendar metadata: id, summary, description, time_zone, access_role, primary.
        """
        lc = ctx.request_context.lifespan_context
        cache = lc.calendar_cache

        cached = cache.get(calendar_id)
        if cached is not None:
            return cached

        try:
            c = lc.calendar_service.calendarList().get(calendarId=calendar_id).execute()
        except Exception as e:
            return {"error": str(e)}

        result = {
            "id": c["id"],
            "summary": c.get("summary", ""),
            "description": c.get("description"),
            "time_zone": c.get("timeZone"),
            "access_role": c.get("accessRole"),
            "primary": c.get("primary", False),
        }
        cache.store(calendar_id, result)
        return result

    @tool(annotations=ToolAnnotations(title="List Events", readOnlyHint=True))
    def list_events(
        calendar_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        max_results: int = 50,
        expand_recurring: bool = True,
        ctx: Context = None,
    ) -> list[dict[str, Any]]:
        """
        List events in a calendar.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            time_min: Lower bound (inclusive) for event start times, RFC 3339 format,
                      e.g. '2026-01-01T00:00:00Z'. Defaults to the current UTC time.
            time_max: Upper bound (exclusive) for event end times, RFC 3339 format.
            query: Free-text search terms to find events matching summary, description,
                   location, attendee names/emails.
            max_results: Maximum number of events to return (default 50, max 2500).
            expand_recurring: When True (default), recurring events are expanded into
                              individual instances. When False, each recurring series is
                              returned as a single master event — useful for retrieving
                              the master event ID needed to update all instances at once.

        Returns:
            List of events with id, summary, start, end, location, description,
            organizer, attendees, recurrence, html_link, and status.
        """
        lc = ctx.request_context.lifespan_context
        max_results = min(max(1, max_results), 2500)

        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": expand_recurring,
        }
        if expand_recurring:
            kwargs["orderBy"] = "startTime"
        kwargs["timeMin"] = time_min or datetime.now(timezone.utc).isoformat()
        if time_max:
            kwargs["timeMax"] = time_max
        if query:
            kwargs["q"] = query

        try:
            result = lc.calendar_service.events().list(**kwargs).execute()
        except Exception as e:
            return [{"error": str(e)}]

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
                    "location": e.get("location"),
                    "description": e.get("description"),
                    "organizer": e.get("organizer", {}).get("email"),
                    "attendees": [
                        {"email": a.get("email"), "response": a.get("responseStatus")}
                        for a in e.get("attendees", [])
                    ],
                    "recurrence": e.get("recurrence"),
                    "html_link": e.get("htmlLink"),
                    "status": e.get("status"),
                }
            )
        return events

    @tool(annotations=ToolAnnotations(title="Get Event", readOnlyHint=True))
    def get_event(calendar_id: str, event_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Fetch a single event by calendar ID and event ID.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            event_id: The event ID.

        Returns:
            Full event details: id, summary, start, end, location, description,
            organizer, attendees, recurrence, html_link, status, created, updated.
        """
        lc = ctx.request_context.lifespan_context
        try:
            e = lc.calendar_service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except Exception as ex:
            return {"error": str(ex)}

        start = e.get("start", {})
        end = e.get("end", {})
        return {
            "id": e["id"],
            "summary": e.get("summary", ""),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "location": e.get("location"),
            "description": e.get("description"),
            "organizer": e.get("organizer", {}).get("email"),
            "attendees": [
                {"email": a.get("email"), "response": a.get("responseStatus")}
                for a in e.get("attendees", [])
            ],
            "recurrence": e.get("recurrence"),
            "html_link": e.get("htmlLink"),
            "status": e.get("status"),
            "created": e.get("created"),
            "updated": e.get("updated"),
        }

    @tool(annotations=ToolAnnotations(title="Create Event", destructiveHint=True))
    def create_event(
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        timezone: str | None = None,
        recurrence: list[str] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new event in a calendar.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            summary: Event title.
            start: Start datetime in RFC 3339 format, e.g. '2026-06-01T10:00:00-07:00'.
                   Use 'YYYY-MM-DD' for all-day events.
            end: End datetime in RFC 3339 format. Use 'YYYY-MM-DD' for all-day events.
            description: Optional event description.
            location: Optional location string.
            attendees: Optional list of attendee email addresses.
            timezone: IANA timezone name (e.g. 'America/Los_Angeles'). Required when
                      start/end are date-only (all-day events) or when recurrence is
                      set with datetime start/end.
            recurrence: RFC 5545 recurrence rules, e.g.
                        ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"] for Mon/Wed/Fri weekly,
                        ["RRULE:FREQ=DAILY;COUNT=5"] for 5 occurrences,
                        ["RRULE:FREQ=MONTHLY;UNTIL=20261231T000000Z"] until a date.
                        EXDATE and RDATE lines are also accepted in the array.

        Returns:
            Created event: id, summary, start, end, recurrence, html_link, status.
        """
        lc = ctx.request_context.lifespan_context

        is_all_day = len(start) == 10  # 'YYYY-MM-DD'
        if is_all_day:
            start_obj: dict[str, str] = {"date": start}
            end_obj: dict[str, str] = {"date": end}
            if timezone:
                start_obj["timeZone"] = timezone
                end_obj["timeZone"] = timezone
        else:
            start_obj = {"dateTime": start}
            end_obj = {"dateTime": end}
            if timezone:
                start_obj["timeZone"] = timezone
                end_obj["timeZone"] = timezone

        body: dict[str, Any] = {"summary": summary, "start": start_obj, "end": end_obj}
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        if recurrence:
            body["recurrence"] = recurrence

        try:
            e = lc.calendar_service.events().insert(calendarId=calendar_id, body=body).execute()
        except Exception as ex:
            return {"error": str(ex)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Created event %s in calendar %s", e["id"], calendar_id)
        ev_start = e.get("start", {})
        ev_end = e.get("end", {})
        return {
            "id": e["id"],
            "summary": e.get("summary", ""),
            "start": ev_start.get("dateTime") or ev_start.get("date"),
            "end": ev_end.get("dateTime") or ev_end.get("date"),
            "recurrence": e.get("recurrence"),
            "html_link": e.get("htmlLink"),
            "status": e.get("status"),
        }

    @tool(annotations=ToolAnnotations(title="Update Event", destructiveHint=True))
    def update_event(
        calendar_id: str,
        event_id: str,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        timezone: str | None = None,
        recurrence: list[str] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Update fields on an existing event using a partial update (patch semantics).
        Only the fields you provide are changed; omitted fields are left as-is.

        **Recurring event scope** — the Calendar API controls which instances are
        updated based on which event ID you pass:
        - This event only: pass the instance event ID (e.g. "base_id_20260601T100000Z").
          The API creates an exception override for that occurrence.
        - All events in the series: pass the master (recurring) event ID. Use
          list_events(expand_recurring=False) to retrieve master event IDs.
        - This and following: not directly supported by the API. As a workaround, update
          the master event's RRULE to add an UNTIL date before the target instance, then
          create a new event starting from that date.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            event_id: The event ID to update (instance ID for single-occurrence changes,
                      master ID for all-occurrence changes).
            summary: New event title.
            start: New start datetime (RFC 3339) or date ('YYYY-MM-DD').
            end: New end datetime (RFC 3339) or date ('YYYY-MM-DD').
            description: New description.
            location: New location.
            attendees: Replacement attendee list (full replacement, not append).
            timezone: IANA timezone for start/end when they are date-only.
            recurrence: RFC 5545 recurrence rules to replace the event's RRULE, e.g.
                        ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"]. Pass an empty list ([])
                        to remove recurrence and make the event a one-time occurrence.

        Returns:
            Updated event: id, summary, start, end, recurrence, html_link, status.
        """
        lc = ctx.request_context.lifespan_context
        patch: dict[str, Any] = {}

        if summary is not None:
            patch["summary"] = summary
        if description is not None:
            patch["description"] = description
        if location is not None:
            patch["location"] = location
        if attendees is not None:
            patch["attendees"] = [{"email": email} for email in attendees]
        if recurrence is not None:
            patch["recurrence"] = recurrence

        if start is not None:
            is_all_day = len(start) == 10
            start_obj: dict[str, str] = {"date": start} if is_all_day else {"dateTime": start}
            if timezone:
                start_obj["timeZone"] = timezone
            patch["start"] = start_obj

        if end is not None:
            is_all_day = len(end) == 10
            end_obj: dict[str, str] = {"date": end} if is_all_day else {"dateTime": end}
            if timezone:
                end_obj["timeZone"] = timezone
            patch["end"] = end_obj

        try:
            e = (
                lc.calendar_service.events()
                .patch(calendarId=calendar_id, eventId=event_id, body=patch)
                .execute()
            )
        except Exception as ex:
            return {"error": str(ex)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Updated event %s in calendar %s", event_id, calendar_id)
        ev_start = e.get("start", {})
        ev_end = e.get("end", {})
        return {
            "id": e["id"],
            "summary": e.get("summary", ""),
            "start": ev_start.get("dateTime") or ev_start.get("date"),
            "end": ev_end.get("dateTime") or ev_end.get("date"),
            "recurrence": e.get("recurrence"),
            "html_link": e.get("htmlLink"),
            "status": e.get("status"),
        }

    @tool(annotations=ToolAnnotations(title="Delete Event", destructiveHint=True))
    def delete_event(calendar_id: str, event_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Delete or cancel an event.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            event_id: The event ID to delete.

        Returns:
            Confirmation with calendar_id, event_id, and action 'deleted'.
        """
        lc = ctx.request_context.lifespan_context
        try:
            lc.calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Deleted event %s from calendar %s", event_id, calendar_id)
        return {"calendar_id": calendar_id, "event_id": event_id, "action": "deleted"}

    @tool(annotations=ToolAnnotations(title="Find Free Slots", readOnlyHint=True))
    def find_free_slots(
        calendar_ids: list[str],
        time_min: str,
        time_max: str,
        timezone: str = "UTC",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Query busy times for a list of calendars and return free slots within the window.

        Args:
            calendar_ids: List of calendar IDs to check (use 'primary' for the user's
                          primary calendar).
            time_min: Start of the window to check, RFC 3339 format,
                      e.g. '2026-06-01T09:00:00Z'.
            time_max: End of the window to check, RFC 3339 format.
            timezone: IANA timezone name for the query (default 'UTC').

        Returns:
            busy: dict mapping each calendar_id to its list of busy periods
                  ({start, end} each in RFC 3339).
            free_slots: list of free periods ({start, end}) across all calendars,
                        computed as the complement of the union of all busy times.
        """
        lc = ctx.request_context.lifespan_context

        body: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": timezone,
            "items": [{"id": cid} for cid in calendar_ids],
        }

        try:
            result = lc.calendar_service.freebusy().query(body=body).execute()
        except Exception as e:
            return {"error": str(e)}

        calendars_busy = result.get("calendars", {})
        busy: dict[str, list[dict[str, str]]] = {}
        for cid in calendar_ids:
            cal_data = calendars_busy.get(cid, {})
            errors = cal_data.get("errors")
            if errors:
                busy[cid] = [{"error": err.get("reason", "unknown")} for err in errors]
            else:
                busy[cid] = [
                    {"start": p["start"], "end": p["end"]} for p in cal_data.get("busy", [])
                ]

        # Compute union of all busy intervals to derive free slots
        all_busy: list[tuple[str, str]] = []
        for periods in busy.values():
            for p in periods:
                if "error" not in p:
                    all_busy.append((p["start"], p["end"]))

        all_busy.sort(key=lambda x: x[0])
        merged: list[tuple[str, str]] = []
        for start, end in all_busy:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        free_slots: list[dict[str, str]] = []
        cursor = time_min
        for busy_start, busy_end in merged:
            if cursor < busy_start:
                free_slots.append({"start": cursor, "end": busy_start})
            cursor = max(cursor, busy_end)
        if cursor < time_max:
            free_slots.append({"start": cursor, "end": time_max})

        return {"busy": busy, "free_slots": free_slots}
