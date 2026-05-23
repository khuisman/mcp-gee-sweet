# Calendar Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/calendar.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{CALENDAR_ID}` (a subscribed calendar the service account has access to) and `{EVENT_ID}` (a pre-existing event in that calendar) from `fixtures.local.md`.

> **Service account note:** the service account must have been added to each calendar via `calendarList().insert()` before it can read or write events. `list_calendars` only returns calendars the service account has explicitly subscribed to — it will not see calendars shared with the owning user's personal account. See `docs/project_calendar_setup.md` in memory.

---

## `list_calendars`

### TC-CAL01: Returns subscribed calendars

**Prompt**
> "List all calendars I have access to"

**Checks**
- Returns at least one calendar
- Each item has `id`, `summary`, `time_zone`, `access_role`, `primary`
- The service account's own calendar (or the primary shared calendar) is present

---

### TC-CAL02: primary flag

**Prompt**
> "List calendars and tell me which one is marked as primary"

**Checks**
- Exactly one calendar has `primary: true`
- All others have `primary: false`
- 🔍 **Service account note:** service accounts may have no primary calendar — `primary` may be `false` on all entries; note what is observed

---

### TC-CAL03: Cache hit on second call

**Prompt** (run twice)
> "List my calendars again"

**Checks**
- Second call returns same results
- Logs show `Calendar list cache hit`

---

### TC-CAL04: Empty subscription list

**Setup:** a service account with no calendar subscriptions

**Prompt**
> "List all calendars"

**Checks**
- Returns `[]` — not an error
- 🔍 **Hard to test without a fresh service account** — note if observed

---

## `get_calendar`

### TC-CAL05: Valid calendar ID

**Prompt**
> "Get the details for calendar {CALENDAR_ID}"

**Checks**
- Returns `id`, `summary`, `description`, `time_zone`, `access_role`, `primary`
- `time_zone` is a valid IANA name (e.g. `America/Los_Angeles`)
- No `error` field

---

### TC-CAL06: calendar_id='primary'

**Prompt**
> "Get the calendar details for 'primary'"

**Checks**
- Returns calendar metadata for the service account's primary calendar
- 🔍 **Service account note:** service accounts may not have a primary calendar — if so, expect `{"error": ...}`; note the actual response

---

### TC-CAL07: Cache hit on second call

**Prompt** (run twice)
> "Get calendar {CALENDAR_ID} again"

**Checks**
- Second call returns same result
- Logs show `Calendar cache hit: {CALENDAR_ID}`

---

### TC-CAL08: Non-existent calendar ID

**Prompt**
> "Get the calendar with ID 'totally-invalid-cal-id@example.com'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- Error message is from the Calendar API

---

## `list_events`

### TC-CAL09: No time filters — upcoming events

**Prompt**
> "List events in calendar {CALENDAR_ID} with no time filter"

**Checks**
- Returns events ordered by start time
- Events are from now onward (no past events)
- Each event has `id`, `summary`, `start`, `end`, `status`

---

### TC-CAL10: time_min + time_max window

**Prompt**
> "List events in {CALENDAR_ID} between 2026-06-01T00:00:00Z and 2026-06-30T23:59:59Z"

**Checks**
- All returned events fall within the specified window
- Events outside the window are absent
- Empty list returned if no events exist in that window — not an error

---

### TC-CAL11: query string search

**Prompt**
> "List events in {CALENDAR_ID} matching the search term 'dinner'"

**Checks**
- Returns only events whose summary, description, or location contains 'dinner'
- Non-matching events excluded
- Empty list if nothing matches — not an error

---

### TC-CAL12: All-day event format

**Setup:** a calendar containing at least one all-day event

**Prompt**
> "List events in {CALENDAR_ID} and show me any all-day events"

**Checks**
- All-day event `start` and `end` are date strings (`YYYY-MM-DD`), not datetime strings
- No `T` or timezone offset in the date values

---

### TC-CAL13: Timed event format

**Prompt**
> "List events in {CALENDAR_ID} and show me a timed event's start and end"

**Checks**
- Timed event `start` and `end` are RFC 3339 datetime strings (contain `T`)
- Timezone offset or `Z` is present

---

### TC-CAL14: max_results clamped

**Prompt**
> "List events in {CALENDAR_ID} with max_results=0" then "List events with max_results=3000"

**Checks**
- `max_results=0` → clamped to 1; at most 1 event returned
- `max_results=3000` → clamped to 2500; no more than 2500 events returned

---

### TC-CAL15: Non-existent calendar ID

**Prompt**
> "List events in calendar 'invalid-cal-id@example.com'"

**Checks**
- Returns `[{"error": "..."}]` — not a top-level exception
- Error message is from the Calendar API

---

## `get_event`

### TC-CAL16: Valid event — full details

**Prompt**
> "Get the details of event {EVENT_ID} from calendar {CALENDAR_ID}"

**Checks**
- Returns `id`, `summary`, `start`, `end`, `location`, `description`, `organizer`, `attendees`, `recurrence`, `html_link`, `status`, `created`, `updated`
- `html_link` opens the event in Google Calendar UI
- `organizer` is an email address string

---

### TC-CAL17: Attendees populated

**Setup:** an event with at least one attendee

**Prompt**
> "Get event {EVENT_ID} and list the attendees"

**Checks**
- `attendees` is a non-empty list
- Each attendee has `email` and `response` (e.g. `accepted`, `needsAction`)

---

### TC-CAL18: Recurring event instance

**Setup:** a recurring event in the calendar

**Prompt**
> "Get a recurring event instance from {CALENDAR_ID} and check its recurrence field"

**Checks**
- `recurrence` is a non-null list (e.g. `["RRULE:FREQ=WEEKLY;..."]`)
- Single (non-recurring) events have `recurrence: null`

---

### TC-CAL19: Non-existent event ID

**Prompt**
> "Get event 'invalidEventId999xyz' from calendar {CALENDAR_ID}"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- Error message references the bad event ID

---

## `create_event`

### TC-CAL20: Timed event ⚠️ destructive

**Prompt**
> "Create an event called 'QA-Timed-Test' in {CALENDAR_ID} on 2026-07-01 from 10:00am to 11:00am Pacific time"

**Checks**
- Event created successfully
- `start` and `end` are RFC 3339 datetime strings with timezone offset
- `html_link` is present and opens the event in Google Calendar
- `status` is `confirmed`
- `calendar_cache.mark_dirty` called — next `list_events` re-fetches

---

### TC-CAL21: All-day event ⚠️ destructive

**Prompt**
> "Create an all-day event called 'QA-AllDay-Test' in {CALENDAR_ID} on 2026-07-02"

**Checks**
- `start` and `end` in response are date strings (`2026-07-02`, `2026-07-03`)
- No `T` in the date values — confirms `date` field used, not `dateTime`
- Event appears in `list_events` for that day

---

### TC-CAL22: With description, location, and attendees ⚠️ destructive

**Prompt**
> "Create an event called 'QA-Full-Test' in {CALENDAR_ID} for 2026-07-03 2pm-3pm PT with description 'QA test event', location 'Conference Room A', and attendee test@example.com"

**Checks**
- All three optional fields present on the created event (verify with `get_event`)
- `attendees` contains `test@example.com`
- `location` is `Conference Room A`
- `description` is `QA test event`

---

### TC-CAL23: Invalid calendar ID

**Prompt**
> "Create an event called 'QA-BadCal' in calendar 'invalid-cal@example.com' for tomorrow"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- No event created

---

## `update_event`

### TC-CAL24: Update summary only ⚠️ destructive

**Prompt**
> "Update the event created in TC-CAL20 — change the title to 'QA-Timed-Updated'"

**Checks**
- `summary` in response is `QA-Timed-Updated`
- `start`, `end`, `location`, `description` unchanged (verify with `get_event`)
- `calendar_cache.mark_dirty` called

---

### TC-CAL25: Update start and end ⚠️ destructive

**Prompt**
> "Update the event from TC-CAL20 — move it to 2026-07-01 from 2pm to 3pm PT"

**Checks**
- `start` and `end` reflect the new times
- `summary` and other fields unchanged

---

### TC-CAL26: Update description and location ⚠️ destructive

**Prompt**
> "Update the event from TC-CAL22 — change the description to 'Updated desc' and location to 'Room B'"

**Checks**
- `description` is `Updated desc`
- `location` is `Room B`
- Other fields (`summary`, `attendees`) unchanged

---

### TC-CAL27: Non-existent event ID

**Prompt**
> "Update event 'invalidEventId999xyz' in {CALENDAR_ID} — change the summary to 'Test'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `delete_event`

### TC-CAL28: Delete an existing event ⚠️ destructive

**Prompt**
> "Delete the event created in TC-CAL21 from {CALENDAR_ID}"

**Checks**
- Returns `{"calendar_id": "...", "event_id": "...", "action": "deleted"}`
- Event no longer appears in `list_events` for that date
- `calendar_cache.mark_dirty` called

---

### TC-CAL29: Non-existent event ID

**Prompt**
> "Delete event 'invalidEventId999xyz' from {CALENDAR_ID}"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- No side effects

---

## `find_free_slots`

### TC-CAL30: Single calendar — no events in window

**Prompt**
> "Find free slots for calendar {CALENDAR_ID} between 2026-07-04T00:00:00Z and 2026-07-04T23:59:59Z" *(use a date with no events)*

**Checks**
- `busy[{CALENDAR_ID}]` is an empty list
- `free_slots` covers the entire window as one slot: `[{start: time_min, end: time_max}]`

---

### TC-CAL31: Single calendar — events in window

**Prompt**
> "Find free slots for {CALENDAR_ID} on 2026-07-01 from 9am to 5pm PT" *(ensure TC-CAL20/25 events exist in this window)*

**Checks**
- `busy[{CALENDAR_ID}]` contains the event's `start` and `end` times
- `free_slots` shows the gaps before, between, and after busy periods
- `free_slots` start/end values are RFC 3339 strings

---

### TC-CAL32: Multiple calendar IDs

**Setup:** two calendars the service account has access to

**Prompt**
> "Find free slots across {CALENDAR_ID} and {CALENDAR_ID_2} for 2026-07-01 9am–5pm PT"

**Checks**
- `busy` has a key for each calendar ID
- `free_slots` reflects the union of all busy times — a slot is free only when all calendars are free
- No error if one calendar has no events (that calendar's busy list is just empty)

---

### TC-CAL33: Invalid calendar ID in list

**Prompt**
> "Find free slots for calendars [{CALENDAR_ID}, 'invalid-cal@example.com'] for the next hour"

**Checks**
- `busy["invalid-cal@example.com"]` contains an `error` entry (Calendar API errors-per-calendar)
- `busy[{CALENDAR_ID}]` is still populated correctly
- Top-level response is not an error — partial results returned

---

### TC-CAL34: free_slots covers full window when no busy times

**Prompt**
> "Find free slots for {CALENDAR_ID} between 2026-07-10T00:00:00Z and 2026-07-10T01:00:00Z" *(no events in this window)*

**Checks**
- `free_slots` is exactly `[{"start": "2026-07-10T00:00:00Z", "end": "2026-07-10T01:00:00Z"}]`
- Confirms the complement logic handles the empty-busy case

---

### TC-CAL35: Contiguous busy periods merged in free_slots

**Setup:** two back-to-back events with no gap (or overlapping events)

**Prompt**
> "Find free slots for {CALENDAR_ID} over a period with two adjacent events"

**Checks**
- The two busy periods are merged in the free slot calculation
- `free_slots` does not include a zero-length or negative-length gap between them
- Confirms the interval merge logic in `find_free_slots`

---
