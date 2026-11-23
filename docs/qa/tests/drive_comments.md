# Drive Tools — Comments — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive/comments.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}`, `{DOC_ID}`, and `{FOLDER_ID}` from `fixtures.local.md`.

The comment tools call the Drive `comments`/`replies` resource, not the Docs API, so they take any file Drive supports comments on. TC-DOC96–TC-DOC101 moved here from `docs_content.md` with #663, which renamed the tools (`list_doc_comments` → `list_file_comments`, `add_doc_comment` → `add_file_comment`, `doc_id` → `file_id`) and replaced `resolve_doc_comment` with `reply_to_comment(action=)`. They keep their IDs, so earlier results files still point at them; their Result entries before #663 record the old names as they were called. New cases here use `TC-D`.

A comment added on `{DOC_ID}` stays there until it's deleted. Later cases build on the comments TC-DOC96, TC-DOC97 and TC-DOC99 leave, so delete them only once the cases that use them have run: `list_file_comments(file_id={DOC_ID})`, then `delete_comment(file_id={DOC_ID}, comment_id=<id>)` for each comment whose text starts `QA TC-` (`delete_comment` since #664; before it they were removed in the Docs UI). Keep test comment text prefixed `QA TC-…` so it's identifiable. TC-D310, TC-D315 to TC-D321 and TC-D324 work on a throwaway spreadsheet and delete it instead.

---

## `list_file_comments` / `add_file_comment` / `reply_to_comment` (#151, #663)

### TC-DOC96: Add a comment with no quoted-text anchor ⚠️ destructive
**Prompt**
> `add_file_comment(file_id={DOC_ID}, content="QA TC-DOC96: general note.")`

**Checks**
- Returns `id`, `content` matching the input text, `author` (`display_name`/`email_address` populated from the caller's identity), `created_time`
- `quoted_text` is `null` — no anchor was requested
- No error

**Cleanup:** after the cases that build on it (see the note at the top)

**Result (2026-07-16) ✅ PASS**
`add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC96: general note.")` returned `id: "AAAB-5FtNYE"`, `content` matching the input, `author.display_name: "<QA user>"`, `created_time`, `quoted_text: null`. No error. Note: `author.email_address` was `null` rather than populated — this is Drive API behavior for the authenticated OAuth user's own comments (email visibility is a privacy-scoped field), not a tool defect; the tool correctly passes through whatever the API returns.

**Result (2026-09-04) ✅ PASS**
add_doc_comment (no anchor) returned id, content match, author.display_name="<QA user>" (email_address null - Drive API privacy behavior, not a defect), created_time, quoted_text:null.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: add_doc_comment returned id, matching content, author.display_name, created_time and quoted_text:null. email_address was null, which is the known Drive privacy behavior.

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Run on the fixture copy. Returned id `doco.PHdj…`, matching content, author.display_name, created_time, `quoted_text: null`. `author.email_address` is null (Drive privacy behavior for the caller's own comments, as in prior passes; see stale wording note).

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — returned `id`, matching `content`, `author.display_name`, `created_time`, `quoted_text: null`; `author.email_address` null (Drive privacy behavior, as before).

---

### TC-DOC97: Add a comment anchored to quoted text ⚠️ destructive
**Setup:** `{DOC_ID}` must contain the literal text "QA anchor target" somewhere (add it with `insert_doc_text` if absent; `write_doc_content` would replace the whole body)

**Prompt**
> `add_file_comment(file_id={DOC_ID}, content="QA TC-DOC97: anchored note.", quoted_text="QA anchor target")`

**Checks**
- Returns `quoted_text: "QA anchor target"` — the anchor round-trips through the API response
- `list_file_comments` on the same doc shows this comment with the same `quoted_text`

**Cleanup:** see the note at the top

**Result (2026-07-16) ✅ PASS**
Doc lacked the literal text "QA anchor target", so it was inserted via `insert_doc_text` (not `write_doc_content`, which replaces the whole doc body — using it as the setup note suggests would have wiped the fixture's existing content). `add_doc_comment(doc_id=<TEST_DOC_ID>, content="QA TC-DOC97: anchored note.", quoted_text="QA anchor target")` returned `quoted_text: "QA anchor target"`, round-tripping correctly. Confirmed via `list_doc_comments` in TC-DOC98 below.

**Result (2026-09-04) ✅ PASS**
Inserted "QA anchor target" text via insert_doc_text, then add_doc_comment with quoted_text="QA anchor target" returned quoted_text round-tripped correctly.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: I inserted "QA anchor target" with insert_doc_text, then add_doc_comment returned quoted_text "QA anchor target".

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — Added "QA anchor target" to the copy with insert_doc_text, then add_doc_comment returned `quoted_text: "QA anchor target"`; list_doc_comments shows the same quoted_text.

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — the Doc was created holding "QA anchor target"; `add_file_comment` returned `quoted_text: "QA anchor target"`, and `list_file_comments` shows the same.

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

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — both comments listed, each `resolved: false` and `replies: []`; DOC97's `quoted_text` is "QA anchor target", DOC96's null; `file_id` matches the Doc.

---

### TC-DOC99: Resolve a comment ⚠️ destructive
**Setup:** use the `id` returned by TC-DOC96 as `{COMMENT_ID}`

**Prompt**
> `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, content="Handled.", action="resolve")`

**Checks**
- Returns `file_id`, `comment_id`, `reply_id`, `action: "resolve"`, `content: "Handled."`, and `created_time` (`resolve_doc_comment` before #663 returned `doc_id`, `comment_id`, `reply_id` and `action`)
- Re-running `list_file_comments` shows that comment with `resolved: true` and a reply with `content: "Handled."` and `action: "resolve"`

**Cleanup:** after the cases that build on it: resolving doesn't remove the comment thread, just marks it resolved (see the note at the top)

**Result (2026-07-16) ✅ PASS**
`resolve_doc_comment(doc_id=<TEST_DOC_ID>, comment_id="AAAB-5FtNYE", reply_content="Handled.")` returned `doc_id`, `comment_id`, `reply_id: "AAAB-5FtNYQ"`, `action: "resolve"`. Re-ran `list_doc_comments`: the TC-DOC96 comment now shows `resolved: true` with a reply `content: "Handled.", action: "resolve"`. The reply also included `modified_time` — confirms the fix from PR review comment (missing `modified_time` on replies) is live.

**Result (2026-09-04) ✅ PASS**
resolve_doc_comment(TC-DOC96's id) returned doc_id/comment_id/reply_id/action:"resolve". Re-list confirmed resolved:true with reply content "Handled.", action:"resolve", modified_time present.

**Result (2026-10-17) ✅ PASS — v0.9.2 release pass**
Run 2 (ash).

**Result (2026-10-19) ✅ PASS — v0.9.3 release pass**
`oauth`: resolve_doc_comment returned doc_id, comment_id, reply_id and action "resolve". A re-list showed resolved:true with a reply "Handled." (action resolve, modified_time present).

**Result (2026-11-08) ✅ PASS — ornithomimus release pass, shard B on `mcp-gee-sweet-oauth`** — resolve_doc_comment returned doc_id, comment_id, reply_id, `action:"resolve"`; relisting shows the DOC96 comment `resolved:true` with a reply content "Handled.", action "resolve".

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — returned `file_id`, `comment_id`, `reply_id`, `action: "resolve"`, `content: "Handled."` and `created_time`; a re-list (via TC-D314 step 1) shows the reply `Handled.` with `action: "resolve"` (the comment then reopened by TC-D312).

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

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — tool error carrying HttpError 404 "Comment not found: not-a-real-comment-id."

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

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — tool error carrying HttpError 404 "File not found: not-a-real-doc-id."

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

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway spreadsheet in the QA folder** — 1: `id`, `content: "QA TC-D310 a"`, `quoted_text: null`. 2: `quoted_text: "QA anchor"`. 3: `action: null`, `content: "QA TC-D310 reply"`. 4: `action: "resolve"`, `content: ""`. 5: `file_id` matches, both comments; step 1's `resolved: true` with the replies `QA TC-D310 reply` (`action: null`) then the `resolve` reply; step 2's `resolved: false`, `replies: []`, `quoted_text: "QA anchor"`. Cleanup: spreadsheet deleted permanently.

---

### TC-D311: A plain reply leaves the comment open ⚠️ destructive
**Setup:** run TC-DOC97 first; use its `id` as `{COMMENT_ID}`

**Prompt**
> `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, content="QA TC-D311: plain reply.")`

**Checks**
- Returns `file_id`, `comment_id`, a `reply_id`, `action: null`, `content: "QA TC-D311: plain reply."` and `created_time`
- `list_file_comments(file_id={DOC_ID})` shows the TC-DOC97 comment still `resolved: false`, with this reply last in its `replies`, `action: null`

**Cleanup:** see the note at the top

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — returned `file_id`, `comment_id`, `reply_id`, `action: null`, `content: "QA TC-D311: plain reply."`, `created_time`; the list shows the DOC97 comment still `resolved: false` with this reply, `action: null`.

**Note (2026-11-20, PR #1563 round 4, Kit, at `ba84c5e`)** — observed outside this case: a plain reply (no `action`) to a *resolved* comment reopens it. Drive returns the reply with `action: "reopen"`, though the tool sent no action. Reproduced twice on a throwaway spreadsheet. `reply_to_comment`'s docstring says the action is None for a plain reply and doesn't mention this; sent back on the PR.

---

### TC-D312: Reopen a resolved comment ⚠️ destructive
**Setup:** run TC-DOC99 first; its comment (TC-DOC96's `id`) is resolved. Use that `id` as `{COMMENT_ID}`

**Steps**
1. `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, action="reopen")`
2. `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, action="resolve")`, then `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, content="QA TC-D312: plain reply.")` with no `action` (added in PR #1563 round 5)

**Checks**
- 1: returns `action: "reopen"` and `content: ""` (Drive returns an empty string for a reply with no text). `list_file_comments(file_id={DOC_ID})` shows that comment with `resolved: false`, its last reply `action: "reopen"`
- 2: the plain reply returns `action: "reopen"` though none was sent: Drive reopens a resolved comment that gets a plain reply, as `reply_to_comment`'s docstring says. `list_file_comments` shows the comment `resolved: false`

**Cleanup:** to leave the comment as TC-DOC99 left it, `reply_to_comment(file_id={DOC_ID}, comment_id={COMMENT_ID}, action="resolve")`

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — returned `action: "reopen"`, `content: ""`; the list shows the DOC96 comment `resolved: false`, its last reply `action: "reopen"`. Cleanup skipped: the Doc was deleted.

---

### TC-D313: A reply with neither content nor action is refused before any call
**Steps**
1. `reply_to_comment(file_id={DOC_ID}, comment_id=<any comment's id from list_file_comments>)`
2. `reply_to_comment(file_id={DOC_ID}, comment_id=<the same id>, action="delete")`
3. `reply_to_comment(file_id={DOC_ID}, comment_id=<the same id>, content="   ")` (added in PR #1563 round 2)

**Checks**
- 1: returns `{"error": ...}` saying to pass `content` or an `action`. `list_file_comments` shows no new reply on that comment
- 2: refused as an invalid argument (only `resolve` and `reopen` are accepted), with no reply posted
- 3: the same `{"error": ...}` as step 1: content that is only whitespace counts as none. `list_file_comments` shows no new reply

**Cleanup:** none (no mutation applied)

**Result (2026-11-20) ⚠️ PARTIAL — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — 1: `{"error": "Pass content for a plain reply, or an action ('resolve' or 'reopen'); a reply with neither has nothing to post."}`, no reply added. 2: refused by argument validation (`Input should be 'resolve' or 'reopen'`), nothing posted. Both checks met, but a probe outside them, `reply_to_comment(content="   ")` with no action, passed the guard and posted a reply Drive stored with `content: ""`: a whitespace-only reply has nothing to post either. Sent back on the PR.

**Result (2026-11-20) ✅ PASS — PR #1563 round 2 (Kit), `mcp-gee-sweet-kit` at `024f62f`, OAuth, on a throwaway spreadsheet in the QA folder, deleted afterward** — step 3 only (the fix): `reply_to_comment(content="   ")` returned the same `{"error": ...}` as step 1, and the list showed no new reply. Probes beside it: `reply_to_comment(content="  ", action="resolve")` resolved the comment with a reply `content: ""` (the whitespace not sent), and `resolve_doc_comment(reply_content="  ")` did the same. Steps 1 and 2 are unchanged since round 1 and weren't re-run.

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

**Cleanup:** see the note at the top

**Result (2026-11-20) ✅ PASS — PR #1563 round 1 (Kit), `mcp-gee-sweet-kit` at `07e02d0`, OAuth, on a throwaway Doc (`QA PR1563 comments scratch`) in the QA folder, deleted afterward** — 1 and 2: the same comments, `file_id` echoed, `deprecation_warnings` `["`doc_id` is deprecated: use `file_id`. `doc_id` is removed in the next feature release."]`. 3: comment added, no `deprecation_warnings`. 4: tool error `Pass only `file_id`: `doc_id` is its deprecated old name.` 5: returned `doc_id`, `comment_id`, `reply_id`, `action: "resolve"`; the list shows that comment `resolved: true` with the reply `QA TC-D314: resolved.` 6: `list_doc_comments`' description starts ``Deprecated: use `list_file_comments`.``; `resolve_doc_comment`'s starts ``Deprecated: use `reply_to_comment` with `action='resolve'` instead.``

---

### TC-D315: `add_file_comment(anchor=)` passes a Drive anchor through ⚠️ destructive
**Background:** `decision-comments-first-class.md` gives `add_file_comment` an `anchor` passthrough for non-Google files (images, PDFs), where Drive's viewer may honor a `drive#commentRegion`. Decision 5 there confirmed the Google editors ignore any anchor, so this case checks the round trip, not a pinned comment.

**Setup:** `create_spreadsheet(title="QA TC-D315 anchor", folder_id={FOLDER_ID})`; note the returned ID as `{SHEET_FILE_ID}`.

**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D315 anchored", anchor="{\"r\": \"head\", \"a\": [{\"rect\": {\"x\": 10, \"y\": 20, \"w\": 30, \"h\": 40, \"mw\": 100, \"mh\": 100}}]}")`
2. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D315 plain")`
3. `list_file_comments(file_id={SHEET_FILE_ID})`

**Checks**
- 1: returns `anchor` equal to the string sent, character for character
- 2: returns `anchor: null`
- 3: both comments are listed, unresolved, with no replies

**Cleanup:** `delete_file(file_id={SHEET_FILE_ID}, permanent=True)`

**Result (2026-11-20) ❌ FAIL — PR #1563 round 2 (Kit), `mcp-gee-sweet-kit` at `024f62f`, OAuth, on a throwaway spreadsheet in the QA folder, deleted afterward** — 1: refused before any call: `1 validation error for add_file_commentArguments anchor Input should be a valid string [type=string_type, ... input_type=dict]`, the same with a leading space. mcp's `pre_parse_json` runs `json.loads` on a string argument whose annotation isn't exactly `str`, and `anchor`'s is `str | None`, so a `drive#commentRegion` JSON string reaches validation as a dict and is rejected; reproduced in a fresh interpreter through the registered tool's `fn_metadata`, so it isn't client-specific. 2: `anchor: null`, as expected. 3 not run: step 1 added nothing. Sent back on the PR.

**Result (2026-11-20) ✅ PASS — PR #1563 round 3 (Kit), `mcp-gee-sweet-kit` at `c6eeff1`, OAuth, on a throwaway spreadsheet in the QA folder, deleted afterward** — 1: returned `anchor` equal to the string sent, character for character. 2: `anchor: null`. 3: both comments listed, `resolved: false`, `replies: []`. Probe beside it: `reply_to_comment(content="[1, 2]")` posted the reply with `content: "[1, 2]"` verbatim. Outside the case: at this head an explicit `null` for `page_token`, `quoted_text`, `anchor`, `content` or `reply_content` fails validation (each is now exactly `str`), where the round 2 head accepted it; reported on the PR.

**Result (2026-11-20) ✅ PASS — PR #1563 round 4 (Kit), `mcp-gee-sweet-kit` at `ba84c5e`, OAuth, on a throwaway spreadsheet in the QA folder, deleted afterward** — 1: `anchor` returned equal to the string sent, character for character. 2: `anchor: null`. 3: both comments listed, `resolved: false`, `replies: []`. Null probes through Claude Code (an argument written `null` reaches the server as JSON null): `add_file_comment(quoted_text=null)`, `list_file_comments(page_token=null)`, `reply_to_comment(content=null, action="resolve")` and `resolve_doc_comment(reply_content=null)` were all accepted, as no value, where round 3's head rejected them; `reply_to_comment(content="[1, 2]")` posted `[1, 2]` verbatim.

### TC-D324: `list_file_comments` pages through comments with `page_size` and `next_page_token` (#329) ⚠️ destructive
**Setup:** `create_spreadsheet(title="QA TC-D324 comments", folder_id={FOLDER_ID})`; note the returned ID as `{SHEET_FILE_ID}`.

**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D324 one")`, then the same with `content="QA TC-D324 two"` and `content="QA TC-D324 three"`
2. `list_file_comments(file_id={SHEET_FILE_ID}, page_size=2)`
3. `list_file_comments(file_id={SHEET_FILE_ID}, page_size=2, page_token=<step 2's next_page_token>)`
4. `list_file_comments(file_id={SHEET_FILE_ID}, page_size=0)`

**Checks**
- 2: `file_id: {SHEET_FILE_ID}`, two `comments`, and a non-empty `next_page_token`
- 3: the one remaining comment and no `next_page_token` key; across steps 2 and 3 the three comments are `QA TC-D324 one`, `two` and `three`, each once, each with `author` (`display_name`/`email_address`)
- 4: one comment and a `next_page_token` (a `page_size` below 1 is raised to 1, not sent as 0)

**Cleanup:** `delete_file(file_id={SHEET_FILE_ID}, permanent=True)`

**Result (2026-11-22) ✅ PASS — PR #1588 round 1 (Kit), `mcp-gee-sweet-kit` at `e56d11b`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 2: `three`, `two` and `next_page_token` `Mg==`. 3: `one` alone, no `next_page_token` key. Each comment once across the two pages, each with `author` `{display_name, email_address}` (`email_address` null for the caller's own comments, as Drive returns it and as before this PR). 4: one comment (`three`) and a `next_page_token`.

---

## `get_file_comment` / `update_comment` / `delete_comment` (#664)

Every case here works on its own throwaway spreadsheet. Setup for each: `create_spreadsheet(title="QA <case ID> comments", folder_id={FOLDER_ID})`; note the returned ID as `{SHEET_FILE_ID}`. Cleanup for each: `delete_file(file_id={SHEET_FILE_ID}, permanent=True)`.

### TC-D316: `get_file_comment` returns one comment with every reply ⚠️ destructive
**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D316 top", quoted_text="QA anchor")`; note its `id` as `{COMMENT_ID}`
2. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D316 r1")`, then the same with `content="QA TC-D316 r2"`, then `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, action="resolve")`
3. `get_file_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`
4. `list_file_comments(file_id={SHEET_FILE_ID})`

**Checks**
- 3: returns `file_id: {SHEET_FILE_ID}` and `comment` with `id: {COMMENT_ID}`, `content: "QA TC-D316 top"`, `author` (`display_name`/`email_address` of the caller), `created_time`, `modified_time`, `resolved: true`, `deleted: false`, `quoted_text: "QA anchor"`, and three `replies` in order: `QA TC-D316 r1` (`action: null`), `QA TC-D316 r2` (`action: null`), then `content: ""` with `action: "resolve"`. Each reply has `id`, `author`, `created_time`, `modified_time` and `deleted: false`
- 4: the one comment in step 4's list is the same as step 3's `comment`, field for field

**Cleanup:** as the section says

**Result (2026-11-21) ✅ PASS — PR #1578 round 1 (Kit), `mcp-gee-sweet-kit` at `8b2c917`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 3: `comment` with `content: "QA TC-D316 top"`, `author`, `created_time`, `modified_time`, `resolved: true`, `deleted: false`, `quoted_text: "QA anchor"`, and replies `QA TC-D316 r1` (`action: null`), `QA TC-D316 r2` (`action: null`), then `content: ""` with `action: "resolve"`, each with `id`, `author`, `created_time`, `modified_time`, `deleted: false`. 4: the list's one comment equal to step 3's, field for field. `author.email_address` was `null` for the OAuth user's own comments, as in TC-DOC96.

### TC-D317: `update_comment` edits a comment and a reply ⚠️ destructive
**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D317 top")`; note its `id` as `{COMMENT_ID}`
2. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D317 reply")`; note its `reply_id` as `{REPLY_ID}`. Then `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, action="resolve")`; note its `reply_id` as `{RESOLVE_ID}`
3. `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D317 top v2")`
4. `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, reply_id={REPLY_ID}, content="QA TC-D317 reply v2")`
5. `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, reply_id={RESOLVE_ID}, content="QA TC-D317 done")`
6. `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="   ")`
7. `get_file_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`

**Checks**
- 3: returns `file_id`, `comment_id: {COMMENT_ID}`, `reply_id: null`, `content: "QA TC-D317 top v2"` and a `modified_time`
- 4: returns `reply_id: {REPLY_ID}` and `content: "QA TC-D317 reply v2"`
- 5: returns `reply_id: {RESOLVE_ID}` and `content: "QA TC-D317 done"`
- 6: returns `{"error": ...}` saying to pass the new text, and naming `delete_comment`
- 7: the comment's `content` is `QA TC-D317 top v2` (step 6 changed nothing) and it's still `resolved: true`. Its replies are `QA TC-D317 reply v2` (`action: null`) then `QA TC-D317 done` with `action: "resolve"`: the edit kept the resolving reply's action

**Cleanup:** as the section says

**Result (2026-11-21) ✅ PASS — PR #1578 round 1 (Kit), `mcp-gee-sweet-kit` at `8b2c917`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 3: `reply_id: null`, `content: "QA TC-D317 top v2"`, `modified_time`. 4: the reply's id and `QA TC-D317 reply v2`. 5: the resolve reply's id and `QA TC-D317 done`. 6: `{"error": "Pass the new text as content; ... use delete_comment."}`. 7: comment `QA TC-D317 top v2`, `resolved: true`; replies `QA TC-D317 reply v2` (`action: null`) then `QA TC-D317 done` (`action: "resolve"`). Probe beside it: an author edit whose text starts with U+0001 landed (Drive stored it without that character) but the tool returned the non-author error; sent back on the PR.

**Result (2026-11-21) ✅ PASS — PR #1578 round 2 (Kit), `mcp-gee-sweet-kit` at `f5f6673`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 3–5 and 7 as in round 1. 6: the error now reads `... only whitespace or control characters would leave the comment blank. To remove it, use delete_comment.` Round 1's send-back, rerun through the branch's `update_comment` in a fresh interpreter as the author: text with a leading `\x01`, a trailing `\x1f`, tab edges, or a reply with a leading `\x01` each returned the edit (Drive stored them trimmed), NBSP edges were kept as sent and reported as landed, and text of only control characters returned the error before any call. Drive itself stores a control-only reply as `''`.

### TC-D318: `delete_comment` deletes a reply, then the comment ⚠️ destructive
**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D318 top")`; note its `id` as `{COMMENT_ID}`. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D318 other")`
2. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D318 r1")`; note its `reply_id` as `{REPLY_ID}`. Then the same with `content="QA TC-D318 r2"`
3. `delete_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, reply_id={REPLY_ID})`
4. `get_file_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`, then the same with `include_deleted=True`
5. `delete_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`
6. `list_file_comments(file_id={SHEET_FILE_ID})`, then `get_file_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`, then `get_file_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, include_deleted=True)`
7. `delete_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})` again

**Checks**
- 3: returns `file_id`, `comment_id: {COMMENT_ID}`, `reply_id: {REPLY_ID}`, `deleted: true`
- 4: without `include_deleted`, the comment has one reply, `QA TC-D318 r2`. With it, two: `{REPLY_ID}` first, with `deleted: true`, `content: null` and `author: null`, then `QA TC-D318 r2`
- 5: returns `reply_id: null`, `deleted: true`
- 6: the list holds only `QA TC-D318 other`. The plain get is a tool error carrying HttpError 404 (comment not found). The `include_deleted` get returns the comment with `deleted: true`, `content: null` and `author: null`
- 7: a tool error carrying HttpError 404: a deleted comment can't be deleted again

**Cleanup:** as the section says

**Result (2026-11-21) ✅ PASS — PR #1578 round 1 (Kit), `mcp-gee-sweet-kit` at `8b2c917`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 3: `reply_id` echoed, `deleted: true`. 4: without `include_deleted`, one reply `QA TC-D318 r2`; with it, the deleted reply first (`deleted: true`, `content: null`, `author: null`), then `QA TC-D318 r2`. 5: `reply_id: null`, `deleted: true`. 6: the list holds only `QA TC-D318 other`; the plain get raised HttpError 404 `Comment not found`; the `include_deleted` get returned the comment `deleted: true`, `content: null`, `author: null`, its replies included, all `deleted: true` (deleting the comment marks its replies deleted). 7: HttpError 404.

### TC-D319: Editing a deleted comment or reply says it's deleted ⚠️ destructive
**Background:** Drive answers an edit of a deleted comment with a bare HTTP 500 and of a deleted reply with a 400 "Invalid Value" (checked live), neither of which says why. `update_comment` reads the target back after such a failure.

**Steps**
1. `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D319 top")`; note its `id` as `{COMMENT_ID}`. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D319 reply")`; note its `reply_id` as `{REPLY_ID}`
2. `delete_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, reply_id={REPLY_ID})`, then `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, reply_id={REPLY_ID}, content="QA TC-D319 x")`
3. `delete_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`, then `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D319 x")`
4. `update_comment(file_id={SHEET_FILE_ID}, comment_id="not-a-real-comment", content="QA TC-D319 x")`

**Checks**
- 2: returns `{"error": ...}` naming the reply `{REPLY_ID}` as deleted, and pointing to `reply_to_comment` and `add_file_comment`
- 3: returns `{"error": ...}` naming the comment `{COMMENT_ID}` as deleted
- 4: a tool error carrying HttpError 404 (comment not found), not the deleted message

**Cleanup:** as the section says

**Result (2026-11-21) ✅ PASS — PR #1578 round 1 (Kit), `mcp-gee-sweet-kit` at `8b2c917`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 2: `{"error": "The reply <id> is deleted, so it can't be edited. Post a new reply with reply_to_comment, or a new comment with add_file_comment."}`. 3: the same error naming the comment. 4: HttpError 404 `Comment not found: not-a-real-comment.` Probe beside it: editing a reply that was never deleted itself, on a deleted comment, raised Drive's HttpError 404 `Comment not found: <comment id>` (not a 400/500), as `delete_comment` documents for its replies.

### TC-D320: `get_file_comment` on a comment ID that doesn't exist
**Steps**
1. `get_file_comment(file_id={SHEET_FILE_ID}, comment_id="not-a-real-comment")`

**Checks**
- 1: a tool error carrying HttpError 404 (comment not found)

**Cleanup:** as the section says

**Result (2026-11-21) ✅ PASS — PR #1578 round 1 (Kit), `mcp-gee-sweet-kit` at `8b2c917`, OAuth, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — 1: HttpError 404 `Comment not found: not-a-real-comment.`

### TC-D321: An edit by someone other than the author is reported, not passed off as done ⚠️ destructive
**Background:** Drive lets only a comment's or reply's author edit it, and answers anyone else's edit with HTTP 200 and the old text, changing nothing (checked live both ways between the OAuth user and the service account, #664). A non-author's delete is refused with a 403. This needs two identities: run step 1 on an OAuth server and steps 2–4 on a service-account server (`mcp-gee-sweet-sa` in a release pass). A lane QA session, which may call only its own server, runs steps 2–4 in a fresh interpreter (`CLAUDE.md`, "MCP restart") on the branch's `get_file_comment`/`update_comment`/`delete_comment` with a Drive client built from `auth._service_account_creds()`. The service account must be able to see `{SHEET_FILE_ID}`: create it in a Shared Drive folder the service account is a member of.

**Steps**
1. As the OAuth user: `add_file_comment(file_id={SHEET_FILE_ID}, content="QA TC-D321 by user")`; note its `id` as `{COMMENT_ID}`. `reply_to_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D321 user reply")`; note its `reply_id` as `{REPLY_ID}`
2. As the service account: `update_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, content="QA TC-D321 sa edit")`, then the same with `reply_id={REPLY_ID}`
3. As the service account: `delete_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID}, reply_id={REPLY_ID})`
4. As the OAuth user: `get_file_comment(file_id={SHEET_FILE_ID}, comment_id={COMMENT_ID})`

**Checks**
- 2: both return `{"error": ...}` saying Drive left the comment (then the reply) unchanged and only its author can edit it, with `content` holding the text left in place: `QA TC-D321 by user`, then `QA TC-D321 user reply`
- 3: a tool error carrying HttpError 403
- 4: the comment reads `QA TC-D321 by user` and its one reply `QA TC-D321 user reply`, neither deleted

**Cleanup:** as the section says

**Result (2026-11-21) ✅ PASS — PR #1578 round 1 (Kit), `mcp-gee-sweet-kit` at `8b2c917`, step 1 and 4 OAuth, steps 2-3 the service account, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — steps 2-3 ran the branch's `update_comment`/`delete_comment` in a fresh interpreter with a Drive client from `auth._service_account_creds()`. 2: both returned the "Drive left the comment (then reply) ... unchanged: only its author can edit it" error, `content` `QA TC-D321 by user`, then `QA TC-D321 user reply`. 3: HttpError 403 (`insufficientFilePermissions`). 4: comment `QA TC-D321 by user` with its one reply `QA TC-D321 user reply`, neither deleted.

**Result (2026-11-21) ✅ PASS — PR #1578 round 2 (Kit), `mcp-gee-sweet-kit` at `f5f6673`, steps 2-3 the service account in a fresh interpreter, on a throwaway spreadsheet in the QA folder (Shared Drive), deleted afterward** — rerun on the round 2 sheet, since the fix changed the comparison. 2: both returned the "only its author can edit it" error with the text left in place. 3: HttpError 403.
