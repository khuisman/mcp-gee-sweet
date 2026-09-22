# Gmail Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/gmail.py`

Fixtures: see [`docs/qa/setup.md`](../setup.md). Substitute `{MESSAGE_ID}`, `{THREAD_ID}`, and `{DRAFT_ID}` from live calls or `fixtures.local.md` when present.

> **Auth note:** OAuth (personal mailbox) is the practical path for live Gmail QA. Service accounts need domain-wide delegation to impersonate a user — without it, expect auth/mailbox errors. Prefer a dedicated QA inbox; treat `send_message` / `delete_message` as destructive.

---

## `list_messages`

### TC-GM01: List recent inbox messages

**Prompt**
> "List my 5 most recent inbox messages"

**Checks**
- Returns `messages` as a list (may be empty)
- Each item has `id` and `thread_id`
- No top-level `error`

---

### TC-GM02: Invalid label filter returns API error

**Prompt**
> "List messages with label_ids=['TOTALLY_INVALID_LABEL_XYZ']"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
- Error text comes from the Gmail API

---

## `get_message`

### TC-GM03: Fetch a known message

**Setup:** capture a `message_id` from TC-GM01 (or `{MESSAGE_ID}`)

**Prompt**
> "Get the full content of message {MESSAGE_ID}"

**Checks**
- Returns `id`, `thread_id`, `headers` (at least subject/from), `body_plain` and/or `body_html`, `attachments` (list, may be empty)
- No `error` field

---

### TC-GM04: Non-existent message ID

**Prompt**
> "Get message 'totally-invalid-message-id-xyz'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `list_threads`

### TC-GM05: List threads with a query

**Prompt**
> "List threads matching query 'in:inbox' with max_results=5"

**Checks**
- Returns `threads` list; each item has `id`
- Optional `next_page_token` only when more pages exist
- No top-level `error`

---

### TC-GM06: Invalid label filter returns API error

**Prompt**
> "List threads with label_ids=['TOTALLY_INVALID_LABEL_XYZ']"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `get_thread`

### TC-GM07: Fetch a known thread

**Setup:** capture `thread_id` from TC-GM01 / TC-GM05

**Prompt**
> "Get all messages in thread {THREAD_ID}"

**Checks**
- Returns `id` and `messages` (non-empty for a real thread)
- Each message has `id` and headers/body fields shaped like `get_message`
- No `error` field

---

### TC-GM08: Non-existent thread ID

**Prompt**
> "Get thread 'totally-invalid-thread-id-xyz'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `list_labels`

### TC-GM09: List system and user labels

**Prompt**
> "List all Gmail labels"

**Checks**
- Returns a list including system labels such as `INBOX` / `UNREAD` / `SENT`
- Each item has `id`, `name`, `type`
- No top-level `error`

---

### TC-GM10: Auth / API failure surfaces as error

**Setup:** only runnable when credentials lack Gmail scope or mailbox access (otherwise note N/A)

**Prompt**
> "List all Gmail labels"

**Checks**
- If the call fails, result is `{"error": "..."}` — not a crash
- 🔍 **Hard to force with valid OAuth** — note if observed

---

## `send_message`

### TC-GM11: Send a QA message ⚠️ destructive

**Prompt**
> "Send an email to myself with subject 'mcp-gee-sweet-qa-send' and body 'QA send_message test'"

**Checks**
- Returns `id`, `thread_id`, `label_ids` (includes `SENT` or similar)
- Message appears via follow-up `list_messages(query='subject:mcp-gee-sweet-qa-send')`
- No `error` field

---

### TC-GM12: Send with invalid recipient returns error

**Prompt**
> "Send an email to 'not-an-email' with subject 'qa' and body 'x'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `create_draft`

### TC-GM13: Create a draft ⚠️ destructive

**Prompt**
> "Create a draft to myself with subject 'mcp-gee-sweet-qa-draft' and body 'QA draft'"

**Checks**
- Returns draft `id` and nested `message.id`
- Draft visible in Gmail drafts (or via API follow-up)
- No `error` field

---

### TC-GM14: Create draft with invalid attachment shape

**Prompt**
> "Create a draft to myself with subject 'qa' body 'x' and attachments=[{}]"

**Checks**
- Returns `{"error": "..."}` mentioning `local_path` / `content_base64` (or API error) — not a crash

---

## `send_draft`

### TC-GM15: Send an existing draft ⚠️ destructive

**Setup:** draft from TC-GM13 (`{DRAFT_ID}`)

**Prompt**
> "Send draft {DRAFT_ID}"

**Checks**
- Returns sent message `id` and `thread_id`
- Draft is no longer in drafts
- No `error` field

---

### TC-GM16: Send non-existent draft

**Prompt**
> "Send draft 'totally-invalid-draft-id-xyz'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `reply_to_message`

### TC-GM17: Reply in-thread ⚠️ destructive

**Setup:** `{MESSAGE_ID}` from TC-GM11 or inbox

**Prompt**
> "Reply to message {MESSAGE_ID} with body 'mcp-gee-sweet-qa-reply'"

**Checks**
- Returns `id` and same `thread_id` as the original
- Follow-up `get_thread` shows the reply
- No `error` field

---

### TC-GM18: Reply to non-existent message

**Prompt**
> "Reply to message 'totally-invalid-message-id-xyz' with body 'hi'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `modify_labels`

### TC-GM19: Mark a message unread then read ⚠️ destructive

**Setup:** `{MESSAGE_ID}` from an inbox message you may mutate

**Prompt**
> "Add UNREAD to message {MESSAGE_ID}, then remove UNREAD from it"

**Checks**
- Both calls return `id` / `label_ids` without `error`
- After remove, `UNREAD` is absent from `label_ids` (or confirmed via `get_message`)

---

### TC-GM20: Missing target returns validation error

**Prompt**
> "Modify labels: add STARRED but do not pass message_id or thread_id"

**Checks**
- Returns `{"error": "..."}` mentioning exactly one of `message_id` or `thread_id`

---

## `trash_message`

### TC-GM21: Trash a disposable message ⚠️ destructive

**Setup:** send or use a disposable `{MESSAGE_ID}`

**Prompt**
> "Trash message {MESSAGE_ID}"

**Checks**
- Returns `action: 'trashed'` and `label_ids` including `TRASH` (or equivalent)
- No `error` field

---

### TC-GM22: Trash non-existent message

**Prompt**
> "Trash message 'totally-invalid-message-id-xyz'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception

---

## `delete_message`

### TC-GM23: Permanently delete a trashed disposable message ⚠️ destructive

**Setup:** prefer a message already in trash from TC-GM21; confirm operator intent

**Prompt**
> "Permanently delete message {MESSAGE_ID}"

**Checks**
- Returns `{"message_id": ..., "action": "deleted"}`
- Subsequent `get_message` returns an error
- No top-level exception

---

### TC-GM24: Delete non-existent message

**Prompt**
> "Permanently delete message 'totally-invalid-message-id-xyz'"

**Checks**
- Returns `{"error": "..."}` — not a top-level exception
