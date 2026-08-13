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

---

### TC-D02: Create with explicit folder ID ⚠️ requires-oauth
**Prompt**
> "Create a new spreadsheet called 'QA-Create-Explicit' in folder {FOLDER_ID}"

**Checks**
- Spreadsheet appears in the specified folder
- Response includes the correct folder reference

---

### TC-D03: Create without a folder (root of Drive) ⚠️ requires-oauth
**Prompt**
> "Create a new spreadsheet called 'QA-Create-Root' with no folder specified"

**Checks**
- Spreadsheet created at Drive root
- No folder assignment in response
- 🔍 **Note:** service account may not have access to personal Drive root — note error if seen

---

### TC-D04: Service account Drive limitation

**Prompt**
> "Create a spreadsheet called 'QA-SA-Limit' — I want to verify whether the service account can create in personal Drive"

**Checks**
- 🔍 **Known limitation:** service account cannot create in personal Drive (only shared folders it has access to)
- Note exact error if it fails — confirm it matches the documented limitation

---

### TC-D05: Drive folder cache invalidated ⚠️ requires-oauth
**Prompt**
> "Create a spreadsheet called 'QA-Cache-Check' in {FOLDER_ID}, then list the files in that folder"

**Checks**
- `list_files` includes 'QA-Cache-Check'
- Confirms `drive_folder_cache.mark_dirty` fired after creation

---

### TC-D06: Resulting spreadsheet has expected title ⚠️ requires-oauth
**Prompt**
> "Create a spreadsheet called 'Exact Title Test' and confirm the title in the response"

**Checks**
- Response title is exactly 'Exact Title Test' — no truncation or modification

---

## `list_spreadsheets`

### TC-D13: List from configured folder

**Prompt**
> "List all spreadsheets in my default Drive folder"

**Checks**
- Returns a list of spreadsheets
- Includes 'mcp-gee-sweet-qa-fixtures' (created in setup)
- Each entry has a name and ID

---

### TC-D14: List from explicit folder ID

**Prompt**
> "List spreadsheets in folder {FOLDER_ID}"

**Checks**
- Returns spreadsheets from that specific folder
- Results scoped to the given folder

---

### TC-D15: List from root (no folder)

**Prompt**
> "List spreadsheets at the root of my Drive — no folder filter"

**Checks**
- Returns spreadsheets from Drive root (or all accessible spreadsheets)
- 🔍 **Product decision:** "root" vs "all accessible" — note which behavior is observed

---

### TC-D16: Empty folder

**Prompt**
> "List spreadsheets in a folder that has no spreadsheets — use a folder ID with only docs or no files"

**Checks**
- Returns `[]` — not an error

---

### TC-D17: Pagination not implemented

**Prompt**
> "List spreadsheets in {FOLDER_ID}"

**Checks**
- 🔍 **Known limitation:** if the folder has >100 spreadsheets, results are silently truncated
- Note the count returned and whether a `nextPageToken` is visible in any debug output

---

## `list_folders`

### TC-D26: List folders in a specific parent

**Prompt**
> "List the folders inside {FOLDER_ID}"

**Checks**
- Returns a list of folder names and IDs (or empty list if no subfolders)
- Each entry is a folder, not a file

---

### TC-D27: List from root

**Prompt**
> "List folders at the root of my Drive"

**Checks**
- Returns top-level folders
- Confirms `'root' in parents` filter is applied

---

### TC-D28: Empty folder

**Prompt**
> "List folders in a folder that has no subfolders"

**Checks**
- Returns `[]` — not an error
- 🔍 **Known limitation:** pagination not implemented — >100 subfolders would silently truncate

---

## `search_spreadsheets`

### TC-D29: Basic name search

**Prompt**
> "Search for spreadsheets with 'qa-fixtures' in the name"

**Checks**
- Returns at least one result including 'mcp-gee-sweet-qa-fixtures'
- Each result has a name and ID

---

### TC-D30: Content search

**Prompt**
> "Search spreadsheets for the text 'Widget' — search file contents"

**Checks**
- Returns spreadsheets containing 'Widget' in their content
- Includes {SPREADSHEET_ID} (Sales sheet has 'Widget' in A2)

---

### TC-D31: max_results respected

**Prompt**
> "Search for spreadsheets matching 'test' but limit results to 2"

**Checks**
- Returns at most 2 results
- Confirms `max_results` clamped to 1–100

---

### TC-D32: Query with a single quote — injection fix

**Prompt**
> "Search for spreadsheets with \"it's\" in the name"

**Checks**
- No Drive API syntax error
- Returns results (possibly empty) without crashing
- Confirms the query injection bug fix: `'` → `\'` before embedding

---

### TC-D33: No results

**Prompt**
> "Search for spreadsheets named 'ZZZAbsolutelyNoMatch12345'"

**Checks**
- Returns `[]` — not an error

---

### TC-D34: Empty query string

**Prompt**
> "Search for spreadsheets with an empty search query"

**Checks**
- 🔍 **Product decision:** returns all accessible spreadsheets, or an error for empty query?
- Note observed behavior

---

### TC-D35: API error

**Prompt**
> "Search for spreadsheets using an invalid API key scenario — force an auth error if possible"

**Checks**
- Returns `[{"error": ...}]` — not a top-level exception
- Error message is from the Drive API

---

## `list_files`

### TC-D36: List all files in a folder (no MIME type filter)

**Prompt**
> "List all files in folder {FOLDER_ID}"

**Checks**
- Returns both spreadsheets and docs
- Each entry has a name, ID, and MIME type
- Trashed files not included

---

### TC-D37: Filter by MIME type

**Prompt**
> "List only Google Docs (not spreadsheets) in folder {FOLDER_ID}"

**Checks**
- Returns only items with `mimeType = application/vnd.google-apps.document`
- Spreadsheets excluded

---

### TC-D38: Cache hit on second call

**Prompt** (run twice)
> "List files in {FOLDER_ID} again"

**Checks**
- Second call returns same results
- Logs show `cache hit` for the second call

---

### TC-D39: mime_type=None cache key

**Prompt**
> "List all files in {FOLDER_ID} with no MIME type filter, twice in a row"

**Checks**
- Both calls return the same results
- Cache key with `None` MIME type works correctly — no KeyError or cache miss

---

### TC-D40: max_results clamped

**Prompt**
> "List files in {FOLDER_ID} with a max of 2 results"

**Checks**
- Returns at most 2 files
- Confirms `max_results` clamped to 1–1000

---

### TC-D41: Pagination limit

**Prompt**
> "List files in a folder with many files"

**Checks**
- 🔍 **Known limitation:** >1000 files silently truncated — note count if relevant

---

### TC-D42: Trashed files excluded

**Prompt**
> "List files in {FOLDER_ID}"

**Checks**
- Trashed files not in results
- Confirms `trashed=false` is in the Drive query

---

### TC-D43: Cache invalidated after create ⚠️ requires-oauth
**Prompt**
> "Create a spreadsheet called 'QA-ListFilesCache' in {FOLDER_ID}, then list files in that folder"

**Checks**
- New spreadsheet appears in `list_files` results
- Confirms `drive_folder_cache.mark_dirty` fires after `create_spreadsheet`

---

### TC-D236: md5_checksum present for a binary file, null for a Google Workspace file (issue #274) ⚠️ local-filesystem

**Background:** `list_files` now surfaces Drive's `md5Checksum` field so callers can diff content directly instead of inferring change from `modifiedTime` alone, which upload paths like `upload_local_file` don't always keep in sync with actual content (see TC-D226's follow-up finding). `{FOLDER_ID}` already contains both `{SPREADSHEET_ID}` and `{DOC_ID}` (per `setup.md`), so no new Workspace fixture needs creating here.

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

---

## `create_folder`

### TC-D58: Create in default folder ⚠️ requires-oauth

**Prompt**
> "Create a new folder called 'QA-Folder-Test' in my default folder"

**Checks**
- Response includes a `folderId` and `name: 'QA-Folder-Test'`
- `parent` matches `{FOLDER_ID}`
- Folder visible in Drive

---

### TC-D59: Create at root (no parent) ⚠️ requires-oauth

**Prompt**
> "Create a folder called 'QA-Folder-Root' with no parent folder specified"

**Checks**
- Folder created without error
- `parent` is `root` or omitted
- 🔍 **Note:** service account may not have access to personal Drive root — record error if seen

---

### TC-D60: Cache invalidated after create ⚠️ requires-oauth

**Prompt**
> "Create a folder called 'QA-Folder-Cache' in {FOLDER_ID}, then list files in that folder"

**Checks**
- `list_files` result includes 'QA-Folder-Cache' with `mimeType: application/vnd.google-apps.folder`
- Confirms `drive_folder_cache.mark_dirty` fired for the parent

---

## `move_file`

### TC-D61: Move a file to another folder ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to move — do not use the fixture spreadsheet.

**Prompt**
> "Create a new spreadsheet called 'QA-Move-Test' in folder {FOLDER_ID}, then move it to the root of My Drive, then confirm its new parent"

**Checks**
- Response includes `fileId`, `name`, and updated `parent` no longer matching `{FOLDER_ID}`
- Both old and new parent caches invalidated — subsequent `list_files` reflects the change

**Cleanup:** Trash 'QA-Move-Test' after the test.

---

### TC-D62: Move a folder

**Prompt**
> "Move the folder created in TC-D58 ('QA-Folder-Test') into {FOLDER_ID} — use its folder ID"

**Checks**
- Folder now nested inside `{FOLDER_ID}`
- `mimeType` in response is `application/vnd.google-apps.folder`

---

### TC-D63: Non-existent file ID

**Prompt**
> "Move file 'invalidid123xyz' to {FOLDER_ID}"

**Checks**
- API error propagates cleanly — not a server crash
- Error message identifies the bad file ID

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

---

### TC-D65: Rename a folder

**Prompt**
> "Rename the 'QA-Folder-Cache' folder (from TC-D60) to 'QA-Folder-Renamed'"

**Checks**
- Folder name updated in Drive
- Response `name` is 'QA-Folder-Renamed'

---

### TC-D66: Non-existent file ID

**Prompt**
> "Rename file 'invalidid123xyz' to 'SomeName'"

**Checks**
- API error propagates — not a crash or silent failure

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

---

### TC-D68: Copy with explicit name and destination folder ⚠️ requires-oauth
**Prompt**
> "Copy {SPREADSHEET_ID} into {FOLDER_ID} and name the copy 'QA-Copy-Explicit'"

**Checks**
- New file named 'QA-Copy-Explicit' appears in `{FOLDER_ID}`
- Destination folder cache invalidated — `list_files` includes the copy
- Original `{SPREADSHEET_ID}` is unchanged

---

### TC-D69: Copy a Google Doc ⚠️ requires-oauth
**Prompt**
> "Copy {DOC_ID} and name it 'QA-Doc-Copy'"

**Checks**
- New doc created independently of the original
- `mimeType` is `application/vnd.google-apps.document`
- Edits to the copy do not affect the original

---

### TC-D70: Attempt to copy a folder ⚠️ requires-oauth

**Prompt**
> "Copy the folder from TC-D65 ('QA-Folder-Renamed') to see if folder copy is supported"

**Checks**
- 🔍 **Known API limitation:** Drive API does not support copying folders — expect an API error
- Error message should be clear, not a server crash

---

## `delete_file`

### TC-D71: Trash a file (default — recoverable) ⚠️ destructive

**Prompt**
> "Trash the file 'QA-Renamed-File' from TC-D64 — use permanent=False"

**Checks**
- Response: `{"fileId": ..., "action": "trashed"}`
- File no longer appears in `list_files` for its folder (trashed files excluded)
- File is recoverable from Drive Trash

---

### TC-D72: Permanently delete a file ⚠️ requires-oauth ⚠️ destructive

**Setup:** Create a throwaway spreadsheet to permanently delete.

**Prompt**
> "Create a new spreadsheet called 'QA-Delete-Permanent' in folder {FOLDER_ID}, then permanently delete it using permanent=True"

**Checks**
- Response: `{"fileId": ..., "action": "deleted"}`
- File is completely gone — not in Trash, not in any folder
- Parent folder cache invalidated

---

### TC-D73: Trash a folder ⚠️ destructive

**Prompt**
> "Trash the 'QA-Folder-Renamed' folder from TC-D65"

**Checks**
- Folder and its contents moved to Trash
- `list_folders` no longer shows it in the parent

---

### TC-D74: Non-existent file ID

**Prompt**
> "Delete file 'invalidid123xyz'"

**Checks**
- API error propagates — not a crash
- No cache mutation occurs for a non-existent file

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

---

### TC-D205: Empty trash scoped to a specific Shared Drive ⚠️ destructive

**Requires a Shared Drive fixture the QA account has access to** — get its ID via `list_drives`. If no Shared Drive is available in the current QA environment, skip this case and note it as such rather than fabricating a result.

**⚠️ This empties every file in the *named Shared Drive's* trash**, not just files created by this QA run, and does not touch My Drive's trash.

**Setup:** In the target Shared Drive, create a throwaway file and trash it.

**Prompt**
> "Empty the trash for Shared Drive {SHARED_DRIVE_ID}"

**Checks**
- Response: `{"action": "trash_emptied", "drive_id": "{SHARED_DRIVE_ID}"}`
- The throwaway file from Setup is now permanently gone from that Shared Drive
- My Drive's own trash (if it has unrelated trashed files) is unaffected

**Result (2026-07-21) skipped** — `list_drives` returned no Shared Drives accessible to this QA account. Unit test `test_empty_trash_with_drive_id_scopes_to_shared_drive` confirms the `driveId` passthrough via mock; no live Shared Drive fixture currently exists to verify end-to-end.

---

## `search_files`

### TC-D75: Search by name across all MIME types

**Prompt**
> "Search files for 'QA' — no MIME type filter"

**Checks**
- Returns a mix of docs, spreadsheets, and folders created during QA
- Each result has `id`, `name`, `mimeType`, `modified_time`, and `web_link`

---

### TC-D76: Search with MIME type filter

**Prompt**
> "Search for files named 'QA' that are Google Docs only"

**Checks**
- All results have `mimeType: application/vnd.google-apps.document`
- Spreadsheets and folders excluded

---

### TC-D77: Search with folder filter

**Prompt**
> "Search for files with 'QA' in the name, but only in {FOLDER_ID}"

**Checks**
- All results have `parent` matching `{FOLDER_ID}`
- Files from other folders excluded

---

### TC-D78: Query with single quote

**Prompt**
> "Search files for \"it's a test\""

**Checks**
- No Drive API syntax error
- Returns results (possibly empty) — confirms `'` is safely escaped

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

---

### TC-D80: Metadata for a Google Doc

**Prompt**
> "Get the metadata for {DOC_ID}"

**Checks**
- `mimeType` is `application/vnd.google-apps.document`
- `web_link` is present and opens the doc

---

### TC-D81: Metadata for a folder

**Prompt**
> "Get the metadata for {FOLDER_ID}"

**Checks**
- `mimeType` is `application/vnd.google-apps.folder`
- `web_link` may be absent or point to Drive folder URL

---

### TC-D82: Non-existent file ID

**Prompt**
> "Get metadata for file 'invalidid123xyz'"

**Checks**
- API error propagates — not a silent empty result or crash

---

### TC-D237: md5_checksum present for a binary file, null for a Google Workspace file (issue #274)

**Background:** Mirrors TC-D236 for `get_file_metadata` — same `md5Checksum` field, same Workspace-files-have-none caveat, added alongside `size`'s existing conditional-presence handling.

**Prompt**
> "Get the metadata for {BINARY_FILE_ID}" *(the PNG from TC-D93)*, then "Get the metadata for {SPREADSHEET_ID}"

**Checks**
- Call `get_file_metadata(file_id="{BINARY_FILE_ID}")` — `md5_checksum` is present, a 32-character hex string
- Call `get_file_metadata(file_id="{SPREADSHEET_ID}")` — `md5_checksum` is `null` (Google Workspace file)
- `{BINARY_FILE_ID}`'s `md5_checksum` matches the value `list_files` reports for the same file (TC-D236) — same field, same source

**Result (2026-07-31) ✅ PASS** — no persistent PNG fixture from TC-D93 currently exists in `{FOLDER_ID}` (checked live via `list_files`), so a PNG was uploaded fresh for this run instead and trashed afterward. `get_file_metadata` returned `md5_checksum: "bf2b97d8351aa217100ec405ede9d512"` for the PNG (matched `list_files`'s value for the same file) and `md5_checksum: null` for `{SPREADSHEET_ID}`.

---

## `list_drives`

### TC-D120: List all shared drives

**Prompt**
> "List all shared drives I have access to"

**Checks**
- Returns a list; each item has `id`, `name`, `created_time`, `capabilities`
- `capabilities` is a non-empty dict (e.g. contains `canAddChildren`)
- No error if zero shared drives accessible — returns `[]`

---

### TC-D121: Filter by name

**Prompt**
> "List shared drives whose name contains 'Marketing'"

**Checks**
- `query='name contains "Marketing"'` passed to API
- Only drives matching the filter are returned
- Drives not matching the name are absent from results

---

### TC-D122: max_results clamping

**Prompt**
> "List shared drives with max_results=0" then "List shared drives with max_results=300"

**Checks**
- `max_results=0` clamped to 1; at most 1 drive returned
- `max_results=300` clamped to 200; no more than 200 drives returned

---

### TC-D123: Pagination across multiple pages

**Setup:** environment with more than 100 shared drives (or simulate via mock)

**Prompt**
> "List all shared drives with max_results=150"

**Checks**
- `nextPageToken` followed; second page fetched
- Total results ≤ 150
- No duplicate drives across pages

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

---

### TC-D153: Filter shared files by MIME type

**Prompt**
> "List spreadsheets shared with me"

**Checks**
- All returned files have `mimeType` of `application/vnd.google-apps.spreadsheet`
- No Docs or other types in result
- Returns empty list for service accounts (expected)

**Result (2026-06-21) ✅** OAuth: 8 spreadsheets returned, all `application/vnd.google-apps.spreadsheet`. No other MIME types present.

---

### TC-D154: Limit shared files with max_results

**Prompt**
> "Show me the 3 most recently shared files (max 3)"

**Checks**
- Result contains at most 3 items
- Files ordered by `modifiedTime desc`
- Returns empty list for service accounts (expected)

**Result (2026-06-21) ✅** OAuth: exactly 3 items returned — Budget & Savings, 2025 medical expenses, Tax Documents folder. Correct top-3 by `modifiedTime desc`.

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

---

### TC-D157: Filter by days

**Prompt**
> "List files modified in the last 7 days"

**Checks**
- Query includes `modifiedTime >` constraint for 7 days ago
- Only files modified within 7 days are returned

**Result (2026-06-21) ✅** All returned files have `modifiedTime` of 2026-06-15 or later (within 7 days of 2026-06-21). `modifiedTime >` constraint confirmed in query.

---

### TC-D158: Filter by MIME type

**Prompt**
> "List recent spreadsheets (last 14 days)"

**Checks**
- All results are Google Sheets (`application/vnd.google-apps.spreadsheet`)
- `modifiedTime` constraint applied correctly

**Result (2026-06-21) ✅** All 14 returned files are `application/vnd.google-apps.spreadsheet`. All have `modifiedTime` within 14 days of 2026-06-21.

---

### TC-D159: max_results capped at 100

**Checks (unit test)**
- Passing `max_results=500` results in `pageSize=100` in the API call

**Result (2026-06-21) ✅** Unit test confirms `pageSize=100` when `max_results=500`.

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

---

### TC-D161: Fields requested include storageQuota and user

**Checks (unit test)**
- API is called with `fields` including both `storageQuota` and `user`
- No extra API calls needed to get user info

**Result (2026-06-21) ✅** Unit test confirms `fields` arg includes both `storageQuota` and `user`.

---

### TC-D162: Byte values are integers not strings

**Checks (unit test)**
- `usage_bytes`, `usage_in_drive_bytes`, `usage_in_trash_bytes` are Python `int`
- API returns these as strings (e.g. `"1073741824"`) — tool must cast them

**Result (2026-06-21) ✅** Unit test confirms all byte values are `int` after cast from API string response.

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

---

### TC-D170: Custom sheet_name renames the default sheet ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import `/tmp/qa-import.csv` into a new spreadsheet called 'QA-CSV-SheetName', writing to a sheet named 'Imported Data'"

**Checks**
- `list_sheets` on the new spreadsheet shows exactly one sheet, named 'Imported Data' (not the default 'Sheet1')
- Data is present on that sheet via `get_sheet_data`

**Result (2026-07-05) ✅ PASS** `list_sheets` returned exactly `["Imported Data"]` — the default 'Sheet1' was renamed, not left as a second sheet. `get_sheet_data(sheet="Imported Data")` returned all 4 rows intact.

---

### TC-D171: Grid auto-expands beyond the default 1000-row limit ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import `/tmp/qa-import-large.csv` into a new spreadsheet called 'QA-CSV-Large'" *(generate a CSV with 1500+ rows first, e.g. a header plus 1500 numbered rows)*

**Checks**
- Call succeeds without a grid-limit error (the documented pre-fix failure mode from the issue)
- `rows_written` matches the CSV's row count
- `get_sheet_data` confirms the last row of data is present and readable (not silently truncated at row 1000)

**Result (2026-07-05) ✅ PASS** Imported a 1501-row CSV (header + 1500 numbered rows) with no grid-limit error — `rows_written: 1501`. Fetched `A999:B1501` and confirmed rows 998–1500 are all present and correctly ordered, including the final row `["1500","row-1500"]` — no truncation at the default 1000-row boundary.

---

### TC-D172: Ragged rows padded to a common width ⚠️ requires-oauth ⚠️ local-filesystem
**Prompt**
> "Import `/tmp/qa-import-ragged.csv` into a new spreadsheet called 'QA-CSV-Ragged'" *(create a CSV where some rows have fewer columns than others, e.g. `a,b,c\n1,2\n`)*

**Checks**
- No dropped or misaligned rows in `get_sheet_data` — short rows are padded with empty cells rather than shifted
- `rows_written` counts every row, including the short one

**Result (2026-07-05) ✅ PASS** CSV `a,b,c / 1,2 / 4,5,6` (middle row missing column `c`) imported with `rows_written: 3`. `get_sheet_data` returned `[["a","b","c"],["1","2"],["4","5","6"]]` — the short row landed under columns a/b with no shift, and the third row wasn't dropped. (Sheets' values.get omits the trailing empty string we pad with, which is expected — the important signal is correct alignment, not a literal empty-string round-trip.)

---

### TC-D173: Non-existent local path (unit test)

**Checks (unit test)**
- Missing `local_path` returns `{"error": "..."}` mentioning the path — no Drive API call made

**Result:** ✅ Unit test `test_file_not_found_returns_error` confirms this — no live Drive call needed since the function returns before touching `ctx`.

---

### TC-D174: Non-.csv extension rejected (unit test)

**Checks (unit test)**
- A `.txt` (or other non-.csv) file returns `{"error": "..."}` mentioning `.csv`, without calling the Drive API

**Result:** ✅ Unit test `test_unsupported_extension_returns_error` confirms this.

---

### TC-D175: Service account Drive limitation

**Prompt**
> "Import `/tmp/qa-import.csv` into a new spreadsheet called 'QA-CSV-SA-Limit' — I want to verify whether the service account can create in personal Drive"

**Checks**
- 🔍 **Known limitation:** same as `create_spreadsheet` (TC-D04) — service account cannot create in personal Drive, only shared folders it has access to
- Unit-level equivalent already covered: `test_storage_quota_error_returns_helpful_message`

**Result (2026-07-05) ✅ PASS** Against the service-account server (`mcp-gee-sweet-sa`), the call returned `{"error": "Service accounts cannot create or copy files in personal Drive (no storage quota). Use OAuth or ADC auth for full Drive write access, or use a Shared Drive destination. Check server://auth-status for your current auth method and affected tools."}` — the same `_SA_QUOTA_ERROR` message `create_spreadsheet` returns, confirming the shared error path works for this tool too.

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

---

### TC-D209: Non-existent target file ID

**Prompt**
> "Create a shortcut named 'QA-Shortcut-Bad' pointing to file ID 'invalidid123xyz' in folder {FOLDER_ID}"

**Checks**
- API error propagates cleanly — not a server crash
- Error message identifies the bad target file ID
- No shortcut left behind in `{FOLDER_ID}`

**Result (2026-07-22) ✅** — Returned `HttpError 404: "File not found: invalidid123xyz."` — propagates cleanly, no crash, names the bad ID. Follow-up `list_files(folder_id={FOLDER_ID}, mime_type="application/vnd.google-apps.shortcut")` returned an empty list — no shortcut left behind.

---
