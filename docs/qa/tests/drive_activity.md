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

**Result (2026-09-04) ✅ PASS**
list_file_activity({DOC_ID}) -> file_id matches; activities is a list of 5; every entry has timestamp/action/actors; actions observed: edit, move, create (all in allowed set); no `error` key. drive.activity.readonly scope is granted.

---

### TC-D164: Known-user actor structure

**Prompt**
> "Show me the activity history for file {DOC_ID} — I want to see who made each change"

**Checks**
- At least one activity entry has an actor with `type: "user"`
- That actor has a `person_name` field (e.g. `"people/12345"`)
- `is_current_user` is a boolean

**Result (2026-06-24) ✅ PASS** Multiple user actors returned. Current-user entries have `person_name: "people/101951097007377611160"`, `is_current_user: true`. A second user (`people/114161724974780080071`, `is_current_user: false`) also appears. A `system` actor appears on the `permission_change` entry with `event: null`.

**Result (2026-09-04) ✅ PASS**
Each actor: type:"user", person_name:"people/108427788683920971958", is_current_user:true (boolean). At least one user actor with a person_name field present. (All activity on this fixture is by the current user; no second/system actor in the current 5-entry window.)

---

### TC-D165: Pagination — next_page_token present when results exceed page_size

**Prompt**
> "List file activity for {DOC_ID} with page_size=1"

**Checks**
- At least 1 activity in `activities` (the Drive Activity API treats page_size as a hint and may return slightly more due to activity grouping — do not assert exactly 1)
- `next_page_token` is present in the response

**Result (2026-06-24) ✅ PASS** `page_size=1` returned 2 activities (Drive Activity API groups related events and does not hard-clip to the requested count). `next_page_token` present. Confirmed pagination works.

**Result (2026-09-04) ✅ PASS**
list_file_activity({DOC_ID}, page_size=1) -> 2 activities returned (Drive Activity API groups related events, does not hard-clip to 1) and `next_page_token` present.

---

### TC-D166: Invalid file ID returns error (unit test)

**Checks (unit test)**
- When the Drive Activity API returns an HTTP 403 or 404, the tool returns `{"error": "..."}` rather than raising an exception

**Result (2026-06-24) ✅** Unit test `test_http_error_returns_error_dict` confirms HTTP errors are caught and returned as `{"error": str(e)}`.

**Result (2026-09-04) ⏭️ SKIP**
Unit-test-only check (HTTP 403/404 -> {"error": ...}); no live fixture that is readable-but-activity-forbidden. Separately, live HttpError propagation for the sibling sharing tools was confirmed clean in TC-D126/D129/D131/D235.

---

### TC-D168: list_file_activity response-size cap — code path only, no dedicated live fixture (issue #242)

**Background:** `list_file_activity` is already Drive-API-paginated (`page_size` clamped 1–100) and low per-item size — the only realistic exposure is a single activity's `actors` list ballooning on a file with many collaborators. Per the #242 decision doc, this tool intentionally did NOT get a dedicated live-fixture verification (reproducing hundreds of real Drive Activity events isn't cheaply reproducible) — the cap was added for defense-in-depth only, verified by unit tests (`tests/drive/test_activity.py::TestListFileActivity::test_oversized_result_raises`, `test_error_points_to_page_size_not_local_path`).

**Result (2026-07-03) ✅ N/A (by design)** — sanity-checked live that the tool still functions normally post-change (`list_file_activity(file_id={SPREADSHEET_ID}, page_size=5)` returned a normal activity list, no regression). Cap-triggering behavior covered by unit tests only, not live-verified — documented scoping decision, not an oversight.

**Result (2026-09-04) ✅ PASS**
N/A by design (#242 decision doc). Sanity: list_file_activity({SPREADSHEET_ID}, page_size=5) returned a normal 8-entry activity list, no cap ValueError, no regression. Cap-trigger path is unit-tested only.

---
