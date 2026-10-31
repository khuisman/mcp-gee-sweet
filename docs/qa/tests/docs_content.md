# Docs Tools — Content (Create/Read/Write, Markdown/HTML Conversion) — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs/content.py`, plus four submodules bundled here rather than split into their own files (this file is the catch-all for everything issue #233's split didn't carve out a dedicated file for): `editing.py` (`insert_doc_text`, `delete_doc_range`, `insert_page_break`, `insert_softbreak_paragraph`), `images.py` (`insert_inline_image`, `insert_local_images`), `comments.py` (`list_doc_comments`, `add_doc_comment`, `resolve_doc_comment`), `named_ranges.py` (`create_named_range`, `create_bookmark`) — plus the markdown/HTML conversion pipeline these tools drive: `ast.py`, `html_parser.py`, `emitter.py`, `anchors.py`, `indices.py`.

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` (and, for `insert_local_images`, `{FOLDER_ID}`) from `fixtures.local.md`.

These tools operate on document body indices. Use `get_doc_structure` first in any session to obtain current indices before calling insert/delete/style operations.

---

## `create_doc`

### TC-D07: Create with no content ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Empty-Doc' with no content"

**Checks**
- Doc created successfully
- No `batchUpdate` call made (no content to write)
- Response includes doc ID and web link

**Result (2026-09-04) ✅ PASS**
QA-Empty-Doc created (docId 10XUmZffu...), no content, no error. Trashed.

**Result (2026-09-20) ✅ PASS — regression spot-check, PR #777 (issue #544)** Verified via `mcp-gee-sweet-sky`. PR #777 replaces `create_doc`'s and `create_doc_from_file`'s hardcoded `"application/vnd.google-apps.document"` literal with the shared `_GOOGLE_DOC_MIME` constant (finishing the sweep started for `upload_file`/`_CONVERT_MIME` under #412). Created `QA-scratch-TC544-create_doc-mime-check` and `QA-scratch-TC544-create_doc_from_file-mime-check`; `get_file_metadata` confirmed `mimeType: application/vnd.google-apps.document` for both. Consistent with `/code-review high`'s finding of zero functional changes (the two literals and the constant are byte-identical) and the full unit suite (1524 passed, 3 skipped). Both trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc "QA-Empty-Doc" (run folder) returned docId+web_link; structure shows only sectionBreak plus an empty paragraph, so nothing was written. Trashed.

---

### TC-D08: Create with HTML content — formatting preserved ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Formatted-Doc' with this content: `<h1>Main Title</h1><p>A paragraph.</p><ul><li>Item A</li><li>Item B</li></ul>`"

**Checks**
- Doc created with correct title
- Open the doc in a browser: heading renders as H1, bullets render as a list
- Confirms the `create_doc` bug fix: uses `_html_to_doc_requests`, not `_html_to_text`

**Result (2026-09-04) ✅ PASS**
HTML converted correctly: HEADING_1 "Main Title", paragraph "A paragraph.", bullets "Item A"/"Item B" as list items (get_doc_structure confirmed). Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc with the h1/p/ul HTML: HEADING_1 "Main Title", NORMAL_TEXT "A paragraph.", "Item A"/"Item B" as bullets sharing one listId. Trashed.

---

### TC-D09: Create with a link ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Link-Doc' with content: `<p>Visit <a href=\"https://example.com\">Example</a></p>`"

**Checks**
- Doc created
- Open in browser: "Example" is a clickable link to https://example.com

**Result (2026-09-04) ✅ PASS**
"Example" run has link_url=https://example.com, underline styling. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc with the link HTML: the "Example" run has link_url=https://example.com and is underlined. Trashed.

---

### TC-D10: Content with no block-level elements — batchUpdate skipped ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Inline-Doc' with content: `<span>just a span</span>`"

**Checks**
- Doc created without error
- No `batchUpdate` call (inline-only HTML produces no requests)
- Doc body is empty (span is not a block element)

**Result (2026-09-04) ✅ PASS**
Body empty (only terminal blank paragraph) — inline-only span produced no content. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc with `<span>just a span</span>`: no error; body has only the terminal empty paragraph. Trashed.

---

### TC-D11: Drive folder cache invalidated ⚠️ requires-oauth
**Prompt**
> "Create a doc called 'QA-DocCache' in {FOLDER_ID}, then list the files in that folder"

**Checks**
- `list_files` includes 'QA-DocCache'
- Confirms `drive_folder_cache.mark_dirty` fires after doc creation

**Result (2026-09-04) ✅ PASS**
list_files(FOLDER_ID) included QA-DocCache after create. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Listed the run folder (primes the cache), then create_doc "QA-DocCache" in it, then list_files: QA-DocCache is present. Trashed.

---

### TC-D12: Long content ⚠️ requires-oauth
**Prompt**
> "Create a Google Doc called 'QA-Long-Doc' with a very long paragraph — repeat the word 'test ' 500 times as the body content"

**Checks**
- Doc created without error
- Content visible in the doc
- Note any API size limit errors

**Result (2026-09-04) ✅ PASS**
500x "test " paragraph created without error, content visible (endIndex 2412), no size-limit error. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc with one paragraph of about 490 hand-typed "test " repeats (not exactly 500): no error, no size-limit error, paragraph 1–2462. Trashed.

---

## `get_doc_content`

### TC-D44: Happy path

**Prompt**
> "Get the content of doc {DOC_ID}"

**Checks**
- Returns text content with the expected HTML: heading, paragraph, list items
- Response includes metadata (title, web link)
- No `error` field

**Result (2026-09-04) ✅ PASS**
get_doc_content returned text content: "Test Document", paragraph, "* Item one"/"* Item two", metadata (name, modified_time, web_link), no error.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: get_doc_content(copy) returned "Test Document / This document is used… / * Item one / * Item two" plus name, modified_time and web_link. No error.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-sa`: `get_doc_content(TEST_DOC_ID)` returned "Test Document" (heading), the paragraph, and "* Item one"/"* Item two". Metadata included name, modified_time and web_link. No error.

**Result (2026-10-20) ✅ PASS — v0.9.3 post-advisory re-check @ c90b88d3**
`kai-sa` (service account) and `kai-oauth` (OAuth): fixture doc content returned with name, modified_time, web_link; no error.

---

### TC-D45: Cache hit on second call

**Prompt** (run twice)
> "Get the content of doc {DOC_ID} again"

**Checks**
- Second call returns same content
- Logs show `cache hit`

**Result (2026-09-04) ✅ PASS**
Second call returned identical content to TC-D44 (cache-hit content match; log-level cache-hit confirmation not directly observable via MCP tool response).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`kai-oauth`: The second get_doc_content returned identical content. Not run: the "logs show cache hit" check, because the rules forbid reading server logs.

**Result (2026-10-20) ✅ PASS — v0.9.3 post-advisory re-check @ c90b88d3**
`kai-oauth` (OAuth): `Cached doc …` (1.3 s), then `Doc cache hit: …` (0.28 s), same content.

---

### TC-D46: Non-Google-Doc file ID

**Prompt**
> "Get the content of {SPREADSHEET_ID} using get_doc_content"

**Checks**
- Drive export API returns an error (spreadsheets can't be exported as plain text this way)
- Error propagates cleanly — not a server crash

**Result (2026-09-04) ✅ PASS**
get_doc_content against SPREADSHEET_ID returned clean HttpError 400 "The requested conversion is not supported." — propagated as tool error, not a crash.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: get_doc_content(TEST_SPREADSHEET_ID) raised a clean HttpError 400 "The requested conversion is not supported." No crash.

---

### TC-D47: Non-existent file ID

**Prompt**
> "Get the content of doc 'invalidid123xyz'"

**Checks**
- Returns a clear API error
- Not a silent empty response

**Result (2026-09-04) ✅ PASS**
get_doc_content('invalidid123xyz') returned clean HttpError 404 "File not found: invalidid123xyz." — not silent empty.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: get_doc_content('invalidid123xyz') raised a clean HttpError 404 "File not found: invalidid123xyz."

---

### TC-D48: Large document

**Prompt**
> "Get the content of a large Google Doc — if you have one, use its ID"

**Checks**
- Content returned without timeout or truncation
- Note any response size limits observed

**Result (2026-09-04) ✅ PASS**
get_doc_content on TEST_LARGE_DOC_ID (mcp-gee-sweet-qa-large-doc, ~53.6KB content) returned without truncation or timeout — well under current MAX_TOOL_RESPONSE_CHARS default (1,000,000, raised by #519). No response-size limit hit at this fixture size.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: get_doc_content(TEST_LARGE_DOC_ID) inline returned the full ~54.9k-char response, untruncated (ends with the closing quote and brace). The local_path variant wrote 54891 bytes. No cap hit.

---

### TC-D49: Content decode branch

**Prompt**
> "Get the content of {DOC_ID} and tell me if the content came back as bytes or a string"

**Checks**
- Content decoded correctly regardless of whether the API returns bytes or string
- 🔍 **Implementation note:** `content.decode("utf-8")` vs already-string branch in `drive.py`

**Result (2026-09-04) ✅ PASS**
Content decoded as plain string (not bytes) — matches TC-D44's content, no decode artifacts.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Content came back as a decoded string with a BOM prefix and no byte or decode artifacts.

---

### TC-DOC80: get_doc_content trips the response-size cap; cached path re-checks it too (issue #242) ⚠️ low-cap override required

**Background:** #242 generalized #235's response-size safety net to `get_doc_content`. `doc_cache` previously returned a cached result *before* any cap check ran, so a cached oversized doc would bypass the cap on repeat calls — fixed so the check runs on both the cache-hit and cache-miss paths.

**Run method (issue #678):** `MAX_TOOL_RESPONSE_CHARS` is read once at `tools/response_limits.py` import, and #519 raised its default from 40000 to 1,000,000. The `TEST_LARGE_DOC_ID` fixture (~54k chars, sized for TC-D48) is far under that default, so it cannot trip the cap on a normally-started server. This case is therefore **not** run through the shared shard server — instead run it against the low cap, one of:
- a purpose-started server with `MAX_TOOL_RESPONSE_CHARS=40000` in its env, or
- a direct script invocation: `MAX_TOOL_RESPONSE_CHARS=40000 uv run python3 -c "..."` from the repo root, calling the real `get_doc_content` tool function (import from `mcp_gee_sweet.tools.docs`) against `TEST_LARGE_DOC_ID` with a real OAuth `docs`/`drive` service (`mcp_gee_sweet.auth._oauth_creds()` + `googleapiclient.discovery.build`). This exercises the real code path and the real Docs API — record the Result as a live verification, noting it was script-driven rather than through the MCP tool wrapper.

**Setup:** `TEST_LARGE_DOC_ID` (`mcp-gee-sweet-qa-large-doc`). Measure its current serialized `get_doc_content` size at run time and put the number in the Result — it just needs to exceed 40000, which it comfortably does at ~54k.

**Checks**
- First call (fetch path), cap = 40000: raises `ValueError` naming the actual response size, the `40000`-character cap, and `MAX_TOOL_RESPONSE_CHARS`
- Second call (cache-hit path, no `refresh_cache` in between): raises the *same* error — proves the cache-hit path re-checks the cap rather than returning the stale oversized cached result
- Same call with `local_path` set: succeeds, returns `{local_path, id, bytes_written}`, and the file on disk contains the full content

**Result (2026-07-03) ✅ PASS — superseded, needs re-run under the #678 method.** _Prior run, against the then-default 40000 cap with a ~49,700-char fixture:_ Fetch-path call raised `get_doc_content: the response is 49700 characters, over the 40000-character safety cap. …`; repeat call served from `doc_cache` (no extra Drive round-trip) raised the identical error; `local_path` call succeeded (`bytes_written: 49700`), file verified then cleaned up. Not valid for v0.9.0 — the cap default and fixture size both changed since; re-run per the Run method above.

**Result (2026-09-04) ✅ PASS**
Script-driven at MAX_TOOL_RESPONSE_CHARS=40000 (repo-root uv run python3, real OAuth creds): fetch-path raises ValueError naming 54891 chars/40000 cap/MAX_TOOL_RESPONSE_CHARS; cache-hit path (real DocContentCache store+get round-trip, content byte-identical) still raises — confirms #242 cache-ordering fix; local_path via real write_capped_result_to_disk returns {local_path,bytes_written:54891,id}, on-disk content matches exactly. Supersedes the 2026-07-03 result (old 40000 default, ~49,700-char fixture) — see #678.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Low-cap script needs a usable OAuth token (aziz token fails to refresh; copying another was classifier-denied).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`kai-oauth`: Needs the low-cap (MAX_TOOL_RESPONSE_CHARS=40000) scratch script with the fixture-owning account's token, which isn't available in this pass. Measured the current size: 54891 chars via local_path.

---

## `write_doc_content`

### TC-D50: Write to an empty doc ⚠️ requires-oauth
**Prompt**
> "Create a new empty doc called 'QA-WriteEmpty', then write this content to it: `<h1>Hello</h1><p>World</p>`"

**Checks**
- Doc content replaced with heading and paragraph
- `end_index=2` path taken (doc was empty — no delete step needed)
- Open in browser to verify formatting

**Result (2026-09-04) ✅ PASS**
Created QA-WriteEmpty, wrote <h1>Hello</h1><p>World</p>. get_doc_structure: HEADING_1 "Hello" then paragraph "World". Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Created QA-WriteEmpty, then wrote `<h1>Hello</h1><p>World</p>`: HEADING_1 "Hello", NORMAL_TEXT "World". The end_index=2 path is inferred from the empty doc, not observable. Trashed.

---

### TC-D51: Write to a doc with existing content ⚠️ destructive

**Prompt**
> "Overwrite the content of {DOC_ID} with: `<h2>Replaced</h2><p>New content only.</p>`"

**Checks**
- Previous content cleared
- New heading and paragraph visible in the doc
- `doc_cache.mark_dirty` called — next `get_doc_content` re-fetches

**Result (2026-09-04) ✅ PASS**
Overwrote DOC_ID with <h2>Replaced</h2><p>New content only.</p>. get_doc_structure confirmed prior content cleared, HEADING_2 "Replaced" + paragraph "New content only." present.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Overwrote the copy: the prior content is gone; HEADING_2 "Replaced" + "New content only."; the next get_doc_content returned the new text (cache refreshed).

---

### TC-D52: HTML with headings and bullets

**Prompt**
> "Write this HTML to {DOC_ID}: `<h1>Title</h1><h2>Subtitle</h2><ul><li>A</li><li>B</li></ul><p>Footer</p>`"

**Checks**
- H1 renders as Heading 1, H2 as Heading 2
- A and B render as bullet list items
- Footer renders as normal paragraph

**Result (2026-09-04) ✅ PASS**
Wrote <h1>Title</h1><h2>Subtitle</h2><ul><li>A</li><li>B</li></ul><p>Footer</p>. Confirmed HEADING_1/HEADING_2/bullets A,B (shared listId)/paragraph Footer.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: HEADING_1 "Title", HEADING_2 "Subtitle", A/B bullets on one listId, NORMAL_TEXT "Footer".

---

### TC-D53: HTML with a link

**Prompt**
> "Write this to {DOC_ID}: `<p>Click <a href=\"https://example.com\">here</a> for more</p>`"

**Checks**
- "here" is a clickable hyperlink to https://example.com
- Surrounding text renders as normal paragraph

> **Note:** `write_doc_content` replaces the full document content, so this test is self-contained regardless of run order.

**Result (2026-09-04) ✅ PASS**
Wrote link HTML. "here" run has link_url=https://example.com, surrounding text plain.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: The "here" run has link_url=https://example.com (underlined); "Click " and " for more" are plain.

---

### TC-D54: HTML with no recognizable tags

**Prompt**
> "Write `<span>no blocks here</span>` to {DOC_ID}"

**Checks**
- Existing content cleared (delete step runs)
- Nothing inserted (span produces no block-level requests)
- Doc body is empty

**Result (2026-09-04) ✅ PASS**
Wrote <span>no blocks here</span>. Existing content cleared, body empty (only terminal blank paragraph) — span produced no block requests.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Wrote `<span>no blocks here</span>`: prior content cleared, body only the terminal empty paragraph.

---

### TC-D55: Empty string content

**Prompt**
> "Write an empty string to {DOC_ID}"

**Checks**
- Existing content cleared
- Nothing inserted
- Doc body is empty

**Result (2026-09-04) ✅ PASS**
Wrote empty string. Existing content cleared, body empty.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Wrote "Pre-D55 content", then an empty string: cleared, body only sectionBreak + empty paragraph.

---

### TC-D56: Very long content

**Prompt**
> "Write a very long document to {DOC_ID} — use 100 paragraphs each with 50 words of placeholder text"

**Checks**
- Writes successfully or returns a clear API size limit error (~2MB per batchUpdate request)
- Note any limit encountered

> **Note:** Content is generated inline by the conductor — no fixture file needed.

**Result (2026-09-04) ✅ PASS**
Wrote 100 paragraphs x 50 "words" each (~11KB). Write succeeded without error, well under 2MB batchUpdate limit.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Wrote 100 `<p>` paragraphs of 50+ words each (~30KB of HTML): no error. Read-back has 100 paragraphs, p01…p100, 32357 bytes. No limit hit.

---

### TC-D57: Cache invalidated after write

**Prompt**
> "Write `<p>CacheTest</p>` to {DOC_ID}, then immediately get the doc content"

**Checks**
- `get_doc_content` returns 'CacheTest' — not the old cached version
- Confirms `doc_cache.mark_dirty` fires after write

**Result (2026-09-04) ✅ PASS**
Wrote <p>CacheTest</p>, immediately get_doc_content returned "CacheTest" — not stale cache, confirms mark_dirty fires after write.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Wrote `<p>CacheTest</p>`, then get_doc_content immediately returned "CacheTest", not the previous long content.

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

**Result (2026-09-04) ✅ PASS**
2x2 real Docs table (not flattened), header "Name"/"Value", data "Alpha"/"1".

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Real 2×2 table (not flattened): Name/Value, Alpha/1. Browser view of the identical HTML is in the TC-DOC32 screenshot.

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

**Result (2026-09-04) ✅ PASS**
HEADING_1 "Batch Comparison", paragraph "See the table below.", 3x2 table after paragraph, cells correct (Original/Double/2 cups flour/4 cups flour/1 egg/2 eggs).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: HEADING_1 "Batch Comparison", the paragraph, then a 3×2 table after it: Original/Double, 2 cups flour/4 cups flour, 1 egg/2 eggs.

---

### TC-D142: Table with empty cells
**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><td>A</td><td></td></tr><tr><td></td><td>D</td></tr></table>`"

**Checks**
- 2×2 table created
- Cell (0,0) = "A", cell (0,1) = empty, cell (1,0) = empty, cell (1,1) = "D"
- Empty cells don't cause an error — `insertText` is simply skipped for them

**Result (2026-09-04) ✅ PASS**
2x2 table, cell(0,0)="A", (0,1)="", (1,0)="", (1,1)="D" — empty cells no error.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: 2×2 table: (0,0)="A", (0,1)="", (1,0)="", (1,1)="D". No error.

---

### TC-D143: Table-only HTML (no paragraphs)
**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><td>X</td><td>Y</td></tr></table>`"

**Checks**
- A 1-row × 2-column table is created
- Cells contain "X" and "Y"
- No paragraph text before the table
- Confirms the early-return guard correctly handles tables-only input

**Result (2026-09-04) ✅ PASS**
1x2 table only (X/Y), no paragraph text before table (only structural blank paragraph). Early-return guard confirmed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: 1×2 table X/Y. Only the structural 1pt blank paragraph precedes it; no text paragraph.

---

### TC-D144: Multiple tables in one write
**Prompt**
> "Write this HTML to {DOC_ID}: `<p>First table:</p><table><tr><td>A</td><td>B</td></tr></table><p>Second table:</p><table><tr><td>C</td><td>D</td></tr></table>`"

**Checks**
- Both tables are created in the document
- First table has cells "A" and "B"; second has "C" and "D"
- "First table:" and "Second table:" paragraphs appear before both tables
- No index corruption or API error between the two table insertions

**Result (2026-09-04) ✅ PASS**
Both tables created correctly (A/B then C/D), "First table:"/"Second table:" paragraphs before each, no index corruption.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: "First table:" → A/B table, then "Second table:" → C/D table. Indices consistent, no API error.

---

### TC-D145: HTML with `<th>` header cells treated as data
**Prompt**
> "Write this HTML to {DOC_ID}: `<table><tr><th>Col1</th><th>Col2</th></tr><tr><td>Val1</td><td>Val2</td></tr></table>`"

**Checks**
- `<th>` cells are included in the table (not ignored)
- First row contains "Col1" and "Col2", second row contains "Val1" and "Val2"
- Both rows are ordinary table cells (Docs has no header-cell type). The `<th>` cells' runs are bold (`bold: true`); the `<td>` cells' runs are not. TC-DOC32 covers the bold styling in detail.

**Result (2026-09-04) ✅ PASS**
<th> cells included as normal cells: row0 Col1/Col2, row1 Val1/Val2.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
th cells included; "Docs doesn't distinguish th/td" is stale (th now exports bold).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: th cells included: row0 Col1/Col2, row1 Val1/Val2. The check's "Docs doesn't distinguish th/td" is stale wording: th now renders bold (see TC-DOC32). Not a defect.

---

## `get_doc_structure`

### TC-DOC01: Structure of a non-empty doc
**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns `docId`, `title`, and `elements` list
- Each element has `type`, `startIndex`, `endIndex`
- Paragraphs include `namedStyleType`, `text`, and `runs`
- First element is a `sectionBreak` at index 0
- Last element is a paragraph ending at the document's total length

**Result (2026-06-20) ✅ PASS**
- Returned `docId`, `title`, `elements` list. sectionBreak at index 0. Paragraphs include `namedStyleType`, `text`, `runs`. Final paragraph ends at document total length.

**Result (2026-09-04) ✅ PASS**
Confirmed throughout session: docId/title/elements present, sectionBreak at index 0, paragraphs include namedStyleType/text/runs, final paragraph ends at doc total length.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Structure has docId/title/elements; sectionBreak at 0; paragraphs carry namedStyleType/text/runs; the last paragraph ends at 89 = doc length.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-sa`: `get_doc_structure(TEST_DOC_ID)` returned docId, title and elements. Index 0 is a sectionBreak. Paragraphs carry namedStyleType, text and runs. The last paragraph is [88,89].

**Result (2026-10-20) ✅ PASS — v0.9.3 post-advisory re-check @ c90b88d3**
`kai-sa` (service account) and `kai-oauth` (OAuth): docId, title, elements; sectionBreak 0–1; headingId and bullet `{listId, nestingLevel 0}` present; last paragraph ends at 89.

---

### TC-DOC02: Paragraph runs include style data
**Setup:** `{DOC_ID}` must contain at least one bold or italic run (use `write_doc_content` with `<b>` or `<i>` to set up)

**Prompt**
> "Get the structure of doc {DOC_ID} and show me the formatting on each run"

**Checks**
- Runs with bold styling return `bold: true`
- Runs without explicit style return `bold: null` (not `false`) — null means inherited
- `link_url` is populated for runs inside `<a>` tags

**Result (2026-06-20) ✅ PASS**
- Wrote `<b>bold</b> and <i>italic</i> and <a href="...">a link</a>`. "Bold text" run: `bold: true`. Plain text runs: `bold: null` (not false). Link run: `link_url: "https://example.com"`. Null semantics confirmed.

**Result (2026-09-04) ✅ PASS**
Wrote <b>bold text</b> and <i>italic text</i> and <a>a link</a>. "bold text" run bold:true, "italic text" italic:true, plain-text runs bold:null (not false), link run link_url="https://example.com".

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: "bold text" bold:true; "italic text" italic:true; plain runs bold:null (not false); "a link" link_url=https://example.com.

---

### TC-DOC03: Structure of a doc containing a table
**Setup:** `{DOC_ID}` must contain a table

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Table element has `type: "table"`, `rows`, `columns`
- `cells` list contains one entry per cell with `row`, `col`, `startIndex`, `endIndex`, `paragraphStartIndex`
- `paragraphStartIndex` is one greater than cell `startIndex` (empty cell: paragraph is the only content)
- Cell text is populated correctly for non-empty cells

**Result (2026-06-20) ✅ PASS**
- Inserted a 2×2 table; `get_doc_structure` returned `type: "table"`, `rows: 2`, `columns: 2`, 4 cells. Each cell: `paragraphStartIndex = startIndex + 1`. Cell `text: ""` for all empty cells.

**Result (2026-09-04) ✅ PASS**
Confirmed via TC-D140/142/145 table writes: type:"table", rows/columns, cells list with row/col/startIndex/endIndex/paragraphStartIndex; empty cell paragraphStartIndex = startIndex+1 (e.g. D142 cell (0,1): startIndex 7, paragraphStartIndex 8).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: From the D142 table: type "table", rows/columns, cells carry row/col/startIndex/endIndex/paragraphStartIndex; empty cell (0,1) has startIndex 7 and paragraphStartIndex 8.

---

### TC-DOC04: Structure of an empty doc
**Setup:** doc with only the default empty paragraph

**Prompt**
> "Get the structure of doc {DOC_ID}"

**Checks**
- Returns elements with at least the sectionBreak and one empty paragraph
- No error

**Result (2026-06-20) ✅ PASS**
- Wrote `<p></p>`. Structure: sectionBreak at 0–1, one empty paragraph at 1–2. No error.

**Result (2026-09-04) ✅ PASS**
Confirmed via TC-D55 (empty string write): sectionBreak + one empty paragraph, no error.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: From the D55 empty doc: sectionBreak 0–1 plus one empty paragraph 1–2. No error.

---

### TC-DOC05: Invalid doc ID returns error
**Prompt**
> "Get the structure of doc not-a-real-id"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references the invalid ID or a 404

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "<HttpError 404 ... Requested entity was not found.>"}`. No exception raised.

**Result (2026-09-04) ✅ PASS**
get_doc_structure('not-a-real-id') returned {"error": "<HttpError 404 ... Requested entity was not found.>"}. No exception raised.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: get_doc_structure('not-a-real-id') returned {"error": "<HttpError 404 … Requested entity was not found.>"}; no exception.

---

## `insert_doc_text`

### TC-DOC06: Insert a single paragraph ⚠️ destructive
**Setup:** fetch current structure; note the `endIndex` of the last non-final paragraph

**Prompt**
> "Insert the text 'Inserted line.\n' at index {N} in doc {DOC_ID}"

**Checks**
- Re-fetch structure shows new paragraph at the expected position
- Surrounding paragraphs shifted by the length of the inserted text
- `insertions: 1` in response

**Cleanup:** delete the inserted range after verifying

**Result (2026-06-20) ✅ PASS**
- Inserted "Inserted line.\n" at index 88. Re-fetch showed new paragraph at 88–103. "Item two\n" unchanged; final blank shifted to 103–104. `insertions: 1`.

**Result (2026-09-04) ✅ PASS**
Inserted "Inserted line.\n" at index 38. Re-fetch: new paragraph at 38-53, insertions:1.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Inserted "Inserted line.\n" at 15: new paragraph 15–30; following paragraphs shifted +15; insertions:1.

---

### TC-DOC07: Insert at multiple indices — high→low ordering verified ⚠️ destructive
**Setup:** fetch structure; identify two paragraphs P1 (earlier) and P2 (later) with known indices. Record P1's `startIndex` as N1 and P2's `startIndex` as N2 (N2 > N1). Both insertions are short fixed strings so index arithmetic is checkable.

**Prompt**
> "Insert 'AAA\n' at index {N1} and 'BBB\n' at index {N2} in doc {DOC_ID}"

**Checks**
- Re-fetch structure shows 'AAA' before P1 and 'BBB' before P2 (not shifted into wrong paragraphs)
- 'BBB' paragraph's `startIndex` = N2 + 4 (len('AAA\n') inserted before it)
- If tool processed low→high instead, 'BBB' would land 4 bytes early — use this arithmetic to confirm ordering
- `insertions: 2` in response

**Cleanup:** delete both inserted ranges

**Result (2026-06-20) ✅ PASS**
- N1=70 (Item one startIndex), N2=79 (Item two startIndex). After insert: "AAA\n" at 70–74 before Item one; "BBB\n" at 83–87 before Item two. BBB startIndex = N2+4 = 83 ✅. `insertions: 2`. High→low ordering confirmed.

**Result (2026-09-04) ✅ PASS**
Inserted 'AAA\n' at N1=1, 'BBB\n' at N2=38. Re-fetch: AAA before P1, BBB before P2 at startIndex 42 = N2+4. insertions:2. High->low ordering confirmed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: N1=30, N2=85: AAA at 30–34; BBB at 89–93 = N2+4 (before "Item one"); insertions:2. High-to-low order confirmed. Both cleaned up after.

---

### TC-DOC08: Empty insertions list returns error
**Prompt**
> "Call insert_doc_text on doc {DOC_ID} with an empty insertions list"

**Checks**
- Returns `{"error": "insertions list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "insertions list is empty"}`.

**Result (2026-09-04) ✅ PASS**
insert_doc_text with empty insertions list returned {"error":"insertions list is empty"}.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Empty insertions list returned {"error":"insertions list is empty"}.

---

## `delete_doc_range`

### TC-DOC09: Delete a paragraph ⚠️ destructive
**Setup:** insert a known paragraph first (TC-DOC06), note its `startIndex` and `endIndex`

**Prompt**
> "Delete the range from index {start} to {end} in doc {DOC_ID}"

**Checks**
- Re-fetch structure no longer contains the deleted paragraph
- Surrounding content shifted back correctly
- `deletions: 1` in response

**Result (2026-06-20) ✅ PASS**
- Inserted "Delete me.\n" at 88; deleted [88, 99]. Re-fetch confirmed paragraph absent; "Item two\n" back at 79–88; final blank at 88–89. `deletions: 1`.

**Result (2026-09-04) ✅ PASS**
Deleted [46,61) ("Inserted line." paragraph). Re-fetch: paragraph absent, BBB back at 42-46, final blank at 46-47. deletions:1.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Deleted [15,30) ("Inserted line."): paragraph gone; AAA back at 15–19; later content shifted back; deletions:1.

---

### TC-DOC10: Cannot delete final segment newline
**Setup:** fetch structure; note the final element's `endIndex`

**Prompt**
> "Delete the range from index 1 to {final_endIndex} in doc {DOC_ID}"

**Checks**
- Returns an API error about the segment newline
- 🔍 **Note:** correct usage is `endIndex - 1` for the final element

**Result (2026-06-20) ✅ PASS**
- Attempted delete [1, 89] (final_endIndex=89). API returned `{"error": "<HttpError 400 ... The range cannot include the newline character at the end of the segment.>"}`.

**Result (2026-09-04) ✅ PASS**
Attempted delete [1,47) (includes final segment newline). Returned HttpError 400 "The range cannot include the newline character at the end of the segment."

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Deleting [1,97) (final endIndex) returned HttpError 400 "The range cannot include the newline character at the end of the segment."

---

### TC-DOC11: Empty deletions list returns error
**Prompt**
> "Call delete_doc_range on doc {DOC_ID} with an empty deletions list"

**Checks**
- Returns `{"error": "deletions list is empty"}`

**Result (2026-06-20) ✅ PASS**
- Returned `{"error": "deletions list is empty"}`.

**Result (2026-09-04) ✅ PASS**
delete_doc_range with empty deletions list returned {"error":"deletions list is empty"}.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Empty deletions list returned {"error":"deletions list is empty"}.

---

## Multi-operation ordering and sequencing

### TC-DOC22: Multi-delete high→low ordering verified ⚠️ destructive
**Setup:** insert two known paragraphs ('DEL-A\n' and 'DEL-B\n') at known positions. Note their `startIndex`/`endIndex` after re-fetching. DEL-B has higher indices than DEL-A.

**Prompt**
> "Delete range {DEL-A start}–{DEL-A end} and range {DEL-B start}–{DEL-B end} from doc {DOC_ID} in one call"

**Checks**
- Both paragraphs absent from re-fetched structure
- Content that followed DEL-B is now at DEL-B's original startIndex (no offset error)
- If tool processed low→high, DEL-B's range would be stale after DEL-A shifts indices — verify neither deletion fails with an out-of-bounds error
- `deletions: 2` in response

**Result (2026-06-20) ✅ PASS**
- DEL-A at 79–85, DEL-B at 94–100. Deleted both in one call. Re-fetch: both absent; "Item two\n" back at 79–88 (DEL-B's original startIndex). No out-of-bounds error. `deletions: 2`.

**Result (2026-09-04) ✅ PASS**
Inserted DEL-A (5-11) and DEL-B (48-54), deleted both in one call. Re-fetch: both absent, BBB back at 42-46 (DEL-B's original startIndex). deletions:2, no out-of-bounds error.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Inserted DEL-A (19–25) and DEL-B (93–99), deleted both in one call: both gone; "Item two" back at 87 (its pre-insert start); no out-of-bounds error; deletions:2.

---

### TC-DOC26: Full end-to-end sequence — insert table then style cells ⚠️ destructive
**Purpose:** the complete `insert_doc_table` → `style_doc_table_cells` sequence was never run end-to-end in live testing. Covers both tools and the index handoff between them.

**Setup:** fetch structure; note a suitable insertion index N

**Prompt**
**Playwright: required**
> "Insert a 2×3 table at index {N} in doc {DOC_ID}, then style row 0 with grey background (red=0.85 green=0.85 blue=0.85) spanning all 3 columns, and add a solid black border (width 0.5) to every cell"

**Checks**
- `insert_doc_table` succeeds: `rows: 2`, `columns: 3`, 6 cells returned
- `style_doc_table_cells` for row 0 grey background succeeds (`requests: 1`)
- `style_doc_table_cells` for all 6 cells border succeeds (`requests: 6`)
- Re-fetch `get_doc_structure` shows the table at `tableStartIndex`
- 🔍 Visual check in Google Docs: styled header row and visible borders

**Cleanup:** delete table range

**Result (2026-06-20) ✅ PASS**
- Inserted 2×3 table at N=88. Row 0 grey background (column_span 3): `requests: 1`. All 6 cells border (black, 0.5pt): `requests: 6`. Re-fetch confirmed table at `tableStartIndex: 89`.

**Result (2026-09-04) ✅ PASS**
insert_doc_table(N=46,2x3): rows:2,columns:3,6 cells. style_doc_table_cells row0 grey bg (col_span 3): requests:1. All 6 cells border (black,0.5pt): requests:6. Re-fetch confirmed table at tableStartIndex 47. Playwright screenshot (docs/qa/screenshots/2026-09-04-tc-doc26.png) confirmed grey header row and visible black borders. Table deleted after.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: insert_doc_table(88, 2×3): rows 2, cols 3, 6 cells, tableStartIndex 89. Row-0 grey background (column_span 3) gave requests:1; black 0.5pt borders on all 6 cells gave requests:6. Re-fetch shows the table at 89. Screenshot shows a grey header row and black borders (2026-10-19-tc-doc26.png).

---

### TC-DOC27: Insert text then insert table — index chaining ⚠️ destructive
**Purpose:** verify that indices returned by one operation are usable as input to a subsequent operation without re-fetching the full structure each time.

**Setup:** start with a known doc structure; note `endIndex` of a paragraph as N

**Step 1 prompt**
> "Insert 'Intro paragraph.\n' at index {N} in doc {DOC_ID}"

**Step 2 prompt** (using `N + len('Intro paragraph.\n')` as the new insertion point)
> "Insert a 2×2 table at index {N + 17} in doc {DOC_ID}"

**Checks**
- Both operations succeed without error
- Re-fetch structure shows the paragraph immediately followed by the table
- `precedingParagraphIndex` = N + 17, `tableStartIndex` = N + 18

**Cleanup:** for each table, delete `[precedingParagraphIndex, tableEndIndex]` in one range (high→low for the two tables).

**Result (2026-06-20) ✅ PASS**
- N=88 (endIndex of "Item two\n"). Inserted "Intro paragraph.\n" (17 chars) at 88; then 2×2 table at 105. `precedingParagraphIndex=105=N+17`, `tableStartIndex=106=N+18`. Both ops succeeded without re-fetching structure.

**Result (2026-09-04) ✅ PASS**
Inserted "Intro paragraph.\n" (17 chars) at N=46; inserted 2x2 table at N+17=63 without re-fetching structure between calls. precedingParagraphIndex=63=N+17, tableStartIndex=64=N+18. get_doc_structure confirmed paragraph immediately followed by table. Table deleted after.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Inserted "Intro paragraph.\n" at N=88, then the table at 105 without re-fetching: precedingParagraphIndex 105 = N+17, tableStartIndex 106 = N+18; the paragraph is directly followed by the table.

---

## Phase 2 — `write_doc_content` / `create_doc` translator fixes

These test the HTML→AST→Docs API pipeline introduced in Phase 2 (#87). All use `write_doc_content` against the fixture doc.

### TC-DOC31: `<h2>` maps to HEADING_2 (not HEADING_3) ⚠️ destructive
**Purpose:** Regression test for #41 — `<h2>`–`<h6>` previously all collapsed to HEADING_3.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<h1>Level 1</h1><h2>Level 2</h2><h3>Level 3</h3><h4>Level 4</h4>`"

**Checks**
- Call `get_doc_structure` on the doc after writing
- First heading has `namedStyleType: "HEADING_1"`
- Second heading has `namedStyleType: "HEADING_2"` (not HEADING_3 — the old bug)
- Third heading has `namedStyleType: "HEADING_3"`
- Fourth heading has `namedStyleType: "HEADING_4"`

**Cleanup:** write fixture content back: `<h1>Test Document</h1><p>This document is used for QA testing of mcp-gee-sweet.</p><ul><li>Item one</li><li>Item two</li></ul>`

**Result (2026-06-20) ✅ PASS**
- `get_doc_structure` confirmed: HEADING_1 "Level 1", HEADING_2 "Level 2" (not HEADING_3), HEADING_3 "Level 3", HEADING_4 "Level 4". Old bug absent.

**Result (2026-09-04) ✅ PASS**
Wrote h1-h4. get_doc_structure: HEADING_1 "Level 1", HEADING_2 "Level 2" (not HEADING_3 - old bug absent), HEADING_3 "Level 3", HEADING_4 "Level 4".

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: HEADING_1 "Level 1", HEADING_2 "Level 2" (not HEADING_3), HEADING_3, HEADING_4.

---

### TC-DOC32: `<th>` cells produce bold runs ⚠️ destructive
**Purpose:** Regression test for #65 — `<th>` previously ignored; cells had no bold styling.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><th>Name</th><th>Value</th></tr><tr><td>Alpha</td><td>1</td></tr></table>`"

**Checks**
- `get_doc_structure` shows the table
- Row 0 cells (`Name`, `Value`) have runs with `bold: true`
- Row 1 cells (`Alpha`, `1`) have runs with `bold: null` (not bolded)
- 🔍 Visual check: header row text is bold in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-20) ⚠️ PARTIAL**
- Table created; `get_doc_structure` shows 2 rows, 2 cols with cells "Name", "Value", "Alpha", "1". `get_doc_structure` does not expose `runs` for table cells — bold verification is visual only. 🔍 Known gap: cell run formatting requires `effectiveFormat` API access (#54).
**Corrected (2026-10-17, #1044 audit):** bold in table cells was never checked on screen ("visual only").

**Result (2026-09-04) ✅ PASS**
th cells: table shows Name/Value/Alpha/1. Playwright screenshot (tc-doc32.png) confirmed "Name"/"Value" bold, "Alpha"/"1" plain.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Table Name/Value/Alpha/1. Cell runs aren't in get_doc_structure, so bold was checked in the browser: Name/Value bold, Alpha/1 plain (2026-10-19-tc-doc32.png).

---

### TC-DOC33: Inline formatting inside `<td>` cells ⚠️ destructive
**Purpose:** Regression test for #69 — inline formatting inside table cells was previously lost.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><b>bold</b> plain <i>italic</i></td></tr></table>`"

**Checks**
- `get_doc_structure` shows the table cell
- Cell text includes 'bold', 'plain', 'italic'
- Run with 'bold' has `bold: true`
- Run with 'italic' has `italic: true`
- Plain text run has `bold: null` and `italic: null`
- 🔍 Visual check: cell shows mixed formatting

**Cleanup:** write fixture content back

**Result (2026-06-20) ⚠️ PARTIAL**
- `get_doc_structure` shows 1 row, 1 col, cell text "bold plain italic" — all three segments present. Run-level bold/italic not verifiable via `get_doc_structure` (same cell-runs gap as TC-DOC32). 🔍 Visual check required for run formatting.
**Corrected (2026-10-17, #1044 audit):** the in-cell bold/italic was never checked on screen.

**Result (2026-09-04) ✅ PASS**
Cell text "bold plain italic". Playwright screenshot (tc-doc33.png) confirmed "bold" bold, "plain" plain, "italic" italic within one cell.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Cell text "bold plain italic". Screenshot shows "bold" bold, "plain" regular, "italic" italic in one cell (2026-10-19-tc-doc33.png).

---

### TC-DOC34: `colspan` produces merged cells ⚠️ destructive
**Purpose:** Regression test for #67 — `colspan` was previously ignored.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td colspan=\"2\">Wide cell</td></tr><tr><td>A</td><td>B</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the table has 2 rows
- Row 0 has 1 cell (merged), row 1 has 2 cells
- 🔍 Visual check: top row spans both columns in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- Call succeeded. `get_doc_structure`: 2 rows, 2 cols. Cell [0,0] text "Wide cell" (merged), cell [0,1] text "" (phantom). Row 1: "A", "B". Note: `get_doc_structure` reports `columns: 2` for the table — the merge is visible via the phantom empty slot at [0,1] and the larger index span of cell [0,0].

**Result (2026-09-04) ✅ PASS**
colspan=2 table: 2 rows, columns:2, [0,0]="Wide cell" merged, [0,1]="" phantom, row1 A/B. Playwright screenshot (tc-doc34.png) confirmed visual merge (top row spans both columns).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: 2 rows; [0,0]="Wide cell" (merged) and [0,1]="" phantom; row 1 A/B. Screenshot shows the top cell spanning both columns (2026-10-19-tc-doc34.png).

---

### TC-DOC35: Column widths from HTML ⚠️ destructive
**Purpose:** Regression test for #66 — `width` attributes on `<col>` were previously ignored.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><col width=\"144\"><col width=\"288\"><tr><td>Narrow</td><td>Wide</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- 🔍 Visual check: first column is narrower than second column in Google Docs
- 🔍 Note: `get_doc_structure` does not expose column width properties; visual verification is the only check available without `effectiveFormat` API access (#54)

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- Call succeeded with no API error. Column width is visual-only per the test note.

**Result (2026-09-04) ✅ PASS**
col width table, no API error. Playwright screenshot (tc-doc35.png) confirmed "Narrow" column visibly narrower than "Wide" column, ratio consistent with 144:288.

**Result (2026-10-17) ❌ FAIL — v0.9.2 release pass**
Passes alone, but widths on any table after the first fail with 400 "table start location is invalid" (reproduced 3×). Pre-existing: widths are built from the pre-fill document.

**Result (2026-10-18) ✅ PASS — PR #1082 QA round 1 (Kit)**
No API error. Playwright: "Narrow" visibly half the width of "Wide" (144:288).

**Result (2026-10-18) ✅ PASS — PR #1082 QA round 2 (Kit)**
No API error. Playwright: Narrow:Wide still 1:2 after the round-1 fix.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: No API error; screenshot shows Narrow ≈ half the width of Wide (144:288) (2026-10-19-tc-doc35.png). Extra probe: two tables with col widths in one write also succeeded with no 400, so the v0.9.2 failure (widths on a second table) did not reproduce.

---

### TC-DOC36: `rowspan` produces vertically merged cells ⚠️ destructive
**Purpose:** First live verification of issue #91 — rowspan support in the HTML→AST→emitter pipeline. A cell spanning two rows must produce a `mergeTableCells` request, and the phantom cell in the lower row must not be filled.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td rowspan=\"2\">Tall</td><td>R0C1</td></tr><tr><td>R1C1</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the table has 2 rows and 2 columns
- Row 0 has 2 physical cells; row 1 has 2 physical cells (Google Docs keeps the phantom cell as a physical slot post-merge)
- Cell [0,0] text = 'Tall'; cell [0,1] text = 'R0C1'; cell [1,1] text = 'R1C1'
- Cell [1,0] is the phantom slot — it must be empty (not filled with 'Tall' or any content)
- 🔍 Visual check: first column shows 'Tall' spanning both rows in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- 2 rows, 2 cols. Cell [0,0] "Tall" ✅, [0,1] "R0C1" ✅, [1,0] "" (phantom, empty) ✅, [1,1] "R1C1" ✅.

**Result (2026-09-04) ✅ PASS**
rowspan=2: 2 rows, 2 cols, [0,0]="Tall",[0,1]="R0C1",[1,0]="" phantom,[1,1]="R1C1". Playwright screenshot (tc-doc36.png) confirmed "Tall" visually spans both rows.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: 2×2: [0,0]="Tall", [0,1]="R0C1", [1,0]="" (phantom), [1,1]="R1C1". Screenshot shows "Tall" spanning both rows (2026-10-19-tc-doc36.png).

---

### TC-DOC37: Combined `rowspan` and `colspan` in the same table ⚠️ destructive
**Purpose:** verify that a single cell carrying both `rowspan` and `colspan` emits exactly one `mergeTableCells` request with both dimensions, and that physical column tracking stays correct for subsequent cells in the same row.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td rowspan=\"2\" colspan=\"2\">Big</td><td>R0C2</td></tr><tr><td>R1C2</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows 2 rows, 3 columns
- Cell [0,0] text = 'Big'; cell [0,2] text = 'R0C2'; cell [1,2] text = 'R1C2'
- Cells at [0,1], [1,0], [1,1] are phantom slots — must all be empty
- 🔍 Visual check: top-left 2×2 block shows 'Big' spanning both rows and columns

**Cleanup:** write fixture content back

**Result (2026-06-20) ✅ PASS**
- 2 rows, 3 cols. [0,0] "Big" ✅, [0,1] "" ✅, [0,2] "R0C2" ✅, [1,0] "" ✅, [1,1] "" ✅, [1,2] "R1C2" ✅. All phantom slots empty.

**Result (2026-08-19, regression) ⚠️ PARTIAL — re-run live against PR #636 (issue #377, Ruff UP/B/C4/SIM/RUF adoption).** PR #636 added `strict=True` to five `zip()` calls in `emitter.py`'s table-building pipeline (`_ast_cell_to_doc_cell`, `_build_merge_requests`, `_build_fill_requests`, `_build_cell_style_requests`, `_build_width_requests`) — a fail-fast guard, no intended behavior change on matched-length inputs. Re-ran via `create_doc` against a scratch doc (docId `1vux36c7ZOyBHb8YPi3WnubSotL0Mg0y5QZJjPmbEvxA`), not the shared fixture: `get_doc_structure` confirmed 2 rows, 3 columns; [0,0]="Big", [0,2]="R0C2", [1,2]="R1C2"; phantom slots [0,1]/[1,0]/[1,1] all empty. No `zip()` length-mismatch error raised. Doc trashed after verification (structural check only, no Playwright this round).
**Corrected (2026-10-17, #1044 audit):** structural check only; the required Playwright check wasn't run.

**Result (2026-09-04) ✅ PASS**
rowspan=2 colspan=2: 2 rows, 3 cols. [0,0]="Big",[0,1]="" phantom,[0,2]="R0C2",[1,0]="" phantom,[1,1]="" phantom,[1,2]="R1C2". Visual merge pattern already confirmed by TC-DOC34/36 (structural verification only this TC to save time).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: 2×3: [0,0]="Big", [0,2]="R0C2", [1,2]="R1C2"; phantoms [0,1], [1,0], [1,1] empty. Screenshot shows "Big" filling the 2×2 block (2026-10-19-tc-doc37.png).

---

### TC-DOC38: `rowspan` with header row — phantom not filled, real cells in correct columns ⚠️ destructive
**Purpose:** edge-case verification that when a rowspan pushes subsequent real cells to higher logical columns, the physical-to-AST index mapping resolves correctly and no cell gets the wrong content.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><th>Name</th><th>Type</th><th>Notes</th></tr><tr><td rowspan=\"2\">Alpha</td><td>A</td><td>first</td></tr><tr><td>B</td><td>second</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- Row 0: header cells 'Name', 'Type', 'Notes' — all bold
- Row 1: 'Alpha' in col 0 (rowspan=2), 'A' in col 1, 'first' in col 2
- Row 2: col 0 is phantom (empty, not filled with any content), 'B' in col 1, 'second' in col 2
- 🔍 Visual check: 'Alpha' spans rows 1 and 2 in Google Docs; row 2 col 1 shows 'B' (not shifted left)

**Cleanup:** write fixture content back

**Result (2026-06-20) ⚠️ PARTIAL**
- 3 rows, 3 cols. Row 0: "Name"/"Type"/"Notes" (bold visual only). Row 1: [1,0] "Alpha", [1,1] "A", [1,2] "first" ✅. Row 2: [2,0] "" (phantom) ✅, [2,1] "B" (not shifted left) ✅, [2,2] "second" ✅. Physical-to-AST column mapping correct.
**Corrected (2026-10-17, #1044 audit):** header bold was "visual only" and wasn't checked on screen.

**Result (2026-09-04) ✅ PASS**
rowspan header table: 3 rows, 3 cols. Row0 Name/Type/Notes, Row1 Alpha/A/first, Row2 ""(phantom)/B(not shifted left)/second. Physical-to-AST column mapping correct.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: 3×3: Name/Type/Notes; Alpha/A/first; ""/B/second (B not shifted left). Screenshot shows the header bold and Alpha spanning rows 1–2 (2026-10-19-tc-doc38.png).

---

## Markdown support — `create_doc` / `write_doc_content` / `create_doc_from_file`

### TC-DOC39: Markdown headings via `write_doc_content` ⚠️ destructive
**Purpose:** Verify that `content_format='markdown'` routes through the AST pipeline and produces correct heading styles.

**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `# Heading 1\n## Heading 2\n### Heading 3\n`"

**Checks**
- Call `get_doc_structure` after writing
- First heading has `namedStyleType: "HEADING_1"`
- Second heading has `namedStyleType: "HEADING_2"`
- Third heading has `namedStyleType: "HEADING_3"`

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- `get_doc_structure` confirmed HEADING_1, HEADING_2, HEADING_3 in order.

**Result (2026-09-04) ✅ PASS**
Markdown headings. get_doc_structure: HEADING_1/HEADING_2/HEADING_3 in order.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Markdown headings: HEADING_1, HEADING_2, HEADING_3 in order.

---

### TC-DOC40: Markdown bold and italic via `write_doc_content` ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `**bold** and *italic* text`"

**Checks**
- `get_doc_structure` shows a run with `bold: true` for 'bold'
- A run with `italic: true` for 'italic'

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Run `"bold"` had `bold: true`; run `"italic"` had `italic: true`.

**Result (2026-09-04) ✅ PASS**
Markdown bold/italic. "bold" run bold:true, "italic" run italic:true.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: "bold" run bold:true; "italic" run italic:true.

---

### TC-DOC41: Markdown task list ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `- [x] Done item\n- [ ] Pending item\n- Plain item\n`"

**Checks**
- Doc contains `☑ Done item` and `☐ Pending item` as bullet items
- Plain item has no checkbox glyph

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- `☑ Done item`, `☐ Pending item`, `Plain item` (no glyph) confirmed via `get_doc_structure`.
- 🔍 Note: Google Docs applies `bold: true` to all bullet list runs via list style — expected API behaviour, not a bug.

**Result (2026-09-04) ✅ PASS**
Markdown task list. "☑ Done item", "☐ Pending item", "Plain item" (no glyph).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Bullets "☑ Done item", "☐ Pending item", "Plain item" (no glyph), all on one listId.

---

### TC-DOC42: Markdown fenced code block ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown' with a fenced Python code block containing `def hello(): return 'world'`"

**Checks**
- Doc contains the code text with monospace font (Courier New)
- 🔍 Visual check: code block appears in monospace font in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ⚠️ PARTIAL**
- Two paragraphs: `def hello():` and `    return 'world'` confirmed via `get_doc_structure`.
- `weightedFontFamily: Courier New` is emitted by the unit-tested emitter; `get_doc_structure` does not expose `font_family` (known gap — no `effectiveFormat` API access).
**Corrected (2026-10-17, #1044 audit):** Courier New was "confirmed" by unit tests, not on screen.

**Result (2026-07-04) — related bug found, not a failure of this TC's own checks** Writing a fenced code block as the doc's last content left an explicit `font_size`/`font_family` override on the document's trailing paragraph mark, which `write_doc_content`'s clear+reinsert couldn't remove (the Docs API won't let `deleteContentRange` touch the final paragraph mark) — a *subsequent* `write_doc_content` call with plain content would inherit that contamination. Filed as [#255](https://github.com/khuisman/mcp-gee-sweet/issues/255). Fixed in [#258](https://github.com/khuisman/mcp-gee-sweet/pull/258), then corrected in [#259](https://github.com/khuisman/mcp-gee-sweet/pull/259) after live re-testing showed #258's single-batchUpdate version was unreliable. **Re-verified live (2026-07-05)** after both merged: wrote a fenced code block, then overwrote with plain content — new content came back with `textStyle: {}`, no contamination, across repeated rounds.

**Result (2026-09-04) ✅ PASS**
Markdown fenced code block. Text "def hello(): return 'world'" present. Playwright screenshot (tc-doc42.png) confirmed monospace font (toolbar shows "Courie..." = Courier New).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Fenced block: one paragraph "def hello(): return 'world'". Screenshot shows monospace text with the toolbar font "Courie…" at the cursor (2026-10-19-tc-doc42.png).

---

### TC-DOC43: Markdown table via `write_doc_content` ⚠️ destructive
**Prompt**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': a pipe table with columns Name and Value, rows Alpha/1 and Beta/2"

**Checks**
- `get_doc_structure` shows a table with 3 rows (header + 2 data rows) and 2 columns
- Cell text matches: 'Name', 'Value', 'Alpha', '1', 'Beta', '2'

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- Table: 3 rows, 2 columns. Cells: Name/Value, Alpha/1, Beta/2 — all correct.

**Result (2026-09-04) ✅ PASS**
Markdown pipe table. 3 rows, 2 columns: Name/Value, Alpha/1, Beta/2 — all correct.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Markdown pipe table: 3 rows × 2 cols, Name/Value, Alpha/1, Beta/2.

---

### TC-DOC44: `create_doc_from_file` with a local .md file ⚠️ requires-oauth ⚠️ destructive
**Setup:** use `docs/qa/fixtures/tc-d195-create-doc.md` from the repo

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d195-create-doc.md"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows HEADING_1 "QA Test Document", paragraphs with bold/italic runs, bullet items with `☑` and `☐` glyphs, and a table (Col A/Col B, one/two)
- 🔍 Visual check in Google Docs: heading, bold/italic text, task checkboxes, and table all render correctly

**Cleanup:** delete the created doc

**Result (2026-06-19) ✅ PASS**
- `docId` and `web_link` returned. `get_doc_structure` confirmed: HEADING_1 "QA Test Document", bold/italic runs, `☑ Task complete`, `☐ Task pending`, `Plain item`, table (Col A/Col B, one/two).

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-d195-create-doc.md): docId+web_link, no error. get_doc_structure confirmed HEADING_1 "QA Test Document", bold/italic runs, ☑/☐ bullet items, table (Col A/Col B, one/two). Trashed.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
create_doc_from_file(tc-d195-create-doc.md): docId+web_link, no error. get_doc_structure: HEADING_1 "QA Test Document", bold/italic runs, ☑/☐/Plain item bullets, Col A/Col B table. Playwright (account check passed): heading, bold/italic, checkbox glyphs, and table render correctly. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc_from_file(tc-d195-create-doc.md): docId+web_link; HEADING_1 "QA Test Document"; bold and italic runs; ☑/☐/Plain item bullets; Col A/Col B, one/two table. Screenshot shows all of it rendered (2026-10-19-tc-doc44.png). Trashed.

---

### TC-DOC45: `create_doc_from_file` with a local .html file ⚠️ requires-oauth ⚠️ destructive
**Setup:** use `docs/qa/fixtures/tc-d196-create-doc.html` from the repo

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d196-create-doc.html"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows HEADING_2 "From HTML file" and paragraph "Content paragraph."

**Cleanup:** delete the created doc

**Result (2026-06-19) ✅ PASS**
- `docId` and `web_link` returned. `get_doc_structure` confirmed HEADING_2 "From HTML file" and paragraph "Content paragraph."

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-d196-create-doc.html): docId+web_link, no error. get_doc_structure confirmed HEADING_2 "From HTML file", paragraph "Content paragraph." Trashed.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
create_doc_from_file(tc-d196-create-doc.html): docId+web_link, no error. get_doc_structure: HEADING_2 "From HTML file", paragraph "Content paragraph." Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc_from_file(tc-d196-create-doc.html): HEADING_2 "From HTML file" and paragraph "Content paragraph." Trashed.

---

### TC-DOC46: `create_doc_from_file` file not found
**Prompt**
> "Create a Google Doc from the file ~/does-not-exist.md"

**Checks**
- Returns `{"error": "File not found: ..."}` — no exception raised

**Result (2026-06-19) ✅ PASS**
- Returned `{"error": "File not found: /tmp/nonexistent-file.md"}` — no exception.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file('~/does-not-exist.md') returned {"error": "File not found: ~/does-not-exist.md"}, no exception.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
create_doc_from_file('~/does-not-exist.md') returned {"error": "File not found: ~/does-not-exist.md"}, no exception. Unsupported .txt also still returns the no-hint message "Use .md or .html/.htm" (shared helper, format_overridable=False).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc_from_file('~/does-not-exist.md') returned {"error":"File not found: ~/does-not-exist.md"}; no exception.

---

### TC-DOC47: `write_doc_content` inline code monospace ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': `Use the \`print()\` function`"

**Checks**
- 🔍 Visual check: `print()` appears in monospace (Courier New) inside the paragraph

**Cleanup:** write fixture content back

**Result (2026-06-19) ⚠️ PARTIAL**
- Paragraph text `Call my_function() with param=True to enable it.` confirmed; code spans at correct positions.
- `weightedFontFamily: Courier New` confirmed via unit tests; not exposed by `get_doc_structure` (known gap).
**Corrected (2026-10-17, #1044 audit):** Courier New was "confirmed" by unit tests, not on screen.

**Result (2026-07-04)** Two findings during the v0.8.1 live pass, neither a failure of this TC's own checks:
1. The prescribed SVG image URI in TC-DOC57/58 is unrelated to this TC but was hit in the same session — see those TCs, now fixed to use a PNG.
2. This TC's own content (an inline code span) was one of the reproductions of the trailing-paragraph-mark contamination bug — see TC-DOC42's 2026-07-04 result for the full account, filed as [#255](https://github.com/khuisman/mcp-gee-sweet/issues/255), fixed in [#258](https://github.com/khuisman/mcp-gee-sweet/pull/258)/[#259](https://github.com/khuisman/mcp-gee-sweet/pull/259) and re-verified live post-merge. Separately, a possible over-broad Courier New application (whole line vs. just the code span) was observed visually but not conclusively confirmed, since `get_doc_structure` doesn't expose `font_family` per run — no ticket filed yet, flagged as a follow-up if that gap is ever closed.

**Result (2026-09-04) ✅ PASS**
Wrote inline code markdown. Playwright screenshot (tc-doc47.png) confirmed "print()" renders in monospace font within the plain-font sentence — only the code span, not the whole line.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Screenshot shows only "print()" in monospace inside the Arial sentence (2026-10-19-tc-doc47.png).

---

### TC-DOC78: `data-style="title"` produces TITLE named style ⚠️ destructive
**Purpose:** verify that `<p data-style="title">` is parsed as a `NamedBlock(TITLE)` and the emitter applies `updateParagraphStyle` with `namedStyleType: TITLE`.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<p data-style=\"title\">My Document Title</p><p>Body paragraph.</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the first paragraph with `namedStyleType: "TITLE"` and text "My Document Title"
- Second paragraph has `namedStyleType: "NORMAL_TEXT"` and text "Body paragraph."

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- First paragraph `namedStyleType: "TITLE"`, text "My Document Title" confirmed via `get_doc_structure`.
- Second paragraph `namedStyleType: "NORMAL_TEXT"`, text "Body paragraph." confirmed.

**Result (2026-09-04) ✅ PASS**
data-style="title" -> TITLE named style, "My Document Title" + NORMAL_TEXT "Body paragraph."

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: TITLE "My Document Title", then NORMAL_TEXT "Body paragraph."

---

### TC-DOC79: `data-style="subtitle"` produces SUBTITLE named style ⚠️ destructive
**Purpose:** verify SUBTITLE works the same way as TITLE.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<p data-style=\"title\">Title</p><p data-style=\"subtitle\">Subtitle text here</p><p>Body.</p>`"

**Checks**
- Call succeeds with no API error
- First paragraph: `namedStyleType: "TITLE"`, text "Title"
- Second paragraph: `namedStyleType: "SUBTITLE"`, text "Subtitle text here"
- Third paragraph: `namedStyleType: "NORMAL_TEXT"`, text "Body."

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅ PASS**
- All three paragraphs confirmed: `TITLE` / `SUBTITLE` / `NORMAL_TEXT` with correct text values.

**Result (2026-09-04) ✅ PASS**
data-style="title"/"subtitle" -> TITLE "Title", SUBTITLE "Subtitle text here", NORMAL_TEXT "Body."

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: TITLE "Title", SUBTITLE "Subtitle text here", NORMAL_TEXT "Body."

---

### TC-DOC76: Table immediately after heading renders at Normal Text size ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-d226-heading-table.md` from the repo (absolute path: `<repo-root>/docs/qa/fixtures/tc-d226-heading-table.md`)

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d226-heading-table.md, then show me its structure."

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows a `table` element with 6 cells containing "Finding", "Severity", "Ticket", "Some finding", "HIGH", "KINDLY-123"
- 🔍 Visual check: open the doc — table cell text renders visually smaller than the "HIGH" H2 heading above it (~11pt vs ~16pt); no blank paragraph workaround needed

**Cleanup:** delete the created doc

**Result (2026-06-24) ✅ PASS** "HIGH" heading renders visually larger than table text. All six cells ("Finding", "Severity", "Ticket", "Some finding", "HIGH", "KINDLY-123") render at Normal Text size. No blank paragraph between heading and table required. No oversized cell text observed.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-d226-heading-table.md): table with 6 cells (Finding/Severity/Ticket/Some finding/HIGH/KINDLY-123) confirmed. Playwright screenshot (tc-doc76-77.png) confirmed "HIGH" heading renders visibly larger (16pt) than table cell text (11pt). Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc_from_file(tc-d226-heading-table.md): table with 6 cells Finding/Severity/Ticket/Some finding/HIGH/KINDLY-123. Screenshot shows the HIGH heading (16pt) visibly larger than the cell text (2026-10-19-tc-doc76-77.png). Trashed.

---

### TC-DOC77: No visible blank line between heading and table in `create_doc_from_file` ⚠️ requires-oauth ⚠️ destructive

**Background:** the Docs API inserts a structurally-required blank paragraph before every table;
`deleteContentRange` is rejected for it. The fix collapses it to zero visual height via
`updateParagraphStyle` (spaceAbove/Below=0, lineSpacing=1) + `updateTextStyle` (fontSize=1pt).

**Setup:** use `docs/qa/fixtures/tc-d226-heading-table.md` (heading immediately followed by a table)

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d226-heading-table.md, then show me its structure."

**Checks**
- Tool completes without error (no `HttpError 400`)
- `get_doc_structure` returns a body with a heading and a table; a blank paragraph element may still be listed (it is structurally present), but its `paragraph.paragraphStyle` should show `lineSpacing: 1`, `spaceAbove: 0`, `spaceBelow: 0`
- 🔍 Visual check: open the doc — no visible blank line between the "HIGH" heading and the table

**Cleanup:** delete the created doc

**Result (2026-06-25) ✅ PASS**
- Tool completed without error. Structure: sectionBreak → HEADING_2 "HIGH\n" (1-6) → blank para "\n" (6-7, `font_size: 1` on its run confirming collapse applied) → table (7-70, cells filled correctly: Finding/Severity/Ticket header, Some finding/HIGH/KINDLY-123 data) → trailing para (70-71). Visual check: no visible gap between heading and table in the rendered doc.

**Result (2026-09-04) ✅ PASS**
No HttpError 400. Blank paragraph between heading and table has font_size:1 on its run (collapse applied). Playwright screenshot confirmed no visible gap between heading and table.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`kai-oauth`: Same doc as TC-DOC76: no HttpError 400; the blank paragraph 6–7 between the heading and the table has font_size 1; the screenshot shows no visible gap. Not checked: paragraphStyle lineSpacing/spaceAbove/spaceBelow, which get_doc_structure doesn't expose; reading them needs a raw-field token script, not available in this pass.

---

### TC-DOC81: create_doc_from_file renders \$ escape as literal $ (issue #213) ⚠️ requires-oauth ⚠️ destructive

**Background:** Python-Markdown's default `ESCAPED_CHARS` omits `$` (unlike CommonMark, which includes it in its escapable-punctuation set), so `\$` — commonly used to defeat math/LaTeX-delimiter renderers like Obsidian/Typora/Jupyter that treat bare `$...$` as inline math — previously passed through untouched into the rendered Doc as a literal backslash+dollar. Fixed via a small `markdown.extensions.Extension` that adds `$` to `ESCAPED_CHARS`, so it's handled by the library's own escape mechanism (respecting code-span/fenced-code protection) rather than a blind text substitution.

**Setup:** use `docs/qa/fixtures/tc-d213-dollar-escape.md` from the repo (a table cell, a second table row, and a plain-text sentence, each with a `\$`-escaped dollar amount)

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-d213-dollar-escape.md"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_content` shows `$6,000`, `$25`, and `$1,200` as plain literal dollar amounts — no `\$` (literal backslash+dollar) anywhere in the content

**Cleanup:** delete the created doc

**Result (2026-07-04) ✅ PASS**
`create_doc_from_file` succeeded. `get_doc_content` returned: `"...Deductible\r\n\t$6,000\r\n\tCopay\r\n\t$25\r\n\tPlain text with an escaped price: $1,200 due at signing."` — all three escaped amounts rendered as literal `$`, no `\$` anywhere. Doc permanently deleted after verification.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-d213-dollar-escape.md). get_doc_content showed $6,000, $25, $1,200 as literal — no \$ anywhere. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: create_doc_from_file(tc-d213-dollar-escape.md): get_doc_content shows $6,000, $25, $1,200 as literal amounts, with no `\$` anywhere. Trashed.

---

## `create_doc` autolinks bare URLs (issue #248)

### TC-DOC82: create_doc autolinks bare URLs in markdown content (issue #248) ⚠️ requires-oauth ⚠️ destructive

**Background:** Python-Markdown's built-in autolink only fires on `<https://...>` (angle brackets) or `[text](url)` — a bare URL like `https://example.com/some-page` was left as inert plain text with no hyperlink. Fixed via a low-priority `InlineProcessor` extension that autolinks bare `http(s)://` URLs left as plain text after the library's own link/code-span processing runs, trimming trailing sentence punctuation and unmatched closing parens (CommonMark/GFM extended-autolink behavior).

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'QA TC-DOC82' with content_format='markdown' and this content: `From: https://example.com/some-page. See (https://example.com/parens) for details. Already linked: [click](https://example.com/existing). Code: \`https://example.com/code\`.`"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows a run with `link_url: "https://example.com/some-page"` (trailing period NOT included in the link)
- A run with `link_url: "https://example.com/parens"` (wrapping parens NOT included in the link)
- The existing markdown link still shows `link_url: "https://example.com/existing"` (not double-processed)
- The backtick-wrapped URL has no `link_url` set (code span still suppresses autolinking)

**Cleanup:** delete the created doc

**Result (2026-07-05) ✅ PASS**
`create_doc` succeeded (docId `1F66ZQQMuBx9CjaGx49bBg6DlcVMAYMnqnuYHtouyfIU`). `get_doc_structure` confirmed all four checks: `https://example.com/some-page` run has `link_url` set with the trailing `.` split into its own unlinked run; `https://example.com/parens` run has `link_url` set with both wrapping parens split into unlinked runs; the markdown link's `click` run has `link_url: "https://example.com/existing"` (untouched, not double-processed); the backtick-wrapped `https://example.com/code` run has `link_url: null`. Doc trashed after verification. Visual check (re-created identical content, Playwright screenshot, re-trashed): both bare URLs render blue/underlined, wrapping punctuation stays plain black, `click` renders as a normal link, and the backtick-wrapped URL renders as plain monospace code — not a link.

**Result (2026-08-19, regression) ⚠️ PARTIAL — re-run live against PR #636 (issue #377, Ruff UP/B/C4/SIM/RUF adoption).** PR #636 merged this test's exact `if`/`elif` trailing-punctuation branch into one `or`-joined condition in `_BareUrlInlineProcessor` (mechanical SIM108-style cleanup, no intended behavior change). Re-ran via `create_doc` (docId `1NZTdIPJxmxMWGKJH_aelsillFToCShhXCutGhCiH8JU`): all four checks still hold — trailing `.` and wrapping parens correctly split off into unlinked runs, existing markdown link untouched, backtick-wrapped URL has `link_url: null`. Doc trashed after verification (structural check only, no Playwright this round).
**Corrected (2026-10-17, #1044 audit):** structural check only; the required Playwright check wasn't run.

**Result (2026-09-04) ✅ PASS**
create_doc markdown with bare URLs. All 4 checks confirmed: "https://example.com/some-page" link_url set, trailing "." split off unlinked; "https://example.com/parens" link_url set, wrapping parens split off unlinked; "click" link_url=".../existing" (untouched); backtick-wrapped URL run has link_url:null. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: some-page link_url set with the trailing "." unlinked; parens link_url set with "(" and ")" unlinked; "click" keeps link_url …/existing; backtick URL has link_url null. Screenshot shows two blue links, the click link, and plain monospace for the code URL (2026-10-19-tc-doc82.png). Trashed.

---

### TC-DOC83: autolink_urls=False leaves bare URLs as plain text (issue #248) ⚠️ requires-oauth ⚠️ destructive

**Background:** The autolinking added for TC-DOC82 is unconditional by default. `autolink_urls: bool = True` on `create_doc`/`create_doc_from_file`/`write_doc_content` lets a caller opt out for the whole call when a bare URL should stay as plain, non-monospace text (backticks are the existing per-URL escape hatch, but they force code styling).

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'QA TC-DOC83' with content_format='markdown', autolink_urls=False, and this content: `See https://example.com/inert here`"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows the URL text present with `link_url: null` (no hyperlink applied)

**Cleanup:** delete the created doc

**Result (2026-07-05) ✅ PASS**
`create_doc` succeeded (docId `1elTfZ70c6AO66cjLQ7O-PrzzUlYGmVwiKuNWjDXVMGI`). `get_doc_structure` confirmed the entire line ("See https://example.com/inert here") is a single unstyled run — no `link_url`, no underline. Doc trashed after verification. Visual check (re-created identical content, Playwright screenshot, re-trashed): entire line renders as plain black text, no blue/underline anywhere.

**Result (2026-09-04) ✅ PASS**
create_doc with autolink_urls=False. Entire line is one unstyled run, no link_url anywhere. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: autolink_urls=False: the whole line is one run with link_url null. Screenshot shows plain black text (2026-10-19-tc-doc83.png). Trashed.

---
## Nested table support — `write_doc_content`

### TC-DOC48: Simple nested table ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>Inner</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col)
- The outer cell contains a nested table element with cell text "Inner"
- 🔍 Visual check: nested table visible inside the outer table cell in Google Docs

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 1 col, cell [0,0] startIndex=4 endIndex=17 text="" (empty text run confirms cell holds nested table, not text). Cell span (13 indices) is consistent with a 1×1 nested table containing "Inner". Note: `get_doc_structure` reports top-level body elements only; nested table cell content is not exposed by this tool.

**Result (2026-09-04) ✅ PASS**
Simple nested table: outer 1x1, cell span 4-17 (13 idx, consistent with nested table holding "Inner"). No API error.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: No error; outer table 1×1, cell span 4–17. Nested content isn't exposed by get_doc_structure (documented). Screenshot shows the inner table with "Inner" inside the outer cell (2026-10-19-tc-doc48.png).

---

### TC-DOC49: Nested table alongside regular cells ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>Label</td><td><table><tr><td>Val A</td><td>Val B</td></tr></table></td></tr></table>`"

**Checks**
- Outer table has 1 row, 2 columns
- Cell [0,0] text = "Label"
- Cell [0,1] contains a nested table with 1 row × 2 cols, cells "Val A" and "Val B"
- 🔍 Visual check: label in col 0, small inner table in col 1

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 2 cols. Cell [0,0] text="Label" ✅. Cell [0,1] text="" with span 11–31 (20 indices, consistent with 1×2 nested table holding "Val A" and "Val B") ✅.

**Result (2026-09-04) ✅ PASS**
Nested table alongside regular cell: outer 1 row 2 cols, [0,0]="Label", [0,1]="" span 11-31 (20 idx, consistent with 1x2 nested table).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Outer 1×2; [0,0]="Label"; [0,1] span 11–31. Screenshot shows a 1×2 inner table "Val A"/"Val B" in column 1 (2026-10-19-tc-doc49.png).

---

### TC-DOC50: Nested table with multiple rows and columns ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>R0C0</td><td>R0C1</td></tr><tr><td>R1C0</td><td>R1C1</td></tr></table></td></tr></table>`"

**Checks**
- Outer table: 1 row, 1 col
- Nested table: 2 rows × 2 cols
- All four nested cells filled correctly: R0C0, R0C1, R1C0, R1C1
- 🔍 Visual check: 2×2 grid inside the outer cell

**Cleanup:** write fixture content back

**Result (2026-06-19) ✅** `write_doc_content` succeeded. `get_doc_structure` shows outer table: 1 row × 1 col, cell [0,0] text="" with span 4–35 (31 indices, consistent with a 2×2 nested table containing four 4-char cell values plus table overhead) ✅.

**Result (2026-09-04) ✅ PASS**
Nested table multi-row/col: outer 1x1, cell span 4-35 (31 idx). Playwright screenshot (tc-doc50.png) confirmed visible 2x2 nested grid (R0C0/R0C1/R1C0/R1C1) rendering inside the outer cell — covers visual confirmation for DOC48/49/50.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Outer 1×1, cell span 4–35. Screenshot shows a 2×2 nested grid R0C0/R0C1/R1C0/R1C1 (2026-10-19-tc-doc50.png).

---

### TC-DOC51: Nested tables not supported in markdown (documented limitation)
**Note:** The markdown pipeline does not produce nested tables — the `markdown` library does not support table-in-table syntax. Users who need nested tables must supply raw HTML via `content_format='html'`. No test to run; this entry documents the known limitation.

**Result (2026-09-04) ⏭️ SKIP**

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Documentation-only entry (nested tables in markdown are a documented limitation); nothing to run.

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`kai-oauth`: Documentation-only entry (nested tables in Markdown are a documented limitation); nothing to run.


---

### TC-DOC84: Text sharing a cell with a nested table is no longer dropped (issue #108) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>Some label <table><tr><td>Inner</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col) with a non-empty text run in cell [0,0] (previously this cell's text was silently dropped — bled into the nested table's own cell instead)
- 🔍 Visual check: "Some label" appears above/before the nested table inside the outer cell, and the nested table's own cell reads "Inner" (not "Some label Inner" merged together)

**Cleanup:** write fixture content back

**Result (2026-07-06) ✅ PASS** `get_doc_structure` shows outer cell [0,0] `text: "Some label"` (previously empty per TC-DOC48's bug pattern). Playwright screenshot confirms "Some label" renders above the nested table, whose own cell reads exactly "Inner" — no merging.

**Result (2026-09-04) ✅ PASS**
Outer cell [0,0] text "Some label" (previously dropped bug) — text sharing cell with nested table preserved.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kai-oauth`: Outer 1×1 cell [0,0] text "Some label" (not dropped). Screenshot shows "Some label" above a nested table whose cell reads exactly "Inner" (2026-10-19-tc-doc84.png).

---

### TC-DOC85: Text after a nested table in the same cell, correctly positioned (issue #275) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td>Inner</td></tr></table>After</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer cell's text as "After" — content intact, not merged with "Inner"
- 🔍 Visual check: "After" renders *below* the nested table, not above it

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` cell [0,0] `text: "After"`. Playwright confirms "After" renders below the nested table ("Inner"). Note: an earlier pass of this test case (2026-07-06) incorrectly expected "After" to render *above* the table — that was the pre-#275-fix limitation (a cell's text always rendered as one block before any nested table, regardless of source order). #275 fixed the emitter to place text on the correct side of each nested table; this test case's expectation and prompt were updated to match.

**Result (2026-09-04) ✅ PASS**
Outer cell text "After" — text after nested table correctly positioned, not merged with "Inner".

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: write_doc_content of a nested table followed by "After". Outer cell [0,0] text was "After", and the Playwright screenshot (2026-10-19-tc-doc85.png) shows "After" below the nested "Inner" table.

---

### TC-DOC86: Text before AND after one nested table, both correctly positioned (issue #275) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>Before <table><tr><td>Inner</td></tr></table> After</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows outer cell [0,0] text as `"Before \n After"` (the `\n` confirms two distinct paragraphs — before and after the table — not one merged block)
- 🔍 Visual check: "Before" above the nested table, "Inner" inside it, "After" below it

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` shows `text: "Before \n After"`. Playwright screenshot confirms all three pieces render in the correct order and position.

**Result (2026-09-04) ✅ PASS**
Outer cell text "Before \n After" — text before AND after nested table both correctly positioned (two paragraphs).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Outer cell text was "Before \n After". The screenshot (tc-doc86) shows Before, then the Inner table, then After, in that order.

---

### TC-DOC87: Multiple nested tables in one cell with text between them (issue #275) ⚠️ destructive
**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td>A<table><tr><td>1</td></tr></table>B<table><tr><td>2</td></tr></table>C</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows outer cell [0,0] text as `"A\nB\nC"` (three separate paragraphs — one per text segment between/around the two nested tables)
- 🔍 Visual check: A, then a table containing "1", then B, then a second table containing "2", then C — all in that order

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` shows `text: "A\nB\nC"`. Playwright screenshot confirms both nested tables render in the correct positions with "1" and "2" filled in, and A/B/C text correctly interleaved — a capability that didn't exist before #275 (previously only one nested table per cell was supported at all).

**Result (2026-09-04) ✅ PASS**
Outer cell text "A\nB\nC" — multiple nested tables with interleaved text, three separate paragraphs.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Outer cell text was "A\nB\nC". The screenshot (tc-doc87) shows A, table "1", B, table "2", C.

---

### TC-DOC88: `colspan="0"` clamps to 1 instead of producing a degenerate zero-column cell

**Background:** Found via code review of PR #276 — `int(attr_dict.get("colspan") or 1)` only covers a *missing* colspan attribute; an explicit `colspan="0"` is a non-empty (truthy) string, so it survives the `or` and parses to the literal integer `0`. A cell that spans zero columns breaks downstream `num_cols` calculations used by the nested-table fill algorithm. Fixed by clamping colspan/rowspan to a minimum of 1 in `html_parser.py`.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td colspan="0">Wide</td><td>Next</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the table with `columns: 2` (not 1 or a broken/merged layout) — cell [0,0] text "Wide", cell [0,1] text "Next"

**Cleanup:** write fixture content back

**Result (2026-07-07) ✅ PASS** `get_doc_structure` shows `columns: 2`, cell [0,0] `text: "Wide"`, cell [0,1] `text: "Next"` — `colspan="0"` clamped to 1 and rendered as two normal side-by-side cells.

**Result (2026-09-04) ✅ PASS**
colspan="0" clamped to 1: columns:2, [0,0]="Wide", [0,1]="Next" — not degenerate.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: colspan="0" gave columns:2, with [0,0]="Wide" and [0,1]="Next".

---

### TC-DOC89: Degenerate table (row with no cells) followed by a real table doesn't desync content (issue #277)

**Background:** `ast_to_requests` skips emitting an `insertTable` request for a table with zero rows or zero columns (e.g. a `<tr>` with no `<td>`s), but was still counting that table in the list it hands to `fill_tables()`. Since `fill_tables()` pairs AST tables against live-doc tables positionally, a skipped table shifted every later table's fill/merge/style requests onto the wrong doc table — silently, with no error. Fixed by excluding degenerate tables from that list at the source.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<table><tr></tr></table><table><tr><td>A</td><td>B</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows exactly **one** table in the doc (the empty-row table produces no table element at all)
- That table is `columns: 2` with cell [0,0] text "A" and cell [0,1] text "B" — not empty, not misapplied, not offset onto the wrong table

**Cleanup:** write fixture content back

**Result (2026-07-09) ✅ PASS**

**Result (2026-09-04) ✅ PASS**
Degenerate empty-row table dropped; exactly one real table remains, columns:2, [0,0]="A",[0,1]="B" — not misapplied/offset.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: The empty-row table produced no element. Exactly one table remained: columns:2, [0,0]="A", [0,1]="B".

---

### TC-DOC90: `colspan`/`rowspan` inside a nested table now merges correctly (issue #109) ⚠️ destructive

**Background:** Nested tables produced a correctly-sized shell but silently ignored `colspan`/`rowspan` on their own cells — no `mergeTableCells` request was ever emitted for them, unlike outer-table cells (TC-DOC34/36/37). Fixed by having `_fill_table_fully` run the same merge phase for a nested table's own cells that `fill_tables` already runs for the outer table.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: `<table><tr><td><table><tr><td colspan=\"2\">Header</td></tr><tr><td>A</td><td>B</td></tr></table></td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the outer table (1 row × 1 col) with cell [0,0] text empty (holds the nested table, not text)
- 🔍 Visual check: nested table renders with "Header" spanning both columns of the top row, and "A"/"B" as two separate cells in the second row — not four ungrouped cells

**Cleanup:** write fixture content back

**Result (2026-07-09) ✅ PASS**
`write_doc_content` succeeded. `get_doc_structure` showed the outer table (1 row × 1 col) with cell [0,0] text empty. Playwright screenshot confirmed the nested table rendered with "Header" spanning both columns of the top row and "A"/"B" as two separate cells below — the merge applied correctly. (Unrelated observation: the fixture doc had leftover header/footer text visible in the render and in `get_doc_content`'s plain-text export but not in `get_doc_structure` — headers/footers aren't part of the body map that tool returns; pre-existing fixture-doc state from an earlier header/footer test, untouched by `write_doc_content`, not a regression from this PR.) Fixture content restored per cleanup step.

**Result (2026-09-04) ✅ PASS**
colspan inside nested table: outer 1x1 cell empty (holds nested table). Playwright screenshot (tc-doc90.png) confirmed nested table's "Header" spans both columns of top row, "A"/"B" separate cells below — merge inside nested table works.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Outer 1×1 table with an empty cell [0,0]. The screenshot (tc-doc90) shows "Header" spanning both nested columns, with A and B in separate cells below.

---

## `insert_inline_image` (#145)

**Fixture:** `docs/qa/fixtures/qa-fixture-pixel.png` — the same 1×1 pixel PNG already committed for `insert_local_images` below, reused here rather than adding a second near-identical fixture (issue #224). TC-DOC57/58 previously depended on an external `gstatic.com` URL (Google's own branding logo) as their only image source, and neither case exercised a self-contained, repo-owned asset — closed here by having both cases upload+share this fixture instead. #224 also asked to investigate an SVG fixture alongside the PNG one; deliberately not added — the Docs API's `InsertInlineImageRequest` reference documents PNG/JPEG/GIF as the only supported inline-image formats (no SVG), confirmed against the API reference directly, so a committed SVG fixture would exercise a format the API rejects outright rather than add a useful test case.

### TC-DOC57: Insert an image by public URI ⚠️ requires-oauth ⚠️ destructive
**Setup:**
1. `upload_local_file(local_path="<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png", parent_folder_id={FOLDER_ID}, name="qa-fixture-pixel.png", skip_if_exists=False)` — note the returned `fileId` as `{FIXTURE_FILE_ID}` and `web_content_link` (a direct-download link, returned for a new non-converted upload) as `{FIXTURE_WEB_CONTENT_LINK}`
2. `share_file(file_id={FIXTURE_FILE_ID}, permissions=[{"type": "anyone", "role": "reader"}])`
3. Fetch structure; note the `endIndex` of a paragraph to insert after as `{N}`

**Prompt**
**Playwright: required**
> "Insert an image from URI '{FIXTURE_WEB_CONTENT_LINK}' at index {N} in doc {DOC_ID}"

Tool call: `insert_inline_image(doc_id={DOC_ID}, index={N}, uri="{FIXTURE_WEB_CONTENT_LINK}")`. `upload_local_file` returns Drive's `webContentLink` as `web_content_link` (#511), so no hand-built `uc?export=download` URL is needed.

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `index: N`
- 🔍 Visual check in Google Docs: image appears in the document at the insertion point

**Cleanup:** delete the inserted image range (use `delete_doc_range` on the image's index span, visible in `get_doc_structure` as an element); remove the `anyone` permission from `{FIXTURE_FILE_ID}` and trash it

**Result (2026-08-21) ✅ PASS** Uploaded+shared `qa-fixture-pixel.png`, fetched structure (`N=88`), called `insert_inline_image(uri="https://drive.google.com/uc?export=download&id={FIXTURE_FILE_ID}")`. Response: `{docId, index: 88}` — no API error. `get_doc_structure` confirmed the image occupies one index slot (endIndex grew 89→90). Playwright screenshot confirmed a (tiny, since the source is 1×1px) image visible at the insertion point. Cleanup completed: image range deleted, permission removed, file trashed.

**Result (2026-09-04) ✅ PASS**
Uploaded+shared qa-fixture-pixel.png, inserted via uri (uc?export=download). Response {docId, index:28}, no API error. get_doc_structure confirmed image occupies 1 index slot (endIndex 29->30). Playwright screenshot (tc-doc57.png) confirmed tiny image visible below table. Cleanup: range deleted, permission removed, file trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Inserted from a public gstatic PNG URI (sharing to anyone was out of scope at the time).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kit`: On a fresh doc in the run folder: uploaded the pixel, shared anyone/reader, `insert_inline_image(uri=…uc?export=download&id=…)` returned docId and index, no error. Playwright (`2026-10-19-tc-doc57-58.png`) shows the 1×1 image at the insertion point. Share removed; files trashed. (The oauth shard's share was refused by the session's safety check, so Aziz ran it.)

---

### TC-DOC58: Insert an image with explicit size, from a Drive file ⚠️ requires-oauth ⚠️ destructive
**Setup:** same as TC-DOC57 (independent fresh upload+share, its own `{FIXTURE_FILE_ID}` — do not reuse TC-DOC57's, which its own cleanup already trashes and de-shares) — this case exercises `drive_file_id` instead of `uri`, closing a gap where no existing test covered the plain (non-`auto_downscale`) `drive_file_id` happy path: TC-DOC161/162 (#400) only cover the oversized-error and auto-downscale cases, and the auto-downscale path shares its own resized copy internally rather than requiring the caller to share anything first

**Prompt**
**Playwright: required**
> "Insert the image at Drive file {FIXTURE_FILE_ID} at index {N} in doc {DOC_ID} with width 100 and height 50"

Tool call: `insert_inline_image(doc_id={DOC_ID}, index={N}, drive_file_id={FIXTURE_FILE_ID}, width=100, height=50)`

**Checks**
- Call succeeds with no API error
- 🔍 Visual check: select the inserted image, open Format → Image options → Size & rotation, and confirm width and height both read ≈0.69in (50pt) — **not** 1.39in×0.69in (100pt×50pt). Confirmed live (2026-08-21) that the Docs API treats `width`/`height` as a bounding box fitted preserving the source's own native aspect ratio, not a non-uniform stretch: since `qa-fixture-pixel.png` is natively 1×1 (square), the requested 100×50 box is fit to its shorter side, landing both axes at 50pt. This is expected Docs API behavior, not a tool defect — a non-square source (verified separately with a throwaway 40×20 PNG) does land at the exact requested 100×50. The point of this check is confirming the explicit size was honored at all: 50pt is unambiguously larger than the fixture's own unsized default of 0.75pt×0.75pt (verified live), which the old "smaller than default" wording got backwards for this fixture — the explicit size here is *larger* than default, not smaller.

**Cleanup:** delete inserted image range; remove the `anyone` permission from `{FIXTURE_FILE_ID}` and trash it

**Result (2026-08-21) ✅ PASS** Uploaded+shared a fresh, independent copy of `qa-fixture-pixel.png` (own `{FIXTURE_FILE_ID}`, not TC-DOC57's). Called `insert_inline_image(drive_file_id={FIXTURE_FILE_ID}, width=100, height=50)` at `N=88`. Response: `{docId, index: 88}` — no API error. Verified applied size via Format → Image options → Size & rotation: width and height both read 0.69in (50pt), confirming Google's Docs API fit the requested 100×50 bounding box to the fixture's native 1:1 aspect ratio rather than stretching non-uniformly (cross-checked against the raw `documents().get()` response directly: `inlineObjects[...].inlineObjectProperties.embeddedObject.size` = `{width: 50pt, height: 50pt}`). Separately confirmed via a throwaway 40×20 non-square PNG that a non-square source *does* land at the exact requested 100×50 — this collapse is specific to a square-native source, not a general tool defect. Also confirmed the fixture's own true default (no explicit size) is 0.75pt×0.75pt, so the 50pt explicit size is clearly *larger* than default, not smaller as the original check wording (fixed this pass) claimed. Cleanup completed: image range deleted, permission removed, file trashed.

**Result (2026-09-04) ✅ PASS**
Fresh upload+share, inserted via drive_file_id with width=100,height=50. Response {docId, index:28}, no API error. Playwright screenshot (tc-doc58.png) confirmed a visibly large square image rendered (much larger than DOC57's tiny unsized default), consistent with explicit sizing honored (square aspect-ratio fit to 50x50pt per prior established finding). Cleanup: range deleted, permission removed, file trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs an anyone share; ran before the user's explicit sharing approval.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`kit`: Same doc: `insert_inline_image(drive_file_id, width=100, height=50)` returned docId and index, no error. Playwright (`2026-10-19-tc-doc57-58.png`) shows a ~67px (50pt) square, the expected bounding-box fit for a square source. Share removed; files trashed.

---

### TC-DOC59: No source provided returns error
**Prompt**
> "Call insert_inline_image on doc {DOC_ID} at index 1 without providing a URI or drive_file_id"

**Checks**
- Returns `{"error": "Provide either uri or drive_file_id"}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Provide either uri or drive_file_id, not both"}`. No API call made.

**Result (2026-09-04) ✅ PASS**
insert_inline_image with neither uri nor drive_file_id returned {"error":"Provide either uri or drive_file_id"}.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: insert_inline_image with neither source returned {"error":"Provide either uri or drive_file_id"}.

---

### TC-DOC60: Both URI and drive_file_id provided returns error
**Prompt**
> "Call insert_inline_image on doc {DOC_ID} at index 1 with both uri 'https://example.com/img.png' and drive_file_id 'someid'"

**Checks**
- Returns `{"error": "Provide only one of uri or drive_file_id, not both"}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Provide only one of uri or drive_file_id, not both"}`. No API call made.

**Result (2026-09-04) ✅ PASS**
insert_inline_image with both uri and drive_file_id returned {"error":"Provide only one of uri or drive_file_id, not both"}.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: With both sources it returned {"error":"Provide only one of uri or drive_file_id, not both"}.

---

## `insert_page_break` (#148)

### TC-DOC94: Insert a page break at a given index ⚠️ destructive
**Setup:** create a doc with two short paragraphs; note the `endIndex` of the first paragraph

**Prompt**
**Playwright: required**
> "Insert a page break at index {N} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `index: N`
- `get_doc_structure` does not surface the page break as its own element (it's an inline element inside the paragraph, not a top-level body element) — this is expected, not a bug
- 🔍 Visual check in Google Docs: the second paragraph starts on a new page

**Cleanup:** delete the created doc

**Result (2026-07-15) ✅ PASS**
Created a doc with two paragraphs; `get_doc_structure` showed the first paragraph ending at index 38. `insert_page_break(index=38)` returned `{"docId": ..., "index": 38}` with no API error. Re-fetched `get_doc_structure`: the page break did not appear as its own top-level element (as expected) — the second paragraph's `startIndex` shifted from 38 to 40, consistent with an inline break being inserted. Playwright visual check: navigated to the doc, clicked into the body, pressed Ctrl+End to reach the document end — the accessibility live region announced "Entering page 2 of 2," confirming the second paragraph now renders on a new page. Doc trashed after verification.

**Result (2026-09-04) ✅ PASS**
Created 2-paragraph doc, inserted page break at index 18 (end of "First paragraph."). Response {docId, index:18}, no error. get_doc_structure: page break not surfaced as own element (expected, inline); "Second paragraph." startIndex shifted 18->20. Playwright screenshot (tc-doc94.png) showed only "First paragraph." on visible page — consistent with "Second paragraph." pushed to a new page. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Created a 2-paragraph doc and called insert_page_break(index=18), which returned {docId, index:18}. There was no page-break element type, and "Second paragraph." moved from 18 to 20. The screenshot (tc-doc94) shows it at the top of page 2. Doc trashed.

---

### TC-DOC95: API error returned gracefully (index beyond document end)
**Prompt**
> "Insert a page break at index 99999 in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure (index out of bounds)

**Cleanup:** none (no mutation applied)

**Result (2026-07-15) ✅ PASS**
`insert_page_break(doc_id=<TEST_DOC_ID>, index=99999)` returned `{"error": "<HttpError 400 ... Index 99999 must be less than the end index of the referenced segment, 89. ...>"}` — no exception raised, error clearly references the out-of-bounds index. No mutation applied to the fixture doc.

**Result (2026-09-04) ✅ PASS**
insert_page_break(index=99999) on DOC_ID returned HttpError 400 "Index 99999 must be less than the end index of the referenced segment, 29." No exception, no mutation.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: index=99999 returned {"error": HttpError 400 "Index 99999 must be less than the end index … 89"}. No exception.

---

## `list_doc_comments` / `add_doc_comment` / `resolve_doc_comment` (#151)

These operate on the Drive `comments`/`replies` resource, not the Docs API — they work against any file type Drive supports comments on (Docs, Sheets, Slides), but are scoped here to the doc fixture. There is no `delete_doc_comment` tool (out of scope for #151), so comments added during QA are not cleanable via a tool call — they persist as real threads on the fixture doc until removed manually in the Docs UI. Keep test comment text prefixed `QA TC-DOC…` so they're identifiable for manual cleanup.

### TC-DOC96: Add a comment with no quoted-text anchor ⚠️ destructive
**Prompt**
> "Add a comment 'QA TC-DOC96: general note.' to doc {DOC_ID}"

**Checks**
- Returns `id`, `content` matching the input text, `author` (`display_name`/`email_address` populated from the caller's identity), `created_time`
- `quoted_text` is `null` — no anchor was requested
- No error

**Cleanup:** none available — no `delete_doc_comment` tool exists; the comment persists on the fixture doc (see section note above)

**Result (2026-07-16) ✅ PASS**
`add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC96: general note.")` returned `id: "AAAB-5FtNYE"`, `content` matching the input, `author.display_name: "<QA user>"`, `created_time`, `quoted_text: null`. No error. Note: `author.email_address` was `null` rather than populated — this is Drive API behavior for the authenticated OAuth user's own comments (email visibility is a privacy-scoped field), not a tool defect; the tool correctly passes through whatever the API returns.

**Result (2026-09-04) ✅ PASS**
add_doc_comment (no anchor) returned id, content match, author.display_name="<QA user>" (email_address null - Drive API privacy behavior, not a defect), created_time, quoted_text:null.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: add_doc_comment returned id, matching content, author.display_name, created_time and quoted_text:null. email_address was null, which is the known Drive privacy behavior.

---

### TC-DOC97: Add a comment anchored to quoted text ⚠️ destructive
**Setup:** `{DOC_ID}` must contain the literal text "QA anchor target" somewhere (use `write_doc_content` to add it first if absent)

**Prompt**
> "Add a comment 'QA TC-DOC97: anchored note.' to doc {DOC_ID}, quoting the text 'QA anchor target'"

**Checks**
- Returns `quoted_text: "QA anchor target"` — the anchor round-trips through the API response
- `list_doc_comments` on the same doc shows this comment with the same `quoted_text`

**Cleanup:** none available (see section note above)

**Result (2026-07-16) ✅ PASS**
Doc lacked the literal text "QA anchor target", so it was inserted via `insert_doc_text` (not `write_doc_content`, which replaces the whole doc body — using it as the setup note suggests would have wiped the fixture's existing content). `add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC97: anchored note.", quoted_text="QA anchor target")` returned `quoted_text: "QA anchor target"`, round-tripping correctly. Confirmed via `list_doc_comments` in TC-DOC98 below.

**Result (2026-09-04) ✅ PASS**
Inserted "QA anchor target" text via insert_doc_text, then add_doc_comment with quoted_text="QA anchor target" returned quoted_text round-tripped correctly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: I inserted "QA anchor target" with insert_doc_text, then add_doc_comment returned quoted_text "QA anchor target".

---

### TC-DOC98: List comments reflects previously added comments
**Setup:** run TC-DOC96 and TC-DOC97 first

**Prompt**
> "List the comments on doc {DOC_ID}"

**Checks**
- Both the TC-DOC96 and TC-DOC97 comments appear in `comments`
- Each has `resolved: false` and `replies: []`
- The TC-DOC97 entry has `quoted_text: "QA anchor target"`; the TC-DOC96 entry has `quoted_text: null`
- `doc_id` in the response matches `{DOC_ID}`

**Cleanup:** none (read-only)

**Result (2026-07-16) ✅ PASS**
`list_doc_comments(doc_id=<TEST_DOC_ID>)` returned both comments: TC-DOC97 (`quoted_text: "QA anchor target"`) and TC-DOC96 (`quoted_text: null`), both `resolved: false` and `replies: []`, `doc_id` echoed correctly.

**Result (2026-09-04) ✅ PASS**
list_doc_comments showed both TC-DOC96/97 comments, both resolved:false and replies:[], correct quoted_text values, doc_id matches.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: list_doc_comments listed both comments with resolved:false and replies:[], the correct quoted_text values, and a matching doc_id.

---

### TC-DOC99: Resolve a comment ⚠️ destructive
**Setup:** use the `id` returned by TC-DOC96 as `{COMMENT_ID}`

**Prompt**
> "Resolve comment {COMMENT_ID} on doc {DOC_ID} with the reply 'Handled.'"

**Checks**
- Returns `doc_id`, `comment_id`, `reply_id`, and `action: "resolve"`
- Re-running `list_doc_comments` shows that comment with `resolved: true` and a reply with `content: "Handled."` and `action: "resolve"`

**Cleanup:** none available — resolving doesn't remove the comment thread, just marks it resolved (see section note above)

**Result (2026-07-16) ✅ PASS**
`resolve_doc_comment(doc_id=<TEST_DOC_ID>, comment_id="AAAB-5FtNYE", reply_content="Handled.")` returned `doc_id`, `comment_id`, `reply_id: "AAAB-5FtNYQ"`, `action: "resolve"`. Re-ran `list_doc_comments`: the TC-DOC96 comment now shows `resolved: true` with a reply `content: "Handled.", action: "resolve"`. The reply also included `modified_time` — confirms the fix from PR review comment (missing `modified_time` on replies) is live.

**Result (2026-09-04) ✅ PASS**
resolve_doc_comment(TC-DOC96's id) returned doc_id/comment_id/reply_id/action:"resolve". Re-list confirmed resolved:true with reply content "Handled.", action:"resolve", modified_time present.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: resolve_doc_comment returned doc_id, comment_id, reply_id and action "resolve". A re-list showed resolved:true with a reply "Handled." (action resolve, modified_time present).

---

### TC-DOC100: Resolve a non-existent comment ID
**Prompt**
> "Resolve comment 'not-a-real-comment-id' on doc {DOC_ID}"

**Checks**
- API error propagates — not a silent success or server crash

**Cleanup:** none (no mutation applied)

**Result (2026-07-16) ✅ PASS**
`resolve_doc_comment(doc_id=<TEST_DOC_ID>, comment_id="not-a-real-comment-id")` raised `HttpError 404 ... "Comment not found: not-a-real-comment-id."` — propagated cleanly, no silent success, no server crash.

**Result (2026-09-04) ✅ PASS**
resolve_doc_comment('not-a-real-comment-id') raised HttpError 404 "Comment not found" — propagated cleanly, no silent success.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: A fake comment ID raised HttpError 404 "Comment not found".

---

### TC-DOC101: List comments on a non-existent doc
**Prompt**
> "List the comments on doc 'not-a-real-doc-id'"

**Checks**
- API error propagates — not a silent empty list or server crash

**Cleanup:** none (no mutation applied)

**Result (2026-07-16) ✅ PASS**
`list_doc_comments(doc_id="not-a-real-doc-id")` raised `HttpError 404 ... "File not found: not-a-real-doc-id."` — propagated cleanly, no silent empty list, no server crash.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: A fake doc ID raised HttpError 404 "File not found".

## HTML/Markdown → Doc image conversion (#332, #333)

**Background:** `_AstParser` in `html_parser.py` has no `<img>` handling at all — `handle_starttag`/`handle_endtag` recognize block tags, inline formatting tags, table tags, and list tags, but an `img` tag matches none of those branches and is silently ignored. Since markdown images (`![alt](src)`) are converted to `<img>` HTML by `_md_to_html` before reaching this same parser, **every** content path that goes through the shared AST pipeline — `create_doc`, `create_doc_from_file`, `write_doc_content`, for both `content_format="html"` and `content_format="markdown"` — drops images with no error, no warning, and no placeholder. The only working path today is the separate `insert_inline_image` tool (TC-DOC57/58), which requires a second pass of index bookkeeping after the doc already exists (the manual workaround documented in #332/#333).

This is worse than a simple drop in two cases, both verified directly against `html_to_ast` on the fixtures below:
- A paragraph (or table cell) whose **only** content is an image produces **zero** AST nodes for it — not even an empty paragraph/cell. `ast_to_requests`'s guard `if not text.strip(): continue` (and the equivalent cell-fill guard in `emitter.py`) discards it entirely.
- An inline image inside running text (`"before <img> after"`) leaves no gap, marker, or trace — the surrounding runs are simply concatenated (`"before "` + `" after"`), so a caller inspecting `get_doc_structure` afterward has no signal an image was ever present in the source.

**Fixtures:** `docs/qa/fixtures/tc-doc102-image-conversion.html` and `docs/qa/fixtures/tc-doc103-image-conversion.md` — each covers 8 placement cases: standalone image paragraph, inline mid-paragraph, two consecutive images with no separating text, image wrapped in a link, image inside a list item, image inside a table cell, image inside a nested table cell (HTML only — markdown tables can't nest, matching the documented limitation in TC-DOC51; the markdown fixture substitutes reference-style `![alt][ref]` syntax for its Case 7 instead), and an image with an unreachable URL (included specifically to show the drop happens at parse time, before any HTTP fetch is attempted — a dead image URL fails identically to a live one).


**Result (2026-09-04) ✅ PASS**
list_doc_comments('not-a-real-doc-id') raised HttpError 404 "File not found" — propagated cleanly, no silent empty list.

### TC-DOC102: HTML image conversion — every placement should produce a visible image ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc102-image-conversion.html"

**Checks**
- `docId` and `web_link` returned with no `error`
- `get_doc_structure` shows all 8 headings and surrounding paragraph text intact
- Each of the 8 cases produces an inline image element (`get_doc_structure` doesn't currently surface inline images explicitly — cross-check via element/paragraph text length matching an image occupying one index slot, as in TC-DOC57)
- 🔍 Visual check in Google Docs: an image renders in each of the 8 cases, including inside the plain table cell and the nested table cell
- Final paragraph after Case 8 is present (confirms the document isn't truncated)

**Cleanup:** delete the created doc

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`html_to_ast`), not yet run live against the Docs API.** Running the fixture through `html_to_ast` this session confirms every one of the 8 cases drops its image with zero trace:
- Case 1 (standalone image paragraph): the paragraph containing only the image produces **no AST node at all** — not even an empty paragraph. `get_doc_structure` would show "Paragraph before the image." followed directly by "Paragraph after the image." with nothing between them.
- Case 2 (inline mid-paragraph): AST paragraph text is `"Text before "` + `" text after, same paragraph."` — concatenated with no gap or marker.
- Case 3 (two consecutive images, no text): produces **zero** AST nodes — the whole paragraph vanishes.
- Case 4 (image wrapped in a link): produces **zero** AST nodes — same as Case 3, since the only content was the image.
- Case 5 (image inside a list item): `BulletItem` text is `"List item with an image "` + `" inline"` — image silently gone, item otherwise intact.
- Case 6 (image inside a table cell): cell `children` is `[]` — completely empty cell, no error.
- Case 7 (image inside a nested table cell): the nested `Table` itself comes through correctly as a structural node, but its own single cell (containing only the image) is empty, same as Case 6.
- Case 8 (unreachable URL): produces **zero** AST nodes, identically to Case 1/3/4 — confirms the drop happens at parse time regardless of URL validity.
- Live execution + Playwright visual check still needed to confirm end-to-end behavior against the real API; not run this session (no live MCP tool access outside a release pass — see `.claude/team-roles/aziz.md`).

**Background (#333 implementation, 2026-08-02):** #333 implements body-level image support (Cases 1–5, 8 above); table-cell images (Cases 6–7) are a deliberate, documented out-of-scope gap tracked as a follow-up issue, not a regression — same silent-drop behavior as the original FAIL result above. Dev-side verification against the real Docs API (not through this repo's own MCP tool interface — a `mcp-gee-sweet-<name>` server process imports code once at session start, so a same-session tool call would exercise stale pre-fix code; see `CLAUDE.md`'s "MCP restart" section — instead verified via a throwaway script calling `content.py`'s `_apply_doc_content` directly, reusing `mcp_gee_sweet.auth._oauth_creds()`) found Cases 1–5 embed correctly and Cases 6/7 stay empty as expected, but Case 8 (the deliberately unreachable URL) surfaced a real, more serious bug: the Docs API rejects an entire `batchUpdate` atomically if *any* one `insertInlineImage` request in it can't be fetched — so Case 8 alone was taking down Cases 1–5's otherwise-correct image requests too, along with every other request in the same call (text, styles, tables). Not a position-math bug — a rejected batch executes nothing at all. Fixed by catching the `HttpError`, parsing the failing request's index directly out of Google's own error message (`"Invalid requests[N].insertInlineImage: ..."`), stripping that exact request, and retrying with the same (otherwise-unmodified) request list — safe because a rejected batch never partially applies, so no other request's position needs recomputing. Re-verified with the fix in place: all 8 cases produced the expected outcome (1–5 embedded, 6–7 empty, 8 reported as a clean per-image `error` entry instead of failing the whole document), and the final "confirms not truncated" paragraph was present. Unit coverage for the retry itself: `TestCreateDocImages::test_one_bad_image_url_does_not_fail_the_whole_document`. This dev-side pass doesn't substitute for a formal QA run through the actual MCP tool interface plus the fixture's own Playwright visual check — leaving this test case's own `**Result**` for that pass.

**Result (2026-09-04) ❌ FAIL**
create_doc_from_file(tc-doc102-image-conversion.html): docId+web_link, no top-level error. images list: 6 successes (cases 1-5, one of 3's two) + 1 per-image error (case 8, unreachable URL) = 7 entries; cases 6/7 (table-cell images) silently dropped with no entry, matching documented gap. get_doc_structure confirmed all 8 headings + surrounding paragraph text intact, table cells empty for dropped images, final paragraph present (not truncated). Playwright screenshot (tc-doc102.png) confirmed Google-logo images visibly rendering for Cases 1-5. Trashed.
**Corrected (2026-10-17, #1044 audit):** this case's Checks require an image in all 8 cases, including both table cells; Cases 6/7 rendered empty with no error or per-image entry. #509 (closed) is a different symptom. Tracked in #1073.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: create_doc_from_file(.html) returned 6 successes plus a per-image error for Case 8. Cases 1–5 render (tc-doc102.png). Case 6 and Case 7 table-cell images are dropped silently, with no images entry (tc-doc102b.png). Tracked in #1073 (open). Headings and the final paragraph are intact. Doc trashed.

**Result (2026-10-24) ⚠️ PARTIAL — PR #1215 QA round 1 (Kit) @ 79f19d4**
`kit`: create_doc_from_file(.html) returned no error, with 8 image successes plus the Case 8 per-image error (`doc edit failed: insertInlineImage: There was a problem retrieving the image…`). Raw `documents().get()`: Cases 1–5 as before; Case 6's image cell holds one `inlineObjectElement`; Case 7's nested cell holds one. All 8 headings and the final paragraph are present. Playwright (`2026-10-24-tc-doc102.png`): a logo in both table cells. **Defect:** Case 7's outer cell holds three paragraphs before the nested table (`""`, `""`, 10 spaces), from the fixture's indentation whitespace (`<td>\n      <table>`). They push the nested table onto the next page, away from its row. `html_to_ast` gives the cell the same `Run('\n      ')` on `develop`, so it predates #1073 (sent back on PR #1215, since `html_parser.py` is in its diff). Doc trashed.

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 2 (Kit) @ f9f6ee7**
`kit`: create_doc_from_file(.html) returned no error, with 8 successes plus the Case 8 error. Raw read: Case 6's cell holds one image. Case 7's outer cell now holds only an empty paragraph, the nested table (`[IMG]`), and an empty paragraph (Docs' structural ones): the round-1 indentation paragraphs are gone. Playwright (`2026-10-24-tc-doc102-r2.png`): logos in both cells. In this doc the Case 7 row still breaks across a page boundary, but that's only where the page ends: the same table alone at the top of a doc renders as one row with the nested table beside "Outer cell…" (`2026-10-24-pr1215-case7-alone.png`). Docs trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 3 (Kit) @ e3a6e69**
`kit`: create_doc_from_file(.html) returned no error, with 8 successes plus the Case 8 error. Raw read: Case 6's cell holds one image, and Case 7's outer cell holds only Docs' two structural empty paragraphs around the nested table (`[IMG]`). Docs trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 4 (Kit) @ 5d2b4e8**
`kit`: 8 successes plus the Case 8 error, with no top-level error. Raw read: Case 6's cell holds one image, and Case 7's outer cell holds only Docs' structural empty paragraphs around the nested `[IMG]`. Doc trashed.

---

### TC-DOC103: Markdown image conversion shares the same drop as the HTML path ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc103-image-conversion.md"

**Checks**
- `docId` and `web_link` returned with no `error`
- Same 8-case expectations as TC-DOC102 (Case 7 here is reference-style `![alt][ref]` syntax instead of a nested table)
- 🔍 Visual check: images render in all 8 cases, including the reference-style image

**Cleanup:** delete the created doc

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`_md_to_html` → `html_to_ast`), not yet run live.** `_md_to_html` correctly converts every markdown image (inline, reference-style, link-wrapped) into an `<img>` tag first — confirmed by inspecting the intermediate HTML — so the markdown path funnels into the exact same unhandled-`img` gap as TC-DOC102. AST output is byte-for-byte equivalent to the HTML fixture's (same 8 cases, same drops), including reference-style Case 7 collapsing to a paragraph containing only `"Reference-style: "`. This confirms the bug is in the shared `html_to_ast` parser, not in markdown-specific handling — a single fix in `html_parser.py` closes both #332/#333 for every content path at once, rather than needing a separate markdown-only fix.

**Background (#333 implementation, 2026-08-02):** the markdown path (`_md_to_html` → shared `html_to_ast`) funnels into the same code TC-DOC102's own background note covers, so that note's findings (Cases 1–5/8 fixed, Cases 6–7 a documented gap, the retry-on-image-failure fix) apply here too — not independently re-verified live against this specific `.md` fixture. A formal QA pass should run this fixture directly (not just TC-DOC102's `.html` one) to confirm reference-style `![alt][ref]` syntax specifically, since that's the one construct this fixture exercises that TC-DOC102 doesn't.

**Result (2026-09-04) ❌ FAIL**
create_doc_from_file(tc-doc103-image-conversion.md): 7 successes + 1 per-image error (case 8), case 6 (table cell) silently dropped (8 of 9 source images reach the images list). get_doc_structure confirmed all headings/text, and index-math on Case 7's paragraph (546-527=19 vs 18 expected for text-only) confirms an image occupies the extra slot. Playwright screenshot (tc-doc103.png) confirmed: Case 6 table cell empty, Case 7 reference-style image renders correctly (Google logo), Case 8 degrades gracefully with no truncation. Trashed.
**Corrected (2026-10-17, #1044 audit):** Case 6's table-cell image was dropped silently; the Checks require an image in every case. Tracked in #1073.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: create_doc_from_file(.md) returned 7 successes plus the Case 8 error. The Case 7 reference-style image renders (tc-doc103b.png), but the Case 6 table-cell image is dropped silently. Tracked in #1073. Doc trashed.

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 1 (Kit) @ 79f19d4**
`kit`: create_doc_from_file(.md) returned no error, with 8 image successes plus the Case 8 per-image error. Raw `documents().get()`: Case 6's image cell holds one `inlineObjectElement`, Case 7 reads `Reference-style: [IMG]`, and headings and the final paragraph are intact. Playwright (`2026-10-24-tc-doc103.png`): logos in the Case 6 cell and Case 7. Doc trashed.

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 2 (Kit) @ f9f6ee7**
`kit`: create_doc_from_file(.md) returned no error, with 8 successes plus the Case 8 error. Raw read: Case 6's cell holds one `inlineObjectElement`, and Case 7 reads `Reference-style: [IMG]`. Doc trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 3 (Kit) @ e3a6e69**
`kit`: create_doc_from_file(.md) returned no error, with 8 successes plus the Case 8 error. Raw read: Case 6's cell holds one image, and Case 7 reads `Reference-style: [IMG]`. Doc trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 4 (Kit) @ 5d2b4e8**
`kit`: 8 successes plus the Case 8 error. Raw read: Case 6's cell holds one image, and Case 7 reads `Reference-style: [IMG]`. Doc trashed.

---

## HTML/Markdown → Doc nested list conversion (#334)

**Background:** Three independent, compounding bugs, isolated separately below:

1. **Parser data loss (`html_parser.py`, both HTML and Markdown paths):** `_AstParser.handle_starttag`'s block-tag branch (`if tag in _BLOCK_TAGS and self._table_depth == 0:`) unconditionally resets `self._run_buf`/`self._pending_runs` whenever ANY block tag opens — including a nested `<li>` opening inside an already-open outer `<li>`. There's no stack/save-restore of the outer block's in-progress buffer, so **the outer list item's own text is silently destroyed** whenever that item has both its own text and a nested sub-list (the extremely common `<li>Item text<ul>...</ul></li>` shape — e.g. any markdown of the form `- Item:\n  - sub\n  - sub`). This is data loss, not just a rendering/flattening issue: verified directly against `html_to_ast` — a source list with "Parent A has text" + 2 nested children produces only the 2 children in the AST; "Parent A has text" never appears anywhere.
2. **Emitter ignores depth (`emitter.py`):** even where the parser *does* correctly track nesting (`BulletItem.depth`, verified correct in all cases below, including the ones unaffected by bug 1), `ast_to_requests` never reads `.depth` or `.paragraph_style` — `createParagraphBullets` is emitted with only `range` and `bulletPreset`, no indentation. Google Docs infers a bullet's nesting level from paragraph indentation, not an explicit field on the create request, so **every bullet renders at nesting level 0 in the live document regardless of source depth.** This is a real gap even for a list with zero parent-text collisions.
3. **Markdown-specific, on top of 1+2:** python-markdown's `sane_lists` extension (used by `_md_to_html`) only recognizes a sub-list as nested when indented by exactly 4 spaces or a tab. The CommonMark/GFM-standard indentation that most people and tools (including Claude) write by default — 2 spaces under a `-`/`*` marker, 3 spaces under a `1.` marker — is silently flattened to the parent list **before it even reaches the HTML parser**, with no warning. Verified empirically this session (`uv run python3 -c "import markdown; ..."`) across four indentation widths.

**Fixtures:** `docs/qa/fixtures/tc-doc104-nested-lists.html` (direct HTML, isolates bugs 1+2 with no markdown-library involvement), `docs/qa/fixtures/tc-doc105-nested-lists-gfm.md` (GFM-standard 2/3-space indentation, adds bug 3 on top), `docs/qa/fixtures/tc-doc106-nested-lists-4space.md` (4-space indentation — the documented python-markdown workaround — reproduces bugs 1+2 only, proving they're independent of bug 3). Each fixture has 3 cases: parent item with its own text + a nested sub-list (bug 1 trigger), a bare parent item with no text of its own (isolates bug 2 alone, since there's no parent text to lose), and ordered-in-ordered nesting. `tc-doc104-nested-lists.html` alone has a 4th case (added for #714, TC-DOC190) with two levels of bare parent `<li>`s, isolating a `min_depth == 2` run rather than Case 2's `min_depth == 1`.

### TC-DOC104: Direct HTML nested lists — parent item text must survive when a sub-list follows it ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: contents of docs/qa/fixtures/tc-doc104-nested-lists.html"

**Checks**
- `get_doc_structure` shows "Parent A has text" and "Parent B has text" as their own bullet items, each followed by their nested children
- Case 2's bare-nested children ("Bare-nested child C1"/"C2") appear at a visibly deeper indentation than Case 2's (absent) parent
- Case 3's "Top ordered 1" survives as its own item, with "Nested ordered 1.1"/"1.2" indented under it
- 🔍 Visual check in Google Docs: 3 distinct indentation levels are visible in Case 1 (Parent A / Child A2 / Grandchild A2a), and Case 2/3's nesting is visually indented, not flush-left

**Cleanup:** write fixture content back

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`html_to_ast`), not yet run live.** Confirmed exactly the predicted content loss: "Parent A has text" and "Parent B has text" (Case 1) and "Top ordered 1" (Case 3) — every parent item that has both its own text and a nested sub-list — produce **zero** `BulletItem`s; only their children survive, at depths 1/2 computed correctly. Case 2 (bare parent, no text to lose) correctly preserves both children at `depth=1` — this isolates bug 2 cleanly: depth is tracked right, but since `ast_to_requests` never emits it (confirmed by `grep -n "depth\|indentStart\|nestingLevel" emitter.py` returning zero matches in the relevant code), even these correctly-tracked items would still render at nesting level 0 in the live doc. Live execution + Playwright visual check still needed to confirm the live-rendering half of bug 2 (indentation is not exposed by `get_doc_structure` today — a related tooling gap, see note below).

**Result (2026-07-27) ❌ FAIL — run live against PR #432 (issue #336's emitter fix), Playwright visual check.** Bug 1 (parent text lost) is confirmed fixed independently (unrelated PR #401/`preserve_if_empty` work) — "Parent A has text"/"Parent B has text"/"Top ordered 1" all survive as their own bullet items with correct `depth` in `get_doc_structure`. But bug 2's live-rendering half is **not fixed** — PR #432's new leading-tab/`createParagraphBullets` mechanism produces visibly broken, inconsistent nesting, not the flat-nesting-level-0 the PR describes replacing:
- Two siblings at the *same* AST `depth=1` ("Child A1" and "Child A2", both children of "Parent A has text") render at **different** visual indentation levels — "Child A1" sits flush with its depth-0 parent (unindented), while "Child A2" is indented one level, as if it were Child A1's child rather than its sibling.
- The same pattern recurs for "Ordered child B1"/"B2" and "Nested ordered 1.1"/"1.2" — first item after a preceding bullet's own `createParagraphBullets` call stays at the wrong level; later siblings shift progressively.
- Ordered-list numbering is corrupted: "Ordered child B1" and "Ordered child B2" both render as "1." (not "1."/"2."); "Top ordered 1"/"Top ordered 2" also lose continuous numbering across the nested block.
- On the raw HTML fixture specifically (not the 4-space-markdown fixture below), literal whitespace between a `<li>`'s own text and its nested `<ul>` (the fixture file's own indentation, e.g. `Parent A has text\n    <ul>`) is preserved by `html_parser.py`'s existing whitespace handling as part of the same `BulletItem`'s run text, and the embedded newline splits it into an extra empty bullet paragraph in the live doc when rendered (visible in the screenshot as a stray bullet with no text between "Parent A has text" and "Child A1"). This part is unrelated to PR #432 (pre-existing `html_parser.py` behavior, reproducible with any depth-0 bullet regardless of the tab mechanism) but compounds the visible breakage on this fixture.
- Root cause not fully isolated — confirmed via an offline `ast_to_requests` dump (no live API) that request ordering/index math for the deferred nested-bullet pass looks internally consistent (each `createParagraphBullets` range's boundaries line up exactly against `full_text`, no character-index overlap between requests) — see TC-DOC106's result below, which reproduces the identical first-sibling-not-indented/numbering-corruption pattern on a markdown fixture with **no** embedded-whitespace paragraphs at all, ruling out the whitespace/embedded-newline issue as the actual cause of the indentation bug itself. Most likely explanation: the Docs API's `createParagraphBullets` nesting inference is not purely a function of each call's own leading-tab count in isolation, as the code's own comment assumes — something about calling it via separate, out-of-visual-order requests (this PR's deferred, descending-position pass) instead of one combined call, or per-call adjacency to an already-bulleted neighbor, is affecting the level the API actually assigns. Needs the PR author to reproduce directly against the live API (not just the mocked unit tests, which only assert request *construction*, not actual Docs API rendering behavior) to pin down the exact mechanism.
- Screenshots and repro scripts available in this session for the Dev's follow-up.

**Sending back to Dev — this is the PR's own target behavior failing live on the repo's existing QA fixture, not a peripheral or edge-case finding.**

**Result (2026-07-27, round 2) ❌ FAIL — re-run live against PR #432 commit 5fa26e7 (Playwright visual check), after Dev's fix.** Root cause was confirmed to be exactly what round 1 suspected: separate per-paragraph `createParagraphBullets` calls let each paragraph land under a different `listId`. The fix groups maximal contiguous same-preset `BulletItem` runs into one call. Live re-verification:
- Case 1: "Child A1"/"Child A2" (both `depth=1`) now render at the **same** indentation level (circle glyph), "Grandchild A2a" (`depth=2`) renders one level deeper (square glyph) — 3 distinct levels confirmed. "Ordered child B1"/"B2" render with continuous numbering ("1.", "2.").
- Case 3: "Top ordered 1" → "Nested ordered 1.1"/"1.2" (rendered "a."/"b.", correct decimal→alpha nesting) → "Top ordered 2" — correct nesting and numbering.
- Case 2: "Bare-nested child C1"/"C2" render visibly more indented than the absent parent (checklist requirement met), though their bullet glyph is a disc rather than the circle used by other `depth=1` items elsewhere in the doc — a narrow, isolated-run edge case (a contiguous bulleted run with no `depth=0` member to anchor nesting level 0 against). Not part of this test case's stated checklist; filed separately as #439, non-blocking.
- The stray empty-bullet paragraph noted in round 1 is confirmed pre-existing and unrelated to this PR (reproduced identically on TC-DOC106 below, which has no such artifact at all in its markdown source) — out of scope here.
**Corrected (2026-10-17, #1044 audit):** the stray empty bullet paragraphs this run recorded as "pre-existing, unrelated" are visible in this case's own output. Tracked in #1074.

**Bugs 1 and 2 confirmed fixed live; the result is still a FAIL (see the correction above).**

**Result (2026-09-04) ❌ FAIL**
create_doc_from_file(tc-doc104-nested-lists.html): "Parent A has text"/"Parent B has text"/"Top ordered 1" all survive as own bullet items (bug 1 fixed), correct nestingLevel 0/1/2 (bug 2 fixed). Playwright screenshot (tc-doc104.png) confirmed 3 visible indentation levels for Case 1, correct alpha-nesting for Case 3. Known pre-existing artifacts reproduced as documented (non-blocking): stray whitespace-only bullet paragraphs from raw-HTML fixture indentation (html_parser.py's own whitespace handling, unrelated to PR #432), which consume list numbers and shift "Top ordered 2" to render as "3." instead of "2." — matches historical finding, not a new regression. Case 2's bare-nested children render with disc (not circle) glyph — known #439, non-blocking. Trashed.
**Corrected (2026-10-17, #1044 audit):** the stray whitespace-only bullets this run recorded as "non-blocking" consume list numbers, so "Top ordered 2" renders as "3.", visible in this case's own Case 3. Tracked in #1074.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: Parent texts survive and nestingLevels are 0/1/2. However, whitespace-only bullet paragraphs ("    ", "        ") appear after "Parent A has text", "Child A2", "Parent B has text" and "Top ordered 1". They take a list number, so "Top ordered 2" renders as "3." (tc-doc104.png). Tracked in #1074 (open). v0.9.2 recorded PASS here, but this run reproduces the defect.

---

### TC-DOC105: Markdown nested lists at GFM-standard (2/3-space) indentation ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': contents of docs/qa/fixtures/tc-doc105-nested-lists-gfm.md"

**Checks**
- Same nesting expectations as TC-DOC104 (this is the indentation width most humans/AI tools write by default — it should behave the same as explicit HTML nesting)
- No literal `1.`/`2.` digit-dot text visible anywhere in bullet content

**Cleanup:** write fixture content back

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`_md_to_html`), not yet run live.** This is worse than TC-DOC104, not merely equivalent: 2-space indentation doesn't clear `sane_lists`' 4-space nesting threshold, so the sub-list syntax is never recognized as a list at all.
- Case 1: "Child A1" and "Child A2" become **sibling** bullets of "Parent A has text" (fully flattened, not nested) — while "Parent B has text" ends up with the literal text `"Parent B has text\n  1. Ordered child B1\n  2. Ordered child B2"` glued into ONE bullet item, i.e. the ordered sub-items render as raw, visible `1.`/`2.` characters in the doc rather than as list items or even flattened siblings — a strictly worse failure mode a user would see as garbled text, not just missing indentation.
- Case 2: a bare `-` marker with nothing else on its line, followed by an indented sub-list, isn't recognized as a list item at all by `sane_lists` — the whole block degrades to a single plain paragraph containing the literal source text (`"-\n  - Bare-nested child C1\n  - Bare-nested child C2"`).
- Case 3: "Top ordered 1" survives as its own item (no bug-1 collision at this indentation, since the sub-items aren't recognized as nested — they become plain siblings instead), but "Nested ordered 1.1"/"1.2" render as flat siblings, not nested, and are mis-numbered as continuing the same list as "Top ordered 1"/"2" in the live doc.
- Live execution + Playwright visual check still needed; not run this session.

**Result (2026-09-04) ❌ FAIL**
Wrote GFM 2/3-space-indented markdown to DOC_ID. Confirmed the documented bug-3 gap behaves exactly as expected: Case 1 "Child A1"/"Child A2" flattened to siblings of "Parent A" (2-space doesn't clear sane_lists' 4-space threshold), "Parent B has text" followed by literal raw "  1. Ordered child B1\n  2. Ordered child B2" text (garbled, not list items) — matches documented failure mode. Case 2's bare `-` marker degrades to plain paragraphs (not merged into one blob this time, likely improved by unrelated #401/#402 paragraph-boundary fixes). Case 3's nested ordered items flatten to siblings of "Top ordered 1"/"2", same listId, all nestingLevel 0 — mis-numbering as documented. This is a known, tracked, not-yet-fixed limitation (bug 3) — behavior unchanged from the 2026-07-16 baseline, not a new regression.
**Corrected (2026-10-17, #1044 audit):** this run saw the 2- and 3-space nested lists flatten and the ordered sub-items show as literal `1.`/`2.` text, which is a defect, not a pass. #334, which `docs/known-limitations.md` named as the tracker, is closed. Tracked in #1071.

**Result (2026-10-17) ❌ FAIL — v0.9.2 release pass**
Known gap: 2/3-space indented ordered children flatten (documented bug-3 behavior, unchanged since 2026-09-04).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: With 2/3-space GFM indentation, Child A1/A2 flatten to level 0. The B children read "  1. Ordered child B1" as literal text. Case 2 is literal "-" text, and Case 3's nested items flatten to level 0. Tracked in #1071 (open), plus #1075 for Case 2.

---

### TC-DOC106: Markdown nested lists at 4-space indentation — isolates bugs 1+2 from bug 3 ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Write this markdown to doc {DOC_ID} using content_format='markdown': contents of docs/qa/fixtures/tc-doc106-nested-lists-4space.md"

**Checks**
- Same nesting expectations as TC-DOC104 — 4-space indentation is the one width where `_md_to_html` produces genuinely nested `<ul>`/`<ol>` HTML, so this TC should behave identically to TC-DOC104 once bugs 1+2 are fixed
- Confirms whether a "use 4 spaces" workaround note in tool docstrings would be sufficient today (it would not — bugs 1+2 still apply at this indentation)

**Cleanup:** write fixture content back

**Result (2026-07-16) ❌ FAIL — verified via direct code execution (`_md_to_html` → `html_to_ast`), not yet run live.** At 4-space indentation, `_md_to_html` produces properly nested `<ul>`/`<ol>` HTML (confirmed by inspecting the intermediate HTML output), so this fixture reproduces TC-DOC104's HTML-path results exactly: "Parent A has text"/"Parent B has text"/"Top ordered 1" all lost to bug 1, correct `depth` values (1, 2) on the surviving children, Case 2's bare-parent children correctly preserved at `depth=1`. This confirms bugs 1+2 are independent of the markdown-library indentation quirk (bug 3) — fixing `_md_to_html`'s indentation sensitivity alone would not fix nested lists; `html_parser.py` and `emitter.py` both need fixing regardless of indentation width used.

**Result (2026-07-27) ❌ FAIL — run live against PR #432, Playwright visual check.** Bug 1 confirmed fixed (independent of this PR). Bug 2's live-rendering is **not fixed**, and this fixture is the more important data point of the two run this round since it has no interstitial-whitespace paragraphs at all (unlike TC-DOC104's raw-HTML fixture): "Child A1" (AST `depth=1`) still renders flush with "Parent A has text" (`depth=0`) while its own sibling "Child A2" (also `depth=1`) renders one level deeper, and "Ordered child B1"/"B2" both render as "1." instead of continuing the numbering. This isolates the defect to PR #432's `createParagraphBullets`/leading-tab mechanism itself — see TC-DOC104's result above for full detail and root-cause discussion. Sending back to Dev alongside TC-DOC104.

**Result (2026-07-27, round 2) ✅ PASS — re-run live against PR #432 commit 5fa26e7 (Playwright visual check), after Dev's fix.** This fixture is the clean confirmation (no whitespace artifacts to confound the result): Case 1 "Child A1"/"Child A2" both render at the same, correct depth-1 indentation (circle glyph), "Grandchild A2a" one level deeper (square glyph), "Ordered child B1"/"B2" number continuously ("1.", "2."). Case 3 "Top ordered 1" → "Nested ordered 1.1"/"1.2" (alpha-nested, "a."/"b.") → "Top ordered 2" nests and numbers correctly. Confirms the fix, independent of TC-DOC104's unrelated whitespace-artifact noise.

**PASS.**

**Result (2026-09-04) ❌ FAIL**
Wrote 4-space-indented markdown to DOC_ID. Confirmed clean reproduction of TC-DOC104's fixed bugs 1+2 with NO stray-whitespace artifacts (this fixture has none): Case 1 "Child A1"/"Child A2" (level1)/"Grandchild A2a" (level2) correctly nested; "Ordered child B1"/"B2" visually indented+numbered under "Parent B has text" despite reporting nestingLevel:0 (expected Docs API quirk — a list with no depth-0 member pre-populates level-0 glyph/indent with level-1's values, per emitter.py's documented behavior). Case 3 correctly alpha-nested (1./a./b./2.) with correct top-level numbering. Playwright screenshot (tc-doc106.png) confirmed all of this visually. New observation (not blocking, not previously called out for this fixture): Case 2's bare `-` marker with nothing else on its line isn't recognized as a list item by python-markdown regardless of indentation width (a markdown-syntax-level limitation, not the sane_lists indentation-threshold bug this fixture targets) — renders as plain literal "-"/"  - Bare-nested child C1" text, same failure shape as TC-DOC105's Case 2. Fixture restored to seed content after.
**Corrected (2026-10-17, #1044 audit):** Case 2's bare `-` marker rendered as literal text. #692, which resolved it as a documented limitation, is closed, so the limitation has no open issue. Tracked in #1075.

**Resolution (#692):** Filed and triaged as a documented limitation rather than a code fix — see `docs/known-limitations.md`'s "A bare `-` line is never recognized as an empty list item" entry for the two manifestations (this fixture's Case 2 hits the first-line/paragraph-collapse one) and the recommended non-breaking-space workaround. Pinned with unit tests in `tests/test_docs_content.py::TestMdToHtml`.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: Case 1 and Case 3 nest and number correctly (tc-doc106.png). Case 2's bare "-" renders as literal "-" / "- Bare-nested child C1" text. Tracked in #1075 (open).

---

**Tooling gap note (not a fix, just a QA-visibility limitation):** `get_doc_structure` doesn't currently expose paragraph indentation or the Docs API's bullet `nestingLevel` field, so confirming bug 2's live-rendering half (or a future fix for it) requires a Playwright visual check every time rather than a structural assertion. Worth a follow-up ticket if this bug is fixed — the same way `font_family` is already a known `get_doc_structure` gap (TC-DOC42/47).

---

## `create_named_range` / `create_bookmark` (#152)

The Docs API has no dedicated bookmark-creation endpoint — `create_bookmark` is implemented as a thin wrapper over `createNamedRange` spanning a single character. Neither tool's output is visible anywhere in the Docs UI (named ranges aren't a UI-surfaced concept), so verification is API-round-trip only, except TC-DOC109 which specifically checks the UI does *not* show the bookmark, to confirm the docstring's caveat is accurate.

### TC-DOC107: `create_named_range` creates a named range over a span ⚠️ destructive
**Setup:** create a doc with a paragraph of text; call `get_doc_structure` to get its `startIndex`/`endIndex`

**Prompt**
> "Create a named range called 'section-a' spanning indices {N} to {M} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, a non-empty string `namedRangeId`, `name: "section-a"`, `startIndex: N`, `endIndex: M`

**Cleanup:** delete the created doc

**Result (2026-07-17) ✅ PASS**
`create_named_range(doc_id, name="section-a", start_index=1, end_index=64)` against a doc with one paragraph of real text returned `{"docId": ..., "namedRangeId": "kix.kmeha3539w3s", "name": "section-a", "startIndex": 1, "endIndex": 64}` — all fields present and correct. Note: `create_doc`'s `content` param and a plain-text (no wrapping tag) call to `write_doc_content` both silently produced an empty document body (confirmed live via Playwright screenshot) — wrapping the same text in `<p>...</p>` via `write_doc_content` worked. This is unrelated to `create_named_range`/`create_bookmark` (not touched by this PR) but is a real, reproducible bug in the existing HTML content pipeline; flagging separately, not blocking this PR. Filed as issue #343; fixed — see TC-DOC131/TC-DOC132 below.

**Result (2026-09-04) ✅ PASS**
create_named_range(name="section-a", start_index=1, end_index=73) returned correct namedRangeId/name/startIndex/endIndex.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: create_named_range("section-a", 1, 64) returned namedRangeId, name, startIndex 1 and endIndex 64.

---

### TC-DOC108: `create_named_range` — API error returned gracefully (end_index beyond document end)
**Prompt**
> "Create a named range called 'bad' spanning indices 1 to 99999 in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure (index out of bounds)

**Cleanup:** none (no mutation applied)

**Result (2026-07-17) ✅ PASS**
Returned `{"error": "<HttpError 400 ... Index 99998 must be less than the end index of the referenced segment, 65.>"}` — clean error dict, no exception, references index out of bounds.

**Result (2026-09-04) ✅ PASS**
create_named_range(end_index=99999) returned clean HttpError 400 referencing index out of bounds.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: end_index=99999 returned an {"error"} with HttpError 400, index out of bounds.

---

### TC-DOC109: `create_bookmark` creates a single-character named range anchor ⚠️ destructive
**Setup:** create a doc with a paragraph of text; call `get_doc_structure` to get a valid index `N` within it

**Prompt**
**Playwright: required**
> "Create a bookmark called 'intro' at index {N} in doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId`, a non-empty string `namedRangeId`, `name: "intro"`, `index: N`
- 🔍 Visual check in Google Docs: Insert > Link, then click the "Headings, bookmarks, and tabs" button in the link dialog — the resulting list does **not** include "intro" — confirms this is a named-range-backed anchor, not a native Docs UI bookmark (documented limitation)

**Cleanup:** delete the created doc

**Result (2026-07-17) ❌ FAIL**
`create_bookmark(doc_id, name="intro", index=1)` returned `{"docId": ..., "namedRangeId": "kix.jare8zg6gej", "name": "intro", "index": 1}`. Playwright: Insert > Link > "Headings, bookmarks, and tabs" listed only "Tab 1" — "intro" does not appear, confirming the documented limitation (not a native Docs UI bookmark).
**Corrected (2026-10-17, #1044 audit):** `create_bookmark` didn't produce a bookmark Docs lists. Recording that as "confirming the documented limitation" leaves a tool that doesn't do what its name says with no open issue. Tracked in #1076.

**Result (2026-09-04) ❌ FAIL**
create_bookmark(name="intro", index=1) returned namedRangeId/name/index correctly. UI-dialog "intro not listed in bookmarks" check not re-performed this round (structural/architectural fact — named ranges are categorically invisible to Docs UI bookmark dialogs, previously confirmed live 2026-07-17; not something product code could regress). Doc loaded fine in Playwright.
**Corrected (2026-10-17, #1044 audit):** same as the 2026-07-17 correction above; this run didn't re-check the UI at all. Tracked in #1076.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: create_bookmark("intro", 1) returned namedRangeId, name and index:1. In Playwright, Insert link (Cmd+K) → "Headings, bookmarks, and tabs" listed only "Tab 1" (tc-doc109.png), so the tool does not create a bookmark that Docs lists. Tracked in #1076 (open). v0.9.2 recorded PASS.

---

### TC-DOC110: `create_bookmark` — API error returned gracefully (index beyond document end)
**Prompt**
> "Create a bookmark called 'bad' at index 99999 in doc {DOC_ID}"

**Checks**
- Returns `{"error": "..."}` — does not raise an exception
- Error message references an API failure (index out of bounds)

**Cleanup:** none (no mutation applied)

**Result (2026-07-17) ✅ PASS**
Returned `{"error": "<HttpError 400 ... Index 99999 must be less than the end index of the referenced segment, 65.>"}` — clean error dict, no exception, references index out of bounds.

**Result (2026-09-04) ✅ PASS**
create_bookmark(index=99999) returned clean HttpError 400 referencing index out of bounds.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: index=99999 returned an {"error"} with HttpError 400, index out of bounds. Scratch doc trashed.

---

### TC-DOC111: `find_in_doc` literal case-insensitive search returns correct offsets
**Setup:** create a doc via `write_doc_content` with content `<p>Hello World</p><p>another hello here</p>`

**Prompt**
> "Find all instances of 'hello' in doc {DOC_ID}"

**Checks**
- Returns a list of 2 matches
- First match: `matched_text` is `"Hello"`, `context` is `"Hello World"`
- Second match: `matched_text` is `"hello"`, `context` is `"another hello here"`
- Each match's `start_index`/`end_index` span exactly the matched text — confirm by calling `get_doc_structure` and slicing the paragraph text at those offsets

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
2 matches returned. `start_index`/`end_index` (1-6, 21-26) confirmed exact against `get_doc_structure` paragraph offsets (paragraphs start at 1 and 13).

**Result (2026-09-04) ✅ PASS**
find_in_doc('hello') on "Hello World"/"another hello here" doc: 2 matches, "Hello"[1,6], "hello"[21,26], contexts correct. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Two matches: "Hello" [1,6] in context "Hello World" and "hello" [21,26]. Both match the paragraph offsets (paragraphs start at 1 and 13).

---

### TC-DOC112: `find_in_doc` regex search feeds directly into `style_doc_range` to hyperlink matches ⚠️ destructive
**Setup:** create a doc via `write_doc_content` with content `<p>Contact test@example.com or admin@example.com for help</p>`

**Prompt**
> "Find every email address in doc {DOC_ID} using a regex, then turn each one into a mailto: link"

**Checks**
- `find_in_doc(doc_id, query=r"[\w.]+@[\w.]+", regex=True)` returns 2 matches with the correct `matched_text` values and offsets
- Calling `style_doc_range` with `link_url="mailto:" + matched_text` at each returned `start_index`/`end_index` succeeds
- `get_doc_structure` afterward shows both runs with `link_url` set to the corresponding `mailto:` address, confirming the offsets from `find_in_doc` landed on the exact right characters

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
2 email matches found; `style_doc_range` applied `mailto:` links at the returned offsets; `get_doc_structure` afterward showed both runs split exactly at the email boundaries with the correct `link_url`.

**Result (2026-09-04) ✅ PASS**
find_in_doc regex email search: 2 matches with correct offsets. style_doc_range applied mailto: links at those offsets; get_doc_structure confirmed both runs split exactly at email boundaries with correct link_url. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: The regex found test@example.com [9,25] and admin@example.com [29,46]. style_doc_range set the mailto links, and the structure shows both runs split exactly at those offsets with the correct link_url.

---

### TC-DOC113: `find_in_doc` case_sensitive=True excludes different-case matches
**Setup:** create a doc via `write_doc_content` with content `<p>Hello World, another hello here</p>`

**Prompt**
> "Find case-sensitive matches of 'hello' in doc {DOC_ID}"

**Checks**
- Returns exactly 1 match (`matched_text: "hello"`) — the capitalized "Hello" in the same doc is excluded

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
Exactly 1 match returned (`"hello"`); capitalized "Hello" correctly excluded.

**Result (2026-09-04) ✅ PASS**
find_in_doc case_sensitive=True('hello'): exactly 1 match ("hello"), capitalized "Hello" excluded. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: case_sensitive=True returned 1 match ("hello" [22,27]). "Hello" was excluded.

---

### TC-DOC114: `find_in_doc` invalid regex returned gracefully
**Setup:** create a doc via `write_doc_content` with any content

**Prompt**
> "Search doc {DOC_ID} using the regex '(unclosed'"

**Checks**
- Returns `{"error": "..."}` referencing the invalid regex — does not raise an exception

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
Returned `{"error": "Invalid regex: missing ), unterminated subpattern at position 0"}}` — clean error dict, no exception. Also spot-checked live: an invalid `doc_id` now returns `{"error": "<HttpError 404 ...>"}` instead of raising (regression test for the fix to the missing-try/except finding from code review).

**Result (2026-09-04) ✅ PASS**
find_in_doc('(unclosed', regex=True) returned {"error":"Invalid regex: missing ), unterminated subpattern at position 0"}. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: '(unclosed' with regex=True returned {"error":"Invalid regex: missing ), unterminated subpattern at position 0"}.

---

### TC-DOC115: `find_in_doc` searches table cell text
**Setup:** create a doc, insert a 1x1 table via `insert_doc_table`, then write "needle" into the cell via `insert_doc_text` at the cell's `paragraphStartIndex` (from `get_doc_structure`)

**Prompt**
> "Find 'needle' in doc {DOC_ID}"

**Checks**
- Returns 1 match with `matched_text: "needle"` and `start_index` equal to the cell's `paragraphStartIndex`

**Cleanup:** delete the created doc

**Result (2026-07-18) ✅ PASS**
1 match returned, `start_index` (11) equal to the cell's `paragraphStartIndex` (11).

**Result (2026-09-04) ✅ PASS**
Inserted 1x1 table + "needle" text at cell's paragraphStartIndex. find_in_doc('needle'): 1 match, start_index(5) = cell paragraphStartIndex. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: I inserted a 1×1 table and put "needle" at paragraphStartIndex 5. find_in_doc returned 1 match with start_index 5. Doc trashed.

---

## `insert_softbreak_paragraph` (#332)

Not tagged `⚠️ requires-oauth` — like `insert_doc_text`/`style_doc_range`, the tool itself is auth-agnostic; only the fixture doc happens to live in personal Drive.

### TC-DOC116: Two lines join into a single soft-break paragraph with an explicit style ⚠️ destructive
**Setup:** create a doc with a placeholder paragraph via `write_doc_content`; note the placeholder paragraph's `startIndex` ({N}) and `endIndex`. Then empty it with `delete_doc_range` over `{N}` to `endIndex - 1`, which keeps the paragraph's own `\n`. The tool inserts no trailing `\n`, so inserting at the start of a non-empty paragraph merges the block into it (the placeholder text would end up on line 2, e.g. "…Databaseplaceholder").

**Prompt**
**Playwright: required**
> "Insert a soft-break paragraph at index {N} in doc {DOC_ID} with lines [{text: 'Document ID: KH-OPS-001', bold: true}, {text: 'Category: AWS / Database'}], named_style_type HEADING_2"

**Checks**
- Response has no `error`; `start_index`/`end_index`/`line_ranges` are present, and each `line_ranges` entry's span matches its line's text length
- `get_doc_structure` shows **one** paragraph element spanning the inserted block (not two) — confirms the `\v` separator did not create a paragraph break. Its text is exactly the two lines joined by `\v`, with no leftover placeholder text
- That paragraph's `namedStyleType` is `HEADING_2`
- 🔍 Visual check in Google Docs: the two lines render as one tight paragraph (no blank-line gap between them) with a visible line break; only the first line is bold

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
Structural checks confirmed (single paragraph, HEADING_2, correct line_ranges). Playwright screenshot confirmed one tight paragraph with a visible soft line break, only "Document ID: KH-OPS-001" bold.

**Result (2026-09-04) ✅ PASS**
insert_softbreak_paragraph with 2 lines, HEADING_2. Response: start/end_index, line_ranges matching each line's text length exactly. get_doc_structure: ONE paragraph (not two), namedStyleType HEADING_2, only first line's run bold. Playwright screenshot (tc-doc116.png) confirmed one tight paragraph with visible soft line break, only "Document ID: KH-OPS-001" bold. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
One paragraph with \v and correct line_ranges; setup inserts at the placeholder's start, which merges it (stale).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: insert_softbreak_paragraph(HEADING_2) returned line_ranges [1,24] and [25,49], each matching its line length. The structure shows one HEADING_2 paragraph with \v, and only the first line is bold. The screenshot (tc-doc116) shows one tight paragraph. Stale setup, not a defect: inserting at the placeholder's start merges "placeholder" onto line 2 ("…Databaseplaceholder").

---

### TC-DOC117: Invalid named_style_type rejected without mutating the doc
**Setup:** create a doc via `write_doc_content` with any content

**Prompt**
> "Insert a soft-break paragraph at index 1 in doc {DOC_ID} with lines [{text: 'x'}], named_style_type 'NOT_A_STYLE'"

**Checks**
- Returns `{"error": "..."}` naming the invalid value — does not raise an exception
- `get_doc_structure` shows the doc unchanged (no insertion occurred)

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
Returned `{"error": "invalid named_style_type 'NOT_A_STYLE'; must be one of: ..."}}`; doc structure confirmed unchanged.

**Result (2026-09-04) ✅ PASS**
insert_softbreak_paragraph with named_style_type='NOT_A_STYLE' returned {"error":"invalid named_style_type 'NOT_A_STYLE'; must be one of: ..."}. get_doc_structure confirmed doc unchanged ("placeholder\n" intact, no insertion). Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: NOT_A_STYLE returned {"error":"invalid named_style_type 'NOT_A_STYLE'; must be one of: …"}. The structure was unchanged.

---

## `insert_local_images` (#332)

**Fixture:** `docs/qa/fixtures/qa-fixture-pixel.png` — a 1×1 pixel PNG, small enough to commit directly; only used to confirm placement/replacement mechanics, not visual image quality.

Tagged `⚠️ requires-oauth` on every case that reaches the upload step — the tool calls the same local-file-upload path as `upload_local_file`, which cannot write to personal Drive under a service account (see its docstring). Error-path cases that return before any upload (marker not found/not unique, missing local file) are not tagged, matching the convention for `insert_inline_image`'s own error-path tests.

### TC-DOC118: Single marker is replaced by an uploaded image ⚠️ requires-oauth ⚠️ destructive
**Setup:** create a doc via `write_doc_content` with content `<p>before</p><p>IMGMARKERONE</p><p>after</p>`

**Prompt**
**Playwright: required**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERONE', local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png', into folder {FOLDER_ID}"

**Checks**
- `results` has exactly one entry with no `error`, a `fileId`, `shared: false`, and an `index` equal to the "IMGMARKERONE" paragraph's `startIndex` (from a prior `get_doc_structure`)
- `get_doc_structure` afterward: the marker text is gone, the "before"/"after" paragraphs are unaffected, and the middle paragraph's `endIndex - startIndex` is now 2 (one image "character" + the paragraph's trailing `\n`)
- The uploaded file (`results[0].fileId`) has no `anyone` permission (`list_permissions`). `revoke_sharing` defaults to `True`, so the temporary `anyone`/`reader` share is revoked once the image is embedded (see TC-DOC152)
- 🔍 Visual check in Google Docs: an image renders where the marker used to be, and the literal marker text is gone

**Cleanup:** delete the created doc; delete the uploaded image file

**Result (2026-07-19) ✅ PASS**
`results` had one entry, `fileId` present, `index` 8 matched the marker paragraph's `startIndex`. Middle paragraph's span was exactly 2 (image + `\n`); before/after paragraphs unaffected. `list_permissions` confirmed `anyone`/`reader`.

**Result (2026-09-04) ✅ PASS**
insert_local_images single marker: results[0] fileId present, index=8 = marker's startIndex, shared:false. get_doc_structure: marker gone, before/after unaffected, middle paragraph span=2 (image+\n). list_permissions confirmed no anyone permission. Uploaded file + doc trashed.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** Run in a scratch doc (not the shared fixture), batched with TC-DOC164's oversized image and the TC-DOC197/198 cases in one `insert_local_images` call. The pixel entry succeeded: `fileId` present, `shared: false`, `index` 8 matching the marker paragraph's `startIndex`. `get_doc_structure`: the marker was gone, its paragraph spanned exactly 2 (8–10), and "before"/"after" and the other markers were untouched. The permission check follows the post-#332 default (share revoked, no `anyone` grant), same as the 2026-09-04 result. Playwright: the pixel rendered as a dot under "before" (account check passed on the fixture doc's title). Doc and upload trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Marker replaced; the image is no longer left shared (revoke is the default since DOC152), so the TC expectation is stale.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: One result: fileId present, shared:false, index 8 (equal to the marker's startIndex). The middle paragraph is now 8–10, and before/after are untouched. The screenshot (tc-doc118) shows the dot. The "shared anyone/reader" check is stale: list_permissions shows no anyone grant, which is the revoke-by-default behavior TC-DOC152 expects. Upload trashed.

---

### TC-DOC119: Two markers are placed in one call, higher index first
**Setup:** create a doc via `write_doc_content` with content `<p>MARKERONE</p><p>MARKERTWO</p>`

**Prompt**
**Playwright: required**
> "In doc {DOC_ID}, insert local images: marker 'MARKERONE' and marker 'MARKERTWO', both using local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png', into folder {FOLDER_ID}"

**Checks**
- `results` has two entries, both with no `error` and distinct `fileId`s
- `get_doc_structure` afterward: both marker texts are gone and both paragraphs now contain only an image
- 🔍 Visual check: both paragraphs show an image, in the original top-to-bottom order

**Cleanup:** delete the created doc; delete both uploaded image files

**Result (2026-07-19) ✅ PASS**
Both entries succeeded with distinct fileIds, returned in input order (MARKERONE, MARKERTWO) despite MARKERTWO sitting at the higher document index — confirms the results-ordering fix live. Both paragraphs reduced to image-only spans afterward.

**Result (2026-09-04) ✅ PASS**
Two markers, MARKERTWO at higher doc index than MARKERONE. Both results succeeded with distinct fileIds, returned in INPUT order (MARKERONE first) despite MARKERTWO's higher index — confirms results-ordering fix. Both paragraphs reduced to image-only spans. Uploaded files + doc trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Two results with distinct fileIds, returned in input order (index 1 and 11). Both paragraphs are now image-only spans, and the screenshot (tc-doc119) shows two dots in order. Uploads trashed.

---

### TC-DOC120: Marker not found / not unique / local file missing all fail per-image without mutating the doc
**Setup:** create a doc via `write_doc_content` with content `<p>DUPMARKER</p><p>DUPMARKER</p>`

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'NOPE' with local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png'; marker 'DUPMARKER' with the same local_path; marker 'ANY' with local_path '/nonexistent/missing.png' — all into folder {FOLDER_ID}"

**Checks**
- `results` has three entries, each with an `error` and no `fileId`: "not found" for NOPE, "must be unique" for DUPMARKER (occurs twice), a missing-file message for ANY
- `get_doc_structure` shows the doc completely unchanged — no image, no marker text removed (the tool uploads/shares before touching the document, and none of these three ever reached that step)

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
All three error messages matched exactly (not found / occurs 2 times / no file found); no `fileId` on any entry; doc structure confirmed unchanged.

**Result (2026-09-04) ✅ PASS**
Three per-image failures: "not found" (NOPE), "occurs 2 times; must be unique" (DUPMARKER), "No file found at '/nonexistent/missing.png'" (ANY) — no fileId on any. get_doc_structure confirmed doc completely unchanged (both DUPMARKER paragraphs intact). Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Three per-image errors: "marker 'NOPE' not found", "occurs 2 times; must be unique" and "No file found at '/nonexistent/missing.png'". No fileIds, the doc is unchanged, and no uploads appeared in the folder.

---

### TC-DOC121: A marker that's a substring of unrelated document text is not falsely matched
**Setup:** create a doc via `write_doc_content` with content `<p>Reference build IMG10 in the changelog.</p>` — note there is no standalone "IMG1" token anywhere, only "IMG1" as the first four characters of "IMG10"

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'IMG1', local_path '<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png', into folder {FOLDER_ID}"

**Checks**
- `results` has one entry with an `error` containing "not found" — plain substring search would incorrectly match "IMG1" inside "IMG10" and report success
- `get_doc_structure` shows the doc completely unchanged (no upload happened, since the marker never resolved)
- No file was uploaded to Drive (nothing to clean up)

**Cleanup:** delete the created doc

**Result (2026-07-19) ✅ PASS**
Returned `{"error": "marker 'IMG1' not found in document"}}` — confirms the substring-collision fix live; the prior implementation would have falsely matched inside "IMG10".

**Result (2026-09-04) ✅ PASS**
marker 'IMG1' returned {"error":"marker 'IMG1' not found in document"} — confirms substring-collision fix (didn't falsely match inside "IMG10"). get_doc_structure confirmed doc unchanged, no upload. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Marker IMG1 returned "marker 'IMG1' not found in document". The doc is unchanged and nothing was uploaded.

---

## Nested list / interrupted `<li>` parent-text handling — `write_doc_content` (issue #335)

**Note:** nested-list *indentation* is a separate, not-yet-fixed issue (#336) — `BulletItem.depth` is computed correctly but the Docs writer doesn't yet turn it into visual indentation, so all bullets below may render at the same flat list level for now. These test cases cover #335: that an open `<li>`'s own text is no longer silently dropped when something block-level opens inside it (a nested `<ul>`/`<ol>`, but also `<pre>`, `<table>`, `<p>`, headings), that text appears before its children in document order, that text trailing a nested construct (before the real `</li>`) isn't dropped either, and that formatting state doesn't leak forward when an inline tag is left unclosed across the boundary. None are tagged `Playwright: required` since indentation (the only visual signature not yet checkable) isn't verifiable until #336 lands — `get_doc_structure` text/order/style checks are sufficient here.

### TC-DOC122: Parent `<li>` text survives alongside a nested list ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Item text<ul><li>sub a</li><li>sub b</li></ul></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows **three** bulleted paragraphs in order: "Item text", "sub a", "sub b" — previously the parent's "Item text" paragraph was dropped entirely, leaving only the two children

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Item text", "sub a", "sub b". Fixture restored.

**Result (2026-09-04) ✅ PASS**
Parent li with own text + nested sublist: 3 bulleted paragraphs "Item text"/"sub a"/"sub b" in order — parent text preserved.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Three bullets in order: "Item text" (L0), "sub a" (L1), "sub b" (L1).

---

### TC-DOC123: Three-level nested list preserves every parent's own text, in document order ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Parent A has text<ul><li>Child A1 has text<ul><li>Grandchild A2a</li></ul></li></ul></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows three bulleted paragraphs in order: "Parent A has text", "Child A1 has text", "Grandchild A2a" — all three levels' own text present, none clobbered by the nested `<li>` below it
- Order matches source order (each parent before its own children) — a fix that only restores the buffer at the outer `</li>` close would emit children before their parent instead

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Parent A has text", "Child A1 has text", "Grandchild A2a". Fixture restored.

**Result (2026-09-04) ✅ PASS**
3-level nested list: "Parent A has text"/"Child A1 has text"/"Grandchild A2a" all present in document order at correct depths.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: "Parent A has text" (L0), "Child A1 has text" (L1), "Grandchild A2a" (L2), in source order.

---

### TC-DOC124: Nested list via Markdown also preserves the parent line's text ⚠️ destructive
**Prompt**
> "Write this Markdown to doc {DOC_ID} with content_format='markdown': `- Item text:\n    - sub a\n    - sub b`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows three bulleted paragraphs: "Item text:", "sub a", "sub b" — confirms the fix applies through the Markdown→HTML pipeline too, not just raw HTML
- Note: 4-space indentation is used deliberately — 2-space indentation doesn't clear the `sane_lists` nesting threshold and produces a flat, unnested list instead (a separate, already-tracked issue, #334)

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Item text:", "sub a", "sub b" — confirms the fix applies through the Markdown pipeline too. Fixture restored.

**Result (2026-09-04) ✅ PASS**
Markdown 4-space nested list: "Item text:"/"sub a"/"sub b" in order — confirms fix applies through markdown pipeline too.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Markdown with 4-space indentation gave "Item text:" (L0), "sub a" (L1), "sub b" (L1).

---

### TC-DOC125: A `<pre>` block opening inside an open `<li>` doesn't drop the `<li>`'s own text ⚠️ destructive
**Note:** covers the review-round finding that #335's original fix only guarded `<ul>`/`<ol>` — any block-level construct interrupting an open `<li>` had the same data-loss bug.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Note:<pre>code</pre></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a bulleted paragraph "Note:" followed by a separate (non-bulleted) paragraph "code" — previously "Note:" was dropped entirely and no bullet was emitted for this `<li>` at all

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned bulleted paragraph "Note:" followed by non-bulleted paragraph "code". Fixture restored.

**Result (2026-09-04) ✅ PASS**
<pre> inside open <li>: bulleted "Note:" followed by non-bulleted "code" paragraph — parent text not dropped.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Bulleted "Note:" followed by a non-bulleted "code" paragraph.

---

### TC-DOC126: A `<table>` opening inside an open `<li>` doesn't drop the `<li>`'s own text ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Before<table><tr><td>cell</td></tr></table></li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a bulleted paragraph "Before" followed by a 1×1 table whose cell reads "cell"

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned bulleted paragraph "Before" followed by a 1×1 table with cell text "cell". Fixture restored.

**Result (2026-09-04) ✅ PASS**
<table> inside open <li>: bulleted "Before" followed by 1x1 table, cell "cell".

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Bulleted "Before", the standard 1pt spacer paragraph, then a 1×1 table with cell "cell".

---

### TC-DOC127: Trailing text after a nested list, before the real `</li>`, is not dropped ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Parent<ul><li>Child</li></ul>trailing text</li></ul>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows three bulleted paragraphs in order: "Parent" (depth 0), "Child" (nested), "trailing text" (depth 0) — previously "trailing text" was silently dropped since the parent `<li>`'s block context was never reopened after its nested list closed

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned three paragraphs in order: "Parent", "Child", "trailing text". Fixture restored.

**Result (2026-09-04) ✅ PASS**
Trailing text after nested list, before real </li>: "Parent"(depth0)/"Child"(nested)/"trailing text"(depth0) all present in order — not dropped.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: "Parent" (L0), "Child" (L1), "trailing text" (L0).

---

### TC-DOC128: An unclosed `<b>` inside a `<li>` doesn't leak bold formatting into the rest of the document ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Item <b>bold text<ul><li>sub</li></ul></li></ul><p>After the list</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows "Item " unbolded and "bold text" bolded within the first bullet (as authored)
- The "sub" bullet and the "After the list" paragraph are **not** bolded — previously the never-closed `<b>` left bold formatting active for every subsequent node in the document

**Cleanup:** write fixture content back

**Result (2026-07-19) ✅ PASS**
`get_doc_structure` returned "Item " unbolded and "bold text" bolded within the first bullet; "sub" and "After the list" both unbolded. Fixture restored.

**Result (2026-09-04) ✅ PASS**
Unclosed <b> inside <li> interrupted by nested list: "Item " unbolded, "bold text" bolded (as authored); "sub" and "After the list" both unbolded — no bold leak.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: "Item " is not bold and "bold text" is bold. "sub" and "After the list" are not bold.

---

### TC-DOC129: A heading's own text survives a nested table interrupting it ⚠️ destructive
**Note:** review round 2 found the prior fix was still gated on the interrupted block being specifically `<li>` — any open block (headings, plain paragraphs) had the same text-loss bug, and in this specific shape the loss was worse than a drop: the heading's text was spliced directly into the table's own cell content.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<h2>Heading text<table><tr><td>cell</td></tr></table></h2>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a level-2 heading reading exactly "Heading text", followed by a 1×1 table whose cell reads exactly "cell" — not "Heading textcell" or any other splice/merge of the two

**Cleanup:** write fixture content back

**Result (2026-09-04) ✅ PASS**
Heading interrupted by nested table: HEADING_2 "Heading text" exactly, table cell "cell" exactly — no text/cell splice.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: HEADING_2 "Heading text" exactly, then the spacer and a 1×1 table with "cell". No splice.

---

### TC-DOC130: Malformed HTML (an unclosed `<p>` inside a `<li>`) degrades locally without corrupting later, well-formed content ⚠️ destructive
**Note:** covers a live-confirmed corruption mode from review round 2 — an interruption stack that pops on any close tag (rather than verifying it owns the frame) let a stray close tag later in the document consume the wrong frame, causing unrelated plain text to be spuriously wrapped as a bulleted list item.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>text<p>unclosed</li></ul><p>Later unrelated paragraph</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a bulleted paragraph "text" (the `<li>`'s own text, preserved despite the unclosed `<p>` inside it)
- `get_doc_structure` shows "Later unrelated paragraph" as a plain, non-bulleted paragraph — not wrapped into a list item and not merged with any other text

**Cleanup:** write fixture content back

**Result (2026-09-04) ✅ PASS**
Malformed HTML (unclosed <p> inside <li>): bulleted "text" preserved, "Later unrelated paragraph" plain non-bulleted, not merged with anything.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Bulleted "text", plain "unclosed", then a plain, unmerged "Later unrelated paragraph".

---

## Bare top-level text no longer silently dropped — `write_doc_content` (issue #343)

**Background:** surfaced by Kit while building fixtures for TC-DOC107/PR #337 (unrelated to that PR's diff, flagged separately). `content`/HTML with no wrapping block tag (e.g. `hello world` instead of `<p>hello world</p>`) fell into `html_to_ast`'s inline-only code path — `handle_data` only buffers text inside an open block (`<p>`, `<li>`, a heading, or a table cell), so text with no block ancestor at all was silently dropped, producing an empty document body. The fix adds a generic open-tag depth counter so `handle_data` can tell genuinely bare text (depth 0) apart from text merely wrapped in a non-block tag with no block ancestor at all (e.g. `<span>no blocks</span>`, depth 1) — the latter stays an intentional no-op (see `test_inline_only_html_skips_batchupdate`), the former now gets an implicit paragraph wrap.

### TC-DOC131: Bare text with no wrapping tag at all is no longer dropped ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `hello world`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a single plain paragraph reading exactly "hello world" — previously this call silently produced an empty document body

**Cleanup:** write fixture content back

**Result (2026-09-04) ✅ PASS**
Wrote raw bare text "hello world" (no wrapping tag). get_doc_structure shows a single plain paragraph reading exactly "hello world" — previously silently dropped.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Bare "hello world" became a single plain paragraph "hello world".

---

### TC-DOC132: An inline tag with no block ancestor still produces no content (regression guard) ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<span>no blocks</span>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows the document body empty/unchanged — this is the deliberate existing behavior for inline-only tags with no block ancestor and the #343 fix must not alter it

**Cleanup:** write fixture content back

**Result (2026-09-04) ✅ PASS**
Wrote <span>no blocks</span>. Document body empty/unchanged — deliberate no-op behavior confirmed unaffected by #343 fix.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: `<span>no blocks</span>` left the body empty (only the terminal "\n"). This is the deliberate no-op.

---

## UTF-16 code-unit offset correctness in write paths (issue #358)

**Background:** Docs API `startIndex`/`endIndex` count UTF-16 code units, not Python code points — an astral-plane character (most emoji, some CJK/math symbols) is one Python `str` character but a 2-unit surrogate pair. `emitter.py`'s `ast_to_requests` derived every downstream offset (table positions, paragraph-style ranges, inline run-style ranges) from plain `len()`, so any content containing an astral-plane character before other content in the same batch silently desynced every subsequent computed offset. Fixed by introducing a shared `utf16_len` helper (`docs/indices.py`) and routing `emitter.py` and `content.py` through it; `sheets/helpers.py`'s `_utf16_len` now delegates to the same helper instead of duplicating the accounting. The identical pattern was already fixed in `find_in_doc`'s `_collect_doc_paragraphs` (#262); this closes the matching gap in the write path.

### TC-DOC133: `write_doc_content` — table position lands correctly after an astral-plane (emoji) paragraph ⚠️ destructive
**Prompt**
> "Write this HTML to doc {DOC_ID}: `<p>😀 Hello</p><table><tr><td>Marker</td></tr></table>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows a paragraph reading exactly "😀 Hello" immediately followed by a 1×1 table whose cell reads exactly "Marker" — not truncated, spliced, or overlapping. Pre-fix, `table_positions` was computed from `len("😀 Hello\n")` (8) instead of the correct UTF-16 length (9), landing the table one unit early — inside the paragraph's trailing newline.

**Cleanup:** write fixture content back

**Result (2026-07-22) ✅ PASS**
Run against a live sandbox scoped to only `create_doc,create_doc_from_file,write_doc_content,find_in_doc,insert_softbreak_paragraph,insert_local_images,update_cells` (`get_doc_structure` not enabled) — verified via `find_in_doc` instead: "Hello" matched at `[4,9]` (paragraph text, UTF-16-correct given 😀 occupies units 1-2), "Marker" matched intact at `[14,20]` with clean cell-only context, no splice/corruption between paragraph and table content. Geometry consistent with the fixed `table_positions` (10) rather than the pre-fix value (9). A future run with `get_doc_structure` available should confirm the exact table/cell start index directly rather than inferring it from `find_in_doc` matches.

**Result (2026-09-04) ✅ PASS**
Wrote <p>😀 Hello</p><table>... get_doc_structure (now available, better than historical find_in_doc-only verification): paragraph "😀 Hello" exactly (1-10, 9 UTF-16 units), immediately followed by 1x1 table cell "Marker" exactly — no truncation/splice/overlap. Confirms utf16_len fix directly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: "😀 Hello" spans 1–10 (9 UTF-16 units), then the spacer and a 1×1 table "Marker" at 11–22. No splice or overlap.

---

### TC-DOC134: `insert_softbreak_paragraph` — `line_ranges` correct across an astral-plane (emoji) character ⚠️ destructive
**Setup:** fresh/empty doc (index 1 is always a valid insertion point in a new Google Doc)

**Prompt**
> "Insert a soft-break paragraph at index 1 in doc {DOC_ID} with lines [{text: '😀X'}, {text: 'Y'}]"

**Checks**
- Response has no `error`; `end_index` is 6 and `line_ranges` is `[{start_index: 1, end_index: 4}, {start_index: 5, end_index: 6}]` — UTF-16-correct (😀 = 2 units, X/\v/Y = 1 unit each, total 5 units from index 1). Pre-fix (`len()`-based) would have given `end_index: 5` and `line_ranges: [{1,3},{4,5}]`.
- `get_doc_structure` confirms the paragraph text reads exactly "😀X\vY" with no dropped or shifted characters

**Cleanup:** delete the created doc

**Result (2026-07-22) ✅ PASS**
`insert_softbreak_paragraph` returned `end_index: 6`, `line_ranges: [{start_index:1,end_index:4},{start_index:5,end_index:6}]` — exact match for the UTF-16-correct values, not the pre-fix `len()`-based ones. Independently confirmed via `find_in_doc`: "Y" matched at `[5,6]` with context `"😀XY"`.

**Result (2026-09-04) ✅ PASS**
insert_softbreak_paragraph(lines=[{"😀X"},{"Y"}]) on fresh doc returned end_index=6, line_ranges=[{1,4},{5,6}] — exact match for UTF-16-correct values. get_doc_structure confirmed paragraph text "😀X\vY\n" exactly, no dropped/shifted chars. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: On a fresh doc it returned end_index 6 and line_ranges [{1,4},{5,6}]. The structure text is "😀X\vY\n". Doc trashed.

---

## Unsupported markdown constructs preserve paragraph boundaries (issue #401)

**Background:** #332/#333 established that an unsupported construct like `<img>` (markdown images convert to `<img>` before reaching the shared HTML→AST parser) gets dropped from the document. #401 is a step further: the construct's entire *paragraph* was also being deleted, not just the construct itself — `_emit_block_node` (`html_parser.py`) returned early without appending anything whenever a closed block's buffered runs came back empty (e.g. its only child was an unsupported `<img>`), and a bare `<hr>` (python-markdown's rendering of both `---` and `___` thematic breaks — confirmed via the issue's own follow-up comment) never opened a block at all, so it left zero trace. Either way, the two blocks on either side ended up directly adjacent (one's `endIndex` == the next one's `startIndex`), unlike how any standard markdown viewer degrades (the construct's own line/block boundary survives even when the construct itself can't render). The fix keeps an empty node (`runs=[]`) in the AST for both cases instead of dropping it — `emitter.py`'s `ast_to_requests` was updated to match, since its own `if not text.strip(): continue` guard would otherwise have skipped the now-empty node's contribution to `full_text` and lost the boundary anyway.

### TC-DOC135: An image and thematic breaks each keep their own paragraph instead of fusing adjacent headings together ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc135-paragraph-boundary.md` — a public `https://` image, two headings, a `---` thematic break, a `##` heading + paragraph, a `___` thematic break, and a final `##` heading + paragraph, plus the underscore-variant break called out in the issue's follow-up comment. The issue's own repro (`![Kindly Human](kh-logo.png)`) used an image that was dropped. This fixture's image embeds, so the case covers the boundaries around an embedded image and the two breaks, not #401's dropped-image boundary; a dropped image's boundary is covered by the #401 unit tests in `tests/test_docs_core.py`.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc135-paragraph-boundary.md, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists, in order: a plain (non-heading, non-bulleted) paragraph holding only the embedded image, 2 index units wide (the image plus its `\n`); the fixture's image is a public URL, which embeds since #333 instead of being dropped — then HEADING_1 "Kindly Human", HEADING_1 "Auditing and Accountability Policy", an empty paragraph (the `---` break), HEADING_2 "PURPOSE", a plain paragraph "Body text after the thematic break.", another empty paragraph (the `___` break), HEADING_2 "SCOPE", and a plain paragraph "Body text after the underscore break."
- Confirm the image paragraph is its own element, and each empty paragraph is a real, distinct structural element (own `startIndex`/`endIndex`, one index unit wide) sitting *between* the two real elements around it — not the two real elements landing with one's `endIndex` equal to the next one's `startIndex` with nothing between them

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-22, live via `mcp-gee-sweet-kit`, doc `1wUsmzHLHn4v4DRFvedfcy7qqBVuVnIcjk3gnUjtJTQU`, deleted after). `get_doc_structure` returned exactly the expected sequence: empty paragraph (dropped-image boundary), HEADING_1 "Kindly Human", HEADING_1 "Auditing and Accountability Policy", empty paragraph (`---`), HEADING_2 "PURPOSE", body paragraph, empty paragraph (`___`), HEADING_2 "SCOPE", body paragraph — each empty paragraph its own 1-unit-wide element between real neighbors, none fused. Separately reproduced live (scratch doc `1xa-iLbjHbqSJlyQ2IN_mFggCTd9gb_WsenMKolehQio`, deleted after) that `_interrupt_open_block` (`html_parser.py:236`) still drops the entire outer node when a block whose only content is an unsupported construct is interrupted by a nested block (e.g. `- ![img](x.png)\n    - nested`) — the outer bullet vanishes completely, not just its image, unlike the direct-close case this test covers. This gap is outside TC-DOC135's own scope but confirms the code-review finding on the same PR; see PR comment for detail. Not itself a fail for this test case, but blocks `qa-approved` for the PR as a whole.

**Re-verified after fix (2026-07-24, live via `mcp-gee-sweet-kit`, doc `1gWzAqpRvwT8n7IfJ70dkKRHyErTJyJLLjY4w3GaEqh4`, deleted after):** direct-close path unaffected by the interrupt-path fix (`preserve_if_empty` now keyed on `_block_had_unsupported_content` rather than `not self._block_resumed`) — `get_doc_structure` returned the identical expected sequence, no regression.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc135-paragraph-boundary.md). Notable: the fixture's image now EMBEDS successfully (images:[{src:...}], no error) rather than being dropped, since #333 (native markdown image support, landed after this fixture/TC was authored) now handles public http(s) image URLs. get_doc_structure confirmed the core paragraph-boundary check still holds: HEADING_1 "Kindly Human", HEADING_1 "Auditing and Accountability Policy", empty paragraph (--- break), HEADING_2 "PURPOSE", body text, empty paragraph (___ break), HEADING_2 "SCOPE", body text — no fused headings, each boundary its own distinct element. The first paragraph is now a real embedded image (2 units) rather than an empty 1-unit placeholder — an improvement, not a defect. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Order correct; the first element is now an image paragraph, not an empty one (stale).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Order: image paragraph (1–3; the image now embeds, so the "empty" check is stale), H1 "Kindly Human", H1 "Auditing…", empty (51–52), H2 PURPOSE, body, empty (96–97), H2 SCOPE, body. Each boundary is its own 1-unit element.

---

**Background:** TC-DOC135's own review round found a same-bug-class gap: `_interrupt_open_block` (`html_parser.py`) flushed the currently-open block *before* descending into a nested construct with `preserve_if_empty=False` unconditionally, so a block whose only content was an unsupported construct (e.g. an `<img>`) vanished entirely — not just the image — whenever it was itself interrupted by a nested list/table/pre/block instead of closing directly. The fix replaces the old `not self._block_resumed` proxy (used at every `_emit_block_node` call site) with a new `self._block_had_unsupported_content` flag that tracks, per open-block segment, whether something was actually silently dropped (an unsupported void element or unrecognized tag) since the segment last began — set in `handle_starttag`'s generic inline-element fallthrough, reset on both fresh block open and on `_resume_interrupted_block`. This is a deliberately different signal than "is this the block's first segment," because the interrupt call site's old proxy is wrong exactly when a block is empty for a completely unrelated, common reason: an `<li>` that wraps *only* a nested list with no text of its own (ordinary nested-list markdown) is empty on its first flush too, and must NOT gain a spurious empty bullet — a regression the naive `not self._block_resumed` fix would have introduced, caught by the existing unit test `TestNestedLists::test_parent_with_no_own_text_unaffected`.

### TC-DOC136: A block whose only content is a dropped construct survives when interrupted by a nested list, while a block with no content of its own still emits nothing ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc136-interrupted-block-boundary.md` — an H1 "Bug case" followed by a bullet whose only content is an unsupported `<img>`, immediately interrupted by its own nested one-item list (no direct-close ever happens for the outer bullet); then an H1 "Control case" followed by a bullet with real text of its own before an interrupting nested two-item list.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc136-interrupted-block-boundary.md, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists, in order: HEADING_1 "Bug case", an empty (non-heading) bullet item — the dropped image's boundary, surviving the interruption instead of the whole outer bullet vanishing — a nested bullet item "nested one", HEADING_1 "Control case", a bullet item "text", and two nested bullet items "control child a" / "control child b"
- Exactly one bullet item appears for the "Bug case" list before "nested one" (the preserved empty outer bullet) — not zero (the pre-fix vanish) and not two (a duplicate)
- No spurious empty bullet item appears anywhere under "Control case" — the outer "text" bullet's own real content is the only node before its two children

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-24, live via `mcp-gee-sweet-kit`, doc `16Cp78j9qXCqXXcA3PcYI_-bPUsRx9PwB9a-wn0zFIWU`, deleted after). `get_doc_structure` returned exactly the expected sequence: HEADING_1 "Bug case", one empty paragraph (the preserved outer-bullet boundary), "nested one", HEADING_1 "Control case", "text", "control child a", "control child b" — exactly one empty node for the bug case (neither vanished nor duplicated), and no spurious empty node anywhere under the control case. Confirms the send-back finding from PR #406's prior QA round (interrupt path dropping a block whose only content was an unsupported construct) is fixed without regressing the ordinary nested-list-with-no-own-text case.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc136-interrupted-block-boundary.md). Image ref "x.png" now resolves as a local-path reference (per #333) and fails per-image ("No file found at 'x.png'") rather than being silently unhandled-tag-dropped — same underlying "content lost, preserve boundary" case the test targets. get_doc_structure confirmed exact expected sequence: HEADING_1 "Bug case", ONE empty bulleted paragraph (preserved outer-bullet boundary), "nested one", HEADING_1 "Control case", "text", "control child a", "control child b" — exactly one empty node for the bug case (neither vanished nor duplicated), no spurious empty node under control case. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: H1 "Bug case", one empty L0 bullet, "nested one" (L1), H1 "Control case", "text", then "control child a"/"b" (L1). No spurious empty bullet. The images list reports x.png as not found, per-image.

---

**Background:** TC-DOC136's own review round (QA pass 2) found a second, unrelated gap in the *original* #401 fix (not introduced by TC-DOC136's own change): the bare-`<hr>`-with-no-open-block check (`html_parser.py`, added by #401) tested `self._block_tag is None and self._table_depth == 0` but omitted `self._tag_depth == 0` — the condition `handle_data`'s sibling bare-text check uses (#343) to distinguish genuinely bare top-level content from content that's merely wrapped in an inline tag with no block ancestor. An `<hr>` wrapped only in an inline tag (e.g. `<span><hr></span>`) was therefore treated as a bare top-level thematic break and injected a spurious empty-paragraph boundary — contradicting the existing, tested policy (`test_span_wrapped_text_still_dropped`, TC-DOC132) that inline-only content with no block ancestor is a deliberate no-op. Only reachable via hand-authored HTML through `create_doc_from_file`'s `.html` path — python-markdown never emits `<hr>` wrapped in an inline tag, only as a bare top-level sibling.

### TC-DOC137: An `<hr>` wrapped only in an inline tag with no block ancestor stays a no-op, matching the existing bare-text policy ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc137-inline-hr-no-block-ancestor.html` — a paragraph, a `<span>` wrapping only an `<hr>` with no block ancestor, and another paragraph.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc137-inline-hr-no-block-ancestor.html, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` shows exactly two body elements: a paragraph "Before" immediately followed by a paragraph "After" — no empty paragraph or other structural element between them (the pre-fix bug would show three elements, with a spurious empty paragraph from the inline-wrapped `<hr>`)

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-24, live via `mcp-gee-sweet-kit`, doc `11kfAgxg8pfiSfEGgvu9AvLtYlaWjf4B0KsBJPwntnSI`, deleted after). `get_doc_structure` returned exactly "Before" immediately followed by "After" — no spurious empty paragraph from the inline-wrapped `<hr>`, confirming the send-back finding from PR #406's QA pass 2 is fixed. Full unit suite: 898 passed.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc137-inline-hr-no-block-ancestor.html): get_doc_structure showed exactly "Before" immediately followed by "After" — no spurious empty paragraph from the inline-wrapped <hr> with no block ancestor. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Exactly "Before" (1–8) then "After" (8–14), with nothing between them.

---

## Whitespace/`&nbsp;`-only paragraphs preserve their blank line instead of being silently dropped (issue #402)

**Background:** distinct from #401's `runs=[]` case (an unsupported construct like `<img>` leaves a block with *no* buffered content at all). Here the block's buffered runs are non-empty but strip to nothing — a lone `&nbsp;` or a run of plain spaces — which markdown authors commonly write as a standalone line to force a visible blank-line spacer, since a literal blank line collapses in markdown. `_emit_block_node` (`html_parser.py`) used to drop any block whose text stripped to empty regardless of *why*, fusing the paragraphs on either side together exactly like #401 did before its fix. The fix distinguishes a *freshly*-closed block (opened and closed with nothing in between, e.g. `<p>&nbsp;</p>`) — always kept now, unconditional on `preserve_if_empty`, since there's real (if invisible) content to lose — from a *resumed* block's whitespace-only trailing flush (e.g. the indentation newline between a nested list's `</ul>` and the outer `<li>`'s own `</li>`), which is markup-formatting noise, not authored content, and keeps falling back to the same `preserve_if_empty` gate the `runs=[]` case already used (confirmed via `test_nested_list_via_markdown_preserves_parent_text`, which regressed under a first, broader version of this fix that preserved every non-empty-runs whitespace-only block regardless of resumption state). `emitter.py`'s `ast_to_requests` no longer special-cases whitespace text either — it emits whatever text a kept node carries.

### TC-DOC138: A standalone `&nbsp;` line between two paragraphs keeps its own blank paragraph rather than fusing its neighbors together ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc138-nbsp-spacer-paragraph.md` — mirrors the issue's own repro (an Employee Handbook acknowledgment/signature block): a paragraph, a standalone `&nbsp;` line, a row of underscores (renders as `<hr />`, exercising #401's case in the same doc), and a final paragraph with several inline `&nbsp;` runs mixed with real text.

**Prompt**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc138-nbsp-spacer-paragraph.md, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists exactly 4 paragraphs in order: the acknowledgment paragraph, a non-empty paragraph whose `text` is just the nbsp character (plus the API's own trailing newline) — not merged into either neighbor, own `startIndex`/`endIndex` — an empty paragraph (the underscore `<hr>`, #401's case), and the "Employee Signature ... Date" paragraph
- The nbsp paragraph's `endIndex` does **not** equal the acknowledgment paragraph's `endIndex` (i.e. it isn't zero-width/fused) — it has real width from the nbsp character
- The final paragraph's inline `&nbsp;&nbsp;...` run between "Employee Signature" and "Date" survives as literal nbsp characters in its `text`, not collapsed or stripped

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-27, live via `mcp-gee-sweet-kit`, doc `1e9W8zb8gWtOCDb6lJcuFtCZbum7hoXRqGbBaEBd3vD0`, deleted after). `get_doc_structure` returned the expected 4 content paragraphs in order, followed by the doc's own terminal empty paragraph (confirmed via a separate baseline doc with unrelated plain content — this trailing element is a standard Google Docs artifact on every doc, not something this fix introduces, so it doesn't count against "exactly 4"). Verified at the raw codepoint level via a direct Docs API call: the spacer paragraph is literally `'\xa0\n'` (startIndex 96, endIndex 98) with real width — not fused with the acknowledgment paragraph's endIndex 96; the `<hr>` paragraph is the expected bare `'\n'`; the final paragraph's inline gap is `'Employee Signature \xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0 Date\n'`, all 8 nbsp characters intact, not collapsed to regular spaces. Full unit suite: 945 passed.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc138-nbsp-spacer-paragraph.md). get_doc_structure confirmed 4 content paragraphs in order + terminal blank: acknowledgment(1-96), nbsp spacer(96-98, text=" \n", real width, not fused with acknowledgment's endIndex 96), <hr> empty paragraph(98-99), "Employee Signature ... Date" final paragraph (99-132) with the inline nbsp gap preserved as spacing. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Acknowledgment 1–96, nbsp spacer 96–98 (real width), empty hr paragraph 98–99, and "Employee Signature … Date" 99–132 with a 10-character gap (not collapsed).

---

## A mismatched `<ol>`/`<ul>` close tag no longer permanently desyncs list depth (issue #382)

**Background:** `handle_endtag`'s `<ol>`/`<ul>` close-tag handling (`html_parser.py`) used to pop `_list_ordered` — the stack `BulletItem.depth`/`.ordered` are computed from — only when the closing tag's implied type matched the stack's own top entry. A mismatched pair (e.g. an `<ol>` closed by a stray `</ul>`, a real input surface since `write_doc_content`/`create_doc` accept raw, unvalidated HTML directly) silently skipped the pop instead of performing it, leaving the stack one level too deep for the rest of the document — every subsequent `BulletItem.depth` came out off by one, bleeding into completely unrelated, later, well-formed lists, not just the malformed one. Fixed by popping `_list_ordered` unconditionally on any `<ol>`/`<ul>` close (by count, not gated on matching the popped entry's own type) — mirroring the same unconditional-pop principle `_resume_interrupted_block` already applies to the separate node-*type* correctness concern for this same malformed-tag scenario. Well-formed nesting is unaffected, since the old gate was already true in that case.

### TC-DOC141: A malformed list elsewhere in the doc doesn't bleed a bogus nesting depth into a later, unrelated, well-formed list ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc141-mismatched-list-tags.html` — a malformed `<ol><li>Parent<ul><li>Child</li></ol></li></ul>` (the `<ol>` is closed by a stray `</ul>`), then an unrelated paragraph, then a completely separate, well-formed `<ol><li>Fresh ordered item</li></ol>`.

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc141-mismatched-list-tags.html, then show me its structure."

**Checks**
- Tool completes without error
- `get_doc_structure` lists, in order: a bullet "Parent", a nested bullet "Child", a plain paragraph "Unrelated paragraph between the two lists.", and a bullet "Fresh ordered item"
- 🔍 Visual check: "Fresh ordered item" renders as a **top-level** numbered list item (e.g. "1."), not indented one level in under the malformed list above it — the pre-fix bug would render it nested one level deep despite being its own separate, well-formed `<ol>`

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-27, live via `mcp-gee-sweet-kit`). `create_doc_from_file` on the fixture completed without error. `get_doc_structure` listed the four paragraphs in order — "Parent", "Child", "Unrelated paragraph between the two lists.", "Fresh ordered item" (the tool doesn't surface bullet/nestingLevel fields, so order/text was confirmed this way and depth via the visual check below). Playwright screenshot confirmed "Fresh ordered item" rendered as a top-level "1." — not indented under the malformed list above it, matching the fixed behavior. Test doc trashed per cleanup step.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc141-mismatched-list-tags.html) — malformed <ol>/<ul> tag pair. get_doc_structure text order: "Parent"/"Child"/"Unrelated paragraph between the two lists."/"Fresh ordered item". Playwright screenshot (tc-doc141.png) confirmed "Fresh ordered item" renders as a TOP-LEVEL "1." — not indented under the malformed list above, confirming the #382 fix. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: Order: "Parent" (L0), "Child" (L1), the unrelated plain paragraph, then "Fresh ordered item" (L0). The screenshot (tc-doc141) shows "Fresh ordered item" as a top-level "1.".

---

## GitHub/GitLab-style heading-anchor links resolve to working Docs jump links (issue #409)

**Background:** Markdown converted from GitHub/GitLab Pages-published source keeps internal cross-reference links as literal `#slug` URL fragments — meaningless inside a Google Doc, since Docs has its own heading-jump-link addressing scheme. `get_doc_structure` now surfaces each heading paragraph's `headingId` (`paragraphStyle.headingId`, already present in the API response — no new API capability needed). `create_doc`/`create_doc_from_file`/`write_doc_content` now run an automatic second pass after any conversion that left a `#slug` link behind: it resolves the anchor against the doc's own real headings (trying GitHub's non-collapsing and GitLab's hyphen-collapsing slugification conventions, then a normalized-word-token fallback) and rewrites it to a working `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=<headingId>` link — confirmed live 2026-07-24 that this ordinary-URL form works as a real in-doc jump link, no special `Link.headingId` API field needed. An anchor that matches no heading with reasonable confidence gets its link stripped (text kept, plain) rather than left dangling or guessed — a link silently pointing at the wrong section is worse than no link. The pass is skipped entirely (no extra API round trip) when the converted content has no `#`-prefixed link at all — see unit test `test_no_anchor_link_skips_resolution_pass` in `tests/test_docs_content.py`.

### TC-DOC142: `get_doc_structure` surfaces `headingId` for heading paragraphs ⚠️ destructive

**Setup:** none — heading created fresh by the call under test.

**Prompt**
> "Write this Markdown to doc {DOC_ID}: '# A Heading\n\nSome text.\n', then show me its structure."

Tool calls: `write_doc_content(doc_id={DOC_ID}, content="# A Heading\n\nSome text.\n", content_format="markdown")`, then `get_doc_structure(doc_id={DOC_ID})`.

**Checks**
- First element has `namedStyleType: "HEADING_1"` and a non-null `headingId` (e.g. `"h.xxxxxxxxxxx"`)
- Second element ("Some text.") has `namedStyleType: "NORMAL_TEXT"` and `headingId: null`

**Cleanup:** write fixture content back

**Result:** PASS (2026-07-28, live via `mcp-gee-sweet-kit`). First element was `HEADING_1`/`headingId: "h.sfbe55a8e31j"`; second was `NORMAL_TEXT`/`headingId: null`. Fixture content restored.

**Result (2026-09-04) ✅ PASS**
write_doc_content markdown heading to DOC_ID. get_doc_structure: first element HEADING_1/headingId non-null, second element ("Some text.") NORMAL_TEXT/headingId:null.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: HEADING_1 "A Heading" with a non-null headingId, then NORMAL_TEXT "Some text." with headingId null.

---

### TC-DOC143: `create_doc_from_file` resolves markdown heading-anchor links to working in-doc jump links, and strips unmatched ones ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc142-heading-anchors.md`.

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc142-heading-anchors.md, then show me its structure."

Tool calls: `create_doc_from_file(local_path="<repo-root>/docs/qa/fixtures/tc-doc142-heading-anchors.md")`, then `get_doc_structure(doc_id=<returned docId>)`.

**Checks**
- `get_doc_structure` shows a HEADING_1 "Appendix A - Approved Hashing Algorithms" and a HEADING_2 "Appendix B - Something Else", each with a non-null `headingId`
- The run "Appendix A" has `link_url` equal to `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=<headingId>` where `<headingId>` is the SAME value as the "Appendix A - Approved Hashing Algorithms" heading's own `headingId`
- The run "Appendix B itself" has `link_url` similarly pointing at the "Appendix B - Something Else" heading's own `headingId`
- The run "dead link" has `link_url: null` (stripped — not left pointing at the literal `#totally-nonexistent-section` fragment)
- 🔍 Visual check: clicking "Appendix A" in the rendered Doc jumps to the "Appendix A - Approved Hashing Algorithms" heading; "dead link" renders as plain, non-hyperlinked text

**Cleanup:** delete the created doc

**Result:** ⚠️ PARTIAL as written (2026-07-28, live via `mcp-gee-sweet-kit`) — "Appendix A" and "Appendix B itself" runs resolved to their own headings' `headingId` correctly, "dead link" was stripped to `link_url: null`. Visual jump-link click not separately verified via Playwright since `/code-review high` on this PR independently confirmed, by direct source reading, two higher-severity defects this fixture can't reach: (1) `_resolve_heading_anchors`'s body walk (`content.py`) only inspects top-level `paragraph` elements, never descending into `table` cells, so both the pending-link gate and the resolution scan are blind to any heading-anchor link or heading inside a table; (2) an anchor run whose `pe.get("startIndex")` is `None` (documented elsewhere in this same file as occurring on a document's first body element) is silently dropped rather than carrying the offset forward the way `_collect_doc_paragraphs` already does for the identical quirk. Neither case is exercised by `tc-doc142-heading-anchors.md` (no table, and the anchor links aren't on the doc's first element) — this is a real coverage gap in the fixture, not just an untested edge case. Sending back to Dev per findings below rather than approving.
**Corrected (2026-10-17, #1044 audit):** the jump-link click wasn't verified with Playwright.

**Cleanup:** delete the created doc

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc142-heading-anchors.md). All 4 checks confirmed: HEADING_1/HEADING_2 with own headingIds; "Appendix A" run link_url resolves to Appendix A's own headingId; "Appendix B itself" run link_url resolves to Appendix B's own headingId; "dead link" run link_url:null (stripped). Trashed.

**Result (2026-09-21) ✅ PASS — re-run on PR #783 (issue #454), live via `mcp-gee-sweet-kit`.** PR #783 hoists `resolve_heading_anchor`'s per-anchor slugified-heading-list computation into a new `compute_scheme_slugs` helper (caching across anchors in one document) — this test case exercises the function this refactor changed. `create_doc_from_file(tc-doc142-heading-anchors.md)`: all 4 checks confirmed identical to prior runs — HEADING_1/HEADING_2 own `headingId`s; "Appendix A" and "Appendix B itself" runs' `link_url` resolve to their own headings; "dead link" run `link_url: null` (stripped). No regression from the caching change. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: The headings have their own headingIds. The "Appendix A" and "Appendix B itself" runs link to …#heading=<their own heading's id>, and "dead link" has link_url null. In Playwright, clicking "Appendix A" opened a link chip naming the heading, and following it set the URL to #heading=h.v7o7e59z8uyd. Clicking "dead link" opened no link chip (tc-doc143.png).

---

### TC-DOC144: A heading-anchor link inside a table cell is resolved (regression for the table-blind body walk) ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc144-anchor-in-table-cell.md` — a top-level `# Reference Section` heading, then a table whose first cell contains a markdown link `[Reference Section](#reference-section)`.

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc144-anchor-in-table-cell.md, then show me its structure."

Tool calls: `create_doc_from_file(local_path="<repo-root>/docs/qa/fixtures/tc-doc144-anchor-in-table-cell.md")`, then `get_doc_structure(doc_id=<returned docId>)`.

**Checks**
- `get_doc_structure` shows a HEADING_1 "Reference Section" with a non-null `headingId`
- `get_doc_structure`'s table cell text reads "See Reference Section for details." (the link text, not the literal `#reference-section` fragment) — this tool doesn't surface per-run `link_url` for table cell content (only whole-cell `text`), so confirming the actual hyperlink requires a raw `documents().get()` call: the table cell's "Reference Section" `textRun` should carry `textStyle.link.url` equal to `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=<headingId>` where `<headingId>` matches the HEADING_1 paragraph's own `headingId`
- 🔍 Visual check: clicking "Reference Section" inside the table cell jumps to the "Reference Section" heading

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-29, live via `mcp-gee-sweet-kit` for `create_doc_from_file`/`get_doc_structure`, plus a raw `documents().get()` script for the table cell's own `textRun.textStyle.link` since `get_doc_structure` doesn't expose it). HEADING_1 "Reference Section" had `headingId: "h.lgbpfqi86w2d"`; the table cell's "Reference Section" run's `link.url` was `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=h.lgbpfqi86w2d` — matches. Confirms fix for QA round 1 finding #1 (table-cell anchor links). Test doc trashed per cleanup step.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc144-anchor-in-table-cell.md). HEADING_1 "Reference Section" headingId confirmed; table cell text "See Reference Section for details." confirmed. Playwright screenshot (tc-doc144.png) confirmed "Reference Section" renders as a blue/underlined hyperlink inside the table cell. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: H1 headingId is h.tmfo0jvm0qfk, and the cell text is "See Reference Section for details.". I verified the cell link with get_doc_as_markdown instead of a raw read: it exported [Reference Section](…#heading=h.tmfo0jvm0qfk). Clicking it in Playwright jumped to that heading (tc-doc144.png).

---

### TC-DOC145: A heading-anchor link that is the document's very first body element is resolved (regression for the startIndex-carry-forward gap) ⚠️ requires-oauth ⚠️ destructive

**Setup:** use `docs/qa/fixtures/tc-doc145-anchor-on-first-element.md` — the document's very first line is a markdown link `[Jump to Overview](#overview)`, followed by the `# Overview` heading it references.

**Prompt**
**Playwright: required**
> "Create a Google Doc from the file <repo-root>/docs/qa/fixtures/tc-doc145-anchor-on-first-element.md, then show me its structure."

Tool calls: `create_doc_from_file(local_path="<repo-root>/docs/qa/fixtures/tc-doc145-anchor-on-first-element.md")`, then `get_doc_structure(doc_id=<returned docId>)`.

**Checks**
- `get_doc_structure`'s first element is the paragraph containing "Jump to Overview" (the Docs API omits `startIndex` on a document's very first element — this is the case the fix must not drop)
- That run's `link_url` is equal to `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=<headingId>` where `<headingId>` matches the "Overview" HEADING_1 paragraph's own `headingId` — not left as the literal `#overview` fragment
- 🔍 Visual check: clicking "Jump to Overview" jumps to the "Overview" heading

**Cleanup:** delete the created doc

**Result:** PASS (2026-07-29, live via `mcp-gee-sweet-kit`). `get_doc_structure`'s first element was the "Jump to Overview" paragraph; its run's `link_url` was `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=h.jmodqzi4drr`, matching the "Overview" heading's own `headingId`. Confirms fix for QA round 1 finding #2 (startIndex-carry-forward). Test doc trashed per cleanup step.

**Result (2026-09-04) ✅ PASS**
create_doc_from_file(tc-doc145-anchor-on-first-element.md). First element is the "Jump to Overview" paragraph (Docs API startIndex-omission-on-first-element quirk handled); its run's link_url resolves exactly to the "Overview" HEADING_1's own headingId. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: The first element is "Jump to Overview", with link_url …#heading=h.wb50l61h54s7, which matches the Overview H1. Clicking it in Playwright opened a chip for the "Overview" heading and moved the URL to that heading (tc-doc145.png).

---

## Stale block-interruption frame from a mismatched list-close no longer resumed by a later, unrelated list (issue #450)

**Background:** Surfaced during PR #449's QA pass (issue #382 — mismatched `<ol>`/`<ul>` close tags), confirmed as a distinct pre-existing bug rather than a regression from that PR. `_resume_interrupted_block` pushes a `_BlockFrame` onto `_block_stack` when a list interrupts an open block (e.g. an `<h1>` interrupted by `<ol>`). If the interrupting list is later closed by a *mismatched* tag (`</ul>` instead of `</ol>`), the old code only matched a frame by comparing its `interrupted_by` tag against the exact closing tag — a mismatch left the frame stuck on the stack. A later, unrelated, well-formed list could then close with a tag that happened to match the stale frame's `interrupted_by` value, incorrectly restoring `self._block_tag` to the original (now long-closed) outer block and mistyping subsequent bare trailing text as that stale block type. Fixed by matching list-category interruptions (`interrupted_by` in `{"ol", "ul"}`) by the list-nesting depth recorded at interrupt time instead of by tag identity — the frame is always resolved (popped) once that depth is reached, even on a mismatch, but the outer block is only actually *resumed* (`self._block_tag` restored) on an exact tag match; a mismatched close ends the interruption without guessing at reopening the outer block.

### TC-DOC148: A stale block-interruption frame from a mismatched list-close is not resumed by a later, unrelated well-formed list ⚠️ destructive

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<h1>Start<ol><li>Item</li></ul><ol><li>Later item</li></ol>Trailing bare text`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` lists, in order: a HEADING_1 "Start", a bullet "Item", a bullet "Later item", and a plain (non-heading) paragraph "Trailing bare text" — the pre-fix bug rendered the last line as a HEADING_1 instead of a plain paragraph, because the mismatched `</ul>` left the `<h1>` interruption frame stuck until the second, unrelated `<ol>`'s well-formed `</ol>` coincidentally popped and resumed it

**Cleanup:** write fixture content back

**Result (2026-09-04) ✅ PASS**
Wrote HTML with mismatched list close (<ol>...</ul>) followed by well-formed <ol>. get_doc_structure: HEADING_1 "Start", bullet "Item", bullet "Later item", plain (non-heading) paragraph "Trailing bare text" — NOT rendered as HEADING_1 (the pre-fix bug), confirming #450 fix.

**Result (2026-09-21) ✅ PASS — re-run on PR #779 (issue #451), live via `mcp-gee-sweet-kit`.** PR #779 merges `handle_endtag`'s previously-identical `if tag == "ol": ...` / `if tag == "ul": ...` branches into one `if tag in ("ol", "ul"):` branch — this test case exercises exactly that code path. `write_doc_content` on the fixture doc completed with no error; `get_doc_structure` returned HEADING_1 "Start", bullet "Item", bullet "Later item", plain NORMAL_TEXT "Trailing bare text" — matches expected, no regression from the merge. Fixture content restored.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: H1 "Start", bullet "Item", bullet "Later item", then plain NORMAL_TEXT "Trailing bare text".

---

**Background (PR #478 review round):** Code review on the fix above caught a second, related bug in the same function, live-reproduced against the branch. Bare top-level text directly inside a still-open `<ol>`/`<ul>` (not wrapped in its own `<li>`) opens an *implicit* paragraph via `handle_data`'s bare-text path (#343) without ever going through `_interrupt_open_block` — so it has no frame of its own on `_block_stack`. `_resume_interrupted_block`'s resume path unconditionally overwrote `self._block_tag` and cleared `self._run_buf`, silently destroying that implicit paragraph's text instead of flushing it first — reachable via a mismatched inner list close (the discard path TC-DOC148 above exercises) immediately followed by an exact-matching outer list close. Fixed by flushing whatever block is currently open, if any, before actually resuming.

### TC-DOC149: An implicit paragraph opened by bare text inside a still-open list is flushed, not clobbered, when an interrupted block resumes ⚠️ destructive

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<h1>Start<ol><li>B<ul><li>C</li></ol>D</ol>E`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` lists, in order: a HEADING_1 "Start", a bullet "B", a bullet "C", a plain (non-heading) paragraph "D", and a HEADING_1 "E" — the pre-fix bug dropped "D" entirely and rendered "E" as its own new heading instead of "Start"'s resumed content

**Result (2026-08-02) ✅ PASS** — live `write_doc_content` + `get_doc_structure` against the fixture doc returned exactly HEADING_1 "Start", paragraph "B", paragraph "C", paragraph "D", HEADING_1 "E" — "D" is preserved (previously vanished entirely) and no other regression in the sequence.

**Cleanup:** write fixture content back

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: H1 "Start", bullet "B" (L0), bullet "C" (L1), plain "D", H1 "E".

## Image sharing lifecycle — `revoke_sharing` default and consistency (#333)

**Background:** #332's `insert_local_images` always uploaded and shared a local image `anyone:reader` (required — the Docs backend fetches inline images as an anonymous HTTP request, confirmed live 2026-07-18) but never revoked that share afterward, leaving the caller to call `remove_permission` manually. #333 adds native markdown/HTML image support (`create_doc`, `create_doc_from_file`, `write_doc_content`) reusing the same upload+share lifecycle for local-path and `drive:<file_id>` sources, and — per explicit product decision — both the new path and `insert_local_images` now default to auto-revoking that temporary share once the image is actually embedded (`revoke_sharing=True`), with a flag to opt out and keep the old always-shared behavior.


**Result (2026-09-04) ✅ PASS**
Wrote HTML with bare text inside still-open list + mismatched close. get_doc_structure: HEADING_1 "Start", bullet "B", bullet "C", plain paragraph "D" (preserved, not clobbered), HEADING_1 "E" (correctly resumed, not a new heading) — matches expected sequence exactly.

### TC-DOC150: `create_doc` markdown image (local path) is embedded and its temporary share is revoked by default ⚠️ requires-oauth ⚠️ destructive

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'TC-DOC150' from this markdown, using folder {FOLDER_ID}: `# Report\n\n![Pixel](<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png)\n\nAfter the image.`"

Tool call: `create_doc(title="TC-DOC150", content="# Report\n\n![Pixel](<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png)\n\nAfter the image.", content_format="markdown", folder_id=<FOLDER_ID>)`

**Checks**
- Response has no `error`; `images` is a one-item list with `fileId` set, `shared: false`, and no `revoke_error`
- `list_permissions(file_id=<images[0].fileId>)` shows no `anyone` type permission (confirms the revoke actually happened, not just that the response claimed it did)
- 🔍 Visual check: the pixel image renders between "Report" and "After the image."

**Cleanup:** delete the created doc; delete the uploaded image file (`delete_file(file_id=<images[0].fileId>)`)

**Background (2026-08-02):** dev-side verification (same scratch-script approach as TC-DOC102's background note — not through the MCP tool interface) exercised this exact scenario: `_apply_doc_content` against a real scratch doc with a markdown image, `target_folder_id="root"`. Image uploaded, shared, embedded (confirmed via a raw `documents().get()` read showing an `inlineObjectElement` in the correct paragraph, correctly interleaved with a table and trailing text in the same call), and the outcome entry showed `{"fileId": "<real id>", "shared": False}` — the temporary `anyone:reader` permission was confirmed actually gone (not just reported as gone), since a subsequent `permissions().create()`-then-`delete()` round trip only succeeds if the delete genuinely executed. Scratch doc and uploaded image both trashed at end of run.

**Result (2026-08-02) ✅ PASS — live via the actual `create_doc` MCP tool.** Response had no `error`; `images` was `[{"src": "<local path>", "fileId": "<real id>", "shared": false}]`, no `revoke_error`. `list_permissions` on the uploaded file's `fileId` showed only the owner and service-account permissions — no `anyone` grant. Playwright screenshot confirmed the pixel image renders between "Report" and "After the image." (visually a tiny dot, as expected for this 1×1 fixture with no explicit width/height). Doc and uploaded image trashed after the check.

**Result (2026-09-04) ✅ PASS**
create_doc markdown local-path image, folder_id set. Response: images=[{fileId, shared:false}], no revoke_error. list_permissions on uploaded file showed only owner+service-account, no anyone grant — confirms revoke actually happened. Doc+image trashed.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** `create_doc` with the local-path markdown image and `folder_id` set gave no `error` and `images=[{fileId, shared: false}]`, with no `revoke_error`. `list_permissions` on the upload showed only the organizer and the service account, no `anyone` grant. Playwright: a pixel dot renders between "Report" and "After the image." Doc and upload trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: create_doc with a markdown local-path image returned images [{fileId, shared:false}] and no revoke_error. list_permissions showed no anyone grant. The screenshot (tc-doc150) shows the dot between "Report" and "After the image.". Doc and image trashed.

---

### TC-DOC151: `create_doc` markdown image (`drive:` reference) with `revoke_sharing=False` leaves the image shared ⚠️ requires-oauth ⚠️ destructive

**Prerequisite:** upload an image to Drive first (e.g. `upload_local_file` with `<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png`) and note its `fileId`

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'TC-DOC151' from this markdown, with revoke_sharing off: `![Pixel](drive:<UPLOADED_FILE_ID>)`"

Tool call: `create_doc(title="TC-DOC151", content="![Pixel](drive:<UPLOADED_FILE_ID>)", content_format="markdown", revoke_sharing=False)`

**Checks**
- Response has no `error`; `images` is `[{"src": "drive:<UPLOADED_FILE_ID>", "fileId": "<UPLOADED_FILE_ID>", "shared": true}]`
- `list_permissions(file_id=<UPLOADED_FILE_ID>)` shows an `anyone`/`reader` permission still present
- 🔍 Visual check: the pixel image renders in the doc

**Cleanup:** delete the created doc; `remove_permission` the `anyone` grant, then delete the uploaded image file

**Result (2026-09-04) ✅ PASS**
Pre-uploaded image via upload_local_file, then create_doc with drive: reference + revoke_sharing=False. Response images=[{"src":"drive:...", "fileId":..., "shared":true}] exact match. list_permissions confirmed anyone/reader still present. Doc+permission+image cleaned up.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a persistent anyone share; ran before the user's explicit sharing approval.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: I uploaded the pixel, then create_doc used drive:<id> with revoke_sharing=False. images was exactly [{src:"drive:<id>", fileId:<id>, shared:true}], and list_permissions showed anyoneWithLink/reader. The screenshot (tc-doc151) shows the dot. Cleanup: anyone permission removed, doc and image trashed.

---

### TC-DOC152: `insert_local_images` now revokes its temporary share by default (behavior change from #332) ⚠️ local-filesystem ⚠️ destructive

**Prerequisite:** doc must contain a plain-text marker, e.g. write `"Marker: IMGMARKERONE"` via `write_doc_content` first

**Prompt**
**Playwright: required**
> "Insert <repo-root>/docs/qa/fixtures/qa-fixture-pixel.png at marker IMGMARKERONE in doc {DOC_ID}"

Tool call: `insert_local_images(doc_id=DOC_ID, images=[{"marker": "IMGMARKERONE", "local_path": "<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png"}])`

**Checks**
- `results[0]` has `fileId`, `index`, `shared: false`, no `revoke_error`
- `list_permissions(file_id=<results[0].fileId>)` shows no `anyone` permission — this is a **behavior change** from #332's original shipped version, which always left the file shared; existing callers relying on the old always-shared behavior need `revoke_sharing=False` now
- 🔍 Visual check: the pixel image renders in place of the marker text

**Cleanup:** delete the uploaded image file; write fixture content back

**Result (2026-08-02) ⚠️ PARTIAL — live via the actual `insert_local_images` MCP tool**, run against a scratch doc (not the shared fixture doc) containing `Marker: IMGMARKERONE`. Note: the tool now requires `folder_id` ("folder_id is required (no server default folder configured)" when omitted) — this test case's own tool-call example above doesn't pass one; worth updating the case text separately, not blocking. With `folder_id` supplied: `results[0]` had `fileId`, `index`, `shared: false`, no `revoke_error`; `list_permissions` on the uploaded file showed no `anyone` permission, confirming the new revoke-by-default behavior change from #332. Visual check not captured (structural/permission checks were conclusive); scratch doc and uploaded image trashed after the check.
**Corrected (2026-10-17, #1044 audit):** the visual check wasn't captured.

**Result (2026-09-04) ✅ PASS**
insert_local_images (default revoke_sharing) on scratch doc with "Marker: IMGMARKERONE": results[0] had fileId, index, shared:false, no revoke_error. list_permissions confirmed no anyone grant — new default-revoke behavior change from #332 confirmed. Doc+image trashed.

**Result (2026-10-04) ⚠️ PARTIAL — Kit, PR #903 round 1 (`8a634db`).** Regression check of the success path after the revoke moved into `_revoke_shares()`. Live `insert_local_images` with `folder_id` on a scratch doc holding `Marker: IMGMARKERONE` returned `results[0]` with `fileId`, `index: 9`, `shared: false`, and no `revoke_error`. `list_permissions` on the image showed no `anyone` grant. The visual check was done structurally, not with Playwright: `get_doc_as_markdown` showed `Marker: ![](…)`, an inline image where the marker was. The doc and image were trashed.
**Corrected (2026-10-17, #1044 audit):** the visual check was replaced by `get_doc_as_markdown`.

**Result (2026-10-04) ✅ PASS — Kit, PR #903 round 2 (`4e392c3`).** Re-run after the round 2 restructure moved the success path into the new `try`, against the reconnected kit server. `results[0]` had `fileId`, `index: 9`, `shared: false`, and no `revoke_error`. `list_permissions` showed no `anyone` grant, and `get_doc_as_markdown` showed `Marker: ![](…)`. The doc and image were trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: I called insert_local_images as written, without folder_id; it succeeded and uploaded to the server default (Shared Drive root). results[0] had fileId, index 9, shared:false and no revoke_error. list_permissions showed no anyone grant. The screenshot (tc-doc152) shows "Marker: ·". Image trashed.

---

### TC-DOC153: A table-cell image renders between two text cells ⚠️ requires-oauth ⚠️ destructive

**Purpose:** an image in a table cell is embedded in its cell (#1073). Until #1073, #333's body-level-only image support dropped it silently: the cell came out empty, with no error and no `images` entry. The case also guards the cursor-never-advances hang an `Image` in `Cell.children` once risked (#509). The results before 2026-10-24 were recorded against the old checks (an empty image cell and no `images` key).

**Prompt**
**Playwright: required**
> "Create a Google Doc from this HTML: `<table><tr><td>Before</td><td><img src=\"https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png\"></td><td>After</td></tr></table>`"

**Checks**
- Call returns promptly, with no `error`
- `images` has one entry, for the logo URL, with no `error`
- `get_doc_structure`: cell 0 reads "Before" and cell 2 "After"
- Raw `documents().get()` read: cell 1's paragraph holds one `inlineObjectElement` and no text
- Playwright: the Google logo shows in the middle cell

**Cleanup:** delete the created doc

**Result (2026-08-02) ✅ PASS — live via the actual `create_doc` MCP tool.** Call returned immediately with no `error` and no `images` key. `get_doc_structure` confirmed the table's cell 0 text is "Before", cell 2 text is "After", and cell 1 (the image cell) is empty (`""`). Doc trashed after the check.

**Result (2026-09-04) ✅ PASS**
create_doc HTML table with image in a cell: no error. get_doc_structure: cell 0 "Before", cell 2 "After", cell 1 (image) empty (""). No images key in response (image dropped at parse time, table-cell images still out of scope). No timeout/hang. Trashed.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
create_doc HTML table with an image in a cell: returned at once, no error, no `images` key. get_doc_structure: cell 0 "Before", cell 1 "", cell 2 "After". No hang. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`oauth`: All of the case's own checks are met: no error, no images key, cells "Before" / "" / "After", no hang. However, the table-cell image is dropped silently, which is the open known limitation #1073. Recorded as FAIL under the known-limitation rule; v0.9.2 recorded PASS.

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 1 (Kit) @ 79f19d4**
`kit`: create_doc returned promptly with no error, and `images` held one entry for the logo URL, with no `error`. `get_doc_structure`: cells `Before` / `` / `After`. Raw `documents().get()`: cell 1's paragraph holds one `inlineObjectElement` and no text. Playwright (`2026-10-24-tc-doc153.png`): the logo shows in the middle cell. Doc trashed.

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 2 (Kit) @ f9f6ee7**
`kit`: create_doc returned with no error; `images` held one logo entry with no `error`. Raw read: cells `Before` / `[IMG]` / `After`. Doc trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 3 (Kit) @ e3a6e69**
`kit`: no error; one logo entry with no `error`. Raw read: `Before` / `[IMG]` / `After`. Doc trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 4 (Kit) @ 5d2b4e8**
`kit`: no error; one logo entry with no `error`. Raw read: `Before` / `[IMG]` / `After`. Doc trashed.

---

### TC-DOC154: A `<pre>` block resumed after a nested table doesn't leave a spurious trailing whitespace-only paragraph ⚠️ requires-oauth ⚠️ destructive

**Background:** issue #443, found during PR #441's code review (issue #402: preserve whitespace/`&nbsp;`-only paragraphs during HTML→Docs conversion). `_emit_block_node` distinguishes a freshly-closed block's whitespace-only trailing text (kept, real content) from a *resumed* block's whitespace-only trailing flush (dropped as markup-formatting noise) — see TC-DOC138's background for the general mechanism. The `<pre>` close-tag handler built its `Paragraph` directly instead of going through `_emit_block_node`, so a `<pre>` resumed after a nested construct (e.g. a `<table>`) interrupting it kept trailing whitespace unconditionally, producing a spurious visible-space paragraph. Fixed by applying the same fresh-vs-resumed check to `<pre>`'s own trailing-whitespace decision, while still keeping a *fresh* `<pre>`'s whitespace unconditionally (every character inside `<pre>` is normally significant, unlike `<p>`).

**Prompt**
> "Create a Google Doc from this HTML: `<pre>code<table><tr><td>cell</td></tr></table>   </pre>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows exactly two content elements: a `<pre>`-styled paragraph reading "code", followed by a 1×1 table whose cell reads "cell" — no trailing empty/whitespace-only paragraph after the table
- Companion regression guard (same call, different content): `<pre>   </pre>` on its own (no interruption) still produces one paragraph whose text is the literal whitespace — confirms the fix didn't also start dropping a *fresh* `<pre>`'s own whitespace content

**Cleanup:** delete the created doc(s)

**Result (2026-08-04) ❌ FAIL — run live against PR #515 (issue #443).** Primary check and companion regression guard both PASS: `<pre>code<table>...</table>   </pre>` produces exactly "code" paragraph → 1×1 table ("cell") → the mandatory structural trailing paragraph every Doc requires, with no spurious visible-space paragraph; a standalone `<pre>   </pre>` (no interruption) still keeps its literal whitespace unconditionally. However, `/code-review high` on the same PR live-verified (via `html_to_ast` against the worktree's own code) and this session independently reproduced via the real Docs API a related, not-yet-fixed case the test prompt above doesn't cover: a resumed `<pre>` whose trailing whitespace-only flush follows genuinely *dropped* unsupported content (e.g. `<pre>code<table>...</table> <hr></pre>`) produces a doc structurally identical to the no-drop case — no boundary node at all, silently losing the paragraph break that `_emit_block_node`'s `preserve_if_empty` guarantees every other block type (`<p>`/`<li>`/headings) in an analogous situation. Sent back to Dev (PR #515 comment) rather than approved; not filed as a separate ticket since it's blocking on this same PR.

**Result (2026-08-05) ✅ PASS — re-verified live against fix commit `a465ea3`.** Round 1's finding is fixed: `<pre>code<table>...</table> <hr></pre>` (space survives after dropped `<hr>`) now renders a boundary paragraph `" \n"` immediately after the table; the zero-whitespace variant `<pre>code<table>...</table><hr></pre>` renders an empty boundary paragraph, matching the fix's own two new unit tests. Both of round 1's original checks (primary + companion regression guard) re-confirmed unaffected by the rewritten condition. `TestPreBlock` (10/10) passes. Note for future rounds: the first live-verification attempt this round produced a false FAIL — the `/mcp reconnect` had been run *before* this worktree was reset to the fix commit, so the tool call exercised stale pre-fix code (same class of gotcha as the PR #385 retro entry in `.claude/team-roles/qa.md`); caught by cross-checking against a direct script invocation of the same code path, not by the tool output itself. `qa-approved` applied.

**Result (2026-09-04) ✅ PASS**
<pre>code<table>...</table>   </pre>: exactly "code" -> 1x1 table("cell") -> structural trailing paragraph, no spurious whitespace paragraph. Companion <pre>   </pre> (fresh, no interruption): keeps literal whitespace unconditionally. Round-2 refinement also verified: <pre>code<table>...</table> <hr></pre> produces a boundary paragraph " \n" after the table (space survives after dropped <hr>) — fix confirmed. All 3 scratch docs trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: `<pre>code<table>…</table>   </pre>` gave "code", the spacer, the 1×1 "cell" table and only the terminal paragraph, with no whitespace paragraph. The companion `<pre>   </pre>` kept "   \n". Both docs trashed.

---

## Blockquote formatting (issue #476)

**Background:** `<blockquote>`/Markdown `>` previously converted to a plain, visually indistinguishable paragraph — see `docs/design/blockquote-representation.md` for the representation decision (a flat `blockquote_depth` field, mirroring `BulletItem.depth`, rather than a wrapper node) and why a left border (`paragraphStyle.borderLeft`) plus a depth-scaled indent (`paragraphStyle.indentStart`, 36pt per level) were chosen as the visual equivalent — Google Docs has no native blockquote paragraph style. `get_doc_structure` does not surface `indentStart`/`borderLeft` (only `namedStyleType`/`headingId` are extracted from `paragraphStyle`), so these checks need a raw `documents().get()` read — same pattern as `docs_style.md` TC-DOC146's table-cell-border verification.

### TC-DOC158: HTML blockquote gets a left border and indent; surrounding non-quoted content is unaffected ⚠️ destructive

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<blockquote><p>A quoted line</p></blockquote><p>Not quoted</p>`"

Tool call: `write_doc_content(doc_id={DOC_ID}, content="<blockquote><p>A quoted line</p></blockquote><p>Not quoted</p>", content_format="html")`

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows two paragraphs in order: "A quoted line" then "Not quoted"
- Raw `documents().get()` read: the "A quoted line" paragraph's `paragraphStyle` has `indentStart.magnitude == 36`, `indentFirstLine.magnitude == 36` (#1056), and a `borderLeft` present; the "Not quoted" paragraph's `paragraphStyle` has none of the three keys

**Cleanup:** write fixture content back

**Result (2026-08-07) ✅ PASS — run live against PR #546 round 2 (fix commit ba78e61) (issue #476).** Text order confirmed "A quoted line" then "Not quoted". Raw `documents().get()` read: "A quoted line" had `indentStart.magnitude == 36` and `borderLeft` present (gray, 3pt, solid); "Not quoted" had neither key.

**Result (2026-09-04) ✅ PASS**
Wrote HTML blockquote+plain paragraph. Text order "A quoted line"/"Not quoted" confirmed. Playwright screenshot (tc-doc158.png) confirmed "A quoted line" has visible gray left border+indent, "Not quoted" has neither. (Raw documents().get() indentStart/borderLeft numeric check attempted via scratch script but blocked — OAuth token refresh failed mid-session requiring an interactive consent flow this sandboxed environment can't complete; abandoned rather than hang. Visual confirmation used instead.)

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
Export shows the blockquote markers, but the indent isn't visible on single-line quotes (indentFirstLine not set).

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 1 (Kit) @ 13f4274**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. The call returned no error, and the text order was "A quoted line" then "Not quoted". In the raw read, "A quoted line" had `indentStart` 36 and `indentFirstLine` 36, plus a `borderLeft` (gray, 3pt, solid). "Not quoted" had none of the three keys.

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 2 (Kit) @ c118bdd**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. Same result as round 1: "A quoted line" at (36, 36) with `borderLeft` (gray, 3pt, solid), and "Not quoted" with none of the three keys.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`oauth`: Text order is "A quoted line" then "Not quoted", and get_doc_as_markdown gives "> A quoted line\n\nNot quoted". The screenshot (tc-doc158) shows a gray left border and indent on the quoted line only, including its first line. Not run: the raw documents().get() indentStart/indentFirstLine/borderLeft numeric check (needs the account's token in a scratch script, not available in this pass).

---

### TC-DOC159: Nested blockquote doubles the indent; both levels get the same border ⚠️ destructive

**Prompt**
> "Write this Markdown to doc {DOC_ID}: '> outer\n> > nested\n'"

Tool call: `write_doc_content(doc_id={DOC_ID}, content="> outer\n> > nested\n", content_format="markdown")`

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows two paragraphs in order: "outer" then "nested"
- Raw `documents().get()` read: "outer"'s `paragraphStyle.indentStart.magnitude == 36`; "nested"'s `paragraphStyle.indentStart.magnitude == 72`; each paragraph's `indentFirstLine.magnitude` equals its own `indentStart.magnitude` (#1056); both paragraphs have a `borderLeft` present with the same width and color

**Cleanup:** write fixture content back

**Result (2026-08-07) ✅ PASS — run live against PR #546 round 2 (fix commit ba78e61) (issue #476).** Text order confirmed "outer" then "nested". Raw `documents().get()` read: "outer" at `indentStart.magnitude == 36`, "nested" at `indentStart.magnitude == 72`; both had the identical `borderLeft` (gray, 3pt, solid).

**Result (2026-09-04) ⚠️ PARTIAL**
Live re-verification blocked by an OAuth token refresh failure (invalid_grant on a fresh script's _oauth_creds() call — infra/credential issue, not a QA finding; already-running MCP servers unaffected). Fallback: confirmed via git log that emitter.py's blockquote indentStart/borderLeft logic has not changed since the 2026-08-07 live PASS (commit ba78e61/39539dd) — the only intervening touch (f0ad989, Ruff lint adoption) diffs clean of any blockquote/indent/border lines and states "no functional behavior change". Result carried forward from 2026-08-07.
**Corrected (2026-10-17, #1044 audit):** nothing was run live: the result was carried forward from 2026-08-07.

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
Export shows the blockquote markers, but the indent isn't visible on single-line quotes (indentFirstLine not set).

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 1 (Kit) @ 13f4274**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. The call returned no error, and the text order was "outer" then "nested". In the raw read, "outer" had (`indentStart`, `indentFirstLine`) of (36, 36) and "nested" had (72, 72). Both had an identical `borderLeft` (gray, 3pt, solid, 8pt padding).

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 2 (Kit) @ c118bdd**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. Same result as round 1: "outer" at (36, 36), "nested" at (72, 72), with identical `borderLeft`s.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`oauth`: Text order is "outer" then "nested", and the export is "> outer\n\n> > nested". The screenshot (tc-doc159) shows nested indented further than outer, with matching gray borders. Not run: the raw documents().get() 36/72 numeric and borderLeft-equality check (same token reason).

---

### TC-DOC160: Blockquote wrapping a bulleted list still tags each item — text and list membership survive alongside the blockquote's own indent/border ⚠️ destructive

**Prompt**
> "Write this Markdown to doc {DOC_ID}: '> - Quoted item one\n> - Quoted item two\n'"

Tool call: `write_doc_content(doc_id={DOC_ID}, content="> - Quoted item one\n> - Quoted item two\n", content_format="markdown")`

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows both items as list paragraphs sharing one `listId`, with text exactly "Quoted item one" / "Quoted item two" (no leaked `>` or `-` markdown syntax)
- Raw `documents().get()` read: both paragraphs' `paragraphStyle` have a `borderLeft` present, `indentStart.magnitude == 72`, and `indentFirstLine.magnitude == 54`: the level-0 list indent (36/18) plus the 36pt quote indent (#1056; before it, the bullets call overwrote the quote indent and left 36/18)

**Cleanup:** write fixture content back

**Result (2026-08-07) ✅ PASS — run live against PR #546 round 2 (fix commit ba78e61) (issue #476).** Both items landed as list paragraphs sharing one `listId`, text exactly "Quoted item one" / "Quoted item two" with no leaked markdown syntax. Raw `documents().get()` read: both paragraphs had `borderLeft` present.

**Result (2026-09-04) ✅ PASS**
Wrote blockquote-wrapped bulleted list markdown. get_doc_structure: both items list paragraphs sharing one listId, text exactly "Quoted item one"/"Quoted item two", no leaked markdown syntax. Playwright screenshot (tc-doc160.png) confirmed visible left border spans both bulleted items.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 1 (Kit) @ 13f4274**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. The call returned no error. Both items are list paragraphs with the same `listId`, text exactly "Quoted item one" / "Quoted item two", nestingLevel 0. In the raw read, both had `indentStart` 72, `indentFirstLine` 54, and a `borderLeft`.

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 2 (Kit) @ c118bdd**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. Same result as round 1: both items share one `listId` at nestingLevel 0, with text intact, at `indentStart` 72 and `indentFirstLine` 54, each with a `borderLeft`.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`jay`: `write_doc_content` (markdown `> - Quoted item one / two`): no error. `get_doc_structure`: both items share one `listId`, nestingLevel 0, exact text, no leaked `>`/`-`. `get_doc_as_markdown` round-trips `> - …` for both. Not run: the raw `documents().get()` indent/border check (scratch script). On screen, TC-DOC229's run of the same shape showed a quoted level-0 glyph 36pt right of an unquoted one, with the gray bar.

---

## Oversized inline-image handling — `insert_inline_image` / `insert_local_images` / markdown-image embedding (#400)

**Background:** Google Docs' `insertInlineImage` rejects any image over ~25 megapixels with a raw `HttpError 400 "...The provided image is too large."` that names neither the actual limit nor the image's own size. `tools/docs/images.py` adds pre-validation (default: a clear error naming the limit and the image's actual size, before any upload/share/embed happens) and an opt-in `auto_downscale` param that resizes the image instead of failing — for sources whose bytes this server already has direct access to (`drive_file_id`, a `"drive:"` reference, or a local file path). A bare public `http(s)` uri can't be pre-validated this way (would mean fetching arbitrary external content just to check it) — it instead gets Google's own error message rewritten with the same explanation once the embed actually fails. See `docs/decisions/decision-pillow-image-dependency.md` for the full scope-boundary rationale.

**Setup (all cases below):** generate a throwaway oversized test PNG — 6000×6000 = 36 megapixels, safely over the 25MP limit — not committed to the repo (too large):
```
uv run python3 -c "from PIL import Image; Image.new('RGB', (6000, 6000), 'red').save('/tmp/qa-oversized.png')"
```

### TC-DOC161: `insert_inline_image` with an oversized `drive_file_id` fails fast with a clear, actionable error
**Setup:** upload the oversized PNG — `upload_local_file(local_path="/tmp/qa-oversized.png", parent_folder_id={FOLDER_ID}, name="qa-oversized.png")` — note the returned `fileId` as `{OVERSIZED_FILE_ID}`

**Prompt**
> "Insert the image at Drive file {OVERSIZED_FILE_ID} at index 1 in doc {DOC_ID}"

Tool call: `insert_inline_image(doc_id={DOC_ID}, index=1, drive_file_id={OVERSIZED_FILE_ID})`

**Checks**
- Returns `{"error": ...}` containing "36.0 megapixels", "25 megapixels", and "auto_downscale=True"
- `get_doc_structure` on `{DOC_ID}` is unchanged from before the call — no `insertInlineImage` reached the Docs API

**Cleanup:** trash the uploaded `{OVERSIZED_FILE_ID}` file

**Result (2026-08-09) ✅ PASS — run live against PR #554 (issue #400).** Error: "Image is 6000x6000 (36.0 megapixels), which exceeds Google Docs' inline-image limit of 25 megapixels (...). Resize it before inserting, or pass auto_downscale=True to have it resized automatically." `get_doc_structure` before/after calls were byte-identical.

**Result (2026-09-04) ✅ PASS**
insert_inline_image(drive_file_id=oversized 6000x6000). Error contained "36.0 megapixels", "25 megapixels", "auto_downscale=True". get_doc_structure before/after byte-identical — no insertInlineImage reached API.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** Fresh upload `qa-oversized-pr801.png` (6000x6000) into a scratch doc. The error named "36.0 megapixels", "25 megapixels" and "auto_downscale=True". Nothing was inserted (the follow-up TC-DOC162 call landed at index 1 on the untouched single-paragraph doc).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Uploaded a 6000x6000 PNG (named `qa-oversized-C.png`). `insert_inline_image(drive_file_id)` returned an error naming "36.0 megapixels", "25 megapixels" and "auto_downscale=True". `get_doc_structure` was identical before and after.

---

### TC-DOC162: `insert_inline_image` `auto_downscale=True` resizes and embeds a copy, leaving the original untouched ⚠️ requires-oauth ⚠️ destructive
**Setup:** same as TC-DOC161 — note `{OVERSIZED_FILE_ID}`

**Prompt**
**Playwright: required**
> "Insert the image at Drive file {OVERSIZED_FILE_ID} at index 1 in doc {DOC_ID}, resizing it automatically if it's too large"

Tool call: `insert_inline_image(doc_id={DOC_ID}, index=1, drive_file_id={OVERSIZED_FILE_ID}, auto_downscale=True)`

**Checks**
- Call succeeds with no API error; response includes `resized_file_id`, distinct from `{OVERSIZED_FILE_ID}`
- `get_file_metadata({resized_file_id})` name is `"qa-oversized.png (resized)"`
- `{OVERSIZED_FILE_ID}` itself still exists, untrashed, unmodified (the original is never touched — no `update()`/`delete()` against it)
- 🔍 Visual check in Google Docs: an image renders at the insertion point

**Cleanup:** delete the inserted image range (`delete_doc_range` on its index span); trash both `{OVERSIZED_FILE_ID}` and `{resized_file_id}`

**Result (2026-08-09) ✅ PASS — run live against PR #554 (issue #400).** `resized_file_id` returned, distinct from the original; `get_file_metadata` on it read name `"qa-oversized.png (resized)"`; original file's checksum/size/trashed status unchanged after the call. Playwright screenshot of the doc confirmed the image rendered at the insertion point. (Note: the fixture doc has unrelated stray header content from earlier header/footer test runs, visible above the inserted image in the screenshot — pre-existing fixture pollution, not caused by this PR.)

**Result (2026-09-04) ✅ PASS**
insert_inline_image(auto_downscale=True) succeeded, resized_file_id distinct from original. get_file_metadata: resized name "qa-oversized.png (resized)"; original file untouched (same checksum/size as upload). Playwright screenshot (tc-doc162.png) confirmed large red image rendered at insertion point. Range deleted, both files trashed.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** This exercises the parent-folder fallback PR #801 folded into `downscale_drive_file`. `resized_file_id` differed from the original, and `get_file_metadata` gave name `"qa-oversized-pr801.png (resized)"` in the same parent folder as the original. The original was unchanged (size 119593, same as the local file, untrashed). Playwright: the red image rendered at the insertion point. Both files and the doc trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a persistent anyone share; ran before the user's explicit sharing approval.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `auto_downscale=True`: no error. `resized_file_id` differs from the original, and its name is `qa-oversized-C.png (resized)` (the suffix follows my upload's name), in the same folder. The original is untrashed: size 119588, same md5. Playwright: a red image renders at the insertion point (`2026-10-19-tc-doc162.png`). Resized copy trashed.

---

### TC-DOC163: `insert_inline_image` with a too-large public `uri` gets Google's error rewritten with the size-limit explanation, not pre-validated
**Setup:** temporarily share the oversized PNG for a public URL — upload it (`upload_local_file` as in TC-DOC161), then `share_file(file_id={OVERSIZED_FILE_ID}, permissions=[{"type": "anyone", "role": "reader"}])`, and use the `web_content_link` from the `upload_local_file` response as `{OVERSIZED_WEB_CONTENT_LINK}`. `upload_local_file` returns Drive's `webContentLink` as `web_content_link` for a new non-converted upload (#511).

**Prompt**
> "Insert the image at uri '{OVERSIZED_WEB_CONTENT_LINK}' at index 1 in doc {DOC_ID}"

Tool call: `insert_inline_image(doc_id={DOC_ID}, index=1, uri="{OVERSIZED_WEB_CONTENT_LINK}")`

**Checks**
- Returns `{"error": ...}` containing Google's own raw "too large" message *and* the appended "25 megapixels" / limits-URL explanation — confirms the rewrite appends rather than replaces the original message
- Error does not mention `auto_downscale` (not supported for a bare `uri` source)

**Cleanup:** remove the `anyone` permission from `{OVERSIZED_FILE_ID}`; trash the file

**Result (2026-08-09) ✅ PASS — run live against PR #554 (issue #400).** Error: `<HttpError 400 ... "Invalid requests[0].insertInlineImage: The provided image is too large."> This is very likely Google Docs' inline-image limit of 25 megapixels (...) — check the image's pixel dimensions and resize it before retrying.` — Google's raw message preserved, explanation appended, no mention of `auto_downscale`.

**Result (2026-09-04) ✅ PASS**
insert_inline_image(uri=shared oversized file's direct-download link). Error: Google's raw "The provided image is too large." preserved, plus appended "25 megapixels or 50MB" explanation. No mention of auto_downscale. Permission removed, file trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a persistent anyone share; ran before the user's explicit sharing approval.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Shared the original anyone/reader and called `uri=https://drive.google.com/uc?export=download&id=…`. The error keeps Google's raw "The provided image is too large." and appends "…25 megapixels or 50MB…". No mention of `auto_downscale`. Permission removed, file trashed.

---

### TC-DOC164: `insert_local_images` with an oversized local image fails fast per-image, without ever uploading it
**Setup:** create a doc with a marker — `write_doc_content(doc_id={DOC_ID}, content="<p>IMGMARKERONE</p>")`

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERONE', local_path '/tmp/qa-oversized.png', into folder {FOLDER_ID}"

Tool call: `insert_local_images(doc_id={DOC_ID}, images=[{"marker": "IMGMARKERONE", "local_path": "/tmp/qa-oversized.png"}], folder_id={FOLDER_ID})`

**Checks**
- `results` has one entry with an `error` containing "36.0 megapixels" / "25 megapixels", no `fileId`
- `list_files(folder_id={FOLDER_ID}, query="qa-oversized.png")` returns no results — the oversized file was never uploaded
- `get_doc_structure` shows the "IMGMARKERONE" marker text still present, unchanged

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-09) ✅ PASS — run live against PR #554 (issue #400).** `results[0].error` contained "36.0 megapixels"/"25 megapixels", no `fileId`. `list_files(folder_id={FOLDER_ID}, mime_type="image/png")` returned empty — no upload occurred. Marker paragraph unchanged.

**Result (2026-09-04) ✅ PASS**
insert_local_images(oversized local path, no auto_downscale): results[0].error contained "36.0 megapixels"/"25 megapixels", no fileId. list_files(mime_type=image/png) returned empty — no upload. Marker text unchanged.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** `results` entry: "Image is 6000x6000 (36.0 megapixels)… 25 megapixels… auto_downscale=True", no `fileId`. Only today's `qa-fixture-pixel.png` uploads were new in the folder; the `qa-oversized*` files there date from 2026-09-04 (older pollution). The marker text was unchanged.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `insert_local_images` with the oversized local PNG: `results[0].error` has "36.0 megapixels"/"25 megapixels", no `fileId`. My scratch upload folder listed empty, and the `IMGMARKERONE` marker was unchanged.

---

### TC-DOC165: `insert_local_images` `auto_downscale=True` uploads and embeds a resized copy ⚠️ requires-oauth ⚠️ destructive
**Setup:** create a doc with a marker — `write_doc_content(doc_id={DOC_ID}, content="<p>IMGMARKERONE</p>")`

**Prompt**
**Playwright: required**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERONE', local_path '/tmp/qa-oversized.png', into folder {FOLDER_ID}, auto-downscaling if too large"

Tool call: `insert_local_images(doc_id={DOC_ID}, images=[{"marker": "IMGMARKERONE", "local_path": "/tmp/qa-oversized.png"}], folder_id={FOLDER_ID}, auto_downscale=True)`

**Checks**
- `results` has one entry with no `error`, a `fileId`, `downscaled: true`, and `index` equal to the marker paragraph's `startIndex` (from a prior `get_doc_structure`)
- The uploaded file's name is `"qa-oversized.png"` (unsuffixed — unlike TC-DOC162's drive_file_id path, there's no original-file naming collision to avoid here)
- 🔍 Visual check in Google Docs: an image renders where the marker used to be

**Cleanup:** write fixture content back over `{DOC_ID}`; trash the uploaded image file

**Result (2026-08-09) ✅ PASS — run live against PR #554 (issue #400).** `results[0]` had no `error`, `fileId` present, `downscaled: true`, `index` equal to the marker paragraph's `startIndex` (1). Uploaded file name was unsuffixed `"qa-oversized.png"`. Playwright screenshot confirmed the image rendered where the marker had been.

**Result (2026-09-04) ✅ PASS**
insert_local_images(auto_downscale=True): results[0] no error, fileId, downscaled:true, index=1=marker's startIndex. Uploaded file name unsuffixed "qa-oversized.png". Playwright screenshot (tc-doc165.png) confirmed image rendered where marker was. Uploaded file trashed.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** Alone: `fileId`, `downscaled: true`, `shared: false`, `index` 10 = the marker's `startIndex`. Uploaded name unsuffixed `qa-oversized.png`. Playwright: the red image rendered where the marker was. **Transient seen, not a defect:** the first attempt batched this image with TC-DOC167's ~47MB resized copy in one call. Both uploads succeeded, but Docs rejected the atomic batch with "There was a problem retrieving the image". Each passed alone, and the identical two-image call passed on a fresh doc right after. PR #801 doesn't touch the embed batch (only pre-upload validation and where the downscale runs), so this is Google's fetch of a near-limit image flaking, not a regression. Uploads trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: With `auto_downscale=True`: `fileId`, `downscaled: true`, `shared: false`, `index` 1 (the marker's startIndex). Uploaded name is `qa-oversized.png`, unsuffixed. Playwright: the red image is where the marker was (`tc-doc165.png`). Upload trashed.

---

### TC-DOC166: An oversized local-path image in markdown content fails per-image without blocking the rest of the doc ⚠️ requires-oauth ⚠️ destructive
**Prompt**
> "Write this Markdown to doc {DOC_ID}: 'Before\n\n![Big](/tmp/qa-oversized.png)\n\nAfter'"

Tool call: `write_doc_content(doc_id={DOC_ID}, content="Before\n\n![Big](/tmp/qa-oversized.png)\n\nAfter", content_format="markdown")`

**Checks**
- Call succeeds with no API error; `get_doc_structure` shows "Before" and "After" paragraphs present
- Response's `images` has one entry for `/tmp/qa-oversized.png` with an `error` containing "36.0 megapixels" / "25 megapixels", no `fileId`
- No file named "qa-oversized.png" was uploaded to the server's default folder

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-09) ✅ PASS (run via `create_doc` substitute) — run live against PR #554 (issue #400).** This worktree's server has no `DRIVE_FOLDER_ID` configured, so `write_doc_content` itself returned `"folder_id is required to upload a local image (no server default folder configured)"` before ever reaching the size check — an environment gap, not a PR defect (`write_doc_content` has no per-call folder override by design). Re-ran the identical markdown content through `create_doc(folder_id={FOLDER_ID}, ...)` instead, which shares the same `_apply_doc_content` code path and does accept an explicit folder: call succeeded with no API error, "Before"/"After" paragraphs both present, `images[0].error` contained "36.0 megapixels"/"25 megapixels", and no file was uploaded to the target folder.

**Result (2026-09-04) ✅ PASS**
create_doc(folder_id, markdown with oversized local-path image) — write_doc_content itself lacks a folder override so create_doc used instead (same _apply_doc_content path). No top-level error; "Before"/"After" paragraphs both present. images[0].error contained "36.0 megapixels"/"25 megapixels", no fileId. No file uploaded to target folder. Trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Ran `write_doc_content` directly (the server has a default folder). No top-level error. "Before" and "After" paragraphs present. `images[0].error` has "36.0 megapixels"/"25 megapixels", no `fileId`. `search_files("qa-oversized")` found nothing.

---

### TC-DOC167: `insert_local_images` — an image under the megapixel pre-check but over Google's byte-size limit is now caught by pre-validation, not just the batchUpdate fallback
**Background:** `check_image_bytes`/`check_dimensions` used to only enforce Google's ~25-megapixel limit, not the ~50MB file-size limit `images.py`'s own module docstring also cites from Google's docs — so an image under 25 megapixels but with a very large byte size (e.g. low-compressibility noise data) passed pre-validation silently and reached the real `batchUpdate` call, which Google could still reject as "too large" (see the 2026-08-09 Result below, which documents that pre-#562 behavior — it predates this fix and is kept for history, not as the current expected outcome). Issue #562 added a `check_file_size` byte-size check (Google's documented ~50MB ceiling) alongside the megapixel one, so this exact case is now caught *before* any upload, the same way an over-megapixel image already was. `downscale_image_bytes` also gained a byte-size-driven shrink loop so `auto_downscale=True` has an actual effect here too, not just for the megapixel case.

**Setup:** generate a real, Pillow-decodable PNG that stays under the megapixel limit but is large in bytes — noise data compresses poorly, so this reliably produces a large file:
```
uv run python3 -c "
import os
from PIL import Image
w, h = 4800, 5000  # 24.0 megapixels — under the 25MP pre-check
img = Image.frombytes('RGB', (w, h), os.urandom(w*h*3))
img.save('/tmp/qa-bigfile.png', compress_level=1)
"
```
(Produces a ~75MB file, safely over Google's documented 50MB ceiling while staying under the megapixel pre-check.)

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERBIG', local_path '/tmp/qa-bigfile.png', into folder {FOLDER_ID}"

Tool call: `insert_local_images(doc_id={DOC_ID}, images=[{"marker": "IMGMARKERBIG", "local_path": "/tmp/qa-bigfile.png"}], folder_id={FOLDER_ID})`

**Checks**
- `results[0]` has **no** `fileId` (pre-validation now catches it *before* any upload) and an `error` naming the file's actual size in MB and Google's 50MB limit (`too_large_bytes_message` — mirrors `too_large_message`'s megapixel-case wording, including the `auto_downscale=True` suggestion)
- No new file appears in `{FOLDER_ID}` — confirm via `list_files(folder_id={FOLDER_ID})` or equivalent, since nothing should have been uploaded
- `get_doc_structure` shows the "IMGMARKERBIG" marker text still present, unchanged

**Follow-up check (`auto_downscale=True`):** re-run the same call with `auto_downscale=True` added — `results[0]` should now succeed with `downscaled: true` and a `fileId`, and the uploaded copy's byte size should be at or under 50MB (the megapixel-only downscale path this call would have hit pre-#562 was a no-op here, since 24MP is already under the 25MP limit — this confirms the new byte-size-driven shrink loop in `downscale_image_bytes` is what actually did the work).

**Cleanup:** if `auto_downscale=True` was run, trash the uploaded file (`results[0].fileId`); write fixture content back over `{DOC_ID}`

**Result (2026-08-09) ✅ PASS — run live against PR #554 round 2 (fix commit badad67, issue #400). Predates #562 — see the note in Background above; this result documents the pre-#562 rewritten-error batchUpdate-fallback behavior that #562's pre-validation now supersedes for this specific case.** First attempt (immediately after a reconnect that had happened *before* the worktree was synced to `badad67`) reproduced the exact stale-reconnect trap this project's QA process has hit before — the error came back unrewritten. A second reconnect (after confirming the worktree was already on the fix commit) plus a retry got the correctly rewritten error: `doc edit failed: <HttpError 400 ... "The provided image is too large."> This is very likely Google Docs' inline-image limit of 25 megapixels (...) — check the image's pixel dimensions and resize it before retrying.` Marker text confirmed unchanged after the failed call.

**Result (2026-08-12) ✅ PASS — run live against PR #580 (issue #562, commit `048fc97`), both the main case and the `auto_downscale=True` follow-up.** Generated a real 4900x4900 (24.01MP, under the 25MP pre-check) noise PNG at ~76.0MB. Main call (`auto_downscale` omitted): `results[0]` had no `fileId` and `error` = `"Image is 76.0MB, which exceeds Google Docs' inline-image file-size limit of 50MB (...). Resize it before inserting, or pass auto_downscale=True to have it resized automatically."` — confirmed via `list_files(folder_id={FOLDER_ID}, mime_type="image/png")` that nothing was uploaded, and `get_doc_structure` showed the marker text unchanged. Follow-up call with `auto_downscale=True`: succeeded — `results[0]` had `fileId`, `downscaled: true`, `shared: false`, and an `index`; `get_file_metadata` on the uploaded file showed `size: "47357544"` (~47.4MB, under the 50MB ceiling); `get_doc_structure` confirmed the marker text was replaced. This live-verifies the new byte-size-driven shrink loop in `downscale_image_bytes` actually converges for a realistic low-compressibility image, one of this round's code-review findings ([current round's code review](https://github.com/khuisman/mcp-gee-sweet/pull/580) — the loop has no postcondition check if it doesn't converge within its bounded attempts, filed as a non-blocking follow-up since this real-world case converges on the very first resize). Uploaded file trashed and fixture doc content restored after.

**Result (2026-09-04) ✅ PASS**
Generated real ~76MB 4800x5000 (24.0MP, under 25MP pre-check) noise PNG. Main call (no auto_downscale): results[0] no fileId, error = "Image is 76.0MB, which exceeds ... 50MB limit ... auto_downscale=True" — pre-validation caught it before any upload; list_files confirmed nothing uploaded; marker unchanged. Follow-up call with auto_downscale=True: succeeded, fileId, downscaled:true; uploaded copy's size 47,361,943 bytes (~45.2MB), under 50MB — confirms the byte-size-driven shrink loop converges. Uploaded file trashed, fixture doc restored to seed state.

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** A 4800x5000 noise PNG (~76MB). Main call: "Image is 76.0MB, which exceeds… 50MB… auto_downscale=True", no `fileId`, nothing uploaded, marker unchanged. With `auto_downscale=True`: `fileId`, `downscaled: true`, uploaded copy 47,361,547 bytes (under 50MB). (See TC-DOC165's note: the first `auto_downscale` attempt batched with another image hit a transient Docs fetch error; alone and on retry it passed.) Uploads trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: 4800x5000 noise PNG, 76MB. Main call: "Image is 76.0MB, which exceeds … 50MB … auto_downscale=True", no `fileId`. Folder empty after `refresh_cache`, marker unchanged. With `auto_downscale=True`: `fileId`, `downscaled: true`, uploaded size 47,362,029 bytes (under 50MB). Upload trashed.

---

## `update_doc_from_file` (#341)

`update_doc_from_file(doc_id, local_path, content_format=None, ...)` combines `create_doc_from_file`'s server-side file reading (extension inference, same error shapes) with `write_doc_content`'s in-place clear+replace mechanism — both now share one implementation via `_replace_doc_content`. Like `write_doc_content`/`insert_doc_text`/`style_doc_range`, the tool itself is auth-agnostic (it never creates a Drive file, only edits an existing doc's content) — none of the cases below are tagged `⚠️ requires-oauth`, matching those siblings' own convention (see the note at line 2053 above). All cases operate directly on the shared fixture doc `{DOC_ID}`, the same convention `write_doc_content`'s own TC-DOC39–43 use.

### TC-DOC168: `update_doc_from_file` replaces `{DOC_ID}`'s content in place from a local .md file ⚠️ destructive
**Setup:** `get_file_metadata(file_id={DOC_ID})`, note `name`/`parents`/`webViewLink` for comparison after

**Prompt**
> "Update Google Doc {DOC_ID} from the file <repo-root>/docs/qa/fixtures/tc-d195-create-doc.md"

**Checks**
- Returned `docId` equals `{DOC_ID}`, `web_link` present, no `error`
- `get_doc_structure` shows HEADING_1 "QA Test Document", bold/italic runs, `☑`/`☐` bullet items, and the Col A/Col B table from the fixture — matching what TC-DOC44 confirms `create_doc_from_file` produces from the same file
- `get_file_metadata(file_id={DOC_ID})` afterward shows the same `name`/`parents`/`webViewLink` as the Setup snapshot — confirms the doc's identity and Drive location were preserved (no new Doc was minted), only its content changed

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-10) ✅ PASS — run live against PR #564 (issue #341).** `update_doc_from_file` returned `docId` matching `{DOC_ID}` and a `web_link`, no `error`. `get_doc_structure` afterward showed HEADING_1 "QA Test Document", bold "bold"/italic "italic" runs, `☑ Task complete`/`☐ Task pending` bullet items, and the Col A/Col B table — matches TC-DOC44's own `create_doc_from_file` output for the same fixture file. `get_file_metadata` before and after showed identical `name`/`parents`/`webViewLink` — doc identity and location preserved.


**Result (2026-09-04) ✅ PASS**
update_doc_from_file(tc-d195-create-doc.md) on DOC_ID: returned docId matching DOC_ID, no error. get_doc_structure matches TC-DOC44's create_doc_from_file output exactly (HEADING_1, bold/italic runs, ☑/☐ items, Col A/Col B table). get_file_metadata before/after identical name/parents/webViewLink — doc identity/location preserved.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
update_doc_from_file(tc-d195-create-doc.md) on DOC_ID: docId matched, web_link present, no error. get_doc_structure matches TC-DOC44's output (HEADING_1, bold/italic, ☑/☐ items, Col A/Col B table). get_file_metadata before/after: same name/parents/webViewLink.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `update_doc_from_file(tc-d195-create-doc.md)`: `docId` matches, `web_link` present, no error. Structure: HEADING_1 "QA Test Document", bold/italic runs, ☑/☐ items, Col A/Col B table. `get_file_metadata` before and after: same name, parents and webViewLink.

### TC-DOC169: `update_doc_from_file` with a local .html file ⚠️ destructive
**Prompt**
> "Update Google Doc {DOC_ID} from the file <repo-root>/docs/qa/fixtures/tc-d196-create-doc.html"

**Checks**
- Returned `docId` equals `{DOC_ID}`, no `error`
- `get_doc_structure` shows HEADING_2 "From HTML file" and paragraph "Content paragraph." — matching what TC-DOC45 confirms for the same file via `create_doc_from_file`

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-10) ✅ PASS — run live against PR #564 (issue #341).** Returned `docId` matching `{DOC_ID}`, no `error`. `get_doc_structure` afterward showed HEADING_2 "From HTML file" and paragraph "Content paragraph." — matches TC-DOC45's own `create_doc_from_file` output for the same fixture file.


**Result (2026-09-04) ✅ PASS**
update_doc_from_file(tc-d196-create-doc.html): docId matched, no error. get_doc_structure: HEADING_2 "From HTML file", paragraph "Content paragraph." — matches TC-DOC45.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
update_doc_from_file(tc-d196-create-doc.html): docId matched, no error. get_doc_structure: HEADING_2 "From HTML file", paragraph "Content paragraph."

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `update_doc_from_file(tc-d196-create-doc.html)`: no error. HEADING_2 "From HTML file" and paragraph "Content paragraph."

### TC-DOC170: `update_doc_from_file` file not found
**Prompt**
> "Update Google Doc {DOC_ID} from the file ~/does-not-exist.md"

**Checks**
- Returns `{"error": "File not found: ..."}` — no exception raised
- Fixture doc `{DOC_ID}` is left completely untouched (`get_doc_content` unchanged) — the file-existence check runs before any Docs API call

**Result (2026-08-10) ✅ PASS — run live against PR #564 (issue #341).** Returned `{"error": "File not found: ~/does-not-exist.md"}`, no exception. `get_doc_content` before and after the call returned byte-identical content (including headers/footers) and the same `modified_time`.


**Result (2026-09-04) ✅ PASS**
update_doc_from_file('~/does-not-exist.md') returned {"error":"File not found: ~/does-not-exist.md"}, no exception. get_doc_content confirmed doc unchanged (still HEADING_2/paragraph from DOC169).

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
update_doc_from_file('~/does-not-exist.md') returned {"error": "File not found: ~/does-not-exist.md"}, no exception. get_doc_content unchanged.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `~/does-not-exist.md` returned `{"error":"File not found: ~/does-not-exist.md"}`. `get_doc_content` unchanged.

### TC-DOC171: `update_doc_from_file` unsupported extension with no override returns an error, doc untouched
**Setup:** create a local file `qa-update.txt` with arbitrary plain text

**Prompt**
> "Update Google Doc {DOC_ID} from the file <path-to>/qa-update.txt"

**Checks**
- Returns `{"error": "Unsupported file extension '.txt'. ..."}` mentioning `.txt` and that `content_format` can be passed explicitly
- Fixture doc `{DOC_ID}` is left untouched (no Docs API call made — the extension check runs before the doc_id lookup, same as the file-not-found case above)

**Cleanup:** delete the local `qa-update.txt` file

**Result (2026-08-10) ✅ PASS — run live against PR #564 (issue #341).** Returned `{"error": "Unsupported file extension '.txt'. Use .md or .html/.htm, or pass content_format explicitly."}`. `get_doc_content` before and after the call was byte-identical with the same `modified_time` — no Docs API call was made.


**Result (2026-09-04) ✅ PASS**
update_doc_from_file(qa-update.txt, no override) returned {"error":"Unsupported file extension '.txt'. Use .md or .html/.htm, or pass content_format explicitly."}. get_doc_content confirmed doc untouched — no Docs API call made.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
update_doc_from_file(qa-update.txt) returned {"error": "Unsupported file extension '.txt'. Use .md or .html/.htm, or pass content_format explicitly."}. get_doc_content unchanged.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `qa-update.txt` returned "Unsupported file extension '.txt'. Use .md or .html/.htm, or pass content_format explicitly." Structure unchanged.

### TC-DOC172: `update_doc_from_file` `content_format` explicitly overrides an unrecognized extension ⚠️ destructive
**Setup:** create a local file `qa-update-override.txt` containing `# Overridden Heading\n\nParagraph text.\n`

**Prompt**
> "Update Google Doc {DOC_ID} from the file <path-to>/qa-update-override.txt with content_format='markdown'"

**Checks**
- No `error`; `get_doc_structure` shows HEADING_1 "Overridden Heading" and paragraph "Paragraph text."

**Cleanup:** write fixture content back over `{DOC_ID}`; delete the local `qa-update-override.txt` file

**Result (2026-08-10) ✅ PASS — run live against PR #564 (issue #341).** Called with `content_format='markdown'` on `qa-update-override.txt`; no `error`. `get_doc_structure` afterward showed HEADING_1 "Overridden Heading" and paragraph "Paragraph text." Fixture content restored and local file deleted afterward.

**Result (2026-09-04) ✅ PASS**
update_doc_from_file(qa-update-override.txt, content_format='markdown') succeeded, no error. get_doc_structure: HEADING_1 "Overridden Heading", paragraph "Paragraph text." Fixture restored after.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
update_doc_from_file(qa-update-override.txt, content_format='markdown'): no error. get_doc_structure: HEADING_1 "Overridden Heading", paragraph "Paragraph text." Fixture restored to setup.md's seed HTML via write_doc_content afterward.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `qa-update-override.txt` with `content_format='markdown'`: HEADING_1 "Overridden Heading" and paragraph "Paragraph text."

---

## `get_doc_as_markdown`

### TC-DOC173: Basic export — headings, styled runs, links
**Setup:** `write_doc_content(doc_id={DOC_ID}, content_format='markdown', content="# Title\n\nSome **bold** and *italic* and ~~strike~~ text with a [link](https://example.com).\n")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- Returns `doc_id`, `title`, and `markdown`
- `markdown` contains `# Title`
- `markdown` contains `**bold**`, `*italic*`, `~~strike~~`, and `[link](https://example.com)`. The write path renders `~~strike~~` as a struck-through run since #1228 (markdown-it's GFM strikethrough rule), and the export writes it back as `~~strike~~`

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ❌ FAIL — run live against PR #591 (issue #300).** `markdown` returned `"# Title\n\nSome **bold** and *italic* and ~~strike~~ text with a [link](https://example.com).\n\n"` — all checks satisfied.
**Corrected (2026-10-17, #1044 audit):** the Markdown write path has no strikethrough support (`~~strike~~` stays literal text in the Doc), so this export check passed on literal tildes, not on a struck-through run. The 2026-10-17 result above records the same thing as FAIL. Tracked in #1077.

**Result (2026-09-04) ❌ FAIL**
get_doc_as_markdown basic export: returned doc_id/title/markdown = "# Title\n\nSome **bold** and *italic* and ~~strike~~ text with a [link](https://example.com).\n\n" — exact match.
**Corrected (2026-10-17, #1044 audit):** same as the 2026-08-15 correction above. Tracked in #1077.

**Result (2026-10-17) ❌ FAIL — v0.9.2 release pass**
Stale TC: ~~strike~~ was never converted on write; the export correctly escapes the literal text as \~\~strike\~\~.

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`jay`: The export is `# Title\n\nSome **bold** and *italic* and \~\~strike\~\~ text with a [link](https://example.com).` The `~~strike~~` check fails because strikethrough is never converted on write. Known limitation, open #1077.

---

### TC-DOC174: Nested, ordered, and checked bullet lists
**Setup:** `write_doc_content(doc_id={DOC_ID}, content_format='markdown', content="- top\n    - nested\n- [x] done\n- [ ] todo\n\n1. first\n2. second\n")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` shows "nested" indented under "top" (e.g. two leading spaces before its `- ` marker)
- `markdown` contains `- [x] done` and `- [ ] todo`
- `markdown` contains an ordered-list marker (`1. `) for both "first" and "second"
- No blank line between consecutive list items (a "tight" list)

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** `markdown` returned `"- top\n  - nested\n- [x] done\n- [ ] todo\n1. first\n1. second\n\n"`. All stated checks satisfied literally (both ordered items are marked `1. ` — valid CommonMark, since ordered-list rendering is driven by the first item's number, not a defect). Note for a future test-case tightening pass (not filed as a ticket — matches its own written check): no blank line separates the unordered and ordered lists on the round-trip, unlike the source's blank line.

**Result (2026-09-04) ✅ PASS**
Nested/ordered/checked lists export: markdown = "- top\n  - nested\n- [x] done\n- [ ] todo\n1. first\n1. second\n\n" — nested indented under top, checkboxes correct, ordered markers present (both "1." — valid CommonMark, numbering driven by first item), tight list (no blank line between items).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `- top\n  - nested\n- [x] done\n- [ ] todo\n1. first\n1. second\n\n`. Every check is met. Observation under New findings: there is no blank line between the bullet list and the ordered list.

---

### TC-DOC175: Blockquote nesting
**Setup:** `write_doc_content(doc_id={DOC_ID}, content_format='markdown', content="> a quoted line\n>> double quoted\n")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains a line prefixed `> ` for "a quoted line"
- `markdown` contains a line prefixed `> > ` for "double quoted"

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** `markdown` returned `"> a quoted line\n\n> > double quoted\n\n"` — both checks satisfied.

**Result (2026-09-04) ✅ PASS**
Blockquote nesting export: markdown contains "> a quoted line" and "> > double quoted".

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `> a quoted line\n\n> > double quoted\n\n`

---

### TC-DOC176: Inline code vs. fenced code block
**Setup:** `write_doc_content(doc_id={DOC_ID}, content_format='markdown', content="See `x` inline.\n\n```\nfull code block\n```\n")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `` `x` `` inline within the "See ... inline." sentence (not as its own fenced block)
- `markdown` contains a fenced block (triple backtick) wrapping "full code block"

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** `markdown` returned `"See \`x\` inline.\n\n\`\`\`\nfull code block\n\`\`\`\n\n"` — both checks satisfied.

**Result (2026-09-04) ✅ PASS**
Inline code vs fenced block: markdown = "See \`x\` inline.\n\n\`\`\`\nfull code block\n\`\`\`\n\n" — exact match.

**Result (2026-10-07) ✅ PASS — regression check for PR #923 (`2b8da7a`).** Run against an isolated service-account sandbox on a Shared Drive, on a doc created with this case's setup content. `markdown` returned `"See \`x\` inline.\n\n\`\`\`\nfull code block\n\`\`\`\n\n"`, an exact match. Backtick-free inline code still gets a single-backtick fence.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: ``See `x` inline.\n\n```\nfull code block\n```\n\n``

---

### TC-DOC177: Table with a merged (colspan) header cell
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<table><tr><td colspan=\"2\">Merged</td></tr><tr><td>a</td><td>b</td></tr></table>")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains a pipe-table with a header row, a `| --- | --- |` separator, and a data row `| a | b |`
- The merged cell's text ("Merged") appears in the first column of the header row; the second header column is blank

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ❌ FAIL — run live against PR #591 (issue #300), round 1.** `markdown` returned `"\n\n| Merged |  |  |\n| --- | --- | --- |\n| a | b |  |\n\n"` — a **3-column** table instead of 2. A phantom placeholder column appears from the colspan merge. Confirms `/code-review high`'s finding on `doc_to_ast.py`'s `_table_elem_to_ast` (builds one `Cell` per raw `tableCells[]` JSON entry unconditionally, not accounting for the phantom placeholder entries Google's API leaves for positions covered by an earlier cell's `rowSpan`/`columnSpan` — a fact this codebase's own `emitter.py` already established). Additional live probe (rowspan, not in this test case but same root cause) is worse: `<table><tr><td rowspan="2">Tall</td><td>b1</td></tr><tr><td>b2</td></tr></table>` exported as `"| Tall | b1 |\n| --- | --- |\n|  |  |\n\n"` — **`b2`'s content is silently lost entirely**, not just misaligned. Blocking finding; commented on PR, handed back to Jay.

**Result (2026-08-15) ✅ PASS — re-verified live against PR #591 (issue #300) fix commit 4adeb03, round 2.** `markdown` returned `"\n\n| Merged |  |\n| --- | --- |\n| a | b |\n\n"` — correct 2-column table, no phantom column. Fixed via `doc_to_ast.py`'s new `covered` position-tracking in `_table_elem_to_ast`.

**Result (2026-09-04) ✅ PASS**
Colspan header table export: markdown = 2-column table "| Merged |  |\n| --- | --- |\n| a | b |" — correct, no phantom column (fix still holds).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `| Merged |  |\n| --- | --- |\n| a | b |`: 2 columns, no phantom column.

---

### TC-DOC178: Nested table renders a placeholder, not silently dropped
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<table><tr><td>outer text<table><tr><td>inner</td></tr></table></td></tr></table>")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains "outer text" in the corresponding cell
- That same cell contains a placeholder phrase (e.g. "nested table omitted") rather than silently losing the inner table's content with no trace
- The placeholder's opening `*` is separated from "outer text" by a space (or a `<br>`). Run together as `outer text*(nested table omitted…)*`, the `*` sits between a letter and `(`, so CommonMark doesn't treat it as opening emphasis and the note doesn't render in italics. Open as #1078; until it's fixed this check fails

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ❌ FAIL — run live against PR #591 (issue #300).** `markdown` returned `"\n\n| outer text*(nested table omitted — Markdown tables can't contain a table; use get_doc_structure for full fidelity)* |\n| --- |\n\n"` — both checks satisfied. Minor cosmetic nit (not filed): no space/newline between "outer text" and the placeholder note, so they run together.
**Corrected (2026-10-17, #1044 audit):** the "minor cosmetic nit (not filed)" is a real export defect: the placeholder runs into the cell text with no separator (`outer text*(nested table omitted…)*`), still reproducible on `develop`. Tracked in #1078.

**Result (2026-09-04) ✅ PASS**
Nested table export: markdown contains "outer text" and placeholder "*(nested table omitted — Markdown tables can't contain a table; use get_doc_structure for full fidelity)*" in the same cell.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`jay`: `| outer text*(nested table omitted — …)*<br> |`. The placeholder still runs into the cell text (open #1078). There is also a new trailing `<br>` after the placeholder; see New findings.

---

### TC-DOC179: `include_comments=True` includes only open comments
**Setup:** `write_doc_content(doc_id={DOC_ID}, content_format='markdown', content="Some anchor text here.\n")`, then `add_doc_comment(doc_id={DOC_ID}, content="please revise", quoted_text="anchor text")` to get `comment_id_1`, and a second `add_doc_comment(doc_id={DOC_ID}, content="resolved note")` to get `comment_id_2`, then `resolve_doc_comment(doc_id={DOC_ID}, comment_id=comment_id_2)`

**Prompt**
> "Export doc {DOC_ID} as Markdown including comments"

**Checks**
- `markdown` contains a `## Comments` section
- "please revise" and the quoted anchor "anchor text" appear
- "resolved note" does NOT appear (resolved comments are excluded)

**Cleanup:** write fixture content back over `{DOC_ID}` (this also clears the comments' anchor text, but the comments themselves persist on the file — delete via Drive UI if a clean fixture is required for a later run)

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** Both checks satisfied: "please revise" and quoted "anchor text" present, "resolved note" absent. An unrelated stale open comment ("QA TC-DOC97: anchored note") from earlier fixture pollution also appeared in the section — pre-existing, already tracked under #304, not caused by this PR.

**Result (2026-09-04) ✅ PASS**
include_comments=True: markdown contains "## Comments", "please revise" + quoted "anchor text" present, "resolved note" absent (resolved excluded). Note: an unrelated stale open comment from this same shard's earlier TC-DOC97 run also appeared — pre-existing fixture-doc comment pollution, not a defect.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `include_comments=True`: `## Comments` present, with "please revise" and the quoted "anchor text". "resolved note" is absent.

---

### TC-DOC180: `include_comments` omitted defaults to no Comments section
**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` does NOT contain `## Comments`, even if the doc has comments from a prior test

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** `markdown` returned `"Some anchor text here.\n\n"` — no `## Comments` section, despite open comments still on the doc from TC-DOC179.

**Result (2026-09-04) ✅ PASS**
include_comments omitted: markdown has no "## Comments" section despite open comments existing on the doc.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: No `## Comments` section without the flag, though open comments exist.

---

### TC-DOC181: Invalid doc_id returns an error, not a crash
**Prompt**
> "Export doc nonexistent-doc-id-xyz as Markdown"

**Checks**
- Returns `{"error": ...}` — no traceback surfaced to the caller

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** Returned `{"error": "<HttpError 404 ... Requested entity was not found...>"}`, no traceback.

**Result (2026-09-04) ✅ PASS**
get_doc_as_markdown('nonexistent-doc-id-xyz') returned clean {"error": "<HttpError 404 ...>"}, no traceback.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `nonexistent-doc-id-xyz` returned `{"error": "<HttpError 404 … Requested entity was not found.>"}`, no traceback. The first try hit the #1052 flake (see Infra).

---

### TC-DOC182: `local_path` bypasses the response and writes the raw Markdown to disk
**Prompt**
> "Export doc {DOC_ID} as Markdown, writing the result to <path-to>/qa-md-export.md"

Tool calls: `get_doc_as_markdown(doc_id={DOC_ID})`, then `get_doc_as_markdown(doc_id={DOC_ID}, local_path="<path-to>/qa-md-export.md")`.

**Checks**
- The second call returns `{local_path, bytes_written, doc_id, title}` (no inline `markdown` field in the response)
- The file at `<path-to>/qa-md-export.md` is plain Markdown, not a JSON object (#958): its bytes equal the first call's `markdown` field encoded as UTF-8 (e.g. `cmp` against that text saved to a scratch file), and `bytes_written` equals the file's size

**Cleanup:** delete the local `qa-md-export.md` file (and the scratch comparison file)

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300).** Response was `{"local_path": ..., "bytes_written": 170, "doc_id": ...}` with no inline `markdown` field; the written file's `markdown` field matched the doc's actual content exactly.

**Result (2026-09-04) ✅ PASS**
local_path set: response {local_path, doc_id, bytes_written}, no inline markdown field. File content's markdown field matched doc's actual content exactly. Local file cleaned up.

_Both results above predate #958, when the file held the JSON result envelope; re-run against the raw-Markdown checks._

**Result (2026-10-11) ✅ PASS — Kit, PR #982 round 1 (`457c37b`).** Ran on a scratch doc (created with `create_doc`, trashed afterwards) instead of `{DOC_ID}`. It held non-ASCII text (`Café naïve — 日本語`, an emoji), quotes, bold, a bullet list, and one open comment, and every call used `include_comments=True`. The `local_path=".../qa-md-export.md"` call returned `{local_path, bytes_written: 184, doc_id, title}` with no `markdown` field. The file's bytes equaled the inline `markdown` field encoded as UTF-8, including the `## Comments` section, and `json.loads` on the file failed as expected. A directory `local_path` (without `include_comments`) wrote `<doc_id>.md` (111 bytes, no comments section). Regression check: `get_sheet_data(local_path=...)` still wrote a JSON file that parses. Local files deleted. Side observation, outside this case: the comment's quoted anchor `Café` came back as `Caf&#233;`, both in the export and in `add_doc_comment`'s echo.

**Result (2026-10-11) ✅ PASS — Kit, PR #982 round 2 (`4f4fb99`).** Re-run after the write moved to `_write_atomically`, against the reconnected kit server, on a fresh scratch doc (trashed afterwards). `local_path` pointed at an existing `qa-md-export.md` holding `previous export`. The call returned `{local_path, bytes_written: 114, doc_id, title}`, and the file was replaced with bytes equal to the inline `markdown` (mode `0644`). A directory `local_path` wrote `<doc_id>.md` with the same bytes. A read-only (`0444`) existing target raised `Permission denied` and kept its old content. `get_sheet_data(local_path=)` still wrote parseable JSON. No `.gee-sweet-partial-*` temp file was left in the directory. Local files deleted.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `local_path` returned `{local_path, bytes_written: 24, doc_id, title}` with no `markdown` field. `cmp` of the file against the inline `markdown` text: identical. File size 24 = `bytes_written`.

---

### TC-DOC183: Rowspan merge preserves the covered row's own trailing cell
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<table><tr><td rowspan=\"2\">Tall</td><td>b1</td></tr><tr><td>b2</td></tr></table>")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains a 2-column pipe table: header row `| Tall | b1 |`, then `| --- | --- |`, then a data row whose second column is `b2` (first column blank — the position "Tall" spans into)
- `b2` is NOT dropped — this reproduces PR #591 QA round 1's root-cause finding (rowspan/multi-row tables previously had zero test coverage and silently lost the covered row's own real cell)

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300) fix commit 4adeb03, round 2.** `markdown` returned `"\n\n| Tall | b1 |\n| --- | --- |\n|  | b2 |\n\n"` — `b2` preserved in the second column, first column blank.

**Result (2026-09-04) ✅ PASS**
Rowspan export: markdown = "| Tall | b1 |\n| --- | --- |\n|  | b2 |\n\n" — b2 preserved in second column.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `| Tall | b1 |\n| --- | --- |\n|  | b2 |`: b2 kept.

---

### TC-DOC184: Link URL containing unbalanced parentheses doesn't break the destination
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<p><a href=\"https://en.wikipedia.org/wiki/Foo_(bar)\">link</a></p>")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `[link](<https://en.wikipedia.org/wiki/Foo_(bar)>)` — the destination is angle-bracket wrapped, not a bare `(...)` that breaks on the unmatched `)`

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300) fix commit 4adeb03, round 2.** `markdown` returned `"[link](<https://en.wikipedia.org/wiki/Foo_(bar)>)\n\n"` — exact match. Regression check: a plain URL with no parens/whitespace (TC-DOC173's `https://example.com`) re-verified unaffected — still renders as a bare, unwrapped destination.

**Result (2026-09-04) ✅ PASS**
Link with unbalanced parens: markdown = "[link](<https://en.wikipedia.org/wiki/Foo_(bar)>)\n\n" — angle-bracket wrapped, exact match.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `[link](<https://en.wikipedia.org/wiki/Foo_(bar)>)`

---

### TC-DOC185: Plain paragraph text resembling a block marker is escaped, not reinterpreted
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<p>1. Not actually a list item</p><p># Not a heading either</p>")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `1\. Not actually a list item` (backslash before the period — not a real ordered-list marker)
- `markdown` contains `\# Not a heading either` (backslash before the hash — not a real ATX heading)

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #591 (issue #300) fix commit 4adeb03, round 2.** `markdown` returned `"1\\. Not actually a list item\n\n\\# Not a heading either\n\n"` — both leading markers escaped as expected.

**Result (2026-09-04) ✅ PASS**
Plain text resembling markers: markdown = "1\\. Not actually a list item\n\n\\# Not a heading either\n\n" — both escaped correctly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `1\. Not actually a list item` and `\# Not a heading either`

---

### TC-DOC186: Image mixed into an all-Courier-New paragraph is not dropped (#594)
**Setup:** `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<p><img src=\"https://picsum.photos/id/1/200/100\" alt=\"test image\"><code>x = 1</code></p>")` — note `<code>` (not `<span style=...>`), and the image outside `<pre>`: html_parser.py's write side silently drops an `<img>` inside `<pre>` (a deliberate, documented gap — see `docs/images.py`'s module docstring), and `style_doc_range` has no `font_family` param at all, so `<code>` is the only reachable way to get an all-Courier-New paragraph with an image in it through this project's own tools.

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains an image reference `![...](...)` for the image — not silently dropped (alt text will round-trip empty regardless of the source `<img alt="...">` value — a pre-existing, unrelated gap tracked as #508, since `insertInlineImage`'s write path never stamps `title`/`description` on the embedded object; not this test's concern)
- `markdown` also contains a fenced block (triple backtick) wrapping `x = 1`
- Both appear in the output, image before the fenced block (source order)

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #599 (issue #594).** `markdown` returned `"![](https://lh7-rt.googleusercontent.com/...)\n\n```\nx = 1\n```\n\n"` — image present and ordered before the fenced code block as expected; alt text came back empty (`![]`, not `![test image]`) due to #508, unrelated to this PR's own fix.

**Result (2026-09-04) ✅ PASS**
Image + code in all-Courier-New paragraph: markdown contains an image reference followed by a fenced code block wrapping "x = 1", image before code block (source order) — not dropped.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `![](…)` then a fence holding `x = 1`, image first. Alt text comes back empty as the case expects, but the #508 it cites is closed as not-planned (see New findings).

---

### TC-DOC187: Blank spacer paragraph inside a table cell is preserved, not collapsed (#594)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<table><tr><td>Line 1<br><br>Line 2</td></tr></table>")` — two consecutive `<br>` insert a literal `"\n\n"` into the cell's body text, which the Docs backend splits into three real paragraphs in the cell (`"Line 1"`, an empty one, `"Line 2"`) — this is the only reachable way through this project's write tools to produce a genuinely empty-runs paragraph (as opposed to a `&nbsp;`-only one, which round-trips as non-empty per #402) inside a table cell.

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains the cell's content as `Line 1<br><br>Line 2` (double `<br>` — the blank spacer survives as a second line break)
- NOT `Line 1<br>Line 2` (single `<br>`) or `Line 1 Line 2` (no separator at all) — either would mean the spacer paragraph was silently dropped

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #599 (issue #594).** `markdown` returned `"\n\n| Line 1<br><br>Line 2 |\n| --- |\n\n"` — double `<br>` preserved, spacer not collapsed, for the mid-cell case this test covers.

⚠️ **Gap found in the same fix, not covered by this test case:** a spacer at a cell's *leading or trailing* edge (rather than sandwiched between two real lines) is still silently dropped. Reproduced live: `write_doc_content(content="<table><tr><td>Trailing test<br><br></td></tr><tr><td><br><br>Leading test</td></tr></table>")` → `get_doc_as_markdown` returned `"\n\n| Trailing test |\n| --- |\n| Leading test |\n\n"` — no `<br><br>` in either row, indistinguishable from a cell with no spacer at all. Root cause: `_cell_content_to_children` (doc_to_ast.py) correctly represents the edge spacer as a leading/trailing `"\n"` in the cell's own text (confirmed via local AST inspection: `'Line 1\n'` / `'\nLine 2'`), but `_render_cell` (ast_to_markdown.py, unmodified by this PR) does `text = "".join(parts).strip()` before the `\n`→`<br>` conversion — `.strip()` removes exactly the leading/trailing newline this PR's own fix just added, so only a mid-cell spacer survives to the rendered Markdown. Reported as a blocking finding on PR #599 rather than fixed here directly, since it needs a code change in the same fix this PR introduces.

Fix (round 2): `_render_cell` now converts `\n` → `<br>` *before* calling `.strip()`, not after — `<br>` isn't whitespace, so a genuine edge spacer survives the strip while incidental surrounding whitespace still gets trimmed as before. See TC-DOC188 below for the dedicated edge-spacer test case this gap was missing.

**Result (2026-09-04) ✅ PASS**
Mid-cell blank spacer (double <br>): markdown = "| Line 1<br><br>Line 2 |\n| --- |\n\n" — double <br> preserved, spacer not collapsed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `| Line 1<br><br>Line 2 |`

---

### TC-DOC188: Blank spacer paragraph at a cell's leading/trailing edge is preserved (#594 round 2)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<table><tr><td>Trailing test<br></td></tr><tr><td><br>Leading test</td></tr></table>")` — a single `<br>` at each edge, matching the single-spacer shape the unit tests (`test_trailing_spacer_paragraph_in_a_cell_leaves_a_trailing_newline` et al.) model; using `<br><br>` here (as the original PR-comment repro and QA round 1's gap report did) inserts two literal `"\n"` characters, which the Docs backend splits into *two* blank paragraphs at the edge, not one — live-confirmed to render as a doubled `<br><br>` rather than the single `<br>` these checks describe. Corrected during round-2 QA re-verification.

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown`'s first data row renders as `| Trailing test<br> |` (the trailing spacer survives as a trailing `<br>`, not dropped to a bare `| Trailing test |`)
- `markdown`'s second data row renders as `| <br>Leading test |` (the leading spacer survives as a leading `<br>`, not dropped to a bare `| Leading test |`)

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-08-15) ✅ PASS — run live against PR #599 (issue #594) round 2, fix commit 42ed950.** With the corrected single-`<br>`-per-edge setup, `markdown` returned `"\n\n| Trailing test<br> |\n| --- |\n| <br>Leading test |\n\n"` — matches both checks exactly. Also re-confirmed with the original (double-`<br>`) setup as a bonus check: returned `"\n\n| Trailing test<br><br> |\n| --- |\n| <br><br>Leading test |\n\n"` — 2 `<br>` in, 2 `<br>` out, consistent with the 1:1 preservation the mid-cell TC-DOC187 case already established; confirms the fix isn't collapsing multi-paragraph edge spacers either, just previously-reported-as-single-`<br>`-expected case was actually a two-paragraph input.

**Result (2026-09-04) ✅ PASS**
Edge spacers (single <br> each): markdown = "| Trailing test<br> |\n| --- |\n| <br>Leading test |\n\n" — both leading/trailing spacers survive exactly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `| Trailing test<br> |` and `| <br>Leading test |`

---

### TC-DOC204: Inline code containing backticks gets a longer fence and renders back to its original text (#936)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<p>see <code>call(`value`)</code></p><p>see <code>`leading</code></p><p>see <code>trailing`</code></p><p>see <code>``nested``</code></p><p>see <code>plain</code></p>")`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `` see ``call(`value`)`` ``, a two-backtick fence around content with a one-backtick run
- `markdown` contains ``` see `` `leading `` ``` and ``` see `` trailing` `` ```. The content has a backtick at the edge, so it's padded with one space on each side
- `markdown` contains ```` see ``` ``nested`` ``` ````, a three-backtick fence around a two-backtick run, padded
- `markdown` contains `` see `plain` `` (regression: backtick-free code is unchanged)
- Rendering each paragraph with a CommonMark renderer (e.g. Python `markdown`) gives a `<code>` element whose text is exactly the original: `` call(`value`) ``, `` `leading ``, `` trailing` ``, ``` ``nested`` ```, `plain`

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-07) ✅ PASS — run live against PR #923 (`2b8da7a`).** Run against an isolated service-account sandbox on a Shared Drive, on a doc written with the setup HTML (combined in one write with TC-DOC205's paragraphs). The relevant paragraphs of `markdown` were `"see ``call(`value`)``\n\nsee `` `leading ``\n\nsee `` trailing` ``\n\nsee ``` ``nested`` ```\n\n…see `plain`\n\n"`, matching each check. Each paragraph rendered with Python `markdown` gave a `<code>` element with exactly the original text.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: ``see ``call(`value`)`` ``, ``see `` `leading `` ``, ``see `` trailing` `` ``, ``see ``` ``nested`` ``` ``, ``see `plain` ``. Rendered with Python `markdown`, each `<code>` holds exactly the original text.

---

### TC-DOC205: A link on an inline code run containing backticks wraps the code span and keeps its destination (#936)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content=...)` with one paragraph per TC-DOC204 input, each code run wrapped in a link: `<p>see <a href="https://example.com/code"><code>call(`value`)</code></a></p>`, and likewise for `` `leading ``, `` trailing` ``, ``` ``nested`` ```

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- Each paragraph renders as `see [<span>](https://example.com/code)`, where `<span>` is the same fenced code span TC-DOC204 expects for that input
- Rendering each paragraph with a CommonMark renderer gives an `<a href="https://example.com/code">` containing a `<code>` element whose text is exactly the original

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-07) ✅ PASS — run live against PR #923 (`2b8da7a`).** Same doc and environment as TC-DOC204. `markdown` returned `"see [``call(`value`)``](https://example.com/code)\n\nsee [`` `leading ``](https://example.com/code)\n\nsee [`` trailing` ``](https://example.com/code)\n\nsee [``` ``nested`` ```](https://example.com/code)"`. Rendered with Python `markdown`, each paragraph had an `<a>` with `href="https://example.com/code"` wrapping a `<code>` with exactly the original text.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Each paragraph is `see [<span>](https://example.com/code)`. Rendered, each is an `<a href>` wrapping a `<code>` with the exact original text.

---

### TC-DOC206: Inline code keeps a space at both ends, and adjacent code runs export as one span (#938)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<p>pad <code> both ends </code> end</p><p>adj <code>x`</code><b><code>`y</code></b> end</p>")`. The bold change splits the second paragraph's code into two Courier New runs.

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains ``pad `  both ends  ` end``: one extra space a side, since CommonMark strips one space from each end when both ends have one
- `markdown` contains ```` adj ```x``y``` end ````: the two runs merge into one span, with a three-backtick delimiter around the two-backtick run
- Rendering `markdown` with a strict CommonMark renderer (e.g. `markdown-it-py`'s `commonmark` preset, not Python `markdown`, which strips code-span whitespace) gives `<code> both ends </code>` and `<code>x``y</code>`

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #968 round 1 (`d2449f7`).** `get_doc_as_markdown` returned ``pad `  both ends  ` end\n\nadj ```x``y``` end``. markdown-it-py 4.2.0's `commonmark` preset rendered `<code> both ends </code>` and `<code>x``y</code>`. Fixture content was written back.

**Result (2026-10-10) ✅ PASS — Kit, PR #968 round 2 (`759362a`).** Re-run because the fix changed `_render_run`. Output was identical to round 1. Fixture content was written back.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: ``pad `  both ends  ` end`` and ``adj ```x``y``` end``. markdown-it `commonmark` renders `<code> both ends </code>` and ``<code>x``y</code>``.

---

### TC-DOC207: Inline code in a table cell keeps a literal `|` and puts line breaks outside the code (#938)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content="<table><tr><td>Head</td></tr><tr><td>pipe <code>a|b</code> and a|b</td></tr><tr><td><code>x</code><br><code>y|z</code></td></tr></table>")`. The last cell has two code-styled paragraphs.

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains the row `| pipe <code>a&#124;b</code> and a\|b |`: the code's pipe is an HTML entity inside raw `<code>`, with no backslash, and the plain-text pipe is still escaped
- `markdown` contains the row `` | `x`<br><code>y&#124;z</code> | ``: the cell's paragraph break is a `<br>` between two code elements, not inside one
- Rendering `markdown` with a GFM-table renderer (e.g. `markdown-it-py`'s `commonmark` preset with `table` enabled) gives a one-column table whose cells contain `<code>a|b</code>` and `<code>x</code><br><code>y|z</code>`. No cell shows a backslash

Not covered live: a soft break (Shift+Enter) inside an inline code run in a paragraph that also has plain text. No tool can build one (`style_doc_range` doesn't set a font), so unit tests cover it (`TestInlineCodeCommonMark::test_newline_in_inline_code_does_not_start_a_new_block`).

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS (checks as written); ❌ probe beyond the case — Kit, PR #968 round 1 (`d2449f7`).** `get_doc_as_markdown` returned both expected rows exactly: `| pipe <code>a&#124;b</code> and a\|b |` and `` | `x`<br><code>y&#124;z</code> | ``. markdown-it-py's `commonmark` preset with `table` enabled rendered a one-column table with `<code>a|b</code>` and `<code>x</code><br><code>y|z</code>`, and no backslash. Probe: a cell with code `a|*b* _c_` exported as `<code>a&#124;*b* _c_</code>`, which renders `<em>` inside the `<code>`. A cell with code `C:\|x` exported as `<code>C:\&#124;x</code>`, which renders as `C:&amp;#124;x`. Both are sent back on the PR. Fixture content was written back.

**Result (2026-10-10) ✅ PASS — Kit, PR #968 round 2 (`759362a`).** Re-run because the fix changed the table-cell `<code>` path. Both expected rows came back exactly, and the render was the same as round 1. The round 1 probe is now TC-DOC208, which passes. Fixture content was written back.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Rows `| pipe <code>a&#124;b</code> and a\|b |` and ``| `x`<br><code>y&#124;z</code> |``. markdown-it with tables: `<code>a|b</code>` and `<code>x</code><br><code>y|z</code>`, no backslashes.

---

### TC-DOC208: Markdown punctuation inside table-cell `<code>`, linked code after a cell break, and HTML-like plain text all export literally (#938)
**Setup:** raw HTML via `write_doc_content(doc_id={DOC_ID}, content_format='html', content=...)` with this content. The `\` in `C:\|x` is one literal backslash character.

```html
<table><tr><td>Head</td></tr><tr><td><code>a|*b* _c_</code></td></tr><tr><td><code>C:\|x</code></td></tr><tr><td><code>x</code><br><a href="https://example.com/b"><code>b</code></a></td></tr></table><p>Use &lt;br&gt; or &amp;#124; and ~~old~~, AT&amp;T a &lt; b</p>
```

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains the row `| <code>a&#124;&#42;b&#42; &#95;c&#95;</code> |`: every punctuation character inside raw `<code>` is a numeric entity
- `markdown` contains the row `| <code>C&#58;&#92;&#124;x</code> |`: the backslash is an entity too, so it can't escape the pipe's `&`
- `markdown` contains the row `` | `x`<br>[`b`](https://example.com/b) | ``: the `<br>` from the cell's paragraph break is outside the link
- `markdown` contains the paragraph `Use \<br> or \&#124; and \~\~old\~\~, AT&T a < b`: `<` before a tag, `&` starting an entity, and `~` are escaped; `AT&T` and `a < b` are not
- Rendering `markdown` with `markdown-it-py`'s `commonmark` preset with `table` enabled gives cells `<code>a|*b* _c_</code>`, `<code>C:\|x</code>`, and `<code>x</code><br><a href="https://example.com/b"><code>b</code></a>`, with no `<em>` inside any `<code>`, and the paragraph renders as literal text (no line break, no `|`, no strikethrough)

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #968 round 2 (`759362a`).** `get_doc_as_markdown` returned all four expected lines exactly. markdown-it-py 4.2.0 (`commonmark` + `table` + `strikethrough`) rendered the cells `<code>a|*b* _c_</code>`, `<code>C:\|x</code>`, and `<code>x</code><br><a href="https://example.com/b"><code>b</code></a>`, and the paragraph `Use &lt;br&gt; or &amp;#124; and ~~old~~, AT&amp;T a &lt; b`, with no `<em>`, `<del>`, or line break. Fixture content was written back.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: All four expected lines are exact. markdown-it (commonmark + table + strikethrough) renders the expected cells, with no `<em>` or `<del>`. The paragraph renders as literal text.

### TC-DOC209: A linked code-only paragraph and linked images keep their links on export (#951)
**Background:** a fenced block's content is literal, so an all-code paragraph with a linked run used to export as a plain fence and drop the URL. Linked images lost their link everywhere, because the read side never read the image element's own `textStyle.link`. The write side can't create a linked image, so steps 2–3 link the images with `style_doc_range`.

**Setup:**
1. `write_doc_content(doc_id={DOC_ID}, content_format='html', content=...)` with:
   ```html
   <p><a href="https://pypi.org/project/pkg/"><code>pkg</code></a></p><p><code>x = 1</code><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"></p><p><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"></p>
   ```
2. `get_doc_structure(doc_id={DOC_ID})` and note each image's index: in the second paragraph, the position right after `x = 1` (`{IMG1}`); the third paragraph's `startIndex` (`{IMG2}`).
3. `style_doc_range(doc_id={DOC_ID}, ranges=[{"start_index": {IMG1}, "end_index": {IMG1}+1, "link_url": "https://example.com/in-code"}, {"start_index": {IMG2}, "end_index": {IMG2}+1, "link_url": "https://example.com/plain"}])`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` starts with `` [`pkg`](https://pypi.org/project/pkg/) ``, an inline code span inside a link, not a ```` ``` ```` fence
- The second paragraph still exports as a fence: ```` ``` ````, `x = 1`, ```` ``` ````, followed by a separate line `[![](<contentUri>)](https://example.com/in-code)`
- The third paragraph is `[![](<contentUri>)](https://example.com/plain)`
- Rendering `markdown` with `markdown-it-py`'s `commonmark` preset gives `<a href="https://pypi.org/project/pkg/"><code>pkg</code></a>`, one `<pre><code>x = 1` block, and two `<a>` elements each wrapping an `<img>`, with the hrefs above

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #976 round 1 (`3dbd257`).** Ran on a scratch doc (created with `create_doc`, trashed afterwards) instead of `{DOC_ID}`, to stay off the shared fixture. Images landed at indices 10 and 12. `get_doc_as_markdown` returned `` [`pkg`](https://pypi.org/project/pkg/) ``, a ```` ``` ```` fence holding `x = 1`, then `[![](<contentUri>)](https://example.com/in-code)` and `[![](<contentUri>)](https://example.com/plain)` as separate paragraphs. markdown-it-py `commonmark` rendered `<a href="https://pypi.org/project/pkg/"><code>pkg</code></a>`, one `<pre><code>x = 1`, and two `<a>` elements each wrapping an `<img>` with the expected hrefs. Off-script probe on the same doc: a fenced two-line block (`a`, `b`) with only its soft break linked (`style_doc_range` over that one index) exported as `` `a`<br>`b` ``, with no fence and no link (sent back in round 1).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Images at 10 and 12, linked with `style_doc_range`. Export: ``[`pkg`](https://pypi.org/project/pkg/)``, a fence holding `x = 1`, `[![](…)](…/in-code)`, `[![](…)](…/plain)`. markdown-it renders the expected `<a><code>`, one `<pre>`, and two `<a><img>`.

### TC-DOC210: A code block whose only link is on its soft break keeps its fence (PR #976 QA round 1)
**Background:** a link covering only a code block's line break (selecting a whole line in the UI can do this) renders as no link at all. It used to cost the paragraph its fence anyway, so the block exported as `` `a`<br>`b` `` with no link.

**Setup:**
1. `write_doc_content(doc_id={DOC_ID}, content_format='html', content='<pre>a\nb</pre>')`, with a real newline between `a` and `b`
2. `get_doc_structure(doc_id={DOC_ID})` and note the code paragraph's `startIndex` (`{P}`). The soft break sits at `{P}+1`.
3. `style_doc_range(doc_id={DOC_ID}, ranges=[{"start_index": {P}+1, "end_index": {P}+2, "link_url": "https://example.com/br"}])`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` starts with ```` ```\na\nb\n``` ````: one fence holding both lines, no `<br>`, no backtick span. Trailing newlines after the fence come from the doc's empty last paragraph and aren't part of the check.

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #976 round 2 (`fcf45d8`).** Ran on a scratch doc (created with `create_doc`, trashed afterwards). `{P}` was 1, so the link went on index 2. `get_doc_as_markdown` returned ```` ```\na\nb\n```\n\n ````: one fence, no `<br>`, no backtick span. The same setup exported `` `a`<br>`b` `` in round 1. The check said "exactly" and didn't allow the trailing `\n\n`, which every export has, so its wording was loosened.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `<pre>a\nb</pre>`, link on index 2. Export: ```` ```\na\nb\n``` ````: one fence.

### TC-DOC211: Links to a heading in the same doc export as working URLs, on text and on an image (PR #976 QA round 1)
**Background:** Docs reports a link made with the UI's "Headings" picker as `{"headingId": ...}`, with no `url`, on a text run and an image alike. These links used to export with no link. `style_doc_range`'s `link_url` always writes a plain `url`, so step 3 makes the links through the Docs UI.

**Setup:**
1. `write_doc_content(doc_id={DOC_ID}, content_format='html', content='<h1>Target</h1><p>jump <img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"></p>')`
2. `get_doc_structure(doc_id={DOC_ID})` and note the heading's `headingId` (`{HID}`)
3. With Playwright, open the doc, select the word `jump`, press Ctrl+K (Cmd+K on macOS), and pick the `Target` heading from the link dialog's "Headings" list. Then click the image and link it to `Target` the same way.

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `[jump](https://docs.google.com/document/d/{DOC_ID}/edit?tab=t.0#heading={HID})`. The tab may differ from `t.0` if the UI recorded one, but the `#heading={HID}` fragment must match.
- `markdown` contains `[![](<contentUri>)](https://docs.google.com/document/d/{DOC_ID}/edit?tab=t.0#heading={HID})`, with the same tab caveat
- Opening the exported `jump` URL in Playwright lands on the `Target` heading

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #976 round 2 (`fcf45d8`).** Ran on the same scratch doc as TC-DOC210 (trashed afterwards). The Playwright profile was signed into the fixture-owning account: the page title matched the doc name. `{HID}` was `h.ys7n1h73fcgv`. Step 3 in practice: double-click `jump` to select it. Cmd+K opens a dialog whose list already shows the heading (`Tт Target`), with no need to go through "Headings, bookmarks, and tabs". Click that dialog option, `li[role=option]`, not the left sidebar's `Target` outline entry: the outline entry only navigates, and clicking it first linked nothing. Then click the image and repeat. `get_doc_as_markdown` returned `[jump](https://docs.google.com/document/d/{DOC_ID}/edit?tab=t.0#heading=h.ys7n1h73fcgv) [![](<contentUri>)](…same URL…)`. Navigating to that URL opened the doc with the cursor at the start of `Target` (toolbar showed Heading 1).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Linked `jump` and the image to the `Target` heading through the Docs UI (Cmd+K, "Target" option). Export: `[jump](…/edit?tab=t.0#heading=h.myo62uuyrqg4)` and `[![](…)](same URL)`, where `h.myo62uuyrqg4` is the heading's `headingId`. Opening that URL in Playwright put the cursor on the Heading 1 "Target" (`tc-doc211.png`).

### TC-DOC212: Text ending in `!` right before a link exports as text plus a link, not as an image (#969)
**Background:** each run is rendered on its own, so `wow!` followed by a linked `x` exported as `wow![x](https://example.com/a)`, which CommonMark reads as an image: the link becomes an `<img>` and the `!` disappears. Linked code (`` wow![`y`](...) ``) and table cells did the same.

**Setup:**
1. `write_doc_content(doc_id={DOC_ID}, content_format='html', content=...)` with:
   ```html
   <p>wow!<a href="https://example.com/a">x</a></p><p>hey!<a href="https://example.com/b"><code>y</code></a></p><p>fine! plain</p><table><tr><td>cell!<a href="https://example.com/c">z</a></td></tr><tr><td>b</td></tr></table>
   ```

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `wow\![x](https://example.com/a)` and `` hey\![`y`](https://example.com/b) ``
- `markdown` contains `fine! plain`, with no backslash: a `!` that isn't right before a link is left alone
- The table's first cell is `cell\![z](https://example.com/c)`
- Rendering `markdown` with `markdown-it-py`'s `commonmark` preset (with `table` enabled) gives `wow!<a href="https://example.com/a">x</a>`, `hey!<a href="https://example.com/b"><code>y</code></a>`, and `cell!<a href="https://example.com/c">z</a>`, and no `<img>` anywhere

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #981 round 1 (`307e47c`).** Ran on a scratch doc (created with `create_doc` from the setup HTML, trashed afterwards) instead of `{DOC_ID}`. `get_doc_as_markdown` returned `wow\![x](https://example.com/a)`, `` hey\![`y`](https://example.com/b) ``, `fine! plain`, and the cell `cell\![z](https://example.com/c)`. markdown-it-py `commonmark` + `table` rendered `wow!<a href="https://example.com/a">x</a>`, `hey!<a href="https://example.com/b"><code>y</code></a>`, `fine! plain`, and `cell!<a href="https://example.com/c">z</a>`, with no `<img>`. Off-script probe on the same doc: `a <b> text` and `AT&amp;T` written as one run each, with `style_doc_range` setting `foreground_color` on `b> text` and `amp;T` to split each into two runs. Export was `a <b> text` (a raw HTML tag in CommonMark) and `AT&amp;T` (renders `AT&T`). As single runs, the same text exports escaped (`a \<b> text`, `AT\&amp;T`). Sent back in round 1.

**Result (2026-10-10) ✅ PASS — Kit, PR #981 round 2 (`b2bfafe`).** Re-run after the fix rewrote `_join_inline`'s `!` check into the shared `_BOUNDARY_SYNTAX` table, on a scratch doc (trashed afterwards). The export was byte-identical to round 1's: `wow\![x](https://example.com/a)`, `` hey\![`y`](https://example.com/b) ``, `fine! plain`, and `cell\![z](https://example.com/c)`.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `wow\![x](…/a)`, ``hey\![`y`](…/b)``, `fine! plain`, cell `cell\![z](…/c)`. markdown-it renders `wow!<a>`, `hey!<a><code>`, `cell!<a>`, no `<img>`.

### TC-DOC214: `<` and `&` split from the rest of a tag or entity by a color change still export literally (PR #981 QA round 1)
**Background:** `<` is escaped only when a tag or autolink could follow it, and `&` only when an entity could. Each run was escaped on its own, so a run boundary right after the `<` or `&` hid what followed. A color change splits a run without changing anything Markdown renders, so `a <b> text` exported as a raw `<b>` tag and `AT&amp;T` as the entity for `&`.

**Setup:**
1. `write_doc_content(doc_id={DOC_ID}, content_format='html', content='<p>a &lt;b&gt; text</p><p>AT&amp;amp;T</p><p>see &lt;https://x.io&gt;</p><p>a &lt; b and AT&amp;T</p>')`
2. `find_in_doc(doc_id={DOC_ID}, query="b> text")`, `find_in_doc(doc_id={DOC_ID}, query="amp;T")`, and `find_in_doc(doc_id={DOC_ID}, query="https://x.io>")`, noting each match's `start_index`/`end_index`
3. `style_doc_range(doc_id={DOC_ID}, ranges=[...])` with one range per match from step 2, each with `"foreground_color": {"red": 1, "green": 0, "blue": 0}`

**Prompt**
> "Export doc {DOC_ID} as Markdown"

**Checks**
- `markdown` contains `a \<b> text`, `AT\&amp;T`, and `see \<https://x.io>`
- `markdown` contains `a < b and AT&T` unchanged: a `<` or `&` that can't start syntax stays unescaped
- Rendering `markdown` with `markdown-it-py`'s `commonmark` preset gives `a &lt;b&gt; text`, `AT&amp;amp;T`, and `see &lt;https://x.io&gt;` as paragraph text, with no `<b>` tag and no `<a>`

**Cleanup:** write fixture content back over `{DOC_ID}`

**Result (2026-10-10) ✅ PASS — Kit, PR #981 round 2 (`b2bfafe`).** Ran on a scratch doc (created with `create_doc` from the step 1 HTML, trashed afterwards) instead of `{DOC_ID}`. Step 2 used one `find_in_doc(regex=True)` call for all three queries: matches at 4–11, 15–20 and 26–39. After step 3, `get_doc_structure` showed each of the first three paragraphs as two runs split at the `<`/`&` (`a <` | `b> text`, `AT&` | `amp;T`, `see <` | `https://x.io>`). `get_doc_as_markdown` returned `a \<b> text`, `AT\&amp;T`, `see \<https://x.io>`, and `a < b and AT&T` unchanged. markdown-it-py `commonmark` rendered `a &lt;b&gt; text`, `AT&amp;amp;T`, `see &lt;https://x.io&gt;`, and `a &lt; b and AT&amp;T`, with no `<b>` and no `<a>`. Round 1 got `a <b> text` and `AT&amp;T` unescaped from the same kind of split, on pre-fix code (`307e47c`).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Matches at 4–11, 15–20 and 26–39 were colored red. `get_doc_structure` confirmed each split into two runs at `<`/`&`. Export: `a \<b> text`, `AT\&amp;T`, `see \<https://x.io>`, `a < b and AT&T`. markdown-it renders them as literal text, no `<b>` and no `<a>`.


### TC-DOC216: A linked image written as Markdown or HTML keeps its link and round-trips (#977) ⚠️ requires-oauth
**Background:** the write side built a linked image with no link, so `[![alt](src)](url)` and `<a href><img></a>` imported as a plain image and didn't round-trip with TC-DOC209's export. The image now gets its link through an `updateTextStyle` over its one-character range, right after its insert. That request has to stay paired with the image when an unreachable image is dropped and retried, and a `#slug` image link goes through the heading-anchor pass.

**Setup:** none. Each step uses a scratch doc.

**Prompt**
**Playwright: required** (each linked image is clickable to its URL in the rendered doc; the unlinked one isn't)
1. `create_doc(title="TC-DOC216 md", folder_id={FOLDER_ID}, content_format='markdown', content=...)` with:
   ```markdown
   # Overview

   Before [![Logo](https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png)](https://example.com/one) and [linked text](https://example.com/t)![Plain](https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png)

   Jump: [![A](https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png)](#overview) and [![B](https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png)](#missing)

   | a | b |
   |---|---|
   | 1 | 2 |

   [![C](https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png)](https://example.com/after-table)
   ```
2. `get_doc_as_markdown(doc_id=<step 1 docId>)`
3. `create_doc(title="TC-DOC216 retry", folder_id={FOLDER_ID}, content_format='html', content=...)` with:
   ```html
   <p><a href="https://example.com/b1"><img src="https://example.invalid/nope.png?1"></a></p><p>x <a href="https://example.com/good"><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"></a> y</p><p><a href="https://example.com/b2"><img src="https://example.invalid/nope.png?2"></a></p>
   ```
4. `get_doc_as_markdown(doc_id=<step 3 docId>)`
5. `create_doc(title="TC-DOC216 adjacent", folder_id={FOLDER_ID}, content_format='html', content=...)` with (raw HTML, the first image wrapped in a top-level `<a>` with no `<p>`):
   ```html
   <a href="https://example.com/top"><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png" width="100"></a><p>x <a href="https://example.com/first"><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png" width="40"></a><a href="https://example.com/second"><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png" width="80"></a><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png" width="120"> y</p>
   ```
6. `get_doc_as_markdown(doc_id=<step 5 docId>)`
7. `create_doc(title="TC-DOC216 nested anchor", folder_id={FOLDER_ID}, content_format='html', content=...)` with an href-less `<a name>` nested inside each linked anchor (#994):
   ```html
   <a href="https://example.com/bare"><a name="n1"></a><img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"></a><p><a href="https://example.com/block"><a name="n2"></a>tail<img src="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"></a> after</p>
   ```
8. `get_doc_as_markdown(doc_id=<step 7 docId>)`

**Checks**
- Step 2: `[![](<contentUri>)](https://example.com/one)`
- Step 2: `[linked text](https://example.com/t)` is followed by an unlinked `![](<contentUri>)`, not one inside the link
- Step 2: image `A` links to `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=<headingId>`, the `Overview` heading. Image `B` is unlinked, its `#missing` link stripped
- Step 2: the image after the table is `[![](<contentUri>)](https://example.com/after-table)`
- Step 3: `images` reports an `error` for both `example.invalid` sources and none for the Google logo
- Step 4: the only image is `[![](<contentUri>)](https://example.com/good)`, between `x` and `y`. No text character carries `b1`'s or `b2`'s link
- Step 6: the first paragraph is the top-level image alone, as `[![](<contentUri>)](https://example.com/top)`
- Step 6: the second paragraph is `x `, `[![](<contentUri>)](https://example.com/first)`, `[![](<contentUri>)](https://example.com/second)`, an unlinked `![](<contentUri>)`, then ` y`, in that order. Playwright: in the step 5 doc's editor the three inline images get wider left to right (40, 80, 120px source widths), which confirms the order independently of the links
- Step 8: the first paragraph is `[![](<contentUri>)](https://example.com/bare)`. The second is `[tail](https://example.com/block)`, then `[![](<contentUri>)](https://example.com/block)`, then an unlinked ` after`: the nested `<a name>` doesn't end the outer link

**Cleanup:** `delete_file` all four scratch docs

**Result (2026-10-11) ✅ PASS — Sky, PR #992 round 1 (`6aa4dac`).** Step 2: `Logo` came back as `[![](<contentUri>)](https://example.com/one)`. `[linked text](https://example.com/t)` was followed by an unlinked `![](<contentUri>)`. `A` linked to `.../edit?tab=t.0#heading=h.…` (the `Overview` heading), and `B` was unlinked. The image after the table kept `https://example.com/after-table`. Step 3: `images` reported an `error` for both `example.invalid` sources and none for the logo. Step 4: the only image was `[![](<contentUri>)](https://example.com/good)` between `x` and `y`, and no text carried `b1`'s or `b2`'s link. Playwright, clicking each image in the step 1 doc's editor: `Logo` and the after-table image each showed a link chip for `https://example.com/…`, and `A`'s chip showed `Overview`. The unlinked image and `B` showed no link chip. The `/mobilebasic` HTML view isn't a substitute: it renders the text link but never wraps an image in `<a>`. A separate probe, `[![first](…)](https://example.com/first)[![second](…)](https://example.com/second)`, exported as `second` then `first`: adjacent images are written in reverse order. Each kept its own link.

**Result (2026-10-11) ✅ PASS — Sky, PR #992 round 2 (`3a506f4`).** Re-ran step 3 (the retry, now pairing each image with its link by identity) and the new step 5. Step 4: the only image was `[![](<contentUri>)](https://example.com/good)` between `x` and `y`, and no text carried `b1`'s or `b2`'s link. Step 6: the first paragraph was the top-level image alone, as `[![](<contentUri>)](https://example.com/top)`. The second paragraph was `x `, `…(https://example.com/first)`, `…(https://example.com/second)`, an unlinked image, then ` y`. Playwright: in the step 5 doc's editor the three inline images got wider left to right, and the top image's link chip showed `https://example.com/…`. Steps 1–2 weren't re-run: the fix commit doesn't change that path beyond the sort, which step 5 covers.

**Result (2026-10-11) ✅ PASS — Sky, PR #992 round 3 (`9271dfe`).** Ran the new step 7. Step 8: the first paragraph was `[![](<contentUri>)](https://example.com/bare)`, and the second was `[tail](https://example.com/block)`, then `[![](<contentUri>)](https://example.com/block)`, then an unlinked ` after`. The fix commit only touches `html_parser.py`'s anchor handling, so steps 1–6 weren't re-run.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Ran all four scratch docs. Step 2: `[![](…)](…/one)`; `[linked text](…/t)` then an unlinked image; A links to `#heading=h.qclk1iquowgu` (Overview); B is unlinked; the after-table image is linked. Step 3: errors for both `example.invalid` sources only. Step 4: the only image is `[![](…)](…/good)` between x and y. Step 6: the top image is alone, then first/second/unlinked in order. Step 8: `[![](…)](…/bare)`, then `[tail](…/block)[![](…)](…/block) after`. Playwright: Logo shows an `https://example.com/…` link chip, A shows "Overview", the Plain image has no chip, and the adjacent images widen left to right (screenshots `tc-doc216*.png`). Docs trashed.

### TC-DOC220: A literal fence line inside a code block doesn't close its export fence (PR #940) ⚠️ requires-oauth
**Background:** a code-block paragraph used to export inside a fixed three-backtick fence, so a content line of three or more backticks closed the block early and everything after it fell out as ordinary Markdown. The fence is now one longer than the longest backtick run in the content, with a minimum of three.

**Setup:** none. Each step uses a scratch doc.

**Prompt**
1. `create_doc(title="TC-DOC220 three", folder_id={FOLDER_ID}, content='<pre>before\n```\nafter</pre>')`, with real newlines inside the `<pre>`
2. `get_doc_as_markdown(doc_id=<step 1 docId>)`
3. Repeat steps 1–2 with a middle line of four backticks, then of six
4. Repeat steps 1–2 with `<pre>x = 1\ny = 2</pre>`, which has no backticks

**Checks**
- Step 2: `markdown` starts with ```````` ````\nbefore\n```\nafter\n```` ````````. A strict CommonMark renderer gives one `<pre><code>` holding exactly `before`, ```` ``` ````, `after`
- Step 3: the fence is five backticks around the four-backtick line and seven around the six-backtick line. Each renders as one `<pre><code>` holding all three lines, with nothing after the literal line falling out of the block
- Step 4: `markdown` starts with ```` ```\nx = 1\ny = 2\n``` ````, the plain three-backtick fence
- Trailing newlines after the fence come from the doc's empty last paragraph and aren't part of any check

**Cleanup:** `delete_file` all four scratch docs

**Result (2026-10-13) ✅ PASS — post-merge live check, develop `6bf7961`.** Ran in an isolated service-account sandbox on a Shared Drive. The exports were ```````` ````\nbefore\n```\nafter\n````\n\n ````````, then the five- and seven-backtick equivalents, then ```` ```\nx = 1\ny = 2\n```\n\n ````. markdown-it-py 4.2.0's `commonmark` preset rendered each fenced block as one `<pre><code>` holding exactly the original lines. Control: the same renderer, given the pre-fix three-backtick fence around the step 1 content, ends the block after `before` and renders `after` as a paragraph. Scratch docs trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: The exports use four-, five-, seven- and three-backtick fences as expected. markdown-it renders each as one `<pre><code>` holding all lines. Docs trashed.

### TC-DOC221: Code segments split by an inline image each get a fence sized to their own content (PR #940) ⚠️ requires-oauth
**Background:** a code-block paragraph with an inline image exports as one fenced block per code segment, with the image between them. Since PR #940, each segment's fence is sized to its own backtick runs, so a literal fence line in one segment doesn't lengthen the other's.

**Setup:**
1. `create_doc(title="TC-DOC221", folder_id={FOLDER_ID}, content='<pre>before\n```\nmid\nafter</pre>')`, with real newlines inside the `<pre>`
2. `get_doc_structure(doc_id=<docId>)` and note the code paragraph's `startIndex` (`{P}`). `mid` starts at `{P}+11`.
3. `insert_inline_image(doc_id=<docId>, index={P}+11, uri="https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png")`

**Prompt**
> "Export doc <docId> as Markdown"

**Checks**
- `markdown` is a four-backtick fence holding `before` and ```` ``` ````, then `![](<contentUri>)`, then a three-backtick fence holding `mid` and `after`, in that order
- A strict CommonMark renderer gives `<pre><code>`, `<img>`, `<pre><code>`, with the literal ```` ``` ```` inside the first block and nothing outside a block except the image
- The first block also ends with an empty line: the soft break before the image belongs to the first segment. That's how segments have always split (#594), not part of this case

**Cleanup:** `delete_file` the scratch doc

**Result (2026-10-13) ✅ PASS — post-merge live check, develop `6bf7961`.** Ran in an isolated service-account sandbox on a Shared Drive. `{P}` was 1, so the image went in at index 12. The export was ````````` ````\nbefore\n```\n\n````\n\n![](<contentUri>)\n\n```\nmid\nafter\n```\n\n `````````. markdown-it-py 4.2.0's `commonmark` preset rendered `<pre><code>before\n```\n\n</code></pre>`, the `<img>`, then `<pre><code>mid\nafter\n</code></pre>`. Scratch doc trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).


**Result (2026-10-18) ✅ PASS — Sky, PR #1088 round 1 (`76b82a9`), regression.** Scratch doc; `{P}` was 1, link on index 2. Export was ```` ```\na\nb\n```\n\n ````: one fence, no `<br>`, no backtick span. Trashed afterwards.

**Result (2026-10-18) ✅ PASS — Sky, PR #1088 round 2 (`e972af0`), regression.** `_is_code_block` now asks `_split_edge_breaks` whether a linked run renders a link. Scratch doc; `{P}` was 1, link on index 2. Export was ```` ```\na\nb\n```\n\n ````: one fence. Locally, a linked Courier run of `" \n"` (whitespace plus the break) also keeps the fence. Trashed afterwards.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: P=1, image at 12. Export: a four-backtick fence holding `before`, ```` ``` ```` and a blank line, then `![](…)`, then a three-backtick fence holding `mid`/`after`. markdown-it renders `<pre>`, `<img>`, `<pre>`. Doc trashed.
---

## Orphan fileId on inline-image sharing failure (#649)

Mirrors #420's fix in `drive/transfer.py` (see TC-D249/TC-D250 in `docs/qa/tests/drive_transfer.md`) applied to the same create()-succeeds-but-follow-up-fails shape in `docs/images.py`'s `upload_and_share_image` and `docs/content.py`'s `_resolve_image_source`: a transient failure in the `permissions().create()`/`files().get()` sharing step, after `files().create()` (or an already-uploaded `_upload_local_file`) had already succeeded, previously returned a bare `{"error": ...}` with no way to find the Drive file that now genuinely exists. Not reliably reproducible live (would require forcing a transient API failure in the exact window between create and share); verified by unit test instead, matching TC-D249/TC-D250's own convention.

### TC-DOC189: `upload_and_share_image` / `_resolve_image_source` — a sharing-step failure after a successful upload reports the orphan's file_id, not a bare error (unit test)

**Background:** three call sites had this shape: `images.py`'s `upload_and_share_image` (used directly by `insert_local_images`'s auto_downscale branch and by `downscale_drive_file`), `images.py`'s `insert_local_images`'s own plain (non-downscaled) upload+share step, and `content.py`'s `_resolve_image_source`'s shared sharing step (used by `create_doc`/`create_doc_from_file`/`write_doc_content`/`update_doc_from_file`'s markdown/HTML image embedding for both `drive:<file_id>` and local-path sources).

**Checks (unit test)**
- `tests/test_docs_images.py::TestUploadAndShareImage::test_share_failure_after_create_returns_file_id` — `create()` succeeds, `permissions().create()` raises → result carries `file_id` alongside `error`
- ~~`tests/test_docs_images.py::TestUploadAndShareImage::test_metadata_fetch_failure_after_create_returns_file_id`~~ — removed by #511: the post-share `files().get()` it exercised no longer exists (the link now comes back from `create()`); `test_does_not_refetch_web_content_link` guards that instead
- `tests/test_docs_images.py::TestUploadAndShareImage::test_create_failure_returns_bare_error_no_file_id` — regression guard: when `create()` itself fails, no `file_id` key at all (nothing was created, so there's no orphan)
- `tests/test_docs_images.py::TestInsertLocalImages::test_sharing_failure_reports_per_image_error_and_skips_doc_edit` (updated) and `test_downscaled_upload_share_failure_still_reports_file_id` (new) — both of `insert_local_images`'s upload paths (plain and auto_downscale) surface `fileId` in the per-image outcome entry on a sharing failure
- `tests/test_docs_images.py::TestInsertLocalImages::test_missing_web_content_link_reports_orphan_file_id_without_sharing` (new, PR #652 QA round 1 finding 1) — `insert_local_images`'s plain path's *second* post-upload failure branch (`if not uri:` — the upload succeeded but Drive returned no webContentLink; since #511 this fails *before* sharing) also surfaces `fileId` in the per-image outcome and still marks the folder cache dirty
- `tests/test_docs_images.py::TestInsertLocalImages::test_sharing_failure_orphan_still_marks_folder_cache_dirty` / `test_downscaled_upload_share_failure_still_reports_file_id` (cache assertion) — the folder-listing cache is still marked dirty for the orphan case, mirroring the cache-invalidation-gate fix PR #645's QA round found necessary for the identical shape in `transfer.py`
- `tests/test_docs_content.py::TestResolveImageSource::test_local_upload_sharing_failure_returns_orphan_file_id` (new) — a local-path source's sharing failure (the true orphan case — the file was freshly created by this call) carries `file_id`
- `tests/test_docs_content.py::TestResolveImageSource::test_local_upload_missing_web_content_link_returns_orphan_file_id` (new) — same local-path source, the missing-`webContentLink` branch, also carries `file_id`
- `tests/test_docs_content.py::TestResolveImageSource::test_sharing_failure_is_error` (updated, PR #652 QA round 1 finding 2) and `test_missing_web_content_link_is_error` (updated) — a `drive:<file_id>` source is the caller's *pre-existing* file, not an orphan this call created, so both its post-upload failure branches now **omit** `file_id` — surfacing it in a failed-image outcome would let a caller with orphan-reclaim logic delete a file it never made
- `tests/test_docs_content.py::TestCreateDocImages::test_sharing_failure_image_outcome_still_carries_file_id` (updated — now a local-upload source) — `create_doc`'s own image-outcome assembly loop (which previously only copied `result["error"]`, discarding every other key) surfaces `fileId` in the per-image outcome entry for a genuine orphan
- `tests/test_docs_content.py::TestCreateDocImages::test_drive_source_sharing_failure_omits_file_id` (new) — the `drive:` counterpart: `create_doc`'s image outcome for a `drive:` source's sharing failure has no `fileId`

**Result: N/A — unit-test-verified only, per TC-D249/TC-D250 convention** (the transient-failure window between create and share cannot be forced against the live API). All listed unit tests run green locally (`uv run python -m pytest tests/test_docs_images.py tests/test_docs_content.py` → 264 passed, 2026-08-28).

**Result (2026-08-28) ❌ FAIL — first QA pass on PR #652, Sky.** `/code-review high origin/develop...HEAD` surfaced a blocking gap the unit suite does not cover: `insert_local_images._upload_and_share`'s plain (non-downscale) upload path has a *second* post-upload failure branch — `if not uri:` (metadata fetched but Drive returned no `webContentLink`, `images.py:722`) — that was **not** given the #649 fix its two sibling branches received in this same diff (`upload_and_share_image` `images.py:301-305`, `_resolve_image_source` `content.py:277-281`, both carry `file_id`). It sets `entry["error"]` + `placement["failed"] = True` and returns without `entry["fileId"]` / `placement["file_id"]`, so the orphan is unreported *and* the `any("file_id" in p ...)` folder-cache-dirty gate at `images.py:746` never fires for it — the exact class #649 exists to close, left unfixed in 1 of the 3 enumerated call sites. Needs the `file_id` propagation plus a unit test mirroring `test_missing_web_content_link_is_error`. Sent back to Ash; see PR comment for the full finding list (incl. the `drive:` vs local-upload orphan-shape ambiguity, and non-blocking tickets/comments filed for the systemic dedup + cleanup gaps).

**Result (2026-08-28) ✅ PASS — re-verification round on PR #652, Sky, fix commit `c4e5f01`.** Both blocking findings closed:
- **Finding 1:** `insert_local_images._upload_and_share`'s plain-path `if not uri:` branch (`images.py:721`) now sets `entry["fileId"]` + `placement["file_id"]` before returning, matching its two sibling branches; new `test_missing_web_content_link_after_share_still_reports_orphan_file_id` asserts both the surfaced `fileId` and the `mark_dirty` call.
- **Finding 2:** `_resolve_image_source` gained a `created_here` flag (set `True` only after `_upload_local_file` succeeds); both post-share failure returns now carry `file_id` **only** for the local-upload branch, so a `drive:<file_id>` source's sharing failure returns a bare error. Covered by updated `test_sharing_failure_is_error` / `test_missing_web_content_link_is_error` (now assert `"file_id" not in result`), new `test_local_upload_missing_web_content_link_returns_orphan_file_id`, and new `test_drive_source_sharing_failure_omits_file_id`.

Verification: fix diff is tightly scoped to the two named findings (no `/code-review` re-run needed), full docs unit suite green (`uv run python -m pytest tests/test_docs_images.py tests/test_docs_content.py` → **267 passed**), and a live happy-path smoke (`mcp-gee-sweet-sky` `create_doc` with a local-image markdown embed into the QA fixtures folder) returned `images:[{src, fileId, shared:false}]` with no error — the `_resolve_image_source` refactor doesn't regress the common embed path. Smoke doc + uploaded image deleted afterward.

**Result (2026-09-04) ➖ N/A**

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: All listed tests exist (confirmed with `--co`). TestUploadAndShareImage, TestInsertLocalImages, TestResolveImageSource and TestCreateDocImages are in the 119-test run, all passed.


---

### TC-DOC190: Isolated depth>0 bullet run renders the correct nested glyph, not the disc (#439) ⚠️ destructive

**Background:** `createParagraphBullets` assigns each covered paragraph `nestingLevel = (its leading-tab count) − (the minimum leading-tab count across the whole call's range)`. A contiguous same-preset `BulletItem` run whose every item sits at `depth > 0` with no `depth=0` sibling in that same call (e.g. TC-DOC104's Case 2 — a bare `<li>` with no text of its own, only a nested `<ul>` — where the empty parent `<li>` is dropped, leaving just the two `depth=1` children) therefore collapsed entirely to `nestingLevel 0`: the per-level indent was bumped so the items still *looked* nested, but the rendered bullet glyph was the depth-0 disc (●) instead of the depth-1 circle (○). PR #432's round-2 QA (TC-DOC104/106 results, 2026-07-27) flagged this and split it out as #439, non-blocking. Fixed in `emitter.py`'s deferred bullet pass: an isolated run is wrapped with a throwaway 0-tab anchor paragraph (insert `\n` at `run_start` → `createParagraphBullets` over the range extended by 1 → `deleteContentRange` the anchor), so the real items land at their true `nestingLevel` and its glyph. The anchor insert (+1) and delete (−1) cancel, leaving every position outside the run — later bullet runs, table/image inserts — exactly where an ordinary single call would.

Because the anchor always contributes 0 tabs, this fix renders every isolated item at `nestingLevel == its own depth` exactly, with no clamp — a `min_depth == 2` run (Case 4 below: two levels of bare parent `<li>`s dropped, leaving only `depth=2` children) renders two indent tiers deep with no visible parent above it, not clamped to depth 1. This PR #711 QA round's own ad-hoc probe found that result but flagged it non-blocking/unverified-as-intended (see this test's original result below). Issue #714 settled the question: render at true depth is the intended, decided behavior — see the issue's decision comment. Case 4 below promotes that probe into a real, repeatable check.

**Prompt**
**Playwright: required**
> "Write this HTML to doc {DOC_ID}: contents of docs/qa/fixtures/tc-doc104-nested-lists.html"

**Checks**
- Case 2's "Bare-nested child C1"/"C2" render with the **circle** (○) glyph — the same glyph as Case 1's "Child A1"/"Child A2" (also `depth=1`) elsewhere in the same doc — not the disc (●) glyph used at depth 0
- Case 2's children stay visibly indented one level deeper than the (absent) parent (the TC-DOC104 checklist requirement — must not regress)
- Case 1 / Case 3 nesting is unchanged from TC-DOC104's passing result: 3 distinct indentation levels in Case 1 (disc / circle / square), continuous numbering for "Ordered child B1"/"B2" and Case 3's "Top ordered 1"/"2"
- Precise structural confirmation (complements the Playwright glyph check, since `get_doc_structure` still doesn't expose `nestingLevel` — see the tooling-gap note under TC-DOC106): a script-driven `documents().get()` shows "Bare-nested child C1"/"C2" with `bullet.nestingLevel == 1`, and that list's `listProperties.nestingLevels[1].glyphSymbol` is the circle — not `nestingLevel 0`
- The isolated ordered sub-run is fixed the same way: Case 1's "Ordered child B1"/"B2" report `bullet.nestingLevel == 1` (glyph "a."/"b.", `NUMBERED_DECIMAL_ALPHA_ROMAN` level 1), not `nestingLevel 0` ("1."/"2." decimal)
- Case 4 (`min_depth == 2`, #714): "Doubly-bare child D2a"/"D2b" report `bullet.nestingLevel == 2` — **not** `nestingLevel 0` or `1` — and that list's `listProperties.nestingLevels[2].glyphSymbol` is the square (■), the depth-2 glyph, matching Case 1's own Grandchild-A2a square at the same level. 🔍 Visual check: both items visibly render two indent tiers deep with no parent bullet above them.

**Cleanup:** write fixture content back

**Result (2026-09-08) ❌ FAIL — run live against PR #711 (commit `a3d9baf`), script-driven `documents().get()` + Playwright visual check.** Wrote the fixture HTML to the fixtures doc via `write_doc_content` (batchUpdate accepted, no atomic-batch rejection). Live `documents().get()`:
- Case 2 "Bare-nested child C1"/"C2" → `bullet.nestingLevel == 1`, `lists[listId].listProperties.nestingLevels[1].glyphSymbol == '○'` (circle) — the identical glyph symbol reported for Case 1's "Child A1"/"Child A2". **Not** `nestingLevel 0` / disc. Both items of the run correct (no first-item-merges-into-anchor regression).
- Case 1 isolated ordered sub-run "Ordered child B1"/"B2" → `nestingLevel == 1`, `glyphType 'ALPHA'` / `glyphFormat '%1.'` ("a."/"b."). Not `nestingLevel 0` decimal.
- Case 1 anchored nesting unchanged: Parent A/B `●` L0, Child A1/A2 `○` L1, Grandchild A2a `■` L2 — 3 distinct levels.
- Case 3 unchanged: "Top ordered 1"/"Top ordered 2" both `nestingLevel 0` DECIMAL on one shared `listId` (continuous numbering), "Nested ordered 1.1"/"1.2" `nestingLevel 1` ALPHA.
**Corrected (2026-10-17, #1044 audit):** the standalone `nestingLevel 0` disc paragraphs of spaces this run called "pre-existing noise, out of scope" are in this case's own rendered fixture. Tracked in #1074.

Playwright (fixtures doc temp-shared reader to the browser's Google identity for the screenshot, revoked immediately after — public `anyone` share is classifier-blocked; the browser profile authenticates as a different Google account than the QA MCP server, so it can't open server-owned fixture docs otherwise): "Bare-nested child C1"/"C2" visually render the hollow-circle glyph, indented one level, matching Case 1's A1/A2. B1/B2 render "a."/"b.". Three visible indent tiers in Case 1 (●/○/■). Case 3 numbers 1→(2)→3 with nested a./b.

Pre-existing noise (not caused by this PR, already documented under TC-DOC104 round-1 result 2026-07-16 line ~1799 and TC-DOC106): the raw-HTML fixture's interstitial whitespace between `</li>` and `<ul>` produces standalone `nestingLevel 0` disc paragraphs containing only spaces ("    "). Reproduces identically on develop; TC-DOC106's markdown fixture has none. Out of scope for #439.

Extra probes run live (fresh scratch docs, trashed after) to check the code-review's correctness hypotheses — all refuted:
- Single-item isolated run `<ul><li><ul><li>only</li></ul></li></ul>` → `nestingLevel 1`, circle (not a no-op).
- Isolated run as the *only* doc content → batchUpdate accepted; items `nestingLevel 1` circle; the terminal empty paragraph carries no bullet (no stray bullet on the segment-end newline).
- Blockquote wrapping an isolated run → **both** items keep `borderLeft` + `indentStart` (blockquote style not stripped from the first item).
- Isolated run immediately followed by a `<table>` → table lands at the same index it would with an ordinary depth-0-anchored run (anchor insert/delete are position-neutral).
- `min_depth == 2` isolated run (`<ul><li><ul><li><ul><li>D2a</li>…`) → renders at absolute `nestingLevel 2` (square glyph, 108pt indent), i.e. two indent tiers with no visible parents. Issue #714 settled this as the intended, decided behavior (render at true depth, no clamp) rather than an open question — see Case 4 above and its own dated Result entry, which promotes this probe into a real, repeatable check against the checked-in fixture.

**Result (2026-09-11) ✅ PASS — Case 4 (#714) run live against PR #731 (commit `a0c9b9d`), script-driven `documents().get()` + Playwright visual check.** Wrote the 4-case fixture HTML (including the new Case 4) to the fixtures doc via `write_doc_content`. `get_doc_structure` confirmed "Doubly-bare child D2a"/"D2b" both at `bullet.nestingLevel == 2` on their own `listId`. A follow-up script-driven `documents().get()` confirmed that list's `listProperties.nestingLevels[2].glyphSymbol == '■'` — the identical glyph symbol reported for Case 1's own Grandchild-A2a at the same level. Playwright (fixtures doc temp-shared reader for the screenshot, revoked immediately after): both items visibly render two indent tiers deep with no parent bullet above them, glyph is a filled square — screenshot at `docs/qa/screenshots/2026-09-11-tc-doc190-case4.png`. Cases 1–3 unaffected (spot-checked in the same `get_doc_structure` call: Case 1 still 3 distinct levels, Case 3 still continuous numbering). Fixture content written back to baseline afterward.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ❌ FAIL — v0.9.3 release pass**
`jay`: Case 2 C1/C2 are nestingLevel 1 with a circle glyph. B1/B2 are level 1 "a./b.". Case 4 D2a/D2b are level 2 with a square glyph, two tiers deep. Case 1 has ●/○/■. But the fixture's whitespace between list tags renders as stray nestingLevel-0 bullet paragraphs (`"    "`), visible as empty bullets. In Case 3 that makes the numbering 1, (empty) 2., 3. "Top ordered 2". Open #1074. Raw glyph read not run (scratch script). Screenshot `tc-doc190.png`.

**Result (2026-10-29, PR #1295 @ 47607c8f) ❌ FAIL — Case 1 regressed; Cases 2–4 pass.** `create_doc_from_file` on the fixture, graded from `documents().get()`. Case 1: "Ordered child B1" is `nestingLevel` **2** (i.) and B2 is level 1 (a.), in one list; expected both at level 1, a. and b. A nested list of the other type that ends its top-level list renders its first item one level too deep. The same requests built from `develop`'s source, applied live, fail the same way, so this comes from #1072 (PR #1286), not PR #1295; sent back on PR #1295, whose diff changes `_top_list_requests`. Case 2: C1/C2 at level 1 (○). Case 3: 1., a., b., 2. Case 4: D2a/D2b at level 2 (■). No stray empty bullets this run (#1074's symptom didn't show). Grid: [`results/2026-10-29-markdown-pr1295.md`](../results/2026-10-29-markdown-pr1295.md)

**Result (2026-10-30, PR #1295 @ 3af9a092, round 2) ✅ PASS — all four cases, Run 2 identical, checked on screen (`pr1295-r2/tc-doc190.png`).** Case 1: Parent A ●, A1/A2 ○, A2a ■; Parent B ●, Ordered child B1 **a.**, B2 **b.**, both at level 1. Case 2: C1/C2 ○ at level 1. Case 3: 1., a., b., 2. Case 4: D2a/D2b ■ at level 2. Grid: [`results/2026-10-29-markdown-pr1295.md`](../results/2026-10-29-markdown-pr1295.md) §"Round 2"

---

### TC-DOC191: A multi-line fenced code block stays one Docs paragraph, and round-trips as one fence (#719) ⚠️ requires-oauth

**Background:** A markdown fenced code block with more than one line (`` ``` `` + N lines + `` ``` ``) converts to one `Paragraph` AST node whose `Run` text legitimately contains embedded `"\n"` characters — but the Docs API treats every `"\n"` in inserted text as a new paragraph boundary, so the block used to silently fragment into one `NORMAL_TEXT` paragraph per line. Creation itself still applied `Courier New` correctly to every fragment (confirmed live pre-fix via a raw `documents().get()`), but `get_doc_as_markdown`'s round-trip then re-rendered each fragment as its own separate one-line fence instead of one — reproducing identically for a plain (non-HTML) multi-line code block, not just the HTML-tag content the issue was originally filed against. Fixed by writing the block's internal line breaks as `"\v"` (the same soft-break convention `insert_softbreak_paragraph` already uses) instead of `"\n"`, with a matching reversal on the read side for any `Courier New`-styled run.

**Setup:** `create_doc(title="TC-DOC191", content_format="markdown", content="Some text before.\n\n\`\`\`\n<ul>\n  <li>\n    <ul>\n      <li>Item D2a</li>\n    </ul>\n  </li>\n</ul>\n\`\`\`\n\nSome text after.")`

**Checks**
- `get_doc_structure({DOC_ID})` shows exactly **3** body paragraphs (plus the trailing empty one) — "Some text before.", one paragraph holding the entire multi-line `<ul>…</ul>` block, "Some text after." — not one paragraph per code line (8 separate `NORMAL_TEXT` paragraphs would mean the fragmentation bug is back)
- `get_doc_as_markdown({DOC_ID})` returns the code content as **one** fenced block (`` ``` `` … `` ``` ``) containing all the original lines with their indentation intact — not multiple separate one-line fences
- Repeat with a plain (non-HTML) multi-line code block — `content="\`\`\`\ndef foo():\n    return 1\n\`\`\`"` — same shape: 1 Docs paragraph, 1 fence back, confirming the fix isn't scoped to HTML-tag content specifically
- A single-line fenced block (`` ``` ``\nx = 1\n`` ``` ``) is unaffected — still 1 paragraph, 1 fence back (no embedded `"\n"` to substitute)

**Cleanup:** `delete_file({DOC_ID}, permanent=true)` — a scratch doc created solely for this test, not a shared fixture.

**Result (2026-09-11) ❌ FAIL — first QA pass on PR #730, Kit.** The checks above (paragraph count, `get_doc_as_markdown` fencing) passed as written, but `/code-review high origin/develop...HEAD` surfaced a gap this test case's own checks don't exercise: neither check inspects the body paragraph's raw *text* for a leaked `"\v"` (U+000B). Live-confirmed on a scratch doc: `get_doc_structure` returned `"line oneline twoline three\n"` and `find_in_doc` returned the same literal `\v` in `matched_text`/`context` — the write-side `"\n"`→`"\v"` substitution's read-side reversal (`doc_to_ast.py`) only covers the `get_doc_as_markdown` path; `get_doc_structure` and `find_in_doc` build their text straight off the raw Docs API response with no equivalent reversal. Sent back to Jay; see PR comment for the full finding (a second, narrower finding on the same reversal mechanism was confirmed unreachable through any current tool and filed separately as #732, non-blocking).

**Result (2026-09-11) ✅ PASS — re-verification round on PR #730, Kit, fix commit `d8fabdf`.** Fix extracts the substitution into a shared `decode_code_run_text()` helper (`indices.py`) and applies it at all three read sites (`get_doc_structure`'s body-paragraph runs and table cells, `find_in_doc`'s `_collect_doc_paragraphs`), plus `doc_to_ast.py`'s own reversal now delegates to the same helper. Live-reverified against a fresh scratch doc: `get_doc_structure` now returns `"line one\nline two\nline three\n"` (real newlines, no `\v`); `find_in_doc` with a literal multi-line query now matches the same real-newline text. Full `tests/test_docs_content.py` + `tests/test_docs_markdown_export.py` suites green (269 passed) locally. Diff was small and targeted directly at the two named findings with no unrelated commits in between, so this followed the re-verification fast path (`git show` + live-verify) rather than a second full `/code-review`.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).


**Result (2026-10-18) ✅ PASS — Sky, PR #1088 round 1 (`76b82a9`), regression.** PR #1088 makes `_text_run_to_run` decode every `"\v"`, not just Courier New runs. One scratch doc held all three blocks (the `<ul>` block, the `def foo()` block, the single-line block): `get_doc_structure` showed one paragraph per block with real `\n` and no `\v`, and `get_doc_as_markdown` returned exactly three fences with indentation intact. Trashed afterwards.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Ran on the doc copy with `write_doc_content` (same pipeline as `create_doc`), all three blocks in one doc. Each block is one paragraph with real \n, no \v. Export: exactly three fences, indentation intact.
---

### TC-DOC192: `handle_data`'s implicit top-level paragraph resets all block-open state on open (#417) (unit test)

**Background:** `#343`'s implicit-paragraph-for-bare-top-level-text path (`html_parser.py`'s `handle_data`, `self._block_tag = "p"`) was the one block-open site in the file that didn't reset `self._block_had_unsupported_content` to `False`, unlike every other block-open path (`pre`, `_BLOCK_TAGS`, `_resume_interrupted_block`). Currently inert for any reachable tool call: this branch only fires when `data.strip()` is truthy, so the resulting node's `runs` are always non-empty at close time, making the stale flag's value moot for `_emit_block_node`'s `preserve_if_empty` check — there's no HTML input that makes this branch's stale flag produce different `get_doc_structure`/`get_doc_as_markdown` output than the fixed version does. Fixed for state-consistency (a future change extending this branch to open on some other empty-content trigger would otherwise silently inherit a stale value) by adding `self._block_had_unsupported_content = False` alongside the existing `self._block_tag = "p"` / `self._block_named_style = None` lines, matching every sibling block-open path.

**Checks (unit test)**
- `tests/test_docs_content.py::TestBareTopLevelText::test_implicit_paragraph_open_resets_unsupported_content_flag` — feeds `_AstParser` (imported directly, matching the `test_table_depth_resets_to_zero` precedent in `tests/test_docs_tables.py`) `<p>Real text<img></p>Bare text`: the dropped `<img>` (no `src`) inside the first `<p>` sets `_block_had_unsupported_content = True`; after the following bare text opens its own implicit paragraph, the flag must read `False`, not stay stale `True`.

**Result: N/A — unit-test-verified only, per TC-DOC189/TC-D249/TC-D250 convention.** No HTML input reaches this flag's value through any live tool's observable output (see Background) — a live QA pass would confirm the same happy-path conversion the existing bare-top-level-text checks already cover, not this fix. `uv run python -m pytest tests/test_docs_content.py` → 203 passed locally.

**Result (2026-09-19) ❌ FAIL — first QA pass on PR #766, Kit.** `/code-review high origin/develop...HEAD` surfaced 2 findings, sent back for a fix in the same round: (1) the same implicit-paragraph open branch also left `self._block_resumed` stale, the identical pattern one field over — a `<table>` interrupting an open `<p>` sets `self._block_resumed = True` when it closes and resumes the `<p>`, and the `</p>` close that follows doesn't touch the flag, so it's still `True` when bare top-level text opens its own implicit paragraph right after; (2) the actual root cause — block-open state (`_block_tag`, `_block_named_style`, `_block_had_unsupported_content`, `_block_resumed`, `_run_buf`, `_pending_runs`) is hand-duplicated across all 4 call sites instead of reset by one shared helper, which is why a field can be forgotten at one site without the others noticing. Recommended folding finding 1 into a fix and doing finding 2's small helper now while the file is open. Sent back to Jay.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `TestBareTopLevelText::test_implicit_paragraph_open_resets_unsupported_content_flag` and `…resets_resumed_flag` passed.

---

### TC-DOC193: A literal leading tab in a bullet item's own source text does not nest it deeper than its sibling (#434 finding 1) ⚠️ requires-oauth

**Background:** `emitter.py`'s nested-bullet mechanism (#336) prepends `"\t" * depth` synthetic tab characters to each `BulletItem` paragraph's text as the only way to signal nesting level to `createParagraphBullets`, which infers (and removes) nesting depth from however many leading tab characters it finds — it can't tell a synthesized depth marker apart from a literal tab that happens to already be the first character of the item's own source text (e.g. hand-formatted raw HTML). Left un-stripped, a depth-1 item whose own text starts with a literal tab reads as 2 leading tabs to the API — one level deeper than an identically-nested sibling with no such literal tab — even though both are AST `depth=1`. Fixed by stripping a literal leading tab from a `BulletItem`'s own joined run text before combining it with the synthesized depth tabs (`emitter.py`'s main loop, just above where `tabs`/`text` are combined into `appended_text`). Surfaced by `/code-review high` on PR #432, filed as issue #434.

**Setup:** `create_doc(title="TC-DOC193", content_format="html", content="<ul><li>Parent<ul><li>\tChild with a literal leading tab</li><li>Child with no leading tab</li></ul></li></ul>")` — the `\t` inside the first `<li>` of the nested `<ul>` is a literal tab byte in the content string, not the two-character sequence `\` + `t`.

**Checks**
- `get_doc_structure({DOC_ID})` shows exactly 3 bullet items — "Parent" at `nestingLevel: 0`, "Child with a literal leading tab" at `nestingLevel: 1`, "Child with no leading tab" at `nestingLevel: 1` — both children at the **same** nesting level as each other (not the leading-tab child one level deeper, which is what the un-fixed code produces: `nestingLevel: 2` for it vs `1` for its sibling)
- The rendered text of "Child with a literal leading tab" in `get_doc_structure` has no leading `\t` character of its own — the literal tab was stripped, not merely absorbed into the depth count

**Cleanup:** `delete_file({DOC_ID}, permanent=true)` — a scratch doc created solely for this test, not a shared fixture.

**Note:** the companion table-position-desync half of this same finding (a literal leading tab silently under-counting `cumulative_tabs`, shifting a later table's `insertTable` position), plus the round-2 style-range/image-position regression described below, are unit-test-covered directly (`tests/test_docs_core.py::TestBulletDepthEdgeCases`) rather than re-verified live here — they're the same code path as the nesting-level fix above, and the live check already exercises the fix at its primary, most-visible defect surface.

**Result (2026-09-19) ❌ FAIL — first QA pass on PR #768, Kit.** `/code-review high origin/develop...HEAD` surfaced 6 distinct findings (7 raw; two shared one root cause). Two were confirmed-live real regressions introduced by this PR's own finding-1 fix, both sent back for a fix in the same round:
1. **Style-range overrun** — the leading-tab strip only touched the *concatenated* `run_text` string used to build the inserted text, not the underlying `Run` objects the per-run style-request loop iterates over afterward. `run_len = utf16_len(item.text)` still counted the stripped tab character(s), so a styled run's `updateTextStyle` range overran by however many tab chars were stripped (live repro: `BulletItem(runs=[Run('\tHello', bold=True)], depth=0)` → `insertText: 'Hello\n'` but `updateTextStyle range {startIndex: 1, endIndex: 7}`, one past where "Hello" actually ends).
2. **Same root cause, image position** — `insertInlineImage` position miscomputed the same way for an `Image` following a tab-stripped `Run`, landing one full segment past where the image actually belongs.

Plus 4 non-blocking cleanup items (finding 3+4 folded, finding 5 folded, finding 6 — see TC-DOC194's own Result for the finding-3/4 disposition; findings 5/6 landed here). Sent back to Jay.

**Fix pushed, awaiting re-verification (2026-09-19, Jay).** Root cause of findings 1+2 fixed together: the strip now runs on the actual `Run`/`Image` sequence (`_strip_bullet_leading_tabs`, a pure non-mutating helper — the caller's AST objects are never modified) rather than only the joined string, and that stripped sequence (`offset_runs`, carried through the newly-introduced typed `_SegmentMeta.runs` field — finding 6) is what the per-run style/position offset loop walks, not `node.runs`. New unit tests `test_literal_leading_tab_stripped_run_does_not_overrun_its_own_style_range` and `test_literal_leading_tab_stripped_run_does_not_shift_following_image` reproduce both live-repro'd findings and pass against the fix. Finding 5 (the strip's own content-loss tradeoff at depth 0, previously undocumented/untested) got an explicit comment callout in `emitter.py` plus `test_literal_leading_tab_still_strips_at_depth_zero`. `uv run python -m pytest` → 1516 passed, 3 skipped locally. Live re-verification is Kit's own next pass, not this entry.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Literal tab in the `<li>` (a `\ttabprobe` paragraph in the same write confirmed the tab reached the server). Parent at level 0; both children at level 1. The tab child's text has no leading `\t`.

---

### TC-DOC194: An orphan `<li>` outside any `<ul>`/`<ol>` does not take the isolated-bullet-run wrap path (#434 findings 3+4) (unit test)

**Background:** `html_parser.py` treats `<li>` as an ordinary `_BLOCK_TAGS` entry, reachable with no enclosing `<ul>`/`<ol>` at all — `_make_bullet_item` computes `depth = len(self._list_ordered) - 1`, which is `-1` for such an orphan. `emitter.py`'s bullet-grouping loop reading this raw `-1` unclamped for its `min_depth` routing check (`if min_depth == 0: ... else: isolated wrap path`) meant an orphan `<li>` took the 3-request isolated-run wrap path (insert anchor / bullets / delete anchor) purely because `-1 != 0`, even though the actual character-level result (0 literal leading tabs either way) is identical to what the plain 1-request `min_depth == 0` path already produces. Not a rendering defect — both paths converge on the same `nestingLevel: 0` — so there is no live-observable signal to check.

**Result (2026-09-19) ❌ FAIL — first QA pass on PR #768, Kit.** The originally-shipped fix clamped `max(node.depth, 0)` at 3 separate `emitter.py` call sites instead of at the actual source of the negative value — `html_parser.py::_make_bullet_item`'s `depth = len(self._list_ordered) - 1` — leaving every *other* consumer of `BulletItem.depth` (`ast_to_markdown.py:119`'s own `"  " * node.depth`) to independently remember the same clamp, "currently benign only because `'x' * -1 == ''`, not because of an actual invariant." Recommended folding this into a single source-level clamp (finding 3) and deduping the 3 now-redundant `emitter.py` clamps once that lands (finding 4). Sent back to Jay alongside TC-DOC193's findings 1+2.

**Fix pushed, awaiting re-verification (2026-09-19, Jay).** `_make_bullet_item` now clamps `depth = max(len(self._list_ordered) - 1, 0)` at the source — an orphan `<li>`'s `BulletItem.depth` is `0`, never `-1`, before it ever reaches `emitter.py` or `ast_to_markdown.py`. All 3 `emitter.py` call sites' redundant `max(node.depth, 0)` clamps removed; `ast_to_markdown.py`'s own `node.depth` usage is now safe by invariant rather than by accident of Python's negative-repeat semantics, needing no code change of its own. Live re-verification is Kit's own next pass, not this entry.

**Checks (unit test)**
- `tests/test_docs_core.py::TestBulletDepthEdgeCases::test_orphan_li_depth_is_clamped_at_the_ast_level` — `html_to_ast("<li>Orphan</li>")` produces a `BulletItem` with `depth == 0`, confirming the clamp lands at its actual source rather than being re-derived indirectly through `ast_to_requests`'s own behavior
- `tests/test_docs_core.py::TestBulletDepthEdgeCases::test_negative_depth_orphan_li_does_not_take_isolated_wrap_path` — `html_to_ast("<li>Orphan</li>")` (the real production path, not a hand-built `BulletItem(depth=-1)`, which is no longer a shape `emitter.py` needs to defend against) produces exactly 1 `createParagraphBullets` request and no `deleteContentRange` request (the isolated-wrap path's signature)
- `tests/test_docs_core.py::TestBulletDepthEdgeCases::test_negative_depth_orphan_li_groups_with_depth_zero_sibling` — `html_to_ast("<li>Orphan</li><ul><li>Normal</li></ul>")` still groups into one `createParagraphBullets` call, not two, and doesn't take the wrap path either

**Result: N/A — unit-test-verified only, per TC-DOC189/TC-D249/TC-D250 convention.** No source HTML makes this fix produce different `get_doc_structure`/rendered output than the un-fixed code — both routes converge on the identical `nestingLevel: 0` result; the only difference is 2 fewer wasted API requests per orphan `<li>` run. `uv run python -m pytest tests/test_docs_core.py -k TestBulletDepthEdgeCases` → 8 passed locally (round 2: 4 original + 4 new from the QA findings above).

**Result (2026-09-19) ✅ PASS — re-verification round on PR #766, Jay.** Both findings closed together: added `_AstParser._open_block(tag, *, resumed, named_style)`, a single setter for all 6 fields listed in finding 2, and routed all 4 call sites (`_resume_interrupted_block`'s resume branch, `<pre>`'s open, `_BLOCK_TAGS`' open, and `handle_data`'s implicit-paragraph open) through it — closing finding 1 as a structural consequence of finding 2's fix rather than as a standalone one-field patch. New test `tests/test_docs_content.py::TestBareTopLevelText::test_implicit_paragraph_open_resets_resumed_flag` reproduces finding 1's exact scenario (`<p>Before<table>...</table>After</p>Bare text`) and was confirmed to fail (`_block_resumed is True`) against the pre-fix code via a scratch-script diff before the fix, then pass after. Full suite green (`uv run python -m pytest` → 1508 passed, 3 skipped).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `test_orphan_li_depth_is_clamped_at_the_ast_level` and both `negative_depth_orphan_li` tests passed.

---

### TC-DOC195: A resumed block's genuine trailing `&nbsp;` survives instead of vanishing (issue #444) ⚠️ destructive

**Background:** #402 (TC-DOC138) already keeps a *fresh* `<p>&nbsp;</p>`'s whitespace-only content instead of dropping it, but a block *resumed* after a nested list/table interrupts it (e.g. `<li>Item<ul>...</ul>&nbsp;</li>`) still fell back to the pre-#402 always-drop behavior — a resumed block's whitespace-only flush is normally markup-formatting noise (e.g. the indentation newline between a nested list's `</ul>` and the outer `<li>`'s own `</li>`), not authored content, and the two need to stay distinguishable (see `test_nested_list_via_markdown_preserves_parent_text`). Fixed via a new `_is_formatting_whitespace` check in `html_parser.py`: a resumed segment's whitespace-only text that contains a character outside plain ASCII formatting whitespace (the decoded `\xa0` a `&nbsp;`/`&#160;` becomes — `HTMLParser`'s default `convert_charrefs=True` resolves these before `handle_data` ever sees them, so `handle_entityref`/`handle_charref` can't be used as the signal instead) is recognized as genuinely-authored content and preserved, since no pretty-printer/renderer has a reason to emit a non-breaking space as structural indentation. Deliberately does **not** extend to a *fresh* `<li>`/heading whose only content is `&nbsp;` (e.g. `<li>&nbsp;</li>` between two real siblings) — that's the PR #441 regression #402 itself already excludes, and it's unrelated to whether the character is "authored": lists/headings simply have no blank-line-spacer convention for a standalone empty item (`test_nbsp_only_list_item_still_dropped`/`test_nbsp_only_heading_still_dropped` cover that this stays unchanged). The identical fix also applies to the `<pre>` close-tag handler's own independent fresh/resumed whitespace check (#443) — covered by a unit test only (`test_resumed_pre_trailing_nbsp_preserved`), not a separate live case here, since a nested table inside `<pre>` has no live-observable signal beyond what TC-DOC154's own established pattern and that unit test already confirm deterministically.

**Prompt**
> "Write this HTML to doc {DOC_ID}: `<ul><li>Item<ul><li>Child</li></ul>&nbsp;</li></ul><p>Before<table><tr><td>cell</td></tr></table>&nbsp;</p>`"

**Checks**
- Call succeeds with no API error
- `get_doc_structure` shows, in order: bulleted "Item" (depth 0), bulleted "Child" (nested, depth 1), a **third** bulleted paragraph whose text is just the nbsp character at depth 0 — previously this trailing content after the nested list vanished with no trace
- "Before" paragraph, then the table, then a final paragraph whose text is just the nbsp character — the resumed `<p>`'s own trailing `&nbsp;` after the nested table also survives, matching the fresh-`<p>&nbsp;</p>` behavior TC-DOC138 already covers

**Cleanup:** write fixture content back

**Result (2026-09-20) ✅ PASS — Kit, PR #772.** Round 1's `/code-review high` found 3 blocking issues before this case was run live: (1) a resumed segment's preserved runs could carry an embedded ASCII newline adjacent to the authored `\xa0`/entity content, which the Docs API splits into a spurious extra paragraph regardless of styling (#719) — reproduces with source shaped `<ul><li>Item<ul><li>x</li></ul>\n&nbsp;</li></ul>` (a newline between the nested list's close tag and the entity); (2) `_ASCII_FORMATTING_WHITESPACE` included `\v`/`\f` despite qualifying for the same authored-content reasoning as `\xa0`; (3) the 3-line `is_resumed_authored_whitespace` expression was duplicated verbatim at both call sites (`_emit_block_node` and the `<pre>` close handler). Jay's round-2 fix (`6dbba4d`) added `_strip_formatting_whitespace` (strips formatting-noise characters from preserved runs before insertion, leaving genuine multi-line `<pre>` content untouched), narrowed the whitelist to `" \t\n\r"`, and deduped the shared check into `_is_resumed_authored_whitespace`. Full suite green (`uv run python -m pytest` → 1533 passed, 3 skipped, including 4 new regression tests). Live-verified against the fixture doc: (a) the finding-1 repro (`<ul><li>Item<ul><li>Child</li></ul>\n&nbsp;</li></ul>`) produced exactly 3 body paragraphs with no spurious split; (b) this case's own original prompt, run for the first time this round, matched every stated check exactly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Order: Item (L0), Child (L1), nbsp-only bullet (L0), Before, table "cell", nbsp-only paragraph. No error.

### TC-DOC196: Several unreachable image URLs in one document — each fails alone, everything else lands (issue #510) ⚠️ requires-oauth ⚠️ destructive

**Background:** Google's Docs API rejects an entire `batchUpdate` if any one `insertInlineImage` can't be fetched, and names only the *first* failing image per error. `_apply_doc_content` used to resend the whole document once per bad image. It now sends the text/style/bullet prefix once and retries only the trailing table/image insert pass per bad image. The failing index is also now read from the structured error body rather than `HttpError`'s display string. Round-trip counts aren't visible through the tool interface: unit tests cover those (`TestCreateDocImages::test_multiple_bad_images_retry_only_the_insert_tail`, `TestFailedInsertImageRequestIndex`). This case checks the end-to-end outcome with more than one bad image, plus a table in the same tail.

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'TC-DOC196' with this markdown content (content_format markdown):
> ```
> # Title
>
> Before text with **bold**.
>
> ![Bad1](https://example.invalid/bad1.png)
>
> - item one
> - item two
>
> ![Good](https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png)
>
> | a | b |
> |---|---|
> | 1 | 2 |
>
> ![Bad2](https://example.invalid/bad2.png)
>
> After text.
> ```"

**Checks**
- `create_doc` returns `docId`/`web_link` with no top-level `error`
- `images` has 3 entries in document order: `bad1.png` with an `error` starting `doc edit failed:`, the Google-logo URL with no `error`, and `bad2.png` with an `error` starting `doc edit failed:`
- `get_doc_structure` shows, in order: the `Title` heading, "Before text with bold." (bold run intact), bulleted "item one"/"item two", the table (cells `a`, `b`, `1`, `2`), and "After text." — nothing truncated
- The paragraph between the bullets and the table has one extra index slot beyond its text, meaning the good image was embedded (same index-math cross-check as TC-DOC57)
- Playwright: the Google logo renders between the bullets and the table, and nothing renders where the two bad images were

**Cleanup:** delete the created doc

**Result (2026-09-23) ❌ SENT BACK — Kit, PR #787 round 1.** The live checks themselves all passed. `create_doc` returned no top-level error, and `images` had 3 entries in order: bad1 and bad2 each with `doc edit failed:`, the Google logo clean. `get_doc_structure` showed every element in order with nothing truncated (heading, bold run intact, both bullets, 2×2 table, "After text."). The paragraph at 49–51 has the extra index slot. A raw `documents.get` confirmed exactly 1 `inlineObject`, placed between the bullets and the table. Each bad image left an empty paragraph behind, which the pre-#510 retry did too. Playwright: **SKIPPED.** The browser profile is signed in as the personal account and got a 403 on the Shared-Drive doc (the post-2026-09-01 auth migration). The raw API placement check above stood in for it. Also checked, not a scripted check: review finding 2 (tail inserts inheriting styles after the prefix commits) was probed live with an image right after a `##` heading and a table right after a blockquote. The split-path doc and a no-bad-image control had identical paragraph and text styles, differing only by the dropped image's empty paragraph, so the finding was not reproduced. Also observed live: bad1's per-image error text quotes `requests[2]`, an index into the tail-only retry batch, not the original request list (see the PR comment, finding 9). Sent back for code-review findings 1/3, 4, 5, 6, 7, 8, 9 (see the PR comment), not for a live failure.

**Result (2026-09-23) ✅ PASS — Kit, PR #787 round 2.** Re-verified against Jay's fix `69eff02` (fast path: `git show` plus a live re-run, no second full `/code-review`). Every round-1 finding is addressed in the diff. K=1 retries the whole remaining list as one atomic call, and the prefix/tail split starts only at the second image failure. The K≥2 partial-write window is documented in the code comment and `image-conversion.md`. Detection now uses `status == 400` plus `HttpError.reason`. The caller-facing text drops the `Invalid requests[N].` lead-in and the `HttpError` wrapper, and `rewrite_too_large_error` still fires on the stripped text (spot-checked). A fail-safe falls back to whole-list retries if any image request sits outside the inferred tail, and a unit test pins `ast_to_requests`'s tail invariant. Both stale comments are fixed. Full suite green (`uv run python -m pytest` → 1574 passed, 3 skipped). Live: this case's own prompt, K=2 (split path), matched every API check again. It gave the identical structure to round 1, with exactly 1 `inlineObject` between the bullets and the table (raw `documents.get`). Both bad-image errors read `doc edit failed: insertInlineImage: There was a problem retrieving the image...` with no wrapper and no internal index. An extra K=1 probe (heading, bold text, good image, table, one bad image, trailing text) also landed intact with one `inlineObject` and the same clean error text. Playwright: ✅ PASS (visual confirmed). It was skipped at first, for the same reason as round 1: the browser profile was signed in as the personal account and got a 403 on Shared-Drive docs. After the browser was switched to the Workspace account, this case's prompt was re-run on a fresh doc (post-merge, same code). The screenshot showed the Google logo between the bullets and the table and nothing where either bad image was, with the heading, bold run, table and "After text." all rendering normally. Created docs trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `create_doc`: no top-level error. `images`: bad1 "doc edit failed: …", the logo clean, bad2 "doc edit failed: …". Structure is complete: Title, the bold run, both bullets, 2x2 table, "After text.". The 49–51 paragraph has the extra image slot. Playwright: the logo sits between the bullets and the table, nothing where the bad images were (`tc-doc196.png`). Doc trashed.

---

### TC-DOC197: `insert_local_images` — a local image over ~179 megapixels is still size-checked, not waved through as "not an image" (PR #801)
**Background:** Pillow's `Image.open` refuses to identify an image whose header claims more than 2× `Image.MAX_IMAGE_PIXELS` (~179MP) and raises `DecompressionBombError` instead. The local size gate used to swallow that as "not a recognizable image", so the *most* oversized images skipped the megapixel check entirely and failed later with Google's bare "too large" error. `_read_dimensions` now reads the PNG/JPEG/GIF header without that guard, since no pixels are decoded there. `auto_downscale=True` still can't help, because downscaling needs a full decode, which the guard does block. That case must fail with a clear reason, not silently.

**Setup:** generate a 14000x13000 (182MP) PNG. A 1-bit image keeps it tiny on disk:
```
uv run python3 -c "
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
Image.new('1', (14000, 13000)).save('/tmp/qa-bomb.png')
"
```
Create a doc with the marker: `create_doc(title=..., content="<p>IMGMARKERBOMB</p>", folder_id={FOLDER_ID})`

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERBOMB', local_path '/tmp/qa-bomb.png', into folder {FOLDER_ID}"

Tool call: `insert_local_images(doc_id={DOC_ID}, images=[{"marker": "IMGMARKERBOMB", "local_path": "/tmp/qa-bomb.png"}], folder_id={FOLDER_ID})`

**Checks**
- `results[0]` has no `fileId` and an `error` containing "14000x13000 (182.0 megapixels)" and "25 megapixels"
- No `qa-bomb.png` appears in `{FOLDER_ID}`, and the marker text is unchanged
- Re-run with `auto_downscale=True`: `results[0]` still has no `fileId`, and its `error` ends with "Could not auto-downscale it (unreadable or corrupt image, animated, too large to decode safely, or still over the file-size limit after shrinking)." (the last reason was added by #894/#581)

**Cleanup:** trash the doc; `rm /tmp/qa-bomb.png`

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** Both checks matched exactly, and nothing was uploaded. (Round 1 reproduced the pre-fix behavior locally: `check_image_file` returned `None` for this file.) Doc trashed.

**Result (2026-10-10) ✅ PASS — PR #961 (Sky)**
insert_local_images with the 14000x13000 PNG: results[0] no fileId, error names "14000x13000 (182.0 megapixels)" and "25 megapixels". With auto_downscale=True: error ends with "Could not auto-downscale it (unreadable or corrupt image, animated, too large to decode safely, or still over the file-size limit after shrinking)." No qa-bomb.png in FOLDER_ID; marker text unchanged. Doc trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: 14000x13000 PNG: "14000x13000 (182.0 megapixels)… 25 megapixels", no `fileId`. With `auto_downscale`: the error ends with "Could not auto-downscale it (unreadable or corrupt image, animated, too large to decode safely, or still over the file-size limit after shrinking)." Nothing uploaded, marker unchanged.

---

### TC-DOC198: `insert_local_images` — an unreadable local file fails with "failed to read local file", not a raw upload error (PR #801)
**Background:** PR #801 moved the local size gate from reading the whole file to `stat()` plus a header read. Round 1 found the header read swallowed `OSError`, so a permission-denied file passed the gate as "not an image". It then crashed inside the upload as a bare `[Errno 13]`. The file open is now outside the best-effort guard.

**Setup:** `uv run python3 -c "from PIL import Image; Image.new('RGB', (10, 10)).save('/tmp/qa-noread.png')" && chmod 000 /tmp/qa-noread.png`. Create a doc with the marker `IMGMARKERNOREAD`.

**Prompt**
> "In doc {DOC_ID}, insert local images: marker 'IMGMARKERNOREAD', local_path '/tmp/qa-noread.png', into folder {FOLDER_ID}"

**Checks**
- `results[0].error` is exactly `failed to read local file: [Errno 13] Permission denied: '/tmp/qa-noread.png'`, with no `fileId`
- Nothing uploaded; marker unchanged

**Cleanup:** trash the doc; `chmod 644 /tmp/qa-noread.png && rm /tmp/qa-noread.png`

**Result (2026-09-24) ✅ PASS — Kit, PR #801 round 2 (fix `4d5f842`, issue #560).** The error text matched exactly, with no `fileId` and nothing uploaded. (Round 1 reproduced the pre-fix behavior locally: `prepare_local_image` returned `None` and the file went on to the upload.) Doc trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: chmod 000 PNG: `failed to read local file: [Errno 13] Permission denied: '<path>'`, no `fileId`. Nothing uploaded, marker unchanged.

---

### TC-DOC199: Image embedding shares through one helper and makes two Drive calls per uploaded image, not three (issue #511) ⚠️ requires-oauth ⚠️ destructive

**Background:** #511 consolidated three hand-copied share blocks (`upload_and_share_image`, `insert_local_images`'s plain upload path, `_resolve_image_source`) into `images.py`'s `share_image_file`, the two revoke closures (`_apply_doc_content`, `insert_local_images`) into `revoke_image_shares`, the local-path size-gate → upload → share sequence both `create_doc`'s image resolution and `insert_local_images` ran into `upload_and_share_local_image`, and the per-image `fileId`/`error` fold (including the #649 orphan `fileId` whose hand-copied drift PR #652's QA round caught) into `record_image_outcome` (which also carries `downscaled`/`already_shared` into the outcome entry — see TC-DOC200/TC-DOC201). Each copy used to follow its `permissions().create()` with a `files().get()` just to read `webContentLink`. That field now comes back from the call that created or looked up the file (confirmed live on #511: `create()` returns it, identical to the post-share value), so each uploaded image takes two Drive calls instead of three. Nothing about the tools' outputs should change except:
- Every sharing-failure message now reads `sharing failed for Drive file '<id>': ...` (the wording `create_doc`'s local/`drive:` path already used). Changed: `insert_local_images`' plain upload (was `uploaded file '<id>' but failed to share it: ...`) and every auto_downscale resized upload — `insert_local_images`, `create_doc`/`create_doc_from_file`/`write_doc_content`/`update_doc_from_file`, and `insert_inline_image`'s `drive_file_id` path (was `created Drive file '<id>' but failed to share it: ...`).
- Every missing-`webContentLink` message now reads `Drive returned no webContentLink for file '<id>'`, and fails *before* sharing. Was: `file <id> shared but Drive returned no webContentLink` (`create_doc` family), `uploaded and shared as <id> but Drive returned no webContentLink` (`insert_local_images`), `resized image <id> uploaded but Drive returned no webContentLink` (auto_downscale resized uploads).
- `upload_local_file`'s response gains `web_content_link` (TC-D93).
- `create_doc` and its siblings now report `downscaled: true` like `insert_local_images` does (TC-DOC201), and an image file that was already link-shared keeps its link (`already_shared: true`, TC-DOC200) in both tools.

These messages are only reachable through injected Drive failures, so they're covered by unit tests, not live. The Drive call count isn't visible through the tools, so it's covered by unit tests.

**Action (live regression — the outcomes these paths produce are unchanged)**
1. Run TC-DOC150 (`create_doc`, local-path image, revoke by default)
2. Run TC-DOC151 (`create_doc`, `drive:` image, `revoke_sharing=False`)
3. Run TC-DOC152 (`insert_local_images`, revoke by default)
4. Run TC-DOC165 (`insert_local_images`, `auto_downscale=True`)

**Checks**
- Each case above passes exactly as written: images embed, `shared` and `list_permissions` match the case's revoke setting, and there's no `revoke_error`
- Unit tests: `tests/test_docs_images.py::TestShareImageFile` (success without a `files()` call; missing link fails before sharing; `file_id` on a failure only when `created_here`), `TestRevokeImageShares` (per-entry `shared`/`revoke_error`), `TestUploadAndShareLocalImage` (two Drive calls, orphan `file_id` only after a successful upload, `downscaled` flag), `TestRecordImageOutcome`/`TestRecordImageOutcomeFlags`, `TestUploadAndShareImage::test_success_returns_uri_file_id_permission_id` and `TestInsertLocalImages::test_successful_single_image_places_and_deletes_marker` (no `files().get()`), `tests/test_docs_content.py::TestResolveImageSource::test_local_path_uploaded_shared_and_resolved` (no `files().get()`), and `tests/drive/test_transfer.py::TestUploadLocalFileCore::test_returns_web_content_link_when_drive_provides_it`

**Cleanup:** per each referenced case

**Result (2026-09-28) ❌ FAIL — Kit, PR #842 round 1 (`5604534`, issue #511).** API checks for all four referenced cases passed, and the 520 unit tests in the touched test files pass. Two defects were confirmed live, so this goes back to Dev. Playwright didn't connect this session, so the visual checks are pending for round 2.
- TC-DOC150: `images=[{fileId, shared: false}]`, no `revoke_error`; `list_permissions` shows no `anyone` grant.
- TC-DOC151: `images=[{src: "drive:<id>", fileId: <id>, shared: true}]`; `anyone`/`reader` still present.
- TC-DOC152: `results[0]` has `fileId`, `index` 9, `shared: false`, no `revoke_error`; no `anyone` grant.
- TC-DOC165: `fileId`, `downscaled: true`, `shared: false`, `index` 1 = the marker's `startIndex`; uploaded name unsuffixed `qa-oversized.png`.
- ❌ **Pre-existing public link revoked (code-review F1, pre-existing on `develop`, but it lives in the new `share_image_file`).** The file already had the user's own `anyoneWithLink` reader grant (set with `share_file`). `create_doc(content="![Pixel](drive:<id>)")` with the default `revoke_sharing=True` returned `shared: false`, and `list_permissions` afterward showed the `anyone` grant **gone**. Drive's `permissions.create` returns the existing fixed-ID `anyoneWithLink` permission, and the revoke then deletes it.
- ❌ **`create_doc` drops `downscaled` (code-review F3).** `create_doc(content="![Big](/tmp/qa-oversized.png)", auto_downscale=True)` resized and embedded the image, but `images[0]` had no `downscaled` key. `insert_local_images` reports `downscaled: true` for the same file (TC-DOC165 above).
All docs, uploads, and grants were trashed or removed.

**Result (2026-09-28) ✅ PASS — Kit, PR #842 round 2 (`07e5139`).** All six round-1 findings are fixed. F1 and F3 were re-verified live via TC-DOC200/TC-DOC201 above. F2/F4/F5/F6/F7 were checked in the fix diff, and the full unit suite passes (1900 passed, 3 skipped). Regression cases on the new code:
- TC-DOC150: `shared: false`, no `anyone` grant. Playwright: the pixel dot renders between "Report" and "After the image."
- TC-DOC151: `shared: true`, and `anyoneWithLink` is still present with `revoke_sharing=False`. Embed confirmed via `get_doc_as_markdown`.
- TC-DOC152: `fileId`, `index` 9, `shared: false`, no `anyone` grant. Embed confirmed via `get_doc_as_markdown` (`Marker: ![](…)`).
- TC-DOC165: `downscaled: true`, `shared: false`, `index` 1. Playwright: the red image renders where the marker was.
All artifacts trashed.

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
150, 152 and 165 pass; 151 skipped (sharing scope).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: 150: `shared: false`, no anyone grant, embed in the export. 151: `revoke_sharing=False` gave `shared: true`, `anyoneWithLink` present. 152: `fileId`, `index` 9, `shared: false`, no anyone grant, `Marker: ![](…)` in the export. 165: passed above. The 28 listed unit tests passed. Embeds were checked through the export, not screenshots.

---

### TC-DOC200: Embedding an image that's already link-shared leaves its link in place (PR #842 QA round 1) ⚠️ requires-oauth ⚠️ destructive

**Background:** Drive's `permissions.create()` for an `anyone` grant that already exists returns that grant's fixed ID (`anyoneWithLink`) instead of creating a new one. Before this fix, the default `revoke_sharing=True` then deleted it, removing a public link the user had set up themselves. `share_image_file` now compares the returned ID against the file's `permissionIds` from the same `get()`/`create()` call and never revokes a grant that was already there.

**Setup:** `upload_local_file(local_path="<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png", parent_folder_id={FOLDER_ID})` → note `fileId` as `{PIXEL_ID}`; then `share_file(file_id={PIXEL_ID}, permissions=[{"type": "anyone", "role": "reader"}], send_notification=False)`

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'TC-DOC200' in folder {FOLDER_ID} from this markdown: `![Pixel](drive:{PIXEL_ID})`"

Tool call: `create_doc(title="TC-DOC200", content="![Pixel](drive:{PIXEL_ID})", content_format="markdown", folder_id={FOLDER_ID})`

**Checks**
- Response has no `error`; `images` is `[{"src": "drive:{PIXEL_ID}", "fileId": "{PIXEL_ID}", "shared": true, "already_shared": true}]`, with no `revoke_error`
- `list_permissions(file_id={PIXEL_ID})` still shows the `anyone`/`reader` grant (the regression: it used to be gone)
- Control: `create_doc(title="TC-DOC200b", content="![Pixel](drive:{PIXEL_ID})", content_format="markdown", folder_id={FOLDER_ID})` after `remove_permission(file_id={PIXEL_ID}, permission_id="anyoneWithLink")` returns `shared: false` with no `already_shared`, and `list_permissions` shows no `anyone` grant (a grant this call created is still revoked)
- 🔍 Visual check: the pixel image renders in TC-DOC200

**Cleanup:** trash both docs and `{PIXEL_ID}`


**Result (2026-09-28) ✅ PASS — Kit, PR #842 round 2 (`07e5139`).** With `anyoneWithLink` already set via `share_file`: `images=[{src, fileId, already_shared: true, shared: true}]`, no `revoke_error`. `list_permissions` still shows `anyoneWithLink`: the round-1 regression is fixed. Control (after `remove_permission`): TC-DOC200b returned `shared: false` with no `already_shared`, and no `anyone` grant remained. Embed confirmed via `get_doc_as_markdown` (`![](…)`). The 1×1 pixel sits under the cursor at index 1, so a screenshot can't show it. Docs and pixel trashed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
Needs a persistent anyone share; ran before the user's explicit sharing approval.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`jay`: With `anyoneWithLink` already set: `images=[{…, already_shared: true, shared: true}]`, no `revoke_error`, and the grant is still there. Control after `remove_permission`: `shared: false`, no `already_shared`, no anyone grant. Embed confirmed in the export. The required visual check couldn't be confirmed: the 1x1 pixel doesn't show in a screenshot (`tc-doc200.png`).

---

### TC-DOC201: `create_doc` reports `downscaled` for an auto-downscaled image (PR #842 QA round 1) ⚠️ requires-oauth ⚠️ destructive

**Background:** `insert_local_images` reported `downscaled: true` for a resized image; `create_doc` resized and embedded the same file but dropped the flag. Both now record outcomes through `record_image_outcome`.

**Setup:** create the oversized fixture as in TC-DOC162: `uv run python3 -c "from PIL import Image; Image.new('RGB', (6000, 6000), 'red').save('/tmp/qa-oversized.png')"`

**Prompt**
**Playwright: required**
> "Create a Google Doc titled 'TC-DOC201' in folder {FOLDER_ID} from this markdown, auto-downscaling oversized images: `![Big](/tmp/qa-oversized.png)`"

Tool call: `create_doc(title="TC-DOC201", content="![Big](/tmp/qa-oversized.png)", content_format="markdown", folder_id={FOLDER_ID}, auto_downscale=True)`

**Checks**
- Response has no `error`; `images[0]` has `fileId`, `shared: false`, and `downscaled: true`
- 🔍 Visual check: a red image renders in the doc

**Cleanup:** trash the doc and `images[0].fileId`; `rm /tmp/qa-oversized.png`

**Result (2026-09-28) ✅ PASS — Kit, PR #842 round 2 (`07e5139`).** `images[0]` had `fileId`, `downscaled: true`, `shared: false`. Playwright: the red image renders. Extra check for the `drive:` half of F3: `create_doc(content="![Big](drive:<oversized upload>)", auto_downscale=True)` also returned `downscaled: true`, with a new resized `fileId`. Docs, the resized copies, and the oversized upload were trashed.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: `create_doc(auto_downscale=True)`: `images[0]` has `fileId`, `downscaled: true`, `shared: false`. Playwright: the red image renders (`tc-doc201.png`). Trashed.

---

### TC-DOC202: A failed doc edit still revokes the image's temporary share (#789) ⚠️ destructive

**Background:** `_apply_doc_content` shares each local-path/`drive:` image `anyone:reader` before the doc edit, and used to revoke those shares only after the edit succeeded. Any failure after the shares were made (the content `batchUpdate`, a retry, `fill_tables`, anchor resolution) left the image publicly readable with nothing reporting it, and the raise lost every image file ID. The revoke now runs whether the edit succeeds, fails, or is cancelled, and a failed edit returns `{"error", "docId", "images"}` instead of raising (PR #877 round 2). The case forces a non-image failure by locking the target doc (`contentRestrictions.readOnly`), which makes the Docs API reject the `batchUpdate` with a 403. The doc is left empty so `write_doc_content` has nothing to clear and reaches the image step before the 403.

**Setup:**
1. `create_doc(title="TC-DOC202", folder_id={FOLDER_ID})` with no content. Record `docId` as `{LOCKED_DOC_ID}`.
2. `upload_local_file(local_path="<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png", folder_id={FOLDER_ID})`. Record its ID as `{PIXEL_FILE_ID}`.
3. No tool sets a content restriction, so lock the doc with a scratch script from the checkout under test, using the same OAuth token as the server under test:

```bash
uv run python3 -c "
from googleapiclient.discovery import build
from mcp_gee_sweet.auth import _oauth_creds
d = build('drive', 'v3', credentials=_oauth_creds(), cache_discovery=False)
d.files().update(fileId='{LOCKED_DOC_ID}', body={'contentRestrictions': [{'readOnly': True, 'reason': 'TC-DOC202'}]}, supportsAllDrives=True).execute()
"
```

**Prompt**
> "Replace the content of doc {LOCKED_DOC_ID} with this markdown: `Text\n\n![Pixel](drive:{PIXEL_FILE_ID})`"

Tool call: `write_doc_content(doc_id={LOCKED_DOC_ID}, content="Text\n\n![Pixel](drive:{PIXEL_FILE_ID})", content_format="markdown")`

**Checks**
- The call returns (doesn't raise) `{"error": "doc edit failed: ...", "docId": "{LOCKED_DOC_ID}", "images": [{"src": "drive:{PIXEL_FILE_ID}", "fileId": "{PIXEL_FILE_ID}", "shared": false}]}`, and the error text includes the Docs `batchUpdate`'s 403 "The caller does not have permission". If the call succeeds instead, the lock didn't take and the case proves nothing; re-check setup step 3
- `list_permissions(file_id={PIXEL_FILE_ID})` shows no `anyone` permission. Before the fix, an `anyone`/`reader` grant was left behind here (reproduced live by the Dev with a scratch script on 2026-10-03)
- If the server under test writes a log file (`LOG_FILE`), it has a WARNING line naming `{LOCKED_DOC_ID}`, with `files created by this call: none; pre-existing files: {PIXEL_FILE_ID}; still link-shared by this call: none` (a `drive:` source is the caller's own file, never listed as created)

**Cleanup:** unlock the doc with the setup script, using `body={'contentRestrictions': [{'readOnly': False}]}`. Then trash `{LOCKED_DOC_ID}` and `{PIXEL_FILE_ID}`.

**Result (2026-10-03) ✅ PASS — Kit, PR #877 round 1 (`505e8a5`).** `write_doc_content` failed with the expected 403 "The caller does not have permission" from the Docs `batchUpdate`. A `list_permissions` call made after the failure showed no `anyone` grant on the pixel. `LOG_FILE` had `WARNING ... Doc edit failed for {LOCKED_DOC_ID} after its images were resolved; image file IDs: {PIXEL_FILE_ID}; still link-shared: none`. The case passes, but the log line lists `{PIXEL_FILE_ID}`, the caller's own pre-existing `drive:` file, under the IDs `_log_images_after_failed_edit`'s docstring calls now-orphaned files (finding F2 in the round 1 PR comment). The doc was unlocked, and both files were trashed.

**Result (2026-10-03) ✅ PASS — Kit, PR #877 round 2 (`de95c80`).** `write_doc_content` returned (didn't raise) `{"error": "doc edit failed: <HttpError 403 ... \"The caller does not have permission\">", "docId": "{LOCKED_DOC_ID}", "images": [{"src": "drive:{PIXEL_FILE_ID}", "fileId": "{PIXEL_FILE_ID}", "shared": false}]}`. `list_permissions` showed no `anyone` grant on the pixel. `LOG_FILE` had `files created by this call: none; pre-existing files: {PIXEL_FILE_ID}; still link-shared by this call: none`. Separately, a minimal anyio model of the new shielded resolve and revoke structure, cancelled both mid-resolution and mid-edit, ran every delete and logged the warning both times. The doc was unlocked, and both files were trashed.

**Result (2026-10-04) ⚠️ PARTIAL (log check not run) — Kit, PR #903 round 2 (`4e392c3`).** Re-run because the failed-edit log helper moved from `content.py` to `images.py` (`log_images_after_failed_edit`, shared with `insert_local_images`). `write_doc_content` returned (didn't raise) `{"error": "doc edit failed: <HttpError 403 ... \"The caller does not have permission\">", "docId": "{LOCKED_DOC_ID}", "images": [{"src": "drive:{PIXEL_FILE_ID}", "fileId": "{PIXEL_FILE_ID}", "shared": false}]}`. `list_permissions` showed no `anyone` grant on the pixel. The kit server writes no `LOG_FILE`, so the WARNING line wasn't checked live. `tests/test_docs_content.py` asserts its arguments, now patched on `images_module.logger`. The doc was unlocked, and both files were trashed.
**Corrected (2026-10-17, #1044 audit):** the log check wasn't run.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
The scratch script needs a usable OAuth token (see DOC80).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`jay`: Needs the fixture-owning account's token in a scratch script (the lock script); not available in this pass.

---

### TC-DOC203: A cancelled `insert_local_images` still revokes the image's temporary share (#883) ⚠️ requires-oauth ⚠️ destructive

**Background:** `insert_local_images` uploads each image, shares it `anyone:reader`, sends the doc `batchUpdate`, then revokes the share. The revoke used to run only after the `batchUpdate` returned, so a call cancelled during the upload/share gather or the `batchUpdate` left the uploaded image publicly readable, with nothing reporting it. Now the upload/share gather is shielded from cancellation, so every granted share is recorded, and a shielded revoke runs on every exit, including a cancelled one. A cancelled call returns nothing, so every file it uploaded is logged as a WARNING, on every exit path: before the edit, with nothing left to embed, while the `batchUpdate` runs, and during the post-edit revoke (PR #903 round 2). A cancellation that arrives during the gather lands before the `batchUpdate` is sent, so the doc is left untouched. One that arrives while the `batchUpdate` runs can't stop it: the edit is atomic, so the doc is either untouched or has the image embedded, and either way no public share is left. This is the same pattern `_apply_doc_content` got in PR #877 (TC-DOC202), and both log through the same helper.

No MCP client can cancel a tool call at a chosen point, so this case uses `scripts/qa_cancel_insert_local_images.py`. The script runs the checkout's own `insert_local_images` against the real APIs inside an anyio task group and cancels it at one point: `share` (while the permission is being granted), `share-fail` (the same, but the share then fails, leaving an unshared upload), `edit` (just before the `batchUpdate`), `inflight` (while the `batchUpdate` runs), or `revoke` (during the post-edit revoke). Run it from the checkout under test with that checkout's OAuth token (`TOKEN_PATH`). It prints the tool's WARNING to stderr.

**Setup:**
1. `create_doc(title="TC-DOC203", content="Before\n\nIMGMARKER883\n\nINFLIGHT883\n\nREVOKE883\n\nAfter", content_format="markdown", folder_id={FOLDER_ID})`. Record `docId` as `{DOC_ID}`.

**Prompt**
> (none — script-driven; the steps below are shell commands plus tool calls)

**Steps**
1. `uv run python scripts/qa_cancel_insert_local_images.py {DOC_ID} {FOLDER_ID} <repo-root>/docs/qa/fixtures/qa-fixture-pixel.png IMGMARKER883 share`. Record the file ID from the WARNING as `{SHARE_FILE_ID}`.
2. The same command with `share-fail` in place of `share`. Record the WARNING's file ID as `{ORPHAN_FILE_ID}`.
3. The same command with `edit`. Record the WARNING's file ID as `{EDIT_FILE_ID}`.
4. The same command with `edit --keep-shared`. Record the WARNING's file ID as `{KEPT_FILE_ID}`.
5. The same command with marker `INFLIGHT883` and point `inflight`. Record the WARNING's file ID as `{INFLIGHT_FILE_ID}`.
6. The same command with marker `REVOKE883` and point `revoke`. Record the WARNING's file ID as `{REVOKE_FILE_ID}`.

**Checks**
- Each run prints `cancelled at '<point>'; the tool returned nothing` and a WARNING `Doc edit for {DOC_ID} failed or was cancelled after its images were resolved; files created by this call: <one file ID>; pre-existing files: none; still link-shared by this call: ...`. That last field is the `{KEPT_FILE_ID}` itself for step 4, and `none` for every other step. Before round 2, steps 2 and 6 logged nothing
- `list_permissions` on `{SHARE_FILE_ID}`, `{ORPHAN_FILE_ID}`, `{EDIT_FILE_ID}`, `{INFLIGHT_FILE_ID}`, and `{REVOKE_FILE_ID}` shows no `anyone` permission. Before the fix, the `edit` run left an `anyone`/`reader` grant and logged nothing (reproduced live by the Dev with this script on 2026-10-04)
- `list_permissions(file_id={KEPT_FILE_ID})` does show the `anyone`/`reader` permission (`revoke_sharing=False` is respected on the cancel path)
- After `refresh_cache(doc_id={DOC_ID})`, `get_doc_content(file_id={DOC_ID})` still has `IMGMARKER883` (none of steps 1–4 edited the doc) and no longer has `REVOKE883` (step 6 cancels after the edit landed). `INFLIGHT883` may be either present or gone, since the in-flight edit can't be stopped; if it's gone, `get_doc_as_markdown` shows an image in its place

**Cleanup:** trash `{SHARE_FILE_ID}`, `{ORPHAN_FILE_ID}`, `{EDIT_FILE_ID}`, `{KEPT_FILE_ID}`, `{INFLIGHT_FILE_ID}`, `{REVOKE_FILE_ID}`, and `{DOC_ID}`.

**Result (2026-10-04) ✅ PASS (checks as written); 🔍 two probes beyond the case — Kit, PR #903 round 1 (`8a634db`).** All three steps ran from the kit worktree with its OAuth token, on a scratch doc in `{FOLDER_ID}`. Each step printed `cancelled at '<point>'; the tool returned nothing` and the expected WARNING. `still link-shared by this call` was `none` for `share` and `edit`, and listed `{KEPT_FILE_ID}` for `edit --keep-shared`. `list_permissions` showed no `anyone` grant on `{SHARE_FILE_ID}` or `{EDIT_FILE_ID}`, and showed `anyoneWithLink`/`reader` on `{KEPT_FILE_ID}`. `get_doc_content` still read `Before`, `IMGMARKER883`, `After`. That read came before any cache refresh, but the in-flight probe below then found the marker, so no step had edited the doc.

Two extra probes ran from a scratch copy of the script (not committed):
- **`share-fail`** (the gate holds the share, then raises instead of granting): the call uploaded a file, the share failed, the cancel arrived during the shielded gather, and **no WARNING was logged**. With every placement failed, the tool returns at `if not ready` before any unshielded await, so the cancellation is never seen there and the created orphan (#649) appears in no log. That breaks the docstring's new promise (finding 1 in the round 1 PR comment).
- **`inflight`** (the gate hands the `batchUpdate` to its worker thread at once, and the cancel lands while the thread runs): the WARNING was logged and the share revoked, with no `anyone` grant afterward. The edit still landed after the cancel: after `refresh_cache`, `get_doc_as_markdown` showed the image embedded where the marker had been. Docs had fetched the image before the revoke. The batchUpdate is atomic (it either embeds with a successful fetch or fails whole), so neither ordering leaves a broken embed or a public share. The case's background says a cancel "during ... the `batchUpdate`" is covered, but the committed script only cancels before the send (finding 5).

All files from both probes and the three steps, and the doc, were trashed.

**Result (2026-10-04) ✅ PASS — Kit, PR #903 round 2 (`4e392c3`).** All six steps ran from the kit worktree with its OAuth token, on a fresh scratch doc in `{FOLDER_ID}`. Each step printed `cancelled at '<point>'; the tool returned nothing` and the WARNING `Doc edit for {DOC_ID} failed or was cancelled after its images were resolved; files created by this call: <one file ID>; pre-existing files: none; still link-shared by this call: ...`. That last field listed `{KEPT_FILE_ID}` for step 4 and was `none` for every other step. Steps 2 (`share-fail`, the orphan) and 6 (`revoke`), which logged nothing in round 1's probe, now log. `list_permissions` showed no `anyone` grant on `{SHARE_FILE_ID}`, `{ORPHAN_FILE_ID}`, `{EDIT_FILE_ID}`, `{INFLIGHT_FILE_ID}`, or `{REVOKE_FILE_ID}`, and showed `anyoneWithLink`/`reader` on `{KEPT_FILE_ID}`. After `refresh_cache`, `get_doc_as_markdown` read `Before`, `IMGMARKER883`, an image, an image, `After`. So steps 1–4 left `IMGMARKER883` untouched, step 6's edit landed before its cancel, and step 5's in-flight edit also landed (an image replaced `INFLIGHT883`). All six files and the doc were trashed.

**Result (2026-10-14) ✅ PASS — Kit, PR #1029 round 1 (`089f6ee`).** Re-run on the shared `ImageShareLifecycle`. All six steps ran from the kit worktree with its OAuth token, on a fresh scratch doc in a scratch folder on the QA Shared Drive. Each printed `cancelled at '<point>'; the tool returned nothing` and the expected WARNING, whose `still link-shared by this call` listed `{KEPT_FILE_ID}` for step 4 and was `none` otherwise. `list_permissions` showed no `anyone` grant on the five revoked files and `anyoneWithLink`/`reader` on `{KEPT_FILE_ID}`. `get_doc_as_markdown` read `Before`, `IMGMARKER883`, an image, an image, `After`. New with #907: step 5 printed `(edit landed: no)` from the cancel path, then the lifecycle's "finished afterward" DEBUG line and a later `(edit landed: yes)`. Script note: steps 3–4 print `batchUpdates sent: 1; landed: 0`, but the `edit` gate cancels before the request is sent (`sent` is counted before the hold; sent back in the round 1 PR comment). Cleanup done.

**Result (2026-10-14) ✅ PASS (partial re-run) — Kit, PR #1029 round 2 (`fd591d9`).** Re-verified the script-counter fix only: step 3 (`edit`) on a fresh scratch doc printed the cancel line, the WARNING (`still link-shared by this call: none`), and `batchUpdates sent: 0; landed: 0` (round 1 printed `sent: 1`). `IMGMARKER883` was still in the doc, and the file had no `anyone` grant. Cleanup done.

**Result (2026-10-15) ✅ PASS — Kit, PR #1029 round 4 (`d748932`).** Re-run after the `develop` merge (#1023, #1034). All six steps ran from the kit worktree with its OAuth token, on a fresh scratch doc in a scratch folder on the QA Shared Drive. Each printed `cancelled at '<point>'; the tool returned nothing` and the expected WARNING, whose `still link-shared by this call` listed `{KEPT_FILE_ID}` for step 4 and was `none` otherwise. Steps 1–4 printed `batchUpdates sent: 0; landed: 0`. Step 5 printed `(edit landed: no)`, the lifecycle's "finished afterward" DEBUG line, then `(edit landed: yes)`. `list_permissions` showed no `anyone` grant on the five revoked files and `anyoneWithLink`/`reader` on `{KEPT_FILE_ID}`. After `refresh_cache`, `get_doc_as_markdown` read `Before`, `IMGMARKER883`, an image, an image, `After`. Cleanup done.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
The scratch script needs a usable OAuth token (see DOC80).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`jay`: Needs the fixture-owning account's token in a scratch script (`qa_cancel_insert_local_images.py`); not available in this pass.

## Unreadable source file returns an error — `create_doc_from_file` / `update_doc_from_file` (PR #961)

Both tools read the local file through the shared `_read_doc_source_file` helper. Before PR #961's round 2, a path that existed but wasn't a readable UTF-8 regular file raised out of the tool (`[Errno 21] Is a directory`, `'utf-8' codec can't decode byte 0xe9 ...`) instead of returning `{"error": ...}`.

### TC-DOC213: A directory or non-UTF-8 source file returns `{"error": ...}`, and nothing is created or edited
**Setup:**
- `mkdir -p /tmp/tc-doc213/dir.md`
- `python3 -c "open('/tmp/tc-doc213/latin1.html','wb').write('<p>caf\xe9</p>'.encode('latin-1'))"`
- `get_doc_content(file_id={DOC_ID})`, note the content for comparison afterward

**Steps**
1. `create_doc_from_file(local_path="/tmp/tc-doc213/dir.md", folder_id={FOLDER_ID})`
2. `create_doc_from_file(local_path="/tmp/tc-doc213/latin1.html", folder_id={FOLDER_ID})`
3. `update_doc_from_file(doc_id={DOC_ID}, local_path="/tmp/tc-doc213/dir.md")`
4. `update_doc_from_file(doc_id={DOC_ID}, local_path="/tmp/tc-doc213/latin1.html")`

**Checks**
- Each call returns a dict with an `error` key naming the path (any wording). None comes back as `Error executing tool ...`
- `list_files(folder_id={FOLDER_ID})` shows no new Doc named `dir` or `latin1` (the filename stem `create_doc_from_file` uses as the default title; steps 1–2 fail before the Drive `create`)
- `get_doc_content(file_id={DOC_ID})` matches the Setup snapshot (steps 3–4 fail before any Docs API call)

**Cleanup:** `rm -rf /tmp/tc-doc213`

**Result (2026-10-10) ✅ PASS — Sky, PR #961 round 2 (`849f0bb`).** Ran with the fixtures under this job's scratch dir instead of `/tmp/tc-doc213`. Steps 1 and 3 returned `{"error": "Not a regular file: <path>/dir.md"}`; steps 2 and 4 returned `{"error": "File is not valid UTF-8: <path>/latin1.html (invalid continuation byte at byte 6)"}`. No call surfaced as `Error executing tool`. `list_files({FOLDER_ID})` showed only the three standing fixtures. After `refresh_cache`, `get_doc_content({DOC_ID})` matched the Setup snapshot. Round 1 reproduced both raises on the pre-fix code (`075ce99`).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: In my scratch dir: the `dir.md` directory gave "Not a regular file: …", and `latin1.html` gave "File is not valid UTF-8: … (invalid continuation byte at byte 6)", from both `create_doc_from_file` and `update_doc_from_file`. None surfaced as "Error executing tool". No new Doc in the folder. Doc content unchanged after `refresh_cache`.

## Comment quoted text is plain text, not HTML-escaped (#984)

Drive returns a comment's `quotedFileContent.value` HTML-escaped (`Caf&#233;`, `&amp;`, `&lt;`, `&quot;`, `&#39;`), and a literal `&amp;` in the anchor as `&amp;amp;`. `add_doc_comment`, `list_doc_comments`, and `get_doc_as_markdown(include_comments=True)` unescape it once. The Markdown export then escapes the quote only as Markdown needs, with `"> "` on every line, and escapes comment authors, text, and replies the same way.

### TC-DOC215: Non-ASCII, `&`/`<`/`"`, literal-entity, and multi-line anchors round-trip as plain text ⚠️ destructive ⚠️ requires-oauth
**Setup:** `create_doc(title="QA TC-DOC215", folder_id={FOLDER_ID}, content="<p>Café and Tom &amp; Jerry, a &lt; b, say \"hi\" it's &amp;amp; literal</p><p>line one</p><p>line *two* &lt;x&gt;</p>")`, note the returned `docId` as `{SCRATCH_DOC_ID}`

**Steps**
1. `add_doc_comment(doc_id={SCRATCH_DOC_ID}, content="QA TC-DOC215 a <b> *x*", quoted_text="Café and Tom & Jerry, a < b, say \"hi\" it's")`
2. `add_doc_comment(doc_id={SCRATCH_DOC_ID}, content="QA TC-DOC215 b", quoted_text="&amp; literal")`
3. `add_doc_comment(doc_id={SCRATCH_DOC_ID}, content="QA TC-DOC215 c", quoted_text="line one\nline *two* <x>")`
4. `list_doc_comments(doc_id={SCRATCH_DOC_ID})`
5. `get_doc_as_markdown(doc_id={SCRATCH_DOC_ID}, include_comments=True)`

**Checks**
- Steps 1–3 each return `quoted_text` equal to the `quoted_text` passed in, character for character: `Café`, not `Caf&#233;`; `&`, `<`, `"`, `'` unescaped; step 2 returns `&amp; literal`, not `&amp;amp; literal` or `& literal`
- Step 4's three comments carry the same `quoted_text` values as steps 1–3
- Step 5's `## Comments` section contains these quote blocks, each followed by a blank line before the comment text:
  - `> Café and Tom & Jerry, a < b, say "hi" it's`
  - `> \&amp; literal`
  - `> line one\` (ending in a hard-break backslash, since PR #991 round 2) then `> line \*two\* \<x>` on the next line
- Step 5 renders step 1's comment text as `QA TC-DOC215 a \<b> \*x\*` (plain text, escaped only as Markdown needs), and step 1 itself returns `content` unchanged
- No `&#233;`, `&quot;`, `&#39;`, or `&lt;` appears anywhere in step 5's comments section

**Cleanup:** `delete_file(file_id={SCRATCH_DOC_ID})`

**Result (2026-10-11) ✅ PASS — Kit, PR #991 round 1 (`9953a83`).** Steps 1–3 echoed each `quoted_text` exactly (`Café and Tom & Jerry, a < b, say "hi" it's`, `&amp; literal`, `line one\nline *two* <x>`); step 4 returned the same three values. Step 5's comments section had `> Café and Tom & Jerry, a < b, say "hi" it's`, `> \&amp; literal`, and `> line one` / `> line \*two\* \<x>`, each followed by a blank line, and comment text `QA TC-DOC215 a \<b> \*x\*`; no `&#233;`/`&quot;`/`&#39;`/`&lt;` in the section. Extra probe: a comment created in the Docs UI (Playwright) on the doc's literal `&amp; literal` text also came back from `list_doc_comments` as `&amp; literal`, so Drive escapes UI-created anchors too and a single unescape is correct for them. The case passes, but the round was sent back for Markdown-escaping gaps in comment text that this case doesn't exercise (see the PR comment).

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: Steps 1–3 echo `quoted_text` exactly (`Café…it's`, `&amp; literal`, `line one\nline *two* <x>`), and `list_doc_comments` matches. The export has `> Café and Tom & Jerry, a < b, say "hi" it's`, `> \&amp; literal`, `> line one\` / `> line \*two\* \<x>`, and `QA TC-DOC215 a \<b> \*x\*`. No entities.

### TC-DOC217: Multi-line comment text and indented/rule body paragraphs stay plain text in the Markdown export ⚠️ destructive ⚠️ requires-oauth
Comment text is plain text, so no line of it may render as Markdown structure, and each line keeps its own line (a hard break, not a soft wrap). Body paragraphs that start with spaces or a tab before a marker, or that are a `---` rule line, stay plain paragraphs too (#993). Replies are covered by unit tests only: the one tool that posts a reply, `resolve_doc_comment`, also resolves the comment, and `include_comments` exports only open ones.

**Setup:**
- `create_doc(title="QA TC-DOC217", folder_id={FOLDER_ID}, content="<p>anchor</p>")`, note the returned `docId` as `{SCRATCH_DOC_ID}`
- `insert_doc_text(doc_id={SCRATCH_DOC_ID}, insertions=[{"index": 1, "text": " - a\n  # h\n---\n\ttab indent\n## Notes\n"}])`

**Steps**
1. `add_doc_comment(doc_id={SCRATCH_DOC_ID}, quoted_text="anchor", content="Summary\n---\nPoints:\n - a\n   - b\na | b\n-|-\nc | d\n## Notes\n\n    indented *x*")`
1a. `add_doc_comment(doc_id={SCRATCH_DOC_ID}, quoted_text="Summary\n===  ", content="QA TC-DOC217 setext")` (the trailing spaces after `===` are part of the anchor; Drive keeps them in `quoted_text`)
2. `get_doc_as_markdown(doc_id={SCRATCH_DOC_ID}, include_comments=True, local_path="/tmp/tc-doc217.md")`
3. `uv run python -c "from markdown_it import MarkdownIt; print(MarkdownIt('commonmark').enable('table').render(open('/tmp/tc-doc217.md').read()))"`

**Checks**
- Step 3's HTML has no `<ul>`, `<ol>`, `<h1>`, `<table>`, or `<pre>`. It has exactly one `<h2>` (`Comments`) and one `<hr />`: the comments section's own heading and separator
- The body renders `<p>- a</p>`, `<p># h</p>`, `<p>---</p>`, `<p>tab indent</p>`, and `<p>## Notes</p>`
- Step 1's comment renders `Summary`, `---`, `Points:`, `- a`, `- b`, `a | b`, `-|-`, `c | d`, and `## Notes` as separate lines joined by `<br />` in one paragraph, with no literal `\` at any line end, then `<p>indented *x*</p>` as its own paragraph
- Step 1a's quote renders as `<blockquote>` holding `<p>Summary<br />` and `===</p>`, with no `<h1>`

**Cleanup:** `delete_file(file_id={SCRATCH_DOC_ID})`, `rm /tmp/tc-doc217.md`

**Result (2026-10-11) ✅ PASS (case as written), ❌ sent back on probes — Kit, PR #991 round 2 (`de8143e`).** Ran with the export under this job's scratch dir instead of `/tmp`. Every check passed for the case's own content: body `<p>- a</p>`, `<p># h</p>`, `<p>---</p>`, `<p>tab indent</p>`; the comment's eight lines joined by `<br />` in one paragraph, then `<p>indented *x*</p>`; no `<ul>`/`<ol>`/`<table>`/`<pre>`. Extra probes on the same doc failed: (1) a body paragraph `## Notes` and a comment line `## Notes` each rendered as `<h2>`, and the comment line before it kept a literal `\`, because `_LEADING_SIMPLE_MARKER` matches only a single `#`; (2) `add_doc_comment(quoted_text="Summary\n===  ")` exported `> Summary\` / `> ===  `, which renders as `<h1>Summary\</h1>` inside the blockquote, because `_LEADING_RULE_LINE` doesn't allow trailing whitespace after `=`. Drive trims trailing whitespace from the end of comment `content` (not from `quoted_text`), and a mid-content `===  ` line is safe because the hard break before it blocks the setext.

**Result (2026-10-11) ✅ PASS — Kit, PR #991 round 3 (`95ba882`).** Ran with the export under this job's scratch dir instead of `/tmp`. Step 3's HTML had no `<ul>`/`<ol>`/`<h1>`/`<table>`/`<pre>`, exactly one `<h2>` (`Comments`) and one `<hr />`. Body: `<p>- a</p>`, `<p># h</p>`, `<p>---</p>`, `<p>tab indent</p>`, `<p>## Notes</p>`. Step 1's comment rendered its nine lines through `## Notes` joined by `<br />` with no literal `\`, then `<p>indented *x*</p>`. Step 1a's `quoted_text` came back as `Summary\n===  ` (trailing spaces kept) and rendered as `<blockquote><p>Summary<br />===</p></blockquote>`, no `<h1>`.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: markdown-it render: no ul/ol/h1/table/pre; one `<h2>` and one `<hr />`. The body is `<p>- a</p>`, `<p># h</p>`, `<p>---</p>`, `<p>tab indent</p>`, `<p>## Notes</p>`. The comment's lines are joined by `<br />` with no trailing `\`, then `<p>indented *x*</p>`. The setext quote is `<blockquote><p>Summary<br />===</p>`, no h1.

### TC-DOC218: A trailing-slash `local_path` naming a missing directory creates it; one naming an existing file is refused (issue #990) ⚠️ local-filesystem
Every capped tool's `local_path` goes through the shared `write_capped_result_to_disk`. Before #990, `dir/` for a directory that didn't exist yet was written as a *file* named `dir`, and `file/` over an existing file overwrote it.

**Setup:** `rm -rf /tmp/qa-990 && mkdir -p /tmp/qa-990/linkdir && printf 'keep me' > /tmp/qa-990/blocker && ln -s /tmp/qa-990/missing /tmp/qa-990/dangling && ln -s /tmp/qa-990/elsewhere /tmp/qa-990/linkdir/{DOC_ID}.md`. Confirm `/tmp/qa-990/new`, `/tmp/qa-990/missing`, and `/tmp/qa-990/elsewhere` don't exist.

**Steps**
1. `get_doc_as_markdown(doc_id={DOC_ID}, local_path="/tmp/qa-990/new/sub/")`
2. `get_doc_as_markdown(doc_id={DOC_ID}, local_path="/tmp/qa-990/blocker/")`
3. `get_doc_as_markdown(doc_id={DOC_ID}, local_path="/tmp/qa-990/blocker/sub/")`
4. `get_doc_as_markdown(doc_id={DOC_ID}, local_path="/tmp/qa-990/dangling/")`
5. `get_doc_as_markdown(doc_id={DOC_ID}, local_path="/tmp/qa-990/linkdir/")`

**Checks**
- Step 1 returns `local_path` `/tmp/qa-990/new/sub/{DOC_ID}.md`. `/tmp/qa-990/new/sub` is a directory (`test -d`), not a file, and the `.md` file in it holds raw Markdown whose byte size equals `bytes_written`
- Step 2 raises "local_path '/tmp/qa-990/blocker/' has a non-directory path component at '/tmp/qa-990/blocker'; local_path ends in a path separator or '.', which makes it a directory target…", and `/tmp/qa-990/blocker` still holds `keep me`
- Step 3 raises a `ValueError` "…has a non-directory path component at '/tmp/qa-990/blocker'" (a file further up the path), not a raw `NotADirectoryError` (PR #1000 QA round 1)
- Step 4 raises a `ValueError` "…has a symlink to a missing target at '/tmp/qa-990/dangling'", not a raw `FileExistsError`, and `/tmp/qa-990/missing` still doesn't exist (PR #1000 QA round 1)
- Step 5 raises a `ValueError` "…has a symlink to a missing target at '/tmp/qa-990/linkdir/{DOC_ID}.md'", and `/tmp/qa-990/elsewhere` still doesn't exist: the file joined onto a directory gets the same checks as a file `local_path` (PR #1000 QA round 2)

**Cleanup:** `rm -rf /tmp/qa-990`

**Result (2026-10-11) ✅ PASS — Kit, PR #1000 round 1 (`12bd36a`).** Ran under this job's scratch dir instead of `/tmp`. Step 1 returned `local_path` `<dir>/new/sub/{DOC_ID}.md`, `bytes_written` 96; `new/sub` is a directory and the file is 96 bytes. Step 2 raised the expected "ends in a separator, so it must be a directory, but … is an existing file" error and `blocker` still holds `keep me`. Probes outside the case (sent back): `<file>/sub/` with `<file>` a regular file raises a raw `NotADirectoryError`, and `<dangling symlink>/` raises `FileExistsError`, not the new `ValueError`.

**Result (2026-10-11) ✅ PASS — Kit, PR #1000 round 2 (`695d0f9`).** Ran under this job's scratch dir instead of `/tmp`. Step 1 returned `<dir>/new/sub/{DOC_ID}.md`, `bytes_written` 96, and `new/sub` is a directory. Step 2 raised "…has a non-directory path component at '<dir>/blocker'; local_path ends in a path separator or '.', which makes it a directory target…", and `blocker` still holds `keep me`. Step 3 raised the `ValueError` naming `<dir>/blocker`. Step 4 raised "…has a symlink to a missing target at '<dir>/dangling'", and `missing` was not created.

**Result (2026-10-11) ✅ PASS — Kit, PR #1000 round 3 (`290f5bc`).** Ran under this job's scratch dir instead of `/tmp`. Steps 1–4 matched round 2 (step 1 wrote `<dir>/new/sub/{DOC_ID}.md`, 96 bytes; steps 2–4 raised the expected `ValueError`s; `blocker` still holds `keep me`; `missing` not created). Step 5 raised "…has a symlink to a missing target at '<dir>/linkdir/{DOC_ID}.md'", and `elsewhere` was not created.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: In my scratch dir. Step 1 wrote `new/sub/<id>.md`: a directory, 267 bytes = `bytes_written`. Step 2 raised "non-directory path component … ends in a path separator", and `blocker` still holds "keep me". Step 3 raised the non-directory error naming `blocker`. Step 4 raised "symlink to a missing target at …/dangling"; `missing` absent. Step 5 raised "symlink to a missing target at …/linkdir/<id>.md"; `elsewhere` absent.

## Backup copy before replacing a doc's content — `write_doc_content` / `update_doc_from_file` (#878)

### TC-DOC219: A replace backs the doc up first, removes the backup on success, and names it on failure ⚠️ destructive
Before #878, a replace that failed after the clear left the doc empty, and the error didn't say so. Now a doc with content is copied with Drive before the clear (`"<title> (backup before replace)"`, next to the doc). The copy is removed on success and kept and named as `backupId` on failure. No tool call can make the content write fail after a successful clear, so part B injects the failure from a scratch script against the checkout under test. Design: `docs/design/doc-replace-backup.md`.

Run it on a server whose account can own a copy of `{DOC_ID}`: OAuth, or a service account when `{DOC_ID}` is on a Shared Drive. A service account writing into a My Drive doc gets `storageQuotaExceeded` on the copy, so it replaces without a backup by design (#1018 widened this to a few other copy failures; TC-DOC224). Step 1 then returns a "replaced without a backup copy" `warning`, and step 4 reports "couldn't be backed up" instead of a `backupId`.

**Setup:** `write_doc_content(doc_id={DOC_ID}, content="<p>TC-DOC219 before</p>")`. Note the doc's `name` from `get_file_metadata(file_id={DOC_ID})`.

**Steps (part A, tool calls)**
1. `write_doc_content(doc_id={DOC_ID}, content="<h1>TC-DOC219 after</h1><p>Replaced.</p>")`
2. `search_files(query="<name> (backup before replace)")` (the name noted in Setup)
3. `get_doc_content(file_id={DOC_ID})`

**Steps (part B, scratch script from the checkout under test, same OAuth token as the server under test)**

4. Run, with `{DOC_ID}` filled in:
```
uv run python3 -c "
import asyncio, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
creds = auth._oauth_creds()
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=creds),
    drive_service=build('drive', 'v3', credentials=creds), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
with patch.object(c, 'fill_tables', side_effect=RuntimeError('injected failure')):
    print(asyncio.run(c._replace_doc_content(lc, '{DOC_ID}', '<p>TC-DOC219 failed write</p>', 'html',
        autolink_urls=True, revoke_sharing=True, auto_downscale=False, allow_no_backup=False)))
"
```
5. `get_doc_content(file_id={BACKUP_ID})`, where `{BACKUP_ID}` is step 4's `backupId`. Part B's mock `doc_cache` leaves the server's cache stale, so call `refresh_cache(doc_id={DOC_ID})` before reading `{DOC_ID}` again.

**Steps (part C, a 503 returned after the request already ran, PR #1017 QA round 1)**

6. Restore some content first: `write_doc_content(doc_id={DOC_ID}, content="<p>TC-DOC219 before C</p>")`. Then run the script below with `MATCH=':batchUpdate'` (the clear), then `refresh_cache(doc_id={DOC_ID})` and `get_doc_content(file_id={DOC_ID})`, then `get_doc_content(file_id=<its backupId>)`.
7. `write_doc_content(doc_id={DOC_ID}, content="<p>TC-DOC219 before C2</p>")`, then run the script with `MATCH='/copy'` (the backup copy), then `refresh_cache(doc_id={DOC_ID})`, `get_doc_content(file_id={DOC_ID})`, and `search_files(query="<name> (backup before replace)")`.
```
MATCH=':batchUpdate' uv run python3 -c "
import asyncio, os, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
creds = auth._oauth_creds()
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=creds),
    drive_service=build('drive', 'v3', credentials=creds), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
real = c.execute_in_thread
async def after_commit(fn, service):
    result = await real(fn, service)
    if os.environ['MATCH'] in getattr(getattr(fn, '__self__', None), 'uri', ''):
        raise HttpError(resp=MagicMock(status=503), content=b'{}')
    return result
with patch.object(c, 'execute_in_thread', after_commit):
    print(asyncio.run(c._replace_doc_content(lc, '{DOC_ID}', '<p>TC-DOC219 part C</p>', 'html',
        autolink_urls=True, revoke_sharing=True, auto_downscale=False, allow_no_backup=False)))
"
```

**Checks**
- Step 1 returns `docId` and `web_link`, with no `error`, `backupId`, or `warning`
- Step 2 finds no file: the backup was removed (deleted, or trashed on a Shared Drive where the account can't delete, #876)
- Step 3 shows "TC-DOC219 after" and "Replaced.", and no "TC-DOC219 before"
- Step 4 prints `{"error": "doc edit failed: injected failure. The document's previous content was cleared first; a full copy of it is kept as '<name> (backup before replace)' (backupId).", "docId": "{DOC_ID}", "backupId": "..."}`
- Step 5 shows "TC-DOC219 after" and "Replaced.", the content from before step 4's failed write
- Step 6's script prints an error containing "may have been cleared" and a `backupId`. `{DOC_ID}` reads empty, and the `backupId` doc shows "TC-DOC219 before C": the backup was kept, not deleted
- Step 7's script prints "Couldn't back up the document before replacing its content, so it was left unchanged" ending in "A copy named '<name> (backup before replace)' may still have been created next to the document; check for it and delete it". `{DOC_ID}` still shows "TC-DOC219 before C2", and `search_files` finds that copy

**Cleanup:** `delete_file` on `{BACKUP_ID}`, step 6's `backupId`, and the copy step 7's `search_files` found, then write fixture content back over `{DOC_ID}`

**Result (2026-10-12) ❌ FAIL — Sky, PR #1017 round 1 (`94b1ddd`).** Ran on a scratch doc on the QA Shared Drive (OAuth), not the shared fixture doc, and part B used the script with the server's env loaded from this slot's MCP config. Part A passed: step 1 returned `docId`/`web_link` only; step 2 found no backup; step 3 showed the new content. Part B passed: step 4 printed the expected error with a `backupId`, step 5 showed the pre-failure content, and the same `search_files` query from step 2 found that kept backup (a positive control for step 2). The case fails on two extra probes run with the same script, `execute_in_thread` patched to raise `HttpError` 503 after the real call had already gone through. (a) On the clear: it returned "Couldn't clear the document, so it was left unchanged" and removed the backup, but a fresh `get_doc_content` (after `refresh_cache`) showed the doc empty: data loss (review finding 1). (b) On the `files.copy`: it returned "Couldn't back up… left unchanged" with no file ID, while a `(backup before replace)` copy now existed next to the doc (finding 5). `update_doc_from_file` replace on the same doc: new content written, no backup left behind. Note: part B's mock `doc_cache` leaves the server's cache stale, so call `refresh_cache(doc_id=…)` before step 5-style reads of `{DOC_ID}`. Cleanup done: the scratch doc and both kept copies were trashed.

**Result (2026-10-13) ✅ PASS — Sky, PR #1017 round 2 (`e6f0902`).** Ran on a fresh scratch doc on the QA Shared Drive (OAuth). The scripts loaded the server's env from this slot's MCP config. Part A: step 1 returned `docId`/`web_link` only, step 2 found no backup, step 3 showed the new content. Part B: step 4 printed the expected "cleared first" error with a `backupId`, and step 5 showed "TC-DOC219 after / Replaced.". Part C step 6 (503 after the clear landed): "…may have been cleared; a full copy of it is kept…" with a `backupId`. After `refresh_cache`, `{DOC_ID}` read empty and the backup showed "TC-DOC219 before C". Step 7 (503 after the copy landed): "…left unchanged… A copy named '<name> (backup before replace)' may still have been created next to the document; check for it and delete it". `{DOC_ID}` still showed "TC-DOC219 before C2", and `search_files` found the copy. The 503 text in steps 6–7 shows the script's `MagicMock` reason, a script artifact. Extra probe: `_BACKUP_COPY_TIMEOUT` patched to 3 s, with the copy's worker thread blocking 15 s after the real copy. The coroutine returned after 3.7 s with "…left unchanged: TimeoutError. A copy named … may still have been created…", so the bound cancels the wait on the thread. `asyncio.run` still waited for the thread at exit, which is expected in a script. Each timeout run left the copy it warned about. Cleanup done: the scratch doc and all five copies were trashed.

**Result (2026-10-13) ✅ PASS — Sky, PR #1017 round 3 (`b78faab`).** Re-verification of the round-2 cache fix. Part A ran on a fresh scratch doc on the QA Shared Drive (OAuth), with the cache warmed by a `get_doc_content` before step 1 and no `refresh_cache` before step 3. Step 1 returned `docId`/`web_link` only, step 2 found no backup, and step 3 showed "TC-DOC219 after / Replaced.", so the write invalidated the cached pre-write content. Parts B and C weren't re-run: the fix only moves `mark_dirty` on the success path, and both parts passed in round 2. The lookup-failure path is covered by the new unit assertion. Cleanup done: the scratch doc was trashed.

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
Part A passes; parts B and C need the OAuth scratch script.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`jay`: Part A passed: step 1 returned only `docId`/`web_link`; `search_files("QA-v0.9.3-C-doc (backup before replace)")` found nothing (no positive control was run); the content is "TC-DOC219 after / Replaced.". Parts B and C need the token scratch script; not run.

### TC-DOC224: A caller who can edit the doc but can't add to its folder replaces it without a backup, and is told so (#1018) ⚠️ destructive ⚠️ requires-oauth
#878's backup copy has no `parents`, so it goes into the doc's folder. A caller who can edit the doc but only read or comment on that folder gets 403 `insufficientFilePermissions` on the copy. That caller could write the doc before #878, so the replace now goes ahead without a backup and says so (`docs/design/doc-replace-backup.md`, "The copy fails"). Two identities are needed: the OAuth account owns the fixture, and the service account is the caller. The case runs as a scratch script from the checkout under test, with no MCP server involved, so it needs both `token.json` and service-account credentials in `src/mcp_gee_sweet/.env`. The fixture is a fresh My Drive folder, not `{DOC_ID}`, since the service account needs exactly reader access on the folder and writer access on the doc.

**Setup:** none. The script creates and deletes its own fixture.

**Steps**
1. Run from the checkout under test:
```
uv run python -I -c "
import asyncio, json, time, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
oauth, sa = auth._oauth_creds(), auth._service_account_creds()
od, odocs = build('drive', 'v3', credentials=oauth), build('docs', 'v1', credentials=oauth)
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=sa),
    drive_service=build('drive', 'v3', credentials=sa), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
def text(d):
    b = odocs.documents().get(documentId=d).execute()['body']['content']
    return ''.join(r.get('textRun', {}).get('content', '') for e in b for r in e.get('paragraph', {}).get('elements', [])).strip()
def run(d, html):
    return asyncio.run(c._replace_doc_content(lc, d, html, 'html', autolink_urls=True, revoke_sharing=True, auto_downscale=False, allow_no_backup=False))
folder = od.files().create(body={'name': 'TC-DOC224 folder', 'mimeType': 'application/vnd.google-apps.folder'}, fields='id').execute()['id']
try:
    doc = od.files().create(body={'name': 'TC-DOC224 doc', 'mimeType': 'application/vnd.google-apps.document', 'parents': [folder]}, fields='id').execute()['id']
    odocs.documents().batchUpdate(documentId=doc, body={'requests': [{'insertText': {'location': {'index': 1}, 'text': 'TC-DOC224 before\n'}}]}).execute()
    for fid, role in ((folder, 'reader'), (doc, 'writer')):
        od.permissions().create(fileId=fid, body={'type': 'user', 'role': role, 'emailAddress': sa.service_account_email}, sendNotificationEmail=False).execute()
    time.sleep(3)
    print('A', json.dumps({k: v for k, v in run(doc, '<p>TC-DOC224 after</p>').items() if k != 'docId'}), repr(text(doc)))
    with patch.object(c, 'fill_tables', side_effect=RuntimeError('injected failure')):
        print('B', json.dumps({k: v for k, v in run(doc, '<p>TC-DOC224 failed</p>').items() if k != 'docId'}))
    print('C', [f['name'] for f in od.files().list(q=f\"'{folder}' in parents and trashed=false\", fields='files(name)').execute()['files']])
finally:
    od.files().delete(fileId=folder).execute()
    print('cleanup done')
"
```

**Checks**
- Line `A` has `web_link` and `warning` "The document's previous content was replaced without a backup copy (this account can't add a file to the document's folder).", with no `error` or `backupId`. Its doc text is `'TC-DOC224 after'`
- Line `B`'s `error` is "doc edit failed: injected failure. The document's previous content was cleared first and couldn't be backed up (this account can't add a file to the document's folder), so the document may be empty or partly written.", with no `backupId`
- Line `C` lists only `TC-DOC224 doc`: no `(backup before replace)` copy was made
- The log shows `Replacing doc … without a backup: this account can't add a file to the document's folder` before each of `A` and `B`
- `cleanup done` is printed

**Cleanup:** the script deletes the folder, and the doc with it. If it stopped before `cleanup done`, `search_files(query="TC-DOC224")` on the OAuth server and delete what it finds.

**Result (2026-10-14) ✅ PASS — Sky, PR #1034 round 1 (`454001d`).** Ran the script as written from this slot's checkout, with this slot's OAuth token and the shared service-account key passed by env var. Line `A` had `web_link` and the expected `warning`, with doc text `'TC-DOC224 after'`. Line `B` had the expected "cleared first and couldn't be backed up (this account can't add a file to the document's folder)" error and no `backupId`. Line `C` listed only `TC-DOC224 doc`. Before each of `A` and `B`, the log showed googleapiclient's `403 … "insufficientFilePermissions"` and then `Replacing doc … without a backup: this account can't add a file to the document's folder`. `cleanup done` was printed. Extra probe: the service account was given writer access on both the doc and a My Drive folder, and the copy returned `storageQuotaExceeded`, as the design doc says. After the owner set `downloadRestrictions.itemDownloadRestriction.restrictedForWriters`, the same copy returned 403 `cannotCopyFile` (with or without `parents`). That reason isn't in `_no_backup_reason`, so such a writer is still refused.

**Result (2026-10-14) ✅ PASS — Sky, PR #1034 round 2 (`ca210a4`).** Re-ran the script as written, and every check held, with the same `A`/`B`/`C` output and log lines as round 1. Extra probe for the round-1 fix: the same fixture, with `execute_in_thread` patched so that only the `webViewLink` lookup raises `ConnectionError`. The replace raised `RuntimeError` "The document's previous content was replaced without a backup copy (this account can't add a file to the document's folder). The new content was written, but looking up the document's link failed: injected lookup failure", with the `ConnectionError` as `__cause__`. The doc read `'TC-DOC224 lookup after'`, and the folder held no backup copy. `numChildrenInNonRootLimitExceeded` can't be produced live (a 500k-item folder), so it's unit-tested only. Cleanup done.

**Result (2026-10-14) ✅ PASS — Kit, PR #1029 round 4 (`d748932`).** Re-ran after `develop` (#1034) was merged into PR #1029, whose `ImageShareLifecycle` now runs inside `_replace_doc_content`. The script ran as written (its `\"` escapes undone for a file) from the kit checkout, with this slot's OAuth token and service-account key passed by env var. Lines `A`, `B` and `C`, both `Replacing doc … without a backup` log lines (each after a 403 `insufficientFilePermissions`), and `cleanup done` all matched the checks.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
The scratch script needs a usable OAuth token (see DOC80).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`jay`: Needs the fixture-owning account's token and service-account credentials in a scratch script; not available in this pass.

## Image-share lifecycle: cancellation and cache follow-ups (#909)

`_apply_doc_content` (behind `create_doc`, `create_doc_from_file`, `write_doc_content`, `update_doc_from_file`) and `insert_local_images` now share one temporary-image-share lifecycle, `images.ImageShareLifecycle` (#908). Before this, `_apply_doc_content` sent its content `batchUpdate` even when the call was cancelled during the shielded image gather (#904), and logged nothing when a cancellation arrived during its success-path revoke (#908). Both tools' cancel paths invalidated the doc cache before an in-flight edit landed, or not at all (#907). And `write_doc_content` and a resized `drive:` copy never marked the folder they uploaded into as dirty (#666). TC-DOC203 covers `insert_local_images` on the same lifecycle and should be re-run alongside these.

### TC-DOC222: A cancelled `write_doc_content` never sends its edit after a cancel during the share, logs a cancel during the revoke, and re-invalidates the cache once an in-flight edit lands (#904, #907, #908) ⚠️ requires-oauth ⚠️ destructive ⚠️ local-filesystem

**Background:** Same mechanism as TC-DOC203: `scripts/qa_cancel_insert_local_images.py` runs the checkout's own tool against the real APIs and cancels it at one point. `--tool write_doc_content` routes the call through `_replace_doc_content`/`_apply_doc_content` (its MARKER argument is ignored; `-` below). The script prints every doc-cache invalidation as `doc cache marked dirty for <id> (edit landed: yes|no)`, then waits for an in-flight edit to finish. Run it from the checkout under test with that checkout's OAuth token (`TOKEN_PATH`). It prints the tool's WARNINGs to stderr. On an empty doc `write_doc_content` sends no clear and makes no backup copy, so its first `batchUpdate` is the content one.

**Setup:**
1. `create_doc(title="TC-DOC222", folder_id={FOLDER_ID})` with no content. Record `docId` as `{DOC_ID}`.
2. `create_doc(title="TC-DOC222 inflight", folder_id={FOLDER_ID})` with no content. Record `docId` as `{INFLIGHT_DOC_ID}`.
3. `create_doc(title="TC-DOC222 markers", content="Before\n\nINFLIGHT909\n\nAfter", content_format="markdown", folder_id={FOLDER_ID})`. Record `docId` as `{MARKER_DOC_ID}`.

**Prompt**
> (none — script-driven; the steps below are shell commands plus tool calls)

**Steps** (`<pixel>` is `<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png`)
1. `uv run python scripts/qa_cancel_insert_local_images.py {DOC_ID} {FOLDER_ID} <pixel> - share --tool write_doc_content`. Record the file ID from the WARNING as `{SHARE_FILE_ID}`.
2. The same command with `revoke` in place of `share`. Record the WARNING's file ID as `{REVOKE_FILE_ID}`.
3. `uv run python scripts/qa_cancel_insert_local_images.py {INFLIGHT_DOC_ID} {FOLDER_ID} <pixel> - inflight --tool write_doc_content`. Record the WARNING's file ID as `{INFLIGHT_FILE_ID}`.
4. `uv run python scripts/qa_cancel_insert_local_images.py {MARKER_DOC_ID} {FOLDER_ID} <pixel> INFLIGHT909 inflight` (default tool, `insert_local_images`). Record the WARNING's file ID as `{ILI_FILE_ID}`.
5. Step 1's command again, with `inflight` in place of `share`. `{DOC_ID}` has content since step 2, so this cancels during the *clear* `batchUpdate`, before any image work. Record the backup copy's ID from its WARNING as `{BACKUP_ID}`.

**Checks**
- Steps 1–4 each print `cancelled at '<point>'; the tool returned nothing` and a WARNING `Doc edit for <doc> failed or was cancelled after its images were resolved; files created by this call: <one file ID>; pre-existing files: none; still link-shared by this call: none`. Before #908, step 2 logged nothing
- Step 1 prints `batchUpdates sent: 0; landed: 0`. Before #904, the content `batchUpdate` was still sent after the cancellation
- Steps 3, 4 and 5 each print a `doc cache marked dirty for <doc> (edit landed: no)` line from the cancel path, then a later `doc cache marked dirty for <doc> (edit landed: yes)` line, and end with `batchUpdates sent: 1; landed: 1`. Before #907, the `(edit landed: yes)` line was missing. If a run shows only `(edit landed: yes)` lines, the edit finished before the cancel reached the tool; re-run that step on a fresh doc
- Step 5 logs `Replacing doc {DOC_ID} was cancelled; kept its backup copy {BACKUP_ID}` and no image WARNING (no image was uploaded)
- `list_permissions` on `{SHARE_FILE_ID}`, `{REVOKE_FILE_ID}`, `{INFLIGHT_FILE_ID}`, and `{ILI_FILE_ID}` shows no `anyone` permission
- After `refresh_cache` on each doc, `get_doc_as_markdown` shows: `{INFLIGHT_DOC_ID}` with `Before`, an image, `After` (the in-flight edit landed); `{MARKER_DOC_ID}` with an image where `INFLIGHT909` was; `{DOC_ID}` empty (step 5's clear landed); `{BACKUP_ID}` with `Before`, an image, `After` (step 2's content)

**Cleanup:** trash `{SHARE_FILE_ID}`, `{REVOKE_FILE_ID}`, `{INFLIGHT_FILE_ID}`, `{ILI_FILE_ID}`, `{BACKUP_ID}`, `{DOC_ID}`, `{INFLIGHT_DOC_ID}`, and `{MARKER_DOC_ID}`.

**Result (2026-10-14) ✅ PASS (checks as written); ❌ sent back on a probe — Kit, PR #1029 round 1 (`089f6ee`).** Ran from the kit worktree with its OAuth token, docs in a scratch folder on the QA Shared Drive, the fixture pixel from this checkout. Steps 1–4 each printed the cancel line and the WARNING with `still link-shared by this call: none`. Step 1 printed `batchUpdates sent: 0; landed: 0`. Steps 3, 4 and 5 each printed `(edit landed: no)` line(s) from the cancel path (step 3 two: the lifecycle's and `_replace_doc_content`'s `_failed`), then `(edit landed: yes)`, and ended `sent: 1; landed: 1`. Step 5 logged `Replacing doc {DOC_ID} was cancelled; kept its backup copy {BACKUP_ID}` and no image WARNING. `list_permissions` showed no `anyone` grant on the four files. `get_doc_as_markdown`: `{INFLIGHT_DOC_ID}` `Before`/image/`After`; `{MARKER_DOC_ID}` an image where `INFLIGHT909` was; `{DOC_ID}` empty; `{BACKUP_ID}` `Before`/image/`After`. **Probe (failed):** step 2's command (`revoke`) on a doc that already had content, so a backup was made: two batchUpdates (clear + content) landed and the doc read `Before`/image/`After`, yet the call also logged `Replacing doc … was cancelled; kept its backup copy …`, and that copy was left in Drive for a replace that had fully succeeded. The lifecycle's new post-revoke checkpoint routes the cancel through `_failed` instead of after `_discard_backup` (review finding 2). Cleanup done.

**Result (2026-10-14) ✅ PASS (partial re-run) — Kit, PR #1029 round 2 (`fd591d9`).** Re-ran step 3 and step 5 on fresh scratch docs; both matched round 1 (step 3: `(edit landed: no)` lines, then `(edit landed: yes)`, `sent: 1; landed: 1`, the doc `Before`/image/`After`; step 5: `kept its backup copy` logged, the backup held the old content). Round 1's failed probe (`revoke` on a doc with content) now passes: both batchUpdates landed, the doc read `Before`/image/`After`, no `kept its backup copy` line was logged, and after `refresh_cache` the folder held no `(backup before replace)` copy of that doc. Cleanup done.

**Result (2026-10-14) ✅ PASS (probe only) — Kit, PR #1029 round 3 (`2311322`).** Steps not re-run; the round's fix only touches `create_doc`/`create_doc_from_file`'s Drive create. A scratch script (not committed) ran the checkout's `create_doc` against the real APIs with a mock folder cache and cancelled it while `files().create` ran on its worker thread. The tool returned nothing, the create landed afterward (the Doc was in the folder), and the folder was marked dirty once it landed. An uncancelled `create_doc` in the same folder marked it dirty as before. Cleanup done.

**Result (2026-10-15) ✅ PASS — Kit, PR #1029 round 4 (`d748932`).** Full re-run after the `develop` merge brought #1034's no-backup changes into `_replace_doc_content`. Ran from the kit worktree with its OAuth token, docs in a scratch folder on the QA Shared Drive. Steps 1–4 each printed the cancel line and the WARNING with `still link-shared by this call: none`. Step 1 printed `batchUpdates sent: 0; landed: 0`. Steps 3, 4 and 5 printed `(edit landed: no)` line(s) from the cancel path (step 3 two), then `(edit landed: yes)`, and ended `sent: 1; landed: 1`. Step 5 logged `Replacing doc {DOC_ID} was cancelled; kept its backup copy {BACKUP_ID}` and no image WARNING. `list_permissions` showed no `anyone` grant on the four files. `get_doc_as_markdown`: `{INFLIGHT_DOC_ID}` `Before`/image/`After`; `{MARKER_DOC_ID}` an image where `INFLIGHT909` was; `{DOC_ID}` empty; `{BACKUP_ID}` `Before`/image/`After`. Round 1's probe (`revoke` on a doc that already had content, so a backup was made) passed again: `sent: 2; landed: 2`, the doc read `Before`/image/`After`, no `kept its backup copy` line was logged, and the folder held no `(backup before replace)` copy of that doc. Cleanup done.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
The scratch script needs a usable OAuth token (see DOC80).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`jay`: Needs the fixture-owning account's token in a scratch script (cancel script); not available in this pass.

---

### TC-DOC223: An image upload or resized copy shows up in a cached folder listing without `refresh_cache`, and a failed edit still names its resized copy (#666) ⚠️ requires-oauth ⚠️ destructive ⚠️ local-filesystem

**Background:** `list_files` caches each folder's listing. `create_doc` marked its target folder dirty, but `write_doc_content` (which uploads a local image into the server's default folder) never did. A `drive:` source's or `drive_file_id`'s resized copy lands next to its original, which no tool marked dirty either. Every upload result now names the folder its file was created in, and the shared image lifecycle (or `insert_inline_image`) marks that folder dirty. The case reads each listing once to cache it, and never calls `refresh_cache`.

**Setup:**
1. `uv run python3 -c "from PIL import Image; Image.new('RGB', (6000, 6000), 'red').save('/tmp/qa-oversized-909.png')"`
2. `create_folder(name="TC-DOC223 originals", parent_folder_id={FOLDER_ID})`. Record its ID as `{ORIG_FOLDER_ID}`.
3. `upload_local_file(local_path="/tmp/qa-oversized-909.png", parent_folder_id={ORIG_FOLDER_ID})`. Record the returned `fileId` as `{OVERSIZED_FILE_ID}`.
4. `create_doc(title="TC-DOC223", content="Start", folder_id={FOLDER_ID})`. Record `docId` as `{DOC_ID}`.
5. Read the server's default folder from its config (`DRIVE_FOLDER_ID`) as `{DEFAULT_FOLDER_ID}`. If it isn't set, skip steps 3–4 below and their check: `write_doc_content` can't upload a local image without one.

**Steps**
1. `list_files(folder_id={ORIG_FOLDER_ID})`, to cache the listing. It shows only `qa-oversized-909.png`.
2. `insert_inline_image(doc_id={DOC_ID}, index=1, drive_file_id={OVERSIZED_FILE_ID}, auto_downscale=True)`. Record `resized_file_id`. Then `list_files(folder_id={ORIG_FOLDER_ID})` again.
3. `list_files(folder_id={DEFAULT_FOLDER_ID}, mime_type="image/png")`, to cache the listing.
4. `write_doc_content(doc_id={DOC_ID}, content="![Pixel](<repo-root>/docs/qa/fixtures/qa-fixture-pixel.png)", content_format="markdown")`. Record `images[0].fileId` as `{PIXEL_FILE_ID}`. Then `list_files(folder_id={DEFAULT_FOLDER_ID}, mime_type="image/png")` again.
5. Lock `{DOC_ID}` read-only with TC-DOC202's setup step 3 script (doc ID `{DOC_ID}`, reason `TC-DOC223`). Then `insert_inline_image(doc_id={DOC_ID}, index=1, drive_file_id={OVERSIZED_FILE_ID}, auto_downscale=True)` again.

**Checks**
- Step 2's second listing includes `qa-oversized-909.png (resized)` with ID `resized_file_id`. Before the fix it showed only the original until `refresh_cache`
- Step 4's second listing includes `{PIXEL_FILE_ID}` (`qa-fixture-pixel.png`). Before the fix it was missing until `refresh_cache`
- Step 5 returns `{"error": ...}` with the Docs `batchUpdate`'s 403 "The caller does not have permission", plus a `resized_file_id` different from step 2's. That copy exists and is link-shared even though nothing was embedded; before the fix the error result didn't name it

**Cleanup:** unlock `{DOC_ID}` with the same script, using `body={'contentRestrictions': [{'readOnly': False}]}`. Trash both steps' `resized_file_id`, `{OVERSIZED_FILE_ID}`, `{ORIG_FOLDER_ID}`, `{PIXEL_FILE_ID}`, and `{DOC_ID}`. `rm /tmp/qa-oversized-909.png`

**Result (2026-10-14) ✅ PASS — Kit, PR #1029 round 1 (`089f6ee`).** Ran in a scratch folder on the QA Shared Drive; the oversized PNG went under this job's scratch dir instead of `/tmp`, and `{DEFAULT_FOLDER_ID}` is the Shared Drive root (`DRIVE_FOLDER_ID`). Step 1's listing showed only `qa-oversized-909.png`; step 2's second listing added `qa-oversized-909.png (resized)` with ID `resized_file_id`. Step 3's listing was empty; step 4's second listing showed `{PIXEL_FILE_ID}` (`qa-fixture-pixel.png`). No `refresh_cache` anywhere. Step 5 returned the 403 "The caller does not have permission" error plus a new `resized_file_id`, different from step 2's. Cleanup done.

**Result (2026-10-17) 🟡 PARTIAL — v0.9.2 release pass**
Steps 3–4 pass; steps 1–2 and 5 need an anyone share or the lock script.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`jay`: Steps 1–2: after caching the originals listing, `insert_inline_image(auto_downscale)` made `qa-oversized-909.png (resized)`, and it showed in the second listing with no `refresh_cache`. Steps 3–4: the default folder is the Shared Drive root (found from a probe upload's parents, which I then trashed). The cached png listing was empty; after `write_doc_content` with the pixel, the second listing showed its `fileId`, with no `refresh_cache`. Step 5 needs the lock script; not run. Artifacts trashed.

### TC-DOC225: A writer whose sharing settings block copying is refused by default, and replaces without a backup with `allow_no_backup=True` (#1035) ⚠️ destructive ⚠️ requires-oauth
When `downloadRestrictions.itemDownloadRestriction.restrictedForWriters` is set on a doc, a writer's backup copy gets 403 `cannotCopyFile` (measured live, 2026-10-14). Unlike #1018's reasons (TC-DOC224), this one refuses by default and replaces without a backup only when the caller passes `allow_no_backup=True` (`docs/design/doc-replace-backup.md`, "The copy fails"). The same writer also gets 403 `cannotExportFile` on an export, so no other kind of backup is possible either. Same two-identity setup as TC-DOC224: the OAuth account owns the fixture, and the service account is the caller. The script runs from the checkout under test with no MCP server involved, so it needs both `token.json` and service-account credentials in `src/mcp_gee_sweet/.env`. Here the service account is a writer on both the folder and the doc, so the folder permission isn't what stops the copy.

**Setup:** none. The script creates and deletes its own fixture.

**Steps**
1. Run from the checkout under test:
```
uv run python -I -c "
import asyncio, json, time, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
oauth, sa = auth._oauth_creds(), auth._service_account_creds()
od, odocs = build('drive', 'v3', credentials=oauth), build('docs', 'v1', credentials=oauth)
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=sa),
    drive_service=build('drive', 'v3', credentials=sa), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
def text(d):
    b = odocs.documents().get(documentId=d).execute()['body']['content']
    return ''.join(r.get('textRun', {}).get('content', '') for e in b for r in e.get('paragraph', {}).get('elements', [])).strip()
def run(d, html, allow):
    return asyncio.run(c._replace_doc_content(lc, d, html, 'html', autolink_urls=True, revoke_sharing=True, auto_downscale=False, allow_no_backup=allow))
folder = od.files().create(body={'name': 'TC-DOC225 folder', 'mimeType': 'application/vnd.google-apps.folder'}, fields='id').execute()['id']
try:
    doc = od.files().create(body={'name': 'TC-DOC225 doc', 'mimeType': 'application/vnd.google-apps.document', 'parents': [folder]}, fields='id').execute()['id']
    odocs.documents().batchUpdate(documentId=doc, body={'requests': [{'insertText': {'location': {'index': 1}, 'text': 'TC-DOC225 before\n'}}]}).execute()
    for fid in (folder, doc):
        od.permissions().create(fileId=fid, body={'type': 'user', 'role': 'writer', 'emailAddress': sa.service_account_email}, sendNotificationEmail=False).execute()
    od.files().update(fileId=doc, body={'downloadRestrictions': {'itemDownloadRestriction': {'restrictedForWriters': True}}}).execute()
    time.sleep(5)
    print('A', json.dumps({k: v for k, v in run(doc, '<p>TC-DOC225 refused</p>', False).items() if k != 'docId'}), repr(text(doc)))
    print('B', json.dumps({k: v for k, v in run(doc, '<p>TC-DOC225 after</p>', True).items() if k != 'docId'}), repr(text(doc)))
    print('C', [f['name'] for f in od.files().list(q=f\"'{folder}' in parents and trashed=false\", fields='files(name)').execute()['files']])
finally:
    od.files().delete(fileId=folder).execute()
    print('cleanup done')
"
```

**Checks**
- Line `A`'s `error` is "Couldn't back up the document before replacing its content (the document's sharing settings don't allow this account to copy it), so it was left unchanged. To replace it without a backup, retry with allow_no_backup=True. Its previous content then can't be recovered with export_revision: Docs merges the revision from before the replace into the replace's own.", with no `backupId`. Its doc text is still `'TC-DOC225 before'`
- Line `B` has `web_link` and `warning` "The document's previous content was replaced without a backup copy (the document's sharing settings don't allow this account to copy it).", with no `error` or `backupId`. Its doc text is `'TC-DOC225 after'`
- Line `C` lists only `TC-DOC225 doc`: no `(backup before replace)` copy was made
- The log shows googleapiclient's `403 … "cannotCopyFile"` before each of `A` and `B`, and `Replacing doc … without a backup: the document's sharing settings don't allow this account to copy it` before `B` only
- `cleanup done` is printed

**Cleanup:** the script deletes the folder, and the doc with it. If it stopped before `cleanup done`, `search_files(query="TC-DOC225")` on the OAuth server and delete what it finds.

**Result (2026-10-16) ✅ PASS — Sky, PR #1042 round 1 (`4ba422c`).** Ran the script as written from this worktree. Line `A` returned the expected refusal with no `backupId`, and the doc text stayed `'TC-DOC225 before'`. Line `B` returned `web_link` and the expected `warning` with no `error` or `backupId`, and the doc text became `'TC-DOC225 after'`. Line `C` listed only `TC-DOC225 doc`. The log showed `403 … "cannotCopyFile"` before `A` and before `B`, and `Replacing doc … without a backup: the document's owner doesn't allow this account to copy it` before `B` only. `cleanup done` was printed. The case passes, but two extra probes in the same round found the refusal text wrong for callers this case doesn't cover. (1) A *reader* on a doc with `copyRequiresWriterPermission` also gets 403 `cannotCopyFile` (`capabilities.canCopy`/`canEdit` both false). It is told to retry with `allow_no_backup=True`, and that retry logs "Replacing … without a backup" and then fails at the clear with 403. (2) A writer on a Shared Drive doc with `restrictedForWriters` (the file has no `owners`) gets the same "the document's owner" wording. Both were sent back on the PR.

**Result (2026-10-16) ✅ PASS — Sky, PR #1042 round 2 (`9323a1b`).** Ran the script as written from this worktree. Lines `A`, `B`, and `C` matched every check with the new "the document's sharing settings don't allow this account to copy it" wording, and so did the log lines. `cleanup done` was printed. The round-1 Shared Drive probe, re-run in the QA Shared Drive (service account as Content manager, `restrictedForWriters` set, `canEdit: true`), now gets the same sharing-settings refusal without naming an owner.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
The scratch script needs a usable OAuth token (see DOC80).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`jay`: Needs the fixture-owning account's token and service-account credentials in a scratch script; not available in this pass.

### TC-DOC226: A reader blocked from copying is told it can't edit the doc, with or without `allow_no_backup` (#1035) ⚠️ destructive ⚠️ requires-oauth
With `copyRequiresWriterPermission` set, a caller with only reader access also gets 403 `cannotCopyFile` on the backup copy. `allow_no_backup=True` can't help it, since the clear would fail, so after that copy failure the doc's `capabilities.canEdit` is read. When it's false, the call refuses with an error saying the account can't edit the doc, whatever the flag says (`docs/design/doc-replace-backup.md`, "The copy fails"; PR #1042 QA round 1). Before the fix, the default call said to retry with `allow_no_backup=True`, and that retry logged `Replacing doc … without a backup` and then failed at the clear with a 403. Same two-identity setup as TC-DOC225: the OAuth account owns the fixture, and the service account is the caller, here with reader access on the doc only.

**Setup:** none. The script creates and deletes its own fixture.

**Steps**
1. Run from the checkout under test:
```
uv run python -I -c "
import asyncio, json, time, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
oauth, sa = auth._oauth_creds(), auth._service_account_creds()
od, odocs = build('drive', 'v3', credentials=oauth), build('docs', 'v1', credentials=oauth)
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=sa),
    drive_service=build('drive', 'v3', credentials=sa), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
def text(d):
    b = odocs.documents().get(documentId=d).execute()['body']['content']
    return ''.join(r.get('textRun', {}).get('content', '') for e in b for r in e.get('paragraph', {}).get('elements', [])).strip()
def run(d, html, allow):
    return asyncio.run(c._replace_doc_content(lc, d, html, 'html', autolink_urls=True, revoke_sharing=True, auto_downscale=False, allow_no_backup=allow))
folder = od.files().create(body={'name': 'TC-DOC226 folder', 'mimeType': 'application/vnd.google-apps.folder'}, fields='id').execute()['id']
try:
    doc = od.files().create(body={'name': 'TC-DOC226 doc', 'mimeType': 'application/vnd.google-apps.document', 'parents': [folder]}, fields='id').execute()['id']
    odocs.documents().batchUpdate(documentId=doc, body={'requests': [{'insertText': {'location': {'index': 1}, 'text': 'TC-DOC226 before\n'}}]}).execute()
    od.permissions().create(fileId=doc, body={'type': 'user', 'role': 'reader', 'emailAddress': sa.service_account_email}, sendNotificationEmail=False).execute()
    od.files().update(fileId=doc, body={'copyRequiresWriterPermission': True}).execute()
    time.sleep(5)
    print('A', json.dumps({k: v for k, v in run(doc, '<p>TC-DOC226 default</p>', False).items() if k != 'docId'}), repr(text(doc)))
    print('B', json.dumps({k: v for k, v in run(doc, '<p>TC-DOC226 flag</p>', True).items() if k != 'docId'}), repr(text(doc)))
finally:
    od.files().delete(fileId=folder).execute()
    print('cleanup done')
"
```

**Checks**
- Lines `A` and `B` each have exactly one key, `error`: "This account can't edit the document, so it was left unchanged (Drive also refused the backup copy: the document's sharing settings don't allow this account to copy it)." Neither mentions `allow_no_backup`. Each line's doc text is still `'TC-DOC226 before'`
- The log shows googleapiclient's `403 … "cannotCopyFile"` before each of `A` and `B`, and no `Replacing doc … without a backup` line anywhere
- `cleanup done` is printed

**Cleanup:** the script deletes the folder, and the doc with it. If it stopped before `cleanup done`, `search_files(query="TC-DOC226")` on the OAuth server and delete what it finds.

**Result (2026-10-16) ✅ PASS — Sky, PR #1042 round 2 (`9323a1b`).** Ran the script as written from this worktree. Lines `A` and `B` each had only `error`, with the expected "This account can't edit the document …" text and no mention of `allow_no_backup`. The doc text stayed `'TC-DOC226 before'` after both. The log showed `403 … "cannotCopyFile"` before each line and no `Replacing doc … without a backup` line. `cleanup done` was printed.

**Result (2026-10-17) ⏭️ SKIP — v0.9.2 release pass**
The scratch script needs a usable OAuth token (see DOC80).

**Result (2026-10-19) ⏭️ SKIP — v0.9.3 release pass**
`jay`: Same reason as TC-DOC225.

---

### TC-DOC227: Column widths on tables after the first ⚠️ destructive
**Purpose:** Regression test for #1053. `fill_tables` built `updateTableColumnProperties` from the doc as it was before the cell fill, so widths on any table after the first failed with 400 "The provided table start location is invalid." and left the doc partly written. TC-DOC35 covers only a single table. The fourth table covers the same partial-write failure through more `<col>` widths than the row has cells (400 "Invalid column index"), found in PR #1082 QA round 1.

**Prompt**
**Playwright: required**
1. `write_doc_content(doc_id="{DOC_ID}", content='<p>intro</p><table><tr><td>first table text</td><td>more</td></tr></table><p>sep</p><table><col width="144"><col width="288"><tr><td>Narrow</td><td>Wide</td></tr></table><p>sep</p><table><col width="300"><tr><td>Third</td></tr></table><p>sep</p><table><col width="100"><col width="100"><col width="100"><tr><td>a</td><td>b</td></tr></table>')`
2. `get_doc_as_markdown(doc_id="{DOC_ID}")`

**Checks**
- Step 1 returns no `error` key and no `backupId` key (a kept backup means the write failed partway)
- Step 2 shows all four tables with their text: `first table text`/`more`, `Narrow`/`Wide`, `Third`, `a`/`b`
- 🔍 Playwright: in the second table, the "Narrow" column is visibly about half the width of "Wide" (144:288). The third table's single column is narrower than the page's full text width. The fourth table has three `<col>` widths but only two cells: its two columns are equal and narrower than the page (the third width is skipped, not sent as an invalid column index). The first table's columns are evenly distributed

**Cleanup:** write fixture content back

**Result (2026-10-18) ❌ FAIL — PR #1082 QA round 1 (Kit)**
Step 1: no `error`, no `backupId`. Step 2: all three tables with their text. Playwright: second table Narrow:Wide is 1:2, third table narrower than the page, first table evenly distributed — the #1053 fix works. Fails only the yellow-background check: `html_parser` never parses `<td style="background-color:…">` (no write path sets a cell's `background_color`), so this check expects behavior the tool has never had. Test-case text needs correcting, not the code.

**Result (2026-10-18) ✅ PASS — PR #1082 QA round 2 (Kit)**
Step 1: no `error`, no `backupId`. Step 2: all four tables with their text. Playwright: second table Narrow:Wide 1:2; third table narrower than the page; fourth table (three `<col>`, two cells) has two equal columns narrower than the page, so the extra width was skipped instead of failing with "Invalid column index 2" as in round 1; first table evenly distributed.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: #1053 regression. Four-table write: no `error`, no `backupId`, and no `(backup before replace)` copy left. Export has all four tables' text. Playwright (`tc-doc227.png`): Narrow:Wide is 144:288 px (1:2); Third is 300 px, narrower than the page; the fourth table is two equal 100 px columns (the extra `<col>` was skipped); the first table is evenly distributed.

---

### TC-DOC228: A soft break in prose exports as `<br>`, not a raw `\v` ⚠️ destructive
**Purpose:** Regression test for #1057. `get_doc_as_markdown` turned a soft break (`"\v"`) back into a line break only in Courier New runs, so a soft-break paragraph from `insert_softbreak_paragraph` exported a literal U+000B in normal text. It must export as a `<br>` hard break, in a paragraph and a heading alike, and a line that looks like Markdown syntax must stay inside the paragraph.

**Setup:** `write_doc_content(doc_id="{DOC_ID}", content="<p>anchor one</p><p>anchor two</p>")`

**Steps**
1. `insert_softbreak_paragraph(doc_id="{DOC_ID}", index=1, lines=[{"text": "first", "bold": true}, {"text": "# not a heading"}, {"text": "linked", "link_url": "https://example.com"}, {"text": "tail: "}])`
2. `find_in_doc(doc_id="{DOC_ID}", query="anchor two")`, note the match's start index as `{N}`
3. `insert_softbreak_paragraph(doc_id="{DOC_ID}", index={N}, lines=[{"text": "Heading line"}, {"text": "subtitle: "}], named_style_type="HEADING_2")`
4. `get_doc_as_markdown(doc_id="{DOC_ID}", local_path="/tmp/tc-doc228.md")`
5. `uv run python -c "from markdown_it import MarkdownIt; print(MarkdownIt('commonmark').render(open('/tmp/tc-doc228.md').read()))"`
6. `uv run python -c "print('\x0b' in open('/tmp/tc-doc228.md').read())"`
7. Whitespace beside an edge break (PR #1088 QA round 1): `write_doc_content(doc_id="{DOC_ID}", content="<p>anchor</p>")`, then `insert_softbreak_paragraph(doc_id="{DOC_ID}", index=1, lines=[{"text": "a "}, {"text": "link"}, {"text": "b: "}])`, then `style_doc_range(doc_id="{DOC_ID}", ranges=[{"start_index": 2, "end_index": 8, "link_url": "https://example.com/x"}])` (the link covers `" \vlink"`), then `get_doc_as_markdown(doc_id="{DOC_ID}")`
8. `style_doc_range(doc_id="{DOC_ID}", ranges=[{"start_index": 2, "end_index": 8, "font_family": "Courier New"}])`, then `get_doc_as_markdown(doc_id="{DOC_ID}")`

**Checks**
- Step 6 prints `False`: no raw vertical tab anywhere in the export
- Step 5's HTML has `<p><strong>first</strong><br># not a heading<br><a href="https://example.com">linked</a><br>tail: anchor one</p>`: one paragraph, no `<h1>`, and the `<br>` on each side of the link sits outside the `<a>`. markdown-it passes inline raw HTML through as written, so it prints `<br>`, not `<br />`
- Step 5's HTML has `<h2>Heading line<br>subtitle: anchor two</h2>`
- Step 7's `markdown` starts `a <br>[link](https://example.com/x)<br>b: anchor`: the space and the `<br>` sit outside the link's brackets, not `a[ <br>link](...)`
- Step 8's `markdown` starts ``a <br>[`link`](https://example.com/x)<br>b: anchor``: the same for a linked code span

**Cleanup:** write fixture content back, `rm /tmp/tc-doc228.md`

**Result (2026-10-18) ✅ PASS — Sky, PR #1088 round 1 (`76b82a9`).** Ran on a scratch doc (`create_doc` with the Setup content, trashed afterwards) instead of the shared fixture. `{N}` was 47. The export was `**first**<br># not a heading<br>[linked](https://example.com)<br>tail: anchor one` / `## Heading line<br>subtitle: anchor two`; step 5 rendered `<p><strong>first</strong><br># not a heading<br><a href="https://example.com">linked</a><br>tail: anchor one</p>` and `<h2>Heading line<br>subtitle: anchor two</h2>`; step 6 printed `False`. The checks as first written expected `<br />`, which markdown-it never prints for inline raw HTML, so they were corrected to `<br>` in this round; the behavior they check was right.

**Result (2026-10-18) ✅ PASS — Sky, PR #1088 round 2 (`e972af0`).** Scratch doc, trashed afterwards. Steps 1–6 gave the same export and HTML as round 1, and step 6 printed `False`. Steps 7–8 are new this round: step 7 reproduced round 1's send-back (`a[ <br>link](https://example.com/x)<br>b: anchor` at `76b82a9`) and now exports `a <br>[link](https://example.com/x)<br>b: anchor`; step 8 exports ``a <br>[`link`](https://example.com/x)<br>b: anchor``.

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`jay`: #1057 regression. Export: `**first**<br># not a heading<br>[linked](https://example.com)<br>tail: anchor one\n\n## Heading line<br>subtitle: anchor two`. markdown-it renders the exact expected `<p>` and `<h2>`. `'\x0b' in file` is False. Step 7: `a <br>[link](https://example.com/x)<br>b: anchor`. Step 8: ``a <br>[`link`](https://example.com/x)<br>b: anchor``.

---

### TC-DOC229: Quoted nested and numbered lists keep both the list indent and the quote indent ⚠️ destructive
**Purpose:** Regression test for #1056. `createParagraphBullets` overwrites a paragraph's `indentStart` and `indentFirstLine` with the list preset's, so the quote indent set before it was lost and a quoted list sat at the same indent as an unquoted one. The emitter now styles a quoted list item after its bullets call, at the list level's own indent plus 36pt per quote level. TC-DOC160 covers one level-0 bulleted run. This case adds a nested item, a numbered list, and an unquoted list that must stay at the preset's indents.

**Prompt**
**Playwright: required**
1. `write_doc_content(doc_id="{DOC_ID}", content="- plain\n    - plain nested\n\nmid\n\n> - Quoted item one\n>     - Quoted nested\n> - Quoted item two\n\n> 1. Quoted numbered\n", content_format="markdown")`
2. `get_doc_as_markdown(doc_id="{DOC_ID}")`

**Checks**
- Step 1 returns no `error` key
- Raw `documents().get()` read, `paragraphStyle` per list paragraph as (`indentFirstLine`, `indentStart`) magnitudes:
  - "plain" (18, 36) and "plain nested" (54, 72), with no `borderLeft`
  - "Quoted item one" and "Quoted item two" (54, 72), "Quoted nested" (90, 108), "Quoted numbered" (54, 72), each with a `borderLeft`
- Step 2's output has `> - Quoted item one`, `>   - Quoted nested`, `> - Quoted item two`, and `> 1. Quoted numbered`, each with exactly one `>`; "plain" and "plain nested" have none
- 🔍 Playwright: each quoted item's glyph sits visibly to the right of the unquoted item at the same level ("Quoted item one" right of "plain", "Quoted nested" right of "plain nested"), with the gray bar to the left of the quoted glyphs

**Cleanup:** write fixture content back

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 1 (Kit) @ 13f4274**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. Step 1 returned no `error`. In the raw read, (`indentFirstLine`, `indentStart`) were: "plain" (18, 36) and "plain nested" (54, 72), neither with a `borderLeft`; "Quoted item one" and "Quoted item two" (54, 72), "Quoted nested" (90, 108), and "Quoted numbered" (54, 72), each with a `borderLeft`. Step 2 output had `> - Quoted item one`, `>   - Quoted nested`, `> - Quoted item two`, and `> 1. Quoted numbered`, each with exactly one `>`, and the plain items had none. Playwright: "Quoted item one" sits to the right of "plain" and "Quoted nested" to the right of "plain nested", with the gray bar to the left of each quoted glyph. Observed, not a defect: Docs draws `borderLeft` at each paragraph's own indent, so the nested item's bar steps right instead of continuing the quote's bar. The same happened before #1056, because list levels already differed in indent.

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 2 (Kit) @ c118bdd**
Run on a scratch doc in the Shared Drive QA folder instead of the fixture. Same result as round 1: "plain" (18, 36) and "plain nested" (54, 72) with no `borderLeft`; "Quoted item one", "Quoted item two", and "Quoted numbered" (54, 72) and "Quoted nested" (90, 108), each with a `borderLeft`. Step 2 printed each quoted item with exactly one `>`. Playwright: each quoted glyph sits to the right of the unquoted one at the same level, with the gray bar to its left.

**Result (2026-10-18) ✅ PASS — PR #1089 QA round 3 (Kit) @ 85bbf00**
Re-run after the `develop` merge (with #1088 and the google-auth bump), on a scratch doc in the Shared Drive QA folder, via `create_doc` with the same Markdown. Raw read, Markdown export, and Playwright were all the same as round 2: plain (18, 36) and (54, 72) with no border, quoted level-0 items (54, 72), "Quoted nested" (90, 108), each quoted item with a `borderLeft` and exactly one `>`.

**Result (2026-10-19) ⚠️ PARTIAL — v0.9.3 release pass**
`jay`: #1056 regression. No error. Export has `> - Quoted item one`, `>   - Quoted nested`, `> - Quoted item two`, `> 1. Quoted numbered`, each with one `>`; the plain items have none. Playwright (`tc-doc229.png`): "Quoted item one" glyph sits about 48px (36pt) right of "plain", "Quoted nested" right of "plain nested", with a gray bar left of each quoted glyph. Not run: the raw `documents().get()` indent/borderLeft read (scratch script).

---

### TC-DOC230: Adjacent separate quotes render as separate quotes, with space around each ⚠️ destructive
**Purpose:** Regression test for #1098. Docs joins the left borders of adjacent paragraphs with the same border and indents, so two separate quotes in a row showed one continuous bar, and a quote touched the paragraphs around it. The emitter now puts a collapsed, unbordered paragraph between two separate quotes and gives each quote 8pt where it meets other content; a separator is spaced on one side only, below the quote before it. A quoted heading keeps its named style's own spacing. HTML input, because Python-Markdown merges `> a`, a blank line, `> b` into one quote before the emitter sees it (#1116). The quoted heading was added in round 2 (PR #1199 QA round 1 found its HEADING_1 spacing overwritten).

**Prompt**
**Playwright: required**
1. `write_doc_content(doc_id="{DOC_ID}", content="<p>Before.</p><blockquote><p>Quote one</p></blockquote><blockquote><p>Quote two</p></blockquote><blockquote><p>Same quote, first</p><p>Same quote, second</p></blockquote><blockquote><blockquote><p>Inner one</p></blockquote><blockquote><p>Inner two</p></blockquote></blockquote><blockquote><ul><li>List one A</li><li>List one B</li></ul></blockquote><blockquote><ul><li>List two A</li></ul></blockquote><p>After.</p><blockquote><h1>Quoted H1</h1><p>Quoted para</p></blockquote><h1>Unquoted H1</h1>", content_format="html")`
2. `get_doc_structure(doc_id="{DOC_ID}")`

**Checks**
- Step 1 returns no `error` key
- Step 2 (and a raw `documents().get()` read, `paragraphStyle`): an empty paragraph with no `borderLeft` sits between "Quote one" and "Quote two", between "Quote two" and "Same quote, first", between "Same quote, second" and "Inner one", between "Inner one" and "Inner two", between "Inner two" and "List one A", and between "List one B" and "List two A". None sits between "Same quote, first" and "Same quote, second", or between "List one A" and "List one B"
- Raw read: of the quoted paragraphs, only "Quote one" has `spaceAbove` 8pt (each other quote follows a separator, which is spaced on one side only). "Quote one", "Quote two", "Same quote, second", "Inner one", "Inner two", "List one B", "List two A", and "Quoted para" each have `spaceBelow` 8pt. "Same quote, first" has no `spaceBelow` and "Same quote, second" no `spaceAbove`
- Raw read: "Quoted H1" has `namedStyleType` `HEADING_1`, a `borderLeft`, and no `spaceAbove`/`spaceBelow` of its own (it uses HEADING_1's)
- "List one A"/"List one B" share a `listId`; "List two A" has a different one
- 🔍 Playwright: "Quote one" and "Quote two" each have their own gray bar with a visible gap between the bars; "Same quote, first" and "Same quote, second" share one unbroken bar; "Inner one" and "Inner two" have separate bars; the two quoted lists have separate bars. "Before." and "After." have visible space between them and the quotes next to them. No empty line shows where a separator paragraph is: the gap between two separate quotes is about the same as between "Before." and "Quote one" (baseline to baseline, within a few px). The gap above "Quoted H1" is HEADING_1's own and visibly larger than the gap above "Quote one" (round 1 found it shrunk to the 8pt quote gap)

**Cleanup:** write fixture content back

**Result (2026-10-24) ❌ FAIL — PR #1199 QA round 1 (Kit) @ 7811da8**
`kit`, on a scratch doc in the fixture folder (deleted afterward), not the fixture doc. Step 1: no error. Step 2 and raw read: an unbordered empty paragraph (`lineSpacing` 1, 1pt font) sits at each of the six expected places and nowhere else. `spaceAbove`/`spaceBelow` 8pt are exactly as listed. "List one A"/"B" share a `listId` and "List two A" has a different one. Playwright (`2026-10-24-tc-doc230.png`): each separate quote has its own bar, "Same quote, first/second" share one, and no separator line is visible. **Fails the last check:** baseline to baseline, "Before."→"Quote one" is 31px but "Quote one"→"Quote two" is 41px (a normal line is about 19px). Between two separate quotes, the 8pt `spaceBelow` and 8pt `spaceAbove` add up to about double the gap a quote has from plain text. Sent back on PR #1199. Side observation: `get_doc_as_markdown` reads each separator back as two extra blank lines between the quotes (`> Quote one\n\n\n\n> Quote two`). The Markdown is still valid.

**Result (2026-10-24) ✅ PASS — PR #1199 QA round 2 (Kit) @ a211c94**
`kit`, on a scratch doc in the fixture folder (deleted afterward), not the fixture doc, with the round-2 input. Step 1: no error. Raw read: the six unbordered collapsed separators are in place, and there is none inside "Same quote" or between "List one A"/"B". Of the quoted paragraphs, only "Quote one" has `spaceAbove` 8pt. `spaceBelow` 8pt is on exactly the listed ones, "Quoted para" included. "Quoted H1" is `HEADING_1` with a border and no `spaceAbove`/`spaceBelow` of its own. The list IDs are as expected. Playwright (`2026-10-24-tc-doc230-r2.png`): every separate quote has its own bar and "Same quote" has one bar. Baseline to baseline, "Before."→"Quote one" is 31px and "Quote one"→"Quote two" is 30px. The gap above "Quoted H1" is HEADING_1's, visibly larger than the one above "Quote one".

---

### TC-DOC231: Consecutive code blocks and consecutive tables stay separate ⚠️ destructive
**Purpose:** Regression test for #1098. Two code blocks in a row read as one block, since neither had any spacing, and two tables in a row touched and read as one table, since the paragraph Docs requires between them was collapsed like the one before every table. Code blocks now get 8pt above and below, and the paragraph between two tables keeps its height. The numbered list after the tables was added in round 2: `insertTable` gives the paragraphs before each table the following block's style (#1097), so at full height the one between the tables showed as an empty numbered item, and the list started at 3 (PR #1199 QA round 1).

**Prompt**
**Playwright: required**
1. `write_doc_content(doc_id="{DOC_ID}", content="Before.\n\n```\ncode one\nsecond line\n```\n\n```\ncode two\n```\n\nBetween.\n\n| K | V |\n|---|---|\n| k1 | v1 |\n\n| K | V |\n|---|---|\n| k2 | v2 |\n\n1. numbered one\n2. numbered two\n", content_format="markdown")`
2. `get_doc_structure(doc_id="{DOC_ID}")`

**Checks**
- Step 1 returns no `error` key
- Raw `documents().get()` read: the "code one…second line" paragraph (one paragraph, lines joined by a soft break) and the "code two" paragraph each have `spaceAbove` and `spaceBelow` 8pt; "Before." and "Between." have neither
- Step 2 shows two tables with exactly one empty paragraph between them. Raw read: that paragraph's `namedStyleType` is `NORMAL_TEXT`, and it has no `lineSpacing` 1 and no 1pt `fontSize`. The empty paragraph before the first table is still collapsed (`lineSpacing` 1, 1pt `fontSize`)
- Raw read: neither empty paragraph has a `bullet`, an `indentStart`/`indentFirstLine`, or a `borderLeft`
- 🔍 Playwright: the two code blocks show a visible gap between them, and between each and the paragraph next to it. The two tables show a blank line between them (the first table's bottom border doesn't touch the second's top border), with no list glyph on it. No visible blank line shows above the first table. The list after the tables is numbered "1." and "2." Not a check here: both tables sit indented to the list's indent, which comes from the tables' own cells and is #1097

**Cleanup:** write fixture content back

**Result (2026-10-24) ✅ PASS — PR #1199 QA round 1 (Kit) @ 7811da8**
`kit`, on a scratch doc in the fixture folder (deleted afterward), not the fixture doc. Step 1: no error. Raw read: "code one\vsecond line" (one paragraph) and "code two" each have `spaceAbove`/`spaceBelow` 8pt, and "Before." and "Between." have neither. Exactly one empty paragraph sits between the two tables. It is `NORMAL_TEXT`, with no `lineSpacing` and no font size set. The paragraph before the first table is still collapsed (`lineSpacing` 1, 1pt). Playwright (`2026-10-24-tc-doc231.png`): the code blocks have visible gaps, a blank line separates the tables, and nothing is visible above the first table. Beyond this case's checks, a probe on the same head found that when a list follows two tables, the paragraph between them keeps the list's bullet and shows a visible empty numbered item. It was sent back on PR #1199.

**Result (2026-10-24) ✅ PASS — PR #1199 QA round 2 (Kit) @ a211c94**
`kit`, on a scratch doc in the fixture folder (deleted afterward), not the fixture doc, with the round-2 input. Step 1: no error. Raw read: both code paragraphs have 8pt above and below, and "Before." and "Between." have neither. Exactly one empty paragraph sits between the tables. It is `NORMAL_TEXT` at full height. The paragraph before the first table is collapsed (`lineSpacing` 1, 1pt). Neither empty paragraph has a `bullet`, an indent or a `borderLeft`. Playwright (`2026-10-24-tc-doc231-r2.png`): the code blocks have visible gaps, and a blank line with no glyph separates the tables. Nothing is visible above the first table, and the list numbers "1." and "2." Both tables still sit indented to the list's indent. That is outside this case's checks and tracked in open #1097. Probe on the same head (`2026-10-24-pr1199-r2-probe.png`): with a quote after two tables, neither empty paragraph has a border or indent. A quote ending in an H2 is kept apart from the next quote by a separator, with the H2's own spacing intact.

---

### TC-DOC232: A table doesn't take the style of the block after it ⚠️ destructive
**Purpose:** Regression test for #1097. `insertTable` gives a table its left indent, and every empty cell its text style, from the paragraph at the insertion point, which was the start of the next block. A table before a list or quote sat indented to it, and one before a bold, Courier New, or heading-styled first character showed that style in every cell (r13, r15, TC-MD202/203, TC-MD402). Each table is now inserted at a plain placeholder paragraph of its own, deleted right after.

**Prompt**
**Playwright: required**
1. `write_doc_content(doc_id="{DOC_ID}", content="## Before\n\n| Day | City |\n|---|---|\n| Mon | Lisbon |\n\n**Hotel:** Casa do Bairro\n\n| Day | City |\n|---|---|\n| Tue | Porto |\n\n> **Note:** quoted text\n\n| Day | City |\n|---|---|\n| Wed | Braga |\n\n```\ncode here\n```\n\n| Day | City |\n|---|---|\n| Thu | Faro |\n\n#### After\n\n| K | V |\n|---|---|\n| k1 | v1 |\n\n| K | V |\n|---|---|\n| k2 | v2 |\n\n1. numbered one\n2. numbered two\n", content_format="markdown")`
2. `get_doc_as_markdown(doc_id="{DOC_ID}")`

**Checks**
- Step 1 returns no `error` key
- Raw `documents().get()` read: there are six tables. In each, the header cells' runs have `bold` true and nothing else set in `textStyle`, and the body cells' runs have an empty `textStyle` (no `bold`, no `weightedFontFamily`, no `foregroundColor`, no `fontSize`)
- Raw read: "Hotel:" is still bold, "Note:" is bold inside a paragraph with a `borderLeft`, "code here" is Courier New, "After" is `HEADING_4`, and "numbered one"/"numbered two" share a `listId`
- Raw read: no empty paragraph sits directly after any table. Each table is followed by its own next block's first paragraph, except the first of the two `K | V` tables, which is followed by the one full-height empty paragraph between them (TC-DOC231)
- Drive HTML export (`export_file` to `text/html`, or `files().export`): no `<table>` has a `margin-left` in its `style`
- Step 2: every body cell reads as plain text (no `**`, no backticks)
- 🔍 Playwright: all six tables sit at the left margin, aligned with "Before" and "Hotel:", including the ones before the quote and before the numbered list. Only the header rows are bold; body cells are in the body font and color, not gray, not monospace. The numbered list starts at "1."

**Cleanup:** write fixture content back

**Result (2026-10-24) ✅ PASS — PR #1201 QA round 1 (Kit) @ cfc5a32**
`kit`, on a scratch doc in the fixture folder (trashed afterward), not the fixture doc. Step 1: no error. Raw read: six tables; header runs `bold` only, body runs an empty `textStyle`. "Hotel:" bold, "Note:" bold with a `borderLeft`, "code here" Courier New, "After" `HEADING_4`, both numbered items share one `listId`. No empty paragraph follows any table, except the full-height one between the two `K | V` tables. HTML export: no `<table>` has `margin-left`. Step 2: body cells plain. Playwright (`2026-10-24-tc-doc232.png`): the tables are at the left margin, with only the header rows bold. Probes on the same head, all outside this case's checks: a table between two numbered items (`1. step one`, table, `2. step two`) exports with `margin-left:36pt`, because the list's `createParagraphBullets` range covers the placeholder. A table inside a quote renders at margin 0, between two indented, bordered quote paragraphs. `write_doc_content` over a doc whose final paragraph is an indented `HEADING_2` turns every replaced paragraph into `HEADING_2`, and a merged-away cell's empty paragraph gets `fontSize` 16. 1x1, 1x3, and 3x5-with-colspan HTML tables each lose their placeholder cleanly.

**Result (2026-10-24) ✅ PASS — PR #1201 QA round 2 (Kit) @ f73ba2f**
`kit`, re-run on a scratch doc in the fixture folder (trashed afterward). Every raw-read, HTML-export, and Markdown check holds as in round 1: six tables, none with `margin-left`, header runs `bold` only, body runs empty, and both numbered items share one `listId`. The round-1 probe gaps are covered by TC-DOC233.

---

### TC-DOC233: A table between list items, a table inside a quote, and a doc that ended in a heading ⚠️ destructive
**Purpose:** Regression test for the three gaps PR #1201 QA round 1 found beyond TC-DOC232 (#1097). A table between two numbered items sat inside the list's one `createParagraphBullets` range, so its placeholder was bulleted and the table took the list's indent. A table inside a quote lost the quote's indent once it stopped taking the next quote paragraph's. And `write_doc_content` kept the doc's final paragraph style through the clear, so a doc that ended in an indented heading turned the new content, the table placeholder included, into that heading.

**Prompt**
**Playwright: required**
1. `write_doc_content(doc_id="{DOC_ID}", content="Old body\n\nOld heading\n", content_format="markdown")`
2. `get_doc_structure(doc_id="{DOC_ID}")`, and note the "Old heading" paragraph's `start_index` and the last paragraph's `end_index`. The last paragraph is the empty one after "Old heading", and it's the one whose style survives the clear, so styling "Old heading" alone doesn't exercise the fix
3. `style_doc_range(doc_id="{DOC_ID}", ranges=[{"start_index": <Old heading start_index>, "end_index": <last paragraph end_index>, "named_style_type": "HEADING_2"}])`
4. `write_doc_content(doc_id="{DOC_ID}", content="Intro para\n\n1. step one\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n2. step two\n\n> quote a\n>\n> | Q | R |\n> |---|---|\n> | 3 | 4 |\n>\n> quote b\n\nAfter **bold**\n", content_format="markdown")`
5. `get_doc_as_markdown(doc_id="{DOC_ID}")`

**Checks**
- Steps 1, 3, and 4 return no `error` key
- Raw `documents().get()` read after step 4: no paragraph is `HEADING_2`. "Intro para" and "After bold" are `NORMAL_TEXT` with no `indentStart`
- Raw read: "step one" and "step two" share one `listId`; the empty paragraph before the `A | B` table has no `bullet`
- Raw read: both tables' header runs have `bold` true and nothing else in `textStyle`; body runs have an empty `textStyle` (no `fontSize` either)
- Raw read: "quote a" and "quote b" each have a `borderLeft` and a 36pt `indentStart`
- Drive HTML export (`export_file` to `text/html`, or `files().export`): the `A | B` table's `<table>` style has no `margin-left`; the `Q | R` table's has `margin-left:36pt`. The list's two `<ol>` elements share one `lst-kix_…` class, with `start="1"` and `start="2"`
- Step 5: "step one" and "step two" read as items 1 and 2
- 🔍 Playwright: the `A | B` table sits at the left margin, aligned with "Intro para", not with the list text. The list numbers "1." and "2." The `Q | R` table is indented to the quote text's left edge, with no gray bar beside it. Nothing reads as a heading

**Cleanup:** write fixture content back

**Result (2026-10-24) ⚠️ PARTIAL — PR #1201 QA round 2 (Kit) @ f73ba2f**
`kit`, on a scratch doc in the fixture folder (trashed afterward). Step 3 was run over "Old heading" through the final empty paragraph, which was also bulleted: as first written, step 3 styled only "Old heading", which isn't the paragraph that survives the clear (steps 2–3 fixed in this round). Steps 1, 3, 4: no error. Raw read after step 4: no `HEADING_2`; "Intro para" and "After bold" `NORMAL_TEXT` with no indent; "step one"/"step two" share one `listId`; the empty paragraph before `A | B` has no bullet; header runs `bold` only, body runs empty. "quote a"/"quote b" have a `borderLeft` and 36pt. HTML export: `A | B` has no `margin-left`, `Q | R` has `margin-left:36pt`; the two `<ol>` share one `lst-kix_` class with `start="1"`/`start="2"`. **Step 5 fails:** `get_doc_as_markdown` returns `1. step two`, since the read side writes every numbered item as `1.` and the table ends the Markdown list (#1208; outside PR #1201's diff). Playwright (`2026-10-24-tc-doc233.png`): `A | B` at the margin, list numbered 1 and 2, `Q | R` indented to the quote text with no bar, no headings. Probes (`create_doc`, HTML): a quoted table as the doc's first element exports at 36pt, one in a depth-2 quote at 72pt, and one inside a quoted list at 36pt (the quote's indent). A colspan table in a quote is clean.

**Result (2026-10-25) ⚠️ PARTIAL — PR #1234 QA round 1 (Sky) @ 79a7a38, step 5 only**
`sky`. Only step 5 was in scope for #1208. Step 4's content was written with `create_doc(content_format="markdown")` to a scratch doc (trashed afterward), not with `write_doc_content` over the fixture. Steps 1–3, the raw/HTML checks and Playwright were not re-run. Step 5: `get_doc_as_markdown` returns `1. step one`, the `A | B` table, then `2. step two`, so the #1208 failure from the 2026-10-24 round is fixed.

**Result (2026-10-25) ⚠️ PARTIAL — PR #1234 QA round 2 (Sky) @ 2af4b0b, step 5 only**
`sky`, after `/mcp reconnect`, with the same scope and method as round 1 (scratch doc, trashed afterward). Step 5: `1. step one`, the `A | B` table, `2. step two`.

---

### TC-DOC234: Table-cell images: text around one, a linked one, an unreachable one, and nested tables ⚠️ requires-oauth ⚠️ destructive
**Purpose:** Regression test for #1073 beyond TC-DOC153's single image-only cell. A cell image goes in during the table fill, so this covers what the fill has to get right: an image's offset among the cell's text, two adjacent images keeping source order, a link on the image, an unfetchable image dropped without losing the rest of the table, and the position of a nested table after an image in the same cell.

**Prompt**
**Playwright: required**
1. `create_doc(title="TC-DOC234", content=<HTML below>, content_format="html")`, where the HTML is (`LOGO` = `https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png`):
   ```html
   <table>
   <tr><td>Text then <img src="LOGO"> then text</td><td><img src="LOGO"><img src="LOGO"></td><td>After</td></tr>
   <tr><td><a href="https://example.com/linked"><img src="LOGO"></a></td><td>bad: <img src="https://example.invalid/nope.png"> end</td><td>plain</td></tr>
   </table>
   <table><tr><td>Lead <img src="LOGO"><table><tr><td><img src="LOGO"> inner</td></tr></table>tail <img src="LOGO"></td></tr></table>
   <p>Final paragraph</p>
   ```
2. `create_doc(title="TC-DOC234 md", content="| Name | Logo |\n|---|---|\n| Two | ![a](LOGO) and ![b](LOGO) |\n\ndone\n", content_format="markdown")`
3. `get_doc_as_markdown(doc_id=<step 2's docId>)`

**Checks**
- Steps 1 and 2 return no `error` key
- Step 1's `images` has 8 entries. The `example.invalid` one has an `error` starting `doc edit failed:` and naming the image fetch; the other 7 have no `error`
- Raw `documents().get()` read of step 1's doc, writing each `inlineObjectElement` as `[IMG]`: row 0 cells read `Text then [IMG] then text`, `[IMG][IMG]`, `After`. Row 1 cells read `[IMG]`, `bad:  end` (two spaces, no image), `plain`. Row 1 cell 0's `inlineObjectElement` has `textStyle.link.url` `https://example.com/linked`
- Raw read, second table's one cell: a paragraph `Lead [IMG]`, then the nested table, then a paragraph `tail [IMG]`. The nested table's one cell reads `[IMG] inner`
- "Final paragraph" is present after the second table
- Step 3: the `Two` row's cell holds two images with ` and ` between them
- 🔍 Playwright (step 1's doc): a logo shows in every cell the raw read shows `[IMG]` in, and none in the `bad:` cell. Text sits on the expected side of each logo; the nested table sits between "Lead" and "tail"

**Cleanup:** trash both docs

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 1 (Kit) @ 79f19d4**
`kit`: steps 1 and 2 returned no error. Step 1's `images` held 8 entries: `example.invalid` had `doc edit failed: insertInlineImage: There was a problem retrieving the image…`, and the other 7 had no error. Raw read: row 0 is `Text then [IMG] then text` / `[IMG][IMG]` / `After`; row 1 is `[IMG]` (link `https://example.com/linked`) / `bad:  end` / `plain`. The second table reads `Lead [IMG]`, then the nested table (`[IMG] inner`), then `tail [IMG]`; "Final paragraph" follows. Step 2 raw read: `[IMG] and [IMG]`. Step 3: the `Two` row is `![](…) and ![](…)`. Playwright (`2026-10-24-tc-doc234.png`): logos match the raw read, none in `bad:`, and the nested table sits between Lead and tail. Probe (not a Check): a local-path PNG in a top-level cell and in a nested cell, on the Shared Drive default folder, uploaded, embedded at the right offset (`local: [IMG] end`, `nested [IMG]`), and reported `shared: false` after revoke. Both docs and both uploads trashed.

**Result (2026-10-24) ✅ PASS — PR #1215 QA round 2 (Kit) @ f9f6ee7**
`kit`: steps 1–2 returned no error; step 1's `images` held 8 entries, with only `example.invalid` carrying `doc edit failed:`. The raw reads match round 1 exactly, row by row, including the linked image and the nested table between `Lead [IMG]` and `tail [IMG]`; step 2 reads `[IMG] and [IMG]`. Probe (not a Check), batch split: one row of four cells, `A1 <bad> x` / `B1 <logo> y` / `C1 <bad> z` / `D1 <logo> w`, so two unfetchable images fall in one cell-fill batch. Both bad ones were reported with `doc edit failed:`, and the raw read is `A1  x` / `B1 [IMG] y` / `C1  z` / `D1 [IMG] w`, every good image at its offset. Docs trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 3 (Kit) @ e3a6e69**
`kit`: steps 1–2 returned no error; 8 entries, with only `example.invalid` in error. The raw reads match rounds 1–2 row by row, and step 2 reads `[IMG] and [IMG]`. Probes (not Checks), one doc. Body retry, now on the shared `batch_retry` loop: five body paragraphs with three unfetchable images and a linked logo after them read `B1  one` / `B2 [IMG] two` / `B3  three` / `B4  four` / `B5 [IMG link=https://example.com/l] five`. Cell batch split: `A1  x` / `B1 [IMG] y` / `C1  z` / `D1 [IMG] w`. An image-only cell in a table after an `<h1>` carries no `fontSize` and renders the same height as its text neighbor (`2026-10-25-pr1215-r3-probe.png`). Docs trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 4 (Kit) @ 5d2b4e8**
`kit`: steps 1–2 returned no error, and the `images` entries match round 3. The raw reads match rounds 1–3 row by row, and step 2 reads `[IMG] and [IMG]`. Playwright (`2026-10-25-tc-doc234-r4.png`) matches. Probes (not Checks): the body retry with three unfetchable images plus a linked logo, and the cell batch split, give the same raw reads as round 3. Docs trashed.

---

### TC-DOC235: Line breaks and block content inside a table cell survive HTML parsing ⚠️ requires-oauth ⚠️ destructive
**Purpose:** Regression guard for PR #1215 round 2. Collapsing source whitespace in a cell, done to stop indentation before a nested table from becoming empty paragraphs, must not merge a cell's own block content or a `<pre>`'s lines, and must not leak a space past the table.

**Prompt**
1. `create_doc(title="TC-DOC235", content=<HTML below>, content_format="html")`:
   ```html
   <table><tr><td><p>para one</p>
   <p>para two</p></td><td><pre>line1
     line2</pre></td><td><a href="https://example.com/x">linked
   </a>after</td></tr></table>
   <table><tr><td>
     <table><tr><td>inner</td></tr></table>
   </td></tr></table>
   <p>End</p>
   ```

**Checks**
- No `error`
- Raw `documents().get()` read, first table: cell 0 has `para one` and `para two` as two separate lines, not `para one para two`. Cell 1 keeps `line1` and `line2` on separate lines. Cell 2's `linked` keeps its link, and the source newline after it stays inside the link, as on `develop`. That newline is a line break, so `after` is on its own line: it's the cell's existing source-newline behavior, tracked separately, and not what this case checks
- Second table: the outer cell holds the nested table with no paragraph made only of indentation spaces before or after it
- `End` is its own paragraph after the second table

**Cleanup:** trash the doc

**Result (2026-10-24) ❌ FAIL — PR #1215 QA round 2 (Kit) @ f9f6ee7**
`kit`: probe run of the same shapes (`<p>`, `<pre>`) in one `create_doc`. Raw read: cell 0 reads `para one para two` and the `<pre>` cell reads `line1 line2`, so both merged onto one line. On `develop`, `html_to_ast` keeps them as `a\nb` and `x\n  y`. The nested-table cell is correct (no indentation paragraphs). Sent back on PR #1215 round 2. Doc trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 3 (Kit) @ e3a6e69**
`kit`: no error. Raw read: cell 0 is `para one` / `para two` (two paragraphs), cell 1 is `line1` / `  line2`, and cell 2's `linked` carries `https://example.com/x`. The second table's outer cell holds only the structural empty paragraphs around the nested table (`inner`), and `End` follows. Playwright (`2026-10-25-tc-doc235.png`) matches. Cell 2's check was reworded this round: it had assumed the source newline after `linked` collapses to a space, but on `develop` and here it's a line break (existing behavior, tracked separately). The newline itself is now unlinked where `develop` kept it in the link, which is sent back on PR #1215 round 3. Doc trashed.

**Result (2026-10-25) ✅ PASS — PR #1215 QA round 4 (Kit) @ 5d2b4e8**
`kit`: no error. Raw read: `para one` / `para two`, `line1` / `  line2`, and `linked` (link `https://example.com/x`) then `after`. The second table holds only the structural empty paragraphs around `inner`. Probe (added cell, not a Check): `<td>\n  Intro text\n  <table>…nested…</table>\n  tail\n</td>` reads `Intro text` / nested table / `tail`, with no stray paragraphs. The newline after `linked` reads unlinked in the doc although the parser now keeps it in the link (`html_to_ast`: `('\n', 'http://u')`). It's the paragraph's end marker, which Docs doesn't link. Playwright (`2026-10-25-tc-doc235-r4.png`) matches. Doc trashed.

---

### TC-DOC236: `get_doc_as_markdown` numbers each ordered item as Docs does, across an interrupting table and nested sublists (#1208) ⚠️ requires-oauth ⚠️ destructive
**Purpose:** Regression test for #1208. The export wrote every numbered item as `1.`, so an item that continues a Docs list after a table read back as a second list starting at 1. It now writes each item's ordinal in its Docs list: counted per `listId` and nesting level, continuing across an interrupting block, and restarting a sublist under each new parent item. The ticket's own case (a table between two items) is TC-DOC233 step 5; this one adds nested sublists and a second, separate list.

**Prompt**
1. `create_doc(title="TC-DOC236", content="1. a\n    1. a1\n    1. a2\n1. b\n    1. b1\n\n| t |\n|---|\n| c |\n\n1. c\n\nAside\n\n1. x\n1. y\n", content_format="markdown")`
2. `export_file(file_id=<docId>, export_format="txt")`
3. `get_doc_as_markdown(doc_id=<docId>)`

**Checks**
- Step 1 returns no `error` key
- Step 2, Docs' own numbering: `1. a`, `1. a1`, `2. a2`, `2. b`, `1. b1`, then the table, `3. c`, `Aside`, `1. x`, `2. y`. If Docs numbers any item differently, the case's premise has changed: report it rather than checking step 3 against this list
- Raw `documents().get()` read: `a` through `c` share one `listId`, and `x`/`y` share a different one
- Step 3: every list item's marker matches step 2's number for that item, including `3. c` after the table and `1. x` starting the second list. (The sublist's indent is #1128, not checked here)

**Cleanup:** trash the doc

**Result (2026-10-25) ✅ PASS — PR #1234 QA round 1 (Sky) @ 79a7a38**
`sky`, doc created in the default folder (trashed afterward). Step 1: no error. Step 2 txt export: `1. a`, `1. a1`, `2. a2`, `2. b`, `1. b1`, the table, `3. c`, `Aside`, `1. x`, `2. y`. Docs' txt export writes level 1 as decimal (`1. a1`), not the preset's alpha glyph. `get_doc_structure` bullets: `a`/`a1`/`a2`/`b`/`b1`/`c` share one `listId`, and `x`/`y` share a different one. Step 3: `1. a`, `1. a1`, `2. a2`, `2. b`, `1. b1`, `3. c` after the table, `1. x`, `2. y`, all matching step 2.

**Result (2026-10-25) ✅ PASS — PR #1234 QA round 2 (Sky) @ 2af4b0b**
`sky`, after `/mcp reconnect`, on a fresh doc (trashed afterward). Steps 1–3 read the same as round 1: txt export `1. a`, `1. a1`, `2. a2`, `2. b`, `1. b1`, the table, `3. c`, `Aside`, `1. x`, `2. y`. `a`–`c` share one `listId` and `x`/`y` another. `get_doc_as_markdown` matches item for item. No sublist here starts past 1, so the new `1.` fallback isn't exercised live: the API can't write `startNumber`, and the case is unit-tested.

### TC-DOC237: A Docs edit tool cancelled while its edit is in flight re-invalidates the doc cache once the edit lands (#1030) ⚠️ requires-oauth ⚠️ destructive

**Background:** Same mechanism as TC-D301: `scripts/qa_cancel_inflight_write.py` runs the checkout's own tool against the real APIs and cancels it while its `batchUpdate` is held on its worker thread, printing every doc-cache invalidation as `doc cache marked dirty for <id> (write landed: yes|no)`. TC-DOC222 covers the image-embedding edits (#907); this case covers the edit tools outside `content.py`/`images.py`. `insert_doc_table` is included because it used to mark the doc dirty only once its re-fetch found the table.

**Setup:**
1. `create_doc(title="TC-DOC237", content="Before", content_format="markdown", folder_id={FOLDER_ID})`. Record `docId` as `{DOC_ID}`.

**Prompt**
> (none — script-driven; the steps below are shell commands plus tool calls)

**Steps**
1. `uv run python scripts/qa_cancel_inflight_write.py insert_doc_text --doc-id {DOC_ID}`
2. `uv run python scripts/qa_cancel_inflight_write.py insert_doc_table --doc-id {DOC_ID}`

**Checks**
- Each step prints `doc cache marked dirty for {DOC_ID} (write landed: no)`, then `cancelled <tool> while its write was in flight; the tool returned nothing`, then `doc cache marked dirty for {DOC_ID} (write landed: yes)`, and ends `writes sent: 1; landed: 1`. Before #1030, neither invalidation was printed
- After `refresh_cache(doc_id={DOC_ID})`, `get_doc_structure(doc_id={DOC_ID})` shows a table at the start of the body and `INFLIGHT1030 Before` after it (both cancelled edits landed)
- If a step shows only `(write landed: yes)`, the edit finished before the cancel reached the tool; re-run that step on a fresh doc

**Cleanup:** trash `{DOC_ID}`.

**Result (2026-10-26) ✅ PASS — PR #1264 QA round 1 (Kit) @ 46b3ba07**
Ran the script from the `kit` checkout with its own `TOKEN_PATH`, on a fresh doc (trashed afterward). Both steps printed `doc cache marked dirty for {DOC_ID} (write landed: no)`, then `cancelled <tool> while its write was in flight; the tool returned nothing`, then `(write landed: yes)`, and ended `writes sent: 1; landed: 1`. After `refresh_cache`, `get_doc_structure` showed an empty paragraph, a 1x1 table at index 2, and then `INFLIGHT1030 Before`, so both cancelled edits landed.

**Result (2026-10-27) ✅ PASS — PR #1264 QA round 2 (Kit) @ 0ca267f3**
Re-ran both steps on a fresh doc (trashed afterward) from the `kit` checkout at the fix commit. Same output as round 1, and `get_doc_structure` again showed the table followed by `INFLIGHT1030 Before`. Extra round-2 check for the `get_doc_content` epoch fix, in a fresh interpreter with a real in-memory `DocContentCache` and the real API: after one read, the cached row was overwritten with an older `modifiedTime` to stand in for an outside edit (Docs bumps `modifiedTime` minutes late, #814, so a real edit can't be timed reliably). The next read exported again, and the read after it served from cache with no further export, so the refetched content is now stored.


---

## `get_doc_structure`: inline images as runs (#1070)

### TC-DOC239: An inline image is its own run, with indices `delete_doc_range` can use (#1070) ⚠️ destructive
**Purpose:** #1070's failure was a paragraph of a tab then an image, where `get_doc_structure` gave no way to tell the image's index from the tab's. Each image is now a `{"type": "inlineObject", ...}` run with its own one-index span.

**Setup:** `create_doc(title="QA-TC-DOC239", folder_id={FOLDER_ID})`, then `insert_doc_text(doc_id=<it>, insertions=[{"index": 1, "text": "\tafter\nplain text\nX Y\n"}])`. Insert a public PNG with `insert_inline_image(uri=..., width=60, height=20)` at 21, then 20, then 2 (high index first), so the first paragraph is tab, image, `after` and the third is `X`, image, space, image, `Y`.

1. `get_doc_structure(doc_id=<it>)`
2. `delete_doc_range` over the first paragraph's image run `[startIndex, endIndex)`.
3. `insert_inline_image` at 2 again, `get_doc_structure`, then `delete_doc_range` over the tab `[1, 2)`.

**Checks**
- Step 1, first paragraph: `runs` are the `\t` text run, an `inlineObject` run spanning exactly one index (`[2, 3)`), then `after\n`. Its `inlineObjectId` is a key in the raw document's `inlineObjects`, and the paragraph `text` is still `"\tafter\n"`.
- Third paragraph: two `inlineObject` runs, each with its own ID and non-overlapping one-index spans in order.
- The second paragraph (no images) has one text run with no `type` key.
- Step 2 leaves `\tafter\n`: the image is gone and the tab is kept.
- Step 3 leaves the image at `[1, 2)` followed by `after\n`: the tab is gone and the image is kept.

**Cleanup:** `delete_file` the doc.

**Result (2026-10-27) ✅ PASS**
Run against PR #1110's merge in an isolated service-account sandbox on a Shared Drive. Step 1: runs `\t`, `inlineObject` `[2,3)`, `after\n`; paragraph text `"\tafter\n"`. Third paragraph: `X`, `inlineObject` `[21,22)`, ` `, `inlineObject` `[23,24)`, `Y\n`. All three IDs match the raw `inlineObjects` keys. `plain text\n` has one run with no `type` key. Step 2 left `[1,8) '\tafter\n'`. Step 3 left `[1,2)` image then `after\n`. Doc trashed.

---

## Blank paragraph before a table (#1092)

### TC-DOC240: The blank paragraph Docs leaves before a table is collapsed NORMAL_TEXT, not a second heading (#1092) ⚠️ destructive
**Purpose:** Docs inserts a table after an empty paragraph, which inherits the style of the block before it. The collapse request now also sets `namedStyleType: NORMAL_TEXT`. This case also checks the other blocks that could leak their style into that paragraph.

**Setup:** fixtures in `docs/qa/fixtures/`:
- `tc-doc240-heading.md`: `## Decisions`, a blank line, a `| Item | Choice |` table with two body rows (3 rows × 2 columns), then `After the table.`
- `tc-doc240-normal.md`: `Intro paragraph.`, then a table with one body row (2 × 2).
- `tc-doc240-bullet.md`: `- one` / `- two`, then the same 2 × 2 table.
- `tc-doc240-quote.md`: `> quoted line`, then the same 2 × 2 table.
- `tc-doc240-seed.md`: one line, `Seed line.`

1. `create_doc_from_file` each of the four table fixtures into `{FOLDER_ID}`.
2. `create_doc_from_file(local_path=docs/qa/fixtures/tc-doc240-seed.md, folder_id={FOLDER_ID})`, then `update_doc_from_file(doc_id=<it>, local_path=docs/qa/fixtures/tc-doc240-heading.md)`.

**Checks** (raw `documents().get()` per Doc)
- `tc-doc240-heading.md`, both from step 1 and from the step 2 update: a `HEADING_2` "Decisions", then one `NORMAL_TEXT` blank paragraph with `spaceAbove`/`spaceBelow` 0, `lineSpacing` 1 and a 1pt `fontSize` on its newline, then the table. There's no second, empty heading.
- Every table cell paragraph is `NORMAL_TEXT`, so a `#decisions` anchor can only resolve to the heading.
- The paragraph after the heading Doc's table, `After the table.`, is a plain `NORMAL_TEXT` paragraph.
- `tc-doc240-normal.md`: the blank paragraph has the same collapse.
- `tc-doc240-bullet.md`: the blank paragraph has no `bullet`.
- `tc-doc240-quote.md`: the blank paragraph has no `borderLeft` or `indentStart`.

**Cleanup:** `delete_file` each doc.

**Result (2026-10-27) ✅ PASS**
Run against PR #1138's merge in an isolated service-account sandbox on a Shared Drive. Every check matched for all five Docs. The blank paragraph read `NORMAL_TEXT`, `spaceAbove`/`spaceBelow` 0pt, `lineSpacing` 1, newline `fontSize` 1pt, with no `bullet`, `borderLeft` or `indentStart`. Every cell paragraph of the heading table, created or updated, is `NORMAL_TEXT`, and so is the trailing paragraph. Read through the API only, not on screen. Docs trashed. (This run's inputs were written by hand before the fixtures were committed; the run below uses the fixtures.)

**Result (2026-10-29) ✅ PASS — PR #1274 send-back round (Jay), committed fixtures**
`mcp-gee-sweet-jay` (OAuth) at `develop` b2f868f2's code, in `{FOLDER_ID}`, raw `documents().get()` from a fresh interpreter. In all five Docs, the paragraph before the table is `NORMAL_TEXT` with `spaceAbove`/`spaceBelow` 0pt, `lineSpacing` 1 and newline `fontSize` 1pt, with no `bullet`, `borderLeft` or `indentStart`. Both heading Docs (created, and updated from the seed) read `HEADING_2` "Decisions", the blank paragraph, a 3 × 2 table, then `After the table.` as `NORMAL_TEXT`. All 6 cell paragraphs per Doc (12 across the two) are `NORMAL_TEXT`. The bullet Doc's items keep their own list, and the quote Doc's border stays on `quoted line`. Docs trashed.

---

## Link targets without a URI scheme (#1120)

### TC-DOC241: A scheme-less link target lands as plain text and is reported; a host-only one is linked over https; schemed targets land as written (#1120, #1180) ⚠️ destructive
**Purpose:** Docs turned a relative target like `./guide.md` into a dead `http://./guide.md` link. The converter now keeps a target that starts with `#` or has a scheme, and rewrites a scheme-less one that names a host (`//host/x`, `www.host`) to `https://` (#1180). It writes any other target's run as plain text and lists the target under `dropped_links` with `reason: "no_scheme"`. TC-MD111 LK-12 covers the Markdown suite's case. This one covers each entry point, a range of schemes, padded targets and table cells.

**Setup:** fixtures in `docs/qa/fixtures/`:
- `tc-doc241-links.md`: a `## Target heading`, then one paragraph per link with targets `./guide.md`, `/guide.md`, `//example.com/x`, `HTTPS://Example.com`, `Mailto:qa@example.com`, `tel:+15555550100`, `ftps://example.com/f`, `file:///tmp/qa.txt`, `vscode://file/tmp/qa.txt`, `javascript:alert(1)`, `data:text/plain,hi`, `vbscript:msgbox`, `https://example.com/ok`, an image linked to `https://example.com/imglink` and `#target-heading`. Then a table whose cells hold `[cell anchor](#target-heading)` and `[cell rel](./guide.md)`.
- `tc-doc241-links.html`: an `<h2>`, then `<a>` targets `./guide.md`, `/guide.md`, `//example.com/x`, `" https://example.com/x "` (padded), `https://example.com/ok` and `#target-heading`.
- `tc-doc241-write.md`: links to `./guide.md`, `/guide.md`, `//example.com/x` and `https://example.com/ok`.

1. `create_doc_from_file` each of `tc-doc241-links.md` and `tc-doc241-links.html` into `{FOLDER_ID}`.
2. `create_doc(title="QA-TC-DOC241-write", folder_id={FOLDER_ID})`, then `write_doc_content(doc_id=<it>, content=<tc-doc241-write.md's text>, content_format="markdown")`.

**Checks** (raw `documents().get()`)
- `./guide.md`, `/guide.md` and the table cell's `cell rel` are plain text with their link text kept and no `link`, through all three entry points.
- Each of the three calls returns `dropped_links` of exactly `[{"url": "./guide.md", "reason": "no_scheme"}, {"url": "/guide.md", "reason": "no_scheme"}]`. The list holds distinct targets, so `cell rel`'s `./guide.md` shares the body link's entry.
- `//example.com/x` is linked as `https://example.com/x` through all three entry points, and isn't in `dropped_links`.
- `HTTPS://Example.com`, `Mailto:qa@example.com`, `tel:+15555550100`, `ftps://example.com/f`, `vscode://file/tmp/qa.txt`, `https://example.com/ok` and the image link `https://example.com/imglink` are stored exactly as written, and no call fails.
- The padded HTML target is stored as `https://example.com/x`.
- Both `#target-heading` anchors (body and table cell) resolve to the heading's `headingId`.
- The linked image keeps its link.
- Observation only, not a PASS/FAIL check: record what `file:///tmp/qa.txt`, `javascript:alert(1)`, `data:text/plain,hi` and `vbscript:msgbox` become. Whether the script schemes should be stored is #1189's question (now bundled in #1238), so this case doesn't judge it.

**Cleanup:** `delete_file` each doc.

**Result (2026-10-27) ✅ PASS (pre-#1228/#1272 code, superseded by the run below)**
Run against PR #1149's merge in an isolated service-account sandbox on a Shared Drive. `./guide.md`, `/guide.md`, `//example.com/x` and `cell rel` are plain text with no `link` through all three entry points. Stored as written: `HTTPS://Example.com`, `Mailto:qa@example.com`, `tel:+15555550100`, `ftps://example.com/f`, `file:///tmp/qa.txt`, `vscode://file/tmp/qa.txt`, `https://example.com/ok`, and the image link `https://example.com/imglink`. The padded HTML target is stored as `https://example.com/x`. Both anchors became `…/edit?tab=t.0#heading=<the heading's headingId>`, the heading's own ID. Docs also stores `javascript:alert(1)`, `data:text/plain,hi` and `vbscript:msgbox` as written, with no API error. That's recorded for the script-scheme policy (#1189), not as a failure here. Whether Docs opens each scheme from the UI wasn't checked. Docs trashed.

**Result (2026-10-29) ✅ PASS — PR #1274 send-back round (Jay), committed fixtures**
`mcp-gee-sweet-jay` (OAuth) at `develop` b2f868f2's code, in `{FOLDER_ID}`, raw `documents().get()` from a fresh interpreter. All three calls returned no error and `dropped_links` `[{"url": "./guide.md", "reason": "no_scheme"}, {"url": "/guide.md", "reason": "no_scheme"}]`. `relative`, `root relative` and `cell rel` are plain text with no `link` in every Doc. `protocol relative` is linked to `https://example.com/x` in all three. Stored as written: `HTTPS://Example.com`, `Mailto:qa@example.com`, `tel:+15555550100`, `ftps://example.com/f`, `vscode://file/tmp/qa.txt`, `https://example.com/ok`, and the image link `https://example.com/imglink`. The padded HTML target is stored as `https://example.com/x`. Both Markdown anchors and the HTML anchor became `…/edit?tab=t.0#heading=<the heading's headingId>`, the Doc's own heading. Observation: in the Markdown Doc, `file:`, `javascript:`, `data:` and `vbscript:` aren't links at all. markdown-it's `validateLink` refuses those schemes, so each paragraph holds its literal Markdown source, e.g. `[file](file:///tmp/qa.txt)`. Docs trashed.

**Result (2026-10-29) ✅ PASS — PR #1274 QA round 2 (Rio), committed fixtures**
`mcp-gee-sweet-rio` (OAuth) at PR head 68f2dc91, whose `src/` matches `develop` b2f868f2. The Docs went into the Shared Drive default folder, and the raw `documents().get()` came from a fresh interpreter. All three calls returned no error and `dropped_links` exactly `[{"url": "./guide.md", "reason": "no_scheme"}, {"url": "/guide.md", "reason": "no_scheme"}]`. `relative`, `root relative` and `cell rel` are plain text with no `link`. `protocol relative` is linked to `https://example.com/x` in all three Docs, and the padded HTML target is stored as `https://example.com/x`. Stored as written: `HTTPS://Example.com`, `Mailto:qa@example.com`, `tel:+15555550100`, `ftps://example.com/f`, `vscode://file/tmp/qa.txt`, `https://example.com/ok`, and the image link `https://example.com/imglink`. The Markdown body anchor, the cell anchor and the HTML anchor each became `…/edit?tab=t.0#heading=<the heading's headingId>`, the Doc's own `HEADING_2`. Observation: same as the run above. `file:`, `javascript:`, `data:` and `vbscript:` paragraphs hold their literal Markdown source, now tracked as #1290. Docs trashed.

---

## Loose lists (#1111)

### TC-DOC242: A loose list (blank lines between items) keeps its bullets, numbers, levels and checkboxes (#1111) ⚠️ destructive
**Purpose:** The Markdown parser wraps each loose item's text in `<p>`, and that `<p>` used to end the item, so the text landed as a plain paragraph. An item's first `<p>` is now part of the item.

**Setup:** fixtures in `docs/qa/fixtures/`:
- `tc-doc242-loose.md`: these groups, separated by `---`: `- a\n\n- b`; `1. a\n\n2. b`; `> - a\n>\n> - b`; `- a\n    - a1\n\n- b`; `- [x] done\n\n- [ ] todo`; and the tight `- t1\n- t2`.
- `tc-doc242-loose.html`: `<ul><li>\n  <p>a</p>\n</li><li>\n  <p>b</p>\n</li></ul>`, then `<ul><li><p data-style="subtitle">styled</p></li><li>plain</li></ul>`.

1. `create_doc_from_file` each fixture into `{FOLDER_ID}`.

**Checks** (`get_doc_structure` plus raw `documents().get()`)
- `- a\n\n- b` is two items in one bullet list, and `1. a\n\n2. b` is one `DECIMAL` list.
- The quoted list is one list whose paragraphs carry the quote's left border.
- `- a / a1 / b` is one list with levels 0, 1, 0.
- The task items read `☑ done` and `☐ todo`.
- The tight list is unchanged: two items in one list.
- No empty paragraph sits between the items of any list. In the Markdown Doc, the only empty paragraphs are the five `---` separators and the body's final paragraph, which every Doc ends with. In the HTML Doc, the only one is the body's final paragraph.
- Item text is `a\n` and `b\n`, with no leading or trailing newline, tab or space from the HTML's indentation (`tc-doc242-loose.html` included).
- The `data-style` item is a `SUBTITLE` paragraph with no bullet, as before #1164 (its `NamedBlock` keeps its own block).

**Cleanup:** `delete_file` each doc.

**Result (2026-10-27) ✅ PASS**
Run against PR #1164's merge in an isolated service-account sandbox on a Shared Drive. Every check matched, through the API only. `loose.md`'s items read `a\n`/`b\n` (●), `a\n`/`b\n` (DECIMAL), `a\n`/`b\n` with a left border at indent 72pt, `a`/`a1`/`b` at levels 0/1/0, then `☑ done`/`☐ todo` and `t1`/`t2`. Each group shares one `listId`, and the only empty paragraphs are the five separators and the body's final paragraph. In `loose.html`, `a\n`/`b\n` are one list with no padding, and `styled` is a bare `SUBTITLE` paragraph. #1115's on-screen done-when (the TC-MD cases through EP-1 to EP-4) is not covered here and stays pending in its tracking issue. Docs trashed.

**Result (2026-10-29) ✅ PASS — PR #1274 send-back round (Jay), committed fixtures**
`mcp-gee-sweet-jay` (OAuth) at `develop` b2f868f2's code (markdown-it), in `{FOLDER_ID}`, raw `documents().get()` from a fresh interpreter. `tc-doc242-loose.md`: `a\n`/`b\n` (●), `a\n`/`b\n` (`DECIMAL`), `a\n`/`b\n` with a left border at `indentStart` 72pt, `a`/`a1`/`b` at levels 0/1/0, `☑ done`/`☐ todo`, then `t1`/`t2`. Each group has a `listId` of its own shared by its items, and the only empty paragraphs are the five separators and the body's final paragraph. `tc-doc242-loose.html`: `a\n`/`b\n` in one list with no padding, `styled` a `SUBTITLE` paragraph with no bullet, `plain` a bullet item, then the final empty paragraph. Docs trashed.

---

## Conversion before the replace (#1240)

### TC-DOC243: A replace converts its content before it touches the doc, and an unresolved image's request is dropped with its link ⚠️ destructive
**Purpose:** `write_doc_content` and `update_doc_from_file` used to copy and clear the doc before they converted the new Markdown, so a conversion that raised or was cancelled left the doc empty. Without a backup (`allow_no_backup=True`, or a `_no_backup_reason` case), nothing could restore it. The whole Markdown → HTML → AST → requests conversion now runs first, in one `asyncio.to_thread` call. Requests are now built before images resolve, with a placeholder for every image; an image that fails to resolve has its request and its link request dropped (part A). No input is known to make the conversion raise, so parts B and C inject the failure from a scratch script against the checkout under test, the way TC-DOC219 part B does.

Run on a server whose account can own a copy of `{DOC_ID}` (see TC-DOC219).

**Setup:** `write_doc_content(doc_id={DOC_ID}, content="<p>TC-DOC243 before</p>")`. Note the doc's `name` from `get_file_metadata(file_id={DOC_ID})`.

**Steps (part A, tool calls)**
1. `write_doc_content(doc_id={DOC_ID}, content_format="markdown", content="# TC-DOC243 A\n\n[![Logo](https://www.google.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png)](https://example.com/good-link)\n\n[![Missing](/tmp/tc-doc243-missing.png)](https://example.com/bad-link)\n\nAfter the images.\n")`
2. `get_doc_as_markdown(doc_id={DOC_ID})`

**Steps (part B, a conversion that raises; scratch script, same OAuth token as the server under test)**

3. Run, with `{DOC_ID}` filled in, once with `ALLOW=0` and once with `ALLOW=1`:
```
ALLOW=0 uv run python3 -c "
import asyncio, os, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
creds = auth._oauth_creds()
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=creds),
    drive_service=build('drive', 'v3', credentials=creds), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
with patch.object(c, '_convert_doc_content', side_effect=RuntimeError('injected parser failure')):
    print(asyncio.run(c._replace_doc_content(lc, '{DOC_ID}', '# never written', 'markdown',
        autolink_urls=True, revoke_sharing=True, auto_downscale=False,
        allow_no_backup=os.environ['ALLOW'] == '1')))
"
```
4. `refresh_cache(doc_id={DOC_ID})`, `get_doc_as_markdown(doc_id={DOC_ID})`, and `search_files(query="<name> (backup before replace)")`

**Steps (part C, a conversion cancelled mid-parse)**

5. Run, with `{DOC_ID}` filled in:
```
uv run python3 -c "
import asyncio, time, mcp_gee_sweet
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
creds = auth._oauth_creds()
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=creds),
    drive_service=build('drive', 'v3', credentials=creds), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
real = c._convert_doc_content
def slow(*args):
    time.sleep(3)
    return real(*args)
async def main():
    with patch.object(c, '_convert_doc_content', slow):
        try:
            await asyncio.wait_for(c._replace_doc_content(lc, '{DOC_ID}', '# never written',
                'markdown', autolink_urls=True, revoke_sharing=True, auto_downscale=False,
                allow_no_backup=True), 1)
        except TimeoutError:
            print('cancelled')
asyncio.run(main())
"
```
6. Repeat step 4.

**Checks**
- Step 1 returns `docId` and `web_link` with no `error`. Its `images` has two entries: the logo with no `error`, and `/tmp/tc-doc243-missing.png` with `error` "No file found at '/tmp/tc-doc243-missing.png'" and `fallback_text` "Missing" (#1099)
- Step 2 shows the "TC-DOC243 A" heading, the logo image linked to `https://example.com/good-link`, then the text "Missing" linked to `https://example.com/bad-link` where the missing image was (#1099: its alt text stands in for it, with its link), then "After the images.". `bad-link` is on "Missing" only, not on the text around it. Before #1099 this check expected an empty paragraph and no `bad-link` at all; the 2026-10-29 and 2026-10-30 results below ran against that
- Both step 3 runs print `{'error': "Couldn't convert the content, so the document was left unchanged: RuntimeError: injected parser failure", 'docId': '{DOC_ID}'}`
- Step 4 shows step 2's content unchanged, and `search_files` finds no backup copy: nothing was copied
- Step 5 prints `cancelled`, and step 6 shows step 2's content unchanged with no backup copy

**Cleanup:** `write_doc_content(doc_id={DOC_ID}, content="<p>TC-DOC243 done</p>")`

**Result (2026-10-29) ✅ PASS — PR #1296 round 1 (Kit)**
`mcp-gee-sweet-kit` at 38f7131e, reconnected after the reset. Run on a scratch doc that this account owns, in `{FOLDER_ID}` (Shared Drive), instead of `{DOC_ID}`, so this destructive case couldn't collide with another QA shard. Parts B and C ran from scripts in this worktree (the printed module path confirmed the PR's `content.py`). Part A: step 1 returned no `error`; `images` held the logo (no `error`) and the missing path with "No file found at '/tmp/tc-doc243-missing.png'". Step 2 showed the heading, the logo linked to `https://example.com/good-link`, an empty paragraph where the dropped image was, then "After the images."; `bad-link` appeared nowhere. Part B: both `ALLOW=0` and `ALLOW=1` printed the expected `{'error', 'docId'}`; step 4 showed part A's content unchanged and found no backup copy. Part C printed `cancelled`, and the doc was again unchanged, with no backup copy. Extra cases: `_create_doc_with_content` with the same injected failure returned "Couldn't convert the content, so no document was created: RuntimeError: injected parser failure", and `search_files` found no doc. `update_doc_from_file` with a file containing an ordered list with a nested bullet, a table (one cell with a missing local image plus text, one with the logo), a missing linked image before " between [link](#heading)", and a tail paragraph: the list kept 1/2 around the nested bullet, the cell kept "cell text" and embedded the logo, " between" carried no link (the dropped image's `bad-link` didn't land on it), and the anchor resolved to `#heading=`. The scratch doc was trashed, and no backup copy was left behind.

**Result (2026-10-30) ✅ PASS — PR #1296 round 2 (Kit)**
`mcp-gee-sweet-kit` at daaa92eb, reconnected after the reset, on a scratch doc in `{FOLDER_ID}` as in round 1. Part A: same as round 1, with the logo embedded, the missing image reported in `images` with its error, an empty paragraph where it was, and no link on any text run. A fresh-interpreter rerun of parts B (`ALLOW=1`) and the create-path injection now also logs `ERROR mcp_gee_sweet.tools.docs.content Converting doc content failed (<outcome>)` with the traceback, before the same `{'error', ...}` result. Scratch doc trashed, no backup copy left.

**Result (2026-10-31) ✅ PASS (part A only) — PR #1310 round 1 (Kit)**
`mcp-gee-sweet-kit` at c136f679, reconnected after the reset, on a scratch doc in `{FOLDER_ID}`. Steps 1–2 under the #1099 checks: the logo embedded with no `error`, `/tmp/tc-doc243-missing.png` reported with `error` "No file found at '/tmp/tc-doc243-missing.png'" and `fallback_text` "Missing", and `get_doc_as_markdown` shows `[Missing](https://example.com/bad-link)` between the logo and "After the images.", with no link on the surrounding text. Parts B and C weren't rerun: this PR doesn't change the conversion-first path they inject into. Scratch doc trashed.

### TC-DOC244: A file's relative image path resolves against the file, and a replace uploads its local images to folder_id, the server default, or the doc's own folder (#1121, #1139) ⚠️ requires-oauth ⚠️ destructive
**Purpose:** `create_doc_from_file`/`update_doc_from_file` resolved a relative image path against the server's working directory, so a README's images never embedded (#1121). `update_doc_from_file` had no `folder_id`, so on a server with no default folder every local image failed after the doc was cleared, leaving it without its images (#1139). A relative path is now joined to the file's own folder; `write_doc_content`/`update_doc_from_file` take `folder_id`, fall back to the server's default folder and then to the doc's own folder, and refuse before touching the doc when none is known. The doc's-folder fallback only runs on a server with no `DRIVE_FOLDER_ID`, so parts B and C use a scratch script against the checkout under test with `folder_id=None`, the way TC-DOC243 part B does.

**Playwright: required**

**Setup:** `create_doc(title="TC-DOC244 scratch", folder_id={FOLDER_ID}, content="<p>TC-DOC244 before</p>")`; call its `docId` `{SCRATCH}`. `F` = `{REPO}/docs/qa/fixtures/md/tc-doc244/relative-image.md`, which embeds `../../qa-fixture-pixel.png`.

**Steps (part A, tool calls)**
1. `update_doc_from_file(doc_id={SCRATCH}, local_path=F, folder_id={FOLDER_ID})`
2. `get_doc_as_markdown(doc_id={SCRATCH})`, and `get_file_metadata(file_id=<step 1's images[0].fileId>)`
3. `create_doc_from_file(local_path=F, title="TC-DOC244 create", folder_id={FOLDER_ID})`, then `get_doc_as_markdown` on its `docId`

**Steps (part B, the doc's own folder; scratch script, same OAuth token as the server under test)**

4. Run, with `{SCRATCH}` and `{REPO}` filled in:
```
uv run python3 -c "
import asyncio, mcp_gee_sweet
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from googleapiclient.discovery import build
from mcp_gee_sweet import auth
from mcp_gee_sweet.tools.docs import content as c
creds = auth._oauth_creds()
lc = SimpleNamespace(docs_service=build('docs', 'v1', credentials=creds),
    drive_service=build('drive', 'v3', credentials=creds), doc_cache=MagicMock(),
    drive_folder_cache=MagicMock(), folder_id=None)
F = '{REPO}/docs/qa/fixtures/md/tc-doc244/relative-image.md'
print(asyncio.run(c._replace_doc_content(lc, '{SCRATCH}', Path(F).read_text(), 'markdown',
    autolink_urls=True, revoke_sharing=True, auto_downscale=False, allow_no_backup=False,
    source_dir=Path(F).parent)))
"
```
5. `get_file_metadata(file_id=<step 4's images[0].fileId>)`

**Steps (part C, no folder known)**

6. Run step 4's script with one change: before `print`, add `c._doc_parents = lambda *a: asyncio.sleep(0, result=None)` (a doc shared from a folder this account can't see has no parents).
7. `refresh_cache(doc_id={SCRATCH})`, `get_doc_as_markdown(doc_id={SCRATCH})`, and `search_files(query="TC-DOC244 scratch (backup before replace)")`

**Checks**
- Step 1 returns `docId` with no `error`; `images` has one entry, `src` `../../qa-fixture-pixel.png`, with a `fileId` and no `error`
- Step 2 shows the "TC-DOC244" heading, "Before the image.", the 1×1 pixel image, and "After the image."; the uploaded pixel's `parents` is `[{FOLDER_ID}]`
- Step 3: the same content in the new doc, the pixel embedded, its `images` entry with no `error`
- Step 4 prints a result with no `error` and one `images` entry with a `fileId`; step 5 shows that file's `parents` is `{FOLDER_ID}`, the scratch doc's own folder
- Step 6 prints `{'error': "The content has a local image, but there's no Drive folder to upload it to: ... Pass folder_id. The document was left unchanged.", 'docId': '{SCRATCH}'}`
- Step 7 shows step 4's content unchanged, and `search_files` finds no backup copy: the call stopped before copying or clearing

**Cleanup:** `delete_file` the scratch doc, step 3's doc, and each uploaded `qa-fixture-pixel.png` copy in `{FOLDER_ID}` (steps 1, 3 and 4)

**Result (2026-10-31) ✅ PASS — PR #1310 round 1 (Kit)**
`mcp-gee-sweet-kit` at c136f679, reconnected after the reset, OAuth, with `{FOLDER_ID}` a folder inside the Shared Drive. Part A: step 1 returned one `images` entry (`src` `../../qa-fixture-pixel.png`, a `fileId`, no `error`); step 2 showed the heading, "Before the image.", the pixel and "After the image." in that order, and the uploaded pixel's `parents` was `[{FOLDER_ID}]`; step 3's new doc had the same content with the pixel embedded. Part B (fresh interpreter, `folder_id=None`): no `error`, one `images` entry, and its file's `parents` was the scratch doc's own folder. Part C printed the expected refusal ending "Pass folder_id. The document was left unchanged."; after `refresh_cache`, the doc still showed part B's content and `search_files` found no backup copy. Playwright (account check passed against the fixture doc's title): the scratch doc shows the heading, both paragraphs and the 1×1 pixel between them. All scratch docs and the three uploaded pixels trashed.

**Result (2026-10-31) ⚠️ PARTIAL — PR #1310 round 2 (Kit), the fix commit's refusal changes only**
Fresh interpreter against f6307b59. A missing local image (`/tmp/kit-nope.png`) with no folder known no longer refuses: the replace goes ahead and writes "gone" in its place, with `error` and `fallback_text` in `images`. `_doc_parents` now returns `(parents, error)` instead of raising: on a real doc it returned the doc's folder. But a nonexistent `doc_id` with an existing local image returns the "no Drive folder to upload it to … looking up the document's own folder failed (<HttpError 404 … File not found …>). Pass folder_id." refusal, which names the wrong problem (sent back). Parts A–C weren't rerun; the fix doesn't change their paths.

**Result (2026-10-31) ✅ PASS (the round-3 unreachable-doc fix) — PR #1310 round 3 (Kit)**
Fresh interpreter against eb6ce267, `folder_id=None`, with an existing local image and `doc_id='bogusDocIdDoesNotExist123'`: returns `{'error': "Couldn't read the document (it doesn't exist, or this account can't open it), so it was left unchanged: <HttpError 404 … File not found …>", 'docId': …}` instead of the folder refusal. Parts A–C weren't rerun; the fix doesn't change their paths.
