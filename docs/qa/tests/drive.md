# Drive Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}`, `{DOC_ID}`, and `{FOLDER_ID}` from `fixtures.local.md`.

---

## `create_spreadsheet`

### TC-D01: Create in default folder

**Prompt**
> "Create a new spreadsheet called 'QA-Create-Test' in my default folder"

**Checks**
- Spreadsheet created with title 'QA-Create-Test'
- Response includes spreadsheet ID and a web link
- `drive_folder_cache.mark_dirty` called — next `list_files` for that folder re-fetches

---

### TC-D02: Create with explicit folder ID

**Prompt**
> "Create a new spreadsheet called 'QA-Create-Explicit' in folder {FOLDER_ID}"

**Checks**
- Spreadsheet appears in the specified folder
- Response includes the correct folder reference

---

### TC-D03: Create without a folder (root of Drive)

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

### TC-D05: Drive folder cache invalidated

**Prompt**
> "Create a spreadsheet called 'QA-Cache-Check' in {FOLDER_ID}, then list the files in that folder"

**Checks**
- `list_files` includes 'QA-Cache-Check'
- Confirms `drive_folder_cache.mark_dirty` fired after creation

---

### TC-D06: Resulting spreadsheet has expected title

**Prompt**
> "Create a spreadsheet called 'Exact Title Test' and confirm the title in the response"

**Checks**
- Response title is exactly 'Exact Title Test' — no truncation or modification

---

## `create_doc`

### TC-D07: Create with no content

**Prompt**
> "Create a Google Doc called 'QA-Empty-Doc' with no content"

**Checks**
- Doc created successfully
- No `batchUpdate` call made (no content to write)
- Response includes doc ID and web link

---

### TC-D08: Create with HTML content — formatting preserved

**Prompt**
> "Create a Google Doc called 'QA-Formatted-Doc' with this content: `<h1>Main Title</h1><p>A paragraph.</p><ul><li>Item A</li><li>Item B</li></ul>`"

**Checks**
- Doc created with correct title
- Open the doc in a browser: heading renders as H1, bullets render as a list
- Confirms the `create_doc` bug fix: uses `_html_to_doc_requests`, not `_html_to_text`

---

### TC-D09: Create with a link

**Prompt**
> "Create a Google Doc called 'QA-Link-Doc' with content: `<p>Visit <a href=\"https://example.com\">Example</a></p>`"

**Checks**
- Doc created
- Open in browser: "Example" is a clickable link to https://example.com

---

### TC-D10: Content with no block-level elements — batchUpdate skipped

**Prompt**
> "Create a Google Doc called 'QA-Inline-Doc' with content: `<span>just a span</span>`"

**Checks**
- Doc created without error
- No `batchUpdate` call (inline-only HTML produces no requests)
- Doc body is empty (span is not a block element)

---

### TC-D11: Drive folder cache invalidated

**Prompt**
> "Create a doc called 'QA-DocCache' in {FOLDER_ID}, then list the files in that folder"

**Checks**
- `list_files` includes 'QA-DocCache'
- Confirms `drive_folder_cache.mark_dirty` fires after doc creation

---

### TC-D12: Long content

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

### TC-D43: Cache invalidated after create

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

### TC-D50: Write to an empty doc

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

---

### TC-D57: Cache invalidated after write

**Prompt**
> "Write `<p>CacheTest</p>` to {DOC_ID}, then immediately get the doc content"

**Checks**
- `get_doc_content` returns 'CacheTest' — not the old cached version
- Confirms `doc_cache.mark_dirty` fires after write

---

## `create_folder`

### TC-D58: Create in default folder

**Prompt**
> "Create a new folder called 'QA-Folder-Test' in my default folder"

**Checks**
- Response includes a `folderId` and `name: 'QA-Folder-Test'`
- `parent` matches `{FOLDER_ID}`
- Folder visible in Drive

---

### TC-D59: Create at root (no parent)

**Prompt**
> "Create a folder called 'QA-Folder-Root' with no parent folder specified"

**Checks**
- Folder created without error
- `parent` is `root` or omitted
- 🔍 **Note:** service account may not have access to personal Drive root — record error if seen

---

### TC-D60: Cache invalidated after create

**Prompt**
> "Create a folder called 'QA-Folder-Cache' in {FOLDER_ID}, then list files in that folder"

**Checks**
- `list_files` result includes 'QA-Folder-Cache' with `mimeType: application/vnd.google-apps.folder`
- Confirms `drive_folder_cache.mark_dirty` fired for the parent

---

## `move_file`

### TC-D61: Move a file to another folder ⚠️ destructive

**Prompt**
> "Move the file {SPREADSHEET_ID} to folder {FOLDER_ID}"

**Checks**
- Response includes `fileId`, `name`, and updated `parent` matching `{FOLDER_ID}`
- File no longer appears in its previous folder (list to verify)
- Both old and new parent caches invalidated — subsequent `list_files` reflects the change

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

### TC-D64: Rename a file ⚠️ destructive

**Prompt**
> "Rename the file 'QA-Create-Test' (from TC-D01) to 'QA-Renamed-File' — use its spreadsheet ID"

**Checks**
- Response `name` is 'QA-Renamed-File'
- File appears with new name in Drive
- Parent folder cache invalidated — `list_files` reflects the new name

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

### TC-D67: Copy with auto-assigned name

**Prompt**
> "Copy the spreadsheet {SPREADSHEET_ID} without specifying a new name"

**Checks**
- New file created with name like 'Copy of <original>'
- Response includes a new `fileId` different from `{SPREADSHEET_ID}`
- `web_link` is present and different from the original

---

### TC-D68: Copy with explicit name and destination folder

**Prompt**
> "Copy {SPREADSHEET_ID} into {FOLDER_ID} and name the copy 'QA-Copy-Explicit'"

**Checks**
- New file named 'QA-Copy-Explicit' appears in `{FOLDER_ID}`
- Destination folder cache invalidated — `list_files` includes the copy
- Original `{SPREADSHEET_ID}` is unchanged

---

### TC-D69: Copy a Google Doc

**Prompt**
> "Copy {DOC_ID} and name it 'QA-Doc-Copy'"

**Checks**
- New doc created independently of the original
- `mimeType` is `application/vnd.google-apps.document`
- Edits to the copy do not affect the original

---

### TC-D70: Attempt to copy a folder

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

### TC-D72: Permanently delete a file ⚠️ destructive

**Prompt**
> "Permanently delete the file 'QA-Copy-Explicit' from TC-D68 — use permanent=True"

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

### TC-D88: Upload plain text file

**Prompt**
> "Upload a plain text file called 'qa-upload.txt' to {FOLDER_ID} with content 'Hello from QA'"

**Checks**
- File appears in `{FOLDER_ID}` with `mimeType: text/plain`
- `name` is 'qa-upload.txt'
- Folder cache invalidated — `list_files` shows the new file

---

### TC-D89: Upload Markdown as raw file (no conversion)

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

### TC-D91: Upload HTML and convert to Google Doc

**Prompt**
> "Upload this HTML to {FOLDER_ID} as a Google Doc called 'QA-HTML-Doc': `<h1>HTML Title</h1><p>A paragraph.</p><ul><li>X</li><li>Y</li></ul>`"

**Checks**
- Google Doc created with formatted content
- Heading and list visible in browser
- `source_format` was `html`, `convert_to_doc` was `True`

---

### TC-D92: Upload Markdown with table

**Prompt**
> "Upload this markdown as a Google Doc called 'QA-Table-Doc' to {FOLDER_ID}: `# Table Test\n\n| Col A | Col B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |`"

**Checks**
- Google Doc created
- Open in browser: a 2×2 table is visible under the heading
- Confirms `markdown[extra]` extension handles GFM tables
