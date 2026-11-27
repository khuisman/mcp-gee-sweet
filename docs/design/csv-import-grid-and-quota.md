# CSV Import: Exact Grid Sizing and the Write Quota

**Date:** 2026-11-22
**Issue:** #1573
**Module:** `src/mcp_gee_sweet/tools/drive/files.py` (`import_csv_to_sheet`)

## Problem

`import_csv_to_sheet` refused any CSV over about 769k rows, whatever its width, with Sheets' "above the limit of 20000000 cells" error. It sized the grid to `max(rows, 1000)` × `max(columns, 26)`, so a narrow file still counted 26 cells a row (#1529's investigation: 800k × 1 and 1.05M × 10 both refused, while Drive's own import took 1.9M × 10).

Fixing the grid exposed a second ceiling the first one had hidden. The 800k × 1 file then got its grid, but 93 of its 160 chunk writes were refused with `429 RATE_LIMIT_EXCEEDED`: Sheets allows 60 write requests per minute per user, and every chunk was sent at once with no retry. Any import of more than 60 chunks (300k rows at 5,000 a chunk) failed partway, whatever its width.

## Measured live (2026-11-22, OAuth, Shared Drive)

Each measured on an empty spreadsheet by `updateSheetProperties`, twice:

| Grid change | Result |
|---|---|
| 1000×26 → 2,000,000 × 10, one request | refused: 52M cells |
| 1000×10 → 2,000,000 × 10 | accepted: the 20M limit includes 20M |
| 1000×10 → 2,000,001 × 10 | refused |
| 1000×26 → 1000 × 18,278 | accepted |
| 1000×26 → 1000 × 18,279 | refused: "above the limit of 18278 columns" |
| 1000×26 → 1,000,000 × 20, one request | refused as 26M cells |
| 1000×26 → 1,000,000 × 20, columns then rows as two requests in one batch | accepted |

So Sheets checks a row change against the sheet's *current* column count, even when the same request sets both. Exact sizing alone wouldn't have fixed the ticket: the narrow files it's about need their columns shrunk before their rows grow.

A small CSV imported through Drive's own conversion (`files.create` with a CSV body and the spreadsheet mimeType) keeps the default 1000×26 grid.

End to end through this branch's tool code (fresh interpreter, real services): the 800k × 1 file imported fully in 227 s, all 800,000 rows, grid 800,000 × 1.

## Decisions

**The grid is exactly the data's size on both axes**, never padded. The ticket asked for this. Drive pads a small file to 1000×26; we don't, because the padding counts against the workbook-wide limit, so a near-limit file would leave no room for even a second sheet. A short file now gets a short sheet. A column floor of 1 covers a file of blank lines (`csv` yields `[]` for each).

**Limits are checked before the spreadsheet is created** (`_csv_grid_limit_error`), so an oversized file leaves nothing behind. The orphan left by a *later* failure is #1574's.

**Column change first, as its own request** (`_grid_resize_requests`), in the same `batchUpdate` as the rename. From a fresh sheet the intermediate grid is 1000 × the new width, at most 18.3M cells, so it never trips the limit itself.

**A 429 is resent; nothing else is.** A 429 means Sheets refused the request and applied nothing. A 5xx or a timeout may have landed, and resending a values write is harmless in itself, but the codebase's rule is never to resend a write whose fate is unknown, so those still report in `failed_ranges`.

**One shared pause per import (`_RateLimitPause`), not a per-chunk backoff.** The quota is per user, so a 429 on one chunk means every chunk sent now would be refused too. With independent per-chunk backoff (the pattern `_copy_for_backup` uses for its single request), 100 waiting chunks would each wake on their own schedule and spend each new window's requests on refusals. Instead a 429 pauses every write. Every Sheets write of the import goes through `_RateLimitPause.send()`: the chunk writes, and the rename-and-resize `batchUpdate`, which now goes out on almost every import and counts against the same quota.

- **A reply to a request sent before the current pause began says nothing about the window the pause waits for.** Its 429 doesn't extend the pause, and its success doesn't reset the delay. A 429 on a request sent after it doubles the delay (5 s, capped at 60 s), and a success resets it. In round 1 any success reset the delay, so a late 200 from the earlier burst undid the doubling and the pause stayed near 5 s (PR #1589 QA round 1).
- **At most `_CSV_WRITE_CONCURRENCY` (4) writes are in flight.** `send()` holds a semaphore slot across the wait and the request. Without it, all 160 chunks passed the pause at once and queued for the default executor's threads (`min(32, cpu + 4)`), so most were sent later, during a pause, with a send time older than it: their 429s neither extended the pause nor were held back by it (PR #1589 QA round 1). 4 stays below the executor's smallest size, 5.
- **A pause never runs past the deadline**, 10 minutes after the pause object is made, just before the import's first write. A 429 at or after it is final, and the chunk reports it in `failed_ranges`, as before.
- **Starting a pause sends a progress update** ("Sheets write quota reached; waiting N s"), since a pause can last a minute with no chunk finishing, and a client that resets its timeout on progress would otherwise hear nothing.

**The limit check runs before the rows are padded**, so a refused file doesn't pay for building the padded copy.

## Known ceiling left (closed by #1577)

With 5,000-row chunks, a file needs `rows / 5000` writes at 60 a minute. At the 20M-cell limit a 10-column file is 400 chunks (about 7 minutes), inside the 10-minute budget; a 1-column file is 4,000 chunks (over an hour), so its rows past the budget come back in `failed_ranges`. Sizing chunks by cells as well as rows is the fix, and it's the same mechanism #1577 adds for bytes.

## Chunks sized by cells and bytes (#1577, 2026-11-24)

A fixed 5,000-row chunk was wrong at both ends: 3,000 rows of 40,000-character cells (120 MB) went as one request and timed out at 60 s with nothing written (#1529), and a narrow file made thousands of tiny writes. `_csv_chunks` now closes a chunk before a row would take it past `_CSV_CHUNK_MAX_CELLS` (200,000) cells or `_CSV_CHUNK_MAX_BYTES` (5 MB) of the request's `values` array. Bytes are counted as googleapiclient sends them, `json.dumps` with ASCII escaping, so a non-ASCII character counts 6 bytes and an astral one 12. A row is never split: a row over a budget on its own is a chunk of one row, at its own size. Splitting a row would mean column-range writes and column-aware `failed_ranges`. What makes a row that large is its total size, not any one cell: 100 cells of 50,000 characters, 2,000 columns of 2,500, or 10,000 of 500 all reach 5 MB. Such rows are each a lone chunk over the budget, up to four in flight at once, so a file of them can still time out (a known limitation, `docs/known-limitations.md`).

**Counting bytes without encoding (PR #1615 QA round 1).** Planning ran `json.dumps` once per row: 4.9 s for 2M one-column rows, about 49 s at the 20M-cell limit, with no progress update. `_row_json_bytes` counts a row arithmetically (its text, two quotes a cell, `, ` between cells, brackets) unless `_JSON_ESCAPED` finds a character `json.dumps` escapes, the same set as the json module's own `ESCAPE_ASCII` (anything outside space to `~`, DEL included, plus the quote and backslash), and only then encodes. It's checked against `json.dumps` for every ASCII character. Planning 2M one-column rows now takes about 1.5 s; prefix sums with bisect weren't faster, since the cost is per row. A file of 200,000 rows or more announces the planning step with a progress update first (`_CSV_PLAN_PROGRESS_ROWS`).

**A refused chunk is split (PR #1615 QA round 1).** Sheets refuses a whole `values.update` with a 400 when any one cell is over its 50,000-character limit, and writes none of it. With 5,000-row chunks one bad cell lost 5,000 rows; with 200k-cell chunks a narrow file under 200,000 cells is one chunk, so one bad cell sent the whole import down #1574's all-refused path and deleted the spreadsheet (observed live: 10,000 rows, one 50,001-character cell). Now a chunk of several rows refused with a 400 is split in half and each half resent, first half first, until the refused rows stand alone; one bad row in a 200,000-row chunk costs about 36 extra writes. Only a 400 splits: a 403 or 404 refuses every row alike, a final 429 is the quota, and a 5xx may have landed. `_CSV_SPLIT_MAX_WRITES` (100) caps the extra writes per import, so a 400 that every row would get can't multiply the import's writes; past it, a refused chunk is reported whole. A chunk reports one progress update whatever its splits, and `written_ranges` joins adjacent ranges, so a split chunk reads as the rows on either side of each refused row.

### Measured live (OAuth, Shared Drive, one `values.update` each)

One write at a time:

| Payload | Time |
|---|---|
| 50 cells, 2 MB | 3.3 s |
| 125 cells, 5 MB | 9.7 s |
| 250 cells, 10 MB | 18.9 s |
| 500 cells, 20 MB | 25.6 s |
| 200k cells × 1 column, 2.4 MB | 4.3 s |
| 500k cells, 6 MB | 9–11 s |
| 1M cells × 10 columns, 10.2 MB | 16.5 s |

Four at once into one spreadsheet, as the import sends them (`_CSV_WRITE_CONCURRENCY`), each write's time:

| Each write | Time each |
|---|---|
| 5 MB, 125 long cells | 12 s |
| 10 MB, 250 long cells | 38 s |
| 100k cells × 1 column | 4–5 s |
| 200k cells × 1 column | 8–9 s |
| 400k cells × 1 column | 31–34 s |
| 400k cells × 10 columns (40k rows) | 25–29 s |

Sheets doesn't serialize writes to one spreadsheet, but a write's time grows faster than its size under concurrency, and cells cost time on their own as well as bytes (400k short cells, 4.8 MB, took longer than 5 MB of long ones). So both budgets are needed, and each is set where four concurrent writes finish in about 10 s, well inside the 60 s default socket timeout.

### What it gives

- **The 120 MB file imports**: 25 chunks, all 3,000 rows, 172 s end to end through the tool code (fresh interpreter, real services).
- **A narrow file at the 20M-cell limit imports, in far fewer writes.** A 1-column file at the 20M-cell limit (20M rows, 189 MB) is 100 writes, not 4,000. Through the tool code it landed every row in 190 s: about 4 s a write from the first chunk to the last, so a write doesn't slow as the sheet fills. That is about 48 writes a minute, close to the 60-a-minute quota without reaching it (no pause), so the shared pause still matters, for a faster link or a second import from the same user. The 800k × 1 file of TC-D326 is 4 chunks now and no longer exercises the pause live.
- **A stall on Google's side still fails a chunk.** In one of two 20M × 1 runs, 10 consecutive chunks (rows 16.6M–18.6M) hit the 60 s timeout and the chunks after them landed; the other run showed the same kind of stall, every write in flight taking 12–14 s, for about 10 s. Smaller chunks don't help with that. A timed-out write may have landed, so it isn't resent (#1573's rule) and comes back in `failed_ranges`.
- **Chunk planning runs before the spreadsheet is created, off the loop** (`asyncio.to_thread`), since it encodes every row: a cancellation while it runs leaves nothing behind.
