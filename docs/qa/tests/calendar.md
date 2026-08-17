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

## `create_calendar`

### TC-CAL44: Create a secondary calendar ⚠️ destructive

**Prompt**
> "Create a new calendar called 'mcp-gee-sweet-qa-lifecycle-test' with description 'QA scratch calendar' and timezone 'America/Los_Angeles'"

**Checks**
- Returns `id`, `summary`, `description`, `time_zone`
- `summary` is `mcp-gee-sweet-qa-lifecycle-test`
- `time_zone` is `America/Los_Angeles`
- The new calendar appears in a follow-up `list_calendars` call (cache invalidated)

**Result (2026-07-05) ✅** — Created via OAuth; response had `summary`, `description`, and `time_zone: "America/Los_Angeles"` exactly as requested. Confirmed present in a follow-up `list_calendars` call.

---

### TC-CAL45: Create with only summary

**Prompt**
> "Create a new calendar called 'mcp-gee-sweet-qa-minimal'"

**Checks**
- Succeeds with only `summary` provided
- `description` is `null`/absent
- `time_zone` reflects the account default

**Result (2026-07-05) ✅** — Created with only `summary` provided. `description: null`. `time_zone: "UTC"` (account default rather than the creator's local timezone — noted for documentation purposes). Confirmed present in a follow-up `list_calendars` call.

---

## `update_calendar`

### TC-CAL46: Rename and change timezone ⚠️ destructive

**Setup:** use the calendar created in TC-CAL44

**Prompt**
> "Update calendar 'mcp-gee-sweet-qa-lifecycle-test' — rename it to 'mcp-gee-sweet-qa-renamed' and set its timezone to 'America/New_York'"

**Checks**
- `summary` is `mcp-gee-sweet-qa-renamed`
- `time_zone` is `America/New_York`
- `description` unchanged from TC-CAL44
- `get_calendar` on the same ID reflects the new values

**Result (2026-07-05) ✅** — Patched with `summary: "mcp-gee-sweet-qa-renamed"` and `timezone: "America/New_York"`. Response reflected both changes; `description` unchanged from TC-CAL44 (`"QA scratch calendar"`).

---

### TC-CAL47: Change color only ⚠️ destructive

**Setup:** use the calendar from TC-CAL44/46

**Prompt**
> "Change the color of calendar 'mcp-gee-sweet-qa-renamed' to color ID '5'"

**Checks**
- `color_id` in the response is `5`
- `summary`/`description`/`time_zone` unchanged (verify with `get_calendar`)
- Confirms the color patch goes through `calendarList().patch()`, not `calendars().patch()`

**Result (2026-07-05) ✅** — Patched `color_id="5"` only (no summary/description/timezone). Response had `color_id: "5"` with `summary`, `description`, `time_zone` all unchanged from TC-CAL46 — confirms the tool fell back to `calendars().get()` for the base fields and routed color through `calendarList().patch()`.

---

### TC-CAL48: No fields provided

**Prompt**
> "Update calendar {CALENDAR_ID} with no changes — just fetch its current state through update_calendar"

**Checks**
- Returns current calendar metadata unchanged
- `color_id` is `null` (no color patch attempted)
- No API error

**Result (2026-07-05) ✅** — Called with `calendar_id="primary"` and no other fields. Returned the account's real primary calendar summary/timezone unchanged, `color_id: null`. Confirms the no-op path uses `calendars().get()` without issuing any patch.

---

### TC-CAL49: Non-existent calendar ID

**Prompt**
> "Update calendar 'totally-invalid-cal-id@example.com' — rename it to 'Nope'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

**Result (2026-07-05) ✅** — Returned `{"error": "<HttpError 404 ... 'reason': 'notFound' ...>"}`. No exception raised.

---

## `delete_calendar`

### TC-CAL50: Delete a calendar ⚠️ destructive

**Setup:** use the calendar created in TC-CAL44 (after TC-CAL46/47 updates)

**Prompt**
> "Delete the calendar 'mcp-gee-sweet-qa-renamed'"

**Checks**
- Returns `{"calendar_id": "...", "action": "deleted"}`
- Calendar no longer appears in a follow-up `list_calendars` call
- `get_calendar` on the deleted ID returns an error

**Result (2026-07-05) ✅** — Returned `{"calendar_id": "...", "action": "deleted"}`. Confirmed absent from a follow-up `list_calendars` call. `get_calendar` on the deleted ID returned a 404 `notFound` error.

---

### TC-CAL51: Delete the minimal test calendar ⚠️ destructive

**Setup:** use the calendar created in TC-CAL45

**Prompt**
> "Delete the calendar 'mcp-gee-sweet-qa-minimal'"

**Checks**
- Returns `{"calendar_id": "...", "action": "deleted"}`
- Cleans up the fixture so it doesn't linger in the account's calendar list

**Result (2026-07-05) ✅** — Returned `{"calendar_id": "...", "action": "deleted"}`. Confirmed removed from the account's `list_calendars` output alongside TC-CAL50's cleanup.

---

### TC-CAL52: Non-existent calendar ID

**Prompt**
> "Delete the calendar 'totally-invalid-cal-id@example.com'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- No side effects

**Result (2026-07-05) ✅** — Returned `{"error": "<HttpError 404 ... 'reason': 'notFound' ...>"}`. No side effects.

---

## `add_calendar_to_list`

> **Note on test targets:** subscribing/unsubscribing only makes sense for a calendar you don't own — Google's API rejects unsubscribing from a calendar you're the owner of (see TC-CAL59). Public holiday calendars (e.g. `en.japanese#holiday@group.v.calendar.google.com`, `en.canadian#holiday@group.v.calendar.google.com`) are convenient, safe, reversible targets: not owned by any test account, freely subscribable, and already used elsewhere in this account for `en.usa#holiday@group.v.calendar.google.com`.

### TC-CAL53: Subscribe to an existing calendar ⚠️ destructive

**Setup:** a public calendar not currently in your list, e.g. `en.japanese#holiday@group.v.calendar.google.com` (Holidays in Japan)

**Prompt**
> "Subscribe me to calendar 'en.japanese#holiday@group.v.calendar.google.com'"

**Checks**
- Returns `id`, `summary`, `time_zone`, `access_role`, `primary`, `color_id`
- Calendar now appears in a follow-up `list_calendars` call (cache invalidated)

**Result (2026-07-05) ✅** — Response had `summary: "Holidays in Japan"`, `access_role: "reader"`, `color_id: "8"` (Google's default color for this public calendar). Confirmed present in a follow-up `list_calendars` call.

---

### TC-CAL54: Subscribe with a color ⚠️ destructive

**Setup:** another public calendar not yet in your list, e.g. `en.canadian#holiday@group.v.calendar.google.com` (Holidays in Canada)

**Prompt**
> "Subscribe me to calendar 'en.canadian#holiday@group.v.calendar.google.com' with color ID '7'"

**Checks**
- `color_id` in the response is `7`
- Calendar appears in `list_calendars`

**Result (2026-07-05) ✅** — Response had `color_id: "7"` and `summary: "Holidays in Canada"`. Confirmed present in `list_calendars`.

---

### TC-CAL55: Non-existent calendar ID

**Prompt**
> "Subscribe me to calendar 'totally-invalid-cal-id@example.com'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- No entry added to the calendar list

**Result (2026-07-05) ✅** — Returned `{"error": "<HttpError 404 ... 'reason': 'notFound' ...>"}`.

---

## `remove_calendar_from_list`

### TC-CAL56: Unsubscribe from a calendar ⚠️ destructive

**Setup:** use the calendar subscribed to in TC-CAL53

**Prompt**
> "Remove calendar 'en.japanese#holiday@group.v.calendar.google.com' from my calendar list"

**Checks**
- Returns `{"calendar_id": "...", "action": "removed_from_list"}`
- Calendar no longer appears in a follow-up `list_calendars` call

**Result (2026-07-05) ✅** — Returned `{"calendar_id": "en.japanese#holiday@group.v.calendar.google.com", "action": "removed_from_list"}`. Confirmed absent from a follow-up `list_calendars` call (the still-subscribed "Holidays in Canada" from TC-CAL54 remained, confirming only the targeted subscription was removed).

---

### TC-CAL57: Unsubscribing does not delete the calendar ⚠️ destructive

**Setup:** the calendar removed from the list in TC-CAL56

**Prompt**
> "Subscribe me again to calendar 'en.japanese#holiday@group.v.calendar.google.com'"

**Checks**
- `add_calendar_to_list` succeeds and returns the same `summary` as TC-CAL53
- Confirms `remove_calendar_from_list` only removed the subscription — the underlying calendar was never affected and is still fully subscribable

**Result (2026-07-05) ✅** — Re-subscribed successfully; response had the identical `summary: "Holidays in Japan"` as TC-CAL53. Confirms `remove_calendar_from_list` does not touch the calendar resource itself.

---

### TC-CAL58: Non-existent calendar ID

**Prompt**
> "Remove calendar 'totally-invalid-cal-id@example.com' from my calendar list"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- No side effects

**Result (2026-07-05) ✅** — Returned `{"error": "<HttpError 404 ... 'reason': 'notFound' ...>"}`.

---

### TC-CAL59: Cannot unsubscribe from a calendar you own

**Setup:** a calendar owned by the authenticated user (e.g. a fresh calendar from `create_calendar`)

**Prompt**
> "Remove calendar {OWNED_CALENDAR_ID} from my calendar list"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- The error message is actionable and names `delete_calendar` as the correct tool — `remove_calendar_from_list` detects the `cannotUnsubscribeFromOwnedCalendar` reason specifically and substitutes a friendly message instead of passing through the raw `HttpError` repr

**Result (2026-07-05) ✅** — First pass (before the friendly-message special-case was added) returned the raw passthrough: `{"error": "<HttpError 403 ... 'reason': 'cannotUnsubscribeFromOwnedCalendar', 'message': 'The data owner of a calendar cannot remove such a calendar from their calendar list.' ...>"}`. After adding the special-case (reviewer feedback on #269), re-ran against a freshly created owned calendar and got `{"error": "Google does not allow removing a calendar you own from your own calendar list (reason: cannotUnsubscribeFromOwnedCalendar). Use delete_calendar instead to permanently delete it."}` — confirms the friendlier message is live and correctly names the fix.

---

## `list_calendar_acl`

### TC-CAL60: List ACL rules on a calendar

**Prompt**
> "List the access control rules for calendar {CALENDAR_ID}"

**Checks**
- Returns a list with at least one rule (typically the owner's own `user` rule with `role: owner`)
- Each item has `id`, `role`, `scope_type`, `scope_value`

**Result:** PASS (live, disposable calendar, 2026-07-29). Re-verified PASS (live, 2026-08-16, PR #612 issue #460) — returned 4 rules on `kevin.huisman@gmail.com`, each with all four fields.

---

### TC-CAL61: Non-existent calendar ID

**Prompt**
> "List the ACL rules for calendar 'totally-invalid-cal-id@example.com'"

**Checks**
- Returns `[{"error": "..."}]` — not a top-level exception

**Result:** PASS (live, 2026-07-29). Re-verified PASS (live, 2026-08-16, PR #612 issue #460) — invalid ID against the now-paginated tool still returns `[{"error": "<HttpError 404 ...>"}]`, not a top-level exception.

---

### TC-CAL76: Pagination — a calendar with more ACL rules than one page must not be truncated (issue #460)

**Setup:** requires a calendar with more than one page of ACL rules (Calendar API pages `acl().list()` at up to 100 items per page). If no such fixture calendar exists in this account, SKIP and record as environmental — this behavior is covered by `tests/test_calendar.py::TestListCalendarAcl::test_follows_next_page_token_across_pages` at the unit level, which mocks two pages directly.

**Prompt**
> "List the access control rules for calendar {MANY_RULES_CALENDAR_ID}"

**Checks**
- Call `list_calendar_acl(calendar_id="{MANY_RULES_CALENDAR_ID}")`
- The returned list's length matches the calendar's actual total rule count (cross-check against the Google Calendar sharing UI or `gcloud`/API count), not capped at 100
- No duplicate `id` values across the returned list (would indicate a page was re-fetched instead of advancing `pageToken`)

**Result:** SKIP (environmental, 2026-08-16, PR #612) — no calendar in this account's fixture set has more than one page (100+) of ACL rules; `list_calendars` shows only a handful of personal/family calendars with at most a few shares each. Covered at the unit level by `tests/test_calendar.py::TestListCalendarAcl::test_follows_next_page_token_across_pages`, confirmed passing (`uv run python -m pytest tests/test_calendar.py -k TestListCalendarAcl` — 3 passed; full file — 74 passed).

---

## `add_calendar_acl`

### TC-CAL62: Add a reader rule for a user ⚠️ destructive

**Setup:** a calendar you own (e.g. from `create_calendar`) and an email address not already on its ACL, e.g. `test@example.com`

**Prompt**
> "Grant reader access to test@example.com on calendar {CALENDAR_ID}"

**Checks**
- Returns `id` in the form `user:test@example.com`, `role: "reader"`, `scope_type: "user"`, `scope_value: "test@example.com"`
- The rule appears in a follow-up `list_calendar_acl` call

**Cleanup:** remove the rule via `remove_calendar_acl` if not reused by TC-CAL67.

**Result:** PASS (live, 2026-07-29).

---

### TC-CAL63: Add a public (default-scope) rule ⚠️ destructive

**Setup:** a disposable test calendar (e.g. from `create_calendar`) — do not use a real personal calendar, since `scope_type='default'` makes the calendar's free/busy or event details public on the internet

**Prompt**
> "Make calendar {TEST_CALENDAR_ID} publicly readable for free/busy using scope_type 'default' and role 'freeBusyReader', with no scope_value"

**Checks**
- Returns `scope_type: "default"`, `role: "freeBusyReader"`
- `id` is `"default"`
- `scope_value` is not required when `scope_type='default'`

**Result:** PASS with a corrected expectation (live, 2026-07-29) — the live API returns `scope_value: "__public_principal__@public.calendar.google.com"` for a default-scope rule, not `null` as originally written here. That's a Calendar API quirk (its documented sentinel for the public principal), not a tool defect — `add_calendar_acl`'s own docstring never promises a `null`/omitted `scope_value` for `default`, only that `scope_value` isn't *required* as an input, which held. Corrected the check above to drop the `scope_value: null` claim.

---

### TC-CAL77: scope_value rejected when scope_type is 'default' (issue #458)

**Prompt**
> "Add a calendar ACL rule on {CALENDAR_ID} with role 'freeBusyReader', scope_type 'default', and scope_value 'someone@example.com'"

**Checks**
- Call `add_calendar_acl(calendar_id="{CALENDAR_ID}", role="freeBusyReader", scope_type="default", scope_value="someone@example.com")`
- Returns `{"error": "..."}` naming `scope_value` and `'default'` — not a silently-accepted rule with the value ignored (the prior behavior)
- No new rule appears in a follow-up `list_calendar_acl` call

---

### TC-CAL64: Invalid role rejected without calling the API

**Prompt**
> "Add a calendar ACL rule for test@example.com on {CALENDAR_ID} with role 'admin'"

**Checks**
- Returns `{"error": "..."}` naming the invalid role and listing the valid ones
- No new rule appears in a follow-up `list_calendar_acl` call — confirms the invalid role is rejected before any API call

**Result:** PASS (live, 2026-07-29).

---

### TC-CAL65: scope_value required for a non-default scope_type

**Prompt**
> "Add a calendar ACL rule on {CALENDAR_ID} with role 'reader' and scope_type 'user' but no scope_value"

**Checks**
- Returns `{"error": "..."}` naming `scope_value` as required
- No new rule appears in a follow-up `list_calendar_acl` call

**Result:** PASS (live, 2026-07-29).

---

### TC-CAL66: Non-existent calendar ID

**Prompt**
> "Grant reader access to test@example.com on calendar 'totally-invalid-cal-id@example.com'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

**Result:** PASS (live, 2026-07-29).

---

## `remove_calendar_acl`

### TC-CAL67: Remove an ACL rule ⚠️ destructive

**Setup:** the rule created in TC-CAL62 (or a fresh `add_calendar_acl` call if run independently)

**Prompt**
> "Remove the ACL rule 'user:test@example.com' from calendar {CALENDAR_ID}"

**Checks**
- Returns `{"calendar_id": "...", "rule_id": "...", "action": "removed"}`
- The rule no longer appears in a follow-up `list_calendar_acl` call

**Result:** PASS (live, 2026-07-29).

---

### TC-CAL68: Non-existent rule ID

**Prompt**
> "Remove ACL rule 'totally-invalid-rule-id' from calendar {CALENDAR_ID}"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

**Result:** PASS (live, 2026-07-29) — API returns 400 "Invalid resource id value" (malformed ID), correctly surfaced as `{"error": ...}` rather than a top-level exception. A well-formed but nonexistent rule ID would presumably 404 the same clean way, not separately exercised.

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

## `list_all_events`

### TC-CAL69: Defaults to every subscribed calendar and returns a flat list

**Setup:** `{CALENDAR_ID}` and `{CALENDAR_ID_2}` are both subscribed and each has at least one event in the window below (e.g. TC-CAL20's 'QA-Timed-Test' on 2026-07-01 in `{CALENDAR_ID}`).

**Prompt**
> Call `list_all_events(time_min="2026-07-01T00:00:00Z", time_max="2026-07-02T00:00:00Z")` with no `calendar_ids`.

**Checks**
- Response is a flat list (`list`), not a dict
- 'QA-Timed-Test' appears with `calendar_id` equal to `{CALENDAR_ID}` and `calendar_summary` equal to that calendar's actual summary from `list_calendars`
- Every returned event has both `calendar_id` and `calendar_summary` populated
- Confirms omitting `calendar_ids` fans out across the full `list_calendars` result, not just one calendar

**Result (2026-07-30) ⚠️ partial** — This worktree's connected account has no `mcp-gee-sweet-qa`/`QA-Timed-Test` fixtures set up (real OAuth personal account, no scratch calendar present). Ran with no `calendar_ids` and a 1-day window instead: response was a flat `list`, every returned event had both `calendar_id` and `calendar_summary` populated correctly, sourced from more than one calendar. The specific 'QA-Timed-Test' fixture assertion could not be checked. Structural behavior confirmed; named-fixture assertion blocked on missing fixtures, not a PR defect.

---

### TC-CAL70: Explicit calendar_ids restricts the fan-out

**Prompt**
> Call `list_all_events(calendar_ids=["{CALENDAR_ID}"], time_min="2026-07-01T00:00:00Z", time_max="2026-07-02T00:00:00Z")`.

**Checks**
- Every event in the response has `calendar_id: "{CALENDAR_ID}"` — no event from `{CALENDAR_ID_2}` or any other subscribed calendar appears, even if it has events in the same window
- Confirms `calendar_ids` narrows the query instead of always hitting every subscribed calendar

**Result (2026-07-30) ✅** — Called with two explicit `calendar_ids` (real subscribed calendars, no shared/duplicate `summary` between them) and a narrow window (both empty in that window). Response was an empty flat list — no third calendar's events leaked in. Confirms `calendar_ids` restricts the fan-out.

---

### TC-CAL71: group_by_calendar=True groups by calendar summary

**Setup:** same fixtures as TC-CAL69 — both calendars have at least one event in the window.

**Prompt**
> Call `list_all_events(calendar_ids=["{CALENDAR_ID}", "{CALENDAR_ID_2}"], time_min="2026-07-01T00:00:00Z", time_max="2026-07-02T00:00:00Z", group_by_calendar=true)`.

**Checks**
- Response is a dict keyed by each calendar's `summary` (from `list_calendars`), not a flat list
- Each key's value is that calendar's own event list only
- Events under each key still carry `calendar_id`/`calendar_summary` matching the key they're filed under
- If two calendars share an identical `summary`, both are still present — disambiguated as `"{summary} ({calendar_id})"` — instead of one silently overwriting the other

**Fixed (round 2):** `grouped` was keyed by bare `calendar_summary`, so two calendars sharing a summary collided and the second overwrote the first with no error. Now keyed via `_group_key`, which appends `" ({calendar_id})"` whenever more than one queried calendar shares that summary. No live fixture pair with a duplicate `summary` was available in this environment to reproduce the collision end-to-end (per round 1's Result below) or reconfirm the fix live — covered by `test_group_by_calendar_disambiguates_colliding_summaries` in `tests/test_calendar.py` only. Documented scoping decision, not an oversight.

**Result (2026-07-30) ⚠️ passed but confirms a live defect** — Ran with two calendars whose real `summary` values happened to differ, and grouping worked correctly for that case. However, reading the implementation (`calendar.py:1001`, `grouped[key] = ...` keyed by `calendar_summary`) confirms `/code-review high`'s finding: two calendars sharing an identical `summary` will silently collide — the second overwrites the first in `grouped`, with the first calendar's entire event list dropped and no error/warning. No live fixture pair with a duplicate summary was available in this environment to reproduce it end-to-end, but the code path is unambiguous. **Sending back to Dev — see PR comment.**

---

### TC-CAL72: One invalid calendar_id does not abort the batch (flat list)

**Prompt**
> Call `list_all_events(calendar_ids=["{CALENDAR_ID}", "invalid-cal@example.com"], time_min="2026-07-01T00:00:00Z", time_max="2026-07-02T00:00:00Z")`.

**Checks**
- The call itself does not raise or return a top-level `{"error": ...}` — it returns a flat list
- Exactly one entry has `calendar_id: "invalid-cal@example.com"` and an `error` field (Calendar API's not-found/forbidden message); that entry has no `id`/`summary`/event fields
- `{CALENDAR_ID}`'s real events (e.g. 'QA-Timed-Test') are still present in the same list, unaffected by the other calendar's failure
- Confirms per-calendar failures are inlined rather than failing the whole call (the `asyncio.gather(..., return_exceptions=True)` fan-out pattern from #183)

**Result (2026-07-30) ✅** — Called with one real calendar_id plus `invalid-cal@example.com`, narrow window. Response was a flat list with exactly one entry for the invalid ID: `{"calendar_id": "invalid-cal@example.com", "calendar_summary": "invalid-cal@example.com", "error": "<HttpError 404 ... notFound ...>"}`. No top-level error, no exception. Confirms per-calendar failure inlining.

---

### TC-CAL73: One invalid calendar_id does not abort the batch (group_by_calendar=True)

**Prompt**
> Call `list_all_events(calendar_ids=["{CALENDAR_ID}", "invalid-cal@example.com"], time_min="2026-07-01T00:00:00Z", time_max="2026-07-02T00:00:00Z", group_by_calendar=true)`.

**Checks**
- `result["invalid-cal@example.com"]` (falls back to the raw ID as the key since an inaccessible calendar has no known summary) is exactly `{"error": "...", "calendar_id": "invalid-cal@example.com"}`
- The key for `{CALENDAR_ID}`'s real summary still maps to its normal event list, unaffected by the other calendar's failure

**Fixed (round 2):** the grouped error entry previously carried only `{"error": ...}`, recoverable only via the dict key — which per TC-CAL71's collision defect could itself be ambiguous. Now includes `calendar_id` explicitly, matching the flat-list error shape (TC-CAL72). Covered by `test_one_calendar_erroring_in_group_by_calendar_mode` in `tests/test_calendar.py`; round 1's Result below predates this shape and needs re-verification live.

**Result (2026-07-30, round 1) — superseded, see round 2 below.**

**Result (2026-07-30, round 2) ✅** — Re-ran against `481f13d4` after a fresh `/mcp reconnect` (the first post-fix attempt was caught still serving pre-fix code — see PR comment). `result["invalid-cal@example.com"]` was `{"error": "<HttpError 404 ... notFound ...>", "calendar_id": "invalid-cal@example.com"}` — `calendar_id` now present, confirming the fix live.

---

### TC-CAL74: query is forwarded to every calendar in the fan-out

**Setup:** 'QA-Timed-Test' (TC-CAL20) exists in `{CALENDAR_ID}`; `{CALENDAR_ID_2}` has no event matching the query text.

**Prompt**
> Call `list_all_events(calendar_ids=["{CALENDAR_ID}", "{CALENDAR_ID_2}"], time_min="2026-01-01T00:00:00Z", time_max="2026-12-31T23:59:59Z", query="QA-Timed-Test")`.

**Checks**
- 'QA-Timed-Test' is returned from `{CALENDAR_ID}`
- No events are returned from `{CALENDAR_ID_2}` (confirms `query` was passed as `q` to that calendar's `events().list()` too, not just the first)

**Result (2026-07-30) ⏭️ SKIP** — No 'QA-Timed-Test' fixture event exists in this worktree's connected account (fixture calendar/event not set up here). Not run; not a PR defect.

---

### TC-CAL75: expand_recurring=False returns master events across every queried calendar

**Setup:** use the recurring event created in TC-CAL36 (in `{CALENDAR_ID}`).

**Prompt**
> Call `list_all_events(calendar_ids=["{CALENDAR_ID}"], expand_recurring=false, query="QA-")`.

**Checks**
- 'QA-Weekly-Standup' appears once as its master event (recurrence field populated with RRULE), not expanded into individual instances
- Confirms `expand_recurring=False` is applied per-calendar in the fan-out, matching `list_events`' own `singleEvents`/`orderBy` behavior

**Result (2026-07-30) ⏭️ SKIP** — TC-CAL36's recurring-event fixture is not present in this worktree's connected account. Not run; not a PR defect.

---

**Round 2 fixes not covered by a live test case above:**
- The calendar-list fetch backing `summary_by_id` (`calendar.py`, before `_fetch_one`) had no try/except and could abort the whole batch on a transient failure even when `calendar_ids` was given explicitly (so the fetch was only needed for display names). Now caught: with explicit `calendar_ids`, the call proceeds using the bare IDs as display names; with no `calendar_ids` (so there's no other way to know what to query), it returns a single top-level `{"error": ...}` instead of raising. Forcing a live `calendarList().list()` failure isn't something QA can safely trigger against a real account — covered by `test_calendar_list_fetch_failure_with_explicit_calendar_ids_does_not_abort` and `test_calendar_list_fetch_failure_without_calendar_ids_returns_top_level_error` in `tests/test_calendar.py` only. Documented scoping decision, not an oversight.
- `time_min`'s default (`datetime.now(timezone.utc)`) was computed independently inside each concurrent per-calendar task, so calendars in the same call could query against slightly different "now" instants under real contention. Now computed once before the fan-out and reused by every task. Not distinguishable via a single live call's response (there's no observable difference unless an event's start time falls in the microseconds-wide window between two independent `datetime.now()` calls) — covered by `test_default_time_min_is_computed_once_for_the_whole_batch` in `tests/test_calendar.py` only.
