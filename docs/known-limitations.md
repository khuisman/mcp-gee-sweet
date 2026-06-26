# Known Limitations

Constraints imposed by the Google Docs/Drive/Sheets APIs or by current implementation scope.
Each entry describes what the limitation is, why it exists, and the available workaround (if any).

---

## Google Docs

### Blank paragraph before every table

**What:** A blank paragraph always appears in the document structure immediately before each
table, even when none was written in the source HTML/Markdown.

**Why:** `insertTable` is a structural Docs API operation that requires at least one paragraph
before the table. When phase-1 `insertText` is used to write document content, it displaces the
document's initial empty paragraph to the position just before the table. Attempting to remove
this paragraph via `deleteContentRange` is rejected by the API ("Invalid deletion range") because
the paragraph is a required structural element — even though the Google Docs UI allows the
equivalent manual deletion.

**Workaround:** The emitter collapses the blank paragraph to zero visual height using
`updateParagraphStyle` (`spaceAbove/spaceBelow = 0`, `lineSpacing = 1`) and `updateTextStyle`
(`fontSize = 1pt`). The paragraph remains in the document structure but is invisible in the
rendered output. Related: #190.

---

### `get_doc_structure` — top-level body elements only

**What:** `get_doc_structure` reports elements in the document body at the top level only.
Content inside nested table cells (tables within table cells) is not exposed.

**Why:** The tool walks the body content array one level deep. Deeply nested structures require
recursive traversal that is not currently implemented.

**Workaround:** For inspecting nested cell content, fetch the raw document via the Docs API
`documents.get` endpoint (accessible via `batch_update` passthrough or by reading the raw API
response). Related: #133.

---

## Google Drive

### Service account cannot create files in personal Drive

**What:** When authenticated as a service account (`AUTH_METHOD=service_account`), tools that
create new files (`create_doc`, `create_doc_from_file`, `create_spreadsheet`) will fail with a
permission error if the target folder is in a personal Google Drive.

**Why:** Service accounts have their own Drive storage quota separate from any user's personal
Drive. They can only create files in shared drives or in folders explicitly shared with the
service account.

**Workaround:** Manually create the file in Drive and share it with the service account, then
use `write_doc_content` or `update_cells` to populate it. Alternatively, use OAuth authentication
(`AUTH_METHOD=oauth`) which authenticates as the user and has full personal Drive access.
Related: project memory `service_account_limit`.

---

## Calendar

### `list_all_events` — async/httplib2 thread-safety blocker

**What:** `list_all_events` (fetching events across multiple calendars concurrently) is blocked
on a thread-safety issue: the Google API Python client uses `httplib2` internally, and `httplib2`
connections are not safe to share across threads.

**Why:** The implementation uses `ThreadPoolExecutor` to fan out calendar queries in parallel.
Each thread needs its own HTTP connection, but reconstructing a full authorized service per
thread via `build_from_document` + `google_auth_httplib2.AuthorizedHttp` adds significant
overhead and complexity (Frankenstein code) rather than working cleanly through the SDK.

**Workaround:** Use `list_events` per calendar individually. The `list_all_events` tool exists
but may have reliability issues under concurrent load until #183 (async/httplib2 strategy) is
resolved. Related: #194, #183.
