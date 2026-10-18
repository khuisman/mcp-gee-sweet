### IC-01 — plain inline code

Run `make test` before pushing.

### IC-02 — code span containing a backtick

Use ``a ` b`` and `` `ticks` `` as literal text.

### IC-03 — code adjacent to formatting

**`bold code`**, *`italic code`*, `code`**bold**, and **bold**`code`.

### IC-04 — markdown inside code is literal

`**not bold**` and `[not a link](https://example.com)` and `<b>not html</b>`.

### IC-05 — code at start and end of a paragraph

`start` of the line, end of the line `end`

### IC-06 — paragraph that is only inline code

`only_code_here()`
