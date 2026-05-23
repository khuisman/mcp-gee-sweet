# Fixture Setup

Run the seed prompt below once against your MCP server. It creates a spreadsheet and a doc with known data that all test cases reference. Record the resulting IDs in `fixtures.local.md`.

## Seed prompt

Paste this into Claude with your MCP server connected:

---

> Set up my QA fixtures for mcp-gee-sweet. Please do all of the following in order:
>
> 1. Create a spreadsheet called **"mcp-gee-sweet-qa-fixtures"** in my default folder.
> 2. Rename the first sheet to **"Sales"** and populate it with:
>    - Row 1 (headers): Product, Q1, Q2, Q3
>    - Row 2: Widget, 100, 120, 140
>    - Row 3: Gadget, 200, 180, 220
>    - Row 4: Donut, 50, 60, 55
>    - Row 5: Gizmo, 300, 310, 290
>    - Row 6: Totals, =SUM(B2:B5), =SUM(C2:C5), =SUM(D2:D5)
> 3. Add a second sheet called **"Empty"** — leave it completely blank.
> 4. Add a third sheet called **"Notes & Misc"** with:
>    - Row 1 (headers): Date, Note
>    - Row 2: =TODAY(), Setup complete
> 5. Create a Google Doc called **"mcp-gee-sweet-qa-fixtures-doc"** with this content:
>    `<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>`
>
> When done, give me the spreadsheet ID and the doc ID.

---

## Known fixture state

| Sheet | Row | A | B | C | D |
|---|---|---|---|---|---|
| Sales | 1 | Product | Q1 | Q2 | Q3 |
| Sales | 2 | Widget | 100 | 120 | 140 |
| Sales | 3 | Gadget | 200 | 180 | 220 |
| Sales | 4 | Donut | 50 | 60 | 55 |
| Sales | 5 | Gizmo | 300 | 310 | 290 |
| Sales | 6 | Totals | =SUM(B2:B5) | =SUM(C2:C5) | =SUM(D2:D5) |
| Empty | — | _(blank)_ | | | |
| Notes & Misc | 1 | Date | Note | | |
| Notes & Misc | 2 | =TODAY() | Setup complete | | |

Doc content: `<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>`

## After running

Record both IDs in `fixtures.local.md` (copy from `fixtures.template.md`).

---

## Calendar fixture setup

Calendar tests require a calendar the service account can access. The service account cannot see calendars shared only with your personal account — it must be explicitly subscribed.

**Seed prompt** (paste with MCP server connected):

---

> Set up my calendar QA fixtures for mcp-gee-sweet. Please do all of the following:
>
> 1. Call `list_calendars` — if a calendar called **"mcp-gee-sweet-qa"** already appears, skip to step 3.
> 2. I will share my primary Google Calendar with the service account email manually in Google Calendar settings (Settings → Share with specific people). Once done, tell me to proceed.
> 3. Create a test event in that calendar: title **"QA Test Event"**, tomorrow at 10:00–11:00 AM in my local timezone.
> 4. Return the calendar ID and the event ID.

---

Record `CALENDAR_ID` and `EVENT_ID` in `fixtures.local.md`.

> **Note:** If the service account still can't see the calendar after sharing, you may need to subscribe it manually. See the `Calendar API setup` memory entry for the `calendarList().insert()` workaround.

---

## Resetting fixtures

Re-run the seed prompt to get a fresh spreadsheet. Update `fixtures.local.md` with the new IDs before continuing.
