# Calendar Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/calendar.py`

Fixtures: substitute `{CALENDAR_ID}` with your calendar ID (typically your Gmail address).
TC-CAL10 through TC-CAL12 create and mutate events — run these after read-only tests, and clean up created events afterward.

---

## `list_calendars`

### TC-CAL01: List all calendars

**Prompt**
> "List all my calendars"

**Checks**
- Returns a list of calendars
- Each item has `id`, `summary`, `time_zone`, `access_role`
- At least one calendar has `primary: true`

---

## `get_calendar`

### TC-CAL02: Get calendar by ID

**Prompt**
> "Get details for calendar {CALENDAR_ID}"

**Checks**
- Returns `summary`, `time_zone`, `access_role`
- `id` matches `{CALENDAR_ID}`

---

### TC-CAL03: Get primary calendar

**Prompt**
> "Get the primary calendar"

**Checks**
- Returns calendar metadata without error
- `primary: true` in response

---

### TC-CAL04: Non-existent calendar ID

**Prompt**
> "Get details for calendar notarealid@example.com"

**Checks**
- Returns `{"error": ...}`
- No exception propagated to the user

---

## `list_events`

### TC-CAL05: List events in a time window

**Prompt**
> "List events on calendar {CALENDAR_ID} from 2026-05-22T00:00:00Z to 2026-06-01T00:00:00Z"

**Checks**
- Returns list of events ordered by start time
- Each event has `id`, `summary`, `start`, `end`, `status`
- Events outside the window are absent

---

### TC-CAL06: Search events by query

**Prompt**
> "Find events on {CALENDAR_ID} containing 'birthday' in the next 90 days"

**Checks**
- Only events matching the search term returned
- `query` parameter passed to API

---

### TC-CAL07: All-day event format

**Setup:** ensure a known all-day event exists on the calendar.

**Prompt**
> "List events on {CALENDAR_ID} around {ALL_DAY_EVENT_DATE}"

**Checks**
- `start` and `end` are date strings (no `T`), e.g. `"2026-05-26"`
- No `dateTime` field in response

---

### TC-CAL08: max_results clamping

**Prompt**
> "List up to 3000 events on {CALENDAR_ID} for the next year"

**Checks**
- At most 2500 events returned (API cap enforced)

---

## `get_event`

### TC-CAL09: Get a specific event

**Setup:** pick a known `{EVENT_ID}` from TC-CAL05 results.

**Prompt**
> "Get event {EVENT_ID} from calendar {CALENDAR_ID}"

**Checks**
- Returns full event: `id`, `summary`, `start`, `end`, `organizer`, `attendees`, `status`
- `attendees` is a list of `{email, response}` objects

---

## `create_event`, `update_event`, `delete_event`

### TC-CAL10: Create a timed event

**Prompt**
> "Create an event called 'QA Test Event' on {CALENDAR_ID} from 2026-06-01T10:00:00-07:00 to 2026-06-01T11:00:00-07:00 with description 'automated QA test'"

**Checks**
- Returns `id`, `summary`, `start`, `end`, `html_link`
- `summary` is `"QA Test Event"`
- `html_link` is a valid Google Calendar URL
- Event appears when listing that time window

---

### TC-CAL11: Update the created event

**Setup:** use `{EVENT_ID}` from TC-CAL10.

**Prompt**
> "Update event {EVENT_ID} on {CALENDAR_ID} — change the summary to 'QA Test Event (updated)' and location to 'Remote'"

**Checks**
- Returned `summary` is `"QA Test Event (updated)"`
- `get_event` confirms `location` is `"Remote"`
- Fields not included in patch are unchanged

---

### TC-CAL12: Delete the created event

**Setup:** use `{EVENT_ID}` from TC-CAL10.

**Prompt**
> "Delete event {EVENT_ID} from calendar {CALENDAR_ID}"

**Checks**
- Returns `{"deleted": true}`
- Subsequent `get_event` for the same ID returns `{"error": ...}`

---

## `find_free_slots`

### TC-CAL13: Find busy periods for one calendar

**Prompt**
> "Find busy times on {CALENDAR_ID} from 2026-05-22T00:00:00Z to 2026-05-23T00:00:00Z"

**Checks**
- Returns `time_min`, `time_max`, and `busy` map
- `busy` has a key matching `{CALENDAR_ID}`
- Each busy period has `start` and `end` RFC3339 strings

---

### TC-CAL14: Window with no events

**Prompt**
> "Find busy times on {CALENDAR_ID} from 2030-01-01T00:00:00Z to 2030-01-02T00:00:00Z"

**Checks**
- `busy[{CALENDAR_ID}]` is an empty list
- No error returned
