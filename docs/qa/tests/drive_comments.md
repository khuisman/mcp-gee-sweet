# Drive Tools — Comments — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive/comments.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}`, `{DOC_ID}`, and `{FOLDER_ID}` from `fixtures.local.md`.

The comment tools call the Drive `comments`/`replies` resource, not the Docs API, so they take any file Drive supports comments on. TC-DOC96–TC-DOC101 moved here from `docs_content.md` with #663, which renamed the tools (`list_doc_comments` → `list_file_comments`, `add_doc_comment` → `add_file_comment`, `doc_id` → `file_id`) and replaced `resolve_doc_comment` with `reply_to_comment(action=)`. They keep their IDs, so earlier results files still point at them; their Result entries before #663 record the old names as they were called. New cases here use `TC-D`.

There is no tool that deletes a comment yet (#664 adds `delete_comment`), so a comment added on `{DOC_ID}` stays there until it's removed in the Docs UI. Keep test comment text prefixed `QA TC-…` so it's identifiable for manual cleanup. TC-D310 works on a throwaway spreadsheet and deletes it instead.

---

## `list_file_comments` / `add_file_comment` / `reply_to_comment` (#151, #663)

### TC-DOC96: Add a comment with no quoted-text anchor ⚠️ destructive
**Prompt**
> `add_file_comment(file_id={DOC_ID}, content="QA TC-DOC96: general note.")`

**Checks**
- Returns `id`, `content` matching the input text, `author` (`display_name`/`email_address` populated from the caller's identity), `created_time`
- `quoted_text` is `null` — no anchor was requested
- No error

**Cleanup:** none available — no tool deletes a comment yet; the comment persists on the fixture doc (see the note at the top)

**Result (2026-07-16) ✅ PASS**
`add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC96: general note.")` returned `id: "AAAB-5FtNYE"`, `content` matching the input, `author.display_name: "<QA user>"`, `created_time`, `quoted_text: null`. No error. Note: `author.email_address` was `null` rather than populated — this is Drive API behavior for the authenticated OAuth user's own comments (email visibility is a privacy-scoped field), not a tool defect; the tool correctly passes through whatever the API returns.

**Result (2026-09-04) ✅ PASS**
add_doc_comment (no anchor) returned id, content match, author.display_name="<QA user>" (email_address null - Drive API privacy behavior, not a defect), created_time, quoted_text:null.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: add_doc_comment returned id, matching content, author.display_name, created_time and quoted_text:null. email_address was null, which is the known Drive privacy behavior.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Run on the fixture copy. Returned id `doco.PHdj…`, matching content, author.display_name, created_time, `quoted_text: null`. `author.email_address` is null (Drive privacy behavior for the caller's own comments, as in prior passes; see stale wording note).

---

### TC-DOC97: Add a comment anchored to quoted text ⚠️ destructive
**Setup:** `{DOC_ID}` must contain the literal text "QA anchor target" somewhere (add it with `insert_doc_text` if absent; `write_doc_content` would replace the whole body)

**Prompt**
> `add_file_comment(file_id={DOC_ID}, content="QA TC-DOC97: anchored note.", quoted_text="QA anchor target")`

**Checks**
- Returns `quoted_text: "QA anchor target"` — the anchor round-trips through the API response
- `list_file_comments` on the same doc shows this comment with the same `quoted_text`

**Cleanup:** none available (see the note at the top)

**Result (2026-07-16) ✅ PASS**
Doc lacked the literal text "QA anchor target", so it was inserted via `insert_doc_text` (not `write_doc_content`, which replaces the whole doc body — using it as the setup note suggests would have wiped the fixture's existing content). `add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC97: anchored note.", quoted_text="QA anchor target")` returned `quoted_text: "QA anchor target"`, round-tripping correctly. Confirmed via `list_doc_comments` in TC-DOC98 below.

**Result (2026-09-04) ✅ PASS**
Inserted "QA anchor target" text via insert_doc_text, then add_doc_comment with quoted_text="QA anchor target" returned quoted_text round-tripped correctly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: I inserted "QA anchor target" with insert_doc_text, then add_doc_comment returned quoted_text "QA anchor target".

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Added "QA anchor target" to the copy with insert_doc_text, then add_doc_comment returned `quoted_text: "QA anchor target"`; list_doc_comments shows the same quoted_text.

---

### TC-DOC98: List comments reflects previously added comments
**Setup:** run TC-DOC96 and TC-DOC97 first

**Prompt**
> `list_file_comments(file_id={DOC_ID})`

**Checks**
- Both the TC-DOC96 and TC-DOC97 comments appear in `comments`
- Each has `resolved: false` and `replies: []`
- The TC-DOC97 entry has `quoted_text: "QA anchor target"`; the TC-DOC96 entry has `quoted_text: null`
- `file_id` in the response matches `{DOC_ID}` (`doc_id` before #663)

**Cleanup:** none (read-only)

**Result (2026-07-16) ✅ PASS**
`list_doc_comments(doc_id=<TEST_DOC_ID>)` returned both comments: TC-DOC97 (`quoted_text: "QA anchor target"`) and TC-DOC96 (`quoted_text: null`), both `resolved: false` and `replies: []`, `doc_id` echoed correctly.

**Result (2026-09-04) ✅ PASS**
list_doc_comments showed both TC-DOC96/97 comments, both resolved:false and replies:[], correct quoted_text values, doc_id matches.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: list_doc_comments listed both comments with resolved:false and replies:[], the correct quoted_text values, and a matching doc_id.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Both comments listed, each `resolved:false`, `replies:[]`; DOC97 entry has the quoted_text, DOC96 entry null; `doc_id` matches the copy.

---

### TC-DOC99: Resolve a comment ⚠️ destructive
**Setup:** use the `id` returned by TC-DOC96 as `{COMMENT_ID}`

**Prompt**
> `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, content="Handled.", action="resolve")`

**Checks**
- Returns `file_id`, `comment_id`, `reply_id`, `action: "resolve"`, `content: "Handled."`, and `created_time` (`resolve_doc_comment` before #663 returned `doc_id`, `comment_id`, `reply_id` and `action`)
- Re-running `list_file_comments` shows that comment with `resolved: true` and a reply with `content: "Handled."` and `action: "resolve"`

**Cleanup:** none available — resolving doesn't remove the comment thread, just marks it resolved (see the note at the top)

**Result (2026-07-16) ✅ PASS**
`resolve_doc_comment(doc_id=<TEST_DOC_ID>, comment_id="AAAB-5FtNYE", reply_content="Handled.")` returned `doc_id`, `comment_id`, `reply_id: "AAAB-5FtNYQ"`, `action: "resolve"`. Re-ran `list_doc_comments`: the TC-DOC96 comment now shows `resolved: true` with a reply `content: "Handled.", action: "resolve"`. The reply also included `modified_time` — confirms the fix from PR review comment (missing `modified_time` on replies) is live.

**Result (2026-09-04) ✅ PASS**
resolve_doc_comment(TC-DOC96's id) returned doc_id/comment_id/reply_id/action:"resolve". Re-list confirmed resolved:true with reply content "Handled.", action:"resolve", modified_time present.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: resolve_doc_comment returned doc_id, comment_id, reply_id and action "resolve". A re-list showed resolved:true with a reply "Handled." (action resolve, modified_time present).

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — resolve_doc_comment returned doc_id, comment_id, reply_id, `action:"resolve"`; relisting shows the DOC96 comment `resolved:true` with a reply content "Handled.", action "resolve".

---

### TC-DOC100: Resolve a non-existent comment ID
**Prompt**
> `reply_to_comment(file_id={DOC_ID}, comment_id="not-a-real-comment-id", action="resolve")`

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

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Tool error carrying the HttpError 404 "Comment not found: not-a-real-comment-id." Not a silent success or crash.

---

### TC-DOC101: List comments on a non-existent doc
**Prompt**
> `list_file_comments(file_id="not-a-real-doc-id")`

**Checks**
- API error propagates — not a silent empty list or server crash

**Cleanup:** none (no mutation applied)

**Result (2026-07-16) ✅ PASS**
`list_doc_comments(doc_id="not-a-real-doc-id")` raised `HttpError 404 ... "File not found: not-a-real-doc-id."` — propagated cleanly, no silent empty list, no server crash.

**Result (2026-09-04) ✅ PASS**
list_doc_comments('not-a-real-doc-id') raised HttpError 404 "File not found" — propagated cleanly, no silent empty list.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: A fake doc ID raised HttpError 404 "File not found".

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Tool error carrying HttpError 404 "File not found: not-a-real-doc-id." Not an empty list.

---

### TC-D310: Comments on a spreadsheet: add, anchor, list, reply and resolve ⚠️ destructive
**Background:** #663's premise: the comment tools were never Docs-specific, since the Drive comments resource takes any `fileId`. This case runs every comment tool against a Sheets file.

**Setup:** `create_spreadsheet(title="QA TC-D310 comments", folder_id={FOLDER_ID})`; note the returned ID as `{SHEET_FILE_ID}`.

**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D310 a")`
2. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D310 b", quoted_text="QA anchor")`
3. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id=<step 1's id>, content="QA TC-D310 reply")`
4. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id=<step 1's id>, action="resolve")`
5. `list_file_comments(file_id={SHEET_FILE_ID})`

**Checks**
- Steps 1–4 return without an error. Step 1 returns an `id`, `content: "QA TC-D310 a"` and `quoted_text: null`; step 2 returns `quoted_text: "QA anchor"`
- Step 3 returns `action: null` and `content: "QA TC-D310 reply"`; step 4 returns `action: "resolve"` and `content: ""` (Drive returns an empty string for a reply with no text)
- Step 5 returns `file_id: {SHEET_FILE_ID}` and both comments. Step 1's comment has `resolved: true` and two replies, `QA TC-D310 reply` (`action: null`) then one with `action: "resolve"`. Step 2's comment has `resolved: false`, `replies: []` and `quoted_text: "QA anchor"`

**Cleanup:** `delete_file(file_id={SHEET_FILE_ID}, permanent=True)`

---

### TC-D311: A plain reply leaves the comment open ⚠️ destructive
**Setup:** run TC-DOC97 first; use its `id` as `{COMMENT_ID}`

**Prompt**
> `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, content="QA TC-D311: plain reply.")`

**Checks**
- Returns `file_id`, `comment_id`, a `reply_id`, `action: null`, `content: "QA TC-D311: plain reply."` and `created_time`
- `list_file_comments(file_id={DOC_ID})` shows the TC-DOC97 comment still `resolved: false`, with this reply last in its `replies`, `action: null`

**Cleanup:** none available (see the note at the top)

---

### TC-D312: Reopen a resolved comment ⚠️ destructive
**Setup:** run TC-DOC99 first; its comment (TC-DOC96's `id`) is resolved. Use that `id` as `{COMMENT_ID}`

**Prompt**
> `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, action="reopen")`

**Checks**
- Returns `action: "reopen"` and `content: ""` (Drive returns an empty string for a reply with no text)
- `list_file_comments(file_id={DOC_ID})` shows that comment with `resolved: false`, its last reply `action: "reopen"`

**Cleanup:** to leave the comment as TC-DOC99 left it, `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, action="resolve")`

---

### TC-D313: A reply with neither content nor action is refused before any call
**Steps**
1. `reply_to_comment(file_id={DOC_ID}, comment_id=<any comment's id from list_file_comments>)`
2. `reply_to_comment(file_id={DOC_ID}, comment_id=<the same id>, action="delete")`

**Checks**
- 1: returns `{"error": ...}` saying to pass `content` or an `action`. `list_file_comments` shows no new reply on that comment
- 2: refused as an invalid argument (only `resolve` and `reopen` are accepted), with no reply posted

**Cleanup:** none (no mutation applied)

---

### TC-D314: The old comment tool names and `doc_id` still work for one release ⚠️ destructive
**Background:** #663 renamed `list_doc_comments`/`add_doc_comment` and their `doc_id` parameter, and deprecated `resolve_doc_comment`, under `docs/design.md`'s "Renaming or Removing a Tool". Run it on a server with `ENABLED_TOOLS=all`, which registers the old names as aliases (the team servers do).

**Steps**
1. `list_file_comments(doc_id={DOC_ID})`
2. `list_doc_comments(doc_id={DOC_ID})`
3. `add_doc_comment(file_id={DOC_ID}, content="QA TC-D314: alias.")`
4. `list_file_comments(file_id={DOC_ID}, doc_id={DOC_ID})`
5. `resolve_doc_comment(doc_id={DOC_ID}, comment_id=<step 3's id>, reply_content="QA TC-D314: resolved.")`
6. Read the tool list (`list_tools`, or the client's tool descriptions) for `list_doc_comments` and `resolve_doc_comment`

**Checks**
- 1 and 2: the same comments as `list_file_comments(file_id={DOC_ID})`, with `file_id` echoed and `deprecation_warnings` holding one entry naming `doc_id` and `file_id`
- 3: the comment is added, and the result has no `deprecation_warnings`: the old tool name alone isn't flagged in the result, only the old parameter
- 4: a tool error saying to pass only `file_id`
- 5: returns `doc_id`, `comment_id`, `reply_id` and `action: "resolve"` (its old shape), and `list_file_comments` shows that comment resolved
- 6: `list_doc_comments`' description starts ``Deprecated: use `list_file_comments`.``; `resolve_doc_comment`'s starts ``Deprecated: use `reply_to_comment` with `action='resolve'` instead.``

**Cleanup:** none available (see the note at the top)
