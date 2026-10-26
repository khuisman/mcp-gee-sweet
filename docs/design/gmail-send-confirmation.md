# Safe-by-Default Gmail Sending

**Date:** 2026-10-25
**Issue:** #1081 (spec revised from the design pass in its thread). Follow-ups: #1235 (confirming on 2026-07-28 connections), #1236 (the same capability-only check in the OAuth re-authorization offer).

## Problem

`send_message`, `reply_to_message` and `send_draft` delivered mail immediately, guarded only by `destructiveHint`. Clients treat that as a hint and skip it once a tool is auto-approved, and an instruction in the prompt can be lost when an agent's context is compacted. So the gate has to be in the server.

## Shape

`GMAIL_SEND=confirm` (the default) never delivers on the agent's call alone:

1. `send_message` and `reply_to_message` compose the message as before, then save it with `drafts.create` instead of `messages.send`. A reply carries the original's `threadId`, so the held draft sits in the thread.
2. Every send then goes through `_confirm_and_send_draft`, which `send_draft` uses too:
   - It reads the draft back (`drafts.get(format="full")`) and builds the confirmation from the stored message. Gmail stamps the draft's From when storing it (checked live), so the form shows the real sender, not the tool's arguments.
   - It computes recipient flags (`_recipient_flags`) from the stored To/Cc/Bcc.
   - If the call can't elicit (`_can_elicit_form`), it returns the held-draft result.
   - Otherwise it asks through `ctx.elicit` with a one-field form (`send: bool`, required, no default), bounded by `_CONFIRM_TIMEOUT_SECONDS`.
   - Only an accepted form with `send` true continues. It re-reads the draft (`format="minimal"`) and sends with `drafts.send({"id": draft_id})` only if the message ID matches the one the form was built from.
3. Every other outcome returns `{"sent": false, "reason", "draft_id", "message", "recipient_flags", "note"}`. The reasons are `no_elicitation`, `declined`, `cancelled`, `timeout`, `error`, and `changed`.

`GMAIL_SEND=direct` keeps the old code paths unchanged. The only change there is that results gain `sent: true`, so both modes share one result shape.

## Decisions

**Draft first, then ask.** The draft exists before the question, so every non-yes outcome, including a cancelled tool call or a dropped connection mid-form, leaves something the user can find in Gmail. Asking first and composing after would lose the message on every refusal.

**Detection needs `can_send_request`.** On an MCP 2026-07-28 connection, mcp 2.3.0 still reports the client's form capability, but `session.can_send_request` is `False` and `ctx.elicit` raises `NoBackChannelError` (probed in the design pass, and confirmed again by this PR's in-process `mcp.Client(mode="2026-07-28")` test and live run). A capability-only check, like `reauth._supports_url_elicitation`, would elicit and fail. A bare `elicitation: {}` counts as form support, matching mcp's own `_require_capability`.

**`NoBackChannelError` is caught in the tool.** It's an `MCPError`, so letting it propagate would end the call as a protocol error and lose `draft_id`. It's the backstop for a channel that drops between the check and the request. In this PR's own tests it also covered the 2026-07-28 path when the `can_send_request` check was removed as a mutation check.

**Confirmed content = sent content, by message ID.** `drafts.update` replaces a draft's message ID and keeps its draft ID (checked live before implementing: one `update_draft` gave the draft a new message ID under the same draft ID). So the message ID recorded at confirmation identifies what the user saw, and the hash fallback the spec allowed wasn't needed. `drafts.send` has no precondition, so the check is a separate read, and a short window remains (`docs/known-limitations.md`). `send_draft` keeps `draft_id` as its only argument, since `drafts.send` also accepts replacement content.

**Organization = the primary address's domain plus alias domains.** `_own_addresses` now also records `gmail_primary_address` (`isPrimary` from `sendAs.list`, else `getProfile`). A consumer primary (`gmail.com`, `googlemail.com`) turns the outside-organization flag off. Keying it on "any alias is a consumer domain" instead would wrongly disable the flag for a Workspace user with an external send-as alias. An unknown primary returns `outside_organization_unchecked` instead of an empty list, so the result never implies every recipient is inside.

**Unrecognized `GMAIL_SEND` falls back to `confirm`.** A typo should fail safe, not send.

## Not done here

Confirming on 2026-07-28 connections through the `InputRequiredResult` round trip is #1235. On those connections mail stays a draft.
