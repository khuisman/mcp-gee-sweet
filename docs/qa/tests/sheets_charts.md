# Chart Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/charts.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}` from `fixtures.local.md`.

All chart tests use the Sales sheet (`A1:D6`) as the data range. Charts are additive — they don't mutate cell data — so fixture reset is generally not needed. Every test case that successfully creates a chart has a **Cleanup** step deleting it via `batch_update` with a `deleteEmbeddedObject` request against the returned `chartId`, so a full run leaves the Sales sheet exactly as it started.

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

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-08-15) ✅ PASS** — `add_chart` returned `chartId: 1767578399`, `basicChart.chartType: COLUMN`. Playwright screenshot of the Sales sheet confirms the "Sales by Quarter" column chart rendered correctly with Q1/Q2/Q3 series grouped by product.

**Result (2026-09-04) ✅ PASS**
add_chart(COLUMN, A1:D5, title="Sales by Quarter") → chartId 77030586, basicChart.chartType COLUMN. Deleted after

---

### TC-C02: BAR chart

**Prompt**
> "Add a bar chart to the Sales sheet of {SPREADSHEET_ID} using data range A1:D5"

**Checks**
- Chart added with BAR type
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-08-19) ✅ PASS** — `add_chart` returned `chartId: 1421396281`, `basicChart.chartType: BAR`. Cleanup via `batch_update`/`deleteEmbeddedObject` succeeded; Playwright screenshot of the Sales sheet before chart creation and after cleanup are pixel-identical (no leftover chart, no cell-data drift) — confirms the new Cleanup step actually restores the sheet to its pre-test state.

**Result (2026-09-04) ✅ PASS**
add_chart(BAR, A1:D5) → chartId 82345835, chartType BAR. Deleted after

---

### TC-C03: LINE chart

**Prompt**
> "Add a line chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- LINE chart added
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(LINE, A1:D5) → chartId 1210688378, chartType LINE. Deleted after

---

### TC-C04: AREA chart

**Prompt**
> "Add an area chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- AREA chart added
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(AREA, A1:D5) → chartId 1920190609, chartType AREA. Deleted after

---

### TC-C05: PIE chart

**Prompt**
> "Add a pie chart to the Sales sheet of {SPREADSHEET_ID} using range A1:B5 (Product and Q1 columns only)"

**Checks**
- PIE chart added
- Response includes `chartId`
- Pie chart code path taken (no axis/domain/series splitting)

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(PIE, A1:B5) → chartId 132308391, response uses "pieChart" key (dedicated pie code path, not basicChart w/ axis/domain splitting). Deleted after

---

### TC-C06: SCATTER chart

**Prompt**
> "Add a scatter chart to the Sales sheet of {SPREADSHEET_ID} using range B1:C5"

**Checks**
- SCATTER chart added
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(SCATTER, B1:C5) → chartId 1210711819, chartType SCATTER. Deleted after

---

### TC-C07: COMBO chart

**Prompt**
> "Add a combo chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- COMBO chart added
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(COMBO, A1:D5) → chartId 1496649436, chartType COMBO, per-series "type" field (COLUMN/COLUMN/LINE). Deleted after

---

### TC-C08: HISTOGRAM chart

**Prompt**
> "Add a histogram chart to the Sales sheet of {SPREADSHEET_ID} using range B2:B5 (Q1 values)"

**Checks**
- HISTOGRAM chart added
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(HISTOGRAM, B2:B5) → chartId 2013613202, "histogramChart" key. Deleted after

---

### TC-C09: Invalid chart type

**Prompt**
> "Add a 'DONUT' chart to the Sales sheet of {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` before calling the API
- Error message references the invalid chart type
- No API call made

**Result (2026-09-04) ✅ PASS**
add_chart(chart_type="DONUT") → {"error":"Invalid chart type 'DONUT'. Must be one of: COLUMN, BAR, LINE, AREA, PIE, SCATTER, COMBO, HISTOGRAM"}, no chart created

---

### TC-C10: Lowercase chart type input

**Prompt**
> "Add a 'column' chart (lowercase) to the Sales sheet of {SPREADSHEET_ID} using range A1:D5"

**Checks**
- Chart created successfully — `.upper()` normalized 'column' → 'COLUMN'
- Response includes `chartId`

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(chart_type="column" lowercase) → succeeded, chartId 148233447, normalized to COLUMN. Deleted after

---

### TC-C11: Sheet not found

**Prompt**
> "Add a column chart to a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` — sheet not found
- No API call made

**Result (2026-09-04) ✅ PASS**
add_chart(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found in spreadsheet"}, no chart created

---

### TC-C12: Custom position and size

**Prompt**
**Playwright: required**
> "Add a line chart to the Sales sheet of {SPREADSHEET_ID} using range A1:D5, positioned at x=100, y=200, width=400, height=300"

**Checks**
- Chart added with the specified `overlayPosition` values
- Response includes `chartId`
- 🔍 **Product decision:** are position/size values in pixels or grid units? Note what the API accepts

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-09-04) ✅ PASS**
add_chart(LINE, position_x=100,position_y=200,width=400,height=300) → chartId 1652849479, overlayPosition={offsetXPixels:100,offsetYPixels:200,widthPixels:400,heightPixels:300} — confirms values are pixels (field names say so directly). Deleted after

