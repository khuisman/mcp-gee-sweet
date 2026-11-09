# Chart Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/sheets/structure.py` (`add_chart`)

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-sa`: `add_chart(COLUMN, A1:D5, "Sales by Quarter")` returned chartId 516837778 with `basicChart.chartType` COLUMN. Playwright screenshot `2026-10-19-tc-c01.png` shows the column chart on Sales (Q1/Q2/Q3 grouped by product). Chart then deleted with `deleteEmbeddedObject`.

**Result (2026-10-20) ✅ PASS — v0.9.3 post-advisory re-check @ c90b88d3**
`kai-sa` (service account) and `kai-oauth` (OAuth): `add_chart(COLUMN, A1:D5)` returned a chartId with `chartType` COLUMN; chart deleted. API checks only (no Playwright in this re-check).

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `add_chart(COLUMN, A1:D5, "Sales by Quarter")` → chartId 1097585336, basicChart.chartType COLUMN. Playwright (copy C URL checked) `.playwright-mcp/S4/2026-11-08-tc-c01.png`: "Sales by Quarter" column chart on Sales, Q1/Q2/Q3 grouped by Widget/Gadget/Donut/Gizmo. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — chartId 460565049, chartType BAR. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — chartId 758338615, chartType LINE. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — chartId 437275636, chartType AREA. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `PIE, A1:B5` → chartId 937917322, spec uses `pieChart` (single domain col 0, single series col 1; no axis). Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `SCATTER, B1:C5` → chartId 1968051945, chartType SCATTER. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — chartId 612816217, chartType COMBO, series types COLUMN/COLUMN/LINE. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `HISTOGRAM, B2:B5` → chartId 162167517, `histogramChart` key. Deleted.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `{"error": "Invalid chart type 'DONUT'. Must be one of: COLUMN, BAR, LINE, AREA, PIE, SCATTER, COMBO, HISTOGRAM"}`, no chartId.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `chart_type="column"` → chartId 1998082987, chartType COLUMN. Deleted.

---

### TC-C11: Sheet not found

**Prompt**
> "Add a column chart to a sheet called 'NoSuchSheet' in {SPREADSHEET_ID}"

**Checks**
- Returns `{"error": ...}` — sheet not found
- No API call made

**Result (2026-09-04) ✅ PASS**
add_chart(sheet="NoSuchSheet") → {"error":"Sheet 'NoSuchSheet' not found in spreadsheet"}, no chart created

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `{"error": "Sheet 'NoSuchSheet' not found in spreadsheet"}`, no chart.

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

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `LINE, A1:D5, x=100, y=200, 400x300` → chartId 1566204555, overlayPosition {offsetXPixels 100, offsetYPixels 200, widthPixels 400, heightPixels 300}. Product decision: pixels. Playwright `.playwright-mcp/S4/2026-11-08-tc-c12.png`: a 400x300 line chart offset ~100 px right / 200 px down from A1 (top edge at row 10), and the earlier 8 charts gone. Deleted.

---

### TC-C13: Range with no end column is rejected (#954)

**Tool calls**
1. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="COLUMN", data_range="B2:5")`
2. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="COLUMN", data_range="1:5")`

**Checks**
- Each call returns `{"error": ...}` naming its `data_range` and saying it has no end column
- Neither call creates a chart: the error is returned before any API call (the range is validated ahead of the sheet lookup), so neither response carries a `chartId` or `result`. Previously both succeeded and silently charted a single column with no real series

**Result (2026-10-11) ✅ PASS** (PR #983 @ 5b85357)
add_chart(data_range="B2:5") → {"error":"data_range 'B2:5' has no end column; add_chart needs explicit column bounds (e.g. 'A1:C10' or 'A:C')"}; add_chart(data_range="1:5") → same error naming '1:5'. Neither response carries a chartId

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `B2:5` → `{"error": "data_range 'B2:5' has no end column; add_chart needs explicit column bounds (e.g. 'A1:C10' or 'A:C')"}`; `1:5` → same naming '1:5'. No chartId/result in either.

---

### TC-C14: Column-only range still charts every column (#954)

**Tool calls**
1. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="COLUMN", data_range="A:D")`

**Checks**
- Response includes a `chartId` (an open row end is fine; only an open column end is rejected)
- In the response's `result.replies[0].addChart.chart.spec`, `basicChart.domains` has one source (column A) and `basicChart.series` has three (columns B, C, D)

**Cleanup:** delete the chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-10-11) ✅ PASS** (PR #983 @ 5b85357)
add_chart(COLUMN, data_range="A:D") → chartId 563506711; spec.basicChart.domains = 1 source (col 0), series = 3 sources (cols 1, 2, 3), rows 0–996 (open row end accepted). Deleted after

**Result (2026-10-11) ✅ PASS** (PR #983 @ af3fea8, round 2 regression)
add_chart(COLUMN, data_range="A:D") → chartId 915893384; domains = col 0, series = cols 1, 2, 3. Deleted after

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `A:D` → chartId 1484793642; domains = 1 source (col 0), series = 3 (cols 1, 2, 3), rows 0–996. Deleted.


---

### TC-C15: PIE range without exactly 2 columns is rejected (PR #983)

**Tool calls**
1. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="PIE", data_range="A1:D5")`
2. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="PIE", data_range="B1:B5")`

**Checks**
- Call 1 returns `{"error": ...}` saying `'A1:D5'` spans 4 column(s) and a PIE chart needs exactly 2; call 2 says `'B1:B5'` spans 1 column(s)
- Neither response carries a `chartId` or `result`: the error is returned before any API call. Previously call 1 succeeded and charted only column B, silently dropping C and D

**Result (2026-10-11) ✅ PASS** (PR #983 @ af3fea8)
add_chart(PIE, "A1:D5") → {"error":"data_range 'A1:D5' spans 4 column(s); a PIE chart needs exactly 2 (labels, then values)"}; add_chart(PIE, "B1:B5") → same error with "spans 1 column(s)". No chartId in either. Regression: add_chart(PIE, "A1:B5") still succeeds (chartId 774316831, domain col 0, series col 1). Deleted after

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — `A1:D5` → "data_range 'A1:D5' spans 4 column(s); a PIE chart needs exactly 2 (labels, then values)"; `B1:B5` → "... spans 1 column(s) ...". No chartId/result. (A1:B5 PIE success shown in TC-C05.)

---

### TC-C16: Single-column range for a domain-based chart is rejected; HISTOGRAM still accepts one (PR #983)

**Tool calls**
1. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="COLUMN", data_range="B2:B5")`
2. `add_chart(spreadsheet_id="{SPREADSHEET_ID}", sheet="Sales", chart_type="HISTOGRAM", data_range="B2:B5")`

**Checks**
- Call 1 returns `{"error": ...}` saying `'B2:B5'` spans 1 column and a COLUMN chart needs at least 2, with no `chartId` or `result`. Previously it succeeded with column B as both the domain and the only series
- Call 2 returns a `chartId`, and `result.replies[0].addChart.chart.spec` has a `histogramChart` key with one series (column B)

**Cleanup:** delete call 2's chart via `batch_update` with `requests=[{"deleteEmbeddedObject": {"objectId": <chartId>}}]`

**Result (2026-10-11) ✅ PASS** (PR #983 @ af3fea8)
add_chart(COLUMN, "B2:B5") → {"error":"data_range 'B2:B5' spans 1 column; a COLUMN chart needs at least 2 (the first column is the domain, the rest are series)"}, no chartId. add_chart(HISTOGRAM, "B2:B5") → chartId 1594431116, spec.histogramChart.series = 1 source (col 1, rows 1–5). Deleted after

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (kai-oauth): every chart type and error case matched; all 13 charts deleted.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard S4 on `jay`** — COLUMN `B2:B5` → "data_range 'B2:B5' spans 1 column; a COLUMN chart needs at least 2 (...)", no chartId. HISTOGRAM `B2:B5` → chartId 492374035, `histogramChart.series` = 1 source (col 1, rows 1–5). Deleted.

Cleanup: run folder QA-orn-S4-2026-11-08 trashed (delete_file, not permanent); nothing kept. Playwright tab closed via page.close().
