# Markdown rendering, document boundaries and document state — 2026-10-22 (#1044)

The third live run of [`docs/qa/tests/docs_markdown.md`](../tests/docs_markdown.md): document boundaries (TC-MD301–303) and document state (TC-MD401–404). Phase 1 is in [`2026-10-18-markdown.md`](2026-10-18-markdown.md), Phase 2 in [`2026-10-18-markdown-phase2.md`](2026-10-18-markdown-phase2.md). With this run every TC in the file has a baseline.

**Result: no TC passes.**

- **Document boundaries:** 71 of 112 TC-MD301 cells pass, with 6 pending (below). TC-MD302 and TC-MD303 fail only on rendering defects already filed: the long document renders in full through every entry point, and long file names upload cleanly.
- **Document state:** TC-MD401 and TC-MD403 fail only on rendering defects already filed: replacing a Doc's content and running `update_doc_from_file` twice both behave correctly. TC-MD402 adds one new defect: in a themed Doc, table cells take the heading style.
- **Determinism (TC-MD404):** Run 1 and Run 2 render identically everywhere except one cell. A `create_doc_from_file` call there hung for 30 minutes and left an empty Doc (#1129).

## Setup

- **Code under test:** `develop` at `60aaf6c1`. All four main-checkout servers were restarted on it at 2026-10-22 20:53 local, after #1138 (blank paragraph before a table reset to normal text) and #1110 merged; the main checkout's `src/` matched `origin/develop` byte for byte.
- **Shards:**

  | Shard | Server | TCs |
  |---|---|---|
  | A | `kai-oauth` | TC-MD301 DS-01 to DS-07 |
  | B | `oauth` | TC-MD301 DS-08 to DS-14 |
  | C | `kai-sa` | TC-MD302 |
  | D | `sa` | TC-MD303, TC-MD401 to TC-MD403 |

  Each shard ran Run 1 and then Run 2 itself, into fresh folders.
- **Folders:** `QA-MD-2026-10-22-p3-run<N>-<shard>` under `TEST_FOLDER_ID`, one per shard per run, with a child per case for EP-5/6/7. All eight were trashed after recording.
- **Approval:** throwaway Docs and folders under `TEST_FOLDER_ID`, trashed afterwards. No shares; the only image (DS-06, and the r04 badge in TC-MD302) is a public URL.
- **Playwright:** verified signed into the fixture-owning account before the shards started.

## Method

As Phase 2:
- **Screenshots:** one `browser_run_code_unsafe` call per Doc captured 1400×2200 page screenshots at `.kix-appview-editor` scrollTop = (k−1)×1900.
- **Judging:** EP-1, EP-5 and EP-8 were judged by eye. EP-2/3/4 were pixel-compared with EP-1, and EP-6/7 with EP-5, masking the Docs chrome, the caret column and the outline pane.
- **Run 2:** pixel-compared page by page against Run 1.
- **Cursor:** a 3×18 px diff at the document start is the text cursor, not content. It was read as identical.

## Results by TC

Cells count each case once per entry point.

### TC-MD301 — documents that start or end with a non-paragraph block (71/112 pass, 6 pending)

| Case | EP-1 | EP-2 | EP-3 | EP-4 | EP-5 | EP-6 | EP-7 | EP-8 |
|---|---|---|---|---|---|---|---|---|
| DS-01 starts with bullets | ✅ | ✅ | ✅ | ✅ | ❌ #1101 | ❌ #1101 | ❌ #1101 | ✅ |
| DS-02 starts numbered | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| DS-03 starts with a table | ✅ | ✅ | ✅ | ✅ | ❌ #1101 | ❌ #1101 | ❌ #1101 | ❌ #1102 |
| DS-04 starts with code | ✅ | ✅ | ✅ | ✅ | ❌ #1101 | ❌ #1101 | ❌ #1101 | ✅ |
| DS-05 starts with a quote | ✅ | ✅ | ❌ #1129 (Run 2) | ✅ | ❌ #1101 | ❌ #1101 | ❌ #1101 | ❌ #1102 |
| DS-06 starts with an image | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| DS-07 starts with a rule | ❌ #1096 | ❌ #1096 | ❌ #1096 | ❌ #1096 | ✅ | ✅ | ✅ | ✅ |
| DS-08 ends with a table | ✅ | ✅ | ✅ | ✅ | ❌ #1101 | ❌ #1101 | ❌ #1101 | ❌ #1102 |
| DS-09 ends with a list | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ #1102 |
| DS-10 empty | pending¹ | pending¹ | ✅ | ✅ | ✅ | ✅ | ✅ | pending¹ |
| DS-11 whitespace only | ✅² | ✅² | ✅ | ✅ | ✅ | ✅ | ✅ | ✅² |
| DS-12 no trailing newline | ✅² | ✅² | ✅ | ✅ | ✅ | ✅ | ✅ | ✅² |
| DS-13 CRLF line endings | pending¹ | pending¹ | ✅ | ✅ | ❌ #1101 | ❌ #1101 | ❌ #1101 | pending¹ |
| DS-14 YAML front matter | ❌ #1173 | ❌ #1173 | ❌ #1173 | ❌ #1173 | ❌ #1173, #1101 | ❌ #1173, #1101 | ❌ #1173, #1101 | ❌ #1173, #1102 |

¹ EP-1, EP-2 and EP-8 take the Markdown inline as a tool argument, and the client (Claude Code) couldn't send these bytes:
- **DS-10:** an empty string is dropped, so the call fails client-side with `InputValidationError`. Passing `""` instead put the literal text `""` in the Doc.
- **DS-13:** `\r\n` arrived as `\n`, so the blank lines were lost.

That is a client limitation, not the server. EP-3 to EP-7, which read the file from disk, test the same bytes. The same limitation stopped the suite's `create_doc(content="")` blank-target step; the shards created blank targets with `content` omitted.

² Rendered as expected; the client gives no way to confirm the exact bytes it sent.

What each failure looked like:
- **DS-01, DS-13, EP-5–7:** bullets use a `-` glyph, not ● (C2). DS-13 also shows an empty paragraph after the list.
- **DS-03, DS-08, EP-5–7 and EP-8:** a visible empty line next to the table (C15). In DS-03 it's above the table: Docs keeps a paragraph before a table at the document start, and our converter (EP-1–4) collapses it to a hairline. In DS-08 it's between the paragraph and the table. EP-8 also has a non-bold header row and unpadded cells (C13).
- **DS-04, EP-5–7:** the code line is in Arial (C6).
- **DS-05, EP-5–7:** the quote is indented but has no left border. EP-8: a plain paragraph (C7).
- **DS-05, EP-3, Run 2 only:** the call hung (see TC-MD404). Run 1 and a retry rendered correctly.
- **DS-07, EP-1–4:** the leading `---` is an empty-looking line, not a rule (C8).
- **DS-09, EP-8:** the heading is bold and larger, not the Heading 1 style (C1). The case's own check passes: no empty bullet after the list.
- **DS-14:** D3 (front matter not shown) fails in every engine:
  - **Ours:** an empty paragraph, then `title: Front matter` and `author: QA` as body text.
  - **Drive import:** a rule, then the two lines joined as a setext heading.
  - **EP-8:** rule, small text, rule.

  Filed as #1173.
- **Our converter passes DS-03:** the collapsed blank paragraph before a leading table stays invisible, which #1138 was meant to ensure.

### TC-MD302 — long document (0/8 pass)

The fixture is ~2,000 lines, 49,788 bytes, of the 16 realistic documents twice.

| Check | EP-1–4 | EP-5–7 | EP-8 |
|---|---|---|---|
| Completes, no timeout or partial Doc | ✅ | ✅ | ✅ |
| Second copies of r06 and r16 render like the first | ✅ | ✅ | ✅ |
| Every thematic break (32 `***` plus r03's two `---`) is a visible line | ❌ #1096 (0/34) | ✅ 34/34 | ✅ 34/34 |
| HTML comments not shown | ✅ | ✅ | ✅ |
| **Cell** | ❌ | ❌ | ❌ |

- **No deep-document offset bug:** the long-document checks themselves pass. Shard C also rendered r06 and r16 standalone through EP-3 as a control; they match the copies inside the long Doc.
- **Inline transcription was exact:** EP-1 is pixel-identical to EP-3 on all 26 screens, so the 50 KB inline argument arrived intact.
- **What fails is the Phase 1 rendering defects, repeated in every copy.**
  - **Ours:** #1096, #1071, #1072, #1093, #1094, #1097 (r13/r15 tables), #1099 (r04's SVG badge dropped; the per-image error is returned, the call succeeds).
  - **Drive import:** #1101.
  - **EP-8:** #1102.
- **One symptom not seen in Phase 1:** EP-5–7 number r12's Prompts 1, 2, 2. "Rate limiter" should be 3. Both copies and both runs. Drive's own import (#1101; evidence added there).

### TC-MD303 — long `.md` file names through EP-3, EP-5, EP-6, EP-7 (0/8 pass)

The long-name checks all pass, in both runs, for a 110-byte ASCII name and a 138-byte name of 45 × `議`:
- no `error`, no `failed` entry, no 403 `propertyLengthLimitExceeded`;
- `list_files` shows exactly one Doc per target folder;
- a second identical `sync_folder` call reports the file `skipped`;
- Drive keeps the full name, `.md` included, as the Doc title.

The cells fail on the meeting-notes rendering (TC-MD001's checklist):
- **EP-3:** #1071 (sub-bullets don't nest), #1093 (the Date/Attendees/Facilitator lines stay separate), #1098 (no spacing after the quote).
- **EP-5–7:** #1101.

### TC-MD401 — replacing a Doc that already has content (0/2 pass)

- **The replace checks pass, EP-2 and EP-4, both runs.** The r06 render over r07 is pixel-identical to r06 rendered into a blank Doc, and no table, list or styled paragraph of r07 remains.
- **The cells fail** because that r06 render fails TC-MD006's checklist: #1094, #1072, #1071, #1098.

### TC-MD402 — writing into a themed Doc (0/2 pass)

The theme takes effect on headings and body:
- Heading 1/2: Montserrat, blue, bold.
- Heading 3: Montserrat, gray, italic.
- Body: Georgia.
- Lists and numbering match the unthemed render, which itself fails #1071.
- r02 has no code, so "code stays Courier New" isn't exercised by this fixture.

**Added to #1097:** in the themed Doc every Timeline table cell, header and body, renders in the heading look (blue, bold Montserrat). In the unthemed Doc the body cells are plain. `get_doc_as_markdown` agrees, showing every cell bold only in the themed Doc. The table sits between `## Timeline` and `## Phases`, so this looks like #1097's "a table takes the style of an adjacent paragraph", hidden in an unthemed Doc. Not yet confirmed at the requests level.

### TC-MD403 — `update_doc_from_file` twice in a row (0/1 pass)

- **Idempotence passes, both runs.** The second render is pixel-identical to the first. `get_doc_structure` matches element for element: same count, types, indices, styles, text and nesting levels. The only differences are regenerated `headingId`/`listId` values, and no paragraphs or lists accumulate.
- **The cell fails** on the r10 render (TC-MD010): #1071, as in Phase 1.

### TC-MD404 — determinism across runs (FAIL)

Every page of every case and entry point in this run is identical between Run 1 and Run 2, with one exception: DS-05 EP-3. Its Run 2 call never returned and left an empty Doc.

**The hang:**
- The client's log for that server shows `create_doc_from_file` called at 04:34:18 UTC with no response or progress until the client's 1,800-second idle timeout aborted it at 05:04:30.
- The Doc had been created but no content was written.
- An immediate retry finished in 4 seconds.

That is #1129: `thread_http`'s per-thread `httplib2.Http()` has no socket timeout, so a request on a dead connection blocks until the OS gives up. #1129 described the path as "not observed"; this is an observation, and the stall lasted far longer than the 50–200 s `ETIMEDOUT` it anticipated. The cause isn't proven: no server log was configured for the run.

EP-8's code-font flip from Phases 1 and 2 (#1102) didn't recur here; DS-04's EP-8 code was monospace in both runs. Phase 1 and Phase 2's nondeterminism failures still stand, so TC-MD404 fails for the file as a whole.

## Issues

- **New:** #1173, D3 front matter (DS-14).
- **Evidence added:**
  - #1129: the observed hang; relabeled `enhancement` → `defect`. Its release is still open.
  - #1101: r12 numbering 1, 2, 2.
  - #1097: themed-Doc table cells take the heading style (TC-MD402), suspected to be the same cause.
- Every other failure above maps to an issue that already has Phase 1/2 evidence.

## Findings that weren't filed

- **Progress after completion:** the client log shows `Received a progress notification for an unknown token` twice. It was `upload_local_folder`'s per-file progress arriving after its request had already completed. Harmless as seen (the call succeeded); worth a look if it recurs.
- **Pagination:** EP-8 splits the r06 heading across a page break, and an EP-3 table header repeats across a page break. Keep-with-next behaviour, as in Phase 2.
- **`upload_local_folder` returns file names only, not file IDs,** so finding the created Doc takes an extra `list_files`.

## Process notes

- **Browser contention:** the shared Playwright browser was again the bottleneck. Shards waited up to 32 minutes for the lock. Parallel capture is tracked in the private planning project.
- **No lock incidents:** no stale-lock recoveries were needed. One shard read a 5-second-old lock as stale from a bad mtime read and correctly re-checked before touching it.
- **Playwright `filename` scripts must sit under the Playwright workspace root:** shard B kept its scripts in the ignored screenshot directory.
- **No denials and no #1052 connection resets.**

## Resource usage

| Shard | Prefix | Tokens | Tool uses | Wall time |
|---|---|---|---|---|
| A | `kai-oauth` | 333,592 | 358 | ~91 min (incl. the 30-min hang) |
| B | `oauth` | 397,476 | 425 | ~77 min |
| C | `kai-sa` | 538,578 | 204 | ~97 min |
| D | `sa` | 344,443 | 211 | ~65 min |
| Aziz (setup, checks, compile) | — | _not measured per step_ | | |

Total across shards: about 1.61M tokens.

## Maintainer decisions (2026-10-22)

- D3 front matter: new issue, #1173.
- Themed-table cells: evidence on #1097, not a separate issue.
- #1129: evidence comment and relabel to `defect`. Which release fixes it is still open.
- #1101: r12 numbering added as evidence.
- `docs_markdown.md`'s header: the gate is the _ornithomimus_ release, since v0.9.4 became the Pillow hotfix.
- DS-10/DS-13 EP-1/2/8: stay pending, not N/A and not tested another way.

## Next

Re-run the whole file (Phases 1–2 and this run) once the parser switch (#1116) and the engine choice (#1101) land.
