# Drive Tools — Activity — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive/activity.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}`, `{DOC_ID}`, and `{FOLDER_ID}` from `fixtures.local.md`.

---

## `list_file_activity`

### TC-D163: Basic activity fetch returns timeline entries

**Prompt**
> "Show me the activity history for file {DOC_ID}"

**Checks**
- `file_id` matches `{DOC_ID}`
- `activities` is a list (may be empty for brand-new fixtures)
- Each entry has `timestamp`, `action`, and `actors` keys
- `action` is one of: edit, create, move, rename, delete, restore, permission_change, comment, settings_change, system_event, unknown
- No `error` key in result

**Result (2026-06-24) ✅ PASS** 52 activities returned. All entries have `timestamp`, `action`, and `actors`. Actions observed: `edit`, `rename`, `permission_change`, `create`. Actor types include `user` (known, `is_current_user: true/false`) and `system`. No `error` key.

---

### TC-D164: Known-user actor structure

**Prompt**
> "Show me the activity history for file {DOC_ID} — I want to see who made each change"

**Checks**
- At least one activity entry has an actor with `type: "user"`
- That actor has a `person_name` field (e.g. `"people/12345"`)
- `is_current_user` is a boolean

**Result (2026-06-24) ✅ PASS** Multiple user actors returned. Current-user entries have `person_name: "people/101951097007377611160"`, `is_current_user: true`. A second user (`people/114161724974780080071`, `is_current_user: false`) also appears. A `system` actor appears on the `permission_change` entry with `event: null`.

---

### TC-D165: Pagination — next_page_token present when results exceed page_size

**Prompt**
> "List file activity for {DOC_ID} with page_size=1"

**Checks**
- At least 1 activity in `activities` (the Drive Activity API treats page_size as a hint and may return slightly more due to activity grouping — do not assert exactly 1)
- `next_page_token` is present in the response

**Result (2026-06-24) ✅ PASS** `page_size=1` returned 2 activities (Drive Activity API groups related events and does not hard-clip to the requested count). `next_page_token` present. Confirmed pagination works.

---

### TC-D166: Invalid file ID returns error (unit test)

**Checks (unit test)**
- When the Drive Activity API returns an HTTP 403 or 404, the tool returns `{"error": "..."}` rather than raising an exception

**Result (2026-06-24) ✅** Unit test `test_http_error_returns_error_dict` confirms HTTP errors are caught and returned as `{"error": str(e)}`.

---

### TC-D167: export_file trips the response-size cap on base64-inflated content (issue #242)

**Background:** #242 generalized #235's response-size safety net to `export_file`. Unlike the other capped tools, `export_file` has no `local_path` param — its base64 output written to a JSON file would be a worse artifact than `download_file` (pre-existing tool) already produces, so the error points there instead.

**Prompt**
> "Export {SPREADSHEET_ID} as xlsx"

**Checks**
- Call raises `ValueError` mentioning the actual response size, the 40,000-character cap, base64's ~33% inflation, and `download_file` as the recommended alternative — must NOT mention `local_path` (this tool doesn't have that param)

**Result (2026-07-03) ✅ PASS**
Exporting even the small QA fixture spreadsheet as `xlsx` immediately exceeded the cap: `export_file: the response is 54280 characters, over the 40000-character safety cap. Base64 encoding inflates raw file size by ~33%. Call download_file instead to write the file straight to disk without this overhead, or set MAX_TOOL_RESPONSE_CHARS if your MCP client can handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS).` Confirms `export_file`'s cap trips far more readily than the other capped tools given base64 inflation — `download_file` is the practical default for anything but tiny files.

---

### TC-D168: list_file_activity response-size cap — code path only, no dedicated live fixture (issue #242)

**Background:** `list_file_activity` is already Drive-API-paginated (`page_size` clamped 1–100) and low per-item size — the only realistic exposure is a single activity's `actors` list ballooning on a file with many collaborators. Per the #242 decision doc, this tool intentionally did NOT get a dedicated live-fixture verification (reproducing hundreds of real Drive Activity events isn't cheaply reproducible) — the cap was added for defense-in-depth only, verified by unit tests (`tests/drive/test_activity.py::TestListFileActivity::test_oversized_result_raises`, `test_error_points_to_page_size_not_local_path`).

**Result (2026-07-03) ✅ N/A (by design)** — sanity-checked live that the tool still functions normally post-change (`list_file_activity(file_id={SPREADSHEET_ID}, page_size=5)` returned a normal activity list, no regression). Cap-triggering behavior covered by unit tests only, not live-verified — documented scoping decision, not an oversight.

---
