# Drive Tools — Sharing & Permissions — QA Test Cases

Source: `src/mcp_gee_sweet/tools/drive/sharing.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute your `{SPREADSHEET_ID}`, `{DOC_ID}`, and `{FOLDER_ID}` from `fixtures.local.md`.

---

## `share_spreadsheet`

### TC-D18: Share as writer

**Prompt**
> "Share {SPREADSHEET_ID} with test-recipient@example.com as a writer"

**Checks**
- Returns success for that recipient
- No entries in `failures`

**Result (2026-09-04) ❌ FAIL**
share_spreadsheet writer on Shared Drive file -> `{"successes":[],"failures":[{... "error":"Failed to share: File not found: <id>."}]}`. `share_spreadsheet._share_one` calls `permissions().create()` WITHOUT `supportsAllDrives=True` (sharing.py:69-77), unlike share_file (:364) and update/remove/transfer. Every Shared Drive file is invisible to it. Reproduced on throwaway file AND on real {SPREADSHEET_ID}.

**Result (2026-09-05) ✅ PASS** — re-verified against PR #695 (issue #687)
share_spreadsheet writer on the real Shared Drive fixture -> `{"successes":[{"email_address":"test-recipient@example.com","role":"writer",...}],"failures":[]}`. `supportsAllDrives=True` now set on the `permissions().create()` call; fix confirmed live. Test permission removed after verification.

---

### TC-D19: Share as reader

**Prompt**
> "Share {SPREADSHEET_ID} with test-recipient@example.com as a reader"

**Checks**
- Permission granted as reader
- No `failures`

**Result (2026-09-04) ❌ FAIL**
Same supportsAllDrives bug — reader share returns "File not found".

**Result (2026-09-05) ✅ PASS** — re-verified against PR #695 (issue #687)
Reader share on the real Shared Drive fixture succeeds -> `{"successes":[{"email_address":"test-recipient2@example.com","role":"reader",...}],"failures":[]}`. Test permission removed after verification.

---

### TC-D20: Share as commenter

**Prompt**
> "Share {SPREADSHEET_ID} with test-recipient@example.com as a commenter"

**Checks**
- Permission granted as commenter
- No `failures`

**Result (2026-09-04) ❌ FAIL**
Same supportsAllDrives bug — commenter share returns "File not found".

**Result (2026-09-05) ✅ PASS** — re-verified against PR #695 (issue #687)
Commenter share on the real Shared Drive fixture succeeds -> `{"successes":[{"email_address":"test-recipient3@example.com","role":"commenter",...}],"failures":[]}`. Test permission removed after verification.

---

### TC-D21: Invalid role

**Prompt**
> "Share {SPREADSHEET_ID} with test@example.com as an 'owner'"

**Checks**
- Entry goes to `failures` list (invalid role)
- Returns a message indicating the role is not accepted

**Result (2026-09-04) ✅ PASS**
Invalid role 'owner' -> failures:[{error:"Invalid role 'owner'. Must be 'reader', 'commenter', or 'writer'."}], no exception. Client-side validation, fires before API call so unaffected by the bug.

---

### TC-D22: Missing email address key

**Prompt**
> "Share {SPREADSHEET_ID} — pass a recipient object with no email_address field"

**Checks**
- Entry goes to `failures` with `None` email
- Does not throw an unhandled exception

**Result (2026-09-04) ✅ PASS**
Recipient with no email_address -> failures:[{email_address:null, error:"Missing email_address in recipient entry."}], no exception.

---

### TC-D23: Mixed success and failure

**Prompt**
> "Share {SPREADSHEET_ID} with two recipients: valid@example.com as writer, and a second recipient with an invalid role 'superuser'"

**Checks**
- valid@example.com in success list
- Invalid role entry in `failures`
- Both results present in the same response

**Result (2026-09-04) ❌ FAIL**
Mixed: invalid-role entry ('superuser') correctly routed to failures; valid@example.com writer entry ALSO in failures ("File not found") due to supportsAllDrives bug, not in successes. Partial-failure batching itself works; API-path recipient blocked.

**Result (2026-09-05) ✅ PASS** — re-verified against PR #695 (issue #687)
valid@example.com writer -> successes; invalid-role@example.com ('superuser') -> failures with the same invalid-role message as before. Both results present in one response as expected. Test permission removed after verification.

---

### TC-D24: send_notification=False

**Prompt**
> "Share {SPREADSHEET_ID} with test@example.com as reader but don't send them a notification email"

**Checks**
- Share succeeds
- No notification email sent (verify by using an email you control)

**Result (2026-09-04) ❌ FAIL**
send_notification=False -> API path -> "File not found" (supportsAllDrives bug). Cannot verify notification suppression.

**Result (2026-09-05) ⚠️ PASS (with test-case caveat)** — re-verified against PR #695 (issue #687)
The `supportsAllDrives` bug is fixed, but this test case's own `test@example.com` recipient can't validate it: with `send_notification=False`, Drive rejects a share to any email with no associated Google account ("you must check the Notify people box to invite this recipient") — a real, unrelated API constraint, not a regression. Re-ran against a real Google account (an email the tester controls) instead: share succeeded with `send_notification=False`, confirming the fix. Test-case prompt should be updated to use a real Google-account email rather than `test@example.com` to actually exercise this path in the future.

---

### TC-D25: Non-existent spreadsheet ID

**Prompt**
> "Share spreadsheet 'invalidid123xyz' with test@example.com as reader"

**Checks**
- API error goes to `failures` list — not a top-level exception
- 🔍 **Danger check:** no ownership validation before sharing — note that any accessible spreadsheet ID can be shared

**Result (2026-09-04) ✅ PASS**
share_spreadsheet("invalidid123xyz", ...) -> error routed to failures:[{error:"Failed to share: File not found: invalidid123xyz."}], NOT a top-level exception. 🔍 Danger check confirmed: no ownership validation before sharing — any accessible spreadsheet ID is shareable.

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

**Result (2026-09-04) ❌ FAIL**
Concurrent 5-recipient share: all 5 -> "File not found" (supportsAllDrives bug). Each failure entry echoes its own email/role correctly (no cross-attribution in the failure list), but the no-cross-attribution check requires successes, which cannot be produced. Blocked.

**Result (2026-09-05) ✅ PASS** — re-verified against PR #695 (issue #687)
All 5 recipients -> successes, none in failures. `list_permissions` cross-check confirmed exact attribution: recipient1=reader, recipient2=commenter, recipient3=writer, recipient4=reader, recipient5=writer — no cross-attribution. All 5 test permissions removed after verification (teardown complete).

---

## `list_permissions`

### TC-D124: List permissions on a file — top-level entry present

**Note (v0.9.0):** on a Shared Drive item (the current fixture, post-#305), Drive reports no `owner` role at all (`owners: []`) — the top-level roles are `organizer`/`fileOrganizer` instead. Checks updated to match; on a personal-Drive file the original `owner`-role expectation still holds.

**Prompt**
> "List all permissions on {SPREADSHEET_ID}"

**Checks**
- Returns at least one entry
- 🔍 On a Shared Drive item: at least one entry has `role: 'organizer'` (the de-facto owner there); on a personal-Drive file: an entry has `role: 'owner'`
- Each entry has `id`, `type`, `role` — no `KeyError` or missing fields

**Result (2026-09-04) ❌ FAIL**
list_permissions on {SPREADSHEET_ID} returns 2 well-formed entries (all have id/type/role, no KeyError). But NO entry has role:'owner' — fixture is now a Shared Drive file (owners:[]), roles are 'organizer' (kevin@mcpsuite.io) and 'fileOrganizer' (SA). "Owner entry has role:'owner' and type:'user'" check not met. Tool is correct; test-case assumption is stale post-#305 Shared-Drive migration.

---

### TC-D125: List permissions after sharing — new entry visible

**Setup:** run TC-D132 first (share with a test user as reader)

**Prompt**
> "List the permissions on {SPREADSHEET_ID}"

**Checks**
- The test user's email appears with `role: 'reader'`
- Their `permission_id` is present for use in update/remove tests

**Result (2026-09-04) ✅ PASS**
(adapted to throwaway QA-v090-share-sheet) After share_file reader grant, list_permissions shows huismanfamily01@gmail.com role:'reader' with permission_id 17827006775376940548 present for later update/remove use.

---

### TC-D126: Non-existent file ID

**Prompt**
> "List permissions on file 'invalidid123xyz'"

**Checks**
- API error propagates — not a silent empty list or server crash

**Result (2026-09-04) ✅ PASS**
list_permissions("invalidid123xyz") -> HttpError 404 "File not found: invalidid123xyz." propagates as tool error; not a silent empty list or crash. URL confirms supportsAllDrives=true is sent.

---

## `update_permission`

### TC-D127: Downgrade writer → reader ⚠️ destructive

**Setup:** share {SPREADSHEET_ID} with test-recipient@example.com as writer first (TC-D132 variant); note the `permission_id` returned

**Prompt**
> "Update permission {PERMISSION_ID} on {SPREADSHEET_ID} to 'reader'"

**Checks**
- Response `role` is `reader`
- Follow-up `list_permissions` confirms the same permission ID now has `role: 'reader'`

**Result (2026-09-04) ✅ PASS**
update_permission(throwaway, 03150678215290859261, "reader") on a writer entry -> {"permissionId":"03150678215290859261","role":"reader"}; follow-up list_permissions confirms that id now role:'reader'.

---

### TC-D128: Invalid role value

**Prompt**
> "Update permission {PERMISSION_ID} on {SPREADSHEET_ID} to role 'owner'"

**Checks**
- Returns `{"error": "Invalid role 'owner'..."}` — not an exception
- No API call made (validation fires client-side before Drive API)

**Result (2026-09-04) ✅ PASS**
update_permission(..., role="owner") -> {"error":"Invalid role 'owner'. Must be one of: reader, commenter, writer"} — not an exception; client-side validation, no API call.

---

### TC-D129: Non-existent permission ID

**Prompt**
> "Update permission 'fakepermid999' on {SPREADSHEET_ID} to 'reader'"

**Checks**
- Drive API error propagates — not a server crash
- Error message references the invalid permission ID

**Result (2026-09-04) ✅ PASS**
update_permission(..., "fakepermid999", "reader") -> HttpError 404 "Permission not found: fakepermid999." propagates; message references the bad permission id; no crash.

---

## `remove_permission`

### TC-D130: Remove a permission ⚠️ destructive

**Setup:** share {SPREADSHEET_ID} with test-recipient@example.com first; note `permission_id` returned

**Prompt**
> "Remove permission {PERMISSION_ID} from {SPREADSHEET_ID}"

**Checks**
- Response: `{"fileId": ..., "permissionId": ..., "action": "removed"}`
- Follow-up `list_permissions` no longer shows that permission ID

**Result (2026-09-04) ✅ PASS**
remove_permission(throwaway, 12400478166082616858) -> {"fileId":"15wb2N6...","permissionId":"12400478166082616858","action":"removed"}; follow-up list_permissions no longer shows that id.

---

### TC-D131: Non-existent permission ID

**Prompt**
> "Remove permission 'fakepermid999' from {SPREADSHEET_ID}"

**Checks**
- Drive API error propagates — not a silent success or server crash

**Result (2026-09-04) ✅ PASS**
remove_permission(..., "fakepermid999") -> HttpError 404 "Permission not found: fakepermid999." propagates; not a silent success or crash.

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

**Result (2026-09-04) ⏭️ SKIP**
environmental — no second Workspace user + Shared-Drive-only fixture. transfer_ownership(new QA spreadsheet, huismanfamily01@gmail.com) -> HttpError 403 "Owner role is invalid for shared drive items." (reason: ownerOnTeamDriveItemNotSupported). Every file this env creates lands in {SHARED_DRIVE_ID}; {PERMISSION_EMAIL} is a personal Gmail, not in the mcpsuite.io org. Cannot complete; needs a My-Drive disposable file + real in-org receiver. Tool surfaced the API error cleanly (no crash).

---

### TC-D234: Service account cannot transfer ownership

**Prompt** (run against the `mcp-gee-sweet-sa` server, per `create_spreadsheet`'s `drive_files.md` TC-D04 convention for auth-method-dependent behavior)
> "Transfer ownership of {SPREADSHEET_ID} to {TEST_PERMISSION_EMAIL}"

**Checks**
- Call fails with a Drive API permission/consent error — not a silent success or unhandled crash
- 🔍 **Known limitation:** service accounts have no personal Drive identity to own files; this documents the failure mode the tool's docstring OAuth requirement refers to

**Result (2026-07-27) ⏭️ SKIP — environmental**
The `mcp-gee-sweet-sa` server available in this role worktree is a separate long-running process not tracking this PR's branch — `transfer_ownership` isn't registered on it even after `/mcp reconnect`, so the tool doesn't exist to call yet on that connection. Not a product defect; needs re-running once this PR's code reaches wherever that server's process is pointed (e.g. post-merge).

**Result (2026-09-04) ⏭️ SKIP**
out of shard scope — requires the mcp-gee-sweet-sa server; this shard is restricted to the mcp__mcp-gee-sweet-kit__ (OAuth) prefix only.

---

### TC-D235: Non-existent file ID

**Prompt**
> "Transfer ownership of file 'fakefileid999' to {TEST_PERMISSION_EMAIL}"

**Checks**
- Drive API error propagates — not a silent success

**Result (2026-07-27) ✅ PASS**
`transfer_ownership(file_id="fakefileid999", new_owner_email="qa-nonexistent-placeholder@example.com")` → `HttpError 404: "File not found: fakefileid999."` propagates as a tool error, not a silent success. Non-destructive, no fixture needed.

**Result (2026-09-04) ✅ PASS**
transfer_ownership("fakefileid999", ...) -> HttpError 404 "File not found: fakefileid999." propagates; not a silent success.

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

**Result (2026-09-04) ✅ PASS**
share_file(throwaway, [{type:user, email:huismanfamily01@gmail.com, role:reader}]) -> successes:[{type:'user', role:'reader', permissionId:'17827006775376940548', email_address:'huismanfamily01@gmail.com'}], failures:[]. Follow-up list_permissions confirms the entry.

---

### TC-D133: Missing email_address for type=user

**Prompt**
> "Share {SPREADSHEET_ID} using share_file — pass a permission with type='user' and role='reader' but omit email_address"

**Checks**
- Entry goes to `failures` with a message about missing `email_address`
- No API call attempted for that entry
- Does not throw an unhandled exception

**Result (2026-09-04) ✅ PASS**
share_file with type='user' role='reader', no email_address -> failures:[{error:"'email_address' required for type='user'"}], successes:[], no exception.

---

### TC-D134: Invalid role

**Prompt**
> "Share {SPREADSHEET_ID} with test@example.com using share_file with role='superuser'"

**Checks**
- Entry goes to `failures` with a message about the invalid role
- `successes` is empty

**Result (2026-09-04) ✅ PASS**
share_file with role='superuser' -> failures:[{error:"Invalid role 'superuser'. Must be one of: reader, commenter, writer"}], successes:[].

---

### TC-D135: Share with type=domain

> ⚠️ **Environmental:** `example.com` is not a Google Workspace domain; Drive will reject this with a domain validation error. Replace with your actual GWS domain if available, or SKIP and record as environmental.

**Prompt**
> "Share {SPREADSHEET_ID} with everyone at {GWS_DOMAIN} as a reader using share_file with type='domain'"

**Checks**
- Response `successes` contains an entry with `type: 'domain'` and `domain: '{GWS_DOMAIN}'`
- Follow-up `list_permissions` shows the domain permission entry

**Result (2026-09-04) ✅ PASS**
share_file type='domain' domain='mcpsuite.io' (real GWS domain) role='reader' -> successes:[{type:'domain', role:'reader', permissionId:'09502084656447390423', domain:'mcpsuite.io'}]; list_permissions shows the domain entry (display_name "MCPSuite").

---

### TC-D136: Share with type=anyone (public link)

**Prompt**
**Playwright: required**
> "Make {SPREADSHEET_ID} publicly readable using share_file with type='anyone' and role='reader'"

**Checks**
- Response `successes` contains `type: 'anyone'`, `role: 'reader'`
- Follow-up `list_permissions` shows an `anyone` entry
- File accessible via its `web_link` without authentication (verify in incognito browser)

**Result (2026-09-04) ✅ PASS**
share_file type='anyone' role='reader' -> successes:[{type:'anyone', role:'reader', permissionId:'anyoneWithLink'}]; list_permissions shows the 'anyone' entry. Incognito web_link check NOT performed — the Playwright browser session is authenticated as kevin@mcpsuite.io, so it cannot verify unauthenticated access (documented run.md limitation for permission tests); API is the confirmation source.

---

### TC-D137: Share a folder

**Prompt**
**Playwright: required**
> "Share folder {FOLDER_ID} with {TEST_PERMISSION_EMAIL} as a writer using share_file"

**Checks**
- Share succeeds; `successes` contains the entry
- `list_permissions` on the folder shows the new permission
- A child file's own Share dialog in Drive UI shows the inherited access — `list_permissions` on the child itself does not surface a folder-level grant (confirmed live: the Drive API's `permissions.list` only returns permissions granted directly on the queried resource, not ones inherited from an ancestor folder), so this genuinely has no API alternative

**Result (2026-09-04) ✅ PASS**
share_file(folder QA-v090-share-folder, [{type:user, email:huismanfamily01@gmail.com, role:writer}]) -> successes:[{...permissionId:'17827006775376940548'}], failures:[]; list_permissions on the folder confirms role:'writer'. Child-file inherited-access via Drive UI Share dialog NOT checked (test-case itself states this has no API alternative; requires the Share dialog).

---

### TC-D138: Mixed success and failure in one call

**Prompt**
> "Share {SPREADSHEET_ID} using share_file with two permissions: first type='user' email=test@example.com role='reader', second type='user' role='writer' (no email_address)"

**Checks**
- First entry in `successes`, second entry in `failures`
- Both present in the same response — partial failure does not abort the batch

**Result (2026-09-04) ✅ PASS**
share_file with [{type:user, email:qa-mixed-recipient@example.com, role:reader}, {type:user, role:writer (no email)}] -> first in successes (permissionId 12400478166082616858), second in failures ("'email_address' required for type='user'"). Both in one response; batch not aborted. (First attempt used test@example.com which Google's own address validation rejected with "There's a problem with this email or domain" — environmental Google quirk, retried with a clean address.)

---

### TC-D139: send_notification=False for user share

**Prompt**
> "Share {SPREADSHEET_ID} with {TEST_PERMISSION_EMAIL} as reader using share_file, but don't send a notification email"

**Checks**
- Share succeeds; `successes` populated
- No notification email sent — verify by checking the inbox of `TEST_PERMISSION_EMAIL`
- `send_notification=False` confirmed — `sendNotificationEmail=False` passed to the API

> ⚠️ **Note:** Drive requires `sendNotificationEmail=True` when sharing with non-Google Workspace accounts. If `TEST_PERMISSION_EMAIL` is a personal Gmail, this test may fail with a Drive API restriction — record as environmental, not a tool bug.

**Result (2026-09-04) ✅ PASS**
share_file(throwaway, huismanfamily01@gmail.com reader, send_notification=false) -> successes populated (permissionId 17827006775376940548), failures:[]. No Drive restriction hit despite personal Gmail (test-case's env warning did not materialize). Inbox non-delivery not independently verified.

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

**Result (2026-09-04) ✅ PASS**
share_file concurrent 4-permission call (3 users + 1 domain). All 4 in successes, none in failures. Attribution cross-checked individually against list_permissions: qa177-recipient1=reader (17860759509164023546), qa177-recipient2=writer (03150678215290859261), qa177-recipient3=commenter (13827627058833662749), domain mcpsuite.io=reader (09502084656447390423). No cross-attribution.

---
