# Chart Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/charts.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}` from `fixtures.local.md`.

All chart tests use the Sales sheet (`A1:D6`) as the data range. Charts are additive — they don't mutate cell data — so fixture reset is generally not needed. However, added charts accumulate on the sheet across test runs.

---

## `add_chart`

### TC-C01: COLUMN chart

**Prompt**
**Playwright: required**
> "Add a column chart to the Sales sheet of {SPREADSHEET_ID} using data range A1:D5 with title 'Sales by Quarter'"

**Checks**
- Chart appears on the Sales sheet
- Response includes a `chartId`
- Chart type is COLUMN

**Result (2026-08-15) ✅ PASS** — `add_chart` returned `chartId: 1767578399`, `basicChart.chartType: COLUMN`. Playwright screenshot of the Sales sheet confirms the "Sales by Quarter" column chart rendered correctly with Q1/Q2/Q3 series grouped by product.

---

### TC-C02: BAR chart

**Prompt**
> "Add a bar chart to the Sales sheet of {SPREADSHEET_ID} using data range A1:D5"

**Checks**
- Chart added with BAR type
- Response includes `chartId`

---

### TC-C03: LINE chart

**Prompt**
> "Add a line chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- LINE chart added
- Response includes `chartId`

---

### TC-C04: AREA chart

**Prompt**
> "Add an area chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- AREA chart added
- Response includes `chartId`

---

### TC-C05: PIE chart

**Prompt**
> "Add a pie chart to the Sales sheet of {SPREADSHEET_ID} using range A1:B5 (Product and Q1 columns only)"

**Checks**
- PIE chart added
- Response includes `chartId`
- Pie chart code path taken (no axis/domain/series splitting)

---

### TC-C06: SCATTER chart

**Prompt**
> "Add a scatter chart to the Sales sheet of {SPREADSHEET_ID} using range B1:C5"

**Checks**
- SCATTER chart added
- Response includes `chartId`

---

### TC-C07: COMBO chart

**Prompt**
> "Add a combo chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- COMBO chart added
- Response includes `chartId`

---

### TC-C08: HISTOGRAM chart

**Prompt**
> "Add a histogram chart to the Sales sheet of {SPREADSHEET_ID} using range B2:B5 (Q1 values)"

**Checks**
- HISTOGRAM chart added
- Response includes `chartId`

---

### TC-C09: Invalid chart type

**Prompt**
> "Add a 'DONUT' chart to the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` before calling the API
- Error message references the invalid chart type
- No API call made

---

### TC-C10: Lowercase chart type input

**Prompt**
> "Add a 'column' chart (lowercase) to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- Chart created successfully — `.upper()` normalized 'column' → 'COLUMN'
- Response includes `chartId`

---

### TC-C11: Sheet not found

**Prompt**
> "Add a column chart to a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` — sheet not found
- No API call made

---

### TC-C12: Custom position and size

**Prompt**
**Playwright: required**
> "Add a line chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5, positioned at x=100, y=200, width=400, height=300"

**Checks**
- Chart added with the specified `overlayPosition` values
- Response includes `chartId`
- 🔍 **Product decision:** are position/size values in pixels or grid units? Note what the API accepts
