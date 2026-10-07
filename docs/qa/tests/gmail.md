# Gmail Tools — QA Test Cases

Source: `src/mcp_gee_sweet/tools/gmail.py`. Plan of record: [`gmail-test-plan.md`](../gmail-test-plan.md).

> **Auth:** every case here is ⚠️ requires-oauth. Before running, call `list_labels` on the slot you'll use. If it returns the `gmail.modify` re-authorize error or `403 accessNotConfigured`, the slot can't run Gmail: record `SKIP(no-gmail-scope)`, not FAIL. The service-account path is covered only by TC-I31 (`infra.md`).

## Conventions

- **Fixtures.** Read cases use the seeded fixture set, never real inbox contents. Seed it with `scripts/qa_gmail_fixtures.py` (setup.md §"Gmail fixture setup") and run its `status` command first. Placeholders in `{TEST_…}` form are the `.env` keys that script writes. Every fixture carries the user label `mcp-qa-fixture` (`{TEST_GMAIL_LABEL_ID}`) and a `[mcp-qa:<key>]` subject.
- **Addresses.** `{QA}` is `TEST_GMAIL_ADDRESS`. `{QA+tag}` is its plus-address (`qa@example.com` → `qa+tag@example.com`). `{SENDER}` is `TEST_GMAIL_SENDER_ADDRESS`. Write cases send only to `{QA+tc-gmNN}` addresses, except the cross-mailbox cases (TC-GM44–45), which also send to `{SENDER}`. Nothing else is ever a recipient.
- **Subjects.** Every message a case sends or drafts has a subject starting `[mcp-qa:tc-gmNN]`, so `qa_gmail_fixtures.py reset` sweeps anything a failed run leaves behind. (TC-GM42's empty-subject message is the one exception; its Cleanup trashes it by ID.)
- **Sending to yourself is one message.** Mail to `{QA+tag}` comes back as one ID labeled `SENT`+`INBOX`, not a sent copy plus a delivered copy. Cleanup trashes that one ID.
- **Don't break fixtures.** Never trash a fixture, and never remove `mcp-qa-fixture` from one. Cases that change a fixture's labels (TC-GM19) restore them in the same case.
- **Sender mailbox.** TC-GM44–45 read the sender mailbox through the global `mcp-gee-sweet` server (`mcp__mcp-gee-sweet__*`). It's a personal inbox. Touch only `[mcp-qa`-subject messages there, and only the ones the case names. It may run different code than the release candidate, so it only observes; the QA-side call is the one under test.
- **Sharding.** Run the whole file as one shard on one slot. Write cases share a mailbox, and parallel shards would see each other's messages.
- **Order.** Run TC-GM33 (reads the `thread` fixture) before TC-GM43 (replies into it).

---

## `list_messages`

### TC-GM01: List the fixture set by label

**Action**
1. `list_messages` with `query: "label:mcp-qa-fixture"`, `max_results: 50`

**Checks**
- `messages` includes `{TEST_MESSAGE_ID}` and `{TEST_GMAIL_LATIN1_ID}`
- Every item has `id` and `thread_id`
- No `next_page_token` (the fixture set fits in one page of 50)
- No `error` field

---

### TC-GM02: Invalid label filter returns API error

**Action**
1. `list_messages` with `label_ids: ["TOTALLY_INVALID_LABEL_XYZ"]`

**Checks**
- Returns `{"error": "..."}`, not a tool exception
- The error text comes from the Gmail API (mentions the label)

---

### TC-GM34: Pagination and `max_results` clamping (`list_messages` + `list_threads`)

The 7 `page-N` fixtures share the subject prefix `[mcp-qa:page]`, and each is its own thread. Confirmed live 2026-09-26 that this query matches exactly those 7.

**Action**
1. `list_messages` with `query: "label:mcp-qa-fixture subject:(mcp-qa page)"`, `max_results: 3`
2. Same, plus `page_token` from step 1
3. Same, plus `page_token` from step 2
4. Repeat steps 1–3 with `list_threads` and the same params
5. `list_messages` with the same query and `max_results: 0`
6. `list_messages` with the same query and `max_results: 9999`

**Checks**
- Steps 1 and 2: 3 items each, `next_page_token` present, no ID in both pages
- Step 3: 1 item, no `next_page_token`. The 7 IDs across steps 1–3 are all distinct.
- Step 4: same shape for `threads` (3, 3, 1), each item with `id`, `snippet`, `history_id`
- Step 5: exactly 1 message (clamped up to 1), no `error`
- Step 6: all 7 messages, no `next_page_token`, no `error` (clamped down to 500)
- Don't check `result_size_estimate`. It's Gmail's estimate, not a count: live 2026-09-26, step 1 reported `201` for this 7-message query.

**Result (2026-10-06, PR #928 round 1) ✅ PASS (regression, #795's shared `_list_kwargs`/`_list_page`)**: via `mcp-gee-sweet-kit`. `list_messages` and `list_threads` both paged 3/3/1 with `next_page_token` on the first two pages only, and the 7 IDs were distinct. Thread items carry `id`, `snippet`, and `history_id`. `max_results: 0` returned exactly 1 message, and `9999` returned all 7 with no token.

---

### TC-GM35: Spam and trash are excluded unless asked for

The `spam` and `trash` fixtures are inserted already labeled `SPAM` / `TRASH`.

**Action**
1. `list_messages` with `query: "label:mcp-qa-fixture subject:(mcp-qa spam)"`
2. Step 1 again with `include_spam_trash: true`
3. `list_messages` with `query: "label:mcp-qa-fixture subject:(mcp-qa trash)"`
4. Step 3 again with `include_spam_trash: true`

**Checks**
- Steps 1 and 3: `messages` is empty
- Steps 2 and 4: exactly 1 message each
- No `error` field in any response

(Steps 1–2 confirmed live 2026-09-26 while writing this case: 0 then 1.)

---

## `get_message`

### TC-GM03: Fetch the plain fixture

**Action**
1. `get_message` with `message_id: "{TEST_MESSAGE_ID}"`

**Checks**
- `headers.subject` is `[mcp-qa:plain] plain text`
- `headers.from` contains `{SENDER}`; `headers.to` contains `{QA}`
- `headers.message_id` is non-empty
- `body_plain` is `mcp-gee-sweet plain fixture.` (ignore trailing whitespace); `body_html` is `null`; `attachments` is `[]`
- `label_ids` includes `{TEST_GMAIL_LABEL_ID}`
- No `error` or `body_decode_errors` field

---

### TC-GM04: Non-existent message ID

**Action**
1. `get_message` with `message_id: "totally-invalid-message-id-xyz"`

**Checks**
- Returns `{"error": "..."}`, not a tool exception

---

### TC-GM26: Non-UTF-8-labeled bodies still decode correctly (issue #792) ⚠️ requires-oauth

**Background:** #792 assumed `get_message`/`get_thread` garble ISO-8859-1 / Windows-1252 / Shift_JIS mail because they decode `body.data` as UTF-8 regardless of the part's `Content-Type` charset. PR #816 round 1 showed live that the premise is false. The Gmail API already transcodes every text part's `body.data` to UTF-8 but keeps the original charset label, so the UTF-8-only decode is correct and decoding with the declared charset garbles. This case now guards that: a part labeled with a non-UTF-8 charset must still come back as the right text. The fixtures are built from raw bytes, not `MIMEText`. `MIMEText(..., 'shift_jis')` silently emits `charset="iso-2022-jp"`, which never exercised Shift_JIS. The fixtures are *inserted* (not sent), so nothing leaves the QA mailbox.

**Setup:** insert both fixtures with a scratch script from the checkout under test, using the same OAuth token as the server under test (its saved scopes must include `gmail.modify`):

```bash
uv run python3 - <<'EOF'
import base64
from googleapiclient.discovery import build
from mcp_gee_sweet.auth import _oauth_creds

def mime(subject, parts):
    out = [
        b"MIME-Version: 1.0",
        b"To: qa@example.invalid",
        b"Subject: " + subject,
        b'Content-Type: multipart/alternative; boundary="tcgm26"',
        b"",
    ]
    for ctype, cte, body in parts:
        out += [b"--tcgm26", b"Content-Type: " + ctype, b"Content-Transfer-Encoding: " + cte, b"", body]
    out += [b"--tcgm26--", b""]
    return b"\r\n".join(out)

# A: iso-8859-1 quoted-printable plain part + genuine Shift_JIS base64 html part.
a = mime(b"TC-GM26 charset fixture A", [
    (b"text/plain; charset=iso-8859-1", b"quoted-printable", b"Caf=E9 cr=E8me, na=EFve"),
    (b"text/html; charset=shift_jis", b"base64", base64.b64encode("<p>こんにちは世界</p>".encode("shift_jis"))),
])
# B: windows-1252 8bit plain part (smart quotes and en dash are cp1252-only bytes).
b = mime(b"TC-GM26 charset fixture B", [
    (b"text/plain; charset=windows-1252", b"8bit", "“Smart quotes” – 5".encode("cp1252")),
])

g = build("gmail", "v1", credentials=_oauth_creds(), cache_discovery=False)
for label, raw in (("A", a), ("B", b)):
    r = g.users().messages().insert(userId="me", body={"raw": base64.urlsafe_b64encode(raw).decode()}).execute()
    print(label, r["id"], r["threadId"])
EOF
```

Record fixture A's IDs as `{CHARSET_FIXTURE_A_ID}` / `{CHARSET_THREAD_A_ID}`, and fixture B's message ID as `{CHARSET_FIXTURE_B_ID}`.

**Action**
1. `get_message` with `message_id: "{CHARSET_FIXTURE_A_ID}"`
2. `get_thread` with `thread_id: "{CHARSET_THREAD_A_ID}"`
3. `get_message` with `message_id: "{CHARSET_FIXTURE_B_ID}"`

**Checks**
- Step 1: `body_plain` is `Café crème, naïve` and `body_html` is `<p>こんにちは世界</p>` (ignore trailing whitespace), with no mojibake (`CafÃ©`, `縺薙ｓ…`) and no `�` replacement characters
- Step 2: the one message in `messages` has the same `body_plain` / `body_html` as step 1
- Step 3: `body_plain` is `“Smart quotes” – 5` (ignore trailing whitespace)
- No `error` or `body_decode_errors` field in any response

**Cleanup:** `trash_message` both fixtures.

**Result** (2026-09-26, PR #816 round 1, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **FAIL**. Step 1 `body_plain` = `CafÃ© crÃ¨me, naÃ¯ve` (mojibake). `body_html` = `<p>こんにちは世界</p>` (correct). Step 2 identical. No `error` field. Root cause, confirmed via raw `format=full` vs `format=raw` inspection: the Gmail API already transcodes every text part's `body.data` to UTF-8, while the part's `Content-Type` header keeps the original charset label. Wire bytes `Caf=E9` (iso-8859-1 QP) arrive in `body.data` as `Caf\xc3\xa9`, so decoding with the declared charset double-decodes. Note: Python's `MIMEText(..., 'shift_jis')` actually emits `charset="iso-2022-jp"`, so the fixture's HTML part never exercised Shift_JIS. A second probe with a raw base64 `charset=shift_jis` part and an 8bit `charset=windows-1252` part showed the same UTF-8 transcoding. `get_message` returned the Shift_JIS part as `縺薙ｓ縺ｫ縺｡縺ｯ荳也阜` (UTF-8 bytes that happen to be valid Shift_JIS). The cp1252 part came out correct only because byte `0x9d` is undefined in cp1252, which forced the UTF-8 fallback. The pre-#792 UTF-8-only decode was correct for all three. Both fixtures trashed.

**Result** (2026-09-26, PR #816 round 2 at `1daec0a`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS**. Step 1: `body_plain` = `Café crème, naïve`, `body_html` = `<p>こんにちは世界</p>`. Step 2: the one message has identical bodies. Step 3: `body_plain` = `“Smart quotes” – 5`. No mojibake, no `�`, and no `error` or `body_decode_errors` field in any response. Both fixtures trashed.


---

### TC-GM27: Unicode subject and bodies decode intact

**Action**
1. `get_message` with `message_id: "{TEST_GMAIL_UNICODE_ID}"`

**Checks**
- `headers.subject` is `[mcp-qa:alt-unicode] Ünïcødé ✓ 🎉 subject`
- `body_plain` is `Grüße aus Zürich — naïve café, 日本語, emoji 🎉🚀.` (ignore trailing whitespace)
- `body_html` contains `Grüße aus <b>Zürich</b> — naïve café, 日本語, emoji 🎉🚀.`
- No mojibake (`Ã`, `â€`) and no `�` in any header or body
- No `error` or `body_decode_errors` field

---

### TC-GM28: Attachment metadata, including a nameless inline image

**Action**
1. `get_message` with `message_id: "{TEST_GMAIL_ATTACH_ID}"`
2. `get_message` with `message_id: "{TEST_GMAIL_INLINE_ID}"`

**Checks**
- Step 1: `body_plain` is `mcp-gee-sweet attachments fixture: a PDF and a CSV.`
- Step 1: `attachments` has exactly 2 entries: `filename: "mcp-qa.pdf"` with `mime_type: "application/pdf"`, and `filename: "mcp-qa.csv"` with `mime_type: "text/csv"`. Each has a positive `size` and a non-null `attachment_id`.
- Step 1: the CSV's content does **not** leak into `body_plain` (it's an attachment, not a second text body)
- Step 2: `body_html` contains `cid:mcp-qa-inline-png`
- Step 2: `attachments` has one entry with `mime_type: "image/png"`, `filename: null`, and a non-null `attachment_id`. Gmail stores the nameless inline image by `attachmentId` (plan §5 P3, live 2026-09-26), so it is listed.

---

### TC-GM29: A forwarded message doesn't replace the outer body

**Action**
1. `get_message` with `message_id: "{TEST_GMAIL_FWD_ID}"`

**Checks**
- `body_plain` starts with `outer body — the forwarder's own note.` and does **not** contain `inner body`
- `attachments` includes an entry with `filename: "forwarded.eml"` and `mime_type: "message/rfc822"`
- No `error` field

Depends on how Gmail stores delivered mail (plan §5 P2). In a release pass, repeat on a second, freshly sent seed.

---

### TC-GM30: Large bodies Gmail delivers by `attachmentId` are fetched, capped, and writable via `local_path` (issue #825) ⚠️ requires-oauth

**Background:** Gmail returns a large text body (somewhere between ~400 KB and 3 MB) from `messages.get(format=full)` as a nameless part carrying `body.attachmentId`, with no inline `data`. Before #825, `get_message`/`get_thread` listed such parts as nameless attachments and returned `body_plain`/`body_html` as `null`. The fix fetches them with `users.messages.attachments.get`. That endpoint returns the part's raw bytes in its declared charset, unlike inline `body.data`, which Gmail transcodes to UTF-8 (TC-GM26), so the fetched bytes decode with the part's own charset. A ~6 MB message exceeds the default `MAX_TOOL_RESPONSE_CHARS`, so it hits the normal size-cap error, and `local_path` bypasses the cap. The parts' own decoded sizes are a lower bound on the response, so without `local_path` the error is raised before anything is downloaded (PR #829 round 2). Round 2 also remaps two common charset mislabels before decoding a fetched body: `us-ascii` is decoded as UTF-8 and `iso-8859-1` as windows-1252. Step 7 checks that. The early size check counts only parts whose charset guarantees at least one serialized character per byte, so a UTF-16 part over 1,000,000 bytes that serializes under the cap still comes back inline (PR #829 round 3); step 8 checks that. Fetch-failure reporting (`attachment_id` in `body_fetch_errors`, errors copied into the `local_path` manifest, a later inline part used as the fallback), a missing `data` field, and the bounded fetch concurrency can't be forced against the live API; unit tests cover them. Steps 1–4 use the seeded `large-body` fixture (`TEST_GMAIL_LARGE_ID`, a real delivery: both its 3 MB `text/plain` and `text/html` parts arrive by `attachmentId`; check with `uv run python scripts/qa_gmail_fixtures.py inspect`). Steps 5 and 7 use *inserted* fixtures: `messages.insert` produces the same `attachmentId` layout, confirmed live on #825.

**Setup:** confirm the server under test runs with the default `MAX_TOOL_RESPONSE_CHARS` (1,000,000). Pick a scratch directory `{OUT_DIR}` outside the repo. Insert the charset fixture with a scratch script from the checkout under test, using the same OAuth token as the server under test (its saved scopes must include `gmail.modify`):

```bash
uv run python3 - <<'EOF'
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from mcp_gee_sweet.auth import _oauth_creds

m = MIMEMultipart("alternative")
m.attach(MIMEText("Café crème brûlée TC-GM30.\n" * 110_000, "plain", "iso-8859-1"))
m.attach(MIMEText("<p>こんにちは TC-GM30</p>\n" * 200_000, "html", "shift_jis"))
m["To"] = "qa@example.invalid"
m["Subject"] = "TC-GM30 large charset fixture"
g = build("gmail", "v1", credentials=_oauth_creds(), cache_discovery=False)
r = g.users().messages().insert(userId="me", body={"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute()
print(r["id"])
EOF
```

Record the printed ID as `{LARGE_CHARSET_ID}`. (Python's `MIMEText` emits the `shift_jis` part as `charset="iso-2022-jp"`, per TC-GM26's note. Either way it's a non-UTF-8 charset that `attachments.get` returns untranscoded.)

Insert the mislabel fixture the same way. Its bytes are built by hand, since `MIMEText` always labels its charset correctly:

```bash
uv run python3 - <<'EOF'
import base64
from googleapiclient.discovery import build
from mcp_gee_sweet.auth import _oauth_creds

plain = "\u201cSmart\u201d \u2013 quotes TC-GM30.\n" * 120_000  # windows-1252 bytes, labeled iso-8859-1
html = "<p>Caf\u00e9 \u201cUTF-8\u201d TC-GM30</p>\n" * 120_000  # UTF-8 bytes, labeled us-ascii
lines = [b"MIME-Version: 1.0", b"To: qa@example.invalid", b"Subject: TC-GM30 mislabel fixture",
         b'Content-Type: multipart/alternative; boundary="tcgm29"', b""]
for ctype, body in ((b"text/plain; charset=iso-8859-1", plain.encode("cp1252")),
                    (b"text/html; charset=us-ascii", html.encode("utf-8"))):
    lines += [b"--tcgm29", b"Content-Type: " + ctype, b"Content-Transfer-Encoding: base64", b"",
              base64.encodebytes(body)]
lines += [b"--tcgm29--", b""]
g = build("gmail", "v1", credentials=_oauth_creds(), cache_discovery=False)
r = g.users().messages().insert(userId="me", body={"raw": base64.urlsafe_b64encode(b"\r\n".join(lines)).decode()}).execute()
print(r["id"])
EOF
```

Record the printed ID as `{MISLABEL_ID}`.

Insert the UTF-16 fixture: about 1.14 MB of UTF-16 bytes that serialize to under 600,000 characters, so it fits under the default cap even though its byte size doesn't (PR #829 QA round 2):

```bash
uv run python3 - <<'EOF'
import base64
from googleapiclient.discovery import build
from mcp_gee_sweet.auth import _oauth_creds

body = ("UTF-16 body line for TC-GM30.\n" * 19_000).encode("utf-16")
raw = (b"MIME-Version: 1.0\r\nTo: qa@example.invalid\r\nSubject: TC-GM30 utf-16 fixture\r\n"
       b"Content-Type: text/plain; charset=utf-16\r\nContent-Transfer-Encoding: base64\r\n\r\n"
       + base64.encodebytes(body))
g = build("gmail", "v1", credentials=_oauth_creds(), cache_discovery=False)
r = g.users().messages().insert(userId="me", body={"raw": base64.urlsafe_b64encode(raw).decode()}).execute()
print(r["id"])
EOF
```

Record the printed ID as `{UTF16_ID}`.

**Action**
1. `get_message` with `message_id: "{TEST_GMAIL_LARGE_ID}"`
2. `get_message` with `message_id: "{TEST_GMAIL_LARGE_ID}"`, `local_path: "{OUT_DIR}"`, then read the JSON file at the returned `local_path` and record its `thread_id` as `{LARGE_THREAD_ID}`
3. `get_thread` with `thread_id: "{LARGE_THREAD_ID}"`
4. `get_thread` with `thread_id: "{LARGE_THREAD_ID}"`, `local_path: "{OUT_DIR}/thread.json"`, then read that file
5. `get_message` with `message_id: "{LARGE_CHARSET_ID}"`, `local_path: "{OUT_DIR}/charset.json"`, then read that file
6. `get_message` with `message_id: "{TEST_GMAIL_ATTACH_ID}"`
7. `get_message` with `message_id: "{MISLABEL_ID}"`, `local_path: "{OUT_DIR}/mislabel.json"`, then read that file
8. `get_message` with `message_id: "{UTF16_ID}"` (no `local_path`)

**Checks**
- Step 1: the call fails with the size-cap error: it reads `get_message: the response would be at least 6037989 characters` (the two parts' decoded sizes) and says `Pass local_path to write the result to disk`. It returns in about a second, since nothing is downloaded. Not a dropped connection, not a truncated body
- Step 2: the response is exactly `{local_path, bytes_written, message_id}`, with `local_path` ending in `message_{TEST_GMAIL_LARGE_ID}.json`. In the file: `body_plain` is 3,000,002 characters and starts `mcp-gee-sweet large-body fixture line.`, `body_html` is 3,037,987 characters and starts `<pre>mcp-gee-sweet large-body fixture line.`, `attachments` is `[]`, and there is no `body_fetch_errors` or `body_decode_errors` key
- Step 3: the same pre-download error, naming `get_thread` (`would be at least 6037989 characters`) and `local_path`
- Step 4: the response has `thread_id` = `{LARGE_THREAD_ID}` and `message_count` = 1, and the file's one message has the same `body_plain` length as step 2
- Step 5: in the file, `body_plain` starts `Café crème brûlée TC-GM30.` and `body_html` starts `<p>こんにちは TC-GM30</p>`. Neither contains mojibake (`CafÃ©`) or `�`, and `attachments` is `[]`
- Step 6 (regression, real attachments unchanged): the PDF and CSV are still listed in `attachments` with their filenames and `attachment_id`s
- Step 7: the manifest has no `body_fetch_errors` or `body_decode_errors` key. In the file, `body_plain` starts `“Smart” – quotes TC-GM30.` (real curly quotes and an en dash, not C1 control characters such as `\u0093`), `body_html` starts `<p>Café “UTF-8” TC-GM30</p>` (no `Ã©` or `â€œ`), and `attachments` is `[]`
- Step 8: returns inline, **not** the size-cap error, even though the part is over 1,000,000 bytes. `body_plain` starts `UTF-16 body line for TC-GM30.` and contains no `�`; no `body_fetch_errors` or `body_decode_errors` key

**Cleanup:** `trash_message` with `message_id: "{LARGE_CHARSET_ID}"`, then `{MISLABEL_ID}`, then `{UTF16_ID}`. Delete `{OUT_DIR}`. Leave the seeded `large-body` fixture in place.

**Result** (2026-09-26, PR #829 round 1 at `e30c2d1`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS** on every listed check. Step 1: size-cap error naming `get_message`, 6,190,675 characters, and `Pass local_path`. Step 2: manifest `{local_path, bytes_written: 6190675, message_id}`, file named `message_{TEST_GMAIL_LARGE_ID}.json`. `body_plain` is 3,000,002 characters and `body_html` is 3,037,987 characters, both with the expected prefixes. `attachments` = `[]`, no error keys. The thread ID equals the message ID. Step 3: size-cap error naming `get_thread`, 6,190,757 characters. Step 4: `message_count` = 1, and the file's `body_plain` is 3,000,002 characters. Step 5: `body_plain` (2,970,000 characters) starts `Café crème brûlée TC-GM29.` and `body_html` (4,200,000 characters) starts `<p>こんにちは TC-GM29</p>`. Neither contains `Ã` or `�`, and `attachments` = `[]`. Step 6: `mcp-qa.pdf` and `mcp-qa.csv` are both still listed, with `attachment_id`s. Charset fixture trashed and `{OUT_DIR}` deleted. The PR still went back to the Dev for code-review findings that this case doesn't exercise (fetch-failure reporting, concurrency, charset mislabels, the manifest omitting errors). See the PR #829 comment.

**Result** (2026-09-26, PR #829 round 2 at `04dd085`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **FAIL**. All 7 listed steps passed. Steps 1 and 3: `would be at least 6037989 characters`, returned without downloading. Steps 2 and 4: the same lengths as round 1, with no error keys. Step 5: clean iso-8859-1 and iso-2022-jp bodies. Step 6: PDF and CSV still listed. Step 7: `“Smart” – quotes`, `<p>Café “UTF-8”`, no C1 controls, no `Ã`/`â€`/`�`, no error keys. The case fails on an unlisted probe of the new pre-download check. `_deferred_body_bytes` treats `body.size` (bytes in the part's own charset) as a lower bound on serialized characters, which is false for UTF-16, UTF-32 and iso-2022-jp. An inserted single-part `text/plain; charset=utf-16` message with a 1,188,002-byte body decodes correctly to 594,000 characters, and written via `local_path` it is 612,717 characters. Without `local_path`, `get_message` still refuses it: `the response would be at least 1188002 characters, over the 1000000-character safety cap`. Sent back to the Dev on PR #829. All three inserted fixtures trashed and `{OUT_DIR}` deleted.

**Result** (2026-09-26, PR #829 round 3 at `dca6ce4`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS**. Scoped re-verification of the size-floor fix: steps 1, 3, 7 and 8 were re-run. Steps 2, 4, 5 and 6 are unaffected by the fix's diff and passed in round 2. Steps 1 and 3: `would be at least 6037989 characters`, so the floor still fires for the ASCII fixture. Step 7: `“Smart” – quotes` and `<p>Café “UTF-8”`, with no C1 controls, `Ã`/`â€`, `�` or error keys (decoding now goes through `_codec_for`). Step 8: the UTF-16 fixture returned **inline** (589,674 characters, no size-cap error). `body_plain` is 570,000 characters and starts `UTF-16 body line for TC-GM30.`, with no `�` and no error keys. Both inserted fixtures trashed and `{OUT_DIR}` deleted.

---

### TC-GM32: Latin-1 body decodes correctly (seeded companion to TC-GM26)

**Background:** #792 closed with the finding that Gmail transcodes every text part's `body.data` to UTF-8 (see TC-GM26). The `latin1` fixture is a `charset=iso-8859-1` part that needs no setup script, so this case is a cheap regression check for the same behavior. Expected to **pass**.

**Action**
1. `get_message` with `message_id: "{TEST_GMAIL_LATIN1_ID}"`

**Checks**
- `body_plain` is `Café, niño, façade - ISO-8859-1 body (#792).` (ignore trailing whitespace)
- No mojibake (`CafÃ©`), no `�`, no `body_decode_errors` field

---

### TC-GM46: `include_body: false` returns headers without body or attachments (issue #793)

**Background:** `include_body: false` fetches with Gmail's `format='metadata'`, which returns headers but no payload parts (confirmed live 2026-10-04). So the result omits attachment metadata as well as the body.

**Action**
1. `get_message` with `message_id: "{TEST_GMAIL_ATTACH_ID}"`, `include_body: false`

**Checks**
- `id` is `{TEST_GMAIL_ATTACH_ID}`; `thread_id`, `snippet`, `label_ids`, `internal_date`, and a positive `size_estimate` are present
- `headers.subject` starts `[mcp-qa:`, `headers.from` contains `{SENDER}`, `headers.message_id` is non-empty
- No `body_plain`, `body_html`, `attachments`, `body_decode_errors`, `body_fetch_errors`, or `error` key

**Result** (2026-10-04, PR #885 round 1 at `47937d8`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS**. `id`, `thread_id`, `snippet` (`mcp-gee-sweet attachments fixture: a PDF and a CSV.`), `label_ids`, `internal_date` and `size_estimate` = 7893 present. `headers.subject` = `[mcp-qa:attachments] PDF + CSV`, `headers.from` = `{SENDER}`, `headers.message_id` non-empty. No body, attachment, error-list or `error` keys. The PR still went back to the Dev for code-review findings this case doesn't exercise; see the PR #885 comment.

**Result** (2026-10-04, PR #885 round 2 at `48bf23f`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS (regression)**. The output matches round 1 field for field. The fix's `metadataHeaders` filter can't be seen through shaping, so it was checked against the raw API instead (see TC-GM31's round 2 result).

---

## `list_threads`

### TC-GM05: List the fixture threads

**Action**
1. `list_threads` with `query: "label:mcp-qa-fixture"`, `max_results: 50`

**Checks**
- `threads` includes `{TEST_THREAD_ID}` and `{TEST_GMAIL_BIG_THREAD_ID}`
- Every item has `id`; `snippet` and `history_id` keys are present
- No `next_page_token`, no `error` field

---

### TC-GM06: Invalid label filter returns API error

**Action**
1. `list_threads` with `label_ids: ["TOTALLY_INVALID_LABEL_XYZ"]`

**Checks**
- Returns `{"error": "..."}`, not a tool exception

---

## `get_thread`

### TC-GM07: Fetch the thread fixture

**Action**
1. `get_thread` with `thread_id: "{TEST_THREAD_ID}"`

**Checks**
- `id` is `{TEST_THREAD_ID}`; `messages` has at least 3 entries
- Every message has `id`, `thread_id`, `label_ids`, `headers`, `body_plain`, `body_html`, and `attachments`, shaped like `get_message`
- No `error` field

---

### TC-GM08: Non-existent thread ID

**Action**
1. `get_thread` with `thread_id: "totally-invalid-thread-id-xyz"`

**Checks**
- Returns `{"error": "..."}`, not a tool exception

---

### TC-GM31: An over-cap thread returns the size-cap error, and `include_body: false` lists it (issue #793)

**Background:** the `over-cap-thread` fixture is 3 messages of ~400 KB each, which is over the default `MAX_TOOL_RESPONSE_CHARS` in full format but under it per message. The full fetch should refuse cleanly rather than drop the connection or truncate. Since #793, `include_body: false` fetches only metadata, which is small enough to list the thread's message IDs.

**Action**
1. `get_thread` with `thread_id: "{TEST_GMAIL_BIG_THREAD_ID}"`
2. `get_thread` with `thread_id: "{TEST_GMAIL_BIG_THREAD_ID}"`, `include_body: false`
3. `get_message` with `message_id` set to the first message ID from step 2

**Checks**
- Step 1: the tool call fails with an error containing `get_thread: the response is` and `safety cap`. The error suggests `include_body=False` followed by `get_message` on individual IDs. The session stays connected: the next call works.
- Step 1: no partial or truncated thread is returned
- Step 2: no `error`. `id` is `{TEST_GMAIL_BIG_THREAD_ID}`, and `messages` has 3 entries, each with `id`, `thread_id`, `snippet`, `label_ids`, `size_estimate`, and `headers` (`headers.subject` contains `[mcp-qa:over-cap-thread]`)
- Step 2: no message has a `body_plain`, `body_html`, or `attachments` key, and the whole response is a few KB, not ~1.2 MB
- Step 3: succeeds, with a `body_plain` that starts `mcp-gee-sweet over-cap-thread message`

**Result** (2026-10-04, PR #885 round 1 at `47937d8`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS**. Step 1: `get_thread: the response is 1275124 characters, over the 1000000-character safety cap`, with the hint naming `include_body=False` then `get_message` on individual IDs; no partial thread, and the next call worked. Step 2: no `error`, 3 messages, each with `id`, `thread_id`, `snippet`, `label_ids`, `size_estimate` (~412 KB each) and `headers` (subjects contain `[mcp-qa:over-cap-thread]`; `in_reply_to`/`references` chain correctly), no body or attachment keys; the response was about 3 KB. Step 3: run with `local_path` to keep ~425 KB out of the QA session's context (424,899 bytes written); `body_plain` starts `mcp-gee-sweet over-cap-thread message 1.`. The thread-level `snippet` is `null`, the same as the full format (`threads.get` returns none).

**Result** (2026-10-04, PR #885 round 2 at `48bf23f`, `mcp-gee-sweet-kit`, OAuth token with `gmail.modify`): **PASS**. Steps 1–3 matched round 1 exactly (1,275,124-character cap error with the `include_body=False` hint; 3 metadata-only messages; step 3 via `local_path`, 424,899 bytes). The `metadataHeaders` filter was checked with a fresh-interpreter raw `threads.get` on the same thread using this slot's token. Plain `format=metadata` returned 24,591 bytes and 88 headers (ARC-*, DKIM-Signature, Received, X-Gm-*, and others). `_get_format_kwargs(False)` returned 3,003 bytes and 19 headers, all from the shaped set (Date, From, In-Reply-To, Message-ID, References, Subject, To).

---

### TC-GM33: Thread order and reply headers

**Action**
1. `get_thread` with `thread_id: "{TEST_THREAD_ID}"`

Ignore any message whose `label_ids` includes `TRASH` (left by an earlier TC-GM43 run). Call the remaining three M1, M2, M3, identified by their body text in the checks below.

**Checks**
- Exactly 3 non-trashed messages, with non-decreasing `internal_date`. M2 and M3 can share a value (sent in the same second; seen live 2026-09-26), so the order is proven by the `in_reply_to` chain below, not by the timestamps.
- M1 `body_plain` starts `Sender opens the thread fixture (message 1).`; M2 starts `QA mailbox reply (thread fixture, message 2).`; M3 starts `Sender reply (thread fixture, message 3).`
- M1 and M3 `headers.from` contain `{SENDER}`; M2 `headers.from` contains `{QA}` and its `label_ids` includes `SENT`
- M1 `headers.in_reply_to` is `null`
- M2 `headers.in_reply_to` equals M1 `headers.message_id`
- M3 `headers.in_reply_to` equals M2 `headers.message_id`, and M3 `headers.references` contains both M1's and M2's `message_id`, in that order

---

## `list_labels`

### TC-GM09: List system and user labels

**Action**
1. `list_labels`

**Checks**
- Includes `INBOX`, `UNREAD`, `SENT`, `DRAFT`, `TRASH`, and `SPAM`, each with `type: "system"`
- Includes an entry with `name: "mcp-qa-fixture"`, `type: "user"`, and `id` equal to `{TEST_GMAIL_LABEL_ID}`
- Every item has `id`, `name`, `type`
- No `error` field

---

### TC-GM10: (retired)

Retired by #822. The Gmail-scope failure path is covered deterministically by TC-I32 (`infra.md`), which uses a scope-less token copy. Don't reuse this ID.

---

### TC-GM36: Add and remove a user label by ID ⚠️ destructive

Uses a throwaway, not a fixture: removing `mcp-qa-fixture` from a fixture would hide it from every read case.

**Action**
1. `send_message` with `to: "{QA+tc-gm36}"`, `subject: "[mcp-qa:tc-gm36] user label"`, `body: "mcp-gee-sweet TC-GM36"`. Record `id` as `{GM36_ID}`.
2. `modify_labels` with `message_id: "{GM36_ID}"`, `add_label_ids: ["{TEST_GMAIL_LABEL_ID}"]`
3. `modify_labels` with `message_id: "{GM36_ID}"`, `remove_label_ids: ["{TEST_GMAIL_LABEL_ID}"]`

**Checks**
- Step 2: `label_ids` includes `{TEST_GMAIL_LABEL_ID}`
- Step 3: `label_ids` no longer includes it
- No `error` field in any response

**Cleanup:** `trash_message` `{GM36_ID}`.

---

## `send_message`

### TC-GM11: Send to a plus-address ⚠️ destructive

**Action**
1. `send_message` with `to: "{QA+tc-gm11}"`, `subject: "[mcp-qa:tc-gm11] send_message"`, `body: "mcp-gee-sweet TC-GM11"`. Record `id` as `{GM11_ID}`.
2. `list_messages` with `query: "subject:(mcp-qa tc-gm11)"`

**Checks**
- Step 1: returns `id`, `thread_id`, and `label_ids`, and `label_ids` includes `SENT`
- Step 2: `messages` includes `{GM11_ID}`
- No `error` field

**Cleanup:** `trash_message` `{GM11_ID}`.

---

### TC-GM12: Invalid recipient returns an error

**Action**
1. `send_message` with `to: "not-an-email"`, `subject: "[mcp-qa:tc-gm12] invalid recipient"`, `body: "x"`

**Checks**
- Returns `{"error": "..."}`, not a tool exception, and no `id`
- If it returns an `id` instead, record FAIL and trash that ID

---

### TC-GM38: HTML body with attachments from both sources ⚠️ destructive ⚠️ local-filesystem

**Setup:** `printf 'name,qty\nwidget,3\n' > /tmp/mcp-qa-tc-gm38.csv` on the machine running the server.

**Action**
1. `send_message` with `to: "{QA+tc-gm38}"`, `subject: "[mcp-qa:tc-gm38] html + attachments"`, `body: "mcp-gee-sweet TC-GM38 plain"`, `body_html: "<p>mcp-gee-sweet <b>TC-GM38</b> html</p>"`, and `attachments`:
   - `{"local_path": "/tmp/mcp-qa-tc-gm38.csv", "mime_type": "text/csv"}`
   - `{"content_base64": "aGVsbG8gZnJvbSBUQy1HTTM4", "filename": "note.txt"}` (no `mime_type`; decodes to `hello from TC-GM38`)
2. `get_message` with the `id` from step 1

**Checks**
- Step 2: `body_plain` is `mcp-gee-sweet TC-GM38 plain`; `body_html` contains `<b>TC-GM38</b>`
- Step 2: `attachments` has exactly 2 entries: `filename: "mcp-qa-tc-gm38.csv"` (the file's own name, since no `filename` was passed) with `mime_type: "text/csv"`, and `filename: "note.txt"`
- Step 2: `note.txt`'s `mime_type` is `text/plain`, guessed from its extension since no `mime_type` was passed (#802; it was `application/octet-stream` before #896). TC-GM47 covers more extensions.

**Cleanup:** `trash_message` the step-1 `id`; delete `/tmp/mcp-qa-tc-gm38.csv`.

**Result (2026-10-06, PR #928 round 1) ✅ PASS**: via `mcp-gee-sweet-kit`. Both bodies matched. There were 2 attachments: `mcp-qa-tc-gm38.csv` (`text/csv`, 18 bytes, read through `_compose_raw`'s off-loop thread) and `note.txt`, whose `mime_type` was `text/plain`, guessed. The message was trashed and the local file deleted.

---

### TC-GM39: `cc` and `bcc` as lists ⚠️ destructive

**Action**
1. `send_message` with `to: "{QA+tc-gm39}"`, `cc: ["{QA+tc-gm39-cc1}", "{QA+tc-gm39-cc2}"]`, `bcc: ["{QA+tc-gm39-bcc}"]`, `subject: "[mcp-qa:tc-gm39] cc and bcc lists"`, `body: "mcp-gee-sweet TC-GM39"`
2. `get_message` with the `id` from step 1

**Checks**
- `headers.cc` contains both cc addresses, comma-separated, and nothing else
- `headers.bcc` contains `{QA+tc-gm39-bcc}` (the sender's own copy keeps Bcc; TC-GM45 checks that the delivered copy doesn't)
- `headers.to` is `{QA+tc-gm39}`

**Cleanup:** `trash_message` the step-1 `id`.

---

### TC-GM40: A newline in the subject is rejected (header injection) ⚠️ destructive

**Action**
1. `send_message` with `to: "{QA+tc-gm40}"`, `subject: "[mcp-qa:tc-gm40] a\nBcc: {QA+tc-gm40-injected}"`, `body: "should not send"` (the `\n` is a real newline in the JSON string)
2. `send_message` with `to: "{QA+tc-gm40}"`, `subject: "[mcp-qa:tc-gm40] line one\nline two"`, `body: "should not send"`
3. `list_messages` with `query: "subject:(mcp-qa tc-gm40)"`, `include_spam_trash: true`

**Checks**
- Steps 1 and 2: each returns `{"error": "..."}` and no `id`. A local probe (2026-09-26) raises `HeaderParseError` for step 1 and `HeaderWriteError` for step 2, both inside the tool's `try`.
- Step 3: `messages` is empty, so nothing was sent

**Cleanup:** none expected. If step 3 finds anything, record FAIL and trash it.

---

### TC-GM47: An attachment without `mime_type` gets its type from the filename extension (issue #802) ⚠️ destructive

**Background:** an attachment passed without `mime_type` used to go out as `application/octet-stream` whatever its name, so recipients' clients couldn't preview it. #802 guesses the type from the filename's extension, as `upload_local_file` does. A compressed file (`.gz`) gets the compression type, not the type of what's inside it.

**Action**
1. `send_message` with `to: "{QA+tc-gm47}"`, `subject: "[mcp-qa:tc-gm47] attachment mime guess"`, `body: "mcp-gee-sweet TC-GM47"`, and `attachments` (none has `mime_type`):
   - `{"content_base64": "JVBERi0xLjQK", "filename": "gm47.pdf"}`
   - `{"content_base64": "aGVsbG8=", "filename": "gm47.csv.gz"}`
   - `{"content_base64": "aGVsbG8=", "filename": "gm47.zzzunknown"}`
   - `{"content_base64": "aGVsbG8=", "filename": "gm47.png", "mime_type": "text/plain"}` (explicit type wins)
2. `get_message` with the `id` from step 1

**Checks**
- Step 2: `attachments` has exactly 4 entries, with `mime_type` by filename:
  - `gm47.pdf` → `application/pdf`
  - `gm47.csv.gz` → `application/gzip`
  - `gm47.zzzunknown` → `application/octet-stream`
  - `gm47.png` → `text/plain`
- No `error` field

**Cleanup:** `trash_message` the step-1 `id`.

**Result (2026-10-06, PR #928 round 1) ✅ PASS (as written), with send-back findings out of scope for this case**: via `mcp-gee-sweet-kit`. The 4 attachments came back as `gm47.pdf` → `application/pdf`, `gm47.csv.gz` → `application/gzip`, `gm47.zzzunknown` → `application/octet-stream`, and `gm47.png` → `text/plain` (explicit wins), with no `error`. A probe in the same round showed two regressions the case's extensions don't reach. `fwd.eml` with no `mime_type` was guessed as `message/rfc822` but still built as a base64 `MIMEApplication`, which RFC 2046 §5.2.1 forbids. Python's parser decodes that payload to `None`. A UTF-8 `notes.txt` (`héllo`) was guessed as `text/plain` with no `charset`, so per RFC 2046 it reads as US-ASCII. Gmail accepted both. The part headers were confirmed by running the branch's `_build_raw_message` locally. Both messages were trashed.

---

## `create_draft`

### TC-GM13: Create a draft ⚠️ destructive

**Action**
1. `create_draft` with `to: "{QA+tc-gm13}"`, `subject: "[mcp-qa:tc-gm13] draft"`, `body: "mcp-gee-sweet TC-GM13"`. Record `id` as `{GM13_DRAFT_ID}`.
2. `get_message` with `message_id` set to `message.id` from step 1

**Checks**
- Step 1: returns `id` and `message.id`, no `error`
- Step 2: `label_ids` includes `DRAFT` and not `SENT`

**Cleanup:** TC-GM15 sends this draft. If TC-GM15 isn't run, `qa_gmail_fixtures.py reset` deletes it (the tools can't delete a draft).

---

### TC-GM14: Invalid attachment shape

**Action**
1. `create_draft` with `to: "{QA+tc-gm14}"`, `subject: "[mcp-qa:tc-gm14] bad attachment"`, `body: "x"`, `attachments: [{}]`

**Checks**
- Returns `{"error": "..."}` that mentions `local_path` and `content_base64`, and no draft `id`

**Result (2026-10-06, PR #928 round 1) ✅ PASS (regression, error now raised inside `_compose_raw`'s thread)**: returned `{"error": "Each attachment needs either local_path or content_base64 (plus optional filename and mime_type)."}`, with no draft `id`.

---

### TC-GM41: Draft with HTML and an attachment survives `send_draft` ⚠️ destructive

**Action**
1. `create_draft` with `to: "{QA+tc-gm41}"`, `subject: "[mcp-qa:tc-gm41] draft round trip"`, `body: "mcp-gee-sweet TC-GM41 plain"`, `body_html: "<p>mcp-gee-sweet <i>TC-GM41</i></p>"`, `attachments: [{"content_base64": "VEMtR000MSBhdHRhY2htZW50", "filename": "gm41.txt", "mime_type": "text/plain"}]`
2. `get_message` with `message_id` set to `message.id` from step 1. Record its `attachments`.
3. `send_draft` with `draft_id` from step 1
4. `get_message` with the `id` from step 3

**Checks**
- Step 2: one attachment, `filename: "gm41.txt"`, `mime_type: "text/plain"`
- Step 4: `label_ids` includes `SENT`, not `DRAFT`
- Step 4: `body_plain` and `body_html` match step 2's
- Step 4: the attachment's `filename`, `mime_type`, and `size` equal step 2's

**Cleanup:** `trash_message` the step-3 `id`.

**Result (2026-10-06, PR #928 round 1) ✅ PASS (regression, `create_draft`/`send_draft` via `_compose_raw` and `_message_summary`)**: step 2 had one attachment, `gm41.txt` (`text/plain`, 18 bytes), and `label_ids` `DRAFT`. `send_draft` returned `id`, `thread_id`, and `label_ids` (`SENT`, no `DRAFT`). Step 4's bodies and attachment `filename`/`mime_type`/`size` equal step 2's. Trashed.

---

## `send_draft`

### TC-GM15: Send an existing draft ⚠️ destructive

**Setup:** `{GM13_DRAFT_ID}` from TC-GM13

**Action**
1. `send_draft` with `draft_id: "{GM13_DRAFT_ID}"`
2. `get_message` with the `id` from step 1
3. `send_draft` with `draft_id: "{GM13_DRAFT_ID}"` again

**Checks**
- Step 1: returns `id`, `thread_id`, `label_ids`, and `label_ids` includes `SENT`
- Step 2: `label_ids` doesn't include `DRAFT`; `headers.subject` is `[mcp-qa:tc-gm13] draft`
- Step 3: returns `{"error": "..."}`. The draft is gone, which is the only way the tools can show it left the drafts list.

**Cleanup:** `trash_message` the step-1 `id`.

---

### TC-GM16: Non-existent draft

**Action**
1. `send_draft` with `draft_id: "totally-invalid-draft-id-xyz"`

**Checks**
- Returns `{"error": "..."}`, not a tool exception

---

## `reply_to_message`

### TC-GM17: Reply in-thread with correct threading headers ⚠️ destructive

**Action**
1. `send_message` with `to: "{QA+tc-gm17}"`, `subject: "[mcp-qa:tc-gm17] reply original"`, `body: "mcp-gee-sweet TC-GM17 original"`. Record `id` as `{GM17_ORIG}`.
2. `get_message` with `message_id: "{GM17_ORIG}"`. Record `headers.message_id` as `{GM17_MID}`.
3. `reply_to_message` with `message_id: "{GM17_ORIG}"`, `body: "mcp-gee-sweet TC-GM17 reply"`
4. `get_message` with the `id` from step 3

**Checks**
- Step 3: `thread_id` equals `{GM17_ORIG}`'s `thread_id`
- Step 3: no `warning` field. One appears only when the mailbox's own addresses couldn't be looked up (#802), which a healthy token never hits; the failure path is unit-tested only.
- Step 4: `headers.in_reply_to` equals `{GM17_MID}`, and `headers.references` ends with `{GM17_MID}`
- Step 4: `headers.subject` is exactly `Re: [mcp-qa:tc-gm17] reply original` (one `Re: `)
- Step 4: `headers.to` is `{QA+tc-gm17}` (a reply to your own sent message goes to its original `To`, per TC-GM24)

**Cleanup:** `trash_message` `{GM17_ORIG}` and the step-3 `id`.

**Result (2026-10-06, PR #928 round 1) ✅ PASS**: via `mcp-gee-sweet-kit`. Step 3's `thread_id` equals the original's, and there was no `warning` field. Step 4: `in_reply_to` and `references` are both the original's Message-ID, the subject is `Re: [mcp-qa:tc-gm17] reply original` (one `Re: `), and `to` is the `+tc-gm17` address. Both messages were trashed.

---

### TC-GM18: Reply to non-existent message

**Action**
1. `reply_to_message` with `message_id: "totally-invalid-message-id-xyz"`, `body: "hi"`

**Checks**
- Returns `{"error": "..."}`, not a tool exception

---

### TC-GM23: Reply goes to the original's Reply-To, not its From (issue #791) ⚠️ destructive ⚠️ requires-oauth

**Background:** `reply_to_message` used to always reply to `From`, so mail with a `Reply-To` (mailing lists, support desks, no-reply senders) got the reply at the wrong address. #791 resolves `Reply-To` over `From`, like a standard mail client. This reproduces the defect without mailing anyone outside the QA mailbox: the original is *inserted* (not sent) with a fake `From` and a `Reply-To` pointing at a plus-address of the QA mailbox itself.

**Setup:** there's no tool for inserting a message, so insert the fixture with a scratch script from the checkout under test, using the same OAuth token as the server under test (its saved scopes must include `gmail.modify`). Replace `<mailbox>` with the QA mailbox address, e.g. `qa@example.com` → `qa+tc-gm23@example.com`:

```bash
uv run python3 -c "
import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from mcp_gee_sweet.auth import _oauth_creds
m = MIMEText('mcp-gee-sweet TC-GM23 fixture')
m['From'] = 'No Reply <noreply@example.invalid>'
m['Reply-To'] = '<mailbox local part>+tc-gm23@<mailbox domain>'
m['To'] = '<mailbox>'
m['Subject'] = 'TC-GM23 reply-to fixture'
g = build('gmail', 'v1', credentials=_oauth_creds(), cache_discovery=False)
r = g.users().messages().insert(userId='me', body={'raw': base64.urlsafe_b64encode(m.as_bytes()).decode(), 'labelIds': ['INBOX']}).execute()
print(r['id'])
"
```

Record the printed ID as `{REPLY_TO_FIXTURE_ID}`.

**Seeded alternative:** the `reply-to` fixture (`{TEST_GMAIL_REPLYTO_ID}`, setup.md Gmail section) has the same shape. Use it as `{REPLY_TO_FIXTURE_ID}` instead of running the script, and leave it out of Cleanup: trash only the two replies, since other runs reuse the fixture.

**Action**
1. `get_message` with `message_id: "{REPLY_TO_FIXTURE_ID}"`
2. `reply_to_message` with `message_id: "{REPLY_TO_FIXTURE_ID}"`, `body: "mcp-gee-sweet TC-GM23 reply"`
3. `get_message` with `message_id` set to the `id` returned by step 2
4. `reply_to_message` again with `reply_all: true`, same `message_id`, `body: "mcp-gee-sweet TC-GM23 reply-all"`, then `get_message` on its returned `id`

**Checks**
- Step 1: `headers.reply_to` is the `+tc-gm23` address and `headers.from` is `noreply@example.invalid`
- Step 3: `headers.to` is the `+tc-gm23` address only; `noreply@example.invalid` appears nowhere in `to`/`cc`
- Step 4: `headers.to` contains the `+tc-gm23` address and does **not** contain the bare QA mailbox address (the authenticated mailbox is excluded from reply-all); `noreply@example.invalid` appears nowhere
- The step-2 reply arrives in the QA inbox (it was addressed to the mailbox's own plus-address), in the same `thread_id` as the fixture

**Cleanup:** `trash_message` the fixture, both replies, and their delivered inbox copies.

**Result (2026-09-26, PR #815 round 1) ✅ PASS** — via `mcp-gee-sweet-kit` (token has `gmail.modify`), fixture inserted with the setup script. Step 1: `reply_to` = `+tc-gm23` address, `from` = `noreply@example.invalid`. Step 3: `to` = `+tc-gm23` address only. Step 4 (reply-all): `to` = `+tc-gm23` address only; the bare mailbox was excluded, and `noreply@example.invalid` appears nowhere. Both replies share the fixture's `thread_id`. A reply to your own plus-address is one message labeled `SENT`+`INBOX`, not a separate delivered copy, so cleanup is just the fixture plus the two replies. All trashed.

**Result (2026-09-26, PR #815 round 2) ✅ PASS (regression)** — re-run against `45530d7`: the plain reply and reply-all both go `to` = `+tc-gm23` only. The bare mailbox and `noreply@example.invalid` appear nowhere. Trashed.

---

### TC-GM24: Replying to your own sent message goes to its original To, not back to you (issue #791) ⚠️ destructive ⚠️ requires-oauth

**Background:** a plain reply (`reply_all: false`) to a message the mailbox itself sent used to set `To` to the mailbox's own address. #791 replies to that message's original `To` instead, like a standard mail client. A plus-address of the QA mailbox stands in for the other person, so nothing leaves the mailbox.

**Action**
1. `send_message` with `to: "<mailbox local part>+tc-gm24@<mailbox domain>"`, `subject: "TC-GM24 own-sent fixture"`, `body: "mcp-gee-sweet TC-GM24 fixture"`. Record its `id` as `{OWN_SENT_ID}`.
2. `get_message` with `message_id: "{OWN_SENT_ID}"`
3. `reply_to_message` with `message_id: "{OWN_SENT_ID}"`, `body: "mcp-gee-sweet TC-GM24 reply"`
4. `get_message` with `message_id` set to the `id` returned by step 3

**Checks**
- Step 2: `label_ids` includes `SENT`
- Step 4: `headers.to` is the `+tc-gm24` address, **not** the bare QA mailbox address
- Step 4: `thread_id` matches `{OWN_SENT_ID}`'s thread

**Cleanup:** `trash_message` the fixture, the reply, and their delivered inbox copies.

**Result (2026-09-26, PR #815 round 1) ✅ PASS** — via `mcp-gee-sweet-kit`. Step 2: `label_ids` includes `SENT`. Step 4: `to` = `+tc-gm24` address, not the bare mailbox; `thread_id` matches. Both trashed. **Scope note:** this case covers only a single-recipient `To`. Live repros of the PR's code-review findings (both plain replies to your own sent mail) failed. `To: <mailbox>, <mailbox>+tc-f3` replied `To: <mailbox>, <mailbox>+tc-f3`, so you get a copy of your own reply. `Cc`-only (no `To`) replied `To: <mailbox>` and dropped the Cc'd recipient. Both were sent back to the Dev on PR #815.

**Result (2026-09-26, PR #815 round 2) ✅ PASS (regression)** — re-run against `45530d7`: the reply goes `to` = `+tc-gm24`, same thread. The round-1 scope-note failures are now covered by TC-GM25, which passes. Trashed.

---

### TC-GM25: Replies to your own multi-recipient or Cc-only sent mail never copy you and never drop the Cc (issue #791) ⚠️ destructive ⚠️ requires-oauth

**Background:** PR #815 QA round 1 reproduced two live failures TC-GM24 doesn't cover, both on plain replies to your own sent mail. `To: <mailbox>, <mailbox>+x` replied to both, so you got a copy of your own reply. A `Cc`-only message (no `To`) replied `To: <mailbox>` and dropped the Cc'd person. The fix drops the mailbox's own addresses (primary and send-as aliases) from every reply, and replies to an own message's `Cc` when nobody else is in `To`. Plus-addresses of the QA mailbox stand in for other people, so nothing leaves the mailbox. They count as other people because they aren't send-as aliases.

**Action**
1. `send_message` with `to: ["<mailbox>", "<mailbox local part>+tc-gm25a@<mailbox domain>"]`, `subject: "TC-GM25 multi-recipient fixture"`, `body: "mcp-gee-sweet TC-GM25 fixture A"`. Record its `id` as `{GM25_A}`.
2. `reply_to_message` with `message_id: "{GM25_A}"`, `body: "mcp-gee-sweet TC-GM25 reply A"`, then `get_message` on the returned `id`.
3. `send_message` with `to: ""`, `cc: "<mailbox local part>+tc-gm25b@<mailbox domain>"`, `subject: "TC-GM25 Cc-only fixture"`, `body: "mcp-gee-sweet TC-GM25 fixture B"` (the round-1 Cc-only repro). Record its `id` as `{GM25_B}`.
4. `reply_to_message` with `message_id: "{GM25_B}"`, `body: "mcp-gee-sweet TC-GM25 reply B"`, then `get_message` on the returned `id`.
5. `reply_to_message` with `message_id: "{GM25_B}"`, `reply_all: true`, `body: "mcp-gee-sweet TC-GM25 reply-all B"`, then `get_message` on the returned `id`.
6. Repeat steps 3–5 with `to: "<mailbox>"` instead of `to: ""` and `+tc-gm25c` as the Cc (a message to yourself that also Cc's someone).

**Checks**
- Step 2: `headers.to` is exactly the `+tc-gm25a` address. The bare mailbox address appears nowhere in `to`/`cc`.
- Step 4: `headers.to` is exactly the `+tc-gm25b` address, not the bare mailbox. `cc` is empty.
- Step 5: `headers.to` is exactly the `+tc-gm25b` address. The bare mailbox appears nowhere in `to`/`cc`.
- Step 6: same as steps 4–5, with the `+tc-gm25c` address.

**Cleanup:** `trash_message` all three fixtures, all five replies, and their delivered inbox copies.

**Result (2026-09-26, PR #815 round 2) ✅ PASS** — via `mcp-gee-sweet-kit` after `/mcp reconnect`, against fix `45530d7`. Step 2: `to` = `+tc-gm25a` only; the bare mailbox appears nowhere. Steps 4 and 5 (Cc-only, sent with `to: []`): both `to` = `+tc-gm25b`, `cc` empty. Step 6 (to-self + Cc): plain reply and reply-all both `to` = `+tc-gm25c`, `cc` empty. Also confirmed live with the same token that `users.settings.sendAs.list` succeeds under `gmail.modify` and returns the primary address (1 entry, `isPrimary: true`), so `_own_addresses` takes its alias-list path rather than the `getProfile` fallback. All fixtures and replies trashed.


---

### TC-GM42: Reply subject normalization ⚠️ destructive

**Action**
1. `send_message` with `to: "{QA+tc-gm42}"`, `subject: ""`, `body: "mcp-gee-sweet TC-GM42 no subject"`. Record `id` as `{GM42_A}`.
2. `reply_to_message` with `message_id: "{GM42_A}"`, `body: "mcp-gee-sweet TC-GM42 reply A"`, then `get_message` on the returned `id`
3. `send_message` with `to: "{QA+tc-gm42}"`, `subject: "RE: [mcp-qa:tc-gm42] upper-case prefix"`, `body: "mcp-gee-sweet TC-GM42 RE"`. Record `id` as `{GM42_B}`.
4. `reply_to_message` with `message_id: "{GM42_B}"`, `body: "mcp-gee-sweet TC-GM42 reply B"`, then `get_message` on the returned `id`

**Checks**
- Step 2: `headers.subject` is exactly `Re:`
- Step 4: `headers.subject` is exactly `RE: [mcp-qa:tc-gm42] upper-case prefix` (no `Re: RE:`)
- Both replies share their original's `thread_id`

**Cleanup:** `trash_message` `{GM42_A}`, `{GM42_B}`, and both reply IDs. `{GM42_A}` and its reply have no `[mcp-qa` subject, so `reset` won't sweep them; trash them by ID.

---

### TC-GM43: Reply from the middle of a thread chains References ⚠️ destructive

Run after TC-GM33. The middle message (M2) was sent by the QA mailbox, so the reply goes to its original `To`: the sender mailbox. That's an allowed recipient (plan §3.1).

**Action**
1. `get_thread` with `thread_id: "{TEST_THREAD_ID}"`. Take M2 as in TC-GM33 and record its `id`, `headers.message_id`, and `headers.references`.
2. `reply_to_message` with `message_id` set to M2's `id`, `body: "mcp-gee-sweet TC-GM43 reply from the middle"`
3. `get_message` with the `id` from step 2

**Checks**
- Step 2: `thread_id` is `{TEST_THREAD_ID}`
- Step 3: `headers.in_reply_to` equals M2's `message_id`
- Step 3: `headers.references` equals M2's `references` followed by a space and M2's `message_id`, so it names M1 then M2
- Step 3: `headers.subject` is `Re: [mcp-qa:thread] two-party thread` (one `Re: `)
- Step 3: `headers.to` is `{SENDER}`

**Cleanup:** `trash_message` the step-2 `id`. On the sender side, TC-GM44's cleanup rule applies: trash the delivered copy (`Re: [mcp-qa:thread]`, body `mcp-gee-sweet TC-GM43 reply from the middle`) through `mcp__mcp-gee-sweet__trash_message`.

---

## `modify_labels`

### TC-GM19: Toggle UNREAD on a message and STARRED on a thread ⚠️ destructive

**Action**
1. `get_message` with `message_id: "{TEST_MESSAGE_ID}"`. Note whether `label_ids` includes `UNREAD`.
2. `modify_labels` with `message_id: "{TEST_MESSAGE_ID}"`, `add_label_ids: ["UNREAD"]`
3. `modify_labels` with `message_id: "{TEST_MESSAGE_ID}"`, `remove_label_ids: ["UNREAD"]`
4. `modify_labels` with `thread_id: "{TEST_THREAD_ID}"`, `add_label_ids: ["STARRED"]`
5. `modify_labels` with `thread_id: "{TEST_THREAD_ID}"`, `remove_label_ids: ["STARRED"]`

**Checks**
- Step 2: returns `id`, `thread_id`, `label_ids`, with `UNREAD` in `label_ids`
- Step 3: `UNREAD` is not in `label_ids`
- Step 4: returns `id` (`{TEST_THREAD_ID}`) and `messages`; **every** entry in `messages` has `STARRED` in `label_ids`
- Step 5: **no** entry in `messages` has `STARRED`
- No `error` field in any response

**Cleanup:** if step 1 showed `UNREAD`, add it back with `modify_labels` so the fixture ends as it started.

**Result (2026-10-06, PR #928 round 1) ✅ PASS (regression, `modify_labels` message branch via `_message_summary`)**: the message branch returned `id`, `thread_id`, and `label_ids`. `UNREAD` was added, then removed. On the thread, `STARRED` was added to every message, then removed from every message. There was no `error` in any response. The fixture started `UNREAD`, and `UNREAD` was restored.

---

### TC-GM20: Validation errors

**Action**
1. `modify_labels` with `add_label_ids: ["STARRED"]` and neither `message_id` nor `thread_id`
2. `modify_labels` with `add_label_ids: ["STARRED"]`, `message_id: "{TEST_MESSAGE_ID}"`, and `thread_id: "{TEST_THREAD_ID}"`
3. `modify_labels` with `message_id: "{TEST_MESSAGE_ID}"` and neither `add_label_ids` nor `remove_label_ids`

**Checks**
- Steps 1 and 2: `{"error": "Provide exactly one of message_id or thread_id."}`
- Step 3: `{"error": "Provide at least one of add_label_ids or remove_label_ids."}`
- `{TEST_MESSAGE_ID}`'s labels are unchanged (no API call was made)

---

## `trash_message`

### TC-GM21: Trash a throwaway ⚠️ destructive

**Action**
1. `send_message` with `to: "{QA+tc-gm21}"`, `subject: "[mcp-qa:tc-gm21] trash me"`, `body: "mcp-gee-sweet TC-GM21"`
2. `trash_message` with `message_id` set to the `id` from step 1

**Checks**
- Step 2: `action` is `"trashed"`, `label_ids` includes `TRASH`, `id` matches step 1
- No `error` field

---

### TC-GM22: Trash non-existent message

**Action**
1. `trash_message` with `message_id: "totally-invalid-message-id-xyz"`

**Checks**
- Returns `{"error": "..."}`, not a tool exception

---

### TC-GM37: Trash twice, then try to restore by label ⚠️ destructive 🔍 product decision

**Background:** the tools have no `untrash`. Whether `modify_labels(remove_label_ids=["TRASH"])` restores a message is unverified (plan §2 item 3). This case records the answer. It isn't pass/fail on the restore question: record what happened and update plan §2 item 3 with it.

**Action**
1. `send_message` with `to: "{QA+tc-gm37}"`, `subject: "[mcp-qa:tc-gm37] trash twice"`, `body: "mcp-gee-sweet TC-GM37"`. Record `id` as `{GM37_ID}`.
2. `trash_message` with `message_id: "{GM37_ID}"`
3. `trash_message` with `message_id: "{GM37_ID}"` again
4. `modify_labels` with `message_id: "{GM37_ID}"`, `remove_label_ids: ["TRASH"]`
5. `get_message` with `message_id: "{GM37_ID}"`
6. `list_messages` with `query: "subject:(mcp-qa tc-gm37)"` (no `include_spam_trash`)

**Checks**
- Step 2: `action: "trashed"`, `TRASH` in `label_ids`
- Step 3: either the same success shape (idempotent) or a clean `{"error": ...}`. **Record which.** Either is acceptable; a tool exception is a FAIL.
- Steps 4–6: **record** whether step 4 errors, whether `TRASH` is gone from step 5's `label_ids`, which other labels it has (`INBOX`? `SENT`?), and whether step 6 lists `{GM37_ID}`

**Cleanup:** `trash_message` `{GM37_ID}` (a no-op if it's still in trash).

---

## Cross-mailbox delivery

These cases prove what the recipient actually receives, which plus-address cases can't show. The QA-side call is the one under test. Sender-side calls go through `mcp__mcp-gee-sweet__*` and only observe. Read, and afterwards trash, only the `[mcp-qa`-subject messages each case names in the sender mailbox.

### TC-GM44: A reply threads in the recipient's mailbox ⚠️ destructive ⚠️ cross-mailbox

**Action**
1. QA: `reply_to_message` with `message_id: "{TEST_MESSAGE_ID}"`, `body: "mcp-gee-sweet TC-GM44 reply"`. The `plain` fixture is from `{SENDER}`, so the reply goes there. Record the returned `id`.
2. Sender, after ~30 s: `mcp__mcp-gee-sweet__list_messages` with `query: "subject:(mcp-qa plain)"`, `max_results: 10`. Retry up to 3 times, 30 s apart, until two messages share a `thread_id`.
3. Sender: `mcp__mcp-gee-sweet__get_message` on each returned ID

**Checks**
- Step 1: returns `id`, `thread_id` equal to `{TEST_MESSAGE_ID}`'s thread, `SENT` in `label_ids`
- Step 3: the sender mailbox holds its original `[mcp-qa:plain] plain text` (labeled `SENT`) and the delivered `Re: [mcp-qa:plain] plain text` with body `mcp-gee-sweet TC-GM44 reply`, and **both have the same `thread_id`**
- Step 3: the delivered reply's `headers.in_reply_to` equals the original's `headers.message_id`

**Cleanup:** QA: `trash_message` the step-1 `id`. Sender: `mcp__mcp-gee-sweet__trash_message` the delivered reply only. Leave the sender's original: it's the `plain` fixture's source.

---

### TC-GM45: Bcc is stripped from the delivered copy ⚠️ destructive ⚠️ cross-mailbox

**Action**
1. QA: `send_message` with `to: "{SENDER}"`, `cc: "{QA+tc-gm45-cc}"`, `bcc: "{QA+tc-gm45-bcc}"`, `subject: "[mcp-qa:tc-gm45] bcc stripping"`, `body: "mcp-gee-sweet TC-GM45"`. Record `id` as `{GM45_ID}`.
2. Sender, after ~30 s: `mcp__mcp-gee-sweet__list_messages` with `query: "subject:(mcp-qa tc-gm45)"`. Retry as in TC-GM44. Then `mcp__mcp-gee-sweet__get_message` on the result.
3. QA: `get_message` with `message_id: "{GM45_ID}"`

**Checks**
- Step 2: `headers.cc` is `{QA+tc-gm45-cc}` and `headers.bcc` is `null`. A delivered copy that shows Bcc is a FAIL: it leaks the blind recipient.
- Step 3: the QA mailbox's own copy keeps `headers.bcc` (as in TC-GM39)

**Cleanup:** QA: `trash_message` `{GM45_ID}`. Sender: `mcp__mcp-gee-sweet__trash_message` the delivered copy.
