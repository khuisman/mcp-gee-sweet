# Decision: `transfer_ownership` refusals

**Date:** 2026-11-23
**Issue:** [#1181](https://github.com/khuisman/mcp-gee-sweet/issues/1181), PR [#1600](https://github.com/khuisman/mcp-gee-sweet/pull/1600)
**Follow-up:** [#1601](https://github.com/khuisman/mcp-gee-sweet/issues/1601)

> A point-in-time record of what Drive returned for each ownership transfer the tool can't complete, checked live, and why the tool rewrites two of those refusals and not the others.

## What Drive returned

Every probe sent `transfer_ownership`'s own request, `permissions.create(fileId, body={type: user, role: owner, emailAddress}, transferOwnership=True, sendNotificationEmail=True, supportsAllDrives=True)`, against a throwaway Doc or spreadsheet that was deleted afterwards.

| Owner → recipient | Status | Reason | Message |
|---|---|---|---|
| Any identity, file in a shared drive (TC-D233, TC-D234) | 403 | `ownerOnTeamDriveItemNotSupported` | "Owner role is invalid for shared drive items." |
| gmail.com → gmail.com | 403 | `consentRequiredForOwnershipTransfer` | "Consent is required to transfer ownership of a file to another user." |
| gmail.com → Workspace account | 400 | `ownershipChangeAcrossDomainNotPermitted` | "…Sorry, cannot transfer ownership to …. Ownership can only be transferred to another user in the same organization as the current owner." |
| Workspace → address with no Google account (PR #1600 QA round 1) | 400 | `invalidSharingRequest` | "Sorry, ownership can only be transferred to another user in the same organization as the current owner." |

## Decision

- **Rewrite the shared drive and consent refusals.** Neither of Drive's texts says why the transfer failed or what to do instead, so the tool returns `{"error"}` with that, under `docs/style-guide.md`'s "catch when the tool has a message clearer than Google's". Both are matched by reason, so a transfer costs no extra call (the other option for the shared drive case was a `files.get` for `driveId` before every transfer).
- **Word each message from its reason alone.** Only gmail.com → gmail.com produced the consent refusal, but the rewrite applies to every account pair Drive sends it for, so the message doesn't name personal accounts.
- **Let the cross-organization 400 through.** Its message already says ownership stays within the owner's organization. It came back under two different reasons, so nothing should key on either.

## The consumer request flow

Google's guide (developers.google.com/workspace/drive/api/guides/transfer-file) says a consumer transfer starts when the owner creates or updates the recipient's permission with `role=writer, pendingOwner=true`, and the recipient then makes their own permission `owner` with `transferOwnership=true`. Live, between two gmail.com accounts:

| Step | Request | Response `pendingOwner` |
|---|---|---|
| A | `permissions.create(body={type: user, role: writer, emailAddress, pendingOwner: true}, sendNotificationEmail=True, supportsAllDrives=True)` | `false` |
| B | `permissions.get` of that permission | `false` |
| C | `permissions.update(permissionId, body={role: writer, pendingOwner: true}, supportsAllDrives=True)` | `true` |
| C2 | `permissions.get` again | `true` |

So **create ignores `pendingOwner`, and update sets it**, contrary to the guide's "creating". Step A alone grants the recipient writer access and nothing else.

This PR doesn't send the request: doing so grants writer access as a side effect, and whether the tool should is a product decision (#1601). The consent message says the tool doesn't send one and points to the Share dialog.
