# Drive Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive.py`

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

## `create_doc`

### TC-D07: Create with no content ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Empty-Doc' with no content"

**Checks**
- Doc created successfully
- No `batchUpdate` call made (no content to write)
- Response includes doc ID and web link

---

### TC-D08: Create with HTML content — formatting preserved ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Formatted-Doc' with this content: `<h1>Main Title</h1><p>A paragraph.</p><ul><li>Item A</li><li>Item B</li></ul>`"

**Checks**
- Doc created with correct title
- Open the doc in a browser: heading renders as H1, bullets render as a list
- Confirms the `create_doc` bug fix: uses `_html_to_doc_requests`, not `_html_to_text`

---

### TC-D09: Create with a link ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Link-Doc' with content: `<p>Visit <a href=\"https://example.com\">Example</a></p>`"

**Checks**
- Doc created
- Open in browser: "Example" is a clickable link to https://example.com

---

### TC-D10: Content with no block-level elements — batchUpdate skipped ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Inline-Doc' with content: `<span>just a span</span>`"

**Checks**
- Doc created without error
- No `batchUpdate` call (inline-only HTML produces no requests)
- Doc body is empty (span is not a block element)

---

### TC-D11: Drive folder cache invalidated ⚠️ requires-oauth
**Prompt**
> "Create a doc called 'QA-DocCache' in {FOLDER_ID}, then list the files in that folder"

**Checks**
- `list_files` includes 'QA-DocCache'
- Confirms `drive_folder_cache.mark_dirty` fires after doc creation

---

### TC-D12: Long content ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Long-Doc' with a very long paragraph — repeat the word 'test ' 500 times as the body content"

**Checks**
- Doc created without error
- Content visible in the doc
- Note any API size limit errors

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

## `share_spreadsheet`

### TC-D18: Share as writer

**Prompt**
> "Share {SPREADSHEET_ID} with test-recipient@example.com as a writer"

**Checks**
- Returns success for that recipient
- No entries in `failures`

---

### TC-D19: Share as reader

**Prompt**
> "Share {SPREADSHEET_ID} with test-recipient@example.com as a reader"

**Checks**
- Permission granted as reader
- No `failures`

---

### TC-D20: Share as commenter

**Prompt**
> "Share {SPREADSHEET_ID} with test-recipient@example.com as a commenter"

**Checks**
- Permission granted as commenter
- No `failures`

---

### TC-D21: Invalid role

**Prompt**
> "Share {SPREADSHEET_ID} with test@example.com as an 'owner'"

**Checks**
- Entry goes to `failures` list (invalid role)
- Returns a message indicating the role is not accepted

---

### TC-D22: Missing email address key

**Prompt**
> "Share {SPREADSHEET_ID} — pass a recipient object with no email_address field"

**Checks**
- Entry goes to `failures` with `None` email
- Does not throw an unhandled exception

---

### TC-D23: Mixed success and failure

**Prompt**
> "Share {SPREADSHEET_ID} with two recipients: valid@example.com as writer, and a second recipient with an invalid role 'superuser'"

**Checks**
- valid@example.com in success list
- Invalid role entry in `failures`
- Both results present in the same response

---

### TC-D24: send_notification=False

**Prompt**
> "Share {SPREADSHEET_ID} with test@example.com as reader but don't send them a notification email"

**Checks**
- Share succeeds
- No notification email sent (verify by using an email you control)

---

### TC-D25: Non-existent spreadsheet ID

**Prompt**
> "Share spreadsheet 'invalidid123xyz' with test@example.com as reader"

**Checks**
- API error goes to `failures` list — not a top-level exception
- 🔍 **Danger check:** no ownership validation before sharing — note that any accessible spreadsheet ID can be shared

---

### TC-D176: Concurrent multi-recipient share — no cross-attribution (issue #183)

**Background:** #183 made `share_spreadsheet` issue its per-recipient `permissions().create()` calls concurrently via `asyncio.gather()` instead of one at a time. Mocked unit tests can't catch a genuine race against the real Drive API — this exercises enough distinct, identifiable recipients at once to surface any result mixed up between concurrent calls (wrong role or permissionId attributed to the wrong email).

**Prompt**
> "Share {SPREADSHEET_ID} with these 5 recipients at once: recipient1@example.com as reader, recipient2@example.com as commenter, recipient3@example.com as writer, recipient4@example.com as reader, recipient5@example.com as writer"

**Checks**
- All 5 entries appear in `successes`, none in `failures`
- Each entry's `email_address` and `role` in the response exactly match what was requested for that recipient — cross-check every one individually, not just the count
- `list_permissions` on the spreadsheet afterward confirms each of the 5 emails actually has the role it was assigned (not swapped with another recipient's)

**Teardown**
`remove_permission` for each of the 5 test recipients.

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

## `get_doc_content`

### TC-D44: Happy path

**Prompt**
> "Get the content of doc {DOC_ID}"

**Checks**
- Returns text content with the expected HTML: heading, paragraph, list items
- Response includes metadata (title, web link)
- No `error` field

---

### TC-D45: Cache hit on second call

**Prompt** (run twice)
> "Get the content of doc {DOC_ID} again"

**Checks**
- Second call returns same content
- Logs show `cache hit`

---

### TC-D46: Non-Google-Doc file ID

**Prompt**
> "Get the content of {SPREADSHEET_ID} using get_doc_content"

**Checks**
- Drive export API returns an error (spreadsheets can't be exported as plain text this way)
- Error propagates cleanly — not a server crash

---

### TC-D47: Non-existent file ID

**Prompt**
> "Get the content of doc 'invalidid123xyz'"

**Checks**
- Returns a clear API error
- Not a silent empty response

---

### TC-D48: Large document

**Prompt**
> "Get the content of a large Google Doc — if you have one, use its ID"

**Checks**
- Content returned without timeout or truncation
- Note any response size limits observed

---

### TC-D49: Content decode branch

**Prompt**
> "Get the content of {DOC_ID} and tell me if the content came back as bytes or a string"

**Checks**
- Content decoded correctly regardless of whether the API returns bytes or string
- 🔍 **Implementation note:** `content.decode("utf-8")` vs already-string branch in `drive.py`

---

## `write_doc_content`

### TC-D50: Write to an empty doc ⚠️ requires-oauth
**Prompt**
> "Create a new empty doc called 'QA-WriteEmpty', then write this content to it: `<h1>Hello</h1><p>World</p>`"

**Checks**
- Doc content replaced with heading and paragraph
- `end_index=2` path taken (doc was empty — no delete step needed)
- Open in browser to verify formatting

---

### TC-D51: Write to a doc with existing content ⚠️ destructive

**Prompt**
> "Overwrite the content of {DOC_ID} with: `<h2>Replaced</h2><p>New content only.</p>`"

**Checks**
- Previous content cleared
- New heading and paragraph visible in the doc
- `doc_cache.mark_dirty` called — next `get_doc_content` re-fetches

---

### TC-D52: HTML with headings and bullets

**Prompt**
> "Write this HTML to {DOC_ID}: `<h1>Title</h1><h2>Subtitle</h2><ul><li>A</li><li>B</li></ul><p>Footer</p>`"

**Checks**
- H1 renders as Heading 1, H2 as Heading 2
- A and B render as bullet list items
- Footer renders as normal paragraph

---

### TC-D53: HTML with a link

**Prompt**
> "Write this to {DOC_ID}: `<p>Click <a href=\"https://example.com\">here</a> for more</p>`"

**Checks**
- "here" is a clickable hyperlink to https://example.com
- Surrounding text renders as normal paragraph

> **Note:** `write_doc_content` replaces the full document content, so this test is self-contained regardless of run order.

---

### TC-D54: HTML with no recognizable tags

**Prompt**
> "Write `<span>no blocks here</span>` to {DOC_ID}"

**Checks**
- Existing content cleared (delete step runs)
- Nothing inserted (span produces no block-level requests)
- Doc body is empty

---

### TC-D55: Empty string content

**Prompt**
> "Write an empty string to {DOC_ID}"

**Checks**
- Existing content cleared
- Nothing inserted
- Doc body is empty

---

### TC-D56: Very long content

**Prompt**
> "Write a very long document to {DOC_ID} — use 100 paragraphs each with 50 words of placeholder text"

**Checks**
- Writes successfully or returns a clear API size limit error (~2MB per batchUpdate request)
- Note any limit encountered

> **Note:** Content is generated inline by the conductor — no fixture file needed.

---

### TC-D57: Cache invalidated after write

**Prompt**
> "Write `<p>CacheTest</p>` to {DOC_ID}, then immediately get the doc content"

**Checks**
- `get_doc_content` returns 'CacheTest' — not the old cached version
- Confirms `doc_cache.mark_dirty` fires after write

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

**Result (2026-07-21) held, not run** — Code review found `empty_trash` omits Shared Drive scoping (`driveId`), meaning it currently only empties the caller's My Drive trash rather than "every file currently in the trash" as documented — see PR comment. Since this behavior is likely to change once that's addressed, holding off on live-testing the current implementation against the account's real trash rather than exercising code expected to be redesigned.

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

## `export_file`

### TC-D83: Export Google Doc as plain text

**Prompt**
> "Export {DOC_ID} as plain text"

**Checks**
- Response `encoding` is `utf-8`
- `content` is a plain text string matching the doc's text
- `format` is `txt`

---

### TC-D84: Export Google Doc as HTML

**Prompt**
> "Export {DOC_ID} as HTML"

**Checks**
- Response `encoding` is `utf-8`
- `content` is an HTML string with `<html>` tags
- Headings and lists from the doc visible as HTML elements

---

### TC-D85: Export Google Doc as PDF (binary)

**Prompt**
> "Export {DOC_ID} as PDF"

**Checks**
- Response `encoding` is `base64`
- `content` is a non-empty base64 string
- Decoding it produces a valid PDF (starts with `%PDF`)

---

### TC-D86: Export Google Sheet as CSV

**Prompt**
> "Export {SPREADSHEET_ID} as CSV"

**Checks**
- Response `encoding` is `utf-8`
- `content` is comma-separated text matching the sheet's data

---

### TC-D87: Unknown export format

**Prompt**
> "Export {DOC_ID} in format 'xyz'"

**Checks**
- Returns a `ValueError` with a message listing valid formats
- Not a server crash

---

## `upload_file`

### TC-D88: Upload plain text file ⚠️ requires-oauth
**Prompt**
> "Upload a plain text file called 'qa-upload.txt' to {FOLDER_ID} with content 'Hello from QA'"

**Checks**
- File appears in `{FOLDER_ID}` with `mimeType: text/plain`
- `name` is 'qa-upload.txt'
- Folder cache invalidated — `list_files` shows the new file

---

### TC-D89: Upload Markdown as raw file (no conversion) ⚠️ requires-oauth
**Prompt**
> "Upload a markdown file called 'qa-notes.md' to {FOLDER_ID} with content '# Heading\n\n- item 1\n- item 2' and do not convert it to a doc"

**Checks**
- File created with `mimeType: text/markdown` (or `text/plain` — note whichever)
- Markdown syntax is preserved as literal text — no conversion
- `convert_to_doc` was `False`

---

### TC-D90: Upload Markdown and convert to Google Doc ⚠️ destructive
**Prompt**
> "Upload this markdown to {FOLDER_ID} as a Google Doc called 'QA-Markdown-Doc': `# My Title\n\n## Section One\n\n- Bullet A\n- Bullet B\n\nSome **bold** text and a [link](https://example.com).`"

**Checks**
- A Google Doc is created (not a raw `.md` file)
- Open in browser: 'My Title' renders as Heading 1
- 'Section One' renders as a heading
- Bullet A and B render as a list
- **bold** renders as bold text
- 'link' is a hyperlink to https://example.com

---

### TC-D91: Upload HTML and convert to Google Doc ⚠️ requires-oauth
**Prompt**
> "Upload this HTML to {FOLDER_ID} as a Google Doc called 'QA-HTML-Doc': `<h1>HTML Title</h1><p>A paragraph.</p><ul><li>X</li><li>Y</li></ul>`"

**Checks**
- Google Doc created with formatted content
- Heading and list visible in browser
- `source_format` was `html`, `convert_to_doc` was `True`

---

### TC-D92: Upload Markdown with table ⚠️ requires-oauth
**Prompt**
> "Upload this markdown as a Google Doc called 'QA-Table-Doc' to {FOLDER_ID}: `# Table Test\n\n| Col A | Col B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |`"

**Checks**
- Google Doc created
- Open in browser: a 2×2 table is visible under the heading
- Confirms `markdown[extra]` extension handles GFM tables

---

## `upload_local_file`

### TC-D93: Upload a binary file ⚠️ local-filesystem
**Prompt**
> "Upload the local file `/tmp/qa-test.png` to {FOLDER_ID}" *(create any small PNG at that path first)*

**Checks**
- File appears in Drive with `mimeType: image/png`
- `skipped: false` in response
- `list_files` for `{FOLDER_ID}` includes the new file after upload

---

### TC-D94: skip_if_exists prevents re-upload ⚠️ local-filesystem
**Prompt** (run twice, same file)
> "Upload `/tmp/qa-test.png` to {FOLDER_ID} again"

**Checks**
- Second call returns the existing file's `fileId` with `skipped: true`
- No duplicate created in Drive
- Confirms the pre-check list query fires and short-circuits

---

### TC-D95: skip_if_exists=False creates duplicate ⚠️ local-filesystem
**Prompt**
> "Upload `/tmp/qa-test.png` to {FOLDER_ID} with skip_if_exists set to false"

**Checks**
- A second file with the same name is created in Drive
- Response `skipped: false`
- 🔍 Drive allows duplicate names — both files now exist

---

### TC-D96: Non-existent local path ⚠️ local-filesystem

**Prompt**
> "Upload the file `/tmp/does-not-exist-qa.bin` to {FOLDER_ID}"

**Checks**
- `ValueError` raised with a message referencing the missing path
- No Drive API call made

---

### TC-D97: Name override ⚠️ local-filesystem
**Prompt**
> "Upload `/tmp/qa-test.png` to {FOLDER_ID} but name it 'renamed-in-drive.png'"

**Checks**
- File in Drive is named `renamed-in-drive.png`, not `qa-test.png`
- Local file unchanged

---

## `upload_local_folder`

### TC-D98: Bulk upload of a mixed directory ⚠️ destructive ⚠️ local-filesystem
**Prompt**
> "Upload all files from `/tmp/qa-folder/` to {FOLDER_ID}" *(create a directory with 2–3 files of different types)*

**Checks**
- All files appear in Drive with correct MIME types
- `uploaded` list matches the filenames
- `failed` is empty

---

### TC-D99: .DS_Store excluded by default ⚠️ local-filesystem
**Prompt**
> "Upload the directory `/tmp/qa-folder/` to {FOLDER_ID}" *(ensure `.DS_Store` exists in that directory)*

**Checks**
- `.DS_Store` is absent from the `uploaded` list and from Drive
- Other files in the directory are uploaded normally

---

### TC-D100: skip_if_exists batches the existence check ⚠️ local-filesystem
**Prompt** (run twice)
> "Upload `/tmp/qa-folder/` to {FOLDER_ID} again with skip_if_exists=True"

**Checks**
- Previously uploaded files appear in `skipped`
- `uploaded` contains only new files (if any)
- Only one `list` API call is made per run (not one per file) — check server logs

---

## `download_file`

### TC-D101: Download a non-Google file ⚠️ local-filesystem

**Prompt**
> "Download the file {BINARY_FILE_ID} to `/tmp/qa-downloads/`" *(use the ID of the PNG uploaded in TC-D93)*

**Checks**
- File written to `/tmp/qa-downloads/<drive_name>`
- `size_bytes` matches the Drive file size
- File is a valid PNG (can be opened)

---

### TC-D102: Export Google Doc as plain text ⚠️ local-filesystem

**Prompt**
> "Download {DOC_ID} as a txt file to `/tmp/qa-downloads/`"

**Checks**
- File written as `<doc_name>.txt`
- Content is readable plain text matching the doc body
- `encoding` for the response is not relevant here — file is on disk

---

### TC-D103: Export Google Doc as PDF ⚠️ local-filesystem

**Prompt**
> "Download {DOC_ID} as a pdf to `/tmp/qa-downloads/`"

**Checks**
- File written as `<doc_name>.pdf`
- File opens as a valid PDF (`%PDF` header)
- `size_bytes` > 0

---

### TC-D104: Export Google Sheet as CSV ⚠️ local-filesystem

**Prompt**
> "Download {SPREADSHEET_ID} as CSV to `/tmp/qa-downloads/`"

**Checks**
- CSV file written locally
- Content matches the spreadsheet's first sheet data

---

### TC-D105: Workspace file without export_format ⚠️ local-filesystem

**Prompt**
> "Download {DOC_ID} to `/tmp/qa-downloads/` without specifying a format"

**Checks**
- `ValueError` raised mentioning that `export_format` is required
- No file written

---

### TC-D106: local_path as exact file path ⚠️ local-filesystem

**Prompt**
> "Download {BINARY_FILE_ID} and save it to `/tmp/qa-specific-name.png`"

**Checks**
- File written to exactly `/tmp/qa-specific-name.png`, not into a subdirectory
- Parent directory created if it didn't exist

---

## `download_folder`

### TC-D107: Download folder with mixed content ⚠️ local-filesystem

**Prompt**
> "Download all files from {FOLDER_ID} to `/tmp/qa-folder-download/`"

**Checks**
- All non-Workspace files written to the local directory
- Workspace files (Docs, Sheets) listed in `skipped` — not exported without `export_format`
- `downloaded` list matches non-Workspace filenames

---

### TC-D108: Download folder with export_format ⚠️ local-filesystem

**Prompt**
> "Download all files from {FOLDER_ID} to `/tmp/qa-folder-export/` with export_format='pdf'"

**Checks**
- Non-Workspace files downloaded as-is
- Workspace files exported as `.pdf` and included in `downloaded`
- All resulting files have `.pdf` extension or original extension

---

### TC-D109: skip_if_exists=True skips existing local files ⚠️ local-filesystem

**Prompt** (run twice)
> "Download {FOLDER_ID} to `/tmp/qa-folder-download/` again"

**Checks**
- Files already present locally appear in `skipped`
- `downloaded` is empty (or contains only new Drive files)

---

### TC-D110: mime_type_filter ⚠️ local-filesystem

**Prompt**
> "Download only Google Docs from {FOLDER_ID} to `/tmp/qa-docs-only/` using export_format='txt'"

**Checks**
- Only `application/vnd.google-apps.document` files exported
- Other file types absent from the output directory

---

## `sync_folder`

### TC-D111: dry_run shows full action plan ⚠️ local-filesystem

**Prompt**
> "Do a dry run sync of {FOLDER_ID} with `/tmp/qa-sync/` in bidirectional mode"

**Checks**
- Response includes `actions` list with `{name, action, reason}` for every file
- `dry_run: true` in response
- No files created or modified locally or in Drive

---

### TC-D112: Bidirectional — Drive-only file downloaded ⚠️ destructive ⚠️ local-filesystem

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` bidirectionally" *(ensure at least one file exists in Drive but not locally)*

**Checks**
- Drive-only files appear in `downloaded`
- Files written to `/tmp/qa-sync/`

---

### TC-D113: Bidirectional — local-only file uploaded ⚠️ destructive ⚠️ local-filesystem
**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` bidirectionally" *(create a new file in `/tmp/qa-sync/` that doesn't exist in Drive)*

**Checks**
- New local file appears in `uploaded`
- File visible in Drive after sync

---

### TC-D114: Local newer → uploaded; Drive newer → downloaded ⚠️ local-filesystem

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` and show me what gets uploaded vs downloaded"

**Checks**
- Files where local mtime > Drive modifiedTime + 5s → in `uploaded`
- Files where Drive modifiedTime > local mtime + 5s → in `downloaded`
- Files within 5s of each other → in `skipped`

---

### TC-D115: Upload preserves mtime for future sync accuracy ⚠️ local-filesystem
**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` to upload a local file, then sync again immediately"

**Checks**
- First sync: local-only file appears in `uploaded`
- Second sync: same file appears in `skipped` (in sync), not re-uploaded
- Confirms `modifiedTime` is set on the Drive file to match the local mtime

---

### TC-D116: direction='upload' — Drive-only file not downloaded ⚠️ local-filesystem
**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` using direction='upload'"

**Checks**
- Drive-only files appear in `skipped`, not `downloaded`
- Local-only files are uploaded
- Drive-newer files appear in `conflicts`, not `downloaded`

---

### TC-D117: direction='download' — local-only file not uploaded ⚠️ local-filesystem

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` using direction='download'"

**Checks**
- Local-only files appear in `skipped`, not `uploaded`
- Drive-only files are downloaded
- Local-newer files appear in `conflicts`, not `uploaded`

---

### TC-D118: Workspace files excluded without export_format ⚠️ local-filesystem

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` — the folder contains a Google Doc"

**Checks**
- Google Doc does not appear in `downloaded`, `uploaded`, or `conflicts`
- 🔍 **Note:** Workspace files are silently excluded unless `export_format` is set — document this for users

---

### TC-D119: Invalid direction raises error ⚠️ local-filesystem

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` using direction='mirror'"

**Checks**
- `ValueError` raised immediately, before any API calls
- Error message lists the valid direction values

---

### TC-D178: Concurrent mixed upload/download batch — no cross-attribution or corruption ⚠️ destructive ⚠️ local-filesystem (issue #183)

**Background:** #183 made `sync_folder`'s per-file transfers run concurrently via `asyncio.gather()` instead of one at a time, including simultaneous uploads and downloads in the same call. Mocked unit tests can't catch a genuine race against the real Drive API — this exercises enough distinct, identifiable files at once (each with unique content) to surface any result attributed to the wrong file, or file content written to the wrong destination, under real concurrency.

**Setup**
In `{FOLDER_ID}`, create 3 Drive-only files (`drive-a.txt`, `drive-b.txt`, `drive-c.txt`), each with distinct content (e.g. containing its own filename as a marker). Locally in `/tmp/qa-sync-183/`, create 3 local-only files (`local-x.txt`, `local-y.txt`, `local-z.txt`), each with distinct content.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-183/` using direction='bidirectional'"

**Checks**
- All 3 Drive-only files appear in `downloaded`; all 3 local-only files appear in `uploaded`; `failed` is empty
- Each downloaded local file's content matches its *own* source Drive file's marker — not another file's content (would indicate cross-attribution under concurrency)
- Each uploaded Drive file's content matches its *own* source local file's marker (check via `export_file` or `download_file` on each)
- `size_bytes` equals the sum of the 3 downloaded files' actual sizes

**Teardown**
Delete the 3 Drive-only test files from `{FOLDER_ID}`, delete the 3 uploaded local-only files from Drive, remove `/tmp/qa-sync-183/`.

---

### TC-D190: `recursive=True` walks into subfolders present on both sides (issue #315) ⚠️ destructive ⚠️ local-filesystem

**Background:** #315 — `sync_folder` only ever looked at files directly inside `folder_id`; a folder with subfolders on both sides reported a clean "in sync" result while silently ignoring everything nested one level down. `recursive=True` fixes this by walking matching subfolders to any depth.

**Setup**
In `{FOLDER_ID}`, create a subfolder named `nested` (via `create_folder`). Inside it, create a Drive-only text file `deep.txt` with content `hello from nested`. Locally, create the same subfolder path `/tmp/qa-sync-315/nested/` (empty) so the subfolder itself exists on both sides but the file is Drive-only.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-315/` bidirectionally with recursive=True"

**Checks**
- `downloaded` includes `nested/deep.txt` (not just `deep.txt`) — the relative path carries the subfolder prefix
- `/tmp/qa-sync-315/nested/deep.txt` exists locally with content `hello from nested`
- `folders_skipped` is empty
- Re-running the same sync afterward reports `nested/deep.txt` under `skipped` (`in sync`), confirming the recursive mtime comparison also worked, not just the initial download

**Result (2026-07-17)** ⚠️ PARTIAL — recursive descent, download, and `folders_skipped`-empty all confirmed live (nested file downloaded to `qa328-nested/deep.txt` with correct content and prefix). The re-sync check **fails**: the second sync re-`upload`ed the file instead of reporting `skipped`/"in sync". Root cause confirmed live and unrelated to recursion — `download` never sets the local file's mtime to match Drive's `modifiedTime`, so any real time gap (>5s tolerance) between download and the next comparison makes the local copy look "newer" and triggers a needless re-upload. Reproduces identically on the pre-existing top-level fixture files (`qa-notes.md`, `qa-upload.txt`), confirming this is a pre-existing defect in the base (non-recursive) mtime-diff logic, not something this PR's recursion work introduced or worsened. Filed as #346 rather than blocking this PR.

**Teardown**
Delete `nested` (and its contents) from `{FOLDER_ID}` via `delete_file`. Remove `/tmp/qa-sync-315/`.

---

### TC-D191: `recursive=True` reports out-of-scope subfolders under `folders_skipped` instead of silently ignoring them ⚠️ destructive ⚠️ local-filesystem

**Background:** #315's fallback ask (if full recursion weren't viable) was to at least surface subfolders the sync can't safely touch, rather than reporting a clean result. Even with recursion implemented, a subfolder that exists on only one side is deliberately left alone when the sync `direction` wouldn't create it on the other side — this confirms that case is reported, not silently dropped.

**Setup**
In `{FOLDER_ID}`, create a subfolder named `drive-only-sub` (via `create_folder`) with one file inside it. Do not create any local counterpart.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-315b/` using direction='upload' and recursive=True"

**Checks**
- `folders_skipped` contains `drive-only-sub/`
- `downloaded` and `uploaded` do not mention anything under `drive-only-sub/`
- `/tmp/qa-sync-315b/drive-only-sub/` was not created on disk

**Result (2026-07-17) ✅ PASS**

**Teardown**
Delete `drive-only-sub` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-315b/` if created.

---

### TC-D192: default `recursive=False` still ignores subfolders entirely (regression guard) ⚠️ local-filesystem

**Prompt**
> "Do a dry run sync of {FOLDER_ID} with `/tmp/qa-sync-315c/` in bidirectional mode" *(ensure {FOLDER_ID} has at least one subfolder with files in it, alongside a top-level file)*

**Checks**
- `actions` only lists the top-level file(s) — nothing from inside the subfolder appears
- `folders_skipped` is empty (subfolders aren't even considered when `recursive` is omitted)
- No entry in `failed` referencing the subfolder itself (guards against a pre-existing bug where a subfolder's mimeType could be mistaken for an exportable Workspace file when `export_format` was set)

**Result (2026-07-17) ✅ PASS**

---

### TC-D193: `recursive=True` — same-named Drive file and folder no longer crashes the whole sync (PR #328 review) ⚠️ destructive ⚠️ local-filesystem

**Background:** Sky's code review on PR #328 found that Drive allows a file and a folder to share a name in the same parent (items are keyed by ID, not name). With `recursive=True` and a download-permitting direction, the file-level pass downloads the file to `dest_dir/name`, then the folder-level pass calls `child_dest_dir.mkdir(parents=True, exist_ok=True)` on the same path — `exist_ok` only tolerates an *existing directory*, not an existing file, so this used to raise an uncaught `FileExistsError` and abort the entire sync, discarding all accumulated results. Fixed by checking for the collision first and recording it as a `failed` entry instead of crashing.

**Setup**
In `{FOLDER_ID}`, create a Drive-only text file named `collide` with content `i am a file`. Separately, create a Drive folder also named `collide` (via `create_folder`) directly inside `{FOLDER_ID}`, with one file inside it, e.g. `inner.txt`.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-328a/` bidirectionally with recursive=True"

**Checks**
- The call succeeds and returns a normal result — no exception, no aborted/partial response
- `downloaded` includes `collide` (the file)
- `failed` includes an entry whose `name` is `collide/` and whose `error` mentions the name already existing as a file
- `/tmp/qa-sync-328a/collide` exists locally as the downloaded file's content (`i am a file`), not overwritten or corrupted by the failed mkdir attempt

**Result (2026-07-17) ✅ PASS**

**Teardown**
Delete both the `collide` file and the `collide` folder (with its contents) from `{FOLDER_ID}` via `delete_file`. Remove `/tmp/qa-sync-328a/`.

---

### TC-D194: `recursive=True` — Drive folder-creation failure for a local-only subfolder is recorded as `failed`, not an uncaught crash (PR #328 review) ⚠️ destructive ⚠️ local-filesystem

**Background:** Unlike every file-level transfer (each wrapped and converted to a `failed` entry on error), the `drive_service.files().create(...)` call for a local-only subfolder being uploaded had no try/except. A transient network/permission/quota error there used to propagate uncaught through `sync_folder`, aborting the whole multi-level sync instead of recording one failed item. Covered primarily by a unit test (`tests/drive/test_transfer.py::TestSyncFolderRecursive::test_drive_folder_create_failure_recorded_as_failed_not_crashed`) that forces a `create()` failure deterministically — reproducing a genuine transient Drive API failure live isn't practical. This live check only confirms the surrounding recursive-upload path still behaves normally; it does not exercise the failure branch itself.

**Setup**
Locally, create `/tmp/qa-sync-328b/sub/local.txt` with content `hello`.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-328b/` using direction='upload' and recursive=True"

**Checks**
- `uploaded` includes `sub/local.txt`
- A new Drive folder named `sub` now exists inside `{FOLDER_ID}` (via `list_folders` or `list_files`), containing `local.txt`
- `failed` is empty (happy path — the try/except added around folder creation doesn't change success behavior)

**Result (2026-07-17) ✅ PASS**

**Teardown**
Delete the `sub` folder (and its contents) from `{FOLDER_ID}`. Remove `/tmp/qa-sync-328b/`.

---

### TC-D195: `download_folder` skips subfolders instead of attempting to export them (PR #328 review) ⚠️ destructive ⚠️ local-filesystem

**Background:** The decision doc for #315 claimed the folder/Workspace-mimeType conflation bug (a subfolder's mimeType sharing the `application/vnd.google-apps.` prefix with real Workspace docs) "can no longer happen ... regardless of `recursive`" — but that was only true for `sync_folder`'s own traversal via `_list_drive_children`. `download_folder` has separate listing code that still classified purely by mimeType prefix, so `download_folder(folder_id, local_path, export_format='pdf')` on a folder containing a subfolder still tried to `.export()` the subfolder and failed. Fixed by always skipping folder-mimeType items before the Workspace-file check runs.

**Setup**
In `{FOLDER_ID}`, create a subfolder named `nested-sub` (via `create_folder`) with one file inside it. Also ensure at least one top-level Google Doc exists directly in `{FOLDER_ID}` (for the export_format path to have something legitimate to do).

**Prompt**
> "Download all files from {FOLDER_ID} to `/tmp/qa-download-328/` exporting Workspace files as pdf"

**Checks**
- `skipped` includes `nested-sub` — the subfolder itself, listed as skipped, not attempted
- `failed` contains no entry mentioning `nested-sub` (guards the specific regression: previously this would appear in `failed` with an export error)
- The top-level Google Doc's `.pdf` export appears under `downloaded` as before — confirms the fix didn't disturb normal Workspace-file export
- `/tmp/qa-download-328/nested-sub/` was never created (this tool is non-recursive; the subfolder's contents are never touched)

**Result (2026-07-17) ✅ PASS** — run against an isolated scratch folder (not directly in `{FOLDER_ID}`) to avoid dragging in the shared fixture folder's ~10 pre-existing pollution items into the export; same tool behavior either way.

**Teardown**
Delete `nested-sub` from `{FOLDER_ID}`. Remove `/tmp/qa-download-328/`.

---

### TC-D196: `recursive=True` dry-run trips the response-size cap on a large action list (PR #328 review) ⚠️ local-filesystem

**Background:** `recursive=True` removes the previous implicit bound (one folder's direct children) on the `actions` list; nothing called `enforce_response_size_cap` the way other large-payload tools (e.g. `export_file`) do. The #315 decision doc's own reproduction case (22 subfolders / ~225 files) was a realistic scale to hit `MAX_TOOL_RESPONSE_CHARS`. This needs a large real Drive tree to trip live — if no existing fixture of that scale is available, this may need to be run against a temporarily-constructed large folder rather than the standard QA fixtures.

**Prompt**
> "Do a dry run sync of {LARGE_FOLDER_ID} with a matching local directory in bidirectional mode with recursive=True" *(requires a Drive folder with enough nested files/subfolders — roughly 20+ subfolders / 200+ files — to serialize past 40,000 characters)*

**Checks**
- Call raises `ValueError` mentioning the actual response size and the 40,000-character cap
- Error message does not offer a `local_path` bypass (unlike `get_sheet_data`'s cap message) — `sync_folder`'s `local_path` param already means the sync destination, not a dump target for the oversized response
- Error message suggests narrowing scope (folder, direction, or non-recursive) instead

**Result (2026-07-17)** pending — a 20+ subfolder / 200+ file live fixture is impractical to construct and tear down for a single scoped QA pass (200+ setup/teardown tool calls). Already deterministically unit-tested (`TestSyncFolderResponseSizeCap::test_oversized_result_raises`, monkeypatches the cap to trigger reliably) and passing. Not re-attempted live this pass.

---

### TC-D197: `recursive=True` — sibling subfolders sync correctly with no cross-attribution under concurrent descent (PR #328 review) ⚠️ destructive ⚠️ local-filesystem

**Background:** CLAUDE.md names `sync_folder` among the tools that parallelize per-item work via `asyncio.gather(..., return_exceptions=True)`. The recursive descent into sibling subfolders originally awaited each one sequentially instead, right next to the file-level loop in the same function that does use `gather` — wall-clock time scaled with the sum of subfolder round-trips instead of the max. Fixed by gathering sibling `_sync_level` calls the same way. Genuine concurrency (not just correctness) is unit-tested via a real-thread synchronization barrier (`tests/drive/test_transfer.py::TestSyncFolderRecursive::test_recursive_sibling_subfolders_descend_concurrently`); this live check confirms correctness under real concurrent Drive API calls — a mocked test can't catch a genuine race the way #183's TC-D178/TC-D179 precedent established.

**Setup**
In `{FOLDER_ID}`, create two subfolders, `sib-a` and `sib-b`, each with 3-4 distinct files with unique identifiable content (e.g. containing their own filename as a marker).

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-328c/` bidirectionally with recursive=True"

**Checks**
- `downloaded` includes all files from both `sib-a/` and `sib-b/` with correct relative-path prefixes
- Each downloaded file's local content matches its own source file's marker — not another file's content (would indicate cross-attribution under concurrency)
- `failed` is empty

**Result (2026-07-17) ✅ PASS**

**Teardown**
Delete `sib-a` and `sib-b` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-328c/`.

---

### TC-D198: `download_folder` transfers files concurrently instead of one at a time (issue #316) ⚠️ local-filesystem

**Background:** Live testing measured `download_folder` against a real 217-file Shared Drive folder at 226s total — roughly 1.04s/file, scaling linearly, consistent with a sequential `for file in files: await download(file)` loop rather than concurrent fan-out. `sync_folder`'s per-level transfers already ran concurrently via `asyncio.gather()` (#293); `download_folder` had its own separate, still-sequential loop. Fixed by rewriting it to the same concurrent-gather pattern. Genuine concurrency (not just correctness) is unit-tested via a real-thread synchronization barrier (`tests/drive/test_transfer.py::TestDownloadFolder::test_files_download_concurrently`); this live check confirms wall-clock time actually improves and results stay correctly attributed under real concurrent Drive API calls.

**Setup**
In `{FOLDER_ID}`, ensure at least 10-15 non-Workspace files exist.

**Prompt**
> "Download all files from {FOLDER_ID} to `/tmp/qa-download-316/` and tell me how long the call took"

**Checks**
- Wall-clock time is well under (file count × ~1s) — concurrent fan-out means total time tracks the slowest individual transfer, not the sum of all of them
- Every file appears in `downloaded` with the correct name and `size_bytes` matching its own source file — no content or name cross-attribution between files under concurrency
- `failed` is empty

**Result (2026-07-17) ❌ FAIL** Ran against the live `{FOLDER_ID}` fixture, which (due to accumulated fixture drift) happens to contain two Drive files named `qa-notes.md` (distinct IDs, different source MIME types) and two named `qa-upload.txt` (distinct IDs). `download_folder` reported both as `"downloaded": ["qa-notes.md", "qa-notes.md", "qa-upload.txt", "qa-upload.txt"]` with `size_bytes: 296` (both files' sizes summed), but only one physical copy of each landed on disk — the second concurrent writer clobbered the first. This directly violates this test case's own second check ("no content or name cross-attribution between files under concurrency"): the tool's response claims two independent successful downloads for a file that was actually overwritten mid-flight, and double-counts its byte total. Root cause: `download_folder`'s new candidate-collection loop (`src/mcp_gee_sweet/tools/drive/transfer.py:1098-1130`) checks `skip_if_exists` against the pre-transfer filesystem state for every Drive file before any download starts, so two Drive files that map to the same local name (Drive allows duplicate names, keyed by ID) both pass the check and are queued into `candidates`; `asyncio.gather` (line 1178) then runs both `_download_one` calls concurrently, racing to write the same path. The prior sequential implementation was accidentally safe here since each file's existence check ran only after the previous file had fully written. Confirmed reproducible: re-ran after a clean `/mcp reconnect` against a fresh empty destination directory and got the same result both times.

**Follow-up (2026-07-17, commit `3ad523c`) ✅ FIXED** — re-ran the identical live call against the same `{FOLDER_ID}` fixture (still carrying the incidental `qa-notes.md`/`qa-upload.txt` duplicates). `downloaded` now contains each name exactly once, `failed` carries an explicit "duplicate filename" entry for each extra, `size_bytes` (148) matches only the single-copy total, and the files on disk are intact/uncorrupted. See TC-D200 for a purpose-built reproduction of the same fix.

**Teardown**
Remove `/tmp/qa-download-316/`.

---

### TC-D199: `download_folder` and `sync_folder` emit `notifications/progress` updates as each transfer completes (issue #316)

**Background:** Both tools previously ran silently for their entire duration — the 226s `download_folder` call above returned nothing until the very end, with no indication to the caller of whether it was working or hung. Both now call `ctx.report_progress()` from inside each individual transfer's own coroutine right as it finishes, not after the whole concurrent batch resolves, so a caller that supplied a progressToken sees a live stream of updates spread across the call's duration instead of one final burst. The two tools' messages aren't identical: `download_folder` knows its file count upfront (a single non-recursive listing), so it reports a real `total` and a message like `"12/217: report.pdf: ok"`. `sync_folder` doesn't know the total ahead of time (recursive descent discovers files level by level), so it always passes `total=None` and reports a running count with a message like `"readme.txt: download_ok"` — no "N/total" prefix. Progress is file-count based, not byte-size, for both: neither tool's Drive listing fetches a `size` field, and a Workspace file's exported size is unknown until after the export completes, so an accurate byte total isn't available upfront (a size-based mode is tracked separately in #352). `sync_folder`'s dry-run mode never transfers anything, so it never reports progress either. `ctx.report_progress()` itself is wrapped in a try/except at both call sites (PR #351 review) — a failed notification (e.g. a dropped session) no longer downgrades an already-successful transfer to a reported failure.

**Note:** `notifications/progress` is a protocol-level message, not part of the tool's JSON response — whether it's visible during this QA pass depends on whether the MCP client surfaces raw progress notifications in the transcript. The exact per-item call count, `total`, and message content are already asserted against a mocked `ctx` in `tests/drive/test_transfer.py::TestDownloadFolder::test_reports_progress_as_files_complete` and `TestSyncFolderRecursive::test_reports_progress_for_each_transfer_not_after_the_whole_batch`/`test_dry_run_reports_no_progress`. If the client doesn't surface progress notifications, this check can only confirm the call still completes normally with the notification calls in place.

**Setup**
In `{FOLDER_ID}`, ensure at least 5 files exist.

**Prompt**
> "Download all files from {FOLDER_ID} to `/tmp/qa-progress-316/`"

**Checks**
- If progress notifications are visible in the client: multiple discrete "N/total" updates appear spread across the call, not a single update at the very end
- Regardless of notification visibility: the call completes normally and `downloaded` is correct

**Result (2026-07-17) ⚠️ PARTIAL** This QA client (Claude Code direct tool calls) doesn't set a `progressToken`, so raw `notifications/progress` messages aren't visible in this transcript — the first check couldn't be exercised live, consistent with this test case's own caveat. Second check confirmed: `download_folder` completed normally against `{FOLDER_ID}` with no error from the new `ctx.report_progress(...)` call path (which no-ops safely with no token, per `Context.report_progress`'s own guard). Note: code review separately found `ctx.report_progress` is *not* wrapped in a try/except at either call site (`transfer.py:298` in `_sync_level`, `transfer.py:1172` in `download_folder`) — if a real client supplies a progressToken and the notification send fails mid-transfer (e.g. a dropped SSE connection on a long sync), an already-successful transfer gets misreported as failed. That failure mode requires a live, then-interrupted session to trigger and wasn't reproducible in this pass; flagged in code review as a confirmed defect regardless.

**Follow-up (2026-07-17, commit `3ad523c`) ✅ FIXED** — both call sites now wrap `ctx.report_progress(...)` in try/except, logging at debug level and letting the transfer's own already-computed result stand regardless of notification-channel failure. Confirmed via new unit tests (`test_report_progress_failure_does_not_demote_a_successful_upload`/`_download`, both inject a `RuntimeError` via `ctx.report_progress.side_effect` and assert the item still lands in `uploaded`/`downloaded`, not `failed`) — full suite passes (767 tests). `download_folder`'s message now also includes the outcome suffix (`f"{completed}/{total}: {name}: {kind}"`), matching its docstring example and closing the doc/code mismatch flagged in code review.

**Teardown**
Remove `/tmp/qa-progress-316/`.

---

### TC-D200: `download_folder` — two Drive files with the same name no longer race or double-count (PR #351 review) ⚠️ local-filesystem

**Background:** QA's TC-D198 pass live-reproduced a correctness bug in the concurrency fix: `download_folder`'s candidate-collection loop checked `skip_if_exists` against the pre-transfer filesystem state for every Drive file before any download started. Drive allows two files with the same name (distinct IDs) in one folder — the local filesystem doesn't — so two same-named files both passed the check and were queued into the same concurrent batch, racing to write the identical local path. The prior sequential implementation was accidentally safe here (each file's existence check ran only after the previous file had fully written). Fixed by deduping candidates by destination path as they're collected: the first file claims the path, later files with the same destination are recorded under `failed` with an explanatory "duplicate filename" error instead of being queued to write. Unit-tested deterministically (`tests/drive/test_transfer.py::TestDownloadFolder::test_duplicate_drive_filenames_do_not_race_or_double_count`); this live check confirms the fix against the exact fixture-drift scenario QA's TC-D198 run hit.

**Setup**
In `{FOLDER_ID}`, create two Drive files with the identical name, e.g. `dup-test.txt` (distinct IDs — two separate `upload_file` calls with the same `name`), with different content each (so a content mix-up is detectable).

**Prompt**
> "Download all files from {FOLDER_ID} to `/tmp/qa-dup-351/`"

**Checks**
- `downloaded` contains `dup-test.txt` exactly once (not twice)
- `failed` contains exactly one entry for `dup-test.txt` (or the export-suffixed name, if the duplicate involves Workspace files) whose `error` mentions "duplicate filename"
- `/tmp/qa-dup-351/dup-test.txt` exists and its content matches whichever of the two Drive files was actually downloaded (i.e. content is intact, not corrupted by a partial concurrent write)
- `size_bytes` reflects only the one file that was actually downloaded, not both

**Result (2026-07-17) ✅ PASS** Uploaded two distinct-ID files named `dup-test.txt` (different content each) to `{FOLDER_ID}`, then ran `download_folder`. Response: `"downloaded": [..., "dup-test.txt", ...]` exactly once, `"failed"` included exactly one `dup-test.txt` entry with `error` containing "duplicate filename", and `size_bytes` reflected only the single downloaded copy. On disk, `dup-test.txt` contained one file's content intact (not interleaved/corrupted). This re-verifies the fix from `3ad523c` against a purpose-built duplicate, on top of the incidental fixture-drift duplicates re-checked under TC-D198.

**Teardown**
Delete both `dup-test.txt` files from `{FOLDER_ID}`. Remove `/tmp/qa-dup-351/`.

---

### TC-D201: `sync_folder` no longer re-uploads a file after downloading it (issue #346) ⚠️ destructive ⚠️ local-filesystem

**Background:** TC-D190's re-sync check found that a downloaded file's local mtime defaulted to write time ("now"), not Drive's `modifiedTime` — since "now" is always later than Drive's original timestamp, the next sync saw the file as locally newer (outside the 5s tolerance) and re-uploaded it, repeating on every subsequent sync. Filed as #346 rather than blocking #315/#328. Fixed by setting the local file's mtime to Drive's `modifiedTime` (via `os.utime`) right after a successful download, mirroring what the upload branch already does in reverse for the Drive side. Unit-tested deterministically (`tests/drive/test_transfer.py::TestSyncFolderDownloadMtimeRoundTrip`); this live check re-runs TC-D190's exact failing scenario to confirm the fix.

**Setup**
In `{FOLDER_ID}`, ensure at least one Drive-only file exists that isn't already present locally (a fresh scratch fixture is fine — no need to reuse the polluted long-standing fixture files).

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-346/` bidirectionally" *(run twice in a row)*

**Checks**
- First run: the file appears in `downloaded`
- Second run (any real time gap is fine — no need to wait past the 5s tolerance deliberately, ordinary tool-call latency between the two prompts is enough): the same file appears in `skipped` ("in sync"), not `uploaded`
- No entry for the file appears in `conflicts` on either run

**Result (2026-07-17) ✅ PASS** Uploaded `qa-mtime-346.txt` to `{FOLDER_ID}`, ran `sync_folder(direction="bidirectional")` twice against a fresh local dir. First run: `downloaded` included `qa-mtime-346.txt`. Second run: `qa-mtime-346.txt` moved to `skipped`, with `uploaded`/`conflicts` both empty — no re-upload loop. Bonus: the two pre-existing raw (non-Workspace) fixture files (`qa-notes.md`, `qa-upload.txt`) also settled into `skipped` on the second run, confirming the fix holds on the raw-file download branch, not just the Workspace-export branch the unit tests exercise.

**Teardown**
Delete the test file from `{FOLDER_ID}`. Remove `/tmp/qa-sync-346/`.

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

## `list_permissions`

### TC-D124: List permissions on a file — owner entry present

**Prompt**
> "List all permissions on {SPREADSHEET_ID}"

**Checks**
- Returns at least one entry (the owner)
- Owner entry has `role: 'owner'` and `type: 'user'`
- Each entry has `id`, `type`, `role` — no `KeyError` or missing fields

---

### TC-D125: List permissions after sharing — new entry visible

**Setup:** run TC-D132 first (share with a test user as reader)

**Prompt**
> "List the permissions on {SPREADSHEET_ID}"

**Checks**
- The test user's email appears with `role: 'reader'`
- Their `permission_id` is present for use in update/remove tests

---

### TC-D126: Non-existent file ID

**Prompt**
> "List permissions on file 'invalidid123xyz'"

**Checks**
- API error propagates — not a silent empty list or server crash

---

## `update_permission`

### TC-D127: Downgrade writer → reader ⚠️ destructive

**Setup:** share {SPREADSHEET_ID} with test-recipient@example.com as writer first (TC-D132 variant); note the `permission_id` returned

**Prompt**
> "Update permission {PERMISSION_ID} on {SPREADSHEET_ID} to 'reader'"

**Checks**
- Response `role` is `reader`
- Follow-up `list_permissions` confirms the same permission ID now has `role: 'reader'`

---

### TC-D128: Invalid role value

**Prompt**
> "Update permission {PERMISSION_ID} on {SPREADSHEET_ID} to role 'owner'"

**Checks**
- Returns `{"error": "Invalid role 'owner'..."}` — not an exception
- No API call made (validation fires client-side before Drive API)

---

### TC-D129: Non-existent permission ID

**Prompt**
> "Update permission 'fakepermid999' on {SPREADSHEET_ID} to 'reader'"

**Checks**
- Drive API error propagates — not a server crash
- Error message references the invalid permission ID

---

## `remove_permission`

### TC-D130: Remove a permission ⚠️ destructive

**Setup:** share {SPREADSHEET_ID} with test-recipient@example.com first; note `permission_id` returned

**Prompt**
> "Remove permission {PERMISSION_ID} from {SPREADSHEET_ID}"

**Checks**
- Response: `{"fileId": ..., "permissionId": ..., "action": "removed"}`
- Follow-up `list_permissions` no longer shows that permission ID
- Removed user can no longer access the file (verify in Drive UI if using a real test account)

---

### TC-D131: Non-existent permission ID

**Prompt**
> "Remove permission 'fakepermid999' from {SPREADSHEET_ID}"

**Checks**
- Drive API error propagates — not a silent success or server crash

---

## `share_file`

> ⚠️ **Fixture requirement:** TC-D132, TC-D137, TC-D139 require `TEST_PERMISSION_EMAIL` in `.env` to be a **real Google account** you control (e.g. a secondary Gmail). `example.com` addresses are not valid Google accounts and Drive will reject sharing with them. TC-D135 (domain share) requires a Google Workspace domain — `example.com` will also fail; use your actual GWS domain or skip and note as environmental.

### TC-D132: Share with type=user as reader

**Prompt**
> "Share {SPREADSHEET_ID} with {TEST_PERMISSION_EMAIL} as a reader using share_file"

**Checks**
- Response `successes` contains the entry with `type: 'user'`, `role: 'reader'`, and a `permissionId`
- `failures` is empty
- Follow-up `list_permissions` confirms the new entry

---

### TC-D133: Missing email_address for type=user

**Prompt**
> "Share {SPREADSHEET_ID} using share_file — pass a permission with type='user' and role='reader' but omit email_address"

**Checks**
- Entry goes to `failures` with a message about missing `email_address`
- No API call attempted for that entry
- Does not throw an unhandled exception

---

### TC-D134: Invalid role

**Prompt**
> "Share {SPREADSHEET_ID} with test@example.com using share_file with role='superuser'"

**Checks**
- Entry goes to `failures` with a message about the invalid role
- `successes` is empty

---

### TC-D135: Share with type=domain

> ⚠️ **Environmental:** `example.com` is not a Google Workspace domain; Drive will reject this with a domain validation error. Replace with your actual GWS domain if available, or SKIP and record as environmental.

**Prompt**
> "Share {SPREADSHEET_ID} with everyone at {GWS_DOMAIN} as a reader using share_file with type='domain'"

**Checks**
- Response `successes` contains an entry with `type: 'domain'` and `domain: '{GWS_DOMAIN}'`
- Follow-up `list_permissions` shows the domain permission entry

---

### TC-D136: Share with type=anyone (public link)

**Prompt**
> "Make {SPREADSHEET_ID} publicly readable using share_file with type='anyone' and role='reader'"

**Checks**
- Response `successes` contains `type: 'anyone'`, `role: 'reader'`
- Follow-up `list_permissions` shows an `anyone` entry
- File accessible via its `web_link` without authentication (verify in incognito browser)

---

### TC-D137: Share a folder

**Prompt**
> "Share folder {FOLDER_ID} with {TEST_PERMISSION_EMAIL} as a writer using share_file"

**Checks**
- Share succeeds; `successes` contains the entry
- `list_permissions` on the folder shows the new permission
- 🔍 **Note:** verify that child files inherit the permission (check in Drive UI)

---

### TC-D138: Mixed success and failure in one call

**Prompt**
> "Share {SPREADSHEET_ID} using share_file with two permissions: first type='user' email=test@example.com role='reader', second type='user' role='writer' (no email_address)"

**Checks**
- First entry in `successes`, second entry in `failures`
- Both present in the same response — partial failure does not abort the batch

---

### TC-D139: send_notification=False for user share

**Prompt**
> "Share {SPREADSHEET_ID} with {TEST_PERMISSION_EMAIL} as reader using share_file, but don't send a notification email"

**Checks**
- Share succeeds; `successes` populated
- No notification email sent — verify by checking the inbox of `TEST_PERMISSION_EMAIL`
- `send_notification=False` confirmed — `sendNotificationEmail=False` passed to the API

> ⚠️ **Note:** Drive requires `sendNotificationEmail=True` when sharing with non-Google Workspace accounts. If `TEST_PERMISSION_EMAIL` is a personal Gmail, this test may fail with a Drive API restriction — record as environmental, not a tool bug.

---

### TC-D177: Concurrent multi-permission share — no cross-attribution (issue #183)

**Background:** Same concurrency change as TC-D176, applied to `share_file`'s richer type/domain/anyone permission model. This mixes distinct types and roles across several entries at once to catch a result attributed to the wrong entry under concurrent execution.

**Prompt**
> "Share {SPREADSHEET_ID} using share_file with these 4 permissions at once: type='user' email=recipient1@example.com role='reader', type='user' email=recipient2@example.com role='writer', type='user' email=recipient3@example.com role='commenter', type='domain' domain={GWS_DOMAIN} role='reader'"

**Checks**
- All 4 entries appear in `successes`, none in `failures`
- Each entry's `type`, `role`, and `email_address`/`domain` in the response exactly match what was requested for that entry — cross-check individually
- `list_permissions` afterward confirms each principal actually has the role it was assigned (not swapped with another entry's)

**Teardown**
`remove_permission` for each of the 4 test permissions.

---

## `write_doc_content` — table support (issue #62)

### TC-D140: Simple 2×2 table created from HTML

**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><th>Name</th><th>Value</th></tr><tr><td>Alpha</td><td>1</td></tr></table>`"

**Checks**
- A real Google Docs table is visible in the doc — NOT flattened plain text
- Table has 2 rows and 2 columns
- Header row contains "Name" and "Value"; data row contains "Alpha" and "1"
- Open in browser to verify

---

### TC-D141: Table after paragraph content

**Prompt**
> "Write this HTML to {DOC_ID}: `<h1>Batch Comparison</h1><p>See the table below.</p><table><tr><th>Original</th><th>Double</th></tr><tr><td>2 cups flour</td><td>4 cups flour</td></tr><tr><td>1 egg</td><td>2 eggs</td></tr></table>`"

**Checks**
- Doc has "Batch Comparison" as a Heading 1
- "See the table below." renders as a paragraph
- A 3-row × 2-column table is present after the paragraph
- Table cells contain correct text: "Original", "Double", "2 cups flour", "4 cups flour", etc.
- Table appears after the paragraph content (interleaved in HTML order)

---

### TC-D142: Table with empty cells
**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><td>A</td><td></td></tr><tr><td></td><td>D</td></tr></table>`"

**Checks**
- 2×2 table created
- Cell (0,0) = "A", cell (0,1) = empty, cell (1,0) = empty, cell (1,1) = "D"
- Empty cells don't cause an error — `insertText` is simply skipped for them

---

### TC-D143: Table-only HTML (no paragraphs)
**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><td>X</td><td>Y</td></tr></table>`"

**Checks**
- A 1-row × 2-column table is created
- Cells contain "X" and "Y"
- No paragraph text before the table
- Confirms the early-return guard correctly handles tables-only input

---

### TC-D144: Multiple tables in one write
**Prompt**
> "Write this HTML to {DOC_ID}: `<p>First table:</p><table><tr><td>A</td><td>B</td></tr></table><p>Second table:</p><table><tr><td>C</td><td>D</td></tr></table>`"

**Checks**
- Both tables are created in the document
- First table has cells "A" and "B"; second has "C" and "D"
- "First table:" and "Second table:" paragraphs appear before both tables
- No index corruption or API error between the two table insertions

---

### TC-D145: HTML with `<th>` header cells treated as data
**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><th>Col1</th><th>Col2</th></tr><tr><td>Val1</td><td>Val2</td></tr></table>`"

**Checks**
- `<th>` cells are included in the table (not ignored)
- First row contains "Col1" and "Col2", second row contains "Val1" and "Val2"
- Google Docs doesn't distinguish th vs td styling — both rows are plain table cells

---

## `list_revisions`

### TC-D146: List revisions for a spreadsheet

**Prompt**
> "List the revisions for spreadsheet {SPREADSHEET_ID}"

**Checks**
- Returns a non-empty list of revisions
- Each entry has `revisionId`, `modifiedTime`, `modifiedBy`, `keepForever`
- Most recent revision appears last
- `modifiedTime` values are ISO 8601 timestamps

---

### TC-D147: List revisions for a non-existent file

**Prompt**
> "List revisions for file ID 'invalid_file_id_xyz'"

**Checks**
- Returns a clear API error (404), not an unhandled exception

---

## `export_revision`

### TC-D148: Export a revision and read a cell range

**Setup:**
1. Write "QA-BEFORE" to Sales!A1 using `update_cells`
2. Wait at least 30 seconds (Drive may coalesce rapid writes into a single revision)
3. Write "QA-AFTER" to Sales!A1
4. Call `list_revisions` on {SPREADSHEET_ID} and identify the revision from between the two writes

> ⚠️ **Known limitation:** Drive's revision API coalesces writes that occur within a short window into a single revision. If only one revision appears, both writes landed in it — SKIP and record as environmental. The 30-second pause reduces but does not eliminate this risk.

**Prompt**
> "Export revision {REVISION_ID} of {SPREADSHEET_ID} and show me the value in range A1"

**Checks**
- Returns `values` with "QA-BEFORE" in A1
- `sheet` matches the first sheet name
- `modifiedTime` matches the revision timestamp from `list_revisions`

---

### TC-D149: Export revision with explicit sheet name

**Prompt**
> "Export revision {REVISION_ID} of {SPREADSHEET_ID}, sheet 'Sheet2', range A1:B5"

**Checks**
- Returns data from Sheet2, not the first sheet
- Range is respected — only rows/columns within A1:B5 returned
- Handles multi-sheet files correctly

---

### TC-D150: Export revision — no range returns all data

**Prompt**
> "Export revision {REVISION_ID} of {SPREADSHEET_ID} with no range filter"

**Checks**
- Returns all rows and columns of the first sheet
- No error from omitting the range parameter

---

### TC-D151: Export revision of a non-Sheets file

**Prompt**
> "Export revision {REVISION_ID} of a Google Doc file (not a spreadsheet)"

**Checks**
- Returns a clear error: "No XLSX export available for this revision"
- Does not crash

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

**Checks (unit test)**
- `mime_type` containing `'` is escaped before interpolation into query string
- No SQL/query-injection risk

**Result (2026-06-21) ✅** Unit test confirms escape applied before query interpolation.

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
