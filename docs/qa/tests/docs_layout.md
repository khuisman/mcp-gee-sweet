# Docs Tools — Layout (Headers/Footers) — QA Test Cases

Source: `src/mcp_gee_sweet/tools/docs/layout.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{DOC_ID}` from `fixtures.local.md`.

---

## `create_header` / `create_footer` (#147)

### TC-DOC68: Create a default page header ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page header to doc {DOC_ID}"

**Checks**
- Call succeeds with no API error
- Response contains `docId` and `headerId` (non-empty string)
- 🔍 Visual check in Google Docs: document shows a header section

**Cleanup:** none needed (headers persist; restore fixture doc if desired)

**Result (2026-06-22) ✅ PASS** Called `create_header(doc_id=fixture)` (no content). Returned `{"docId": ..., "headerId": "kix.xxxxxxxxxx"}`. Header section visible in Google Docs. Note: on first call after a prior session created the header (due to index=1 bug), the "already exists" 400 error was caught and the ID was retrieved from `documentStyle.defaultHeaderId` — this is the expected fallback path.

---

### TC-DOC69: Create a header with content ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page header to doc {DOC_ID} with content 'Confidential — Internal Only'"

**Checks**
- Response contains `docId` and `headerId`
- Two API calls were made (create + insert text) — verifiable via no error in response
- 🔍 Visual check: header text "Confidential — Internal Only" appears in the document header

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_header(doc_id=temp_doc, content="Confidential — Internal Only")`. Returned `{"docId": ..., "headerId": "kix.xxxxxxxxxx"}` with no `warning` key — both header creation (via `documentStyle` fallback) and content insertion at `index=0` succeeded.

---

### TC-DOC70: Create a default page footer ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page footer to doc {DOC_ID}"

**Checks**
- Response contains `docId` and `footerId` (non-empty string)
- 🔍 Visual check: document shows a footer section

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_footer(doc_id=fixture)`. Returned `{"docId": ..., "footerId": "kix.xxxxxxxxxx"}`. Footer section visible in Google Docs.

---

### TC-DOC71: Create a footer with content ⚠️ destructive
**Prompt**
**Playwright: required**
> "Add a page footer to doc {DOC_ID} with content 'Page 1'"

**Checks**
- Response contains `docId` and `footerId`
- 🔍 Visual check: footer shows "Page 1"

**Cleanup:** none needed

**Result (2026-06-22) ✅ PASS** Called `create_footer(doc_id=temp_doc, content="Page 1")`. Returned `{"docId": ..., "footerId": "kix.xxxxxxxxxx"}` with no `warning` key — footer created and content inserted at `index=0`.

---

### TC-DOC72: Invalid header_type returns error
**Prompt**
> "Call create_header on doc {DOC_ID} with header_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid header_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid header_type 'INVALID'. Use DEFAULT or FIRST_PAGE_HEADER"}`. No API call made.

---

### TC-DOC73: Invalid footer_type returns error
**Prompt**
> "Call create_footer on doc {DOC_ID} with footer_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid footer_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid footer_type 'BOGUS'. Use DEFAULT or FIRST_PAGE_FOOTER"}`. No API call made.

---

### TC-DOC74: insert_doc_text with segment_id writes into header ⚠️ destructive
**Setup:** call `create_header` first to get a `headerId`

**Prompt**
**Playwright: required**
> "Insert the text 'Header text via insert_doc_text' at index 0 in doc {DOC_ID} using segment_id '{headerId}'"

**Note:** An empty header/footer segment has end index 1 (one newline at index 0). Insert at index 0, not 1.

**Checks**
- Call succeeds with no API error
- Response contains `insertions: 1`
- 🔍 Visual check: "Header text via insert_doc_text" appears in the document header

**Result (2026-06-22) ✅ PASS** Called `insert_doc_text` with `[{index: 0, text: "QA Test Header", segment_id: "kix.xxxxxxxxxx"}]`. Response: `{"docId": ..., "insertions": 1}`. Text "QA Test Header" appeared in fixture doc header. Same mechanism also confirmed for footer segment insertion (segment_id: "kix.xxxxxxxxxx", text: "Page 1").

---

### TC-DOC75: `get_doc_named_styles` reads named style defaults set via the Docs UI
**Note:** Named styles are only populated when the user explicitly goes to Format > Paragraph styles > Update X to match. Most docs leave named styles at Google's defaults — this tool returns empty or near-empty for those docs. Use `get_doc_theme` to read actual paragraph appearance instead.

**Prompt**
> "Call `get_doc_named_styles` on doc {DOC_ID} and show me the result."

**Checks**
- No `error` key in result
- For a doc where named styles were explicitly set: returns a non-empty dict with named style type keys
- For a standard doc: may return `{}` or only Google's default entries (expected, not an error)

**Result (2026-06-20) ✅ PASS** Called on a doc that had `apply_theme` previously applied (Georgia HEADING_1/H2, Roboto NORMAL_TEXT). Returned 9 entries: NORMAL_TEXT (Roboto 11pt, line_spacing 115), HEADING_1 (Georgia 24pt bold, space_above 20), HEADING_2 (Georgia 18pt, space_above 18), HEADING_3–6 (Google defaults with font sizes and colors), TITLE, SUBTITLE. Confirms `apply_theme` default mode successfully writes to named styles, and `get_doc_named_styles` reads them back correctly. No error.

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

---

### TC-DOC80: get_doc_content trips the response-size cap; cached path re-checks it too (issue #242)

**Background:** #242 generalized #235's response-size safety net to `get_doc_content`. `doc_cache` previously returned a cached result *before* any cap check ran, so a cached oversized doc would bypass the cap on repeat calls — fixed so the check runs on both the cache-hit and cache-miss paths.

**Setup:** `TEST_LARGE_DOC_ID` (`mcp-gee-sweet-qa-large-doc`), grown from its original ~5,300-character seed content to ~49,700 characters by inserting repeated padding text (permanent fixture growth — this doc's whole purpose is being a large-content fixture, and it was never previously large enough to exceed any cap since none existed for this tool before now).

**Checks**
- First call (fetch path) raises `ValueError` mentioning the actual response size, the cap, and `MAX_TOOL_RESPONSE_CHARS`
- Second call (cache-hit path, no `refresh_cache` in between) raises the *same* error — proves the cache-hit path re-checks the cap rather than returning the stale oversized cached result
- Same call with `local_path` set succeeds, returns `{local_path, id, bytes_written}`, and the file on disk contains the full content

**Result (2026-07-03) ✅ PASS**
Fetch-path call raised: `get_doc_content: the response is 49700 characters, over the 40000-character safety cap. Pass local_path to write the result to disk instead of returning it inline (bypasses this cap), or set MAX_TOOL_RESPONSE_CHARS if your MCP client can handle larger responses (e.g. a raised MAX_MCP_OUTPUT_TOKENS).` Repeat call (served from `doc_cache`, confirmed via no additional Drive API round-trip) raised the identical error — confirms the cache-ordering fix. `local_path` call succeeded: `{"local_path":"/tmp/qa_doc_content_242.json","bytes_written":49700,"id":"{TEST_LARGE_DOC_ID}"}`; file verified then cleaned up.

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

---

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

---
