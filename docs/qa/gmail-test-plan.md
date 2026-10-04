# Gmail — QA Test Plan

**Status:** draft (2026-09-26), scoped under [#803](https://github.com/khuisman/mcp-gee-sweet/issues/803)
**Source under test:** `src/mcp_gee_sweet/tools/gmail.py` (11 tools)
**Case file:** [`tests/gmail.md`](tests/gmail.md) (TC-GM01–45. TC-GM26 is the #792 charset case, so the §4.2 cases start at 27.)

This is the plan of record for testing the Gmail domain: what the mailbox fixture looks like, which behaviors need live coverage, and which gaps are tooling or product gaps rather than test gaps.

---

## 1. Where coverage stands today

| Layer | State |
|---|---|
| Unit (`tests/test_gmail.py`, 59 tests) | Strong on `_reply_recipients` (#791: 20 cases). Thin on MIME building and payload parsing (see §5). |
| Live — reply routing (TC-GM23–25) | ✅ Run 2026-09-26 on PR #815, both rounds. |
| Live — everything else (TC-GM01–22) | ❌ **Never run.** No `**Result**` exists in `tests/gmail.md`, `results/`, or `runs/`. #786 merged with unit tests only. |
| Live — auth degradation (TC-I31–34, `infra.md`) | ✅ Run on #790. |
| Smoke suite (`runs/README.md`) | ❌ No Gmail entry. A shared-layer regression that breaks Gmail passes Smoke. |
| Fixtures (`setup.md`, `fixtures.template.md`) | ❌ No Gmail section. `operations.yaml` names `TEST_MESSAGE_ID`/`TEST_THREAD_ID` but nothing creates them. |

TC-GM01–22 also predate the prescriptive-case rule: most are one-line natural-language prompts ("List my 5 most recent inbox messages") with no exact tool name or params, and read against whatever happens to be in the inbox. They need rewriting against the fixture set below. TC-GM23–25 are the reference style.

---

## 2. Testability constraints

Things about the tool surface that shape how every case has to be written:

1. **The QA mailbox can't create its own inbound mail.** `send_message` only produces mail *from* the mailbox under test. Two ways around it (see §3.1):
   - **A second, sender mailbox** (the maintainer's personal account, through the global `mcp-gee-sweet` server) sends real mail to the QA mailbox. That gives genuinely delivered messages: a real foreign `From`, Gmail's own MIME and `Message-ID`, real spam/category filtering, and two-party threads.
   - **`users.messages.insert`** from a scratch script (the TC-GM23 pattern) for anything `send_message` can't express: a custom `Reply-To`, a non-UTF-8 charset, a `multipart/related` inline image, a pre-labeled `SPAM`/`TRASH` message. `insert` works under `gmail.modify`; confirmed on PR #815.
2. **No draft cleanup.** There's no `list_drafts`/`delete_draft`. Every `create_draft` that isn't then sent leaves a draft behind for good (via the tools). Cases must either send the draft (TC-GM15) or clean up by script.
3. **No untrash.** `trash_message` is one-way through the tools. Whether `modify_labels(remove_label_ids=["TRASH"])` restores a message is **unverified**; the API has a dedicated `untrash` endpoint. Test it once (TC-GM37) and record the answer here either way.
4. **No label create/delete.** User-label cases need a pre-existing label, which the fixture script creates.
5. **No attachment download.** `get_message` surfaces `attachment_id`, but nothing can fetch the bytes (out of scope per `decision-gmail-domain.md`). Attachment cases can only check metadata round-trips.
6. **"Other people" = the sender mailbox, or plus-addresses of the QA mailbox.** Plus-addresses aren't send-as aliases, so `_own_addresses` treats them as third parties. They're enough for recipient-routing cases. Use the sender mailbox when the case needs a genuinely different account, for example a reply that must actually be delivered elsewhere. Mail goes only between these two mailboxes. Any `@example.invalid` address is fine as a *planted* `From` (inserted, never sent to).
7. **Sending to yourself is one message, not two.** A message to the mailbox or a plus-address of it comes back as one ID labeled `SENT`+`INBOX` (observed on PR #815). Cases must not expect a separate delivered copy.
8. **OAuth only.** Every case except the auth ones is ⚠️ requires-oauth. The SA server can only exercise TC-I31.
9. **Token scope and API enablement.** The server's `token.json` must include `gmail.modify`, and the Gmail API must be enabled in the server's Cloud project. Checked 2026-09-26 with `list_labels`: `mcp-gee-sweet-oauth` and `mcp-gee-sweet-kai-oauth` both reach the QA mailbox (`mcp-gee-sweet-kit` did on PR #815). The global `mcp-gee-sweet` server first got `403 accessNotConfigured` because its Cloud project didn't have the Gmail API enabled. It worked once the API was enabled the same day. Before a pass, run `list_labels` on every slot you'll use. A slot missing either piece fails every Gmail call. That reads like a product failure but isn't one.

---

## 3. Fixture mailbox

### 3.1 Accounts

| Role | Account | Reached through | `.env` key |
|---|---|---|---|
| **QA mailbox** (under test) | The Workspace fixture-owning account (the one Playwright signs into, `playwright_oauth.md`) | `mcp-gee-sweet-oauth` / `-kai-oauth` (main checkout), or a lane slot reset to the release commit | `TEST_GMAIL_ADDRESS` |
| **Sender mailbox** (external party) | The maintainer's personal Google account | The global `mcp-gee-sweet` server only | `TEST_GMAIL_SENDER_ADDRESS` |

Keep both addresses in `.env`, never in a tracked file.

The sender mailbox is only a way to produce inbound mail and a real second party. It is **never** the system under test, and its results don't count toward a pass: the global server may run a different code version than the release candidate. It sends only to `TEST_GMAIL_ADDRESS` (or its plus-addresses). A case must not read, label, or trash anything in the sender mailbox except `[mcp-qa`-subject messages that either mailbox sent as part of QA: its own fixture sends, and the replies and sends TC-GM43–45 deliver to it. It's a personal inbox.

**Prerequisite:** the Gmail API must be enabled in the global server's Cloud project. It was enabled on 2026-09-26 and confirmed with `list_labels` on `mcp-gee-sweet`. If the server ever returns `403 accessNotConfigured` again, that error names the project and gives the enable link.

### 3.2 Seed script

Add `scripts/qa_gmail_fixtures.py` (new), modeled on the TC-GM23 setup snippet: `_oauth_creds()` + `build("gmail", "v1")`, `users.messages.insert` only, never `send`. Requirements:

- **Idempotent.** Every seeded message carries a stable `X-MCP-QA-Fixture: <key>` header and subject prefix `[mcp-qa:<key>]`. On rerun, look each key up (`q=subject:"[mcp-qa:<key>]"`) and reuse it instead of inserting a duplicate.
- **Isolated.** Apply one user label, `mcp-qa-fixture` (created by the script if missing), to every fixture. Read cases query `label:mcp-qa-fixture` so they never depend on real inbox contents.
- **Writes IDs to `.env`**, not to any tracked file (`no resource IDs in commits`).
- **`--reset` flag** trashes every `label:mcp-qa-fixture` message and all `[mcp-qa` drafts, then reseeds. This is also the draft-cleanup path that item 2 above lacks.

### 3.3 Fixture set

**Source** says how each fixture gets made. **Sent** means the sender mailbox really sends it, so Gmail builds and delivers it. The seed script does this through the Gmail API with the sender mailbox's token, not with `send_message` tool calls (#821). A 3 MB body can't be passed as a tool argument, and `send_message` can't build a real `message/rfc822` forward. **Inserted** means the seed script plants it with `messages.insert`, because `send_message` can't express the shape. Prefer sent wherever it's possible: an inserted message is only as realistic as the MIME we write by hand. Two of the open questions depend on exactly that. Whether Gmail hands back a large body by `attachmentId` (GM30), and how it lays out a forwarded message (GM29), are really questions about Gmail's own storage, so their fixtures come from real delivery.

| Key | Source | Shape | `.env` key | Used by |
|---|---|---|---|---|
| `plain` | Sent | Single `text/plain` from the sender mailbox; lands `INBOX`+`UNREAD` | `TEST_MESSAGE_ID` | GM01, 03, 19 |
| `alt-unicode` | Sent | `body` + `body_html`, non-ASCII subject and body, astral emoji | `TEST_GMAIL_UNICODE_ID` | GM27 |
| `attachments` | Sent + Inserted | Sent: body + small PDF + CSV. Inserted: a `multipart/related` inline PNG with `Content-ID` and **no filename** (`send_message` can't build `related`) | `TEST_GMAIL_ATTACH_ID`, `TEST_GMAIL_INLINE_ID` | GM28, 46 |
| `thread` | Sent (both sides) | Sender sends; the QA mailbox replies; the sender replies again. A real two-party, 3-message thread with Gmail-generated `Message-ID`/`References` | `TEST_THREAD_ID` | GM05, 07, 33, 43 |
| `reply-to` | Inserted | Foreign `From: noreply@example.invalid`, `Reply-To` = `+tc-gm23` (`send_message` has no `Reply-To` param) | `TEST_GMAIL_REPLYTO_ID` | GM23 (replaces its inline setup) |
| `forwarded` | Sent | Outer body, then a forwarded message as a real `message/rfc822` part named `forwarded.eml` | `TEST_GMAIL_FWD_ID` | GM29 |
| `large-body` | Sent | `body` of ~3 MB plain text | `TEST_GMAIL_LARGE_ID` | GM30 (#803's `attachmentId` question) |
| `over-cap-thread` | Sent | Several sender↔QA replies, each with a large body, until full-format size exceeds `MAX_TOOL_RESPONSE_CHARS` | `TEST_GMAIL_BIG_THREAD_ID` | GM31 |
| `latin1` | Inserted | `text/plain; charset=iso-8859-1` body with `é`/`ñ` (`send_message` always writes UTF-8) | `TEST_GMAIL_LATIN1_ID` | GM32 (#792) |
| `page-N` | Inserted | 7 tiny messages tagged `[mcp-qa:page]` (inserted to avoid 7 real sends per reseed) | — | GM34 |
| `spam` / `trash` | Inserted | One each, inserted with the `SPAM` / `TRASH` label. Don't try to get real spam delivered; filtering isn't deterministic. | — | GM35 |
| label | Script | User label `mcp-qa-fixture`, applied by the seed script to every fixture in the QA mailbox, sent ones included | `TEST_GMAIL_LABEL_ID` | GM36, all read cases |

`scripts/qa_gmail_fixtures.py` (#821) does all of it: `seed` inserts and labels, `send` delivers the sent rows, and a second `seed` labels those and records their IDs. See `setup.md`'s Gmail section.

**Seeded live 2026-09-26.** Gmail's spam filter put three sent fixtures (`plain`, `attachments`, `large-body`) in Spam, so `seed` now moves every sent fixture back to `INBOX`. That filtering can recur on any reseed.

---

## 4. Case plan

### 4.1 Rewrite existing cases (TC-GM01–22)

Keep the IDs and intent. Rewrite each to name the exact tool and params and to read from fixtures instead of the live inbox. For example, TC-GM01 becomes `list_messages(query="label:mcp-qa-fixture", max_results=50)`, checking that `{TEST_MESSAGE_ID}` is present. Specific fixes while rewriting:

- **GM11/13/15/17/21:** send and draft to a `+tc-gmNN` plus-address, never the bare mailbox, and use `[mcp-qa]` subjects so `--reset` can sweep them.
- **GM11:** also assert `SENT` is in `label_ids` (currently "SENT or similar").
- **GM13:** follow up with `get_message(message.id)` and assert `label_ids` includes `DRAFT`. Today the check is "visible in Gmail drafts", which no tool can confirm.
- **GM17:** assert the reply's `headers.in_reply_to` equals the original's `message_id`, `references` ends with it, and the subject has exactly one `Re: `. Today it only checks `thread_id`.
- **GM19:** add a thread-scope variant (`thread_id={TEST_THREAD_ID}`, add/remove `STARRED`) and assert every message in the response changed.
- **GM20:** add the other two validation branches: both `message_id` and `thread_id` passed, and neither `add_label_ids` nor `remove_label_ids`.
- **GM10:** drop it. TC-I32 covers this deterministically with a scope-less token copy.

### 4.2 New cases (TC-GM27+)

| TC | Tool(s) | What it proves | Kind |
|---|---|---|---|
| GM27 | `get_message` | Unicode subject, body, and emoji decode intact; `body_plain` and `body_html` both populated | read |
| GM28 | `get_message` | Both attachments (PDF, CSV) listed with filename, MIME type, size, `attachment_id`. The inline PNG (`inline` fixture) is listed with `filename: null`; Gmail stores it by `attachmentId` (§5, P3: not a defect). | read |
| GM29 | `get_message` | `body_plain` is the *outer* message's body; the `.eml` is listed as a `message/rfc822` attachment (§5, P2: not a defect with Gmail's real layout) | read |
| GM30 | `get_message`, `get_thread` | `large-body` (Gmail delivers both 3 MB parts by `attachmentId`, #825). Without `local_path`: the size-cap error, naming `local_path`, since ~6 MB exceeds the default cap. With `local_path`: the written JSON has `body_plain` (3,000,002 chars) and `body_html` (3,037,987 chars) filled, `attachments: []`, no `body_fetch_errors`. Same for `get_thread` on its thread. Written in the #825 PR (#829). | read |
| GM31 | `get_thread` | Over-cap thread returns the size-cap error, not a dropped connection or a truncated body, and the error points at `include_body=False`. With `include_body=False` the same thread lists its 3 message IDs and headers with no bodies (#793). | read |
| GM32 | `get_message` | Latin-1 body decodes correctly. A zero-setup regression companion to TC-GM26: #792 closed with the finding that Gmail transcodes every text part to UTF-8, so this is expected to **pass**. | read |
| GM33 | `get_thread` | 3 messages in chronological order, each shaped like `get_message`, `in_reply_to`/`references` populated | read |
| GM34 | `list_messages`, `list_threads` | `max_results=3` over the 7 `page` fixtures: `next_page_token` present, page 2 has no overlap with page 1, final page has no token. Also `max_results=0` and `9999` clamp without error. | read |
| GM35 | `list_messages` | The `spam`/`trash` fixtures are absent by default and present with `include_spam_trash=True` | read |
| GM36 | `list_labels`, `modify_labels` | User label appears with `type: "user"`; add and remove it by ID on a throwaway sent in the case (not on a fixture: removing the fixture label would hide it from every read case) | write |
| GM37 | `trash_message`, `modify_labels` | Trash a throwaway, trash it again (idempotent or clean error, record which), then try `remove_label_ids=["TRASH"]` and record whether it restores the message (§2 item 3) | write, 🔍 product decision |
| GM38 | `send_message` | `body_html` + two attachments (one `local_path`, one `content_base64`, one without `mime_type`) to a plus-address; `get_message` shows `multipart/mixed` with alt body and both attachments. Record the missing-`mime_type` part's type (#802 item 3). | write |
| GM39 | `send_message` | `cc` and `bcc` as lists: the sent copy's `headers.bcc` is present, `cc` is exact | write |
| GM40 | `send_message` | Subject containing `\n` (header-injection attempt) returns `{"error": ...}` and sends nothing. Local probe: `HeaderParseError` (header-shaped line) or `HeaderWriteError` (any other newline) is raised inside the `try`, so this should pass (§5). | write, security |
| GM41 | `create_draft` → `send_draft` | Draft with attachments and HTML survives `send_draft` byte-for-byte in metadata (filename, size) | write |
| GM42 | `reply_to_message` | Reply to a message with no Subject header: subject is exactly `Re:`. Reply to a `RE: foo` subject: no doubled prefix. | write |
| GM43 | `reply_to_message` | Reply into the 3-message `thread` from its middle message: `references` chains all prior IDs, reply lands in the same thread. M2 was sent by the QA mailbox, so the reply is delivered to the sender mailbox | write, cross-mailbox |
| GM44 | `reply_to_message` (QA) → `list_messages` (sender) | End-to-end delivery. The QA mailbox replies to the `plain` fixture. On the sender side, `list_messages(query='subject:"[mcp-qa:plain]"')` shows the reply arrived in the **same thread** as the original. Proves `In-Reply-To`/`References` thread correctly in the recipient's mailbox, not just in ours. Plus-address cases can't show this. | write, cross-mailbox |
| GM45 | `send_message` (QA) → `get_message` (sender) | QA sends to the sender mailbox with `cc` = a QA plus-address and `bcc` = another. On the sender side, `get_message` shows `cc` present and **no** `bcc` header. Bcc must be stripped from delivered copies; GM39 only sees the sender's copy. | write, cross-mailbox |
| GM46 | `get_message` | `include_body=False` on the `attachments` fixture: headers, snippet, labels, and `size_estimate` present; no `body_plain`, `body_html`, or `attachments` key, since Gmail's `metadata` format returns no payload parts (#793) | read |

Every write case uses a `+tc-gmNN` plus-address and an `[mcp-qa:tc-gmNN]` subject (so `reset` sweeps it), and ends with a **Cleanup** step.

### 4.3 Smoke entry

Add two rows to the Smoke suite in `runs/README.md`:

- **TC-GM01** `list_messages` (read path, needs only the label fixture)
- **TC-GM11** `send_message` to a plus-address (write path; exercises MIME build + send)

Both need an OAuth slot whose token has `gmail.modify`; Smoke should record `SKIP(no-gmail-scope)` rather than FAIL on a slot without it.

### 4.4 Concurrency

No Gmail tool fans out with `asyncio.gather`, and there's no Gmail cache, so no TC-I24/TC-I02-style barrier cases are needed. `reply_to_message` makes 3–4 sequential calls; it's covered by the ordinary cases.

In a sharded release pass, run Gmail as **one shard on one slot**: write cases share one mailbox, and parallel shards would see each other's `[mcp-qa]` messages in list results.

---

## 5. Unit-test gaps

Found by reading `test_gmail.py` against `gmail.py` and running the helpers directly (`uv run python3`, static verification only, no API calls):

| # | Gap | Local observation |
|---|---|---|
| P1 | `_extract_bodies_and_attachments`: a `text/plain` part with `attachmentId` and no filename | Classified as an attachment, `body_plain` is `None`. Whether Gmail ever sends this is GM30's question. |
| P2 | Same function: `message/rfc822` part ahead of the outer body | Depth-first walk takes the **forwarded** message's `text/plain` as `body_plain` (`"inner body"` returned, outer body lost). Real only if Gmail expands the rfc822 part with `data` inline; GM29 settles it. |
| P3 | Same function: inline image with inline `data`, no filename, no `attachmentId` | Not listed in `attachments` at all. |
| P4 | `_build_raw_message` attachment branches (`local_path`, `content_base64`, non-`application/*` type, missing both → `ValueError`) | No unit tests. Local probe: CSV via `content_base64` builds correctly as `text/csv` with filename. |
| P5 | `_build_raw_message` `body_html` alone and `body_html` + attachments | No unit tests for either `multipart/alternative` path. |
| P6 | Header injection via `subject` | Not tested. Local probe: stdlib raises `HeaderParseError`, which the tool's `try` turns into `{"error": ...}`. Worth pinning with a test. |
| P7 | `modify_labels` both-targets and no-labels branches | Only the missing-target branch is tested. |
| P8 | Reply subject normalization (`""`, `RE:`, `Fwd:`) | Not tested directly. |
| P9 | `list_*` `max_results` clamping; `get_*` size-cap path | Not tested. |
| — | Empty `to` | Emits a bare `To: ` header. Gmail accepted it on TC-GM25 step 3, so no action needed. |

**Live outcome (2026-09-26, `get_message` on `mcp-gee-sweet-oauth`, raw layout via the seed script's `inspect`):**
- **P1 is confirmed and filed as #825.** A ~3 MB body arrives by `attachmentId`, while a ~405 KB body still arrives inline. The #825 fix fetches it with `users.messages.attachments.get`, which returns the part's raw bytes in its declared charset, not the UTF-8 that inline `body.data` is transcoded to (confirmed live with a latin-1 and a Shift-JIS body).
- **P2 doesn't reproduce.** Gmail puts the outer body first and the `message/rfc822` part after it.
- **P3 doesn't reproduce.** Gmail stores the nameless inline image by `attachmentId`, so it's listed.

P2 and P3 remain possible only for hand-built MIME, so they're unit-test material at most. P4–P9 are hardening tests. They can land together as one ticket.

---

## 6. Execution order

1. ~~Enable the Gmail API for the global server~~ (done 2026-09-26). Land the seed script and the `setup.md`/`fixtures.template.md` Gmail section, including the sender-side send checklist.
2. ~~Rewrite TC-GM01–22 and add TC-GM27–45.~~ Done in #822.
3. Run the whole file once on an OAuth slot with `gmail.modify` and record results. This closes #803. Repeat GM29/30 on a second, freshly sent seed, since they depend on how Gmail stores delivered mail.
4. ~~File defects for whatever GM28–30 reproduce, plus the P4–P9 unit-test ticket.~~ Done: #825 (P1) and #823 (P4–P9).
5. ~~Add the Smoke rows.~~ Done in #822.

## 7. Out of scope

- Service-account Gmail (#794) beyond TC-I31
- Attachment download, permanent delete, watch/push (`decision-gmail-domain.md`)
- Delivery to any address other than the two QA mailboxes (§3.1). Mail only goes between the QA mailbox and the sender mailbox, and sending anywhere else from a QA run is an outward-facing action we don't want automated.
