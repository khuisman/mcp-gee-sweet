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

**One shared pause per import (`_RateLimitPause`), not a per-chunk backoff.** The quota is per user, so a 429 on one chunk means every chunk sent now would be refused too. With independent per-chunk backoff (the pattern `_copy_for_backup` uses for its single request), 100 waiting chunks would each wake on their own schedule and spend each new window's requests on refusals. Instead a 429 pauses every chunk. A 429 on a request sent *before* the current pause began doesn't extend it, since it was in flight when the pause started and says nothing new; one sent after it doubles the delay (5 s, capped at 60 s). Any success resets the delay. After 10 minutes of the import, a 429 is no longer retried and the chunk reports it in `failed_ranges`, as before.

## Known ceiling left

With 5,000-row chunks, a file needs `rows / 5000` writes at 60 a minute. At the 20M-cell limit a 10-column file is 400 chunks (about 7 minutes), inside the 10-minute budget; a 1-column file is 4,000 chunks (over an hour), so its rows past the budget come back in `failed_ranges`. Sizing chunks by cells as well as rows is the fix, and it's the same mechanism #1577 adds for bytes.
