# Notes: read.py

## `get_multiple_spreadsheet_summary` — range notation (`read.py:207`)

```python
range_to_get = f"{sheet_info.title}!A1:{max_row}"
```

With `rows_to_fetch=5` and a sheet named "Budget", this produces:

```
Budget!A1:5
```

### What `A1:5` actually means

The Sheets API accepts `A1:5` and interprets it as "all columns, rows 1–5" — so in practice it likely returns data from every column, not just column A. But the notation is ambiguous: `A1:5` looks like it could mean `A1:A5` (column A only, rows 1–5).

The unambiguous equivalents would be:

- `Budget!1:5` — rows 1–5, all columns (explicit row-only range)
- `Budget!A1:Z5` — rows 1–5, columns A–Z (explicit column cap)

### Product decision needed

The current behavior probably works, but two questions worth resolving before PyPI:

1. **Does `A1:5` actually return all columns in production?** Needs a live check against a sheet with data in columns B, C, D, etc.
2. **Should the summary cap columns?** A sheet with 50 columns returns a lot of data in a "summary" call. If yes, pick a reasonable cap (e.g., `A:Z`) and switch to `f"{sheet_info.title}!A1:Z{max_row}"`.

This is a product decision, not a bug — the QA checklist item is a placeholder until that call is made.
