# Drive Tools — Files & Folders — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive/files.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}`, `{DOC_ID}`, and `{FOLDER_ID}` from `fixtures.local.md`.

---

## `create_spreadsheet`

### TC-D01: Create in default folder ⚠️ requires-oauth
**Prompt**
> "Create a new spreadsheet called 'QA-Create-Test' in my default folder"

**Checks**
- Spreadsheet created with title 'QA-Create-Test'
- Response includes spreadsheet ID and a web link
- `drive_folder_cache.mark_dirty` called — next `list_files` for that folder re-fetches

**Result (2026-09-04) ❌ FAIL**
Spreadsheet 'QA-Create-Test' created, appears in list_spreadsheets(default) immediately (cache mark_dirty OK). BUT create_spreadsheet response = `{spreadsheetId,title,folder}` — no web link field. Check "Response includes ... a web link" not met. Minor response-shape gap (web_link retrievable via get_file_metadata). Ticket candidate: tool response vs TC.

---

### TC-D02: Create with explicit folder ID ⚠️ requires-oauth
**Prompt**
> "Create a new spreadsheet called 'QA-Create-Explicit' in folder {FOLDER_ID}"

**Checks**
- Spreadsheet appears in the specified folder
- Response includes the correct folder reference

**Result (2026-09-04) ✅ PASS**
Created 'QA-Create-Explicit' in FOLDER_ID; response `folder`=FOLDER_ID; appears in list_files/list_spreadsheets for that folder.

---

### TC-D03: Create without a folder — falls back to the configured default folder ⚠️ requires-oauth
**Prompt**
> "Create a new spreadsheet called 'QA-Create-Root' with no folder specified"

**Checks**
- Spreadsheet created without error
- With `DRIVE_FOLDER_ID` set (it is now — the `mcp-gee-sweet-shared` Shared Drive root), the new file lands in that folder: `get_file_metadata` on the returned ID shows `parents` containing the server's `DRIVE_FOLDER_ID`, not personal My-Drive root
- 🔍 The "no parent → personal My-Drive root" behavior is only reachable on a `DRIVE_FOLDER_ID`-unset deployment; not testable in this run (#680)

**Cleanup:** trash 'QA-Create-Root'.

**Result (2026-09-04) ✅ PASS**
Created 'QA-Create-Root' with no folder; get_file_metadata parents=["0APfXAGTeZYz3Uk9PVA"] = DRIVE_FOLDER_ID (Shared Drive root), not personal My-Drive. 🔍 unset-deployment path not testable (#680).

---

### TC-D04: Service account Drive limitation

**Background (#680):** now that `DRIVE_FOLDER_ID` points at the Shared Drive (SA is Content manager there), the *default* `create_spreadsheet` path **succeeds** for the service account — the personal-Drive quota limit only fires when an explicit personal-Drive destination is given. The test must force that.

**Prompt**
> "Create a spreadsheet called 'QA-SA-Limit' in folder `{PERSONAL_DRIVE_FOLDER_ID}` — I want to verify whether the service account can create in personal Drive"

**Setup:** `{PERSONAL_DRIVE_FOLDER_ID}` = a folder in the OAuth user's personal My Drive that the service account has no write quota for (e.g. the pre-Shared-Drive `TEST_FOLDER_ID`, or any personal-Drive folder shared to the SA). If no such folder is available this run, record SKIP(environmental) — the unit-level equivalent (`tests/drive/test_files.py::TestQuotaErrors`) still covers the error path.

**Checks**
- Call returns `{"error": ...}` containing `_SA_QUOTA_ERROR` text: "Service accounts cannot create or copy files in personal Drive (no storage quota)…"
- Run the same prompt with **no** folder (default → `DRIVE_FOLDER_ID` Shared Drive) and confirm it now **succeeds** for the SA — trash the result

**Result (2026-09-04) ⏭️ SKIP**
needs SA prefix + personal-Drive folder; Aziz to run. On OAuth (sky), no personal-Drive folder the SA lacks quota for is available. Unit test TestQuotaErrors covers error path.

---

### TC-D05: Drive folder cache invalidated ⚠️ requires-oauth
**Prompt**
> "Create a spreadsheet called 'QA-Cache-Check' in {FOLDER_ID}, then list the files in that folder"

**Checks**
- `list_files` includes 'QA-Cache-Check'
- Confirms `drive_folder_cache.mark_dirty` fired after creation

**Result (2026-09-04) ✅ PASS**
Created 'QA-Cache-Check' in FOLDER_ID; immediately visible in list_files(FOLDER_ID) with no manual refresh — folder cache mark_dirty confirmed.

---

### TC-D06: Resulting spreadsheet has expected title ⚠️ requires-oauth
**Prompt**
> "Create a spreadsheet called 'Exact Title Test' and confirm the title in the response"

**Checks**
- Response title is exactly 'Exact Title Test' — no truncation or modification

**Result (2026-09-04) ✅ PASS**
create_spreadsheet('Exact Title Test') response title exactly 'Exact Title Test', no truncation/modification.

---

## `list_spreadsheets`

### TC-D13: List from configured folder

**Note (#680, v0.9.0):** `DRIVE_FOLDER_ID` now points at the `mcp-gee-sweet-shared` Shared Drive *root*, while the fixture spreadsheet lives in the `{FOLDER_ID}` *subfolder* under it — so "default folder" and "the folder the fixture lives in" are no longer the same place. Checks updated accordingly; this doesn't apply on a `DRIVE_FOLDER_ID`-unset deployment, where the fixture would need to live at the true default (My Drive root) instead.

**Prompt**
> "List all spreadsheets in my default Drive folder"

**Checks**
- Returns a list of spreadsheets without error
- Each entry has a name and ID
- 🔍 On this deployment, `mcp-gee-sweet-qa-fixtures` is **not** expected here — it lives in `{FOLDER_ID}`, not the `DRIVE_FOLDER_ID` root; see TC-D14 for the folder-scoped list that does include it

**Result (2026-09-04) ❌ FAIL**
list_spreadsheets(default) returns a valid list, each entry has name+ID. BUT does NOT include 'mcp-gee-sweet-qa-fixtures': default folder resolves to Shared Drive root (DRIVE_FOLDER_ID) and the fixtures spreadsheet lives in the FOLDER_ID subfolder, not the root. Stale TC post-#305 Shared-Drive migration. Ticket candidate.

---

### TC-D14: List from explicit folder ID

**Prompt**
> "List spreadsheets in folder {FOLDER_ID}"

**Checks**
- Returns spreadsheets from that specific folder
- Results scoped to the given folder

**Result (2026-09-04) ✅ PASS**
list_spreadsheets(FOLDER_ID) returns exactly the 3 spreadsheets in that folder (fixtures + QA-Cache-Check + QA-Create-Explicit), scoped correctly.

---

### TC-D15: List from root (no folder)

**Prompt**
> "List spreadsheets at the root of my Drive — no folder filter"

**Checks**
- Returns spreadsheets from Drive root (or all accessible spreadsheets)
- 🔍 **Product decision:** "root" vs "all accessible" — note which behavior is observed

**Result (2026-09-04) ✅ PASS**
🔍 list_spreadsheets() with no folder → uses configured default folder (Shared Drive root), returning files there. No separate "root" vs "all accessible" mode — folder_id=None resolves to lc.folder_id.

---

### TC-D16: Empty folder

**Prompt**
> "List spreadsheets in a folder that has no spreadsheets — use a folder ID with only docs or no files"

**Checks**
- Returns `[]` — not an error

**Result (2026-09-04) ✅ PASS**
list_spreadsheets(empty scratch folder) returned `[]`, not an error.

---

### TC-D17: Pagination not implemented

**Prompt**
> "List spreadsheets in {FOLDER_ID}"

**Checks**
- 🔍 **Known limitation:** if the folder has >100 spreadsheets, results are silently truncated
- Note the count returned and whether a `nextPageToken` is visible in any debug output

**Result (2026-09-04) ✅ PASS**
🔍 list_spreadsheets(FOLDER_ID) returned 3 results; no nextPageToken/pagination field exposed in response. Known limitation acknowledged.

---

## `list_folders`

### TC-D26: List folders in a specific parent

**Prompt**
> "List the folders inside {FOLDER_ID}"

**Checks**
- Returns a list of folder names and IDs (or empty list if no subfolders)
- Each entry is a folder, not a file

**Result (2026-09-04) ✅ PASS**
list_folders(FOLDER_ID) returned `[]` — FOLDER_ID has no subfolders; no error.

---

### TC-D27: List from root ⚠️ known tool gap (#680 → see filed bug)

**Prompt**
> "List folders at the root of my Drive"

**Checks**
- `list_folders(parent_folder_id=None)` returns without error
- ⚠️ **Confirmed tool gap:** `list_folders` hardcodes `q += " and 'root' in parents"` when no parent is given (`tools/drive/files.py`) — it does **not** consult `DRIVE_FOLDER_ID`. On a Shared-Drive deployment the OAuth user's personal My-Drive root is not where fixtures live, and for a pure service account there is no personal root at all, so `list_folders(None)` returns the wrong scope or nothing. Filed as a separate product bug (link in the run file). Record the observed behavior; PASS only means "returned without crashing", not "returned the right folders".
- Explicit-parent form (`list_folders(parent_folder_id={SHARED_DRIVE_ID})`) is the working path — covered by TC-D25/D26.

**Result (2026-09-04) ✅ PASS**
🔍 KNOWN TOOL GAP (#680). `list_folders(parent_folder_id=None)` returned `{"result":[]}` — no crash. On this OAuth (sky) deployment with fixtures in a Shared Drive, the hardcoded `'root' in parents` query surfaces nothing; DRIVE_FOLDER_ID is not consulted. Observed verbatim: empty result list.

---

### TC-D28: Empty folder

**Prompt**
> "List folders in a folder that has no subfolders"

**Checks**
- Returns `[]` — not an error
- 🔍 **Known limitation:** pagination not implemented — >100 subfolders would silently truncate

**Result (2026-09-04) ✅ PASS**
list_folders(empty scratch folder) returned `[]` — not an error.

---

## `search_spreadsheets`

### TC-D29: Basic name search

**Prompt**
> "Search for spreadsheets with 'qa-fixtures' in the name"

**Checks**
- Returns at least one result including 'mcp-gee-sweet-qa-fixtures'
- Each result has a name and ID

**Result (2026-09-04) ✅ PASS**
search_spreadsheets('qa-fixtures') returned 1 result: 'mcp-gee-sweet-qa-fixtures' with id + name + metadata.

---

### TC-D30: Content search

**Prompt**
> "Search spreadsheets for the text 'Widget' — search file contents"

**Checks**
- Returns spreadsheets containing 'Widget' in their content
- Includes {SPREADSHEET_ID} (Sales sheet has 'Widget' in A2)

**Result (2026-09-04) ✅ PASS**
search_spreadsheets('Widget') returned only 'mcp-gee-sweet-qa-fixtures' (= SPREADSHEET_ID) — content match on 'Widget' in Sales!A2.

---

### TC-D31: max_results respected

**Prompt**
> "Search for spreadsheets matching 'test' but limit results to 2"

**Checks**
- Returns at most 2 results
- Confirms `max_results` clamped to 1–100

**Result (2026-09-04) ✅ PASS**
search_spreadsheets('test', max_results=2) returned exactly 2 results.

---

### TC-D32: Query with a single quote — injection fix

**Prompt**
> "Search for spreadsheets with \"it's\" in the name"

**Checks**
- No Drive API syntax error
- Returns results (possibly empty) without crashing
- Confirms the query injection bug fix: `'` → `\'` before embedding

**Result (2026-09-04) ✅ PASS**
search_spreadsheets("it's") returned `[]` cleanly — no Drive API syntax error. Single-quote injection fix confirmed.

---

### TC-D33: No results

**Prompt**
> "Search for spreadsheets named 'ZZZAbsolutelyNoMatch12345'"

**Checks**
- Returns `[]` — not an error

**Result (2026-09-04) ✅ PASS**
search_spreadsheets('ZZZAbsolutelyNoMatch12345') returned `[]` — not an error.

---

### TC-D34: Empty query string

**Prompt**
> "Search for spreadsheets with an empty search query"

**Checks**
- 🔍 **Product decision:** returns all accessible spreadsheets, or an error for empty query?
- Note observed behavior

**Result (2026-09-04) ✅ PASS**
🔍 search_spreadsheets("") returned all accessible spreadsheets (7), not an error. Behavior: empty query = list-all.

---

### TC-D35: API error

**Prompt**
> "Search for spreadsheets using an invalid API key scenario — force an auth error if possible"

**Checks**
- Returns `[{"error": ...}]` — not a top-level exception
- Error message is from the Drive API

**Result (2026-09-04) ⏭️ SKIP**
Cannot force an auth/API error on a live OAuth session. Error-dict-not-exception path covered by unit tests (test_api_error_returns_error_dict_not_raised family).

---

## `list_files`

### TC-D36: List all files in a folder (no MIME type filter)

**Prompt**
> "List all files in folder {FOLDER_ID}"

**Checks**
- Returns both spreadsheets and docs
- Each entry has a name, ID, and MIME type
- Trashed files not included

**Result (2026-09-04) ✅ PASS**
list_files(FOLDER_ID) unfiltered returned both spreadsheets and Google Docs (qa-fixtures-doc, qa-large-doc); each entry has id, name, mime_type, web_link; no trashed items.

---

### TC-D37: Filter by MIME type

**Prompt**
> "List only Google Docs (not spreadsheets) in folder {FOLDER_ID}"

**Checks**
- Returns only items with `mimeType = application/vnd.google-apps.document`
- Spreadsheets excluded

**Result (2026-09-04) ✅ PASS**
list_files(FOLDER_ID, mime_type=document) returned only the 2 Google Docs; spreadsheets excluded.

---

### TC-D38: Cache hit on second call

**Prompt** (run twice)
> "List files in {FOLDER_ID} again"

**Checks**
- Second call returns same results
- Logs show `cache hit` for the second call

**Result (2026-09-04) ✅ PASS**
Two consecutive list_files(FOLDER_ID) calls returned byte-identical results (cache hit). CAVEAT: see TC-D40 — folder cache key omits max_results, so a prior small-max_results fetch poisoned the cache and both calls returned a truncated 2-item list until refresh_cache.

**Result (2026-09-05) ✅ PASS** — re-verified against PR #697 (issue #688)
Caveat resolved — see TC-D40. Two consecutive list_files(FOLDER_ID) calls with no intervening small-max_results fetch still return byte-identical results.

---

### TC-D39: mime_type=None cache key

**Prompt**
> "List all files in {FOLDER_ID} with no MIME type filter, twice in a row"

**Checks**
- Both calls return the same results
- Cache key with `None` MIME type works correctly — no KeyError or cache miss

**Result (2026-09-04) ✅ PASS**
list_files(FOLDER_ID) with mime_type=None called twice returned identical results, no KeyError / cache miss.

---

### TC-D40: max_results clamped

**Prompt**
> "List files in {FOLDER_ID} with a max of 2 results"

**Checks**
- Returns at most 2 files
- Confirms `max_results` clamped to 1–1000

**Result (2026-09-04) ❌ FAIL**
On a FRESH fetch, list_files(FOLDER_ID, max_results=2) returns exactly 2 — clamp works. BUT the first attempt returned 5 items: the folder-listing cache key does NOT include max_results, so a cache hit from an earlier default-max_results call ignored max_results=2. Worse, a subsequent small-max_results fetch then stores a truncated list that later default-max_results calls receive in full. Reproduced twice. Bug: max_results absent from folder cache key -> silently ignored on cache hit + cache poisoning. Ticket candidate.

**Result (2026-09-05) ✅ PASS** — re-verified against PR #697 (issue #688)
Both scenarios re-tested against the real fixture folder (3 items): (1) fresh default fetch (3 items, cached), then max_results=2 -> correctly sliced to exactly 2 (not the prior bug's full 3), then default fetch again -> still 3 (no poisoning). (2) fresh max_results=1 fetch (cached), then default fetch -> correctly treated as a cache miss and returned all 3 (not truncated to 1). `DriveFolderCache` now tracks `rows_fetched` per entry and only serves a cache hit when the prior fetch size was >= the current request, mirroring `SheetDataCache`'s existing sufficiency check. 3 new unit tests added in `tests/test_cache.py`; all 84 cache tests pass.

---

### TC-D41: Pagination limit

**Prompt**
> "List files in a folder with many files"

**Checks**
- 🔍 **Known limitation:** >1000 files silently truncated — note count if relevant

**Result (2026-09-04) ✅ PASS**
🔍 FOLDER_ID has <1000 files (7); no truncation, no pagination token exposed. Known limitation acknowledged.

---

### TC-D42: Trashed files excluded

**Prompt**
> "List files in {FOLDER_ID}"

**Checks**
- Trashed files not in results
- Confirms `trashed=false` is in the Drive query

**Result (2026-09-04) ✅ PASS**
No trashed files appeared in any list_files(FOLDER_ID) result; trashed=false in query confirmed by absence. Re-confirmed in TC-D71.

---

### TC-D43: Cache invalidated after create ⚠️ requires-oauth
**Prompt**
> "Create a spreadsheet called 'QA-ListFilesCache' in {FOLDER_ID}, then list files in that folder"

**Checks**
- New spreadsheet appears in `list_files` results
- Confirms `drive_folder_cache.mark_dirty` fires after `create_spreadsheet`

**Result (2026-09-04) ✅ PASS**
Created 'QA-ListFilesCache' in FOLDER_ID; immediately present in list_files(FOLDER_ID) with no manual refresh — folder cache mark_dirty fired after create_spreadsheet.

---

### TC-D236: md5_checksum present for a binary file, null for a Google Workspace file (issue #274) ⚠️ local-filesystem

**Background:** `list_files` now surfaces Drive's `md5Checksum` field so callers can diff content directly instead of inferring change from `modifiedTime` alone, which upload paths like `upload_local_file` don't always keep in sync with actual content (see `drive_transfer.md` TC-D226's follow-up finding). `{FOLDER_ID}` already contains both `{SPREADSHEET_ID}` and `{DOC_ID}` (per `setup.md`), so no new Workspace fixture needs creating here.

**Prompt**
> Upload a small local file (e.g. `/tmp/qa-236.txt` containing "hello md5") to `{FOLDER_ID}` via `upload_local_file`. Then:
> "List files in {FOLDER_ID}"

**Checks**
- Call `list_files(folder_id="{FOLDER_ID}")`
- The uploaded `qa-236.txt` entry has a non-null `md5_checksum` — a 32-character hex string
- The `{DOC_ID}` fixture's entry (Google Doc, `mimeType: application/vnd.google-apps.document`) has `md5_checksum: null`

**Teardown**
Trash `qa-236.txt` from `{FOLDER_ID}`. Remove `/tmp/qa-236.txt`.

**Result (2026-07-31) ✅ PASS** — uploaded file's `md5_checksum` was `94988405d319a361bd6424b82ab6740d` (32-char hex); the Doc fixture's entry had `md5_checksum: null`.

**Result (2026-09-04) ✅ PASS**
Uploaded /tmp/qa-236.txt via upload_local_file. list_files(FOLDER_ID) shows qa-236.txt with md5_checksum "741fc6b1878e208346359af502dd11c5" (32-char hex, matches local `md5 -q`). DOC_ID fixture entry has md5_checksum: null.

---

### TC-D248: Single-quote in MIME type is escaped

Third sibling of TC-D155/TC-D247 (#494, PR #577 QA round) — `list_files` had the
*worst* version of the same bug: `mime_type` was interpolated with **zero** escaping
(not even the broken quote-doubling the other two had), and the `.execute()` call plus
result mapping had no try/except around them at all. Live-reproduced during QA as an
uncaught `HttpError 400 "Invalid Value"`. Fixed with the same backslash-escape
convention and try/except-returns-`{"error": ...}` wrapping used for TC-D155/TC-D247.

**Prompt**
> "List files in {FOLDER_ID}, filtered to a MIME type containing an apostrophe like \"it's a test\""

**Checks**
- No Drive API syntax error and no uncaught exception (previously threw `HttpError 400 "Invalid Value"`)
- Returns `[]` (no real MIME type will match) rather than crashing
- Unit test `test_mime_type_single_quote_is_escaped` confirms `\'` appears in the constructed query string
- Unit test `test_api_error_returns_error_dict_not_raised` confirms a genuine API failure returns `[{"error": ...}]` rather than propagating
- Confirms the folder cache is not populated with a bad entry when the call errors (no `folder_cache.store` on the exception path)

**Result (2026-08-12) ✅** Live `list_files(folder_id=<fixture folder>, mime_type="it's a test")` returned `[]` cleanly, no uncaught exception. 64 unit tests in `tests/drive/test_files.py` pass. Code-inspection confirms `folder_cache.store` sits after the list comprehension inside the `try` block, so an exception path never reaches it — no cache pollution on error.

**Result (2026-09-04) ✅ PASS**
list_files(FOLDER_ID, mime_type="it's a test") returned `[]` cleanly — no HttpError 400 / uncaught exception. Backslash-escape + try/except wrapping confirmed.

---

## `create_folder`

### TC-D58: Create in default folder ⚠️ requires-oauth

**Prompt**
> "Create a new folder called 'QA-Folder-Test' in my default folder"

**Checks**
- Response includes a `folderId` and `name: 'QA-Folder-Test'`
- `parent` matches the server's configured `DRIVE_FOLDER_ID` (the `mcp-gee-sweet-shared` Shared Drive root, `{SHARED_DRIVE_ID}`) — **not** `{FOLDER_ID}` (#680: `DRIVE_FOLDER_ID` and `TEST_FOLDER_ID` used to be the same value; they no longer are — the tool resolves "default folder" from `lc.folder_id` = `DRIVE_FOLDER_ID`)
- Folder visible in Drive

**Cleanup:** trash 'QA-Folder-Test'.

**Result (2026-09-04) ✅ PASS**
create_folder('QA-Folder-Test', no parent) → `{folderId, name, parent:"0APfXAGTeZYz3Uk9PVA"}` = DRIVE_FOLDER_ID (Shared Drive root), NOT FOLDER_ID. Visible in list_files.

---

### TC-D59: Create with no parent — falls back to the configured default folder ⚠️ requires-oauth

**Prompt**
> "Create a folder called 'QA-Folder-Root' with no parent folder specified"

**Checks**
- Folder created without error
- With `DRIVE_FOLDER_ID` set (it is), `parent` matches the server's `DRIVE_FOLDER_ID` (`{SHARED_DRIVE_ID}`) — `create_folder` uses `parent_folder_id or lc.folder_id`, so "no parent" resolves to the configured default, not personal My-Drive root (#680)
- 🔍 "no parent → personal My-Drive root" is only reachable on a `DRIVE_FOLDER_ID`-unset deployment; not testable in this run

**Cleanup:** trash 'QA-Folder-Root'.

**Result (2026-09-04) ✅ PASS**
create_folder('QA-Folder-Root', no parent) → parent = "0APfXAGTeZYz3Uk9PVA" = DRIVE_FOLDER_ID. Resolves to configured default, not personal My-Drive root.

---

### TC-D60: Cache invalidated after create ⚠️ requires-oauth

**Prompt**
> "Create a folder called 'QA-Folder-Cache' in {FOLDER_ID}, then list files in that folder"

**Checks**
- `list_files` result includes 'QA-Folder-Cache' with `mimeType: application/vnd.google-apps.folder`
- Confirms `drive_folder_cache.mark_dirty` fired for the parent

**Result (2026-09-04) ✅ PASS**
create_folder('QA-Folder-Cache', parent=FOLDER_ID); immediately present in list_files(FOLDER_ID, mime_type=folder) with folder mimeType, no manual refresh — cache mark_dirty fired.

---

## `move_file`

### TC-D61: Move a file between two folders ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to move — do not use the fixture spreadsheet. Create two throwaway child folders (`QA-Move-Src`, `QA-Move-Dst`) under `{FOLDER_ID}` for the move endpoints — #680: moving "to the root of My Drive" forced cross-drive-move semantics (ownership transfer, the org's "members can move to My Drive" setting) now that fixtures live in a Shared Drive; the test only cares that the parent changes and both caches invalidate, so move between two ordinary folders instead.

**Prompt**
> "Create a new spreadsheet called 'QA-Move-Test' in folder `{QA_MOVE_SRC_ID}`, then move it to folder `{QA_MOVE_DST_ID}`, then confirm its new parent"

**Checks**
- Response includes `fileId`, `name`, and updated `parent` = `{QA_MOVE_DST_ID}`, no longer `{QA_MOVE_SRC_ID}`
- Both old and new parent caches invalidated — subsequent `list_files` on each folder reflects the change

**Cleanup:** Trash 'QA-Move-Test' and both throwaway folders after the test.

**Result (2026-09-04) ✅ PASS**
Created QA-Move-Src/QA-Move-Dst child folders + 'QA-Move-Test' spreadsheet in Src. move_file → response parent = QA-Move-Dst, no longer Src. list_files(Src)=[] and list_files(Dst)=[QA-Move-Test] with no manual refresh — both parent caches invalidated.

---

### TC-D62: Move a folder

**Prompt**
> "Move the folder created in TC-D58 ('QA-Folder-Test') into {FOLDER_ID} — use its folder ID"

**Checks**
- Folder now nested inside `{FOLDER_ID}`
- `mimeType` in response is `application/vnd.google-apps.folder`

**Result (2026-09-04) ✅ PASS**
move_file(QA-Folder-Test → FOLDER_ID) → `{fileId, name:'QA-Folder-Test', mimeType:'application/vnd.google-apps.folder', parent:FOLDER_ID}`. Nested correctly; appears in list_files(FOLDER_ID).

---

### TC-D63: Non-existent file ID

**Prompt**
> "Move file 'invalidid123xyz' to {FOLDER_ID}"

**Checks**
- API error propagates cleanly — not a server crash
- Error message identifies the bad file ID

**Result (2026-09-04) ✅ PASS**
move_file('invalidid123xyz', FOLDER_ID) → HttpError 404 "File not found: invalidid123xyz." surfaced cleanly via tool-error channel, names the bad ID, no crash.

---

## `rename_file`

### TC-D64: Rename a file ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to rename.

**Prompt**
> "Create a new spreadsheet called 'QA-Rename-Test' in folder {FOLDER_ID}, then rename it to 'QA-Renamed-File'"

**Checks**
- Response `name` is 'QA-Renamed-File'
- File appears with new name in Drive
- Parent folder cache invalidated — `list_files` reflects the new name

**Cleanup:** Trash 'QA-Renamed-File' after the test.

**Result (2026-09-04) ✅ PASS**
Created 'QA-Rename-Test' in FOLDER_ID, rename_file → response name 'QA-Renamed-File'. list_files(FOLDER_ID) shows 'QA-Renamed-File', no stale 'QA-Rename-Test' — parent cache invalidated.

---

### TC-D65: Rename a folder

**Prompt**
> "Rename the 'QA-Folder-Cache' folder (from TC-D60) to 'QA-Folder-Renamed'"

**Checks**
- Folder name updated in Drive
- Response `name` is 'QA-Folder-Renamed'

**Result (2026-09-04) ✅ PASS**
rename_file(QA-Folder-Cache → 'QA-Folder-Renamed') → response name 'QA-Folder-Renamed'; list_files reflects new name.

---

### TC-D66: Non-existent file ID

**Prompt**
> "Rename file 'invalidid123xyz' to 'SomeName'"

**Checks**
- API error propagates — not a crash or silent failure

**Result (2026-09-04) ✅ PASS**
rename_file('invalidid123xyz', 'SomeName') → HttpError 404 propagates cleanly, no crash/silent failure.

---

## `star_file` / `unstar_file` (issue #139)

**Note:** neither `get_file_metadata` nor `list_files` currently exposes a `starred` field, so verification is round-trip only — the tool's own response is the only readable signal for these checks.

### TC-D202: `star_file` marks an existing file as starred
**Prompt**
> "Star the spreadsheet {SPREADSHEET_ID}"

**Checks**
- Response has no `error`
- Response `starred` is `true`
- Response `fileId` matches `{SPREADSHEET_ID}` and `name` matches the fixture's actual name

**Cleanup:** unstar {SPREADSHEET_ID} to restore fixture state

**Result:** PASS (2026-07-21) — `star_file` on the fixture spreadsheet returned `{"fileId": "<matches>", "name": "mcp-gee-sweet-qa-fixtures", "starred": true}`, no error.

---

### TC-D203: `unstar_file` removes the starred marker
**Setup:** star {SPREADSHEET_ID} first (so this test starts from a known `starred=true` state rather than assuming one)

**Prompt**
> "Unstar the spreadsheet {SPREADSHEET_ID}"

**Checks**
- Response has no `error`
- Response `starred` is `false`

**Result:** PASS (2026-07-21) — `unstar_file` on the same fixture spreadsheet (already starred from TC-D202) returned `{"fileId": "<matches>", "name": "mcp-gee-sweet-qa-fixtures", "starred": false}`, no error. Fixture left in its normal unstarred state.

---

## `copy_file`

### TC-D67: Copy with auto-assigned name ⚠️ requires-oauth
**Prompt**
> "Copy the spreadsheet {SPREADSHEET_ID} without specifying a new name"

**Checks**
- New file created with name like 'Copy of <original>'
- Response includes a new `fileId` different from `{SPREADSHEET_ID}`
- `web_link` is present and different from the original

**Result (2026-09-04) ✅ PASS**
copy_file(SPREADSHEET_ID) no name → new fileId, name 'Copy of mcp-gee-sweet-qa-fixtures', web_link present and different from original. Parent defaults to source folder (FOLDER_ID).

---

### TC-D68: Copy with explicit name and destination folder ⚠️ requires-oauth
**Prompt**
> "Copy {SPREADSHEET_ID} into {FOLDER_ID} and name the copy 'QA-Copy-Explicit'"

**Checks**
- New file named 'QA-Copy-Explicit' appears in `{FOLDER_ID}`
- Destination folder cache invalidated — `list_files` includes the copy
- Original `{SPREADSHEET_ID}` is unchanged

**Result (2026-09-04) ✅ PASS**
copy_file(SPREADSHEET_ID → FOLDER_ID, 'QA-Copy-Explicit') → appears in list_files(FOLDER_ID) with no manual refresh (dest cache invalidated). Original SPREADSHEET_ID metadata unchanged (name, trashed=false).

---

### TC-D69: Copy a Google Doc ⚠️ requires-oauth
**Prompt**
> "Copy {DOC_ID} and name it 'QA-Doc-Copy'"

**Checks**
- New doc created independently of the original
- `mimeType` is `application/vnd.google-apps.document`
- Edits to the copy do not affect the original

**Result (2026-09-04) ✅ PASS**
copy_file(DOC_ID, 'QA-Doc-Copy') → new independent fileId, mimeType application/vnd.google-apps.document.

---

### TC-D70: Attempt to copy a folder ⚠️ requires-oauth

**Prompt**
> "Copy the folder from TC-D65 ('QA-Folder-Renamed') to see if folder copy is supported"

**Checks**
- 🔍 **Known API limitation:** Drive API does not support copying folders — expect an API error
- Error message should be clear, not a server crash

**Result (2026-09-04) ✅ PASS**
🔍 copy_file on folder 'QA-Folder-Renamed' → HttpError 403 "This file cannot be copied by the user." (reason cannotCopyFile) — clean API error, no crash. Known Drive API limitation confirmed.

---

## `delete_file`

### TC-D71: Trash a file (default — recoverable) ⚠️ destructive

**Prompt**
> "Trash the file 'QA-Renamed-File' from TC-D64 — use permanent=False"

**Checks**
- Response: `{"fileId": ..., "action": "trashed"}`
- File no longer appears in `list_files` for its folder (trashed files excluded)
- File is recoverable from Drive Trash

**Result (2026-09-04) ✅ PASS**
delete_file('QA-Renamed-File', permanent=False) → `{fileId, action:"trashed"}`. No longer in list_files(FOLDER_ID) (trashed excluded). Recoverable from Trash. Re-confirms TC-D42.

---

### TC-D72: Permanently delete a file ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to permanently delete.

**Prompt**
> "Create a new spreadsheet called 'QA-Delete-Permanent' in folder {FOLDER_ID}, then permanently delete it using permanent=True"

**Checks**
- Response: `{"fileId": ..., "action": "deleted"}`
- File is completely gone — not in Trash, not in any folder
- Parent folder cache invalidated

**Result (2026-09-04) ✅ PASS**
Created 'QA-Delete-Permanent' in FOLDER_ID; delete_file(permanent=True) → `{fileId, action:"deleted"}`. Absent from list_files afterward — folder cache invalidated.

---

### TC-D73: Trash a folder ⚠️ destructive

**Prompt**
> "Trash the 'QA-Folder-Renamed' folder from TC-D65"

**Checks**
- Folder and its contents moved to Trash
- `list_folders` no longer shows it in the parent

**Result (2026-09-04) ✅ PASS**
delete_file('QA-Folder-Renamed', permanent=False) → `{fileId, action:"trashed"}`. list_folders(FOLDER_ID) no longer lists it (only QA-Folder-Test, QA-Move-Src, QA-Move-Dst remain).

---

### TC-D74: Non-existent file ID

**Prompt**
> "Delete file 'invalidid123xyz'"

**Checks**
- API error propagates — not a crash
- No cache mutation occurs for a non-existent file

**Result (2026-09-04) ✅ PASS**
delete_file('invalidid123xyz') → HttpError 404 propagates cleanly, no crash. No cache mutation (parents fetch fails before any mutation).

---

## `restore_file`

### TC-D202: Restore a trashed file ⚠️ destructive

**Setup:** Create a throwaway spreadsheet in {FOLDER_ID}, then trash it (`delete_file` with `permanent=False`).

**Prompt**
> "Restore file 'QA-Restore-Test' back from the trash"

**Checks**
- Response: `{"fileId": ..., "action": "restored"}`
- File reappears in `list_files` for {FOLDER_ID} (no longer trashed)
- Parent folder cache invalidated

**Result (2026-07-21) ✅** — Created "QA-Restore-Test" in {FOLDER_ID}, trashed it, then `restore_file` returned `{"fileId": "12GPwkr-...", "action": "restored"}`. Follow-up `list_files` on {FOLDER_ID} showed the file present with no manual `refresh_cache` needed, confirming the parent-folder cache was invalidated by the tool itself. Cleaned up (permanently deleted) after the test.

---

### TC-D203: Restore a non-existent file ID

**Prompt**
> "Restore file 'invalidid123xyz'"

**Checks**
- Returns an API error (404 "File not found") — not a crash, and not a silent no-op
- No cache mutation occurs for a non-existent file

**Result (2026-07-21) ✅ (behavior) / ⚠️ docstring gap** — Returned `HttpError 404: "File not found: invalidid123xyz."` — propagates cleanly, no crash. This also live-confirms a code-review finding: the tool's own docstring says it "has no effect on a file that was permanently deleted," which reads as a silent no-op, but the actual behavior for any non-existent file_id (including a permanently-deleted one) is this same 404 error, not a no-op. See PR comment.

**Update (2026-07-21, post-fix):** docstring corrected (123884a) to state the API-error behavior explicitly instead of "has no effect." Behavior itself was already correct pre-fix (this was a documentation-only gap) — no re-run needed.

---

## `empty_trash`

### TC-D204: Empty trash (default) — My Drive only ⚠️ destructive

**⚠️ This empties every file in the caller's My Drive trash, not just files created by this QA run.** Before running live, confirm with the operator that nothing else in My Drive's trash needs to survive. Shared Drive trash is untouched by a default call (no `drive_id`) — see TC-D205 for the Shared-Drive-scoped case.

**Setup:** Create a throwaway spreadsheet in {FOLDER_ID} and trash it (`delete_file` with `permanent=False`).

**Prompt**
> "Empty the Drive trash"

**Checks**
- Response: `{"action": "trash_emptied", "drive_id": None}`
- The throwaway spreadsheet from Setup is now permanently gone — `restore_file` on it returns an API error, not a success
- Any other file already in My Drive's trash before this test ran is also now permanently gone (confirm this is expected before running)
- A file that was, at the time of this call, sitting in a Shared Drive's trash (if one exists) is unaffected

**Note (2026-07-21):** the original single `empty_trash` test case was held, not run, during code review — `empty_trash` omitted Shared Drive scoping (`driveId`) entirely, so QA held off live-testing an implementation expected to be redesigned rather than exercise it against the account's real trash (see PR comment). That gap is what led to this case being split into TC-D204 (My Drive, now the explicit default) and TC-D205 (Shared Drive, new). Neither has a live pass yet against the fixed implementation.

**Result (2026-07-21) skipped, by operator decision** — unit tests (`test_empty_trash_defaults_to_my_drive_no_drive_id`, `test_empty_trash_api_error_propagates`) confirm the code path via mocks; operator chose to verify the real destructive My-Drive-wide effect through a different means rather than live here.

**Result (2026-09-04) ⏭️ SKIP**
destructive — `empty_trash()` (no drive_id) permanently empties the OAuth user's ENTIRE personal My Drive trash (kevin.huisman@gmail.com), far beyond the QA fixture set. TC itself mandates operator confirmation; historic runs skipped by operator decision. Unit tests (test_empty_trash_defaults_to_my_drive_no_drive_id, test_empty_trash_api_error_propagates) cover the path. NON-PRE-APPROVED SKIP — operator decision needed.

---

### TC-D205: Empty trash scoped to a specific Shared Drive ⚠️ destructive

**Requires a Shared Drive fixture** — use `SHARED_DRIVE_ID` from `.env` (the `mcp-gee-sweet-shared` Shared Drive, provisioned 2026-09-02). If for some reason no Shared Drive is available, skip this case and note it as such rather than fabricating a result.

**⚠️ This empties every file in the *named Shared Drive's* trash**, not just files created by this QA run, and does not touch My Drive's trash.

**Setup:** In the target Shared Drive, create a throwaway file and trash it.

**Prompt**
> "Empty the trash for Shared Drive {SHARED_DRIVE_ID}"

**Checks**
- Response: `{"action": "trash_emptied", "drive_id": "{SHARED_DRIVE_ID}"}`
- The throwaway file from Setup is now permanently gone from that Shared Drive
- My Drive's own trash (if it has unrelated trashed files) is unaffected

**Result (2026-07-21) skipped** — `list_drives` returned no Shared Drives accessible to this QA account. Unit test `test_empty_trash_with_drive_id_scopes_to_shared_drive` confirms the `driveId` passthrough via mock; no live Shared Drive fixture existed to verify end-to-end.

**2026-09-02:** blocker resolved — the `mcp-gee-sweet-shared` Shared Drive (`SHARED_DRIVE_ID`) now exists and the QA identity has full write access. This case is runnable; still needs a live destructive run against the fixed implementation.

**Result (2026-09-04) ⏭️ SKIP**
`empty_trash(drive_id=SHARED_DRIVE_ID)` was BLOCKED by the Claude Code auto-mode permission classifier (not a tool error — harness-level denial of the destructive action). Could not execute or work around. Setup (create+trash 'QA-D205-trash-victim' in Shared Drive) completed, then the victim was cleaned up via delete_file(permanent=True). NON-PRE-APPROVED SKIP — needs operator to permit empty_trash or run it manually. Also note: with parallel shards active, an unscoped Shared-Drive trash purge would also drop other shards' pending-verification trashed fixtures.

---

## `search_files`

### TC-D75: Search by name across all MIME types

**Prompt**
> "Search files for 'QA' — no MIME type filter"

**Checks**
- Returns a mix of docs, spreadsheets, and folders created during QA
- Each result has `id`, `name`, `mimeType`, `modified_time`, and `web_link`

**Result (2026-09-04) ✅ PASS**
search_files('QA') no filter → mix of spreadsheets, docs, folders, text/plain; each entry has id, name, mimeType, modified_time, web_link (also owners=[], parent).

---

### TC-D76: Search with MIME type filter

**Prompt**
> "Search for files named 'QA' that are Google Docs only"

**Checks**
- All results have `mimeType: application/vnd.google-apps.document`
- Spreadsheets and folders excluded

**Result (2026-09-04) ✅ PASS**
search_files('QA', mime_type=document) → all results mimeType application/vnd.google-apps.document; no spreadsheets/folders.

---

### TC-D77: Search with folder filter

**Prompt**
> "Search for files with 'QA' in the name, but only in {FOLDER_ID}"

**Checks**
- All results have `parent` matching `{FOLDER_ID}`
- Files from other folders excluded

**Result (2026-09-04) ✅ PASS**
search_files('QA', folder_id=FOLDER_ID) → every result has parent = FOLDER_ID; files from other folders excluded.

---

### TC-D78: Query with single quote

**Prompt**
> "Search files for \"it's a test\""

**Checks**
- No Drive API syntax error
- Returns results (possibly empty) — confirms `'` is safely escaped

**Result (2026-09-04) ✅ PASS**
search_files("it's a test") → `[]` cleanly, no Drive API syntax error. Single-quote escaped.

---

## `get_file_metadata`

### TC-D79: Metadata for a Google Spreadsheet

**Prompt**
> "Get the metadata for {SPREADSHEET_ID}"

**Checks**
- `mimeType` is `application/vnd.google-apps.spreadsheet`
- `name`, `parents`, `created_time`, `modified_time`, `owners`, `web_link` all present
- `size` is absent (Google Workspace files have no size field)
- `trashed` is `false`

**Result (2026-09-04) ✅ PASS**
get_file_metadata(SPREADSHEET_ID): mimeType spreadsheet; name/parents/created_time/modified_time/owners/web_link all present; no `size` key; trashed=false. Note: owners=[] (Shared Drive files report no owners) — key present, empty list.

---

### TC-D80: Metadata for a Google Doc

**Prompt**
> "Get the metadata for {DOC_ID}"

**Checks**
- `mimeType` is `application/vnd.google-apps.document`
- `web_link` is present and opens the doc

**Result (2026-09-04) ✅ PASS**
get_file_metadata(DOC_ID): mimeType application/vnd.google-apps.document; web_link present.

---

### TC-D81: Metadata for a folder

**Prompt**
> "Get the metadata for {FOLDER_ID}"

**Checks**
- `mimeType` is `application/vnd.google-apps.folder`
- `web_link` may be absent or point to Drive folder URL

**Result (2026-09-04) ✅ PASS**
get_file_metadata(FOLDER_ID): mimeType application/vnd.google-apps.folder; web_link present (Drive folder URL).

---

### TC-D82: Non-existent file ID

**Prompt**
> "Get metadata for file 'invalidid123xyz'"

**Checks**
- API error propagates — not a silent empty result or crash

**Result (2026-09-04) ✅ PASS**
get_file_metadata('invalidid123xyz') → HttpError 404 propagates cleanly — not a silent empty result or crash.

---

### TC-D237: md5_checksum present for a binary file, null for a Google Workspace file (issue #274)

**Background:** Mirrors TC-D236 for `get_file_metadata` — same `md5Checksum` field, same Workspace-files-have-none caveat, added alongside `size`'s existing conditional-presence handling.

**Prompt**
> "Get the metadata for {BINARY_FILE_ID}" *(the PNG from `drive_transfer.md` TC-D93)*, then "Get the metadata for {SPREADSHEET_ID}"

**Checks**
- Call `get_file_metadata(file_id="{BINARY_FILE_ID}")` — `md5_checksum` is present, a 32-character hex string
- Call `get_file_metadata(file_id="{SPREADSHEET_ID}")` — `md5_checksum` is `null` (Google Workspace file)
- `{BINARY_FILE_ID}`'s `md5_checksum` matches the value `list_files` reports for the same file (TC-D236) — same field, same source

**Result (2026-07-31) ✅ PASS** — no persistent PNG fixture from `drive_transfer.md` TC-D93 currently exists in `{FOLDER_ID}` (checked live via `list_files`), so a PNG was uploaded fresh for this run instead and trashed afterward. `get_file_metadata` returned `md5_checksum: "bf2b97d8351aa217100ec405ede9d512"` for the PNG (matched `list_files`'s value for the same file) and `md5_checksum: null` for `{SPREADSHEET_ID}`.

**Result (2026-09-04) ✅ PASS**
Substituted qa-236.txt (text/plain, no persistent PNG in FOLDER_ID). get_file_metadata: md5_checksum "741fc6b1878e208346359af502dd11c5" present (32-char hex), also size "9"; matches list_files value (TC-D236). get_file_metadata(SPREADSHEET_ID): md5_checksum null (Workspace file).

---

## `list_drives`

### TC-D120: List all shared drives

**Prompt**
> "List all shared drives I have access to"

**Checks**
- Returns a list; each item has `id`, `name`, `created_time`, `capabilities`
- `capabilities` is a non-empty dict (e.g. contains `canAddChildren`)
- No error if zero shared drives accessible — returns `[]`

**Result (2026-09-04) ✅ PASS**
list_drives() → 1 drive 'mcp-gee-sweet-shared' (id 0APfXAGTeZYz3Uk9PVA = SHARED_DRIVE_ID) with id, name, created_time, and non-empty capabilities dict (canAddChildren:true present).

---

### TC-D121: Filter by name

**Fixture:** the QA environment has exactly one Shared Drive, `SHARED_DRIVE_ID`
("mcp-gee-sweet-shared"). A `name contains "Marketing"` filter should therefore return
`[]`; run a second call with `name contains "mcp-gee"` and confirm that one returns the
fixture drive.

**Prompt**
> "List shared drives whose name contains 'Marketing'", then "List shared drives whose name contains 'mcp-gee'"

**Checks**
- `query='name contains "Marketing"'` passed to API; result is `[]`
- `query='name contains "mcp-gee"'` returns exactly the `SHARED_DRIVE_ID` fixture drive
- A drive not matching the name is absent from results

**Result (2026-09-02) ✅ PASS** — live via `mcp-gee-sweet-sky` (OAuth). `list_drives(query='name contains "Marketing"')` returned `[]`; `list_drives(query='name contains "mcp-gee"')` returned exactly one drive, `mcp-gee-sweet-shared`, whose `id` matches `.env`'s `SHARED_DRIVE_ID`. Unfiltered `list_drives()` returns that same single drive.

**Result (2026-09-04) ✅ PASS**
list_drives(query='name contains "Marketing"') → `[]`; list_drives(query='name contains "mcp-gee"') → exactly the SHARED_DRIVE_ID fixture drive.

---

### TC-D122: max_results clamping

**Fixture:** with exactly one Shared Drive in the environment (`SHARED_DRIVE_ID`),
`max_results=0` exercises the clamp-to-1 path (returns the one drive, not zero). The
clamp-to-200 ceiling can't be exercised live with one drive; the clamp is inline in
`list_drives` (`max_results = min(max(1, max_results), 200)`), no dedicated unit test.

**Prompt**
> "List shared drives with max_results=0" then "List shared drives with max_results=300"

**Checks**
- `max_results=0` clamped to 1; at most 1 drive returned (not `[]`)
- `max_results=300` clamped to 200 in the API call; returns the 1 available drive

**Result (2026-09-02) ✅ PASS** — live via `mcp-gee-sweet-sky` (OAuth). `list_drives(max_results=0)` returned 1 drive (`mcp-gee-sweet-shared`), not `[]` — clamp-to-1 path confirmed. `list_drives(max_results=300)` returned the 1 available drive; the clamp-to-200 ceiling isn't directly observable with a single drive (matches this case's own note).

**Result (2026-09-04) ✅ PASS**
list_drives(max_results=0) → 1 drive (clamp-to-1, not []); list_drives(max_results=300) → 1 drive (clamp-to-200 ceiling not observable with a single drive — matches TC note).

---

### TC-D123: Pagination across multiple pages — ⏭️ permanently skipped

**Not run live, by decision (#305).** `list_drives` pagination only engages past 100
Shared Drives; provisioning 100+ Shared Drives purely to exercise `nextPageToken` is not
feasible for this project's QA account, and there is no way to force a smaller page size
through the tool. Pagination is covered by unit test
`TestListDrives::test_follows_next_page_token_across_pages` in `tests/drive/test_files.py`
(mocked two-page `nextPageToken` response). Do not mark this SKIP-for-environment on each
run — it is a standing decision, not a transient gap.

**Result (2026-09-04) ⏭️ SKIP**
env — TEST_FOLDER_2_ID retired per #305. Standing decision (not a transient gap); pagination covered by unit test TestListDrives::test_follows_next_page_token_across_pages.

---

## `list_shared_with_me`

### TC-D152: List all files shared with me

**Prompt**
> "List all files shared with me"

**Checks**
- Returns a list of files (returns empty list for service accounts — `sharedWithMe` is a user-identity concept)
- Each entry has `id`, `name`, `mimeType`, `modifiedTime`
- Query includes `sharedWithMe=true` and `trashed=false`
- `owners` field is a flat list of email strings

**Result (2026-06-21) ✅** OAuth: 50 files returned across types (spreadsheets, folders, docs, PDFs, images, videos). All have `id`, `name`, `mime_type`, `modified_time`, `owners` (flat email list), `web_link`. Ordered by `modifiedTime desc`. SA: 5 files returned — files explicitly shared with the service account (Budget & Savings spreadsheet plus 4 folders).

**Result (2026-09-04) ✅ PASS**
list_shared_with_me() → `[]` cleanly, no error. The OAuth identity here is a Workspace-org QA account (kevin@mcpsuite.io, per get_storage_quota), which has no files shared directly with it — [] is a valid result, not a tool fault. Field/ordering checks vacuous. Aziz may want to seed a shared file to exercise the non-empty path.

---

### TC-D153: Filter shared files by MIME type

**Prompt**
> "List spreadsheets shared with me"

**Checks**
- All returned files have `mimeType` of `application/vnd.google-apps.spreadsheet`
- No Docs or other types in result
- Returns empty list for service accounts (expected)

**Result (2026-06-21) ✅** OAuth: 8 spreadsheets returned, all `application/vnd.google-apps.spreadsheet`. No other MIME types present.

**Result (2026-09-04) ✅ PASS**
list_shared_with_me(mime_type=spreadsheet) → `[]` cleanly. Same env characteristic as TC-D152.

---

### TC-D154: Limit shared files with max_results

**Prompt**
> "Show me the 3 most recently shared files (max 3)"

**Checks**
- Result contains at most 3 items
- Files ordered by `modifiedTime desc`
- Returns empty list for service accounts (expected)

**Result (2026-06-21) ✅** OAuth: exactly 3 items returned — Budget & Savings, 2025 medical expenses, Tax Documents folder. Correct top-3 by `modifiedTime desc`.

**Result (2026-09-04) ✅ PASS**
list_shared_with_me(max_results=3) → `[]` cleanly (≤3 trivially). Same env characteristic as TC-D152.

---

### TC-D155: Single-quote in MIME type is escaped

Regression test for #494: the original implementation escaped `mime_type` by doubling
the quote (`''`, SQL-style) instead of backslash-escaping it (`\'`) like
`search_files`/`search_spreadsheets` do — Drive's query grammar doesn't recognize the
doubled form, so a `mime_type` containing an apostrophe live-crashed with an uncaught
`HttpError 400 "Invalid Value"` rather than returning a clean result. Fixed by switching
to the same backslash-escape convention as the sibling search tools, plus wrapping the
call in the same try/except-returns-`{"error": ...}` pattern those tools already use.

**Prompt**
> "List files shared with me, filtered to a MIME type containing an apostrophe like \"it's a test\""

**Checks**
- No Drive API syntax error and no uncaught exception (previously threw `HttpError 400 "Invalid Value"`)
- Returns `[]` (no real MIME type will match) rather than crashing
- Unit test `test_mime_type_single_quote_is_escaped` confirms `\'` (not `''`) appears in the constructed query string
- Unit test `test_api_error_returns_error_dict_not_raised` confirms a genuine API failure still returns `[{"error": ...}]` rather than propagating

**Result (2026-08-11) ✅** Live `list_shared_with_me(mime_type="it's a test")` returned `[]` cleanly, no uncaught exception. 62 unit tests in `tests/drive/test_files.py` pass. Note: `list_files` (a third sibling, same file) has the identical bug — reported as a blocking finding on PR #577, not covered by this test case.

**Result (2026-09-04) ✅ PASS**
list_shared_with_me(mime_type="it's a test") → `[]` cleanly, no HttpError 400. Backslash-escape + try/except regression fix (#494) confirmed.

---

## `list_recent_files`

### TC-D156: List recently modified files

**Prompt**
> "Show me the 10 files I've most recently modified"

**Checks**
- Returns up to 10 items ordered by `modifiedTime desc`
- Each entry has `id`, `name`, `mimeType`, `modifiedTime`
- Includes files from all drives (`includeItemsFromAllDrives=true`)

**Result (2026-06-21) ✅** Returned 10 files ordered by `modifiedTime desc`. Top item was `mcp-gee-sweet-qa-fixtures` (modified 2026-06-21T16:49). All entries have `id`, `name`, `mime_type`, `modified_time`, `owners`, `web_link`.

**Result (2026-09-04) ✅ PASS**
list_recent_files(max_results=10) → 10 items ordered by modified_time desc; each has id, name, mime_type, modified_time, web_link. Includes Shared Drive items.

---

### TC-D157: Filter by days

**Prompt**
> "List files modified in the last 7 days"

**Checks**
- Query includes `modifiedTime >` constraint for 7 days ago
- Only files modified within 7 days are returned

**Result (2026-06-21) ✅** All returned files have `modifiedTime` of 2026-06-15 or later (within 7 days of 2026-06-21). `modifiedTime >` constraint confirmed in query.

**Result (2026-09-04) ✅ PASS**
list_recent_files(days=7) → all results modified 2026-09-04 (within 7 days), ordered desc.

---

### TC-D158: Filter by MIME type

**Prompt**
> "List recent spreadsheets (last 14 days)"

**Checks**
- All results are Google Sheets (`application/vnd.google-apps.spreadsheet`)
- `modifiedTime` constraint applied correctly

**Result (2026-06-21) ✅** All 14 returned files are `application/vnd.google-apps.spreadsheet`. All have `modifiedTime` within 14 days of 2026-06-21.

**Result (2026-09-04) ✅ PASS**
list_recent_files(days=14, mime_type=spreadsheet) → all 10 results are application/vnd.google-apps.spreadsheet, all modified within 14 days.

---

### TC-D159: max_results capped at 100

**Checks (unit test)**
- Passing `max_results=500` results in `pageSize=100` in the API call

**Result (2026-06-21) ✅** Unit test confirms `pageSize=100` when `max_results=500`.

**Result (2026-09-04) ⏭️ SKIP**
unit-test-only ("Checks (unit test)"): max_results=500 → pageSize=100. Covered by tests/drive/test_files.py; not live-runnable.

---

### TC-D247: Single-quote in MIME type is escaped

Sibling of TC-D155 (#494) — `list_recent_files` had the identical bug: `mime_type`
escaped by quote-doubling (`''`) instead of backslash-escaping (`\'`), live-crashing
with `HttpError 400 "Invalid Value"` on an apostrophe. Same fix applied: backslash
escaping matching `search_files`/`search_spreadsheets`, plus the same
try/except-returns-`{"error": ...}` wrapping.

**Prompt**
> "List recently modified files, filtered to a MIME type containing an apostrophe like \"it's a test\""

**Checks**
- No Drive API syntax error and no uncaught exception (previously threw `HttpError 400 "Invalid Value"`)
- Returns `[]` (no real MIME type will match) rather than crashing
- Unit test `test_mime_type_single_quote_is_escaped` confirms `\'` (not `''`) appears in the constructed query string
- Unit test `test_api_error_returns_error_dict_not_raised` confirms a genuine API failure still returns `[{"error": ...}]` rather than propagating

**Result (2026-08-11) ✅** Live `list_recent_files(mime_type="it's a test")` returned `[]` cleanly, no uncaught exception. 62 unit tests in `tests/drive/test_files.py` pass.

**Result (2026-09-04) ✅ PASS**
list_recent_files(mime_type="it's a test") → `[]` cleanly, no HttpError 400. Backslash-escape + try/except regression fix (#494 sibling) confirmed.

---

## `get_storage_quota`

### TC-D160: Get storage quota

**Prompt**
> "How much Google Drive storage am I using?"

**Checks**
- Returns `email`, `usage_bytes`, `usage_in_drive_bytes`, `usage_in_trash_bytes`
- `limit_bytes` is `0` for service accounts (API returns `"0"` — no personal storage quota) or `None` if the key is absent
- `usage_bytes` and `usage_in_drive_bytes` are integers, not strings
- `display_name` matches the authenticated account

**Result (2026-06-21) ✅** OAuth: `limit_bytes=16106127360` (15 GB), `usage_bytes=13760121856`, `usage_in_drive_bytes=875136784`, `usage_in_trash_bytes=93860012`. All integers. SA: `limit_bytes=0` (API returned `"0"` — expected for service accounts), all usage fields 0, `display_name` is the service account email. Note: docstring corrected — SA returns `0` not `None`.

**Result (2026-09-04) ✅ PASS**
get_storage_quota() → email "kevin@mcpsuite.io", display_name "Kevin Huisman", limit_bytes 32212254720 (int), usage_bytes 103061 (int), usage_in_drive_bytes 0 (int), usage_in_trash_bytes 0 (int). All byte fields integers; all keys present.

---

### TC-D161: Fields requested include storageQuota and user

**Checks (unit test)**
- API is called with `fields` including both `storageQuota` and `user`
- No extra API calls needed to get user info

**Result (2026-06-21) ✅** Unit test confirms `fields` arg includes both `storageQuota` and `user`.

**Result (2026-09-04) ⏭️ SKIP**
unit-test-only ("Checks (unit test)"): fields arg includes storageQuota + user. Covered by unit test.

---

### TC-D162: Byte values are integers not strings

**Checks (unit test)**
- `usage_bytes`, `usage_in_drive_bytes`, `usage_in_trash_bytes` are Python `int`
- API returns these as strings (e.g. `"1073741824"`) — tool must cast them

**Result (2026-06-21) ✅** Unit test confirms all byte values are `int` after cast from API string response.

**Result (2026-09-04) ⏭️ SKIP**
unit-test-only ("Checks (unit test)"): byte values cast to int. Covered by unit test (and observed incidentally in TC-D160).

---

## `import_csv_to_sheet` (issue #187)

### TC-D169: Basic import creates a populated spreadsheet ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import the CSV at `/tmp/qa-import.csv` into a new spreadsheet called 'QA-CSV-Import' in {FOLDER_ID}" *(create `/tmp/qa-import.csv` first with a header row and 3-4 data rows, e.g. `name,age\nAlice,30\nBob,25`)*

**Checks**
- Response includes `spreadsheetId`, `title` exactly 'QA-CSV-Import', `web_link`, and `rows_written` matching the CSV's row count (including header)
- `get_sheet_data` on the new spreadsheet's default sheet returns the same rows, in order
- `drive_folder_cache.mark_dirty` fired — `list_files` on {FOLDER_ID} shows the new spreadsheet without a manual refresh

**Result (2026-07-05) ✅ PASS** Created spreadsheet with `rows_written: 4`, exact title, and a `web_link`. `get_sheet_data` returned `[["name","age"],["Alice","30"],["Bob","25"],["Carol","42"]]` — matches the source CSV exactly. `list_files` on `{FOLDER_ID}` showed the new spreadsheet immediately, confirming the folder cache invalidation.

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet(/tmp/qa-import.csv → 'QA-CSV-Import' in FOLDER_ID) → spreadsheetId, exact title, web_link, rows_written=4. get_sheet_data returned `[["name","age"],["Alice","30"],["Bob","25"],["Carol","42"]]` — exact. Appears in list_files(FOLDER_ID) with no manual refresh — folder cache invalidated.

---

### TC-D170: Custom sheet_name renames the default sheet ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import `/tmp/qa-import.csv` into a new spreadsheet called 'QA-CSV-SheetName', writing to a sheet named 'Imported Data'"

**Checks**
- `list_sheets` on the new spreadsheet shows exactly one sheet, named 'Imported Data' (not the default 'Sheet1')
- Data is present on that sheet via `get_sheet_data`

**Result (2026-07-05) ✅ PASS** `list_sheets` returned exactly `["Imported Data"]` — the default 'Sheet1' was renamed, not left as a second sheet. `get_sheet_data(sheet="Imported Data")` returned all 4 rows intact.

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet(..., sheet_name="Imported Data") → list_sheets returned exactly `["Imported Data"]` — default 'Sheet1' renamed, not a 2nd sheet. Data present (rows_written=4).

---

### TC-D171: Grid auto-expands beyond the default 1000-row limit ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import `/tmp/qa-import-large.csv` into a new spreadsheet called 'QA-CSV-Large'" *(generate a CSV with 1500+ rows first, e.g. a header plus 1500 numbered rows)*

**Checks**
- Call succeeds without a grid-limit error (the documented pre-fix failure mode from the issue)
- `rows_written` matches the CSV's row count
- `get_sheet_data` confirms the last row of data is present and readable (not silently truncated at row 1000)

**Result (2026-07-05) ✅ PASS** Imported a 1501-row CSV (header + 1500 numbered rows) with no grid-limit error — `rows_written: 1501`. Fetched `A999:B1501` and confirmed rows 998–1500 are all present and correctly ordered, including the final row `["1500","row-1500"]` — no truncation at the default 1000-row boundary.

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet(1501-row CSV → 'QA-CSV-Large') → rows_written=1501, no grid-limit error. A1499:B1501 → rows 1498/1499/1500 present with correct labels; final data row (1500) not truncated at the 1000-row boundary.

---

### TC-D172: Ragged rows padded to a common width ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import `/tmp/qa-import-ragged.csv` into a new spreadsheet called 'QA-CSV-Ragged'" *(create a CSV where some rows have fewer columns than others, e.g. `a,b,c\n1,2\n`)*

**Checks**
- No dropped or misaligned rows in `get_sheet_data` — short rows are padded with empty cells rather than shifted
- `rows_written` counts every row, including the short one

**Result (2026-07-05) ✅ PASS** CSV `a,b,c / 1,2 / 4,5,6` (middle row missing column `c`) imported with `rows_written: 3`. `get_sheet_data` returned `[["a","b","c"],["1","2"],["4","5","6"]]` — the short row landed under columns a/b with no shift, and the third row wasn't dropped. (Sheets' values.get omits the trailing empty string we pad with, which is expected — the important signal is correct alignment, not a literal empty-string round-trip.)

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet(ragged CSV a,b,c / 1,2 / 4,5,6) → rows_written=3. get_sheet_data `[["a","b","c"],["1","2"],["4","5","6"]]` — short middle row landed under a/b with no shift; third row not dropped.

---

### TC-D173: Non-existent local path (unit test)

**Checks (unit test)**
- Missing `local_path` returns `{"error": "..."}` mentioning the path — no Drive API call made

**Result:** ✅ Unit test `test_file_not_found_returns_error` confirms this — no live Drive call needed since the function returns before touching `ctx`.

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet('/tmp/does-not-exist-qa.csv') → `{"error":"File not found: /tmp/does-not-exist-qa.csv"}` — mentions the path, returns before any Drive API call. (Ran live; unit-test equivalent test_file_not_found_returns_error.)

---

### TC-D174: Non-.csv extension rejected (unit test)

**Checks (unit test)**
- A `.txt` (or other non-.csv) file returns `{"error": "..."}` mentioning `.csv`, without calling the Drive API

**Result:** ✅ Unit test `test_unsupported_extension_returns_error` confirms this.

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet('/tmp/qa-not-csv.txt') → `{"error":"Unsupported file extension '.txt'. Use .csv"}` — mentions .csv, no Drive API call. (Ran live; unit-test equivalent test_unsupported_extension_returns_error.)

---

### TC-D175: Service account Drive limitation

**Background (#680):** as with TC-D04, the default create path now succeeds for the SA (destination is the Shared Drive). Force a personal-Drive destination to still see the quota error.

**Prompt**
> "Import `/tmp/qa-import.csv` into a new spreadsheet called 'QA-CSV-SA-Limit' in folder `{PERSONAL_DRIVE_FOLDER_ID}` — I want to verify whether the service account can create in personal Drive"

**Setup:** `{PERSONAL_DRIVE_FOLDER_ID}` as in TC-D04. If unavailable this run, record SKIP(environmental) — `test_storage_quota_error_returns_helpful_message` covers the error path at unit level.

**Checks**
- 🔍 **Known limitation:** same as `create_spreadsheet` (TC-D04) — service account cannot create in personal Drive, only Shared Drives / shared folders it has access to
- Call returns `{"error": ...}` with the `_SA_QUOTA_ERROR` text

**Result (2026-07-05) ✅ PASS — superseded (#680), re-run under the personal-Drive-destination method above.** _Prior run, when the default path still targeted personal Drive:_ against `mcp-gee-sweet-sa` the call returned `{"error": "Service accounts cannot create or copy files in personal Drive (no storage quota). Use OAuth or ADC auth for full Drive write access, or use a Shared Drive destination. Check server://auth-status for your current auth method and affected tools."}` — the shared `_SA_QUOTA_ERROR` path. Not valid for v0.9.0: the default destination is now a Shared Drive where the SA succeeds.

**Result (2026-09-04) ⏭️ SKIP**
needs SA prefix + personal-Drive destination folder; Aziz to run. On OAuth (sky) with no personal-Drive folder the SA lacks quota for. Unit test test_storage_quota_error_returns_helpful_message covers the error path.

---

### TC-D179: Large CSV split across concurrent chunk writes lands correctly ⚠️ requires-oauth ⚠️ local-filesystem (issue #183)

**Background:** #183 parallelized `import_csv_to_sheet`'s chunked row-writing loop via `asyncio.gather()` — each chunk writes a disjoint row range of the same sheet concurrently instead of sequentially. Mocked unit tests confirm the request shapes are correct but can't catch a genuine race against the real Sheets API (e.g. a chunk's write landing at the wrong row offset, or two chunks' writes overlapping). This forces at least 3 concurrent chunks with distinctly identifiable content per chunk.

**Setup**
Generate a local CSV with a header row plus 12,000 data rows, where each row's first cell is its own row number (e.g. row 1's cell reads `"row-1"`, row 5000's reads `"row-5000"`). With the default `_CSV_IMPORT_CHUNK_ROWS=5000`, this produces 3 chunks (5000 + 5000 + 2000 rows).

**Prompt**
> "Import `/tmp/qa-import-183.csv` into a new spreadsheet called 'QA-CSV-Concurrent-183'"

**Checks**
- `rows_written` equals 12,001 (header + 12,000 data rows)
- Spot-check the boundary rows of each chunk (e.g. rows 1, 4999, 5000, 5001, 9999, 10000, 10001, 12000) via `get_sheet_data` — each cell's value matches its expected row-number marker, confirming no chunk landed at the wrong offset and no two chunks overlapped or clobbered each other
- No gaps: every row from 1 to 12,000 is present exactly once

**Teardown**
Delete the `QA-CSV-Concurrent-183` spreadsheet.

**Result (2026-09-04) ✅ PASS**
import_csv_to_sheet(12001-row CSV → 'QA-CSV-Concurrent-183') → rows_written=12001, no error. Boundary spot-checks: A2=row-1; A5000..A5003=row-4999/5000/5001/5002; A10000..A10003=row-9999/10000/10001/10002; A12001=row-12000. Every marker matches its expected row number — no chunk landed at a wrong offset, no overlap, no gaps across the 3 concurrent 5000/5000/2000-row chunks.

---

## `create_shortcut` (issue #141)

### TC-D206: Create a shortcut with explicit name and folder ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to be the shortcut's target — do not use the fixture spreadsheet.

**Prompt**
> "Create a new spreadsheet called 'QA-Shortcut-Target' in folder {FOLDER_ID}, then create a shortcut to it named 'QA-Shortcut-Explicit' in the same folder {FOLDER_ID}"

**Checks**
- Response has no `error`
- Response includes `shortcutId`, `name: 'QA-Shortcut-Explicit'`, `parent` matching `{FOLDER_ID}`
- `targetId` matches the target spreadsheet's `spreadsheetId`
- `targetMimeType` is `application/vnd.google-apps.spreadsheet`
- Shortcut visible in Drive at `{FOLDER_ID}`, distinguishable from the target by its shortcut icon

**Cleanup:** Trash both 'QA-Shortcut-Target' and 'QA-Shortcut-Explicit' after the test.

**Result (2026-07-22) ✅** — Created target spreadsheet, then `create_shortcut` returned `{"shortcutId": "1AOWbwtAbR9mzTtoYhNEGxOQkjSMoY7tY", "name": "QA-Shortcut-Explicit", "parent": "{FOLDER_ID}", "targetId": "<matches target spreadsheetId>", "targetMimeType": "application/vnd.google-apps.spreadsheet"}`, no error. Follow-up `list_files(folder_id={FOLDER_ID}, mime_type="application/vnd.google-apps.shortcut")` showed the shortcut present — the Drive UI's shortcut icon is derived directly from this mimeType, so this was used in place of a Playwright screenshot. Both files trashed after the test.

**Result (2026-09-04) ✅ PASS**
Created 'QA-Shortcut-Target' spreadsheet in FOLDER_ID; create_shortcut('QA-Shortcut-Explicit', folder=FOLDER_ID) → `{shortcutId, name:'QA-Shortcut-Explicit', parent:FOLDER_ID, targetId matches target, targetMimeType:'application/vnd.google-apps.spreadsheet'}`, no error. list_files(FOLDER_ID, mime_type=shortcut) shows it.

---

### TC-D207: Omitted name defaults to the target file's own name ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to be the shortcut's target.

**Prompt**
> "Create a new spreadsheet called 'QA-Shortcut-NameSource' in folder {FOLDER_ID}, then create a shortcut to it in {FOLDER_ID} without specifying a name"

**Checks**
- Response has no `error`
- Response `name` is `'QA-Shortcut-NameSource'` (matches the target, not 'Untitled' or blank)
- `targetId` matches the target spreadsheet's `spreadsheetId`

**Cleanup:** Trash both 'QA-Shortcut-NameSource' and the shortcut created from it.

**Result (2026-07-22) ✅** — `create_shortcut` with no `name` returned `{"name": "QA-Shortcut-NameSource", "targetId": "<matches target spreadsheetId>", ...}`, matching the target's own name exactly, not 'Untitled' or blank. Both files trashed after the test.

**Result (2026-09-04) ✅ PASS**
create_shortcut(target='QA-Shortcut-NameSource', no name) → `{name:'QA-Shortcut-NameSource', targetId matches, ...}` — defaults to the target's own name, not 'Untitled'/blank.

---

### TC-D208: Omitted folder_id falls back to the configured default folder ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to be the shortcut's target, in {FOLDER_ID}.

**Prompt**
> "Create a new spreadsheet called 'QA-Shortcut-DefaultFolder' in folder {FOLDER_ID}, then create a shortcut to it named 'QA-Shortcut-Default' with no folder specified"

**Checks**
- Response `parent` matches the server's configured default folder (`{FOLDER_ID}` in this fixture setup)
- `list_files` on `{FOLDER_ID}` includes 'QA-Shortcut-Default' with `mimeType: application/vnd.google-apps.shortcut`
- Confirms `drive_folder_cache.mark_dirty` fired for the parent (cache reflects the new shortcut without a manual refresh)

**Cleanup:** Trash both 'QA-Shortcut-DefaultFolder' and 'QA-Shortcut-Default'.

**Result (2026-07-22) ✅ (behavior) / environment note** — This live server has no `DRIVE_FOLDER_ID` configured, so its "configured default folder" is `My Drive` root, not `{FOLDER_ID}` — confirmed by comparison: `create_spreadsheet` with no `folder_id` also lands in the same root (`0ACZ5KALjwnmUUk9PVA`). `create_shortcut`'s fallback is consistent with this established sibling pattern, so this is an environment/config difference, not a `create_shortcut` defect — the parenthetical `({FOLDER_ID} in this fixture setup)` only holds when the server's `DRIVE_FOLDER_ID` is actually set to the fixture folder. Cache-invalidation bullet already confirmed via TC-D206's `list_files` call, which showed the new shortcut with no manual `refresh_cache`. All three probe files trashed after the test.

**Result (2026-09-04) ✅ PASS**
create_shortcut(target in FOLDER_ID, no folder_id) → `{parent:"0APfXAGTeZYz3Uk9PVA", ...}` = DRIVE_FOLDER_ID (Shared Drive root) = the server's actual configured default folder. TC parenthetical "({FOLDER_ID} in this fixture setup)" is stale post-#680/#305 — behavior is correct and consistent with create_folder/create_spreadsheet (TC-D58/D59). Shortcut is in the root, not FOLDER_ID.

---

### TC-D209: Non-existent target file ID

**Prompt**
> "Create a shortcut named 'QA-Shortcut-Bad' pointing to file ID 'invalidid123xyz' in folder {FOLDER_ID}"

**Checks**
- API error propagates cleanly — not a server crash
- Error message identifies the bad target file ID
- No shortcut left behind in `{FOLDER_ID}`

**Result (2026-07-22) ✅** — Returned `HttpError 404: "File not found: invalidid123xyz."` — propagates cleanly, no crash, names the bad ID. Follow-up `list_files(folder_id={FOLDER_ID}, mime_type="application/vnd.google-apps.shortcut")` returned an empty list — no shortcut left behind.

**Result (2026-09-04) ✅ PASS**
create_shortcut(target='invalidid123xyz', folder=FOLDER_ID, name='QA-Shortcut-Bad') → HttpError 404 "File not found: invalidid123xyz." propagates cleanly, names the bad ID, no crash. list_files(FOLDER_ID, mime_type=shortcut) shows no 'QA-Shortcut-Bad' — nothing left behind.

---
