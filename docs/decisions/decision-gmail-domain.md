# Decision: Gmail Domain

**Date:** 2026-09-21
**Issue:** [#785](https://github.com/khuisman/mcp-gee-sweet/issues/785)

> This is a point-in-time record. It captures context, alternatives, and reasoning as they were understood on the date above — not the current state of the project.

## Background

Gmail is listed as in-scope in [Design Principles](../design.md) and sketched under v1.1.0+ on the [roadmap](../roadmap.md). Calendar is already wired as a single-file domain (`tools/calendar.py` + `gmail_service`-style lifespan client). Agents frequently need to read mail, send/reply, and organize labels — operations that require the Gmail API and cannot be expressed through Sheets/Drive/Docs tools.

## Use case

Give an AI client reliable primitives over a user's mailbox: search and read messages/threads, send and draft mail, reply in-thread, and apply organizational label changes (archive, read/unread, star, trash). Client-side workflows such as "find unanswered threads" or "send reminders" compose from these primitives and are intentionally **not** server tools ([composite-tool policy](decision-composite-tools.md)).

## Tool-count cost

**12 tools** in one module (`src/mcp_gee_sweet/tools/gmail.py`):

| Group | Tools | Count |
|---|---|---|
| Reading | `list_messages`, `get_message`, `list_threads`, `get_thread`, `list_labels` | 5 |
| Sending / drafts | `send_message`, `create_draft`, `send_draft`, `reply_to_message` | 4 |
| Organization | `modify_labels`, `trash_message`, `delete_message` | 3 |

This is comparable to Calendar's surface and stays within the "atomic primitives" inclusion test. No cache layer in v1 — list/get responses are live API calls with the shared response-size cap where lists or full bodies can grow large.

## Auth

Add `gmail_service = build("gmail", "v1", ...)` on `SpreadsheetContext` and three scopes:

- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/gmail.send`
- `https://www.googleapis.com/auth/gmail.readonly`

**Service accounts** need [domain-wide delegation](https://developers.google.com/workspace/gmail/api/auth/about-auth) to impersonate a user mailbox; OAuth (personal) works without delegation. Documented in `docs/auth.md` and the generated Gmail note in `docs/tools.md`.

## Alternatives considered

1. **Defer Gmail until Tasks** — rejected; issue #785 and design.md already prioritize Gmail as a communication primitive agents ask for often.
2. **Server-side composites** (`find_unanswered`, `send_reminders`) — rejected per composite-tool policy; agents can chain list/get/send.
3. **Separate narrower scope sets via `ENABLED_TOOLS` only** — still request all three Gmail scopes at auth time (Google's usual pattern for one consent screen); callers can still filter tools with `ENABLED_TOOLS` / the "Gmail only" subset.

## Decision

Implement the 12 primitives above, mirroring Calendar's registration / `execute_in_thread` / `{"error": str}` patterns. Out of scope for this decision: attachment *download* bytes, watch/push notifications, and the composites named above.
