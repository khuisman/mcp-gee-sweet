import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..auth import execute_in_thread
from .response_limits import enforce_response_size_cap

logger = logging.getLogger(__name__)

_CANNOT_UNSUBSCRIBE_OWNED_ERROR = (
    "Google does not allow removing a calendar you own from your own calendar list "
    "(reason: cannotUnsubscribeFromOwnedCalendar). Use delete_calendar instead to "
    "permanently delete it."
)

_CALENDAR_ACL_ROLES = ("reader", "writer", "owner", "freeBusyReader")
_CALENDAR_ACL_SCOPE_TYPES = ("default", "user", "group", "domain")


def register(tool):
    @tool(annotations=ToolAnnotations(title="List Calendars", readOnlyHint=True))
    async def list_calendars(ctx: Context = None) -> list[dict[str, Any]]:
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

        result = await execute_in_thread(
            lc.calendar_service.calendarList().list().execute,
            lc.calendar_service,
        )
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
    async def get_calendar(calendar_id: str, ctx: Context = None) -> dict[str, Any]:
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
            c = await execute_in_thread(
                lc.calendar_service.calendarList().get(calendarId=calendar_id).execute,
                lc.calendar_service,
            )
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

    @tool(annotations=ToolAnnotations(title="Create Calendar", destructiveHint=True))
    async def create_calendar(
        summary: str,
        description: str | None = None,
        timezone: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Create a new secondary calendar owned by the authenticated user.

        Args:
            summary: Calendar title.
            description: Optional calendar description.
            timezone: IANA timezone name (e.g. 'America/Los_Angeles'). Defaults to
                      the account's timezone if omitted.

        Returns:
            Created calendar: id, summary, description, time_zone.
        """
        lc = ctx.request_context.lifespan_context

        body: dict[str, Any] = {"summary": summary}
        if description:
            body["description"] = description
        if timezone:
            body["timeZone"] = timezone

        try:
            c = await execute_in_thread(
                lc.calendar_service.calendars().insert(body=body).execute,
                lc.calendar_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(c["id"])
        logger.debug("Created calendar %s", c["id"])
        return {
            "id": c["id"],
            "summary": c.get("summary", ""),
            "description": c.get("description"),
            "time_zone": c.get("timeZone"),
        }

    @tool(annotations=ToolAnnotations(title="Update Calendar", destructiveHint=True))
    async def update_calendar(
        calendar_id: str,
        summary: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
        color_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Update fields on an existing calendar using patch semantics. Only the
        fields you provide are changed; omitted fields are left as-is.

        Note: color_id is set via the authenticated user's calendar list entry
        (calendarList().patch()), not the calendar resource itself — it is a
        per-user setting, not a property of the calendar shared with others.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            summary: New calendar title.
            description: New calendar description.
            timezone: New IANA timezone name (e.g. 'America/Los_Angeles').
            color_id: New color ID from the palette returned by the Calendar API's
                      colors().get() endpoint (predefined IDs, typically '1'-'24').

        Returns:
            Updated calendar: id, summary, description, time_zone, color_id.
        """
        lc = ctx.request_context.lifespan_context

        patch: dict[str, Any] = {}
        if summary is not None:
            patch["summary"] = summary
        if description is not None:
            patch["description"] = description
        if timezone is not None:
            patch["timeZone"] = timezone

        try:
            if patch:
                c = await execute_in_thread(
                    lc.calendar_service.calendars()
                    .patch(calendarId=calendar_id, body=patch)
                    .execute,
                    lc.calendar_service,
                )
            else:
                c = await execute_in_thread(
                    lc.calendar_service.calendars().get(calendarId=calendar_id).execute,
                    lc.calendar_service,
                )

            result_color_id = None
            if color_id is not None:
                list_entry = await execute_in_thread(
                    lc.calendar_service.calendarList()
                    .patch(calendarId=calendar_id, body={"colorId": color_id})
                    .execute,
                    lc.calendar_service,
                )
                result_color_id = list_entry.get("colorId")
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Updated calendar %s", calendar_id)
        return {
            "id": c.get("id", calendar_id),
            "summary": c.get("summary", ""),
            "description": c.get("description"),
            "time_zone": c.get("timeZone"),
            "color_id": result_color_id,
        }

    @tool(annotations=ToolAnnotations(title="Delete Calendar", destructiveHint=True))
    async def delete_calendar(calendar_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Permanently delete a calendar. For calendars you own, this deletes the
        calendar entirely for all users it is shared with — use with caution.
        To only stop seeing a calendar in your own list, use
        remove_calendar_from_list instead.

        Args:
            calendar_id: The calendar ID to delete.

        Returns:
            Confirmation with calendar_id and action 'deleted'.
        """
        lc = ctx.request_context.lifespan_context
        try:
            await execute_in_thread(
                lc.calendar_service.calendars().delete(calendarId=calendar_id).execute,
                lc.calendar_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Deleted calendar %s", calendar_id)
        return {"calendar_id": calendar_id, "action": "deleted"}

    @tool(annotations=ToolAnnotations(title="Add Calendar To List", destructiveHint=True))
    async def add_calendar_to_list(
        calendar_id: str,
        color_id: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Subscribe the authenticated user (or service account) to a calendar,
        adding it to their calendar list so it appears in list_calendars.

        This does not create or share a calendar — it only adds an existing,
        already-accessible calendar to your own list. For service accounts,
        this is the required step before a calendar shared with the service
        account's email will show up in list_calendars.

        Args:
            calendar_id: The calendar ID to subscribe to (e.g. the owner's email
                         for a personal calendar, or a `...@group.calendar.google.com` ID).
            color_id: Optional color ID from the palette returned by the Calendar
                      API's colors().get() endpoint (predefined IDs, typically '1'-'24').

        Returns:
            The new calendar list entry: id, summary, time_zone, access_role,
            primary, color_id.
        """
        lc = ctx.request_context.lifespan_context

        body: dict[str, Any] = {"id": calendar_id}
        if color_id is not None:
            body["colorId"] = color_id

        try:
            c = await execute_in_thread(
                lc.calendar_service.calendarList().insert(body=body).execute,
                lc.calendar_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(c["id"])
        logger.debug("Added calendar %s to calendar list", c["id"])
        return {
            "id": c["id"],
            "summary": c.get("summary", ""),
            "time_zone": c.get("timeZone"),
            "access_role": c.get("accessRole"),
            "primary": c.get("primary", False),
            "color_id": c.get("colorId"),
        }

    @tool(annotations=ToolAnnotations(title="Remove Calendar From List", destructiveHint=True))
    async def remove_calendar_from_list(calendar_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Unsubscribe from a calendar, removing it from the authenticated user's
        calendar list. The calendar itself is not deleted and is unaffected for
        any other user it's shared with — use delete_calendar to permanently
        delete a calendar you own.

        Args:
            calendar_id: The calendar ID to remove from the list.

        Returns:
            Confirmation with calendar_id and action 'removed_from_list'.
        """
        lc = ctx.request_context.lifespan_context
        try:
            await execute_in_thread(
                lc.calendar_service.calendarList().delete(calendarId=calendar_id).execute,
                lc.calendar_service,
            )
        except HttpError as e:
            if e.resp.status == 403 and b"cannotUnsubscribeFromOwnedCalendar" in (e.content or b""):
                return {"error": _CANNOT_UNSUBSCRIBE_OWNED_ERROR}
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Removed calendar %s from calendar list", calendar_id)
        return {"calendar_id": calendar_id, "action": "removed_from_list"}

    @tool(annotations=ToolAnnotations(title="List Calendar ACL", readOnlyHint=True))
    async def list_calendar_acl(calendar_id: str, ctx: Context = None) -> list[dict[str, Any]]:
        """
        List the access control rules (sharing entries) on a calendar.

        Args:
            calendar_id: The calendar ID, or 'primary'.

        Returns:
            List of ACL rules, each with id, role, scope_type, and scope_value.
        """
        lc = ctx.request_context.lifespan_context
        try:
            result = await execute_in_thread(
                lc.calendar_service.acl().list(calendarId=calendar_id).execute,
                lc.calendar_service,
            )
        except Exception as e:
            return [{"error": str(e)}]

        rules = []
        for r in result.get("items", []):
            scope = r.get("scope", {})
            rules.append(
                {
                    "id": r.get("id"),
                    "role": r.get("role"),
                    "scope_type": scope.get("type"),
                    "scope_value": scope.get("value"),
                }
            )
        return rules

    @tool(annotations=ToolAnnotations(title="Add Calendar ACL", destructiveHint=True))
    async def add_calendar_acl(
        calendar_id: str,
        role: str,
        scope_type: str = "user",
        scope_value: str | None = None,
        send_notifications: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Grant access to a calendar by adding an access control rule.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            role: Access role to grant. One of: 'reader', 'writer', 'owner', 'freeBusyReader'.
            scope_type: Who the rule applies to. One of: 'user', 'group', 'domain', 'default'
                        ('default' grants public access to all users and needs no scope_value).
            scope_value: Email address (for 'user'/'group') or domain name (for 'domain').
                         Required unless scope_type is 'default'.
            send_notifications: Whether to send a notification email to the grantee.
                                 Defaults to True.

        Returns:
            Created ACL rule: id, role, scope_type, scope_value.
        """
        lc = ctx.request_context.lifespan_context

        if role not in _CALENDAR_ACL_ROLES:
            return {
                "error": f"Invalid role '{role}'. Must be one of: {', '.join(_CALENDAR_ACL_ROLES)}"
            }
        if scope_type not in _CALENDAR_ACL_SCOPE_TYPES:
            return {
                "error": f"Invalid scope_type '{scope_type}'. "
                f"Must be one of: {', '.join(_CALENDAR_ACL_SCOPE_TYPES)}"
            }
        if scope_type != "default" and not scope_value:
            return {"error": f"scope_value is required when scope_type is '{scope_type}'."}

        scope: dict[str, str] = {"type": scope_type}
        if scope_value:
            scope["value"] = scope_value

        try:
            r = await execute_in_thread(
                lc.calendar_service.acl()
                .insert(
                    calendarId=calendar_id,
                    body={"role": role, "scope": scope},
                    sendNotifications=send_notifications,
                )
                .execute,
                lc.calendar_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Added ACL rule %s to calendar %s", r.get("id"), calendar_id)
        result_scope = r.get("scope", {})
        return {
            "id": r.get("id"),
            "role": r.get("role"),
            "scope_type": result_scope.get("type"),
            "scope_value": result_scope.get("value"),
        }

    @tool(annotations=ToolAnnotations(title="Remove Calendar ACL", destructiveHint=True))
    async def remove_calendar_acl(
        calendar_id: str, rule_id: str, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Revoke an access control rule from a calendar.

        Args:
            calendar_id: The calendar ID, or 'primary'.
            rule_id: The ACL rule ID to remove (from list_calendar_acl).

        Returns:
            Confirmation with calendar_id, rule_id, and action 'removed'.
        """
        lc = ctx.request_context.lifespan_context
        try:
            await execute_in_thread(
                lc.calendar_service.acl().delete(calendarId=calendar_id, ruleId=rule_id).execute,
                lc.calendar_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Removed ACL rule %s from calendar %s", rule_id, calendar_id)
        return {"calendar_id": calendar_id, "rule_id": rule_id, "action": "removed"}

    @tool(annotations=ToolAnnotations(title="List Events", readOnlyHint=True))
    async def list_events(
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
            result = await execute_in_thread(
                lc.calendar_service.events().list(**kwargs).execute,
                lc.calendar_service,
            )
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
    async def get_event(calendar_id: str, event_id: str, ctx: Context = None) -> dict[str, Any]:
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
            e = await execute_in_thread(
                lc.calendar_service.events().get(calendarId=calendar_id, eventId=event_id).execute,
                lc.calendar_service,
            )
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
    async def create_event(
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
            e = await execute_in_thread(
                lc.calendar_service.events().insert(calendarId=calendar_id, body=body).execute,
                lc.calendar_service,
            )
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
    async def update_event(
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
            e = await execute_in_thread(
                lc.calendar_service.events()
                .patch(calendarId=calendar_id, eventId=event_id, body=patch)
                .execute,
                lc.calendar_service,
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
    async def delete_event(calendar_id: str, event_id: str, ctx: Context = None) -> dict[str, Any]:
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
            await execute_in_thread(
                lc.calendar_service.events()
                .delete(calendarId=calendar_id, eventId=event_id)
                .execute,
                lc.calendar_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.calendar_cache.mark_dirty(calendar_id)
        logger.debug("Deleted event %s from calendar %s", event_id, calendar_id)
        return {"calendar_id": calendar_id, "event_id": event_id, "action": "deleted"}

    @tool(annotations=ToolAnnotations(title="Find Free Slots", readOnlyHint=True))
    async def find_free_slots(
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
            result = await execute_in_thread(
                lc.calendar_service.freebusy().query(body=body).execute,
                lc.calendar_service,
            )
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

    @tool(annotations=ToolAnnotations(title="List All Events", readOnlyHint=True))
    async def list_all_events(
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        calendar_ids: list[str] | None = None,
        max_results_per_calendar: int = 50,
        expand_recurring: bool = True,
        group_by_calendar: bool = False,
        ctx: Context = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        List events across multiple calendars in one call, fanning out to each
        calendar in parallel instead of requiring one list_events call per calendar.

        Args:
            time_min: Lower bound (inclusive) for event start times, RFC 3339 format,
                      e.g. '2026-01-01T00:00:00Z'. Defaults to the current UTC time.
            time_max: Upper bound (exclusive) for event end times, RFC 3339 format.
            query: Free-text search terms to find events matching summary, description,
                   location, attendee names/emails.
            calendar_ids: Calendar IDs to query. Defaults to every calendar in the
                          authenticated user's calendar list (list_calendars).
            max_results_per_calendar: Maximum number of events to return per calendar
                                       (default 50, max 2500).
            expand_recurring: When True (default), recurring events are expanded into
                              individual instances. When False, each recurring series is
                              returned as a single master event.
            group_by_calendar: When False (default), returns a flat list of events sorted
                               by calendar. When True, returns a dict keyed by calendar
                               summary instead (disambiguated with " (calendar_id)" suffix
                               when two calendars share the same summary).

        Returns:
            A flat list of events (each including calendar_id and calendar_summary),
            or if group_by_calendar=True, a dict mapping calendar summary to that
            calendar's event list. A calendar that fails to query is included inline
            as {calendar_id, calendar_summary, error} rather than aborting the batch.
            If the calendar list itself fails to load and calendar_ids wasn't given
            (so there's no way to know what to query), returns a single top-level
            {"error": ...} instead of raising.
            Raises ValueError if the response exceeds the safety cap (default 1,000,000
            characters, set MAX_TOOL_RESPONSE_CHARS to change it) — narrow the time
            window, pass calendar_ids, or lower max_results_per_calendar.
        """
        lc = ctx.request_context.lifespan_context
        max_results_per_calendar = min(max(1, max_results_per_calendar), 2500)
        resolved_time_min = time_min or datetime.now(timezone.utc).isoformat()

        cache = lc.calendar_cache
        try:
            all_calendars = cache.get_list()
            if all_calendars is None:
                result = await execute_in_thread(
                    lc.calendar_service.calendarList().list().execute,
                    lc.calendar_service,
                )
                all_calendars = [
                    {
                        "id": c["id"],
                        "summary": c.get("summary", ""),
                        "time_zone": c.get("timeZone"),
                        "access_role": c.get("accessRole"),
                        "primary": c.get("primary", False),
                    }
                    for c in result.get("items", [])
                ]
                cache.store_list(all_calendars)
        except Exception as e:
            # calendar_ids explicit: this call only needed the list for display
            # names, so fall back to bare calendar_ids instead of aborting.
            if calendar_ids is None:
                error_result: dict[str, Any] = {"error": f"Failed to list calendars: {e!s}"}
                return error_result if group_by_calendar else [error_result]
            all_calendars = []

        summary_by_id = {c["id"]: c.get("summary", "") for c in all_calendars}
        target_ids = calendar_ids if calendar_ids is not None else [c["id"] for c in all_calendars]

        summary_counts: dict[str, int] = {}
        for cid in target_ids:
            summary = summary_by_id.get(cid, cid)
            summary_counts[summary] = summary_counts.get(summary, 0) + 1

        def _group_key(calendar_id: str) -> str:
            summary = summary_by_id.get(calendar_id, calendar_id)
            if summary_counts.get(summary, 0) > 1:
                return f"{summary} ({calendar_id})"
            return summary

        async def _fetch_one(calendar_id: str) -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "calendarId": calendar_id,
                "maxResults": max_results_per_calendar,
                "singleEvents": expand_recurring,
                "timeMin": resolved_time_min,
            }
            if expand_recurring:
                kwargs["orderBy"] = "startTime"
            if time_max:
                kwargs["timeMax"] = time_max
            if query:
                kwargs["q"] = query

            calendar_summary = summary_by_id.get(calendar_id, calendar_id)
            try:
                result = await execute_in_thread(
                    lc.calendar_service.events().list(**kwargs).execute,
                    lc.calendar_service,
                )
            except Exception as e:
                return {
                    "calendar_id": calendar_id,
                    "calendar_summary": calendar_summary,
                    "error": str(e),
                }

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
                        "calendar_id": calendar_id,
                        "calendar_summary": calendar_summary,
                    }
                )
            return {
                "calendar_id": calendar_id,
                "calendar_summary": calendar_summary,
                "events": events,
            }

        # return_exceptions=True: each _fetch_one already catches its own errors and
        # returns a tagged dict, but this also lets any genuinely unexpected exception
        # finish alongside the rest of the batch instead of orphaning in-flight tasks.
        raw = await asyncio.gather(*(_fetch_one(cid) for cid in target_ids), return_exceptions=True)
        per_calendar = [
            r
            if not isinstance(r, BaseException)
            else {
                "calendar_id": cid,
                "calendar_summary": summary_by_id.get(cid, cid),
                "error": str(r),
            }
            for cid, r in zip(target_ids, raw, strict=True)
        ]

        if group_by_calendar:
            grouped: dict[str, Any] = {}
            for entry in per_calendar:
                key = _group_key(entry["calendar_id"])
                grouped[key] = (
                    {"error": entry["error"], "calendar_id": entry["calendar_id"]}
                    if "error" in entry
                    else entry["events"]
                )
            enforce_response_size_cap(
                grouped, tool_name="list_all_events", local_path_available=False
            )
            return grouped

        flat: list[dict[str, Any]] = []
        for entry in per_calendar:
            if "error" in entry:
                flat.append(
                    {
                        "calendar_id": entry["calendar_id"],
                        "calendar_summary": entry["calendar_summary"],
                        "error": entry["error"],
                    }
                )
            else:
                flat.extend(entry["events"])
        enforce_response_size_cap(flat, tool_name="list_all_events", local_path_available=False)
        return flat
