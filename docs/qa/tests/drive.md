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
