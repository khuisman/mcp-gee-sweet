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
**Playwright: required**
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
**Playwright: required**
> "Create an all-day event called 'QA-AllDay-Test' in {CALENDAR_ID} on 2026-07-02"

**Checks**
- `start` and `end` in response are date strings (`2026-07-02`, `2026-07-03`)
- No `T` in the date values — confirms `date` field used, not `dateTime`
- Event appears in `list_events` for that day

---

### TC-CAL22: With description, location, and attendees ⚠️ destructive

**Prompt**
**Playwright: required**
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
**Playwright: required**
> "Update the event created in TC-CAL20 — change the title to 'QA-Timed-Updated'"

**Checks**
- `summary` in response is `QA-Timed-Updated`
- `start`, `end`, `location`, `description` unchanged (verify with `get_event`)
- `calendar_cache.mark_dirty` called

---

### TC-CAL25: Update start and end ⚠️ destructive

**Prompt**
**Playwright: required**
> "Update the event from TC-CAL20 — move it to 2026-07-01 from 2pm to 3pm PT"

**Checks**
- `start` and `end` reflect the new times
- `summary` and other fields unchanged

---

### TC-CAL26: Update description and location ⚠️ destructive

**Prompt**
**Playwright: required**
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
**Playwright: required**
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

## `create_event` — recurrence support

### TC-CAL36: Create a weekly recurring event ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a recurring event called 'QA-Weekly-Standup' in {CALENDAR_ID} every Monday from 9am to 9:30am Pacific time, starting 2026-07-07"

**Checks**
- Event created successfully
- Response includes `recurrence` field containing an RRULE string with `FREQ=WEEKLY` and `BYDAY=MO`
- `html_link` is present
- Verify with `get_event` that the master event's `recurrence` field is non-null
- Follow-up: `list_events(expand_recurring=True)` shows multiple Monday instances

**Result (2026-06-24) ✅** — Event created with `id: 3n4mjvi13au7fg1ce0np9ca73k`, `recurrence: ["RRULE:FREQ=WEEKLY;BYDAY=MO"]`, `status: confirmed`, `html_link` present. Confirmed master ID has no date suffix.

---

### TC-CAL37: Create a daily recurring event with COUNT limit ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a recurring event called 'QA-Daily-5x' in {CALENDAR_ID} every day at 8am Pacific for exactly 5 occurrences, starting 2026-07-14"

**Checks**
- Response `recurrence` contains `RRULE:FREQ=DAILY;COUNT=5`
- `list_events` with `expand_recurring=True` and appropriate time window returns exactly 5 instances
- No events appear after the 5th occurrence

**Result (2026-06-24) ✅** — Created with `recurrence: ["RRULE:FREQ=DAILY;COUNT=5"]`. `list_events(expand_recurring=True)` for Jul 14–19 returned exactly 5 instances (Jul 14–18). No Jul 19+ instances returned. Each instance had `recurrence: null`.

---

### TC-CAL38: Recurrence absent when not provided

**Prompt**
**Playwright: required**
> "Create a one-time event called 'QA-OneOff' in {CALENDAR_ID} on 2026-07-21 from 2pm to 3pm PT"

**Checks**
- Response `recurrence` is `null` (not set)
- `list_events(expand_recurring=False)` does not include this event as a recurring series
- Confirms non-recurring events are unaffected

**Result (2026-06-24) ✅** — Created with `recurrence: null`. Appears in `list_events(expand_recurring=False)` with `recurrence: null` — confirms one-off events are unaffected by recurrence logic.

---

## `list_events` — expand_recurring

### TC-CAL39: expand_recurring=False returns master events

**Setup:** use the recurring event created in TC-CAL36

**Prompt**
**Playwright: required**
> "List events in {CALENDAR_ID} with expand_recurring=False and no time filter"

**Checks**
- Response contains the master recurring event (not individual instances)
- Each recurring event has a `recurrence` field with RRULE strings
- The master event `id` does not contain an underscore + date suffix (instance IDs do)
- Non-recurring events also appear (one entry each)

**Result (2026-06-24) ✅** — `list_events(expand_recurring=False, query="QA-")` returned 3 items: QA-Weekly-Standup (recurrence: WEEKLY/MO), QA-Daily-5x (recurrence: DAILY/COUNT=5), QA-OneOff (recurrence: null). All master IDs had no date suffix. Confirms `singleEvents=False` path works correctly.

---

### TC-CAL40: expand_recurring=True (default) expands instances

**Setup:** use the recurring event created in TC-CAL36

**Prompt**
**Playwright: required**
> "List events in {CALENDAR_ID} between 2026-07-07T00:00:00Z and 2026-07-28T23:59:59Z"

**Checks**
- Response contains individual Monday instances (e.g. 4 Mondays in a 4-week window)
- Each instance `id` contains the base event ID plus a date suffix
- `recurrence` field is `null` on individual instances (it lives on the master)

**Result (2026-06-24) ✅** — Returned 4 instances (Jul 7, 13, 20, 27). Each ID had the `_YYYYMMDDTHHMMSSZ` suffix. `recurrence: null` on all instances. Note: Jul 7 is the original start date (Tuesday); the API kept it as the first instance and subsequent occurrences fell on Mondays per BYDAY=MO.

---

## `update_event` — recurrence support

### TC-CAL41: Update RRULE on a master event ⚠️ destructive

**Setup:** use the weekly recurring event from TC-CAL36; retrieve its master event ID via `list_events(expand_recurring=False)`

**Prompt**
> "Update the recurring event 'QA-Weekly-Standup' in {CALENDAR_ID} — change it from weekly to every 2 weeks"

**Checks**
- Response `recurrence` reflects the new RRULE (e.g. `RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO`)
- `list_events(expand_recurring=True)` for a 4-week window now returns 2 instances (not 4)
- Other fields (`summary`, `start`, `end`) are unchanged

**Result (2026-06-24) ✅** — Patched master with `recurrence: ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"]`. Response echoed the new RRULE. `list_events(expand_recurring=True)` for Jul 7–28 returned 2 instances (Jul 7 and Jul 20) vs 4 previously. `summary` and `start`/`end` unchanged.

---

### TC-CAL42: Remove recurrence by passing an empty list ⚠️ destructive

**Setup:** use the weekly recurring event from TC-CAL36 (master event ID)

**Prompt**
> "Update the master 'QA-Weekly-Standup' event in {CALENDAR_ID} and remove its recurrence to make it a one-off event — pass an empty recurrence list"

**Checks**
- Response `recurrence` is `null` or absent
- Event no longer appears as a series in `list_events(expand_recurring=False)`
- Only a single instance exists at the original start date

**Result (2026-06-24) ✅** — Patched master with `recurrence: []`. Response returned `recurrence: null`. `list_events(expand_recurring=False)` showed QA-Weekly-Standup with `recurrence: null` — one entry, no series. Only the Jul 7 occurrence remains.

---

### TC-CAL43: Update a single instance without affecting the series ⚠️ destructive

**Setup:** use the recurring event from TC-CAL37; get an instance event ID (contains date suffix) via `list_events(expand_recurring=True)`

**Prompt**
> "Update just the first occurrence of 'QA-Daily-5x' in {CALENDAR_ID} — rename it 'QA-Daily-5x (Modified)' using its instance event ID"

**Checks**
- That one instance has `summary: 'QA-Daily-5x (Modified)'`
- Other instances still have `summary: 'QA-Daily-5x'` (unchanged)
- The master event `summary` is unchanged (verify with `get_event` on the master ID)
- Confirms instance-level patching creates an exception override, not a series update

**Result (2026-06-24) ✅** — Patched instance `9lrphvbvegq03163gjh7fu35qo_20260714T150000Z` with `summary: 'QA-Daily-5x (Modified)'`. Jul 15–18 instances still returned `summary: 'QA-Daily-5x'`. `get_event` on master `9lrphvbvegq03163gjh7fu35qo` returned `summary: 'QA-Daily-5x'` and `recurrence: ["RRULE:FREQ=DAILY;COUNT=5"]` unchanged. Instance-level exception confirmed.

---
