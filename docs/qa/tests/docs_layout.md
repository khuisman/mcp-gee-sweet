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

**Result (2026-09-04) ✅ PASS**
create_header (no content) -> {docId, headerId:"kix.4yrlc2k9cy3n"} non-empty; no error. Visual 🔍 not verified (browser unauth; headers also not visible in body snapshot per run.md limitation).

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

**Result (2026-09-04) ✅ PASS**
create_header content "Confidential — Internal Only" -> {docId, headerId} (same id via documentStyle fallback since header already existed); no error/warning key. Visual 🔍 not verified.

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

**Result (2026-09-04) ✅ PASS**
create_footer (no content) -> {docId, footerId:"kix.khcu7s4gsbju"} non-empty; no error. Visual 🔍 not verified.

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

**Result (2026-09-04) ✅ PASS**
create_footer content "Page 1" -> {docId, footerId}; no error/warning. Visual 🔍 not verified.

---

### TC-DOC72: Invalid header_type returns error
**Prompt**
> "Call create_header on doc {DOC_ID} with header_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid header_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid header_type 'INVALID'. Use DEFAULT or FIRST_PAGE_HEADER"}`. No API call made.

**Result (2026-09-04) ✅ PASS**
create_header header_type='INVALID' -> {"error":"Invalid header_type 'INVALID'. Use DEFAULT or FIRST_PAGE_HEADER"}; no API call.

---

### TC-DOC73: Invalid footer_type returns error
**Prompt**
> "Call create_footer on doc {DOC_ID} with footer_type 'INVALID'"

**Checks**
- Returns `{"error": "Invalid footer_type 'INVALID'..."}`

**Result (2026-06-22) ✅ PASS** Returned `{"error": "Invalid footer_type 'BOGUS'. Use DEFAULT or FIRST_PAGE_FOOTER"}`. No API call made.

**Result (2026-09-04) ✅ PASS**
create_footer footer_type='INVALID' -> {"error":"Invalid footer_type 'INVALID'. Use DEFAULT or FIRST_PAGE_FOOTER"}; no API call.

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

**Result (2026-09-04) ✅ PASS**
insert_doc_text index 0, segment_id headerId -> {docId, insertions:1}; no API error. Visual 🔍 not verified.

---

