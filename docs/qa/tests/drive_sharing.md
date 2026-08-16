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

**Prompt** (run against the `mcp-gee-sweet-sa` server, per `create_spreadsheet`'s `drive_files.md` TC-D04 convention for auth-method-dependent behavior)
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
**Playwright: required**
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
- `list_permissions` on a child file already inside `{FOLDER_ID}` (e.g. `{SPREADSHEET_ID}`) shows the same permission — Drive propagates a folder-level grant to its children automatically, so inheritance is confirmable via the same API call rather than the folder's Share dialog in Drive UI

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
