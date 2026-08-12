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

### TC-D210: convert=True — CSV converts to a native Google Sheet (issue #188) ⚠️ local-filesystem
**Prompt**
> "Upload the local file `/tmp/qa-convert.csv` to {FOLDER_ID} with convert set to true" *(create `/tmp/qa-convert.csv` with a couple rows of comma-separated data first)*

**Checks**
- Call `upload_local_file(local_path="/tmp/qa-convert.csv", parent_folder_id="{FOLDER_ID}", convert=true)`
- Response has no `error` key, `skipped: false`
- `get_file_metadata` (or `list_files` on `{FOLDER_ID}`) shows the new file's `mimeType` as `application/vnd.google-apps.spreadsheet`, not `text/csv`
- `get_sheet_data` against the returned `fileId` returns the CSV's rows/columns as real cell data (confirms Drive actually imported the content, not just relabeled the MIME type)

---

### TC-D211: convert=True — Markdown converts to a native Google Doc ⚠️ local-filesystem
**Prompt**
> "Upload the local file `/tmp/qa-convert.md` to {FOLDER_ID} with convert set to true" *(create `/tmp/qa-convert.md` with a heading and a paragraph first)*

**Checks**
- Call `upload_local_file(local_path="/tmp/qa-convert.md", parent_folder_id="{FOLDER_ID}", convert=true)`
- Response has no `error` key
- File's `mimeType` is `application/vnd.google-apps.document`, not `text/markdown`
- `get_doc_content` on the returned `fileId` returns readable text matching the markdown source (heading and paragraph both present)

---

### TC-D212: convert=True — PPTX converts to a native Google Slides file ⚠️ local-filesystem
**Prompt**
> "Upload the local file `/tmp/qa-convert.pptx` to {FOLDER_ID} with convert set to true" *(any minimal .pptx works)*

**Checks**
- Call `upload_local_file(local_path="/tmp/qa-convert.pptx", parent_folder_id="{FOLDER_ID}", convert=true)`
- Response has no `error` key
- File's `mimeType` is `application/vnd.google-apps.presentation`, not the OOXML pptx MIME type

---

### TC-D213: convert=True — unsupported extension returns an error, nothing uploaded ⚠️ local-filesystem
**Prompt**
> "Upload the local file `/tmp/qa-convert.zip` to {FOLDER_ID} with convert set to true" *(any small file named `.zip` works — content doesn't matter)*

**Checks**
- Call `upload_local_file(local_path="/tmp/qa-convert.zip", parent_folder_id="{FOLDER_ID}", convert=true)`
- Response contains `error` mentioning the `.zip` extension is unsupported
- `list_files` on `{FOLDER_ID}` shows no new file was created

---

### TC-D214: convert omitted (default False) still uploads CSV as-is ⚠️ local-filesystem
**Prompt**
> "Upload the local file `/tmp/qa-convert.csv` to {FOLDER_ID}" *(convert not mentioned — confirms the default doesn't change existing behavior)*

**Checks**
- Call `upload_local_file(local_path="/tmp/qa-convert.csv", parent_folder_id="{FOLDER_ID}")` (no `convert` arg)
- File's `mimeType` in Drive is `text/csv`, unchanged from pre-#188 behavior
- No regression versus TC-D93's binary-upload path

---

### TC-D215: skip_if_exists does not treat an unconverted duplicate as a match when convert=True (PR #410 review) ⚠️ local-filesystem
**Background:** the existence check used for `skip_if_exists` matched by filename only, regardless of the existing file's `mimeType`. Uploading `a.csv` once with `convert=False` (raw), then again with `convert=True` and default `skip_if_exists=True`, silently returned the raw file with `skipped: true` and no `mimeType` in the response — conversion never ran and nothing signaled that. Fixed by also comparing the existing file's `mimeType` against the intended conversion target before treating it as skip-worthy.

**Prompt**
> Step 1: "Upload the local file `/tmp/qa-convert-215.csv` to {FOLDER_ID}" *(no convert — creates a raw text/csv file named qa-convert-215.csv)*
> Step 2: "Upload the local file `/tmp/qa-convert-215.csv` to {FOLDER_ID} with convert set to true"

**Checks**
- Step 2's response has `skipped: false` (not true) — a second, converted file is created rather than returning the raw one
- Step 2's created file has `mimeType: application/vnd.google-apps.spreadsheet`
- `list_files` on `{FOLDER_ID}` shows both files with distinct fileIds: the original raw `text/csv` one from step 1 named `qa-convert-215.csv`, and the new converted spreadsheet from step 2 — Drive's own import-conversion behavior strips the `.csv` extension from the converted copy's name, so it appears as `qa-convert-215`, not `qa-convert-215.csv`

**Teardown**
Delete both files (raw `qa-convert-215.csv` and converted `qa-convert-215`) from `{FOLDER_ID}`. Remove `/tmp/qa-convert-215.csv`.

**Result (2026-07-24) ✅ PASS** — Verified via `mcp-gee-sweet-sky` against fixture folder `{FOLDER_ID}`. Step 2 returned `skipped: false` with a distinct `fileId` from step 1, `mimeType: application/vnd.google-apps.spreadsheet` confirmed via `get_file_metadata`, and `list_files` showed both the raw and converted files coexisting (converted copy named `qa-convert-215`, extension stripped by Drive itself — check text above corrected to reflect this).

---

### TC-D216: convert=True extension is derived from the effective name, not local_path (PR #410 review) ⚠️ local-filesystem
**Background:** the extension used to look up the conversion target was read from `local_path`'s suffix even when a `name` override changed the effective destination filename, so a no-extension local scratch file with a `.csv` name override incorrectly errored as an unsupported extension. Fixed by deriving the extension from the effective destination name.

**Prompt**
> "Upload the local file `/tmp/qa-scratch-216` to {FOLDER_ID}, naming it `qa-convert-216.csv`, with convert set to true" *(create `/tmp/qa-scratch-216` with no extension, containing a couple rows of comma-separated data)*

**Checks**
- Call `upload_local_file(local_path="/tmp/qa-scratch-216", parent_folder_id="{FOLDER_ID}", name="qa-convert-216.csv", convert=true)`
- Response has no `error` key
- Created file's `mimeType` is `application/vnd.google-apps.spreadsheet`

**Teardown**
Delete `qa-convert-216.csv` from `{FOLDER_ID}`. Remove `/tmp/qa-scratch-216`.

**Result (2026-07-24) ✅ PASS** — Verified via `mcp-gee-sweet-sky` against fixture folder `{FOLDER_ID}`. Response had no `error` key and `mimeType: application/vnd.google-apps.spreadsheet`, confirming the extension used for conversion came from the `name` override rather than the extension-less `local_path`.

**Teardown (TC-D210–TC-D214)**
Delete all `qa-convert.*` files and their converted Drive counterparts from `{FOLDER_ID}`. Remove the local `/tmp/qa-convert.*` scratch files.

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

### TC-D240: convert=True — each file converts per its own extension (issue #411) ⚠️ local-filesystem
**Background:** `upload_local_folder` previously had its own independent inline upload path with no `convert` param, so bulk-importing a folder of CSV/DOCX/PPTX files into native Google formats required falling back to per-file `upload_local_file` calls. Fixed by routing each file through the same `_upload_local_file` helper `upload_local_file` uses.

**Prompt**
> "Upload the directory `/tmp/qa-folder-240/` to {FOLDER_ID} with convert set to true" *(create the directory with `a.csv` and `b.md`, each with a bit of real content)*

**Checks**
- Call `upload_local_folder(local_path="/tmp/qa-folder-240/", parent_folder_id="{FOLDER_ID}", convert=true)`
- Both `a.csv` and `b.md` appear in `uploaded`, `failed` is empty
- `list_files` on `{FOLDER_ID}` shows `a.csv`'s Drive `mimeType` as `application/vnd.google-apps.spreadsheet` and `b.md`'s as `application/vnd.google-apps.document` — not their raw MIME types
- `get_sheet_data`/`get_doc_content` against the respective returned content confirms Drive actually imported it, not just relabeled the MIME type

**Teardown**
Delete both converted files from `{FOLDER_ID}`. Remove `/tmp/qa-folder-240/`.

**Result (2026-08-04) ✅ PASS** — Verified via `mcp-gee-sweet-sky` (PR #505 regression check) against an isolated fixture folder. `uploaded: ["a.csv", "b.md"]`, `failed` empty. `list_files` showed `a.csv` as `application/vnd.google-apps.spreadsheet` (name stripped to `a`) and `b.md` as `application/vnd.google-apps.document` (name kept `.md`, per the documented convert_markdown naming convention). `get_sheet_data` on the spreadsheet's `a.csv` sheet tab returned the real CSV content (`col1,col2` / `hello,world`); `get_doc_content` on the Doc returned the real markdown content ("Test" heading + "Some content." paragraph) — confirms actual import, not just mimeType relabeling.

---

### TC-D241: convert=True — a file with an unsupported extension is reported in `failed`, siblings still upload ⚠️ local-filesystem
**Prompt**
> "Upload the directory `/tmp/qa-folder-241/` to {FOLDER_ID} with convert set to true" *(create the directory with `a.csv` and `archive.zip`)*

**Checks**
- Call `upload_local_folder(local_path="/tmp/qa-folder-241/", parent_folder_id="{FOLDER_ID}", convert=true)`
- `a.csv` appears in `uploaded` and converts normally
- `archive.zip` appears in `failed` with an error mentioning the `.zip` extension is unsupported, not in `uploaded`
- `list_files` on `{FOLDER_ID}` shows no file created for `archive.zip`

**Teardown**
Delete the converted `a.csv` from `{FOLDER_ID}`. Remove `/tmp/qa-folder-241/`.

**Result (2026-08-04) ✅ PASS** — Verified via `mcp-gee-sweet-sky` (PR #505 regression check) against an isolated fixture folder. `a.csv` appeared in `uploaded`; `archive.zip` appeared in `failed` with error `"Conversion not supported for extension '.zip'. Supported extensions: .csv, .docx, .htm, .html, .md, .pptx, .xlsx"`, and no Drive file was created for it.

---

### TC-D242: convert=True — an existing unconverted duplicate is not treated as skip-worthy (mirrors TC-D215 for the bulk path) ⚠️ local-filesystem
**Prompt**
> Step 1: "Upload the directory `/tmp/qa-folder-242/` to {FOLDER_ID}" *(no convert — creates a raw `text/csv` file named `a.csv`)*
> Step 2: "Upload the directory `/tmp/qa-folder-242/` to {FOLDER_ID} with convert set to true"

**Checks**
- Step 2's `a.csv` appears in `uploaded` (not `skipped`) — a same-named raw file already existing in Drive doesn't count as the converted duplicate
- `list_files` on `{FOLDER_ID}` shows two distinct files: the original raw `text/csv` one from step 1, and the new converted spreadsheet from step 2 (Drive's own import-conversion strips the `.csv` extension from the converted copy's display name, same as TC-D215)

**Teardown**
Delete both files from `{FOLDER_ID}`. Remove `/tmp/qa-folder-242/`.

**Result (2026-08-04) ✅ PASS** — Verified via `mcp-gee-sweet-sky` (PR #505 regression check) against an isolated fixture folder. Step 2's `a.csv` appeared in `uploaded`, not `skipped`. `list_files` showed two distinct files: the original raw `text/csv` `a.csv`, and the new converted `a` spreadsheet — distinct `fileId`s confirmed.

---

### TC-D243: convert=True — a second run against the same folder skips the already-converted file (PR #505 review, issue #411) ⚠️ local-filesystem
**Background:** `upload_local_folder`'s `convert=True` skip check keys `existing_by_name` by Drive's *actual* returned file name but looks up entries by the local file's own name (`p.name`, extension included). Drive's native import-conversion strips the source extension from the converted copy's display name (confirmed live via TC-D215/TC-D242 — a converted `data.csv` shows up in Drive as `data`, not `data.csv`), so the lookup by `p.name` never matches a previously-converted file. A second `convert=True` run against the same folder is expected to re-convert and duplicate every file already converted by the first run.

**Prompt**
> Step 1: "Upload the directory `/tmp/qa-folder-243/` to {FOLDER_ID} with convert set to true" *(create the directory with a single `dup.csv`)*
> Step 2: "Upload the directory `/tmp/qa-folder-243/` to {FOLDER_ID} with convert set to true again"

**Checks**
- Step 2's `dup.csv` appears in `skipped`, not `uploaded` — the already-converted file from step 1 should be recognized and not re-converted
- `list_files` on `{FOLDER_ID}` shows exactly one converted Sheet from `dup.csv`, not two

**Teardown**
Delete the converted file(s) from `{FOLDER_ID}`. Remove `/tmp/qa-folder-243/`.

**Result (2026-08-04) ❌ FAIL (round 1)** — Verified via `mcp-gee-sweet-sky` against a fresh isolated fixture folder. Step 1 uploaded `dup.csv` as expected (`uploaded: ["dup.csv"]`). Step 2 also returned `uploaded: ["dup.csv"]` instead of `skipped` — confirmed the bug live, not just via code inspection. `list_files` on the fixture folder showed two distinct Sheet files both named `dup` (extension stripped by Drive on both conversions), with different `fileId`s and `modifiedTime`s ~18s apart — exactly the duplicate-reconversion failure PR #505's code review predicted. Fixture folder and files trashed as teardown. This confirms the bug reported to the Dev in the PR #505 QA-round-1 comment.

**Result (2026-08-05) ✅ PASS (round 2, fix 53df82b)** — Verified via `mcp-gee-sweet-sky` against a fresh isolated fixture folder. Step 2 now returns `skipped: ["dup.csv"]`, `uploaded: []`. `list_files` showed exactly one converted `dup` Sheet, no duplicate. Also live-tested the mixed raw+converted edge case the fix commit specifically claims to handle (not in the original checks above): raw upload, then `convert=True` twice — the third call correctly skips (`skipped: ["dup.csv"]`) with `list_files` showing exactly two files total (the raw `dup.csv` and the converted `dup`), no third copy. `TestUploadLocalFolder` unit suite (12 tests) passes. Fixtures trashed as teardown.

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

### TC-D217: convert_markdown=True — local .md file uploads as a native Google Doc (issue #211) ⚠️ local-filesystem
**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-211/` using direction='upload' and convert_markdown set to true" *(create `/tmp/qa-sync-211/notes.md` locally first, with a heading and a paragraph, nothing matching in Drive yet)*

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-211/", direction="upload", convert_markdown=true)`
- `uploaded` contains `notes.md`
- `list_files` on `{FOLDER_ID}` shows the new file's `mimeType` as `application/vnd.google-apps.document`, still named `notes.md` (not renamed, not `.gdoc`)
- `get_doc_content` on the new file's ID returns readable text matching the markdown source

**Result (2026-07-25) ✅ PASS** Ran against a throwaway scratch subfolder of `{FOLDER_ID}` (not the shared top level, per `run.md`'s pollution guidance). `uploaded: ["notes.md"]`; `list_files` showed `mimeType: application/vnd.google-apps.document`, name still `notes.md`; `get_doc_content` returned the markdown source as readable text.

---

### TC-D218: convert_markdown resync matches the converted Doc — no duplicate created ⚠️ local-filesystem
**Prompt** (immediately after TC-D217, same fixture, no local changes)
> "Sync {FOLDER_ID} with `/tmp/qa-sync-211/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- `notes.md` appears in `skipped` ("in sync"), not `uploaded`
- `list_files` on `{FOLDER_ID}` still shows only one `notes.md` (no duplicate from a repeat upload)

**Result, round 1 (2026-07-25) ❌ FAIL** No duplicate was created (`list_files` still showed exactly one `notes.md`), but the resync did **not** skip — it landed in `failed` with `"Cannot download native Google Doc without export_format (convert_markdown has no reverse conversion)"`, and stayed stuck there on a second identical resync attempt (never converges to skip on its own). Root cause: Drive's native import-conversion on `create()` overwrites the `modifiedTime` we request in the request body with its own "now" — confirmed via `get_file_metadata`, local mtime `15:02:32.000Z` vs. Drive's actual `modified_time` `15:02:46.724Z`, a ~14.7s gap driven by conversion latency, comfortably outside the 5s sync tolerance. `diff = local − drive` is therefore negative ("drive newer"), so `bidirectional` picks `download`, which then hits the new no-`export_format` guard and fails. This is a live-only defect the code review's static pass didn't catch (it requires observing Drive's actual post-conversion `modifiedTime`, not just reading the source) and it breaks the PR's own stated purpose — "re-syncs settle into 'in sync'... instead of re-uploading a duplicate every run" does not hold for `direction='bidirectional'`, the mode most users would actually run repeatedly. `direction='upload'` sidesteps this (see TC-D219) because it never reaches the download branch.

**Result, round 2 (2026-07-25) ✅ PASS** After the fix's metadata-only `files().update()` re-stamp following `create()`: `notes.md` landed in `skipped`, not `failed`, on the immediate resync. `get_file_metadata` confirmed Drive's `modified_time` (`15:47:12.000Z`) now matches the local mtime exactly, byte-for-byte on the seconds field — no drift. Ran a second identical resync immediately after to confirm it's not a one-off race; stayed `skipped` both times.

---

### TC-D219: convert_markdown — local edit re-converts in place, not a new file ⚠️ local-filesystem
**Prompt** (after TC-D218; edit `/tmp/qa-sync-211/notes.md` locally, add a new paragraph)
> "Sync {FOLDER_ID} with `/tmp/qa-sync-211/` using direction='upload' and convert_markdown set to true"

**Checks**
- `notes.md` appears in `uploaded`
- `list_files` on `{FOLDER_ID}` still shows only one `notes.md` file (same `fileId` as TC-D217/218 — updated, not recreated)
- `get_doc_content` on that file shows the new paragraph

**Result, round 1 (2026-07-25) ✅ PASS** `uploaded: ["notes.md"]`; same file ID as TC-D217/218 (updated via `files().update()`, not recreated); `get_doc_content` showed both the original and new paragraph. Note: on this `update()` path Drive respected the `modifiedTime` we set exactly (`15:03:53.000Z`, no conversion-latency drift) — unlike the `create()` path in TC-D217/218, which is the asymmetry behind that failure.

**Result, round 2 (2026-07-25) ✅ PASS** Re-verified after the fix (the upload branch gained a mismatch check for finding #3): re-edited the same converted Doc and re-uploaded with `direction='upload'`. Same file ID reused (`files().update()`, not recreated); `get_doc_content` showed all three paragraphs (original + TC-D218 fixture text + this round's new paragraph). No regression from the added mismatch-check logic.

**Teardown (TC-D217–TC-D219)**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-211/`.

---

### TC-D220: convert_markdown omitted (default False) — .md still uploads as plain text ⚠️ local-filesystem
**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-211b/` using direction='upload'" *(convert_markdown not mentioned; create `/tmp/qa-sync-211b/notes.md` locally first)*

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-211b/", direction="upload")` (no `convert_markdown` arg)
- `uploaded` contains `notes.md`
- File's `mimeType` in Drive is `text/plain` (or `text/markdown`, per local mimetypes config), not `application/vnd.google-apps.document` — unchanged from pre-#211 behavior

**Result (2026-07-25) ✅ PASS** `uploaded: ["notes.md"]`; `list_files` showed `mimeType: text/markdown`, confirming default (unset) `convert_markdown` behavior is unchanged from pre-#211.

**Teardown**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-211b/`.

---

### TC-D221: convert_markdown — Drive-only converted Doc with no export_format reports a clean conflict, not a crash or a doomed download (round 2 review, #414) ⚠️ local-filesystem
**Background:** a converted Doc with no local counterpart yet ('drive only') is matched into the sync plan without requiring `export_format` (so TC-D218's resync works) — this reopens a path that used to always be excluded, so it needs its own guard against a raw `KeyError` when no `export_format` is set. Round 1 of this test case predates a fix (round 2, PR #414) that scopes converted-Doc matching to a Drive `properties` marker this tool sets on create — see TC-D222 for why. Because that marker can't be set through any public tool, this fixture reuses TC-D217's own conversion call to produce a genuinely-marked Doc, then removes only the local twin to make it drive-only.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-221/` using direction='upload' and convert_markdown set to true" *(create `/tmp/qa-sync-221/notes.md` locally first, with any content, nothing matching in Drive yet — same shape as TC-D217, distinct fixture dir)*
>
> Then delete the local file only: remove `/tmp/qa-sync-221/notes.md` (leave the Drive-side Doc it just created untouched).
>
> Then: "Sync {FOLDER_ID} with `/tmp/qa-sync-221/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- The first (upload) call succeeds; `notes.md` appears in `uploaded`
- After deleting the local file, the second (bidirectional) call: no exception raised
- `notes.md` appears in `conflicts`, not `failed`, not `downloaded`
- `list_files` on `{FOLDER_ID}` still shows exactly one `notes.md` Doc (untouched, not deleted or modified)

**Result, round 1 (2026-07-25) ✅ PASS, against the pre-fix Prompt/Checks above** — this result predates round 2's rewrite of this test case's Prompt/Checks (see Background) and doesn't map onto them; it's kept for the record rather than deleted. Original fixture used an `orphan.md` Doc created directly via `create_doc` (no local counterpart, no `properties` marker — round 1's matching was still name+mimeType only). No exception; `failed: [{"name": "orphan.md", "error": "Cannot download native Google Doc without export_format (convert_markdown has no reverse conversion)"}]`; not present in `downloaded`. Same failure-shape as TC-D218's (unintended) failure, confirming the guard itself worked correctly in round 1 — the problem was that TC-D218 reached it on a path that should never have been a failure at all.

**Result, round 2 (2026-07-25) ✅ PASS, against the rewritten Prompt/Checks above** — convert-uploaded `notes.md` via TC-D217's own mechanism, then removed only the local twin. Bidirectional resync: no exception; `conflicts: ["notes.md"]`, not present in `failed` or `downloaded`; `list_files` showed exactly one `notes.md` Doc, untouched.

**Teardown**
Delete the `notes.md` Doc from `{FOLDER_ID}`. Remove `/tmp/qa-sync-221/`.

---

### TC-D222: convert_markdown — a pre-existing unrelated Doc with a colliding name is never treated as this tool's converted twin (#414 QA review, finding #2) ⚠️ local-filesystem
**Background:** matching a Drive Doc back to its local `.md` file used to rely only on name + mimeType, so any human-created Doc that happened to be named `notes.md` would be silently treated as if this tool had created it — letting a same-named local file overwrite that Doc's real content via `files().update()`. The fix scopes matching to a Drive `properties` marker this tool sets on its own conversions, which a pre-existing unrelated Doc never has.

**Prompt**
> In `{FOLDER_ID}`, create a Google Doc titled `notes.md` via `create_doc(title="notes.md")` and write some distinct placeholder content into it with `write_doc_content`. Then create `/tmp/qa-sync-222/notes.md` locally with different content, and:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-222/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-222/", direction="bidirectional", convert_markdown=true)`
- `notes.md` appears in `uploaded` (the local file is treated as local-only and converted into a *new* Doc — it does not match the pre-existing unrelated one)
- `list_files` on `{FOLDER_ID}` now shows **two** files named `notes.md` (the original unrelated Doc, untouched, plus the newly-created converted one)
- `get_doc_content` on the original Doc's ID still returns the original placeholder content — confirming it was never overwritten

**Result (2026-07-25) ✅ PASS** `uploaded: ["notes.md"]`; `list_files` showed two `notes.md` files after the sync (the pre-existing unrelated Doc plus a newly-created converted one, distinct IDs); `get_doc_content` on the original Doc's ID returned `"ORIGINAL unrelated Doc content — never touched by conversion."` unchanged — confirms the `properties`-marker fix prevents the collision.

**Teardown**
Delete both `notes.md` files from `{FOLDER_ID}`. Remove `/tmp/qa-sync-222/`.

---

### TC-D223: convert_markdown cannot promote a file previously synced with convert_markdown=False (#414 QA review, finding #3) ⚠️ local-filesystem
**Background:** Drive's API has no supported way to convert an existing file's type via `files().update()` — only `files().create()` honors native import conversion. A `.md` file first synced as a plain file and later re-synced with `convert_markdown=True` used to silently re-upload markdown text into the still-plain file rather than promoting it to a Doc. The fix detects the mismatch and fails cleanly instead.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-223/` using direction='upload'" *(convert_markdown omitted; create `/tmp/qa-sync-223/notes.md` locally first, nothing matching in Drive yet)*
>
> Then edit `/tmp/qa-sync-223/notes.md` locally (add a paragraph, so it's newer than the plain Drive file), and:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-223/` using direction='upload' and convert_markdown set to true"

**Checks**
- First call: `notes.md` appears in `uploaded`; `list_files` shows its `mimeType` as `text/plain`/`text/markdown`, not a Google Doc
- Second call: no exception raised
- `notes.md` appears in `failed`, not `uploaded`, with an error message mentioning it's a plain file and can't be promoted
- `list_files` on `{FOLDER_ID}` still shows the same file, still not a Google Doc, with its original (first-upload) content — the second call's markdown text was never written into it

**Result (2026-07-25) ✅ PASS** First call: `uploaded: ["notes.md"]`, `mimeType: text/markdown`. Second call (edited + `convert_markdown=true`): no exception; `failed: [{"name": "notes.md", "error": "'notes.md' already exists in Drive as a plain file, not a converted Doc — convert_markdown cannot promote an existing file's type; delete it in Drive and re-sync to convert"}]`, not in `uploaded`. `list_files` afterward showed `mimeType` still `text/markdown` and `modified_time` unchanged from the first upload, confirming the second call's content was never written.

**Teardown**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-223/`.

---

### TC-D224: convert_markdown + export_format together never exports a converted Doc's binary content into a `.md`-named file (#414 QA review, finding #1) ⚠️ local-filesystem
**Background:** a converted Doc has no reverse conversion. Before the fix, if `export_format` was *also* supplied alongside `convert_markdown=True`, a drive-only converted Doc would skip the "no `export_format`" guard and fall through to a real export call — writing e.g. binary PDF bytes into a file still named `.md`.

**Prompt**
> Reuse TC-D221's setup: convert-upload `/tmp/qa-sync-224/notes.md` (direction='upload', convert_markdown=true), then delete the local file only, leaving the Drive-side converted Doc. Then:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-224/` using direction='bidirectional', convert_markdown set to true, and export_format set to 'pdf'"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-224/", direction="bidirectional", convert_markdown=true, export_format="pdf")`
- No exception raised
- `notes.md` appears in `conflicts`, not `downloaded`, not `failed`
- `/tmp/qa-sync-224/notes.md` is **not created on disk** — confirms no binary export content was written into a `.md`-named file

**Result (2026-07-25) ✅ PASS** No exception; `conflicts: ["notes.md"]`, not in `downloaded` or `failed`; local directory stayed empty — no binary export content was written to disk. Also spot-checked `dry_run=true` with the same inputs: `actions` reported `{"name": "notes.md", "action": "conflict", "reason": "drive-only convert_markdown Doc has no reverse conversion — add a matching local .md or remove it in Drive"}` — confirms finding #4 (dry_run mislabeling) is also resolved, since the plan-building loop now classifies this case identically for both dry_run and live runs.

**Teardown**
Delete the `notes.md` Doc from `{FOLDER_ID}`. Remove `/tmp/qa-sync-224/`.

---

### TC-D225: convert_markdown resync without the flag still matches — no duplicate (round 3 review, #414) ⚠️ local-filesystem
**Background:** matching used to be gated on the *current call's* `convert_markdown` flag, not just the Doc's own stamped property. A resync that simply omitted `convert_markdown=True` on a folder containing an already-converted Doc saw the local `.md` as "local only" and silently created a second, plain-text duplicate — no error, no warning.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-sync-225/` using direction='upload' and convert_markdown set to true" *(create `/tmp/qa-sync-225/notes.md` locally first, nothing matching in Drive yet)*
>
> Then, with no local changes: "Sync {FOLDER_ID} with `/tmp/qa-sync-225/` using direction='bidirectional'" *(convert_markdown omitted this time)*

**Checks**
- First call: `notes.md` appears in `uploaded`
- Second call (flag omitted): `notes.md` appears in `skipped` ("in sync"), not `uploaded`
- `list_files` on `{FOLDER_ID}` shows exactly **one** `notes.md` file — no duplicate plain-text copy created

**Result (2026-07-25) ✅ PASS** First call: `uploaded: ["notes.md"]`. Second call (flag omitted): `skipped: ["notes.md"]`, `uploaded: []`; `list_files` showed exactly one `notes.md`, still `application/vnd.google-apps.document`. Also checked the companion scenario (local edit + flag omitted, matching the new `test_local_edit_without_flag_reimports_in_place_not_duplicated` unit test): edited the local file and re-synced with `direction='upload'`, `convert_markdown` omitted — `uploaded: ["notes.md"]`, same file ID reused (not recreated), `get_doc_content` showed the edited text correctly reimported, no duplicate.

**Additional round-3 code-review finding checked and refuted:** the review theorized Drive's import-conversion might complete *asynchronously after* our metadata-only `modifiedTime` re-stamp (the TC-D218 fix), silently undoing it and reproducing the original bug in softened form (permanent `conflict` instead of permanent `failed`). Tested directly: converted a fresh file, confirmed `modified_time` matched the local mtime exactly immediately after upload, then re-checked via `get_file_metadata` after several minutes of real elapsed time (doing other QA work in between, not a sleep) — `modified_time` was unchanged, and a `sync_folder` resync at that point still returned `skipped`. No drift observed; the conversion is synchronous within the `create()` call, not a background job that continues after it returns.

**Teardown**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-225/`.

---

### TC-D226: a Doc converted via upload_local_file(convert=True) is recognized by sync_folder's convert_markdown matching (round 3 review, #414, finding #2) ⚠️ local-filesystem
**Background:** before the fix, only `sync_folder`'s own `create()` call stamped the marker property matching relies on — `upload_local_file(convert=True)`'s converted Docs were invisible to it despite the docstring calling this "the same mechanism," so a subsequent `sync_folder` run on the same folder silently created a second Doc.

**Prompt**
> In `{FOLDER_ID}`, call `upload_local_file(local_path="/tmp/qa-sync-226-src/notes.md", convert=true)` *(create that local file first, with any content)*. Then, with `/tmp/qa-sync-226/notes.md` containing identical content and mtime close to now:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-226/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- `upload_local_file` call succeeds; `list_files` shows the new Doc named `notes.md`
- `sync_folder` call: `notes.md` appears in `skipped` ("in sync"), not `uploaded`
- `list_files` on `{FOLDER_ID}` still shows exactly **one** `notes.md` file — no second Doc created

**Result (2026-07-25) ✅ PASS (core fix), with a follow-up finding** `upload_local_file(convert=true)` succeeded; `list_files` showed the new Doc. First `sync_folder` attempt landed in `conflicts` rather than `skipped` — correctly matched the existing Doc (no duplicate; `list_files` showed exactly one `notes.md` throughout, confirming the core fix works), but not the "in sync" outcome this case's Checks describe. Root cause, confirmed via code: `_upload_local_file` (`transfer.py` ~line 138-148) never sets `modifiedTime` on the Doc it creates, unlike `_sync_level`'s own upload path which explicitly stamps the local file's mtime — so a Doc from `upload_local_file(convert=True)` always carries Drive's own creation timestamp instead. This isn't a one-off timing fluke from test-fixture setup delay (my first guess); it's structural, and will produce a spurious `conflict` on very close to every first `sync_folder` call after an `upload_local_file(convert=True)`, not just an occasional one — confirmed by re-running with the local mtime deliberately set to match Drive's `modified_time`, which *did* land `skipped` as this case describes, but only because I forced that match by hand. Flagged to Dev as a follow-up finding (#3 in the round-3 code review) rather than blocking this round on it — the outcome is a safe, non-destructive `conflict`, not data loss or a duplicate. Also re-verified TC-D222 (unrelated pre-existing `.md` Doc) still holds after this round's matching change: two distinct `notes.md` files resulted, original's content untouched — no regression.

**Teardown**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-226-src/` and `/tmp/qa-sync-226/`.

---

### TC-D227: convert_markdown — a plain file and a converted Doc sharing the same name are reported as a clean failure, not silently overwritten (issue #422, finding #1) ⚠️ local-filesystem

**Background:** Drive allows a plain file and a `convert_markdown`-produced Doc to share the same display name — both compute the same `drive_map` key during plan-building. Before the fix, whichever was enumerated last silently won the slot; the other became completely invisible to that sync (never uploaded, downloaded, or reported anywhere).

**Prompt**
> In `{FOLDER_ID}`, call `upload_file(name="notes.md", content="plain text version")` to create a plain file named `notes.md`. Then call `upload_local_file(local_path="/tmp/qa-sync-227-src/notes.md", parent_folder_id="{FOLDER_ID}", convert=true)` *(create that local source file first, with any content)* — Drive now has two files both named `notes.md`: one plain, one a converted Google Doc. With `/tmp/qa-sync-227/` created but empty (no local file):
> "Sync {FOLDER_ID} with `/tmp/qa-sync-227/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-227/", direction="bidirectional", convert_markdown=true)`
- `failed` contains exactly one entry for `notes.md`, with an error mentioning both a plain file and a convert_markdown Doc sharing the name
- `notes.md` does not appear in `uploaded`, `downloaded`, `skipped`, or `conflicts`
- `list_files` on `{FOLDER_ID}` afterward still shows both original `notes.md` files untouched (two distinct file IDs, unchanged content)

**Teardown**
Delete both `notes.md` files from `{FOLDER_ID}`. Remove `/tmp/qa-sync-227-src/` and `/tmp/qa-sync-227/`.

**Result (2026-07-26) ✅ PASS** — Created a plain `notes.md` via `upload_file` and a converted `notes.md` Doc via `upload_local_file(convert=true)`, then `sync_folder(direction="bidirectional", convert_markdown=true)` returned `failed: [{"name": "notes.md", "error": "both a plain file and a convert_markdown Doc are named 'notes.md' in this Drive folder — sync can't tell which one the local file matches; rename or remove one of them in Drive"}]` — exactly one entry, absent from `uploaded`/`downloaded`/`skipped`/`conflicts`. Follow-up `list_files` confirmed both original file IDs untouched with unchanged `modifiedTime`. Both files trashed after the test.

---

### TC-D228: upload_local_file(convert=True) stamps modifiedTime from the local file's mtime, so a follow-up sync_folder lands in skipped, not conflicts (issue #422, finding #2 — follow-up to TC-D226) ⚠️ local-filesystem

**Background:** TC-D226 flagged a follow-up finding: `_upload_local_file` never set `modifiedTime` on a converted Doc, unlike `_sync_level`'s own upload path which stamps the local file's mtime — so the Doc always carried Drive's own creation timestamp instead, landing a subsequent `sync_folder(convert_markdown=true)` in `conflicts` rather than `skipped` on very close to every first run. The fix stamps `modifiedTime` on `create()` and re-stamps it via a metadata-only `update()` afterward, since Drive's native import-conversion overwrites the `create()`-time value once conversion finishes (the same drift `_sync_level`'s own path already works around, per TC-D218).

**Prompt**
> In `{FOLDER_ID}`, call `upload_local_file(local_path="/tmp/qa-sync-228-src/notes.md", parent_folder_id="{FOLDER_ID}", convert=true)` *(create that local file first, with any content)*. Then, with `/tmp/qa-sync-228/notes.md` containing identical content copied immediately after (same mtime, no manual adjustment):
> "Sync {FOLDER_ID} with `/tmp/qa-sync-228/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- `upload_local_file` call succeeds; `get_file_metadata` on the returned `fileId` shows `modifiedTime` close to the local source file's mtime, not a later Drive-assigned creation time
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-228/", direction="bidirectional", convert_markdown=true)`: `notes.md` appears in `skipped` ("in sync"), not `conflicts` — this is the exact scenario TC-D226 flagged as a follow-up finding, now fixed
- `list_files` on `{FOLDER_ID}` still shows exactly one `notes.md` file

**Teardown**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-228-src/` and `/tmp/qa-sync-228/`.

**Result (2026-07-26) ✅ PASS** — `upload_local_file(convert=true)` returned a Doc whose `get_file_metadata` showed `modifiedTime: "2026-07-27T04:59:26.000Z"`, matching the local source file's mtime exactly, not `createdTime: "2026-07-27T05:00:01.406Z"` (35s later). With the local copy's mtime touched to match the source, `sync_folder(direction="bidirectional", convert_markdown=true)` landed `notes.md` in `skipped` ("in sync"), not `conflicts` — the exact TC-D226 follow-up scenario, now fixed. File trashed after the test.

---

### TC-D229: convert_markdown — a drive-only converted Doc reports skip under direction='upload', conflict only when a download would otherwise be attempted (issue #422, finding #3) ⚠️ local-filesystem

**Background:** the drive-only branch of the plan-building loop checked `_is_converted_md` before checking `direction`, so a convert_markdown Doc with no local counterpart always reported `conflict` — even under `direction='upload'`, where an ordinary (non-converted) drive-only file correctly reports a plain `skip`, since an upload-only caller doesn't care about drive-only content at all. The fix routes the convert_markdown case through the same direction check as the ordinary case.

**Prompt**
> In `{FOLDER_ID}`, call `upload_local_file(local_path="/tmp/qa-sync-229-src/notes.md", parent_folder_id="{FOLDER_ID}", convert=true)` *(create that local file first, with any content — this Doc will be drive-only from `/tmp/qa-sync-229/`'s perspective, since nothing exists there)*. With `/tmp/qa-sync-229/` created but empty:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-229/` using direction='upload' and convert_markdown set to true"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-229/", direction="upload", convert_markdown=true)`: `notes.md` appears in `skipped` ("drive only, upload direction"), not `conflicts`; `failed` and `downloaded` are both empty
- Repeat with `direction='bidirectional'` against the same fixture (still no local file): `notes.md` now appears in `conflicts` (unchanged behavior — a convert_markdown Doc still can't be downloaded, so a direction that would otherwise attempt one must still report conflict, not skip)

**Teardown**
Delete `notes.md` from `{FOLDER_ID}`. Remove `/tmp/qa-sync-229-src/` and `/tmp/qa-sync-229/`.

**Result (2026-07-26) ✅ PASS** — With a drive-only convert_markdown Doc and no local counterpart, `sync_folder(direction="upload", convert_markdown=true)` reported `notes.md` under `skipped` ("drive only, upload direction") with `failed`/`downloaded` both empty. Repeating with `direction="bidirectional"` against the same fixture flipped it to `conflicts`, as expected since a convert_markdown Doc has no reverse conversion. File trashed after the test.

---

### TC-D230: two plain files sharing the same name are also reported as a collision failure, not just a plain-file/converted-Doc pair (PR #433 review, finding #2) ⚠️ local-filesystem

**Background:** TC-D227's collision guard originally only fired when one colliding entry was a `convert_markdown` Doc and the other was a plain file (differing `_is_converted_md`). A same-type collision — e.g. two ordinary plain files sharing a display name — was silently overwritten just the same, reproducing issue #422's own bug in a case the original fix didn't close. The fix broadens the guard to any duplicate name in `drive_map`, regardless of type.

**Prompt**
> In `{FOLDER_ID}`, call `upload_file(name="notes.md", content="version A")`. Then call `upload_file(name="notes.md", content="version B")` — Drive now has two distinct plain files, both named `notes.md`. With `/tmp/qa-sync-230/` created but empty (no local file):
> "Sync {FOLDER_ID} with `/tmp/qa-sync-230/` using direction='bidirectional'"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-230/", direction="bidirectional")`
- `failed` contains exactly one entry for `notes.md`, with an error mentioning multiple Drive entries sharing the name
- `notes.md` does not appear in `uploaded`, `downloaded`, `skipped`, or `conflicts`
- `list_files` on `{FOLDER_ID}` afterward still shows both `notes.md` files untouched (two distinct file IDs, unchanged content)

**Teardown**
Delete both `notes.md` files from `{FOLDER_ID}`. Remove `/tmp/qa-sync-230/`.

**Result (2026-07-27) ✅ PASS** — Created two distinct plain `notes.md` files, then `sync_folder(direction="bidirectional")` returned `failed: [{"name": "notes.md", "error": "multiple files are named 'notes.md' in this Drive folder — ..."}]`, absent from `uploaded`/`downloaded`/`skipped`/`conflicts`. `get_file_metadata` on both file IDs afterward confirmed neither was touched. (The same call also caught two pre-existing same-name collisions already present in the fixture folder — `qa-notes.md` and `qa-upload.txt`, each duplicated from earlier QA runs — confirming the broadened guard also catches real fixture drift, not just the synthetic test case; not a new ticket, already covered by #304's Drive pollution tracking.) Both test files trashed after.

---

### TC-D231: a local file whose name collides with a Drive-side pair is reported as failed, not silently dropped from every result list (PR #433 review, finding #3) ⚠️ local-filesystem

**Background:** TC-D227's fixture had no local counterpart for the colliding name. When a local file *does* share the colliding name, the plan-building loop's `continue` used to skip it entirely — it never appeared in `uploaded`, `downloaded`, `skipped`, `conflicts`, or `actions`, with zero indication anything was wrong. The fix routes the collision through the normal plan machinery so it's always reported.

**Prompt**
> In `{FOLDER_ID}`, call `upload_file(name="notes.md", content="plain text version")`. Then call `upload_local_file(local_path="/tmp/qa-sync-231-src/notes.md", parent_folder_id="{FOLDER_ID}", convert=true)` *(create that local source file first, with any content)* — Drive now has both a plain file and a converted Doc named `notes.md`. Now create `/tmp/qa-sync-231/notes.md` locally too (any content), then:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-231/` using direction='bidirectional' and convert_markdown set to true"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-231/", direction="bidirectional", convert_markdown=true)`
- `failed` contains exactly one entry for `notes.md` (same shape as TC-D227, now confirmed to fire even with a local counterpart present)
- `notes.md` does not appear in `uploaded`, `skipped`, or `conflicts`
- `list_files` on `{FOLDER_ID}` afterward still shows both original Drive-side `notes.md` files untouched; local `/tmp/qa-sync-231/notes.md` is also untouched (no new upload attempted)

**Teardown**
Delete both `notes.md` files from `{FOLDER_ID}`. Remove `/tmp/qa-sync-231-src/` and `/tmp/qa-sync-231/`.

**Result (2026-07-27) ✅ PASS** — With a local `notes.md` present alongside the plain-file/converted-Doc collision, `sync_folder(direction="bidirectional", convert_markdown=true)` still correctly reported exactly one `failed` entry for `notes.md`, not silently dropped as it was pre-fix. Local file content and both Drive-side file IDs' `modified_time` confirmed untouched afterward. All three files removed after the test.

---

### TC-D232: a name collision under dry_run reports as a conflict preview, not a failed entry (PR #433 review, finding #4) ⚠️ local-filesystem

**Background:** `dry_run=true` never materializes any transfer, so `failed` should only ever contain real execution failures — nothing should land there during a preview. The collision guard's `failed.append()` originally ran unconditionally in the `drive_map`-building loop, before the `dry_run` gate, so a collision showed up in `failed` even during dry_run — inconsistent with the pre-existing folder-collision failure path in the same function, which is explicitly guarded against this. The fix reports it as a `conflict` in `actions` (with `action: "collision"`) during dry_run, and only as a real `failed` entry once execution is actually attempted. **Update (#512, see TC-D244):** the flat `conflicts` list (like every other flat list) is now always empty during `dry_run` — `actions` alone is the complete preview, so this case's own collision entry only shows up there now, not in both places.

**Prompt**
> Reuse TC-D227's setup: a plain file and a `convert_markdown`-produced Doc both named `notes.md` in `{FOLDER_ID}`. With `/tmp/qa-sync-232/` created but empty:
> "Sync {FOLDER_ID} with `/tmp/qa-sync-232/` using direction='bidirectional', convert_markdown set to true, and dry_run set to true"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-sync-232/", direction="bidirectional", convert_markdown=true, dry_run=true)`
- `failed` is empty; `conflicts` is also empty (#512 — flat lists stay empty during dry_run)
- `actions` contains one entry for `notes.md` with `"action": "collision"`
- Neither Drive-side `notes.md` file was touched (nothing materializes during dry_run)

**Teardown**
Delete both `notes.md` files from `{FOLDER_ID}`. Remove `/tmp/qa-sync-232/`.

**Result (2026-08-04) ✅ PASS** — Reproduced with a scratch fixture (own scratch folder, not the shared `{FOLDER_ID}`): `sync_folder(..., convert_markdown=true, dry_run=true)` against a plain `notes.md` and a `convert_markdown`-produced Doc also named `notes.md` returned `failed: []`, `conflicts: []`, and `actions: [{"name": "notes.md", "action": "collision", "reason": "a plain file and a convert_markdown Doc are named 'notes.md' in this Drive folder — sync can't tell which one the local file matches; rename or remove one of them in Drive"}]` — confirms the #512 dry_run/flat-lists-always-empty change applies to the collision case too, not just skip/upload/download. Both scratch files trashed after the test.

---

### TC-D119: Invalid direction or export_format returns error, not a raised exception ⚠️ local-filesystem (issue #488)

**Prompt 1**
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` using direction='mirror'"

**Prompt 2** (PR #563 review round — the identical bug in the adjacent `export_format` check)
> "Sync {FOLDER_ID} with `/tmp/qa-sync/` using export_format='bogus'"

**Checks**
- Prompt 1 returns `{"error": "Invalid direction 'mirror'. Use 'upload', 'download', or 'bidirectional'."}` — not a raised exception, not a silent no-op
- Prompt 2 returns `{"error": "Unknown export_format 'bogus'. Valid: pdf, html, txt, docx, odt, rtf, epub, csv, xlsx, ods, pptx"}` — not a raised exception
- Neither makes a Drive API call (rejected before any upload/download work)

**Result (2026-08-10) ✅ PASS** — Re-verified against fix commit `4b5eb33`. `sync_folder(folder_id=<qa-fixtures folder>, local_path=<scratch dir>, direction='mirror', dry_run=true)` returned exactly `{"error": "Invalid direction 'mirror'. Use 'upload', 'download', or 'bidirectional'."}`. `sync_folder(..., export_format='bogus', dry_run=true)` now also returns `{"error": "Unknown export_format 'bogus'. Valid: pdf, html, txt, docx, odt, rtf, epub, csv, xlsx, ods, pptx"}` — no raised exception, matches `direction`'s shape. Both prompts pass, no Drive API calls made for either.

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

**Background:** `recursive=True` removes the previous implicit bound (one folder's direct children) on the `actions` list; nothing called `enforce_response_size_cap` the way other large-payload tools (e.g. `export_file`) do. The #315 decision doc's own reproduction case (22 subfolders / ~225 files) was a realistic scale to hit `MAX_TOOL_RESPONSE_CHARS`. This needs a large real Drive tree to trip live — if no existing fixture of that scale is available, this may need to be run against a temporarily-constructed large folder rather than the standard QA fixtures. **Update (#512):** the flat lists (`uploaded`/`downloaded`/`skipped`/`conflicts`/`failed`) no longer duplicate `actions` during `dry_run` (see TC-D244), and a `result_local_path` offramp now exists (see TC-D245) — this case still stands for the "narrow scope" no-offramp path, but the error message's bypass guidance changed.

**Prompt**
> "Do a dry run sync of {LARGE_FOLDER_ID} with a matching local directory in bidirectional mode with recursive=True" *(requires a Drive folder with enough nested files/subfolders — roughly 20+ subfolders / 200+ files — to serialize past 40,000 characters)*

**Checks**
- Call raises `ValueError` mentioning the actual response size and the 40,000-character cap
- Error message offers `result_local_path` as a bypass (not bare `local_path` — `sync_folder`'s own `local_path` param already means the sync destination, not a dump target for the oversized response)
- Error message suggests narrowing scope (folder, direction, or non-recursive) instead

*(A 20+ subfolder / 200+ file live fixture is impractical to construct/tear down for a scoped QA pass — this case is deterministically unit-tested instead: `TestSyncFolderResponseSizeCap::test_oversized_result_raises`, `test_error_points_to_result_local_path_not_local_path`.)*

---

### TC-D244: dry_run's flat lists stay empty — `actions` alone is the complete, non-redundant preview (issue #512) ⚠️ local-filesystem

**Background:** `sync_folder(dry_run=True)` used to duplicate every `skip`/`conflict` name into both a flat list (`skipped`/`conflicts`) and a full `{name, action, reason}` entry in `actions` — for a folder that's mostly already in sync, this roughly doubled the response for no new information, deterministically tripping the 40,000-character response-size cap on a moderately-sized folder (reported: 303 local / 280 Drive files, only 24 new/changed). Fixed by leaving the flat lists empty during `dry_run` — `actions` was already a complete picture (name + action-type + reason for every item considered, including upload/download entries the flat lists never populated during dry_run even before this fix) — and relying on it exclusively instead of duplicating a subset of it into a second structure.

**Setup**
In a scratch Drive folder, upload ~5 small text files (e.g. `qa-512-a.txt` .. `qa-512-e.txt`). In a local directory, create local copies of 3 of them with the same content and mtime touched to match (so they read as in-sync), leave the remaining 2 Drive-only, and add 1 new local-only file not present in Drive.

**Prompt**
> Call `sync_folder(folder_id="{SCRATCH_FOLDER_ID}", local_path="/tmp/qa-512/", direction="bidirectional", dry_run=true)`

**Checks**
- `result["uploaded"] == []`, `result["downloaded"] == []`, `result["skipped"] == []`, `result["conflicts"] == []`, `result["failed"] == []` — all empty regardless of what the plan actually contains
- `result["actions"]` contains one entry per file considered (5 Drive + 1 local-only = 6), each with `name`, `action`, and `reason`
- The 3 in-sync files appear in `actions` with `action == "skip"`, `reason == "in sync"`
- Each Drive-only file appears in `actions` with `action == "download"` (bidirectional direction)
- The local-only file appears in `actions` with `action == "upload"`
- No file is transferred and no local/Drive state changes (dry_run)

**Teardown**
Delete the 5 Drive files. Remove `/tmp/qa-512/`.

**Result (2026-08-04) ✅ PASS** — Reproduced with a scratch folder (5 files a–e uploaded via `upload_local_file`; a/b/c copied locally with `cp -p` to preserve the mtime `upload_local_file` had already stamped onto Drive, so they land in-sync without any manual touch; d/e left Drive-only; f added local-only). `sync_folder(..., dry_run=true)` returned all five flat lists empty and `actions` with exactly 6 entries: a/b/c `skip`/"in sync", d/e `download`/"drive only", f `upload`/"local only". Scratch folder trashed after the test.

---

### TC-D245: `result_local_path` bypasses the response-size cap and writes the sync result to disk (issue #512)

**Background:** Unlike every other capped tool except `export_file`/`list_file_activity` (both deliberately, per `docs/decisions/decision-response-size-cap-generalization.md`), `sync_folder` had no escape hatch at all — its own `local_path` param is already the sync destination, so it couldn't double as a dump target the way `get_sheet_data`'s `local_path` does. `result_local_path` is a new, separate param serving that purpose: passing it unconditionally writes the full result to disk (bypassing the cap entirely, matching the `get_doc_content`/`get_sheet_data` pattern) instead of returning it inline.

**Prompt**
> Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-512b/", direction="bidirectional", dry_run=true, result_local_path="/tmp/qa-512b-result/")`

**Checks**
- Call succeeds (no `ValueError`) even if the inline result would otherwise be small (this bypass is unconditional once passed, not only triggered when the cap is actually exceeded)
- Returned manifest contains `local_path` (pointing at a file under `/tmp/qa-512b-result/`), `bytes_written`, `folder_id`, and `dry_run: true` — not the sync result's own keys (`uploaded`/`actions`/etc.) directly
- Reading the file at the manifest's `local_path` and parsing it as JSON reproduces the same shape `sync_folder` would have returned inline (`uploaded`, `downloaded`, `skipped`, `conflicts`, `failed`, `folders_skipped`, `size_bytes`, `dry_run`, `actions`)

**Teardown**
Remove `/tmp/qa-512b/` and `/tmp/qa-512b-result/`.

**Result (2026-08-04) ✅ PASS** — Reusing TC-D244's scratch fixture, `sync_folder(..., dry_run=true, result_local_path=<result dir>/)` returned only `{local_path, bytes_written, folder_id, dry_run: true}` (no inline `uploaded`/`actions`/etc.). Reading the written JSON file reproduced the exact same shape/values the inline call in TC-D244 returned. **Live-confirmed a related correctness gap while running this case — see the PR comment: `result_local_path` has no guard against pointing inside the sync's own `local_path`, so the written manifest file gets picked up as a spurious local-only file on the next sync.**

---

### TC-D246: `result_local_path` pointing at or inside `local_path` is rejected up front (PR #518 review finding, issue #512)

**Background:** TC-D245's live pass caught this: `local_path` is scanned as sync input on every call, unlike every other capped tool's `local_path`/`result_local_path` (pure output destinations) — writing the result manifest inside it made the manifest file itself show up as a new local-only entry on the very next sync, and would get uploaded to Drive on a real (non-dry_run) run. Fixed by rejecting the call up front (before any Drive API call) when `result_local_path` resolves to `local_path` itself or a path inside it.

**Prompt**
> Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-512c/", direction="bidirectional", dry_run=true, result_local_path="/tmp/qa-512c/")` (exact same directory as `local_path`)
>
> Then: `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-512c/", direction="bidirectional", dry_run=true, result_local_path="/tmp/qa-512c/nested/out.json")` (nested inside `local_path`)

**Checks**
- Both calls raise `ValueError` mentioning `result_local_path`, before making any Drive API call (no listing, no file created)
- Error message explains why (`local_path` is scanned as sync input) and suggests a separate directory
- A control call with `result_local_path="/tmp/qa-512c-result/"` (a sibling directory, not inside `local_path`) succeeds normally (regression check against TC-D245)

**Teardown**
Remove `/tmp/qa-512c/` and `/tmp/qa-512c-result/`.

**Result (2026-08-04) ✅ PASS** — Reproduced against a scratch fixture. Both invalid calls (`result_local_path` equal to `local_path`, and nested inside it) raised `ValueError: result_local_path (...) must not be local_path (...) or a path inside it...` with no Drive API call made and no file created under `local_path` either time. The sibling-directory control call succeeded normally, writing the manifest under the separate result dir (regression-checked against TC-D245). `uv run python -m pytest tests/drive/test_transfer.py -k result_local_path` also passes (5/5).

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

### TC-D238: `use_checksum=true` skips a file whose content is identical despite a large modifiedTime gap (issue #274) ⚠️ local-filesystem

**Background:** `upload_local_file` doesn't stamp Drive's `modifiedTime` to match the local file's mtime the way `sync_folder`'s own upload path does (same gap TC-D226 flagged for the `convert_markdown` case) — under plain mtime comparison, a file uploaded that way always reads as "Drive newer" on the next `sync_folder`, even when content is byte-identical, and gets needlessly re-downloaded. `use_checksum=true` adds a content check (local md5 vs. Drive's `md5Checksum`) ahead of the mtime comparison: a match is treated as in sync regardless of modifiedTime drift.

**Setup**
Create `/tmp/qa-238-src/dup.txt` locally with any content. Call `upload_local_file(local_path="/tmp/qa-238-src/dup.txt", parent_folder_id="{FOLDER_ID}")` — this Doc's Drive `modifiedTime` will be Drive's own creation timestamp, not stamped to match the local file. Create `/tmp/qa-238/dup.txt` with **identical** content (copy the source file) — its local mtime will differ from Drive's `modifiedTime` by more than 5s (ordinary tool-call latency is enough; no need to force it further).

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-238/` using direction='bidirectional' and use_checksum=true"

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-238/", direction="bidirectional", use_checksum=true)`
- `dup.txt` appears in `skipped`, not `downloaded` or `conflicts`
- Repeat the identical call with `use_checksum` omitted (defaults to `false`) against a **fresh** empty local dir (`/tmp/qa-238b/`) containing the same-content `dup.txt` with the same mtime gap — `dup.txt` should **not** land in `skipped` this time (mtime alone can't tell the content is identical), confirming `use_checksum=true` is what changed the outcome, not something else about the fixture. The exact non-`skipped` bucket it lands in (`uploaded`, `downloaded`, or `conflicts`) depends on which side's mtime ends up later, which this setup doesn't pin down: the Setup step above uploads to Drive *first* and creates the local copy *after*, so the local file's mtime is ordinarily the later of the two — under `direction='bidirectional'` that reads as "local newer" and routes to `uploaded`, not `downloaded`/`conflicts` as an earlier version of this check assumed. Don't treat a specific bucket name as the pass criterion; treat "did not land in `skipped`" as the criterion.

**Teardown**
Delete `dup.txt` from `{FOLDER_ID}`. Remove `/tmp/qa-238-src/`, `/tmp/qa-238/`, `/tmp/qa-238b/`.

**Result (2026-07-31) ✅ PASS** — `use_checksum=true` call: `dup.txt` in `skipped`. Control call (`use_checksum` omitted): `dup.txt` in `uploaded`, not `skipped` — confirms the flag changed the outcome. Reproduces this PR's own code-review finding: the control call's actual bucket is `uploaded`, not the doc's originally-stated `downloaded`/`conflicts`, because this Setup's upload-then-copy ordering makes local mtime the later one; wording above corrected to describe the mechanism instead of a specific bucket name.

---

### TC-D239: `use_checksum=true` has no effect on Google Workspace files (no md5Checksum to compare) (issue #274) ⚠️ local-filesystem

**Background:** Google Workspace files (Docs, Sheets, Slides) have no fixed byte content, so Drive never returns `md5Checksum` for them — `use_checksum=true` must fall back to the existing mtime comparison for these exactly as if the flag were `false`, not error or misbehave.

**Prompt**
> "Sync {FOLDER_ID} with `/tmp/qa-239/` using direction='bidirectional', export_format='pdf', and use_checksum=true" *(against the existing {DOC_ID}-style Workspace fixture content already covered by TC-D201/TC-D218)*

**Checks**
- Call `sync_folder(folder_id="{FOLDER_ID}", local_path="/tmp/qa-239/", direction="bidirectional", export_format="pdf", use_checksum=true)`
- No exception; result shape matches an equivalent `use_checksum=false` call against the same fixture (same file(s) in `downloaded`/`skipped`)

**Teardown**
Remove `/tmp/qa-239/`.

**Result (2026-07-31) ✅ PASS** — no exception; result shape (13 downloaded, 9 pre-existing-duplicate-name `failed` entries from unrelated fixture pollution, `size_bytes: 1768790`) was byte-for-byte identical between the `use_checksum=true` call and a control `use_checksum=false` call against a fresh empty dir.

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

## `transfer_ownership`

> ⚠️ **Fixture requirement:** TC-D233 requires `TEST_PERMISSION_EMAIL` in `.env` to be a **real Google account** you control, and that ownership can be transferred back afterward (via the Drive UI, logged in as that second account) to restore the fixture — Drive has no API path to reclaim ownership once transferred. Use a disposable file, not {SPREADSHEET_ID} itself.

### TC-D233: Transfer ownership to another user ⚠️ destructive ⚠️ requires-oauth

**Setup:** `create_spreadsheet(title="TransferOwnershipQA")` — a disposable file so ownership loss doesn't disrupt other fixtures.

**Prompt**
> "Transfer ownership of {file_id} to {TEST_PERMISSION_EMAIL}"

**Checks**
- Response: `{"fileId": ..., "new_owner": "{TEST_PERMISSION_EMAIL}", "permissionId": ...}`
- `list_permissions` on the file shows `{TEST_PERMISSION_EMAIL}` with `role: "owner"`; the original account's own permission is demoted (typically to `writer`)

**Cleanup:** Log in as `{TEST_PERMISSION_EMAIL}` and transfer ownership back via the Drive UI, or delete the file from that account.

**Result (2026-07-27) ⏭️ SKIP — environmental**
`docs/qa/.env` doesn't exist in this scoped role-worktree pass (a known gap — see `docs/qa/run.md`), so `TEST_PERMISSION_EMAIL` isn't available. Skipped rather than risk an irreversible transfer with a placeholder address, since this is the one case here with no API path to undo a mistake. Needs a full conductor-prompt run with real fixtures.

---

### TC-D234: Service account cannot transfer ownership

**Prompt** (run against the `mcp-gee-sweet-sa` server, per `create_spreadsheet`'s TC-D04 convention for auth-method-dependent behavior)
> "Transfer ownership of {SPREADSHEET_ID} to {TEST_PERMISSION_EMAIL}"

**Checks**
- Call fails with a Drive API permission/consent error — not a silent success or unhandled crash
- 🔍 **Known limitation:** service accounts have no personal Drive identity to own files; this documents the failure mode the tool's docstring OAuth requirement refers to

**Result (2026-07-27) ⏭️ SKIP — environmental**
The `mcp-gee-sweet-sa` server available in this role worktree is a separate long-running process not tracking this PR's branch — `transfer_ownership` isn't registered on it even after `/mcp reconnect`, so the tool doesn't exist to call yet on that connection. Not a product defect; needs re-running once this PR's code reaches wherever that server's process is pointed (e.g. post-merge).

---

### TC-D235: Non-existent file ID

**Prompt**
> "Transfer ownership of file 'fakefileid999' to {TEST_PERMISSION_EMAIL}"

**Checks**
- Drive API error propagates — not a silent success

**Result (2026-07-27) ✅ PASS**
`transfer_ownership(file_id="fakefileid999", new_owner_email="qa-nonexistent-placeholder@example.com")` → `HttpError 404: "File not found: fakefileid999."` propagates as a tool error, not a silent success. Non-destructive, no fixture needed.

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
